from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from typing import Any

PRODUCTION_CERTIFICATION_PROFILE = "production-certification-v2"
CERTIFICATION_REPORT_SCHEMA_VERSION = "aicheck-certification-report-v2"
LEGACY_NON_CERTIFYING_PROFILE = "legacy_non_certifying"

_TERMINAL_REVIEW_STATUSES = {
    "completed",
    "waiting_human_review",
    "accepted_by_human",
    "edited_by_human",
    "rejected_by_human",
}
_SEVERITIES = {"low", "medium", "high", "critical"}


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _finding_identity(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("findingCode", "fieldCode", "title", "description", "message", "fieldName"):
            if value.get(key):
                return _normalized_text(value[key])
        return ""
    return _normalized_text(value)


def _severity(value: Any, fallback: Any = None) -> str | None:
    raw = value.get("severity") or value.get("riskLevel") if isinstance(value, dict) else fallback
    normalized = _normalized_text(raw)
    aliases = {"低": "low", "中": "medium", "高": "high", "严重": "critical"}
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in _SEVERITIES else None


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return round(2 * precision * recall / (precision + recall), 4)


def _gate(name: str, passed: bool, *, applicable: bool = True, detail: str | None = None) -> dict[str, Any]:
    return {
        "gate": name,
        "passed": bool(passed),
        "applicable": applicable,
        "detail": None if passed else detail,
    }


def _review_run_id_for_case(
    case: dict[str, Any],
    case_index: int,
    body: dict[str, Any],
    overrides: dict[str, dict[str, Any]],
) -> str | None:
    case_id = str(case.get("id") or "")
    override = overrides.get(case_id) or overrides.get(str(case.get("sourceFeedbackId") or "")) or {}
    for key in ("reviewRunId", "sourceReviewRunId"):
        if override.get(key):
            return str(override[key])
    mappings = body.get("caseReviewRuns")
    if isinstance(mappings, dict) and mappings.get(case_id):
        value = mappings[case_id]
        if isinstance(value, dict):
            value = value.get("reviewRunId") or value.get("id")
        return str(value) if value else None
    review_run_ids = body.get("reviewRunIds")
    if isinstance(review_run_ids, dict) and review_run_ids.get(case_id):
        return str(review_run_ids[case_id])
    if isinstance(review_run_ids, list) and case_index < len(review_run_ids):
        value = review_run_ids[case_index]
        if isinstance(value, dict):
            value = value.get("reviewRunId") or value.get("id")
        return str(value) if value else None
    for key in ("reviewRunId", "sourceReviewRunId"):
        if case.get(key):
            return str(case[key])
    return None


def _expected_clause_ids(case: dict[str, Any]) -> list[str]:
    for key in ("expectedClauseIds", "expectedClauses", "expectedKbRefs"):
        value = case.get(key)
        if not isinstance(value, list):
            continue
        result: list[str] = []
        for item in value:
            clause_id = item.get("clauseId") or item.get("id") if isinstance(item, dict) else item
            if clause_id:
                result.append(str(clause_id))
        if result:
            return result
    return []


def _selected_clause_ids(traces: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for trace in traces:
        for selected in trace.get("selectedClauses") or []:
            if not isinstance(selected, dict):
                continue
            clause_id = selected.get("clauseId") or selected.get("id")
            if clause_id:
                result.append(str(clause_id))
    return result


def _malformed_actual_findings(value: Any) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return [{"index": None, "reason": "findingDrafts must be a list"}]
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            failures.append({"index": index, "reason": "finding draft must be an object"})
            continue
        if not _finding_identity(item):
            failures.append({"index": index, "reason": "finding draft has no stable identity"})
        raw_severity = item.get("severity") or item.get("riskLevel")
        if raw_severity is not None and _severity(item) is None:
            failures.append({"index": index, "reason": "finding draft severity is malformed"})
    return failures


def build_production_certification_case_results(
    *,
    evaluation_run_id: str,
    cases: list[dict[str, Any]],
    body: dict[str, Any],
    overrides: dict[str, dict[str, Any]],
    find_review_run: Callable[[str], dict[str, Any] | None],
    retrieval_traces_for_run: Callable[[str], list[dict[str, Any]]],
    clone: Callable[[Any], Any],
    now: Callable[[], str],
    make_id: Callable[[], str],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    caller_actual_keys = {
        "actualFindings",
        "findings",
        "actualEvidence",
        "evidenceRefs",
        "actualClauseIds",
        "selectedClauseIds",
        "selectedRoute",
    }
    for case_index, case in enumerate(cases):
        case_id = str(case.get("id") or "")
        override = overrides.get(case_id) or overrides.get(str(case.get("sourceFeedbackId") or "")) or {}
        ignored_overrides = sorted(key for key in caller_actual_keys if key in override)
        review_run_id = _review_run_id_for_case(case, case_index, body, overrides)
        review_run = find_review_run(review_run_id) if review_run_id else None
        actual_present = bool(review_run is not None and "findingDrafts" in review_run and review_run.get("findingDrafts") is not None)
        actual_raw = review_run.get("findingDrafts") if actual_present and review_run else None
        malformed = _malformed_actual_findings(actual_raw) if actual_present else []
        actual_findings = clone(actual_raw) if actual_present and isinstance(actual_raw, list) else []
        valid_actual = [item for item in actual_findings if isinstance(item, dict) and _finding_identity(item)]
        execution_complete = bool(
            review_run
            and actual_present
            and not malformed
            and str(review_run.get("status") or "") in _TERMINAL_REVIEW_STATUSES
        )
        if not review_run_id:
            execution_status = "not_executed"
            incomplete_reason = "reviewRunId is missing"
        elif not review_run:
            execution_status = "not_executed"
            incomplete_reason = "persisted ReviewRun was not found"
        elif not actual_present:
            execution_status = "incomplete"
            incomplete_reason = "persisted ReviewRun has no findingDrafts output"
        elif malformed:
            execution_status = "malformed"
            incomplete_reason = "persisted ReviewRun findingDrafts are malformed"
        elif str(review_run.get("status") or "") not in _TERMINAL_REVIEW_STATUSES:
            execution_status = "incomplete"
            incomplete_reason = "persisted ReviewRun has not reached a certifiable execution state"
        else:
            execution_status = "completed"
            incomplete_reason = None

        expected_findings = clone(case.get("expectedFindings") or [])
        expected_rows = [
            {
                "index": index,
                "identity": _finding_identity(item),
                "severity": _severity(item, case.get("riskLevel")),
                "raw": item,
            }
            for index, item in enumerate(expected_findings)
        ]
        actual_rows = [
            {
                "index": index,
                "identity": _finding_identity(item),
                "severity": _severity(item),
                "raw": item,
            }
            for index, item in enumerate(valid_actual)
        ]
        available_actual: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in actual_rows:
            available_actual[row["identity"]].append(row)
        matched_actual_indexes: set[int] = set()
        matches: list[dict[str, Any]] = []
        false_negatives: list[dict[str, Any]] = []
        severity_mismatches: list[dict[str, Any]] = []
        for expected in expected_rows:
            candidates = available_actual.get(expected["identity"]) or []
            actual = candidates.pop(0) if candidates else None
            if actual is None:
                false_negatives.append(expected)
                continue
            matched_actual_indexes.add(actual["index"])
            severity_agrees = expected["severity"] is None or expected["severity"] == actual["severity"]
            match = {
                "expectedIndex": expected["index"],
                "actualIndex": actual["index"],
                "identity": expected["identity"],
                "expectedSeverity": expected["severity"],
                "actualSeverity": actual["severity"],
                "severityAgrees": severity_agrees,
            }
            matches.append(match)
            if not severity_agrees:
                severity_mismatches.append(match)
        false_positives = [row for row in actual_rows if row["index"] not in matched_actual_indexes]
        expected_counts = Counter(row["identity"] for row in expected_rows)
        actual_counts = Counter(row["identity"] for row in actual_rows)
        duplicate_count = sum(max(0, count - max(1, expected_counts.get(identity, 0))) for identity, count in actual_counts.items())

        high_risk_expected = [row for row in expected_rows if row["severity"] in {"high", "critical"}]
        high_risk_matched = [
            match
            for match in matches
            if match["expectedSeverity"] in {"high", "critical"}
        ]
        severity_comparable = [match for match in matches if match["expectedSeverity"] is not None]
        severity_agreed = [match for match in severity_comparable if match["severityAgrees"]]
        tp = len(matches)
        fp = len(false_positives)
        fn = len(false_negatives)
        precision = _rate(tp, tp + fp)
        recall = _rate(tp, tp + fn)

        traces = retrieval_traces_for_run(review_run_id) if review_run else []
        expected_clause_ids = _expected_clause_ids(case)
        selected_clause_ids = _selected_clause_ids(traces)
        selected_norm = {_normalized_text(item) for item in selected_clause_ids}
        missing_clause_ids = [item for item in expected_clause_ids if _normalized_text(item) not in selected_norm]
        retrieval_applicable = bool(expected_clause_ids)

        hard_gates = [
            _gate("actual_resolved_from_persisted_review_run", bool(review_run), detail=incomplete_reason),
            _gate("review_run_execution_complete", execution_complete, detail=incomplete_reason),
            _gate("actual_findings_well_formed", actual_present and not malformed, detail=incomplete_reason),
            _gate("one_to_one_finding_recall", fn == 0, detail=f"{fn} expected finding(s) missed"),
            _gate("no_false_positive_findings", fp == 0, detail=f"{fp} false-positive finding(s)"),
            _gate("no_duplicate_findings", duplicate_count == 0, detail=f"{duplicate_count} duplicate finding(s)"),
            _gate("severity_agreement", not severity_mismatches, applicable=bool(severity_comparable), detail=f"{len(severity_mismatches)} severity mismatch(es)"),
            _gate("high_risk_recall", len(high_risk_matched) == len(high_risk_expected), applicable=bool(high_risk_expected), detail=f"{len(high_risk_expected) - len(high_risk_matched)} high-risk finding(s) missed"),
            _gate("persisted_retrieval_trace", not retrieval_applicable or bool(traces), applicable=retrieval_applicable, detail="persisted ReviewRun retrieval trace is missing"),
            _gate("retrieval_recall", not missing_clause_ids, applicable=retrieval_applicable, detail=f"{len(missing_clause_ids)} expected clause(s) missed"),
        ]
        metrics = {
            "truePositives": tp,
            "falsePositives": fp,
            "falseNegatives": fn,
            "precision": precision,
            "recall": recall,
            "f1": _f1(precision, recall),
            "falsePositiveRate": _rate(fp, len(actual_rows)),
            "duplicateCount": duplicate_count,
            "duplicateRate": _rate(duplicate_count, len(actual_rows)),
            "severityAgreement": _rate(len(severity_agreed), len(severity_comparable)),
            "severityMismatchCount": len(severity_mismatches),
            "highRiskRecall": _rate(len(high_risk_matched), len(high_risk_expected)),
            "highRiskExpectedCount": len(high_risk_expected),
            "highRiskMissCount": len(high_risk_expected) - len(high_risk_matched),
        }
        results.append(
            {
                "id": make_id(),
                "schemaVersion": CERTIFICATION_REPORT_SCHEMA_VERSION,
                "profile": PRODUCTION_CERTIFICATION_PROFILE,
                "certifying": True,
                "evaluationRunId": evaluation_run_id,
                "evaluationCaseId": case_id,
                "sourceFeedbackId": case.get("sourceFeedbackId"),
                "businessPackId": case.get("businessPackId"),
                "nodeId": case.get("nodeId"),
                "riskLevel": case.get("riskLevel"),
                "status": "passed" if all(gate["passed"] for gate in hard_gates) else "failed",
                "executionStatus": execution_status,
                "incompleteReason": incomplete_reason,
                "reviewRunId": review_run_id,
                "actualSource": "persisted_review_run_pre_human_findingDrafts",
                "actualSourcePersisted": bool(review_run),
                "ignoredCallerOverrideFields": ignored_overrides,
                "expectedFindingCount": len(expected_rows),
                "actualFindingCount": len(actual_rows),
                "actualOutputPresent": actual_present,
                "actualOutputExplicitlyEmpty": actual_present and isinstance(actual_raw, list) and len(actual_raw) == 0,
                "malformedActual": malformed,
                "matches": matches,
                "falsePositiveFindings": [row["raw"] for row in false_positives],
                "falseNegativeFindings": [row["raw"] for row in false_negatives],
                "severityMismatches": severity_mismatches,
                "metrics": metrics,
                "hardGates": hard_gates,
                "retrievalTraceIds": [str(item.get("retrievalTraceId") or item.get("id")) for item in traces],
                "expectedClauseIds": expected_clause_ids,
                "selectedClauseIds": selected_clause_ids,
                "missingClauseIds": missing_clause_ids,
                "createdAt": now(),
            }
        )
    return results


def summarize_production_certification(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "truePositives": sum(int(item["metrics"]["truePositives"]) for item in case_results),
        "falsePositives": sum(int(item["metrics"]["falsePositives"]) for item in case_results),
        "falseNegatives": sum(int(item["metrics"]["falseNegatives"]) for item in case_results),
        "duplicateCount": sum(int(item["metrics"]["duplicateCount"]) for item in case_results),
        "severityMismatchCount": sum(int(item["metrics"]["severityMismatchCount"]) for item in case_results),
        "highRiskExpectedCount": sum(int(item["metrics"]["highRiskExpectedCount"]) for item in case_results),
        "highRiskMissCount": sum(int(item["metrics"]["highRiskMissCount"]) for item in case_results),
    }
    actual_total = sum(int(item.get("actualFindingCount") or 0) for item in case_results)
    severity_total = sum(
        len([match for match in item.get("matches") or [] if match.get("expectedSeverity") is not None])
        for item in case_results
    )
    severity_agreed = severity_total - totals["severityMismatchCount"]
    tp = totals["truePositives"]
    fp = totals["falsePositives"]
    fn = totals["falseNegatives"]
    precision = _rate(tp, tp + fp)
    recall = _rate(tp, tp + fn)
    passed = sum(1 for item in case_results if item.get("status") == "passed")
    execution_complete = sum(1 for item in case_results if item.get("executionStatus") == "completed")
    return {
        "cases": len(case_results),
        "passed": passed,
        "failed": len(case_results) - passed,
        "executionCompleteCases": execution_complete,
        "casePassRate": _rate(passed, len(case_results)),
        "executionRate": _rate(execution_complete, len(case_results)),
        **totals,
        "precision": precision,
        "recall": recall,
        "f1": _f1(precision, recall),
        "falsePositiveRate": _rate(fp, actual_total),
        "duplicateRate": _rate(totals["duplicateCount"], actual_total),
        "severityAgreement": _rate(severity_agreed, severity_total),
        "highRiskRecall": _rate(
            totals["highRiskExpectedCount"] - totals["highRiskMissCount"],
            totals["highRiskExpectedCount"],
        ),
    }


def certification_report_hash_payload(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
