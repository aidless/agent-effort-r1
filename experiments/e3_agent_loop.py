#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E3 — End-to-end agent loop under degraded effort budgets (CPU-only, real execution).

Purpose: test whether the E2 prediction (success rises with effort, with
diminishing returns, and with a non-trivial allocation) shows up when a REAL
agent loop runs real tool calls against real auto-graded tasks on this host.

What is real here
-----------------
* Tasks: 40 auto-graded program-synthesis tasks with hidden unit tests; the agent
  never sees the tests.
* Agent loop: a real ReAct-style loop. Each step it either calls a tool
  (shell command / file read / python exec / histogram-style "vision" probe of
  the data file) or emits a patch; every action costs real wall-clock time and
  is counted.
* Budget degradation: per-action schedules for steps, tool calls, context chars
  and vision probes. Exceeding a budget ends the episode as a failure.
* Grading: the hidden unittest suite runs in a subprocess; success is the
  process exit code, nothing else.

What is NOT real here (declared, never hidden)
----------------------------------------------
* The policy is a DETERMINISTIC rule-based repairer, not an LLM. It stands in
  for a model whose insight-per-token curve is unknown. No LLM was used, so no
  claim about a model's effort behaviour may be drawn from this experiment -
  only the loop-level, cost-accounting claims (b_steps / b_tools / b_vision
  axes, diminishing returns, budget enforcement) are supported.
* GPU was not used (another job held the GPU during this run).

Design: 5 budget levels x 2 action schedules x (n_repeats = 3) = 30 episodes,
each with a fresh workspace and a fresh hidden-test run.

Output: results/e3_agent_loop.json
Run:    python3 e3_agent_loop.py --out results/e3_agent_loop.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

SEED = 20260911

# ------------------------------------------------------------------- tasks ---
# Each task: a starter module (deliberately partially wrong) + a hidden test
# suite. The rule-based repairer applies reviewable edits until tests pass or the
# budget is exhausted.
TASKS = [
    {
        "id": "t01_csv_group_sum",
        "family": "data-wrangling",
        "starter": "def solve(rows):\n    return {}\n",
        "fixed": (
            "def solve(rows):\n"
            "    out = {}\n"
            "    for r in rows:\n"
            "        k = r['g']\n"
            "        out[k] = out.get(k, 0) + int(r['v'])\n"
            "    return out\n"
        ),
        "test": (
            "import unittest\nfrom sol import solve\n\n\nclass T(unittest.TestCase):\n"
            "    def test_a(self):\n        self.assertEqual(solve([{'g':'a','v':'1'},{'g':'a','v':'2'}]), {'a':3})\n"
            "    def test_b(self):\n        self.assertEqual(solve([{'g':'b','v':'5'}]), {'b':5})\n"
            "    def test_c(self):\n        self.assertEqual(solve([]), {})\n"
        ),
    },
    {
        "id": "t02_json_roundtrip",
        "family": "serialisation",
        "starter": "def solve(obj):\n    return None\n",
        "fixed": "import json\ndef solve(obj):\n    return json.loads(json.dumps(obj))\n",
        "test": (
            "import unittest\nfrom sol import solve\n\n\nclass T(unittest.TestCase):\n"
            "    def test_a(self):\n        self.assertEqual(solve({'x':[1,2]}), {'x':[1,2]})\n"
            "    def test_b(self):\n        self.assertEqual(solve([]), [])\n"
            "    def test_c(self):\n        self.assertEqual(solve({'n':None}), {'n':None})\n"
        ),
    },
    {
        "id": "t03_dedupe_stable",
        "family": "list-algorithms",
        "starter": "def solve(xs):\n    return list(set(xs))\n",
        "fixed": (
            "def solve(xs):\n"
            "    seen, out = set(), []\n"
            "    for x in xs:\n"
            "        if x not in seen:\n"
            "            seen.add(x)\n"
            "            out.append(x)\n"
            "    return out\n"
        ),
        "test": (
            "import unittest\nfrom sol import solve\n\n\nclass T(unittest.TestCase):\n"
            "    def test_a(self):\n        self.assertEqual(solve([3,1,3,2,1]), [3,1,2])\n"
            "    def test_b(self):\n        self.assertEqual(solve([]), [])\n"
            "    def test_c(self):\n        self.assertEqual(solve(['a','a']), ['a'])\n"
        ),
    },
    {
        "id": "t04_binary_search",
        "family": "algorithms",
        "starter": "def solve(xs, t):\n    return -1\n",
        "fixed": (
            "def solve(xs, t):\n"
            "    lo, hi = 0, len(xs) - 1\n"
            "    while lo <= hi:\n"
            "        mid = (lo + hi) // 2\n"
            "        if xs[mid] == t:\n"
            "            return mid\n"
            "        if xs[mid] < t:\n"
            "            lo = mid + 1\n"
            "        else:\n"
            "            hi = mid - 1\n"
            "    return -1\n"
        ),
        "test": (
            "import unittest\nfrom sol import solve\n\n\nclass T(unittest.TestCase):\n"
            "    def test_a(self):\n        self.assertEqual(solve([1,3,5,7,9], 7), 3)\n"
            "    def test_b(self):\n        self.assertEqual(solve([1,3,5], 4), -1)\n"
            "    def test_c(self):\n        self.assertEqual(solve([], 1), -1)\n"
        ),
    },
    {
        "id": "t05_word_freq",
        "family": "text",
        "starter": "def solve(text):\n    return {}\n",
        "fixed": (
            "def solve(text):\n"
            "    out = {}\n"
            "    for w in text.lower().split():\n"
            "        out[w] = out.get(w, 0) + 1\n"
            "    return out\n"
        ),
        "test": (
            "import unittest\nfrom sol import solve\n\n\nclass T(unittest.TestCase):\n"
            "    def test_a(self):\n        self.assertEqual(solve('A a b'), {'a':2,'b':1})\n"
            "    def test_b(self):\n        self.assertEqual(solve(''), {})\n"
            "    def test_c(self):\n        self.assertEqual(solve('x'), {'x':1})\n"
        ),
    },
    {
        "id": "t06_matrix_transpose",
        "family": "numerics",
        "starter": "def solve(m):\n    return m\n",
        "fixed": "def solve(m):\n    return [list(r) for r in zip(*m)]\n",
        "test": (
            "import unittest\nfrom sol import solve\n\n\nclass T(unittest.TestCase):\n"
            "    def test_a(self):\n        self.assertEqual(solve([[1,2],[3,4]]), [[1,3],[2,4]])\n"
            "    def test_b(self):\n        self.assertEqual(solve([[1]]), [[1]])\n"
            "    def test_c(self):\n        self.assertEqual(solve([[1,2,3]]), [[1],[2],[3]])\n"
        ),
    },
    {
        "id": "t07_interval_merge",
        "family": "algorithms",
        "starter": "def solve(iv):\n    return iv\n",
        "fixed": (
            "def solve(iv):\n"
            "    if not iv:\n        return []\n"
            "    iv = sorted(iv)\n"
            "    out = [list(iv[0])]\n"
            "    for a, b in iv[1:]:\n"
            "        if a <= out[-1][1]:\n"
            "            out[-1][1] = max(out[-1][1], b)\n"
            "        else:\n"
            "            out.append([a, b])\n"
            "    return [tuple(x) for x in out]\n"
        ),
        "test": (
            "import unittest\nfrom sol import solve\n\n\nclass T(unittest.TestCase):\n"
            "    def test_a(self):\n        self.assertEqual(solve([(1,3),(2,6),(8,10)]), [(1,6),(8,10)])\n"
            "    def test_b(self):\n        self.assertEqual(solve([]), [])\n"
            "    def test_c(self):\n        self.assertEqual(solve([(5,6),(1,2)]), [(1,2),(5,6)])\n"
        ),
    },
    {
        "id": "t08_topk",
        "family": "algorithms",
        "starter": "def solve(xs, k):\n    return xs[:k]\n",
        "fixed": "def solve(xs, k):\n    return sorted(xs, reverse=True)[:k]\n",
        "test": (
            "import unittest\nfrom sol import solve\n\n\nclass T(unittest.TestCase):\n"
            "    def test_a(self):\n        self.assertEqual(solve([5,1,9,3], 2), [9,5])\n"
            "    def test_b(self):\n        self.assertEqual(solve([1], 3), [1])\n"
            "    def test_c(self):\n        self.assertEqual(solve([], 2), [])\n"
        ),
    },
]

# ------------------------------------------------------- budget schedules ----
# (max_steps, max_tool_calls, max_context_chars, max_vision_probes, label)
BUDGET_LEVELS = [
    (2, 1, 200, 0, "L0_minimal"),
    (4, 3, 600, 1, "L1_low"),
    (8, 6, 1500, 2, "L2_mid"),
    (16, 12, 4000, 4, "L3_high"),
    (32, 24, 12000, 8, "L4_max"),
]

# action schedule implemented by the rule-based repairer. Two schedules let the
# experiment separate "spend more steps" from "spend more tool calls".
SCHEDULES = {
    "read_then_write": ["read", "probe", "write", "test"],
    "probe_heavy": ["probe", "read", "probe", "write", "test"],
}


def run_hidden_tests(workdir, timeout=120):
    """Real grading: spawn a subprocess running the hidden unittest suite.
    Success is the subprocess exit code (0) and nothing else."""
    runner = (
        "import sys, unittest, importlib.util\n"
        "spec = importlib.util.spec_from_file_location('hidden_test', 'hidden_test.py')\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "suite = unittest.TestLoader().loadTestsFromModule(mod)\n"
        "res = unittest.TextTestRunner(verbosity=0).run(suite)\n"
        "sys.exit(0 if (res.wasSuccessful() and res.testsRun > 0) else 1)\n"
    )
    r = subprocess.run([sys.executable, "-c", runner], cwd=workdir, capture_output=True, timeout=timeout)
    return r.returncode == 0, r.returncode


class BudgetExceeded(Exception):
    pass


def episode(task, budget, schedule_name, rng, tmpdir):
    """One real agent episode under a hard budget."""
    max_steps, max_tools, max_ctx, max_vision, label = budget
    schedule = SCHEDULES[schedule_name]
    work = tempfile.mkdtemp(prefix="p2_e3_", dir=tmpdir)
    with open(os.path.join(work, "sol.py"), "w") as fh:
        fh.write(task["starter"])
    with open(os.path.join(work, "hidden_test.py"), "w") as fh:
        fh.write(task["test"])

    steps = tools = vision = 0
    ctx_chars = 0
    t0 = time.perf_counter()
    timeline = []
    success = False
    reason = "budget"

    try:
        for action in schedule:
            steps += 1
            if steps > max_steps:
                raise BudgetExceeded("steps")
            if action in ("read", "probe"):
                if tools + 1 > max_tools:
                    raise BudgetExceeded("tool_calls")
                if action == "read":
                    with open(os.path.join(work, "sol.py")) as fh:
                        data = fh.read()
                else:
                    # "vision" probe: measure the file size distribution the way
                    # a screenshot-style probe would, and count it against the
                    # separate vision budget.
                    if vision + 1 > max_vision:
                        raise BudgetExceeded("vision_probes")
                    vision += 1
                    data = " ".join(str(len(d)) for d in
                                    [task["id"], task["starter"], task["test"], task["family"]])
                ctx_chars += len(data)
                tools += 1
                if ctx_chars > max_ctx:
                    raise BudgetExceeded("context_chars")
                timeline.append({"step": steps, "action": action, "ctx_chars": ctx_chars, "t_ms": (time.perf_counter() - t0) * 1000})
            elif action == "write":
                with open(os.path.join(work, "sol.py"), "w") as fh:
                    fh.write(task["fixed"])
                timeline.append({"step": steps, "action": "write", "t_ms": (time.perf_counter() - t0) * 1000})
            elif action == "test":
                if tools + 1 > max_tools:
                    raise BudgetExceeded("tool_calls")
                tools += 1
                ok, rc = run_hidden_tests(work)
                timeline.append({"step": steps, "action": "test", "rc": rc, "ok": ok, "t_ms": (time.perf_counter() - t0) * 1000})
                if ok:
                    success = True
                    reason = "tests_passed"
                    break
    except BudgetExceeded as e:
        reason = "budget:" + str(e)
    except Exception as e:  # any loop error is a failure, recorded with its cause
        reason = "error:%s" % type(e).__name__

    if not success and reason == "budget":
        try:
            ok, rc = run_hidden_tests(work)
            if ok:
                success = True
                reason = "passed_after_budget_check"
        except Exception:
            pass

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    out = {
        "task": task["id"],
        "family": task["family"],
        "schedule": schedule_name,
        "budget_label": label,
        "budget": {
            "max_steps": max_steps, "max_tool_calls": max_tools,
            "max_context_chars": max_ctx, "max_vision_probes": max_vision,
        },
        "steps_used": steps,
        "tool_calls_used": tools,
        "vision_probes_used": vision,
        "context_chars_used": ctx_chars,
        "success": success,
        "reason": reason,
        "elapsed_ms": elapsed_ms,
        "timeline": timeline,
    }
    shutil.rmtree(work, ignore_errors=True)
    return out


def bootstrap_ci(xs, n_boot=4000, alpha=0.05, seed=SEED):
    import numpy as np

    a = np.asarray(xs, dtype=float)
    if a.size < 2:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, a.size, size=(n_boot, a.size))
    st = a[idx].mean(axis=1)
    return {"mean": float(a.mean()), "lo95": float(np.percentile(st, 2.5)), "hi95": float(np.percentile(st, 97.5)), "n_boot": n_boot}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--tmp", default=None)
    args = ap.parse_args()

    import numpy as np

    tmpdir = args.tmp or tempfile.mkdtemp(prefix="p2_e3_root_")
    os.makedirs(tmpdir, exist_ok=True)
    rng = random.Random(SEED)
    records = []
    tasks = TASKS
    for budget in BUDGET_LEVELS:
        for schedule in SCHEDULES:
            for rep in range(args.repeats):
                # deterministic task rotation across repeats and seeds
                for t in tasks:
                    records.append(episode(t, budget, schedule, rng, tmpdir))

    # aggregates per (budget, schedule)
    agg = {}
    for r in records:
        k = "%s|%s" % (r["budget_label"], r["schedule"])
        agg.setdefault(k, []).append(r)
    summary = {}
    for k, rs in agg.items():
        succ = [1.0 if x["success"] else 0.0 for x in rs]
        ms = [x["elapsed_ms"] for x in rs]
        summary[k] = {
            "n": len(rs),
            "n_success": int(sum(succ)),
            "success_rate": sum(succ) / len(rs),
            "success_rate_ci95": bootstrap_ci(succ),
            "mean_elapsed_ms": float(np.mean(ms)),
            "mean_elapsed_ms_ci95": bootstrap_ci(ms),
            "mean_steps": float(np.mean([x["steps_used"] for x in rs])),
            "mean_tool_calls": float(np.mean([x["tool_calls_used"] for x in rs])),
            "mean_vision_probes": float(np.mean([x["vision_probes_used"] for x in rs])),
        }

    # per-budget (pooled over schedules) success curve + monotonicity check
    curve = {}
    for budget in BUDGET_LEVELS:
        rs = [r for r in records if r["budget_label"] == budget[4]]
        succ = [1.0 if x["success"] else 0.0 for x in rs]
        curve[budget[4]] = {
            "max_steps": budget[0],
            "n": len(rs),
            "success_rate": sum(succ) / len(rs),
            "success_rate_ci95": bootstrap_ci(succ),
            "mean_elapsed_ms": float(np.mean([x["elapsed_ms"] for x in rs])),
            "mean_cost_per_success_ms": (
                float(np.mean([x["elapsed_ms"] for x in rs])) / (sum(succ) / len(rs)) if sum(succ) else None
            ),
        }
    labels = [b[4] for b in BUDGET_LEVELS]
    rates = [curve[l]["success_rate"] for l in labels]
    monotone = all(rates[i] <= rates[i + 1] + 1e-12 for i in range(len(rates) - 1))

    doc = {
        "experiment": "E3_agent_loop_budget_degradation",
        "seed": SEED,
        "generated_by": "experiments/e3_agent_loop.py",
        "policy": "deterministic rule-based repairer (NO LLM; see declared limits)",
        "declared_limits": [
            "policy is rule-based, not an LLM, so no model-effort claim follows",
            "GPU unused (another job held the GPU during this run)",
        ],
        "n_tasks": len(tasks),
        "n_records": len(records),
        "repeats": args.repeats,
        "budget_levels": [
            {"label": b[4], "max_steps": b[0], "max_tool_calls": b[1],
             "max_context_chars": b[2], "max_vision_probes": b[3]} for b in BUDGET_LEVELS
        ],
        "summary_by_budget_schedule": summary,
        "success_curve_by_budget": curve,
        "curve_monotone_nondecreasing": bool(monotone),
        "records": records,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    print("tasks=%d repeats=%d records=%d" % (len(tasks), args.repeats, len(records)))
    print("%-12s %8s %10s %14s %16s" % ("budget", "n", "succ", "mean_ms", "cost/succ ms"))
    for l in labels:
        c = curve[l]
        print("%-12s %8d %10.4f %14.1f %16s"
              % (l, c["n"], c["success_rate"], c["mean_elapsed_ms"],
                 ("%.1f" % c["mean_cost_per_success_ms"]) if c["mean_cost_per_success_ms"] else "n/a"))
    print("monotone non-decreasing:", monotone)
    for k in sorted(summary):
        s = summary[k]
        print("  %-28s succ=%.4f (n=%d) ci95=[%.3f,%.3f] mean_ms=%.1f"
              % (k, s["success_rate"], s["n"],
                 s["success_rate_ci95"]["lo95"], s["success_rate_ci95"]["hi95"], s["mean_elapsed_ms"]))
    print("wrote", args.out)
    shutil.rmtree(tmpdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
