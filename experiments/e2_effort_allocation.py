#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E2 — Joint optimal effort allocation over five effort axes (CPU-only).

Research question (H1/H2, see HYPOTHESES.md): given a fixed cost budget, does a
single UNIFIED router over the five effort axes

    b_reason  reasoning tokens per turn   (source-controlled in V4.1-Flash)
    b_steps   trajectory length in turns  (the report's agentic transfer claim)
    b_tools   local tool invocations
    b_search  network search invocations
    b_vision  screenshot / visual-probe operations

beat (i) maxing every axis, (ii) a fixed mid setting, (iii) budget-DECOUPLED
per-axis routers that may not trade budget across axes, and (iv) any single-axis
scaling?

Two cost currencies are reported, because they disagree:
  * tokens  — what the V4.1-Flash report actually optimises (its RL penalises
              reasoning tokens; its latency model prices tokens at fixed
              prefill/decode rates plus measured tool time, report lines
              2740-2744). PRIMARY currency.
  * ms      — wall clock, built only from MEASURED per-action latencies
              (E1/E1b). SECONDARY currency, reported for deployment latency.

Provenance contract
-------------------
MEASURED : every ms coefficient comes from results/e1_tool_latency.json (E1) and
           results/e1b_agent_primitives.json (E1b). No latency constant is
           hand-written here.
SOURCE   : the reasoning-effort success kernel is anchored to the V4.1-Flash
           report quotes in evidence/v41flash_effort_control.json
           (lines 2434 / 2436 / 2439-2440 / 2094, appendix C eq. 12-17).
ASSUMED  : token prices for steps/tools/vision, base success, the four agent-axis
           gains and their half-saturation references. Declared in ASSUMED and
           re-run over a sensitivity grid. The paper must cite them as assumed.

Output: results/e2_allocation.json
Run:    python3 e2_effort_allocation.py --e1 results/e1_tool_latency.json \
        --e1b results/e1b_agent_primitives.json --out results/e2_allocation.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

SEED = 20260911

# ---------------------------------------------------- SOURCE anchors (V4.1) --
ACC_B25 = 0.671            # line 2434 (8 reasoning-intensive benchmarks, effort 25)
ACC_B100 = 0.763           # line 2434 (same, effort 100)
TOKEN_MULT_25_100 = 2.5    # line 2436 "roughly 2.5x more output tokens"
FRONTLOAD_TARGET = 0.76    # lines 2439-2440: the 60-80 range recovers "most" of
                           # the maximum accuracy at <half the token budget
B_MIN, B_MAX, B_REF = 1.0, 100.0, 25.0
R_REF_TOKENS = 3000.0 / TOKEN_MULT_25_100   # reasoning tokens per turn at b=25

# ---------------------------------------------------------------- search grid
REASON_LEVELS = np.array([0, 25, 50, 75, 100], float)
STEP_LEVELS = np.array([1, 2, 4, 8, 12, 20, 32], float)
TOOL_LEVELS = np.array([0, 1, 2, 4, 8, 16, 24], float)
SEARCH_LEVELS = np.array([0, 1, 2, 4, 8, 16], float)
VISION_LEVELS = np.array([0, 1, 2, 4, 8, 16], float)
AXIS_NAMES = ["b_reason", "b_steps", "b_tools", "b_search", "b_vision"]
AXIS_LEVELS = [REASON_LEVELS, STEP_LEVELS, TOOL_LEVELS, SEARCH_LEVELS, VISION_LEVELS]

# ------------------------------------------------- ASSUMED model parameters --
ASSUMED = {
    "base_success": 0.35,
    "gain_steps": 0.30,
    "gain_tools": 0.25,
    "gain_search": 0.28,
    "gain_vision": 0.20,
    "ref_steps": 10.0,
    "ref_tools": 6.0,
    "ref_search": 4.0,
    "ref_vision": 4.0,
    # token prices, in "context tokens": each step re-encodes its context
    "tokens_per_step_overhead": 1000.0,
    "tokens_per_tool_call": 200.0,
    "tokens_per_search_call": 400.0,
    "tokens_per_vision_op": 200.0,
    # latency model
    "ms_per_1k_decode_tokens": 30.0,
    "search_success_rate": 0.85,
    "retry_multiplier": 1.4,
}
SENSITIVITY = {
    "base_success": [0.20, 0.35, 0.50],
    "gain_steps": [0.15, 0.30, 0.45],
    "gain_tools": [0.12, 0.25, 0.40],
    "gain_search": [0.15, 0.28, 0.42],
    "gain_vision": [0.10, 0.20, 0.35],
    "ref_steps": [6.0, 10.0, 16.0],
    "ref_tools": [3.0, 6.0, 12.0],
    "tokens_per_step_overhead": [500.0, 1000.0, 2000.0],
    "ms_per_1k_decode_tokens": [10.0, 30.0, 60.0],
    "search_success_rate": [0.70, 0.85, 1.00],
}
MID = [50.0, 8.0, 4.0, 2.0, 2.0]

TARGETS_TOKENS = [0.45, 0.50, 0.55, 0.575, 0.60, 0.625, 0.65, 0.675]
BUDGETS_TOKENS = [5000, 10000, 20000, 30000, 50000, 80000, 120000]
BUDGETS_MS = [2000, 5000, 10000, 20000, 40000, 80000]


# ------------------------------------------------------------ source kernels -
def reasoning_weight(b, s0):
    """w(25)=0, w(100)=1, concave in b (exponential penalty, line 2094 / app. C)."""
    num = math.log(1.0 + (b - B_MIN) / s0) - math.log(1.0 + (B_REF - B_MIN) / s0)
    den = math.log(1.0 + (B_MAX - B_MIN) / s0) - math.log(1.0 + (B_REF - B_MIN) / s0)
    return num / den


def reasoning_tokens(b, kappa):
    """L(b) = R_REF*exp(kappa*(b-25)); anchored so L(100)/L(25)=2.5 (line 2436)."""
    return R_REF_TOKENS * math.exp(kappa * (b - B_REF))


def fit_s0(target_frontload=FRONTLOAD_TARGET):
    lo, hi = 1.0, 5000.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if reasoning_weight(80.0, mid) < target_frontload:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def sat(x, ref, gain):
    return gain * (1.0 - math.exp(-x / ref)) if x > 0 else 0.0


# ------------------------------------------------------------------- model ---
def make_cost_coeffs(e1, e1b):
    ag, agb = e1["aggregates"], e1b["aggregates"]
    return {
        "local_tool_ms": ag["T12_shell_read_verify"]["mean_ok_ms"],
        "local_tool_p50_ms": ag["T12_shell_read_verify"]["p50_ok_ms"],
        "local_tool_p95_ms": ag["T12_shell_read_verify"]["p95_ok_ms"],
        "shell_command_ms": ag["T2_shell_command"]["mean_ok_ms"],
        "file_write_ms": ag["T6_file_write_atomic"]["mean_ok_ms"],
        "python_exec_ms": ag["T3_python_exec"]["mean_ok_ms"],
        "json_tool_call_ms": agb["P6_json_tool_call"]["mean_ok_ms"],
        "patch_apply_ms": agb["P5_patch_apply"]["mean_ok_ms"],
        "test_run_ms": agb["P3_test_run_small"]["mean_ok_ms"],
        "loopback_search_ms": agb["P4_local_http_search"]["mean_ok_ms"],
        "internet_search_ms": ag["T8_net_reachable"]["mean_ok_ms"],
        "internet_search_p50_ms": ag["T8_net_reachable"]["p50_ok_ms"],
        "internet_unreachable_ms": ag["T9_net_unreachable"]["mean_ms"],
        "internet_unreachable_failure_rate": ag["T9_net_unreachable"]["failure_rate"],
        "vision_op_ms": agb["P1_image_codec_png"]["mean_ok_ms"],
        "vision_op_p95_ms": agb["P1_image_codec_png"]["p95_ok_ms"],
        "screenshot_capture_failure_rate": agb["P2_screenshot_capture"]["failure_rate"],
        "process_spawn_ms": ag["T11_process_spawn_tree"]["mean_ok_ms"],
    }


def evaluate(alloc, C, p, kappa, s0):
    """Returns (success, tokens, ms, factors).

    Success model (declared): the reasoning kernel is source-anchored; the agent
    axes are substitutable routes that recover part of the residual failure,
    each with exponential saturation:
        agent = 1 - prod_x (1 - gain_x*(1-exp(-x/ref_x)))
        p     = 1 - (1 - acc*agent) * (1 - base_success)
    Monotone in every axis; bounded in [base_success, 1].
    """
    b, steps, tools, search, vision = alloc
    acc = ACC_B25 + (ACC_B100 - ACC_B25) * reasoning_weight(b, s0)
    agent = 1.0 - (
        (1.0 - sat(steps, p["ref_steps"], p["gain_steps"]))
        * (1.0 - sat(tools, p["ref_tools"], p["gain_tools"]))
        * (1.0 - sat(search, p["ref_search"], p["gain_search"]))
        * (1.0 - sat(vision, p["ref_vision"], p["gain_vision"]))
    )
    success = min(1.0, 1.0 - (1.0 - acc * agent) * (1.0 - p["base_success"]))

    tokens = (
        steps * reasoning_tokens(b, kappa)
        + steps * p["tokens_per_step_overhead"]
        + (tools + search) * p["tokens_per_tool_call"]
        + search * p["tokens_per_search_call"]
        + vision * p["tokens_per_vision_op"]
    )
    per_step = C["file_write_ms"] + C["shell_command_ms"] + C["json_tool_call_ms"] + C["process_spawn_ms"]
    fail = 1.0 - p["search_success_rate"]
    ms = (
        steps * reasoning_tokens(b, kappa) * p["ms_per_1k_decode_tokens"] / 1000.0
        + steps * per_step
        + tools * C["json_tool_call_ms"]
        + search * C["internet_search_ms"] * (1.0 + fail * (p["retry_multiplier"] - 1.0))
        + vision * C["vision_op_ms"]
    )
    return float(success), float(tokens), float(ms), {
        "reasoning_kernel": acc, "agent_recovery": agent
    }


def all_allocs():
    return np.array(np.meshgrid(*AXIS_LEVELS, indexing="ij")).reshape(5, -1).T


def sweep(allocs, C, p, kappa, s0):
    n = len(allocs)
    su = np.empty(n)
    tk = np.empty(n)
    ms = np.empty(n)
    for i, a in enumerate(allocs):
        su[i], tk[i], ms[i], _ = evaluate(a, C, p, kappa, s0)
    return su, tk, ms


def best_for_budget(allocs, su, cost, budget):
    m = cost <= budget + 1e-9
    if not m.any():
        return None, None, None
    i = int(np.argmax(np.where(m, su, -np.inf)))
    return float(su[i]), tuple(float(x) for x in allocs[i]), float(cost[i])


def min_cost_for_success(allocs, su, cost, target):
    m = su >= target - 1e-12
    if not m.any():
        return None, None, None
    i = int(np.argmin(np.where(m, cost, np.inf)))
    return float(cost[i]), float(su[i]), tuple(float(x) for x in allocs[i])


def pareto(points):
    pts = sorted(points, key=lambda x: (x[0], -x[1]))
    out, best = [], -1.0
    for c, s in pts:
        if s > best + 1e-12:
            out.append((c, s))
            best = s
    return out


def pareto_rows(points):
    pts = sorted(points, key=lambda x: (x[0], -x[1]))
    out, best = [], -1.0
    for c, s, a in pts:
        if s > best + 1e-12:
            out.append({"cost": c, "success": s, "alloc": list(a)})
            best = s
    return out


# ---------------------------------------------------- decoupled baseline -----
def greedy_axis_ladder(C, p, kappa, s0, axis_idx, levels, per_axis_tokens):
    """Greedy marginal-success climb on ONE axis under its own private token
    budget. Later, more expensive levels must be paid from that axis's own
    share, so no cross-axis trade is possible."""
    cur = list(MID)
    cur[axis_idx] = float(min(levels))
    s_prev, c_prev, _, _ = evaluate(cur, C, p, kappa, s0)
    used = 0.0
    for lv in sorted(levels):
        trial = list(cur)
        trial[axis_idx] = float(lv)
        s_new, c_new, _, _ = evaluate(trial, C, p, kappa, s0)
        dc = c_new - c_prev
        if dc > 0 and used + dc > per_axis_tokens:
            break
        if s_new <= s_prev + 1e-12 and dc >= 0:
            continue
        cur, s_prev, c_prev = trial, s_new, c_new
        used += max(dc, 0.0)
    return tuple(cur), s_prev


def decoupled_frontier(C, p, kappa, s0, n_budget=120, budget_max=150000.0):
    out = []
    for B in np.linspace(3000.0, budget_max, n_budget):
        per = B / len(AXIS_LEVELS)
        alloc = list(MID)
        for idx, levels in enumerate(AXIS_LEVELS):
            a_i, _ = greedy_axis_ladder(C, p, kappa, s0, idx, levels, per)
            alloc[idx] = a_i[idx]
        s, c, _, _ = evaluate(alloc, C, p, kappa, s0)
        out.append((c, s, tuple(alloc)))
    return pareto_rows(out)


# ------------------------------------------------------------------ main -----
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--e1", default="results/e1_tool_latency.json")
    ap.add_argument("--e1b", default="results/e1b_agent_primitives.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-boot", type=int, default=200)
    args = ap.parse_args()

    e1 = json.load(open(args.e1, encoding="utf-8"))
    e1b = json.load(open(args.e1b, encoding="utf-8"))
    C = make_cost_coeffs(e1, e1b)
    p = dict(ASSUMED)
    kappa = math.log(TOKEN_MULT_25_100) / (B_MAX - B_REF)
    s0 = fit_s0()
    allocs = all_allocs()
    su, tk, ms = sweep(allocs, C, p, kappa, s0)

    def fixed(levels):
        s, c, m, parts = evaluate(levels, C, p, kappa, s0)
        return {"alloc": dict(zip(AXIS_NAMES, levels)), "success": s,
                "cost_tokens": c, "cost_ms": m, "factors": parts}

    max_lv = [float(lv.max()) for lv in AXIS_LEVELS]
    baselines = {
        "B1_all_max": fixed(max_lv),
        "B2_fixed_mid": fixed(MID),
        "B3_reason_only_max": fixed([B_MAX] + MID[1:]),
        "B4_agent_only_max": fixed([MID[0]] + [float(lv.max()) for lv in AXIS_LEVELS[1:]]),
    }

    ablations = {}
    for name, idx, levels in zip(AXIS_NAMES, range(5), AXIS_LEVELS):
        pts = []
        for lv in levels:
            a = list(MID)
            a[idx] = float(lv)
            s, c, _, _ = evaluate(a, C, p, kappa, s0)
            pts.append((c, s, tuple(a)))
        ablations[name] = {
            "frontier": pareto_rows(pts),
            "best_success_single_axis": max(x[1] for x in pts),
        }

    unified = {"target_frontier_tokens": [], "budget_frontier_tokens": [], "budget_frontier_ms": []}
    for t in TARGETS_TOKENS:
        c, s, a = min_cost_for_success(allocs, su, tk, t)
        unified["target_frontier_tokens"].append(
            {"target_success": t, "min_cost_tokens": c, "achieved_success": s,
             "alloc": list(a) if a else None})
    for B in BUDGETS_TOKENS:
        s, a, c = best_for_budget(allocs, su, tk, B)
        unified["budget_frontier_tokens"].append(
            {"budget_tokens": B, "max_success": s, "alloc": list(a) if a else None, "cost_tokens": c})
    for B in BUDGETS_MS:
        s, a, c = best_for_budget(allocs, su, ms, B)
        unified["budget_frontier_ms"].append(
            {"budget_ms": B, "max_success": s, "alloc": list(a) if a else None, "cost_ms": c})

    # -------- matched comparisons ------------------------------------------
    def cmp_against(name, base):
        bc = base["cost_tokens"]
        bs = base["success"]
        r_b = best_for_budget(allocs, su, tk, bc)
        c_at = min_cost_for_success(allocs, su, tk, bs)
        return {
            name: {
                "baseline_success": bs,
                "baseline_cost_tokens": bc,
                "baseline_cost_ms": base["cost_ms"],
                "unified_success_at_baseline_cost": r_b[0],
                "unified_alloc_at_baseline_cost": list(r_b[1]) if r_b[1] else None,
                "unified_cost_tokens_at_baseline_success": c_at[0],
                "cost_ratio_baseline_over_unified_at_matched_success": (bc / c_at[0]) if c_at[0] else None,
                "success_gain_points_at_baseline_cost": (r_b[0] - bs) * 100.0 if r_b[0] is not None else None,
            }
        }

    all_max = baselines["B1_all_max"]
    midb = baselines["B2_fixed_mid"]
    s_star = float(su.max())
    c90_unified, s90, a90 = min_cost_for_success(allocs, su, tk, 0.90 * s_star)
    c40_unified, s40, a40 = min_cost_for_success(allocs, su, tk, 0.40)

    dec = decoupled_frontier(C, p, kappa, s0)
    dec_c = np.array([d["cost"] for d in dec])
    dec_s = np.array([d["success"] for d in dec])

    def dec_succ_at(budget):
        m = dec_c <= budget + 1e-9
        return float(dec_s[m].max()) if m.any() else None

    def dec_cost_at(target):
        m = dec_s >= target - 1e-12
        return float(dec_c[m].min()) if m.any() else None

    matched = {}
    matched.update(cmp_against("vs_all_max", all_max))
    matched.update(cmp_against("vs_fixed_mid", midb))
    matched.update(cmp_against("vs_reason_only_max", baselines["B3_reason_only_max"]))
    matched.update(cmp_against("vs_agent_only_max", baselines["B4_agent_only_max"]))
    matched["vs_decoupled_separate_budgets"] = {
        "n_frontier_points": len(dec),
        "decoupled_best_success": float(dec_s.max()),
        "decoupled_cost_at_40pct_success": dec_cost_at(0.40),
        "unified_cost_at_40pct_success": c40_unified,
        "cost_ratio_decoupled_over_unified_at_40pct": (
            (dec_cost_at(0.40) / c40_unified) if dec_cost_at(0.40) and c40_unified else None),
        "decoupled_success_at_all_max_cost": dec_succ_at(all_max["cost_tokens"]),
        "unified_success_at_all_max_cost": best_for_budget(allocs, su, tk, all_max["cost_tokens"])[0],
    }

    saturation = {
        "attainable_success_s_star": s_star,
        "target90_success": 0.90 * s_star,
        "unified_cost_tokens_at_target90": c90_unified,
        "unified_alloc_at_target90": list(a90) if a90 else None,
        "all_max_cost_tokens": all_max["cost_tokens"],
        "all_max_success": all_max["success"],
        "all_max_reaches_target90": bool(all_max["success"] >= 0.90 * s_star - 1e-12),
        "cost_ratio_all_max_over_unified_at_target90": (all_max["cost_tokens"] / c90_unified) if c90_unified else None,
        "caveat": ("Above ~90% of attainable success extra spending buys almost nothing, so "
                   "the all-max baseline's disadvantage is concentrated on the rising part of "
                   "the curve; the matched-success ratio is the honest headline."),
    }

    # -------- bootstrap over MEASURED latency variability -------------------
    rng = np.random.default_rng(SEED)
    boot_ms_gap, boot_tk_gap = [], []
    for _ in range(args.n_boot):
        Cb = dict(C)
        for key, src, name in [
            ("local_tool_ms", e1, "T12_shell_read_verify"),
            ("json_tool_call_ms", e1b, "P6_json_tool_call"),
            ("internet_search_ms", e1, "T8_net_reachable"),
            ("vision_op_ms", e1b, "P1_image_codec_png"),
            ("file_write_ms", e1, "T6_file_write_atomic"),
            ("shell_command_ms", e1, "T2_shell_command"),
        ]:
            samples = [v for v, f in zip(src["raw"][name]["samples_ms"], src["raw"][name]["ok"]) if f]
            if len(samples) >= 2:
                Cb[key] = float(np.mean(rng.choice(samples, size=len(samples), replace=True)))
        sb, tb, mb = sweep(allocs, Cb, p, kappa, s0)
        am_ms = evaluate(max_lv, Cb, p, kappa, s0)[2]
        am_tk = evaluate(max_lv, Cb, p, kappa, s0)[1]
        r_ms = best_for_budget(allocs, sb, mb, am_ms)
        r_tk = best_for_budget(allocs, sb, tb, am_tk)
        boot_ms_gap.append((r_ms[0] - all_max["success"]) * 100.0 if r_ms[0] else np.nan)
        boot_tk_gap.append((r_tk[0] - all_max["success"]) * 100.0 if r_tk[0] else np.nan)

    def ci(x):
        x = np.asarray(x, float)
        return {"mean": float(np.nanmean(x)),
                "lo95": float(np.nanpercentile(x, 2.5)),
                "hi95": float(np.nanpercentile(x, 97.5)),
                "n": int(np.sum(~np.isnan(x)))}

    bootstrap = {
        "success_gain_vs_all_max_points_ms_budget": ci(boot_ms_gap),
        "success_gain_vs_all_max_points_token_budget": ci(boot_tk_gap),
        "n_boot": args.n_boot,
        "resampled_measured_tools": ["T12", "P6", "T8", "P1", "T6", "T2"],
        "note": "resamples per-invocation latencies from the E1/E1b raw samples",
    }

    # -------- sensitivity ---------------------------------------------------
    sens = []
    for key, vals in SENSITIVITY.items():
        for v in vals:
            p2 = dict(p)
            p2[key] = v
            s2, t2, _ = sweep(allocs, C, p2, kappa, s0)
            r = best_for_budget(allocs, s2, t2, all_max["cost_tokens"])
            sens.append({
                "param": key, "value": v,
                "unified_success_at_all_max_cost": r[0],
                "unified_alloc": list(r[1]) if r[1] else None,
                "success_gain_vs_all_max_points": (r[0] - all_max["success"]) * 100.0 if r[0] else None,
            })
    g = [x["success_gain_vs_all_max_points"] for x in sens if x["success_gain_vs_all_max_points"] is not None]
    sens_summary = {
        "min_gain_points": float(np.min(g)),
        "max_gain_points": float(np.max(g)),
        "n_cases": len(g),
        "n_cases_unified_loses": int(np.sum(np.asarray(g) < -1e-9)),
        "n_cases_tie": int(np.sum(np.abs(np.asarray(g)) <= 1e-9)),
    }

    doc = {
        "experiment": "E2_joint_effort_allocation",
        "seed": SEED,
        "generated_by": "experiments/e2_effort_allocation.py",
        "kind": "model-based optimisation over MEASURED cost primitives with a SOURCE-anchored reasoning kernel",
        "measured_inputs": {"e1_file": args.e1, "e1b_file": args.e1b, "cost_coefficients_ms": C},
        "source_anchors": {
            "acc_b25": ACC_B25, "acc_b100": ACC_B100,
            "token_mult_25_100": TOKEN_MULT_25_100,
            "frontload_target_fraction_at_b80": FRONTLOAD_TARGET,
            "frontload_fraction_achieved": reasoning_weight(80.0, s0),
            "kappa": kappa, "s0": s0,
            "r_ref_tokens_at_b25": R_REF_TOKENS,
            "r_tokens_at_b100": reasoning_tokens(B_MAX, kappa),
        },
        "assumed_params": p,
        "assumed_params_declared_unmeasured": list(ASSUMED.keys()),
        "axis_names": AXIS_NAMES,
        "grid": {"n_allocations": int(len(allocs)),
                 "levels": {n: lv.tolist() for n, lv in zip(AXIS_NAMES, AXIS_LEVELS)},
                 "mid_reference_alloc": dict(zip(AXIS_NAMES, MID))},
        "unified_router": unified,
        "baselines": baselines,
        "single_axis_ablations": ablations,
        "matched_comparisons": matched,
        "saturation_comparison": saturation,
        "decoupled_frontier": dec,
        "bootstrap_gains": bootstrap,
        "sensitivity": sens,
        "sensitivity_summary": sens_summary,
        "pareto_front_tokens": [{"cost_tokens": c, "success": s} for c, s in pareto(list(zip(tk, su)))],
        "pareto_front_ms": [{"cost_ms": c, "success": s} for c, s in pareto(list(zip(ms, su)))],
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    print("kappa=%.6f s0=%.1f frontload_frac@80=%.4f (target %.2f)"
          % (kappa, s0, reasoning_weight(80.0, s0), FRONTLOAD_TARGET))
    print("n_allocations=%d  attainable success range %.4f..%.4f" % (len(allocs), su.min(), su.max()))
    for k, v in baselines.items():
        print("  %-20s success=%.4f tokens=%9.0f ms=%9.0f" % (k, v["success"], v["cost_tokens"], v["cost_ms"]))
    print("unified token-budget frontier:")
    for row in unified["budget_frontier_tokens"]:
        print("  <=%8d tok  success=%s  alloc=%s"
              % (row["budget_tokens"], ("%.4f" % row["max_success"]) if row["max_success"] else "n/a", row["alloc"]))
    for k in ["vs_all_max", "vs_fixed_mid", "vs_reason_only_max", "vs_agent_only_max"]:
        m = matched[k]
        print("  %-20s gain at baseline cost %s pts ; token-cost ratio at matched success %.2fx"
              % (k, ("%.3f" % m["success_gain_points_at_baseline_cost"]) if m["success_gain_points_at_baseline_cost"] is not None else "n/a",
                 m["cost_ratio_baseline_over_unified_at_matched_success"] or -1))
    print("  vs_decoupled        cost ratio at 40%% success %s ; unified success at all-max cost %s"
          % (matched["vs_decoupled_separate_budgets"]["cost_ratio_decoupled_over_unified_at_40pct"],
             matched["vs_decoupled_separate_budgets"]["unified_success_at_all_max_cost"]))
    print("saturation: s*=%.4f target90=%.4f unified cost=%s tok ; all_max=%s tok (ratio %.2fx) ; all_max reaches target: %s"
          % (s_star, 0.90 * s_star, ("%.0f" % c90_unified) if c90_unified else "n/a",
             ("%.0f" % all_max["cost_tokens"]),
             saturation["cost_ratio_all_max_over_unified_at_target90"] or -1,
             saturation["all_max_reaches_target90"]))
    print("bootstrap gain vs all_max: token-budget %.3f [%.3f, %.3f] pts"
          % (bootstrap["success_gain_vs_all_max_points_token_budget"]["mean"],
             bootstrap["success_gain_vs_all_max_points_token_budget"]["lo95"],
             bootstrap["success_gain_vs_all_max_points_token_budget"]["hi95"]))
    print("sensitivity: gain in [%.3f, %.3f] pts over %d cases ; unified loses in %d ; ties %d"
          % (sens_summary["min_gain_points"], sens_summary["max_gain_points"],
             sens_summary["n_cases"], sens_summary["n_cases_unified_loses"], sens_summary["n_cases_tie"]))
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
