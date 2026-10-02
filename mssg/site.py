"""构建流程：扫描 content/**/*.md → HTML，生成首页索引，拷贝静态资源，增量构建。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from . import markdown as _md
from . import template as _tpl
from .frontmatter import split as _split_fm

_FIRST_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)
_HEADING_RE = re.compile(r"^#{1,6}\s+")
_TITLE_TAG_RE = re.compile(r"<[^>]*>")


def _clean_title(md_text: str) -> str:
    """从 Markdown 标题行提取纯文本（去掉 ** 等行内标记）。"""
    html = _md.parse(md_text)
    plain = _TITLE_TAG_RE.sub("", html)
    return plain.strip()

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

_CATEGORY_FALLBACK = (
    "<!doctype html><html><head><meta charset=utf-8>"
    "<title>分类：{{ category }}</title></head><body>"
    "<h1>分类：{{ category }}</h1><ul>"
    "{% for p in pages %}"
    '<li>{{ p.date }} <a href="/{{ p.url }}">{{ p.title }}</a></li>'
    "{% endfor %}</ul>" + _PAGINATION_NAV + "</body></html>"
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


def _tag_slug(tag: str) -> str:
    """标签转 URL/文件名单：保留 Unicode 可读性，只中和路径分隔符。

    不用百分号编码做文件名——编码后的文件名经 HTTP 服务器 URL 解码后
    反而找不到文件（如 tags/%E6%BC%94.html 请求会被解码为 tags/演.html）。
    """
    slug = tag.replace("/", "-").replace("\\", "-").strip()
    slug = "".join(c for c in slug if c.isprintable()).strip(".")
    return slug or "tag"


def _page_tags(page: dict) -> list:
    """取页面的标签列表（支持列表、逗号分隔字符串或单个标量）。"""
    tags = page.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    elif not isinstance(tags, (list, tuple)):
        tags = [tags]
    return [str(t).strip() for t in tags if str(t).strip()]


def _page_categories(page: dict) -> list:
    """取页面的分类列表（同 tags 的三种写法）。"""
    cats = page.get("categories", page.get("category", []))
    if isinstance(cats, str):
        cats = [c.strip() for c in cats.split(",")]
    elif not isinstance(cats, (list, tuple)):
        cats = [cats]
    return [str(c).strip() for c in cats if str(c).strip()]


_MORE_MARKER = "<!--more-->"


def _split_summary(body_md: str) -> tuple:
    """摘要：<!--more--> 之前的内容；没有标记则取首段。

    返回 (summary_html, summary_text)。
    """
    if _MORE_MARKER in body_md:
        head = body_md.split(_MORE_MARKER, 1)[0]
    else:
        # 首段 fallback：跳过开头的标题行，取第一个真正的段落
        lines = []
        started = False
        for ln in body_md.split("\n"):
            s = ln.strip()
            if not started:
                if not s or _HEADING_RE.match(s):
                    continue
                started = True
            if not s:
                break
            lines.append(ln)
        head = "\n".join(lines)
    html_sum = _md.parse(head)
    text = _TITLE_TAG_RE.sub("", html_sum)
    text = re.sub(r"\s+", " ", text).strip()
    return html_sum, text[:200]


def _rss_date(value) -> str:
    """日期转 RFC822（RSS pubDate）；无法解析则原样输出。"""
    from email.utils import formatdate
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return formatdate(dt.timestamp(), usegmt=True)
        except ValueError:
            continue
    return s


class Site:
    def __init__(self, root: str | Path, config: str = "mssg.toml"):
        self.root = Path(root)
        self.config_name = config
        self.config_path = self.root / config
        self.cfg = self._load_config(config)
        self._data: dict = {}

    def _ctx(self, **kw) -> dict:
        """模板公共上下文：site + data + 调用方变量。"""
        ctx = {"site": self.cfg["site"], "data": self._data}
        ctx.update(kw)
        return ctx

    def _load_data(self, data_dir: Path) -> dict:
        """加载 data/ 下的 .json/.toml 数据文件，供模板使用。"""
        data = {}
        if data_dir.is_dir():
            for dp in sorted(data_dir.iterdir()):
                if not dp.is_file():
                    continue
                try:
                    if dp.suffix == ".json":
                        data[dp.stem] = json.loads(
                            dp.read_text(encoding="utf-8")
                        )
                    elif dp.suffix == ".toml":
                        with open(dp, "rb") as f:
                            data[dp.stem] = tomllib.load(f)
                    else:
                        continue
                except Exception as e:
                    raise ValueError("数据文件解析失败 %s：%s" % (dp.name, e))
        return data

    def _load_config(self, config: str) -> dict:
        cfg = {
            "site": {
                "title": "My Site",
                "base_url": "",
                "description": "",
                # 公司站各节：缺了也不让模板炸，给空默认值
                "menu": [],
                "hero": {},
                "features": [],
                "contact": {},
                "footer": {},
            },
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
        # 指纹计入文件名 + 内容：重命名模板也能触发重建
        tpl_digest = (
            hashlib.sha1(
                "".join(
                    "%s\x00%s" % (name, src) for name, src in templates.items()
                ).encode("utf-8")
            ).hexdigest()
            if templates
            else ""
        )
        templates_changed = cache.get("templates") != tpl_digest

        # data/ 数据文件变化同样触发全量重建
        self._data = self._load_data(self.root / b.get("data_dir", "data"))
        data_digest = hashlib.sha1(
            json.dumps(self._data, ensure_ascii=False, sort_keys=True,
                       default=str).encode("utf-8")
        ).hexdigest()
        data_changed = cache.get("data") != data_digest
        cache["data"] = data_digest
        global_changed = templates_changed or data_changed

        pages = []
        rels = set()
        rebuilt_any = force or global_changed
        render_jobs = []  # (page, out_path, key, digest)
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
                    and not global_changed
                    and cache.get(key) == digest
                    and out_path.exists()
                ):
                    continue
                render_jobs.append((page, out_path, key, digest, rel))

        # 页面渲染并行化（IO 密集，线程池足够；写缓存串行）
        if render_jobs:
            def _do_render(job):
                page, out_path, key, digest, rel = job
                try:
                    self._render_page(page, templates, out_path)
                except Exception as e:
                    return (key, digest, "渲染页面失败 %s：%s" % (rel, e))
                return (key, digest, None)

            workers = min(8, (os.cpu_count() or 2))
            with ThreadPoolExecutor(max_workers=workers) as ex:
                for key, digest, err in ex.map(_do_render, render_jobs):
                    if err:
                        raise ValueError(err)
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
            # 之前生成的分页文件现在不需要了（有了 content/index.md）；
            # index.html 现在由 content/index.md 生成，不在此删除
            self._clean_stale(
                output_dir,
                [f for f in cache.pop("index_files") if f != "index.html"],
                set(),
            )

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

        cat_made: set = set()
        if b.get("category_pages", True):
            cat_made = self._render_category_pages(
                pages, templates, output_dir, rebuilt_any
            )
            self._clean_stale(output_dir, cache.get("category_files", []), cat_made)
            cache["category_files"] = sorted(cat_made)
        elif cache.get("category_files"):
            self._clean_stale(output_dir, cache.pop("category_files"), set())

        if b.get("feed", True):
            feed_rel = self._render_feed(pages, output_dir, rebuilt_any)
            self._clean_stale(output_dir, cache.get("feed_files", []), {feed_rel})
            cache["feed_files"] = [feed_rel]
        elif cache.get("feed_files"):
            self._clean_stale(output_dir, cache.pop("feed_files"), set())

        if b.get("rss", True):
            rss_rel = self._render_rss(pages, output_dir, rebuilt_any)
            self._clean_stale(output_dir, cache.get("rss_files", []), {rss_rel})
            cache["rss_files"] = [rss_rel]
        elif cache.get("rss_files"):
            self._clean_stale(output_dir, cache.pop("rss_files"), set())

        if b.get("robots", True):
            robots_rel = self._render_robots(output_dir, rebuilt_any)
            self._clean_stale(output_dir, cache.get("robots_files", []), {robots_rel})
            cache["robots_files"] = [robots_rel]
        elif cache.get("robots_files"):
            self._clean_stale(output_dir, cache.pop("robots_files"), set())

        if b.get("sitemap", True):
            extra_paths = set(index_made) | set(tag_made) | set(cat_made)
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
        if not date:
            date = time.strftime(
                "%Y-%m-%d", time.localtime(md_path.stat().st_mtime)
            )
        page = {
            "title": title,
            "date": str(date),
            "content": _md.parse(body),
            "url": url,
        }
        summary_html, summary_text = _split_summary(body)
        page["summary"] = summary_html
        page["summary_text"] = summary_text
        page["toc"] = _md.extract_toc(body)
        for key, value in meta.items():
            if key not in page:
                page[key] = value
        return page

    @staticmethod
    def _first_heading(body: str) -> str:
        m = _FIRST_HEADING.search(body)
        return _clean_title(m.group(1)) if m else ""

    def _render_page(self, page: dict, templates: dict, out_path: Path) -> None:
        tpl_name = str(page.get("template", "page.html"))
        ctx = self._ctx(page=page)
        if tpl_name in templates:
            out = _tpl.render_template(tpl_name, ctx, templates)
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
            ctx = self._ctx(
                pages=chunk,
                pagination=_pagination_ctx(i, total, prev_rel, next_rel),
            )
            if "index.html" in templates:
                out = _tpl.render_template("index.html", ctx, templates)
            else:
                out = _tpl.render(_INDEX_FALLBACK, ctx)
            dest = output_dir / rel
            made.add(rel)
            if rebuilt_any or not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(out, encoding="utf-8")
        return made

    def _render_taxonomy(
        self, pages: list, templates: dict, output_dir: Path, rebuilt_any: bool,
        *, get_terms, dirname: str, tpl_name: str, fallback: str,
        var_name: str, label: str,
    ) -> set:
        """通用分类法页面：terms/<slug>.html（分页时还有 terms/<slug>/N.html）。

        get_terms(page) -> 该页的词条列表；var_name 为模板中词条变量名。
        返回生成文件的相对路径集合。
        """
        per_page = self.cfg["build"].get("per_page", 0)
        by_term: dict[str, list] = {}
        for p in pages:
            for t in get_terms(p):
                by_term.setdefault(t, []).append(p)
        made = set()
        # 先算 slug：不同词条撞车时加 -2/-3 后缀区分
        slugs: dict[str, str] = {}
        used: set[str] = set()
        for term in sorted(by_term):
            base = _tag_slug(term)
            slug = base
            n = 2
            while slug in used:
                slug = "%s-%d" % (base, n)
                n += 1
            used.add(slug)
            slugs[term] = slug
        for term in sorted(by_term):
            tpages = sorted(by_term[term], key=lambda p: p["date"], reverse=True)
            chunks = _paginate(tpages, per_page)
            total = len(chunks)
            tag_q = slugs[term]
            for i, chunk in enumerate(chunks, start=1):
                if i == 1:
                    rel = "%s/%s.html" % (dirname, tag_q)
                    prev_rel = None
                else:
                    rel = "%s/%s/%d.html" % (dirname, tag_q, i)
                    prev_rel = (
                        "%s/%s.html" % (dirname, tag_q)
                        if i == 2
                        else "%s/%s/%d.html" % (dirname, tag_q, i - 1)
                    )
                next_rel = (
                    "%s/%s/%d.html" % (dirname, tag_q, i + 1) if i < total else None
                )
                ctx = self._ctx(
                    **{var_name: term},
                    pages=chunk,
                    pagination=_pagination_ctx(i, total, prev_rel, next_rel),
                )
                if tpl_name in templates:
                    out = _tpl.render_template(tpl_name, ctx, templates)
                else:
                    out = _tpl.render(fallback, ctx)
                dest = output_dir / rel
                made.add(rel)
                if rebuilt_any or not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(out, encoding="utf-8")
        return made

    def _render_tag_pages(
        self, pages: list, templates: dict, output_dir: Path, rebuilt_any: bool
    ) -> set:
        """为每个标签生成 tags/<tag>.html（分页时还有 tags/<tag>/N.html）。"""
        return self._render_taxonomy(
            pages, templates, output_dir, rebuilt_any,
            get_terms=_page_tags, dirname="tags", tpl_name="tag.html",
            fallback=_TAG_FALLBACK, var_name="tag", label="标签",
        )

    def _render_category_pages(
        self, pages: list, templates: dict, output_dir: Path, rebuilt_any: bool
    ) -> set:
        """为每个分类生成 categories/<cat>.html（分页时还有 categories/<cat>/N.html）。"""
        return self._render_taxonomy(
            pages, templates, output_dir, rebuilt_any,
            get_terms=_page_categories, dirname="categories",
            tpl_name="category.html", fallback=_CATEGORY_FALLBACK,
            var_name="category", label="分类",
        )

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
        ctx = self._ctx(groups=ordered)
        if "archive.html" in templates:
            out = _tpl.render_template("archive.html", ctx, templates)
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

    def _render_rss(self, pages: list, output_dir: Path, rebuilt_any: bool) -> str:
        """生成 RSS 2.0 订阅 feed_rss.xml（最近 20 篇），返回相对路径。"""
        base = self.cfg["site"].get("base_url", "").rstrip("/")
        items = []
        for p in pages[:20]:
            url = (base + "/" + p["url"]) if base else "/" + p["url"]
            items.append(
                "  <item>\n"
                "    <title>%s</title>\n"
                "    <link>%s</link>\n"
                "    <guid>%s</guid>\n"
                "    <pubDate>%s</pubDate>\n"
                "    <description>%s</description>\n"
                "  </item>"
                % (
                    _xml_escape(str(p["title"])),
                    _xml_escape(url),
                    _xml_escape(url),
                    _rss_date(p["date"]),
                    _xml_escape(str(p.get("summary_text", ""))),
                )
            )
        if pages:
            pub = _rss_date(pages[0]["date"])
        else:
            pub = _rss_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        feed_url = (base + "/feed_rss.xml") if base else "/feed_rss.xml"
        out = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<rss version="2.0">\n'
            " <channel>\n"
            "  <title>%s</title>\n"
            '  <link>%s</link>\n'
            "  <description>%s</description>\n"
            "  <pubDate>%s</pubDate>\n"
            "%s\n"
            " </channel>\n"
            "</rss>\n"
            % (
                _xml_escape(str(self.cfg["site"].get("title", ""))),
                _xml_escape(feed_url),
                _xml_escape(str(self.cfg["site"].get("title", ""))),
                pub,
                "\n".join(items),
            )
        )
        dest = output_dir / "feed_rss.xml"
        if rebuilt_any or not dest.exists():
            dest.write_text(out, encoding="utf-8")
        return "feed_rss.xml"

    def _render_robots(self, output_dir: Path, rebuilt_any: bool) -> str:
        """生成 robots.txt，返回相对路径。"""
        base = self.cfg["site"].get("base_url", "").rstrip("/")
        lines = ["User-agent: *", "Allow: /"]
        if base:
            lines.append("Sitemap: %s/sitemap.xml" % base)
        dest = output_dir / "robots.txt"
        if rebuilt_any or not dest.exists():
            dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return "robots.txt"

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
    """生成公司官网级站点脚手架，返回站点根目录。目标为非空目录时拒绝覆盖。

    换肤不需要改模板：导航菜单、hero、特性卡、联系方式、页脚文字
    都在 mssg.toml 里配置。
    """
    root = Path(name)
    if root.is_file():
        raise FileExistsError("目标已存在且为文件，拒绝覆盖：%s" % root)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError("目录已存在且非空，拒绝覆盖：%s" % root)
    (root / "content").mkdir(parents=True, exist_ok=True)
    (root / "templates").mkdir(parents=True, exist_ok=True)
    (root / "static").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)

    (root / "data" / "links.json").write_text(
        '{\n  "items": [\n    {"name": "示例", "url": "https://example.com"}\n  ]\n}\n',
        encoding="utf-8",
    )

    (root / "mssg.toml").write_text(
        """\
[site]
title = "星尘科技"
description = "星尘科技专注于云端协作工具，帮小团队把想法快速变成产品。"
base_url = ""

# 导航菜单（按 weight 排序）
[[site.menu]]
name = "首页"
url = "/"
weight = 1
[[site.menu]]
name = "产品"
url = "/products.html"
weight = 2
[[site.menu]]
name = "新闻"
url = "/#news"
weight = 3
[[site.menu]]
name = "关于"
url = "/about.html"
weight = 4

# 首页 hero 区
[site.hero]
title = "把想法变成产品"
subtitle = "开箱即用的协作工具，让小团队也能有大公司的效率。"
cta_text = "了解产品"
cta_url = "/products.html"
cta2_text = "联系我们"
cta2_url = "/about.html#contact"

# 首页特性卡片（增删改后重新 build 即可）
[[site.features]]
title = "开箱即用"
text = "一行命令建站，一次构建上线，不写一行后端代码。"
[[site.features]]
title = "极速构建"
text = "增量构建只重建改动过的页面，改完即刻预览。"
[[site.features]]
title = "SEO 友好"
text = "语义化 HTML、sitemap、RSS、Open Graph 标签开箱即备。"

# 联系方式（页脚与关于页共用）
[site.contact]
email = "hi@example.com"
phone = "400-000-0000"

[site.footer]
text = "© 2026 星尘科技"

[build]
# per_page = 5  # 首页/标签页每页篇数；0 或不填则不分页
# 分页文件：首页 page/2.html…，标签页 tags/<tag>/2.html…
""",
        encoding="utf-8",
    )

    (root / "templates" / "base.html").write_text(
        """\
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}{{ site.title }}{% endblock %}</title>
{% block meta %}
<meta name="description" content="{{ site.description }}">
<meta property="og:title" content="{{ site.title }}">
<meta property="og:description" content="{{ site.description }}">
<meta property="og:type" content="website">
{% if site.base_url %}<meta property="og:url" content="{{ site.base_url }}/{{ page.url if page else '' }}">{% endif %}
<meta name="twitter:card" content="summary">
{% endblock %}
<link rel="stylesheet" href="/style.css">
<link rel="alternate" type="application/atom+xml" title="{{ site.title }}" href="/feed.xml">
</head>
<body>
<header class="site-header">
<div class="wrap nav">
<a class="brand" href="/">{{ site.title }}</a>
<nav>
{% for m in site.menu|sort(attribute="weight") %}<a href="{{ m.url }}">{{ m.name }}</a>{% endfor %}
</nav>
</div>
</header>
<main>{% block content %}{% endblock %}</main>
<footer class="site-footer">
<div class="wrap">
<p>{{ site.footer.text }} · 由 mssg 生成</p>
{% if site.contact.email %}<p>联系：<a href="mailto:{{ site.contact.email }}">{{ site.contact.email }}</a>{% if site.contact.phone %} · {{ site.contact.phone }}{% endif %}</p>{% endif %}
</div>
</footer>
</body>
</html>
""",
        encoding="utf-8",
    )
    (root / "templates" / "page.html").write_text(
        """\
{% extends "base.html" %}
{% block title %}{{ page.title }} - {{ site.title }}{% endblock %}
{% block meta %}<meta name="description" content="{{ page.summary_text }}">
<meta property="og:title" content="{{ page.title }} - {{ site.title }}">
<meta property="og:description" content="{{ page.summary_text }}">
<meta property="og:type" content="article">
{% endblock %}
{% block content %}
<div class="wrap article">
<h1>{{ page.title }}</h1>
{% if page.date %}<p class="meta">{{ page.date }}</p>{% endif %}
{% if page.toc %}
<nav class="toc"><ul>
{% for h in page.toc %}<li class="toc{{ h.level }}"><a href="#{{ h.id }}">{{ h.text }}</a></li>
{% endfor %}
</ul></nav>
{% endif %}
{{ page.content }}
</div>
{% endblock %}
""",
        encoding="utf-8",
    )
    (root / "templates" / "index.html").write_text(
        """\
{% extends "base.html" %}
{% block content %}
<section class="hero">
<div class="wrap">
<h1>{{ site.hero.title }}</h1>
<p class="lede">{{ site.hero.subtitle }}</p>
<p class="cta-row">
<a class="btn" href="{{ site.hero.cta_url }}">{{ site.hero.cta_text }}</a>
{% if site.hero.cta2_text %}<a class="btn ghost" href="{{ site.hero.cta2_url }}">{{ site.hero.cta2_text }}</a>{% endif %}
</p>
</div>
</section>
<section class="features">
<div class="wrap">
<div class="cards">
{% for f in site.features %}
<div class="card"><h3>{{ f.title }}</h3><p>{{ f.text }}</p></div>
{% endfor %}
</div>
</div>
</section>
<section class="news" id="news">
<div class="wrap">
<h2>新闻动态</h2>
<ul class="post-list">
{% for p in pages[:5] %}
<li><span class="date">{{ p.date }}</span> <a href="/{{ p.url }}">{{ p.title }}</a></li>
{% endfor %}
</ul>
<p><a href="/archive.html">全部归档 →</a></p>
{% if pagination.multiple %}
<nav class="pager">
{% if pagination.has_prev %}<a href="{{ pagination.prev_url }}">← 上一页</a>{% endif %}
<span>{{ pagination.page }} / {{ pagination.total_pages }}</span>
{% if pagination.has_next %}<a href="{{ pagination.next_url }}">下一页 →</a>{% endif %}
</nav>
{% endif %}
</div>
</section>
{% endblock %}
""",
        encoding="utf-8",
    )
    (root / "templates" / "tag.html").write_text(
        """\
{% extends "base.html" %}
{% block title %}标签：{{ tag }} - {{ site.title }}{% endblock %}
{% block content %}
<div class="wrap article">
<h1>标签：{{ tag }}</h1>
<ul class="post-list">
{% for p in pages %}
<li><span class="date">{{ p.date }}</span> <a href="/{{ p.url }}">{{ p.title }}</a></li>
{% endfor %}
</ul>
{% if pagination.multiple %}
<nav class="pager">
{% if pagination.has_prev %}<a href="{{ pagination.prev_url }}">上一页</a>{% endif %}
<span>{{ pagination.page }} / {{ pagination.total_pages }}</span>
{% if pagination.has_next %}<a href="{{ pagination.next_url }}">下一页</a>{% endif %}
</nav>
{% endif %}
</div>
{% endblock %}
""",
        encoding="utf-8",
    )
    (root / "templates" / "category.html").write_text(
        """\
{% extends "base.html" %}
{% block title %}分类：{{ category }} - {{ site.title }}{% endblock %}
{% block content %}
<div class="wrap article">
<h1>分类：{{ category }}</h1>
<ul class="post-list">
{% for p in pages %}
<li><span class="date">{{ p.date }}</span> <a href="/{{ p.url }}">{{ p.title }}</a></li>
{% endfor %}
</ul>
</div>
{% endblock %}
""",
        encoding="utf-8",
    )
    (root / "templates" / "archive.html").write_text(
        """\
{% extends "base.html" %}
{% block title %}归档 - {{ site.title }}{% endblock %}
{% block content %}
<div class="wrap article">
<h1>归档</h1>
{% for g in groups %}
<h2>{{ g.ym }}</h2>
<ul class="post-list">
{% for p in g.pages %}
<li><span class="date">{{ p.date }}</span> <a href="/{{ p.url }}">{{ p.title }}</a></li>
{% endfor %}
</ul>
{% endfor %}
</div>
{% endblock %}
""",
        encoding="utf-8",
    )
    (root / "content" / "about.md").write_text(
        """\
---
title: 关于我们
date: 2026-10-02
---

# 关于我们

星尘科技是一家专注于云端协作工具的公司，目标是让小团队也能有大公司的效率。

## 联系方式 {#contact}

- 邮箱：hi@example.com
- 电话：400-000-0000

欢迎随时联系我们。
""",
        encoding="utf-8",
    )
    (root / "content" / "products.md").write_text(
        """\
---
title: 产品介绍
date: 2026-10-02
---

# 产品介绍

## 星尘协作

为小团队打造的一站式协作平台：

- 任务看板，开箱即用
- 文档与知识库二合一
- 秒级构建的静态站点发布

```python
print("你好，星尘")
```

> 纸上得来终觉浅，绝知此事要躬行。
""",
        encoding="utf-8",
    )
    (root / "content" / "hello.md").write_text(
        """\
---
title: 你好，世界
date: 2026-10-02
tags: [mssg, 示例]
---

# 你好，世界

这是用 **mssg** 生成的第一篇文章。

- Markdown（含表格、脚注、代码高亮）
- Jinja2 模板（继承、循环、过滤器）
- YAML front matter
""",
        encoding="utf-8",
    )
    (root / "content" / "draft.md").write_text(
        """\
---
title: 草稿示例
date: 2026-10-03
draft: true
---

# 草稿示例

这篇是草稿，`mssg build` 默认跳过，
`mssg build --drafts` 才会构建它。
""",
        encoding="utf-8",
    )
    (root / "static" / "style.css").write_text(
        """\
:root{
  --primary:#1d4ed8; --primary-dark:#1e40af;
  --ink:#1f2937; --muted:#6b7280; --line:#e5e7eb;
  --bg:#ffffff; --soft:#f3f4f6; --card:#ffffff;
}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.8;color:var(--ink);background:var(--bg)}
a{color:var(--primary);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:64rem;margin:0 auto;padding:0 1.25rem}
/* 导航 */
.site-header{position:sticky;top:0;background:rgba(255,255,255,.96);
  border-bottom:1px solid var(--line);z-index:10}
.site-header .nav{display:flex;align-items:center;justify-content:space-between;
  padding:.9rem 1.25rem;flex-wrap:wrap;gap:.5rem}
.brand{font-size:1.25rem;font-weight:700;color:var(--ink)}
.brand:hover{text-decoration:none}
.site-header nav a{margin-left:1.25rem;color:var(--ink);font-size:.95rem}
.site-header nav a:hover{color:var(--primary)}
/* hero */
.hero{background:linear-gradient(135deg,#1e3a8a,#1d4ed8 60%,#3b82f6);
  color:#fff;padding:4.5rem 0;text-align:center}
.hero h1{font-size:2.4rem;margin:0 0 1rem;line-height:1.3}
.hero .lede{font-size:1.15rem;opacity:.92;max-width:36rem;margin:0 auto 2rem}
.cta-row .btn{display:inline-block;background:#fff;color:var(--primary-dark);
  padding:.7rem 1.8rem;border-radius:.5rem;font-weight:600;margin:.25rem}
.cta-row .btn:hover{text-decoration:none;transform:translateY(-1px)}
.cta-row .btn.ghost{background:transparent;color:#fff;border:1px solid #fff}
/* 特性卡片 */
.features{padding:3.5rem 0;background:var(--soft)}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:1.25rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:.75rem;
  padding:1.5rem}
.card h3{margin:0 0 .5rem;font-size:1.1rem}
.card p{margin:0;color:var(--muted);font-size:.95rem}
/* 新闻列表 */
.news{padding:3rem 0}
.news h2{font-size:1.5rem;margin:0 0 1.25rem}
.post-list{list-style:none;margin:0 0 1.5rem;padding:0}
.post-list li{padding:.6rem 0;border-bottom:1px solid var(--line)}
.post-list .date{color:var(--muted);font-size:.9rem;margin-right:1rem}
/* 文章页 */
.article{padding:2.5rem 0;max-width:46rem}
.article h1{font-size:2rem;line-height:1.4}
.meta{color:var(--muted);font-size:.9rem}
.toc{background:var(--soft);border-radius:.5rem;padding:1rem 1.5rem;margin:1.5rem 0}
.toc ul{margin:0;padding-left:1.25rem}
.toc3{margin-left:1rem}
/* 页脚 */
.site-footer{border-top:1px solid var(--line);padding:2rem 0;color:var(--muted);
  font-size:.9rem;text-align:center}
/* 通用内容元素 */
pre{background:#f4f4f4;padding:1em;overflow:auto;border-radius:.5rem}
code{background:#f4f4f4;padding:0 .3em;border-radius:.25rem}
pre code{background:none;padding:0}
.codehilite{background:#f4f4f4;padding:.2em 1em;overflow:auto;border-radius:.5rem}
.codehilite .k,.codehilite .kn{color:#008000;font-weight:bold}
.codehilite .s,.codehilite .s1,.codehilite .s2{color:#ba2121}
.codehilite .c,.codehilite .c1,.codehilite .cm{color:#408080;font-style:italic}
.codehilite .nb,.codehilite .nf{color:#06287e}
.codehilite .mi,.codehilite .mf,.codehilite .o{color:#666}
table{border-collapse:collapse;margin:1em 0}
th,td{border:1px solid #ccc;padding:.3em .8em}
blockquote{border-left:3px solid var(--primary);margin:1.5em 0;padding:.2em 0 .2em 1em;
  color:var(--muted);background:var(--soft);border-radius:0 .5rem .5rem 0}
.pager{display:flex;gap:1rem;align-items:center;margin:2rem 0}
/* 移动端 */
@media (max-width:640px){
  .hero{padding:3rem 0}
  .hero h1{font-size:1.8rem}
  .cards{grid-template-columns:1fr}
  .site-header nav a{margin-left:.9rem}
}
""",
        encoding="utf-8",
    )
    return root