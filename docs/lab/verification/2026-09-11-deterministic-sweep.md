# 确定性层全节点扫描（2026-09-11）

用户批准「先做①：全 69 个节点的离线扫描」。工具：`backend/scripts/sweep_deterministic_layer.py`，
按审查图前三步 `load_context → load_ocr_result → run_rule_engine` 重放确定性层，不调模型。

## 一、探针自己先错了两次

| 版本 | 错在哪 | 表现 | 怎么发现的 |
| --- | --- | --- | --- |
| v1 | review_run 没带 tenantId | 26 个节点「崩在 load_context」 | 看异常：`read_ndt_tables` 的身份断言 |
| v2 | 用 `dispatch_runtime_tool({}, …)` 当 tool_runner | 节点 24 扫出 0 项通过，生产实际 12 项 | 拿生产判过 passed 的 AC-R24-05 做保真度对照 |

v3 走生产图，AC-R24-05 判 passed，与生产一致。**比生产弱的探针会把「工具没数据」误报成「节点没结论」**，
所以先对齐再看数字。

## 二、基线（P-2026-ECD202）

| 指标 | 值 |
| --- | ---: |
| 有已发布规则的节点 | 68 / 69（缺 40） |
| 挂了文档的节点 | 32 / 69 |
| 原子核查项 | 192 |
| 通过 / 不符合 / 证据不足 | **1 / 0 / 191** |

证据不足的原因（全部可归因）：

| 原因 | 项数 |
| --- | ---: |
| `checkCount=0`（工具跑了但一项没检） | 94，其中 54 在没挂文档的节点上 |
| `requiredFields_not_configured` | 11 |
| `sampling_parameters_missing` | 11 |
| `R19_SEMANTIC_JUDGMENT_MISSING` | 8 |
| 其余具名事实缺口 | 61 |

## 三、扫描直接挖出来的三个缺陷

### 1. 跨工程串资料（已修，8 月 ~）

`_documents_by_version(state, projectId)` 对三个项目各自调用都返回 316 个版本（全库），
两两交集 316。第一个循环按 projectId 过滤，第二个循环（补非当前版本）把全库版本无条件
补进来。`pipeline_facts` 与 `design_facts` 是全工程扫描，拿到的于是是别的工程的资料。
`certificate_facts` 那处被运行级范围兜住。60 份 projectId 为空的文档原来出现在每个工程里。

### 2. 28 条假管线（已修）

追「为什么 pipelineGrades 永远是空的」，追到表格本身坏了：MinerU 把施工图的表头认错一行，
列名成了数据值（`['BOM A', '0.275', '设计压力', 'GC2', …]`），`设计压力` 键底下装的是别的列。
老写法任一字段有值就收，再给没管线号的行合成 id → 28 条管线号/级别/材质全 null、
designPressureMPa 为 2/4/6/…/16 等差数列的「管线」，喂给逐管线判定。

**缺结论只是查不出来，假事实会把人引到错的结论上。** 现在没管线号的行不产出。
改后四个项目管线数全部归零——那 28 条背后一条真的都没有。

### 3. 三个一声不吭的工具（已修）

挂了文档却出不了结论的节点里最常见的三个，原来只回「证据不足」：

| 工具 | 现在的原因 |
| --- | --- |
| `check_all_equal` 只拿到 1 个值 | `fewer_than_two_comparable_values` + `missingSources` 点名缺哪两个 |
| `check_design_license_scope` | `required_pipeline_grades_missing` |
| `check_date_covers` | `periodStart_and_periodEnd_missing` |

## 四、节点 1 的完整链条（典型样本）

设计许可证持证单位「广东政和工程有限公司」抽到了；设计文件的图签单位、设计章单位没抽到
→ `check_all_equal` 没东西可比。`licenseScopes: ["GB1","GB2","GC1"]` 抽到了；
`requiredPipelineGrades` 空——因为整个工程没有一条真管线（见三.2）。`validUntil: 2028-01-17`
抽到了；`periodStart/periodEnd` 空——因为**生产里所有项目的施工起止日期都是 null**。

三个缺口里两个是工程级基础事实，不是某份文档。

## 五、没做的、要决定的

- **表头重识别**：那张施工图的真表头就在第一行数据里（管路起点/管路终点/管路等级/介质名称/
  设计压力/设计温度/压力管道级别…）。列名像数据值、某一行全是短标签时，可以重新定表头。
  这是表格归一化层的活，做了才能让这个工程的管道特性表真正可读。
- **施工起止日期**：证书有效期覆盖全靠它，全库为空。要先确认有没有录入口。
- 37 个节点一份文档都没挂。

## 六、「表头重识别」做下去变成了「图签配对」

用户批准做表头重识别。看完整张表的 HTML 才发现它不是表头认错——是**单线图图签**：

    设计压力 | 0.275 | 操作压力 | 0.413 | 管路起点 | LP7103 | 管路等级 | M1E | 压力管道级别 | GC2 | BOM A
    设计温度 | 60°C  | 操作温度 | 常温  | 管路终点 | ST7102 | 介质名称 | …   | 损伤比例     | RT10%
    C-1 | 2025.04 | ID | 黄红描述 | DN | 数量 | 材质 | 说明        ← 材料表表头
    …BOM 行…

标签、值横着排，根本没有「正确的表头行」可以重识别。真实信息干净地摆在格子里，
整张表只描述**一条**管线。所以做的是 `r14_facts._extract_title_block_pipeline`：
按 cells（已解开 colspan）逐行走，标签后面那一格是它的值；一行至少两个已知标签才算图签行
（材料表表头只有「材质」一个，否则「说明」会变成材质的值）；≥3 个标签才认作图签；
身份用管线号，没有就用图上的起止点 `LP7103→ST7102`，都没有就不产出。

全库这个形状目前只有一张表，但单线图图签是通用画法，后面的工程都会带。

### 效果（生产数据，未部署前用挂载文件验证）

| 项目 | 改前 | 改后 |
| --- | --- | --- |
| P-2026-ECD202 管线 | 28 条假的 → 0 | **1 条真的**：LP7103→ST7102，GC2，0.275 MPa，60°C |
| 节点 1 `check_design_license_scope` | 证据不足（required=[]） | **passed**：GC1 覆盖 GC2 |
| 节点 2 `check_installation_license_scope` | 证据不足 | **passed**：GB2/GC2 覆盖 GC2 |
| 节点 1 AC-R01-04（读设计文件自述级别） | 证据不足 | 仍证据不足，`required_pipeline_grades_missing`——那条路径读的是 designDocument.pipelineGrades，没动 |

这是这个工程第一个从图纸上长出来的确定性结论。

## 七、证书节点从结构上不可能通过——两道墙，都拆了

图签配对让节点 1/2 的许可范围工具判出 passed 之后，原子项仍是证据不足。追下去是两道墙：

### 墙一：证书事实从没有 judgment

`execution.load_ocr_result` 把 `businessFacts["judgment"]["claimedFacts"]` 当 evidenceFacts。
焊材类构建器产这个，证书类（节点 1/2/3/24/38）不产。于是 `validate_evidence_grounding`
永远 factCount=0，锚定门一票否决，业务工具 passed 也翻不过来。

`certificate_facts` 现在产 judgment：每条证书一条 claimedFact（值取证书编号），
证据带由位置与引文决定的 `evidenceRefId`（同一处两次抽到得同一个 id），
`_field_values` / `_evidence` / `_locate_text` 把原来一路丢掉的 confidence 传下来。
`merge_certificate_facts` 对 judgment 做列表拼接，不覆盖节点 24 焊工 builder 已有的。

### 墙二：引擎没给分被当成零分

补上 judgment 之后，grounding 仍判 `fact_1_confidence` 不过——因为 confidence 是 0.0。
量了全库：

| (sourceEngine, extractionMethod) | 字段数 | 0.0 占 | ≥0.75 占 |
| --- | ---: | ---: | ---: |
| `mineru_vlm` / `profile_heuristic` | **376** | **376** | 0 |
| — / `scan_ocr_import` | 155 | 0 | 76 |
| `mineru_vlm` / 焊工证工具 | 42 | 0 | 42 |
| `pp_ocr_v6` | 13 | 0 | 13 |

MinerU 的 VLM 通道逐片不给分，适配层写 0.0 并在 `quality.reasons` 里标
`provider_confidence_unavailable`（生产 176 份解析结果带这个标）。一整份读对了的许可证
（TS1844171-2028、广东政和工程有限公司、GB1/GB2、2028-01-17）五个字段全 0.0，
不是「低置信度」，是「没有分数」。

**这个口径项目早就定过**：`repository.py` 给 `extracted_fields.reviewStatus` 的是三态
（`libs/field_confidence.field_review_status`，「置信度未知 ≠ 低置信度」，注释原话
「既不冒充已确认，也不诬告识别质量」）。只是标记没传到 `parse_result.fields[]`，
grounding 又只做数字比较。

`validate_evidence_grounding` 现在与之对齐：事实带 `confidenceUnavailable` 时，置信度检查
记作 `unscored` 而不是不过；位置齐、引文在、无冲突 → `human_review_required`
（reason `provider_confidence_unavailable`）；有分而分低的照旧证据不足。

### 聚合器顺带修的一处

`aggregate_tool_results` 原来把 `human_review_required` 排在 `evidence_insufficient` 前，
以前只有业务工具会发它，没事；锚定门也发之后，节点 1 实测「比不了 / 缺施工日期 / 缺级别」
的原子项全被抬成「请人判断」。现在锚定门的结果单列：只在业务工具全部通过时，
它才有资格把 passed 降成 human_review_required；业务说不清的还是说不清；
`grounding evidence_insufficient` 一票否决的既有口径不动。

### 效果（生产数据，未部署前挂载验证）

| 原子项 | 业务工具 | 锚定门 | 原子项判定 |
| --- | --- | --- | --- |
| AC-R01-02 设计许可范围 | passed（GC1 ⊇ GC2） | 没分 | **human_review_required** |
| AC-R02-01 安装许可范围 | passed（GB2/GC2 ⊇ GC2） | 没分 | **human_review_required** |
| AC-R01-05 / AC-R02-04 纯锚定门 | — | 没分 | human_review_required |
| AC-R01-01 图签单位一致性 | 比不了（设计文件图签单位没抽到） | 没分 | evidence_insufficient |
| AC-R01-03 / AC-R02-02/03 有效期覆盖 | 缺施工起止日期 | 没分 | evidence_insufficient |

节点 1、2 的总判定从 evidence_insufficient 变成 human_review_required：
「许可范围覆盖了，请人核对引文」——这是这两个节点第一次给出不是「证据不足」的话。
