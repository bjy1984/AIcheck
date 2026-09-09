"""P9 R3 输出契约：标题 ≤30 字只说差距、正文 ≤150 字、每节点 ≤8 条（多出归并）。

审计（2026-09-06）：正文最长 884 字且含 JSON，节点 2 一次 13 条并排。长度在校验层只记
TEXT_TOO_LONG 警告（不判失败——截断会把"差在哪"截掉，比长更糟）；条数在生成后按优先级
截到 8 条，多出的通过守卫的发现归并成一条"其余 N 条已归并"（标题由代码生成，不进守卫），
多出的降级条目只把待核对断言并进最后一条降级项。提示词同时写明这三条格式约束。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

TITLE_MAX_CHARS = 30
DESCRIPTION_MAX_CHARS = 150
MAX_FINDINGS_PER_NODE = 8
DOWNGRADED_TITLE = "证据不足，需人工确认"
MERGED_TITLE_PREFIX = "其余"
_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}

PROMPT_FORMAT_REQUIREMENTS = [
    f"每条 finding 的 title 不超过 {TITLE_MAX_CHARS} 字、只说差距（查到什么不一致），不写结论套话。",
    f"description 不超过 {DESCRIPTION_MAX_CHARS} 字，固定写法：查到什么 → 差在哪 → 怎么做；不要输出 JSON 或表格原文。",
    f"每个节点最多 {MAX_FINDINGS_PER_NODE} 条 finding，同一问题不要拆成多条；超出的合并写。",
]


def prompt_format_requirements(*, complete: bool = False) -> list[str]:
    if not complete:
        return list(PROMPT_FORMAT_REQUIREMENTS)
    return [
        *PROMPT_FORMAT_REQUIREMENTS[:2],
        "保留每个独立问题及其原子审查项和完整证据引用，不得为了条数限制合并或省略不同问题；同一问题不要重复输出。",
    ]


def text_length_warnings_for(draft: dict[str, Any], index: int) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for field, limit in (("title", TITLE_MAX_CHARS), ("description", DESCRIPTION_MAX_CHARS)):
        length = len(" ".join(str(draft.get(field) or "").split()))
        if length > limit:
            warnings.append({"code": "TEXT_TOO_LONG", "index": index, "field": field, "length": length, "limit": limit})
    return warnings


def _is_downgraded(draft: dict[str, Any]) -> bool:
    return str(draft.get("title") or "").startswith(DOWNGRADED_TITLE) or str(draft.get("groundingStatus") or "") == "insufficient_evidence"


def _priority(draft: dict[str, Any]) -> tuple[int, int]:
    return (0 if not _is_downgraded(draft) else 1, -_SEVERITY_RANK.get(str(draft.get("severity") or "").lower(), 0))


def _merge_grounded(extras: list[dict[str, Any]], template: dict[str, Any]) -> dict[str, Any]:
    titles = [" ".join(str(item.get("title") or "").split()) for item in extras]
    body = "；".join(titles)
    description = f"另有 {len(extras)} 条通过证据核对的发现已归并：{body}"
    if len(description) > DESCRIPTION_MAX_CHARS:
        description = description[: DESCRIPTION_MAX_CHARS - 1] + "…"
    severity = max(extras, key=lambda item: _SEVERITY_RANK.get(str(item.get("severity") or "").lower(), 0)).get("severity")
    evidence_refs: list[Any] = []
    for item in extras:
        for ref in item.get("evidenceRefs") or []:
            if ref not in evidence_refs:
                evidence_refs.append(ref)
    merged = {
        **{key: template.get(key) for key in ("reviewRunId", "projectId", "nodeId", "businessPackId", "agentId", "agentVersion")},
        "id": f"{template.get('id') or 'FND-DRAFT'}-MERGED",
        "findingType": "merged_findings",
        "severity": severity,
        "title": f"{MERGED_TITLE_PREFIX} {len(extras)} 条发现已归并",
        "description": description,
        "evidenceRefs": evidence_refs[:6],
        "ruleRefs": [ref for item in extras for ref in item.get("ruleRefs") or []][:6],
        "kbRefs": [],
        "confidence": min(float(item.get("confidence") or 0.5) for item in extras),
        "suggestedAction": "human_confirm",
        "groundingStatus": "grounded",
        "unsupportedClaims": [],
        "requiresHumanConfirmation": True,
        "mergedFindingIds": [str(item.get("id") or "") for item in extras],
        "mergedTitles": titles,
        "llmGenerated": False,
    }
    return merged


def cap_findings(drafts: list[dict[str, Any]], *, limit: int = MAX_FINDINGS_PER_NODE) -> list[dict[str, Any]]:
    """按优先级保留 limit 条；多出的通过守卫项归并成一条，多出的降级项把断言并进保留的降级项。总数永不超过 limit。"""
    items = deepcopy([item for item in drafts if isinstance(item, dict)])
    if len(items) <= limit:
        return items
    ordered = sorted(items, key=_priority)
    kept = ordered[:limit]
    extra_grounded = [item for item in ordered[limit:] if not _is_downgraded(item)]
    extra_downgraded = [item for item in ordered[limit:] if _is_downgraded(item)]
    # 归并条 / 降级汇总条要占名额：从保留区尾部让位，让出的条目本身也进入待归并，直到放得下为止
    def needed_slots() -> int:
        return int(bool(extra_grounded)) + int(bool(extra_downgraded) and not any(_is_downgraded(item) for item in kept))

    while kept and len(kept) + needed_slots() > limit:
        spill = kept.pop()
        (extra_downgraded if _is_downgraded(spill) else extra_grounded).insert(0, spill)
    if extra_grounded:
        kept.append(_merge_grounded(extra_grounded, template=extra_grounded[0]))
    if extra_downgraded:
        target = next((item for item in reversed(kept) if _is_downgraded(item)), None)
        if target is None:
            target = {**extra_downgraded[0], "mergedFindingIds": []}
            kept.append(target)
            extra_downgraded = extra_downgraded[1:]
        claims = list(target.get("unsupportedClaims") or [])
        for item in extra_downgraded:
            for claim in item.get("unsupportedClaims") or []:
                if claim not in claims:
                    claims.append(claim)
        target["unsupportedClaims"] = claims
        target["mergedFindingIds"] = [*(target.get("mergedFindingIds") or []), *(str(item.get("id") or "") for item in extra_downgraded)]
    return kept[:limit]


def cap_generated_findings(
    generated: tuple[list[dict[str, Any]], dict[str, Any]], *, complete: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    drafts, metadata = generated
    if complete:
        return drafts, {**metadata, "findingRetention": "complete", "findingCount": len(drafts)}
    capped = cap_findings(drafts)
    if len(capped) != len(drafts):
        metadata = {**metadata, "cappedFindings": {"before": len(drafts), "after": len(capped), "limit": MAX_FINDINGS_PER_NODE}}
    return capped, metadata


def store_generated_findings(review_run, drafts, *, complete, hash_payload):
    review_run["findingDrafts"] = deepcopy(drafts)
    if complete:
        review_run["findingRetention"] = "complete"
        review_run["findingSummaryDrafts"] = cap_findings(review_run["findingDrafts"])
    review_run["outputHash"] = hash_payload(review_run["findingDrafts"])
    return {"findingDrafts": len(review_run["findingDrafts"]), "outputHash": review_run["outputHash"]}
