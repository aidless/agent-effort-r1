#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""h4_derived_stats.py — derived H4 statistics, written to a first-class artifact.

Why this exists
---------------
The H4 result file holds per-episode records and cell aggregates, but the
quantities the paper actually argues from are DERIVED from them: the paired
McNemar table, the logistic non-monotonicity test (in two forms -- with and
without the structurally-floored level), and the action-frequency profile that
exposes the mechanism.  Leaving them only in prose means no machine check can
back them (the claim ledger verifier requires every claimed number to resolve to
a field), so they are computed here once and persisted.

Rule enforced: the non-monotonicity test is reported BOTH with and without the
floored level, because including a level at which no policy can pass manufactures
a spurious inverted-U.  See H4_FINDINGS.md §2.3.

Usage:
  python3 experiments/h4_derived_stats.py results/h4_real_llm_gx_qwen3_8b.json \
          --out results/h4_derived_stats.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter


def mcnemar(recs, level_a, level_b):
    """Exact McNemar on pairs matched by (task, repeat, menu)."""
    def key(r):
        return (r["task"], r["repeat"], r["menu"])
    a = {key(r): bool(r["success"]) for r in recs if r["level"] == level_a}
    b = {key(r): bool(r["success"]) for r in recs if r["level"] == level_b}
    common = sorted(set(a) & set(b))
    worsened = sum(1 for k in common if a[k] and not b[k])
    improved = sum(1 for k in common if not a[k] and b[k])
    ties = sum(1 for k in common if a[k] == b[k])
    m = worsened + improved
    if m == 0:
        p = 1.0
    else:
        k = min(worsened, improved)
        p = min(1.0, 2.0 * sum(math.comb(m, i) for i in range(k + 1)) / (2 ** m))
    return {"n_pairs": len(common), "worsened": worsened, "improved": improved,
            "ties": ties, "exact_p_two_sided": p}


def logistic_lr(recs, levels, budget):
    """LR test: linear vs quadratic in standardised log2(budget)."""
    import numpy as np
    from scipy.stats import chi2
    sub = [r for r in recs if r["level"] in levels]
    x = np.array([budget[r["level"]] for r in sub], float)
    y = np.array([1.0 if r["success"] else 0.0 for r in sub], float)
    z = (np.log2(x) - np.log2(x).mean()) / np.log2(x).std()

    def fit(design):
        X = np.column_stack([np.ones(len(y))] + design)
        beta = np.zeros(X.shape[1])
        for _ in range(300):
            p = 1.0 / (1.0 + np.exp(-X @ beta))
            W = np.diag(p * (1 - p) + 1e-12)
            try:
                step = np.linalg.solve(X.T @ W @ X, X.T @ (y - p))
            except np.linalg.LinAlgError:
                break
            beta = beta + step
            if np.max(np.abs(step)) < 1e-12:
                break
        p = np.clip(1.0 / (1.0 + np.exp(-X @ beta)), 1e-12, 1 - 1e-12)
        return beta, float(np.sum(y * np.log(p) + (1 - y) * np.log(1 - p)))

    b1, ll1 = fit([z])
    b2, ll2 = fit([z, z ** 2])
    lr = 2.0 * (ll2 - ll1)
    return {"n": int(len(y)), "levels": list(levels),
            "loglik_linear": ll1, "loglik_quadratic": ll2,
            "lr_chi2": float(lr), "df": 1,
            "p_value": float(chi2.sf(lr, 1)),
            "quadratic_coef_std_log2_budget": float(b2[2]),
            "monotone_model_implied": "p increases in every axis; a decrease is out of range"}


# The registered identifiability bar, defined once so the two writers cannot
# drift apart (the axis-only branch used to repeat the literal).
MAX_CI_WIDTH = 0.30


def identifiability_from(fit):
    """The quantity A9 is judged on. One formula, shared by the iso-bearing and the
    axis-only paths -- a second copy could drift from the first, and the whole point of
    the pre-registration is that the estimator does not change."""
    fit = fit or {}
    ident = {}
    for ax in ("steps", "tools", "vision"):
        v = (fit.get("identifiability") or {}).get(ax) or {}
        ci = (fit.get("params_ci95") or {}).get("g_" + ax) or {}
        w = None
        if ci.get("lo95") is not None and ci.get("hi95") is not None:
            w = float(ci["hi95"]) - float(ci["lo95"])
        ident[ax] = {"point_estimate": (fit.get("params") or {}).get("g_" + ax),
                     "ci95_width": w, "n_interior_cells": v.get("n_interior_cells"),
                     "withheld": bool(w is not None and w > MAX_CI_WIDTH)}
    return ident




def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("result")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    d = json.load(open(args.result, encoding="utf-8"))
    recs = d["records"]
    iso = [r for r in recs if r["arm"] == "iso"]
    if not iso:
        # A9 replicated the three axis arms only, so its artifact has no iso records at all.
        # The registered quantity (gain identifiability) is read from gain_fit and does not
        # touch iso; what the iso block produced -- curve, McNemar pairs, the logistic LR, the
        # action counts, the representative trajectory -- is NOT PRODUCED by this arm. Those
        # fields are written as an explicit not-run marker rather than 0 or an empty dict,
        # because an empty curve in results/ would read like a measurement of nothing.
        return write_axis_only(args, d, recs)

    budget = {b["label"]: b["max_steps"] for b in d["iso_with_e3"]["budget_levels"]}
    order = ["L0_minimal", "L1_low", "L2_mid", "L3_high", "L4_max"]

    curve = {}
    for L in order:
        rs = [r for r in iso if r["level"] == L]
        succ = sum(1 for r in rs if r["success"])
        curve[L] = {"n": len(rs), "n_success": succ,
                    "success": succ / len(rs) if rs else None,
                    "max_steps": budget[L],
                    "failure_reasons": dict(Counter(r["reason"] for r in rs))}

    pairs = {}
    for a, b in (("L0_minimal", "L1_low"), ("L1_low", "L4_max"),
                 ("L2_mid", "L3_high"), ("L3_high", "L4_max")):
        pairs["%s_to_%s" % (a, b)] = mcnemar(iso, a, b)

    lr_all = logistic_lr(iso, order, budget)
    lr_nof = logistic_lr(iso, order[1:], budget)

    actions = {}
    for L in order:
        rs = [r for r in iso if r["level"] == L]
        c = Counter()
        for r in rs:
            for t in r["model_turns"]:
                c[t.get("action")] += 1
        actions[L] = {a: c.get(a, 0) / len(rs) for a in ("read", "write", "test")}
    actions["_units"] = "actions per episode (mean)"

    # The single worst high-budget failure: the paper quotes this trajectory by
    # name, so it must be a recorded field rather than prose.
    cands = []
    for r in iso:
        if r["level"] != order[-1] or r["success"]:
            continue
        ws = sum(1 for t in r["model_turns"] if t.get("action") == "write")
        ts = sum(1 for t in r["model_turns"] if t.get("action") == "test")
        cands.append((ws, r, ts))
    rep_traj = None
    if cands:
        ws, r, ts = max(cands, key=lambda x: x[0])
        rep_traj = {"task": r["task"], "repeat": r["repeat"], "budget_level": r["level"],
                    "writes": ws, "tests": ts, "steps_used": r["steps_used"],
                    "model_turns": len(r["model_turns"]), "reason": r["reason"],
                    "reads": sum(1 for t in r["model_turns"] if t.get("action") == "read")}

    fit = d.get("gain_fit") or {}
    ident = identifiability_from(fit)

    out = {
        "generated_by": "experiments/h4_derived_stats.py",
        "source_result": args.result,
        "source_sha256": __import__("hashlib").sha256(open(args.result, "rb").read()).hexdigest(),
        "n_records": len(recs),
        "iso_curve": curve,
        "mcnemar_pairs": pairs,
        "logistic_lr_all_levels": lr_all,
        "logistic_lr_excluding_structurally_floored_level": lr_nof,
        "non_monotonicity_verdict": {
            "with_floored_level_quadratic_significant": bool(lr_all["p_value"] < 0.05),
            "without_floored_level_quadratic_significant": bool(lr_nof["p_value"] < 0.05),
            "reading": ("the quadratic term's significance comes from the structurally "
                        "floored level (no policy can pass there); once excluded the "
                        "quadratic is NOT significant, so the supported statement is a "
                        "monotone DECLINE above the low budget, not an interior optimum"),
        },
        "actions_per_episode": actions,
        "representative_failing_high_budget_trajectory": rep_traj,
        "identifiability_max_ci_width": MAX_CI_WIDTH,
        "gain_identifiability": ident,
    }
    open(args.out, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print("wrote %s" % args.out)
    print("  curve:", {k: round(v["success"], 4) for k, v in curve.items()})
    print("  L1->L4 McNemar:", pairs["L1_low_to_L4_max"])
    print("  LR all levels  : chi2=%.2f p=%.3g quad=%.3f"
          % (lr_all["lr_chi2"], lr_all["p_value"], lr_all["quadratic_coef_std_log2_budget"]))
    print("  LR excl. floor : chi2=%.2f p=%.3g quad=%.3f"
          % (lr_nof["lr_chi2"], lr_nof["p_value"], lr_nof["quadratic_coef_std_log2_budget"]))
    print("  withheld gains :", [k for k, v in ident.items() if v["withheld"]])
    return 0




def write_axis_only(args, d, recs):
    NOT_RUN = {"note": "no iso arm in this artifact: the arm was run as an axis-only "
                       "replication (protocol A9), so these descriptive iso statistics were "
                       "not produced here -- read them from the registered repeats=3 product"}
    ident = identifiability_from(d.get("gain_fit") or {})
    out = {
        "generated_by": "experiments/h4_derived_stats.py (axis-only branch)",
        "source_result": args.result,
        "source_sha256": __import__("hashlib").sha256(open(args.result, "rb").read()).hexdigest(),
        "n_records": len(recs),
        "arms_present": sorted({r["arm"] for r in recs}),
        "iso_curve": dict(NOT_RUN),
        "mcnemar_pairs": dict(NOT_RUN),
        "logistic_lr_all_levels": dict(NOT_RUN),
        "logistic_lr_excluding_structurally_floored_level": dict(NOT_RUN),
        "non_monotonicity_verdict": dict(NOT_RUN),
        "actions_per_episode": dict(NOT_RUN),
        "representative_failing_high_budget_trajectory": dict(NOT_RUN),
        "identifiability_max_ci_width": MAX_CI_WIDTH,
        "gain_identifiability": ident,
    }
    open(args.out, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print("wrote %s (axis-only branch; iso block not run)" % args.out)
    print("  arms present    :", out["arms_present"])
    for ax in ("steps", "tools", "vision"):
        v = ident.get(ax) or {}
        print("  %-6s width=%s point=%s withheld=%s"
              % (ax, v.get("ci95_width"), v.get("point_estimate"), v.get("withheld")))
    print("  withheld gains :", [k for k, v in ident.items() if v["withheld"]])
    return 0



if __name__ == "__main__":
    sys.exit(main())
