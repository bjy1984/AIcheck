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

## 八、部署后的基线，以及计划第 1、2 项

墙一墙二拆掉并部署（8d0e4621）后重扫 P-2026-ECD202：

| | 改前 | 现在 |
| --- | --- | --- |
| passed / human_review_required / evidence_insufficient | 1 / 0 / 191 | **0 / 7 / 185** |
| `checkCount=0` | 94 | 80 |
| 出非「证据不足」结论的节点 | 24 | **1、2、3、24、38**（全部证书节点） |

passed 从 1 变 0 不是退步：那 1 项是节点 24 的纯锚定门（AC-R24-05），焊工证字段有分（0.78）
但同一原子项现在按三态口径带着未评分事实一起判，落到 human_review_required。

### 计划第 1 项：施工起止日期（已做）

不是没人填，是 API 不接、界面没口。现在：
- `libs/project_dates.py`：只收 ISO 日期或空，写坏的拒绝（落一个「2028-1-17」进去按字符串比就错）；
  起点晚于终点拒绝；创建与更新都走它。routes.py 因此 +10 行，基线随本次提交重冻。
- 管理台新建向导与编辑对话框各加「施工开始日期 / 计划完工日期」两个日期选择器（ISO 出参）。
- `check_date_covers` 读的就是这两个键；填上之后 AC-R01-03、AC-R02-02/03 才有得判。

### 计划第 2 项：设计文件的图签单位与设计章单位（已做）

AC-R01-01 比三处：许可证持证单位 / 图签设计单位 / 设计章单位。后两处**全库没有任何地方产出**，
执行器只读不写。数据其实在手上：施工图首页「项目名称」字段开头就是
`广东政和工程有限公司GEM-HORSE ENGINEERING CO.,LTD(原…) 资质等级…`，seals[] 第 1/3/4 页都是
`广东政和工程有限公司`；许可证上的章是「广东省市场监督管理局」（发证机关，按后缀筛掉）。

新增 `design_org_facts.build_design_org_facts`，从节点 1 的 `merge_certificate_facts` 挂入
（不动有棘轮的 execution.py），两条事实带证据并进 judgment。

生产数据挂载验证：**AC-R01-01 check_all_equal → passed**（三处同名），原子项按三态落到
human_review_required；evidenceFacts 1 → 3。

## 九、计划第 3 项：公示平台进事实链（已做，平台今晚不通）

`search_cnse_persons` 在 10 个节点的工具清单里、54 次运行零次调用——它只在模型可选的工具表上，
从没进过事实链。新增 `certificate_platform_verify.verify_certificate_records`，从
`build_certificate_facts` 去重后接入：

| 证书类型 | 查什么 | 核得上时 |
| --- | --- | --- |
| 设计/安装/检测机构许可证（TS1234567-2028） | 按编号直查 → `verification_from_license_record`（与 R12 人工核验记录同形） | 有效期、许可范围用平台登记补/校，挂一条 confidence=1.0 的证据 |
| 焊工证 / 检测人员证（证件编号=身份证） | 四步取全部证书 licList | 现行焊工项目代号替换 OCR 坏码，有效期取最早到期的现行项目 |

边界：平台失败一律软失败（保留 OCR、记 platformError，从不抛）；同一编号 24 小时只查一次
（`state["cnse_lookup_cache"]`，错误缓 1 小时）；`AICHECK_CERT_PLATFORM_VERIFY=off` 与
`run["replay"]` 不碰网；测试套件在 conftest 默认关（一条只造了许可证字段的用例曾在容器里真查到
TS1844171-2028，拿回 1.0 证据把「引擎没给分」的断言掀翻）。只拿到首条记录（licList 没取到）
时不改写——李卫伍那次平台排第一的是起重机指挥。

**生产实测（2026-09-12 02:25）**：四次查询全失败——两条许可证 `CnseRequestError`
（取验证码就超时），两条焊工证一条滑块匹配 0.467<0.50、一条同样超时。从部署容器直接
`httpx.get("https://cnse.e-cqs.cn/info-pub/pub")` 也是 TLS 握手超时，**不是本次代码的问题，是
这台服务器今晚到平台的链路**（09-05/06 同一容器查询成功）。软失败按设计工作：事实原样保留，
节点 1/2/24 的判定与接线前一致。错误缓存 1 小时，复测前要么等，要么清 `cnse_lookup_cache`。

## 十、计划第 4 项：人工核对写回事实（已做）

「需人工判断」是终点还是中转，取决于人核过之后系统记不记得。现在记得：

- 后端：`fact_corrections` 打补丁时字段 `confidence=1.0`、`confidenceUnavailable=False`
  （`review_input_data`）；证书证据带 `fieldName/humanCorrected`，judgment 的 claimedFacts 带
  `fields[]`（fieldName/documentVersionId/documentId/quotedText/humanCorrected）；grounding 判
  unscored 时把 `claimedFacts` 透传，`output_contract.atomic_check_outcomes` 汇成
  `unscoredFacts`。测试：`tests/test_human_confirmed_facts_score.py`（两条都核过 → grounding 通过）。
- 前端：逐项核查里每条「引擎没给分」的事实按字段列出「核对无误：<字段名>」，点击 →
  `ocr-fields` 找到抽取字段 → `fact-corrections` 以原值写一条（reason「人工核对无误」）→ 重载。
  已确认过的字段显示「已人工确认」。（`WorkbenchAiReviewPanel.vue` + `aiFindingFeedback.handleConfirmFact`）
- 口径：只落「人看过引文、抽取值没错」这一件事，不改值；改值仍走原来的字段修正入口。
  下次同节点复核，核过的字段有分，「需人工判断」才能变「通过」。

## 十一、计划第 5 项：七个有资料项目的节点 × 项目矩阵（部署 c620fc56 后）

扫描方式同第四节（`sweep_deterministic_layer.py`，回放生产图步骤，不调 LLM，
`AICHECK_CERT_PLATFORM_VERIFY=off` 以免 69×7 次查询把平台打挂）。每格 `通过/需人工/证据不足`。
七个项目 = 全库文档数 ≥ 8 的项目；「五个真实项目」之外多带了 GDLNG/HDCP 两个演示项目，一并列出。

| 项目 | 有结论节点 | passed | human_review | insufficient | 卡住 |
|---|---|---|---|---|---|
| P-2026-6B15AE 测试项目4 | 68 | 1 | 1 | 190 | 节点 40 无规则 |
| P-2026-7F7270 測試項目5 | 68 | 0 | 2 | 187 | 同 |
| P-2026-ECD202 测试项目3 | 68 | 0 | 8 | 184 | 同 |
| P-2026-GDLNG-002 | 68 | 5 | 1 | 186 | 同 |
| P-2026-HDCP-001 | 68 | 2 | 1 | 189 | 同 |
| P-TEST-OCR-001 珠海海瑞德 | 68 | 10 | 1 | 181 | 同 |
| P-TEST-OCR-002 珠海化工区 | 68 | 13 | 0 | 179 | 同 |

只列有差异的节点（其余 4–69 号节点七个项目全是「证据不足」，且行行相同——那是没挂文档、
规则跑空 `checkCount=0`，不是项目差异）：

| 节点 | 6B15AE | 7F7270 | ECD202 | GDLNG | HDCP | OCR-001 | OCR-002 |
|---|---|---|---|---|---|---|---|
| 1 设计资质 | 0/1/4 | 0/1/4 | 0/3/2 | 0/1/4 | 0/0/5 | 1/0/4 | 1/0/4 |
| 2 安装资质 | 0/0/4 | 0/1/2 | 0/2/2 | 0/0/4 | 0/0/4 | 1/0/3 | 1/0/3 |
| 3 检测资质 | 0/0/4 | 0/0/4 | 0/1/3 | 0/0/4 | 0/0/4 | 0/1/3 | 1/0/3 |
| 12 | 0/0/2 | 0/0/2 | 0/0/2 | 0/0/2 | 0/0/2 | 1/0/1 | 1/0/1 |
| 13 | 0/0/3 | 0/0/3 | 0/0/3 | 0/0/3 | 0/0/3 | 0/0/3 | 1/0/2 |
| 16 | 0/0/7 | 0/0/5 | 0/0/7 | 0/0/7 | 1/0/6 | 1/0/6 | 1/0/6 |
| 21 | 0/0/2 | 0/0/2 | 0/0/2 | 0/0/2 | 0/0/2 | 0/0/2 | 1/0/1 |
| 23 | 0/0/3 | 0/0/3 | 0/0/3 | 1/0/2 | 0/0/3 | 0/0/3 | 0/0/3 |
| 24 焊工证 | 0/0/5 | 0/0/5 | 0/1/4 | 1/0/4 | 0/1/4 | 1/0/4 | 1/0/4 |
| 25 WPS/PQR | 0/0/3 | 0/0/3 | 0/0/3 | 1/0/2 | 0/0/3 | 1/0/2 | 1/0/2 |
| 26 焊材 | 0/0/3 | 0/0/3 | 0/0/3 | 1/0/2 | 0/0/3 | 1/0/2 | 1/0/2 |
| 29 | 1/0/1 | 0/0/2 | 0/0/2 | 1/0/1 | 1/0/1 | 1/0/1 | 1/0/1 |
| 32 | 0/0/2 | 0/0/2 | 0/0/2 | 0/0/2 | 0/0/2 | 1/0/1 | 1/0/1 |
| 38 | 0/0/2 | 0/0/2 | 0/1/1 | 0/0/2 | 0/0/2 | 1/0/1 | 1/0/1 |
| 40 | 无规则 ×7 | | | | | | |

证据不足原因合计（七项目 1296 项）：`checkCount=0` 572（44%，规则跑了但没挂到可检的文档）；
`requiredFields_not_configured` 77；`sampling_parameters_missing` 77；`R19_SEMANTIC_JUDGMENT_MISSING` 56；
`validUntil_and_periodStart_and_periodEnd_missing` 36（施工起止日期，待办 11）；`r15_design_items_missing` 35；
工具没说原因 29；`required_signature_roles_missing` 28；`pwht_weld_items_missing` 28；
`welder_qualifications_and_welding_work_records_missing` 24；`required_document_types_missing` 21；`condition_missing` 21。

读法：
- ECD202 的 8 项「需人工判断」是本轮改动的直接结果（节点 1/2/3/24/38 证书事实有了、只差置信度）；
  OCR-001/002 之所以有 10/13 项通过，是它们的证书走的是给分的 OCR 通道，不是规则更松。
- 七个项目 44% 的证据不足是同一件事：节点没挂文档。这不是引擎问题，是待办 9/12 那类资料问题。
- 节点 40 七个项目一律「无规则」，仍等 RULE-NDT 发布决定（待办 10）。

明细 JSON：本机 scratchpad `sweep/<projectId>.json`（未入库）。

## 十二、计划第 6 项：45 项「历史残留」的真实账

按「最新一次运行的原子项是否属于该节点当前已发布规则」重新数：**只有 2 条最新运行跑错规则**——
P-TEST-OCR-001 节点 35（跑的是 AC-R23-*）和 E2E 测试项目的节点 36。原先数出的 45 项分布在
HDCP-001 节点 24/29（08-29 的 7+8 次旧运行）、ECD202 节点 29/32/38（09-03）等**已被更新运行覆盖**的
老记录里，重跑它们不会改变任何界面上的结论，也不值得花模型费。

做了的：`POST /review-runs/RRUN-280D43C098/rerun`（监检角色、口令读服务器 secrets）→
子运行 `RRUN-REPLAY-C5F6247D`，原子项已是 AC-R35-01/02（两项证据不足，节点 35 没挂文档）。
E2E 项目不动。第一次发请求时容器正被扫描占满 CPU，60 秒超时没建出子运行；等扫描结束、超时放宽到
300 秒后一次成功——同容器里别叠着跑重活。

## 十三、公示平台复测（2026-09-12 04:40，部署 c620fc56 后）

平台恢复可达（容器内 `GET /info-pub/pub` 302，14 秒）。对 ECD202 节点 1/24 真查三条：

| 证书 | 查询 | 结果 |
|---|---|---|
| 焊工 姜军 511621198504208836 | 身份证 → licList | **verified_match**：OCR 坏码 `CTAF-Fe II-6G…` 被平台原文 `GTAW-FEII-6G-3/57-FEFS-02/11/12` / `SMAW-FEII-6G(K)-9/57-FEF3J` 替换，有效期取平台 2029-09-30，`sources.qualificationCodes=cnse_platform` |
| 设计许可证 TS1844171-2028 | 编号直查 | unable_to_verify：`pubQueryVCodeData.json` 取验证码失败（平台慢，20/60 秒超时） |
| 焊工 410521198609180550 | 身份证 | 同上 |

结论：接线在真实数据上成立——核得上的那条把节点 24 最大的坏数据源（OCR 认坏的项目代号）换成了登记原文；
核不上的软失败按设计保留 OCR。剩下的是平台侧的吞吐：验证码接口今晚 2/3 超时，错误缓存 1 小时后自动重试。

## 十四、浏览器实测（2026-09-12，部署 c620fc56 → 71a7e6a7 → 本轮）

用监检账号登录线上工作台，对 P-2026-ECD202 节点 1 发起真实节点复核（`ai-recheck`，
AIRUN-1-1EF3981C → RRUN-F53919B502），在「逐项核查」里看到的与随即修掉的：

| 看到的 | 根因 | 修法 |
|---|---|---|
| 两条设计单位事实渲染出来了，但没有「核对无误」按钮 | design-org claimedFacts 没有 `fields[]` | 图签带来源字段名（项目名称）与 documentId；片段来源没有字段名，如实留空 |
| 同两条事实在全部 5 个原子项下各列一遍 | grounding 挂在节点每个原子项上 | `unscoredFacts` 只挂在「需人工判断」——人工确认只在这种结论上能改判 |
| 设计章的事实引用了图签那条证据 | 按「值出现在引文里」配对，设计章名是图签引文子串 | 每处单位名各自绑定自己那条证据 |
| 设计章不是抽取字段，永远核不了 → 节点 1 出不去「需人工判断」 | 只有 fieldId 一条确认路径 | 补 `factPath` 确认：claimedFact 带 factPath，界面给事实级按钮，写 fact_corrections(factPath)，下次构建该证据 1.0 |
| `factPath` 到前端是空串 | grounding 透传只带 5 个键 | 透传带 factPath |

第二次复核（AIRUN-1-3C43D630 → RRUN-13813C34FD）：AC-R01-01/02/05 需人工判断且各带
「图签设计单位 ← 项目名称@DOC-A8E48BB4」与「设计章单位（按事实路径确认）」；03 不符合、04 证据不足不再挂事实。

**同轮新增：每个原子项都列依据与证据**（用户要求「AI 审核通过/未通过/需人工都要清晰列出并罗列证据」）：
- `validate_evidence_grounding` 不再只在没分时回传事实：每条事实带 `scored` 与 `evidence[]`
  （文件·页·引文·来源·置信度·是否人工确认），从 evidenceRefs 按 id 解析。
- `atomic_check_outcomes` 每项加 `checks[]`（业务工具逐条检查：码/通过否/期望/实际）、
  `reason`（不足原因）、`facts[]`（事实+证据原文）。
- 界面：每项下先「原因」，再 ✓/✗/－ 逐条检查（码翻成人话，`friendlyCheckCode`），再按事实列引文
  （「TS1844171-2028」设计资质.png · 第 1 页 / 公示平台登记 / 已人工确认）。
  原因码表 `checkReasonLabels`（七项目扫描里出现过的全部 25 个码），认不出的按 `_missing/_not_configured` 后缀兜底。

## 十五、端到端实测：人工核对写回真的能把「需人工判断」变成「通过」

2026-09-12 在线上工作台（监检账号）走完整条链，节点 P-2026-ECD202 / 1：

| 步 | 动作 | 结果 |
|---|---|---|
| 1 | 发起节点复核（ai-recheck） | AC-R01-01/02/05 需人工判断（引擎没给分）、03 不符合、04 证据不足 |
| 2 | 点「核对无误：项目名称」 | `fact_corrections` 落 FCOR-AF52C90A46（fieldId 路径） |
| 3 | 再复核 | 图签设计单位 scored=true、humanCorrected=true，未给分只剩设计章 |
| 4 | 点「核对无误」（设计章，无抽取字段） | 落 FCOR-81B3801730（factPath 路径） |
| 5 | 再复核 | **AC-R01-01/02/05 → 通过**；界面「共 5 项 不符合 1、证据不足 1、通过 3」 |

两条修正随后已撤销（`/fact-corrections/{id}/revoke`）：它们是自动化代点的，不能冒充监检人员的
真实核对留在反馈语料里。撤销后节点回到「需人工判断」，这是诚实的状态；真正要它变「通过」，
得监检人员自己点这两下。

同轮实测发现并修掉的界面问题：
- 点完「核对无误」界面毫无变化（本次留痕不会因这条确认改写，要下次复核才计分）→
  本地标「已记录，下次复核生效」，避免反复点。
- 逐条检查的「实际 / 要求」换行后贴到行首 → 靠右对齐。
- 公示平台这次核到了许可证：证据里多一条「平台登记单位…登记状态：active」，来源标「公示平台登记」。
