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
            # 实际模型也算运行身份：路由版本不随模型切换而变（2026.08 下先后打过
            # deepseek-v4-pro 与通义），只按路由版本复用会让换模型对资料没变的
            # 项目完全不生效——点按钮拿回的仍是旧模型那次结果。
            "modelName": preview.get("modelName"),
        },
    )
    rows = state.setdefault("project_analysis_runs", [])
    same_key_runs = [row for row in rows if row.get("idempotencyKey") == idempotency_key]
    # failed/partial_failure 的历史运行留档但不复用：run id 由快照哈希决定，
    # 若失败也复用，同一份资料的一键分析失败一次就永远无法重试（实测：模型名
    # 配错 400 之后，再点按钮只会拿回同一个 failed run）。partial_failure 在
    # 分批语义下同样必须可重试——新运行会跳过已产出结果的节点，只补失败批。
    existing = next(
        (
            row
            for row in same_key_runs
            if str(row.get("phase") or "") not in {"failed", "partial_failure"}
        ),
        None,
    )
    if existing:
        return existing
    run_id = idempotency_key.replace("PAKEY-", "PARUN-", 1)
    if same_key_runs:
        run_id = f"{run_id}-R{len(same_key_runs) + 1}"
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
        "batchPlan": deepcopy(preview.get("batchPlan") or []),
        "batchCount": int(preview.get("batchCount") or 1),
        "currentBatchIndex": 0,
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
        "batchCount": int(run.get("batchCount") or 1),
        "currentBatchIndex": int(run.get("currentBatchIndex") or 0),
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
    last_activity_at = project_analysis_last_activity_at(run)
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


def project_analysis_last_activity_at(run: dict[str, Any]) -> datetime | None:
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
    return max(activity_times, default=None)


def reap_stalled_project_analysis_runs(
    state: dict[str, Any],
    *,
    now: datetime | None = None,
    stall_timeout: timedelta | None = None,
    model_running_timeout: timedelta | None = None,
    project_id: str | None = None,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    """把超时无进展的非终态运行落 failed 终态（改库，不是改显示）。

    status 视图的 STALLED 判定只骗显示不改库，而**非终态 run 会被幂等复用**：
    worker 猝死留下的僵尸 run 让同一份资料永远发不起新分析。收敛器与视图
    同口径（同阈值、同活动时间取法），把库也落掉，failed 不被复用，用户可重试。

    model_running 单独给阈值：模型调用最长可配到 3600 秒且期间没有心跳，
    统一 30 分钟阈值会误杀合法长调用——调用方应传入「模型超时 + 余量」。
    """
    reap_at = now or datetime.now(SERVER_TZ)
    base_timeout = stall_timeout or PROJECT_ANALYSIS_STALL_TIMEOUT
    reaped: list[dict[str, Any]] = []
    for run in state.get("project_analysis_runs") or []:
        if project_id is not None and str(run.get("projectId") or "") != project_id:
            continue
        if tenant_id is not None and str(run.get("tenantId") or "") != tenant_id:
            continue
        phase = str(run.get("phase") or "")
        if phase in TERMINAL_PHASES:
            continue
        timeout = base_timeout
        if phase == "model_running" and model_running_timeout is not None:
            timeout = max(base_timeout, model_running_timeout)
        last_activity_at = project_analysis_last_activity_at(run)
        if last_activity_at is not None and reap_at - last_activity_at <= timeout:
            continue
        advance_project_analysis_phase(
            state,
            run,
            # 已有批次产出的僵尸收敛成 partial_failure：结果保留、重试只补余批
            "partial_failure" if int(run.get("persistedNodeCount") or 0) > 0 else "failed",
            failedFromPhase=phase,
            errorCode="PROJECT_ANALYSIS_RUN_STALLED",
            errorMessage=(
                "本次工程 AI 分析长时间没有进展，已由巡检自动收敛；"
                "请重新发起分析。"
            ),
        )
        reaped.append(run)
    return reaped
