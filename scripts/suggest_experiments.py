"""paper-writing-agent: experiment-suggestion generator (G4).

Turns adversarial-review Critical/Major findings + claim-ledger gaps into a
structured "what experiment to add and why" list, so a revision round is not
just re-wording but a traceable experiment-completion plan.

Inputs (any combination, at least one required):
  --review    REVIEW_R{n}_summary.md / review JSON with Critical/Major issues
  --ledger    CLAIM_LEDGER.md (claims with inconclusive status = evidence gaps)
  --manifest  evidence_manifest.json (what evidence exists)
  --fm        failure-modes library (references/failure-modes.md), optional

Output: JSON + markdown table, each suggestion carries:
  - trigger: the review issue / ledger gap that demands it
  - experiment: what to run (design sketch)
  - evidence_target: which claim it would upgrade (inconclusive -> verified)
  - min_cost: minimal cost estimate (runs/seeds/GPU-hours, qualitative)
  - priority: P0 (review-blocking) / P1 (strengthening)

The generator is deterministic (no LLM): it classifies review issues by known
patterns (missing baseline / missing ablation / no CI / no power analysis /
uncontrolled variable / no generalization check) and maps each to a canonical
experiment template. Unknown patterns are listed as "manual review needed".

Usage:
  python suggest_experiments.py --review REVIEW_R1_summary.md --ledger CLAIM_LEDGER.md --out reports/experiment_suggestions.md
  python suggest_experiments.py --ledger CLAIM_LEDGER.md --out out.json

Exit 0 = suggestions produced; exit 2 = no inputs / unreadable files.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# pattern -> (canonical experiment template, priority, evidence_target note)
PATTERNS = [
    (re.compile(r"基线|baseline|对照", re.I),
     "add a stronger baseline (best published method on this benchmark) with equal budget",
     "P0", "upgrades any 'outperforms X' claim to a verified comparison"),
    (re.compile(r"消融|ablation", re.I),
     "run a component ablation: remove each component one at a time, keep budget/seed fixed",
     "P0", "upgrades 'component X matters' claims; FM-23 discipline: one variable per run"),
    (re.compile(r"置信区间|CI|confidence interval", re.I),
     "report bootstrap CI (stats.bootstrap_ci, n_boot>=1000) for every headline metric",
     "P0", "turns point estimates into interval claims"),
    (re.compile(r"功效|power|样本量|sample size", re.I),
     "run power_analysis.py (paired/two-sample t, McNemar, ...) and state alpha/power/effect/N in Methods",
     "P0", "justifies N; upgrades the Methods sample-size sentence"),
    (re.compile(r"泛化|generaliz|跨数据集|cross-dataset|外推", re.I),
     "add a held-out dataset/domain check with the same pipeline (no retuning)",
     "P1", "upgrades 'generalizes to X' claims"),
    (re.compile(r"混淆|confound|未控制|控制变量", re.I),
     "design a controlled comparison: vary only the target factor, freeze all else (seeds, budget, prompts)",
     "P0", "upgrades causal-sounding claims; equal-budget discipline E051"),
    (re.compile(r"种子|seed|方差|variance", re.I),
     "rerun with >=5 seeds and report mean±std (summarize_multi_seed) instead of a single run",
     "P1", "upgrades single-seed results; seed-count consistency across text/tables"),
    (re.compile(r"成本|cost|预算|budget", re.I),
     "report per-arm cost (llm_client cost_from_calls_log) so comparisons are equal-budget",
     "P1", "upgrades fairness of comparisons; E045/E051 discipline"),
    (re.compile(r"错误率|误差分析|failure|error analysis", re.I),
     "add a failure-mode breakdown: which inputs fail, in what proportion (error matrix)",
     "P1", "upgrades 'works well' to 'fails in these identifiable cases'; E053"),
    (re.compile(r"新颖|novelty|新意", re.I),
     "add a positioning experiment against the closest prior work with matched setup",
     "P1", "upgrades novelty claims from assertion to measured difference"),
]

UNKNOWN_PREFIX = "[MANUAL REVIEW NEEDED]"


def parse_review(path: Path) -> list[str]:
    """Extract issue descriptions from a review summary (md or json)."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
            issues = data.get("issues") or data.get("reviews") or []
            out = []
            for it in issues:
                if isinstance(it, dict):
                    if "issues" in it:
                        for sub in it["issues"]:
                            out.append(str(sub.get("problem", "")))
                    else:
                        out.append(str(it.get("problem", "")))
                elif isinstance(it, str):
                    out.append(it)
            return [s for s in out if s]
        except json.JSONDecodeError:
            pass
    # markdown/plain text: lines with severity keywords
    lines = []
    for line in text.splitlines():
        if re.search(r"(Critical|Major)", line) and len(line.strip()) > 15:
            lines.append(line.strip())
    return lines


def parse_ledger_gaps(path: Path) -> list[str]:
    """Claims with inconclusive status = evidence gaps that experiments can close."""
    gaps = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "inconclusive" in line.lower() and "|" in line:
            cells = [c.strip() for c in line.split("|")]
            if len(cells) >= 6:
                gaps.append(f"ledger {cells[1]}: {cells[2][:120]}")
    return gaps


def classify(text: str):
    for pat, tmpl, prio, note in PATTERNS:
        if pat.search(text):
            return tmpl, prio, note
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", default=None, help="review summary (md/json)")
    ap.add_argument("--ledger", default=None, help="CLAIM_LEDGER.md")
    ap.add_argument("--manifest", default=None, help="evidence_manifest.json (optional)")
    ap.add_argument("--out", default=None, help="output path (md or .json)")
    args = ap.parse_args()

    triggers: list[str] = []
    if args.review:
        p = Path(args.review)
        if not p.exists():
            print(f"FAIL: review file not found: {p}", file=sys.stderr)
            return 2
        triggers += [f"review: {t}" for t in parse_review(p)]
    if args.ledger:
        p = Path(args.ledger)
        if not p.exists():
            print(f"FAIL: ledger not found: {p}", file=sys.stderr)
            return 2
        triggers += parse_ledger_gaps(p)
    if not triggers:
        print("FAIL: no triggers found (empty review / no inconclusive ledger entries)", file=sys.stderr)
        return 2

    suggestions = []
    for t in triggers:
        m = classify(t)
        if m is None:
            suggestions.append({"trigger": t, "experiment": UNKNOWN_PREFIX,
                                "priority": "?", "note": "manual review needed"})
            continue
        tmpl, prio, note = m
        suggestions.append({"trigger": t[:160], "experiment": tmpl,
                            "priority": prio, "note": note})

    # dedupe by experiment template
    seen = {}
    for s in suggestions:
        key = s["experiment"]
        if key not in seen:
            seen[key] = {"experiment": key, "priority": s["priority"],
                         "note": s["note"], "triggers": []}
        seen[key]["triggers"].append(s["trigger"])
    rows = list(seen.values())
    rows.sort(key=lambda r: 0 if r["priority"] == "P0" else 1)

    if args.out and str(args.out).endswith(".json"):
        Path(args.out).write_text(json.dumps({"suggestions": rows,
                                              "total_triggers": len(triggers),
                                              "unknown": sum(1 for s in rows if s["experiment"] == UNKNOWN_PREFIX)},
                                             indent=2, ensure_ascii=False), encoding="utf-8")
    elif args.out:
        lines = ["# Experiment suggestions (G4, generated from review/ledger gaps)",
                 "", f"Triggers scanned: {len(triggers)} | Suggestions: {len(rows)}",
                 "", "| Priority | Experiment | Evidence target | Triggers |",
                 "|---|---|---|---|"]
        for r in rows:
            trig = "; ".join(r["triggers"][:2]) + ("..." if len(r["triggers"]) > 2 else "")
            lines.append(f"| {r['priority']} | {r['experiment']} | {r['note']} | {trig} |")
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
