from __future__ import annotations

from libs.business_pack import load_business_pack
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan


def test_all_engineering_node_plans_compile_against_runtime_catalog() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plans = [compile_node_tool_plan(pack, f"R{node_id:02d}", available_tools=available) for node_id in range(1, 69)]

    assert sum(len(plan) for plan in plans) == 171
    assert all(item["compilable"] for plan in plans for item in plan)
    assert all(not item["missingTools"] for plan in plans for item in plan)
    assert {item["implementationStatus"] for plan in plans for item in plan} <= {
        "implemented",
        "pilot_implemented",
    }


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
    assert insufficient["result"] == "failed"


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
