"""paper-writing-agent: submission package checker (N4).

Human-executable checklist over the artifacts produced by prepare_submission.py
(or over a paper dir directly). Runs the mechanical half of the OpenReview
pre-upload checks and prints a pass/fail checklist; the human confirms the
[ ] boxes. Non-blocking by default (--fail-on-error promotes FAIL to exit 1).

Checks:
  C1 zip exists and <= 100 MB (TMLR supplementary limit)
  C2 main.pdf exists (compiled)
  C3 anonymous (no author block / emails / URLs in package, G3 re-scan)
  C4 evidence manifest present and its files all exist under the package
  C5 gates report clean (run_acceptance_gates on gates_config.json if present)
  C6 claim ledger present
  C7 no process docs in package (ROUND/REVIEW/SELF_ASSESSMENT, FM-26)

Usage:
  python check_submission_package.py <paper_dir> [--zip submission/submission_x.zip]
       [--out reports/submission_check.md] [--fail-on-error]

Exit 0 = all PASS (or report-only); exit 1 = any FAIL with --fail-on-error;
exit 2 = fatal (dir missing).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

SIZE_LIMIT_MB = 100
PROCESS_PREFIXES = ("ROUND_R", "REVIEW_R", "SELF_ASSESSMENT", "REBUTTAL")
PROCESS_SUFFIXES = (".summary.md", "_R7_ethics.md", "_R7_ethics.json")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s}\\]+")
AUTHOR_RE = re.compile(r"\\(?:author|and)\s*\{[^}]*\}|\\email\s*\{[^}]*\}|\\affiliation\s*\{[^}]*\}",
                       re.IGNORECASE)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paper_dir")
    ap.add_argument("--zip", default=None, help="package zip path (default: first *.zip under paper_dir/submission)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--fail-on-error", action="store_true")
    args = ap.parse_args()

    root = Path(args.paper_dir).resolve()
    if not root.is_dir():
        print(f"FAIL: paper_dir not found: {root}", file=sys.stderr)
        return 2

    # C1: zip
    zip_path = None
    if args.zip:
        zip_path = Path(args.zip)
    else:
        cands = sorted((root / "submission").glob("*.zip")) if (root / "submission").exists() else []
        if not cands:
            cands = sorted(root.glob("*.zip"))
        if cands:
            zip_path = cands[0]
    checks: list[tuple[str, str, str]] = []
    if zip_path and zip_path.exists():
        size_mb = zip_path.stat().st_size / 1e6
        checks.append(("C1", "PASS" if size_mb <= SIZE_LIMIT_MB else "FAIL",
                       f"zip {zip_path.name} {size_mb:.1f} MB (limit {SIZE_LIMIT_MB})"))
    else:
        checks.append(("C1", "FAIL", f"no submission zip found under {root / 'submission' or root}"))

    # C2: main.pdf
    main_pdf = root / "paper" / "main.pdf"
    if not main_pdf.exists():
        main_pdf = root / "main.pdf"
    checks.append(("C2", "PASS" if main_pdf.exists() else "FAIL",
                   "main.pdf present" if main_pdf.exists() else "main.pdf missing (compile first)"))

    # C3: anonymity on the zip content (or the paper tree)
    hits: list[str] = []
    if zip_path and zip_path.exists():
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for n in zf.namelist():
                    if not n.endswith((".tex", ".bib", ".md", ".txt")):
                        continue
                    try:
                        text = zf.read(n).decode("utf-8", errors="ignore")
                    except KeyError:
                        continue
                    for m in AUTHOR_RE.finditer(text):
                        hits.append(f"{n}: {m.group(0)[:50]}")
                    for m in EMAIL_RE.finditer(text):
                        hits.append(f"{n}: email {m.group(0)}")
                    for m in URL_RE.finditer(text):
                        if "arxiv.org" not in m.group(0) and "openreview" not in m.group(0):
                            hits.append(f"{n}: url {m.group(0)[:70]}")
        except zipfile.BadZipFile:
            hits.append("(zip unreadable)")
    else:
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.suffix.lower() in {".tex", ".bib", ".md", ".txt"}:
                if any(seg in {"reports", ".git", "node_modules", "submission"} for seg in p.parts):
                    continue
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for m in AUTHOR_RE.finditer(text):
                    hits.append(f"{p.name}: {m.group(0)[:50]}")
                for m in EMAIL_RE.finditer(text):
                    hits.append(f"{p.name}: email {m.group(0)}")
                for m in URL_RE.finditer(text):
                    if "arxiv.org" not in m.group(0) and "openreview" not in m.group(0):
                        hits.append(f"{p.name}: url {m.group(0)[:70]}")
    checks.append(("C3", "PASS" if not hits else "FAIL",
                   f"anonymous: {len(hits)} hit(s)" + (f" :: {hits[0][:60]}" if hits else "")))

    # C4: manifest files exist
    manifest_path = root / "evidence_manifest.json"
    missing = []
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            for f in data.get("files", []):
                p = root / f if isinstance(f, str) else None
                if p is not None and not p.exists():
                    missing.append(f)
        except (OSError, json.JSONDecodeError):
            checks.append(("C4", "FAIL", "evidence_manifest.json unreadable"))
            missing = None
        if missing is not None:
            checks.append(("C4", "PASS" if not missing else "FAIL",
                           f"manifest ok" if not missing else f"{len(missing)} manifest files missing: {missing[:5]}"))
    else:
        checks.append(("C4", "FAIL", "evidence_manifest.json missing"))

    # C5: gates
    gates_cfg = root / "gates_config.json"
    if gates_cfg.exists():
        try:
            r = subprocess.run([sys.executable, str(root / "scripts" / "run_acceptance_gates.py"),
                                str(gates_cfg)], capture_output=True, text=True, timeout=600)
            ok = r.returncode == 0
            checks.append(("C5", "PASS" if ok else "FAIL",
                           "acceptance gates PASS" if ok else f"acceptance gates FAIL: {r.stdout[-200:]}"))
        except (OSError, subprocess.TimeoutExpired) as e:
            checks.append(("C5", "FAIL", f"gate runner error: {e}"))
    else:
        checks.append(("C5", "SKIP", "no gates_config.json (not gated)"))

    # C6: ledger
    checks.append(("C6", "PASS" if (root / "CLAIM_LEDGER.md").exists() else "FAIL",
                   "CLAIM_LEDGER.md present" if (root / "CLAIM_LEDGER.md").exists() else "CLAIM_LEDGER.md missing"))

    # C7: no process docs in zip
    proc_leaks = []
    if zip_path and zip_path.exists():
        with zipfile.ZipFile(zip_path) as zf:
            for n in zf.namelist():
                base = Path(n).name
                if base.startswith(PROCESS_PREFIXES) or base.endswith(PROCESS_SUFFIXES):
                    proc_leaks.append(n)
    checks.append(("C7", "PASS" if not proc_leaks else "FAIL",
                   "no process docs in package" if not proc_leaks else f"process docs leaked: {proc_leaks[:5]}"))

    fails = [c for c in checks if c[1] == "FAIL"]
    lines = ["# Submission package check report", "",
             f"Target: `paper`  |  checks: {len(checks)}  |  failures: {len(fails)}", ""]
    for cid, sev, msg in checks:
        lines.append(f"- [{cid}] {sev} :: {msg}")
    lines += ["", "## Human checklist (confirm before upload)", ""]
    for cid, sev, _ in checks:
        if sev != "SKIP":
            lines.append(f"- [ ] {cid}: {sev}")
    report = "\n".join(lines) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
    print(report)
    if args.fail_on_error and fails:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
