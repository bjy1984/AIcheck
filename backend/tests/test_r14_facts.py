from __future__ import annotations

from libs.ocr.profiles import profile_for
from libs.ocr_accuracy_pipeline import infer_preliminary_profile_id
from libs.review_orchestrator.execution import (
    ALLOWED_AGENT_TOOLS,  # noqa: F401 - establishes runtime import order
)
from libs.review_orchestrator.r14_facts import build_r14_business_facts


def test_r14_fact_builder_links_design_pipeline_factory_and_special_reports() -> None:
    state = {
        "versions": [
            {"id": "V-MAT", "documentId": "D-MAT", "fileName": "综合材料表.pdf"},
            {"id": "V-PIPE", "documentId": "D-PIPE", "fileName": "管道特性表.pdf"},
            {"id": "V-FACTORY", "documentId": "D-FACTORY", "fileName": "螺栓出厂检验报告.pdf"},
            {"id": "V-HARD", "documentId": "D-HARD", "fileName": "螺栓硬度检测报告.pdf"},
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
                        "tableId": "T-MAT",
                        "title": "管道组成件材料表",
                        "businessSchemas": ["material_component_table"],
                        "pageNo": 2,
                        "confidence": 0.97,
                        "normalizedRows": [
                            {
                                "lineNo": "L-100",
                                "componentType": "高强螺栓",
                                "specification": "M24",
                                "grade": "8.8",
                                "material": "35CrMo",
                                "batchNo": "B-14",
                                "pressureClass": "PN16",
                                "requiredInspectionItems": "光谱、硬度",
                                "confidence": 0.97,
                            }
                        ],
                    }
                ],
                "fields": [],
                "fragments": [],
            },
            {
                "documentId": "D-PIPE",
                "documentVersionId": "V-PIPE",
                "profileId": "piping_characteristic_list_v1",
                "documentType": "piping_characteristic_list",
                "tables": [
                    {
                        "tableId": "T-PIPE",
                        "title": "管道特性表",
                        "businessSchemas": ["pipeline_characteristic_table"],
                        "pageNo": 3,
                        "confidence": 0.96,
                        "normalizedRows": [
                            {"lineNo": "L-100", "designPressureMPa": 1.6, "pressureClass": "PN16", "confidence": 0.96}
                        ],
                    }
                ],
                "fields": [],
                "fragments": [],
            },
            {
                "documentId": "D-FACTORY",
                "documentVersionId": "V-FACTORY",
                "profileId": "factory_inspection_report_v1",
                "documentType": "factory_inspection_report",
                "tables": [],
                "fields": [
                    _field("report_no", "FR-14"),
                    _field("product_name", "高强螺栓"),
                    _field("line_no", "L-100"),
                    _field("specification", "M24"),
                    _field("component_grade", "8.8"),
                    _field("material_grade", "35CrMo"),
                    _field("batch_no", "B-14"),
                    _field("pressure_class", "PN16"),
                    _field("conclusion", "合格"),
                ],
                "fragments": [],
            },
            {
                "documentId": "D-HARD",
                "documentVersionId": "V-HARD",
                "profileId": "material_retest_report_v1",
                "documentType": "material_retest_report",
                "tables": [],
                "fields": [
                    _field("report_no", "HR-14"),
                    _field("report_type", "硬度检测"),
                    _field("product_name", "高强螺栓"),
                    _field("specification", "M24"),
                    _field("batch_no", "B-14"),
                    _field("test_items", "布氏硬度"),
                    _field("conclusion", "合格"),
                ],
                "fragments": [],
            },
        ],
    }
    review_run = {
        "nodeId": 14,
        "inputDocumentVersionIds": ["V-MAT", "V-PIPE", "V-FACTORY", "V-HARD"],
    }

    facts = build_r14_business_facts(state, review_run)

    assert facts["r14"]["designItems"][0]["lineNo"] == "L-100"
    assert facts["r14"]["designItems"][0]["grade"] == "8.8"
    assert facts["r14"]["pipelineCharacteristics"][0]["designPressureMPa"] == 1.6
    assert facts["r14"]["factoryInspectionReports"][0]["reportNo"] == "FR-14"
    assert facts["r14"]["factoryInspectionReports"][0]["grade"] == "8.8"
    assert facts["r14"]["specialInspectionReports"][0]["reportType"] == "hardness_test"
    assert len(facts["judgment"]["claimedFacts"]) == 4
    assert len(facts["judgment"]["evidenceRefs"]) == 4


def test_r14_ocr_profiles_are_routable() -> None:
    factory = profile_for("factory_inspection_report")
    retest = profile_for("material_retest_report")

    assert factory["profileId"] == "factory_inspection_report_v1"
    assert "component_grade" in factory["structuredExtraction"]["fields"]
    assert "pressure_class" in factory["structuredExtraction"]["fields"]
    assert retest["profileId"] == "material_retest_report_v1"
    assert "report_type" in retest["structuredExtraction"]["fields"]
    assert "test_pressure_mpa" in retest["structuredExtraction"]["fields"]
    assert infer_preliminary_profile_id("某批螺栓出厂检验报告.pdf", None, None) == "factory_inspection_report_v1"
    assert infer_preliminary_profile_id("某批螺栓硬度检测报告.pdf", None, None) == "material_retest_report_v1"


def _field(code: str, value: object) -> dict:
    return {
        "fieldCode": code,
        "fieldValue": value,
        "pageNo": 1,
        "bbox": [10, 10, 100, 30],
        "confidence": 0.96,
    }
