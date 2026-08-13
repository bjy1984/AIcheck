"""审计项状态口径：「还没开始」不是「需关注」（线上审计 L-5）。

线上实测一个刚立项、0 份资料的项目：

    未开始 345 · 处理中 0 · 需关注 138 · 执行失败 0 · 已完成 0

69 个节点的「资料提交」与「证据确认」全是需关注，理由是
「仍有 N 项必传资料未匹配」「仍有必传审查点缺少已确认资料证据」。

这两句描述的是「还没做」，不是「出了问题」。开局 138 个红点，等于把这个信号
用废了——真正需要关注的事项将淹没其中。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo

client = TestClient(app)
INSPECTION = {
    "X-Dev-Role": "inspection",
    "X-Dev-User": "USER-INSPECTION-001",
    "X-Role": "inspection",
}


def _items_by_key(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("key")): item for item in row.get("items") or []}


def _overview(project_id: str) -> list[dict[str, Any]]:
    response = client.get(
        f"/api/projects/{project_id}/inspection/audit-overview", headers=INSPECTION
    )
    assert response.json()["code"] == 0, response.text
    return response.json()["data"]["items"]


def test_untouched_node_is_not_started_not_needs_attention() -> None:
    """一个节点若既无挂载、无草稿、也无提交，两个下游审计项都该是「未开始」。"""
    rows = _overview("P-2026-HDCP-001")
    assert rows, "审计总览没有返回任何节点"

    offenders = []
    for row in rows:
        node_id = int((row.get("node") or {}).get("nodeId") or 0)
        bindings = [
            item
            for item in repo.state.get("bindings", [])
            if str(item.get("projectId")) == "P-2026-HDCP-001"
            and int(item.get("nodeId") or 0) == node_id
        ]
        if bindings:
            continue  # 已经动过的节点不在此列
        items = _items_by_key(row)
        for key in ("submission", "evidence"):
            if items.get(key, {}).get("status") == "needs_attention":
                offenders.append(f"节点{node_id}.{key}")
    assert not offenders, (
        "以下审计项在「什么都还没做」时被判为需关注：" + "、".join(offenders[:10])
    )


def test_summary_has_no_needs_attention_when_nothing_submitted() -> None:
    """整体口径：没有任何提交的项目，需关注数应为 0。"""
    response = client.get(
        "/api/projects/P-2026-HDCP-001/inspection/audit-overview", headers=INSPECTION
    )
    data = response.json()["data"]
    submitted = [
        item
        for item in repo.state.get("bindings", [])
        if str(item.get("projectId")) == "P-2026-HDCP-001"
        and str(item.get("bindingStatus")) in {"已提交", "已通过", "需补正"}
    ]
    if submitted:
        return  # 这个项目已经有提交，不适用
    assert data["summary"]["needs_attention"] == 0, (
        f"0 份提交的项目不该有需关注项，实际 {data['summary']['needs_attention']} 个"
    )


def test_missing_materials_still_surface_as_an_issue_message() -> None:
    """收紧状态不等于把原因藏起来——「缺 N 项必传资料」仍要能看到。

    状态回归为「未开始」，但缺项说明必须保留，否则用户不知道还差什么。
    """
    rows = _overview("P-2026-HDCP-001")
    with_missing = [
        row
        for row in rows
        if any(
            str(issue.get("code")) == "MATERIALS_MISSING"
            for issue in (_items_by_key(row).get("submission") or {}).get("issues") or []
        )
    ]
    assert with_missing, "缺项说明不该随状态一起消失"
