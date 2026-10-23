"""check_literature_freshness.py — 相关文献增量门（审计项 L2-3）。

立项→投稿之间 arXiv 会持续出现新工作, LITERATURE_REVIEW.md 里的
novelty 定位可能过时。本脚本检查 <paper_dir>/LITERATURE_REVIEW.md 的
真实 mtime 距今天数, 输出机器可读报告, 并可充当投稿前门禁
（--fail-on-stale: Stale=1 或 Missing=1 时 exit 1）。

族内约定（与五个扫描器一致, 供 scanner_regression 式断言）:
  - 报告含机器可读 "## <小节>: <计数>" 行; 本检查的深度信号行是
    "## 段落: <计数>"（LITERATURE_REVIEW.md 的非空段落数）;
  - 固定目标标签 "paper", 报告内不出现绝对路径/调用目录名
    （字节可复现, FM-24; 内容与调用 cwd 无关）;
  - exit 0 = 仅报告（或 --fail-on-stale 下通过）; exit 1 = 门禁失败。

报告字段:
  Missing      文件缺失? 1/0
  Age_days     真实 mtime 距今天数（向下取整, 未来时间钳为 0）;
               缺失时为 -1 哨兵
  Stale        Age_days >= Max_age_days? 1/0; 缺失时为 0
               （缺失的失败语义由 Missing 字段承担）
  Claims_count --claims-file 中非空、非 '#' 注释行数（novelty 声称覆盖数）
  Max_age_days 配置的阈值（默认 30）

--fail-on-stale 退出规则:
  (Stale == 1) OR (Missing == 1 AND 未给 --allow-missing) -> exit 1
  否则 exit 0。--allow-missing 只豁免"缺失"这一条件, 不豁免真过期。

用法:
  python check_literature_freshness.py <paper_dir> [--max-age-days 30]
       [--claims-file claims.txt] [--allow-missing]
       [--out report.md] [--fail-on-stale]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path

REVIEW_NAME = "LITERATURE_REVIEW.md"
TARGET_LABEL = "paper"
MISSING_AGE = -1


def _force_utf8_stdio() -> None:
    """管道/重定向时 stdout 一律 UTF-8, 与落盘报告字节一致（FM-24）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _paragraph_count(text: str) -> int:
    """非空段落数: 由连续非空行组成的一个块计为一段。"""
    count = 0
    in_block = False
    for line in text.splitlines():
        if line.strip():
            if not in_block:
                count += 1
                in_block = True
        else:
            in_block = False
    return count


def _count_claims(path: Path) -> int:
    """每行一条 novelty 声称; 跳过空行与 '#' 注释行（容忍 UTF-8 BOM）。"""
    try:
        raw = path.read_bytes()
    except OSError:
        return -1
    text = raw.decode("utf-8", errors="ignore")
    if text.startswith("\ufeff"):
        text = text[1:]
    n = 0
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(
        description="LITERATURE_REVIEW.md 新鲜度门禁检查（L2-3）")
    ap.add_argument("paper_dir", help="论文项目根目录（应含 LITERATURE_REVIEW.md）")
    ap.add_argument("--max-age-days", type=int, default=30,
                    help="允许的最大陈旧天数（默认 30）; Age_days >= 该值视为 Stale")
    ap.add_argument("--claims-file", default=None,
                    help="novelty 声称文件（每行一条; 空行/'#' 注释跳过）, "
                         "仅用于报告 Claims_count 覆盖数")
    ap.add_argument("--allow-missing", action="store_true",
                    help="LITERATURE_REVIEW.md 缺失时不计入门禁失败"
                         "（报告仍标 Missing=1）")
    ap.add_argument("--check-drift", action="store_true",
                    help="G3: 检测 novelty 漂移——声称引用的工作是否比 review 的最新"
                         "引用陈旧(声称未随 review 更新); 网络级抢发检测留给 D0 重扫")
    ap.add_argument("--out", default=None,
                    help="报告输出路径（默认仅打印到 stdout）")
    ap.add_argument("--fail-on-stale", action="store_true",
                    help="Stale=1 或 Missing=1（未 --allow-missing）时 exit 1")
    args = ap.parse_args()

    _force_utf8_stdio()

    root = Path(args.paper_dir)
    if not root.is_dir():
        print(f"error: paper_dir is not a directory: {root}", file=sys.stderr)
        return 2

    review = root / REVIEW_NAME
    if review.is_file():
        mtime = review.stat().st_mtime  # 真实 mtime, 与调用 cwd 无关
        delta = _dt.datetime.now() - _dt.datetime.fromtimestamp(mtime)
        age_days = max(0, delta.days)
        missing = 0
        review_text = review.read_text(encoding="utf-8", errors="ignore")
        paragraphs = _paragraph_count(review_text)
    else:
        age_days = MISSING_AGE
        missing = 1
        paragraphs = 0
        review_text = ""

    stale = 1 if (missing == 0 and age_days >= args.max_age_days) else 0

    if args.claims_file is not None:
        claims_count = _count_claims(Path(args.claims_file))
        if claims_count < 0:
            print(f"warning: cannot read claims file: {args.claims_file}",
                  file=sys.stderr)
            claims_count = 0
    else:
        claims_count = 0

    # G3: novelty-drift check (local, deterministic)
    drift = 0
    drift_notes: list[str] = []
    if args.check_drift and not missing and args.claims_file is not None:
        # 1) 收集 review 中最新的引用年份 (arXiv:YYMM.xxxxx / (YYYY) / 20XX)
        years = [int(m) for m in re.findall(r"20\d\d", review_text)]
        review_latest = max(years) if years else None
        # 2) 收集每条声称引用的年份
        claim_path = Path(args.claims_file)
        for line in claim_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            claim_years = [int(m) for m in re.findall(r"20\d\d", s)]
            if claim_years and review_latest is not None:
                oldest = min(claim_years)
                if oldest < review_latest - 1:  # 声称停在 review 最新引用 2 年前
                    drift += 1
                    drift_notes.append(
                        f"{s[:80]} (claims from {oldest}, review covers {review_latest})")
            elif claim_years and review_latest is None:
                drift_notes.append(f"{s[:80]} (no recent years in review to compare)")
        if review_latest is not None and age_days >= args.max_age_days:
            drift_notes.append(
                f"review is {age_days} days old; even if claims look fresh, "
                "re-run D0 incremental scan for arXiv preemptions")

    lines = ["# Literature freshness check report", ""]
    lines.append(f"Target: `{TARGET_LABEL}`")
    lines.append(f"LITERATURE_REVIEW.md: {'missing' if missing else 'present'}")
    lines.append(f"## 段落: {paragraphs}")
    lines.append(f"## Missing: {missing}")
    lines.append(f"## Age_days: {age_days}")
    lines.append(f"## Stale: {stale}")
    lines.append(f"## Claims_count: {claims_count}")
    lines.append(f"## Max_age_days: {args.max_age_days}")
    lines.append(f"## Novelty_drift: {drift}")
    if args.check_drift and drift_notes:
        lines.append("")
        lines.append("Novelty-drift notes (G3):")
        lines += [f"- {n}" for n in drift_notes[:20]]
    if missing and not args.allow_missing:
        lines.append("")
        lines.append("- gate: LITERATURE_REVIEW.md is missing; "
                     "--allow-missing exempts the exit code only (Missing stays 1)")
    elif missing:
        lines.append("")
        lines.append("- gate: LITERATURE_REVIEW.md is missing but "
                     "--allow-missing exempts the failure")
    if stale:
        lines.append("")
        lines.append(f"- gate: review is stale (age {age_days} days >= max "
                     f"{args.max_age_days}); re-run the D0 incremental scan "
                     "and re-check novelty claims before submission")
    report = "\n".join(lines) + "\n"

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
    print(report, end="")

    if args.fail_on_stale and (stale == 1 or (missing == 1 and not args.allow_missing) or drift > 0):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
