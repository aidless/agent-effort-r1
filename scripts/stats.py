"""统计协议(实验方案文档 §2-§4):exact McNemar / Wilcoxon / Friedman+Nemenyi / CLES。

scipy 可用则用它;否则 exact McNemar 退化为标准库精确二项实现。
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

# --------------------------------------------------------------------------- #
# exact McNemar(配对二分类)
# --------------------------------------------------------------------------- #

def _binom_cdf_ge(k: int, n: int, p: float = 0.5) -> float:
    """P(X >= k | Binomial(n, p)),标准库精确计算(避免大数溢出用对数)。"""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    log_sum = 0.0
    # 从 k 到 n 求和:用 1 - CDF(k-1) 更稳,但小 n 直接求和即可
    for i in range(k, n + 1):
        log_sum += math.exp(
            math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
            + i * math.log(p) + (n - i) * math.log1p(-p)
        )
    return min(1.0, log_sum)


def exact_mcnemar(b: int, c: int, alternative: str = "two-sided") -> tuple[float, float]:
    """b: A 赢 B 输;c: B 赢 A 输。

    返回 (p, odds_ratio)。n = b + c,双侧 = 2 * min(P(X>=max), P(X<=min)) 截断到 1。
    """
    n = b + c
    if n == 0:
        return 1.0, float("nan")
    m = max(b, c)
    if alternative == "greater":
        p = _binom_cdf_ge(b, n, 0.5)
    elif alternative == "less":
        p = 1.0 - _binom_cdf_ge(b, n, 0.5) + _binom_cdf_ge(n + 1, n, 0.5)  # P(X <= b-1)
        p = max(0.0, min(1.0, p))
    else:  # two-sided
        p = 2.0 * _binom_cdf_ge(m, n, 0.5)
        p = min(1.0, p)
    odds = b / c if c else float("inf")
    return p, odds


def mcnemar_scipy(b: int, c: int) -> tuple[float, float]:
    """scipy 精确版(若有),与标准库实现交叉验证。"""
    try:
        from scipy.stats import binomtest
    except ImportError:
        return exact_mcnemar(b, c)
    t = binomtest(b, b + c, 0.5, alternative="two-sided")
    return float(t.pvalue), (b / c if c else float("inf"))


# --------------------------------------------------------------------------- #
# Wilcoxon signed-rank(配对连续)
# --------------------------------------------------------------------------- #

def wilcoxon_signed_rank(a: Sequence[float], b: Sequence[float]) -> dict[str, Any]:
    """配对差值检验;返回 W、p、n_eff(剔零后)、CLES。

    scipy 可用则用 scipy.stats.wilcoxon(zero_method='wilcox');
    否则对 n<=25 精确枚举,更大用正态近似(足够论文前期)。
    """
    d = [x - y for x, y in zip(a, b)]
    nonzero = [x for x in d if x != 0.0]
    n = len(nonzero)
    if n == 0:
        return {"w": None, "p": 1.0, "n": 0, "n_zero": len(d), "cles": 0.5}
    cles = sum(1.0 if x < 0 else (0.5 if x == 0 else 0.0) for x in d) / len(d)
    try:
        from scipy.stats import wilcoxon as _sw

        res = _sw(a, b, zero_method="wilcox", alternative="two-sided")
        return {"w": float(res.statistic), "p": float(res.pvalue), "n": n,
                "n_zero": len(d) - n, "cles": round(cles, 4)}
    except ImportError:
        pass
    # -- 标准库回退:精确枚举(小 n)------------------------------------------
    ranks = {abs(x): 0.0 for x in nonzero}
    for i, v in enumerate(sorted(ranks), 1):
        ranks[v] = i  # 无并列简化;并列需平均秩(见坑清单)
    w_plus = sum(ranks[abs(x)] for x in nonzero if x > 0)
    w_minus = sum(ranks[abs(x)] for x in nonzero if x < 0)
    w = min(w_plus, w_minus)
    if n <= 25:
        total = 1 << n
        count_le = 0
        for mask in range(total):
            s = sum(i + 1 for i in range(n) if (mask >> i) & 1)
            if s <= w:
                count_le += 1
        p = 2.0 * count_le / total
        p = min(1.0, p)
    else:
        mu = n * (n + 1) / 4.0
        sigma = math.sqrt(n * (n + 1) * (2 * n + 1) / 24.0)
        z = (w - mu) / sigma
        p = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2))))
    return {"w": float(w), "p": float(p), "n": n, "n_zero": len(d) - n,
            "cles": round(cles, 4)}


# --------------------------------------------------------------------------- #
# Friedman + Nemenyi(多系统 × 多数据集)
# --------------------------------------------------------------------------- #

def friedman_nemenyi(matrix: Sequence[Sequence[float]], labels: Sequence[str],
                     minimize: bool = True) -> dict[str, Any]:
    """matrix: 行=数据集, 列=系统。返回 Friedman p + 平均排名 + CD + 两两显著矩阵。

    依赖 scikit-posthocs(或 scipy 的 friedmanchisquare 回退)。
    """
    import numpy as np

    arr = np.asarray(matrix, dtype=float)
    k, n = arr.shape[1], arr.shape[0]
    try:
        import scikit_posthocs as sp
        from scipy.stats import friedmanchisquare, studentized_range

        stat, p_f = friedmanchisquare(*[arr[:, j] for j in range(k)])
        # scikit-posthocs >= 0.13: 无 friedman_test/critical_difference_ranks,
        # 用 scipy friedmanchisquare + posthoc_nemenyi_friedman; CD 用
        # studentized_range 公式(Demsar 2006): q_alpha * sqrt(k(k+1)/(12N))
        posthoc = sp.posthoc_nemenyi_friedman(arr)
        q_alpha = float(studentized_range.ppf(1 - 0.05, k, float("inf")))
        cd = q_alpha * math.sqrt(k * (k + 1) / (12.0 * n))
        sig = {labels[i]: {labels[j]: bool(posthoc.iloc[i, j] < 0.05)
                           for j in range(k) if i != j} for i in range(k)}
        ranks = np.mean(np.argsort(arr if minimize else -arr, axis=1), axis=0) + 1
        return {"friedman_stat": float(stat), "p": float(p_f), "k": k, "n": n,
                "cd": float(cd), "ranks": dict(zip(labels, ranks.tolist())),
                "significant": sig}
    except ImportError:
        from scipy.stats import friedmanchisquare

        stat, p_f = friedmanchisquare(*[arr[:, j] for j in range(k)])
        return {"friedman_stat": float(stat), "p": float(p_f), "k": k, "n": n,
                "cd": None, "ranks": None, "significant": None,
                "note": "scikit-posthocs missing: CD/Nemenyi skipped"}


# --------------------------------------------------------------------------- #
# Bootstrap CI(A6, AIRS-Bench create_summary_plots 模式)
# --------------------------------------------------------------------------- #

def bootstrap_ci(values: Sequence[float], n_boot: int = 1000, alpha: float = 0.05,
                 seed: int | None = 300) -> dict[str, Any]:
    """均值 bootstrap 置信区间(分位法)。

    values: 多 seed 观测(一个系统/臂的多个 run);返回 mean、95% CI、n。
    seed 默认 300(EXGENTIC Benchmark.seed 同款),保证可复现。
    无 numpy 时退化为手写重采样(标准库 random)。
    """
    import random

    vals = [float(v) for v in values]
    n = len(vals)
    if n == 0:
        return {"mean": None, "ci_low": None, "ci_high": None, "n": 0, "n_boot": 0}
    mean = sum(vals) / n
    rng = random.Random(seed)
    if n_boot <= 0:
        return {"mean": mean, "ci_low": None, "ci_high": None, "n": n, "n_boot": 0}
    try:
        import numpy as np

        arr = np.asarray(vals)
        boots = [float(np.mean(rng.choices(list(arr), k=n))) for _ in range(n_boot)]
    except ImportError:
        boots = [sum(rng.choices(vals, k=n)) / n for _ in range(n_boot)]
    boots.sort()
    lo = int(round(n_boot * alpha / 2.0)) - 1
    hi = int(round(n_boot * (1 - alpha / 2.0))) - 1
    lo = max(0, min(lo, n_boot - 1))
    hi = max(0, min(hi, n_boot - 1))
    return {"mean": round(mean, 6), "ci_low": round(boots[lo], 6),
            "ci_high": round(boots[hi], 6), "n": n, "n_boot": n_boot,
            "seed": seed}


def summarize_multi_seed(results: Sequence[dict], key: str = "score",
                         n_boot: int = 1000, alpha: float = 0.05,
                         seed: int = 300) -> dict[str, Any]:
    """多 seed 汇总(AIRS-Bench leaderboard 式): mean ± std + bootstrap CI。

    results: [{"seed": 1, "score": 0.62}, ...] 或 [0.62, 0.71, ...]。
    """
    if results and isinstance(results[0], dict):
        vals = [float(r[key]) for r in results]
    else:
        vals = [float(r) for r in results]
    n = len(vals)
    if n == 0:
        return {"mean": None, "std": None, "n": 0}
    mean = sum(vals) / n
    std = (sum((v - mean) ** 2 for v in vals) / max(n - 1, 1)) ** 0.5
    ci = bootstrap_ci(vals, n_boot=n_boot, alpha=alpha, seed=seed)
    return {"mean": round(mean, 6), "std": round(std, 6), "n": n,
            "ci_low": ci["ci_low"], "ci_high": ci["ci_high"],
            "n_boot": ci["n_boot"], "seed": ci["seed"]}


# --------------------------------------------------------------------------- #
# McNemar chi2(带连续性校正)+ Breslow-Day(A7, EXGENTIC compare.py 模式)
# --------------------------------------------------------------------------- #

def mcnemar_chi2(b: int, c: int) -> dict[str, Any]:
    """McNemar chi2 版(带 Yates 连续性校正),与 exact_mcnemar 交叉验证。

    b: A 赢 B 输;c: B 赢 A 输。chi2 = (|b-c| - 1)^2 / (b+c),df=1。
    """
    n = b + c
    if n == 0:
        return {"chi2": 0.0, "p": 1.0, "n": 0}
    chi2 = (abs(b - c) - 1.0) ** 2 / n
    try:
        from scipy.stats import chi2 as _chi2
        p = float(_chi2.sf(chi2, 1))
    except ImportError:
        p = None
    return {"chi2": round(chi2, 6), "p": p, "n": n, "note": "Yates continuity correction"}


def breslow_day(tables: Sequence[Sequence[int]], labels: Sequence[str] | None = None) -> dict[str, Any]:
    """Breslow-Day 跨层 OR 异质性检验(EXGENTIC compare.py 模式)。

    tables: k 个 2×2 表,每个 [[a, b], [c, d]]:
        a=两系统都对? 按需定义;通常 a=win, b=loss, c=loss, d=tie。
    返回 MH 合并 OR、BD 统计量、p(chi2, df=k-1)、逐层 OR。
    无 scipy 时 p=None。
    """
    import math

    k = len(tables)
    if k < 2:
        return {"note": "need >= 2 strata", "k": k}
    ors, wts = [], []
    for t in tables:
        a, b, c, d = (int(x) for x in (t[0][0], t[0][1], t[1][0], t[1][1]))
        n = a + b + c + d
        ors.append((a * d / (b * c)) if (b * c) else float("inf"))
        wts.append(n)
    # Mantel-Haenszel 合并 OR(剔除非有限层)
    num = den = 0.0
    for t in tables:
        a, b, c, d = (int(x) for x in (t[0][0], t[0][1], t[1][0], t[1][1]))
        n = a + b + c + d
        if n > 0:
            num += a * d / n
            den += b * c / n
    mh_or = num / den if den else float("inf")

    # BD 统计量:对每层在 OR=mh_or 下求期望 a,算 (a-E)^2/V
    # 方程 (psi-1)a^2 - [psi(n1+m1)+N0]a + psi*n1*m1 = 0, N0 = 第二行和
    bd = 0.0
    details = []
    for i, t in enumerate(tables):
        a, b, c, d = (int(x) for x in (t[0][0], t[0][1], t[1][0], t[1][1]))
        n1 = a + b          # 第一行和
        m1 = a + c          # 第一列和
        n0 = c + d          # 第二行和
        psi = mh_or
        if abs(psi - 1.0) < 1e-12:
            exp_a = n1 * m1 / (n1 + n0)
        else:
            A = psi - 1.0
            B = psi * (n1 + m1) + n0
            disc = B * B - 4 * A * psi * n1 * m1
            exp_a = (B - math.sqrt(max(disc, 0.0))) / (2 * A) if A else n1 * m1 / (n1 + n0)
        exp_a = max(0.0, min(exp_a, n1, m1))  # 期望值必须在可行区间
        # 方差(倒数相加再取倒数)
        v = 0.0
        for term in (exp_a, n1 - exp_a, m1 - exp_a, n0 - m1 + exp_a):
            if term > 0:
                v += 1.0 / term
        var = 1.0 / v if v > 0 else float("inf")
        contrib = ((a - exp_a) ** 2 / var) if var and var != float("inf") else 0.0
        bd += contrib
        details.append({"stratum": labels[i] if labels and i < len(labels) else i,
                        "a": a, "exp_a": round(exp_a, 4), "var": round(var, 4),
                        "or": round(ors[i], 4) if ors[i] != float("inf") else None})
    df = k - 1
    try:
        from scipy.stats import chi2 as _chi2
        p = float(_chi2.sf(bd, df))
    except ImportError:
        p = None
    return {"mh_or": round(mh_or, 4) if mh_or != float("inf") else None,
            "bd_stat": round(bd, 6), "df": df, "p": p,
            "strata": details}


# --------------------------------------------------------------------------- #
# CD 图 / 森林图(G2, matplotlib; 无 matplotlib 时文本回退)
# --------------------------------------------------------------------------- #

def plot_critical_difference(friedman_result: dict, out_path: str = "cd_plot.pdf") -> str:
    """Friedman+Nemenyi 结果的 Critical Difference 图(Demsar 2006)。

    friedman_result: friedman_nemenyi() 的返回值(须含 ranks/cd/significant)。
    matplotlib 不可用时回退为文本 CD 表(返回文本路径说明)。
    返回实际写出文件的路径。
    """
    ranks = friedman_result.get("ranks")
    cd = friedman_result.get("cd")
    if not ranks or cd is None:
        raise ValueError("friedman_result missing ranks/cd (run friedman_nemenyi first)")
    labels = list(ranks.keys())
    vals = [ranks[l] for l in labels]
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        txt = out_path.rsplit(".", 1)[0] + ".txt"
        with open(txt, "w", encoding="utf-8") as f:
            f.write("Critical Difference (text fallback, no matplotlib)\n")
            f.write(f"CD = {cd:.4f}\n")
            for l, v in sorted(zip(labels, vals), key=lambda x: x[1]):
                f.write(f"  {v:.2f}  {l}\n")
        return txt
    # 优先用 scikit-posthocs 官方 CD diagram(>=0.13); 不可用则手绘
    try:
        import pandas as pd
        import scikit_posthocs as sp

        sig_matrix = pd.DataFrame(
            [[1.0 if not fr.get("significant", {}).get(a, {}).get(b) else 0.05
              for b in labels] for a in labels],
            index=labels, columns=labels)
        fig, ax = plt.subplots(figsize=(8, max(2.5, 0.5 * len(labels) + 1)))
        sp.critical_difference_diagram(ranks, sig_matrix, cd=cd, ax=ax,
                                       label_fmt_right="{label} ({rank:.2f})")
        ax.set_title("Critical Difference (Friedman + Nemenyi)", fontsize=11)
        fig.tight_layout()
        fig.savefig(out_path, bbox_inches="tight")
        import matplotlib.pyplot as _plt
        _plt.close(fig)
        return out_path
    except Exception:
        pass  # 手绘回退
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    fig, ax = plt.subplots(figsize=(8, max(2.5, 0.5 * len(labels) + 1)))
    y = 0
    for i in order:
        ax.plot([1, 2], [y, y], "k-", lw=1)
        ax.plot([1], [y], "ko", ms=4)
        ax.plot([2], [y], "ko", ms=4)
        ax.text(0.98, y, f"{vals[i]:.2f} {labels[i]}", ha="right", va="center", fontsize=9)
        y += 1
    ax.plot([1, 1 + cd], [y - 0.5, y - 0.5], "k-", lw=2)
    ax.text(1 + cd / 2, y - 0.5 + 0.15, f"CD = {cd:.3f}", ha="center", fontsize=9)
    ax.set_xlim(0.9, 2.3)
    ax.set_ylim(-0.3, y + 0.3)
    ax.axis("off")
    ax.set_title("Critical Difference (Friedman + Nemenyi)", fontsize=11)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    import matplotlib.pyplot as _plt
    _plt.close(fig)
    return out_path


def plot_forest(estimates: dict[str, dict], out_path: str = "forest.pdf") -> str:
    """森林图: 每系统 point estimate ± CI(AIRS-Bench 多 seed 报告风格)。

    estimates: {label: {"mean": float, "ci_low": float, "ci_high": float, "n": int}}
    无 matplotlib 时文本回退。
    """
    labels = list(estimates.keys())
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        txt = out_path.rsplit(".", 1)[0] + ".txt"
        with open(txt, "w", encoding="utf-8") as f:
            f.write("Forest plot (text fallback, no matplotlib)\n")
            for l in labels:
                e = estimates[l]
                f.write(f"  {e['mean']:.4f} [{e['ci_low']:.4f}, {e['ci_high']:.4f}]  {l}  (n={e.get('n', '?')})\n")
        return txt
    fig, ax = plt.subplots(figsize=(7, max(2.5, 0.5 * len(labels) + 1)))
    ys = list(range(len(labels)))
    means = [estimates[l]["mean"] for l in labels]
    lows = [estimates[l]["ci_low"] for l in labels]
    highs = [estimates[l]["ci_high"] for l in labels]
    ax.errorbar(means, ys, xerr=[[m - lo for m, lo in zip(means, lows)],
                                  [hi - m for m, hi in zip(means, highs)]],
                fmt="o", capsize=4, ms=5)
    ax.set_yticks(ys)
    ax.set_yticklabels(labels)
    ax.axvline(0, color="gray", ls="--", lw=0.8)
    ax.set_xlabel("estimate (95% CI)")
    ax.set_title("Forest plot", fontsize=11)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    import matplotlib.pyplot as _plt
    _plt.close(fig)
    return out_path


# --------------------------------------------------------------------------- #
# 报告助手
# --------------------------------------------------------------------------- #

def stars(p: float) -> str:
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return "n.s."


def win_tie_loss(paired: Iterable[tuple[bool, bool]]) -> dict[str, int]:
    """paired: 每个任务 (A 通过?, B 通过?)。返回 {'win','tie','loss','wins_excl_ties','p','odds'}。

    win = A 对 B 错;loss = B 对 A 错;tie = 其余。win/loss 进 exact McNemar。
    """
    w = t = l = 0
    for a, b2 in paired:
        if a and not b2:
            w += 1
        elif b2 and not a:
            l += 1
        else:
            t += 1
    p, odds = exact_mcnemar(w, l)
    return {"win": w, "loss": l, "tie": t,
            "wins_excl_ties": (w / (w + l)) if (w + l) else float("nan"),
            "p_exact_mcnemar": p, "odds_ratio": odds}
