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
