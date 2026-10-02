# mssg

基于 Python-Markdown、Jinja2、PyYAML、Pygments 的静态站点生成器。
只做薄封装：Markdown 渲染、模板引擎、front matter 解析全部交给
久经考验的第三方库，mssg 自己只负责站点构建流程（增量构建、标签/
分类/归档、分页、feed、sitemap、文件监听）。

## 安装

需要 Python 3.11+。`pip install .` 会自动安装依赖
（Markdown、Jinja2、PyYAML、Pygments）。

## 快速开始

```bash
mssg new my-site        # 生成站点脚手架
cd my-site
mssg build              # 构建，输出到 public/
mssg serve              # 构建 + 本地预览 http://127.0.0.1:8000/
                        # serve 默认监听 content/templates/static/mssg.toml 的变化并自动重建
                        # （--no-watch 可关闭）
```

站点结构：

```
my-site/
  mssg.toml        # 配置（站点标题、目录等）
  content/         # Markdown 文章（支持 --- front matter ---）
  templates/       # base.html / page.html / index.html / tag.html / archive.html
  static/          # 原样拷贝到输出目录
  public/          # 构建产物
```

front matter 示例：

```markdown
---
title: 你好，世界
date: 2026-10-02
tags: [mssg, 示例]
draft: false
template: page.html
---

# 你好，世界

正文……
```

front matter 是完整 YAML（PyYAML 解析），支持嵌套结构、多行字符串、
日期自动识别等。注意 `date: 2026-10-02` 会被解析为日期对象，
模板里用 `{{ page.date }}` 输出时已转回字符串。

## 配置参考（mssg.toml）

```toml
[site]
title = "星尘科技"  # 站点标题，模板里用 {{ site.title }}
description = "一句话介绍"  # meta description / og:description
base_url = ""        # 站点根 URL，如 https://example.com（用于 feed/sitemap 绝对链接）

# 导航菜单（按 weight 排序，模板里用 site.menu|sort(attribute="weight")）
[[site.menu]]
name = "首页"
url = "/"
weight = 1
[[site.menu]]
name = "关于"
url = "/about.html"
weight = 2

# 首页 hero 区
[site.hero]
title = "把想法变成产品"
subtitle = "副标题一句话"
cta_text = "了解产品"     # 主按钮
cta_url = "/products.html"
cta2_text = "联系我们"    # 次按钮（可省略）
cta2_url = "/about.html#contact"

# 首页特性卡片（可增删，改完重新 build）
[[site.features]]
title = "开箱即用"
text = "卡片描述文字"

# 联系方式（页脚与关于页共用）
[site.contact]
email = "hi@example.com"
phone = "400-000-0000"

[site.footer]
text = "© 2026 星尘科技"

[build]
content_dir = "content"     # Markdown 源目录
template_dir = "templates"  # 模板目录
static_dir = "static"       # 静态资源目录（原样拷贝）
output_dir = "public"       # 输出目录
drafts = false              # true 则默认构建草稿（等价于 --drafts）
tag_pages = true            # 是否生成 tags/<tag>.html
category_pages = true       # 是否生成 categories/<cat>.html
archive_page = true         # 是否生成 archive.html
feed = true                 # 是否生成 feed.xml（Atom）
rss = true                  # 是否生成 feed_rss.xml（RSS 2.0）
sitemap = true              # 是否生成 sitemap.xml
robots = true               # 是否生成 robots.txt
per_page = 0                # 首页/标签页每页篇数；0 为不分页
                            # 分页文件：首页 page/2.html…、标签页 tags/<tag>/2.html…
                            # （content 下不要建 page/、tags/<tag>/ 同名路径，以免冲突）
search = true               # 站内搜索：生成 search.json 索引 + /search.html（无后端纯前端）
image_max_width = 1600      # static/ 里的图片超过此宽度则缩放（Pillow）；0 为不缩放
image_quality = 82          # JPEG 压缩质量（1-95）；PNG 自动 optimize

# 联系表单：填入 Formspree / Getform 等第三方服务的 endpoint，
# 联系页（/contact.html）的表单即可用；留空则显示配置提示
[site.form]
endpoint = ""
# endpoint = "https://formspree.io/f/xxxxxx"

# 多语言：取消注释启用英文版。about.en.md 这类文件会输出到 en/ 目录，
# [site.en] 覆盖英文版的站点文案（标题/菜单/hero 等深层合并）
[i18n]
# default = "zh"
# langs = ["zh", "en"]
# [site.en]
# title = "Stardust"
# description = "English description."
```

换肤不需要改模板：改 `mssg.toml` 里的标题、菜单、hero、特性卡、
联系方式，重新 `mssg build` 就是一家新公司。

## CLI 参考

```bash
mssg new <目录>              # 生成站点脚手架（非空目录拒绝覆盖）
mssg new post <slug> [-t 标题]  # 在 content/ 下新建文章（已存在则拒绝覆盖）
mssg post <slug> [-t 标题]      # 同上，兼容别名
mssg build [--force] [--drafts] [-c mssg.toml]
mssg serve [--port 8000] [--drafts] [--no-watch] [-c mssg.toml]
mssg clean [-c mssg.toml]       # 清空构建输出目录（指向站点根时拒绝执行）
mssg admin [--port 8902] [-c mssg.toml]  # 本地内容管理后台（仅 127.0.0.1）
mssg --version
```

`mssg admin` 在本机起一个网页后台：文章列表、新建、编辑
（标题/日期/标签/分类/草稿/正文）、删除，保存后自动重建。
只监听回环地址，不对外暴露；不要把它放到公网。

## Markdown（Python-Markdown）

完整 Markdown 语法，外加扩展：

- `extra`：表格（支持 `:---:` / `:---` / `---:` 列对齐）、脚注、定义列表等
- `codehilite`：Pygments 代码高亮（输出 `<div class="codehilite">`，
  脚手架 `style.css` 自带一套配色）
- `toc`：h1–h6 自动生成锚点 `id`（中文保留，如 `<h2 id="章节标题">`），
  供 `page.toc`（h2/h3 列表，每项有 level/text/id）跳转
- `sane_lists`：更符合直觉的列表解析

行内 HTML 原样通过（`<!--more-->` 摘要标记依赖它）。

## 模板（Jinja2）

标准 Jinja2 语法（`{{ }}` / `{% %}` / `{# #}`），自动转义关闭
（`page.content` 是已生成的 HTML）：

- `{{ name }}` / `{{ page.title }}` —— 变量，缺失则为空
- `{% for p in pages %} ... {% endfor %}` —— 循环，
  体内可用 `loop.index` / `loop.index0` / `loop.first` / `loop.last` 等
- `{% if x %} ... {% elif y %} ... {% else %} ... {% endif %}` —— 条件
- `{% extends "base.html" %}` + `{% block name %} ... {% endblock %}` —— 模板继承
- `{% include "part.html" %}` —— 引入模板片段（使用当前上下文）
- 过滤器：Jinja2 内建全部可用，支持链式 `{{ x|striptags|trim }}`；
  mssg 额外注册 `date`：`{{ p.date|date("%Y年%m月%d日") }}`

注意 Jinja2 语义（与旧自研引擎不同）：

- `default` 只对**未定义**变量生效，空字符串想走默认值用
  `{{ n|default("n/a", true) }}`
- `truncate(n)` 默认 `leeway=5`，短串不截断；精确截断用
  `{{ n|truncate(5, true, "…", 0) }}`
- `join` 无参数时分隔符为空串（`{{ xs|join(", ") }}` 加分隔符）
- `urlencode` 保留 `/`（按查询串语义编码）
- 字典的键若与方法名冲突（如 `items`），点号会取到方法；
  用下标取值：`{{ data.links["items"] }}`

模板错误（语法错误、模板不存在、循环引用等）统一转为 `ValueError`，
构建失败时会报出出问题的页面文件名。

模板可用变量：`site`（配置）、`data`（`data/` 下 .json/.toml 数据文件）、
`page`（当前页面：title/date/content/url/summary/summary_text/toc + front matter
全部字段；toc 为 h2/h3 列表，每项有 level/text/id）、
`pages`（当前列表的页面，按日期倒序）、`pagination`（分页信息：
page/total_pages/multiple/has_prev/has_next/prev_url/next_url）。

摘要：在正文中写 `<!--more-->` 划线，之前的内容即摘要；不写则取首段
（跳过开头的标题行）。`page.summary` 为 HTML，`page.summary_text` 为纯文本。

分页：`[build] per_page = 5` 后，首页第 2 页起为 `page/2.html`…，
标签第 2 页起为 `tags/<tag>/2.html`…；分页 URL 自动计入 sitemap；
per_page 改动会触发全量重建并清理多余分页文件。

## 构建特性

- 增量构建：内容与模板的 SHA1 无变化时跳过，只重建改动过的页面
- 模板改动（含重命名）自动触发全量重建
- `static/` 原样拷贝，删除的文件会自动清理输出残留
- 删除 Markdown 源文件后，输出 HTML 与索引/标签页/feed/sitemap 中的引用一并清理
- `mssg clean` 可清空输出目录
- 草稿：front matter 写 `draft: true` 的页面默认跳过，
  `mssg build --drafts` / `mssg serve --drafts` 可包含草稿
- 标签页：front matter 写 `tags: [a, b]`，自动生成 `tags/<tag>.html`
  （模板 `tag.html`，变量：`tag`、`pages`）；
  标签名保留原文（含中文），`/` `\` 会转为 `-`，重名加 `-2` 后缀
- 分类页：front matter 写 `categories: [a, b]`（或 `category:`），自动生成
  `categories/<cat>.html`（模板 `category.html`，变量：`category`、`pages`）
- 归档页：自动生成 `archive.html`，按年月分组
  （模板 `archive.html`，变量：`groups`，每组有 `ym` 与 `pages`）
- Atom 订阅：自动生成 `feed.xml`（最近 20 篇），`[build] feed = false` 可关闭
- RSS 订阅：自动生成 `feed_rss.xml`（RSS 2.0，最近 20 篇），`[build] rss = false` 可关闭
- 站点地图：自动生成 `sitemap.xml`（含 lastmod），`[build] sitemap = false` 可关闭
- robots.txt：自动生成（含 Sitemap 指向），`[build] robots = false` 可关闭
- 数据文件：`data/` 下的 `.json`/`.toml` 会在模板里以 `data` 变量可用，
  改动触发重建
- 并行构建：页面渲染用线程池并行（缓存写回串行）
- 多语言：`content/about.en.md` → `en/about.html`（文件名后缀约定）；
  `[i18n] langs = ["zh", "en"]` 开启，`[site.en]` 覆盖该语言的站点文案
  （标题/菜单/hero 等深层合并）；首页/标签/分类/归档/订阅按语言独立生成；
  模板变量 `lang` / `langs` / `default_lang` / `translations`；
  自动输出 `hreflang` 标签与导航语言切换器；增量构建可感知翻译文件增删
- 站内搜索：构建时生成 `search.json` 全文索引，`/search.html`
  纯前端 JS 搜索（按当前语言过滤），无后端依赖；`[build] search = false` 可关闭
- 图片优化：`static/` 里的 JPG/PNG/WebP 构建时自动压缩，
  超过 `image_max_width` 则等比缩放（Pillow LANCZOS）；损坏图片回退普通拷贝
- 联系表单：`[site.form] endpoint` 填入 Formspree / Getform 等第三方服务地址，
  `/contact.html` 的表单即提交到该地址；留空则显示配置提示

## 测试

```bash
python -m unittest discover -s tests
```

版本历史见 [CHANGELOG.md](CHANGELOG.md)。

## 路线图

已完成：

- [x] 模板继承（`{% extends %}` / `{% block %}`）
- [x] 标签页与归档页自动生成
- [x] 草稿（`draft: true`）过滤
- [x] Atom 输出（feed.xml）
- [x] `serve` 的文件监听自动重建
- [x] sitemap.xml
- [x] 模板过滤器（Jinja2 内建全部 + `date`，支持链式）
- [x] 文章摘要（`<!--more-->` / 首段 fallback）
- [x] 分类页、RSS 2.0、robots.txt、页面 TOC
- [x] 数据文件（`data/` → 模板变量）
- [x] 并行构建、`mssg new post` 文章脚手架
- [x] 第三方库迁移（Python-Markdown / Jinja2 / PyYAML / Pygments，0.4.0）
- [x] 公司官网级脚手架：配置驱动换肤（菜单/hero/特性卡/页脚）、
  响应式主题、OG/Twitter SEO 标签（0.5.0）

后续想法：

- [x] `{% include %}` 模板片段引入
- [x] 分页（首页/标签页按 N 篇分页）
- [x] 多语言站点支持（0.6.0：文件名后缀约定 + 按语言独立生成 + hreflang）
- [x] 站内搜索（0.6.0：search.json + 纯前端）
- [x] 本地内容管理后台（0.6.0：`mssg admin`）
- [x] 图片压缩/缩放（0.6.0：Pillow）
- [x] 联系表单（0.6.0：第三方 endpoint 配置）
