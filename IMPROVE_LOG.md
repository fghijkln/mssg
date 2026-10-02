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

