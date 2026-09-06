# 研究：审计合理性与准确性的自我迭代——让审计量与人工纠正量变成审计 agent 的燃料

日期：2026-09-06　范围：节点级 AI 审查、一键分析、确定性工具、接地守卫、提示词与业务包的持续改进机制
方法：生产库人工反馈数据盘点；代码中反馈采集点逐一核实（见第 2 节）；对照 2025–2026 年人机协同评估文献中被反复验证的做法（见第 8 节来源）。

## 0. 结论先行

1. **今天没有飞轮，因为没有燃料。** 采集端点其实建了九条，其中四条 UI 不可达、两条不落库、一条发常量；生产库里"人工最终结论 vs AI 建议"的对比字段早就设计好了（review_opinions 的 aiSuggestedResult / overriddenFromAi、ai_feedback 的 correctedOutput / rootCause、feedback_triage 的 canUseForEval），但真实数据为：人工结论 1 条种子，AI 反馈 1 条种子，证据链驳回 0 条。117 次 AI 审查里没有一次被人在系统里"改过"。任何算法层面的自我迭代都排在"让每次人工动作留下一条可对比记录"之后。
2. **可迭代的不是模型，是四层可版本化的资产**：确定性工具与数据表（限值、覆盖表、时间线）、接地守卫语料、提示词与清单模板、案例库（few-shot / 回归样本）。模型权重不训练（数据量、合规与成本都不支持），但四层资产每一项都能由人工纠正驱动、离线回放验证、按版本灰度。
3. **迭代必须是"离线回放 → 指标不降 → 灰度 → 全量"，不能是"边跑边学"。** 监检结论是法定行为，任何自动调整都不得改变已出具的结论；纠正只影响下一版资产。
4. **人工纠正本身要被质检。** 人机协同文献的一致警告是自动化偏差：接受率接近 100% 说明人没有独立判断。要设计"盲审抽样"和"覆盖率 / 覆盖差异率"两个反向指标，否则飞轮会把错误固化。
5. 建议按四步走：第 1 步（本周）把采集补全并可度量；第 2 步（2 周）建纠正分类与回放基准；第 3 步（1 个月）四层资产的半自动更新流水线；第 4 步（持续）指标看板与灰度治理。总工作量约 12–16 人日，全部落在已有优化计划的 P8 H0 与 P9 R2 之上。

## 1. 什么叫"审计 agent 变好"

先把目标写成能算的数：

| 指标 | 定义 | 数据来源 | 方向 |
|---|---|---|---|
| 采纳率 | 人工最终结论 = AI 建议结论 的节点占比 | review_opinions.result vs aiSuggestedResult | 高，但不是越高越好（见 §6） |
| 覆盖差异率 | 人工改动 AI 结论的节点占比（不符合↔满足、需补正↔证据不足） | overriddenFromAi | 逐版下降 |
| 发现级精确率 | 人工采纳的 AI 发现 / AI 发现总数 | review_findings.humanStatus | 上升 |
| 发现级召回率 | AI 发现覆盖的人工独立发现 / 人工独立发现总数 | 人工新增发现（今天无此入口） | 上升 |
| 降级率 | 守卫降级为"证据不足"的发现占比 | groundingStatus | 下降到个位数 |
| 误降级率 | 人工判定"其实有依据"的降级发现占比 | 需要人工在折叠组里点"其实有依据" | 下降 |
| 证据引用准确率 | 人工确认 AI 引用的证据位置正确的比例 | evidenceRefs 点击后确认 | 上升 |
| 独立性 | 盲审样本上人工结论与 AI 建议的差异率 | §6 盲审 | 保持在合理区间，不趋零 |

没有这张表，"迭代"只能靠感觉。P8 H0 的基准脚本要把这张表作为输出。

## 2. 现有采集点盘点（代码核实结果）

### 2.1 已经建好但没接上的
| 采集点 | 端点 | 落库 | 现状 |
|---|---|---|---|
| 人工审查意见（主路径） | `POST /projects/{p}/inspection/nodes/{n}/review-opinions`（routes.py:13118） | `review_opinions`：result、opinion、basis、evidenceLinkIds、**aiRunId、aiSuggestedResult、overriddenFromAi**（13161–13190 做了 AI 展示词→业务词归一后再比较） | 唯一算出“人机不一致”的地方，但 **没有任何代码读取 overriddenFromAi**；也不写 ai_feedback |
| 采纳 AI 建议 | `POST …/ai-suggestions/{sid}/adopt`（13371） | **不落库**，只返回内存草稿 + 一条无 before/after 的审计日志 | 最强的正向信号是“阅后即焚” |
| 驳回 AI 建议 | `POST …/ai-suggestions/{sid}/reject`（13432） | **不落库**，理由只放在 mutation_result 信封里；前端传的 manualOpinion 被丢弃 | UI 写着“该说明会进入审计日志”，实际没有 |
| 单条发现 采纳/驳回 | `POST /review/findings/{id}/accept` 与 `/reject`（16585 / 16650） | review_findings.status、rejectReason、revision | **前端没有调用者**，只有测试在调 |
| B 线人工决定 | `POST /review-runs/{id}/human-decision`（12859 → execution.py:3709） | review_runs.humanDecision、ai_feedback、review_findings（originalAiOutputHash / correctedOutputHash / humanEdited） | 设计最完整的一条：**`submitReviewBHumanDecisionApi` 零调用点**，UI 不可达 |
| AiRun 反馈 | `POST /ai/runs/{id}/feedback`（16686） | ai_feedback（feedbackType 十值枚举、correctedOutput、shouldEnterEvaluationSet） | 只有测试在调；采纳/驳回本应调它 |
| 证据链确认 / 驳回 | `POST …/evidence-links/{id}/confirm` 与 `/reject`（7348 / 7368 → material_targeting.py:1254） | manualStatus、manualComment、confirmedByName / rejectedByName | 后端保留驳回理由，**前端发的是常量字符串**“监检人员不采用该候选证据。”，从不问为什么 |
| 退回补正 / 补充资料单 | `POST …/actions/return-correction`（13461） | rectifications：status、rectificationType、comment、bindingIds、supplementRequirements | **没有 aiRunId / finding 引用**，答不了“哪条 AI 发现导致了退回” |
| FDE 诊断反馈与 triage | `POST /fde/review-runs/{id}/feedback`（21430）、`/fde/feedback/{id}/triage`（21937） | ai_feedback（rootCause 十二值枚举、originalAiOutput、correctedOutput、expectedEvidence、完整版本谱系）、feedback_triage、evaluation_cases / evaluation_sets（黄金集 ESET-GOLDEN-ENGINEERING-001，门槛 evidenceHitRate ≥ 0.9，routes.py:22249） | 完整，但标注 `diagnostic_only_no_business_state_change`，只有 FDE 人员用；监检人员的真实动作从不进来 |

### 2.2 已有指标与它们读的数据
- `acceptance_rate`（采纳率）、`evidence_hit_rate`、`hallucination_rate`（routes.py:17323–17347）三个指标都只读 ai_feedback。因为 2.1 里监检人员的路径不写 ai_feedback，这三个数今天算的是 FDE 与种子数据。
- `_human_corrections_for_review_run`（execution.py:3358）只被 FDE 控制台的只读表消费；提示词组装、检索、规则生成没有任何代码读 ai_feedback、evaluation_cases 或 review_opinions。**没有任何东西回流到生成侧。**
- ai_trace_steps 记到模型输出为止，没有人工结果字段。
- 可用的连接键：review_opinions.aiRunId ↔ ai_runs.id ↔ ai_feedback.aiRunId ↔ review_runs.aiRunId ↔ review_findings.sourceDraftId。缺口：review_opinions 只存 aiRunId 不存 suggestion.id，一次运行多条建议时无法区分。

### 2.3 三条最高价值的缺口
1. `overriddenFromAi` 是全库唯一算好的“人机不一致”信号，没人读它。对 review_opinions 做一次聚合，不用新增任何采集，就能得到按节点、按规则的一致率——前提是人先在系统里提交结论（今天真实记录 1 条）。
2. 采纳与驳回不写 ai_feedback。两个 handler 都已经解析了 latest_run 与 suggestion id，加一次 `record_human_feedback` 调用，监检人员的真实动作就接进了现成的 triage → 评估集 → 黄金集流水线。
3. 两条建好的路径 UI 不可达：B 线 human-decision（已做 AI 原文与人工改写的哈希）与 finding 级 accept/reject。接上即得到监督改进所需的“原文 / 改写”对。

## 3. 人工纠正的分类学

纠正只有分好类才能变成资产更新。建议在 ai_feedback 的 rootCause 上固定七类，每类对应一种资产与一种自动化程度：

| 类别 | 例子（本轮审计里真实出现的） | 更新的资产 | 自动化程度 |
|---|---|---|---|
| A 数据表缺失/错误 | 焊材限值档案为空；TSG 2026 覆盖表未录；R27/R28 标准号 | 限值 YAML、覆盖表、时间线 | 半自动：纠正生成"候选行"，人工核对原文后合并 |
| B 确定性规则错误 | 分片去重 key 含 severity；位置表 6G→全部；validFlag 当现行 | 工具代码 + 单测 | 手动开发，纠正直接变成回归用例 |
| C 守卫误杀 | 法规号 Z6002-2010、日期 2026年12月25日、施工单位名被判无据 | `_supplied_identifiers` 语料 | 全自动：人工点"其实有依据"→ token 进白名单候选 → 回放验证 |
| D 证据抽取错误 | 焊工证抽取器一份文件一张证；管道特性表置信度 0 | OCR profile、抽取器 | 手动开发；纠正样本进抽取回归集 |
| E 提示词/输出结构 | 模板句 67%；小模型信封走样 | 提示词模板、清单项 | 半自动：纠正样本进 few-shot 案例库 |
| F 业务口径 | 充氩前提、作废版本判预警 | 2.5 默认分支表、rules.yaml criteria | 手动，业务方决定 |
| G 平台/外部源 | 平台只取第一条记录；TSG 无在线源 | 集成客户端 | 手动开发 |

分类由两步完成：人工提交纠正时选一个粗类（"AI 说错了 / AI 漏了 / AI 引用错了 / 依据不对"），周度 triage 时由维护者定到 A–G 并写 rootCause。feedback_triage 表已有 canUseForEval / canUseForTraining / dataSensitivity 三个字段，正好承载。

## 4. 四层资产的迭代回路

```
人工动作 ──► 纠正记录（分类、原 AI 输出、人工输出、证据）
                │
                ▼
        周度 triage（A–G）
                │
     ┌──────────┼──────────────┬──────────────┐
     ▼          ▼              ▼              ▼
 数据表候选行  守卫白名单候选  案例库条目    回归用例
 (A)          (C)            (E)           (B/D)
     │          │              │              │
     └──────────┴──────┬───────┴──────────────┘
                       ▼
            离线回放：基准样本 + 全部历史纠正
            （P8 H0 脚本；指标见 §1）
                       │ 指标不降
                       ▼
            资产新版本（YAML / 语料 / 模板 / 用例）
            带版本号进业务包快照
                       │
                       ▼
            灰度：新旧版本各审一遍同一节点（影子运行）
                       │ 一周无新增误判
                       ▼
                    全量
```

### 4.1 数据表（A 类）
- 纠正记录里带"人工写的正确值 + 原文页码"，脚本生成候选行（标准号、牌号、字段、值、来源），进 `pending_limits.yaml`；核对人对照原文后移入正式档案并写 `verifiedBy`。
- 回放：所有引用该标准/牌号的历史证书重新核验，人工已确认的结论不得翻转。

### 4.2 守卫语料（C 类）
- 人工在"证据不足"折叠组里点"其实有依据"，系统记录被判无据的 token 与人工指出的证据位置。
- 自动规则：同一 token 被 ≥3 名不同审查人在 ≥2 个项目里标"有依据" → 进白名单候选；回放验证该 token 进语料后降级率下降且没有新增无据放行 → 合并。
- 只加标识符，不加结论词（P8 H3 原则）。

### 4.3 案例库与清单（E 类）
- 每条被人工改写过标题/正文的发现，存为 `(节点, 规则, 证据摘要, AI 原文, 人工改写)` 案例。
- 提示词组装时按 节点 + 规则 + 相似证据 检索 2–3 条案例作 few-shot（案例即检索，不是训练）；小模型受益最大（清单模式 H5 的清单项也可由案例库反推缺项）。
- 案例带版本与失效日期，规则文本变更时自动下架相关案例。

### 4.4 回归用例（B/D 类）
- 每条 B/D 类纠正生成一个用例：输入快照（OCR 快照 + 事实）、期望输出（人工结论）；进 `backend/tests/regression/<rule>/`。
- CI 与 P8 H0 基准各跑一次；用例只增不删，行为变化需显式更新期望并记录原因。

## 5. 采集设计：让每次人工动作都留下可对比记录

| 人工动作 | 今天 | 应改为 | 落点 |
|---|---|---|---|
| 提交人工结论 | review_opinions 已有 aiSuggestedResult / overriddenFromAi 字段 | 前端提交时强制带上当时展示的 aiRunId、结论卡结论、发现 id 列表；结论不同则弹一个"为什么"单选（AI 说错 / 漏了 / 引用错 / 依据不对） | P9 R1 结论卡 + ReviewDecisionPanel |
| 对单条发现表态 | 无入口 | 每张发现卡两个按钮：采纳 / 不成立（不成立必选原因） → review_findings.humanStatus + ai_feedback | P9 R1 |
| 证据不足折叠组 | 只显示 | "其实有依据"按钮：选哪条 token、指向哪个证据位置 | P9 R1 + 守卫白名单流水线 |
| 证据链确认/驳回 | 420 确认、0 驳回 | 驳回必填原因（位置错 / 内容不符 / 文件错）；驳回记录关联 AI 生成的 evidenceRef | 已有接口补字段 |
| 退回补正 / 联络单 | rectifications 无 AI 关联 | 记录触发它的 finding id 与 AI 建议动作；补正后再次审查的结果回写"补正是否解决了该发现" | routes 补字段 |
| 人工新增发现 | 无入口 | 结论卡底部"补充发现"：标题、证据位置、规则 → 作为召回率分母 | P9 R1 |
| 一键分析节点级修改 | 无 | 同上，复用 | P9 R4 |

采集覆盖率指标：有 AI 审查的节点里，最终有人工结论记录的比例。目标 100%（今天 <1%）。

## 6. 防止飞轮把错误固化

- **自动化偏差**：文献里放射科实验显示 AI 出错时经验不足的审阅者准确率从 80% 跌到 20%。对策：每周随机抽 10% 已完成节点做盲审（不显示 AI 结论，由另一名审查人独立判），盲审差异率与常规差异率之差就是"橡皮图章指数"，超过阈值触发培训与展示层调整。
- **单人纠正不进资产**：数据表与守卫语料的合并要求 ≥2 名审查人、≥2 个项目一致；单条纠正只进回归用例，不改规则。
- **纠正也有错**：triage 时 canUseForEval 与 canUseForTraining 分开；被后续纠正推翻的纠正自动降级为"争议样本"，不进基准。
- **资产版本进快照**：业务包快照哈希已覆盖 rules / bindings / clause package；把限值档案、守卫语料、案例库版本一并纳入，任何一次审查都能回答"当时用的是哪版"。
- **影子运行**：新版本资产先以影子模式跑同一节点，输出只进对比表不进 UI；一周后比对差异，人工抽查差异样本。
- **不改历史结论**：迭代只影响新审查；历史 AiRun 保持原样，回放结果单独存。

## 7. 实施步骤与工作量

| 步 | 内容 | 落点 | 估时 |
|---|---|---|---|
| 1 采集补全 | 采纳/驳回改写 ai_feedback；接通 B 线 human-decision 与 finding 级 accept/reject；证据链驳回必填原因；退回补正带 aiRunId 与 finding id；结论卡“补充发现”与“其实有依据”两个新入口；采集覆盖率指标 | P9 R1/R4、routes 13371/13432/13461/7368、review_opinions/ai_feedback 写入 | 2.5–3.5 天（端点多数已存在） |
| 2 分类与基准 | rootCause 七类；周度 triage 页面（FDE 控制台）；P8 H0 基准输出 §1 指标表；历史 117 次 AiRun 由维护者回填一轮纠正作为冷启动 | FdeConsole、scripts/experiments | 3 天 |
| 3 四层流水线 | 候选行生成、白名单候选与回放、案例库检索接入提示词、回归用例目录与 CI | libs/feedback/、review_grounding、build_review_prompt_parts、tests/regression | 5–6 天 |
| 4 治理 | 盲审抽样任务、影子运行开关、资产版本进快照、看板 | cron、business_pack 快照、前端看板 | 2–3 天 |

合计 12.5–15.5 人日。与优化计划的关系：步骤 1 并入 P9 R1，步骤 2 并入 P8 H0，步骤 3 的守卫白名单并入 P8 H3、案例库并入 P8 H5，步骤 4 并入 P7 探针与灰度。

## 8. 来源
- Human-in-the-loop 与 LLM-as-judge 校准：https://www.langchain.com/resources/llm-as-a-judge ；https://galileo.ai/blog/calibrate-llm-judge-human-annotations
- 黄金数据集持续维护：https://langfuse.com/resources/engineering/golden-dataset-evaluation ；https://www.getmaxim.ai/articles/building-a-golden-dataset-for-ai-evaluation-a-step-by-step-guide/
- 生产持续评估与影子评估：https://www.velsof.com/ai-automation/ai-agent-continuous-evaluation/ ；https://aws.amazon.com/blogs/machine-learning/evaluating-ai-agents-real-world-lessons-from-building-agentic-systems-at-amazon/
- 纠正转回归测试、错误分类：https://www.braintrust.dev/articles/best-human-in-the-loop-llm-evaluation-platforms-2026 ；https://arxiv.org/abs/2605.25226
- 案例推理与经验记忆：https://arxiv.org/abs/2504.06943
- 自动化偏差与橡皮图章：https://sloanreview.mit.edu/article/ai-explainability-how-to-avoid-rubber-stamping-recommendations/ ；https://www.techtarget.com/it-strategy/feature/Human-in-the-loop-shouldnt-rubber-stamp-decisions ；https://tianpan.co/blog/2026-04-15-human-in-the-loop-rubber-stamp
- 主动学习式文档审阅（Relativity Assisted Review）：https://help.relativity.com/PDFDownloads/Server2025_PDF/Relativity%20-%20Assisted%20Review%20Active%20Learning%20Guide.pdf
