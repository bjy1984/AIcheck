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
    "manufacturing_supervision_certificate": "manufacturing_supervision_certificate_v1",
    "type_test_report": "type_test_report_v1",
    "foreign_component_inspection_record": "foreign_component_inspection_record_v1",
    "factory_inspection_report": "factory_inspection_report_v1",
    "material_retest_report": "material_retest_report_v1",
    "acceptance_witness_record": "acceptance_witness_record_v1",
    "sampling_witness_record": "sampling_witness_record_v1",
    "material_ndt_report": "material_ndt_report_v1",
    "technical_review_approval": "technical_review_approval_v1",
    "new_material_data": "new_material_data_v1",
    "material_mark_transfer_record": "material_mark_transfer_record_v1",
    "material_substitution_approval": "material_substitution_approval_v1",
    "valve_test_report": "valve_test_report_v1",
    "pipeline_summary": "pipeline_summary_v1",
    "welding_consumable_certificate": "welding_consumable_certificate_v1",
    "welding_consumable_management": "welding_consumable_management_v1",
    "pipe_fit_up_record": "pipe_fit_up_record_v1",
    "weld_appearance_record": "weld_appearance_record_v1",
    "weld_repair_record": "weld_repair_record_v1",
    "heat_treatment_procedure": "heat_treatment_procedure_v1",
    "heat_treatment_instrument": "heat_treatment_instrument_v1",
    "heat_treatment_record": "heat_treatment_record_v1",
    "hardness_report": "hardness_report_v1",
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

BUSINESS_RECORD_PREPROCESS_POLICY = {
    "renderDpi": 400,
    "maxLongSide": 3000,
    "textDetLimitSideLen": 3400,
    "ocr": {
        "useDocOrientationClassify": True,
        "useDocUnwarping": True,
        "useTextlineOrientation": True,
        "textDetLimitSideLen": 3400,
    },
    "variants": ["original", "deskew", "gray_clahe", "adaptive_threshold", "table_line_enhanced"],
    "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
    "seal": {
        "enableColorCandidate": True,
        "enablePaddlexSeal": True,
        "enableSealTextRecognition": True,
        "cropPaddingRatio": 0.18,
        "maxPages": 10,
    },
}


def structured_extraction_config(
    profile_id: str,
    fields: list[str],
    *,
    tables: list[str] | None = None,
    field_definitions: dict[str, str] | None = None,
    table_definitions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": "DocumentAiStructuredExtraction@2",
        "mode": "shadow",
        "templateVersion": f"{profile_id}-qwen-grounded@2",
        "maxCandidates": 64,
        "maxPriorTokens": 12000,
        "maxPages": 6,
        "fields": list(fields),
        "tables": list(tables or []),
        "fieldDefinitions": dict(field_definitions or {}),
        "tableDefinitions": deepcopy(table_definitions or {}),
        "outputContract": {
            "fieldShape": {"value": "", "sourceCandidateIds": []},
            "tableRowShape": {
                "tableId": "",
                "rowKey": "",
                "cells": {"column_key": {"value": "", "sourceCandidateIds": []}},
            },
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
            "product_name",
            "material_grade",
            "specification",
            "batch_no",
            "standard_no",
            "inspection_conclusion",
            "issue_date",
        ],
        "requiredTables": ["material_chemical_composition_table", "mechanical_property_table"],
        "sealRules": {"required": True, "expectedSealTypes": ["company_official_seal", "quality_seal"]},
        "structuredExtraction": structured_extraction_config(
            "quality_certificate_v1",
            [
                "certificate_no",
                "manufacturer",
                "dealer_name",
                "product_name",
                "material_grade",
                "specification",
                "quantity",
                "batch_no",
                "heat_no",
                "standard_no",
                "delivery_condition",
                "document_form",
                "inspection_items",
                "test_results",
                "inspection_conclusion",
                "issue_date",
                "manufacturer_quality_seal",
                "dealer_official_seal",
                "handler_responsible_seal",
            ],
            tables=["material_chemical_composition_table", "mechanical_property_table"],
            field_definitions={
                "document_form": "仅从文件明确标注或可靠文档元数据中抽取原件、正本、复印件或副本；扫描PDF本身不得默认视为复印件。",
                "manufacturer_quality_seal": "制造单位质量检验章或质量证明专用章的识别事实。",
                "dealer_official_seal": "复印件上的经营单位公章，不得以安装单位章默认替代。",
                "handler_responsible_seal": "复印件上的经办负责人章或签章，与经营单位公章分别记录。",
                "test_results": "化学、力学和出厂检验项目的结构化实测值；保留单位、原文和证据位置。",
            },
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
    "manufacturing_supervision_certificate_v1": {
        "profileId": "manufacturing_supervision_certificate_v1",
        "documentType": "manufacturing_supervision_certificate",
        "requiredFields": [
            "certificate_no",
            "product_name",
            "manufacturer",
            "conclusion",
        ],
        "requiredTables": [],
        "sealRules": {"required": False, "expectedSealTypes": ["inspection_seal", "company_official_seal"]},
        "structuredExtraction": structured_extraction_config(
            "manufacturing_supervision_certificate_v1",
            [
                "certificate_no",
                "product_name",
                "manufacturer",
                "specification",
                "material",
                "manufacturing_process",
                "structure",
                "batch_no",
                "serial_no",
                "conclusion",
                "supervision_organization",
                "issue_date",
            ],
            tables=["manufacturing_supervision_product_scope_table"],
            field_definitions={
                "batch_no": "埋弧焊钢管、聚乙烯管逐批监检时用于关联设计材料表的批号或批次号。",
                "serial_no": "元件组合装置逐台监检时用于关联具体台件的产品编号或出厂编号。",
                "conclusion": "制造监督检验证书中的监检结论，不从印章存在性推断。",
            },
        ),
        "qualityRules": {
            "criticalConflictFields": ["certificate_no", "product_name", "manufacturer", "batch_no", "serial_no", "conclusion"],
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
    "type_test_report_v1": {
        "profileId": "type_test_report_v1",
        "documentType": "type_test_report",
        "requiredFields": [
            "report_no",
            "product_name",
            "manufacturer",
            "test_organization",
            "specification_scope",
            "conclusion",
        ],
        "requiredTables": [],
        "sealRules": {"required": False, "expectedSealTypes": ["inspection_seal", "company_official_seal"]},
        "structuredExtraction": structured_extraction_config(
            "type_test_report_v1",
            [
                "report_no",
                "certificate_no",
                "product_name",
                "manufacturer",
                "test_organization",
                "specification",
                "specification_scope",
                "material",
                "structure",
                "manufacturing_process",
                "nominal_diameter_min_mm",
                "nominal_diameter_max_mm",
                "nominal_pressure_min_mpa",
                "nominal_pressure_max_mpa",
                "conclusion",
                "certificate_status",
                "valid_from",
                "valid_until",
                "standard_no",
            ],
            tables=["type_test_product_scope_table"],
            field_definitions={
                "specification_scope": "报告或证书明确覆盖的产品规格范围，不能仅返回试样规格。",
                "manufacturer": "型式试验覆盖的制造单位或申请单位。",
                "test_organization": "实施并签发型式试验报告或证书的机构。",
                "conclusion": "型式试验结论；无法确认时留空，不得推断合格。",
            },
        ),
        "qualityRules": {
            "criticalConflictFields": [
                "report_no",
                "certificate_no",
                "product_name",
                "manufacturer",
                "specification_scope",
                "conclusion",
            ],
        },
        "preprocessPolicy": {
            "renderDpi": 400,
            "maxLongSide": 3000,
            "textDetLimitSideLen": 3400,
            "ocr": {
                "useDocOrientationClassify": True,
                "useDocUnwarping": True,
                "useTextlineOrientation": True,
                "textDetLimitSideLen": 3400,
            },
            "variants": ["original", "deskew", "gray_clahe", "adaptive_threshold", "table_line_enhanced"],
            "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": True, "enablePaddlexSeal": True, "cropPaddingRatio": 0.18, "maxPages": 8},
        },
    },
    "foreign_component_inspection_record_v1": {
        "profileId": "foreign_component_inspection_record_v1",
        "documentType": "foreign_component_inspection_record",
        "requiredFields": [
            "record_no",
            "product_name",
            "manufacturer",
            "inspection_route",
            "inspection_organization",
            "conclusion",
        ],
        "requiredTables": [],
        "sealRules": {"required": False, "expectedSealTypes": ["inspection_seal", "company_official_seal"]},
        "structuredExtraction": structured_extraction_config(
            "foreign_component_inspection_record_v1",
            [
                "record_no",
                "report_no",
                "certificate_no",
                "product_name",
                "manufacturer",
                "inspection_route",
                "inspection_organization",
                "specification",
                "batch_no",
                "serial_no",
                "conclusion",
                "issue_date",
            ],
            tables=["foreign_component_inspection_scope_table"],
            field_definitions={
                "inspection_route": "明确抽取到岸、口岸、使用地或随锅炉/压力容器整机检验，不得根据文件名称之外的信息推断。",
                "manufacturer": "被检境外制造产品的实际制造单位。",
                "conclusion": "产品安全性能检验结论；无法确认时留空，不得推断合格。",
            },
        ),
        "qualityRules": {
            "criticalConflictFields": [
                "record_no",
                "product_name",
                "manufacturer",
                "inspection_route",
                "conclusion",
            ],
        },
        "preprocessPolicy": {
            "renderDpi": 400,
            "maxLongSide": 3000,
            "textDetLimitSideLen": 3400,
            "ocr": {
                "useDocOrientationClassify": True,
                "useDocUnwarping": True,
                "useTextlineOrientation": True,
                "textDetLimitSideLen": 3400,
            },
            "variants": ["original", "deskew", "gray_clahe", "adaptive_threshold", "table_line_enhanced"],
            "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": True, "enablePaddlexSeal": True, "cropPaddingRatio": 0.18, "maxPages": 8},
        },
    },
    "factory_inspection_report_v1": {
        "profileId": "factory_inspection_report_v1",
        "documentType": "factory_inspection_report",
        "requiredFields": [
            "report_no",
            "product_name",
            "material_grade",
            "specification",
            "pressure_class",
            "conclusion",
        ],
        "requiredTables": [],
        "sealRules": {"required": False, "expectedSealTypes": ["inspection_seal", "quality_seal", "company_official_seal"]},
        "structuredExtraction": structured_extraction_config(
            "factory_inspection_report_v1",
            [
                "report_no",
                "product_name",
                "manufacturer",
                "line_no",
                "specification",
                "component_grade",
                "material_grade",
                "batch_no",
                "pressure_class",
                "nominal_pressure_mpa",
                "test_items",
                "test_results",
                "conclusion",
                "standard_no",
                "issue_date",
            ],
            tables=["factory_inspection_item_table"],
            field_definitions={
                "component_grade": "螺栓、螺母等组成件的性能等级或强度等级，与材料牌号分开抽取。",
                "pressure_class": "报告标示的PN、Class或其他额定压力等级，不从试验压力反推。",
                "batch_no": "用于与材料表及专项检验报告建立同批次关联的批号、炉号或炉批号。",
                "conclusion": "出厂检验结论；无法确认时留空，不得推断合格。",
            },
        ),
        "qualityRules": {
            "criticalConflictFields": ["report_no", "product_name", "component_grade", "material_grade", "batch_no", "pressure_class", "conclusion"],
        },
        "preprocessPolicy": {
            "renderDpi": 400,
            "maxLongSide": 3000,
            "textDetLimitSideLen": 3400,
            "ocr": {
                "useDocOrientationClassify": True,
                "useDocUnwarping": True,
                "useTextlineOrientation": True,
                "textDetLimitSideLen": 3400,
            },
            "variants": ["original", "deskew", "gray_clahe", "adaptive_threshold", "table_line_enhanced"],
            "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": True, "enablePaddlexSeal": True, "cropPaddingRatio": 0.18, "maxPages": 8},
        },
    },
    "material_retest_report_v1": {
        "profileId": "material_retest_report_v1",
        "documentType": "material_retest_report",
        "requiredFields": ["report_no", "product_name", "batch_no", "report_type", "test_items", "conclusion"],
        "requiredTables": [],
        "sealRules": {"required": False, "expectedSealTypes": ["inspection_seal", "company_official_seal"]},
        "structuredExtraction": structured_extraction_config(
            "material_retest_report_v1",
            [
                "report_no",
                "report_type",
                "product_name",
                "manufacturer",
                "line_no",
                "specification",
                "component_grade",
                "material_grade",
                "batch_no",
                "pressure_class",
                "nominal_pressure_mpa",
                "test_pressure_mpa",
                "test_items",
                "test_results",
                "conclusion",
                "standard_no",
                "issue_date",
            ],
            tables=["material_retest_result_table"],
            field_definitions={
                "report_type": "光谱、硬度、金相、无损检测或耐压试验等报告类别，可多值。",
                "test_pressure_mpa": "仅对耐压试验报告抽取实际试验压力，单位统一为MPa并保留原文。",
                "batch_no": "必须用于关联被抽查元件、出厂报告和设计材料表。",
                "conclusion": "专项检验或复验结论；无法确认时留空，不得推断合格。",
            },
        ),
        "qualityRules": {
            "criticalConflictFields": ["report_no", "report_type", "product_name", "batch_no", "test_items", "conclusion"],
        },
        "preprocessPolicy": {
            "renderDpi": 400,
            "maxLongSide": 3000,
            "textDetLimitSideLen": 3400,
            "ocr": {
                "useDocOrientationClassify": True,
                "useDocUnwarping": True,
                "useTextlineOrientation": True,
                "textDetLimitSideLen": 3400,
            },
            "variants": ["original", "deskew", "gray_clahe", "adaptive_threshold", "table_line_enhanced"],
            "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": True, "enablePaddlexSeal": True, "cropPaddingRatio": 0.18, "maxPages": 8},
        },
    },
    "acceptance_witness_record_v1": {
        "profileId": "acceptance_witness_record_v1",
        "documentType": "acceptance_witness_record",
        "requiredFields": ["record_no", "product_name", "batch_no", "quantity", "completed_steps", "signature_roles", "conclusion"],
        "requiredTables": ["arrival_acceptance_item_table"],
        "sealRules": {"required": False, "expectedSealTypes": ["company_official_seal", "quality_seal"]},
        "structuredExtraction": structured_extraction_config(
            "acceptance_witness_record_v1",
            [
                "record_no", "product_name", "specification", "material_grade", "batch_no", "heat_no",
                "quantity", "procedure_approved", "completed_steps", "acceptance_items", "sample_no",
                "witness_roles", "signature_roles", "conclusion", "isolated", "nonconformance_disposition",
                "release_approved", "issue_date",
            ],
            tables=["arrival_acceptance_item_table"],
            field_definitions={
                "completed_steps": "分别记录质量证明核验、身份标识核验、外观检查、尺寸检查和结论记录，不得由总体合格结论反推。",
                "signature_roles": "记录验收人员和接收人员等实际签字角色。",
                "witness_roles": "抽样时记录监检人员或其他见证人员角色。",
                "isolated": "验收不合格批次是否已隔离或封存的明确事实。",
            },
        ),
        "qualityRules": {"criticalConflictFields": ["record_no", "product_name", "batch_no", "quantity", "conclusion"]},
        "preprocessPolicy": {
            "renderDpi": 400,
            "maxLongSide": 3000,
            "textDetLimitSideLen": 3400,
            "ocr": {"useDocOrientationClassify": True, "useDocUnwarping": True, "useTextlineOrientation": True, "textDetLimitSideLen": 3400},
            "variants": ["original", "deskew", "gray_clahe", "adaptive_threshold", "table_line_enhanced"],
            "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": True, "enablePaddlexSeal": True, "cropPaddingRatio": 0.18, "maxPages": 8},
        },
    },
    "sampling_witness_record_v1": {
        "profileId": "sampling_witness_record_v1",
        "documentType": "sampling_witness_record",
        "requiredFields": ["record_no", "product_name", "batch_no", "sample_no", "witness_roles"],
        "requiredTables": [],
        "sealRules": {"required": False, "expectedSealTypes": ["company_official_seal", "quality_seal"]},
        "structuredExtraction": structured_extraction_config(
            "sampling_witness_record_v1",
            [
                "record_no", "product_name", "specification", "material_grade", "batch_no", "heat_no",
                "quantity", "sample_no", "witness_roles", "signature_roles", "conclusion", "issue_date",
            ],
            field_definitions={
                "sample_no": "记录抽样形成的样品或试样唯一编号。",
                "witness_roles": "记录监检人员或项目规定的其他见证人员实际角色。",
            },
        ),
        "qualityRules": {"criticalConflictFields": ["record_no", "product_name", "batch_no", "sample_no"]},
        "preprocessPolicy": {
            "renderDpi": 400,
            "maxLongSide": 3000,
            "textDetLimitSideLen": 3400,
            "ocr": {"useDocOrientationClassify": True, "useDocUnwarping": True, "useTextlineOrientation": True, "textDetLimitSideLen": 3400},
            "variants": ["original", "deskew", "gray_clahe", "adaptive_threshold", "table_line_enhanced"],
            "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": True, "enablePaddlexSeal": True, "cropPaddingRatio": 0.18, "maxPages": 8},
        },
    },
    "material_ndt_report_v1": {
        "profileId": "material_ndt_report_v1",
        "documentType": "material_ndt_report",
        "requiredFields": ["report_no", "product_name", "batch_no", "ndt_methods", "test_items", "signature_roles", "conclusion"],
        "requiredTables": ["material_ndt_result_table"],
        "sealRules": {"required": False, "expectedSealTypes": ["inspection_testing_seal", "company_official_seal"]},
        "structuredExtraction": structured_extraction_config(
            "material_ndt_report_v1",
            [
                "report_no", "product_name", "manufacturer", "specification", "material_grade", "batch_no",
                "heat_no", "sample_no", "ndt_methods", "test_items", "test_results", "standard_no",
                "procedure_approved", "required_signature_roles", "signature_roles", "conclusion", "issue_date",
            ],
            tables=["material_ndt_result_table"],
            field_definitions={
                "ndt_methods": "材料本体采用的无损检测方法；不得抽取焊口号或焊缝检测比例来冒充材料本体检测。",
                "batch_no": "被检材料炉批号，用于与材料表、质量证明文件和取样记录追溯。",
                "test_results": "按检测方法记录结构化结果、等级或缺陷数据，并保留原始单位和证据。",
            },
        ),
        "qualityRules": {"criticalConflictFields": ["report_no", "product_name", "batch_no", "ndt_methods", "conclusion"]},
        "preprocessPolicy": {
            "renderDpi": 400,
            "maxLongSide": 3000,
            "textDetLimitSideLen": 3400,
            "ocr": {"useDocOrientationClassify": True, "useDocUnwarping": True, "useTextlineOrientation": True, "textDetLimitSideLen": 3400},
            "variants": ["original", "deskew", "gray_clahe", "adaptive_threshold", "table_line_enhanced"],
            "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": True, "enablePaddlexSeal": True, "cropPaddingRatio": 0.18, "maxPages": 8},
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
        "requiredTables": ["engineering_drawing_list_rows_v1"],
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
            tables=["engineering_drawing_list_rows_v1"],
            table_definitions={
                "engineering_drawing_list_rows_v1": {
                    "aliases": ["engineering_drawing_list_rows"],
                    "columns": {
                        "0": "sequence_no",
                        "1": "drawing_name",
                        "2": "drawing_no",
                    },
                    "rowWindowSize": 10,
                }
            },
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
    "technical_review_approval_v1": {
        "profileId": "technical_review_approval_v1",
        "documentType": "technical_review_approval",
        "requiredFields": ["approval_document_no", "material_grade", "approval_organization", "technical_review_passed", "approval_procedure_completed"],
        "requiredTables": [],
        "sealRules": {"required": True, "expectedSealTypes": ["approval_seal", "company_official_seal"]},
        "structuredExtraction": structured_extraction_config(
            "technical_review_approval_v1",
            ["approval_document_no", "material_grade", "product_name", "applicable_scope", "technical_review_passed", "approval_organization", "approval_procedure_completed", "conclusion", "issue_date"],
            field_definitions={
                "technical_review_passed": "仅依据技术评审证书或评审意见中的明确结论提取，不得由文件标题推断。",
                "approval_procedure_completed": "批准文件编号、批准机构和明确完成状态同时有证据时为真。",
            },
        ),
        "qualityRules": {"criticalConflictFields": ["approval_document_no", "material_grade", "technical_review_passed", "approval_organization", "approval_procedure_completed"]},
        "preprocessPolicy": deepcopy(BUSINESS_RECORD_PREPROCESS_POLICY),
    },
    "new_material_data_v1": {
        "profileId": "new_material_data_v1",
        "documentType": "new_material_data",
        "requiredFields": ["document_no", "material_grade", "data_items"],
        "requiredTables": [],
        "sealRules": {"required": False, "expectedSealTypes": []},
        "structuredExtraction": structured_extraction_config(
            "new_material_data_v1",
            ["document_no", "material_grade", "product_name", "data_items", "chemical_composition", "tensile_properties", "fatigue_data", "fracture_toughness", "scope_performance_parameters", "conclusion", "issue_date"],
            tables=["new_material_performance_data_table"],
            field_definitions={"data_items": "列出文件实际提供的性能数据类别，不得把目录标题推断为已提供完整试验数据。"},
        ),
        "qualityRules": {"criticalConflictFields": ["document_no", "material_grade", "data_items"]},
        "preprocessPolicy": deepcopy(BUSINESS_RECORD_PREPROCESS_POLICY),
    },
    "material_mark_transfer_record_v1": {
        "profileId": "material_mark_transfer_record_v1",
        "documentType": "material_mark_transfer_record",
        "requiredFields": ["record_no", "original_mark", "transferred_mark", "batch_no", "material_grade", "mark_method", "inspector", "conclusion"],
        "requiredTables": [],
        "sealRules": {"required": False, "expectedSealTypes": ["inspection_seal"]},
        "structuredExtraction": structured_extraction_config(
            "material_mark_transfer_record_v1",
            ["record_no", "original_mark", "transferred_mark", "batch_no", "heat_no", "material_grade", "material_type", "special_material", "mark_method", "identity_chain_verified", "confusion_control", "harmful_substances_absent", "inspector", "conclusion", "issue_date"],
            tables=["material_mark_transfer_table"],
        ),
        "qualityRules": {"criticalConflictFields": ["original_mark", "transferred_mark", "batch_no", "material_grade", "mark_method", "conclusion"]},
        "preprocessPolicy": deepcopy(BUSINESS_RECORD_PREPROCESS_POLICY),
    },
    "material_substitution_approval_v1": {
        "profileId": "material_substitution_approval_v1",
        "documentType": "material_substitution_approval",
        "requiredFields": ["change_no", "original_material", "substitute_material", "substitution_scope", "original_design_organization", "approving_organization", "written_approval_present", "approval_date"],
        "requiredTables": [],
        "sealRules": {"required": True, "expectedSealTypes": ["design_license_seal", "company_official_seal"]},
        "structuredExtraction": structured_extraction_config(
            "material_substitution_approval_v1",
            ["change_no", "original_material", "substitute_material", "substitution_scope", "original_design_organization", "approving_organization", "written_approval_present", "approval_date", "implementation_date", "implemented", "conclusion"],
            tables=["material_substitution_scope_table"],
            field_definitions={"implemented": "仅根据施工使用记录或明确的实施状态提取；采购建议或未批准申请不得标记为已实施。"},
        ),
        "qualityRules": {"criticalConflictFields": ["change_no", "original_material", "substitute_material", "original_design_organization", "approving_organization", "approval_date"]},
        "preprocessPolicy": deepcopy(BUSINESS_RECORD_PREPROCESS_POLICY),
    },
    "valve_test_report_v1": {
        "profileId": "valve_test_report_v1",
        "documentType": "valve_test_report",
        "requiredFields": ["report_no", "valve_no", "valve_type", "nominal_diameter_mm", "nominal_pressure", "standard_ref", "construction_record_id", "conclusion"],
        "requiredTables": ["valve_pressure_test_table"],
        "sealRules": {"required": False, "expectedSealTypes": ["inspection_seal"]},
        "structuredExtraction": structured_extraction_config(
            "valve_test_report_v1",
            ["report_no", "valve_no", "valve_type", "nominal_diameter_mm", "nominal_pressure", "valve_body_material_category", "maximum_allowable_working_pressure_mpa", "seal_test_level", "pipeline_grade", "lot_id", "lot_size", "tested_count", "standard_ref", "construction_record_id", "shell_test_medium", "shell_test_pressure_mpa", "shell_hold_seconds", "shell_procedure_steps", "shell_test_result", "shell_leakage", "seal_test_medium", "seal_test_pressure_mpa", "seal_hold_seconds", "seal_procedure_steps", "seal_test_result", "seal_leakage", "conclusion", "issue_date"],
            tables=["valve_pressure_test_table", "valve_sampling_table"],
            field_definitions={
                "standard_ref": "提取报告明确写明的试验依据标准号及年份，不得由文件类型推断。",
                "shell_procedure_steps": "提取壳体试验的实际操作步骤或方法原文要点。",
                "seal_procedure_steps": "提取密封试验的实际操作步骤或方法原文要点。",
            },
        ),
        "qualityRules": {"criticalConflictFields": ["valve_no", "nominal_diameter_mm", "nominal_pressure", "standard_ref", "shell_test_pressure_mpa", "shell_hold_seconds", "seal_test_pressure_mpa", "seal_hold_seconds", "conclusion"]},
        "preprocessPolicy": deepcopy(BUSINESS_RECORD_PREPROCESS_POLICY),
    },
    "site_layout_drawing_v1": engineering_drawing_profile(
        "site_layout_drawing_v1",
        "site_layout_drawing",
        ["company_name", "drawing_no", "design_phase", "document_title"],
    ),
}


R24_R34_BUSINESS_PROFILE_FIELDS = {
    "pipeline_summary_v1": ("pipeline_summary", ["line_no", "material_grade", "outer_diameter", "wall_thickness"], ["管线号", "材料牌号", "外径", "壁厚"]),
    "welding_consumable_certificate_v1": ("welding_consumable_certificate", ["certificate_no", "brand", "specification", "batch_no", "standard_ref", "chemical_composition", "mechanical_properties"], ["证明书编号", "牌号", "规格", "批号", "执行标准", "化学成分", "力学性能"]),
    "welding_consumable_management_v1": ("welding_consumable_management", ["record_no", "record_kind", "batch_no", "temperature", "humidity", "drying_temperature", "drying_minutes", "handler"], ["记录编号", "记录类型", "批号", "温度", "湿度", "烘干温度", "烘干时间", "经办人"]),
    "pipe_fit_up_record_v1": ("pipe_fit_up_record", ["record_no", "weld_no", "wall_thickness", "misalignment", "root_gap", "bevel_angle", "forced_fit_up"], ["记录编号", "焊缝编号", "壁厚", "错边量", "组对间隙", "坡口角度", "强行组对"]),
    "weld_appearance_record_v1": ("weld_appearance_record", ["record_no", "weld_no", "inspection_grade", "wall_thickness", "reinforcement", "width", "undercut_depth", "crack"], ["记录编号", "焊缝编号", "检验等级", "壁厚", "焊缝余高", "焊缝宽度", "咬边深度", "裂纹"]),
    "weld_repair_record_v1": ("weld_repair_record", ["record_no", "weld_no", "repair_application_no", "repair_procedure_no", "same_location_repair_count", "post_repair_ndt_report_no", "post_repair_ndt_result"], ["记录编号", "焊缝编号", "返修申请单号", "返修工艺编号", "同一部位返修次数", "返修后检测报告编号", "返修后检测结论"]),
    "heat_treatment_procedure_v1": ("heat_treatment_procedure", ["procedure_no", "weld_no", "qualification_report_no", "heating_rate", "holding_temperature", "holding_minutes", "cooling_rate", "approved"], ["工艺编号", "焊缝编号", "评定报告编号", "升温速率", "保温温度", "保温时间", "降温速率", "批准"]),
    "heat_treatment_instrument_v1": ("heat_treatment_instrument", ["instrument_type", "instrument_no", "calibration_certificate_no", "valid_until", "drawing_no", "temperature_point_count"], ["仪表类型", "仪表编号", "校准证书编号", "有效期至", "布置图号", "测温点数量"]),
    "heat_treatment_record_v1": ("heat_treatment_record", ["record_no", "weld_no", "curve_ref", "curve_continuous", "holding_temperature", "holding_minutes"], ["记录编号", "焊缝编号", "温度时间曲线", "曲线完整无中断", "保温温度", "保温时间"]),
    "hardness_report_v1": ("hardness_report", ["report_no", "weld_no", "hardness_method", "tested_joint_count", "lot_joint_count", "hardness_readings"], ["报告编号", "焊缝编号", "硬度方法", "检测接头数", "批内接头数", "硬度读数"]),
}

for _profile_id, (_document_type, _required_fields, _labels) in R24_R34_BUSINESS_PROFILE_FIELDS.items():
    OCR_PROFILES[_profile_id] = {
        "profileId": _profile_id,
        "documentType": _document_type,
        "postprocessVersion": "r24-r34-labeled-business-fields-v1",
        "requiredFields": _required_fields,
        "requiredTables": [],
        "fieldLabels": dict(zip(_required_fields, _labels)),
        "structuredExtraction": structured_extraction_config(
            _profile_id,
            _required_fields,
            field_definitions={key: description for key, description in {
                "chemical_composition": "按元素名称提取实测值并保留表格单元格证据，不得把标准限值当作实测值。",
                "mechanical_properties": "按试验项目提取实测值、单位和结论，不得只提取合格二字。",
                "hardness_readings": "逐测点提取焊缝或热影响区、硬度方法/标尺、原始读数和换算后HBW。",
            }.items() if key in _required_fields},
        ),
        "sealRules": {"required": False, "expectedSealTypes": []},
        "qualityRules": {"minFieldConfidence": 0.65, "criticalConflictFields": _required_fields[:4]},
        "preprocessPolicy": {
            "renderDpi": 300, "maxLongSide": 2800, "textDetLimitSideLen": 3600,
            "ocr": {"useDocOrientationClassify": True, "useDocUnwarping": True, "useTextlineOrientation": True, "textDetLimitSideLen": 3600},
            "variants": ["original", "deskew", "gray_clahe", "table_line_enhanced"],
            "table": {"preferEngine": "pp_structure_v3", "fallback": "heuristic_table_from_fragments"},
            "seal": {"enableColorCandidate": False, "enablePaddlexSeal": False, "maxPages": 12},
        },
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
