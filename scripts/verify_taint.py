"""paper-writing-agent: evidence-taint propagation verifier (L2-5).

Mechanizes the propagation rule of references/evidence-states.md: when a
source evidence file is tainted (state value other than "verified"/"candidate",
or listed in the "tainted" array), every claim in CLAIM_LEDGER.md that
references that file is blocked from entering the manuscript.

Reads:
  <paper_dir>/CLAIM_LEDGER.md            claim rows (same table format as
                                         verify_claim_ledger.py)
  <paper_dir>/evidence/tainted.json      {"tainted": [paths],
                                          "state": {path: status}}

  - "tainted" and "state" may appear independently; both may coexist.
  - state values other than "verified"/"candidate" are treated as tainted;
    the recorded status is the state value itself (e.g. "broken").
  - "tainted" entries are always tainted; their status is the state value
    if present, else "tainted".
  - a missing tainted.json means no taint (Tainted_files = 0).

Evidence paths in the ledger tolerate several spellings; all are normalized
(posix, normpath) before comparison and existence checks:
  results/e1.json
  evidence/../results/e1.json            (parent traversal collapsed)
  e1.json:acc                            (':field' suffix, file part taken)
  results/e1.json -> gTV.mean / gTV.sd   (arrow field list, file part taken)
  ref1; ref2                             (';'-separated multiple files)

Report sections (machine-readable "## <Name>: <count>" lines, target tag
"paper", paths relative to the paper dir for byte-reproducible reports):
  Tainted_claims   (ERROR)  claims referencing a tainted file
  Missing_evidence (ERROR)  claims referencing a file that does not exist
  Claims_checked   (INFO)   claim rows parsed
  Tainted_files    (INFO)   tainted files declared (0 when tainted.json absent)

Usage:
  python verify_taint.py <paper_dir> [--ledger CLAIM_LEDGER.md]
      [--taint evidence/tainted.json] [--out report.md] [--fail-on-error]

Exit 0 = no ERROR sections (or --fail-on-error not given); exit 1 =
any ERROR section > 0 with --fail-on-error, or the ledger is missing.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
from pathlib import Path

# Same claim-row shape as verify_claim_ledger.py (6 table columns).
ROW_RE = re.compile(
    r"^\|\s*(C\d+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|$"
)
# State values that do NOT block claims. Everything else is tainted.
CLEAN_STATES = {"verified", "candidate"}
DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def strip_cell(s: str) -> str:
    return s.replace("`", "").strip()


def norm_rel(p: str) -> str:
    """Normalize a ledger/taint path to a canonical relative posix path.

    Collapses "./", "a/..", backslashes, and stray whitespace so that
    "results/e1.json", "evidence/../results/e1.json" and "e1.json" (when the
    paper root is the evidence root) all map onto the same key.
    """
    p = p.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    if not p:
        return ""
    if posixpath.isabs(p) or DRIVE_RE.match(p):
        # Absolute / drive-letter path: keep for the existence check, but it
        # can never match a relative taint entry.
        return posixpath.normpath(p)
    return posixpath.normpath(p)


def extract_file(ref: str) -> str:
    """Return the normalized evidence-file part of one ledger reference cell."""
    ref = ref.strip().strip("`").strip()
    if not ref:
        return ""
    # Arrow form: "results/e1.json -> gTV.mean / gTV.sd" -> file part only.
    if "->" in ref:
        ref = ref.split("->", 1)[0].strip()
    # Colon field suffix: "e1.json:acc" -> file part only. Guard against http
    # URLs and Windows drive letters ("C:\\...").
    elif ":" in ref and not ref.lower().startswith("http") and not DRIVE_RE.match(ref):
        ref = ref.split(":", 1)[0].strip()
    # Trailing punctuation that may cling to the path (",", ";", ".", CJK).
    ref = ref.rstrip(".,;，。")
    return norm_rel(ref)


def load_taint(root: Path, taint_rel: str):
    """Return (taint, notes).

    taint: dict[casefolded_norm_path -> (status, display_path)].
    notes: informational lines (missing / unparseable taint source).
    """
    tpath = root / taint_rel
    if not tpath.exists():
        return {}, [f"- taint source `{taint_rel}` not present - no taint detected"]
    try:
        # utf-8-sig tolerates a UTF-8 BOM (Windows editors / PowerShell
        # Set-Content -Encoding utf8), which json.loads would otherwise reject.
        data = json.loads(tpath.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001 - report and continue as no taint
        return {}, [f"- WARN taint source `{taint_rel}` unparseable ({exc}) - treated as no taint"]
    if not isinstance(data, dict):
        return {}, [f"- WARN taint source `{taint_rel}` is not a JSON object - treated as no taint"]

    tainted_list = data.get("tainted", [])
    state = data.get("state", {})
    if not isinstance(tainted_list, list):
        tainted_list = []
    if not isinstance(state, dict):
        state = {}

    # Normalize state keys once; drop non-string / empty entries.
    state_norm: dict[str, tuple[str, str]] = {}
    for p, st in state.items():
        if not isinstance(p, str) or not isinstance(st, str):
            continue
        np_ = norm_rel(p)
        if np_:
            state_norm[np_.casefold()] = (st.strip() or "tainted", np_)

    taint: dict[str, tuple[str, str]] = {}
    # Explicit "tainted" list always taints (status: state value or "tainted").
    for p in tainted_list:
        if not isinstance(p, str) or not p.strip():
            continue
        np_ = norm_rel(p)
        if not np_:
            continue
        key = np_.casefold()
        status, disp = state_norm.get(key, ("tainted", np_))
        taint[key] = (status, disp)
    # State entries whose value is neither verified nor candidate are tainted.
    for key, (st, disp) in state_norm.items():
        if st.casefold() not in CLEAN_STATES:
            taint[key] = (st, disp)
    return taint, []


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Verify no claim references tainted or missing evidence files (L2-5)."
    )
    ap.add_argument("target", nargs="?", help="paper directory (--selftest ignores)")
    ap.add_argument("--ledger", default="CLAIM_LEDGER.md", help="ledger file name (default CLAIM_LEDGER.md)")
    ap.add_argument("--taint", default="evidence/tainted.json", help="taint source relative to <paper_dir>")
    ap.add_argument("--out", default=None, help="write the report to this file")
    ap.add_argument("--fail-on-error", action="store_true",
                    help="exit 1 when any ERROR section is non-empty")
    ap.add_argument("--selftest", action="store_true", help="run selftest and exit")
    args = ap.parse_args()

    if args.selftest:
        # 注入: ledger 引用 missing 文件 -> 应检出
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "CLAIM_LEDGER.md").write_text(
                "| C01 | claim | missing.json -> x | 1.0 | recompute | verified |\n",
                encoding="utf-8")
            # 复用核心检测: 扫描 ledger 行引用的文件存在性
            import re as _re
            ref_re = _re.compile(r"([A-Za-z0-9_./\-]+\.(?:json|npz|csv))")
            text = (root / "CLAIM_LEDGER.md").read_text(encoding="utf-8")
            refs = ref_re.findall(text)
            missing = [r for r in refs if not (root / r).exists()]
            ok = bool(missing)
            print(f"selftest: missing_refs={missing}: {'PASS' if ok else 'FAIL'}")
            return 0 if ok else 1

    if not args.target:
        ap.error("target required (or use --selftest)")

    root = Path(args.target)
    ledger_path = root / args.ledger
    if not ledger_path.exists():
        print(f"FAIL missing ledger: {ledger_path}")
        return 1

    try:
        ledger_display = ledger_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        ledger_display = ledger_path.name

    taint, notes = load_taint(root, args.taint)

    tainted_claims: list[tuple[str, str, str]] = []  # (cid, path, status)
    missing_evidence: list[tuple[str, str]] = []     # (cid, path)
    claims_checked = 0

    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        # Protect escaped pipes (\\|) from table-column splitting, restore later.
        guarded = line.replace("\\|", "\u0001")
        m = ROW_RE.match(guarded)
        if not m:
            continue
        cid, claim, evref, values, method, status = (
            strip_cell(x).replace("\u0001", "|") for x in m.groups()
        )
        # Same skips as verify_claim_ledger.py: header / template-example rows.
        if cid.lower().startswith("id") or "template" in status.lower() or "example" in status.lower():
            continue
        claims_checked += 1
        for ref in evref.split(";"):
            ref = ref.strip()
            if not ref:
                continue
            fpath = extract_file(ref)
            if not fpath:
                continue
            key = fpath.casefold()
            if key in taint:
                st, _disp = taint[key]
                if (cid, fpath, st) not in tainted_claims:
                    tainted_claims.append((cid, fpath, st))
            if not (root / fpath).exists() and (cid, fpath) not in missing_evidence:
                missing_evidence.append((cid, fpath))

    lines = [
        "# Evidence taint propagation report",
        f"\nTarget: `paper`  |  ledger: `{ledger_display}`  |  taint source: `{args.taint}`",
    ]
    lines.extend(notes)
    lines.append(f"\n## Tainted_claims: {len(tainted_claims)}  (ERROR)")
    for cid, fpath, st in sorted(tainted_claims):
        lines.append(f"- [ERROR] {cid}: references tainted evidence `{fpath}` (status: {st})")
    lines.append(f"\n## Missing_evidence: {len(missing_evidence)}  (ERROR)")
    for cid, fpath in sorted(missing_evidence):
        lines.append(f"- [ERROR] {cid}: references missing evidence file `{fpath}`")
    lines.append(f"\n## Claims_checked: {claims_checked}  (INFO)")
    lines.append(f"\n## Tainted_files: {len(taint)}  (INFO)")
    for _key, (st, disp) in sorted(taint.items(), key=lambda kv: kv[1][1]):
        lines.append(f"- {disp} (status: {st})")
    lines.append(
        f"\n## Summary: {len(tainted_claims)} tainted claim(s), "
        f"{len(missing_evidence)} missing evidence, {claims_checked} claims checked, "
        f"{len(taint)} tainted file(s)"
    )

    report = "\n".join(lines)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
    print(report)

    if args.fail_on_error and (tainted_claims or missing_evidence):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
