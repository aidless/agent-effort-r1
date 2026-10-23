# STATE_SNAPSHOT.md — 科研状态快照（E104）

论文：From Controllable Reasoning Effort to Controllable Agent Effort
轮次：R2（限定补齐 + 新鲜度门 + G4 匿名仓去泄漏 + H4 harness 就绪）｜更新：2026-09-11｜编译：11 页 PDF，0 overfull，0 未定义引用

## 状态字段

| 字段 | 内容 |
|---|---|
| `state_of_the_art` | 源报告（V4.1-Flash 技术报告，`evidence/V41FLASH_TechReport.txt`（与 `papers/_shared/evidence/` 下原件同 SHA-256），SHA-256 `ac24848a…abf3`）：单一标量努力 b∈{1..100}，指数惩罚 k(b)=k0·exp(−(b−b_min)/τ)；25→100 令八推理基准 67.1→76.3%、DeepSWE v1.1 66.0→74.2%、TB2.1 82.4→90.6%，token 约 2.5×；60–80 前置恢复大部分精度。相关基线：CoBa 49.1% token 节省@85.13%；Gambit +6.7pt@−68.5% token；EcoAgent-Bench tool-API 微严格成功率 3.9–24.0%、经济一致性 ≤7.3%。 |
| `hypotheses` | H1 统一预算优于分立预算 **[PROVEN]**（1.32× 成本优势 @40% 成功）；H2 跨轴调剂优于均匀加码 **[PROVEN-部分]**（3.44×/4.52×/2.05× vs 三种非饱和基线；与 all-max 为平局，仅尾部 8.67×）；H3 最优构成随预算旋转 **[PROVEN]**；H4 真实 LLM 下实测 g_x **[TESTING-仅工具链]**（harness 已写、CPU dry-run 896 episode 通过、拟合器回收自检 `all_recovered:true`；**真跑仍受 GPU 排队阻塞** free 23852<25600。正文维持 conjecture，不得升级） |
| `key_knowledge` | ① 同一逻辑动作出网 vs 本机差 2194×（2233.75 ms vs 1.02 ms），出网延迟的分布极重尾（p95 6,693 ms）；② 无头主机无法真实截屏（30/30 失败），视觉轴必须以编解码等可测原语代理并如实披露；③ 失败的网络调用在失败前仍要付 961.82 ms，必须计入预算；④ 乘性（conjunctive）轴模型会让前沿塌缩，必须用可替代（union）语义；⑤ 源报告附录 C 自陈其推导只是局部近似（lines 3779–3788），不得当作精确曲线引用；⑥ **匿名包只审计绝对路径远远不够**：`papers/_shared/` 与兄弟投稿目录名同属 G9/G10 泄漏，且曾写在 `main.bib` 里（会渲染进 PDF）；⑦ **结构性不可行格 ≠ 增益**：`max_tool_calls=0` 无 test 调用即无判分，其恒 0 必须移出拟合并单列，否则阈值效应被读成轴饱和；⑧ 逐 episode 种子若由 `len(task_id)` 派生，长度碰撞（17/18 字符）会把独立抽样压成 2 个 |
| `reflection` | ① 第一版 success 模型用乘性 AND，成功率被压到 0.05 量级、前沿无分辨力——**建模错误而非数据问题**，已改为失败空间 union；② E2 的"all-max 被打败"直觉在饱和后不成立，初版脚本因此报出 441× 的假优势，属于典型 FM-15（数字自洽但语义荒谬），已改为匹配成功 + 8.67× 尾部代价 + 平局声明；③ 远程 `python3 -m pytest` 不存在导致 E1b 首跑 P3 全失败，改为 unittest 自动回退并重跑——环境失败不是科学负结果，但必须留档；④ **R2 同类再现三次**：H4 harness 的种子碰撞、stub 预算不感知、不可行格进拟合，三者都造出过'看起来像科学结论'的假数字，全部在 CPU dry-run 的回收自检阶段被抓住；⑤ R2 一度把 extractor 改成只看包内路径，而包内是 867 B 指针 stub，直接打挂两条门（18/20）——**门没有被绕过，改的是源头** |
| `experiment_history` | E1 延迟画像（12 工具，40–200 次/项）→ `results/e1_tool_latency.json`（sha256 e41aaf87…）；E1b agent 原语（6 项）→ `results/e1b_agent_primitives.json`（da146146…）；E2 联合分配（8,820 分配 + 200 bootstrap + 30 点网格）→ `results/e2_allocation.json`（9fabfd79…）；E3 端到端 240 episode → `results/e3_agent_loop.json`（2fb188ed…）；唯一复算 → `results/stats.json`（9fc51066…，`analysis.py` 全部 assert 通过）；**R2：H4 CPU dry-run 896 episode → `results/h4_dryrun_stub.json`（`dry_run:true`、`is_real_llm:false`、`all_recovered:true`，非任何模型的测量）** |
| `machine_checks` | 20/20 验收门 PASS（`gates_history.jsonl`）；claim ledger 33 PASS/0 FAIL；taint 0/0；hallucination 0 引用错误/0 命名缺失；stats scan 0 错误；writing style 0 findings；TMLR G1-G11 0 failures；compile gate 0 错误 0 警告；**manifest 123 PASS/0 FAIL；投稿包 7/7 PASS；O05 新鲜度门 exit 0（Age_days 0, Stale 0, Claims 3）** |
| `recent_actions` | 重建 `evidence/v41flash_effort_control.json`（40 条逐字引文 + 19 数值事实，行号 LF 约定）；三篇 arXiv JSON 移入 `evidence/related_work/`；重写 `paper/main.tex`（IMRaD 全文 + GAP + 3 个可证伪假设 + 来源对齐 + 5 项 declared limits）；重建 `CLAIM_LEDGER.md`；更新 `HYPOTHESES.md`、`ROUND_R1.md`、`gates_config.json` |
| `recent_actions_R2` | 核验 §E3 限定（**已在盘上，未改写**）；跑并落盘 O05 新鲜度门；**发现并修复匿名包的真实 G9/G10 泄漏**（`main.bib` 内队列路径、证据包 `../_shared/` 与兄弟目录名、extractor 回退路径、4 份过程文档）→ 源头修 + 出货前显式整块替换 + 独立 fail-loud 泄漏门，绝对路径 14→0、内部泄漏 13→0；重建确定性 zip（39 条目 0.51 MB）；写 H4 harness（**import 复用** E3 任务集/预算网格/判分）+ 远程锁包装器，CPU dry-run 896 episode 通过并建立**增益回收自检**（g_steps/g_tools/g_vision 三者 CI 覆盖声明值）；修掉 3 个 harness 缺陷；验证 GPU 预检（exit 3）、锁三态、包装器全部 ABORT 正确且**不绕锁** |
| `open_questions` | U01 源模型本体的五轴路由收益（无法运行其 checkpoint，正文只作 quotation）；U02 真实 LLM 策略下的 g_x（H4 未跑）；U03 延迟绝对值的跨主机可移植性（只把比值当可移植量）；U04 `g_search` 在本任务集上**无变化来源**——本轮明确不拟合，保持未测而非用 0 或猜测填充 |

## 假设生命周期规则（沿用）

- `[未跑]`：已登记未实验 → 正文不得提及（或只能作 future work）；
- `[TESTING]`：实验进行中/未复核 → 正文 hedge；
- `[PROVEN]`：证据文件 + 独立重算通过 → 可强断言，且 claim ledger 对应条目必须 verified/measured；
- 任何状态变更必须在 `experiment_history` 记录触发证据（文件路径）。
- **R2 增补**：工具链就绪（harness 可运行、dry-run 通过）**不等于** `[PROVEN]`；
  H4 在真跑且复核前不得从 `conjecture` 升级，dry-run 产物不得进论文、不得进匿名包。

## 交付前对账（R2）

| 检查 | 结果 |
|---|---|
| 快照 `[PROVEN]` ↔ ledger `measured` ↔ 正文强断言 | H1/H3 一致；H2 维持"部分成立"；H4 维持 conjecture（工具链就绪 ≠ 已验证） |
| `analysis.py` 重算 vs 落盘聚合 | 全部 assert 通过（`recompute_checks_passed: true`） |
| 正文数字 ↔ `results/stats.json` | 100% 覆盖（Tables 1–3 的每个数字均在 stats.json 有字段） |
| inconclusive 措辞 | U01/U02 在正文分别为 “quotation, never a measurement” 与 “conjecture” |
| 页数 | 11 页（含参考文献与两个附录），371,244 bytes，0 overfull；无注水：3 张表全部由实测/重算产出 |
| 验收门 | `run_acceptance_gates.py gates_config.json` → TOTAL 20/20 PASS（exit 0）；manifest `--verify` 123 PASS/0 FAIL；投稿包 7/7 PASS |
| 匿名包 ↔ G9/G10 | 绝对路径 0、内部队列结构/兄弟投稿 0，泄漏门 exit 0（fail-loud，替换失配即 exit 1，本轮已实证） |
| 未跑的格子 | H4 真跑无结果；dry-run 产物隔离命名并在文件内标注 `dry_run:true`，**不进正文、不进匿名包** |
| 已知误报 | 数字一致性扫描残留 3 条数值等价误报（`1.00` vs `1.000`，|差|=0）；TMLR 扫描以 `--exclude-dir evidence` 运行（证据目录是来源材料而非稿件） |
