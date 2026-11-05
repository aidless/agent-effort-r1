# Failure modes

## FM-RATIO — a modeled cost ratio is not a measured agent gain

The number 3.44 is the fixed-middle row of the E2 allocation calculation. It is the baseline's modeled token cost divided by the cheapest of 8,820 grid points whose modeled success is at least that baseline's modeled success. The stored value at `e2.baselines.B2_fixed_mid.cost_ratio` in `results/arxiv_r1_descriptive.json` is 3.4402002147712176. `scripts/recompute_arxiv_r1.py` rebuilds it from the declared algebra in `results/e2_allocation.json`. That script does not read a Qwen trajectory.

Treating 3.44, or any other E2 cost ratio, as a measured reduction in agent cost, as a deployment saving, or as evidence that the allocation improved the recorded Qwen runs is a misreading. The 8B rates 0.9375 and 0.7500 and the 14B rates 1.0000 and 0.8750 are descriptive test-pass rates on eight authored tasks, with two nested menus and identical repeats. They do not estimate a population effect, and they were not produced by executing the E2 grid.

The same misreading applies to the token prices and to the unconstrained action combinations in that grid: they are assumptions. E1 and E1b latency samples are host measurements of primitives. They do not confirm those prices.

The missing runtime snapshot (`3326b513fa891cbd99e8c1ffcd986bd27d9dac73fd75dc7a3a31c0993db3f9e8`) and the missing prompts, responses, written programs, and final workspaces do not supply a way to convert the ratio into a measured gain. This repository does not invent those artifacts.
