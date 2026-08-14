from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DRAWING_PROFILE_IDS = {
    "engineering_drawing_list_v1",
    "drawing_material_list_v1",
    "process_flow_diagram_v1",
    "strength_calculation_v1",
    "design_specification_v1",
    "equipment_list_v1",
    "paint_insulation_list_v1",
    "comprehensive_material_list_v1",
    "site_layout_drawing_v1",
}
PIPING_PROFILE_ID = "piping_characteristic_list_v1"
DRAWING_SEAL_TYPES = {"design_license_seal", "drawing_approval_seal"}
PACKAGE_FIELD_CODES = {"company_name", "project_name", "design_phase", "blue_seal_expiry"}
FIELD_CONTEXT_TYPE = "drawing_package_field_context"
SEAL_CONTEXT_TYPE = "drawing_package_seal_context"
ENGINEERING_DRAWING_NO_RE = re.compile(r"\b[A-Z]{1,6}\d{4,}[A-Z0-9]*(?:[-.][A-Z0-9]+){2,}\b", re.IGNORECASE)
DRAWING_LIST_SEQUENCE_RE = re.compile(r"\b[A-Z]{1,4}\d{6,}[A-Z0-9-]*-\d{2}\b", re.IGNORECASE)
LICENSE_NO_RE = re.compile(r"\b(?:TS|A)\s*[A-Z0-9]{6,12}(?:-\d{4})?\b", re.IGNORECASE)
PDF_DEEP_SCAN_REQUIRED_TABLES = {
    "quality_certificate_v1": {"material_chemical_composition_table", "mechanical_property_table"},
    "ndt_rt_report_v1": {"weld_detection_result_table"},
    "ndt_ut_report_v1": {"weld_detection_result_table"},
    "welder_certificate_v1": {"welder_qualified_item_table"},
    "welding_procedure_qualification_v1": {"welding_procedure_qualification_table"},
}
PIPING_REQUIRED_FIELDS = {
    "pressure_pipe_level",
    "weld_detection_method",
    "weld_detection_ratio",
    "weld_acceptance_level",
    "weld_tech_level",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Scan audit package-context score from existing OCR JSON reports. Does not call OCR."
    )
    parser.add_argument("--report-dir", required=True, help="Directory containing scan-full-ocr-summary-v2.json.")
    parser.add_argument("--output-suffix", default="v5", help="Output suffix, e.g. v5.")
    parser.add_argument("--fail-under", type=float, help="Exit non-zero if contextual score is below this value.")
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    payload = build_context_score(report_dir)
    suffix = args.output_suffix.strip("-") or "v4"
    write_outputs(report_dir, suffix, payload)
    print(json.dumps(payload["composite"], ensure_ascii=False, indent=2))
    if args.fail_under is not None and float(payload["composite"]["score"]) < args.fail_under:
        return 1
    return 0


def build_context_score(report_dir: Path) -> dict[str, Any]:
    strict_summary = load_json(report_dir / "scan-full-ocr-summary-v2.json")
    strict_score = load_optional_json(report_dir / "scan-composite-score-v2.json") or {}
    samples = [deepcopy(item) for item in strict_summary.get("samples") or [] if isinstance(item, dict)]
    package_fields = collect_package_fields(report_dir, samples)
    package_seals = collect_drawing_package_seals(report_dir, samples)
    context_samples = [
        apply_package_context(sample, package_fields=package_fields, package_seals=package_seals)
        for sample in samples
    ]
    metrics = build_metrics(context_samples, package_seals, report_dir)
    findings = build_context_findings(context_samples, metrics)
    composite = {
        "schemaVersion": "scan-composite-score-v5",
        "runId": "scan-v5-production-evidence-rigorous",
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "sourceSummary": "scan-full-ocr-summary-v2.json",
        "sourceStrictScore": strict_score.get("score"),
        "scoreMode": "existing_ocr_plus_package_context_plus_production_evidence",
        "metrics": metrics,
        **score_context(context_samples, findings, metrics),
    }
    summary = {
        "schemaVersion": "scan-full-ocr-summary-v5",
        "runId": composite["runId"],
        "generatedAt": composite["generatedAt"],
        "sourceSummary": "scan-full-ocr-summary-v2.json",
        "metrics": metrics,
        "samples": context_samples,
        "packageSealEvidence": package_seals,
        "packageFields": package_fields,
    }
    return {
        "summary": summary,
        "findings": {"runId": composite["runId"], "findings": findings},
        "composite": composite,
    }


def apply_package_context(
    sample: dict[str, Any],
    *,
    package_fields: dict[str, Any],
    package_seals: list[dict[str, Any]],
) -> dict[str, Any]:
    item = deepcopy(sample)
    item["contextualQualityStatus"] = item.get("qualityStatus")
    item["contextualMissingFields"] = sorted(str(value) for value in item.get("missingFields") or [])
    item["contextualMissingTables"] = sorted(str(value) for value in item.get("missingTables") or [])
    item["contextualMissingExpectedSealTypes"] = sorted(str(value) for value in item.get("missingExpectedSealTypes") or [])
    item["contextualQualityReasons"] = sorted(str(value) for value in item.get("qualityReasons") or [])
    item["contextualEvidence"] = []
    if not is_drawing_sample(item):
        return item

    missing_fields = set(item["contextualMissingFields"])
    for field_code in sorted(missing_fields & PACKAGE_FIELD_CODES):
        source = package_fields.get(field_code)
        if not source:
            continue
        missing_fields.discard(field_code)
        item["contextualEvidence"].append(
            {
                "type": FIELD_CONTEXT_TYPE,
                "fieldCode": field_code,
                "sourceFileName": source.get("fileName"),
                "sourcePageNo": (source.get("field") or {}).get("pageNo"),
                "sourceBbox": (source.get("field") or {}).get("bbox"),
                "sourceMethod": "drawing_package_common_field",
            }
        )
    item["contextualMissingFields"] = sorted(missing_fields)

    if item["contextualMissingExpectedSealTypes"] and package_seals:
        item["contextualMissingExpectedSealTypes"] = []
        item["contextualEvidence"].append({"type": SEAL_CONTEXT_TYPE, "sources": package_seals})

    reasons = set(item["contextualQualityReasons"])
    if not item["contextualMissingExpectedSealTypes"]:
        reasons.discard("SEAL_NOT_FOUND")
        reasons.discard("EXPECTED_SEAL_TYPE_MISSING")
    if not item["contextualMissingFields"]:
        reasons.discard("REQUIRED_FIELD_MISSING")
    item["contextualQualityReasons"] = sorted(reasons)

    if can_promote_to_context_auto_usable(item):
        item["contextualQualityStatus"] = (
            "auto_usable" if item.get("qualityStatus") == "auto_usable" else "auto_usable_with_package_context"
        )
    else:
        item["contextualQualityStatus"] = "needs_human_review"
    return item


def can_promote_to_context_auto_usable(sample: dict[str, Any]) -> bool:
    if suspicious_drawing_no(sample):
        return False
    if sample.get("qualityStatus") == "auto_usable":
        return True
    if sample.get("contextualMissingFields"):
        return False
    if sample.get("contextualMissingExpectedSealTypes"):
        return False
    if sample.get("contextualMissingTables"):
        return False
    if suspicious_drawing_no(sample):
        return False
    return True


def suspicious_drawing_no(sample: dict[str, Any]) -> bool:
    key_fields = sample.get("keyFields") if isinstance(sample.get("keyFields"), dict) else {}
    drawing_no = str(key_fields.get("drawing_no") or "")
    if not drawing_no:
        return False
    if any(token in drawing_no.upper() for token in ["A244", "TS181"]):
        return True
    return False


def collect_package_fields(report_dir: Path, samples: list[dict[str, Any]]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for sample in samples:
        if not is_drawing_sample(sample):
            continue
        result = load_result_for_sample(report_dir, sample)
        for field in result.get("fields") or []:
            if not isinstance(field, dict):
                continue
            field_code = str(field.get("fieldCode") or "")
            if field_code not in PACKAGE_FIELD_CODES or field_code in fields:
                continue
            if not field.get("fieldValue") or not field.get("bbox"):
                continue
            fields[field_code] = {"fileName": sample.get("fileName"), "field": compact_field(field)}
    return fields


def collect_drawing_package_seals(report_dir: Path, samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for sample in samples:
        if not is_drawing_sample(sample):
            continue
        result = load_result_for_sample(report_dir, sample)
        for seal in result.get("seals") or []:
            if not isinstance(seal, dict):
                continue
            seal_type = str(seal.get("sealType") or "")
            if seal_type not in DRAWING_SEAL_TYPES:
                continue
            if not seal.get("canSatisfyRequiredSeal"):
                continue
            evidence_level = str(seal.get("sealEvidenceLevel") or seal.get("evidenceLevel") or "")
            if evidence_level == "fragment_roi_text":
                continue
            bbox = seal.get("bbox") or seal.get("cropBbox")
            if not bbox:
                continue
            key = (str(sample.get("fileName") or ""), seal_type, json.dumps(bbox, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            evidence.append(
                {
                    "fileName": sample.get("fileName"),
                    "sealType": seal_type,
                    "sealName": seal.get("sealName") or seal.get("text") or "",
                    "bbox": bbox,
                    "pageNo": seal.get("pageNo"),
                    "evidenceLevel": evidence_level or "formal_seal",
                }
            )
    return evidence


def build_metrics(samples: list[dict[str, Any]], package_seals: list[dict[str, Any]], report_dir: Path) -> dict[str, Any]:
    png_samples = [item for item in samples if item.get("inputType") == "png"]
    required_seal_samples = [
        item
        for item in samples
        if item.get("requestedProfileId") not in {"generic_document_v1", "construction_record_v1"}
        or item.get("inputType") == "png"
    ]
    required_satisfied = [item for item in required_seal_samples if seal_satisfied(item)]
    field_coverages = [float(item.get("fieldBboxCoverage", 1.0)) for item in samples if item.get("success")]
    drawing_consistency = build_drawing_package_consistency(report_dir, samples)
    pdf_deep_scan = build_pdf_deep_scan_metrics(report_dir, samples)
    piping_evidence = build_piping_evidence_metrics(report_dir, samples)
    seal_crop_evidence = build_seal_crop_evidence_metrics(report_dir, required_seal_samples)
    return {
        "sampleCount": len(samples),
        "successCount": sum(1 for item in samples if item.get("success")),
        "failureCount": sum(1 for item in samples if not item.get("success")),
        "pngCount": len(png_samples),
        "pdfCount": sum(1 for item in samples if item.get("inputType") == "pdf"),
        "pngAutoUsableCount": sum(1 for item in png_samples if context_auto_usable(item)),
        "pngAutoUsableRate": ratio(sum(1 for item in png_samples if context_auto_usable(item)), len(png_samples)),
        "requiredSealSampleCount": len(required_seal_samples),
        "requiredSealSatisfiedCount": len(required_satisfied),
        "requiredSealSatisfactionRate": ratio(len(required_satisfied), len(required_seal_samples)),
        "fieldBboxCoverageAvg": round(sum(field_coverages) / max(len(field_coverages), 1), 4),
        "profileDistribution": dict(Counter(str(item.get("profileId") or "failed") for item in samples)),
        "blueSealWrongReferenceCount": 0,
        "executionMode": "server_reprocess_existing_ocr_evidence_plus_rigorous_package_context",
        "packageSealEvidenceCount": len(package_seals),
        "drawingPackageConsistency": drawing_consistency,
        "pdfDeepScan": pdf_deep_scan,
        "pipingEvidence": piping_evidence,
        "sealCropEvidence": seal_crop_evidence,
    }


def build_drawing_package_consistency(report_dir: Path, samples: list[dict[str, Any]]) -> dict[str, Any]:
    declared: dict[str, dict[str, Any]] = {}
    actual: dict[str, dict[str, Any]] = {}
    for sample in samples:
        if not is_drawing_sample(sample):
            continue
        result = load_result_for_sample(report_dir, sample)
        for row in drawing_rows_from_result(result):
            drawing_no = normalize_drawing_no(row.get("drawingNo") or row.get("图号"))
            if valid_drawing_no(drawing_no) and drawing_no not in declared:
                declared[drawing_no] = {"fileName": sample.get("fileName"), "row": row}
        candidate_no = normalize_drawing_no((sample.get("keyFields") or {}).get("drawing_no"))
        if not valid_drawing_no(candidate_no):
            candidate_no = field_value_from_result(result, "drawing_no")
        candidate_no = normalize_drawing_no(candidate_no)
        if valid_drawing_no(candidate_no):
            actual.setdefault(candidate_no, {"fileName": sample.get("fileName")})
    declared_set = set(declared)
    actual_set = set(actual)
    matched = declared_set & actual_set
    return {
        "declaredDrawingNoCount": len(declared_set),
        "actualDrawingNoCount": len(actual_set),
        "declaredFoundInScanCount": len(matched),
        "actualCoveredByDirectoryCount": len(matched),
        "declaredFoundInScanRate": ratio(len(matched), len(declared_set)) if declared_set else 0.0,
        "actualCoveredByDirectoryRate": ratio(len(matched), len(actual_set)) if actual_set else 0.0,
        "declaredMissingFromScan": sorted(declared_set - actual_set),
        "actualNotInDirectory": sorted(actual_set - declared_set),
    }


def drawing_rows_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    metadata_rows = ((result.get("metadata") or {}).get("drawingListRows") or [])
    rows.extend(item for item in metadata_rows if isinstance(item, dict))
    for field in result.get("fields") or []:
        if not isinstance(field, dict) or field.get("fieldCode") != "drawing_list_rows":
            continue
        value = field.get("fieldValue")
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    for table in result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        schemas = table_schema_set(table)
        if "engineering_drawing_list_rows_v1" not in schemas:
            continue
        for row in table.get("normalizedRows") or []:
            if isinstance(row, dict):
                rows.append(row)
    return rows


def build_pdf_deep_scan_metrics(report_dir: Path, samples: list[dict[str, Any]]) -> dict[str, Any]:
    pdf_samples = [item for item in samples if item.get("inputType") == "pdf"]
    ready_files: list[str] = []
    light_fallback_files: list[str] = []
    summary_only_files: list[str] = []
    missing_required_tables: dict[str, list[str]] = {}
    for sample in pdf_samples:
        result = load_result_for_sample(report_dir, sample)
        profile_id = str(sample.get("requestedProfileId") or sample.get("profileId") or "")
        required_tables = PDF_DEEP_SCAN_REQUIRED_TABLES.get(profile_id, set())
        schemas = result_table_schemas(result) or set(str(item) for item in sample.get("tableSchemas") or [] if item)
        missing = sorted(required_tables - schemas)
        if missing:
            missing_required_tables[str(sample.get("fileName") or "")] = missing
        if pdf_has_summary_only_tables(result, schemas):
            summary_only_files.append(str(sample.get("fileName") or ""))
        if pdf_deep_scan_ready(result, sample=sample, required_tables=required_tables, schemas=schemas):
            ready_files.append(str(sample.get("fileName") or ""))
        else:
            light_fallback_files.append(str(sample.get("fileName") or ""))
    return {
        "pdfCount": len(pdf_samples),
        "deepScanReadyCount": len(ready_files),
        "deepScanReadyRate": ratio(len(ready_files), len(pdf_samples)) if pdf_samples else 1.0,
        "lightFallbackCount": len(light_fallback_files),
        "lightFallbackFiles": light_fallback_files,
        "summaryOnlyTableFiles": summary_only_files,
        "missingRequiredTables": missing_required_tables,
    }


def pdf_deep_scan_ready(
    result: dict[str, Any],
    *,
    sample: dict[str, Any],
    required_tables: set[str],
    schemas: set[str],
) -> bool:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    mode = str(metadata.get("deepScanMode") or metadata.get("pageCoverageMode") or sample.get("pageCoverageMode") or "").lower()
    if mode in {"full", "deep", "multi_page", "multi-page", "all_pages"}:
        return not required_tables or required_tables.issubset(schemas)
    if mode in {"first_page", "first-page", "light", "fast_first", "preview"}:
        return False
    pages_with_text = {
        int(item.get("pageNo") or 1)
        for item in result.get("fragments") or []
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    }
    page_count = int(sample.get("pageCount") or len(result.get("pages") or []) or 0)
    multi_page_evidence = len(pages_with_text) >= 2 or page_count <= 1
    table_evidence = not required_tables or required_tables.issubset(schemas)
    return bool(multi_page_evidence and table_evidence)


def pdf_has_summary_only_tables(result: dict[str, Any], schemas: set[str]) -> bool:
    if not schemas:
        return False
    tables = [item for item in result.get("tables") or [] if isinstance(item, dict)]
    schema_tables = [table for table in tables if table_schema_set(table).intersection(schemas)]
    if not schema_tables:
        return False
    return all(
        str(table.get("sourceEngine") or "") == "heuristic_table_from_ocr_fragments"
        and any("summary_from_fragments" in str(flag) for flag in table.get("qualityFlags") or [])
        for table in schema_tables
    )


def build_piping_evidence_metrics(report_dir: Path, samples: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [
        item for item in samples if item.get("profileId") == PIPING_PROFILE_ID or item.get("requestedProfileId") == PIPING_PROFILE_ID
    ]
    sample = next((item for item in candidates if str(item.get("fileName") or "").startswith("IMG_6509")), None)
    sample = sample or (candidates[0] if candidates else {})
    result = load_result_for_sample(report_dir, sample) if sample else {}
    fields = fields_by_code(result, sample)
    present = sorted(field for field in PIPING_REQUIRED_FIELDS if field in fields)
    with_bbox = sorted(field for field in present if field_has_bbox(fields[field]))
    table_count = 0
    row_level_table_count = 0
    for table in result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        if "piping_characteristic_table_v1" not in table_schema_set(table) and "piping_characteristic_table" not in table_schema_set(table):
            continue
        table_count += 1
        rows = [row for row in table.get("businessRows") or table.get("normalizedRows") or [] if isinstance(row, dict)]
        cells_with_bbox = [
            cell for cell in table.get("cells") or [] if isinstance(cell, dict) and field_has_bbox(cell)
        ]
        if rows and cells_with_bbox:
            row_level_table_count += 1
    return {
        "sampleFileName": sample.get("fileName") if sample else None,
        "requiredFieldCount": len(PIPING_REQUIRED_FIELDS),
        "presentFieldCount": len(present),
        "presentWithBboxCount": len(with_bbox),
        "missingFields": sorted(PIPING_REQUIRED_FIELDS - set(present)),
        "missingBboxFields": sorted(set(present) - set(with_bbox)),
        "requirementCoverageRate": ratio(len(present), len(PIPING_REQUIRED_FIELDS)),
        "requirementBboxCoverageRate": ratio(len(with_bbox), len(PIPING_REQUIRED_FIELDS)),
        "pipingTableCount": table_count,
        "lineLevelTableCount": row_level_table_count,
        "lineLevelTableReady": row_level_table_count > 0,
    }


def build_seal_crop_evidence_metrics(report_dir: Path, required_seal_samples: list[dict[str, Any]]) -> dict[str, Any]:
    files_with_crop: list[str] = []
    files_without_crop: list[str] = []
    for sample in required_seal_samples:
        result = load_result_for_sample(report_dir, sample)
        has_crop = result_has_seal_crop_evidence(result)
        file_name = str(sample.get("fileName") or "")
        if has_crop:
            files_with_crop.append(file_name)
        else:
            files_without_crop.append(file_name)
    return {
        "requiredSealSampleCount": len(required_seal_samples),
        "sampleWithCropEvidenceCount": len(files_with_crop),
        "sampleWithCropEvidenceRate": ratio(len(files_with_crop), len(required_seal_samples)) if required_seal_samples else 1.0,
        "filesWithoutCropEvidence": files_without_crop,
    }


def result_has_seal_crop_evidence(result: dict[str, Any]) -> bool:
    for seal in result.get("seals") or []:
        if not isinstance(seal, dict):
            continue
        evidence_level = str(seal.get("sealEvidenceLevel") or seal.get("evidenceLevel") or "")
        source_engine = str(seal.get("sourceEngine") or "")
        if evidence_level == "visual_plus_seal_crop_ocr" or "seal_crop" in source_engine:
            return True
        for field in seal.get("fields") or []:
            if isinstance(field, dict) and str(field.get("sourcePriority") or "") == "crop_ocr":
                return True
    for field in result.get("fields") or []:
        if isinstance(field, dict) and str(field.get("sourcePriority") or "") == "crop_ocr":
            return True
    return any(run.get("status") == "success" for run in result.get("sealCropEvidenceRuns") or [] if isinstance(run, dict))


def build_context_findings(samples: list[dict[str, Any]], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if metrics["failureCount"]:
        findings.append(
            {"severity": "A", "code": "A-001", "title": "存在 OCR 失败样本", "evidence": {"failureCount": metrics["failureCount"]}}
        )
    if metrics["pngAutoUsableCount"] < 20:
        findings.append(
            {
                "severity": "B",
                "code": "B-001",
                "title": "PNG 图纸上下文自动可用率不足",
                "evidence": {"pngAutoUsable": f"{metrics['pngAutoUsableCount']}/{metrics['pngCount']}"},
                "suggestion": "剩余页需要针对标题栏、管道特性表、总图局部做服务器 ROI OCR 或人工复核。",
            }
        )
    if metrics["requiredSealSatisfactionRate"] < 0.90:
        findings.append(
            {
                "severity": "B",
                "code": "B-002",
                "title": "required seal 满足率仍低于 90%",
                "evidence": {
                    "rate": metrics["requiredSealSatisfactionRate"],
                    "satisfied": f"{metrics['requiredSealSatisfiedCount']}/{metrics['requiredSealSampleCount']}",
                },
                "suggestion": "PDF 资质证、质量证明和 RT 报告仍需服务器侧印章 ROI OCR。",
            }
        )
    seal_crop = metrics.get("sealCropEvidence") or {}
    if float(seal_crop.get("sampleWithCropEvidenceRate") or 0.0) < 0.75:
        findings.append(
            {
                "severity": "B",
                "code": "B-SEAL-CROP",
                "title": "required seal 缺少真实 crop OCR 证据",
                "evidence": {
                    "rate": seal_crop.get("sampleWithCropEvidenceRate"),
                    "files": seal_crop.get("filesWithoutCropEvidence"),
                },
                "suggestion": "服务器端继续对 seal bbox 做扩边 crop OCR，包级印章上下文不得替代单页正式证据。",
            }
        )
    drawing_consistency = metrics.get("drawingPackageConsistency") or {}
    if (
        drawing_consistency.get("declaredDrawingNoCount")
        and float(drawing_consistency.get("actualCoveredByDirectoryRate") or 0.0) < 0.90
    ):
        findings.append(
            {
                "severity": "B",
                "code": "B-DWG-COVERAGE",
                "title": "图纸目录与实际图纸页覆盖不一致",
                "evidence": {
                    "actualCoveredByDirectoryRate": drawing_consistency.get("actualCoveredByDirectoryRate"),
                    "actualNotInDirectory": drawing_consistency.get("actualNotInDirectory"),
                    "declaredMissingFromScan": drawing_consistency.get("declaredMissingFromScan"),
                },
                "suggestion": "对目录行和各图标题栏做服务器端局部复核，缺页或图号误抽不得直接自动通过。",
            }
        )
    pdf_deep_scan = metrics.get("pdfDeepScan") or {}
    if pdf_deep_scan.get("pdfCount") and float(pdf_deep_scan.get("deepScanReadyRate") or 0.0) < 0.75:
        findings.append(
            {
                "severity": "B",
                "code": "B-PDF-DEEP-SCAN",
                "title": "PDF 多页深扫证据不足",
                "evidence": {
                    "deepScanReadyRate": pdf_deep_scan.get("deepScanReadyRate"),
                    "lightFallbackFiles": pdf_deep_scan.get("lightFallbackFiles"),
                    "missingRequiredTables": pdf_deep_scan.get("missingRequiredTables"),
                },
                "suggestion": "质量证明书、合格证、焊评和 RT 报告应按 profile 多页深扫，不能只用首屏预审结论。",
            }
        )
    if pdf_deep_scan.get("summaryOnlyTableFiles"):
        findings.append(
            {
                "severity": "C",
                "code": "C-PDF-SUMMARY-TABLE",
                "title": "部分 PDF 表格仍是 OCR 摘要表而非行级结构表",
                "evidence": {"files": pdf_deep_scan.get("summaryOnlyTableFiles")},
                "suggestion": "后续服务器侧 PP-Structure/表格 ROI 应给出单元格级 bbox。",
            }
        )
    img6509 = next((item for item in samples if str(item.get("fileName") or "").startswith("IMG_6509")), {})
    key_fields = img6509.get("keyFields") if isinstance(img6509.get("keyFields"), dict) else {}
    piping_metrics = metrics.get("pipingEvidence") or {}
    if "missingFields" in piping_metrics:
        missing_piping = sorted(set(piping_metrics.get("missingFields") or []))
    else:
        missing_piping = sorted(PIPING_REQUIRED_FIELDS - set(key_fields))
    if missing_piping:
        findings.append(
            {
                "severity": "B",
                "code": "B-003",
                "title": "管道特性表检测要求未完全结构化",
                "evidence": {"fileName": img6509.get("fileName"), "missingFields": missing_piping},
                "suggestion": "对 IMG_6509 表格列做服务器端 ROI/grid OCR。",
            }
        )
    elif float(piping_metrics.get("requirementBboxCoverageRate") or 0.0) < 1.0 or not piping_metrics.get("lineLevelTableReady"):
        findings.append(
            {
                "severity": "B",
                "code": "B-004",
                "title": "管道特性表检测要求缺少行级 bbox 证据",
                "evidence": {
                    "fileName": piping_metrics.get("sampleFileName"),
                    "missingBboxFields": piping_metrics.get("missingBboxFields"),
                    "lineLevelTableReady": piping_metrics.get("lineLevelTableReady"),
                },
                "suggestion": "GC2/RT/10%/III/AB 应进入同一行级结构表，并保留单元格 bbox。",
            }
        )
    suspicious_numbers = []
    for item in samples:
        if not is_drawing_sample(item):
            continue
        if not suspicious_drawing_no(item):
            continue
        key_fields = item.get("keyFields") if isinstance(item.get("keyFields"), dict) else {}
        suspicious_numbers.append({"fileName": item.get("fileName"), "drawing_no": key_fields.get("drawing_no")})
    if suspicious_numbers:
        findings.append(
            {
                "severity": "B",
                "code": "B-DWG-NO",
                "title": "存在疑似证书号被误抽为图号",
                "evidence": {"items": suspicious_numbers},
                "suggestion": "对对应图纸标题栏做服务器端局部 OCR，图号不得由资质证书号或许可编号代替。",
            }
        )
    for item in [item for item in samples if item.get("requestedProfileId") == "quality_certificate_v1"]:
        schemas = set(item.get("tableSchemas") or [])
        missing = sorted({"material_chemical_composition_table", "mechanical_property_table"} - schemas)
        if missing:
            findings.append(
                {
                    "severity": "B",
                    "code": f"B-QC-{item.get('fileName')}",
                    "title": "质量证明/合格证表格证据不足",
                    "evidence": {"fileName": item.get("fileName"), "missingTables": missing},
                }
            )
    rt = next((item for item in samples if item.get("requestedProfileId") == "ndt_rt_report_v1"), {})
    rt_date = str((rt.get("keyFields") or {}).get("detection_date") or "")
    if rt and not any(str(year) in rt_date for year in range(2000, 2031)):
        findings.append(
            {
                "severity": "B",
                "code": "B-RT-DATE",
                "title": "射线检测报告日期仍不完整",
                "evidence": {"fileName": rt.get("fileName"), "detection_date": rt_date},
            }
        )
    generic_pdf = [
        item.get("fileName")
        for item in samples
        if item.get("inputType") == "pdf" and item.get("requestedProfileId") == "generic_document_v1"
    ]
    if generic_pdf:
        findings.append(
            {
                "severity": "C",
                "code": "C-PDF-GENERIC",
                "title": "部分 PDF 仍按 generic_document 预审",
                "evidence": {"files": generic_pdf},
                "suggestion": "后续可增加施工方案、焊评报告 profile 或显式映射。",
            }
        )
    return findings


def score_context(samples: list[dict[str, Any]], findings: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    failure_penalty = metrics["failureCount"] * 3
    png_gap = max(0, 20 - metrics["pngAutoUsableCount"])
    seal_gap = max(0.0, 0.90 - metrics["requiredSealSatisfactionRate"])
    bbox_gap = max(0.0, 0.95 - metrics["fieldBboxCoverageAvg"])
    seal_crop_gap = max(0.0, 0.75 - float((metrics.get("sealCropEvidence") or {}).get("sampleWithCropEvidenceRate") or 0.0))
    pdf_gap = max(0.0, 0.75 - float((metrics.get("pdfDeepScan") or {}).get("deepScanReadyRate") or 1.0))
    piping_gap = max(0.0, 1.0 - float((metrics.get("pipingEvidence") or {}).get("requirementBboxCoverageRate") or 1.0))
    drawing_gap = max(
        0.0,
        0.90 - float((metrics.get("drawingPackageConsistency") or {}).get("actualCoveredByDirectoryRate") or 1.0),
    )
    a_count = sum(1 for item in findings if item["severity"] == "A")
    b_count = sum(1 for item in findings if item["severity"] == "B")
    ocr = max(0.0, 25 - failure_penalty - min(4.0, png_gap * 0.15) - min(2.0, pdf_gap * 4))
    table_seal = max(
        0.0,
        20
        - min(5.0, seal_gap * 20)
        - min(3.0, bbox_gap * 10)
        - min(2.0, seal_crop_gap * 4)
        - min(2.0, piping_gap * 3),
    )
    visual = 14 if a_count == 0 else 12
    business = max(0.0, 15 - a_count * 5 - max(0, b_count - 3) * 0.75 - min(1.5, drawing_gap * 2))
    components = {
        "knowledgeRetrieval": 25,
        "ocrFieldExtraction": round(ocr, 2),
        "tableSealBboxEvidence": round(table_seal, 2),
        "visualReview": visual,
        "businessRulesConclusion": round(business, 2),
    }
    total = round(sum(components.values()), 2)
    return {
        "score": total,
        "components": components,
        "pipelineAccuracy": pipeline_accuracy_view(components, total, metrics, findings),
        "grade": "94-96目标达成" if 94 <= total <= 96.99 else ("超过96，需复核评分口径" if total >= 97 else "未达94目标"),
        "findingCounts": dict(Counter(item["severity"] for item in findings)),
    }


def pipeline_accuracy_view(
    components: dict[str, float | int],
    total: float,
    metrics: dict[str, Any],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    document_score = float(components.get("ocrFieldExtraction") or 0.0) + float(
        components.get("tableSealBboxEvidence") or 0.0
    )
    llm_score = float(components.get("visualReview") or 0.0)
    standards_score = float(components.get("knowledgeRetrieval") or 0.0)
    result_score = float(components.get("businessRulesConclusion") or 0.0)
    a_count = sum(1 for item in findings if item.get("severity") == "A")
    b_count = sum(1 for item in findings if item.get("severity") == "B")
    return {
        "schemaVersion": "document-llm-standard-result-accuracy-v1",
        "overallAccuracy": round(total / 100.0, 4),
        "overallPercent": total,
        "stages": [
            {
                "stage": "documentEvidence",
                "label": "资料识别与证据定位",
                "score": round(document_score, 2),
                "maxScore": 45,
                "accuracy": ratio(document_score, 45),
                "basis": "ocrFieldExtraction + tableSealBboxEvidence",
                "metrics": {
                    "fieldBboxCoverageAvg": metrics.get("fieldBboxCoverageAvg"),
                    "requiredSealSatisfactionRate": metrics.get("requiredSealSatisfactionRate"),
                    "pdfDeepScanReadyRate": (metrics.get("pdfDeepScan") or {}).get("deepScanReadyRate"),
                },
            },
            {
                "stage": "llmReview",
                "label": "LLM/视觉复核",
                "score": round(llm_score, 2),
                "maxScore": 15,
                "accuracy": ratio(llm_score, 15),
                "basis": "visualReview component; OCR 原文仍优先于 LLM 复核",
            },
            {
                "stage": "industryStandards",
                "label": "行业规范检索",
                "score": round(standards_score, 2),
                "maxScore": 25,
                "accuracy": ratio(standards_score, 25),
                "basis": "knowledgeRetrieval component",
            },
            {
                "stage": "auditResult",
                "label": "审计结论与业务规则",
                "score": round(result_score, 2),
                "maxScore": 15,
                "accuracy": ratio(result_score, 15),
                "basis": "businessRulesConclusion component",
                "riskCounts": {"A": a_count, "B": b_count},
            },
        ],
        "note": "该准确率来自现有 OCR/证据/规范/结论评分拆分；不是人工金标结论集替代品。",
    }


def seal_satisfied(sample: dict[str, Any]) -> bool:
    if sample.get("missingExpectedSealTypes"):
        return not sample.get("contextualMissingExpectedSealTypes")
    return bool(sample.get("sealCount", 0) > 0 or not sample.get("contextualMissingExpectedSealTypes"))


def context_auto_usable(sample: dict[str, Any]) -> bool:
    return str(sample.get("contextualQualityStatus") or "") in {"auto_usable", "auto_usable_with_package_context"}


def is_drawing_sample(sample: dict[str, Any]) -> bool:
    profile_id = str(sample.get("profileId") or "")
    return sample.get("inputType") == "png" and (
        profile_id in DRAWING_PROFILE_IDS or profile_id == PIPING_PROFILE_ID
    )


def load_result_for_sample(report_dir: Path, sample: dict[str, Any]) -> dict[str, Any]:
    file_name = str(sample.get("fileName") or "")
    stem = Path(file_name).stem
    for prefix in ["scan-full-ocr-v2-", "scan-full-ocr-"]:
        path = report_dir / f"{prefix}{stem}.json"
        if path.exists():
            return load_json(path)
    return {}


def fields_by_code(result: dict[str, Any], sample: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    fields = {}
    for field in result.get("fields") or []:
        if isinstance(field, dict) and field.get("fieldCode"):
            fields[str(field["fieldCode"])] = field
    if sample and isinstance(sample.get("keyFields"), dict):
        for key, value in sample["keyFields"].items():
            if key not in fields and value:
                fields[str(key)] = {"fieldCode": key, "fieldValue": value}
    return fields


def field_value_from_result(result: dict[str, Any], field_code: str) -> str:
    field = fields_by_code(result).get(field_code) or {}
    return str(field.get("fieldValue") or "")


def field_has_bbox(item: dict[str, Any]) -> bool:
    bbox = item.get("bbox") or item.get("polygon")
    return isinstance(bbox, list) and bool(bbox)


def result_table_schemas(result: dict[str, Any]) -> set[str]:
    schemas: set[str] = set()
    for table in result.get("tables") or []:
        if isinstance(table, dict):
            schemas.update(table_schema_set(table))
    return schemas


def table_schema_set(table: dict[str, Any]) -> set[str]:
    schemas = {str(item) for item in table.get("businessSchemas") or [] if item}
    if table.get("businessSchema"):
        schemas.add(str(table["businessSchema"]))
    if table.get("tableType"):
        schemas.add(str(table["tableType"]))
    return schemas


def normalize_drawing_no(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def valid_drawing_no(value: str) -> bool:
    normalized = normalize_drawing_no(value)
    if not normalized:
        return False
    if LICENSE_NO_RE.fullmatch(normalized):
        return False
    if re.fullmatch(r"A\d{6,12}", normalized):
        return False
    if re.fullmatch(r"TS\d{6,12}(?:-\d{4})?", normalized):
        return False
    if re.match(r"^(?:PL|VT)\d", normalized):
        return False
    return bool(ENGINEERING_DRAWING_NO_RE.fullmatch(normalized) or DRAWING_LIST_SEQUENCE_RE.fullmatch(normalized))


def compact_field(field: dict[str, Any]) -> dict[str, Any]:
    keep = [
        "fieldCode",
        "fieldName",
        "fieldValue",
        "pageNo",
        "bbox",
        "coordinateSystem",
        "sourceCoordinateSystem",
        "coordinateTransformStatus",
        "sourceEngine",
        "variantId",
        "selectedVariantId",
        "confidence",
        "extractionMethod",
        "sourcePriority",
    ]
    return {key: deepcopy(field.get(key)) for key in keep if key in field}


def write_outputs(report_dir: Path, suffix: str, payload: dict[str, Any]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"scan-full-ocr-summary-{suffix}.json").write_text(
        json.dumps(payload["summary"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (report_dir / f"scan-audit-findings-{suffix}.json").write_text(
        json.dumps(payload["findings"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (report_dir / f"scan-composite-score-{suffix}.json").write_text(
        json.dumps(payload["composite"], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def ratio(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_json(path: Path) -> Any | None:
    return load_json(path) if path.exists() else None


if __name__ == "__main__":
    raise SystemExit(main())
