from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any
from uuid import uuid4

from libs.audit_runtime import (
    audit_runtime_config,
    audit_runtime_for_run,
    audit_runtime_public_config,
)
from libs.business_pack import (
    DEFAULT_BUSINESS_PACK_ID,
    build_ai_review_prompt,
    load_business_pack,
    matching_rule_for_node,
)
from libs.business_pack.clause_store import (
    freeze_review_run_clause_snapshot,
    review_run_clause_snapshot,
)
from libs.contracts.responses import server_time
from libs.db.repository import STATE_COLLECTIONS, flush_state_records, load_review_run_state, repo
from libs.integrations.errors import IntegrationServiceError
from libs.integrations.litellm_client import LiteLLMClient, production_mode_enabled
from libs.knowledge_retrieval import retrieve_knowledge_clauses
from libs.model_usage import estimate_messages_tokens, model_cost_cny, normalize_model_usage
from libs.qwen_runtime import (
    QwenRuntimeClient,
    build_qwen_runtime_client,
    qwen_runtime_public_config,
)
from libs.raw_vault import raw_context_from_record
from libs.reasoning_budget import (
    review_max_output_tokens,
    review_reasoning_effort,
    truncation_caused_by_reasoning,
)
from libs.review_grounding import (
    apply_grounding_guardrails,
    build_grounded_review_input,
    grounding_prompt_block,
)
from libs.review_orchestrator.clause_digest import retrieved_clause_digest
from libs.review_orchestrator.evidence_budget import (
    trim_evidence_to_budget,
    truncation_requirements,
)
from libs.review_orchestrator.graph_topology import REVIEW_GRAPH_EDGES, REVIEW_GRAPH_STEPS
from libs.review_orchestrator.llm_tool_schemas import build_llm_tools_for_runtime
from libs.review_orchestrator.node_fact_overrides import (
    apply_node_fact_corrections,
    pure_llm_grounding_input,
)
from libs.review_orchestrator.r12_agent import (
    apply_r12_human_input,
    build_r12_business_facts,
    ensure_r12_human_input_task,
    extract_r12_license_candidates,
    is_r12_formal_review,
    validate_r12_human_input,
)
from libs.review_orchestrator.r13_facts import build_r13_business_facts
from libs.review_orchestrator.r14_facts import build_r14_business_facts
from libs.review_orchestrator.r15_facts import build_r15_business_facts
from libs.review_orchestrator.r16_facts import build_r16_business_facts
from libs.review_orchestrator.r17_facts import build_r17_business_facts
from libs.review_orchestrator.r18_facts import build_r18_business_facts
from libs.review_orchestrator.r19_agent import (
    R19_EXECUTION_MODE,
    R19_REVIEW_QUESTIONS,
    R19_TASK_TYPE,
    apply_r19_human_input,
    build_r19_agent_context,
    ensure_r19_human_input_task,
    is_r19_formal_review,
    validate_r19_human_input,
    validate_r19_semantic_submission,
)
from libs.review_orchestrator.r19_agent import (
    context_for_model as r19_context_for_model,
)
from libs.review_orchestrator.r20_r23_facts import (
    build_r20_business_facts,
    build_r21_business_facts,
    build_r22_business_facts,
    build_r23_business_facts,
)
from libs.review_orchestrator.r24_r34_facts import BUILDERS as R24_R34_FACT_BUILDERS
from libs.review_orchestrator.retry_policy import has_review_retry_consumer
from libs.review_orchestrator.rule_result_digest import (
    compact_rule_results,
    compact_tool_output,
)
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
from libs.review_orchestrator.tool_scope import scoped_runtime_tool_catalog
from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan
from libs.security.tenant import current_tenant_id, tenant_id_for_record


def qwen_runtime_client() -> QwenRuntimeClient:
    return build_qwen_runtime_client(LiteLLMClient)





# 确定性判定 → AI 建议结论展示词。所有结论均为建议，最终由监检人员确认。
SUGGESTION_RESULT_LABELS = {
    "passed": "建议满足要求",
    "failed": "建议不符合",
    "evidence_insufficient": "证据不足",
    "not_applicable": "建议不适用",
    "human_review_required": "需专业判断",
    "execution_error": "执行故障待重试",
}

REVIEW_STATE_COLLECTIONS = (
    "review_runs",
    "review_step_runs",
    "review_graph_nodes",
    "review_tool_calls",
    "review_events",
    "retrieval_traces",
    "rule_check_results",
    "ai_feedback",
    "review_run_clause_snapshots",
    "model_call_attempts",
    "workflow_outbox",
    "workflow_inbox",
)

REVIEW_RUN_TERMINAL_STATUSES = {
    "accepted_by_human",
    "edited_by_human",
    "rejected_by_human",
    "cancelled",
    "failed",
    "failed_to_start",
}

NON_RETRYABLE_REVIEW_REASONS = {
    "REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED",
    "REVIEW_COST_BUDGET_EXCEEDED",
    "REVIEW_MAX_ATTEMPTS_EXCEEDED",
    "LLM_OUTPUT_TRUNCATED",
    # 推理占满输出额度：重试只会再被吃光一次，要改的是预算不是次数
    "LLM_OUTPUT_BUDGET_EXHAUSTED_BY_REASONING",
    "LLM_OUTPUT_EMPTY",
    "LLM_OUTPUT_INVALID_JSON",
    "LLM_OUTPUT_INVALID_ENVELOPE",
    "LLM_OUTPUT_EMPTY_FINDINGS",
    "LLM_OUTPUT_INVALID_FINDING",
}


def review_workflow_id(tenant_id: str, review_run_id: str) -> str:
    """Namespace Temporal workflows without exposing the tenant identifier."""

    tenant_digest = hashlib.sha256(str(tenant_id).encode("utf-8")).hexdigest()[:12]
    return f"review-run-{tenant_digest}-{review_run_id}"

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
    "inspect_r12_license_candidates",
    "request_official_registry_verification",
    "inspect_r13_review_facts",
    "inspect_r14_review_facts",
    "inspect_r15_review_facts",
    "inspect_r16_review_facts",
    "inspect_r17_review_facts",
    "inspect_r18_review_facts",
    "inspect_r19_review_context",
    "request_r19_human_input",
    "submit_r19_semantic_review",
    "get_project_context",
    "get_node_requirements",
    "get_document_ocr_result",
    "recognize_document_seals",
    "recognize_signatures_and_seals",
    "search_project_documents",
    "extract_structured_fields",
    "extract_document_fields",
    "extract_table_records",
    "locate_evidence_fragment",
    "extract_welder_certificate",
    "verify_license_or_certificate",
    "verify_welder_certificate_authenticity",
    "check_all_equal",
    "check_date_covers",
    "check_design_license_scope",
    "decode_welder_qualification",
    "check_welder_work_coverage",
    "check_pressure_gauge_requirements",
    "check_pressure_test_parameters",
    "check_pressure_test_report_consistency",
    "validate_evidence_grounding",
    "run_rule_engine",
    "retrieve_clauses",
    "search_knowledge_base",
    "call_qwen_runtime_chat",
    "create_review_finding_draft",
    "create_ai_diagnostic",
} | {item["name"] for item in runtime_tool_catalog()}


def ensure_review_state() -> None:
    for collection in REVIEW_STATE_COLLECTIONS:
        repo.state.setdefault(collection, [])


def stable_hash_payload(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def review_run_revision(review_run: dict[str, Any]) -> int:
    return int(review_run.get("revision") or 1)


def review_run_etag(review_run: dict[str, Any]) -> str:
    review_run_id = str(review_run.get("reviewRunId") or review_run.get("id") or "unknown")
    return f'W/"review-run-{review_run_id}-r{review_run_revision(review_run)}"'


def bump_review_run_revision(review_run: dict[str, Any]) -> None:
    review_run["revision"] = review_run_revision(review_run) + 1
    review_run["updatedAt"] = server_time()


def review_failure_retryable(exc: Exception) -> bool:
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return False
    if isinstance(exc, IntegrationServiceError):
        if exc.reason in NON_RETRYABLE_REVIEW_REASONS:
            return False
        if exc.status_code in {408, 425, 429} or (exc.status_code is not None and exc.status_code >= 500):
            return True
        return bool(exc.reason and any(token in exc.reason for token in ("TIMEOUT", "UNAVAILABLE", "CONNECTION")))
    return isinstance(exc, (ConnectionError, TimeoutError, OSError, RuntimeError))


def mark_review_run_retry_exhausted(review_run_id: str) -> dict[str, Any] | None:
    review_run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one(
        "review_runs", review_run_id
    )
    if not review_run:
        return None
    review_run["status"] = "failed"
    review_run["retryableFailure"] = False
    review_run["errorCode"] = "REVIEW_RETRY_EXHAUSTED"
    review_run["finishedAt"] = server_time()
    bump_review_run_revision(review_run)
    append_review_event(
        review_run_id,
        event_type="review_run.retry_exhausted",
        title="ReviewRun 重试耗尽",
        status="failed",
        details={"errorCode": "REVIEW_RETRY_EXHAUSTED"},
    )
    ai_run = repo.find_one("ai_runs", str(review_run.get("aiRunId") or ""))
    if ai_run:
        ai_run["status"] = "失败"
        ai_run["errorCode"] = "REVIEW_RETRY_EXHAUSTED"
    if not review_run.get("advisoryOnly"):
        previous_status = str(review_run.get("previousNodeStatus") or "待人工确认")
        repo.set_node_status(
            str(review_run.get("projectId")),
            int(review_run.get("nodeId") or 0),
            previous_status,
        )
    return review_run


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
    tenant_id = tenant_id_for_record(ai_run) or current_tenant_id()
    workflow_id = review_workflow_id(tenant_id, review_run_id)
    now = server_time()
    audit_runtime = audit_runtime_public_config(mode=str(ai_run.get("auditInputMode") or "") or None)
    clause_package_snapshot = repo.clone(ai_run.get("clausePackageSnapshot"))
    record = {
        "id": review_run_id,
        "reviewRunId": review_run_id,
        "tenantId": tenant_id,
        "aiRunId": ai_run["id"],
        "projectId": ai_run.get("projectId"),
        "nodeId": ai_run.get("nodeId"),
        "businessPackId": ai_run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
        "businessPackVersion": ai_run.get("businessPackVersion"),
        "businessPackSnapshotHash": ai_run.get("businessPackSnapshotHash"),
        "atomicCheckToolBindingSetId": ai_run.get("atomicCheckToolBindingSetId"),
        "atomicCheckToolBindingSetVersion": ai_run.get("atomicCheckToolBindingSetVersion"),
        "atomicCheckToolBindingSetLifecycle": ai_run.get("atomicCheckToolBindingSetLifecycle"),
        "atomicCheckToolBindingSetHash": ai_run.get("atomicCheckToolBindingSetHash"),
        "atomicCheckToolBindingSetSnapshot": repo.clone(ai_run.get("atomicCheckToolBindingSetSnapshot") or {}),
        "atomicCheckToolBindingsSnapshot": repo.clone(ai_run.get("atomicCheckToolBindingsSnapshot") or []),
        "clausePackageId": ai_run.get("clausePackageId") or (clause_package_snapshot or {}).get("packageStorageId"),
        "clausePackageSnapshotHash": ai_run.get("clausePackageSnapshotHash") or (clause_package_snapshot or {}).get("snapshotHash"),
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
                "clausePackageSnapshotHash": ai_run.get("clausePackageSnapshotHash")
                or (clause_package_snapshot or {}).get("snapshotHash"),
                "promptVersion": ai_run.get("promptVersion"),
                "ruleSetVersion": ai_run.get("ruleVersion"),
                "atomicCheckToolBindingSetHash": ai_run.get("atomicCheckToolBindingSetHash"),
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
    frozen_clause_snapshot = freeze_review_run_clause_snapshot(
        repo.state,
        review_run_id=review_run_id,
        project_id=str(record.get("projectId") or ""),
        node_id=int(record.get("nodeId") or 0),
        snapshot=clause_package_snapshot,
        created_at=now,
    )
    if frozen_clause_snapshot:
        record["clausePackageId"] = frozen_clause_snapshot.get("packageId")
        record["clausePackageSnapshotHash"] = frozen_clause_snapshot.get("packageSnapshotHash")
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


def plan_r12_human_verification(
    review_run: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """Let the LLM control the R12 interaction request, with a deterministic safety guard."""

    ensure_review_state()
    mode = review_llm_execution_mode()
    trace: dict[str, Any] = {
        "controlMode": "deterministic_workflow_guard",
        "llmExecution": mode,
        "llmCalled": False,
        "requestedHumanInput": False,
        "toolCalls": [],
    }
    if mode in {"deterministic", "disabled", "mock"}:
        return "workflow_guard", trace
    tools = [
        {
            "type": "function",
            "function": {
                "name": "inspect_r12_license_candidates",
                "description": "读取 R12 已从上传资料中识别出的制造许可证候选，不进行官网真实性判断。",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "request_official_registry_verification",
                "description": "当 R12 存在制造许可证候选时，暂停工作流并请求监检人员到官方平台逐证核验。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "candidateIds": {"type": "array", "items": {"type": "string"}},
                        "reason": {"type": "string"},
                    },
                    "required": ["candidateIds", "reason"],
                    "additionalProperties": False,
                },
            },
        },
    ]
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "你是 R12 压力管道元件制造许可复核 Agent。官网查询必须由监检人员完成；"
                "你必须先调用 inspect_r12_license_candidates，再调用 request_official_registry_verification。"
                "不得依据 OCR 自行宣称已完成官网核验。"
            ),
        },
        {
            "role": "user",
            "content": f"当前识别到 {len(candidates)} 个制造许可证候选，请推进 R12 复核。",
        },
    ]
    requested = False
    reasoning_chunks: list[str] = []
    model_attempt = {
        "id": f"MCALL-R12-{uuid4().hex[:10].upper()}",
        "reviewRunId": review_run.get("reviewRunId"),
        "aiRunId": review_run.get("aiRunId"),
        "projectId": review_run.get("projectId"),
        "nodeId": 12,
        "stage": "r12_agent_human_input_planning",
        "callKind": "agent_tool_call",
        "provider": review_run.get("modelGateway") or "qwen_runtime",
        "modelAlias": review_run.get("modelAlias"),
        "status": "running",
        "promptHash": stable_hash_payload(messages),
        "createdAt": server_time(),
        "startedAt": server_time(),
        "updatedAt": server_time(),
    }
    repo.state.setdefault("model_call_attempts", []).insert(0, model_attempt)
    try:
        client = qwen_runtime_client()
        last_response: dict[str, Any] = {}
        for _ in range(3):
            response = client.chat_sync(
                messages,
                model=str(review_run.get("modelAlias") or "review-chat"),
                tools=tools,
                tool_choice="auto",
                temperature=0.0,
                max_tokens=600,
                timeout=max(30.0, float(os.getenv("AICHECK_QWEN_REVIEW_TIMEOUT_SECONDS", "180"))),
                _raw_capture_context=raw_context_from_record(
                    review_run,
                    model_call_attempt_id=str(model_attempt["id"]),
                    stage=str(model_attempt["stage"]),
                    turn=len(trace["toolCalls"]) + 1,
                ),
            )
            last_response = response
            choices = response.get("choices") if isinstance(response.get("choices"), list) else []
            message = (choices[0].get("message") or {}) if choices and isinstance(choices[0], dict) else {}
            reasoning = message.get("reasoning_content") or message.get("reasoning")
            if reasoning:
                reasoning_chunks.append(str(reasoning))
            tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
            trace["llmCalled"] = True
            if not tool_calls:
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                function = call.get("function") if isinstance(call, dict) else {}
                tool_name = str((function or {}).get("name") or "")
                raw_arguments = (function or {}).get("arguments") or "{}"
                try:
                    arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
                except (TypeError, ValueError, json.JSONDecodeError):
                    arguments = {}
                if tool_name == "inspect_r12_license_candidates":
                    output = {"candidateCount": len(candidates), "candidates": candidates}
                elif tool_name == "request_official_registry_verification":
                    requested = True
                    output = {
                        "status": "waiting_human_input_required",
                        "candidateIds": [item.get("candidateId") for item in candidates],
                    }
                else:
                    output = {"status": "rejected", "errorCode": "R12_AGENT_TOOL_NOT_ALLOWED"}
                trace["toolCalls"].append(
                    {"toolName": tool_name, "argumentsHash": stable_hash_payload(arguments), "output": output}
                )
                append_tool_call(review_run, "r12_agent_precheck", tool_name, compact_tool_output(output))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(call.get("id") or f"r12-{len(trace['toolCalls'])}"),
                        "content": json.dumps(output, ensure_ascii=False, default=str),
                    }
                )
            if requested:
                break
        trace.update(
            {
                "controlMode": "llm_tool_call_guarded" if requested else "llm_tool_call_with_workflow_guard",
                "requestedHumanInput": requested,
                "reasoningContent": "\n".join(reasoning_chunks),
            }
        )
        model_attempt.update(
            {
                "status": "succeeded",
                "responseHash": stable_hash_payload(last_response),
                "reasoningContent": "\n".join(reasoning_chunks),
                "toolCallCount": len(trace["toolCalls"]),
                "finishedAt": server_time(),
                "updatedAt": server_time(),
            }
        )
        return ("llm_agent" if requested else "workflow_guard"), trace
    except Exception as exc:
        trace.update(
            {
                "controlMode": "llm_failed_workflow_guard",
                "errorType": type(exc).__name__,
                "reasoningContent": "\n".join(reasoning_chunks),
            }
        )
        model_attempt.update(
            {
                "status": "failed",
                "failureReason": type(exc).__name__,
                "reasoningContent": "\n".join(reasoning_chunks),
                "finishedAt": server_time(),
                "updatedAt": server_time(),
            }
        )
        return "workflow_guard", trace


def plan_r13_tool_review(
    review_run: dict[str, Any],
    facts: dict[str, Any],
) -> dict[str, Any]:
    r13 = facts.get("r13") if isinstance(facts.get("r13"), dict) else {}
    return _plan_guarded_material_tool_review(
        review_run,
        node_id=13,
        inspect_tool_name="inspect_r13_review_facts",
        inspect_output={
            "designItemCount": len(r13.get("designItems") or []),
            "supervisionCertificateCount": len(r13.get("supervisionCertificates") or []),
            "typeTestReportCount": len(r13.get("typeTestReports") or []),
            "designItems": list(r13.get("designItems") or [])[:50],
        },
        required_tool_arguments={
            "classify_r13_component_requirements": {"designItems": r13.get("designItems") or []},
            "evaluate_r13_supervision_certificate_completeness": {
                "designItems": r13.get("designItems") or [],
                "supervisionCertificates": r13.get("supervisionCertificates") or [],
            },
            "evaluate_r13_type_test_coverage": {
                "designItems": r13.get("designItems") or [],
                "typeTestReports": r13.get("typeTestReports") or [],
            },
        },
        system_prompt=(
            "你是R13制造监检证书和型式试验覆盖复核Agent。先调用inspect_r13_review_facts读取事实，"
            "再依次调用分类、制造监检证书齐全性和型式试验覆盖Tool。只能使用Tool返回的结果，"
            "不得自行改写产品分类、覆盖范围或证书结论。事实不足时保留证据不足。"
        ),
        user_prompt="请基于已上传设计材料表、制造监督检验证书和型式试验报告推进R13复核。",
    )


def plan_r14_tool_review(
    review_run: dict[str, Any],
    facts: dict[str, Any],
) -> dict[str, Any]:
    r14 = facts.get("r14") if isinstance(facts.get("r14"), dict) else {}
    product_rules = {
        "GB/T 12771-2019": {
            "requiredItems": ["nondestructive_testing"],
            "basis": "GB/T 12771-2019 6.9",
        }
    }
    common = {"designItems": r14.get("designItems") or []}
    return _plan_guarded_material_tool_review(
        review_run,
        node_id=14,
        inspect_tool_name="inspect_r14_review_facts",
        inspect_output={
            "designItemCount": len(r14.get("designItems") or []),
            "pipelineCharacteristicCount": len(r14.get("pipelineCharacteristics") or []),
            "factoryInspectionReportCount": len(r14.get("factoryInspectionReports") or []),
            "specialInspectionReportCount": len(r14.get("specialInspectionReports") or []),
            "designItems": list(r14.get("designItems") or [])[:50],
        },
        required_tool_arguments={
            "classify_r14_component_applicability": common,
            "evaluate_r14_component_design_match": {
                **common,
                "factoryInspectionReports": r14.get("factoryInspectionReports") or [],
            },
            "resolve_r14_required_inspection_items": {**common, "productInspectionRules": product_rules},
            "evaluate_r14_special_report_coverage": {
                **common,
                "specialInspectionReports": r14.get("specialInspectionReports") or [],
                "productInspectionRules": product_rules,
            },
            "evaluate_r14_pressure_compatibility": {
                **common,
                "pipelineCharacteristics": r14.get("pipelineCharacteristics") or [],
                "factoryInspectionReports": r14.get("factoryInspectionReports") or [],
                "specialInspectionReports": r14.get("specialInspectionReports") or [],
            },
        },
        system_prompt=(
            "你是R14管道组成件出厂检验复核Agent。先读取R14结构化事实，再调用适用性分类、"
            "等级材质一致性、必检项目解析、专项报告覆盖和压力等级对应Tool。光谱、硬度、金相、"
            "无损检测和耐压试验不得默认全部必需；只能按设计要求或冻结产品标准规则判断。"
            "不得绕过R12/R13适用性路由，不得覆盖确定性Tool结果。"
        ),
        user_prompt="请基于设计材料表、管道特性表、出厂检验报告和专项报告推进R14复核。",
    )


def plan_r15_tool_review(
    review_run: dict[str, Any],
    facts: dict[str, Any],
) -> dict[str, Any]:
    r15 = facts.get("r15") if isinstance(facts.get("r15"), dict) else {}
    common = {"designItems": r15.get("designItems") or []}
    return _plan_guarded_material_tool_review(
        review_run,
        node_id=15,
        inspect_tool_name="inspect_r15_review_facts",
        inspect_output={
            "designItemCount": len(r15.get("designItems") or []),
            "manufacturingLicenseCandidateCount": len(r15.get("manufacturingLicenseCandidates") or []),
            "manualRegistryVerificationCount": len(r15.get("manualRegistryVerifications") or []),
            "supervisionCertificateCount": len(r15.get("supervisionCertificates") or []),
            "typeTestReportCount": len(r15.get("typeTestReports") or []),
            "arrivalInspectionRecordCount": len(r15.get("arrivalInspectionRecords") or []),
            "completeMachineInspectionRecordCount": len(r15.get("completeMachineInspectionRecords") or []),
            "designItems": list(r15.get("designItems") or [])[:50],
        },
        required_tool_arguments={
            "classify_r15_foreign_manufacturing_applicability": common,
            "classify_r15_regulatory_requirements": common,
            "evaluate_r15_manufacturing_license_coverage": {
                **common,
                "licenseCandidates": r15.get("manufacturingLicenseCandidates") or [],
                "registryVerifications": r15.get("manualRegistryVerifications") or [],
                "requireRegistryVerification": True,
            },
            "evaluate_r15_type_test_coverage": {
                **common,
                "typeTestReports": r15.get("typeTestReports") or [],
            },
            "evaluate_r15_manufacturing_inspection_route": {
                **common,
                "supervisionCertificates": r15.get("supervisionCertificates") or [],
                "arrivalInspectionRecords": r15.get("arrivalInspectionRecords") or [],
                "completeMachineInspectionRecords": r15.get("completeMachineInspectionRecords") or [],
            },
        },
        system_prompt=(
            "你是R15境外制造压力管道元件和安全附件复核Agent。先读取结构化事实，再严格依次调用境外制造适用性、"
            "法定要求分类、制造许可覆盖、型式试验覆盖和制造监检路径Tool。境外制造与境外材料牌号必须区分；"
            "不能在境外完成制造监检时，必须按TSG 31-2025第2.2.1.5条检查到岸检验或随整机检验。"
            "只能解释确定性Tool结果，不得自行补造产品分类、证书范围或合格结论。"
        ),
        user_prompt=(
            "请依据TSG 31-2025第1.10、2.2.1.5条及TSG D7006-2020附件D D2.4.1，"
            "对境外制造元件和安全附件推进R15复核。"
        ),
    )


def plan_r16_tool_review(
    review_run: dict[str, Any],
    facts: dict[str, Any],
) -> dict[str, Any]:
    r16 = facts.get("r16") if isinstance(facts.get("r16"), dict) else {}
    common = {
        "designItems": r16.get("designItems") or [],
        "qualityCertificates": r16.get("qualityCertificates") or [],
    }
    return _plan_guarded_material_tool_review(
        review_run,
        node_id=16,
        inspect_tool_name="inspect_r16_review_facts",
        inspect_output={
            "designItemCount": len(r16.get("designItems") or []),
            "qualityCertificateCount": len(r16.get("qualityCertificates") or []),
            "designItems": list(r16.get("designItems") or [])[:50],
        },
        required_tool_arguments={
            "resolve_r16_product_standard_profile": common,
            "evaluate_r16_quality_certificate_batch_coverage": common,
            "evaluate_r16_quality_certificate_form_and_seals": common,
            "evaluate_r16_quality_certificate_design_match": common,
            "evaluate_r16_quality_certificate_content": common,
            "evaluate_r16_quality_certificate_results": common,
            "evaluate_r16_batch_traceability": common,
        },
        system_prompt=(
            "你是R16产品质量证明文件复核Agent。必须先读取结构化事实，再依次调用产品标准路由、批次覆盖、"
            "原件/复印件及印章、设计一致性、必需内容、数值结果和追溯链Tool。只能使用Tool结论；"
            "产品标准或数值限值未冻结时保留证据不足，不得自行查表、估算或补造合格结论。"
        ),
        user_prompt="请依据TSG D7006-2020附件D D2.4.1(5)和设计规定的产品标准推进R16复核。",
    )


def plan_r17_tool_review(
    review_run: dict[str, Any],
    facts: dict[str, Any],
) -> dict[str, Any]:
    r17 = facts.get("r17") if isinstance(facts.get("r17"), dict) else {}
    common = {
        "designItems": r17.get("designItems") or [],
        "acceptanceRecords": r17.get("acceptanceRecords") or [],
        "witnessRecords": r17.get("witnessRecords") or [],
        "samplingRetestReports": r17.get("samplingRetestReports") or [],
        "samplingRules": r17.get("samplingRules") or [],
    }
    return _plan_guarded_material_tool_review(
        review_run,
        node_id=17,
        inspect_tool_name="inspect_r17_review_facts",
        inspect_output={
            "designItemCount": len(r17.get("designItems") or []),
            "acceptanceRecordCount": len(r17.get("acceptanceRecords") or []),
            "witnessRecordCount": len(r17.get("witnessRecords") or []),
            "samplingRetestReportCount": len(r17.get("samplingRetestReports") or []),
        },
        required_tool_arguments={
            "evaluate_r17_arrival_acceptance_batch_coverage": common,
            "evaluate_r17_acceptance_procedure": common,
            "resolve_r17_sampling_retest_requirement": common,
            "evaluate_r17_sampling_witness_chain": common,
            "evaluate_r17_nonconformance_control": common,
        },
        system_prompt=(
            "你是R17到货验收与抽样复验见证复核Agent。必须先核验逐批验收记录和质量体系验收程序，"
            "再解析抽样复验适用性；仅对明确需要抽样复验的批次核验见证—样品—报告链，"
            "最后核验不合格隔离处置。可选复验报告为空不得直接判定缺失，Tool结果不得被模型覆盖。"
        ),
        user_prompt="请依据TSG D7006-2020附件D D2.4.1(6)推进R17复核。",
    )


def plan_r18_tool_review(
    review_run: dict[str, Any],
    facts: dict[str, Any],
) -> dict[str, Any]:
    r18 = facts.get("r18") if isinstance(facts.get("r18"), dict) else {}
    common = {
        "designItems": r18.get("designItems") or [],
        "retestReports": r18.get("retestReports") or [],
        "materialNdtReports": r18.get("materialNdtReports") or [],
    }
    return _plan_guarded_material_tool_review(
        review_run,
        node_id=18,
        inspect_tool_name="inspect_r18_review_facts",
        inspect_output={
            "designItemCount": len(r18.get("designItems") or []),
            "retestReportCount": len(r18.get("retestReports") or []),
            "materialNdtReportCount": len(r18.get("materialNdtReports") or []),
        },
        required_tool_arguments={
            "classify_r18_material_test_applicability": common,
            "resolve_r18_material_test_requirement_profile": common,
            "evaluate_r18_material_retest_report_completeness": common,
            "evaluate_r18_material_ndt_report_completeness": common,
            "evaluate_r18_material_report_approval_procedure": common,
            "evaluate_r18_material_test_results_and_traceability": common,
        },
        system_prompt=(
            "你是R18材料复验和材料本体无损检测报告复核Agent。R18不是无条件必审：必须先调用适用性Tool，"
            "再绑定明确的试验项目、方法和验收限值；仅审查适用批次的报告完整性、批准程序、结果和追溯链。"
            "焊缝NDT报告不得冒充材料本体NDT报告，限值缺失时必须保留证据不足。"
        ),
        user_prompt="请依据TSG D7006-2020附件D D2.4.1(7)推进R18复核。",
    )


def plan_r19_semantic_review(
    review_run: dict[str, Any],
    agent_context: dict[str, Any],
) -> dict[str, Any]:
    """Run the evidence-bound semantic Agent used for R19's open-format review."""

    ensure_review_state()
    mode = review_llm_execution_mode()
    trace: dict[str, Any] = {
        "controlMode": R19_EXECUTION_MODE,
        "llmExecution": mode,
        "llmCalled": False,
        "submitted": False,
        "requestedHumanInput": False,
        "toolCalls": [],
        "reasoningContent": "",
        "executionMode": R19_EXECUTION_MODE,
    }
    if mode in {"deterministic", "disabled", "mock"}:
        trace.update(
            {
                "controlMode": "r19_llm_unavailable_human_guard",
                "requestedHumanInput": True,
                "humanInputRequest": {
                    "questionIds": [item["questionId"] for item in R19_REVIEW_QUESTIONS],
                    "reason": "R19 requires semantic review but the LLM execution mode is unavailable.",
                    "title": "人工确认 R19 境外牌号材料审查事实",
                },
            }
        )
        return trace

    document_version_ids = {str(item) for item in agent_context.get("documentVersionIds") or [] if item}
    evidence_index = agent_context.setdefault("evidenceIndex", {})
    known_evidence_ids = {str(item) for item in evidence_index}
    tool_catalog = {str(item.get("name")): item for item in runtime_tool_catalog()}

    def schema_for_runtime(name: str) -> dict[str, Any]:
        if name == "locate_evidence_fragment":
            return {
                "type": "object",
                "properties": {
                    "documentVersionIds": {"type": "array", "items": {"type": "string"}},
                    "queryTerms": {"type": "array", "items": {"type": "string"}},
                    "minConfidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["documentVersionIds", "queryTerms"],
                "additionalProperties": False,
            }
        if name == "extract_document_fields":
            return {
                "type": "object",
                "properties": {
                    "documentVersionIds": {"type": "array", "items": {"type": "string"}},
                    "fieldCodes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["documentVersionIds"],
                "additionalProperties": False,
            }
        if name == "extract_table_records":
            return {
                "type": "object",
                "properties": {
                    "documentVersionIds": {"type": "array", "items": {"type": "string"}},
                    "businessSchemas": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["documentVersionIds"],
                "additionalProperties": False,
            }
        return {
            "type": "object",
            "properties": {
                "documentVersionIds": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["documentVersionIds"],
            "additionalProperties": False,
        }

    runtime_names = [
        "get_document_ocr_result",
        "extract_document_fields",
        "extract_table_records",
        "locate_evidence_fragment",
    ]
    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "inspect_r19_review_context",
                "description": (
                    "读取R19固定审查问题、输入文档索引、OCR证据预览、已完成的人工确认和已登记EvidenceRef。"
                    "不作符合性判断。"
                ),
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        *[
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str((tool_catalog.get(name) or {}).get("capability") or "读取文档事实和证据。"),
                    "parameters": schema_for_runtime(name),
                },
            }
            for name in runtime_names
        ],
        {
            "type": "function",
            "function": {
                "name": "validate_r19_semantic_judgment",
                "description": (
                    "校验单个R19语义判断的结果、解释、条款和EvidenceRef是否满足结构与证据约束；"
                    "本Tool不修改该判断的业务结果。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "atomicCheckId": {"type": "string"},
                        "judgment": {"type": "object"},
                    },
                    "required": ["atomicCheckId", "judgment"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "request_r19_human_input",
                "description": (
                    "当现有文件不能可靠判断R19关键事实、证据冲突或需要专业人员确认时，创建结构化人工任务并暂停。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "questionIds": {"type": "array", "items": {"type": "string"}},
                        "reason": {"type": "string"},
                        "title": {"type": "string"},
                        "instructions": {"type": "string"},
                    },
                    "required": ["questionIds", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit_r19_semantic_review",
                "description": (
                    "提交覆盖AC-R19-01至AC-R19-08的结构化语义判断。passed、failed和not_applicable均必须引用"
                    "已登记EvidenceRef；节点result由服务端固定聚合，模型不能自行指定。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "atomicJudgments": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "atomicCheckId": {"type": "string"},
                                    "result": {
                                        "type": "string",
                                        "enum": [
                                            "passed",
                                            "failed",
                                            "evidence_insufficient",
                                            "not_applicable",
                                            "human_review_required",
                                        ],
                                    },
                                    "explanation": {"type": "string"},
                                    "reasonCodes": {"type": "array", "items": {"type": "string"}},
                                    "evidenceRefIds": {"type": "array", "items": {"type": "string"}},
                                    "clauseRefs": {"type": "array", "items": {"type": "string"}},
                                    "missingFacts": {"type": "array", "items": {"type": "string"}},
                                    "recommendedAction": {"type": "string"},
                                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                },
                                "required": [
                                    "atomicCheckId",
                                    "result",
                                    "explanation",
                                    "evidenceRefIds",
                                    "clauseRefs",
                                    "confidence",
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "summary": {"type": "string"},
                        "recommendedActions": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["atomicJudgments", "summary"],
                    "additionalProperties": False,
                },
            },
        },
    ]
    model_context = r19_context_for_model(agent_context)
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "你是R19境外牌号材料复核Agent。固定依据为TSG D7006-2020附件D D2.4.1(8)和"
                "TSG 31-2025第2.1.2条。文件格式不固定，因此你负责逐问题进行跨文件语义分析；"
                "但不得编造文件事实、条款或EvidenceRef。先读取上下文，必要时读取OCR字段/表格并定位证据。"
                "每个passed、failed或not_applicable判断必须引用已登记EvidenceRef。企业标准仅在境内制造单位"
                "使用境外牌号材料时适用。现有证据不足、冲突或需要专业判断时调用request_r19_human_input；"
                "可以可靠完成时调用submit_r19_semantic_review。节点结果由服务端固定聚合。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "完成R19全部八个原子项的证据化语义审查。",
                    "context": model_context,
                },
                ensure_ascii=False,
                default=str,
            ),
        },
    ]
    reasoning_chunks: list[str] = []
    model_attempt = {
        "id": f"MCALL-R19-{uuid4().hex[:10].upper()}",
        "reviewRunId": review_run.get("reviewRunId"),
        "aiRunId": review_run.get("aiRunId"),
        "projectId": review_run.get("projectId"),
        "nodeId": 19,
        "stage": "r19_llm_semantic_primary",
        "callKind": "agent_tool_call",
        "provider": review_run.get("modelGateway") or "qwen_runtime",
        "modelAlias": review_run.get("modelAlias"),
        "status": "running",
        "promptHash": stable_hash_payload(messages),
        "createdAt": server_time(),
        "startedAt": server_time(),
        "updatedAt": server_time(),
    }
    repo.state.setdefault("model_call_attempts", []).insert(0, model_attempt)
    last_response: dict[str, Any] = {}
    try:
        client = qwen_runtime_client()
        max_turns = max(4, min(20, int(os.getenv("AICHECK_R19_AGENT_MAX_TURNS", "12"))))
        for turn in range(1, max_turns + 1):
            response = client.chat_sync(
                messages,
                model=str(review_run.get("modelAlias") or "review-chat"),
                tools=tools,
                tool_choice="auto",
                temperature=0.0,
                max_tokens=2200,
                timeout=max(30.0, float(os.getenv("AICHECK_QWEN_REVIEW_TIMEOUT_SECONDS", "180"))),
                _raw_capture_context=raw_context_from_record(
                    review_run,
                    model_call_attempt_id=str(model_attempt["id"]),
                    stage=str(model_attempt["stage"]),
                    turn=turn,
                ),
            )
            last_response = response
            choices = response.get("choices") if isinstance(response.get("choices"), list) else []
            message = (choices[0].get("message") or {}) if choices and isinstance(choices[0], dict) else {}
            reasoning = message.get("reasoning_content") or message.get("reasoning")
            if reasoning:
                content = str(reasoning)
                reasoning_chunks.append(content)
                append_review_event(
                    str(review_run.get("reviewRunId") or ""),
                    event_type="agent.reasoning.delta",
                    title="R19 模型推理流",
                    status="running",
                    node_key="r19_agent_semantic_review",
                    details={
                        "turn": turn,
                        "content": content,
                        "contentHash": stable_hash_payload(content),
                        "sourceField": "reasoning_content" if message.get("reasoning_content") else "reasoning",
                    },
                )
            tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
            trace["llmCalled"] = True
            if not tool_calls:
                break
            messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": tool_calls})
            for call in tool_calls:
                function = call.get("function") if isinstance(call, dict) else {}
                tool_name = str((function or {}).get("name") or "")
                raw_arguments = (function or {}).get("arguments") or "{}"
                try:
                    arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
                except (TypeError, ValueError, json.JSONDecodeError):
                    arguments = {}
                if tool_name in runtime_names:
                    requested_ids = {str(item) for item in arguments.get("documentVersionIds") or [] if item}
                    if requested_ids - document_version_ids:
                        output = {"status": "rejected", "errorCode": "R19_DOCUMENT_SCOPE_VIOLATION"}
                    else:
                        if not requested_ids:
                            arguments["documentVersionIds"] = sorted(document_version_ids)
                        output = dispatch_runtime_tool(repo.state, tool_name, arguments)
                        for evidence in output.get("evidenceRefs") or []:
                            if not isinstance(evidence, dict):
                                continue
                            evidence_id = str(evidence.get("evidenceRefId") or evidence.get("id") or "")
                            if evidence_id:
                                evidence_index[evidence_id] = evidence
                                known_evidence_ids.add(evidence_id)
                elif tool_name == "inspect_r19_review_context":
                    output = r19_context_for_model(agent_context)
                elif tool_name == "validate_r19_semantic_judgment":
                    arguments["knownEvidenceRefIds"] = sorted(known_evidence_ids)
                    arguments["evidenceIndex"] = evidence_index
                    output = dispatch_runtime_tool(repo.state, tool_name, arguments)
                elif tool_name == "request_r19_human_input":
                    registered_ids = {item["questionId"] for item in R19_REVIEW_QUESTIONS}
                    selected_ids = [
                        str(item)
                        for item in arguments.get("questionIds") or []
                        if str(item) in registered_ids
                    ]
                    output = {
                        "status": "waiting_human_input_required",
                        "questionIds": selected_ids or sorted(registered_ids),
                    }
                    trace["requestedHumanInput"] = True
                    trace["humanInputRequest"] = {**arguments, "questionIds": output["questionIds"]}
                elif tool_name == "submit_r19_semantic_review":
                    validation = validate_r19_semantic_submission(
                        arguments,
                        known_evidence_ref_ids=known_evidence_ids,
                        evidence_index=evidence_index,
                    )
                    output = validation
                    if validation.get("status") == "valid":
                        trace.update(
                            {
                                "submitted": True,
                                "atomicJudgments": validation.get("atomicJudgments") or [],
                                "result": validation.get("result"),
                                "summary": validation.get("summary"),
                                "recommendedActions": validation.get("recommendedActions") or [],
                                "knownEvidenceRefIds": sorted(known_evidence_ids),
                            }
                        )
                else:
                    output = {"status": "rejected", "errorCode": "R19_AGENT_TOOL_NOT_ALLOWED"}
                compact = compact_tool_output(output)
                trace["toolCalls"].append(
                    {
                        "toolName": tool_name,
                        "argumentsHash": stable_hash_payload(arguments),
                        "output": compact,
                    }
                )
                append_tool_call(review_run, "r19_agent_semantic_review", tool_name, compact)
                append_review_event(
                    str(review_run.get("reviewRunId") or ""),
                    event_type="agent.tool_call.completed",
                    title=f"R19 Tool：{tool_name}",
                    status=str(output.get("status") or "completed"),
                    node_key="r19_agent_semantic_review",
                    details={"turn": turn, "toolName": tool_name, "output": compact},
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(call.get("id") or f"r19-{len(trace['toolCalls'])}"),
                        "content": json.dumps(output, ensure_ascii=False, default=str),
                    }
                )
            if trace.get("requestedHumanInput") or trace.get("submitted"):
                break

        if not trace.get("requestedHumanInput") and not trace.get("submitted"):
            trace.update(
                {
                    "controlMode": "r19_llm_incomplete_human_guard",
                    "requestedHumanInput": True,
                    "humanInputRequest": {
                        "questionIds": [item["questionId"] for item in R19_REVIEW_QUESTIONS],
                        "reason": "R19 Agent reached its execution boundary without a valid evidence-bound submission.",
                        "title": "人工确认 R19 未完成的语义审查事实",
                    },
                }
            )
        trace["reasoningContent"] = "\n".join(reasoning_chunks)
        model_attempt.update(
            {
                "status": "succeeded",
                "responseHash": stable_hash_payload(last_response),
                "reasoningContent": trace["reasoningContent"],
                "toolCallCount": len(trace["toolCalls"]),
                "submitted": bool(trace.get("submitted")),
                "requestedHumanInput": bool(trace.get("requestedHumanInput")),
                "finishedAt": server_time(),
                "updatedAt": server_time(),
            }
        )
        return trace
    except Exception as exc:
        trace.update(
            {
                "controlMode": "r19_llm_failed_human_guard",
                "requestedHumanInput": True,
                "humanInputRequest": {
                    "questionIds": [item["questionId"] for item in R19_REVIEW_QUESTIONS],
                    "reason": f"R19 semantic Agent failed safely: {type(exc).__name__}",
                    "title": "人工确认 R19 境外牌号材料审查事实",
                },
                "errorType": type(exc).__name__,
                "reasoningContent": "\n".join(reasoning_chunks),
            }
        )
        model_attempt.update(
            {
                "status": "failed",
                "failureReason": type(exc).__name__,
                "reasoningContent": trace["reasoningContent"],
                "finishedAt": server_time(),
                "updatedAt": server_time(),
            }
        )
        return trace


def _plan_guarded_material_tool_review(
    review_run: dict[str, Any],
    *,
    node_id: int,
    inspect_tool_name: str,
    inspect_output: dict[str, Any],
    required_tool_arguments: dict[str, dict[str, Any]],
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    """Run a bounded LLM Tool Loop while keeping deterministic execution as the safety guard."""

    ensure_review_state()
    mode = review_llm_execution_mode()
    required_tools = list(required_tool_arguments)
    trace: dict[str, Any] = {
        "controlMode": "deterministic_workflow_guard",
        "llmExecution": mode,
        "llmCalled": False,
        "toolCalls": [],
        "requiredTools": [inspect_tool_name, *required_tools],
        "missingRequiredTools": [inspect_tool_name, *required_tools],
    }
    if mode in {"deterministic", "disabled", "mock"}:
        return trace

    inspect_tool = {
        "type": "function",
        "function": {
            "name": inspect_tool_name,
            "description": "读取当前节点已构造的结构化业务事实，不作符合性判断。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    }
    tools = [inspect_tool, *build_llm_tools_for_runtime(required_tools)]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    reasoning_chunks: list[str] = []
    called_tools: set[str] = set()
    model_attempt = {
        "id": f"MCALL-R{node_id}-{uuid4().hex[:10].upper()}",
        "reviewRunId": review_run.get("reviewRunId"),
        "aiRunId": review_run.get("aiRunId"),
        "projectId": review_run.get("projectId"),
        "nodeId": node_id,
        "stage": f"r{node_id}_agent_tool_review",
        "callKind": "agent_tool_call",
        "provider": review_run.get("modelGateway") or "qwen_runtime",
        "modelAlias": review_run.get("modelAlias"),
        "status": "running",
        "promptHash": stable_hash_payload(messages),
        "createdAt": server_time(),
        "startedAt": server_time(),
        "updatedAt": server_time(),
    }
    repo.state.setdefault("model_call_attempts", []).insert(0, model_attempt)
    last_response: dict[str, Any] = {}
    try:
        client = qwen_runtime_client()
        for _ in range(len(required_tools) + 3):
            response = client.chat_sync(
                messages,
                model=str(review_run.get("modelAlias") or "review-chat"),
                tools=tools,
                tool_choice="auto",
                temperature=0.0,
                max_tokens=1000,
                timeout=max(30.0, float(os.getenv("AICHECK_QWEN_REVIEW_TIMEOUT_SECONDS", "180"))),
                _raw_capture_context=raw_context_from_record(
                    review_run,
                    model_call_attempt_id=str(model_attempt["id"]),
                    stage=str(model_attempt["stage"]),
                    turn=len(trace["toolCalls"]) + 1,
                ),
            )
            last_response = response
            choices = response.get("choices") if isinstance(response.get("choices"), list) else []
            message = (choices[0].get("message") or {}) if choices and isinstance(choices[0], dict) else {}
            reasoning = message.get("reasoning_content") or message.get("reasoning")
            if reasoning:
                reasoning_chunks.append(str(reasoning))
            tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
            trace["llmCalled"] = True
            if not tool_calls:
                break
            messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": tool_calls})
            for call in tool_calls:
                function = call.get("function") if isinstance(call, dict) else {}
                tool_name = str((function or {}).get("name") or "")
                if tool_name == inspect_tool_name:
                    output = inspect_output
                elif tool_name in required_tool_arguments:
                    output = dispatch_runtime_tool(repo.state, tool_name, required_tool_arguments[tool_name])
                else:
                    output = {"status": "rejected", "errorCode": f"R{node_id}_AGENT_TOOL_NOT_ALLOWED"}
                if tool_name in {inspect_tool_name, *required_tools}:
                    called_tools.add(tool_name)
                trace["toolCalls"].append(
                    {"toolName": tool_name, "argumentsHash": stable_hash_payload(required_tool_arguments.get(tool_name, {})), "output": compact_tool_output(output)}
                )
                append_tool_call(review_run, f"r{node_id}_agent_precheck", tool_name, compact_tool_output(output))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(call.get("id") or f"r{node_id}-{len(trace['toolCalls'])}"),
                        "content": json.dumps(output, ensure_ascii=False, default=str),
                    }
                )
            if called_tools >= {inspect_tool_name, *required_tools}:
                break

        missing = [name for name in [inspect_tool_name, *required_tools] if name not in called_tools]
        trace.update(
            {
                "controlMode": "llm_tool_call_guarded" if not missing else "llm_tool_call_with_workflow_guard",
                "missingRequiredTools": missing,
                "reasoningContent": "\n".join(reasoning_chunks),
            }
        )
        model_attempt.update(
            {
                "status": "succeeded",
                "responseHash": stable_hash_payload(last_response),
                "reasoningContent": trace["reasoningContent"],
                "toolCallCount": len(trace["toolCalls"]),
                "finishedAt": server_time(),
                "updatedAt": server_time(),
            }
        )
        return trace
    except Exception as exc:
        trace.update(
            {
                "controlMode": "llm_failed_workflow_guard",
                "errorType": type(exc).__name__,
                "reasoningContent": "\n".join(reasoning_chunks),
            }
        )
        model_attempt.update(
            {
                "status": "failed",
                "failureReason": type(exc).__name__,
                "reasoningContent": trace["reasoningContent"],
                "finishedAt": server_time(),
                "updatedAt": server_time(),
            }
        )
        return trace


def apply_r12_human_input_for_review_run(
    review_run_id: str,
    task_id: str,
    payload: dict[str, Any],
    *,
    actor_id: str | None,
    actor_name: str | None,
    command_id: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    ensure_review_state()
    review_run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one(
        "review_runs", review_run_id
    )
    if not review_run:
        return {"status": "missing", "reviewRunId": review_run_id}
    if not commit:
        return validate_r12_human_input(review_run, task_id, payload)
    result = apply_r12_human_input(
        review_run,
        task_id,
        payload,
        actor_id=actor_id,
        actor_name=actor_name,
        command_id=command_id,
    )
    if result.get("status") != "applied":
        return result
    bump_review_run_revision(review_run)
    ai_run = repo.find_one("ai_runs", str(review_run.get("aiRunId") or ""))
    if ai_run:
        ai_run["status"] = "推理中"
    append_review_event(
        review_run_id,
        event_type="human_input.r12_registry_verification_submitted",
        title="R12 官网人工核验结果已提交",
        status="resuming",
        details={
            "taskId": task_id,
            "responseId": (result.get("response") or {}).get("responseId"),
            "candidateCount": len((result.get("response") or {}).get("verifications") or []),
            "actorId": actor_id,
            "commandId": command_id,
        },
    )
    return result


def apply_review_human_input_for_review_run(
    review_run_id: str,
    task_id: str,
    payload: dict[str, Any],
    *,
    actor_id: str | None,
    actor_name: str | None,
    command_id: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Validate or apply any registered blocking human-input task."""

    ensure_review_state()
    review_run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one(
        "review_runs", review_run_id
    )
    if not review_run:
        return {"status": "missing", "reviewRunId": review_run_id}
    task = next(
        (
            item
            for item in review_run.get("humanInputTasks") or []
            if isinstance(item, dict) and str(item.get("taskId") or "") == str(task_id)
        ),
        None,
    )
    if not task:
        return {"status": "missing_task", "errors": ["human_input_task_not_found"]}
    task_type = str(task.get("taskType") or "")
    if task_type == R19_TASK_TYPE:
        if not commit:
            return validate_r19_human_input(review_run, task_id, payload)
        result = apply_r19_human_input(
            review_run,
            task_id,
            payload,
            actor_id=actor_id,
            actor_name=actor_name,
            command_id=command_id,
        )
        if result.get("status") != "applied":
            return result
        bump_review_run_revision(review_run)
        ai_run = repo.find_one("ai_runs", str(review_run.get("aiRunId") or ""))
        if ai_run:
            ai_run["status"] = "推理中"
        append_review_event(
            review_run_id,
            event_type="agent.human_input.accepted",
            title="R19 人工语义证据确认已提交",
            status="resuming",
            details={
                "taskId": task_id,
                "taskType": task_type,
                "responseId": (result.get("response") or {}).get("responseId"),
                "answerCount": len((result.get("response") or {}).get("answers") or []),
                "actorId": actor_id,
                "commandId": command_id,
            },
        )
        return result
    if task_type == "official_registry_license_verification":
        return apply_r12_human_input_for_review_run(
            review_run_id,
            task_id,
            payload,
            actor_id=actor_id,
            actor_name=actor_name,
            command_id=command_id,
            commit=commit,
        )
    return {"status": "invalid_input", "errors": ["human_input_task_type_not_registered"]}


def execute_review_run_inline(review_run_id: str) -> dict[str, Any]:
    """同步执行一次 ReviewRun，并保证结果落库。

    ## 为什么要包这一层

    2026-08-15 前端操作审计实测：监检点「发起缺项预审」，接口返回
    `status: waiting_human_review`，而数据库里那条运行永远停在 `queued`、
    promptAudit 0 字符、findingDrafts 0 条。等 45 秒仍是 queued。

    界面轮询读的是落库状态，所以**永远显示排队中**——AI 复核在界面上出不来结果。

    原因是里面这个函数体有 6 个返回点，**一次 flush_state_records 都没有**。
    失败之所以能落库，是因为异常路径在 dispatcher 和各 except 分支里另外显式
    调了 flush。于是形成一个很坏的不对称：**失败看得见，成功看不见。**

    用 try/finally 而不是在 6 个 return 前各加一行：出口还会再增加，
    加一个忘一个，这个 bug 就会以同样的形状回来。
    """
    try:
        return _execute_review_run_inline(review_run_id)
    finally:
        # 落库失败不能把已经跑完的审查结果连带吞掉——那会从「结果看不见」
        # 变成「结果没了」。这里记下来继续，由调用方拿到的返回值兜住。
        try:
            records = review_run_state_records(review_run_id)
            # 落库必须用**执行时手上那个对象**，不能再查一次。
            #
            # 并发重载会整体替换 repo.state["review_runs"]：换掉之后，执行真正
            # 改的那个对象就和 state 脱钩了，再查只能查到重载来的干净副本
            # （还停在 queued）。2026-08-15 实测就是这样——事件一路跑到
            # waiting_human_review，库里那条运行却仍是 queued、promptAudit 0：
            # **跑完了，但落库落的是旧的。**
            inflight = _INFLIGHT_REVIEW_RUNS.get(review_run_id)
            if inflight is not None and records:
                records["review_runs"] = [inflight]
            if records:
                flush_state_records(records)
        except Exception:  # noqa: BLE001 - 落库尽力而为，不掀翻已跑完的结果
            # 但必须留下声音。第一版这里是 `pass`，结果把真正的根因盖了整整一轮：
            # flush 抛在 ai_runs 上（别的进程改过那条），事务回滚，
            # review_runs 跟着一起没落库——界面永远显示排队中，日志里一个字都没有。
            logging.getLogger(__name__).exception("ReviewRun %s 落库失败", review_run_id)
        finally:
            _INFLIGHT_REVIEW_RUNS.pop(review_run_id, None)
            repo.unpin_object(REVIEW_RUN_COLLECTION_NAME, review_run_id)


# 正在执行中的运行记录，按 reviewRunId 索引。存在的唯一理由是并发重载会把
# repo.state["review_runs"] 整体换掉，导致执行中的对象与 state 脱钩——
# 落库时得认这个对象，而不是重新去 state 里查一个已经不是它的副本。
_INFLIGHT_REVIEW_RUNS: dict[str, dict[str, Any]] = {}

# 物理集合名，pin_object 用。走 STATE_COLLECTIONS 取而不是写死字符串——
# 两者一旦不一致，钉住会静默失效（钉了个不存在的集合，谁都不会报错）。
REVIEW_RUN_COLLECTION_NAME = STATE_COLLECTIONS["review_runs"]


def _execute_review_run_inline(review_run_id: str) -> dict[str, Any]:
    ensure_review_state()
    review_run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if not review_run:
        # 2026-08-15 线上实测：工作台开着（每 3 秒轮一次）时，这里必然找不到。
        #
        #   工作台开着：5.4s 返回 → status=missing → 运行永远停在 queued
        #   工作台关掉：91.1s 返回 → waiting_human_review → 正常完成
        #
        # 并发请求做作用域加载时会**整体替换** repo.state["review_runs"] 这个列表。
        # ai-recheck 刚把新运行插进内存、还没轮到执行，轮询把列表换掉，记录就没了。
        #
        # 建记录时已经落过库（create_review_run_from_ai_run 末尾那次 flush），
        # 所以从库里捞回来即可——比起「让上游别并发」，这条更结实：
        # 谁都可能在任何时刻触发一次重载。
        load_review_run_state(review_run_id)
        review_run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one(
            "review_runs", review_run_id
        )
    if not review_run:
        return {"reviewRunId": review_run_id, "status": "missing"}
    # 记下这一份，落库时认它——中途若被并发重载换掉，state 里那份就不是它了。
    _INFLIGHT_REVIEW_RUNS[review_run_id] = review_run
    # 更根本的一道：让并发加载别去覆盖它。只记住对象还不够——执行体里后续
    # 还会再 find_one 拿这条运行，覆盖之后拿到的就是另一个对象，改在那上面，
    # 我记住的这份反而成了旧的。实测就栽在这：事件跑完了，库里仍是 queued。
    repo.pin_object(REVIEW_RUN_COLLECTION_NAME, review_run_id)
    if review_run.get("status") in {"waiting_human_input", "waiting_human_review", *REVIEW_RUN_TERMINAL_STATUSES}:
        return {"reviewRunId": review_run_id, "status": review_run.get("status"), "alreadyCompleted": True}
    ai_run = repo.find_one("ai_runs", str(review_run.get("aiRunId")))
    if is_r12_formal_review(review_run):
        candidates = extract_r12_license_candidates(repo.state, review_run)
        completed_for_input = any(
            isinstance(item, dict)
            and item.get("taskType") == "official_registry_license_verification"
            and item.get("status") == "completed"
            and item.get("reviewRunInputHash") == review_run.get("inputHash")
            for item in review_run.get("humanInputTasks") or []
        )
        requested_by, agent_trace = plan_r12_human_verification(review_run, candidates) if candidates and not completed_for_input else (
            "workflow_guard",
            {
                "controlMode": (
                    "human_registry_verification_completed"
                    if completed_for_input
                    else "no_license_candidate_continue_to_rule_engine"
                ),
                "llmCalled": False,
                "requestedHumanInput": False,
            },
        )
        task = ensure_r12_human_input_task(
            repo.state,
            review_run,
            requested_by=requested_by,
            agent_trace=agent_trace,
        )
        if task:
            review_run["status"] = "waiting_human_input"
            review_run["currentStep"] = "waiting_r12_registry_verification"
            review_run["r12AgentControl"] = agent_trace
            if not task.get("waitingEventRecorded"):
                task["waitingEventRecorded"] = True
                append_review_event(
                    review_run_id,
                    event_type="human_input.r12_registry_verification_required",
                    title="R12 等待官网人工核验",
                    status="waiting_human_input",
                    details={
                        "taskId": task.get("taskId"),
                        "candidateCount": task.get("candidateCount"),
                        "requestedBy": requested_by,
                        "controlMode": agent_trace.get("controlMode"),
                    },
                )
            bump_review_run_revision(review_run)
            if ai_run:
                ai_run["status"] = "待人工核验"
                ai_run["reviewRunId"] = review_run_id
            return {
                "reviewRunId": review_run_id,
                "status": "waiting_human_input",
                "humanInputTaskId": task.get("taskId"),
            }
    if is_r19_formal_review(review_run):
        r19_context = build_r19_agent_context(repo.state, review_run)
        agent_trace = plan_r19_semantic_review(review_run, r19_context)
        review_run["r19AgentContext"] = r19_context_for_model(r19_context)
        review_run["r19AgentControl"] = agent_trace
        if agent_trace.get("requestedHumanInput"):
            task = ensure_r19_human_input_task(
                review_run,
                agent_trace.get("humanInputRequest") if isinstance(agent_trace.get("humanInputRequest"), dict) else {},
                requested_by=(
                    "llm_agent"
                    if agent_trace.get("llmCalled") and agent_trace.get("controlMode") == R19_EXECUTION_MODE
                    else "workflow_guard"
                ),
                agent_trace=agent_trace,
                agent_context=r19_context,
            )
            if task:
                review_run["status"] = "waiting_human_input"
                review_run["currentStep"] = "waiting_r19_semantic_evidence_confirmation"
                if not task.get("waitingEventRecorded"):
                    task["waitingEventRecorded"] = True
                    append_review_event(
                        review_run_id,
                        event_type="agent.human_input.required",
                        title="R19 等待人工确认关键事实",
                        status="waiting_human_input",
                        details={
                            "taskId": task.get("taskId"),
                            "taskType": task.get("taskType"),
                            "questionCount": task.get("questionCount"),
                            "controlMode": agent_trace.get("controlMode"),
                        },
                    )
                bump_review_run_revision(review_run)
                if ai_run:
                    ai_run["status"] = "待人工核验"
                    ai_run["reviewRunId"] = review_run_id
                return {
                    "reviewRunId": review_run_id,
                    "status": "waiting_human_input",
                    "humanInputTaskId": task.get("taskId"),
                }
        if agent_trace.get("submitted"):
            review_run["r19SemanticReview"] = {
                "executionMode": R19_EXECUTION_MODE,
                "result": agent_trace.get("result"),
                "atomicJudgments": repo.clone(agent_trace.get("atomicJudgments") or []),
                "summary": agent_trace.get("summary"),
                "recommendedActions": repo.clone(agent_trace.get("recommendedActions") or []),
                "knownEvidenceRefIds": repo.clone(agent_trace.get("knownEvidenceRefIds") or []),
                "createdAt": server_time(),
            }
    node_id = int(review_run.get("nodeId") or 0)
    is_formal_material_agent = (
        node_id in {13, 14, 15, 16, 17, 18}
        and str(review_run.get("reviewMode") or "formal") == "formal"
        and not bool(review_run.get("advisoryOnly"))
    )
    if is_formal_material_agent:
        material_facts = {
            13: build_r13_business_facts,
            14: build_r14_business_facts,
            15: build_r15_business_facts,
            16: build_r16_business_facts,
            17: build_r17_business_facts,
            18: build_r18_business_facts,
        }[node_id](repo.state, review_run)
        agent_trace = {
            13: plan_r13_tool_review,
            14: plan_r14_tool_review,
            15: plan_r15_tool_review,
            16: plan_r16_tool_review,
            17: plan_r17_tool_review,
            18: plan_r18_tool_review,
        }[node_id](review_run, material_facts)
        review_run[f"r{node_id}AgentControl"] = agent_trace
    review_run["status"] = "running"
    review_run["startedAt"] = review_run.get("startedAt") or server_time()
    bump_review_run_revision(review_run)
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
        bump_review_run_revision(review_run)
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
            deterministic_verdict = str(
                next(iter(context.get("ruleResults") or []), {}).get("result") or ""
            )
            ai_run.setdefault("suggestion", {}).update(
                {
                    # 建议结论携带确定性判定（最终仍由监检人员确认，任何结论不自动成立）。
                    "result": SUGGESTION_RESULT_LABELS.get(deterministic_verdict, "需人工确认"),
                    "deterministicResult": deterministic_verdict or None,
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
        retryable = review_failure_retryable(exc)
        # 只有 Temporal 编排下才有东西真的会来重试（apps/review_worker/activities.py
        # 是 retry_pending 的唯一消费方）。线上跑的是 inline 模式、根本没起
        # review-worker——这时候标成 retry_pending，运行就永远停在那儿，而界面
        # 显示「等待重试」，等的却是一个不存在的人。
        #
        # 没有重试者就不说等待重试：标成失败，并把 retryable 如实带出去，
        # 由失败横幅给出「可以重跑」的按钮，让人自己决定要不要花这次成本。
        retryable = retryable and has_review_retry_consumer()
        failure_status = "retry_pending" if retryable else "failed"
        error_code = (
            str(exc.reason)
            if isinstance(exc, IntegrationServiceError) and exc.reason
            else "REVIEW_WORKFLOW_TRANSIENT_FAILURE"
            if retryable
            else "REVIEW_WORKFLOW_FAILED"
        )
        review_run["status"] = failure_status
        review_run["retryableFailure"] = retryable
        review_run["errorCode"] = error_code
        review_run["errorMessage"] = str(exc) if isinstance(exc, IntegrationServiceError) else type(exc).__name__
        review_run["finishedAt"] = server_time()
        bump_review_run_revision(review_run)
        append_review_event(
            review_run_id,
            event_type="review_run.retry_pending" if retryable else "review_run.failed",
            title="ReviewRun 等待重试" if retryable else "ReviewRun 执行失败",
            status=failure_status,
            details={"errorCode": error_code, "retryable": retryable},
        )
        if ai_run:
            ai_run["status"] = "等待重试" if retryable else "失败"
            ai_run["errorCode"] = error_code
            ai_run["errorMessage"] = "Temporal/LangGraph 审查编排暂时失败。" if retryable else "Temporal/LangGraph 审查编排执行失败。"
        if not retryable and not review_run.get("advisoryOnly"):
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
        return {
            "reviewRunId": review_run_id,
            "status": failure_status,
            "errorCode": error_code,
            "retryable": retryable,
        }


def run_step(review_run: dict[str, Any], node_key: str, context: dict[str, Any]) -> dict[str, Any]:
    audit_runtime = audit_runtime_for_run(review_run)
    context["auditRuntime"] = audit_runtime
    if node_key == "load_context":
        project = repo.require_project(str(review_run.get("projectId")))
        node = repo.node(str(review_run.get("projectId")), int(review_run.get("nodeId") or 0))
        context["project"] = project or {}
        context["node"] = node or {}
        if int(review_run.get("nodeId") or 0) == 12:
            context["businessFacts"] = build_r12_business_facts(repo.state, review_run)
        elif int(review_run.get("nodeId") or 0) == 13:
            context["businessFacts"] = build_r13_business_facts(repo.state, review_run)
        elif int(review_run.get("nodeId") or 0) == 14:
            context["businessFacts"] = build_r14_business_facts(repo.state, review_run)
        elif int(review_run.get("nodeId") or 0) == 15:
            context["businessFacts"] = build_r15_business_facts(repo.state, review_run)
        elif int(review_run.get("nodeId") or 0) == 16:
            context["businessFacts"] = build_r16_business_facts(repo.state, review_run)
        elif int(review_run.get("nodeId") or 0) == 17:
            context["businessFacts"] = build_r17_business_facts(repo.state, review_run)
        elif int(review_run.get("nodeId") or 0) == 18:
            context["businessFacts"] = build_r18_business_facts(repo.state, review_run)
        elif int(review_run.get("nodeId") or 0) == 19:
            context["businessFacts"] = build_r19_agent_context(repo.state, review_run)
        elif int(review_run.get("nodeId") or 0) == 20:
            context["businessFacts"] = build_r20_business_facts(repo.state, review_run)
        elif int(review_run.get("nodeId") or 0) == 21:
            context["businessFacts"] = build_r21_business_facts(repo.state, review_run)
        elif int(review_run.get("nodeId") or 0) == 22:
            context["businessFacts"] = build_r22_business_facts(repo.state, review_run)
        elif int(review_run.get("nodeId") or 0) == 23:
            context["businessFacts"] = build_r23_business_facts(repo.state, review_run)
        elif f"r{int(review_run.get('nodeId') or 0)}" in R24_R34_FACT_BUILDERS:
            builder = R24_R34_FACT_BUILDERS[f"r{int(review_run.get('nodeId') or 0)}"]
            context["businessFacts"] = builder(repo.state, review_run)
        applied_corrections = apply_node_fact_corrections(
            repo.state,
            str(review_run.get("projectId") or ""),
            int(review_run.get("nodeId") or 0),
            context.get("businessFacts") if isinstance(context.get("businessFacts"), dict) else None,
        )
        if applied_corrections:
            review_run["appliedFactCorrections"] = repo.clone(applied_corrections)
        clause_snapshot = review_run_clause_snapshot(repo.state, str(review_run.get("reviewRunId") or ""))
        context["clausePackageSnapshot"] = clause_snapshot or {}
        return {
            "projectId": review_run.get("projectId"),
            "nodeId": review_run.get("nodeId"),
            "nodeName": (node or {}).get("name"),
            "clausePackageId": (clause_snapshot or {}).get("packageStorageId"),
            "fixedClauseCount": len((clause_snapshot or {}).get("clauses") or []),
            "appliedFactCorrections": len(applied_corrections),
        }
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
        if context.get("businessFacts"):
            business_facts = context.get("businessFacts") if isinstance(context.get("businessFacts"), dict) else {}
            if int(review_run.get("nodeId") or 0) == 19:
                context["evidenceFacts"] = []
                business_evidence_refs = [
                    item
                    for item in (business_facts.get("evidenceIndex") or {}).values()
                    if isinstance(item, dict)
                ]
            else:
                judgment = business_facts.get("judgment") if isinstance(business_facts.get("judgment"), dict) else {}
                context["evidenceFacts"] = [
                    item for item in judgment.get("claimedFacts") or [] if isinstance(item, dict)
                ]
                business_evidence_refs = [
                    item for item in judgment.get("evidenceRefs") or [] if isinstance(item, dict)
                ]
            known_evidence_ids = {
                str(item.get("id") or item.get("evidenceRefId") or "") for item in evidence_links
            }
            evidence_links = [
                *evidence_links,
                *[
                    item
                    for item in business_evidence_refs
                    if str(item.get("id") or item.get("evidenceRefId") or "") not in known_evidence_ids
                ],
            ]
            grounding_input["evidenceLinks"] = evidence_links
            grounding_input.setdefault("summary", {})["evidenceLinkCount"] = len(evidence_links)
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
        project = context.get("project") or repo.require_project(str(review_run.get("projectId") or "")) or {}
        pack = project.get("businessPackSnapshot") or load_business_pack(
            str(review_run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID)
        )
        pack = repo.clone(pack)
        if review_run.get("atomicCheckToolBindingSetSnapshot"):
            pack["atomicCheckToolBindingSet"] = repo.clone(review_run["atomicCheckToolBindingSetSnapshot"])
        if review_run.get("atomicCheckToolBindingsSnapshot"):
            pack["atomicCheckToolBindings"] = repo.clone(review_run["atomicCheckToolBindingsSnapshot"])
        rule = (
            current_published_rule_for_node(
                int(review_run.get("nodeId") or 0),
                business_pack_id=str(review_run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID),
            )
            or matching_rule_for_node(pack, int(review_run.get("nodeId") or 0))
            or next(iter(pack.get("ruleSets") or []), {})
        )
        fixed_clauses = (context.get("clausePackageSnapshot") or {}).get("clauses") or []
        if fixed_clauses:
            linked_clause_ids = [
                item.get("clauseReferenceId") or item.get("sourceLocatorId")
                for item in fixed_clauses
                if item.get("clauseReferenceId") or item.get("sourceLocatorId")
            ]
        else:
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
        source_rule_id = str(rule.get("sourceRuleId") or rule.get("id") or rule.get("ruleKey") or "")
        semantic_review = review_run.get("r19SemanticReview") if int(review_run.get("nodeId") or 0) == 19 else None
        if isinstance(semantic_review, dict) and semantic_review.get("atomicJudgments"):
            atomic_results = []
            for judgment in semantic_review.get("atomicJudgments") or []:
                if not isinstance(judgment, dict):
                    continue
                atomic_results.append(
                    {
                        "atomicCheckId": judgment.get("atomicCheckId"),
                        "sourceRuleId": "R19",
                        "result": judgment.get("result"),
                        "reasonCodes": judgment.get("reasonCodes") or [],
                        "evidenceRefIds": judgment.get("evidenceRefIds") or [],
                        "clauseRefs": judgment.get("clauseRefs") or [],
                        "explanation": judgment.get("explanation"),
                        "missingFacts": judgment.get("missingFacts") or [],
                        "recommendedAction": judgment.get("recommendedAction"),
                        "confidence": judgment.get("confidence"),
                        "sourceMethod": R19_EXECUTION_MODE,
                    }
                )
            result_counts: dict[str, int] = {}
            for item in atomic_results:
                key = str(item.get("result") or "evidence_insufficient")
                result_counts[key] = result_counts.get(key, 0) + 1
            tool_execution = {
                "result": semantic_review.get("result") or "evidence_insufficient",
                "atomicResults": atomic_results,
                "summary": {
                    "atomicCheckCount": len(atomic_results),
                    "resultCounts": result_counts,
                    "executionMode": R19_EXECUTION_MODE,
                    "nodeResultSource": "fixed_aggregator_over_llm_semantic_judgments",
                },
            }
            deterministic_result = str(tool_execution["result"])
        else:
            tool_plan = compile_node_tool_plan(
                pack,
                source_rule_id,
                available_tools={item["name"] for item in runtime_tool_catalog()},
                require_published=(
                    str(review_run.get("reviewMode") or "formal") == "formal"
                    and not bool(review_run.get("advisoryOnly"))
                ),
            )
            fact_snapshot = context.get("businessFacts") if isinstance(context.get("businessFacts"), dict) else {}
            tool_execution = execute_node_tool_plan(
                tool_plan,
                tool_runner=lambda name, arguments: execute_agent_tool(
                    review_run,
                    node_key,
                    name,
                    arguments,
                    context,
                ),
                facts=fact_snapshot,
                tool_arguments=context.get("atomicToolArguments")
                if isinstance(context.get("atomicToolArguments"), dict)
                else {},
                document_version_ids=list(review_run.get("inputDocumentVersionIds") or []),
                evidence_facts=context.get("evidenceFacts") if isinstance(context.get("evidenceFacts"), list) else [],
                evidence_refs=context.get("evidenceLinks") if isinstance(context.get("evidenceLinks"), list) else [],
            )
            deterministic_result = tool_execution.get("result") if tool_plan else "evidence_insufficient"
        result = {
            "id": f"RCHK-{uuid4().hex[:8].upper()}",
            "reviewRunId": review_run["reviewRunId"],
            "ruleCode": rule.get("ruleKey") or rule.get("id") or "generic-review",
            "ruleSetVersion": rule.get("version") or review_run.get("ruleSetVersion"),
            "result": deterministic_result,
            "severity": rule.get("severity") or "medium",
            "message": (
                "R19 LLM 已完成证据约束的逐原子项语义判断，节点结果由固定聚合器生成，待人工确认。"
                if isinstance(semantic_review, dict) and semantic_review.get("atomicJudgments")
                else "固定 atomicCheck Tool 执行完成，待人工确认。"
                if deterministic_result in {"passed", "failed", "not_applicable"}
                else "atomicCheck Tool 执行故障（系统问题，非业务结论），请检查服务状态后重试。"
                if deterministic_result == "execution_error"
                else "形式检查完成，但需要专业人员作实质判断。"
                if deterministic_result == "human_review_required"
                else "固定 atomicCheck Tool 缺少完整事实、证据或规则参数，禁止自动判定符合。"
            ),
            "linkedClauseIds": linked_clause_ids,
            "evidenceRefs": [{"source": "ocr_fields", "count": len(context.get("fields") or [])}],
            "suggestedAction": "human_confirm",
            "atomicCheckResults": tool_execution.get("atomicResults") or [],
            "toolExecutionSummary": tool_execution.get("summary") or {},
            "createdAt": server_time(),
        }
        repo.state["rule_check_results"].append(result)
        context["currentRule"] = rule
        context["ruleResults"] = [result]
        context["atomicToolExecution"] = tool_execution
        if int(review_run.get("nodeId") or 0) == 19:
            verification_tool = {"verificationCount": 0, "status": "skipped_for_r19"}
        else:
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
    project = context.get("project") or repo.require_project(str(review_run.get("projectId") or "")) or {}
    pack = project.get("businessPackSnapshot") or load_business_pack(
        str(review_run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID)
    )
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
    # 只下发本节点规则用得上的工具。全量 111 个占 9740 tokens ≈ 41% 预算，
    # 挂 0 份资料就已经吃掉近一半——节点 24 那次 REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED
    # 就是这么来的。裁剪一律 fail-open：认不出就送全量，见 tool_scope 的说明。
    scoped_tools, tool_scope_meta = scoped_runtime_tool_catalog(
        runtime_tool_catalog(), pack, review_run.get("nodeId")
    )
    context["toolScope"] = tool_scope_meta
    user_payload = {
        "task": "Generate ReviewFindingDraftList JSON only.",
        "auditInputMode": audit_runtime["mode"],
        "auditRuntime": audit_runtime_public_config(mode=audit_runtime["mode"]),
        "availableRuntimeTools": scoped_tools,
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
        # 压掉嵌套工具输出里的证据引用列表再进提示词。原样给会让单个
        # locate_evidence_fragment 结果占掉 39% 预算（见 rule_result_digest）。
        "ruleResults": compact_rule_results(context.get("ruleResults") or []),
        "fixedClausePackage": context.get("clausePackageSnapshot") or {},
        "retrievalTraceIds": [item.get("retrievalTraceId") for item in context.get("retrievalTraces") or []],
        # 检索到的条款正文与 ID。原先只给 traceId，不给条款本身——而输出 schema
        # 要求模型产出 kbRefs: [{retrievalTraceId, clauseIds}]。它手里没有任何
        # clauseId，这个要求根本无法满足：线上 3 条 finding 的 kbRefs 全是空的。
        #
        # retrieve_knowledge 这一步照常跑、照常写 retrieval_traces，产出却只存进
        # context["knowledgeClauses"] 然后无人读取。实测把它清空，提示词只有
        # traceId 那一处变化——等于整步白跑。
        "retrievedClauses": retrieved_clause_digest(context.get("knowledgeClauses")),
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
        # 本次给了模型哪些工具。裁剪会改变它能取到什么证据，也就会改变判定——
        # 日后复盘一个可疑结论时，这是「当时它手里有什么」的唯一记录。
        "toolScope": context.get("toolScope") or {},
    }


def build_review_messages(review_run: dict[str, Any], context: dict[str, Any]) -> list[dict[str, str]]:
    return build_review_prompt_parts(review_run, context)["messages"]


def review_model_budget_policy(review_run: dict[str, Any]) -> dict[str, Any]:
    alias = str(review_run.get("modelAlias") or "review-chat")
    route = next(
        (
            item
            for item in repo.state.get("model_route_versions", [])
            if item.get("modelAlias") == alias and item.get("status") == "production"
        ),
        {},
    )
    configured = route.get("budgetPolicy") if isinstance(route.get("budgetPolicy"), dict) else {}
    return {
        "maxInputTokens": max(1024, int(os.getenv("AICHECK_REVIEW_MAX_INPUT_TOKENS", "24000"))),
        # 走 reasoning_budget 的统一口径，不再自己写死。原值 1600 对推理模型
        # 连推理都装不下：节点 2 实测 completion 1600 / reasoning 1600，
        # 正文一个字没写就被判 LLM_OUTPUT_TRUNCATED。
        "maxOutputTokens": review_max_output_tokens(),
        "maxCostCny": max(
            0.01,
            float(
                os.getenv("AICHECK_REVIEW_MAX_COST_CNY")
                or configured.get("maxCostPerRun")
                or 2.0
            ),
        ),
        "maxAttempts": max(1, int(os.getenv("AICHECK_REVIEW_MAX_ATTEMPTS", "2"))),
    }


def persist_review_model_attempt(attempt: dict[str, Any]) -> None:
    repo.state.setdefault("model_call_attempts", []).insert(0, attempt)
    flush_state_records({"model_call_attempts": [attempt]})


def trim_review_input_to_budget(
    review_run: dict[str, Any],
    context: dict[str, Any],
    budget_policy: dict[str, Any],
) -> tuple[list[dict[str, str]], int]:
    """裁减证据后重建提示词，并把裁减结果留痕。"""
    grounding_input = context.get("groundingInput") or {}
    version_labels = document_version_labels(grounding_input)
    # 证据之外的固定开销（工具目录、规则、模板）不可裁，先量出来给证据留余量
    fixed_overhead = estimate_messages_tokens(
        build_review_prompt_parts(review_run, {**context, "groundingInput": {}})["messages"]
    )
    trimmed, report = trim_evidence_to_budget(
        grounding_input,
        available_tokens=int(budget_policy["maxInputTokens"]) - fixed_overhead,
        version_labels=version_labels,
    )
    if not report.get("truncated"):
        # 裁不动说明超的不是证据（例如固定开销本身就过大）——照旧响亮地失败，
        # 别让它带着一份完整证据继续跑然后在模型侧超时。
        raise IntegrationServiceError(
            "QwenRuntime", "review.chat", reason="REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED"
        )
    if report.get("stillOverBudget") or report.get("nothingLeftToReview"):
        # 全裁光还超，或者一份都没留住——两种都不是「裁减成功」。
        # 审 0 份资料会得到一个基于空证据的结论：护栏会把它降级为待人工确认，
        # 但监检看到的仍是一次「做过了」的审查。这种沉默的空转比失败更贵。
        raise IntegrationServiceError(
            "QwenRuntime", "review.chat", reason="REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED"
        )

    # 证据不全 → 走既有护栏降级为待人工确认、置信度封顶，不许出「满足要求」
    trimmed = dict(trimmed)
    trimmed["groundingStatus"] = "insufficient_evidence"
    trimmed["truncationRequirements"] = truncation_requirements(report)
    context["groundingInput"] = trimmed
    context["evidenceBudget"] = report
    review_run["evidenceBudget"] = repo.clone(report)

    rebuilt = build_review_prompt_parts(review_run, context)["messages"]
    return rebuilt, estimate_messages_tokens(rebuilt)


def document_version_labels(grounding_input: dict[str, Any]) -> dict[str, str]:
    """版本号 → 文件名。裁减清单要给人看文件名，不是一串 ID。"""
    wanted = {str(item) for item in grounding_input.get("documentVersionIds") or [] if item}
    if not wanted:
        return {}
    documents = {str(item.get("id")): item for item in repo.state.get("documents") or []}
    labels: dict[str, str] = {}
    for version in repo.state.get("versions") or []:
        version_id = str(version.get("id") or "")
        if version_id not in wanted:
            continue
        document = documents.get(str(version.get("documentId") or "")) or {}
        name = str(document.get("fileName") or "").strip()
        if name:
            labels[version_id] = name
    return labels


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
    budget_policy = review_model_budget_policy(review_run)
    messages = build_review_messages(review_run, context)
    estimated_input_tokens = estimate_messages_tokens(messages)

    # 超预算时先按整份资料裁减再重建，而不是整次失败。原先一超就报
    # REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED，一份资料都没审——监检既拿不到任何
    # AI 意见，也不知道差多少、该拆掉哪份。
    #
    # 裁减是有代价的，所以三条约束一起上（详见 evidence_budget 模块）：
    # 只裁整份、裁过就降级为待人工确认、裁了什么写进提示词和界面。
    if estimated_input_tokens > budget_policy["maxInputTokens"]:
        messages, estimated_input_tokens = trim_review_input_to_budget(
            review_run, context, budget_policy
        )

    qwen_runtime = qwen_runtime_public_config()
    estimated_cost = model_cost_cny(
        {
            "input_tokens": estimated_input_tokens,
            "output_tokens": budget_policy["maxOutputTokens"],
        }
    )["total"]
    if estimated_input_tokens > budget_policy["maxInputTokens"]:
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason="REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED")
    if estimated_cost > budget_policy["maxCostCny"]:
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason="REVIEW_COST_BUDGET_EXCEEDED")
    logical_call_id = f"review:{review_run['reviewRunId']}:generate_findings"
    previous_attempts = [
        item
        for item in repo.state.get("model_call_attempts", [])
        if item.get("logicalCallId") == logical_call_id
    ]
    attempt_number = len(previous_attempts) + 1
    if attempt_number > budget_policy["maxAttempts"]:
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason="REVIEW_MAX_ATTEMPTS_EXCEEDED")
    attempt = {
        "id": f"MCALL-{uuid4().hex[:12].upper()}",
        "reviewRunId": review_run.get("reviewRunId"),
        "aiRunId": review_run.get("aiRunId"),
        "projectId": review_run.get("projectId"),
        "nodeId": review_run.get("nodeId"),
        "stage": "review_generate_findings",
        "callKind": "review_findings",
        "logicalCallId": logical_call_id,
        "attempt": attempt_number,
        "maxAttempts": budget_policy["maxAttempts"],
        "provider": qwen_runtime.get("provider"),
        "modelAlias": review_run.get("modelAlias"),
        "status": "running",
        "promptHash": stable_hash_payload(messages),
        "usage": {},
        "usageNormalized": {},
        "costNormalized": {},
        "estimatedCostCny": estimated_cost,
        "budget": {
            "scope": "review_run",
            "budgetKey": review_run.get("reviewRunId"),
            "limitCostCny": budget_policy["maxCostCny"],
            "reservedCostCny": estimated_cost,
        },
        "createdAt": server_time(),
        "startedAt": server_time(),
        "updatedAt": server_time(),
    }
    persist_review_model_attempt(attempt)
    reasoning_effort = review_reasoning_effort()
    try:
        response = qwen_runtime_client().chat_sync(
            messages,
            model=str(review_run.get("modelAlias") or "review-chat"),
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=budget_policy["maxOutputTokens"],
            # 给推理设上界。只调大 max_tokens 不收敛——实测推理会膨胀到填满
            # 给它的额度（6000→用满 6000，8000→推理 6570 总输出顶满）。
            **({"reasoning_effort": reasoning_effort} if reasoning_effort else {}),
            timeout=max(30.0, float(os.getenv("AICHECK_QWEN_REVIEW_TIMEOUT_SECONDS", "180"))),
            _raw_capture_context=raw_context_from_record(
                review_run,
                model_call_attempt_id=str(attempt["id"]),
                stage=str(attempt["stage"]),
                turn=1,
            ),
        )
    except IntegrationServiceError as exc:
        attempt.update(
            {
                "status": "failed",
                "failureReason": exc.reason or exc.__class__.__name__,
                "finishedAt": server_time(),
                "updatedAt": server_time(),
            }
        )
        flush_state_records({"model_call_attempts": [attempt]})
        raise
    except Exception as exc:
        attempt.update(
            {
                "status": "failed",
                "failureReason": exc.__class__.__name__,
                "finishedAt": server_time(),
                "updatedAt": server_time(),
            }
        )
        flush_state_records({"model_call_attempts": [attempt]})
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
    raw_usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    normalized_usage = normalize_model_usage(raw_usage)
    normalized_cost = model_cost_cny(raw_usage)
    attempt.update(
        {
            "status": "response_received",
            "provider": response.get("provider") or attempt.get("provider"),
            "model": response.get("model") or review_run.get("modelAlias"),
            "providerRequestId": response.get("id") or response.get("request_id"),
            "responseHash": response_hash,
            "usage": repo.clone(raw_usage),
            "usageNormalized": normalized_usage,
            "costNormalized": normalized_cost,
            "estimatedCostCny": normalized_cost["total"],
            "budget": {
                **attempt["budget"],
                "actualCostCny": normalized_cost["total"],
                "remainingCostCny": max(0.0, budget_policy["maxCostCny"] - normalized_cost["total"]),
            },
            "updatedAt": server_time(),
        }
    )
    flush_state_records({"model_call_attempts": [attempt]})
    prompt_shape = context.get("promptShape") or build_review_prompt_shape(review_run, context)
    finish_reason = (
        ((response.get("choices") or [{}])[0] or {}).get("finish_reason")
        if isinstance(response.get("choices"), list)
        else None
    )
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
        "usage": raw_usage,
        "usageNormalized": normalized_usage,
        "costNormalized": normalized_cost,
        "budget": repo.clone(attempt["budget"]),
        "reasoningProcess": reasoning_process[:3000],
        "resultText": content[:4000],
        "auditInputMode": (context.get("auditRuntime") or audit_runtime_for_run(review_run))["mode"],
        "finishReason": finish_reason,
    }
    review_run["llmConversationId"] = conversation_id
    review_run["llmMetadata"] = repo.clone(llm_metadata)
    if str(finish_reason or "").strip().lower() in {"length", "max_tokens", "token_limit"}:
        attempt.update(
            {
                "status": "invalid_output",
                "failureReason": "LLM_OUTPUT_TRUNCATED",
                "finishReason": finish_reason,
                "finishedAt": server_time(),
                "updatedAt": server_time(),
            }
        )
        flush_state_records({"model_call_attempts": [attempt]})
        # 区分「推理吃光了额度」和「模型真的没话说」——两者处置完全不同：
        # 前者调大 AICHECK_QWEN_REVIEW_MAX_TOKENS 就能解决，后者调多少都没用。
        # 只报 LLM_OUTPUT_TRUNCATED 等于告诉人「截断了」，而人要知道的是「我该改什么」。
        truncation_reason = (
            "LLM_OUTPUT_BUDGET_EXHAUSTED_BY_REASONING"
            # 用 truncation_caused_by_reasoning 而不是 output_budget_exhausted_by_reasoning：
            # 这里已经确定被截断了，finish_reason=length 对两种成因都成立、没有区分力。
            if truncation_caused_by_reasoning(
                raw_usage, int(budget_policy["maxOutputTokens"])
            )
            else "LLM_OUTPUT_TRUNCATED"
        )
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason=truncation_reason)
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
            "usage": raw_usage,
            "usageNormalized": normalized_usage,
            "costNormalized": normalized_cost,
            "modelCallAttemptId": attempt["id"],
        },
    )
    try:
        drafts = normalize_llm_findings(review_run, context, content)
    except IntegrationServiceError as exc:
        attempt.update(
            {
                "status": "invalid_output",
                "failureReason": exc.reason or "LLM_OUTPUT_INVALID",
                "finishReason": finish_reason,
                "finishedAt": server_time(),
                "updatedAt": server_time(),
            }
        )
        flush_state_records({"model_call_attempts": [attempt]})
        raise
    attempt.update(
        {
            "status": "success",
            "finishReason": finish_reason,
            "finishedAt": server_time(),
            "updatedAt": server_time(),
        }
    )
    flush_state_records({"model_call_attempts": [attempt]})
    review_run.setdefault("modelCallAttemptIds", []).append(attempt["id"])
    return drafts, llm_metadata


def normalize_llm_findings(review_run: dict[str, Any], context: dict[str, Any], content: str) -> list[dict[str, Any]]:
    base = build_finding_draft(review_run, context)
    grounding_input = context.get("groundingInput") or {}
    if not content.strip():
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason="LLM_OUTPUT_EMPTY")
    try:
        parsed = json.loads(content)
    except ValueError as exc:
        raise IntegrationServiceError(
            "QwenRuntime",
            "review.chat",
            reason="LLM_OUTPUT_INVALID_JSON",
        ) from exc
    if not isinstance(parsed, dict):
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason="LLM_OUTPUT_INVALID_ENVELOPE")
    raw_findings = parsed.get("findings")
    if not isinstance(raw_findings, list):
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason="LLM_OUTPUT_INVALID_ENVELOPE")
    if not raw_findings:
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason="LLM_OUTPUT_EMPTY_FINDINGS")
    if any(not isinstance(item, dict) for item in raw_findings[:10]):
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason="LLM_OUTPUT_INVALID_FINDING")
    drafts = []
    for item in raw_findings[:10]:
        draft = {**repo.clone(base)}
        draft["id"] = f"FND-DRAFT-{uuid4().hex[:8].upper()}"
        draft["findingType"] = str(item.get("findingType") or item.get("finding_type") or base["findingType"])
        draft["severity"] = str(item.get("severity") or base["severity"])
        draft["title"] = str(item.get("title") or base["title"])[:120]
        draft["description"] = str(item.get("description") or base["description"])[:1200]
        draft["evidenceRefs"] = repo.clone(item.get("evidenceRefs")) if isinstance(item.get("evidenceRefs"), list) else []
        draft["ruleRefs"] = repo.clone(item.get("ruleRefs")) if isinstance(item.get("ruleRefs"), list) else []
        draft["kbRefs"] = repo.clone(item.get("kbRefs")) if isinstance(item.get("kbRefs"), list) else []
        draft["confidence"] = bounded_confidence(item.get("confidence"), default=base["confidence"])
        draft["suggestedAction"] = str(item.get("suggestedAction") or item.get("suggested_action") or "human_confirm")
        draft["groundingStatus"] = str(item.get("groundingStatus") or item.get("grounding_status") or base.get("groundingStatus") or "")
        draft["unsupportedClaims"] = item.get("unsupportedClaims") if isinstance(item.get("unsupportedClaims"), list) else []
        draft["requiresHumanConfirmation"] = True
        draft["llmGenerated"] = True
        drafts.append(draft)
    return apply_grounding_guardrails(drafts, grounding_input)


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


# 置信度原先是四处硬编码常量（0.82 / 0.55 / 0.5 / 0.68），前端却以「置信度 82%」
# 两位精度展示一个从未被计算的数字——比不显示更糟，它让人以为系统在量化把握。
# 现在由证据锚定质量派生：能拿到多少可定位、可追溯的证据，就报多少把握。
PURE_LLM_CONFIDENCE_CEILING = 0.55
GROUNDING_CONFIDENCE_FLOOR = 0.3
GROUNDING_CONFIDENCE_CEILING = 0.95


def derive_grounding_confidence(
    grounding_input: dict[str, Any], audit_mode: str
) -> tuple[float, dict[str, Any]]:
    """按证据锚定质量算置信度，并返回可核对的计算依据。

    分母是本次拿到的证据条数，分子是「可定位、置信度不低、无关键质量告警」的条数。
    纯 LLM 模式没有 OCR/page/bbox 证据，无论算出多少都封顶——这类结论本就只能
    当人工复核提示。
    """
    summary = dict((grounding_input or {}).get("summary") or {})
    evidence_count = int(summary.get("evidenceLinkCount") or 0)
    penalties = {
        "lowConfidenceEvidenceCount": int(summary.get("lowConfidenceEvidenceCount") or 0),
        "missingPositionEvidenceCount": int(summary.get("missingPositionEvidenceCount") or 0),
        "criticalQualityFlagCount": int(summary.get("criticalQualityFlagCount") or 0),
        "blockingIssueCount": int(summary.get("blockingIssueCount") or 0),
    }
    if evidence_count <= 0:
        confidence = GROUNDING_CONFIDENCE_FLOOR
        ratio = 0.0
    else:
        flawed = min(evidence_count, sum(penalties.values()))
        ratio = (evidence_count - flawed) / evidence_count
        confidence = GROUNDING_CONFIDENCE_FLOOR + ratio * (
            GROUNDING_CONFIDENCE_CEILING - GROUNDING_CONFIDENCE_FLOOR
        )
    if str(audit_mode) == "pure_llm":
        confidence = min(confidence, PURE_LLM_CONFIDENCE_CEILING)
    confidence = round(min(max(confidence, GROUNDING_CONFIDENCE_FLOOR), GROUNDING_CONFIDENCE_CEILING), 2)
    return confidence, {
        "method": "grounding_coverage",
        "evidenceCount": evidence_count,
        "usableRatio": round(ratio, 3),
        "penalties": penalties,
        "auditMode": str(audit_mode),
        "pureLlmCeilingApplied": str(audit_mode) == "pure_llm",
    }


def build_finding_draft(review_run: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    evidence = context.get("evidenceLinks") or []
    rule_result = next(iter(context.get("ruleResults") or []), {})
    grounding_input = context.get("groundingInput") or {}
    audit_runtime = context.get("auditRuntime") or audit_runtime_for_run(review_run)
    grounding_status = str(grounding_input.get("groundingStatus") or "insufficient_evidence")
    description = "已基于 OCR 字段、规则检查和知识检索生成审查草稿，需监检员人工确认。"
    source_method = "ocr_llm_review"
    if audit_runtime["mode"] == "pure_llm":
        description = "当前为纯 LLM 审计模式，未加载 OCR/page/bbox 证据；以下建议只能作为人工复核提示，不能作为自动审计结论。"
        source_method = "pure_llm_review"
    if grounding_status != "grounded":
        description = "当前 OCR 证据不足以支撑自动审查结论，需人工核对原件、字段、表格、印章和证据链。"
        if audit_runtime["mode"] == "pure_llm":
            description = "当前为纯 LLM 审计模式，未加载 OCR/page/bbox 证据；以下建议只能作为人工复核提示，不能作为自动审计结论。"
    confidence, confidence_basis = derive_grounding_confidence(grounding_input, audit_runtime["mode"])
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
        # 置信度必须可核对：带上算它的依据，而不是给一个来历不明的数字。
        "confidenceBasis": confidence_basis,
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
        "clausePackageId": review_run.get("clausePackageId"),
        "clausePackageSnapshotHash": review_run.get("clausePackageSnapshotHash"),
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
        prompt_audit = view.get("promptAudit") if isinstance(view.get("promptAudit"), dict) else {}
        view["promptSummary"] = {
            key: prompt_audit.get(key)
            for key in (
                "promptVersion",
                "ruleVersion",
                "messagesHash",
                "promptHash",
                "responseHash",
                "payloadPolicy",
            )
            if prompt_audit.get(key) is not None
        }
        for sensitive_field in (
            "rawPrompt",
            "rawOcrText",
            "prompt",
            "promptAudit",
            "messages",
            "llmMetadata",
            "reasoningProcess",
            "llmResultText",
            "ocrText",
            "inputPayload",
            "outputPayload",
        ):
            view.pop(sensitive_field, None)
    view["revision"] = review_run_revision(review_run)
    view["etag"] = review_run_etag(review_run)
    view["graphSummary"] = summarize_graph(review_run["reviewRunId"])
    view["clausePackageSnapshot"] = review_run_clause_snapshot(
        repo.state,
        str(review_run.get("reviewRunId") or review_run.get("id") or ""),
    )
    return view


def summarize_graph(review_run_id: str) -> dict[str, Any]:
    nodes = graph_nodes_for_review_run(review_run_id)
    counts: dict[str, int] = {}
    for node in nodes:
        status = str(node.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {"total": len(nodes), "statusCounts": counts}


def confirmed_findings_for_human_decision(
    review_run: dict[str, Any],
    decision: str,
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    original_drafts = [repo.clone(item) for item in review_run.get("findingDrafts") or [] if isinstance(item, dict)]
    if decision == "reject":
        return [], None
    if decision == "accept":
        return original_drafts, None
    corrected_output = payload.get("correctedOutput")
    if not isinstance(corrected_output, list) or not corrected_output:
        return [], {"code": "CORRECTED_OUTPUT_REQUIRED"}
    if len(json.dumps(corrected_output, ensure_ascii=False, default=str)) > 100_000:
        return [], {"code": "CORRECTED_OUTPUT_TOTAL_TOO_LARGE"}
    if len(corrected_output) > len(original_drafts):
        return [], {"code": "CORRECTED_OUTPUT_TOO_MANY_FINDINGS"}
    originals_by_id = {str(item.get("id") or ""): item for item in original_drafts if item.get("id")}
    confirmed: list[dict[str, Any]] = []
    editable_fields = {
        "findingType",
        "severity",
        "title",
        "description",
        "evidenceRefs",
        "ruleRefs",
        "kbRefs",
        "confidence",
        "suggestedAction",
        "groundingStatus",
        "unsupportedClaims",
    }
    for index, correction in enumerate(corrected_output):
        if not isinstance(correction, dict):
            return [], {"code": "CORRECTED_OUTPUT_ITEM_NOT_OBJECT", "index": index}
        source_draft_id = str(correction.get("sourceDraftId") or correction.get("id") or "")
        original = originals_by_id.get(source_draft_id) if source_draft_id else None
        if source_draft_id and original is None:
            return [], {"code": "CORRECTED_OUTPUT_SOURCE_NOT_FOUND", "index": index}
        if original is None and index < len(original_drafts):
            original = original_drafts[index]
        if original is None:
            return [], {"code": "CORRECTED_OUTPUT_SOURCE_NOT_FOUND", "index": index}
        corrected = repo.clone(original)
        for field in editable_fields:
            if field in correction:
                corrected[field] = repo.clone(correction[field])
        corrected["id"] = original.get("id") or f"FND-DRAFT-{uuid4().hex[:8].upper()}"
        corrected["reviewRunId"] = review_run.get("reviewRunId")
        corrected["findingType"] = str(corrected.get("findingType") or "ai_review_suggestion")
        corrected["severity"] = str(corrected.get("severity") or "medium")
        corrected["title"] = str(corrected.get("title") or "人工修正后的审查发现")
        corrected["description"] = str(corrected.get("description") or "")
        corrected["evidenceRefs"] = corrected.get("evidenceRefs") if isinstance(corrected.get("evidenceRefs"), list) else []
        corrected["ruleRefs"] = corrected.get("ruleRefs") if isinstance(corrected.get("ruleRefs"), list) else []
        corrected["kbRefs"] = corrected.get("kbRefs") if isinstance(corrected.get("kbRefs"), list) else []
        corrected["confidence"] = bounded_confidence(corrected.get("confidence"), default=0.5)
        corrected["suggestedAction"] = str(corrected.get("suggestedAction") or "human_confirm")
        corrected["groundingStatus"] = str(corrected.get("groundingStatus") or "insufficient_evidence")
        corrected["unsupportedClaims"] = (
            corrected.get("unsupportedClaims") if isinstance(corrected.get("unsupportedClaims"), list) else []
        )
        corrected["requiresHumanConfirmation"] = True
        if len(corrected["title"]) > 200 or len(corrected["description"]) > 6000:
            return [], {"code": "CORRECTED_OUTPUT_TEXT_TOO_LONG", "index": index}
        if any(len(corrected.get(field) or []) > 50 for field in ("evidenceRefs", "ruleRefs", "kbRefs")):
            return [], {"code": "CORRECTED_OUTPUT_TOO_MANY_REFERENCES", "index": index}

        # An edited claim must never inherit previously validated references without
        # re-grounding. Re-run every evidence/rule/KB gate even when the user keeps
        # the original reference arrays unchanged.
        ai_run = repo.find_one("ai_runs", str(review_run.get("aiRunId") or "")) or {}
        evidence_links = review_run.get("evidenceLinks") or ai_run.get("evidenceLinks") or [
            item
            for item in repo.state.get("node_evidence_links", [])
            if str(item.get("projectId") or "") == str(review_run.get("projectId") or "")
            and int(item.get("nodeId") or 0) == int(review_run.get("nodeId") or 0)
        ]
        evidence_validation = validate_review_evidence_refs(
            [corrected],
            evidence_links,
            audit_runtime=audit_runtime_for_run(review_run),
        )
        if not evidence_validation.get("passed"):
            return [], {
                "code": "CORRECTED_OUTPUT_EVIDENCE_REFS_INVALID",
                "index": index,
                "validation": evidence_validation,
            }
        reference_validation = validate_review_references(
            [corrected],
            [
                item
                for item in repo.state.get("rule_check_results", [])
                if item.get("reviewRunId") == review_run.get("reviewRunId")
            ],
            [
                item
                for item in repo.state.get("retrieval_traces", [])
                if item.get("reviewRunId") == review_run.get("reviewRunId")
            ],
        )
        if not reference_validation.get("passed"):
            return [], {
                "code": "CORRECTED_OUTPUT_REFERENCES_INVALID",
                "index": index,
                "validation": reference_validation,
            }
        confirmed.append(corrected)
    validation = validate_review_schema(confirmed)
    if not validation.get("passed"):
        return [], {"code": "CORRECTED_OUTPUT_SCHEMA_INVALID", "validation": validation}
    return confirmed, None


def human_decision_for_review_run(
    review_run_id: str,
    decision: str,
    payload: dict[str, Any],
    *,
    commit: bool = True,
) -> dict[str, Any]:
    ensure_review_state()
    review_run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if not review_run:
        return {"status": "missing", "reviewRunId": review_run_id}
    allowed = {"accept", "edit", "reject"}
    if decision not in allowed:
        return {"status": "invalid_decision", "allowed": sorted(allowed)}
    comment = str(payload.get("comment") or payload.get("reason") or "")
    if len(comment) > 2000:
        return {
            "status": "invalid_input",
            "reviewRunId": review_run_id,
            "error": {"code": "HUMAN_DECISION_COMMENT_TOO_LONG", "maxLength": 2000},
        }
    if review_run.get("status") != "waiting_human_review":
        return {
            "status": "invalid_state",
            "reviewRunId": review_run_id,
            "currentStatus": review_run.get("status"),
            "requiredStatus": "waiting_human_review",
        }
    confirmed_findings, correction_error = confirmed_findings_for_human_decision(review_run, decision, payload)
    if correction_error:
        return {
            "status": "invalid_corrected_output",
            "reviewRunId": review_run_id,
            "error": correction_error,
        }
    status_map = {"accept": "accepted_by_human", "edit": "edited_by_human", "reject": "rejected_by_human"}
    if not commit:
        return {
            "status": "validated",
            "nextStatus": status_map[decision],
            "reviewRun": review_run,
            "confirmedFindings": confirmed_findings,
        }
    review_run["status"] = status_map[decision]
    review_run["humanDecision"] = {
        "decision": decision,
        "comment": comment,
        "correctedOutput": payload.get("correctedOutput"),
        "decidedAt": server_time(),
    }
    bump_review_run_revision(review_run)
    append_review_event(
        review_run_id,
        event_type="human_decision.submitted",
        title="人工确认已提交",
        status=review_run["status"],
        details=review_run["humanDecision"],
    )
    feedback = record_human_feedback_for_review_run(review_run, decision, payload)
    if decision in {"accept", "edit"}:
        persist_confirmed_findings(
            review_run,
            payload,
            confirmed_findings=confirmed_findings,
            human_edited=decision == "edit",
        )
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


def persist_confirmed_findings(
    review_run: dict[str, Any],
    payload: dict[str, Any],
    *,
    confirmed_findings: list[dict[str, Any]],
    human_edited: bool,
) -> None:
    original_output_hash = stable_hash_payload(review_run.get("findingDrafts") or [])
    corrected_output_hash = stable_hash_payload(confirmed_findings) if human_edited else None
    for draft in confirmed_findings:
        source_draft_id = draft.get("id")
        finding_id = f"FND-{uuid4().hex[:8].upper()}"
        finding = {
            **repo.clone(draft),
            "id": finding_id,
            "sourceDraftId": source_draft_id,
            "source": "human_edited_ai" if human_edited else "ai",
            "humanEdited": human_edited,
            "originalAiOutputHash": original_output_hash,
            "correctedOutputHash": corrected_output_hash,
            "status": "accepted",
            "humanStatus": review_run["status"],
            "humanComment": payload.get("comment") or payload.get("reason"),
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
    tenant_id = tenant_id_for_record(parent)
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
            "workflowId": review_workflow_id(tenant_id, child_id),
            "temporalRunId": None,
            "startedAt": None,
            "finishedAt": None,
            "createdAt": now,
            "updatedAt": now,
            "replayReason": reason,
            "outputHash": stable_hash_payload(parent.get("findingDrafts") or []),
            "findingDrafts": [],
            "humanDecision": None,
            "revision": 1,
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
