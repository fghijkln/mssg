"""构建流程：扫描 content/**/*.md → HTML，生成首页索引，拷贝静态资源，增量构建。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import tomllib
from pathlib import Path

from . import markdown as _md
from . import template as _tpl
from .frontmatter import split as _split_fm

_FIRST_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)


def _sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class Site:
    def __init__(self, root: str | Path, config: str = "mssg.toml"):
        self.root = Path(root)
        self.cfg = self._load_config(config)

    def _load_config(self, config: str) -> dict:
        cfg = {
            "site": {"title": "My Site", "base_url": ""},
            "build": {
                "content_dir": "content",
                "template_dir": "templates",
                "static_dir": "static",
                "output_dir": "public",
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

    def build(self, force: bool = False) -> dict:
        b = self.cfg["build"]
        content_dir = self.root / b["content_dir"]
        template_dir = self.root / b["template_dir"]
        static_dir = self.root / b["static_dir"]
        output_dir = self.root / b["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)

        cache_path = output_dir / ".mssg" / "cache.json"
        cache = self._load_cache(cache_path)

        templates = self._load_templates(template_dir)
        tpl_digest = (
            hashlib.sha1("".join(templates.values()).encode("utf-8")).hexdigest()
            if templates
            else ""
        )
        templates_changed = cache.get("templates") != tpl_digest

        pages = []
        rebuilt_any = force or templates_changed
        if content_dir.is_dir():
            for md_path in sorted(content_dir.rglob("*.md")):
                rel = md_path.relative_to(content_dir).as_posix()
                url = rel[:-3] + ".html"
                digest = _sha1_file(md_path)
                page = self._read_page(md_path, rel, url)
                pages.append(page)
                out_path = output_dir / url
                key = "page:" + rel
                if (
                    not force
                    and not templates_changed
                    and cache.get(key) == digest
                    and out_path.exists()
                ):
                    continue
                self._render_page(page, templates, out_path)
                cache[key] = digest
                rebuilt_any = True

        pages.sort(key=lambda p: p["date"], reverse=True)
        if rebuilt_any or not (output_dir / "index.html").exists():
            self._render_index(pages, templates, output_dir)

        if static_dir.is_dir():
            shutil.copytree(static_dir, output_dir, dirs_exist_ok=True)

        cache["templates"] = tpl_digest
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
        text = md_path.read_text(encoding="utf-8")
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
        tpl = templates.get(
            str(page.get("template", "page.html")),
            "<!doctype html><html><head><meta charset=utf-8>"
            "<title>{{ page.title }}</title></head>"
            "<body>{{ page.content }}</body></html>",
        )
        ctx = {"site": self.cfg["site"], "page": page}
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_tpl.render(tpl, ctx), encoding="utf-8")

    def _render_index(self, pages: list, templates: dict, output_dir: Path) -> None:
        tpl = templates.get(
            "index.html",
            "<!doctype html><html><head><meta charset=utf-8>"
            "<title>{{ site.title }}</title></head><body>"
            "<h1>{{ site.title }}</h1><ul>"
            "{% for p in pages %}"
            '<li>{{ p.date }} <a href="/{{ p.url }}">{{ p.title }}</a></li>'
            "{% endfor %}</ul></body></html>",
        )
        ctx = {"site": self.cfg["site"], "pages": pages}
        (output_dir / "index.html").write_text(
            _tpl.render(tpl, ctx), encoding="utf-8"
        )

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
    """生成站点脚手架，返回站点根目录。"""
    root = Path(name)
    (root / "content").mkdir(parents=True, exist_ok=True)
    (root / "templates").mkdir(parents=True, exist_ok=True)
    (root / "static").mkdir(parents=True, exist_ok=True)

    (root / "mssg.toml").write_text(
        '[site]\ntitle = "我的小站"\nbase_url = ""\n',
        encoding="utf-8",
    )

    (root / "templates" / "page.html").write_text(
        "<!doctype html>\n"
        '<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>{{ page.title }} - {{ site.title }}</title>\n"
        '<link rel="stylesheet" href="/style.css">\n</head>\n<body>\n'
        '<header><h1><a href="/">{{ site.title }}</a></h1></header>\n'
        "<main>\n<h2>{{ page.title }}</h2>\n"
        "{% if page.date %}<p class=meta>{{ page.date }}</p>{% endif %}\n"
        "{{ page.content }}\n</main>\n"
        "<footer><p>由 mssg 生成</p></footer>\n</body>\n</html>\n",
        encoding="utf-8",
    )
    (root / "templates" / "index.html").write_text(
        "<!doctype html>\n"
        '<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>{{ site.title }}</title>\n"
        '<link rel="stylesheet" href="/style.css">\n</head>\n<body>\n'
        "<h1>{{ site.title }}</h1>\n<ul>\n"
        "{% for p in pages %}\n"
        '<li>{{ p.date }} <a href="/{{ p.url }}">{{ p.title }}</a></li>\n'
        "{% endfor %}\n</ul>\n</body>\n</html>\n",
        encoding="utf-8",
    )
    (root / "content" / "hello.md").write_text(
        "---\ntitle: 你好，世界\ndate: 2026-10-02\n---\n\n"
        "# 你好，世界\n\n这是用 **mssg** 生成的第一篇文章。\n\n"
        "- 零依赖，只用 Python 标准库\n- 自研 Markdown 解析器\n- 自研模板引擎\n\n"
        "> 纸上得来终觉浅，绝知此事要躬行。\n",
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
