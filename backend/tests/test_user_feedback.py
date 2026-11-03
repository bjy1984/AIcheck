"""意见反馈：各业务角色提给管理员，管理员看全部、回复、改状态，提交人只看得到自己的。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api import main
from libs.db.repository import repo
from libs.security.actions import required_action_for_request

client = TestClient(main.app)
SUBMIT, MINE, ADMIN = "/api/user-feedback", "/api/user-feedback/mine", "/api/admin/user-feedback"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    repo.reset()
    monkeypatch.setattr(repo, "postgres_enabled", False)
    monkeypatch.setattr(repo, "sync_postgres", None)
    monkeypatch.setattr(repo, "postgres_dsn", None)
    monkeypatch.setattr(repo, "sqlite_enabled", False)
    monkeypatch.setattr(repo, "sqlite_path", None)
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AICHECK_ALLOW_DEV_TOKENS", "true")
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_USERS", "true")


def bearer(role: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer dev-token-{role}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


def data_of(response):
    assert response.status_code == 200 and response.json()["code"] == 0, response.text
    return response.json()["data"]


def submit(role: str, **body):
    payload = {"category": "audit_accuracy", "content": "节点 9 的特性表明明写了检测比例，AI 还说缺。", **body}
    return client.post(SUBMIT, headers=bearer(role), json=payload)


def test_every_business_role_can_submit_and_only_sees_its_own():
    for role in ("inspection", "contractor", "ndt", "owner"):
        feedback = data_of(submit(role, context={"page": "/workbench/x", "projectId": "P-1", "nodeId": 9, "evil": "x"}))["feedback"]
        assert feedback["status"] == "open" and feedback["statusLabel"] == "待处理"
        assert feedback["categoryLabel"] == "审计不准确"
        assert feedback["submittedBy"]["role"] == role
        # 上下文只收白名单字段
        assert feedback["context"] == {"page": "/workbench/x", "projectId": "P-1", "nodeId": "9"}
    mine = data_of(client.get(MINE, headers=bearer("contractor")))["items"]
    assert [item["submittedBy"]["role"] for item in mine] == ["contractor"]
    assert repo.state["user_feedback"][0]["submittedBy"]["role"] == "owner"


def test_submission_is_validated_and_needs_login():
    assert submit("inspection", category="whatever").json()["code"] != 0
    assert submit("inspection", content="  缺 ").json()["code"] != 0
    assert client.post(SUBMIT, json={"category": "bug", "content": "按钮点了没反应"}).json()["code"] == 401
    assert required_action_for_request("POST", SUBMIT) == "feedback:submit"
    assert "feedback:submit" in repo.role_actions("owner")


def test_same_idempotency_key_does_not_create_a_second_record():
    body = {"category": "usability", "content": "上传按钮藏得太深，找了很久。"}
    first = data_of(client.post(SUBMIT, headers=bearer("inspection", "fb-1"), json=body))
    second = data_of(client.post(SUBMIT, headers=bearer("inspection", "fb-1"), json=body))
    assert first["feedback"]["id"] == second["feedback"]["id"]
    assert len(repo.state["user_feedback"]) == 1


def test_admin_lists_filters_replies_and_the_submitter_sees_the_reply():
    feedback_id = data_of(submit("inspection"))["feedback"]["id"]
    data_of(submit("contractor", category="usability", content="资料清单太长，看不出还缺哪几份。"))

    # 业务角色看不了全部、也处理不了
    assert client.get(ADMIN, headers=bearer("inspection")).json()["code"] != 0
    denied = client.post(f"{ADMIN}/{feedback_id}/reply", headers=bearer("inspection"), json={"status": "resolved", "reply": "好"})
    assert denied.json()["code"] != 0

    listing = data_of(client.get(ADMIN, headers=bearer("admin")))
    assert len(listing["items"]) == 2 and listing["statusCounts"]["open"] == 2
    only_accuracy = data_of(client.get(ADMIN, headers=bearer("admin"), params={"category": "audit_accuracy"}))["items"]
    assert [item["id"] for item in only_accuracy] == [feedback_id]

    # 关掉一条要写回复
    bare = client.post(f"{ADMIN}/{feedback_id}/reply", headers=bearer("admin"), json={"status": "resolved"})
    assert bare.json()["code"] != 0
    done = data_of(client.post(f"{ADMIN}/{feedback_id}/reply", headers=bearer("admin"),
                               json={"status": "resolved", "reply": "已修复特性表识别，请重新跑一次 AI 复核。"}))
    assert done["feedback"]["statusLabel"] == "已解决" and done["auditLogId"]

    mine = data_of(client.get(MINE, headers=bearer("inspection")))["items"]
    assert mine[0]["reply"]["content"].startswith("已修复特性表识别")
    assert data_of(client.get(ADMIN, headers=bearer("admin")))["statusCounts"] == {
        "open": 1, "acknowledged": 0, "resolved": 1, "declined": 0}
