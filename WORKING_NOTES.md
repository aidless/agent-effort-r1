# WORKING_NOTES.md

- 论文标题: From Controllable Reasoning Effort to Controllable Agent Effort: Joint Effort Allocation for Tool-Using Agents
- Phase: R2 完成（§E3 限定核验 + O05 新鲜度门 + G4 匿名仓去泄漏 + H4 harness CPU 验证就绪）
- 唯一权威来源: `evidence/V41FLASH_TechReport.txt`（与 `papers/_shared/evidence/` 下原件同 SHA-256）
  （3791 行，SHA-256 `ac24848a4dee30669b9caac6ca05b62d7186e4c546add099ccc906065288abf3`；
  **行号只以 `\n` 切分**，禁用 `str.splitlines()`——该法得 3841 行，+50 偏移）
- 错误来源（已排除，不得再引用）: `papers/csa2_robust/evidence/V41_2606.06467.pdf`
  （Microsoft CLSA / arXiv 2606.06467）

## 范围

把源报告唯一的可控努力轴（标量 b 作用于推理 token，指数惩罚 k(b)）推广为**五轴统一努力预算**：
`b_reason / b_steps / b_tools / b_search / b_vision`。增量点：源报告只把 b 用在推理 token；
其 scaffold 与 deadline 实验都不构成多轴预算分配。

## 假设（冻结于运行前，详见 HYPOTHESES.md）

- H1 统一预算优于分立预算 —— **已验证**（1.32× 成本优势 @40% 成功）
- H2 跨轴调剂优于均匀加码 —— **部分成立**（3.44×/4.52×/2.05× vs 三种非饱和基线；
  与 all-max 在匹配成功处平局，仅在“达 90% 可得成功的代价”上 8.67×）
- H3 最优构成随预算旋转 —— **已验证**
- H4 真实 LLM 下实测 g_x —— **未跑**（harness 已就绪并通过 CPU dry-run；阻塞于 GPU 排队）

## 开放问题

- U01 源模型本体的五轴路由收益：无法运行其 checkpoint，正文只作 quotation。
- U02 真实 LLM 策略下的 g_x：E3 用确定性规则修复器；**R2 已写好 `experiments/h4_real_llm_gx.py`
  （import 复用 E3 任务集/预算网格/判分）+ `experiments/h4_run_remote.sh`（锁 + 显存地板）**，
  CPU dry-run 896 episode 通过且拟合器回收自检 `all_recovered:true`；真跑待主会话放行 GPU。
  **工具链就绪 ≠ 已验证**：正文维持 conjecture，dry-run 产物不得进论文/匿名包。
- U04 `g_search`：本任务集无变化来源，H4 **明确不拟合**，保持未测而非填 0。
- U03 绝对延迟的跨主机可移植性：只把**比值**当可移植量。

## 证据包入口

| 产物 | 路径 | sha256（前 8 位） |
|---|---|---|
| 源引文包（40 引文 / 19 数值事实） | `evidence/v41flash_effort_control.json` | `54a2639a` |
| E1 通用工具延迟（12 项 / 1000+ 次） | `results/e1_tool_latency.json` | `e41aaf87` |
| E1b agent 原语（6 项 / 300 次） | `results/e1b_agent_primitives.json` | `da146146` |
| E2 联合分配（8,820 分配） | `results/e2_allocation.json` | `9fabfd79` |
| E3 端到端（240 episode） | `results/e3_agent_loop.json` | `2fb188ed` |
| H4 CPU dry-run（896 episode，**非测量**） | `results/h4_dryrun_stub.json` | 见 manifest |
| O05 新鲜度门报告 | `reports/literature_freshness.md` | 见 reports/ |
| 唯一复算产出（论文所有数字） | `results/stats.json` | `9fc51066` |

## 复算与编译

```
python3 analysis.py .                       # 必须输出 recompute checks passed: True
python3 experiments/extract_v41_effort_evidence.py   # 40 引文逐字校验
cd paper && SOURCE_DATE_EPOCH=1767225600 pdflatex main.tex   # 11 页，0 overfull
```

## 当前诚实状态

- 论文：11 页（含参考文献 + 2 附录），3 张表全部由实测/重算产出，无占位符、无注水。
- 未做：源模型实测（不可能）；真实 LLM 的 g_x 实测（**harness 就绪，阻塞于 GPU 排队** free 23852 < 25600）；跨主机延迟复测。
- R2 新增防线：匿名包泄漏门（绝对路径 + 内部队列结构/兄弟投稿目录，fail-loud）；
  出货前 redaction；H4 dry-run 与真跑产物靠 `dry_run`/`is_real_llm` 字段与命名隔离。

## 工具失效模式（实测，**必读**）

### W1：`write` 给 `F:\` 风格路径可能落到错误位置（不是"没写"）

本工作区路径**自身含反斜杠**（`/home/liuzewen/F:\deepseek` 是一个真实目录名），
而 bash 工具的 cwd 是 `/home/liuzewen`。`write` 拿到
`/home/liuzewen/F:\deepseek/papers/agent_effort/ROUND_R2.md` 时，**可能把
`F:\deepseek\papers\agent_effort\ROUND_R2.md` 整段当成一个文件名**，于是在 `$HOME`
下写出一个名字含反斜杠的**普通文件**——**文件写成了，只是位置错**。

实证：`$HOME/F:\deepseek\papers\agent_effort\ROUND_R2.md`（19090 B, 23:14）vs
工作区 `ROUND_R2.md`（18967→19027 B, 23:16）。**旁证：其它会话同样中招**
（见下：另一会话的 scripts/ 下两个文件与 results/smoke/ 下一条产物，以及若干**以盘符/反斜杠为名的目录**——具体名字不在本文件复述，以免把本机布局写进发布包）。

> 我最初的诊断是"报成功但静默不落盘"——**那是错的**，文件一直在，只是落错了地方。

**对策（写文件时一律执行）**
1. 用**工作区相对路径或 POSIX 绝对路径**，不要用 `F:\` 风格；
2. 写完**按绝对路径回读** `ls -l` + `sha256sum`，不要只信工具返回；
3. 落盘后扫一遍 `$HOME` 与 cwd 有无**含反斜杠/盘符的条目**——出现即失效信号。
   **必须用 `os.listdir` 判定，不要用 `ls | grep`**（实测同一目录：
   `ls -la | grep -c '\\'` = 1、`ls -1 | grep -cF '\'` = 8、`os.listdir` = **9**；
   `ls` 在管道下会转义/加引号含特殊字符的名字，**会漏报**）。权威计数以 listdir 为准。
4. `papers/agent_effort/` 下目前**没有**此类残留；`$HOME` 下的残留**一律不删**
   （删除属保护层，需用户授权）。当前 `$HOME` 权威计数：**9 个**（4 目录 + 5 文件）。

**失效的确切形态（2026-09-12 实测，比"整条路径当一个文件名"更精确）**：
解析器**沿正斜杠逐级解析直到第一个反斜杠**，此后**其余整段并成一个文件名**，
落在已解析到的那一级目录里。即 `/A/B/C\D\E.py` → 目录 `A/B/` 下出现**单个文件** `C\D\E.py`。

因此错误落点**不只在 `$HOME`**：
- `/home/liuzewen/` 下：一条本论文的 ROUND 报告（19090 B，整条路径入名）；
- **`papers/` 内**（跨会话都有）：一条本轮的 `agent_effort\...` 分析脚本（7744 B，我的）、
  **一条别的会话的 `papers/<另一篇>/...` 控制分析脚本**。

**推论（重要）**：写文件路径里**除了工作区根那个 `F:\` 之外，任何位置都不得再出现反斜杠**。
本会话的成功写入全都长这样：`/home/liuzewen/F:\deepseek/papers/agent_effort/<文件>`——
`F:\deepseek` 之后**一律正斜杠**。凡在 `agent_effort` 之后又写 `\`（如
`agent_effort\experiments\x.py`）的，必落错位置。
**恢复办法**：从错误落点 **copyfile 到正确路径**（不是移动、不删除原残留）。

> 另注：`papers/` 内的那个 stray 目录/文件**不在**本论文的匿名包白名单内
> （打包只取 `papers/agent_effort/{paper,experiments,results,evidence}`），故不影响 G4/G9/G10；
> 已重跑门禁确认。

### W2：报告里的哈希必须是**对该文件的最后一次操作**

同一模式犯过**两次**：先算哈希 → 之后又编辑 → 汇报时用的是旧哈希，于是**报告里的哈希
指的不是任何现存制品**。固定顺序：**写完所有内容 → 跑完全部门 → 最后算哈希 → 立即汇报**；
汇报后不再改该文件；还要改就重新算并重报，或写「**哈希待定**」。
哈希与大小必须来自**同一次读取**。本文件因此不固化任何字面哈希，以
`evidence_manifest.json`（重建 + `--verify` 通过）为权威。

### W3：远端 H4 运行的三个环境事实（GPU 宿主，会反复咬人）

1. **vLLM 0.27.1 默认 `VLLM_USE_FLASHINFER_SAMPLER=1`，但该镜像没有 `flashinfer` 模块**
   → EngineCore 启动即 `ModuleNotFoundError: No module named 'flashinfer'`，报错栈会指向
   attention backend，很容易被误判成模型/权重问题。**必须** `export VLLM_USE_FLASHINFER_SAMPLER=0`。
2. **`gpu_memory_utilization` 是占【总量】的比例，不是占空余**。共享机上按总量设会 OOM
   （实测：别家作业占 12.8 GB 时 `0.90×48 GiB` 必然失败）。正确做法按空余设：
   `util = min(requested, (free − 2 GiB)/total)`；harness 已自适应并记录
   `gpu_memory_utilization_detail` 与 `gpu_state_at_load`。
3. **GPU 存在不守锁的并发占用**：实测有视频生成作业（`direct_run.py` + ComfyUI :8188）
   在**锁 FREE** 的情况下占用 12.8 GB / 100% 利用率。→ 真跑的 wall-clock 会被第三方污染，
   **必须披露**，不得当作 H4 自身开销。

### W4：Qwen3 混合推理默认开 thinking —— 会静默摧毁 JSON 协议实验

Qwen3 默认 `enable_thinking=True`，会先生成约 **974 token** 的 `<think>` 才给正文，
于是 `max_tokens` 常在 JSON 之前耗尽 → **动作解析失败**。实测（同 prompt 各 6 次）：

| 模式 | 平均耗时 | 平均 token | JSON 合法率 |
|---|---|---|---|
| thinking ON | 7.46 s | 974 | 6/6 |
| thinking OFF | **0.58 s** | **74** | 6/6 |

→ **12.9×** 加速。在 pilot 里 thinking ON 造成 **10/40 = 25% episode 死于 `parse_failures`**
（`results/h4_pilot_steps.json` 实测计数；早先误写 30%，已按产物更正），
把"预算→成功率"曲线压成假的低平台（看起来像"加步数无用"）。
对策：`tok.apply_chat_template(..., enable_thinking=False)` 后 `generate`，并把
`chat_mode_requested/effective` 写进产物；**任何 JSON 动作协议实验都应先验证这一点**。
- 不得声称：任何关于源模型本体的可控性结论（只能引用其报告），
  以及任何“LLM agent 在真实策略下也这样”的结论（E3 策略非 LLM）。
