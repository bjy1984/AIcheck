from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo
from libs.db.seed import PROJECT_ID

client = TestClient(app)
HEADERS = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None
    document, version = repo.create_document(PROJECT_ID, "分析资料.pdf", "application/pdf")
    repo.apply_ocr_result(
        document["id"],
        version["id"],
        {
            "status": "success",
            "artifactHash": "sha256:project-analysis",
            "fragments": [{"pageNo": 1, "text": "工程分析完整 OCR"}],
            "tables": [],
            "seals": [],
        },
    )
    repo.state["node_evidence_links"].append(
        {
            "id": "NEL-PROJECT-ANALYSIS",
            "projectId": PROJECT_ID,
            "nodeId": 1,
            "documentId": document["id"],
            "documentVersionId": version["id"],
            "manualStatus": "confirmed",
            "revision": 1,
        }
    )


def _ok(response) -> dict:
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def test_preview_create_list_detail_and_status_are_project_scoped() -> None:
    preview = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/preview",
            headers=HEADERS,
        )
    )["preview"]
    created = _ok(
        client.post(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/runs",
            headers={**HEADERS, "Idempotency-Key": "one-project-analysis"},
            json={"snapshotHash": preview["snapshotHash"]},
        )
    )["run"]
    replayed = _ok(
        client.post(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/runs",
            headers={**HEADERS, "Idempotency-Key": "one-project-analysis"},
            json={"snapshotHash": preview["snapshotHash"]},
        )
    )["run"]
    run_id = created["projectAnalysisRunId"]
    listed = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/runs",
            headers=HEADERS,
        )
    )
    detail = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/runs/{run_id}",
            headers=HEADERS,
        )
    )["run"]
    status = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/runs/{run_id}/status",
            headers=HEADERS,
        )
    )["status"]

    assert preview["includedNodeCount"] == 1
    assert preview["uniqueFileCount"] == 1
    assert preview["contextLimitExceeded"] is False
    assert created["projectAnalysisRunId"] == replayed["projectAnalysisRunId"]
    assert listed["total"] == 1
    assert detail["projectId"] == PROJECT_ID
    assert status["phase"] == "preparing_snapshot"
    assert created["dispatch"]["mode"] == "disabled"
    assert repo.state["audit_logs"][0]["objectType"] == "ProjectAnalysisRun"


def test_node_package_exposes_project_analysis_status_and_validated_node_result() -> None:
    from libs.project_analysis.results import persist_project_analysis_node_results

    project_run = {
        "projectAnalysisRunId": "PARUN-NODE-DISPLAY",
        "projectAnalysisSnapshotId": "PASNAP-NODE-DISPLAY",
        "tenantId": "TENANT-DEFAULT",
        "projectId": PROJECT_ID,
        "phase": "waiting_human_review",
        "status": "waiting_human_review",
        "includedNodeCount": 1,
        "uniqueFileCount": 1,
        "fileReferenceCount": 1,
        "estimatedInputTokens": 80000,
        "totalFindingCount": 1,
        "validatedFindingCount": 1,
        "persistedNodeCount": 1,
        "modelAlias": "project-review-large",
        "rawModelOutput": "must-not-be-exposed-in-node-package",
        "createdAt": "2026-08-27 20:00:00",
        "updatedAt": "2026-08-27 20:10:00",
        "finishedAt": "2026-08-27 20:10:00",
    }
    repo.state["project_analysis_snapshots"] = [
        {
            "projectAnalysisSnapshotId": "PASNAP-NODE-DISPLAY",
            "projectId": PROJECT_ID,
            "nodeIds": [1],
        }
    ]
    repo.state["project_analysis_runs"] = [project_run]
    persist_project_analysis_node_results(
        repo.state,
        project_run,
        {
            "nodeReviews": [
                {
                    "nodeId": 1,
                    "reviewResult": "partially_supported",
                    "findings": [
                        {
                            "findingType": "license_scope",
                            "severity": "high",
                            "title": "许可范围需要人工确认",
                            "description": "现有证据不足以确认许可范围完全覆盖。",
                            "confidence": 0.72,
                            "evidenceRefs": [],
                            "ruleRefs": [],
                            "requiresHumanConfirmation": True,
                        }
                    ],
                }
            ]
        },
    )

    package = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/nodes/1/package",
            headers=HEADERS,
        )
    )

    run_view = package["projectAnalysis"]["run"]
    assert run_view["projectAnalysisRunId"] == "PARUN-NODE-DISPLAY"
    assert run_view["projectId"] == PROJECT_ID
    assert run_view["phase"] == "waiting_human_review"
    assert run_view["estimatedInputTokens"] == 80000
    assert run_view["validatedFindingCount"] == 1
    assert run_view["persistedNodeCount"] == 1
    assert run_view["progressMode"] == "determinate"
    assert run_view["percent"] == 100
    node_review = package["projectAnalysis"]["nodeReview"]
    assert node_review["projectAnalysisRunId"] == "PARUN-NODE-DISPLAY"
    assert node_review["reviewResult"] == "partially_supported"
    assert node_review["findingDrafts"][0]["title"] == "许可范围需要人工确认"
    assert "rawModelOutput" not in package["projectAnalysis"]["run"]


def test_create_rejects_changed_snapshot_and_wrong_role() -> None:
    preview = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/preview",
            headers=HEADERS,
        )
    )["preview"]
    stale = client.post(
        f"/projects/{PROJECT_ID}/inspection/full-project-analysis/runs",
        headers={**HEADERS, "Idempotency-Key": "stale-project-analysis"},
        json={"snapshotHash": "sha256:stale"},
    ).json()
    forbidden = client.get(
        f"/projects/{PROJECT_ID}/inspection/full-project-analysis/preview",
        headers={"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"},
    ).json()

    assert stale["code"] != 0
    assert stale["data"]["currentSnapshotHash"] == preview["snapshotHash"]
    assert forbidden["code"] != 0


def test_preview_backfills_large_model_route_for_upgraded_persisted_state() -> None:
    repo.state["model_route_versions"] = [
        row
        for row in repo.state["model_route_versions"]
        if row.get("modelAlias") != "project-review-large"
    ]

    preview = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/preview",
            headers=HEADERS,
        )
    )["preview"]

    assert preview["modelAlias"] == "project-review-large"
    assert preview["maxContextTokens"] >= 131072


def test_empty_project_analysis_scope_does_not_create_run() -> None:
    repo.state["node_evidence_links"] = []
    repo.state["bindings"] = []
    preview = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/preview",
            headers=HEADERS,
        )
    )["preview"]

    response = client.post(
        f"/projects/{PROJECT_ID}/inspection/full-project-analysis/runs",
        headers={**HEADERS, "Idempotency-Key": "empty-project-analysis"},
        json={"snapshotHash": preview["snapshotHash"]},
    ).json()

    assert preview["includedNodeCount"] == 0
    assert response["code"] != 0
    assert response["message"] == "PROJECT_ANALYSIS_EMPTY_SCOPE"
    assert repo.state.get("project_analysis_runs", []) == []


def test_dispatch_failure_lands_failed_run_and_stays_retryable(monkeypatch) -> None:
    preview = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/preview",
            headers=HEADERS,
        )
    )["preview"]

    def fail_dispatch(_run_id: str) -> dict:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(
        "apps.api.project_analysis_routes.task_dispatcher.dispatch_project_analysis",
        fail_dispatch,
    )
    failed = client.post(
        f"/projects/{PROJECT_ID}/inspection/full-project-analysis/runs",
        headers={**HEADERS, "Idempotency-Key": "retryable-project-analysis"},
        json={"snapshotHash": preview["snapshotHash"]},
    )

    assert failed.status_code == 503
    assert failed.json()["data"]["reason"] == "AI_RUN_FAILED"
    # run 在派发前已落库，失败后必须留档为 failed 终态——从内存里删掉了事
    # 会在 DB 留下永远 preparing_snapshot 的孤儿（派发前落库是为了消掉
    # worker 首跳 PROJECT_ANALYSIS_RUN_NOT_FOUND 的竞态）。
    failed_runs = repo.state.get("project_analysis_runs", [])
    assert len(failed_runs) == 1
    assert failed_runs[0]["phase"] == "failed"
    assert failed_runs[0]["errorCode"] == "DISPATCH_FAILED"
    failed_run_id = str(failed_runs[0]["projectAnalysisRunId"])

    monkeypatch.setattr(
        "apps.api.project_analysis_routes.task_dispatcher.dispatch_project_analysis",
        lambda _run_id: {"mode": "disabled", "taskId": None},
    )
    retried = _ok(
        client.post(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/runs",
            headers={**HEADERS, "Idempotency-Key": "retryable-project-analysis"},
            json={"snapshotHash": preview["snapshotHash"]},
        )
    )["run"]

    assert retried["phase"] == "preparing_snapshot"
    assert retried["dispatch"]["mode"] == "disabled"
    # failed 运行不被幂等复用：重试是一次新运行，failed 历史留档
    assert retried["projectAnalysisRunId"] != failed_run_id
    assert len(repo.state.get("project_analysis_runs", [])) == 2


def test_stalled_cached_run_is_invalidated_and_restarted_with_same_key(monkeypatch) -> None:
    """同一快照的僵尸运行不能让固定 Idempotency-Key 永久回放旧响应。"""
    monkeypatch.setattr(
        "apps.api.project_analysis_routes.task_dispatcher.dispatch_project_analysis",
        lambda _run_id: {"mode": "disabled", "taskId": None},
    )
    preview = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/preview",
            headers=HEADERS,
        )
    )["preview"]
    headers = {**HEADERS, "Idempotency-Key": "stalled-project-analysis"}
    first = _ok(
        client.post(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/runs",
            headers=headers,
            json={"snapshotHash": preview["snapshotHash"]},
        )
    )["run"]
    stalled = repo.state["project_analysis_runs"][0]
    stalled.update(
        {
            "phase": "validating_output",
            "status": "validating_output",
            "createdAt": "2026-01-01 00:00:00",
            "updatedAt": "2026-01-01 00:10:00",
            "lastHeartbeatAt": "2026-01-01 00:05:00",
        }
    )

    restarted = _ok(
        client.post(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/runs",
            headers=headers,
            json={"snapshotHash": preview["snapshotHash"]},
        )
    )["run"]

    runs = repo.state["project_analysis_runs"]
    assert any(row["phase"] == "failed" for row in runs), runs
    assert len(runs) == 2
    assert restarted["projectAnalysisRunId"] != first["projectAnalysisRunId"]
    assert restarted["projectAnalysisRunId"].endswith("-R2")
    assert restarted["phase"] == "preparing_snapshot"
    failed = next(row for row in runs if row["projectAnalysisRunId"] == first["projectAnalysisRunId"])
    assert failed["phase"] == "failed"
    assert failed["errorCode"] == "PROJECT_ANALYSIS_RUN_STALLED"


def test_run_is_persisted_before_celery_dispatch(monkeypatch) -> None:
    """先落库再派发。worker 拿到任务比本请求结束后的中间件统一落库更快，
    首跳会 PROJECT_ANALYSIS_RUN_NOT_FOUND，白烧一次重试退避（实测约 17 秒）。"""
    events: list[str] = []
    monkeypatch.setattr(
        "apps.api.project_analysis_routes.flush_state",
        lambda *_args, **_kwargs: events.append("flush"),
    )
    monkeypatch.setattr(
        "apps.api.project_analysis_routes.task_dispatcher.dispatch_project_analysis",
        lambda _run_id: events.append("dispatch") or {"mode": "disabled", "taskId": None},
    )
    preview = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/preview",
            headers=HEADERS,
        )
    )["preview"]
    _ok(
        client.post(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/runs",
            headers={**HEADERS, "Idempotency-Key": "persist-before-dispatch"},
            json={"snapshotHash": preview["snapshotHash"]},
        )
    )

    assert events == ["flush", "dispatch"]


def test_celery_dispatch_envelope_is_deterministic_and_written_before_send(monkeypatch) -> None:
    """celery 模式下派发信封先于发送写进 run 并落库。

    否则 run 行在本请求里有两次写（落库后又补 dispatch 字段），收尾中间件
    会在 worker 已开始改这一行之后再写旧内容，worker 落库首跳必撞
    ConcurrentPersistenceError（实测），白烧一次重试。
    """
    from libs.integrations import task_dispatcher

    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "celery")
    envelope = task_dispatcher.project_analysis_dispatch_envelope("PARUN-X")
    assert envelope["mode"] == "celery"
    assert envelope["taskId"] == task_dispatcher.deterministic_task_id(
        "project-analysis", "PARUN-X"
    )

    sent: list[str] = []
    monkeypatch.setattr(
        "apps.api.project_analysis_routes.task_dispatcher.dispatch_project_analysis",
        lambda run_id: sent.append(run_id) or dict(envelope),
    )
    flush_snapshots: list[object] = []
    monkeypatch.setattr(
        "apps.api.project_analysis_routes.flush_state",
        lambda *_args, **_kwargs: flush_snapshots.append(
            (repo.state.get("project_analysis_runs") or [{}])[0].get("dispatch")
        ),
    )
    preview = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/preview",
            headers=HEADERS,
        )
    )["preview"]
    created = _ok(
        client.post(
            f"/projects/{PROJECT_ID}/inspection/full-project-analysis/runs",
            headers={**HEADERS, "Idempotency-Key": "envelope-before-send"},
            json={"snapshotHash": preview["snapshotHash"]},
        )
    )["run"]

    assert sent  # 任务真的发出去了
    # 落库那一刻 run 行已带最终信封——之后本请求不再改这一行
    assert flush_snapshots and flush_snapshots[0] == envelope | {
        "taskId": task_dispatcher.deterministic_task_id(
            "project-analysis", str(created["projectAnalysisRunId"])
        )
    }
    assert created["dispatch"] == flush_snapshots[0]
