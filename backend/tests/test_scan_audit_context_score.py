from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.scan_audit_context_score import build_context_score


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_drawing_package_context_promotes_continuation_sheet_without_masking_pdf_gaps(tmp_path: Path) -> None:
    report_dir = tmp_path
    samples = [
        {
            "fileName": "IMG_0001_1800.png",
            "inputType": "png",
            "requestedProfileId": "piping_characteristic_list_v1",
            "profileId": "engineering_drawing_list_v1",
            "success": True,
            "qualityStatus": "auto_usable",
            "missingFields": [],
            "missingTables": [],
            "missingExpectedSealTypes": [],
            "qualityReasons": [],
            "fieldBboxCoverage": 1.0,
            "sealCount": 1,
            "keyFields": {"drawing_no": "QX201903S-13-Y-00"},
        },
        {
            "fileName": "IMG_0002_1800.png",
            "inputType": "png",
            "requestedProfileId": "piping_characteristic_list_v1",
            "profileId": "drawing_material_list_v1",
            "success": True,
            "qualityStatus": "needs_human_review",
            "missingFields": ["project_name", "design_phase", "blue_seal_expiry"],
            "missingTables": [],
            "missingExpectedSealTypes": ["design_license_seal", "drawing_approval_seal"],
            "qualityReasons": ["REQUIRED_FIELD_MISSING", "SEAL_NOT_FOUND"],
            "fieldBboxCoverage": 1.0,
            "sealCount": 0,
            "keyFields": {"drawing_no": "QX201903S-13-Y-09"},
        },
        {
            "fileName": "IMG_0003_1800.png",
            "inputType": "png",
            "requestedProfileId": "piping_characteristic_list_v1",
            "profileId": "site_layout_drawing_v1",
            "success": True,
            "qualityStatus": "needs_human_review",
            "missingFields": ["company_name", "project_name", "document_title", "drawing_no", "design_phase", "blue_seal_expiry"],
            "missingTables": [],
            "missingExpectedSealTypes": ["design_license_seal", "drawing_approval_seal"],
            "qualityReasons": ["REQUIRED_FIELD_MISSING", "SEAL_NOT_FOUND"],
            "fieldBboxCoverage": 1.0,
            "sealCount": 0,
            "keyFields": {},
        },
        {
            "fileName": "IMG_0004_1800.png",
            "inputType": "png",
            "requestedProfileId": "piping_characteristic_list_v1",
            "profileId": "strength_calculation_v1",
            "success": True,
            "qualityStatus": "auto_usable",
            "missingFields": [],
            "missingTables": [],
            "missingExpectedSealTypes": [],
            "qualityReasons": [],
            "fieldBboxCoverage": 1.0,
            "sealCount": 1,
            "keyFields": {"drawing_no": "A244010070"},
        },
        {
            "fileName": "20260623104828.pdf",
            "inputType": "pdf",
            "requestedProfileId": "quality_certificate_v1",
            "profileId": "quality_certificate_v1",
            "success": True,
            "qualityStatus": "needs_human_review",
            "missingFields": ["certificate_no"],
            "missingTables": ["mechanical_property_table"],
            "missingExpectedSealTypes": ["company_official_seal", "quality_seal"],
            "qualityReasons": ["REQUIRED_FIELD_MISSING", "SEAL_NOT_FOUND", "REQUIRED_TABLE_MISSING"],
            "fieldBboxCoverage": 1.0,
            "sealCount": 0,
            "keyFields": {},
            "tableSchemas": ["material_chemical_composition_table"],
        },
        {
            "fileName": "20260623104829.pdf",
            "inputType": "pdf",
            "requestedProfileId": "welding_procedure_qualification_v1",
            "profileId": "welding_procedure_qualification_v1",
            "success": True,
            "qualityStatus": "needs_human_review",
            "missingFields": [],
            "missingTables": ["welding_procedure_qualification_table"],
            "missingExpectedSealTypes": [],
            "qualityReasons": ["REQUIRED_TABLE_MISSING"],
            "fieldBboxCoverage": 1.0,
            "sealCount": 0,
            "pageCount": 4,
            "keyFields": {"report_no": "PQR-2021-001"},
            "tableSchemas": [],
        },
    ]
    write_json(report_dir / "scan-full-ocr-summary-v2.json", {"samples": samples})
    write_json(report_dir / "scan-composite-score-v2.json", {"score": 88.75})
    write_json(
        report_dir / "scan-full-ocr-v2-IMG_0001_1800.json",
        {
            "fields": [
                field("company_name", "广东星燃石化设计院有限公司", [10, 10, 100, 20]),
                field("project_name", "二期装车站新增两套卸车系统项目", [10, 30, 100, 40]),
                field("design_phase", "施工图", [10, 50, 100, 60]),
                field("blue_seal_expiry", "2024年6月21日", [10, 70, 100, 80]),
            ],
            "seals": [
                {
                    "sealType": "drawing_approval_seal",
                    "sealName": "广东省建设工程勘察设计出图专用章",
                    "bbox": [500, 500, 700, 700],
                    "pageNo": 1,
                    "canSatisfyRequiredSeal": True,
                    "sealEvidenceLevel": "visual_plus_seal_crop_ocr",
                }
            ],
        },
    )
    write_json(report_dir / "scan-full-ocr-v2-IMG_0002_1800.json", {"fields": [], "seals": []})
    write_json(report_dir / "scan-full-ocr-v2-IMG_0003_1800.json", {"fields": [], "seals": []})
    write_json(report_dir / "scan-full-ocr-v2-IMG_0004_1800.json", {"fields": [], "seals": []})
    write_json(report_dir / "scan-full-ocr-v2-20260623104828.json", {"fields": [], "seals": []})

    payload = build_context_score(report_dir)
    by_name = {item["fileName"]: item for item in payload["summary"]["samples"]}

    assert by_name["IMG_0002_1800.png"]["contextualQualityStatus"] == "auto_usable_with_package_context"
    assert by_name["IMG_0002_1800.png"]["contextualMissingExpectedSealTypes"] == []
    assert by_name["IMG_0003_1800.png"]["contextualQualityStatus"] == "needs_human_review"
    assert by_name["IMG_0003_1800.png"]["contextualMissingFields"] == ["document_title", "drawing_no"]
    assert by_name["IMG_0004_1800.png"]["contextualQualityStatus"] == "needs_human_review"
    assert by_name["20260623104828.pdf"]["contextualMissingExpectedSealTypes"] == [
        "company_official_seal",
        "quality_seal",
    ]
    assert payload["composite"]["sourceStrictScore"] == 88.75
    assert payload["composite"]["metrics"]["packageSealEvidenceCount"] == 1
    pipeline_accuracy = payload["composite"]["pipelineAccuracy"]
    assert pipeline_accuracy["schemaVersion"] == "document-llm-standard-result-accuracy-v1"
    assert pipeline_accuracy["overallPercent"] == payload["composite"]["score"]
    assert [item["stage"] for item in pipeline_accuracy["stages"]] == [
        "documentEvidence",
        "llmReview",
        "industryStandards",
        "auditResult",
    ]
    assert pipeline_accuracy["stages"][0]["basis"] == "ocrFieldExtraction + tableSealBboxEvidence"
    finding_codes = {item["code"] for item in payload["findings"]["findings"]}
    assert "B-DWG-NO" in finding_codes


def test_v5_flags_production_evidence_gaps_without_running_ocr(tmp_path: Path) -> None:
    report_dir = tmp_path
    samples = [
        {
            "fileName": "IMG_6514_1800.png",
            "inputType": "png",
            "requestedProfileId": "engineering_drawing_list_v1",
            "profileId": "engineering_drawing_list_v1",
            "success": True,
            "qualityStatus": "auto_usable",
            "missingFields": [],
            "missingTables": [],
            "missingExpectedSealTypes": [],
            "qualityReasons": [],
            "fieldBboxCoverage": 1.0,
            "sealCount": 1,
            "keyFields": {"drawing_no": "QX201903S-13-Y-00"},
        },
        {
            "fileName": "IMG_6515_1800.png",
            "inputType": "png",
            "requestedProfileId": "drawing_material_list_v1",
            "profileId": "drawing_material_list_v1",
            "success": True,
            "qualityStatus": "needs_human_review",
            "missingFields": ["project_name", "design_phase", "blue_seal_expiry"],
            "missingTables": [],
            "missingExpectedSealTypes": ["design_license_seal"],
            "qualityReasons": ["REQUIRED_FIELD_MISSING", "SEAL_NOT_FOUND"],
            "fieldBboxCoverage": 1.0,
            "sealCount": 0,
            "keyFields": {"drawing_no": "QX201903S-13-Y-02"},
        },
        {
            "fileName": "IMG_6509_1800.png",
            "inputType": "png",
            "requestedProfileId": "piping_characteristic_list_v1",
            "profileId": "piping_characteristic_list_v1",
            "success": True,
            "qualityStatus": "auto_usable",
            "missingFields": [],
            "missingTables": [],
            "missingExpectedSealTypes": [],
            "qualityReasons": [],
            "fieldBboxCoverage": 1.0,
            "sealCount": 1,
            "keyFields": {"drawing_no": "QX201903S-13-Y-01"},
        },
        {
            "fileName": "20260623104828.pdf",
            "inputType": "pdf",
            "requestedProfileId": "quality_certificate_v1",
            "profileId": "quality_certificate_v1",
            "success": True,
            "qualityStatus": "needs_human_review",
            "missingFields": [],
            "missingTables": ["mechanical_property_table"],
            "missingExpectedSealTypes": ["quality_seal"],
            "qualityReasons": ["REQUIRED_TABLE_MISSING", "SEAL_NOT_FOUND"],
            "fieldBboxCoverage": 1.0,
            "sealCount": 0,
            "pageCount": 3,
            "keyFields": {},
            "tableSchemas": ["material_chemical_composition_table"],
        },
        {
            "fileName": "20260623104829.pdf",
            "inputType": "pdf",
            "requestedProfileId": "welding_procedure_qualification_v1",
            "profileId": "welding_procedure_qualification_v1",
            "success": True,
            "qualityStatus": "needs_human_review",
            "missingFields": [],
            "missingTables": ["welding_procedure_qualification_table"],
            "missingExpectedSealTypes": [],
            "qualityReasons": ["REQUIRED_TABLE_MISSING"],
            "fieldBboxCoverage": 1.0,
            "sealCount": 0,
            "pageCount": 4,
            "keyFields": {"report_no": "PQR-2021-001"},
            "tableSchemas": [],
        },
    ]
    write_json(report_dir / "scan-full-ocr-summary-v2.json", {"samples": samples})
    write_json(report_dir / "scan-composite-score-v2.json", {"score": 89})
    write_json(
        report_dir / "scan-full-ocr-v2-IMG_6514_1800.json",
        {
            "metadata": {
                "drawingListRows": [
                    {"drawingNo": "QX201903S-13-Y-00", "drawingName": "工艺图纸目录", "bbox": [1, 1, 20, 20]},
                    {"drawingNo": "QX201903S-13-Y-01", "drawingName": "管道特性表", "bbox": [1, 21, 20, 40]},
                ]
            },
            "fields": [
                field("company_name", "广东星燃石化设计院有限公司", [10, 10, 100, 20]),
                field("project_name", "二期装车站新增两套卸车系统项目", [10, 30, 100, 40]),
                field("design_phase", "施工图", [10, 50, 100, 60]),
                field("blue_seal_expiry", "2024年6月21日", [10, 70, 100, 80]),
                field("drawing_no", "QX201903S-13-Y-00", [10, 90, 100, 100]),
            ],
            "seals": [
                {
                    "sealType": "drawing_approval_seal",
                    "sealName": "广东省建设工程勘察设计出图专用章",
                    "bbox": [500, 500, 700, 700],
                    "pageNo": 1,
                    "canSatisfyRequiredSeal": True,
                    "sealEvidenceLevel": "visual_plus_seal_crop_ocr",
                    "fields": [{"fieldCode": "blue_seal_expiry", "fieldValue": "2024年6月21日", "sourcePriority": "crop_ocr"}],
                }
            ],
        },
    )
    write_json(
        report_dir / "scan-full-ocr-v2-IMG_6515_1800.json",
        {"fields": [field("drawing_no", "QX201903S-13-Y-02", [1, 1, 20, 20])], "seals": []},
    )
    write_json(
        report_dir / "scan-full-ocr-v2-IMG_6509_1800.json",
        {
            "fields": [
                field("pressure_pipe_level", "GC2", [1, 1, 20, 20]),
                field("weld_detection_method", "RT", [21, 1, 30, 20]),
                field("weld_detection_ratio", "10%", [31, 1, 42, 20]),
                field("weld_acceptance_level", "III", [43, 1, 52, 20]),
                {"fieldCode": "weld_tech_level", "fieldName": "焊缝检测技术等级", "fieldValue": "AB"},
            ],
            "tables": [
                {
                    "businessSchema": "piping_characteristic_table_v1",
                    "normalizedRows": [{"pipeNo": "PL8301", "weldDetectionMethod": "RT", "weldDetectionScale": "10%"}],
                    "cells": [{"text": "RT", "row": 1, "col": 1}],
                }
            ],
            "seals": [
                {
                    "sealType": "drawing_approval_seal",
                    "bbox": [100, 100, 180, 180],
                    "canSatisfyRequiredSeal": True,
                    "sealEvidenceLevel": "fragment_roi_text",
                }
            ],
        },
    )
    write_json(
        report_dir / "scan-full-ocr-v2-20260623104828.json",
        {
            "metadata": {"pageCoverageMode": "first_page"},
            "fragments": [{"text": "质量证明书 化学成分 C Si Mn", "pageNo": 1, "bbox": [1, 1, 50, 20]}],
            "tables": [
                {
                    "businessSchema": "material_chemical_composition_table",
                    "sourceEngine": "heuristic_table_from_ocr_fragments",
                    "qualityFlags": ["quality_certificate_chemical_summary_from_fragments"],
                }
            ],
            "seals": [],
        },
    )
    write_json(
        report_dir / "scan-full-ocr-v2-20260623104829.json",
        {
            "metadata": {"pageCoverageMode": "first_page"},
            "fragments": [{"text": "承压设备焊接工艺评定报告 PQR-2021-001", "pageNo": 1, "bbox": [1, 1, 80, 20]}],
            "tables": [],
            "seals": [],
        },
    )

    payload = build_context_score(report_dir)
    metrics = payload["composite"]["metrics"]

    assert payload["composite"]["schemaVersion"] == "scan-composite-score-v5"
    assert metrics["drawingPackageConsistency"]["actualNotInDirectory"] == ["QX201903S-13-Y-02"]
    assert metrics["pdfDeepScan"]["deepScanReadyRate"] == 0.0
    assert metrics["pdfDeepScan"]["missingRequiredTables"]["20260623104829.pdf"] == [
        "welding_procedure_qualification_table"
    ]
    assert metrics["pipingEvidence"]["missingBboxFields"] == ["weld_tech_level"]
    assert metrics["sealCropEvidence"]["sampleWithCropEvidenceRate"] < 1
    finding_codes = {item["code"] for item in payload["findings"]["findings"]}
    assert {"B-DWG-COVERAGE", "B-PDF-DEEP-SCAN", "B-SEAL-CROP", "B-004"}.issubset(finding_codes)
    assert payload["composite"]["score"] < 96


def field(field_code: str, value: str, bbox: list[int]) -> dict[str, object]:
    return {
        "fieldCode": field_code,
        "fieldName": field_code,
        "fieldValue": value,
        "pageNo": 1,
        "bbox": bbox,
        "confidence": 0.98,
        "sourceEngine": "paddle_ocr_subprocess",
    }
