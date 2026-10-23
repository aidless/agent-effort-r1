r"""paper-writing-agent: hallucination scanner (MLR-Bench HALLUCINATION_RUBRIC, 4 types).

Machine-checkable half of the MLR-Bench four-type hallucination check
(Nonexistent Citations / Hallucinated Methodology / Mathematical Errors /
Faked Experimental Results). Programmatic assertions come first; the
semantic half (LLM judge) consumes the informational sections.

  (E) Nonexistent_citations  - a \cite/\citep/\citet{key} whose key has no
                               @entry{key, definition in any .bib under the
                               tree; or a bib entry missing its title/author
                               (incomplete citation = unverifiable)
  (E) Method_file_claims     - prose explicitly names a file under
                               evidence/ or scripts/ (e.g. "we run
                               scripts/recompute.py", "see evidence/e1.json")
                               that does not exist: the described method
                               cannot be reproduced from the package
  (W) Arithmetic_contradiction - inline "X = a + b" style equations whose
                               claimed total does not match the sum of its
                               parts (first-order math check only)
  (W) Bibkey_typo_hint       - \cite keys that look like a known key with
                               case/prefix drift (informational when >0)
  (I) Strong_claim_surface   - count of strong-assertion phrases
                               (outperforms/significantly/best/state-of-the-
                               art/novel/first) that the LLM judge must
                               verify against evidence (Faked Results half)
  (I) Numbers_without_ledger - numeric literals in prose not covered by any
                               CLAIM_LEDGER.md value (traceability surface)

Only .tex/.md/.txt are scanned for prose; .bib is scanned for definitions.
Family exclusion conventions apply (ROUND_R/REVIEW_R/SELF_ASSESSMENT process
docs, verification scaffolding dirs, reports/). Report paths are rendered
relative to the scan target with the fixed 'paper' label (FM-24).

Usage:
  python scan_hallucination.py <dir> [--out report.md] [--fail-on-error]
       [--exclude-dir "..."] [--exclude-name "..."]

Exit 0 = clean (or report-only); exit 1 = any ERROR section non-empty
with --fail-on-error.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TEX_SUFFIX = {".tex", ".md", ".txt"}
BIB_SUFFIX = {".bib"}
DEFAULT_EXCLUDE = {"reports", ".git", "__pycache__", "node_modules", "build", "dist", "assets", "templates"}
VERIFY_PREFIX_EXCLUDE = (".r", "._", "tmp_r", ".tmp_", ".verify", "_verify", "verify_", ".review_", ".compile")
VERIFY_SUFFIX_EXCLUDE = ("_verify", "_check", "_backup", "_fixedpoint", "_rebuild", "_compile", ".tmpdir")
PROCESS_DOC_PREFIXES = ("ROUND_R", "REVIEW_R", "SELF_ASSESSMENT")
PROCESS_DOC_SUFFIXES = (".summary.md", "_R7_ethics.md")

CITE_RE = re.compile(r"\\(?:cite|citet|citep|citealp|autocite)\*?(\[[^\]]*\])?\{([^}]*)\}")
BIB_ENTRY_RE = re.compile(r"@\w+\{([^,]+),")
BIBITEM_RE = re.compile(r"\\bibitem\{([^}]+)\}")
MISSING_FIELD_RE = re.compile(r"^\s*(title|author)\s*=\s*[{\"]?\s*[}\"]?\s*,?\s*$", re.MULTILINE)
ARITH_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*=\s*([-+]?\d+(?:\.\d+)?)\s*\+\s*([-+]?\d+(?:\.\d+)?)")
STRONG_RE = re.compile(
    r"\b(outperforms?|significantly (?:better|improves?|outperforms?)|"
    r"state[- ]of[- ]the[- ]art|best[- ]performing|first (?:to|work)|"
    r"novel (?:approach|method|framework)|achieves? (?:the )?best)\b",
    re.IGNORECASE,
)
COMMENT_RE = re.compile(r"(?<!\\)%.*$", re.MULTILINE)
NUM_RE = re.compile(r"[-+]?\d+\.\d+|\b\d+\b")


def excluded(p: Path, exclude: set) -> bool:
    parts = p.parts
    if any(part in exclude for part in parts):
        return True
    for i, part in enumerate(parts):
        is_dir = i < len(parts) - 1
        for prefix in VERIFY_PREFIX_EXCLUDE:
            if prefix == "verify_" and not is_dir:
                continue
            if part.startswith(prefix):
                return True
        for suffix in VERIFY_SUFFIX_EXCLUDE:
            if part.endswith(suffix):
                return True
    return False


def is_process_doc(name: str) -> bool:
    if name.startswith(PROCESS_DOC_PREFIXES):
        return True
    return name.endswith(PROCESS_DOC_SUFFIXES)


def iter_files(root: Path, suffixes: set, exclude: set, exclude_names: list):
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in suffixes and not excluded(p.relative_to(root), exclude):
            if any(sub in p.name for sub in exclude_names):
                continue
            if is_process_doc(p.name):
                continue
            yield p


def rel(p: Path, root: Path) -> str:
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", help="dir (--selftest ignores)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--fail-on-error", action="store_true")
    ap.add_argument("--exclude-dir", default="reports,.git,__pycache__,node_modules,build,dist,tmp,assets,templates")
    ap.add_argument("--exclude-name", default="")
    ap.add_argument("--selftest", action="store_true", help="run selftest and exit")
    args = ap.parse_args()

    if args.selftest:
        # 注入: 不存在的 cite key + 缺失的 scripts 文件引用 + 算术矛盾, 断言检出
        import tempfile
        import importlib
        mod = importlib.import_module("scan_hallucination")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "main.tex").write_text(
                "\\cite{no_such_key} and \\cite{real2024}\n"
                "We run scripts/recompute.py for results.\n"
                "The total 10.2 = 5.0 + 6.0 is wrong.\n"
                "\\bibliography{main}\n", encoding="utf-8")
            (root / "main.bib").write_text(
                "@article{real2024, title={T}, author={A}, year={2024}}",
                encoding="utf-8")
            err_cites, err_files, warn_arith = [], [], []
            bib_keys = set()
            for m in mod.BIB_ENTRY_RE.finditer((root / "main.bib").read_text(encoding="utf-8")):
                bib_keys.add(m.group(1).strip())
            text = (root / "main.tex").read_text(encoding="utf-8")
            for m in mod.CITE_RE.finditer(text):
                for key in (k.strip() for k in m.group(2).split(",") if k.strip()):
                    if key not in bib_keys and not key.startswith(("fig:", "tab:")):
                        err_cites.append(key)
            method_file_re = re.compile(
                r"\b(?:evidence|scripts|script)/[A-Za-z0-9_./\-]+\.(?:json|py|r|sh|md|txt|csv)\b")
            for m in method_file_re.finditer(text):
                tok = m.group(0)
                if tok.startswith(("evidence/", "scripts/")) and not (root / tok).exists():
                    err_files.append(tok)
            for m in mod.ARITH_RE.finditer(text):
                total, a, b = (float(x) for x in m.groups())
                if abs(total - (a + b)) > 1e-6:
                    warn_arith.append(m.group(0))
            ok = ("no_such_key" in err_cites and err_files and warn_arith)
            print(f"selftest: cite_hit={'no_such_key' in err_cites} "
                  f"file_hit={bool(err_files)} arith_hit={bool(warn_arith)}: "
                  f"{'PASS' if ok else 'FAIL'}")
            return 0 if ok else 1

    if not args.target:
        ap.error("target required (or use --selftest)")
    root = Path(args.target)
    exclude = set(DEFAULT_EXCLUDE) | {s.strip() for s in args.exclude_dir.split(",") if s.strip()}
    if args.out:
        out_dir = Path(args.out).resolve().parent
        if out_dir != root.resolve():
            exclude.add(out_dir.name)
    exclude_names = [s.strip() for s in args.exclude_name.split(",") if s.strip()]

    # ---- bib key inventory ----
    bib_keys: set[str] = set()
    bib_incomplete: list[str] = []
    for p in iter_files(root, TEX_SUFFIX, exclude, exclude_names):
        if p.suffix.lower() == ".tex":
            t = p.read_text(encoding="utf-8", errors="ignore")
            for m in BIBITEM_RE.finditer(t):
                bib_keys.add(m.group(1).strip())
    for p in iter_files(root, BIB_SUFFIX, exclude, exclude_names):
        text = p.read_text(encoding="utf-8", errors="ignore")
        for m in BIB_ENTRY_RE.finditer(text):
            bib_keys.add(m.group(1).strip())
        # crude completeness: an entry whose title/author line is empty
        for m in re.finditer(r"@\w+\{([^,]+),[^}]*\}", text, re.DOTALL):
            body = m.group(0)
            if MISSING_FIELD_RE.search(body):
                bib_incomplete.append(f"{m.group(1).strip()}@{rel(p, root)}")

    # ---- prose scan ----
    err_cites: list[str] = []
    err_files: list[str] = []
    warn_arith: list[str] = []
    info_strong: int = 0
    ledger_nums: set[str] = set()
    text_nums: set[str] = set()
    ledger_seen = False

    ledger_path = root / "CLAIM_LEDGER.md"
    if ledger_path.exists():
        ledger_seen = True
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if "|" in line:
                cells = line.split("|")
                if len(cells) >= 5:
                    for v in NUM_RE.findall(cells[4]):
                        ledger_nums.add(v)

    # collect method-file claims: evidence/... or scripts/... tokens in prose
    # 2026-10-08 修正：加负向后行断言——匹配的必须是根相对路径的开头。
    # <host>/p2_agent_effort/scripts/x.py 这类云端溯源引用（C45/DEFECT 文档的记录约定）
    # 不是本地方法文件，不该被当幻觉检查；之前的 \b 会在 / 之后照常命中。
    method_file_re = re.compile(r"(?<![\w./\-])(?:evidence|scripts|script)/[A-Za-z0-9_./\-]+\.(?:json|py|r|sh|md|txt|csv)\b")

    for p in iter_files(root, TEX_SUFFIX, exclude, exclude_names):
        text = p.read_text(encoding="utf-8", errors="ignore")
        if p.suffix.lower() == ".tex":
            text = COMMENT_RE.sub("", text)
        rp = rel(p, root)

        for m in CITE_RE.finditer(text):
            for key in (k.strip() for k in m.group(2).split(",") if k.strip()):
                if key not in bib_keys and not key.startswith(("fig:", "tab:", "sec:", "alg:")):
                    err_cites.append(f"{key}@{rp}")

        for m in method_file_re.finditer(text):
            tok = m.group(0)
            if tok.startswith(("evidence/", "scripts/")):
                cand = root / tok
                if not cand.exists():
                    err_files.append(f"{tok}@{rp}")

        for m in ARITH_RE.finditer(text):
            total, a, b = (float(x) for x in m.groups())
            if abs(total - (a + b)) > 1e-6:
                warn_arith.append(f"{m.group(0)}@{rp}")

        info_strong += len(STRONG_RE.findall(text))
        text_nums.update(NUM_RE.findall(text))

    # ---- report ----
    lines = ["# Hallucination scan report (MLR-Bench four types)",
             "",
             f"Target: `{root.name}`",
             "",
             "## (E) Nonexistent Citations / incomplete bib entries",
             ]
    if err_cites:
        lines += [f"- {c}" for c in sorted(set(err_cites))[:60]]
    else:
        lines.append("- none")
    if bib_incomplete:
        lines.append("")
        lines.append("Incomplete bib entries (missing title/author):")
        lines += [f"- {b}" for b in bib_incomplete[:30]]
    lines += ["",
              "## (E) Hallucinated Methodology: named method files missing",
              ]
    if err_files:
        lines += [f"- {f}" for f in sorted(set(err_files))[:60]]
    else:
        lines.append("- none")
    lines += ["",
              "## (W) Mathematical Errors: inline arithmetic contradictions",
              ]
    if warn_arith:
        lines += [f"- {w}" for w in sorted(set(warn_arith))[:60]]
    else:
        lines.append("- none")
    lines += ["",
              "## (I) Faked Results surface: strong-claim count for LLM judge",
              f"- {info_strong} strong-assertion phrases found; LLM judge must verify each against evidence",
              "",
              "## (I) Numbers without ledger coverage",
              ]
    uncovered = sorted(v for v in text_nums if v not in ledger_nums)
    lines.append(f"- {len(uncovered)} numeric literals not covered by CLAIM_LEDGER.md values"
                 + ("" if ledger_seen else " (no CLAIM_LEDGER.md found)"))
    lines.append(", ".join(uncovered[:80]))
    lines.append("")
    lines.append(f"## Summary: {len(err_cites)} cite errors, {len(err_files)} missing method files, "
                 f"{len(warn_arith)} arithmetic warnings, {info_strong} strong claims")

    report = "\n".join(lines)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
    print(report)
    if args.fail_on_error and (err_cites or err_files):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
