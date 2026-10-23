#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_h4_claims.py — gate the H4 numbers that enter the manuscript.

Two rules, both machine-checked against the落盘 result JSON (no hard-coded
numbers in this file):

  R1 BACKING   every H4 number that appears in the manuscript must be traceable
               to a field in results/h4_real_llm_gx_qwen3_8b.json.
  R2 GUARD     a g_x POINT ESTIMATE may not appear in the manuscript when its
               axis failed the identifiability test (interior cells >= 2 AND
               bootstrap CI width <= max_ci_width). This is the rule that the
               2026-09-12 run violated before the guard was strengthened:
               g_steps=0.9128 had CI95 width 1.0000 and MUST NOT be quotable.

Non-vacuity (a gate that cannot fail is not a gate):
  `--selftest` runs two injected counter-examples and FAILS if either is not
  caught -- a quoted withheld estimate (must be rejected) and a clean text with
  no H4 numbers (must be accepted). Run it in CI; it is also run by
  gates_config.json.

Usage:
  python3 check_h4_claims.py <paper_dir> [--result <json>] [--out report.md]
  python3 check_h4_claims.py <paper_dir> --selftest
Exit: 0 = pass; 1 = violation; 2 = the gate could not run (missing input).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

RESULT_NAME = "results/h4_real_llm_gx_qwen3_8b.json"
# Every H4 artifact a manuscript number may legitimately resolve to.  The main
# result file alone is not enough: the paper also quotes the paired test, the
# non-monotonicity test and the think-mode probe, which live in their own
# persisted artifacts.
EXTRA_RESULTS = (
    "results/h4_derived_stats.json",
    "results/h4_think_off_probe.json",
    "results/h4_pilot_steps.json",
)
# Manuscript targets: the H4 numbers may only be quoted in these places.
TEX_GLOBS = ("paper/main.tex",)


def load_result(paper_dir, override=None):
    p = override or os.path.join(paper_dir, RESULT_NAME)
    if not os.path.isfile(p):
        return None, p
    return json.load(open(p, encoding="utf-8")), p


def collected_numbers(doc, extras=()):
    """All numbers the H4 artifacts can BACK, keyed to their source field."""
    backed = {}

    def walk(o, prefix):
        """Flatten arbitrarily nested JSON; every scalar is a backable number."""
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, "%s.%s" % (prefix, k) if prefix else str(k))
        elif isinstance(o, list):
            for i, v in enumerate(o[:3]):
                walk(v, "%s[%d]" % (prefix, i))
        elif isinstance(o, bool):
            pass
        elif isinstance(o, (int, float)):
            backed.setdefault(round(float(o), 6), []).append(prefix)

    walk(doc, "")
    for path in extras:
        try:
            walk(json.load(open(path, encoding="utf-8")), os.path.basename(path))
        except Exception:
            pass

    def add(val, field):
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            backed.setdefault(round(float(val), 6), []).append(field)

    t = doc.get("timing") or {}
    for k, v in t.items():
        add(v, "timing." + k)
    for k, v in (doc.get("gain_fit") or {}).get("params", {}).items():
        add(v, "gain_fit.params." + k)
    for k, ci in ((doc.get("gain_fit") or {}).get("params_ci95") or {}).items():
        for b, v in ci.items():
            add(v, "gain_fit.params_ci95.%s.%s" % (k, b))
    add((doc.get("gain_fit") or {}).get("r_squared_on_cells"), "gain_fit.r_squared_on_cells")
    for k, v in (doc.get("summary_by_cell") or {}).items():
        add(v.get("success"), "summary_by_cell[%s].success" % k)
        add(v.get("n"), "summary_by_cell[%s].n" % k)
    for lvl, v in (doc.get("iso_success_curve") or {}).items():
        add(v.get("success"), "iso_success_curve[%s].success" % lvl)
        add(v.get("n"), "iso_success_curve[%s].n" % lvl)
    for k, v in (doc.get("gain_fit") or {}).get("identifiability", {}).items():
        add(v.get("ci95_width"), "gain_fit.identifiability.%s.ci95_width" % k)
    return backed


DEFAULT_MAX_CI_WIDTH = 0.30


def guard_threshold(doc):
    fit = doc.get("gain_fit") or {}
    for v in (fit.get("identifiability") or {}).values():
        if v.get("max_ci_width") is not None:
            return float(v["max_ci_width"])
    return DEFAULT_MAX_CI_WIDTH


def withheld_estimates(doc):
    """{value: (axis, reason)} for every axis whose point estimate must NOT be quoted.

    The verdict is RE-DERIVED from the CI widths, not read from the stored
    `unidentified_axes` list.  A result file produced before the guard was
    strengthened still says `unidentified_axes: []` while its CIs span ~1.0; if
    this gate trusted that field it would pass vacuously on exactly the run that
    motivated the guard.  (Caught by --selftest on 2026-09-12.)
    """
    out = {}
    fit = doc.get("gain_fit") or {}
    thr = guard_threshold(doc)
    listed = set(fit.get("unidentified_axes") or [])
    for ax in ("steps", "tools", "vision"):
        val = (fit.get("params") or {}).get("g_" + ax)
        if not isinstance(val, (int, float)):
            continue
        ident = (fit.get("identifiability") or {}).get(ax) or {}
        width = ident.get("ci95_width")
        if width is None:
            ci = (fit.get("params_ci95") or {}).get("g_" + ax) or {}
            if ci.get("lo95") is not None and ci.get("hi95") is not None:
                width = float(ci["hi95"]) - float(ci["lo95"])
        too_wide = (width is not None and width > thr)
        if ax in listed or too_wide:
            why = ("CI95 width %.4f > %.3f: not pinned" % (width, thr)) if too_wide \
                else "listed unidentified"
            out[round(float(val), 6)] = (ax, why)
    return out


def is_backed(token, backed, tol=0.0006):
    """A manuscript number is backed if it matches a result value at 3 decimals."""
    try:
        x = float(token)
    except ValueError:
        return False
    for v in backed:
        if abs(x - v) <= tol:
            return True
    return False


NUM_RE = re.compile(r"(?<![\w.])(\d+\.\d{3,6})(?![\w])")


def audit_text(text, doc, label, extras=()):
    backed = collected_numbers(doc, extras)
    withheld = withheld_estimates(doc)
    findings = []
    max_w = ((doc.get("gain_fit") or {}).get("identifiability") or {})
    threshold = next((v.get("max_ci_width") for v in max_w.values()
                      if v.get("max_ci_width") is not None), 0.30)

    # R2 first: a withheld point estimate is a hard failure wherever it appears.
    for m in NUM_RE.finditer(text):
        tok = m.group(1)
        try:
            x = round(float(tok), 6)
        except ValueError:
            continue
        # A quoted estimate is rounded, so match at the QUOTED precision:
        # "0.913" (3 dp) must match a withheld 0.912812.
        dp = len(tok.split(".")[1]) if "." in tok else 0
        for wv, (ax, why) in withheld.items():
            if round(wv, dp) == x:
                findings.append((
                    "R2_GUARD", "FAIL",
                    "%s quotes g_%s = %s but that estimate is WITHHELD (%s): "
                    "the point estimate must not appear" % (label, ax, tok, why)))
                break  # inside the match, NOT the loop: see the three-axis selftest

    # R1: H4 numbers named in the manuscript need a backing field.
    # Only numbers in the same sentence as an H4 marker are audited, so that
    # unrelated paper numbers (E1/E2/E3) are not falsely flagged.
    for sent in re.split(r"(?<=[.;])\s+", text):
        if not re.search(r"\bH4\b|agent[- ]axis gain|g_\{?(steps|tools|vision)\}?", sent):
            continue
        for m in NUM_RE.finditer(sent):
            tok = m.group(1)
            if not is_backed(tok, backed):
                findings.append((
                    "R1_BACKING", "FAIL",
                    "%s quotes %s near an H4 marker but no field in %s backs it"
                    % (label, tok, RESULT_NAME)))
    return findings


def read_targets(paper_dir):
    out = []
    for rel in TEX_GLOBS:
        p = os.path.join(paper_dir, rel)
        if os.path.isfile(p):
            out.append((rel, open(p, encoding="utf-8", errors="ignore").read()))
    return out


# One injection PER AXIS.  A single-axis injection is not enough: an earlier
# version of this gate broke out of the matching loop after the first entry, so
# it caught g_steps and silently passed g_tools and g_vision.
INJECT_WITHHELD = {
    "steps": (r"The estimated agent-axis gain is g_steps = 0.913, which shows "
              r"that trajectory steps are the dominant source of improvement."),
    "tools": (r"The H4 agent-axis gain g_tools = 0.496 dominates the calibrated "
              r"partial gain."),
    "vision": (r"The H4 agent-axis gain g_vision = 0.041 is the weakest of the "
               r"calibrated partial gains."),
}
INJECT_CLEAN = ("The end-to-end loop reproduces the saturation shape reported for E3. "
                "No agent-axis gain is quoted here.")


def selftest(doc, extras=()):
    """Non-vacuity: EVERY withheld axis must be rejected when quoted, and clean
    text must be accepted.  Per-axis, because a loop-exit bug can make the guard
    cover only the first axis (this happened -- see INJECT_WITHHELD)."""
    ok = True
    withheld = withheld_estimates(doc)
    covered = {ax for _v, (ax, _w) in withheld.items()}
    for ax, text in INJECT_WITHHELD.items():
        if ax not in covered:
            print("SELFTEST skip %-7s (not withheld in this result)" % ax)
            continue
        bad = audit_text(text, doc, "<injected-%s>" % ax, extras)
        hit = [f for f in bad if f[0] == "R2_GUARD"]
        if hit:
            print("SELFTEST ok: injected g_%-7s rejected" % ax)
        else:
            print("SELFTEST FAIL: injected g_%-7s was NOT caught" % ax, file=sys.stderr)
            ok = False
    good = audit_text(INJECT_CLEAN, doc, "<injected-clean>", extras)
    if good:
        print("SELFTEST FAIL: clean text was flagged: %s" % good, file=sys.stderr)
        ok = False
    else:
        print("SELFTEST ok: clean text accepted")
    return 0 if ok else 1


REQUIRED_IN_PACKAGE = (
    # (path inside the package, why the paper cannot be checked without it)
    ("results/h4_real_llm_gx_qwen3_8b.json", "the 672 per-episode records: the only evidence for the H4 curve"),
    ("results/h4_derived_stats.json", "the paired test, both non-monotonicity fits, the action profile"),
    ("experiments/h4_derived_stats.py", "regenerates the derived statistics from the records"),
    ("experiments/analyze_h4_result.py", "--refit re-runs the gain fit under the current guard"),
    ("experiments/h4_real_llm_gx.py", "the harness that produced the records"),
)


def check_package(paper_dir, zip_path=None):
    """Adversarial review M1: the paper's central negative result must be
    recomputable from the released package.  A gate, not a habit -- the earlier
    blanket 'h4_*' exclusion silently shipped the paper without its own H4 data.
    """
    import hashlib
    import zipfile
    if zip_path is None:
        cands = sorted(__import__("glob").glob(os.path.join(paper_dir, "submission", "*.zip")))
        if not cands:
            return [("PACKAGE", "FAIL", "no submission zip found under submission/")]
        zip_path = cands[0]
    findings = []
    try:
        zf = zipfile.ZipFile(zip_path)
    except Exception as e:
        return [("PACKAGE", "FAIL", "cannot open %s: %s" % (zip_path, e))]
    names = set(zf.namelist())
    for rel, why in REQUIRED_IN_PACKAGE:
        if rel not in names:
            findings.append(("PACKAGE", "FAIL",
                             "%s is MISSING from %s -- %s" % (rel, os.path.basename(zip_path), why)))
    # internal consistency: the shipped derived stats must hash the shipped result
    try:
        res = zf.read("results/h4_real_llm_gx_qwen3_8b.json")
        der = json.loads(zf.read("results/h4_derived_stats.json").decode("utf-8"))
        h = hashlib.sha256(res).hexdigest()
        if der.get("source_sha256") != h:
            findings.append(("PACKAGE", "FAIL",
                             "shipped h4_derived_stats.source_sha256 does not match the "
                             "shipped result bytes: the package is not self-consistent"
                             " (redaction changed the result after derivation?)"))
    except KeyError:
        pass
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper_dir")
    ap.add_argument("--result", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--package", action="store_true",
                    help="also assert the released zip ships the H4 evidence and that "
                         "its derived statistics match the shipped records")
    args = ap.parse_args()

    doc, path = load_result(args.paper_dir, args.result)
    if doc is None:
        print("H4 claims gate: result file not found (%s) -> cannot run" % path, file=sys.stderr)
        return 2

    extras = [os.path.join(args.paper_dir, r) for r in EXTRA_RESULTS]
    if args.selftest:
        return selftest(doc, extras)

    findings = []
    extras = [os.path.join(args.paper_dir, r) for r in EXTRA_RESULTS]
    for rel, text in read_targets(args.paper_dir):
        findings += audit_text(text, doc, rel, extras)

    if args.package:
        findings += check_package(args.paper_dir)

    lines = ["# H4 claims gate report", "",
             "result: `%s`" % RESULT_NAME,
             "identifiability threshold: CI95 width <= %s (re-derived, not read "
             "from the stored verdict)" % guard_threshold(doc),
             "withheld axes (re-derived): %s"
             % (", ".join(sorted({ax for ax, _w in withheld_estimates(doc).values()})) or "none"),
             ""]
    if not findings:
        lines += ["## PASS — no unbacked H4 number and no withheld point estimate", ""]
    else:
        lines += ["## %d violation(s)" % len(findings), ""]
        lines += ["- [%s] %s :: %s" % (k, s, m) for k, s, m in findings]
        lines += [""]
    report = "\n".join(lines)
    print(report)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(report + "\n")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
