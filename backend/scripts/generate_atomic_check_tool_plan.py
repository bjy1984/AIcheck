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
PILOT_RULES = {"R01", "R02", "R03", "R06", "R07", "R09", "R24", "R60", "R61", "R62"}


RULE_PROFILES: dict[str, tuple[list[str], str, str]] = {
    "R01": (["designLicense.holderName", "designLicense.scopeCodes", "designLicense.validity", "designDocument.organizationName", "project.pipelineGrades", "project.constructionPeriod"], "check_design_license_scope", "design_license"),
    "R02": (["installationLicense.scopeCodes", "installationLicense.validity", "project.pipelineGrades", "project.constructionPeriod"], "evaluate_installation_license_scope", "installation_license"),
    "R03": (["ndtOrganization.name", "ndtLicense.methodCodes", "ndtLicense.validity", "ndtPlan.organizationName", "design.requiredNdtMethods", "project.constructionPeriod"], "evaluate_ndt_organization_scope", "ndt_organization_license"),
    "R04": (["designDocumentSet.documentTypes", "designDocuments.signatureRoles", "project.pipelineGrade", "project.designParameters"], "evaluate_design_approval_level", "design_approval"),
    "R05": (["drawingReviewWitness.document", "drawingReviewWitness.issuer", "drawingReviewWitness.signatures"], "check_document_set_completeness", "drawing_review_witness"),
    "R06": (["calculation.coveredLines", "calculation.designParameters", "design.designParameters", "calculation.signatureRoles", "project.pipelineGrade"], "evaluate_design_approval_level", "calculation_approval"),
    "R07": (["designChange.designLicenseSeal", "designChange.signatureRoles", "project.requiredApprovalLevel"], "evaluate_design_approval_level", "design_change_approval"),
    "R08": (["design.standardReferences", "standardCatalog.versionStatus", "reviewDate"], "check_standard_version_active", "standard_version"),
    "R09": (["designSpecialRequirements.domains.ndt", "designSpecialRequirements.domains.corrosion", "designSpecialRequirements.domains.pressureTest", "designSpecialRequirements.domains.leakTest", "fixedClauses.designSpecialRequirementRules"], "evaluate_design_special_requirements", "design_special_requirements"),
    "R10": (["design.adoptedStandardType", "comparisonDeclaration.document", "comparisonTable.coveredSafetyTopics"], "evaluate_alternative_standard", "alternative_standard"),
    "R11": (["constructionPlan.signatureRoles", "constructionPlan.ownerApproval", "constructionPlan.projectParameters", "design.projectParameters", "constructionPlan.processRequirements"], "evaluate_construction_plan", "construction_plan"),
    "R24": (["welderCertificate.qualificationCodes", "welderCertificate.validity", "welder.identity", "actualWeld.workItems", "actualWeld.welderIdentity"], "check_welder_work_coverage", "welder_qualification"),
    "R25": (["wps.parameters", "pqr.parameters", "actualWeld.conditions", "pipeline.wallThickness"], "check_wps_pqr_coverage", "wps_pqr"),
    "R26": (["weldingConsumable.mtc", "weldingConsumable.batchNo", "weldingConsumable.grade", "weldingConsumable.specification", "design.consumableRequirements", "weldingConsumable.validity"], "evaluate_welding_consumable", "welding_consumable_mtc"),
    "R27": (["consumableStore.temperatureHumidityRecords", "consumableStore.bakingRecords", "consumableStore.issueRecords", "consumableStore.returnRecords", "consumableStore.expiryStatus"], "evaluate_welding_consumable_control", "welding_consumable_control"),
    "R28": (["fitUp.measuredGap", "fitUp.misalignment", "fitUp.bevelAngle", "design.fitUpLimits"], "evaluate_pipe_fit_up", "pipe_fit_up"),
    "R29": (["weldRecord.current", "weldRecord.voltage", "weldRecord.speed", "weldRecord.interpassTemperature", "weldRecord.weldId", "weldRecord.welderId"], "evaluate_welding_process", "welding_record"),
    "R30": (["weldAppearance.reinforcement", "weldAppearance.width", "weldAppearance.undercut", "weldAppearance.surfaceDefects", "weldAppearance.photos"], "evaluate_weld_appearance", "weld_appearance"),
    "R31": (["repair.repairCount", "repair.application", "repair.procedure", "repair.specialApproval", "repair.retestReport"], "evaluate_weld_repair", "weld_repair"),
    "R32": (["heatTreatmentProcedure.signatureRoles", "heatTreatmentProcedure.heatingRate", "heatTreatmentProcedure.holdingTemperature", "heatTreatmentProcedure.holdingTime", "heatTreatmentProcedure.coolingRate"], "evaluate_heat_treatment", "heat_treatment_procedure"),
    "R33": (["thermocouple.calibrationValidity", "temperatureController.calibrationValidity", "temperatureMeasurement.pointLayout"], "evaluate_heat_treatment_instruments", "heat_treatment_instruments"),
    "R34": (["heatTreatmentCurve.timeSeries", "heatTreatmentReport.parameters", "hardnessReport.values", "material.category", "design.hardnessLimit"], "evaluate_heat_treatment", "heat_treatment_result"),
    "R35": (["ndtQuality.manual", "ndtQuality.controlledForms", "ndtQuality.appointments", "ndtEquipment.calibrationReports"], "evaluate_ndt_quality_system", "ndt_quality_system"),
    "R36": (["ndtPlan.document", "ndtPlan.methods", "ndtPlan.ratios", "design.ndtRequirements"], "evaluate_ndt_process", "ndt_plan"),
    "R37": (["ndtNonconformance.procedure", "ndtNonconformance.commission", "ndtNonconformance.notice", "ndtNonconformance.feedback"], "evaluate_ndt_nonconformance", "ndt_nonconformance"),
    "R38": (["ndtPersonnel.roster", "ndtPersonnel.qualificationCodes", "ndtPersonnel.registration", "actualNdt.workItems"], "check_ndt_personnel_coverage", "ndt_personnel"),
    "R39": (["ndtProcedure.method", "ndtProcedure.parameters", "ndtProcedure.instruction", "design.ndtRequirements"], "evaluate_ndt_process", "ndt_procedure"),
    "R40": (["ndtRecord.weldIds", "ndtRecord.parameters", "ndtReport.results", "design.ndtRequirements"], "evaluate_ndt_process", "ndt_record_report"),
    "R41": (["radiographicFilms.inventory", "radiographicFilm.imageQuality", "radiographicFilm.weldId", "ndtReport.weldIds"], "evaluate_rt_film", "rt_film_sampling"),
    "R42": (["siteSampling.films", "siteSampling.records", "siteSampling.reports", "siteSampling.weldIds"], "evaluate_rt_film", "rt_site_sampling"),
    "R43": (["coatingMaterial.qualityCertificate", "coatingMaterial.typeTest", "coatingMaterial.manufacturingLicense", "coatingMaterial.supervisionCertificate"], "evaluate_corrosion_protection", "coating_material"),
    "R44": (["coating.constructionRecords", "coating.inspectionRecords", "insulation.constructionRecords", "insulation.inspectionRecords"], "evaluate_corrosion_protection", "coating_insulation_process"),
    "R45": (["holidayDetector.calibrationValidity", "coatingHolidayTest.parameters", "coatingHolidayTest.results"], "evaluate_corrosion_protection", "holiday_test"),
    "R46": (["cathodicProtection.deviceType", "cathodicProtection.constructionRecords", "cathodicProtection.acceptanceResults"], "evaluate_corrosion_protection", "cathodic_protection"),
    "R47": (["staticGrounding.constructionRecords", "staticGrounding.measuredResults", "staticGrounding.acceptanceResults"], "evaluate_corrosion_protection", "static_grounding"),
    "R48": (["crossing.structure", "crossing.weldLayout", "crossing.sleeveSegments", "crossing.ndtCoverage", "design.crossingRequirements"], "evaluate_pipeline_installation", "crossing_weld_layout"),
    "R49": (["crossing.constructionRecords", "crossing.inspectionRecords", "design.crossingRequirements"], "evaluate_pipeline_installation", "crossing_construction"),
    "R50": (["sleeve.externalCoating", "sleeve.internalInsulation", "project.hasCathodicProtection", "inspection.records"], "evaluate_corrosion_protection", "sleeve_insulation"),
    "R51": (["design.requiresInsulatedSupport", "insulatedSupport.inspectionRecords", "insulatedSupport.results"], "evaluate_pipeline_installation", "insulated_support"),
    "R52": (["prefabrication.weldRecords", "prefabrication.heatTreatmentRecords", "prefabrication.ndtRecords", "prefabrication.testRecords"], "evaluate_pipeline_installation", "site_prefabrication"),
    "R53": (["installation.alignmentRecords", "installation.connectionMethod", "installation.prohibitedMethods", "equipment.anchorStatus"], "evaluate_pipeline_installation", "pipe_connection"),
    "R54": (["compensator.type", "compensator.prestretch", "compensator.precompression", "design.compensatorRequirements"], "evaluate_pipeline_installation", "compensator"),
    "R55": (["support.type", "support.location", "support.inspectionResults", "design.supportRequirements"], "evaluate_pipeline_installation", "pipe_support"),
    "R56": (["safetyAccessory.license", "safetyAccessory.typeTest", "safetyAccessory.qualityCertificate", "safetyAccessory.location", "safetyAccessory.model", "design.safetyAccessoryRequirements"], "evaluate_safety_accessory", "safety_accessory_installation"),
    "R57": (["safetyValve.calibrationReport", "safetyValve.openingPressure", "safetyValve.sealingPressure", "design.setPressure"], "evaluate_safety_accessory", "safety_valve_calibration"),
    "R58": (["emergencyValve.testReport", "emergencyValve.functionItems", "emergencyValve.results"], "evaluate_safety_accessory", "emergency_valve_test"),
    "R59": (["pressureTestPlan.signatureRoles", "pressureTestPlan.timing", "pressureTestPlan.medium", "pressureTestPlan.pressurizationRate", "pressureTestPlan.instrumentRequirements", "pressureTestPlan.safetyMeasures", "pressureTestPlan.acceptanceCriteria"], "evaluate_pressure_test", "pressure_test_plan"),
    "R60": (["pressureTest.gauges", "pressureTest.maxTestPressure", "pressureTest.testDate", "pressureTest.medium", "pressureTest.mediumTemperature", "pressureTest.ambientTemperature"], "check_pressure_gauge_requirements", "pressure_gauge"),
    "R61": (["pressureTest.method", "pressureTest.designPressure", "pressureTest.testPressure", "pressureTest.holdMinutes", "pressureTest.testResult", "pressureTest.allowableStressAtTestTemperature", "pressureTest.allowableStressAtDesignTemperature", "pressureTest.maximumAllowableTestPressure", "pressureTest.pneumaticYieldLimitPressure", "pressureTest.pressureSteps"], "check_pressure_test_parameters", "pressure_test_parameters"),
    "R62": (["pressureTestReport.standardRef", "pressureTestReport.parameters", "pressureTestPlan.parameters", "pressureTestObserved.parameters", "pressureTestReport.result"], "check_pressure_test_report_consistency", "pressure_test_report"),
    "R63": (["stressAnalysis.issuer", "stressAnalysis.coveredSystems", "stressAnalysis.designParameters", "design.pipelineSystems"], "evaluate_stress_analysis", "stress_analysis"),
    "R64": (["sensitiveLeakTest.method", "sensitiveLeakTest.parameters", "sensitiveLeakTest.results", "design.leakTestRequirements"], "evaluate_leak_test", "sensitive_leak_test"),
    "R65": (["ndtReport.inventory", "radiographicFilms.inventory", "weldInventory.totalCount", "sampling.selectedWeldIds"], "evaluate_rt_film", "ndt_report_film_sampling"),
    "R66": (["leakTest.gauges", "leakTest.medium", "leakTest.mediumTemperature", "leakTest.ambientTemperature", "leakTest.testPressure", "design.designPressure"], "evaluate_leak_test", "leak_test_instruments"),
    "R67": (["leakTest.method", "leakTestReport.standardRef", "leakTestReport.parameters", "leakTestReport.holdMinutes", "leakTestReport.result", "design.leakTestRequirements"], "evaluate_leak_test", "leak_test_report"),
    "R68": (["blowingCleaning.plan", "blowingCleaning.timing", "blowingCleaning.medium", "blowingCleaning.pressure", "blowingCleaning.sequence", "blowingCleaning.safetyMeasures", "blowingCleaning.acceptanceResult"], "evaluate_blowing_cleaning", "blowing_cleaning"),
    "R12": (["manufacturerLicense.number", "manufacturerLicense.scope", "component.materialTableItems", "component.pipelineScheduleItems"], "evaluate_component_manufacturer_scope", "component_manufacturer_license"),
    "R13": (["component.typeTestScope", "component.designItems", "component.supervisionCertificates", "component.requiredSupervision"], "evaluate_material_component", "component_type_test"),
    "R14": (["component.factoryReport", "component.grade", "component.material", "component.pressureClass", "design.materialTable", "component.specialReports"], "evaluate_material_component", "component_factory_inspection"),
    "R15": (["foreignComponent.manufacturingLicense", "foreignComponent.typeTestCertificate", "foreignComponent.designItems"], "evaluate_foreign_component", "foreign_component"),
    "R16": (["component.qualityCertificate", "component.supplyCondition", "component.composition", "component.inspectionItems", "component.copySeals", "design.acceptanceStandard"], "evaluate_material_component", "component_quality_certificate"),
    "R17": (["component.acceptanceRecords", "component.witnessRecords", "component.samplingRetestReports", "sampling.requirements"], "evaluate_material_component", "component_acceptance"),
    "R18": (["material.retestReport", "material.ndtReport", "material.standardRef", "material.testResults"], "evaluate_material_component", "material_retest"),
    "R19": (["foreignMaterial.qualityCertificate", "foreignMaterial.retestReport", "foreignMaterial.enterpriseStandard", "foreignMaterial.grade"], "evaluate_material_component", "foreign_material_grade"),
    "R20": (["newMaterial.typeTestReport", "newMaterial.technicalReview", "newMaterial.approvalDocuments"], "evaluate_material_component", "new_material"),
    "R21": (["material.originalMark", "material.transferredMark", "material.transferRecords", "material.batchNo"], "check_traceability", "material_mark_transfer"),
    "R22": (["materialSubstitution.originalDesignOrganization", "materialSubstitution.approvingOrganization", "materialSubstitution.writtenApproval", "materialSubstitution.substitutedItems"], "evaluate_design_approval_level", "material_substitution"),
    "R23": (["valve.constructionRecords", "valve.pressureTestReport", "valve.testProcedure", "valve.testPressure", "valve.holdMinutes", "valve.testResult", "valve.standardRef"], "evaluate_valve_test", "valve_pressure_test"),
    "R69": (["qualitySystemEvaluation.report", "qualitySystemEvaluation.result", "qualitySystemEvaluation.evaluator", "qualitySystemEvaluation.evaluationDate", "qualitySystemEvaluation.coveredProjectId", "reviewRun.nodeResults"], "check_document_set_completeness", "construction_quality_system_evaluation"),
}


PILOT_BINDINGS: dict[str, dict[str, Any]] = {
    "AC-R24-01": {"facts": ["welderCertificate.identity", "welderCertificate.qualificationCodes", "welderCertificate.validity"], "tools": ["extract_welder_certificate", "decode_welder_qualification", "check_date_covers", "validate_evidence_grounding"], "parameters": {"qualificationProfile": "welder-qualification-code-tsg-z6002-v1"}},
    "AC-R24-02": {"facts": ["welderCertificate.identity", "actualWeld.welderIdentity", "welderCertificate.qualificationCodes", "actualWeld.workItems"], "tools": ["extract_welder_certificate", "decode_welder_qualification", "check_all_equal", "check_welder_work_coverage", "validate_evidence_grounding"], "parameters": {"coverageProfile": "welder-work-coverage-tsg-z6002-v1"}},
    "AC-R24-03": {"facts": ["welderCertificate.qualificationCodes", "actualWeld.position"], "tools": ["decode_welder_qualification", "check_welder_work_coverage", "validate_evidence_grounding"], "parameters": {"dimension": "position"}},
    "AC-R24-04": {"facts": ["welderCertificate.qualificationCodes", "actualWeld.wallThickness", "actualWeld.diameter"], "tools": ["decode_welder_qualification", "check_welder_work_coverage", "validate_evidence_grounding"], "parameters": {"dimensions": ["thickness", "diameter"]}},
    "AC-R60-01": {"facts": ["pressureTest.gauges", "pressureTest.maxTestPressure", "pressureTest.testDate", "pressureTest.medium", "pressureTest.mediumTemperature", "pressureTest.ambientTemperature"], "tools": ["extract_document_fields", "extract_table_records", "check_pressure_gauge_requirements", "validate_evidence_grounding"], "parameters": {"minGaugeCount": 2, "maxAccuracyClass": 1.6, "rangeRatio": [1.5, 2.0]}},
    "AC-R61-01": {"facts": ["pressureTest.method", "pressureTest.designPressure", "pressureTest.testPressure", "pressureTest.holdMinutes", "pressureTest.testResult", "pressureTest.allowableStressAtTestTemperature", "pressureTest.allowableStressAtDesignTemperature", "pressureTest.maximumAllowableTestPressure"], "tools": ["extract_document_fields", "check_pressure_test_parameters", "validate_evidence_grounding"], "parameters": {"ruleProfileVersion": "pressure-test-parameters-gbt20801-v2"}},
    "AC-R61-02": {"facts": ["pressureTest.method", "pressureTest.designPressure", "pressureTest.testPressure", "pressureTest.holdMinutes", "pressureTest.testResult", "pressureTest.maximumAllowableTestPressure", "pressureTest.pneumaticYieldLimitPressure", "pressureTest.pressureSteps"], "tools": ["extract_document_fields", "extract_table_records", "check_pressure_test_parameters", "validate_evidence_grounding"], "parameters": {"ruleProfileVersion": "pressure-test-parameters-gbt20801-v2"}},
    "AC-R62-01": {"facts": ["pressureTestReport.standardRef", "pressureTestReport.parameters", "pressureTestPlan.parameters", "pressureTestObserved.parameters", "pressureTestReport.result"], "tools": ["extract_document_fields", "check_pressure_test_report_consistency", "validate_evidence_grounding"], "parameters": {"numericTolerance": 0.001}},
}


R04_BINDINGS: dict[str, dict[str, Any]] = {
    "AC-R04-01": {
        "facts": [
            "designDocumentSet.catalogListedDocumentTypes",
            "designDocumentSet.uploadedDocumentTypes",
            "designDocumentSet.parseableDocumentTypes",
        ],
        "tools": [
            "get_document_ocr_result",
            "extract_document_fields",
            "extract_table_records",
            "check_document_set_completeness",
            "validate_evidence_grounding",
        ],
        "parameters": {
            "requiredDocumentTypes": [
                "drawing_catalog",
                "design_specification",
                "pipeline_data_sheet",
                "pipeline_layout_drawing",
                "pipeline_material_list",
                "straight_pipe_strength_calculation",
            ]
        },
    },
    "AC-R04-02": {
        "facts": ["designDocuments.documents", "project.pipelines"],
        "tools": [
            "get_document_ocr_result",
            "extract_document_fields",
            "extract_table_records",
            "recognize_signatures_and_seals",
            "evaluate_design_document_approval",
            "validate_evidence_grounding",
        ],
        "parameters": {
            "approvalMode": "three_level",
            "targetDocumentTypes": [
                "pipeline_data_sheet",
                "pipeline_material_grade_table",
                "equipment_layout_drawing",
                "pipeline_layout_drawing",
                "strength_calculation",
                "pipeline_stress_calculation",
            ],
            "requiredRoles": ["设计", "校核", "审核"],
            "ruleVersion": "r04-design-approval-tsg31-2025-v1",
        },
    },
    "AC-R04-03": {
        "facts": ["designDocuments.documents", "project.pipelines"],
        "tools": [
            "get_document_ocr_result",
            "extract_document_fields",
            "extract_table_records",
            "recognize_signatures_and_seals",
            "evaluate_design_document_approval",
            "validate_evidence_grounding",
        ],
        "parameters": {
            "approvalMode": "four_level_conditional",
            "targetDocumentTypes": [
                "pipeline_material_grade_table",
                "pipeline_stress_calculation",
                "equipment_layout_drawing",
                "pipeline_layout_drawing",
            ],
            "requiredRoles": ["设计", "校核", "审核", "审定"],
            "ruleVersion": "r04-design-approval-tsg31-2025-v1",
            "triggerProfile": "gc1-or-gcd-pressure-temperature-v1",
        },
    },
}


R01_R03_BINDINGS: dict[str, dict[str, Any]] = {
    "AC-R01-01": {
        "facts": ["designLicense.holderName", "designDocument.titleBlockOrganization", "designDocument.designSealOrganization"],
        "tools": ["extract_document_fields", "recognize_signatures_and_seals", "check_all_equal", "validate_evidence_grounding"],
        "parameters": {"argumentProfile": "r01_design_org_identity", "normalizer": "organization_name", "requiredCount": 3},
    },
    "AC-R01-02": {
        "facts": ["designLicense.scopeCodes", "project.pipelineGrades"],
        "tools": ["extract_document_fields", "extract_table_records", "check_design_license_scope", "validate_evidence_grounding"],
        "parameters": {"argumentProfile": "r01_design_scope_project", "scopeProfile": "design-license-scope-cn-v1"},
    },
    "AC-R01-03": {
        "facts": [
            "designLicense.validFrom", "designLicense.validUntil", "project.constructionStart",
            "project.plannedConstructionEnd", "project.actualConstructionEnd", "project.changeClarificationEnd",
        ],
        "tools": ["extract_document_fields", "check_date_covers", "validate_evidence_grounding"],
        "parameters": {
            "argumentProfile": "r01_design_license_period",
            "coverageMode": "closed_interval",
            "periodEndPolicy": "latest_of_planned_actual_change_clarification",
        },
    },
    "AC-R01-04": {
        "facts": ["designLicense.scopeCodes", "designDocument.pipelineGrades"],
        "tools": ["extract_document_fields", "extract_table_records", "check_design_license_scope", "validate_evidence_grounding"],
        "parameters": {"argumentProfile": "r01_design_scope_documents", "scopeProfile": "design-license-scope-cn-v1"},
    },
    "AC-R02-01": {
        "facts": ["installationLicense.scopeCodes", "project.pipelineGrades"],
        "tools": ["extract_document_fields", "extract_table_records", "check_installation_license_scope", "validate_evidence_grounding"],
        "parameters": {"argumentProfile": "r02_installation_scope", "scopeProfile": "installation-license-scope-cn-v2"},
    },
    "AC-R02-02": {
        "facts": ["installationLicense.validFrom", "installationLicense.validUntil", "project.constructionStart", "project.plannedConstructionEnd"],
        "tools": ["extract_document_fields", "check_date_covers", "validate_evidence_grounding"],
        "parameters": {"argumentProfile": "r02_installation_license_period", "coverageMode": "closed_interval"},
    },
    "AC-R02-03": {
        "facts": ["installationLicense.validFrom", "installationLicense.validUntil", "project.constructionStart", "project.plannedConstructionEnd"],
        "tools": ["check_date_covers", "validate_evidence_grounding"],
        "parameters": {
            "argumentProfile": "r02_installation_license_period",
            "failureAction": "CONTACT_NOTICE_REQUIRED",
            "externalActionPolicy": "recommendation_only",
        },
    },
    "AC-R03-01": {
        "facts": ["ndtAgencies.agencies[].agencyId", "ndtAgencies.agencies[].licenseOrganizationName", "ndtAgencies.agencies[].planOrganizationName"],
        "tools": ["extract_document_fields", "evaluate_ndt_agencies", "validate_evidence_grounding"],
        "parameters": {"argumentProfile": "r03_agency_identity", "evaluationMode": "identity"},
    },
    "AC-R03-02": {
        "facts": ["ndtAgencies.agencies[].agencyId", "ndtAgencies.agencies[].approvalItemCodes", "ndtAgencies.agencies[].requiredMethods"],
        "tools": ["extract_document_fields", "extract_table_records", "decode_ndt_approval_item_codes", "evaluate_ndt_agencies", "validate_evidence_grounding"],
        "parameters": {"argumentProfile": "r03_method_coverage", "evaluationMode": "method_coverage", "codeProfile": "tsg-z7002-2022-table-a1"},
    },
    "AC-R03-03": {
        "facts": [
            "ndtAgencies.agencies[].agencyId", "ndtAgencies.agencies[].validFrom", "ndtAgencies.agencies[].validUntil",
            "ndtAgencies.agencies[].periodStart", "ndtAgencies.agencies[].plannedPeriodEnd",
        ],
        "tools": ["extract_document_fields", "evaluate_ndt_agencies", "validate_evidence_grounding"],
        "parameters": {
            "argumentProfile": "r03_date_coverage",
            "evaluationMode": "date_coverage",
            "failureAction": "CONTACT_NOTICE_REQUIRED",
            "externalActionPolicy": "recommendation_only",
        },
    },
}


R06_R07_BINDINGS: dict[str, dict[str, Any]] = {
    "AC-R06-01": {
        "facts": [
            "calculationDocuments.documents[].documentId",
            "calculationDocuments.documents[].documentType",
            "calculationDocuments.documents[].bodyUploaded",
            "calculationDocuments.documents[].coveredPipelineIds",
            "calculationDocuments.documents[].parameterComparisons",
        ],
        "tools": [
            "extract_document_fields",
            "extract_table_records",
            "evaluate_calculation_document_consistency",
            "validate_evidence_grounding",
        ],
        "parameters": {
            "argumentProfile": "r06_calculation_consistency",
            "targetDocumentTypes": ["strength_calculation", "pipeline_stress_calculation"],
            "ruleVersion": "r06-calculation-consistency-v1",
        },
    },
    "AC-R06-02": {
        "facts": ["calculationDocuments.documents"],
        "tools": [
            "extract_document_fields",
            "recognize_signatures_and_seals",
            "evaluate_design_document_approval",
            "validate_evidence_grounding",
        ],
        "parameters": {
            "argumentProfile": "r06_three_level_approval",
            "approvalMode": "three_level",
            "targetDocumentTypes": ["strength_calculation", "pipeline_stress_calculation"],
            "requiredRoles": ["设计", "校核", "审核"],
            "ruleVersion": "r06-design-approval-tsg31-2025-3.1.3.3-v1",
        },
    },
    "AC-R06-03": {
        "facts": ["calculationDocuments.documents", "project.pipelines"],
        "tools": [
            "extract_document_fields",
            "recognize_signatures_and_seals",
            "evaluate_design_document_approval",
            "validate_evidence_grounding",
        ],
        "parameters": {
            "argumentProfile": "r06_four_level_approval",
            "approvalMode": "four_level_conditional",
            "targetDocumentTypes": ["pipeline_stress_calculation"],
            "requiredRoles": ["设计", "校核", "审核", "审定"],
            "triggerProfile": "gc1-or-gcd-pressure-temperature-v1",
            "ruleVersion": "r06-design-approval-tsg31-2025-3.1.3.3-v1",
        },
    },
    "AC-R07-01": {
        "facts": [
            "designChanges.hasDesignChanges",
            "designChanges.documents[].documentId",
            "designChanges.documents[].documentType",
            "designChanges.documents[].changedDocumentType",
            "designChanges.documents[].writtenApproval",
            "designChanges.documents[].originalDesignOrganizationName",
            "designChanges.documents[].approvingOrganizationName",
            "designChanges.documents[].signatureRoles",
            "designChanges.documents[].designLicenseSeal",
            "designChanges.documents[].coveredPipelineIds",
            "project.pipelines",
        ],
        "tools": [
            "extract_document_fields",
            "recognize_signatures_and_seals",
            "evaluate_design_change_approval",
            "verify_design_license_seals",
            "validate_evidence_grounding",
        ],
        "parameters": {
            "argumentProfile": "r07_design_change_approval",
            "approvalLevelPolicy": "inherit_changed_document_and_pipeline",
            "requiredDocumentTypes": ["drawing_catalog", "pipeline_layout_drawing"],
            "expectedSealName": "压力管道设计许可印章",
            "sealPolicy": "tsg31_2025_3.1.2_by_document_type",
            "ruleVersion": "r07-design-change-tsg31-2025-v1",
        },
    },
}


R09_BINDINGS: dict[str, dict[str, Any]] = {
    "AC-R09-01": {
        "facts": [
            "designSpecialRequirements.domains.ndt",
            "designSpecialRequirements.domains.corrosion",
            "designSpecialRequirements.domains.pressureTest",
            "designSpecialRequirements.domains.leakTest",
            "fixedClauses.designSpecialRequirementRules",
        ],
        "tools": [
            "extract_document_fields",
            "extract_table_records",
            "evaluate_design_special_requirements",
            "validate_evidence_grounding",
        ],
        "parameters": {
            "argumentProfile": "r09_design_special_requirements",
            "domains": ["ndt", "corrosion", "pressureTest", "leakTest"],
            "requiredPathsByDomain": {
                "ndt": ["requirements.method", "requirements.coverage", "requirements.acceptanceCriteria"],
                "corrosion": ["requirements.protectionMethod", "requirements.acceptanceCriteria"],
                "pressureTest": ["requirements.method", "requirements.testPressure", "requirements.acceptanceCriteria"],
                "leakTest": ["requirements.method", "requirements.testPressure", "requirements.acceptanceCriteria"],
            },
            "ruleVersion": "r09-design-special-requirements-v1",
        },
    },
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
    if rule_id == "R69":
        facts, _, profile = RULE_PROFILES[rule_id]
        return {
            "atomicCheckId": check_id,
            "sourceRuleId": rule_id,
            "requiredFacts": facts,
            "tools": ["locate_evidence_fragment", "extract_document_fields", "check_document_set_completeness", "validate_evidence_grounding"],
            "parameters": {
                "profile": profile,
                "clauseSource": "frozen_standard_clause_package",
                "failurePolicy": check["failurePolicy"],
                "requiredReportFields": ["result", "evaluator", "evaluationDate", "coveredProjectId"],
                "automatedDecisionAllowed": False,
            },
            "outputSchema": "manual-evaluation-evidence-result-v1",
            "implementationStatus": "implemented",
        }
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
    r04_override = R04_BINDINGS.get(check_id)
    if r04_override:
        return {
            "atomicCheckId": check_id,
            "sourceRuleId": rule_id,
            "requiredFacts": r04_override["facts"],
            "tools": r04_override["tools"],
            "parameters": {
                "profile": "design_approval",
                "clauseSource": "frozen_standard_clause_package",
                "failurePolicy": check["failurePolicy"],
                **r04_override["parameters"],
            },
            "outputSchema": "deterministic-tool-result-v1",
            "implementationStatus": "implemented",
        }
    r01_r03_override = R01_R03_BINDINGS.get(check_id)
    if r01_r03_override:
        return {
            "atomicCheckId": check_id,
            "sourceRuleId": rule_id,
            "requiredFacts": r01_r03_override["facts"],
            "tools": r01_r03_override["tools"],
            "parameters": {
                "profile": RULE_PROFILES[rule_id][2],
                "clauseSource": "frozen_standard_clause_package",
                "failurePolicy": check["failurePolicy"],
                **r01_r03_override["parameters"],
            },
            "outputSchema": "deterministic-tool-result-v1",
            "implementationStatus": "pilot_implemented",
        }
    r06_r07_override = R06_R07_BINDINGS.get(check_id)
    if r06_r07_override:
        return {
            "atomicCheckId": check_id,
            "sourceRuleId": rule_id,
            "requiredFacts": r06_r07_override["facts"],
            "tools": r06_r07_override["tools"],
            "parameters": {
                "profile": RULE_PROFILES[rule_id][2],
                "clauseSource": "frozen_standard_clause_package",
                "failurePolicy": check["failurePolicy"],
                **r06_r07_override["parameters"],
            },
            "outputSchema": "deterministic-tool-result-v1",
            "implementationStatus": "pilot_implemented",
        }
    r09_override = R09_BINDINGS.get(check_id)
    if r09_override:
        return {
            "atomicCheckId": check_id,
            "sourceRuleId": rule_id,
            "requiredFacts": r09_override["facts"],
            "tools": r09_override["tools"],
            "parameters": {
                "profile": RULE_PROFILES[rule_id][2],
                "clauseSource": "frozen_standard_clause_package",
                "failurePolicy": check["failurePolicy"],
                **r09_override["parameters"],
            },
            "outputSchema": "deterministic-tool-result-v1",
            "implementationStatus": "pilot_implemented",
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
    trace_count = sum(1 for check in checks if check["instruction"] == TRACE_INSTRUCTION)
    lines = [
        "# Tools 规划",
        "",
        f"> 生成源：`backend/business_packs/engineering_inspection_v1/atomic_checks.yaml`。本文件覆盖全部 {len(checks)} 个 atomicCheck；`implemented` 表示 Tool 链已实现，`pilot_implemented` 表示实现仍受试点范围或专业规则版本限制。R69 虽使用已实现的确定性 Tool，但 Tool 只校验证据、不生成业务结论。",
        "",
        "## 1. 统一绑定协议",
        "",
        "```text",
        "atomicCheck → requiredFacts → tools → parameters → outputSchema",
        "```",
        "",
        "- 固定条款来自 ReviewRun 冻结的 `standardClausePackage`，LLM 不选择或替换条款。",
        "- Tool Result 统一返回 `passed / failed / evidence_insufficient / not_applicable`。",
        f"- {trace_count} 个重复证据追溯项统一使用 `validate_evidence_grounding`，但仍保留逐 atomicCheck 绑定，确保审计覆盖完整。",
        "- R69 为人工评价边界：Tool 汇总 R01-R68 结果并校验评价报告字段，最终评价结论只能采用监检人员签发结果。",
        "- 试点范围：R01-R03、R06-R07、R09、R24、R60-R62。",
        "",
        "## 2. 试点已实现 Tool",
        "",
        "| Tool | 试点 | 作用 |",
        "|---|---|---|",
        "| `check_all_equal` | R01/R24 | 标准化机构名称或人员身份一致性 |",
        "| `check_date_covers` | R01/R24 | 证照有效期覆盖业务周期 |",
        "| `check_design_license_scope` | R01 | GC1、GC2、GCD 设计许可范围覆盖 |",
        "| `decode_welder_qualification` | R24 | 解析焊工项目代号 |",
        "| `check_welder_work_coverage` | R24 | 方法、材料、位置、厚度、管径覆盖 |",
        "| `check_pressure_gauge_requirements` | R60 | 压力表数量、有效期、精度和量程 |",
        "| `check_pressure_test_parameters` | R61 | 温度应力比、压力上下限、保压、气压分级升压和结果 |",
        "| `check_pressure_test_report_consistency` | R62 | 报告、方案与现场参数一致性 |",
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
