#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_v41_effort_evidence.py — canonical, recomputable evidence extractor.

Re-homes the P2 premise ("controllable reasoning effort -> controllable agent
effort") onto the TRUE source: DeepSeek-V4.1-Flash tech report.

HARD LINE-NUMBER CONVENTION (cross-paper, enforced):
  lines are produced by splitting the report text on "\\n" ONLY.
  str.splitlines() is BANNED here because the report contains 51 form feeds
  (\\x0c); splitlines() would shift every line number by +35 and make
  cross-paper citations mutually inconsistent.

Emits evidence/v41flash_effort_control.json with:
  - source identity (path, sha256, n_lines_lf, n_page_breaks)
  - machine checks (occurrence counts)
  - line-anchored verbatim quotes (line range -> exact text)

Every downstream number in the manuscript must be recomputable from this file.

Run:  python3 experiments/extract_v41_effort_evidence.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER_DIR = os.path.dirname(HERE)
REPORT_LOCAL = os.path.join(PAPER_DIR, "evidence", "V41FLASH_TechReport.txt")
# Fallback to the shared source tree (the queue keeps ONE authoritative copy so
# line numbers cannot drift).  The SHA-256 check below fails closed, so a
# drifted or substituted copy can never silently validate.
REPORT_SHARED = os.path.normpath(
    os.path.join(PAPER_DIR, os.pardir, "_shared", "evidence", "V41FLASH_TechReport.txt")
)
if os.environ.get("V41_REPORT_TXT"):
    REPORT, REPORT_SOURCE = os.environ["V41_REPORT_TXT"], "env:V41_REPORT_TXT"
elif os.path.exists(REPORT_SHARED):
    REPORT, REPORT_SOURCE = REPORT_SHARED, "authoritative source tree"
else:
    REPORT, REPORT_SOURCE = REPORT_LOCAL, "in-package copy"
# The document that the extracted quotes were taken FROM, as a path the package
# itself uses.  The resolution detail is recorded separately so that the
# evidence package stays portable across hosts and mirrors.
REPORT_DOC_PATH = "evidence/V41FLASH_TechReport.txt"
EXPECTED_SHA256 = "ac24848a4dee30669b9caac6ca05b62d7186e4c546add099ccc906065288abf3"
# A third-party report that turned out to be a DIFFERENT document; recorded so
# the exclusion is auditable without naming an unrelated sibling submission.
WRONG_SOURCE_NOTE = "excluded: an unrelated third-party report, identified by SHA-256"
OUT = os.path.join(PAPER_DIR, "evidence", "v41flash_effort_control.json")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_lines_lf(path: str) -> list[str]:
    """Split on \\n ONLY (banned: str.splitlines(), see module docstring)."""
    with open(path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


# ---------------------------------------------------------------- quotes ----
# (key, first_line, last_line, required_exact_substring)
QUOTES = [
    (
        "abstract_checkpoint_url",
        22,
        24,
        "checkpoints are available",
    ),
    (
        "s514_heading",
        2039,
        2039,
        "Controllable Reasoning Effort in RL",
    ),
    (
        "s514_scalar_b_definition_en",
        2042,
        2044,
        "scalar effort level",
    ),
    (
        "s514_system_prompt",
        2046,
        2049,
        "range 1",
    ),
    (
        "s514_b_range_100",
        2051,
        2051,
        "requested effort level",
    ),
    (
        "s514_sampling_Mb",
        2052,
        2052,
        "sample",
    ),
    (
        "s514_subgroup_normalization",
        2061,
        2064,
        "subgroup",
    ),
    (
        "s514_length_penalty_eq9",
        2065,
        2081,
        "length-penalty term",
    ),
    (
        "s514_kb_exponential_eq10",
        2081,
        2094,
        "decreases exponentially",
    ),
    (
        "s514_k0_bmin_Delta_lambda",
        2092,
        2096,
        "basic penalty coefficient",
    ),
    (
        "s514_deployment_interpolation",
        2100,
        2104,
        "interpolated reasoning behaviors",
    ),
    (
        "s514_api_tiers_table2",
        2105,
        2111,
        "preset reasoning-effort tiers",
    ),
    (
        "toc_5_3_3",
        303,
        303,
        "Performance across reasoning efforts",
    ),
    (
        "toc_appendixC",
        343,
        343,
        "Exponential Token Penalty in Reasoning Effort Control",
    ),
    (
        "toc_appendixB2",
        335,
        335,
        "Reasoning Efforts across Scaffolds",
    ),
    (
        "toc_appendixB3",
        339,
        339,
        "Detailed Results of Reasoning Benchmarks",
    ),
    (
        "s532_frontloaded_gains",
        2431,
        2443,
        "front-loaded",
    ),
    (
        "s533_perf_across_efforts",
        2444,
        2455,
        "monotonically",
    ),
    (
        "s534_scaffold_transfer",
        2456,
        2470,
        "eight configurations from six scaffold families",
    ),
    (
        "s535_multiagent_heading",
        2656,
        2663,
        "Multi-Agent",
    ),
    (
        "s535_derived_latency_dag",
        2740,
        2744,
        "measured tool-execution",
    ),
    (
        "fig10_deadline_scaling",
        2759,
        2763,
        "multi-agent configurations outperform",
    ),
    (
        "fig10_caption",
        2736,
        2737,
        "wall-clock",
    ),
    (
        "fig9_caption",
        2598,
        2604,
        "Figure 9",
    ),
    (
        "table4_scaffolds_max_effort",
        2605,
        2609,
        "Table 4",
    ),
    (
        "fig11_caption",
        3476,
        3482,
        "Figure 11",
    ),
    (
        "fig11_trajectory_length",
        3258,
        3268,
        "monotonically with effort",
    ),
    (
        "fig12_smooth_control",
        3269,
        3278,
        "smooth, well-behaved control",
    ),
    (
        "appxC_heading",
        3486,
        3486,
        "Exponential Token Penalty in Reasoning Effort Control",
    ),
    (
        "appxC_soft_budget",
        3487,
        3490,
        "without imposing a hard token budget",
    ),
    (
        "appxC_eq11_deduction",
        3491,
        3501,
        "caps the deduction",
    ),
    (
        "appxC_eq12_kb",
        3501,
        3511,
        "penalty coefficient at the lowest effort level",
    ),
    (
        "appxC_marginal_utility",
        3512,
        3513,
        "probability of being",
    ),
    (
        "appxC_eq13_preferred_length",
        3711,
        3728,
        "arg max",
    ),
    (
        "appxC_eq14_foc",
        3730,
        3741,
        "first-order condition",
    ),
    (
        "appxC_eq15_exponential_marginal",
        3743,
        3755,
        "marginal benefit decays approximately exponentially",
    ),
    (
        "appxC_eq16_affine",
        3756,
        3767,
        "affine trend",
    ),
    (
        "appxC_eq17_sensitivity",
        3768,
        3778,
        "predicted sensitivity to effort",
    ),
    (
        "appxC_limitations",
        3779,
        3788,
        "local reward-level approximation",
    ),
    (
        "s_deployment_cost_quality",
        3487,
        3487,
        "deployment-time control over the cost",
    ),
]

# machine-checked terminology counts (case-sensitive) over the true source
TERMS = [
    "Controllable Reasoning Effort",
    "reasoning effort",
    "reasoning-effort",
    "scalar effort",
    "effort level",
    "Output tokens",
    "Terminal-Bench 2.1",
    "DeepSWE",
    "scaffold",
    "multi-turn agentic",
]

# numeric facts asserted in the manuscript, each tied to a line
NUMERIC_FACTS = [
    {
        "key": "effort_range_low",
        "value": 1,
        "line": 2048,
        "note": "system-prompt instruction declares effort range 1-100",
    },
    {
        "key": "effort_range_high",
        "value": 100,
        "line": 2048,
        "note": "system-prompt instruction declares effort range 1-100",
    },
    {
        "key": "api_tier_max_b",
        "value": 100,
        "line": 2107,
        "note": "Table 2: API tier max -> b = 100 (see also line 2455)",
    },
    {
        "key": "api_tier_high_b",
        "value": 75,
        "line": 2107,
        "note": "Table 2: API tier high -> b = 75",
    },
    {
        "key": "api_tier_low_b",
        "value": 50,
        "line": 2455,
        "note": "public API: low/high/max -> effort values 50/75/100",
    },
    {
        "key": "avg_pass1_at_b25_eight_bench",
        "value": 67.1,
        "line": 2434,
        "note": "eight reasoning-intensive benchmarks, effort 25",
    },
    {
        "key": "avg_pass1_at_b100_eight_bench",
        "value": 76.3,
        "line": 2434,
        "note": "eight reasoning-intensive benchmarks, effort 100",
    },
    {
        "key": "deepswe_pass1_at_b25",
        "value": 66.0,
        "line": 2435,
        "note": "DeepSWE v1.1, effort 25 -> 100",
    },
    {
        "key": "deepswe_pass1_at_b100",
        "value": 74.2,
        "line": 2435,
        "note": "DeepSWE v1.1, effort 25 -> 100",
    },
    {
        "key": "tb21_pass1_at_b25",
        "value": 82.4,
        "line": 2436,
        "note": "Terminal-Bench 2.1, effort 25 -> 100",
    },
    {
        "key": "tb21_pass1_at_b100",
        "value": 90.6,
        "line": 2436,
        "note": "Terminal-Bench 2.1, effort 25 -> 100",
    },
    {
        "key": "token_multiplier_low_to_max",
        "value": 2.5,
        "line": 2436,
        "note": "roughly 2.5x more output tokens (25 -> 100)",
    },
    {
        "key": "final_step_len_multiplier_lo",
        "value": 1.6,
        "line": 2441,
        "note": "final step to effort 100 lengthens agent trajectories 1.6-1.8x",
    },
    {
        "key": "final_step_len_multiplier_hi",
        "value": 1.8,
        "line": 2441,
        "note": "final step to effort 100 lengthens agent trajectories 1.6-1.8x",
    },
    {
        "key": "frontload_band_lo",
        "value": 60,
        "line": 2439,
        "note": "60-80 range recovers most of max accuracy at <half token budget",
    },
    {
        "key": "frontload_band_hi",
        "value": 80,
        "line": 2439,
        "note": "60-80 range recovers most of max accuracy at <half token budget",
    },
    {
        "key": "n_scaffold_families",
        "value": 6,
        "line": 2461,
        "note": "eight configurations from six scaffold families",
    },
    {
        "key": "n_scaffold_configs",
        "value": 8,
        "line": 2461,
        "note": "eight configurations from six scaffold families",
    },
    {
        "key": "matharena_apex_gain_pt",
        "value": 40.3,
        "line": 3277,
        "note": "+40.3 points (25.3%->65.6%) as effort increases, Fig 12 discussion",
    },
]


def main() -> int:
    lines = load_lines_lf(REPORT)
    raw = open(REPORT, "rb").read()
    n_page_breaks = raw.count(b"\x0c")
    text = raw.decode("utf-8")

    got_sha = sha256(REPORT)
    if EXPECTED_SHA256 and got_sha != EXPECTED_SHA256:
        print("FATAL: source hash drift: %s != %s" % (got_sha, EXPECTED_SHA256))
        return 3

    quotes = []
    for key, a, b, must in QUOTES:
        seg = lines[a - 1 : b]
        joined = "\n".join(seg)
        quotes.append(
            {
                "key": key,
                "line_start": a,
                "line_end": b,
                "text": joined,
                "required_substring": must,
                "substring_found": must in joined,
            }
        )

    missing = [q["key"] for q in quotes if not q["substring_found"]]
    if missing:
        print("FATAL: required substrings missing for: %s" % ", ".join(missing))
        return 2

    # form-feed trap check: the banned method must produce a DIFFERENT count
    n_lines_lf = len(lines)
    n_lines_splitlines = len(text.splitlines())
    trap_delta = n_lines_splitlines - n_lines_lf

    facts = []
    for f in NUMERIC_FACTS:
        line_txt = lines[f["line"] - 1]
        facts.append({**f, "line_text": line_txt})

    doc = {
        "source_id": "V41FLASH_TechReport",
        "source_path": REPORT_DOC_PATH,
        "source_resolved_via": REPORT_SOURCE,
        "source_sha256": sha256(REPORT),
        "title": "DeepSeek-V4.1-Flash: Pushing the Limits of KV Cache Compression",
        "line_convention": "split on \\n only; str.splitlines() banned",
        "n_lines_lf": n_lines_lf,
        "n_newlines_wc_l": raw.count(b"\n"),
        "n_lines_splitlines_banned": n_lines_splitlines,
        "splitlines_line_shift": trap_delta,
        "n_page_breaks": n_page_breaks,
        "term_counts": {t: text.count(t) for t in TERMS},
        "quotes": quotes,
        "numeric_facts": facts,
        "provenance": {
            "generator": "experiments/extract_v41_effort_evidence.py",
            "wrong_source_excluded": WRONG_SOURCE_NOTE,
        },
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=False)
        fh.write("\n")

    print("wrote", os.path.relpath(OUT, PAPER_DIR))
    print("  sha256(report)      =", doc["source_sha256"])
    print("  n_lines_lf          =", n_lines_lf)
    print("  n_lines(splitlines) =", n_lines_splitlines, "(banned; delta +%d)" % trap_delta)
    print("  n_page_breaks       =", n_page_breaks)
    print("  quotes              =", len(quotes), "all substrings found")
    print("  numeric_facts       =", len(facts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
