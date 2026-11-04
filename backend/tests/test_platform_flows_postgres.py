"""多特检院与意见反馈审批在真实 PostgreSQL 上走一遍（2026-11-04，预发布检查）。

其他特检院测试都关掉了数据库（test_platform_institutes 的夹具），跨院落库检查只在生产跑——
11-04 开通特检院连续三次在生产报 Cross-tenant persistence。这里接真库：每个请求收尾都走真实的
落库和院标记检查，最后从库里重新加载核对。本机没有测试库时跳过；CI（backend-quality.yml）带
PostgreSQL 服务，会跑。
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import InMemoryRepository, repo
from libs.security.auth import DEFAULT_INITIAL_PASSWORD
from scripts.migrate_backend import apply_migrations

pytestmark = pytest.mark.skipif(
    not os.getenv("AICHECK_TEST_POSTGRES_URL"),
    reason="AICHECK_TEST_POSTGRES_URL is required for PostgreSQL integration tests",
)

client = TestClient(app)
PLATFORM = {"Authorization": "Bearer dev-token-admin"}
TENANT = "TENANT-PGT"


def ok(response) -> dict:
    body = response.json()
    assert response.status_code == 200 and body.get("code") == 0, body
    return body["data"]


def keyed(headers: dict, key: str) -> dict:
    return {**headers, "Idempotency-Key": key}


def test_开通院_反馈审批_AI修复_口径_删除院_全程按真库落库(isolated_postgres_url: str, monkeypatch) -> None:
    apply_migrations(isolated_postgres_url)
    for name, value in {"AICHECK_ENABLE_DEMO_DATA": "false", "AICHECK_ENABLE_DEMO_USERS": "true",
                        "AICHECK_REQUIRE_AUTH": "true", "AICHECK_ALLOW_DEV_TOKENS": "true",
                        "AICHECK_TENANT_MODE": "shared"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("AICHECK_PLATFORM_ADMIN_USERNAMES", raising=False)
    original = (repo.state, dict(repo._persistence_baseline), dict(repo._singleton_baseline),
                dict(repo._idempotency_baseline))
    reloaded: InMemoryRepository | None = None
    try:
        repo.reset()
        repo.configure_sync_postgres(isolated_postgres_url)
        # 平台院要有一条通用规则：开通时会复制过去（生产第三次就是在这一步报错）
        repo.state["rule_versions"] = [{"id": "RV-PG-1", "ruleId": "R24", "status": "published"}]
        repo.apply_tenant_scope()
        repo.flush_to_sync_postgres(selected_state_keys={"rule_versions"}, selected_singleton_keys=set())

        ok(client.post("/api/platform/institutes", headers=keyed(PLATFORM, "i1"),
                       json={"code": "PGT", "name": "真库测试院", "adminUsername": "pg-admin"}))
        ok(client.post(f"/api/platform/institutes/{TENANT}/admins", headers=keyed(PLATFORM, "i2"),
                       json={"username": "pg-admin-2"}))
        ok(client.post("/api/platform/institutes/sync-rules", headers=keyed(PLATFORM, "i3"), json={}))

        first = ok(client.post("/api/auth/login", json={"username": "pg-admin", "password": DEFAULT_INITIAL_PASSWORD}))
        assert first["user"]["tenantId"] == TENANT
        ok(client.post("/api/auth/change-password", headers={"Authorization": f"Bearer {first['token']}"},
                       json={"currentPassword": DEFAULT_INITIAL_PASSWORD, "newPassword": "pg-secret-1"}))
        institute = {"Authorization": f"Bearer {ok(client.post('/api/auth/login', json={'username': 'pg-admin', 'password': 'pg-secret-1'}))['token']}"}

        feedback_id = ok(client.post("/api/user-feedback", headers=keyed(institute, "f1"),
                                     json={"category": "bug", "content": "真库测试：总览很慢"}))["feedback"]["id"]
        task_id = ok(client.post(f"/api/admin/user-feedback/{feedback_id}/escalate", headers=keyed(institute, "f2"),
                                 json={"scope": "public"}))["taskId"]
        def act(verb: str, body: dict, key: str) -> dict:
            return ok(client.post(f"/api/platform/improvement-tasks/{task_id}/{verb}", headers=keyed(PLATFORM, key), json=body))

        act("approve", {"title": "总览慢", "taskStatement": "修", "acceptanceCriteria": "过"}, "t1")
        claim_id = act("claim", {"agent": "ci"}, "t2")["task"]["claim"]["id"]
        act("submit", {"prUrl": "https://example.com/pr/1", "tests": "ok", "claimId": claim_id}, "t3")
        act("status", {"status": "deployed"}, "t4")
        assert ok(client.post(f"/api/user-feedback/{feedback_id}/confirm", headers=keyed(institute, "f3"),
                              json={"resolved": True}))["taskStatus"] == "closed"

        ok(client.put("/api/admin/review-policies/standard_not_yet_effective_on_review_date",
                      headers=keyed(institute, "p1"), json={"value": "failed"}))
        ok(client.put("/api/platform/review-policy-defaults/certificate_expired_without_construction_period",
                      headers=keyed(PLATFORM, "p2"), json={"value": "human_review_required"}))
        ok(client.delete(f"/api/platform/institutes/{TENANT}", headers=keyed(PLATFORM, "d1")))

        # 从库里重新加载：每样东西都落在它该在的院
        repo.close_sync_postgres()
        reloaded = InMemoryRepository(seed=False)
        reloaded.configure_sync_postgres(isolated_postgres_url)
        reloaded.load_from_sync_postgres(tenant_id=TENANT)
        assert [row["id"] for row in reloaded.state["rule_versions"]] == ["RV-PG-1"]
        feedback = next(row for row in reloaded.state["user_feedback"] if row["id"] == feedback_id)
        assert feedback["status"] == "resolved" and feedback["tenantId"] == TENANT
        assert reloaded.state["admin_config"]["reviewPolicies"] == {"standard_not_yet_effective_on_review_date": "failed"}
        assert all(user["status"] == "停用" for user in reloaded.state["users"]), "删院后院内账号全停用"
        reloaded.load_from_sync_postgres()
        platform_state = reloaded.state
        task = next(row for row in platform_state["improvement_tasks"] if row["id"] == task_id)
        assert task["status"] == "closed" and task["sources"][0]["sourceTenantId"] == TENANT
        assert next(row for row in platform_state["institutes"] if row["id"] == TENANT)["status"] == "deleted"
        assert platform_state["admin_config"]["reviewPolicyDefaults"] == {
            "certificate_expired_without_construction_period": "human_review_required"}
    finally:
        if reloaded is not None:
            reloaded.close_sync_postgres()
        repo.close_sync_postgres()
        repo.postgres_dsn = None
        repo.postgres_enabled = False
        repo.state, repo._persistence_baseline, repo._singleton_baseline, repo._idempotency_baseline = original


def test_合并_不采纳_仍有问题重开_再确认关闭_都按真库落库(isolated_postgres_url: str, monkeypatch) -> None:
    """2026-11-04 审计第三组：真库测试原来只走主流程；合并、不采纳、提交人说仍有问题重新打开都没在真库上跑过。"""
    apply_migrations(isolated_postgres_url)
    for name, value in {"AICHECK_ENABLE_DEMO_DATA": "false", "AICHECK_ENABLE_DEMO_USERS": "true",
                        "AICHECK_REQUIRE_AUTH": "true", "AICHECK_ALLOW_DEV_TOKENS": "true",
                        "AICHECK_TENANT_MODE": "shared"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("AICHECK_PLATFORM_ADMIN_USERNAMES", raising=False)
    original = (repo.state, dict(repo._persistence_baseline), dict(repo._singleton_baseline),
                dict(repo._idempotency_baseline))
    reloaded: InMemoryRepository | None = None
    try:
        repo.reset()
        repo.configure_sync_postgres(isolated_postgres_url)
        ok(client.post("/api/platform/institutes", headers=keyed(PLATFORM, "i1"),
                       json={"code": "PGT", "name": "真库测试院", "adminUsername": "pg-admin"}))
        first = ok(client.post("/api/auth/login", json={"username": "pg-admin", "password": DEFAULT_INITIAL_PASSWORD}))
        ok(client.post("/api/auth/change-password", headers={"Authorization": f"Bearer {first['token']}"},
                       json={"currentPassword": DEFAULT_INITIAL_PASSWORD, "newPassword": "pg-secret-1"}))
        institute = {"Authorization": f"Bearer {ok(client.post('/api/auth/login', json={'username': 'pg-admin', 'password': 'pg-secret-1'}))['token']}"}

        def feedback(content: str, key: str) -> str:
            return ok(client.post("/api/user-feedback", headers=keyed(institute, key),
                                  json={"category": "bug", "content": content}))["feedback"]["id"]

        def escalate(feedback_id: str, key: str) -> str:
            return ok(client.post(f"/api/admin/user-feedback/{feedback_id}/escalate", headers=keyed(institute, key),
                                  json={"scope": "public"}))["taskId"]

        def act(task_id: str, verb: str, body: dict, key: str) -> dict:
            return ok(client.post(f"/api/platform/improvement-tasks/{task_id}/{verb}", headers=keyed(PLATFORM, key), json=body))

        main_feedback, dup_feedback, declined_feedback = (feedback("总览加载很慢", "f1"), feedback("总览打开也很慢", "f2"),
                                                          feedback("想要换一个皮肤", "f3"))
        main_task, dup_task, declined_task = escalate(main_feedback, "e1"), escalate(dup_feedback, "e2"), escalate(declined_feedback, "e3")
        act(dup_task, "merge", {"intoTaskId": main_task}, "m1")
        act(declined_task, "decline", {"reason": "院级配置，在院里改"}, "d1")
        act(main_task, "approve", {"title": "总览慢", "taskStatement": "修", "acceptanceCriteria": "过"}, "a1")
        for round_no in (1, 2):
            claim_id = act(main_task, "claim", {"agent": "ci"}, f"c{round_no}")["task"]["claim"]["id"]
            act(main_task, "submit", {"prUrl": f"https://example.com/pr/{round_no}", "tests": "ok", "claimId": claim_id}, f"s{round_no}")
            act(main_task, "status", {"status": "deployed"}, f"u{round_no}")
            if round_no == 1:
                ok(client.post(f"/api/user-feedback/{main_feedback}/confirm", headers=keyed(institute, "k1"),
                               json={"resolved": False, "note": "还是慢"}))
        for feedback_id, key in ((main_feedback, "k2"), (dup_feedback, "k3")):
            ok(client.post(f"/api/user-feedback/{feedback_id}/confirm", headers=keyed(institute, key), json={"resolved": True}))

        repo.close_sync_postgres()
        reloaded = InMemoryRepository(seed=False)
        reloaded.configure_sync_postgres(isolated_postgres_url)
        reloaded.load_from_sync_postgres(tenant_id=TENANT)
        statuses = {row["id"]: row["status"] for row in reloaded.state["user_feedback"]}
        assert statuses == {main_feedback: "resolved", dup_feedback: "resolved", declined_feedback: "declined"}
        reloaded.load_from_sync_postgres()
        tasks = {row["id"]: row for row in reloaded.state["improvement_tasks"]}
        assert tasks[main_task]["status"] == "closed" and tasks[dup_task]["status"] == "merged"
        assert tasks[declined_task]["status"] == "declined"
        assert "还是慢" in tasks[main_task]["reopenNote"]
        assert all(entry["by"] == "提交人" for entry in tasks[main_task]["history"] if "提交人" in entry["action"])
    finally:
        if reloaded is not None:
            reloaded.close_sync_postgres()
        repo.close_sync_postgres()
        repo.postgres_dsn = None
        repo.postgres_enabled = False
        repo.state, repo._persistence_baseline, repo._singleton_baseline, repo._idempotency_baseline = original
