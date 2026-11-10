"""AI审查助手读「人工在系统里留下的东西」（2026-11-10，记忆评估里「与审查事实一致」一项）。

监检在审查页面上做过三类事，审查流水线都认，但对话助手原来一样也看不到：

- 人工修正的事实字段（`fact_corrections`）：OCR 把证书号认错了，监检改成对的。
  正式复核会把修正值覆盖到事实上；对话助手读 OCR 原值，会照着错的回答。
- 监检的人工意见（`review_opinions`）：满足要求、需补正等。这是节点的终局口径。
- 证据的人工确认或驳回（`manualStatus`）。

这里只做**只读汇总**：给模型一份「人工已经定了什么」，并要求它如实写明，不得用 OCR 原值
覆盖，也不得把人工意见说成自己的判定。人工记录本身不在这里改。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

#: 回答上下文里带的精简版；工具返回完整版
CONTEXT_LIMITS = {"items": 8, "chars": 120}
TOOL_LIMITS = {"items": 20, "chars": 200}

NOTICE = (
    "人工修正的字段值与监检的人工意见，优先于 OCR 抽取值和 AI 判定。回答涉及这些字段或节点结论时，"
    "须写明「人工已修正」或「人工已出意见」，不得用 OCR 原值覆盖，也不得把人工意见说成自己的判定。"
)


def _text(value: Any, limit: int) -> str:
    text = str(value if value is not None else "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _same_node(row: dict[str, Any], project_id: str, node_id: int) -> bool:
    return str(row.get("projectId") or "") == project_id and int(row.get("nodeId") or 0) == int(
        node_id
    )


def human_records_signature(state: dict[str, Any], project_id: str, node_id: int) -> dict[str, Any]:
    """这一刻节点上的人工记录指纹：有效修正的编号、最新人工意见。

    每条回答落库时记下它（`humanRecordsSeen`），之后拿它和现在比，就能说清回答为什么过期：
    是「此后有人工修正」，而不是笼统的「证据变了」。"""
    active = sorted(
        str(row.get("id") or "")
        for row in state.get("fact_corrections", []) or []
        if _same_node(row, project_id, node_id) and row.get("status") == "active"
    )
    opinions = sorted(
        (
            row
            for row in state.get("review_opinions", []) or []
            if _same_node(row, project_id, node_id)
        ),
        key=lambda row: str(row.get("createdAt") or ""),
        reverse=True,
    )
    latest = opinions[0] if opinions else {}
    return {
        "correctionIds": active[:50],
        "opinionId": latest.get("id"),
        "opinionResult": latest.get("result"),
    }


def human_records_change_text(seen: dict[str, Any], current: dict[str, Any]) -> str:
    """回答当时看到的人工记录和现在比，变了什么；没变返回空串。"""
    before, after = set(seen.get("correctionIds") or []), set(current.get("correctionIds") or [])
    parts = []
    if after - before:
        parts.append(f"新增人工修正 {len(after - before)} 处")
    if before - after:
        parts.append(f"撤销或替换人工修正 {len(before - after)} 处")
    if seen.get("opinionId") != current.get("opinionId") or seen.get(
        "opinionResult"
    ) != current.get("opinionResult"):
        parts.append(f"人工意见变为“{current.get('opinionResult') or '无'}”")
    return "，".join(parts)


def human_review_records(
    state: dict[str, Any],
    project_id: str,
    node_id: int,
    *,
    evidence_links: list[dict[str, Any]] | None = None,
    limits: dict[str, int] = TOOL_LIMITS,
) -> dict[str, Any]:
    """本项目本节点的人工修正、最新人工意见、证据人工状态计数。只读，不改任何记录。"""
    max_items, max_chars = limits["items"], limits["chars"]
    file_names = {
        str(item.get("documentVersionId") or ""): item.get("fileName") or item.get("documentName")
        for item in evidence_links or []
        if item.get("documentVersionId")
    }

    def same_node(row: dict[str, Any]) -> bool:
        return str(row.get("projectId") or "") == project_id and int(row.get("nodeId") or 0) == int(
            node_id
        )

    corrections = [row for row in state.get("fact_corrections", []) or [] if same_node(row)]
    active = sorted(
        (row for row in corrections if row.get("status") == "active"),
        key=lambda row: str(row.get("createdAt") or ""),
        reverse=True,
    )
    opinions = sorted(
        (row for row in state.get("review_opinions", []) or [] if same_node(row)),
        key=lambda row: str(row.get("createdAt") or ""),
        reverse=True,
    )
    latest = opinions[0] if opinions else None
    decisions = Counter(
        str(item.get("manualStatus") or "pending").lower() for item in evidence_links or []
    )
    return {
        "status": "succeeded",
        "hasHumanRecords": bool(
            active or latest or decisions.get("confirmed") or decisions.get("rejected")
        ),
        "correctionCount": len(active),
        "withdrawnCorrectionCount": len(corrections) - len(active),
        "factCorrections": [
            {
                "correctionId": row.get("id"),
                "fieldName": row.get("fieldName"),
                "factPath": row.get("factPath"),
                "originalValue": _text(row.get("originalValue"), max_chars),
                "correctedValue": _text(row.get("correctedValue"), max_chars),
                "reason": _text(row.get("reason"), max_chars),
                "correctedBy": row.get("correctedBy"),
                "correctedAt": row.get("createdAt"),
                "documentVersionId": row.get("documentVersionId"),
                "fileName": file_names.get(str(row.get("documentVersionId") or "")),
            }
            for row in active[:max_items]
        ],
        "latestOpinion": None
        if latest is None
        else {
            "opinionId": latest.get("id"),
            "result": latest.get("result"),
            "opinion": _text(latest.get("opinion"), max_chars * 2),
            "reviewerName": latest.get("reviewerName"),
            "createdAt": latest.get("createdAt"),
        },
        "opinionCount": len(opinions),
        "evidenceDecisions": dict(decisions),
        "notice": NOTICE,
    }


def human_records_for_context(
    state: dict[str, Any], project_id: str, node_id: int, evidence_links: list[dict[str, Any]]
) -> dict[str, Any]:
    """每轮提问都带的精简版：让模型知道有人工记录，细节再用 get_human_review_records 取。"""
    return human_review_records(
        state, project_id, node_id, evidence_links=evidence_links, limits=CONTEXT_LIMITS
    )
