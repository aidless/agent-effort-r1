# LITERATURE_REVIEW.md — P2（R1 重建：重挂真来源 + 可核验基线池）

检索日期：2026-09-11（可复算：下方每条带 URL/arXiv 编号，投前需重跑新鲜度门）
口径：**唯一权威来源**是源报告（`evidence/V41FLASH_TechReport.txt`（与 `papers/_shared/evidence/` 下原件同 SHA-256））。
三篇 arXiv 工作只作**相关工作/基线**，不作前提来源。

## 1. 检索日志

| 路径 | 命中 | 处置 |
|---|---|---|
| 源报告逐字检索（`grep -n`，LF 行号） | `Controllable Reasoning Effort` ×2（2039, 3486）、`effort level` ×17、`reasoning effort` ×8、`scalar effort` ×4，其余见 `evidence/v41flash_effort_control.json → term_counts` | 直接采用为唯一前提来源 |
| arXiv 语义检索：budget-aware agent / test-time compute allocation | 6 篇 | 见 §2 方法家族表 |
| 交叉核对：标题 + 作者 + 摘要三要素逐条人工确认（避免幻觉引用） | 8 条全部含 URL | 见 `paper/main.bib` |

## 2. 方法家族表

| 家族 | 代表工作 | 决策变量 | 货币 | 与 P2 的边界 |
|---|---|---|---|---|
| 单 episode 内推理分配 | CoBa（arXiv:2608.07424v2，85.13% vs 85.20%@−49.1% token）；Thought-Level Beam Search（arXiv:2608.08020v2，HMMT-24 +6.7pt / token −68.5%）；Self-Consistency（arXiv:2203.11171） | 生成 / 验证 / 停止；候选宽度；采样票数 | 参权 token | **不含**轨迹步数、工具调用、检索、视觉 |
| 预算感知的 agent | Budget-Aware Tool-Use（arXiv:2511.17006） | 是否继续用工具 | 剩余预算观测 | 预算**感知** ≠ 预算**构成** |
| 预算约束的 agent 评测 | EcoAgent-Bench（arXiv:2608.05519v1，304 任务，tool-API 微严格成功率 3.9–24.0%、经济一致性 ≤7.3%、升级率 0%→3%） | 升级 / 选档 / 止损 | 定价动作 | 只评测决策对错，不推导最优构成；其"预算扫不动决策"恰是我们 §5.2 结果的相关佐证 |
| 受控努力（源报告） | V4.1-Flash 技术报告 §5.1.4 + 附录 C（b∈{1..100}，k(b)=k0·exp(−(b−b_min)/τ)；25→100：67.1→76.3 / 66.0→74.2 / 82.4→90.6，token ~2.5×；60–80 前置） | **仅**推理 token 长度 | 推理 token | 其一轴被我们推广为五轴预算；其 scaffold / deadline 实验不构成多轴分配 |
| 综述 | Reasoning on a Budget（arXiv:2507.02076） | — | — | 定位用 |
| 基准 | SWE-bench（arXiv:2310.06770） | — | — | 长时程 agent 任务的动机来源 |

## 3. 可证伪 GAP 陈述

- **G1**：现有工作没有把「推理 token / 轨迹步数 / 本地工具 / 网络检索 / 视觉探针」放进**同一会计单位**与**同一预算**下做联合路由。可证伪：若存在同构工作，本工作的增量消失。
- **G2**：没有工作报告「最优努力**构成**随预算旋转」这一现象（现有工作报的是单轴标度律或单 episode 内的分配）。可证伪：找到一个展示多轴构成旋转的前作。
- **G3**：源报告的 b 是**推理长度**旋钮；把它当多轴预算旋钮使用时，其代价结构（步数 × 每步推理 token）在报告中未被讨论。可证伪：报告中若已有该乘性代价分析，则我们的"推广面"缩水。

## 4. 基线池（本工作实际比较的基线）

| 基线 | 定义 | 结果（token 币种） |
|---|---|---|
| all-max | 五轴全部拉满 | 0.6906 @ 145,600（匹配成功处与统一路由**平局**） |
| fixed-mid | (50,8,4,2,2) | 0.5320 @ 23,429 |
| reasoning-only max | b=100，其余中档 | 0.5478 @ 34,400 |
| agent-only max | 四 agent 轴拉满，b=50 | 0.6633 @ 101,717 |
| decoupled | 五份私有预算、各自贪心、禁止跨轴调剂 | 达 40% 成功需 3,284 vs 统一 2,484（1.32×） |
| 单轴消融 | 每次只动一个轴、其余中档 | 最佳单轴 0.548 |

## 5. 新颖性声称（每条必须绑定 ledger 条目）

- N1（ledger C21–C26）：首次（在我们检索范围内）把五个 agent 努力轴置于同一预算下求解联合前沿，并报告构成随预算旋转。→ 投稿前需重跑新鲜度门。
- N2（ledger C09 + C21–C24）：源报告声称推理努力控制"忠实地迁移"到 agentic 轨迹；我们给出该迁移的**代价侧**边界（步数 × 推理 token 的乘性代价使轨迹长度成为最后才买的轴）。→ 这是对源报告结论的补充而非反驳。
- N3（ledger C15–C19）：五轴成本的跨族离散度（0.033 ms → 2233.75 ms，同一逻辑动作出网 2194×）为"统一努力阶梯"的不可行性提供一手证据。

## 6. 新鲜度门（Phase 5 前必跑）

```
python3 scripts/check_literature_freshness.py . --claims-file novelty_claims.txt --max-age-days 30
```
现状：`novelty_claims.txt` **尚未落盘**，该门未跑，列为投稿前阻塞项 **O05**。
