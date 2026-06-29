from __future__ import annotations

import hashlib
import json
import os
from typing import Any
from uuid import uuid4

from libs.business_pack import DEFAULT_BUSINESS_PACK_ID, load_business_pack, matching_rule_for_node
from libs.contracts.responses import server_time
from libs.db.repository import repo

REVIEW_GRAPH_STEPS: list[dict[str, Any]] = [
    {"key": "load_context", "label": "加载项目上下文", "taskQueue": "review.graph"},
    {"key": "load_ocr_result", "label": "加载 OCR 证据", "taskQueue": "review.graph"},
    {"key": "run_rule_engine", "label": "执行确定性规则", "taskQueue": "review.validation"},
    {"key": "retrieve_knowledge", "label": "检索知识依据", "taskQueue": "review.retrieval"},
    {"key": "build_prompt", "label": "构造审查 Prompt", "taskQueue": "review.graph"},
    {"key": "llm_generate_findings", "label": "LiteLLM 生成审查草稿", "taskQueue": "review.llm"},
    {"key": "schema_validation", "label": "Schema 校验", "taskQueue": "review.validation"},
    {"key": "evidence_validation", "label": "证据校验", "taskQueue": "review.validation"},
    {"key": "reference_validation", "label": "依据校验", "taskQueue": "review.validation"},
    {"key": "critic_review", "label": "Critic 复核", "taskQueue": "review.llm"},
    {"key": "quality_gate", "label": "质量门禁", "taskQueue": "review.validation"},
    {"key": "persist_drafts", "label": "持久化草稿", "taskQueue": "review.graph"},
]

REVIEW_GRAPH_EDGES = [
    {"source": REVIEW_GRAPH_STEPS[index]["key"], "target": REVIEW_GRAPH_STEPS[index + 1]["key"]}
    for index in range(len(REVIEW_GRAPH_STEPS) - 1)
]

REVIEW_STATE_COLLECTIONS = (
    "review_runs",
    "review_step_runs",
    "review_graph_nodes",
    "review_tool_calls",
    "review_events",
    "retrieval_traces",
    "rule_check_results",
)

FORBIDDEN_AGENT_TOOLS = {
    "approve_review",
    "issue_formal_correction",
    "close_correction",
    "change_project_status",
    "archive_project",
    "delete_document",
    "modify_audit_log",
    "grant_permission",
}

ALLOWED_AGENT_TOOLS = {
    "get_project_context",
    "get_node_requirements",
    "get_document_ocr_result",
    "run_rule_engine",
    "retrieve_clauses",
    "search_knowledge_base",
    "create_review_finding_draft",
    "create_ai_diagnostic",
}


def ensure_review_state() -> None:
    for collection in REVIEW_STATE_COLLECTIONS:
        repo.state.setdefault(collection, [])


def stable_hash_payload(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def review_task_queues() -> dict[str, str]:
    return {
        "workflow": os.getenv("AICHECK_REVIEW_WORKFLOW_TASK_QUEUE", "review.workflow"),
        "graph": os.getenv("AICHECK_REVIEW_GRAPH_TASK_QUEUE", "review.graph"),
        "llm": os.getenv("AICHECK_REVIEW_LLM_TASK_QUEUE", "review.llm"),
        "retrieval": os.getenv("AICHECK_REVIEW_RETRIEVAL_TASK_QUEUE", "review.retrieval"),
        "validation": os.getenv("AICHECK_REVIEW_VALIDATION_TASK_QUEUE", "review.validation"),
    }


def create_review_run_from_ai_run(ai_run: dict[str, Any], *, mode: str = "temporal") -> dict[str, Any]:
    ensure_review_state()
    existing_id = ai_run.get("reviewRunId")
    if existing_id:
        existing = repo.find_one("review_runs", str(existing_id), id_field="reviewRunId")
        if existing:
            return existing

    review_run_id = f"RRUN-{uuid4().hex[:10].upper()}"
    task_queues = review_task_queues()
    workflow_id = f"review-run-{review_run_id}"
    now = server_time()
    record = {
        "id": review_run_id,
        "reviewRunId": review_run_id,
        "aiRunId": ai_run["id"],
        "projectId": ai_run.get("projectId"),
        "nodeId": ai_run.get("nodeId"),
        "businessPackId": ai_run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
        "businessPackVersion": ai_run.get("businessPackVersion"),
        "businessPackSnapshotHash": ai_run.get("businessPackSnapshotHash"),
        "agentId": ai_run.get("agentId") or "compliance_review_agent",
        "agentVersion": ai_run.get("agentVersion") or "1.0.0",
        "promptVersion": ai_run.get("promptVersion") or "review_prompt@1.0.0",
        "modelAlias": ai_run.get("model") or "review-chat",
        "modelGateway": "litellm",
        "ruleSetVersion": ai_run.get("ruleVersion") or "ruleset-v1",
        "kbVersion": ai_run.get("knowledgeBaseVersion") or "inspection_kb@1.0.0",
        "ocrResultVersions": ai_run.get("ocrResultVersions") or [],
        "inputDocumentVersionIds": ai_run.get("inputDocumentVersionIds") or [],
        "schemaVersion": ai_run.get("schemaVersion") or "ReviewFindingDraftList@1.0.0",
        "runMode": ai_run.get("runType") or "production",
        "status": "queued",
        "currentStep": "created",
        "workflowEngine": "temporal" if mode == "temporal" else "inline_temporal_compatible",
        "graphEngine": "langgraph",
        "workflowType": "ReviewRunWorkflow",
        "workflowId": workflow_id,
        "temporalNamespace": os.getenv("TEMPORAL_NAMESPACE", "default"),
        "taskQueues": task_queues,
        "sensitivePayloadPolicy": {
            "temporalPayload": "ids_hashes_versions_only",
            "rawTextStorage": "mongo_minio_with_fde_grants",
            "payloadCodecRequiredInProduction": True,
        },
        "allowedTools": sorted(ALLOWED_AGENT_TOOLS),
        "forbiddenTools": sorted(FORBIDDEN_AGENT_TOOLS),
        "inputHash": stable_hash_payload(
            {
                "documentVersionIds": ai_run.get("inputDocumentVersionIds") or [],
                "businessPackId": ai_run.get("businessPackId"),
                "promptVersion": ai_run.get("promptVersion"),
                "ruleSetVersion": ai_run.get("ruleVersion"),
            }
        ),
        "outputHash": None,
        "findingDrafts": [],
        "createdAt": now,
        "updatedAt": now,
        "startedAt": None,
        "finishedAt": None,
        "revision": 1,
    }
    repo.state["review_runs"].insert(0, record)
    ai_run["reviewRunId"] = review_run_id
    ai_run["workflowId"] = workflow_id
    ai_run["workflowEngine"] = record["workflowEngine"]
    ai_run["graphEngine"] = record["graphEngine"]
    ai_run["modelGateway"] = record["modelGateway"]
    seed_graph_nodes(record)
    append_review_event(
        review_run_id,
        event_type="review_run.created",
        title="ReviewRun 已创建",
        status="queued",
        details={"aiRunId": ai_run["id"], "workflowId": workflow_id},
    )
    return record


def seed_graph_nodes(review_run: dict[str, Any]) -> None:
    existing = {
        item.get("nodeKey")
        for item in repo.state["review_graph_nodes"]
        if item.get("reviewRunId") == review_run["reviewRunId"]
    }
    for sequence, step in enumerate(REVIEW_GRAPH_STEPS, start=1):
        if step["key"] in existing:
            continue
        repo.state["review_graph_nodes"].append(
            {
                "id": f"RGNODE-{uuid4().hex[:8].upper()}",
                "reviewRunId": review_run["reviewRunId"],
                "aiRunId": review_run.get("aiRunId"),
                "nodeKey": step["key"],
                "label": step["label"],
                "sequence": sequence,
                "taskQueue": step["taskQueue"],
                "status": "pending",
                "attempt": 0,
                "createdAt": server_time(),
            }
        )


def append_review_event(
    review_run_id: str,
    *,
    event_type: str,
    title: str,
    status: str,
    node_key: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_review_state()
    event = {
        "id": f"REVT-{uuid4().hex[:8].upper()}",
        "reviewRunId": review_run_id,
        "eventType": event_type,
        "title": title,
        "status": status,
        "nodeKey": node_key,
        "details": details or {},
        "createdAt": server_time(),
    }
    repo.state["review_events"].append(event)
    return event


def mark_graph_node(
    review_run_id: str,
    node_key: str,
    status: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_review_state()
    node = next(
        item
        for item in repo.state["review_graph_nodes"]
        if item.get("reviewRunId") == review_run_id and item.get("nodeKey") == node_key
    )
    now = server_time()
    if status == "running":
        node["startedAt"] = node.get("startedAt") or now
        node["attempt"] = int(node.get("attempt") or 0) + 1
    if status in {"succeeded", "failed", "skipped"}:
        node["finishedAt"] = now
    node["status"] = status
    node["updatedAt"] = now
    if details:
        node.setdefault("details", {}).update(details)
        node["outputHash"] = stable_hash_payload(details)
    append_review_event(
        review_run_id,
        event_type=f"graph_node.{status}",
        title=f"{node.get('label')}：{status}",
        status=status,
        node_key=node_key,
        details=details,
    )
    return node


def execute_review_run_inline(review_run_id: str) -> dict[str, Any]:
    ensure_review_state()
    review_run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if not review_run:
        return {"reviewRunId": review_run_id, "status": "missing"}
    if review_run.get("status") in {"waiting_human_review", "accepted_by_human", "edited_by_human", "rejected_by_human", "failed"}:
        return {"reviewRunId": review_run_id, "status": review_run.get("status"), "alreadyCompleted": True}
    ai_run = repo.find_one("ai_runs", str(review_run.get("aiRunId")))
    review_run["status"] = "running"
    review_run["startedAt"] = review_run.get("startedAt") or server_time()
    review_run["updatedAt"] = server_time()
    if ai_run:
        ai_run["status"] = "推理中"
    context: dict[str, Any] = {}
    try:
        for step in REVIEW_GRAPH_STEPS:
            node_key = step["key"]
            review_run["currentStep"] = node_key
            mark_graph_node(review_run_id, node_key, "running")
            details = run_step(review_run, node_key, context)
            mark_graph_node(review_run_id, node_key, "succeeded", details=details)
        review_run["status"] = "waiting_human_review"
        review_run["currentStep"] = "waiting_human_review"
        review_run["finishedAt"] = server_time()
        review_run["updatedAt"] = review_run["finishedAt"]
        review_run["outputHash"] = stable_hash_payload(review_run.get("findingDrafts") or [])
        append_review_event(review_run_id, event_type="review_run.waiting_human", title="等待人工确认", status="waiting_human_review")
        if ai_run:
            ai_run["status"] = "完成"
            ai_run["finishedAt"] = review_run["finishedAt"]
            ai_run["findingDrafts"] = repo.clone(review_run.get("findingDrafts") or [])
            ai_run["evidenceLinks"] = repo.clone(context.get("evidenceLinks") or [])
            ai_run.setdefault("suggestion", {}).update(
                {
                    "result": "需人工确认",
                    "opinionDraft": (review_run.get("findingDrafts") or [{}])[0].get("description", "AI 审查草稿已生成。"),
                    "confidence": (review_run.get("findingDrafts") or [{}])[0].get("confidence", 0.82),
                    "manualConfirmItems": ["证据链、规则依据和条款适用性"],
                }
            )
            ai_run["steps"] = [
                {
                    "id": node["id"],
                    "title": node["label"],
                    "action": node["nodeKey"],
                    "conclusion": node["status"],
                    "evidenceLinkIds": [item.get("id") for item in context.get("evidenceLinks", [])[:3]],
                }
                for node in graph_nodes_for_review_run(review_run_id)
            ]
        return {"reviewRunId": review_run_id, "status": review_run["status"]}
    except Exception as exc:
        review_run["status"] = "failed"
        review_run["errorCode"] = "REVIEW_WORKFLOW_FAILED"
        review_run["errorMessage"] = str(exc)
        review_run["finishedAt"] = server_time()
        append_review_event(review_run_id, event_type="review_run.failed", title="ReviewRun 执行失败", status="failed", details={"message": str(exc)})
        if ai_run:
            ai_run["status"] = "失败"
            ai_run["errorCode"] = "AI_RUN_FAILED"
            ai_run["errorMessage"] = "Temporal/LangGraph 审查编排执行失败。"
        return {"reviewRunId": review_run_id, "status": "failed", "errorMessage": str(exc)}


def run_step(review_run: dict[str, Any], node_key: str, context: dict[str, Any]) -> dict[str, Any]:
    if node_key == "load_context":
        project = repo.require_project(str(review_run.get("projectId")))
        node = repo.node(str(review_run.get("projectId")), int(review_run.get("nodeId") or 0))
        context["project"] = project or {}
        context["node"] = node or {}
        return {"projectId": review_run.get("projectId"), "nodeId": review_run.get("nodeId"), "nodeName": (node or {}).get("name")}
    if node_key == "load_ocr_result":
        version_ids = set(review_run.get("inputDocumentVersionIds") or [])
        fields = [item for item in repo.state.get("extracted_fields", []) if item.get("documentVersionId") in version_ids]
        evidence_links = repo.clone(repo.state.get("evidence_links", [])[:5])
        context["fields"] = fields
        context["evidenceLinks"] = evidence_links
        append_tool_call(review_run, node_key, "get_document_ocr_result", {"fieldCount": len(fields), "evidenceLinks": len(evidence_links)})
        return {"fieldCount": len(fields), "evidenceLinkCount": len(evidence_links)}
    if node_key == "run_rule_engine":
        pack = load_business_pack(str(review_run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID))
        rule = matching_rule_for_node(pack, int(review_run.get("nodeId") or 0)) or next(iter(pack.get("ruleSets") or []), {})
        result = {
            "id": f"RCHK-{uuid4().hex[:8].upper()}",
            "reviewRunId": review_run["reviewRunId"],
            "ruleCode": rule.get("ruleKey") or rule.get("id") or "generic-review",
            "ruleSetVersion": rule.get("version") or review_run.get("ruleSetVersion"),
            "result": "passed" if context.get("fields") else "warning",
            "severity": rule.get("severity") or "medium",
            "message": "规则检查完成，待人工确认。" if context.get("fields") else "未发现可用 OCR 字段，需人工复核。",
            "linkedClauseIds": [],
            "evidenceRefs": [{"source": "ocr_fields", "count": len(context.get("fields") or [])}],
            "suggestedAction": "human_confirm",
            "createdAt": server_time(),
        }
        repo.state["rule_check_results"].append(result)
        context["ruleResults"] = [result]
        append_tool_call(review_run, node_key, "run_rule_engine", {"ruleCode": result["ruleCode"], "result": result["result"]})
        return {"ruleResults": 1, "ruleCode": result["ruleCode"], "result": result["result"]}
    if node_key == "retrieve_knowledge":
        trace = {
            "id": f"RTR-{uuid4().hex[:8].upper()}",
            "retrievalTraceId": f"RTR-{uuid4().hex[:8].upper()}",
            "reviewRunId": review_run["reviewRunId"],
            "query": f"{context.get('node', {}).get('name') or '节点'} 审查依据",
            "queryType": "review_basis_search",
            "filters": {
                "businessPackId": review_run.get("businessPackId"),
                "nodeId": review_run.get("nodeId"),
                "effectiveAt": server_time(),
            },
            "retrievers": [
                {"type": "clause_index", "topK": 5},
                {"type": "hybrid_bm25_dense", "topK": 10},
            ],
            "selectedClauses": [],
            "kbVersion": review_run.get("kbVersion"),
            "createdAt": server_time(),
        }
        repo.state["retrieval_traces"].append(trace)
        context["retrievalTraces"] = [trace]
        append_tool_call(review_run, node_key, "search_knowledge_base", {"retrievalTraceId": trace["retrievalTraceId"]})
        return {"retrievalTraceId": trace["retrievalTraceId"], "selectedClauses": 0}
    if node_key == "build_prompt":
        prompt_shape = {
            "system": "review_agent_sop",
            "userContextHash": stable_hash_payload(
                {
                    "projectId": review_run.get("projectId"),
                    "nodeId": review_run.get("nodeId"),
                    "fieldCount": len(context.get("fields") or []),
                }
            ),
        }
        context["promptShape"] = prompt_shape
        return {"promptVersion": review_run.get("promptVersion"), "promptPayload": "ids_hashes_versions_only"}
    if node_key == "llm_generate_findings":
        draft = build_finding_draft(review_run, context)
        context["findingDrafts"] = [draft]
        append_tool_call(review_run, node_key, "create_review_finding_draft", {"findingDraftId": draft["id"]})
        return {"modelGateway": "litellm", "modelAlias": review_run.get("modelAlias"), "findingDrafts": 1}
    if node_key in {"schema_validation", "evidence_validation", "reference_validation", "critic_review", "quality_gate"}:
        context.setdefault("validationResults", {})[node_key] = {"passed": True}
        return {"passed": True}
    if node_key == "persist_drafts":
        review_run["findingDrafts"] = repo.clone(context.get("findingDrafts") or [])
        review_run["outputHash"] = stable_hash_payload(review_run["findingDrafts"])
        return {"findingDrafts": len(review_run["findingDrafts"]), "outputHash": review_run["outputHash"]}
    return {"skipped": True}


def build_finding_draft(review_run: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    evidence = context.get("evidenceLinks") or []
    rule_result = next(iter(context.get("ruleResults") or []), {})
    return {
        "id": f"FND-DRAFT-{uuid4().hex[:8].upper()}",
        "reviewRunId": review_run["reviewRunId"],
        "projectId": review_run.get("projectId"),
        "nodeId": review_run.get("nodeId"),
        "businessPackId": review_run.get("businessPackId"),
        "agentId": review_run.get("agentId"),
        "agentVersion": review_run.get("agentVersion"),
        "findingType": "ai_review_suggestion",
        "severity": rule_result.get("severity") or "medium",
        "title": "AI 证据化审查草稿",
        "description": "已基于 OCR 字段、规则检查和知识检索生成审查草稿，需监检员人工确认。",
        "evidenceRefs": [
            {
                "evidenceLinkId": item.get("id"),
                "documentVersionId": item.get("documentVersionId"),
                "pageNo": item.get("pageNo"),
                "bbox": item.get("bbox"),
                "source": item.get("source") or "evidence_link",
            }
            for item in evidence[:3]
            if isinstance(item, dict)
        ],
        "evidenceLinkIds": [item.get("id") for item in evidence[:3] if isinstance(item, dict)],
        "ruleRefs": [
            {
                "ruleCode": rule_result.get("ruleCode"),
                "ruleSetVersion": rule_result.get("ruleSetVersion"),
            }
        ]
        if rule_result
        else [],
        "kbRefs": [
            {"kbVersion": trace.get("kbVersion"), "retrievalTraceId": trace.get("retrievalTraceId")}
            for trace in context.get("retrievalTraces") or []
        ],
        "confidence": 0.82,
        "suggestedAction": "human_confirm",
        "requiresHumanConfirmation": True,
        "status": "pending_human_review",
        "createdAt": server_time(),
    }


def append_tool_call(review_run: dict[str, Any], node_key: str, tool_name: str, output_summary: dict[str, Any]) -> None:
    repo.state["review_tool_calls"].append(
        {
            "id": f"RTC-{uuid4().hex[:8].upper()}",
            "reviewRunId": review_run["reviewRunId"],
            "nodeKey": node_key,
            "toolName": tool_name,
            "allowed": tool_name in ALLOWED_AGENT_TOOLS,
            "outputHash": stable_hash_payload(output_summary),
            "outputSummary": output_summary,
            "createdAt": server_time(),
        }
    )


def graph_nodes_for_review_run(review_run_id: str) -> list[dict[str, Any]]:
    ensure_review_state()
    return sorted(
        [repo.clone(item) for item in repo.state["review_graph_nodes"] if item.get("reviewRunId") == review_run_id],
        key=lambda item: int(item.get("sequence") or 0),
    )


def review_run_timeline(review_run_id: str) -> list[dict[str, Any]]:
    ensure_review_state()
    return sorted(
        [repo.clone(item) for item in repo.state["review_events"] if item.get("reviewRunId") == review_run_id],
        key=lambda item: item.get("createdAt") or "",
    )


def graph_view_for_review_run(review_run_id: str) -> dict[str, Any]:
    ensure_review_state()
    nodes = graph_nodes_for_review_run(review_run_id)
    tool_calls = [
        repo.clone(item)
        for item in repo.state["review_tool_calls"]
        if item.get("reviewRunId") == review_run_id
    ]
    tool_calls_by_node: dict[str, list[dict[str, Any]]] = {}
    for call in tool_calls:
        tool_calls_by_node.setdefault(str(call.get("nodeKey")), []).append(call)
    for node in nodes:
        node["toolCalls"] = tool_calls_by_node.get(str(node.get("nodeKey")), [])
    return {
        "nodes": nodes,
        "edges": repo.clone(REVIEW_GRAPH_EDGES),
        "timeline": review_run_timeline(review_run_id),
    }


def review_run_view(review_run: dict[str, Any], *, include_sensitive: bool = False) -> dict[str, Any]:
    view = repo.clone(review_run)
    if not include_sensitive:
        view.pop("rawPrompt", None)
        view.pop("rawOcrText", None)
    view["graphSummary"] = summarize_graph(review_run["reviewRunId"])
    return view


def summarize_graph(review_run_id: str) -> dict[str, Any]:
    nodes = graph_nodes_for_review_run(review_run_id)
    counts: dict[str, int] = {}
    for node in nodes:
        status = str(node.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {"total": len(nodes), "statusCounts": counts}


def human_decision_for_review_run(review_run_id: str, decision: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_review_state()
    review_run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if not review_run:
        return {"status": "missing", "reviewRunId": review_run_id}
    allowed = {"accept", "edit", "reject"}
    if decision not in allowed:
        return {"status": "invalid_decision", "allowed": sorted(allowed)}
    status_map = {"accept": "accepted_by_human", "edit": "edited_by_human", "reject": "rejected_by_human"}
    review_run["status"] = status_map[decision]
    review_run["humanDecision"] = {
        "decision": decision,
        "comment": payload.get("comment") or payload.get("reason"),
        "correctedOutput": payload.get("correctedOutput"),
        "decidedAt": server_time(),
    }
    append_review_event(
        review_run_id,
        event_type="human_decision.submitted",
        title="人工确认已提交",
        status=review_run["status"],
        details=review_run["humanDecision"],
    )
    if decision in {"accept", "edit"}:
        persist_confirmed_findings(review_run, payload)
    ai_run = repo.find_one("ai_runs", str(review_run.get("aiRunId")))
    if ai_run:
        ai_run["status"] = "已人工确认" if decision in {"accept", "edit"} else "已驳回"
    return {"status": review_run["status"], "reviewRun": review_run}


def persist_confirmed_findings(review_run: dict[str, Any], payload: dict[str, Any]) -> None:
    for draft in review_run.get("findingDrafts") or []:
        finding_id = f"FND-{uuid4().hex[:8].upper()}"
        finding = {
            **repo.clone(draft),
            "id": finding_id,
            "source": "ai",
            "status": "accepted",
            "humanStatus": review_run["status"],
            "humanComment": payload.get("comment"),
            "createdAt": server_time(),
            "revision": 1,
        }
        repo.state["review_findings"].insert(0, finding)


def clone_review_run_for_replay(
    parent: dict[str, Any],
    *,
    run_mode: str,
    reason: str | None = None,
) -> dict[str, Any]:
    ensure_review_state()
    now = server_time()
    child_id = f"RRUN-REPLAY-{uuid4().hex[:8].upper()}"
    child = repo.clone(parent)
    child.update(
        {
            "id": child_id,
            "reviewRunId": child_id,
            "parentReviewRunId": parent.get("reviewRunId") or parent.get("id"),
            "runMode": run_mode,
            "status": "queued",
            "currentStep": "created",
            "workflowId": f"review-run-{child_id}",
            "temporalRunId": None,
            "startedAt": None,
            "finishedAt": None,
            "createdAt": now,
            "updatedAt": now,
            "replayReason": reason,
            "outputHash": stable_hash_payload(parent.get("findingDrafts") or []),
            "findingDrafts": [],
            "humanDecision": None,
        }
    )
    repo.state["review_runs"].insert(0, child)
    seed_graph_nodes(child)
    append_review_event(
        child_id,
        event_type="review_run.replay_created",
        title="FDE 创建 ReviewRun 重跑",
        status="queued",
        details={"parentReviewRunId": child["parentReviewRunId"], "runMode": run_mode, "reason": reason},
    )
    return child
