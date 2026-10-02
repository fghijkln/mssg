"""极简 front matter 解析（零依赖）。

文件开头用 --- 包裹的 key: value 块：
    ---
    title: 你好
    date: 2026-10-02
    tags: [a, b]
    draft: false
    ---
支持字符串（可加引号）、整数、浮点数、布尔、[a, b] 行内列表
与 "- " 开头的多行列表。
"""

from __future__ import annotations

import re

_KEYVAL = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")


def split(text: str) -> tuple[dict, str]:
    """分离 front matter 与正文，返回 (meta, body)。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() in ("---", "..."):
            end = idx
            break
    if end is None:
        return {}, text
    meta = _parse("\n".join(lines[1:end]))
    return meta, "\n".join(lines[end + 1:])


def _parse(src: str) -> dict:
    data: dict = {}
    current_key: str | None = None
    for raw in src.split("\n"):
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = _KEYVAL.match(line)
        if m and not line[:1].isspace():
            key, val = m.group(1), m.group(2).strip()
            if val == "":
                data[key] = []
                current_key = key
            elif val.startswith("[") and val.endswith("]"):
                data[key] = _split_list(val[1:-1])
                current_key = None
            else:
                data[key] = _coerce(_strip_comment(val))
                current_key = None
        elif (
            line.strip().startswith("- ")
            and current_key is not None
            and isinstance(data.get(current_key), list)
        ):
            data[current_key].append(_coerce(line.strip()[2:].strip()))
        else:
            current_key = None
    return data


def _strip_comment(val: str) -> str:
    """去掉引号外的行尾注释（` # ...`），引号内的 # 保留。"""
    in_single = in_double = False
    for i, ch in enumerate(val):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif (
            ch == "#"
            and not in_single
            and not in_double
            and i > 0
            and val[i - 1] in " \t"
        ):
            return val[:i].rstrip()
    return val


def _split_list(inner: str) -> list:
    """切分行内列表，引号内的逗号不分割。"""
    items: list[str] = []
    buf: list[str] = []
    in_single = in_double = False
    for ch in inner:
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
        elif ch == "," and not in_single and not in_double:
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    items.append("".join(buf))
    return [
        _coerce(_strip_comment(item.strip()))
        for item in items
        if item.strip()
    ]


def _coerce(value: str):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    low = value.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "none", "~"):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value
