"""paper-writing-agent: build or verify an evidence manifest with SHA-256.

Usage:
  python build_evidence_manifest.py <paper_dir> [--out evidence_manifest.json]
  python build_evidence_manifest.py <paper_dir> --verify evidence_manifest.json

Build mode: scan the paper directory, hash every file, write a manifest
(the manifest itself is excluded from its own file list).
Verify mode: check that every manifest entry still exists with the same hash;
missing/hash-mismatched files are FAIL (exit 1), extra files are WARN.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "build", "dist", "reports"}
# reports/ 是扫描/门禁的瞬态输出(每次运行重写, 字节稳定但内容随状态变化):
# 纳入 manifest 会让"重建清单→跑门禁"永不收敛(FM-24/25 边界, 2026-08-15 实证:
# gates.json 随 PASS 数变化 → manifest 对账 FAIL)。所有扫描器默认排除 reports/,
# manifest 构建器应与之一致——manifest 只覆盖证据与交付物。
# gates_history.jsonl 是门禁运行的过程记录(每次 --record 追加, 哈希必然漂移):
# 纳入 manifest 使"重建清单→跑门禁"永不收敛(R1 对抗审稿 Critical 实证 2026-08-15)。
# 与 evidence_manifest.json 自排除同类: manifest 只覆盖证据与交付物, 不覆盖过程元数据。
PROCESS_FILE_EXCLUDES = {"gates_history.jsonl"}
# R21/R30: verification scaffolding immunity.
VERIFY_PREFIX_EXCLUDE = (".r", "._", "tmp_r", ".tmp_", ".verify", "_verify", "verify_", ".review_", ".compile")
VERIFY_SUFFIX_EXCLUDE = ("_verify", "_check", "_backup", "_fixedpoint", "_rebuild", "_compile", ".tmpdir")


def is_excluded_part(name: str, is_dir: bool) -> bool:
    for prefix in VERIFY_PREFIX_EXCLUDE:
        if prefix == "verify_" and not is_dir:
            continue
        if name.startswith(prefix):
            return True
    for suffix in VERIFY_SUFFIX_EXCLUDE:
        if name.endswith(suffix):
            return True
    return False


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_files(root: Path, exclude: set[str] | None = None):
    ex = set(EXCLUDED_DIRS) | set(exclude or ())
    files = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        parts = p.relative_to(root).parts
        if any(part in ex for part in parts):
            continue
        if p.name in PROCESS_FILE_EXCLUDES:
            continue
        if any(is_excluded_part(part, i < len(parts) - 1) for i, part in enumerate(parts)):
            continue
        files.append(p)
    return files


def build(root: Path, out: Path, exclude: set[str] | None = None):
    entries = []
    for p in collect_files(root, exclude):
        rel = p.relative_to(root).as_posix()
        if out.exists() and p.resolve() == out.resolve():
            continue  # never hash the manifest into itself
        st = p.stat()
        entries.append({
            "path": rel,
            "size": st.st_size,
            "sha256": sha256_of(p),
            "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
        })
    manifest = {
        "root": str(root),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": entries,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(entries)} entries -> {out}")


def verify(root: Path, manifest_path: Path):
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    fails, warns, passes = 0, 0, 0
    for e in data["files"]:
        p = root / e["path"]
        if not p.exists():
            print(f"FAIL missing {e['path']}")
            fails += 1
            continue
        got = sha256_of(p)
        if got != e["sha256"]:
            print(f"FAIL hash mismatch {e['path']} (manifest {e['sha256'][:12]}... vs disk {got[:12]}...)")
            fails += 1
        else:
            print(f"PASS {e['path']}")
            passes += 1
    disk = {p.relative_to(root).as_posix() for p in collect_files(root) if p.name != manifest_path.name}
    listed = {e["path"] for e in data["files"]}
    for extra in sorted(disk - listed):
        print(f"WARN file not in manifest: {extra}")
        warns += 1
    print(f"\nTOTAL: {passes} PASS, {fails} FAIL, {warns} WARN")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="paper directory")
    ap.add_argument("--out", default="evidence_manifest.json")
    ap.add_argument("--verify", default=None, help="manifest to verify (implies verify mode)")
    ap.add_argument("--exclude", default=None, help="comma-separated extra names to exclude")
    args = ap.parse_args()
    root = Path(args.target)
    exclude = {s.strip() for s in (args.exclude or "").split(",") if s.strip()}
    if args.verify:
        return verify(root, Path(args.verify))
    return build(root, root / args.out, exclude) or 0


if __name__ == "__main__":
    sys.exit(main())