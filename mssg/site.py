"""构建流程：扫描 content/**/*.md → HTML，生成首页索引，拷贝静态资源，增量构建。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape as _xml_escape

from . import markdown as _md
from . import template as _tpl
from .frontmatter import split as _split_fm

_FIRST_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)

_PAGINATION_NAV = (
    "{% if pagination.multiple %}<nav>"
    '{% if pagination.has_prev %}<a href="{{ pagination.prev_url }}">上一页</a>'
    "{% endif %}"
    "<span>{{ pagination.page }} / {{ pagination.total_pages }}</span>"
    '{% if pagination.has_next %}<a href="{{ pagination.next_url }}">下一页</a>'
    "{% endif %}</nav>{% endif %}"
)

_TAG_FALLBACK = (
    "<!doctype html><html><head><meta charset=utf-8>"
    "<title>标签：{{ tag }}</title></head><body>"
    "<h1>标签：{{ tag }}</h1><ul>"
    "{% for p in pages %}"
    '<li>{{ p.date }} <a href="/{{ p.url }}">{{ p.title }}</a></li>'
    "{% endfor %}</ul>" + _PAGINATION_NAV + "</body></html>"
)

_ARCHIVE_FALLBACK = (
    "<!doctype html><html><head><meta charset=utf-8>"
    "<title>归档</title></head><body><h1>归档</h1>"
    "{% for g in groups %}<h2>{{ g.ym }}</h2><ul>"
    "{% for p in g.pages %}"
    '<li>{{ p.date }} <a href="/{{ p.url }}">{{ p.title }}</a></li>'
    "{% endfor %}</ul>{% endfor %}</body></html>"
)

_INDEX_FALLBACK = (
    "<!doctype html><html><head><meta charset=utf-8>"
    "<title>{{ site.title }}</title></head><body>"
    "<h1>{{ site.title }}</h1><ul>"
    "{% for p in pages %}"
    '<li>{{ p.date }} <a href="/{{ p.url }}">{{ p.title }}</a></li>'
    "{% endfor %}</ul>" + _PAGINATION_NAV + "</body></html>"
)


def _paginate(items: list, per_page) -> list[list]:
    """按每页数量切分；per_page <= 0 表示不分页。"""
    try:
        per_page = int(per_page or 0)
    except (TypeError, ValueError):
        per_page = 0
    if per_page <= 0:
        return [list(items)]
    return [list(items[i : i + per_page]) for i in range(0, len(items), per_page)] or [
        []
    ]


def _pagination_ctx(page: int, total: int, prev_rel, next_rel) -> dict:
    """分页上下文（模板变量 pagination）。"""
    return {
        "page": page,
        "total_pages": total,
        "multiple": total > 1,
        "has_prev": prev_rel is not None,
        "has_next": next_rel is not None,
        "prev_url": "/" + prev_rel if prev_rel else "",
        "next_url": "/" + next_rel if next_rel else "",
    }


def _sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_draft(value) -> bool:
    """front matter 的 draft 字段是否为真。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return False


def _atom_date(value) -> str:
    """日期转 RFC3339；无法解析则原样输出。"""
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return s


def _page_tags(page: dict) -> list:
    """取页面的标签列表（支持列表或逗号分隔字符串）。"""
    tags = page.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    return [str(t).strip() for t in tags if str(t).strip()]


class Site:
    def __init__(self, root: str | Path, config: str = "mssg.toml"):
        self.root = Path(root)
        self.config_name = config
        self.config_path = self.root / config
        self.cfg = self._load_config(config)

    def _load_config(self, config: str) -> dict:
        cfg = {
            "site": {"title": "My Site", "base_url": ""},
            "build": {
                "content_dir": "content",
                "template_dir": "templates",
                "static_dir": "static",
                "output_dir": "public",
                "drafts": False,
            },
        }
        path = self.root / config
        if path.exists():
            with open(path, "rb") as f:
                user = tomllib.load(f)
            for section in ("site", "build"):
                cfg[section].update(user.get(section, {}))
        return cfg

    # -- 对外接口 ------------------------------------------------------

    def build(self, force: bool = False, include_drafts: bool = False) -> dict:
        # 每次构建都重读配置：serve 监听时修改 mssg.toml 能立即生效
        self.cfg = self._load_config(self.config_name)
        b = self.cfg["build"]
        include_drafts = include_drafts or b.get("drafts", False)
        content_dir = self.root / b["content_dir"]
        template_dir = self.root / b["template_dir"]
        static_dir = self.root / b["static_dir"]
        output_dir = self.root / b["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)

        cache_path = output_dir / ".mssg" / "cache.json"
        cache = self._load_cache(cache_path)

        # 配置文件变化 → 强制全量重建
        config_digest = (
            _sha1_file(self.config_path) if self.config_path.exists() else ""
        )
        if cache.get("config") != config_digest:
            force = True

        templates = self._load_templates(template_dir)
        tpl_digest = (
            hashlib.sha1("".join(templates.values()).encode("utf-8")).hexdigest()
            if templates
            else ""
        )
        templates_changed = cache.get("templates") != tpl_digest

        pages = []
        rels = set()
        rebuilt_any = force or templates_changed
        if content_dir.is_dir():
            for md_path in sorted(content_dir.rglob("*.md")):
                rel = md_path.relative_to(content_dir).as_posix()
                rels.add(rel)
                url = rel[:-3] + ".html"
                digest = _sha1_file(md_path)
                try:
                    page = self._read_page(md_path, rel, url)
                except Exception as e:
                    raise ValueError("解析页面失败 %s：%s" % (rel, e))
                out_path = output_dir / url
                key = "page:" + rel
                if _is_draft(page.get("draft")) and not include_drafts:
                    # 草稿：不构建；清理之前可能已生成的旧输出
                    if out_path.exists():
                        out_path.unlink()
                        rebuilt_any = True
                    if cache.pop(key, None) is not None:
                        rebuilt_any = True
                    continue
                pages.append(page)
                if (
                    not force
                    and not templates_changed
                    and cache.get(key) == digest
                    and out_path.exists()
                ):
                    continue
                try:
                    self._render_page(page, templates, out_path)
                except Exception as e:
                    raise ValueError("渲染页面失败 %s：%s" % (rel, e))
                cache[key] = digest
                rebuilt_any = True

        # 清理已删除页面的残留：输出文件 + 缓存键；有删除则视为有更新，
        # 必须在渲染索引/标签页/feed 之前做，让它们用最新的 pages 重建
        for key in [k for k in cache if k.startswith("page:") and k[5:] not in rels]:
            del cache[key]
            stale_out = output_dir / (key[5:-3] + ".html")
            if stale_out.is_file():
                try:
                    stale_out.resolve().relative_to(output_dir.resolve())
                except ValueError:
                    continue  # 路径穿越保护
                stale_out.unlink()
            rebuilt_any = True

        pages.sort(key=lambda p: p["date"], reverse=True)
        # content/index.md 存在时，它就是首页，不再用自动索引覆盖
        has_home = any(p["url"] == "index.html" for p in pages)
        index_made: set = set()
        if not has_home:
            index_made = self._render_index(
                pages, templates, output_dir, rebuilt_any
            )
            self._clean_stale(output_dir, cache.get("index_files", []), index_made)
            cache["index_files"] = sorted(index_made)
        elif cache.get("index_files"):
            # 之前生成的分页文件现在不需要了（有了 content/index.md）
            self._clean_stale(output_dir, cache.pop("index_files"), set())

        tag_made: set = set()
        if b.get("tag_pages", True):
            tag_made = self._render_tag_pages(
                pages, templates, output_dir, rebuilt_any
            )
            self._clean_stale(output_dir, cache.get("tag_files", []), tag_made)
            cache["tag_files"] = sorted(tag_made)
        elif cache.get("tag_files"):
            self._clean_stale(output_dir, cache.pop("tag_files"), set())

        archive_rel = None
        if b.get("archive_page", True):
            archive_rel = self._render_archive(pages, templates, output_dir, rebuilt_any)
            self._clean_stale(output_dir, cache.get("archive_files", []), {archive_rel})
            cache["archive_files"] = [archive_rel]
        elif cache.get("archive_files"):
            self._clean_stale(output_dir, cache.pop("archive_files"), set())

        if b.get("feed", True):
            feed_rel = self._render_feed(pages, output_dir, rebuilt_any)
            self._clean_stale(output_dir, cache.get("feed_files", []), {feed_rel})
            cache["feed_files"] = [feed_rel]
        elif cache.get("feed_files"):
            self._clean_stale(output_dir, cache.pop("feed_files"), set())

        if b.get("sitemap", True):
            extra_paths = set(index_made) | set(tag_made)
            if archive_rel:
                extra_paths.add(archive_rel)
            extra = sorted(extra_paths - {"index.html"})
            sm_rel = self._render_sitemap(pages, output_dir, rebuilt_any, extra)
            self._clean_stale(output_dir, cache.get("sitemap_files", []), {sm_rel})
            cache["sitemap_files"] = [sm_rel]
        elif cache.get("sitemap_files"):
            self._clean_stale(output_dir, cache.pop("sitemap_files"), set())

        if static_dir.is_dir():
            new_static = set()
            for sp in sorted(static_dir.rglob("*")):
                if sp.is_file():
                    new_static.add(sp.relative_to(static_dir).as_posix())
            # 清理 static 里已删除的文件在输出目录中的残留
            for stale in set(cache.get("static_files", [])) - new_static:
                stale_path = output_dir / stale
                if stale_path.is_file():
                    try:
                        stale_path.resolve().relative_to(output_dir.resolve())
                    except ValueError:
                        continue  # 路径穿越保护
                    stale_path.unlink()
            shutil.copytree(static_dir, output_dir, dirs_exist_ok=True)
            cache["static_files"] = sorted(new_static)

        cache["templates"] = tpl_digest
        cache["config"] = config_digest
        self._save_cache(cache_path, cache)
        return {"pages": len(pages), "rebuilt": rebuilt_any}

    # -- 内部 ----------------------------------------------------------

    def _load_templates(self, template_dir: Path) -> dict:
        templates = {}
        if template_dir.is_dir():
            for tp in sorted(template_dir.rglob("*.html")):
                templates[tp.relative_to(template_dir).as_posix()] = tp.read_text(
                    encoding="utf-8"
                )
        return templates

    def _read_page(self, md_path: Path, rel: str, url: str) -> dict:
        text = md_path.read_text(encoding="utf-8-sig")
        meta, body = _split_fm(text)
        title = meta.get("title") or self._first_heading(body) or md_path.stem
        date = meta.get("date")
        if date is None:
            date = time.strftime(
                "%Y-%m-%d", time.localtime(md_path.stat().st_mtime)
            )
        page = {
            "title": title,
            "date": str(date),
            "content": _md.parse(body),
            "url": url,
        }
        for key, value in meta.items():
            if key not in page:
                page[key] = value
        return page

    @staticmethod
    def _first_heading(body: str) -> str:
        m = _FIRST_HEADING.search(body)
        return m.group(1).strip() if m else ""

    def _render_page(self, page: dict, templates: dict, out_path: Path) -> None:
        tpl_name = str(page.get("template", "page.html"))
        ctx = {"site": self.cfg["site"], "page": page}
        if tpl_name in templates:
            out = _tpl.render_template(tpl_name, ctx, templates.get)
        else:
            out = _tpl.render(
                "<!doctype html><html><head><meta charset=utf-8>"
                "<title>{{ page.title }}</title></head>"
                "<body>{{ page.content }}</body></html>",
                ctx,
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out, encoding="utf-8")

    def _render_index(
        self, pages: list, templates: dict, output_dir: Path, rebuilt_any: bool
    ) -> set:
        """渲染首页；per_page > 0 时分页为 page/2.html…，返回相对路径集合。"""
        per_page = self.cfg["build"].get("per_page", 0)
        chunks = _paginate(pages, per_page)
        total = len(chunks)
        made = set()
        for i, chunk in enumerate(chunks, start=1):
            rel = "index.html" if i == 1 else "page/%d.html" % i
            prev_rel = (
                None
                if i == 1
                else ("index.html" if i == 2 else "page/%d.html" % (i - 1))
            )
            next_rel = "page/%d.html" % (i + 1) if i < total else None
            ctx = {
                "site": self.cfg["site"],
                "pages": chunk,
                "pagination": _pagination_ctx(i, total, prev_rel, next_rel),
            }
            if "index.html" in templates:
                out = _tpl.render_template("index.html", ctx, templates.get)
            else:
                out = _tpl.render(_INDEX_FALLBACK, ctx)
            dest = output_dir / rel
            made.add(rel)
            if rebuilt_any or not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(out, encoding="utf-8")
        return made

    def _render_tag_pages(
        self, pages: list, templates: dict, output_dir: Path, rebuilt_any: bool
    ) -> set:
        """为每个标签生成 tags/<tag>.html（分页时还有 tags/<tag>/N.html）。

        返回生成文件的相对路径集合。
        """
        per_page = self.cfg["build"].get("per_page", 0)
        by_tag: dict[str, list] = {}
        for p in pages:
            for t in _page_tags(p):
                by_tag.setdefault(t, []).append(p)
        made = set()
        for tag in sorted(by_tag):
            tpages = sorted(by_tag[tag], key=lambda p: p["date"], reverse=True)
            chunks = _paginate(tpages, per_page)
            total = len(chunks)
            tag_q = quote(tag, safe="")
            for i, chunk in enumerate(chunks, start=1):
                if i == 1:
                    rel = "tags/%s.html" % tag_q
                    prev_rel = None
                else:
                    rel = "tags/%s/%d.html" % (tag_q, i)
                    prev_rel = (
                        "tags/%s.html" % tag_q
                        if i == 2
                        else "tags/%s/%d.html" % (tag_q, i - 1)
                    )
                next_rel = (
                    "tags/%s/%d.html" % (tag_q, i + 1) if i < total else None
                )
                ctx = {
                    "site": self.cfg["site"],
                    "tag": tag,
                    "pages": chunk,
                    "pagination": _pagination_ctx(i, total, prev_rel, next_rel),
                }
                if "tag.html" in templates:
                    out = _tpl.render_template("tag.html", ctx, templates.get)
                else:
                    out = _tpl.render(_TAG_FALLBACK, ctx)
                dest = output_dir / rel
                made.add(rel)
                if rebuilt_any or not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(out, encoding="utf-8")
        return made

    def _render_archive(
        self, pages: list, templates: dict, output_dir: Path, rebuilt_any: bool
    ) -> str:
        """生成 archive.html（按年月归档），返回相对路径。"""
        groups: dict[str, list] = {}
        for p in pages:
            groups.setdefault(str(p["date"])[:7], []).append(p)
        ordered = [
            {"ym": ym, "pages": sorted(ps, key=lambda p: p["date"], reverse=True)}
            for ym, ps in sorted(groups.items(), reverse=True)
        ]
        ctx = {"site": self.cfg["site"], "groups": ordered}
        if "archive.html" in templates:
            out = _tpl.render_template("archive.html", ctx, templates.get)
        else:
            out = _tpl.render(_ARCHIVE_FALLBACK, ctx)
        dest = output_dir / "archive.html"
        if rebuilt_any or not dest.exists():
            dest.write_text(out, encoding="utf-8")
        return "archive.html"

    def _render_feed(self, pages: list, output_dir: Path, rebuilt_any: bool) -> str:
        """生成 Atom 1.0 订阅 feed.xml（最近 20 篇），返回相对路径。"""
        base = self.cfg["site"].get("base_url", "").rstrip("/")
        entries = []
        for p in pages[:20]:
            url = (base + "/" + p["url"]) if base else "/" + p["url"]
            entries.append(
                "  <entry>\n"
                "    <title>%s</title>\n"
                '    <link href="%s"/>\n'
                "    <id>%s</id>\n"
                "    <updated>%s</updated>\n"
                '    <content type="html">%s</content>\n'
                "  </entry>"
                % (
                    _xml_escape(str(p["title"])),
                    _xml_escape(url, {'"': "&quot;"}),
                    _xml_escape(url),
                    _atom_date(p["date"]),
                    _xml_escape(str(p["content"])),
                )
            )
        if pages:
            updated = _atom_date(pages[0]["date"])
        else:
            updated = _atom_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        feed_url = (base + "/feed.xml") if base else "/feed.xml"
        site_id = base if base else "/"
        out = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<feed xmlns="http://www.w3.org/2005/Atom">\n'
            "  <title>%s</title>\n"
            '  <link href="%s"/>\n'
            '  <link rel="self" href="%s"/>\n'
            "  <updated>%s</updated>\n"
            "  <id>%s</id>\n"
            "%s\n"
            "</feed>\n"
            % (
                _xml_escape(str(self.cfg["site"].get("title", ""))),
                _xml_escape(feed_url, {'"': "&quot;"}),
                _xml_escape(feed_url, {'"': "&quot;"}),
                updated,
                _xml_escape(site_id),
                "\n".join(entries),
            )
        )
        dest = output_dir / "feed.xml"
        if rebuilt_any or not dest.exists():
            dest.write_text(out, encoding="utf-8")
        return "feed.xml"

    def _render_sitemap(
        self, pages: list, output_dir: Path, rebuilt_any: bool, extra=()
    ) -> str:
        """生成 sitemap.xml；extra 为分页等附加相对路径。返回相对路径。"""
        base = self.cfg["site"].get("base_url", "").rstrip("/")

        def abs_url(rel: str) -> str:
            return (base + "/" + rel) if base else "/" + rel

        entries = []
        seen = set()
        if pages:
            entries.append(("index.html", pages[0]["date"]))
            seen.add("index.html")
        for p in pages:
            # content/index.md 本身就是首页，去重避免 index.html 出现两次
            if p["url"] not in seen:
                seen.add(p["url"])
                entries.append((p["url"], p["date"]))
        index_date = pages[0]["date"] if pages else time.strftime("%Y-%m-%d")
        for rel in extra:
            if rel not in seen:
                seen.add(rel)
                entries.append((rel, index_date))
        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ]
        for rel, date in entries:
            lines.extend(
                [
                    "  <url>",
                    "    <loc>%s</loc>" % _xml_escape(abs_url(rel)),
                    "    <lastmod>%s</lastmod>" % _xml_escape(str(date)[:10]),
                    "  </url>",
                ]
            )
        lines.append("</urlset>")
        dest = output_dir / "sitemap.xml"
        if rebuilt_any or not dest.exists():
            dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return "sitemap.xml"

    @staticmethod
    def _clean_stale(output_dir: Path, old_files: list, made: set) -> None:
        """删除旧构建产物中已不再生成的残留文件（含路径穿越保护）。"""
        for stale in set(old_files) - made:
            stale_path = output_dir / stale
            if stale_path.is_file():
                try:
                    stale_path.resolve().relative_to(output_dir.resolve())
                except ValueError:
                    continue
                stale_path.unlink()

    @staticmethod
    def _load_cache(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _save_cache(path: Path, cache: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def new_site(name: str | Path) -> Path:
    """生成站点脚手架，返回站点根目录。目标为非空目录时拒绝覆盖。"""
    root = Path(name)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError("目录已存在且非空，拒绝覆盖：%s" % root)
    (root / "content").mkdir(parents=True, exist_ok=True)
    (root / "templates").mkdir(parents=True, exist_ok=True)
    (root / "static").mkdir(parents=True, exist_ok=True)

    (root / "mssg.toml").write_text(
        '[site]\ntitle = "我的小站"\nbase_url = ""\n'
        "\n[build]\n# per_page = 5  # 首页/标签页每页篇数；0 或不填则不分页\n"
        "# 分页文件：首页 page/2.html…，标签页 tags/<tag>/2.html…\n",
        encoding="utf-8",
    )

    (root / "templates" / "base.html").write_text(
        "<!doctype html>\n"
        '<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>{% block title %}{{ site.title }}{% endblock %}</title>\n"
        '<link rel="stylesheet" href="/style.css">\n'
        '<link rel="alternate" type="application/atom+xml" '
        'title="{{ site.title }}" href="/feed.xml">\n</head>\n<body>\n'
        '<header><h1><a href="/">{{ site.title }}</a></h1></header>\n'
        "<main>{% block content %}{% endblock %}</main>\n"
        "<footer><p>由 mssg 生成</p></footer>\n</body>\n</html>\n",
        encoding="utf-8",
    )
    (root / "templates" / "page.html").write_text(
        '{% extends "base.html" %}\n'
        "{% block title %}{{ page.title }} - {{ site.title }}{% endblock %}\n"
        "{% block content %}\n<h2>{{ page.title }}</h2>\n"
        "{% if page.date %}<p class=meta>{{ page.date }}</p>{% endif %}\n"
        "{{ page.content }}\n{% endblock %}\n",
        encoding="utf-8",
    )
    (root / "templates" / "index.html").write_text(
        '{% extends "base.html" %}\n'
        "{% block title %}{{ site.title }}{% endblock %}\n"
        "{% block content %}\n<h1>{{ site.title }}</h1>\n<ul>\n"
        "{% for p in pages %}\n"
        '<li>{{ p.date }} <a href="/{{ p.url }}">{{ p.title }}</a></li>\n'
        "{% endfor %}\n</ul>\n"
        "{% if pagination.multiple %}\n<nav>\n"
        '{% if pagination.has_prev %}<a href="{{ pagination.prev_url }}">上一页</a>\n'
        "{% endif %}"
        "<span>{{ pagination.page }} / {{ pagination.total_pages }}</span>\n"
        '{% if pagination.has_next %}<a href="{{ pagination.next_url }}">下一页</a>\n'
        "{% endif %}</nav>\n{% endif %}"
        "{% endblock %}\n",
        encoding="utf-8",
    )
    (root / "templates" / "tag.html").write_text(
        '{% extends "base.html" %}\n'
        "{% block title %}标签：{{ tag }} - {{ site.title }}{% endblock %}\n"
        "{% block content %}\n<h1>标签：{{ tag }}</h1>\n<ul>\n"
        "{% for p in pages %}\n"
        '<li>{{ p.date }} <a href="/{{ p.url }}">{{ p.title }}</a></li>\n'
        "{% endfor %}\n</ul>\n"
        "{% if pagination.multiple %}\n<nav>\n"
        '{% if pagination.has_prev %}<a href="{{ pagination.prev_url }}">上一页</a>\n'
        "{% endif %}"
        "<span>{{ pagination.page }} / {{ pagination.total_pages }}</span>\n"
        '{% if pagination.has_next %}<a href="{{ pagination.next_url }}">下一页</a>\n'
        "{% endif %}</nav>\n{% endif %}"
        "{% endblock %}\n",
        encoding="utf-8",
    )
    (root / "templates" / "archive.html").write_text(
        '{% extends "base.html" %}\n'
        "{% block title %}归档 - {{ site.title }}{% endblock %}\n"
        "{% block content %}\n<h1>归档</h1>\n"
        "{% for g in groups %}\n<h2>{{ g.ym }}</h2>\n<ul>\n"
        "{% for p in g.pages %}\n"
        '<li>{{ p.date }} <a href="/{{ p.url }}">{{ p.title }}</a></li>\n'
        "{% endfor %}\n</ul>\n{% endfor %}\n{% endblock %}\n",
        encoding="utf-8",
    )
    (root / "content" / "hello.md").write_text(
        "---\ntitle: 你好，世界\ndate: 2026-10-02\ntags: [mssg, 示例]\n---\n\n"
        "# 你好，世界\n\n这是用 **mssg** 生成的第一篇文章。\n\n"
        "- 零依赖，只用 Python 标准库\n- 自研 Markdown 解析器\n- 自研模板引擎\n\n"
        "> 纸上得来终觉浅，绝知此事要躬行。\n",
        encoding="utf-8",
    )
    (root / "content" / "draft.md").write_text(
        "---\ntitle: 草稿示例\ndate: 2026-10-03\ndraft: true\n---\n\n"
        "# 草稿示例\n\n这篇是草稿，`mssg build` 默认跳过，\n"
        "`mssg build --drafts` 才会构建它。\n",
        encoding="utf-8",
    )
    (root / "static" / "style.css").write_text(
        "body{max-width:42em;margin:2em auto;padding:0 1em;"
        "font-family:serif;line-height:1.8;color:#222}\n"
        "a{color:#0645ad}\n.meta{color:#888;font-size:.9em}\n"
        "pre{background:#f4f4f4;padding:1em;overflow:auto}\n"
        "code{background:#f4f4f4;padding:0 .3em}\n"
        "pre code{background:none;padding:0}\n"
        "table{border-collapse:collapse}\n"
        "th,td{border:1px solid #ccc;padding:.3em .8em}\n"
        "blockquote{border-left:3px solid #ccc;margin-left:0;padding-left:1em;color:#555}\n",
        encoding="utf-8",
    )
    return root
