"""seal_run.py - 原子封存实验 run（评估不变量 2）。

把完成的实验输出从 work 区域原子发布到 results/runs/<run-id>/ 并标记 sealed。
sealed 后任何命令（含 --force）不得覆盖——只读不变量。

用法:
  python seal_run.py <paper_dir> <run_id> [--source results/seed_pairs.npz]
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="paper dir")
    ap.add_argument("run_id", help="run id from run_records")
    ap.add_argument("--source", default="results/seed_pairs.npz",
                    help="output file to seal")
    args = ap.parse_args()

    root = Path(args.target)
    run_dir = root / "results" / "runs" / args.run_id
    if run_dir.exists():
        status = run_dir / "STATUS.json"
        if status.exists():
            st = json.loads(status.read_text(encoding="utf-8"))
            if st.get("sealed"):
                print(f"REFUSE: run {args.run_id} already sealed; cannot overwrite")
                return 3
    run_dir.mkdir(parents=True, exist_ok=True)

    src = root / args.source
    if not src.exists():
        print(f"FAIL: source {args.source} not found")
        return 1

    # copy output + run record into sealed dir
    dst = run_dir / src.name
    shutil.copy2(src, dst)

    # run record
    rec_dir = root / "results" / "run_records"
    rec = None
    for f in rec_dir.glob(f"{args.run_id}.json"):
        rec = f
        break
    if rec:
        shutil.copy2(rec, run_dir / "run_record.json")

    # compute sealed manifest
    sealed_manifest = {}
    for p in sorted(run_dir.rglob("*")):
        if p.is_file() and p.name != "STATUS.json":
            sealed_manifest[p.relative_to(run_dir).as_posix()] = \
                hashlib.sha256(p.read_bytes()).hexdigest()

    status = {
        "run_id": args.run_id,
        "sealed": True,
        "sealed_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
        "source": args.source,
        "manifest": sealed_manifest,
        "immutable": True,
    }
    (run_dir / "STATUS.json").write_text(
        json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"sealed run {args.run_id} -> {run_dir.relative_to(root)}")
    print(f"sealed files: {list(sealed_manifest.keys())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
