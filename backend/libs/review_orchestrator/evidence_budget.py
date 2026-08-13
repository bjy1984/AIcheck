"""证据超预算时按资料整份裁减，并把裁掉了什么说清楚。

在此之前的行为是整体失败：一个节点挂的资料合计超过模型上下文预算，整次审查
直接报 REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED，一份都没审。对监检来说这是最差的
结果——他既没拿到任何 AI 意见，也不知道差多少、该拆掉哪一份。

## 三条设计约束

**一、只按整份资料裁，不裁半份。**
把一份证书截掉后半截，模型看到的是一份「没写有效期」的证书——它会据此判定
「缺少有效期」，而实际上那一栏好好地在原件上。半份资料比没有资料更危险：
没有资料是缺证据，半份资料是假证据。

**二、裁过就不能给「满足要求」。**
裁减后 groundingStatus 置为 insufficient_evidence，现有护栏
（apply_grounding_guardrails）会自动降级为待人工确认、置信度封顶 0.5。
这不是保守，是诚实：模型没读全，它的「满足」就没有依据。

**三、裁了什么必须让人看见。**
提示词里明写未送审清单并禁止对相关项下结论；同时落到 evidenceBudget 字段供
界面展示。悄悄少送几份、模型照常给结论，是这轮审计里反复出现的那类最贵的
失败——看起来一切正常。

## 裁减顺序

先裁体量最大的。目的不是省得最多，而是让**能被完整审到的资料份数最多**：
与其为一份 20 页的施工方案挤掉三份证书，不如先放弃那一份。
"""

from __future__ import annotations

import json
from typing import Any

# 与证据一起送的固定开销（工具目录、规则、模板等）留出的余量。
# 宁可少送一点，也不要卡在边界上——估算本身有误差。
BUDGET_SAFETY_MARGIN_TOKENS = 512

# 带 documentVersionId 的证据集合，按资料整份裁减时一起走
EVIDENCE_COLLECTIONS = ("fields", "tables", "seals", "fragments", "evidenceLinks")


def _tokens_of(value: Any) -> int:
    """与 estimate_messages_tokens 同口径的粗估：约 3.2 字符 1 token。"""
    return int(len(json.dumps(value, ensure_ascii=False)) / 3.2)


def evidence_tokens_by_version(evidence: dict[str, Any]) -> dict[str, int]:
    """每份资料（documentVersionId）各占多少 token。"""
    totals: dict[str, int] = {}
    for key in EVIDENCE_COLLECTIONS:
        for item in evidence.get(key) or []:
            if not isinstance(item, dict):
                continue
            version_id = str(item.get("documentVersionId") or "")
            if not version_id:
                continue
            totals[version_id] = totals.get(version_id, 0) + _tokens_of(item)
    return totals


def _without_versions(evidence: dict[str, Any], dropped: set[str]) -> dict[str, Any]:
    trimmed = dict(evidence)
    for key in EVIDENCE_COLLECTIONS:
        items = evidence.get(key)
        if not isinstance(items, list):
            continue
        trimmed[key] = [
            item
            for item in items
            if not (
                isinstance(item, dict)
                and str(item.get("documentVersionId") or "") in dropped
            )
        ]
    remaining = [
        str(item)
        for item in evidence.get("documentVersionIds") or []
        if str(item) not in dropped
    ]
    trimmed["documentVersionIds"] = remaining
    return trimmed


def trim_evidence_to_budget(
    evidence: dict[str, Any],
    *,
    available_tokens: int,
    version_labels: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """把证据裁到预算之内。返回 (裁后证据, 裁减说明)。

    裁减说明里的 droppedVersionIds 是要给人看的——不是内部诊断。
    """
    labels = version_labels or {}
    budget = max(0, int(available_tokens) - BUDGET_SAFETY_MARGIN_TOKENS)
    current = _tokens_of(evidence)
    if current <= budget:
        return evidence, {"truncated": False, "evidenceTokens": current, "budgetTokens": budget}

    per_version = evidence_tokens_by_version(evidence)
    # 大的先裁：目标是让能被完整审到的份数最多，不是省得最多
    order = sorted(per_version, key=lambda vid: -per_version[vid])
    dropped: set[str] = set()
    trimmed = evidence
    for version_id in order:
        if _tokens_of(trimmed) <= budget:
            break
        dropped.add(version_id)
        trimmed = _without_versions(evidence, dropped)

    remaining_tokens = _tokens_of(trimmed)
    kept_count = len(trimmed.get("documentVersionIds") or [])
    return trimmed, {
        "truncated": bool(dropped),
        "evidenceTokens": remaining_tokens,
        "originalTokens": current,
        "budgetTokens": budget,
        "droppedVersionIds": sorted(dropped),
        "droppedNames": [labels.get(vid) or vid for vid in sorted(dropped)],
        "keptVersionCount": kept_count,
        # 全裁光仍超预算：剩下的固定开销就已经装不下，这时候截断救不了，
        # 必须让它响亮地失败，而不是送一份空证据让模型凭空判断。
        "stillOverBudget": remaining_tokens > budget,
        # 一份都没留住 = 这次审查没有任何证据可依。线上实测踩到过：两份大资料
        # 都被裁掉，报告却说「成功」——模型会对着一份空证据集给出结论，护栏虽然
        # 会降级为待人工确认，但监检看到的是一次「做过了」的审查，实际什么都没审。
        # 裁减的前提是「还剩下能审的东西」；剩不下，就该失败。
        "nothingLeftToReview": bool(dropped) and kept_count == 0,
    }


def truncation_requirements(report: dict[str, Any]) -> list[str]:
    """写进提示词的硬性要求。

    只在证据里删掉资料是不够的——模型不知道自己少看了东西，会对着残缺的
    证据集给出一个自信的结论。必须明说：这些没送，不许当它们不存在。
    """
    if not report.get("truncated"):
        return []
    names = report.get("droppedNames") or []
    return [
        "以下资料因超出单次上下文预算未被送审："
        + "、".join(str(name) for name in names)
        + "。",
        "不得因为上述资料未出现在证据中就判定其缺失或不合规——它们只是本次没送，不是没有。",
        "任何依赖上述资料的检查项，一律输出 human_confirm，不得判定满足要求。",
    ]
