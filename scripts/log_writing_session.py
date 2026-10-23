#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""log_writing_session.py — 写作溯源日志(append-only JSONL, L2-6 provenance)
======================================================================

每次写作/修改动作追加一条不可覆盖记录 {ts, file, section, model, prompt_hash,
evidence_hash, note}; ts 为 ISO8601 UTC。--log 已存在时只追加, 绝不重写已有行。

用法:
  # 追加一条记录(写前校验字段齐全, 缺字段/空字段 → exit 1)
  python log_writing_session.py --log <path.jsonl> \
      --file <相对路径> --section <章节名> --model <模型名> \
      --prompt-hash <hash> --evidence-hash <hash> [--note <文本>]

  # 打印全部已有记录(每行 JSON)
  python log_writing_session.py --log <path.jsonl> --show

  # 该文件记录数(gate 用, 输出 "## <file>: <n>")
  python log_writing_session.py --log <path.jsonl> --check <file>

  # 报告模式: 写 <path> 并打印族内 "## <段落>: <计数>" 段
  python log_writing_session.py --log <path.jsonl> --report <path>
    报告段: Entries_total / Files_touched / Latest_ts / Sections_covered
    目标标签用 --report 文件名(不硬编码 'paper'); 机器可读 "## <段落>: <值>"

hash 由调用方计算: 建议复用 build_evidence_manifest.py 的 SHA-256 或 sha256sum。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_FIELDS = ("ts", "file", "section", "model", "prompt_hash", "evidence_hash", "note")
NONEMPTY_FIELDS = ("file", "section", "model", "prompt_hash", "evidence_hash")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_record(rec: dict):
    """字段齐全校验: 返回错误信息或 None(写入前调用)。"""
    missing = [k for k in REQUIRED_FIELDS if k not in rec]
    if missing:
        return "missing fields: " + ", ".join(missing)
    empty = [k for k in NONEMPTY_FIELDS if not isinstance(rec[k], str) or not rec[k].strip()]
    if empty:
        return "empty fields: " + ", ".join(empty)
    return None


def read_entries(log_path: Path):
    """读全部合法记录; 损坏行跳过并 WARN(append-only 日志不修不删)。"""
    entries = []
    if not log_path.exists():
        return entries
    with open(log_path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                print(f"WARN line {i}: not valid JSON, skipped", file=sys.stderr)
                continue
            if not isinstance(rec, dict):
                print(f"WARN line {i}: not an object, skipped", file=sys.stderr)
                continue
            entries.append(rec)
    return entries


def do_append(args) -> int:
    if not args.log:
        print("error: --log is required to append", file=sys.stderr)
        return 1
    required = {
        "file": args.file, "section": args.section, "model": args.model,
        "prompt_hash": args.prompt_hash, "evidence_hash": args.evidence_hash,
    }
    missing = [k for k, v in required.items() if v is None]
    if missing:
        print("error: missing required field(s): " + ", ".join(missing), file=sys.stderr)
        return 1
    rec = {
        "ts": now_iso(),
        "file": args.file,
        "section": args.section,
        "model": args.model,
        "prompt_hash": args.prompt_hash,
        "evidence_hash": args.evidence_hash,
        "note": args.note or "",
    }
    err = validate_record(rec)
    if err:
        print(f"error: refused to write — {err}", file=sys.stderr)
        return 1
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False))
    return 0


def do_show(args) -> int:
    if not args.log:
        print("error: --log is required for --show", file=sys.stderr)
        return 1
    log_path = Path(args.log)
    if not log_path.exists():
        return 0
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                print(line.rstrip("\n"))
    return 0


def do_check(args) -> int:
    if not args.log:
        print("error: --log is required for --check", file=sys.stderr)
        return 1
    if args.check is None:
        print("error: --check requires a <file> argument", file=sys.stderr)
        return 1
    entries = read_entries(Path(args.log))
    n = sum(1 for e in entries if e.get("file") == args.check)
    print(f"## {args.check}: {n}")
    return 0


def do_report(args) -> int:
    if not args.log:
        print("error: --log is required for --report", file=sys.stderr)
        return 1
    entries = read_entries(Path(args.log))
    files = {e.get("file") for e in entries if e.get("file")}
    sections = {e.get("section") for e in entries if e.get("section")}
    latest = max((e.get("ts", "") for e in entries if e.get("ts")), default="")
    lines = [
        "# Writing provenance report",
        "",
        f"- Target: `{Path(args.report).name}`",
        f"- log: `{args.log}`",
        f"- generated: {now_iso()}",
        "",
        f"## Entries_total: {len(entries)}",
        f"## Files_touched: {len(files)}",
        f"## Latest_ts: {latest or 'none'}",
        f"## Sections_covered: {len(sections)}",
        "",
    ]
    report = "\n".join(lines)
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="写作溯源日志(append-only JSONL)")
    ap.add_argument("--log", default=None, help="JSONL 日志路径")
    ap.add_argument("--file", default=None, help="写作/修改的相对文件路径")
    ap.add_argument("--section", default=None, help="章节名")
    ap.add_argument("--model", default=None, help="模型名")
    ap.add_argument("--prompt-hash", default=None, help="提示词 hash(调用方计算)")
    ap.add_argument("--evidence-hash", default=None, help="证据 hash(调用方计算)")
    ap.add_argument("--note", default="", help="备注(可选)")
    ap.add_argument("--show", action="store_true", help="打印全部记录(每行 JSON)")
    ap.add_argument("--check", metavar="FILE", default=None, help="打印该文件记录数(供 gate 解析)")
    ap.add_argument("--report", metavar="PATH", default=None, help="写报告并打印段计数")
    args = ap.parse_args()

    # A record is being appended when any record field is present; --report may
    # be combined with it (append first, then report the counts). --show and
    # --check stay mutually exclusive report modes.
    has_record = any((args.file, args.section, args.model, args.prompt_hash, args.evidence_hash))
    modes = sum(1 for m in (args.show, args.check) if m)
    if modes > 1:
        print("error: --show and --check are mutually exclusive", file=sys.stderr)
        return 1
    if has_record:
        rc = do_append(args)
        if rc != 0:
            return rc
        if args.report is not None:
            return do_report(args)
        return 0
    if args.show:
        return do_show(args)
    if args.check is not None:
        return do_check(args)
    if args.report is not None:
        return do_report(args)
    print("error: nothing to do — provide record fields, or one of --show/--check/--report", file=sys.stderr)
    return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
