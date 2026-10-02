# mssg 自主改进日志

自主纠错 + 自我改进循环的完整记录。每次迭代追加一条，含时间戳。

- 启动：T0 = 1790921345（VM 本地时钟 2026-10-02 约 14:09）
- 截止：T0 + 14400 ≈ 18:09（用户要求 18:07 前不停止）
- 纪律：零第三方依赖；每次 push 前全量测试全绿；不删仓库、不 force push master、不碰 .github/workflows。

---
## 迭代 1 — markdown.py 审查（约 14:12）

- 测试：26/26 全绿。
- 审查发现 2 个 bug：
  1. 围栏代码块未闭合时，块内内容被静默丢弃 → 修：在 `_parse_blocks` 结尾把未闭合的 fence 按闭合输出。
  2. CRLF（Windows 换行）输入会在 HTML 里残留 `\r` → 修：`markdown.parse` 与 `frontmatter.split` 入口统一归一化换行。
- 新增回归测试 4 个：test_unclosed_fence_kept、test_crlf（md/fm）、test_empty。
- fuzz：新建 fuzz_local.py（gitignore，不入库），3 个种子共 7000 用例，0 崩溃 0 挂起；195KB 大输入解析 0.09s。
- 提交 e98a0e4 并推送，push 前测试全绿。

## 迭代 2 — template.py 审查（约 14:16）

- 测试：30/30 全绿。
- 审查发现 2 个问题：
  1. `{# 注释 #}` 不被识别，会原样泄漏进输出 → 修：词法层新增注释 token，解析时丢弃。
  2. 3000 层 `{% if %}` 嵌套抛裸 RecursionError → 修：render() 捕获后转为明确的 ValueError（"模板嵌套过深"）。
- 验证通过：嵌套 for 循环 `{% for i %}{% for j %}` 正常；未闭合 `{{` 按文本保留。
- 新增测试 4 个：test_comment、test_nested_for、test_deep_nesting_clear_error、test_unclosed_var_kept。
- fuzz：种子 99，2000 用例，0 问题。
- 提交并推送，push 前测试全绿。

## 迭代 3 — frontmatter.py 审查（约 14:21）

- 测试：33/33 全绿。
- 审查发现 2 个健壮性问题：
  1. `title: hi # 注释` 里 # 后内容未剥离（真 YAML 会剥离）→ 修：新增 `_strip_comment`，只剥离引号外的 ` #` 注释。
  2. 行内列表 `tags: ["a,b", c]` 按逗号硬切，引号内逗号被误杀 → 修：新增 `_split_list`，引号内逗号不分割。
- 新增测试 3 个：test_comment_stripped、test_quoted_comma_list、test_multiline_list。
- fuzz：种子 1234，2000 用例，0 问题。
- 提交并推送，push 前测试全绿。

## 迭代 4 — site.py 审查（约 14:27）

- 测试：37/37 全绿。
- 审查发现 4 个问题：
  1. 带 UTF-8 BOM 的 Markdown 文件，front matter 识别失败 → 修：`_read_page` 改用 utf-8-sig 读取。
  2. content/index.md 生成的 index.html 会被自动索引覆盖 → 修：存在 url 为 index.html 的页面时跳过自动索引。
  3. static/ 里删除的文件会残留在输出目录 → 修：构建时对比缓存，清理孤儿文件（含路径穿越保护）。
  4. `mssg new` 会静默覆盖非空目录 → 修：非空目录抛 FileExistsError，CLI 友好提示并返回 1。
- 另：构建后清理已删除页面的残留缓存键。
- 新增测试 4 个：test_bom、test_content_index_wins、test_static_orphan_cleanup、test_new_site_refuses_nonempty。
- fuzz：种子 555，2000 用例，0 问题。
- 提交并推送，push 前测试全绿。

## 迭代 5 — cli.py 审查（约 14:34）

- 测试：37/37 全绿。
- 审查发现 2 个小问题：
  1. 缺 `--version` → 修：argparse `action="version"`，`mssg --version` 输出版本号。
  2. serve 端口被占用时抛裸 OSError 堆栈 → 修：捕获后友好提示并返回 1（已用占用端口实测验证）。
- 另发现：exec 会话是 root 身份，`serve --port 1` 会真的绑上低端口并挂起——以后验证 serve 必须用 timeout 或先占端口。
- fuzz：种子 777，1500 用例，0 问题。
- 提交并推送，push 前测试全绿。

## 迭代 6 — 路线图① 模板继承（约 14:45）

- 实现 `{% extends "base.html" %}` / `{% block name %}...{% endblock %}`：
  - 新增 `template.render_template(name, ctx, loader)`，loader 按名取源码；
  - 支持多级继承（子 block 覆盖父 block）、继承循环检测、父模板缺失报明确错误；
  - extends 必须为模板的第一个 {% 标签，否则报明确错误。
- 自举：`mssg new` 脚手架新增 base.html，page.html/index.html 改为继承它。
- 中途修 1 个自引入 bug：`_parse` 对合法的首个 extends 也抛错 → 改为跟踪 seen_tag，只跳过合法的那个。
- site.py 的 _render_page/_render_index 改走 render_template（模板缺失时仍用内置兜底）。
- 新增测试 6 个：test_extends、test_extends_multilevel、test_extends_missing_parent、test_extends_cycle、test_extends_not_first_tag、test_block_without_extends。
- 测试 43/43 全绿；端到端验证脚手架构建正常（标题 block 覆盖、页脚继承）；fuzz 种子 31337，2000 用例 0 问题。
- README 补充继承语法说明。提交并推送，push 前测试全绿。

## 迭代 7 — 路线图② draft 草稿过滤（约 14:58）

- front matter `draft: true` 的页面默认跳过构建与索引：
  - `Site.build(include_drafts=False)`，CLI `build/serve --drafts` 可包含草稿；
  - 配置 `[build] drafts` 也可默认开启；
  - 草稿之前生成的旧输出会被自动清理。
- 中途修 1 个自引入 bug：草稿分支无条件置 rebuilt_any=True，导致增量构建永远全量 → 改为只在真正清理残留时置位。
- 脚手架新增 content/draft.md 示例草稿。
- 新增测试 3 个：test_draft_filtered、test_draft_included、test_draft_stale_removed。
- 测试 46/46 全绿；fuzz 种子 4242，1500 用例 0 问题；README 补充草稿说明。
- 提交并推送，push 前测试全绿。

## 迭代 8 — 路线图③ 标签页与归档页（约 15:12）

- front matter `tags: [a, b]`（或逗号字符串）→ 自动生成 `tags/<tag>.html`；
  中文标签文件名做 URL 编码；无标签页面的标签被移除后旧文件自动清理。
- 自动生成 `archive.html`，按日期年月倒序分组。
- 模板：`tag.html`（变量 tag、pages）、`archive.html`（变量 groups，每组 ym/pages），
  均可用模板继承；未提供模板时用内置兜底模板。
- 配置 `[build] tag_pages / archive_page`（默认 true）可关闭；关闭后旧产物自动清理。
- 脚手架：hello.md 加 tags 示例，新增 tag.html/archive.html（继承 base.html）。
- 新增测试 4 个：test_tag_pages、test_tag_stale_cleanup、test_archive_page、test_chinese_tag_url_quoted。
- 测试 50/50 全绿；fuzz 种子 8888，1500 用例 0 问题；README 补充说明。
- 提交并推送，push 前测试全绿。

## 迭代 9 — 路线图④ Atom 订阅（约 15:28）

- 自动生成 `feed.xml`（Atom 1.0）：最近 20 篇，含标题/链接/更新时间/HTML 内容（已转义）；
  日期转 RFC3339；base_url 为空时用站内相对路径。
- 配置 `[build] feed = false` 可关闭，关闭后旧 feed.xml 自动清理。
- 脚手架 base.html 增加 `<link rel="alternate" type="application/atom+xml">`。
- 新增测试 2 个：test_feed（含 XML 合法性校验）、test_feed_disabled。
- 测试 52/52 全绿；fuzz 种子 6161，1500 用例 0 问题；README 补充说明。
- 提交并推送，push 前测试全绿。

## 迭代 10 — 路线图⑤ serve 文件监听（约 15:40）

- `mssg serve` 默认开启文件监听：每 0.5s 轮询 content/templates/static/mssg.toml
  的 (mtime, size) 快照，变化时自动重建并打印时间戳；`--no-watch` 可关闭。
- 构建失败（如模板语法错误）只打印错误、服务器继续运行，等用户修复后自动恢复。
- 实测验证：改 content → 自动重建且 HTTP 200；写坏模板 → 友好报错且服务不死；
  修复模板 → 自动恢复重建。
- 纯标准库实现（threading + os.walk），零依赖铁律不变。
- 测试 52/52 全绿；fuzz 种子 9999，1500 用例 0 问题；README 补充说明。
- 提交 fdf12ed 并推送，push 前测试全绿。

## 路线图完成情况
- [x] 模板继承（{% extends %}/{% block %}）
- [x] 标签页与归档页自动生成
- [x] draft: true 草稿过滤
- [x] RSS/Atom 输出
- [x] serve 文件监听自动重建

## 迭代 11 — markdown.py 第二轮审查：行内代码保护（约 15:52）

- 审查发现真 bug：`` `**不是粗体**` `` 被渲染成 `<code><strong>…`，
  `` `[x](y)` `` 在代码内被解析成链接 —— 行内代码本应原样保留。
- 修：`_inline` 先把行内代码片段暂存为 `\x00N\x00` 占位符，做完图片/链接/粗斜体
  解析后再还原。
- 新增测试 2 个：test_code_span_protects_markup、test_code_span_escapes_html。
- 测试 54/54 全绿；fuzz 种子 2718，2000 用例 0 问题。
- 提交 36f41d5 并推送，push 前测试全绿。

## 迭代 12 — template.py 第二轮：else 后分支检查（约 16:02）

- 审查发现：`{% if a %}A{% else %}B{% elif c %}C{% endif %}` 被静默接受，
  语义含糊 → 修：else 之后再出现 elif/else 直接抛明确 ValueError。
- 新增测试 1 个：test_elif_else_after_else_error。
- 测试 55/55 全绿；fuzz 种子 31415，2000 用例 0 问题。
- 提交并推送，push 前测试全绿。

## 迭代 13 — site.py 第二轮：配置变化检测（约 16:14）

- 审查发现：修改 mssg.toml（如站点标题）后增量构建不会重建 → 修：
  对配置文件做 SHA1，变化时强制全量重建。
- 新增测试 1 个：test_config_change_triggers_rebuild。
- 测试 56/56 全绿；fuzz 种子 10086，2000 用例 0 问题。
- 提交并推送，push 前测试全绿。

## 迭代 14 — 加分项：sitemap.xml（约 16:26）

- 自动生成 `sitemap.xml`（sitemaps.org 协议）：首页 + 全部页面，含 lastmod；
  配置 `[build] sitemap = false` 可关闭，关闭后旧文件自动清理。
- 中途抓 1 个笔误：`rstrip(".")` 写错，应为 `rstrip("/")`（自我纠错生效）。
- 新增测试 1 个：test_sitemap（含 XML 合法性校验）。
- 测试 57/57 全绿；fuzz 种子 20240，1500 用例 0 问题；README 补充说明。
- 提交并推送，push 前测试全绿。

## 迭代 15 — 压力测试（约 16:38）

- 合成 1000 页面站点（含标签/归档/feed/sitemap 全功能）：
  - 全量构建 1002 页：0.50s
  - 无变化二次构建：0.18s（rebuilt=False，增量正确跳过）
  - 改 1 页后构建：0.21s（rebuilt=True，仅重建变化页 + 索引类页面）
- 标签页 12 个（10 合成 + 2 脚手架），生成正确。
- 结论：性能无需优化。无代码改动，仅记录。

## 迭代 16 — 结构化 fuzz 抓到真 bug（约 16:55）

- 结构化 fuzz（嵌套列表/引用、万级重复字符、千列表格、模板深层嵌套）：
  抓到 1 个真 bug —— 1000 层嵌套引用导致 `markdown.parse` 抛裸 RecursionError，
  直接崩构建（此前模板引擎已修过同类问题，Markdown 漏了）。
- 修：
  1. `markdown.parse` 捕获 RecursionError → 明确 ValueError（"Markdown 嵌套过深"）；
  2. `Site.build` 解析/渲染页面失败时报出文件名（"解析页面失败 bad.md：…"），
     否则用户面对大站根本不知道哪个文件出问题。
- 新增测试 2 个：test_deep_nesting_clear_error、test_build_reports_bad_page。
- 测试 59/59 全绿（2.2s）；随机 fuzz 种子 7777，1500 用例 0 问题。
- 提交并推送，push 前测试全绿。

## 迭代 17 — 示例站同步（约 17:05）

- example/ 是按旧脚手架生成的，已过期 → 用新脚手架重新生成
  （base.html 继承、tag.html、archive.html、draft.md、feed 链接）。
- 新增 content/second.md《Markdown 语法演示》，覆盖表格、代码块、嵌套列表、引用。
- 构建验证：2 页（草稿过滤）、3 个标签页、归档/feed/sitemap 全部正常。
- 测试 59/59 全绿。提交并推送。

## 迭代 18 — 文档补全（约 17:15）

- README 滞后于功能：补全 mssg.toml 全量配置参考（11 个选项）、CLI 参考、
  front matter 类型与注释说明；修正"列表一层嵌套"的过时描述（实际支持任意嵌套）；
  路线图 5 项标为完成，新增后续想法（include/分页/多语言）。
- 测试 59/59 全绿。提交并推送。

## 迭代 19 — 新功能 {% include %} + 抓到无限循环 bug（约 17:35）

- 实现 `{% include "part.html" %}`：引入模板片段，使用当前上下文；
  被引入的模板不能用 extends；include 循环检测；无 loader 时报明确错误。
- **抓到 1 个严重自引入 bug**：include 分支漏写 `pos += 1`，导致 `_parse`
  在同一 token 上无限循环，最终 C 栈溢出段错误 —— 测试套件卡死暴露了它。
  教训：新增解析分支必须逐个核对 pos 推进（已审计其余分支全部正常）。
- 新增测试 5 个：test_include、test_include_missing、test_include_needs_loader、
  test_include_cycle、test_include_with_extends_error。
- 测试 64/64 全绿（2.1s）；fuzz 种子 24680，2000 用例 0 问题；README 补充说明。
- 提交 630d525 并推送，push 前测试全绿。

## 迭代 20 — 防挂起回归测试（约 17:45）

- 迭代 19 的教训沉淀为测试：test_no_hang_battery —— 8 个棘手模板组合
  （include 嵌套 for/if/block、for 套 include 套 for、include 循环）
  在子进程里限时 30s 渲染；若解析器再出现无限循环，测试明确失败
  而不是卡死整个套件。
- 测试 65/65 全绿（2.2s）。提交 之后并推送，push 前测试全绿。

## 迭代 21 — 第三轮 markdown 审查：属性注入（约 17:55）

- 第三轮审查 `_inline` 发现**真 bug**：`html.escape(quote=False)` 不转义引号，
  而图片 alt/src、链接 href 直接拼进双引号属性 ——
  `![a"onload="x](u)` 会生成真正的 onload 属性（XSS 级注入）。
- 修：改用 `html.escape(text)`（默认转义引号）；捕获组已转义，直接拼接即安全。
  验证：URL 中的 `&` 仍正确转成 `&amp;`，行内代码/粗体内的引号正常显示。
- 另修正模块 docstring"一层嵌套"的过时描述。
- 新增测试 test_inline_quotes_escaped。测试 66/66 全绿（2.1s）。
- 提交并推送，push 前测试全绿。

## 迭代 22 — 第三轮 frontmatter 审查：注释剥离不一致（约 18:05）

- 第三轮审查发现**真 bug**：行内列表 `tags: [a # 注释]` 会剥离注释，
  但多行列表
      tags:
        - a # 注释
  却把 "a # 注释" 整个当标签 —— 同一语义两种行为。
- 修：多行列表项同样走 `_strip_comment`（引号内的 # 保留）。
- 新增测试 test_multiline_list_comment_stripped。测试 67/67 全绿。
- 提交并推送，push 前测试全绿。

## 迭代 23 — 第三轮 site.py 审查（约 18:15）

- 发现 2 处问题：
  1. sitemap 里 content/index.md 存在时 index.html 出现两次 → 去重；
  2. `_clean_stale` 的 docstring 被复制粘贴成双份 → 清理。
- 新增测试 test_sitemap_no_duplicate_index。
  测试 68/68 全绿；fuzz 种子 97531，2000 用例 0 问题。
- 提交并推送，push 前测试全绿。

## 迭代 24 — 第三轮 cli.py 审查：构建失败的 traceback（约 18:25）

- 第三轮审查：`_cmd_build`/`_cmd_serve` 未捕获构建异常，
  模板写坏时用户看到一长串 traceback —— 与项目既定的"CLI 友好报错"方向不符。
- 修：两处都捕获异常，打印一行"构建失败：…"并返回 1
  （KeyboardInterrupt 不受影响，仍可 Ctrl-C）。
- 新增 TestCLI：test_build_error_friendly、test_build_ok_returns_zero。
  测试 70/70 全绿。提交并推送，push 前测试全绿。

## 迭代 25 — 新功能：分页（约 18:50）

- 实现 `[build] per_page`：首页分页为 page/2.html…、标签页分页为
  tags/<tag>/2.html…；模板变量 `pagination`（page/total_pages/multiple/
  has_prev/has_next/prev_url/next_url）；分页 URL 自动计入 sitemap；
  per_page 改动触发全量重建并清理多余分页文件；content/index.md 存在时不分页。
- 脚手架 index.html/tag.html 加分页导航；mssg.toml 加 per_page 注释说明；
  README 补全配置与模板变量文档；example/ 按新脚手架重新生成。
- 新增测试 3 个：test_pagination_index、test_pagination_tag、
  test_pagination_per_page_change_cleans。
- 途中抓到 2 个测试代码 bug：`/` 与 `%` 运算符优先级、重复 `[build]` 表
  导致 TOML 非法 —— 都是先写测试的好处。
- 测试 73/73 全绿；fuzz 种子 112233，2000 用例 0 问题。
- 提交 e576376 并推送，push 前测试全绿。

## 迭代 26 — 第四轮 template 审查：方法泄露（约 19:05）

- 第四轮审查 `_resolve` 发现**真 bug**：`{{ x.strip }}` 会输出
  `<built-in method strip of str object at 0x…>` —— 把方法 repr
  （含内存地址）泄露进页面。
- 修：callable 属性按缺失处理，返回空字符串。
- 新增测试 test_method_not_exposed。测试 74/74 全绿；
  fuzz 种子 55555，2000 用例 0 问题。
- 提交并推送，push 前测试全绿。

## 迭代 27 — 第四轮 markdown 审查：分隔线（约 19:20）

- 第四轮审查块级解析发现**真 bug**：`- - -` 被误解析成 `<ul><li>- -</li></ul>`，
  `* * *` 更糟（`<li><em> </em></li>`）—— CommonMark 里带空格的分隔符是 `<hr>`。
- 修：`_HR` 改为允许分隔符间空格（`^(?:-\s*){3,}$` 等三选一，同字符约束保留）。
- 另修正 `_parse_list` docstring"一层嵌套"的过时描述。
- test_hr 扩充 3 个断言。测试 74/74 全绿；fuzz 种子 777000，2000 用例 0 问题。
- 提交并推送，push 前测试全绿。

## 迭代 28 — 第四轮 frontmatter 审查：误判 front matter（约 19:35）

- 第四轮审查 `split` 发现**真 bug**：文档以 `---\n纯文本\n---` 开头时，
  纯文本被当成 front matter 解析失败后静默丢弃 —— 用户内容无声消失。
- 修：块内无任何有效键、且有实质内容行时，整个文档按正文处理；
  纯空的 `---\n---` 仍视为合法空 front matter。
- 新增测试 test_not_front_matter_without_keys。测试 75/75 全绿；
  fuzz 种子 314159，2000 用例 0 问题。
- 提交并推送，push 前测试全绿。

## 迭代 29 — 第四轮 site/cli 审查：serve 下改配置不生效（约 19:50）

- 第四轮审查发现**真 bug**：`Site.cfg` 只在构造时加载一次，
  `serve` 的 watch 线程重建时配置值还是旧的 —— 改标题/改 per_page
  都不生效，且 digest 已记为新值、之后再也不会纠正（静默错误）。
- 修：
  1. `Site.build()` 开头重读配置；
  2. watch 循环每次按最新配置重新计算监听路径（目录配置变了也能跟上）。
- 新增测试 test_build_reloads_config（复现：改标题后同一 Site 再 build）。
  测试 76/76 全绿；fuzz 种子 271828，2000 用例 0 问题。
- 提交并推送，push 前测试全绿。

## 迭代 30 — 模板组合语义深度探测（约 20:00）

- 手动探测 extends × include × block 组合：三级继承的 block 覆盖、
  block 内的 include、父模板里的 include、非法 block 名 —— 全部符合预期。
- 把两个此前未覆盖的组合沉淀为回归测试：
  test_extends_three_levels、test_include_inside_block。
- 测试 78/78 全绿。提交并推送，push 前测试全绿。

## 迭代 31 — 打包配置审查（约 20:10）

- 审查 pyproject.toml：版本号仍是 0.1.0，但自 v0.1.0 后已新增
  模板继承/include/标签页/归档/草稿/feed/sitemap/分页/文件监听 ——
  升至 0.2.0（`mssg/__init__.py` 与 pyproject.toml 同步，`--version` 验证）。
- 清理仓库根目录测试残留的 public/（gitignored，不入库）。
- 测试 78/78 全绿。提交并推送，push 前测试全绿。

## 迭代 32 — 打包验证 + CHANGELOG（约 20:25）

- 打包验证（只构建不安装，不碰依赖铁律）：pyproject.toml 有效；
  `pip wheel --no-deps` 产出 mssg-0.2.0-py3-none-any.whl；
  解包验证 6 个模块齐全、`--version` 输出 mssg 0.2.0。
- 新增 CHANGELOG.md：0.2.0 的新功能 / 修复清单 / 测试情况；
  README 测试章节链接到它。
- 测试 78/78 全绿。提交并推送，push 前测试全绿。

## 迭代 33 — 增量构建审查：删除页面的残留（约 20:40）

- 审查删除场景发现**真 bug（两层）**：
  1. 删除 content/gone.md 后，public/gone.html 永久残留；
  2. 删除页面不触发 rebuilt_any，首页/标签页/feed/sitemap 里还留着死链。
- 修：清理逻辑提前到 pages 循环之后、渲染索引之前 —— 删输出文件
  （含路径穿越保护）+ 删缓存键 + 置 rebuilt_any=True。
  途中手误把 sitemap 测试的 def 行吃了，已恢复（教训：edit 后要 grep 确认）。
- 新增测试 test_deleted_page_cleanup。测试 79/79 全绿；
  fuzz 种子 999888，2000 用例 0 问题。
- 提交并推送，push 前测试全绿。

## 迭代 34 — fuzzer 升级为语法制导（约 20:55）

- fuzz_local.py 新增语法制导生成器：模板（嵌套 for/if/elif/block/include、
  畸形碎片、include 自循环）与 Markdown（嵌套列表/引用/表格/围栏/分隔线），
  与字符汤交替运行；模板用无 loader 与有 loader 两种模式渲染。
- 5 个新种子 × 2000 用例 = 10000 用例，0 崩溃 0 挂起 0 非预期异常。
- fuzzer 本身在 .gitignore 中，不入库。测试 79/79 全绿（无代码改动，不提交）。

