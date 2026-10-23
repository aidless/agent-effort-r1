# Revision Round R2 报告 — 限定补齐 + 新鲜度门 + G4 匿名仓 + H4 harness 就绪

日期：2026-09-11 ｜ 论文：From Controllable Reasoning Effort to Controllable Agent Effort
上一轮：R1 ｜状态：已完成 ｜本轮成本：**0（全程 CPU；GPU 未使用、未取锁）**

## 0. 接手声明（冷接管口径）

本轮由接手者执行。前一个 agent 在 22:13 于 **写 H4 harness 途中被中断**；磁盘状态已先读后动，
R1 的既有产物（E1/E1b/E2/E3 结果、`stats.json`、`analysis.py`、`paper/main.*`、20/20 门禁、
78 条 manifest）**未重做**。接手时 `main.tex` 已含 §E3 限定句（sha256 `ff3ef071…`）；
本轮**未改动 `main.tex`**（改后重验：sha256 仍为 `ff3ef0718fbe1bbb306b15e09b1711b39bf3178f806172aae3094d7e6ed08086`）。

## 1. 本轮范围

四项任务：(1) §E3 补限定；(2) O05 文献新鲜度门；(3) G4 匿名仓库准备；(4) H4 harness 写好并
CPU 验证到可运行。

## 2. 任务一：§E3 限定（核验为主，未改写）

`paper/main.tex` §E3（`sec:res-e3`）已含所需限定，原文：

> The information in this curve is concentrated in its lower two levels: three of
> the five budget levels (mid, high, max) sit at $1.000$, so the upper half of this
> particular frontier carries no discriminating information. The task set used here
> saturates at $8$ steps; ``buying more steps yields nothing'' is therefore a
> statement about the ceiling of \emph{this eight-task set}, not a general law about
> agent effort. A harder task set would move the saturation point and reopen the
> upper region, and we flag this as the main way the E3 result under-reports the
> regime a real agent operates in.

覆盖要求的三点：上三档全 `1.000`、饱和点为 8 步、显式否定"普遍规律"读法。
与既有 saturating 句（"saturates early … no further gain from four times the budget"）
互补而不冲突：前者陈述曲线形状，本段限定其**适用范围**。
本轮**未改动该句**，以免无必要改稿触发新的门禁漂移。

## 3. 任务二：O05 文献新鲜度门（已跑，门 PASS）

```
python3 scripts/check_literature_freshness.py . --max-age-days 30 \
        --claims-file novelty_claims.txt --out reports/literature_freshness.md
```

| 字段 | 值 |
|---|---|
| Missing | 0 |
| Age_days | 0 |
| Stale | 0 |
| Claims_count | 3（`novelty_claims.txt`） |
| Max_age_days | 30 |
| Novelty_drift | 0 |
| 段落（深度信号） | 14 |

`--fail-on-stale` 退出码 **0**（门 PASS）。报告落盘 `reports/literature_freshness.md`。

> 口径说明：`Age_days` 是 `LITERATURE_REVIEW.md` 的**真实 mtime 距今天数**，即"综述新鲜度"，
> 不是"文献新鲜度"。它只能证明定位未被搁置过久，**不能**证明检索已覆盖 30 天内新工作。
> 因此只把它当**过期门**用，**不据此提高 novelty 断言强度**；novelty 三条维持原文口径
> （"within our retrieval scope"）。

## 4. 任务三：G4 匿名仓库（已就绪，仅剩人工外发）

### 4.1 本轮发现并修复的真实泄漏（前轮已随包出货）

`make_submission_bundle.py` 原只审计**绝对路径**（`/root/...`、`/home/...`、`C:\...`），
不审计**内部队列结构**；`check_submission_package.py` 的 C3 只查作者/机构串，同样不覆盖。
结果：上一个包**带着下列内部引用出货**，本轮全部拦截：

| 位置 | 泄漏内容 | 类别 |
|---|---|---|
| `paper/main.bib` | `papers/\_shared/evidence/V41FLASH\_TechReport.txt` | **在稿件本身**（会渲染进 PDF 参考文献） |
| `evidence/v41flash_effort_control.json` | `source_path: ../_shared/…`、`source_path_shared: papers/_shared/…` | 证据包 |
| `evidence/v41flash_effort_control.json` | `provenance.wrong_source_excluded: papers/csa2_robust/…` | **点名兄弟投稿目录** |
| `experiments/extract_v41_effort_evidence.py` | `os.pardir, "_shared", …` 回退路径 | 工具源码 |
| `CLAIM_LEDGER.md` / `HYPOTHESES.md` / `LITERATURE_REVIEW.md` / `WORKING_NOTES.md` | `papers/_shared/…`、`papers/csa2_robust/…`、`papers/agent_effort/` | 过程文档 |

**为什么算 G9/G10**：点名共享证据树或**兄弟投稿目录**，使同一评审周期内的两份投稿可被关联，
即使没有任何绝对主机路径，也构成双盲隔离失败。

### 4.2 修复方式（源头修 + 出货前 redact + 独立门）

1. **源头修**（真修，不是出货前掩盖）：
   - `paper/main.bib`：改指包内路径 `{\tt evidence/V41FLASH\_TechReport.txt}` 并**重编译**。
   - `extract_v41_effort_evidence.py`：新增 `source_path`（固定为包内文档路径）与
     `source_resolved_via`（`env:V41_REPORT_TXT` / `authoritative source tree` / `in-package copy`），
     不再把解析来源的相对路径写进证据包；`wrong_source_excluded` 改为不含兄弟目录名的说明。
     工作副本仍支持共享树回退（门禁裸跑需要），**出货副本由显式整块替换**为两个分支。
2. **出货前 redaction**：`redact_tree()`；替换以**明文整块**为主（可审阅），正则仅兜底。
   redaction 在**哈希之前**执行，故 manifest 记录最终字节。
3. **独立门**：`leak_scan()` 扫 `papers/`、`papers[_/]\\?_shared`、`\_shared`、`"_shared"`
   **以及队列中全部兄弟目录名**（实取 7 个：`_shared, async_rl_2bit, csa2_robust, encoder_memory,
   engram_vs_kv, multiagent_scaling, science_factory`）。命中即 **exit 1**，不静默。

### 4.3 结果

| 指标 | 修前 | 修后 |
|---|---|---|
| 文件数 | 37 | **36**（净 −1：移出打包基础设施；H4 产物本就不在前一轮的 37 件内） |
| 绝对路径命中 | **14** | **0** |
| 内部结构/兄弟投稿泄漏 | 13（未审计→已存在） | **0** |
| 被 redaction 改写文件 | — | 6 |
| 门退出码 | — | **0** |

泄漏门**fail-loud**：任何一处替换失效会立即 exit 1。本轮已实证——改
`extract_v41_effort_evidence.py` 后替换一度失配，门立刻报 2 处泄漏并 exit 1，
修正 `EXTRACTOR_FALLBACK_OLD` 后归零。

**未出货清单**：

| 文件 | 理由 |
|---|---|
| `experiments/make_submission_bundle.py` | 打包基础设施，天然编码队列布局 |
| `experiments/h4_real_llm_gx.py`、`h4_gx_measure.py`、`h4_queue_step.sh`、`h4_run_remote.sh` | **H4 未跑、无论文数字依赖、必带主机 GPU 锁与模型路径**；未跑的 harness 随包出货会同时泄漏主机路径并暗示不存在的证据 |
| `results/h4_dryrun_stub.json` | harness 已排除，裸 dry-run 产物不可解释 |

### 4.4 剩余人工步骤（保护层：外发 + 不可逆，必须由人做）

`submission/repo/ANON_REPO.md` 已列明：
1. 建匿名镜像（`anonymous.4open.science` 或匿名 GitHub org）；
2. 上传该目录的**内容**（非父目录）；
3. 把 URL 写进稿件复现章节与 OpenReview 补充材料字段，再跑
   `check_tmlr_compliance.py … --names "" --exclude-dir evidence` 确认 host 在白名单；
4. 重跑 `check_submission_package.py . --fail-on-error`。

装包：`submission/repo/` **36 文件** + `submission/submission_agent_effort_anon.zip`
（**38 条目，0.51 MB，确定性 zip**；条目数 = 文件 + 目录）。

## 5. 任务四：H4 harness（已写、CPU 验证到可运行，**未起 GPU**）

### 5.1 与 E3 的同构性（结构性保证，非复制）

`experiments/h4_real_llm_gx.py` **运行时 import** `experiments/e3_agent_loop.py`，取用其
`TASKS`(8) / `BUDGET_LEVELS`(5) / `SCHEDULES`(2) / `run_hidden_tests`。任务集、五档预算网格、
两个动作调度与判分调用与 E3 **同一对象**，不可能漂移。E3 的调度轴在此实现为**可选动作菜单**：
`read_then_write → {read,write,test}`，`probe_heavy → {read,probe,write,test}`。

与 E2 参数化的对应：`b_steps↔g_steps`、`b_tools↔g_tools`、`b_vision↔g_vision`（沿用 E3 的
probe 视觉代理口径），`g_search` 在本题集上**无变化来源，声明为 UNMEASURED 而非拟合**。

### 5.2 真实验设计

- **iso 臂**：E3 的五档耦合预算 × 2 菜单（复现臂）。
- **三个单轴臂**：每次只动一个轴，其余固定在 **E2 的 MID 分配**（steps=8, tools=4, vision=2）——
  **固定在内部点而非天花板**：伴随轴已饱和则主轴增益不可辨识。
  轴电平取 E2 自身网格：steps `[2,4,8,16,32]`、tools `[0,1,2,4,8,16,24]`、vision `[0,1,2,4,8,16]`。
- **拟合**：`1-p = (1-p0)·∏_x (1 - g_x·(1-exp(-b_x/ref_x)))`，加权最小二乘 + 400 次 bootstrap CI；
  **可辨识性护栏**：某轴扫描内点（严格落在 (0,1)）< 2 个则**拒绝给出点估计**，列入 `unidentified_axes`。
- **结构性不可行格**（`max_steps<2` 或 `max_tool_calls<1`）不进拟合，单列
  `floor_cells_excluded_from_fit`——任何策略在此都不可能通过，算进增益就是阈值效应冒充增益。
- **判分**：隐藏 unittest 子进程退出码，唯一判据；客户端只拿 `{rc:0|1}`，**不泄露回溯文本**。
- temperature 0 + 逐请求 seed；声明 GPU 采样确定性非精确。

### 5.3 本轮踩到并修掉的三个**真缺陷**（都是 harness 自身，不是数据）

| # | 缺陷 | 症状 | 根因 | 修法 |
|---|---|---|---|---|
| H4-FIX-01 | 逐 episode 种子由 `len(task_id)` 派生 | 任务 id 长度只取 17/18 两个值，896 episode 实际只有 **2 个独立抽样**，成功率为粗阶梯（0.625 反复） | 种子未按任务 id 哈希展开 | `episode_seed()`：sha256(task_id) 取模 → 8 个互异种子（已断言 `distinct==8`） |
| H4-FIX-02 | stub 策略不感知预算，把可行性当增益 | `g_steps` 拟合 0.50 vs 声明 0.35；`max_steps=2` 因 read+write+test 超步必然失败，拟合器读成该轴已饱和 | 固定动作序列撞硬步数阈值 | `_stub_plan()` 预算感知：只在强制后缀（write+test）仍可完成时才加 read/probe |
| H4-FIX-03 | 结构性不可行格进入拟合 | `max_tool_calls=0` 恒 0（无 test 调用即无判分），被摊到增益上 | 未区分"阈值地板"与"增益" | 新增 `structurally_feasible()`，不可行格移出拟合并单列 |

> 三条与 R1 的 FIX-01/FIX-02 同类：**建模/实现错误造出的假效应**，不是数据问题（FM-15）。

### 5.4 CPU dry-run 证据（**不是**任何模型的测量）

```
python3 experiments/h4_real_llm_gx.py --backend stub --repeats 4 \
        --out results/h4_dryrun_stub.json --ref-sensitivity
```

- 896 episode（25 臂 × 8 任务 × 4 重复，含被排除的不可行格），**exit 0**，约 90 s，全程 CPU。
- `dry_run: true`、`is_real_llm: false`、`backend: "stub"` 写入产物，`declared_limits` 内明写
  "STUB BACKEND: this file is a CPU dry run and is NOT a measurement of any model"。

**增益回收自检**（把 dry-run 从冒烟测试升级为拟合器验证）：stub 用 E2 的函数形式以**已声明的
仿真常数** `STUB_TRUTH = {p0=0.55, g_steps=0.35, g_tools=0.28, g_vision=0.22}` 抽签，
拟合器必须还原：

| 轴 | 声明值 | 拟合值 | 绝对误差 | bootstrap 95% CI | 落在 CI 内 |
|---|---|---|---|---|---|
| `g_steps` | 0.35 | 0.3239 | 0.0261 | [0.000, 0.521] | ✅ |
| `g_tools` | 0.28 | 0.2912 | 0.0112 | [0.000, 0.454] | ✅ |
| `g_vision` | 0.22 | 0.3250 | 0.1050 | [0.140, 0.426] | ✅ |

`stub_gain_recovery.all_recovered = true`；17 个可行格进入拟合；三轴均可辨识
（内点 5/6/6，成功率取值互异）；`p0=0.522` vs 声明 0.55。
**含义**：拟合器能从已知真相的模拟中回收真相——验证的是**代码**，不是模型。
CI 偏宽（n=32/格）如实报告，未粉饰。`ref_sensitivity` 27 组已产出。

### 5.5 GPU 纪律（已 CPU 侧验证，**本轮未取锁、未用 GPU**）

- 单锁 `/root/autodl-tmp/gpu.lock`，`flock`；**非阻塞**——锁被占立即 ABORT，绝不静默排队。
- 起 GPU 前 `nvidia-smi` 查显存；低于地板即 **ABORT 且不绕锁**（`MIN_FREE_MIB=25600`；14B 走 30000）。
  vllm/torch 全部**惰性 import**（AST 已验证：顶层无 vllm/torch）。
- 实测：`--preflight-only` → `{"verdict":"ABORT","free_mib":5792,"required_free_mib":25600}`，
  **exit 3**；`--backend vllm` 主路径同样 **exit 3** 并打印 "the shared GPU lock is not bypassed"。
- 锁原语三态实测：取锁（写 pid/时间戳）、释放、**竞争 fail-loud**
  （`gpu_lock_busy:[Errno 11] Resource temporarily unavailable`）。
- 包装器 `experiments/h4_run_remote.sh`：模型路径不存在 → exit 2；显存不足 → exit 3；
  抢锁失败 → exit 4。本地实跑均正确 ABORT（未触及 GPU）。
- 产物一律写 `/root/autodl-tmp/h4_agent_effort/`（根分区仅剩 ~1.1 GB）。

### 5.6 就绪状态：**就绪待跑（阻塞于 GPU 排队，非本 harness）**

远端实测（2026-09-11 23:00）：RTX 3090 48 GB，**free 23852 MiB / used 24700 MiB / util 100%**；
按纪律 `free < 25600` → **ABORT，不绕锁**。故本轮按要求**只验证到可运行**。
模型已核实：`/root/autodl-tmp/models/Qwen3-8B-AWQ`（5.7 GB）、`Qwen3-14B-AWQ`（9.4 GB），
均 AWQ 量化 Qwen3ForCausalLM；远端 vllm 0.27.1 / torch 2.13.0+cu130 / Python 3.10.12。

真跑单条命令（等主会话通知后）：
```
bash experiments/h4_run_remote.sh                    # Qwen3-8B-AWQ，默认
MODEL=/root/autodl-tmp/models/Qwen3-14B-AWQ TAG=qwen3_14b bash experiments/h4_run_remote.sh
```
预计规模：25 臂 × 8 任务 × 3 重复 = 600 episode（每 episode 多轮 LLM 调用）。

## 6. 机器检查（本轮全绿）

| 检查 | 命令 | 结果 |
|---|---|---|
| 唯一脚本复算 | `analysis.py .` | PASS（E3 五档 0.000/0.500/1.000/1.000/1.000；monotone True） |
| claim ledger | `verify_claim_ledger.py .` | **33 PASS / 0 FAIL / 0 WARN** |
| 验收门（全量） | `run_acceptance_gates.py gates_config.json --record` | **20/20 PASS**（exit 0） |
| manifest 对账 | `build_evidence_manifest.py . --verify` | **123 PASS / 0 FAIL / 0 WARN** |
| 投稿包检查 | `check_submission_package.py . --fail-on-error` | **7/7 PASS**（exit 0） |
| TMLR G1–G11 | `check_tmlr_compliance.py . --names "" --exclude-dir evidence` | 6 findings / **0 failures** |
| 编译门 | `compile_gate.py .` | PASS（11 页，0 overfull，0 未定义引用） |
| 写作风格 | `check_writing_style.py .` | **0 findings** |
| 幻觉扫描 | `scan_hallucination.py . --fail-on-error` | 0 引用错误 / 0 命名缺失 |
| 污染传播 | `verify_taint.py . --fail-on-error` | 0 tainted（33 claims） |
| 新鲜度门 | `check_literature_freshness.py . --max-age-days 30 --fail-on-stale` | **exit 0**（Age_days 0, Stale 0） |

中间态留档：改 `extract_v41_effort_evidence.py` 后，门 "source quotations re-verify byte-for-byte"
与 "manifest hash reconciliation" 曾 **FAIL（18/20）**——因为改成只看包内路径，而包内是 867 B 的
**指针 stub** 而非 163 KB 真实报告。修法是恢复共享树回退（工作副本），出货副本走显式整块替换。
**未通过的门没有被绕过**：`main.bib` 泄漏也一并从源头修掉并重编译。

## 7. 本轮自我发现（诚实项）

| 项 | 说明 |
|---|---|
| 接手时 §E3 限定已在盘上 | 未重做、未改写，仅核验（sha256 与 manifest 一致） |
| **H4 与前一 agent 的工作重叠** | 前 agent 22:12–22:13 已写 `h4_gx_measure.py` / `h4_queue_step.sh`（被中断）。本 agent 先写了自己的 `h4_real_llm_gx.py` 后才发现，**存在重复劳动**（接手信息未含这两个文件）。两份均保留在盘上（删除属保护层，未获授权） |
| dry-run 不能当测量 | stub 产物显式标 `dry_run/is_real_llm`，不进论文、不出货 |
| 新鲜度门语义 | 只证明综述未被搁置，不提高 novelty 断言强度（§3） |
| `ROUND_R2.md` 首次写入**落到错误位置**（原诊断"未落盘"已按实证修正，见 §7.2、§7.3） | 首次 `write` **确实写成功了**，但落成 `$HOME` 下**名字含反斜杠的单文件** `/home/liuzewen/F:\deepseek\papers\agent_effort\ROUND_R2.md`（19090 B，23:14），而非工作区路径。**教训：工具报成功 ≠ 写到目标位置；必须以绝对路径回读确认** |
| 未修复、仅披露 | 远端起跑仍受 GPU 排队阻塞；`g_search` 在本任务集上无法测量；`QUEUE.md`/`csa2_robust` 在本轮期间有**并发 agent** 的 mtime 变动（非本 agent 所为，本 agent 未触碰） |

### 7.1 两份 H4 harness 的差异（供决策，本轮不擅自删）

| | `h4_gx_measure.py`（前 agent，被中断） | `h4_real_llm_gx.py`（本轮，已验证跑通） |
|---|---|---|
| 策略 | 单轮：模型一次写出完整 `sol.py` | 多轮 ReAct：逐轮 JSON 动作 `read/probe/write/test` |
| 轴 | steps / tools / **context**；search、vision 声明未测 | steps / tools / **vision(probe 代理)**；search 声明未测 |
| 与 E2 `g_x` 对应 | context **不是** E2 的轴（E2 五轴无 context） | 三轴 1:1 对应 E2 的 steps/tools/vision |
| 预算网格 | 自带电平，`mid` 固定 | 复用 E3 五档 + E2 轴电平；伴随轴取 E2 MID |
| 模型后端 | transformers（AWQ 原生，失败退 fp16 反量化） | vLLM（`quantization="awq"`） |
| 可辨识性护栏 | 无 | 有（内点<2 则拒绝给点估计） |
| fitted 自检 | 无 | 有（`stub_gain_recovery`，已通过） |
| CPU dry-run | 有 `--dry-run` 标志，未验证运行 | 已 896 episode 跑通，exit 0 |

**建议**：以 `h4_real_llm_gx.py` 为准（与 E2 参数化 1:1、复用 E3 网格、有可辨识性与回收自检、
已 CPU 验证）；前 agent 的"伴随轴固定于 mid"思路已吸收进本 harness。
是否删除旧文件请主会话决定（删除属保护层）。

### 7.2 修正：`write` 的失效模式是"落到错误位置"，不是"静默不落盘"

初审时我在工作区找不到 `ROUND_R2.md`，据此写成"报成功但未落盘"。主会话在 `$HOME` 下发现残留后，
该诊断**已被实证推翻**，正确机制如下。

**工作区路径本身含反斜杠**（关键背景）：

```
/home/liuzewen/F:\deepseek          <- 真实目录，名字里带一个反斜杠
cwd（bash 工具）                     = /home/liuzewen
```

`write` 拿到 `/home/liuzewen/F:\deepseek/papers/agent_effort/ROUND_R2.md` 时，若把
`F:\deepseek\papers\agent_effort\ROUND_R2.md` 整段当成**一个文件名**，就会在 `cwd`（即 `$HOME`）
下写出一个名字含反斜杠的**普通文件**——文件写成了，只是**位置错**：

| 位置 | 大小 | mtime |
|---|---|---|
| `$HOME/F:\deepseek\papers\agent_effort\ROUND_R2.md`（错误落点，单文件） | **19090 B** | 23:14 |
| `papers/agent_effort/ROUND_R2.md`（正确落点，工作区） | 18967→19027 B | 23:16 |

**旁证：不是本 agent 独有**。`$HOME` 下同类残留（均为名字含反斜杠的单文件/目录）：

```
F:\deepseek\papers\<另一会话>\scripts\ 下 1 条（引用核验脚本，6127 B）
F:\deepseek\papers\<另一会话>\scripts\ 下 1 条（候选 JSON，6935 B）
F:\deepseek\papers\<另一会话>\results\smoke\ 下 1 条（smoke 产物，1565 B）
目录：F:  E:\  F:\deepseek  F:\\deepseek
```

**对应排查**：工作区 `papers/agent_effort/` 下**没有**任何含反斜杠/盘符的条目（本 agent 未在工作区制造残留）；
四个对应产物的**工作区副本均存在且内容完整**，故**没有证据断链，无需重做任何实验或产物**。
所有残留文件**一个都没有删除**（删除属保护层，未获授权）。

**对策（已执行，并写入 `WORKING_NOTES.md`）**：
1. 写文件用**工作区相对路径或 POSIX 绝对路径**，避免 `F:\` 风格；
2. 写完**按绝对路径回读** `ls -l` + `sha256sum`，不只看工具返回；
3. 每次落盘后扫 `$HOME` 与 cwd 有无**含反斜杠/盘符的条目**——这本身就是失效信号。
   **必须用 `python3 -c "import os;print([n for n in os.listdir(p) if '\\\\' in n])"` 之类的 listdir，
   不要用 `ls | grep`**：实测同一目录下 `ls -la | grep -c '\\'` 得 1、`ls -1 | grep -cF '\'` 得 8、
   `os.listdir` 得 **9**——`ls` 在管道下会对含特殊字符的名字加引号/转义，`grep` 因而是**会漏报的**。
   我先前"7→8"的计数正是来自这个不可靠方法，**权威计数以 listdir 为准**。

**该失效在 R2 期间**仍在发生（活体复现，非历史遗留）。用 `os.listdir` 复核，
`$HOME` 下含反斜杠/盘符的条目**权威计数为 9**：

```
E:\                                                  dir
F:                                                   dir
F:\\deepseek                                         dir
F:\deepseek                                          dir
F:\deepseek\.agent-memory\ledger\lessons.md     2650 B   23:32:43  <- 与我的 evolve_add 调用同刻
F:\deepseek\papers\agent_effort\ROUND_R2.md    19090 B   23:14
F:\deepseek\papers\<另一会话>\scripts\ 下 1 条（候选 JSON，6935 B）
F:\deepseek\papers\<另一会话>\scripts\ 下 1 条（引用核验脚本，6127 B）
F:\deepseek\papers\<另一会话>\results\smoke\ 下 1 条（smoke 产物，1565 B）
```

（前四点为我发现、主会话独立复核一致的实测结果；主会话扫得同为 9 个。）

即**记忆/进化工具也走同一条错误路径**，不只是 `write`。两点后果必须记清：

- 工作区 `papers/agent_effort/` 下仍**无**任何含反斜杠条目，论文产物未受污染；
- 但该 stray 里的内容是**另一个会话的条目**（`science_factory` 的 L0001–L0004），
  **我在本会话追加的那条经验不在它里面**；工作区 `.agent-memory/ledger/lessons.md`
  （22101 B, 21:55）里也**没有**该条（`grep` 命中 0）。
  故**本会话的 lessons 追加没有落到工作区账本**，仅有工具返回的成功回执。
  因此我把该经验**另行固化到本文件 §7.2 与 `WORKING_NOTES.md` 的 W1**（论文自身的持久记录），
  不依赖那条可能落错位置的账本；stray 文件**一律未删**。

> 机制说明：stray 内容为**其它会话**条目这一点，只能说明"该文件由进化/记忆装置整体重建"，
> 不能证明重建的具体代码路径——上述"同样落错位置"是**观察到的巧合时刻 + 同一路径形态**的推断，
> 非直接证明；能确证的是**事实层**：新 stray 出现在 `$HOME`、我的条目不在任何账本里。

### 7.3 修正：`ROUND_R2.md` 的哈希我报错了（陈旧哈希配了新大小）—— **同一模式犯了两次**

我在汇报里写"19027 B、`ac87a1e2…`"。**这是错的**；主会话在磁盘上算出的是 `0a75df94…`。实测复核：

| 版本 | 大小 | sha256（前 16） |
|---|---|---|
| 当前工作区文件 | **19027 B** | `0a75df94d76bae20` |
| 我首次算哈希时的版本 | **18967 B** | `ac87a1e2dec1037d` |
| 主会话在磁盘上算到的 | 19027 B | `0a75df94…` ✅ 与当前一致 |

**成因（已复现证明）**：我先对文件算了哈希（`ac87a1e2…`，当时 18967 B），**之后又改了一行**
（把文件数那一行的理由写准确，净 +60 B），文件变成 19027 B，但汇报时**沿用了旧哈希、只更新了大小**
——即"陈旧哈希 + 新大小"的转录错误。可复现证据：把当前文件那一行改回旧写法，恰好得到
18967 B / `ac87a1e2…`（已实测验证）。

**结论**：文件**从未被他人改动**，也不是截断；**是我报错了一个数字**。

**同一模式在本次指派中犯了两次**——第二次：我向主会话报 `ROUND_R2.md` = 19027 B / `0a75df94…`，
之后**又改了该文件两处**（§7.2 的 9 个 stray 与 §7.3 本身），于是那个哈希**立即再次作废**。
主会话指出这不是诚信问题而是**流程问题**，但后果一样：**报告里的哈希指的不是任何现存制品。**

### 7.4 哈希纪律（硬规则，据此执行）

> **哈希必须是对该文件的最后一次操作。**

固定顺序：**写完所有内容 → 跑完全部门 → 最后算哈希 → 立即汇报**。
汇报之后**不再改该文件**；若确需再改，则重新算哈希并重报，或在汇报里写
「**哈希待定（hash pending）**」，**绝不给出一个会过期的值**。
哈希与大小必须取自**同一次读取**（`sha256sum` 与 `stat` 相邻执行）。

本文件因此当前处于「**哈希待定**」状态：本文档仍在被编辑，其权威哈希以
`evidence_manifest.json`（每次重建后 `--verify` 通过）中的值为准，**不在正文中固化一个会过期的字面值**。

## 7.5 H4 真跑完成（2026-09-12）—— 结果与预期相反，**主结果是负结果**

真跑已完成（`think_off`，672 episode）。**完整证据与逐条复算见 `H4_FINDINGS.md`**；此处只记要点与纪律：

- **主结论**：单调增益模型**被数据拒绝**——同构 5 档成功率 0.0000 / 0.9375 / 0.8750 / 0.8125 / **0.7500**
  （低档后**逐档下降**）；配对 McNemar L1→L4 **恶化 9 / 改善 0 / ties 39，exact p=0.0039**。
- **三轴 g_x 点估计全部不可辨识**（CI95 宽度 1.0000 / 1.0000 / 0.5801 > 0.30）→ **不得引用任何数值**。
- **机制（可引用）**：预算越大越不验证——write/episode 1.6875→13.8125，test/episode 0.9375→0.75；
  L4 失败轨迹为 read + write×31 且**无一次 test**。全档失败均为 `budget:steps`，`parse_failures` 全档 0。
- **一处必须记住的更正**：二次项显著性**完全由结构性地板点 L0 驱动**（含 L0：chi2=67.17717677530908；
  剔除 L0：0.19053330087083964，p=0.662，系数符号翻转）→ **不得**写「内部最优点」，
  正确表述是「超过低档后**单调下降**」。因此**未**把 P6 的 P\*=8 写成跨论文互证。

**本轮新增的三条防线（都由这次真跑暴露的问题而来）**：

1. **可辨识性护栏从"单条"升为"两条"**：原判据只要求「内点 ≥2」，**过弱**——它对 CI 宽度≈1.0 的
   参数仍判 `identified: true`。已加「CI 宽度 ≤ 0.30」。在同批记录上重拟合，三轴全部转为 NOT IDENTIFIED。
2. **H4 数字门（非空洞）**：`scripts/check_h4_claims.py` 已接入 22 门验收配置。
   建设中该门**假通过过一次**（信任了产物里旧护栏留下的 `unidentified_axes: []`），
   被 `--selftest` 的注入反例抓出；改为从 CI 宽度**重新判定**。第二次容差过紧（0.913 vs 0.912812）又漏，
   改为按引用精度比较后通过。**教训：没有反证用例的门等于没有门。**
3. **派生量必须落盘**：McNemar、LR、动作频次这些"论文要引用的派生量"原先只存在于散记里，
   ledger 校验立刻 4 条 FAIL（声称的数找不到字段）。已固化为 `results/h4_derived_stats.json`
   （重跑字节一致），C34–C40 全部可回指。

**未做**：`main.tex` 的 H4 改稿——**等主会话确认口径**（见上：不得写"内部最优"）。14B 未跑（主会话指示）。
`g_search` 恒 UNMEASURED（本任务集无变化来源，不得用别的轴凑数）。

## 7.6 `main.tex` H4 改稿完成（口径经主会话复核后执行，2026-09-12）

主会话独立复现了我的 §2.3 更正（其算得含 L0 chi2=39.18 / 剔除后 1.079, p=0.2989，**同样符号翻转、同样不显著**），
确认口径为「单调下降 + 验证崩溃」，并**撤回**了先前的 P6 互证建议。据此完成改稿。

### 改动的句子（前 → 后）

| 位置 | 前 | 后 |
|---|---|---|
| 摘要 | "We make **four** contributions." | "We make **five** contributions." |
| 摘要 (iii) | "...measured costs with a source-anchored reasoning kernel, we compute..." | "...**and four declared agent-axis gains**, we compute..." |
| 摘要 | （无第五条） | 新增 **(v)**：真实模型 672 集**未确认**饱和增益假设——峰值 0.9375 后单调降到 0.7500（McNemar p=0.0039），三轴 CI 宽 1.00/1.00/0.58 不可辨识，主因是**验证崩溃**（最大预算下重写 31 次、零测试） |
| 引言贡献 | 4 条 | 新增第 5 条 "**A real-model test of the gain assumption**"，指向 §H4 |
| Honest scope | "with a rule-based agent policy" | 补明 §H4 **另用真实模型在 GPU 上**跑，是唯一"检验而非假设"增益的地方 |
| **新 §H4** | （无） | 整节：Table（5 档 n=48，成功率+write/ep+test/ep）、配对检验、**模型形式被拒**（单调 vs 下降，r²=0.291）、**三轴 withhold**、**机制**（31 次重写零测试）、以及 **"A correction we had to make to ourselves"**（地板点伪曲率） |
| Discussion 第三段 | "we **conjecture**... A model-backed agent would sit between the two. That comparison is a conjecture" | 改为**实测结论**：真实模型**不**复现饱和形状；增益前提在真实模型上**失效**；机制是"预算改变了行为"（从验证转向重写），并接上 wu2026 的"完成 ≠ 经济" |
| Discussion 末 | "**we did not measure them**" | 改为"**我们测了**，但没定住：区间过宽 + 单调形式表示不了"，并说明风险方向是**反转** |
| Declared limits 2 | 假设参数（无补充） | 补明 §H4 试图测量但**未定住**，且发现假设的单调形状在该任务集上**错误** |
| Declared limits 3 | 合成策略（仅 E3） | 补明 §H4 提供真实模型对照，且结果是**负的** |
| Declared limits 5 | "**No accelerator.** A concurrent job held the GPU throughout" | **更正为**：E1–E3 为 CPU；§H4 用了 1×RTX3090（共享锁）；并写明"早先草稿此条只适用 R1–R2" |
| Declared limits | （无） | 新增 3 条：**单模型单任务集**、**假设模型单调**、**一阶段伪影已排除且留证**（10/40 截断、13GB 不守锁共租、按空余显存分配） |
| Conclusion | "...saturating returns... gains remain assumptions" | 补：真实模型上假设**未存活**；给**两面**总结；"gains remain assumptions——**now with a measured counterexample attached**" |

### 附带更正（产物纠正了我）
pilot 的 `parse_failures` 我一直引用为 **30%**，下载产物实测为 **10/40 = 25%**。
已在 `H4_FINDINGS.md` 与 `WORKING_NOTES.md` 按产物更正（论文未引用该比例，故不影响稿件）。

### 交付前核对
- H4 门（非空洞）：对**真实稿件**验证——干净副本 **PASS**；把 `g_steps = 0.913` 注入真实 H4 句子 → **FAIL** 且指明"WITHHELD (CI95 width 1.0000 > 0.300)"。
- 稿内 17 个 H4 数字逐条对产物核对：**ALL VERIFIED**（曲线/配对 p/r²/动作频次/代表轨迹/CI 宽/672/wall/think 对照）。
- 摘要：**无** `g_x` 字面量、**无**任何依赖单调 `g_x` 的结论；E3 的 monotone 句保留（那是 E3 实测的正确陈述，现已与 (v) 并列对照）。
- 门：**22/22 PASS**；manifest **135 PASS/0 FAIL**；ledger **40 PASS/0 FAIL**；投稿包 7/7；泄漏 0。
- 页数：**13**（11 → 13，新增整节 + Table + 4 条 limits）。

## 7.7 对抗审稿 REVISE 的修复（2026-09-12）

P2 对抗审稿判 REVISE：1 Major（打包）+ 3 Minor。裁判独立重算 H4 全部数字一致、6 项威胁全 PASS
（无 inverted-U、`g_vision=0.041` 从不出现于正文、摘要 5 个数字全对、E3/H4 严格分离、
exact McNemar 无伪 ×2、parse 10/40=25% 非 30%）。**问题在打包与一处门 bug，不在科学。**

### Major M1：中心负结果在发布包内不可重算 —— 已修

**实测确认**：旧 zip（40 条目）**完全没有** H4 的 4 个结果 JSON 与 harness，只有
`analyze_h4_result.py`/`compare_h4_to_e2.py` 两个分析脚本（它们反而在包里，需要的输入不在）。
根因是我在"H4 未跑"时期加的一条 **`h4_` 前缀一刀切排除**；H4 跑完后它变成了有害规则，
而 `ANON_REPO.md` 还写着 "h4_real_llm_gx.py :: not yet run, no result"——**陈旧且错误**。
后果：摘要"every number is recomputable … by one canonical script"**对 H4 是假的**。

修法（源头修，不是补丁）：
1. **把 harness 改成 host-agnostic**：`H4_GPU_LOCK`/`H4_OUT_DIR` 走环境变量，`--model` 必填，
   文档示例用 `$MODEL_DIR`。现 `h4_real_llm_gx.py` 与 `h4_run_remote.sh` 的绝对路径数为 **0**。
2. **移除 `h4_` 一刀切**，改为按文件列明；只保留三个**如实**的 "Not shipped" 条目
   （superseded 草稿 harness / queue wrapper、CPU stub dry-run，各附理由）。
3. **新增主机路径脱敏**（仅出货副本）：`$MODEL_DIR`/`$H4_WORK`/`$WORKSPACE_PATH` 占位，
   测量值不变。
4. **新增打包后重导**：脱敏改了结果字节 → 包内 `h4_derived_stats.json` 的 `source_sha256`
   会与包内结果**对不上**（实测 mismatch）。故在脱敏后**在包内**重跑派生脚本，
   使包自洽；并断言校验通过。
5. **摘要/复现段改为如实**：E1–E3 由 `analysis.py`，H4 由 `h4_derived_stats.py` +
   `analyze_h4_result.py --refit`；并明说 "`analysis.py` does NOT cover H4"。
6. **加回归门**：`check_h4_claims.py --package` 断言 zip 内必须有 5 件 H4 证据且包自洽。

**结果**：zip 47 文件 / 49 条目 / 0.63 MB，含 **9 个 H4 条目**（4 结果 + 4 脚本 + wrapper），
绝对路径 0、内部泄漏 0。**从 zip 独立解包后重跑派生脚本 → 输出与包内文件逐字节相同**
（`identical: True`），即中心负结果现在**在发布包内真的可重算**。

### Minor (a)：门 bug —— `break` 缩进错误，门实际只拦 g_steps

`check_h4_claims.py` 的 `break` 位于 `for` 内、`if` **外**，因此遍历第一个 withholding 条目后
无条件退出。实测复现：注入 `g_steps=0.913` → caught；`g_tools=0.496`、`g_vision=0.041` →
**caught=False**（静默漏过）。修法：`break` 移入 `if` 内；并**把 selftest 扩成三轴逐轴注入**，
任一条未被拦即 FAIL。修复后三轴均被拦；且在真实稿件上注入 `g_tools`+`g_vision` →
**2 violations**（此前会 0）。

### Minor (b)：672 的分解写错

正文/caption 原写 "672 = 8×5×2×3"，实为 **240（iso 复现）+ 432（单轴 sweep）**；
`H4_FINDINGS.md` 原写 "25 臂 × 8 × 3 = 600" 也错，实为 **28 臂**。已按产物更正三处
（caption 写明 $8\times5\times2\times3$ 的 240 与 120/168/144 的 432；正文补同义说明）。

### Minor (c)：selftest 三轴化 —— 已随 (a) 完成。

## 8. 交付物（本轮新增/修改）

| 文件 | 动作 | 说明 |
|---|---|---|
| `experiments/h4_real_llm_gx.py` | 新增 | H4 harness（CPU 验证通过，未起 GPU） |
| `experiments/h4_run_remote.sh` | 新增 | 真跑包装器（锁 + 显存地板 + 优先级） |
| `results/h4_dryrun_stub.json` | 新增 | CPU dry-run 产物（896 episode，`dry_run:true`） |
| `reports/literature_freshness.md` | 新增 | O05 新鲜度门报告 |
| `paper/main.bib` | 修改 | 移除稿件内队列路径（**G9/G10 泄漏，源头修**） |
| `paper/main.pdf` / `main.bbl` | 重编译 | 11 页，0 overfull，`SOURCE_DATE_EPOCH` 固定 |
| `experiments/extract_v41_effort_evidence.py` | 修改 | 证据包不再写解析来源路径；`source_path` 固定为包内路径 |
| `evidence/v41flash_effort_control.json` | 重建 | 40 引文 / 19 数值事实不变；路径字段去队列化 |
| `experiments/make_submission_bundle.py` | 修改 | 新增 redaction / 泄漏门 / 确定性 zip / 未出货清单 |
| `submission/repo/` + `..._anon.zip` | 重建 | 36 文件 / 38 条目 / 0.51 MB，0 泄漏 |
| `evidence_manifest.json` | 重建 | 123 条 |
| `STATE_SNAPSHOT.md`、`WORKING_NOTES.md` | 更新 | R2 状态、U04、新防线 |

**未改**：`paper/main.tex`（§E3 限定已在盘上）、其它论文目录、`papers/QUEUE.md`、
E1/E1b/E2/E3 结果与 `stats.json`。

## 追加：R1 修复轮（登记 2026-09-24T18:19:29Z；改动实际发生在 17:53–18:06Z）

改动全部由 `apply_candidate.py --go APPLY` 执行（自带逐次备份），备份命名见该行。

| 编号 | 文件 | 改动 | 触发/理由 | 状态 |
|---|---|---|---|---|
| CHG15 | `paper/main.tex` | 摘要整段替换为 CANDIDATE-A（paste 2,809 → 1,919 字符），H4 的 McNemar 主张改为单元层口径 | R1 Critical AE-1 / A1（两个角色独立命中：48 record-pair 实为 16 单元 × 3 份逐位相同重复） | done |
| CHG16 | `paper/main.tex:697-699,702` | 正文 §4.4 三条 + 一处强度句换成「有条件式」（B3 路由）：同时报 record 层 p=0.0039 与单元层 3/0、p=0.25 | 同上；措辞选择由 h4p_route_matrix 的 4 条 measured 判据定 | done |
| CHG17 | `paper/main.tex（新增 \section）` | Ethics and Broader Impact 插入 215 词 | TMLR 必要项 ethics_discussion（audit_paper_structure REQUIRED-FAIL） | done |

## 追加：AE-2（Table 3 伪重复 + 拷贝上的 bootstrap）——登记 2026-09-24T18:50:51Z

| 编号 | 文件 | 改动 | 触发/理由 | 状态 |
|---|---|---|---|---|
| CHG18 | `paper/main.tex` 59-60, 621-624, 630, 632-636 | Table 3 的 $n$ 列改印 "48 (16)"、五层区间换成对 16 个独立单元的 Clopper--Pearson（[0.000,0.206]/[0.246,0.754]/[0.794,1.000]×3），说明句由"4000 次 bootstrap"改为精确二项区间；摘要 (iv) 的 "$48$ episodes" 同步改 "$16$ independent units" （paste 反而更短） | R1 Critical AE-2 + Major A5：`policy` 自述 deterministic ⇒ 3 份重复不携带信息；饱和层 1.000 的 bootstrap 区间塌成 [1.000,1.000]，在最不确定的地方报出确定性 | done |
| CHG19 | `evidence/E3_UNIT_LEVEL.json` / `.txt`（新） | 由 `recompute_e3_units.py` 从 `results/e3_agent_loop.json` 现场派生：80 单元、跨重复变化 0/80、每层单元级 CP 区间 + 记录级对照 | 表里的数必须住在可复算的载体里；断言"跨重复有变化"若为真则拒绝折叠（反向自我保护） | done |
| CHG20 | `arxiv_d0788aa9/recompute_e3_units.py` | 手写不完全 Beta 换成 `scipy.stats.binomtest`；并修我自己夹具里手算错的期望（8/16 不是 0.250/0.750 而是 0.2465/0.7535） | 夹具当场抓出实现返回 [0.474,0.526]——那是绕着点估计的带，不是 95% 覆盖的区间 | done |
| CHG21 | `arxiv_d0788aa9/draft_ae2_table3.py` | 兜底分支丢了 `\caption{` 的收尾花括号 ⇒ Emergency stop；补"括号平衡 + 每行 $ 成对"两条断言，并从备份整体回滚后重打 | 第一次 apply 后编译 rc=12、main.log 3 条错误；已回滚重做，现编译 rc=0、14 页 | done |

## 追加：匿名包检测器的瞎眼（登记 2026-09-25T04:13:45Z）

| 编号 | 文件 | 改动 | 触发/理由 | 状态 |
|---|---|---|---|---|
| CHG22 | `experiments/make_submission_bundle.py:64` | `ABS_PATH_RE` 的 Windows 分支由 `[A-Z]:\\\\`（raw 串里＝要求**两个**反斜杠）改成 `[A-Z]:[\\]{1,2}` 并加 `[A-Z]:/` 一支 | R1 R-AE-03：包里明明写着 `F:\deepseek\papers\…`，而 `ANON_REPO.md` 报 "absolute-path hits: 0"。验证用文件自己那行字面量重编译：单/双反斜杠、`/home/…`、`/root/autodl-tmp`、`C:/Users/…` 五种全中；负控（比例 `x:y`、`section 3:10`、单字母 `q:`）保持安静。**注意这只修了检测器**：该正则只统计不改写，泄漏本身要另做（加进 `DROP_GLOBS` 或写替换），而 arXiv 目标包经 `package_leak_gate.py` 实测 11/11 干净 | done |

## 追加：伦理小节标题对 venue 闸不可见（登记 2026-09-25T04:19:17Z）

| 编号 | 文件 | 改动 | 触发/理由 | 状态 |
|---|---|---|---|---|
| CHG23 | `paper/main.tex` | `\section{Ethical Considerations}` 这个标题**venue 自己的闸看不见**：check_tmlr_compliance 的 tmlr 头部模式是 `Broader Impact|Ethics`，而 "Ethical" 不含 "Ethics"；我的 audit 用的是 `ethic\w*` 所以判绿 ⇒ 两把尺对同一篇给相反读数。改成 TMLR 自己用的措辞 `\section{Ethics and Broader Impact}`（备份在 arxiv_d0788aa9/backups/，重跑两把尺都绿） | R1 后复测：`check_tmlr_compliance --venue tmlr` 报 `[G7] WARN :: no Broader Impact / Ethics section found`，而 `audit_paper_structure` 报 `REQUIRED-FAIL=-` —— 分歧原因是标题词形 | done |

## 追加：Table 3 的出处闭进规范流水线（R2 方法学第 5 条，登记 2026-09-25T05:45:50Z）

| 编号 | 文件 | 改动 | 触发/理由 | 状态 |
|---|---|---|---|---|
| CHG24 | `analysis.py:34-70, 122-150, 155-165` | 新增 `exact_ci()`（Clopper--Pearson，缺 scipy 就 **拒绝运行**、不回落到 bootstrap）与 `unit_aggregate()`（按 (task,schedule) 折叠；**若有单元跨重复不一致就返回 NOT_JUDGED 并拒绝折叠**）；curve 与 by_budget_schedule 都加 `n_units / success_units / success_rate_ci95_units / units_varying_across_repeats`；记录级 boot 保留在原字段做对照 | R2：正文摘要承诺"每个数都能由规范 `analysis.py` 重算"，而我上轮换的 CP 列只活在 `evidence/E3_UNIT_LEVEL.json` 里——`stats.json` 仍只发记录级 boot（含零宽 [1.0,1.0]）。承诺与来源打架是我的改动造成的，必须把区间做进流水线而不是只做个旁证脚本 | done |
| CHG25 | 同上，两道**非恒真**自检 | ① 单元区间必须不比记录级窄（否则红）；② 折叠只在**结构上成立**：`n_units == n_tasks×2 == 16` 且 `records == repeats × n_units`，不满足即红并置 `recompute_checks_passed=False`。跑出来 rc=0、0 条 RED、checks True；与独立仪器 `E3_UNIT_LEVEL.json` 五层逐值对表 **delta≤1.1e-05**、n_units 16/16 全对 | ①单独用能被"折叠没起作用"骗过（同 n 时区间仍可能因方法不同而更宽），所以补②把判据钉在设计常数上 | done |
| CHG26 | `paper/main.tex` Table 3 说明句 + `CLAIM_LEDGER.md` C52 | 表注加"3 dp、**向外**取整"（`analysis.py` 印 0.2465/0.7535，表里是 [0.246,0.754]——向内取整会印出比算出来更窄的区间）；C52 指针补 `results/stats.json -> E3_loop.curve / n_units / success_rate_ci95_units / units_varying_across_repeats`，四个字段逐个解析验过存在 | 让"重算"这句重新为真；编译 rc=0、0 错误；账 52 行无重号 | done |

## 追加：R2 Critical 修复轮（登记 2026-09-25T06:14:27Z；验证：compile rc=0、0 错误；摘要 paste 1,916 OK）

| 编号 | 文件 | 改动 | 触发/理由 | 状态 |
|---|---|---|---|---|
| CHG27 | `paper/main.tex` 摘要 | "$16$ independent units per level" → "$16$ units per level"（省 12 字符），paste 从 **1,928 越线** 回到 **1,916 OK**；"independent" 仍由表注 "$16$ independent (task, schedule) units" 承载 | **我上一轮 AE-2 改动造成的回归**：apply 时 new_paste=1,919，之后换词多加 9 字符顶过 arXiv 的 1,920 硬限。只有把摘要长度做成每轮必测的闸，这种回归才不会靠运气发现 | done |
| CHG28 | `analysis.py` + Table 3（同轮，见 §14/§16） | 规范流水线现产单元级 Clopper–Pearson；两道非恒真自检（区间不得变窄 + 折叠须在结构上成立）；与独立仪器 `evidence/E3_UNIT_LEVEL.json` 五层逐值 delta ≤ 1.1e-05 | R2 方法学第 5 条：正文承诺"每个数由 `analysis.py` 重算"，而我上轮只写了旁证脚本 | done |
| CHG29 | `paper/main.tex` 两处 + `CLAIM_LEDGER.md` C53 | `30.37` → **`30.36`**（L457 正文句与 Table~\ref{tab:latency} 的 `mean` 列）；C53 指针/数值列补 `aggregates.T3_python_exec.mean_ms = 30.36466666666667`，使 30.36 有承载物 | 正文该数**无任何产物支撑**（同对象 mean=30.36466…→两位小数 30.36；p50=31.41、min/max 均非 30.37），是取整错；改前 md5 `37c746e5…`、改后 `1528a064…`，重编译 rc=0、16 页、0 错误；备份在 `~/jev-local/arxiv_d0788aa9/backups/agent_effort_main.tex.bak_fix3037_20260925T100508Z` | done |
