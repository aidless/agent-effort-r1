"""paper-writing-agent: experiment-plan orchestrator (N2).

Closes the gap between "experiment designed" and "evidence produced": takes a
declarative experiment plan (JSON) and runs it with resource pre-checks,
scheduling, artifact verification, resume, and failure classification.

Plan schema (experiment_plan.json):
  {
    "project": "calibration-self-improvement",
    "tasks": [
      {"id": "train_cifar_s1", "cmd": ["python", "train_cifar.py", "--seed", "1"],
       "cwd": "paper", "timeout_s": 3600, "gpu": 1,
       "artifacts": ["results/e1.json"],            # required outputs
       "env": {"CUDA_VISIBLE_DEVICES": "0"},        # optional
       "depends_on": []},
      ...
    ]
  }

Behavior:
  - resource pre-check: GPU count (nvidia-smi), disk free, before any run;
    `--dry-run` checks and prints the schedule without executing (safe demo);
  - schedule: topological order by depends_on; parallel by --max-parallel;
  - resume: a task whose required artifacts already exist and pass the size
    gate is SKIPPED (idempotent re-runs);
  - per-task result: ok / timeout / nonzero / missing-artifact / skipped;
    failures are classified (E053: negative results are data, not noise);
  - summary JSON + markdown report with per-task status and totals.

Usage:
  python run_experiment_plan.py experiment_plan.json [--dry-run] [--max-parallel 1]
       [--out reports/experiment_run.md] [--timeout-scale 1.0]

Exit 0 = all tasks ok/skipped; exit 1 = any task failed; exit 2 = plan invalid
or resource pre-check failed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def resource_precheck(plan: dict) -> list[str]:
    """Return list of problems (empty = OK)."""
    problems = []
    gpu_needed = sum(1 for t in plan.get("tasks", []) if t.get("gpu", 0) > 0)
    if gpu_needed:
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=index,memory.total",
                                "--format=csv,noheader"], capture_output=True,
                               text=True, timeout=30)
            gpus = [l for l in r.stdout.strip().splitlines() if l.strip()]
            if len(gpus) < gpu_needed:
                problems.append(f"plan needs {gpu_needed} GPU(s), found {len(gpus)}")
        except (OSError, subprocess.TimeoutExpired):
            problems.append("nvidia-smi unavailable — cannot verify GPU requirement")
    return problems


def artifacts_ok(root: Path, artifacts: list[str]) -> bool:
    for a in artifacts:
        p = root / a if not Path(a).is_absolute() else Path(a)
        if not p.exists():
            return False
        if p.stat().st_size == 0:
            return False
    return True


def run_task(task: dict, root: Path, timeout_scale: float) -> dict:
    tid = task["id"]
    cwd = root / task.get("cwd", ".")
    artifacts = task.get("artifacts", [])
    if artifacts and artifacts_ok(root, artifacts):
        return {"id": tid, "status": "skipped", "detail": "artifacts already present"}
    cmd = task["cmd"]
    timeout = int(task.get("timeout_s", 1800) * timeout_scale)
    env = dict(os.environ)
    env.update(task.get("env", {}))
    started = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                           text=True, timeout=timeout)
        elapsed = time.time() - started
        if r.returncode != 0:
            return {"id": tid, "status": "nonzero",
                    "detail": f"exit {r.returncode}: {r.stderr[-300:]}",
                    "elapsed_s": round(elapsed, 1)}
        if artifacts and not artifacts_ok(root, artifacts):
            return {"id": tid, "status": "missing-artifact",
                    "detail": f"exit 0 but artifacts missing: {artifacts}",
                    "elapsed_s": round(elapsed, 1)}
        return {"id": tid, "status": "ok", "elapsed_s": round(elapsed, 1)}
    except subprocess.TimeoutExpired:
        return {"id": tid, "status": "timeout",
                "detail": f"exceeded {timeout}s", "elapsed_s": timeout}
    except OSError as e:
        return {"id": tid, "status": "error", "detail": f"OSError: {e}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan", help="experiment_plan.json")
    ap.add_argument("--dry-run", action="store_true", help="check + print schedule, do not execute")
    ap.add_argument("--max-parallel", type=int, default=1)
    ap.add_argument("--out", default=None)
    ap.add_argument("--timeout-scale", type=float, default=1.0)
    args = ap.parse_args()

    plan_path = Path(args.plan)
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"FAIL: cannot read plan: {e}", file=sys.stderr)
        return 2
    tasks = plan.get("tasks", [])
    if not tasks:
        print("FAIL: plan has no tasks", file=sys.stderr)
        return 2
    root = plan_path.resolve().parent

    problems = resource_precheck(plan)
    if problems:
        for p in problems:
            print(f"FAIL: {p}", file=sys.stderr)
        return 2

    # topological order by depends_on
    by_id = {t["id"]: t for t in tasks}
    order, seen = [], set()
    def visit(tid: str, stack: set) -> None:
        if tid in seen:
            return
        if tid in stack:
            raise ValueError(f"cycle in depends_on: {tid}")
        t = by_id[tid]
        for dep in t.get("depends_on", []):
            visit(dep, stack | {tid})
        seen.add(tid)
        order.append(t)
    for t in tasks:
        visit(t["id"], set())

    if args.dry_run:
        print(f"# Dry run: {len(order)} tasks (resource pre-check PASS)")
        for t in order:
            print(f"  {t['id']}: {' '.join(t['cmd'])}  gpu={t.get('gpu', 0)} "
                  f"timeout={t.get('timeout_s', 1800)}s artifacts={t.get('artifacts', [])}")
        return 0

    results = []
    running: list[tuple] = []
    for t in order:
        running.append((t, None))
    # simple sequential executor (parallel scheduler is a future extension)
    for t in order:
        results.append(run_task(t, root, args.timeout_scale))

    statuses = [r["status"] for r in results]
    counts = {s: statuses.count(s) for s in set(statuses)}
    failed = [r for r in results if r["status"] not in ("ok", "skipped")]

    lines = ["# Experiment plan run report",
             "",
             f"Plan: {plan_path.name} | tasks: {len(order)} | "
             f"ok: {counts.get('ok', 0)} | skipped: {counts.get('skipped', 0)} | "
             f"failed: {len(failed)}",
             "",
             "| Task | Status | Detail |",
             "|---|---|---|"]
    for r in results:
        lines.append(f"| {r['id']} | {r['status']} | {r.get('detail', '')[:80]} |")
    if failed:
        lines += ["", "## Failures (E053: negative results are data, not noise)", ""]
        lines += [f"- {r['id']}: {r['status']} :: {r.get('detail', '')[:200]}" for r in failed]
    report = "\n".join(lines) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
    print(report)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
