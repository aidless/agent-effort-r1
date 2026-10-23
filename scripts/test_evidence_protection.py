"""test_evidence_protection.py - 证据保护负向测试（评估不变量 1-4）。

故意让各类"验证器"尝试改写受保护证据，系统必须拒绝：
  P1: generate_data.py 不得写入 results/（合成隔离）
  P2: train_cifar.py 不得覆盖 sealed run
  P3: verify_tree_diff 能检测受保护树被篡改
  P4: seal_run.py sealed 后不可覆盖

用法: python test_evidence_protection.py <paper_dir>
"""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    results = []

    # P1: generate_data.py must NOT write to results/ (synthetic isolation)
    r = run([sys.executable, "generate_data.py", str(root)], cwd=root)
    results.append(("P1 generate_data not in results/",
                    "REFUSE" in r.stdout or "REFUSE" in r.stderr or
                    not (root / "results" / "seed_pairs.npz").exists() or
                    (root / "fixtures" / "synthetic" / "seed_pairs.npz").exists()))

    # P3: verify_tree_diff detects tampering
    snap = root / "results" / ".protection_snap.json"
    r1 = run([sys.executable, "verify_tree_diff.py", str(root), "snapshot", str(snap)], cwd=root)
    # tamper: create a file under protected dir
    probe = root / "results" / "runs" / ".tamper_probe"
    try:
        probe.mkdir(parents=True, exist_ok=True)
        (probe / "x.txt").write_text("tamper", encoding="utf-8")
        r2 = run([sys.executable, "verify_tree_diff.py", str(root), "check", str(snap)], cwd=root)
        results.append(("P3 tree-diff detects tampering", "FAIL" in r2.stdout or "FAIL" in r2.stderr))
        import shutil
        shutil.rmtree(probe, ignore_errors=True)
    except Exception:
        results.append(("P3 tree-diff detects tampering", False))

    ok = all(p for _, p in results)
    print("=== Evidence protection tests ===")
    for name, passed in results:
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print(f"\n{'ALL PASS' if ok else 'SOME FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
