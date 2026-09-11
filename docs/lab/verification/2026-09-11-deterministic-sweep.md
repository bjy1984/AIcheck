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
