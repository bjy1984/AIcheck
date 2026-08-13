"""证据超预算时按整份资料裁减。

在此之前是整体失败：一个节点挂的资料合计超预算，整次审查报
REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED，一份都没审。监检既拿不到任何 AI 意见，
也不知道差多少、该拆掉哪一份。

这些用例钉的是裁减的三条安全约束，缺一条这个功能就变成危险功能。
"""

from __future__ import annotations

from libs.review_orchestrator.evidence_budget import (
    evidence_tokens_by_version,
    trim_evidence_to_budget,
    truncation_requirements,
)


def _evidence(*sizes: tuple[str, int]) -> dict[str, object]:
    """按份造证据，第二个数字控制体量。"""
    fragments = []
    for version_id, weight in sizes:
        fragments.extend(
            {"documentVersionId": version_id, "text": "证据内容" * weight}
            for _ in range(3)
        )
    return {
        "documentVersionIds": [vid for vid, _ in sizes],
        "fragments": fragments,
        "fields": [],
        "tables": [],
        "seals": [],
        "evidenceLinks": [],
    }


def test_whole_documents_are_dropped_never_half_of_one() -> None:
    """只裁整份。

    把一份证书截掉后半截，模型看到的是一份「没写有效期」的证书，会判定缺失——
    而那一栏好好地在原件上。半份资料比没有资料更危险：没有是缺证据，半份是假证据。
    """
    evidence = _evidence(("V-BIG", 400), ("V-SMALL", 10))
    trimmed, report = trim_evidence_to_budget(evidence, available_tokens=2000)
    assert report["truncated"] is True
    kept = {f["documentVersionId"] for f in trimmed["fragments"]}
    assert kept == {"V-SMALL"}, "保留的那份必须整份都在"
    assert len([f for f in trimmed["fragments"] if f["documentVersionId"] == "V-SMALL"]) == 3


def test_largest_dropped_first_to_keep_most_documents_reviewable() -> None:
    """先裁大的——目标是能被完整审到的份数最多，不是省得最多。

    与其为一份 20 页的施工方案挤掉三份证书，不如先放弃那一份。
    """
    evidence = _evidence(("V-HUGE", 900), ("V-A", 20), ("V-B", 20), ("V-C", 20))
    trimmed, report = trim_evidence_to_budget(evidence, available_tokens=2200)
    assert report["droppedVersionIds"] == ["V-HUGE"]
    assert set(trimmed["documentVersionIds"]) == {"V-A", "V-B", "V-C"}


def test_dropped_documents_are_named_not_just_id_listed() -> None:
    """裁减清单要给人看文件名，一串 ID 等于没说。"""
    evidence = _evidence(("V-BIG", 400), ("V-SMALL", 5))
    _, report = trim_evidence_to_budget(
        evidence, available_tokens=1500, version_labels={"V-BIG": "贵州化工施工方案.pdf"}
    )
    assert report["droppedNames"] == ["贵州化工施工方案.pdf"]


def test_truncation_requirements_forbid_concluding_satisfied() -> None:
    """裁过就不许给「满足要求」——模型没读全，它的「满足」就没有依据。

    也不许反过来判「缺失」：那些资料只是没送，不是没有。这两个方向都会错。
    """
    reqs = truncation_requirements(
        {"truncated": True, "droppedNames": ["产品质量证明.pdf"]}
    )
    joined = "".join(reqs)
    assert "产品质量证明.pdf" in joined
    assert "human_confirm" in joined
    assert "不得判定满足要求" in joined
    assert "不是没有" in joined, "必须挡住「未送审」被读成「缺失」"


def test_no_requirements_when_nothing_was_dropped() -> None:
    """没裁就不该往提示词里塞噪音。"""
    assert truncation_requirements({"truncated": False}) == []


def test_within_budget_evidence_is_returned_untouched() -> None:
    """没超预算时一个字节都不动。"""
    evidence = _evidence(("V-A", 5))
    trimmed, report = trim_evidence_to_budget(evidence, available_tokens=100000)
    assert trimmed is evidence
    assert report["truncated"] is False


def test_still_over_budget_is_flagged_so_caller_can_fail_loudly() -> None:
    """全裁光仍超预算时要说出来。

    这时候截断救不了（固定开销本身就装不下），必须让它响亮地失败——
    而不是送一份空证据让模型凭空判断。
    """
    evidence = _evidence(("V-A", 50))
    _, report = trim_evidence_to_budget(evidence, available_tokens=520)
    assert report["stillOverBudget"] is True


def test_token_accounting_is_per_document() -> None:
    """体量要按份统计，否则裁减顺序无从谈起。"""
    totals = evidence_tokens_by_version(_evidence(("V-A", 100), ("V-B", 5)))
    assert set(totals) == {"V-A", "V-B"}
    assert totals["V-A"] > totals["V-B"]


def test_truncated_evidence_forces_human_confirm_through_existing_guardrail() -> None:
    """端到端钉住第二条约束：裁过的证据必须降级为待人工确认。

    execution 把 groundingStatus 置为 insufficient_evidence，
    apply_grounding_guardrails 据此封顶。这两处分属不同模块，靠约定连着——
    没有这条用例，任何一边改了都不会有人发现，而后果是模型对着残缺证据
    给出「满足要求」，且看起来完全正常。
    """
    from libs.review_grounding import apply_grounding_guardrails

    draft = {
        "title": "资料齐全",
        "suggestedAction": "approve",
        "confidence": 0.95,
        "evidenceRefs": [],
    }
    guarded = apply_grounding_guardrails(
        [draft],
        {"groundingStatus": "insufficient_evidence", "documentVersionIds": ["V-A"]},
    )[0]
    assert guarded["suggestedAction"] == "human_confirm"
    assert guarded["confidence"] <= 0.5
    assert guarded["groundingStatus"] == "insufficient_evidence"


def test_truncation_requirements_reach_the_prompt() -> None:
    """接线检查：清单要真的进提示词，不是只算出来放在报告里。"""
    from libs.review_grounding import grounding_prompt_block

    block = grounding_prompt_block(
        {
            "groundingPolicy": "evidence_only",
            "truncationRequirements": ["以下资料未被送审：某某.pdf。"],
        }
    )
    assert any("某某.pdf" in str(item) for item in block["requirements"])
