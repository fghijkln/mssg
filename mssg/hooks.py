"""插件钩子系统。

站点根目录下建 `plugins/`，每个 `*.py` 即一个插件，两种注册方式：

    # plugins/myplugin.py
    def page_html(page, html):
        return html.replace("</body>", "<!-- hi --></body>")

    HOOKS = {"page_html": page_html}

或定义 `register(hooks)` 函数。构建时自动加载（serve 监听下改插件即生效）。

事件：
  build_started(site)        构建开始（配置与插件已加载）
  page_read(page)            页面元数据读入后触发（只有标题/日期/标签等，
                             正文尚未解析为 HTML；草稿不触发）。如需处理
                             渲染后的 HTML 请用 page_html。
  page_html(page, html)      内容页渲染后，返回处理过的 HTML（链式）
  build_finished(site, result) 构建结束，result 为 build() 返回的字典

注意：页面渲染在线程池中进行，钩子函数须线程安全。
插件加载失败（ImportError 等）会直接中断构建并报错。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

EVENTS = ("build_started", "page_read", "page_html", "build_finished")


class Hooks:
    def __init__(self):
        self._handlers = {e: [] for e in EVENTS}

    def register(self, event: str, fn) -> None:
        if event not in self._handlers:
            raise ValueError(
                "未知钩子事件 %r，可用：%s" % (event, ", ".join(EVENTS))
            )
        self._handlers[event].append(fn)

    def run(self, event: str, *args, **kwargs) -> list:
        """触发事件，返回各处理函数的返回值列表。"""
        return [fn(*args, **kwargs) for fn in self._handlers[event]]

    def filter_html(self, event: str, page: dict, html: str) -> str:
        """链式 HTML 过滤：每个处理函数接收 (page, html) 并返回新 html。"""
        for fn in self._handlers[event]:
            html = fn(page, html)
        return html

    def load_dir(self, plugins_dir: str | Path) -> list:
        """加载插件目录，返回加载的插件名列表。"""
        d = Path(plugins_dir)
        if not d.is_dir():
            return []
        loaded = []
        for py in sorted(d.glob("*.py")):
            if py.name.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(
                "mssg_plugin_" + py.stem, py
            )
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
            except Exception as e:
                raise ValueError("插件加载失败 %s：%s" % (py.name, e))
            if hasattr(mod, "register"):
                mod.register(self)
            hooks = getattr(mod, "HOOKS", {}) or {}
            for event, fn in hooks.items():
                self.register(event, fn)
            loaded.append(py.stem)
        return loaded
