# 新颖性漂移扫描（freshness_drift）

claims: `novelty_claims.txt`  |  立项日 cutoff: **2026-08-01**  |  扫描日: 2026-10-09  |  判定: **CLEAN**

- drift（已被接收/发表的先行工作，重叠 claim）: **0**
- preprint（预印本重叠，需人工裁决是否抢发）: 0
- 未检索到（阶梯全 0，无判据）: 0
- 检索失败: 0

## 逐条判据留痕

| claim | 检索式 | 扫描日 | 重叠命中/库内命中 | 最强命中 | 备注 |
|---|---|---|---|---|---|
| First work (within our retrieval scope) to place reasoning | `(all:allocation AND all:frontier AND all:network) AND submittedDate:[20260801000` | 2026-10-09 | 0 / 库内 5 | 无重叠 | 按保守判据未发现重叠 |
| First work to report that the optimal effort composition r | `(all:composition AND all:magnitude AND all:measured AND all:optimal) AND submitt` | 2026-10-09 | 0 / 库内 2 | 无重叠 | 按保守判据未发现重叠 |
| First work to give the cost-side boundary of the source re | `(all:agentic AND all:boundary AND all:control AND all:faithfully) AND submittedD` | 2026-10-09 | 0 / 库内 1 | 无重叠 | 按保守判据未发现重叠 |

> 「无重叠」不构成新颖性证明：只说明在 cutoff 之后、以本检索式未抓到先行工作。检索式换了、截止日推后、arXiv 新增，都可能改变结论。
>
> 「库内命中」是检索式在 arXiv 命中的**总条数**。它上万说明检索式退化成全库扫描，返回的候选是近随机样本 —— 这种情况下「未发现重叠」不是干净的结果，必须改检索式后重跑。

## 判读

未发现重叠。这**不是**新颖性证明，只代表本次检索式的结果。
