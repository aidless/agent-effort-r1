#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analyze_h4_result.py — post-hoc verification of an H4 result file.

Why this exists
---------------
The CPU dry run's `stub_gain_recovery` check proves the FITTER works by making it
recover simulator constants that are known by construction.  A REAL run has no
such ground truth, so that check is *not applicable* and `stub_gain_recovery` is
null there by design.  The honest analogue is a RESIDUAL check: does the fitted
model actually reproduce the observed per-cell success rates?  If the fitting
step went wrong, the residuals say so.

This script reports, from a result JSON and nothing else:
  * the measured grid (n, success, Wilson CI) per cell;
  * the fitted g_x with bootstrap CI and the identifiability verdict;
  * structurally infeasible cells, listed separately (never folded into a gain);
  * per-cell observed vs predicted failure and residuals (the real-run check).

Usage:
  python3 analyze_h4_result.py <h4_result.json> [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys


def bootstrap_ci(xs, n_boot=4000, seed=20260911):
    import numpy as np
    a = np.asarray(xs, dtype=float)
    if a.size < 2:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, a.size, size=(n_boot, a.size))
    st = a[idx].mean(axis=1)
    return {"mean": float(a.mean()), "lo95": float(np.percentile(st, 2.5)),
            "hi95": float(np.percentile(st, 97.5))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("result")
    ap.add_argument("--json", default=None)
    ap.add_argument("--refit", action="store_true",
                    help="re-fit from the raw records with the CURRENT (possibly "
                         "strengthened) guard and report whether the stored fit still "
                         "holds -- lets a guard fix be re-evaluated without a GPU rerun")
    ap.add_argument("--max-ci-width", type=float, default=0.30)
    args = ap.parse_args()

    d = json.load(open(args.result, encoding="utf-8"))

    print("=" * 78)
    print("H4 RESULT VERIFICATION")
    print("=" * 78)
    print("file          :", args.result)
    print("backend       : %s   is_real_llm=%s   dry_run=%s"
          % (d.get("backend"), d.get("is_real_llm"), d.get("dry_run")))
    print("script_sha256 :", d.get("script_sha256"))
    for k in ("model_path", "chat_mode_requested", "chat_mode_effective", "lock_mode"):
        print("%-14s: %s" % (k, d.get(k)))
    mf = d.get("model_fingerprint") or {}
    if mf:
        print("model         : %d files, %.2f GB, full_hash=%s"
              % (mf.get("n_files", 0), mf.get("total_bytes", 0) / 1e9, mf.get("full_hash")))
    print("gpu_at_load   :", d.get("gpu_state_at_load"))
    print("gpu_util      :", d.get("gpu_memory_utilization_detail"))
    print()

    t = d.get("timing") or {}
    print("--- wall clock (measured per episode, summed; never mean x count) ---")
    print("total %.1f s | episodes %s | mean/episode %.1f s | %.2f ep/min"
          % (t.get("wall_clock_s_total", -1), t.get("episodes"),
             (t.get("mean_episode_ms") or 0) / 1000.0,
             t.get("episodes_per_minute", -1)))
    print()

    cells = d.get("summary_by_cell") or {}
    print("--- measured cells (n, success, Wilson 95% CI, failure reasons) ---")
    hdr = "%-14s %-18s %4s %8s %-20s %s"
    print(hdr % ("arm", "level", "n", "succ", "CI95(Wilson)", "failure reasons"))
    for k in sorted(cells):
        v = cells[k]
        ci = v.get("success_ci95_wilson") or {}
        cis = "[%.3f,%.3f]" % (ci.get("lo95", -1), ci.get("hi95", -1)) if ci else "-"
        print(hdr % (v["arm"], v["level"], v["n"], "%.3f" % v["success"], cis,
                     json.dumps(v.get("failure_reasons", {}), ensure_ascii=False)))
    print()

    fit = d.get("gain_fit") or {}
    print("--- gain fit ---")
    if not fit.get("fitted"):
        print("NOT FITTED:", json.dumps(fit, ensure_ascii=False))
    else:
        print("form:", fit.get("form"))
        print("%-10s %-10s %-22s %s" % ("param", "value", "bootstrap CI95", "verdict"))
        for name, val in (fit.get("params") or {}).items():
            ci = (fit.get("params_ci95") or {}).get(name)
            cis = "[%.3f,%.3f]" % (ci["lo95"], ci["hi95"]) if ci else "-"
            verdict = ""
            if name.startswith("g_"):
                ax = name[2:]
                idt = (fit.get("identifiability") or {}).get(ax, {})
                verdict = "IDENTIFIED" if idt.get("identified") else "WITHHELD (not identified)"
            print("%-10s %-10.4f %-22s %s" % (name, val, cis, verdict))
        print("r^2 on cells: %s   n_cells: %s"
              % (fit.get("r_squared_on_cells"), fit.get("n_cells")))
        print()
        print("identifiability:")
        for ax, v in (fit.get("identifiability") or {}).items():
            print("  %-7s n_cells=%d interior=%d identified=%s  rates=%s"
                  % (ax, v["n_cells"], v["n_interior_cells"], v["identified"],
                     v["distinct_success_rates"]))
        if fit.get("unidentified_axes"):
            print("  -> point estimates WITHHELD for: %s" % ", ".join(fit["unidentified_axes"]))
    print()

    st = d.get("stub_gain_recovery")
    print("--- recovery self-check ---")
    if st is None:
        print("stub_gain_recovery = null  (EXPECTED for a real run: it has no known")
        print("  ground truth to recover. The applicable real-run check is the")
        print("  RESIDUAL check below.)")
    else:
        print("all_recovered:", st.get("all_recovered"))
        for k, v in (st.get("params") or {}).items():
            print("  %-9s declared=%.3f fitted=%s recovered=%s"
                  % (k, v["declared"], v["fitted"], v["recovered"]))
    print()

    floor = d.get("floor_cells_excluded_from_fit") or []
    print("--- structurally infeasible cells (excluded from the fit) ---")
    if not floor:
        print("none")
    for c in floor:
        print("  %-14s %s success=%.3f  %s"
              % (c["arm"], json.dumps(c["budget"], ensure_ascii=False), c["success"], c["why"]))
    print()

    # ---- residual check: the real-run analogue of the recovery check ----
    print("--- residual check (observed vs fitted failure per cell) ---")
    import numpy as np
    if not fit.get("fitted"):
        print("skipped (no fit)")
    else:
        refs = fit.get("refs_used") or {}
        p = fit["params"]
        rows = []
        for k, v in sorted(cells.items()):
            if not v["arm"].startswith("axis_"):
                continue
            b = v["budget"]
            sat = 1.0
            for ax, fld in (("steps", "max_steps"), ("tools", "max_tool_calls"),
                            ("vision", "max_vision_probes")):
                if ax not in p:
                    continue
                r = refs.get(ax)
                if not r:
                    continue
                sat *= (1.0 - p["g_" + ax] * (1.0 - math.exp(-float(b[fld]) / r)))
            pred_fail = (1.0 - p["p0"]) * sat
            obs = 1.0 - v["success"]
            rows.append((k, obs, pred_fail, obs - pred_fail))
        if rows:
            print("%-34s %10s %10s %10s" % ("cell", "obs_fail", "pred_fail", "resid"))
            for k, o, pr, r in rows:
                print("%-34s %10.3f %10.3f %+10.3f" % (k, o, pr, r))
            res = np.array([r for *_x, r in rows])
            print()
            print("residuals: mean %+.4f  sd %.4f  max|r| %.4f  (n=%d)"
                  % (res.mean(), res.std(ddof=1) if res.size > 1 else 0.0,
                     np.abs(res).max(), res.size))
            print("NOTE: with n=%d per cell the success rate is quantised to 1/%d,"
                  % (list(cells.values())[0]["n"], list(cells.values())[0]["n"]))
            print("      so small residuals are not evidence of a good fit.")
    print()

    if args.refit:
        print("--- RE-FIT with the current guard (max_ci_width=%.3f) ---" % args.max_ci_width)
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        spec = importlib.util.spec_from_file_location("h4mod", os.path.join(here, "h4_real_llm_gx.py"))
        hm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hm)
        cells = d.get("summary_by_cell") or {}
        fc = [{"arm": v["arm"], "budget": v["budget"], "fail": 1.0 - v["success"],
               "n": v["n"], "success": v["success"]}
              for v in cells.values() if v["arm"].startswith("axis_")]
        fc = [c for c in fc if hm.structurally_feasible(c["budget"])]
        nf = hm.fit_gains(fc, n_boot=400, max_ci_width=args.max_ci_width)
        stored = (d.get("gain_fit") or {}).get("identifiability") or {}
        print("%-8s %-12s %-12s %s" % ("axis", "stored", "refit", "changed?"))
        for ax in ("steps", "tools", "vision"):
            a = (stored.get(ax) or {}).get("identified")
            b = (nf["identifiability"].get(ax) or {}).get("identified")
            print("%-8s %-12s %-12s %s" % (ax, a, b, "YES" if a != b else "no"))
        print()
        print("refit params:", json.dumps(nf["params"]))
        print("refit withheld:", nf["unidentified_axes"])
        for ax, v in nf["identifiability"].items():
            print("  %-7s ci_width=%.4f interior=%d -> identified=%s (%s)"
                  % (ax, v["ci95_width"] or -1, v["n_interior_cells"], v["identified"], v["why"]))
        print()

    print("--- declared limits carried in the result ---")
    for x in (d.get("declared_limits") or []):
        print("  -", x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
