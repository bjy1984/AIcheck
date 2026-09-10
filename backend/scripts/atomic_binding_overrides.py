"""Explicit binding corrections not expressible by the legacy rule-profile heuristics.

Maintained source for generation; never reads the generated YAML at runtime.
"""

ATOMIC_BINDING_OVERRIDES = {'AC-R01-03': {'requiredFacts': ['certificateFacts.certificates',
                                 'designLicense.validFrom',
                                 'designLicense.validUntil',
                                 'project.constructionStart',
                                 'project.plannedConstructionEnd',
                                 'project.actualConstructionEnd',
                                 'project.changeClarificationEnd'],
               'tools': ['extract_document_fields',
                         'check_date_covers',
                         'check_certificate_validity',
                         'validate_evidence_grounding']},
 'AC-R02-02': {'requiredFacts': ['certificateFacts.certificates',
                                 'installationLicense.validFrom',
                                 'installationLicense.validUntil',
                                 'project.constructionStart',
                                 'project.plannedConstructionEnd'],
               'tools': ['extract_document_fields',
                         'check_date_covers',
                         'check_certificate_validity',
                         'validate_evidence_grounding']},
 'AC-R03-03': {'requiredFacts': ['certificateFacts.certificates',
                                 'ndtAgencies.agencies[].agencyId',
                                 'ndtAgencies.agencies[].validFrom',
                                 'ndtAgencies.agencies[].validUntil',
                                 'ndtAgencies.agencies[].periodStart',
                                 'ndtAgencies.agencies[].plannedPeriodEnd'],
               'tools': ['extract_document_fields',
                         'check_certificate_validity',
                         'evaluate_ndt_agencies',
                         'validate_evidence_grounding']},
 'AC-R05-01': {'tools': ['get_document_ocr_result',
                         'extract_document_fields',
                         'evaluate_drawing_review_witness',
                         'validate_evidence_grounding'],
               'parameters': {'profile': 'drawing_review_witness',
                              'clauseSource': 'frozen_standard_clause_package',
                              'failurePolicy': 'business_rule_result',
                              'acceptedTypes': ['review_approval_certificate',
                                                'review_opinion',
                                                'design_reply',
                                                'owner_filing_receipt'],
                              'requireSeal': True,
                              'ruleVersion': 'r05-drawing-review-witness-v1'}},
 'AC-R08-01': {'requiredFacts': ['design.standardReferences',
                                 'standardCatalog.versionStatus',
                                 'officialStandardStatus',
                                 'reviewDate'],
               'tools': ['get_document_ocr_result',
                         'extract_document_fields',
                         'check_date_covers',
                         'lookup_standard_status',
                         'check_standard_version_active',
                         'validate_evidence_grounding']},
 'AC-R12-01': {'tools': ['get_document_ocr_result',
                         'extract_document_fields',
                         'extract_table_records',
                         'recognize_signatures_and_seals',
                         'check_signature_completeness',
                         'check_cross_document_match',
                         'check_scope_coverage',
                         'evaluate_component_manufacturer_scope',
                         'validate_evidence_grounding',
                         'verify_org_license']},
 'AC-R24-01': {'requiredFacts': ['certificateFacts.certificates',
                                 'r24.certificates',
                                 'r24.qualificationCodes',
                                 'r24.workDate'],
               'tools': ['extract_welder_certificate',
                         'decode_welder_qualification',
                         'check_welder_work_coverage',
                         'check_certificate_validity',
                         'verify_welder_on_platform']},
 'AC-R35-01': {'requiredFacts': ['r35.projectId',
                                 'r35.organizationId',
                                 'r35.activityDate',
                                 'r35.applicability',
                                 'r35.manual',
                                 'r35.controlledForms',
                                 'r35.appointments',
                                 'r35.implementationRecords',
                                 'r35.equipmentIds',
                                 'r35.calibrationReports'],
               'tools': ['get_document_ocr_result',
                         'extract_document_fields',
                         'extract_table_records',
                         'evaluate_ndt_quality_system',
                         'validate_evidence_grounding'],
               'parameters': {'decisionTool': 'evaluate_ndt_quality_system',
                              'profile': 'ndt_quality_system',
                              'clauseSource': 'frozen_standard_clause_package',
                              'failurePolicy': 'business_rule_result'}},
 'AC-R35-02': {'parameters': {'resultRole': 'evidence_gate',
                              'minConfidence': 0.75,
                              'requirePage': True,
                              'requireBboxOrQuotedText': True,
                              'denyOnConflict': True}},
 'AC-R38-01': {'requiredFacts': ['certificateFacts.certificates',
                                 'ndtPersonnel.roster',
                                 'ndtPersonnel.qualificationCodes',
                                 'ndtPersonnel.registration',
                                 'actualNdt.workItems'],
               'tools': ['get_document_ocr_result',
                         'extract_document_fields',
                         'extract_table_records',
                         'check_required',
                         'check_conditional_requirement',
                         'check_ndt_personnel_coverage',
                         'check_certificate_validity',
                         'validate_evidence_grounding']},
 'AC-R36-01': {'requiredFacts': ['r36.projectId', 'r36.applicability', 'r36.plan', 'r36.requirements'],
               'tools': ['get_document_ocr_result',
                         'extract_document_fields',
                         'extract_table_records',
                         'evaluate_r36_ndt_plan',
                         'validate_evidence_grounding'],
               'parameters': {'profile': 'ndt_plan',
                              'decisionTool': 'evaluate_r36_ndt_plan',
                              'clauseSource': 'frozen_standard_clause_package',
                              'failurePolicy': 'business_rule_result'}},
 'AC-R36-02': {'parameters': {'resultRole': 'evidence_gate',
                              'minConfidence': 0.75,
                              'requirePage': True,
                              'requireBboxOrQuotedText': True,
                              'denyOnConflict': True}},
'AC-R37-01': {'requiredFacts': ['r37.projectId',
                                 'r37.organizationId',
                                 'r37.applicability',
                                 'r37.procedure',
                                 'r37.caseInventory',
                                 'r37.commissions'],
               'tools': ['get_document_ocr_result',
                         'extract_document_fields',
                         'extract_table_records',
                         'evaluate_ndt_nonconformance',
                         'validate_evidence_grounding'],
               'parameters': {'profile': 'ndt_nonconformance_witness',
                              'decisionTool': 'evaluate_ndt_nonconformance',
                              'clauseSource': 'frozen_standard_clause_package',
                              'failurePolicy': 'business_rule_result'}},
 'AC-R37-02': {'requiredFacts': ['r37.projectId',
                                 'r37.organizationId',
                                 'r37.progressiveInventory',
                                 'r37.caseInventory',
                                 'r37.closureLinks'],
               'tools': ['get_document_ocr_result',
                         'extract_document_fields',
                         'extract_table_records',
                         'evaluate_r37_defect_closure',
                         'validate_evidence_grounding'],
               'parameters': {'profile': 'ndt_progression_reinspection_closure',
                              'decisionTool': 'evaluate_r37_defect_closure',
                              'clauseSource': 'frozen_standard_clause_package',
                              'failurePolicy': 'business_rule_result'}},
 'AC-R37-03': {'parameters': {'resultRole': 'evidence_gate',
                              'minConfidence': 0.75,
                              'requirePage': True,
                              'requireBboxOrQuotedText': True,
                              'denyOnConflict': True}}}


ATOMIC_BINDING_OVERRIDES.update({
    "AC-R40-01": {"tools": ["get_document_ocr_result", "extract_document_fields", "extract_table_records", "check_required", "evaluate_ndt_process", "evaluate_r40_parameters", "evaluate_r40_conclusions", "validate_evidence_grounding"], "parameters": {"profile": "ndt_record_report", "clauseSource": "frozen_standard_clause_package",
        "failurePolicy": "business_rule_result", "pendingCapabilities": ["technical_parameters", "design_requirements", "report_results"]}},
    "AC-R39-01": {
        "requiredFacts": ["r39.procedureReference", "r39.documentContent", "r39.approvalChain", "r39.firstUseValidation", "r39.ptEmulsifierApplication", "r39.inventoryConsistency"],
        "tools": ["get_document_ocr_result", "extract_document_fields", "extract_table_records",
                  "evaluate_r39_procedure_reference", "evaluate_r39_document_content", "evaluate_r39_approval_chain",
                  "evaluate_r39_first_use_validation", "evaluate_r39_pt_emulsifier_application", "evaluate_r39_inventory_consistency", "validate_evidence_grounding"],
        "parameters": {"profile": "ndt_procedure_partial_review", "clauseSource": "frozen_standard_clause_package",
                       "failurePolicy": "business_rule_result",
                       "pendingCapabilities": ["procedure_reference_consistency", "method_specific_technical_requirements", "complete_document_and_application_inventory"]},
    },
    "AC-R39-02": {"parameters": {"resultRole": "evidence_gate", "minConfidence": 0.75,
                                  "requirePage": True, "requireBboxOrQuotedText": True, "denyOnConflict": True}},
})


ATOMIC_BINDING_OVERRIDES.update({
    "AC-R11-02": {
        "requiredFacts": ["r11.projectParameters"],
        "tools": ["extract_table_records", "evaluate_r11_project_parameters", "validate_evidence_grounding"],
        "parameters": {"profile": "construction_plan_object_comparison", "failurePolicy": "business_rule_result"},
    },
})

# AC-R11-03「焊接、试验等内容是否满足施工标准要求」原先只绑通用的 evaluate_construction_plan，
# 等于没有专用判定。判据取自规则包冻结的 constructionPlanProcessRules，工具不自行推导限值。
ATOMIC_BINDING_OVERRIDES["AC-R11-03"] = {
    "requiredFacts": ["r11.processStandards"],
    "tools": ["extract_table_records", "evaluate_r11_process_standards", "validate_evidence_grounding"],
    "parameters": {"profile": "construction_plan_process_standards", "failurePolicy": "business_rule_result",
                   "clauseSource": "frozen_standard_clause_package"},
}

# AC-R45-01 原先绑 evaluate_corrosion_protection——那个名字在 business_tools 里没有实现，
# 落到通用解释器且 ruleChecks 无人产生，资料再齐也只返回"未配置"的证据不足。
# 判据改为从规则包冻结的 holidayTestRules 取。
# R64／R66／R67 原先都绑 evaluate_leak_test——那个名字在 business_tools 里没有实现。
# 判据改为从各自规则包冻结的块取（8.6.1.7、8.6.2.1-8.6.2.3、8.7 均已 source_verified）。
for _check_id, _fact, _tool, _profile in (
    ("AC-R64-01", "r64.alternativeTest", "evaluate_r64_alternative_test", "alternative_test"),
    ("AC-R66-01", "r66.leakTestConditions", "evaluate_r66_leak_test_conditions", "leak_test_conditions"),
    ("AC-R67-01", "r67.leakTestMethod", "evaluate_r67_leak_test_method", "leak_test_method"),
):
    ATOMIC_BINDING_OVERRIDES[_check_id] = {
        "requiredFacts": [_fact],
        "tools": ["extract_table_records", _tool, "validate_evidence_grounding"],
        "parameters": {"profile": _profile, "failurePolicy": "business_rule_result",
                       "clauseSource": "frozen_standard_clause_package"},
    }

# AC-R63-01 原绑 evaluate_stress_analysis、AC-R68-01 原绑 evaluate_blowing_cleaning——
# 两个名字在 business_tools 里都没有实现。判据改为从各自规则包冻结的块取
# （6.7.5.5／8.6.1.7、7.9.1-7.9.5 均已 source_verified，正文已逐句核对）。
for _check_id, _fact, _tool, _profile in (
    ("AC-R63-01", "r63.stressAnalysis", "evaluate_r63_stress_analysis", "flexibility_stress_analysis"),
    ("AC-R68-01", "r68.blowingCleaning", "evaluate_r68_blowing_cleaning", "blowing_and_cleaning"),
):
    ATOMIC_BINDING_OVERRIDES[_check_id] = {
        "requiredFacts": [_fact],
        "tools": ["extract_table_records", _tool, "validate_evidence_grounding"],
        "parameters": {"profile": _profile, "failurePolicy": "business_rule_result",
                       "clauseSource": "frozen_standard_clause_package"},
    }

# R47／R48／R50／R53／R54／R55 原先分别绑 evaluate_static_grounding、evaluate_crossing_structure、
# evaluate_corrosion_protection、evaluate_pipe_installation、evaluate_compensator、
# evaluate_support_components——这些名字在 business_tools 里都没有实现。判据改为从各自规则包
# 冻结的块取，来源全部是 GB/T 20801.1-2025 已逐句核对的正文。
for _check_id, _fact, _tool, _profile in (
    ("AC-R47-01", "r47.staticGrounding", "evaluate_r47_static_grounding", "static_grounding"),
    ("AC-R48-01", "r48.weldLayout", "evaluate_r48_weld_layout", "crossing_weld_layout"),
    ("AC-R50-01", "r50.sleeveInsulation", "evaluate_r50_sleeve_insulation", "sleeve_insulation"),
    ("AC-R52-01", "r52.prefabrication", "evaluate_r52_prefabrication", "field_prefabrication"),
    ("AC-R53-01", "r53.installationConnections", "evaluate_r53_installation_connections", "installation_connections"),
    ("AC-R53-02", "r53.equipmentConnection", "evaluate_r53_equipment_connection", "equipment_connection"),
    ("AC-R54-01", "r54.compensator", "evaluate_r54_compensator", "compensator_installation"),
    ("AC-R55-01", "r55.supports", "evaluate_r55_supports", "support_components"),
):
    ATOMIC_BINDING_OVERRIDES[_check_id] = {
        "requiredFacts": [_fact],
        "tools": ["extract_table_records", _tool, "validate_evidence_grounding"],
        "parameters": {"profile": _profile, "failurePolicy": "business_rule_result",
                       "clauseSource": "frozen_standard_clause_package"},
    }

ATOMIC_BINDING_OVERRIDES["AC-R45-01"] = {
    "requiredFacts": ["r45.holidayTest"],
    "tools": ["extract_table_records", "evaluate_r45_holiday_test", "validate_evidence_grounding"],
    "parameters": {"profile": "coating_holiday_test", "failurePolicy": "business_rule_result",
                   "clauseSource": "frozen_standard_clause_package"},
}

ATOMIC_BINDING_OVERRIDES["AC-R11-01"] = {
    "requiredFacts": ["r11.approval"],
    "tools": ["extract_table_records", "evaluate_construction_plan", "validate_evidence_grounding"],
    "parameters": {"profile": "construction_plan_approval", "failurePolicy": "business_rule_result",
                   "pendingCapabilities": ["signature_authenticity_and_authority", "owner_reply_validity_and_timing"]},
}
