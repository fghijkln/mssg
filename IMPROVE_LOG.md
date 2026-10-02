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

