from __future__ import annotations

import pytest


def test_project_analysis_phase_progress_is_honest_and_terminal_is_immutable() -> None:
    from libs.project_analysis.domain import (
        ProjectAnalysisPhaseError,
        advance_project_analysis_phase,
        create_project_analysis_run,
        project_analysis_status_view,
    )

    state = {"project_analysis_runs": [], "project_analysis_events": []}
    run = create_project_analysis_run(
        state,
        tenant_id="TENANT-1",
        project_id="P-1",
        snapshot={
            "projectAnalysisSnapshotId": "PASNAP-1",
            "snapshotHash": "sha256:snapshot",
            "nodeIds": [1, 2],
        },
        preview={
            "includedNodeCount": 2,
            "uniqueFileCount": 3,
            "fileReferenceCount": 4,
            "estimatedInputTokens": 90000,
            "maxContextTokens": 131072,
            "reservedOutputTokens": 24000,
            "modelAlias": "project-review-large",
            "modelRouteVersion": "2026.08",
        },
        actor_id="USER-1",
    )
    advance_project_analysis_phase(state, run, "building_prompt", loadedFileCount=1)
    advance_project_analysis_phase(state, run, "queued", queueTaskId="TASK-1")
    advance_project_analysis_phase(state, run, "model_running", heartbeat=True)
    status = project_analysis_status_view(run)

    assert status["phase"] == "model_running"
    assert status["progressMode"] == "indeterminate"
    assert "percent" not in status
    assert status["lastHeartbeatAt"]
    assert len(state["project_analysis_events"]) == 4

    advance_project_analysis_phase(state, run, "validating_output", totalFindingCount=5)
    advance_project_analysis_phase(state, run, "persisting_results", validatedFindingCount=5)
    advance_project_analysis_phase(state, run, "waiting_human_review", persistedNodeCount=2)
    completed = project_analysis_status_view(run)
    assert completed["progressMode"] == "determinate"
    assert completed["percent"] == 100
    with pytest.raises(ProjectAnalysisPhaseError):
        advance_project_analysis_phase(state, run, "model_running")


def test_project_analysis_run_is_idempotent_for_same_snapshot_and_route() -> None:
    from libs.project_analysis.domain import create_project_analysis_run

    state = {"project_analysis_runs": [], "project_analysis_events": []}
    kwargs = {
        "tenant_id": "TENANT-1",
        "project_id": "P-1",
        "snapshot": {
            "projectAnalysisSnapshotId": "PASNAP-1",
            "snapshotHash": "sha256:snapshot",
            "nodeIds": [1],
        },
        "preview": {
            "includedNodeCount": 1,
            "uniqueFileCount": 1,
            "fileReferenceCount": 1,
            "estimatedInputTokens": 100,
            "maxContextTokens": 1000,
            "reservedOutputTokens": 100,
            "modelAlias": "project-review-large",
            "modelRouteVersion": "2026.08",
        },
        "actor_id": "USER-1",
    }

    first = create_project_analysis_run(state, **kwargs)
    second = create_project_analysis_run(state, **kwargs)

    assert first is second
    assert len(state["project_analysis_runs"]) == 1


def test_project_analysis_run_is_not_reused_across_model_switch() -> None:
    """换了实际模型就是一次新的运行。

    路由版本 2026.08 下先后打过 deepseek-v4-pro 与通义；只按路由版本复用，
    切换模型对资料没变的项目完全不生效——点按钮拿回的仍是旧模型那次结果。
    """
    from libs.project_analysis.domain import create_project_analysis_run

    state = {"project_analysis_runs": [], "project_analysis_events": []}
    base = {
        "tenant_id": "TENANT-1",
        "project_id": "P-1",
        "snapshot": {
            "projectAnalysisSnapshotId": "PASNAP-1",
            "snapshotHash": "sha256:snapshot",
            "nodeIds": [1],
        },
        "actor_id": "USER-1",
    }
    preview = {
        "includedNodeCount": 1,
        "uniqueFileCount": 1,
        "fileReferenceCount": 1,
        "estimatedInputTokens": 100,
        "maxContextTokens": 1000,
        "reservedOutputTokens": 100,
        "modelAlias": "project-review-large",
        "modelRouteVersion": "2026.08",
    }
    deepseek = create_project_analysis_run(
        state, **base, preview={**preview, "modelName": "official_api:deepseek-v4-pro"}
    )
    qwen = create_project_analysis_run(
        state, **base, preview={**preview, "modelName": "official_api:qwen3.8-max"}
    )
    again = create_project_analysis_run(
        state, **base, preview={**preview, "modelName": "official_api:qwen3.8-max"}
    )

    assert deepseek is not qwen
    assert qwen is again
    assert deepseek["projectAnalysisRunId"] != qwen["projectAnalysisRunId"]
    assert not qwen["projectAnalysisRunId"].endswith("-R2"), "不是重试，是另一份运行身份"
    assert len(state["project_analysis_runs"]) == 2


def test_project_analysis_status_reconciles_stale_non_terminal_run_for_display() -> None:
    from libs.project_analysis.domain import project_analysis_status_view

    view = project_analysis_status_view(
        {
            "projectAnalysisRunId": "PARUN-STALLED",
            "projectId": "P-1",
            "phase": "validating_output",
            "status": "validating_output",
            "updatedAt": "2000-01-01 00:00:00",
        }
    )

    assert view["phase"] == "failed"
    assert view["status"] == "failed"
    assert view["statusReconciledFrom"] == "validating_output"
    assert view["errorCode"] == "PROJECT_ANALYSIS_RUN_STALLED"
    assert "长时间没有进展" in view["errorMessage"]


def test_project_analysis_status_uses_most_recent_activity_timestamp() -> None:
    from libs.contracts.responses import server_time
    from libs.project_analysis.domain import project_analysis_status_view

    view = project_analysis_status_view(
        {
            "projectAnalysisRunId": "PARUN-RECENT",
            "projectId": "P-1",
            "phase": "validating_output",
            "status": "validating_output",
            "lastHeartbeatAt": "2000-01-01 00:00:00",
            "updatedAt": server_time(),
        }
    )

    assert view["phase"] == "validating_output"
    assert view["status"] == "validating_output"


def test_failed_run_is_not_reused_so_same_snapshot_can_retry() -> None:
    """失败的运行不复用：run id 由快照哈希决定，若复用，同一份资料
    失败一次后一键分析就永远无法重试（实测：模型名配错 400 之后被卡死）。"""
    from libs.project_analysis.domain import create_project_analysis_run

    state = {"project_analysis_runs": [], "project_analysis_events": []}
    kwargs = {
        "tenant_id": "TENANT-1",
        "project_id": "P-1",
        "snapshot": {
            "projectAnalysisSnapshotId": "PASNAP-1",
            "snapshotHash": "sha256:snapshot",
            "nodeIds": [1],
        },
        "preview": {
            "includedNodeCount": 1,
            "uniqueFileCount": 1,
            "fileReferenceCount": 1,
            "estimatedInputTokens": 100,
            "maxContextTokens": 1000,
            "reservedOutputTokens": 100,
            "modelAlias": "project-review-large",
            "modelRouteVersion": "2026.08",
        },
        "actor_id": "USER-1",
    }

    first = create_project_analysis_run(state, **kwargs)
    first["phase"] = "failed"
    first["status"] = "failed"

    retry = create_project_analysis_run(state, **kwargs)

    assert retry is not first
    assert retry["projectAnalysisRunId"] != first["projectAnalysisRunId"]
    assert retry["projectAnalysisRunId"].endswith("-R2")
    assert len(state["project_analysis_runs"]) == 2

    # 重试成功后（非 failed），再次发起必须复用重试运行，而不是三跑。
    retry["phase"] = "waiting_human_review"
    third = create_project_analysis_run(state, **kwargs)
    assert third is retry


def test_reaper_fails_stalled_runs_but_spares_active_and_long_model_calls() -> None:
    """收敛器把超时无进展的非终态运行落 failed（改库）；活跃运行和
    在长超时保护内的 model_running 不碰。僵尸非终态 run 会被幂等复用，
    不清掉的话该快照永远发不起新分析。"""
    from datetime import datetime, timedelta

    from libs.contracts.responses import SERVER_TZ
    from libs.project_analysis.domain import reap_stalled_project_analysis_runs

    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=SERVER_TZ)
    stalled = {
        "projectAnalysisRunId": "PARUN-DEAD",
        "phase": "queued",
        "status": "queued",
        "updatedAt": "2026-08-28 11:00:00",
        "revision": 1,
    }
    active = {
        "projectAnalysisRunId": "PARUN-LIVE",
        "phase": "validating_output",
        "status": "validating_output",
        "updatedAt": "2026-08-28 11:55:00",
        "revision": 1,
    }
    long_model_call = {
        "projectAnalysisRunId": "PARUN-SLOW-MODEL",
        "phase": "model_running",
        "status": "model_running",
        "lastHeartbeatAt": "2026-08-28 11:10:00",  # 50 分钟前，但模型超时保护 60 分钟
        "updatedAt": "2026-08-28 11:10:00",
        "revision": 1,
    }
    terminal = {
        "projectAnalysisRunId": "PARUN-DONE",
        "phase": "waiting_human_review",
        "status": "waiting_human_review",
        "updatedAt": "2026-08-28 10:00:00",
        "revision": 1,
    }
    state = {
        "project_analysis_runs": [stalled, active, long_model_call, terminal],
        "project_analysis_events": [],
    }

    reaped = reap_stalled_project_analysis_runs(
        state,
        now=now,
        stall_timeout=timedelta(minutes=30),
        model_running_timeout=timedelta(minutes=60),
    )

    assert [r["projectAnalysisRunId"] for r in reaped] == ["PARUN-DEAD"]
    assert stalled["phase"] == "failed"
    assert stalled["errorCode"] == "PROJECT_ANALYSIS_RUN_STALLED"
    assert stalled["failedFromPhase"] == "queued"
    assert active["phase"] == "validating_output"
    assert long_model_call["phase"] == "model_running"
    assert terminal["phase"] == "waiting_human_review"

    # model_running 超过保护阈值后照样收敛
    later = now + timedelta(minutes=25)
    reaped_later = reap_stalled_project_analysis_runs(
        state,
        now=later,
        stall_timeout=timedelta(minutes=30),
        model_running_timeout=timedelta(minutes=60),
    )
    assert [r["projectAnalysisRunId"] for r in reaped_later] == ["PARUN-SLOW-MODEL"]
    assert long_model_call["phase"] == "failed"
