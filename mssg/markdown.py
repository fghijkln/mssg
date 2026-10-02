"""Markdown 渲染（基于 Python-Markdown 第三方库）。

API（与旧自研解析器兼容）：
  parse(src, extensions=None, extension_configs=None) -> HTML
  extract_toc(src, extensions=None, extension_configs=None) -> [{level, text, id}]
  slugify(text) -> 锚点 id

默认扩展：extra（含表格、脚注、定义列表等）、codehilite
（Pygments 代码高亮）、toc（标题锚点 id）、sane_lists。
站点可在 mssg.toml 里 [markdown] extensions 覆盖。

性能：Markdown 实例按配置缓存（线程本地），避免每页重建；
Python-Markdown 实例非线程安全，不跨线程共享。
"""
from __future__ import annotations

import re
import threading
import warnings

import markdown as _markdown
from markdown.extensions.toc import slugify_unicode as _slugify_unicode

DEFAULT_EXTENSIONS = ["extra", "codehilite", "toc", "sane_lists"]
DEFAULT_EXTENSION_CONFIGS = {
    "codehilite": {"guess_lang": False, "css_class": "codehilite"},
    "toc": {"slugify": _slugify_unicode, "toc_depth": "2-3"},
}
_TAG_RE = re.compile(r"<[^>]+>")

_local = threading.local()


def _freeze(configs: dict) -> tuple:
    """extension_configs 转可哈希的缓存键（含函数值用 repr）。"""
    items = []
    for k in sorted(configs):
        v = configs[k]
        if isinstance(v, dict):
            items.append((k, _freeze(v)))
        else:
            try:
                hash(v)
                items.append((k, v))
            except TypeError:
                items.append((k, repr(v)))
    return tuple(items)


def _cached_md(extensions, extension_configs) -> "_markdown.Markdown":
    """按配置取线程本地缓存的 Markdown 实例（不存在则创建）。"""
    key = (tuple(extensions or []), _freeze(extension_configs or {}))
    cache = getattr(_local, "md_cache", None)
    if cache is None:
        cache = _local.md_cache = {}
    md = cache.get(key)
    if md is None:
        md = _markdown.Markdown(
            extensions=list(extensions or []),
            extension_configs=dict(extension_configs or {}),
        )
        cache[key] = md
    else:
        md.reset()
    return md


_warned_no_pygments = False


def _warn_if_no_pygments() -> None:
    """Pygments 未安装时警告一次（codehilite 会自动降级为普通代码块）。"""
    global _warned_no_pygments
    if _warned_no_pygments:
        return
    _warned_no_pygments = True
    try:
        import pygments  # noqa: F401
    except ImportError:
        warnings.warn(
            "Pygments 未安装，代码高亮已降级为普通代码块；"
            'pip install "mssg[highlight]" 可恢复'
        )


def _get_md(extensions, extension_configs) -> "_markdown.Markdown":
    exts = list(extensions or DEFAULT_EXTENSIONS)
    cfgs = dict(extension_configs or DEFAULT_EXTENSION_CONFIGS)
    if "codehilite" in exts:
        _warn_if_no_pygments()
    return _cached_md(exts, cfgs)


def parse(src: str, extensions=None, extension_configs=None) -> str:
    """Markdown 转 HTML（含代码高亮与标题锚点）。"""
    return _get_md(
        extensions or DEFAULT_EXTENSIONS,
        extension_configs or DEFAULT_EXTENSION_CONFIGS,
    ).convert(src)


def slugify(text: str) -> str:
    """标题转锚点 id（CJK 保留）。"""
    return _slugify_unicode(text, "-")


def extract_toc(src: str, extensions=None, extension_configs=None) -> list:
    """提取 h2/h3 目录：[{level, text, id}]。"""
    md = _get_md(
        extensions or DEFAULT_EXTENSIONS,
        extension_configs or DEFAULT_EXTENSION_CONFIGS,
    )
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
