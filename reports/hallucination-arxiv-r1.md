# Hallucination scan report (MLR-Bench four types)

Target: `paper`

## (E) Nonexistent Citations / incomplete bib entries
- none

## (E) Hallucinated Methodology: named method files missing
- scripts/recompute_arxiv_r1.py@main.tex

## (W) Mathematical Errors: inline arithmetic contradictions
- none

## (I) Faked Results surface: strong-claim count for LLM judge
- 0 strong-assertion phrases found; LLM judge must verify each against evidence

## (I) Numbers without ledger coverage
- 135 numeric literals not covered by CLAIM_LEDGER.md values (no CLAIM_LEDGER.md found)
+0.0625, -0.0714, -0.1875, -0.2143, -0.35, -0.50, -0.671, -1.00, 0, 0.00, 0.0000, 0.008, 0.025, 0.033, 0.052, 0.057, 0.065, 0.075, 0.101, 0.116, 0.20, 0.205, 0.2143, 0.25, 0.264, 0.28, 0.30, 0.5, 0.50, 0.5000, 0.512, 0.5320, 0.5478, 0.6250, 0.6305, 0.6633, 0.671, 0.6906, 0.7348, 0.7500, 0.76, 0.763, 0.8125, 0.8750, 0.912, 0.9375, 000, 1, 1.00, 1.0000, 1.018, 1.084, 1.1875, 1.305, 1.312, 1.941, 10, 100, 101, 12, 12.675, 120, 1200, 13, 14.429, 145, 1500, 16, 163, 17, 17353895263, 177.341, 18, 1914.169, 2, 2.0000, 2.05, 2.13, 2.264, 2.5

## Summary: 0 cite errors, 1 missing method files, 0 arithmetic warnings, 0 strong claims