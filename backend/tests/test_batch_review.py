"""监检一键审查（0817 第 3 条）。

    「对于施工方已经提交的文件支持一键审查」

原先只能一个节点一个节点点 ai-recheck。一个项目几十个节点，
监检要点几十次，还得自己记住哪些点过了——**这不是效率问题，
是「漏掉一个也不会有人发现」的问题。**

## 判据

- 端点真的挂上了。拆到独立模块后忘记 include_router 的话，
  路由 404 而且**不会报错**——office_preview 拆分时踩过一次。
- 跳过一定要带**理由**。只回「已发起 3 个」的话，另外 20 个去哪了没人知道。
- 一个节点失败不许带走整批：前面跑了、后面没跑，却返回一个 500，
  监检根本不知道现在是什么状态。
- 有上限并且**明说**超出的部分，不静默截断。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api import batch_review_routes as batch
from apps.api.main import app
from libs.db.repository import repo

client = TestClient(app)
HEADERS = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
PROJECT_ID = "P-2026-HDCP-001"


def _post(payload: dict | None = None) -> dict:
    response = client.post(
        f"/api/projects/{PROJECT_ID}/inspection/ai-recheck-batch",
        json=payload or {},
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_端点已挂载并返回业务成功码():
    """拆到独立模块后忘记 include_router 的话，路由 404 且不会报错。"""
    body = _post({"nodeIds": []})
    assert body["code"] == 0, body


def test_跳过的节点必须带理由():
    body = _post({"nodeIds": [9998, 9999]})
    data = body["data"]
    assert data["startedCount"] == 0
    assert data["skippedCount"] == 2
    for item in data["skipped"]:
        assert item["reason"], "跳过没写原因，监检会以为跑过了"
        assert item["message"]


def test_项目不存在返回业务错误码():
    """这个仓库的接口是 HTTP 200 + 业务 code，不能只看 HTTP 状态。"""
    response = client.post(
        "/api/projects/P-NOT-EXIST/inspection/ai-recheck-batch", json={}, headers=HEADERS
    )
    assert response.json()["code"] != 0


def test_一个节点失败不影响其余(monkeypatch):
    """**最重要的一条。** 中途炸掉而返回 500 的话，监检不知道跑到哪了。"""
    monkeypatch.setattr(batch, "_node_has_reviewable_material", lambda *_: True)
    monkeypatch.setattr(batch, "_node_has_running_review", lambda *_: False)

    import apps.api.routes as routes

    def flaky(request, project_id, node_id, *rest):
        if int(node_id) == 2:
            raise RuntimeError("编排未启动")
        return type("R", (), {"body": b"{}"})()

    monkeypatch.setattr(routes, "ai_recheck", flaky)

    data = _post({"nodeIds": [1, 2, 3]})["data"]
    assert data["startedCount"] == 2, "一个节点失败把其余也带走了"
    failed = [item for item in data["skipped"] if item["reason"] == "START_FAILED"]
    assert len(failed) == 1
    assert "编排未启动" in failed[0]["message"], "失败原因被吞掉了"


def test_超出上限的部分明确回报而不是静默截断(monkeypatch):
    monkeypatch.setattr(batch, "_node_has_reviewable_material", lambda *_: True)
    monkeypatch.setattr(batch, "_node_has_running_review", lambda *_: False)
    import apps.api.routes as routes

    monkeypatch.setattr(routes, "ai_recheck", lambda *a, **k: type("R", (), {"body": b"{}"})())

    node_ids = list(range(1, batch.MAX_BATCH_NODES + 6))
    data = _post({"nodeIds": node_ids})["data"]
    assert data["startedCount"] == batch.MAX_BATCH_NODES
    over = [item for item in data["skipped"] if item["reason"] == "BATCH_LIMIT"]
    assert len(over) == 5, "超出的部分被悄悄丢掉了"
    assert data["batchLimit"] == batch.MAX_BATCH_NODES, "上限要回给前端，否则用户不知道为什么少了"


def test_不传节点时取项目下全部节点(monkeypatch):
    """监检要的是「把该审的都审一遍」，不是逼他先自己列清单。"""
    seen: list[int] = []
    monkeypatch.setattr(batch, "_node_has_reviewable_material", lambda *a: seen.append(a[1]) or False)
    _post({})
    project_nodes = {
        int(node.get("nodeId") or 0)
        for node in repo.state.get("tree_nodes", [])
        if str(node.get("projectId")) == PROJECT_ID
    } - {0}
    assert seen, "没有遍历任何节点"
    assert set(seen) == project_nodes
