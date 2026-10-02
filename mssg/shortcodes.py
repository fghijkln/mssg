"""Shortcodes：Markdown 里的 ``{{< name args >}}`` 模板标签。

在 Markdown 解析之前展开为 HTML（块级标签会被 Python-Markdown
原样透传）。未知 shortcode 保留原文并警告一次。

语法（Hugo ``{{< >}}`` 子集）：

    {{< youtube dQw4w9WgXcQ >}}
    {{< figure src="a.jpg" title="图注" >}}
    {{< image src="photo.jpg" width="800" alt="描述" >}}

自定义：在 ``templates/shortcodes/<name>.html``（站点覆盖主题）
放 Jinja2 模板，可用变量 ``args``（位置参数列表）、``kwargs``
（键值参数字典）、``page``、``site``。
"""
from __future__ import annotations

import re
import shlex

SHORTCODE_RE = re.compile(r"\{\{<\s*([A-Za-z][\w-]*)\s*(.*?)\s*>\}\}", re.S)


def parse_args(argstr: str) -> tuple:
    """解析参数串 → (args, kwargs)。支持 key="v"、key='v'、key=v 与位置参数。"""
    args: list = []
    kwargs: dict = {}
    if not argstr.strip():
        return args, kwargs
    for tok in shlex.split(argstr):
        if "=" in tok:
            k, _, v = tok.partition("=")
            k = k.strip()
            if k:
                kwargs[k] = v
            else:
                args.append(tok)
        else:
            args.append(tok)
    return args, kwargs


def expand(text: str, render) -> str:
    """展开文本中的 shortcode。

    render(name, args, kwargs) → html 或 None；
    返回 None 表示未知 shortcode，保留原文。
    """

    def repl(m: re.Match) -> str:
        name, argstr = m.group(1), m.group(2)
        try:
            args, kwargs = parse_args(argstr)
        except ValueError:
            return m.group(0)
        out = render(name, args, kwargs)
        return out if out is not None else m.group(0)

    return SHORTCODE_RE.sub(repl, text)
