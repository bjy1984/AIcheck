"""Shadow-only Jev second opinions over the frozen rule plan and full OCR text.

This never changes an atomic or node verdict. Confidence is recorded for the
pending 33-case calibration; no production queue threshold is applied here.
"""

from __future__ import annotations

import logging
from typing import Any

from libs.review_input_data import current_selected_parse_results
from libs.review_orchestrator.jev_client import MODEL, ask_jev, jev_stage_enabled
from libs.review_orchestrator.jev_state import (
    MAX_STATE_CHARS,
    scoped_document_states,
)

CHOICES = {
    "passed": "资料充分且该原子项满足要求",
    "failed": "资料充分且该原子项不满足要求",
    "evidence_insufficient": "资料不足，不能据此作出符合或不符合判断",
    "human_review_required": "现有资料需要监检人员专业判断或外部核验",
    "not_applicable": "有充分依据表明该原子项不适用于此对象",
}


def _questions(checks: list[dict[str, Any]], page_options: dict[str, str],
               subjects: list[str]) -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {}
    for index, check in enumerate(checks):
        for subject_index, subject in enumerate(subjects or [""]):
            suffix = f"{index}_n{subject_index}" if subjects else str(index)
            instruction = f"只评价{subject + '的' if subject else '这一'}项，不替代确定性规则：{check['instruction']}。若需外部平台或对象身份不明，选需人工；不得把没有证据判为通过。"
            questions[f"q{suffix}"] = {"type": "choice", "instructions": instruction,
                                       "criteria": CHOICES}
            if page_options:
                questions[f"p{suffix}"] = {"type": "choice", "instructions":
                                          f"哪一份文件的哪一页最直接支持{subject + '的' if subject else '此项'}判断：{check['instruction']}？原文没有支持页时选 none。此回答不是正式证据引用。",
                                          "criteria": {"none": "没有任何页能直接支持", **page_options}}
    return questions


def _subjects(review_run: dict[str, Any], business_facts: dict[str, Any] | None) -> list[str]:
    if int(review_run.get("nodeId") or 0) not in {24, 29}:
        return []
    node = (business_facts or {}).get(f"r{review_run['nodeId']}") or {}
    return sorted({str(row.get("welderName") or "").strip() for row in node.get("certificates") or []
                   if isinstance(row, dict) and str(row.get("welderName") or "").strip()})


def _page_options(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, str]:
    options: dict[str, str] = {}
    versions = {str(item) for item in review_run.get("inputDocumentVersionIds") or []}
    for parse in current_selected_parse_results(state, {"documentVersionIds": sorted(versions)},
                                                 context={"reviewRun": review_run}):
        version_id = str(parse.get("documentVersionId") or "")
        for key in ("layoutBlocks", "fields", "fragments", "tables"):
            for item in parse.get(key) or []:
                if not isinstance(item, dict):
                    continue
                try:
                    page = int(item.get("pageNo") or item.get("page") or 0)
                except (TypeError, ValueError):
                    continue
                if page > 0:
                    options[f"{version_id}:p{page}"] = f"文件版本 {version_id} 第 {page} 页"
    # The Choice primitive supports at most 255 options; keep room for none.
    return options if len(options) <= 200 else {}


def _source_rule_checks(pack: dict[str, Any], review_run: dict[str, Any],
                        rule_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actual_ids = {str(row.get("atomicCheckId") or "") for result in rule_results
                  for row in result.get("atomicCheckResults") or []}
    return [row for row in pack.get("atomicChecks") or [] if isinstance(row, dict)
            and str(row.get("nodeId")) == str(review_run.get("nodeId"))
            and str(row.get("id")) in actual_ids and str(row.get("instruction") or "").strip()]


def second_opinions(state: dict[str, Any], review_run: dict[str, Any],
                    rule_results: list[dict[str, Any]], pack: dict[str, Any],
                    *, business_facts: dict[str, Any] | None = None) -> dict[str, Any]:
    if not jev_stage_enabled("SECOND_OPINION"):
        return {"status": "disabled", "model": MODEL, "atomic": [], "factConflicts": []}
    documents, conflicts, overlong = scoped_document_states(state, review_run, rule_results)
    checks = _source_rule_checks(pack, review_run, rule_results)
    if not checks:
        return {"status": "no_atomic_checks", "model": MODEL, "atomic": [],
                "factConflicts": conflicts, "overlongDocumentVersionIds": overlong}
    if overlong:
        # A partial node would look authoritative despite missing a whole file.
        return {"status": "overlong_documents", "model": MODEL, "atomic": [],
                "factConflicts": conflicts, "overlongDocumentVersionIds": overlong}
    if not documents or any(not row["hasOcrText"] for row in documents):
        return {"status": "missing_document_text", "model": MODEL, "atomic": [],
                "factConflicts": conflicts, "overlongDocumentVersionIds": []}
    full_states = [row["state"] for row in documents]
    if sum(map(len, full_states)) + len(full_states) - 1 <= MAX_STATE_CHARS:
        full_states = ["\n".join(full_states)]
    pages = _page_options(state, review_run) if len(full_states) == 1 else {}
    subjects = _subjects(review_run, business_facts)
    if len(subjects) > 20:
        return {"status": "too_many_people", "model": MODEL, "atomic": [],
                "factConflicts": conflicts, "overlongDocumentVersionIds": []}
    questions = _questions(checks, pages, subjects)
    try:
        answer_sets = [ask_jev(full_text, questions) for full_text in full_states]
    except (OSError, ValueError, RuntimeError) as exc:
        logging.getLogger(__name__).warning("Jev second opinion unavailable: %s", type(exc).__name__)
        return {"status": "unavailable", "model": MODEL, "atomic": [],
                "factConflicts": conflicts, "overlongDocumentVersionIds": []}
    deterministic = {str(row.get("atomicCheckId")): str(row.get("result") or "")
                     for result in rule_results for row in result.get("atomicCheckResults") or []}
    opinions: list[dict[str, Any]] = []
    for index, check in enumerate(checks):
        by_person = []
        for subject_index, subject in enumerate(subjects or [""]):
            suffix = f"{index}_n{subject_index}" if subjects else str(index)
            answers = [batch[f"q{suffix}"] for batch in answer_sets]
            choices = {str(answer["choice"]) for answer in answers}
            person_choice = next(iter(choices)) if len(choices) == 1 else "human_review_required"
            person_confidence = min(float(answer["confidence"]) for answer in answers) if len(choices) == 1 else 0.0
            page_choice = answer_sets[0].get(f"p{suffix}", {}).get("choice") if pages else None
            by_person.append({"person": subject or None, "choice": person_choice,
                              "confidence": person_confidence,
                              "suggestedSupportPage": page_choice if page_choice in pages else None})
        choices = {row["choice"] for row in by_person}
        choice = next(iter(choices)) if len(choices) == 1 else "human_review_required"
        confidence = min(row["confidence"] for row in by_person) if len(choices) == 1 else 0.0
        atomic_id = str(check["id"])
        opinions.append({"atomicCheckId": atomic_id, "choice": choice,
                         "confidence": confidence, "model": MODEL,
                         "agreesWithRuleEngine": choice == deterministic.get(atomic_id),
                         "suggestedSupportPage": by_person[0]["suggestedSupportPage"] if len(by_person) == 1 else None,
                         **({"perPerson": by_person} if subjects else {}),
                         "sourceDocumentVersionIds": [row["documentVersionId"] for row in documents]})
    return {"status": "completed", "model": MODEL, "atomic": opinions,
            "factConflicts": conflicts, "overlongDocumentVersionIds": []}
