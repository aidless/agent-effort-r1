# Revision Round R1 报告 — 重挂到真来源 + 首批真实实验

日期：2026-09-11 ｜ 论文：From Controllable Reasoning Effort to Controllable Agent Effort
上一轮：R0（立项）｜状态：已完成 ｜本轮成本：0（CPU-only，无 GPU、无 API 预算；远程宿主 96 vCPU / 754 GB）

## 1. 本轮范围

- 目标：(A) 把 P2 从错误来源重挂到唯一权威来源并写出可投稿骨架；
  (B) 产出第一批真实实验证据（E1 工具延迟画像、E2 联合分配、E3 端到端）。
- 主要改动方向：来源身份 → 证据包 → 正文重写 → 三个真实实验 → 台账/快照/门禁同步。
- 阻塞项：无（GPU 被并发作业占用，按硬约定不使用 GPU；全部实验 CPU 可跑）。

## 2. 变更日志

| 变更 ID | 文件 | 改了什么 | 为什么改 | 证据影响 | 状态 |
|---|---|---|---|---|---|
| CHG01 | `evidence/v41flash_effort_control.json`（新，29.8 KB） | 从 `evidence/V41FLASH_TechReport.txt`（与 `papers/_shared/evidence/` 下原件同 SHA-256） 抽取 40 条逐字引文（带 line_start/line_end）+ 19 条数值事实 + 术语计数 + 行号陷阱校验 | 旧证据入口是 3 篇 arXiv 相关工作，方向前提**未挂真来源** | 抽取脚本 `experiments/extract_v41_effort_evidence.py` 对每个必需子串 fail-fast；`sed -n` 逐条字节比对 40/40 一致 | done |
| CHG02 | `evidence/related_work/`（新目录） | 三篇 arXiv JSON 移出 `evidence/` 根 | 它们是相关工作，不是前提来源；防止再次被误引用 | 口径修正，无数字影响 | done |
| CHG03 | `paper/main.tex` | 从模板原文重写为完整 IMRaD：Introduction / Related Work / Method / Experiments(pre-registered) / Results / Discussion / Conclusion + 2 附录；含 GAP、3 个可证伪假设、逐条行号溯源、5 项 declared limits | 原文件是 TMLR 样例模板，无任何论文内容 | 所有数字来自 `results/stats.json` | done |
| CHG04 | `paper/main.bib` | 换成 8 条**已核验**的真实文献（arXiv 检索确认标题/作者）+ 源报告 | 避免幻觉引用（MLR-Bench E 类） | 每条带 URL；无编造条目 | done |
| CHG05 | `experiments/e1_tool_latency.py`（新） | 12 个原语 ×[40,200] 次实测，含"语义失败"判定（退出码正确但答案错=失败）与不可达网络兜底 | 需要"步数×工具调用×截图"成本模型的一手输入，禁止编造延迟常数 | 原始逐次样本落盘，可重算 | done |
| CHG06 | `experiments/e1b_agent_primitives.py`（新） | 补 6 个 agent 专有原语（图像编解码 / 截屏尝试 / 小测试运行 / loopback 检索 / 打补丁 / JSON CLI 调用）；test runner 自动回退 unittest | E1 的通用原语不足以给视觉轴与检索轴定价 | 首跑因远程无 pytest 导致 P3 全失败 → 加 unittest 回退并重跑 | done |
| CHG07 | `experiments/e2_effort_allocation.py`（新） | 8,820 个候选分配的前沿搜索 + 4 类基线 + 解耦基线 + 200 次 bootstrap + 30 点敏感性网格 | 需要 H1/H2/H3 的可证伪判据 | 见 R2 的模型修正 | done |
| CHG08 | `experiments/e3_agent_loop.py`（新） | 8 个自动判分任务（隐藏单测，agent 不可见）× 5 预算级 × 2 调度 × 3 重复 = 240 episode | H1/H3 的端到端回路验证 | 首跑判分器 `loadTestsFromName` 无法加载裸 test 函数（0 testsRun）→ 改 `importlib+loadTestsFromModule` 并把隐藏测试改成 unittest.TestCase，重跑 | done |
| CHG09 | `analysis.py`（新） | 唯一复算脚本：从 raw samples 重算每个聚合并 **assert** 与落盘一致，产出 `results/stats.json` | FM-16/17：统计量必须由唯一脚本从原始数据重算 | `recompute_checks_passed: true` | done |
| CHG10 | `CLAIM_LEDGER.md` | 重建：33 条（14 条 source 引文 + 20 条 measured）+ 6 条假设参数 + 3 条 inconclusive + 强断言登记 | 旧台账 4 条且基于错来源 | 每条含文件+字段+复核方法 | done |
| CHG11 | `HYPOTHESES.md` | H1/H2/H3 填入实测结果与证伪条件判定；新增 H4（真实 LLM 下实测 g_x，TODO）；方法表改用源报告为首行 | 假设必须冻结后再判，结果需可对照 | 逐条指向 `results/e2_allocation.json` 字段 | done |
| CHG12 | `STATE_SNAPSHOT.md` / `ROUND_R0.md` | 初始化状态机并回填历史收据 | 冷接管需要 | done |
| CHG13 | `protocol.md` / `gates_config.json` / `evidence_manifest.json` | 填入真实实验设计、种子口径、环境、生成脚本；门禁改指真实产物 | 旧门禁指向不存在的 `generate_data.py` | 见 §3.5 | done |
| CHG14 | `evidence/protocol.md` | 记录：数据非模拟（E1/E1b/E3 为真实执行）、E2 为模型化优化（已披露假设）、无人类受试者、GPU 未使用 | FM-21 数据披露 | done |

## 3. 机器检查结果

### 3.1 唯一脚本复算（替代/等价于数字一致性扫描）
```
python3 analysis.py .
```
结果：**PASS** — `recompute_checks_passed: true`；对 E1/E1b 的 n、failure_rate、
mean_ok、p50_ok、p95_ok 以及 E3 的每层成功率逐项 assert 一致。

### 3.2 Claim ledger 对账
```
python3 scripts/verify_claim_ledger.py .
```
结果：**PASS — 33 PASS / 0 FAIL / 0 WARN**。反例留档：初版账本用「同上」「→」等简写导致 33/33 FAIL，
逐条改为 `path -> field.segment / field.segment` 形式并可解析后全部通过（见 FIX-03）。

### 3.3 写作风格 / 数字一致性 / 统计一致性 / 幻觉 / 污染传播
```
python3 scripts/scan_number_consistency.py . --out reports/numbers.md
python3 scripts/scan_stats_consistency.py . --out reports/stats.md --fail-on-error
python3 scripts/check_writing_style.py . --out reports/style.md
python3 scripts/scan_hallucination.py . --out reports/hallucination.md --fail-on-error
python3 scripts/verify_taint.py . --out reports/taint.md --fail-on-error
```
结果：全部 exit 0。写作风格 0 findings；统计一致性 0 错误；幻觉扫描 0 引用错误 / 0 命名缺失文件；
污染传播 0 tainted / 0 missing。数字一致性扫描残留 3 条 **数值等价** 误报（`1.00` 与 `1.000`、
`+0.000` 与 `0.000`，|差|=0），已在 §5 FIX-04 记录为何不再改稿。

### 3.4 TMLR 合规扫描 + 编译门
```
python3 scripts/check_tmlr_compliance.py . --names "" --exclude-dir evidence --out reports/tmlr.md
python3 scripts/compile_gate.py . --out reports/compile.md
```
结果：TMLR 5 findings / **0 failures**（G1 PASS、G6 PASS、G7 PASS、G9×2 PASS）。
编译门 **PASS（错误类 0、警告类 0）**：11 页 PDF，0 overfull hbox，0 未定义引用/交叉引用，
0 孤儿标签，0 未引用文献条目。`SOURCE_DATE_EPOCH=1767225600`。

> 说明：TMLR 扫描以 `--exclude-dir evidence` 运行——`evidence/` 是**来源材料与原始产出**，
> 不是稿件内容（其中含大量一手报告 URL 与数字，属来源而非正文引用）。

### 3.5 验收门（全量）
```
python3 scripts/run_acceptance_gates.py gates_config.json --record gates_history.jsonl
```
结果：**TOTAL 20/20 PASS**（exit 0），记录写入 `gates_history.jsonl`。

### 3.6 TMLR 合规状态表（G1-G11）

| 门 | 检查项 | 状态 | 备注 |
|---|---|---|---|
| G1 | tmlr 模板 | ✅ | `\usepackage{tmlr}`（无选项，匿名） |
| G2 | US Letter + pdflatex | ✅ | 本机 pdflatex + SOURCE_DATE_EPOCH 固定 |
| G3 | 全文匿名 | ✅ | 无作者块（PDF 渲染为 Anonymous authors）；机构名以 "the V4.1-Flash technical report" 形式引用 |
| G4 | 匿名仓库 | ⏳ | 代码随论文提交，仓库需在投稿时匿名化 |
| G5 | 补充材料 ≤100MB | ✅ | 证据包 < 1 MB |
| G6 | 引用格式 tmlr.bst | ✅ | `\bibliographystyle{tmlr}`，8 条已核验文献 |
| G7 | Broader Impact | ✅ | 含对"效率提升双刃"的显式讨论与 8 例反转披露 |
| G8 | OpenReview 表单 | ⏳ | `evidence/G8_form_checklist.md` 待投稿时逐项勾选 |
| G9 | 交叉论文重叠 | ⏳ | P1–P7 共用同一来源，投稿前必须做逐句重叠比对 |
| G10 | 双盲隔离 | ✅ | 正文不出现本地路径/机构内部命名 |
| G11 | 验收门 + 哈希对账 | ✅ | 20/20 PASS；`evidence_manifest.json` 78 条已 `--verify` 通过 |

## 4. E1b 环境失败与修复（FM 留档）

| 现象 | 根因 | 处理 | 结果 |
|---|---|---|---|
| P3 小测试运行 30/30 失败（`AssertionError:` 空消息） | 远程主机**没有 pytest**（`ModuleNotFoundError`） | 加 unittest 自动回退并把选择写进输出（`test_runner` 字段） | 重跑 30/30 成功，58.25 ms |
| P2 真实截屏 30/30 失败 | 无头容器，无 `mss` 且 `DISPLAY` 未设置 | **不**用编造常数替代；如实记录失败率 1.00，视觉单位改用 PNG 编解码代理并写入正文 | 已在 C18 登记 |
| T9 不可达主机 | RFC 2606 保留域名（`.invalid`/`.test`），按设计必然失败 | 作为一等证据保留：失败率 1.00 且失败前耗时 961.82 ms | 已在 C17 登记 |

## 5. 本轮内自我发现并修正的问题（5 项）

| 修正 ID | 问题 | 症状 | 根因 | 修正 | 影响 |
|---|---|---|---|---|---|
| FIX-01 | E2 首版成功模型用**乘性（conjunctive）**轴合成 | 成功率被压到 0.05 量级，前沿无分辨力，`success_gain` 全为 0 | 把"多轴都成功"当必要条件，而真实 agent 的多轴是**可替代路线** | 改为失败空间 union：`p = 1 − (1 − acc·agent)(1 − p0)`，`agent = 1 − Π(1 − g_x·sat)` | 前沿恢复分辨力（0.362 … 0.691） |
| FIX-02 | 首版把 all-max 当作可被打败的基线 | 报出 441× 成本优势 | all-max 已在模型内饱和，匹配成功处必然平局 | 改为双口径诚实陈述：匹配成功处**平局**（0.6906@145,600），优势只在"达 90% 可得成功的代价"（8.67×）；并披露 30 点网格中 8 例反转 | 删除了一条不成立的强断言（见 ledger §E） |
| FIX-03 | claim ledger 用「同上」/「→」/中文分号简写 | verify_claim_ledger 33/33 FAIL（`missing file 同上`） | 解析器按 `;` 切分后每段必须是 `path -> field`，`→`/`同上` 不可解析 | 逐条改为可解析引用（引文按 `quotes[i]` 索引、数组用 `[k]`、多字段用 ` / `），值列改由脚本从证据 JSON 直出 | 33 PASS / 0 FAIL |
| FIX-04 | 小数位不一致触发数字一致性误报 | 报告 3 条 table-vs-prose mismatch | 同一量在表内写作 `1.00`/`+0.00`、正文写作 `1.000`/`0.000`，扫描按字面量比较 | 批量统一到 3 位小数；剩余 3 条为**数值等价**（|差|=0，`1.00` 是失败率 100% 的合法写法），记录为已知误报，不再为凑扫描器改稿 | 误报 3 条，已定性 |
| FIX-05 | 宏名冲突导致编译门 4×"Double subscript" | `\usepackage{tmlr}` 下 `\bref`…`\bvi` 展开异常 | 宏名与模板/字体宏命名空间冲突，且 `\reff_{\min}` 造成双下标 | 重命名为 `\eff/\reff/\stepeff/\tooleff/\searcheff/\viseff`；带下标的量改用纯 `b`/`b_{\min}`；表头宏补 `$...$` | 编译门 PASS（0 错误 0 警告） |

## 6. 开放事项 / 阻塞项

| ID | 事项 | 阻塞类型 | 需要的输入 | 建议 |
|---|---|---|---|---|
| O01 | 源模型本体上五轴路由的收益 | 不可获得 | 源模型 checkpoint 权重 | 正文只作 quotation（U01 inconclusive） |
| O02 | 真实 LLM 策略下的 g_x（H4） | 资源 | 空闲 GPU + 本机已有 Qwen3-8B/14B-AWQ | 待 P1 GPU 实验结束即跑；在此之前正文标 conjecture |
| O03 | GPU 独占 | 协调 | —— | 本工作全程 CPU-only，未与 P1 争用（观测 GPU 38.6 GB 已用 / 100% 利用率） |
| O04 | 页数 11（含参考文献与附录） | 交付口径 | 另 6 篇来源一致为 6–11 页 | 不为凑页注水；只在有真实结果时增删 |
| O05 | 文献新鲜度门未跑 | Phase 5 阻塞 | 需 `novelty_claims.txt`（已落盘 3 条）+ 重跑 arXiv 增量扫描 | 投稿前必跑 `check_literature_freshness.py --max-age-days 30` |

## 7. 交付物清单

- [x] manuscript（`paper/main.tex` + 8 条 bib + 编译产物 `main.pdf` 11 页）
- [x] evidence package（`evidence/v41flash_effort_control.json` 40 引文/19 数值 + `protocol.md`）
- [x] raw results（`results/e1_tool_latency.json`、`e1b_agent_primitives.json`、`e2_allocation.json`、`e3_agent_loop.json`）
- [x] 唯一复算脚本（`analysis.py` → `results/stats.json`）
- [x] `evidence_manifest.json`（hash 对账）
- [x] `CLAIM_LEDGER.md`（已对账）
- [x] 本轮报告（本文件）+ `ROUND_R0.md`（历史收据）
- [x] 远程运行日志留档（`results/run_logs/*.log`）
