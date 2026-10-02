"""mssg 自研模板引擎（零依赖，只用标准库）。

支持的语法：
    {{ name }} / {{ page.title }}        变量（支持点号取值，缺失则为空）
    {% for post in posts %} ... {% endfor %}
    {% if x %} ... {% elif y %} ... {% else %} ... {% endif %}

if 条件支持：变量真值、not x、a == b、a != b（b 可为引号字符串、数字或变量）。
for 循环体内可用 loop.index（从 1 计）与 loop.index0（从 0 计）。
{# ... #} 为注释，原样丢弃。
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"({{.*?}}|{%.*?%}|{#.*?#})", re.S)
_FOR = re.compile(r"for\s+(\w+)\s+in\s+([\w.]+)$")


def render(template: str, ctx: dict, loader=None) -> str:
    """渲染模板字符串。

    若模板首标签为 {% extends "parent.html" %}，则按继承链渲染，
    需要 loader(name) -> 模板源码（找不到返回 None）。
    """
    try:
        return _do_render(template, ctx, loader, "<string>", ())
    except RecursionError:
        raise ValueError("模板嵌套过深（超过 Python 递归限制）")


def render_template(name: str, ctx: dict, loader) -> str:
    """按名称渲染模板（支持继承），loader(name) 返回源码或 None。"""
    src = loader(name)
    if src is None:
        raise ValueError("找不到模板：%s" % name)
    try:
        return _do_render(src, ctx, loader, name, ())
    except RecursionError:
        raise ValueError("模板嵌套过深（超过 Python 递归限制）")


def _do_render(src: str, ctx: dict, loader, name: str, seen: tuple) -> str:
    if name in seen:
        raise ValueError("模板继承循环：%s" % " -> ".join([*seen, name]))
    extends, nodes, blocks = _parse_template(src, loader)
    if extends is None:
        child_ctx = dict(ctx)
        child_ctx.setdefault("__blocks__", blocks)
        return "".join(node.render(child_ctx) for node in nodes)
    if loader is None:
        raise ValueError("模板使用了 {%% extends %%} 但未提供 loader")
    top_nodes, merged = _resolve_parent(extends, loader, (*seen, name))
    merged = dict(merged)
    merged.update(blocks)  # 子模板的 block 覆盖父模板
    child_ctx = dict(ctx)
    child_ctx["__blocks__"] = merged
    return "".join(node.render(child_ctx) for node in top_nodes)


def _resolve_parent(name: str, loader, seen: tuple) -> tuple[list, dict]:
    """沿继承链向上解析，返回 (顶层父模板节点, 合并后的 blocks)。"""
    if name in seen:
        raise ValueError("模板继承循环：%s" % " -> ".join([*seen, name]))
    src = loader(name)
    if src is None:
        raise ValueError("找不到父模板：%s" % name)
    extends, nodes, blocks = _parse_template(src, loader)
    if extends is None:
        return nodes, blocks
    top_nodes, parent_blocks = _resolve_parent(extends, loader, (*seen, name))
    merged = dict(parent_blocks)
    merged.update(blocks)
    return top_nodes, merged


def _parse_template(src: str, loader) -> tuple[str | None, list, dict]:
    """解析模板源码，返回 (extends 父模板名|None, 节点, blocks)。"""
    tokens = list(_TOKEN.split(src))
    extends = None
    for tok in tokens:
        if tok.startswith("{%"):
            inner = tok[2:-2].strip()
            if _tag_keyword(inner) == "extends":
                m = re.match(r"""extends\s+["']([^"']+)["']$""", inner)
                if not m:
                    raise ValueError("extends 语法错误：%s" % inner)
                extends = m.group(1)
            break  # 只看第一个 {% 标签
        # {{、{#、纯文本：继续向后找
    blocks: dict = {}
    nodes, _ = _parse(tokens, 0, (), blocks, loader, _skip_extends=extends is not None)
    return extends, nodes, blocks


def _resolve(name: str, ctx: dict):
    parts = name.split(".")
    val = ctx
    for part in parts:
        if isinstance(val, dict) and part in val:
            val = val[part]
        elif hasattr(val, part):
            attr = getattr(val, part)
            if callable(attr):
                return ""  # 方法/函数不暴露，避免输出 <built-in method …>
            val = attr
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


class _Block:
    def __init__(self, name: str, body: list):
        self.name = name
        self.body = body

    def render(self, ctx: dict) -> str:
        override = ctx.get("__blocks__", {}).get(self.name)
        body = override.body if override is not None else self.body
        return "".join(node.render(ctx) for node in body)


class _Include:
    def __init__(self, name: str, loader):
        self.name = name
        self.loader = loader

    def render(self, ctx: dict) -> str:
        seen = ctx.get("__include_seen__", ())
        if self.name in seen:
            raise ValueError(
                "模板 include 循环：%s" % " -> ".join([*seen, self.name])
            )
        src = self.loader(self.name)
        if src is None:
            raise ValueError("找不到被引入的模板：%s" % self.name)
        extends, nodes, blocks = _parse_template(src, self.loader)
        if extends is not None:
            raise ValueError("被 include 的模板不能使用 extends：%s" % self.name)
        child = dict(ctx)
        child["__blocks__"] = blocks
        child["__include_seen__"] = (*seen, self.name)
        return "".join(node.render(child) for node in nodes)


def _tag_keyword(inner: str) -> str:
    parts = inner.split()
    return parts[0] if parts else ""


def _parse(
    tokens: list,
    pos: int,
    stops: tuple,
    blocks: dict,
    loader,
    _skip_extends: bool = False,
) -> tuple[list, int]:
    nodes: list = []
    seen_tag = False
    while pos < len(tokens):
        tok = tokens[pos]
        if tok.startswith("{#"):
            seen_tag = True
            pos += 1  # 注释：丢弃
        elif tok.startswith("{{"):
            seen_tag = True
            nodes.append(_Var(tok[2:-2].strip()))
            pos += 1
        elif tok.startswith("{%"):
            inner = tok[2:-2].strip()
            kw = _tag_keyword(inner)
            if kw in stops:
                return nodes, pos
            if kw == "extends":
                if _skip_extends and not seen_tag:
                    # 作为首个标签的 extends：已由 _parse_template 处理，这里跳过
                    _skip_extends = False
                    seen_tag = True
                    pos += 1
                    continue
                raise ValueError("extends 必须为模板的第一个标签")
            seen_tag = True
            if inner.startswith("for "):
                m = _FOR.match(inner)
                if not m:
                    raise ValueError("模板 for 语法错误：%s" % inner)
                body, pos = _parse(tokens, pos + 1, ("endfor",), blocks, loader)
                pos += 1  # 跳过 endfor
                nodes.append(_For(m.group(1), m.group(2), body))
            elif inner.startswith("if "):
                branches = []
                cond: str | None = inner[3:].strip()
                seen_else = False
                while True:
                    body, pos = _parse(
                        tokens, pos + 1, ("elif", "else", "endif"), blocks, loader
                    )
                    branches.append((cond, body))
                    inner2 = tokens[pos][2:-2].strip()
                    kw2 = _tag_keyword(inner2)
                    if kw2 == "endif":
                        pos += 1
                        break
                    if kw2 in ("elif", "else") and seen_else:
                        raise ValueError("else 之后不能再出现 elif/else")
                    if kw2 == "else":
                        seen_else = True
                        cond = None
                    else:  # elif <cond>
                        cond = inner2[len("elif"):].strip()
                nodes.append(_If(branches))
            elif kw == "block":
                name = inner[len("block"):].strip()
                if not name or not re.match(r"^\w+$", name):
                    raise ValueError("block 语法错误：%s" % inner)
                body, pos = _parse(tokens, pos + 1, ("endblock",), blocks, loader)
                pos += 1  # 跳过 endblock
                node = _Block(name, body)
                if name not in blocks:
                    blocks[name] = node
                nodes.append(node)
            elif kw == "include":
                m = re.match(r"""include\s+["']([^"']+)["']$""", inner)
                if not m:
                    raise ValueError("include 语法错误：%s" % inner)
                if loader is None:
                    raise ValueError("include 需要提供 loader")
                nodes.append(_Include(m.group(1), loader))
                pos += 1
            else:
                raise ValueError("未知模板标签：%s" % inner)
        else:
            nodes.append(_Text(tok))
            pos += 1
    if stops:
        raise ValueError("模板缺少结束标签：%s" % (stops,))
    return nodes, pos
