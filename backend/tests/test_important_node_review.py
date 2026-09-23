from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api import routes as api
from apps.api.main import app
from libs.db.repository import repo
from libs.db.seed import PROJECT_ID
from libs.important_node_review import NODE_IDS, SKILL_ROOT, recommend_nodes, skill_catalog
from libs.important_review_runtime import attach_important_review, important_review_prompt

client = TestClient(app)
HEADERS = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
PREFIX = f"/api/projects/{PROJECT_ID}/inspection/important-review"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    repo.reset()
    monkeypatch.setattr(repo, "postgres_enabled", False)
    monkeypatch.setattr(repo, "sync_postgres", None)
    monkeypatch.setattr(repo, "postgres_dsn", None)
    monkeypatch.setattr(repo, "sqlite_enabled", False)
    monkeypatch.setattr(repo, "sqlite_path", None)
    monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "true")


def data(response):
    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0, response.text
    return response.json()["data"]


def test_catalog_is_complete_and_matches_maintained_document():
    assert {row["nodeId"] for row in skill_catalog()} == set(NODE_IDS)
    source = Path(__file__).resolve().parents[2] / "docs/业务节点描述v3.md"
    assert source.read_text() == (SKILL_ROOT / "references/business-nodes-v3.md").read_text()
    result = data(client.get(PREFIX, headers=HEADERS))
    assert result["enabled"] is True
    assert len(result["nodes"]) == 12
    assert all(node["sections"] and node["version"] for node in result["nodes"])


def test_recommend_unbound_and_multi_node_content_without_inferring_completeness():
    docs = [{"id": "D", "currentVersionId": "V", "fileName": "综合资料.pdf"}]
    parsed = [{"documentVersionId": "V", "fragments": [{"text": "焊工资格 焊接工艺 WPS"}]}]
    nodes = recommend_nodes(skill_catalog(), docs, parsed, [])
    assert {24, 25, 26} <= {row["nodeId"] for row in nodes if row["recommended"]}
    assert "完整性需审查确认" in next(row for row in nodes if row["nodeId"] == 24)["message"]
    assert not next(row for row in nodes if row["nodeId"] == 13)["recommended"]
    assert "适用性待确认" in next(row for row in nodes if row["nodeId"] == 13)["message"]
    assert not any(row["recommended"] for row in recommend_nodes(skill_catalog(), docs, [{"documentVersionId": "OTHER", "text": "焊工"}], []))


def test_frozen_skill_is_server_owned_and_reaches_prompt():
    run = {"nodeId": 24, "inputDocumentVersionIds": ["V"]}
    attach_important_review(run, {"importantNodeReview": True, "importantReviewSnapshot": {"content": "FAKE"}})
    assert "平台" in run["importantReviewSnapshot"]["content"]
    assert "FAKE" not in run["importantReviewSnapshot"]["content"]
    assert important_review_prompt(run)["importantNodeReview"] == run["importantReviewSnapshot"]
    assert important_review_prompt({}) == {}


@pytest.mark.parametrize("role,user", [("contractor", "USER-CONTRACTOR-001"), ("owner", "USER-OWNER-001"), ("ndt", "USER-NDT-001")])
def test_other_roles_cannot_read_or_start(role, user):
    headers = {"X-Role": role, "X-User-Id": user}
    assert client.get(PREFIX, headers=headers).json()["code"] != 0
    assert client.post(PREFIX + "/nodes/24/runs", headers=headers, json={"inputDocumentVersionIds": ["V"]}).json()["code"] != 0


def test_missing_or_unknown_files_are_rejected_before_dispatch():
    before = deepcopy(repo.state["ai_runs"])
    response = client.post(PREFIX + "/analyze", headers=HEADERS, json={"inputDocumentVersionIds": ["FOREIGN"]})
    assert response.json()["code"] != 0
    response = client.post(PREFIX + "/nodes/24/runs", headers=HEADERS, json={"inputDocumentVersionIds": ["FOREIGN"]})
    assert response.json()["code"] != 0
    assert repo.state["ai_runs"] == before


def test_node_whitelist_and_client_rule_override_are_rejected():
    for path, body in [("/nodes/1/runs", {"inputDocumentVersionIds": ["V"]}),
                       ("/nodes/24/runs", {"inputDocumentVersionIds": ["V"], "importantReviewSnapshot": {}})]:
        assert client.post(PREFIX + path, headers=HEADERS, json=body).json()["code"] != 0


def test_generic_selection_rejects_invalid_important_review_before_freezing():
    from apps.api.review_input_selection import (
        ReviewInputSelectionError,
        resolve_review_input_selection,
    )
    for node_id, body in [(1, {"importantNodeReview": True, "inputDocumentVersionIds": ["V"]}),
                          (24, {"importantNodeReview": True})]:
        with pytest.raises(ReviewInputSelectionError):
            resolve_review_input_selection(None, None, PROJECT_ID, node_id, body)


def test_new_endpoint_reuses_existing_dispatch_contract(monkeypatch):
    captured = {}
    def dispatch(request, project, node, body, key, role):
        captured.update(project=project, node=node, body=body, key=key)
        from libs.contracts.responses import ok
        return ok({"runId": "AI-TEST"}, request)
    monkeypatch.setattr(api, "ai_recheck", dispatch)
    assert data(client.post(PREFIX + "/nodes/24/runs", headers={**HEADERS, "Idempotency-Key": "important-test"},
                            json={"inputDocumentVersionIds": ["V"]}))["runId"] == "AI-TEST"
    assert captured["body"] == {"inputDocumentVersionIds": ["V"], "reviewMode": "gap_precheck",
                                "auditInputMode": "ocr_llm", "importantNodeReview": True}
    assert captured["key"] == "important-test"


def test_authenticated_member_scope_and_revocation_are_enforced(monkeypatch):
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    logged_in = data(client.post("/api/auth/login", json={"username": "inspection", "password": "anyuekeji.123"}))
    headers = {"Authorization": "Bearer " + logged_in["token"]}
    member = next(row for row in repo.state["project_members"]
                  if row.get("projectId") == PROJECT_ID and row.get("userId") == HEADERS["X-User-Id"])
    member["nodeScope"] = [24]
    assert [row["nodeId"] for row in data(client.get(PREFIX, headers=headers))["nodes"]] == [24]
    assert client.post(PREFIX + "/nodes/4/runs", headers=headers,
                       json={"inputDocumentVersionIds": ["V"]}).json()["code"] != 0
    repo.state["project_members"].remove(member)
    assert client.get(PREFIX, headers=headers).json()["code"] != 0
    assert client.get(PREFIX + "/runs", headers=headers).json()["code"] != 0


def test_unavailable_dispatch_never_substitutes_local_summary_for_skill(monkeypatch):
    listing = data(client.get(f"/api/projects/{PROJECT_ID}/documents", headers=HEADERS))
    document = next(row for row in listing["items"] if row.get("bodyUploaded"))
    monkeypatch.setattr(api.task_dispatcher, "ai_recheck_dispatch_readiness", lambda: {"ready": False})
    monkeypatch.setattr(api, "local_gap_precheck_fallback_policy", lambda: {"allowed": True})
    before = deepcopy(repo.state["ai_runs"])
    response = client.post(PREFIX + "/nodes/24/runs", headers={**HEADERS, "Idempotency-Key": "unavailable-skill"},
                           json={"inputDocumentVersionIds": [document["currentVersionId"]]})
    assert response.status_code == 409
    assert repo.state["ai_runs"] == before


def test_unbound_file_start_freezes_rule_and_versions_and_is_idempotent(monkeypatch):
    # Use a visible submitted project file, then remove every persistent node relation.
    listing = data(client.get(f"/api/projects/{PROJECT_ID}/documents", headers=HEADERS))
    document = next(row for row in listing["items"] if row.get("bodyUploaded"))
    document_id, version_id = document["id"], document["currentVersionId"]
    stored = repo.find_one("documents", document_id)
    stored["poolSubmissionStatus"] = "已提交"
    stored["poolSubmittedAt"] = "2026-09-22 00:00:00"
    repo.state["bindings"] = [row for row in repo.state["bindings"] if row.get("documentId") != document_id]
    repo.state["node_evidence_links"] = [row for row in repo.state["node_evidence_links"] if row.get("documentId") != document_id]
    before = deepcopy(repo.state["bindings"])
    analyzed = data(client.post(PREFIX + "/analyze", headers=HEADERS, json={"inputDocumentVersionIds": [version_id]}))
    assert len(analyzed["nodes"]) == 12
    calls = []
    monkeypatch.setattr(api.task_dispatcher, "ai_recheck_dispatch_readiness", lambda: {"ready": True})
    def dispatch(project, node, run_id, **kwargs):
        calls.append(kwargs)
        return {"taskId": "TASK-TEST", "status": "queued"}
    monkeypatch.setattr(api.task_dispatcher, "dispatch_ai_recheck", dispatch)
    headers = {**HEADERS, "Idempotency-Key": "unbound-important-test"}
    first = data(client.post(PREFIX + "/nodes/24/runs", headers=headers, json={"inputDocumentVersionIds": [version_id]}))
    second = data(client.post(PREFIX + "/nodes/24/runs", headers=headers, json={"inputDocumentVersionIds": [version_id]}))
    assert first["runId"] == second["runId"]
    assert calls == [{"force_async": True}]
    run = repo.find_one("ai_runs", first["runId"])
    assert run["inputDocumentVersionIds"] == [version_id]
    assert run["importantReviewSnapshot"]["nodeId"] == 24
    assert run["advisoryOnly"] is True
    assert repo.state["bindings"] == before
    listed = data(client.get(PREFIX + "/runs", headers=HEADERS))["items"]
    assert listed[0]["id"] == first["runId"]
    assert listed[0]["rule"]["version"] == run["importantReviewSnapshot"]["version"]
    assert listed[0]["atomicCheckOutcomes"] == []
    stored["currentVersionId"] = "NEW-VERSION"
    assert data(client.get(PREFIX + "/runs", headers=HEADERS))["items"][0]["documentsChanged"] is True
