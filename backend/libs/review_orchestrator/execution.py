from __future__ import annotations

import hashlib
import json
import os
from typing import Any
from uuid import uuid4

from libs.business_pack import DEFAULT_BUSINESS_PACK_ID, build_ai_review_prompt, load_business_pack, matching_rule_for_node
from libs.contracts.responses import server_time
from libs.db.repository import repo
from libs.integrations.errors import IntegrationServiceError
from libs.integrations.litellm_client import LiteLLMClient, production_mode_enabled
from libs.knowledge_retrieval import retrieve_knowledge_clauses

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
    "run_rule_engine",
    "retrieve_clauses",
    "search_knowledge_base",
    "call_litellm_chat",
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
        rule_basis = retrieve_knowledge_clauses(
            repo.state,
            query=str(rule.get("description") or rule.get("name") or "审查规则依据"),
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
            "result": "passed" if context.get("fields") else "warning",
            "severity": rule.get("severity") or "medium",
            "message": "规则检查完成，待人工确认。" if context.get("fields") else "未发现可用 OCR 字段，需人工复核。",
            "linkedClauseIds": linked_clause_ids,
            "evidenceRefs": [{"source": "ocr_fields", "count": len(context.get("fields") or [])}],
            "suggestedAction": "human_confirm",
            "createdAt": server_time(),
        }
        repo.state["rule_check_results"].append(result)
        context["ruleResults"] = [result]
        append_tool_call(review_run, node_key, "run_rule_engine", {"ruleCode": result["ruleCode"], "result": result["result"]})
        return {"ruleResults": 1, "ruleCode": result["ruleCode"], "result": result["result"], "linkedClauseIds": linked_clause_ids}
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
        return {"promptVersion": review_run.get("promptVersion"), "promptPayload": "ids_hashes_versions_only"}
    if node_key == "llm_generate_findings":
        drafts, llm_details = generate_finding_drafts(review_run, context)
        context["findingDrafts"] = drafts
        for draft in drafts:
            append_tool_call(review_run, node_key, "create_review_finding_draft", {"findingDraftId": draft["id"]})
        return {"modelGateway": "litellm", "modelAlias": review_run.get("modelAlias"), "findingDrafts": len(drafts), **llm_details}
    if node_key == "schema_validation":
        result = validate_review_schema(context.get("findingDrafts") or [])
        context.setdefault("validationResults", {})[node_key] = result
        return result
    if node_key == "evidence_validation":
        result = validate_review_evidence_refs(context.get("findingDrafts") or [], context.get("evidenceLinks") or [])
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


def build_review_prompt_shape(review_run: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    project = context.get("project") or {}
    node = context.get("node") or {}
    fields = context.get("fields") or []
    rule_result = next(iter(context.get("ruleResults") or []), {})
    return {
        "system": "review_agent_sop",
        "promptVersion": review_run.get("promptVersion"),
        "schemaVersion": review_run.get("schemaVersion"),
        "payloadHash": stable_hash_payload(
            {
                "projectId": project.get("id") or review_run.get("projectId"),
                "nodeId": node.get("id") or review_run.get("nodeId"),
                "fieldCount": len(fields),
                "ruleCode": rule_result.get("ruleCode"),
                "kbVersion": review_run.get("kbVersion"),
            }
        ),
        "payloadPolicy": "ids_hashes_versions_only",
    }


def build_review_messages(review_run: dict[str, Any], context: dict[str, Any]) -> list[dict[str, str]]:
    pack = load_business_pack(str(review_run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID))
    node = context.get("node") or {}
    fields = context.get("fields") or []
    rule_result = next(iter(context.get("ruleResults") or []), {})
    prompt = build_ai_review_prompt(pack, node=node, fields=fields, rule=rule_result)
    user_payload = {
        "task": "Generate ReviewFindingDraftList JSON only.",
        "requirements": [
            "Every finding must require human confirmation.",
            "Do not approve, reject, issue correction, close correction, archive, or change business status.",
            "Use evidenceRefs, ruleRefs, and kbRefs from the supplied IDs only.",
        ],
        "projectId": review_run.get("projectId"),
        "nodeId": review_run.get("nodeId"),
        "fieldCount": len(fields),
        "ruleResults": context.get("ruleResults") or [],
        "retrievalTraceIds": [item.get("retrievalTraceId") for item in context.get("retrievalTraces") or []],
        "evidenceLinkIds": [item.get("id") for item in context.get("evidenceLinks") or []],
        "outputSchema": {
            "findings": [
                {
                    "findingType": "string",
                    "severity": "low|medium|high",
                    "title": "string",
                    "description": "string",
                    "confidence": "0..1",
                    "suggestedAction": "human_confirm|request_correction",
                }
            ]
        },
    }
    return [
        {"role": "system", "content": prompt["system"]},
        {"role": "user", "content": prompt["user"] + "\n\n" + json.dumps(user_payload, ensure_ascii=False)},
    ]


def generate_finding_drafts(review_run: dict[str, Any], context: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mode = review_llm_execution_mode()
    if mode in {"deterministic", "disabled", "mock"}:
        return [build_finding_draft(review_run, context)], {"llmExecution": mode, "llmCalled": False}
    messages = build_review_messages(review_run, context)
    try:
        response = LiteLLMClient().chat_sync(
            messages,
            model=str(review_run.get("modelAlias") or "review-chat"),
            temperature=0.1,
            response_format={"type": "json_object"},
        )
    except IntegrationServiceError:
        raise
    except Exception as exc:
        raise IntegrationServiceError("LiteLLM", "review.chat", reason=exc.__class__.__name__) from exc
    append_tool_call(
        review_run,
        "llm_generate_findings",
        "call_litellm_chat",
        {
            "modelAlias": review_run.get("modelAlias"),
            "responseHash": stable_hash_payload(response),
        },
    )
    content = LiteLLMClient.first_message_text(response)
    drafts = normalize_llm_findings(review_run, context, content)
    return drafts, {
        "llmExecution": "litellm",
        "llmCalled": True,
        "responseHash": stable_hash_payload(response),
        "usage": response.get("usage") or {},
    }


def normalize_llm_findings(review_run: dict[str, Any], context: dict[str, Any], content: str) -> list[dict[str, Any]]:
    base = build_finding_draft(review_run, context)
    if not content.strip():
        return [base]
    try:
        parsed = json.loads(content)
    except ValueError:
        base["description"] = content[:800]
        base["llmResponseFormat"] = "free_text_wrapped"
        return [base]
    raw_findings = parsed.get("findings") if isinstance(parsed, dict) else None
    if not isinstance(raw_findings, list) or not raw_findings:
        return [base]
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
        draft["requiresHumanConfirmation"] = True
        draft["llmGenerated"] = True
        drafts.append(draft)
    return drafts or [base]


def bounded_confidence(value: Any, *, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
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


def validate_review_evidence_refs(drafts: list[dict[str, Any]], evidence_links: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    evidence_ids = {str(item.get("id")) for item in evidence_links if isinstance(item, dict) and item.get("id")}
    checked_refs = 0
    for draft_index, draft in enumerate(drafts):
        refs = draft.get("evidenceRefs") if isinstance(draft.get("evidenceRefs"), list) else []
        if not refs:
            warnings.append({"code": "NO_EVIDENCE_REFS", "index": draft_index, "message": "Finding has no direct evidence references."})
            continue
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
