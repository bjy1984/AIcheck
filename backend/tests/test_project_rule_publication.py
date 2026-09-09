from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo

client = TestClient(app)
PROJECT = "P-2026-HDCP-001"
HEADERS = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
BASE = f"/api/projects/{PROJECT}/rules/versions"


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    repo.reset()
    monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "true")
    monkeypatch.setenv("AICHECK_STRICT_PRODUCTION", "true")


def ok(response):
    value = response.json()
    assert value["code"] == 0, value
    return value["data"]


def draft():
    return ok(client.post(BASE, headers=HEADERS, json={"inspectionItem": "项目审查", "standardText": "原准则", "nodeIds": [24]}))["rule"]


def publish(rule, key):
    url = f"{BASE}/{rule['id']}"
    body = {"reason": "已核对工程规则"}
    preview = ok(client.post(f"{url}/publish-preview", headers=HEADERS, json=body))
    body["previewId"] = preview["previewId"]
    headers = {**HEADERS, "If-Match": rule["etag"], "Idempotency-Key": key}
    response = ok(client.post(f"{url}/publish", headers=headers, json=body))
    assert ok(client.post(f"{url}/publish", headers=headers, json=body)) == response
    return response["rule"]


def test_project_publish_and_rollback_preview_real_direction_and_single_scope():
    first = publish(draft(), "first-publish")
    second = ok(client.post(f"{BASE}/{first['id']}/fork", headers=HEADERS, json={"standardText": "新准则"}))["rule"]
    preview = ok(client.post(f"{BASE}/{second['id']}/publish-preview", headers=HEADERS, json={"reason": "更新"}))
    change = next(row for row in preview["impact"]["changes"] if row["field"] == "standardText")
    assert change["before"] == "原准则" and change["after"] == "新准则"
    second = publish(second, "second-publish")
    assert repo.find_one("rule_versions", first["id"])["status"] == "已回滚"
    body = {"reason": "恢复原版本", "targetVersionId": first["id"]}
    preview = ok(client.post(f"{BASE}/{second['id']}/rollback-preview", headers=HEADERS, json=body))
    change = next(row for row in preview["impact"]["changes"] if row["field"] == "standardText")
    assert change["before"] == "新准则" and change["after"] == "原准则"
    response = ok(client.post(f"{BASE}/{second['id']}/rollback", headers={**HEADERS, "If-Match": second["etag"], "Idempotency-Key": "rollback"},
                              json={**body, "previewId": preview["previewId"]}))
    assert response["target"]["id"] == first["id"] and response["target"]["status"] == "已发布"
    assert ok(client.post(f"{BASE}/{second['id']}/rollback", headers={**HEADERS, "If-Match": second["etag"], "Idempotency-Key": "rollback"},
                          json={**body, "previewId": preview["previewId"]})) == response


def test_project_publication_rejects_missing_preview_foreign_rule_and_incomplete_conditions():
    rule = draft()
    before = deepcopy(repo.state["rule_versions"])
    assert client.post(f"{BASE}/{rule['id']}/publish", headers={**HEADERS, "If-Match": rule["etag"]}, json={"reason": "missing"}).json()["code"] != 0
    platform = next(row for row in before if not row.get("projectId"))
    assert client.post(f"{BASE}/{platform['id']}/publish-preview", headers=HEADERS, json={"reason": "forbidden"}).json()["code"] != 0
    assert repo.state["rule_versions"] == before
    repo.find_one("rule_versions", rule["id"])["executionConditions"] = {"schemaVersion": "rule-conditions-v1", "checks": [
        {"id": "C", "field": "x", "operator": "eq", "expected": 1}]}
    assert client.post(f"{BASE}/{rule['id']}/publish-preview", headers=HEADERS, json={"reason": "not verified"}).json()["code"] != 0


def test_stale_preview_or_etag_cannot_change_rule_and_repreview_recovers():
    rule = draft()
    body = {"reason": "核对更新"}
    preview = ok(client.post(f"{BASE}/{rule['id']}/publish-preview", headers=HEADERS, json=body))
    current = repo.find_one("rule_versions", rule["id"])
    current["revision"] += 1
    failed = client.post(f"{BASE}/{rule['id']}/publish", headers={**HEADERS, "If-Match": rule["etag"], "Idempotency-Key": "stale"},
                         json={**body, "previewId": preview["previewId"]})
    assert failed.json()["code"] != 0
    assert current["status"] == "草稿"
    refreshed = next(row for row in ok(client.get(BASE, headers=HEADERS))["items"] if row["id"] == rule["id"])
    assert publish(refreshed, "refreshed")["status"] == "已发布"


def test_project_preview_is_bound_to_actor_and_cannot_publish_as_construction():
    rule = draft()
    body = {"reason": "核对更新"}
    preview = ok(client.post(f"{BASE}/{rule['id']}/publish-preview", headers=HEADERS, json=body))
    response = client.post(f"{BASE}/{rule['id']}/publish", headers={"X-Role": "construction", "X-User-Id": "USER-CONSTRUCTION-001", "If-Match": rule["etag"]},
                           json={**body, "previewId": preview["previewId"]})
    assert response.json()["code"] != 0
    assert repo.find_one("rule_versions", rule["id"])["status"] == "草稿"


def test_rollback_cannot_activate_a_draft():
    first = publish(draft(), "one")
    second = ok(client.post(f"{BASE}/{first['id']}/fork", headers=HEADERS, json={"standardText": "新准则"}))["rule"]
    body = {"reason": "不能以回滚绕过发布", "targetVersionId": second["id"]}
    preview = ok(client.post(f"{BASE}/{first['id']}/rollback-preview", headers=HEADERS, json=body))
    response = client.post(f"{BASE}/{first['id']}/rollback", headers={**HEADERS, "If-Match": first["etag"], "Idempotency-Key": "draft-rollback"},
                           json={**body, "previewId": preview["previewId"]})
    assert response.json()["code"] != 0
    assert repo.find_one("rule_versions", first["id"])["status"] == "已发布"
    assert repo.find_one("rule_versions", second["id"])["status"] == "草稿"


def test_publish_preview_covers_every_replaced_rule_and_final_status():
    first = publish(draft(), "one")
    existing = deepcopy(repo.find_one("rule_versions", first["id"]))
    existing.update(id="OTHER-PUBLISHED", ruleKey="different-key", standardText="另一条准则")
    repo.state["rule_versions"].append(existing)
    new = ok(client.post(f"{BASE}/{first['id']}/fork", headers=HEADERS, json={"standardText": "合并准则"}))["rule"]
    impact = ok(client.post(f"{BASE}/{new['id']}/publish-preview", headers=HEADERS, json={"reason": "合并"}))["impact"]
    texts = [change for change in impact["changes"] if change["field"] == "standardText"]
    assert {row["before"] for row in texts} == {"原准则", "另一条准则"}
    assert {row["after"] for row in texts} == {"合并准则"}
    assert all(change["after"] == "已发布" for change in impact["changes"] if change["field"] == "status")
    publish(new, "merged")
    active = [row["id"] for row in repo.state["rule_versions"] if row.get("projectId") == PROJECT and row.get("status") == "已发布"]
    assert active == [new["id"]]
