"""mssg 自研 Markdown 子集解析器（零依赖，只用标准库）。

支持的语法：
    # ~ ######      ATX 标题
    段落            连续非空行合并为一段
    **粗体** *斜体* `行内代码`
    [文字](url)     链接
    ![alt](url)     图片
    - / * / +       无序列表（支持一层嵌套）
    1. / 1)         有序列表（支持一层嵌套）
    >               引用块（可嵌套任意块级语法）
    ```             围栏代码块
    --- / ***       分隔线
    | a | b |       简单表格（需表头分隔行）
"""

from __future__ import annotations

import html
import re

_INLINE_CODE = re.compile(r"`([^`\n]+?)`")
_IMAGE = re.compile(r'!\[([^\]]*)\]\(\s*([^\s)]+)(?:\s+"[^"]*")?\s*\)')
_LINK = re.compile(r'\[([^\]]+)\]\(\s*([^\s)]+)(?:\s+"[^"]*")?\s*\)')
_BOLD = re.compile(r"\*\*([^*]+?)\*\*")
_ITALIC = re.compile(r"\*([^*]+?)\*")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HR = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})\s*$")
_LIST_ITEM = re.compile(r"^(\s*)(?:([-*+])|(\d+)[.)])\s+(.*)$")
_BLOCKQUOTE = re.compile(r"^\s*>\s?(.*)$")
_TABLE_SEP_CELL = re.compile(r"^\s*:?-+:?\s*$")


def _inline(text: str) -> str:
    """行内语法：先转义 HTML，再处理行内标记。

    行内代码片段先暂存为占位符，避免其中的 *、**、[]() 被误解析。
    """
    text = html.escape(text, quote=False)
    codes: list[str] = []

    def _stash(m: "re.Match") -> str:
        codes.append(m.group(1))
        return "\x00%d\x00" % (len(codes) - 1)

    text = _INLINE_CODE.sub(_stash, text)
    text = _IMAGE.sub(
        lambda m: '<img src="%s" alt="%s">' % (m.group(2), m.group(1)), text
    )
    text = _LINK.sub(
        lambda m: '<a href="%s">%s</a>' % (m.group(2), m.group(1)), text
    )
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    for i, code in enumerate(codes):
        text = text.replace("\x00%d\x00" % i, "<code>%s</code>" % code)
    return text


def parse(src: str) -> str:
    """把 Markdown 子集源码转成 HTML 片段。"""
    src = src.replace("\r\n", "\n").replace("\r", "\n")
    lines = src.replace("\t", "    ").split("\n")
    try:
        blocks, _ = _parse_blocks(lines, 0)
    except RecursionError:
        raise ValueError("Markdown 嵌套过深（超过 Python 递归限制）")
    return "\n".join(blocks)


def _parse_blocks(lines: list[str], i: int) -> tuple[list[str], int]:
    out: list[str] = []
    n = len(lines)
    in_fence = False
    fence: list[str] = []
    para: list[str] = []

    def flush_para() -> None:
        if para:
            out.append("<p>%s</p>" % _inline(" ".join(para)))
            para.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if line.startswith("```"):
            flush_para()
            if not in_fence:
                in_fence = True
                fence = []
            else:
                in_fence = False
                out.append(
                    "<pre><code>%s</code></pre>" % html.escape("\n".join(fence))
                )
            i += 1
            continue
        if in_fence:
            fence.append(line)
            i += 1
            continue
        if not stripped:
            flush_para()
            i += 1
            continue

        m = _HEADING.match(line)
        if m:
            flush_para()
            level = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (level, _inline(m.group(2)), level))
            i += 1
            continue
        if _HR.match(line):
            flush_para()
            out.append("<hr>")
            i += 1
            continue
        if _BLOCKQUOTE.match(line):
            flush_para()
            quote_lines = []
            while i < n:
                qm = _BLOCKQUOTE.match(lines[i])
                if not qm:
                    break
                quote_lines.append(qm.group(1))
                i += 1
            inner, _ = _parse_blocks(quote_lines, 0)
            out.append("<blockquote>\n%s\n</blockquote>" % "\n".join(inner))
            continue
        if _LIST_ITEM.match(line):
            flush_para()
            list_html, i = _parse_list(lines, i)
            out.append(list_html)
            continue
        if stripped.startswith("|") and i + 1 < n and _is_table_sep(lines[i + 1]):
            flush_para()
            table_html, i = _parse_table(lines, i)
            out.append(table_html)
            continue

        para.append(stripped)
        i += 1

    flush_para()
    if in_fence:
        # 围栏代码块未闭合：按闭合处理，避免内容静默丢失
        out.append("<pre><code>%s</code></pre>" % html.escape("\n".join(fence)))
    return out, i


def _parse_list(lines: list[str], i: int) -> tuple[str, int]:
    """解析一个列表（含一层嵌套），返回 (html, 下一行下标）。"""
    n = len(lines)
    m0 = _LIST_ITEM.match(lines[i])
    assert m0 is not None
    base = len(m0.group(1))
    ordered = m0.group(3) is not None
    entries: list[list[str]] = []  # [正文 html, 子列表 html]

    while i < n:
        m = _LIST_ITEM.match(lines[i])
        if not m:
            break
        indent = len(m.group(1))
        cur_ordered = m.group(3) is not None
        if indent < base or (indent == base and cur_ordered != ordered):
            break
        if indent > base:
            sub, i = _parse_list(lines, i)
            entries[-1][1] += sub
            continue
        entries.append([_inline(m.group(4)), ""])
        i += 1

    tag = "ol" if ordered else "ul"
    parts = ["<%s>" % tag]
    for text, children in entries:
        parts.append("<li>%s%s</li>" % (text, children))
    parts.append("</%s>" % tag)
    return "\n".join(parts), i


def _is_table_sep(line: str) -> bool:
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return False
    cells = s.strip("|").split("|")
    return bool(cells) and all(_TABLE_SEP_CELL.match(c) for c in cells)


def _parse_table(lines: list[str], i: int) -> tuple[str, int]:
    header = [c.strip() for c in lines[i].strip().strip("|").split("|")]
    i += 2  # 跳过表头与分隔行
    rows = []
    n = len(lines)
    while i < n and lines[i].strip().startswith("|"):
        rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
        i += 1
    parts = ["<table>"]
    parts.append(
        "<thead><tr>%s</tr></thead>"
        % "".join("<th>%s</th>" % _inline(c) for c in header)
    )
    parts.append("<tbody>")
    for row in rows:
        parts.append(
            "<tr>%s</tr>" % "".join("<td>%s</td>" % _inline(c) for c in row)
        )
    parts.append("</tbody>")
    parts.append("</table>")
    return "\n".join(parts), i
