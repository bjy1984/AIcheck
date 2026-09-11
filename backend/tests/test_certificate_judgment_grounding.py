"""证书事实要能被 grounding 核；引擎没给分不等于分低。

2026-09-11 全节点扫描：证书节点（1/2/3/24/38）的 businessFacts 从没有 judgment，
execution.load_ocr_result 把 evidenceFacts 建成空列表，validate_evidence_grounding
看到 factCount=0，整个原子项一律证据不足——check_design_license_scope 明明 passed
也翻不过来。

补上 judgment 之后撞上第二道墙：生产 59% 的字段来自 MinerU VLM 通道，逐片不给分，
适配层写 0.0 并标 provider_confidence_unavailable。原来的 grounding 拿 0.0 去比 0.75，
一整份读对了的许可证（TS1844171-2028、广东政和工程有限公司、GB1/GB2、2028-01-17）
每个事实都判「置信度不够」。repository.py 早就为 extracted_fields 定了三态口径
（置信度未知 ≠ 低置信度），grounding 现在与之对齐。
"""
from __future__ import annotations

from libs.review_orchestrator.certificate_facts import build_certificate_facts, merge_certificate_facts
from libs.review_orchestrator.deterministic_tools import validate_evidence_grounding


def _state(*, reasons: list[str] | None, field_confidence: float) -> dict:
    return {
        "documents": [{"id": "DOC-1", "projectId": "P-1", "currentVersionId": "DV-1",
                       "fileName": "广东政和设计院压力管道设计资质.png", "materialTypeCode": "design_license"}],
        "versions": [{"id": "DV-1", "documentId": "DOC-1"}],
        "projects": [{"id": "P-1", "designOrgName": "广东政和工程有限公司"}],
        "ocr_parse_results": [
            {
                "documentVersionId": "DV-1",
                "status": "success",
                "profileId": "qualification_certificate_v1",
                "quality": {"reasons": reasons or []},
                "fields": [
                    {"fieldCode": "certificate_no", "fieldName": "许可证编号", "fieldValue": "TS1844171-2028",
                     "pageNo": 1, "bbox": [520, 309, 753, 337], "confidence": field_confidence},
                    {"fieldCode": "organization_name", "fieldName": "单位名称", "fieldValue": "广东政和工程有限公司",
                     "pageNo": 1, "bbox": [100, 200, 400, 230], "confidence": field_confidence},
                    {"fieldCode": "license_scope", "fieldName": "许可范围", "fieldValue": "压力管道设计；公用管道(GB1,GB2)；工业管道(GC1)",
                     "pageNo": 1, "bbox": [100, 300, 700, 360], "confidence": field_confidence},
                    {"fieldCode": "valid_until", "fieldName": "有效期至", "fieldValue": "2028年1月17日",
                     "pageNo": 1, "bbox": [100, 400, 300, 420], "confidence": field_confidence},
                ],
                "fragments": [],
            }
        ],
    }


def _run(node: int = 1) -> dict:
    return {"projectId": "P-1", "nodeId": node, "inputDocumentVersionIds": ["DV-1"]}


def test_证书事实带着可核的judgment():
    facts = build_certificate_facts(_state(reasons=None, field_confidence=0.91), "P-1", 1, ["DV-1"])
    judgment = facts["judgment"]
    assert len(judgment["claimedFacts"]) == 1
    fact = judgment["claimedFacts"][0]
    assert fact["value"] == "TS1844171-2028"
    assert fact["evidenceRefIds"], "证据要有 id，否则 grounding 对不上"
    assert fact["confidence"] == 0.91 and fact["confidenceUnavailable"] is False
    ref_ids = {item["evidenceRefId"] for item in judgment["evidenceRefs"]}
    assert set(fact["evidenceRefIds"]) <= ref_ids
    assert all(item["pageNo"] == 1 and item["quotedText"] for item in judgment["evidenceRefs"])


def test_有分且够高时grounding通过():
    facts = build_certificate_facts(_state(reasons=None, field_confidence=0.91), "P-1", 1, ["DV-1"])
    out = validate_evidence_grounding({"facts": facts["judgment"]["claimedFacts"],
                                       "evidenceRefs": facts["judgment"]["evidenceRefs"], "minConfidence": 0.75})
    assert out["result"] == "passed"


def test_引擎没给分是交人工判断_不是证据不足():
    """生产原样：MinerU 字段 confidence=0.0 且 quality.reasons 含 provider_confidence_unavailable。"""
    facts = build_certificate_facts(_state(reasons=["provider_confidence_unavailable"], field_confidence=0.0), "P-1", 1, ["DV-1"])
    fact = facts["judgment"]["claimedFacts"][0]
    assert fact["confidenceUnavailable"] is True and fact["confidence"] is None
    out = validate_evidence_grounding({"facts": facts["judgment"]["claimedFacts"],
                                       "evidenceRefs": facts["judgment"]["evidenceRefs"], "minConfidence": 0.75})
    assert out["result"] == "human_review_required"
    assert out["facts"]["reason"] == "provider_confidence_unavailable"
    assert out["facts"]["unscoredFacts"] == [1]
    confidence_check = next(item for item in out["checks"] if item["code"] == "fact_1_confidence")
    assert confidence_check["passed"] is True and confidence_check["actual"] == "unscored"


def test_引擎给了分但分低_仍是证据不足():
    """没标 unavailable 的 0.3 是真的低分，不能借「没分」的口子放过去。"""
    facts = build_certificate_facts(_state(reasons=None, field_confidence=0.3), "P-1", 1, ["DV-1"])
    out = validate_evidence_grounding({"facts": facts["judgment"]["claimedFacts"],
                                       "evidenceRefs": facts["judgment"]["evidenceRefs"], "minConfidence": 0.75})
    assert out["result"] == "evidence_insufficient"


def test_没分但位置不全_照样证据不足():
    """「交人工」只给位置齐、引文在的事实；缺页码的证据连人都没法去看。"""
    facts = build_certificate_facts(_state(reasons=["provider_confidence_unavailable"], field_confidence=0.0), "P-1", 1, ["DV-1"])
    refs = [{**item, "pageNo": None, "bbox": None, "quotedText": ""} for item in facts["judgment"]["evidenceRefs"]]
    out = validate_evidence_grounding({"facts": facts["judgment"]["claimedFacts"], "evidenceRefs": refs, "minConfidence": 0.75})
    assert out["result"] == "evidence_insufficient"


def test_合并时不覆盖节点24已有的judgment():
    """焊工 builder 自己产 judgment；证书事实要并进去，两边都不能丢。"""
    state = _state(reasons=None, field_confidence=0.9)
    state["documents"][0]["materialTypeCode"] = "welder_certificate"
    state["documents"][0]["fileName"] = "焊工证.pdf"
    existing = {"r24": {}, "judgment": {"claimedFacts": [{"factId": "r24-1", "value": "X", "evidenceRefIds": ["W-1"]}],
                                         "evidenceRefs": [{"evidenceRefId": "W-1", "pageNo": 1, "quotedText": "x"}]}}
    merged = merge_certificate_facts(state, _run(24), existing)
    ids = [item["factId"] for item in merged["judgment"]["claimedFacts"]]
    assert ids[0] == "r24-1" and any(item.startswith("certificate-") for item in ids[1:]), ids
    assert any(item["evidenceRefId"] == "W-1" for item in merged["judgment"]["evidenceRefs"])
