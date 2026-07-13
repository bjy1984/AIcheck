from __future__ import annotations

import inspect

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.review_worker.workflows import ReviewRunWorkflow
from libs.db.repository import repo
from libs.review_orchestrator.dispatcher import dispatch_existing_review_run
from libs.review_orchestrator.execution import clone_review_run_for_replay


client = TestClient(app)


def setup_function() -> None:
    repo.reset()


def parent_review_run() -> dict:
    parent = {
        "id": "RRUN-PARENT-001",
        "reviewRunId": "RRUN-PARENT-001",
        "aiRunId": "AIRUN-PARENT-001",
        "projectId": "P-2026-HDCP-001",
        "nodeId": 24,
        "workflowEngine": "inline_temporal_compatible",
        "workflowId": "review-run-RRUN-PARENT-001",
        "taskQueues": {"workflow": "review.workflow"},
        "status": "failed",
        "reviewMode": "formal",
        "advisoryOnly": False,
        "findingDrafts": [],
    }
    repo.state["review_runs"].insert(0, parent)
    return parent


def test_temporal_workflow_has_bounded_retry_policy() -> None:
    source = inspect.getsource(ReviewRunWorkflow.run)

    assert "RetryPolicy(" in source
    assert "maximum_attempts=3" in source
    assert "non_retryable_error_types" in source


def test_dispatch_existing_review_run_marks_disabled_mode_failed(monkeypatch) -> None:
    child = clone_review_run_for_replay(parent_review_run(), run_mode="diagnostic_replay", reason="test")
    monkeypatch.setattr("libs.review_orchestrator.dispatcher.review_orchestration_mode", lambda: "legacy")

    dispatch = dispatch_existing_review_run(child)

    assert dispatch["status"] == "failed_to_start"
    assert child["status"] == "failed_to_start"
    assert child["dispatchErrorCode"] == "REVIEW_ORCHESTRATION_DISABLED"


def test_cancel_knowledge_task_records_revoke_request(monkeypatch) -> None:
    task = repo.state["knowledge_tasks"][0]
    task["status"] = "运行中"
    task["lastDispatch"] = {"taskId": "CELERY-TASK-1"}
    captured: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        "apps.worker.celery_app.celery_app.control.revoke",
        lambda task_id, terminate=False: captured.append((task_id, terminate)),
    )

    response = client.post(
        f"/api/knowledge/tasks/{task['id']}/cancel",
        json={"reason": "用户取消"},
        headers={"X-Role": "admin", "Idempotency-Key": "cancel-task-p1"},
    )

    data = response.json()["data"]
    assert captured == [("CELERY-TASK-1", False)]
    assert data["task"]["status"] == "已取消"
    assert data["revokeResults"] == [{"taskId": "CELERY-TASK-1", "status": "requested"}]


def test_operations_tasks_exposes_canonical_status_codes() -> None:
    repo.state["review_runs"].insert(
        0,
        {
            "id": "RRUN-TASK-001",
            "reviewRunId": "RRUN-TASK-001",
            "projectId": "P-2026-HDCP-001",
            "status": "waiting_human_review",
            "updatedAt": "2026-07-12T00:00:00Z",
        },
    )

    response = client.get("/api/operations/tasks", params={"area": "fde"}, headers={"X-Role": "fde"})
    item = next(entry for entry in response.json()["data"]["items"] if entry["id"] == "RRUN-TASK-001")

    assert item["status"] == "waiting_human_review"
    assert item["statusCode"] == "waiting_human"
    assert item["displayStatus"] == "waiting_human_review"
