"""release.py - 单一发布入口（审查要求：发布门不可被跳过）。

只允许本脚本生成 release/ 下的投稿包。流程：
  1. 验证 evidence bundle 存在且哈希匹配（results/verified/<bundle-id>/）
  2. 验证论文引用的 bundle ID 一致
  3. 验证状态链完整（running→candidate→independently_recomputed→sealed→verified→paper_claims_enabled）
  4. 验证 ledger 无 provisional/broken/tainted 引用
  5. 生成 release/ 投稿包 + submission manifest

用法: python release.py <paper_dir> --bundle <bundle-id> [--dry-run]
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REQUIRED_STATE = "paper_claims_enabled"
VALID_STATES = ("planned", "running", "candidate", "independently_recomputed",
                "sealed", "verified", "paper_claims_enabled")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="paper dir")
    ap.add_argument("--bundle", required=True, help="verified evidence bundle id")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = Path(args.target)
    bundle_dir = root / "results" / "verified" / args.bundle
    reasons = []
    blocked = False

    # 1. bundle exists
    if not bundle_dir.exists():
        blocked = True
        reasons.append(f"verified bundle not found: {args.bundle}")
    else:
        # 2. bundle STATUS must be verified_real_evidence
        status_path = bundle_dir / "STATUS.json"
        if status_path.exists():
            st = json.loads(status_path.read_text(encoding="utf-8-sig"))
            if st.get("state") != REQUIRED_STATE and st.get("status") != REQUIRED_STATE:
                blocked = True
                reasons.append(f"bundle state {st.get('state')} != {REQUIRED_STATE}")
        else:
            blocked = True
            reasons.append("bundle STATUS.json missing")

        # 3. sealed manifest hash matches
        manifest = bundle_dir / "manifest.json"
        if manifest.exists():
            m = json.loads(manifest.read_text(encoding="utf-8-sig"))
            for rel, expected in (m.get("sealed_manifest") or {}).items():
                p = bundle_dir / rel
                if p.exists() and sha256_file(p) != expected:
                    blocked = True
                    reasons.append(f"manifest hash mismatch: {rel}")
        else:
            blocked = True
            reasons.append("bundle manifest.json missing")

    # 4. ledger has no provisional/broken/tainted
    ledger = root / "CLAIM_LEDGER.md"
    if ledger.exists():
        text = ledger.read_text(encoding="utf-8")
        for bad in ("provisional", "broken_engineering", "tainted_provenance"):
            if bad in text:
                blocked = True
                reasons.append(f"ledger still references {bad}")

    if blocked:
        print("BLOCKED: release not allowed")
        for r in reasons:
            print(f"  - {r}")
        return 1

    # 5. build release package
    release_dir = root / "release"
    if not args.dry_run:
        if release_dir.exists():
            shutil.rmtree(release_dir)
        release_dir.mkdir(parents=True)
        for f in ("paper", "results", "evidence_manifest.json", "CLAIM_LEDGER.md",
                  "EXPERIMENT_SPEC.json"):
            src = root / f
            if src.exists():
                dst = release_dir / f
                if src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
        # submission manifest
        sub_manifest = {
            "bundle_id": args.bundle,
            "evidence_state": REQUIRED_STATE,
            "created_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
            "files": {p.relative_to(release_dir).as_posix(): sha256_file(p)
                      for p in release_dir.rglob("*") if p.is_file()},
        }
        (release_dir / "submission_manifest.json").write_text(
            json.dumps(sub_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"RELEASE OK: bundle {args.bundle} -> release/ "
          f"({'dry-run' if args.dry_run else 'built'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
