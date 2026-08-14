from __future__ import annotations

from libs.ocr.profiles import profile_for
from libs.ocr_accuracy_pipeline import infer_preliminary_profile_id
from libs.review_orchestrator.execution import (
    ALLOWED_AGENT_TOOLS,  # noqa: F401 - establishes runtime import order
)
from libs.review_orchestrator.r15_facts import build_r15_business_facts


def test_r15_fact_builder_extracts_foreign_items_certificates_and_inspection_route() -> None:
    state = {
        "versions": [
            {"id": "V-MAT", "documentId": "D-MAT", "fileName": "境外制造元件清单.pdf"},
            {"id": "V-LIC", "documentId": "D-LIC", "fileName": "制造许可证.pdf"},
            {"id": "V-TR", "documentId": "D-TR", "fileName": "阀门型式试验报告.pdf"},
            {"id": "V-ARR", "documentId": "D-ARR", "fileName": "境外阀门到岸检验记录.pdf"},
        ],
        "documents": [],
        "ocr_parse_results": [
            {
                "documentId": "D-MAT",
                "documentVersionId": "V-MAT",
                "profileId": "comprehensive_material_list_v1",
                "documentType": "comprehensive_material_list",
                "tables": [
                    {
                        "tableId": "T-R15",
                        "title": "境外制造压力管道元件清单",
                        "businessSchemas": ["material_component_table"],
                        "pageNo": 2,
                        "confidence": 0.97,
                        "normalizedRows": [
                            {
                                "componentType": "金属阀门",
                                "manufacturerName": "ACME Valve GmbH",
                                "manufacturingCountry": "Germany",
                                "specification": "DN100 PN40",
                                "nominalDiameterMM": 100,
                                "nominalPressureMPa": 4,
                                "requiresManufacturingLicense": True,
                                "requiresTypeTest": True,
                                "requiresManufacturingSupervision": True,
                                "manufacturingSupervisionCompletedOverseas": False,
                                "shippedWithBoilerOrPressureVessel": False,
                                "confidence": 0.97,
                            }
                        ],
                    }
                ],
                "fields": [],
                "fragments": [],
            },
            {
                "documentId": "D-LIC",
                "documentVersionId": "V-LIC",
                "profileId": "qualification_certificate_v1",
                "documentType": "manufacturing_license",
                "tables": [],
                "fields": [
                    _field("certificate_no", "TS2710X001"),
                    _field("organization_name", "ACME Valve GmbH"),
                    _field("license_scope", "压力管道阀门制造"),
                    _field("valid_until", "2030-12-31"),
                ],
                "fragments": [_fragment("特种设备生产许可证 压力管道阀门制造", 1)],
            },
            {
                "documentId": "D-TR",
                "documentVersionId": "V-TR",
                "profileId": "type_test_report_v1",
                "documentType": "type_test_report",
                "tables": [],
                "fields": [
                    _field("report_no", "TR-R15"),
                    _field("product_name", "金属阀门"),
                    _field("manufacturer", "ACME Valve GmbH"),
                    _field("test_organization", "型式试验机构"),
                    _field("specification_scope", "DN50-DN200 PN10-PN64"),
                    _field("conclusion", "合格"),
                ],
                "fragments": [],
            },
            {
                "documentId": "D-ARR",
                "documentVersionId": "V-ARR",
                "profileId": "foreign_component_inspection_record_v1",
                "documentType": "foreign_component_inspection_record",
                "tables": [],
                "fields": [
                    _field("record_no", "ARR-R15"),
                    _field("product_name", "金属阀门"),
                    _field("manufacturer", "ACME Valve GmbH"),
                    _field("inspection_route", "到岸检验"),
                    _field("inspection_organization", "特种设备检验院"),
                    _field("conclusion", "合格"),
                ],
                "fragments": [],
            },
        ],
    }
    review_run = {
        "nodeId": 15,
        "inputDocumentVersionIds": ["V-MAT", "V-LIC", "V-TR", "V-ARR"],
        "manualRegistryVerifications": [
            {
                "verifications": [
                    {
                        "candidateId": "placeholder",
                        "outcome": "verified_match",
                        "registryStatus": "active",
                    }
                ]
            }
        ],
    }

    facts = build_r15_business_facts(state, review_run)

    r15 = facts["r15"]
    assert r15["designItems"][0]["manufacturingCountry"] == "Germany"
    assert r15["designItems"][0]["manufacturingSupervisionCompletedOverseas"] is False
    assert r15["manufacturingLicenseCandidates"][0]["candidateId"].startswith("R15LIC-")
    assert r15["manufacturingLicenseCandidates"][0]["organizationName"] == "ACME Valve GmbH"
    assert r15["typeTestReports"][0]["reportNo"] == "TR-R15"
    assert r15["arrivalInspectionRecords"][0]["recordNo"] == "ARR-R15"
    assert r15["completeMachineInspectionRecords"] == []
    assert len(facts["judgment"]["claimedFacts"]) == 4
    assert len(facts["judgment"]["evidenceRefs"]) == 4


def test_r15_arrival_inspection_ocr_profile_is_routable() -> None:
    profile = profile_for("foreign_component_inspection_record")

    assert profile["profileId"] == "foreign_component_inspection_record_v1"
    assert "inspection_route" in profile["structuredExtraction"]["fields"]
    assert "inspection_organization" in profile["structuredExtraction"]["fields"]
    assert (
        infer_preliminary_profile_id("某境外阀门到岸检验记录.pdf", None, None)
        == "foreign_component_inspection_record_v1"
    )


def _field(code: str, value: object) -> dict:
    return {
        "fieldCode": code,
        "fieldValue": value,
        "pageNo": 1,
        "bbox": [10, 10, 100, 30],
        "confidence": 0.96,
    }


def _fragment(text: str, page_no: int) -> dict:
    return {
        "text": text,
        "pageNo": page_no,
        "bbox": [10, 40, 300, 70],
        "confidence": 0.96,
    }
