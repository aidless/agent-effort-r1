"""paper-writing-agent: statistical-consistency scanner.

Machine-checkable INTERNAL consistency of the statistics reported in the
manuscript text (tex/md/txt). It does NOT recompute results from raw data
(that is verify_claim_ledger / independent_recompute's job); it verifies that
the numbers the paper itself reports are coherent and APA-plausible:

  (E) impossible p-values (p < 0 or p > 1) and impossible bounds
  (E) out-of-range effect sizes (eta2/R2/omega2/CramerV/CLES/AUC not in [0,1];
      r/rho/phi not in [-1,1]; adjusted R2 exempt from the lower bound)
  (E) negative F/chi2 or zero df
  (E) p-value contradicts the recomputed two-sided p of a co-located
      statistic: t(df), z, chi2(df), F(df1,df2)  (stdlib CDFs, no scipy)
  (E) p-value inequality contradicts the recomputed p ("p < 0.001" but
      recomputed p = 0.023)
  (E) same-line n/N conflict ("n = 30" and "n = 40" on one line, no
      per-group qualifier)
  (W) sign mismatch between t/z and a co-located effect size (d/r)
  (W) "p = 0.000" (APA: report as p < .001)
  (W) multiple-comparison risk: >= --mcp-threshold significance claims and
      no correction term (FDR/Bonferroni/Holm/Tukey/...) anywhere in the doc
  (I) df >= any n in the same window (plausibility note, not a verdict)
  (I) r/t/n triple present (Pearson relation t = r*sqrt((n-2)/(1-r^2)))
  (I) statistic-p pairs found but not recomputable (U/W/H/tau/...)

Report sections carry machine-readable "## Section: <count>" lines so
scanner_regression.py can assert hits; paths are rendered relative to the
target for byte-reproducible reports (FM-24); process documents and
verification scaffolding are excluded like the sibling scanners.

Usage:
  python scan_stats_consistency.py <dir_or_file> [--out report.md]
       [--fail-on-error] [--mcp-threshold 10] [--exclude-dir ...]
       [--exclude-name ...]

Exit 0 = report-only (or clean with --fail-on-error);
exit 1 = ERROR-level findings with --fail-on-error.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# numeric core: stdlib-only CDFs (Numerical Recipes 6.2/6.4 style)
# ---------------------------------------------------------------------------


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _betacf(a: float, b: float, x: float, itmax: int = 300, eps: float = 3e-12) -> float:
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                  + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_two_sided_p(t: float, df: float):
    """Two-sided p of |T| under Student-t with df degrees of freedom."""
    if df <= 0:
        return None
    if df > 1000:
        return 2.0 * (1.0 - _normal_cdf(abs(t)))
    x = df / (df + t * t)
    return _betai(df / 2.0, 0.5, x)


def _gammp_series(a: float, x: float, itmax: int = 300, eps: float = 3e-12) -> float:
    ap = a
    s = 1.0 / a
    d = 1.0 / a
    for _ in range(itmax):
        ap += 1.0
        d *= x / ap
        s += d
        if abs(d) < abs(s) * eps:
            break
    return s * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gammq_cf(a: float, x: float, itmax: int = 300, eps: float = 3e-12) -> float:
    fpm = 1e-300
    b = x + 1.0 - a
    c = 1.0 / fpm
    d = 1.0 / b if abs(b) > fpm else 1e30
    h = d
    for i in range(1, itmax + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < fpm:
            d = fpm
        c = b + an / c
        if abs(c) < fpm:
            c = fpm
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def _gammp(a: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x < a + 1.0:
        return _gammp_series(a, x)
    return 1.0 - _gammq_cf(a, x)


def chi2_p_upper(x: float, df: float):
    """Upper-tail p of chi^2 = x with df degrees of freedom."""
    if df <= 0 or x < 0:
        return None
    if df > 1000:
        z = (x - df) / math.sqrt(2.0 * df)
        return 1.0 - _normal_cdf(z)
    return 1.0 - _gammp(df / 2.0, x / 2.0)


def f_p_upper(f: float, d1: float, d2: float):
    """Upper-tail p of F = f with (d1, d2) degrees of freedom."""
    if d1 <= 0 or d2 <= 0 or f < 0:
        return None
    x = d1 * f / (d1 * f + d2)
    return 1.0 - _betai(d1 / 2.0, d2 / 2.0, x)


# ---------------------------------------------------------------------------
# text scaffolding (same conventions as scan_number_consistency.py)
# ---------------------------------------------------------------------------

TEXT_SUFFIX = {".tex", ".md", ".txt"}
DEFAULT_EXCLUDE = {"reports", ".git", "__pycache__", "node_modules", "build", "dist", "assets"}
VERIFY_PREFIX_EXCLUDE = (".r", "._", "tmp_r", ".tmp_", ".verify", "_verify", "verify_", ".review_", ".compile")
VERIFY_SUFFIX_EXCLUDE = ("_verify", "_check", "_backup", "_fixedpoint", "_rebuild", "_compile", ".tmpdir")
PROCESS_DOC_PREFIXES = ("ROUND_R", "REVIEW_R", "SELF_ASSESSMENT")
PROCESS_DOC_SUFFIXES = (".summary.md", "_R7_ethics.md")


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


def iter_text_files(root: Path, exclude: set, exclude_names: list):
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in TEXT_SUFFIX and not excluded(p.relative_to(root), exclude):
            if any(sub in p.name for sub in exclude_names):
                continue
            if is_process_doc(p.name):
                continue
            yield p


# ---------------------------------------------------------------------------
# patterns
# ---------------------------------------------------------------------------

NUM = r"[-+]?[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?"
DF = r"[0-9]+(?:\.[0-9]+)?"

STAT_T_RE = re.compile(r"t\s*\(\s*(" + DF + r")\s*\)\s*=\s*(" + NUM + r")")
STAT_F_RE = re.compile(r"F\s*\(\s*(" + DF + r")\s*,\s*(" + DF + r")\s*\)\s*=\s*(" + NUM + r")")
SUP2 = r"(?:\^?\s*2|²)"
STAT_CHI_RE = re.compile(
    r"(?:χ\s*" + SUP2 + r"|\\?chi\s*" + SUP2 + r"|chi\s*-?\s*square|chi2|X\s*" + SUP2 + r"|X2)\s*\(\s*(" + DF + r")\s*\)\s*=\s*(" + NUM + r")")
STAT_Z_RE = re.compile(r"\bz\s*=\s*(" + NUM + r")")
# statistics we cannot recompute (Mann-Whitney U, Wilcoxon W, Kruskal-Wallis H,
# Kendall tau, ...): only counted when a p-value sits in the same window.
STAT_OTHER_RE = re.compile(r"\b(?:U|W|H|τ|tau|K)\s*=\s*(" + NUM + r")")

# p-values MUST carry a decimal point or exponent form (bare integers like
# "p=3" are TikZ layout params, e.g. "sep=1.20cm" / "top=3pt", or variables);
# \b prevents matching the trailing "p" of words like "sep" / "top" / "group".
PVAL = r"(\.\d+|\d+\.\d+(?:[eE][-+]?\d+)?|\d+[eE][-+]?\d+)"
P_EQ_RE = re.compile(r"\bp\s*=\s*(" + PVAL + r")")
P_LE_RE = re.compile(r"\bp\s*[<≤]\s*=\s*(" + PVAL + r")")
P_GE_RE = re.compile(r"\bp\s*[>≥]\s*=\s*(" + PVAL + r")")
P_LT_RE = re.compile(r"\bp\s*[<≤]\s*(" + PVAL + r")")
P_GT_RE = re.compile(r"\bp\s*[>≥]\s*(" + PVAL + r")")
ALL_P_RES = [P_EQ_RE, P_LE_RE, P_GE_RE, P_LT_RE, P_GT_RE]

# effect sizes with a hard range
ES_01 = [
    (re.compile(r"(?:η\s*" + SUP2 + r"|eta\s*\^?\s*2|η2|eta2)\s*=\s*(" + NUM + r")"), "eta2"),
    (re.compile(r"\bR\s*" + SUP2 + r"\s*=\s*(" + NUM + r")"), "R2"),
    (re.compile(r"(?:ω\s*" + SUP2 + r"|omega\s*\^?\s*2|ω2|omega2)\s*=\s*(" + NUM + r")"), "omega2"),
    (re.compile(r"(?:Cram[ée]r'?s?\s+V)\s*=\s*(" + NUM + r")"), "CramerV"),
    (re.compile(r"\bCLES\s*=\s*(" + NUM + r")"), "CLES"),
    (re.compile(r"\bAUC\s*=\s*(" + NUM + r")"), "AUC"),
]
ES_N1_1 = [
    (re.compile(r"\br\s*=\s*(" + NUM + r")"), "r"),
    (re.compile(r"(?:ρ|rho)\s*=\s*(" + NUM + r")"), "rho"),
    (re.compile(r"φ\s*=\s*(" + NUM + r")"), "phi"),
]
ES_D = re.compile(r"\bd\s*=\s*(" + NUM + r")")

N_RE = re.compile(r"\b[nN]\s*=\s*([0-9]+)")
# 带大小写捕获的变体, 仅用于同行冲突判定: 大写 N 且值 ≤ 5 视为评分/维度语义
# (TMLR 新颖性维 N 为 1-5 分, 如 "N=2 升级为 N=4"), 不参与样本量冲突判定;
# 小写 n 恒参与; 大写 N > 5 视为样本量(R52 实证假阳性类, 2026-08-15)。
# 2026-10-09 修正：负向后行 (?<!/) —— `adjudicated_flips/n = 24/60` 这类
# 「分子/n = a/b」公式记法中，n 是分母不是样本量声明（实测 C83 行被误判
# n=60 与 n=24 冲突）。真实声明（"n = 24"）前面不会有除号。
N_CASE_RE = re.compile(r"(?<!/)\b([nN])\s*=\s*([0-9]+)(?!\.[0-9])")
N_QUALIFIER_RE = re.compile(r"per group|each group|per condition|per arm|respectively|subgroup|per seed|per run|per fold|\bvs\.?\b|versus|compared with|compared to|对比|->|⇒|×|per unit|单元|重复", re.IGNORECASE)
# 2026-10-08 增补：->/⇒/×/单元/重复 —— 对照箭头与推导记法（H4_PSEUDOREPLICATION 的
# n=48 vs n=16 两层对比、C52 的 240=80×3⇒n=16 推导）是刻意的统计分层表述，
# 不是样本量冲突；沿用既有 qualifier 豁免机制，命中仍计入报告但降为可解释项。
CORRECTION_RE = re.compile(
    r"\b(FDR|Benjamini[- ]Hochberg|Bonferroni|Holm|Tukey|Šidák|Sidak|false discovery|correction|corrected|adjust(?:ed|ment)?|family[- ]wise|post[- ]hoc)\b",
    re.IGNORECASE)
ADJUSTED_RE = re.compile(r"adjusted", re.IGNORECASE)
ZERO_P_RE = re.compile(r"^0+\.0+$|^\.0+$|^0$")

WINDOW_FWD = 400
WINDOW_BACK = 300


def _to_float(s: str):
    s = s.strip()
    if s.startswith("."):
        s = "0" + s
    try:
        return float(s)
    except ValueError:
        return None


def _line(text: str, pos: int) -> int:
    return text[:pos].count("\n") + 1


class Finding:
    __slots__ = ("section", "severity", "file", "line", "snippet")

    def __init__(self, section: str, severity: str, file: str, line: int, snippet: str):
        self.section = section
        self.severity = severity
        self.file = file
        self.line = line
        self.snippet = snippet


def _latex_sci_to_e(s: str) -> str:
    import re as _re
    # convert 8.69\times10^{-6} to 8.69e-06
    s = _re.sub(r"(\d+\.\d+)\s*(?:\\times|\u00d7)\s*10\s*\^\{(-?\d+)\}", lambda m: f"{m.group(1)}e{m.group(2)}", s)
    # also handle \times10^-6 without braces
    s = _re.sub(r"(\d+\.\d+)\s*(?:\\times|\u00d7)\s*10\^-(\d+)", lambda m: f"{m.group(1)}e-{m.group(2)}", s)
    return s

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", help="dir or file (--selftest ignores)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--fail-on-error", action="store_true")
    ap.add_argument("--mcp-threshold", type=int, default=10,
                    help="significance-claim count at which the multiple-comparison warning fires")
    ap.add_argument("--exclude-dir", default="reports,.git,__pycache__,node_modules,build,dist,tmp,assets")
    ap.add_argument("--exclude-name", default="")
    ap.add_argument("--selftest", action="store_true", help="run selftest and exit")
    args = ap.parse_args()

    if args.selftest:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "main.tex").write_text(
                "We report p = 0.000 and p = 0.05.\n", encoding="utf-8")
            text = (root / "main.tex").read_text(encoding="utf-8", errors="ignore")
            hit_eq = bool(P_EQ_RE.search(text))
            ok = hit_eq and "0.000" in text
            print(f"selftest: p_eq_pattern_hit={hit_eq} p_zero_present={'0.000' in text}: "
                  f"{'PASS' if ok else 'FAIL'}")
            return 0 if ok else 1

    if not args.target:
        ap.error("target required (or use --selftest)")
    root = Path(args.target)

    root = Path(args.target)
    if root.is_file():
        targets = [root]
    else:
        exclude = set(DEFAULT_EXCLUDE) | {s.strip() for s in args.exclude_dir.split(",") if s.strip()}
        if args.out:
            out_dir = Path(args.out).resolve().parent
            if out_dir != root.resolve():
                exclude.add(out_dir.name)
        exclude_names = [s.strip() for s in args.exclude_name.split(",") if s.strip()]
        targets = list(iter_text_files(root, exclude, exclude_names))

    root_abs = root if root.is_dir() else root.parent
    root_abs = root_abs.resolve()
    target_name = "paper"

    def show(p: Path) -> str:
        try:
            return p.resolve().relative_to(root_abs).as_posix()
        except ValueError:
            return p.name

    findings: list[Finding] = []
    sig_claims = 0
    correction_mentioned = False
    n_inventory: dict[str, int] = {}
    pairs_checked = 0
    pairs_unverifiable = 0

    for f in targets:
        text = _latex_sci_to_e(f.read_text(encoding="utf-8", errors="ignore"))
        rel = show(f)

        if CORRECTION_RE.search(text):
            correction_mentioned = True

        # --- p-value sanity -------------------------------------------------
        for p_re in (P_EQ_RE, P_LE_RE, P_GE_RE, P_LT_RE, P_GT_RE):
            for m in p_re.finditer(text):
                v = _to_float(m.group(1))
                if v is None:
                    continue
                if p_re is P_EQ_RE:
                    if v < 0 or v > 1:
                        findings.append(Finding("impossible_p", "E", rel, _line(text, m.start()),
                                                f"impossible p-value {m.group(0)}"))
                    elif v == 0.0 and ZERO_P_RE.match(m.group(1)):
                        findings.append(Finding("p_zero", "W", rel, _line(text, m.start()),
                                                f"{m.group(0)}: APA reports tiny p as 'p < .001'"))
                    elif v <= 0.05:
                        sig_claims += 1
                elif p_re in (P_LT_RE, P_LE_RE):
                    if v > 1 or v < 0:
                        findings.append(Finding("impossible_p", "E", rel, _line(text, m.start()),
                                                f"impossible p bound {m.group(0)}"))
                    elif v <= 0.05:
                        sig_claims += 1
                else:  # GT / GE
                    if v > 1 or v < 0:
                        findings.append(Finding("impossible_p", "E", rel, _line(text, m.start()),
                                                f"impossible p bound {m.group(0)}"))

        # --- effect-size range ----------------------------------------------
        for es_re, name in ES_01:
            for m in es_re.finditer(text):
                v = _to_float(m.group(1))
                if v is None:
                    continue
                lower = -1.0 if (name == "R2" and ADJUSTED_RE.search(text[max(0, m.start() - 40):m.start()])) else 0.0
                if v < lower or v > 1.0:
                    findings.append(Finding("effect_range", "E", rel, _line(text, m.start()),
                                            f"{name} = {v} outside [0,1]"))
        for es_re, name in ES_N1_1:
            for m in es_re.finditer(text):
                v = _to_float(m.group(1))
                if v is None:
                    continue
                if v < -1.0 or v > 1.0:
                    findings.append(Finding("effect_range", "E", rel, _line(text, m.start()),
                                            f"{name} = {v} outside [-1,1]"))

        # --- negative F/chi2, zero df ---------------------------------------
        for m in STAT_F_RE.finditer(text):
            d1, d2, val = _to_float(m.group(1)), _to_float(m.group(2)), _to_float(m.group(3))
            if d1 is None or d2 is None or val is None:
                continue
            if d1 <= 0 or d2 <= 0 or val < 0:
                findings.append(Finding("neg_stat", "E", rel, _line(text, m.start()),
                                        f"invalid F: F({m.group(1)},{m.group(2)}) = {m.group(3)}"))
        for m in STAT_CHI_RE.finditer(text):
            df, val = _to_float(m.group(1)), _to_float(m.group(2))
            if df is None or val is None:
                continue
            if df <= 0 or val < 0:
                findings.append(Finding("neg_stat", "E", rel, _line(text, m.start()),
                                        f"invalid chi2: chi2({m.group(1)}) = {m.group(2)}"))
        for m in STAT_T_RE.finditer(text):
            df = _to_float(m.group(1))
            if df is not None and df <= 0:
                findings.append(Finding("neg_stat", "E", rel, _line(text, m.start()),
                                        f"invalid df: t({m.group(1)})"))

        # --- same-line n/N conflict ------------------------------------------
        for ln, line in enumerate(text.splitlines(), 1):
            hits = N_CASE_RE.findall(line)
            vals = [int(v) for c, v in hits if c == "n" or int(v) > 5]
            if len(vals) > 1 and len(set(vals)) > 1:
                if N_QUALIFIER_RE.search(line):
                    continue
                findings.append(Finding("n_conflict", "E", rel, ln,
                                        f"conflicting sample sizes on one line: {line.strip()[:140]}"))

        # --- n inventory ------------------------------------------------------
        for m in N_RE.finditer(text):
            key = m.group(1)
            n_inventory[key] = n_inventory.get(key, 0) + 1

        # --- statistic <-> p pairing -----------------------------------------
        stats = []
        for m in STAT_T_RE.finditer(text):
            stats.append(("t", m, _to_float(m.group(1)), _to_float(m.group(2)), None))
        for m in STAT_Z_RE.finditer(text):
            stats.append(("z", m, None, _to_float(m.group(1)), None))
        for m in STAT_CHI_RE.finditer(text):
            stats.append(("chi2", m, _to_float(m.group(1)), _to_float(m.group(2)), None))
        for m in STAT_F_RE.finditer(text):
            stats.append(("f", m, _to_float(m.group(1)), _to_float(m.group(2)), _to_float(m.group(3))))
        for m in STAT_OTHER_RE.finditer(text):
            stats.append(("other", m, None, _to_float(m.group(1)), None))

        p_matches = []
        for p_re in ALL_P_RES:
            for m in p_re.finditer(text):
                p_matches.append((m.start(), p_re, m))

        for kind, m, p1, p2, p3 in stats:
            if p1 is None or p2 is None or (kind == "f" and p3 is None):
                continue
            start = m.start()
            lo = max(0, start - WINDOW_BACK)
            hi = min(len(text), m.end() + WINDOW_FWD)
            window = text[lo:hi]
            # nearest p match inside the window
            best = None
            best_dist = None
            for ppos, p_re, pm in p_matches:
                if lo <= ppos <= hi:
                    dist = min(abs(ppos - start), abs(ppos - m.end()))
                    if best_dist is None or dist < best_dist:
                        best_dist = dist
                        best = (p_re, pm)
            if best is None:
                continue

            p_re, pm = best
            stated = _to_float(pm.group(1))
            if stated is None:
                continue
            if kind == "other":
                pairs_unverifiable += 1
                continue
            pairs_checked += 1

            if kind == "t":
                rec = t_two_sided_p(p2, p1)
            elif kind == "z":
                rec = 2.0 * (1.0 - _normal_cdf(abs(p2)))
            elif kind == "chi2":
                rec = chi2_p_upper(p2, p1)
            else:
                rec = f_p_upper(p3, p1, p2)
            if rec is None:
                continue

            if p_re is P_EQ_RE:
                if abs(rec - stated) > max(0.01, 0.2 * stated):
                    findings.append(Finding("p_eq_mismatch", "E", rel, _line(text, m.start()),
                                            f"{m.group(0)} with {pm.group(0)}: recomputed p = {rec:.4f}"))
            elif p_re in (P_LT_RE, P_LE_RE):
                bad = (rec >= stated) if p_re is P_LT_RE else (rec > stated)
                if bad:
                    findings.append(Finding("p_ineq_mismatch", "E", rel, _line(text, m.start()),
                                            f"{m.group(0)} with {pm.group(0)}: recomputed p = {rec:.4f} contradicts the inequality"))
            else:  # GT / GE
                bad = (rec <= stated) if p_re is P_GT_RE else (rec < stated)
                if bad:
                    findings.append(Finding("p_ineq_mismatch", "E", rel, _line(text, m.start()),
                                            f"{m.group(0)} with {pm.group(0)}: recomputed p = {rec:.4f} contradicts the inequality"))

            # sign mismatch between t/z and co-located d/r
            if kind in ("t", "z"):
                for es_re, name in [(ES_D, "d"), (ES_N1_1[0][0], "r")]:
                    for em in es_re.finditer(window):
                        ev = _to_float(em.group(1))
                        if ev is None or ev == 0.0:
                            continue
                        if (p2 > 0) != (ev > 0):
                            findings.append(Finding("sign_mismatch", "W", rel, _line(text, m.start()),
                                                    f"{m.group(0)} (sign {'+' if p2 > 0 else '-'}) vs {name} = {ev}: sign mismatch"))
                            break

            # Pearson r/t/n triple (INFO)
            if kind == "t":
                ns = [int(v) for v in N_RE.findall(window)]
                if ns:
                    max_n = max(ns)
                    if p1 > max_n:
                        findings.append(Finding("df_vs_n", "I", rel, _line(text, m.start()),
                                                f"t(df={p1:g}) exceeds nearby n = {max_n}: check the df"))
                rms = ES_N1_1[0][0].findall(window)
                ns2 = [int(v) for v in N_RE.findall(window)]
                if rms and ns2:
                    rv = _to_float(rms[0])
                    n0 = max(ns2)
                    if rv is not None and -1.0 < rv < 1.0 and n0 >= 3:
                        t_rec = rv * math.sqrt((n0 - 2) / (1.0 - rv * rv))
                        if abs(t_rec - p2) > max(0.5, 0.15 * abs(p2)):
                            findings.append(Finding("r_t_n_triple", "I", rel, _line(text, m.start()),
                                                    f"r = {rv} with n = {n0} implies t = {t_rec:.2f}, but t = {p2} reported"))

        # --- df-vs-n for F/chi2 (INFO) ---------------------------------------
        for m in STAT_F_RE.finditer(text):
            d1, d2 = _to_float(m.group(1)), _to_float(m.group(2))
            window = text[max(0, m.start() - WINDOW_BACK):m.end() + WINDOW_FWD]
            ns = [int(v) for v in N_RE.findall(window)]
            if ns and d1 is not None and d2 is not None:
                max_n = max(ns)
                if d2 > max_n:
                    findings.append(Finding("df_vs_n", "I", rel, _line(text, m.start()),
                                            f"F df2 = {d2:g} exceeds nearby n = {max_n}: check the df"))

    # --- multiple-comparison risk (document level) ---------------------------
    if sig_claims >= args.mcp_threshold and not correction_mentioned:
        findings.append(Finding("mcp_risk", "W", target_name, 0,
                                f"{sig_claims} significance claims and no multiple-comparison correction term found (threshold {args.mcp_threshold})"))

    # ---------------------------------------------------------------------------
    sections = [
        ("impossible_p", "Impossible or out-of-range p-values"),
        ("effect_range", "Out-of-range effect sizes"),
        ("neg_stat", "Negative statistics or zero df"),
        ("p_eq_mismatch", "p-value vs statistic mismatch (equality)"),
        ("p_ineq_mismatch", "p-value vs statistic mismatch (inequality)"),
        ("n_conflict", "Same-line n/N conflict"),
        ("sign_mismatch", "Sign mismatch (statistic vs effect size)"),
        ("p_zero", "p = 0.000 (APA: report p < .001)"),
        ("mcp_risk", "Multiple-comparison risk"),
        ("df_vs_n", "df-vs-n plausibility notes (info)"),
        ("r_t_n_triple", "r/t/n triple notes (info)"),
        ("unverifiable", "Unverifiable statistic-p pairs (info)"),
    ]
    counts = {name: 0 for name, _ in sections}
    by_section: dict[str, list[Finding]] = {name: [] for name, _ in sections}
    for fd in findings:
        counts[fd.section] += 1
        by_section[fd.section].append(fd)

    lines = [f"# Statistical consistency scan report"]
    lines.append(f"\nTarget: `{target_name}`  |  text files: {len(targets)}  |  stat-p pairs checked: {pairs_checked}  |  unverifiable pairs: {pairs_unverifiable}")
    for name, title in sections:
        lines.append(f"\n## {title}: {counts[name]}")
        for fd in by_section[name]:
            if fd.line:
                lines.append(f"- [{fd.severity}] {fd.snippet} @ {fd.file}:{fd.line}")
            else:
                lines.append(f"- [{fd.severity}] {fd.snippet}")
    inv = ", ".join(f"n={k} x{c}" for k, c in sorted(n_inventory.items(), key=lambda kv: -kv[1]))
    lines.append(f"\n## Sample-size declarations: {inv if inv else '(none)'}")

    report = "\n".join(lines)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
    print(report)

    error_keys = {"impossible_p", "effect_range", "neg_stat", "p_eq_mismatch", "p_ineq_mismatch", "n_conflict"}
    has_error = any(counts[k] > 0 for k in error_keys)
    if args.fail_on_error and has_error:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
