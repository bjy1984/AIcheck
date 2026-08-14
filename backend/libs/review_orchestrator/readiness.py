from __future__ import annotations

from typing import Any

REVIEW_SCORECARD_V2_WEIGHTS = {
    "detection": 30,
    "evidence": 25,
    "retrieval": 15,
    "execution_provenance": 20,
    "backend_release": 10,
}


REQUIRED_REVIEW_SCORECARD_STEPS = [
    "load_context",
    "load_ocr_result",
    "run_rule_engine",
    "retrieve_knowledge",
    "build_prompt",
    "llm_generate_findings",
    "schema_validation",
    "evidence_validation",
    "reference_validation",
    "critic_review",
    "quality_gate",
    "persist_drafts",
]


def build_review_orchestration_scorecard(
    *,
    review_run: dict[str, Any],
    graph_view: dict[str, Any],
    temporal_history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sections = [
        workflow_section(review_run, temporal_history or {}),
        graph_section(review_run, graph_view),
        evidence_section(review_run, graph_view),
        governance_section(review_run),
    ]
    score = round(sum(float(section["score"]) for section in sections), 2)
    blockers = [
        blocker
        for section in sections
        for blocker in section.get("blockers", [])
    ]
    return {
        "schemaVersion": "aicheck-review-orchestration-scorecard-v1",
        "targetScore": 100,
        "score": score,
        "ok": score >= 100 and not blockers,
        "sections": sections,
        "blockers": blockers,
    }


def build_review_orchestration_scorecard_v2(
    *,
    review_run: dict[str, Any],
    graph_view: dict[str, Any],
    temporal_history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Phase 1 readiness card without treating artifact counts as proof of execution."""
    temporal = temporal_history or {}
    nodes = {
        str(item.get("nodeKey")): item
        for item in graph_view.get("nodes") or []
        if isinstance(item, dict) and item.get("nodeKey")
    }
    summary = graph_view.get("artifactSummary") if isinstance(graph_view.get("artifactSummary"), dict) else {}
    drafts = [item for item in review_run.get("findingDrafts") or [] if isinstance(item, dict)]
    quality_gate = review_run.get("qualityGate") if isinstance(review_run.get("qualityGate"), dict) else {}
    graph_execution = review_run.get("graphExecution") if isinstance(review_run.get("graphExecution"), dict) else {}
    policy = review_run.get("sensitivePayloadPolicy") if isinstance(review_run.get("sensitivePayloadPolicy"), dict) else {}

    rule_succeeded = node_succeeded(nodes, "run_rule_engine")
    detection_output = safe_int(summary.get("ruleCheckResults")) > 0 or bool(review_run.get("ruleCheckResults"))
    drafts_present = bool(drafts) and node_succeeded(nodes, "persist_drafts")
    detection_validation = all(node_succeeded(nodes, key) for key in ["schema_validation", "critic_review", "quality_gate"])
    quality_passed = quality_gate.get("passed") is True

    evidence_validation = node_succeeded(nodes, "evidence_validation")
    reference_validation = node_succeeded(nodes, "reference_validation")
    no_validation_failures = safe_int(summary.get("validationFailures")) == 0
    exact_evidence_refs = bool(drafts) and all(draft_has_exact_evidence_refs(item, review_run) for item in drafts)

    retrieval_succeeded = node_succeeded(nodes, "retrieve_knowledge")
    retrieval_trace_present = safe_int(summary.get("retrievalTraces")) > 0 or bool(review_run.get("retrievalTraces"))
    kb_refs_present = bool(drafts) and all(valid_kb_refs(item.get("kbRefs")) for item in drafts)

    temporal_active = review_run.get("workflowEngine") == "temporal" and review_run.get("workflowType") == "ReviewRunWorkflow" and bool(review_run.get("workflowId"))
    graph_complete = all(node_succeeded(nodes, key) for key in REQUIRED_REVIEW_SCORECARD_STEPS)
    langgraph_active = review_run.get("graphRunner") == "langgraph" and graph_complete
    postgres_checkpoint = graph_execution.get("checkpointer") == "postgres"
    history_hardened = temporal.get("historyPolicy") == "ids_hashes_versions_only" and temporal.get("payloadCodecRequired") is True
    provenance_complete = bool(review_run.get("inputHash") and review_run.get("outputHash")) and not (review_run.get("dispatchErrorCode") or review_run.get("temporalSignalErrorCode"))

    human_confirmed = bool(drafts) and all(item.get("requiresHumanConfirmation") is True for item in drafts)
    governance_state = review_run.get("status") in {"waiting_human_review", "accepted_by_human", "edited_by_human", "rejected_by_human"}
    storage_hardened = policy.get("rawTextStorage") == "postgres_minio_with_fde_grants"
    forbidden_tools = set(review_run.get("forbiddenTools") or [])
    forbidden_tools_complete = {"approve_review", "issue_formal_correction", "change_project_status", "delete_document"} <= forbidden_tools

    sections = [
        weighted_section(
            "detection",
            REVIEW_SCORECARD_V2_WEIGHTS["detection"],
            [(rule_succeeded, 10), (detection_output, 6), (drafts_present, 6), (detection_validation, 4), (quality_passed, 4)],
        ),
        weighted_section(
            "evidence",
            REVIEW_SCORECARD_V2_WEIGHTS["evidence"],
            [(evidence_validation, 7), (reference_validation, 6), (no_validation_failures, 5), (exact_evidence_refs, 7)],
        ),
        weighted_section(
            "retrieval",
            REVIEW_SCORECARD_V2_WEIGHTS["retrieval"],
            [(retrieval_succeeded, 6), (retrieval_trace_present, 4), (kb_refs_present, 5)],
        ),
        weighted_section(
            "execution_provenance",
            REVIEW_SCORECARD_V2_WEIGHTS["execution_provenance"],
            [(temporal_active, 4), (langgraph_active, 4), (postgres_checkpoint, 4), (history_hardened, 4), (provenance_complete, 4)],
        ),
        weighted_section(
            "backend_release",
            REVIEW_SCORECARD_V2_WEIGHTS["backend_release"],
            [(human_confirmed, 3), (governance_state, 2), (storage_hardened, 2), (forbidden_tools_complete, 3)],
        ),
    ]
    gate_specs = [
        ("rule_engine_executed", rule_succeeded, "rule engine node did not succeed"),
        ("detection_persisted", drafts_present, "validated finding drafts were not persisted"),
        ("quality_gate_passed", quality_passed and detection_validation, "detection validation or quality gate did not pass"),
        ("evidence_validation_passed", evidence_validation and reference_validation and no_validation_failures, "evidence/reference validation did not pass cleanly"),
        ("exact_input_evidence_refs", exact_evidence_refs, "finding evidence refs are missing, cross-document, or lack valid page/bbox position"),
        ("retrieval_executed", retrieval_succeeded and retrieval_trace_present and kb_refs_present, "retrieval execution, trace, or finding KB refs are missing"),
        ("temporal_langgraph_postgres", temporal_active and langgraph_active and postgres_checkpoint, "Temporal/LangGraph/Postgres execution stack is not active"),
        ("provenance_hardened", history_hardened and provenance_complete, "history policy, payload codec, hashes, or dispatch provenance is incomplete"),
        ("human_release_governance", human_confirmed and governance_state and storage_hardened and forbidden_tools_complete, "human confirmation/release governance or protected storage policy is incomplete"),
    ]
    mandatory_gates = [
        {"name": name, "passed": passed, "message": None if passed else message}
        for name, passed, message in gate_specs
    ]
    blockers = [str(gate["message"]) for gate in mandatory_gates if not gate["passed"]]
    score = round(sum(float(item["score"]) for item in sections), 2)
    return {
        "schemaVersion": "aicheck-review-orchestration-scorecard-v2",
        "targetScore": 85,
        "score": score,
        "ok": score >= 85 and not blockers,
        "weights": dict(REVIEW_SCORECARD_V2_WEIGHTS),
        "sections": sections,
        "mandatoryGates": mandatory_gates,
        "blockers": blockers,
    }


def node_succeeded(nodes: dict[str, dict[str, Any]], node_key: str) -> bool:
    return str((nodes.get(node_key) or {}).get("status") or "") == "succeeded"


def draft_has_exact_evidence_refs(draft: dict[str, Any], review_run: dict[str, Any]) -> bool:
    refs = [item for item in draft.get("evidenceRefs") or [] if isinstance(item, dict)]
    if not refs:
        return False
    exact_versions = {
        str(item)
        for item in review_run.get("inputDocumentVersionIds") or review_run.get("documentVersionIds") or []
        if item
    }
    if not exact_versions:
        return False
    for ref in refs:
        version_id = str(ref.get("documentVersionId") or "")
        if not version_id or version_id not in exact_versions:
            return False
        if safe_int(ref.get("pageNo")) < 1 or not valid_bbox(ref.get("bbox")):
            return False
    failures = draft.get("evidenceValidationFailures") or []
    return not failures


def valid_kb_refs(value: Any) -> bool:
    refs = [item for item in value or [] if isinstance(item, dict)] if isinstance(value, list) else []
    return bool(refs) and all(item.get("retrievalTraceId") and item.get("clauseIds") for item in refs)


def valid_bbox(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return False
    try:
        left, top, right, bottom = (float(item) for item in value)
    except (TypeError, ValueError):
        return False
    return right > left and bottom > top


def weighted_section(name: str, max_score: float, checks: list[tuple[bool, float]]) -> dict[str, Any]:
    score = round(sum(points for passed, points in checks if passed), 2)
    return {
        "name": name,
        "score": score,
        "maxScore": max_score,
        "status": "pass" if score >= max_score else "fail",
    }


def workflow_section(review_run: dict[str, Any], temporal_history: dict[str, Any]) -> dict[str, Any]:
    points = 0.0
    blockers: list[str] = []
    if review_run.get("workflowType") == "ReviewRunWorkflow":
        points += 5
    else:
        blockers.append("ReviewRun workflowType must be ReviewRunWorkflow")
    if review_run.get("workflowEngine") == "temporal":
        points += 7
    else:
        blockers.append("outer workflow is not running on Temporal")
    if review_run.get("workflowId"):
        points += 4
    else:
        blockers.append("workflowId is missing")
    if temporal_history.get("historyPolicy") == "ids_hashes_versions_only":
        points += 4
    else:
        blockers.append("Temporal history policy must be ids_hashes_versions_only")
    if temporal_history.get("payloadCodecRequired") is True:
        points += 3
    else:
        blockers.append("Temporal payload codec is not marked required")
    if review_run.get("dispatchErrorCode") or review_run.get("temporalSignalErrorCode"):
        blockers.append("Temporal dispatch or signal error exists")
    else:
        points += 2
    return section("workflow", points, 25, blockers)


def graph_section(review_run: dict[str, Any], graph_view: dict[str, Any]) -> dict[str, Any]:
    nodes = [item for item in graph_view.get("nodes") or [] if isinstance(item, dict)]
    node_keys = {str(item.get("nodeKey")) for item in nodes}
    statuses = {str(item.get("status") or "") for item in nodes}
    graph_execution = review_run.get("graphExecution") if isinstance(review_run.get("graphExecution"), dict) else {}
    points = 0.0
    blockers: list[str] = []
    missing_steps = [step for step in REQUIRED_REVIEW_SCORECARD_STEPS if step not in node_keys]
    if not missing_steps:
        points += 6
    else:
        blockers.append("LangGraph is missing steps: " + ", ".join(missing_steps))
    if nodes and statuses <= {"succeeded"}:
        points += 6
    else:
        blockers.append("one or more LangGraph nodes are not succeeded")
    if len(graph_view.get("edges") or []) >= max(0, len(nodes) - 1):
        points += 4
    else:
        blockers.append("LangGraph edges do not connect all nodes")
    if review_run.get("graphRunner") == "langgraph":
        points += 5
    else:
        blockers.append("inner graph is using manual fallback instead of LangGraph")
    if graph_execution.get("checkpointer") == "postgres":
        points += 4
    else:
        blockers.append("LangGraph Postgres checkpointer is not active")
    return section("graph", points, 25, blockers)


def evidence_section(review_run: dict[str, Any], graph_view: dict[str, Any]) -> dict[str, Any]:
    summary = graph_view.get("artifactSummary") if isinstance(graph_view.get("artifactSummary"), dict) else {}
    points = 0.0
    blockers: list[str] = []
    if review_run.get("modelGateway") in {"qwen_runtime", "litellm"}:
        points += 5
    else:
        blockers.append("modelGateway must be qwen_runtime")
    gates = [
        ("toolCalls", 3, "tool gateway calls are missing"),
        ("ruleCheckResults", 1, "rule engine result is missing"),
        ("retrievalTraces", 1, "knowledge retrieval trace is missing"),
        ("findingDrafts", 1, "review finding draft is missing"),
    ]
    for key, minimum, message in gates:
        if safe_int(summary.get(key)) >= minimum:
            points += 4
        else:
            blockers.append(message)
    if safe_int(summary.get("validationFailures")) == 0:
        points += 5
    else:
        blockers.append("validation failures exist")
    quality_gate = review_run.get("qualityGate") if isinstance(review_run.get("qualityGate"), dict) else {}
    if quality_gate.get("passed") is True:
        points += 4
    else:
        blockers.append("quality gate is not passed")
    return section("evidence", points, 30, blockers)


def governance_section(review_run: dict[str, Any]) -> dict[str, Any]:
    points = 0.0
    blockers: list[str] = []
    policy = review_run.get("sensitivePayloadPolicy") if isinstance(review_run.get("sensitivePayloadPolicy"), dict) else {}
    if review_run.get("inputHash") and review_run.get("outputHash"):
        points += 5
    else:
        blockers.append("input/output hash is missing")
    drafts = [item for item in review_run.get("findingDrafts") or [] if isinstance(item, dict)]
    if drafts and all(item.get("requiresHumanConfirmation") is True for item in drafts):
        points += 5
    else:
        blockers.append("finding drafts must require human confirmation")
    if review_run.get("status") in {"waiting_human_review", "accepted_by_human", "edited_by_human", "rejected_by_human"}:
        points += 4
    else:
        blockers.append("review run has not reached a human-review governance state")
    if policy.get("rawTextStorage") == "postgres_minio_with_fde_grants":
        points += 3
    else:
        blockers.append("raw text storage policy is not grant-gated")
    forbidden_tools = set(review_run.get("forbiddenTools") or [])
    if {"approve_review", "issue_formal_correction", "change_project_status", "delete_document"} <= forbidden_tools:
        points += 3
    else:
        blockers.append("forbidden business tools are not fully declared")
    return section("governance", points, 20, blockers)


def section(name: str, score: float, max_score: float, blockers: list[str]) -> dict[str, Any]:
    score = round(min(max(score, 0.0), max_score), 2)
    return {
        "name": name,
        "score": score,
        "maxScore": max_score,
        "status": "pass" if score >= max_score and not blockers else "fail",
        "blockers": blockers,
    }


def safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0
