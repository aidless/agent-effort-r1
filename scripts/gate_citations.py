#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gate_citations.py — Phase 5 引用验证门禁 (L2-2)
================================================

把 research-kit 的独立引用验证工具 verify_citations.py 接入论文 agent 的
Phase 5 门禁: 输入 <paper_dir>,自动查找 main.bib / references.bib(也可
--bib 显式指定),调用 verify_citations.py 做 4 层验证(纯标准库,外部工具),
收集其输出并输出门禁报告,按 --fail-on-suspicious 控制退出码。

本脚本只调用 verify_citations.py,不修改它;只新增报告/临时文件,不改动
论文既有文件(verify_citations 会按其自身约定在 bib 同目录维护 90 天缓存
.verify_cache.json,这是该工具文档化的行为)。

用法:
  python gate_citations.py <paper_dir>                                     # 自动找 main.bib / references.bib
  python gate_citations.py <paper_dir> --bib refs.bib                      # 显式指定 bib
  python gate_citations.py <paper_dir> --fail-on-suspicious --out reports/citations_gate.md
  python gate_citations.py <paper_dir> --allow-missing-bib                 # 无 bib 也放行

退出码:
  0 = 门禁通过;或文档化降级(网络不可达/verifier 超时 -> Skipped_network=1);
      或无 bib 且 --allow-missing-bib;或报告模式(未给 --fail-on-suspicious)
  1 = 门禁失败: --fail-on-suspicious 且 Not_found+Mismatch > 0;
      或 --fail-on-suspicious 且无 bib(且未 --allow-missing-bib)
  2 = 基础设施错误: paper_dir 不存在 / --bib 指向的文件不存在 / verifier
      缺失 / verifier 崩溃或输出无法解析

报告段落(固定六段,恒输出,缺省计 0;格式沿用族内约定:
固定 'paper' 目标标签 + 相对路径 + "## <段落>: <计数>" 行):
  Verified / Not_found / Mismatch / Manual_needed / Skipped_network / No_bib_found
  - Manual_needed 段落 = verify_citations 的 manual_needed + suspicious 两种状态:
    两者都需人工核对,且都不属于 verify_citations 的拦截类(mismatch/not_found)。
  - Not_found/Mismatch 计数直接来自 verify_citations 的 --json 结构化输出。

网络判定: verify_citations 不显式报告网络错误(断网时静默降级为
not_found/manual_needed),因此本门禁自带连通性探测(默认探测 Crossref /
Semantic Scholar / OpenAlex / arXiv 四个 API 端点)。探测失败、verifier
stderr 含网络错误/超时特征、或 verifier 子进程超时 => Skipped_network=1,
门禁"文档化降级"为 exit 0(引用未在当前会话重新验证,结果可能来自 90 天缓存)。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_VERIFIER = Path(r"F:\deepseek\research-kit\citation-verifier\verify_citations.py")
PROBE_HOSTS = [
    "https://api.crossref.org",
    "https://api.semanticscholar.org",
    "https://api.openalex.org",
    "http://export.arxiv.org",
]
BIB_CANDIDATES = ["main.bib", "references.bib"]
SUBDIRS = ["", "paper"]  # 同时兼容 bootstrap 布局 <dir>/paper/main.bib
NETWORK_ERROR_RE = re.compile(
    r"timed\s*out|timeout|connection\s+(refused|reset)|unreachable|URLError|"
    r"网络(连接|错误|不可达)|连接失败|超时",
    re.IGNORECASE,
)
PARAGRAPHS = ["Verified", "Not_found", "Mismatch", "Manual_needed", "Skipped_network", "No_bib_found"]
STATUS_TO_PARAGRAPH = {
    "verified": "Verified",
    "not_found": "Not_found",
    "mismatch": "Mismatch",
    "manual_needed": "Manual_needed",
    "suspicious": "Manual_needed",  # 标题命中但元数据冲突,同样需人工核对
}


def rel_display(path: Path, root: Path) -> str:
    """相对 root 渲染路径(族内 byte-reproducible 约定);无法相对时用绝对路径。"""
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def find_bib(paper_dir: Path) -> Path | None:
    for sub in SUBDIRS:
        for name in BIB_CANDIDATES:
            p = paper_dir / sub / name
            if p.is_file():
                return p
    return None


def probe_network(hosts: list[str], timeout: float) -> bool:
    """任一 API 端点返回 HTTP 响应即视为网络可达。"""
    for host in hosts:
        try:
            req = urllib.request.Request(host, headers={"User-Agent": "citation-gate/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp.read(1024)
            return True
        except urllib.error.HTTPError:
            return True  # 收到 HTTP 响应(含 4xx/5xx)即网络可达
        except Exception:
            continue
    return False


def run_verifier(verifier: Path, bib: Path, timeout: float) -> dict:
    """调用 verify_citations.py 并收集 stdout/stderr/退出码/结构化 JSON。"""
    fd, json_path = tempfile.mkstemp(prefix="gate_citations_", suffix=".json")
    os.close(fd)
    cmd = [sys.executable, str(verifier), str(bib), "--json", json_path]
    try:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            return {
                "timeout": True,
                "rc": -1,
                "stdout": (e.stdout or "") if isinstance(e.stdout, str) else "",
                "stderr": (e.stderr or "") if isinstance(e.stderr, str) else "",
                "results": None,
                "json_path": json_path,
            }
        results = None
        if os.path.exists(json_path):
            try:
                with open(json_path, encoding="utf-8") as f:
                    results = json.load(f)
            except Exception:
                results = None
        return {
            "timeout": False,
            "rc": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "results": results,
            "json_path": json_path,
        }
    finally:
        if os.path.exists(json_path):
            try:
                os.remove(json_path)
            except OSError:
                pass


def count_statuses(results: list) -> dict:
    counts = {p: 0 for p in PARAGRAPHS}
    per_entry: list[dict] = []
    for r in results:
        status = str(r.get("status", ""))
        para = STATUS_TO_PARAGRAPH.get(status, "Manual_needed")
        counts[para] += 1
        per_entry.append({
            "key": r.get("key", "?"),
            "status": status,
            "detail": str(r.get("detail", ""))[:100],
        })
    return counts, per_entry


def build_report(
    paper_dir: Path,
    bib: Path | None,
    counts: dict,
    verdict: str,
    note: str = "",
    per_entry: list | None = None,
    verifier_name: str = "",
    rc: int = 0,
    total: int = 0,
) -> str:
    lines = ["# 引用验证门禁报告 (L2-2)", ""]
    bib_disp = rel_display(bib, paper_dir) if bib else "-"
    lines.append(
        f"Target: `paper`  |  bib: {bib_disp}  |  条目: {total}  |  "
        f"verifier: {verifier_name} (exit {rc})  |  门禁结论: {verdict}  |  "
        f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    lines.append("")
    for p in PARAGRAPHS:
        lines.append(f"## {p}: {counts[p]}")
    if note:
        lines += ["", note]
    if per_entry:
        lines += ["", "条目明细(key [verify_citations 状态] 详情):"]
        for e in per_entry:
            lines.append(f"- {e['key']} [{e['status']}] {e['detail']}")
    lines.append("")
    lines.append("> Manual_needed 段落含 verify_citations 的 manual_needed 与 suspicious 两种状态"
                 "(均需人工核对,均非拦截类)。")
    lines.append("> 计数来自 verify_citations --json 结构化输出;网络不可达时计数不可靠,"
                 "以 Skipped_network 降级为准。")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Phase 5 引用验证门禁 (L2-2): 调用 research-kit verify_citations.py 并输出门禁报告"
    )
    ap.add_argument("paper_dir", help="论文目录")
    ap.add_argument("--bib", help="显式指定 .bib 文件(默认自动查找 main.bib / references.bib)")
    ap.add_argument("--out", help="门禁报告输出路径(同时打印到 stdout)")
    ap.add_argument("--fail-on-suspicious", action="store_true",
                    help="Not_found + Mismatch > 0 时 exit 1")
    ap.add_argument("--allow-missing-bib", action="store_true",
                    help="无 bib 文件时 exit 0(默认: 无 bib 且 --fail-on-suspicious 时 exit 1)")
    ap.add_argument("--verifier", default=str(DEFAULT_VERIFIER),
                    help=f"verify_citations.py 路径(默认 {DEFAULT_VERIFIER})")
    ap.add_argument("--probe-host", action="append", default=None,
                    help="覆盖连通性探测主机(可多次;测试/离线环境用)")
    ap.add_argument("--probe-timeout", type=float, default=5.0,
                    help="连通性探测每端点超时秒数(默认 5)")
    ap.add_argument("--timeout", type=float, default=900.0,
                    help="verify_citations 子进程总超时秒数(默认 900)")
    args = ap.parse_args()

    paper_dir = Path(args.paper_dir).resolve()
    if not paper_dir.is_dir():
        print(f"错误: paper_dir 不存在: {paper_dir}", file=sys.stderr)
        return 2

    # ---- 定位 bib ----
    if args.bib:
        cand = Path(args.bib)
        if not cand.is_absolute():
            # 相对路径优先相对 paper_dir 解析(族内约定),其次相对 cwd
            in_paper = paper_dir / cand
            bib = in_paper if in_paper.is_file() else Path.cwd() / cand
        else:
            bib = cand
        bib = bib.resolve()
        if not bib.is_file():
            print(f"错误: --bib 指向的文件不存在: {bib}", file=sys.stderr)
            return 2
    else:
        bib = find_bib(paper_dir)

    if bib is None:
        counts = {p: 0 for p in PARAGRAPHS}
        counts["No_bib_found"] = 1
        verdict = "MISSING_BIB"
        note = ("未找到 main.bib / references.bib(含 <dir>/paper/ 子目录布局)。"
                "引用未经验证,不构成通过结论。")
        if args.allow_missing_bib:
            rc = 0
            note += " --allow-missing-bib: 门禁放行(文档化例外)。"
        elif args.fail_on_suspicious:
            rc = 1
            note += " --fail-on-suspicious: 无可验证内容,门禁失败。"
        else:
            rc = 0
            note += " 报告模式(未给 --fail-on-suspicious): 不拦截。"
        report = build_report(paper_dir, None, counts, verdict, note=note)
        print(report)
        if args.out:
            _write_out(args.out, report)
        return rc

    verifier = Path(args.verifier).resolve()
    if not verifier.is_file():
        print(f"错误: verifier 不存在: {verifier}", file=sys.stderr)
        return 2

    # ---- 网络判定 + 调用 verifier ----
    hosts = args.probe_host or PROBE_HOSTS
    network_up = probe_network(hosts, args.probe_timeout)

    v = run_verifier(verifier, bib, args.timeout)

    degraded = False
    degrade_reason = ""
    if v["timeout"]:
        degraded = True
        degrade_reason = f"verify_citations 子进程超时(>{args.timeout:.0f}s)"
    elif not network_up:
        degraded = True
        degrade_reason = "连通性探测失败(Crossref/S2/OpenAlex/arXiv 均不可达)"
    elif re.search(NETWORK_ERROR_RE, v["stderr"]):
        degraded = True
        degrade_reason = f"verify_citations 报网络错误/超时: {v['stderr'].strip()[:120]}"

    if v["results"] is None and not degraded:
        # 仅当 verifier 实际运行却未产出结构化结果时视为基础设施错误;
        # 超时/断网降级路径下无结果是预期的,直接走 Skipped_network。
        print("错误: verify_citations 未能产出结构化结果(崩溃或输出无法解析);"
              f"退出码 {v['rc']}", file=sys.stderr)
        if v["stderr"]:
            print(v["stderr"][-2000:], file=sys.stderr)
        return 2

    counts, per_entry = count_statuses(v["results"] or [])
    total = len(v["results"] or [])

    if degraded:
        counts["Skipped_network"] = 1
        verdict = "DEGRADED(文档化降级)"
        note = (f"文档化降级: {degrade_reason}。引用未在当前会话重新验证"
                "(计数可能来自 90 天缓存或不可靠),门禁降级为不拦截(exit 0)。"
                "网络恢复后请重跑本门禁以真正通过。")
        rc = 0
    else:
        suspicious = counts["Not_found"] + counts["Mismatch"]
        if args.fail_on_suspicious and suspicious > 0:
            verdict = "FAIL"
            rc = 1
            note = (f"--fail-on-suspicious: Not_found + Mismatch = {suspicious} > 0。"
                    "以下条目必须修正或删除后重跑: " +
                    ", ".join(e["key"] for e in per_entry
                              if e["status"] in ("not_found", "mismatch")))
        elif suspicious > 0:
            # 报告模式(未给 --fail-on-suspicious): 有可疑项但不拦截
            verdict = "REPORT(有可疑项,未拦截)"
            rc = 0
            note = (f"报告模式(未给 --fail-on-suspicious): Not_found + Mismatch = {suspicious} > 0,"
                    "门禁不拦截,但以下条目建议修正或删除: " +
                    ", ".join(e["key"] for e in per_entry
                              if e["status"] in ("not_found", "mismatch")))
        else:
            verdict = "PASS"
            rc = 0
            note = "未发现拦截类引用(mismatch/not_found)。"

    verifier_name = verifier.name
    report = build_report(paper_dir, bib, counts, verdict, note=note,
                          per_entry=per_entry, verifier_name=verifier_name,
                          rc=v["rc"], total=total)
    print(report)
    if args.out:
        _write_out(args.out, report)
    return rc


def _write_out(out: str, report: str) -> None:
    p = Path(out)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(report + "\n")


if __name__ == "__main__":
    sys.exit(main())
