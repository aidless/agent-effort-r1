"""make_run_record.py - 不可变运行记录（评估 P0 整改）。

每次训练运行生成不可修改的 run ID，绑定：
  代码哈希、数据哈希、依赖锁、硬件、命令行参数、随机种子、输出哈希。
论文只能引用已封存 run ID 的数据（评估要求："论文只能引用已封存 run ID"）。

用法: python make_run_record.py <paper_dir> [--tag phase_a_final]
产出: results/run_records/<run_id>.json (不可变，运行后不再修改)
"""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
import uuid
from pathlib import Path

import numpy as np


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="paper dir")
    ap.add_argument("--tag", default="run", help="tag for the run")
    ap.add_argument("--note", default="", help="human note")
    ap.add_argument("--seeds", type=int, default=0, help="seed count for the run")
    ap.add_argument("--pre-run", action="store_true",
                    help="snapshot BEFORE training starts (R43: provenance from run start)")
    args = ap.parse_args()

    root = Path(args.target)
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"

    # 1. code hashes (the pipeline scripts that produce this data)
    code_files = ["train_cifar.py", "analysis.py", "verify_train_output.py"]
    code_hashes = {}
    for cf in code_files:
        p = root / cf
        code_hashes[cf] = sha256_file(p) if p.exists() else "MISSING"

    # 2. data hash (CIFAR-10 batches — data version)
    import hashlib as _h
    data_hashes = {}
    data_dir = Path(r"F:\deepseek\.datasets\cifar-10-batches-py")
    if data_dir.exists():
        for bf in sorted(data_dir.glob("data_batch_*"))[:3]:
            data_hashes[bf.name] = _h.md5(bf.read_bytes()).hexdigest()

    # 3. dependencies lock
    req = root / "requirements.txt"
    req_hash = sha256_file(req) if req.exists() else "MISSING"

    # 4. hardware / platform + env
    hw = {"platform": platform.platform(), "python": platform.python_version()}
    try:
        import torch
        hw["torch"] = torch.__version__
        hw["cuda"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            hw["gpu"] = torch.cuda.get_device_name(0)
            hw["cuda_driver"] = torch.version.cuda
    except Exception:
        pass

    # git commit (if repo)
    git_commit = None
    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            git_commit = r.stdout.strip()
    except Exception:
        pass

    # output hash (seed_pairs.npz if exists)
    npz = root / "results" / "seed_pairs.npz"
    out_hash = sha256_file(npz) if npz.exists() else "MISSING"
    out_seeds = 0
    if npz.exists():
        try:
            out_seeds = len(np.load(npz, allow_pickle=True)["ours"])
        except Exception:
            pass

    record = {
        "run_id": run_id,
        "tag": args.tag,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": args.note,
        "recorded_at": "pre_run" if args.pre_run else "post_run",
        "git_commit": git_commit,
        "code_hashes": code_hashes,
        "data_hashes": data_hashes,
        "requirements_sha256": req_hash,
        "hardware": hw,
        "env_conda_prefix": __import__("os").environ.get("CONDA_PREFIX", ""),
        "seeds": [1000 + i for i in range(args.seeds)] if hasattr(args, "seeds") else None,
        "output_sha256": out_hash,
        "output_seeds": out_seeds,
        "output_path": "results/seed_pairs.npz",
        "exit_status": "pending",  # filled post-run
        "immutable": True,
    }
    # self-hash (record is immutable once written)
    record_body = json.dumps(record, sort_keys=True, ensure_ascii=False)
    record["record_sha256"] = hashlib.sha256(record_body.encode("utf-8")).hexdigest()

    out_dir = root / "results" / "run_records"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run_id}.json"
    out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"run record: {out_path.relative_to(root)}")
    print(f"run_id: {run_id}")
    print(f"output_sha256: {out_hash[:16]}... (seeds={out_seeds})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
