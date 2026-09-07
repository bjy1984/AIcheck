"""P8 H5 清单填表模式（AICHECK_REVIEW_PROMPT_MODE=checklist）。

自由模式让模型"想出"审查结构：写标题、写长描述、下肯定结论——小模型写不出结构，
大模型写出来的一半被守卫丢掉（2026-09-06 六模型实测）。清单模式把结构收回代码：

- 清单项来自本节点的原子检查项（atomic_checks.yaml）与必传资料（node_requirements）；
- 模型对每项只填 {itemId, verdict ∈ 符合|不符合|证据不足|需人工确认, evidenceRefs, note}，
  另可给最多 3 条 extraFindings（清单之外的问题）；
- 标题由代码按清单项生成，严重度来自规则；肯定结论词只出现在代码生成的标题里，
  守卫只对 note 与 extraFindings 做断言核对。

灰度：默认 freeform；基准脚本 --prompt-mode 同时跑两种模式，用 extraFindings 命中率
判断清单模式有没有漏掉自由模式能发现的问题。
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from libs.integrations.errors import IntegrationServiceError

VERDICTS = ("符合", "不符合", "证据不足", "需人工确认")
MAX_EXTRA_FINDINGS = 3
NOTE_MAX_CHARS = 150
_VERDICT_ALIASES = {
    "pass": "符合",
    "passed": "符合",
    "compliant": "符合",
    "fail": "不符合",
    "failed": "不符合",
    "non_compliant": "不符合",
    "insufficient": "证据不足",
    "evidence_insufficient": "证据不足",
    "insufficient_evidence": "证据不足",
    "human_confirm": "需人工确认",
    "needs_human": "需人工确认",
}
_VERDICT_SEVERITY_FLOOR = {"不符合": None, "证据不足": "medium", "需人工确认": "low", "符合": "low"}
_VERDICT_FINDING_TYPE = {
    "符合": "checklist_pass",
    "不符合": "checklist_fail",
    "证据不足": "checklist_evidence_insufficient",
    "需人工确认": "checklist_human_confirm",
}


def review_prompt_mode() -> str:
    value = str(os.getenv("AICHECK_REVIEW_PROMPT_MODE") or "freeform").strip().lower()
    return "checklist" if value == "checklist" else "freeform"


def checklist_enabled() -> bool:
    return review_prompt_mode() == "checklist"


def _rule_for(pack: dict[str, Any], rule_id: str, source_rule_id: str) -> dict[str, Any]:
    for rule in [*(pack.get("ruleSets") or []), *(pack.get("rules") or [])]:
        if not isinstance(rule, dict):
            continue
        if str(rule.get("id") or "") == rule_id or (source_rule_id and str(rule.get("sourceRuleId") or "") == source_rule_id):
            return rule
    return {}


def build_checklist_items(pack: dict[str, Any], node_id: int, requirements: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """清单 = 本节点原子检查项 + 必传/条件必传资料。每项带 ruleCode 与 expectedEvidence。"""
    items: list[dict[str, Any]] = []
    for check in pack.get("atomicChecks") or []:
        if not isinstance(check, dict) or int(check.get("nodeId") or 0) != int(node_id):
            continue
        rule = _rule_for(pack, str(check.get("ruleId") or ""), str(check.get("sourceRuleId") or ""))
        items.append(
            {
                "itemId": str(check.get("id")),
                "question": f"{check.get('name') or ''}：{check.get('instruction') or ''}".strip("："),
                "ruleCode": str(rule.get("ruleKey") or check.get("sourceRuleId") or check.get("ruleId") or ""),
                "ruleSetVersion": str(rule.get("version") or ""),
                "severity": str(rule.get("severity") or "medium"),
                "expectedEvidence": "需引用 OCR 证据" if check.get("evidenceRequired") else "可无证据",
                "kind": "atomic_check",
            }
        )
    for requirement in requirements or []:
        if not isinstance(requirement, dict):
            continue
        required_type = str(requirement.get("requiredType") or "")
        if required_type == "可选":
            continue
        items.append(
            {
                "itemId": str(requirement.get("id") or f"REQ-{node_id}-{len(items) + 1}"),
                "question": f"是否已提交 {requirement.get('name') or requirement.get('materialTypeName') or '资料'}（{required_type or '必传'}）",
                "ruleCode": "",
                "ruleSetVersion": "",
                "severity": "high" if required_type == "必传" else "medium",
                "expectedEvidence": "需引用该资料的证据",
                "kind": "material_requirement",
            }
        )
    return items


CHECKLIST_REQUIREMENTS = [
    "本次为清单填表：对 checklist 里每一项只填 itemId、verdict、evidenceRefs、note，不要复述题目。",
    "verdict 只能是 符合 / 不符合 / 证据不足 / 需人工确认 四选一；没有证据支持的项不得填 符合。",
    "note 不超过 120 字，按“查到什么 → 差在哪 → 怎么做”写；不要下结论性套话。",
    "清单之外发现的问题写进 extraFindings，最多 3 条，格式同自由模式的 finding。",
]


def apply_to_payload(user_payload: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    payload = dict(user_payload)
    payload["task"] = "Fill the ReviewChecklist JSON only."
    payload["promptMode"] = "checklist"
    payload["checklist"] = [
        {key: item[key] for key in ("itemId", "question", "ruleCode", "expectedEvidence")} for item in items
    ]
    payload["requirements"] = [*list(payload.get("requirements") or []), *CHECKLIST_REQUIREMENTS]
    finding_schema = ((payload.get("outputSchema") or {}).get("findings") or [{}])[0]
    payload["outputSchema"] = {
        "checklist": [
            {
                "itemId": "string",
                "verdict": "符合|不符合|证据不足|需人工确认",
                "evidenceRefs": finding_schema.get("evidenceRefs") or [],
                "note": "string(<=120)",
            }
        ],
        "extraFindings": [finding_schema],
    }
    return payload


REPAIR_PROMPT = (
    "你上一次的输出没有满足输出契约。下面是你自己的原始输出。"
    "请只输出一个 JSON 对象，形如 {\"checklist\": [{\"itemId\", \"verdict\", \"evidenceRefs\", \"note\"}], "
    "\"extraFindings\": [...]}。不要解释，不要 Markdown 代码块，不要新增原始输出里没有的事实。"
)


def _normalize_verdict(value: Any) -> str | None:
    text = str(value or "").strip()
    if text in VERDICTS:
        return text
    return _VERDICT_ALIASES.get(text.lower())


def _rank(severity: str) -> int:
    return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(str(severity or "").lower(), 2)


def _item_severity(item: dict[str, Any], verdict: str) -> str:
    rule_severity = str(item.get("severity") or "medium")
    floor = _VERDICT_SEVERITY_FLOOR.get(verdict)
    if verdict == "不符合":
        return rule_severity
    return floor if floor and _rank(floor) < _rank(rule_severity) else (floor or rule_severity)


def normalize_checklist_output(
    review_run: dict[str, Any],
    context: dict[str, Any],
    content: str,
    *,
    base: dict[str, Any],
    grounding_input: dict[str, Any],
    guard: Callable[[list[dict[str, Any]], dict[str, Any]], list[dict[str, Any]]],
    clone: Callable[[Any], Any],
    bounded_confidence: Callable[..., float],
) -> list[dict[str, Any]]:
    """把模型填的清单组装成 finding 草稿；守卫只核对 note 与 extraFindings。"""
    if not content.strip():
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason="LLM_OUTPUT_EMPTY")
    try:
        parsed = json.loads(content)
    except ValueError as exc:
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason="LLM_OUTPUT_INVALID_JSON") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("checklist"), list):
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason="LLM_OUTPUT_INVALID_ENVELOPE")
    items_by_id = {str(item["itemId"]): item for item in context.get("checklistItems") or []}
    if not items_by_id:
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason="REVIEW_CHECKLIST_MISSING")

    drafts: list[dict[str, Any]] = []
    code_titles: dict[str, str] = {}
    summary = {verdict: 0 for verdict in VERDICTS}
    summary["unknownItems"] = 0
    for row in parsed["checklist"]:
        if not isinstance(row, dict):
            continue
        item = items_by_id.get(str(row.get("itemId") or ""))
        verdict = _normalize_verdict(row.get("verdict"))
        if item is None or verdict is None:
            summary["unknownItems"] += 1
            continue
        evidence_refs = clone(row.get("evidenceRefs")) if isinstance(row.get("evidenceRefs"), list) else []
        if verdict == "符合" and not evidence_refs:
            verdict = "证据不足"  # 没有证据的"符合"不成立：规则明说过，这里兜底
        summary[verdict] += 1
        note = " ".join(str(row.get("note") or "").split())[:NOTE_MAX_CHARS]
        draft = clone(base)
        draft["id"] = f"FND-DRAFT-{uuid4().hex[:8].upper()}"
        draft["findingType"] = _VERDICT_FINDING_TYPE[verdict]
        draft["severity"] = _item_severity(item, verdict)
        # 标题由代码生成：肯定结论词只出现在这里，守卫不核对它
        question_head = str(item.get("question") or "").split("：")[0][:30]
        title = f"{question_head}：{verdict}"
        code_titles[draft["id"]] = title
        draft["title"] = "清单项"
        draft["description"] = note or f"模型对该项填写为“{verdict}”，未附说明。"
        draft["evidenceRefs"] = evidence_refs
        draft["ruleRefs"] = (
            [{"ruleCode": item["ruleCode"], "ruleSetVersion": item.get("ruleSetVersion") or ""}] if item.get("ruleCode") else []
        )
        draft["kbRefs"] = []
        draft["confidence"] = bounded_confidence(row.get("confidence"), default=base["confidence"])
        draft["suggestedAction"] = "request_correction" if verdict == "不符合" else "human_confirm"
        draft["groundingStatus"] = "grounded" if evidence_refs else "insufficient_evidence"
        draft["unsupportedClaims"] = []
        draft["checklistItemId"] = item["itemId"]
        draft["checklistVerdict"] = verdict
        draft["requiresHumanConfirmation"] = True
        draft["llmGenerated"] = True
        drafts.append(draft)

    extra = parsed.get("extraFindings") if isinstance(parsed.get("extraFindings"), list) else []
    for item in [row for row in extra if isinstance(row, dict)][:MAX_EXTRA_FINDINGS]:
        draft = clone(base)
        draft["id"] = f"FND-DRAFT-{uuid4().hex[:8].upper()}"
        draft["findingType"] = str(item.get("findingType") or "checklist_extra")
        draft["severity"] = str(item.get("severity") or base["severity"])
        draft["title"] = str(item.get("title") or base["title"])
        draft["description"] = str(item.get("description") or base["description"])
        draft["evidenceRefs"] = clone(item.get("evidenceRefs")) if isinstance(item.get("evidenceRefs"), list) else []
        draft["ruleRefs"] = clone(item.get("ruleRefs")) if isinstance(item.get("ruleRefs"), list) else []
        draft["kbRefs"] = clone(item.get("kbRefs")) if isinstance(item.get("kbRefs"), list) else []
        draft["confidence"] = bounded_confidence(item.get("confidence"), default=base["confidence"])
        draft["suggestedAction"] = str(item.get("suggestedAction") or "human_confirm")
        draft["groundingStatus"] = str(item.get("groundingStatus") or base.get("groundingStatus") or "")
        draft["unsupportedClaims"] = item.get("unsupportedClaims") if isinstance(item.get("unsupportedClaims"), list) else []
        draft["checklistExtra"] = True
        draft["requiresHumanConfirmation"] = True
        draft["llmGenerated"] = True
        drafts.append(draft)
    if not drafts:
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason="LLM_OUTPUT_EMPTY_FINDINGS")

    guarded = guard(drafts, grounding_input)
    for draft in guarded:
        title = code_titles.get(str(draft.get("id")))
        if not title:
            continue
        if not draft.get("evidenceRefs"):
            # 没引用任何证据的清单项：不管守卫怎么判，都只能是证据不足（verdict 已改写为 证据不足）
            draft["groundingStatus"] = "insufficient_evidence"
            draft["suggestedAction"] = "human_confirm"
            draft["confidence"] = min(float(draft.get("confidence") or 0.5), 0.5)
            draft["title"] = title
        elif draft.get("groundingStatus") == "grounded":
            draft["title"] = title
        else:
            draft["modelTitle"] = title  # 降级的清单项：模板标题照旧，代码标题留作原文
    metadata = review_run.get("llmMetadata") if isinstance(review_run.get("llmMetadata"), dict) else {}
    metadata["checklistSummary"] = {**summary, "extraFindings": min(len(extra), MAX_EXTRA_FINDINGS), "items": len(items_by_id)}
    review_run["llmMetadata"] = metadata
    return guarded
