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
