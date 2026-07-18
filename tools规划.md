# Tools 规划

> 生成源：`backend/business_packs/engineering_inspection_v1/atomic_checks.yaml`。本文件覆盖全部 194 个 atomicCheck；`implemented` 表示 Tool 链已实现，`pilot_implemented` 表示实现仍受试点范围或专业规则版本限制。R69 虽使用已实现的确定性 Tool，但 Tool 只校验证据、不生成业务结论。

## 1. 统一绑定协议

```text
atomicCheck → requiredFacts → tools → parameters → outputSchema
```

- 固定条款来自 ReviewRun 冻结的 `standardClausePackage`，LLM 不选择或替换条款。
- Tool Result 统一返回 `passed / failed / evidence_insufficient / not_applicable`；R19 另允许 `human_review_required`。
- 64 个重复证据追溯项统一使用 `validate_evidence_grounding`，但仍保留逐 atomicCheck 绑定，确保审计覆盖完整。
- R69 为人工评价边界：Tool 汇总 R01-R68 结果并校验评价报告字段，最终评价结论只能采用监检人员签发结果。
- 试点范围：R01-R03、R06-R07、R09、R12-R34、R60-R62。R19 使用 `llm_semantic_primary`，Tool负责取证和结构校验，固定聚合器生成节点 result。

## 2. 试点已实现 Tool

| Tool | 试点 | 作用 |
|---|---|---|
| `check_all_equal` | R01/R24 | 标准化机构名称或人员身份一致性 |
| `check_date_covers` | R01/R24 | 证照有效期覆盖业务周期 |
| `check_design_license_scope` | R01 | GC1、GC2、GCD 设计许可范围覆盖 |
| `decode_welder_qualification` | R24 | 解析焊工项目代号 |
| `check_welder_work_coverage` | R24 | 方法、材料、位置、厚度、管径覆盖 |
| `check_wps_pqr_coverage` | R25 | WPS/PQR 审批、对应关系、参数与生产条件覆盖 |
| `evaluate_welding_consumable` | R26 | 焊材质量证明、批号追溯、牌号规格和性能符合性 |
| `evaluate_welding_consumable_control` | R27 | 焊材验收、保管、烘干、发放、使用和回收闭环 |
| `evaluate_pipe_fit_up` | R28 | 错边、间隙、坡口和禁止强行组对 |
| `evaluate_welding_process` | R29 | 施焊参数、焊工资格、WPS 覆盖和焊缝追溯联动 |
| `evaluate_weld_appearance` | R30 | 外观缺陷、咬边及余高限值 |
| `evaluate_weld_repair` | R31 | 返修次数、审批、返修工艺和返修后检测 |
| `resolve_pwht_applicability` | R32/R34 | 基于材料、厚度、接头和设计要求统一判定热处理适用性 |
| `evaluate_heat_treatment` | R32/R34 | 热处理工艺卡及曲线、硬度结果的确定性审核 |
| `evaluate_heat_treatment_instruments` | R33 | 测温元件、温控/记录仪表校准和测温点布置 |
| `check_pressure_gauge_requirements` | R60 | 压力表数量、有效期、精度和量程 |
| `check_pressure_test_parameters` | R61 | 温度应力比、压力上下限、保压、气压分级升压和结果 |
| `check_pressure_test_report_consistency` | R62 | 报告、方案与现场参数一致性 |
| `validate_evidence_grounding` | 全局门禁 | 页码、坐标/原文、置信度和冲突检查 |
| `validate_r19_semantic_judgment` | R19 | 校验模型语义判断的Schema、固定条款和EvidenceRef，不改写业务结果 |

## 3. 全量绑定清单

### R01

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R01-01 | 核查设计许可证的机构名称是否与施工图纸标题栏和设计印章一致 | `designLicense.holderName`<br>`designDocument.titleBlockOrganization`<br>`designDocument.designSealOrganization` | `extract_document_fields`<br>`recognize_signatures_and_seals`<br>`check_all_equal`<br>`validate_evidence_grounding` | `profile=design_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`argumentProfile=r01_design_org_identity`<br>`normalizer=organization_name`<br>`requiredCount=3` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R01-02 | 核查设计许可证的范围根据设计文件中的施工说明、管道特性表，动力管道（GCD），在范围处一定要有GCD管道资质，GC2级别管道要有GC2或者GC1的资质，GC1级别管道要有GC1的资质 | `designLicense.scopeCodes`<br>`project.pipelineGrades` | `extract_document_fields`<br>`extract_table_records`<br>`check_design_license_scope`<br>`validate_evidence_grounding` | `profile=design_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`argumentProfile=r01_design_scope_project`<br>`scopeProfile=design-license-scope-cn-v1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R01-03 | 有效期：是否能覆盖住施工期间，因为施工期间也要有技术变更澄清事宜 | `designLicense.validFrom`<br>`designLicense.validUntil`<br>`project.constructionStart`<br>`project.plannedConstructionEnd`<br>`project.actualConstructionEnd`<br>`project.changeClarificationEnd` | `extract_document_fields`<br>`check_date_covers`<br>`validate_evidence_grounding` | `profile=design_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`argumentProfile=r01_design_license_period`<br>`coverageMode=closed_interval`<br>`periodEndPolicy=latest_of_planned_actual_change_clarification` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R01-04 | 找到设计许可证的范围，找到设计文件中的施工说明、管道特性表，动力管道（GCD）的施工范围，gcd管道资质要对应，对应的规则是：GC2级别管道要有GC2或者GC1的资质，GC1级别管道要有GC1的资质 | `designLicense.scopeCodes`<br>`designDocument.pipelineGrades` | `extract_document_fields`<br>`extract_table_records`<br>`check_design_license_scope`<br>`validate_evidence_grounding` | `profile=design_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`argumentProfile=r01_design_scope_documents`<br>`scopeProfile=design-license-scope-cn-v1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R01-05 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R02

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R02-01 | 核查安装许可证的范围、根据设计文件中的施工说明、管道特性表，动力管道（GCD），在范围处一定要有GCD管道资质或者A及锅炉安装资质，GC2级别管道要有GC2或者GC1或者GCD的资质，GC1级别管道要有GC1的资质 | `installationLicense.scopeCodes`<br>`project.pipelineGrades` | `extract_document_fields`<br>`extract_table_records`<br>`check_installation_license_scope`<br>`validate_evidence_grounding` | `profile=installation_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`argumentProfile=r02_installation_scope`<br>`scopeProfile=installation-license-scope-cn-v2` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R02-02 | 2、有效期：是否能覆盖住施工计划工期 | `installationLicense.validFrom`<br>`installationLicense.validUntil`<br>`project.constructionStart`<br>`project.plannedConstructionEnd` | `extract_document_fields`<br>`check_date_covers`<br>`validate_evidence_grounding` | `profile=installation_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`argumentProfile=r02_installation_license_period`<br>`coverageMode=closed_interval` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R02-03 | 如果不能覆盖，需要发联络单提醒 | `installationLicense.validFrom`<br>`installationLicense.validUntil`<br>`project.constructionStart`<br>`project.plannedConstructionEnd` | `check_date_covers`<br>`validate_evidence_grounding` | `profile=installation_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`argumentProfile=r02_installation_license_period`<br>`failureAction=CONTACT_NOTICE_REQUIRED`<br>`externalActionPolicy=recommendation_only` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R02-04 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R03

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R03-01 | 核查特种设备检验检测机构核准证，核查机构名称名称是否与检测方案的名称一致 | `ndtAgencies.agencies[].agencyId`<br>`ndtAgencies.agencies[].licenseOrganizationName`<br>`ndtAgencies.agencies[].planOrganizationName` | `extract_document_fields`<br>`evaluate_ndt_agencies`<br>`validate_evidence_grounding` | `profile=ndt_organization_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`argumentProfile=r03_agency_identity`<br>`evaluationMode=identity` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R03-02 | 核查核准项目代码所代表的检测项目是否满足设计文件要求的检测方法 | `ndtAgencies.agencies[].agencyId`<br>`ndtAgencies.agencies[].approvalItemCodes`<br>`ndtAgencies.agencies[].requiredMethods` | `extract_document_fields`<br>`extract_table_records`<br>`decode_ndt_approval_item_codes`<br>`evaluate_ndt_agencies`<br>`validate_evidence_grounding` | `profile=ndt_organization_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`argumentProfile=r03_method_coverage`<br>`evaluationMode=method_coverage`<br>`codeProfile=tsg-z7002-2022-table-a1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R03-03 | 3、有效期：是否能覆盖住施工计划工期，如果不能覆盖，需要发联络单提醒 | `ndtAgencies.agencies[].agencyId`<br>`ndtAgencies.agencies[].validFrom`<br>`ndtAgencies.agencies[].validUntil`<br>`ndtAgencies.agencies[].periodStart`<br>`ndtAgencies.agencies[].plannedPeriodEnd` | `extract_document_fields`<br>`evaluate_ndt_agencies`<br>`validate_evidence_grounding` | `profile=ndt_organization_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`argumentProfile=r03_date_coverage`<br>`evaluationMode=date_coverage`<br>`failureAction=CONTACT_NOTICE_REQUIRED`<br>`externalActionPolicy=recommendation_only` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R03-04 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R04

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R04-01 | 是否齐全：基本要求，至少包括图纸目录、设计说明书、管道数据表、管道布置图、管道材料一览表以及直管强度计算书， | `designDocumentSet.catalogListedDocumentTypes`<br>`designDocumentSet.uploadedDocumentTypes`<br>`designDocumentSet.parseableDocumentTypes` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_document_set_completeness`<br>`validate_evidence_grounding` | `profile=design_approval`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`requiredDocumentTypes=['drawing_catalog', 'design_specification', 'pipeline_data_sheet', 'pipeline_layout_drawing', 'pipeline_material_list', 'straight_pipe_strength_calculation']` | `deterministic-tool-result-v1` | `implemented` |
| AC-R04-02 | 批准程序：管道数据表、管道材料等级表、设备布置图、管道布置图、强度计算书和管道应力计算书等主要设计图样或者文件，应当有设计、校核、审核三级签字 | `designDocuments.documents`<br>`project.pipelines` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`recognize_signatures_and_seals`<br>`evaluate_design_document_approval`<br>`validate_evidence_grounding` | `profile=design_approval`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`approvalMode=three_level`<br>`targetDocumentTypes=['pipeline_data_sheet', 'pipeline_material_grade_table', 'equipment_layout_drawing', 'pipeline_layout_drawing', 'strength_calculation', 'pipeline_stress_calculation']`<br>`requiredRoles=['设计', '校核', '审核']`<br>`ruleVersion=r04-design-approval-tsg31-2025-v1` | `deterministic-tool-result-v1` | `implemented` |
| AC-R04-03 | 下列管道的材料等级表、应力计算书、设备布置图和管道布置图应当有设计、校核、审核、审定四级签字： | `designDocuments.documents`<br>`project.pipelines` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`recognize_signatures_and_seals`<br>`evaluate_design_document_approval`<br>`validate_evidence_grounding` | `profile=design_approval`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`approvalMode=four_level_conditional`<br>`targetDocumentTypes=['pipeline_material_grade_table', 'pipeline_stress_calculation', 'equipment_layout_drawing', 'pipeline_layout_drawing']`<br>`requiredRoles=['设计', '校核', '审核', '审定']`<br>`ruleVersion=r04-design-approval-tsg31-2025-v1`<br>`triggerProfile=gc1-or-gcd-pressure-temperature-v1` | `deterministic-tool-result-v1` | `implemented` |
| AC-R04-04 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R05

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R05-01 | 审查施工单位出具的施工图审查见证材料 | `drawingReviewWitness.document`<br>`drawingReviewWitness.issuer`<br>`drawingReviewWitness.signatures` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_document_set_completeness`<br>`validate_evidence_grounding` | `profile=drawing_review_witness`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R05-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R06

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R06-01 | 审查强度计算书、管道应力分析计算书是否覆盖本项目对应管线或管段，计算书名称、管道编号、设计压力、设计温度、介质、材料、规格等设计条件应与设计文件一致 | `calculationDocuments.documents[].documentId`<br>`calculationDocuments.documents[].documentType`<br>`calculationDocuments.documents[].bodyUploaded`<br>`calculationDocuments.documents[].coveredPipelineIds`<br>`calculationDocuments.documents[].parameterComparisons` | `extract_document_fields`<br>`extract_table_records`<br>`evaluate_calculation_document_consistency`<br>`validate_evidence_grounding` | `profile=calculation_approval`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`argumentProfile=r06_calculation_consistency`<br>`targetDocumentTypes=['strength_calculation', 'pipeline_stress_calculation']`<br>`ruleVersion=r06-calculation-consistency-v1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R06-02 | 强度计算书、管道应力分析计算书作为主要设计文件，应当有设计、校核、审核三级签字 | `calculationDocuments.documents` | `extract_document_fields`<br>`recognize_signatures_and_seals`<br>`evaluate_design_document_approval`<br>`validate_evidence_grounding` | `profile=calculation_approval`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`argumentProfile=r06_three_level_approval`<br>`approvalMode=three_level`<br>`targetDocumentTypes=['strength_calculation', 'pipeline_stress_calculation']`<br>`requiredRoles=['设计', '校核', '审核']`<br>`ruleVersion=r06-design-approval-tsg31-2025-3.1.3.3-v1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R06-03 | 对 GC1 级管道，或者设计压力大于等于 16.7MPa，或者 GCD 级管道设计压力大于等于 4.0MPa 且设计温度大于等于 570℃的，应当有设计、校核、审核、审定四级签字 | `calculationDocuments.documents`<br>`project.pipelines` | `extract_document_fields`<br>`recognize_signatures_and_seals`<br>`evaluate_design_document_approval`<br>`validate_evidence_grounding` | `profile=calculation_approval`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`argumentProfile=r06_four_level_approval`<br>`approvalMode=four_level_conditional`<br>`targetDocumentTypes=['pipeline_stress_calculation']`<br>`requiredRoles=['设计', '校核', '审核', '审定']`<br>`triggerProfile=gc1-or-gcd-pressure-temperature-v1`<br>`ruleVersion=r06-design-approval-tsg31-2025-3.1.3.3-v1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R06-04 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R07

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R07-01 | 是否盖设计许可章，是否有相应人员三级或者四级签字 | `designChanges.hasDesignChanges`<br>`designChanges.documents[].documentId`<br>`designChanges.documents[].documentType`<br>`designChanges.documents[].changedDocumentType`<br>`designChanges.documents[].writtenApproval`<br>`designChanges.documents[].originalDesignOrganizationName`<br>`designChanges.documents[].approvingOrganizationName`<br>`designChanges.documents[].signatureRoles`<br>`designChanges.documents[].designLicenseSeal`<br>`designChanges.documents[].coveredPipelineIds`<br>`project.pipelines` | `extract_document_fields`<br>`recognize_signatures_and_seals`<br>`evaluate_design_change_approval`<br>`verify_design_license_seals`<br>`validate_evidence_grounding` | `profile=design_change_approval`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`argumentProfile=r07_design_change_approval`<br>`approvalLevelPolicy=inherit_changed_document_and_pipeline`<br>`requiredDocumentTypes=['drawing_catalog', 'pipeline_layout_drawing']`<br>`expectedSealName=压力管道设计许可印章`<br>`sealPolicy=tsg31_2025_3.1.2_by_document_type`<br>`ruleVersion=r07-design-change-tsg31-2025-v1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R07-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R08

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R08-01 | 所采用的标准是现行有效的 | `design.standardReferences`<br>`standardCatalog.versionStatus`<br>`reviewDate` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_date_covers`<br>`check_standard_version_active`<br>`validate_evidence_grounding` | `profile=standard_version`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R08-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R09

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R09-01 | 审查设计说明：是否对无损检测、防腐和耐压试验和泄露性试验规定了具体要求，其相应要求应符合安全技术和标准规定 | `designSpecialRequirements.domains.ndt`<br>`designSpecialRequirements.domains.corrosion`<br>`designSpecialRequirements.domains.pressureTest`<br>`designSpecialRequirements.domains.leakTest`<br>`fixedClauses.designSpecialRequirementRules` | `extract_document_fields`<br>`extract_table_records`<br>`evaluate_design_special_requirements`<br>`validate_evidence_grounding` | `profile=design_special_requirements`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`argumentProfile=r09_design_special_requirements`<br>`domains=['ndt', 'corrosion', 'pressureTest', 'leakTest']`<br>`requiredPathsByDomain={'ndt': ['requirements.method', 'requirements.coverage', 'requirements.acceptanceCriteria'], 'corrosion': ['requirements.protectionMethod', 'requirements.acceptanceCriteria'], 'pressureTest': ['requirements.method', 'requirements.testPressure', 'requirements.acceptanceCriteria'], 'leakTest': ['requirements.method', 'requirements.testPressure', 'requirements.acceptanceCriteria']}`<br>`ruleVersion=r09-design-special-requirements-v1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R09-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R10

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R10-01 | 先判断设计文件或工程规定是否采用了非默认、境外、企业或其他替代标准 | `design.adoptedStandardType`<br>`comparisonDeclaration.document`<br>`comparisonTable.coveredSafetyTopics` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`check_conditional_requirement`<br>`evaluate_alternative_standard`<br>`validate_evidence_grounding` | `profile=alternative_standard`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R10-02 | 逐项判断比照表是否覆盖材料、设计、制造、安装、检验、试验等关键安全要求，缺少申明或比照不完整时要求人工确认 | `design.adoptedStandardType`<br>`comparisonDeclaration.document`<br>`comparisonTable.coveredSafetyTopics` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_scope_coverage`<br>`evaluate_alternative_standard`<br>`validate_evidence_grounding` | `profile=alternative_standard`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R10-03 | 若采用其他标准，继续查找符合《工业管道安全技术规程》基本安全要求的符合性申明和比照表 | `design.adoptedStandardType`<br>`comparisonDeclaration.document`<br>`comparisonTable.coveredSafetyTopics` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_conditional_requirement`<br>`evaluate_alternative_standard`<br>`validate_evidence_grounding` | `profile=alternative_standard`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R10-04 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R11

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R11-01 | 审查程序是否满足要求，应有编制、审核、审批人员签字，经建设单位批复后 | `constructionPlan.signatureRoles`<br>`constructionPlan.ownerApproval`<br>`constructionPlan.projectParameters`<br>`design.projectParameters`<br>`constructionPlan.processRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`evaluate_construction_plan`<br>`validate_evidence_grounding` | `profile=construction_plan`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R11-02 | 审查施工项目主要内容（如装置名称、管道规格、材质、长度等信息）是否与设计文件上内容一致 | `constructionPlan.signatureRoles`<br>`constructionPlan.ownerApproval`<br>`constructionPlan.projectParameters`<br>`design.projectParameters`<br>`constructionPlan.processRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`check_cross_document_match`<br>`evaluate_construction_plan`<br>`validate_evidence_grounding` | `profile=construction_plan`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R11-03 | 焊接、试验等内容是否满足施工标准要求 | `constructionPlan.signatureRoles`<br>`constructionPlan.ownerApproval`<br>`constructionPlan.projectParameters`<br>`design.projectParameters`<br>`constructionPlan.processRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`evaluate_construction_plan`<br>`validate_evidence_grounding` | `profile=construction_plan`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R11-04 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R12

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R12-01 | 制造许可证，提取许可证号在查询平台核实，并与设计资料中特性表、材料表的信息进行核实对应，主要看能不能覆盖本次工程所用管道元件 | `manufacturerLicense.number`<br>`manufacturerLicense.scope`<br>`component.materialTableItems`<br>`component.pipelineScheduleItems` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_cross_document_match`<br>`check_scope_coverage`<br>`evaluate_component_manufacturer_scope`<br>`validate_evidence_grounding` | `profile=component_manufacturer_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R12-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R13

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R13-01 | 型式试验证书（报告）检查覆盖范围是否符合设计文件中材料表的管道元件 | `r13.designItems`<br>`r13.typeTestReports` | `classify_r13_component_requirements`<br>`evaluate_r13_type_test_coverage` | `profile=component_type_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R13-02 | 监检证书是否齐全 | `r13.designItems`<br>`r13.supervisionCertificates` | `classify_r13_component_requirements`<br>`evaluate_r13_supervision_certificate_completeness` | `profile=component_type_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R13-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R14

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R14-01 | 审核出厂质量证明文件或抽查复验记录，比如螺栓螺母，查看等级材质是否符合设计文件要求（与材料表对应） | `r14.designItems`<br>`r14.factoryInspectionReports` | `classify_r14_component_applicability`<br>`evaluate_r14_component_design_match` | `profile=component_factory_inspection`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R14-02 | 审查光谱、硬度、金相、无损检测和耐压试验等报告 | `r14.designItems`<br>`r14.specialInspectionReports` | `resolve_r14_required_inspection_items`<br>`evaluate_r14_special_report_coverage` | `profile=component_factory_inspection`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`productInspectionRules={'GB/T 12771-2019': {'requiredItems': ['nondestructive_testing'], 'basis': 'GB/T 12771-2019 6.9'}}` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R14-03 | 设计文件中材料表、管道特性表压力等级对应 | `r14.designItems`<br>`r14.pipelineCharacteristics`<br>`r14.factoryInspectionReports`<br>`r14.specialInspectionReports` | `evaluate_r14_pressure_compatibility` | `profile=component_factory_inspection`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R14-04 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R15

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R15-01 | 仅依据制造国家、制造地点或明确结构化事实判断是否属于境外制造；不得把境外材料牌号当作境外制造事实。 | `r15.designItems` | `get_document_ocr_result`<br>`extract_table_records`<br>`classify_r15_foreign_manufacturing_applicability` | `profile=foreign_component`<br>`ruleVersion=r15-foreign-component-tsg31-2025-d7006-2020-v1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R15-02 | 依据TSG 31-2025第1.10、2.2.1.5条及TSG D7006-2020附件D D2.4.1，逐项分类制造许可、型式试验和制造监检要求。 | `r15.designItems` | `classify_r15_regulatory_requirements` | `profile=foreign_component`<br>`clauseSource=frozen_standard_clause_package`<br>`ruleVersion=r15-foreign-component-tsg31-2025-d7006-2020-v1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R15-03 | 需要制造许可的境外产品，其制造单位、官网人工核验状态和许可范围应覆盖本工程实际产品。 | `r15.designItems`<br>`r15.manufacturingLicenseCandidates`<br>`r15.manualRegistryVerifications` | `get_document_ocr_result`<br>`extract_document_fields`<br>`evaluate_r15_manufacturing_license_coverage` | `profile=foreign_component`<br>`requireRegistryVerification=True`<br>`ruleVersion=r15-foreign-component-tsg31-2025-d7006-2020-v1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R15-04 | 有型式试验要求的境外产品，其证书或报告应覆盖制造单位、产品类别、材料、结构、制造工艺及规格压力范围。 | `r15.designItems`<br>`r15.typeTestReports` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`evaluate_r15_type_test_coverage` | `profile=foreign_component`<br>`ruleVersion=r15-foreign-component-tsg31-2025-d7006-2020-v1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R15-05 | 对需要制造监检的境外产品核验境外制造监检、到岸检验或随锅炉压力容器整机安全性能检验的适用路径。 | `r15.designItems`<br>`r15.supervisionCertificates`<br>`r15.arrivalInspectionRecords`<br>`r15.completeMachineInspectionRecords` | `get_document_ocr_result`<br>`extract_document_fields`<br>`evaluate_r15_manufacturing_inspection_route` | `profile=foreign_component`<br>`ruleVersion=r15-foreign-component-tsg31-2025-d7006-2020-v1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R15-06 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R16

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R16-01 | 按设计规定的制造验收标准，将每项管道元件或安全附件绑定到已冻结的具体产品标准规则；标准未建模时不得判定为符合。 | `r16.designItems[].standardRef` | `resolve_r16_product_standard_profile` | `profile=r16_quality_certificate`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R16-02 | 按产品、规格、炉批号或产品编号逐项核验本工程到货元件是否具有唯一对应的产品质量证明文件。 | `r16.designItems`<br>`r16.qualityCertificates` | `evaluate_r16_quality_certificate_batch_coverage` | `profile=r16_quality_certificate`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R16-03 | 原件核验制造单位质量检验章；复印件必须同时核验经营单位公章和经办负责人章。 | `r16.qualityCertificates[].documentForm`<br>`r16.qualityCertificates[].manufacturerQualitySealPresent`<br>`r16.qualityCertificates[].dealerOfficialSealPresent`<br>`r16.qualityCertificates[].handlerResponsibleSealPresent` | `evaluate_r16_quality_certificate_form_and_seals` | `profile=r16_quality_certificate`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R16-04 | 逐批核对制造单位、产品名称、规格、材质、执行标准和交货状态是否符合设计材料表及特殊要求。 | `r16.designItems`<br>`r16.qualityCertificates` | `evaluate_r16_quality_certificate_design_match` | `profile=r16_quality_certificate`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R16-05 | 按具体产品标准核验质量证明文件核心字段、化学成分、力学性能、出厂检验项目及设计特殊检验项目是否齐全。 | `r16.designItems[].requiredInspectionItems`<br>`r16.qualityCertificates[].inspectionItems`<br>`r16.qualityCertificates[].conclusion` | `evaluate_r16_quality_certificate_content` | `profile=r16_quality_certificate`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R16-06 | 使用已冻结的结构化验收限值核验检验结果，并核验设计材料表、质量证明文件和实物标识的炉批号或产品编号一致。 | `r16.designItems[].acceptanceLimits`<br>`r16.designItems[].physicalMark`<br>`r16.qualityCertificates[].testResults` | `evaluate_r16_quality_certificate_results`<br>`evaluate_r16_batch_traceability` | `profile=r16_quality_certificate`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R16-07 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R17

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R17-01 | 按产品、规格、炉批号或产品编号核验每批到货元件是否具有唯一对应的验收记录。 | `r17.designItems`<br>`r17.acceptanceRecords` | `evaluate_r17_arrival_acceptance_batch_coverage` | `profile=r17_acceptance`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R17-02 | 核验质量证明、身份标识、外观、尺寸、结论记录和验收签字等质量体系验收步骤。 | `r17.acceptanceRecords[].completedSteps`<br>`r17.acceptanceRecords[].signatureRoles`<br>`r17.acceptanceRecords[].conclusion` | `evaluate_r17_acceptance_procedure` | `profile=r17_acceptance`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R17-03 | 根据设计要求或冻结抽样规则逐批确定是否需要抽样复验；触发条件不明时不得要求或豁免复验。 | `r17.designItems[].requiresSamplingRetest`<br>`r17.samplingRules` | `resolve_r17_sampling_retest_requirement` | `profile=r17_acceptance`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R17-04 | 仅对明确需要抽样复验的批次，核验取样见证记录、见证角色、样品编号和复验报告的连续证据链。 | `r17.designItems[].requiresSamplingRetest`<br>`r17.witnessRecords`<br>`r17.samplingRetestReports` | `evaluate_r17_sampling_witness_chain` | `profile=r17_acceptance`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R17-05 | 对验收不合格批次核验隔离、处置和放行批准，防止未受控材料投入使用。 | `r17.acceptanceRecords[].conclusion`<br>`r17.acceptanceRecords[].disposition` | `evaluate_r17_nonconformance_control` | `profile=r17_acceptance`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R17-06 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R18

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R18-01 | 依据设计要求和冻结规则逐批识别是否需要材料复验或材料本体无损检测；R18不作无条件必传审查。 | `r18.designItems[].requiresMaterialRetest`<br>`r18.designItems[].requiresMaterialNdt` | `classify_r18_material_test_applicability` | `profile=r18_material_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R18-02 | 为适用批次绑定具体产品标准、复验项目、材料NDT方法和结构化验收限值；规则不完整时返回证据不足。 | `r18.designItems[].standardRef`<br>`r18.designItems[].requiredRetestItems`<br>`r18.designItems[].requiredMaterialNdtMethods`<br>`r18.designItems[].acceptanceLimits` | `resolve_r18_material_test_requirement_profile` | `profile=r18_material_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R18-03 | 仅对明确需要材料复验的批次核验复验报告是否存在并覆盖全部要求的复验项目。 | `r18.designItems[].requiresMaterialRetest`<br>`r18.retestReports` | `evaluate_r18_material_retest_report_completeness` | `profile=r18_material_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R18-04 | 仅对明确需要材料本体无损检测的批次核验专用报告和检测方法；焊缝NDT报告不得替代。 | `r18.designItems[].requiresMaterialNdt`<br>`r18.materialNdtReports` | `evaluate_r18_material_ndt_report_completeness` | `profile=r18_material_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R18-05 | 核验材料复验和材料NDT报告的批准程序及试验、审核、批准等签字角色。 | `r18.retestReports[].signatureRoles`<br>`r18.materialNdtReports[].signatureRoles` | `evaluate_r18_material_report_approval_procedure` | `profile=r18_material_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R18-06 | 核验报告结论、结构化验收限值以及材料批号—样品号—报告号的追溯关系。 | `r18.designItems[].acceptanceLimits`<br>`r18.retestReports[].testResults`<br>`r18.materialNdtReports[].testResults` | `evaluate_r18_material_test_results_and_traceability` | `profile=r18_material_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R18-07 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R19

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R19-01 | 根据设计材料表、产品质量证明文件及材料牌号和执行标准，识别本工程是否使用境外牌号材料，并列明涉及元件、安全附件、制造单位、材料牌号、批次和使用范围。 | `r19.documents`<br>`r19.designMaterialItems`<br>`r19.qualityCertificates`<br>`r19.materialGrades` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`locate_evidence_fragment`<br>`validate_r19_semantic_judgment` | `profile=foreign_material_grade`<br>`executionMode=llm_semantic_primary`<br>`llmJudgmentRequired=True`<br>`fixedAggregatorRequired=True`<br>`failurePolicy=business_rule_result`<br>`semanticProfile=r19_applicability_and_scope`<br>`clauseSource=frozen_standard_clause_package` | `r19-semantic-judgment-v1` | `pilot_implemented` |
| AC-R19-02 | 核验境外材料标准是否为境外压力管道现行标准，并核验该材料是否具有类似工况使用经历；文件不能支持时不得推定满足。 | `r19.foreignMaterialStandards`<br>`r19.similarServiceEvidence` | `get_document_ocr_result`<br>`locate_evidence_fragment`<br>`validate_r19_semantic_judgment` | `profile=foreign_material_grade`<br>`executionMode=llm_semantic_primary`<br>`llmJudgmentRequired=True`<br>`fixedAggregatorRequired=True`<br>`failurePolicy=business_rule_result`<br>`semanticProfile=r19_standard_currency_and_service_experience`<br>`clauseSource=frozen_standard_clause_package` | `r19-semantic-judgment-v1` | `pilot_implemented` |
| AC-R19-03 | 对照境外材料标准、国内相近材料及企业标准，分析化学成分、力学性能、物理性能和工艺性能，确认不低于安全技术规范及相应国内材料标准的基本要求。 | `r19.foreignMaterialStandard`<br>`r19.domesticComparableStandard`<br>`r19.enterpriseStandard`<br>`r19.qualityCertificates` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`locate_evidence_fragment`<br>`validate_r19_semantic_judgment` | `profile=foreign_material_grade`<br>`executionMode=llm_semantic_primary`<br>`llmJudgmentRequired=True`<br>`fixedAggregatorRequired=True`<br>`failurePolicy=business_rule_result`<br>`semanticProfile=r19_composition_and_property_equivalence`<br>`clauseSource=frozen_standard_clause_package` | `r19-semantic-judgment-v1` | `pilot_implemented` |
| AC-R19-04 | 按材料牌号和炉批号关联产品质量证明文件与复验报告，核验化学成分和力学性能复验项目、试样或批次追溯、试验结果及结论。 | `r19.qualityCertificates`<br>`r19.materialRetestReports`<br>`r19.batchTraceability` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`locate_evidence_fragment`<br>`validate_r19_semantic_judgment` | `profile=foreign_material_grade`<br>`executionMode=llm_semantic_primary`<br>`llmJudgmentRequired=True`<br>`fixedAggregatorRequired=True`<br>`failurePolicy=business_rule_result`<br>`semanticProfile=r19_validation_retest`<br>`clauseSource=frozen_standard_clause_package` | `r19-semantic-judgment-v1` | `pilot_implemented` |
| AC-R19-05 | 先判断境外牌号材料是否首次使用；首次使用时核验焊接工艺评定覆盖材料组别、焊接方法、厚度和适用范围，非首次使用时应提供可追溯的使用经历依据。 | `r19.firstUseStatus`<br>`r19.similarServiceEvidence`<br>`r19.wpsPqr` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`locate_evidence_fragment`<br>`validate_r19_semantic_judgment` | `profile=foreign_material_grade`<br>`executionMode=llm_semantic_primary`<br>`llmJudgmentRequired=True`<br>`fixedAggregatorRequired=True`<br>`failurePolicy=business_rule_result`<br>`semanticProfile=r19_first_use_welding_qualification`<br>`clauseSource=frozen_standard_clause_package` | `r19-semantic-judgment-v1` | `pilot_implemented` |
| AC-R19-06 | 核验验证性复验结果和适用的焊接工艺评定结果是否纳入或者作为附件关联至产品质量证明文件，并形成证书号、报告号和炉批号追溯链。 | `r19.qualityCertificates`<br>`r19.materialRetestReports`<br>`r19.wpsPqr`<br>`r19.archiveLinks` | `get_document_ocr_result`<br>`locate_evidence_fragment`<br>`validate_r19_semantic_judgment` | `profile=foreign_material_grade`<br>`executionMode=llm_semantic_primary`<br>`llmJudgmentRequired=True`<br>`fixedAggregatorRequired=True`<br>`failurePolicy=business_rule_result`<br>`semanticProfile=r19_retest_and_pqr_archiving`<br>`clauseSource=frozen_standard_clause_package` | `r19-semantic-judgment-v1` | `pilot_implemented` |
| AC-R19-07 | 仅对境内制造单位使用境外牌号材料的情形，核验对应企业标准是否覆盖材料技术要求、验收规则、复验、首次使用工艺评定和质量证明归档要求；境外制造情形不得误判为缺少企业标准。 | `r19.manufacturerLocation`<br>`r19.enterpriseStandard`<br>`r19.foreignMaterialStandards`<br>`r19.retestRequirements`<br>`r19.wpsPqrRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`locate_evidence_fragment`<br>`validate_r19_semantic_judgment` | `profile=foreign_material_grade`<br>`executionMode=llm_semantic_primary`<br>`llmJudgmentRequired=True`<br>`fixedAggregatorRequired=True`<br>`failurePolicy=business_rule_result`<br>`semanticProfile=r19_domestic_manufacturer_enterprise_standard`<br>`clauseSource=frozen_standard_clause_package` | `r19-semantic-judgment-v1` | `pilot_implemented` |
| AC-R19-08 | 核验每项判断引用的文件版本、页码、坐标或原文片段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `r19.atomicJudgments[].evidenceRefIds`<br>`r19.evidenceIndex` | `locate_evidence_fragment`<br>`validate_r19_semantic_judgment`<br>`validate_evidence_grounding` | `profile=foreign_material_grade`<br>`executionMode=llm_semantic_primary`<br>`llmJudgmentRequired=True`<br>`fixedAggregatorRequired=True`<br>`failurePolicy=evidence_insufficient`<br>`semanticProfile=r19_evidence_traceability`<br>`clauseSource=frozen_standard_clause_package`<br>`minConfidence=0.75` | `r19-semantic-judgment-v1` | `pilot_implemented` |

### R20

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R20-01 | 逐项区分TSG 31-2025第2.1.3.1和2.1.3.2两类新材料并核验型式试验覆盖；第2.1.3.1分支还应核验技术评审通过及批准手续，第2.1.3.2分支应核验化学成分、拉伸、疲劳、断裂韧性和使用范围性能数据。 | `r20.designItems`<br>`r20.typeTestReports`<br>`r20.technicalReviewApprovals`<br>`r20.materialDataDocuments` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`classify_r20_new_material_applicability`<br>`evaluate_r20_new_material_procedure` | `profile=new_material`<br>`ruleVersion=r20-new-material-tsg31-2025-d7006-2020-v1`<br>`clauseSource=frozen_standard_clause_package` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R20-02 | 核验结论引用的型式试验报告、技术评审证书、批准文件或材料性能数据的文件、页码/坐标和原文字段可追溯；材料类别不明、证据缺失、冲突或OCR低置信度时不得判定为符合。 | `r20.designItems`<br>`r20.typeTestReports`<br>`r20.technicalReviewApprovals`<br>`r20.materialDataDocuments` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `profile=new_material`<br>`minConfidence=0.75` | `deterministic-tool-result-v1` | `pilot_implemented` |

### R21

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R21-01 | 先判定是否实际发生标志移植；发生时核验移植记录、原标志至移植标志的批次追溯、防混料措施、特殊材料种类抽查覆盖以及硬印和色标方法限制，未发生时结论为不适用。 | `r21.markTransferOccurred`<br>`r21.transferRecords`<br>`r21.materialInventory` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`evaluate_r21_mark_transfer` | `profile=material_mark_transfer`<br>`ruleVersion=r21-mark-transfer-gbt20801.1-2025-d7006-2020-v1`<br>`clauseSource=frozen_standard_clause_package` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R21-02 | 核验结论引用的标志移植记录、质量证明和实物标志证据可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `r21.transferRecords`<br>`r21.materialInventory` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `profile=material_mark_transfer`<br>`minConfidence=0.75` | `deterministic-tool-result-v1` | `pilot_implemented` |

### R22

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R22-01 | 先判定材料代用是否实际实施；仅有未实施采购建议时结论为不适用。实际代用应核验原设计单位书面批准、批准时间早于使用时间、批准范围及替代材料与实际使用一致。 | `r22.materialSubstitutionOccurred`<br>`r22.substitutionRecords`<br>`r22.actualMaterialUsage` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`evaluate_r22_material_substitution` | `profile=material_substitution`<br>`ruleVersion=r22-material-substitution-tsg31-2025-d7006-2020-v1`<br>`clauseSource=frozen_standard_clause_package` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R22-02 | 核验结论引用的设计变更单、原设计单位书面批准文件和材料实际使用记录可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `r22.substitutionRecords`<br>`r22.actualMaterialUsage` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `profile=material_substitution`<br>`minConfidence=0.75` | `deterministic-tool-result-v1` | `pilot_implemented` |

### R23

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R23-01 | 按设计文件、供货合同、缺省GB/T 13927-2022的优先级确定试验依据；按GB/T 20801.1-2025第7.2.4条核验GC1为100%、GC2为10%且不少于1个、GC3为5%且不少于1个，并核验工厂逐台见证豁免及抽样不合格处置。 | `r23.designStandardRefs`<br>`r23.contractStandardRefs`<br>`r23.designAndContractBasisChecked`<br>`r23.testLots` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`resolve_r23_valve_test_basis`<br>`evaluate_r23_valve_sampling` | `profile=valve_pressure_test`<br>`ruleVersion=r23-valve-test-gbt20801.1-2025-v1`<br>`clauseSource=frozen_standard_clause_package` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R23-02 | 逐台核验施工记录和耐压试验报告中的依据标准、壳体及密封试验介质、压力、保压时间、程序、泄漏和结论符合设计文件及选定标准；标准正文或参数卡不完整时结论只能为证据不足。 | `r23.constructionRecords`<br>`r23.testRecords`<br>`r23.standardRequirementProfiles`<br>`r23.designStandardRefs`<br>`r23.contractStandardRefs`<br>`r23.designAndContractBasisChecked` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`evaluate_r23_valve_test_records` | `profile=valve_pressure_test`<br>`ruleVersion=r23-valve-test-gbt20801.1-2025-v1`<br>`clauseSource=frozen_standard_clause_package`<br>`failClosedOnMissingStandardProfile=True` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R23-03 | 核验结论引用的设计文件、合同、阀门施工记录、耐压试验记录或报告的页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `r23.testRecords`<br>`r23.testLots` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `profile=valve_pressure_test`<br>`minConfidence=0.75` | `deterministic-tool-result-v1` | `pilot_implemented` |

### R24

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R24-01 | 核验焊工资格证原件或经核验复印件、人员身份及作业日期有效性；2026年8月1日前执行TSG Z6002-2010，达到新规生效日后若TSG Z6002-2026规则档案未完成验证则返回证据不足。 | `r24.certificates`<br>`r24.qualificationCodes`<br>`r24.workDate` | `extract_welder_certificate`<br>`decode_welder_qualification`<br>`check_welder_work_coverage` | `profile=r24_welder_qualification`<br>`argumentProfile=r24_certificate_validity_identity`<br>`transitionEffectiveDate=2026-08-01` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R24-02 | 按TSG Z6002附件A逐项解析实际焊接方法和母材类别覆盖；例如FeII可覆盖20钢所属FeI，但不得把示例材料固定为所有工程事实。 | `r24.certificates`<br>`r24.qualificationCodes`<br>`r24.workItems` | `decode_welder_qualification`<br>`check_welder_work_coverage` | `profile=r24_welder_qualification`<br>`argumentProfile=r24_method_material_identity` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R24-03 | 按项目代号和实际接头位置逐焊口核验位置覆盖；6G可覆盖相应全位置作业，其他代号按对应表格规则处理。 | `r24.qualificationCodes`<br>`r24.workItems` | `decode_welder_qualification`<br>`check_welder_work_coverage` | `profile=r24_welder_qualification`<br>`argumentProfile=r24_position_coverage` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R24-04 | 按考试试件厚度和外径动态计算覆盖范围，并核验填充金属及附加工艺因素；例如3/57对应的0-6mm和外径25mm以上仅是该代号的计算结果。 | `r24.qualificationCodes`<br>`r24.workItems` | `decode_welder_qualification`<br>`check_welder_work_coverage` | `profile=r24_welder_qualification`<br>`argumentProfile=r24_thickness_diameter_filler_factors` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R24-05 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R25

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R25-01 | 核验PQR和WPS本体均经审批生效，WPS明确引用支持它的PQR；焊接与粘接应进入各自评定分支，不得混用。 | `r25.wpsItems`<br>`r25.pqrItems`<br>`r25.workItems` | `extract_document_fields`<br>`extract_table_records`<br>`check_wps_pqr_coverage` | `profile=r25_wps_pqr`<br>`argumentProfile=r25_approval_and_link`<br>`failClosedOnMissingRange=True` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R25-02 | 逐项核验WPS电流、电压、焊接速度和层间温度范围处于PQR评定范围内，并将管线汇总表及施焊记录中的母材、方法、管径、壁厚和实际参数与WPS/PQR覆盖范围比对。 | `r25.wpsItems`<br>`r25.pqrItems`<br>`r25.workItems` | `extract_table_records`<br>`check_wps_pqr_coverage` | `profile=r25_wps_pqr`<br>`argumentProfile=r25_parameter_and_actual_coverage`<br>`failClosedOnMissingRange=True` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R25-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R26

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R26-01 | 核验焊条、焊丝、焊剂MTC包含化学成分和力学性能实测数据，按焊材类别、牌号和执行标准绑定已冻结验收限值，并与实物或验收记录批号一致；产品标准规则未建模时不得判定符合。 | `r26.qualityCertificates`<br>`r26.physicalItems`<br>`r26.productStandardProfiles` | `extract_document_fields`<br>`extract_table_records`<br>`evaluate_welding_consumable` | `profile=r26_welding_consumable_mtc`<br>`argumentProfile=r26_mtc_results_batch`<br>`failClosedOnMissingStandardProfile=True` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R26-02 | 核验焊材牌号、规格和产品标准符合设计；超过制造方说明或管理文件规定的库存期限时应有复验合格证据，不得把库存期限误作证书统一有效期。 | `r26.qualityCertificates`<br>`r26.designRequirements`<br>`r26.physicalItems` | `extract_document_fields`<br>`evaluate_welding_consumable` | `profile=r26_welding_consumable_mtc`<br>`argumentProfile=r26_design_and_inventory_period` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R26-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R27

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R27-01 | 联查焊材验收、库房温湿度、烘干保温、领用、实际使用和剩余回收记录，并以牌号和批号建立连续追溯链。 | `r27.managementRecords`<br>`r27.controlRequirements` | `extract_document_fields`<br>`extract_table_records`<br>`evaluate_welding_consumable_control` | `profile=r27_welding_consumable_control`<br>`argumentProfile=r27_record_set` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R27-02 | 按设计、产品说明书或冻结管理要求核验烘干温度时间、保温和储存条件，识别混用、错用及超过库存期限未复验的焊材。 | `r27.managementRecords`<br>`r27.controlRequirements` | `extract_table_records`<br>`evaluate_welding_consumable_control` | `profile=r27_welding_consumable_control`<br>`argumentProfile=r27_drying_holding_mix_expiry` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R27-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R28

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R28-01 | 按材料类别和壁厚计算GB/T 20801.1-2025第7.4.4.3条错边量限值，核验组对间隙、坡口角度符合设计/WPS，并核验除设计预拉伸外未强行组对。 | `r28.fitUpRecords` | `extract_document_fields`<br>`extract_table_records`<br>`evaluate_pipe_fit_up` | `profile=r28_pipe_fit_up`<br>`argumentProfile=r28_numeric_and_forced_fit` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R28-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R29

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R29-01 | 核验施工记录包含焊口、焊工、电流、电压、焊接速度、层间温度和清晰焊缝标识；逐焊口复用R24焊工资格覆盖和R25 WPS/PQR覆盖规则，保证真实可追溯。 | `r29.weldingRecords`<br>`r29.certificates`<br>`r29.wpsItems`<br>`r29.pqrItems`<br>`r29.workItems` | `extract_document_fields`<br>`extract_table_records`<br>`evaluate_welding_process` | `profile=r29_welding_record`<br>`argumentProfile=r29_linked_r24_r25_traceability` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R29-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R30

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R30-01 | 核验外观检查记录对应焊口、检验等级、接头类型和壁厚；设计或监检方案要求照片时核验照片与焊口可追溯。 | `r30.appearanceRecords`<br>`r30.photoRequired` | `extract_document_fields`<br>`evaluate_weld_appearance` | `profile=r30_weld_appearance`<br>`argumentProfile=r30_record_and_photo` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R30-02 | 按GB/T 20801.1-2025表43及设计更严要求核验裂纹、未熔合、表面气孔、外露夹渣、咬边和余高；焊缝宽度仅在设计或WPS给出范围时自动判定，缺少限值时返回证据不足。 | `r30.appearanceRecords` | `extract_table_records`<br>`evaluate_weld_appearance` | `profile=r30_weld_appearance`<br>`argumentProfile=r30_table43_and_design_wps` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R30-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R31

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R31-01 | 核验返修申请、原因分析、合格返修工艺和返修后同方法复检；同一部位返修次数大于2次时核验修订专项措施及技术负责人批准，热处理后返修还应核验重新热处理。 | `r31.repairOccurred`<br>`r31.repairRecords` | `extract_document_fields`<br>`extract_table_records`<br>`evaluate_weld_repair` | `profile=r31_weld_repair`<br>`argumentProfile=r31_repair_procedure_count_ndt` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R31-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R32

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R32-01 | 按材料组、控制厚度、强度、接头例外及设计要求解析焊口级热处理适用性；适用时核验工艺卡经审批、基于评定报告，并核验升温速率、保温温度、保温时间和降温速率符合表36及第7.6.4条。 | `r32.weldItems`<br>`r32.procedureCards`<br>`r32.qualificationReports` | `extract_document_fields`<br>`extract_table_records`<br>`resolve_pwht_applicability`<br>`evaluate_heat_treatment` | `profile=heat_treatment_procedure`<br>`argumentProfile=r32_shared_applicability_and_procedure` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R32-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R33

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R33-01 | 核验热电偶、温控仪和自动温度记录仪均有覆盖使用日期的校准/校验证书，并核验测温点布置图与实际焊口和加热范围对应。 | `r33.weldItems`<br>`r33.instrumentRecords`<br>`r33.temperaturePointLayouts`<br>`r33.reviewDate` | `extract_document_fields`<br>`resolve_pwht_applicability`<br>`evaluate_heat_treatment_instruments` | `profile=r33_heat_treatment_instruments`<br>`argumentProfile=r33_shared_applicability_calibration_and_layout` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R33-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R34

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R34-01 | 复用R32焊口级热处理适用性；适用时核验自动温度-时间曲线完整无中断、报告参数可追溯，并核验局部热处理100%及炉内热处理每批不少于10%的焊缝和热影响区硬度检测覆盖。 | `r34.weldItems`<br>`r34.heatTreatmentReports`<br>`r34.hardnessReports` | `extract_document_fields`<br>`extract_table_records`<br>`resolve_pwht_applicability`<br>`evaluate_heat_treatment` | `profile=heat_treatment_result`<br>`argumentProfile=r34_curve_report_hardness` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R34-02 | 优先执行设计硬度限值；再按GB/T 20801.1-2025表36材料组条件执行200、225、241或250HBW等限值，表中无值时执行不超过母材硬度125%的规则。洛氏/维氏读数必须有换算标准和换算后的HBW，不得把碳钢200HB、合金钢225HB作为无条件通用限值。 | `r34.weldItems`<br>`r34.heatTreatmentReports`<br>`r34.hardnessReports` | `extract_table_records`<br>`resolve_pwht_applicability`<br>`evaluate_heat_treatment` | `profile=heat_treatment_result`<br>`argumentProfile=r34_material_conditioned_hardness` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R34-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R35

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R35-01 | 工作见证：需提供无损检测单位质量保证手册、受控记录及报告表格、项目人员任命文件、检测仪器及其他必要设备的检定报告 | `ndtQuality.manual`<br>`ndtQuality.controlledForms`<br>`ndtQuality.appointments`<br>`ndtEquipment.calibrationReports` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_date_covers`<br>`evaluate_ndt_quality_system`<br>`validate_evidence_grounding` | `profile=ndt_quality_system`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R35-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R36

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R36-01 | 工作见证：需提供无损检测方案 | `ndtPlan.document`<br>`ndtPlan.methods`<br>`ndtPlan.ratios`<br>`design.ndtRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_ndt_process`<br>`validate_evidence_grounding` | `profile=ndt_plan`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R36-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R37

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R37-01 | 工作见证：需提供检测单位不合格品的控制处理措施程序、无损检测委托单、对不合格品开出的联络单或意见书、不合格品处理的反馈见证文件 | `ndtNonconformance.procedure`<br>`ndtNonconformance.commission`<br>`ndtNonconformance.notice`<br>`ndtNonconformance.feedback` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_ndt_nonconformance`<br>`validate_evidence_grounding` | `profile=ndt_nonconformance`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R37-02 | 标准规范：无损检测单位质量保证手册中有关不合格品与不符合项控制程序文件、NB/T 47013.1-2015《承压设备无损检测 第1部分：通用要求》、NB/T 47013.2-2015《承压设备无损检测 第2部分：射线检测》、NB/T 47013.3-2023《承压设备无损检测 第3部分：超声检测》等 | `ndtNonconformance.procedure`<br>`ndtNonconformance.commission`<br>`ndtNonconformance.notice`<br>`ndtNonconformance.feedback` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_ndt_nonconformance`<br>`validate_evidence_grounding` | `profile=ndt_nonconformance`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R37-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R38

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R38-01 | 工作见证：需提供无损检测人员明细表、无损检测人员资格证和执业注册证，必要时提供无损检测人员劳动合同证明文件 | `ndtPersonnel.roster`<br>`ndtPersonnel.qualificationCodes`<br>`ndtPersonnel.registration`<br>`actualNdt.workItems` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_conditional_requirement`<br>`check_ndt_personnel_coverage`<br>`validate_evidence_grounding` | `profile=ndt_personnel`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R38-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R39

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R39-01 | 工作见证：需提供相关单项无损检测工艺文件、操作指导书 | `ndtProcedure.method`<br>`ndtProcedure.parameters`<br>`ndtProcedure.instruction`<br>`design.ndtRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_ndt_process`<br>`validate_evidence_grounding` | `profile=ndt_procedure`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R39-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R40

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R40-01 | 工作见证：需提供相关单项无损检测记录、报告 | `ndtRecord.weldIds`<br>`ndtRecord.parameters`<br>`ndtReport.results`<br>`design.ndtRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`evaluate_ndt_process`<br>`validate_evidence_grounding` | `profile=ndt_record_report`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R40-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R41

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R41-01 | 工作见证：需提供相关所有射线检测底片 | `radiographicFilms.inventory`<br>`radiographicFilm.imageQuality`<br>`radiographicFilm.weldId`<br>`ndtReport.weldIds` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_rt_film`<br>`validate_evidence_grounding` | `profile=rt_film_sampling`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R41-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R42

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R42-01 | 工作见证：需提供射线检测现场抽查的底片、记录和报告 | `siteSampling.films`<br>`siteSampling.records`<br>`siteSampling.reports`<br>`siteSampling.weldIds` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`evaluate_rt_film`<br>`validate_evidence_grounding` | `profile=rt_site_sampling`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R42-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R43

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R43-01 | 工厂化预制的防腐管道元件需提供出厂质量证明文件，必要时提供型式试验证书、压力管道元件制造许可、制造监督检验证书 | `coatingMaterial.qualityCertificate`<br>`coatingMaterial.typeTest`<br>`coatingMaterial.manufacturingLicense`<br>`coatingMaterial.supervisionCertificate` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`check_numeric_range`<br>`check_conditional_requirement`<br>`evaluate_corrosion_protection`<br>`validate_evidence_grounding` | `profile=coating_material`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R43-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R44

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R44-01 | 工作见证：防腐施工及检查记录、保温施工及检查记录 | `coating.constructionRecords`<br>`coating.inspectionRecords`<br>`insulation.constructionRecords`<br>`insulation.inspectionRecords` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`evaluate_corrosion_protection`<br>`validate_evidence_grounding` | `profile=coating_insulation_process`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R44-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R45

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R45-01 | 工作见证：电火花检测仪检定报告、防腐层电火花检测记录和报告 | `holidayDetector.calibrationValidity`<br>`coatingHolidayTest.parameters`<br>`coatingHolidayTest.results` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_date_covers`<br>`evaluate_corrosion_protection`<br>`validate_evidence_grounding` | `profile=holiday_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R45-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R46

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R46-01 | 工作见证：牺牲阳极、外加电流阴极保护、杂散电流排流装置施工记录和验收报告 | `cathodicProtection.deviceType`<br>`cathodicProtection.constructionRecords`<br>`cathodicProtection.acceptanceResults` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`evaluate_corrosion_protection`<br>`validate_evidence_grounding` | `profile=cathodic_protection`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R46-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R47

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R47-01 | 工作见证：静电接地施工记录和验收报告 | `staticGrounding.constructionRecords`<br>`staticGrounding.measuredResults`<br>`staticGrounding.acceptanceResults` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`evaluate_corrosion_protection`<br>`validate_evidence_grounding` | `profile=static_grounding`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R47-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R48

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R48-01 | 抽查管道结构、焊缝布置施工检查记录或现场抽查是否符合相关标准及设计要求（如管道穿越墙、道路时应设套管保护，套管内的管段不宜有环焊缝存在，如有应进行100%无损检测等） | `crossing.structure`<br>`crossing.weldLayout`<br>`crossing.sleeveSegments`<br>`crossing.ndtCoverage`<br>`design.crossingRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`evaluate_pipeline_installation`<br>`validate_evidence_grounding` | `profile=crossing_weld_layout`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R48-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R49

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R49-01 | 抽查穿跨越工程施工及检查记录是否符合技术规范、相关标准及设计文件的要求 | `crossing.constructionRecords`<br>`crossing.inspectionRecords`<br>`design.crossingRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`evaluate_pipeline_installation`<br>`validate_evidence_grounding` | `profile=crossing_construction`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R49-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R50

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R50-01 | 抽查套管防腐绝缘检查记录（如穿跨越段钢套管一般外部需要进行防腐，内部与管道绝缘隔离（有阴极保护时），以防止阴极保护电流的流失及可能造成的套管内管段电屏蔽腐蚀） | `sleeve.externalCoating`<br>`sleeve.internalInsulation`<br>`project.hasCathodicProtection`<br>`inspection.records` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`evaluate_corrosion_protection`<br>`validate_evidence_grounding` | `profile=sleeve_insulation`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R50-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R51

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R51-01 | 抽查绝缘支撑检查记录（当设计文件要求管道与支撑绝缘时，应进行 | `design.requiresInsulatedSupport`<br>`insulatedSupport.inspectionRecords`<br>`insulatedSupport.results` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`check_conditional_requirement`<br>`evaluate_pipeline_installation`<br>`validate_evidence_grounding` | `profile=insulated_support`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R51-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R52

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R52-01 | 现场抽查预制管道的焊接、焊后热处理质量（对加工制作、焊接、热处理、检查、检测、试验等进行抽查） | `prefabrication.weldRecords`<br>`prefabrication.heatTreatmentRecords`<br>`prefabrication.ndtRecords`<br>`prefabrication.testRecords` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_sampling_requirement`<br>`evaluate_pipeline_installation`<br>`validate_evidence_grounding` | `profile=site_prefabrication`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R52-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R53

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R53-01 | 抽查管道布管与连接方式穿跨越检查试验记录（如不得用强力对口、加热管子、加偏垫或者加多层垫等方法来消除接口端面的空隙、偏斜、错口或者不同轴等缺陷 | `installation.alignmentRecords`<br>`installation.connectionMethod`<br>`installation.prohibitedMethods`<br>`equipment.anchorStatus` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`evaluate_pipeline_installation`<br>`validate_evidence_grounding` | `profile=pipe_connection`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R53-02 | 与设备的连接应当在设备安装定位紧固地脚螺栓后自然地进行） | `installation.alignmentRecords`<br>`installation.connectionMethod`<br>`installation.prohibitedMethods`<br>`equipment.anchorStatus` | `get_document_ocr_result`<br>`extract_document_fields`<br>`evaluate_pipeline_installation`<br>`validate_evidence_grounding` | `profile=pipe_connection`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R53-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R54

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R54-01 | 抽查管道补偿装置检查试验记录（按照设计文件的规定进行预拉伸或者预压缩） | `compensator.type`<br>`compensator.prestretch`<br>`compensator.precompression`<br>`design.compensatorRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`evaluate_pipeline_installation`<br>`validate_evidence_grounding` | `profile=compensator`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R54-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R55

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R55-01 | 抽查管道支撑件检查试验记录 | `support.type`<br>`support.location`<br>`support.inspectionResults`<br>`design.supportRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`evaluate_pipeline_installation`<br>`validate_evidence_grounding` | `profile=pipe_support`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R55-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R56

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R56-01 | 审查安全附件的制造许可证、型式试验证书、产品质量证明书等，设计、制造是否符合技术规范的要求 | `safetyAccessory.license`<br>`safetyAccessory.typeTest`<br>`safetyAccessory.qualityCertificate`<br>`safetyAccessory.location`<br>`safetyAccessory.model`<br>`design.safetyAccessoryRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_safety_accessory`<br>`validate_evidence_grounding` | `profile=safety_accessory_installation`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R56-02 | 现场实物抽查安装位置、规格、型号、铭牌等是否符合设计文件等的要求 | `safetyAccessory.license`<br>`safetyAccessory.typeTest`<br>`safetyAccessory.qualityCertificate`<br>`safetyAccessory.location`<br>`safetyAccessory.model`<br>`design.safetyAccessoryRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`check_cross_document_match`<br>`check_sampling_requirement`<br>`evaluate_safety_accessory`<br>`validate_evidence_grounding` | `profile=safety_accessory_installation`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R56-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R57

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R57-01 | 审查安全阀校验报告中的开启压力、密封压力等是否符合安全技术规范等的要求 | `safetyValve.calibrationReport`<br>`safetyValve.openingPressure`<br>`safetyValve.sealingPressure`<br>`design.setPressure` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`check_numeric_range`<br>`evaluate_safety_accessory`<br>`validate_evidence_grounding` | `profile=safety_valve_calibration`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R57-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R58

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R58-01 | 审查紧急切断阀性能测试报告中功能测试项目及内容等 | `emergencyValve.testReport`<br>`emergencyValve.functionItems`<br>`emergencyValve.results` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_safety_accessory`<br>`validate_evidence_grounding` | `profile=emergency_valve_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R58-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R59

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R59-01 | 审查耐压试验方案（审批手续及签字，耐压试验的时机、试验介质、升压速度、试验用压力表和温度计的要求、试验采取的安全措施、合格标准等） | `pressureTestPlan.signatureRoles`<br>`pressureTestPlan.timing`<br>`pressureTestPlan.medium`<br>`pressureTestPlan.pressurizationRate`<br>`pressureTestPlan.instrumentRequirements`<br>`pressureTestPlan.safetyMeasures`<br>`pressureTestPlan.acceptanceCriteria` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_numeric_range`<br>`evaluate_pressure_test`<br>`validate_evidence_grounding` | `profile=pressure_test_plan`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R59-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R60

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R60-01 | 现场检查试验用压力表、试验介质、介质温度、环境温度（如压力表不得少于2块，并在检定有效期内，精度不得低于1.6级，量程为最大试验压力的1.5~2倍等） | `pressureTest.gauges`<br>`pressureTest.maxTestPressure`<br>`pressureTest.testDate`<br>`pressureTest.medium`<br>`pressureTest.mediumTemperature`<br>`pressureTest.ambientTemperature` | `extract_document_fields`<br>`extract_table_records`<br>`check_pressure_gauge_requirements`<br>`validate_evidence_grounding` | `profile=pressure_gauge`<br>`minGaugeCount=2`<br>`maxAccuracyClass=1.6`<br>`rangeRatio=[1.5, 2.0]` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R60-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R61

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R61-01 | 现场检查耐压试验压力、保压时间及结果（如液压试验时，试验压力为设计压力的1.5倍（不考虑温度系数），保压时间不应少于10min | `pressureTest.method`<br>`pressureTest.designPressure`<br>`pressureTest.testPressure`<br>`pressureTest.holdMinutes`<br>`pressureTest.testResult`<br>`pressureTest.allowableStressAtTestTemperature`<br>`pressureTest.allowableStressAtDesignTemperature`<br>`pressureTest.maximumAllowableTestPressure` | `extract_document_fields`<br>`check_pressure_test_parameters`<br>`validate_evidence_grounding` | `profile=pressure_test_parameters`<br>`ruleProfileVersion=pressure-test-parameters-gbt20801-v2` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R61-02 | 气压试验时，试验压力不低于设计压力的1.1倍等） | `pressureTest.method`<br>`pressureTest.designPressure`<br>`pressureTest.testPressure`<br>`pressureTest.holdMinutes`<br>`pressureTest.testResult`<br>`pressureTest.maximumAllowableTestPressure`<br>`pressureTest.pneumaticYieldLimitPressure`<br>`pressureTest.pressureSteps` | `extract_document_fields`<br>`extract_table_records`<br>`check_pressure_test_parameters`<br>`validate_evidence_grounding` | `profile=pressure_test_parameters`<br>`ruleProfileVersion=pressure-test-parameters-gbt20801-v2` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R61-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R62

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R62-01 | 现场检查耐压试验记录（报告）（记录或报告中采用的标准、试验参数、保压时间、耐压试验结果是否符合技术规范、相关标准及设计文件的要求） | `pressureTestReport.standardRef`<br>`pressureTestReport.parameters`<br>`pressureTestPlan.parameters`<br>`pressureTestObserved.parameters`<br>`pressureTestReport.result` | `extract_document_fields`<br>`check_pressure_test_report_consistency`<br>`validate_evidence_grounding` | `profile=pressure_test_report`<br>`numericTolerance=0.001` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R62-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R63

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R63-01 | 检查由设计单位出具的管道系统柔性（应力）分析报告 | `stressAnalysis.issuer`<br>`stressAnalysis.coveredSystems`<br>`stressAnalysis.designParameters`<br>`design.pipelineSystems` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_stress_analysis`<br>`validate_evidence_grounding` | `profile=stress_analysis`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R63-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R64

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R64-01 | 现场检查敏感性泄漏试验（试验方法和要求是否符合技术规范、相关标准及设计文件的要求） | `sensitiveLeakTest.method`<br>`sensitiveLeakTest.parameters`<br>`sensitiveLeakTest.results`<br>`design.leakTestRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_leak_test`<br>`validate_evidence_grounding` | `profile=sensitive_leak_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R64-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R65

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R65-01 | 审查无损检测报告内容是否符合技术规范、相关标准及设计文件的要求 | `ndtReport.inventory`<br>`radiographicFilms.inventory`<br>`weldInventory.totalCount`<br>`sampling.selectedWeldIds` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_rt_film`<br>`validate_evidence_grounding` | `profile=ndt_report_film_sampling`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R65-02 | 抽查不少于焊接接头总数50%的无损检测报告和底片 | `ndtReport.inventory`<br>`radiographicFilms.inventory`<br>`weldInventory.totalCount`<br>`sampling.selectedWeldIds` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`check_sampling_requirement`<br>`evaluate_rt_film`<br>`validate_evidence_grounding` | `profile=ndt_report_film_sampling`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R65-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R66

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R66-01 | 检查试验用压力表（直径、量程、精度检定有效期）、试验介质、介质温度、试验环境温度、试验压力（试验压力为设计压力） | `leakTest.gauges`<br>`leakTest.medium`<br>`leakTest.mediumTemperature`<br>`leakTest.ambientTemperature`<br>`leakTest.testPressure`<br>`design.designPressure` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_date_covers`<br>`check_numeric_range`<br>`evaluate_leak_test`<br>`validate_evidence_grounding` | `profile=leak_test_instruments`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R66-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R67

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R67-01 | 检查泄漏试验方法和报告（泄漏试验包括敏感性泄漏试验和气密性试验，应按设计文件规定的方法和要求进行，试验报告采用的标准、试验参数、保压时间、耐压试验结果等是否符合技术规范、相关标准及设计文件的要求） | `leakTest.method`<br>`leakTestReport.standardRef`<br>`leakTestReport.parameters`<br>`leakTestReport.holdMinutes`<br>`leakTestReport.result`<br>`design.leakTestRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`check_numeric_range`<br>`evaluate_leak_test`<br>`validate_evidence_grounding` | `profile=leak_test_report`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R67-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R68

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R68-01 | 抽查吹扫、清洗记录及方案（吹扫和清洗的时机、吹扫和清洗的介质、吹扫压力、吹扫和清洗的顺序、安全事项和合格要求） | `blowingCleaning.plan`<br>`blowingCleaning.timing`<br>`blowingCleaning.medium`<br>`blowingCleaning.pressure`<br>`blowingCleaning.sequence`<br>`blowingCleaning.safetyMeasures`<br>`blowingCleaning.acceptanceResult` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`check_numeric_range`<br>`evaluate_blowing_cleaning`<br>`validate_evidence_grounding` | `profile=blowing_cleaning`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R68-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R69

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R69-01 | 核验监检人员签发的评价报告是否存在且覆盖当前工程，并包含评价结果、评价人员、评价日期和签发信息；Tool不得生成或改写评价结果。 | `qualitySystemEvaluation.report`<br>`qualitySystemEvaluation.result`<br>`qualitySystemEvaluation.evaluator`<br>`qualitySystemEvaluation.evaluationDate`<br>`qualitySystemEvaluation.coveredProjectId`<br>`reviewRun.nodeResults` | `locate_evidence_fragment`<br>`extract_document_fields`<br>`check_document_set_completeness`<br>`validate_evidence_grounding` | `profile=construction_quality_system_evaluation`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result`<br>`requiredReportFields=['result', 'evaluator', 'evaluationDate', 'coveredProjectId']`<br>`automatedDecisionAllowed=False` | `manual-evaluation-evidence-result-v1` | `implemented` |
| AC-R69-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `qualitySystemEvaluation.report`<br>`qualitySystemEvaluation.result`<br>`qualitySystemEvaluation.evaluator`<br>`qualitySystemEvaluation.evaluationDate`<br>`qualitySystemEvaluation.coveredProjectId`<br>`reviewRun.nodeResults` | `locate_evidence_fragment`<br>`extract_document_fields`<br>`check_document_set_completeness`<br>`validate_evidence_grounding` | `profile=construction_quality_system_evaluation`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=evidence_insufficient`<br>`requiredReportFields=['result', 'evaluator', 'evaluationDate', 'coveredProjectId']`<br>`automatedDecisionAllowed=False` | `manual-evaluation-evidence-result-v1` | `implemented` |

## 4. 运行时约束

1. `requiredFacts` 缺失时返回 `evidence_insufficient`，不得推定为符合。
2. `parameters.profile` 必须随 ReviewRun 冻结并记录版本。
3. 正式判断必须保存 Tool 名称、版本、输入输出 Hash、EvidenceRef 和 ClauseRef。
4. 默认节点中LLM只能解释Tool Result；R19例外允许LLM形成逐原子项语义判断，但必须通过Schema/EvidenceRef校验，节点result仍由固定聚合器生成。
5. `pilot_implemented` 项进入正式放行前仍须完成专业规则样例验收；缺少事实、证据或规则参数时固定返回 `evidence_insufficient`。
