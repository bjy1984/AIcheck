"""Shadow-only Jev second opinions over the frozen rule plan and full OCR text.

This never changes an atomic or node verdict. Confidence is recorded for the
pending 33-case calibration; no production queue threshold is applied here.
"""

from __future__ import annotations

import logging
from typing import Any

from libs.review_input_data import current_selected_parse_results
from libs.review_orchestrator.jev_client import (
    MODEL,
    ask_jev,
    batch_jev_questions,
    jev_stage_enabled,
)
from libs.review_orchestrator.jev_state import (
    MAX_STATE_CHARS,
    scoped_document_states,
)
from libs.review_orchestrator.r19_agent import r19_semantic_questions

CHOICES = {
    "passed": "资料充分且该原子项满足要求",
    "failed": "资料充分且该原子项不满足要求",
    "evidence_insufficient": "资料不足，不能据此作出符合或不符合判断",
    "human_review_required": "现有资料需要监检人员专业判断或外部核验",
    "not_applicable": "有充分依据表明该原子项不适用于此对象",
}

R19_APPLICABILITY = {
    "applicable": "有原文依据表明本题适用于当前材料或对象",
    "not_applicable": "有原文依据表明本题不适用；不能仅凭未找到资料选此项",
    "unknown": "现有原文不足以确定是否适用",
}
R19_JUDGMENT = {
    "passed": "原文足以证明本题要求已满足",
    "failed": "原文足以证明本题要求未满足",
    "evidence_insufficient": "原文不足、相互矛盾或仍需外部或人工核验",
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


def _r19_shadow_questions(catalog: list[dict[str, Any]], pages: dict[str, str]) -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(catalog):
        scope = f"{item['questionId']} {item['title']}：{item['instruction']}"
        questions[f"a{index}"] = {"type": "choice", "instructions":
            f"只根据本次完整 OCR 原文判断适用性。{scope}。缺资料不能当成不适用。",
            "criteria": R19_APPLICABILITY}
        questions[f"j{index}"] = {"type": "choice", "instructions":
            f"只根据本次完整 OCR 原文判断要求是否满足。{scope}。不确定时选证据不足；此为影子意见，不代替监检裁决。",
            "criteria": R19_JUDGMENT}
        if pages:
            questions[f"p{index}"] = {"type": "choice", "instructions":
                f"哪一页最直接支持 {item['questionId']} 的判断？无支持页选 none；页码只是定位建议，不是正式证据引用。",
                "criteria": {"none": "没有可确认的支持页", **pages}}
    return questions


def _r19_second_opinions(state: dict[str, Any], review_run: dict[str, Any],
                         rule_results: list[dict[str, Any]]) -> dict[str, Any]:
    # R19's primary judgment is Qwen semantic review. Do not inject it as a
    # "verified rule check" into the independent Jev question state.
    documents, conflicts, overlong = scoped_document_states(state, review_run, [])
    base = {"model": MODEL, "atomic": [], "factConflicts": conflicts,
            "overlongDocumentVersionIds": overlong, "comparisonSource": "r19_semantic_review"}
    if overlong:
        return {**base, "status": "overlong_documents"}
    if any(row.get("ocrNotReady") for row in documents):
        return {**base, "status": "ocr_not_ready"}
    if not documents or any(not row["hasOcrText"] for row in documents):
        return {**base, "status": "missing_document_text"}
    full_state = "\n".join(row["state"] for row in documents)
    if len(full_state) > MAX_STATE_CHARS:
        return {**base, "status": "overlong_documents",
                "overlongDocumentVersionIds": [row["documentVersionId"] for row in documents]}
    catalog = r19_semantic_questions(review_run)
    if not catalog:
        return {**base, "status": "no_atomic_checks"}
    pages = _page_options(state, review_run)
    questions = _r19_shadow_questions(catalog, pages)
    try:
        batch_jev_questions(full_state, questions)
    except ValueError:
        return {**base, "status": "overlong_request"}
    try:
        answers = ask_jev(full_state, questions)
    except (OSError, ValueError, RuntimeError) as exc:
        logging.getLogger(__name__).warning("R19 Jev shadow unavailable: %s", type(exc).__name__)
        return {**base, "status": "unavailable"}
    current = {str(row.get("atomicCheckId")): str(row.get("result") or "")
               for result in rule_results for row in result.get("atomicCheckResults") or []}
    opinions = []
    for index, item in enumerate(catalog):
        applicability = answers[f"a{index}"]
        judgment = answers[f"j{index}"]
        applies = applicability["choice"]
        if applies == "not_applicable":
            choice, confidence = "not_applicable", float(applicability["confidence"])
        elif applies == "unknown":
            choice, confidence = "evidence_insufficient", float(applicability["confidence"])
        else:
            choice = str(judgment["choice"])
            confidence = min(float(applicability["confidence"]), float(judgment["confidence"]))
        suggested_page = answers.get(f"p{index}", {}).get("choice") if pages else None
        atomic_id = str(item["questionId"])
        opinions.append({"atomicCheckId": atomic_id, "choice": choice, "confidence": confidence,
                         "model": MODEL, "applicability": applies,
                         "suggestedSupportPage": suggested_page if suggested_page in pages else None,
                         "sourceDocumentVersionIds": [row["documentVersionId"] for row in documents],
                         "agreesWithRuleEngine": None,
                         "agreesWithCurrentResult": choice == current[atomic_id] if atomic_id in current else None,
                         "currentResult": current.get(atomic_id)})
    return {**base, "status": "completed", "atomic": opinions}


def second_opinions(state: dict[str, Any], review_run: dict[str, Any],
                    rule_results: list[dict[str, Any]], pack: dict[str, Any],
                    *, business_facts: dict[str, Any] | None = None) -> dict[str, Any]:
    if not jev_stage_enabled("SECOND_OPINION"):
        return {"status": "disabled", "model": MODEL, "atomic": [], "factConflicts": []}
    if (int(review_run.get("nodeId") or 0) == 19
            and str(review_run.get("reviewMode") or "formal") == "formal"
            and not review_run.get("advisoryOnly")):
        return _r19_second_opinions(state, review_run, rule_results)
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
