"""Frozen questions → Jev hints on the Lab branch.

Only atomic checks the business pack marks as semantic judgment get a question
(jev_usage_policy). Questions come from each check's own instruction with a
fixed template and fixed options, so the same inputs always give the same
questions. Per-run Qwen authoring was removed: on the same input its question
hashes changed every run, and one pass option dropped half of the requirement
(R09-01). Jev returns only a choice and a confidence, with no reasons, so it
never decides a check: rule, platform and calculation results stay
authoritative and Jev only flags disagreements for a human to look at first.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import defaultdict
from copy import deepcopy
from typing import Any

from libs.jev_evaluation_input import approved_ocr_text
from libs.review_orchestrator.jev_client import (
    MAX_REQUEST_CHARS,
    MODEL,
    ask_jev,
    batch_jev_questions,
    jev_stage_enabled,
)
from libs.review_orchestrator.jev_usage_policy import semantic_opinion_allowed
from libs.review_orchestrator.r19_agent import r19_semantic_questions
from libs.review_tools.executor import aggregate_atomic_results

_EVIDENCE_GATE_TOOLS = frozenset({"locate_evidence_fragment", "validate_evidence_grounding",
                                  "extract_document_fields", "extract_table_records"})
# Certificates are checked against registries and licences, dates and numbers are
# computed. OCR-only Jev cannot answer these, so they never become Jev questions.
_RULE_OWNED_TOOLS = frozenset({
    "check_certificate_validity", "check_design_license_scope", "check_installation_license_scope",
    "decode_welder_qualification", "verify_design_license_seals", "verify_license_or_certificate",
    "verify_org_license", "verify_welder_on_platform",
    "check_date_covers", "check_document_set_completeness", "check_pressure_test_parameters",
    "check_required", "check_sampling_requirement", "check_welder_work_coverage",
    "check_wps_pqr_coverage", "pipeline_stress_calculation", "straight_pipe_strength_calculation",
    "strength_calculation",
})
_NO_HINT_STATUSES = frozenset({"disabled", "nonformal_run", "no_semantic_checks"})
QUESTION_PROMPT_VERSION = "jev-frozen-question-v1"
QUESTION_SOURCE = "frozen-template"
_QUESTION_KEYS_ORDERED = ("passed", "failed", "evidence_insufficient",
                          "human_review_required", "not_applicable")
_QUESTION_KEYS = frozenset(_QUESTION_KEYS_ORDERED)
# 边界实测：题目写明条件时，适用性 3/3、选项缺陷 2/2 都答对；错在出题漏写，不在 Jev。
FROZEN_OPTIONS = {
    "passed": "原文足以证明题目中的全部要求都已满足",
    "failed": "原文明确证明违反要求或与要求矛盾",
    "evidence_insufficient": "缺少材料、缺少页码、文字无法辨认或无法完成比对，不能判断满足或不满足",
    "human_review_required": "原文相互矛盾，或必须由外部平台核验、监检人员专业判断",
    "not_applicable": "原文明确表明该要求的适用条件不成立；缺少资料不能当成不适用",
}


def _frozen_question(instruction: str) -> str:
    return (f"只根据本次完整 OCR 原文判断：{instruction.rstrip('。；;')}。"
            "要求中的每一部分都满足才算满足；没有证据不得判为满足。")

def _rule_owned_ids(records: list[dict[str, Any]]) -> set[str]:
    """Checks Jev must not be asked about: evidence gates, registry checks, calculations."""
    owned = set()
    for record in records:
        for item in record.get("atomicCheckResults") or []:
            tools = {str(tool.get("toolName") or "") for tool in item.get("toolResults") or []
                     if isinstance(tool, dict)}
            if ((tools and "validate_evidence_grounding" in tools and tools <= _EVIDENCE_GATE_TOOLS)
                    or tools & _RULE_OWNED_TOOLS):
                owned.add(str(item.get("atomicCheckId") or ""))
    return owned


def _appears_on_its_own(name: str, names: list[str], text: str) -> bool:
    """「李卫」只出现在「李卫伍」里面时，不算李卫本人在原文中出现。"""
    longer = [other for other in names if other != name and name in other]
    covered = {start + offset for other in longer for start in _find_all(text, other)
               for offset in range(other.index(name), other.index(name) + 1)}
    return any(start not in covered for start in _find_all(text, name))


def _find_all(text: str, needle: str) -> list[int]:
    starts, start = [], text.find(needle)
    while start != -1:
        starts.append(start)
        start = text.find(needle, start + 1)
    return starts


def _atomic_results(records: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(item.get("atomicCheckId")): str(item.get("result") or "")
        for record in records for item in record.get("atomicCheckResults") or []
        if isinstance(item, dict) and item.get("atomicCheckId")
    }


def _node_inputs(state: dict[str, Any], run: dict[str, Any],
                 rule_results: list[dict[str, Any]], pack: dict[str, Any],
                 business_facts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the allowed inputs without including deterministic answers."""
    if not jev_stage_enabled("PRIMARY_DECISION"):
        return {"status": "disabled"}
    if str(run.get("reviewMode") or "formal") != "formal" or run.get("advisoryOnly"):
        return {"status": "nonformal_run"}
    allowed_projects = {item.strip() for item in os.getenv("AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS", "").split(",")
                        if item.strip()}
    if str(run.get("projectId") or "") not in allowed_projects:
        return {"status": "project_not_approved_for_jev"}
    node_id = int(run.get("nodeId") or 0)
    current = _atomic_results(rule_results)
    rule_owned_ids = _rule_owned_ids(rule_results)
    if node_id == 19:
        try:
            catalog = r19_semantic_questions(run)
        except ValueError:
            return {"status": "invalid_r19_catalog"}
        checks = [(str(item["questionId"]), str(item["instruction"])) for item in catalog
                  if str(item.get("questionId")) in current]
        if len(checks) != 8:
            return {"status": "missing_frozen_checks"}
    else:
        # Deterministic-rule checks are decided by their frozen tools; asking Jev to
        # re-judge them means re-computing thresholds, which it gets wrong. Only checks
        # the pack marks as semantic judgment get a second opinion (jev_usage_policy).
        checks = [(str(item["id"]), str(item["instruction"]))
                  for item in pack.get("atomicChecks") or []
                  if isinstance(item, dict) and str(item.get("nodeId")) == str(node_id)
                  and semantic_opinion_allowed(item)
                  and str(item.get("id")) in current and str(item.get("id")) not in rule_owned_ids
                  and str(item.get("instruction") or "").strip()]
        rule_owned_ids |= set(current) - {check_id for check_id, _ in checks}
    if len({check_id for check_id, _ in checks}) != len(checks):
        return {"status": "missing_frozen_checks"}
    if set(current) != {check_id for check_id, _ in checks} | rule_owned_ids:
        return {"status": "missing_frozen_checks"}
    if not checks:
        return {"status": "no_semantic_checks", "ruleOwnedAtomicCheckIds": sorted(rule_owned_ids)}
    status, ocr_text = approved_ocr_text(state, run)
    if status != "ready":
        return {"status": status}
    if len(ocr_text) > MAX_REQUEST_CHARS - 5_000:
        return {"status": "request_overlong"}
    question_targets: dict[str, tuple[str, str | None]] = {}
    if node_id in {24, 29}:
        person_facts = (business_facts or {}).get(f"r{node_id}") or {}
        certificates = person_facts.get("certificates") or []
        names = [str(item.get("welderName") or "").strip() for item in certificates
                 if isinstance(item, dict)]
        if not names or any(not name or not _appears_on_its_own(name, names, ocr_text) for name in names):
            return {"status": "multi_person_scope_unknown"}
        if len(names) != len(set(names)) or len(names) > 20:
            return {"status": "ambiguous_person_identity"}
        work_names = {str(item.get("welderName") or "").strip()
                      for collection in ("weldingRecords", "workItems")
                      for item in person_facts.get(collection) or [] if isinstance(item, dict)
                      and str(item.get("welderName") or "").strip()}
        if work_names - set(names):
            return {"status": "multi_person_scope_unknown"}
        expanded = []
        for check_id, instruction in checks:
            for person_index, name in enumerate(sorted(names)):
                question_id = f"{check_id}__person_{person_index}"
                expanded.append((question_id, f"仅评价持证人{name}：{instruction}"))
                question_targets[question_id] = (check_id, name)
        checks = expanded
    else:
        question_targets = {check_id: (check_id, None) for check_id, _ in checks}
    node_template = next((item for item in pack.get("nodeTemplates") or []
                          if isinstance(item, dict) and str(item.get("nodeId")) == str(node_id)), {})
    if not node_template:
        return {"status": "missing_node_template"}
    template = {
        "nodeId": node_id,
        "nodeName": str(node_template.get("name") or ""),
        "requiredMaterials": [{"name": str(item.get("name") or ""),
                               "applicability": str(item.get("applicability") or "")}
                              for item in node_template.get("requiredMaterials") or [] if isinstance(item, dict)],
        "atomicChecks": [{"atomicCheckId": check_id, "instruction": instruction}
                         for check_id, instruction in checks],
    }
    input_hash = hashlib.sha256(json.dumps([ocr_text, template], ensure_ascii=False,
                                          sort_keys=True).encode()).hexdigest()
    return {"status": "ready", "ocrText": ocr_text, "template": template,
            "checks": checks, "current": current,
            "ruleOwnedAtomicCheckIds": sorted(rule_owned_ids - {check_id for check_id, _ in checks}),
            "questionTargets": question_targets, "inputHash": input_hash}


def _validated_questions(payload: Any, check_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or set(payload) != {"questions"} or not isinstance(payload["questions"], list):
        raise ValueError("qwen_invalid_question_envelope")
    items = payload["questions"]
    if len(items) != len(check_ids):
        raise ValueError("qwen_question_count_mismatch")
    validated = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"atomicCheckId", "question", "options"}:
            raise ValueError("qwen_invalid_question_item")
        check_id = str(item["atomicCheckId"])
        question = item["question"]
        options = item["options"]
        if (check_id not in check_ids or not isinstance(question, str) or not 12 <= len(question.strip()) <= 500
                or not isinstance(options, dict) or set(options) != _QUESTION_KEYS
                or any(not isinstance(value, str) or not 5 <= len(value.strip()) <= 250
                       for value in options.values())
                or len(set(options.values())) != len(options)):
            raise ValueError("qwen_invalid_question_item")
        validated.append({"atomicCheckId": check_id, "question": question.strip(),
                          "options": {key: options[key].strip() for key in _QUESTION_KEYS_ORDERED}})
    if {item["atomicCheckId"] for item in validated} != check_ids:
        raise ValueError("qwen_duplicate_or_missing_question")
    return validated


def author_node_questions(state: dict[str, Any], run: dict[str, Any],
                          rule_results: list[dict[str, Any]], pack: dict[str, Any],
                          *, business_facts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fixed-template questions from each semantic check's own instruction; no model writes them."""
    source = _node_inputs(state, run, rule_results, pack, business_facts)
    base = {"status": source["status"], "model": QUESTION_SOURCE, "promptVersion": QUESTION_PROMPT_VERSION}
    if source["status"] != "ready":
        return base
    questions = [{"atomicCheckId": check_id, "question": _frozen_question(instruction),
                  "options": dict(FROZEN_OPTIONS)} for check_id, instruction in source["checks"]]
    try:
        questions = _validated_questions({"questions": questions}, {item[0] for item in source["checks"]})
    except ValueError as exc:
        return {**base, "status": "invalid_frozen_question", "reasonCode": str(exc)[:80],
                "inputHash": source["inputHash"]}
    question_json = json.dumps(questions, ensure_ascii=False, sort_keys=True)
    identifiers = [str(run.get("projectId") or ""), str(run.get("reviewRunId") or "")]
    identifiers.extend(str(item) for item in run.get("inputDocumentVersionIds") or [])
    identifiers.extend(str(row.get("fileName") or "") for row in state.get("documents") or []
                       if isinstance(row, dict) and row.get("projectId") == run.get("projectId"))
    if any(identifier and identifier in question_json for identifier in identifiers):
        return {**base, "status": "question_contains_local_identifier", "inputHash": source["inputHash"]}
    return {**base, "status": "completed", "inputHash": source["inputHash"],
            "questionHash": hashlib.sha256(question_json.encode()).hexdigest(), "questions": questions}


def decide_node(state: dict[str, Any], run: dict[str, Any], rule_results: list[dict[str, Any]],
                pack: dict[str, Any], question_plan: dict[str, Any] | None = None,
                *, business_facts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Jev chooses among Qwen's validated options; no fixed-question shortcut."""
    base: dict[str, Any] = {"model": MODEL, "source": "jev", "role": "advisory", "atomic": []}
    source = _node_inputs(state, run, rule_results, pack, business_facts)
    if source["status"] != "ready":
        return {**base, "status": source["status"]}
    if not isinstance(question_plan, dict) or question_plan.get("status") != "completed":
        return {**base, "status": "qwen_question_plan_unavailable"}
    if question_plan.get("promptVersion") != QUESTION_PROMPT_VERSION:
        return {**base, "status": "stale_question_plan"}
    if question_plan.get("inputHash") != source["inputHash"]:
        return {**base, "status": "stale_question_plan"}
    checks = source["checks"]
    try:
        drafted = _validated_questions({"questions": question_plan.get("questions")},
                                       {item[0] for item in checks})
    except ValueError:
        return {**base, "status": "invalid_question_plan"}
    question_json = json.dumps(drafted, ensure_ascii=False, sort_keys=True)
    if hashlib.sha256(question_json.encode()).hexdigest() != question_plan.get("questionHash"):
        return {**base, "status": "stale_question_plan"}
    questions: dict[str, dict[str, Any]] = {}
    by_id = {item["atomicCheckId"]: item for item in drafted}
    for index, (check_id, _instruction) in enumerate(checks):
        authored = by_id[check_id]
        questions[f"q{index}"] = {"type": "choice", "instructions": authored["question"],
                                   "criteria": authored["options"]}
    ocr_text = source["ocrText"]
    current = source["current"]
    question_text = json.dumps(questions, ensure_ascii=False)
    identifiers = [str(run.get("projectId") or ""), str(run.get("reviewRunId") or "")]
    identifiers.extend(str(item) for item in run.get("inputDocumentVersionIds") or [])
    identifiers.extend(str(row.get("fileName") or "") for row in state.get("documents") or []
                       if isinstance(row, dict) and row.get("projectId") == run.get("projectId"))
    if any(identifier and identifier in question_text for identifier in identifiers):
        return {**base, "status": "question_contains_local_identifier"}
    try:
        batches = batch_jev_questions(ocr_text, questions)
    except ValueError:
        return {**base, "status": "request_overlong"}
    if len(batches) > 10:
        return {**base, "status": "request_budget_exceeded"}
    input_hash = hashlib.sha256(json.dumps([ocr_text, questions], ensure_ascii=False,
                                          sort_keys=True).encode()).hexdigest()
    started = time.monotonic()
    request_metrics: list[dict[str, Any]] = []
    try:
        answers = ask_jev(ocr_text, questions, observe=request_metrics.append)
    except (OSError, RuntimeError, ValueError) as exc:
        overlong = isinstance(exc, ValueError) and str(exc) == "jev_request_overlong"
        return {**base, "status": "request_overlong" if overlong else "unavailable", "inputHash": input_hash,
                "requestBatchCount": len(batches), "requestMetrics": request_metrics}
    if set(answers) != set(questions):
        return {**base, "status": "incomplete_answer", "inputHash": input_hash,
                "requestBatchCount": len(batches)}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, (question_id, _instruction) in enumerate(checks):
        answer = answers[f"q{index}"]
        choice, confidence = answer["choice"], float(answer["confidence"])
        check_id, person = source["questionTargets"][question_id]
        grouped[check_id].append({"person": person, "choice": choice, "confidence": confidence})
    opinions = []
    for check_id, rows in grouped.items():
        choice = aggregate_atomic_results([{"result": row["choice"]} for row in rows])
        opinions.append({"atomicCheckId": check_id, "choice": choice,
                         "confidence": min(row["confidence"] for row in rows),
                         **({"perPerson": rows} if rows[0]["person"] else {}),
                         "deterministicResult": current[check_id],
                         "agreesWithRuleEngine": choice == current[check_id]})
    return {**base, "status": "completed", "atomic": opinions,
            "ruleOwnedAtomicCheckIds": source["ruleOwnedAtomicCheckIds"],
            "disagreementAtomicCheckIds": [row["atomicCheckId"] for row in opinions
                                           if not row["agreesWithRuleEngine"]],
            "inputHash": input_hash, "questionPlanHash": question_plan["questionHash"],
            "questionAuthorModel": question_plan["model"], "requestBatchCount": len(batches),
            "elapsedSeconds": round(time.monotonic() - started, 3), "requestMetrics": request_metrics,
            # Jev's own node-level view, kept for paired evaluation only; never the node result.
            "opinionResult": aggregate_atomic_results([{"result": row["choice"]} for row in opinions])}


def attach_hints(rule_results: list[dict[str, Any]], decision: dict[str, Any]) -> list[dict[str, Any]]:
    """Put Jev's choice next to each rule result; results themselves never change."""
    annotated = deepcopy(rule_results)
    status = str(decision.get("status") or "")
    if status in _NO_HINT_STATUSES:
        return annotated
    choices = ({str(row["atomicCheckId"]): row for row in decision.get("atomic") or []}
               if status == "completed" else {})
    for record in annotated:
        disagreements = []
        for item in record.get("atomicCheckResults") or []:
            row = choices.get(str(item.get("atomicCheckId") or ""))
            if row is None:
                continue
            agrees = row["choice"] == item.get("result")
            item["jevHint"] = {"choice": row["choice"], "confidence": row["confidence"],
                               "agreesWithRuleEngine": agrees,
                               **({"perPerson": row["perPerson"]} if row.get("perPerson") else {})}
            if not agrees:
                disagreements.append(str(item["atomicCheckId"]))
        record["jevHintStatus"] = status
        record["jevDisagreementAtomicCheckIds"] = disagreements
    return annotated


def jev_hint_summary(decision: dict[str, Any] | None,
                     fact_check: dict[str, Any] | None = None) -> dict[str, Any]:
    """Node-level hint for the suggestion card; empty when Jev was not asked."""
    status = str((decision or {}).get("status") or "")
    fact_status = str((fact_check or {}).get("status") or "")
    hint: dict[str, Any] = {}
    if status and status not in _NO_HINT_STATUSES:
        hint.update({"status": status,
                     "disagreementCount": len(decision.get("disagreementAtomicCheckIds") or []),
                     "opinionResult": decision.get("opinionResult")})
    if fact_status in {"completed", "partial"}:
        hint.update({"factCheckStatus": fact_status, "factSuspects": list(fact_check.get("suspects") or [])})
    return {"jevHint": hint} if hint else {}
