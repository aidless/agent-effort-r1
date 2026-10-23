"""paper-writing-agent: project switcher (N3).

Multi-project isolation for the paper agent. Each paper project lives under
<projects_root>/<name>/; switching records the active project and loads its
context digest (manifest summary, ledger state, latest round) so sessions
never confuse projects.

State file: <projects_root>/.active_project.json  {name, switched_at, cwd}

Usage:
  python switch_project.py list                      # list projects
  python switch_project.py <name>                    # switch active project
  python switch_project.py init <name> --dir <path>  # register an existing dir

Exit 0 = ok; exit 2 = unknown project / init without --dir.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECTS_ROOT = Path(r"F:\deepseek\papers") if Path(r"F:\deepseek\papers").exists() else Path("papers")
STATE = PROJECTS_ROOT / ".active_project.json"


def _list_projects() -> list[Path]:
    return sorted([p for p in PROJECTS_ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")])


def _digest(proj: Path) -> list[str]:
    lines = [f"# Project: {proj.name}", ""]
    manifest = proj / "evidence_manifest.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8-sig"))
            files = data.get("files", [])
            lines.append(f"evidence manifest: {len(files)} files")
        except (OSError, json.JSONDecodeError):
            lines.append("evidence manifest: unreadable")
    ledger = proj / "CLAIM_LEDGER.md"
    if ledger.exists():
        n = sum(1 for l in ledger.read_text(encoding="utf-8", errors="ignore").splitlines()
                if l.startswith("| C") and "template" not in l)
        lines.append(f"claim ledger: ~{n} entries")
    rounds = sorted(proj.glob("ROUND_R*.md"),
                    key=lambda p: int(p.stem.replace("ROUND_R", "")))
    if rounds:
        latest = rounds[-1]
        lines.append(f"latest round: {latest.name}")
    assess = proj / "SELF_ASSESSMENT.md"
    if assess.exists():
        lines.append("SELF_ASSESSMENT: present")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", nargs="?", default="list",
                    help="list | <name> | init <name> --dir <path>")
    ap.add_argument("--dir", default=None, help="for init: existing project dir to register")
    args = ap.parse_args()

    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)

    if args.action == "list":
        projects = _list_projects()
        print(f"Projects under {PROJECTS_ROOT}:")
        if STATE.exists():
            try:
                cur = json.loads(STATE.read_text(encoding="utf-8-sig"))
                print(f"  active: {cur.get('name', '?')} (switched {cur.get('switched_at', '?')})")
            except (OSError, json.JSONDecodeError):
                print("  active: (state unreadable)")
        for p in projects:
            print(f"  - {p.name}")
        return 0

    if args.action == "init":
        name = args.dir and Path(args.dir).name
        if not name:
            print("FAIL: init requires --dir <path>", file=sys.stderr)
            return 2
        target = PROJECTS_ROOT / name
        if not target.exists():
            print(f"FAIL: source dir not found: {args.dir}", file=sys.stderr)
            return 2
        # register by pointer file (do not move the real project)
        target.mkdir(exist_ok=True)
        (target / ".source").write_text(str(Path(args.dir).resolve()), encoding="utf-8")
        print(f"registered project: {name} -> {args.dir}")
        args.action = name

    # switch to <name>
    name = args.action
    proj = PROJECTS_ROOT / name
    if not proj.is_dir() and not (proj / ".source").exists():
        print(f"FAIL: unknown project: {name} (list to see available)", file=sys.stderr)
        return 2
    state = {"name": name,
             "switched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "cwd": str(proj)}
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n".join(_digest(proj)))
    print("\nswitched active project ->", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
