# 更新日志

## 0.7.0（2026-10-02）

主题系统 + 真正的 canonical（166 测试全绿）：

### 新功能

- 主题机制：内置主题放在 `mssg/themes/<name>/`（模板 + 静态资源），
  `[site] theme` 切换（`company`/`minimal`），`mssg new --theme minimal` 建站；
  站点 `templates/` 下放同名文件即覆盖主题对应模板，`static/` 同名覆盖主题静态资源；
  未知主题名构建时报错并列出可用主题
- 新主题 `minimal`：Google 官网式的极简风（大留白、细字重、无渐变），
  与 `company` 共用全部配置项（菜单/hero/特性卡/搜索/表单/i18n）
- 真正的 `<link rel="canonical">`：`base_url` 配置后输出（之前 0.5.0 的
  CHANGELOG 误写为 canonical，实际只有 `og:url`，本次补上真正的标签；
  放在 `{% block meta %}` 之外，避免被 `page.html` 的 meta 覆盖吞掉）
- `mssg new` 不再复制模板文件到站点（脚手架更干净）；换肤 = 改配置，
  微调 = 在站点 `templates/` 放覆盖文件

## 0.6.0（2026-10-02）

补齐公司官网级能力的五个短板（157 测试全绿）：

### 新功能

- 多语言（i18n）：`content/about.en.md` → `en/about.html`（文件名后缀约定，
  默认语言不加前缀）；`[i18n] default/langs` 开启；`[site.en]` 深层覆盖该语言的
  站点文案（标题/菜单/hero/特性卡等）；首页/标签/分类/归档/订阅按语言独立生成；
  模板新增 `lang` / `langs` / `default_lang` / `translations` 变量；
  自动输出 `hreflang` 标签与导航栏语言切换器；翻译文件增删会触发兄弟页面重建
  （增量构建感知）
- 站内搜索：构建生成 `search.json`（标题/URL/日期/语言/纯文本正文），
  `/search.html` 用原生 JS 前端搜索并按当前语言过滤，无后端依赖；
  `[build] search = false` 可关闭
- `mssg admin`：本地内容管理后台（纯标准库 `http.server`），文章列表/新建/
  编辑（标题/日期/标签/分类/草稿/正文）/删除，保存后自动重建；
  只监听 127.0.0.1，无鉴权——不要暴露到公网
- 图片优化：`static/` 下的 JPG/PNG/WebP 构建时自动压缩，
  超过 `image_max_width`（默认 1600）等比缩放（Pillow LANCZOS），
  `image_quality`（默认 82）控制 JPEG 质量；损坏图片回退普通拷贝
- 联系表单：`[site.form] endpoint` 填入 Formspree / Getform 等第三方服务地址，
  `/contact.html`（新模板 + 示例页）表单即提交到该地址；留空显示配置提示
- 依赖新增 `Pillow>=10.0`

### 脚手架变化

- 新增 `templates/search.html`、`templates/contact.html`、`content/contact.md`
- 导航菜单新增"联系""搜索"；`base.html` 输出 `<html lang>`、hreflang 与语言切换器
- `mssg.toml` 新增 `[site.form]`、`[i18n]`、`[site.en]` 注释示例与图片配置项

## 0.5.0（2026-10-02）

公司官网级脚手架。`mssg new` 现在生成一个可直接上线的公司站：
导航栏、hero、特性卡片、新闻动态、页脚联系方式，全部在
`mssg.toml` 里配置，不动模板即可换肤（参考 Hugo 社区公司主题的
做法：品牌相关全部是配置项）。

### 新功能

- 新默认主题：响应式公司站（粘性导航、渐变 hero、特性卡片网格、
  移动端自适应），纯 CSS、无 JS
- `[[site.menu]]`：导航菜单（按 weight 排序）
- `[site.hero]`：首页标题/副标题/双 CTA 按钮
- `[[site.features]]`：首页特性卡片（增删改后重新 build 即可）
- `[site.contact]` / `[site.footer]`：联系方式与页脚文字
- SEO：Open Graph + Twitter Card meta 标签（`og:url` 需要配置 base_url；
  真正的 canonical 标签在 0.7.0 补上）
- 首页新闻区（最新 5 篇）+ 分页导航；示例内容含"关于我们/产品介绍"两个页面
- 配置缺省保护：`mssg.toml` 里不写 menu/hero 等节时模板不报错

## 0.4.0（2026-10-02）

架构转向：不再追求零依赖。Markdown 渲染、模板引擎、front matter
解析改用久经考验的第三方库，mssg 只做薄封装，维护负担大幅下降。

### 变更

- Markdown：自研子集解析器 → Python-Markdown（`extra`/`codehilite`/
  `toc`/`sane_lists` 扩展）。新增：完整 Markdown 语法、脚注、
  Pygments 代码高亮、h1–h6 全部带锚点 id、行内 HTML 原样通过
- 模板：自研引擎 → Jinja2。新增：`loop.first`/`loop.last` 等循环变量、
  宏、空白控制等全部 Jinja2 能力；mssg 只额外注册 `date` 过滤器。
  模板错误统一转为 `ValueError`（构建失败报出页面文件名不变）
- front matter：自研子集 → PyYAML 完整 YAML（嵌套、多行字符串等）
- 脚手架：示例文章展示代码高亮；`style.css` 内置一套 codehilite 配色
- `mssg new post <slug>` 正式实现（之前文档写了但没实现）；
  顶层 `mssg post` 保留为兼容别名

### 语义变化（Jinja2 标准语义）

- `default` 只对未定义变量生效；空串走默认值请用 `default("n/a", true)`
- `truncate(n)` 默认 leeway=5，短串不截断
- `join` 无参数时分隔符为空串
- 字典键与方法名冲突时（如 `items`），点号取到方法，请用 `data.links["items"]`

### 依赖

Markdown、Jinja2、PyYAML、Pygments（`pip install .` 自动安装）。

生产级特性补完。零依赖铁律不变：只用 Python 标准库。

### 新功能

- 摘要：`<!--more-->` 标记或首段自动 fallback；`page.summary`（HTML）、
  `page.summary_text`（纯文本 200 字）；脚手架 page.html 已用它生成
  `<meta name="description">`
- 分类法：`categories/<cat>.html`（与标签页同构，分页、撞车加后缀），
  `[build] category_pages` 开关
- RSS 2.0：`feed_rss.xml`（与 Atom 并存），`[build] rss` 开关
- `robots.txt` 自动生成（含 Sitemap 指向），`[build] robots` 开关
- 页面目录：`page.toc`（h2/h3，含锚点 id）；h2/h3 输出带 `id` 属性
- 模板过滤器：`{{ x|upper }}` 链式调用，共 15 个：
  upper/lower/title/capitalize/trim/escape/striptags/urlencode/length/
  join/first/last/default(x)/replace(a,b)/truncate(n)/date(fmt)
- 数据文件：`data/*.json|*.toml` → 模板变量 `data`；改动触发重建
- 并行构建：页面渲染线程池并行（缓存写回串行，无竞态）
- `mssg new post <slug> [-t 标题]`：新建文章脚手架

### 修复

- 摘要 fallback 把开头的 `# 标题` 也算进首段 → 跳过标题行取第一个真正段落

## 未发布

0.2.0 之后的修复（均为先写复现测试再修）：

- 中文标签页改用原文做文件名（之前百分号编码致 HTTP 404）；`/` `\` 转 `-`，重名加后缀
- 空 `date:` 回退到文件 mtime（之前归档页显示 `[]` 分组）
- 从正文提取的标题去掉 `**` 等行内标记
- 行内 HTML 实体不再双重转义（`&amp;` 不再变 `&amp;amp;`）
- 未闭合模板标记（`{{ x }`、`{# b`、`{% if x`）统一按普通文本处理
- front matter 键名支持 Unicode（如 `标题:`）
- `tags: 5` 标量视为单个标签（之前崩构建）
- `mssg new` 目标为已存在文件时报明确错误（之前 traceback）
- `mssg clean` 配置加载异常走友好报错

## 0.2.0（2026-10-02）

自 0.1.0 后的全部新功能与修复。零依赖铁律不变：只用 Python 标准库。

### 新功能

- 模板继承：`{% extends %}` / `{% block %}`（多级继承、循环检测、缺失父模板报明确错误）
- 模板片段：`{% include "part.html" %}`（使用当前上下文、循环检测）
- 标签页：`tags/<tag>.html` 自动生成（URL 编码、残留清理、`tag_pages` 开关）
- 归档页：`archive.html` 按年月归档（`archive_page` 开关）
- 草稿过滤：front matter `draft: true` 默认跳过（`--drafts` / `[build] drafts` 可包含）
- Atom 订阅：`feed.xml`（最近 20 篇，`[build] feed` 开关）
- 站点地图：`sitemap.xml`（`[build] sitemap` 开关）
- 分页：`[build] per_page`（首页 `page/2.html`…、标签页 `tags/<tag>/2.html`…，
  模板变量 `pagination`，sitemap 自动收录）
- `serve` 文件监听自动重建（标准库轮询、构建失败不退出、`--no-watch` 可关；
  监听时改 `mssg.toml` 配置立即生效）
- `mssg.toml` 变化自动触发全量重建；`--version`
- `mssg clean`：清空构建输出目录（指向站点根时拒绝执行）
- 表格列对齐：`:---:` / `:---` / `---:`

### 修复（均为先写复现测试再修）

- 删除 Markdown 源文件后：输出 HTML 残留、索引/标签页/feed/sitemap 死链
  （现清理输出并触发重建）
- 后加 `content/index.md` 时分页清理误删自定义首页
- 模板重命名（内容不变）不触发重建 → 指纹计入文件名
- `serve` 监听时改 `mssg.toml` 配置不生效 → 每次构建重读配置
- `draft: 1`（整数）不算草稿 → 与字符串语义一致
- URL 含括号的链接断裂（如 Wikipedia）→ 支持单层平衡括号
- 引号转义后 `[t](u "ti")` 标题语法失效（自引入回归）→ 已修复
- 表格行内代码里的 `|` 切错列
- sitemap 漏掉 archive.html
- 值开头的 `#`（`key: # 注释`）未视为注释；纯注释的列表项未丢弃
- Markdown 深层嵌套抛明确错误而非裸 `RecursionError`；构建失败报出文件名
- `{% include %}` 分支漏 `pos += 1` 致无限循环（测试套件卡死暴露）
- 行内引号未转义导致图片 alt/src、链接 href 属性注入
- 模板点号访问泄露对象方法（如 `{{ x.strip }}` 输出方法 repr）
- `- - -` / `* * *` 被误解析为列表项（应为 `<hr>`）
- 多行列表项行尾注释未剥离（与行内列表不一致）
- 无有效键的 `---` 块被误判为 front matter 并吞掉正文
- sitemap 里 `content/index.md` 导致 index.html 重复
- 行内代码内的 `**`、`[x](y)` 被误解析（占位符暂存法）
- 模板 `{% else %}` 后再出现 elif/else 报明确错误
- 未闭合围栏代码块丢内容；CRLF 换行归一化
- front matter 行尾注释剥离、引号内逗号列表
- 构建：BOM 头、`content/index.md` 优先、static 残留清理、草稿残留清理、
  `new` 拒绝覆盖非空目录、CLI 友好报错（构建失败返回 1 不抛 traceback、
  端口占用提示）

### 测试

- 92 个单元测试（`python -m unittest discover -s tests`），全部通过
- 随机 + 语法制导 fuzz（Markdown 解析器 + 模板引擎）：数万用例，0 崩溃 0 挂起
- 站点级 fuzz（完整 build 链路）：怪异标题/标签/正文，0 非预期异常
- 防挂起电池测试：棘手模板组合在子进程限时渲染，挂起则明确失败
- 压力测试：1000 页面全量构建 0.64s、无变化 0.21s、单页改动 0.15s

## 0.1.0（2026-10-02）

首个可用版本：`new` / `build` / `serve` 三个命令，自研 Markdown 子集解析器、
自研模板引擎、front matter 解析、增量构建、示例站、22 个单元测试。
