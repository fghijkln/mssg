"""Asset pipeline（零依赖）：CSS/JS 压缩 + fingerprint 文件名。

CSS 压缩：去注释、压空白（字符串字面量先暂存，还原不受影响）。
JS 压缩是保守的：只去掉注释与空行/行首尾空白，不做词法级空白合并
（避免 ASI 与正则字面量风险）。注意：JS 里如果写了包含 ``//`` 的
正则字面量（如 ``/http:\\/\\//``），行注释剥离可能误伤——这类文件请
关闭 minify 或把 ``//`` 改写为 ``\\/\\/``。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

_CSS_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def minify_css(text: str) -> str:
    """压缩 CSS（字符串安全）。"""
    stash: list = []

    def _stash(m: re.Match) -> str:
        stash.append(m.group(0))
        return "\x00%d\x00" % (len(stash) - 1)

    text = _CSS_STRING_RE.sub(_stash, text)
    text = _CSS_COMMENT_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([{}:;,>])\s*", r"\1", text)
    text = text.replace(";}", "}")
    text = text.strip()
    for i, s in enumerate(stash):
        text = text.replace("\x00%d\x00" % i, s)
    return text


def minify_js(text: str) -> str:
    """保守压缩 JS：去注释（字符串/模板字符串感知）+ 删空行与行首尾空白。"""
    out: list = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in ("'", '"', "`"):
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == ch:
                    break
                j += 1
            out.append(text[i : j + 1])
            i = j + 1
            continue
        if ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                j = text.find("\n", i)
                i = n if j == -1 else j + 1
                continue
            if nxt == "*":
                j = text.find("*/", i + 2)
                i = n if j == -1 else j + 2
                continue
        out.append(ch)
        i += 1
    lines = [ln.strip() for ln in "".join(out).split("\n")]
    return "\n".join(ln for ln in lines if ln)


def minified(src: Path) -> bytes | None:
    """css/js 返回压缩后的 bytes；其他类型返回 None。"""
    suf = src.suffix.lower()
    if suf not in (".css", ".js"):
        return None
    try:
        text = src.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    out = minify_css(text) if suf == ".css" else minify_js(text)
    return out.encode("utf-8")


def fingerprinted_name(rel: str, content: bytes) -> str:
    """style.css → style.<8hex>.css；a.min.js → a.min.<8hex>.css（同目录）。"""
    h = hashlib.sha1(content).hexdigest()[:8]

    def _fp(name: str) -> str:
        idx = name.rfind(".")
        stem, suffix = (name[:idx], name[idx:]) if idx > 0 else (name, "")
        return "%s.%s%s" % (stem, h, suffix)

    if "/" in rel:
        parent, name = rel.rsplit("/", 1)
        return parent + "/" + _fp(name)
    return _fp(rel)
