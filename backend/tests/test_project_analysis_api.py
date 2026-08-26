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
    assert repo.state["audit_logs"][0]["objectType"] == "ProjectAnalysisRun"


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
