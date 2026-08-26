from __future__ import annotations

import json
from copy import deepcopy
from typing import Any


class ProjectAnalysisOutputError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = str(code)
        super().__init__(self.code)


def _bounded_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    if 1 < number <= 100:
        number /= 100
    return max(0.0, min(1.0, number))


def recompute_project_analysis_summary(
    node_reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    result_to_key = {
        "supported": "supportedNodeCount",
        "partially_supported": "partialNodeCount",
        "insufficient_evidence": "insufficientNodeCount",
        "conflict": "conflictNodeCount",
        "mismatch": "mismatchNodeCount",
    }
    summary = {key: 0 for key in result_to_key.values()}
    priority_risks: list[str] = []
    priority_actions: list[str] = []
    for review in node_reviews:
        key = result_to_key.get(str(review.get("reviewResult") or ""))
        if key:
            summary[key] += 1
        for risk in review.get("risks") or []:
            value = str(risk).strip()
            if value and value not in priority_risks:
                priority_risks.append(value)
        for action in review.get("recommendations") or []:
            value = str(action).strip()
            if value and value not in priority_actions:
                priority_actions.append(value)
    return {
        **summary,
        "humanReviewNodeCount": len(node_reviews),
        "priorityRisks": priority_risks,
        "priorityManualActions": priority_actions,
    }


def _validate_evidence_ref(
    evidence_ref: dict[str, Any],
    *,
    allowed_file_ids: set[str],
    corpus: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    failures: list[dict[str, Any]] = []
    file_id = str(evidence_ref.get("fileId") or "")
    if file_id not in allowed_file_ids:
        failures.append({"code": "EVIDENCE_FILE_OUTSIDE_NODE", "fileId": file_id})
        return None, failures
    source = corpus.get(file_id)
    if not source:
        failures.append({"code": "EVIDENCE_FILE_NOT_IN_CORPUS", "fileId": file_id})
        return None, failures
    if str(evidence_ref.get("documentVersionId") or "") != str(
        source.get("documentVersionId") or ""
    ):
        failures.append({"code": "EVIDENCE_VERSION_MISMATCH", "fileId": file_id})
    if str(evidence_ref.get("fileName") or "") != str(source.get("fileName") or ""):
        failures.append({"code": "EVIDENCE_FILENAME_MISMATCH", "fileId": file_id})
    quoted_text = str(evidence_ref.get("quotedText") or "")
    if not quoted_text or quoted_text not in str(source.get("fullOcrText") or ""):
        failures.append({"code": "EVIDENCE_QUOTE_NOT_VERBATIM", "fileId": file_id})
    return (deepcopy(evidence_ref) if not failures else None), failures


def _validate_rule_ref(
    rule_ref: dict[str, Any], expected_node: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    source = str(rule_ref.get("source") or "")
    text = str(rule_ref.get("text") or "")
    if source not in {"criteria", "checkMethod"}:
        return None, [{"code": "RULE_REF_SOURCE_INVALID", "source": source}]
    basis = str(expected_node.get(source) or "")
    if not text or text not in basis:
        return None, [{"code": "RULE_REF_NOT_VERBATIM", "source": source}]
    return deepcopy(rule_ref), []


def _validated_finding(
    finding: dict[str, Any],
    *,
    expected_node: dict[str, Any],
    corpus: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    item = deepcopy(finding)
    allowed_file_ids = {
        str(row.get("fileId") or "")
        for row in expected_node.get("fileRefs") or []
        if row.get("fileId")
    }
    valid_evidence: list[dict[str, Any]] = []
    valid_rules: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for evidence_ref in item.get("evidenceRefs") or []:
        if not isinstance(evidence_ref, dict):
            failures.append({"code": "EVIDENCE_REF_INVALID_TYPE"})
            continue
        valid, diagnostics = _validate_evidence_ref(
            evidence_ref,
            allowed_file_ids=allowed_file_ids,
            corpus=corpus,
        )
        failures.extend(diagnostics)
        if valid:
            valid_evidence.append(valid)
    for rule_ref in item.get("ruleRefs") or []:
        if not isinstance(rule_ref, dict):
            failures.append({"code": "RULE_REF_INVALID_TYPE"})
            continue
        valid, diagnostics = _validate_rule_ref(rule_ref, expected_node)
        failures.extend(diagnostics)
        if valid:
            valid_rules.append(valid)
    if not valid_evidence:
        failures.append({"code": "EVIDENCE_REFS_MISSING"})
    item["requiresHumanConfirmation"] = True
    item["confidence"] = _bounded_confidence(item.get("confidence"))
    item["evidenceRefs"] = valid_evidence
    item["ruleRefs"] = valid_rules
    item["kbRefs"] = item.get("kbRefs") if isinstance(item.get("kbRefs"), list) else []
    item["unsupportedClaims"] = (
        item.get("unsupportedClaims")
        if isinstance(item.get("unsupportedClaims"), list)
        else []
    )
    item["validationFailures"] = failures
    invalid = bool(failures)
    if invalid:
        item["groundingStatus"] = "insufficient_evidence"
        item["confidence"] = min(item["confidence"], 0.55)
        item["suggestedAction"] = "human_confirm"
        item["evidenceRefs"] = []
        codes = [row["code"] for row in failures if row.get("code")]
        item["unsupportedClaims"] = list(
            dict.fromkeys([*item["unsupportedClaims"], *codes])
        )
    else:
        item["groundingStatus"] = "grounded"
        if item.get("suggestedAction") not in {"human_confirm", "request_correction"}:
            item["suggestedAction"] = "human_confirm"
    return item, invalid


def validate_project_analysis_output(
    raw_text: str,
    snapshot: dict[str, Any],
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        parsed = json.loads(str(raw_text))
    except ValueError as exc:
        raise ProjectAnalysisOutputError("LLM_OUTPUT_INVALID_JSON") from exc
    if not isinstance(parsed, dict):
        raise ProjectAnalysisOutputError("LLM_OUTPUT_INVALID_ENVELOPE")
    if parsed.get("schemaVersion") != "AIAllReviewResult@2.0.0":
        raise ProjectAnalysisOutputError("LLM_OUTPUT_SCHEMA_VERSION_MISMATCH")
    if str(parsed.get("projectId") or "") != str(snapshot.get("projectId") or ""):
        raise ProjectAnalysisOutputError("PROJECT_ANALYSIS_PROJECT_MISMATCH")
    reviews = parsed.get("nodeReviews")
    if not isinstance(reviews, list) or any(not isinstance(row, dict) for row in reviews):
        raise ProjectAnalysisOutputError("LLM_OUTPUT_INVALID_NODE_REVIEWS")
    actual_ids = [int(row.get("nodeId") or 0) for row in reviews]
    expected_ids = [int(item) for item in snapshot.get("nodeIds") or []]
    if sorted(actual_ids) != sorted(expected_ids) or len(set(actual_ids)) != len(actual_ids):
        raise ProjectAnalysisOutputError("PROJECT_ANALYSIS_NODE_SET_MISMATCH")
    expected_nodes = {
        int(row.get("nodeId") or 0): row
        for row in (request_payload.get("project") or {}).get("nodes") or []
        if isinstance(row, dict)
    }
    corpus = (request_payload.get("project") or {}).get("fileCorpus") or {}
    validated_reviews: list[dict[str, Any]] = []
    for source_review in reviews:
        review = deepcopy(source_review)
        node_id = int(review.get("nodeId") or 0)
        expected_node = expected_nodes.get(node_id) or {}
        review["nodeName"] = expected_node.get("nodeName") or review.get("nodeName")
        findings: list[dict[str, Any]] = []
        invalid_count = 0
        for source_finding in review.get("findings") or []:
            if not isinstance(source_finding, dict):
                continue
            finding, invalid = _validated_finding(
                source_finding,
                expected_node=expected_node,
                corpus=corpus,
            )
            findings.append(finding)
            invalid_count += int(invalid)
        review["findings"] = findings
        if not findings or invalid_count == len(findings):
            review["reviewResult"] = "insufficient_evidence"
        elif invalid_count:
            review["reviewResult"] = "partially_supported"
        validated_reviews.append(review)
    return {
        **deepcopy(parsed),
        "nodeReviews": validated_reviews,
        "projectSummary": recompute_project_analysis_summary(validated_reviews),
        "validation": {
            "nodeCount": len(validated_reviews),
            "findingCount": sum(len(row.get("findings") or []) for row in validated_reviews),
            "invalidFindingCount": sum(
                any(finding.get("validationFailures") or [])
                for row in validated_reviews
                for finding in row.get("findings") or []
            ),
        },
    }
