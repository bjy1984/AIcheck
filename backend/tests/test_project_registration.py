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

import pytest
from fastapi.testclient import TestClient

from apps.api import project_registration_routes as registration
from apps.api.main import app
from libs.db.repository import repo
from libs.security.auth import issue_token

client = TestClient(app)

PROJECT_A = "P-REG-TEST-A"
PROJECT_B = "P-REG-TEST-B"
GOOD_PASSWORD = "Aa!234567890x"


@pytest.fixture(autouse=True)
def _fixture():
    projects = repo.state.setdefault("projects", [])
    projects[:0] = [
        {"id": PROJECT_A, "name": "甲项目", "contractorOrgName": "甲施工单位"},
        {"id": PROJECT_B, "name": "乙项目", "contractorOrgName": "乙施工单位"},
    ]
    users = repo.state.setdefault("users", [])
    users[:0] = [
        {"id": "U-LEAD-A", "username": "lead-a", "role": "inspection"},
        {"id": "U-LEAD-B", "username": "lead-b", "role": "inspection"},
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
        u for u in repo.state["users"] if u.get("id") not in {"U-LEAD-A", "U-LEAD-B", "U-PLAIN"}
    ]
    repo.state["users"] = [
        u for u in repo.state["users"] if not str(u.get("username", "")).startswith("applicant")
    ]
    repo.state["project_members"] = [
        m for m in repo.state["project_members"] if m.get("projectId") not in {PROJECT_A, PROJECT_B}
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


def test_普通成员不能生成链接():
    assert _make_link(username="plain-a")["code"] != 0


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
