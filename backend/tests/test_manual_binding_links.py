"""人工挂载的资料必须进审查视野；已提交的资料改挂节点不退回未提交。

2026-09-03 审计（测试项目3 节点 2）：已提交 3 份、AI 只看自动打靶的 2 份；
文件库改挂节点后文件从「已提交」退回「施工方未提交」。
"""

from __future__ import annotations

from libs.manual_binding_links import (
    bindings_missing_evidence_links,
    document_already_submitted,
    submitted_binding_document_versions,
    upsert_manual_binding_evidence_links,
)
from libs.review_evidence import active_node_document_versions


def _state():
    return {
        "documents": [
            {"id": "DOC-LIC", "projectId": "P-1", "fileName": "许可证.jpg", "currentVersionId": "DV-LIC-V1", "materialTypeCode": "manufacturing_license"},
            {"id": "DOC-DRAW", "projectId": "P-1", "fileName": "施工图.pdf", "currentVersionId": "DV-DRAW-V2"},
            {"id": "DOC-OLD", "projectId": "P-1", "fileName": "旧版.pdf", "currentVersionId": "DV-OLD-V2"},
        ],
        "tree_nodes": [{"projectId": "P-1", "nodeId": 2, "name": "施工单位许可资质", "businessPackId": "bp"}],
        "bindings": [
            {"id": "BIND-2-A", "projectId": "P-1", "nodeId": 2, "documentId": "DOC-LIC", "documentVersionId": "DV-LIC-V1", "bindingStatus": "已提交", "requirementName": "施工许可证"},
            {"id": "BIND-2-B", "projectId": "P-1", "nodeId": 2, "documentId": "DOC-DRAW", "documentVersionId": "DV-DRAW-V2", "bindingStatus": "已提交"},
            {"id": "BIND-2-C", "projectId": "P-1", "nodeId": 2, "documentId": "DOC-OLD", "documentVersionId": "DV-OLD-V1", "bindingStatus": "已提交"},
            {"id": "BIND-2-D", "projectId": "P-1", "nodeId": 2, "documentId": "DOC-LIC", "documentVersionId": "DV-LIC-V1", "bindingStatus": "草稿挂载"},
        ],
        "node_evidence_links": [
            {"id": "NEL-AUTO", "projectId": "P-1", "nodeId": 2, "documentId": "DOC-DRAW", "documentVersionId": "DV-DRAW-V2", "manualStatus": "confirmed", "source": "material_targeting", "revision": 3},
        ],
    }


def test_已提交人工挂载进活跃资料集合_草稿与旧版本不进():
    state = _state()
    rows = submitted_binding_document_versions(state, "P-1", 2)
    assert [row["documentVersionId"] for row in rows] == ["DV-DRAW-V2", "DV-LIC-V1"]
    active = active_node_document_versions(state, "P-1", 2)
    assert [row["documentVersionId"] for row in active] == ["DV-DRAW-V2", "DV-LIC-V1"], "许可证只有人工挂载，也要能被审查看到"
    drawing = next(row for row in active if row["documentVersionId"] == "DV-DRAW-V2")
    assert drawing["mountLinkIds"] == ["BIND-2-B", "NEL-AUTO"] and drawing["mountRevision"] == 3


def test_补链接幂等_已有自动打靶链接不重复():
    state = _state()
    missing = bindings_missing_evidence_links(state, "P-1")
    assert [row["id"] for row in missing] == ["BIND-2-A"]
    created = upsert_manual_binding_evidence_links(state, "P-1", state["bindings"], actor_name="施工方")
    assert [link["documentId"] for link in created] == ["DOC-LIC"]
    link = created[0]
    assert link["source"] == "manual_binding" and link["manualStatus"] == "confirmed"
    assert link["nodeName"] == "施工单位许可资质" and link["bindingId"] == "BIND-2-A"
    assert upsert_manual_binding_evidence_links(state, "P-1", state["bindings"]) == []
    assert bindings_missing_evidence_links(state, "P-1") == []
    # 驳回后再次提交：同一条链接恢复为已确认
    link["manualStatus"] = "rejected"
    again = upsert_manual_binding_evidence_links(state, "P-1", state["bindings"], actor_name="再提交")
    assert again and again[0]["id"] == link["id"] and link["manualStatus"] == "confirmed"
    assert len([row for row in state["node_evidence_links"] if row["source"] == "manual_binding"]) == 1


def test_资料已进审查视野的判定():
    state = _state()
    assert document_already_submitted(state, "P-1", "DOC-LIC")
    state["bindings"] = [row for row in state["bindings"] if row["documentId"] != "DOC-LIC"]
    assert not document_already_submitted(state, "P-1", "DOC-LIC")
    state["documents"][0]["poolSubmissionStatus"] = "已提交"
    assert document_already_submitted(state, "P-1", "DOC-LIC")
