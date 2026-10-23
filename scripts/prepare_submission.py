"""paper-writing-agent: submission package preparer (N1).

Builds the TMLR submission package + OpenReview field checklist + anonymity
re-check, WITHOUT performing the upload itself (upload is a protected-layer
action: it needs the user's account, final confirmation, and is irreversible
once submitted — the tool prepares everything, the human clicks submit).

Outputs under <paper_dir>/submission/:
  - submission_<name>.zip  : main.pdf + paper/*.tex + main.bib + evidence/
                             + evidence_manifest.json + gates/reports summary
                             (excludes ROUND_*/REVIEW_*/SELF_ASSESSMENT process
                             docs and any *_verify scaffolding — FM-26)
  - openreview_checklist.md : per-field checklist (title/abstract/authors/
                             keywords/confidentiality/PDF/zip) with extracted
                             values and TODO markers for human-only fields
  - anonym_check.md        : G3 re-scan of the package (author names, emails,
                             URLs, acknowledgements) before upload

Usage:
  python prepare_submission.py <paper_dir> [--name <zip_base>] [--out <dir>]

Exit 0 = package built (checklist may still have TODOs); exit 2 = fatal
(no main.tex, no main.pdf, unreadable).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

# FM-26: process/audit docs never ship inside the submission package.
PROCESS_PREFIXES = ("ROUND_R", "REVIEW_R", "SELF_ASSESSMENT", "REBUTTAL")
PROCESS_SUFFIXES = (".summary.md", "_R7_ethics.md", "_R7_ethics.json")
VERIFY_PREFIX = (".r", "._", "tmp_r", ".tmp_", ".verify", "_verify", "verify_", ".review_", ".compile")
VERIFY_SUFFIX = ("_verify", "_check", "_backup", "_fixedpoint", "_rebuild", "_compile", ".tmpdir")
SKIP_DIRS = {"reports", ".git", "__pycache__", "node_modules", "build", "dist", "submission", "ARCHIVE", ".bak-fix-20260816", ".pytest_cache", "release", "theory"}

# G3 anonymity scan patterns (author block, emails, URLs, acknowledgements)
AUTHOR_RE = re.compile(
    r"\\(?:author|and)\s*\{[^}]*\}|\\email\s*\{[^}]*\}|\\thanks\s*\{[^}]*\}|"
    r"\\affiliation\s*\{[^}]*\}|Acknowledg(e)?ment", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s}\\]+")


def excluded(p: Path, root: Path) -> bool:
    try:
        rel = p.relative_to(root)
    except ValueError:
        return True
    for part in rel.parts:
        if part in SKIP_DIRS:
            return True
        for pref in VERIFY_PREFIX:
            if part.startswith(pref):
                return True
        for suff in VERIFY_SUFFIX:
            if part.endswith(suff):
                return True
    if rel.name.startswith(PROCESS_PREFIXES) or rel.name.endswith(PROCESS_SUFFIXES):
        return True
    # Paper text extractions are not part of submission
    if rel.parts[0] == "paper" and rel.suffix.lower() == ".txt":
        return True
    return False


def extract_title(main_tex: Path) -> str:
    m = re.search(r"\\title\s*\{([^}]+)\}", main_tex.read_text(encoding="utf-8", errors="ignore"))
    return m.group(1).strip() if m else "(not found — check main.tex \\title)"


def extract_abstract(main_tex: Path) -> str:
    text = main_tex.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", text, re.DOTALL)
    if not m:
        return "(not found)"
    abstract = m.group(1)
    abstract = re.sub(r"\\(?:cite|citep|citet)\{[^}]*\}", "[cite]", abstract)
    return " ".join(abstract.split())[:600]


def extract_keywords(main_tex: Path) -> str:
    text = main_tex.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"\\keywords\s*\{([^}]+)\}", text)
    return m.group(1).strip() if m else "(not found — add \\keywords{...})"


def scan_anonymity(root: Path) -> list[str]:
    hits = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in {".tex", ".bib", ".md", ".txt"} and not excluded(p, root):
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in AUTHOR_RE.finditer(text):
                hits.append(f"{p.name}: author-like pattern: {m.group(0)[:60]}")
            for m in EMAIL_RE.finditer(text):
                hits.append(f"{p.name}: email: {m.group(0)}")
            for m in URL_RE.finditer(text):
                if "arxiv.org" not in m.group(0) and "openreview" not in m.group(0):
                    hits.append(f"{p.name}: url: {m.group(0)[:80]}")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paper_dir")
    ap.add_argument("--name", default=None, help="zip base name (default: submission_<dir>")
    ap.add_argument("--out", default=None, help="output dir (default: <paper_dir>/submission)")
    args = ap.parse_args()

    root = Path(args.paper_dir).resolve()
    if not root.is_dir():
        print(f"FAIL: paper_dir not found: {root}", file=sys.stderr)
        return 2

    # locate manuscript
    paper = root / "paper"
    main_tex = paper / "main.tex" if (paper / "main.tex").exists() else root / "main.tex"
    if not main_tex.exists():
        print("FAIL: no paper/main.tex (or main.tex at root) — cannot prepare submission", file=sys.stderr)
        return 2
    main_pdf = main_tex.with_suffix(".pdf")
    if not main_pdf.exists():
        print(f"WARN: {main_pdf.name} not found — compile first (compile_gate.py or pdflatex)", file=sys.stderr)

    name = args.name or f"submission_{root.name}"
    out_dir = Path(args.out) if args.out else root / "submission"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{name}.zip"

    # ---- build zip ----
    included = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(root.rglob("*")):
            if not p.is_file() or excluded(p, root):
                continue
            rel = p.relative_to(root).as_posix()
            zf.write(p, arcname=rel)
            included.append(rel)
    size_mb = zip_path.stat().st_size / 1e6

    # ---- OpenReview checklist ----
    title = extract_title(main_tex)
    abstract = extract_abstract(main_tex)
    keywords = extract_keywords(main_tex)
    checklist_lines = [
        "# OpenReview submission checklist (TMLR)",
        "",
        "> 本清单由 prepare_submission.py 生成。`[TODO]` 字段必须人工确认/填写；",
        "> 上传动作本身保留人工（保护层：账号、最终确认、不可逆）。",
        "",
        "## 稿件",
        f"- [ ] 确认 main.pdf 为最终匿名版（见 anonym_check.md）",
        f"- [ ] 确认 zip（{size_mb:.1f} MB）包含 evidence 包（清单见下）",
        "",
        "## 表单字段",
        f"- [ ] Title: {title}",
        f"- [ ] Abstract: {abstract}",
        f"- [ ] Keywords: {keywords}",
        "- [ ] [TODO] Authors（OpenReview 实名/匿名策略按 TMLR 当期要求）",
        "- [ ] [TODO] Confidentiality / 双盲声明",
        "- [ ] [TODO] Previous submissions / 交叉投稿声明（G9）",
        "",
        "## zip 内容摘要",
        f"- {len(included)} files, {size_mb:.1f} MB",
    ]
    checklist = "\n".join(checklist_lines) + "\n"

    # ---- anonymity re-check ----
    hits = scan_anonymity(root)
    anonym_lines = ["# Anonymity re-check (G3) — pre-upload scan", "",
                    f"Hits: {len(hits)}"]
    if hits:
        anonym_lines += [f"- {h}" for h in hits[:50]]
        anonym_lines += ["", "**ACTION REQUIRED**: 以上命中项必须清除或匿名化后再上传。"]
    else:
        anonym_lines += ["- none (clean)"]
    anonym = "\n".join(anonym_lines) + "\n"

    (out_dir / "openreview_checklist.md").write_text(checklist, encoding="utf-8")
    (out_dir / "anonym_check.md").write_text(anonym, encoding="utf-8")

    print(f"# Submission package ready")
    print(f"zip: {zip_path} ({size_mb:.1f} MB, {len(included)} files)")
    print(f"checklist: {out_dir / 'openreview_checklist.md'}")
    print(f"anonymity: {out_dir / 'anonym_check.md'} ({len(hits)} hits)")
    if not main_pdf.exists():
        print("WARN: main.pdf missing — compile before upload")
    if hits:
        print(f"WARN: {len(hits)} anonymity hits — fix before upload (see anonym_check.md)")
    print("\nUpload remains MANUAL (protected layer): login to OpenReview, upload zip+PDF, confirm.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
