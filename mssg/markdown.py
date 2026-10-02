"""Markdown 渲染（基于 Python-Markdown 第三方库）。

API（与旧自研解析器兼容）：
  parse(src)        -> HTML
  extract_toc(src)  -> [{level, text, id}]（h2/h3）
  slugify(text)     -> 锚点 id

启用的扩展：extra（含表格、脚注、定义列表等）、codehilite
（Pygments 代码高亮）、toc（标题锚点 id）、sane_lists。
"""

from __future__ import annotations

import re

import markdown as _markdown
from markdown.extensions.toc import slugify_unicode as _slugify_unicode

_EXTENSIONS = ["extra", "codehilite", "toc", "sane_lists"]
_EXTENSION_CONFIGS = {
    "codehilite": {"guess_lang": False, "css_class": "codehilite"},
    "toc": {"slugify": _slugify_unicode, "toc_depth": "2-3"},
}
_TAG_RE = re.compile(r"<[^>]+>")


def _new_md() -> "_markdown.Markdown":
    return _markdown.Markdown(
        extensions=_EXTENSIONS, extension_configs=_EXTENSION_CONFIGS
    )


def parse(src: str) -> str:
    """Markdown 转 HTML（含代码高亮与标题锚点）。"""
    return _new_md().convert(src)


def slugify(text: str) -> str:
    """标题转锚点 id（CJK 保留）。"""
    return _slugify_unicode(text, "-")


def extract_toc(src: str) -> list:
    """提取 h2/h3 目录：[{level, text, id}]。"""
    md = _new_md()
    md.convert(src)
    out = []

    def walk(tokens):
        for tok in tokens:
            out.append(
                {
                    "level": tok["level"],
                    "text": _TAG_RE.sub("", tok["name"]).strip(),
                    "id": tok["id"],
                }
            )
            walk(tok.get("children", []))

    walk(md.toc_tokens)
    return out
