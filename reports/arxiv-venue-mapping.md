# arXiv venue mapping and scanner triage

The generic/TMLR scanner reports four anonymity failures for the confirmed real author block, name, affiliation and email. These are intended author metadata for arXiv, not anonymous-review defects; retained scanner output is not relabeled all-PASS. G9 looked under paper/evidence rather than project evidence, where protocol files exist. Original historical protocol is not a proof of a fully bound runtime; current-protocol-audit-r1.json discloses that gap.

The first hallucination scan used paper/ as its root, falsely treating scripts/recompute_arxiv_r1.py as missing. Rerun at the actual project root correctly finds that method file. Numeric coverage messages include inherited process documentation and rounded formatting and are informational, not a verification of every manuscript number. The 1014-field ledger and new recomputation supply the arithmetic checks; qualitative claims rely on independent review.

Style warnings match negated prove/guarantee statements, not affirmative evidence claims. No hidden p-value inference is introduced. Taint file absent means no explicit taint annotations detected, not proof of untainted historical experiments.
