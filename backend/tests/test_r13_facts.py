from __future__ import annotations

from apps.ocr_service.profiles import profile_for
from libs.ocr_accuracy_pipeline import infer_preliminary_profile_id
from libs.review_orchestrator.execution import ALLOWED_AGENT_TOOLS  # noqa: F401 - establishes runtime import order
from libs.review_orchestrator.r13_facts import build_r13_business_facts


def test_r13_fact_builder_extracts_design_items_certificates_reports_and_grounding() -> None:
    state = {
        "versions": [
            {"id": "V-DESIGN", "documentId": "D-DESIGN", "fileName": "综合材料表.pdf"},
            {"id": "V-SC", "documentId": "D-SC", "fileName": "制造监督检验证书.pdf"},
            {"id": "V-TR", "documentId": "D-TR", "fileName": "型式试验报告.pdf"},
        ],
        "documents": [],
        "ocr_parse_results": [
            {
                "documentId": "D-DESIGN",
                "documentVersionId": "V-DESIGN",
                "profileId": "comprehensive_material_list_v1",
                "documentType": "comprehensive_material_list",
                "tables": [
                    {
                        "tableId": "T-MATERIAL",
                        "title": "压力管道元件材料表",
                        "businessSchemas": ["material_component_table"],
                        "pageNo": 3,
                        "confidence": 0.96,
                        "normalizedRows": [
                            {
                                "componentType": "埋弧焊钢管",
                                "manufacturerName": "甲制造有限公司",
                                "specification": "DN500 PN10",
                                "material": "L360",
                                "manufacturingProcess": "埋弧焊",
                                "nominalDiameterMM": 500,
                                "nominalPressureMPa": 10,
                                "batchNo": "B-001",
                                "confidence": 0.96,
                            }
                        ],
                    }
                ],
                "fields": [],
                "fragments": [],
            },
            {
                "documentId": "D-SC",
                "documentVersionId": "V-SC",
                "profileId": "manufacturing_supervision_certificate_v1",
                "documentType": "manufacturing_supervision_certificate",
                "tables": [],
                "fields": [
                    _field("certificate_no", "SC-001", 1),
                    _field("product_name", "埋弧焊钢管", 1),
                    _field("manufacturer", "甲制造有限公司", 1),
                    _field("batch_no", "B-001", 1),
                    _field("conclusion", "合格", 1),
                ],
                "fragments": [],
            },
            {
                "documentId": "D-TR",
                "documentVersionId": "V-TR",
                "profileId": "type_test_report_v1",
                "documentType": "type_test_report",
                "tables": [],
                "fields": [
                    _field("report_no", "TR-001", 1),
                    _field("product_name", "埋弧焊钢管", 1),
                    _field("manufacturer", "甲制造有限公司", 1),
                    _field("test_organization", "特种设备检测院", 1),
                    _field("material", "L360", 2),
                    _field("manufacturing_process", "埋弧焊", 2),
                    _field("nominal_diameter_min_mm", 100, 2),
                    _field("nominal_diameter_max_mm", 800, 2),
                    _field("nominal_pressure_min_mpa", 1, 2),
                    _field("nominal_pressure_max_mpa", 16, 2),
                    _field("conclusion", "合格", 2),
                ],
                "fragments": [],
            },
        ],
    }
    review_run = {
        "nodeId": 13,
        "inputDocumentVersionIds": ["V-DESIGN", "V-SC", "V-TR"],
    }

    facts = build_r13_business_facts(state, review_run)

    assert len(facts["r13"]["designItems"]) == 1
    assert facts["r13"]["designItems"][0]["batchNo"] == "B-001"
    assert facts["r13"]["supervisionCertificates"][0]["certificateNo"] == "SC-001"
    assert facts["r13"]["supervisionCertificates"][0]["batchNo"] == "B-001"
    assert facts["r13"]["typeTestReports"][0]["reportNo"] == "TR-001"
    assert facts["r13"]["typeTestReports"][0]["nominalDiameterMaxMM"] == 800
    assert len(facts["judgment"]["claimedFacts"]) == 3
    assert len(facts["judgment"]["evidenceRefs"]) == 3
    assert all(item["evidenceRefIds"] for item in facts["judgment"]["claimedFacts"])


def test_r13_ocr_profiles_are_routable_and_extract_coverage_fields() -> None:
    supervision = profile_for("manufacturing_supervision_certificate")
    type_test = profile_for("type_test_report")

    assert supervision["profileId"] == "manufacturing_supervision_certificate_v1"
    assert "batch_no" in supervision["structuredExtraction"]["fields"]
    assert "serial_no" in supervision["structuredExtraction"]["fields"]
    assert type_test["profileId"] == "type_test_report_v1"
    assert "specification_scope" in type_test["structuredExtraction"]["fields"]
    assert "nominal_pressure_max_mpa" in type_test["structuredExtraction"]["fields"]
    assert infer_preliminary_profile_id("某元件制造监督检验证书.pdf", None, None) == "manufacturing_supervision_certificate_v1"
    assert infer_preliminary_profile_id("阀门型式试验报告.pdf", None, None) == "type_test_report_v1"


def _field(code: str, value: object, page_no: int) -> dict:
    return {
        "fieldCode": code,
        "fieldValue": value,
        "pageNo": page_no,
        "bbox": [10, 10, 100, 30],
        "confidence": 0.96,
    }
