"""构建流程：扫描 content/**/*.md → HTML，生成首页索引，拷贝静态资源，增量构建。"""

from __future__ import annotations

import copy
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
from . import themes as _themes
from . import images as _images
from .frontmatter import split as _split_fm
from .hooks import Hooks
from .scaffold import new_site

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


def _split_summary(body_md: str, extensions=None, extension_configs=None) -> tuple:
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
    html_sum = _md.parse(head, extensions=extensions, extension_configs=extension_configs)
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
        self.hooks = Hooks()

    def _ctx(self, site=None, lang=None, **kw) -> dict:
        """模板公共上下文：site + data + 语言变量 + 调用方变量。"""
        default = self._default_lang()
        langs = self._langs()
        ctx = {
            "site": site if site is not None else self._site_for_lang(default),
            "data": self._data,
            "lang": lang or default,
            "langs": langs,
            "default_lang": default,
        }
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
                "theme": "company",
                # 公司站各节：缺了也不让模板炸，给空默认值
                "menu": [],
                "hero": {},
                "features": [],
                "contact": {},
                "footer": {},
                "form": {},
            },
            "build": {
                "content_dir": "content",
                "template_dir": "templates",
                "static_dir": "static",
                "output_dir": "public",
                "drafts": False,
            },
            "i18n": {"default": "zh", "langs": []},
            "markdown": {},
        }
        path = self.root / config
        if path.exists():
            with open(path, "rb") as f:
                user = tomllib.load(f)
            for section in ("site", "build", "i18n", "markdown"):
                cfg[section].update(user.get(section, {}))
        return cfg

    # -- i18n ----------------------------------------------------------

    def _langs(self) -> list:
        """语言列表；未配置时为单语言（默认语言），行为与旧版一致。"""
        i18n = self.cfg.get("i18n", {})
        default = i18n.get("default", "zh") or "zh"
        langs = [l for l in (i18n.get("langs") or []) if l]
        if default not in langs:
            langs = [default] + langs
        return langs

    def _default_lang(self) -> str:
        return self._langs()[0]

    def _split_lang(self, rel: str) -> tuple:
        """content 相对路径 → (lang, 去掉语言后缀的相对路径)。

        约定：about.en.md → ("en", "about.md")；about.md → (默认语言, "about.md")。
        """
        langs = self._langs()
        default = self._default_lang()
        if rel.endswith(".md"):
            stem = rel[:-3]
            for lang in langs:
                if lang != default and stem.endswith("." + lang):
                    return lang, stem[: -(len(lang) + 1)] + ".md"
        return default, rel

    @staticmethod
    def _deep_merge(base: dict, over: dict) -> dict:
        for k, v in over.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                Site._deep_merge(base[k], v)
            else:
                base[k] = copy.deepcopy(v)
        return base

    def _site_for_lang(self, lang: str) -> dict:
        """当前语言的 site 配置：基础配置 + [site.<lang>] 覆盖。

        语言子表（如 site.en）从结果中剔除，不污染模板变量。
        """
        langs = set(self._langs())
        base = {
            k: copy.deepcopy(v)
            for k, v in self.cfg["site"].items()
            if k not in langs
        }
        return self._deep_merge(base, copy.deepcopy(self.cfg["site"].get(lang, {})))

    def _md_options(self) -> tuple:
        """[markdown] 配置 → (extensions, extension_configs)。

        extension_configs 与内置默认深层合并（TOML 写不出的函数值如
        toc.slugify 保持默认）。
        """
        m = self.cfg.get("markdown", {})
        exts = m.get("extensions") or list(_md.DEFAULT_EXTENSIONS)
        cfgs = copy.deepcopy(_md.DEFAULT_EXTENSION_CONFIGS)
        self._deep_merge(cfgs, m.get("extension_configs", {}) or {})
        return exts, cfgs

    # -- 对外接口 ------------------------------------------------------

    def build(self, force: bool = False, include_drafts: bool = False) -> dict:
        # 每次构建都重读配置：serve 监听时修改 mssg.toml 能立即生效
        self.cfg = self._load_config(self.config_name)
        self._md_opts = self._md_options()
        # 插件：每次构建重载，serve 监听下改 plugins/ 即生效
        self.hooks = Hooks()
        self.hooks.load_dir(self.root / "plugins")
        self.hooks.run("build_started", self)
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
        default_lang = self._default_lang()

        # 预扫描翻译映射（文件名 → 各语言 URL）：新增/删除翻译文件时，
        # 兄弟语言页面的 hreflang 也要更新，因此触发全量页面重建。
        tmap: dict[str, dict] = {}
        if content_dir.is_dir():
            for md_path in sorted(content_dir.rglob("*.md")):
                rel = md_path.relative_to(content_dir).as_posix()
                lang, base_rel = self._split_lang(rel)
                pre = "" if lang == default_lang else lang + "/"
                tmap.setdefault(base_rel, {})[lang] = pre + base_rel[:-3] + ".html"
        tmap_digest = hashlib.sha1(
            json.dumps(tmap, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        translations_changed = cache.get("tmap") != tmap_digest
        cache["tmap"] = tmap_digest
        if translations_changed:
            rebuilt_any = True

        if content_dir.is_dir():
            for md_path in sorted(content_dir.rglob("*.md")):
                rel = md_path.relative_to(content_dir).as_posix()
                rels.add(rel)
                lang, base_rel = self._split_lang(rel)
                prefix = "" if lang == default_lang else lang + "/"
                url = prefix + base_rel[:-3] + ".html"
                digest = _sha1_file(md_path)
                try:
                    page, body = self._read_meta(md_path, rel, url)
                except Exception as e:
                    raise ValueError("解析页面失败 %s：%s" % (rel, e))
                page["lang"] = lang
                page["key"] = base_rel  # 翻译映射用：去掉语言后缀的相对路径
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
                self.hooks.run("page_read", page)
                page["_body"] = body  # 轻量页保留正文，供 _ensure_content 按需解析
                pages.append(page)
                if (
                    not force
                    and not global_changed
                    and not translations_changed
                    and cache.get(key) == digest
                    and out_path.exists()
                ):
                    continue  # 缓存命中：跳过 Markdown 重量解析
                self._parse_content(page, body)
                render_jobs.append((page, out_path, key, digest, rel))

        # 把翻译映射挂到页面上（_render_page 需要 page["translations"]）
        for p in pages:
            p["translations"] = tmap.get(p["key"], {})

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

        # 各语言独立渲染列表页（首页/标签/分类/归档/订阅）
        index_made: set = set()
        tag_made: set = set()
        cat_made: set = set()
        archive_rels: list = []
        feed_rels: list = []
        rss_rels: list = []
        home_trans = {
            l: ("" if l == default_lang else l + "/") + "index.html"
            for l in self._langs()
        }
        for lang in self._langs():
            lpages = [p for p in pages if p["lang"] == lang]
            lpages.sort(key=lambda p: p["date"], reverse=True)
            prefix = "" if lang == default_lang else lang + "/"
            lsite = self._site_for_lang(lang)

            def _ck(name: str, _lang: str = lang) -> str:
                return "%s:%s" % (name, _lang)

            # content/index[.lang].md 存在时，它就是该语言的首页
            has_home = any(p["url"] == prefix + "index.html" for p in lpages)
            if not has_home:
                made = self._render_index(
                    lpages, templates, output_dir, rebuilt_any,
                    prefix=prefix, site=lsite, lang=lang,
                    translations=home_trans,
                )
                index_made |= made
                self._clean_stale(output_dir, cache.get(_ck("index_files"), []), made)
                cache[_ck("index_files")] = sorted(made)
            elif cache.get(_ck("index_files")):
                # 之前生成的分页文件现在不需要了（有了 content/index.md）；
                # index.html 现在由 content/index.md 生成，不在此删除
                self._clean_stale(
                    output_dir,
                    [
                        f
                        for f in cache.pop(_ck("index_files"))
                        if f != prefix + "index.html"
                    ],
                    set(),
                )

            if b.get("tag_pages", True):
                made = self._render_tag_pages(
                    lpages, templates, output_dir, rebuilt_any,
                    prefix=prefix, site=lsite, lang=lang,
                    translations=home_trans,
                )
                tag_made |= made
                self._clean_stale(output_dir, cache.get(_ck("tag_files"), []), made)
                cache[_ck("tag_files")] = sorted(made)
            elif cache.get(_ck("tag_files")):
                self._clean_stale(output_dir, cache.pop(_ck("tag_files")), set())

            if b.get("archive_page", True):
                arel = self._render_archive(
                    lpages, templates, output_dir, rebuilt_any,
                    prefix=prefix, site=lsite, lang=lang,
                    translations=home_trans,
                )
                archive_rels.append(arel)
                self._clean_stale(
                    output_dir, cache.get(_ck("archive_files"), []), {arel}
                )
                cache[_ck("archive_files")] = [arel]
            elif cache.get(_ck("archive_files")):
                self._clean_stale(output_dir, cache.pop(_ck("archive_files")), set())

            if b.get("category_pages", True):
                made = self._render_category_pages(
                    lpages, templates, output_dir, rebuilt_any,
                    prefix=prefix, site=lsite, lang=lang,
                    translations=home_trans,
                )
                cat_made |= made
                self._clean_stale(
                    output_dir, cache.get(_ck("category_files"), []), made
                )
                cache[_ck("category_files")] = sorted(made)
            elif cache.get(_ck("category_files")):
                self._clean_stale(
                    output_dir, cache.pop(_ck("category_files")), set()
                )

            if b.get("feed", True):
                frel = self._render_feed(
                    lpages, output_dir, rebuilt_any, prefix=prefix, site=lsite
                )
                feed_rels.append(frel)
                self._clean_stale(
                    output_dir, cache.get(_ck("feed_files"), []), {frel}
                )
                cache[_ck("feed_files")] = [frel]
            elif cache.get(_ck("feed_files")):
                self._clean_stale(output_dir, cache.pop(_ck("feed_files")), set())

            if b.get("rss", True):
                rrel = self._render_rss(
                    lpages, output_dir, rebuilt_any, prefix=prefix, site=lsite
                )
                rss_rels.append(rrel)
                self._clean_stale(
                    output_dir, cache.get(_ck("rss_files"), []), {rrel}
                )
                cache[_ck("rss_files")] = [rrel]
            elif cache.get(_ck("rss_files")):
                self._clean_stale(output_dir, cache.pop(_ck("rss_files")), set())

        # 站内搜索：search.json 索引 + 各语言一份 search.html
        if b.get("search", True):
            search_rel = self._render_search_index(pages, output_dir, rebuilt_any)
            self._clean_stale(
                output_dir, cache.get("search_files", []), {search_rel}
            )
            cache["search_files"] = [search_rel]
            search_page_rels: list = []
            for lang in self._langs():
                prefix = "" if lang == default_lang else lang + "/"
                srel = self._render_search_page(
                    templates, output_dir, rebuilt_any,
                    prefix=prefix, site=self._site_for_lang(lang),
                    lang=lang, translations=home_trans,
                )
                search_page_rels.append(srel)
            self._clean_stale(
                output_dir,
                cache.get("search_page_files", []),
                set(search_page_rels),
            )
            cache["search_page_files"] = sorted(search_page_rels)
        else:
            if cache.get("search_files"):
                self._clean_stale(output_dir, cache.pop("search_files"), set())
            if cache.get("search_page_files"):
                self._clean_stale(
                    output_dir, cache.pop("search_page_files"), set()
                )

        if b.get("robots", True):
            robots_rel = self._render_robots(output_dir, rebuilt_any)
            self._clean_stale(output_dir, cache.get("robots_files", []), {robots_rel})
            cache["robots_files"] = [robots_rel]
        elif cache.get("robots_files"):
            self._clean_stale(output_dir, cache.pop("robots_files"), set())

        if b.get("sitemap", True):
            extra_paths = (
                set(index_made) | set(tag_made) | set(cat_made) | set(archive_rels)
            )
            extra = sorted(extra_paths - set(home_trans.values()))
            sm_rel = self._render_sitemap(pages, output_dir, rebuilt_any, extra)
            self._clean_stale(output_dir, cache.get("sitemap_files", []), {sm_rel})
            cache["sitemap_files"] = [sm_rel]
        elif cache.get("sitemap_files"):
            self._clean_stale(output_dir, cache.pop("sitemap_files"), set())

        # 静态资源：主题 static 为底，站点 static/ 覆盖同名文件
        _, theme_static = self._theme_dirs()
        static_srcs = [
            (theme_static, True),
            (static_dir, False),
        ]
        new_static = set()
        for src_dir, _ in static_srcs:
            if src_dir.is_dir():
                for sp in sorted(src_dir.rglob("*")):
                    if sp.is_file():
                        new_static.add(sp.relative_to(src_dir).as_posix())
        if new_static or cache.get("static_files"):
            # 清理 static 里已删除的文件在输出目录中的残留
            for stale in set(cache.get("static_files", [])) - new_static:
                stale_path = output_dir / stale
                if stale_path.is_file():
                    try:
                        stale_path.resolve().relative_to(output_dir.resolve())
                    except ValueError:
                        continue  # 路径穿越保护
                    stale_path.unlink()
            max_w = b.get("image_max_width", 1600)
            quality = b.get("image_quality", 82)
            for src_dir, _ in static_srcs:
                if src_dir.is_dir():
                    for sp in sorted(src_dir.rglob("*")):
                        if sp.is_file():
                            rel = sp.relative_to(src_dir).as_posix()
                            dst = output_dir / rel
                            if _images.is_image(sp):
                                # 图片缓存：源文件指纹 + 压缩配置不变且输出存在则跳过
                                sig = "%s|%s|%s" % (_sha1_file(sp), max_w, quality)
                                if cache.get("img:" + rel) == sig and dst.exists():
                                    continue
                                _images.copy_static_file(sp, dst, max_w, quality)
                                cache["img:" + rel] = sig
                            else:
                                _images.copy_static_file(sp, dst, max_w, quality)
            cache["static_files"] = sorted(new_static)
            # 清理已删除图片的缓存指纹
            for key in [k for k in cache if k.startswith("img:") and k[4:] not in new_static]:
                del cache[key]

        cache["templates"] = tpl_digest
        cache["config"] = config_digest
        self._save_cache(cache_path, cache)
        result = {"pages": len(pages), "rebuilt": rebuilt_any}
        self.hooks.run("build_finished", self, result)
        return result

    # -- 内部 ----------------------------------------------------------

    @staticmethod
    def available_themes() -> list:
        """内置主题列表（见 mssg/themes.py）。"""
        return _themes.available_themes()

    def _theme_dirs(self) -> tuple:
        """当前主题的 (templates_dir, static_dir)；主题不存在时报 ValueError。"""
        return _themes.theme_dirs(self.cfg["site"].get("theme", "company"))

    def _load_templates(self, template_dir: Path) -> dict:
        """加载模板：主题模板为底，站点 templates/ 覆盖同名文件。"""
        templates = {}
        theme_tpl, _ = self._theme_dirs()
        for d in (theme_tpl, template_dir):
            if d.is_dir():
                for tp in sorted(d.rglob("*.html")):
                    templates[tp.relative_to(d).as_posix()] = tp.read_text(
                        encoding="utf-8"
                    )
        return templates

    def _read_page(self, md_path: Path, rel: str, url: str) -> dict:
        """读入页面：轻量元数据 + 重量 Markdown 解析（完整页面）。"""
        page, body = self._read_meta(md_path, rel, url)
        return self._parse_content(page, body)

    def _read_meta(self, md_path: Path, rel: str, url: str) -> tuple:
        """轻量读取：front matter + 标题/日期/标签，不做 Markdown 解析。

        返回 (page, body)；缓存命中时直接用 page（列表页/订阅只需元数据），
        未命中时再对 body 做重量解析。
        """
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
            "url": url,
        }
        for key, value in meta.items():
            if key not in page:
                page[key] = value
        return page, body

    def _parse_content(self, page: dict, body: str) -> dict:
        """重量解析：Markdown → content/summary/toc（就地修改 page 并返回）。"""
        exts, cfgs = self._md_opts
        page["content"] = _md.parse(body, extensions=exts, extension_configs=cfgs)
        summary_html, summary_text = _split_summary(
            body, extensions=exts, extension_configs=cfgs
        )
        page["summary"] = summary_html
        page["summary_text"] = summary_text
        page["toc"] = _md.extract_toc(body, extensions=exts, extension_configs=cfgs)
        return page

    def _ensure_content(self, pages: list) -> None:
        """把轻量页面按需升级为完整页面（feed/搜索索引渲染前调用）。"""
        for p in pages:
            if "content" not in p:
                self._parse_content(p, p.pop("_body", ""))

    @staticmethod
    def _first_heading(body: str) -> str:
        m = _FIRST_HEADING.search(body)
        return _clean_title(m.group(1)) if m else ""

    def _render_page(self, page: dict, templates: dict, out_path: Path) -> None:
        lang = page.get("lang", self._default_lang())
        tpl_name = str(page.get("template", "page.html"))
        ctx = self._ctx(
            site=self._site_for_lang(lang),
            lang=lang,
            page=page,
            translations=page.get("translations", {}),
        )
        if tpl_name in templates:
            out = _tpl.render_template(tpl_name, ctx, templates)
        else:
            out = _tpl.render(
                "<!doctype html><html><head><meta charset=utf-8>"
                "<title>{{ page.title }}</title></head>"
                "<body>{{ page.content }}</body></html>",
                ctx,
            )
        out = self.hooks.filter_html("page_html", page, out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out, encoding="utf-8")

    def _render_index(
        self, pages: list, templates: dict, output_dir: Path, rebuilt_any: bool,
        *, prefix: str = "", site=None, lang=None, translations=None,
    ) -> set:
        """渲染首页；per_page > 0 时分页为 page/2.html…，返回相对路径集合。

        prefix 为语言前缀（如 "en/"），多语言站点各语言独立渲染首页。
        """
        per_page = self.cfg["build"].get("per_page", 0)
        chunks = _paginate(pages, per_page)
        total = len(chunks)
        made = set()
        for i, chunk in enumerate(chunks, start=1):
            rel = prefix + ("index.html" if i == 1 else "page/%d.html" % i)
            dest = output_dir / rel
            made.add(rel)
            if not rebuilt_any and dest.exists():
                continue  # 无改动：连模板都不渲染
            prev_rel = (
                None
                if i == 1
                else (prefix + ("index.html" if i == 2 else "page/%d.html" % (i - 1)))
            )
            next_rel = prefix + "page/%d.html" % (i + 1) if i < total else None
            ctx = self._ctx(
                site=site,
                lang=lang,
                pages=chunk,
                pagination=_pagination_ctx(i, total, prev_rel, next_rel),
                translations=translations or {},
            )
            if "index.html" in templates:
                out = _tpl.render_template("index.html", ctx, templates)
            else:
                out = _tpl.render(_INDEX_FALLBACK, ctx)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(out, encoding="utf-8")
        return made

    def _render_taxonomy(
        self, pages: list, templates: dict, output_dir: Path, rebuilt_any: bool,
        *, get_terms, dirname: str, tpl_name: str, fallback: str,
        var_name: str, label: str,
        prefix: str = "", site=None, lang=None, translations=None,
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
                    rel = prefix + "%s/%s.html" % (dirname, tag_q)
                    prev_rel = None
                else:
                    rel = prefix + "%s/%s/%d.html" % (dirname, tag_q, i)
                    prev_rel = (
                        prefix + "%s/%s.html" % (dirname, tag_q)
                        if i == 2
                        else prefix + "%s/%s/%d.html" % (dirname, tag_q, i - 1)
                    )
                next_rel = (
                    prefix + "%s/%s/%d.html" % (dirname, tag_q, i + 1) if i < total else None
                )
                dest = output_dir / rel
                made.add(rel)
                if not rebuilt_any and dest.exists():
                    continue  # 无改动：连模板都不渲染
                ctx = self._ctx(
                    site=site,
                    lang=lang,
                    **{var_name: term},
                    pages=chunk,
                    pagination=_pagination_ctx(i, total, prev_rel, next_rel),
                    translations=translations or {},
                )
                if tpl_name in templates:
                    out = _tpl.render_template(tpl_name, ctx, templates)
                else:
                    out = _tpl.render(fallback, ctx)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(out, encoding="utf-8")
        return made

    def _render_tag_pages(
        self, pages: list, templates: dict, output_dir: Path, rebuilt_any: bool,
        *, prefix: str = "", site=None, lang=None, translations=None,
    ) -> set:
        """为每个标签生成 tags/<tag>.html（分页时还有 tags/<tag>/N.html）。"""
        return self._render_taxonomy(
            pages, templates, output_dir, rebuilt_any,
            get_terms=_page_tags, dirname="tags", tpl_name="tag.html",
            fallback=_TAG_FALLBACK, var_name="tag", label="标签",
            prefix=prefix, site=site, lang=lang, translations=translations,
        )

    def _render_category_pages(
        self, pages: list, templates: dict, output_dir: Path, rebuilt_any: bool,
        *, prefix: str = "", site=None, lang=None, translations=None,
    ) -> set:
        """为每个分类生成 categories/<cat>.html（分页时还有 categories/<cat>/N.html）。"""
        return self._render_taxonomy(
            pages, templates, output_dir, rebuilt_any,
            get_terms=_page_categories, dirname="categories",
            tpl_name="category.html", fallback=_CATEGORY_FALLBACK,
            var_name="category", label="分类",
            prefix=prefix, site=site, lang=lang, translations=translations,
        )

    def _render_archive(
        self, pages: list, templates: dict, output_dir: Path, rebuilt_any: bool,
        *, prefix: str = "", site=None, lang=None, translations=None,
    ) -> str:
        """生成 archive.html（按年月归档），返回相对路径。"""
        rel = prefix + "archive.html"
        dest = output_dir / rel
        if not rebuilt_any and dest.exists():
            return rel
        groups: dict[str, list] = {}
        for p in pages:
            groups.setdefault(str(p["date"])[:7], []).append(p)
        ordered = [
            {"ym": ym, "pages": sorted(ps, key=lambda p: p["date"], reverse=True)}
            for ym, ps in sorted(groups.items(), reverse=True)
        ]
        ctx = self._ctx(
            site=site, lang=lang, groups=ordered, translations=translations or {}
        )
        if "archive.html" in templates:
            out = _tpl.render_template("archive.html", ctx, templates)
        else:
            out = _tpl.render(_ARCHIVE_FALLBACK, ctx)
        dest.write_text(out, encoding="utf-8")
        return rel

    def _search_entry(self, p: dict) -> dict:
        """单页的搜索索引条目（需要 p 有 content）。"""
        text = re.sub(r"<[^>]+>", " ", str(p.get("content", "")))
        text = re.sub(r"\s+", " ", text).strip()[:2000]
        return {
            "title": p.get("title", ""),
            "url": p.get("url", ""),
            "date": str(p.get("date", ""))[:10],
            "lang": p.get("lang", self._default_lang()),
            "text": text,
        }

    def _render_search_index(self, pages: list, output_dir: Path, rebuilt_any: bool) -> str:
        """生成 search.json（站内搜索索引），返回相对路径。

        增量更新：内容未变的页面（轻量页）复用旧索引条目，只解析新增/
        改动的页面。
        """
        rel = "search.json"
        dest = output_dir / rel
        if not rebuilt_any and dest.exists():
            return rel
        old = {}
        if dest.exists():
            try:
                old = {
                    i["url"]: i
                    for i in json.loads(dest.read_text(encoding="utf-8"))
                }
            except (OSError, ValueError):
                old = {}
        items = []
        for p in pages:
            if "content" in p or p.get("url") not in old:
                self._ensure_content([p])
                items.append(self._search_entry(p))
            else:
                items.append(old[p["url"]])
        dest.write_text(
            json.dumps(items, ensure_ascii=False), encoding="utf-8"
        )
        return rel

    _SEARCH_FALLBACK = """<!doctype html><html lang="{{ lang }}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>搜索 - {{ site.title }}</title></head><body>
<h1>搜索</h1>
<input id="q" placeholder="输入关键词…" style="width:100%;padding:.6em">
<div id="results"></div>
<script>
const LANG = document.documentElement.lang;
let idx = [];
fetch("/search.json").then(r => r.json()).then(d => {
  idx = d.filter(e => !e.lang || e.lang === LANG);
});
document.getElementById("q").addEventListener("input", e => {
  const q = e.target.value.trim().toLowerCase();
  const box = document.getElementById("results");
  if (!q) { box.innerHTML = ""; return; }
  const hits = idx.filter(
    h => ((h.title || "") + " " + (h.text || "")).toLowerCase().includes(q)
  ).slice(0, 20);
  box.innerHTML = hits.length
    ? hits.map(h => '<p><a href="/' + h.url + '">' +
        h.title.replace(/</g, "&lt;") + "</a><br><small>" + h.date + "</small></p>").join("")
    : "<p>没有找到。</p>";
});
</script>
</body></html>"""

    def _render_search_page(
        self, templates: dict, output_dir: Path, rebuilt_any: bool,
        *, prefix: str = "", site=None, lang=None, translations=None,
    ) -> str:
        """生成 search.html（站内搜索页，前端 JS 读取 search.json），返回相对路径。"""
        rel = prefix + "search.html"
        dest = output_dir / rel
        if not rebuilt_any and dest.exists():
            return rel
        ctx = self._ctx(
            site=site, lang=lang, translations=translations or {}
        )
        if "search.html" in templates:
            out = _tpl.render_template("search.html", ctx, templates)
        else:
            out = _tpl.render(self._SEARCH_FALLBACK, ctx)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(out, encoding="utf-8")
        return rel

    def _render_feed(
        self, pages: list, output_dir: Path, rebuilt_any: bool,
        *, prefix: str = "", site=None,
    ) -> str:
        """生成 Atom 1.0 订阅 feed.xml（最近 20 篇），返回相对路径。"""
        rel = prefix + "feed.xml"
        dest = output_dir / rel
        if not rebuilt_any and dest.exists():
            return rel
        self._ensure_content(pages[:20])
        site = site if site is not None else self.cfg["site"]
        base = site.get("base_url", "").rstrip("/")
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
        feed_url = (base + "/" + prefix + "feed.xml") if base else "/" + prefix + "feed.xml"
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
                _xml_escape(str(site.get("title", ""))),
                _xml_escape(feed_url, {'"': "&quot;"}),
                _xml_escape(feed_url, {'"': "&quot;"}),
                updated,
                _xml_escape(site_id),
                "\n".join(entries),
            )
        )
        dest.write_text(out, encoding="utf-8")
        return rel

    def _render_rss(
        self, pages: list, output_dir: Path, rebuilt_any: bool,
        *, prefix: str = "", site=None,
    ) -> str:
        """生成 RSS 2.0 订阅 feed_rss.xml（最近 20 篇），返回相对路径。"""
        rel = prefix + "feed_rss.xml"
        dest = output_dir / rel
        if not rebuilt_any and dest.exists():
            return rel
        self._ensure_content(pages[:20])
        site = site if site is not None else self.cfg["site"]
        base = site.get("base_url", "").rstrip("/")
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
        feed_url = (base + "/" + prefix + "feed_rss.xml") if base else "/" + prefix + "feed_rss.xml"
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
                _xml_escape(str(site.get("title", ""))),
                _xml_escape(feed_url),
                _xml_escape(str(site.get("title", ""))),
                pub,
                "\n".join(items),
            )
        )
        dest.write_text(out, encoding="utf-8")
        return rel

    def _render_robots(self, output_dir: Path, rebuilt_any: bool) -> str:
        """生成 robots.txt，返回相对路径。"""
        dest = output_dir / "robots.txt"
        if not rebuilt_any and dest.exists():
            return "robots.txt"
        base = self.cfg["site"].get("base_url", "").rstrip("/")
        lines = ["User-agent: *", "Allow: /"]
        if base:
            lines.append("Sitemap: %s/sitemap.xml" % base)
        dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return "robots.txt"

    def _render_sitemap(
        self, pages: list, output_dir: Path, rebuilt_any: bool, extra=()
    ) -> str:
        """生成 sitemap.xml；extra 为分页等附加相对路径。返回相对路径。"""
        dest = output_dir / "sitemap.xml"
        if not rebuilt_any and dest.exists():
            return "sitemap.xml"
        base = self.cfg["site"].get("base_url", "").rstrip("/")

        def abs_url(rel: str) -> str:
            return (base + "/" + rel) if base else "/" + rel

        entries = []
        seen = set()
        # 各语言首页优先（单语言时行为与旧版一致）
        for lang in self._langs():
            lpages = [p for p in pages if p["lang"] == lang]
            home = ("" if lang == self._default_lang() else lang + "/") + "index.html"
            date = lpages[0]["date"] if lpages else time.strftime("%Y-%m-%d")
            entries.append((home, date))
            seen.add(home)
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
