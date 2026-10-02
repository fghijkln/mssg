"""YAML 子集解析/生成（零依赖，专为 front matter 设计）。

支持的子集（覆盖真实 front matter 的 99% 用法）：
  - key: value（Unicode 键名，如中文键）
  - 标量：字符串（可加单/双引号）、整数、浮点数、
    布尔（true/false/yes/no/on/off，不区分大小写）、
    null（null/~//空）、ISO 日期（2026-10-02 → datetime.date，与 PyYAML 一致）
  - 行内列表：tags: [a, b]（引号内逗号保留）
  - 多行列表：
      tags:
        - a
        - b
  - 嵌套字典（缩进）：
      author:
        name: 小王
  - | 字面量块（多行字符串）
  - # 注释：整行注释；值内 # 在引号外且位于开头或空白之后时为注释

不支持（会如实报错或按字符串处理）：锚点/别名、!tag、多行流式、
复杂嵌套。复杂数据请用 data/ 下的 .toml/.json。
"""
from __future__ import annotations

import re
from datetime import date

_BOOL = {
    "true": True, "yes": True, "on": True,
    "false": False, "no": False, "off": False,
}
_NULL = {"null", "~", ""}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")


def _strip_comment(val: str) -> str:
    """去掉引号外的行尾注释（引号内的 # 保留）。

    # 在值开头或空白之后出现时视为注释开始（`a#b` 里的 # 不是注释）。
    """
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
            and (i == 0 or val[i - 1] in " \t")
        ):
            return val[:i].rstrip()
    return val


def _split_list(inner: str) -> list:
    """行内列表逗号切分（引号内逗号保留）。"""
    items, buf = [], []
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
        if item.strip() and _strip_comment(item.strip()) != ""
    ]


def _unquote(s: str) -> tuple:
    """去引号，返回 (value, was_quoted)。"""
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        q = s[0]
        inner = s[1:-1]
        if q == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        else:
            inner = inner.replace("''", "'")
        return inner, True
    return s, False


def _coerce(val: str):
    """标量类型推断（引号包裹的一律按字符串处理）。"""
    val = val.strip()
    unquoted, was_quoted = _unquote(val)
    if was_quoted:
        return unquoted
    low = unquoted.lower()
    if low in _NULL:
        return None
    if low in _BOOL:
        return _BOOL[low]
    if _DATE_RE.match(unquoted):
        try:
            y, m, d = (int(x) for x in unquoted.split("-"))
            return date(y, m, d)
        except ValueError:
            pass
    if _INT_RE.match(unquoted):
        try:
            return int(unquoted)
        except ValueError:
            pass
    if _FLOAT_RE.match(unquoted):
        try:
            return float(unquoted)
        except ValueError:
            pass
    return unquoted


def _parse_block(lines: list, start: int, indent: int) -> tuple:
    """解析一个缩进层级的块，返回 (value, next_index)。

    value 为 dict（key: ... 行）或 list（- ... 行）。
    """
    i = start
    # 先看第一行判定类型
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if not s or s.startswith("#"):
            i += 1
            continue
        cur_indent = len(raw) - len(raw.lstrip(" "))
        if cur_indent < indent:
            break
        if s.startswith("- ") or s == "-":
            return _parse_list(lines, i, cur_indent)
        else:
            return _parse_dict(lines, i, cur_indent)
    return {}, i


def _parse_list(lines: list, start: int, indent: int) -> tuple:
    items = []
    i = start
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if not s or s.startswith("#"):
            i += 1
            continue
        cur_indent = len(raw) - len(raw.lstrip(" "))
        if cur_indent < indent or not (s.startswith("- ") or s == "-"):
            break
        item = s[1:].strip()
        if item == "":
            # "- " 后面是嵌套块
            val, i = _parse_block(lines, i + 1, indent + 2)
            items.append(val)
        else:
            items.append(_coerce(_strip_comment(item)))
            i += 1
    return items, i


def _parse_dict(lines: list, start: int, indent: int) -> tuple:
    data: dict = {}
    i = start
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if not s or s.startswith("#"):
            i += 1
            continue
        cur_indent = len(raw) - len(raw.lstrip(" "))
        if cur_indent < indent:
            break
        if cur_indent > indent:
            # 缩进异常：上一行已处理完嵌套，这里属于更深的块，交回去
            break
        if s.startswith("- ") or s == "-":
            break  # 调用方是 dict，这里出现列表项：交回去
        # key: value（键取第一个冒号之前，值可含冒号如 http://）
        if ":" not in s:
            i += 1
            continue
        key, _, val = s.partition(":")
        key = key.strip()
        val = val.strip()
        if not key:
            i += 1
            continue
        if val in ("|", ">"):
            # 字面量/折叠块：收集更深缩进的行
            i += 1
            buf = []
            while i < len(lines):
                r2 = lines[i]
                if not r2.strip():
                    buf.append("")
                    i += 1
                    continue
                ind2 = len(r2) - len(r2.lstrip(" "))
                if ind2 <= indent:
                    break
                buf.append(r2.strip())
                i += 1
            # 去掉首尾空行
            while buf and not buf[0]:
                buf.pop(0)
            while buf and not buf[-1]:
                buf.pop()
            data[key] = "\n".join(buf) + ("\n" if buf else "")
            continue
        if val.startswith("[") and val.endswith("]"):
            data[key] = _split_list(val[1:-1])
            i += 1
            continue
        if val == "":
            # 值在下一缩进块；无内容时为 None（与 PyYAML 一致）
            val_parsed, i = _parse_block(lines, i + 1, indent + 1)
            data[key] = val_parsed if val_parsed != {} else None
            continue
        data[key] = _coerce(_strip_comment(val))
        i += 1
    return data, i


def loads(text: str) -> dict:
    """解析 YAML 子集文本为 dict（非 dict/解析失败返回 {}）。"""
    try:
        data, _ = _parse_dict(text.split("\n"), 0, 0)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _dump_scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if (
        not s
        or s[0] in " \t\"'#"
        or s[-1] in " \t"
        or any(c in s for c in ":#{}[],&*!|>'\"%@`")
        or s.lower() in _BOOL
        or s.lower() in _NULL
        or _DATE_RE.match(s)
        or _INT_RE.match(s)
        or _FLOAT_RE.match(s)
    ):
        return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')
    return s


def dumps(data: dict) -> str:
    """dict → YAML 子集文本（admin 写 front matter 用）。"""
    lines = []
    for k, v in data.items():
        if isinstance(v, dict):
            lines.append("%s:" % k)
            for sk, sv in v.items():
                lines.append("  %s: %s" % (sk, _dump_scalar(sv)))
        elif isinstance(v, list):
            if v and any(isinstance(x, dict) for x in v):
                lines.append("%s:" % k)
                for x in v:
                    lines.append("  - %s" % _dump_scalar(x))
            else:
                lines.append(
                    "%s: [%s]" % (k, ", ".join(_dump_scalar(x) for x in v))
                )
        else:
            lines.append("%s: %s" % (k, _dump_scalar(v)))
    return "\n".join(lines) + "\n"
