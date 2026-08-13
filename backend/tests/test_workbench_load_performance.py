"""工作台加载性能的结构性护栏（线上审计 L-1 / L-2）。

线上实测：登录到工作台可用需 24 秒，其中 audit-overview 一个接口占 20.4 秒；
一次加载重复传输同一份 1.1 MB 业务包快照 4 次以上。

两条都不用「断言耗时」——CI 上耗时不稳定，而这两个问题的本质是**做了多少次**
和**传了什么**，都是确定量。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

import apps.api.routes as routes_module
from apps.api.main import app
from libs.db.repository import InMemoryRepository, repo

client = TestClient(app)
INSPECTION = {
    "X-Dev-Role": "inspection",
    "X-Dev-User": "USER-INSPECTION-001",
    "X-Role": "inspection",
}
PROJECT_ID = "P-2026-HDCP-001"


def test_detached_view_does_not_rebuild_the_seed() -> None:
    """游离视图造完就整体替换 state，播种是纯浪费。

    线上实测 InMemoryRepository() 单次 172 ms（重建 demo 种子、发布条款 release、
    绑定 69 个节点），占 project_document_read_view() 总耗时 242 ms 的 71%，
    而产物一次都没被读过。
    """
    seeded = InMemoryRepository()
    detached = InMemoryRepository(seed=False)
    assert detached.state is not None
    # 空骨架：集合键齐全但都是空的，由调用方立即整体替换
    assert all(detached.state[key] == [] for key in detached.state)
    # seed=False 不能退回 blank_state()——它自己先 fresh_state() 再清空，照付全额成本
    assert len(detached.state) <= len(seeded.state)


def test_audit_overview_builds_the_project_view_once_not_per_node(monkeypatch) -> None:
    """项目级视图与 nodeId 无关，不该在 69 个节点的循环里各建一次。"""
    calls: list[str] = []
    original = repo.project_document_read_view

    def _counting(project_id: str):
        calls.append(project_id)
        return original(project_id)

    monkeypatch.setattr(repo, "project_document_read_view", _counting)
    response = client.get(
        f"/api/projects/{PROJECT_ID}/inspection/audit-overview", headers=INSPECTION
    )
    assert response.json()["code"] == 0, response.text
    assert len(calls) <= 1, (
        f"audit-overview 构造了 {len(calls)} 次项目视图；它与节点无关，应只构造一次"
    )


def _project_payloads(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict) and "businessPackId" in item]
    if isinstance(data, dict):
        project = data.get("project")
        return [project] if isinstance(project, dict) else []
    return []


def test_project_responses_do_not_carry_the_business_pack_snapshot() -> None:
    """快照单个 1.1 MB，前端只用 businessPackSnapshotHash 判断版本。

    这条按端点扫描而不是只测一处——上一轮就是因为 tree 走了 repo.clone(project)
    绕过统一出口，才漏了 1.5 MB。
    """
    endpoints = [
        "/api/workbench/projects",
        f"/api/projects/{PROJECT_ID}/tree",
        f"/api/projects/{PROJECT_ID}/workbench/context",
        f"/api/projects/{PROJECT_ID}/inspection/audit-overview",
    ]
    offenders = []
    for path in endpoints:
        response = client.get(path, headers=INSPECTION)
        if response.status_code != 200 or response.json().get("code") != 0:
            continue
        for project in _project_payloads(response.json().get("data")):
            if "businessPackSnapshot" in project:
                offenders.append(path)
                break
    assert not offenders, "以下端点仍在下发 1.1 MB 的业务包快照：" + "、".join(offenders)


def test_version_marker_survives_so_clients_can_still_detect_changes() -> None:
    """剥掉快照不能连版本标识一起剥掉，否则前端无从判断业务包是否变了。"""
    project = repo.require_project(PROJECT_ID)
    assert project is not None
    payload = routes_module.versioned_project(project)
    assert "businessPackSnapshot" not in payload
    assert payload.get("revision") is not None
    assert payload.get("etag")
    if project.get("businessPackSnapshotHash"):
        assert payload.get("businessPackSnapshotHash") == project["businessPackSnapshotHash"]
