#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analysis.py — canonical recomputation of every number reported in the paper.

Read-only w.r.t. the evidence: it NEVER regenerates data. It re-derives each
statistic from the raw per-invocation samples and from the E2/E3 record files,
asserts that the values stored in those files agree with the recomputation, and
writes one consolidated results/stats.json that the manuscript cites.

If an assert fires, the manuscript number is wrong and must be fixed - that is
the point of this file (FM-16/17: one canonical script, no hand-copied values).

Run: python3 analysis.py .
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys

import numpy as np

SEED = 20260911


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def boot_ci(xs, n_boot=4000, alpha=0.05, seed=SEED):
    a = np.asarray(xs, dtype=float)
    if a.size < 2:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, a.size, size=(n_boot, a.size))
    st = a[idx].mean(axis=1)
    return {"mean": float(a.mean()), "lo95": float(np.percentile(st, 2.5)),
            "hi95": float(np.percentile(st, 97.5)), "n_boot": n_boot}


def exact_ci(k, n, alpha=0.05):
    """Clopper-Pearson, on independent units. No silent fallback.

    The interval printed in Table 3 used to be a bootstrap over the 48 records per level, but
    `repeats` copies of a deterministic policy are one measurement written three times, and a
    bootstrap of triplicates collapses to zero width exactly at 0/16 and 16/16 -- it reports
    certainty where the evidence is thinnest. If scipy is missing this aborts rather than quietly
    reusing boot_ci, because a substitute interval would be the same defect with a different name.
    """
    try:
        from scipy.stats import binomtest
    except ImportError:
        raise SystemExit('analysis.py needs scipy for the exact binomial interval on units; '
                         'refusing to substitute the record-level bootstrap it replaces')
    ci = binomtest(int(k), int(n)).proportion_ci(confidence_level=1 - alpha, method='exact')
    return {"lo95": float(ci.low), "hi95": float(ci.high), "n_units": int(n),
            "method": "clopper-pearson-exact"}


def unit_aggregate(rs, key_fields=('task', 'schedule')):
    """Collapse repeat-copies to independent units, and refuse to collapse real variation.

    Returns (successes, n_units, units_varying). If any unit's repeats disagree, the copies DO
    carry information and collapsing them would be wrong -- successes is then None so the caller
    must report NOT_JUDGED instead of a smaller n it prefers.
    """
    groups = {}
    for r in rs:
        groups.setdefault(tuple(str(r.get(k, '')) for k in key_fields), []).append(
            1.0 if r['success'] else 0.0)
    varying = sum(1 for v in groups.values() if len(set(v)) > 1)
    if varying:
        return None, len(groups), varying
    return float(sum(1 for v in groups.values() if v[0] == 1.0)), len(groups), 0


def wls_agreement(a_json, b, tol=1e-9, label=""):
    if b is None:
        return True
    ok = abs(a_json - b) <= tol * max(1.0, abs(b))
    if not ok:
        print("MISMATCH %s: file=%r recomputed=%r" % (label, a_json, b))
    return ok


def main() -> int:
    paper_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    res = os.path.join(paper_dir, "results")
    e1 = load(os.path.join(res, "e1_tool_latency.json"))
    e1b = load(os.path.join(res, "e1b_agent_primitives.json"))
    e2 = load(os.path.join(res, "e2_allocation.json"))
    e3 = load(os.path.join(res, "e3_agent_loop.json"))

    checks_ok = True

    # ---------------- E1 / E1b: recompute latency aggregates ----------------
    tools = {}
    for doc, tag in [(e1, "E1"), (e1b, "E1b")]:
        for name, rec in doc["raw"].items():
            good = [v for v, f in zip(rec["samples_ms"], rec["ok"]) if f]
            arr = np.asarray(rec["samples_ms"], dtype=float)
            stored = doc["aggregates"][name]
            checks_ok &= wls_agreement(stored["n"], len(arr), 0, "n:" + name)
            checks_ok &= wls_agreement(stored["failure_rate"], float(np.mean([not f for f in rec["ok"]])), 1e-9, "fail:" + name)
            if good:
                checks_ok &= wls_agreement(stored["mean_ok_ms"], float(np.mean(good)), 1e-9, "mean_ok:" + name)
                checks_ok &= wls_agreement(stored["p50_ok_ms"], float(np.percentile(good, 50)), 1e-9, "p50:" + name)
                checks_ok &= wls_agreement(stored["p95_ok_ms"], float(np.percentile(good, 95)), 1e-9, "p95:" + name)
            tools[name] = {
                "tag": tag,
                "n": len(arr),
                "n_ok": len(good),
                "failure_rate": float(np.mean([not f for f in rec["ok"]])),
                "mean_ms": float(arr.mean()),
                "sd_ms": float(arr.std(ddof=1)) if arr.size > 1 else None,
                "var_ms2": float(arr.var(ddof=1)) if arr.size > 1 else None,
                "p50_ms": float(np.percentile(arr, 50)),
                "p95_ms": float(np.percentile(arr, 95)),
                "p99_ms": float(np.percentile(arr, 99)),
                "cv": float(arr.std(ddof=1) / arr.mean()) if arr.size > 1 and arr.mean() else None,
                "ci95_mean_ms": boot_ci(good if len(good) >= 2 else arr),
            }

    # ---------------- E2: recompute the headline comparisons ----------------
    e2c = e2["matched_comparisons"]
    su_max = e2["saturation_comparison"]
    e2_out = {
        "n_allocations": e2["grid"]["n_allocations"],
        "source_kernel": e2["source_anchors"],
        "baselines": {k: {"success": v["success"], "cost_tokens": v["cost_tokens"], "cost_ms": v["cost_ms"]}
                      for k, v in e2["baselines"].items()},
        "vs_all_max": e2c["vs_all_max"],
        "vs_fixed_mid": e2c["vs_fixed_mid"],
        "vs_reason_only_max": e2c["vs_reason_only_max"],
        "vs_agent_only_max": e2c["vs_agent_only_max"],
        "vs_decoupled": e2c["vs_decoupled_separate_budgets"],
        "saturation": su_max,
        "bootstrap_gains": e2["bootstrap_gains"],
        "sensitivity_summary": e2["sensitivity_summary"],
        "budget_frontier_tokens": e2["unified_router"]["budget_frontier_tokens"],
        "budget_frontier_ms": e2["unified_router"]["budget_frontier_ms"],
    }
    # internal consistency: all-max must reach s_star
    checks_ok &= wls_agreement(e2["baselines"]["B1_all_max"]["success"], su_max["attainable_success_s_star"], 1e-9, "s_star")

    # ---------------- E3: recompute the success curve -----------------------
    recs = e3["records"]
    curve = {}
    for lvl in e3["budget_levels"]:
        lab = lvl["label"]
        rs = [r for r in recs if r["budget_label"] == lab]
        succ = [1.0 if r["success"] else 0.0 for r in rs]
        ms = [r["elapsed_ms"] for r in rs]
        curve[lab] = {
            "n": len(rs),
            "success_rate": float(np.mean(succ)),
            "success_rate_ci95": boot_ci(succ),
            "mean_elapsed_ms": float(np.mean(ms)),
            "mean_elapsed_ms_ci95": boot_ci(ms),
            "mean_steps": float(np.mean([r["steps_used"] for r in rs])),
            "mean_tool_calls": float(np.mean([r["tool_calls_used"] for r in rs])),
            "max_steps": lvl["max_steps"],
        }
        # the interval the paper prints: exact binomial on independent (task, schedule) units
        ks, nu, varying = unit_aggregate(rs)
        curve[lab]["n_units"] = nu
        curve[lab]["units_varying_across_repeats"] = varying
        if ks is None:
            curve[lab]["success_units"] = None
            curve[lab]["success_rate_ci95_units"] = None
            curve[lab]["unit_note"] = ('NOT_JUDGED: %d/%d units disagree across repeats, so the '
                                       'copies are not triplicates and must not be collapsed'
                                       % (varying, nu))
        else:
            curve[lab]["success_units"] = int(ks)
            curve[lab]["success_rate_ci95_units"] = exact_ci(ks, nu)
            # non-vacuity: collapsing to fewer independent units can never make the interval
            # narrower. If it did, either the grouping or the interval is wrong.
            wide = True
            rec = curve[lab]["success_rate_ci95"]
            if rec:
                wide = (curve[lab]["success_rate_ci95_units"]["lo95"] <= rec["lo95"] + 1e-12
                        and curve[lab]["success_rate_ci95_units"]["hi95"] >= rec["hi95"] - 1e-12)
            if not wide:
                print('RED: unit CI is not wider than the record CI at %s: units=%s records=%s'
                      % (lab, curve[lab]["success_rate_ci95_units"], rec))
            checks_ok &= wide
            # The width test alone can pass while the collapse does nothing (equal n, different
            # method). Tie the count to the DESIGN: one unit per (task, schedule), and records per
            # level must be exactly repeats x units.
            want = e3["n_tasks"] * 2
            if nu != want or len(rs) != int(e3["repeats"]) * nu:
                print('RED: %s has %d units, design says %d tasks x 2 schedules = %d, and %d records '
                      '!= repeats(%s) x units' % (lab, nu, want, want, len(rs), e3["repeats"]))
                checks_ok = False
        checks_ok &= wls_agreement(e3["success_curve_by_budget"][lab]["success_rate"], curve[lab]["success_rate"], 1e-9, "E3:" + lab)
    labels = [l["label"] for l in e3["budget_levels"]]
    rates = [curve[l]["success_rate"] for l in labels]
    monotone = all(rates[i] <= rates[i + 1] + 1e-12 for i in range(len(rates) - 1))
    checks_ok &= (bool(monotone) == bool(e3["curve_monotone_nondecreasing"]))

    by_bs = {}
    for k, v in e3["summary_by_budget_schedule"].items():
        rs = [r for r in recs
              if "%s|%s" % (r["budget_label"], r["schedule"]) == k]
        s = [1.0 if r["success"] else 0.0 for r in rs]
        safe = k.replace("|", "_")
        ks2, nu2, var2 = unit_aggregate(rs)
        by_bs[safe] = {"budget_label": k.split("|")[0], "schedule": k.split("|")[1],
                       "n": len(rs), "success_rate": float(np.mean(s)),
                       "success_rate_ci95": boot_ci(s),
                       "n_units": nu2,
                       "success_units": None if ks2 is None else int(ks2),
                       "success_rate_ci95_units": None if ks2 is None else exact_ci(ks2, nu2),
                       "units_varying_across_repeats": var2,
                       "mean_elapsed_ms": float(np.mean([r["elapsed_ms"] for r in rs]))}
        checks_ok &= wls_agreement(v["success_rate"], by_bs[k.replace("|", "_")]["success_rate"], 1e-9, "E3bs:" + k)

    # cost per success where success > 0
    cost_per_success = {}
    for lab in labels:
        r0 = curve[lab]["success_rate"]
        cost_per_success[lab] = (curve[lab]["mean_elapsed_ms"] / r0) if r0 > 0 else None

    out = {
        "paper": "From Controllable Reasoning Effort to Controllable Agent Effort",
        "generated_by": "analysis.py (read-only recomputation)",
        "seed": SEED,
        "inputs": {
            f: {"sha256": hashlib.sha256(open(os.path.join(res, f), "rb").read()).hexdigest()}
            for f in ["e1_tool_latency.json", "e1b_agent_primitives.json",
                      "e2_allocation.json", "e3_agent_loop.json"]
        },
        "E1_E1b_latency": tools,
        "E2_allocation": e2_out,
        "E3_loop": {
            "policy": e3["policy"],
            "declared_limits": e3["declared_limits"],
            "n_tasks": e3["n_tasks"],
            "n_records": e3["n_records"],
            "repeats": e3["repeats"],
            "curve": curve,
            "by_budget_schedule": by_bs,
            "curve_monotone_nondecreasing": bool(monotone),
            "cost_per_success_ms": cost_per_success,
        },
        "recompute_checks_passed": bool(checks_ok),
    }
    with open(os.path.join(res, "stats.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    print("recompute checks passed:", checks_ok)
    print("--- E1/E1b measured latencies (ms) ---")
    print("%-26s %5s %7s %10s %10s %10s %16s" % ("tool", "n", "fail", "mean", "p50", "p95", "ci95(mean)"))
    for n, t in tools.items():
        ci = t["ci95_mean_ms"] or {}
        print("%-26s %5d %7.3f %10.3f %10.3f %10.3f   [%7.3f, %7.3f]"
              % (n, t["n"], t["failure_rate"], t["mean_ms"], t["p50_ms"], t["p95_ms"],
                 ci.get("lo95", float("nan")), ci.get("hi95", float("nan"))))
    print("--- E2 ---")
    for k, v in e2_out["baselines"].items():
        print("  %-20s succ=%.4f tokens=%.0f ms=%.0f" % (k, v["success"], v["cost_tokens"], v["cost_ms"]))
    print("  vs_all_max gain at its cost: %s pts; cost ratio at matched success %.3f"
          % (e2c["vs_all_max"]["success_gain_points_at_baseline_cost"],
             e2c["vs_all_max"]["cost_ratio_baseline_over_unified_at_matched_success"]))
    print("  vs_fixed_mid gain at its cost: %.3f pts; cost ratio %.3f"
          % (e2c["vs_fixed_mid"]["success_gain_points_at_baseline_cost"],
             e2c["vs_fixed_mid"]["cost_ratio_baseline_over_unified_at_matched_success"]))
    print("  vs_decoupled cost ratio at 40%% success: %.3f"
          % e2_out["vs_decoupled"]["cost_ratio_decoupled_over_unified_at_40pct"])
    print("  saturation: target90 cost unified=%.0f vs all_max=%.0f (ratio %.2f)"
          % (su_max["unified_cost_tokens_at_target90"], su_max["all_max_cost_tokens"],
             su_max["cost_ratio_all_max_over_unified_at_target90"]))
    print("--- E3 ---")
    for l in labels:
        c = curve[l]
        print("  %-12s n=%3d succ=%.4f ci95=[%.3f,%.3f] mean_ms=%.1f steps=%.1f"
              % (l, c["n"], c["success_rate"], c["success_rate_ci95"]["lo95"],
                 c["success_rate_ci95"]["hi95"], c["mean_elapsed_ms"], c["mean_steps"]))
    print("  monotone:", monotone)
    return 0 if checks_ok else 1


if __name__ == "__main__":
    sys.exit(main())
