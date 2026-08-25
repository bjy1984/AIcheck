from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo
from libs.db.seed import PROJECT_ID
from libs.integrations import task_dispatcher


client = TestClient(app)
INSPECTION_HEADERS = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def _ok(response) -> dict:
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def test_get_returns_disabled_project_scoped_default_policy() -> None:
    policy = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/auto-review-policy",
            headers=INSPECTION_HEADERS,
        )
    )["policy"]

    assert policy["projectId"] == PROJECT_ID
    assert policy["enabled"] is False
    assert policy["etag"]


def test_inspection_can_enable_policy_with_etag_and_idempotency() -> None:
    current = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/auto-review-policy",
            headers=INSPECTION_HEADERS,
        )
    )["policy"]
    headers = {
        **INSPECTION_HEADERS,
        "If-Match": current["etag"],
        "Idempotency-Key": "enable-auto-review-once",
    }
    payload = {
        "enabled": True,
        "triggerModes": ["ocr_mounted", "daily_schedule"],
        "dailyTime": "03:30",
        "timezone": "Asia/Shanghai",
    }

    first = _ok(
        client.put(
            f"/projects/{PROJECT_ID}/inspection/auto-review-policy",
            headers=headers,
            json=payload,
        )
    )["policy"]
    second = _ok(
        client.put(
            f"/projects/{PROJECT_ID}/inspection/auto-review-policy",
            headers=headers,
            json=payload,
        )
    )["policy"]

    assert first["enabled"] is True
    assert first["dailyTime"] == "03:30"
    assert first["reviewMode"] == "gap_precheck"
    assert second["revision"] == first["revision"]
    assert len(repo.state["auto_review_policies"]) == 1


def test_policy_update_rejects_missing_or_stale_etag() -> None:
    current = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/auto-review-policy",
            headers=INSPECTION_HEADERS,
        )
    )["policy"]
    missing = client.put(
        f"/projects/{PROJECT_ID}/inspection/auto-review-policy",
        headers=INSPECTION_HEADERS,
        json={"enabled": True},
    ).json()
    stale = client.put(
        f"/projects/{PROJECT_ID}/inspection/auto-review-policy",
        headers={**INSPECTION_HEADERS, "If-Match": 'W/"auto-review-policy-stale-r99"'},
        json={"enabled": True},
    ).json()

    assert missing["code"] != 0
    assert stale["code"] != 0
    assert current["revision"] == 1


def test_owner_and_contractor_cannot_change_auto_review_policy() -> None:
    current = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/auto-review-policy",
            headers=INSPECTION_HEADERS,
        )
    )["policy"]
    for role in ("owner", "contractor"):
        response = client.put(
            f"/projects/{PROJECT_ID}/inspection/auto-review-policy",
            headers={"X-Role": role, "If-Match": current["etag"]},
            json={"enabled": True},
        )
        assert response.json()["code"] != 0


def test_policy_isolated_between_projects() -> None:
    other_project_id = "P-2026-GDLNG-002"
    current = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/auto-review-policy",
            headers=INSPECTION_HEADERS,
        )
    )["policy"]
    _ok(
        client.put(
            f"/projects/{PROJECT_ID}/inspection/auto-review-policy",
            headers={**INSPECTION_HEADERS, "If-Match": current["etag"]},
            json={"enabled": True},
        )
    )

    other = _ok(
        client.get(
            f"/projects/{other_project_id}/inspection/auto-review-policy",
            headers=INSPECTION_HEADERS,
        )
    )["policy"]

    assert other["projectId"] == other_project_id
    assert other["enabled"] is False


def test_status_reports_pending_candidates_and_project_runs() -> None:
    repo.state["auto_review_candidates"].append(
        {
            "id": "ARC-1",
            "tenantId": "TENANT-DEFAULT",
            "projectId": PROJECT_ID,
            "nodeId": 1,
            "status": "pending",
        }
    )
    repo.state["project_review_runs"].append(
        {
            "id": "PRRUN-1",
            "tenantId": "TENANT-DEFAULT",
            "projectId": PROJECT_ID,
            "status": "running",
            "childReviewRunIds": ["RRUN-AUTO-1", "RRUN-AUTO-2"],
        }
    )
    repo.state["review_runs"] = [
        {
            "reviewRunId": "RRUN-AUTO-1",
            "projectId": PROJECT_ID,
            "nodeId": 1,
            "status": "running",
            "evidenceCoverage": {
                "expectedShardCount": 3,
                "completedShardCount": 2,
                "failedShardCount": 0,
            },
        },
        {
            "reviewRunId": "RRUN-AUTO-2",
            "projectId": PROJECT_ID,
            "nodeId": 2,
            "status": "review_incomplete",
            "errorCode": "EVIDENCE_SHARD_PROCESSING_INCOMPLETE",
            "failedEvidenceShardIds": ["ESHARD-4"],
            "evidenceCoverage": {
                "expectedShardCount": 2,
                "completedShardCount": 1,
                "failedShardCount": 1,
            },
        },
    ]

    status = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/auto-review-status",
            headers=INSPECTION_HEADERS,
        )
    )

    assert status["pendingNodeCount"] == 1
    assert status["runningProjectRunCount"] == 1
    assert status["runningNodeReviewCount"] == 1
    assert status["reviewIncompleteNodeCount"] == 1
    assert status["shardProgress"] == {
        "expectedShardCount": 5,
        "completedShardCount": 3,
        "failedShardCount": 1,
    }
    assert status["latestFailure"] == {
        "reviewRunId": "RRUN-AUTO-2",
        "nodeId": 2,
        "errorCode": "EVIDENCE_SHARD_PROCESSING_INCOMPLETE",
        "failedEvidenceShardIds": ["ESHARD-4"],
    }


def test_manual_full_review_creates_parent_and_node_child_runs(monkeypatch) -> None:
    repo.state["node_evidence_links"] = []
    document, version = repo.create_document(PROJECT_ID, "设计许可证.pdf", "application/pdf")
    repo.apply_ocr_result(
        document["id"],
        version["id"],
        {
            "status": "success",
            "artifactHash": "sha256:license",
            "fields": [],
            "tables": [],
            "seals": [],
            "fragments": [
                {
                    "id": "FRAG-LICENSE",
                    "pageNo": 1,
                    "text": "许可证编号TS1844171-2028，工业管道GC1覆盖GC2。",
                    "bbox": [1, 2, 30, 40],
                    "confidence": 0.99,
                }
            ],
        },
    )
    repo.state["node_evidence_links"].append(
        {
            "id": "NEL-AUTO-MANUAL-1",
            "projectId": PROJECT_ID,
            "nodeId": 1,
            "documentId": document["id"],
            "documentVersionId": version["id"],
            "materialTypeCode": "design_license",
            "requiredType": "必传",
            "supportStatus": "命中",
            "matchedEvidenceItems": ["许可证编号"],
            "manualStatus": "confirmed",
            "revision": 1,
        }
    )
    monkeypatch.setattr(
        task_dispatcher,
        "ai_recheck_dispatch_readiness",
        lambda: {"ready": True, "mode": "test", "statusReason": "test_dispatch"},
    )
    monkeypatch.setattr(
        task_dispatcher,
        "dispatch_ai_recheck",
        lambda project_id, node_id, run_id: {"mode": "test", "taskId": f"TEST-{run_id}"},
    )

    result = _ok(
        client.post(
            f"/projects/{PROJECT_ID}/inspection/auto-review/run",
            headers={**INSPECTION_HEADERS, "Idempotency-Key": "manual-full-once"},
        )
    )

    parent = result["projectReviewRun"]
    assert parent["triggerType"] == "manual_full"
    assert parent["expectedNodeIds"] == [1]
    assert len(parent["childAiRunIds"]) == 1
    child = repo.find_one("ai_runs", parent["childAiRunIds"][0])
    assert child["projectReviewRunId"] == parent["projectReviewRunId"]
    assert child["reviewMode"] == "gap_precheck"
    assert child["advisoryOnly"] is True
