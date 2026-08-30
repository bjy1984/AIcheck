"""审查编排的共享底座：状态集合、工具白名单与几个到处都要用的小helper。

从 execution.py 拆出来，不是为了「整理」，而是为了让规则规划器
（rule_planners.py）能独立成模块——它们要用这几个 helper，而 helper
留在 execution.py 里就会形成循环导入。

execution.py 仍然 re-export 这里的名字：ALLOWED_AGENT_TOOLS 等被
__init__.py 和测试按 `from ...execution import` 引用，路径不能断。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
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
from libs.review_evidence import bind_evidence_package_to_review_run, review_run_evidence_lineage
from libs.review_grounding import (
    apply_grounding_guardrails,
    build_grounded_review_input,
    canonical_grounding_metadata,
    clause_formal_evidence_eligible,
    grounding_prompt_block,
    is_canonical_clause,
    merge_canonical_grounding_metadata,
)
from libs.review_orchestrator import shard_execution
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




REVIEW_STATE_COLLECTIONS = (
    "review_runs", "evidence_snapshots", "evidence_manifests", "evidence_shards", "node_finding_aggregates",
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


def qwen_runtime_client() -> QwenRuntimeClient:
    return build_qwen_runtime_client(LiteLLMClient)


def ensure_review_state() -> None:
    for collection in REVIEW_STATE_COLLECTIONS:
        repo.state.setdefault(collection, [])


def stable_hash_payload(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


def review_llm_execution_mode() -> str:
    configured = os.getenv("AICHECK_REVIEW_LLM_EXECUTION", "").strip().lower()
    if configured:
        return configured
    if production_mode_enabled() or os.getenv("AICHECK_REVIEW_ORCHESTRATION", "").strip().lower() == "temporal":
        return "litellm"
    return "deterministic"


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
