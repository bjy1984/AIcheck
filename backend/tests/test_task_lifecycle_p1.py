from __future__ import annotations

import asyncio
import inspect
import sys

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.review_worker.activities import run_review_graph_activity
from apps.review_worker.workflows import ReviewRunWorkflow
from libs import runtime_readiness
from libs.db.repository import repo
from libs.integrations import task_dispatcher
from libs.review_orchestrator.dispatcher import (
    _start_temporal_workflow,
    dispatch_existing_review_run,
)
from libs.review_orchestrator.execution import clone_review_run_for_replay, review_workflow_id
from libs.security.tenant import current_tenant_id

client = TestClient(app)


@pytest.mark.parametrize(
    ("dependencies", "expected_ready", "expected_reason", "expected_reason_codes"),
    [
        (
            {"service": False, "schema": True, "workerHeartbeat": True},
            False,
            "temporal_service_unavailable",
            ["temporal_service_unavailable"],
        ),
        (
            {"service": True, "schema": False, "workerHeartbeat": True},
            False,
            "temporal_schema_unavailable",
            ["temporal_schema_unavailable"],
        ),
        (
            {"service": True, "schema": True, "workerHeartbeat": False},
            False,
            "temporal_worker_unavailable",
            ["temporal_worker_unavailable"],
        ),
        (
            {"service": True, "schema": True, "workerHeartbeat": True},
            True,
            "temporal_dependencies_ready",
            [],
        ),
    ],
)
def test_temporal_dispatch_readiness_requires_every_live_dependency(
    monkeypatch: pytest.MonkeyPatch,
    dependencies: dict[str, bool],
    expected_ready: bool,
    expected_reason: str,
    expected_reason_codes: list[str],
) -> None:
    """Removing any live dependency must stop Temporal dispatch before a run is queued."""
    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", "temporal")

    readiness = task_dispatcher.ai_recheck_dispatch_readiness(lambda: dependencies)

    assert readiness["ready"] is expected_ready
    assert readiness["mode"] == "temporal"
    assert readiness["orchestrationMode"] == "temporal"
    assert readiness["statusReason"] == expected_reason
    assert readiness["reasonCodes"] == expected_reason_codes
    assert readiness["dependencies"] == dependencies


def test_temporal_dispatch_reads_cached_health_snapshot_without_live_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An AI request must never repeat the health path's network and database probes."""
    calls = 0

    def live_dependencies() -> dict[str, bool]:
        nonlocal calls
        calls += 1
        return {"service": True, "schema": True, "workerHeartbeat": True}

    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", "temporal")
    monkeypatch.setenv("AICHECK_REVIEW_READINESS_TTL_SECONDS", "30")
    monkeypatch.setattr(runtime_readiness, "_review_readiness_cache", None, raising=False)
    monkeypatch.setattr(runtime_readiness, "live_review_runtime_dependencies", live_dependencies)

    refreshed = runtime_readiness.cached_review_dispatch_readiness(refresh_if_stale=True)
    first = task_dispatcher.ai_recheck_dispatch_readiness()
    second = task_dispatcher.ai_recheck_dispatch_readiness()
    health = runtime_readiness.production_runtime_status()

    assert refreshed["ready"] is True
    assert first == second
    assert first["ready"] is True
    assert calls == 1
    assert health["reviewDispatchReadiness"] == first
    assert health["workflowReady"] == first["ready"]
    assert health["temporalReadiness"]["ready"] == first["ready"]
    assert first["cache"]["ttlSeconds"] == 30.0
    assert first["cache"]["fresh"] is True
    first["dependencies"]["service"] = False
    assert task_dispatcher.ai_recheck_dispatch_readiness()["dependencies"]["service"] is True


def test_expired_temporal_snapshot_fails_closed_without_request_path_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An expired cache must block dispatch, not turn an AI request into a refresh worker."""
    calls = 0
    now = 100.0

    def live_dependencies() -> dict[str, bool]:
        nonlocal calls
        calls += 1
        return {"service": True, "schema": True, "workerHeartbeat": True}

    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", "temporal")
    monkeypatch.setenv("AICHECK_REVIEW_READINESS_TTL_SECONDS", "1")
    monkeypatch.setattr(runtime_readiness, "_review_readiness_cache", None)
    monkeypatch.setattr(runtime_readiness, "live_review_runtime_dependencies", live_dependencies)
    monkeypatch.setattr(runtime_readiness.time, "monotonic", lambda: now)
    runtime_readiness.cached_review_dispatch_readiness(refresh_if_stale=True)
    now = 102.0

    readiness = task_dispatcher.ai_recheck_dispatch_readiness()

    assert readiness["ready"] is False
    assert readiness["statusReason"] == "temporal_readiness_snapshot_stale"
    assert readiness["cache"]["stale"] is True
    assert calls == 1


def test_slow_health_refresh_starts_ttl_when_probes_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful 1.05s refresh must still be fresh immediately with the supported 1s TTL."""
    now = 100.0

    def slow_live_dependencies() -> dict[str, bool]:
        nonlocal now
        now += 1.05
        return {"service": True, "schema": True, "workerHeartbeat": True}

    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", "temporal")
    monkeypatch.setenv("AICHECK_REVIEW_READINESS_TTL_SECONDS", "1")
    monkeypatch.setattr(runtime_readiness, "_review_readiness_cache", None)
    monkeypatch.setattr(runtime_readiness, "live_review_runtime_dependencies", slow_live_dependencies)
    monkeypatch.setattr(runtime_readiness.time, "monotonic", lambda: now)

    health = runtime_readiness.production_runtime_status(refresh_review_readiness=True)
    dispatch = task_dispatcher.ai_recheck_dispatch_readiness()

    assert health["workflowReady"] is True
    assert health["reviewDispatchReadiness"]["ready"] is True
    assert dispatch["ready"] is True
    assert dispatch["statusReason"] == "temporal_dependencies_ready"
    assert dispatch == health["reviewDispatchReadiness"]


def test_postgres_readiness_probes_bound_connection_and_statement_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removing either PostgreSQL timeout must make readiness probes unsafe and fail this test."""
    connect_kwargs: list[dict] = []

    class Result:
        def __init__(self, query: str) -> None:
            self.query = query

        def fetchall(self):
            if "service_heartbeats" in self.query:
                return [(_review_worker_payload(), None)]
            return [(name,) for name in runtime_readiness.REQUIRED_TABLES]

        def fetchone(self):
            return (1, None)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query: str, *_args):
            return Result(query)

        def rollback(self) -> None:
            return None

    class Psycopg:
        @staticmethod
        def connect(_dsn: str, **kwargs):
            connect_kwargs.append(kwargs)
            return Connection()

    monkeypatch.setitem(sys.modules, "psycopg", Psycopg())
    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", "temporal")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_DSN", "postgresql://checkpoint.test/db")
    monkeypatch.setenv("AICHECK_DATABASE_URL", "postgresql://application.test/db")
    monkeypatch.setenv("AICHECK_REVIEW_READINESS_PROBE_TIMEOUT_SECONDS", "0.4")
    monkeypatch.setenv("TEMPORAL_ADDRESS", "temporal.test:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "aicheck")

    schema = runtime_readiness.workflow_schema_status()
    heartbeat = runtime_readiness.review_worker_heartbeat_status()

    assert schema["ready"] is True
    assert heartbeat["ready"] is True
    assert len(connect_kwargs) == 2
    assert all(options["connect_timeout"] == 1 for options in connect_kwargs)
    assert all(options["options"] == "-c statement_timeout=400" for options in connect_kwargs)


def test_temporal_service_probe_uses_bounded_protocol_handshake(monkeypatch) -> None:
    """A listening non-Temporal TCP socket must not be sufficient for dispatch readiness."""
    observed: dict[str, str] = {}

    async def connect(address: str, *, namespace: str):
        observed.update({"address": address, "namespace": namespace})
        raise RuntimeError("protocol handshake failed")

    monkeypatch.setenv("TEMPORAL_ADDRESS", "temporal.test:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "aicheck")
    monkeypatch.setenv("AICHECK_REVIEW_READINESS_PROBE_TIMEOUT_SECONDS", "0.4")
    monkeypatch.setattr("temporalio.client.Client.connect", connect)

    status = runtime_readiness.temporal_service_connectivity_status()

    assert status["ready"] is False
    assert status["errorType"] == "RuntimeError"
    assert status["address"] == "temporal.test:7233"
    assert status["namespace"] == "aicheck"
    assert observed == {"address": "temporal.test:7233", "namespace": "aicheck"}


def _review_worker_payload(task_queue: str = "review.workflow") -> dict[str, str]:
    return {
        "taskQueue": task_queue,
        "temporalAddress": "temporal.test:7233",
        "temporalNamespace": "aicheck",
    }


def test_review_worker_heartbeat_matching_runtime_identity_is_ready(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_WORKFLOW_TASK_QUEUE", "review.workflow")
    monkeypatch.setenv("TEMPORAL_ADDRESS", "temporal.test:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "aicheck")

    status = runtime_readiness.review_worker_heartbeat_status(
        lambda: [{"payload": _review_worker_payload(), "lastSeenAt": "2026-08-22T12:00:00+00:00"}]
    )

    assert status["ready"] is True
    assert status["statusReason"] == "review_worker_heartbeat_ready"
    assert status["expectedTaskQueue"] == "review.workflow"
    assert status["observedTaskQueues"] == ["review.workflow"]


def test_review_worker_heartbeat_wrong_task_queue_is_not_ready(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_WORKFLOW_TASK_QUEUE", "review.workflow")
    monkeypatch.setenv("TEMPORAL_ADDRESS", "temporal.test:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "aicheck")

    status = runtime_readiness.review_worker_heartbeat_status(
        lambda: [{"payload": _review_worker_payload("review.other"), "lastSeenAt": None}]
    )

    assert status["ready"] is False
    assert status["statusReason"] == "review_worker_task_queue_mismatch"
    assert status["reasonCodes"] == ["review_worker_task_queue_mismatch"]
    assert status["observedTaskQueues"] == ["review.other"]


def test_review_worker_heartbeat_mixed_fresh_worker_queues_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_WORKFLOW_TASK_QUEUE", "review.workflow")
    monkeypatch.setenv("TEMPORAL_ADDRESS", "temporal.test:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "aicheck")

    status = runtime_readiness.review_worker_heartbeat_status(
        lambda: [
            {"payload": _review_worker_payload(), "lastSeenAt": "2026-08-22T12:00:00+00:00"},
            {"payload": _review_worker_payload("review.old"), "lastSeenAt": "2026-08-22T12:00:01+00:00"},
        ]
    )

    assert status["ready"] is False
    assert status["activeCount"] == 2
    assert status["statusReason"] == "review_worker_task_queue_mismatch"
    assert status["observedTaskQueues"] == ["review.old", "review.workflow"]


def test_review_worker_heartbeat_missing_identity_payload_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_WORKFLOW_TASK_QUEUE", "review.workflow")
    monkeypatch.setenv("TEMPORAL_ADDRESS", "temporal.test:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "aicheck")

    status = runtime_readiness.review_worker_heartbeat_status(
        lambda: [{"payload": None, "lastSeenAt": "2026-08-22T12:00:00+00:00"}]
    )

    assert status["ready"] is False
    assert status["statusReason"] == "review_worker_identity_missing"
    assert status["reasonCodes"] == ["review_worker_identity_missing"]
    assert status["missingIdentityCount"] == 1


def test_worker_queue_mismatch_reason_propagates_to_shared_health_and_dispatch_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = {
        "ready": False,
        "statusReason": "review_worker_task_queue_mismatch",
        "reasonCodes": ["review_worker_task_queue_mismatch"],
        "expectedTaskQueue": "review.workflow",
        "observedTaskQueues": ["review.old"],
    }
    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", "temporal")
    monkeypatch.setattr(runtime_readiness, "_review_readiness_cache", None)
    monkeypatch.setattr(
        runtime_readiness,
        "live_review_runtime_dependencies",
        lambda: {"service": {"ready": True}, "schema": {"ready": True}, "workerHeartbeat": worker},
    )

    health = runtime_readiness.production_runtime_status(refresh_review_readiness=True)
    dispatch = task_dispatcher.ai_recheck_dispatch_readiness()

    assert dispatch == health["reviewDispatchReadiness"]
    assert dispatch["ready"] is False
    assert dispatch["statusReason"] == "temporal_worker_unavailable"
    assert dispatch["dependencyDetails"]["workerHeartbeat"] == worker


def test_strict_legacy_celery_uses_same_policy_for_dispatch_and_health(monkeypatch) -> None:
    """Strict production must not disagree about the supported legacy Celery path."""
    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", "legacy")
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "celery")
    monkeypatch.setenv("AICHECK_STRICT_PRODUCTION", "true")
    monkeypatch.setattr(
        runtime_readiness,
        "material_review_asset_status",
        lambda: {"ready": True, "version": "test", "itemCount": 1, "sourceSha256": "sha256:test"},
    )
    monkeypatch.setattr(
        runtime_readiness,
        "audit_service_configuration_status",
        lambda: {
            "ocr": {"ready": True},
            "qwen": {"ready": True},
            "embedding": {"ready": True},
            "temporal": {"configured": False, "mode": "legacy"},
        },
    )

    dispatch = task_dispatcher.ai_recheck_dispatch_readiness()
    health = runtime_readiness.production_runtime_status()

    assert dispatch["ready"] is True
    assert dispatch["mode"] == "celery"
    assert dispatch["statusReason"] == "task_dispatch_enabled"
    assert health["workflowReady"] is True
    assert health["reviewDispatchReadiness"] == dispatch
    assert health["runtimeReady"] is True


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
