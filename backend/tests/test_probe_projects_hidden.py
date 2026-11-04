"""巡检探针项目「写操作审计-勿动-…」不出现在项目列表和计数里，按 id 仍能访问（2026-11-04）。"""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

os.environ.setdefault("AICHECK_ENABLE_DEMO_DATA", "true")

from apps.api.main import app  # noqa: E402
from libs.db.repository import repo  # noqa: E402
from libs.probe_projects import is_probe_project  # noqa: E402

client = TestClient(app)
ADMIN = {"Authorization": "Bearer dev-token-admin", "X-Role": "admin"}


def test_按名字或标记认出探针项目():
    assert is_probe_project({"name": "写操作审计-勿动-11040410", "region": "审计专用-已改"})
    assert not is_probe_project({"name": "写操作审计-勿动-20261104041000"}), "名字格式或地区对不上的不认（2026-11-04 审计）"
    assert is_probe_project({"name": "随便", "probe": True})
    assert not is_probe_project({"name": "写操作审计说明"}) and not is_probe_project(None)


def _base_project() -> dict:
    """先跑过关掉演示数据的用例时库里没有项目：自己建一个，别依赖用例顺序。"""
    if repo.state.get("projects"):
        return dict(repo.state["projects"][0])
    created = client.post("/api/projects", headers={**ADMIN, "Idempotency-Key": "probe-hidden-base"},
                          json={"name": "探针隐藏测试基准项目"}).json()["data"]
    return dict(created.get("project") or created)


def test_列表和计数都不含探针项目_按id仍能打开():
    base = _base_project()
    probe = {**base, "id": "P-PROBE-HIDE-1", "code": "P-PROBE-HIDE-1", "name": "写操作审计-勿动-11040410",
             "region": "审计专用-已改", "status": "已归档"}
    lookalike = {**base, "id": "P-PROBE-HIDE-2", "code": "P-PROBE-HIDE-2", "name": "写操作审计-勿动-广州燃气二期"}
    repo.state["projects"].extend([probe, lookalike])
    try:
        listed = client.get("/api/projects?pageSize=500", headers=ADMIN).json()["data"]
        ids = {row["id"] for row in (listed.get("items") or listed.get("list") or [])}
        assert "P-PROBE-HIDE-1" not in ids and base["id"] in ids
        assert "P-PROBE-HIDE-2" in ids, "真实项目改成同样开头不会被藏起来"
        workbench = {row["id"] for row in client.get("/api/workbench/projects?role=admin", headers=ADMIN).json()["data"]}
        assert "P-PROBE-HIDE-1" not in workbench
        assert client.get("/api/projects/P-PROBE-HIDE-1", headers=ADMIN).json()["code"] == 0, "按 id 访问不受影响（探针自己要用）"
    finally:
        repo.state["projects"] = [row for row in repo.state["projects"] if row["id"] not in {"P-PROBE-HIDE-1", "P-PROBE-HIDE-2"}]
