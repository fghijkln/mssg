"""站点脚手架：mssg new 生成的目录结构与示例内容。

模板与主题静态资源来自内置主题（mssg/themes/<theme>/），不在站点里复制；
换主题只改 mssg.toml 里 [site] theme。
"""
from __future__ import annotations

from pathlib import Path

from .themes import available_themes


def new_site(name: str | Path, theme: str = "company") -> Path:
    """生成站点脚手架，返回站点根目录。目标为非空目录时拒绝覆盖。

    模板与主题静态资源来自内置主题（mssg/themes/<theme>/），不在站点里
    复制一份；换主题只改 mssg.toml 里 [site] theme。想微调单个模板时，
    在站点 templates/ 下放同名文件即可覆盖主题的对应文件。
    """
    if theme not in available_themes():
        raise ValueError(
            "未知主题 %r，可用主题：%s" % (theme, ", ".join(available_themes()))
        )
    root = Path(name)
    if root.is_file():
        raise FileExistsError("目标已存在且为文件，拒绝覆盖：%s" % root)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError("目录已存在且非空，拒绝覆盖：%s" % root)
    (root / "content").mkdir(parents=True, exist_ok=True)
    (root / "static").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)

    (root / "data" / "links.json").write_text(
        '{\n  "items": [\n    {"name": "示例", "url": "https://example.com"}\n  ]\n}\n',
        encoding="utf-8",
    )

    (root / "mssg.toml").write_text(
        """\
[site]
title = "星尘科技"
description = "星尘科技专注于云端协作工具，帮小团队把想法快速变成产品。"
base_url = ""
theme = "%s"  # 内置主题：company（公司站）/ minimal（极简风）/ novacore（深色科技风）；templates/ 下放同名文件可覆盖

# 导航菜单（按 weight 排序；children 可嵌套多级，hover/聚焦时下拉展开）
[[site.menu]]
name = "首页"
url = "/"
weight = 1
[[site.menu]]
name = "产品"
url = "/products.html"
weight = 2
# [[site.menu.children]]
# name = "手机"
# url = "/products/phone.html"
# weight = 1
# [[site.menu.children]]
# name = "电脑"
# url = "/products/pc.html"
# weight = 2
[[site.menu]]
name = "新闻"
url = "/#news"
weight = 3
[[site.menu]]
name = "关于"
url = "/about.html"
weight = 4
[[site.menu]]
name = "联系"
url = "/contact.html"
weight = 5
[[site.menu]]
name = "搜索"
url = "/search.html"
weight = 6

# 首页 hero 区
[site.hero]
title = "把想法变成产品"
subtitle = "开箱即用的协作工具，让小团队也能有大公司的效率。"
cta_text = "了解产品"
cta_url = "/products.html"
cta2_text = "联系我们"
cta2_url = "/about.html#contact"

# 首页特性卡片（增删改后重新 build 即可）
[[site.features]]
title = "开箱即用"
text = "一行命令建站，一次构建上线，不写一行后端代码。"
[[site.features]]
title = "极速构建"
text = "增量构建只重建改动过的页面，改完即刻预览。"
[[site.features]]
title = "SEO 友好"
text = "语义化 HTML、sitemap、RSS、Open Graph 标签开箱即备。"

# 联系方式（页脚与关于页共用）
[site.contact]
email = "hi@example.com"
phone = "400-000-0000"

[site.footer]
text = "© 2026 星尘科技"

# 联系表单：填入 Formspree / Getform 等第三方服务的 endpoint，
# 联系页（/contact.html）的表单即可用；留空则显示配置提示。
[site.form]
endpoint = ""
# endpoint = "https://formspree.io/f/xxxxxx"

# 多语言：取消注释启用英文版。about.en.md 这类文件会输出到 en/ 目录，
# [site.en] 覆盖英文版的站点文案（标题/菜单/hero 等）。
# [i18n]
# default = "zh"
# langs = ["zh", "en"]
#
# [site.en]
# title = "Stardust"
# description = "Stardust builds collaboration tools for small teams."

[build]
# per_page = 5  # 首页/标签页每页篇数；0 或不填则不分页
# 分页文件：首页 page/2.html…，标签页 tags/<tag>/2.html…
# image_max_width = 1600  # static/ 里的图片超过此宽度则缩放；0 表示不缩放
# image_quality = 82      # JPEG 压缩质量（1-95）
# search = false          # 设为 false 关闭站内搜索（search.json + /search.html）

# Markdown 扩展：默认 ["extra", "codehilite", "toc", "sane_lists"]，
# 可增删；extension_configs 透传给 Python-Markdown
# [markdown]
# extensions = ["extra", "codehilite", "toc", "sane_lists"]
# [markdown.extension_configs.codehilite]
# css_class = "codehilite"

# 插件：plugins/ 下每个 *.py 自动加载，可注册钩子
# （build_started / page_read / page_html / build_finished），
# 示例见 README 的"插件"一节。
""" % theme,
        encoding="utf-8",
    )

    (root / "content" / "about.md").write_text(
        """\
---
title: 关于我们
date: 2026-10-02
---

# 关于我们

星尘科技是一家专注于云端协作工具的公司，目标是让小团队也能有大公司的效率。

## 联系方式 {#contact}

- 邮箱：hi@example.com
- 电话：400-000-0000

欢迎随时联系我们。
""",
        encoding="utf-8",
    )
    (root / "content" / "products.md").write_text(
        """\
---
title: 产品介绍
date: 2026-10-02
---

# 产品介绍

## 星尘协作

为小团队打造的一站式协作平台：

- 任务看板，开箱即用
- 文档与知识库二合一
- 秒级构建的静态站点发布

```python
print("你好，星尘")
```

> 纸上得来终觉浅，绝知此事要躬行。
""",
        encoding="utf-8",
    )
    (root / "content" / "hello.md").write_text(
        """\
---
title: 你好，世界
date: 2026-10-02
tags: [mssg, 示例]
---

# 你好，世界

这是用 **mssg** 生成的第一篇文章。

- Markdown（含表格、脚注、代码高亮）
- Jinja2 模板（继承、循环、过滤器）
- YAML front matter
""",
        encoding="utf-8",
    )
    (root / "content" / "contact.md").write_text(
        """\
---
title: 联系我们
date: 2026-10-02
template: contact.html
---

欢迎通过下表给我们留言，我们会尽快回复。
""",
        encoding="utf-8",
    )
    (root / "content" / "draft.md").write_text(
        """\
---
title: 草稿示例
date: 2026-10-03
draft: true
---

# 草稿示例

这篇是草稿，`mssg build` 默认跳过，
`mssg build --drafts` 才会构建它。
""",
        encoding="utf-8",
    )
    return root
