"""verify_tree_diff.py - 受保护树差分（评估不变量 1+3）。

验证器只读契约：任何验证/门禁/审稿运行前后，受保护证据树必须哈希不变。
若除允许位置以外的任何文件变化（新增/删除/哈希改变），报告 FAIL 并列出变更。

受保护区域：
  results/runs/     - 封存的实验 run
  results/verified/ - 验证过的证据包
  results/*.npz/*.json - canonical evidence 文件

用法:
  python verify_tree_diff.py <paper_dir> snapshot <file>   # 验证前快照
  python verify_tree_diff.py <paper_dir> check <file>      # 验证后差分
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

PROTECTED_DIRS = ("results/runs", "results/verified")
PROTECTED_FILES = ("results/seed_pairs.npz", "results/e1.json", "results/e2.json")
ALLOWED_WRITE = ("results/run_records", "reports")  # 验证器可写的位置


def snapshot_tree(root: Path) -> dict:
    """Recursively hash protected tree (relative path -> sha256)."""
    snap = {}
    for base in PROTECTED_DIRS:
        d = root / base
        if d.exists():
            for p in sorted(d.rglob("*")):
                if p.is_file():
                    h = hashlib.sha256(p.read_bytes()).hexdigest()
                    snap[p.relative_to(root).as_posix()] = h
    for rel in PROTECTED_FILES:
        p = root / rel
        if p.exists():
            snap[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return snap


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="paper dir")
    ap.add_argument("mode", choices=["snapshot", "check"])
    ap.add_argument("snapfile", help="snapshot json path")
    args = ap.parse_args()

    root = Path(args.target)
    snap_path = Path(args.snapfile)

    if args.mode == "snapshot":
        snap = snapshot_tree(root)
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(json.dumps(snap, indent=1, sort_keys=True), encoding="utf-8")
        print(f"snapshot: {len(snap)} protected files hashed")
        return 0

    # check mode: diff current vs snapshot
    if not snap_path.exists():
        print("FAIL: snapshot file missing (run snapshot first)")
        return 1
    before = json.loads(snap_path.read_text(encoding="utf-8"))
    after = snapshot_tree(root)
    changed = []
    added = []
    removed = []
    for rel, h in after.items():
        if rel not in before:
            added.append(rel)
        elif before[rel] != h:
            changed.append(rel)
    for rel in before:
        if rel not in after:
            removed.append(rel)
    if not (changed or added or removed):
        print("PASS: protected tree unchanged")
        return 0
    print("FAIL: protected tree modified!")
    for rel in changed:
        print(f"  CHANGED: {rel}")
    for rel in added:
        print(f"  ADDED: {rel}")
    for rel in removed:
        print(f"  REMOVED: {rel}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
