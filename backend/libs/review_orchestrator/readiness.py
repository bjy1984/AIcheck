from __future__ import annotations

from typing import Any


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
    if review_run.get("modelGateway") == "litellm":
        points += 5
    else:
        blockers.append("modelGateway must be litellm")
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
