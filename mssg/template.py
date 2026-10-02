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

import hashlib
import threading
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
    env.filters["menu_sort"] = _f_menu_sort
    env.globals["asset"] = _asset_global
    return env


def _f_menu_sort(items) -> list:
    """按 weight 排序菜单（缺 weight 视为 0，不炸模板）。"""

    def _w(m):
        try:
            return int((m or {}).get("weight", 0))
        except (TypeError, ValueError):
            return 0

    return sorted(items or [], key=_w)


_asset_resolver = None
"""当前构建的资源解析函数：path → 输出 URL。由 Site.build() 设置。"""


def set_asset_resolver(fn) -> None:
    """设置当前构建的 asset 解析函数（fingerprint 映射）。"""
    global _asset_resolver
    _asset_resolver = fn


def _asset_global(path: str) -> str:
    """模板全局函数：{{ asset("css/style.css") }} → 指纹 URL 或原路径。"""
    r = _asset_resolver
    if r is None:
        return path
    return r(path)


def render(template_str: str, ctx: dict, templates: dict | None = None) -> str:
    """渲染模板字符串。模板错误统一转为 ValueError。"""
    env = _make_env(templates)
    try:
        return env.from_string(template_str).render(dict(ctx or {}))
    except RecursionError:
        raise ValueError("模板嵌套过深或存在循环引用（超过 Python 递归限制）")
    except TemplateError as e:
        raise ValueError("模板错误：%s" % e)


_ENV_CACHE: dict = {}
_ENV_LOCK = threading.Lock()
_ENV_CACHE_MAX = 8


def _templates_digest(templates: dict) -> str:
    h = hashlib.sha1()
    for name in sorted(templates):
        h.update(name.encode("utf-8"))
        h.update(b"\x00")
        h.update(templates[name].encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _cached_env(templates: dict) -> Environment:
    """按模板内容缓存 Environment，避免每次渲染重编译（线程安全）。

    Jinja2 的 Environment.get_template/render 并发调用是线程安全的。
    """
    digest = _templates_digest(templates)
    env = _ENV_CACHE.get(digest)
    if env is None:
        with _ENV_LOCK:
            env = _ENV_CACHE.get(digest)
            if env is None:
                env = _make_env(templates)
                _ENV_CACHE[digest] = env
                while len(_ENV_CACHE) > _ENV_CACHE_MAX:
                    _ENV_CACHE.pop(next(iter(_ENV_CACHE)))
    return env


def render_template(name: str, ctx: dict, templates: dict) -> str:
    """按名称渲染模板（支持 extends/include 跨模板引用）。模板错误统一转为 ValueError。

    同一批模板的 Environment 会被缓存复用，不重复编译。
    （templates 为可调用 loader 时不缓存，保持旧行为。）
    """
    env = _cached_env(templates) if isinstance(templates, dict) else _make_env(templates)
    try:
        return env.get_template(name).render(dict(ctx or {}))
    except RecursionError:
        raise ValueError("模板嵌套过深或存在循环引用（超过 Python 递归限制）")
    except TemplateError as e:
        raise ValueError("模板错误 [%s]：%s" % (name, e))
