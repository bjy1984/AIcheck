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
    assert is_probe_project({"name": "写操作审计-勿动-20261104041000"})
    assert is_probe_project({"name": "随便", "probe": True})
    assert not is_probe_project({"name": "写操作审计说明"}) and not is_probe_project(None)


def test_列表和计数都不含探针项目_按id仍能打开():
    base = dict(repo.state["projects"][0])
    probe = {**base, "id": "P-PROBE-HIDE-1", "code": "P-PROBE-HIDE-1", "name": "写操作审计-勿动-20261104041000", "status": "已归档"}
    repo.state["projects"].append(probe)
    try:
        listed = client.get("/api/projects?pageSize=500", headers=ADMIN).json()["data"]
        ids = {row["id"] for row in (listed.get("items") or listed.get("list") or [])}
        assert "P-PROBE-HIDE-1" not in ids and base["id"] in ids
        workbench = {row["id"] for row in client.get("/api/workbench/projects?role=admin", headers=ADMIN).json()["data"]}
        assert "P-PROBE-HIDE-1" not in workbench
        assert client.get("/api/projects/P-PROBE-HIDE-1", headers=ADMIN).json()["code"] == 0, "按 id 访问不受影响（探针自己要用）"
    finally:
        repo.state["projects"] = [row for row in repo.state["projects"] if row["id"] != "P-PROBE-HIDE-1"]
