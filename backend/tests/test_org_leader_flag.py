"""组织负责人标记只能由系统管理员设（0817 第 5 条的前提）。

## 为什么要单独守这一条

权限下放的整条链是：

    admin 指定谁是组织负责人  ->  负责人在本组织内分配角色

**第一步一旦能被负责人自己动，整条链就成了提权通道**：
他给自己或同伙加上标记，再给自己换角色，绕开了所有下放的边界。

所以 isOrgLeader 只能走后台建/改用户的接口——那两个接口本来就只有 admin
能调，这里锁住「它确实只在那条路上可写」以及「读得出来」。

## 一条容易写错的语义

不传这个字段时要**保持原值**，不能当成取消。
后台改用户时前端往往只提交改动过的字段，把「没提到」当成 false 的话，
每改一次手机号就顺手把负责人身份撤了——而且没有任何提示。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import admin_user_projection, build_admin_user_record
from libs.db.repository import repo

client = TestClient(app)
ADMIN = {"X-Role": "admin", "X-User-Id": "USER-ADMIN-001"}


def test_默认不是负责人():
    user = build_admin_user_record({"username": "u1", "role": "contractor"})
    assert user["isOrgLeader"] is False


def test_可以显式设成负责人():
    user = build_admin_user_record({"username": "u1", "role": "contractor", "isOrgLeader": True})
    assert user["isOrgLeader"] is True


def test_不传时保持原值():
    """**最容易写错的一条。**

    后台改用户时前端往往只提交改动过的字段。把「没提到」当成 false 的话，
    每改一次手机号就顺手把负责人身份撤了，而且没有任何提示。
    """
    existing = {"id": "U1", "username": "u1", "role": "contractor", "isOrgLeader": True}
    user = build_admin_user_record({"mobile": "13800000000"}, existing=existing)
    assert user["isOrgLeader"] is True, "只改手机号就把负责人身份撤了"


def test_可以显式取消():
    existing = {"id": "U1", "username": "u1", "role": "contractor", "isOrgLeader": True}
    user = build_admin_user_record({"isOrgLeader": False}, existing=existing)
    assert user["isOrgLeader"] is False


def test_投影里带得出来():
    """界面要显示「这个人是不是本组织负责人」，不带出来后台就没法勾选。"""
    projected = admin_user_projection({"id": "U1", "username": "u1", "isOrgLeader": True})
    assert projected["isOrgLeader"] is True
    assert admin_user_projection({"id": "U2", "username": "u2"})["isOrgLeader"] is False


@pytest.fixture
def _leader():
    user = {
        "id": "U-LEADER-FLAG-TEST",
        "username": "leader-flag-test",
        "role": "contractor",
        "orgId": "ORG-FLAG-TEST",
        "isOrgLeader": False,
    }
    repo.state.setdefault("users", []).insert(0, user)
    yield user
    repo.state["users"] = [u for u in repo.state["users"] if u.get("id") != user["id"]]


def test_非管理员改不了这个标记(_leader):
    """整条权限下放链的第一步。这一步能被自己动，后面所有边界都白设。"""
    for headers in (
        {"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"},
        {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"},
    ):
        response = client.patch(
            f"/api/admin/users/{_leader['id']}",
            json={"isOrgLeader": True},
            headers=headers,
        )
        assert response.json()["code"] != 0, f"{headers['X-Role']} 把自己变成了组织负责人"
        assert _leader["isOrgLeader"] is False
