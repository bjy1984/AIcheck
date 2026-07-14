# Tools 实现规划方案

> 方案依据：`tools规划.md`、`业务节点分析.md`、`业务疑问.md`，以及当前工程中的 `atomic_check_tool_bindings.yaml`、`runtime_tools.py`、`deterministic_tools.py` 和 `execution.py`。
>
> 本文是实现路线图，不替代 `tools规划.md` 的逐 atomicCheck 绑定清单。`tools规划.md` 应继续由业务包配置生成，不作为人工维护源。

## 1. 结论先行

### 1.1 2026-07-12 实施结果

本方案现已在当前工程完成第一轮落地：

- `tools规划.md` 中 61 个唯一 Tool 已全部进入 Runtime Tool Catalog，缺失 Tool 数量为 0。
- 173 条 atomicCheck Tool 链均可由固定执行器编译，无未注册 Tool；140 条标记为 `implemented`，33 条保留 `pilot_implemented`。
- 新增 10 个通用确定性 Tool，并为资质设计、焊接热处理、NDT、防腐安装、压力泄漏、材料组件等专业 Tool 提供安全执行实现。
- `run_rule_engine` 已接入固定 Tool Plan；强制 Tool 是否执行不再由 LLM 决定。
- 专业事实、证据或规则参数不完整时统一 fail-closed，返回 `failed`、`evidence_insufficient` 或 `not_applicable`，不能自动得到“符合”。
- R61 已升级为 `pressure-test-parameters-gbt20801-v2`，补入液压温度许用应力比、组成件上限、气压 1.33 倍和 90% 屈服上限、分级升压及保压检查；旧固定倍数规则已从 atomicCheck 和生成器源配置删除。
- 2026-07-14 编号迁移回归结果：938 passed、12 skipped；另有 4 个 Temporal/Outbox 测试因本地环境未安装 `temporalio` 在收集阶段排除。Tool 专项测试覆盖注册完整性、缺证、边界值、不适用、机构隔离、文件本体、抽样、版本日期、追溯以及压力试验安全规则。

以下事项仍保持试点或人工复核，不得理解为已经允许自动生产放行：TSG Z6002-2026 全量焊工资格代号、R60 未明确的表盘直径阈值、R62 全过程报告一致性，以及缺少正式 NB/T 47013.8-2025 原文支撑的 R64/R66/R67 专业规则。

以下为编号整理后的当前绑定基线：

- 已配置 173 条 `atomicCheck → requiredFacts → tools → parameters → outputSchema` 绑定，覆盖附件定义的 R01-R69。
- 绑定清单中共有 61 个唯一 Tool 名称，均已注册；专业能力是否达到生产放行要求仍按节点单独验收。
- 33 条绑定标记为 `pilot_implemented`，其余 140 条标记为 `implemented`。
- R61 的 `check_pressure_test_parameters` 使用了不完整的压力计算规则，修复前不得用于生产放行。
- R24、R60、R62 的试点实现也只覆盖有限场景，必须继续保持试点状态。
- R69 已按 `files/checklist.docx` 补录，但属于人工评价节点；Tool 只校验评价报告和证据完整性，`automatedDecisionAllowed=false`。

推荐采用“固定执行计划 + 确定性专业 Tool + LLM 解释与交互”的模式：

```text
业务节点
  → 固定 atomicCheck
  → 固定条款快照
  → 固定 requiredFacts
  → 固定 Tool 执行计划
  → 证据抽取和事实标准化
  → 适用性判断
  → 确定性业务计算/比较
  → 证据门禁
  → 节点结论聚合
  → LLM 生成可读审查摘要、补证建议和交互回复
```

LLM 不负责选择强制 Tool、不提供阈值或公式、不修改 Tool 结果，也不能将 `evidence_insufficient` 改写成“符合”。

## 2. 实现目标和边界

### 2.1 实现目标

1. 将 173 条 atomicCheck 绑定转换为可执行、可重复、可测试的 Tool 执行计划。
2. 将证据抽取、事实标准化、适用性判断、业务计算、证据门禁和结论聚合分层实现。
3. 每个判断均可追溯到输入文件版本、页码/坐标或原文、Tool 版本、规则版本和固定条款快照。
4. 同一输入、同一版本的执行结果必须一致，不依赖 LLM 的随机推理。
5. 证据缺失、冲突、低置信度、规则版本不确定或 Tool 异常时实行 fail-closed，不得自动判定符合。

### 2.2 不由 Tool 自动完成的事项

- 人工签发正式监检结论。
- 业务方尚未明确的专业口径，例如 R05 施工图审查见证材料的认定范围。
- 尚无正式有效标准原文支撑的判断，例如当前缺少正式 NB/T 47013.8-2025 原文支撑的部分判断。
- 联络单自动创建；当前只输出 `suggestedAction=issue_contact_notice`，记录为待实现。
- R69 的评价结果；Tool 只能汇总 R01-R68 结果并校验监检人员评价报告，不自动形成或覆盖评价结论。

## 3. 当前实现盘点

### 3.1 已有基础能力

| 能力 | 当前实现 | 结论 |
| --- | --- | --- |
| ReviewRun 固定条款快照 | `review_orchestrator/execution.py`、`clause_store` | 可复用 |
| Tool Catalog 和 Dispatcher | `review_orchestrator/runtime_tools.py` | 可复用，需改为注册表式扩展 |
| 确定性 Tool | `review_orchestrator/deterministic_tools.py` | 可复用接口，需拆包和升级结果协议 |
| Tool 白名单 | `execution.py` 中 `ALLOWED_AGENT_TOOLS` | 可复用，但不能继续手工维护多份名单 |
| Tool 调用审计 | `review_tool_calls` | 可复用，需保存版本、输入快照哈希和完整业务结果引用 |
| OCR 字段、表格、签章和证据定位 | `runtime_tools.py` | 已有适配器，需补齐资料类型 profile 和质量校验 |
| atomicCheck Tool 绑定 | `atomic_check_tool_bindings.yaml` | 作为执行计划来源，但须先修正已发现的业务误绑定 |

### 3.2 已实现且被绑定使用的 15 个 Tool

1. 证据/抽取类：`get_document_ocr_result`、`extract_document_fields`、`extract_table_records`、`recognize_signatures_and_seals`、`locate_evidence_fragment`、`extract_welder_certificate`、`validate_evidence_grounding`。
2. 通用判断类：`check_all_equal`、`check_date_covers`。
3. 设计许可类：`check_design_license_scope`。
4. 焊工资格类：`decode_welder_qualification`、`check_welder_work_coverage`。
5. 耐压试验类：`check_pressure_gauge_requirements`、`check_pressure_test_parameters`、`check_pressure_test_report_consistency`。

其中“实现”不等于“已具备生产放行能力”：

- R24 的资格项目解析仅支持少数代号形态，未完整覆盖 TSG Z6002-2026。
- R60 尚缺压力表位置、表盘直径来源及完整介质条件。
- R61 缺少液压温度许用应力比、气压上限、90% 屈服限制和分级升压规则，必须停用旧算法。
- R62 只做有限字段一致性比较，不能代表试验全过程合格。

### 3.3 当前结构性问题

1. `deterministic_tools.py` 是单文件注册和实现，继续增加 41 个 Tool 后会难以评审、测试和版本管理。
2. Tool 是否已实现以 atomicCheck 的 `implementationStatus` 表示，无法准确反映同一条绑定中“抽取 Tool 已实现、专业判断 Tool 未实现”的混合状态。
3. 当前 `deterministic-tool-result-v1` 缺少 `standardSnapshotHash`、`inputSnapshotHash`、直接证据引用、适用性结果和人工复核原因。
4. Tool 参数仍可能由调用方直接传入；安全阈值、公式和业务分支必须来自冻结规则配置，不能由 LLM 临时生成。
5. 当前编排器允许 Agent 调用 Tool，但合规审查的必调链不应依赖 LLM 自主选择，否则存在漏调和跳过门禁风险。

## 4. 目标实现架构

### 4.1 六层结构

| 层级 | 职责 | 典型输出 |
| --- | --- | --- |
| 1. Evidence Adapter | 获取 OCR、表格、签章、页面坐标和原文 | 原始候选事实、EvidenceRef |
| 2. Fact Builder | 资料类型识别、语义归一化、单位换算、实体关联 | 标准化 FactSnapshot |
| 3. Applicability Engine | 判断节点、原子项和专业分支是否适用 | applicable / not_applicable / unknown |
| 4. Domain Tool | 执行公式、范围覆盖、交叉比较、抽样算法等确定性判断 | passed / failed / evidence_insufficient |
| 5. Evidence Gate | 核验所有结论事实均有可靠证据且无冲突 | grounded / insufficient / conflicted |
| 6. Aggregator | 聚合 atomicCheck 和节点结论，生成固定结果 | AI结论、补证项、人工复核项 |

抽取层可以使用 OCR 或受控模型产生“候选事实”，但候选事实必须保留置信度和证据位置；业务公式与合规结论必须由确定性 Tool 执行。

### 4.2 固定执行而非 LLM 自由编排

新增 `AtomicCheckExecutor`，从发布时冻结的绑定生成执行 DAG：

1. 校验 atomicCheck、条款快照和 Tool 版本是否完整。
2. 根据 `requiredFacts` 获取项目事实和文档事实。
3. 对同一 ReviewRun 复用已生成的 FactSnapshot，避免重复 OCR 和重复归一化。
4. 执行适用性 Tool；不适用时停止该 atomicCheck 后续专业 Tool。
5. 执行绑定中规定的全部专业 Tool，不允许 LLM 删除、替换或改变顺序。
6. 对专业 Tool 使用的每个事实执行证据门禁。
7. 使用固定优先级聚合结果。
8. LLM 只读取结果对象，生成用户可读说明或发起补证交互。

### 4.3 结果聚合规则

节点结论按以下优先级聚合：

```text
存在 failed
  → 不符合
否则存在 tool_error / human_review_required / evidence_insufficient / applicability_unknown
  → 无法判定，待补证或人工确认
否则全部 not_applicable
  → 不适用
否则所有适用 atomicCheck 均 passed
  → 符合
```

个别业务原子项要求“文件缺失即判定不符合”时，在绑定中显式配置 `missingEvidencePolicy=failed`；未配置时不得把证据不足一律等同于不符合。

## 5. 统一数据和结果协议

### 5.1 Required Fact 定义

新增 `fact_definitions.yaml`，每个 requiredFact 至少定义：

- `factCode`、数据类型、单位、是否必填、单值/多值。
- 所属实体：项目、机构、人员、文件、管线、焊口、部件、批次或试验。
- 允许的数据来源和来源优先级。
- 归一化 profile，例如机构名称、标准编号、管道级别、材料牌号、日期和压力单位。
- 缺失、冲突和低置信度处理策略。

关键实体必须使用稳定主键：`documentVersionId`、`organizationId`、`personId`、`lineId`、`weldId`、`componentSerialNo`、`batchNo`。仅靠文本相似度不得直接合并两家机构或两个人员。

施工周期统一为：

```text
constructionEnd = max(plannedConstructionEnd, actualConstructionEnd)
```

并保留两个原始日期及其证据，不能只保存计算后的日期。

### 5.2 参数来源

绑定中的 `parameters` 只保存 profile 和策略标识；公式、阈值、枚举和适用条件保存到版本化 `tool_rule_profiles.yaml`：

```text
atomicCheck binding
  → ruleProfileId
  → frozen rule profile version
  → standard clause refs
```

LLM 只能提供事实候选，不能传入或覆盖压力倍数、抽样比例、资格覆盖范围、签字级数等规则参数。

### 5.3 `deterministic-tool-result-v2`

建议统一升级为：

```json
{
  "toolCallId": "RTC-...",
  "toolName": "evaluate_pressure_test",
  "toolVersion": "2.0.0",
  "outputSchema": "deterministic-tool-result-v2",
  "executionStatus": "succeeded",
  "result": "passed|failed|evidence_insufficient|not_applicable|human_review_required",
  "applicability": "applicable|not_applicable|unknown",
  "ruleVersion": "pressure-test@2.0.0",
  "standardSnapshotHash": "sha256:...",
  "inputSnapshotHash": "sha256:...",
  "facts": [],
  "checks": [],
  "evidenceRefs": [],
  "ruleRefs": [],
  "warnings": [],
  "humanReviewReasons": []
}
```

`executionStatus` 表示 Tool 是否成功运行；`result` 表示业务判断，两者不得混用。

## 6. 56 个 Tool 的实现分组

以下分组覆盖 `tools规划.md` 中全部 56 个唯一 Tool，不为复用而强行合并专业算法。

### 6.1 A 包：证据与事实获取（7 个）

| Tool | 状态 | 实现重点 |
| --- | --- | --- |
| `get_document_ocr_result` | 已有适配器 | 增加文件版本、解析版本和页级质量信号 |
| `extract_document_fields` | 已有适配器 | 按资料 profile 输出标准 Fact，而不是无约束字段字典 |
| `extract_table_records` | 已有适配器 | 增加行主键、跨页表格、单位和表头映射 |
| `recognize_signatures_and_seals` | 已有适配器 | 角色、姓名、印章名称、位置、置信度分开输出 |
| `locate_evidence_fragment` | 已有适配器 | 保证 `documentVersionId + pageNo + bbox/quotedText` 完整 |
| `extract_welder_certificate` | 受限试点 | 适配新旧证书和项目代号版本 |
| `validate_evidence_grounding` | 已实现 v1 | 升级冲突检测、事实逐项覆盖和 v2 结果协议 |

此包优先级为 P0，是所有专业 Tool 的共同前置依赖。

### 6.2 B 包：通用确定性判断（12 个）

| 状态 | Tool |
| --- | --- |
| 已有 | `check_all_equal`、`check_date_covers` |
| 待实现 | `check_required`、`check_scope_coverage`、`check_cross_document_match`、`check_signature_completeness`、`check_numeric_range`、`check_conditional_requirement`、`check_sampling_requirement`、`check_document_set_completeness`、`check_standard_version_active`、`check_traceability` |

实现要求：

- `check_required` 必须区分“目录中列出”和“文件本体已上传且可解析”。
- `check_cross_document_match` 支持字符串、日期、枚举、数值容差和集合等不同比较模式，不能全部使用字符串相等。
- `check_signature_completeness` 的三级/四级角色由适用性和 rule profile 决定。
- `check_sampling_requirement` 必须显式输入分母、批次/层级、抽样单位、最低数量和加倍抽查策略。
- `check_standard_version_active` 以审查日期和标准生效/废止区间判断，支持版本切换。
- `check_traceability` 应验证实体链连续性，而不仅检查字段非空。

### 6.3 C 包：资质、设计和施工策划（10 个）

| Tool | 主要节点 | 状态 |
| --- | --- | --- |
| `check_design_license_scope` | R01 | 受限试点 |
| `evaluate_installation_license_scope` | R02 | 待实现 |
| `evaluate_ndt_organization_scope` | R03 | 待实现 |
| `evaluate_design_approval_level` | R04、R06、R07、R22 | 待实现 |
| `evaluate_alternative_standard` | R10 | 待实现 |
| `evaluate_construction_plan` | R11 | 待实现 |
| `evaluate_design_special_requirements` | R09 | 待实现 |
| `evaluate_stress_analysis` | R63 | 待实现 |
| `evaluate_component_manufacturer_scope` | R12 | 待实现 |
| `evaluate_foreign_component` | R15 | 待实现 |

重点业务约束：

- R02 明确支持“A级锅炉安装资质”，施工周期覆盖使用计划结束和实际结束日期中较晚者。
- R03 按每家检测机构分别生成一次判断，不把多家机构合并成一个结果。
- R04/R06 将三级或四级签字的触发条件结构化，不能依赖 atomicCheck 的半句话。
- R05 的见证材料范围未确认前只输出人工确认，不能自动判定符合。

### 6.4 D 包：焊接与热处理（11 个）

| 状态 | Tool |
| --- | --- |
| 受限试点 | `decode_welder_qualification`、`check_welder_work_coverage` |
| 待实现 | `check_wps_pqr_coverage`、`evaluate_welding_consumable`、`evaluate_welding_consumable_control`、`evaluate_pipe_fit_up`、`evaluate_welding_process`、`evaluate_weld_appearance`、`evaluate_weld_repair`、`evaluate_heat_treatment`、`evaluate_heat_treatment_instruments` |

实现要求：

- TSG Z6002-2010 与 TSG Z6002-2026 按 2026-08-01 实施日期切换，解析器按规则版本运行。
- 焊工资格覆盖必须包括焊接方法、材料类别、位置、厚度、直径、填充金属和附加工艺因素。
- R32 先按焊口生成热处理适用性；R33、R34 必须继承同一份焊口级适用性事实。
- R34 硬度阈值按材料和标准表格确定，禁止使用统一 200HB/225HB 阈值。

### 6.5 E 包：无损检测（5 个）

| Tool | 主要节点 | 状态 |
| --- | --- | --- |
| `evaluate_ndt_quality_system` | R35 | 待实现 |
| `evaluate_ndt_process` | R36、R39、R40 | 待实现 |
| `evaluate_ndt_nonconformance` | R37 | 待实现 |
| `check_ndt_personnel_coverage` | R38 | 待实现 |
| `evaluate_rt_film` | R41、R42、R65 | 待实现 |

实现要求：

- R35-R42 按检测机构分组，共用 R36 的方法、比例、级别、时机和标准版本事实。
- R30 的施工单位目视检查比例和监检机构抽查比例使用两个独立分母。
- R41/R42 实现分层抽样、最低数量、代表性和加倍抽查，不能只比较一个总百分比。
- R64/R66/R67 在取得 NB/T 47013.8-2025 正式原文并重做条款绑定前不得完成生产验收。

### 6.6 F 包：防腐与安装（2 个专业 Tool）

| Tool | 主要节点 | 状态 |
| --- | --- | --- |
| `evaluate_corrosion_protection` | R43-R47、R50 | 待实现 |
| `evaluate_pipeline_installation` | R48-R55 | 待实现 |

这两个 Tool 名称保持不变，但内部按 profile 拆分策略模块，不使用一个超大 if/else：

- 防腐：材料批次、施工环境、层级/厚度、漏点检测、阴极保护、套管防腐。
- 安装：开挖、穿跨越、套管、绝缘支撑、预制、布管连接、补偿装置、支撑件。

R48/R49 先形成穿跨越结构事实，R50/R51 继承该适用性；不存在套管或绝缘结构时应返回 `not_applicable`，不能误判缺失。

### 6.7 G 包：安全附件、压力、泄漏、吹扫和阀门（8 个）

| Tool | 主要节点 | 状态 |
| --- | --- | --- |
| `evaluate_safety_accessory` | R56-R58 | 待实现 |
| `evaluate_pressure_test` | R59 | 待实现 |
| `check_pressure_gauge_requirements` | R60 | 受限试点 |
| `check_pressure_test_parameters` | R61 | 旧版必须停用并重写 |
| `check_pressure_test_report_consistency` | R62 | 受限试点 |
| `evaluate_leak_test` | R64、R66、R67 | 待实现且受标准原文阻塞 |
| `evaluate_blowing_cleaning` | R68 | 待实现 |
| `evaluate_valve_test` | R23 | 待实现 |

该包为最高安全优先级：

- R59-R67 必须共享同一管道系统边界和试验路线，不允许各节点独立猜测适用性。
- R61 重写后必须支持液压试验 S1/S2 温度许用应力比、气压试验上下限、90% 屈服限制和分级升压过程。
- R63-R65 的压力试验免除必须同时满足柔性分析、敏感性泄漏试验和 100% NDT，缺一不可。
- R56-R58 按每台设备的产品编号关联安装记录、校验/性能报告。
- R23 补齐 GB/T 20801.1-2025 7.2.4 适用性和阀门试验数量算法后再实现。

### 6.8 H 包：材料和产品组成件（1 个聚合 Tool）

| Tool | 主要节点 | 状态 |
| --- | --- | --- |
| `evaluate_material_component` | R13-R20 | 待实现 |

该 Tool 仅作为稳定入口，内部按监管分类调用独立策略：许可、制造监检、型式试验、出厂检验、质量证明、抽样复验、材料复验、境外牌号和新材料。不得把所有材料规则压缩为“文件是否存在”。

先由 R12 形成产品监管分类，再执行 R13-R20 分支；R16-R21 使用同一产品编号/炉批号/批次追溯链。R13、R15 条款误绑定修正前不得完成实现验收。

## 7. 工程代码落地方案

### 7.1 目录调整

保留 `review_orchestrator/runtime_tools.py` 作为兼容入口，新建专业 Tool 包：

```text
backend/libs/review_tools/
  contracts.py                 # Fact、EvidenceRef、ToolResult v2
  registry.py                  # 唯一 Tool 注册表和版本解析
  executor.py                  # AtomicCheckExecutor 和固定 DAG
  aggregation.py               # atomicCheck/节点结论聚合
  profiles.py                  # 冻结 rule profile 加载和校验
  evidence/
  common/
  licensing_design/
  welding/
  heat_treatment/
  ndt/
  corrosion/
  installation/
  pressure_test/
  leak_test/
  safety_accessory/
  materials/
  valves/
```

原有 `deterministic_tools.py` 先改为兼容转发层，待所有调用迁移后再删除，避免一次性破坏现有测试和接口。

### 7.2 配置文件

建议新增：

```text
backend/business_packs/engineering_inspection_v1/
  fact_definitions.yaml
  tool_definitions.yaml
  tool_rule_profiles.yaml
  atomic_check_tool_bindings.yaml    # 继续保留，作为固定执行链来源
```

`tool_definitions.yaml` 记录 Tool 级状态，而不是只使用绑定级状态：

```yaml
toolName: check_pressure_test_parameters
toolVersion: 2.0.0
status: disabled | planned | pilot | production
supportedRuleProfiles: []
inputSchema: pressure-test-input-v2
outputSchema: deterministic-tool-result-v2
owner: pressure_test_domain
```

发布校验必须拒绝以下情况：Tool 未注册、版本不存在、requiredFact 未定义、参数不属于 profile、标准条款快照缺失、生产节点引用 pilot/disabled Tool。

### 7.3 编排器改造

在 `execution.py` 的 `run_rule_engine` 阶段加入固定 Tool Plan：

1. `compile_atomic_check_plan(reviewRun)`。
2. `build_fact_snapshot(plan)`。
3. `execute_atomic_check_plan(plan, factSnapshot)`。
4. `aggregate_node_result(results)`。
5. 将聚合结果交给 LLM 生成审查摘要。

现有 `execute_agent_tool` 保留给对话中的补充检索和解释，但正式审查的必调 Tool 由服务器直接执行，不依赖 Agent 是否发起调用。

`ALLOWED_AGENT_TOOLS` 和 `RUNTIME_TOOL_DESCRIPTORS` 改为从唯一注册表生成，避免三处手工同步。

### 7.4 审计数据

每次 Tool 执行至少持久化：

- ReviewRun、节点、atomicCheck、Tool 名称和版本。
- 输入 FactSnapshot ID 和哈希。
- rule profile 版本、标准条款快照哈希和规则引用。
- 完整结果对象的存储引用及结果哈希。
- 输入/输出 EvidenceRef。
- 开始时间、结束时间、错误码、重试次数。
- 是否触发人工复核及原因。

严禁只保存 `compact_tool_output` 后丢弃专业 checks；摘要可用于列表展示，完整结果必须可审计读取。

## 8. 分阶段实施计划

### 阶段 0：安全止血和配置修正（P0，3-5 个工作日）

1. 将 R61 旧 `check_pressure_test_parameters@1.0.0` 标记为 `disabled_for_production`。
2. 生产执行遇到 disabled/planned/pilot Tool 时返回 `human_review_required`，不得默认跳过。
3. 完成 `业务节点分析.md` 第 79.5 节列出的 9 项 P0 配置修正。
4. 补充 NB/T 47013.8-2025 正式原文；未补齐前锁定 R64/R66/R67 为人工复核。
5. 重新生成 `tools规划.md`，保证它与修正后的 atomicCheck 和绑定一致。

验收门槛：已知不安全算法不再产生生产“符合”结论；P0 误绑定均有修订记录和专业复核人。

### 阶段 1：Tool 平台和通用 Tool（P0，1.5-2 周）

1. 实现 `review_tools` 包、唯一注册表、v2 协议和固定执行器。
2. 建立 FactDefinition、RuleProfile 和 EvidenceRef 数据模型。
3. 实现 B 包 10 个待实现通用判断 Tool。
4. 将现有 7 个证据 Tool 升级到统一 Fact/Evidence 输出。
5. 实现 Tool 结果完整持久化、缓存和按输入哈希幂等执行。

验收门槛：任选一个节点可在不依赖 LLM 选 Tool 的情况下完整执行；缺证、冲突、异常均不能自动通过。

### 阶段 2：耐压、泄漏和阀门安全包（P0，1.5-2 周）

优先重写 R59-R62，随后在正式标准原文可用后完成 R63-R68、R23。

验收门槛：所有压力边界、临界值、上下限、温度应力比、分级升压、抽样数量均有边界测试和专业人员签字确认；旧 R61 回归用例必须证明不会误放行。

### 阶段 3：焊接、热处理和无损检测（P0/P1，2-3 周）

1. 完成 D、E 包。
2. 建立焊口级事实模型和 R32-R34 共享适用性。
3. 建立机构级 NDT 上下文和 R35-R42 共享计划事实。
4. 支持 TSG Z6002 版本切换和分层抽样/加倍抽查。

验收门槛：不同机构、不同焊口、不同材料和不同标准版本不会串用事实；抽样分母和加倍规则可审计。

### 阶段 4：资质、设计和施工策划（P1，1.5-2 周）

完成 C 包，处理 R01-R11、R63、R12、R15、R22 的相关能力。R05 保持人工确认，直到业务方明确见证文件类型和签字角色。

验收门槛：机构逐家判断、文件本体缺失、三级/四级签字、标准有效期切换和施工周期口径均有正反用例。

### 阶段 5：防腐、安装和安全附件（P1，2 周）

完成 F 包及 `evaluate_safety_accessory`，优先处理 R43、R48/R53 已发现的条款问题和跨节点适用性继承。

验收门槛：条件不适用返回 `not_applicable`；材料批次、结构类型和设备编号可跨节点追溯。

### 阶段 6：材料和产品组成件（P1，2 周）

完成 R12-R22 的监管分类和材料追溯链，修正 R13/R15 后实现材料专业策略。

验收门槛：每个产品/批次先分类再分支判断；目录或质量证明中的文字不能替代缺失的文件本体；材料代用能触发设计、WPS/PQR 和竣工资料一致性复核。

### 阶段 7：全量双轨验证和投产（P0，1-2 周）

1. 选择真实历史项目进行“人工结论 vs Tool 结论”盲测。
2. 先旁路运行，只生成 AI 结论和差异，不影响正式状态。
3. 对全部差异进行专业复核，修正规则或事实抽取。
4. 达到验收指标后，按专业包逐步从 pilot 切换为 production，禁止一次性全量开启。

如由 2 名后端、1 名测试和持续投入的专业监检人员共同实施，整体预计约 10-14 周；正式标准原文缺失和业务疑问确认不计入纯开发工期。

## 9. 测试和安全验收

### 9.1 每个 Tool 的最低测试集

- 正常符合、不符合、证据缺失、证据冲突、低置信度、不适用。
- 等于阈值、略低于阈值、略高于阈值。
- 单位换算、日期边界、版本生效日和废止日。
- 多机构、多人员、多管线、多焊口、多产品、多批次隔离。
- Tool 异常、超时、重复执行和旧版本回放。

### 9.2 专业回归测试

- 每个 atomicCheck 至少 1 个符合和 1 个不符合的 golden case。
- P0 节点至少增加缺证和临界值用例。
- 从历史项目脱敏抽取真实复杂样本，不能只使用人工构造的理想 JSON。
- 对公式 Tool 使用性质测试或参数化测试覆盖数值空间。
- 对规则改版执行新旧版本并行回放，确保历史 ReviewRun 仍可按原快照复现。

### 9.3 上线硬门槛

1. P0 用例 100% 通过。
2. 不允许出现“Tool 未执行但节点符合”。
3. 不允许出现“证据门禁失败但节点符合”。
4. 相同快照重复执行结果完全一致。
5. 每个结论具有 Tool、规则、标准条款、事实和证据五类追溯信息。
6. 专业监检人员对该 Tool 的规则表、边界用例和不适用条件完成签字确认。

不宜用一个总体准确率掩盖安全风险。正式试运行阶段的首要指标应是“错误放行数为 0”，其次才是自动化覆盖率。

## 10. 任务拆分和责任边界

| 角色 | 主要责任 |
| --- | --- |
| 专业监检人员 | 确认条款、适用条件、公式、阈值、抽样规则和 golden case 预期 |
| 后端开发 | Fact/Tool 协议、专业算法、固定执行器、版本和审计持久化 |
| OCR/算法 | 字段/表格/签章抽取、证据坐标、置信度和冲突发现 |
| 测试 | 边界、回归、版本回放、历史项目双轨验证 |
| 产品/前端 | 展示 AI 结论、Tool 检查项、依据证据、补证和人工确认状态 |

专业人员未确认的规则不得由开发或 LLM自行补齐后标记为 production。

## 11. 每个 Tool 的完成定义

一个 Tool 只有同时满足以下条件，才可从 `planned/pilot` 变为 `production`：

1. 适用性、requiredFacts、公式/规则和条款引用已确认。
2. Input/Output JSON Schema 已发布且通过校验。
3. Tool 和 rule profile 均有独立版本。
4. 正、反、缺证、冲突、不适用和边界用例齐全。
5. 已注册到唯一 Tool Registry，绑定发布校验通过。
6. 完整结果和证据链可以从 ReviewRun 回放。
7. LLM 无法覆盖 Tool 参数或 Tool 结论。
8. 专业人员完成验收记录。

## 12. 建议立即开始的第一个开发任务

先执行阶段 0，不直接新增第 41 个缺失 Tool：

1. 禁止 R61 旧算法参与生产放行。
2. 新建 Tool Registry 和 v2 结果协议骨架。
3. 把 atomicCheck 绑定编译为服务器固定执行计划。
4. 修正 9 项 P0 业务配置并重新生成 `tools规划.md`。
5. 以 R59-R62 为首个安全闭环试点，完整实现“事实快照 → 适用性 → 压力计算 → 证据门禁 → AI结论 → 审计回放”。

完成这个闭环后，再按阶段 3-6 扩展专业包。这样既保留现有工程的 ReviewRun、Tool Gateway 和审计基础，也能尽快消除当前最危险的错误放行风险。
