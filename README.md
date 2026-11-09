# Agent Effort R1 — an allocation model vs a bounded agent evaluation

[![CI](https://github.com/aidless/agent-effort-r1/actions/workflows/static-checks.yml/badge.svg)](https://github.com/aidless/agent-effort-r1/actions/workflows/static-checks.yml)

An optimal resource allocation under an assumed success function need not
describe the behavior of a tool-using language model. This package examines
that gap with an illustrative five-axis allocation calculation (8,820 tuples
searched; modeled token-cost ratio **3.44** against a fixed-middle setting at
at least matched modeled success — both in
[results/e2_allocation.json](results/e2_allocation.json), summarised in
[results/stats.json](results/stats.json)) and retained records from eight authored
programming tasks.

## What is measured vs assumed

- **Two Qwen3 AWQ case studies** (8B and 14B, 672 retained execution records
  each — [results/h4_real_llm_gx_qwen3_8b.json](results/h4_real_llm_gx_qwen3_8b.json),
  [results/h4_real_llm_gx_qwen3_14b_persist.json](results/h4_real_llm_gx_qwen3_14b_persist.json))
  over five coupled budget settings:
  - 8B peaks at **0.9375** at the low budget, **0.7500** at the maximum
    ([results/h4_derived_stats.json](results/h4_derived_stats.json), `iso_curve`)
  - 14B peaks at **1.0000** in the middle, **0.8750** at the maximum
    ([results/h4_derived_stats_14b.json](results/h4_derived_stats_14b.json), `iso_curve`)
- **The allocation model's gains, token prices and unconstrained action
  combinations are assumptions**, not measured deployment benefits — the
  paper separates the two explicitly.
- **Interpretation limits are audited, not footnoted**: success requires an
  explicit passing test within budget; the supplied scaffold repeats the
  original starter and truncates history; structural probes are not visual
  understanding. Missing generated code and an unresolved runtime-script
  fingerprint are recorded rather than fabricated.

## Honest scope

Descriptive rates on eight tasks with two nested menus and identical repeated
outcomes — **not** independent samples establishing a general decline. The
manuscript (11 pages, `paper/`) is a preprint, not peer reviewed, with no
external submission claimed.

## Measured results (retained records)

Real measured/recomputed values — latency and E2 from [results/stats.json](results/stats.json)
(offline recompute), Qwen3 peaks from the `h4_derived_stats*` files linked below:

- Tool latency samples: `T1_shell_simple` 120 runs mean **1.305 ms** (p95 **1.422 ms**),
  `T2_shell_command` 90 runs mean **7.129 ms** (p95 **8.109 ms**);
  `P2_screenshot_capture` 30 runs with **n_ok = 0** (all failed, recorded, not fabricated).
  Source: [results/e1_tool_latency.json](results/e1_tool_latency.json), summarised under
  `E1_E1b_latency` in [results/stats.json](results/stats.json).
- E2 allocation grid: **8,820** tuples; baseline modeled success B1_all_max **0.6906**,
  B2_fixed_mid **0.5320**, B3_reason_only_max **0.5478**, B4_agent_only_max **0.6633**
  ([results/e2_allocation.json](results/e2_allocation.json), `baselines`;
  also `E2_allocation` in [results/stats.json](results/stats.json)).
- Cost ratio (vs fixed-middle, at matched modeled success): **3.44**
  ([results/e2_allocation.json](results/e2_allocation.json),
  `matched_comparisons.vs_fixed_mid`; also `E2_allocation.vs_fixed_mid` in
  [results/stats.json](results/stats.json)).
- Qwen3 peaks: 8B **0.9375** (low budget) / **0.7500** (max)
  ([results/h4_derived_stats.json](results/h4_derived_stats.json), `iso_curve`);
  14B **1.0000** (middle) / **0.8750** (max)
  ([results/h4_derived_stats_14b.json](results/h4_derived_stats_14b.json), `iso_curve`).

**Fail-closed (real):** the retained H4 runtime-script fingerprint **does not match**
the supplied harness snapshot, and the exact runtime snapshot **was not recovered** —
so the protocol reports the supplied implementation while the numbers describe
retained records. This is **recorded, not fabricated**: missing generated code and an
unresolved runtime-script fingerprint are explicitly listed (`STATE_SNAPSHOT.md`) rather
than silently treated as verified. Evidence is SHA-256-anchored in `CLAIM_LEDGER.md` +
`evidence_manifest.json`; `pytest -q tests` binds the 3.44 ratio to the published JSON.

## Quick start

```bash
python3 -m pip install -r requirements.txt   # numpy 2.2.6 / scipy 1.15.3 (pin)
python3 analysis.py                          # recompute every table (offline, no LLM)
pytest -q tests                              # 2 deterministic recompute checks
```

No network and no model calls are needed to recompute the reported numbers —
all inputs are retained in `results/`.

## Recompute

```bash
python3 analysis.py        # retained-data recomputation, six input files
pytest -q tests            # byte-match recomputation + headline contract
```

Evidence chain: `CLAIM_LEDGER.md` + `evidence_manifest.json` (SHA-256).
`STATE_SNAPSHOT.md` records the current revision state, including what could
not be resolved.

The tests are deterministic and offline. They do not rerun model episodes;
they require the canonical recomputation to reproduce the same parsed
`results/stats.json` content to 12 decimal places across supported Python and
SciPy versions and bind the
README's 3.44 ratio to the published descriptive JSON rather than to an
intermediate allocation file.

## Environment

`requirements.txt` is a pinned environment lock (numpy 2.2.6, scipy 1.15.3,
Pillow 11.1.0, ...); its header records the remote execution host that
produced the retained records (Python 3.10.12, 96 vCPU). `python3
analysis.py` recomputes every table from the six retained input files with
no network access and no LLM calls.

## Repository layout

```
analysis.py             retained-data recomputation (six input files → results/stats.json)
results/stats.json      canonical recomputed tables (incl. the 3.4402 cost ratio)
experiments/            E1..E3 + H4 measurement/analysis scripts (the runs that produced the records)
scripts/                gates, scanners, claim-ledger verification (submission hardening)
tests/test_recompute.py byte-match recomputation + headline contract (deterministic, offline)
CLAIM_LEDGER.md         every reported number → evidence/ claim (SHA-256 anchored)
evidence_manifest.json  SHA-256 of every evidence file (self excluded)
paper/                  11-page manuscript (preprint, not peer reviewed)
STATE_SNAPSHOT.md       current revision state incl. what could not be resolved
```
