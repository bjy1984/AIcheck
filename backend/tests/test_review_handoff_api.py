from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from test_review_workstations import run_for

from apps.api.main import app
from libs.db.repository import STATE_COLLECTIONS, repo

client = TestClient(app)
PROJECT = "P-2026-HDCP-001"
HEADERS = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "true")
    repo.reset()
    repo.postgres_enabled = False
    repo.sqlite_enabled = False
    repo.state["review_handoffs"] = []
    for node, name in ((24, "SOURCE"), (35, "TARGET")):
        run = run_for(node)
        run.update(id=name, projectId=PROJECT, tenantId="TENANT-DEFAULT", inputHash=name, inputDocumentVersionIds=[])
        repo.state["review_runs"].append(run)


def payload():
    return {"sourceRunId": "SOURCE", "targetRunId": "TARGET", "kind": "collaboration",
            "subject": {"objectType": "weld", "objectId": "W-1", "repairRound": 0},
            "payload": {"request": "核对返修后检测"}, "evidenceRefs": []}


def test_save_read_deduplicate_and_preserve_stale_handoff():
    assert STATE_COLLECTIONS["review_handoffs"] == "review_handoffs"
    url = f"/api/projects/{PROJECT}/review-handoffs"
    before = deepcopy(repo.state["review_runs"])
    saved = client.post(url, headers=HEADERS, json=payload()).json()
    assert saved["code"] == 0, saved
    record = saved["data"]
    assert record["draft"]["authoritative"] is False
    again = client.post(url, headers=HEADERS, json=payload()).json()
    assert again["data"] == record
    assert len(repo.state["review_handoffs"]) == 1
    detail = client.get(f"{url}/{record['id']}", headers=HEADERS).json()
    assert detail["data"]["validation"]["status"] == "current_draft"
    assert repo.state["review_runs"] == before
    repo.find_one("review_runs", "SOURCE")["inputHash"] = "NEW"
    stale = client.get(f"{url}/{record['id']}", headers=HEADERS).json()
    assert stale["data"]["validation"]["status"] == "stale_or_invalid"
    assert repo.find_one("review_handoffs", record["id"]) == record


@pytest.mark.parametrize("case", ["foreign_project", "foreign_tenant", "missing_run", "outside_evidence", "identity_field", "role", "disabled"])
def test_handoff_rejects_unauthorized_or_invalid_creation(case, monkeypatch):
    body = payload()
    headers = HEADERS
    if case == "foreign_project":
        repo.find_one("review_runs", "TARGET")["projectId"] = "OTHER"
    elif case == "foreign_tenant":
        repo.find_one("review_runs", "TARGET")["tenantId"] = "OTHER"
    elif case == "missing_run":
        body["sourceRunId"] = "MISSING"
    elif case == "outside_evidence":
        body["evidenceRefs"] = [{"documentVersionId": "UNAUTHORIZED", "pageNo": 1}]
    elif case == "identity_field":
        body["authoritative"] = True
    elif case == "role":
        headers = {"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"}
    elif case == "disabled":
        monkeypatch.delenv("AICHECK_WORKSTATIONS_ENABLED")
    response = client.post(f"/api/projects/{PROJECT}/review-handoffs", headers=headers, json=body).json()
    assert response["code"] != 0, response
    assert repo.state["review_handoffs"] == []


def test_saved_draft_survives_sqlite_repository_reload(tmp_path, monkeypatch):
    from libs.db.repository import InMemoryRepository

    monkeypatch.setenv("AICHECK_SQLITE_DISABLE", "false")
    path = tmp_path / "handoff.sqlite3"
    try:
        repo.configure_sqlite(path)
        repo.flush_to_sqlite()
        result = client.post(f"/api/projects/{PROJECT}/review-handoffs", headers=HEADERS, json=payload()).json()
        assert result["code"] == 0, result
        restored = InMemoryRepository(seed=False)
        restored.configure_sqlite(path)
        restored.load_from_sqlite(selected_state_keys={"review_handoffs"}, tenant_id="TENANT-DEFAULT")
        assert restored.find_one("review_handoffs", result["data"]["id"]) == result["data"]
    finally:
        repo.sqlite_enabled = False
        repo.sqlite_path = None


def test_read_and_save_require_both_node_scopes_and_current_document_access():
    url = f"/api/projects/{PROJECT}/review-handoffs"
    saved = client.post(url, headers=HEADERS, json=payload()).json()["data"]
    member = next(row for row in repo.state["project_members"] if row.get("projectId") == PROJECT and row.get("userId") == HEADERS["X-User-Id"])
    before = deepcopy(repo.state["review_handoffs"])
    original_scope = member.get("nodeScope")
    member["nodeScope"] = [24]
    for response in (client.get(f"{url}/{saved['id']}", headers=HEADERS), client.post(url, headers=HEADERS, json=payload())):
        assert response.json()["code"] != 0, response.text
    member["nodeScope"] = original_scope
    repo.find_one("review_runs", "SOURCE")["inputDocumentVersionIds"] = ["UNAVAILABLE"]
    response = client.get(f"{url}/{saved['id']}", headers=HEADERS)
    assert response.json()["code"] != 0, response.text
    assert repo.state["review_handoffs"] == before


def test_list_filters_permissions_before_pagination_and_supports_run_filters():
    url = f"/api/projects/{PROJECT}/review-handoffs"
    visible_ids = set()
    for weld in ("W-1", "W-2"):
        body = payload()
        body["subject"]["objectId"] = weld
        response = client.post(url, headers=HEADERS, json=body).json()
        assert response["code"] == 0, response
        visible_ids.add(response["data"]["id"])
    other = run_for(36)
    other.update(id="TARGET-OTHER", projectId=PROJECT, tenantId="TENANT-DEFAULT", inputHash="other", inputDocumentVersionIds=[])
    repo.state["review_runs"].append(other)
    response = client.post(url, headers=HEADERS, json={**payload(), "targetRunId": "TARGET-OTHER"}).json()
    assert response["code"] == 0, response
    member = next(row for row in repo.state["project_members"] if row.get("projectId") == PROJECT and row.get("userId") == HEADERS["X-User-Id"])
    member["nodeScope"] = [24, 35]
    pages = [client.get(url, headers=HEADERS, params={"page": page, "pageSize": 1}).json()["data"] for page in (1, 2, 3)]
    assert [page["total"] for page in pages] == [2, 2, 2]
    assert {row["id"] for page in pages for row in page["items"]} == visible_ids
    assert pages[2]["items"] == []
    for filters, count in (({"sourceRunId": "SOURCE"}, 2), ({"targetRunId": "TARGET"}, 2), ({"targetRunId": "TARGET-OTHER"}, 0), ({"sourceRunId": "UNKNOWN"}, 0)):
        result = client.get(url, headers=HEADERS, params=filters).json()["data"]
        assert result["total"] == count
    invalid = client.get(url, headers=HEADERS, params={"pageSize": 101}).json()
    assert invalid["code"] != 0 and invalid["data"]["reason"] == "VALIDATION_ERROR", invalid


def test_removed_source_input_does_not_bypass_frozen_document_read_permission():
    version_id = "HANDOFF-SENSITIVE-VERSION"
    document = {"id": "HANDOFF-SENSITIVE", "projectId": PROJECT, "tenantId": "TENANT-DEFAULT",
                "currentVersionId": version_id, "fileName": "sensitive.pdf"}
    repo.state["documents"].append(document)
    repo.state["versions"].append({"id": version_id, "documentId": document["id"], "tenantId": "TENANT-DEFAULT"})
    source = repo.find_one("review_runs", "SOURCE")
    source["inputDocumentVersionIds"] = [version_id]
    url = f"/api/projects/{PROJECT}/review-handoffs"
    result = client.post(url, headers=HEADERS, json=payload()).json()
    assert result["code"] == 0, result
    record = result["data"]
    assert record["draft"]["source"]["documentVersionIds"] == [version_id]
    source["inputDocumentVersionIds"] = []
    document["tenantId"] = "TENANT-OTHER"
    assert client.get(f"{url}/{record['id']}", headers=HEADERS).json()["code"] != 0
    assert client.get(url, headers=HEADERS).json()["data"]["total"] == 0
    assert repo.find_one("review_handoffs", record["id"]) == record
