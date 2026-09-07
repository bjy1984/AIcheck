"""P12 F2：审计反馈飞轮的指标（《优化计划-焊接节点》§17.3），全部从真实采集数据算。

数据来源与口径：
- 采集覆盖率：有 AI 审查（ai_runs）的 (project, node) 里，有人工结论（review_opinions）的比例。
- 采纳率：人工结论 = AI 建议映射值 的比例（分母只算 AI 建议能映射到人工选项的）。
- 覆盖差异率：review_opinions.overriddenFromAi 为真的比例。
- 发现级精确率：人工对单条发现的反馈里被采纳的比例（ai_feedback.findingId 非空：accepted vs 其它类型）。
- 补充发现数：missed_issue 反馈条数（召回率的分子，分母要等人工补充全量，先给计数）。
- 降级率：AI 发现里 groundingStatus=insufficient_evidence 的比例；误降级率：guard_false_downgrade 反馈数 / 降级发现数。
- 证据引用准确率：node_evidence_links 里人工确认 / (确认 + 驳回)。
- 根因分布：ai_feedback.rootCause 七类计数。
橡皮图章指数需要 F4 盲审，这里不算。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

AI_RESULT_TO_OPINION = {
    "建议满足要求": "满足要求",
    "满足要求": "满足要求",
    "建议不符合": "需补正",
    "需补正": "需补正",
    "建议不适用": "不适用",
    "不适用": "不适用",
    "证据不足": "证据不足",
}
ROOT_CAUSES = ("data_table", "rule_logic", "guard_downgrade", "evidence_extraction", "prompt", "policy", "external_source", "other")
REJECT_FEEDBACK_TYPES = {"rejected_false_positive", "wrong_evidence", "wrong_rule_reference", "wrong_severity", "hallucination"}


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _key(item: dict[str, Any]) -> tuple[str, int]:
    return (str(item.get("projectId") or ""), int(item.get("nodeId") or 0))


def _rubber_stamp_value(state: dict[str, Any]) -> float | None:
    from libs.feedback.blind_review import (
        rubber_stamp_index,  # 延迟导入：blind_review 也依赖本模块的结果映射
    )

    return rubber_stamp_index(state).get("value")


def compute_feedback_metrics(state: dict[str, Any]) -> dict[str, Any]:
    ai_runs = [item for item in state.get("ai_runs") or [] if isinstance(item, dict)]
    opinions = [item for item in state.get("review_opinions") or [] if isinstance(item, dict)]
    feedback = [item for item in state.get("ai_feedback") or [] if isinstance(item, dict)]
    links = [item for item in state.get("node_evidence_links") or [] if isinstance(item, dict)]

    reviewed_nodes = {_key(item) for item in ai_runs if item.get("projectId")}
    opinion_nodes = {_key(item) for item in opinions if item.get("projectId")}
    covered = reviewed_nodes & opinion_nodes

    comparable = [item for item in opinions if AI_RESULT_TO_OPINION.get(str(item.get("aiSuggestedResult") or ""))]
    adopted = [item for item in comparable if AI_RESULT_TO_OPINION[str(item["aiSuggestedResult"])] == str(item.get("result") or "")]
    overridden = [item for item in opinions if item.get("aiSuggestedResult") and item.get("overriddenFromAi") is True]

    finding_feedback = [item for item in feedback if item.get("findingId")]
    finding_accepted = [item for item in finding_feedback if item.get("feedbackType") == "accepted" or item.get("accepted") is True]
    finding_rejected = [item for item in finding_feedback if item.get("feedbackType") in REJECT_FEEDBACK_TYPES]
    missed = [item for item in feedback if item.get("feedbackType") == "missed_issue"]
    guard_false = [item for item in feedback if item.get("feedbackType") == "guard_false_downgrade"]

    findings = [
        finding
        for run in ai_runs
        for finding in (run.get("findings") or run.get("findingDrafts") or [])
        if isinstance(finding, dict)
    ]
    downgraded = [item for item in findings if str(item.get("groundingStatus") or "") == "insufficient_evidence"]

    decided_links = [item for item in links if str(item.get("manualStatus") or "").lower() in {"confirmed", "rejected"}]
    confirmed_links = [item for item in decided_links if str(item.get("manualStatus") or "").lower() == "confirmed"]

    root_causes = Counter(str(item.get("rootCause")) for item in feedback if item.get("rootCause"))
    sources = Counter(str(item.get("source") or "unknown") for item in feedback)

    return {
        "schemaVersion": "FeedbackMetrics@1.0.0",
        "counts": {
            "aiRuns": len(ai_runs),
            "reviewedNodes": len(reviewed_nodes),
            "reviewOpinions": len(opinions),
            "aiFeedback": len(feedback),
            "findings": len(findings),
            "evidenceLinksDecided": len(decided_links),
        },
        "collectionCoverage": {"value": _ratio(len(covered), len(reviewed_nodes)), "numerator": len(covered), "denominator": len(reviewed_nodes), "target": ">=0.95"},
        "adoptionRate": {"value": _ratio(len(adopted), len(comparable)), "numerator": len(adopted), "denominator": len(comparable)},
        "overrideRate": {"value": _ratio(len(overridden), len(comparable)), "numerator": len(overridden), "denominator": len(comparable)},
        "findingPrecision": {
            "value": _ratio(len(finding_accepted), len(finding_accepted) + len(finding_rejected)),
            "numerator": len(finding_accepted),
            "denominator": len(finding_accepted) + len(finding_rejected),
        },
        "supplementalFindings": len(missed),
        "downgradeRate": {"value": _ratio(len(downgraded), len(findings)), "numerator": len(downgraded), "denominator": len(findings)},
        "falseDowngradeRate": {"value": _ratio(len(guard_false), len(downgraded)), "numerator": len(guard_false), "denominator": len(downgraded)},
        "evidenceReferenceAccuracy": {"value": _ratio(len(confirmed_links), len(decided_links)), "numerator": len(confirmed_links), "denominator": len(decided_links)},
        "rootCauses": {cause: root_causes.get(cause, 0) for cause in ROOT_CAUSES},
        "feedbackSources": dict(sources),
        "rubberStampIndex": _rubber_stamp_value(state),
    }


def _fmt(metric: dict[str, Any]) -> str:
    value = metric.get("value")
    if value is None:
        return f"—（{metric.get('numerator', 0)}/{metric.get('denominator', 0)}）"
    return f"{value * 100:.1f}%（{metric.get('numerator', 0)}/{metric.get('denominator', 0)}）"


def render_markdown(metrics: dict[str, Any]) -> str:
    rows = [
        ("采集覆盖率", _fmt(metrics["collectionCoverage"]), "≥ 95%"),
        ("采纳率", _fmt(metrics["adoptionRate"]), "高，但不趋 100%"),
        ("覆盖差异率", _fmt(metrics["overrideRate"]), "逐版下降"),
        ("发现级精确率", _fmt(metrics["findingPrecision"]), "上升"),
        ("补充发现数", str(metrics["supplementalFindings"]), "召回率分子"),
        ("降级率", _fmt(metrics["downgradeRate"]), "下降"),
        ("误降级率", _fmt(metrics["falseDowngradeRate"]), "下降"),
        ("证据引用准确率", _fmt(metrics["evidenceReferenceAccuracy"]), "上升"),
        ("橡皮图章指数", "待 F4 盲审" if metrics.get("rubberStampIndex") is None else f"{metrics['rubberStampIndex']:+.3f}", "不趋零"),
    ]
    text = "| 指标 | 当前值 | 方向 |\n|---|---|---|\n" + "".join(f"| {name} | {value} | {direction} |\n" for name, value, direction in rows)
    causes = metrics.get("rootCauses") or {}
    text += "\n根因分布：" + "、".join(f"{cause} {count}" for cause, count in causes.items()) + "\n"
    return text
