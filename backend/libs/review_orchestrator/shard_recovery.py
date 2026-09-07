"""P8 H4：信封修复与分片级升级重试。

2026-09-06 六模型实测：qwen-plus 在长分片上 9 片里 6 片返回的 JSON 没有 findings 数组
（LLM_OUTPUT_INVALID_ENVELOPE），节点审查对此的处理是整次 review_incomplete——
等于该节点没有 AI 审查。这里在"分片失败"与"整次失败"之间加两级：

1. 信封修复：同一模型、一次短请求——把它自己的输出发回去，只要求输出 {"findings":[...]}，
   max_tokens 4,000。不重跑整个提示词，便宜且往往就能修好。
2. 分片升级：仍失败则该分片换升级模型（AICHECK_LLM_MODEL_REVIEW_ESCALATION，默认 qwen3.8-max）
   重跑一次。
3. 两次都失败才把分片标 failed；失败分片由 shard_execution 记进 failedEvidenceShardIds，
   其余分片照常完成（部分覆盖），不再让整次审查 review_incomplete。

每次修复/升级都记 model_call_attempts（stage=envelope_repair / shard_escalation），
基准脚本据此统计升级率——某模型升级率 >30% 就说明它不适合这个角色。
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from libs.contracts.responses import server_time
from libs.db.repository import flush_state_records, repo
from libs.integrations.errors import IntegrationServiceError
from libs.model_usage import model_cost_cny, normalize_model_usage
from libs.qwen_runtime import QwenRuntimeClient
from libs.review_orchestrator._shared import qwen_runtime_client

LOGGER = logging.getLogger(__name__)

REPAIRABLE_REASONS = {"LLM_OUTPUT_INVALID_ENVELOPE", "LLM_OUTPUT_INVALID_JSON", "LLM_OUTPUT_INVALID_FINDING"}
# 升级只针对"模型没按契约输出"这一类；供应商故障、超预算、截断另有各自的处置。
ESCALATABLE_REASONS = REPAIRABLE_REASONS | {"LLM_OUTPUT_EMPTY", "LLM_OUTPUT_EMPTY_FINDINGS"}
REPAIR_MAX_TOKENS = 4000
DEFAULT_ESCALATION_MODEL = "qwen3.8-max"

_REPAIR_SYSTEM_PROMPT = (
    "你上一次的输出没有满足输出契约。下面是你自己的原始输出。"
    "请只输出一个 JSON 对象，形如 {\"findings\": [...]}，findings 数组里每个元素保留原有字段"
    "（findingType, severity, title, description, evidenceRefs, ruleRefs, kbRefs, confidence, "
    "suggestedAction, groundingStatus, unsupportedClaims）。不要解释，不要 Markdown 代码块，"
    "不要新增原始输出里没有的事实。"
)


def escalation_model() -> str:
    return str(os.getenv("AICHECK_LLM_MODEL_REVIEW_ESCALATION") or DEFAULT_ESCALATION_MODEL).strip()


def _failure_reason(exc: BaseException) -> str:
    if isinstance(exc, IntegrationServiceError) and exc.reason:
        return str(exc.reason)
    return exc.__class__.__name__


def _record_attempt(review_run: dict[str, Any], context: dict[str, Any], *, stage: str, model: str) -> dict[str, Any]:
    attempt = {
        "id": f"MCALL-{uuid4().hex[:12].upper()}",
        "reviewRunId": review_run.get("reviewRunId"),
        "aiRunId": review_run.get("aiRunId"),
        "projectId": review_run.get("projectId"),
        "nodeId": review_run.get("nodeId"),
        "evidenceShardId": str(context.get("evidenceShardId") or ""),
        "stage": stage,
        "callKind": "review_findings_repair",
        "logicalCallId": f"review:{review_run.get('reviewRunId')}:{stage}:{context.get('evidenceShardId') or 'node'}",
        "attempt": 1,
        "maxAttempts": 1,
        "modelAlias": model,
        "status": "running",
        "usage": {},
        "usageNormalized": {},
        "costNormalized": {},
        "createdAt": server_time(),
        "startedAt": server_time(),
        "updatedAt": server_time(),
    }
    repo.state.setdefault("model_call_attempts", []).insert(0, attempt)
    flush_state_records({"model_call_attempts": [attempt]})
    return attempt


def _finish_attempt(attempt: dict[str, Any], *, status: str, response: dict[str, Any] | None = None, failure: str | None = None) -> None:
    if response:
        raw_usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        attempt.update(
            {
                "model": response.get("model") or attempt.get("modelAlias"),
                "providerRequestId": response.get("id") or response.get("request_id"),
                "usage": repo.clone(raw_usage),
                "usageNormalized": normalize_model_usage(raw_usage),
                "costNormalized": model_cost_cny(raw_usage, model=str(response.get("model") or "")),
            }
        )
    attempt.update(
        {
            "status": status,
            "failureReason": failure,
            "finishedAt": server_time(),
            "updatedAt": server_time(),
        }
    )
    flush_state_records({"model_call_attempts": [attempt]})


def repair_envelope(
    review_run: dict[str, Any],
    context: dict[str, Any],
    raw_output: str,
    *,
    normalize: Callable[[dict[str, Any], dict[str, Any], str], list[dict[str, Any]]],
) -> list[dict[str, Any]] | None:
    """同一模型的一次短修复请求。修好返回草稿，修不好返回 None（不抛）。"""
    if not str(raw_output or "").strip():
        return None
    model = str(review_run.get("modelAlias") or "review-chat")
    attempt = _record_attempt(review_run, context, stage="envelope_repair", model=model)
    messages = [
        {"role": "system", "content": _REPAIR_SYSTEM_PROMPT},
        {"role": "user", "content": str(raw_output)[:60000]},
    ]
    try:
        response = qwen_runtime_client().chat_sync(
            messages,
            model=model,
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=REPAIR_MAX_TOKENS,
            timeout=max(30.0, float(os.getenv("AICHECK_QWEN_REVIEW_TIMEOUT_SECONDS", "180"))),
        )
    except Exception as exc:  # noqa: BLE001 —— 修复本身失败不致命：任何异常都继续走升级
        LOGGER.warning("envelope repair call failed: %r", exc)
        _finish_attempt(attempt, status="failed", failure=_failure_reason(exc))
        return None
    content = QwenRuntimeClient.first_message_text(response)
    try:
        drafts = normalize(review_run, context, content)
    except IntegrationServiceError as exc:
        _finish_attempt(attempt, status="invalid_output", response=response, failure=_failure_reason(exc))
        return None
    _finish_attempt(attempt, status="success", response=response)
    review_run.setdefault("modelCallAttemptIds", []).append(attempt["id"])
    metadata = review_run.get("llmMetadata") if isinstance(review_run.get("llmMetadata"), dict) else {}
    metadata.update({"envelopeRepaired": True, "repairAttemptId": attempt["id"], "resultText": content})
    review_run["llmMetadata"] = metadata
    return drafts


def generate_with_recovery(
    review_run: dict[str, Any],
    context: dict[str, Any],
    *,
    generate_once: Callable[[dict[str, Any], dict[str, Any]], tuple[list[dict[str, Any]], dict[str, Any]]],
    normalize: Callable[[dict[str, Any], dict[str, Any], str], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """generate_once 的三级包装：原样 → 信封修复 → 升级模型重跑 → 抛出最初的错误。"""
    try:
        return generate_once(review_run, context)
    except IntegrationServiceError as first_error:
        reason = _failure_reason(first_error)
        if reason not in ESCALATABLE_REASONS:
            raise
        recovery: dict[str, Any] = {"firstFailure": reason}
        if reason in REPAIRABLE_REASONS:
            raw_output = str((review_run.get("llmMetadata") or {}).get("resultText") or "")
            drafts = repair_envelope(review_run, context, raw_output, normalize=normalize)
            if drafts is not None:
                metadata = dict(review_run.get("llmMetadata") or {})
                metadata["recovery"] = {**recovery, "recoveredBy": "envelope_repair"}
                review_run["llmMetadata"] = metadata
                return drafts, metadata
            recovery["envelopeRepair"] = "failed"
        model = escalation_model()
        if not model or model == str(review_run.get("modelAlias") or ""):
            raise
        escalated_context = dict(context)
        escalated_context["modelOverride"] = model
        escalated_context["modelAttemptStage"] = "shard_escalation"
        try:
            drafts, metadata = generate_once(review_run, escalated_context)
        except IntegrationServiceError as second_error:
            LOGGER.warning(
                "shard escalation to %s failed after %s: %s",
                model,
                reason,
                _failure_reason(second_error),
            )
            raise first_error from second_error
        metadata = dict(metadata)
        metadata["recovery"] = {**recovery, "recoveredBy": "shard_escalation", "escalationModel": model}
        review_run["llmMetadata"] = repo.clone(metadata)
        return drafts, metadata


def raw_output_looks_like_json_object(text: str) -> bool:
    try:
        return isinstance(json.loads(text), dict)
    except ValueError:
        return False
