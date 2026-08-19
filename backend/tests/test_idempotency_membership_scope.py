"""幂等重放的授权摘要只看**请求所涉项目**的成员关系。

## 事故形态（0819 实测）

原先摘要含用户在**所有项目**的成员快照。审计脚本反复把监检员加进
新建的审计项目，其全局成员列表每轮都变——242 条已缓存的幂等记录
全部永久失效，工作台一打开就是「当前授权上下文已变化」（FORBIDDEN）。

一般化：任何管理员把用户加进一个新项目，都会击穿该用户在
**其他所有项目**里的缓存重放。授权判定（mutation_guard）本来就只看
本项目的成员关系，摘要的粒度必须与它一致。

## 三条判据

1. 别的项目成员变化 **不** 使重放失效；
2. 本项目成员变化（如节点范围变了）**仍然** 使重放失效——守卫不能松；
3. 旧格式记录（全局快照）就地升级，不把用户拒在外面。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo

client = TestClient(app)
ADMIN = {"X-Role": "admin", "X-User-Id": "USER-ADMIN-001"}
PROJECT = "P-2026-HDCP-001"


def _fresh_key(tag: str) -> dict[str, str]:
    return {**ADMIN, "Idempotency-Key": f"IDEM-SCOPE-{tag}"}


def _member(project_id: str, member_id: str) -> dict:
    return {
        "id": member_id,
        "projectId": project_id,
        "userId": "USER-ADMIN-001",
        "name": "摘要粒度用例",
        "role": "admin",
        "status": "启用",
        "nodeScope": [1],
        "actions": [],
    }


def test_别的项目成员变化不使重放失效() -> None:
    rows = [_member(PROJECT, "PM-SCOPE-A")]
    repo.state.setdefault("project_members", [])[:0] = rows
    try:
        first = client.put(
            f"/api/projects/{PROJECT}/members/PM-SCOPE-A",
            json={"nodeScope": [1]},
            headers=_fresh_key("other-project"),
        )
        assert first.status_code == 200, first.text

        # 把同一个用户加进**另一个**项目——这正是击穿 242 条记录的那种变化
        repo.state["project_members"][:0] = [_member("P-OTHER-XYZ", "PM-SCOPE-B")]
        try:
            replay = client.put(
                f"/api/projects/{PROJECT}/members/PM-SCOPE-A",
                json={"nodeScope": [1]},
                headers=_fresh_key("other-project"),
            )
            assert replay.status_code == 200, (
                f"别的项目加了个成员，本项目的重放就被拒了：{replay.text}"
            )
        finally:
            repo.state["project_members"] = [
                item for item in repo.state["project_members"] if item.get("id") != "PM-SCOPE-B"
            ]
    finally:
        repo.state["project_members"] = [
            item for item in repo.state["project_members"] if item.get("id") != "PM-SCOPE-A"
        ]
        repo.state.get("idempotency", {}).clear()


def test_本项目成员变化仍使重放失效() -> None:
    """守卫不能因为收窄粒度而松掉：本项目授权真变了，重放必须拒。"""
    rows = [_member(PROJECT, "PM-SCOPE-C")]
    repo.state.setdefault("project_members", [])[:0] = rows
    try:
        first = client.put(
            f"/api/projects/{PROJECT}/members/PM-SCOPE-C",
            json={"remark": "第一次"},
            headers=_fresh_key("same-project"),
        )
        assert first.status_code == 200, first.text

        # 本项目的节点范围变了——授权上下文实质变化
        rows[0]["nodeScope"] = [1, 2, 3]
        replay = client.put(
            f"/api/projects/{PROJECT}/members/PM-SCOPE-C",
            json={"remark": "第一次"},
            headers=_fresh_key("same-project"),
        )
        assert replay.status_code == 403, (
            f"本项目授权变了却还在重放旧响应：{replay.status_code} {replay.text[:120]}"
        )
    finally:
        repo.state["project_members"] = [
            item for item in repo.state["project_members"] if item.get("id") != "PM-SCOPE-C"
        ]
        repo.state.get("idempotency", {}).clear()
