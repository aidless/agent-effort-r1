r"""paper-writing-agent: figure-claim consistency scanner (audit L2-4, 图-文双向校验).

Machine-checkable BIDIRECTIONAL figure-text consistency for a LaTeX paper
package. This is the mechanical half of the R8 figures reviewer (the
deepseek-eyes skill covers the semantic half: what the rendered figure
actually contains):

  (E) Missing_figure_refs       - \ref{fig:...}/\autoref{fig:...} points at a
                                  label that is never \label{fig:...}-defined
                                  anywhere in the scanned .tex corpus
  (E) Undefined_includegraphics - the \includegraphics{...} target file does
                                  not exist under the paper tree (resolved
                                  relative to the including .tex file's own
                                  dir, the scan root, and <root>/paper/, with
                                  the .pdf/.png/.jpg/.jpeg/.eps/.tex suffix
                                  stripped and re-tried per the LaTeX
                                  extension-omission convention)
  (W) Never_mentioned           - a \label{fig:...} is defined but never
                                  referenced: the figure is an orphan no prose
                                  points at (R8: dead weight or a missing
                                  cross-reference?)
  (I) Figure_mentions           - raw numeric "Fig(ure) N" mentions in prose.
                                  These are semantic claims ("Fig 3 shows X")
                                  whose truth only the deepseek-eyes card can
                                  verify; the count tells R8 how much surface
                                  it must cover
  (I) Figures_defined           - total distinct \label{fig:...} definitions

Only .tex files are scanned. Family exclusion conventions apply: ROUND_R /
REVIEW_R / SELF_ASSESSMENT process documents, verification scaffolding dirs
(.r*/tmp_r*/_verify/...), and reports/ are skipped. LaTeX % comments are
stripped before scanning so stale commented-out \ref's cannot block the gate.
Report paths are rendered relative to the scan target with the fixed 'paper'
label (FM-24 byte-reproducible style, same as the sibling scanners).

Usage:
  python scan_figure_claims.py <dir_or_file> [--out report.md] [--fail-on-error]
       [--exclude-dir "reports,.git,..."] [--exclude-name "..."]

Exit 0 = report-only (or clean with --fail-on-error);
exit 1 = any ERROR-level section non-empty with --fail-on-error.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# text scaffolding (same conventions as scan_number_consistency.py / stats)
# ---------------------------------------------------------------------------

TEX_SUFFIX = {".tex"}
DEFAULT_EXCLUDE = {"reports", ".git", "__pycache__", "node_modules", "build", "dist", "assets"}
VERIFY_PREFIX_EXCLUDE = (".r", "._", "tmp_r", ".tmp_", ".verify", "_verify", "verify_", ".review_", ".compile")
VERIFY_SUFFIX_EXCLUDE = ("_verify", "_check", "_backup", "_fixedpoint", "_rebuild", "_compile", ".tmpdir")
PROCESS_DOC_PREFIXES = ("ROUND_R", "REVIEW_R", "SELF_ASSESSMENT")
PROCESS_DOC_SUFFIXES = (".summary.md", "_R7_ethics.md")

# extensions tried when an \includegraphics path is written without one
IMG_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".tex")

LABEL_RE = re.compile(r"\\label\{(fig:[^}]*)\}")
REF_RE = re.compile(r"\\(?:auto)?ref\*?\{(fig:[^}]*)\}")
INCLUDEGRAPHICS_RE = re.compile(r"\\includegraphics(\*)?(\[[^\]]*\])?\{([^}]*)\}")
MENTION_RE = re.compile(r"\bFig(?:ure)?\.?\s*~?\s*(\d+)\b")
COMMENT_RE = re.compile(r"(?<!\\)%.*$", re.MULTILINE)


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


def iter_tex_files(root: Path, exclude: set, exclude_names: list):
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in TEX_SUFFIX and not excluded(p.relative_to(root), exclude):
            if any(sub in p.name for sub in exclude_names):
                continue
            if is_process_doc(p.name):
                continue
            yield p


def _line(text: str, pos: int) -> int:
    return text[:pos].count("\n") + 1


# ---------------------------------------------------------------------------
# includegraphics file resolution
# ---------------------------------------------------------------------------


def resolve_includegraphics(tex_parent: Path, root: Path, raw: str):
    """Resolve an \\includegraphics argument against the paper tree.

    Tries the path as written, then with each known image/tex suffix
    substituted (LaTeX lets you omit the extension), from each base: the
    including .tex's own directory, the scan root, and <root>/paper/ (papers
    commonly keep figures under paper/ while the scan target is the project
    root). Returns the resolved Path or None.
    """
    p = raw.strip()
    if not p:
        return None
    if p.startswith("./"):
        p = p[2:]
    path = Path(p)
    stems = [path]
    if path.suffix:
        stems.append(path.with_suffix(""))
    bases = []
    for b in (tex_parent, root, root / "paper"):
        if b not in bases:
            bases.append(b)
    for base in bases:
        for stem in stems:
            cands = [stem]
            if not stem.suffix:
                cands += [Path(str(stem) + ext) for ext in IMG_EXTS]
            for cand in cands:
                try:
                    if (base / cand).resolve().is_file():
                        return base / cand
                except OSError:
                    continue
    return None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", help="dir or file (--selftest ignores)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--fail-on-error", action="store_true")
    ap.add_argument("--exclude-dir", default="reports,.git,__pycache__,node_modules,build,dist,tmp,assets")
    ap.add_argument("--exclude-name", default="")
    ap.add_argument("--selftest", action="store_true", help="run selftest and exit")
    args = ap.parse_args()

    if args.selftest:
        # 注入: 未定义 fig ref + 缺失 includegraphics -> 检出
        import tempfile
        import importlib
        mod = importlib.import_module("scan_figure_claims")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "main.tex").write_text(
                "See \\ref{fig:missing} and \\includegraphics{nofile.png}.\n",
                encoding="utf-8")
            text = (root / "main.tex").read_text(encoding="utf-8")
            defined = {m.group(1) for m in mod.LABEL_RE.finditer(text)}
            refs = [m.group(1) for m in mod.REF_RE.finditer(text)]
            undef = [r for r in refs if r not in defined]
            imgs = [m.group(3) for m in mod.INCLUDEGRAPHICS_RE.finditer(text)]
            missing_img = any(mod.resolve_includegraphics(root, root, i) is None for i in imgs)
            ok = bool(undef) and missing_img
            print(f"selftest: undefined_refs={undef} missing_img={missing_img}: "
                  f"{'PASS' if ok else 'FAIL'}")
            return 0 if ok else 1

    if not args.target:
        ap.error("target required (or use --selftest)")
    root = Path(args.target)
    if root.is_file():
        targets = [root]
        scan_root = root.parent
    else:
        exclude = set(DEFAULT_EXCLUDE) | {s.strip() for s in args.exclude_dir.split(",") if s.strip()}
        if args.out:
            out_dir = Path(args.out).resolve().parent
            if out_dir != root.resolve():
                exclude.add(out_dir.name)
        exclude_names = [s.strip() for s in args.exclude_name.split(",") if s.strip()]
        targets = list(iter_tex_files(root, exclude, exclude_names))
        scan_root = root

    root_abs = scan_root.resolve()
    target_name = "paper"

    def show(p: Path) -> str:
        try:
            return p.resolve().relative_to(root_abs).as_posix()
        except ValueError:
            return p.name

    # pass 1: collect raw evidence (definitions need to be global before refs
    # are judged, so refs across \input-split files never false-positive)
    docs = []  # (rel, comment-stripped text)
    for f in targets:
        text = f.read_text(encoding="utf-8", errors="ignore")
        docs.append((show(f), COMMENT_RE.sub("", text)))

    defined_loc: dict[str, tuple[str, int]] = {}   # label -> (rel, line) of first definition
    refs: list[tuple[str, str, int]] = []          # (label, rel, line)
    mentions: list[tuple[str, str, int]] = []      # (fig_number, rel, line)
    missing_incs: list[tuple[str, str, int]] = []  # (raw_path, rel, line)
    inc_total = 0

    for rel, text in docs:
        for m in LABEL_RE.finditer(text):
            label = m.group(1).strip()
            if label not in defined_loc:
                defined_loc[label] = (rel, _line(text, m.start()))
        for m in REF_RE.finditer(text):
            refs.append((m.group(1).strip(), rel, _line(text, m.start())))
        for m in MENTION_RE.finditer(text):
            mentions.append((m.group(1), rel, _line(text, m.start())))
        for m in INCLUDEGRAPHICS_RE.finditer(text):
            inc_total += 1
            raw = m.group(3).strip()
            if resolve_includegraphics(f.parent, scan_root, raw) is None:
                missing_incs.append((raw, rel, _line(text, m.start())))

    # pass 2: verdicts
    defined = set(defined_loc)
    referenced = {label for label, _, _ in refs}

    counts = {
        "Missing_figure_refs": 0,
        "Undefined_includegraphics": 0,
        "Never_mentioned": 0,
        "Figure_mentions": 0,
        "Figures_defined": 0,
    }
    by_section: dict[str, list[tuple[str, str, int, str]]] = {k: [] for k in counts}

    for label, rel, ln in refs:
        if label not in defined:
            counts["Missing_figure_refs"] += 1
            by_section["Missing_figure_refs"].append(
                ("E", rel, ln, f"\\ref{{{label}}} targets an undefined figure label"))
    for raw, rel, ln in missing_incs:
        counts["Undefined_includegraphics"] += 1
        by_section["Undefined_includegraphics"].append(
            ("E", rel, ln, f"\\includegraphics{{{raw}}}: image file not found in the paper tree"))
    for label in sorted(defined - referenced):
        rel, ln = defined_loc[label]
        counts["Never_mentioned"] += 1
        by_section["Never_mentioned"].append(
            ("W", rel, ln, f"label {label} defined but never referenced (orphan figure)"))
    for num, rel, ln in mentions:
        counts["Figure_mentions"] += 1
        by_section["Figure_mentions"].append(
            ("I", rel, ln, f"numeric mention of Fig. {num}"))
    for label in sorted(defined):
        rel, ln = defined_loc[label]
        counts["Figures_defined"] += 1
        by_section["Figures_defined"].append(
            ("I", rel, ln, f"\\label{{{label}}} defined"))

    lines = ["# Figure-claim consistency scan report"]
    lines.append(
        f"\nTarget: `{target_name}`  |  tex files: {len(docs)}  |  figure labels: {len(defined)}"
        f"  |  figure refs: {len(refs)}  |  includegraphics: {inc_total} ({len(missing_incs)} missing)"
        f"  |  numeric mentions: {len(mentions)}")
    for key in counts:
        lines.append(f"\n## {key}: {counts[key]}")
        for sev, rel, ln, snippet in by_section[key]:
            lines.append(f"- [{sev}] {snippet} @ {rel}:{ln}")

    report = "\n".join(lines)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
    print(report)

    has_error = counts["Missing_figure_refs"] > 0 or counts["Undefined_includegraphics"] > 0
    if args.fail_on_error and has_error:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
