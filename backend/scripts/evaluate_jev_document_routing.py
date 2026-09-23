"""Compare Jev document-routing shadows with version-matched inspector labels.

Input is JSONL: one ``jevRoutingShadow`` object per line in --shadows, and one
label object per line in --labels. A label object has projectId, documentId,
documentVersionId, labelSource (inspector or provisional), annotatedBy, and
nodeLabels such as [{"nodeId": 25, "choice": "belongs"}]. Other choices are
does_not_belong and uncertain. Unlabelled nodes are never treated as negatives.

This is offline and read-only. The report contains IDs and counts, never OCR
text, and does not select or approve a production confidence threshold.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

CHOICES = {"yes", "no", "uncertain"}
LABEL_CHOICES = {"belongs", "does_not_belong", "uncertain"}
LABEL_SOURCES = {"inspector", "provisional"}
COMPLETE_STATUSES = {"completed"}
SHADOW_STATUSES = COMPLETE_STATUSES | {
    "partial", "disabled", "invalid_scope", "stale_version", "no_ocr_text", "ocr_not_ready",
    "overlong_document", "no_templates", "request_overlong",
    "request_budget_exceeded", "invalid_response", "unavailable",
}
THRESHOLD_GRID = (0.60, 0.70, 0.80, 0.90, 0.95)


def _version_key(row: dict[str, Any]) -> tuple[str, str, str]:
    key = (str(row.get("projectId") or "").strip(),
           str(row.get("documentId") or "").strip(),
           str(row.get("documentVersionId") or "").strip())
    if any(not value for value in key):
        raise ValueError("project_document_version_required")
    return key


def _case_id(key: tuple[str, str, str]) -> str:
    return "/".join(key)


def _node_id(value: Any) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("positive_integer_node_id_required")
    return value


def _node_ids(value: Any) -> set[int]:
    if not isinstance(value, list):
        raise TypeError("node_id_list_required")
    result = {_node_id(item) for item in value}
    if len(result) != len(value):
        raise ValueError("duplicate_node_id")
    return result


def _shadows(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    output: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("shadow_object_required")
        key = _version_key(row)
        if key in output:
            raise ValueError("duplicate_shadow_version")
        status = row.get("status")
        if status not in SHADOW_STATUSES:
            raise ValueError("invalid_shadow_status")
        scores: dict[int, tuple[str, float]] = {}
        for score in row.get("nodeScores") or []:
            if not isinstance(score, dict):
                raise TypeError("node_score_object_required")
            node = _node_id(score.get("nodeId"))
            if node in scores:
                raise ValueError("duplicate_node_score")
            choice, confidence = score.get("choice"), score.get("confidence")
            if (choice not in CHOICES or type(confidence) not in {int, float}
                    or not math.isfinite(confidence) or not 0 <= confidence <= 1):
                raise ValueError("invalid_node_score")
            scores[node] = (choice, float(confidence))
        if status in COMPLETE_STATUSES and not scores:
            raise ValueError("completed_shadow_without_scores")
        rejected = _node_ids(row.get("humanRejectedNodeIds") or [])
        suggested = _node_ids(row.get("suggestedNodeIds") or [])
        if rejected & suggested:
            raise ValueError("human_rejection_veto_violated")
        output[key] = {"status": status, "scores": scores, "rejected": rejected,
                       "suggested": suggested,
                       "inputHash": str(row.get("inputHash") or ""),
                       "existing": _node_ids(row.get("existingNodeIds") or [])}
    return output


def _labels(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    output: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("label_object_required")
        key = _version_key(row)
        if key in output:
            raise ValueError("duplicate_label_version")
        source = str(row.get("labelSource") or "")
        if source not in LABEL_SOURCES or not str(row.get("annotatedBy") or "").strip():
            raise ValueError("label_source_and_annotator_required")
        node_labels: dict[int, str] = {}
        for item in row.get("nodeLabels") or []:
            if not isinstance(item, dict):
                raise TypeError("node_label_object_required")
            node = _node_id(item.get("nodeId"))
            if node in node_labels or item.get("choice") not in LABEL_CHOICES:
                raise ValueError("duplicate_or_invalid_node_label")
            node_labels[node] = item["choice"]
        if not node_labels:
            raise ValueError("node_labels_required")
        if "expectedNodeIds" in row and _node_ids(row["expectedNodeIds"]) != set(node_labels):
            raise ValueError("incomplete_blind_node_labels")
        output[key] = {"source": source, "labels": node_labels,
                       "inputHash": str(row.get("inputHash") or "")}
    return output


def _metrics(rows: list[dict[str, Any]], threshold: float, *, baseline: bool = False) -> dict[str, Any]:
    true_positive = false_positive = missed_positive = abstained = explicit_negative = 0
    errors: list[dict[str, Any]] = []
    for row in rows:
        gold = row["gold"]
        score = row["score"]
        suggested = row["existing"] if baseline else bool(
            score and score[0] == "yes" and score[1] >= threshold and not row["rejected"]
        )
        if not baseline and (not score or score[0] == "uncertain" or score[1] < threshold):
            abstained += 1
        if suggested and gold:
            true_positive += 1
        elif suggested:
            false_positive += 1
            errors.append({"caseId": row["caseId"], "nodeId": row["nodeId"], "kind": "false_positive"})
        elif gold:
            missed_positive += 1
            errors.append({"caseId": row["caseId"], "nodeId": row["nodeId"], "kind": "missed_positive"})
            if not baseline and score and score[0] == "no" and score[1] >= threshold:
                explicit_negative += 1
    positive_predictions = true_positive + false_positive
    positive_labels = true_positive + missed_positive

    def wilson(successes: int, total: int) -> list[float] | None:
        if not total:
            return None
        z = 1.96
        rate = successes / total
        divisor = 1 + z * z / total
        center = (rate + z * z / (2 * total)) / divisor
        margin = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / divisor
        return [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)]

    return {
        "truePositive": true_positive, "falsePositive": false_positive,
        "missedPositive": missed_positive,
        "precision": round(true_positive / positive_predictions, 4) if positive_predictions else None,
        "recall": round(true_positive / positive_labels, 4) if positive_labels else None,
        "precision95CI": wilson(true_positive, positive_predictions),
        "recall95CI": wilson(true_positive, positive_labels),
        **({} if baseline else {"abstained": abstained, "explicitNegativeOnPositive": explicit_negative}),
        "errors": sorted(errors, key=lambda item: (item["caseId"], item["nodeId"], item["kind"])),
    }


def evaluate_routing(
    shadow_rows: list[dict[str, Any]], label_rows: list[dict[str, Any]], *, threshold: float = 0.90,
) -> dict[str, Any]:
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("invalid_threshold")
    shadows, labels = _shadows(shadow_rows), _labels(label_rows)
    statuses = Counter(row["status"] for row in shadows.values())
    completed_labeled = partial_labeled = provisional = missing_shadow = uncertain = missing_score = stale = 0
    positive = negative = rejected_positive = 0
    compared: list[dict[str, Any]] = []
    for key, label in labels.items():
        shadow = shadows.get(key)
        if shadow is None:
            missing_shadow += 1
            continue
        if shadow["inputHash"] and label["inputHash"] != shadow["inputHash"]:
            stale += 1
            continue
        if label["source"] != "inspector":
            provisional += 1
            continue
        if shadow["status"] != "completed":
            partial_labeled += 1
            continue
        completed_labeled += 1
        for node_id, choice in label["labels"].items():
            if choice == "uncertain":
                uncertain += 1
                continue
            if choice == "belongs":
                positive += 1
                if node_id in shadow["rejected"]:
                    rejected_positive += 1
            else:
                negative += 1
            score = shadow["scores"].get(node_id)
            if score is None:
                missing_score += 1
            compared.append({"caseId": _case_id(key), "nodeId": node_id,
                             "gold": choice == "belongs", "score": score,
                             "rejected": node_id in shadow["rejected"],
                             "existing": node_id in shadow["existing"]})
    thresholds = sorted({*THRESHOLD_GRID, threshold})
    return {
        "schemaVersion": "jev-document-routing-evaluation-v1",
        "status": "ready_for_review" if compared else "no_comparable_inspector_labels",
        "threshold": threshold,
        "intervalMethod": "Wilson 95% on labeled node pairs; within-document correlation not modeled",
        "documents": {"shadowCount": len(shadows), "statusCounts": dict(sorted(statuses.items())),
                      "completedInspectorLabeled": completed_labeled,
                      "noncompletedInspectorLabeled": partial_labeled,
                      "provisionalLabeled": provisional, "labelsWithoutShadow": missing_shadow,
                      "staleInputHashLabeled": stale,
                      "shadowsWithoutLabels": len(set(shadows) - set(labels))},
        "labels": {"comparedNodeCount": len(compared), "positiveNodeCount": positive,
                   "negativeNodeCount": negative, "uncertainNodeCount": uncertain,
                   "missingScoreCount": missing_score,
                   "humanRejectionContradictions": rejected_positive},
        "jev": _metrics(compared, threshold),
        "existingBindings": _metrics(compared, threshold, baseline=True),
        "thresholdSweep": [{"threshold": item, **{
            key: value for key, value in _metrics(compared, item).items() if key != "errors"
        }} for item in thresholds],
        "releaseThresholdApproved": False,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid_json_line_{line_number}") from exc
        rows.append(row)
    return rows


def _read_labels(path: Path) -> list[dict[str, Any]]:
    if path.read_text(encoding="utf-8").lstrip().startswith("{"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and value.get("schemaVersion") == "jev-routing-blind-label-packet-v1":
            return value["cases"]
    return _read_jsonl(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shadows", required=True, type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--threshold", type=float, default=0.90)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = evaluate_routing(_read_jsonl(args.shadows), _read_labels(args.labels), threshold=args.threshold)
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0 if report["status"] == "ready_for_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
