"""模板引擎（基于 Jinja2 第三方库）。

API（与旧自研引擎兼容）：
  render(template_str, ctx, templates=None)  -> 渲染字符串模板
  render_template(name, ctx, templates)       -> 按名称渲染（支持继承/include）

Jinja2 原生支持：{{ }}、{% if/for/elif/else %}、{# 注释 #}、
{% extends %}/{% block %}、{% include %}、loop.index/loop.index0，
以及 upper/lower/title/trim/escape/striptags/join/first/last/
length/default/replace/truncate 等内置过滤器。
mssg 额外注册：date(fmt)（"2026-10-02" → 按格式输出）。
"""

from __future__ import annotations

from datetime import datetime

from jinja2 import BaseLoader, DictLoader, Environment, TemplateError, TemplateNotFound


class _CallableLoader(BaseLoader):
    """兼容旧 API：loader 为 name -> 源码（找不到返回 None）的可调用对象。"""

    def __init__(self, fn):
        self.fn = fn

    def get_source(self, environment, template):
        src = self.fn(template)
        if src is None:
            raise TemplateNotFound(template)
        return src, template, lambda: True


def _f_date(value, fmt="%Y-%m-%d") -> str:
    s = str(value).strip()
    for p in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(s, p).strftime(str(fmt))
        except ValueError:
            continue
    return s


def _make_env(templates) -> Environment:
    if templates is None:
        loader = DictLoader({})
    elif isinstance(templates, dict):
        loader = DictLoader(dict(templates))
    elif callable(templates):
        loader = _CallableLoader(templates)
    else:
        raise TypeError("templates 须为 dict、loader 可调用对象或 None")
    env = Environment(
        loader=loader,
        autoescape=False,  # 页面内容是已生成的 HTML，不转义
    )
    env.filters["date"] = _f_date
    return env


def render(template_str: str, ctx: dict, templates: dict | None = None) -> str:
    """渲染模板字符串。模板错误统一转为 ValueError。"""
    env = _make_env(templates)
    try:
        return env.from_string(template_str).render(dict(ctx or {}))
    except RecursionError:
        raise ValueError("模板嵌套过深或存在循环引用（超过 Python 递归限制）")
    except TemplateError as e:
        raise ValueError("模板错误：%s" % e)


def render_template(name: str, ctx: dict, templates: dict) -> str:
    """按名称渲染模板（支持 extends/include 跨模板引用）。模板错误统一转为 ValueError。"""
    env = _make_env(templates)
    try:
        return env.get_template(name).render(dict(ctx or {}))
    except RecursionError:
        raise ValueError("模板嵌套过深或存在循环引用（超过 Python 递归限制）")
    except TemplateError as e:
        raise ValueError("模板错误 [%s]：%s" % (name, e))
