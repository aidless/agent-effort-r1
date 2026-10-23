#!/usr/bin/env python3
"""薄壳：claim-ledger 闸的实现只有仓根 `scripts/verify_claim_ledger.py` 一份。

为什么留一份而不是十份：同一判据有多份可写副本会各自放宽，是会周期性红回来的缺陷
（本仓实证：source/ 与 scripts/ 两份 check_numbers.py，承重那份一直是坏的）。

本壳只做三件事：
  1. 向上找到仓根的正本实现（跳过自己，否则会递归执行壳）；
  2. 把 `.` 这类相对 target 钉到本壳所在论文根，从仓根或从论文目录调用都成立；
  3. 子进程的 stdout/stderr 与退出码原样交回 —— 不吞输出，不伪造绿。
找不到正本 ⇒ 退出 3 并点名缺什么，绝不退 0。
"""
import sys, subprocess
from pathlib import Path

here = Path(__file__).resolve().parent.parent


def find_canonical(start: Path):
    me = Path(__file__).resolve()
    for d in (start, *start.parents):
        cand = d / "scripts" / "verify_claim_ledger.py"
        if cand.is_file() and cand.resolve() != me:
            return cand.resolve()
    return None


canon = find_canonical(Path(__file__).resolve().parent)
if canon is None:
    sys.stderr.write("CANONICAL_NOT_FOUND: 向上没找到仓根 scripts/verify_claim_ledger.py；"
                     "本闸无法执行（这不是通过）\n")
    raise SystemExit(3)

args = sys.argv[1:]
if args and args[0] in (".", ""):
    args[0] = str(here)
proc = subprocess.run([sys.executable, str(canon), *args])
raise SystemExit(proc.returncode)
