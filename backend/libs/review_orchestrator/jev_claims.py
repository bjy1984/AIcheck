"""Verify Qwen's explicit finding claims against whole-document Jev state.

Until inspector calibration is approved, this only records shadow checks. The
optional rejection gate needs a separately supplied threshold; it cannot be
enabled accidentally by the generic Jev switch.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from libs.review_orchestrator.jev_client import MODEL, ask_jev, jev_stage_enabled
from libs.review_orchestrator.jev_state import MAX_STATE_CHARS, scoped_document_states

CLAIM_CHOICES = {
    "supported": "工程资料原文或无冲突的已核实检查支持这句话",
    "contradicted": "工程资料原文明确否定这句话",
    "not_in_materials": "提供的资料里找不到这句话所断言的编号、数值或事实",
    "needs_human": "需要专业解释、外部平台核验，或无法只凭这些资料判断",
}
SAFE_DESCRIPTION = "这条发现中的断言未通过逐句核对，原判断已撤下。请核对本节点原文及规则结果后人工确认。"


def _downgrade(draft: dict[str, Any], claims: list[str]) -> None:
    draft["title"] = "证据不足，需人工确认"
    draft["description"] = SAFE_DESCRIPTION
    draft["groundingStatus"] = "insufficient_evidence"
    draft["confidence"] = min(float(draft.get("confidence") or 0), 0.55)
    draft["requiresHumanConfirmation"] = True
    draft.setdefault("unsupportedClaims", []).extend(claims or ["claim_check_unavailable"])


def _rejection_threshold() -> float | None:
    if os.getenv("AICHECK_JEV_CALIBRATION_APPROVED", "").lower() not in {"1", "true", "yes"}:
        return None
    if os.getenv("AICHECK_JEV_CLAIM_GATE_ENABLED", "").lower() not in {"1", "true", "yes"}:
        return None
    raw = os.getenv("AICHECK_JEV_CLAIM_REJECT_CONFIDENCE")
    try:
        value = float(raw) if raw is not None else None
    except ValueError:
        return None
    return value if value is not None and 0 < value <= 1 else None


def _combine(answers: list[dict[str, Any]]) -> tuple[str, float]:
    choices = {str(answer["choice"]) for answer in answers}
    if len(choices) == 1:
        return next(iter(choices)), min(float(answer["confidence"]) for answer in answers)
    if choices <= {"supported", "not_in_materials"}:
        return "supported", min(float(answer["confidence"]) for answer in answers if answer["choice"] == "supported")
    return "needs_human", 0.0


def verify_finding_claims(
    state: dict[str, Any], review_run: dict[str, Any], rule_results: list[dict[str, Any]],
    drafts: list[dict[str, Any]], *, business_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not jev_stage_enabled("CLAIM_SHADOW"):
        return {"status": "disabled", "model": MODEL, "findings": [], "factConflicts": []}
    documents, conflicts, overlong = scoped_document_states(state, review_run, rule_results)
    if overlong:
        if _rejection_threshold() is not None:
            for draft in drafts:
                _downgrade(draft, ["whole_document_too_long_for_claim_check"])
        return {"status": "overlong_documents", "model": MODEL, "findings": [],
                "factConflicts": conflicts, "overlongDocumentVersionIds": overlong}
    full_states = [row["state"] for row in documents] or ["（本节点未挂接任何可用原文）"]
    if sum(map(len, full_states)) + len(full_states) - 1 <= MAX_STATE_CHARS:
        full_states = ["\n".join(full_states)]
    questions: dict[str, dict[str, Any]] = {}
    locations: dict[str, tuple[int, str]] = {}
    findings: list[dict[str, Any]] = []
    node_id = int(review_run.get("nodeId") or 0)
    node_facts = (business_facts or {}).get(f"r{node_id}") or {}
    people = {str(row.get("welderName") or "").strip() for row in node_facts.get("certificates") or []
              if isinstance(row, dict) and str(row.get("welderName") or "").strip()} if node_id in {24, 29} else set()
    for draft_index, draft in enumerate(drafts):
        claims = draft.get("claims")
        claims = [str(item).strip() for item in claims if str(item).strip()] if isinstance(claims, list) else []
        text = " ".join(str(draft.get(key) or "") for key in ("title", "description"))
        unfaithful = [claim for claim in claims if claim not in text]
        findings.append({"findingId": draft.get("id"), "claims": [],
                         "decompositionStatus": "complete" if claims and not unfaithful else "incomplete"})
        for claim in claims:
            key = f"c{draft_index}_{len(findings[-1]['claims'])}"
            findings[-1]["claims"].append({"text": claim, "choice": "not_checked", "confidence": None})
            if len(people) > 1 and sum(person in claim for person in people) != 1:
                findings[-1]["claims"][-1]["choice"] = "ambiguous_person"
                findings[-1]["decompositionStatus"] = "incomplete"
                continue
            if claim in unfaithful:
                findings[-1]["claims"][-1]["choice"] = "unfaithful_decomposition"
                continue
            questions[key] = {"type": "choice", "instructions":
                              f"只核查以下原文主张，保持编号与数值原样，不推断缺失内容：{claim}",
                              "criteria": CLAIM_CHOICES}
            locations[key] = (draft_index, claim)
    if questions:
        try:
            batches = [ask_jev(full_text, questions) for full_text in full_states]
        except (OSError, ValueError, RuntimeError) as exc:
            logging.getLogger(__name__).warning("Jev claim check unavailable: %s", type(exc).__name__)
            if _rejection_threshold() is not None:
                for draft in drafts:
                    _downgrade(draft, ["claim_check_unavailable"])
            return {"status": "unavailable", "model": MODEL, "findings": findings, "factConflicts": conflicts}
        for key, (draft_index, claim) in locations.items():
            choice, confidence = _combine([batch[key] for batch in batches])
            item = next(row for row in findings[draft_index]["claims"] if row["text"] == claim)
            item.update(choice=choice, confidence=confidence)
    threshold = _rejection_threshold()
    if threshold is not None:
        for draft, finding in zip(drafts, findings):
            rejected = [item for item in finding["claims"]
                        if item["choice"] in {"contradicted", "not_in_materials"}
                        and isinstance(item["confidence"], (int, float)) and item["confidence"] >= threshold]
            if rejected or finding["decompositionStatus"] != "complete":
                _downgrade(draft, [item["text"] for item in rejected] or ["claim_decomposition_incomplete"])
    return {"status": "completed", "model": MODEL, "findings": findings,
            "factConflicts": conflicts, "rejectionGateApplied": threshold is not None}
