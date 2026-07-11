from __future__ import annotations

import argparse
import json
import random
import statistics
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any


GROUPS = (
    "baseline",
    "paddle_vl_fusion",
    "nuextract_direct",
    "hybrid",
    "paddle_text_nuextract",
)


def normalize_value(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).upper()
    return "".join(character for character in normalized if not character.isspace())


def normalize_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) < 4:
        return None
    try:
        x1, y1, x2, y2 = [float(value[index]) for index in range(4)]
    except (TypeError, ValueError):
        return None
    return [x1, y1, x2, y2] if x2 > x1 and y2 > y1 else None


def bbox_iou(left: Any, right: Any) -> float | None:
    left_bbox = normalize_bbox(left)
    right_bbox = normalize_bbox(right)
    if not left_bbox or not right_bbox:
        return None
    x1, y1 = max(left_bbox[0], right_bbox[0]), max(left_bbox[1], right_bbox[1])
    x2, y2 = min(left_bbox[2], right_bbox[2]), min(left_bbox[3], right_bbox[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    left_area = (left_bbox[2] - left_bbox[0]) * (left_bbox[3] - left_bbox[1])
    right_area = (right_bbox[2] - right_bbox[0]) * (right_bbox[3] - right_bbox[1])
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def fields_by_code(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    raw_fields = payload.get("fields") if isinstance(payload.get("fields"), (dict, list)) else payload
    output: dict[str, dict[str, Any]] = {}
    if isinstance(raw_fields, dict):
        for field_code, value in raw_fields.items():
            if isinstance(value, dict):
                output[str(field_code)] = value
            elif not isinstance(value, list):
                output[str(field_code)] = {"value": value}
    elif isinstance(raw_fields, list):
        for field in raw_fields:
            if not isinstance(field, dict):
                continue
            field_code = field.get("fieldCode") or field.get("fieldName") or field.get("name")
            if field_code:
                output[str(field_code)] = field
    return output


def field_value(field: dict[str, Any]) -> Any:
    for key in ["value", "fieldValue", "text", "result"]:
        if key in field:
            return field.get(key)
    return None


def normalized_table_units(payload: Any) -> tuple[Counter[str], Counter[str]]:
    if not isinstance(payload, dict):
        return Counter(), Counter()
    raw_tables = payload.get("tables")
    if not isinstance(raw_tables, (dict, list)):
        return Counter(), Counter()
    tables = raw_tables.items() if isinstance(raw_tables, dict) else enumerate(raw_tables)
    row_units: Counter[str] = Counter()
    cell_units: Counter[str] = Counter()
    ignored_keys = {
        "sourceCandidateIds",
        "rawSourceCandidateIds",
        "evidenceBbox",
        "bbox",
        "evidencePageNo",
        "pageNo",
        "confidence",
        "attributionStatus",
        "advisoryOnly",
    }
    for table_key, table_value in tables:
        table_name = str(table_key)
        if isinstance(table_value, dict):
            table_name = str(
                table_value.get("tableCode")
                or table_value.get("tableName")
                or table_value.get("name")
                or table_key
            )
            rows = table_value.get("rows") or table_value.get("items") or [table_value]
        else:
            rows = table_value
        if not isinstance(rows, list):
            continue
        for row_index, row in enumerate(rows):
            cells = row.get("cells") if isinstance(row, dict) and isinstance(row.get("cells"), (dict, list)) else row
            values: list[tuple[str, str]] = []
            if isinstance(cells, dict):
                for cell_key, cell in cells.items():
                    if str(cell_key) in ignored_keys:
                        continue
                    raw_value = field_value(cell) if isinstance(cell, dict) else cell
                    normalized = normalize_value(raw_value)
                    if normalized:
                        values.append((str(cell_key), normalized))
            elif isinstance(cells, list):
                for cell_index, cell in enumerate(cells):
                    if isinstance(cell, dict):
                        cell_key = str(
                            cell.get("fieldCode")
                            or cell.get("fieldName")
                            or cell.get("name")
                            or cell.get("col")
                            or cell_index
                        )
                        raw_value = field_value(cell)
                    else:
                        cell_key = str(cell_index)
                        raw_value = cell
                    normalized = normalize_value(raw_value)
                    if normalized:
                        values.append((cell_key, normalized))
            if not values:
                continue
            row_signature = "|".join(f"{key}={value}" for key, value in sorted(values))
            row_units[f"{table_name}|{row_signature}"] += 1
            for cell_key, normalized in values:
                cell_units[f"{table_name}|{cell_key}|{normalized}"] += 1
    return row_units, cell_units


def counter_match_counts(expected: Counter[str], actual: Counter[str]) -> tuple[int, int, int]:
    true_positive = sum((expected & actual).values())
    return true_positive, sum(actual.values()) - true_positive, sum(expected.values()) - true_positive


def f1_score(true_positive: int, false_positive: int, false_negative: int) -> float | None:
    denominator = 2 * true_positive + false_positive + false_negative
    return (2 * true_positive / denominator) if denominator else None


def reviewed_gold(case: dict[str, Any]) -> bool:
    gold = case.get("gold") if isinstance(case.get("gold"), dict) else {}
    reviewers = {str(item) for item in gold.get("reviewers") or [] if str(item).strip()}
    return gold.get("approved") is True and len(reviewers) >= 2


def gold_fields(case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    gold = case.get("gold") if isinstance(case.get("gold"), dict) else {}
    fields = gold.get("fields")
    if isinstance(fields, dict):
        return {
            str(code): value if isinstance(value, dict) else {"value": value}
            for code, value in fields.items()
        }
    return fields_by_code({"fields": fields or []})


def case_group_score(case: dict[str, Any], group: str) -> dict[str, Any]:
    gold = gold_fields(case)
    prediction = ((case.get("predictions") or {}).get(group)) if isinstance(case.get("predictions"), dict) else None
    prediction = prediction if isinstance(prediction, dict) else {}
    structured = prediction.get("structuredOutput") if prediction.get("structuredOutput") is not None else prediction.get("output")
    predicted = fields_by_code(structured)
    correct = 0
    page_correct = 0
    page_total = 0
    bbox_correct = 0
    bbox_total = 0
    bbox_ious: list[float] = []
    field_code_stats: dict[str, dict[str, int]] = {}
    for code, expected in gold.items():
        actual = predicted.get(code) or {}
        field_matches = normalize_value(field_value(expected)) == normalize_value(field_value(actual))
        field_code_stats[code] = {"correct": int(field_matches), "total": 1}
        if field_matches:
            correct += 1
        expected_page = expected.get("pageNo")
        actual_page = actual.get("evidencePageNo") or actual.get("pageNo")
        if expected_page is not None:
            page_total += 1
            page_correct += int(str(expected_page) == str(actual_page))
        iou = bbox_iou(expected.get("bbox"), actual.get("evidenceBbox") or actual.get("bbox"))
        if normalize_bbox(expected.get("bbox")):
            bbox_total += 1
            bbox_correct += int(iou is not None and iou >= 0.5)
        if iou is not None:
            bbox_ious.append(iou)
    predicted_nonempty_codes = {
        code for code, field in predicted.items() if normalize_value(field_value(field))
    }
    false_positive_codes = sorted(predicted_nonempty_codes - set(gold))
    attribution = prediction.get("attributionValidation") if isinstance(prediction.get("attributionValidation"), dict) else {}
    status_counts = attribution.get("statusCounts") if isinstance(attribution.get("statusCounts"), dict) else {}
    unsupported_count = int(status_counts.get("unsupported") or 0)
    explicit_unsupported_codes = {
        code
        for code, field in predicted.items()
        if code in predicted_nonempty_codes and field.get("attributionStatus") in {"unsupported", "advisory_only"}
    }
    hallucinated_codes = set(false_positive_codes) | explicit_unsupported_codes
    hallucination_count = len(hallucinated_codes) + max(0, unsupported_count - len(explicit_unsupported_codes))
    invalid_candidate_count = int(attribution.get("invalidCandidateIdCount") or 0)
    expected_rows, expected_cells = normalized_table_units({"tables": (case.get("gold") or {}).get("tables") or {}})
    actual_rows, actual_cells = normalized_table_units(structured)
    table_row_tp, table_row_fp, table_row_fn = counter_match_counts(expected_rows, actual_rows)
    table_cell_tp, table_cell_fp, table_cell_fn = counter_match_counts(expected_cells, actual_cells)
    gold_count = len(gold)
    selected_pages = prediction.get("selectedPageNos") if isinstance(prediction.get("selectedPageNos"), list) else []
    try:
        page_count = max(1, int(case.get("pageCount") or len(selected_pages) or 1))
    except (TypeError, ValueError):
        page_count = 1
    return {
        "caseId": case.get("caseId"),
        "available": bool(prediction),
        "jsonValid": prediction.get("jsonValid") is not False and isinstance(structured, (dict, list)),
        "fieldCorrect": correct,
        "fieldTotal": gold_count,
        "fieldAccuracy": correct / gold_count if gold_count else None,
        "fieldCodeStats": field_code_stats,
        "pageCorrect": page_correct,
        "pageTotal": page_total,
        "bboxCorrect": bbox_correct,
        "bboxTotal": bbox_total,
        "bboxIous": bbox_ious,
        "tableRowTp": table_row_tp,
        "tableRowFp": table_row_fp,
        "tableRowFn": table_row_fn,
        "tableCellTp": table_cell_tp,
        "tableCellFp": table_cell_fp,
        "tableCellFn": table_cell_fn,
        "falsePositiveFieldCodes": false_positive_codes,
        "predictedNonemptyFieldCount": len(predicted_nonempty_codes),
        "hallucinationCount": hallucination_count,
        "unsupportedAttributionCount": unsupported_count,
        "invalidCandidateIdCount": invalid_candidate_count,
        "latencyMs": prediction.get("totalTimeMs"),
        "pageCount": page_count,
    }


def aggregate_group(case_scores: list[dict[str, Any]]) -> dict[str, Any]:
    available = [item for item in case_scores if item.get("available")]
    field_total = sum(int(item.get("fieldTotal") or 0) for item in available)
    field_correct = sum(int(item.get("fieldCorrect") or 0) for item in available)
    page_total = sum(int(item.get("pageTotal") or 0) for item in available)
    page_correct = sum(int(item.get("pageCorrect") or 0) for item in available)
    bbox_total = sum(int(item.get("bboxTotal") or 0) for item in available)
    bbox_correct = sum(int(item.get("bboxCorrect") or 0) for item in available)
    bbox_ious = [value for item in available for value in item.get("bboxIous") or []]
    latencies = sorted(float(item["latencyMs"]) for item in available if item.get("latencyMs") is not None)
    p95_latency = latencies[min(len(latencies) - 1, max(0, int(len(latencies) * 0.95) - 1))] if latencies else None
    single_page_latencies = sorted(
        float(item["latencyMs"])
        for item in available
        if item.get("latencyMs") is not None and int(item.get("pageCount") or 1) == 1
    )
    six_page_latencies = sorted(
        float(item["latencyMs"])
        for item in available
        if item.get("latencyMs") is not None and int(item.get("pageCount") or 1) == 6
    )

    def p95(values: list[float]) -> float | None:
        return values[min(len(values) - 1, max(0, int(len(values) * 0.95) - 1))] if values else None

    field_code_totals: dict[str, dict[str, int]] = {}
    for item in available:
        for code, stats in (item.get("fieldCodeStats") or {}).items():
            target = field_code_totals.setdefault(code, {"correct": 0, "total": 0})
            target["correct"] += int(stats.get("correct") or 0)
            target["total"] += int(stats.get("total") or 0)
    macro_scores = [stats["correct"] / stats["total"] for stats in field_code_totals.values() if stats["total"]]
    table_row_tp = sum(int(item.get("tableRowTp") or 0) for item in available)
    table_row_fp = sum(int(item.get("tableRowFp") or 0) for item in available)
    table_row_fn = sum(int(item.get("tableRowFn") or 0) for item in available)
    table_cell_tp = sum(int(item.get("tableCellTp") or 0) for item in available)
    table_cell_fp = sum(int(item.get("tableCellFp") or 0) for item in available)
    table_cell_fn = sum(int(item.get("tableCellFn") or 0) for item in available)
    hallucination_count = sum(int(item.get("hallucinationCount") or 0) for item in available)
    predicted_nonempty_count = sum(int(item.get("predictedNonemptyFieldCount") or 0) for item in available)
    return {
        "availableCases": len(available),
        "jsonSuccessRate": (
            sum(bool(item.get("jsonValid")) for item in available) / len(available) if available else None
        ),
        "fieldExactMatch": field_correct / field_total if field_total else None,
        "fieldMacroAccuracy": statistics.mean(macro_scores) if macro_scores else None,
        "fieldCorrect": field_correct,
        "fieldTotal": field_total,
        "pageAccuracy": page_correct / page_total if page_total else None,
        "bboxAccuracyAtIou50": bbox_correct / bbox_total if bbox_total else None,
        "bboxMeanIou": statistics.mean(bbox_ious) if bbox_ious else None,
        "tableRowF1": f1_score(table_row_tp, table_row_fp, table_row_fn),
        "tableCellF1": f1_score(table_cell_tp, table_cell_fp, table_cell_fn),
        "falsePositiveFieldCount": sum(len(item.get("falsePositiveFieldCodes") or []) for item in available),
        "hallucinationRate": (
            min(1.0, hallucination_count / max(predicted_nonempty_count, hallucination_count))
            if predicted_nonempty_count or hallucination_count
            else 0.0
        ),
        "unsupportedAttributionCount": sum(int(item.get("unsupportedAttributionCount") or 0) for item in available),
        "invalidCandidateIdCount": sum(int(item.get("invalidCandidateIdCount") or 0) for item in available),
        "p95LatencyMs": p95_latency,
        "singlePageP95LatencyMs": p95(single_page_latencies),
        "sixPageP95LatencyMs": p95(six_page_latencies),
    }


def paired_bootstrap_delta(
    baseline_scores: list[dict[str, Any]],
    hybrid_scores: list[dict[str, Any]],
    *,
    iterations: int = 2000,
) -> dict[str, Any]:
    paired = [
        (baseline.get("fieldAccuracy"), hybrid.get("fieldAccuracy"))
        for baseline, hybrid in zip(baseline_scores, hybrid_scores, strict=True)
        if baseline.get("fieldAccuracy") is not None and hybrid.get("fieldAccuracy") is not None
    ]
    if not paired:
        return {"pairedCases": 0, "delta": None, "ci95": None}
    observed = statistics.mean(hybrid - baseline for baseline, hybrid in paired)
    randomizer = random.Random(20260711)
    samples = []
    for _ in range(iterations):
        sample = [paired[randomizer.randrange(len(paired))] for _ in paired]
        samples.append(statistics.mean(hybrid - baseline for baseline, hybrid in sample))
    samples.sort()
    lower = samples[int(iterations * 0.025)]
    upper = samples[min(iterations - 1, int(iterations * 0.975))]
    return {"pairedCases": len(paired), "delta": observed, "ci95": [lower, upper]}


def build_report(manifest: dict[str, Any]) -> dict[str, Any]:
    cases = [item for item in manifest.get("cases") or [] if isinstance(item, dict)]
    reviewed_cases = [item for item in cases if reviewed_gold(item)]
    scores = {
        group: [case_group_score(case, group) for case in reviewed_cases]
        for group in GROUPS
    }
    metrics = {group: aggregate_group(group_scores) for group, group_scores in scores.items()}
    paired = paired_bootstrap_delta(scores["baseline"], scores["hybrid"])
    blockers = []
    if len(reviewed_cases) < 30:
        blockers.append("DOUBLE_REVIEWED_GOLD_BELOW_30")
    if len(reviewed_cases) < 150:
        blockers.append("PILOT_CASES_BELOW_150")
    if any(metrics[group]["availableCases"] < len(reviewed_cases) for group in GROUPS):
        blockers.append("FIVE_GROUP_PREDICTIONS_INCOMPLETE")
    hybrid = metrics["hybrid"]
    baseline = metrics["baseline"]
    pilot_gates = {
        "jsonSuccessRateAtLeast995": bool(hybrid.get("jsonSuccessRate") is not None and hybrid["jsonSuccessRate"] >= 0.995),
        "fieldGainAtLeast2Points": bool(
            hybrid.get("fieldExactMatch") is not None
            and baseline.get("fieldExactMatch") is not None
            and hybrid["fieldExactMatch"] - baseline["fieldExactMatch"] >= 0.02
        ),
        "complexTableGainAtLeast5Points": bool(
            hybrid.get("tableCellF1") is not None
            and baseline.get("tableCellF1") is not None
            and hybrid["tableCellF1"] - baseline["tableCellF1"] >= 0.05
        ),
        "pairedCiLowerAboveZero": bool(paired.get("ci95") and paired["ci95"][0] > 0),
        "pageAccuracyAtLeast98": bool(hybrid.get("pageAccuracy") is not None and hybrid["pageAccuracy"] >= 0.98),
        "bboxAccuracyAtLeast98": bool(
            hybrid.get("bboxAccuracyAtIou50") is not None and hybrid["bboxAccuracyAtIou50"] >= 0.98
        ),
        "hallucinationRateAtMost1": bool(
            hybrid.get("hallucinationRate") is not None and hybrid["hallucinationRate"] <= 0.01
        ),
        "invalidCandidateIdsZero": hybrid.get("invalidCandidateIdCount") == 0,
        "singlePageP95AtMost60s": bool(
            hybrid.get("singlePageP95LatencyMs") is not None and hybrid["singlePageP95LatencyMs"] <= 60_000
        ),
        "sixPageP95AtMost180s": bool(
            hybrid.get("sixPageP95LatencyMs") is not None and hybrid["sixPageP95LatencyMs"] <= 180_000
        ),
    }
    gate_blockers = [f"PILOT_GATE_FAILED:{name}" for name, passed in pilot_gates.items() if not passed]
    blockers.extend(gate_blockers)
    ready = not blockers
    return {
        "schemaVersion": "DocumentAiShadowBenchmarkReport@1",
        "status": "pilot_passed" if ready else "blocked",
        "accuracyClaimed": bool(reviewed_cases),
        "reviewedGoldCases": len(reviewed_cases),
        "totalManifestCases": len(cases),
        "groups": metrics,
        "pairedHybridVsBaseline": paired,
        "pilotGates": pilot_gates,
        "blockers": blockers,
        "notes": [
            "Metrics use only cases approved by at least two distinct reviewers.",
            "No field accuracy is reported when no reviewed gold labels exist.",
            "Production enablement still requires profile-specific table and bbox gates.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate five-group Document AI Shadow predictions against reviewed gold labels.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = build_report(manifest)
    raw = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(raw + "\n", encoding="utf-8")
    print(raw)
    return 0 if report["status"] == "pilot_passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
