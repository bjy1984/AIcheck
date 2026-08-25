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


def _ok(response) -> dict:
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def _seed_history() -> None:
    repo.state["project_review_runs"] = [
        {
            "id": "PRRUN-NEW",
            "projectReviewRunId": "PRRUN-NEW",
            "tenantId": "TENANT-DEFAULT",
            "projectId": PROJECT_ID,
            "triggerType": "manual_full",
            "expectedNodeIds": [1, 2],
            "childReviewRunIds": ["RRUN-1", "RRUN-2"],
            "completedNodeIds": [1],
            "failedNodeIds": [2],
            "status": "partial",
            "createdAt": "2026-08-25T12:00:00Z",
        },
        {
            "id": "PRRUN-OLD",
            "projectReviewRunId": "PRRUN-OLD",
            "tenantId": "TENANT-DEFAULT",
            "projectId": PROJECT_ID,
            "triggerType": "daily_schedule",
            "expectedNodeIds": [1],
            "childReviewRunIds": ["RRUN-OLD"],
            "completedNodeIds": [1],
            "failedNodeIds": [],
            "status": "completed",
            "createdAt": "2026-08-24T12:00:00Z",
        },
        {
            "id": "PRRUN-FOREIGN",
            "projectReviewRunId": "PRRUN-FOREIGN",
            "tenantId": "TENANT-FOREIGN",
            "projectId": PROJECT_ID,
            "expectedNodeIds": [],
            "childReviewRunIds": [],
            "status": "completed",
            "createdAt": "2026-08-26T12:00:00Z",
        },
    ]
    repo.state["review_runs"] = [
        {
            "id": "RRUN-1",
            "reviewRunId": "RRUN-1",
            "tenantId": "TENANT-DEFAULT",
            "projectId": PROJECT_ID,
            "projectReviewRunId": "PRRUN-NEW",
            "nodeId": 1,
            "status": "waiting_human_review",
            "evidenceSnapshotId": "ESNAP-1",
            "evidenceManifestId": "EMAN-1",
            "evidenceShardIds": ["ESHARD-1", "ESHARD-2"],
            "evidenceCoverage": {
                "expectedShardCount": 2,
                "completedShardCount": 2,
                "failedShardCount": 0,
                "coveragePassed": True,
            },
            "findingDrafts": [
                {
                    "id": "FND-1",
                    "severity": "high",
                    "title": "许可范围需重点核查",
                    "sourceEvidenceShardIds": ["ESHARD-1"],
                    "sourceModelAttemptIds": ["MCALL-1"],
                },
                {"id": "FND-2", "severity": "medium", "title": "资料缺项"},
            ],
        },
        {
            "id": "RRUN-2",
            "reviewRunId": "RRUN-2",
            "tenantId": "TENANT-DEFAULT",
            "projectId": PROJECT_ID,
            "projectReviewRunId": "PRRUN-NEW",
            "nodeId": 2,
            "status": "review_incomplete",
            "errorCode": "EVIDENCE_SHARD_PROCESSING_INCOMPLETE",
            "failedEvidenceShardIds": ["ESHARD-4"],
            "evidenceShardIds": ["ESHARD-3", "ESHARD-4"],
            "evidenceCoverage": {
                "expectedShardCount": 2,
                "completedShardCount": 1,
                "failedShardCount": 1,
                "coveragePassed": False,
            },
            "findingDrafts": [],
        },
        {
            "id": "RRUN-OLD",
            "reviewRunId": "RRUN-OLD",
            "tenantId": "TENANT-DEFAULT",
            "projectId": PROJECT_ID,
            "projectReviewRunId": "PRRUN-OLD",
            "nodeId": 1,
            "status": "waiting_human_review",
            "evidenceShardIds": ["ESHARD-OLD"],
            "evidenceCoverage": {
                "expectedShardCount": 1,
                "completedShardCount": 1,
                "failedShardCount": 0,
                "coveragePassed": True,
            },
            "findingDrafts": [],
        },
    ]


def test_project_review_run_list_is_isolated_and_newest_first() -> None:
    _seed_history()

    data = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/project-review-runs",
            headers=HEADERS,
        )
    )

    assert [row["projectReviewRunId"] for row in data["projectReviewRuns"]] == [
        "PRRUN-NEW",
        "PRRUN-OLD",
    ]
    assert data["total"] == 2
    assert data["projectReviewRuns"][0]["summary"]["completion"] == {
        "expectedNodeCount": 2,
        "completedNodeCount": 1,
        "failedNodeCount": 1,
        "pendingNodeCount": 0,
    }


def test_project_review_run_detail_includes_node_results_and_shard_lineage() -> None:
    _seed_history()

    data = _ok(
        client.get(
            f"/projects/{PROJECT_ID}/inspection/project-review-runs/PRRUN-NEW",
            headers=HEADERS,
        )
    )

    summary = data["summary"]
    assert summary["projectReviewRunId"] == "PRRUN-NEW"
    assert summary["priorityReviewNodeIds"] == [1, 2]
    assert summary["commonRisks"] == ["许可范围需重点核查"]
    node1, node2 = summary["nodeSummaries"]
    assert node1["nodeId"] == 1
    assert node1["findingCount"] == 2
    assert node1["highestSeverity"] == "high"
    assert node1["evidenceCoverage"]["coveragePassed"] is True
    assert node1["sourceEvidenceShardIds"] == ["ESHARD-1", "ESHARD-2"]
    assert node1["sourceModelAttemptIds"] == ["MCALL-1"]
    assert node2["status"] == "review_incomplete"
    assert node2["failedEvidenceShardIds"] == ["ESHARD-4"]


def test_project_review_history_hides_foreign_tenant_and_rejects_wrong_role() -> None:
    _seed_history()

    foreign = client.get(
        f"/projects/{PROJECT_ID}/inspection/project-review-runs/PRRUN-FOREIGN",
        headers=HEADERS,
    ).json()
    forbidden = client.get(
        f"/projects/{PROJECT_ID}/inspection/project-review-runs",
        headers={"X-Role": "owner"},
    ).json()

    assert foreign["code"] != 0
    assert forbidden["code"] != 0

