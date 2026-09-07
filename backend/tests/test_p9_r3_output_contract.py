"""P9 R3 输出契约：长度只警告、条数按优先级截到 8 并归并、提示词带格式约束。"""

from __future__ import annotations

from libs.review_orchestrator import execution as ex
from libs.review_orchestrator.output_contract import (
    DESCRIPTION_MAX_CHARS,
    MAX_FINDINGS_PER_NODE,
    PROMPT_FORMAT_REQUIREMENTS,
    cap_findings,
    cap_generated_findings,
    text_length_warnings_for,
)


def _grounded(index: int, severity: str) -> dict:
    return {
        "id": f"F{index}",
        "findingType": "x",
        "severity": severity,
        "title": f"发现 {index}",
        "description": "说明",
        "evidenceRefs": [{"evidenceLinkId": f"EVL-{index}"}],
        "ruleRefs": [],
        "kbRefs": [],
        "confidence": 0.8,
        "suggestedAction": "human_confirm",
        "groundingStatus": "grounded",
        "unsupportedClaims": [],
        "requiresHumanConfirmation": True,
    }


def _downgraded(index: int) -> dict:
    return {
        **_grounded(index, "medium"),
        "title": "证据不足，需人工确认",
        "groundingStatus": "insufficient_evidence",
        "unsupportedClaims": [{"claim": f"TS{index}", "reason": "not_present_in_supplied_evidence"}],
    }


def test_length_is_a_warning_not_a_failure() -> None:
    long_draft = {**_grounded(1, "high"), "description": "长" * (DESCRIPTION_MAX_CHARS + 1), "title": "标题" * 20}
    warnings = text_length_warnings_for(long_draft, 0)
    assert {item["field"] for item in warnings} == {"title", "description"}
    result = ex.validate_review_schema([{**long_draft, "reviewRunId": "R"}])
    assert result["passed"] is True
    assert any(item["code"] == "TEXT_TOO_LONG" for item in result["warnings"])


def test_cap_keeps_high_severity_grounded_first_and_merges_the_rest() -> None:
    drafts = [_downgraded(i) for i in range(1, 5)] + [_grounded(i, "low") for i in range(5, 12)] + [_grounded(12, "critical")]
    capped = cap_findings(drafts)
    assert len(capped) == MAX_FINDINGS_PER_NODE
    assert capped[0]["id"] == "F12", "critical 最先保留"
    merged = next(item for item in capped if item.get("findingType") == "merged_findings")
    assert merged["title"].startswith("其余") and merged["mergedFindingIds"]
    assert len(merged["description"]) <= DESCRIPTION_MAX_CHARS
    downgraded_kept = [item for item in capped if item["groundingStatus"] == "insufficient_evidence"]
    claims = {claim["claim"] for item in downgraded_kept for claim in item["unsupportedClaims"]}
    assert claims == {"TS1", "TS2", "TS3", "TS4"}, "多出的降级项把断言并进保留的降级项，不丢"
    assert cap_findings(drafts[:3]) == drafts[:3], "不超限不动"


def test_cap_generated_records_metadata_and_prompt_carries_format_rules() -> None:
    drafts = [_grounded(i, "medium") for i in range(1, 11)]
    capped, metadata = cap_generated_findings((drafts, {"llmCalled": True}))
    assert len(capped) == MAX_FINDINGS_PER_NODE and metadata["cappedFindings"] == {"before": 10, "after": 8, "limit": 8}
    assert any("不超过 30 字" in item for item in PROMPT_FORMAT_REQUIREMENTS)
