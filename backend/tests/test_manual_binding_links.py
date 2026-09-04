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
        "projects": [{"id": "P-1", "businessPackId": "bp"}],
        "requirements": [{"id": "REQ-02-01", "projectId": "P-1", "nodeId": 2, "materialTypeCode": "construction_license"}],
        "admin_config": {
            "materialReviewPoints": [
                {"id": "MRP-2-construction_license", "businessPackId": "bp", "nodeId": 2, "materialTypeCode": "construction_license", "materialTypeName": "施工单位安装许可证", "materialCategory": "资质", "requiredType": "条件必传", "responsibleParty": "contractor", "reviewContent": "施工单位许可资质", "evidenceItems": ["单位名称", "许可证编号", "有效期至"]},
                {"id": "MRP-2-design_document", "businessPackId": "bp", "nodeId": 2, "materialTypeCode": "design_document"},
            ]
        },
        "bindings": [
            {"id": "BIND-2-A", "projectId": "P-1", "nodeId": 2, "documentId": "DOC-LIC", "documentVersionId": "DV-LIC-V1", "bindingStatus": "已提交", "requirementId": "REQ-02-01", "requirementName": "施工许可证"},
            {"id": "BIND-2-B", "projectId": "P-1", "nodeId": 2, "documentId": "DOC-DRAW", "documentVersionId": "DV-DRAW-V2", "bindingStatus": "已提交"},
            {"id": "BIND-2-C", "projectId": "P-1", "nodeId": 2, "documentId": "DOC-OLD", "documentVersionId": "DV-OLD-V1", "bindingStatus": "已提交"},
            {"id": "BIND-2-D", "projectId": "P-1", "nodeId": 2, "documentId": "DOC-LIC", "documentVersionId": "DV-LIC-V1", "bindingStatus": "草稿挂载"},
        ],
        "ocr_parse_results": [
            {"documentVersionId": "DV-LIC-V1", "status": "success", "fragments": [{"pageNo": 1, "text": "特种设备生产许可证 编号：TS3832083-2026 单位名称：江苏三江机电工程有限公司 有效期至：2026年12月25日"}]}
        ],
        "extracted_fields": [
            {"id": "F-1", "documentVersionId": "DV-LIC-V1", "fieldName": "许可证编号", "fieldValue": "TS3832083-2026", "pageNo": 1, "bbox": [351.6, 235.5, 505.4, 254.0], "confidence": 0.9},
            {"id": "F-2", "documentVersionId": "DV-LIC-V1", "fieldName": "单位名称", "fieldValue": "江苏三江机电工程有限公司", "pageNo": 1, "bbox": [87.6, 265.8, 361.8, 285.9], "confidence": 0.9},
            {"id": "F-3", "documentVersionId": "DV-LIC-V1", "fieldName": "有效期至", "fieldValue": "2026年12月25日", "pageNo": 1, "bbox": [86.4, 722.4, 301.0, 741.8], "confidence": 0.9},
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
    # 挂载时选的是「施工单位安装许可证」要求：链接挂到同类型的审查要点上，资料类型跟要点走
    # （资料本身被词典分类成 manufacturing_license，人工选择优先）
    assert link["reviewPointId"] == "MRP-2-construction_license"
    assert link["materialTypeCode"] == "construction_license" and link["formalEvidenceEligible"] is True
    # 文件早已 OCR：按要点的事实目标定位到字段，链接可定位，正式审查能引用
    from libs.material_targeting import evidence_link_is_locatable

    assert evidence_link_is_locatable(link), link
    assert link["pageNo"] == 1 and link["quotedText"].split("：")[0] in {"许可证编号", "单位名称", "有效期至"}
    assert link["formalEvidenceFactCount"] == 3 and link["supportStatus"] == "命中"
    assert sorted(link["matchedEvidenceItems"]) == ["单位名称", "有效期至", "许可证编号"]
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


def test_重算要点_老链接补上要点id():
    from libs.manual_binding_links import refresh_manual_binding_links

    state = _state()
    upsert_manual_binding_evidence_links(state, "P-1", state["bindings"])
    link = next(row for row in state["node_evidence_links"] if row["source"] == "manual_binding")
    link.update({"reviewPointId": "REQ-02-01", "materialTypeCode": "manufacturing_license", "formalEvidenceEligible": False})
    changed = refresh_manual_binding_links(state, "P-1")
    assert [row["id"] for row in changed] == [link["id"]]
    assert link["reviewPointId"] == "MRP-2-construction_license" and link["formalEvidenceEligible"] is True
    assert refresh_manual_binding_links(state, "P-1") == []


def test_没有OCR字段时退回整份文件链接():
    state = _state()
    state["extracted_fields"] = []
    state["ocr_parse_results"] = []
    created = upsert_manual_binding_evidence_links(state, "P-1", state["bindings"])
    link = created[0]
    assert link["pageNo"] is None and link["quotedText"] is None
    assert link["supportStatus"] == "待人工确认" and link["evidenceTier"] == "manual"
