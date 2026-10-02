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
```

站点结构：

```
my-site/
  mssg.toml        # 配置（站点标题、目录等）
  content/         # Markdown 文章（支持 --- front matter ---）
  templates/       # page.html（文章模板）、index.html（首页模板）
  static/          # 原样拷贝到输出目录
  public/          # 构建产物
```

front matter 示例：

```markdown
---
title: 你好，世界
date: 2026-10-02
---

# 你好，世界

正文……
```

## Markdown 支持（自研子集）

ATX 标题、段落、`**粗体**`、`*斜体*`、`` `行内代码` ``、`[链接](url)`、
`![图片](url)`、无序/有序列表（一层嵌套）、`>` 引用、```` ``` ```` 围栏代码块、
`---` 分隔线、简单表格。

## 模板语法（自研）

- `{{ name }}` / `{{ page.title }}` —— 变量，支持点号取值，缺失则为空
- `{% for p in pages %} ... {% endfor %}` —— 循环，体内可用 `loop.index` / `loop.index0`
- `{% if x %} ... {% elif y %} ... {% else %} ... {% endif %}` —— 条件，
  支持 `not x`、`a == b`、`a != b`
- `{# ... #}` —— 注释
- `{% extends "base.html" %}` + `{% block name %} ... {% endblock %}` —— 模板继承
  （extends 必须为模板的第一个标签；子模板的 block 覆盖父模板；支持多级继承）

模板可用变量：`site`（配置）、`page`（当前页面：title/date/content/url + front matter
全部字段）、`pages`（首页：全部页面，按日期倒序）。

## 构建特性

- 增量构建：内容与模板的 SHA1 无变化时跳过，只重建改动过的页面
- 模板改动自动触发全量重建
- `static/` 原样拷贝，删除的文件会自动清理输出残留
- 草稿：front matter 写 `draft: true` 的页面默认跳过，
  `mssg build --drafts` / `mssg serve --drafts` 可包含草稿
- 标签页：front matter 写 `tags: [a, b]`，自动生成 `tags/<tag>.html`
  （模板 `tag.html`，变量：`tag`、`pages`）
- 归档页：自动生成 `archive.html`，按年月分组
  （模板 `archive.html`，变量：`groups`，每组有 `ym` 与 `pages`）
- Atom 订阅：自动生成 `feed.xml`（最近 20 篇），`[build] feed = false` 可关闭

## 测试

```bash
python -m unittest discover -s tests
```

## 路线图

- 模板继承（`{% extends %}` / `{% block %}`）
- 标签页与归档页自动生成
- 草稿（`draft: true`）过滤
- RSS/Atom 输出
- `serve` 的文件监听自动重建
