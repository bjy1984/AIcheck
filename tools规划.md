# Tools 规划

> 生成源：`backend/business_packs/engineering_inspection_v1/atomic_checks.yaml`。本文件覆盖全部 171 个 atomicCheck；`implemented` 表示 Tool 链已实现，`pilot_implemented` 表示实现仍受试点范围或专业规则版本限制。

## 1. 统一绑定协议

```text
atomicCheck → requiredFacts → tools → parameters → outputSchema
```

- 固定条款来自 ReviewRun 冻结的 `standardClausePackage`，LLM 不选择或替换条款。
- Tool Result 统一返回 `passed / failed / evidence_insufficient / not_applicable`。
- 68 个重复证据追溯项统一使用 `validate_evidence_grounding`，但仍保留逐 atomicCheck 绑定，确保审计覆盖完整。
- 试点范围：R01、R12、R48、R49、R50。

## 2. 试点已实现 Tool

| Tool | 试点 | 作用 |
|---|---|---|
| `check_all_equal` | R01/R12 | 标准化机构名称或人员身份一致性 |
| `check_date_covers` | R01/R12 | 证照有效期覆盖业务周期 |
| `check_design_license_scope` | R01 | GC1、GC2、GCD 设计许可范围覆盖 |
| `decode_welder_qualification` | R12 | 解析焊工项目代号 |
| `check_welder_work_coverage` | R12 | 方法、材料、位置、厚度、管径覆盖 |
| `check_pressure_gauge_requirements` | R48 | 压力表数量、有效期、精度和量程 |
| `check_pressure_test_parameters` | R49 | 温度应力比、压力上下限、保压、气压分级升压和结果 |
| `check_pressure_test_report_consistency` | R50 | 报告、方案与现场参数一致性 |
| `validate_evidence_grounding` | 全局门禁 | 页码、坐标/原文、置信度和冲突检查 |

## 3. 全量绑定清单

### R01

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R01-01 | 核查设计许可证的机构名称是否与施工图纸标题栏和设计印章一致 | `designLicense.holderName`<br>`designDocument.titleBlockOrganization`<br>`designDocument.designSealOrganization` | `extract_document_fields`<br>`recognize_signatures_and_seals`<br>`check_all_equal`<br>`validate_evidence_grounding` | `profile=design_license`<br>`normalizer=organization_name`<br>`requiredCount=3` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R01-02 | 核查设计许可证的范围根据设计文件中的施工说明、管道特性表，动力管道（GCD），在范围处一定要有GCD管道资质，GC2级别管道要有GC2或者GC1的资质，GC1级别管道要有GC1的资质 | `designLicense.scopeCodes`<br>`project.pipelineGrades` | `extract_document_fields`<br>`extract_table_records`<br>`check_design_license_scope`<br>`validate_evidence_grounding` | `profile=design_license`<br>`scopeProfile=design-license-scope-cn-v1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R01-03 | 有效期：是否能覆盖住施工期间，因为施工期间也要有技术变更澄清事宜 | `designLicense.validFrom`<br>`designLicense.validUntil`<br>`project.constructionStart`<br>`project.constructionEnd` | `extract_document_fields`<br>`check_date_covers`<br>`validate_evidence_grounding` | `profile=design_license`<br>`coverageMode=closed_interval` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R01-04 | 找到设计许可证的范围，找到设计文件中的施工说明、管道特性表，动力管道（GCD）的施工范围，gcd管道资质要对应，对应的规则是：GC2级别管道要有GC2或者GC1的资质，GC1级别管道要有GC1的资质 | `designLicense.scopeCodes`<br>`designDocument.pipelineGrades` | `extract_document_fields`<br>`extract_table_records`<br>`check_design_license_scope`<br>`validate_evidence_grounding` | `profile=design_license`<br>`scopeProfile=design-license-scope-cn-v1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R01-05 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R02

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R02-01 | 核查安装许可证的范围、根据设计文件中的施工说明、管道特性表，动力管道（GCD），在范围处一定要有GCD管道资质或者A及锅炉安装资质，GC2级别管道要有GC2或者GC1或者GCD的资质，GC1级别管道要有GC1的资质 | `installationLicense.scopeCodes`<br>`installationLicense.validity`<br>`project.pipelineGrades`<br>`project.constructionPeriod` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_scope_coverage`<br>`evaluate_installation_license_scope`<br>`validate_evidence_grounding` | `profile=installation_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R02-02 | 2、有效期：是否能覆盖住施工计划工期 | `installationLicense.scopeCodes`<br>`installationLicense.validity`<br>`project.pipelineGrades`<br>`project.constructionPeriod` | `get_document_ocr_result`<br>`extract_document_fields`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_date_covers`<br>`check_scope_coverage`<br>`evaluate_installation_license_scope`<br>`validate_evidence_grounding` | `profile=installation_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R02-03 | 如果不能覆盖，需要发联络单提醒 | `installationLicense.scopeCodes`<br>`installationLicense.validity`<br>`project.pipelineGrades`<br>`project.constructionPeriod` | `get_document_ocr_result`<br>`extract_document_fields`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_scope_coverage`<br>`check_conditional_requirement`<br>`evaluate_installation_license_scope`<br>`validate_evidence_grounding` | `profile=installation_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R02-04 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R03

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R03-01 | 核查特种设备检验检测机构核准证，核查机构名称名称是否与检测方案的名称一致 | `ndtOrganization.name`<br>`ndtLicense.methodCodes`<br>`ndtLicense.validity`<br>`ndtPlan.organizationName`<br>`design.requiredNdtMethods`<br>`project.constructionPeriod` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_cross_document_match`<br>`evaluate_ndt_organization_scope`<br>`validate_evidence_grounding` | `profile=ndt_organization_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R03-02 | 核查核准项目代码所代表的检测项目是否满足设计文件要求的检测方法 | `ndtOrganization.name`<br>`ndtLicense.methodCodes`<br>`ndtLicense.validity`<br>`ndtPlan.organizationName`<br>`design.requiredNdtMethods`<br>`project.constructionPeriod` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`evaluate_ndt_organization_scope`<br>`validate_evidence_grounding` | `profile=ndt_organization_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R03-03 | 3、有效期：是否能覆盖住施工计划工期，如果不能覆盖，需要发联络单提醒 | `ndtOrganization.name`<br>`ndtLicense.methodCodes`<br>`ndtLicense.validity`<br>`ndtPlan.organizationName`<br>`design.requiredNdtMethods`<br>`project.constructionPeriod` | `get_document_ocr_result`<br>`extract_document_fields`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_date_covers`<br>`check_scope_coverage`<br>`check_conditional_requirement`<br>`evaluate_ndt_organization_scope`<br>`validate_evidence_grounding` | `profile=ndt_organization_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R03-04 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R04

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R04-01 | 是否齐全：基本要求，至少包括图纸目录、设计说明书、管道数据表、管道布置图、管道材料一览表以及直管强度计算书， | `designDocumentSet.documentTypes`<br>`designDocuments.signatureRoles`<br>`project.pipelineGrade`<br>`project.designParameters` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`evaluate_design_approval_level`<br>`validate_evidence_grounding` | `profile=design_approval`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R04-02 | 批准程序：管道数据表、管道材料等级表、设备布置图、管道布置图、强度计算书和管道应力计算书等主要设计图样或者文件，应当有设计、校核、审核三级签字 | `designDocumentSet.documentTypes`<br>`designDocuments.signatureRoles`<br>`project.pipelineGrade`<br>`project.designParameters` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_required`<br>`evaluate_design_approval_level`<br>`validate_evidence_grounding` | `profile=design_approval`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R04-03 | 下列管道的材料等级表、应力计算书、设备布置图和管道布置图应当有设计、校核、审核、审定四级签字： | `designDocumentSet.documentTypes`<br>`designDocuments.signatureRoles`<br>`project.pipelineGrade`<br>`project.designParameters` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_conditional_requirement`<br>`evaluate_design_approval_level`<br>`validate_evidence_grounding` | `profile=design_approval`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R04-04 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R05

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R05-01 | 审查施工单位出具的施工图审查见证材料 | `drawingReviewWitness.document`<br>`drawingReviewWitness.issuer`<br>`drawingReviewWitness.signatures` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_document_set_completeness`<br>`validate_evidence_grounding` | `profile=drawing_review_witness`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R05-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R06

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R06-01 | 审查强度计算书、管道应力分析计算书是否覆盖本项目对应管线或管段，计算书名称、管道编号、设计压力、设计温度、介质、材料、规格等设计条件应与设计文件一致 | `calculation.coveredLines`<br>`calculation.designParameters`<br>`design.designParameters`<br>`calculation.signatureRoles`<br>`project.pipelineGrade` | `get_document_ocr_result`<br>`extract_document_fields`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_required`<br>`check_cross_document_match`<br>`check_scope_coverage`<br>`check_numeric_range`<br>`evaluate_design_approval_level`<br>`validate_evidence_grounding` | `profile=calculation_approval`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R06-02 | 强度计算书、管道应力分析计算书作为主要设计文件，应当有设计、校核、审核三级签字 | `calculation.coveredLines`<br>`calculation.designParameters`<br>`design.designParameters`<br>`calculation.signatureRoles`<br>`project.pipelineGrade` | `get_document_ocr_result`<br>`extract_document_fields`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_required`<br>`evaluate_design_approval_level`<br>`validate_evidence_grounding` | `profile=calculation_approval`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R06-03 | 对 GC1 级管道，或者设计压力大于等于 16.7MPa，或者 GCD 级管道设计压力大于等于 4.0MPa 且设计温度大于等于 570℃的，应当有设计、校核、审核、审定四级签字 | `calculation.coveredLines`<br>`calculation.designParameters`<br>`design.designParameters`<br>`calculation.signatureRoles`<br>`project.pipelineGrade` | `get_document_ocr_result`<br>`extract_document_fields`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_numeric_range`<br>`evaluate_design_approval_level`<br>`validate_evidence_grounding` | `profile=calculation_approval`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R06-04 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R07

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R07-01 | 是否盖设计许可章，是否有相应人员三级或者四级签字 | `designChange.designLicenseSeal`<br>`designChange.signatureRoles`<br>`project.requiredApprovalLevel` | `get_document_ocr_result`<br>`extract_document_fields`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`evaluate_design_approval_level`<br>`validate_evidence_grounding` | `profile=design_change_approval`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R07-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R08

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R08-01 | 所采用的标准是现行有效的 | `design.standardReferences`<br>`standardCatalog.versionStatus`<br>`reviewDate` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_date_covers`<br>`check_standard_version_active`<br>`validate_evidence_grounding` | `profile=standard_version`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R08-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R09

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R09-01 | 审查设计说明：是否对无损检测、防腐和耐压试验和泄露性试验规定了具体要求，其相应要求应符合安全技术和标准规定 | `design.ndtRequirements`<br>`design.corrosionRequirements`<br>`design.pressureTestRequirements`<br>`design.leakTestRequirements`<br>`fixedClauses.requirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`evaluate_design_special_requirements`<br>`validate_evidence_grounding` | `profile=design_special_requirements`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R09-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

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
| AC-R12-01 | 工作见证： 需提供焊工的有效资格证书原件或复印件，以及证书上明确标注的“合格项目”范围（如焊接方法、母材类别、位置等） | `welderCertificate.identity`<br>`welderCertificate.qualificationCodes`<br>`welderCertificate.validity` | `extract_welder_certificate`<br>`decode_welder_qualification`<br>`check_date_covers`<br>`validate_evidence_grounding` | `profile=welder_qualification`<br>`qualificationProfile=welder-qualification-code-tsg-z6002-v1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R12-02 | 监检人员需现场核对人证是否相符，且作业内容（序号29）在证书允许范围内，例：某焊工所焊接的管线材质20钢，规格为89×4.5mm，焊接方法是氩弧焊，焊工证号是GTAW-FeII-6G-3/57-FefS-02/11/12，查TSG Z6002-2010，焊接方法氩弧焊代号GTAW，金属材料类别FeII能覆盖20 | `welderCertificate.identity`<br>`actualWeld.welderIdentity`<br>`welderCertificate.qualificationCodes`<br>`actualWeld.workItems` | `extract_welder_certificate`<br>`decode_welder_qualification`<br>`check_all_equal`<br>`check_welder_work_coverage`<br>`validate_evidence_grounding` | `profile=welder_qualification`<br>`coverageProfile=welder-work-coverage-tsg-z6002-v1` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R12-03 | 焊接位置6G，全位置焊，能覆盖 | `welderCertificate.qualificationCodes`<br>`actualWeld.position` | `decode_welder_qualification`<br>`check_welder_work_coverage`<br>`validate_evidence_grounding` | `profile=welder_qualification`<br>`dimension=position` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R12-04 | 3/57代号可焊管线壁厚0-6mm，管径25-不限，能覆盖89×4.5mm，即通过 | `welderCertificate.qualificationCodes`<br>`actualWeld.wallThickness`<br>`actualWeld.diameter` | `decode_welder_qualification`<br>`check_welder_work_coverage`<br>`validate_evidence_grounding` | `profile=welder_qualification`<br>`dimensions=['thickness', 'diameter']` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R12-05 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R13

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R13-01 | 工作见证： 提供经审批生效的《焊接工艺评定报告》(PQR) 和对应的《焊接作业指导书》(WPS) | `wps.parameters`<br>`pqr.parameters`<br>`actualWeld.conditions`<br>`pipeline.wallThickness` | `get_document_ocr_result`<br>`extract_document_fields`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_required`<br>`check_cross_document_match`<br>`check_wps_pqr_coverage`<br>`validate_evidence_grounding` | `profile=wps_pqr`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R13-02 | 重点核查WPS中的参数（电流、电压、速度、层间温度等）是否与PQR一致，且覆盖实际生产条件（与管线汇总表的管道壁厚对比，看焊评是否能覆盖所焊管线壁厚） | `wps.parameters`<br>`pqr.parameters`<br>`actualWeld.conditions`<br>`pipeline.wallThickness` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_cross_document_match`<br>`check_scope_coverage`<br>`check_numeric_range`<br>`check_wps_pqr_coverage`<br>`validate_evidence_grounding` | `profile=wps_pqr`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R13-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R14

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R14-01 | 工作见证： 焊条、焊丝、焊剂等材料的出厂质量证明书（MTC），需包含化学成分、力学性能等数据，并与实物批号对应 | `weldingConsumable.mtc`<br>`weldingConsumable.batchNo`<br>`weldingConsumable.grade`<br>`weldingConsumable.specification`<br>`design.consumableRequirements`<br>`weldingConsumable.validity` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`check_cross_document_match`<br>`evaluate_welding_consumable`<br>`validate_evidence_grounding` | `profile=welding_consumable_mtc`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R14-02 | 监检时需确认材料牌号、规格符合设计要求，且在有效期内 | `weldingConsumable.mtc`<br>`weldingConsumable.batchNo`<br>`weldingConsumable.grade`<br>`weldingConsumable.specification`<br>`design.consumableRequirements`<br>`weldingConsumable.validity` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_cross_document_match`<br>`check_date_covers`<br>`evaluate_welding_consumable`<br>`validate_evidence_grounding` | `profile=welding_consumable_mtc`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R14-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R15

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R15-01 | 工作见证： 焊材库温湿度记录表、焊条烘干记录、领用登记表、剩余焊材回收记录 | `consumableStore.temperatureHumidityRecords`<br>`consumableStore.bakingRecords`<br>`consumableStore.issueRecords`<br>`consumableStore.returnRecords`<br>`consumableStore.expiryStatus` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`evaluate_welding_consumable_control`<br>`validate_evidence_grounding` | `profile=welding_consumable_control`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R15-02 | 重点检查焊材是否按要求烘干、保温，是否存在混用或过期现象 | `consumableStore.temperatureHumidityRecords`<br>`consumableStore.bakingRecords`<br>`consumableStore.issueRecords`<br>`consumableStore.returnRecords`<br>`consumableStore.expiryStatus` | `get_document_ocr_result`<br>`extract_document_fields`<br>`evaluate_welding_consumable_control`<br>`validate_evidence_grounding` | `profile=welding_consumable_control`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R15-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R16

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R16-01 | 工作见证： 管道组对检查记录表，包含错边量、间隙、坡口角度等实测数据 | `fitUp.measuredGap`<br>`fitUp.misalignment`<br>`fitUp.bevelAngle`<br>`design.fitUpLimits` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_numeric_range`<br>`evaluate_pipe_fit_up`<br>`validate_evidence_grounding` | `profile=pipe_fit_up`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R16-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R17

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R17-01 | 工作见证： 焊接施工记录（含电流、电压、焊接速度、层间温度等）、焊缝编号图或钢印标识 | `weldRecord.current`<br>`weldRecord.voltage`<br>`weldRecord.speed`<br>`weldRecord.interpassTemperature`<br>`weldRecord.weldId`<br>`weldRecord.welderId` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_numeric_range`<br>`evaluate_welding_process`<br>`validate_evidence_grounding` | `profile=welding_record`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R17-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R18

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R18-01 | 工作见证： 外观检查记录表，必要时附照片 | `weldAppearance.reinforcement`<br>`weldAppearance.width`<br>`weldAppearance.undercut`<br>`weldAppearance.surfaceDefects`<br>`weldAppearance.photos` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_conditional_requirement`<br>`evaluate_weld_appearance`<br>`validate_evidence_grounding` | `profile=weld_appearance`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R18-02 | 检查内容包括焊缝余高、宽度、咬边、表面气孔、裂纹等 | `weldAppearance.reinforcement`<br>`weldAppearance.width`<br>`weldAppearance.undercut`<br>`weldAppearance.surfaceDefects`<br>`weldAppearance.photos` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`evaluate_weld_appearance`<br>`validate_evidence_grounding` | `profile=weld_appearance`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R18-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R19

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R19-01 | 工作见证： 返修申请单、返修工艺、返修审手续（同一部位返修次数通常不得超过2次，超过需制定专项方案并经技术负责人批准）、返修后检测报告（如RT/UT） | `repair.repairCount`<br>`repair.application`<br>`repair.procedure`<br>`repair.specialApproval`<br>`repair.retestReport` | `get_document_ocr_result`<br>`extract_document_fields`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_required`<br>`check_conditional_requirement`<br>`evaluate_weld_repair`<br>`validate_evidence_grounding` | `profile=weld_repair`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R19-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R20

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R20-01 | 工作见证： 经审批的热处理工艺卡，明确升温速率、保温温度、保温时间、降温速率等参数 | `heatTreatmentProcedure.signatureRoles`<br>`heatTreatmentProcedure.heatingRate`<br>`heatTreatmentProcedure.holdingTemperature`<br>`heatTreatmentProcedure.holdingTime`<br>`heatTreatmentProcedure.coolingRate` | `get_document_ocr_result`<br>`extract_document_fields`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_numeric_range`<br>`evaluate_heat_treatment`<br>`validate_evidence_grounding` | `profile=heat_treatment_procedure`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R20-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R21

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R21-01 | 工作见证： 热电偶校准证书、温控仪校验报告、测温点布置图 | `thermocouple.calibrationValidity`<br>`temperatureController.calibrationValidity`<br>`temperatureMeasurement.pointLayout` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_heat_treatment_instruments`<br>`validate_evidence_grounding` | `profile=heat_treatment_instruments`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R21-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R22

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R22-01 | 工作见证： 自动记录的温度-时间曲线图、热处理报告、硬度测试报告（布氏/洛氏/维氏） | `heatTreatmentCurve.timeSeries`<br>`heatTreatmentReport.parameters`<br>`hardnessReport.values`<br>`material.category`<br>`design.hardnessLimit` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_numeric_range`<br>`evaluate_heat_treatment`<br>`validate_evidence_grounding` | `profile=heat_treatment_result`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R22-02 | 标准规范：热处理曲线需完整无中断，硬度值应符合设计说明或GB/T20801.1-2025第7.6.6条要求，一般碳钢布氏硬度≤200HB、合金钢≤225HB | `heatTreatmentCurve.timeSeries`<br>`heatTreatmentReport.parameters`<br>`hardnessReport.values`<br>`material.category`<br>`design.hardnessLimit` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_cross_document_match`<br>`check_numeric_range`<br>`evaluate_heat_treatment`<br>`validate_evidence_grounding` | `profile=heat_treatment_result`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R22-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R23

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R23-01 | 工作见证：需提供无损检测单位质量保证手册、受控记录及报告表格、项目人员任命文件、检测仪器及其他必要设备的检定报告 | `ndtQuality.manual`<br>`ndtQuality.controlledForms`<br>`ndtQuality.appointments`<br>`ndtEquipment.calibrationReports` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_date_covers`<br>`evaluate_ndt_quality_system`<br>`validate_evidence_grounding` | `profile=ndt_quality_system`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R23-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R24

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R24-01 | 工作见证：需提供无损检测方案 | `ndtPlan.document`<br>`ndtPlan.methods`<br>`ndtPlan.ratios`<br>`design.ndtRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_ndt_process`<br>`validate_evidence_grounding` | `profile=ndt_plan`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R24-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R25

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R25-01 | 工作见证：需提供检测单位不合格品的控制处理措施程序、无损检测委托单、对不合格品开出的联络单或意见书、不合格品处理的反馈见证文件 | `ndtNonconformance.procedure`<br>`ndtNonconformance.commission`<br>`ndtNonconformance.notice`<br>`ndtNonconformance.feedback` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_ndt_nonconformance`<br>`validate_evidence_grounding` | `profile=ndt_nonconformance`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R25-02 | 标准规范：无损检测单位质量保证手册中有关不合格品与不符合项控制程序文件、NB/T 47013.1-2015《承压设备无损检测 第1部分：通用要求》、NB/T 47013.2-2015《承压设备无损检测 第2部分：射线检测》、NB/T 47013.3-2023《承压设备无损检测 第3部分：超声检测》等 | `ndtNonconformance.procedure`<br>`ndtNonconformance.commission`<br>`ndtNonconformance.notice`<br>`ndtNonconformance.feedback` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_ndt_nonconformance`<br>`validate_evidence_grounding` | `profile=ndt_nonconformance`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R25-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R26

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R26-01 | 工作见证：需提供无损检测人员明细表、无损检测人员资格证和执业注册证，必要时提供无损检测人员劳动合同证明文件 | `ndtPersonnel.roster`<br>`ndtPersonnel.qualificationCodes`<br>`ndtPersonnel.registration`<br>`actualNdt.workItems` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_conditional_requirement`<br>`check_ndt_personnel_coverage`<br>`validate_evidence_grounding` | `profile=ndt_personnel`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R26-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R27

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R27-01 | 工作见证：需提供相关单项无损检测工艺文件、操作指导书 | `ndtProcedure.method`<br>`ndtProcedure.parameters`<br>`ndtProcedure.instruction`<br>`design.ndtRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_ndt_process`<br>`validate_evidence_grounding` | `profile=ndt_procedure`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R27-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R28

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R28-01 | 工作见证：需提供相关单项无损检测记录、报告 | `ndtRecord.weldIds`<br>`ndtRecord.parameters`<br>`ndtReport.results`<br>`design.ndtRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`evaluate_ndt_process`<br>`validate_evidence_grounding` | `profile=ndt_record_report`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R28-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R29

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R29-01 | 工作见证：需提供相关所有射线检测底片 | `radiographicFilms.inventory`<br>`radiographicFilm.imageQuality`<br>`radiographicFilm.weldId`<br>`ndtReport.weldIds` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_rt_film`<br>`validate_evidence_grounding` | `profile=rt_film_sampling`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R29-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R30

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R30-01 | 工作见证：需提供射线检测现场抽查的底片、记录和报告 | `siteSampling.films`<br>`siteSampling.records`<br>`siteSampling.reports`<br>`siteSampling.weldIds` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`evaluate_rt_film`<br>`validate_evidence_grounding` | `profile=rt_site_sampling`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R30-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R31

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R31-01 | 工厂化预制的防腐管道元件需提供出厂质量证明文件，必要时提供型式试验证书、压力管道元件制造许可、制造监督检验证书 | `coatingMaterial.qualityCertificate`<br>`coatingMaterial.typeTest`<br>`coatingMaterial.manufacturingLicense`<br>`coatingMaterial.supervisionCertificate` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`check_numeric_range`<br>`check_conditional_requirement`<br>`evaluate_corrosion_protection`<br>`validate_evidence_grounding` | `profile=coating_material`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R31-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R32

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R32-01 | 工作见证：防腐施工及检查记录、保温施工及检查记录 | `coating.constructionRecords`<br>`coating.inspectionRecords`<br>`insulation.constructionRecords`<br>`insulation.inspectionRecords` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`evaluate_corrosion_protection`<br>`validate_evidence_grounding` | `profile=coating_insulation_process`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R32-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R33

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R33-01 | 工作见证：电火花检测仪检定报告、防腐层电火花检测记录和报告 | `holidayDetector.calibrationValidity`<br>`coatingHolidayTest.parameters`<br>`coatingHolidayTest.results` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_date_covers`<br>`evaluate_corrosion_protection`<br>`validate_evidence_grounding` | `profile=holiday_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R33-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R34

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R34-01 | 工作见证：牺牲阳极、外加电流阴极保护、杂散电流排流装置施工记录和验收报告 | `cathodicProtection.deviceType`<br>`cathodicProtection.constructionRecords`<br>`cathodicProtection.acceptanceResults` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`evaluate_corrosion_protection`<br>`validate_evidence_grounding` | `profile=cathodic_protection`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R34-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R35

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R35-01 | 工作见证：静电接地施工记录和验收报告 | `staticGrounding.constructionRecords`<br>`staticGrounding.measuredResults`<br>`staticGrounding.acceptanceResults` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`evaluate_corrosion_protection`<br>`validate_evidence_grounding` | `profile=static_grounding`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R35-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R36

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R36-01 | 抽查管道结构、焊缝布置施工检查记录或现场抽查是否符合相关标准及设计要求（如管道穿越墙、道路时应设套管保护，套管内的管段不宜有环焊缝存在，如有应进行100%无损检测等） | `crossing.structure`<br>`crossing.weldLayout`<br>`crossing.sleeveSegments`<br>`crossing.ndtCoverage`<br>`design.crossingRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`evaluate_pipeline_installation`<br>`validate_evidence_grounding` | `profile=crossing_weld_layout`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R36-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R37

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R37-01 | 抽查穿跨越工程施工及检查记录是否符合技术规范、相关标准及设计文件的要求 | `crossing.constructionRecords`<br>`crossing.inspectionRecords`<br>`design.crossingRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`evaluate_pipeline_installation`<br>`validate_evidence_grounding` | `profile=crossing_construction`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R37-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R38

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R38-01 | 抽查套管防腐绝缘检查记录（如穿跨越段钢套管一般外部需要进行防腐，内部与管道绝缘隔离（有阴极保护时），以防止阴极保护电流的流失及可能造成的套管内管段电屏蔽腐蚀） | `sleeve.externalCoating`<br>`sleeve.internalInsulation`<br>`project.hasCathodicProtection`<br>`inspection.records` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`evaluate_corrosion_protection`<br>`validate_evidence_grounding` | `profile=sleeve_insulation`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R38-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R39

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R39-01 | 抽查绝缘支撑检查记录；当设计文件要求管道与支撑绝缘时，核查绝缘支撑的位置、绝缘材料、安装方式、绝缘测试记录和检查结论是否符合设计要求 | `design.requiresInsulatedSupport`<br>`insulatedSupport.inspectionRecords`<br>`insulatedSupport.results` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_cross_document_match`<br>`check_sampling_requirement`<br>`check_conditional_requirement`<br>`evaluate_pipeline_installation`<br>`validate_evidence_grounding` | `profile=insulated_support`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R39-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R40

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R40-01 | 现场抽查预制管道的焊接、焊后热处理质量（对加工制作、焊接、热处理、检查、检测、试验等进行抽查） | `prefabrication.weldRecords`<br>`prefabrication.heatTreatmentRecords`<br>`prefabrication.ndtRecords`<br>`prefabrication.testRecords` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_sampling_requirement`<br>`evaluate_pipeline_installation`<br>`validate_evidence_grounding` | `profile=site_prefabrication`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R40-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R41

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R41-01 | 抽查管道布管与连接方式穿跨越检查试验记录（如不得用强力对口、加热管子、加偏垫或者加多层垫等方法来消除接口端面的空隙、偏斜、错口或者不同轴等缺陷 | `installation.alignmentRecords`<br>`installation.connectionMethod`<br>`installation.prohibitedMethods`<br>`equipment.anchorStatus` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`evaluate_pipeline_installation`<br>`validate_evidence_grounding` | `profile=pipe_connection`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R41-02 | 与设备的连接应当在设备安装定位紧固地脚螺栓后自然地进行） | `installation.alignmentRecords`<br>`installation.connectionMethod`<br>`installation.prohibitedMethods`<br>`equipment.anchorStatus` | `get_document_ocr_result`<br>`extract_document_fields`<br>`evaluate_pipeline_installation`<br>`validate_evidence_grounding` | `profile=pipe_connection`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R41-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R42

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R42-01 | 抽查管道补偿装置检查试验记录（按照设计文件的规定进行预拉伸或者预压缩） | `compensator.type`<br>`compensator.prestretch`<br>`compensator.precompression`<br>`design.compensatorRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`evaluate_pipeline_installation`<br>`validate_evidence_grounding` | `profile=compensator`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R42-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R43

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R43-01 | 抽查管道支撑件检查试验记录 | `support.type`<br>`support.location`<br>`support.inspectionResults`<br>`design.supportRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`evaluate_pipeline_installation`<br>`validate_evidence_grounding` | `profile=pipe_support`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R43-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R44

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R44-01 | 审查安全附件的制造许可证、型式试验证书、产品质量证明书等，设计、制造是否符合技术规范的要求 | `safetyAccessory.license`<br>`safetyAccessory.typeTest`<br>`safetyAccessory.qualityCertificate`<br>`safetyAccessory.location`<br>`safetyAccessory.model`<br>`design.safetyAccessoryRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_safety_accessory`<br>`validate_evidence_grounding` | `profile=safety_accessory_installation`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R44-02 | 现场实物抽查安装位置、规格、型号、铭牌等是否符合设计文件等的要求 | `safetyAccessory.license`<br>`safetyAccessory.typeTest`<br>`safetyAccessory.qualityCertificate`<br>`safetyAccessory.location`<br>`safetyAccessory.model`<br>`design.safetyAccessoryRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`check_cross_document_match`<br>`check_sampling_requirement`<br>`evaluate_safety_accessory`<br>`validate_evidence_grounding` | `profile=safety_accessory_installation`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R44-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R45

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R45-01 | 审查安全阀校验报告中的开启压力、密封压力等是否符合安全技术规范等的要求 | `safetyValve.calibrationReport`<br>`safetyValve.openingPressure`<br>`safetyValve.sealingPressure`<br>`design.setPressure` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`check_numeric_range`<br>`evaluate_safety_accessory`<br>`validate_evidence_grounding` | `profile=safety_valve_calibration`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R45-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R46

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R46-01 | 审查紧急切断阀性能测试报告中功能测试项目及内容等 | `emergencyValve.testReport`<br>`emergencyValve.functionItems`<br>`emergencyValve.results` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_safety_accessory`<br>`validate_evidence_grounding` | `profile=emergency_valve_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R46-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R47

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R47-01 | 审查耐压试验方案（审批手续及签字，耐压试验的时机、试验介质、升压速度、试验用压力表和温度计的要求、试验采取的安全措施、合格标准等） | `pressureTestPlan.signatureRoles`<br>`pressureTestPlan.timing`<br>`pressureTestPlan.medium`<br>`pressureTestPlan.pressurizationRate`<br>`pressureTestPlan.instrumentRequirements`<br>`pressureTestPlan.safetyMeasures`<br>`pressureTestPlan.acceptanceCriteria` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_numeric_range`<br>`evaluate_pressure_test`<br>`validate_evidence_grounding` | `profile=pressure_test_plan`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R47-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R48

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R48-01 | 现场检查试验用压力表、试验介质、介质温度、环境温度（如压力表不得少于2块，并在检定有效期内，精度不得低于1.6级，量程为最大试验压力的1.5~2倍等） | `pressureTest.gauges`<br>`pressureTest.maxTestPressure`<br>`pressureTest.testDate`<br>`pressureTest.medium`<br>`pressureTest.mediumTemperature`<br>`pressureTest.ambientTemperature` | `extract_document_fields`<br>`extract_table_records`<br>`check_pressure_gauge_requirements`<br>`validate_evidence_grounding` | `profile=pressure_gauge`<br>`minGaugeCount=2`<br>`maxAccuracyClass=1.6`<br>`rangeRatio=[1.5, 2.0]` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R48-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R49

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R49-01 | 液压试验按设计压力、试验温度与设计温度下的许用应力比计算最低试验压力，并核查组成件及设备共同试验允许的压力上限、保压不少于10min以及无泄漏、无异常和无永久变形等结果 | `pressureTest.method`<br>`pressureTest.designPressure`<br>`pressureTest.testPressure`<br>`pressureTest.holdMinutes`<br>`pressureTest.testResult`<br>`pressureTest.allowableStressAtTestTemperature`<br>`pressureTest.allowableStressAtDesignTemperature`<br>`pressureTest.maximumAllowableTestPressure` | `extract_document_fields`<br>`check_pressure_test_parameters`<br>`validate_evidence_grounding` | `profile=pressure_test_parameters`<br>`ruleProfileVersion=pressure-test-parameters-gbt20801-v2` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R49-02 | 气压试验压力不得低于设计压力的1.1倍，且不得超过设计压力1.33倍、试验温度下90%屈服强度对应压力及组成件允许压力中的最小值；核查50%初始升压、其后每级不大于10%、每级稳压不少于3min及最终保压结果 | `pressureTest.method`<br>`pressureTest.designPressure`<br>`pressureTest.testPressure`<br>`pressureTest.holdMinutes`<br>`pressureTest.testResult`<br>`pressureTest.maximumAllowableTestPressure`<br>`pressureTest.pneumaticYieldLimitPressure`<br>`pressureTest.pressureSteps` | `extract_document_fields`<br>`extract_table_records`<br>`check_pressure_test_parameters`<br>`validate_evidence_grounding` | `profile=pressure_test_parameters`<br>`ruleProfileVersion=pressure-test-parameters-gbt20801-v2` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R49-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R50

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R50-01 | 现场检查耐压试验记录（报告）（记录或报告中采用的标准、试验参数、保压时间、耐压试验结果是否符合技术规范、相关标准及设计文件的要求） | `pressureTestReport.standardRef`<br>`pressureTestReport.parameters`<br>`pressureTestPlan.parameters`<br>`pressureTestObserved.parameters`<br>`pressureTestReport.result` | `extract_document_fields`<br>`check_pressure_test_report_consistency`<br>`validate_evidence_grounding` | `profile=pressure_test_report`<br>`numericTolerance=0.001` | `deterministic-tool-result-v1` | `pilot_implemented` |
| AC-R50-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `pilot_implemented` |

### R51

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R51-01 | 检查由设计单位出具的管道系统柔性（应力）分析报告 | `stressAnalysis.issuer`<br>`stressAnalysis.coveredSystems`<br>`stressAnalysis.designParameters`<br>`design.pipelineSystems` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_stress_analysis`<br>`validate_evidence_grounding` | `profile=stress_analysis`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R51-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R52

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R52-01 | 现场检查敏感性泄漏试验（试验方法和要求是否符合技术规范、相关标准及设计文件的要求） | `sensitiveLeakTest.method`<br>`sensitiveLeakTest.parameters`<br>`sensitiveLeakTest.results`<br>`design.leakTestRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_leak_test`<br>`validate_evidence_grounding` | `profile=sensitive_leak_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R52-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R53

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R53-01 | 审查无损检测报告内容是否符合技术规范、相关标准及设计文件的要求 | `ndtReport.inventory`<br>`radiographicFilms.inventory`<br>`weldInventory.totalCount`<br>`sampling.selectedWeldIds` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_rt_film`<br>`validate_evidence_grounding` | `profile=ndt_report_film_sampling`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R53-02 | 抽查不少于焊接接头总数50%的无损检测报告和底片 | `ndtReport.inventory`<br>`radiographicFilms.inventory`<br>`weldInventory.totalCount`<br>`sampling.selectedWeldIds` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`check_sampling_requirement`<br>`evaluate_rt_film`<br>`validate_evidence_grounding` | `profile=ndt_report_film_sampling`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R53-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R54

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R54-01 | 检查试验用压力表（直径、量程、精度检定有效期）、试验介质、介质温度、试验环境温度、试验压力（试验压力为设计压力） | `leakTest.gauges`<br>`leakTest.medium`<br>`leakTest.mediumTemperature`<br>`leakTest.ambientTemperature`<br>`leakTest.testPressure`<br>`design.designPressure` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_date_covers`<br>`check_numeric_range`<br>`evaluate_leak_test`<br>`validate_evidence_grounding` | `profile=leak_test_instruments`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R54-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R55

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R55-01 | 检查泄漏试验方法和报告（泄漏试验包括敏感性泄漏试验和气密性试验，应按设计文件规定的方法和要求进行，试验报告采用的标准、试验参数、保压时间、耐压试验结果等是否符合技术规范、相关标准及设计文件的要求） | `leakTest.method`<br>`leakTestReport.standardRef`<br>`leakTestReport.parameters`<br>`leakTestReport.holdMinutes`<br>`leakTestReport.result`<br>`design.leakTestRequirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`check_numeric_range`<br>`evaluate_leak_test`<br>`validate_evidence_grounding` | `profile=leak_test_report`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R55-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R56

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R56-01 | 抽查吹扫、清洗记录及方案（吹扫和清洗的时机、吹扫和清洗的介质、吹扫压力、吹扫和清洗的顺序、安全事项和合格要求） | `blowingCleaning.plan`<br>`blowingCleaning.timing`<br>`blowingCleaning.medium`<br>`blowingCleaning.pressure`<br>`blowingCleaning.sequence`<br>`blowingCleaning.safetyMeasures`<br>`blowingCleaning.acceptanceResult` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`check_numeric_range`<br>`evaluate_blowing_cleaning`<br>`validate_evidence_grounding` | `profile=blowing_cleaning`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R56-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R57

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R57-01 | 制造许可证，提取许可证号在查询平台核实，并与设计资料中特性表、材料表的信息进行核实对应，主要看能不能覆盖本次工程所用管道元件 | `manufacturerLicense.number`<br>`manufacturerLicense.scope`<br>`component.materialTableItems`<br>`component.pipelineScheduleItems` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_cross_document_match`<br>`check_scope_coverage`<br>`evaluate_component_manufacturer_scope`<br>`validate_evidence_grounding` | `profile=component_manufacturer_license`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R57-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R58

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R58-01 | 型式试验证书（报告）检查覆盖范围是否符合设计文件中材料表的管道元件 | `component.typeTestScope`<br>`component.designItems`<br>`component.supervisionCertificates`<br>`component.requiredSupervision` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_required`<br>`check_cross_document_match`<br>`check_scope_coverage`<br>`evaluate_material_component`<br>`validate_evidence_grounding` | `profile=component_type_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R58-02 | 监检证书是否齐全 | `component.typeTestScope`<br>`component.designItems`<br>`component.supervisionCertificates`<br>`component.requiredSupervision` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_material_component`<br>`validate_evidence_grounding` | `profile=component_type_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R58-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R59

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R59-01 | 审核出厂质量证明文件或抽查复验记录，比如螺栓螺母，查看等级材质是否符合设计文件要求（与材料表对应） | `component.factoryReport`<br>`component.grade`<br>`component.material`<br>`component.pressureClass`<br>`design.materialTable`<br>`component.specialReports` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_cross_document_match`<br>`check_sampling_requirement`<br>`evaluate_material_component`<br>`validate_evidence_grounding` | `profile=component_factory_inspection`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R59-02 | 审查光谱、硬度、金相、无损检测和耐压试验等报告 | `component.factoryReport`<br>`component.grade`<br>`component.material`<br>`component.pressureClass`<br>`design.materialTable`<br>`component.specialReports` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`check_numeric_range`<br>`evaluate_material_component`<br>`validate_evidence_grounding` | `profile=component_factory_inspection`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R59-03 | 设计文件中材料表、管道特性表压力等级对应 | `component.factoryReport`<br>`component.grade`<br>`component.material`<br>`component.pressureClass`<br>`design.materialTable`<br>`component.specialReports` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_cross_document_match`<br>`check_numeric_range`<br>`evaluate_material_component`<br>`validate_evidence_grounding` | `profile=component_factory_inspection`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R59-04 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R60

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R60-01 | 制造许可资质、型式试验证书 | `foreignComponent.manufacturingLicense`<br>`foreignComponent.typeTestCertificate`<br>`foreignComponent.designItems` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_foreign_component`<br>`validate_evidence_grounding` | `profile=foreign_component`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R60-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R61

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R61-01 | 审查供货状态、成分、出厂检验项目是否符合对应标准 | `component.qualityCertificate`<br>`component.supplyCondition`<br>`component.composition`<br>`component.inspectionItems`<br>`component.copySeals`<br>`design.acceptanceStandard` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_cross_document_match`<br>`evaluate_material_component`<br>`validate_evidence_grounding` | `profile=component_quality_certificate`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R61-02 | 产品质量证明文件需要原件或复印件，其内容是否符合设计文件规定的材料验收标准及其提出的特殊要求，复印件应当加盖经营单位公章和经办负责人章 | `component.qualityCertificate`<br>`component.supplyCondition`<br>`component.composition`<br>`component.inspectionItems`<br>`component.copySeals`<br>`design.acceptanceStandard` | `get_document_ocr_result`<br>`extract_document_fields`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_required`<br>`check_cross_document_match`<br>`evaluate_material_component`<br>`validate_evidence_grounding` | `profile=component_quality_certificate`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R61-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R62

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R62-01 | 验收记录、复验报告 | `component.acceptanceRecords`<br>`component.witnessRecords`<br>`component.samplingRetestReports`<br>`sampling.requirements` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`evaluate_material_component`<br>`validate_evidence_grounding` | `profile=component_acceptance`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R62-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R63

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R63-01 | 材料复验报告、无损检测报告 | `material.retestReport`<br>`material.ndtReport`<br>`material.standardRef`<br>`material.testResults` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_material_component`<br>`validate_evidence_grounding` | `profile=material_retest`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R63-02 | 对应的材料标准：GB/T 12459-2025、GB/T 13401-2025、GB/T 14976-2025 、GB/T 12771-2019 | `material.retestReport`<br>`material.ndtReport`<br>`material.standardRef`<br>`material.testResults` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_cross_document_match`<br>`evaluate_material_component`<br>`validate_evidence_grounding` | `profile=material_retest`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R63-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R64

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R64-01 | 审核产品质量证明文件、复验报告，企业标准 | `foreignMaterial.qualityCertificate`<br>`foreignMaterial.retestReport`<br>`foreignMaterial.enterpriseStandard`<br>`foreignMaterial.grade` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_material_component`<br>`validate_evidence_grounding` | `profile=foreign_material_grade`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R64-02 | TSG31-2025中2.1.2，制定相对应的企业标准 | `foreignMaterial.qualityCertificate`<br>`foreignMaterial.retestReport`<br>`foreignMaterial.enterpriseStandard`<br>`foreignMaterial.grade` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_cross_document_match`<br>`evaluate_material_component`<br>`validate_evidence_grounding` | `profile=foreign_material_grade`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R64-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R65

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R65-01 | 型式试验报告、技术评审证书 | `newMaterial.typeTestReport`<br>`newMaterial.technicalReview`<br>`newMaterial.approvalDocuments` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`evaluate_material_component`<br>`validate_evidence_grounding` | `profile=new_material`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R65-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R66

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R66-01 | 标志移植抽查记录 | `material.originalMark`<br>`material.transferredMark`<br>`material.transferRecords`<br>`material.batchNo` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`check_sampling_requirement`<br>`check_traceability`<br>`validate_evidence_grounding` | `profile=material_mark_transfer`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R66-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R67

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R67-01 | 应当取得原设计单位书面批准设计文件 | `materialSubstitution.originalDesignOrganization`<br>`materialSubstitution.approvingOrganization`<br>`materialSubstitution.writtenApproval`<br>`materialSubstitution.substitutedItems` | `get_document_ocr_result`<br>`extract_document_fields`<br>`recognize_signatures_and_seals`<br>`check_signature_completeness`<br>`check_required`<br>`evaluate_design_approval_level`<br>`validate_evidence_grounding` | `profile=material_substitution`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R67-02 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

### R68

| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |
|---|---|---|---|---|---|---|
| AC-R68-01 | 阀门施工记录、耐压试验记录或报告（包含依据标准） | `valve.constructionRecords`<br>`valve.pressureTestReport`<br>`valve.testProcedure`<br>`valve.testPressure`<br>`valve.holdMinutes`<br>`valve.testResult`<br>`valve.standardRef` | `get_document_ocr_result`<br>`extract_document_fields`<br>`extract_table_records`<br>`check_required`<br>`evaluate_valve_test`<br>`validate_evidence_grounding` | `profile=valve_pressure_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R68-02 | 试验方法程序与结果应符合设计文件和GB/T 13927-2022《工业阀门 压力试验》、GB/T 26480-2011《阀门的检验和试验》 | `valve.constructionRecords`<br>`valve.pressureTestReport`<br>`valve.testProcedure`<br>`valve.testPressure`<br>`valve.holdMinutes`<br>`valve.testResult`<br>`valve.standardRef` | `get_document_ocr_result`<br>`extract_document_fields`<br>`check_required`<br>`check_cross_document_match`<br>`check_numeric_range`<br>`evaluate_valve_test`<br>`validate_evidence_grounding` | `profile=valve_pressure_test`<br>`clauseSource=frozen_standard_clause_package`<br>`failurePolicy=business_rule_result` | `deterministic-tool-result-v1` | `implemented` |
| AC-R68-03 | 核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。 | `judgment.claimedFacts`<br>`judgment.evidenceRefs`<br>`evidence.pageNo`<br>`evidence.bboxOrQuotedText`<br>`evidence.ocrConfidence`<br>`evidence.conflictStatus` | `locate_evidence_fragment`<br>`validate_evidence_grounding` | `minConfidence=0.75`<br>`requirePage=True`<br>`requireBboxOrQuotedText=True`<br>`denyOnConflict=True` | `evidence-gate-result-v1` | `implemented` |

## 4. 运行时约束

1. `requiredFacts` 缺失时返回 `evidence_insufficient`，不得推定为符合。
2. `parameters.profile` 必须随 ReviewRun 冻结并记录版本。
3. 正式判断必须保存 Tool 名称、版本、输入输出 Hash、EvidenceRef 和 ClauseRef。
4. LLM 只能解释 Tool Result 和生成异常候选，不能修改确定性结果。
5. `pilot_implemented` 项进入正式放行前仍须完成专业规则样例验收；缺少事实、证据或规则参数时固定返回 `evidence_insufficient`。
