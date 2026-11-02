# Bench — Agent Effort R1 实测基准

> 本目录登记 agent-effort-r1 的**真实基准**：四个证据层（E1/E1b/E2/E3/H4）的测量结果。
> 所有数字都能从 `results/stats.json` 与六个保留输入文件重取（`python3 analysis.py`，无网络、无模型调用）。
> **关键边界**：本仓库的 E2 是**说明性资源松弛**（illustrative resource relaxation），**不是已验证的部署前沿**；
> E1/E1b 是宿主机延迟采样；H4 是**保留记录**（retained records），不是独立样本。

## 基准 1 — E1/E1b 工具延迟（实测，`results/stats.json` → `E1_E1b_latency`）

| 原语 | n | 失败率 | mean (ms) | p95 (ms) | 来源 |
|---|---|---|---|---|---|
| T1_shell_simple | 120 | 0.0 | 1.305 | 1.422 | `results/stats.json` |
| T2_shell_command | 90 | 0.0 | 7.129 | 8.109 | 同上 |
| T3_python_exec | 60 | — | — | — | 同上 |
| P1_image_codec_png | 60 | — | 177.341 | — | `CLAIM_LEDGER.md` C0001 |
| P2_screenshot_capture | 30 | **n_ok=0** | 0.075 | — | `CLAIM_LEDGER.md` C0006/C0008 |
| P6_json_tool_call | 60 | — | 33.982 | — | `CLAIM_LEDGER.md` C0025 |

- **判读**：延迟是**宿主机实测**；P2 截图捕获 `n_ok=0`（30 次全部失败）被如实记录，**未编造成成功**。
- **边界**：延迟样本来自单一宿主（Python 3.10.12, 96 vCPU），不构成跨环境的普遍延迟结论。

## 基准 2 — E2 分配网格（8,820 元组，实测计算）

| 基线 | 模型化成功 | 成本 (tokens) | 来源 |
|---|---|---|---|
| B1_all_max | 0.6906 | 145,600.0 | `results/stats.json` → `E2_allocation.baselines` |
| B2_fixed_mid | 0.5320 | 23,429.2 | 同上 |
| B3_reason_only_max | 0.5478 | 34,400.0 | 同上 |
| B4_agent_only_max | 0.6633 | 101,716.8 | 同上 |
| 最优（20,000-token） | 0.6305 | — | `paper/main.tex` §Related work |
| **成本比率（vs 固定中位）** | **3.44** | — | README（模型化 token 成本比，至少匹配模型化成功） |

- **判读**：E2 用**假定的成功函数**做穷举有限网格优化（8,820 个分配）；`3.44` 比率比较「最优」与
  「固定中位」，**不是实测部署收益**。README 明确分离「测量」与「假定」。
- **边界**：`(100,1,16,16,16)` 最优元组（模型化成功 0.6305）**不是可行的单动作每轮 H4 轨迹**——
  网格把坐标当成独立可分配，无动作依赖约束。故 E2 是**说明性资源松弛**，不是部署前沿。

## 基准 3 — H4 Qwen3 记录（保留记录，非独立样本）

| 模型 | 保留记录 | 峰值成功（低预算） | 峰值成功（最大预算） | 来源 |
|---|---|---|---|---|
| Qwen3-8B-AWQ | 672 | **0.9375** | **0.7500** | README / `results/stats.json` |
| Qwen3-14B-AWQ | 672 | 1.0000（中预算） | **0.8750** | README / 同上 |

- **判读**：每文件 672 条 = 240 耦合预算 + 432 单轴扫描；三个重复**完全相同**的成功结果——
  是重复执行，**不是独立任务抽样**。
- **边界**：H4 的保留脚本指纹与提交的 harness 快照**不匹配**，运行时快照未恢复——协议报告的是
  提交实现，数字描述的是保留记录。**不声称**当前代码能完全验证历史执行。

## 复现（无网络、无模型调用）

```bash
python3 analysis.py   # 六输入文件 → results/stats.json（12 位小数，确定性离线）
pytest -q tests       # 2 条确定性重算检查（byte-match + headline contract）
```

证据链：`CLAIM_LEDGER.md` + `evidence_manifest.json`（每个数字 → 证据文件 SHA-256）。
