# Agent Effort R1 — an allocation model vs a bounded agent evaluation

An optimal resource allocation under an assumed success function need not
describe the behavior of a tool-using language model. This package examines
that gap with an illustrative five-axis allocation calculation (8,820 tuples
searched; modeled token-cost ratio **3.44** against a fixed-middle setting at
at least matched modeled success) and retained records from eight authored
programming tasks.

## What is measured vs assumed

- **Two Qwen3 AWQ case studies** (8B and 14B, 672 retained execution records
  each) over five coupled budget settings:
  - 8B peaks at **0.9375** at the low budget, **0.7500** at the maximum
  - 14B peaks at **1.0000** in the middle, **0.8750** at the maximum
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
`results/stats.json` content across supported Python versions and bind the
README's 3.44 ratio to the published descriptive JSON rather than to an
intermediate allocation file.

## Environment

`requirements.txt` is a pinned environment lock (numpy 2.2.6, scipy 1.15.3,
Pillow 11.1.0, ...); its header records the remote execution host that
produced the retained records (Python 3.10.12, 96 vCPU). `python3
analysis.py` recomputes every table from the six retained input files with
no network access and no LLM calls.
