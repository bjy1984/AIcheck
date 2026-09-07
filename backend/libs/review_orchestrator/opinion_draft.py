"""顶部"AI 建议"（suggestion.opinionDraft）的取法（P9 R2）。

2026-09-06 生产统计：25 次运行里 20 次的 opinionDraft 是"模型给出的业务结论缺少证据支持……"，
因为它直接取 findingDrafts[0].description，而第一条常常就是守卫降级后的模板句。
取法改为：第一条通过守卫的发现 → 确定性结果说明 → 统计句；永远不取模板句。
"""

from __future__ import annotations

from typing import Any

DOWNGRADED_FINDING_TITLE = "证据不足，需人工确认"
_DETERMINISTIC_OPINION = {
    "passed": "确定性核验通过，AI 未形成额外有依据的发现；请按证据链人工确认。",
    "failed": "确定性核验未通过，请按规则结果处理；AI 发现均未获证据支持。",
    "evidence_insufficient": "确定性核验证据不足，AI 发现也均未获证据支持，请补充资料后复核。",
    "not_applicable": "本节点规则不适用，请人工确认。",
}


def opinion_draft_from_findings(
    drafts: list[dict[str, Any]], *, deterministic_verdict: str = ""
) -> dict[str, Any]:
    grounded = [
        item
        for item in drafts
        if isinstance(item, dict)
        and item.get("groundingStatus") == "grounded"
        and not str(item.get("title") or "").startswith(DOWNGRADED_FINDING_TITLE)
    ]
    if grounded:
        first = grounded[0]
        title = str(first.get("title") or "").strip()
        description = " ".join(str(first.get("description") or "").split())
        text = f"{title}：{description[:150]}" if description else title
        return {
            "text": text or "AI 审查草稿已生成。",
            "source": "grounded_finding",
            "confidence": float(first.get("confidence") or 0.82),
        }
    downgraded = [item for item in drafts if isinstance(item, dict)]
    verdict = str(deterministic_verdict or "").strip().lower()
    if verdict in _DETERMINISTIC_OPINION:
        text = _DETERMINISTIC_OPINION[verdict]
        if downgraded:
            text += f"（{len(downgraded)} 条 AI 发现待人工核对）"
        return {"text": text, "source": "deterministic_result", "confidence": 0.5}
    if downgraded:
        return {
            "text": f"AI 形成 {len(downgraded)} 条发现，均未获证据支持，已折叠为待核对项，请人工核对原件。",
            "source": "downgraded_summary",
            "confidence": 0.5,
        }
    return {"text": "AI 审查草稿已生成。", "source": "empty", "confidence": 0.5}
