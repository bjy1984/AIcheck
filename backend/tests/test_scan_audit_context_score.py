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
    finding_codes = {item["code"] for item in payload["findings"]["findings"]}
    assert "B-DWG-NO" in finding_codes


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
