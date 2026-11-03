"""多特检院第二阶段：平台管理员开通特检院与院管理员，院管理员只管本院（2026-11-02）。

两个院端到端走一遍：开通 → 院管理员按用户名直接登录（不选单位）→ 首登改密 → 在本院建用户、
建项目 → 两边互相看不到 → 用户名全平台唯一 → 停用后登录和旧令牌都失效 → 未登记的院名登录
不会凭空建出一个院。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo
from libs.security.tenant import configured_tenant_id

client = TestClient(app)
PLATFORM = {"Authorization": "Bearer dev-token-admin"}
GD = "TENANT-GDTJ"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    # 和生产一样不带演示数据：新开的院应当是空的
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_DATA", "false")
    repo.reset()
    monkeypatch.setattr(repo, "postgres_enabled", False)
    monkeypatch.setattr(repo, "sync_postgres", None)
    monkeypatch.setattr(repo, "postgres_dsn", None)
    monkeypatch.setattr(repo, "sqlite_enabled", False)
    monkeypatch.setattr(repo, "sqlite_path", None)
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AICHECK_ALLOW_DEV_TOKENS", "true")
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_USERS", "true")
    monkeypatch.setenv("AICHECK_TENANT_MODE", "shared")
    monkeypatch.delenv("AICHECK_PLATFORM_ADMIN_USERNAMES", raising=False)


def data(response):
    body = response.json()
    assert response.status_code == 200 and body["code"] == 0, body
    return body["data"]


def code_of(response):
    return response.json()["code"]


def bearer(token: str, key: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


def login(username: str, password: str):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def open_gdtj() -> str:
    """开通「广东特检院」，院管理员首登改密后返回他的令牌。"""
    created = data(client.post("/api/platform/institutes", headers=PLATFORM, json={
        "code": "gdtj", "name": "广东特检院", "adminUsername": "gd-admin", "adminName": "广东院管理员",
        "adminPassword": "first-pass"}))["institute"]
    assert created["id"] == GD and created["adminUsernames"] == ["gd-admin"]
    signed = data(login("gd-admin", "first-pass"))  # 不传 tenantId：按用户名找到院
    assert signed["user"]["tenantId"] == GD and signed["user"]["platformAdmin"] is False
    assert signed["user"]["mustChangePassword"] is True
    data(client.post("/api/auth/change-password", headers=bearer(signed["token"]),
                     json={"currentPassword": "first-pass", "newPassword": "gd-secret-1"}))
    return data(login("gd-admin", "gd-secret-1"))["token"]


def test_platform_admin_opens_an_institute_whose_admin_only_sees_their_own():
    platform_user = data(client.post("/api/admin/users", headers={**PLATFORM, "If-Match": "*", "Idempotency-Key": "pu"},
                                     json={"username": "plat-inspector", "name": "平台管理员乙", "role": "admin",
                                           "password": "plat-pass1"}))["user"]
    token = open_gdtj()

    # 院管理员不是平台管理员
    assert code_of(client.get("/api/platform/institutes", headers=bearer(token))) != 0
    assert code_of(client.post("/api/platform/institutes", headers=bearer(token), json={"code": "X", "name": "x"})) != 0

    # 在本院建用户：能登录，而且落在本院
    data(client.post("/api/admin/users", headers={**bearer(token, "gd-u1"), "If-Match": "*"},
                     json={"username": "gd-inspector", "name": "广东监检", "role": "inspection", "password": "gd-pass-1",
                           "orgId": "ORG-GDTJ"}))
    assert data(login("gd-inspector", "gd-pass-1"))["user"]["tenantId"] == GD
    # 用户名全平台唯一：平台院已有的名字不能再用
    clash = client.post("/api/admin/users", headers={**bearer(token, "gd-u2"), "If-Match": "*"},
                        json={"username": platform_user["username"], "name": "撞名", "role": "inspection",
                              "password": "gd-pass-2", "orgId": "ORG-GDTJ"})
    assert code_of(clash) != 0 and "其他单位" in clash.json()["message"]

    # 两边的用户列表互相看不到
    gd_users = {row["username"] for row in data(client.get("/api/admin/users", headers=bearer(token)))["items"]}
    assert {"gd-admin", "gd-inspector"} <= gd_users and "plat-inspector" not in gd_users
    platform_users = {row["username"] for row in data(client.get("/api/admin/users", headers=PLATFORM))["items"]}
    assert "gd-inspector" not in platform_users and "gd-admin" not in platform_users

    # 院管理员建的项目只在本院
    project = data(client.post("/api/projects", headers=bearer(token, "gd-p1"), json={"name": "广东院试点项目"}))
    project_id = (project.get("project") or project)["id"]
    gd_projects = {row["id"] for row in data(client.get("/api/projects", headers=bearer(token)))["items"]}
    assert project_id in gd_projects
    assert project_id not in {row["id"] for row in data(client.get("/api/projects", headers=PLATFORM))["items"]}

    # 平台看得到这个院和它的人数、项目数
    listing = {row["id"]: row for row in data(client.get("/api/platform/institutes", headers=PLATFORM))["items"]}
    assert listing[configured_tenant_id()]["builtin"] is True
    assert listing[GD]["userCount"] == 2 and listing[GD]["projectCount"] == 1


def test_disabling_an_institute_blocks_login_and_existing_tokens_then_enabling_restores():
    token = open_gdtj()
    data(client.post(f"/api/platform/institutes/{GD}/status", headers=PLATFORM, json={"status": "disabled"}))
    rejected = client.get("/api/auth/me", headers=bearer(token)).json()
    assert rejected["data"]["reason"] == "AUTH_REQUIRED" and "停用" in rejected["message"]
    assert code_of(login("gd-admin", "gd-secret-1")) != 0
    data(client.post(f"/api/platform/institutes/{GD}/status", headers=PLATFORM, json={"status": "active"}))
    assert data(login("gd-admin", "gd-secret-1"))["user"]["tenantId"] == GD
    # 平台院不能停用
    assert code_of(client.post(f"/api/platform/institutes/{configured_tenant_id()}/status", headers=PLATFORM,
                               json={"status": "disabled"})) != 0


def test_institute_codes_and_admin_names_cannot_be_reused():
    open_gdtj()
    again = client.post("/api/platform/institutes", headers=PLATFORM,
                        json={"code": "GDTJ", "name": "重复", "adminUsername": "someone"})
    assert code_of(again) != 0
    taken = client.post("/api/platform/institutes", headers=PLATFORM,
                        json={"code": "SCTJ", "name": "四川特检院", "adminUsername": "gd-admin"})
    assert code_of(taken) != 0 and "其他单位" in taken.json()["message"]
    assert code_of(client.post("/api/platform/institutes", headers=PLATFORM,
                               json={"code": "bad code!", "name": "x", "adminUsername": "y"})) != 0


def test_an_unregistered_tenant_name_at_login_does_not_conjure_a_tenant():
    before = set(repo._tenant_states)
    response = client.post("/api/auth/login", json={"username": "admin", "password": "x", "tenantId": "TENANT-GHOST"})
    assert response.json()["code"] != 0
    assert "TENANT-GHOST" not in set(repo._tenant_states) - before


# ── 第三阶段：平台通用规则下发、标准与规则只读、注册链接找得到院 ───────────────

PLATFORM_RULE = {"id": "RULE-PLATFORM-R09", "name": "R09 设计文件检验试验要求", "status": "已发布", "nodeIds": [9],
                 "businessPackId": "engineering_inspection_v1", "version": "v1"}


def test_a_new_institute_gets_the_platform_rules_and_later_updates_by_sync():
    repo.state.setdefault("rule_versions", []).extend([
        dict(PLATFORM_RULE),
        {**PLATFORM_RULE, "id": "RULE-PLATFORM-PROJECT", "projectId": "P-PLATFORM-ONLY"},  # 项目规则不下发
    ])
    open_gdtj()
    from libs import institutes

    with institutes.tenant_scope(GD) as state:
        ids = {row["id"]: row for row in state["rule_versions"]}
    assert set(ids) == {"RULE-PLATFORM-R09"} and ids["RULE-PLATFORM-R09"]["syncedFromPlatform"] is True

    repo.state["rule_versions"].append({**PLATFORM_RULE, "id": "RULE-PLATFORM-R11", "nodeIds": [11]})
    repo.state["rule_versions"] = [row for row in repo.state["rule_versions"] if row["id"] != "RULE-PLATFORM-R09"]
    result = data(client.post("/api/platform/institutes/sync-rules", headers=PLATFORM, json={}))["results"][GD]
    assert result == {"synced": 1, "removed": 1}
    with institutes.tenant_scope(GD) as state:
        assert {row["id"] for row in state["rule_versions"]} == {"RULE-PLATFORM-R11"}


def test_institute_admins_cannot_edit_standards_or_platform_rules():
    token = open_gdtj()
    blocked = client.post("/api/rules/versions", headers=bearer(token, "gd-rule"), json={"name": "自定义规则"})
    assert blocked.json()["code"] != 0 and "平台统一维护" in blocked.json()["message"]
    # 平台自己照常能维护（这里只看没被这条拦下）
    platform = client.post("/api/rules/versions", headers={**PLATFORM, "Idempotency-Key": "p-rule"}, json={"name": "x"})
    assert "平台统一维护" not in platform.json().get("message", "")


def test_registration_links_from_an_institute_land_applicants_in_that_institute():
    token = open_gdtj()
    project = data(client.post("/api/projects", headers=bearer(token, "gd-p"), json={
        "name": "广东院注册试点", "inspectionOrgName": "广东特检院"}))
    project_id = (project.get("project") or project)["id"]
    link = data(client.post(f"/api/projects/{project_id}/registration-links", headers=bearer(token, "gd-link"), json={}))
    assert link["token"].startswith(f"{GD}.")

    # 公开接口不带登录：按链接前缀找到院
    assert data(client.get(f"/api/registration-links/{link['token']}"))["projectId"] == project_id
    applied = data(client.post(f"/api/registration-links/{link['token']}/apply", json={
        "username": "gd-applicant", "role": "inspection", "password": "applicant-1", "displayName": "申请人"}))
    pending = data(client.get(f"/api/projects/{project_id}/registration-requests", headers=bearer(token)))["items"]
    assert [row["id"] for row in pending] == [applied["requestId"]]
    data(client.post(f"/api/projects/{project_id}/registration-requests/{applied['requestId']}/review",
                     headers=bearer(token, "gd-review"), json={"approved": True}))
    # 审核通过的人按用户名直接登进广东院
    assert data(login("gd-applicant", "applicant-1"))["user"]["tenantId"] == GD

    # 平台院的旧格式链接不受影响；伪造一个没登记的院前缀则找不到
    assert client.get("/api/registration-links/TENANT-GHOST.abc").json()["code"] != 0


# ── 第三阶段：标准知识库共用平台的 ─────────────────────────────────────────────

def _seed_platform_knowledge():
    repo.state.setdefault("knowledge_sources", []).extend([
        {"id": "KS-STANDARD-RULES", "name": "标准规范库", "sourceType": "standard", "status": "active"},
        {"id": "KS-PROJECT-FILE", "name": "项目文件知识库", "sourceType": "project-file", "status": "active"},
    ])
    repo.state.setdefault("knowledge_files", []).extend([
        {"id": "KF-STD-1", "sourceId": "KS-STANDARD-RULES", "sourceType": "standard", "fileName": "GB 50184-2011.pdf",
         "status": "active"},
        {"id": "KF-PROJ-1", "sourceId": "KS-PROJECT-FILE", "sourceType": "project-file", "fileName": "平台项目资料.pdf",
         "projectId": "P-PLATFORM-ONLY", "status": "active"},
    ])
    repo.state.setdefault("knowledge_chunks", []).extend([
        {"id": "KC-STD-1", "fileId": "KF-STD-1", "pageNo": 46, "chunkNo": 1, "text": "8.5.7 泄漏性试验应按设计文件的规定进行"},
        {"id": "KC-PROJ-1", "fileId": "KF-PROJ-1", "pageNo": 1, "chunkNo": 1, "text": "平台项目的内部资料"},
    ])


def test_institutes_read_platform_standard_files_but_never_platform_project_files():
    _seed_platform_knowledge()
    token = open_gdtj()
    chunks = data(client.get("/api/knowledge/files/KF-STD-1/chunks", headers=bearer(token), params={"pageNo": 46}))
    assert [row["id"] for row in chunks["items"]] == ["KC-STD-1"]
    leaked = client.get("/api/knowledge/files/KF-PROJ-1/chunks", headers=bearer(token)).json()
    assert leaked["code"] != 0 or not (leaked.get("data") or {}).get("items")
    # 院里读完，本院的数据和上下文都没被换成平台院的
    from libs import institutes

    with institutes.tenant_scope(GD) as state:
        assert not state.get("knowledge_chunks")


def test_institute_review_basis_search_uses_the_platform_standard_library():
    from libs import institutes
    from libs.knowledge_retrieval import retrieve_knowledge_clauses

    _seed_platform_knowledge()
    open_gdtj()
    expected = retrieve_knowledge_clauses(repo.state, query="泄漏性试验 审查依据", top_k=5)
    with institutes.tenant_scope(GD) as state:
        got = retrieve_knowledge_clauses(state, query="泄漏性试验 审查依据", top_k=5)
    assert expected["clauses"] and got["clauses"] == expected["clauses"]  # 非空：真检到了平台的标准
    assert all("KF-PROJ-1" not in str(row) for row in got["clauses"])


def test_a_new_institute_starts_blank_even_when_demo_data_is_on(monkeypatch):
    # 生产 runtime.env 开着演示数据：平台院照旧有演示项目，新开的院必须是空的
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_DATA", "true")
    repo.reset()
    assert data(client.get("/api/projects", headers=PLATFORM))["items"], "平台院应当有演示项目"
    token = open_gdtj()
    assert data(client.get("/api/projects", headers=bearer(token)))["items"] == []
