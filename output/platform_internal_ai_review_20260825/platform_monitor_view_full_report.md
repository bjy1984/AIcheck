# 监检工作台实际 AI 审查结果

> 这些结果由项目内真实 `ai-recheck → ReviewRun → LangGraph → QwenRuntime → 证据护栏` 流程产生。使用 OCR+LLM 缺项预审模式，所有结论仅供监检人员人工确认，不限制上传、发起审查或填写人工结论。

## 监检人员实际看到什么

每个正式挂载节点显示：运行状态、AI建议、置信度、意见草稿、findings列表、严重度、OCR证据引用、规则/标准条款和人工确认项。没有正式挂载的节点不会被一键审查自动发起，并显示具体原因。

## test 项目

| 监检端指标 | 数值 |
|---|---:|
| 上传并完成OCR/分类的文件 | 23 |
| 正式挂载并调用平台AI审查的节点 | 39/69 |
| 平台 findings 总数 | 116 |
| 高/严重 findings | 38 |
| 质量门禁通过节点 | 0 |
| 等待人工确认节点 | 39 |
| 建议结论分布 | 证据不足 38；建议不符合 1 |
| 平台审查输入 token | 3,977,275 |
| 平台审查输出 token | 162,237 |
| 平台审查总 token | 4,139,512 |

## test2 项目

| 监检端指标 | 数值 |
|---|---:|
| 上传并完成OCR/分类的文件 | 20 |
| 正式挂载并调用平台AI审查的节点 | 42/69 |
| 平台 findings 总数 | 121 |
| 高/严重 findings | 37 |
| 质量门禁通过节点 | 0 |
| 等待人工确认节点 | 42 |
| 建议结论分布 | 证据不足 41；建议不符合 1 |
| 平台审查输入 token | 1,990,551 |
| 平台审查输出 token | 147,864 |
| 平台审查总 token | 2,138,415 |

## 当前监检端输出暴露的问题

- 81 个已审节点全部停在 `waiting_human_review`，且质量门禁均未通过；这不是模型调用失败，而是平台引用校验要求监检人员继续确认。
- 两项目只有节点23（阀门施工资料和耐压试验记录）给出“建议不符合”，但证据护栏又把主意见降级为“证据不足，需人工确认”，因此不能直接作为人工结论。
- 大量 finding 因 unsupportedClaims 被替换成统一的“模型给出的业务结论缺少证据支持”，监检人员能看到风险等级和引用，但部分具体诊断被护栏丢弃，当前可读性有限。
- 质量门禁主要失败码：`KB_CLAUSE_NOT_IN_TRACE` 252 次；`KB_REF_MISSING_VERSION` 230 次；`RULE_REF_NOT_FOUND` 45 次；`CLAIM_TO_EVIDENCE_MISMATCH` 39 次；`MISSING_RULE_REFS` 7 次
- 57 个节点没有正式挂载，因此平台一键审查不会自动发起；报告中逐节点列出了是“大类提示”“预期缺失”还是“适用性未知”。

## 执行说明

- 首轮发生 5 次远程连接异常，均无模型响应；降低并发后全部重跑成功，最终结果不包含这些空白失败运行。
- 平台审查模型角色为 `review-chat`，当前解析模型是 `qwen3.7-plus`；文件分类模型是另一角色的 `qwen3.8-max`。
- 本次使用真实 MinerU OCR Markdown；离线导入时页码/bbox按文本分片模拟，因此意见内容真实，但点击原文的精确坐标仍需在生产上传链路复测。

# 逐节点监检端输出

## test 项目

# test｜受检单位资质

### 节点 1｜设计单位许可资质

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：106,490 / 5,204
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`设计许可证机构名称与施工图标题栏/印章一致性核查`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-license-001 P1；test-design-document-001 P1；test-design-document-001 P2
   - 规则/条款：engineering-inspection-r01；CREF-8D47713A3A4F023D；CREF-7B62106F1C15EFC6
2. **[中] 设计许可范围覆盖管道级别核查**
   - 类型：`设计许可范围覆盖管道级别核查`；证据状态：`grounded`；置信度：50%
   - 意见：现有资料支持程度：设计许可证（DV-TEST-010-V1）许可子项目包含“工业管道(GC1)”，备注“GC1级覆盖GC2级”；施工图管道特性表（DV-TEST-018-V1 第39–40页）显示多条管段压力管道类别为“GC2”。从字面看GC1可覆盖GC2，但当前工具链未返回结构化的许可证范围字段与管道特性表级别的确定性比对结果（check_design_license_scope 结果为 evidence_insufficient，licenseScopes 与 requiredPipelineGrades 均为空），且未见GCD动力管道的明确识别证据。缺少的资料或证据：结构化的许可证范围字段抽取结果、管道特性表中全部管段级别的完整列表、是否存在GCD动力管道的明确证据。可能风险：若存在GCD或GC1级别管段而许可证未覆盖，将构成超许可范围设计。
   - 证据：test-design-license-001 P1；test-design-document-001 P39；test-design-document-001 P40
   - 规则/条款：engineering-inspection-r01；CREF-D8EC66EEB10CA56C；CREF-4D684D994E20F008
3. **[中] 证据不足，需人工确认**
   - 类型：`设计许可证有效期覆盖施工期间核查`；证据状态：`insufficient_evidence`；置信度：45%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-license-001 P1；test-design-document-001 P2；test-design-document-001 P3
   - 规则/条款：engineering-inspection-r01；CREF-8D47713A3A4F023D

### 节点 2｜施工单位许可资质

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：134,112 / 4,325
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`资质范围覆盖性待确认`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-construction-license-001 P1；test-construction-plan-001 P11；test-design-document-001 P39
   - 规则/条款：engineering-inspection-r02；CREF-8D47713A3A4F023D；CREF-BE7AEEC9B5E1F82D；CREF-4D684D994E20F008
2. **[中] 证据不足，需人工确认**
   - 类型：`有效期覆盖性待确认`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-construction-license-001 P1；test-construction-plan-001 P5；test-construction-plan-001 P6
   - 规则/条款：engineering-inspection-r02；CREF-8D47713A3A4F023D；CREF-BE7AEEC9B5E1F82D；CREF-4D684D994E20F008
3. **[低] 证据不足，需人工确认**
   - 类型：`施工单位一致性待确认`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：未形成有效证据引用
   - 规则/条款：—

### 节点 3｜无损检测机构核准资质

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：142,079 / 6,917
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`无损检测机构核准资质-机构名称一致性`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-ndt-org-certificate-001 P1；test-ndt-plan-001 P1
   - 规则/条款：engineering-inspection-r03；CREF-8D47713A3A4F023D；CREF-355996F50BF66A05
2. **[高] 证据不足，需人工确认**
   - 类型：`无损检测机构核准资质-核准项目代码覆盖检测方法`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-ndt-org-certificate-001 P1；test-design-document-001 P39；test-design-document-001 P40；test-ndt-plan-001 P1
   - 规则/条款：engineering-inspection-r03；CREF-355996F50BF66A05
3. **[中] 证据不足，需人工确认**
   - 类型：`无损检测机构核准资质-有效期覆盖施工计划工期`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-ndt-org-certificate-001 P1；test-ndt-org-certificate-001 P2
   - 规则/条款：engineering-inspection-r03；CREF-8D47713A3A4F023D
4. **[高] 证据不足，需人工确认**
   - 类型：`无损检测机构核准资质-辐射安全许可证有效期`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-ndt-org-certificate-001 P2
   - 规则/条款：engineering-inspection-r03；CREF-8D47713A3A4F023D

# test｜设计文件

### 节点 4｜设计文件的批准程序

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 60%
- **意见草稿：** 根据TSG31-2025《工业管道安全技术规程》第3章要求，设计文件至少应包括图纸目录、设计说明书、管道数据表、管道布置图、管道材料一览表以及直管强度计算书。当前OCR证据显示文档包含图纸目录、安装设计说明、管道材料设计说明、管道等级索引表、管道材料等级代号说明、管道分支表、管道壁厚表、管道平面布置图、管道特性表、综合材料表、管道强度计算书等文件，但缺少独立的'管道数据表'和'管道材料一览表'文件，且'直管强度计算书'与'管道强度计算书'名称不完全一致。现有资料支持程度：部分文件可识别，但关键文件缺失或名称不匹配，需人工确认文件完整性。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：103,229 / 4,824
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 设计文件完整性无法自动核验**
   - 类型：`design_document_completeness`；证据状态：`grounded`；置信度：60%
   - 意见：根据TSG31-2025《工业管道安全技术规程》第3章要求，设计文件至少应包括图纸目录、设计说明书、管道数据表、管道布置图、管道材料一览表以及直管强度计算书。当前OCR证据显示文档包含图纸目录、安装设计说明、管道材料设计说明、管道等级索引表、管道材料等级代号说明、管道分支表、管道壁厚表、管道平面布置图、管道特性表、综合材料表、管道强度计算书等文件，但缺少独立的'管道数据表'和'管道材料一览表'文件，且'直管强度计算书'与'管道强度计算书'名称不完全一致。现有资料支持程度：部分文件可识别，但关键文件缺失或名称不匹配，需人工确认文件完整性。
   - 证据：test-design-document-001 P2；test-design-document-001 P3
   - 规则/条款：engineering-inspection-r04；CREF-32252BABE2D526A8
2. **[中] 证据不足，需人工确认**
   - 类型：`design_approval_signature`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P1；test-design-document-001 P4；test-design-document-001 P50
   - 规则/条款：engineering-inspection-r04；CREF-32252BABE2D526A8；CREF-BE0860B3CDF86487
3. **[中] 证据不足，需人工确认**
   - 类型：`pipeline_classification_verification`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P39；test-design-document-001 P40
   - 规则/条款：engineering-inspection-r04；CREF-32252BABE2D526A8

### 节点 5｜施工图审查手续

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 90%
- **意见草稿：** 根据规则要求，需审查施工单位出具的施工图审查见证材料。当前资料包中未发现任何施工图审查见证材料文件，包括材料名称、项目名称、图纸版本、审查日期、签章和见证结论等关键信息均无法获取。现有资料仅包含施工方案、图纸会审记录和设计文件，但缺少专门的施工图审查见证材料。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：143,563 / 2,302
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 施工图审查见证材料缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：90%
   - 意见：根据规则要求，需审查施工单位出具的施工图审查见证材料。当前资料包中未发现任何施工图审查见证材料文件，包括材料名称、项目名称、图纸版本、审查日期、签章和见证结论等关键信息均无法获取。现有资料仅包含施工方案、图纸会审记录和设计文件，但缺少专门的施工图审查见证材料。
   - 证据：test-construction-plan-001 P1；test-drawing-review-001 P1；test-design-document-001 P1
   - 规则/条款：engineering-inspection-r05；BUSINESS-RULE-R05；TSG-D7006-D2.4.1

### 节点 6｜强度计算书、管道应力分析计算书的审批手续

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 45%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：105,835 / 4,132
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_document`；证据状态：`insufficient_evidence`；置信度：45%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P3；test-design-document-001 P50；test-design-document-001 P51；test-design-document-001 P52
   - 规则/条款：engineering-inspection-r06；BUSINESS-RULE-R06；BUSINESS-RULE-R63；BUSINESS-RULE-R04；TSG-D7006-D2.4.1

### 节点 7｜设计变更的书面批准文件

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 55%
- **意见草稿：** 证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：104,123 / 3,200
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 未找到设计变更书面批准文件**
   - 类型：`missing_design_change_document`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test-design-document-001 P1；test-design-document-001 P2；test-design-document-001 P3
   - 规则/条款：engineering-inspection-r07；CREF-8278F02F838DC7CB；CREF-2B1BC36CE6C49104；CREF-0884A0BA5500262C
2. **[中] 证据不足，需人工确认**
   - 类型：`missing_seal_detection_capability`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P1
   - 规则/条款：engineering-inspection-r07；CREF-2B1BC36CE6C49104
3. **[中] 无法判断签字层级要求**
   - 类型：`incomplete_evidence_for_approval_level`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test-design-document-001 P39；test-design-document-001 P40
   - 规则/条款：engineering-inspection-r07；CREF-2B1BC36CE6C49104

### 节点 8｜设计采用的安全技术规范以及相关标准、压力管道元件的材料标准的版本

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 92%
- **意见草稿：** 在安装设计说明(第7页)中，弯头等管件采用《钢制对焊管件类型与参数》GB/T 12459-2025标准；但在管道材料等级代号说明(第20-22页)中，45°弯头、90°弯头、等径三通、异径三通、同心异径管、偏心异径管、管帽等管件均引用GB/T 12459-2017标准。同一项目设计文件中对同一标准引用了不同版本(2025版与2017版)，存在版本冲突，需人工确认设计意图及标准现行有效性。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：103,008 / 6,848
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 设计文件内部引用的GB/T 12459标准版本不一致**
   - 类型：`标准版本冲突`；证据状态：`grounded`；置信度：92%
   - 意见：在安装设计说明(第7页)中，弯头等管件采用《钢制对焊管件类型与参数》GB/T 12459-2025标准；但在管道材料等级代号说明(第20-22页)中，45°弯头、90°弯头、等径三通、异径三通、同心异径管、偏心异径管、管帽等管件均引用GB/T 12459-2017标准。同一项目设计文件中对同一标准引用了不同版本(2025版与2017版)，存在版本冲突，需人工确认设计意图及标准现行有效性。
   - 证据：test-design-document-001 P7；test-design-document-001 P20；test-design-document-001 P46
   - 规则/条款：engineering-inspection-r08；CREF-FA559F1E492FF306；CREF-DCCEC91117E5FC0C
2. **[中] 设计文件内部引用的GB/T 14976标准版本不一致**
   - 类型：`标准版本冲突`；证据状态：`grounded`；置信度：88%
   - 意见：在安装设计说明(第7页)中，不锈钢管道采用《流体输送用不锈钢无缝钢管》GB/T 14976-2025标准；但在管道材料等级代号说明(第19-20页)中，无缝钢管引用GB/T 14976-2025标准，而在管道壁厚表(第26页)中同样引用GB/T 14976-2025标准。然而，在综合材料表(第45页)中，不锈钢S30408无缝钢管同样引用GB/T 14976-2025标准。经核查，设计文件内部对GB/T 14976标准版本引用一致(均为2025版)，但需人工确认该版本是否为现行有效版本，以及是否存在被替代或废止的情况。
   - 证据：test-design-document-001 P7；test-design-document-001 P19；test-design-document-001 P45
   - 规则/条款：engineering-inspection-r08；CREF-FA559F1E492FF306；CREF-DCCEC91117E5FC0C
3. **[低] 证据不足，需人工确认**
   - 类型：`标准现行有效性待确认`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P7；test-design-document-001 P8；test-design-document-001 P9；test-design-document-001 P12
   - 规则/条款：engineering-inspection-r08；CREF-8F8D040B7CB2779E；CREF-FA559F1E492FF306；CREF-DCCEC91117E5FC0C
4. **[低] 证据不足，需人工确认**
   - 类型：`标准引用完整性待确认`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P51；test-design-document-001 P52
   - 规则/条款：engineering-inspection-r08；CREF-DCCEC91117E5FC0C

### 节点 9｜设计文件上注明的无损检测、防腐、耐压试验和泄漏试验要求

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：113,275 / 3,630
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`missing_design_requirements`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P9；test-design-document-001 P11；test-design-document-001 P39；test-design-document-001 P40
   - 规则/条款：engineering-inspection-r09；CREF-4010D278DBCDD007；CREF-B5CF4CBED1D5ECF0；CREF-A4D107CB9E6B859B

### 节点 10｜采用其他标准时，设计文件或工程规定中应包括符合《工业管道安全技术规程》基本安全的符合性申明及比照表

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

# test｜施工组织设计

### 节点 11｜施工组织设计

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 30%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：137,117 / 4,980
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`MissingSignatureEvidence`；证据状态：`insufficient_evidence`；置信度：30%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-construction-plan-001 P1
   - 规则/条款：engineering-inspection-r11；CREF-9BE9DF9811273C1B；CREF-284745E73F4F182F；CREF-BB00C7A64E9652E4
2. **[中] 施工组织设计项目范围信息与设计文件一致性待确认**
   - 类型：`MissingProjectScopeConsistency`；证据状态：`grounded`；置信度：50%
   - 意见：规则要求审查施工项目主要内容（装置名称、管道规格、材质、长度等）是否与设计文件一致。施工组织设计中提及管道规格Φ89×3.0、材质205（对应S30408）、长度205米，设计文件管道特性表中显示管道规格Φ89x3.0、材质S30408，但装置名称、完整项目范围的一致性比对证据不足，需人工核对确认。
   - 证据：test-construction-plan-001 P1；test-design-document-001 P39
   - 规则/条款：engineering-inspection-r11；CREF-9BE9DF9811273C1B
3. **[中] 证据不足，需人工确认**
   - 类型：`MissingWeldingTestProcedureVerification`；证据状态：`insufficient_evidence`；置信度：40%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-construction-plan-001 P2；test-construction-plan-001 P4；test-design-document-001 P9
   - 规则/条款：engineering-inspection-r11；CREF-BB00C7A64E9652E4
4. **[低] 证据不足，需人工确认**
   - 类型：`SealDetectionDisabled`；证据状态：`insufficient_evidence`；置信度：20%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-construction-plan-001 P1
   - 规则/条款：engineering-inspection-r11；CREF-9BE9DF9811273C1B

# test｜材料

### 节点 12｜压力管道元件及安全附件制造单位的许可资质

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：154,968 / 5,362
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P19；test-material-submission-package-001 P20；test-design-document-001 P45；test-design-document-001 P46
   - 规则/条款：engineering-inspection-r12；CREF-41A631142E46E595；CREF-36CDA821E30D401B；CREF-4D684D994E20F008
2. **[中] 设计文件与进场材料制造单位对应关系待核实**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test-design-document-001 P45；test-design-document-001 P46；test-material-submission-package-001 P3；test-material-submission-package-001 P13；test-material-submission-package-001 P23
   - 规则/条款：engineering-inspection-r12；CREF-41A631142E46E595；CREF-36CDA821E30D401B
3. **[中] 型式试验证书与工程实际使用元件规格比对缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：80%
   - 意见：河北圣天管件集团有限公司提供了两份型式试验证书： 1) 证书编号 TSX71001920232199（非焊接管件-无缝管件），覆盖范围 DN40mm～DN1600mm； 2) 证书编号 TSX74101005320240266（钢制锻造法兰），覆盖材料组别 V、VI，锻件级别 I～IV 级。 但以下比对工作未完成： 1) 本工程使用的 DN25、DN50 规格弯头、法兰是否在型式试验证书覆盖范围内未明确； 2) 型式试验证书中的产品型号与工程实际使用的 90°弯头（1.5D-90°Φ89×3.0）、带颈对焊法兰（DN80 WN-1.6-RF）等具体型号的对应关系未建立； 3) 缺少型式试验报告（编号 20238283、冀特 DGXS1120240266）的具体内容核实。
   - 证据：test-material-submission-package-001 P20；test-design-document-001 P46
   - 规则/条款：engineering-inspection-r12；CREF-41A631142E46E595

### 节点 13｜需制造监检或有型式试验要求的压力管道元件的监检证书、型式试验报告

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：80,485 / 6,225
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_design_material_list`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P1；test-material-submission-package-001 P5；test-material-submission-package-001 P20
   - 规则/条款：engineering-inspection-r13；CREF-98DC646DDE42B793；CREF-EC43C1FD78722947；CREF-B0F3DD6CFEECB884；CREF-6A755FCDE3FD42D5
2. **[中] 证据不足，需人工确认**
   - 类型：`missing_supervision_certificate`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P3；test-material-submission-package-001 P17
   - 规则/条款：engineering-inspection-r13；CREF-EC43C1FD78722947；CREF-6A755FCDE3FD42D5
3. **[中] 证据不足，需人工确认**
   - 类型：`type_test_coverage_unverifiable`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P5；test-material-submission-package-001 P20
   - 规则/条款：engineering-inspection-r13；CREF-B0F3DD6CFEECB884

### 节点 14｜不需制造许可、监检、型式试验的管道组成件的出厂检验报告，必要时进行现场抽查复验

> **平台状态：未发起AI审查。** 仅大类提示，不形成正式绑定，平台一键审查未发起。

### 节点 15｜境外制造的压力管道元件、安全附件的型式试验证书及其制造单位的制造许可证资质

> **平台状态：未发起AI审查。** 仅大类提示，不形成正式绑定，平台一键审查未发起。

### 节点 16｜压力管道元件以及安全附件产品质量证明文件

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：158,519 / 8,686
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`产品质量证明文件形式与签章无法判定`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P3；test-material-submission-package-001 P4
   - 规则/条款：engineering-inspection-r16；CREF-9B6A46316602DDE4；CREF-13DE6D4BCA788F25
2. **[中] 证据不足，需人工确认**
   - 类型：`产品质量证明文件执行标准与设计文件版本不一致`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P7；test-material-submission-package-001 P3
   - 规则/条款：engineering-inspection-r16；CREF-D638CDB8B398042F；CREF-FE2319A8A97DC41F
3. **[中] 证据不足，需人工确认**
   - 类型：`设计材料表与到货产品质量证明文件批次覆盖核验未完成`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P45；test-design-document-001 P48；test-material-submission-package-001 P26；test-material-submission-package-001 P27
   - 规则/条款：engineering-inspection-r16；CREF-9B6A46316602DDE4；CREF-FE2319A8A97DC41F
4. **[中] 证据不足，需人工确认**
   - 类型：`产品质量证明文件内容完整性核验未完成`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P3；test-material-submission-package-001 P13
   - 规则/条款：engineering-inspection-r16；CREF-D638CDB8B398042F；CREF-9F0E905D8CCFDC7B
5. **[中] 证据不足，需人工确认**
   - 类型：`产品质量证明文件与设计材料表一致性核验未完成`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P19；test-design-document-001 P45；test-material-submission-package-001 P3
   - 规则/条款：engineering-inspection-r16；CREF-9B6A46316602DDE4；CREF-FE2319A8A97DC41F

### 节点 17｜压力管道元件以及安全附件产品验收的见证资料、抽样复验

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：79,863 / 5,122
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`missing_sampling_retest_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P2；test-material-submission-package-001 P3
   - 规则/条款：engineering-inspection-r17；CREF-13050D6AF4681984；CREF-7BF61886F397CFF7
2. **[中] 证据不足，需人工确认**
   - 类型：`missing_witness_records`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P3；test-material-submission-package-001 P9；test-material-submission-package-001 P22
   - 规则/条款：engineering-inspection-r17；CREF-7BF61886F397CFF7；CREF-EB63722DC9626283
3. **[低] 证据不足，需人工确认**
   - 类型：`missing_design_requirements`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P1
   - 规则/条款：engineering-inspection-r17；CREF-13050D6AF4681984；CREF-48AC51AABD440ABD
4. **[低] 证据不足，需人工确认**
   - 类型：`incomplete_batch_coverage_verification`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：未形成有效证据引用
   - 规则/条款：—

### 节点 18｜材料复验报告、无损检测报告

> **平台状态：未发起AI审查。** 仅大类提示，不形成正式绑定，平台一键审查未发起。

### 节点 19｜使用境外牌号材料制造的压力管道元件以及安全附件，验证性复验结果

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 55%
- **意见草稿：** 证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：163,241 / 2,872
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 未提供使用境外牌号材料制造的压力管道元件及安全附件的验证性复验资料**
   - 类型：`境外牌号材料验证性复验证据缺失`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test-design-document-001 P17；test-design-document-001 P19；test-design-document-001 P45
   - 规则/条款：RULE-ENG-INSP-R19；CREF-602862FA628F697D；CREF-2625DCD087D7DBC7

### 节点 20｜新材料制造的压力管道元件以及安全附件的型式试验报告、技术评审、批准手续

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 55%
- **意见草稿：** 证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：76,978 / 3,547
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 缺少设计文件/材料表以判定是否涉及新材料**
   - 类型：`missing_design_material_basis`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test-material-submission-package-001 P1；test-material-submission-package-001 P5
   - 规则/条款：engineering-inspection-r20；BUSINESS-RULE-R04；BUSINESS-RULE-R08
2. **[中] 型式试验证书覆盖范围与本工程使用规格的比对未完成**
   - 类型：`missing_type_test_coverage_verification`；证据状态：`grounded`；置信度：60%
   - 意见：资料中包含型式试验证书（如编号 TSX71101004320260043、TSX71001920232199、TSX74101005320240266），但因缺少设计材料表/管道数据表，无法核验证书覆盖的材料、规格、工艺是否覆盖本工程实际使用的元件与安全附件。现有证据仅能证明证书存在，不能证明其覆盖性。
   - 证据：test-material-submission-package-001 P5；test-material-submission-package-001 P20
   - 规则/条款：engineering-inspection-r20；BUSINESS-RULE-R15
3. **[中] 证据不足，需人工确认**
   - 类型：`missing_technical_review_and_approval_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P1
   - 规则/条款：engineering-inspection-r20；BUSINESS-RULE-R15；BUSINESS-RULE-R04

### 节点 21｜材料标志移植

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：86,574 / 2,258
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence_for_rule`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P1；test-material-submission-package-001 P3
   - 规则/条款：RULE-ENG-INSP-R21；CREF-7EA37E6336A563A4；CREF-8C5C018722E829A9；CREF-EB63722DC9626283

### 节点 22｜材料代用

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

# test｜阀门

### 节点 23｜阀门的施工资料和耐压试验记录（报告）

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 建议不符合，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：87,924 / 6,115
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_valve_test_records`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P1；test-material-submission-package-001 P11；test-material-submission-package-001 P21
   - 规则/条款：engineering-inspection-r23；BUSINESS-RULE-R23；CREF-E134954EA2DA20B6；CREF-B8F127C63490C1AD；CREF-9A974D8867872803；CREF-C8DFE6F07C912647
2. **[中] 阀门清单与阀门施工记录未提供**
   - 类型：`missing_valve_list_and_construction_records`；证据状态：`grounded`；置信度：92%
   - 意见：现有资料中材料报审表仅涵盖无缝钢管（HRD-罐区-JSSJ-CLBS-001）、焊丝（HRD-罐区-JSSJ-CLBS-002）、弯头及法兰（HRD-罐区-JSSJ-CLBS-003）、异径管及三通（HRD-罐区-JSSJ-CLBS-004）、垫片（HRD-罐区-JSSJ-CLBS-005）、螺栓（HRD-罐区-JSSJ-CLBS-006），未见阀门类材料的进场报审、阀门清单或阀门施工记录。无法建立阀门编号、规格型号、公称压力与耐压试验报告之间的追溯关系。
   - 证据：test-material-submission-package-001 P1；test-material-submission-package-001 P6；test-material-submission-package-001 P11；test-material-submission-package-001 P21；test-material-submission-package-001 P26；test-material-submission-package-001 P29
   - 规则/条款：engineering-inspection-r23；BUSINESS-RULE-R23
3. **[中] 证据不足，需人工确认**
   - 类型：`missing_design_basis_for_valve_test`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P1
   - 规则/条款：engineering-inspection-r23；BUSINESS-RULE-R23；CREF-E134954EA2DA20B6；CREF-B8F127C63490C1AD

# test｜焊接（粘接）

### 节点 24｜焊工资格证及持证合格项目

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：66,900 / 4,897
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`焊工资格证及持证合格项目-证据不足`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-construction-plan-001 P11；test-construction-plan-001 P12；test-construction-plan-001 P13；test-welder-roster-001 P1
   - 规则/条款：RULE-WELDER-202606；CREF-2FE510BF270BDBE3；CREF-FDB25674558F4D1B；CREF-8771A88BDA5933CB
2. **[中] 证据不足，需人工确认**
   - 类型：`焊工资格证及持证合格项目-证据不足`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-construction-plan-001 P1；test-construction-plan-001 P2；test-construction-plan-001 P17
   - 规则/条款：RULE-WELDER-202606；CREF-FDB25674558F4D1B
3. **[中] 证据不足，需人工确认**
   - 类型：`焊工资格证及持证合格项目-证据不足`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-construction-plan-001 P11；test-welder-roster-001 P1；test-welder-roster-001 P2；test-welder-roster-001 P3
   - 规则/条款：RULE-WELDER-202606；CREF-2FE510BF270BDBE3

### 节点 25｜焊接（粘接）工艺文件

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：128,517 / 2,942
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_welder_certificate`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P8；test-design-document-001 P39
   - 规则/条款：welder-qualification；TSG-Z6002-3.2
2. **[中] 证据不足，需人工确认**
   - 类型：`insufficient_welder_work_coverage_verification`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P39；test-design-document-001 P40
   - 规则/条款：welder-qualification；TSG-Z6002-3.2

### 节点 26｜焊接材料质量证明文件

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 55%
- **意见草稿：** 证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：166,502 / 3,459
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 焊接材料质量证明文件（MTC）缺失，无法核验焊材牌号、规格、批号及有效期**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test-design-document-001 P8；test-material-submission-package-001 P1
   - 规则/条款：RULE-ENG-INSP-R26；CREF-B5885FF5690DD64B；CREF-C1B87D95423DDD28；CREF-4E6243DB73DEB841

### 节点 27｜焊接材料的验收、保管、发放、使用和回收的管理

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 10%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：90,656 / 3,119
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_welder_qualification_evidence`；证据状态：`insufficient_evidence`；置信度：10%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P1；test-material-submission-package-001 P6
   - 规则/条款：welder-qualification；TSG-Z6002-3.2；BUSINESS-RULE-R27
2. **[中] 证据不足，需人工确认**
   - 类型：`missing_welding_record_evidence`；证据状态：`insufficient_evidence`；置信度：15%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P7；test-material-submission-package-001 P11
   - 规则/条款：welder-qualification；TSG-Z6002-3.2
3. **[中] 焊工资格证关键字段未识别**
   - 类型：`welder_certificate_field_extraction_failure`；证据状态：`grounded`；置信度：95%
   - 意见：工具extract_welder_certificate返回结果显示：证件编号（certificateNo）未识别、档案编号（archiveNo）未识别、合格项目代号（qualifiedItems）为空。发证机关仅识别到
   - 证据：未形成有效证据引用
   - 规则/条款：—

### 节点 28｜管道组对

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 29｜施焊参数、施焊记录、焊缝标识

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：91,672 / 4,087
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_welding_records`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-construction-plan-001 P1；test-wps-pqr-001 P2
   - 规则/条款：engineering-inspection-r29；CREF-EA8225D5DAFA7E26；CREF-846B8518EE288749；CREF-9B5CCA3FEFE3C78E
2. **[中] 证据不足，需人工确认**
   - 类型：`welder_certificate_risk`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-construction-plan-001 P11；test-construction-plan-001 P12；test-construction-plan-001 P13
   - 规则/条款：engineering-inspection-r29；CREF-EA8225D5DAFA7E26
3. **[中] 证据不足，需人工确认**
   - 类型：`wps_pqr_coverage_unverified`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-wps-pqr-001 P1；test-wps-pqr-001 P2；test-wps-pqr-001 P5
   - 规则/条款：engineering-inspection-r29；CREF-846B8518EE288749

### 节点 30｜焊接接头外观质量

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 31｜焊缝返修

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

# test｜热处理

### 节点 32｜焊接接头焊后热处理工艺文件

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：115,182 / 4,294
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_heat_treatment_procedure_card`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-wps-pqr-001 P1；test-wps-pqr-001 P4
   - 规则/条款：engineering-inspection-r32；CREF-1B403085C6229F73；CREF-8AB529F378CDFCCA
2. **[中] 焊后热处理适用性无法判定，缺少焊接接头清单与厚度信息**
   - 类型：`pwht_applicability_undetermined`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test-design-document-001 P19；test-wps-pqr-001 P4
   - 规则/条款：engineering-inspection-r32；CREF-8AB529F378CDFCCA
3. **[中] 缺少专门的热处理评定报告支撑**
   - 类型：`missing_heat_treatment_qualification_report`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test-wps-pqr-001 P4；test-design-document-001 P19
   - 规则/条款：engineering-inspection-r32；CREF-1B403085C6229F73；CREF-82222266FA7DC1ED

### 节点 33｜热处理设备用测温记录仪表

> **平台状态：未发起AI审查。** 存在预期资料类型但没有正式挂载，平台一键审查未发起。

### 节点 34｜热处理记录、报告曲线、硬度检测报告

> **平台状态：未发起AI审查。** 存在预期资料类型但没有正式挂载，平台一键审查未发起。

# test｜无损检测

### 节点 35｜无损检测机构施工现场质量保证体系的实施

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：25,044 / 3,710
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-ndt-org-certificate-001 P1
   - 规则/条款：engineering-inspection-r35；BUSINESS-RULE-R35
2. **[高] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-ndt-org-certificate-001 P1
   - 规则/条款：engineering-inspection-r35；BUSINESS-RULE-R35
3. **[高] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-ndt-org-certificate-001 P1
   - 规则/条款：engineering-inspection-r35；BUSINESS-RULE-R35
4. **[高] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-ndt-org-certificate-001 P1
   - 规则/条款：engineering-inspection-r35；BUSINESS-RULE-R35
5. **[中] 证据不足，需人工确认**
   - 类型：`evidence_insufficient`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-ndt-org-certificate-001 P3；test-ndt-org-certificate-001 P4
   - 规则/条款：engineering-inspection-r35；BUSINESS-RULE-R35；BUSINESS-RULE-R69

### 节点 36｜无损检测方案

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 90%
- **意见草稿：** 现有资料为《无损检测施工方案》（DV-TEST-009-V1），包含射线检测和渗透检测的通用工艺规程，但缺少针对具体检测对象的设计文件中的无损检测要求。无法验证：1）检测方法和检测比例是否满足设计文件要求；2）检测时机是否与设计文件一致；3）验收等级是否与设计文件匹配；4）人员和设备配置是否能支撑方案执行。方案中虽有编制、审核、批准人员信息，但缺少设计文件作为比对依据。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：60,159 / 3,245
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 无损检测方案关键要素证据不足**
   - 类型：`missing_required_document`；证据状态：`grounded`；置信度：90%
   - 意见：现有资料为《无损检测施工方案》（DV-TEST-009-V1），包含射线检测和渗透检测的通用工艺规程，但缺少针对具体检测对象的设计文件中的无损检测要求。无法验证：1）检测方法和检测比例是否满足设计文件要求；2）检测时机是否与设计文件一致；3）验收等级是否与设计文件匹配；4）人员和设备配置是否能支撑方案执行。方案中虽有编制、审核、批准人员信息，但缺少设计文件作为比对依据。
   - 证据：test-ndt-plan-001 P1
   - 规则/条款：RULE-ENG-INSP-R36；CREF-FBFB16DD0D145B4E；CREF-D1EE1F4E7CBB0D51；CREF-2F13103A69B0857B
2. **[中] 证据不足，需人工确认**
   - 类型：`missing_design_document`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：未形成有效证据引用
   - 规则/条款：RULE-ENG-INSP-R36；CREF-2F13103A69B0857B
3. **[中] 无损检测方案完整性验证受限**
   - 类型：`incomplete_verification`；证据状态：`grounded`；置信度：80%
   - 意见：现有《无损检测施工方案》包含射线检测（RT）和渗透检测（PT）的通用工艺内容，但缺少以下关键信息的明确证据：1）具体检测对象（管道规格、材质、壁厚等）；2）检测比例的具体数值；3）检测时机的明确规定；4）验收等级的具体引用。方案中提及的编制依据包含NB/T 47013系列标准，但未明确具体检测等级和验收标准。
   - 证据：test-ndt-plan-001 P1；test-ndt-plan-001 P3
   - 规则/条款：RULE-ENG-INSP-R36；CREF-D1EE1F4E7CBB0D51

### 节点 37｜检测过程中发现问题的处理

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 38｜无损检测人员资格证、执业注册证及持证合格项目

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：54,490 / 5,673
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-ndt-person-certificate-001 P1；test-ndt-person-certificate-002 P1；test-ndt-person-certificate-003 P1；test-ndt-person-certificate-004 P1；test-ndt-person-certificate-005 P1；test-ndt-person-certificate-006 P1
   - 规则/条款：engineering-inspection-r38；BUSINESS-RULE-R38
2. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-ndt-plan-001 P1
   - 规则/条款：engineering-inspection-r38；BUSINESS-RULE-R38
3. **[低] 劳动合同证明文件缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：85%
   - 意见：根据规则要求，必要时需提供无损检测人员劳动合同证明文件。现有资料中未发现相关人员的劳动合同证明，无法确认人员与执业单位的劳动关系。
   - 证据：test-ndt-person-certificate-001 P1；test-ndt-person-certificate-004 P1；test-ndt-person-certificate-006 P1
   - 规则/条款：engineering-inspection-r38；BUSINESS-RULE-R38
4. **[低] 证据不足，需人工确认**
   - 类型：`evidence_observation`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-ndt-person-certificate-001 P1；test-ndt-person-certificate-002 P1；test-ndt-person-certificate-003 P1；test-ndt-person-certificate-004 P1；test-ndt-person-certificate-005 P1；test-ndt-person-certificate-006 P1
   - 规则/条款：engineering-inspection-r38；BUSINESS-RULE-R38

### 节点 39｜无损检测工艺文件

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 85%
- **意见草稿：** 规则要求提供相关单项无损检测工艺文件，但现有资料中仅发现《无损检测施工方案》（DV-TEST-009-V1），未发现针对具体检测方法（如射线检测、渗透检测等）的单项工艺文件。施工方案中虽提及射线检测和渗透检测的操作流程，但未明确标注为独立的工艺文件，且缺少工艺文件编号、审批记录等关键要素。现有资料支持程度：不足。缺少的资料：单项无损检测工艺文件（含工艺编号、适用范围、工艺参数、验收标准等）。可能风险：无法验证检测工艺是否经过审批、是否覆盖实际检测对象和方法、参数是否满足标准要求。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：59,721 / 3,360
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 缺少单项无损检测工艺文件**
   - 类型：`missing_required_document`；证据状态：`grounded`；置信度：85%
   - 意见：规则要求提供相关单项无损检测工艺文件，但现有资料中仅发现《无损检测施工方案》（DV-TEST-009-V1），未发现针对具体检测方法（如射线检测、渗透检测等）的单项工艺文件。施工方案中虽提及射线检测和渗透检测的操作流程，但未明确标注为独立的工艺文件，且缺少工艺文件编号、审批记录等关键要素。现有资料支持程度：不足。缺少的资料：单项无损检测工艺文件（含工艺编号、适用范围、工艺参数、验收标准等）。可能风险：无法验证检测工艺是否经过审批、是否覆盖实际检测对象和方法、参数是否满足标准要求。
   - 证据：test-ndt-plan-001 P1
   - 规则/条款：RULE-ENG-INSP-R39；CREF-2D907840ABF66643；CREF-4822F75512030D98
2. **[高] 证据不足，需人工确认**
   - 类型：`missing_required_document`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-ndt-plan-001 P2；test-ndt-plan-001 P4
   - 规则/条款：RULE-ENG-INSP-R39；CREF-4822F75512030D98
3. **[中] 施工方案中缺少关键工艺参数**
   - 类型：`incomplete_document_content`；证据状态：`grounded`；置信度：75%
   - 意见：现有《无损检测施工方案》中虽包含射线检测和渗透检测的操作流程，但缺少以下关键工艺参数：1）射线检测的具体曝光参数（管电压、管电流、曝光时间等）；2）渗透检测的具体工艺参数（渗透时间、显像时间、检测温度范围等虽有提及但不够详细）；3）设备型号和规格信息；4）灵敏度校准的具体方法和要求；5）验收等级的明确引用。现有资料支持程度：部分支持。缺少的资料：详细的工艺参数表、设备清单、校准规程。可能风险：工艺参数不明确可能导致检测灵敏度不足、缺陷漏检。
   - 证据：test-ndt-plan-001 P1；test-ndt-plan-001 P3
   - 规则/条款：RULE-ENG-INSP-R39；CREF-4822F75512030D98
4. **[中] 证据不足，需人工确认**
   - 类型：`missing_design_requirements`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：未形成有效证据引用
   - 规则/条款：RULE-ENG-INSP-R39；CREF-2D907840ABF66643

### 节点 40｜无损检测记录、报告

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 41｜射线检测底片抽查

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 42｜射线检测现场抽查

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

# test｜防腐、保温

### 节点 43｜防腐及保温材料质量证明文件

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 55%
- **意见草稿：** 证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：104,174 / 3,088
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 防腐及保温材料质量证明文件缺失**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test-design-document-001 P11；test-design-document-001 P45
   - 规则/条款：engineering-inspection-r43；BUSINESS-RULE-R43；TSG-D7006-D2.4.1
2. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P11
   - 规则/条款：engineering-inspection-r43；BUSINESS-RULE-R43
3. **[中] 防腐材料质量证明文件缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：90%
   - 意见：设计文件第11页（安装设计说明6.2-6.6节）明确了防腐设计要求：碳钢管道和所用的碳钢型材需要表面处理，喷砂除锈等级须达到Sa2.5级；非绝热的碳钢管道、支架在进行去污、除锈等表面处理后，涂两遍防锈底漆和面漆；绝热碳钢管道表面除锈后，保温管道需刷防腐底漆，碳钢保冷管道底漆采用冷底子油或沥青底漆涂两遍。但当前资料中未发现防腐漆或其他特殊防腐材料的质量证明文件。
   - 证据：test-design-document-001 P11
   - 规则/条款：engineering-inspection-r43；BUSINESS-RULE-R43

### 节点 44｜防腐、补口、补伤及保温

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 45｜防腐层电火花检测

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 46｜牺牲阳极、外加电流阴极保护、杂散电流排流装置

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：78,645 / 3,730
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_required_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P1；test-material-submission-package-001 P2
   - 规则/条款：engineering-inspection-r46；CREF-AC749F12E31BD494；CREF-9AE4242E483645B4；CREF-5BC454DB621E0546
2. **[中] 证据不足，需人工确认**
   - 类型：`design_requirement_unverified`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P1
   - 规则/条款：engineering-inspection-r46；CREF-AC749F12E31BD494
3. **[中] 证据不足，需人工确认**
   - 类型：`evidence_gap_for_compliance`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P1
   - 规则/条款：engineering-inspection-r46；CREF-5BC454DB621E0546；CREF-9AE4242E483645B4

### 节点 47｜静电接地

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：103,485 / 3,007
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P10
   - 规则/条款：engineering-inspection-r47；BUSINESS-RULE-R47
2. **[高] 静电接地验收报告缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：95%
   - 意见：根据规则要求，需提供静电接地验收报告以验证验收结论和签字确认。当前提供的资料中未找到任何静电接地验收报告文件，无法验证静电接地工程是否经过正式验收并合格。
   - 证据：test-design-document-001 P10
   - 规则/条款：engineering-inspection-r47；BUSINESS-RULE-R47
3. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P10
   - 规则/条款：engineering-inspection-r47；BUSINESS-RULE-R47
4. **[低] 设计文件已明确静电接地要求**
   - 类型：`design_requirement_identified`；证据状态：`grounded`；置信度：95%
   - 意见：设计文件第10页'5 静电接地'章节已明确静电接地技术要求：5.1条要求防爆区域内金属设备、管道、储罐均应设置可靠静电接地；非公用工程管道系统每段管道间应保证导电良好，法兰或螺纹接头间电阻>0.03Ω时需设置导线跨接；5.2条要求静电接地引线宜用焊接形式；5.4条要求不锈钢管道导线跨接或接地引线应采用不锈钢板过渡。这些要求将作为施工和验收的依据。
   - 证据：test-design-document-001 P10
   - 规则/条款：engineering-inspection-r47；BUSINESS-RULE-R47

# test｜穿跨越工程

### 节点 48｜穿跨越工程的管道结构、焊缝布置

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 49｜穿跨越工程施工

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 50｜套管防腐绝缘

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 90%
- **意见草稿：** 根据规则要求，需抽查套管防腐绝缘检查记录，包括穿跨越段钢套管外部防腐处理、内部与管道绝缘隔离措施等内容。当前提供的资料中未发现任何套管防腐绝缘相关的检查记录文件。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：103,761 / 3,029
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 套管防腐绝缘检查记录缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：90%
   - 意见：根据规则要求，需抽查套管防腐绝缘检查记录，包括穿跨越段钢套管外部防腐处理、内部与管道绝缘隔离措施等内容。当前提供的资料中未发现任何套管防腐绝缘相关的检查记录文件。
   - 证据：未形成有效证据引用
   - 规则/条款：engineering-inspection-r50；BUSINESS-RULE-R50
2. **[中] 穿跨越设计文件缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：90%
   - 意见：规则要求提供穿跨越设计文件以确认套管防腐绝缘的具体要求。当前资料中仅有管道平面布置图、管道特性表等常规设计文件，未见专门的穿跨越工程设计文件。
   - 证据：未形成有效证据引用
   - 规则/条款：engineering-inspection-r50；BUSINESS-RULE-R50
3. **[中] 阴极保护相关资料缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：90%
   - 意见：规则指出当存在阴极保护时，需检查套管内部与管道的绝缘隔离措施。当前资料中未见任何关于阴极保护系统设计或实施的相关文件，无法判断是否需要绝缘隔离措施。
   - 证据：未形成有效证据引用
   - 规则/条款：engineering-inspection-r50；BUSINESS-RULE-R50
4. **[低] 套管位置信息缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：80%
   - 意见：规则要求识别套管位置信息以便进行针对性的防腐绝缘检查。当前提供的管道平面布置图中未见明确的穿跨越段套管位置标注。
   - 证据：未形成有效证据引用
   - 规则/条款：engineering-inspection-r50；BUSINESS-RULE-R50

### 节点 51｜绝缘支撑

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 85%
- **意见草稿：** 根据规则要求，当设计文件要求管道与支撑绝缘时应进行绝缘支撑检查。经核查提供的施工图设计文件（包括安装设计说明、管道材料设计说明、管道等级索引表、管道特性表等），未发现关于管道与支撑绝缘的具体设计要求。现有资料无法确定本项目是否需要设置绝缘支撑，也无法判断绝缘支撑检查的适用性。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：103,959 / 3,178
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 设计文件未明确管道与支撑绝缘要求**
   - 类型：`missing_design_requirement_for_insulated_support`；证据状态：`grounded`；置信度：85%
   - 意见：根据规则要求，当设计文件要求管道与支撑绝缘时应进行绝缘支撑检查。经核查提供的施工图设计文件（包括安装设计说明、管道材料设计说明、管道等级索引表、管道特性表等），未发现关于管道与支撑绝缘的具体设计要求。现有资料无法确定本项目是否需要设置绝缘支撑，也无法判断绝缘支撑检查的适用性。
   - 证据：test-design-document-001 P4；test-design-document-001 P7；test-design-document-001 P39
   - 规则/条款：engineering-inspection-r51；BUSINESS-RULE-R51；TSG-D7006-D2.4.1
2. **[中] 缺少绝缘支撑检查记录**
   - 类型：`missing_insulation_support_inspection_records`；证据状态：`grounded`；置信度：90%
   - 意见：根据监检规则要求，当设计文件要求管道与支撑绝缘时，应抽查绝缘支撑检查记录。现有资料中未提供绝缘支撑检查记录、绝缘材料信息、绝缘测试记录等相关文件。若设计确实要求绝缘支撑，则缺少必要的施工检查见证资料。
   - 证据：test-design-document-001 P1；test-design-document-001 P2
   - 规则/条款：engineering-inspection-r51；BUSINESS-RULE-R51
3. **[低] 缺少现场绝缘支撑核查证据**
   - 类型：`missing_field_verification_evidence`；证据状态：`grounded`；置信度：80%
   - 意见：根据规则要求，涉及现场检查、抽查或影像证据时，AI只做辅助核验，需监检人员确认现场事实。现有资料中未提供绝缘支撑的现场照片、安装位置记录、绝缘措施实施情况等现场核查证据。需要监检人员进行现场核实确认。
   - 证据：test-design-document-001 P30
   - 规则/条款：engineering-inspection-r51；BUSINESS-RULE-R51

# test｜管道现场制作（预制）

### 节点 52｜管道现场制作（预制）

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

# test｜管道安装

### 节点 53｜管道布管与连接方式、穿跨越

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 54｜补偿装置

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 95%
- **意见草稿：** 根据规则要求，需抽查管道补偿装置检查试验记录（按照设计文件的规定进行预拉伸或者预压缩）。当前提供的资料中仅包含管道元件及材料的进场验收记录（如无缝钢管、焊丝、弯头、法兰、垫片、螺栓等），未发现任何关于补偿装置（如波纹管补偿器、套筒补偿器等）的检查试验记录，也未见补偿装置的预拉伸或预压缩施工记录。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：78,024 / 2,776
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 补偿装置检查试验记录缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：95%
   - 意见：根据规则要求，需抽查管道补偿装置检查试验记录（按照设计文件的规定进行预拉伸或者预压缩）。当前提供的资料中仅包含管道元件及材料的进场验收记录（如无缝钢管、焊丝、弯头、法兰、垫片、螺栓等），未发现任何关于补偿装置（如波纹管补偿器、套筒补偿器等）的检查试验记录，也未见补偿装置的预拉伸或预压缩施工记录。
   - 证据：test-material-submission-package-001 P1
   - 规则/条款：engineering-inspection-r54；BUSINESS-RULE-R54
2. **[高] 补偿装置设计文件缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：95%
   - 意见：规则要求核查补偿装置是否按照设计文件的规定进行预拉伸或预压缩。当前资料中未见管道设计文件（如管道布置图、管道特性表、设计说明等），无法确认设计中是否包含补偿装置及其预拉伸/预压缩要求。
   - 证据：test-material-submission-package-001 P1
   - 规则/条款：engineering-inspection-r54；BUSINESS-RULE-R54
3. **[高] 补偿装置产品技术文件缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：95%
   - 意见：规则要求核查补偿装置产品技术文件。当前资料中未见补偿装置的产品质量证明文件、合格证或技术说明书，无法确认补偿装置的规格型号、技术参数及安装要求。
   - 证据：test-material-submission-package-001 P1
   - 规则/条款：engineering-inspection-r54；BUSINESS-RULE-R54

### 节点 55｜支撑件

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 95%
- **意见草稿：** 本节点（支撑件，C类）要求抽查管道支撑件检查试验记录，并核对支撑件位置、类型、规格型号、安装方式、检查项目与结论，尤其是固定支架、导向支架、弹簧支吊架的功能要求是否被记录验证。当前资料包仅包含管道元件及材料进场报审与质量证明文件（无缝钢管、焊丝、弯头、法兰、异径管、三通、垫片、螺栓等），未提供任何支撑件（支吊架）的设计文件、产品技术文件或检查试验记录，无法判定支撑件是否按设计位置和型式安装，也无法确认检查试验记录是否覆盖关键支撑件。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：77,947 / 4,561
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 支撑件检查试验记录缺失，无法核查支撑件安装与功能验证**
   - 类型：`missing_evidence_for_rule`；证据状态：`grounded`；置信度：95%
   - 意见：本节点（支撑件，C类）要求抽查管道支撑件检查试验记录，并核对支撑件位置、类型、规格型号、安装方式、检查项目与结论，尤其是固定支架、导向支架、弹簧支吊架的功能要求是否被记录验证。当前资料包仅包含管道元件及材料进场报审与质量证明文件（无缝钢管、焊丝、弯头、法兰、异径管、三通、垫片、螺栓等），未提供任何支撑件（支吊架）的设计文件、产品技术文件或检查试验记录，无法判定支撑件是否按设计位置和型式安装，也无法确认检查试验记录是否覆盖关键支撑件。
   - 证据：test-material-submission-package-001 P1；test-material-submission-package-001 P11；test-material-submission-package-001 P21；test-material-submission-package-001 P26；test-material-submission-package-001 P29
   - 规则/条款：RULE-ENG-INSP-R55；CREF-63D25B8ABB39CD71；CREF-931286D94FBF2550
2. **[高] 支撑件设计文件及产品技术文件未提供**
   - 类型：`missing_design_and_product_docs_for_supports`；证据状态：`grounded`；置信度：95%
   - 意见：规则要求提供支撑件的设计文件及产品技术文件，用于核对支撑件类型、规格型号、安装方式与设计一致性。当前资料仅包含管道元件（管子、管件、法兰、垫片、紧固件）的报审与质量证明文件，未见任何支撑件（如支吊架、固定支架、导向支架、弹簧支吊架等）的设计图纸、计算书或产品技术文件，导致无法进行支撑件符合性核查。
   - 证据：test-material-submission-package-001 P1；test-material-submission-package-001 P6；test-material-submission-package-001 P11；test-material-submission-package-001 P21；test-material-submission-package-001 P26；test-material-submission-package-001 P29
   - 规则/条款：RULE-ENG-INSP-R55；CREF-63D25B8ABB39CD71；CREF-931286D94FBF2550
3. **[高] 证据不足，需人工确认**
   - 类型：`missing_inspection_records_for_supports`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P2；test-material-submission-package-001 P12；test-material-submission-package-001 P22；test-material-submission-package-001 P27；test-material-submission-package-001 P30
   - 规则/条款：RULE-ENG-INSP-R55；CREF-63D25B8ABB39CD71；CREF-931286D94FBF2550

# test｜安全附件

### 节点 56｜安全阀、爆破片和紧急切断阀的安装位置、规格和型号

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：75,801 / 3,439
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_safety_accessory_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-material-submission-package-001 P1；test-material-submission-package-001 P11；test-material-submission-package-001 P21；test-material-submission-package-001 P26；test-material-submission-package-001 P29
   - 规则/条款：engineering-inspection-r56；CREF-F4C16066CA372C71；CREF-D4EC0671788DE080
2. **[中] 缺少安全附件相关设计文件及安装记录**
   - 类型：`missing_design_and_installation_records`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test-material-submission-package-001 P1
   - 规则/条款：engineering-inspection-r56；CREF-F4C16066CA372C71；CREF-D4EC0671788DE080

### 节点 57｜安全阀校验报告

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 58｜紧急切断阀性能测试报告

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

# test｜耐压试验

### 节点 59｜耐压试验方案

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 95%
- **意见草稿：** 当前资料包中仅包含设计文件（图纸目录、安装设计说明、管道材料设计说明、管道等级索引表、管道材料等级代号说明、管道分支表、管道壁厚表、管道平面图、管道特性表、综合材料表、管道强度计算书），未提供施工单位编制的《耐压试验方案》。根据规则要求，需审查耐压试验方案的审批手续及签字、试验时机、试验介质、升压速度、试验用压力表和温度计要求、安全措施、合格标准等内容，现有资料无法支持上述审查。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：103,278 / 3,408
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 未提供耐压试验方案文件**
   - 类型：`missing_pressure_test_plan`；证据状态：`grounded`；置信度：95%
   - 意见：当前资料包中仅包含设计文件（图纸目录、安装设计说明、管道材料设计说明、管道等级索引表、管道材料等级代号说明、管道分支表、管道壁厚表、管道平面图、管道特性表、综合材料表、管道强度计算书），未提供施工单位编制的《耐压试验方案》。根据规则要求，需审查耐压试验方案的审批手续及签字、试验时机、试验介质、升压速度、试验用压力表和温度计要求、安全措施、合格标准等内容，现有资料无法支持上述审查。
   - 证据：test-design-document-001 P2；test-design-document-001 P3
   - 规则/条款：engineering-inspection-r59；CREF-0DA14453814C1AE4；CREF-C03983D1C5E0274E
2. **[高] 证据不足，需人工确认**
   - 类型：`missing_quality_system_documentation`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P2
   - 规则/条款：engineering-inspection-r59；CREF-0DA14453814C1AE4
3. **[高] 证据不足，需人工确认**
   - 类型：`missing_signature_verification`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：未形成有效证据引用
   - 规则/条款：engineering-inspection-r59；CREF-0DA14453814C1AE4
4. **[高] 无法验证耐压试验关键参数**
   - 类型：`missing_test_parameters_verification`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test-design-document-001 P39；test-design-document-001 P40
   - 规则/条款：engineering-inspection-r59；CREF-C03983D1C5E0274E

### 节点 60｜试验用压力表、试验介质、介质温度、环境温度

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 61｜耐压试验压力、保压时间及结果

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 62｜耐压试验记录（报告）

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

# test｜耐压试验免除或替代

### 节点 63｜管道系统的柔性(应力)分析

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：103,356 / 3,137
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_stress_analysis_report`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P3；test-design-document-001 P50；test-design-document-001 P51
   - 规则/条款：engineering-inspection-r63；BUSINESS-RULE-R63；BUSINESS-RULE-R06；BUSINESS-RULE-R04
2. **[高] 无法判定是否满足耐压试验免除或替代条件**
   - 类型：`insufficient_evidence_for_exemption`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test-design-document-001 P38；test-design-document-001 P39；test-design-document-001 P40
   - 规则/条款：engineering-inspection-r63；BUSINESS-RULE-R63

### 节点 64｜现场检查替代性试验的过程

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 65｜无损检测报告和底片

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

# test｜泄漏试验

### 节点 66｜试验用压力表、试验介质、介质温度、环境温度、试验压力

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 67｜泄漏试验方法和试验报告

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

# test｜吹扫、清洗

### 节点 68｜吹扫、清洗

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 55%
- **意见草稿：** 证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：104,619 / 3,549
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 缺少吹扫、清洗方案及吹扫、清洗记录**
   - 类型：`missing_blowing_cleaning_plan_and_records`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test-design-document-001 P9；test-design-document-001 P10
   - 规则/条款：engineering-inspection-r68；CREF-0AACDBF3671261E1；CREF-4C52874A7BAB8A99；CREF-14D5262880FA278A
2. **[中] 证据不足，需人工确认**
   - 类型：`missing_blowing_cleaning_timing_verification`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P9
   - 规则/条款：engineering-inspection-r68；CREF-4C52874A7BAB8A99；CREF-14D5262880FA278A
3. **[中] 无法核验吹扫清洗介质、压力、顺序等参数**
   - 类型：`missing_blowing_cleaning_parameters_verification`；证据状态：`grounded`；置信度：90%
   - 意见：设计文件安装设计说明 4.5.2-4.5.4 规定了液体管道水冲洗流速不低于1.5m/s、空气吹扫流速不小于20m/s、蒸汽吹扫流速不小于30m/s等参数要求，管道特性表（EV-TEST-018-039、EV-TEST-018-040）显示各管段吹扫清洗介质为'水'，但现行资料中未见实际执行的吹扫清洗参数记录，无法核验实际参数是否满足设计及规范要求。
   - 证据：test-design-document-001 P9；test-design-document-001 P39；test-design-document-001 P40
   - 规则/条款：engineering-inspection-r68；CREF-4C52874A7BAB8A99；CREF-14D5262880FA278A
4. **[中] 证据不足，需人工确认**
   - 类型：`missing_blowing_cleaning_acceptance_result`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test-design-document-001 P9
   - 规则/条款：engineering-inspection-r68；CREF-4C52874A7BAB8A99；CREF-14D5262880FA278A

# test｜施工单位质量保证体系实施状况的评价

### 节点 69｜施工单位质量保证体系实施状况的评价

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

## test2 项目

# test2｜受检单位资质

### 节点 1｜设计单位许可资质

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 60%
- **意见草稿：** 设计许可证（DV-TEST2-002-V1）单位名称为“广东荣贵能源设备科技有限公司”，图纸标题栏（DV-TEST2-013-V1）亦显示“广东荣贵能源设备科技有限公司”，但图纸第9页出现“东莞市荣贵能源设备科校有限公司”字样，与许可证名称存在差异；同时图纸第11页出现“Guangdong Rongxui Energy technology Equipment CO.,LTD”的英文拼写差异。现有OCR证据可定位相关文本，但印章检测管线未启用，无法核验设计印章文字与许可证名称是否一致，需人工比对原件印章。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：37,113 / 4,268
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 设计许可证机构名称与图纸标题栏/印章一致性核查**
   - 类型：`设计许可证机构名称与图纸标题栏/印章一致性核查`；证据状态：`grounded`；置信度：60%
   - 意见：设计许可证（DV-TEST2-002-V1）单位名称为“广东荣贵能源设备科技有限公司”，图纸标题栏（DV-TEST2-013-V1）亦显示“广东荣贵能源设备科技有限公司”，但图纸第9页出现“东莞市荣贵能源设备科校有限公司”字样，与许可证名称存在差异；同时图纸第11页出现“Guangdong Rongxui Energy technology Equipment CO.,LTD”的英文拼写差异。现有OCR证据可定位相关文本，但印章检测管线未启用，无法核验设计印章文字与许可证名称是否一致，需人工比对原件印章。
   - 证据：test2-002 P1；test2-013 P1；test2-013 P9；test2-013 P11
   - 规则/条款：engineering-inspection-r01；CREF-8D47713A3A4F023D；CREF-7B62106F1C15EFC6
2. **[中] 设计许可范围覆盖管道级别核查**
   - 类型：`设计许可范围覆盖管道级别核查`；证据状态：`grounded`；置信度：65%
   - 意见：设计许可证许可子项目包含“工业管道(GC2)”和“公用管道(GB2)”。管道特性表（DV-TEST2-013-V1 第8页）显示管线NG-01管道类别为GC2。按规则GC2级别管道需具备GC2或GC1资质，现有许可证包含GC2，初步可覆盖。但管道特性表OCR存在截断，无法确认是否存在其他管线或更高级别管道（如GC1或GCD），需人工核对完整管道特性表。
   - 证据：test2-002 P1；test2-013 P8
   - 规则/条款：engineering-inspection-r01；CREF-D8EC66EEB10CA56C；CREF-4D684D994E20F008
3. **[中] 证据不足，需人工确认**
   - 类型：`设计许可证有效期覆盖施工期间核查`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-002 P1；test2-013 P1
   - 规则/条款：engineering-inspection-r01；CREF-8D47713A3A4F023D

### 节点 2｜施工单位许可资质

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：84,074 / 2,535
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-010 P1；test2-013 P8；test2-010 P5；test2-010 P6
   - 规则/条款：engineering-inspection-r02；CREF-8D47713A3A4F023D；CREF-BE7AEEC9B5E1F82D；CREF-4D684D994E20F008
2. **[中] 管道特性表中管道级别字段需人工复核确认**
   - 类型：`evidence_gap`；证据状态：`grounded`；置信度：95%
   - 意见：设计图纸管道特性表（DV-TEST2-013-V1 第 8 页）中管线号 NG-01 的
   - 证据：未形成有效证据引用
   - 规则/条款：—

### 节点 3｜无损检测机构核准资质

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：54,017 / 3,834
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-004 P4
   - 规则/条款：engineering-inspection-r03；BUSINESS-RULE-R03
2. **[中] 检测方案文件缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：80%
   - 意见：规则要求核查无损检测机构名称是否与检测方案中的名称一致，但现有资料中未提供检测方案文件。仅有设计图纸文件（DV-TEST2-013-V1），其中包含设计说明、材料表、管道数据表等，但未包含无损检测方案。需补充提供无损检测方案文件以完成机构名称一致性核查。
   - 证据：test2-013 P1
   - 规则/条款：engineering-inspection-r03；BUSINESS-RULE-R03
3. **[中] 施工计划工期文件缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：80%
   - 意见：规则要求核查无损检测机构核准证有效期是否能覆盖施工计划工期，但现有资料中未提供施工计划或工期安排文件。无法判断核准证有效期（2028年05月12日）是否能覆盖实际施工工期。需补充提供施工计划文件以完成有效期覆盖核查。
   - 证据：未形成有效证据引用
   - 规则/条款：engineering-inspection-r03；BUSINESS-RULE-R03
4. **[低] 设计文件检测方法要求未明确结构化**
   - 类型：`evidence_gap`；证据状态：`grounded`；置信度：95%
   - 意见：设计文件（DV-TEST2-013-V1）中提及
   - 证据：未形成有效证据引用
   - 规则/条款：—

# test2｜设计文件

### 节点 4｜设计文件的批准程序

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 60%
- **意见草稿：** 根据OCR识别的图纸目录（EV-TEST2-013-001），现有设计文件包括：图纸目录、设计说明书、材料表、主要承压元件计算书、管道数据表、管道平面布置图、管道轴测图。规范要求至少包括：图纸目录、设计说明书、管道数据表、管道布置图、管道材料一览表、直管强度计算书。现有'材料表'是否等同于'管道材料一览表'、'主要承压元件计算书'是否等同于'直管强度计算书'需人工确认。此外，规范要求的'管道材料等级表'、'设备布置图'、'管道应力计算书'在当前资料中未见明确体现。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：46,067 / 4,925
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 设计文件清单与规范要求的符合性需人工确认**
   - 类型：`设计文件完整性存疑`；证据状态：`grounded`；置信度：60%
   - 意见：根据OCR识别的图纸目录（EV-TEST2-013-001），现有设计文件包括：图纸目录、设计说明书、材料表、主要承压元件计算书、管道数据表、管道平面布置图、管道轴测图。规范要求至少包括：图纸目录、设计说明书、管道数据表、管道布置图、管道材料一览表、直管强度计算书。现有'材料表'是否等同于'管道材料一览表'、'主要承压元件计算书'是否等同于'直管强度计算书'需人工确认。此外，规范要求的'管道材料等级表'、'设备布置图'、'管道应力计算书'在当前资料中未见明确体现。
   - 证据：test2-013 P1
   - 规则/条款：engineering-inspection-r04；CREF-32252BABE2D526A8
2. **[中] 设计文件签字栏信息需人工核验**
   - 类型：`批准程序签字存疑`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-013 P2；test2-013 P4；test2-013 P8；test2-013 P10；test2-013 P11
   - 规则/条款：engineering-inspection-r04；CREF-32252BABE2D526A8；CREF-BE0860B3CDF86487
3. **[低] 管道级别判定及对应签字要求需人工确认**
   - 类型：`管道级别与签字要求匹配性存疑`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-013 P8
   - 规则/条款：engineering-inspection-r04；CREF-32252BABE2D526A8

### 节点 5｜施工图审查手续

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：53,421 / 2,416
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`missing_witness_material`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-012 P1；test2-013 P1
   - 规则/条款：engineering-inspection-r05；CREF-C7DFEF2D3859A6F8；CREF-54E9E1B6141FA698；CREF-A17587FAF33B8062
2. **[低] 印章检测管线未启用，无法核验设计批准印章**
   - 类型：`seal_detection_disabled`；证据状态：`grounded`；置信度：95%
   - 意见：图纸会审记录（DV-TEST2-012-V1）第1页勾选了
   - 证据：未形成有效证据引用
   - 规则/条款：—

### 节点 6｜强度计算书、管道应力分析计算书的审批手续

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 85%
- **意见草稿：** 本节点要求审查强度计算书、管道应力分析计算书的审批手续（三级或四级签字）。现有资料为设计图纸包（含图纸目录、设计说明、材料表、主要承压元件计算书、管道数据表、平面布置图、轴测图等），其中仅出现“主要承压元件计算书（RGG20260520-03）”的壁厚计算页，未见以“强度计算书/管道应力分析计算书”为名的独立文件，也未见覆盖本项目对应管线或管段的应力分析文件。因此无法核验其是否覆盖对应管线/管段、设计条件是否与设计文件一致，以及是否满足三级/四级签字要求。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：35,366 / 5,838
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 强度计算书/管道应力分析计算书未作为独立文件提供，无法核验审批手续**
   - 类型：`missing_document`；证据状态：`grounded`；置信度：85%
   - 意见：本节点要求审查强度计算书、管道应力分析计算书的审批手续（三级或四级签字）。现有资料为设计图纸包（含图纸目录、设计说明、材料表、主要承压元件计算书、管道数据表、平面布置图、轴测图等），其中仅出现“主要承压元件计算书（RGG20260520-03）”的壁厚计算页，未见以“强度计算书/管道应力分析计算书”为名的独立文件，也未见覆盖本项目对应管线或管段的应力分析文件。因此无法核验其是否覆盖对应管线/管段、设计条件是否与设计文件一致，以及是否满足三级/四级签字要求。
   - 证据：test2-013 P1；test2-013 P7；test2-013 P8
   - 规则/条款：RULE-ENG-INSP-R06；CREF-31BB29693B580253；CREF-5F9B641B36C2F0B7；CREF-937310485D6A7490
2. **[中] 主要承压元件计算书中采用的设计压力与管道特性表不一致，需人工核对计算书适用条件**
   - 类型：`inconsistency`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-013 P7；test2-013 P8
   - 规则/条款：RULE-ENG-INSP-R06；CREF-5F9B641B36C2F0B7
3. **[中] 主要承压元件计算书签字栏显示三级签字，但是否满足本节点四级签字触发条件无法判定**
   - 类型：`approval_signature_uncertain`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-013 P8；test2-013 P1
   - 规则/条款：RULE-ENG-INSP-R06；CREF-31BB29693B580253；CREF-5F9B641B36C2F0B7
4. **[中] 证据不足，需人工确认**
   - 类型：`coverage_uncertain`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P7；test2-013 P8；test2-013 P1
   - 规则/条款：RULE-ENG-INSP-R06；CREF-5F9B641B36C2F0B7；CREF-937310485D6A7490

### 节点 7｜设计变更的书面批准文件

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 90%
- **意见草稿：** 当前资料包仅包含初始设计图纸（图号RGG20260520系列），未发现任何设计变更文件、变更通知单或设计澄清文件。无法核验是否存在设计变更，亦无法核验变更文件是否盖设计许可章及是否有相应人员三级或四级签字。现有资料不支持对该监检项目作出符合性判断。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：33,643 / 3,356
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 未提供设计变更书面批准文件**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：90%
   - 意见：当前资料包仅包含初始设计图纸（图号RGG20260520系列），未发现任何设计变更文件、变更通知单或设计澄清文件。无法核验是否存在设计变更，亦无法核验变更文件是否盖设计许可章及是否有相应人员三级或四级签字。现有资料不支持对该监检项目作出符合性判断。
   - 证据：test2-013 P1
   - 规则/条款：engineering-inspection-r07；BUSINESS-RULE-R07；BUSINESS-RULE-R22；CREF-8278F02F838DC7CB；CREF-2B1BC36CE6C49104；CREF-0884A0BA5500262C
2. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P1
   - 规则/条款：engineering-inspection-r07；CREF-2B1BC36CE6C49104
3. **[中] 签字层级核验缺少管道等级与设计条件关联证据**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-013 P8
   - 规则/条款：engineering-inspection-r07；BUSINESS-RULE-R04；CREF-2B1BC36CE6C49104
4. **[中] 无法比对变更内容与原设计文件**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：85%
   - 意见：规则要求将变更内容与原设计文件对应，确认不是未批准的现场替代。当前资料包中仅有初始设计文件，无变更文件可供比对，无法执行该项核验。
   - 证据：test2-013 P1
   - 规则/条款：engineering-inspection-r07；BUSINESS-RULE-R22；CREF-0884A0BA5500262C

### 节点 8｜设计采用的安全技术规范以及相关标准、压力管道元件的材料标准的版本

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：42,367 / 5,259
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`standard_version_conflict`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P2
   - 规则/条款：RULE-ENG-INSP-R08；CREF-FA559F1E492FF306
2. **[低] 证据不足，需人工确认**
   - 类型：`standard_version_missing`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P2
   - 规则/条款：RULE-ENG-INSP-R08；CREF-8F8D040B7CB2779E；CREF-FA559F1E492FF306
3. **[低] 证据不足，需人工确认**
   - 类型：`standard_version_verification_required`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P5；test2-013 P6
   - 规则/条款：RULE-ENG-INSP-R08；CREF-DCCEC91117E5FC0C
4. **[低] 证据不足，需人工确认**
   - 类型：`standard_version_inconsistency`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P2；test2-013 P3
   - 规则/条款：RULE-ENG-INSP-R08；CREF-DCCEC91117E5FC0C

### 节点 9｜设计文件上注明的无损检测、防腐、耐压试验和泄漏试验要求

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 55%
- **意见草稿：** 证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：42,796 / 4,342
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 设计说明未明确无损检测的具体方法、检测比例及合格级别**
   - 类型：`设计文件无损检测要求不完整`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-013 P3
   - 规则/条款：engineering-inspection-r09；CREF-B5CF4CBED1D5ECF0；CREF-A4D107CB9E6B859B
2. **[中] 设计说明未规定泄漏性试验的具体要求**
   - 类型：`设计文件泄漏试验要求缺失`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-013 P3；test2-013 P8
   - 规则/条款：engineering-inspection-r09；CREF-B5CF4CBED1D5ECF0；CREF-A4D107CB9E6B859B
3. **[低] 防腐设计说明未明确涂层厚度验收标准及检测方法**
   - 类型：`设计文件防腐验收标准不完整`；证据状态：`grounded`；置信度：75%
   - 意见：设计说明'四、防腐设计说明'部分规定了防腐结构（零标高的氮气管道采用二道富锌环氧底漆每道不小于40μm，面漆涂刷二道聚氨酯面漆每道不小于40μm），但未明确涂层总厚度的验收标准、涂层附着力要求及检测方法。根据相关防腐标准要求，设计文件应当明确防腐涂层的验收 criteria。现有资料支持程度：部分支持（规定了单道涂层厚度要求，但未明确验收标准）。缺少的资料或证据：设计文件中关于防腐涂层总厚度验收标准、附着力要求及检测方法的明确规定。可能风险：施工单位可能因验收标准不明确而导致防腐质量争议。
   - 证据：test2-013 P3
   - 规则/条款：engineering-inspection-r09；CREF-B5CF4CBED1D5ECF0
4. **[低] 液压强度试验压力引用管道特性表，需核实参数完整性**
   - 类型：`耐压试验参数需人工核实`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-013 P3；test2-013 P8
   - 规则/条款：engineering-inspection-r09；CREF-A4D107CB9E6B859B

### 节点 10｜采用其他标准时，设计文件或工程规定中应包括符合《工业管道安全技术规程》基本安全的符合性申明及比照表

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

# test2｜施工组织设计

### 节点 11｜施工组织设计

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：45,949 / 4,530
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_document`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P1
   - 规则/条款：engineering-inspection-r11；BUSINESS-RULE-R11；TSG-D7006-D2.4.1
2. **[高] 建设单位批复文件缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：90%
   - 意见：根据规则要求，施工组织设计需经建设单位批复后方可实施。当前资料包中未发现建设单位对施工组织设计的批复文件。现有资料仅包含设计单位出具的设计图纸，未见建设单位（珠海盈德气体有限公司）对施工组织设计的审批意见或批复记录。
   - 证据：test2-013 P2
   - 规则/条款：engineering-inspection-r11；BUSINESS-RULE-R11
3. **[中] 施工组织设计审批签字信息缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：90%
   - 意见：规则要求施工组织设计应有编制、审核、审批人员签字。当前资料包中未提供施工组织设计文件，因此无法识别和验证相关人员的签字情况。设计图纸中虽有设计、校核、审核、审定等人员信息（如李悦恒、蔡如、林家云等），但这些属于设计文件签字，非施工组织设计的审批签字。
   - 证据：test2-013 P4
   - 规则/条款：engineering-inspection-r11；BUSINESS-RULE-R11
4. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P5；test2-013 P8
   - 规则/条款：engineering-inspection-r11；BUSINESS-RULE-R11
5. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P3
   - 规则/条款：engineering-inspection-r11；BUSINESS-RULE-R11；TSG-D7006-D2.4.1

# test2｜材料

### 节点 12｜压力管道元件及安全附件制造单位的许可资质

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 90%
- **意见草稿：** 规则要求提取许可证号并在全国特种设备公示信息查询平台核实，但现有资料中未提供查询平台的核实截图或查询结果记录。已识别的制造许可证（TS2753023—2029、TS2731N74-2028、TS2713486-2026）均未附平台核实证据。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：75,027 / 5,294
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 缺少全国特种设备公示信息查询平台的核实记录**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：90%
   - 意见：规则要求提取许可证号并在全国特种设备公示信息查询平台核实，但现有资料中未提供查询平台的核实截图或查询结果记录。已识别的制造许可证（TS2753023—2029、TS2731N74-2028、TS2713486-2026）均未附平台核实证据。
   - 证据：test2-015 P1；test2-017 P1；test2-018 P8
   - 规则/条款：engineering-inspection-r12；BUSINESS-RULE-R12
2. **[高] 证据不足，需人工确认**
   - 类型：`scope_coverage_gap`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P5；test2-015 P1
   - 规则/条款：engineering-inspection-r12；BUSINESS-RULE-R12；BUSINESS-RULE-R15
3. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-017 P1；test2-013 P5
   - 规则/条款：engineering-inspection-r12；BUSINESS-RULE-R12；BUSINESS-RULE-R15
4. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-018 P8；test2-018 P9；test2-018 P10；test2-013 P5
   - 规则/条款：engineering-inspection-r12；BUSINESS-RULE-R12；BUSINESS-RULE-R15
5. **[中] 缺少安全附件制造单位的许可资质资料**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：85%
   - 意见：规则要求审查压力管道元件及安全附件制造单位的许可资质，但现有资料中未提供安全附件（如安全阀、爆破片等）制造单位的许可资质资料。设计材料表中未见安全附件清单，需确认本工程是否涉及安全附件，如涉及则需补充相关资料。
   - 证据：test2-013 P5；test2-013 P6
   - 规则/条款：engineering-inspection-r12；BUSINESS-RULE-R12
6. **[低] 设计资料中管道特性表与材料表信息需人工核对一致性**
   - 类型：`cross_document_mismatch`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-013 P8；test2-013 P5
   - 规则/条款：engineering-inspection-r12；BUSINESS-RULE-R12

### 节点 13｜需制造监检或有型式试验要求的压力管道元件的监检证书、型式试验报告

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 90%
- **意见草稿：** 本节点要求先依据设计文件材料表识别哪些压力管道元件属于需制造监检或型式试验范围，再核对相应证书/报告是否覆盖本工程实际使用的元件。当前资料包中未提供设计文件材料表或管道元件清单，导致无法执行R13的覆盖性比对。现有资料仅能证明部分制造商持有型式试验证书，但无法判断其是否覆盖本工程实际使用的元件规格、材料、压力等级与数量。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：64,889 / 3,801
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 缺少设计文件材料表/管道元件清单，无法判定监检与型式试验覆盖范围**
   - 类型：`missing_design_material_list`；证据状态：`grounded`；置信度：90%
   - 意见：本节点要求先依据设计文件材料表识别哪些压力管道元件属于需制造监检或型式试验范围，再核对相应证书/报告是否覆盖本工程实际使用的元件。当前资料包中未提供设计文件材料表或管道元件清单，导致无法执行R13的覆盖性比对。现有资料仅能证明部分制造商持有型式试验证书，但无法判断其是否覆盖本工程实际使用的元件规格、材料、压力等级与数量。
   - 证据：test2-015 P1；test2-016 P1
   - 规则/条款：engineering-inspection-r13；BUSINESS-RULE-R15；BUSINESS-RULE-R04
2. **[中] 证据不足，需人工确认**
   - 类型：`missing_supervision_inspection_certificates`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-015 P1；test2-018 P1
   - 规则/条款：engineering-inspection-r13；BUSINESS-RULE-R15
3. **[中] 证据不足，需人工确认**
   - 类型：`type_test_coverage_not_verifiable`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-015 P2；test2-016 P1；test2-018 P9
   - 规则/条款：engineering-inspection-r13；BUSINESS-RULE-R15；BUSINESS-RULE-R08

### 节点 14｜不需制造许可、监检、型式试验的管道组成件的出厂检验报告，必要时进行现场抽查复验

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 15｜境外制造的压力管道元件、安全附件的型式试验证书及其制造单位的制造许可证资质

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 16｜压力管道元件以及安全附件产品质量证明文件

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：70,239 / 5,998
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`产品质量证明文件形式与印章无法核验`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-014 P1；test2-018 P3
   - 规则/条款：engineering-inspection-r16；CREF-9B6A46316602DDE4；CREF-13DE6D4BCA788F25
2. **[中] 证据不足，需人工确认**
   - 类型：`产品质量证明文件与设计材料表匹配性无法核验`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P5；test2-014 P1；test2-018 P3
   - 规则/条款：engineering-inspection-r16；CREF-595842D7953A6CC5；CREF-FE2319A8A97DC41F
3. **[中] 产品质量证明文件内容完整性无法核验**
   - 类型：`产品质量证明文件内容完整性无法核验`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-014 P1；test2-014 P2；test2-018 P3
   - 规则/条款：engineering-inspection-r16；CREF-3D1D049D6EA60044；CREF-9F0E905D8CCFDC7B
4. **[中] 产品质量证明文件批次覆盖与追溯无法核验**
   - 类型：`产品质量证明文件批次覆盖与追溯无法核验`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-013 P5；test2-014 P1；test2-018 P3
   - 规则/条款：engineering-inspection-r16；CREF-595842D7953A6CC5；CREF-FE2319A8A97DC41F
5. **[低] 产品质量证明文件检验结果数值核验无法完成**
   - 类型：`产品质量证明文件检验结果数值核验无法完成`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-014 P2；test2-018 P3
   - 规则/条款：engineering-inspection-r16；CREF-3D1D049D6EA60044；CREF-9F0E905D8CCFDC7B

### 节点 17｜压力管道元件以及安全附件产品验收的见证资料、抽样复验

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 18｜材料复验报告、无损检测报告

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 19｜使用境外牌号材料制造的压力管道元件以及安全附件，验证性复验结果

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 20｜新材料制造的压力管道元件以及安全附件的型式试验报告、技术评审、批准手续

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 21｜材料标志移植

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：57,233 / 2,253
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-014 P1；test2-018 P1
   - 规则/条款：engineering-inspection-r21；BUSINESS-RULE-R21；TSG-D7006-D2.4.1

### 节点 22｜材料代用

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

# test2｜阀门

### 节点 23｜阀门的施工资料和耐压试验记录（报告）

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 建议不符合，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：40,148 / 3,925
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_valve_test_records`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-014 P1；test2-018 P1
   - 规则/条款：engineering-inspection-r23；BUSINESS-RULE-R23；BUSINESS-RULE-R62
2. **[中] 证据不足，需人工确认**
   - 类型：`missing_valve_basis_and_sampling_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-014 P1；test2-018 P5
   - 规则/条款：engineering-inspection-r23；BUSINESS-RULE-R23
3. **[中] 证据不足，需人工确认**
   - 类型：`standard_parameter_card_missing`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-018 P1
   - 规则/条款：engineering-inspection-r23；BUSINESS-RULE-R23

# test2｜焊接（粘接）

### 节点 24｜焊工资格证及持证合格项目

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：15,157 / 3,166
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`evidence_insufficient`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-003 P1；test2-003 P1
   - 规则/条款：RULE-WELDER-202606；CREF-2FE510BF270BDBE3；CREF-FDB25674558F4D1B；CREF-8771A88BDA5933CB

### 节点 25｜焊接（粘接）工艺文件

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：50,413 / 2,759
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_welder_certificate`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-020 P1
   - 规则/条款：RULE-WELDER-202606；TSG-Z6002-3.2
2. **[中] 焊接记录与焊缝编号图缺失，无法建立焊工-焊缝追溯链**
   - 类型：`missing_welder_work_traceability`；证据状态：`grounded`；置信度：85%
   - 意见：规则要求将焊工资格证与焊接记录或焊缝编号图中的实际作业信息进行比对。当前资料包仅包含设计图纸（DV-TEST2-013-V1）和焊接工艺卡（DV-TEST2-020-V1），未提供焊接记录、焊缝编号图或焊工人员明细，无法将焊接工艺卡中声明的焊工持证项目（GTAW-Fe I (II,III)-6G-X/XFefs-02/11/13 和 SMAW-Fe I (II,III)-6G(K)-X/X-Fef3J）与实际施焊人员及焊缝进行关联核验。
   - 证据：test2-020 P1
   - 规则/条款：RULE-WELDER-202606；TSG-Z6002-3.2

### 节点 26｜焊接材料质量证明文件

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：51,655 / 2,727
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_welding_consumable_mtc`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P3；test2-013 P1
   - 规则/条款：engineering-inspection-r26；BUSINESS-RULE-R26；CREF-B5885FF5690DD64B；CREF-C1B87D95423DDD28；CREF-4E6243DB73DEB841；CREF-59759E45A07F924E；CREF-585740652068DA6C

### 节点 27｜焊接材料的验收、保管、发放、使用和回收的管理

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 28｜管道组对

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 29｜施焊参数、施焊记录、焊缝标识

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：31,927 / 4,130
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_welding_records`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-003 P1；test2-020 P1
   - 规则/条款：engineering-inspection-r29；CREF-EA8225D5DAFA7E26；CREF-846B8518EE288749；CREF-9B5CCA3FEFE3C78E
2. **[中] 焊工证缺少档案编号和合格作业项目结构化字段**
   - 类型：`welder_certificate_missing_qualified_items`；证据状态：`grounded`；置信度：85%
   - 意见：焊工证（姜军，证件编号 511621198504208836）OCR 识别结果显示发证机关印章缺失（issuer_seal_missing），且缺少档案编号（missing_archiveNo）和合格作业项目（missing_qualifiedItems）结构化字段。虽然 OCR 文本中包含项目代号 CTAF-Fe II-6G-3/57-FetS-02/11/12 和 SHAV-Fe II-6G(K)-9/57-Fet3J，有效期为 2025年10月至2029年09月，但缺乏发证机关印章可能导致证件有效性存疑。现有资料支持程度：可识别证件基本信息，但无法完成完整的证照真实性核验。
   - 证据：test2-003 P1
   - 规则/条款：engineering-inspection-r29；CREF-EA8225D5DAFA7E26
3. **[中] 证据不足，需人工确认**
   - 类型：`wps_pqr_traceability_incomplete`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-020 P1；test2-020 P2
   - 规则/条款：engineering-inspection-r29；CREF-846B8518EE288749；CREF-9B5CCA3FEFE3C78E

### 节点 30｜焊接接头外观质量

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 31｜焊缝返修

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 90%
- **意见草稿：** 根据规则R31要求，焊缝返修需提供返修申请单、返修工艺、返修审批手续（同一部位返修次数通常不得超过2次，超过需制定专项方案并经技术负责人批准）及返修后检测报告（如RT/UT）。当前提供的资料为焊接工艺评定报告（HP/P-2023-01），未包含任何焊缝返修相关记录。现有资料无法支持焊缝返修合规性判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：60,946 / 2,607
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 未提供焊缝返修申请单、返修工艺及返修审批手续**
   - 类型：`焊缝返修资料缺失`；证据状态：`grounded`；置信度：90%
   - 意见：根据规则R31要求，焊缝返修需提供返修申请单、返修工艺、返修审批手续（同一部位返修次数通常不得超过2次，超过需制定专项方案并经技术负责人批准）及返修后检测报告（如RT/UT）。当前提供的资料为焊接工艺评定报告（HP/P-2023-01），未包含任何焊缝返修相关记录。现有资料无法支持焊缝返修合规性判定。
   - 证据：test2-019 P1
   - 规则/条款：engineering-inspection-r31；BUSINESS-RULE-R31；CREF-BF9CF40BFC804561；CREF-F6C98AD6D4B2511C；CREF-993188B56E2FB3C1
2. **[低] 当前资料为焊接工艺评定报告，非焊缝返修工作见证**
   - 类型：`资料类型不匹配`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-019 P1；test2-019 P9
   - 规则/条款：engineering-inspection-r31；BUSINESS-RULE-R31

# test2｜热处理

### 节点 32｜焊接接头焊后热处理工艺文件

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 95%
- **意见草稿：** 现有资料中仅检索到《焊接工艺卡》(JH-HJGYK-01)，其
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：45,657 / 2,119
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 未提供经审批的焊后热处理工艺卡**
   - 类型：`missing_heat_treatment_procedure_card`；证据状态：`grounded`；置信度：95%
   - 意见：现有资料中仅检索到《焊接工艺卡》(JH-HJGYK-01)，其
   - 证据：未形成有效证据引用
   - 规则/条款：—

### 节点 33｜热处理设备用测温记录仪表

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：32,497 / 2,223
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P1；test2-013 P2
   - 规则/条款：engineering-inspection-r33；BUSINESS-RULE-R33

### 节点 34｜热处理记录、报告曲线、硬度检测报告

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 55%
- **意见草稿：** 证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：33,927 / 2,950
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 热处理记录、报告曲线、硬度检测报告缺失**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-013 P1；test2-013 P2；test2-013 P3
   - 规则/条款：engineering-inspection-r34；CREF-33450552F3FB061B；CREF-A251E33452490A91
2. **[中] 焊后热处理适用性无法判定**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-013 P5；test2-013 P8
   - 规则/条款：engineering-inspection-r34；CREF-A251E33452490A91

# test2｜无损检测

### 节点 35｜无损检测机构施工现场质量保证体系的实施

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：34,289 / 3,856
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_quality_system_manual`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-004 P1；test2-004 P2
   - 规则/条款：RULE-ENG-INSP-R35；BUSINESS-RULE-R35
2. **[高] 证据不足，需人工确认**
   - 类型：`missing_controlled_records_and_forms`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-004 P1
   - 规则/条款：RULE-ENG-INSP-R35；BUSINESS-RULE-R35
3. **[高] 未提供项目人员任命文件**
   - 类型：`missing_personnel_appointment_documents`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-004 P1
   - 规则/条款：RULE-ENG-INSP-R35；BUSINESS-RULE-R35
4. **[高] 证据不足，需人工确认**
   - 类型：`missing_equipment_calibration_reports`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-004 P2
   - 规则/条款：RULE-ENG-INSP-R35；BUSINESS-RULE-R35
5. **[中] 证据不足，需人工确认**
   - 类型：`quality_system_implementation_unverifiable`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-004 P6
   - 规则/条款：RULE-ENG-INSP-R35；BUSINESS-RULE-R35；BUSINESS-RULE-R69

### 节点 36｜无损检测方案

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 37｜检测过程中发现问题的处理

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：62,104 / 2,466
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-019 P1
   - 规则/条款：engineering-inspection-r37；BUSINESS-RULE-R37

### 节点 38｜无损检测人员资格证、执业注册证及持证合格项目

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 90%
- **意见草稿：** 规则要求提供无损检测人员明细表，但现有资料中未检索到该文件。无法确认项目实际参与无损检测的全部人员名单及其分工。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：15,815 / 3,593
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 无损检测人员明细表缺失**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：90%
   - 意见：规则要求提供无损检测人员明细表，但现有资料中未检索到该文件。无法确认项目实际参与无损检测的全部人员名单及其分工。
   - 证据：test2-005 P1
   - 规则/条款：engineering-inspection-r38；BUSINESS-RULE-R38
2. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-005 P1
   - 规则/条款：engineering-inspection-r38；BUSINESS-RULE-R38
3. **[低] 劳动合同证明文件未提供**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-005 P1；test2-005 P2
   - 规则/条款：engineering-inspection-r38；BUSINESS-RULE-R38
4. **[中] 证据不足，需人工确认**
   - 类型：`data_inconsistency`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-005 P2
   - 规则/条款：engineering-inspection-r38；BUSINESS-RULE-R38
5. **[低] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-005 P1；test2-005 P2
   - 规则/条款：engineering-inspection-r38；BUSINESS-RULE-R38

### 节点 39｜无损检测工艺文件

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：55,138 / 3,284
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_required_document`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-011 P2；test2-011 P4
   - 规则/条款：RULE-ENG-INSP-R39；BUSINESS-RULE-R39
2. **[中] 证据不足，需人工确认**
   - 类型：`incomplete_process_coverage`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-011 P1；test2-011 P2；test2-011 P6
   - 规则/条款：RULE-ENG-INSP-R39；BUSINESS-RULE-R39
3. **[中] 证据不足，需人工确认**
   - 类型：`missing_design_requirement_verification`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-011 P1
   - 规则/条款：RULE-ENG-INSP-R39；BUSINESS-RULE-R09

### 节点 40｜无损检测记录、报告

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 60%
- **意见草稿：** 现有资料包含焊接工艺评定报告（HP/P-2023-01）及射线检测报告（2023SHZH-022RTBG-01），但未见针对具体工程焊缝的单项无损检测记录与报告。无法核验委托单号、焊缝/部件编号、检测方法、检测比例、执行标准、设备、检测日期、检测人员、评定人员、评定级别、检测结果、结论、签字与签章等关键字段是否完整、一致并覆盖要求范围。需人工补充对应工程焊缝的无损检测记录、报告、委托单、检测方案及工艺文件进行比对。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：51,765 / 3,521
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 无损检测记录、报告字段与签署完整性无法自动核验**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：60%
   - 意见：现有资料包含焊接工艺评定报告（HP/P-2023-01）及射线检测报告（2023SHZH-022RTBG-01），但未见针对具体工程焊缝的单项无损检测记录与报告。无法核验委托单号、焊缝/部件编号、检测方法、检测比例、执行标准、设备、检测日期、检测人员、评定人员、评定级别、检测结果、结论、签字与签章等关键字段是否完整、一致并覆盖要求范围。需人工补充对应工程焊缝的无损检测记录、报告、委托单、检测方案及工艺文件进行比对。
   - 证据：test2-019 P9；test2-019 P12；test2-019 P13
   - 规则/条款：engineering-inspection-r40；NB-T-47013-NDT-REPORT；BUSINESS-RULE-R40
2. **[低] 射线检测报告人员与签章信息不完整**
   - 类型：`incomplete_record_fields`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-019 P13
   - 规则/条款：engineering-inspection-r40；NB-T-47013-NDT-REPORT；BUSINESS-RULE-R40
3. **[中] 设计文件对无损检测要求未提供，无法核验检测比例与合格级别**
   - 类型：`missing_design_requirement_traceability`；证据状态：`grounded`；置信度：50%
   - 意见：现有资料未提供设计文件或设计说明中关于无损检测方法、检测比例、合格级别的具体要求。射线检测报告虽显示检测比例100%、合格级别II级、执行标准NB/T47013.2-2015，但无法与设计文件进行比对，无法确认是否满足设计与规范要求。需人工补充设计文件并核对。
   - 证据：test2-019 P12
   - 规则/条款：engineering-inspection-r40；NB-T-47013-NDT-REPORT；BUSINESS-RULE-R40

### 节点 41｜射线检测底片抽查

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 55%
- **意见草稿：** 证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：52,762 / 3,668
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 射线检测底片实物/影像资料缺失，无法执行底片抽查**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-019 P12；test2-019 P13；test2-019 P9
   - 规则/条款：engineering-inspection-r41；BUSINESS-RULE-R41；NB-T-47013-NDT-REPORT
2. **[中] 射线检测报告存在但底片清单/焊缝编号映射缺失，无法完成抽查抽样**
   - 类型：`evidence_insufficient`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-019 P12；test2-019 P13
   - 规则/条款：engineering-inspection-r41；BUSINESS-RULE-R41
3. **[中] 证据不足，需人工确认**
   - 类型：`procedural_gap`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-019 P13
   - 规则/条款：engineering-inspection-r41；BUSINESS-RULE-R35；BUSINESS-RULE-R38

### 节点 42｜射线检测现场抽查

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：53,320 / 3,680
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_required_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-019 P12；test2-019 P9
   - 规则/条款：RULE-ENG-INSP-R42；CREF-549CA2867F266AB9；CREF-2FCD602C13E80104；CREF-BACD8535D0CD1DCF
2. **[中] 现有射线检测报告属于焊接工艺评定附件，未与现场抽查见证资料形成闭环**
   - 类型：`evidence_chain_break`；证据状态：`grounded`；置信度：85%
   - 意见：资料中包含射线检测报告（报告编号：2023SHZH-022RTBG-01，检件为焊接工艺评定试件，规格Φ219×7，材质20#，检测标准NB/T 47013.2-2015，技术等级AB级，结论I级合格），但该报告作为焊接工艺评定（HP/P-2023-01）的组成部分出现，未见与“射线检测现场抽查”对应的现场监检记录、底片/图像、抽查部位与焊口号映射、委托合同与委托单等闭环资料。依据本节点工作见证要求，需补充现场抽查底片/图像、记录、报告及（如适用）委托合同与委托单，以便人工核对抽查范围、人员、设备、工艺参数与评定结论的一致性。
   - 证据：test2-019 P12；test2-019 P13；test2-019 P9
   - 规则/条款：RULE-ENG-INSP-R42；CREF-2FCD602C13E80104；CREF-BACD8535D0CD1DCF

# test2｜防腐、保温

### 节点 43｜防腐及保温材料质量证明文件

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 55%
- **意见草稿：** 证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：43,538 / 3,350
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 防腐及保温材料质量证明文件缺失**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-013 P3
   - 规则/条款：engineering-inspection-r43；BUSINESS-RULE-R43；TSG-D7006-D2.4.1
2. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P3；test2-013 P8
   - 规则/条款：engineering-inspection-r43；BUSINESS-RULE-R43
3. **[中] 工厂化预制防腐管道元件出厂质量证明文件缺失**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-013 P5；test2-013 P6
   - 规则/条款：engineering-inspection-r43；BUSINESS-RULE-R43；TSG-D7006-D2.4.1

### 节点 44｜防腐、补口、补伤及保温

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 45｜防腐层电火花检测

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 46｜牺牲阳极、外加电流阴极保护、杂散电流排流装置

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：48,020 / 3,267
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-014 P1；test2-018 P1
   - 规则/条款：engineering-inspection-r46；CREF-AC749F12E31BD494；CREF-9AE4242E483645B4；CREF-5BC454DB621E0546
2. **[中] 设计文件中阴极保护/排流要求未见**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：90%
   - 意见：规则要求将施工记录与验收报告与设计文件中的阴极保护和排流要求进行比对。当前资料包中未包含设计文件（如管道特性表、防腐设计说明、阴极保护设计图等），无法确认设计是否要求设置阴极保护或杂散电流排流装置，也无法核对其类型、位置、数量及测试判据。
   - 证据：test2-014 P1
   - 规则/条款：engineering-inspection-r46；CREF-AC749F12E31BD494

### 节点 47｜静电接地

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 55%
- **意见草稿：** 证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：42,848 / 2,882
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 静电接地施工记录与验收报告缺失**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-013 P4
   - 规则/条款：engineering-inspection-r47；BUSINESS-RULE-R47；CREF-893D935A953DA102；CREF-2566B71AB59E9619
2. **[中] 设计文件静电接地要求与施工验证脱节**
   - 类型：`evidence_gap`；证据状态：`grounded`；置信度：90%
   - 意见：设计文件（DV-TEST2-013-V1 第4页）明确规定了静电接地技术要求：1）应符合SH/T 3097-2017《石油化工静电接地设计规范》；2）所有金属法兰连接处及平行敷设净距小于100mm的金属管道每隔20米跨接一次；3）跨接线采用6mm²铜线；4）防静电接地电阻值不大于100Ω，法兰间接触电阻值应小于0.03Ω。但现有资料中缺乏对应的施工记录、测试记录和验收报告，无法验证上述设计要求是否在施工中得到落实。
   - 证据：test2-013 P4
   - 规则/条款：engineering-inspection-r47；BUSINESS-RULE-R47

# test2｜穿跨越工程

### 节点 48｜穿跨越工程的管道结构、焊缝布置

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 49｜穿跨越工程施工

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 50｜套管防腐绝缘

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：43,115 / 3,139
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 证据不足，需人工确认**
   - 类型：`套管防腐绝缘检查记录缺失`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P1
   - 规则/条款：engineering-inspection-r50；BUSINESS-RULE-R50
2. **[低] 设计文件中未明确穿跨越段套管防腐绝缘要求**
   - 类型：`穿跨越工程设计信息不完整`；证据状态：`grounded`；置信度：85%
   - 意见：现有设计文件（设计说明书、管道特性表等）中未明确标注穿跨越段位置、套管规格、防腐等级、绝缘隔离要求等关键信息。虽然设计说明中提及了碳钢管道防腐要求（如Sa2.5级除锈、富锌环氧底漆等），但未针对穿跨越段钢套管的特殊防腐绝缘要求进行说明。
   - 证据：test2-013 P3；test2-013 P8
   - 规则/条款：engineering-inspection-r50；BUSINESS-RULE-R50
3. **[低] 未提供阴极保护系统相关资料**
   - 类型：`阴极保护相关信息缺失`；证据状态：`grounded`；置信度：80%
   - 意见：根据规则要求，当存在阴极保护时，套管内部需与管道绝缘隔离以防止阴极保护电流流失及电屏蔽腐蚀。现有资料中未发现任何关于阴极保护系统设计、施工或检测的记录，无法判断本项目是否涉及阴极保护要求。
   - 证据：test2-013 P1
   - 规则/条款：engineering-inspection-r50；BUSINESS-RULE-R50

### 节点 51｜绝缘支撑

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 55%
- **意见草稿：** 规则要求：当设计文件要求管道与支撑绝缘时，应抽查绝缘支撑检查记录。现有设计图纸（DV-TEST2-013-V1）中仅见“不锈钢管不得与碳钢管架直接接触，管架应刷绝缘漆，或在管路与管架间垫绝缘材料（如橡胶板、绝缘板等）”的表述，未见针对本项目氮气管道（NG-01，GC2）是否要求设置绝缘支撑的明确条款或节点详图。由于适用性取决于设计要求，当前资料不足以判定本项是否适用，也无法进入后续记录核查。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：43,315 / 3,091
- **质量门禁：** 需人工复核

#### AI findings

1. **[中] 设计文件中未明确绝缘支撑要求，无法判定是否适用本项检查**
   - 类型：`missing_design_requirement_for_insulated_support`；证据状态：`grounded`；置信度：55%
   - 意见：规则要求：当设计文件要求管道与支撑绝缘时，应抽查绝缘支撑检查记录。现有设计图纸（DV-TEST2-013-V1）中仅见“不锈钢管不得与碳钢管架直接接触，管架应刷绝缘漆，或在管路与管架间垫绝缘材料（如橡胶板、绝缘板等）”的表述，未见针对本项目氮气管道（NG-01，GC2）是否要求设置绝缘支撑的明确条款或节点详图。由于适用性取决于设计要求，当前资料不足以判定本项是否适用，也无法进入后续记录核查。
   - 证据：test2-013 P3；test2-013 P8
   - 规则/条款：engineering-inspection-r51；BUSINESS-RULE-R51；CREF-753055B8CA5F09FD；CREF-90702551AC80CDA1
2. **[中] 未提供绝缘支撑检查记录与绝缘测试记录，无法核查实施情况**
   - 类型：`missing_insulated_support_inspection_records`；证据状态：`grounded`；置信度：40%
   - 意见：规则要求抽查绝缘支撑检查记录（在设计有要求时适用），并核验绝缘材料、安装方式及绝缘测试等见证资料。当前资料包仅包含设计图纸（DV-TEST2-013-V1），未见绝缘支撑检查记录、绝缘材料证明、绝缘测试记录或现场影像证据。即使设计有要求，亦无法比对设计与施工的一致性，无法形成符合性结论。
   - 证据：test2-013 P1
   - 规则/条款：engineering-inspection-r51；BUSINESS-RULE-R51

# test2｜管道现场制作（预制）

### 节点 52｜管道现场制作（预制）

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

# test2｜管道安装

### 节点 53｜管道布管与连接方式、穿跨越

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 54｜补偿装置

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：47,404 / 3,138
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：未形成有效证据引用
   - 规则/条款：RULE-ENG-INSP-R54；CREF-63D25B8ABB39CD71；CREF-8C2B8D868BCFCFEF
2. **[高] 缺少管道补偿装置检查试验记录**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：95%
   - 意见：规则 RULE-ENG-INSP-R54 要求抽查管道补偿装置检查试验记录，以验证是否按照设计文件的规定进行预拉伸或者预压缩。现有资料中未检索到任何补偿装置检查试验记录，无法核实实际预拉伸/预压缩量是否按设计执行。
   - 证据：未形成有效证据引用
   - 规则/条款：RULE-ENG-INSP-R54；CREF-63D25B8ABB39CD71；CREF-8C2B8D868BCFCFEF
3. **[低] 现有资料为管件/管子质量证明文件，与补偿装置审查项无关**
   - 类型：`evidence_not_applicable`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-014 P1；test2-018 P1
   - 规则/条款：RULE-ENG-INSP-R54；CREF-63D25B8ABB39CD71；CREF-8C2B8D868BCFCFEF

### 节点 55｜支撑件

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 55%
- **意见草稿：** 证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：47,333 / 3,307
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 缺少管道支撑件检查试验记录**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-014 P1；test2-018 P1
   - 规则/条款：engineering-inspection-r55；CREF-63D25B8ABB39CD71；CREF-931286D94FBF2550
2. **[高] 缺少支撑件设计文件**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：95%
   - 意见：规则要求提供支撑件设计文件以核对支撑件位置、类型、规格型号和安装方式。当前资料包中未包含任何管道支撑件的设计文件（如管道支吊架设计图、支撑件布置图或管道应力分析相关支撑设计说明）。无法进行设计与实际安装的一致性比对。
   - 证据：test2-014 P1；test2-018 P1
   - 规则/条款：engineering-inspection-r55；CREF-63D25B8ABB39CD71；CREF-931286D94FBF2550
3. **[中] 缺少支撑件产品技术文件**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：90%
   - 意见：规则要求提供支撑件产品技术文件（如支吊架产品合格证、型式试验报告等），以验证产品技术文件是否匹配。当前资料包中的产品证明和型式报告（DV-TEST2-018-V1）仅覆盖管件（法兰、弯头、异径管等），未包含任何支撑件/支吊架的产品技术文件。
   - 证据：test2-018 P5；test2-018 P9
   - 规则/条款：engineering-inspection-r55；CREF-931286D94FBF2550

# test2｜安全附件

### 节点 56｜安全阀、爆破片和紧急切断阀的安装位置、规格和型号

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 55%
- **意见草稿：** 证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：66,902 / 3,333
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 安全阀、爆破片和紧急切断阀的制造许可证、型式试验证书、产品质量证明书缺失**
   - 类型：`missing_safety_accessory_documentation`；证据状态：`insufficient_evidence`；置信度：55%
   - 意见：证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。
   - 证据：test2-015 P1；test2-016 P1；test2-018 P1
   - 规则/条款：engineering-inspection-r56；CREF-F4C16066CA372C71；CREF-D4EC0671788DE080
2. **[高] 证据不足，需人工确认**
   - 类型：`missing_safety_accessory_installation_verification`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：未形成有效证据引用
   - 规则/条款：engineering-inspection-r56；CREF-F4C16066CA372C71
3. **[中] 证据不足，需人工确认**
   - 类型：`missing_design_documentation_for_safety_accessories`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：未形成有效证据引用
   - 规则/条款：engineering-inspection-r56；CREF-F4C16066CA372C71；CREF-D4EC0671788DE080

### 节点 57｜安全阀校验报告

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 58｜紧急切断阀性能测试报告

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

# test2｜耐压试验

### 节点 59｜耐压试验方案

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：42,632 / 3,400
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_pressure_test_plan`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P3；test2-013 P8
   - 规则/条款：RULE-ENG-INSP-R59；CREF-0DA14453814C1AE4；CREF-C03983D1C5E0274E
2. **[高] 耐压试验方案的审批签字证据缺失，A 类监检项目需人工确认**
   - 类型：`missing_signature_and_approval_evidence`；证据状态：`grounded`；置信度：90%
   - 意见：规则要求审查耐压试验方案的审批手续及签字。当前资料中未提供耐压试验方案文件，且印章/签字检测管线未启用（recognize_signatures_and_seals 返回 capability_disabled；recognize_document_seals 返回 capability_disabled），无法获取任何签字/签章事实。确定性工具 check_signature_completeness 与 evaluate_pressure_test 均返回 evidence_insufficient（原因：required_signature_roles_missing / pressure_plan_required_roles_missing）。该节点为 A 类监检项目，缺审批签字必须由人工确认。
   - 证据：test2-013 P1
   - 规则/条款：RULE-ENG-INSP-R59；CREF-0DA14453814C1AE4
3. **[中] 证据不足，需人工确认**
   - 类型：`missing_numeric_parameter_verification`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P3；test2-013 P8
   - 规则/条款：RULE-ENG-INSP-R59；CREF-C03983D1C5E0274E

### 节点 60｜试验用压力表、试验介质、介质温度、环境温度

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 61｜耐压试验压力、保压时间及结果

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 62｜耐压试验记录（报告）

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

# test2｜耐压试验免除或替代

### 节点 63｜管道系统的柔性(应力)分析

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 50%
- **意见草稿：** 模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：42,705 / 2,868
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 证据不足，需人工确认**
   - 类型：`missing_stress_analysis_report`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-013 P1；test2-013 P8
   - 规则/条款：RULE-ENG-INSP-R63；CREF-8407FC2486FE3FF0；CREF-38CBF14D50F4A585
2. **[高] 耐压试验免除或替代条件无法被现有资料支持**
   - 类型：`insufficient_evidence_for_exemption_or_substitution`；证据状态：`grounded`；置信度：90%
   - 意见：本节点属于“耐压试验免除或替代”类别，需以柔性（应力）分析报告作为关键证据之一。当前资料中仅有壁厚计算书（主要承压元件计算书）与管道特性表，未见任何针对管道系统柔性或应力分析的计算与结论，亦未见设计文件对免除或替代耐压试验的明确说明。依据证据仅能确认设计文件存在，但不足以支持免除或替代耐压试验的合规性判断。
   - 证据：test2-013 P7；test2-013 P8
   - 规则/条款：RULE-ENG-INSP-R63；CREF-8407FC2486FE3FF0；CREF-38CBF14D50F4A585

### 节点 64｜现场检查替代性试验的过程

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 65｜无损检测报告和底片

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 90%
- **意见草稿：** 规则要求'抽查不少于焊接接头总数50%的无损检测报告和底片'，但现有资料中未提供焊接接头总清单（含焊缝编号、总数）。当前OCR证据仅包含焊接工艺评定报告（HP/P-2023-01）及其配套无损检测报告（2023SHZH-022RTBG-01），属于工艺评定资料，而非工程安装焊缝清单。无法确定焊接接头总数，亦无法生成50%抽查样本。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：49,043 / 3,843
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 缺少焊接接头总清单及总数，无法计算50%抽查基数**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：90%
   - 意见：规则要求'抽查不少于焊接接头总数50%的无损检测报告和底片'，但现有资料中未提供焊接接头总清单（含焊缝编号、总数）。当前OCR证据仅包含焊接工艺评定报告（HP/P-2023-01）及其配套无损检测报告（2023SHZH-022RTBG-01），属于工艺评定资料，而非工程安装焊缝清单。无法确定焊接接头总数，亦无法生成50%抽查样本。
   - 证据：test2-019 P1
   - 规则/条款：engineering-inspection-r65；BUSINESS-RULE-R65
2. **[高] 缺少工程安装对应的无损检测报告清单与底片清单**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：90%
   - 意见：规则要求审查'无损检测报告和底片'并抽查不少于50%。现有资料仅包含焊接工艺评定试件的射线检测报告（报告编号2023SHZH-022RTBG-01，检件名称'试件'，管线号设备位号'SJ'），属于工艺评定过程记录，并非工程安装焊口的无损检测报告与底片清单。未见工程安装阶段的无损检测报告清单、底片清单及对应焊缝编号映射。
   - 证据：test2-019 P12；test2-019 P9
   - 规则/条款：engineering-inspection-r65；BUSINESS-RULE-R65；NB-T-47013-NDT-REPORT
3. **[高] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-019 P12
   - 规则/条款：engineering-inspection-r65；BUSINESS-RULE-R65；BUSINESS-RULE-R09
4. **[中] 证据不足，需人工确认**
   - 类型：`missing_evidence`；证据状态：`insufficient_evidence`；置信度：50%
   - 意见：模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件、OCR 文本、表格、印章和证据链后自行判定。
   - 证据：test2-019 P13
   - 规则/条款：engineering-inspection-r65；BUSINESS-RULE-R03；NB-T-47013-NDT-REPORT
5. **[中] 底片实物/数字影像未提供，无法执行底片质量抽查**
   - 类型：`missing_evidence`；证据状态：`grounded`；置信度：85%
   - 意见：规则要求'抽查不少于焊接接头总数50%的无损检测报告和底片'。现有资料仅包含射线检测报告文本内容，未提供底片实物或数字影像文件，无法核查底片质量（如黑度、像质计显示、标记、搭接等）是否符合NB/T47013.2-2015要求。
   - 证据：test2-019 P12
   - 规则/条款：engineering-inspection-r65；NB-T-47013-NDT-REPORT

# test2｜泄漏试验

### 节点 66｜试验用压力表、试验介质、介质温度、环境温度、试验压力

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

### 节点 67｜泄漏试验方法和试验报告

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。

# test2｜吹扫、清洗

### 节点 68｜吹扫、清洗

- **运行状态：** waiting_human_review（gap_precheck，仅作提示：是）
- **AI建议（待人工确认）：** 证据不足，置信度 95%
- **意见草稿：** 本节点要求抽查吹扫、清洗记录及方案（含吹扫和清洗的时机、介质、吹扫压力、顺序、安全事项和合格要求）。现有资料仅包含设计图纸及设计说明（含管道特性表中对吹扫介质的原则性描述），未提供施工单位的吹扫/清洗方案、吹扫/清洗记录、签字确认及验收结论等关键资料。因此无法核验吹扫清洗是否按方案及设计要求实施、参数是否合规、结果是否合格。
- **人工确认项：** 证据链、规则依据和条款适用性
- **模型：** qwen3.7-plus；输入/输出 token：43,975 / 2,923
- **质量门禁：** 需人工复核

#### AI findings

1. **[高] 未提供吹扫、清洗方案及记录，无法核验吹扫清洗合规性**
   - 类型：`missing_blowing_cleaning_plan_and_record`；证据状态：`grounded`；置信度：95%
   - 意见：本节点要求抽查吹扫、清洗记录及方案（含吹扫和清洗的时机、介质、吹扫压力、顺序、安全事项和合格要求）。现有资料仅包含设计图纸及设计说明（含管道特性表中对吹扫介质的原则性描述），未提供施工单位的吹扫/清洗方案、吹扫/清洗记录、签字确认及验收结论等关键资料。因此无法核验吹扫清洗是否按方案及设计要求实施、参数是否合规、结果是否合格。
   - 证据：test2-013 P3；test2-013 P8
   - 规则/条款：engineering-inspection-r68；BUSINESS-RULE-R68；CREF-0AACDBF3671261E1；CREF-4C52874A7BAB8A99；CREF-14D5262880FA278A
2. **[低] 设计文件仅给出吹扫介质原则性要求，缺少可执行的吹扫参数与验收标准**
   - 类型：`design_document_partial_support`；证据状态：`grounded`；置信度：85%
   - 意见：设计说明中提及“管道在试验合格后应进行吹扫。吹扫时应先吹扫主干管，在管段末端排放，然后吹扫支管，先返后远”，并在管道特性表中给出“清洗吹扫介质：压缩空气”。但未见吹扫压力、吹扫顺序细化、合格判定标准（如靶板要求、目视标准等）及安全事项的具体规定。现有资料支持程度有限，需结合施工方案及现场记录由监检人员确认。
   - 证据：test2-013 P3；test2-013 P8
   - 规则/条款：engineering-inspection-r68；CREF-4C52874A7BAB8A99；CREF-14D5262880FA278A

# test2｜施工单位质量保证体系实施状况的评价

### 节点 69｜施工单位质量保证体系实施状况的评价

> **平台状态：未发起AI审查。** 无正式挂载，需先由监检人员判断节点适用性。
