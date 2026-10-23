# Agent Effort R1 独立审稿

日期：2026-10-13。对象：`paper/main.tex`、新表、`scripts/recompute_arxiv_r1.py`、`results/arxiv_r1_descriptive.json`、六份结果文件的元数据及部分记录、`experiments/h4_real_llm_gx.py`、`experiments/e3_agent_loop.py`；并读 `reports/h4-protocol-review-r1.md`、上级 `reports/agent-effort-source-check.md` 与已认证来源的本地 TXT 对应段落。本轮没有修改论文、没有重跑模型或分析。关键算术人工手核；不声称重新独立计算全部记录或认证历史执行真实性。

## 总体建议

**可以在完成材料公开与少量措辞消歧后，作为条件数值模型加小型记录审计的描述性 arXiv 预印本发布。当前不能称为部署收益验证、通用 Agent 扩展规律、模型准确率认证或顶会质量认证。** 内部审稿不是外部 peer review，arXiv 收录也仍由平台决定。

R1 不是仅把旧结论软化：它已把 E2 的数学假设和 H4 的保留记录分开，承认工具接口、同任务嵌套重复、测试选择与代码版本断链。主要结论在这个狭义范围内获得材料支持；原实验的机制识别与真实性审计缺口没有被解决。

## 逐条论断核查

| 核心论断 | verdict | 证据及边界 |
|---|---|---|
| E2 搜索 8,820 个 tuple，3.44/4.52/2.05 是假设函数内的成本比 | supported | `main.tex:61–95`；`recompute_arxiv_r1.py:127–176`；`tables/allocation.tex`。5×7×7×6×6=8,820。公式和代码一致。不是模型实测收益。 |
| 比值按至少达到基线 modeled success 的最廉价格点算，允许略超 | supported | 脚本 `:150–160` 使用 success >= baseline 的阈值；表题明确。JSON 中 fixed-middle success .531961 对 matched .532772；不是等成功率拟合。 |
| 全最大 endpoint 不建立节省，且最优 tuple 可能不是可执行轨迹 | supported | `main.tex:89–91`；all-max ratio=1；无 calls-per-step 可执行性约束被明确承认。 |
| 每个 H4 文件有 672 记录，coupled 部分每档 48、实际仅 8 任务两菜单三重复 | supported for retained metadata/structure | 脚本 `:69–106` 检查 672、覆盖键、预算与重复结果/动作摘要相同。该检查不是历史模型调用的独立真实性证明。 |
| 8B L1→L4 为 -.1875，14B 为 +.0625，14B 不复制 8B 的方向 | supported | 见下方手核；正文 `:102–105` 没把它变成独立样本显著性或普遍规律。 |
| Success 是预算内显式 rc=0 的 test event，而非全部终止代码正确率 | supported for supplied code and retained outcome fields | H4 `:565–589`；新脚本 `:98–100`；正文 `:108–112,125–128`。代码缺失和 grader 边界阻止更强正确性认证。 |
| 8B 的高预算失败都由同一种通用 verification-collapse 机制导致 | refuted as a general attribution; not claimed by R1 | 14B 的失败多次测试，且 success 与 test 定义相连；正文 `:108–110` 已明确撤回共同机制结论。 |
| H4 source inspection 完整验证了历史运行 | unverifiable; appropriately disclaimed | 两 persist 的 stored SHA-256 与提供脚本不同，缺最终程序和完整模型回复；正文 `:40,127–128` 明确不认证。 |
| source 支持“首次推翻普遍单调 Agent 定理”或真实五轴收益 | refuted; not claimed by R1 | 来源 Appendix B.2 本身有中间平台/下降；E2 gains 是假设，H4 不扫 reasoning/search。正文 `:31–33,67–80,115` 已避免旧叙述。 |

## 人工数字核对

1. `tables/tasks.tex` 的 8B L4−L1 仅 t02=-1、t08=-.5，其余六题 0；总和 -1.5，除以 8 得 **-.1875**。删去零差题得 -1.5/7=-.2142857，删去 t02 得 -.5/7=-.0714286，故正文 LOO 范围 **[-.2143,-.0714]** 正确。它是固定八题组成敏感性，不是随机样本区间。
2. 14B t03=+.5、t05=+1、t07=-1，其余五题 0；总和 +.5，除以 8 得 **+.0625**。删 t05 得 -.5/7=-.0714286；删 t07 得 +1.5/7=.2142857，故 **[-.0714,.2143]** 正确。
3. 两菜单 × 三重复 × 八题=48/档，五档=240；18 个单轴水平 × 单菜单 × 三重复 × 八题=432，合计 **672/模型**。不是 672 个独立任务样本。
4. 8B 曲线 0,.9375,.875,.8125,.75，14B 0,.8125,1,.875,.875，与表和新 JSON 一致。所有非零率有对应任务/菜单分母；没有新发现数值冲突。
5. 3.44≈23429.2046/6810.4189；4.52≈34400/7610.4189；2.05≈101716.8182/49600。all-max 145600/145600=1。它们认证的只是当前代数输出，不是 H4 token 使用。
6. 新 JSON 的 L4 失败 action summaries 支持正文：四个 8B task-menu 条件均 read 一次、write 31 次、test 零次；14B 两个条件均 t07，分别 (17 write,9 test,6 read) 与 (24 write,5 test,3 read)。缺少生成程序，不能判断 8B 是否写对、14B 最后是否已修对但没再测试。

## 尚未解决的严重科学问题

### 1. 实际运行身份没有闭合，必须保持 records/supplied-code 两层

这是当前最重要的剩余边界，不应被“所有 gate passed”或 `is_real_llm:true` 取代。`results/h4_real_llm_gx_qwen3_8b_persist.json:97` 与 14B 相同位置记录 3326b513…；提供代码是 7e2d56e7…；`H4_SELFHASH_DEFECT.md` 还说明自哈希是在结束写出时读磁盘，不总能绑定起跑代码。检索到不到指定快照不能证明数据伪造，也不能替数据完成执行认证。

R1 `main.tex:40,127–128` 的披露充分，应保持在公开版本。最低补正是让摘要“672 recorded executions”和 `:43` “H4 receives”统一成 **672 retained execution records** 与 **the supplied H4 implementation presents**；避免局部不带限定句让读者误以为本文已经认证实跑协议。表/JSON 的 flags 只能验证字段自称 real/non-stub，不能把它当独立证据。

若希望继续声明可再生的真实模型实验，需要恢复并绑定起跑快照、依赖环境、完整模型请求与生成程序或重新冻结重跑。当前稿选择记录审计，就不必假称这些缺口已修好。

### 2. success 仍是选择性验证事件且 grader 未隔离

H4 源码只在模型选择 test 且 rc=0 时成功；结束时未统一判最终文件。测试与 success 的相关性含定义关系。三条测试也没有覆盖整个契约；执行中生成程序与测试共目录，没有防篡改判分边界。R1 已明确这些限制，故没有新增必须重跑才能维持描述性定位的要求。

发布时不能把新表 success rate 在题名、摘要以外的介绍页又简称“代码准确率”，也不能写成“14B 检查得更多所以能力更强”。没有程序留存意味着本稿无法新增最终代码准确率、作弊率或反事实 oracle grading；不能用补写一个分析脚本产生缺失事实。

### 3. E2 的可优化性与收益来自自己选择的假设

E2 的正收益、独立坐标、非可执行 calls/step、固定价格和不变基线给优化器结构优势。当前稿 `:78–95` 如实承认。需要保持“conditional calculation”标签；不应以“来源锚定”和本机时延让 3.44× 看起来是实测控制器收益。H4 没测 reasoning/search，也没提供 E2 四增益的外推估计。仅增加同样八题的 repeat 不解决这一点。

作为 arXiv 案例这不是必须删除的数学玩具，但目前它与 H4 之间是解释/审计联系，不是被实验验证的一套方法。顶会贡献若以 resource allocation method 为主，需要可执行约束、拟合/标定与持出任务控制器比较。

## 来源使用审查与最低文字修正

- 正规 `v41flash2026` 引用已含 arXiv:2609.19969、版本与节号。上级 source-check 记录官方 PDF 哈希链，本轮没有再次上网做身份认证。
- 对本地已认证 TXT 的人工阅读：`:2434–2436` 明确 .671→.763 是 **八个 reasoning-intensive benchmarks 的平均 Pass@1**；`:3257–3267` 明确不同 scaffold 下会有平台和中间下降。R1 `main.tex:33` 对此概括适当，没有制造一个来源未声称的普遍单调定理来推翻，也没有长篇直接摘录。
- 建议将 `main.tex:67` 的泛称 reasoning accuracy anchors 改为 **average Pass@1 across eight reasoning-intensive benchmarks**。这样读者不会误认这两个端点是编程任务或本稿 Qwen 的 accuracy。`:22` “three reasoning-effort anchors”也可更精确写成“两端点与一个近似 token multiplier”。
- `recompute_arxiv_r1.py:242` 的输出日志仍写 three tables，但实际写了 allocation、curves、tasks、latency、axis 五表；改日志即可，不影响数值。
- `main.tex:123` 说 retained action list 描述 completed actions；严格地说它是保留的 action/attempt summary，可能记录 invalid action，且被预算拒绝的下一次动作未必入列表。当前重点是不要用 cap+1 推断额外模型调用，可将句子改成 **retained action summaries distinguish recorded actions from the step-counter sentinel**，不要给该摘要更完整的执行语义。

## 公开描述性稿的最低收尾条件

1. 保持 runtime snapshot 与真实执行的限定，统一上述局部 wording；不可把内审状态称外部审稿通过。
2. 为 ancillary package 建立固定公共 release/持久链接，并在正文 `:133–134` 替换 intended/no public identifier。仅 TeX 排版包不支持核心“可重算”贡献。包括六 raw JSON、当前推导脚本、五张表与新 JSON、八任务/模板、脚本不匹配与 self-hash 缺陷记录、原始文件哈希和最小 README。第三方报告提供链接与身份校验，避免把 pointer stub 当全文。
3. 清楚标记历史材料不是当前论断依据，尤其旧 gain_fit、record-level CI、隐含16task-menu独立性、旧 novelty/monotonicity叙述；保持原记录不变，但公开 README 要给当前入口和废弃解释索引。
4. 完成包外独立执行重算、负对照、最终 PDF 目检与源包编译。父任务已有检查记录可供发布验收，本审稿人本轮没有运行它们，不能以本报告替代。
5. 作者/Independent Researcher 已由本人确认；发布许可、分类、账户/endorsement与 arXiv 收录状态仍按实际提交处理。

**在这些有限收尾完成后，不要求为了当前描述性范围另跑新模型。** 若目标恢复为普遍五轴能力规律、可部署节省或顶会主会方法论文，仍需新的任务、完整协议绑定、可信最终程序判分与实际控制器实验。

最终 verdict：**supported for finite-record arithmetic and the explicitly conditional scope; unverifiable for a complete historical-execution audit; needs-work for public release readiness.**
