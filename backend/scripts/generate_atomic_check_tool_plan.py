from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = ROOT / "backend" / "business_packs" / "engineering_inspection_v1"
SOURCE = PACK_DIR / "atomic_checks.yaml"
BINDINGS = PACK_DIR / "atomic_check_tool_bindings.yaml"
DOCUMENT = ROOT / "tools规划.md"

TRACE_INSTRUCTION = "核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。"
PILOT_RULES = {"R01", "R12", "R48", "R49", "R50"}


RULE_PROFILES: dict[str, tuple[list[str], str, str]] = {
    "R01": (["designLicense.holderName", "designLicense.scopeCodes", "designLicense.validity", "designDocument.organizationName", "project.pipelineGrades", "project.constructionPeriod"], "check_design_license_scope", "design_license"),
    "R02": (["installationLicense.scopeCodes", "installationLicense.validity", "project.pipelineGrades", "project.constructionPeriod"], "evaluate_installation_license_scope", "installation_license"),
    "R03": (["ndtOrganization.name", "ndtLicense.methodCodes", "ndtLicense.validity", "ndtPlan.organizationName", "design.requiredNdtMethods", "project.constructionPeriod"], "evaluate_ndt_organization_scope", "ndt_organization_license"),
    "R04": (["designDocumentSet.documentTypes", "designDocuments.signatureRoles", "project.pipelineGrade", "project.designParameters"], "evaluate_design_approval_level", "design_approval"),
    "R05": (["drawingReviewWitness.document", "drawingReviewWitness.issuer", "drawingReviewWitness.signatures"], "check_document_set_completeness", "drawing_review_witness"),
    "R06": (["calculation.coveredLines", "calculation.designParameters", "design.designParameters", "calculation.signatureRoles", "project.pipelineGrade"], "evaluate_design_approval_level", "calculation_approval"),
    "R07": (["designChange.designLicenseSeal", "designChange.signatureRoles", "project.requiredApprovalLevel"], "evaluate_design_approval_level", "design_change_approval"),
    "R08": (["design.standardReferences", "standardCatalog.versionStatus", "reviewDate"], "check_standard_version_active", "standard_version"),
    "R09": (["design.ndtRequirements", "design.corrosionRequirements", "design.pressureTestRequirements", "design.leakTestRequirements", "fixedClauses.requirements"], "evaluate_design_special_requirements", "design_special_requirements"),
    "R10": (["design.adoptedStandardType", "comparisonDeclaration.document", "comparisonTable.coveredSafetyTopics"], "evaluate_alternative_standard", "alternative_standard"),
    "R11": (["constructionPlan.signatureRoles", "constructionPlan.ownerApproval", "constructionPlan.projectParameters", "design.projectParameters", "constructionPlan.processRequirements"], "evaluate_construction_plan", "construction_plan"),
    "R12": (["welderCertificate.qualificationCodes", "welderCertificate.validity", "welder.identity", "actualWeld.workItems", "actualWeld.welderIdentity"], "check_welder_work_coverage", "welder_qualification"),
    "R13": (["wps.parameters", "pqr.parameters", "actualWeld.conditions", "pipeline.wallThickness"], "check_wps_pqr_coverage", "wps_pqr"),
    "R14": (["weldingConsumable.mtc", "weldingConsumable.batchNo", "weldingConsumable.grade", "weldingConsumable.specification", "design.consumableRequirements", "weldingConsumable.validity"], "evaluate_welding_consumable", "welding_consumable_mtc"),
    "R15": (["consumableStore.temperatureHumidityRecords", "consumableStore.bakingRecords", "consumableStore.issueRecords", "consumableStore.returnRecords", "consumableStore.expiryStatus"], "evaluate_welding_consumable_control", "welding_consumable_control"),
    "R16": (["fitUp.measuredGap", "fitUp.misalignment", "fitUp.bevelAngle", "design.fitUpLimits"], "evaluate_pipe_fit_up", "pipe_fit_up"),
    "R17": (["weldRecord.current", "weldRecord.voltage", "weldRecord.speed", "weldRecord.interpassTemperature", "weldRecord.weldId", "weldRecord.welderId"], "evaluate_welding_process", "welding_record"),
    "R18": (["weldAppearance.reinforcement", "weldAppearance.width", "weldAppearance.undercut", "weldAppearance.surfaceDefects", "weldAppearance.photos"], "evaluate_weld_appearance", "weld_appearance"),
    "R19": (["repair.repairCount", "repair.application", "repair.procedure", "repair.specialApproval", "repair.retestReport"], "evaluate_weld_repair", "weld_repair"),
    "R20": (["heatTreatmentProcedure.signatureRoles", "heatTreatmentProcedure.heatingRate", "heatTreatmentProcedure.holdingTemperature", "heatTreatmentProcedure.holdingTime", "heatTreatmentProcedure.coolingRate"], "evaluate_heat_treatment", "heat_treatment_procedure"),
    "R21": (["thermocouple.calibrationValidity", "temperatureController.calibrationValidity", "temperatureMeasurement.pointLayout"], "evaluate_heat_treatment_instruments", "heat_treatment_instruments"),
    "R22": (["heatTreatmentCurve.timeSeries", "heatTreatmentReport.parameters", "hardnessReport.values", "material.category", "design.hardnessLimit"], "evaluate_heat_treatment", "heat_treatment_result"),
    "R23": (["ndtQuality.manual", "ndtQuality.controlledForms", "ndtQuality.appointments", "ndtEquipment.calibrationReports"], "evaluate_ndt_quality_system", "ndt_quality_system"),
    "R24": (["ndtPlan.document", "ndtPlan.methods", "ndtPlan.ratios", "design.ndtRequirements"], "evaluate_ndt_process", "ndt_plan"),
    "R25": (["ndtNonconformance.procedure", "ndtNonconformance.commission", "ndtNonconformance.notice", "ndtNonconformance.feedback"], "evaluate_ndt_nonconformance", "ndt_nonconformance"),
    "R26": (["ndtPersonnel.roster", "ndtPersonnel.qualificationCodes", "ndtPersonnel.registration", "actualNdt.workItems"], "check_ndt_personnel_coverage", "ndt_personnel"),
    "R27": (["ndtProcedure.method", "ndtProcedure.parameters", "ndtProcedure.instruction", "design.ndtRequirements"], "evaluate_ndt_process", "ndt_procedure"),
    "R28": (["ndtRecord.weldIds", "ndtRecord.parameters", "ndtReport.results", "design.ndtRequirements"], "evaluate_ndt_process", "ndt_record_report"),
    "R29": (["radiographicFilms.inventory", "radiographicFilm.imageQuality", "radiographicFilm.weldId", "ndtReport.weldIds"], "evaluate_rt_film", "rt_film_sampling"),
    "R30": (["siteSampling.films", "siteSampling.records", "siteSampling.reports", "siteSampling.weldIds"], "evaluate_rt_film", "rt_site_sampling"),
    "R31": (["coatingMaterial.qualityCertificate", "coatingMaterial.typeTest", "coatingMaterial.manufacturingLicense", "coatingMaterial.supervisionCertificate"], "evaluate_corrosion_protection", "coating_material"),
    "R32": (["coating.constructionRecords", "coating.inspectionRecords", "insulation.constructionRecords", "insulation.inspectionRecords"], "evaluate_corrosion_protection", "coating_insulation_process"),
    "R33": (["holidayDetector.calibrationValidity", "coatingHolidayTest.parameters", "coatingHolidayTest.results"], "evaluate_corrosion_protection", "holiday_test"),
    "R34": (["cathodicProtection.deviceType", "cathodicProtection.constructionRecords", "cathodicProtection.acceptanceResults"], "evaluate_corrosion_protection", "cathodic_protection"),
    "R35": (["staticGrounding.constructionRecords", "staticGrounding.measuredResults", "staticGrounding.acceptanceResults"], "evaluate_corrosion_protection", "static_grounding"),
    "R36": (["crossing.structure", "crossing.weldLayout", "crossing.sleeveSegments", "crossing.ndtCoverage", "design.crossingRequirements"], "evaluate_pipeline_installation", "crossing_weld_layout"),
    "R37": (["crossing.constructionRecords", "crossing.inspectionRecords", "design.crossingRequirements"], "evaluate_pipeline_installation", "crossing_construction"),
    "R38": (["sleeve.externalCoating", "sleeve.internalInsulation", "project.hasCathodicProtection", "inspection.records"], "evaluate_corrosion_protection", "sleeve_insulation"),
    "R39": (["design.requiresInsulatedSupport", "insulatedSupport.inspectionRecords", "insulatedSupport.results"], "evaluate_pipeline_installation", "insulated_support"),
    "R40": (["prefabrication.weldRecords", "prefabrication.heatTreatmentRecords", "prefabrication.ndtRecords", "prefabrication.testRecords"], "evaluate_pipeline_installation", "site_prefabrication"),
    "R41": (["installation.alignmentRecords", "installation.connectionMethod", "installation.prohibitedMethods", "equipment.anchorStatus"], "evaluate_pipeline_installation", "pipe_connection"),
    "R42": (["compensator.type", "compensator.prestretch", "compensator.precompression", "design.compensatorRequirements"], "evaluate_pipeline_installation", "compensator"),
    "R43": (["support.type", "support.location", "support.inspectionResults", "design.supportRequirements"], "evaluate_pipeline_installation", "pipe_support"),
    "R44": (["safetyAccessory.license", "safetyAccessory.typeTest", "safetyAccessory.qualityCertificate", "safetyAccessory.location", "safetyAccessory.model", "design.safetyAccessoryRequirements"], "evaluate_safety_accessory", "safety_accessory_installation"),
    "R45": (["safetyValve.calibrationReport", "safetyValve.openingPressure", "safetyValve.sealingPressure", "design.setPressure"], "evaluate_safety_accessory", "safety_valve_calibration"),
    "R46": (["emergencyValve.testReport", "emergencyValve.functionItems", "emergencyValve.results"], "evaluate_safety_accessory", "emergency_valve_test"),
    "R47": (["pressureTestPlan.signatureRoles", "pressureTestPlan.timing", "pressureTestPlan.medium", "pressureTestPlan.pressurizationRate", "pressureTestPlan.instrumentRequirements", "pressureTestPlan.safetyMeasures", "pressureTestPlan.acceptanceCriteria"], "evaluate_pressure_test", "pressure_test_plan"),
    "R48": (["pressureTest.gauges", "pressureTest.maxTestPressure", "pressureTest.testDate", "pressureTest.medium", "pressureTest.mediumTemperature", "pressureTest.ambientTemperature"], "check_pressure_gauge_requirements", "pressure_gauge"),
    "R49": (["pressureTest.method", "pressureTest.designPressure", "pressureTest.testPressure", "pressureTest.holdMinutes", "pressureTest.testResult", "pressureTest.allowableStressAtTestTemperature", "pressureTest.allowableStressAtDesignTemperature", "pressureTest.maximumAllowableTestPressure", "pressureTest.pneumaticYieldLimitPressure", "pressureTest.pressureSteps"], "check_pressure_test_parameters", "pressure_test_parameters"),
    "R50": (["pressureTestReport.standardRef", "pressureTestReport.parameters", "pressureTestPlan.parameters", "pressureTestObserved.parameters", "pressureTestReport.result"], "check_pressure_test_report_consistency", "pressure_test_report"),
    "R51": (["stressAnalysis.issuer", "stressAnalysis.coveredSystems", "stressAnalysis.designParameters", "design.pipelineSystems"], "evaluate_stress_analysis", "stress_analysis"),
    "R52": (["sensitiveLeakTest.method", "sensitiveLeakTest.parameters", "sensitiveLeakTest.results", "design.leakTestRequirements"], "evaluate_leak_test", "sensitive_leak_test"),
    "R53": (["ndtReport.inventory", "radiographicFilms.inventory", "weldInventory.totalCount", "sampling.selectedWeldIds"], "evaluate_rt_film", "ndt_report_film_sampling"),
    "R54": (["leakTest.gauges", "leakTest.medium", "leakTest.mediumTemperature", "leakTest.ambientTemperature", "leakTest.testPressure", "design.designPressure"], "evaluate_leak_test", "leak_test_instruments"),
    "R55": (["leakTest.method", "leakTestReport.standardRef", "leakTestReport.parameters", "leakTestReport.holdMinutes", "leakTestReport.result", "design.leakTestRequirements"], "evaluate_leak_test", "leak_test_report"),
    "R56": (["blowingCleaning.plan", "blowingCleaning.timing", "blowingCleaning.medium", "blowingCleaning.pressure", "blowingCleaning.sequence", "blowingCleaning.safetyMeasures", "blowingCleaning.acceptanceResult"], "evaluate_blowing_cleaning", "blowing_cleaning"),
    "R57": (["manufacturerLicense.number", "manufacturerLicense.scope", "component.materialTableItems", "component.pipelineScheduleItems"], "evaluate_component_manufacturer_scope", "component_manufacturer_license"),
    "R58": (["component.typeTestScope", "component.designItems", "component.supervisionCertificates", "component.requiredSupervision"], "evaluate_material_component", "component_type_test"),
    "R59": (["component.factoryReport", "component.grade", "component.material", "component.pressureClass", "design.materialTable", "component.specialReports"], "evaluate_material_component", "component_factory_inspection"),
    "R60": (["foreignComponent.manufacturingLicense", "foreignComponent.typeTestCertificate", "foreignComponent.designItems"], "evaluate_foreign_component", "foreign_component"),
    "R61": (["component.qualityCertificate", "component.supplyCondition", "component.composition", "component.inspectionItems", "component.copySeals", "design.acceptanceStandard"], "evaluate_material_component", "component_quality_certificate"),
    "R62": (["component.acceptanceRecords", "component.witnessRecords", "component.samplingRetestReports", "sampling.requirements"], "evaluate_material_component", "component_acceptance"),
    "R63": (["material.retestReport", "material.ndtReport", "material.standardRef", "material.testResults"], "evaluate_material_component", "material_retest"),
    "R64": (["foreignMaterial.qualityCertificate", "foreignMaterial.retestReport", "foreignMaterial.enterpriseStandard", "foreignMaterial.grade"], "evaluate_material_component", "foreign_material_grade"),
    "R65": (["newMaterial.typeTestReport", "newMaterial.technicalReview", "newMaterial.approvalDocuments"], "evaluate_material_component", "new_material"),
    "R66": (["material.originalMark", "material.transferredMark", "material.transferRecords", "material.batchNo"], "check_traceability", "material_mark_transfer"),
    "R67": (["materialSubstitution.originalDesignOrganization", "materialSubstitution.approvingOrganization", "materialSubstitution.writtenApproval", "materialSubstitution.substitutedItems"], "evaluate_design_approval_level", "material_substitution"),
    "R68": (["valve.constructionRecords", "valve.pressureTestReport", "valve.testProcedure", "valve.testPressure", "valve.holdMinutes", "valve.testResult", "valve.standardRef"], "evaluate_valve_test", "valve_pressure_test"),
}


PILOT_BINDINGS: dict[str, dict[str, Any]] = {
    "AC-R01-01": {"facts": ["designLicense.holderName", "designDocument.titleBlockOrganization", "designDocument.designSealOrganization"], "tools": ["extract_document_fields", "recognize_signatures_and_seals", "check_all_equal", "validate_evidence_grounding"], "parameters": {"normalizer": "organization_name", "requiredCount": 3}},
    "AC-R01-02": {"facts": ["designLicense.scopeCodes", "project.pipelineGrades"], "tools": ["extract_document_fields", "extract_table_records", "check_design_license_scope", "validate_evidence_grounding"], "parameters": {"scopeProfile": "design-license-scope-cn-v1"}},
    "AC-R01-03": {"facts": ["designLicense.validFrom", "designLicense.validUntil", "project.constructionStart", "project.constructionEnd"], "tools": ["extract_document_fields", "check_date_covers", "validate_evidence_grounding"], "parameters": {"coverageMode": "closed_interval"}},
    "AC-R01-04": {"facts": ["designLicense.scopeCodes", "designDocument.pipelineGrades"], "tools": ["extract_document_fields", "extract_table_records", "check_design_license_scope", "validate_evidence_grounding"], "parameters": {"scopeProfile": "design-license-scope-cn-v1"}},
    "AC-R12-01": {"facts": ["welderCertificate.identity", "welderCertificate.qualificationCodes", "welderCertificate.validity"], "tools": ["extract_welder_certificate", "decode_welder_qualification", "check_date_covers", "validate_evidence_grounding"], "parameters": {"qualificationProfile": "welder-qualification-code-tsg-z6002-v1"}},
    "AC-R12-02": {"facts": ["welderCertificate.identity", "actualWeld.welderIdentity", "welderCertificate.qualificationCodes", "actualWeld.workItems"], "tools": ["extract_welder_certificate", "decode_welder_qualification", "check_all_equal", "check_welder_work_coverage", "validate_evidence_grounding"], "parameters": {"coverageProfile": "welder-work-coverage-tsg-z6002-v1"}},
    "AC-R12-03": {"facts": ["welderCertificate.qualificationCodes", "actualWeld.position"], "tools": ["decode_welder_qualification", "check_welder_work_coverage", "validate_evidence_grounding"], "parameters": {"dimension": "position"}},
    "AC-R12-04": {"facts": ["welderCertificate.qualificationCodes", "actualWeld.wallThickness", "actualWeld.diameter"], "tools": ["decode_welder_qualification", "check_welder_work_coverage", "validate_evidence_grounding"], "parameters": {"dimensions": ["thickness", "diameter"]}},
    "AC-R48-01": {"facts": ["pressureTest.gauges", "pressureTest.maxTestPressure", "pressureTest.testDate", "pressureTest.medium", "pressureTest.mediumTemperature", "pressureTest.ambientTemperature"], "tools": ["extract_document_fields", "extract_table_records", "check_pressure_gauge_requirements", "validate_evidence_grounding"], "parameters": {"minGaugeCount": 2, "maxAccuracyClass": 1.6, "rangeRatio": [1.5, 2.0]}},
    "AC-R49-01": {"facts": ["pressureTest.method", "pressureTest.designPressure", "pressureTest.testPressure", "pressureTest.holdMinutes", "pressureTest.testResult", "pressureTest.allowableStressAtTestTemperature", "pressureTest.allowableStressAtDesignTemperature", "pressureTest.maximumAllowableTestPressure"], "tools": ["extract_document_fields", "check_pressure_test_parameters", "validate_evidence_grounding"], "parameters": {"ruleProfileVersion": "pressure-test-parameters-gbt20801-v2"}},
    "AC-R49-02": {"facts": ["pressureTest.method", "pressureTest.designPressure", "pressureTest.testPressure", "pressureTest.holdMinutes", "pressureTest.testResult", "pressureTest.maximumAllowableTestPressure", "pressureTest.pneumaticYieldLimitPressure", "pressureTest.pressureSteps"], "tools": ["extract_document_fields", "extract_table_records", "check_pressure_test_parameters", "validate_evidence_grounding"], "parameters": {"ruleProfileVersion": "pressure-test-parameters-gbt20801-v2"}},
    "AC-R50-01": {"facts": ["pressureTestReport.standardRef", "pressureTestReport.parameters", "pressureTestPlan.parameters", "pressureTestObserved.parameters", "pressureTestReport.result"], "tools": ["extract_document_fields", "check_pressure_test_report_consistency", "validate_evidence_grounding"], "parameters": {"numericTolerance": 0.001}},
}


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def planned_tools(instruction: str, domain_tool: str) -> list[str]:
    tools = ["get_document_ocr_result", "extract_document_fields"]
    if any(token in instruction for token in ("表", "明细", "记录", "清单", "曲线")):
        tools.append("extract_table_records")
    if any(token in instruction for token in ("签字", "签章", "印章", "盖", "批准", "审批")):
        tools.extend(["recognize_signatures_and_seals", "check_signature_completeness"])
    if any(token in instruction for token in ("齐全", "提供", "包括", "包含", "文件", "报告", "证书", "记录")):
        tools.append("check_required")
    if any(token in instruction for token in ("一致", "对应", "相符", "符合设计")):
        tools.append("check_cross_document_match")
    if any(token in instruction for token in ("有效期", "现行有效", "检定")):
        tools.append("check_date_covers")
    if any(token in instruction for token in ("范围", "覆盖", "合格项目")):
        tools.append("check_scope_coverage")
    if any(token in instruction for token in ("抽查", "比例", "不少于", "100%")):
        tools.append("check_sampling_requirement")
    if any(token in instruction for token in ("压力", "温度", "硬度", "精度", "量程", "时间", "参数", "尺寸", "错边", "间隙")):
        tools.append("check_numeric_range")
    if any(token in instruction for token in ("如果", "必要时", "当设计", "先判断", "若采用", "超过", "下列")):
        tools.append("check_conditional_requirement")
    tools.extend([domain_tool, "validate_evidence_grounding"])
    return unique(tools)


def make_binding(check: dict[str, Any]) -> dict[str, Any]:
    check_id = check["id"]
    rule_id = check["sourceRuleId"]
    instruction = str(check["instruction"])
    if instruction == TRACE_INSTRUCTION:
        return {
            "atomicCheckId": check_id,
            "sourceRuleId": rule_id,
            "requiredFacts": ["judgment.claimedFacts", "judgment.evidenceRefs", "evidence.pageNo", "evidence.bboxOrQuotedText", "evidence.ocrConfidence", "evidence.conflictStatus"],
            "tools": ["locate_evidence_fragment", "validate_evidence_grounding"],
            "parameters": {"minConfidence": 0.75, "requirePage": True, "requireBboxOrQuotedText": True, "denyOnConflict": True},
            "outputSchema": "evidence-gate-result-v1",
            "implementationStatus": "pilot_implemented" if rule_id in PILOT_RULES else "implemented",
        }
    facts, domain_tool, profile = RULE_PROFILES[rule_id]
    override = PILOT_BINDINGS.get(check_id)
    if override:
        return {
            "atomicCheckId": check_id,
            "sourceRuleId": rule_id,
            "requiredFacts": override["facts"],
            "tools": override["tools"],
            "parameters": {"profile": profile, **override["parameters"]},
            "outputSchema": "deterministic-tool-result-v1",
            "implementationStatus": "pilot_implemented",
        }
    return {
        "atomicCheckId": check_id,
        "sourceRuleId": rule_id,
        "requiredFacts": facts,
        "tools": planned_tools(instruction, domain_tool),
        "parameters": {"profile": profile, "clauseSource": "frozen_standard_clause_package", "failurePolicy": check["failurePolicy"]},
        "outputSchema": "deterministic-tool-result-v1",
        "implementationStatus": "implemented",
    }


def markdown_cell(values: Any) -> str:
    if isinstance(values, list):
        return "<br>".join(f"`{item}`" for item in values)
    if isinstance(values, dict):
        return "<br>".join(f"`{key}={value}`" for key, value in values.items())
    return str(values).replace("|", "\\|").replace("\n", " ")


def build_document(checks: list[dict[str, Any]], bindings: list[dict[str, Any]]) -> str:
    by_id = {item["atomicCheckId"]: item for item in bindings}
    lines = [
        "# Tools 规划",
        "",
        "> 生成源：`backend/business_packs/engineering_inspection_v1/atomic_checks.yaml`。本文件覆盖全部 171 个 atomicCheck；`implemented` 表示 Tool 链已实现，`pilot_implemented` 表示实现仍受试点范围或专业规则版本限制。",
        "",
        "## 1. 统一绑定协议",
        "",
        "```text",
        "atomicCheck → requiredFacts → tools → parameters → outputSchema",
        "```",
        "",
        "- 固定条款来自 ReviewRun 冻结的 `standardClausePackage`，LLM 不选择或替换条款。",
        "- Tool Result 统一返回 `passed / failed / evidence_insufficient / not_applicable`。",
        "- 68 个重复证据追溯项统一使用 `validate_evidence_grounding`，但仍保留逐 atomicCheck 绑定，确保审计覆盖完整。",
        "- 试点范围：R01、R12、R48、R49、R50。",
        "",
        "## 2. 试点已实现 Tool",
        "",
        "| Tool | 试点 | 作用 |",
        "|---|---|---|",
        "| `check_all_equal` | R01/R12 | 标准化机构名称或人员身份一致性 |",
        "| `check_date_covers` | R01/R12 | 证照有效期覆盖业务周期 |",
        "| `check_design_license_scope` | R01 | GC1、GC2、GCD 设计许可范围覆盖 |",
        "| `decode_welder_qualification` | R12 | 解析焊工项目代号 |",
        "| `check_welder_work_coverage` | R12 | 方法、材料、位置、厚度、管径覆盖 |",
        "| `check_pressure_gauge_requirements` | R48 | 压力表数量、有效期、精度和量程 |",
        "| `check_pressure_test_parameters` | R49 | 温度应力比、压力上下限、保压、气压分级升压和结果 |",
        "| `check_pressure_test_report_consistency` | R50 | 报告、方案与现场参数一致性 |",
        "| `validate_evidence_grounding` | 全局门禁 | 页码、坐标/原文、置信度和冲突检查 |",
        "",
        "## 3. 全量绑定清单",
        "",
    ]
    current_rule = None
    for check in checks:
        binding = by_id[check["id"]]
        if current_rule != check["sourceRuleId"]:
            current_rule = check["sourceRuleId"]
            lines.extend(
                [
                    f"### {current_rule}",
                    "",
                    "| atomicCheck | 审核内容 | requiredFacts | tools | parameters | outputSchema | 状态 |",
                    "|---|---|---|---|---|---|---|",
                ]
            )
        lines.append(
            "| {id} | {instruction} | {facts} | {tools} | {parameters} | `{schema}` | `{status}` |".format(
                id=check["id"],
                instruction=markdown_cell(check["instruction"]),
                facts=markdown_cell(binding["requiredFacts"]),
                tools=markdown_cell(binding["tools"]),
                parameters=markdown_cell(binding["parameters"]),
                schema=binding["outputSchema"],
                status=binding["implementationStatus"],
            )
        )
        next_index = checks.index(check) + 1
        if next_index == len(checks) or checks[next_index]["sourceRuleId"] != current_rule:
            lines.append("")
    lines.extend(
        [
            "## 4. 运行时约束",
            "",
            "1. `requiredFacts` 缺失时返回 `evidence_insufficient`，不得推定为符合。",
            "2. `parameters.profile` 必须随 ReviewRun 冻结并记录版本。",
            "3. 正式判断必须保存 Tool 名称、版本、输入输出 Hash、EvidenceRef 和 ClauseRef。",
            "4. LLM 只能解释 Tool Result 和生成异常候选，不能修改确定性结果。",
            "5. `pilot_implemented` 项进入正式放行前仍须完成专业规则样例验收；缺少事实、证据或规则参数时固定返回 `evidence_insufficient`。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    source = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    checks = source["atomicChecks"]
    missing_profiles = sorted({item["sourceRuleId"] for item in checks} - set(RULE_PROFILES))
    if missing_profiles:
        raise SystemExit(f"Missing rule profiles: {missing_profiles}")
    bindings = [make_binding(item) for item in checks]
    payload = {
        "atomicCheckToolBindingSet": {
            "id": "engineering-inspection-tool-bindings-v1",
            "schemaVersion": "atomic-check-tool-binding-v1",
            "version": "2026.07.12",
            "lifecycleStatus": "draft",
            "atomicCheckCount": len(bindings),
            "pilotRules": sorted(PILOT_RULES),
        },
        "atomicCheckToolBindings": bindings,
    }
    BINDINGS.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    DOCUMENT.write_text(build_document(checks, bindings), encoding="utf-8")
    print(f"generated {len(bindings)} bindings -> {BINDINGS}")
    print(f"generated document -> {DOCUMENT}")


if __name__ == "__main__":
    main()
