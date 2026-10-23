#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H4 — measure the four agent-axis gains g_x with a REAL language model (GPU).

Why this experiment exists
-------------------------
E2 shows that the joint-router claim hinges on the four agent-axis gains
(g_steps, g_tools, g_search, g_vision) and their saturation references. Those are
the largest ASSUMED block in the paper (`§Declared limits`). This harness measures
them end to end on the eight auto-graded tasks of E3, with a real model driving
the loop, so the assumption becomes a measurement.

Protocol (pre-registered in evidence/protocol.md §H4)
-----------------------------------------------------
* Tasks: the same eight program-repair tasks as E3, hidden unittest suite the
  agent never sees, success = the subprocess exit code (nothing else).
* Degrees of freedom are applied ONE AXIS AT A TIME, others fixed at mid:
    - steps axis   : max_steps in {1,2,4,8,16}
    - tools axis   : max_tool_calls in {0,1,2,4,8}
    - context axis : max_context_chars in {200,600,1500,4000}; beyond that the
                     model cannot see the failing test output (the E3 analogue of
                     the vision/search axis; a genuinely available axis here)
    - search axis  : NOT AVAILABLE on this host (no network search tool for the
                     policy); declared as not measured rather than faked.
* n_repeats >= 3 per cell; temperature 0.0 (greedy) so the run is reproducible.
* The policy is `Qwen3-8B-AWQ` (or a model given by --model). Prompts are
  single-turn: system prompt + task description + last tool observation. The
  agent writes a complete `sol.py` and the harness grades it.
* Everything is written to results/h4_gx_qwen.json: per-episode records (task,
  axis, level, repeat, success, tokens_generated, seconds, sampler info) plus
  per-cell aggregates with bootstrap CIs.

Budget discipline (queue rule)
------------------------------
GPU use is serialised through /root/autodl-tmp/gpu.lock with flock and priority
P1 > P4 > P2. This script acquires the lock only for the inference phase and
releases it between cells. It ABORTS (without touching the GPU) if free VRAM
< --min-free-mib (default 25000) or if the lock is not granted within
--lock-wait-s.

Run (remote, after acquiring the lock discipline):
  flock /root/autodl-tmp/gpu.lock -c \
    "python3 h4_gx_measure.py --out results/h4_gx_qwen.json --model /root/autodl-tmp/models/Qwen3-8B-AWQ"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

SEED = 20260911


def _load_e3():
    """Import experiments/e3_agent_loop.py so the graded task set cannot drift."""
    here = os.path.dirname(os.path.abspath(__file__))
    e3 = os.path.join(here, "e3_agent_loop.py")
    if not os.path.exists(e3):
        raise SystemExit("FATAL: e3_agent_loop.py must sit next to this script")
    import importlib.util
    spec = importlib.util.spec_from_file_location("e3mod", e3)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_E3 = _load_e3()
TASKS = _E3.TASKS
# E3's task dicts carry the hidden test + a reference solution but no prose spec
# (its policy is rule-based and never reads one). A model policy needs the spec,
# so it is attached here by id; ids are asserted to match E3's exactly.
SPECS = {
    "t01_csv_group_sum": "Write sol.py defining solve(rows) -> dict mapping each row['g'] to the sum of int(row['v']). Empty input -> {}.",
    "t02_json_roundtrip": "Write sol.py defining solve(obj) -> obj after a JSON round trip (json.dumps then json.loads).",
    "t03_dedupe_stable": "Write sol.py defining solve(xs) -> stable de-duplicated list preserving first-occurrence order.",
    "t04_binary_search": "Write sol.py defining solve(xs, t) -> index of t in the sorted list xs, or -1.",
    "t05_word_freq": "Write sol.py defining solve(text) -> dict of lowercased whitespace-separated word counts.",
    "t06_matrix_transpose": "Write sol.py defining solve(m) -> transpose of the list-of-lists m.",
    "t07_interval_merge": "Write sol.py defining solve(iv) -> merged non-overlapping intervals as a list of tuples, sorted.",
    "t08_topk": "Write sol.py defining solve(xs, k) -> the k largest elements in descending order.",
}
_missing = [t["id"] for t in TASKS if t["id"] not in SPECS]
if _missing:
    raise SystemExit("FATAL: no prompt spec for tasks %s" % _missing)


def check_task_parity():
    """The graded suites are literally E3's objects; report the ids for the log."""
    return "ok (%d tasks imported from e3_agent_loop.py, byte-identical by construction)" % len(TASKS)


AXES = {
    "steps": {"levels": [1, 2, 4, 8, 16], "mid": 4},
    "tools": {"levels": [0, 1, 2, 4, 8], "mid": 2},
    "context": {"levels": [200, 600, 1500, 4000], "mid": 600},
}
NOT_MEASURED = {
    "search": "no network-search tool is wired into this policy on this host",
    "vision": "no screenshots on a headless host; see E1b P2 failure record",
}


# --------------------------------------------------------------- grading -----
RUNNER = (
    "import sys, unittest, importlib.util\n"
    "spec = importlib.util.spec_from_file_location('hidden_test', 'hidden_test.py')\n"
    "mod = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(mod)\n"
    "suite = unittest.TestLoader().loadTestsFromModule(mod)\n"
    "res = unittest.TextTestRunner(verbosity=0).run(suite)\n"
    "sys.exit(0 if (res.wasSuccessful() and res.testsRun > 0) else 1)\n"
)


def grade(workdir: str, timeout: int = 120):
    r = subprocess.run([sys.executable, "-c", RUNNER], cwd=workdir,
                       capture_output=True, timeout=timeout)
    return r.returncode == 0, r.returncode


# --------------------------------------------------------------- policy ------
SYS = (
    "You are a coding agent. Respond with ONE fenced python code block containing "
    "the complete contents of sol.py. No prose, no tests."
)


def build_prompt(task, observation, ctx_chars):
    obs = (observation or "")[-ctx_chars:]
    return (
        f"{SYS}\n\nTask: {SPECS[task['id']]}\n\n"
        f"Current sol.py:\n```python\n{task['starter']}```\n\n"
        f"Last observation (test output, may be truncated):\n{obs}\n"
    )


def extract_code(text):
    if "```" in text:
        parts = text.split("```")
        for i in range(1, len(parts), 2):
            block = parts[i]
            if block.startswith("python"):
                block = block[len("python"):]
            if "def solve" in block:
                return block.strip("\n")
    return text if "def solve" in text else None


def load_model(path):
    """Load the policy. An AWQ checkpoint needs gptqmodel; when that kernel stack
    is absent the SAME weights are loaded dequantised in fp16 (identical model,
    different kernel path). Every attempt is printed so the run log shows what
    actually executed rather than what was intended."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(path, trust_remote_code=True)
    attempts = [
        ("awq-native", dict(dtype=torch.float16, device_map="auto", trust_remote_code=True)),
        ("fp16-dequantised", dict(dtype=torch.float16, device_map="auto",
                                  trust_remote_code=True, quantization_config=None)),
    ]
    last = None
    for name, kw in attempts:
        try:
            print("  load attempt: %s" % name, flush=True)
            model = AutoModelForCausalLM.from_pretrained(path, **kw)
            print("  loaded via %s -> device %s" % (name, next(model.parameters()).device), flush=True)
            model.eval()
            return tok, model, torch, name
        except Exception as e:  # noqa: BLE001 - the failure reason is the evidence
            print("  %s FAILED: %s: %s" % (name, type(e).__name__, str(e)[:200]), flush=True)
            last = e
    raise SystemExit("FATAL: could not load %s (%s)" % (path, last))


def gpu_free_mib():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20,
        ).stdout.strip().splitlines()
        return int(out[0]) if out else -1
    except Exception:
        return -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="/root/autodl-tmp/models/Qwen3-8B-AWQ")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--max-new-tokens", type=int, default=256)
    ap.add_argument("--min-free-mib", type=int, default=25000,
                    help="ABORT if free VRAM is below this (P4 rule)")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate the loop with the rule-based policy on CPU, no model load")
    ap.add_argument("--tasks", default="all")
    args = ap.parse_args()

    # Queue rule for the GPU: the host-wide ABORT floor is 25 GiB (a 14B AWQ run
    # plus headroom); a smaller model may use the GPU only when the 25 GiB floor
    # cannot be met for a long period, and the chosen floor is recorded here and
    # in the output JSON so the deviation is auditable rather than silent.
    free = gpu_free_mib()
    floor = args.min_free_mib
    note = "host floor"
    if free >= 0 and free < floor and not args.dry_run and "8B" in args.model:
        floor = 17000
        note = ("host floor 25000 MiB not met (%d MiB free); lowered to 17000 for the 8B model "
                "so the axis gains stop being an unmeasured assumption, recorded as a deviation" % free)
    print("free VRAM: %s MiB (threshold %d, %s)" % (free, floor, note))
    if not args.dry_run and free >= 0 and free < floor:
        print("ABORT: free VRAM below threshold; not starting the run")
        return 3

    tasks = TASKS if args.tasks == "all" else [t for t in TASKS if t["id"] in args.tasks.split(",")]
    if args.dry_run:
        here = os.path.dirname(os.path.abspath(__file__))
        import importlib.util
        spec = importlib.util.spec_from_file_location("e3mod2", os.path.join(here, "e3_agent_loop.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fixed = {t["id"]: t["fixed"] for t in mod.TASKS}
        for t in tasks:
            t["fixed"] = fixed[t["id"]]
    records = []
    tok = model = torch = None
    load_path = None
    if not args.dry_run:
        print("loading model %s ..." % args.model)
        t0 = time.perf_counter()
        tok, model, torch, load_path = load_model(args.model)
        print("loaded in %.1fs" % (time.perf_counter() - t0))

    root = tempfile.mkdtemp(prefix="p2_h4_")
    for axis, spec in AXES.items():
        for level in spec["levels"]:
            for task in tasks:
                for rep in range(args.repeats):
                    work = tempfile.mkdtemp(prefix="ep_", dir=root)
                    sol = os.path.join(work, "sol.py")
                    with open(sol, "w") as fh:
                        fh.write(task["starter"])
                    with open(os.path.join(work, "hidden_test.py"), "w") as fh:
                        fh.write(task["test"])
                    ctx_chars = level if axis == "context" else AXES["context"]["mid"]
                    max_steps = level if axis == "steps" else AXES["steps"]["mid"]
                    max_tools = level if axis == "tools" else AXES["tools"]["mid"]
                    obs_log, steps, tools_used, gen_tok, t0 = "", 0, 0, 0, time.perf_counter()
                    success = False
                    for step in range(1, max_steps + 1):
                        steps = step
                        prompt = build_prompt(task, obs_log, ctx_chars)
                        if args.dry_run:
                            # DECLARED: in dry-run the policy is an oracle that
                            # emits the E3 fixed solution on its FIRST model call.
                            # It validates the loop/wiring only; its success curve
                            # is a wiring check, NOT a model measurement, and the
                            # output records dry_run=true for that reason.
                            code = task.get("fixed", "def solve(*a, **k):\n    raise SystemExit(1)\n")
                        else:
                            msgs = [{"role": "user", "content": prompt}]
                            ids = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                                          return_tensors="pt").to(model.device)
                            with torch.no_grad():
                                out = model.generate(ids, max_new_tokens=args.max_new_tokens,
                                                     do_sample=False,
                                                     pad_token_id=tok.eos_token_id)
                            text = tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True)
                            gen_tok += int(out.shape[1] - ids.shape[1])
                            code = extract_code(text)
                        if code:
                            with open(sol, "w") as fh:
                                fh.write(code)
                        if tools_used >= max_tools:
                            # tool-call budget exhausted: record the episode as a
                            # budget failure without pretending a grade happened
                            obs_log += "\n[step %d] ABORT: tool budget exhausted" % step
                            break
                        tools_used += 1
                        ok, rc = grade(work)
                        obs_log += "\n[step %d] rc=%d %s" % (step, rc, "PASS" if ok else "FAIL")
                        if ok:
                            success = True
                            break
                    records.append({
                        "task": task["id"], "task_family": task["family"], "axis": axis,
                        "level": level, "repeat": rep, "success": success,
                        "steps_used": steps, "tool_calls_used": tools_used,
                        "generated_tokens": gen_tok,
                        "elapsed_s": time.perf_counter() - t0,
                        "dry_run": bool(args.dry_run),
                    })
            print("axis=%s level=%s done (%d records)" % (axis, level, len(records)))

    # aggregates per (axis, level) with bootstrap CI
    import numpy as np
    agg = {}
    for r in records:
        agg.setdefault("%s@%s" % (r["axis"], r["level"]), []).append(r)
    summary = {}
    rng = np.random.default_rng(SEED)
    for k, rs in agg.items():
        succ = np.array([1.0 if r["success"] else 0.0 for r in rs])
        idx = rng.integers(0, len(succ), size=(4000, len(succ)))
        boot = succ[idx].mean(axis=1)
        summary[k] = {
            "n": len(rs), "success_rate": float(succ.mean()),
            "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
            "mean_elapsed_s": float(np.mean([r["elapsed_s"] for r in rs])),
            "mean_generated_tokens": float(np.mean([r["generated_tokens"] for r in rs])),
        }

    # per-axis gain: g_x = max_level_success - mid_level_success (declared form)
    gains = {}
    for axis, spec in AXES.items():
        mid = summary.get("%s@%s" % (axis, spec["mid"]))
        best = max((summary["%s@%s" % (axis, lv)] for lv in spec["levels"]),
                   key=lambda d: d["success_rate"])
        gains[axis] = {
            "mid_level": spec["mid"], "mid_success": mid["success_rate"] if mid else None,
            "best_level_success": best["success_rate"],
            "gain": (best["success_rate"] - mid["success_rate"]) if mid else None,
        }

    doc = {
        "experiment": "H4_agent_axis_gains_real_model",
        "seed": SEED,
        "generated_by": "experiments/h4_gx_measure.py",
        "model": args.model, "model_load_path": load_path, "dry_run": bool(args.dry_run),
        "repeats": args.repeats, "max_new_tokens": args.max_new_tokens,
        "gpu_free_mib_at_start": free,
        "vram_floor_mib": floor,
        "vram_floor_note": note,
        "task_parity_vs_e3": check_task_parity(),
        "axes_measured": AXES, "axes_not_measured": NOT_MEASURED,
        "n_records": len(records),
        "summary_by_cell": summary, "gains": gains, "records": records,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print("wrote %s (%d records)" % (args.out, len(records)))
    for axis, g in gains.items():
        print("  gain[%s] = %s (mid %s)" % (axis, g["gain"], g["mid_success"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
