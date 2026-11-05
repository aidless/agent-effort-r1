# Agent Effort R1

An optimal allocation under an assumed success function need not describe a tool-using language model.
This package places that calculation beside retained records from eight authored programming tasks.
It separates the assumption from the measurement and names what this tree cannot recompute.

## Hypothesis

E2 searches 8,820 allocation tuples under a declared success function and declared token prices. The fixed-middle comparison yields modeled cost ratio **3.44** (`results/arxiv_r1_descriptive.json` → `e2.baselines.B2_fixed_mid.cost_ratio`, 3.4402002147712176). That ratio, the gains, and the unconstrained action combinations are assumptions. They are not measured token savings on the Qwen runs. Reading them as agent gains is the failure mode in `FAILURE_MODES.md`.

## Measurement

Two retained Qwen3 AWQ case studies, 672 execution records each (`results/h4_real_llm_gx_qwen3_8b_persist.json`, `results/h4_real_llm_gx_qwen3_14b_persist.json`). On eight authored tasks, two nested menus, and identical repeats, the 8B records peak at **0.9375** at the low budget and are **0.7500** at the maximum; the 14B records peak at **1.0000** in the middle and are **0.8750** at the maximum. These are descriptive test-pass rates, not independent samples and not a test of the allocation model.

## Missing from this tree

- The H4 runtime whose retained script SHA-256 is `3326b513fa891cbd99e8c1ffcd986bd27d9dac73fd75dc7a3a31c0993db3f9e8`. The in-tree harness `experiments/h4_real_llm_gx.py` hashes to `7e2d56e7195074ab7c856d18054f59bf8e8557e1e89f90d39be879667adec157`. No matching snapshot is in this repository.
- Complete model responses, per-turn prompts, written programs, and final workspaces. Retained `model_turns` are action and attempt summaries.
- Model weights. Checkpoint file hashes are recorded; the weights are not redistributed.
- The novelty-gate scripts named in `gates_config.json` under `scripts/not_shipped/`. Those checks are marked `expected_fail`. They are not part of the offline recompute.

## Offline recompute

What this tree can recompute, with no network and no model call:

```bash
python3 scripts/recompute_arxiv_r1.py
python3 analysis.py .
pytest -q tests
```

`scripts/recompute_arxiv_r1.py` uses the standard library. It reads six retained files — `e1_tool_latency.json`, `e1b_agent_primitives.json`, `e2_allocation.json`, `e3_agent_loop.json`, `h4_real_llm_gx_qwen3_8b_persist.json`, `h4_real_llm_gx_qwen3_14b_persist.json` — and rewrites `results/arxiv_r1_descriptive.json` plus `paper/tables/{curves,tasks,allocation,latency,axis}.tex`.

`analysis.py` needs numpy and scipy. It reads the first four of those files and rewrites `results/stats.json`. It does not read the H4 files.

Counts checked by tests/test_recompute.py: pytest=7, analysis.py inputs=4, scripts/recompute_arxiv_r1.py inputs=6. CI runs `pytest -q tests`.

The tests do not rerun episodes. They require the six-file script to reproduce the committed descriptive JSON and five tables byte for byte, and `analysis.py` to reproduce `results/stats.json` to 12 decimal places. Clopper-Pearson tail digits past that cutoff are not bit-stable across SciPy builds, so the test restores the committed `results/stats.json` instead of replacing it. CI (`.github/workflows/static-checks.yml`) installs numpy 2.2.6, scipy 1.15.3, and pytest, then runs that same pytest command. There is no status badge.

Retained records still contain the rented-host workspace prefix used when they were written. Those strings were not rewritten, because they are part of the measurement record. Author-home paths were removed from process notes, gate commands, and two derived-stat `source_result` pointers; the `source_sha256` values on those pointers are unchanged.

## Environment

`requirements.txt` pins the remote execution host (Python 3.10.12, numpy 2.2.6, scipy 1.15.3, Pillow 11.1.0). Pillow is not imported by the two recompute commands. pytest is not in the lock.

`python3 scripts/build_evidence_manifest.py . --verify evidence_manifest.json` is not a green check: the manifest still lists `paper/main.aux`, `paper/main.log`, and `paper/main.out`, and those files are absent. They were not recreated.
