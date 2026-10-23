"""verify_labels.py — 标签判定器验证门(G006, pilot-derived)。

程序化标签判定器(字符串/数字匹配)在用于校准或准确率结论前,必须验证自身无误判。
脆性匹配器会静默误判语义正确的答案("1789年"vs"1789"、"80元"vs"80"、"不会"vs"否"),
翻转测量结果(本 pilot: 准确率 63.3%→86.7%, ECE 0.363→0.130)。

用法:
  python verify_labels.py <data.jsonl> [--report <out.md>] [--adjudicate]
  数据行需含 predicted_label / gold_answer / outcome(可选, 缺省按 exact 判定)。

行为:
  1. 对比 exact-match 与 tolerant-match 两种判定的 outcome, 输出翻转集;
  2. --adjudicate 时把翻转集写为逐条清单(供人工/LLM 复核), 不自动改数据;
  3. 翻转率 >5% 且未裁决 → exit 2(blocker, 不得进入校准分析);
     翻转率 ≤5% → exit 0; 无翻转 → exit 0。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 语义容错规则(与 collect_pilot_data 一致)
_SUFFIXES = ["年", "元", "米", "小时", "公里", "秒", "约", "的"]
_SYNONYMS = {"不会": "否", "不是": "否", "会": "是", "yes": "是", "no": "否"}


def norm(s: str) -> str:
    s = str(s).strip().lower()
    return re.sub(r"[,，。\s]+", "", s)


def exact_match(a: str, g: str) -> bool:
    return norm(a) == norm(g)


def tolerant_match(a: str, g: str) -> bool:
    a2, g2 = norm(a), norm(g)
    if a2 == g2:
        return True
    for suf in _SUFFIXES:
        a2 = a2.replace(suf, "")
        g2 = g2.replace(suf, "")
    if a2 == g2:
        return True
    if _SYNONYMS.get(a2) == g2:
        return True
    try:
        return abs(float(a2) - float(g2)) < 1e-6
    except ValueError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="标签判定器验证门(G006)")
    ap.add_argument("data", help="JSONL, 每行含 predicted_label/gold_answer[/outcome]")
    ap.add_argument("--report", default="", help="写出验证报告(.md)")
    ap.add_argument("--adjudicate", action="store_true",
                    help="把翻转集写为逐条清单供裁决(不改数据); 未裁决翻转率>5%% 时 exit 2")
    args = ap.parse_args()

    p = Path(args.data)
    if not p.exists():
        print(f"错误: 数据文件不存在 {p}", file=sys.stderr)
        return 1
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    if not rows:
        print("错误: 空数据", file=sys.stderr)
        return 1

    flips = []
    for i, r in enumerate(rows, 1):
        pred = str(r.get("predicted_label", ""))
        gold = str(r.get("gold_answer", ""))
        e = exact_match(pred, gold)
        t = tolerant_match(pred, gold)
        if e != t:
            flips.append({"row": i, "predicted": pred, "gold": gold,
                          "exact": e, "tolerant": t,
                          "trace_id": r.get("trace_id", f"row-{i}")})

    n = len(rows)
    flip_rate = len(flips) / n
    n_exact = sum(1 for r in rows if exact_match(str(r.get("predicted_label", "")), str(r.get("gold_answer", ""))))
    n_tol = sum(1 for r in rows if tolerant_match(str(r.get("predicted_label", "")), str(r.get("gold_answer", ""))))
    lines = [f"# 标签判定器验证报告(G006)", "",
             f"- 数据: {p}  |  行数: {n}",
             f"- exact-match 准确率: {n_exact}/{n}",
             f"- tolerant-match 准确率: {n_tol}/{n}",
             f"- 翻转集大小: {len(flips)}  ({flip_rate:.1%})", ""]
    if flips:
        lines.append("## 翻转集(逐条待裁决)")
        lines.append("")
        lines.append("| row | trace_id | predicted | gold | exact | tolerant |")
        lines.append("|---|---|---|---|---|---|")
        for f in flips:
            lines.append(f"| {f['row']} | {f['trace_id']} | {f['predicted']!r} | {f['gold']!r} | {f['exact']} | {f['tolerant']} |")
        lines.append("")
        lines.append("> 每条翻转必须裁决: 语义等价(判对, 修 matcher/标签)或语义不等(判错, 保留 exact)。")
        lines.append("> 裁决记录应入证据(outcome_source 标注), 并加 CLAIM_LEDGER 条目使前后数字可追溯。")
    report = "\n".join(lines) + "\n"

    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"report -> {out}")

    blocked = flip_rate > 0.05 and not args.adjudicate
    if blocked:
        print(f"BLOCKED: 翻转率 {flip_rate:.1%} > 5% 且未裁决(--adjudicate 输出清单后逐条裁决, 修复 matcher 或修正标签再继续)")
        print(report)
        return 2
    print(report)
    if flips and args.adjudicate:
        print(f"翻转集已输出({len(flips)} 条), 请逐条裁决后再继续校准分析")
    print(f"verdict: {'PASS (翻转率≤5% 或已裁决)' if not blocked else 'BLOCKED'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
