"""paper-writing-agent: statistical power / sample-size analysis (G1).

Computes power, required sample size, or minimum detectable effect for the
statistical tests most common in TMLR manuscripts:

  --t-two-sample   two-sample (independent) t-test on means
  --t-paired       paired t-test on differences (pre/post, paired arms)
  --mcnemar        paired binary outcomes (exact McNemar, A/B defect hits)
  --proportion     one-sample proportion test (binomial)
  --correlation    Pearson correlation coefficient test

For each test, solve for exactly one unknown:
  --solve n       given effect size d, alpha, power  -> required N
  --solve power   given N, effect size d, alpha       -> achieved power
  --solve d       given N, alpha, power               -> minimum detectable effect

Implementation: scipy when available (non-central t / ncx2 / binomtest); stdlib
normal approximation fallback otherwise. Deterministic, seed-free (analytic).
Report JSON is written to --out and is suitable as evidence for the claim
ledger ("sample size justified by power analysis": Methods section).

Usage:
  python power_analysis.py --t-paired --solve n --d 0.5 --alpha 0.05 --power 0.80
  python power_analysis.py --t-two-sample --solve power --n 30 --d 0.5 --alpha 0.05
  python power_analysis.py --mcnemar --solve n --p-discordant 0.3 --or 4 --alpha 0.05 --power 0.80
  python power_analysis.py --correlation --solve d --n 40 --alpha 0.05 --power 0.80

Exit 0 = computed; exit 2 = missing/conflicting arguments or unsolvable.
"""
from __future__ import annotations

import argparse
import json
import math
import sys

try:
    from scipy import stats as _sp
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


def _z(alpha: float, two_sided: bool = True) -> float:
    if HAS_SCIPY:
        return float(_sp.norm.ppf(1 - alpha / (2 if two_sided else 1)))
    # stdlib fallback: rational approx of inverse normal CDF (Acklam)
    return _norm_ppf(1 - alpha / (2 if two_sided else 1))


def _norm_ppf(p: float) -> float:
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow = 0.02425
    if p <= 0 or p >= 1:
        return float("nan")
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p <= 1 - plow:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
           ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


# --------------------------------------------------------------------------- #
# two-sample t-test (equal n per group)
# --------------------------------------------------------------------------- #

def power_two_sample(n: int, d: float, alpha: float) -> float:
    """Independent t-test, Cohen's d = (mu1-mu2)/pooled_sd, equal groups."""
    df = 2 * (n - 1)
    nc = d * math.sqrt(n / 2.0)
    if HAS_SCIPY:
        tcrit = float(_sp.t.ppf(1 - alpha / 2, df))
        return float(_sp.nct.sf(tcrit, df, nc) + _sp.nct.cdf(-tcrit, df, nc))
    z = _z(alpha)
    return 1.0 - _norm_ppf(z - nc)


def n_two_sample(d: float, alpha: float, power: float) -> float:
    """Minimal n per group (float; ceil for integer)."""
    if HAS_SCIPY:
        lo, hi = 2, 4
        while power_two_sample(hi, d, alpha) < power:
            hi *= 2
        for _ in range(200):
            mid = (lo + hi) / 2
            if power_two_sample(int(mid), d, alpha) < power:
                lo = mid
            else:
                hi = mid
        return hi
    z = _z(alpha)
    z_b = _norm_ppf(power)
    return 2 * (z + z_b) ** 2 / (d * d)


def d_two_sample(n: int, alpha: float, power: float) -> float:
    lo, hi = 1e-6, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if power_two_sample(n, mid, alpha) < power:
            lo = mid
        else:
            hi = mid
    return hi


# --------------------------------------------------------------------------- #
# paired t-test
# --------------------------------------------------------------------------- #

def power_paired(n: int, d: float, alpha: float) -> float:
    """Paired t-test; d = mean(diff)/sd(diff)."""
    df = n - 1
    nc = d * math.sqrt(n)
    if HAS_SCIPY:
        tcrit = float(_sp.t.ppf(1 - alpha / 2, df))
        return float(_sp.nct.sf(tcrit, df, nc) + _sp.nct.cdf(-tcrit, df, nc))
    z = _z(alpha)
    return 1.0 - _norm_ppf(z - nc)


def n_paired(d: float, alpha: float, power: float) -> float:
    if HAS_SCIPY:
        lo, hi = 2, 4
        while power_paired(hi, d, alpha) < power:
            hi *= 2
        for _ in range(200):
            mid = (lo + hi) / 2
            if power_paired(int(mid), d, alpha) < power:
                lo = mid
            else:
                hi = mid
        return hi
    z = _z(alpha)
    z_b = _norm_ppf(power)
    return (z + z_b) ** 2 / (d * d)


def d_paired(n: int, alpha: float, power: float) -> float:
    lo, hi = 1e-6, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if power_paired(n, mid, alpha) < power:
            lo = mid
        else:
            hi = mid
    return hi


# --------------------------------------------------------------------------- #
# exact McNemar (paired binary), via binomial on discordant pairs
# --------------------------------------------------------------------------- #

def power_mcnemar(n_discordant: int, or_: float, alpha: float) -> float:
    """Exact McNemar power: n_discordant = expected b+c pairs, OR = b/c."""
    p_win = or_ / (1 + or_)
    # P(win >= k*) under Binomial(n, 0.5) at alpha level, then power under p_win
    k_star = _binom_crit(n_discordant, alpha)
    return _binom_sf(k_star, n_discordant, p_win)


def _binom_crit(n: int, alpha: float) -> int:
    """Smallest k such that P(X>=k | Bin(n, 0.5)) <= alpha."""
    for k in range(0, n + 1):
        if _binom_sf(k, n, 0.5) <= alpha:
            return k
    return n


def _binom_sf(k: int, n: int, p: float) -> float:
    if HAS_SCIPY:
        return float(_sp.binom.sf(k - 1, n, p))
    # stdlib: log-sum via lgamma
    s = 0.0
    for i in range(k, n + 1):
        s += math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
                      + i * math.log(p) + (n - i) * math.log1p(-p))
    return min(1.0, s)


def n_mcnemar(or_: float, alpha: float, power: float, p_discordant: float = 0.3) -> float:
    """Required total pairs: n_discordant / p_discordant.

    p_discordant = expected fraction of pairs that are discordant (b+c)/N;
    user must supply it (e.g. from pilot data or prior work).
    """
    lo, hi = 1, 8
    while power_mcnemar(hi, or_, alpha) < power:
        hi *= 2
    for _ in range(200):
        mid = (lo + hi) / 2
        if power_mcnemar(int(mid), or_, alpha) < power:
            lo = mid
        else:
            hi = mid
    return hi / p_discordant


def or_mcnemar(n_discordant: int, alpha: float, power: float) -> float:
    lo, hi = 1.0001, 1000.0
    for _ in range(120):
        mid = math.sqrt(lo * hi)
        if power_mcnemar(n_discordant, mid, alpha) < power:
            lo = mid
        else:
            hi = mid
    return hi


# --------------------------------------------------------------------------- #
# one-sample proportion (binomial)
# --------------------------------------------------------------------------- #

def power_proportion(n: int, p0: float, p1: float, alpha: float) -> float:
    """H0: p=p0 vs H1: p=p1 (p1 != p0), exact binomial power."""
    k_star = _binom_crit(n, alpha)  # under p0, two-sided approx via tails
    return _binom_sf(k_star, n, p1)


# --------------------------------------------------------------------------- #
# Pearson correlation
# --------------------------------------------------------------------------- #

def power_correlation(n: int, r: float, alpha: float) -> float:
    """H0: rho=0; approximate power via Fisher z."""
    z_obs = 0.5 * math.log((1 + r) / (1 - r)) * math.sqrt(n - 3)
    z = _z(alpha)
    return 1.0 - _norm_ppf(z - z_obs)


def n_correlation(r: float, alpha: float, power: float) -> float:
    z = _z(alpha)
    z_b = _norm_ppf(power)
    return 3 + ((z + z_b) / (0.5 * math.log((1 + r) / (1 - r)))) ** 2


def r_correlation(n: int, alpha: float, power: float) -> float:
    z = _z(alpha)
    z_b = _norm_ppf(power)
    z_obs = z + z_b
    return math.tanh(z_obs / math.sqrt(n - 3))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

TESTS = {"t-two-sample", "t-paired", "mcnemar", "proportion", "correlation"}
SOLVES = {"n", "power", "d"}


def main() -> int:
    ap = argparse.ArgumentParser(description="statistical power / sample-size analysis")
    ap.add_argument("--t-two-sample", action="store_true")
    ap.add_argument("--t-paired", action="store_true")
    ap.add_argument("--mcnemar", action="store_true")
    ap.add_argument("--proportion", action="store_true")
    ap.add_argument("--correlation", action="store_true")
    ap.add_argument("--solve", choices=sorted(SOLVES), required=True)
    ap.add_argument("--d", type=float, help="effect size (Cohen's d for t-tests)")
    ap.add_argument("--r", type=float, help="correlation coefficient")
    ap.add_argument("--or", type=float, dest="odds_ratio", help="odds ratio (mcnemar)")
    ap.add_argument("--p-discordant", type=float, default=0.3, help="expected discordant pair fraction (mcnemar, solve n)")
    ap.add_argument("--p0", type=float, help="H0 proportion")
    ap.add_argument("--p1", type=float, help="H1 proportion")
    ap.add_argument("--n", type=float, help="sample size (per group / pairs)")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--power", type=float, default=0.80)
    ap.add_argument("--out", default=None, help="JSON report path (claim-ledger evidence)")
    args = ap.parse_args()

    chosen = [t for t in TESTS if getattr(args, t.replace("-", "_"))]
    if len(chosen) != 1:
        print("FAIL: exactly one test must be selected", file=sys.stderr)
        return 2
    test = chosen[0]

    try:
        if test == "t-two-sample":
            if args.solve == "n":
                if args.d is None or args.d <= 0:
                    raise ValueError("--d required (Cohen's d)")
                val = n_two_sample(args.d, args.alpha, args.power)
                res = {"test": "two-sample t", "solve": "n per group",
                       "d": args.d, "alpha": args.alpha, "power": args.power,
                       "n_per_group": val, "n_total": 2 * val, "n_ceil": math.ceil(val)}
            elif args.solve == "power":
                if args.n is None or args.d is None:
                    raise ValueError("--n and --d required")
                p = power_two_sample(int(args.n), args.d, args.alpha)
                res = {"test": "two-sample t", "solve": "power", "n_per_group": int(args.n),
                       "d": args.d, "alpha": args.alpha, "power": p}
            else:  # d
                if args.n is None:
                    raise ValueError("--n required")
                d = d_two_sample(int(args.n), args.alpha, args.power)
                res = {"test": "two-sample t", "solve": "min detectable d",
                       "n_per_group": int(args.n), "alpha": args.alpha,
                       "power": args.power, "d_min": d}
        elif test == "t-paired":
            if args.solve == "n":
                if args.d is None or args.d <= 0:
                    raise ValueError("--d required (Cohen's d)")
                val = n_paired(args.d, args.alpha, args.power)
                res = {"test": "paired t", "solve": "n pairs",
                       "d": args.d, "alpha": args.alpha, "power": args.power,
                       "n_pairs": val, "n_ceil": math.ceil(val)}
            elif args.solve == "power":
                if args.n is None or args.d is None:
                    raise ValueError("--n and --d required")
                p = power_paired(int(args.n), args.d, args.alpha)
                res = {"test": "paired t", "solve": "power", "n_pairs": int(args.n),
                       "d": args.d, "alpha": args.alpha, "power": p}
            else:
                if args.n is None:
                    raise ValueError("--n required")
                d = d_paired(int(args.n), args.alpha, args.power)
                res = {"test": "paired t", "solve": "min detectable d",
                       "n_pairs": int(args.n), "alpha": args.alpha,
                       "power": args.power, "d_min": d}
        elif test == "mcnemar":
            if args.solve == "n":
                if args.odds_ratio is None or args.odds_ratio <= 1:
                    raise ValueError("--or required (>1)")
                nd = n_mcnemar(args.odds_ratio, args.alpha, args.power, args.p_discordant)
                res = {"test": "exact McNemar", "solve": "n total pairs",
                       "or": args.odds_ratio, "p_discordant": args.p_discordant,
                       "alpha": args.alpha, "power": args.power,
                       "n_discordant": nd * args.p_discordant,
                       "n_total": nd, "n_ceil": math.ceil(nd)}
            elif args.solve == "power":
                if args.n is None or args.odds_ratio is None:
                    raise ValueError("--n (discordant pairs) and --or required")
                p = power_mcnemar(int(args.n), args.odds_ratio, args.alpha)
                res = {"test": "exact McNemar", "solve": "power",
                       "n_discordant": int(args.n), "or": args.odds_ratio,
                       "alpha": args.alpha, "power": p}
            else:  # min detectable OR
                if args.n is None:
                    raise ValueError("--n (discordant pairs) required")
                o = or_mcnemar(int(args.n), args.alpha, args.power)
                res = {"test": "exact McNemar", "solve": "min detectable OR",
                       "n_discordant": int(args.n), "alpha": args.alpha,
                       "power": args.power, "or_min": o}
        elif test == "proportion":
            if args.solve == "n":
                if args.p0 is None or args.p1 is None:
                    raise ValueError("--p0 and --p1 required")
                lo, hi = 1, 8
                while power_proportion(hi, args.p0, args.p1, args.alpha) < args.power:
                    hi *= 2
                for _ in range(200):
                    mid = (lo + hi) / 2
                    if power_proportion(int(mid), args.p0, args.p1, args.alpha) < args.power:
                        lo = mid
                    else:
                        hi = mid
                res = {"test": "one-sample proportion", "solve": "n",
                       "p0": args.p0, "p1": args.p1, "alpha": args.alpha,
                       "power": args.power, "n": hi, "n_ceil": math.ceil(hi)}
            else:
                print("FAIL: proportion test supports --solve n only", file=sys.stderr)
                return 2
        else:  # correlation
            if args.solve == "n":
                if args.r is None:
                    raise ValueError("--r required")
                val = n_correlation(args.r, args.alpha, args.power)
                res = {"test": "Pearson correlation", "solve": "n",
                       "r": args.r, "alpha": args.alpha, "power": args.power,
                       "n": val, "n_ceil": math.ceil(val)}
            elif args.solve == "power":
                if args.n is None or args.r is None:
                    raise ValueError("--n and --r required")
                p = power_correlation(int(args.n), args.r, args.alpha)
                res = {"test": "Pearson correlation", "solve": "power",
                       "n": int(args.n), "r": args.r, "alpha": args.alpha, "power": p}
            else:
                if args.n is None:
                    raise ValueError("--n required")
                r = r_correlation(int(args.n), args.alpha, args.power)
                res = {"test": "Pearson correlation", "solve": "min detectable r",
                       "n": int(args.n), "alpha": args.alpha, "power": args.power,
                       "r_min": r}
    except ValueError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2

    res["scipy"] = HAS_SCIPY
    res["gate_rule"] = "Methods must state alpha, power, effect size, and N; "
    res["methods_note"] = _methods_note(res)
    if args.out:
        import os
        from pathlib import Path
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(res, indent=2, ensure_ascii=False))
    print("\nMethods sentence:", res["methods_note"])
    return 0


def _methods_note(res: dict) -> str:
    t = res["test"]
    a = res.get("alpha", 0.05)
    pw = res.get("power", 0.80)
    solve = res.get("solve", "")
    if solve.startswith("n"):
        n = res.get("n_ceil") or res.get("n_per_group") or res.get("n_pairs") or res.get("n_total") or res.get("n")
        eff = res.get("d") or res.get("or") or res.get("r") or f"p1={res.get('p1')}"
        return (f"With alpha={a} and power={pw}, {t} requires N={n} "
                f"to detect {eff} (effect size).")
    if solve == "power":
        n = res.get("n_per_group") or res.get("n_pairs") or res.get("n") or res.get("n_discordant")
        eff = res.get("d") or res.get("or") or res.get("r")
        return (f"With alpha={a} and N={n}, {t} achieves power={res['power']:.3f} "
                f"for effect {eff}.")
    # min detectable
    n = res.get("n_per_group") or res.get("n_pairs") or res.get("n")
    eff = res.get("d_min") or res.get("or_min") or res.get("r_min")
    return (f"With alpha={a}, power={pw} and N={n}, {t} can detect effect {eff}.")


def _selftest() -> int:
    """Cross-check against textbook values (Cohen 1988 power tables)."""
    ok = True
    # paired t, d=0.5, alpha=0.05, power=0.80 -> n=34 (classic)
    n = n_paired(0.5, 0.05, 0.80)
    if not (33 <= n <= 35):
        ok = False
        print(f"SELFTEST FAIL paired n: {n}")
    # two-sample t, n=30/group, d=0.5 -> power ~0.478
    p = power_two_sample(30, 0.5, 0.05)
    if not (0.45 <= p <= 0.50):
        ok = False
        print(f"SELFTEST FAIL two-sample power: {p}")
    # correlation n=40 -> r_min ~0.43
    r = r_correlation(40, 0.05, 0.80)
    if not (0.40 <= r <= 0.46):
        ok = False
        print(f"SELFTEST FAIL corr r_min: {r}")
    # McNemar: OR=4, nd=20 -> power reasonable
    pm = power_mcnemar(20, 4.0, 0.05)
    if not (0.5 <= pm <= 0.95):
        ok = False
        print(f"SELFTEST FAIL mcnemar power: {pm}")
    print(f"selftest: {'PASS' if ok else 'FAIL'} "
          f"(paired n={n:.1f}, two-sample p={p:.3f}, r_min={r:.3f}, mcnemar p={pm:.3f})")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main())
