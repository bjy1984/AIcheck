from __future__ import annotations

from libs.ocr.profiles import profile_for, validate_profiles
from libs.review_orchestrator.r20_r23_facts import build_r23_business_facts
from libs.review_tools.r20_r23_tools import (
    classify_r20_new_material_applicability,
    evaluate_r20_new_material_procedure,
    evaluate_r21_mark_transfer,
    evaluate_r22_material_substitution,
    evaluate_r23_valve_sampling,
    evaluate_r23_valve_test_records,
    resolve_r23_valve_test_basis,
)


def test_r20_classifies_two_new_material_branches_and_non_new_material() -> None:
    output = classify_r20_new_material_applicability(
        {
            "designItems": [
                {"componentItemId": "N1", "newMaterialCategory": "unlisted_all"},
                {"componentItemId": "N2", "newMaterialCategory": "listed_dedicated_material_standard"},
                {"componentItemId": "N3", "listedInGBT20801": True},
            ]
        }
    )

    assert output["result"] == "passed"
    matrix = {item["componentItemId"]: item for item in output["newMaterialClassificationMatrix"]}
    assert matrix["N1"]["technicalReviewRequired"] is True
    assert matrix["N2"]["materialDataRequired"] is True
    assert matrix["N3"]["result"] == "not_applicable"


def test_r20_unlisted_all_requires_type_test_review_and_completed_approval() -> None:
    item = {
        "componentItemId": "N1",
        "newMaterialCategory": "unlisted_all",
        "materialGrade": "X-NEW",
        "productName": "安全阀",
        "nominalDiameterMM": 50,
        "nominalPressureMPa": 4,
    }
    type_test_reports = [
        {
            "reportNo": "TT-1",
            "testOrganization": "国家型式试验机构",
            "productName": "安全阀",
            "materialGrade": "X-NEW",
            "nominalDiameterMinMM": 10,
            "nominalDiameterMaxMM": 100,
            "nominalPressureMinMPa": 1,
            "nominalPressureMaxMPa": 10,
            "conclusion": "合格",
        }
    ]
    passed = evaluate_r20_new_material_procedure(
        {
            "designItems": [item],
            "typeTestReports": type_test_reports,
            "technicalReviewApprovals": [
                {
                    "materialGrade": "X-NEW",
                    "productName": "安全阀",
                    "technicalReviewPassed": True,
                    "approvalDocumentNo": "APP-1",
                    "approvalOrganization": "批准机关",
                    "approvalProcedureCompleted": True,
                }
            ],
        }
    )
    missing_approval = evaluate_r20_new_material_procedure(
        {
            "designItems": [item],
            "typeTestReports": type_test_reports,
            "technicalReviewApprovals": [{"technicalReviewPassed": True, "conclusion": "通过"}],
        }
    )

    assert passed["result"] == "passed"
    assert missing_approval["result"] == "evidence_insufficient"


def test_r20_dedicated_standard_branch_requires_material_data_but_not_technical_review() -> None:
    output = evaluate_r20_new_material_procedure(
        {
            "designItems": [
                {
                    "componentItemId": "N2",
                    "newMaterialCategory": "listed_dedicated_material_standard",
                    "materialGrade": "Y-NEW",
                    "productName": "管件",
                }
            ],
            "typeTestReports": [
                {
                    "reportNo": "TT-2",
                    "testOrganization": "型式试验机构",
                    "productName": "管件",
                    "materialGrade": "Y-NEW",
                    "conclusion": "合格",
                }
            ],
            "materialDataDocuments": [
                {
                    "materialGrade": "Y-NEW",
                    "productName": "管件",
                    "dataItems": [
                        "chemical_composition",
                        "tensile_properties",
                        "fatigue_data",
                        "fracture_toughness",
                        "scope_performance_parameters",
                    ],
                }
            ],
        }
    )

    assert output["result"] == "passed"


def test_r21_returns_not_applicable_without_transfer_and_checks_method_traceability() -> None:
    not_applicable = evaluate_r21_mark_transfer({"markTransferOccurred": False})
    passed = evaluate_r21_mark_transfer(
        {
            "markTransferOccurred": True,
            "transferRecords": [
                {
                    "recordId": "MT-1",
                    "originalMark": "H001-A",
                    "transferredMark": "H001-A-1",
                    "batchNo": "H001",
                    "materialGrade": "06Cr19Ni10",
                    "markMethod": "电化学蚀刻",
                    "inspector": "张三",
                    "conclusion": "合格",
                    "identityChainVerified": True,
                    "confusionControl": True,
                }
            ],
            "materialInventory": [{"materialGrade": "06Cr19Ni10", "batchNo": "H001", "specialMaterial": True}],
        }
    )
    prohibited = evaluate_r21_mark_transfer(
        {
            "markTransferOccurred": True,
            "transferRecords": [
                {
                    "originalMark": "L1",
                    "transferredMark": "L1-1",
                    "batchNo": "L1",
                    "materialGrade": "低温不锈钢",
                    "markMethod": "钢印",
                    "inspector": "李四",
                    "conclusion": "合格",
                    "identityChainVerified": True,
                    "confusionControl": True,
                }
            ],
        }
    )

    assert not_applicable["result"] == "not_applicable"
    assert passed["result"] == "passed"
    assert prohibited["result"] == "failed"


def test_r22_only_reviews_implemented_substitution_and_requires_original_design_org() -> None:
    proposal_only = evaluate_r22_material_substitution(
        {"substitutionRecords": [{"implemented": False, "originalMaterial": "A", "substituteMaterial": "B"}]}
    )
    passed = evaluate_r22_material_substitution(
        {
            "materialSubstitutionOccurred": True,
            "substitutionRecords": [
                {
                    "recordId": "S1",
                    "implemented": True,
                    "originalMaterial": "20#",
                    "substituteMaterial": "Q345",
                    "substitutionScope": "L-100",
                    "changeNo": "DC-1",
                    "originalDesignOrganization": "甲设计院",
                    "approvingOrganization": "甲设计院",
                    "writtenApprovalPresent": True,
                    "approvalDate": "2026-01-10",
                    "implementationDate": "2026-02-01",
                }
            ],
            "actualMaterialUsage": [{"materialGrade": "Q345", "scope": "L-100"}],
        }
    )
    wrong_org = evaluate_r22_material_substitution(
        {
            "materialSubstitutionOccurred": True,
            "substitutionRecords": [
                {
                    "implemented": True,
                    "originalMaterial": "20#",
                    "substituteMaterial": "Q345",
                    "substitutionScope": "L-100",
                    "changeNo": "DC-2",
                    "originalDesignOrganization": "甲设计院",
                    "approvingOrganization": "施工单位",
                    "writtenApprovalPresent": True,
                    "approvalDate": "2026-01-10",
                    "implementationDate": "2026-02-01",
                }
            ],
            "actualMaterialUsage": [{"materialGrade": "Q345", "scope": "L-100"}],
        }
    )

    assert proposal_only["result"] == "not_applicable"
    assert passed["result"] == "passed"
    assert wrong_org["result"] == "failed"


def test_r23_basis_priority_and_sampling_quantities() -> None:
    default = resolve_r23_valve_test_basis({"designAndContractBasisChecked": True})
    explicit = resolve_r23_valve_test_basis({"designStandardRefs": ["GB/T 26480-2011"]})
    conflict = resolve_r23_valve_test_basis(
        {"designStandardRefs": ["GB/T 26480-2011"], "contractStandardRefs": ["GB/T 13927-2022"]}
    )
    sampling = evaluate_r23_valve_sampling(
        {
            "testLots": [
                {"lotId": "G1", "pipelineGrade": "GC1", "lotSize": 4, "testedCount": 4},
                {"lotId": "G2", "pipelineGrade": "GC2", "lotSize": 21, "testedCount": 3},
                {"lotId": "G3", "pipelineGrade": "GC3", "lotSize": 20, "testedCount": 1},
            ]
        }
    )

    assert default["applicableStandardRefs"] == ["GB/T 13927-2022"]
    assert explicit["applicableStandardRefs"] == ["GB/T 26480-2011"]
    assert conflict["result"] == "evidence_insufficient"
    assert sampling["result"] == "passed"
    assert [item["requiredTestCount"] for item in sampling["valveSamplingMatrix"]] == [4, 3, 1]


def test_r23_fails_closed_without_13927_profile_and_passes_with_frozen_parameters() -> None:
    record = {
        "recordId": "VR-1",
        "valveNo": "V-1",
        "valveType": "球阀",
        "nominalDiameterMM": 80,
        "nominalPressure": "PN16",
        "constructionRecordId": "CR-1",
        "standardRef": "GB/T 13927-2022",
        "shellTest": {"medium": "水", "pressureMPa": 2.4, "holdSeconds": 60, "procedureSteps": ["加压", "检漏"], "result": "合格"},
        "sealTest": {"medium": "空气", "pressureMPa": 0.6, "holdSeconds": 60, "procedureSteps": ["加压", "检漏"], "result": "合格"},
        "conclusion": "合格",
    }
    construction_records = [
        {
            "recordId": "CR-1",
            "valveNo": "V-1",
            "valveType": "球阀",
            "nominalDiameterMM": 80,
            "nominalPressure": "PN16",
        }
    ]
    insufficient = evaluate_r23_valve_test_records(
        {"testRecords": [record], "constructionRecords": construction_records, "designAndContractBasisChecked": True}
    )
    passed = evaluate_r23_valve_test_records(
        {
            "testRecords": [record],
            "constructionRecords": construction_records,
            "designAndContractBasisChecked": True,
            "standardRequirementProfiles": {
                "GB/T 13927-2022": {
                    "shell": {"minimumPressureMPa": 2.4, "minimumHoldSeconds": 60, "allowedMedia": ["水"], "requiredProcedureSteps": ["加压", "检漏"]},
                    "seal": {"minimumPressureMPa": 0.6, "minimumHoldSeconds": 60, "allowedMedia": ["空气"], "requiredProcedureSteps": ["加压", "检漏"]},
                }
            },
        }
    )

    assert insufficient["result"] == "evidence_insufficient"
    assert passed["result"] == "passed"


def test_r23_resolves_verified_gbt26480_common_steel_valve_branch() -> None:
    output = evaluate_r23_valve_test_records(
        {
            "designStandardRefs": ["GB/T 26480-2011"],
            "testRecords": [
                {
                    "valveNo": "V-26480",
                    "valveType": "球阀",
                    "nominalDiameterMM": 80,
                    "nominalPressure": "PN16",
                    "valveBodyMaterialCategory": "钢制",
                    "maximumAllowableWorkingPressureMPa": 2,
                    "sealTestLevel": "低压密封",
                    "constructionRecordId": "CR-2",
                    "standardRef": "GB/T 26480-2011",
                    "shellTest": {
                        "medium": "清洁水",
                        "pressureMPa": 3,
                        "holdSeconds": 60,
                        "procedureSteps": ["两端封闭", "阀门部分开启", "体腔加压", "液体试验前排除空气"],
                        "result": "无泄漏，合格",
                    },
                    "sealTest": {
                        "medium": "空气",
                        "pressureMPa": 0.5,
                        "holdSeconds": 60,
                        "procedureSteps": ["密封面清洁无油迹", "在出口端检漏"],
                        "result": "无泄漏，合格",
                    },
                    "conclusion": "合格",
                }
            ],
            "constructionRecords": [
                {
                    "recordId": "CR-2",
                    "valveNo": "V-26480",
                    "valveType": "球阀",
                    "nominalDiameterMM": 80,
                    "nominalPressure": "PN16",
                }
            ],
        }
    )

    assert output["result"] == "passed"


def test_r23_requires_construction_record_link_and_matching_valve_identity() -> None:
    report = {
        "valveNo": "V-9",
        "valveType": "球阀",
        "nominalDiameterMM": 80,
        "nominalPressure": "PN16",
        "constructionRecordId": "CR-9",
        "standardRef": "GB/T 13927-2022",
        "shellTest": {"medium": "水", "pressureMPa": 2.4, "holdSeconds": 60, "procedureSteps": ["加压"], "result": "合格"},
        "sealTest": {"medium": "空气", "pressureMPa": 0.6, "holdSeconds": 60, "procedureSteps": ["检漏"], "result": "合格"},
        "conclusion": "合格",
    }
    profile = {
        "GB/T 13927-2022": {
            "shell": {"minimumPressureMPa": 2.4, "minimumHoldSeconds": 60, "allowedMedia": ["水"], "requiredProcedureSteps": ["加压"]},
            "seal": {"minimumPressureMPa": 0.6, "minimumHoldSeconds": 60, "allowedMedia": ["空气"], "requiredProcedureSteps": ["检漏"]},
        }
    }
    missing = evaluate_r23_valve_test_records(
        {"testRecords": [report], "standardRequirementProfiles": profile, "designAndContractBasisChecked": True}
    )
    mismatch = evaluate_r23_valve_test_records(
        {
            "testRecords": [report],
            "constructionRecords": [
                {"recordId": "CR-9", "valveNo": "V-9", "valveType": "球阀", "nominalDiameterMM": 100, "nominalPressure": "PN16"}
            ],
            "standardRequirementProfiles": profile,
            "designAndContractBasisChecked": True,
        }
    )

    assert missing["result"] == "evidence_insufficient"
    assert mismatch["result"] == "failed"


def test_r20_r23_ocr_profiles_are_registered_and_valid() -> None:
    assert validate_profiles() == []
    assert "approval_procedure_completed" in profile_for("technical_review_approval")["structuredExtraction"]["fields"]
    assert "original_mark" in profile_for("material_mark_transfer_record")["structuredExtraction"]["fields"]
    assert "original_design_organization" in profile_for("material_substitution_approval")["structuredExtraction"]["fields"]
    assert "shell_test_pressure_mpa" in profile_for("valve_test_report")["structuredExtraction"]["fields"]


def test_r23_fact_builder_maps_structured_ocr_into_nested_test_sections() -> None:
    state = {
        "ocr_parse_results": [
            {
                "documentVersionId": "DV-23",
                "profileId": "valve_test_report_v1",
                "fields": [],
                "tables": [
                    {
                        "normalizedRows": [
                            {
                                "report_no": "VT-1",
                                "valve_no": "V-1",
                                "valve_type": "球阀",
                                "nominal_diameter_mm": 80,
                                "nominal_pressure": "PN16",
                                "standard_ref": "GB/T 26480-2011",
                                "construction_record_id": "CR-1",
                                "shell_test_medium": "水",
                                "shell_test_pressure_mpa": 3,
                                "shell_hold_seconds": 60,
                                "shell_test_result": "合格",
                                "seal_test_medium": "空气",
                                "seal_test_pressure_mpa": 0.5,
                                "seal_hold_seconds": 60,
                                "seal_test_result": "合格",
                                "conclusion": "合格",
                            }
                        ]
                    }
                ],
            }
        ],
        "versions": [{"id": "DV-23", "fileName": "阀门耐压试验报告.pdf"}],
    }

    facts = build_r23_business_facts(state, {"inputDocumentVersionIds": ["DV-23"]})

    record = facts["r23"]["testRecords"][0]
    assert record["standardRef"] == "GB/T 26480-2011"
    assert record["shellTest"]["pressureMPa"] == 3
    assert record["sealTest"]["holdSeconds"] == 60
