"""项目负责人标记：可以有多个，且不会被顺手撤掉。

## 这个标记原先只有读、没有写

project_registration_routes 判「是不是这个项目的负责人」靠
project_members.isProjectLeader，但**代码里没有任何地方能设置它**——
也就是说除了 admin（走另一条分支），项目负责人这条路实际是空的：
链接发不出来，申请也没人能审。

这是我引入的缺口，用例把它钉住。

## 同一角色允许多个负责人

现场本来就有 AB 角和轮班。限成一个的话，那个人休假整条审批就卡住了。
所以这里**没有任何唯一性约束**——不要「贴心」地加一个。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.project_registration_routes import can_manage_project_registration
from libs.db.repository import repo

client = TestClient(app)
ADMIN = {"X-Role": "admin", "X-User-Id": "USER-ADMIN-001"}
PROJECT = "P-2026-HDCP-001"


@pytest.fixture
def _members():
    created = [
        {
            "id": "PM-LEADER-TEST-1",
            "projectId": PROJECT,
            "userId": "U-LEADER-TEST-1",
            "name": "甲负责人",
            "role": "contractor",
            "status": "启用",
            "nodeScope": [1],
            "actions": [],
        },
        {
            "id": "PM-LEADER-TEST-2",
            "projectId": PROJECT,
            "userId": "U-LEADER-TEST-2",
            "name": "乙负责人",
            "role": "contractor",
            "status": "启用",
            "nodeScope": [1],
            "actions": [],
        },
    ]
    repo.state.setdefault("project_members", [])[:0] = created
    yield created
    ids = {item["id"] for item in created}
    repo.state["project_members"] = [
        item for item in repo.state["project_members"] if item.get("id") not in ids
    ]


def _set_leader(member_id: str, value: bool):
    return client.put(
        f"/api/projects/{PROJECT}/members/{member_id}",
        json={"isProjectLeader": value},
        headers=ADMIN,
    ).json()


def test_可以设为项目负责人(_members):
    """原先这个标记只有读没有写——除了 admin，谁也当不成项目负责人。"""
    body = _set_leader("PM-LEADER-TEST-1", True)
    assert body["code"] == 0, body
    assert _members[0]["isProjectLeader"] is True


def test_同一角色可以有多个负责人(_members):
    """现场有 AB 角和轮班。限成一个的话，那个人休假整条审批就卡住了。"""
    assert _set_leader("PM-LEADER-TEST-1", True)["code"] == 0
    assert _set_leader("PM-LEADER-TEST-2", True)["code"] == 0, "第二个负责人被拒了"
    leaders = [
        item
        for item in repo.state["project_members"]
        if item.get("projectId") == PROJECT
        and item.get("role") == "contractor"
        and item.get("isProjectLeader")
    ]
    assert len(leaders) >= 2


def test_可以取消(_members):
    _set_leader("PM-LEADER-TEST-1", True)
    assert _set_leader("PM-LEADER-TEST-1", False)["code"] == 0
    assert _members[0]["isProjectLeader"] is False


def test_不传时保持原值(_members):
    """**最容易写错的一条。**

    前端常常只提交改动过的字段。把「没提到」当成 false 的话，
    每改一次节点范围就顺手把负责人撤了——而且没有任何提示。
    """
    _set_leader("PM-LEADER-TEST-1", True)
    body = client.put(
        f"/api/projects/{PROJECT}/members/PM-LEADER-TEST-1",
        json={"nodeScope": [1, 2]},
        headers=ADMIN,
    ).json()
    assert body["code"] == 0, body
    assert _members[0]["isProjectLeader"] is True, "只改节点范围就把负责人撤了"


def test_负责人判定认这个标记(_members):
    """标记设了但判定不认的话，等于没设。"""
    user = {"id": "U-LEADER-TEST-1", "username": "leader-test-1", "role": "contractor"}
    assert can_manage_project_registration(user, PROJECT) is False
    _members[0]["isProjectLeader"] = True
    assert can_manage_project_registration(user, PROJECT) is True


def test_负责人身份不跨项目(_members):
    """甲项目的负责人不该能管乙项目的注册。"""
    _members[0]["isProjectLeader"] = True
    user = {"id": "U-LEADER-TEST-1", "username": "leader-test-1", "role": "contractor"}
    assert can_manage_project_registration(user, "P-OTHER-PROJECT") is False
