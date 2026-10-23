# E3 / H4 闭环协议独立审查 R1

日期：2026-10-13。审查根目录：`/home/liuzewen/arxiv-publication/papers/agent-effort-r1`。只读源码、protocol 和既存 JSON；未运行模型、隐藏测试、统计分析或重新计算成功率，未改正文。文内行号指本轮读取的源码字节。

## 结论与证据绑定边界

当前 H4 源码确实实现“模型提出动作→真实文件读写/子进程测试→反馈→下一轮”的闭环。但测试成功事件、预算会计、提示上下文和 E3/H4 对照的含义比当前论文的简写窄，必须显式披露。

**重大溯源限制：** 两条 persist raw 的 `script_sha256`（两 JSON 第 97 行）均是 `3326b513fa891cbd99e8c1ffcd986bd27d9dac73fd75dc7a3a31c0993db3f9e8`。当前 `experiments/h4_real_llm_gx.py` 与 `anc/experiments/h4_real_llm_gx.py` 的 hash 都是 `7e2d56e7195074ab7c856d18054f59bf8e8557e1e89f90d39be879667adec157`。

本轮仅在本稿和原 `/home/liuzewen/F:\deepseek/papers/agent_effort` 内寻找：活动 experiments、anc、submission/repo 的同名脚本及两个 submission ZIP 内同名脚本，全部为 7e2d56…；未找到 3326b5… 的完整快照。`h4_gx_measure.py` 另为 0c5671…，且是不同单轮设计，不能充当匹配快照。`evidence/H4_SELFHASH_DEFECT.md` 还记录了历史自哈希在写出时才计算的问题，某次新卡运行的自报 hash 已被证明不能绑定起跑代码。

因此下面的代码语义是**当前归档源码的静态检查**，与 raw 样例吻合不等于恢复了原运行的完整代码身份。正文必须写“当前提供的 harness 实现……；执行时的精确快照尚未恢复”，不能称所有旧结果已与本地脚本逐字节绑定。本轮没有扩大到其他磁盘或云端检索。

## 1. budget:steps 的 cap+1 是拒绝哨兵，未证明多执行了一步

当前 `experiments/h4_real_llm_gx.py:519–528` 的顺序是：

1. `steps += 1`（521）；
2. `steps > max_steps` 则抛 BudgetExceeded（522–523）；
3. 构造下一轮提示（524–525），再调用模型（527）。

因此步数耗尽时，`steps_used` 被写为 cap+1，但第 cap+1 次模型调用和动作执行未发生。它记录“下一轮尝试被拒”的计数，不是实际多花了一次推理。

原始样例相符：

- `results/h4_real_llm_gx_qwen3_8b_persist.json:1397` 开始的第一条记录：max_steps=2，steps_used=3，n_history=2，model_turns 只有 read / write，reason=budget:steps。
- `results/h4_real_llm_gx_qwen3_14b_persist.json:1375` 的第一条也是同样结构。

必须披露：动作数/模型调用数宜从 `n_history` 或保存的动作列表解释；不能把步数失败的 `steps_used` 直接等同于已执行动作数。模型看到的 `state.steps_used` 已包括当前正要生成的这一轮（433、524–527），第一轮就显示 1；这是另一个需要明示的计数约定。

E3 也先自增再检查（`e3_agent_loop.py:255–259`），但它是遍历固定动作表而非 while 生成。原始 E3 第一条在 `results/e3_agent_loop.json:330`，steps_used=2 而 timeline 只有一个 read，因为第二步的 probe 在工具/视觉预算检查处被拒；说明即使不是 steps 超限，steps_used 也可能包含未完成动作的尝试。

## 2. 成功是预算内的显式测试通过事件，不等同于最终文件正确性

H4 的执行分支见 `h4_real_llm_gx.py:539–576`：

- read / probe / test 在执行前检查工具预算；write 只消耗 step，不计 tool call（560–564）。
- test 调用真实 `run_hidden_tests` 后，把 rc 存入 history；通过立即设 success=True 并退出（565–574）。
- 步数超限在下一次模型生成前发生（521–523），except 将 reason 改为 budget:steps（577–580）。已经写好的代码不会在超限之后自动补判。

所以预算内写出正确 sol.py 但没选择 test，与写出错误代码，在成功变量上都可能失败。**该指标测量的是“在预算内获得验证的完成”，不是所有终止文件的正确率。** 它使“测试动作减少”与成功下降在定义上直接相关，不能把两者共现当作已独立证明的能力下降或因果机制。

H4 `:582–589` 有 `reason == "budget"` 才补测的代码，但当前 while 的正常终止路径都已设 tests_passed / parse_failures / budget:<原因> / error:<类型>，不能把它误写成“耗尽预算也会统一最终判分”。E3 `:299–306` 有同样补测，其触发是动作表自然结束且 reason 仍为 budget；补测不计新增工具数。当前固定表末尾本就含 test，正常 oracle 修复通过时不需要该路径；本轮没有证据断言它改变了已存结果。

## 3. “隐藏测试”是接口层隐藏，评分器不是隔离的防篡改测评服务

- E3 `:218–231` 在 episode 目录启动 Python 子进程，import hidden_test.py，要求 unittest successful 且 testsRun>0 才正常退出 0；外层实际只看整个 subprocess returncode。
- H4 `:504–508` 将 sol.py 与 hidden_test.py 写在同一目录。read 动作只读 sol.py（540–547）；probe 只返回长度（554–556）；模型不会通过这些预定义动作直接读到测试文本。
- 但 write 可写任意 Python 文本进 sol.py（560–564），随后该文本在测试进程 import 时执行。代码没有建立操作系统层隔离、文件访问限制或独立不可篡改评分协议。因此“cannot read tests”只能解释为“没有提供读测试的动作/正常反馈”，不能宣称测试对执行中的程序绝对不可访问。
- 正常 runner 对 testsRun>0 的检查有意义，但不能保证所有 rc=0 都来自 runner 完整跑完该检查：导入的任意程序可能提前退出或影响进程。**本轮未发现/未声称某条 raw 利用了该路径**，也未执行攻击；这是评分完整性的边界。
- H4 输出 `:608–609` 只保存动作名和测试 rc，不保存完整生成回复、每次写入的代码、完整提示、最终 sol.py 或 finish_reason；`:611` 删除工作目录。现有包无法逐条回看最终代码或离线重判反事实正确率。

正文可写“接口隐藏的三条单测，真实子进程 rc 判分”，不要写“经过完整语义正确性认证”。

## 4. E3 与 H4 同任务、同预算、同 grader，但动作语义并不等同

| 内容 | E3 | H4 |
|---|---|---|
| 策略 | 固定规则修复器 | LLM 每轮选动作 |
| read_then_write | 强制 `[read, probe, write, test]`，E3:212–214 | 允许 `[read, write, test]`，H4:344–347；没有 probe |
| probe_heavy | 强制 `[probe, read, probe, write, test]` | 允许 `[read, probe, write, test]`；不强制 probe 次数或顺序 |
| write | E3:280–283 直接写已知 `task["fixed"]`，是 oracle 参考修复 | H4:560–564 写模型生成的代码 |
| 任务信息 | 规则策略直接持有 task 对象，不需要理解题意 | H4:419–443 显示文字 spec、starter、预算、动作与 history |

H4 `:324–336` 确实 import 了 E3 TASKS/BUDGET_LEVELS/grader；这不证明“只换 policy、其余实验全相同”。E3 和 H4 的 read_then_write 在最短可通过路径、probe 负担上已不同，E3 oracle 还预先知道完整解。应改称 **shared-task comparison under related budget configurations**，不能称严格同构的政策替换实验或相互独立复现。

H4 的 SYS（410–415）展示所有四种动作，而 USER allowed actions 随 menu 变化；parse_action `:478–483` 最终以实际 menu 拦截。在不含 probe 的 menu 下选择 probe 会成为 invalid 并消耗一步，不能把两个 menu 当作仅更换顺序的对照。

## 5. 上下文、记忆与“视觉”轴的实际操作定义

**历史确实被截断。** `h4_real_llm_gx.py:442` 将序列化 history 按字符截为最后 3000 字符，可能从 JSON 字符串中间切开；模型没有收到“这里已经截断”的标记。state.actions 保留全部动作名（433–435），不能恢复丢失的 obs 内容。

**每轮 starter 是原文件。** episode 在 524 传入 `task["starter"]`，build_messages 在 439 插入它。write history 仅存字符长度（564），不存新代码。因而后续提示可能同时含旧 starter 和若干“写过 N 字符”的记录；模型只有再次 read 才获得当前文件内容，且 read 的 obs 仍受 history 截断影响。

**max_context_chars 不是模型窗口。** `ctx_chars` 只在 read/probe 时累加观测字符串长度（545、557），每轮结束才检查是否超阈（575–576）。它不包含 system、spec、starter、历史 JSON、预算、模型输出代码或实际 tokenizer 长度。`episode(...prompt_char_limit=12000)` 参数在读取的 episode 内没有被使用；模型真实最大长度是 VLLMBackend 的 max_model_len（269、289）。应称 **累计 read/probe 输出字符预算**，不能称完整 context capacity 或 token budget。

**视觉不是图像理解。** probe `:554–556` 只返回 task_id / starter / hidden-test / family 的四个字符串长度；不创建图像、不调用视觉模型，且包含测试脚本长度这一侧信息。E1b 的 PNG 时延原语也不能把 H4 probe 自动变成真实多模态任务。宜写 structural probe，vision 仅作为历史预算变量名。

**导出载体的 null 是真实缺陷。** `evidence/h4_observation_protocol.json` 写 history_truncation_chars:null。导出脚本 `scripts/export_observation_protocol.py:81–85` 用一个未匹配实际调用的 regex，未匹配就保留 None，且不失败。因此此 null **不能作为无截断的证据**；应修导出器及载体并加反证，或直接以源码说明 3000 字符截尾。预算可见本身仍由模板支持，但不能据此排除上下文漂移。

## 6. 任务构造、复用与有效单位

任务完整定义在 `e3_agent_loop.py:57–198`：八个手写程序任务（分组求和、JSON往返、去重、二分查找、词频、转置、区间合并、top-k），每题 starter、参考 fixed、三条公开在源码中的 unittest。不是外部标准 benchmark 的随机样本；E3 文件头还写“40 tasks”和30 episodes（11、31–32），属于旧注释，不能引用为实际规模。

H4 SPEC（102–119）从这些测试的契约整理而来。相同八题用于 E3、两个 H4 模型、五档 coupled budgets、三条 single-axis sweep、跨卡复查和 A9 重复；它们不是新的独立测试集。三条测试只覆盖少数实例，例如 t02 的 equality 测试并不检查是否真的产生独立 deep copy，因此“程序任务完成”仅指给定测试通过，不能外推任意输入或完整 contract。

E3 `:357–362` 对固定任务/预算/调度重复三次。H4 `:1073–1079` 对每个 arm/repeat/task 循环，seed 在 `:395–403` 只依赖 task_id 和 rep，跨预算/menu/模型复用；后端 temperature=0（307–308）。这适合配对，但不是增加独立随机任务或独立随机策略样本。

旧伪重复检查已把48条压到16个 task×menu 单元（`experiments/h4_pseudoreplication_check.py:33,51–58`）。进一步的限制是 **16单元来自仅八个 task，每个 task 下两种 menu 仍相关**。`scripts/h4_unit_recount.py:41–47` 只以 task/menu 为字典键，`:85–87` 只检查恰好16键，并没有建立这16个键统计独立。字典压缩还直接覆盖 repeats；现存重复确实一致的证据需保留，不能让此脚本对未来不一致 repeats 静默选最后一条。

必须写“16 task-menu cells nested in eight tasks”，将现有单元级检验标为忽略菜单内任务聚类的探索性读数；若需要推断，另做 task-cluster 敏感性分析或仅描述八个固定任务。CI宽度和拟合功效不能由复制三次或十二次的记录数获得。本轮不重算新 p 值。

## 7. 分离预算扫与完整五轴主张

H4 `AXIS_SWEEPS`（357–365）只扫 steps/tools/probe；search 没激活，reasoning 没变化。axis_arms `:374–379` 只用 probe_heavy menu，另一菜单只在 iso arm。其余参数保持 mid，不等于已证明这些参数 non-binding；raw 的 why 文本写 non-binding 是设计意图，需避免当测量事实。

iso 五档同时增加 steps/tools/read-probe字符/probe数（E3:202–207），且提示把这些预算直接展示给模型。因此观察到的行为变化既可能来自硬约束，也可能来自预算提示、动作可用性和历史保留；没有条件把“纯计算量增加”从这些因素中分离。当前数据不支持普遍五轴增益、g_search 或真实视觉收益的估计。

## 8. 协议 / experiment_plan 的记录边界

包内有 `evidence/protocol.md`（含事后更新、A9补充）和 generic `scripts/run_experiment_plan.py`，但本轮在本稿文件名检索中未找到 H4 具体的 `experiment_plan.json`。generic orchestrator 的存在不是该实验执行记录，也不是预注册时间证明。其脚本 `:66–81` 对已存在非空 artifact 直接 skip，不验证计划身份/源码hash，不能用它替代实际 run provenance。

H4 的实验目标和规则可称内部预先指定（在证据许可范围内），不能把事后单元修正或本轮复核称外部 timestamped preregistration。`scripts/h4_unit_recount.py:11–12` 已明确本身是 2026-10-10 post-hoc、无新 episodes，此定位应该保留。

## 必须纳入修改稿的最短披露清单

1. 成功定义为预算内显式测试通过；未经测试的终止代码按失败；不等于最终文件反事实正确率。
2. steps_used 可包含被拒的下一步计数，budget:steps 的 cap+1 不代表额外执行。
3. E3 是已知参考修复+强制动作表；H4 是菜单驱动，两个实验没有严格同构。
4. 每轮原 starter、write 不持久化代码、history 截尾3000字符；字符预算仅计 read/probe 输出。
5. probe 是四个长度值，未测真实视觉；未激活搜索、未扫 reasoning。
6. 八个手写任务、16 task-menu cells、有任务内依赖和确定性重复；不将全部 episode 作为独立样本。
7. 隐藏测试为接口层隐藏、判分为进程rc；生成代码/提示/finish_reason及最终文件未全部归档。
8. 原运行匹配脚本快照未找回；当前源码检查和原始运行身份绑定必须分开。

这些局限不自动否定全部描述性数据，但会改变论文所研究的问题。诚实定位是一个小型、接口与评分规则明确的预算完成测量案例，不能写成对通用 Agent 能力曲线或路由收益的确证。


## 补充：Git 历史中的匹配快照检索

只读检索原仓库全部可达 refs（git rev-list --all --objects），限定 papers/agent_effort 树；目标路径 git log --all --follow 仅返回一次纳入版本控制的提交 `15a89f5be9ecfccf7124f951fa8cd0adf7569d54`（2026-10-10T09:59:17+08:00）。该路径和 anc 同名文件指向 Git blob `491b20fa5acf9a0667b1498276ac25372170841b`，SHA-256 为 7e2d56…，不是目标 3326b5…。

树内可达对象条目 144 条；先核查 H4 名称的14个唯一脚本/备份 blob，再扩为该树所有 Python/备份候选，共 56 个唯一 blob；匹配 3326b513fa891cbd99e8c1ffcd986bd27d9dac73fd75dc7a3a31c0993db3f9e8 的数量为 0。未 checkout/reset、未改原库，未以不匹配脚本伪造 runtime_snapshot_h4.py。

这是全部可达分支历史的树内搜索，不是全盘或已删除不可达 Git 对象/云端备份搜索。当前不能恢复执行快照的结论维持；Git 在执行后才纳入论文树，不构成原始运行期代码归档。
