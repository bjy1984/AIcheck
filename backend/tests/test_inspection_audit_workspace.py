from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo


client = TestClient(app)
PROJECT_ID = "P-2026-HDCP-001"
NODE_ID = 24
EXPECTED_KEYS = [
    "submission",
    "ocr",
    "evidence",
    "ai_review",
    "human_review",
    "report",
    "archive",
]


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def assert_ok(response):
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    return payload["data"]


def item_map(payload: dict) -> dict[str, dict]:
    return {item["key"]: item for item in payload["items"]}


def test_inspection_audit_overview_returns_non_linear_status_matrix() -> None:
    data = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/audit-overview?pageSize=200",
            headers={"X-Role": "inspection"},
        )
    )

    assert data["schemaVersion"] == "InspectionAuditOverview@1.0.0"
    assert data["total"] == data["summary"]["nodeCount"]
    assert data["total"] > 0
    assert list(item_map(data["items"][0])) == EXPECTED_KEYS
    assert sum(data["summary"][status] for status in (
        "not_started",
        "in_progress",
        "needs_attention",
        "failed",
        "completed",
    )) == data["total"] * len(EXPECTED_KEYS)


def test_inspection_audit_workspace_is_read_only_and_contains_grouped_content() -> None:
    before = deepcopy(repo.state)

    data = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/audit-workspace",
            headers={"X-Role": "inspection"},
        )
    )

    assert data["schemaVersion"] == "InspectionAuditWorkspace@1.0.0"
    assert [item["key"] for item in data["items"]] == EXPECTED_KEYS
    assert set(data["content"]) == {
        "submission",
        "ocr",
        "evidence",
        "aiReview",
        "humanReview",
        "report",
        "archive",
    }
    assert repo.state == before


def test_failed_to_start_only_marks_ai_item_failed() -> None:
    repo.state["review_runs"].insert(
        0,
        {
            "id": "RRUN-AUDIT-DIR-FAILED",
            "reviewRunId": "RRUN-AUDIT-DIR-FAILED",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "status": "failed_to_start",
            "failureReason": "workflow unavailable",
            "createdAt": "2099-01-01 00:00:00",
        },
    )

    data = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/audit-workspace",
            headers={"X-Role": "inspection"},
        )
    )
    items = item_map(data)

    assert items["ai_review"]["status"] == "failed"
    assert items["ai_review"]["issues"][0]["code"] == "AI_REVIEW_FAILED_TO_START"
    assert all(item["status"] != "failed" for key, item in items.items() if key != "ai_review")


def test_gap_precheck_does_not_complete_formal_ai_review() -> None:
    repo.state["ai_runs"].insert(
        0,
        {
            "id": "AIRUN-AUDIT-DIR-GAP",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "status": "完成",
            "reviewMode": "gap_precheck",
            "advisoryOnly": True,
            "suggestion": {
                "id": "SUG-AUDIT-DIR-GAP",
                "result": "需人工确认",
                "opinionDraft": "仅缺项预审",
                "confidence": 0.5,
                "manualConfirmItems": [],
            },
            "evidenceLinks": [],
            "finishedAt": "2099-01-01 00:00:00",
        },
    )

    data = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/audit-workspace",
            headers={"X-Role": "inspection"},
        )
    )

    assert item_map(data)["ai_review"]["status"] == "needs_attention"
    assert item_map(data)["ai_review"]["issues"][0]["code"] == "FORMAL_REVIEW_NOT_RUN"


def test_legacy_unverified_archive_is_attention_not_a_cross_item_blocker() -> None:
    repo.state["archive_items"].insert(
        0,
        {
            "id": "ARCH-AUDIT-DIR-LEGACY",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "name": "历史归档.pdf",
            "type": "report",
            "status": "已归档",
            "verificationStatus": "legacy_unverified",
            "updatedAt": "2099-01-01 00:00:00",
        },
    )

    data = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/audit-workspace",
            headers={"X-Role": "inspection"},
        )
    )
    items = item_map(data)

    assert items["archive"]["status"] == "needs_attention"
    assert items["archive"]["relationStatus"] == "unlinked_legacy"
    assert items["ai_review"]["status"] != "needs_attention" or items["ai_review"]["issues"][0]["code"] != "LEGACY_UNVERIFIED"


def test_non_inspection_role_cannot_open_inspection_audit_workspace() -> None:
    response = client.get(
        f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/audit-workspace",
        headers={"X-Role": "contractor"},
    )

    assert response.status_code == 200
    assert response.json()["code"] != 0
    assert response.json()["data"]["reason"] == "FORBIDDEN"
