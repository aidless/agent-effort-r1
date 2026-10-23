# Revision Round R0 报告 — 立项收据（回填）

日期：2026-09-11 ｜ 论文：From Controllable Reasoning Effort to Controllable Agent Effort
状态：已完成（历史收据，R1 起实质工作）｜本轮成本：0（无 GPU、无 API）

> 本文件原为空白模板，R1 期间回填为**历史收据**，以保留线索链。实质变更见 `ROUND_R1.md`。

## 1. 本轮范围

- 目标：P2 立项——确定方向前提、方法表、假设与证据入口。
- 产出：`papers/agent_effort/` 骨架 + 三篇 arXiv 相关工作摘要 JSON +
  `CLAIM_LEDGER.md` 雏形 + `HYPOTHESES.md`（H1/H2/H3）+ `LITERATURE_REVIEW.md` 种子。
- **阻塞项（当时未识别）**：`paper/main.tex` 仍是 TMLR 官方模板原文，论文无实质内容；
  且方向前提（可控推理努力）**未挂到唯一权威来源**，证据入口是 arXiv 相关工作而非源报告。

## 2. 变更日志

| 变更 ID | 文件 | 改了什么 | 为什么改 | 证据影响 | 状态 |
|---|---|---|---|---|---|
| CHG00 | 全部 | 立项骨架 | 建项 | 无证据 | done |

## 3. 遗留问题（转 R1）

| ID | 事项 | 类型 | R1 处理 |
|---|---|---|---|
| O00-1 | 方向前提未挂真来源（V4.1-Flash 技术报告） | 阻塞（来源身份） | R1 重建 `evidence/v41flash_effort_control.json`，40 条逐字引文 |
| O00-2 | 正文为空模板，无 GAP / 无假设 / 无实验 | 阻塞（交付） | R1 重写全文并跑 E1/E1b/E2/E3 |
| O00-3 | 三篇 arXiv JSON 被当作“证据”而非相关工作 | 口径错误 | R1 移入 `evidence/related_work/` 并在 HYPOTHESES 注明退场 |
| O00-4 | H1/H2/H3 无实验，全部 `inconclusive` | 阻塞（证据） | R1 全部跑出结果并按证伪条件判定 |
