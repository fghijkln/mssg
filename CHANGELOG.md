# 更新日志

## 0.13.6（2026-10-02）

- 新增 `list_deployments`：取项目最近部署记录（含状态/时间）
- App：Cloudflare 面板新增项目列表视图——显示账号下所有 Pages
  项目、每个项目的最新部署状态（已上线/部署中/失败/未部署），
  点项目直接切换；新建项目入口保留；部署页加"切换项目"按钮

## 
## 0.13.5（2026-10-02）

修部署报 `Authorization failed`：

- 真因：JWT 请求头被拼成 `Bearer Bearer <jwt>`（双重前缀），
  deploy_directory 传了已带前缀的 auth 字符串，函数内又拼一次
- 改为全程传递裸 JWT，只在发请求时拼一次前缀；加回归测试锁定
- 去掉 wrangler 协议里没有的 upsert-hashes 一步
- _req/_jreq 支持 action 参数，出错信息带步骤名，方便定位

## 
## 0.13.4（2026-10-02）

修部署接口要求 manifest 字段（`A "manifest" field was expected`）：

- 上传改走 wrangler 同款协议：文件按内容哈希（sha256 base64+扩展名，
  取 32 位）经 JWT 凭证上传（check-missing → upload → upsert-hashes），
  再发 manifest（{"/路径": 哈希}）创建部署
- 未改动的文件服务端按哈希去重，重复部署更快
- HTTP 层重构为 `_call`（返回 status+JSON），DoH/WebView 兜底对
  JWT 系列接口同样生效

## 
## 0.13.3（2026-10-02）

修 Token 有效但 `/accounts` 返回空列表导致连接失败：

- 连接时先调 `/user/tokens/verify` 验活（无效 Token 直接报错）
- 账号列表为空时不再失败，App 引导手动填 Account ID
  （dashboard 地址栏 `dash.cloudflare.com/` 后面那串字符）
- 新增 `cf_set_account`（填入后用项目列表校验 Token 可用性）

## 
## 0.13.2（2026-10-02）

修部分手机直连 IP 也被拦（`[Errno 1] Operation not permitted`）：
部署请求最后的兜底改走 App 内 WebView（Chromium 网络栈，和浏览器同源）。

- `cloudflare.set_transport()`：可插拔传输层；App 启动时把 WebView
  通道注册进去，socket 全坏时自动切换，对用户透明
- Java 新增 `cfFetchSync`：Python→Java→WebView `fetch()`→回调，
  大请求体分 64KB 切片经 JS 桥接组装，无 Binder 大小限制
- DoH 分两层：先试普通域名（cloudflare-dns.com/dns.google），
  再试直连 IP（1.1.1.1/8.8.8.8）
- App 补上缺失的 INTERNET 权限 + 允许本地页面跨域访问 API

## 
## 0.13.1（2026-10-02）

修复：部分手机上系统 DNS 解析不了 `api.cloudflare.com`
（`[Errno 7] No address associated with hostname`），
Cloudflare 一键部署直接失败。

- 部署请求遇 DNS 错误时，自动走备用通道：经 DoH
 （`https://1.1.1.1/dns-query`，不依赖系统 DNS）解析出 IP，
  再直连该 IP（TLS 的 SNI 与证书校验仍用真实域名，安全不降级）
- 对用户透明：关掉 VPN 也解析失败时自动触发，无需任何操作

## 
## 0.13.0（2026-10-02）

Cloudflare Pages 一键部署（可选，220 测试全绿）：

- 新增 `mssg/cloudflare.py`：Pages Direct Upload API 客户端，
  只用标准库（urllib），无新依赖
- 建项目（不存在则自动创建）→ multipart 上传 public/ →
  轮询部署状态 → 返回 `https://<项目>.pages.dev`
- App「导出」里新增「部署到 Cloudflare Pages」：粘贴 API Token
  （Cloudflare Pages / 编辑权限）即连接，一键上线；
  不连也能继续用原来的 ZIP 导出，完全可选
- 单文件 25 MiB / 2 万文件上限按 Cloudflare 限制校验，
  Token 只存本机（600 权限）

## 
## 0.12.0（2026-10-02）

脚手架默认双语 + 英文切换器（211 测试全绿）：

- `mssg new` 默认启用 i18n（`[i18n] default = "zh", langs = ["zh", "en"]`），
  不再需要手动取消注释
- `[site.en]` 开箱即用：英文标题/菜单/hero/特性卡/联系方式/页脚全套文案，
  英文菜单 URL 指向 `/en/` 路径
- 四篇英文示范内容：`about.en.md` / `products.en.md` / `hello.en.md` /
  `contact.en.md`，输出到 `en/` 目录
- 三个内置主题的语言切换器统一显示"中文 / EN"（此前显示原始语言代码）
- 英文首页/标签/归档/搜索/RSS 独立生成，hreflang 双向标注
- 只配一种语言时行为与旧版一致（无 `en/` 目录），已加回归测试

## 0.9.0（2026-10-02）

对标 Hugo 的四项 P0 + 依赖大瘦身（208 测试全绿）：

### 瘦身：往小靠

- 去掉 PyYAML：自研 `mssg/yaml_subset.py` 解析 front matter（标量/列表/
  嵌套字典/注释/`|` 多行/ISO 日期，覆盖当年修过的所有边界），
  `mssg admin` 写回 front matter 也用它
- Pygments → 可选依赖 `mssg[highlight]`：未安装时代码高亮自动降级为
  普通代码块并警告一次
- Pillow → 可选依赖 `mssg[images]`：未安装时图片直接拷贝并警告一次
- 基础安装只剩 Markdown + Jinja2：依赖约 21.8MB → 约 2.3MB（-90%）

### 新功能

- Shortcodes（Hugo `{{< >}}` 语法子集）：内置 `figure`（图注）、
  `youtube`（隐私增强嵌入）、`image`（见下）；`templates/shortcodes/`
  下放 `<name>.html` 即可自定义；未知 shortcode 保留原文并警告一次
- Page bundles：`content/post/x/index.md` 同目录的非 md 资源自动同步到
  页面输出目录；`image`/`figure` 支持 `width` 参数，构建时缩放
  （如 `photo-400w.jpg`，带指纹缓存）；shortcode 解析到的依赖文件
  指纹跟踪——图片改了自动重建缩放图；删除的资源自动清理残留
- Asset pipeline（零依赖）：`[assets] minify = true` 压缩 CSS/JS
  （JS 为保守压缩：只去注释和空行，见 README 说明）；
  `fingerprint = true` 给 css/js 文件名加内容哈希
  （`style.css` → `style.<8hex>.css`），模板里用
  `{{ asset("style.css") }}` 引用；内容变化自动清理旧指纹文件并
  触发全量重渲染
- 嵌套菜单：`[[site.menu.children]]` 可多级嵌套，主题导航
  hover/键盘聚焦时下拉展开；新增 `menu_sort` 模板过滤器
  （按 weight 排序，缺 weight 不炸模板）

## 0.8.0（2026-10-02）

还清六笔技术债（182 测试全绿）：

### 重构

- 拆 `site.py`（1410 行 → 约 1150 行）：`new_site` 移入 `mssg/scaffold.py`，
  图片优化移入 `mssg/images.py`，主题发现移入 `mssg/themes.py`；
  `site.py` 保留重导出，`from mssg.site import Site, new_site` 不变

### 新功能

- 插件钩子：站点 `plugins/` 下每个 `*.py` 自动加载，`HOOKS = {...}`
  或 `register(hooks)` 注册；事件 `build_started` / `page_read` /
  `page_html` / `build_finished`（插件加载失败中断构建并报错，
  渲染在线程池中进行故钩子须线程安全）
- Markdown 可配置：`mssg.toml` 里 `[markdown] extensions` 增删扩展，
  `[markdown.extension_configs.*]` 透传给 Python-Markdown
- admin token 鉴权：默认每次启动生成一次性 token（打印在 URL 里，
  首次访问后种 cookie）；`--token` 指定固定值，`--no-auth` 关闭
  （仍只监听 127.0.0.1）
- 图片缓存：源文件指纹 + `image_max_width`/`image_quality` 不变时跳过
  重复优化，改配置才重新处理

### 性能

- 页面元数据读取与 Markdown 解析分离：无改动时跳过全部解析
- Markdown 实例按配置缓存（线程本地，避免每页重建）
- Jinja2 Environment 按模板内容缓存，不重复编译
- `search.json` 增量更新：只重建新增/改动页面的条目
- 列表页/feed/sitemap 等无改动时连模板都不渲染
- 1000 页站点实测：冷构建 19.6s → 4.8s，热重建 4.5s → 0.5s，
  单页改动 4.5s → 0.6s（`python tools/bench.py --pages 1000` 可复测）

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
