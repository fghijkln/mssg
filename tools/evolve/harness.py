"""GEPA 风格自优化 harness（零依赖，只用标准库）。

把 GEPA 的核心机制落成代码：
  - Trajectory：评估不只返回通过/失败，而是捕获完整执行轨迹
    （unittest 全量输出、构建日志、fuzz 崩溃输入与 traceback），
    存于 tools/evolve/archive/gen_<N>/trajectory.md
  - Reflective mutation：失败后必须先读轨迹写诊断（why），再提针对性补丁，
    不许盲重试。harness 用状态机强制执行该顺序。
  - Pareto 选择：候选在多个目标上评分，只有「无新失败且至少一轴严格变好、
    其余轴不退化」才被接受进前沿 archive。
  - Candidate / Component 选择：按前沿 + 尝试次数 + 路线图队列给出建议。

候选 = 一次 git commit；评估 = 测试 + 示例站构建 + 有界 fuzz。

用法：
  python3 tools/evolve/harness.py status          # 前沿与状态一览
  python3 tools/evolve/harness.py next            # 状态机：下一步该做什么
  python3 tools/evolve/harness.py eval <gen>      # 对当前工作树做一次完整评估
  python3 tools/evolve/harness.py select          # 推荐 (base_commit, target)
  python3 tools/evolve/harness.py accept <gen> <commit>   # Pareto 判定并记录
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
EVOLVE_DIR = Path(__file__).resolve().parent
ARCHIVE = EVOLVE_DIR / "archive"
STATE_PATH = EVOLVE_DIR / "state.json"
TRAJ_LIMIT = 20000  # 单段轨迹截断上限（字符）


# -- 状态 ---------------------------------------------------------------

def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {
        "generation": 0,
        "frontier": [],          # [{id, commit, target, scores, ts, note}]
        "attempts": {},          # {commit: {target: n}}
        "roadmap": [
            "模板继承",
            "标签页与归档页",
            "草稿过滤",
            "RSS/Atom",
            "serve 文件监听",
        ],
        "phase": "select",       # select -> propose -> eval -> reflect/select ...
        "current": {},           # {gen, base_commit, target}
    }


def save_state(state: dict) -> None:
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def git(args: list[str]) -> str:
    r = subprocess.run(
        ["git"] + args, cwd=REPO, capture_output=True, text=True, timeout=60
    )
    return r.stdout.strip()


# -- 评估：捕获完整轨迹 ---------------------------------------------------

def _run(cmd: list[str], timeout: int, cwd: Path | None = None,
          env_extra: dict | None = None) -> tuple[int, str]:
    try:
        env = None
        if env_extra:
            env = dict(os.environ)
            env.update(env_extra)
        r = subprocess.run(
            cmd, cwd=cwd or REPO, capture_output=True, text=True,
            timeout=timeout, env=env,
        )
        return r.returncode, (r.stdout + r.stderr)[-TRAJ_LIMIT:]
    except subprocess.TimeoutExpired as e:
        out = ""
        if e.stdout:
            out += e.stdout.decode("utf-8", "replace")[-TRAJ_LIMIT // 2:]
        return 124, "TIMEOUT\n" + out


def evaluate(gen: int) -> dict:
    """完整评估当前工作树，写轨迹与分数，返回 scores。"""
    gdir = ARCHIVE / f"gen_{gen:03d}"
    gdir.mkdir(parents=True, exist_ok=True)

    traj = [f"# Trajectory gen_{gen:03d}", f"commit: {git(['rev-parse', 'HEAD'])}",
            f"time: {time.strftime('%F %T')}"]
    scores: dict = {}

    # 1) 单元测试（全量输出即轨迹）
    code, out = _run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], 300)
    traj.append("\n## unittest (exit=%d)\n\n```\n%s\n```" % (code, out))
    passed, total, failed_names = _parse_unittest(out)
    scores.update({"tests_passed": passed, "tests_total": total,
                   "tests_failed_names": failed_names})

    # 2) 示例站构建（在 example/ 目录，用仓库源码）
    code, out = _run(
        [sys.executable, "-m", "mssg.cli", "build", "--force"], 120,
        cwd=REPO / "example", env_extra={"PYTHONPATH": str(REPO)},
    )
    traj.append("\n## example build (exit=%d)\n\n```\n%s\n```" % (code, out))
    scores["build_ok"] = code == 0

    # 3) 有界 fuzz：只统计崩溃（异常/挂起），输入与 traceback 进轨迹
    crashes = _bounded_fuzz()
    scores["fuzz_crashes"] = len(crashes)
    if crashes:
        traj.append("\n## fuzz crashes (%d)\n" % len(crashes))
        for seed, tb in crashes[:5]:
            traj.append("### seed %r\n\n```\n%s\n```" % (seed, tb[-4000:]))

    (gdir / "trajectory.md").write_text("\n".join(traj), encoding="utf-8")
    (gdir / "scores.json").write_text(
        json.dumps(scores, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return scores


def _parse_unittest(out: str) -> tuple[int, int, list[str]]:
    import re
    m = re.search(r"Ran (\d+) tests?", out)
    total = int(m.group(1)) if m else 0
    failed = []
    for line in out.splitlines():
        mm = re.match(r"^(FAIL|ERROR): (\S+)", line)
        if mm:
            failed.append(mm.group(2))
    passed = total - len(failed) if total else 0
    ok = "OK" in out.splitlines()[-5:] if out else False
    if ok:
        passed, failed = total, []
    return passed, total, failed


def _bounded_fuzz(n_cases: int = 300, timeout_s: int = 45) -> list[tuple[str, str]]:
    """对 markdown/template 做有界随机输入 fuzz，只收崩溃。"""
    import random
    import traceback
    sys.path.insert(0, str(REPO))
    from mssg import markdown as md, template as tpl
    rng = random.Random(20261002)
    alphabet = list("#*`[](){}<>|_->!\"' \nabcXYZ019 \t:;.=/\\")
    crashes = []
    deadline = time.time() + timeout_s
    for i in range(n_cases):
        if time.time() > deadline:
            break
        s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 400)))
        for fn in (md.parse, lambda t: tpl.render(t, {"a": 1, "x": {"y": [1]}})):
            try:
                fn(s)
            except (RecursionError, MemoryError):
                crashes.append((f"case{i}", "RecursionError/MemoryError"))
            except Exception:
                crashes.append((f"case{i}", traceback.format_exc()))
            if len(crashes) >= 10:
                return crashes
    return crashes


# -- Pareto 选择 ----------------------------------------------------------

AXES = ["tests_passed", "build_ok", "fuzz_crashes_inv", "tests_total"]


def _vector(scores: dict) -> tuple:
    return (
        scores.get("tests_passed", 0),
        1 if scores.get("build_ok") else 0,
        -scores.get("fuzz_crashes", 999),
        scores.get("tests_total", 0),
    )


def dominates(a: tuple, b: tuple) -> bool:
    return all(x >= y for x, y in zip(a, b)) and any(x > y for x, y in zip(a, b))


def pareto_accept(state: dict, gen: int, commit: str,
                  scores: dict, base_commit: str) -> tuple[bool, str]:
    """判定候选是否可接受进前沿。门禁：相对 base 无新失败、构建不挂。"""
    base = next((f for f in state["frontier"] if f["commit"] == base_commit), None)
    if base is not None:
        old_fail = set(base["scores"].get("tests_failed_names", []))
        new_fail = set(scores.get("tests_failed_names", []))
        introduced = new_fail - old_fail
        if introduced:
            return False, "引入新失败: %s" % sorted(introduced)[:5]
        if base["scores"].get("build_ok") and not scores.get("build_ok"):
            return False, "构建从成功变失败"
    v = _vector(scores)
    for f in state["frontier"]:
        if dominates(_vector(f["scores"]), v):
            return False, "被前沿候选 %s 支配" % f["id"]
    # 接受：剔除被新候选支配的旧前沿
    state["frontier"] = [
        f for f in state["frontier"] if not dominates(v, _vector(f["scores"]))
    ]
    return True, "进入前沿"


# -- 状态机 -----------------------------------------------------------------

def cmd_status(state: dict) -> int:
    print("generation: %d  phase: %s" % (state["generation"], state["phase"]))
    print("frontier (%d):" % len(state["frontier"]))
    for f in state["frontier"][-8:]:
        s = f["scores"]
        print("  %s %s target=%s pass=%d/%d build=%s fuzz=%d" % (
            f["id"], f["commit"][:7], f.get("target"),
            s.get("tests_passed"), s.get("tests_total"),
            s.get("build_ok"), s.get("fuzz_crashes")))
    if state["roadmap"]:
        print("roadmap: %s" % " / ".join(state["roadmap"][:5]))
    return 0


def cmd_next(state: dict) -> int:
    phase = state["phase"]
    cur = state.get("current", {})
    if phase == "select":
        print("NEXT: 运行 `harness.py select` 选出 (base_commit, target)。")
    elif phase == "propose":
        print("NEXT: 针对 target=%s 在 base=%s 上写补丁（小步、单点）。"
              % (cur.get("target"), (cur.get("base_commit") or "")[:7]))
        print("写完补丁运行 `harness.py eval <gen>`。")
    elif phase == "eval":
        print("NEXT: 运行 `harness.py eval %d` 捕获完整轨迹并评分。"
              % state["generation"])
    elif phase == "reflect":
        g = state["generation"]
        print("NEXT [GEPA 反思]: 先读 tools/evolve/archive/gen_%03d/trajectory.md 的"
              "完整轨迹，写出诊断（哪个组件、根因 why、针对性修复方案），" % g)
        print("写到 tools/evolve/archive/gen_%03d/reflection.md，然后再提补丁重跑 eval。"
              % g)
        print("不许不看轨迹直接盲改重跑。")
    elif phase == "decide":
        print("NEXT: 运行 `harness.py accept <gen> <commit>` 做 Pareto 判定；")
        print("接受则 commit+push，拒绝则回滚到 base（git reset --hard <base>）。")
    return 0


def cmd_select(state: dict) -> int:
    frontier = state["frontier"]
    attempts = state["attempts"]
    if not frontier:
        base = git(["rev-parse", "HEAD"])
        target = state["roadmap"][0] if state["roadmap"] else "自查"
    else:
        # 前沿中尝试次数最少的候选优先；目标按路线图 + 失败热点轮换
        def cost(f):
            return sum(attempts.get(f["commit"], {}).values())
        base_f = sorted(frontier, key=cost)[0]
        base = base_f["commit"]
        tried = set(attempts.get(base, {}))
        target = next((t for t in state["roadmap"] if t not in tried),
                      "回归自查")
    state["generation"] += 1
    state["current"] = {"gen": state["generation"],
                        "base_commit": base, "target": target}
    state["phase"] = "propose"
    save_state(state)
    print("gen=%d base=%s target=%s" % (state["generation"], base[:7], target))
    return 0


def cmd_eval(state: dict, gen: int) -> int:
    scores = evaluate(gen)
    state["phase"] = ("reflect" if scores["tests_failed_names"]
                      or not scores["build_ok"] or scores["fuzz_crashes"]
                      else "decide")
    save_state(state)
    print("scores: pass=%d/%d build=%s fuzz_crashes=%d failed=%s" % (
        scores["tests_passed"], scores["tests_total"], scores["build_ok"],
        scores["fuzz_crashes"], scores["tests_failed_names"][:5]))
    print("phase -> %s" % state["phase"])
    return 0


def cmd_accept(state: dict, gen: int, commit: str) -> int:
    gdir = ARCHIVE / f"gen_{gen:03d}"
    scores = json.loads((gdir / "scores.json").read_text(encoding="utf-8"))
    base = state["current"].get("base_commit", "")
    ok, reason = pareto_accept(state, gen, commit, scores, base)
    cur = state["current"]
    if ok:
        fid = "F%03d" % (len(state["frontier"]) + 1)
        state["frontier"].append({
            "id": fid, "commit": commit, "target": cur.get("target"),
            "scores": scores, "ts": time.strftime("%F %T"),
        })
        att = state["attempts"].setdefault(base, {})
        att[cur.get("target", "?")] = att.get(cur.get("target", "?"), 0) + 1
        print("ACCEPT %s: %s" % (fid, reason))
    else:
        print("REJECT: %s" % reason)
    state["phase"] = "select"
    state["current"] = {}
    save_state(state)
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    state = load_state()
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == "status":
        return cmd_status(state)
    if cmd == "next":
        return cmd_next(state)
    if cmd == "select":
        return cmd_select(state)
    if cmd == "eval" and len(argv) == 3:
        return cmd_eval(state, int(argv[2]))
    if cmd == "accept" and len(argv) == 4:
        return cmd_accept(state, int(argv[2]), argv[3])
    print("未知命令: %s" % argv[1:])
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
