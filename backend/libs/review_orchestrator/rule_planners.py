"""按规则编号组织的审查规划器。

R12（人工核验）和 R19（语义审查）各自是一整套独立的规划逻辑，与调度
（run_step）正交——它们留在 execution.py 里只是让那个文件更难读，
拆出来两边都清楚。纯搬移，逻辑未改。
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



from ._shared import (
    ALLOWED_AGENT_TOOLS,
    REVIEW_STATE_COLLECTIONS,
    append_review_event,
    append_tool_call,
    ensure_review_state,
    qwen_runtime_client,
    review_llm_execution_mode,
    stable_hash_payload,
)


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
