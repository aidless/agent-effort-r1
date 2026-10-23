"""scanner_regression.py — 失败类反例回归(Voyager 自动课程式落地)。

对每个 scanner 族的失败类夹具运行 scanner,断言:
  - 脏夹具(有失败模式)必须被 scanner 命中;
  - clean 控制组不得误报(零假阳性);
  - ERROR 级命中时 scanner 必须返回非零(族级 --fail-on-* 参数)。
发现新失败模式时(审稿/自查抓到的漏检),往
  assets/scanner_fixtures/<族>/<失败类>/ 加夹具,本脚本即回归锁。

用法:
  python scripts/scanner_regression.py            # 跑全部夹具(全部族)
  python scripts/scanner_regression.py --family stats-consistency
  python scripts/scanner_regression.py --fixture p-stat-mismatch
  python scripts/scanner_regression.py --fixtures-root <dir>   # 候选夹具根(演化验收)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL = SCRIPTS.parent
FIXTURES_ROOT = SKILL / "assets" / "scanner_fixtures"

FAMILIES = {
    "hallucination": {
        "scanner": "scan_hallucination.py",
        "manifest": {
            "clean": {"cite_errors": 0, "missing_files": 0, "arith": 0, "strong": 0},
            "dirty": {"cite_errors": 1, "missing_files": 1, "arith": 1, "strong": 2},
        },
        "sections": {
            "cite_errors": r"## Summary: (\d+) cite errors",
            "missing_files": r"## Summary: \d+ cite errors, (\d+) missing method files",
            "arith": r"## Summary: \d+ cite errors, \d+ missing method files, (\d+) arithmetic warnings",
            "strong": r"## Summary: \d+ cite errors, \d+ missing method files, \d+ arithmetic warnings, (\d+) strong claims",
        },
        "args": ["--fail-on-error"],
        "error_keys": ["cite_errors", "missing_files"],
    },
    "number-consistency": {
        "scanner": "scan_number_consistency.py",
        "manifest": {
            "stale-marker": {"stale": 1, "inverted_ci": 0, "cross_file": 0, "table_prose": 0},
            "inverted-ci": {"stale": 0, "inverted_ci": 1, "cross_file": 0, "table_prose": 0},
            "cross-file": {"stale": 0, "inverted_ci": 0, "cross_file": 1, "table_prose": 0},
            "clean": {"stale": 0, "inverted_ci": 0, "cross_file": 0, "table_prose": 0},
            "table-prose-dirty": {"stale": 0, "inverted_ci": 0, "cross_file": 0, "table_prose": 1},
        },
        "sections": {
            "stale": r"## Stale markers:\s*(\d+)",
            "inverted_ci": r"## Inverted confidence intervals:\s*(\d+)",
            "cross_file": r"## Values in evidence JSON but never in text:\s*(\d+)",
            "table_prose": r"## Table-vs-prose mismatches:\s*(\d+)",
        },
        "args": ["--fail-on-stale"],
        "error_keys": ["stale", "table_prose"],
    },
    "stats-consistency": {
        "scanner": "scan_stats_consistency.py",
        "manifest": {
            "clean": {"impossible_p": 0, "effect_range": 0, "neg_stat": 0,
                      "p_eq_mismatch": 0, "p_ineq_mismatch": 0, "n_conflict": 0,
                      "sign_mismatch": 0, "p_zero": 0, "mcp_risk": 0},
            "impossible-p": {"impossible_p": 1, "effect_range": 0, "neg_stat": 0,
                             "p_eq_mismatch": 0, "p_ineq_mismatch": 0, "n_conflict": 0,
                             "sign_mismatch": 0, "p_zero": 0, "mcp_risk": 0},
            "out-of-range": {"impossible_p": 0, "effect_range": 1, "neg_stat": 0,
                             "p_eq_mismatch": 0, "p_ineq_mismatch": 0, "n_conflict": 0,
                             "sign_mismatch": 0, "p_zero": 0, "mcp_risk": 0},
            "p-stat-mismatch": {"impossible_p": 0, "effect_range": 0, "neg_stat": 0,
                                "p_eq_mismatch": 1, "p_ineq_mismatch": 0, "n_conflict": 0,
                                "sign_mismatch": 0, "p_zero": 0, "mcp_risk": 0},
            "p-ineq-contradiction": {"impossible_p": 0, "effect_range": 0, "neg_stat": 0,
                                     "p_eq_mismatch": 0, "p_ineq_mismatch": 1, "n_conflict": 0,
                                     "sign_mismatch": 0, "p_zero": 0, "mcp_risk": 0},
            "same-line-n-conflict": {"impossible_p": 0, "effect_range": 0, "neg_stat": 0,
                                     "p_eq_mismatch": 0, "p_ineq_mismatch": 0, "n_conflict": 1,
                                     "sign_mismatch": 0, "p_zero": 0, "mcp_risk": 0},
            "sign-mismatch": {"impossible_p": 0, "effect_range": 0, "neg_stat": 0,
                              "p_eq_mismatch": 0, "p_ineq_mismatch": 0, "n_conflict": 0,
                              "sign_mismatch": 1, "p_zero": 0, "mcp_risk": 0},
            "p-zero": {"impossible_p": 0, "effect_range": 0, "neg_stat": 0,
                       "p_eq_mismatch": 0, "p_ineq_mismatch": 0, "n_conflict": 0,
                       "sign_mismatch": 0, "p_zero": 1, "mcp_risk": 0},
            "mcp-no-correction": {"impossible_p": 0, "effect_range": 0, "neg_stat": 0,
                                  "p_eq_mismatch": 0, "p_ineq_mismatch": 0, "n_conflict": 0,
                                  "sign_mismatch": 0, "p_zero": 0, "mcp_risk": 1},
            "score-n-control": {"impossible_p": 0, "effect_range": 0, "neg_stat": 0,
                                "p_eq_mismatch": 0, "p_ineq_mismatch": 0, "n_conflict": 0,
                                "sign_mismatch": 0, "p_zero": 0, "mcp_risk": 0},
            "upper-n-large": {"impossible_p": 0, "effect_range": 0, "neg_stat": 0,
                              "p_eq_mismatch": 0, "p_ineq_mismatch": 0, "n_conflict": 1,
                              "sign_mismatch": 0, "p_zero": 0, "mcp_risk": 0},
        },
        "sections": {
            "impossible_p": r"## Impossible or out-of-range p-values:\s*(\d+)",
            "effect_range": r"## Out-of-range effect sizes:\s*(\d+)",
            "neg_stat": r"## Negative statistics or zero df:\s*(\d+)",
            "p_eq_mismatch": r"## p-value vs statistic mismatch \(equality\):\s*(\d+)",
            "p_ineq_mismatch": r"## p-value vs statistic mismatch \(inequality\):\s*(\d+)",
            "n_conflict": r"## Same-line n/N conflict:\s*(\d+)",
            "sign_mismatch": r"## Sign mismatch \(statistic vs effect size\):\s*(\d+)",
            "p_zero": r"## p = 0\.000 \(APA: report p < \.001\):\s*(\d+)",
            "mcp_risk": r"## Multiple-comparison risk:\s*(\d+)",
        },
        "args": ["--fail-on-error"],
        "error_keys": ["impossible_p", "effect_range", "neg_stat", "p_eq_mismatch",
                       "p_ineq_mismatch", "n_conflict"],
    },
    "figure-claims": {
        "scanner": "scan_figure_claims.py",
        "manifest": {
            "dirty": {"missing_figure_refs": 1, "undefined_includegraphics": 1,
                      "never_mentioned": 1},
            "clean": {"missing_figure_refs": 0, "undefined_includegraphics": 0,
                      "never_mentioned": 0},
        },
        "sections": {
            "missing_figure_refs": r"## Missing_figure_refs:\s*(\d+)",
            "undefined_includegraphics": r"## Undefined_includegraphics:\s*(\d+)",
            "never_mentioned": r"## Never_mentioned:\s*(\d+)",
        },
        "args": ["--fail-on-error"],
        "error_keys": ["missing_figure_refs", "undefined_includegraphics"],
    },
    "compile-gate": {
        "scanner": "compile_gate.py",
        "manifest": {
            "clean": {"compile_errors": 0, "undefined_refs": 0, "undefined_citations": 0,
                      "multiply_labels": 0, "overfull": 0, "orphan_labels": 0,
                      "uncited_bibs": 0},
            "undefined-citation": {"compile_errors": 0, "undefined_refs": 0,
                                   "undefined_citations": 1, "multiply_labels": 0},
            "undefined-ref": {"compile_errors": 0, "undefined_refs": 1,
                              "undefined_citations": 0, "multiply_labels": 0},
            "compile-error": {"compile_errors": 1, "undefined_refs": 0,
                              "undefined_citations": 0, "multiply_labels": 0,
                              "skip_when": "compile_skipped"},
            "multiply-label": {"compile_errors": 0, "undefined_refs": 0,
                               "undefined_citations": 0, "multiply_labels": 1,
                               "skip_when": "compile_skipped"},
        },
        "sections": {
            "compile_errors": r"## Compile errors:\s*(\d+)",
            "undefined_refs": r"## Undefined references:\s*(\d+)",
            "undefined_citations": r"## Undefined citations:\s*(\d+)",
            "multiply_labels": r"## Multiply-defined labels:\s*(\d+)",
            "overfull": r"## Overfull hboxes:\s*(\d+)",
            "orphan_labels": r"## Orphan labels:\s*(\d+)",
            "uncited_bibs": r"## Uncited bib entries:\s*(\d+)",
            "compile_skipped": r"## Compile skipped:\s*(\d+)",
        },
        "args": [],
        "error_keys": ["compile_errors", "undefined_refs", "undefined_citations",
                       "multiply_labels"],
    },
}


def run_fixture(family: str, name: str, fixtures_root: Path) -> tuple[bool, str]:
    fam = FAMILIES[family]
    spec = fam["manifest"][name]
    fdir = fixtures_root / family / name
    if not fdir.is_dir():
        return False, f"fixture dir missing: {fdir}"
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "report.md"
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / fam["scanner"]), str(fdir)] + fam["args"]
            + ["--out", str(out)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180)
        report = out.read_text(encoding="utf-8", errors="ignore") if out.exists() else r.stdout
        counts = {}
        for key, pat in fam["sections"].items():
            m = re.search(pat, report)
            counts[key] = int(m.group(1)) if m else 0
        problems = []
        # 环境依赖夹具: spec 带 skip_when=<section> 且该 section 计数 > 0(如 TeX 缺失时
        # compile_skipped=1) → 该夹具 PASS(降级被记录, 不误报为失败)。
        skip_when = spec.get("skip_when")
        if skip_when and counts.get(skip_when, 0) > 0:
            return True, f"SKIP ({skip_when} 环境降级)"
        for key, want in spec.items():
            if key == "skip_when":
                continue
            got = counts.get(key, 0)
            if want > 0 and got < want:
                problems.append(f"{key}: expected >= {want}, got {got}")
            if want == 0 and got > 0:
                problems.append(f"{key}: expected 0 (false positive), got {got}")
        want_rc = 1 if any(counts.get(k, 0) > 0 for k in fam["error_keys"]) else 0
        if r.returncode != want_rc:
            problems.append(f"exit code: expected {want_rc}, got {r.returncode}")
        return (not problems), ("; ".join(problems) if problems else "OK")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", default="", help="只跑指定夹具(默认全部)")
    ap.add_argument("--family", default="", help="只跑指定族(默认全部)")
    ap.add_argument("--fixtures-root", default=str(FIXTURES_ROOT), help="夹具根目录(候选验收可覆盖)")
    args = ap.parse_args()
    fixtures_root = Path(args.fixtures_root)

    names = []
    for fam_name in FAMILIES:
        if args.family and fam_name != args.family:
            continue
        for fname in FAMILIES[fam_name]["manifest"]:
            names.append((fam_name, fname))
    if args.fixture:
        hits = [n for n in names if n[1] == args.fixture]
        if not hits:
            print(f"fixture not found: {args.fixture}")
            return 1
        names = hits

    failed = []
    for fam_name, fname in names:
        ok, msg = run_fixture(fam_name, fname, fixtures_root)
        print(f"[{'PASS' if ok else 'FAIL'}] {fam_name}/{fname}: {msg}")
        if not ok:
            failed.append(f"{fam_name}/{fname}")
    print(f"\nscanner regression: {len(names) - len(failed)}/{len(names)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
