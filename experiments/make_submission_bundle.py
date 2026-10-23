#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_submission_bundle.py — build the anonymous, minimal submission package (G4/N1).

`prepare_submission.py` copies the whole project, which drags in (a) the 30-file
verification toolkit, (b) process/audit documents (ROUND_R*, SELF_ASSESSMENT),
and (c) tool-internal helper scripts. For a double-blind submission the
supplementary package must be the MINIMAL reproducibility artifact:

    paper/            manuscript source + bibliography + compiled PDF
    experiments/      the four generators that produced every number
    results/          raw JSON outputs + run logs
    evidence/         the source-quote package + a self-contained copy of the
                      source report's identity (hash), never the shared tree
    analysis.py       the single canonical recomputation script
    requirements.txt  pinned environment
    CLAIM_LEDGER.md / HYPOTHESES.md / LITERATURE_REVIEW.md / WORKING_NOTES.md

Excluded: scripts/ (verification toolkit), submission/ (this bundle), reports/
(generated), ROUND_R* / REVIEW_R* / SELF_ASSESSMENT* / gates_history.jsonl
(process documents: FM-26), and any absolute host path.

The anonymous-repository URL cannot be created from here: publishing an
anonymous mirror is an external, irreversible action and belongs to the
protected layer (human confirmation). This script produces the tree that will be
uploaded, plus `ANON_REPO.md` recording exactly what the human must do.

Run: python3 experiments/make_submission_bundle.py . --out submission/repo
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile

KEEP_DIRS = ["paper", "experiments", "results", "evidence"]
KEEP_FILES = [
    "analysis.py",
    "requirements.txt",
    "CLAIM_LEDGER.md",
    "HYPOTHESES.md",
    "LITERATURE_REVIEW.md",
    "WORKING_NOTES.md",
    "novelty_claims.txt",
]
DROP_GLOBS = [
    "paper/main.aux", "paper/main.log", "paper/main.out", "paper/main.blg",
    "paper/*.fls", "paper/*.fdb_latexmk", "paper/*.synctex.gz",
    "results/run_logs/*.log.bak",
]
# host-specific absolute paths that must never ship
# The Windows branch used to be `[A-Z]:\\\\`, which inside a raw string demands TWO literal
# backslashes -- so it never matched the paths that actually occur in this tree (`F:\deepseek\...`,
# written with one).  The detector reported "absolute-path hits: 0" on a package that contained
# several, which is worse than no check: it read as a clean result.  `[\\]{1,2}` takes either, and
# the drive-letter branch requires a following path segment so a bare `x:` in prose is not a hit.
ABS_PATH_RE = re.compile(r"(?:/root/aut[o]dl-tmp[^\s\"']*|/hom[e]/[^\s\"']*|[A-Z]:[\\]{1,2}[^\s\"']*|[A-Z]:/[^\s\"']*)")

# ---------------------------------------------------------------------------
# Internal-structure redaction (G9/G10).
#
# An anonymous package must not reveal the surrounding queue: naming the shared
# evidence tree or a SIBLING submission directory lets a reviewer link two
# submissions reviewed in the same cycle, which is a double-blind violation even
# though nothing here is an absolute host path.  check_submission_package.py C3
# only looks for author/institution strings, so this class of leak needs its own
# pass AND its own gate.
# ---------------------------------------------------------------------------
EXTRACTOR_FALLBACK_OLD = '''# Fallback to the shared source tree (the queue keeps ONE authoritative copy so
# line numbers cannot drift).  The SHA-256 check below fails closed, so a
# drifted or substituted copy can never silently validate.
REPORT_SHARED = os.path.normpath(
    os.path.join(PAPER_DIR, os.pardir, "_shared", "evidence", "V41FLASH_TechReport.txt")
)
if os.environ.get("V41_REPORT_TXT"):
    REPORT, REPORT_SOURCE = os.environ["V41_REPORT_TXT"], "env:V41_REPORT_TXT"
elif os.path.exists(REPORT_SHARED):
    REPORT, REPORT_SOURCE = REPORT_SHARED, "authoritative source tree"
else:
    REPORT, REPORT_SOURCE = REPORT_LOCAL, "in-package copy"'''
EXTRACTOR_FALLBACK_NEW = '''# This anonymous copy ships no shared source tree: supply the report at the
# documented path, or point V41_REPORT_TXT at it.  The SHA-256 check below
# fails closed, so a drifted or substituted copy can never silently validate.
if os.environ.get("V41_REPORT_TXT"):
    REPORT, REPORT_SOURCE = os.environ["V41_REPORT_TXT"], "env:V41_REPORT_TXT"
else:
    REPORT, REPORT_SOURCE = REPORT_LOCAL, "in-package copy"'''

LITERAL_REDACTIONS = [
    (EXTRACTOR_FALLBACK_OLD, EXTRACTOR_FALLBACK_NEW),
    # LaTeX-escaped form, as it appears in main.bib
    (r"papers/\_shared/evidence/V41FLASH\_TechReport.txt",
     r"evidence/V41FLASH\_TechReport.txt"),
    ("papers/csa2_robust/evidence/V41_2606.06467.pdf",
     "[withheld: unrelated sibling submission]"),
    # our own queue tag is a grouping id, not part of the science
    ("papers/agent_effort/", ""),
]
# Absolute host paths are redacted in the SHIPPED copies only (the working tree
# keeps them).  Provenance survives as a declared placeholder, so a reader can see
# that a real location existed without learning the host layout.
HOST_PATH_REDACTIONS = [
    (re.compile(r"/root/aut[o]dl-tmp/models/([A-Za-z0-9._\-]+)"), r"$MODEL_DIR/\1"),
    (re.compile(r"/root/aut[o]dl-tmp/h4_agent_effort"), r"$H4_WORK"),
    (re.compile(r"/root/aut[o]dl-tmp/[^\s\"',)]*"), r"$H4_HOST_PATH"),
    (re.compile(r"/hom[e]/[^\s\"',)]*"), r"$WORKSPACE_PATH"),
]
GENERIC_REDACTIONS = [
    (re.compile(r"papers/(?!_shared)[A-Za-z0-9_.\-]+/"), "[withheld: sibling submission]/"),
    (re.compile(r"papers[_/]\\?_shared"), "[withheld: shared evidence tree]"),
    (re.compile(r"\bpapers/"), ""),
    (re.compile(r"source_path_shared"), "source_path_origin"),
]
LEAK_PATTERNS = [re.compile(r"papers/"),
                 re.compile(r"papers[_/]\\?_shared"),
                 re.compile(r"\\_shared"),
                 re.compile(r"[`\"']_shared")]

# Build infrastructure is inherently queue-aware (it encodes the sibling layout
# it redacts).  It is not needed to reproduce any number, so it is NOT shipped.
#
# The H4 harnesses are the same case for a different reason: they have produced
# NO result, no number in the paper depends on them, and they necessarily carry
# the host GPU-lock and model paths they must run against.  Shipping an unrun
# harness would leak a host path and imply evidence that does not exist.  They
# enter this package when H4 has actually run and enters the manuscript.
SELF_EXCLUDE = {"experiments/make_submission_bundle.py"}
NOT_SHIPPED = {
    "experiments/h4_gx_measure.py":
        "superseded draft harness (used for the pilot only): the reported run uses "
        "h4_real_llm_gx.py, which IS shipped; this draft carries host GPU paths",
    "experiments/h4_queue_step.sh":
        "superseded queue wrapper: replaced by h4_run_remote.sh, which IS shipped",
    "results/h4_dryrun_stub.json":
        "CPU stub dry run (dry_run=true, no model): a control-flow check, not a "
        "measurement, and not cited in the manuscript",
}

# The source report text is NOT redistributed in the anonymous package (it is a
# third-party document).  The pointer stub is replaced by an in-package note that
# keeps the reproduction path honest and complete.
ANON_SOURCE_NOTE = """# V41FLASH_TechReport.txt (not redistributed)

The extracted evidence used by this paper is shipped in full as
`evidence/v41flash_effort_control.json` (40 verbatim quotes with LF line numbers
and 19 numeric facts).  THE PAPER'S NUMBERS DO NOT DEPEND ON THIS FILE: every
table is recomputable from `results/*.json` with `analysis.py`.

Re-deriving the extraction additionally needs the underlying report text, which
is a third-party document and is therefore NOT redistributed here.

    expected file   : evidence/V41FLASH_TechReport.txt
    sha256          : ac24848a4dee30669b9caac6ca05b62d7186e4c546add099ccc906065288abf3
    length          : 3791 lines (split on LF only; 51 form feeds)
    line convention : str.splitlines() is BANNED -- it yields 3841 lines (+50)
                      because the form feeds split there but not on LF

Obtain the report, place the text at that path, verify the SHA-256 above, then
run `python3 experiments/extract_v41_effort_evidence.py`.  The extractor FAILS
CLOSED if the hash drifts, so it cannot silently validate a different document.
"""


def redact_text(text: str) -> str:
    for old, new in LITERAL_REDACTIONS:
        text = text.replace(old, new)
    for pat, new in GENERIC_REDACTIONS:
        text = pat.sub(new, text)
    for pat, new in HOST_PATH_REDACTIONS:
        text = pat.sub(new, text)
    return text


def redact_tree(out: str, copied) -> list:
    """Rewrite internal references in text files only.  Returns a log."""
    log = []
    for rel in copied:
        p = os.path.join(out, rel)
        try:
            raw = open(p, "rb").read()
            text = raw.decode("utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary (PDF) or unreadable: never rewritten
        new = redact_text(text)
        if new != text:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(new)
            log.append(rel)
    return log


def leak_scan(out: str, siblings) -> list:
    """Any surviving internal-path reference, including sibling dir names."""
    pats = list(LEAK_PATTERNS) + [re.compile(r"\b%s\b" % re.escape(s)) for s in siblings if s]
    hits = []
    for dirpath, dirnames, filenames in os.walk(out):
        dirnames[:] = [x for x in dirnames if x != "__pycache__"]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, out).replace(os.sep, "/")
            try:
                text = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            for pat in pats:
                for m in pat.finditer(text):
                    lo = max(0, m.start() - 40)
                    hits.append((rel, pat.pattern, text[lo:m.end() + 40].replace("\n", " ")))
    return hits


def sibling_names(root: str):
    """Directory names in the queue root other than this paper."""
    parent = os.path.dirname(os.path.abspath(root.rstrip(os.sep)))
    me = os.path.basename(os.path.abspath(root.rstrip(os.sep)))
    try:
        return sorted(d for d in os.listdir(parent)
                      if os.path.isdir(os.path.join(parent, d)) and d != me
                      and not d.startswith("."))
    except OSError:
        return []


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def refresh_h4_derived(out):
    """Re-derive the shipped H4 derived-stats file from the SHIPPED result file.

    Redaction changes the result bytes (host paths become placeholders), so a
    derived-stats file copied from the working tree would record the hash of a
    file that is not in this package.  That makes the package fail its own
    provenance check -- an independent reviewer recomputes and sees a mismatch.
    Re-running the derivation inside the package restores consistency and is the
    same deterministic script a reviewer would run.

    Returns a one-line status string, or None when the inputs are absent.
    """
    import subprocess
    res = os.path.join(out, "results", "h4_real_llm_gx_qwen3_8b.json")
    scr = os.path.join(out, "experiments", "h4_derived_stats.py")
    dst = os.path.join(out, "results", "h4_derived_stats.json")
    if not all(os.path.isfile(x) for x in (res, scr, dst)):
        return None
    r = subprocess.run([sys.executable, scr, os.path.join("results",
                                                          "h4_real_llm_gx_qwen3_8b.json"),
                        "--out", os.path.join("results", "h4_derived_stats.json")],
                       cwd=out, capture_output=True, text=True)
    if r.returncode != 0:
        return "FAILED rc=%d: %s" % (r.returncode, (r.stderr or "").strip()[:200])
    # prove it now matches
    import hashlib
    for f in ("results/h4_derived_stats.json",):
        d = json.load(open(os.path.join(out, f), encoding="utf-8"))
        h = hashlib.sha256(open(res, "rb").read()).hexdigest()
        if d.get("source_sha256") != h:
            return "FAILED: source_sha256 still inconsistent"
    return "re-derived from the shipped result (source_sha256 verified)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paper_dir")
    ap.add_argument("--out", default="submission/repo")
    ap.add_argument("--allow-leaks", action="store_true",
                    help="do not fail when an internal-path/sibling reference survives")
    ap.add_argument("--zip", default=None,
                    help="also write a deterministic zip of the bundle to this path")
    args = ap.parse_args()
    root = os.path.abspath(args.paper_dir)
    out = os.path.join(root, args.out) if not os.path.isabs(args.out) else args.out
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)

    copied = []
    for d in KEEP_DIRS:
        src = os.path.join(root, d)
        if not os.path.isdir(src):
            continue
        for dirpath, dirnames, filenames in os.walk(src):
            dirnames[:] = [x for x in dirnames if x not in ("__pycache__", ".git")]
            for fn in filenames:
                s = os.path.join(dirpath, fn)
                rel = os.path.relpath(s, root).replace(os.sep, "/")
                if rel in SELF_EXCLUDE or rel in NOT_SHIPPED:
                    continue
                # H4 DOES ship now: it is the paper's central negative result and
                # must be recomputable from this package (adversarial review M1).
                # The blanket "no h4_*" rule from the unrun era was removed; the
                # two superseded host-specific drafts stay out via NOT_SHIPPED.
                if os.path.basename(rel) == "h4_dryrun_stub.json":
                    continue  # CPU stub dry run: not a measurement, not cited
                if any(glob.fnmatch.fnmatch(rel, g) for g in DROP_GLOBS):
                    continue
                t = os.path.join(out, rel)
                os.makedirs(os.path.dirname(t), exist_ok=True)
                shutil.copy2(s, t)
                copied.append(rel)
    for f in KEEP_FILES:
        s = os.path.join(root, f)
        if os.path.isfile(s):
            t = os.path.join(out, f)
            os.makedirs(os.path.dirname(t) or out, exist_ok=True)
            shutil.copy2(s, t)
            copied.append(f)

    # G9/G10: strip internal queue structure BEFORE hashing the bundle
    redacted = redact_tree(out, copied)
    note_path = os.path.join(out, "evidence", "V41FLASH_TechReport.txt")
    if os.path.isfile(note_path):
        with open(note_path, "w", encoding="utf-8") as fh:
            fh.write(ANON_SOURCE_NOTE)
        if "evidence/V41FLASH_TechReport.txt" not in redacted:
            redacted.append("evidence/V41FLASH_TechReport.txt")

    # make the package internally consistent AFTER redaction changed the bytes
    h4_refresh = refresh_h4_derived(out)

    siblings = sibling_names(root)
    leaks = leak_scan(out, siblings)

    # absolute-path audit: the bundle must be host-agnostic
    hits = []
    for rel in copied:
        p = os.path.join(out, rel)
        try:
            text = open(p, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for m in ABS_PATH_RE.finditer(text):
            hits.append((rel, m.group(0)[:60]))

    # manifest of the bundle itself (so the uploaded tree is hash-pinned)
    entries = []
    for dirpath, dirnames, filenames in os.walk(out):
        dirnames[:] = [x for x in dirnames if x != "__pycache__"]
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, out).replace(os.sep, "/")
            if rel in ("SUBMISSION_MANIFEST.json", "ANON_REPO.md"):
                continue
            entries.append({"path": rel, "size": os.path.getsize(p), "sha256": sha256(p)})
    import json
    with open(os.path.join(out, "SUBMISSION_MANIFEST.json"), "w", encoding="utf-8") as fh:
        json.dump({"kind": "anonymous supplementary package",
                   "n_files": len(entries), "files": entries}, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    anon = [
        "# Anonymous repository / supplementary package (G4)",
        "",
        "Built by `experiments/make_submission_bundle.py`. This directory is the",
        "MINIMAL reproducibility artifact; it contains no verification toolkit, no",
        "process documents, no absolute host paths and no internal queue structure.",
        "",
        f"- files: {len(entries)}",
        f"- absolute-path hits: {len(hits)}",
        f"- internal-path / sibling-submission leaks: {len(leaks)}",
        f"- files rewritten by the redaction pass: {len(redacted)}",
        "",
        "## Not shipped, and why",
        "",
    ]
    anon += [f"- `{k}` :: {v}" for k, v in sorted(NOT_SHIPPED.items())]
    anon += [
        "",
        "## What recomputes what",
        "",
        "- Secs. 1--3 (E1/E1b/E2/E3): `analysis.py` from `results/*.json`.",
        "- Sec. 4 (H4, the real-model result): `experiments/h4_derived_stats.py`",
        "  from `results/h4_real_llm_gx_qwen3_8b.json` regenerates the budget curve,",
        "  the paired exact test, BOTH non-monotonicity fits and the per-level action",
        "  profile; `experiments/analyze_h4_result.py <result> --refit` re-runs the",
        "  gain fit under the current identifiability guard and shows the three axes",
        "  are withheld. The 672 per-episode records are shipped in full.",
        "- `analysis.py` does NOT cover H4; the paper says so explicitly.",
        "",
        "## Source report (not redistributed)",
        "",
        "`evidence/V41FLASH_TechReport.txt` is a pointer, not the document.",
        "Re-deriving the extraction needs the third-party report text (SHA-256 pinned",
        "in that file; the extractor fails closed on drift). The extracted quotations",
        "are shipped in full, so the paper's own numbers do not need it.",
        "",
        "## Redaction of host paths",
        "",
        "Absolute host paths in the shipped copies are replaced by declared",
        "placeholders (`$MODEL_DIR`, `$H4_WORK`, `$WORKSPACE_PATH`). Measured values",
        "are unchanged, and `results/h4_derived_stats.json` is re-derived from the",
        "shipped records so the package stays internally consistent.",
        "",
        "## What a human still has to do (protected layer: external + irreversible)",
        "",
        "1. Create the anonymous mirror, e.g. `anonymous.4open.science` (the TMLR",
        "   whitelist accepts that host) or an anonymous GitHub org.",
        "2. Upload the CONTENTS of this directory (not the parent).",
        "3. Put the resulting URL in the manuscript's reproducibility section and in",
        "   the OpenReview supplementary field, then re-run",
        "   `python3 scripts/check_tmlr_compliance.py . --names \"\" --exclude-dir evidence`",
        "   to confirm the URL is on the allowlist.",
        "4. Re-run `python3 scripts/check_submission_package.py . --fail-on-error`.",
        "",
    ]
    if redacted:
        anon += ["## Redaction log (internal references removed)", ""]
        anon += [f"- `{r}`" for r in sorted(redacted)]
        anon += [""]
    if leaks:
        anon += ["## LEAKS STILL PRESENT - DO NOT UPLOAD", ""]
        anon += [f"- `{r}` :: /{p}/ :: `{c}`" for r, p, c in leaks[:40]]
        anon += [""]
    if hits:
        anon += ["## Absolute-path hits to review before upload", ""]
        anon += [f"- `{h[0]}` :: `{h[1]}`" for h in hits[:40]]
        anon += [""]
    with open(os.path.join(out, "ANON_REPO.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(anon) + "\n")

    print("bundle: %s" % os.path.relpath(out, root))
    print("  files             : %d" % len(entries))
    print("  absolute-path hits: %d" % len(hits))
    print("  redacted files    : %d" % len(redacted))
    for r in sorted(redacted):
        print("    - %s" % r)
    print("  internal leaks    : %d (siblings considered: %s)"
          % (len(leaks), ", ".join(siblings) or "none"))
    for r, p, c in leaks[:10]:
        print("    ! %s :: /%s/ :: %s" % (r, p, c))
    print("  H4 derived stats : %s" % (h4_refresh or "not applicable"))
    print("  wrote SUBMISSION_MANIFEST.json + ANON_REPO.md")

    if args.zip:
        zp = os.path.join(root, args.zip) if not os.path.isabs(args.zip) else args.zip
        os.makedirs(os.path.dirname(zp), exist_ok=True)
        # deterministic archive: sorted entries + fixed timestamp, so the zip is
        # byte-stable across rebuilds (FM-24/25)
        names = []
        for dirpath, dirnames, filenames in os.walk(out):
            dirnames[:] = [x for x in dirnames if x != "__pycache__"]
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                names.append(os.path.relpath(p, out).replace(os.sep, "/"))
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in sorted(names):
                zi = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = 0o644 << 16
                with open(os.path.join(out, rel), "rb") as fh:
                    zf.writestr(zi, fh.read())
        print("  zip               : %s (%d entries, %.2f MB)"
              % (os.path.relpath(zp, root), len(names), os.path.getsize(zp) / 1e6))

    if leaks and not args.allow_leaks:
        print("FAIL: internal-path/sibling leak survived redaction", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
