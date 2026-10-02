"""harness 自举测试：Pareto 判定、unittest 输出解析、有界 fuzz。

GEPA 第一轮：进化引擎先给自己补测试。
"""

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools" / "evolve"))

import harness


def _scores(passed=10, total=10, build=True, crashes=0, failed_names=()):
    return {
        "tests_passed": passed,
        "tests_total": total,
        "build_ok": build,
        "fuzz_crashes": crashes,
        "tests_failed_names": list(failed_names),
    }


def _state_with(frontier):
    return {
        "generation": 1,
        "frontier": frontier,
        "attempts": {},
        "roadmap": [],
        "phase": "decide",
        "current": {"gen": 1, "base_commit": "base", "target": "t"},
    }


def _frontier_entry(cid, scores):
    return {"id": "F001", "commit": cid, "target": "t",
            "scores": scores, "ts": "2026-10-02"}


class TestDominates(unittest.TestCase):
    def test_strict(self):
        self.assertTrue(harness.dominates((5, 1, 0, 10), (4, 1, 0, 10)))

    def test_equal_not_dominate(self):
        v = (5, 1, 0, 10)
        self.assertFalse(harness.dominates(v, v))

    def test_tradeoff_not_dominate(self):
        # 一轴好、一轴差：互不支配
        self.assertFalse(harness.dominates((5, 1, 0, 10), (6, 1, -1, 10)))
        self.assertFalse(harness.dominates((6, 1, -1, 10), (5, 1, 0, 10)))


class TestParetoAccept(unittest.TestCase):
    def test_accept_first_candidate(self):
        st = _state_with([])
        ok, _, _ = harness.pareto_accept(st, "c1", _scores(), "base")
        self.assertTrue(ok)
        self.assertEqual(len(st["frontier"]), 1)

    def test_reject_new_failure(self):
        base = _frontier_entry("base", _scores(failed_names=["test_a"]))
        st = _state_with([base])
        ok, reason, _ = harness.pareto_accept(
            st, "c1", _scores(failed_names=["test_a", "test_b"]), "base")
        self.assertFalse(ok)
        self.assertIn("test_b", reason)

    def test_reject_build_regression(self):
        base = _frontier_entry("base", _scores(build=True))
        st = _state_with([base])
        ok, _, _ = harness.pareto_accept(st, "c1", _scores(build=False), "base")
        self.assertFalse(ok)

    def test_reject_dominated(self):
        base = _frontier_entry("base", _scores(passed=10))
        st = _state_with([base])
        ok, _, _ = harness.pareto_accept(st, "c1", _scores(passed=9), "base")
        self.assertFalse(ok)

    def test_accept_prunes_dominated(self):
        base = _frontier_entry("base", _scores(passed=10))
        st = _state_with([base])
        ok, _, _ = harness.pareto_accept(
            st, "c1", _scores(passed=12, total=12), "base")
        self.assertTrue(ok)
        self.assertEqual([f["commit"] for f in st["frontier"]], ["c1"])


class TestParseUnittest(unittest.TestCase):
    def test_ok(self):
        out = "test_x (a.B) ... ok\n\n----\nRan 3 tests in 0.1s\n\nOK\n"
        passed, total, failed = harness._parse_unittest(out)
        self.assertEqual((passed, total, failed), (3, 3, []))

    def test_fail(self):
        out = ("FAIL: test_bad (a.B)\nTraceback...\n\n"
               "Ran 3 tests in 0.1s\n\nFAILED (failures=1)\n")
        passed, total, failed = harness._parse_unittest(out)
        self.assertEqual(total, 3)
        self.assertEqual(passed, 2)
        self.assertEqual(failed, ["test_bad"])


class TestBoundedFuzz(unittest.TestCase):
    def test_fast_run_returns_list(self):
        crashes = harness._bounded_fuzz(n_cases=20, timeout_s=5)
        self.assertIsInstance(crashes, list)


if __name__ == "__main__":
    unittest.main()
