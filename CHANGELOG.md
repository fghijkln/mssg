# 更新日志

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

### 修复（均为先写复现测试再修）

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

- 78 个单元测试（`python -m unittest discover -s tests`），全部通过
- 随机 fuzz（Markdown 解析器 + 模板引擎）：数万用例，0 崩溃 0 挂起
- 防挂起电池测试：棘手模板组合在子进程限时渲染，挂起则明确失败
- 压力测试：1000 页面全量构建 0.50s、无变化 0.18s、单页改动 0.21s

## 0.1.0（2026-10-02）

首个可用版本：`new` / `build` / `serve` 三个命令，自研 Markdown 子集解析器、
自研模板引擎、front matter 解析、增量构建、示例站、22 个单元测试。
