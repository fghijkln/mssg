"""mssg 自研模板引擎（零依赖，只用标准库）。

支持的语法：
    {{ name }} / {{ page.title }}        变量（支持点号取值，缺失则为空）
    {% for post in posts %} ... {% endfor %}
    {% if x %} ... {% elif y %} ... {% else %} ... {% endif %}

if 条件支持：变量真值、not x、a == b、a != b（b 可为引号字符串、数字或变量）。
for 循环体内可用 loop.index（从 1 计）与 loop.index0（从 0 计）。
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"({{.*?}}|{%.*?%})", re.S)
_FOR = re.compile(r"for\s+(\w+)\s+in\s+([\w.]+)$")


def render(template: str, ctx: dict) -> str:
    tokens = _TOKEN.split(template)
    nodes, _ = _parse(list(tokens), 0, ())
    return "".join(node.render(ctx) for node in nodes)


def _resolve(name: str, ctx: dict):
    parts = name.split(".")
    val = ctx
    for part in parts:
        if isinstance(val, dict) and part in val:
            val = val[part]
        elif hasattr(val, part):
            val = getattr(val, part)
        else:
            return ""
    return val


def _is_truthy(val) -> bool:
    if val is None or val is False:
        return False
    if isinstance(val, (str, list, dict, tuple)) and len(val) == 0:
        return False
    if val == 0:
        return False
    return True


def _literal(token: str, ctx: dict):
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    return _resolve(token, ctx)


def _eval_cond(cond: str, ctx: dict) -> bool:
    cond = cond.strip()
    if cond.startswith("not "):
        return not _is_truthy(_resolve(cond[4:].strip(), ctx))
    for op in ("==", "!="):
        if op in cond:
            left, right = cond.split(op, 1)
            lv, rv = _literal(left, ctx), _literal(right, ctx)
            result = lv == rv
            return result if op == "==" else not result
    return _is_truthy(_resolve(cond, ctx))


class _Text:
    def __init__(self, s: str):
        self.s = s

    def render(self, ctx: dict) -> str:
        return self.s


class _Var:
    def __init__(self, name: str):
        self.name = name

    def render(self, ctx: dict) -> str:
        val = _resolve(self.name, ctx)
        return "" if val is None else str(val)


class _For:
    def __init__(self, var: str, iter_name: str, body: list):
        self.var = var
        self.iter_name = iter_name
        self.body = body

    def render(self, ctx: dict) -> str:
        seq = _resolve(self.iter_name, ctx)
        try:
            items = list(seq)
        except TypeError:
            return ""
        out = []
        for idx, item in enumerate(items):
            child = dict(ctx)
            child[self.var] = item
            child["loop"] = {"index": idx + 1, "index0": idx}
            out.append("".join(node.render(child) for node in self.body))
        return "".join(out)


class _If:
    def __init__(self, branches: list):
        # [(cond_str | None, body)]，cond 为 None 表示 else 分支
        self.branches = branches

    def render(self, ctx: dict) -> str:
        for cond, body in self.branches:
            if cond is None or _eval_cond(cond, ctx):
                return "".join(node.render(ctx) for node in body)
        return ""


def _tag_keyword(inner: str) -> str:
    parts = inner.split()
    return parts[0] if parts else ""


def _parse(tokens: list, pos: int, stops: tuple) -> tuple[list, int]:
    nodes: list = []
    while pos < len(tokens):
        tok = tokens[pos]
        if tok.startswith("{{"):
            nodes.append(_Var(tok[2:-2].strip()))
            pos += 1
        elif tok.startswith("{%"):
            inner = tok[2:-2].strip()
            if _tag_keyword(inner) in stops:
                return nodes, pos
            if inner.startswith("for "):
                m = _FOR.match(inner)
                if not m:
                    raise ValueError("模板 for 语法错误：%s" % inner)
                body, pos = _parse(tokens, pos + 1, ("endfor",))
                pos += 1  # 跳过 endfor
                nodes.append(_For(m.group(1), m.group(2), body))
            elif inner.startswith("if "):
                branches = []
                cond: str | None = inner[3:].strip()
                while True:
                    body, pos = _parse(tokens, pos + 1, ("elif", "else", "endif"))
                    branches.append((cond, body))
                    inner2 = tokens[pos][2:-2].strip()
                    kw = _tag_keyword(inner2)
                    if kw == "endif":
                        pos += 1
                        break
                    if kw == "else":
                        cond = None
                    else:  # elif <cond>
                        cond = inner2[len("elif"):].strip()
                nodes.append(_If(branches))
            else:
                raise ValueError("未知模板标签：%s" % inner)
        else:
            nodes.append(_Text(tok))
            pos += 1
    if stops:
        raise ValueError("模板缺少结束标签：%s" % (stops,))
    return nodes, pos
