from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from io import StringIO
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ocr_100_corpus import OCR_100_SCENARIO_TARGETS, scenario_target_gaps
from scripts.ocr_eval_set import write_text_file


SCENARIO_KEYWORDS: dict[str, list[str]] = {
    "piping_table_profile": ["管道特性表", "piping characteristic", "pipe no", "管线号", "管道号", "p&id"],
    "quality_certificate_profile": ["质量证明", "产品质量", "质量证书", "合格证", "炉批号", "材料牌号", "化学成分", "力学性能"],
    "ndt_rt_profile": ["射线检测", "rt报告", "radiographic", "底片", "评片", "rt ", "检测比例"],
    "ndt_ut_profile": ["超声检测", "ut报告", "ultrasonic", "探头", "扫查", "ut "],
    "construction_record_profile": ["施工记录", "交工", "施工方案", "隐蔽工程", "安装记录", "验收记录"],
    "welding_record_profile": ["焊接工艺评定", "焊接记录", "wps", "pqr", "焊接作业", "焊口"],
    "qualification_certificate_profile": ["许可证", "资质", "许可范围", "证书编号", "有效期", "发证", "特种设备"],
    "seal_text_profile": ["印章", "专用章", "公章", "seal"],
    "fragment_seal_profile": ["出图专用章", "设计许可印章", "压力管道", "ts181"],
    "evidence_profile": ["管道壁厚计算书", "计算书", "设计图纸", "drawing", "设计阶段", "图名"],
    "quality_gate_profile": ["折痕", "低对比", "模糊", "遮挡", "倾斜", "fold", "blur"],
}

DESIGN_CALCULATION_CUES = ["管道壁厚计算书", "强度计算", "设计许可印章", "出图专用章", "图名", "drawing no"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit OCR 100 Scan sample scenario labels against OCR/text cues.")
    parser.add_argument("sample_source", help="scan_sample_queue.json, scan manifest JSON, or annotation task JSON.")
    parser.add_argument("--result-dir", action="append", default=[], help="Directory containing OCR result JSON files keyed by caseId.")
    parser.add_argument("--output", help="Optional JSON audit report path.")
    parser.add_argument("--csv-output", help="Optional CSV audit report path.")
    parser.add_argument("--markdown-output", help="Optional Markdown audit report path.")
    parser.add_argument("--mismatch-threshold", type=float, default=2.0, help="Minimum score gap to flag scenario mismatch.")
    args = parser.parse_args()

    report = build_manifest_audit_report(
        Path(args.sample_source),
        result_dirs=[Path(item) for item in args.result_dir],
        mismatch_threshold=float(args.mismatch_threshold),
    )
    if args.output:
        write_text_file(Path(args.output), json.dumps(report, ensure_ascii=False, indent=2))
    if args.csv_output:
        write_text_file(Path(args.csv_output), manifest_audit_csv(report))
    if args.markdown_output:
        write_text_file(Path(args.markdown_output), manifest_audit_markdown(report))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


def build_manifest_audit_report(
    sample_source: Path,
    *,
    result_dirs: list[Path] | None = None,
    mismatch_threshold: float = 2.0,
) -> dict[str, Any]:
    payload = json.loads(sample_source.expanduser().read_text(encoding="utf-8"))
    samples = load_samples(payload)
    result_dirs = [path.expanduser().resolve() for path in result_dirs or []]
    items = [audit_sample(sample, result_dirs=result_dirs, mismatch_threshold=mismatch_threshold) for sample in samples]
    declared_counts = Counter(str(item.get("declaredScenario") or "unspecified") for item in items)
    suggested_counts = Counter(str(item.get("suggestedScenario") or "unspecified") for item in items if item.get("suggestedScenario"))
    mismatch_items = [item for item in items if item.get("status") == "mismatch"]
    missing_ocr = [item for item in items if not item.get("ocrTextAvailable")]
    return {
        "schemaVersion": "aicheck-ocr-100-manifest-audit-v1",
        "source": str(sample_source),
        "summary": {
            "samples": len(items),
            "mismatches": len(mismatch_items),
            "missingOcrText": len(missing_ocr),
            "declaredScenarioCounts": dict(sorted(declared_counts.items())),
            "suggestedScenarioCounts": dict(sorted(suggested_counts.items())),
            "declaredTargetGaps": scenario_target_gaps(declared_counts),
            "suggestedTargetGaps": scenario_target_gaps(suggested_counts),
        },
        "items": items,
    }


def load_samples(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        raw_samples = payload.get("cases") or payload.get("tasks") or payload.get("samples") or []
    else:
        raw_samples = payload
    samples: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_samples if isinstance(raw_samples, list) else []):
        if not isinstance(raw, dict):
            continue
        source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
        samples.append(
            {
                "caseId": raw.get("caseId") or raw.get("taskId") or f"sample-{index + 1:03d}",
                "fileName": raw.get("fileName") or source.get("fileName") or Path(str(raw.get("sourcePath") or source.get("path") or "")).name,
                "sourcePath": raw.get("sourcePath") or source.get("path"),
                "declaredScenario": raw.get("scenario"),
                "profileId": raw.get("profileId"),
                "documentType": raw.get("documentType"),
                "notes": raw.get("notes") or source.get("notes"),
            }
        )
    return samples


def audit_sample(sample: dict[str, Any], *, result_dirs: list[Path], mismatch_threshold: float) -> dict[str, Any]:
    case_id = str(sample.get("caseId") or "")
    declared = str(sample.get("declaredScenario") or "unspecified")
    result, result_path = load_ocr_result(case_id, result_dirs)
    ocr_text = result_text(result) if result else ""
    text = "\n".join(
        str(value or "")
        for value in [sample.get("fileName"), sample.get("sourcePath"), sample.get("notes"), sample.get("profileId"), sample.get("documentType"), ocr_text]
    )
    scores = scenario_scores(text)
    suggested, score = best_scenario(scores)
    declared_score = float(scores.get(declared, 0.0))
    score_gap = round(float(score) - declared_score, 4)
    status = "ok"
    if suggested and suggested != declared and score_gap >= mismatch_threshold:
        status = "mismatch"
    elif not suggested:
        status = "uncertain"
    return {
        **sample,
        "declaredScenario": declared,
        "suggestedScenario": suggested,
        "status": status,
        "score": score,
        "declaredScore": declared_score,
        "scoreGap": score_gap,
        "ocrTextAvailable": bool(ocr_text.strip()),
        "ocrResultPath": str(result_path) if result_path else None,
        "matchedKeywords": matched_keywords(text),
        "topScores": dict(sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:5]),
        "reviewRequired": status == "mismatch" or not ocr_text.strip(),
    }


def load_ocr_result(case_id: str, result_dirs: list[Path]) -> tuple[dict[str, Any] | None, Path | None]:
    safe = safe_name(case_id)
    for result_dir in result_dirs:
        for candidate in [result_dir / f"{case_id}.json", result_dir / f"{safe}.json"]:
            if not candidate.is_file():
                continue
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
            return payload if isinstance(payload, dict) else None, candidate
    return None, None


def result_text(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for fragment in result.get("fragments") or []:
        if isinstance(fragment, dict):
            parts.append(str(fragment.get("text") or ""))
    for field in result.get("fields") or []:
        if isinstance(field, dict):
            parts.extend([str(field.get("fieldName") or ""), str(field.get("fieldCode") or ""), str(field.get("fieldValue") or field.get("value") or "")])
    for seal in result.get("seals") or []:
        if isinstance(seal, dict):
            parts.extend([str(seal.get("sealType") or ""), str(seal.get("sealName") or seal.get("nameContains") or "")])
    for table in result.get("tables") or []:
        if isinstance(table, dict):
            parts.extend([str(table.get("tableId") or ""), str(table.get("businessSchema") or "")])
            for row in table.get("normalizedRows") or []:
                if isinstance(row, dict):
                    parts.extend(str(value) for value in row.values())
    return "\n".join(item for item in parts if item)


def scenario_scores(text: str) -> dict[str, float]:
    lowered = text.lower()
    scores: dict[str, float] = {}
    for scenario, keywords in SCENARIO_KEYWORDS.items():
        score = 0.0
        for keyword in keywords:
            if keyword.lower() in lowered:
                score += 1.0
        scores[scenario] = score
    if all(cue.lower() in lowered for cue in ["管道", "计算书"]):
        scores["evidence_profile"] += 2.0
    if any(cue.lower() in lowered for cue in DESIGN_CALCULATION_CUES):
        scores["quality_certificate_profile"] -= 1.5
        scores["evidence_profile"] += 2.0
        scores["fragment_seal_profile"] += 1.0
    return scores


def best_scenario(scores: dict[str, float]) -> tuple[str | None, float]:
    if not scores:
        return None, 0.0
    scenario, score = max(scores.items(), key=lambda item: (item[1], item[0]))
    return (scenario, float(score)) if score > 0 else (None, 0.0)


def matched_keywords(text: str) -> dict[str, list[str]]:
    lowered = text.lower()
    output: dict[str, list[str]] = {}
    for scenario, keywords in SCENARIO_KEYWORDS.items():
        matched = [keyword for keyword in keywords if keyword.lower() in lowered]
        if matched:
            output[scenario] = matched
    return output


def manifest_audit_csv(report: dict[str, Any]) -> str:
    fieldnames = [
        "status",
        "caseId",
        "fileName",
        "declaredScenario",
        "suggestedScenario",
        "score",
        "declaredScore",
        "scoreGap",
        "ocrTextAvailable",
        "ocrResultPath",
    ]
    handle = StringIO()
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    for item in report.get("items") or []:
        writer.writerow({key: item.get(key) for key in fieldnames})
    return handle.getvalue()


def manifest_audit_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# OCR 100 Scan Manifest Audit",
        "",
        f"- Samples: {summary.get('samples', 0)}",
        f"- Mismatches: {summary.get('mismatches', 0)}",
        f"- Missing OCR text: {summary.get('missingOcrText', 0)}",
        "",
        "| Status | Case | File | Declared | Suggested | Score Gap |",
        "| --- | --- | --- | --- | --- | ---: |",
    ]
    for item in report.get("items") or []:
        if item.get("status") == "ok":
            continue
        lines.append(
            f"| {item.get('status')} | {item.get('caseId')} | {item.get('fileName')} | "
            f"{item.get('declaredScenario')} | {item.get('suggestedScenario')} | {item.get('scoreGap')} |"
        )
    lines.append("")
    return "\n".join(lines)


def safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


if __name__ == "__main__":
    raise SystemExit(main())
