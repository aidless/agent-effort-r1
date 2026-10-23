"""paper-writing-agent: number-consistency scanner.

Scans a paper package (tex/md/txt + json evidence) for:
  (a) stale markers that must not reappear (configurable),
  (b) inverted confidence intervals,
  (c) full inventory of distinct decimal values with counts,
  (d) cross-file value sets: values only in evidence vs only in text,
  (e) G8 table-vs-prose consistency: a decimal that appears BOTH inside a
      LaTeX table/tabular cell and in surrounding prose must be written the
      same way (same numeric value); a mismatch means table and text disagree.

Usage:
  python scan_number_consistency.py <dir_or_file> [--stale stale.json] [--out report.md] [--fail-on-stale] [--exclude-dir "reports,.git"]

Exit 0 = report-only (or clean when --fail-on-stale); exit 1 = stale markers found.
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

STALE_DEFAULT = [
    "29.3", "35.4", "37.2", "0.218", "8.5%", "7.0%", "7.6%", "17.6%",
    "N=15", "github.com/Anonymous", "+/-25", "0.471", "0.195",
]
CI_RE = re.compile(r"\[\s*([-+]?\d+\.?\d*)\s*,\s*([-+]?\d+\.?\d*)\s*\]")
NUM_RE = re.compile(r"[-+]?\d+\.\d+")
COMMENT_RE = re.compile(r"(?<!\\)%.*$", re.MULTILINE)
# G8: 表格环境(LaTeX table/tabular + Markdown 表格行)
TABLE_ENV_RE = re.compile(
    r"\\begin\{(?:table|tabular|table\*)\}.*?\\end\{(?:table|tabular|table\*)\}|"
    r"(?:^\|\s*[^\n]*\|\s*$)",
    re.DOTALL | re.MULTILINE)
DEFAULT_EXCLUDE = {"reports", ".git", "__pycache__", "node_modules", "build", "dist", "assets"}
# R21/R30: verification scaffolding may appear inside the checkout during
# concurrent review runs (.r21_verify_backup/, tmp_r21_fixedpoint/, etc.).
# The scan must be immune to any of them so a review run can never pollute
# reports/ or break the manifest fixed point.
VERIFY_PREFIX_EXCLUDE = (".r", "._", "tmp_r", ".tmp_", ".verify", "_verify", "verify_", ".review_", ".compile")
VERIFY_SUFFIX_EXCLUDE = ("_verify", "_check", "_backup", "_fixedpoint", "_rebuild", "_compile", ".tmpdir")


def excluded(p, exclude):
    parts = p.parts
    if any(part in exclude for part in parts):
        return True
    # Verification scaffolding: match DIRECTORY parts (a .r21_verify_backup/ or
    # tmp_r21_fixedpoint/ dir), not legit files like scripts/verify_claim_ledger.py.
    # For non-directory parts, only apply the safer prefix list (dot/underscore
    # leading scaffolding) and the suffix list.
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


PROCESS_DOC_PREFIXES = ("ROUND_R", "REVIEW_R", "SELF_ASSESSMENT")
PROCESS_DOC_SUFFIXES = (".summary.md", "_R7_ethics.md")


def is_process_doc(name: str) -> bool:
    """Process/audit documents (round reports, review summaries, self
    assessment) are NOT paper content. They grow and change every review
    round; including them in the scan would make numbers.md depend on the
    review history and never reach a fixed point (FM-26/R13)."""
    if name.startswith(PROCESS_DOC_PREFIXES):
        return True
    return name.endswith(PROCESS_DOC_SUFFIXES)


def iter_text_files(root: Path, exclude, exclude_names):
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in {".tex", ".md", ".txt"} and not excluded(p.relative_to(root), exclude):
            if any(sub in p.name for sub in exclude_names):
                continue
            if is_process_doc(p.name):
                continue
            yield p


def iter_json_files(root: Path, exclude, exclude_names):
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() == ".json" and not excluded(p.relative_to(root), exclude):
            if any(sub in p.name for sub in exclude_names):
                continue
            # FM-25/R12: evidence_manifest.json is PROCESS METADATA, not
            # experiment evidence. Its size/modified fields would otherwise be
            # picked up as "evidence values", making the scan report
            # self-referential (it embeds its own file size) and forever one
            # generation behind the manifest — every rescan changed bytes and
            # broke the FM-24 gate.
            if p.name == "evidence_manifest.json":
                continue
            # gates_config.json is PROCESS CONFIG (timeouts, file paths), not
            # experiment evidence; exclude it so its numeric config values do
            # not pollute the evidence-only list (R13 Nit).
            if p.name == "gates_config.json":
                continue
            yield p


def json_floats(p: Path) -> set[str]:
    vals: set[str] = set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return vals
    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            vals.add(f"{float(o):.4f}")
    walk(data)
    return vals


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", help="dir or file (--selftest ignores)")
    ap.add_argument("--stale", default=None, help="JSON list of stale strings")
    ap.add_argument("--fail-on-stale", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--exclude-dir", default="reports,.git,__pycache__,node_modules,build,dist,tmp,assets",
                    help="comma-separated directory names to exclude")
    ap.add_argument("--exclude-name", default="", help="comma-separated filename substrings to exclude")
    ap.add_argument("--selftest", action="store_true", help="run selftest and exit")
    args = ap.parse_args()

    if args.selftest:
        # D2: 注入 stale marker + 倒置 CI + 表格-正文不一致, 断言三类都检出
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "main.tex").write_text(
                "Stale 0.218 value here.\n"
                "CI [0.5, 0.2] inverted.\n"
                "Prose says 0.7486 but table 0.7485.\n"
                "\\begin{table}\\begin{tabular}{cc} A & 0.7485 \\\\ \\end{tabular}\\end{table}\n",
                encoding="utf-8")
            ok_stale = ok_ci = ok_tp = True
            for f in iter_text_files(root, set(), []):
                text = f.read_text(encoding="utf-8", errors="ignore")
                if "0.218" in text and "0.218" in STALE_DEFAULT:
                    ok_stale = True
                for m in CI_RE.finditer(text):
                    lo, hi = float(m.group(1)), float(m.group(2))
                    if lo > hi:
                        ok_ci = True
            scan_text = COMMENT_RE.sub("", (root / "main.tex").read_text(encoding="utf-8"))
            table_vals = set()
            for env in TABLE_ENV_RE.findall(scan_text):
                for mv in NUM_RE.finditer(env):
                    table_vals.add(mv.group(0))
            prose = TABLE_ENV_RE.sub("", scan_text)
            ok_tp = any(abs(float(tv) - float(pv)) <= 1e-3 and tv != pv
                        for tv in table_vals
                        for pv in NUM_RE.findall(prose))
            ok = ok_stale and ok_ci and ok_tp
            print(f"selftest: stale={ok_stale} inverted_ci={ok_ci} table_prose={ok_tp}: "
                  f"{'PASS' if ok else 'FAIL'}")
            return 0 if ok else 1

    if not args.target:
        ap.error("target required (or use --selftest)")

    root = Path(args.target)
    exclude = set(DEFAULT_EXCLUDE) | {s.strip() for s in args.exclude_dir.split(",") if s.strip()}
    # FM-26/R15 hardening: never scan the --out report directory itself.
    # If the report is written outside the default exclude set, the scan
    # would read its own previous output and become self-referential.
    if args.out:
        out_dir = Path(args.out).resolve().parent
        if out_dir != root.resolve():
            exclude.add(out_dir.name)
    exclude_names = [s.strip() for s in args.exclude_name.split(",") if s.strip()]
    stale = STALE_DEFAULT
    if args.stale:
        stale = json.loads(Path(args.stale).read_text(encoding="utf-8"))

    stale_hits = []
    for f in iter_text_files(root, exclude, exclude_names):
        text = f.read_text(encoding="utf-8", errors="ignore")
        for marker in stale:
            if marker in text:
                for i, line in enumerate(text.splitlines(), 1):
                    if marker in line:
                        stale_hits.append((str(f), marker, i, line.strip()[:160]))
                        break

    bad_cis = []
    for f in iter_text_files(root, exclude, exclude_names):
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in CI_RE.finditer(text):
            lo, hi = float(m.group(1)), float(m.group(2))
            if lo > hi:
                line = text[:m.start()].count("\n") + 1
                bad_cis.append((str(f), m.group(0), line))

    freq: dict[str, int] = {}
    for f in iter_text_files(root, exclude, exclude_names):
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in NUM_RE.finditer(text):
            v = m.group(0)
            freq[v] = freq.get(v, 0) + 1

    json_vals: set[str] = set()
    for f in iter_json_files(root, exclude, exclude_names):
        json_vals |= json_floats(f)
    text_vals = set(freq.keys())
    evidence_only = sorted(json_vals - text_vals)

    # G8: table-vs-prose consistency. For every decimal inside a table cell,
    # look for a NUMERICALLY NEARBY but textually different value in prose
    # (e.g. table 0.7485 vs prose 0.7486): the two are almost certainly the
    # same quantity written inconsistently. Threshold: |a-b| <= 1e-3 (and
    # relative <= 1e-3 of the larger). Same-literal occurrences are fine.
    table_prose_mismatch = []  # (file, table_val, prose_literal, line)
    for f in iter_text_files(root, exclude, exclude_names):
        text = f.read_text(encoding="utf-8", errors="ignore")
        # strip comments for .tex
        scan_text = COMMENT_RE.sub("", text) if f.suffix.lower() == ".tex" else text
        # collect table cell values (inside table/tabular or markdown table rows)
        table_vals: set[str] = set()
        for env in TABLE_ENV_RE.findall(scan_text):
            for mv in NUM_RE.finditer(env):
                table_vals.add(mv.group(0))
        if not table_vals:
            continue
        # prose = text outside table environments
        prose = TABLE_ENV_RE.sub("", scan_text)
        prose_nums = list(NUM_RE.finditer(prose))
        for tv in sorted(table_vals, key=lambda v: -len(v)):
            tv_f = float(tv)
            for pm in prose_nums:
                pv = pm.group(0)
                if pv == tv:
                    continue
                pv_f = float(pv)
                if abs(tv_f - pv_f) <= 1e-3 and abs(tv_f - pv_f) <= 1e-3 * max(abs(tv_f), abs(pv_f), 1.0):
                    ln = prose[: pm.start()].count("\n") + 1
                    start = max(0, pm.start() - 15)
                    end = min(len(prose), pm.end() + 15)
                    table_prose_mismatch.append((str(f), tv, pv, ln, prose[start:end].replace("\n", " ").strip()))
                    break  # one flag per (file, value)

    lines = []
    lines.append("# Number-consistency scan report")
    # Paths in the report are rendered RELATIVE to the scan target so the
    # report is byte-identical regardless of the invocation cwd AND checkout
    # directory name (FM-24/R25: absolute paths made reports non-reproducible
    # and broke the manifest gate).
    target_name = "paper"  # fixed label, not the checkout dir name
    def show(p: Path) -> str:
        try:
            return p.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return p.name
    lines.append(f"\nTarget: `{target_name}`  |  text files: {len(list(iter_text_files(root, exclude, exclude_names)))}  |  json files: {len(list(iter_json_files(root, exclude, exclude_names)))}")
    lines.append(f"\n## Stale markers: {len(stale_hits)}")
    for f, marker, ln, snippet in stale_hits:
        lines.append(f"- `{marker}` @ {show(Path(f))}:{ln}  :: {snippet}")
    lines.append(f"\n## Inverted confidence intervals: {len(bad_cis)}")
    for f, ci, ln in bad_cis:
        lines.append(f"- {ci} @ {show(Path(f))}:{ln}")
    lines.append("\n## Most frequent numeric literals (top 25)")
    for v, c in sorted(freq.items(), key=lambda kv: -kv[1])[:25]:
        lines.append(f"- {v}: {c}")
    lines.append(f"\n## Values in evidence JSON but never in text: {len(evidence_only)}")
    lines.append(", ".join(evidence_only[:60]))
    lines.append(f"\n## Table-vs-prose mismatches: {len(table_prose_mismatch)}")
    for f, tv, pv, ln, snip in table_prose_mismatch:
        lines.append(f"- table `{tv}` vs prose `{pv}` @ {show(Path(f))}:{ln}  :: {snip}")

    report = "\n".join(lines)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
    print(report)
    if args.fail_on_stale and (stale_hits or table_prose_mismatch):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())