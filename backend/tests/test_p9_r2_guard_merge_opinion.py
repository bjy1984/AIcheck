"""P9 R2：守卫不销毁原文、降级条目按断言集合去重、AI 建议不取模板句。"""

from __future__ import annotations

from libs.review_grounding import apply_grounding_guardrails
from libs.review_orchestrator.opinion_draft import opinion_draft_from_findings
from libs.review_orchestrator.shard_execution import aggregate_shard_findings

TEMPLATE = "证据不足，需人工确认"


def _draft(**overrides):
    base = {
        "id": "FND-1",
        "title": "许可证有效期覆盖施工计划工期，符合要求",
        "description": "许可证 TS9999999-2030 有效期至 2030-12-25，覆盖工期，符合要求。",
        "severity": "high",
        "evidenceRefs": [
            {
                "evidenceLinkId": "EVL-1",
                "documentVersionId": "DV-1",
                "pageNo": 1,
                "bbox": [1, 1, 9, 9],
                "quotedText": "有效期",
            }
        ],
        "suggestedAction": "human_confirm",
    }
    base.update(overrides)
    return base


def _grounding_input():
    return {
        "groundingStatus": "grounded",
        "documentVersionIds": ["DV-1"],
        "evidenceTextCorpus": ["许可证 有效期至 2026-12-25"],
        "fragments": [
            {
                "id": "FRAG-1",
                "documentVersionId": "DV-1",
                "text": "许可证 有效期至 2026-12-25",
                "pageNo": 1,
                "bbox": [1, 1, 9, 9],
            }
        ],
        "fields": [],
        "tables": [],
        "seals": [],
        "evidenceLinks": [
            {
                "id": "EVL-1",
                "documentVersionId": "DV-1",
                "pageNo": 1,
                "bbox": [1, 1, 9, 9],
                "quotedText": "有效期",
            }
        ],
        "reviewMode": "gap_precheck",
    }


def test_unsupported_branch_marks_unverified_and_keeps_only_the_claims() -> None:
    """无据断言：标 unverified，具体断言进 unsupportedClaims，整句原文不带出来。"""
    result = apply_grounding_guardrails([_draft()], _grounding_input())[0]
    assert result["groundingStatus"] == "insufficient_evidence"
    assert result["title"] == TEMPLATE
    assert result["unverified"] is True
    assert "TS9999999-2030" not in str(result.get("modelDescription") or "")
    assert any(claim["claim"] == "TS9999999-2030" for claim in result["unsupportedClaims"])


def test_downgraded_findings_merge_by_claim_set_and_keep_highest_severity() -> None:
    claims = [{"claim": "TS9999999-2030", "reason": "not_present_in_supplied_evidence"}]
    shard_results = [
        {
            "evidenceShardId": "ESHARD-1",
            "modelAttemptIds": ["A1"],
            "findingDrafts": [
                {
                    "id": "F1",
                    "findingType": "missing_evidence",
                    "title": TEMPLATE,
                    "description": "模板",
                    "severity": "medium",
                    "unsupportedClaims": claims,
                    "evidenceRefs": [],
                    "ruleRefs": [],
                    "kbRefs": [],
                }
            ],
        },
        {
            "evidenceShardId": "ESHARD-2",
            "modelAttemptIds": ["A2"],
            "findingDrafts": [
                {
                    "id": "F2",
                    "findingType": "missing_evidence",
                    "title": TEMPLATE,
                    "description": "模板",
                    "severity": "high",
                    "unsupportedClaims": list(reversed(claims)),
                    "evidenceRefs": [],
                    "ruleRefs": [],
                    "kbRefs": [],
                }
            ],
        },
        {
            "evidenceShardId": "ESHARD-3",
            "modelAttemptIds": ["A3"],
            "findingDrafts": [
                {
                    "id": "F3",
                    "findingType": "missing_evidence",
                    "title": TEMPLATE,
                    "description": "模板",
                    "severity": "low",
                    "unsupportedClaims": [{"claim": "另一个断言"}],
                    "evidenceRefs": [],
                    "ruleRefs": [],
                    "kbRefs": [],
                }
            ],
        },
    ]
    aggregate = aggregate_shard_findings({"reviewRunId": "RRUN-X"}, shard_results)
    drafts = aggregate.get("findingDrafts") if isinstance(aggregate, dict) else aggregate
    templates = [item for item in drafts if item["title"] == TEMPLATE]
    assert len(templates) == 2, [item.get("unsupportedClaims") for item in templates]
    merged = next(item for item in templates if item["unsupportedClaims"] == claims)
    assert merged["severity"] == "high"
    assert set(merged["sourceEvidenceShardIds"]) == {"ESHARD-1", "ESHARD-2"}
    assert merged["mergedFindingIds"] == ["F2"]


def test_opinion_draft_never_uses_template_sentence() -> None:
    template_draft = {
        "title": TEMPLATE,
        "description": "模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。",
        "groundingStatus": "insufficient_evidence",
        "confidence": 0.5,
    }
    grounded_draft = {
        "title": "发证机关印章识别存疑",
        "description": "印章 OCR 读数为“武苏省市场监督管理”，与发证机关不一致，需人工核对原件。",
        "groundingStatus": "grounded",
        "confidence": 0.7,
    }

    picked = opinion_draft_from_findings([template_draft, grounded_draft])
    assert picked["source"] == "grounded_finding"
    assert picked["text"].startswith("发证机关印章识别存疑：")
    assert picked["confidence"] == 0.7

    fallback = opinion_draft_from_findings(
        [template_draft, template_draft], deterministic_verdict="failed"
    )
    assert fallback["source"] == "deterministic_result"
    assert "模型给出的业务结论缺少证据支持" not in fallback["text"]
    assert "2 条" in fallback["text"]

    only_downgraded = opinion_draft_from_findings([template_draft])
    assert only_downgraded["source"] == "downgraded_summary"
    assert opinion_draft_from_findings([])["source"] == "empty"
