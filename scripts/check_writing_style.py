"""paper-writing-agent: writing-style static checker (heuristic).

Flags patterns that recurred in past revision rounds:

  - strong claims without hedging (proves / first study / clearly / guarantees ...)
  - "results can show" style overuse of can
  - redundant adverbs (very important, totally different, completely unique ...)
  - Chinese-English residue (researches, according to the data, The fact that)
  - passive without subject (It was then analyzed)
  - CI crossing zero co-located with a "significant" claim

Usage:
  python check_writing_style.py <paper_dir> [--out report.md] [--exit-zero]

Exit 1 when findings exist (unless --exit-zero).
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path

TEXT_SUFFIX = {".tex", ".md", ".txt"}

STRONG_CLAIMS = [
    (r"\bproves?\b", "strong claim 'proves' - hedge it"),
    (r"\bfirst study\b", "strong claim 'first study' - hedge it"),
    (r"\bit is clear that\b", "strong claim 'it is clear that'"),
    (r"\bdefinitively\b", "strong claim 'definitively'"),
    (r"\bunquestionably\b", "strong claim 'unquestionably'"),
    (r"\bobviously\b", "strong claim 'obviously'"),
    (r"\bguarantees?\b", "strong claim 'guarantee'"),
    (r"\bconclusively\b", "strong claim 'conclusively'"),
]
CAN_CLAIM = re.compile(r"\bcan\s+(show|prove|demonstrate|conclude|verify|confirm)\b")
REDUNDANT = [
    (r"\bvery important\b", "redundant 'very important' -> critical/essential"),
    (r"\btotally different\b", "redundant 'totally different' -> different"),
    (r"\bcompletely unique\b", "redundant 'completely unique' -> unique"),
    (r"\babsolutely essential\b", "redundant 'absolutely essential' -> essential"),
    (r"\bvery (significant|critical|essential|huge)\b", "redundant 'very X'"),
]
CHINGLISH = [
    (r"\bresearches\b", "misuse of 'researches' (uncountable)"),
    (r"\baccording to the (data|results|experiment|table|figure)\b", "'according to' misused for data/results"),
    (r"\bThe fact that\b", "long noun phrase 'The fact that' -> 'That'"),
    (r"\bon the one hand[^.]*on the other hand\b", "verify 'on the one hand... on the other hand' is contrast, not listing"),
]
PASSIVE_NO_SUBJECT = re.compile(r"\bIt was (?:then\s+)?(analyzed|computed|measured|performed|evaluated|tested|assessed)\b")
CI_RE = re.compile(r"\[\s*([-+]?\d+\.?\d*)\s*,\s*([-+]?\d+\.?\d*)\s*\]")
SIG_RE = re.compile(r"significan|p\s*[<=>]\s*0\.0|p\s*=\s*0\.\d")
DEFAULT_EXCLUDE = {"reports", ".git", "__pycache__", "node_modules", "build", "dist"}


PROCESS_DOC_PREFIXES = ("ROUND_R", "REVIEW_R", "SELF_ASSESSMENT", "novelty_claims")
PROCESS_DOC_SUFFIXES = (".summary.md", "_R7_ethics.md")
# R21/R30: verification scaffolding immunity.
VERIFY_PREFIX_EXCLUDE = (".r", "._", "tmp_r", ".tmp_", ".verify", "_verify", "verify_", ".review_", ".compile")
VERIFY_SUFFIX_EXCLUDE = ("_verify", "_check", "_backup", "_fixedpoint", "_rebuild", "_compile", ".tmpdir")


def is_excluded_path(p, exclude):
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
    """Process/audit documents are NOT paper content (FM-26/R13/R14)."""
    if name.startswith(PROCESS_DOC_PREFIXES):
        return True
    return name.endswith(PROCESS_DOC_SUFFIXES)


def text_files(root: Path, exclude, exclude_names):
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in TEXT_SUFFIX:
            if is_excluded_path(p, exclude):
                continue
            if any(sub in p.name for sub in exclude_names):
                continue
            if is_process_doc(p.name):
                continue
            yield p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", help="dir (--selftest ignores)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--exit-zero", action="store_true")
    ap.add_argument("--exclude-name", default="", help="comma-separated filename substrings to exclude")
    ap.add_argument("--exclude-dir", default="reports,.git,__pycache__,node_modules,build,dist,tmp",
                    help="comma-separated directory names to exclude")
    ap.add_argument("--selftest", action="store_true", help="run selftest and exit")
    args = ap.parse_args()

    if args.selftest:
        # 注入: CI 跨零 + 显著性声明(风格问题) -> 检出
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "main.tex").write_text(
                "The effect is significant with CI [-0.02, 0.05].\n",
                encoding="utf-8")
            text = (root / "main.tex").read_text(encoding="utf-8")
            ci_cross_zero = False
            for m in CI_RE.finditer(text):
                lo, hi = float(m.group(1)), float(m.group(2))
                if lo <= 0 <= hi:
                    ci_cross_zero = True
            sig_claim = bool(SIG_RE.search(text))
            ok = ci_cross_zero and sig_claim  # CI 跨零且声称显著 = 检出
            print(f"selftest: ci_cross_zero={ci_cross_zero} sig_claim={sig_claim}: "
                  f"{'PASS' if ok else 'FAIL'}")
            return 0 if ok else 1

    if not args.target:
        ap.error("target required (or use --selftest)")
    root = Path(args.target)
    exclude = set(DEFAULT_EXCLUDE) | {s.strip() for s in args.exclude_dir.split(",") if s.strip()}
    exclude_names = [s.strip() for s in args.exclude_name.split(",") if s.strip()]

    # Paths rendered relative to the scan target so reports are byte-reproducible
    # regardless of invocation cwd (FM-24/R11).
    root_abs = root.resolve()
    target_name = "paper"  # fixed label, not the checkout dir name
    def show(p: Path) -> str:
        try:
            return p.resolve().relative_to(root_abs).as_posix()
        except ValueError:
            return p.name

    findings = []  # (severity, message)
    can_count = 0
    words_total = 0
    for p in text_files(root, exclude, exclude_names):
        text = p.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            math_ctx = ("theorem" in line.lower() or "worst-case" in line.lower()
                        or "bound" in line.lower() or "lemma" in line.lower())
            for pat, msg in STRONG_CLAIMS:
                if re.search(pat, line, re.IGNORECASE):
                    if "guarantee" in msg and math_ctx:
                        continue  # 数学定理语境的 guarantee（worst-case/bound/Theorem）豁免
                    findings.append(("FAIL", f"{msg} @ {show(p)}:{i} :: {line.strip()[:120]}"))
            if CAN_CLAIM.search(line):
                findings.append(("FAIL", f"'can + claim verb' @ {show(p)}:{i} :: {line.strip()[:120]}"))
            for pat, msg in REDUNDANT:
                if re.search(pat, line, re.IGNORECASE):
                    findings.append(("FAIL", f"{msg} @ {show(p)}:{i} :: {line.strip()[:120]}"))
            for pat, msg in CHINGLISH:
                if re.search(pat, line, re.IGNORECASE):
                    findings.append(("FAIL", f"{msg} @ {show(p)}:{i} :: {line.strip()[:120]}"))
            if PASSIVE_NO_SUBJECT.search(line):
                findings.append(("FAIL", f"passive without subject @ {show(p)}:{i} :: {line.strip()[:120]}"))
            for m in CI_RE.finditer(line):
                lo, hi = float(m.group(1)), float(m.group(2))
                if lo <= 0 <= hi and SIG_RE.search(line) and "non-significant" not in line.lower() and "not significant" not in line.lower():
                    findings.append(("FAIL", f"CI {m.group(0)} crosses zero but sentence claims significance @ {show(p)}:{i}"))
            can_count += len(re.findall(r"\bcan\b", line))
            words_total += len(re.findall(r"\b\w+\b", line))

    can_rate = can_count / max(words_total / 1000, 1e-9)
    if can_rate > 5:
        findings.append(("WARN", f"'can' density {can_rate:.1f}/1000 words (>{5}): prefer may/suggest/evidence-based wording"))

    fails = [f for f in findings if f[0] == "FAIL"]
    lines = ["# Writing-style scan report", f"\nTarget: `{target_name}`  |  findings: {len(findings)}  |  failures: {len(fails)}"]
    for sev, msg in findings:
        lines.append(f"- [{sev}] {msg}")
    report = "\n".join(lines)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
    print(report)
    if args.exit_zero:
        return 0
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())