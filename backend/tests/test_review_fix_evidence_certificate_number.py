"""证号按类别位改写后，证据要跟着换到新编号的出处，不能还指着原来那个字段。

评审指出：安装许可证字段取成了告知书里设计单位的 TS1 号，改用原文里唯一的 TS3 号后，
证据仍是 TS1 那个高置信字段——grounding 就拿它替 TS3 作证，界面也引错号。
"""
from __future__ import annotations

from libs.review_orchestrator.certificate_facts import build_certificate_facts

OLD, NEW = "TS1844168-2027", "TS3844617-2026"


def _state(fragments):
    return {
        "projects": [{"id": "P-1", "contractorOrgName": "示例管道安装有限公司",
                      "constructionStart": "2025-04-01", "plannedConstructionEnd": "2026-04-30"}],
        "documents": [{"id": "DOC-1", "projectId": "P-1", "fileName": "安装许可证.pdf",
                       "materialTypeCode": "installation_license", "currentVersionId": "DV-1"}],
        "ocr_parse_results": [{
            "documentVersionId": "DV-1", "status": "success", "profileId": "qualification_certificate_v1",
            "fields": [{"fieldCode": "certificate_no", "fieldName": "许可证编号", "fieldValue": OLD,
                        "pageNo": 1, "bbox": [1, 2, 3, 4], "confidence": 0.99}],
            "fragments": fragments,
        }],
    }


def _certificate(fragments):
    facts = build_certificate_facts(_state(fragments), "P-1", 2, ["DV-1"])
    return facts["certificateFacts"]["certificates"][0], facts["judgment"]["claimedFacts"][0]


def test_replaced_number_is_anchored_where_the_new_number_appears():
    item, fact = _certificate([
        {"pageNo": 1, "text": f"制造(管道设计)许可证编号:{OLD}", "confidence": 0.95},
        {"pageNo": 2, "text": f"施工单位 示例管道安装有限公司 许可证编号 {NEW}", "confidence": 0.6},
    ])
    assert item["certificateNo"] == NEW and item["replacedByNumberType"] == {"certificateNo": OLD}
    assert not any(OLD in str(ref.get("quotedText") or "") for ref in item["evidence"])
    anchors = [ref for ref in item["evidence"] if NEW in str(ref.get("quotedText") or "")]
    assert [(ref["pageNo"], ref["confidence"]) for ref in anchors] == [(2, 0.6)]
    # 事实的置信度取自新编号那一处，不再是原 TS1 字段的 0.99。
    assert fact["value"] == NEW and fact["confidence"] == 0.6
    assert not any(field.get("quotedText") == OLD for field in fact["fields"])


def test_replaced_number_that_cannot_be_located_goes_to_a_human():
    # 编号被拆在两个片段里：定位不到具体出处，就不能凭别的字段判它可信。
    item, fact = _certificate([
        {"pageNo": 1, "text": f"制造(管道设计)许可证编号:{OLD}", "confidence": 0.95},
        {"pageNo": 1, "text": "施工单位 许可证编号 TS3844617-", "confidence": 0.95},
        {"pageNo": 1, "text": "2026", "confidence": 0.95},
    ])
    assert item["certificateNo"] == NEW
    assert not any(OLD in str(ref.get("quotedText") or "") for ref in item["evidence"])
    assert fact["confidence"] == 0.0
