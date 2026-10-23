"""paper-writing-agent: judge-output schema validator + tolerant parser (G6).

Unified validation for LLM-judge JSON outputs used across adversarial review
and rebuttal simulation. Judges drift (markdown fences, trailing commas,
single quotes, extra keys, missing fields); a drifted output silently breaks
scoring. This tool:

  1. extracts JSON from the response (multi-regex fallback: bare JSON,
     fenced ```json, {..} span extraction, [..] array),
  2. validates against a schema (required fields, enums, types),
  3. normalizes common drift (trailing commas, single-quoted keys, NaN/Infinity,
     control chars),
  4. exits non-zero on invalid output so the caller counts it as a judge
     failure that STAYS IN THE DENOMINATOR (never silently dropped).

Schemas (--schema):
  review     adversarial-review issue list:
             {role, verdict(acceptable|minor-revision|needs-major-revision),
              prevClosure, summary, issues:[{severity(Critical|Major|Minor|Nit),
              location, problem, expectation, evidenceLink}]}
  rebuttal   rebuttal simulation:
             {completion: 0|1, satisfaction: 0|1, questions:[str],
              feedback: str}
  score      generic numeric score with reason:
             {score: number, reason: str, confidence?: number}

Usage:
  python validate_judge_output.py --schema review --input out.json
  python validate_judge_output.py --schema rebuttal --input out.json --out report.md
  echo '{"completion":1,...}' | python validate_judge_output.py --schema rebuttal

Exit 0 = valid; exit 1 = invalid (parse failed or schema violation).
"""
from __future__ import annotations

import argparse
import json
import re
import sys

REVIEW_ISSUE_REQ = ["severity", "location", "problem", "expectation", "evidenceLink"]
REVIEW_REQ = ["role", "verdict", "prevClosure", "summary", "issues"]
REBUTTAL_REQ = ["completion", "satisfaction", "questions", "feedback"]
SCORE_REQ = ["score", "reason"]

SEVERITIES = {"Critical", "Major", "Minor", "Nit"}
VERDICTS = {"acceptable", "minor-revision", "needs-major-revision"}

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def strip_json_markers(text: str) -> str:
    """Remove common wrapping junk: code fences, prose around JSON."""
    text = text.strip()
    # code fence first (most reliable)
    m = _JSON_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    # bare object/array span
    for pat in (_JSON_OBJECT_RE, _JSON_ARRAY_RE):
        m = pat.search(text)
        if m:
            return m.group(0).strip()
    return text


def fix_common_drift(text: str) -> str:
    """Normalize trailing commas, single-quoted keys, NaN/Infinity, BOM."""
    text = text.lstrip("\ufeff")
    text = re.sub(r",\s*([}\]])", r"\1", text)                     # trailing commas
    text = re.sub(r"'([^']*)'\s*:", r'"\1":', text)                 # single-quoted keys
    text = re.sub(r":\s*'([^']*)'", r':"\1"', text)                 # single-quoted values
    text = re.sub(r"\bNaN\b", "null", text)
    text = re.sub(r"\bInfinity\b", "null", text)
    return text


def parse_json_tolerant(text: str):
    """Try strict parse, then drift-fixed parse; return (obj, mode) or (None, err)."""
    raw = strip_json_markers(text)
    try:
        return json.loads(raw), "strict"
    except json.JSONDecodeError as e1:
        fixed = fix_common_drift(raw)
        try:
            return json.loads(fixed), "drift-fixed"
        except json.JSONDecodeError as e2:
            return None, f"parse failed: strict={e1}; drift-fixed={e2}"


def validate_schema(obj, schema: str) -> list[str]:
    """Return list of violations (empty = valid)."""
    if not isinstance(obj, dict):
        return [f"top-level must be an object, got {type(obj).__name__}"]
    req = {"review": REVIEW_REQ, "rebuttal": REBUTTAL_REQ, "score": SCORE_REQ}[schema]
    missing = [k for k in req if k not in obj]
    if missing:
        return [f"missing required field(s): {missing}"]
    if schema == "review":
        v = obj.get("verdict")
        if v not in VERDICTS:
            return [f"verdict {v!r} not in {sorted(VERDICTS)}"]
        issues = obj.get("issues")
        if not isinstance(issues, list):
            return ["issues must be a list"]
        out = []
        for i, it in enumerate(issues):
            if not isinstance(it, dict):
                out.append(f"issues[{i}] not an object")
                continue
            for k in REVIEW_ISSUE_REQ:
                if k not in it:
                    out.append(f"issues[{i}] missing {k!r}")
            if it.get("severity") not in SEVERITIES:
                out.append(f"issues[{i}].severity {it.get('severity')!r} invalid")
        return out
    if schema == "rebuttal":
        out = []
        for k in ("completion", "satisfaction"):
            if obj.get(k) not in (0, 1):
                out.append(f"{k} must be 0 or 1, got {obj.get(k)!r}")
        if not isinstance(obj.get("questions"), list):
            out.append("questions must be a list")
        return out
    if schema == "score":
        if not isinstance(obj.get("score"), (int, float)) or isinstance(obj.get("score"), bool):
            return [f"score must be numeric, got {obj.get('score')!r}"]
        if not isinstance(obj.get("reason"), str):
            return ["reason must be a string"]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", choices=["review", "rebuttal", "score"], required=True)
    ap.add_argument("--input", default=None, help="JSON/text file with judge output (default: stdin)")
    ap.add_argument("--out", default=None, help="report path")
    args = ap.parse_args()

    if args.input:
        text = open(args.input, encoding="utf-8-sig").read()
    else:
        text = sys.stdin.read()

    obj, mode = parse_json_tolerant(text)
    if obj is None:
        lines = ["# Judge output validation ({})".format(args.schema),
                 "", "## Status: INVALID (parse failed)", "- {}".format(mode),
                 "", "## Rule: invalid judge output counts as a judge failure and",
                 "stays in the denominator (never silently dropped)."]
        report = "\n".join(lines)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(report)
        print(report)
        return 1

    violations = validate_schema(obj, args.schema)
    status = "VALID" if not violations else "INVALID"
    lines = ["# Judge output validation ({})".format(args.schema),
             "", "## Status: {} (parse: {})".format(status, mode),
             ""]
    if violations:
        lines.append("## Violations: {}".format(len(violations)))
        lines += ["- {}".format(v) for v in violations]
        lines += ["", "## Rule: invalid judge output counts as a judge failure and",
                  "stays in the denominator (never silently dropped)."]
    else:
        lines.append("## Violations: 0")
    report = "\n".join(lines)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(report)
    print(report)
    return 0 if status == "VALID" else 1


if __name__ == "__main__":
    sys.exit(main())
