# mssg 自优化协议（GEPA 风格）

本目录是 mssg 的自我进化引擎，思想取自 [GEPA](https://github.com/gepa-ai/gepa)
（Genetic-Pareto）：**用完整执行轨迹做反思、用多目标 Pareto 做选择**，
而不是只看通过/失败一个标量。

## 角色分工

- **harness.py（代码）**：评估、捕获完整轨迹、Pareto 判定、状态机、前沿存档。
  它是裁判，不提方案。
- **agent（LLM）**：GEPA 里的 reflective proposer。读轨迹、诊断根因、
  提针对性补丁。它是选手兼教练。

## 一代的固定流程

```
select → propose → eval → reflect(仅失败时) → decide → select → …
```

1. **select**：跑 `harness.py select`，得到 `(gen, base_commit, target)`。
   先 `git reset --hard <base_commit>` 回到基线，保证每代从干净的前沿候选出发。
2. **propose**：针对 target 写补丁。要求：小步、单点、一个 commit 只做一件事。
3. **eval**：跑 `harness.py eval <gen>`。harness 会跑全量测试、示例站构建、
   有界 fuzz，把**完整轨迹**写进 `archive/gen_<N>/trajectory.md`，并给出多维分数。
4. **reflect**（GEPA 的核心，失败时强制）：不许直接重跑。先通读 trajectory，
   写出三段式诊断到 `archive/gen_<N>/reflection.md`：
   - 哪个组件坏了（精确到函数/分支）
   - 根因 why（不是现象，是机制）
   - 针对性修复方案（改哪几行、为什么这样改能根除）
   
   然后按方案改，再跑 `eval`（gen 号不变，轨迹追加）。
5. **decide**：跑 `harness.py accept <gen> <commit>`。harness 做 Pareto 判定：
   - 门禁：相对 base 不许引入新失败，构建不许从成功变失败；
   - 接受条件：至少一个目标轴严格变好，其余轴不退化。
   
   接受 → `git commit`（前缀 feat:/fix:/test:/docs:）并 push；
   拒绝 → `git reset --hard <base_commit>` 丢弃，回到 select。
6. 每代把做了什么记进 `IMPROVE_LOG.md`（仓库根）。

随时可跑 `harness.py status` 看前沿，`harness.py next` 问状态机下一步。

## 评分轴（越高越好，已内置方向）

- `tests_passed`：通过的测试数
- `tests_total`：测试总数（补测试本身就是进化）
- `build_ok`：示例站构建成功
- `-fuzz_crashes`：fuzz 崩溃数（越少越好）

## 铁律

- 依赖：Markdown / Jinja2 / PyYAML / Pygments（pyproject 声明）。
  新增依赖需有明确理由，优先用久经考验的库而非自研。
- 每次 push 前测试全绿；harness 的 accept 是最后一道门。
- `tools/evolve/archive/` 与 `state.json` 是本地工作状态，不入库；
  git 历史即前沿的真实存档。
- 目标优先级：路线图 `state.json roadmap` → 最近失败热点 → 覆盖率最低的模块。
