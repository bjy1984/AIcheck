from __future__ import annotations

import pytest

from libs.business_pack import load_business_pack
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan


def test_all_engineering_node_plans_compile_against_runtime_catalog() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plans = [compile_node_tool_plan(pack, f"R{node_id:02d}", available_tools=available) for node_id in range(1, 70)]

    assert sum(len(plan) for plan in plans) == 194
    assert all(item["compilable"] for plan in plans for item in plan)
    assert all(not item["missingTools"] for plan in plans for item in plan)
    assert {item["implementationStatus"] for plan in plans for item in plan} <= {
        "binding_only",
        "pilot_implemented",
    }


def test_formal_plan_allows_only_explicit_pilot_rule_while_binding_set_is_draft() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}

    r12_plan = compile_node_tool_plan(pack, "R12", available_tools=available, require_published=True)
    r13_plan = compile_node_tool_plan(pack, "R13", available_tools=available, require_published=True)
    r14_plan = compile_node_tool_plan(pack, "R14", available_tools=available, require_published=True)
    r15_plan = compile_node_tool_plan(pack, "R15", available_tools=available, require_published=True)
    r19_plan = compile_node_tool_plan(pack, "R19", available_tools=available, require_published=True)
    r20_plan = compile_node_tool_plan(pack, "R20", available_tools=available, require_published=True)
    r21_plan = compile_node_tool_plan(pack, "R21", available_tools=available, require_published=True)
    r22_plan = compile_node_tool_plan(pack, "R22", available_tools=available, require_published=True)
    r23_plan = compile_node_tool_plan(pack, "R23", available_tools=available, require_published=True)

    assert r12_plan
    assert r13_plan
    assert r14_plan
    assert r15_plan
    assert r19_plan
    assert r20_plan and r21_plan and r22_plan and r23_plan
    assert all(item["pilotRuleEnabled"] is True for item in r12_plan)
    assert all(item["pilotRuleEnabled"] is True for item in r13_plan)
    assert all(item["pilotRuleEnabled"] is True for item in r14_plan)
    assert all(item["pilotRuleEnabled"] is True for item in r15_plan)
    assert all(item["pilotRuleEnabled"] is True for item in r19_plan)
    assert all(item["pilotRuleEnabled"] is True for item in [*r20_plan, *r21_plan, *r22_plan, *r23_plan])
    with pytest.raises(ValueError, match="published.*or an explicitly enabled pilot rule"):
        compile_node_tool_plan(pack, "R11", available_tools=available, require_published=True)


def test_fixed_plan_runs_all_bound_tools_and_fails_closed_on_missing_facts() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plan = compile_node_tool_plan(pack, "R02", available_tools=available)
    called: list[str] = []

    def runner(name: str, arguments: dict) -> dict:
        called.append(name)
        return dispatch_runtime_tool({}, name, arguments)

    output = execute_node_tool_plan(plan, tool_runner=runner, document_version_ids=[])

    assert output["result"] in {"failed", "evidence_insufficient"}
    assert output["result"] != "passed"
    assert output["summary"]["atomicCheckCount"] == len(plan)
    assert called == [tool for item in plan for tool in item["tools"]]


def test_aggregation_never_turns_failed_or_insufficient_into_passed() -> None:
    plan = [
        {
            "atomicCheckId": "AC-X-1",
            "sourceRuleId": "RX",
            "requiredFacts": ["x"],
            "tools": ["check_required"],
            "parameters": {},
            "compilable": True,
            "missingTools": [],
        }
    ]

    passed = execute_node_tool_plan(
        plan,
        facts={"x": 1},
        tool_runner=lambda name, args: dispatch_runtime_tool({}, name, args),
    )
    insufficient = execute_node_tool_plan(
        plan,
        facts={},
        tool_runner=lambda name, args: dispatch_runtime_tool({}, name, args),
    )

    assert passed["result"] == "passed"
    # 业务口径（issue #3）：事实字段缺失是「证据不足」而非「不符合」；
    # 只有字段有值且不满足规则、或应交文件本体缺失时才是 failed。
    assert insufficient["result"] == "evidence_insufficient"


def test_r04_plan_assembles_document_completeness_and_approval_arguments() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plan = compile_node_tool_plan(pack, "R04", available_tools=available)
    captured: list[tuple[str, dict]] = []

    facts = {
        "designDocumentSet": {
            "catalogListedDocumentTypes": ["drawing_catalog"],
            "uploadedDocumentTypes": ["drawing_catalog"],
            "parseableDocumentTypes": ["drawing_catalog"],
        },
        "designDocuments": {
            "documents": [
                {
                    "documentId": "D1",
                    "documentType": "pipeline_layout_drawing",
                    "bodyUploaded": True,
                    "signatureRoles": ["设计", "校核", "审核", "审定"],
                    "coveredPipelineIds": ["P1"],
                }
            ]
        },
        "project": {
            "pipelines": [
                {"pipelineId": "P1", "pipelineGrade": "GC1", "designPressureMPa": 1, "designTemperatureC": 20}
            ]
        },
    }

    def runner(name: str, arguments: dict) -> dict:
        captured.append((name, arguments))
        return dispatch_runtime_tool({}, name, arguments)

    execute_node_tool_plan(plan, tool_runner=runner, facts=facts)

    completeness = next(arguments for name, arguments in captured if name == "check_document_set_completeness")
    approvals = [arguments for name, arguments in captured if name == "evaluate_design_document_approval"]
    assert completeness["uploadedDocumentTypes"] == ["drawing_catalog"]
    assert completeness["requiredDocumentTypes"] == [
        "drawing_catalog",
        "design_specification",
        "pipeline_data_sheet",
        "pipeline_layout_drawing",
        "pipeline_material_list",
        "straight_pipe_strength_calculation",
    ]
    assert [item["approvalMode"] for item in approvals] == ["three_level", "four_level_conditional"]
    assert approvals[1]["pipelines"][0]["pipelineGrade"] == "GC1"


def test_r01_plan_assembles_identity_scope_and_latest_business_end_date() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plan = compile_node_tool_plan(pack, "R01", available_tools=available)
    captured: list[tuple[str, dict]] = []
    facts = {
        "designLicense": {
            "holderName": "甲设计院有限公司",
            "scopeCodes": ["GC1"],
            "validFrom": "2025-01-01",
            "validUntil": "2026-12-31",
        },
        "designDocument": {
            "titleBlockOrganization": "甲设计院有限公司",
            "designSealOrganization": "甲设计院有限公司",
            "pipelineGrades": ["GC1"],
        },
        "project": {
            "pipelineGrades": ["GC1"],
            "constructionStart": "2026-01-01",
            "plannedConstructionEnd": "2026-09-30",
            "actualConstructionEnd": "2026-10-31",
            "changeClarificationEnd": "2026-11-15",
        },
    }

    execute_node_tool_plan(
        plan,
        facts=facts,
        tool_runner=lambda name, arguments: captured.append((name, arguments)) or dispatch_runtime_tool({}, name, arguments),
    )

    equality = next(arguments for name, arguments in captured if name == "check_all_equal")
    dates = next(arguments for name, arguments in captured if name == "check_date_covers")
    assert [item["value"] for item in equality["values"]] == ["甲设计院有限公司"] * 3
    assert dates["periodEnd"] == "2026-11-15"


def test_r02_and_r03_plans_use_specialized_tools_without_signature_false_positive() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    r02 = compile_node_tool_plan(pack, "R02", available_tools=available)
    r03 = compile_node_tool_plan(pack, "R03", available_tools=available)
    bound = [tool for item in [*r02, *r03] for tool in item["tools"]]

    assert "check_installation_license_scope" in bound
    assert "decode_ndt_approval_item_codes" in bound
    assert "evaluate_ndt_agencies" in bound
    assert "recognize_signatures_and_seals" not in bound
    assert "check_signature_completeness" not in bound


def test_r03_plan_assembles_all_agencies_for_fan_out() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plan = compile_node_tool_plan(pack, "R03", available_tools=available)
    captured: list[tuple[str, dict]] = []
    agencies = [
        {"agencyId": "A1", "approvalItemCodes": ["CG"], "requiredMethods": ["RT"]},
        {"agencyId": "A2", "approvalItemCodes": ["PA"], "requiredMethods": ["PA"]},
    ]

    execute_node_tool_plan(
        plan,
        facts={"ndtAgencies": {"agencies": agencies}},
        tool_runner=lambda name, arguments: captured.append((name, arguments)) or dispatch_runtime_tool({}, name, arguments),
    )

    decoded = next(arguments for name, arguments in captured if name == "decode_ndt_approval_item_codes")
    evaluations = [arguments for name, arguments in captured if name == "evaluate_ndt_agencies"]
    assert decoded["approvalItemCodes"] == ["CG", "PA"]
    assert all(arguments["agencies"] == agencies for arguments in evaluations)


def test_r20_r23_plans_assemble_specialized_business_arguments() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    facts = {
        "r20": {
            "designItems": [{"componentItemId": "N1"}],
            "typeTestReports": [{"reportNo": "TT-1"}],
            "technicalReviewApprovals": [{"approvalDocumentNo": "A-1"}],
            "materialDataDocuments": [{"documentNo": "M-1"}],
        },
        "r21": {"markTransferOccurred": False, "transferRecords": [], "materialInventory": []},
        "r22": {"materialSubstitutionOccurred": False, "substitutionRecords": [], "actualMaterialUsage": []},
        "r23": {
            "designStandardRefs": [],
            "contractStandardRefs": [],
            "designAndContractBasisChecked": True,
            "testLots": [{"lotId": "L1"}],
            "constructionRecords": [{"recordId": "C1"}],
            "testRecords": [{"recordId": "V1"}],
            "standardRequirementProfiles": {"GB/T 13927-2022": {"shell": {}}},
        },
    }
    captured: list[tuple[str, dict]] = []

    for rule_id in ("R20", "R21", "R22", "R23"):
        execute_node_tool_plan(
            compile_node_tool_plan(pack, rule_id, available_tools=available),
            facts=facts,
            tool_runner=lambda name, arguments: captured.append((name, arguments))
            or {"status": "succeeded", "result": "passed"},
        )

    by_name = dict(captured)
    assert by_name["evaluate_r20_new_material_procedure"]["typeTestReports"][0]["reportNo"] == "TT-1"
    assert by_name["evaluate_r21_mark_transfer"]["markTransferOccurred"] is False
    assert by_name["evaluate_r22_material_substitution"]["materialSubstitutionOccurred"] is False
    assert by_name["resolve_r23_valve_test_basis"]["designAndContractBasisChecked"] is True
    assert "GB/T 13927-2022" in by_name["evaluate_r23_valve_test_records"]["standardRequirementProfiles"]


def test_r06_plan_reuses_document_approval_with_standard_document_scope() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plan = compile_node_tool_plan(pack, "R06", available_tools=available)
    captured: list[tuple[str, dict]] = []
    documents = [
        {
            "documentId": "S-1",
            "documentType": "strength_calculation",
            "bodyUploaded": True,
            "coveredPipelineIds": ["P1"],
            "signatureRoles": ["设计", "校核", "审核"],
            "parameterComparisons": [{"code": "pressure", "documentValue": 1, "designValue": 1}],
        },
        {
            "documentId": "STRESS-1",
            "documentType": "pipeline_stress_calculation",
            "bodyUploaded": True,
            "coveredPipelineIds": ["P1"],
            "signatureRoles": ["设计", "校核", "审核", "审定"],
            "parameterComparisons": [{"code": "pressure", "documentValue": 1, "designValue": 1}],
        },
    ]
    facts = {
        "calculationDocuments": {"documents": documents},
        "project": {"pipelines": [{"pipelineId": "P1", "pipelineGrade": "GC1"}]},
    }

    execute_node_tool_plan(
        plan,
        facts=facts,
        tool_runner=lambda name, arguments: captured.append((name, arguments)) or dispatch_runtime_tool({}, name, arguments),
    )

    approvals = [arguments for name, arguments in captured if name == "evaluate_design_document_approval"]
    assert approvals[0]["targetDocumentTypes"] == ["strength_calculation", "pipeline_stress_calculation"]
    assert approvals[1]["targetDocumentTypes"] == ["pipeline_stress_calculation"]
    assert all(arguments["documents"] == documents for arguments in approvals)


def test_r07_plan_assembles_design_changes_and_avoids_generic_signature_tools() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plan = compile_node_tool_plan(pack, "R07", available_tools=available)
    captured: list[tuple[str, dict]] = []
    documents = [
        {
            "documentId": "N-1",
            "documentType": "design_change_notice",
            "changedDocumentType": "strength_calculation",
            "bodyUploaded": True,
            "writtenApproval": True,
            "originalDesignOrganizationName": "甲设计院有限公司",
            "approvingOrganizationName": "甲设计院有限公司",
            "signatureRoles": ["设计", "校核", "审核"],
        }
    ]
    facts = {"designChanges": {"hasDesignChanges": True, "documents": documents}, "project": {"pipelines": []}}

    execute_node_tool_plan(
        plan,
        facts=facts,
        tool_runner=lambda name, arguments: captured.append((name, arguments)) or dispatch_runtime_tool({}, name, arguments),
    )

    names = [name for name, _ in captured]
    approval = next(arguments for name, arguments in captured if name == "evaluate_design_change_approval")
    seals = next(arguments for name, arguments in captured if name == "verify_design_license_seals")
    assert "check_signature_completeness" not in names
    assert approval["documents"] == documents
    assert seals["documents"] == documents
    assert seals["expectedSealName"] == "压力管道设计许可印章"


def test_r09_plan_assembles_design_requirements_and_frozen_standard_rules() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plan = compile_node_tool_plan(pack, "R09", available_tools=available)
    captured: list[tuple[str, dict]] = []
    domains = {
        name: {"specified": True, "requirements": {}, "standardRefs": []}
        for name in ("ndt", "corrosion", "pressureTest", "leakTest")
    }
    rules = {name: {"checks": []} for name in domains}

    execute_node_tool_plan(
        plan,
        facts={
            "designSpecialRequirements": {"domains": domains},
            "fixedClauses": {"designSpecialRequirementRules": rules},
        },
        tool_runner=lambda name, arguments: captured.append((name, arguments)) or dispatch_runtime_tool({}, name, arguments),
    )

    arguments = next(arguments for name, arguments in captured if name == "evaluate_design_special_requirements")
    assert arguments["requirements"] == domains
    assert arguments["standardRules"] == rules
    assert arguments["domains"] == ["ndt", "corrosion", "pressureTest", "leakTest"]


def test_r13_plan_uses_specialized_tools_and_assembles_fact_builder_outputs() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plan = compile_node_tool_plan(pack, "R13", available_tools=available, require_published=True)
    captured: list[tuple[str, dict]] = []
    design_items = [
        {
            "componentItemId": "I-SAW",
            "componentType": "埋弧焊钢管",
            "manufacturerName": "甲制造有限公司",
            "batchNo": "B-1",
            "specification": "DN500",
        }
    ]
    supervision_certificates = [{"certificateNo": "SC-1"}]
    type_test_reports = [{"reportNo": "TR-1"}]

    execute_node_tool_plan(
        plan,
        facts={
            "r13": {
                "designItems": design_items,
                "supervisionCertificates": supervision_certificates,
                "typeTestReports": type_test_reports,
            }
        },
        tool_runner=lambda name, arguments: captured.append((name, arguments)) or dispatch_runtime_tool({}, name, arguments),
    )

    names = [name for name, _ in captured]
    assert "classify_r13_component_requirements" in names
    assert "evaluate_r13_type_test_coverage" in names
    assert "evaluate_r13_supervision_certificate_completeness" in names
    assert "evaluate_material_component" not in names
    assert "check_signature_completeness" not in names
    type_arguments = next(arguments for name, arguments in captured if name == "evaluate_r13_type_test_coverage")
    supervision_arguments = next(
        arguments for name, arguments in captured if name == "evaluate_r13_supervision_certificate_completeness"
    )
    assert type_arguments["designItems"] == design_items
    assert type_arguments["typeTestReports"] == type_test_reports
    assert supervision_arguments["designItems"] == design_items
    assert supervision_arguments["supervisionCertificates"] == supervision_certificates


def test_r13_complete_structured_facts_pass_the_full_fixed_plan() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plan = compile_node_tool_plan(pack, "R13", available_tools=available, require_published=True)
    facts = {
        "r13": {
            "designItems": [
                {
                    "componentItemId": "I-SAW",
                    "componentType": "埋弧焊钢管",
                    "manufacturerName": "甲制造有限公司",
                    "material": "L360",
                    "manufacturingProcess": "埋弧焊",
                    "nominalDiameterMM": 500,
                    "nominalPressureMPa": 10,
                    "batchNo": "B-1",
                }
            ],
            "supervisionCertificates": [
                {
                    "certificateNo": "SC-1",
                    "productName": "埋弧焊钢管",
                    "manufacturerName": "甲制造有限公司",
                    "batchNo": "B-1",
                    "conclusion": "合格",
                }
            ],
            "typeTestReports": [
                {
                    "reportNo": "TR-1",
                    "productName": "埋弧焊钢管",
                    "manufacturerName": "甲制造有限公司",
                    "testOrganization": "特种设备检测院",
                    "material": "L360",
                    "manufacturingProcess": "埋弧焊",
                    "nominalDiameterMinMM": 100,
                    "nominalDiameterMaxMM": 800,
                    "nominalPressureMinMPa": 1,
                    "nominalPressureMaxMPa": 16,
                    "conclusion": "合格",
                }
            ],
        }
    }
    evidence_refs = [
        {
            "evidenceRefId": "EV-R13-1",
            "documentVersionId": "V-1",
            "pageNo": 1,
            "quotedText": "埋弧焊钢管 B-1",
            "confidence": 0.96,
        }
    ]
    evidence_facts = [
        {
            "factId": "r13-item-1",
            "value": "埋弧焊钢管",
            "evidenceRefIds": ["EV-R13-1"],
            "confidence": 0.96,
            "conflicted": False,
        }
    ]

    output = execute_node_tool_plan(
        plan,
        facts=facts,
        evidence_facts=evidence_facts,
        evidence_refs=evidence_refs,
        document_version_ids=["V-1"],
        tool_runner=lambda name, arguments: dispatch_runtime_tool({}, name, arguments),
    )

    assert output["result"] == "passed"
    assert output["summary"] == {
        "atomicCheckCount": 3,
        "passedCount": 3,
        "failedCount": 0,
        "evidenceInsufficientCount": 0,
        "notApplicableCount": 0,
        "humanReviewRequiredCount": 0,
        "executionErrorCount": 0,
    }


def test_r14_plan_uses_specialized_tools_and_assembles_fact_builder_outputs() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plan = compile_node_tool_plan(pack, "R14", available_tools=available, require_published=True)
    captured: list[tuple[str, dict]] = []
    facts = {
        "r14": {
            "designItems": [{"componentItemId": "I-BOLT", "componentType": "高强螺栓"}],
            "pipelineCharacteristics": [{"pipelineCharacteristicId": "P-1", "lineNo": "L-1"}],
            "factoryInspectionReports": [{"reportId": "F-1"}],
            "specialInspectionReports": [{"reportId": "S-1"}],
        }
    }

    execute_node_tool_plan(
        plan,
        facts=facts,
        tool_runner=lambda name, arguments: captured.append((name, arguments)) or dispatch_runtime_tool({}, name, arguments),
    )

    names = [name for name, _ in captured]
    assert "classify_r14_component_applicability" in names
    assert "evaluate_r14_component_design_match" in names
    assert "resolve_r14_required_inspection_items" in names
    assert "evaluate_r14_special_report_coverage" in names
    assert "evaluate_r14_pressure_compatibility" in names
    assert "evaluate_material_component" not in names
    assert "check_cross_document_match" not in names
    pressure_arguments = next(arguments for name, arguments in captured if name == "evaluate_r14_pressure_compatibility")
    special_arguments = next(arguments for name, arguments in captured if name == "evaluate_r14_special_report_coverage")
    assert pressure_arguments["designItems"] == facts["r14"]["designItems"]
    assert pressure_arguments["pipelineCharacteristics"] == facts["r14"]["pipelineCharacteristics"]
    assert pressure_arguments["factoryInspectionReports"] == facts["r14"]["factoryInspectionReports"]
    assert pressure_arguments["specialInspectionReports"] == facts["r14"]["specialInspectionReports"]
    assert special_arguments["productInspectionRules"]["GB/T 12771-2019"]["requiredItems"] == [
        "nondestructive_testing"
    ]


def test_r14_complete_structured_facts_pass_the_full_fixed_plan() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plan = compile_node_tool_plan(pack, "R14", available_tools=available, require_published=True)
    facts = {
        "r14": {
            "designItems": [
                {
                    "componentItemId": "I-BOLT",
                    "componentType": "高强螺栓",
                    "lineNo": "L-100",
                    "specification": "M24",
                    "grade": "8.8",
                    "material": "35CrMo",
                    "batchNo": "B-14",
                    "pressureClass": "PN16",
                    "requiredInspectionItems": ["hardness_test"],
                }
            ],
            "pipelineCharacteristics": [
                {"pipelineCharacteristicId": "P-100", "lineNo": "L-100", "designPressureMPa": 1.6}
            ],
            "factoryInspectionReports": [
                {
                    "reportId": "F-14",
                    "productName": "高强螺栓",
                    "lineNo": "L-100",
                    "specification": "M24",
                    "grade": "8.8级",
                    "material": "35CrMo",
                    "batchNo": "B-14",
                    "pressureClass": "PN16",
                    "conclusion": "合格",
                }
            ],
            "specialInspectionReports": [
                {
                    "reportId": "S-14",
                    "reportType": "hardness_test",
                    "productName": "高强螺栓",
                    "specification": "M24",
                    "batchNo": "B-14",
                    "conclusion": "合格",
                }
            ],
        }
    }
    evidence_refs = [
        {
            "evidenceRefId": "EV-R14-1",
            "documentVersionId": "V-1",
            "pageNo": 1,
            "quotedText": "高强螺栓 M24 8.8级 35CrMo PN16",
            "confidence": 0.96,
        }
    ]
    evidence_facts = [
        {
            "factId": "r14-item-1",
            "value": "高强螺栓",
            "evidenceRefIds": ["EV-R14-1"],
            "confidence": 0.96,
            "conflicted": False,
        }
    ]

    output = execute_node_tool_plan(
        plan,
        facts=facts,
        evidence_facts=evidence_facts,
        evidence_refs=evidence_refs,
        document_version_ids=["V-1"],
        tool_runner=lambda name, arguments: dispatch_runtime_tool({}, name, arguments),
    )

    assert output["result"] == "passed"
    assert output["summary"] == {
        "atomicCheckCount": 4,
        "passedCount": 4,
        "failedCount": 0,
        "evidenceInsufficientCount": 0,
        "notApplicableCount": 0,
        "humanReviewRequiredCount": 0,
        "executionErrorCount": 0,
    }


def test_r15_plan_uses_specialized_tools_and_assembles_fact_builder_outputs() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plan = compile_node_tool_plan(pack, "R15", available_tools=available, require_published=True)
    captured: list[tuple[str, dict]] = []
    facts = {
        "r15": {
            "designItems": [{"componentItemId": "I-R15", "componentType": "金属阀门"}],
            "manufacturingLicenseCandidates": [{"candidateId": "LIC-R15"}],
            "manualRegistryVerifications": [{"candidateId": "LIC-R15"}],
            "supervisionCertificates": [{"certificateId": "SC-R15"}],
            "typeTestReports": [{"reportId": "TR-R15"}],
            "arrivalInspectionRecords": [{"recordId": "ARR-R15"}],
            "completeMachineInspectionRecords": [{"recordId": "CM-R15"}],
        }
    }

    execute_node_tool_plan(
        plan,
        facts=facts,
        tool_runner=lambda name, arguments: captured.append((name, arguments)) or dispatch_runtime_tool({}, name, arguments),
    )

    names = [name for name, _ in captured]
    assert "evaluate_foreign_component" not in names
    assert "classify_r15_foreign_manufacturing_applicability" in names
    assert "classify_r15_regulatory_requirements" in names
    assert "evaluate_r15_manufacturing_license_coverage" in names
    assert "evaluate_r15_type_test_coverage" in names
    assert "evaluate_r15_manufacturing_inspection_route" in names
    license_arguments = next(
        arguments for name, arguments in captured if name == "evaluate_r15_manufacturing_license_coverage"
    )
    route_arguments = next(
        arguments for name, arguments in captured if name == "evaluate_r15_manufacturing_inspection_route"
    )
    assert license_arguments["licenseCandidates"] == facts["r15"]["manufacturingLicenseCandidates"]
    assert license_arguments["registryVerifications"] == facts["r15"]["manualRegistryVerifications"]
    assert route_arguments["arrivalInspectionRecords"] == facts["r15"]["arrivalInspectionRecords"]
    assert route_arguments["completeMachineInspectionRecords"] == facts["r15"]["completeMachineInspectionRecords"]


def test_r15_complete_structured_facts_pass_the_full_fixed_plan() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plan = compile_node_tool_plan(pack, "R15", available_tools=available, require_published=True)
    item = {
        "componentItemId": "I-R15-VALVE",
        "componentType": "金属阀门",
        "manufacturerName": "ACME Valve GmbH",
        "manufacturingCountry": "Germany",
        "material": "WCB",
        "nominalDiameterMM": 100,
        "nominalPressureMPa": 4,
        "requiresManufacturingLicense": True,
        "requiresTypeTest": True,
        "requiresManufacturingSupervision": False,
    }
    facts = {
        "r15": {
            "designItems": [item],
            "manufacturingLicenseCandidates": [
                {
                    "candidateId": "R15LIC-1",
                    "licenseNo": "TS2710X001",
                    "organizationName": "ACME Valve GmbH",
                    "licenseScopeRaw": "压力管道阀门制造",
                }
            ],
            "manualRegistryVerifications": [
                {
                    "candidateId": "R15LIC-1",
                    "outcome": "verified_match",
                    "registryStatus": "active",
                    "registryLicenseNo": "TS2710X001",
                    "registryOrganizationName": "ACME Valve GmbH",
                    "registryScopeRaw": "压力管道阀门制造",
                }
            ],
            "supervisionCertificates": [],
            "typeTestReports": [
                {
                    "reportNo": "TR-R15",
                    "productName": "金属阀门",
                    "manufacturerName": "ACME Valve GmbH",
                    "testOrganization": "型式试验机构",
                    "material": "WCB",
                    "nominalDiameterMinMM": 50,
                    "nominalDiameterMaxMM": 200,
                    "nominalPressureMinMPa": 1,
                    "nominalPressureMaxMPa": 6.4,
                    "conclusion": "合格",
                }
            ],
            "arrivalInspectionRecords": [],
            "completeMachineInspectionRecords": [],
        }
    }
    evidence_refs = [
        {
            "evidenceRefId": "EV-R15-1",
            "documentVersionId": "V-R15",
            "pageNo": 1,
            "quotedText": "德国制造金属阀门 DN100 PN40",
            "confidence": 0.96,
        }
    ]
    evidence_facts = [
        {
            "factId": "r15-item-1",
            "value": "金属阀门",
            "evidenceRefIds": ["EV-R15-1"],
            "confidence": 0.96,
            "conflicted": False,
        }
    ]

    output = execute_node_tool_plan(
        plan,
        facts=facts,
        evidence_facts=evidence_facts,
        evidence_refs=evidence_refs,
        document_version_ids=["V-R15"],
        tool_runner=lambda name, arguments: dispatch_runtime_tool({}, name, arguments),
    )

    assert output["result"] == "passed"
    assert output["summary"] == {
        "atomicCheckCount": 6,
        "passedCount": 5,
        "failedCount": 0,
        "evidenceInsufficientCount": 0,
        "notApplicableCount": 1,
        "humanReviewRequiredCount": 0,
        "executionErrorCount": 0,
    }
