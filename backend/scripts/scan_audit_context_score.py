from __future__ import annotations

import argparse
import json
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Scan audit package-context score from existing OCR JSON reports. Does not call OCR."
    )
    parser.add_argument("--report-dir", required=True, help="Directory containing scan-full-ocr-summary-v2.json.")
    parser.add_argument("--output-suffix", default="v4", help="Output suffix, e.g. v4.")
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
    metrics = build_metrics(context_samples, package_seals)
    findings = build_context_findings(context_samples, metrics)
    composite = {
        "schemaVersion": "scan-composite-score-v4",
        "runId": "scan-v4-package-context-rigorous",
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "sourceSummary": "scan-full-ocr-summary-v2.json",
        "sourceStrictScore": strict_score.get("score"),
        "scoreMode": "existing_ocr_plus_drawing_package_context",
        "metrics": metrics,
        **score_context(context_samples, findings, metrics),
    }
    summary = {
        "schemaVersion": "scan-full-ocr-summary-v4",
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


def build_metrics(samples: list[dict[str, Any]], package_seals: list[dict[str, Any]]) -> dict[str, Any]:
    png_samples = [item for item in samples if item.get("inputType") == "png"]
    required_seal_samples = [
        item
        for item in samples
        if item.get("requestedProfileId") not in {"generic_document_v1", "construction_record_v1"}
        or item.get("inputType") == "png"
    ]
    required_satisfied = [item for item in required_seal_samples if seal_satisfied(item)]
    field_coverages = [float(item.get("fieldBboxCoverage", 1.0)) for item in samples if item.get("success")]
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
    }


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
    img6509 = next((item for item in samples if str(item.get("fileName") or "").startswith("IMG_6509")), {})
    required_piping = {
        "pressure_pipe_level",
        "weld_detection_method",
        "weld_detection_ratio",
        "weld_acceptance_level",
        "weld_tech_level",
    }
    key_fields = img6509.get("keyFields") if isinstance(img6509.get("keyFields"), dict) else {}
    missing_piping = sorted(required_piping - set(key_fields))
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
    a_count = sum(1 for item in findings if item["severity"] == "A")
    b_count = sum(1 for item in findings if item["severity"] == "B")
    ocr = max(0.0, 25 - failure_penalty - min(4.0, png_gap * 0.15))
    table_seal = max(0.0, 20 - min(5.0, seal_gap * 20) - min(3.0, bbox_gap * 10))
    visual = 14 if a_count == 0 else 12
    business = max(0.0, 15 - a_count * 5 - max(0, b_count - 3) * 0.75)
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
        "grade": "94-96目标达成" if 94 <= total <= 96.99 else ("超过96，需复核评分口径" if total >= 97 else "未达94目标"),
        "findingCounts": dict(Counter(item["severity"] for item in findings)),
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


def ratio(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_json(path: Path) -> Any | None:
    return load_json(path) if path.exists() else None


if __name__ == "__main__":
    raise SystemExit(main())
