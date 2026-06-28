from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_PROFILE_ID = "generic_document_v1"


OCR_PROFILES: dict[str, dict[str, Any]] = {
    DEFAULT_PROFILE_ID: {
        "profileId": DEFAULT_PROFILE_ID,
        "documentType": "generic_document",
        "engines": {
            "text": "pymupdf_text_layer",
            "ocr": "paddle_ocr_v6",
            "layout": "pp_structure_v3",
            "seal": "paddlex_seal_recognition",
            "fallback": "paddleocr_vl_1_6",
            "electronic": "docling_local",
        },
        "requiredFields": [],
        "requiredTables": [],
        "sealRules": {"required": False, "expectedSealTypes": []},
        "qualityRules": {
            "minFieldConfidence": 0.75,
            "minTableStructureConfidence": 0.8,
        },
    },
    "quality_certificate_v1": {
        "profileId": "quality_certificate_v1",
        "documentType": "quality_certificate",
        "requiredFields": [
            "certificate_no",
            "manufacturer",
            "material_grade",
            "specification",
            "batch_no",
            "standard_no",
            "inspection_conclusion",
            "issue_date",
            "seal",
        ],
        "requiredTables": ["material_chemical_composition_table", "mechanical_property_table"],
        "sealRules": {"required": True, "expectedSealTypes": ["company_official_seal", "quality_seal"]},
    },
    "ndt_rt_report_v1": {
        "profileId": "ndt_rt_report_v1",
        "documentType": "ndt_report",
        "requiredFields": [
            "report_no",
            "project_name",
            "detection_method",
            "weld_no",
            "detection_date",
            "evaluation_level",
            "conclusion",
            "inspection_unit",
            "seal",
        ],
        "requiredTables": ["weld_detection_result_table"],
        "sealRules": {
            "required": True,
            "expectedSealTypes": ["inspection_testing_seal", "company_official_seal"],
        },
    },
    "ndt_ut_report_v1": {
        "profileId": "ndt_ut_report_v1",
        "documentType": "ndt_report",
        "requiredFields": [
            "report_no",
            "project_name",
            "detection_method",
            "weld_no",
            "detection_date",
            "evaluation_level",
            "conclusion",
            "inspection_unit",
            "seal",
        ],
        "requiredTables": ["weld_detection_result_table"],
        "sealRules": {
            "required": True,
            "expectedSealTypes": ["inspection_testing_seal", "company_official_seal"],
        },
    },
    "construction_record_v1": {
        "profileId": "construction_record_v1",
        "documentType": "construction_record",
        "requiredFields": ["record_no", "project_name", "construction_date", "responsible_person"],
        "requiredTables": ["construction_record_table"],
        "sealRules": {"required": False, "expectedSealTypes": []},
    },
    "welding_record_v1": {
        "profileId": "welding_record_v1",
        "documentType": "welding_record",
        "requiredFields": ["record_no", "weld_no", "welder_name", "welder_cert_no", "welding_date"],
        "requiredTables": ["welding_record_table"],
        "sealRules": {"required": False, "expectedSealTypes": []},
    },
    "qualification_certificate_v1": {
        "profileId": "qualification_certificate_v1",
        "documentType": "qualification_certificate",
        "requiredFields": [
            "certificate_no",
            "organization_name",
            "license_scope",
            "valid_until",
            "issuer",
            "issue_date",
            "seal",
        ],
        "requiredTables": [],
        "sealRules": {"required": True, "expectedSealTypes": ["issuer_seal", "company_official_seal"]},
    },
}


def profile_for(profile_id: str | None = None, document_type: str | None = None) -> dict[str, Any]:
    if profile_id and profile_id in OCR_PROFILES:
        return merged_profile(profile_id)
    if document_type:
        for candidate in OCR_PROFILES.values():
            if candidate.get("documentType") == document_type:
                return merged_profile(str(candidate["profileId"]))
    return merged_profile(DEFAULT_PROFILE_ID)


def merged_profile(profile_id: str) -> dict[str, Any]:
    base = deepcopy(OCR_PROFILES[DEFAULT_PROFILE_ID])
    if profile_id == DEFAULT_PROFILE_ID:
        return base
    override = deepcopy(OCR_PROFILES[profile_id])
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key].update(value)
        else:
            base[key] = value
    return base
