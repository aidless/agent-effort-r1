"""paper-writing-agent: rebuttal draft generator (N5).

Turns reviewer comments (REVIEW_R{n}_summary.md or an OpenReview-style review
list) into a structured REBUTTAL.md skeleton: per comment — restate the
concern, answer it, point to the evidence, point to the manuscript change.
The draft is HUMAN-CONFIRMED before submission (rebuttal is a protected-layer
document: it represents the authors to reviewers).

Input formats:
  --review REVIEW_R1_summary.md   parse issues from the adversarial review
  --json reviews.json             [{"severity","location","problem",...}]
  --text file.txt                 one comment per line starting with "- " or numbered

Output (default REBUTTAL.md at paper root):
  # Rebuttal (draft — confirm before submitting)
  ## R1  <severity> <location>
  - Reviewer concern: ...
  - Our response: [TODO]
  - Evidence: [TODO — file/field]
  - Manuscript change: [TODO — section/line]

Usage:
  python draft_rebuttal.py --review REVIEW_R1_summary.md --out REBUTTAL.md
  python draft_rebuttal.py --text comments.txt --out REBUTTAL.md

Exit 0 = draft written; exit 2 = no input / unreadable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def parse_review_md(path: Path) -> list[dict]:
    """Parse adversarial-review summary: both table rows (| ID | 位置 | 问题 | ... |)
    and bullet lines with [severity] prefix."""
    out = []
    in_table = False
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        # table row: | C1 | loc | problem | ... |  (5+ cells)
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) >= 3 and cells[0].startswith(("C", "M")):
                sev = "Critical" if cells[0].startswith("C") else "Major"
                out.append({"severity": sev, "location": cells[1], "problem": cells[2]})
            continue
        m = re.match(r"^\s*[-*]?\s*\[(Critical|Major|Minor|Nit)\]\s*(.*)$", line)
        if m:
            out.append({"severity": m.group(1), "problem": m.group(2).strip()})
    return out


def parse_json_reviews(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    out = []
    for it in data if isinstance(data, list) else data.get("reviews", data.get("issues", [])):
        if isinstance(it, dict):
            if "issues" in it:
                for sub in it["issues"]:
                    out.append({"severity": sub.get("severity", "Major"),
                                "problem": sub.get("problem", ""),
                                "location": sub.get("location", "")})
            else:
                out.append({"severity": it.get("severity", "Major"),
                            "problem": it.get("problem", ""),
                            "location": it.get("location", "")})
    return [o for o in out if o.get("problem")]


def parse_text(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^[-*]\s+(.*)$", s)
        out.append({"severity": "Major", "problem": (m.group(1) if m else s)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", default=None, help="adversarial review summary md")
    ap.add_argument("--json", dest="json_in", default=None, help="reviews json")
    ap.add_argument("--text", default=None, help="plain text comments")
    ap.add_argument("--out", default="REBUTTAL.md")
    args = ap.parse_args()

    comments: list[dict] = []
    if args.review:
        p = Path(args.review)
        if not p.exists():
            print(f"FAIL: review file not found: {p}", file=sys.stderr)
            return 2
        comments = parse_review_md(p)
    elif args.json_in:
        p = Path(args.json_in)
        if not p.exists():
            print(f"FAIL: json not found: {p}", file=sys.stderr)
            return 2
        comments = parse_json_reviews(p)
    elif args.text:
        p = Path(args.text)
        if not p.exists():
            print(f"FAIL: text not found: {p}", file=sys.stderr)
            return 2
        comments = parse_text(p)
    else:
        print("FAIL: one of --review/--json/--text required", file=sys.stderr)
        return 2

    if not comments:
        print("FAIL: no comments parsed from input", file=sys.stderr)
        return 2

    lines = ["# REBUTTAL (draft — human-confirm before submitting)",
             "",
             "> 由 draft_rebuttal.py 生成骨架。每条的 Response/Evidence/Change 均为",
             "> [TODO]，必须人工确认后定稿（rebuttal 代表作者面对审稿人，属保护层文档）。",
             ""]
    for i, c in enumerate(comments, 1):
        sev = c.get("severity", "Major")
        loc = c.get("location", "")
        lines.append(f"## R{i}  [{sev}] {loc}".rstrip())
        lines.append(f"- **Reviewer concern**: {c.get('problem', '')}")
        lines.append("- **Our response**: [TODO]")
        lines.append("- **Evidence**: [TODO — file/field, e.g. results/e1.json -> metric]")
        lines.append("- **Manuscript change**: [TODO — section/line]")
        lines.append("")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote rebuttal draft: {out} ({len(comments)} comments)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
