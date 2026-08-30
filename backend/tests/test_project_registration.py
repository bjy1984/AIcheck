"""按项目生成注册链接 → 自选角色注册 → 项目负责人审核通过。

    「根据项目生成注册链接 - 用户通过链接进去选择角色注册 -
      项目负责人在后台审核通过」

## 和上一版组织邀请的关键差别

上一版把角色写死在链接里，理由是「自选角色的链接等于公开提权入口」。
**加了审核这一关之后这个理由不成立了**：审核才是闸门，自选只是填表。

但这带来一条新的硬要求——

## 待审期间绝不能存在可用账号

这是这份用例里最要紧的一条。**不走「先建用户再标 pending」**：
那种做法只要哪个查询忘了过滤 pending，人就登进来了，而且不会报错。
这里根本不建 user 记录，批准的那一刻才创建。

没有账号，就没有「忘了过滤」的可能。

## 反向用例照旧比正向多

发链接、审核都只能由**这个项目**的负责人做。
「甲公司的负责人能审乙项目的注册」是这条流程最可能出的越权。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from apps.api import project_registration_routes as registration
from apps.api.main import app
from libs.db.repository import STATE_COLLECTIONS, repo
from libs.security.auth import issue_token

client = TestClient(app)

PROJECT_A = "P-REG-TEST-A"
PROJECT_B = "P-REG-TEST-B"
GOOD_PASSWORD = "Aa!234567890x"
ROLE_ORG_FIELDS = {
    "inspection": "inspectionOrgName",
    "contractor": "contractorOrgName",
    "ndt": "ndtOrgName",
    "owner": "ownerOrgName",
}
PROJECT_A_ORGS = {
    "inspectionOrgName": "甲监检单位",
    "contractorOrgName": "甲施工单位",
    "ndtOrgName": "甲无损检测单位",
    "ownerOrgName": "甲建设单位",
}


@pytest.fixture(autouse=True)
def _fixture():
    projects = repo.state.setdefault("projects", [])
    projects[:0] = [
        {"id": PROJECT_A, "name": "甲项目", **PROJECT_A_ORGS},
        {
            "id": PROJECT_B,
            "name": "乙项目",
            "inspectionOrgName": "乙监检单位",
            "contractorOrgName": "乙施工单位",
            "ndtOrgName": "乙无损检测单位",
            "ownerOrgName": "乙建设单位",
        },
    ]
    org_units = repo.state.setdefault("admin_config", {}).setdefault("orgUnits", [])
    test_orgs = [
        {"id": f"ORG-REG-{role.upper()}", "name": org_name, "type": role, "status": "启用"}
        for role, org_name in (
            ("inspection", PROJECT_A_ORGS["inspectionOrgName"]),
            ("contractor", PROJECT_A_ORGS["contractorOrgName"]),
            ("ndt", PROJECT_A_ORGS["ndtOrgName"]),
            ("owner", PROJECT_A_ORGS["ownerOrgName"]),
        )
    ]
    org_units[:0] = test_orgs
    users = repo.state.setdefault("users", [])
    users[:0] = [
        {"id": "U-ADMIN-REG", "username": "admin-registration", "role": "admin"},
        {"id": "U-LEAD-A", "username": "lead-a", "role": "inspection"},
        {"id": "U-LEAD-B", "username": "lead-b", "role": "inspection"},
        {"id": "U-PLAIN-I", "username": "plain-inspection", "role": "inspection"},
        {"id": "U-PLAIN", "username": "plain-a", "role": "contractor"},
    ]
    members = repo.state.setdefault("project_members", [])
    # role / status 是**项目授权中间件**要看的字段（routes.py 的
    # project_scope_error）。缺了它们请求在到达端点之前就被 403 掉了——
    # 也就是说项目级授权其实有两道：中间件管「是不是这个项目的人」，
    # 端点里的 _guard 管「是不是这个项目的负责人」。
    members[:0] = [
        {
            "id": "PM-A",
            "projectId": PROJECT_A,
            "userId": "U-LEAD-A",
            "role": "inspection",
            "status": "启用",
            "isProjectLeader": True,
        },
        {
            "id": "PM-B",
            "projectId": PROJECT_B,
            "userId": "U-LEAD-B",
            "role": "inspection",
            "status": "启用",
            "isProjectLeader": True,
        },
        {
            "id": "PM-PI",
            "projectId": PROJECT_A,
            "userId": "U-PLAIN-I",
            "role": "inspection",
            "status": "启用",
        },
        {
            "id": "PM-P",
            "projectId": PROJECT_A,
            "userId": "U-PLAIN",
            "role": "contractor",
            "status": "启用",
        },
    ]
    yield
    repo.state["projects"] = [p for p in projects if p.get("id") not in {PROJECT_A, PROJECT_B}]
    repo.state["users"] = [
        u
        for u in repo.state["users"]
        if u.get("id")
        not in {"U-ADMIN-REG", "U-LEAD-A", "U-LEAD-B", "U-PLAIN-I", "U-PLAIN"}
    ]
    repo.state["users"] = [
        u for u in repo.state["users"] if not str(u.get("username", "")).startswith("applicant")
    ]
    repo.state["project_members"] = [
        m for m in repo.state["project_members"] if m.get("projectId") not in {PROJECT_A, PROJECT_B}
    ]
    repo.state["admin_config"]["orgUnits"] = [
        org
        for org in repo.state["admin_config"].get("orgUnits", [])
        if org.get("id") not in {item["id"] for item in test_orgs}
    ]
    repo.state["project_invitations"] = []
    repo.state["registration_requests"] = []


def _headers(username: str) -> dict[str, str]:
    user = next(u for u in repo.state["users"] if u["username"] == username)
    return {"Authorization": f"Bearer {issue_token(user)}"}


def _make_link(project_id: str = PROJECT_A, username: str = "lead-a") -> dict:
    return client.post(
        f"/api/projects/{project_id}/registration-links", json={}, headers=_headers(username)
    ).json()


def _apply(token: str, username: str = "applicant-1", role: str = "contractor") -> dict:
    return client.post(
        f"/api/registration-links/{token}/apply",
        json={"username": username, "role": role, "password": GOOD_PASSWORD},
    ).json()


# ---- 生成链接 -------------------------------------------------------------


def test_项目负责人能生成链接且链接不绑角色():
    body = _make_link()
    assert body["code"] == 0, body
    assert body["data"]["token"]
    assert body["data"]["projectId"] == PROJECT_A
    # 角色由注册者自选，链接里不写死
    assert "role" not in body["data"]
    assert set(body["data"]["selectableRoles"]) == set(registration.SELECTABLE_ROLES)
    assert body["data"]["expiresAt"], "没有过期时间的链接是长期后门"
    assert body["data"]["maxUses"], "没有次数上限的话，链接外流后可以被灌注册"


def test_每个注册链接有稳定且不公开的持久化身份():
    first = _make_link()
    second = _make_link()
    first_token = first["data"]["token"]
    second_token = second["data"]["token"]
    first_invite = next(
        item for item in repo.state["project_invitations"] if item["token"] == first_token
    )
    second_invite = next(
        item for item in repo.state["project_invitations"] if item["token"] == second_token
    )
    collection = STATE_COLLECTIONS["project_invitations"]

    first_id = repo.persistence_object_id(collection, first_invite, 0)
    second_id = repo.persistence_object_id(collection, second_invite, 0)

    assert first_id != "0"
    assert second_id != "0"
    assert first_id != second_id
    assert "id" not in first["data"]
    assert "id" not in second["data"]


def test_普通成员不能生成链接():
    assert _make_link(username="plain-a")["code"] != 0


@pytest.mark.parametrize(
    ("username", "role", "expected"),
    [
        ("admin-registration", "admin", True),
        ("lead-a", "inspection", True),
        ("plain-inspection", "inspection", False),
        ("plain-a", "contractor", False),
    ],
)
def test_workbench_context_exposes_authoritative_registration_capability(
    username: str,
    role: str,
    expected: bool,
):
    response = client.get(
        f"/api/projects/{PROJECT_A}/workbench/context?role={role}",
        headers=_headers(username),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["canManageRegistration"] is expected


def test_workbench_context_project_includes_etag_for_guarded_mutations():
    """施工方从 context 取当前项目；没有 etag 就无法提交 If-Match。"""
    response = client.get(
        f"/api/projects/{PROJECT_A}/workbench/context?role=contractor",
        headers=_headers("plain-a"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["project"]["revision"] == 1
    assert body["data"]["project"]["etag"] == f'W/"project-{PROJECT_A}-r1"'


def test_别的项目的负责人不能给本项目发链接():
    """「甲项目的负责人能给乙项目发链接」是这条流程最可能出的越权。"""
    assert _make_link(project_id=PROJECT_B, username="lead-a")["code"] != 0


# ---- 注册 -----------------------------------------------------------------


def test_未登录也能看链接并拿到可选角色():
    token = _make_link()["data"]["token"]
    body = client.get(f"/api/registration-links/{token}").json()
    assert body["code"] == 0
    assert body["data"]["projectName"] == "甲项目"
    assert set(body["data"]["selectableRoles"]) == set(registration.SELECTABLE_ROLES)


@pytest.mark.parametrize("prefix", ["", "/api"])
def test_registration_link_inspect_and_apply_are_public_when_auth_is_required(monkeypatch, prefix):
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    token = _make_link()["data"]["token"]

    inspected = client.get(f"{prefix}/registration-links/{token}")
    assert inspected.status_code == 200
    assert inspected.json()["code"] == 0

    applied = client.post(
        f"{prefix}/registration-links/{token}/apply",
        json={
            "username": f"applicant-public-{prefix.removeprefix('/') or 'root'}",
            "role": "contractor",
            "password": GOOD_PASSWORD,
        },
    )
    assert applied.status_code == 200
    assert applied.json()["code"] == 0
    assert applied.json()["data"]["status"] == "待审核"


def test_anonymous_cannot_manage_registration_when_auth_is_required(monkeypatch):
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    token = _make_link()["data"]["token"]
    request_id = client.post(
        f"/api/registration-links/{token}/apply",
        json={
            "username": "applicant-anonymous-management",
            "role": "contractor",
            "password": GOOD_PASSWORD,
        },
        headers=_headers("lead-a"),
    ).json()["data"]["requestId"]

    responses = [
        client.post(f"/api/projects/{PROJECT_A}/registration-links", json={}),
        client.post(f"/api/projects/{PROJECT_A}/registration-links/{token}/disable"),
        client.get(f"/api/projects/{PROJECT_A}/registration-requests"),
        client.post(
            f"/api/projects/{PROJECT_A}/registration-requests/{request_id}/review",
            json={"approved": True},
        ),
    ]

    assert [response.json()["code"] for response in responses] == [401, 401, 401, 401]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/registration-links/not-an-apply-route"),
        ("GET", "/api/registration-links/token/apply"),
        ("GET", "/api/registration-links/token/extra"),
        ("POST", "/api/registration-links/token/apply/extra"),
    ],
)
def test_registration_public_auth_bypass_requires_exact_method_and_path(monkeypatch, method, path):
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")

    response = client.request(method, path)

    assert response.json()["code"] == 401


def test_提交申请后不产生任何可用账号():
    """**这份用例里最要紧的一条。**

    先建用户再标 pending 的话，只要哪个查询忘了过滤 pending，
    人就登进来了，而且不会报错。这里根本不建 user 记录。
    """
    token = _make_link()["data"]["token"]
    body = _apply(token)
    assert body["code"] == 0, body
    assert body["data"]["status"] == "待审核"
    assert "token" not in body["data"], "回了令牌——待审的人不该拿到任何凭证"
    assert not any(
        u.get("username") == "applicant-1" for u in repo.state["users"]
    ), "待审期间就建了账号，忘一次过滤人就登进来了"


def test_不能自选管理员角色():
    token = _make_link()["data"]["token"]
    for role in ("admin", "fde", "随便写的"):
        assert _apply(token, username=f"applicant-{role}", role=role)["code"] != 0


def test_弱口令被拒并且用后台同一套规则():
    token = _make_link()["data"]["token"]
    body = client.post(
        f"/api/registration-links/{token}/apply",
        json={"username": "applicant-weak", "role": "contractor", "password": "123456"},
    ).json()
    assert body["code"] != 0
    assert not any(r.get("username") == "applicant-weak" for r in repo.state["registration_requests"])


def test_同一用户名不能重复申请():
    token = _make_link()["data"]["token"]
    assert _apply(token, username="applicant-dup")["code"] == 0
    assert _apply(token, username="applicant-dup")["code"] != 0


@pytest.mark.parametrize("_attempt", range(5))
def test_两个链接并发申请同一用户名只创建一条待审申请(_attempt):
    first_token = _make_link()["data"]["token"]
    second_token = _make_link()["data"]["token"]
    username = "applicant-concurrent-apply"
    barrier = Barrier(2)

    def apply(token: str) -> dict:
        barrier.wait()
        return _apply(token, username=username)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(apply, first_token), executor.submit(apply, second_token)]
        responses = [future.result() for future in futures]

    assert sum(response["code"] == 0 for response in responses) == 1, responses
    requests = [
        item for item in repo.state["registration_requests"] if item.get("username") == username
    ]
    assert len(requests) == 1


def test_停用后链接立刻失效():
    """发出去的东西必须能收回来。"""
    token = _make_link()["data"]["token"]
    client.post(
        f"/api/projects/{PROJECT_A}/registration-links/{token}/disable", headers=_headers("lead-a")
    )
    assert client.get(f"/api/registration-links/{token}").json()["code"] != 0
    assert _apply(token, username="applicant-after-disable")["code"] != 0


def test_超过次数上限后失效():
    body = client.post(
        f"/api/projects/{PROJECT_A}/registration-links",
        json={"maxUses": 1},
        headers=_headers("lead-a"),
    ).json()
    token = body["data"]["token"]
    assert _apply(token, username="applicant-first")["code"] == 0
    assert _apply(token, username="applicant-second")["code"] != 0


# ---- 审核 -----------------------------------------------------------------


def test_通过之后才创建账号并加入项目():
    token = _make_link()["data"]["token"]
    request_id = _apply(token, username="applicant-ok")["data"]["requestId"]
    body = client.post(
        f"/api/projects/{PROJECT_A}/registration-requests/{request_id}/review",
        json={"approved": True},
        headers=_headers("lead-a"),
    ).json()
    assert body["code"] == 0, body
    user = next((u for u in repo.state["users"] if u.get("username") == "applicant-ok"), None)
    assert user, "批准了却没建账号"
    assert user["role"] == "contractor", "没有用申请人自选的角色"
    assert any(
        m.get("projectId") == PROJECT_A and m.get("userId") == user["id"]
        for m in repo.state["project_members"]
    ), "批准了却没加进项目，人登进来什么也看不到"


@pytest.mark.parametrize("role", list(ROLE_ORG_FIELDS))
def test_批准四种角色后创建完整授权并立即看见项目(role):
    username = f"applicant-grant-{role}"
    token = _make_link()["data"]["token"]
    request_id = _apply(token, username=username, role=role)["data"]["requestId"]

    reviewed = client.post(
        f"/api/projects/{PROJECT_A}/registration-requests/{request_id}/review",
        json={"approved": True},
        headers=_headers("lead-a"),
    ).json()
    assert reviewed["code"] == 0, reviewed

    user = next(item for item in repo.state["users"] if item.get("username") == username)
    member = next(
        item
        for item in repo.state["project_members"]
        if item.get("projectId") == PROJECT_A and item.get("userId") == user["id"]
    )
    project = repo.require_project(PROJECT_A)
    assert member["orgName"] == project[ROLE_ORG_FIELDS[role]]
    assert member["orgId"]
    assert member["nodeScope"]
    assert member["actions"]
    assert "project:view" in member["actions"]
    assert member["revision"] == 1
    assert member["updatedAt"]

    login = client.post(
        "/api/auth/login", json={"username": username, "password": GOOD_PASSWORD}
    ).json()
    assert login["code"] == 0, login
    projects = client.get(
        f"/api/workbench/projects?role={role}",
        headers={"Authorization": f"Bearer {login['data']['token']}"},
    ).json()
    assert projects["code"] == 0, projects
    assert any(item["id"] == PROJECT_A for item in projects["data"])


def test_批准时缺少角色对应项目组织则拒绝且不创建账号():
    project = repo.require_project(PROJECT_A)
    project["ownerOrgName"] = ""
    token = _make_link()["data"]["token"]
    request_id = _apply(token, username="applicant-no-owner-org", role="owner")["data"][
        "requestId"
    ]

    reviewed = client.post(
        f"/api/projects/{PROJECT_A}/registration-requests/{request_id}/review",
        json={"approved": True},
        headers=_headers("lead-a"),
    ).json()

    assert reviewed["code"] != 0
    assert not any(
        item.get("username") == "applicant-no-owner-org" for item in repo.state["users"]
    )
    record = next(item for item in repo.state["registration_requests"] if item["id"] == request_id)
    assert record["status"] == "待审核"


def test_口令沿用申请时定的那个():
    """审核人不该知道、也不该代设别人的口令。"""
    token = _make_link()["data"]["token"]
    request_id = _apply(token, username="applicant-pwd")["data"]["requestId"]
    record = next(r for r in repo.state["registration_requests"] if r["id"] == request_id)
    client.post(
        f"/api/projects/{PROJECT_A}/registration-requests/{request_id}/review",
        json={"approved": True},
        headers=_headers("lead-a"),
    )
    user = next(u for u in repo.state["users"] if u.get("username") == "applicant-pwd")
    assert user["passwordHash"] == record["passwordHash"]


def test_拒绝必须写理由():
    """不写的话申请人只看到「被拒了」，不知道要改什么。"""
    token = _make_link()["data"]["token"]
    request_id = _apply(token, username="applicant-rej")["data"]["requestId"]
    without = client.post(
        f"/api/projects/{PROJECT_A}/registration-requests/{request_id}/review",
        json={"approved": False},
        headers=_headers("lead-a"),
    ).json()
    assert without["code"] != 0

    with_reason = client.post(
        f"/api/projects/{PROJECT_A}/registration-requests/{request_id}/review",
        json={"approved": False, "reason": "该单位不在本项目参建名单内"},
        headers=_headers("lead-a"),
    ).json()
    assert with_reason["code"] == 0
    assert not any(u.get("username") == "applicant-rej" for u in repo.state["users"])


def test_同一申请不能审两次():
    """重复审批会重复建账号。"""
    token = _make_link()["data"]["token"]
    request_id = _apply(token, username="applicant-twice")["data"]["requestId"]
    url = f"/api/projects/{PROJECT_A}/registration-requests/{request_id}/review"
    assert client.post(url, json={"approved": True}, headers=_headers("lead-a")).json()["code"] == 0
    assert client.post(url, json={"approved": True}, headers=_headers("lead-a")).json()["code"] != 0
    assert len([u for u in repo.state["users"] if u.get("username") == "applicant-twice"]) == 1


def test_审核时发现用户名和成员已由另一申请创建则稳定冲突():
    token = _make_link()["data"]["token"]
    username = "applicant-existing-identity"
    request_id = _apply(token, username=username)["data"]["requestId"]
    existing_user = {
        "id": "USER-EXISTING-IDENTITY",
        "username": username,
        "role": "contractor",
        "status": "启用",
    }
    existing_member = {
        "id": "PM-EXISTING-IDENTITY",
        "projectId": PROJECT_A,
        "userId": existing_user["id"],
        "role": "contractor",
        "status": "启用",
    }
    repo.state["users"].insert(0, existing_user)
    repo.state["project_members"].insert(0, existing_member)
    url = f"/api/projects/{PROJECT_A}/registration-requests/{request_id}/review"

    first = client.post(url, json={"approved": True}, headers=_headers("lead-a")).json()
    replay = client.post(url, json={"approved": True}, headers=_headers("lead-a")).json()

    assert first["code"] != 0
    assert replay["code"] == first["code"]
    assert replay["message"] == first["message"]
    assert len([item for item in repo.state["users"] if item.get("username") == username]) == 1
    assert len(
        [
            item
            for item in repo.state["project_members"]
            if item.get("projectId") == PROJECT_A
            and item.get("userId") == existing_user["id"]
        ]
    ) == 1
    record = next(item for item in repo.state["registration_requests"] if item["id"] == request_id)
    assert record["status"] == "待审核"


def test_两个待审申请并发批准同一用户名只创建一个登录身份():
    token = _make_link()["data"]["token"]
    username = "applicant-two-pending"
    first_request_id = _apply(token, username=username)["data"]["requestId"]
    first_record = next(
        item for item in repo.state["registration_requests"] if item["id"] == first_request_id
    )
    second_request_id = "REG-DUPLICATE-PENDING"
    repo.state["registration_requests"].insert(
        0, {**first_record, "id": second_request_id, "createdAt": "2026-08-22 12:00:00"}
    )
    barrier = Barrier(2)
    headers = _headers("lead-a")

    def approve(request_id: str) -> dict:
        barrier.wait()
        return client.post(
            f"/api/projects/{PROJECT_A}/registration-requests/{request_id}/review",
            json={"approved": True},
            headers=headers,
        ).json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(approve, first_request_id),
            executor.submit(approve, second_request_id),
        ]
        responses = [future.result() for future in futures]

    assert sum(response["code"] == 0 for response in responses) == 1, responses
    users = [item for item in repo.state["users"] if item.get("username") == username]
    assert len(users) == 1
    members = [
        item
        for item in repo.state["project_members"]
        if item.get("projectId") == PROJECT_A and item.get("userId") == users[0]["id"]
    ]
    assert len(members) == 1


@pytest.mark.parametrize("_attempt", range(5))
def test_两个审核人并发批准只创建一个账号和一个项目成员(_attempt):
    token = _make_link()["data"]["token"]
    username = "applicant-concurrent-review"
    request_id = _apply(token, username=username)["data"]["requestId"]
    url = f"/api/projects/{PROJECT_A}/registration-requests/{request_id}/review"
    barrier = Barrier(2)
    headers = _headers("lead-a")

    def approve() -> dict:
        barrier.wait()
        return client.post(url, json={"approved": True}, headers=headers).json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(approve), executor.submit(approve)]
        responses = [future.result() for future in futures]

    assert sum(response["code"] == 0 for response in responses) == 1, responses
    users = [item for item in repo.state["users"] if item.get("username") == username]
    assert len(users) == 1
    members = [
        item
        for item in repo.state["project_members"]
        if item.get("projectId") == PROJECT_A and item.get("userId") == users[0]["id"]
    ]
    assert len(members) == 1


def test_别的项目的负责人不能审核():
    token = _make_link()["data"]["token"]
    request_id = _apply(token, username="applicant-cross")["data"]["requestId"]
    body = client.post(
        f"/api/projects/{PROJECT_A}/registration-requests/{request_id}/review",
        json={"approved": True},
        headers=_headers("lead-b"),
    ).json()
    assert body["code"] != 0
    assert not any(u.get("username") == "applicant-cross" for u in repo.state["users"])


def test_列表不外泄口令哈希():
    token = _make_link()["data"]["token"]
    _apply(token, username="applicant-list")
    body = client.get(
        f"/api/projects/{PROJECT_A}/registration-requests", headers=_headers("lead-a")
    ).json()
    assert body["code"] == 0
    assert body["data"]["items"]
    for item in body["data"]["items"]:
        assert "passwordHash" not in item, "口令哈希出了接口"


def test_只能看到本项目的申请():
    token = _make_link()["data"]["token"]
    _apply(token, username="applicant-scope")
    body = client.get(
        f"/api/projects/{PROJECT_B}/registration-requests", headers=_headers("lead-b")
    ).json()
    assert all(item["projectId"] == PROJECT_B for item in body["data"]["items"])
