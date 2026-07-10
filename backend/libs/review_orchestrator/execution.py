from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any
from uuid import uuid4

from libs.business_pack import DEFAULT_BUSINESS_PACK_ID, build_ai_review_prompt, load_business_pack, matching_rule_for_node
from libs.contracts.responses import server_time
from libs.audit_runtime import audit_runtime_config, audit_runtime_for_run, audit_runtime_public_config
from libs.db.repository import flush_state_records, repo
from libs.integrations.errors import IntegrationServiceError
from libs.integrations.litellm_client import LiteLLMClient, production_mode_enabled
from libs.knowledge_retrieval import retrieve_knowledge_clauses
from libs.qwen_runtime import QwenRuntimeClient, qwen_runtime_config, qwen_runtime_public_config
from libs.review_grounding import apply_grounding_guardrails, build_grounded_review_input, grounding_prompt_block
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog

REVIEW_GRAPH_STEPS: list[dict[str, Any]] = [
    {"key": "load_context", "label": "加载项目上下文", "taskQueue": "review.graph"},
    {"key": "load_ocr_result", "label": "加载 OCR 证据", "taskQueue": "review.graph"},
    {"key": "run_rule_engine", "label": "执行确定性规则", "taskQueue": "review.validation"},
    {"key": "retrieve_knowledge", "label": "检索知识依据", "taskQueue": "review.retrieval"},
    {"key": "build_prompt", "label": "构造审查 Prompt", "taskQueue": "review.graph"},
    {"key": "llm_generate_findings", "label": "QwenRuntime 生成审查草稿", "taskQueue": "review.llm"},
    {"key": "schema_validation", "label": "Schema 校验", "taskQueue": "review.validation"},
    {"key": "evidence_validation", "label": "证据校验", "taskQueue": "review.validation"},
    {"key": "reference_validation", "label": "依据校验", "taskQueue": "review.validation"},
    {"key": "critic_review", "label": "Critic 复核", "taskQueue": "review.llm"},
    {"key": "quality_gate", "label": "质量门禁", "taskQueue": "review.validation"},
    {"key": "persist_drafts", "label": "持久化草稿", "taskQueue": "review.graph"},
]


def qwen_runtime_client() -> QwenRuntimeClient:
    config = qwen_runtime_config()
    server_client = LiteLLMClient() if config["mode"] == "server" or config.get("allowFallbackToServer") else None
    return QwenRuntimeClient(config=config, server_client=server_client)

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
    "ai_feedback",
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
    "recognize_document_seals",
    "search_project_documents",
    "extract_structured_fields",
    "extract_welder_certificate",
    "verify_license_or_certificate",
    "verify_welder_certificate_authenticity",
    "run_rule_engine",
    "retrieve_clauses",
    "search_knowledge_base",
    "call_qwen_runtime_chat",
    "create_review_finding_draft",
    "create_ai_diagnostic",
}


def ensure_review_state() -> None:
    for collection in REVIEW_STATE_COLLECTIONS:
        repo.state.setdefault(collection, [])


def stable_hash_payload(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def review_rule_node_ids(rule: dict[str, Any]) -> set[int]:
    node_ids: set[int] = set()
    for raw in rule.get("nodeIds") or []:
        if str(raw).isdigit():
            node_ids.add(int(raw))
    return node_ids


def current_published_rule_for_node(node_id: int, *, business_pack_id: str | None = None) -> dict[str, Any] | None:
    candidates = []
    for rule in repo.state.get("rule_versions", []):
        if rule.get("status") != "已发布":
            continue
        if node_id not in review_rule_node_ids(rule):
            continue
        if business_pack_id and rule.get("businessPackId") not in {None, "", business_pack_id}:
            continue
        candidates.append(rule)
    candidates.sort(
        key=lambda item: str(item.get("publishedAt") or item.get("updatedAt") or item.get("importedAt") or ""),
        reverse=True,
    )
    return repo.clone(candidates[0]) if candidates else None


def review_task_queues() -> dict[str, str]:
    return {
        "workflow": os.getenv("AICHECK_REVIEW_WORKFLOW_TASK_QUEUE", "review.workflow"),
        "graph": os.getenv("AICHECK_REVIEW_GRAPH_TASK_QUEUE", "review.graph"),
        "llm": os.getenv("AICHECK_REVIEW_LLM_TASK_QUEUE", "review.llm"),
        "retrieval": os.getenv("AICHECK_REVIEW_RETRIEVAL_TASK_QUEUE", "review.retrieval"),
        "validation": os.getenv("AICHECK_REVIEW_VALIDATION_TASK_QUEUE", "review.validation"),
    }


def review_run_state_records(review_run_id: str) -> dict[str, list[dict[str, Any]]]:
    review_run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one(
        "review_runs", review_run_id
    )
    if not review_run:
        return {}
    ai_run_id = str(review_run.get("aiRunId") or "")
    project_id = str(review_run.get("projectId") or "")
    node_id = int(review_run.get("nodeId") or 0)
    records: dict[str, list[dict[str, Any]]] = {"review_runs": [review_run]}
    for collection in REVIEW_STATE_COLLECTIONS:
        if collection == "review_runs":
            continue
        records[collection] = [
            item
            for item in repo.state.get(collection, [])
            if str(item.get("reviewRunId") or "") == review_run_id
        ]
    records["ai_runs"] = [
        item for item in repo.state.get("ai_runs", []) if ai_run_id and str(item.get("id") or "") == ai_run_id
    ]
    records["ai_trace_steps"] = [
        item
        for item in repo.state.get("ai_trace_steps", [])
        if ai_run_id and str(item.get("aiRunId") or "") == ai_run_id
    ]
    records["review_findings"] = [
        item
        for item in repo.state.get("review_findings", [])
        if str(item.get("reviewRunId") or "") == review_run_id
    ]
    records["tree_nodes"] = [
        item
        for item in repo.state.get("tree_nodes", [])
        if str(item.get("projectId") or "") == project_id and int(item.get("nodeId") or 0) == node_id
    ]
    return records


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
    audit_runtime = audit_runtime_public_config(mode=str(ai_run.get("auditInputMode") or "") or None)
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
        "modelGateway": "qwen_runtime",
        "auditInputMode": audit_runtime["mode"],
        "auditRuntime": audit_runtime,
        "reviewMode": ai_run.get("reviewMode") or "formal",
        "advisoryOnly": bool(ai_run.get("advisoryOnly")),
        "confidenceScale": "ratio",
        "operationId": ai_run.get("operationId"),
        "previousNodeStatus": ai_run.get("previousNodeStatus"),
        "stateTransition": repo.clone(ai_run.get("stateTransition") or {}),
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
            "rawTextStorage": "postgres_minio_with_fde_grants",
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
    # Temporal may schedule the worker before the API response middleware runs.
    # Persist the run and its graph first so the worker can load it cross-process.
    flush_state_records(review_run_state_records(review_run_id))
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
        label = step["label"]
        if step["key"] == "load_ocr_result" and str(review_run.get("auditInputMode") or "") == "pure_llm":
            label = "跳过 OCR 证据（纯 LLM）"
        repo.state["review_graph_nodes"].append(
            {
                "id": f"RGNODE-{uuid4().hex[:8].upper()}",
                "reviewRunId": review_run["reviewRunId"],
                "aiRunId": review_run.get("aiRunId"),
                "nodeKey": step["key"],
                "label": label,
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
        repo.state["review_step_runs"].append(
            {
                "id": f"RSTEP-{uuid4().hex[:8].upper()}",
                "reviewRunId": review_run_id,
                "nodeKey": node_key,
                "attempt": node["attempt"],
                "status": "running",
                "startedAt": now,
                "createdAt": now,
            }
        )
    if status in {"succeeded", "failed", "skipped"}:
        node["finishedAt"] = now
        step_run = next(
            (
                item
                for item in reversed(repo.state["review_step_runs"])
                if item.get("reviewRunId") == review_run_id
                and item.get("nodeKey") == node_key
                and item.get("status") == "running"
            ),
            None,
        )
        if step_run:
            step_run["status"] = status
            step_run["finishedAt"] = now
            if details:
                step_run["outputHash"] = stable_hash_payload(details)
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
        from .graph import execute_review_graph

        graph_execution = execute_review_graph(
            review_run,
            context,
            steps=REVIEW_GRAPH_STEPS,
            run_step=run_step,
            mark_graph_node=mark_graph_node,
        )
        review_run["graphExecution"] = graph_execution
        review_run["graphRunner"] = graph_execution["runner"]
        review_run["graphEngine"] = "langgraph" if graph_execution.get("runner") == "langgraph" else "langgraph_fallback"
        review_run["status"] = "waiting_human_review"
        review_run["currentStep"] = "waiting_human_review"
        review_run["finishedAt"] = server_time()
        review_run["updatedAt"] = review_run["finishedAt"]
        review_run["outputHash"] = stable_hash_payload(review_run.get("findingDrafts") or [])
        append_review_event(
            review_run_id,
            event_type="review_run.waiting_human",
            title="等待人工确认",
            status="waiting_human_review",
            details={"graphExecution": graph_execution},
        )
        if ai_run:
            ai_run["status"] = "完成"
            ai_run["finishedAt"] = review_run["finishedAt"]
            ai_run["findingDrafts"] = repo.clone(review_run.get("findingDrafts") or [])
            ai_run["evidenceLinks"] = repo.clone(context.get("evidenceLinks") or [])
            ai_run["reviewRunId"] = review_run.get("reviewRunId")
            ai_run["promptAudit"] = repo.clone(review_run.get("promptAudit") or context.get("promptShape") or {})
            ai_run["llmConversationId"] = review_run.get("llmConversationId")
            ai_run["llmMetadata"] = repo.clone(review_run.get("llmMetadata") or {})
            ai_run["reasoningProcess"] = (ai_run.get("llmMetadata") or {}).get("reasoningProcess")
            ai_run["llmResultText"] = (ai_run.get("llmMetadata") or {}).get("resultText")
            ai_run.setdefault("suggestion", {}).update(
                {
                    "result": "需人工确认",
                    "opinionDraft": (review_run.get("findingDrafts") or [{}])[0].get("description", "AI 审查草稿已生成。"),
                    "confidence": (review_run.get("findingDrafts") or [{}])[0].get("confidence", 0.82),
                    "manualConfirmItems": ["证据链、规则依据和条款适用性"],
                }
            )
            repo.state.setdefault("ai_trace_steps", []).append(
                {
                    "id": f"TRACE-{ai_run['id']}-LLM-{uuid4().hex[:6].upper()}",
                    "aiRunId": ai_run["id"],
                    "traceId": f"TRACE-{ai_run['id']}",
                    "sequence": len([item for item in repo.state.get("ai_trace_steps", []) if item.get("aiRunId") == ai_run["id"]]) + 1,
                    "stepType": "llm_review",
                    "name": "记录 LLM 对话与 Prompt 审计元数据",
                    "status": "completed",
                    "conversationId": ai_run.get("llmConversationId"),
                    "promptHash": (ai_run.get("llmMetadata") or {}).get("promptHash"),
                    "responseHash": (ai_run.get("llmMetadata") or {}).get("responseHash"),
                    "reasoningProcess": ai_run.get("reasoningProcess"),
                    "resultText": ai_run.get("llmResultText"),
                    "createdAt": server_time(),
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
        if not review_run.get("advisoryOnly"):
            previous_status = str(review_run.get("previousNodeStatus") or "")
            repo.set_node_status(
                str(review_run.get("projectId")),
                int(review_run.get("nodeId") or 0),
                "待人工确认",
            )
            transition = {
                "from": "业务核验中",
                "to": "待人工确认",
                "reason": "formal_review_waiting_human_review",
                "previousStableStatus": previous_status or None,
            }
            review_run["stateTransition"] = transition
            if ai_run:
                ai_run["stateTransition"] = repo.clone(transition)
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
        if not review_run.get("advisoryOnly"):
            previous_status = str(review_run.get("previousNodeStatus") or "待人工确认")
            repo.set_node_status(
                str(review_run.get("projectId")),
                int(review_run.get("nodeId") or 0),
                previous_status,
            )
            transition = {
                "from": "业务核验中",
                "to": previous_status,
                "reason": "formal_review_failed_restored_previous_status",
            }
            review_run["stateTransition"] = transition
            if ai_run:
                ai_run["stateTransition"] = repo.clone(transition)
        return {"reviewRunId": review_run_id, "status": "failed", "errorMessage": str(exc)}


def run_step(review_run: dict[str, Any], node_key: str, context: dict[str, Any]) -> dict[str, Any]:
    audit_runtime = audit_runtime_for_run(review_run)
    context["auditRuntime"] = audit_runtime
    if node_key == "load_context":
        project = repo.require_project(str(review_run.get("projectId")))
        node = repo.node(str(review_run.get("projectId")), int(review_run.get("nodeId") or 0))
        context["project"] = project or {}
        context["node"] = node or {}
        return {"projectId": review_run.get("projectId"), "nodeId": review_run.get("nodeId"), "nodeName": (node or {}).get("name")}
    if node_key == "load_ocr_result":
        version_ids = set(review_run.get("inputDocumentVersionIds") or [])
        if not audit_runtime["useOcrEvidence"]:
            grounding_input = pure_llm_grounding_input(version_ids, audit_runtime)
            context["groundingInput"] = grounding_input
            context["fields"] = []
            context["tables"] = []
            context["seals"] = []
            context["fragments"] = []
            context["evidenceLinks"] = []
            context.setdefault("runtimeToolResults", {})["audit_runtime"] = {
                "toolName": "audit_runtime",
                "status": "skipped_ocr",
                "auditInputMode": audit_runtime["mode"],
                "groundingPolicy": audit_runtime["groundingPolicy"],
            }
            return {
                "auditInputMode": audit_runtime["mode"],
                "sourceMethod": "pure_llm_review",
                "ocrSkipped": True,
                "fieldCount": 0,
                "tableCount": 0,
                "sealCount": 0,
                "recognizedSealCount": 0,
                "welderCertificateCount": 0,
                "fragmentCount": 0,
                "evidenceLinkCount": 0,
                "groundingStatus": grounding_input.get("groundingStatus"),
                "reviewWarnings": grounding_input.get("reviewWarnings") or [],
            }
        grounding_input = build_grounded_review_input(repo.state, version_ids)
        fields = grounding_input.get("fields") or []
        evidence_links = grounding_input.get("evidenceLinks") or []
        context["groundingInput"] = grounding_input
        context["fields"] = fields
        context["tables"] = grounding_input.get("tables") or []
        context["seals"] = grounding_input.get("seals") or []
        context["fragments"] = grounding_input.get("fragments") or []
        context["evidenceLinks"] = evidence_links
        summary = grounding_input.get("summary") or {}
        ocr_tool = execute_agent_tool(
            review_run,
            node_key,
            "get_document_ocr_result",
            {"documentVersionIds": sorted(version_ids)},
            context,
        )
        seal_tool = execute_agent_tool(
            review_run,
            node_key,
            "recognize_document_seals",
            {"documentVersionIds": sorted(version_ids)},
            context,
        )
        structured_tool = execute_agent_tool(
            review_run,
            node_key,
            "extract_structured_fields",
            {"documentVersionIds": sorted(version_ids), "materialTypeCode": "welder_certificate"},
            context,
        )
        context.setdefault("runtimeToolResults", {})["get_document_ocr_result"] = ocr_tool
        context["runtimeToolResults"]["recognize_document_seals"] = seal_tool
        context["runtimeToolResults"]["extract_structured_fields"] = structured_tool
        return {
            "fieldCount": summary.get("fieldCount", len(fields)),
            "tableCount": summary.get("tableCount", 0),
            "sealCount": summary.get("sealCount", 0),
            "recognizedSealCount": seal_tool.get("sealCount", 0),
            "welderCertificateCount": structured_tool.get("welderCertificateCount", 0),
            "fragmentCount": summary.get("fragmentCount", 0),
            "evidenceLinkCount": summary.get("evidenceLinkCount", len(evidence_links)),
            "groundingStatus": grounding_input.get("groundingStatus"),
        }
    if node_key == "run_rule_engine":
        pack = load_business_pack(str(review_run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID))
        rule = (
            current_published_rule_for_node(
                int(review_run.get("nodeId") or 0),
                business_pack_id=str(review_run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID),
            )
            or matching_rule_for_node(pack, int(review_run.get("nodeId") or 0))
            or next(iter(pack.get("ruleSets") or []), {})
        )
        rule_basis = retrieve_knowledge_clauses(
            repo.state,
            query=str(rule.get("criteria") or rule.get("checkMethod") or rule.get("name") or "审查依据"),
            review_run_id=review_run["reviewRunId"],
            business_pack_id=str(review_run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID),
            node_id=int(review_run.get("nodeId") or 0),
            kb_version=str(review_run.get("kbVersion") or "inspection_kb@1.0.0"),
            top_k=3,
            query_type="rule_basis_search",
        )
        linked_clause_ids = [item.get("clauseId") for item in rule_basis.get("clauses") or [] if item.get("clauseId")]
        result = {
            "id": f"RCHK-{uuid4().hex[:8].upper()}",
            "reviewRunId": review_run["reviewRunId"],
            "ruleCode": rule.get("ruleKey") or rule.get("id") or "generic-review",
            "ruleSetVersion": rule.get("version") or review_run.get("ruleSetVersion"),
            "result": "passed" if context.get("fields") else "advisory" if audit_runtime["mode"] == "pure_llm" else "warning",
            "severity": rule.get("severity") or "medium",
            "message": (
                "规则检查完成，待人工确认。"
                if context.get("fields")
                else "纯 LLM 模式未加载 OCR 证据，规则结果仅作为人工复核提示。"
                if audit_runtime["mode"] == "pure_llm"
                else "未发现可用 OCR 字段，需人工复核。"
            ),
            "linkedClauseIds": linked_clause_ids,
            "evidenceRefs": [{"source": "ocr_fields", "count": len(context.get("fields") or [])}],
            "suggestedAction": "human_confirm",
            "createdAt": server_time(),
        }
        repo.state["rule_check_results"].append(result)
        context["currentRule"] = rule
        context["ruleResults"] = [result]
        verification_tool = execute_agent_tool(
            review_run,
            node_key,
            "verify_license_or_certificate",
            {
                "documentVersionIds": list(review_run.get("inputDocumentVersionIds") or []),
                "materialTypeCode": "welder_certificate",
            },
            context,
        )
        context.setdefault("runtimeToolResults", {})[
            "verify_license_or_certificate"
        ] = verification_tool
        append_tool_call(
            review_run,
            node_key,
            "run_rule_engine",
            {"ruleCode": result["ruleCode"], "result": result["result"]},
        )
        return {
            "ruleResults": 1,
            "ruleCode": result["ruleCode"],
            "result": result["result"],
            "linkedClauseIds": linked_clause_ids,
            "certificateVerificationCount": verification_tool.get("verificationCount", 0),
        }
    if node_key == "retrieve_knowledge":
        retrieval = retrieve_knowledge_clauses(
            repo.state,
            query=f"{context.get('node', {}).get('name') or '节点'} 审查依据",
            review_run_id=review_run["reviewRunId"],
            business_pack_id=str(review_run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID),
            node_id=int(review_run.get("nodeId") or 0),
            kb_version=str(review_run.get("kbVersion") or "inspection_kb@1.0.0"),
            top_k=5,
        )
        trace = retrieval["trace"]
        repo.state["retrieval_traces"].append(trace)
        context["retrievalTraces"] = [trace]
        context["knowledgeClauses"] = retrieval["clauses"]
        append_tool_call(review_run, node_key, "search_knowledge_base", {"retrievalTraceId": trace["retrievalTraceId"]})
        return {"retrievalTraceId": trace["retrievalTraceId"], "selectedClauses": len(trace.get("selectedClauses") or [])}
    if node_key == "build_prompt":
        prompt_shape = build_review_prompt_shape(review_run, context)
        context["promptShape"] = prompt_shape
        review_run["promptAudit"] = repo.clone(prompt_shape)
        return prompt_shape
    if node_key == "llm_generate_findings":
        drafts, llm_details = generate_finding_drafts(review_run, context)
        context["findingDrafts"] = drafts
        for draft in drafts:
            append_tool_call(review_run, node_key, "create_review_finding_draft", {"findingDraftId": draft["id"]})
        return {"modelGateway": "qwen_runtime", "modelAlias": review_run.get("modelAlias"), "findingDrafts": len(drafts), **llm_details}
    if node_key == "schema_validation":
        result = validate_review_schema(context.get("findingDrafts") or [])
        context.setdefault("validationResults", {})[node_key] = result
        return result
    if node_key == "evidence_validation":
        drafts = context.get("findingDrafts") or []
        result = validate_review_evidence_refs(
            drafts,
            context.get("evidenceLinks") or [],
            audit_runtime=audit_runtime,
        )
        mismatched_indexes = {
            int(failure.get("index"))
            for failure in result.get("failures") or []
            if failure.get("code") == "CLAIM_TO_EVIDENCE_MISMATCH" and failure.get("index") is not None
        }
        for index in mismatched_indexes:
            if 0 <= index < len(drafts):
                draft = drafts[index]
                draft["groundingStatus"] = "insufficient_evidence"
                draft["confidence"] = min(float(draft.get("confidence") or 0), 0.55)
                draft["requiresHumanConfirmation"] = True
                draft.setdefault("unsupportedClaims", []).append("claim_to_evidence_mismatch")
                draft["description"] = "证据不足，需人工确认；审查草稿中的关键数字、日期、证书号、标准号或单位名未能在引用证据中匹配。"
        context.setdefault("validationResults", {})[node_key] = result
        return result
    if node_key == "reference_validation":
        result = validate_review_references(
            context.get("findingDrafts") or [],
            context.get("ruleResults") or [],
            context.get("retrievalTraces") or [],
        )
        context.setdefault("validationResults", {})[node_key] = result
        return result
    if node_key == "critic_review":
        result = critic_review_findings(context.get("findingDrafts") or [])
        context.setdefault("validationResults", {})[node_key] = result
        return result
    if node_key == "quality_gate":
        result = review_quality_gate(context.get("findingDrafts") or [], context.get("validationResults") or {})
        context.setdefault("validationResults", {})[node_key] = result
        review_run["qualityGate"] = result
        append_review_event(
            review_run["reviewRunId"],
            event_type="quality_gate.evaluated",
            title="审查质量门禁已评估",
            status="passed" if result.get("passed") else "needs_human_review",
            node_key=node_key,
            details=result,
        )
        return result
    if node_key == "persist_drafts":
        review_run["findingDrafts"] = repo.clone(context.get("findingDrafts") or [])
        review_run["outputHash"] = stable_hash_payload(review_run["findingDrafts"])
        return {"findingDrafts": len(review_run["findingDrafts"]), "outputHash": review_run["outputHash"]}
    return {"skipped": True}


def review_llm_execution_mode() -> str:
    configured = os.getenv("AICHECK_REVIEW_LLM_EXECUTION", "").strip().lower()
    if configured:
        return configured
    if production_mode_enabled() or os.getenv("AICHECK_REVIEW_ORCHESTRATION", "").strip().lower() == "temporal":
        return "litellm"
    return "deterministic"


def pure_llm_grounding_input(version_ids: set[str], audit_runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "PureLlmReviewInput@1.0.0",
        "documentVersionIds": sorted(version_ids),
        "auditInputMode": audit_runtime["mode"],
        "groundingPolicy": audit_runtime["groundingPolicy"],
        "groundingStatus": "insufficient_evidence",
        "blockingIssues": [
            {
                "code": "PURE_LLM_REVIEW_NO_OCR_EVIDENCE",
                "message": "This audit run is configured to skip OCR evidence; all findings are advisory and require human confirmation.",
            }
        ],
        "fields": [],
        "tables": [],
        "seals": [],
        "fragments": [],
        "evidenceLinks": [],
        "quality": [],
        "evidenceTextCorpus": [],
        "summary": {
            "fieldCount": 0,
            "tableCount": 0,
            "sealCount": 0,
            "fragmentCount": 0,
            "evidenceLinkCount": 0,
            "lowConfidenceEvidenceCount": 0,
            "missingPositionEvidenceCount": 0,
            "tableContentMissingCount": 0,
            "sealTextRiskCount": 0,
            "criticalQualityFlagCount": 0,
            "blockingIssueCount": 1,
            "groundingStatus": "insufficient_evidence",
            "auditInputMode": audit_runtime["mode"],
        },
        "reviewWarnings": [
            {
                "code": "PURE_LLM_REVIEW_ADVISORY_ONLY",
                "message": "Pure LLM mode does not provide OCR/page/bbox evidence and cannot support automatic compliance conclusions.",
            }
        ],
    }


def select_prompt_template(review_run: dict[str, Any]) -> dict[str, Any] | None:
    templates = [item for item in repo.state.get("prompt_templates", []) if isinstance(item, dict)]
    if not templates:
        return None
    prompt_version = str(review_run.get("promptVersion") or "")
    business_pack_id = str(review_run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID)
    candidates = [
        item
        for item in templates
        if item.get("status") in {"production", "published", "active", "启用", "已发布"}
        and item.get("businessPackId") in {None, "", business_pack_id}
    ]
    exact = next(
        (
            item
            for item in candidates
            if prompt_version
            and (
                item.get("id") == prompt_version
                or item.get("promptVersionId") == prompt_version
                or item.get("version") == prompt_version
            )
        ),
        None,
    )
    if exact:
        return repo.clone(exact)
    return repo.clone(candidates[0] if candidates else templates[0])


def build_review_prompt_parts(review_run: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    audit_runtime = context.get("auditRuntime") or audit_runtime_for_run(review_run)
    context["auditRuntime"] = audit_runtime
    pack = load_business_pack(str(review_run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID))
    node = context.get("node") or {}
    fields = context.get("fields") or []
    grounding_input = context.get("groundingInput") or build_grounded_review_input(
        repo.state,
        set(review_run.get("inputDocumentVersionIds") or []),
    )
    context["groundingInput"] = grounding_input
    grounding_block = grounding_prompt_block(grounding_input)
    rule_result = next(iter(context.get("ruleResults") or []), {})
    current_rule = context.get("currentRule") or rule_result
    prompt_template = select_prompt_template(review_run)
    prompt = build_ai_review_prompt(
        pack,
        node=node,
        fields=fields,
        rule=current_rule,
        prompt_template=prompt_template,
    )
    user_payload = {
        "task": "Generate ReviewFindingDraftList JSON only.",
        "auditInputMode": audit_runtime["mode"],
        "auditRuntime": audit_runtime_public_config(mode=audit_runtime["mode"]),
        "availableRuntimeTools": runtime_tool_catalog(),
        "runtimeToolResults": {
            key: compact_tool_output(value)
            for key, value in (context.get("runtimeToolResults") or {}).items()
            if isinstance(value, dict)
        },
        "requirements": [
            "Every finding must require human confirmation.",
            "Do not approve, reject, issue correction, close correction, archive, or change business status.",
            "Use evidenceRefs, ruleRefs, and kbRefs from the supplied IDs only.",
            "When more evidence is needed, plan only with availableRuntimeTools "
            "and do not invent tools.",
            *grounding_block["requirements"],
        ],
        "strictGroundingPolicy": grounding_block["strictGroundingPolicy"],
        "projectId": review_run.get("projectId"),
        "nodeId": review_run.get("nodeId"),
        "fieldCount": len(fields),
        "groundingStatus": grounding_input.get("groundingStatus"),
        "groundedOcrEvidence": grounding_block["groundedOcrEvidence"],
        "ruleResults": context.get("ruleResults") or [],
        "retrievalTraceIds": [item.get("retrievalTraceId") for item in context.get("retrievalTraces") or []],
        "evidenceLinkIds": [item.get("id") for item in context.get("evidenceLinks") or []],
        "plannerPrompt": (prompt.get("template") or {}).get("plannerPrompt") or "",
        "criticPrompt": (prompt.get("template") or {}).get("criticPrompt") or "",
        "outputSchema": {
            "findings": [
                {
                    "findingType": "string",
                    "severity": "low|medium|high",
                    "title": "string",
                    "description": "string",
                    "evidenceRefs": [{"evidenceLinkId": "string", "documentVersionId": "string", "pageNo": "number", "bbox": [0, 0, 0, 0]}],
                    "ruleRefs": [{"ruleCode": "string", "ruleSetVersion": "string"}],
                    "kbRefs": [{"retrievalTraceId": "string", "clauseIds": ["string"]}],
                    "confidence": "0..1",
                    "suggestedAction": "human_confirm|request_correction",
                    "groundingStatus": "grounded|insufficient_evidence",
                    "unsupportedClaims": [],
                }
            ]
        },
    }
    review_task_json = json.dumps(user_payload, ensure_ascii=False)
    user_content = prompt["user"]
    if "{{reviewTaskJson}}" in user_content:
        user_content = user_content.replace("{{reviewTaskJson}}", review_task_json)
    else:
        user_content = user_content + "\n\n" + review_task_json
    messages = [
        {"role": "system", "content": prompt["system"]},
        {"role": "user", "content": user_content},
    ]
    return {
        "messages": messages,
        "promptTemplate": prompt_template,
        "prompt": prompt,
        "userPayload": user_payload,
        "pack": pack,
    }


def build_review_prompt_shape(review_run: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    project = context.get("project") or {}
    node = context.get("node") or {}
    fields = context.get("fields") or []
    rule_result = next(iter(context.get("ruleResults") or []), {})
    parts = build_review_prompt_parts(review_run, context)
    grounding_input = context.get("groundingInput") or {}
    audit_runtime = context.get("auditRuntime") or audit_runtime_for_run(review_run)
    grounding_summary = grounding_input.get("summary") or {}
    messages = parts["messages"]
    prompt_template = parts.get("promptTemplate") or {}
    prompt = parts.get("prompt") or {}
    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]
    return {
        "system": "review_agent_sop",
        "promptVersion": review_run.get("promptVersion"),
        "promptTemplateId": prompt_template.get("id"),
        "promptTemplateName": prompt_template.get("name"),
        "promptTemplateVersion": prompt_template.get("version"),
        "schemaVersion": review_run.get("schemaVersion"),
        "payloadHash": stable_hash_payload(
            {
                "projectId": project.get("id") or review_run.get("projectId"),
                "nodeId": node.get("id") or review_run.get("nodeId"),
                "fieldCount": len(fields),
                "tableCount": grounding_summary.get("tableCount", 0),
                "sealCount": grounding_summary.get("sealCount", 0),
                "fragmentCount": grounding_summary.get("fragmentCount", 0),
                "groundingStatus": grounding_input.get("groundingStatus"),
                "auditInputMode": audit_runtime["mode"],
                "ruleCode": rule_result.get("ruleCode"),
                "kbVersion": review_run.get("kbVersion"),
            }
        ),
        "messagesHash": stable_hash_payload(messages),
        "systemPrompt": system_prompt,
        "userPrompt": user_prompt,
        "plannerPrompt": (prompt.get("template") or {}).get("plannerPrompt") or "",
        "criticPrompt": (prompt.get("template") or {}).get("criticPrompt") or "",
        "messages": messages,
        "payloadPolicy": "full_prompt_stored_for_audit",
    }


def build_review_messages(review_run: dict[str, Any], context: dict[str, Any]) -> list[dict[str, str]]:
    return build_review_prompt_parts(review_run, context)["messages"]


def generate_finding_drafts(review_run: dict[str, Any], context: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mode = review_llm_execution_mode()
    if mode in {"deterministic", "disabled", "mock"}:
        prompt_shape = context.get("promptShape") or build_review_prompt_shape(review_run, context)
        metadata = {
            "llmExecution": mode,
            "llmCalled": False,
            "conversationId": None,
            "promptHash": prompt_shape.get("messagesHash") or prompt_shape.get("payloadHash"),
            "reasoningProcess": "本地确定性模式，未调用外部 LLM；基于规则结果生成待人工确认草稿。",
            "resultText": "",
        }
        review_run["llmMetadata"] = repo.clone(metadata)
        drafts = apply_grounding_guardrails([build_finding_draft(review_run, context)], context.get("groundingInput") or {})
        return drafts, metadata
    messages = build_review_messages(review_run, context)
    qwen_runtime = qwen_runtime_public_config()
    try:
        response = qwen_runtime_client().chat_sync(
            messages,
            model=str(review_run.get("modelAlias") or "review-chat"),
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=max(256, int(os.getenv("AICHECK_QWEN_REVIEW_MAX_TOKENS", "1600"))),
            timeout=max(30.0, float(os.getenv("AICHECK_QWEN_REVIEW_TIMEOUT_SECONDS", "180"))),
        )
    except IntegrationServiceError:
        raise
    except Exception as exc:
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason=exc.__class__.__name__) from exc
    content = QwenRuntimeClient.first_message_text(response)
    message = ((response.get("choices") or [{}])[0].get("message") or {}) if isinstance(response.get("choices"), list) else {}
    conversation_id = str(
        response.get("id")
        or response.get("conversation_id")
        or response.get("conversationId")
        or f"llm-{stable_hash_payload(response)[7:23]}"
    )
    reasoning_process = str(
        message.get("reasoning_content")
        or message.get("reasoning")
        or message.get("reasoningSummary")
        or "模型返回结构化审查草稿；未返回单独的公开推理摘要。"
    )
    response_hash = stable_hash_payload(response)
    prompt_shape = context.get("promptShape") or build_review_prompt_shape(review_run, context)
    llm_metadata = {
        "llmExecution": "qwen_runtime",
        "llmCalled": True,
        "conversationId": conversation_id,
        "modelAlias": review_run.get("modelAlias"),
        "modelResolved": response.get("model") or review_run.get("modelAlias"),
        "qwenRuntime": qwen_runtime,
        "promptVersion": review_run.get("promptVersion"),
        "promptTemplateId": prompt_shape.get("promptTemplateId"),
        "promptHash": prompt_shape.get("messagesHash") or stable_hash_payload(messages),
        "responseHash": response_hash,
        "usage": response.get("usage") or {},
        "reasoningProcess": reasoning_process[:3000],
        "resultText": content[:4000],
        "auditInputMode": (context.get("auditRuntime") or audit_runtime_for_run(review_run))["mode"],
        "finishReason": ((response.get("choices") or [{}])[0] or {}).get("finish_reason")
        if isinstance(response.get("choices"), list)
        else None,
    }
    review_run["llmConversationId"] = conversation_id
    review_run["llmMetadata"] = repo.clone(llm_metadata)
    append_tool_call(
        review_run,
        "llm_generate_findings",
        "call_qwen_runtime_chat",
        {
            "modelAlias": review_run.get("modelAlias"),
            "modelResolved": response.get("model") or review_run.get("modelAlias"),
            "qwenRuntimeMode": qwen_runtime.get("mode"),
            "conversationId": conversation_id,
            "promptHash": llm_metadata["promptHash"],
            "responseHash": response_hash,
            "usage": response.get("usage") or {},
        },
    )
    drafts = normalize_llm_findings(review_run, context, content)
    return drafts, llm_metadata


def normalize_llm_findings(review_run: dict[str, Any], context: dict[str, Any], content: str) -> list[dict[str, Any]]:
    base = build_finding_draft(review_run, context)
    grounding_input = context.get("groundingInput") or {}
    if not content.strip():
        return apply_grounding_guardrails([base], grounding_input)
    try:
        parsed = json.loads(content)
    except ValueError:
        base["description"] = content[:800]
        base["llmResponseFormat"] = "free_text_wrapped"
        return apply_grounding_guardrails([base], grounding_input)
    raw_findings = parsed.get("findings") if isinstance(parsed, dict) else None
    if not isinstance(raw_findings, list) or not raw_findings:
        return apply_grounding_guardrails([base], grounding_input)
    drafts = []
    for item in raw_findings[:10]:
        if not isinstance(item, dict):
            continue
        draft = {**repo.clone(base)}
        draft["id"] = f"FND-DRAFT-{uuid4().hex[:8].upper()}"
        draft["findingType"] = str(item.get("findingType") or item.get("finding_type") or base["findingType"])
        draft["severity"] = str(item.get("severity") or base["severity"])
        draft["title"] = str(item.get("title") or base["title"])[:120]
        draft["description"] = str(item.get("description") or base["description"])[:1200]
        draft["confidence"] = bounded_confidence(item.get("confidence"), default=base["confidence"])
        draft["suggestedAction"] = str(item.get("suggestedAction") or item.get("suggested_action") or "human_confirm")
        draft["groundingStatus"] = str(item.get("groundingStatus") or item.get("grounding_status") or base.get("groundingStatus") or "")
        draft["unsupportedClaims"] = item.get("unsupportedClaims") if isinstance(item.get("unsupportedClaims"), list) else []
        draft["requiresHumanConfirmation"] = True
        draft["llmGenerated"] = True
        drafts.append(draft)
    return apply_grounding_guardrails(drafts or [base], grounding_input)


def bounded_confidence(value: Any, *, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if 1 < numeric <= 100:
        numeric /= 100
    return max(0.0, min(1.0, numeric))


REVIEW_FINDING_REQUIRED_FIELDS = {
    "id",
    "reviewRunId",
    "findingType",
    "severity",
    "title",
    "description",
    "evidenceRefs",
    "ruleRefs",
    "kbRefs",
    "confidence",
    "suggestedAction",
    "requiresHumanConfirmation",
    "groundingStatus",
    "unsupportedClaims",
}
REVIEW_FINDING_SEVERITIES = {"low", "medium", "high", "critical"}
REVIEW_FINDING_ACTIONS = {"human_confirm", "request_correction"}


def validation_payload(
    *,
    passed: bool,
    checked: int,
    failures: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "passed": passed,
        "checked": checked,
        "failures": failures or [],
        "warnings": warnings or [],
        "metrics": metrics or {},
    }


def validate_review_schema(drafts: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not drafts:
        failures.append({"code": "NO_FINDING_DRAFTS", "message": "ReviewRun must produce at least one finding draft."})
        return validation_payload(passed=False, checked=0, failures=failures)
    for index, draft in enumerate(drafts):
        missing = sorted(field for field in REVIEW_FINDING_REQUIRED_FIELDS if field not in draft)
        if missing:
            failures.append({"code": "FINDING_SCHEMA_MISSING_FIELDS", "index": index, "fields": missing})
        severity = str(draft.get("severity") or "")
        if severity not in REVIEW_FINDING_SEVERITIES:
            failures.append({"code": "FINDING_SCHEMA_BAD_SEVERITY", "index": index, "severity": severity})
        action = str(draft.get("suggestedAction") or "")
        if action not in REVIEW_FINDING_ACTIONS:
            failures.append({"code": "FINDING_SCHEMA_BAD_ACTION", "index": index, "suggestedAction": action})
        try:
            confidence = float(draft.get("confidence"))
        except (TypeError, ValueError):
            failures.append({"code": "FINDING_SCHEMA_BAD_CONFIDENCE", "index": index, "confidence": draft.get("confidence")})
        else:
            if confidence < 0 or confidence > 1:
                failures.append({"code": "FINDING_SCHEMA_CONFIDENCE_RANGE", "index": index, "confidence": confidence})
            if confidence < 0.7:
                warnings.append({"code": "LOW_CONFIDENCE_FINDING", "index": index, "confidence": confidence})
        if draft.get("requiresHumanConfirmation") is not True:
            failures.append({"code": "FINDING_MUST_REQUIRE_HUMAN_CONFIRMATION", "index": index})
        if not isinstance(draft.get("ruleRefs"), list):
            failures.append({"code": "FINDING_RULE_REFS_NOT_LIST", "index": index})
        if not isinstance(draft.get("kbRefs"), list):
            failures.append({"code": "FINDING_KB_REFS_NOT_LIST", "index": index})
        if not isinstance(draft.get("evidenceRefs"), list):
            failures.append({"code": "FINDING_EVIDENCE_REFS_NOT_LIST", "index": index})
        grounding_status = str(draft.get("groundingStatus") or "")
        if grounding_status not in {"grounded", "insufficient_evidence"}:
            failures.append({"code": "FINDING_SCHEMA_BAD_GROUNDING_STATUS", "index": index, "groundingStatus": grounding_status})
        if not isinstance(draft.get("unsupportedClaims"), list):
            failures.append({"code": "FINDING_UNSUPPORTED_CLAIMS_NOT_LIST", "index": index})
    return validation_payload(
        passed=not failures,
        checked=len(drafts),
        failures=failures,
        warnings=warnings,
        metrics={"findingCount": len(drafts)},
    )


def validate_bbox(value: Any) -> bool:
    if not isinstance(value, list | tuple) or len(value) != 4:
        return False
    try:
        x1, y1, x2, y2 = [float(item) for item in value]
    except (TypeError, ValueError):
        return False
    return x2 >= x1 and y2 >= y1 and x1 >= 0 and y1 >= 0


def normalize_claim_text(value: Any) -> str:
    text = str(value or "").upper()
    return re.sub(r"[\s\u3000:：/／\\\-_.，。,、()（）\[\]【】]+", "", text)


def extract_claim_tokens(draft: dict[str, Any]) -> list[str]:
    text = "\n".join(
        str(draft.get(key) or "")
        for key in ["title", "description", "opinionDraft", "resultText", "suggestedAction"]
    )
    patterns = [
        r"\b[A-Z]{1,6}\s*/?\s*T?\s*\d{2,6}(?:\.\d+)?(?:-\d{4})?\b",
        r"\bTS[A-Z0-9\-]{6,}\b",
        r"\bA\d{6,}\b",
        r"\b\d{4}[年\-/.]\d{1,2}[月\-/.]\d{1,2}日?\b",
        r"\b\d+(?:\.\d+)?\s*(?:%|MPA|MM|℃|级|类)\b",
        r"[\u4e00-\u9fa5]{2,30}(?:公司|院|中心|厂|集团|有限责任公司)",
    ]
    tokens: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            token = match if isinstance(match, str) else "".join(match)
            normalized = normalize_claim_text(token)
            if normalized and normalized not in tokens:
                tokens.append(normalized)
    return tokens[:20]


def evidence_text_corpus(evidence_links: list[dict[str, Any]], refs: list[dict[str, Any]]) -> str:
    ref_ids = {str(ref.get("evidenceLinkId")) for ref in refs if isinstance(ref, dict) and ref.get("evidenceLinkId")}
    rows = [
        item
        for item in evidence_links
        if isinstance(item, dict) and (not ref_ids or str(item.get("id") or "") in ref_ids)
    ]
    values: list[str] = []
    for row in rows:
        for key in ["quotedText", "fieldName", "fieldValue", "fileName", "standardCode", "reportNo", "conclusion"]:
            if row.get(key):
                values.append(str(row.get(key)))
        for item in row.get("matchedEvidenceItems") or []:
            values.append(str(item))
    return normalize_claim_text("\n".join(values))


def validate_review_evidence_refs(
    drafts: list[dict[str, Any]],
    evidence_links: list[dict[str, Any]],
    *,
    audit_runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime = audit_runtime or audit_runtime_config()
    if runtime.get("requireEvidenceRefs") is False:
        warnings = []
        for draft_index, draft in enumerate(drafts):
            if draft.get("evidenceRefs"):
                warnings.append(
                    {
                        "code": "PURE_LLM_EVIDENCE_REFS_IGNORED",
                        "index": draft_index,
                        "message": "Pure LLM mode does not require evidenceRefs; OCR/page/bbox evidence was not loaded.",
                    }
                )
        warnings.append(
            {
                "code": "PURE_LLM_REVIEW_ADVISORY_ONLY",
                "message": "Evidence validation is advisory because auditInputMode does not require OCR evidence.",
            }
        )
        return validation_payload(
            passed=True,
            checked=0,
            warnings=warnings,
            metrics={
                "evidenceRefCount": 0,
                "availableEvidenceLinks": len(evidence_links),
                "auditInputMode": runtime.get("mode"),
                "evidenceValidationMode": runtime.get("evidenceValidationMode"),
            },
        )
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    evidence_ids = {str(item.get("id")) for item in evidence_links if isinstance(item, dict) and item.get("id")}
    checked_refs = 0
    for draft_index, draft in enumerate(drafts):
        refs = draft.get("evidenceRefs") if isinstance(draft.get("evidenceRefs"), list) else []
        if not refs:
            warnings.append({"code": "NO_EVIDENCE_REFS", "index": draft_index, "message": "Finding has no direct evidence references."})
            continue
        claim_tokens = extract_claim_tokens(draft)
        if claim_tokens:
            corpus = evidence_text_corpus(evidence_links, refs)
            missing_tokens = [token for token in claim_tokens if token not in corpus]
            if missing_tokens:
                failures.append(
                    {
                        "code": "CLAIM_TO_EVIDENCE_MISMATCH",
                        "index": draft_index,
                        "missingTokens": missing_tokens[:10],
                        "message": "Finding contains explicit numbers/dates/certificates/standards/entities not found in cited evidence text.",
                    }
                )
        for ref_index, ref in enumerate(refs):
            checked_refs += 1
            if not isinstance(ref, dict):
                failures.append({"code": "EVIDENCE_REF_NOT_OBJECT", "index": draft_index, "refIndex": ref_index})
                continue
            evidence_link_id = ref.get("evidenceLinkId")
            if evidence_link_id and str(evidence_link_id) not in evidence_ids:
                failures.append({"code": "EVIDENCE_LINK_NOT_FOUND", "index": draft_index, "refIndex": ref_index, "evidenceLinkId": evidence_link_id})
            has_position = bool(ref.get("documentVersionId")) and ref.get("pageNo") is not None and validate_bbox(ref.get("bbox"))
            if not evidence_link_id and not has_position:
                failures.append({"code": "EVIDENCE_REF_MISSING_POSITION", "index": draft_index, "refIndex": ref_index})
            if ref.get("bbox") is not None and not validate_bbox(ref.get("bbox")):
                failures.append({"code": "EVIDENCE_REF_BAD_BBOX", "index": draft_index, "refIndex": ref_index, "bbox": ref.get("bbox")})
    return validation_payload(
        passed=not failures,
        checked=checked_refs,
        failures=failures,
        warnings=warnings,
        metrics={"evidenceRefCount": checked_refs, "availableEvidenceLinks": len(evidence_ids)},
    )


def validate_review_references(
    drafts: list[dict[str, Any]],
    rule_results: list[dict[str, Any]],
    retrieval_traces: list[dict[str, Any]],
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    rule_codes = {str(item.get("ruleCode")) for item in rule_results if isinstance(item, dict) and item.get("ruleCode")}
    trace_ids = {str(item.get("retrievalTraceId") or item.get("id")) for item in retrieval_traces if isinstance(item, dict)}
    clause_ids_by_trace = {
        str(item.get("retrievalTraceId") or item.get("id")): {
            str(clause.get("clauseId"))
            for clause in item.get("selectedClauses") or []
            if isinstance(clause, dict) and clause.get("clauseId")
        }
        for item in retrieval_traces
        if isinstance(item, dict)
    }
    checked_refs = 0
    for draft_index, draft in enumerate(drafts):
        rule_refs = draft.get("ruleRefs") if isinstance(draft.get("ruleRefs"), list) else []
        kb_refs = draft.get("kbRefs") if isinstance(draft.get("kbRefs"), list) else []
        if not rule_refs:
            failures.append({"code": "MISSING_RULE_REFS", "index": draft_index})
        if not kb_refs:
            warnings.append({"code": "MISSING_KB_REFS", "index": draft_index})
        for ref_index, ref in enumerate(rule_refs):
            checked_refs += 1
            if not isinstance(ref, dict):
                failures.append({"code": "RULE_REF_NOT_OBJECT", "index": draft_index, "refIndex": ref_index})
                continue
            rule_code = ref.get("ruleCode")
            if not rule_code or str(rule_code) not in rule_codes:
                failures.append({"code": "RULE_REF_NOT_FOUND", "index": draft_index, "refIndex": ref_index, "ruleCode": rule_code})
            if not ref.get("ruleSetVersion"):
                failures.append({"code": "RULE_REF_MISSING_VERSION", "index": draft_index, "refIndex": ref_index})
        for ref_index, ref in enumerate(kb_refs):
            checked_refs += 1
            if not isinstance(ref, dict):
                failures.append({"code": "KB_REF_NOT_OBJECT", "index": draft_index, "refIndex": ref_index})
                continue
            trace_id = ref.get("retrievalTraceId")
            if trace_id and str(trace_id) not in trace_ids:
                failures.append({"code": "KB_RETRIEVAL_TRACE_NOT_FOUND", "index": draft_index, "refIndex": ref_index, "retrievalTraceId": trace_id})
            allowed_clause_ids = clause_ids_by_trace.get(str(trace_id), set()) if trace_id else set()
            for clause_id in ref.get("clauseIds") or []:
                if allowed_clause_ids and str(clause_id) not in allowed_clause_ids:
                    failures.append({"code": "KB_CLAUSE_NOT_IN_TRACE", "index": draft_index, "refIndex": ref_index, "clauseId": clause_id})
            if not ref.get("kbVersion"):
                failures.append({"code": "KB_REF_MISSING_VERSION", "index": draft_index, "refIndex": ref_index})
    return validation_payload(
        passed=not failures,
        checked=checked_refs,
        failures=failures,
        warnings=warnings,
        metrics={"ruleResultCount": len(rule_results), "retrievalTraceCount": len(retrieval_traces)},
    )


def critic_review_findings(drafts: list[dict[str, Any]]) -> dict[str, Any]:
    warnings = []
    for index, draft in enumerate(drafts):
        if draft.get("suggestedAction") != "human_confirm" and draft.get("requiresHumanConfirmation") is not True:
            warnings.append({"code": "CRITIC_HIGH_RISK_ACTION_REQUIRES_HUMAN", "index": index})
    return validation_payload(
        passed=True,
        checked=len(drafts),
        warnings=warnings,
        metrics={"criticMode": "deterministic_guardrail"},
    )


def review_quality_gate(drafts: list[dict[str, Any]], validation_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    gate_names = ["schema_validation", "evidence_validation", "reference_validation"]
    blocking_failures = [
        {"gate": name, "failures": validation_results.get(name, {}).get("failures") or []}
        for name in gate_names
        if validation_results.get(name, {}).get("passed") is False
    ]
    warnings = []
    for result in validation_results.values():
        warnings.extend(result.get("warnings") or [])
    all_require_human = all(draft.get("requiresHumanConfirmation") is True for draft in drafts) if drafts else False
    if not all_require_human:
        blocking_failures.append({"gate": "human_confirmation", "failures": [{"code": "NOT_ALL_FINDINGS_REQUIRE_HUMAN"}]})
    passed = not blocking_failures
    return validation_payload(
        passed=passed,
        checked=len(drafts),
        failures=blocking_failures,
        warnings=warnings,
        metrics={
            "status": "ready_for_human_review" if passed else "needs_human_review",
            "requiresHumanReview": True,
            "validatedGates": gate_names,
        },
    )


def build_finding_draft(review_run: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    evidence = context.get("evidenceLinks") or []
    rule_result = next(iter(context.get("ruleResults") or []), {})
    grounding_input = context.get("groundingInput") or {}
    audit_runtime = context.get("auditRuntime") or audit_runtime_for_run(review_run)
    grounding_status = str(grounding_input.get("groundingStatus") or "insufficient_evidence")
    description = "已基于 OCR 字段、规则检查和知识检索生成审查草稿，需监检员人工确认。"
    confidence = 0.82
    source_method = "ocr_llm_review"
    if audit_runtime["mode"] == "pure_llm":
        description = "当前为纯 LLM 审计模式，未加载 OCR/page/bbox 证据；以下建议只能作为人工复核提示，不能作为自动审计结论。"
        confidence = 0.55
        source_method = "pure_llm_review"
    if grounding_status != "grounded":
        description = "当前 OCR 证据不足以支撑自动审查结论，需人工核对原件、字段、表格、印章和证据链。"
        confidence = 0.5
        if audit_runtime["mode"] == "pure_llm":
            description = "当前为纯 LLM 审计模式，未加载 OCR/page/bbox 证据；以下建议只能作为人工复核提示，不能作为自动审计结论。"
            confidence = 0.55
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
        "description": description,
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
            {
                "kbVersion": trace.get("kbVersion"),
                "retrievalTraceId": trace.get("retrievalTraceId"),
                "clauseIds": [item.get("clauseId") for item in trace.get("selectedClauses") or [] if item.get("clauseId")],
                "clauses": [
                    {
                        "clauseId": item.get("clauseId"),
                        "kbDocId": item.get("kbDocId"),
                        "clauseNo": item.get("clauseNo"),
                    }
                    for item in (trace.get("selectedClauses") or [])[:3]
                ],
            }
            for trace in context.get("retrievalTraces") or []
        ],
        "confidence": confidence,
        "suggestedAction": "human_confirm",
        "groundingStatus": grounding_status,
        "unsupportedClaims": [],
        "auditInputMode": audit_runtime["mode"],
        "sourceMethod": source_method,
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


def execute_agent_tool(
    review_run: dict[str, Any],
    node_key: str,
    tool_name: str,
    arguments: dict[str, Any] | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    if tool_name in FORBIDDEN_AGENT_TOOLS:
        result = {
            "toolName": tool_name,
            "status": "rejected",
            "errorCode": "FORBIDDEN_AGENT_TOOL",
        }
        append_tool_call(review_run, node_key, tool_name, result)
        return result
    if tool_name not in ALLOWED_AGENT_TOOLS:
        result = {
            "toolName": tool_name,
            "status": "rejected",
            "errorCode": "AGENT_TOOL_NOT_ALLOWED",
        }
        append_tool_call(review_run, node_key, tool_name, result)
        return result
    result = dispatch_runtime_tool(
        repo.state,
        tool_name,
        arguments or {},
        context={
            **context,
            "reviewRun": review_run,
            "inputDocumentVersionIds": review_run.get("inputDocumentVersionIds") or [],
        },
    )
    append_tool_call(review_run, node_key, tool_name, compact_tool_output(result))
    return result


def compact_tool_output(result: dict[str, Any]) -> dict[str, Any]:
    summary_keys = [
        "toolCallId",
        "toolName",
        "status",
        "errorCode",
        "fieldCount",
        "tableCount",
        "sealCount",
        "fragmentCount",
        "welderCertificateCount",
        "verificationCount",
        "qualifiedItemCount",
        "matchedIssuerSealCount",
        "recognizedSealCount",
        "groundingStatus",
    ]
    summary = {key: result.get(key) for key in summary_keys if key in result}
    if result.get("verificationCount") is not None:
        summary["riskFlags"] = [
            flag
            for item in result.get("verifications") or []
            if isinstance(item, dict)
            for flag in item.get("riskFlags") or []
        ][:12]
    return summary


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


def compact_retrieval_trace(trace: dict[str, Any]) -> dict[str, Any]:
    selected_clauses = trace.get("selectedClauses") or []
    page_index_tree = trace.get("pageIndexTree") or {}
    return {
        "retrievalTraceId": trace.get("retrievalTraceId") or trace.get("id"),
        "queryType": trace.get("queryType"),
        "selectedRoute": trace.get("selectedRoute"),
        "routerVersion": trace.get("routerVersion"),
        "selectedClauseCount": len(selected_clauses),
        "selectedClauseIds": [
            item.get("clauseId")
            for item in selected_clauses
            if isinstance(item, dict) and item.get("clauseId")
        ],
        "pageIndexNodeCount": len(page_index_tree.get("selectedNodes") or []),
        "pageIndexLinkedClauseIds": page_index_tree.get("linkedClauseIds") or [],
    }


def compact_rule_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": result.get("id"),
        "ruleCode": result.get("ruleCode"),
        "ruleSetVersion": result.get("ruleSetVersion"),
        "result": result.get("result"),
        "severity": result.get("severity"),
        "linkedClauseIds": result.get("linkedClauseIds") or [],
        "message": result.get("message"),
    }


def validation_failure_count(details: dict[str, Any] | None) -> int:
    if not isinstance(details, dict):
        return 0
    return len(details.get("failures") or [])


def graph_view_for_review_run(review_run_id: str) -> dict[str, Any]:
    ensure_review_state()
    review_run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id) or {}
    nodes = graph_nodes_for_review_run(review_run_id)
    tool_calls = [
        repo.clone(item)
        for item in repo.state["review_tool_calls"]
        if item.get("reviewRunId") == review_run_id
    ]
    rule_results = [
        compact_rule_result(repo.clone(item))
        for item in repo.state["rule_check_results"]
        if item.get("reviewRunId") == review_run_id
    ]
    retrieval_traces = [
        compact_retrieval_trace(repo.clone(item))
        for item in repo.state["retrieval_traces"]
        if item.get("reviewRunId") == review_run_id
    ]
    tool_calls_by_node: dict[str, list[dict[str, Any]]] = {}
    for call in tool_calls:
        tool_calls_by_node.setdefault(str(call.get("nodeKey")), []).append(call)
    for node in nodes:
        node_key = str(node.get("nodeKey"))
        node_tool_calls = tool_calls_by_node.get(node_key, [])
        node["toolCalls"] = node_tool_calls
        artifact_counts = {
            "toolCalls": len(node_tool_calls),
            "ruleResults": len(rule_results) if node_key == "run_rule_engine" else 0,
            "retrievalTraces": len(retrieval_traces) if node_key == "retrieve_knowledge" else 0,
            "validationFailures": validation_failure_count(node.get("details")),
        }
        node["artifactCounts"] = artifact_counts
        if node_key == "run_rule_engine":
            node["ruleResults"] = rule_results
        if node_key == "retrieve_knowledge":
            node["retrievalTraces"] = retrieval_traces
        if node_key.endswith("_validation") or node_key in {"critic_review", "quality_gate"}:
            details = node.get("details") if isinstance(node.get("details"), dict) else {}
            node["validationSummary"] = {
                "passed": details.get("passed"),
                "checked": details.get("checked"),
                "failureCount": len(details.get("failures") or []),
                "warningCount": len(details.get("warnings") or []),
            }
    validation_failures = sum(validation_failure_count(node.get("details")) for node in nodes)
    return {
        "nodes": nodes,
        "edges": repo.clone(REVIEW_GRAPH_EDGES),
        "timeline": review_run_timeline(review_run_id),
        "artifactSummary": {
            "toolCalls": len(tool_calls),
            "ruleCheckResults": len(rule_results),
            "retrievalTraces": len(retrieval_traces),
            "pageIndexTraces": sum(1 for item in retrieval_traces if item.get("selectedRoute") == "pageindex_tree_search"),
            "findingDrafts": len(review_run.get("findingDrafts") or []),
            "validationFailures": validation_failures,
        },
        "artifacts": {
            "ruleCheckResults": rule_results,
            "retrievalTraces": retrieval_traces,
            "findingDrafts": [
                {
                    "id": item.get("id"),
                    "findingType": item.get("findingType"),
                    "severity": item.get("severity"),
                    "confidence": item.get("confidence"),
                    "requiresHumanConfirmation": item.get("requiresHumanConfirmation"),
                }
                for item in review_run.get("findingDrafts") or []
                if isinstance(item, dict)
            ],
        },
    }


def _compact_tool_call(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": call.get("id"),
        "toolName": call.get("toolName"),
        "allowed": call.get("allowed") is True,
        "outputHash": call.get("outputHash"),
        "outputSummary": call.get("outputSummary") or {},
        "createdAt": call.get("createdAt"),
    }


def _summarize_node_decision(
    review_run: dict[str, Any],
    node: dict[str, Any],
    *,
    tool_calls: list[dict[str, Any]],
    rule_results: list[dict[str, Any]],
    retrieval_traces: list[dict[str, Any]],
    finding_drafts: list[dict[str, Any]],
) -> dict[str, Any]:
    node_key = str(node.get("nodeKey") or "")
    details = node.get("details") if isinstance(node.get("details"), dict) else {}
    summary_map = {
        "load_context": "读取项目、节点、业务包和资料目录快照，形成审查上下文。",
        "load_ocr_result": "读取 OCR 字段、证据定位和文档版本，只引用结构化证据，不直接改业务状态。",
        "run_rule_engine": "执行确定性规则，得到缺项、字段、签章和状态约束结果。",
        "retrieve_knowledge": "按业务包、节点、资料类型和知识库版本检索可引用条款。",
        "build_prompt": "将上下文、规则结果、证据 ID 和条款 ID 组装为受控 Prompt 载荷。",
        "llm_generate_findings": "通过 QwenRuntime 生成结构化审查草稿，输出必须绑定证据、规则和知识依据。",
        "schema_validation": "校验 Finding Draft 的字段、枚举、置信度和人工确认要求。",
        "evidence_validation": "校验证据引用是否存在，bbox/page/documentVersion 是否可回放。",
        "reference_validation": "校验规则和知识条款引用是否来自本次规则结果和检索 Trace。",
        "critic_review": "执行确定性 Critic 复核，检查高风险动作是否仍需人工确认。",
        "quality_gate": "汇总 Schema、证据、依据和人工确认门禁，判断是否可进入人工审查。",
        "persist_drafts": "持久化审查草稿并生成输出哈希，原始运行不可被重跑覆盖。",
    }
    input_summary = {
        "reviewRunId": review_run.get("reviewRunId"),
        "inputHash": review_run.get("inputHash"),
        "documentVersionIds": review_run.get("inputDocumentVersionIds") or [],
        "ocrResultVersions": review_run.get("ocrResultVersions") or [],
    }
    output_summary = {
        "outputHash": node.get("outputHash") or details.get("outputHash"),
        "detailsHash": stable_hash_payload(details) if details else None,
        "details": details,
    }
    quality = {
        "passed": details.get("passed") if "passed" in details else node.get("status") == "succeeded",
        "failureCount": len(details.get("failures") or []),
        "warningCount": len(details.get("warnings") or []),
        "metrics": details.get("metrics") or {},
    }
    evidence_refs: list[dict[str, Any]] = []
    rule_refs: list[dict[str, Any]] = []
    kb_refs: list[dict[str, Any]] = []
    if node_key == "run_rule_engine":
        rule_refs = [
            {
                "ruleCode": item.get("ruleCode"),
                "ruleSetVersion": item.get("ruleSetVersion"),
                "linkedClauseIds": item.get("linkedClauseIds") or [],
            }
            for item in rule_results[:5]
        ]
    if node_key == "retrieve_knowledge":
        kb_refs = [
            {
                "retrievalTraceId": item.get("retrievalTraceId"),
                "selectedRoute": item.get("selectedRoute"),
                "selectedClauseIds": item.get("selectedClauseIds") or [],
            }
            for item in retrieval_traces[:5]
        ]
    if node_key in {"llm_generate_findings", "evidence_validation", "reference_validation", "quality_gate", "persist_drafts"}:
        for draft in finding_drafts[:5]:
            if not isinstance(draft, dict):
                continue
            evidence_refs.extend(repo.clone(draft.get("evidenceRefs") or [])[:3])
            rule_refs.extend(repo.clone(draft.get("ruleRefs") or [])[:3])
            kb_refs.extend(repo.clone(draft.get("kbRefs") or [])[:3])
    return {
        "traceId": f"{review_run.get('reviewRunId')}:{node_key}:{node.get('sequence')}",
        "nodeKey": node_key,
        "stepName": node.get("label"),
        "sequence": node.get("sequence"),
        "phase": node.get("taskQueue"),
        "status": node.get("status"),
        "attempt": node.get("attempt") or 0,
        "agentId": review_run.get("agentId"),
        "agentVersion": review_run.get("agentVersion"),
        "inputSummary": input_summary,
        "reasoningSummary": summary_map.get(node_key) or "执行编排节点并记录结构化产物。",
        "toolCalls": [_compact_tool_call(call) for call in tool_calls],
        "outputSummary": output_summary,
        "evidenceRefs": evidence_refs[:8],
        "ruleRefs": rule_refs[:8],
        "kbRefs": kb_refs[:8],
        "quality": quality,
        "startedAt": node.get("startedAt"),
        "finishedAt": node.get("finishedAt"),
        "redactionPolicy": "audit_summary_only_no_raw_chain_of_thought",
    }


def _validation_dimension(node: dict[str, Any]) -> dict[str, Any]:
    details = node.get("details") if isinstance(node.get("details"), dict) else {}
    passed = details.get("passed")
    if passed is None:
        passed = node.get("status") == "succeeded"
    failures = details.get("failures") or []
    warnings = details.get("warnings") or []
    return {
        "dimension": node.get("label") or node.get("nodeKey"),
        "nodeKey": node.get("nodeKey"),
        "status": "pass" if passed else "fail",
        "score": 1 if passed else 0,
        "failureCount": len(failures),
        "warningCount": len(warnings),
        "finding": failures[0].get("code") if failures and isinstance(failures[0], dict) else (warnings[0].get("code") if warnings and isinstance(warnings[0], dict) else "-"),
        "metrics": details.get("metrics") or {},
    }


def _human_corrections_for_review_run(review_run: dict[str, Any]) -> list[dict[str, Any]]:
    review_run_id = str(review_run.get("reviewRunId") or "")
    ai_run_id = str(review_run.get("aiRunId") or "")
    corrections: list[dict[str, Any]] = []
    for feedback in repo.state.get("ai_feedback", []):
        if feedback.get("reviewRunId") != review_run_id and feedback.get("aiRunId") != ai_run_id:
            continue
        original_output = feedback.get("originalAiOutput") or []
        corrected_output = feedback.get("correctedOutput")
        first_original = original_output[0] if isinstance(original_output, list) and original_output else {}
        first_corrected = corrected_output[0] if isinstance(corrected_output, list) and corrected_output else corrected_output
        corrections.append(
            {
                "id": feedback.get("id"),
                "targetType": "review_finding_draft",
                "targetId": first_original.get("id") if isinstance(first_original, dict) else None,
                "feedbackType": feedback.get("feedbackType"),
                "status": feedback.get("status"),
                "rootCause": feedback.get("rootCause"),
                "beforeSummary": first_original.get("description") if isinstance(first_original, dict) else None,
                "afterSummary": first_corrected.get("description") if isinstance(first_corrected, dict) else first_corrected,
                "comment": feedback.get("comment"),
                "accepted": feedback.get("accepted"),
                "shouldEnterEvaluationSet": feedback.get("shouldEnterEvaluationSet"),
                "createdAt": feedback.get("createdAt"),
            }
        )
    if review_run.get("humanDecision") and not corrections:
        decision = review_run["humanDecision"]
        corrections.append(
            {
                "id": f"HDEC-{review_run_id}",
                "targetType": "review_run",
                "targetId": review_run_id,
                "feedbackType": decision.get("decision"),
                "status": review_run.get("status"),
                "rootCause": None,
                "beforeSummary": "AI 审查草稿",
                "afterSummary": decision.get("correctedOutput"),
                "comment": decision.get("comment"),
                "accepted": decision.get("decision") in {"accept", "edit"},
                "shouldEnterEvaluationSet": decision.get("decision") in {"edit", "reject"},
                "createdAt": decision.get("decidedAt"),
            }
        )
    return corrections


def review_run_audit_trace(review_run_id: str) -> dict[str, Any]:
    ensure_review_state()
    review_run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id) or {}
    graph = graph_view_for_review_run(review_run_id)
    nodes = graph.get("nodes") or []
    tool_calls = [
        repo.clone(item)
        for item in repo.state.get("review_tool_calls", [])
        if item.get("reviewRunId") == review_run_id
    ]
    tool_calls_by_node: dict[str, list[dict[str, Any]]] = {}
    for call in tool_calls:
        tool_calls_by_node.setdefault(str(call.get("nodeKey")), []).append(call)
    rule_results = graph.get("artifacts", {}).get("ruleCheckResults") or []
    retrieval_traces = graph.get("artifacts", {}).get("retrievalTraces") or []
    finding_drafts = repo.clone(review_run.get("findingDrafts") or [])
    reasoning_trace = [
        _summarize_node_decision(
            review_run,
            node,
            tool_calls=tool_calls_by_node.get(str(node.get("nodeKey")), []),
            rule_results=rule_results,
            retrieval_traces=retrieval_traces,
            finding_drafts=finding_drafts,
        )
        for node in nodes
    ]
    validation_nodes = [
        node
        for node in nodes
        if node.get("nodeKey") in {"schema_validation", "evidence_validation", "reference_validation", "critic_review", "quality_gate"}
    ]
    dimensions = [_validation_dimension(node) for node in validation_nodes]
    failed_dimensions = [item for item in dimensions if item["status"] != "pass"]
    lineage = {
        "schemaVersion": review_run.get("schemaVersion") or "ReviewFindingDraftList@1.0.0",
        "businessPackId": review_run.get("businessPackId"),
        "businessPackVersion": review_run.get("businessPackVersion"),
        "businessPackSnapshotHash": review_run.get("businessPackSnapshotHash"),
        "agentId": review_run.get("agentId"),
        "agentVersion": review_run.get("agentVersion"),
        "promptVersion": review_run.get("promptVersion"),
        "modelGateway": review_run.get("modelGateway") or "qwen_runtime",
        "modelAlias": review_run.get("modelAlias"),
        "auditInputMode": review_run.get("auditInputMode") or (review_run.get("auditRuntime") or {}).get("mode"),
        "auditRuntime": repo.clone(review_run.get("auditRuntime") or {}),
        "ruleSetVersion": review_run.get("ruleSetVersion"),
        "kbVersion": review_run.get("kbVersion"),
        "workflowEngine": review_run.get("workflowEngine"),
        "workflowId": review_run.get("workflowId"),
        "temporalRunId": review_run.get("temporalRunId"),
        "graphEngine": review_run.get("graphEngine"),
        "graphRunner": review_run.get("graphRunner"),
        "inputDocumentVersionIds": repo.clone(review_run.get("inputDocumentVersionIds") or []),
        "ocrResultVersions": repo.clone(review_run.get("ocrResultVersions") or []),
        "inputHash": review_run.get("inputHash"),
        "outputHash": review_run.get("outputHash"),
        "capabilityBundleHash": stable_hash_payload(
            {
                "agentVersion": review_run.get("agentVersion"),
                "promptVersion": review_run.get("promptVersion"),
                "modelAlias": review_run.get("modelAlias"),
                "ruleSetVersion": review_run.get("ruleSetVersion"),
                "kbVersion": review_run.get("kbVersion"),
                "businessPackVersion": review_run.get("businessPackVersion"),
            }
        ),
        "immutabilityPolicy": "replay_creates_child_run_original_is_never_overwritten",
        "reasoningPolicy": "show_audit_summary_not_raw_chain_of_thought",
    }
    return {
        "reasoningTrace": reasoning_trace,
        "lineage": lineage,
        "qualityEvaluation": {
            "score": round((sum(float(item["score"]) for item in dimensions) / len(dimensions)) * 100, 1) if dimensions else 0,
            "status": "pass" if not failed_dimensions else "needs_human_review",
            "dimensions": dimensions,
            "gates": [
                {
                    "code": item.get("nodeKey"),
                    "status": item.get("status"),
                    "message": item.get("finding"),
                    "failureCount": item.get("failureCount"),
                    "warningCount": item.get("warningCount"),
                }
                for item in dimensions
            ],
            "humanReviewRequired": True,
        },
        "humanCorrections": _human_corrections_for_review_run(review_run),
        "redactionPolicy": "audit_summary_only_no_raw_chain_of_thought",
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
    feedback = record_human_feedback_for_review_run(review_run, decision, payload)
    if decision in {"accept", "edit"}:
        persist_confirmed_findings(review_run, payload)
    ai_run = repo.find_one("ai_runs", str(review_run.get("aiRunId")))
    if ai_run:
        ai_run["status"] = "已人工确认" if decision in {"accept", "edit"} else "已驳回"
    return {"status": review_run["status"], "reviewRun": review_run, "feedback": feedback}


def record_human_feedback_for_review_run(
    review_run: dict[str, Any],
    decision: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    feedback_type = {
        "accept": "accepted",
        "edit": "edited",
        "reject": "rejected_false_positive",
    }[decision]
    should_enter_evaluation_set = bool(payload.get("shouldEnterEvaluationSet", decision in {"edit", "reject"}))
    original_ai_output = repo.clone(review_run.get("findingDrafts") or [])
    corrected_output = payload.get("correctedOutput")
    if corrected_output is None and decision == "accept":
        corrected_output = original_ai_output
    feedback_id = payload.get("feedbackId") or f"AIFB-{review_run['reviewRunId']}-{decision}".upper()
    record = {
        "id": feedback_id,
        "aiRunId": review_run.get("aiRunId"),
        "reviewRunId": review_run.get("reviewRunId"),
        "projectId": review_run.get("projectId"),
        "nodeId": review_run.get("nodeId"),
        "agentId": review_run.get("agentId"),
        "agentVersion": review_run.get("agentVersion"),
        "promptVersion": review_run.get("promptVersion"),
        "modelAlias": review_run.get("modelAlias"),
        "ruleSetVersion": review_run.get("ruleSetVersion"),
        "kbVersion": review_run.get("kbVersion"),
        "businessPackId": review_run.get("businessPackId"),
        "businessPackVersion": review_run.get("businessPackVersion"),
        "inputDocumentVersionIds": repo.clone(review_run.get("inputDocumentVersionIds") or []),
        "ocrResultVersions": repo.clone(review_run.get("ocrResultVersions") or []),
        "feedbackType": feedback_type,
        "accepted": decision in {"accept", "edit"},
        "comment": payload.get("comment") or payload.get("reason"),
        "originalAiOutput": original_ai_output,
        "correctedOutput": corrected_output,
        "shouldEnterEvaluationSet": should_enter_evaluation_set,
        "status": payload.get("feedbackStatus") or "created",
        "rootCause": payload.get("rootCause") or ("human_review_error" if decision == "accept" else "prompt_error"),
        "source": "review_run_human_decision",
        "createdAt": server_time(),
        "immutableSourceRun": True,
    }
    existing = repo.find_one("ai_feedback", feedback_id)
    if existing:
        existing.update(record)
        return repo.clone(existing)
    repo.state["ai_feedback"].insert(0, record)
    return repo.clone(record)


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
            "reviewMode": "gap_precheck" if run_mode != "production" else parent.get("reviewMode", "formal"),
            "advisoryOnly": True if run_mode != "production" else bool(parent.get("advisoryOnly")),
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
