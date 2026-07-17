from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from libs.contracts.responses import server_time
from libs.review_orchestrator.r12_agent import stable_payload_hash


R19_NODE_ID = 19
R19_EXECUTION_MODE = "llm_semantic_primary"
R19_TASK_TYPE = "r19_semantic_evidence_confirmation"
R19_ATOMIC_RESULTS = {
    "passed",
    "failed",
    "evidence_insufficient",
    "not_applicable",
    "human_review_required",
}
R19_HUMAN_OUTCOMES = {"confirmed", "rejected", "unknown"}

R19_REVIEW_QUESTIONS: list[dict[str, Any]] = [
    {
        "questionId": "AC-R19-01",
        "title": "境外牌号材料适用性与使用范围",
        "clauseRefs": ["TSG D7006-2020 D2.4.1(8)", "TSG 31-2025 2.1.2"],
        "instruction": (
            "根据设计材料表、产品质量证明文件及材料牌号/执行标准，识别本工程是否使用境外牌号材料，"
            "并列明涉及的元件、安全附件、制造单位、材料牌号、批次和使用范围。"
        ),
    },
    {
        "questionId": "AC-R19-02",
        "title": "境外材料标准现行性与类似工况使用经历",
        "clauseRefs": ["TSG 31-2025 2.1.2(1)"],
        "instruction": (
            "核验境外材料标准是否为境外压力管道现行标准，并核验材料是否具有类似工况使用经历；"
            "文件不能支持时不得推定满足。"
        ),
    },
    {
        "questionId": "AC-R19-03",
        "title": "化学成分与性能等同性",
        "clauseRefs": ["TSG 31-2025 2.1.2(2)", "TSG 31-2025 2.1.2(3)"],
        "instruction": (
            "对照境外材料标准、国内相近材料及企业标准，分析化学成分、力学性能、物理性能和工艺性能；"
            "性能不得低于本规程及相应国内材料标准的基本要求。"
        ),
    },
    {
        "questionId": "AC-R19-04",
        "title": "化学成分和力学性能验证性复验",
        "clauseRefs": ["TSG D7006-2020 D2.4.1(8)", "TSG 31-2025 2.1.2(4)"],
        "instruction": (
            "按材料牌号和炉批号关联产品质量证明文件与复验报告，核验化学成分和力学性能复验项目、"
            "试样/批次追溯、试验结果及结论。"
        ),
    },
    {
        "questionId": "AC-R19-05",
        "title": "首次使用材料焊接工艺评定",
        "clauseRefs": ["TSG 31-2025 2.1.2(5)"],
        "instruction": (
            "先判断该境外牌号材料是否为首次使用；首次使用时核验焊接工艺评定是否覆盖材料组别、"
            "焊接方法、厚度和适用范围，非首次使用时应给出可追溯的使用经历依据。"
        ),
    },
    {
        "questionId": "AC-R19-06",
        "title": "复验与工艺评定结果归入质量证明文件",
        "clauseRefs": ["TSG 31-2025 2.1.2(6)"],
        "instruction": (
            "核验验证性复验结果和适用的焊接工艺评定结果是否纳入或者作为附件关联至产品质量证明文件，"
            "并形成证书号、报告号、炉批号之间的追溯链。"
        ),
    },
    {
        "questionId": "AC-R19-07",
        "title": "境内制造单位企业标准",
        "clauseRefs": ["TSG 31-2025 2.1.2(1)-(6)"],
        "instruction": (
            "仅对境内制造单位使用境外牌号材料的情形，核验是否制定对应企业标准，且企业标准覆盖材料技术要求、"
            "验收规则、复验、首次使用工艺评定和质量证明归档要求；境外制造情形不得误判为缺少企业标准。"
        ),
    },
    {
        "questionId": "AC-R19-08",
        "title": "R19 证据可追溯性",
        "clauseRefs": ["TSG D7006-2020 D2.4.1(8)", "TSG 31-2025 2.1.2"],
        "instruction": (
            "核验每项判断引用的文件版本、页码、坐标或原文片段可追溯；证据缺失、冲突或OCR低置信度时"
            "不得判定为符合。"
        ),
    },
]


def is_r19_formal_review(review_run: dict[str, Any]) -> bool:
    return (
        int(review_run.get("nodeId") or 0) == R19_NODE_ID
        and str(review_run.get("reviewMode") or "formal") == "formal"
        and not bool(review_run.get("advisoryOnly"))
    )


def build_r19_agent_context(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    requested = {str(item) for item in review_run.get("inputDocumentVersionIds") or [] if item}
    documents: list[dict[str, Any]] = []
    evidence_index: dict[str, dict[str, Any]] = {}
    for parse_result in state.get("ocr_parse_results", []):
        if not isinstance(parse_result, dict):
            continue
        version_id = str(parse_result.get("documentVersionId") or "")
        if requested and version_id not in requested:
            continue
        fields = [item for item in parse_result.get("fields") or [] if isinstance(item, dict)]
        tables = [item for item in parse_result.get("tables") or [] if isinstance(item, dict)]
        fragments = [item for item in parse_result.get("fragments") or [] if isinstance(item, dict)]
        file_name = _file_name(state, version_id)
        previews: list[dict[str, Any]] = []
        for candidate in [*fields, *fragments][:120]:
            quoted_text = _item_text(candidate)
            if not quoted_text:
                continue
            evidence = _evidence_ref(version_id, candidate, quoted_text)
            evidence["fileName"] = file_name
            evidence_index[evidence["evidenceRefId"]] = evidence
            if len(previews) < 12:
                previews.append(evidence)
        documents.append(
            {
                "documentVersionId": version_id,
                "documentId": parse_result.get("documentId"),
                "fileName": file_name,
                "documentType": parse_result.get("documentType"),
                "profileId": parse_result.get("profileId"),
                "fieldCount": len(fields),
                "tableCount": len(tables),
                "fragmentCount": len(fragments),
                "evidencePreview": previews,
                "tablePreview": [_compact_table(item) for item in tables[:4]],
            }
        )

    human_confirmations: list[dict[str, Any]] = []
    for record in review_run.get("manualR19Confirmations") or []:
        if not isinstance(record, dict):
            continue
        for answer in record.get("answers") or []:
            if not isinstance(answer, dict):
                continue
            evidence_ref_id = f"R19HUM-{stable_payload_hash({'responseId': record.get('responseId'), 'answer': answer})[7:19].upper()}"
            human_evidence = {
                "evidenceRefId": evidence_ref_id,
                "sourceType": "human_confirmation",
                "questionId": answer.get("questionId"),
                "outcome": answer.get("outcome"),
                "value": answer.get("value"),
                "quotedText": answer.get("comment") or answer.get("outcome"),
                "sourceRefs": answer.get("sourceRefs") or [],
                "attachmentIds": answer.get("attachmentIds") or [],
                "actorId": record.get("actorId"),
                "actorName": record.get("actorName"),
                "submittedAt": record.get("submittedAt"),
            }
            evidence_index[evidence_ref_id] = human_evidence
            human_confirmations.append({**answer, "evidenceRefId": evidence_ref_id})

    return {
        "executionMode": R19_EXECUTION_MODE,
        "reviewRunId": review_run.get("reviewRunId"),
        "inputHash": review_run.get("inputHash"),
        "documentVersionIds": sorted(requested),
        "documents": documents,
        "documentCount": len(documents),
        "reviewQuestions": [dict(item) for item in R19_REVIEW_QUESTIONS],
        "humanConfirmations": human_confirmations,
        "evidenceIndex": evidence_index,
        "evidenceRefIds": sorted(evidence_index),
    }


def validate_r19_semantic_submission(
    payload: dict[str, Any],
    *,
    known_evidence_ref_ids: set[str] | None = None,
    evidence_index: dict[str, dict[str, Any]] | None = None,
    minimum_ocr_confidence: float = 0.75,
) -> dict[str, Any]:
    judgments = payload.get("atomicJudgments")
    if not isinstance(judgments, list):
        return {"status": "invalid_input", "errors": ["atomicJudgments_must_be_array"]}
    expected_ids = {item["questionId"] for item in R19_REVIEW_QUESTIONS}
    allowed_clauses_by_id = {
        item["questionId"]: set(item["clauseRefs"])
        for item in R19_REVIEW_QUESTIONS
    }
    enforce_known_evidence = known_evidence_ref_ids is not None or evidence_index is not None
    evidence_index = evidence_index or {}
    known = (known_evidence_ref_ids or set()) | set(evidence_index)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    errors: list[str] = []
    for index, raw in enumerate(judgments, 1):
        if not isinstance(raw, dict):
            errors.append(f"judgment_{index}_must_be_object")
            continue
        atomic_id = str(raw.get("atomicCheckId") or "")
        result = str(raw.get("result") or "")
        if atomic_id not in expected_ids:
            errors.append(f"judgment_{index}_atomic_check_invalid")
        if atomic_id in seen:
            errors.append(f"judgment_{index}_atomic_check_duplicate")
        seen.add(atomic_id)
        if result not in R19_ATOMIC_RESULTS:
            errors.append(f"judgment_{index}_result_invalid")
        explanation = _clean_text(raw.get("explanation"), 4000)
        if not explanation:
            errors.append(f"judgment_{index}_explanation_required")
        clause_refs = _string_list(raw.get("clauseRefs"), 20, 300)
        if not clause_refs:
            errors.append(f"judgment_{index}_clause_refs_required")
        elif atomic_id in allowed_clauses_by_id and (
            not set(clause_refs).intersection(allowed_clauses_by_id[atomic_id])
            or set(clause_refs) - allowed_clauses_by_id[atomic_id]
        ):
            errors.append(f"judgment_{index}_clause_ref_not_fixed_for_atomic_check")
        evidence_ref_ids = _evidence_id_list(raw.get("evidenceRefIds"))
        if result in {"passed", "failed", "not_applicable"} and not evidence_ref_ids:
            errors.append(f"judgment_{index}_evidence_required_for_{result}")
        unknown_ids = sorted(set(evidence_ref_ids) - known) if enforce_known_evidence else []
        if unknown_ids:
            errors.append(f"judgment_{index}_evidence_ref_unknown")
        if result in {"passed", "failed", "not_applicable"} and evidence_index:
            for evidence_id in evidence_ref_ids:
                evidence = evidence_index.get(evidence_id) or {}
                if evidence.get("sourceType") == "human_confirmation":
                    if str(evidence.get("questionId") or "") != atomic_id:
                        errors.append(f"judgment_{index}_human_evidence_question_mismatch")
                        break
                    outcome = str(evidence.get("outcome") or "unknown")
                    if outcome == "unknown":
                        errors.append(f"judgment_{index}_human_evidence_unresolved")
                        break
                    if result in {"passed", "not_applicable"} and outcome != "confirmed":
                        errors.append(f"judgment_{index}_human_evidence_outcome_mismatch")
                        break
                    if result == "failed" and outcome != "rejected":
                        errors.append(f"judgment_{index}_human_evidence_outcome_mismatch")
                        break
                    continue
                if not evidence.get("documentVersionId") or not evidence.get("pageNo"):
                    errors.append(f"judgment_{index}_evidence_location_incomplete")
                    break
                if not (evidence.get("bbox") or evidence.get("quotedText")):
                    errors.append(f"judgment_{index}_evidence_quote_or_bbox_required")
                    break
                try:
                    confidence = float(evidence.get("confidence") or 0.0)
                except (TypeError, ValueError):
                    confidence = 0.0
                if confidence < minimum_ocr_confidence:
                    errors.append(f"judgment_{index}_evidence_confidence_too_low")
                    break
                if evidence.get("conflicted") is True or evidence.get("conflictStatus") in {"conflict", "conflicted"}:
                    errors.append(f"judgment_{index}_evidence_conflicted")
                    break
        missing_facts = _string_list(raw.get("missingFacts"), 30, 500)
        recommended_action = _clean_text(raw.get("recommendedAction"), 2000)
        if result in {"evidence_insufficient", "human_review_required"} and not (missing_facts or recommended_action):
            errors.append(f"judgment_{index}_missing_facts_or_action_required")
        try:
            confidence = float(raw.get("confidence"))
        except (TypeError, ValueError):
            confidence = -1.0
        if not 0.0 <= confidence <= 1.0:
            errors.append(f"judgment_{index}_confidence_invalid")
        normalized.append(
            {
                "atomicCheckId": atomic_id,
                "result": result,
                "explanation": explanation,
                "reasonCodes": _string_list(raw.get("reasonCodes"), 20, 120),
                "evidenceRefIds": evidence_ref_ids,
                "clauseRefs": clause_refs,
                "missingFacts": missing_facts,
                "recommendedAction": recommended_action,
                "confidence": confidence,
                "sourceMethod": R19_EXECUTION_MODE,
            }
        )
    if seen != expected_ids:
        errors.append("every_r19_atomic_check_requires_one_judgment")
    traceability = next(
        (item for item in normalized if item.get("atomicCheckId") == "AC-R19-08"),
        None,
    )
    required_trace_ids = {
        evidence_id
        for item in normalized
        if item.get("atomicCheckId") != "AC-R19-08"
        for evidence_id in item.get("evidenceRefIds") or []
    }
    if (
        traceability
        and traceability.get("result") == "passed"
        and not required_trace_ids <= set(traceability.get("evidenceRefIds") or [])
    ):
        errors.append("r19_traceability_judgment_must_cover_all_referenced_evidence")
    if errors:
        return {"status": "invalid_input", "errors": errors, "atomicJudgments": normalized}
    aggregate = aggregate_r19_atomic_judgments(normalized)
    return {
        "status": "valid",
        "atomicJudgments": normalized,
        "result": aggregate,
        "summary": _clean_text(payload.get("summary"), 6000),
        "recommendedActions": _string_list(payload.get("recommendedActions"), 30, 1000),
    }


def aggregate_r19_atomic_judgments(judgments: list[dict[str, Any]]) -> str:
    results = [str(item.get("result") or "evidence_insufficient") for item in judgments]
    if "failed" in results:
        return "failed"
    if "evidence_insufficient" in results:
        return "evidence_insufficient"
    if "human_review_required" in results:
        return "human_review_required"
    applicable = [item for item in results if item != "not_applicable"]
    if applicable and all(item == "passed" for item in applicable):
        return "passed"
    if results and all(item == "not_applicable" for item in results):
        return "not_applicable"
    return "evidence_insufficient"


def ensure_r19_human_input_task(
    review_run: dict[str, Any],
    request: dict[str, Any] | None,
    *,
    requested_by: str,
    agent_trace: dict[str, Any] | None = None,
    agent_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not is_r19_formal_review(review_run):
        return None
    for item in reversed(review_run.get("humanInputTasks") or []):
        if isinstance(item, dict) and item.get("taskType") == R19_TASK_TYPE and item.get("status") == "pending":
            return item
    request = request if isinstance(request, dict) else {}
    requested_ids = {str(item) for item in request.get("questionIds") or [] if item}
    selected = [item for item in R19_REVIEW_QUESTIONS if item["questionId"] in requested_ids]
    if not selected:
        selected = list(R19_REVIEW_QUESTIONS)
    input_hash = stable_payload_hash(
        {
            "reviewRunInputHash": review_run.get("inputHash"),
            "questionIds": [item["questionId"] for item in selected],
        }
    )
    if any(
        isinstance(item, dict)
        and item.get("taskType") == R19_TASK_TYPE
        and item.get("status") == "completed"
        and item.get("inputHash") == input_hash
        for item in review_run.get("humanInputTasks") or []
    ):
        return None
    now = server_time()
    evidence_candidates = _task_evidence_candidates(agent_context)
    task = {
        "taskId": f"HIT-R19-{uuid4().hex[:10].upper()}",
        "taskType": R19_TASK_TYPE,
        "schemaVersion": "1.0",
        "nodeId": R19_NODE_ID,
        "atomicCheckIds": [item["questionId"] for item in selected],
        "title": _clean_text(request.get("title"), 300) or "确认 R19 境外牌号材料关键事实",
        "description": _clean_text(request.get("instructions"), 3000) or (
            "AI 无法从现有文件可靠确认下列高风险语义事实。请逐项核验并提供来源、附件或说明；"
            "未确认前工作流不会生成通过结论。"
        ),
        "reasonCode": "R19_SEMANTIC_EVIDENCE_REQUIRES_HUMAN",
        "status": "pending",
        "required": True,
        "blocking": True,
        "requestedBy": requested_by,
        "inputHash": input_hash,
        "reviewRunInputHash": review_run.get("inputHash"),
        "questions": selected,
        "questionCount": len(selected),
        "evidenceCandidates": evidence_candidates,
        "evidenceCandidateCount": len(evidence_candidates),
        "responseSchemaRef": "human-task://r19_semantic_evidence_confirmation/1.0",
        "uiSchemaRef": "human-task-ui://r19_semantic_evidence_confirmation/1.0",
        "agentTrace": agent_trace or {},
        "responses": [],
        "createdAt": now,
        "updatedAt": now,
    }
    review_run.setdefault("humanInputTasks", []).append(task)
    return task


def validate_r19_human_input(review_run: dict[str, Any], task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    task = next(
        (
            item
            for item in review_run.get("humanInputTasks") or []
            if isinstance(item, dict) and str(item.get("taskId") or "") == str(task_id)
        ),
        None,
    )
    if not task or task.get("taskType") != R19_TASK_TYPE:
        return {"status": "missing_task", "errors": ["r19_human_input_task_not_found"]}
    if task.get("status") != "pending" or review_run.get("status") != "waiting_human_input":
        return {"status": "invalid_state", "errors": ["human_input_task_not_pending"]}
    if task.get("reviewRunInputHash") != review_run.get("inputHash"):
        return {"status": "stale_input", "errors": ["review_run_input_changed"]}
    expected = {str(item.get("questionId")) for item in task.get("questions") or [] if item.get("questionId")}
    known_evidence_ids = {
        str(item.get("evidenceRefId") or "")
        for item in task.get("evidenceCandidates") or []
        if isinstance(item, dict) and item.get("evidenceRefId")
    }
    submitted = payload.get("answers")
    if not isinstance(submitted, list):
        return {"status": "invalid_input", "errors": ["answers_must_be_array"]}
    errors: list[str] = []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(submitted, 1):
        if not isinstance(raw, dict):
            errors.append(f"answer_{index}_must_be_object")
            continue
        question_id = str(raw.get("questionId") or "")
        outcome = str(raw.get("outcome") or "")
        if question_id not in expected:
            errors.append(f"answer_{index}_question_invalid")
        if question_id in seen:
            errors.append(f"answer_{index}_question_duplicate")
        seen.add(question_id)
        if outcome not in R19_HUMAN_OUTCOMES:
            errors.append(f"answer_{index}_outcome_invalid")
        if raw.get("attested") is not True:
            errors.append(f"answer_{index}_attestation_required")
        evidence_refs = _evidence_id_list(raw.get("evidenceRefIds"))
        if set(evidence_refs) - known_evidence_ids:
            errors.append(f"answer_{index}_evidence_ref_unknown")
        source_refs = _validated_source_refs(raw.get("sourceRefs"), errors, index)
        attachment_ids = _string_list(raw.get("attachmentIds"), 20, 200)
        comment = _clean_text(raw.get("comment"), 3000)
        if outcome in {"confirmed", "rejected"} and not (evidence_refs or source_refs or attachment_ids):
            errors.append(f"answer_{index}_source_required")
        normalized.append(
            {
                "questionId": question_id,
                "outcome": outcome,
                "value": raw.get("value"),
                "evidenceRefIds": evidence_refs,
                "sourceRefs": source_refs,
                "attachmentIds": attachment_ids,
                "comment": comment,
                "attested": raw.get("attested") is True,
            }
        )
    if seen != expected:
        errors.append("every_r19_question_requires_one_answer")
    return {"status": "invalid_input" if errors else "valid", "errors": errors, "answers": normalized}


def apply_r19_human_input(
    review_run: dict[str, Any],
    task_id: str,
    payload: dict[str, Any],
    *,
    actor_id: str | None,
    actor_name: str | None,
    command_id: str | None = None,
) -> dict[str, Any]:
    validation = validate_r19_human_input(review_run, task_id, payload)
    if validation.get("status") != "valid":
        return validation
    task = next(
        item
        for item in review_run.get("humanInputTasks") or []
        if isinstance(item, dict) and str(item.get("taskId") or "") == str(task_id)
    )
    now = server_time()
    response = {
        "responseId": f"HIRESP-R19-{uuid4().hex[:10].upper()}",
        "commandId": command_id,
        "inputHash": task.get("inputHash"),
        "answers": validation["answers"],
        "generalComment": _clean_text(payload.get("comment"), 3000),
        "actorId": actor_id,
        "actorName": actor_name,
        "submittedAt": now,
    }
    task.setdefault("responses", []).append(response)
    task["status"] = "completed"
    task["completedAt"] = now
    task["updatedAt"] = now
    review_run.setdefault("manualR19Confirmations", []).append(
        {
            "taskId": task_id,
            "responseId": response["responseId"],
            "inputHash": task.get("inputHash"),
            "answers": validation["answers"],
            "actorId": actor_id,
            "actorName": actor_name,
            "submittedAt": now,
        }
    )
    review_run["status"] = "resuming"
    review_run["currentStep"] = "resume_after_human_input"
    review_run["updatedAt"] = now
    return {"status": "applied", "task": task, "response": response, "reviewRun": review_run}


def _evidence_ref(document_version_id: str, candidate: dict[str, Any], quoted_text: str) -> dict[str, Any]:
    key = {
        "documentVersionId": document_version_id,
        "pageNo": candidate.get("pageNo") or 1,
        "bbox": candidate.get("bbox") or candidate.get("polygon"),
        "quotedText": quoted_text,
    }
    ref_id = f"R19EV-{stable_payload_hash(key)[7:19].upper()}"
    return {
        "evidenceRefId": ref_id,
        "documentVersionId": document_version_id,
        "pageNo": candidate.get("pageNo") or 1,
        "bbox": candidate.get("bbox") or candidate.get("polygon"),
        "quotedText": quoted_text[:1500],
        "confidence": _numeric_confidence(candidate),
    }


def _task_evidence_candidates(agent_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    context = agent_context if isinstance(agent_context, dict) else {}
    candidates: list[dict[str, Any]] = []
    for evidence in (context.get("evidenceIndex") or {}).values():
        if not isinstance(evidence, dict) or not evidence.get("evidenceRefId"):
            continue
        candidates.append(
            {
                key: evidence.get(key)
                for key in [
                    "evidenceRefId",
                    "sourceType",
                    "documentVersionId",
                    "fileName",
                    "pageNo",
                    "bbox",
                    "quotedText",
                    "confidence",
                    "questionId",
                    "outcome",
                    "value",
                    "sourceRefs",
                    "attachmentIds",
                ]
                if evidence.get(key) is not None
            }
        )
        if len(candidates) >= 60:
            break
    return candidates


def _validated_source_refs(value: Any, errors: list[str], answer_index: int) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"answer_{answer_index}_source_refs_must_be_array")
        return []
    output: list[dict[str, Any]] = []
    for source_index, raw in enumerate(value[:20], 1):
        if not isinstance(raw, dict):
            errors.append(f"answer_{answer_index}_source_ref_{source_index}_must_be_object")
            continue
        source_type = _clean_text(raw.get("type"), 50)
        url = _clean_text(raw.get("url"), 2000)
        reference = _clean_text(raw.get("reference"), 1000)
        title = _clean_text(raw.get("title"), 300)
        if source_type not in {"url", "document", "record", "other"}:
            errors.append(f"answer_{answer_index}_source_ref_{source_index}_type_invalid")
            continue
        if source_type == "url" and not (url.startswith("https://") or url.startswith("http://")):
            errors.append(f"answer_{answer_index}_source_ref_{source_index}_url_invalid")
            continue
        if source_type != "url" and not reference:
            errors.append(f"answer_{answer_index}_source_ref_{source_index}_reference_required")
            continue
        output.append(
            {
                "type": source_type,
                **({"url": url} if url else {}),
                **({"reference": reference} if reference else {}),
                **({"title": title} if title else {}),
            }
        )
    return output


def _compact_table(table: dict[str, Any]) -> dict[str, Any]:
    rows = table.get("normalizedRows") or table.get("records") or table.get("rows") or []
    return {
        "tableId": table.get("tableId") or table.get("id"),
        "pageNo": table.get("pageNo") or 1,
        "title": table.get("title") or table.get("tableName"),
        "businessSchema": table.get("businessSchema"),
        "rowCount": len(rows) if isinstance(rows, list) else 0,
        "rows": rows[:10] if isinstance(rows, list) else [],
    }


def _file_name(state: dict[str, Any], version_id: str) -> str | None:
    version = next(
        (
            item
            for item in state.get("versions", [])
            if isinstance(item, dict)
            and str(item.get("id") or item.get("versionId") or item.get("documentVersionId") or "") == version_id
        ),
        None,
    )
    if not version:
        return None
    if version.get("fileName"):
        return str(version["fileName"])
    document_id = str(version.get("documentId") or "")
    document = next(
        (
            item
            for item in state.get("documents", [])
            if isinstance(item, dict) and str(item.get("id") or item.get("documentId") or "") == document_id
        ),
        None,
    )
    return str((document or {}).get("fileName") or (document or {}).get("name") or "") or None


def _item_text(item: dict[str, Any]) -> str:
    return str(item.get("quotedText") or item.get("text") or item.get("fieldValue") or item.get("value") or "").strip()


def _numeric_confidence(item: dict[str, Any]) -> float:
    try:
        return round(float(item.get("confidence") or item.get("ocrConfidence") or 0.0), 4)
    except (TypeError, ValueError):
        return 0.0


def _evidence_id_list(value: Any) -> list[str]:
    output: list[str] = []
    for item in value or []:
        if isinstance(item, dict):
            candidate = item.get("evidenceRefId") or item.get("id")
        else:
            candidate = item
        text = _clean_text(candidate, 200)
        if text and text not in output:
            output.append(text)
    return output[:100]


def _string_list(value: Any, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        text = _clean_text(item, item_limit)
        if text and text not in output:
            output.append(text)
        if len(output) >= limit:
            break
    return output


def _clean_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    return text[:limit] or None


def context_for_model(context: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded, JSON-safe context for Agent messages and audit hashes."""

    return {
        "executionMode": context.get("executionMode"),
        "reviewRunId": context.get("reviewRunId"),
        "documentCount": context.get("documentCount"),
        "documentVersionIds": context.get("documentVersionIds") or [],
        "documents": context.get("documents") or [],
        "reviewQuestions": context.get("reviewQuestions") or [],
        "humanConfirmations": context.get("humanConfirmations") or [],
        "knownEvidenceRefIds": context.get("evidenceRefIds") or [],
    }


def serialized_context(context: dict[str, Any]) -> str:
    return json.dumps(context_for_model(context), ensure_ascii=False, default=str)
