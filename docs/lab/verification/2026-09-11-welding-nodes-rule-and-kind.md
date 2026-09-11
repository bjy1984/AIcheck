# 焊接节点：规则错挂与文档分类错判（2026-09-11）

起因是用户「现在重点优化焊接节点」。第一轮我读错了函数——`material_facts.material_document_kind`
只服务 R16/R17/R18，焊接段用的是 `r24_r34_facts._document_kind`，那里本来就有 19 条焊接路由。
据此得出的「焊接节点没有分类器、全军覆没」是错的，已作废。下面全部是按生产数据重测的结论。

## 一、量到什么

生产 `review_runs` 里节点 24–34 共 67 个运行：

| 来源 | 运行数 | 带输入文档 | 有工具调用 |
| --- | --- | --- | --- |
| 节点级复核 | 29 | 29 | 24 |
| 一键分析（RRUN-PA-*） | 38 | 0 | 0 |

一键分析这条路不带 `inputDocumentVersionIds`、不取规则、不跑确定性工具——用户看到的
节点 25「3 条发现全部待人工确认、无确定性核验」就是这么来的，不是焊接工具坏了。

## 二、三个真缺陷

### 1. 节点 28 跑的是焊工资格证规则

`current_published_rule_for_node(28)` 取到 `RULE-WELDER-202606`（Welder-Qualification-B-v2.1，
正文讲 TSG Z6002 持证项目覆盖）。原因两层：

- 老种子 `CORE_RULE_VERSIONS` 里这条规则声明 `nodeIds: [24, 25, 27, 28]`；
- 生产库里**根本没有** `RULE-ENG-INSP-R28`（管道组对）。业务包 rules.yaml 声明了它，
  2026-09-03 的对齐脚本 `plan_rule_version_reconciliation` 对「库里没有」的记录直接 `continue`，
  静默跳过了这条缺口。

后果：`build_r28_business_facts` 与 `evaluate_pipe_fit_up` 永远够不着，节点 28 的管道组对
从来没有按自己的规则审过。

### 2. 节点 25 / 27 是并列，靠列表顺序决胜

`RULE-WELDER-202606` 与 `RULE-ENG-INSP-R25`/`R27` 的 `publishedAt` 都是 `2026-06-26 09:12:00`，
`select_published_rule` 按 (项目内, publishedAt) 排序，并列时只看入参顺序。实测眼下侥幸取到了
对的规则，但换个读取顺序就会翻。

### 3. 焊接文档分类：把「提到过」当成「就是」

`_document_kind` 拿正文前 4000 字做子串匹配，四类错判（每条都有真实样本）：

| 文件 | 判成 | 应为 | 原因 |
| --- | --- | --- | --- |
| 9.1金辉焊接工艺评定20.pdf | `wps` | `wps_pqr` | 裸标记 `"wps"` 命中正文「预焊接规程编号 pWPS-2023-01」 |
| 焊接工艺评定报告.pdf | `wps` | `wps_pqr` | 同上 |
| 不锈钢氩弧焊HP022-2024焊接工艺评定.pdf | `None` | `wps_pqr` | 标记要求整串「焊接工艺评定报告」，这份标题没有「报告」 |
| 焊工名册.xlsx / 焊工清单.docx | `None` | `welder_certificate` | `documents.materialTypeCode` 够不着（解析结果自己那份 290 份全空） |
| TSGZ6002-2010《焊接人员考核细则》.pdf | `wps` | `None` | 国家标准正文被当成本工程施工证据 |
| GB 50236-2011 / JB∕T 3223-2017 / NBT 47018-2017 | `wps_pqr` / 焊材质量证明 | `None` | 同上，生产有 60 份 `standard_reference` |
| 9.2.焊接工艺卡.pdf | `pqr` | `wps` | 正文引用「焊接工艺评定报告编号 HP/P-2023-01」 |
| 射线检测施工方案(1).pdf ×5 | `weld_appearance_record` | `None` | 正文提到「外观检查记录」 |

因为评定报告被判成 `wps`，`NODE_CONFIG` 要的 `pqrItems`（节点 25/29）与
`qualificationReports`（节点 32）**在所有项目上恒为 0**，`check_wps_pqr_coverage`
从来没有真正比对过 WPS 与 PQR。

## 三、改了什么

- `libs/db/seed.py`：`RULE-WELDER-202606.nodeIds` → `[24]`。
- `libs/rule_scope.py`：选规则加第三决胜项「覆盖节点少者优先」，第四项规则 id 保证可复现；
  「发布时间新」仍然压过它。
- `scripts/reconcile_rule_versions_with_seed.py`：新增 `plan_missing_rule_versions` /
  `apply_missing_rule_versions`，补写库里整条缺失的种子规则（规则只会被置为「已下线」、
  没有删除入口，所以「库里没有」只可能是从未写入）。
- `libs/review_orchestrator/r24_r34_facts.py` 分类器重写：
  - 匹配窗口从正文前 4000 字收到「文档标注 + 文件名 + 正文前 600 字」；
  - 标记分两层，会出现在目录/核查表里的主题词（「焊接工艺评定」「焊工名册」「施工图」）
    只认文件名与文档标注，不认正文；
  - `materialTypeCode = standard_reference` 直接不判（国家标准不是本工程证据）；
  - 「X编号」形式的命中视为引用而非自述；
  - 新增组合路由：同时出现「焊接工艺评定」与「预焊接 / pWPS」→ `wps_pqr`，
    这类文件既是 WPS 也是 PQR 的来源。

## 四、改完量到什么

290 份生产解析结果重跑分类，56 份判定变化，焊接类没有新增误报：

| kind | 改前 | 改后 |
| --- | --- | --- |
| `wps` | 13 | 0 |
| `pqr` | 1 | 3 |
| `wps_pqr` | 5 | 9 |
| `weld_appearance_record` | 7 | 0 |
| `welding_consumable_certificate` | 3 | 1 |
| `welder_certificate` | 22 | 21 |
| `None` | 208 | 216 |

`wps` 归零、`weld_appearance_record` 归零都是去掉误报：那 13 份里没有一份是焊接作业指导书
（施工方案、技术比较、TSG 标准、评定报告），7 份「焊缝外观记录」全是射线检测方案与规范正文。
真的 WPS 内容在 `wps_pqr` 里，节点 25 的 `wpsItems` 不受影响。

事实构建器在真实项目上的变化：

| 节点 | 事实项 | 改前 | 改后 |
| --- | --- | --- | --- |
| 25（P-2026-ECD202） | pqrItems | 0 | 19 |
| 25（P-2026-7F7270） | pqrItems | 0 | 33 |
| 29（P-2026-ECD202） | pqrItems | 0 | 19 |
| 32（P-2026-7F7270） | qualificationReports | 0 | 33 |
| 32（P-2026-ECD202） | qualificationReports | 0 | 19 |

## 五、量到但**不是**代码问题的

- `workItems` / `weldingRecords` 在所有项目上仍然是 0：全库没有任何一份文档是
  焊接施工记录或管线汇总表（文件名、正文、物料类型三路都查过）。节点 24/25/29/32/33/34
  要的「实际施焊参数」没有来源，这是要用户补资料，不是分类器的事。
- 节点 26 的 `qualityCertificates`（焊材质量证明书）同样是 0：之前那 3 份是
  JB∕T 3223 与 NB/T 47018 两份**标准正文**被误判填进去的。
- **节点 40 没有任何已发布规则**：种子里 `R40` 被 `RULE-NDT-202606` 覆盖，而后者是「待发布」。
  这不在焊接段，但是同一类缺口，需要产品决定 RULE-NDT 是否该发布。

## 六、没做的

- 一键分析不跑确定性工具是设计还是缺陷，没有定论，本轮没动。
- 知识条款 `KC-TSG-Z6002-3.2`（焊工资格覆盖要求）的 `scope.nodeIds` 同样是 `[24, 25, 27, 28]`，
  检索层面把焊工资格条款喂给节点 25/27/28。属同一类过度声明，改动会影响检索结果，另议。

## 七、生产对齐结果（2026-09-11 16:54 已落库）

`reconcile_rule_versions_with_seed.py --apply`：替换 1 条、补写 3 条。
原记录备份 `/app/output/ops/rule_versions_backup_2026-09-11T165437.json`。

| 节点 | 改前取到的规则 | 改后 |
| --- | --- | --- |
| 12 | 没有已发布规则 | RULE-ENG-INSP-R12 压力管道元件及安全附件制造单位的许可资质 |
| 24 | RULE-WELDER-202606（声明 4 个节点） | RULE-WELDER-202606（只声明节点 24） |
| 25 | RULE-ENG-INSP-R25（并列侥幸） | RULE-ENG-INSP-R25（唯一候选） |
| 27 | RULE-ENG-INSP-R27（并列侥幸） | RULE-ENG-INSP-R27（唯一候选） |
| **28** | **RULE-WELDER-202606 焊工资格证** | **RULE-ENG-INSP-R28 管道组对** |
| 40 | 没有已发布规则 | 仍然没有（RULE-NDT-202606 是「待发布」，待产品决定） |
| 69 | 没有已发布规则 | RULE-ENG-INSP-R69 施工单位质量保证体系实施状况的评价 |

全库复核：69 个节点里 68 个有且仅有一条已发布规则，没有任何节点被两条规则争抢。

## 八、同一轮里修的界面问题

### 1. 结论卡只列问题，通过项看不见

`rule_check_results[].atomicCheckResults` 里本来就有逐项判定，从没下发过。
生产计数：节点 24 有 36 个原子项其中 12 项通过，节点 29 有 54 个其中 8 项通过——
这些在界面上完全看不到，监检人员没法区分「没报问题」和「压根没查」。

`review_view_with_limitations` 与 `ai_run` 现在都带 `atomicCheckOutcomes`
（判定取自本次执行留痕，名称按 id 从业务包取）；面板新增「逐项核查」，
按 不符合 → 需人工判断 → 证据不足 → 执行故障 → 不适用 → 通过 排列。
没有留痕时明说「本次运行没有留下逐项核查记录（一键分析不执行确定性核查）」，
不把这一段藏起来——藏起来又回到了「沉默看起来像通过」。

### 2. 界面上直接印着生码

节点 25 线上实测：证据不足组里两行写着 `「EVIDENCE_FILE_OUTSIDE_NODE」待核对`、
`「EVIDENCE_REFS_MISSING」待核对`，发现卡上挂着 `material_coverage` 灰标签。

- 证据/结构校验失败码（33 个）补齐中文，见 `auditLabels.evidenceIssueLabels`；
- `findingType` 是模型自由填的字符串而不是枚举——生产里 50 多种写法，
  同一个意思有 `missing_evidence` / `evidence_missing` / `MissingEvidence` / `证据缺失`
  四副面孔。改成先归一化再查表，中文原样放行，认不出的英文 token 退回「审查发现」。

线上复核（313ab539）：三处都已变成中文——「引用的文件不属于本节点」、
「这条结论没有给出证据出处」、「母材覆盖范围」。

### 3. 结论卡的标题与事实被截断到 40 字

数据层 `clip(…, 40)` 让标题永远只剩半句（「…与节点要…」）。改为只压缩空白，
卡片侧允许换行；顺带去掉卡片的 1px 外框与左侧色条（它嵌在已有边框的容器里）。
