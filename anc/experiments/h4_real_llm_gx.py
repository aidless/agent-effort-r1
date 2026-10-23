#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H4 — measuring the agent-axis gains g_x under a REAL LLM policy.

Hypothesis under test (HYPOTHESES.md H4)
---------------------------------------
E2 fitted the allocation frontier with *assumed* agent-axis gains
(``gain_steps=0.30``, ``gain_tools=0.25``, ``gain_vision=0.20``, with
half-saturations ``ref_x``). E3 reproduced the saturation shape with a
DETERMINISTIC rule-based policy, so it cannot speak about a model's effort
behaviour at all.  H4 replaces the rule-based repairer with a real
instruction-tuned coding model and re-measures ``g_steps``, ``g_tools`` and
``g_vision`` from executed episodes.

Isomorphism with E3 (by construction, not by copy)
--------------------------------------------------
This script *imports* ``TASKS``, ``BUDGET_LEVELS``, ``SCHEDULES`` and
``run_hidden_tests`` from ``experiments/e3_agent_loop.py``.  The task set (8
program-synthesis tasks with hidden unittest suites), the five budget levels
and the two action schedules are therefore byte-identical to E3.  The
schedule axis is realised as the *advertised action menu*:

    read_then_write  ->  {read, write, test}          (local-only menu)
    probe_heavy      ->  {read, probe, write, test}   (adds the vision probe)

which is exactly the E3 distinction (E3's second schedule spends an early
vision probe and fails when the budget does not grant it).

What is real
------------
* Tasks, hidden tests and grading: identical to E3; success is the exit code
  of the hidden unittest subprocess and nothing else.  The agent CANNOT read
  the hidden tests -- ``read`` opens ``sol.py`` only, and ``probe`` returns
  lengths, never text.
* The action sequence is chosen by the model itself, one JSON action per turn.
* Every action costs real wall-clock time, counted per episode.
* Budget enforcement is byte-identical to E3 (steps / tool calls / context
  chars / vision probes); exceeding any of them fails the episode.

What is NOT real (declared, never hidden)
-----------------------------------------
* ``--backend stub`` runs a deterministic in-process simulator that emits the
  SAME action protocol.  It exists to prove the control flow, the budget
  accounting, the grader, the fitter and the identifiability guard work
  end-to-end on CPU with no GPU and no network.  Stub output is flagged
  ``dry_run: true`` / ``is_real_llm: false`` and MUST NOT be reported as a
  measurement of any model.
* The task SPEC visible to the model is derived from the hidden test suite
  (see ``SPEC`` below).  The model sees the spec and the starter file; it does
  not see the assertions.
* The reasoning-token axis (b_reason) is not swept here; it is absorbed into
  the fitted base-failure term ``p0``.  The search axis (b_search) is not
  exercised by this task set at all, so ``g_search`` is deliberately left
  UNMEASURED by H4 rather than fitted from no variation.
* The half-saturations ``ref_x`` are carried over from E2 as assumptions, not
  measured here; a ref-sensitivity refit is reported alongside.

Output: results/h4_real_llm_gx.json          (real run)
        results/h4_dryrun_stub.json          (CPU dry run, not a measurement)
Run (dry, CPU, no GPU, no network):
    python3 experiments/h4_real_llm_gx.py --backend stub --out results/h4_dryrun_stub.json
Run (real, GPU -- only inside the shared GPU lock, see --gpu-lock):
    flock "$H4_GPU_LOCK" python3 experiments/h4_real_llm_gx.py \
        --backend vllm --model "$MODEL_DIR/Qwen3-8B-AWQ" \
        --out "$H4_OUT_DIR/h4_real_llm_gx_qwen3_8b.json"

Environment (no value is baked in):
    H4_GPU_LOCK   path of the shared host lock      (default: ./gpu.lock)
    H4_OUT_DIR    directory for results             (default: ./results)
    --model       local path of the AWQ checkpoint  (required for --backend vllm)
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time

SEED = 20260911
HERE = os.path.dirname(os.path.abspath(__file__))

# GPU discipline: one shared lock for the whole host, free-memory pre-flight.
# Host-agnostic by construction: this file ships as a reproducibility artifact and
# must contain no absolute host path.  Every site-specific location is supplied by
# the environment or by a flag.
DEFAULT_GPU_LOCK = os.environ.get("H4_GPU_LOCK", "gpu.lock")
DEFAULT_OUT_DIR = os.environ.get("H4_OUT_DIR", "results")
MIN_FREE_MIB = 25600  # abort below this; a 14B-AWQ + KV cache needs headroom

# --------------------------------------------------------------------------
# Task specifications visible to the model.  Each line states the CONTRACT the
# hidden suite checks; the assertions themselves stay hidden.  Derived from the
# tests in e3_agent_loop.py (t01..t08) so that H4 and E3 grade the same thing.
# --------------------------------------------------------------------------
SPEC = {
    "t01_csv_group_sum": "solve(rows): rows is a list of dicts with keys 'g' and 'v' (v is a numeric string). "
                         "Return a dict mapping each distinct group g to the sum of int(v) over its rows. Empty input -> {}.",
    "t02_json_roundtrip": "solve(obj): return a deep copy of obj produced by serialising to JSON and parsing back. "
                          "Inputs are JSON-serialisable (dict/list/None).",
    "t03_dedupe_stable": "solve(xs): return the elements of xs with duplicates removed, keeping the FIRST occurrence order.",
    "t04_binary_search": "solve(xs, t): xs is sorted ascending. Return the index of t in xs, or -1 if t is absent.",
    "t05_word_freq": "solve(text): return a dict counting lowercase whitespace-separated words in text "
                     "(text.lower().split()). Empty text -> {}.",
    "t06_matrix_transpose": "solve(m): return the transpose of the matrix m (list of rows) as a list of lists.",
    "t07_interval_merge": "solve(iv): iv is a list of (start, end) tuples. Merge overlapping/touching intervals "
                          "and return them sorted by start as tuples. Empty input -> [].",
    "t08_topk": "solve(xs, k): return the k largest elements of xs in descending order "
                "(fewer than k elements -> all of them).",
}

# --------------------------------------------------------------------------
# backends
# --------------------------------------------------------------------------


class StubBackend:
    """Deterministic in-process simulator.  CPU-only, no GPU, no network.

    It speaks the exact same action protocol as the real backend so that the
    episode loop, the budget enforcement, the hidden-test grader and the
    fitter are all exercised.  Its competence is a DECLARED monotone function
    of the advertised budgets; it is a control-flow validator, not a model.
    """

    name = "stub"
    is_real_llm = False

    def chat(self, messages, seed, max_tokens):
        text = messages[-1]["content"] if isinstance(messages[-1].get("content"), str) else ""
        budget = _parse_budget(text)
        menu = _parse_menu(text)
        state = _parse_state(text)
        task_id = _parse_task(text)
        return json.dumps(_stub_action(menu, budget, state, seed, task_id))


def _parse_budget(text):
    m = re.search(r"max_steps=(\d+).*?max_tool_calls=(\d+).*?max_context_chars=(\d+).*?max_vision_probes=(\d+)",
                  text, re.S)
    if not m:
        return {"max_steps": 32, "max_tool_calls": 24, "max_context_chars": 12000, "max_vision_probes": 8}
    return {"max_steps": int(m.group(1)), "max_tool_calls": int(m.group(2)),
            "max_context_chars": int(m.group(3)), "max_vision_probes": int(m.group(4))}


def _parse_menu(text):
    m = re.search(r"allowed actions:\s*([a-z_, ]+)", text)
    if not m:
        return ["read", "write", "test"]
    return [a.strip() for a in m.group(1).split(",") if a.strip()]


def _parse_state(text):
    """Machine-readable turn state, carried on its own prompt line.

    The verbose history is NOT parsed: the reference solutions contain square
    brackets (e.g. ``out[-1][1]``), so any regex over the history is unsound.
    """
    m = re.search(r"state:\s*(\{.*?\})\s*\n", text, re.S)
    if not m:
        return {"steps_used": 0, "tools_used": 0, "vision_used": 0, "actions": []}
    try:
        s = json.loads(m.group(1))
        return s if isinstance(s, dict) else {"actions": []}
    except Exception:
        return {"steps_used": 0, "tools_used": 0, "vision_used": 0, "actions": []}


def _parse_task(text):
    m = re.search(r"task:\s*(t\d+_\w+)", text)
    return m.group(1) if m else "t01_csv_group_sum"


# Declared ground truth of the stub simulator.  The stub draws its success
# probability from E2's own functional form with these constants, so a correct
# fitter must recover them: the CPU dry run is therefore a RECOVERY SELF-CHECK
# of the fitting code, not merely a smoke test.  These numbers are simulator
# parameters -- they are NOT a measurement of any model.
STUB_TRUTH = {"p0": 0.55, "g_steps": 0.35, "g_tools": 0.28, "g_vision": 0.22,
              "ref_steps": 10.0, "ref_tools": 6.0, "ref_vision": 4.0}


def stub_competence(budget):
    """Declared success probability of the stub under an advertised budget."""
    prod = 1.0
    for ax, field in (("steps", "max_steps"), ("tools", "max_tool_calls"),
                      ("vision", "max_vision_probes")):
        b = float(budget[field])
        sat = 1.0 - math.exp(-b / STUB_TRUTH["ref_" + ax])
        prod *= (1.0 - STUB_TRUTH["g_" + ax] * sat)
    return 1.0 - (1.0 - STUB_TRUTH["p0"]) * prod


def _stub_plan(menu, budget):
    """A budget-aware action plan for the stub.

    The stub plans a sequence it can actually COMPLETE.  Without this, a tight
    step or tool budget blocks the mandatory ``write``+``test`` suffix, and the
    resulting feasibility cliff is indistinguishable from a saturated gain --
    the fitter then blames the axis for a threshold effect (observed: g_steps
    recovered as 0.50 against a declared 0.35).  That was a STUB artefact: a
    real model adapts its plan to the budget, so the stub must too.
    """
    def tools_needed(seq):
        return sum(1 for a in seq if a in ("read", "probe", "test"))

    seq = []
    for extra in ("read", "probe"):
        if extra not in menu:
            continue
        cand = seq + [extra]
        if len(cand) + 2 > budget["max_steps"]:
            continue
        if tools_needed(cand) + 1 > budget["max_tool_calls"]:
            continue
        if extra == "probe" and budget["max_vision_probes"] < 1:
            continue
        seq = cand
    return seq + ["write", "test"]


def _stub_action(menu, budget, state, seed, task_id):
    """Declared deterministic policy of the stub.

    Success probability follows E2's functional form with STUB_TRUTH gains, so
    every branch of the pipeline -- including a non-trivial least-squares fit,
    its bootstrap CI and the identifiability guard -- is exercised on CPU.
    """
    actions = list(state.get("actions") or [])
    competence = stub_competence(budget)
    plan = _stub_plan(menu, budget)
    i = len(actions)
    a = plan[i] if i < len(plan) else plan[-1]
    if a == "write":
        good = random.Random(seed).random() < competence
        return {"action": "write", "code": _stub_code(task_id, good)}
    return {"action": a}


def _stub_code(task_id, good):
    """The stub returns E3's own reference solution when it 'succeeds'."""
    if good:
        return FIXED_BY_ID.get(task_id, "")
    return STARTER_BY_ID.get(task_id, "")


class VLLMBackend:
    """Local AWQ model served in-process by vLLM.  GPU.  Lazily imported.

    Deliberately constructed with temperature 0 and a per-request seed so that
    two runs of the same arm are comparable; sampling determinism is still not
    exact on GPU and is declared as such in the output.
    """

    name = "vllm"
    is_real_llm = True

    def __init__(self, model_path, max_model_len=8192, gpu_memory_utilization=0.90,
                 tensor_parallel_size=1, max_tokens=1024, enforce_eager=False,
                 chat_mode="think_off"):
        from vllm import LLM, SamplingParams  # heavy, GPU-only import
        self._SamplingParams = SamplingParams
        self.max_tokens = max_tokens
        self.model_path = model_path
        # Qwen3 hybrid reasoning: with thinking ON the model emits ~974 tokens of
        # <think> before the action and TRUNCATES at max_tokens before reaching
        # the JSON (measured 2026-09-11: 7.46 s/gen, 30% of episodes lost to
        # parse_failures).  With enable_thinking=False: 0.58 s/gen, 74 tokens,
        # 6/6 valid JSON.  Thinking OFF is also the correct CONTROL for this
        # experiment, which does not sweep the reasoning axis (b_reason is
        # absorbed into p0): reasoning is held fixed while steps/tools/vision vary.
        self.chat_mode = chat_mode
        self.chat_mode_effective = chat_mode
        self.llm = LLM(
            model=model_path,
            quantization="awq",
            dtype="float16",
            max_model_len=max_model_len,
            gpu_memory_utilization=gpu_memory_utilization,
            tensor_parallel_size=tensor_parallel_size,
            trust_remote_code=True,
            enforce_eager=enforce_eager,
        )
        self.tok = None
        if chat_mode == "think_off":
            try:
                self.tok = self.llm.get_tokenizer()
                self.tok.apply_chat_template(
                    [{"role": "user", "content": "x"}], tokenize=False,
                    add_generation_prompt=True, enable_thinking=False)
            except Exception as e:
                print("  think_off unsupported (%s); falling back to chat()" % type(e).__name__,
                      flush=True)
                self.tok, self.chat_mode_effective = None, "chat_default"

    def chat(self, messages, seed, max_tokens):
        sp = self._SamplingParams(temperature=0.0, top_p=1.0, max_tokens=max_tokens, seed=int(seed))
        if self.chat_mode_effective == "think_off":
            prompt = self.tok.apply_chat_template(messages, tokenize=False,
                                                  add_generation_prompt=True,
                                                  enable_thinking=False)
            out = self.llm.generate([prompt], sp, use_tqdm=False)
            return out[0].outputs[0].text
        out = self.llm.chat(messages, sp, use_tqdm=False)
        return out[0].outputs[0].text


# --------------------------------------------------------------------------
# E3 isomorphism: import the real task set / budgets / grader
# --------------------------------------------------------------------------


def _load_e3():
    path = os.path.join(HERE, "e3_agent_loop.py")
    spec = importlib.util.spec_from_file_location("e3_agent_loop", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


E3 = _load_e3()
TASKS = E3.TASKS
BUDGET_LEVELS = E3.BUDGET_LEVELS
SCHEDULES = E3.SCHEDULES
run_hidden_tests = E3.run_hidden_tests

TASK_BY_ID = {t["id"]: t for t in TASKS}
STARTER_BY_ID = {t["id"]: t["starter"] for t in TASKS}
FIXED_BY_ID = {t["id"]: t["fixed"] for t in TASKS}

# menu for each E3 schedule: probe_heavy advertises the vision probe, the other
# one does not.  This is the E3 schedule distinction, realised as an action menu.
MENUS = {
    "read_then_write": ["read", "write", "test"],
    "probe_heavy": ["read", "probe", "write", "test"],
}

# --------------------------------------------------------------------------
# arms: the isomorphic replication + three single-axis sweeps
# --------------------------------------------------------------------------
# The iso arm reuses E3's five coupled levels verbatim.  The axis arms vary ONE
# axis while the others are held permissive, which is what makes g_x separately
# identifiable -- in the iso arm the four budgets move together and the gains
# are not separable.  Declared, not hidden.

AXIS_SWEEPS = {
    "axis_steps": ("max_steps", [2, 4, 8, 16, 32]),
    "axis_tools": ("max_tool_calls", [0, 1, 2, 4, 8, 16, 24]),
    "axis_vision": ("max_vision_probes", [0, 1, 2, 4, 8, 16]),
}
# The non-varying axes are held at E2's MID allocation (reason=50, steps=8,
# tools=4, vision=2), i.e. strictly INTERIOR, never at the ceiling: a gain cannot
# be identified from a sweep whose companions already saturate the response.
PERMISSIVE = {"max_steps": 8, "max_tool_calls": 4, "max_context_chars": 1500, "max_vision_probes": 2}


def arms():
    out = []
    for _ms, _mt, _mc, _mv, label in BUDGET_LEVELS:
        for sched in SCHEDULES:
            out.append({"arm": "iso", "level": label, "menu": sched,
                        "budget": _budget_of(label)})
    for arm_name, (field, values) in AXIS_SWEEPS.items():
        for v in values:
            budget = dict(PERMISSIVE)
            budget[field] = v
            out.append({"arm": arm_name, "level": "%s=%d" % (field, v), "menu": "probe_heavy",
                        "budget": budget})
    return out


def _budget_of(label):
    for ms, mt, mc, mv, lab in BUDGET_LEVELS:
        if lab == label:
            return {"max_steps": ms, "max_tool_calls": mt, "max_context_chars": mc,
                    "max_vision_probes": mv}
    raise KeyError(label)


# --------------------------------------------------------------------------
# prompt / action parsing
# --------------------------------------------------------------------------

def episode_seed(task_id, rep):
    """Per-episode seed.

    Derived from a hash of the task id and NOT from ``len(task_id)``: task ids
    collide in length (17 vs 18 chars), which silently collapses independent
    per-task draws into two, and with them the resolution of the whole sweep.
    """
    h = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8]
    return SEED + 7919 * (rep + 1) + int(h, 16) % 100000


SYS = (
    "You are an autonomous coding agent working in a sandbox directory.\n"
    "The file sol.py contains a function that is currently WRONG.\n"
    "Reply with EXACTLY ONE JSON object and nothing else. No markdown fences, no prose.\n"
    "Available actions (reply with one of these JSON shapes):\n"
    '  {"action": "read"}                         read sol.py; the contents are returned to you\n'
    '  {"action": "probe"}                        coarse structural summary (sizes only, never code text)\n'
    '  {"action": "write", "code": "<python>"}    overwrite sol.py with the COMPLETE file\n'
    '  {"action": "test"}                         run the HIDDEN test suite; you get only {"rc": 0|1}\n'
    "The hidden test suite cannot be read. Only the exit code is revealed.\n"
    "Exceeding any budget ends the task as a failure."
)

USER_TMPL = (
    "task: {task_id}\n"
    "spec: {spec}\n"
    "starter file sol.py:\n---\n{starter}\n---\n"
    "allowed actions: {menu}\n"
    "budget: max_steps={max_steps} max_tool_calls={max_tool_calls} "
    "max_context_chars={max_context_chars} max_vision_probes={max_vision_probes}\n"
    "state: {state_json}\n"
    "history: {history}\n"
    "Reply with the next single JSON action."
)


def build_messages(task, menu, budget, starter, history, steps_used, tools_used, vision_used):
    state = {"steps_used": steps_used, "tools_used": tools_used,
             "vision_used": vision_used,
             "actions": [h.get("action") for h in history]}
    return [
        {"role": "system", "content": SYS},
        {"role": "user", "content": USER_TMPL.format(
            task_id=task["id"], spec=SPEC[task["id"]], starter=starter,
            menu=", ".join(menu),
            state_json=json.dumps(state, ensure_ascii=False),
            history=json.dumps(history, ensure_ascii=False)[-3000:],
            **budget)},
    ]


_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def parse_action(raw, menu):
    """Tolerant JSON-action parser.  Returns (action_dict|None, error_str|None)."""
    if not isinstance(raw, str) or not raw.strip():
        return None, "empty"
    cands = []
    m = _FENCE.search(raw)
    if m:
        cands.append(m.group(1))
    cands.append(raw.strip())
    # last balanced-brace object in the text
    depth, start = 0, None
    for i, ch in enumerate(raw):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                cands.append(raw[start:i + 1])
                start = None
    for c in cands:
        try:
            obj = json.loads(c)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        a = obj.get("action")
        if a in menu:
            if a == "write" and not isinstance(obj.get("code"), str):
                return None, "write_without_code"
            return {"action": a, "code": obj.get("code")}, None
    return None, "unparseable_or_disallowed"


# --------------------------------------------------------------------------
# episode
# --------------------------------------------------------------------------


class BudgetExceeded(Exception):
    pass


def episode(backend, task, arm, seed, tmpdir, prompt_char_limit=12000):
    """One real agent episode under a hard budget, with the LLM in the loop."""
    budget = arm["budget"]
    menu = MENUS[arm["menu"]]
    max_steps = budget["max_steps"]
    max_tools = budget["max_tool_calls"]
    max_ctx = budget["max_context_chars"]
    max_vision = budget["max_vision_probes"]

    work = tempfile.mkdtemp(prefix="p2_h4_", dir=tmpdir)
    with open(os.path.join(work, "sol.py"), "w") as fh:
        fh.write(task["starter"])
    with open(os.path.join(work, "hidden_test.py"), "w") as fh:
        fh.write(task["test"])

    steps = tools = vision = 0
    ctx_chars = 0
    t0 = time.perf_counter()
    history = []
    success = False
    reason = "budget"
    parse_errors = 0
    gen_ms_total = 0.0

    try:
        while True:
            steps += 1
            if steps > max_steps:
                raise BudgetExceeded("steps")
            msgs = build_messages(task, menu, budget, task["starter"], history,
                                  steps, tools, vision)
            t_gen = time.perf_counter()
            raw = backend.chat(msgs, seed + 1000 * steps, 1024)
            gen_ms_total += (time.perf_counter() - t_gen) * 1000.0
            act, err = parse_action(raw, menu)
            if act is None:
                parse_errors += 1
                history.append({"action": "invalid", "error": err, "raw_head": raw[:160]})
                # an invalid action is still a spent step, but costs no tool call
                if parse_errors >= 3:
                    reason = "parse_failures"
                    break
                continue

            a = act["action"]
            if a == "read":
                if tools + 1 > max_tools:
                    raise BudgetExceeded("tool_calls")
                with open(os.path.join(work, "sol.py")) as fh:
                    obs = fh.read()
                ctx_chars += len(obs)
                tools += 1
                history.append({"action": "read", "obs": obs})
            elif a == "probe":
                if tools + 1 > max_tools:
                    raise BudgetExceeded("tool_calls")
                if vision + 1 > max_vision:
                    raise BudgetExceeded("vision_probes")
                vision += 1
                # sizes only: the probe never leaks test text
                obs = " ".join(str(len(d)) for d in
                               [task["id"], task["starter"], task["test"], task["family"]])
                ctx_chars += len(obs)
                tools += 1
                history.append({"action": "probe", "obs": obs})
            elif a == "write":
                code = act["code"]
                with open(os.path.join(work, "sol.py"), "w") as fh:
                    fh.write(code)
                history.append({"action": "write", "chars": len(code)})
            elif a == "test":
                if tools + 1 > max_tools:
                    raise BudgetExceeded("tool_calls")
                tools += 1
                ok, rc = run_hidden_tests(work)
                history.append({"action": "test", "rc": rc})
                if ok:
                    success = True
                    reason = "tests_passed"
                    break
            if ctx_chars > max_ctx:
                raise BudgetExceeded("context_chars")
    except BudgetExceeded as e:
        reason = "budget:" + str(e)
    except Exception as e:
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
        "arm": arm["arm"],
        "level": arm["level"],
        "menu": arm["menu"],
        "budget": dict(budget),
        "steps_used": steps,
        "tool_calls_used": tools,
        "vision_probes_used": vision,
        "context_chars_used": ctx_chars,
        "success": success,
        "reason": reason,
        "parse_errors": parse_errors,
        "elapsed_ms": elapsed_ms,
        "generation_ms": gen_ms_total,
        "n_history": len(history),
        "model_turns": [{"action": h.get("action"), "rc": h.get("rc")} for h in history],
    }
    shutil.rmtree(work, ignore_errors=True)
    return out


# --------------------------------------------------------------------------
# aggregation / statistics
# --------------------------------------------------------------------------


def wilson_ci(k, n, z=1.959963984540054):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"lo95": max(0.0, c - h), "hi95": min(1.0, c + h)}


def _bootstrap(xs, n_boot, seed):
    import numpy as np
    a = np.asarray(xs, dtype=float)
    if a.size < 2:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, a.size, size=(n_boot, a.size))
    st = a[idx].mean(axis=1)
    return {"mean": float(a.mean()), "lo95": float(np.percentile(st, 2.5)),
            "hi95": float(np.percentile(st, 97.5)), "n_boot": int(n_boot)}


# --------------------------------------------------------------------------
# g_x fit: 1 - p = (1 - p0) * prod_x (1 - g_x * (1 - exp(-b_x / ref_x)))
# --------------------------------------------------------------------------

REF_ASSUMED = {"steps": 10.0, "tools": 6.0, "vision": 4.0}
REF_SENSITIVITY = {"steps": [6.0, 10.0, 16.0], "tools": [3.0, 6.0, 12.0], "vision": [2.0, 4.0, 8.0]}
AXIS_FIELD = {"steps": "max_steps", "tools": "max_tool_calls", "vision": "max_vision_probes"}


def structurally_feasible(budget):
    """Can ANY policy succeed at this budget?

    Grading requires one tool call (``test``) and the write-before-test order
    requires two steps.  A budget below that floor cannot yield a success for
    any policy, model or rule-based, so its zero cells carry no information
    about a gain and are excluded from the fit instead of being attributed to
    the axis.  They are reported separately as `floor_cells`.
    """
    return budget["max_steps"] >= 2 and budget["max_tool_calls"] >= 1


def _design(cells, refs):
    """cells: [{'budget':..., 'fail': f, 'n': n}] -> (X axes, y, w)."""
    import numpy as np
    rows, ys, ws = [], [], []
    for c in cells:
        b = c["budget"]
        rows.append([float(b[AXIS_FIELD["steps"]]), float(b[AXIS_FIELD["tools"]]),
                     float(b[AXIS_FIELD["vision"]])])
        ys.append(c["fail"])
        ws.append(max(1.0, float(c["n"])))
    return np.asarray(rows), np.asarray(ys), np.asarray(ws)


def fit_gains(cells, refs=None, n_boot=400, seed=SEED, max_ci_width=0.30):
    """Least squares fit of (p0, g_steps, g_tools, g_vision).

    Returns point estimates, bootstrap CI and per-axis identifiability.  An axis
    is identified only if BOTH hold (see the identifiability block):
      (i) its sweep contains >= 2 cells strictly inside (0,1), AND
      (ii) its bootstrap CI95 width is <= max_ci_width.
    (i) alone is insufficient -- it certifies the sweep crossed the interior, not
    that the parameter is pinned.
    """
    import numpy as np
    from scipy.optimize import least_squares

    refs = refs or dict(REF_ASSUMED)
    X, y, w = _design(cells, refs)

    def predict(theta, Xm):
        p0 = theta[0]
        g = theta[1:4]
        sat = 1.0 - np.exp(-Xm / np.array([refs["steps"], refs["tools"], refs["vision"]]))
        prod = np.prod(1.0 - g[None, :] * sat, axis=1)
        return (1.0 - p0) * prod

    def resid(theta, Xm, ym, wm):
        return (predict(theta, Xm) - ym) * wm

    lo = np.array([0.0, 0.0, 0.0, 0.0])
    hi = np.array([0.999, 1.0, 1.0, 1.0])
    best = None
    for x0 in (np.array([0.5, 0.30, 0.25, 0.20]), np.array([0.3, 0.6, 0.6, 0.6]),
               np.array([0.8, 0.1, 0.1, 0.1])):
        try:
            r = least_squares(resid, x0, args=(X, y, w), bounds=(lo, hi), max_nfev=20000)
        except Exception:
            continue
        if best is None or r.cost < best.cost:
            best = r
    if best is None:
        return {"fitted": False, "reason": "least_squares_failed"}

    names = ["p0", "g_steps", "g_tools", "g_vision"]
    point = {n: float(v) for n, v in zip(names, best.x)}
    pred = predict(best.x, X)
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.average(y, weights=w)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else None

    # bootstrap over cells (parametric-free: resample cells with replacement)
    rng = np.random.default_rng(seed)
    boots = []
    m = len(cells)
    for _ in range(n_boot):
        idx = rng.integers(0, m, size=m)
        sub = [cells[i] for i in idx]
        Xb, yb, wb = _design(sub, refs)
        try:
            rb = least_squares(resid, best.x, args=(Xb, yb, wb), bounds=(lo, hi), max_nfev=10000)
        except Exception:
            continue
        boots.append([float(v) for v in rb.x])
    ci = {}
    if len(boots) >= 20:
        arr = np.asarray(boots)
        for j, n in enumerate(names):
            ci[n] = {"lo95": float(np.percentile(arr[:, j], 2.5)),
                     "hi95": float(np.percentile(arr[:, j], 97.5)),
                     "n_boot": int(arr.shape[0])}

    # Identifiability is a TWO-PART test.  "the sweep left saturation" alone is
    # too weak: it only checks that the curve crosses the interior, not that the
    # parameter is PINNED.  The 2026-09-12 Qwen3-8B run passed the interior test
    # for all three axes while the bootstrap CIs spanned ~1.0 of the [0,1] range
    # (g_steps=0.9128 CI [4.3e-14, 1.0]) -- i.e. the guard said "identified" for
    # parameters with NO constraint at all.  A gain may be quoted only if BOTH
    # hold: enough interior cells AND a bootstrap CI no wider than max_ci_width.
    ident = {}
    for ax in ("steps", "tools", "vision"):
        key = "axis_" + ax
        cells_ax = [c for c in cells if c.get("arm") == key]
        interior = [c for c in cells_ax if 0.0 < c["success"] < 1.0]
        rates = sorted({round(c["success"], 6) for c in cells_ax})
        c_ax = ci.get("g_" + ax)
        width = (c_ax["hi95"] - c_ax["lo95"]) if c_ax else None
        enough_interior = len(interior) >= 2
        tight_enough = (width is not None and width <= max_ci_width)
        reasons = []
        if not enough_interior:
            reasons.append("sweep saturated or floored: no interior information")
        if not tight_enough:
            reasons.append("bootstrap CI width %s > %.3f: parameter not pinned"
                           % ("%.3f" % width if width is not None else "n/a", max_ci_width))
        ident[ax] = {
            "n_cells": len(cells_ax),
            "n_interior_cells": len(interior),
            "distinct_success_rates": rates,
            "ci95_width": width,
            "test_interior_cells": bool(enough_interior),
            "test_ci_width": bool(tight_enough),
            "max_ci_width": max_ci_width,
            "identified": bool(enough_interior and tight_enough),
            "why": ("interior cells >= 2 AND CI width <= %.3f" % max_ci_width
                    if (enough_interior and tight_enough) else "; ".join(reasons)),
        }
    unidentified = [ax for ax, v in ident.items() if not v["identified"]]
    return {
        "fitted": True,
        "form": "1 - p = (1 - p0) * prod_x (1 - g_x * (1 - exp(-b_x / ref_x)))",
        "form_is_monotone_increase_of_p": True,
        "form_note": ("1-p is a product of factors that shrink monotonically as any "
                      "b_x grows, so p = 1-(1-p) CANNOT decrease in any axis; a "
                      "non-monotone observed curve is outside this model's range."),
        "refs_used": dict(refs),
        "refs_source": "E2 assumptions (REF_ASSUMED), not measured by H4",
        "params": point,
        "params_ci95": ci,
        "r_squared_on_cells": r2,
        "n_cells": m,
        "identifiability": ident,
        "unidentified_axes": unidentified,
        "point_estimates_withheld_for": unidentified,
        "note": ("a g_* may be quoted ONLY for an identified axis (interior cells >= 2 "
                 "AND bootstrap CI width <= max_ci_width). Unidentified axes are "
                 "reported as such and their point estimates MUST NOT be quoted."),
    }


def ref_sensitivity(cells):
    out = {}
    for r_steps in REF_SENSITIVITY["steps"]:
        for r_tools in REF_SENSITIVITY["tools"]:
            for r_vision in REF_SENSITIVITY["vision"]:
                key = "steps%.0f_tools%.0f_vision%.0f" % (r_steps, r_tools, r_vision)
                f = fit_gains(cells, refs={"steps": r_steps, "tools": r_tools, "vision": r_vision},
                              n_boot=0)
                out[key] = f.get("params") if f.get("fitted") else None
    return out


# --------------------------------------------------------------------------
# GPU discipline
# --------------------------------------------------------------------------


def script_sha256():
    """Hash of this file, so a result can be tied to the exact harness revision."""
    h = hashlib.sha256()
    with open(os.path.abspath(__file__), "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def model_fingerprint(path, full=True):
    """Content fingerprint of the checkpoint directory.

    Full SHA-256 of every file by default: a path and a size are not enough to
    say WHICH weights were measured.  `full=False` hashes only files <= 64 MiB
    and records size + partial hash for the rest (declared as partial).
    """
    if not path or not os.path.isdir(path):
        return {"path": path, "exists": False}
    files = []
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__",)]
        for fn in sorted(filenames):
            fp = os.path.join(dirpath, fn)
            try:
                size = os.path.getsize(fp)
            except OSError:
                continue
            rel = os.path.relpath(fp, path)
            rec = {"file": rel, "size": size}
            if full or size <= 64 << 20:
                h = hashlib.sha256()
                with open(fp, "rb") as fh:
                    for c in iter(lambda: fh.read(1 << 20), b""):
                        h.update(c)
                rec["sha256"] = h.hexdigest()
            else:
                with open(fp, "rb") as fh:
                    head = fh.read(1 << 20)
                rec["sha256_head1MiB"] = hashlib.sha256(head).hexdigest()
                rec["partial"] = True
            rec["symlink_to"] = os.path.realpath(fp) if os.path.islink(fp) else None
            files.append(rec)
            total += size
    return {"path": path, "exists": True, "n_files": len(files),
            "total_bytes": total, "full_hash": bool(full), "files": files}


def _pkg_version(name):
    try:
        mod = __import__(name)
        return getattr(mod, "__version__", "unknown")
    except Exception as e:
        return "%s unavailable (%s)" % (name, type(e).__name__)


def gpu_description():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                            "--format=csv,noheader"], capture_output=True, text=True, timeout=30)
        return r.stdout.strip() or None
    except Exception:
        return None


def gpu_memory_mib():
    """(total, free) MiB, or (None, None)."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.total,memory.free",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=30)
        line = (r.stdout.strip().splitlines() or [""])[0]
        t, f = [int(x.strip()) for x in line.split(",")[:2]]
        return t, f
    except Exception:
        return None, None


def adaptive_gpu_util(requested=0.90, reserve_mib=2048):
    """gpu_memory_utilization is a fraction of TOTAL memory in vLLM, but on a
    SHARED host the right question is how much of the FREE memory we may take.
    Requesting `requested` of total while a co-tenant holds memory is the bug
    that OOMs (measured: 0.90*48 GiB > free once a video job took 12.8 GiB).

    Returns (util, detail).  The reserve keeps headroom for a co-tenant to grow.
    """
    total, free = gpu_memory_mib()
    if not total or not free:
        return requested, {"mode": "fixed", "requested": requested, "reason": "nvidia-smi unavailable"}
    usable = max(0, free - reserve_mib)
    util = min(requested, usable / float(total))
    util = max(util, 0.10)
    return util, {"mode": "adaptive", "requested": requested, "total_mib": total,
                  "free_mib": free, "reserve_mib": reserve_mib,
                  "usable_mib": usable, "util": round(util, 4),
                  "note": "util = min(requested, (free - reserve)/total)"}


def gpu_free_mib():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=30)
    except Exception as e:
        return None, "nvidia-smi_failed:%s" % type(e).__name__
    if r.returncode != 0:
        return None, "nvidia-smi_rc=%d" % r.returncode
    vals = [int(x.strip()) for x in r.stdout.split() if x.strip().isdigit()]
    if not vals:
        return None, "no_gpu_reported"
    return max(vals), None


def preflight(min_free_mib):
    """Return (ok, detail).  Never starts a GPU job when the check fails."""
    free, err = gpu_free_mib()
    if err:
        return False, {"verdict": "ABORT", "reason": err, "required_free_mib": min_free_mib}
    ok = free >= min_free_mib
    return ok, {"verdict": "GO" if ok else "ABORT", "free_mib": free,
                "required_free_mib": min_free_mib,
                "reason": ("enough free VRAM" if ok else
                           "free VRAM below the discipline floor; do not start (no lock bypass)")}


class GpuLock:
    """flock(2) on the single shared lock path.  Non-blocking by default so a
    busy host aborts instead of silently queueing behind another job."""

    def __init__(self, path, blocking=False):
        self.path = path
        self.blocking = blocking
        self.fh = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fh = open(self.path, "a+")
        flags = fcntl.LOCK_EX | (0 if self.blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(self.fh.fileno(), flags)
        except OSError as e:
            self.fh.close()
            self.fh = None
            raise RuntimeError("gpu_lock_busy:%s" % e)
        self.fh.seek(0)
        self.fh.truncate()
        self.fh.write("pid=%d acquired=%s\n" % (os.getpid(), time.strftime("%Y-%m-%dT%H:%M:%S")))
        self.fh.flush()
        return self

    def __exit__(self, *exc):
        if self.fh:
            try:
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            finally:
                self.fh.close()
        return False


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="H4 — real-LLM agent-axis gains g_x")
    ap.add_argument("--backend", choices=["stub", "vllm"], default="stub")
    ap.add_argument("--model", default=None, help="local path to an AWQ checkpoint (vllm backend)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--arms", default="iso,axis_steps,axis_tools,axis_vision")
    ap.add_argument("--max-model-len", type=int, default=8192)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--chat-mode", choices=["think_off", "chat_default"], default="think_off",
                    help="think_off renders the prompt with enable_thinking=False (Qwen3 "
                         "non-thinking mode): 12.9x faster and no JSON truncation")
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.90,
                    help="UPPER BOUND on the fraction of total VRAM to use; on a shared "
                         "host it is clamped to the free memory (see --no-adapt-gpu-util)")
    ap.add_argument("--no-adapt-gpu-util", action="store_true",
                    help="use --gpu-memory-utilization verbatim instead of clamping it "
                         "to the currently free VRAM")
    ap.add_argument("--tmp", default=None)
    ap.add_argument("--gpu-lock", default=DEFAULT_GPU_LOCK)
    ap.add_argument("--external-lock", action="store_true",
                    help="the caller already holds --gpu-lock via `flock`; do NOT take it "
                         "again. flock() treats two fds on the same file as independent, "
                         "so a nested acquire on the outer lock is DENIED and the run "
                         "would abort. Set by experiments/h4_run_remote.sh.")
    ap.add_argument("--min-free-mib", type=int, default=MIN_FREE_MIB)
    ap.add_argument("--preflight-only", action="store_true",
                    help="run the VRAM pre-flight and exit (never loads the model)")
    ap.add_argument("--n-boot", type=int, default=400)
    ap.add_argument("--max-ci-width", type=float, default=0.30,
                    help="a g_x point estimate may be quoted only if its bootstrap "
                         "CI95 width is <= this (identifiability, part ii)")
    ap.add_argument("--ref-sensitivity", action="store_true")
    args = ap.parse_args()

    if args.backend == "vllm":
        ok, detail = preflight(args.min_free_mib)
        print("preflight:", json.dumps(detail, ensure_ascii=False))
        if args.preflight_only:
            return 0 if ok else 3
        if not ok:
            print("ABORT: %s (the shared GPU lock is not bypassed)" % detail["reason"])
            return 3
    elif args.preflight_only:
        print("preflight: skipped (backend=stub; no GPU is touched)")
        return 0

    util_detail = {"mode": "n/a", "reason": "CPU stub backend; no GPU allocation"}
    wanted = set(a.strip() for a in args.arms.split(",") if a.strip())
    selected = [a for a in arms() if a["arm"] in wanted]

    tmpdir = args.tmp or tempfile.mkdtemp(prefix="p2_h4_root_")
    os.makedirs(tmpdir, exist_ok=True)

    t_run0 = time.perf_counter()
    mdl_fp = model_fingerprint(args.model, full=True) if args.backend == "vllm" else None
    if mdl_fp:
        print("model fingerprint: %d files, %.2f GB, full_hash=%s"
              % (mdl_fp.get("n_files", 0), mdl_fp.get("total_bytes", 0) / 1e9, mdl_fp.get("full_hash")),
              flush=True)

    ctx = GpuLock(args.gpu_lock) if args.backend == "vllm" else _NullCtx()
    if args.backend == "vllm" and (args.external_lock or os.environ.get("H4_GPU_LOCK_HELD") == "1"):
        # The wrapper holds the lock.  Taking it again on a second fd is DENIED by
        # flock(), so the nested acquire is skipped rather than allowed to abort.
        lock_mode = "external (flock held by the caller)"
        ctx = _NullCtx()
        print("lock: %s; preflight already passed" % lock_mode)
    else:
        lock_mode = "internal (flock taken by this process)" if args.backend == "vllm" else "none (CPU stub)"
    try:
        with ctx:
            if args.backend == "vllm":
                if not args.model:
                    print("ERROR: --model is required with --backend vllm")
                    return 2
                if args.no_adapt_gpu_util:
                    util, util_detail = args.gpu_memory_utilization, {
                        "mode": "fixed", "requested": args.gpu_memory_utilization}
                else:
                    util, util_detail = adaptive_gpu_util(args.gpu_memory_utilization)
                print("gpu_memory_utilization: %s" % json.dumps(util_detail), flush=True)
                backend = VLLMBackend(args.model, max_model_len=args.max_model_len,
                                      gpu_memory_utilization=util,
                                      max_tokens=args.max_tokens,
                                      chat_mode=args.chat_mode)
            else:
                backend = StubBackend()

            records = []
            n_planned = len(selected) * len(TASKS) * args.repeats
            done = 0
            for arm in selected:
                for rep in range(args.repeats):
                    for task in TASKS:
                        seed = episode_seed(task["id"], rep)
                        rec = episode(backend, task, arm, seed, tmpdir)
                        rec["repeat"] = rep
                        rec["seed"] = seed
                        records.append(rec)
                        done += 1
                        if done % 20 == 0 or done == n_planned:
                            print("  %d/%d episodes" % (done, n_planned), flush=True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # per-cell aggregation
    cells = {}
    for r in records:
        k = "%s|%s|%s" % (r["arm"], r["level"], r["menu"])
        cells.setdefault(k, []).append(r)
    summary = {}
    for k, rs in cells.items():
        succ = [1.0 if x["success"] else 0.0 for x in rs]
        n, ks = len(rs), int(sum(succ))
        summary[k] = {
            "arm": rs[0]["arm"], "level": rs[0]["level"], "menu": rs[0]["menu"],
            "budget": rs[0]["budget"],
            "n": n, "n_success": ks, "success": ks / n,
            "success_ci95_wilson": wilson_ci(ks, n),
            "mean_steps": sum(x["steps_used"] for x in rs) / n,
            "mean_tool_calls": sum(x["tool_calls_used"] for x in rs) / n,
            "mean_vision_probes": sum(x["vision_probes_used"] for x in rs) / n,
            "mean_elapsed_ms": sum(x["elapsed_ms"] for x in rs) / n,
            "mean_generation_ms": sum(x["generation_ms"] for x in rs) / n,
            "parse_errors": sum(x["parse_errors"] for x in rs),
            "budget_hits": sorted({x["reason"] for x in rs if x["reason"].startswith("budget:")}),
            "failure_reasons": _counts(x["reason"] for x in rs),
        }

    # fit on the axis arms only (the iso arm is the E3 replication, and its
    # budgets move together so it cannot separate the gains)
    fit_cells = [{"arm": v["arm"], "budget": v["budget"], "fail": 1.0 - v["success"],
                  "n": v["n"], "success": v["success"]}
                 for v in summary.values() if v["arm"].startswith("axis_")]
    floor_cells = [c for c in fit_cells if not structurally_feasible(c["budget"])]
    fit_cells = [c for c in fit_cells if structurally_feasible(c["budget"])]
    fit = fit_gains(fit_cells, n_boot=args.n_boot, max_ci_width=args.max_ci_width) if fit_cells else {"fitted": False, "reason": "no axis arms"}
    sens = ref_sensitivity(fit_cells) if (args.ref_sensitivity and fit_cells) else None

    # CPU dry run only: the stub's declared gains must come back out of the
    # fitter.  A miss here is a BUG IN THE FITTER, and it is reported as such.
    recovery = None
    if args.backend == "stub" and fit.get("fitted"):
        recovery = {"declared": STUB_TRUTH, "params": {}}
        for key, ax in (("g_steps", "steps"), ("g_tools", "tools"), ("g_vision", "vision")):
            if ax in fit["unidentified_axes"]:
                recovery["params"][key] = {"declared": STUB_TRUTH[key], "fitted": None,
                                           "recovered": None,
                                           "why": "axis not identified in this sweep"}
                continue
            got = fit["params"][key]
            ci = fit.get("params_ci95", {}).get(key)
            inside = (ci is not None and ci["lo95"] <= STUB_TRUTH[key] <= ci["hi95"])
            recovery["params"][key] = {
                "declared": STUB_TRUTH[key], "fitted": got,
                "abs_error": abs(got - STUB_TRUTH[key]),
                "ci95": ci, "recovered": None if ci is None else bool(inside),
            }
        vals = [v["recovered"] for v in recovery["params"].values()]
        recovery["all_recovered"] = bool(all(v is True for v in vals)) if vals else False
        recovery["interpretation"] = (
            "stub gains are simulator constants; recovery validates the FITTER, "
            "it is NOT evidence about any language model")

    iso_curve = {}
    for label in [b[4] for b in BUDGET_LEVELS]:
        rs = [r for r in records if r["arm"] == "iso" and r["level"] == label]
        if rs:
            succ = [1.0 if x["success"] else 0.0 for x in rs]
            iso_curve[label] = {"n": len(rs), "success": sum(succ) / len(rs),
                                "max_steps": _budget_of(label)["max_steps"]}

    doc = {
        "experiment": "H4_real_llm_agent_axis_gains",
        "hypothesis": "H4 (HYPOTHESES.md): measure g_x under a real LLM policy",
        "seed": SEED,
        "generated_by": "experiments/h4_real_llm_gx.py",
        "backend": backend.name,
        "is_real_llm": bool(backend.is_real_llm),
        "dry_run": args.backend == "stub",
        "model_path": args.model,
        "model_fingerprint": mdl_fp,
        "script_sha256": script_sha256(),
        "lock_mode": lock_mode,
        "gpu_lock_path": args.gpu_lock,
        "min_free_mib": args.min_free_mib,
        "gpu_memory_utilization_detail": util_detail,
        "chat_mode_requested": args.chat_mode,
        "chat_mode_effective": getattr(backend, "chat_mode_effective", "n/a"),
        "gpu_state_at_load": {"total_mib": gpu_memory_mib()[0], "free_mib": gpu_memory_mib()[1]},
        "environment": {
            "python": sys.version.split()[0],
            "vllm": _pkg_version("vllm"),
            "torch": _pkg_version("torch"),
            "gpu": gpu_description(),
        },
        "iso_with_e3": {
            "source": "experiments/e3_agent_loop.py (imported at run time)",
            "tasks": [t["id"] for t in TASKS],
            "budget_levels": [{"label": b[4], "max_steps": b[0], "max_tool_calls": b[1],
                               "max_context_chars": b[2], "max_vision_probes": b[3]}
                              for b in BUDGET_LEVELS],
            "schedules_as_menus": MENUS,
            "grader": "e3_agent_loop.run_hidden_tests (identical call)",
        },
        "axis_arms": {"sweeps": {k: {"field": v[0], "values": v[1]} for k, v in AXIS_SWEEPS.items()},
                      "permissive_other_axes": PERMISSIVE,
                      "why": ("the iso budgets move together and cannot separate the gains; "
                              "the axis arms vary one axis with the others non-binding")},
        "declared_limits": [
            "g_reason is not swept; it is absorbed into the fitted p0",
            "g_search is not exercised by this task set and is left UNMEASURED, not fitted",
            "ref_x are E2 assumptions carried over, not measured here (see ref_sensitivity)",
            "task SPEC is derived from the hidden suite; the assertions stay hidden",
            "clients receive only the hidden-suite exit code, never a traceback",
            "temperature 0 with a per-request seed; GPU sampling determinism is not exact",
            "the fitted gain model is MONOTONE (p can only increase in every axis); a "
            "measured curve that decreases with budget is outside its range, so the fit "
            "is descriptive only where the data are monotone",
            "the three axis gains are reported with bootstrap CIs; where a CI is too "
            "wide to pin the parameter the point estimate is WITHHELD (see "
            "identifiability.max_ci_width) and must not be quoted",
        ] + (["STUB BACKEND: this file is a CPU dry run and is NOT a measurement of any model"]
             if args.backend == "stub" else []),
        "timing": {
            "wall_clock_s_total": round(time.perf_counter() - t_run0, 3),
            "wall_clock_s_episodes": round(sum(r["elapsed_ms"] for r in records) / 1000.0, 3),
            "generation_ms_total": round(sum(r["generation_ms"] for r in records), 3),
            "episodes": len(records),
            "mean_episode_ms": round(sum(r["elapsed_ms"] for r in records) / len(records), 3) if records else None,
            "episodes_per_minute": round(len(records) / max(1e-9, (time.perf_counter() - t_run0) / 60.0), 3),
            "note": ("wall-clock is measured per episode (time.perf_counter) and summed; "
                     "it is NEVER reconstructed as mean x count"),
        },
        "n_records": len(records),
        "repeats": args.repeats,
        "summary_by_cell": summary,
        "iso_success_curve": iso_curve,
        "gain_fit": fit,
        "floor_cells_excluded_from_fit": [
            {"arm": c["arm"], "budget": c["budget"], "success": c["success"],
             "why": "no policy can be graded here: grading needs >=1 tool call and "
                    "the write-before-test order needs >=2 steps"}
            for c in floor_cells],
        "stub_gain_recovery": recovery,
        "ref_sensitivity": sens,
        "records": records,
    }

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    print("backend=%s is_real_llm=%s records=%d" % (backend.name, backend.is_real_llm, len(records)))
    print("iso curve:", json.dumps(iso_curve))
    if fit.get("fitted"):
        print("fit params:", json.dumps(fit["params"]))
        print("unidentified axes:", fit["unidentified_axes"])
    else:
        print("fit:", json.dumps(fit))
    print("wrote", args.out)
    return 0


class _NullCtx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _counts(it):
    d = {}
    for x in it:
        d[x] = d.get(x, 0) + 1
    return d


if __name__ == "__main__":
    sys.exit(main())
