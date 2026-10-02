# mssg

极简零依赖静态站点生成器。Markdown 解析器、模板引擎、front matter 解析全部自研，只用 Python 标准库，不装任何第三方包。

## 安装

需要 Python 3.11+（用了标准库 `tomllib`）。

```bash
pip install .
# 或者直接用源码
python -m mssg.cli new my-site
```

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

front matter 支持字符串、整数、浮点数、布尔、`[a, b]` 行内列表与 `- ` 多行列表；
行尾注释会被剥离（引号内、`a#b` 这种无空白的不算注释）。

## 配置参考（mssg.toml）

```toml
[site]
title = "我的小站"   # 站点标题，模板里用 {{ site.title }}
base_url = ""        # 站点根 URL，如 https://example.com（用于 feed/sitemap 绝对链接）

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
```

## CLI 参考

```bash
mssg new <目录>              # 生成站点脚手架（非空目录拒绝覆盖）
mssg new post <slug> [-t 标题]  # 在 content/ 下新建文章（已存在则拒绝覆盖）
mssg build [--force] [--drafts] [-c mssg.toml]
mssg serve [--port 8000] [--drafts] [--no-watch] [-c mssg.toml]
mssg clean [-c mssg.toml]       # 清空构建输出目录（指向站点根时拒绝执行）
mssg --version
```

## Markdown 支持（自研子集）

ATX 标题、段落、`**粗体**`、`*斜体*`、`` `行内代码` ``、`[链接](url)`、
`![图片](url)`、无序/有序列表（支持嵌套）、`>` 引用、```` ``` ```` 围栏代码块、
`---` 分隔线、简单表格（支持 `:---:` / `:---` / `---:` 列对齐）。

## 模板语法（自研）

- `{{ name }}` / `{{ page.title }}` —— 变量，支持点号取值，缺失则为空
- `{% for p in pages %} ... {% endfor %}` —— 循环，体内可用 `loop.index` / `loop.index0`
- `{% if x %} ... {% elif y %} ... {% else %} ... {% endif %}` —— 条件，
  支持 `not x`、`a == b`、`a != b`
- `{# ... #}` —— 注释
- `{% extends "base.html" %}` + `{% block name %} ... {% endblock %}` —— 模板继承
  （extends 必须为模板的第一个标签；子模板的 block 覆盖父模板；支持多级继承）
- `{% include "part.html" %}` —— 引入模板片段（使用当前上下文；被引入的模板不能用 extends）
- 过滤器：`{{ name|upper }}`，支持链式 `{{ x|default("n/a")|upper }}`；
  共 15 个：upper/lower/title/capitalize/trim/escape/striptags/urlencode/
  length/join/first/last/default(x)/replace(a,b)/truncate(n)/date(fmt)
  （如 `{{ p.date|date("%Y年%m月%d日") }}`）

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
- [x] 模板过滤器（15 个，支持链式）
- [x] 文章摘要（`<!--more-->` / 首段 fallback）
- [x] 分类页、RSS 2.0、robots.txt、页面 TOC
- [x] 数据文件（`data/` → 模板变量）
- [x] 并行构建、`mssg new post` 文章脚手架

后续想法：

- [x] `{% include %}` 模板片段引入
- [x] 分页（首页/标签页按 N 篇分页）
- 多语言站点支持
