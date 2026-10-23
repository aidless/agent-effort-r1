# Novelty prescan — novelty claim 联网预检索

- claims_file: `novelty_claims.txt`
- n_claims: 3
- arxiv_since: 2026-08-01（增量扫描下界 = 立项日期）
- scan_date: 2026-10-09
- per_claim_top: 3
- min_relevance: 0.55（候选池 IDF 加权 · ≥2 个有区分度的词命中；分数>1 属正常：标题命中加权 2x）

## 逐条检索留痕

| # | claim | 检索式 | 检索日期 | 命中/库内命中 | 最相关条目 |
|---|---|---|---|---|---|
| C1 | First work (within our retrieval scope) to place reasoning tokens, tra | `(all:allocation AND all:frontier AND all:network) AND submittedDate:[202608010000 TO 999912312359]` | 2026-10-09 | 0 / 库内 5 | — |
| C2 | First work to report that the optimal effort composition rotates acros | `(all:composition AND all:magnitude AND all:measured AND all:optimal) AND submittedDate:[202608010000 TO 999912` | 2026-10-09 | 0 / 库内 2 | — |
| C3 | First work to give the cost-side boundary of the source report's claim | `(all:agentic AND all:boundary AND all:control AND all:faithfully) AND submittedDate:[202608010000 TO 999912312` | 2026-10-09 | 0 / 库内 1 | — |

## 汇总

- 检索日期: 2026-10-09
- 声称条数: 3
- 成功检索: 3
- 检索失败: 0
- 命中重叠条目总数: 0
- 检索式有效性: 见上表「命中/库内命中」——库内命中过大（万级）说明检索式退化成全库扫描，**这不是干净的检索**，需改检索式

## 命中详情

### C1 — First work (within our retrieval scope) to place reasoning tokens, trajectory steps, local tool calls, network search calls and visual probes under a single effort budget and solve the joint allocation frontier.

- 检索式: `(all:allocation AND all:frontier AND all:network) AND submittedDate:[202608010000 TO 999912312359]`
- 检索日期: 2026-10-09　检索式总命中: 5　取回候选: 5　判为重叠: 0　**已放宽 2 级**（前 2 级库内命中为 0）

- 阶梯留痕（越宽越容易捞到无关条目，精度下降）:
  1. totalResults=0 （库内 0，放宽） `(all:allocation AND all:frontier AND all:network AND all:reasoning AND all:retrieval AND a`
  2. totalResults=0 （库内 0，放宽） `(all:allocation AND all:frontier AND all:network AND all:reasoning) AND submittedDate:[202`
  3. totalResults=5 ← 采用 `(all:allocation AND all:frontier AND all:network) AND submittedDate:[202608010000 TO 99991`

- 命中 0：按保守判据未发现明显重叠。**注意这不是证明新颖** —— 只说明这次检索式没抓到，换检索式可能命中。

### C2 — First work to report that the optimal effort composition rotates across the budget rather than scaling uniformly, with a measured cost model spanning five orders of magnitude.

- 检索式: `(all:composition AND all:magnitude AND all:measured AND all:optimal) AND submittedDate:[202608010000 TO 999912312359]`
- 检索日期: 2026-10-09　检索式总命中: 2　取回候选: 2　判为重叠: 0　**已放宽 1 级**（前 1 级库内命中为 0）

- 阶梯留痕（越宽越容易捞到无关条目，精度下降）:
  1. totalResults=0 （库内 0，放宽） `(all:composition AND all:magnitude AND all:measured AND all:optimal AND all:rotates AND al`
  2. totalResults=2 ← 采用 `(all:composition AND all:magnitude AND all:measured AND all:optimal) AND submittedDate:[20`

- 命中 0：按保守判据未发现明显重叠。**注意这不是证明新颖** —— 只说明这次检索式没抓到，换检索式可能命中。

### C3 — First work to give the cost-side boundary of the source report's claim that reasoning-effort control transfers faithfully to long-horizon agentic trajectories.

- 检索式: `(all:agentic AND all:boundary AND all:control AND all:faithfully) AND submittedDate:[202608010000 TO 999912312359]`
- 检索日期: 2026-10-09　检索式总命中: 1　取回候选: 1　判为重叠: 0　**已放宽 1 级**（前 1 级库内命中为 0）

- 阶梯留痕（越宽越容易捞到无关条目，精度下降）:
  1. totalResults=0 （库内 0，放宽） `(all:agentic AND all:boundary AND all:control AND all:faithfully AND all:horizon AND all:r`
  2. totalResults=1 ← 采用 `(all:agentic AND all:boundary AND all:control AND all:faithfully) AND submittedDate:[20260`

- 命中 0：按保守判据未发现明显重叠。**注意这不是证明新颖** —— 只说明这次检索式没抓到，换检索式可能命中。

