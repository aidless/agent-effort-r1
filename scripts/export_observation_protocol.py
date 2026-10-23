#!/usr/bin/env python3
"""Derive the H4 observation-protocol carrier from the harness source.

The manuscript now states that the budget is visible to the model in every turn. That is a
claim about source code, so its carrier must be read out of that source by a command, not
transcribed by hand: this script locates SYS / USER_TMPL / build_messages in
experiments/h4_real_llm_gx.py, records their line ranges, the template strings, and which of
the four budget keys and three used-count keys appear in the text the model is sent.

Usage: python3 scripts/export_observation_protocol.py [--out evidence/h4_observation_protocol.json]
"""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

SRC = "experiments/h4_real_llm_gx.py"
BUDGET_KEYS = ("max_steps", "max_tool_calls", "max_context_chars", "max_vision_probes")
STATE_KEYS = ("steps_used", "tools_used", "vision_used", "actions")


def block(text: str, name: str) -> tuple[int, int, str]:
    """Locate a parenthesised assignment NAME = ( ... ).

    Returns (start_line, end_line, body) with 1-based inclusive line numbers.
    """
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if re.match(rf"^{name}\s*=\s*\(", l)), None)
    if start is None:
        raise SystemExit(f"FAIL {name} not found as a parenthesised assignment in {SRC}")
    depth = 0
    for i in range(start, len(lines)):
        depth += lines[i].count("(") - lines[i].count(")")
        if depth == 0 and i > start:
            return start + 1, i + 1, "\n".join(lines[start:i + 1])
    raise SystemExit(f"FAIL unbalanced parentheses after {name} in {SRC}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="evidence/h4_observation_protocol.json")
    a = ap.parse_args()
    root = Path.cwd()
    src = root / SRC
    if not src.is_file():
        print(f"FAIL missing {SRC} (run from the run root)", file=sys.stderr)
        return 1
    text = src.read_text(encoding="utf-8")
    sys_s, sys_e, sys_body = block(text, "SYS")
    usr_s, usr_e, usr_body = block(text, "USER_TMPL")
    # build_messages is a def, not a parenthesised assignment, so it is located separately.
    lines = text.splitlines()
    b_start = next((i for i, l in enumerate(lines) if l.startswith("def build_messages")), None)
    if b_start is None:
        raise SystemExit(f"FAIL build_messages not found in {SRC}")
    b_end = next((i for i in range(b_start + 1, len(lines))
                  if lines[i].startswith(("def ", "class ", "@"))), len(lines))
    build_body = "\n".join(lines[b_start:b_end])

    sent = usr_body + build_body
    out = {
        "generated_by": "scripts/export_observation_protocol.py",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_file": SRC,
        "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "SYS_lines": [sys_s, sys_e],
        "USER_TMPL_lines": [usr_s, usr_e],
        "build_messages_lines": [b_start + 1, b_end],
        # Scalar copies: the ledger binder only value-checks plain numbers, and a value living
        # inside a list is not checked, so a row citing line numbers must cite these too.
        "SYS_first_line": sys_s,
        "USER_TMPL_first_line": usr_s,
        "USER_TMPL_last_line": usr_e,
        "build_messages_first_line": b_start + 1,
        "n_budget_keys_interpolated": len([k for k in BUDGET_KEYS if f"{{{k}}}" in usr_body]),
        "n_used_count_keys_interpolated": len([k for k in STATE_KEYS if k in build_body]),
        "user_template_text": usr_body,
        "budget_keys_in_message": [k for k in BUDGET_KEYS if k in sent],
        "used_count_keys_in_message": [k for k in STATE_KEYS if k in sent],
        "budget_visible_to_model": len([k for k in BUDGET_KEYS if f"{{{k}}}" in usr_body]) == 4,
        "history_truncation_chars": None,
    }
    m = re.search(r"history=\{?[^,]*\}?\)\[-(\d+):\]", build_body)
    if m:
        out["history_truncation_chars"] = int(m.group(1))
    if not out["budget_visible_to_model"]:
        print("FAIL the template does not interpolate all four budget keys; "
              "the manuscript's observation-protocol paragraph is unsupported", file=sys.stderr)
        return 1
    dest = root / a.out
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"budget_visible_to_model={out['budget_visible_to_model']} "
          f"USER_TMPL@{usr_s}-{usr_e} build_messages@{b_start+1}-{b_end} -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
