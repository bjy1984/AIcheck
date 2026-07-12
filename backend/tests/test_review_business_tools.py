from __future__ import annotations

import pytest

from libs.review_orchestrator.execution import ALLOWED_AGENT_TOOLS
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
from libs.review_tools import BUSINESS_TOOL_NAMES


def call(name: str, arguments: dict) -> dict:
    return dispatch_runtime_tool({}, name, arguments)


def test_all_planned_business_tools_are_registered_allowed_and_fail_closed() -> None:
    catalog = {item["name"] for item in runtime_tool_catalog()}

    assert len(BUSINESS_TOOL_NAMES) == 41
    assert BUSINESS_TOOL_NAMES <= catalog
    assert BUSINESS_TOOL_NAMES <= ALLOWED_AGENT_TOOLS
    for name in BUSINESS_TOOL_NAMES:
        output = call(name, {})
        assert output["status"] == "succeeded"
        assert output["result"] == "evidence_insufficient", name
        assert output["toolCallId"]


def test_required_and_document_completeness_require_uploaded_bodies() -> None:
    required = call("check_required", {"facts": {"license": {"number": "TS-1"}}, "requiredFields": ["license.number", "license.scope"]})
    documents = call(
        "check_document_set_completeness",
        {
            "requiredDocumentTypes": ["drawing_index", "stress_calculation"],
            "uploadedDocumentTypes": ["drawing_index"],
            "parseableDocumentTypes": ["drawing_index"],
            "catalogListedDocumentTypes": ["drawing_index", "stress_calculation"],
        },
    )

    assert required["result"] == "failed"
    assert documents["result"] == "failed"


def test_scope_signature_and_cross_document_checks_are_deterministic() -> None:
    scope = call(
        "check_scope_coverage",
        {"grantedScopes": ["GC1"], "requiredScopes": ["GC2"], "coverageMap": {"GC2": ["GC1"]}},
    )
    signatures = call(
        "check_signature_completeness",
        {"actualRoles": ["设计", "校核", "审核"], "requiredRoles": ["设计", "校核", "审核", "审定"]},
    )
    comparison = call(
        "check_cross_document_match",
        {"comparisons": [{"code": "pressure", "values": [10, 10.004], "tolerance": 0.01}]},
    )

    assert scope["result"] == "passed"
    assert signatures["result"] == "failed"
    assert comparison["result"] == "passed"


def test_numeric_conditional_and_sampling_boundaries() -> None:
    numeric = call("check_numeric_range", {"ranges": [{"code": "temperature", "value": 570, "min": 570}]})
    not_applicable = call("check_conditional_requirement", {"condition": False, "requiredFields": ["document"]})
    sampling = call(
        "check_sampling_requirement",
        {"populationCount": 21, "sampledCount": 3, "requiredRatio": 0.10, "minimumCount": 1, "selectedIds": ["V1", "V2", "V3"]},
    )

    assert numeric["result"] == "passed"
    assert not_applicable["result"] == "not_applicable"
    assert sampling["result"] == "passed"
    assert sampling["facts"]["input"]["requiredCount"] == 3


def test_numeric_range_supports_single_open_bound() -> None:
    lower_only = call(
        "check_numeric_range",
        {"ranges": [{"code": "pressure", "value": 10, "min": 10, "includeMin": False}]},
    )
    upper_only = call(
        "check_numeric_range",
        {"ranges": [{"code": "temperature", "value": 100, "max": 100, "includeMax": True}]},
    )

    assert lower_only["result"] == "failed"
    assert upper_only["result"] == "passed"


def test_pressure_gauge_requires_highest_point_and_dial_record() -> None:
    output = call(
        "check_pressure_gauge_requirements",
        {
            "maxTestPressure": 10,
            "testDate": "2026-06-15",
            "medium": "clean_water",
            "mediumTemperature": 20,
            "ambientTemperature": 25,
            "gauges": [
                {"validUntil": "2027-01-01", "accuracyClass": 1.6, "rangeMax": 20, "atHighestPoint": False},
                {"validUntil": "2027-01-01", "accuracyClass": 1.6, "rangeMax": 20, "atHighestPoint": False},
            ],
        },
    )

    assert output["result"] == "failed"
    assert any(item["code"] == "at_least_one_gauge_at_highest_point" and not item["passed"] for item in output["checks"])


def test_standard_version_and_traceability() -> None:
    standard = call(
        "check_standard_version_active",
        {
            "reviewDate": "2026-08-01",
            "standardReferences": [
                {"standardRef": "TSG-Z6002-2026", "effectiveFrom": "2026-08-01", "status": "active"}
            ],
        },
    )
    traceability = call(
        "check_traceability",
        {
            "items": [
                {
                    "originalMark": "M-01",
                    "transferredMark": "M-01-A",
                    "batchNo": "B-9",
                    "transferRecord": {"batchNo": "B-9"},
                }
            ]
        },
    )

    assert standard["result"] == "passed"
    assert traceability["result"] == "passed"


def test_installation_license_uses_later_planned_or_actual_end_date() -> None:
    output = call(
        "evaluate_installation_license_scope",
        {
            "licenseScopes": ["A级锅炉安装资质"],
            "requiredPipelineGrades": ["GCD", "GC2"],
            "validFrom": "2025-01-01",
            "validUntil": "2026-11-30",
            "periodStart": "2026-01-01",
            "plannedPeriodEnd": "2026-10-31",
            "actualPeriodEnd": "2026-12-15",
        },
    )

    assert output["result"] == "failed"
    assert any(item["code"] == "valid_until_covers_later_construction_end" for item in output["checks"])


def test_ndt_organization_and_personnel_are_evaluated_per_explicit_context() -> None:
    organization = call(
        "evaluate_ndt_organization_scope",
        {
            "licenseOrganizationName": "甲检测有限公司",
            "planOrganizationName": "甲检测有限公司",
            "licensedMethods": ["RT", "UT"],
            "requiredMethods": ["RT"],
            "validUntil": "2027-01-01",
            "periodStart": "2026-01-01",
            "periodEnd": "2026-12-31",
        },
    )
    personnel = call(
        "check_ndt_personnel_coverage",
        {
            "workDate": "2026-06-01",
            "personnel": [
                {"personId": "P1", "methods": ["RT"], "level": 2, "registered": True, "validUntil": "2027-01-01"}
            ],
            "workItems": [{"method": "RT", "requiredLevel": 2}],
        },
    )

    assert organization["result"] == "passed"
    assert personnel["result"] == "passed"


def test_design_approval_requires_document_body_and_all_roles() -> None:
    output = call(
        "evaluate_design_approval_level",
        {
            "documents": [
                {
                    "documentId": "D1",
                    "bodyUploaded": False,
                    "signatureRoles": ["设计", "校核", "审核", "审定"],
                    "requiredRoles": ["设计", "校核", "审核", "审定"],
                }
            ]
        },
    )

    assert output["result"] == "failed"


def test_wps_pqr_coverage_checks_method_material_position_and_ranges() -> None:
    output = call(
        "check_wps_pqr_coverage",
        {
            "qualifiedRanges": [
                {
                    "id": "PQR-1",
                    "method": "GTAW",
                    "materialCategory": "FeII",
                    "position": "6G",
                    "fillerMetal": "FefS",
                    "thicknessMin": 2,
                    "thicknessMax": 10,
                    "diameterMin": 25,
                }
            ],
            "workItems": [
                {"method": "GTAW", "materialCategory": "FeII", "position": "6G", "fillerMetal": "FefS", "thickness": 6, "diameter": 89}
            ],
        },
    )

    assert output["result"] == "passed"


def test_generic_domain_tools_require_facts_and_executable_rule_checks() -> None:
    name = "evaluate_welding_consumable"
    incomplete = call(name, {"requiredFields": ["certificate"], "facts": {"certificate": "MTC-1"}})
    passed = call(
        name,
        {
            "profile": "welding_consumable_mtc",
            "requiredFields": ["certificate", "batchNo"],
            "facts": {"certificate": "MTC-1", "batchNo": "B-1"},
            "ruleChecks": [
                {"code": "grade_matches", "operator": "equals", "actual": "E5015", "expected": "E5015"},
                {"code": "valid", "operator": "accepted", "actual": "合格", "expected": ["合格"]},
            ],
        },
    )

    assert incomplete["result"] == "evidence_insufficient"
    assert passed["result"] == "passed"


def test_rt_film_and_valve_sampling_rules() -> None:
    film = call(
        "evaluate_rt_film",
        {
            "films": [{"weldId": "W-1", "imageQualityAccepted": True}],
            "reportWeldIds": ["W-1"],
            "sampling": {"populationCount": 20, "sampledCount": 2, "requiredRatio": 0.1, "minimumCount": 1},
        },
    )
    valve = call(
        "evaluate_valve_test",
        {
            "pipelineGrade": "GC2",
            "lotSize": 21,
            "testedCount": 3,
            "testProcedure": "shell_and_seat",
            "testPressure": 2.4,
            "holdMinutes": 5,
            "testResult": "合格",
            "standardRef": "GB/T 13927-2022",
        },
    )

    assert film["result"] == "passed"
    assert valve["result"] == "passed"


def test_pressure_plan_requires_all_controls_and_roles() -> None:
    output = call(
        "evaluate_pressure_test",
        {
            "timing": "after_ndt",
            "medium": "clean_water",
            "pressurizationRate": "controlled",
            "instrumentRequirements": ["two_gauges"],
            "safetyMeasures": ["exclusion_zone"],
            "acceptanceCriteria": ["no_leak"],
            "signatureRoles": ["编制", "审核", "批准"],
            "requiredRoles": ["编制", "审核", "批准"],
        },
    )

    assert output["result"] == "passed"


def test_pressure_test_uses_temperature_stress_ratio_and_component_limit() -> None:
    liquid = call(
        "check_pressure_test_parameters",
        {
            "method": "liquid",
            "designPressure": 10,
            "testPressure": 18,
            "holdMinutes": 10,
            "testResult": "passed",
            "allowableStressAtTestTemperature": 120,
            "allowableStressAtDesignTemperature": 100,
            "maximumAllowableTestPressure": 20,
        },
    )
    unsafe = call(
        "check_pressure_test_parameters",
        {
            "method": "liquid",
            "designPressure": 10,
            "testPressure": 15,
            "holdMinutes": 10,
            "testResult": "passed",
            "allowableStressAtTestTemperature": 120,
            "allowableStressAtDesignTemperature": 100,
            "maximumAllowableTestPressure": 20,
        },
    )

    assert liquid["result"] == "passed"
    assert unsafe["result"] == "failed"
    assert liquid["ruleVersion"] == "pressure-test-parameters-gbt20801-v2"


def test_pneumatic_pressure_enforces_upper_limit_and_step_sequence() -> None:
    steps = [
        {"pressure": 5.5, "holdMinutes": 3},
        {"pressure": 6.6, "holdMinutes": 3},
        {"pressure": 7.7, "holdMinutes": 3},
        {"pressure": 8.8, "holdMinutes": 3},
        {"pressure": 9.9, "holdMinutes": 3},
        {"pressure": 11.0, "holdMinutes": 3},
    ]
    output = call(
        "check_pressure_test_parameters",
        {
            "method": "gas",
            "designPressure": 10,
            "testPressure": 11,
            "holdMinutes": 10,
            "testResult": "passed",
            "maximumAllowableTestPressure": 13,
            "pneumaticYieldLimitPressure": 12.5,
            "pressureSteps": steps,
        },
    )
    too_high = call(
        "check_pressure_test_parameters",
        {
            "method": "gas",
            "designPressure": 10,
            "testPressure": 13,
            "holdMinutes": 10,
            "testResult": "passed",
            "maximumAllowableTestPressure": 14,
            "pneumaticYieldLimitPressure": 12.5,
            "pressureSteps": [{"pressure": 6.5, "holdMinutes": 3}, {"pressure": 13, "holdMinutes": 3}],
        },
    )

    assert output["result"] == "passed"
    assert too_high["result"] == "failed"


@pytest.mark.parametrize("name", sorted(BUSINESS_TOOL_NAMES - {
    "check_required",
    "check_scope_coverage",
    "check_cross_document_match",
    "check_signature_completeness",
    "check_numeric_range",
    "check_conditional_requirement",
    "check_sampling_requirement",
    "check_document_set_completeness",
    "check_standard_version_active",
    "check_traceability",
    "check_ndt_personnel_coverage",
    "check_wps_pqr_coverage",
    "evaluate_installation_license_scope",
    "evaluate_ndt_organization_scope",
    "evaluate_design_approval_level",
    "evaluate_rt_film",
    "evaluate_pressure_test",
    "evaluate_valve_test",
}))
def test_remaining_domain_tools_execute_versioned_rules(name: str) -> None:
    output = call(
        name,
        {
            "profile": "test-profile-v1",
            "facts": {"document": {"id": "D-1"}},
            "requiredFields": ["document.id"],
            "ruleChecks": [{"code": "document_present", "operator": "present", "actual": "D-1"}],
        },
    )

    assert output["result"] == "passed"
    assert output["ruleVersion"] == "test-profile-v1"
