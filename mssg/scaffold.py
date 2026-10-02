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
title = "让小团队跑出大公司的速度"
subtitle = "星尘协作把任务、文档、发布装进一个工具箱——从想法到上线，只差一次构建。"
cta_text = "了解产品"
cta_url = "/products.html"
cta2_text = "联系我们"
cta2_url = "/about.html#contact"

# 首页特性卡片（增删改后重新 build 即可）
[[site.features]]
title = "星尘协作"
text = "任务看板与文档二合一，多人实时协同，告别工具碎片化。"
[[site.features]]
title = "星尘发布"
text = "秒级构建的静态站点发布，写完 Markdown，一键上线全球。"
[[site.features]]
title = "星尘洞察"
text = "实时同步的业务看板，让每一次复盘都有数可查。"

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

# 多语言：about.en.md 这类文件输出到 en/ 目录，
# [site.en] 深层覆盖英文版站点文案（标题/菜单/hero/特性卡等），
# 导航栏右上角自动出现语言切换器。
[i18n]
default = "zh"
langs = ["zh", "en"]

[site.en]
title = "Stardust"
description = "Stardust builds collaboration tools for small teams, turning ideas into products."
[[site.en.menu]]
name = "Home"
url = "/en/"
weight = 1
[[site.en.menu]]
name = "Products"
url = "/en/products.html"
weight = 2
[[site.en.menu]]
name = "News"
url = "/en/#news"
weight = 3
[[site.en.menu]]
name = "About"
url = "/en/about.html"
weight = 4
[[site.en.menu]]
name = "Contact"
url = "/en/contact.html"
weight = 5
[[site.en.menu]]
name = "Search"
url = "/en/search.html"
weight = 6
[site.en.hero]
title = "Small team, big-company speed"
subtitle = "Stardust packs tasks, docs, and publishing into one toolbox — from idea to launch in a single build."
cta_text = "Our products"
cta_url = "/en/products.html"
cta2_text = "Contact us"
cta2_url = "/en/about.html#contact"
[[site.en.features]]
title = "Stardust Collab"
text = "Kanban plus docs in one place, real-time collaboration, no more tool sprawl."
[[site.en.features]]
title = "Stardust Publish"
text = "Lightning-fast static site publishing — write Markdown, go global in one click."
[[site.en.features]]
title = "Stardust Insights"
text = "Real-time dashboards, so every review is backed by numbers."
[site.en.contact]
email = "hi@example.com"
phone = "400-000-0000"
[site.en.footer]
text = "© 2026 Stardust"

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

星尘科技成立于 2026 年，是一家专注于云端协作工具的公司。我们相信：**小团队也值得拥有大公司的效率**。

## 我们在做什么

- **星尘协作**：任务看板与文档二合一，告别工具碎片化。
- **星尘发布**：秒级构建的静态站点发布，写完即上线。
- **星尘洞察**：实时数据看板，让每一次决策都有据可依。

## 联系方式 {#contact}

- 邮箱：hi@example.com
- 电话：400-000-0000

欢迎随时联系我们，聊聊你的想法。
""",
        encoding="utf-8",
    )
    (root / "content" / "products.md").write_text(
        """\
---
title: 产品介绍
date: 2026-10-02
---

三款产品，一套工作流。从想法到上线，全程陪伴。

## 星尘协作

为小团队打造的一站式协作平台：

- 任务看板，开箱即用
- 文档与知识库二合一
- 多人实时协同，零学习成本

## 星尘发布

```python
print("你好，星尘")
```

秒级构建的静态站点发布：写完 Markdown，一键上线全球。

## 星尘洞察

> 数据不会说谎，但需要有人替它开口。

实时同步的业务看板，让每一次复盘都有数可查。
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

欢迎来到星尘科技的官方博客。这是我们的第一篇文章，也是一次小小的宣言：**mssg** 让建站回归简单。

## 为什么是静态站点

- **快**：没有数据库，没有后端，全球 CDN 秒开。
- **稳**：纯文件部署，几乎零运维。
- **美**：Markdown 写作，主题一键换肤。

```python
print("你好，世界")
```

> 纸上得来终觉浅，绝知此事要躬行。

敬请期待更多分享。
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
    # 英文版示范内容（输出到 en/ 目录）
    (root / "content" / "about.en.md").write_text(
        """\
---
title: About Us
date: 2026-10-02
---

Founded in 2026, Stardust builds cloud collaboration tools for small teams. We believe **small teams deserve big-company efficiency**.

## What we do

- **Stardust Collab**: kanban plus docs in one place, no more tool sprawl.
- **Stardust Publish**: lightning-fast static publishing — write it, ship it.
- **Stardust Insights**: real-time dashboards, so every decision is data-backed.

## Contact {#contact}

- Email: hi@example.com
- Phone: 400-000-0000

Drop us a line — we'd love to hear your ideas.
""",
        encoding="utf-8",
    )
    (root / "content" / "products.en.md").write_text(
        """\
---
title: Products
date: 2026-10-02
---

Three products, one workflow. From idea to launch, we've got you covered.

## Stardust Collab

The all-in-one collaboration platform for small teams:

- Kanban boards, ready out of the box
- Docs and knowledge base in one
- Real-time collaboration, zero learning curve

## Stardust Publish

```python
print("Hello, Stardust")
```

Lightning-fast static site publishing: write Markdown, go global in one click.

## Stardust Insights

> Data never lies — but someone has to speak for it.

Real-time business dashboards for reviews backed by numbers.
""",
        encoding="utf-8",
    )
    (root / "content" / "hello.en.md").write_text(
        """\
---
title: Hello, World
date: 2026-10-02
tags: [mssg, demo]
---

Welcome to the official Stardust blog. This is our first post — and a small manifesto: **mssg** makes site-building simple again.

## Why static sites

- **Fast**: no database, no backend, served over global CDN in a blink.
- **Reliable**: pure file deployment, near-zero ops.
- **Beautiful**: write in Markdown, re-skin with one theme switch.

```python
print("Hello, World")
```

> What we learn from paper remains shallow; true knowledge comes from practice.

Stay tuned for more.
""",
        encoding="utf-8",
    )
    (root / "content" / "contact.en.md").write_text(
        """\
---
title: Contact Us
date: 2026-10-02
template: contact.html
---

Drop us a message below — we'll get back to you shortly.
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
