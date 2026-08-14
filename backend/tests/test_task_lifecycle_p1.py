from __future__ import annotations

import asyncio
import inspect

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.review_worker.activities import run_review_graph_activity
from apps.review_worker.workflows import ReviewRunWorkflow
from libs.db.repository import repo
from libs.review_orchestrator.dispatcher import (
    _start_temporal_workflow,
    dispatch_existing_review_run,
)
from libs.review_orchestrator.execution import clone_review_run_for_replay, review_workflow_id
from libs.security.tenant import current_tenant_id

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
    assert "review_run_id if legacy_execution else activity_input" in source
    assert 'graph_result.get("status") == "waiting_human_input"' in source
    assert "self._human_input_command" in source
    assert '"status": "resuming"' in source


def test_temporal_workflow_id_is_stable_and_tenant_namespaced() -> None:
    first = review_workflow_id("TENANT-A", "RRUN-SAME")
    repeated = review_workflow_id("TENANT-A", "RRUN-SAME")
    other_tenant = review_workflow_id("TENANT-B", "RRUN-SAME")

    assert first == repeated
    assert first != other_tenant
    assert "TENANT-A" not in first


def test_temporal_start_passes_tenant_execution_envelope(monkeypatch) -> None:
    captured: dict = {}

    class Handle:
        id = "workflow-id"
        result_run_id = "temporal-run-id"

    class Client:
        async def start_workflow(self, workflow_type, execution, *, id, task_queue):
            captured.update(
                {
                    "workflowType": workflow_type,
                    "execution": execution,
                    "id": id,
                    "taskQueue": task_queue,
                }
            )
            return Handle()

    async def connect(*_args, **_kwargs):
        return Client()

    monkeypatch.setattr("temporalio.client.Client.connect", connect)
    run = {
        "id": "RRUN-SAME",
        "reviewRunId": "RRUN-SAME",
        "tenantId": "TENANT-A",
        "workflowId": review_workflow_id("TENANT-A", "RRUN-SAME"),
        "taskQueues": {"workflow": "review.workflow"},
        "revision": 1,
    }
    repo.state["review_runs"].insert(0, run)

    asyncio.run(_start_temporal_workflow(run))

    assert captured["execution"] == {"tenantId": "TENANT-A", "reviewRunId": "RRUN-SAME"}
    assert captured["id"] == review_workflow_id("TENANT-A", "RRUN-SAME")


def test_review_graph_activity_sets_and_restores_tenant_context(monkeypatch) -> None:
    observed: list[str] = []
    monkeypatch.setattr("apps.review_worker.activities.activity.heartbeat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "apps.review_worker.activities.load_review_run_state",
        lambda _review_run_id: observed.append(current_tenant_id()),
    )
    monkeypatch.setattr(
        "apps.review_worker.activities.execute_review_run_inline",
        lambda _review_run_id: {"status": "waiting_human_review"},
    )
    monkeypatch.setattr("apps.review_worker.activities.flush_state_records", lambda _records: None)

    result = asyncio.run(
        run_review_graph_activity({"tenantId": "TENANT-ACTIVITY", "reviewRunId": "RRUN-1"})
    )

    assert result["status"] == "waiting_human_review"
    assert observed == ["TENANT-ACTIVITY"]
    assert current_tenant_id() == "TENANT-DEFAULT"


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


def test_r12_human_input_api_reads_task_and_resumes_inline_review(monkeypatch) -> None:
    review_run_id = "RRUN-R12-API"
    task_id = "HIT-R12-API"
    candidate_id = "R12LIC-API"
    run = {
        "id": review_run_id,
        "reviewRunId": review_run_id,
        "projectId": "P-2026-HDCP-001",
        "nodeId": 12,
        "status": "waiting_human_input",
        "currentStep": "waiting_r12_registry_verification",
        "workflowEngine": "inline_temporal_compatible",
        "workflowId": "review-run-RRUN-R12-API",
        "inputHash": "sha256:r12-api",
        "revision": 1,
        "humanInputTasks": [
            {
                "taskId": task_id,
                "taskType": "official_registry_license_verification",
                "nodeId": 12,
                "title": "核验制造许可证官网登记信息",
                "description": "人工官网查询",
                "status": "pending",
                "required": True,
                "inputHash": "sha256:r12-task-api",
                "reviewRunInputHash": "sha256:r12-api",
                "candidateCount": 1,
                "candidates": [
                    {
                        "candidateId": candidate_id,
                        "documentVersionId": "DV-R12-API",
                        "pageNo": 1,
                        "licenseNo": "TS2710504-2027",
                        "organizationName": "河北管件有限公司",
                    }
                ],
                "responses": [],
            }
        ],
    }
    repo.state["review_runs"].insert(0, run)
    monkeypatch.setattr(
        "apps.api.routes.execute_review_run_inline",
        lambda _review_run_id: {"reviewRunId": _review_run_id, "status": "waiting_human_review"},
    )
    headers = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}

    task_response = client.get(
        f"/api/review-runs/{review_run_id}/human-input-tasks/active",
        headers=headers,
    )
    assert task_response.status_code == 200
    task_payload = task_response.json()["data"]
    assert task_payload["task"]["taskId"] == task_id

    submit_response = client.post(
        f"/api/review-runs/{review_run_id}/human-input-tasks/{task_id}/responses",
        json={
            "verifications": [
                {
                    "candidateId": candidate_id,
                    "outcome": "verified_match",
                    "registryLicenseNo": "TS2710504-2027",
                    "registryOrganizationName": "河北管件有限公司",
                    "registryStatus": "active",
                    "registryScopeRaw": "非焊接管件、锻制法兰",
                    "sourceUrl": "https://example.test/registry",
                    "attested": True,
                }
            ]
        },
        headers={
            **headers,
            "If-Match": task_payload["reviewRun"]["etag"],
            "Idempotency-Key": "r12-human-input-api-test",
        },
    )

    assert submit_response.status_code == 200
    assert run["humanInputTasks"][0]["status"] == "completed"
    assert run["manualRegistryVerifications"][0]["verifications"][0]["outcome"] == "verified_match"
