from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from libs.contracts.responses import SERVER_TZ, server_time

PHASE_ORDER = (
    "preparing_snapshot",
    "building_prompt",
    "queued",
    "model_running",
    "validating_output",
    "persisting_results",
    "waiting_human_review",
)
TERMINAL_PHASES = {"waiting_human_review", "failed", "partial_failure"}
PROJECT_ANALYSIS_STALL_TIMEOUT = timedelta(minutes=30)


class ProjectAnalysisPhaseError(RuntimeError):
    pass


def _stable_id(prefix: str, value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return f"{prefix}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16].upper()}"


def append_project_analysis_event(
    state: dict[str, Any],
    run: dict[str, Any],
    *,
    phase: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    events = state.setdefault("project_analysis_events", [])
    event = {
        "id": _stable_id(
            "PAEVENT",
            {
                "runId": run.get("projectAnalysisRunId"),
                "sequence": len(
                    [
                        row
                        for row in events
                        if row.get("projectAnalysisRunId")
                        == run.get("projectAnalysisRunId")
                    ]
                )
                + 1,
            },
        ),
        "projectAnalysisRunId": run.get("projectAnalysisRunId"),
        "tenantId": run.get("tenantId"),
        "projectId": run.get("projectId"),
        "phase": phase,
        "details": deepcopy(details or {}),
        "createdAt": server_time(),
    }
    events.append(event)
    return event


def create_project_analysis_run(
    state: dict[str, Any],
    *,
    tenant_id: str,
    project_id: str,
    snapshot: dict[str, Any],
    preview: dict[str, Any],
    actor_id: str,
) -> dict[str, Any]:
    idempotency_key = _stable_id(
        "PAKEY",
        {
            "tenantId": tenant_id,
            "projectId": project_id,
            "snapshotHash": snapshot.get("snapshotHash"),
            "promptVersion": snapshot.get("promptVersion"),
            "modelRouteVersion": preview.get("modelRouteVersion"),
        },
    )
    rows = state.setdefault("project_analysis_runs", [])
    existing = next(
        (row for row in rows if row.get("idempotencyKey") == idempotency_key),
        None,
    )
    if existing:
        return existing
    run_id = idempotency_key.replace("PAKEY-", "PARUN-", 1)
    now = server_time()
    run = {
        "id": run_id,
        "projectAnalysisRunId": run_id,
        "projectAnalysisSnapshotId": snapshot.get("projectAnalysisSnapshotId"),
        "snapshotHash": snapshot.get("snapshotHash"),
        "idempotencyKey": idempotency_key,
        "tenantId": tenant_id,
        "projectId": project_id,
        "actorId": actor_id,
        "status": "preparing_snapshot",
        "phase": "preparing_snapshot",
        "includedNodeCount": int(preview.get("includedNodeCount") or 0),
        "uniqueFileCount": int(preview.get("uniqueFileCount") or 0),
        "fileReferenceCount": int(preview.get("fileReferenceCount") or 0),
        "estimatedInputTokens": int(preview.get("estimatedInputTokens") or 0),
        "maxContextTokens": int(preview.get("maxContextTokens") or 0),
        "reservedOutputTokens": int(preview.get("reservedOutputTokens") or 0),
        "modelAlias": preview.get("modelAlias"),
        "modelRouteVersion": preview.get("modelRouteVersion"),
        "preparedNodeCount": 0,
        "loadedFileCount": 0,
        "totalFindingCount": 0,
        "validatedFindingCount": 0,
        "persistedNodeCount": 0,
        "createdAt": now,
        "updatedAt": now,
        "revision": 1,
    }
    rows.insert(0, run)
    append_project_analysis_event(state, run, phase="preparing_snapshot")
    return run


def advance_project_analysis_phase(
    state: dict[str, Any],
    run: dict[str, Any],
    phase: str,
    **updates: Any,
) -> dict[str, Any]:
    current = str(run.get("phase") or "preparing_snapshot")
    if current in TERMINAL_PHASES:
        raise ProjectAnalysisPhaseError("terminal project analysis run is immutable")
    if phase not in {*PHASE_ORDER, "failed", "partial_failure"}:
        raise ProjectAnalysisPhaseError("unsupported project analysis phase")
    if phase in PHASE_ORDER and PHASE_ORDER.index(phase) != PHASE_ORDER.index(current) + 1:
        raise ProjectAnalysisPhaseError(f"illegal phase transition: {current} -> {phase}")
    run.update(deepcopy(updates))
    run["phase"] = phase
    run["status"] = phase
    if updates.get("heartbeat") or phase == "model_running":
        run["lastHeartbeatAt"] = server_time()
    if phase in TERMINAL_PHASES:
        run["finishedAt"] = server_time()
    run["updatedAt"] = server_time()
    run["revision"] = int(run.get("revision") or 0) + 1
    append_project_analysis_event(state, run, phase=phase, details=updates)
    return run


def project_analysis_status_view(run: dict[str, Any]) -> dict[str, Any]:
    phase = str(run.get("phase") or "preparing_snapshot")
    view = {
        "projectAnalysisRunId": run.get("projectAnalysisRunId"),
        "projectId": run.get("projectId"),
        "status": run.get("status"),
        "phase": phase,
        "includedNodeCount": int(run.get("includedNodeCount") or 0),
        "uniqueFileCount": int(run.get("uniqueFileCount") or 0),
        "fileReferenceCount": int(run.get("fileReferenceCount") or 0),
        "estimatedInputTokens": int(run.get("estimatedInputTokens") or 0),
        "preparedNodeCount": int(run.get("preparedNodeCount") or 0),
        "loadedFileCount": int(run.get("loadedFileCount") or 0),
        "totalFindingCount": int(run.get("totalFindingCount") or 0),
        "validatedFindingCount": int(run.get("validatedFindingCount") or 0),
        "persistedNodeCount": int(run.get("persistedNodeCount") or 0),
        "queueTaskId": run.get("queueTaskId"),
        "lastHeartbeatAt": run.get("lastHeartbeatAt"),
        "errorCode": run.get("errorCode"),
        "errorMessage": run.get("errorMessage"),
        "failedFromPhase": run.get("failedFromPhase"),
        "statusReconciledFrom": run.get("statusReconciledFrom"),
        "createdAt": run.get("createdAt"),
        "updatedAt": run.get("updatedAt"),
        "finishedAt": run.get("finishedAt"),
    }
    activity_times: list[datetime] = []
    for value in (
        run.get("lastHeartbeatAt"),
        run.get("updatedAt"),
        run.get("createdAt"),
    ):
        try:
            activity_times.append(
                datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=SERVER_TZ
                )
            )
        except ValueError:
            continue
    last_activity_at = max(activity_times, default=None)
    if (
        phase not in TERMINAL_PHASES
        and last_activity_at is not None
        and datetime.now(SERVER_TZ) - last_activity_at > PROJECT_ANALYSIS_STALL_TIMEOUT
    ):
        view.update(
            {
                "status": "failed",
                "phase": "failed",
                "statusReconciledFrom": phase,
                "errorCode": "PROJECT_ANALYSIS_RUN_STALLED",
                "errorMessage": (
                    "本次工程 AI 分析长时间没有进展，"
                    "未形成可展示结果；请重新发起分析。"
                ),
                "progressMode": "determinate",
                "percent": 0,
            }
        )
        return view
    if phase == "model_running":
        view["progressMode"] = "indeterminate"
    else:
        view["progressMode"] = "determinate"
        view["percent"] = 100 if phase == "waiting_human_review" else 0
    return view


def project_analysis_run_view(run: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(run)
