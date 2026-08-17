"""组织内邀请注册与权限下放（0817 第 4、5 条）。

## 这是本轮唯一有安全后果的改动

前面几条改错了最多是显示不对。**这一条改错了是越权**：
A 组织的负责人能改到 B 组织的人，或者把自己提成系统管理员。

所以这份用例里**反向用例比正向用例多**——「能做什么」好验，
「不能做什么」不验就等于没有。

## 动作层挡不住这件事

动作层按角色授权，只知道你是「施工方」，**不知道你是哪个施工单位的负责人**。
那道判断只有端点做得了，所以端点里的护栏必须写死，并由下面这些用例守住。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from apps.api import org_delegation_routes as delegation
from apps.api.main import app
from libs.db.repository import repo
from libs.security.auth import issue_token

client = TestClient(app)

ORG_A = "ORG-A-TEST"
ORG_B = "ORG-B-TEST"


@pytest.fixture(autouse=True)
def _fixture_users():
    """两个组织，各一个负责人和一个普通成员。"""
    created = [
        {"id": "U-A-LEAD", "username": "a-lead", "role": "contractor", "orgId": ORG_A, "isOrgLeader": True},
        {"id": "U-A-MEMBER", "username": "a-member", "role": "contractor", "orgId": ORG_A},
        {"id": "U-B-LEAD", "username": "b-lead", "role": "contractor", "orgId": ORG_B, "isOrgLeader": True},
        {"id": "U-B-MEMBER", "username": "b-member", "role": "contractor", "orgId": ORG_B},
        {"id": "U-A-ADMIN", "username": "a-admin", "role": "admin", "orgId": ORG_A},
    ]
    users = repo.state.setdefault("users", [])
    users[:0] = created
    repo.state.setdefault("org_units", []).insert(0, {"id": ORG_A, "name": "甲施工单位"})
    yield
    ids = {u["id"] for u in created}
    repo.state["users"] = [u for u in users if u.get("id") not in ids]
    repo.state["org_units"] = [o for o in repo.state["org_units"] if o.get("id") != ORG_A]
    repo.state["org_invitations"] = []


def _headers(username: str) -> dict[str, str]:
    user = next(u for u in repo.state["users"] if u["username"] == username)
    return {"Authorization": f"Bearer {issue_token(user)}"}


# ---- 第 5 条：权限下放 -----------------------------------------------------


def test_负责人可以改本组织成员的角色():
    response = client.post(
        f"/api/org-units/{ORG_A}/members/U-A-MEMBER/role",
        json={"role": "owner"},
        headers=_headers("a-lead"),
    )
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["role"] == "owner"
    target = next(u for u in repo.state["users"] if u["id"] == "U-A-MEMBER")
    assert target["role"] == "owner"


def test_改角色后旧令牌失效():
    """降权在下一次续期之前不生效的话，等于没降。"""
    before = next(u for u in repo.state["users"] if u["id"] == "U-A-MEMBER").get("authVersion") or 0
    client.post(
        f"/api/org-units/{ORG_A}/members/U-A-MEMBER/role",
        json={"role": "owner"},
        headers=_headers("a-lead"),
    )
    after = next(u for u in repo.state["users"] if u["id"] == "U-A-MEMBER")["authVersion"]
    assert after > before, "authVersion 没涨，旧令牌里的旧角色还能用"


def test_不能改别的组织的人():
    """**最要紧的一条。** 跨组织越权。"""
    response = client.post(
        f"/api/org-units/{ORG_B}/members/U-B-MEMBER/role",
        json={"role": "owner"},
        headers=_headers("a-lead"),
    )
    assert response.json()["code"] != 0
    assert next(u for u in repo.state["users"] if u["id"] == "U-B-MEMBER")["role"] == "contractor"


def test_不能借本组织的路径去改外组织的人():
    """路径写自己组织、目标写别人组织——这是最容易漏掉的绕法。"""
    response = client.post(
        f"/api/org-units/{ORG_A}/members/U-B-MEMBER/role",
        json={"role": "owner"},
        headers=_headers("a-lead"),
    )
    assert response.json()["code"] != 0
    assert next(u for u in repo.state["users"] if u["id"] == "U-B-MEMBER")["role"] == "contractor"


def test_不能授出管理员角色():
    for role in ("admin", "fde"):
        response = client.post(
            f"/api/org-units/{ORG_A}/members/U-A-MEMBER/role",
            json={"role": role},
            headers=_headers("a-lead"),
        )
        assert response.json()["code"] != 0, f"{role} 被授出去了，这是提权通道"


def test_不能改自己():
    response = client.post(
        f"/api/org-units/{ORG_A}/members/U-A-LEAD/role",
        json={"role": "owner"},
        headers=_headers("a-lead"),
    )
    assert response.json()["code"] != 0


def test_不能改管理员的角色():
    response = client.post(
        f"/api/org-units/{ORG_A}/members/U-A-ADMIN/role",
        json={"role": "contractor"},
        headers=_headers("a-lead"),
    )
    assert response.json()["code"] != 0


def test_普通成员不能分配权限():
    response = client.post(
        f"/api/org-units/{ORG_A}/members/U-A-MEMBER/role",
        json={"role": "owner"},
        headers=_headers("a-member"),
    )
    assert response.json()["code"] != 0


# ---- 第 4 条：邀请链接 -----------------------------------------------------


def _create_invite(role: str = "contractor", username: str = "a-lead"):
    return client.post(
        f"/api/org-units/{ORG_A}/invitations",
        json={"role": role},
        headers=_headers(username),
    ).json()


def test_负责人能创建邀请且链接带过期时间():
    body = _create_invite()
    assert body["code"] == 0, body
    assert body["data"]["token"]
    assert body["data"]["expiresAt"], "没有过期时间的邀请链接是长期后门"


def test_不能邀请成管理员():
    assert _create_invite(role="admin")["code"] != 0
    assert _create_invite(role="fde")["code"] != 0


def test_别的组织的负责人不能给本组织发邀请():
    body = _create_invite(username="b-lead")
    assert body["code"] != 0


def test_邀请可被未登录者查看但只回组织和角色():
    token = _create_invite()["data"]["token"]
    body = client.get(f"/api/invitations/{token}").json()
    assert body["code"] == 0
    assert body["data"]["orgName"] == "甲施工单位"
    assert body["data"]["role"] == "contractor"
    assert "createdBy" not in body["data"], "不该把创建人这类成员信息回出去"


def test_邀请只能用一次():
    token = _create_invite()["data"]["token"]
    payload = {"username": "invited-1", "password": "Aa!234567890x", "displayName": "被邀请人"}
    first = client.post(f"/api/invitations/{token}/accept", json=payload).json()
    assert first["code"] == 0, first
    second = client.post(
        f"/api/invitations/{token}/accept",
        json={**payload, "username": "invited-2"},
    ).json()
    assert second["code"] != 0, "同一个链接能反复注册——链接会被转发和截图"
    repo.state["users"] = [u for u in repo.state["users"] if u.get("username") != "invited-1"]


def test_过期的邀请不能用():
    token = _create_invite()["data"]["token"]
    invite = next(i for i in repo.state["org_invitations"] if i["token"] == token)
    invite["expiresAt"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    body = client.post(
        f"/api/invitations/{token}/accept",
        json={"username": "invited-late", "password": "Aa!234567890x"},
    ).json()
    assert body["code"] != 0


def test_注册者拿到的是邀请里写死的角色和组织():
    """如果注册请求里能带 role，链接就成了自选角色的入口。"""
    token = _create_invite(role="owner")["data"]["token"]
    client.post(
        f"/api/invitations/{token}/accept",
        json={
            "username": "invited-role",
            "password": "Aa!234567890x",
            "role": "admin",  # 恶意注入
            "orgId": ORG_B,
        },
    )
    created = next((u for u in repo.state["users"] if u.get("username") == "invited-role"), None)
    assert created, "注册没成功，用例本身失效"
    assert created["role"] == "owner", "请求里的 role 覆盖了邀请里的角色"
    assert str(created.get("orgId")) == ORG_A, "请求里的 orgId 覆盖了邀请里的组织"
    repo.state["users"] = [u for u in repo.state["users"] if u.get("username") != "invited-role"]


def test_弱口令被拒并且用的是后台同一套规则():
    token = _create_invite()["data"]["token"]
    body = client.post(
        f"/api/invitations/{token}/accept",
        json={"username": "invited-weak", "password": "123456"},
    ).json()
    assert body["code"] != 0
    assert not any(u.get("username") == "invited-weak" for u in repo.state["users"])


def test_无效令牌不泄露它为什么无效():
    """区分「不存在」「已用过」「已过期」等于给撞令牌的人送反馈。"""
    messages = set()
    for token in ("nope", ""):
        body = client.post(
            f"/api/invitations/{token or 'x'}/accept",
            json={"username": "u", "password": "Aa!234567890x"},
        ).json()
        messages.add(body.get("message"))
    assert len(messages) == 1, f"不同的失效原因回了不同的话：{messages}"


def test_受保护角色名单没被悄悄放宽():
    assert delegation.PROTECTED_ROLES >= {"admin", "fde"}
