# --- acceptance_backfill (EVAL_ACCEPTANCE_STANDARD.md P4) ---
# 证据来源: scripts/check_h4_claims.py
# 修正 2026-11-13（A 类）：原命令缺位置参数 paper_dir，argparse 直接 exit 2。
# 该脚本的 RESULT_NAME="results/..." 与 TEX_GLOBS="paper/main.tex" 都相对 paper_dir，
# 所以 paper_dir 就是仓库根 "."。
.PHONY: eval

eval:
	python3 scripts/check_h4_claims.py . --selftest
