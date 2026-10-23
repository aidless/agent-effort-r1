#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compare_h4_to_e2.py — H4 measured gains vs the E2 ASSUMED gains.

This is a DIRECTIONAL comparison only.  E2's g_x are *assumptions* chosen for the
allocation frontier, not measurements, so agreement is not validation and
disagreement is not falsification of E2: it is the first estimate of how far the
assumption sits from a real LLM policy.

Usage:
  python3 compare_h4_to_e2.py <h4_result.json> [<e2_allocation.json>]
"""
from __future__ import annotations

import json
import sys


def assumed_from_e2(path):
    d = json.load(open(path, encoding="utf-8"))
    # E2 stores its fitted/dedicated parameters; search for the ASSUMED block
    for key in ("assumed_params", "params", "model_params", "assumed"):
        if key in d and isinstance(d[key], dict):
            p = d[key]
            if "gain_steps" in p:
                return {k: p[k] for k in p if str(k).startswith(("gain_", "ref_", "base_"))}
    # fall back to a deep scan
    found = {}

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k.startswith(("gain_", "ref_")) and isinstance(v, (int, float)):
                    found.setdefault(k, v)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(d)
    return found


def main():
    h4p = sys.argv[1]
    e2p = sys.argv[2] if len(sys.argv) > 2 else None
    h4 = json.load(open(h4p, encoding="utf-8"))

    print("H4 result    :", h4p)
    print("backend      : %s  is_real_llm=%s  dry_run=%s" % (
        h4.get("backend"), h4.get("is_real_llm"), h4.get("dry_run")))
    if h4.get("dry_run") or not h4.get("is_real_llm"):
        print("!! THIS IS NOT A MEASUREMENT OF ANY MODEL -- comparison suppressed")
        return 0

    fit = h4.get("gain_fit") or {}
    if not fit.get("fitted"):
        print("fit not available:", fit)
        return 1
    print("script_sha256:", h4.get("script_sha256"))
    print("model_path   :", h4.get("model_path"))
    t = h4.get("timing") or {}
    print("wall-clock   : %.1f s total, %s episodes, %.2f s/episode" % (
        t.get("wall_clock_s_total", -1), t.get("episodes"),
        t.get("mean_episode_ms", 0) / 1000.0))
    print()

    assumed = assumed_from_e2(e2p) if e2p else {}
    axis_key = {"steps": "g_steps", "tools": "g_tools", "vision": "g_vision"}

    print("%-8s %-10s %-10s %-22s %-12s %s" % (
        "axis", "H4 g_x", "E2 assumed", "H4 CI95", "identified", "direction"))
    print("-" * 78)
    for ax, gkey in axis_key.items():
        ident = (fit.get("identifiability") or {}).get(ax, {})
        got = fit["params"].get(gkey)
        ci = (fit.get("params_ci95") or {}).get(gkey)
        asm = assumed.get(gkey)
        if ax in (fit.get("unidentified_axes") or []):
            print("%-8s %-10s %-10s %-22s %-12s %s" % (
                ax, "withheld", "%.3f" % asm if asm is not None else "n/a",
                "-", "NO", "cannot compare (unidentified)"))
            continue
        if asm is None:
            print("%-8s %-10.4f %-10s %-22s %-12s %s" % (
                ax, got, "n/a", "[%.3f,%.3f]" % (ci["lo95"], ci["hi95"]) if ci else "-",
                "yes", "no E2 reference found"))
            continue
        direction = "same sign" if (got > 0) == (asm > 0) else "OPPOSITE SIGN"
        closer = "H4 lower" if got < asm else ("H4 higher" if got > asm else "equal")
        print("%-8s %-10.4f %-10.3f %-22s %-12s %s (%s)" % (
            ax, got, asm, "[%.3f,%.3f]" % (ci["lo95"], ci["hi95"]) if ci else "-",
            "yes", direction, closer))
    print()
    print("Directional only: E2's gains are ASSUMPTIONS, not measurements.")
    print("A disagreement is a distance measurement, not a refutation of E2.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
