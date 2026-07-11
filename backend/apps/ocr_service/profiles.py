from __future__ import annotations

from copy import deepcopy
from typing import Any

from apps.ocr_service.utils import parse_bool


DEFAULT_PROFILE_ID = "generic_document_v1"
PROFILE_ALIASES = {
    "engineering_drawing_list": "engineering_drawing_list_v1",
    "drawing_material_list": "drawing_material_list_v1",
    "process_flow_diagram": "process_flow_diagram_v1",
    "strength_calculation": "strength_calculation_v1",
    "design_specification": "design_specification_v1",
    "equipment_list": "equipment_list_v1",
    "paint_insulation_list": "paint_insulation_list_v1",
    "comprehensive_material_list": "comprehensive_material_list_v1",
    "site_layout_drawing": "site_layout_drawing_v1",
    "construction_plan": "construction_plan_v1",
    "welding_procedure_qualification": "welding_procedure_qualification_v1",
}
DEFAULT_VLM_FALLBACK_REASONS = [
    "REQUIRED_FIELD_MISSING",
    "FIELD_LOW_CONFIDENCE",
    "FIELD_FORMAT_INVALID",
    "FIELD_EVIDENCE_MISSING",
    "FIELD_VALUE_CONFLICT",
    "REQUIRED_TABLE_MISSING",
    "TABLE_STRUCTURE_LOW_CONFIDENCE",
    "TABLE_CELL_EVIDENCE_LOW",
    "TABLE_CONTENT_SPARSE",
    "TABLE_EVIDENCE_MISSING",
    "TABLE_ENGINE_CONFLICT",
    "SEAL_NOT_FOUND",
    "SEAL_TEXT_LOW_CONFIDENCE",
    "SEAL_EVIDENCE_MISSING",
    "EXPECTED_SEAL_TYPE_MISSING",
]


ENGINEERING_DRAWING_COMMON_REQUIRED_FIELDS = [
    "company_name",
    "project_name",
    "document_title",
    "drawing_no",
    "design_phase",
    "blue_seal_expiry",
    "seal",
]

ENGINEERING_DRAWING_COMMON_PREPROCESS_POLICY = {
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
    "seal": {
        "enableColorCandidate": True,
        "enablePaddlexSeal": True,
        "enableSealTextRecognition": True,
        "cropPaddingRatio": 0.16,
        "maxPages": 4,
    },
}

ENGINEERING_DRAWING_COMMON_SEAL_RULES = {
    "required": True,
    "expectedSealTypes": ["design_license_seal", "drawing_approval_seal"],
    "preferredVisualColors": ["red", "blue"],
    "preferredVisualRegion": "bottom_right",
}


def structured_extraction_config(
    profile_id: str,
    fields: list[str],
    *,
    tables: list[str] | None = None,
    field_definitions: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": "DocumentAiStructuredExtraction@1",
        "mode": "shadow",
        "templateVersion": f"{profile_id}-nuextract3@1",
        "maxCandidates": 64,
        "maxPriorTokens": 12000,
        "maxPages": 6,
        "fields": list(fields),
        "tables": list(tables or []),
        "fieldDefinitions": dict(field_definitions or {}),
        "outputContract": {
            "fieldShape": {"value": "", "sourceCandidateIds": []},
            "tableRowShape": {"cells": {}, "sourceCandidateIds": []},
            "allowDirectVisionOnly": True,
            "directVisionOnlyAdvisory": True,
        },
    }


def engineering_drawing_profile(
    profile_id: str,
    document_type: str,
    critical_fields: list[str] | None = None,
    structured_fields: list[str] | None = None,
    structured_tables: list[str] | None = None,
) -> dict[str, Any]:
    profile = {
        "profileId": profile_id,
        "documentType": document_type,
        "postprocessVersion": "engineering-drawing-generic-route-v1",
        "requiredFields": list(ENGINEERING_DRAWING_COMMON_REQUIRED_FIELDS),
        "requiredTables": [],
        "sealRules": deepcopy(ENGINEERING_DRAWING_COMMON_SEAL_RULES),
        "qualityRules": {
            "minFieldConfidence": 0.72,
            "minTableStructureConfidence": 0.55,
            "criticalConflictFields": critical_fields
            or [
                "company_name",
                "project_name",
                "drawing_no",
                "design_phase",
                "blue_seal_expiry",
            ],
        },
        "organizationAliases": [],
        "preprocessPolicy": deepcopy(ENGINEERING_DRAWING_COMMON_PREPROCESS_POLICY),
    }
    if structured_fields is not None:
        profile["structuredExtraction"] = structured_extraction_config(
            profile_id,
            structured_fields,
            tables=structured_tables,
        )
    return profile


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
            "table": {
                "enabled": False,
                "preferEngine": "pp_structure_v3",
                "fallback": "heuristic_table_from_fragments",
                "maxPages": 2,
            },
            "seal": {"enableColorCandidate": False, "enablePaddlexSeal": False, "maxPages": 2},
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
        "structuredExtraction": structured_extraction_config(
            "quality_certificate_v1",
            [
                "certificate_no",
                "manufacturer",
                "material_grade",
                "specification",
                "batch_no",
                "heat_no",
                "standard_no",
                "inspection_conclusion",
                "issue_date",
            ],
            tables=["material_chemical_composition_table", "mechanical_property_table"],
        ),
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
        "structuredExtraction": structured_extraction_config(
            "ndt_rt_report_v1",
            [
                "report_no",
                "project_name",
                "detection_method",
                "weld_no",
                "detection_date",
                "detection_ratio",
                "technical_grade",
                "evaluation_level",
                "film_model",
                "intensifying_screen_thickness",
                "conclusion",
                "inspection_unit",
            ],
            tables=["weld_detection_result_table"],
            field_definitions={
                "detection_ratio": "检测比例，例如 10%",
                "technical_grade": "射线检测技术等级，例如 AB",
                "evaluation_level": "合格或评定级别，例如 III",
                "film_model": "胶片型号，不是底片质量等级",
                "intensifying_screen_thickness": "增感屏厚度，例如 0.03mm",
            },
        ),
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
    "construction_plan_v1": {
        "profileId": "construction_plan_v1",
        "documentType": "construction_plan",
        "postprocessVersion": "construction-plan-profile-route-v1",
        "requiredFields": ["document_title", "project_name", "construction_unit", "issue_date"],
        "requiredTables": [],
        "sealRules": {"required": False, "expectedSealTypes": []},
        "qualityRules": {
            "minFieldConfidence": 0.7,
            "minTableStructureConfidence": 0.0,
            "criticalConflictFields": ["document_title", "project_name", "construction_unit", "issue_date"],
        },
        "preprocessPolicy": {
            "renderDpi": 300,
            "maxLongSide": 2600,
            "textDetLimitSideLen": 3200,
            "ocr": {
                "useDocOrientationClassify": True,
                "useDocUnwarping": True,
                "useTextlineOrientation": True,
                "textDetLimitSideLen": 3200,
            },
            "variants": ["original", "deskew", "gray_clahe"],
            "table": {"enabled": False, "preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": False, "enablePaddlexSeal": False, "maxPages": 2},
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
    "welding_procedure_qualification_v1": {
        "profileId": "welding_procedure_qualification_v1",
        "documentType": "welding_procedure_qualification",
        "postprocessVersion": "welding-procedure-qualification-profile-route-v1",
        "requiredFields": [
            "report_no",
            "project_name",
            "procedure_no",
            "welding_method",
            "base_material",
            "thickness_range",
            "qualification_date",
        ],
        "requiredTables": ["welding_procedure_qualification_table"],
        "sealRules": {"required": False, "expectedSealTypes": []},
        "qualityRules": {
            "minFieldConfidence": 0.7,
            "minTableStructureConfidence": 0.55,
            "criticalConflictFields": [
                "report_no",
                "procedure_no",
                "welding_method",
                "base_material",
                "thickness_range",
                "qualification_date",
            ],
        },
        "preprocessPolicy": {
            "renderDpi": 300,
            "maxLongSide": 2600,
            "textDetLimitSideLen": 3200,
            "ocr": {
                "useDocOrientationClassify": True,
                "useDocUnwarping": True,
                "useTextlineOrientation": True,
                "textDetLimitSideLen": 3200,
            },
            "variants": ["original", "deskew", "gray_clahe", "table_line_enhanced"],
            "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": False, "enablePaddlexSeal": False, "maxPages": 2},
        },
    },
    "welder_certificate_v1": {
        "profileId": "welder_certificate_v1",
        "documentType": "welder_certificate",
        "requiredFields": [
            "welder_certificate_no",
            "welder_archive_no",
            "issuing_authority",
            "welder_operation_item_code",
            "approval_date",
            "valid_until",
        ],
        "requiredTables": ["welder_qualified_item_table"],
        "sealRules": {"required": False, "expectedSealTypes": []},
        "qualityRules": {
            "criticalConflictFields": [
                "welder_certificate_no",
                "welder_archive_no",
                "issuing_authority",
                "welder_operation_item_code",
                "approval_date",
                "valid_until",
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
            "seal": {"enableColorCandidate": False, "enablePaddlexSeal": False, "maxPages": 4},
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
        "postprocessVersion": "piping-table-opencv-grid-fragment-seal-v9",
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
        "structuredExtraction": structured_extraction_config(
            "piping_characteristic_list_v1",
            [
                "company_name",
                "project_name",
                "document_title",
                "drawing_no",
                "design_phase",
                "pipe_no",
                "pipeline_class",
                "medium",
                "design_pressure",
                "design_temperature",
                "strength_test",
                "leak_test",
                "detection_method",
                "detection_ratio",
                "evaluation_level",
                "technical_grade",
            ],
            tables=["piping_characteristic_table"],
            field_definitions={
                "strength_test": "强度试验的压力值或试验方式；RT/UT/MT/PT 不是强度试验",
                "leak_test": "严密性、气密性或泄漏性试验的压力值或方式；检测比例不是试验值",
                "detection_method": "无损检测方法，例如 RT、UT、MT、PT 或 TOFD",
                "detection_ratio": "无损检测抽检比例，例如 10%",
                "evaluation_level": "无损检测合格或评定级别，例如 III",
                "technical_grade": "无损检测技术等级，例如 AB",
            },
        ),
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
    "engineering_drawing_list_v1": {
        "profileId": "engineering_drawing_list_v1",
        "documentType": "engineering_drawing_list",
        "postprocessVersion": "engineering-drawing-list-profile-router-seal-crop-rows-v2",
        "requiredFields": [
            "company_name",
            "project_name",
            "document_title",
            "drawing_no",
            "design_phase",
            "blue_seal_expiry",
            "seal",
        ],
        "requiredTables": ["engineering_drawing_title_block_v1"],
        "sealRules": {
            "required": True,
            "expectedSealTypes": ["design_license_seal", "drawing_approval_seal"],
            "preferredVisualColors": ["red", "blue"],
            "preferredVisualRegion": "bottom_right",
        },
        "structuredExtraction": structured_extraction_config(
            "engineering_drawing_list_v1",
            [
                "company_name",
                "project_name",
                "document_title",
                "drawing_no",
                "design_phase",
                "total_sheets",
                "blue_seal_expiry",
            ],
            tables=["engineering_drawing_title_block_v1", "engineering_drawing_list_rows"],
        ),
        "qualityRules": {
            "minFieldConfidence": 0.72,
            "minTableStructureConfidence": 0.6,
            "criticalConflictFields": [
                "company_name",
                "project_name",
                "drawing_no",
                "design_phase",
                "total_sheets",
                "blue_seal_expiry",
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
            "seal": {
                "enableColorCandidate": True,
                "enablePaddlexSeal": True,
                "enableSealTextRecognition": True,
                "cropPaddingRatio": 0.16,
                "maxPages": 4,
            },
        },
    },
    "drawing_material_list_v1": engineering_drawing_profile(
        "drawing_material_list_v1",
        "drawing_material_list",
    ),
    "process_flow_diagram_v1": engineering_drawing_profile(
        "process_flow_diagram_v1",
        "process_flow_diagram",
    ),
    "strength_calculation_v1": engineering_drawing_profile(
        "strength_calculation_v1",
        "strength_calculation",
        ["project_name", "drawing_no", "design_phase", "document_title", "blue_seal_expiry"],
    ),
    "design_specification_v1": engineering_drawing_profile(
        "design_specification_v1",
        "design_specification",
    ),
    "equipment_list_v1": engineering_drawing_profile(
        "equipment_list_v1",
        "equipment_list",
    ),
    "paint_insulation_list_v1": engineering_drawing_profile(
        "paint_insulation_list_v1",
        "paint_insulation_list",
    ),
    "comprehensive_material_list_v1": engineering_drawing_profile(
        "comprehensive_material_list_v1",
        "comprehensive_material_list",
        structured_fields=[
            "company_name",
            "project_name",
            "document_title",
            "drawing_no",
            "design_phase",
            "material_name",
            "material_grade",
            "specification",
            "quantity",
            "standard_no",
        ],
        structured_tables=["comprehensive_material_list"],
    ),
    "site_layout_drawing_v1": engineering_drawing_profile(
        "site_layout_drawing_v1",
        "site_layout_drawing",
        ["company_name", "drawing_no", "design_phase", "document_title"],
    ),
}


def profile_for(profile_id: str | None = None, document_type: str | None = None) -> dict[str, Any]:
    if profile_id and profile_id in PROFILE_ALIASES:
        profile_id = PROFILE_ALIASES[profile_id]
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
            if parse_bool(seal_rules.get("required"), None) is None:
                failures.append(
                    profile_failure(
                        profile_id,
                        "sealRules.required",
                        "sealRules.required must be a boolean or a parseable boolean string",
                    )
                )
            if not isinstance(seal_rules.get("expectedSealTypes"), list):
                failures.append(
                    profile_failure(profile_id, "sealRules.expectedSealTypes", "expectedSealTypes must be a list")
                )
        quality_rules = profile.get("qualityRules")
        if not isinstance(quality_rules, dict):
            failures.append(profile_failure(profile_id, "qualityRules", "qualityRules must be an object"))
        else:
            for key in ["minFieldConfidence", "minTableStructureConfidence", "minTableCellEvidenceCoverage"]:
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
            seal_required = parse_bool((profile.get("sealRules") or {}).get("required"), False) is True
            if seal_required and parse_bool(seal_policy.get("enableColorCandidate"), False) is not True:
                failures.append(
                    profile_failure(
                        profile_id,
                        "preprocessPolicy.seal.enableColorCandidate",
                        "seal-required profiles must enable color seal candidates",
                    )
                )
            if seal_required and not (
                parse_bool(seal_policy.get("enablePaddlexSeal"), False)
                or parse_bool(seal_policy.get("enableSealTextRecognition"), False)
                or parse_bool(seal_policy.get("enableAgentdesignSeal"), False)
            ):
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
        structured = profile.get("structuredExtraction")
        if structured is not None:
            if not isinstance(structured, dict):
                failures.append(
                    profile_failure(profile_id, "structuredExtraction", "structuredExtraction must be an object")
                )
            else:
                if structured.get("mode") != "shadow":
                    failures.append(
                        profile_failure(profile_id, "structuredExtraction.mode", "structured extraction must be shadow-only")
                    )
                fields = structured.get("fields")
                if not isinstance(fields, list) or not fields:
                    failures.append(
                        profile_failure(profile_id, "structuredExtraction.fields", "structured extraction fields are required")
                    )
                elif "film_quality" in fields:
                    failures.append(
                        profile_failure(
                            profile_id,
                            "structuredExtraction.fields",
                            "film_quality is ambiguous; use technical_grade, film_model, or intensifying_screen_thickness",
                        )
                    )
                for key, ceiling in [("maxCandidates", 64), ("maxPriorTokens", 12000), ("maxPages", 6)]:
                    try:
                        configured_limit = int(structured.get(key) or 0)
                    except (TypeError, ValueError):
                        configured_limit = 0
                    if configured_limit <= 0 or configured_limit > ceiling:
                        failures.append(
                            profile_failure(
                                profile_id,
                                f"structuredExtraction.{key}",
                                f"{key} must be between 1 and {ceiling}",
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
    if value is None:
        return True
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
