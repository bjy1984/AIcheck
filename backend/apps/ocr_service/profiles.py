from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_PROFILE_ID = "generic_document_v1"
DEFAULT_VLM_FALLBACK_REASONS = [
    "REQUIRED_FIELD_MISSING",
    "FIELD_LOW_CONFIDENCE",
    "FIELD_FORMAT_INVALID",
    "FIELD_EVIDENCE_MISSING",
    "FIELD_VALUE_CONFLICT",
    "REQUIRED_TABLE_MISSING",
    "TABLE_STRUCTURE_LOW_CONFIDENCE",
    "TABLE_EVIDENCE_MISSING",
    "TABLE_ENGINE_CONFLICT",
    "SEAL_NOT_FOUND",
    "SEAL_TEXT_LOW_CONFIDENCE",
    "SEAL_EVIDENCE_MISSING",
    "EXPECTED_SEAL_TYPE_MISSING",
]


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
            "criticalConflictFields": [
                "batch_no",
                "certificate_no",
                "drawing_no",
                "issue_date",
                "project_name",
                "report_no",
                "valid_until",
            ],
        },
        "preprocessPolicy": {
            "renderDpi": 300,
            "maxLongSide": 2600,
            "textDetLimitSideLen": 2400,
            "ocr": {
                "useDocOrientationClassify": False,
                "useDocUnwarping": False,
                "useTextlineOrientation": False,
                "textDetLimitSideLen": 2400,
            },
            "variants": ["original", "gray_clahe"],
            "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": True, "enablePaddlexSeal": False},
            "fallback": {"enableVlmWhen": DEFAULT_VLM_FALLBACK_REASONS},
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
        "qualityRules": {
            "criticalConflictFields": [
                "certificate_no",
                "manufacturer",
                "material_grade",
                "batch_no",
                "standard_no",
                "issue_date",
            ],
        },
        "preprocessPolicy": {
            "renderDpi": 400,
            "maxLongSide": 2800,
            "textDetLimitSideLen": 3200,
            "ocr": {
                "useDocOrientationClassify": True,
                "useDocUnwarping": True,
                "useTextlineOrientation": True,
                "textDetLimitSideLen": 3200,
            },
            "variants": ["original", "deskew", "gray_clahe", "adaptive_threshold", "table_line_enhanced"],
            "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": True, "enablePaddlexSeal": True, "cropPaddingRatio": 0.18, "maxPages": 6},
        },
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
        "qualityRules": {
            "criticalConflictFields": [
                "report_no",
                "project_name",
                "weld_no",
                "detection_date",
                "evaluation_level",
                "conclusion",
            ],
        },
        "preprocessPolicy": {
            "renderDpi": 300,
            "maxLongSide": 2600,
            "textDetLimitSideLen": 3200,
            "ocr": {
                "useDocOrientationClassify": True,
                "useDocUnwarping": False,
                "useTextlineOrientation": True,
                "textDetLimitSideLen": 3200,
            },
            "variants": ["original", "deskew", "gray_clahe", "table_line_enhanced"],
            "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": True, "enablePaddlexSeal": True, "maxPages": 6},
            "fallback": {
                "enableVlmWhen": [
                    "TABLE_STRUCTURE_LOW_CONFIDENCE",
                    "REQUIRED_FIELD_MISSING",
                    "SEAL_TEXT_LOW_CONFIDENCE",
                ]
            },
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
        "qualityRules": {
            "criticalConflictFields": [
                "report_no",
                "project_name",
                "weld_no",
                "detection_date",
                "evaluation_level",
                "conclusion",
            ],
        },
        "preprocessPolicy": {
            "renderDpi": 300,
            "maxLongSide": 2600,
            "textDetLimitSideLen": 3200,
            "ocr": {
                "useDocOrientationClassify": True,
                "useDocUnwarping": False,
                "useTextlineOrientation": True,
                "textDetLimitSideLen": 3200,
            },
            "variants": ["original", "deskew", "gray_clahe", "table_line_enhanced"],
            "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": True, "enablePaddlexSeal": True, "maxPages": 6},
            "fallback": {
                "enableVlmWhen": [
                    "TABLE_STRUCTURE_LOW_CONFIDENCE",
                    "REQUIRED_FIELD_MISSING",
                    "SEAL_TEXT_LOW_CONFIDENCE",
                ]
            },
        },
    },
    "construction_record_v1": {
        "profileId": "construction_record_v1",
        "documentType": "construction_record",
        "requiredFields": ["record_no", "project_name", "construction_date", "responsible_person"],
        "requiredTables": ["construction_record_table"],
        "sealRules": {"required": False, "expectedSealTypes": []},
        "qualityRules": {"criticalConflictFields": ["record_no", "project_name", "construction_date"]},
        "preprocessPolicy": {
            "renderDpi": 300,
            "maxLongSide": 2600,
            "variants": ["original", "deskew", "gray_clahe", "table_line_enhanced"],
            "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": False, "enablePaddlexSeal": False},
        },
    },
    "welding_record_v1": {
        "profileId": "welding_record_v1",
        "documentType": "welding_record",
        "requiredFields": ["record_no", "weld_no", "welder_name", "welder_cert_no", "welding_date"],
        "requiredTables": ["welding_record_table"],
        "sealRules": {"required": False, "expectedSealTypes": []},
        "qualityRules": {"criticalConflictFields": ["record_no", "weld_no", "welder_cert_no", "welding_date"]},
        "preprocessPolicy": {
            "renderDpi": 300,
            "maxLongSide": 2600,
            "variants": ["original", "deskew", "gray_clahe", "table_line_enhanced"],
            "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": False, "enablePaddlexSeal": False},
        },
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
        "qualityRules": {
            "criticalConflictFields": [
                "certificate_no",
                "organization_name",
                "license_scope",
                "valid_until",
                "issuer",
                "issue_date",
            ],
        },
        "preprocessPolicy": {
            "renderDpi": 400,
            "maxLongSide": 2800,
            "textDetLimitSideLen": 3200,
            "ocr": {
                "useDocOrientationClassify": True,
                "useDocUnwarping": True,
                "useTextlineOrientation": True,
                "textDetLimitSideLen": 3200,
            },
            "variants": ["original", "deskew", "gray_clahe", "adaptive_threshold", "seal_color_mask"],
            "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": True, "enablePaddlexSeal": True, "cropPaddingRatio": 0.18, "maxPages": 8},
        },
    },
    "piping_characteristic_list_v1": {
        "profileId": "piping_characteristic_list_v1",
        "documentType": "engineering_table_photo",
        "postprocessVersion": "piping-table-opencv-grid-fragment-seal-v8",
        "requiredFields": [
            "company_name",
            "project_name",
            "document_title",
            "drawing_no",
            "design_phase",
            "pipe_no",
            "seal",
        ],
        "requiredTables": ["piping_characteristic_table"],
        "sealRules": {
            "required": True,
            "expectedSealTypes": ["design_license_seal", "drawing_approval_seal"],
            "preferredVisualColors": ["red"],
            "preferredVisualRegion": "bottom_right",
        },
        "qualityRules": {
            "minFieldConfidence": 0.75,
            "minTableStructureConfidence": 0.6,
            "criticalConflictFields": [
                "company_name",
                "project_name",
                "drawing_no",
                "design_phase",
                "pipe_no",
                "design_pressure",
            ],
        },
        "organizationAliases": [],
        "preprocessPolicy": {
            "renderDpi": 300,
            "maxLongSide": 2600,
            "textDetLimitSideLen": 4096,
            "ocr": {
                "useDocOrientationClassify": True,
                "useDocUnwarping": True,
                "useTextlineOrientation": True,
                "textDetLimitSideLen": 4096,
            },
            "variants": ["original", "gray_clahe", "table_line_enhanced", "seal_color_mask"],
            "table": {
                "preferEngine": "pp_structure_v3",
                "fallback": "heuristic_table_from_fragments",
                "useLineEnhancedImage": True,
            },
            "seal": {"enableColorCandidate": True, "enablePaddlexSeal": True, "maxPages": 4},
        },
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


def validate_profiles(profiles: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    source = profiles or OCR_PROFILES
    failures: list[dict[str, Any]] = []
    for profile_id, raw_profile in source.items():
        if raw_profile.get("profileId") != profile_id:
            failures.append(profile_failure(profile_id, "profileId", "profileId must match registry key"))
        if profile_id != DEFAULT_PROFILE_ID:
            raw_quality_rules = raw_profile.get("qualityRules")
            raw_critical = raw_quality_rules.get("criticalConflictFields") if isinstance(raw_quality_rules, dict) else None
            if not isinstance(raw_critical, list) or not raw_critical:
                failures.append(
                    profile_failure(
                        profile_id,
                        "qualityRules.criticalConflictFields",
                        "business profiles must explicitly declare critical conflict fields",
                    )
                )
            if not isinstance(raw_profile.get("preprocessPolicy"), dict):
                failures.append(
                    profile_failure(
                        profile_id,
                        "preprocessPolicy",
                        "business profiles must explicitly define preprocessPolicy",
                    )
                )
        try:
            profile = merged_profile(profile_id) if profiles is None else merge_profile_from(source, profile_id)
        except Exception as exc:
            failures.append(profile_failure(profile_id, "merge", f"profile merge failed: {exc.__class__.__name__}"))
            continue
        if not str(profile.get("documentType") or "").strip():
            failures.append(profile_failure(profile_id, "documentType", "documentType is required"))
        for key in ["requiredFields", "requiredTables"]:
            if not isinstance(profile.get(key), list):
                failures.append(profile_failure(profile_id, key, f"{key} must be a list"))
        seal_rules = profile.get("sealRules")
        if not isinstance(seal_rules, dict):
            failures.append(profile_failure(profile_id, "sealRules", "sealRules must be an object"))
        else:
            if not isinstance(seal_rules.get("required"), bool):
                failures.append(profile_failure(profile_id, "sealRules.required", "sealRules.required must be boolean"))
            if not isinstance(seal_rules.get("expectedSealTypes"), list):
                failures.append(
                    profile_failure(profile_id, "sealRules.expectedSealTypes", "expectedSealTypes must be a list")
                )
        quality_rules = profile.get("qualityRules")
        if not isinstance(quality_rules, dict):
            failures.append(profile_failure(profile_id, "qualityRules", "qualityRules must be an object"))
        else:
            for key in ["minFieldConfidence", "minTableStructureConfidence"]:
                if not confidence_threshold_valid(quality_rules.get(key)):
                    failures.append(profile_failure(profile_id, f"qualityRules.{key}", f"{key} must be between 0 and 1"))
            critical = quality_rules.get("criticalConflictFields")
            if not isinstance(critical, list):
                failures.append(
                    profile_failure(
                        profile_id,
                        "qualityRules.criticalConflictFields",
                        "criticalConflictFields must be a list",
                    )
                )
            elif profile_id != DEFAULT_PROFILE_ID and not critical:
                failures.append(
                    profile_failure(
                        profile_id,
                        "qualityRules.criticalConflictFields",
                        "business profiles must define at least one critical conflict field",
                    )
                )
        preprocess_policy = profile.get("preprocessPolicy")
        if not isinstance(preprocess_policy, dict):
            failures.append(profile_failure(profile_id, "preprocessPolicy", "preprocessPolicy must be an object"))
        else:
            variants = preprocess_policy.get("variants")
            if not isinstance(variants, list) or "original" not in variants:
                failures.append(
                    profile_failure(profile_id, "preprocessPolicy.variants", "variants must include original")
                )
            elif len({str(item) for item in variants}) != len(variants):
                failures.append(
                    profile_failure(profile_id, "preprocessPolicy.variants", "variants must not contain duplicates")
                )
            if not isinstance(preprocess_policy.get("table"), dict):
                failures.append(profile_failure(profile_id, "preprocessPolicy.table", "table policy must be an object"))
            if not isinstance(preprocess_policy.get("seal"), dict):
                failures.append(profile_failure(profile_id, "preprocessPolicy.seal", "seal policy must be an object"))
            required_tables = profile.get("requiredTables") or []
            if required_tables and isinstance(variants, list) and "table_line_enhanced" not in variants:
                failures.append(
                    profile_failure(
                        profile_id,
                        "preprocessPolicy.variants",
                        "table profiles must include table_line_enhanced",
                    )
                )
            seal_policy = preprocess_policy.get("seal") if isinstance(preprocess_policy.get("seal"), dict) else {}
            seal_required = bool((profile.get("sealRules") or {}).get("required"))
            if seal_required and not bool(seal_policy.get("enableColorCandidate")):
                failures.append(
                    profile_failure(
                        profile_id,
                        "preprocessPolicy.seal.enableColorCandidate",
                        "seal-required profiles must enable color seal candidates",
                    )
                )
            if seal_required and not bool(seal_policy.get("enablePaddlexSeal") or seal_policy.get("enableSealTextRecognition")):
                failures.append(
                    profile_failure(
                        profile_id,
                        "preprocessPolicy.seal.enablePaddlexSeal",
                        "seal-required profiles must enable a real seal text recognizer",
                    )
                )
            if seal_required and int(seal_policy.get("maxPages") or 0) < 2:
                failures.append(
                    profile_failure(
                        profile_id,
                        "preprocessPolicy.seal.maxPages",
                        "seal-required profiles must search at least first and last pages",
                    )
                )
            fallback = preprocess_policy.get("fallback") if isinstance(preprocess_policy.get("fallback"), dict) else {}
            fallback_reasons = {str(item) for item in fallback.get("enableVlmWhen") or []}
            if seal_required and "SEAL_TEXT_LOW_CONFIDENCE" not in fallback_reasons:
                failures.append(
                    profile_failure(
                        profile_id,
                        "preprocessPolicy.fallback.enableVlmWhen",
                        "seal-required profiles must include SEAL_TEXT_LOW_CONFIDENCE fallback",
                    )
                )
    return failures


def merge_profile_from(source: dict[str, dict[str, Any]], profile_id: str) -> dict[str, Any]:
    base = deepcopy(source[DEFAULT_PROFILE_ID])
    if profile_id == DEFAULT_PROFILE_ID:
        return apply_profile_defaults(base)
    override = deepcopy(source[profile_id])
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key].update(value)
        else:
            base[key] = value
    return apply_profile_defaults(base)


def confidence_threshold_valid(value: Any) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return 0 <= numeric <= 1


def profile_failure(profile_id: str, path: str, message: str) -> dict[str, Any]:
    return {"profileId": profile_id, "path": path, "message": message}


def merged_profile(profile_id: str) -> dict[str, Any]:
    base = deepcopy(OCR_PROFILES[DEFAULT_PROFILE_ID])
    if profile_id == DEFAULT_PROFILE_ID:
        return apply_profile_defaults(base)
    override = deepcopy(OCR_PROFILES[profile_id])
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key].update(value)
        else:
            base[key] = value
    return apply_profile_defaults(base)


def apply_profile_defaults(profile: dict[str, Any]) -> dict[str, Any]:
    policy = profile.setdefault("preprocessPolicy", {})
    fallback = policy.setdefault("fallback", {})
    configured = [str(item) for item in fallback.get("enableVlmWhen") or []]
    fallback["enableVlmWhen"] = list(dict.fromkeys([*configured, *DEFAULT_VLM_FALLBACK_REASONS]))
    return profile
