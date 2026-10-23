"""check_submit_ready.py - 投稿阻断门（评估要求：发布阻断而非页眉）。

在状态不是 `paper_claims_enabled` 时，任何导出/投稿包脚本必须直接失败。
本脚本是发布管线的强制门：exit 0 = 可投稿；exit 非 0 = 阻断并说明原因。

状态来源：results/runs/<active-run-id>/STATUS.json（由验证器生成，非人工编辑）。
证据状态机：planned -> running -> candidate -> independently_recomputed
  -> sealed -> verified_real_evidence -> paper_claims_enabled

用法:
  python check_submit_ready.py <paper_dir> --active-run <run_id>
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

REQUIRED_STATE = "paper_claims_enabled"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="paper dir")
    ap.add_argument("--active-run", default="", help="active run id (sealed run)")
    ap.add_argument("--stub", action="store_true", help="treat no-status as blocked (default)")
    args = ap.parse_args()

    root = Path(args.target)

    # 1. DRAFT marker must be present unless paper_claims_enabled (defense in depth)
    tex = root / "paper" / "main.tex"
    draft_marked = False
    if tex.exists():
        src = tex.read_text(encoding="utf-8")
        # marker is "in effect" if the header still uses it (not just defined)
        draft_marked = r"\fancyhead[L]{\draftmark}" in src
        if not draft_marked:
            draft_marked = "DRAFT -- EVIDENCE UNDER RE-EXECUTION" in src and "fancyhead" in src

    # 2. Sealed run status must be paper_claims_enabled
    state = None
    status_path = None
    if args.active_run:
        status_path = root / "results" / "runs" / args.active_run / "STATUS.json"
        if status_path.exists():
            raw = status_path.read_text(encoding="utf-8-sig")
            st = json.loads(raw)
            state = st.get("state") or st.get("status") or "unknown"

    # Decision
    blocked = False
    reasons = []
    if state != REQUIRED_STATE:
        blocked = True
        reasons.append(f"run state is '{state}' (need '{REQUIRED_STATE}')")
        if not draft_marked:
            blocked = True
            reasons.append("DRAFT marker missing from main.tex while evidence is not ready "
                           "(submission would bypass the re-execution warning)")
    elif not draft_marked:
        # paper_claims_enabled AND DRAFT removed -> submittable
        pass
    else:
        # state is ready but DRAFT still present -> not yet submittable
        blocked = True
        reasons.append("run state is paper_claims_enabled but DRAFT marker still present "
                       "(remove DRAFT marker only after verified bundle is published)")
    if state is None and not args.active_run:
        blocked = True
        reasons.append("no active run specified")

    if blocked:
        print("BLOCKED: manuscript is not submittable")
        for r in reasons:
            print(f"  - {r}")
        print("Evidence state must reach paper_claims_enabled via the sealed-run",
              "state machine; DRAFT marker must be present as defense-in-depth.")
        return 1

    print("SUBMITTABLE: evidence state paper_claims_enabled + DRAFT marker removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
