"""paper-writing-agent: judge-calibration gate (L1-4).

Enforces the Agent-as-a-Judge pre-calibration discipline (C1) before a judge
model's scores may be used in the final self-assessment (Phase 4.5 O2):

  - a calibration report JSON must exist for the judge+prompt combo,
  - FNR must be < --max-fnr (default 0.15) AND FPR < --max-fpr (default 0.10)
    (ARS v3.11 acceptance thresholds, research-kit judge_calibration_kit.md),
  - report sections carry "## Section: <count>" lines for regression.

Calibration JSON shape (produced by the research-kit protocol):
  {"judge": "deepseek-v4-flash", "prompt_version": "v3",
   "n_gold": 24, "fnr": 0.10, "fpr": 0.05,
   "gold_distribution_note": "同分布: 上一轮收敛论文定级评审"}

Usage:
  python check_judge_calibration.py <calibration.json>
       [--max-fnr 0.15] [--max-fpr 0.10] [--out report.md] [--fail-on-uncalibrated]

Exit 0 = report-only (or PASS with --fail-on-uncalibrated);
exit 1 = uncalibrated (missing file / missing fields / thresholds not met)
         with --fail-on-uncalibrated.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPORT_SECTIONS = [
    ("missing", "Missing calibration report"),
    ("fields", "Missing fields in report"),
    ("threshold_met", "Thresholds met (FNR/FPR)"),
    ("judge", "Judge identity"),
    ("n_gold", "Gold-set size"),
    ("prompt_version", "Prompt version"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="calibration report JSON path")
    ap.add_argument("--max-fnr", type=float, default=0.15)
    ap.add_argument("--max-fpr", type=float, default=0.10)
    ap.add_argument("--out", default=None)
    ap.add_argument("--fail-on-uncalibrated", action="store_true")
    args = ap.parse_args()

    p = Path(args.target)
    counts = {name: 0 for name, _ in REPORT_SECTIONS}
    notes = {name: [] for name, _ in REPORT_SECTIONS}
    judge = prompt_version = n_gold = "?"
    fnr = fpr = None

    if not p.exists():
        counts["missing"] = 1
        notes["missing"].append(f"calibration report not found: {p}")
    else:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            counts["fields"] = 1
            notes["fields"].append(f"invalid JSON: {exc}")
            data = None
        if data is not None:
            for key in ("judge", "prompt_version", "n_gold", "fnr", "fpr"):
                if key not in data or data[key] is None:
                    counts["fields"] += 1
                    notes["fields"].append(f"missing field '{key}'")
            judge = str(data.get("judge", "?"))
            prompt_version = str(data.get("prompt_version", "?"))
            n_gold = data.get("n_gold", "?")
            fnr = data.get("fnr")
            fpr = data.get("fpr")
            if counts["fields"] == 0:
                ok = (isinstance(fnr, (int, float)) and fnr < args.max_fnr
                      and isinstance(fpr, (int, float)) and fpr < args.max_fpr)
                counts["threshold_met"] = 1 if ok else 0
                if not ok:
                    notes["threshold_met"].append(
                        f"FNR={fnr} (max {args.max_fnr}), FPR={fpr} (max {args.max_fpr}) -> not met")
                counts["judge"] = 1
                notes["judge"].append(f"judge={judge}")
                counts["n_gold"] = 1
                notes["n_gold"].append(f"n_gold={n_gold}")
                counts["prompt_version"] = 1
                notes["prompt_version"].append(f"prompt_version={prompt_version}")

    lines = ["# Judge calibration gate report"]
    lines.append("\nTarget: `judge-calibration`")
    for name, title in REPORT_SECTIONS:
        lines.append(f"\n## {title}: {counts[name]}")
        for note in notes[name]:
            lines.append(f"- {note}")

    report = "\n".join(lines)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
    print(report)

    calibrated = (counts["missing"] == 0 and counts["fields"] == 0
                  and counts["threshold_met"] == 1)
    if args.fail_on_uncalibrated and not calibrated:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
