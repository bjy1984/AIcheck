from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from typing import Any
from uuid import uuid4

from libs.contracts.responses import server_time
from libs.integrations.errors import IntegrationServiceError
from libs.model_usage import model_cost_cny, normalize_model_usage
from libs.project_analysis.domain import advance_project_analysis_phase
from libs.project_analysis.prompt import build_project_analysis_request
from libs.qwen_runtime import QwenRuntimeClient


def project_analysis_model_timeout_seconds() -> float:
    try:
        configured = float(os.getenv("AICHECK_PROJECT_ANALYSIS_MODEL_TIMEOUT_SECONDS", "600"))
    except ValueError:
        configured = 600.0
    return max(60.0, min(configured, 3600.0))


def project_analysis_max_output_tokens(run: dict[str, Any]) -> int:
    reserved = max(1, int(run.get("reservedOutputTokens") or 24000))
    try:
        configured = int(os.getenv("AICHECK_PROJECT_ANALYSIS_MAX_OUTPUT_TOKENS", "48000"))
    except ValueError:
        configured = 48000
    desired = max(reserved, min(configured, 65536))
    max_context = int(run.get("maxContextTokens") or 0)
    estimated_input = int(run.get("estimatedInputTokens") or 0)
    available = max_context - estimated_input if max_context else reserved
    return max(1, min(desired, max(available, reserved)))


def _discard_stream_delta(_channel: str, _delta: str) -> None:
    return None


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def execute_project_analysis_model(state: dict[str, Any], run_id: str, *, client) -> dict[str, Any]:
    run = next(
        (
            row
            for row in state.get("project_analysis_runs") or []
            if row.get("projectAnalysisRunId") == run_id
        ),
        None,
    )
    if not run:
        raise KeyError("PROJECT_ANALYSIS_RUN_NOT_FOUND")
    if run.get("modelAttemptId") and str(run.get("phase") or "") != "queued":
        return run
    snapshot = next(
        (
            row
            for row in state.get("project_analysis_snapshots") or []
            if row.get("projectAnalysisSnapshotId") == run.get("projectAnalysisSnapshotId")
        ),
        None,
    )
    if not snapshot:
        raise KeyError("PROJECT_ANALYSIS_SNAPSHOT_NOT_FOUND")
    request = deepcopy(snapshot.get("request")) or build_project_analysis_request(
        state,
        snapshot,
        model_alias=str(run.get("modelAlias") or "project-review-large"),
    )
    advance_project_analysis_phase(state, run, "model_running", heartbeat=True)
    attempt = {
        "id": f"MCALL-PROJECT-{uuid4().hex[:12].upper()}",
        "projectAnalysisRunId": run_id,
        "tenantId": run.get("tenantId"),
        "projectId": run.get("projectId"),
        "stage": "project_analysis_model",
        "callKind": "project_analysis",
        "modelAlias": run.get("modelAlias") or "project-review-large",
        "status": "running",
        "promptHash": _stable_hash(request["messages"]),
        "usage": {},
        "usageNormalized": {},
        "costNormalized": {},
        "createdAt": server_time(),
        "startedAt": server_time(),
        "updatedAt": server_time(),
    }
    state.setdefault("model_call_attempts", []).insert(0, attempt)
    try:
        response = client.chat_sync(
            request["messages"],
            model=str(request["model"]),
            temperature=float(request["temperature"]),
            response_format=request["response_format"],
            max_tokens=project_analysis_max_output_tokens(run),
            timeout=project_analysis_model_timeout_seconds(),
            stream_handler=_discard_stream_delta,
        )
        choice = (response.get("choices") or [{}])[0]
        if str(choice.get("finish_reason") or "").lower() in {
            "length",
            "max_tokens",
            "token_limit",
        }:
            raise IntegrationServiceError(
                "QwenRuntime", "project.analysis", reason="LLM_OUTPUT_TRUNCATED"
            )
        content = QwenRuntimeClient.first_message_text(response)
        if not content.strip():
            raise IntegrationServiceError(
                "QwenRuntime", "project.analysis", reason="LLM_OUTPUT_EMPTY"
            )
    except Exception as exc:
        attempt.update(
            {
                "status": "failed",
                "failureReason": getattr(exc, "reason", None) or exc.__class__.__name__,
                "finishedAt": server_time(),
                "updatedAt": server_time(),
            }
        )
        run.update(
            {
                "phase": "failed",
                "status": "failed",
                "errorCode": attempt["failureReason"],
                "errorMessage": str(exc),
                "finishedAt": server_time(),
                "updatedAt": server_time(),
            }
        )
        raise
    raw_usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    attempt.update(
        {
            "status": "success",
            "providerRequestId": response.get("id"),
            "model": response.get("model") or request["model"],
            "responseHash": _stable_hash(response),
            "usage": raw_usage,
            "usageNormalized": normalize_model_usage(raw_usage),
            "costNormalized": model_cost_cny(raw_usage),
            "finishedAt": server_time(),
            "updatedAt": server_time(),
        }
    )
    run.update(
        {
            "modelAttemptId": attempt["id"],
            "promptHash": attempt["promptHash"],
            "responseHash": attempt["responseHash"],
            "rawModelOutput": content,
            "actualUsage": attempt["usageNormalized"],
            "actualCost": attempt["costNormalized"],
        }
    )
    advance_project_analysis_phase(state, run, "validating_output")
    return run
