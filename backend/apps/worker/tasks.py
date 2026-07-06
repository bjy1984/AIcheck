from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from apps.ocr_service.service import ocr_service
from apps.worker.celery_app import celery_app
from libs.business_pack import build_ai_review_prompt, load_business_pack, matching_rule_for_node
from libs.contracts.responses import server_time
from libs.db.repository import flush_state, load_state, repo
from libs.integrations import task_dispatcher
from libs.integrations.litellm_client import LiteLLMClient
from libs.integrations.ocr_client import OcrClient
from libs.review_grounding import apply_grounding_guardrails, build_grounded_review_input, grounding_prompt_block, unsupported_claims


def stable_hash_payload(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compare_document_version_ids(run: dict[str, Any]) -> set[str]:
    version_ids = {str(item) for item in run.get("documentVersionIds") or [] if item}
    evidence_ids = {str(item) for item in run.get("evidenceLinkIds") or [] if item}
    if evidence_ids:
        version_ids.update(
            str(item.get("documentVersionId"))
            for item in repo.state.get("evidence_links", [])
            if str(item.get("id") or "") in evidence_ids and item.get("documentVersionId")
        )
    if version_ids:
        return version_ids
    project_id = run.get("projectId")
    node_id = run.get("nodeId")
    for ai_run in repo.state.get("ai_runs", []):
        if project_id and ai_run.get("projectId") != project_id:
            continue
        if node_id is not None and int(ai_run.get("nodeId") or -1) != int(node_id):
            continue
        version_ids.update(str(item) for item in ai_run.get("inputDocumentVersionIds") or [] if item)
    return version_ids


def production_prompt_template_for_run(run: dict[str, Any]) -> dict[str, Any] | None:
    business_pack_id = run.get("businessPackId")
    prompt_version = str(run.get("promptVersion") or "")
    templates = [
        item
        for item in repo.state.get("prompt_templates", [])
        if item.get("businessPackId") in {None, "", business_pack_id}
        and item.get("status") in {"production", "published", "active", "启用", "已发布"}
    ]
    exact = next(
        (
            item
            for item in templates
            if prompt_version
            and (
                item.get("id") == prompt_version
                or item.get("promptVersionId") == prompt_version
                or item.get("version") == prompt_version
            )
        ),
        None,
    )
    return repo.clone(exact or (templates[0] if templates else None))


def service_failure_message(service: str) -> str:
    return f"{service} 调用失败，请检查服务健康、模型配置、凭据和网络连通性。"


def worker_ocr_http_enabled() -> bool:
    if os.getenv("AICHECK_OCR_BASE_URL"):
        return True
    return os.getenv("AICHECK_WORKER_OCR_ENABLE_LOCAL_FALLBACK", "false").lower() in {"1", "true", "yes", "on"}


def refresh_worker_state() -> None:
    if (
        repo.sync_postgres is not None
        or repo.postgres_dsn
        or os.getenv("AICHECK_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or repo.sqlite_enabled
    ):
        load_state()


def split_text_fragments(text: str, *, page_no: int = 1, max_chars: int = 1600) -> list[dict[str, Any]]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []
    chunks = []
    for offset in range(0, len(normalized), max_chars):
        chunk_text = normalized[offset : offset + max_chars].strip()
        if chunk_text:
            chunks.append({"pageNo": page_no, "text": chunk_text})
    return chunks


def latest_successful_ocr_parse_result(version_id: str | None) -> dict[str, Any] | None:
    if not version_id:
        return None
    results = [
        item
        for item in repo.state.get("ocr_parse_results", [])
        if item.get("documentVersionId") == version_id and item.get("status") == "success"
    ]
    results.sort(key=lambda item: str(item.get("finishedAt") or item.get("createdAt") or ""), reverse=True)
    return results[0] if results else None


def knowledge_slice_fragments_from_ocr(file: dict[str, Any]) -> list[dict[str, Any]]:
    result = latest_successful_ocr_parse_result(file.get("documentVersionId"))
    raw_fragments = [item for item in (result or {}).get("fragments") or [] if isinstance(item, dict)]
    if not raw_fragments:
        return []
    if len(raw_fragments) == 1:
        fragment = raw_fragments[0]
        return split_text_fragments(str(fragment.get("text") or ""), page_no=int(fragment.get("pageNo") or 1))
    pages: dict[int, list[str]] = {}
    for fragment in raw_fragments:
        text = str(fragment.get("text") or "").strip()
        if not text:
            continue
        page_no = int(fragment.get("pageNo") or 1)
        pages.setdefault(page_no, []).append(text)
    fragments: list[dict[str, Any]] = []
    for page_no in sorted(pages):
        fragments.extend(split_text_fragments(" ".join(pages[page_no]), page_no=page_no))
    return fragments


def parse_with_ocr_service(
    storage_key: str,
    file_name: str | None = None,
    *,
    document_id: str | None = None,
    version_id: str | None = None,
    profile_id: str | None = None,
    document_type: str | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if worker_ocr_http_enabled():
        client = OcrClient()
    else:
        client = None
    if client is not None and client.enabled:
        use_job_api = os.getenv("AICHECK_OCR_USE_JOB_API", "true").lower() != "false"
        if use_job_api and hasattr(client, "parse_via_job_sync"):
            return client.parse_via_job_sync(
                {
                    "documentId": document_id,
                    "documentVersionId": version_id,
                    "documentType": document_type,
                    "profileId": profile_id,
                    "storageKey": storage_key,
                    "fileName": file_name,
                    "options": {"enableTables": True, "enableSeals": True, "enableFallback": True, **(options or {})},
                }
            )
        return client.parse_sync(storage_key, file_name=file_name)
    return ocr_service.parse_document(storage_key, file_name=file_name, options=options)


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def parse_document(self, document_id: str, version_id: str, storage_key: str, file_name: str | None = None) -> dict[str, Any]:
    refresh_worker_state()
    task = repo.ocr_task_for(document_id, version_id, file_name)
    version = repo.find_one("versions", version_id)
    if task is None and version is None:
        load_state()
        task = repo.ocr_task_for(document_id, version_id, file_name)
        version = repo.find_one("versions", version_id)
    if task and task.get("status") == "已取消":
        flush_state()
        return {"documentId": document_id, "versionId": version_id, "status": "canceled"}
    if task and task.get("status") == "成功" and (version or {}).get("ocrStatus") == "已识别":
        flush_state()
        return {"documentId": document_id, "versionId": version_id, "status": "success", "alreadyCompleted": True}
    repo.mark_task_running(task, "OCR worker 开始处理。")
    document = repo.find_one("documents", document_id)
    profile_id = (version or {}).get("ocrProfileId") or (document or {}).get("ocrProfileId")
    document_type = (version or {}).get("documentType") or (document or {}).get("documentType")
    knowledge_file = repo.knowledge_file_for_version(version_id)
    ocr_options: dict[str, Any] = {}
    if (knowledge_file or {}).get("sourceType") == "standard":
        ocr_options["textLayerOnly"] = True
    ocr_job_record = repo.create_ocr_job_record(
        document_id=document_id,
        version_id=version_id,
        storage_key=storage_key,
        file_name=file_name,
        profile_id=profile_id,
        document_type=document_type,
    )
    try:
        result = parse_with_ocr_service(
            storage_key,
            file_name=file_name,
            document_id=document_id,
            version_id=version_id,
            profile_id=profile_id,
            document_type=document_type,
            options=ocr_options,
        )
    except Exception:
        result = {
            "storageKey": storage_key,
            "fileName": file_name,
            "status": "failed",
            "fragments": [],
            "fields": [],
            "seals": [],
            "diagnostics": [service_failure_message("OCR 服务")],
        }
    parse_result_record = repo.finish_ocr_job_record(ocr_job_record, result)
    applied = repo.apply_ocr_result(document_id, version_id, result)
    flush_state()
    next_dispatch = None
    if applied.get("status") == "success":
        if knowledge_file:
            next_dispatch = task_dispatcher.dispatch_slice(knowledge_file["id"])
    return {
        **result,
        "applied": applied,
        "nextDispatch": next_dispatch,
        "ocrJobRecordId": ocr_job_record.get("id"),
        "ocrParseResultId": (parse_result_record or {}).get("parseResultId"),
    }


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def recognize_seals(self, document_id: str, version_id: str) -> dict[str, Any]:
    refresh_worker_state()
    load_state()
    version = repo.find_one("versions", version_id)
    storage_key = version.get("storageKey") if version else version_id
    result = parse_with_ocr_service(
        storage_key,
        file_name=(repo.find_one("documents", document_id) or {}).get("fileName"),
        document_id=document_id,
        version_id=version_id,
    )
    flush_state()
    return {"documentId": document_id, "versionId": version_id, "seals": result.get("seals") or []}


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def slice_knowledge(self, file_id: str) -> dict[str, Any]:
    refresh_worker_state()
    task = next((item for item in repo.state["knowledge_tasks"] if item.get("taskType") == "slice" and item.get("targetId") == file_id), None)
    file = repo.find_one("knowledge_files", file_id)
    if task is None and file is None:
        load_state()
        task = next((item for item in repo.state["knowledge_tasks"] if item.get("taskType") == "slice" and item.get("targetId") == file_id), None)
        file = repo.find_one("knowledge_files", file_id)
    if task and task.get("status") == "已取消":
        flush_state()
        return {"fileId": file_id, "status": "canceled", "chunkCount": 0}
    if task and task.get("status") == "成功" and (file or {}).get("sliceStatus") == "已切片":
        chunk_count = len([item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == file_id])
        flush_state()
        return {"fileId": file_id, "status": "success", "chunkCount": chunk_count, "alreadyCompleted": True}
    repo.mark_task_running(task, "切片 worker 开始处理。")
    if not file:
        repo.mark_task_failed(task, "切片任务失败：找不到关联知识文件。")
        flush_state()
        return {"fileId": file_id, "status": "missing", "chunkCount": 0}
    fragments = knowledge_slice_fragments_from_ocr(file)
    if not fragments:
        fields = [
            item
            for item in repo.state["extracted_fields"]
            if item.get("documentVersionId") == file.get("documentVersionId")
        ]
        fragments = [
            {"pageNo": item.get("pageNo") or 1, "text": f"{item.get('fieldName')}: {item.get('fieldValue')}"}
            for item in fields
        ]
    result = repo.apply_slice_result(file_id, fragments or None)
    flush_state()
    if result.get("status") == "success":
        result["nextDispatch"] = task_dispatcher.dispatch_embed(file_id)
    return result


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def embed_knowledge(self, file_id: str) -> dict[str, Any]:
    refresh_worker_state()
    chunks = [item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == file_id]
    embedding_model = "embedding-default"
    task = next((item for item in repo.state["knowledge_tasks"] if item.get("taskType") == "vector" and item.get("targetId") == file_id), None)
    file = repo.find_one("knowledge_files", file_id)
    if task is None and file is None and not chunks:
        load_state()
        chunks = [item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == file_id]
        task = next((item for item in repo.state["knowledge_tasks"] if item.get("taskType") == "vector" and item.get("targetId") == file_id), None)
        file = repo.find_one("knowledge_files", file_id)
    vector_count = len(chunks) or 1
    if task and task.get("status") == "已取消":
        flush_state()
        return {"fileId": file_id, "status": "canceled", "vectorCount": 0}
    if task and task.get("status") == "成功" and (file or {}).get("vectorStatus") == "已向量化":
        flush_state()
        return {"fileId": file_id, "status": "success", "vectorCount": int((file or {}).get("vectorCount") or vector_count), "alreadyCompleted": True}
    repo.mark_task_running(task, "向量化 worker 开始处理。")
    if not file:
        repo.mark_task_failed(task, "向量化任务失败：找不到关联知识文件。")
        flush_state()
        return {"fileId": file_id, "status": "missing", "vectorCount": 0}
    try:
        vectors: list[dict[str, Any]] = []
        if chunks:
            embedding_response = LiteLLMClient().embed_sync(
                [item["text"] for item in chunks[:16]],
                model=embedding_model,
            )
            vectors = [
                item
                for item in embedding_response.get("data", [])
                if isinstance(item, dict)
            ]
            vector_count = len(vectors)
        result = repo.apply_embed_result(
            file_id,
            vector_count,
            vectors=vectors,
            embedding_model=embedding_model,
        )
    except Exception:
        message = f"EXTERNAL_TOOL_FAILED: {service_failure_message('LiteLLM embedding')}"
        result = {"fileId": file_id, "status": "failed", "errorMessage": message}
        if task:
            repo.mark_task_failed(task, message)
    flush_state()
    return result


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def ai_recheck(self, project_id: str, node_id: int, run_id: str) -> dict[str, Any]:
    refresh_worker_state()
    run = repo.find_one("ai_runs", run_id)
    if not run:
        load_state()
        run = repo.find_one("ai_runs", run_id)
    if not run:
        return {"projectId": project_id, "nodeId": node_id, "runId": run_id, "status": "missing"}
    if run.get("status") in {"完成", "失败"} and run.get("finishedAt"):
        flush_state()
        return {"projectId": project_id, "nodeId": node_id, "runId": run_id, "status": run.get("status"), "alreadyCompleted": True}
    node = repo.node(project_id, node_id)
    project = repo.require_project(project_id)
    pack = load_business_pack(run.get("businessPackId") or (project or {}).get("businessPackId") or "engineering_inspection_v1")
    version_ids = set(run.get("inputDocumentVersionIds") or [])
    grounding_input = build_grounded_review_input(repo.state, version_ids)
    grounding_block = grounding_prompt_block(grounding_input)
    fields = grounding_input.get("fields") or []
    evidence_links = grounding_input.get("evidenceLinks") or []
    rule = matching_rule_for_node(pack, node_id)
    prompt_template = production_prompt_template_for_run(run)
    prompt = build_ai_review_prompt(pack, node=node, fields=fields, rule=rule, prompt_template=prompt_template)
    review_task_json = json.dumps(
        {
            "task": "Generate ReviewFindingDraftList JSON only.",
            "requirements": [
                "Every finding must require human confirmation.",
                "Do not infer names, dates, validity, project coverage, certificate authenticity, seal text, or table values that are not present in evidence.",
                *grounding_block["requirements"],
            ],
            "strictGroundingPolicy": grounding_block["strictGroundingPolicy"],
            "projectId": project_id,
            "nodeId": node_id,
            "fieldCount": len(fields),
            "groundingStatus": grounding_input.get("groundingStatus"),
            "groundedOcrEvidence": grounding_block["groundedOcrEvidence"],
            "evidenceLinkIds": [item.get("id") for item in evidence_links],
        },
        ensure_ascii=False,
    )
    user_prompt = prompt["user"].replace("{{reviewTaskJson}}", review_task_json)
    if review_task_json not in user_prompt:
        user_prompt = f"{user_prompt}\n\n{review_task_json}"
    messages = [{"role": "system", "content": prompt["system"]}, {"role": "user", "content": user_prompt}]
    run["promptAudit"] = {
        "promptVersion": run.get("promptVersion"),
        "promptTemplateId": (prompt_template or {}).get("id"),
        "promptTemplateName": (prompt_template or {}).get("name"),
        "promptTemplateVersion": (prompt_template or {}).get("version"),
        "messagesHash": stable_hash_payload(messages),
        "systemPrompt": prompt["system"],
        "userPrompt": user_prompt,
        "plannerPrompt": (prompt.get("template") or {}).get("plannerPrompt") or "",
        "criticPrompt": (prompt.get("template") or {}).get("criticPrompt") or "",
        "messages": messages,
        "payloadPolicy": "full_prompt_stored_for_audit",
    }
    try:
        response = LiteLLMClient().chat_sync(
            messages,
            model=run.get("model") or "review-chat",
            temperature=0.1,
        )
        answer = LiteLLMClient.first_message_text(response) or "AI 复核完成，建议人工确认关键证据链。"
        message = ((response.get("choices") or [{}])[0].get("message") or {}) if isinstance(response.get("choices"), list) else {}
        conversation_id = str(response.get("id") or response.get("conversation_id") or f"llm-{stable_hash_payload(response)[7:23]}")
        run["llmConversationId"] = conversation_id
        run["llmMetadata"] = {
            "llmExecution": "litellm",
            "llmCalled": True,
            "conversationId": conversation_id,
            "modelAlias": run.get("model") or "review-chat",
            "promptVersion": run.get("promptVersion"),
            "promptTemplateId": (prompt_template or {}).get("id"),
            "promptHash": run["promptAudit"]["messagesHash"],
            "responseHash": stable_hash_payload(response),
            "usage": response.get("usage") or {},
            "groundingStatus": grounding_input.get("groundingStatus"),
            "groundingInputSummary": grounding_input.get("summary") or {},
            "reasoningProcess": str(
                message.get("reasoning_content")
                or message.get("reasoning")
                or message.get("reasoningSummary")
                or "模型返回审查建议；未返回单独的公开推理摘要。"
            )[:3000],
            "resultText": answer[:4000],
        }
        run["reasoningProcess"] = run["llmMetadata"]["reasoningProcess"]
        run["llmResultText"] = run["llmMetadata"]["resultText"]
        run["status"] = "完成"
        run["finishedAt"] = server_time()
        rule_ref = {
            "ruleCode": (rule or {}).get("ruleKey") or (rule or {}).get("id"),
            "ruleSetVersion": run.get("ruleVersion") or (rule or {}).get("version"),
        }
        legacy_draft = {
            "id": f"FND-DRAFT-{run_id}",
            "projectId": project_id,
            "nodeId": node_id,
            "businessPackId": run.get("businessPackId"),
            "businessPackVersion": run.get("businessPackVersion"),
            "businessPackSnapshotHash": run.get("businessPackSnapshotHash"),
            "agentId": run.get("agentId"),
            "agentVersion": run.get("agentVersion"),
            "findingType": "ai_review_suggestion",
            "severity": "medium",
            "title": "AI 资料复核建议",
            "description": answer[:800],
            "evidenceLinkIds": [item.get("id") for item in evidence_links[:3] if isinstance(item, dict)],
            "evidenceRefs": [
                {
                    "evidenceLinkId": item.get("id"),
                    "documentVersionId": item.get("documentVersionId"),
                    "pageNo": item.get("pageNo"),
                    "bbox": item.get("bbox"),
                    "source": "evidence_link",
                }
                for item in evidence_links[:3]
                if isinstance(item, dict)
            ],
            "ruleRefs": [rule_ref] if rule_ref.get("ruleCode") else [],
            "kbRefs": [],
            "confidence": 0.82,
            "suggestedAction": "human_confirm",
            "requiresHumanConfirmation": True,
            "status": "pending_human_review",
        }
        guarded_drafts = apply_grounding_guardrails([legacy_draft], grounding_input)
        guarded_draft = guarded_drafts[0] if guarded_drafts else legacy_draft
        run["llmMetadata"]["groundingStatus"] = guarded_draft.get("groundingStatus")
        run["llmMetadata"]["unsupportedClaims"] = guarded_draft.get("unsupportedClaims") or []
        run["steps"] = [
            {
                "id": f"STEP-{run_id}",
                "title": "LiteLLM 复核",
                "inputSummary": f"{len(fields)} 个 OCR 字段",
                "action": "chat.completions",
                "conclusion": "完成",
                "evidenceLinkIds": [item.get("id") for item in evidence_links[:3] if isinstance(item, dict)],
            }
        ]
        run["suggestion"].update(
            {
                "result": "需人工确认",
                "opinionDraft": str(guarded_draft.get("description") or answer)[:800],
                "confidence": guarded_draft.get("confidence", 0.5),
                "manualConfirmItems": ["证据链和原件一致性"],
            }
        )
        run["evidenceLinks"] = repo.clone(evidence_links[:5])
        repo.state.setdefault("ai_trace_steps", []).append(
            {
                "id": f"TRACE-{run_id}-LLM-{stable_hash_payload(response)[7:13].upper()}",
                "aiRunId": run_id,
                "traceId": f"TRACE-{run_id}",
                "sequence": len([item for item in repo.state.get("ai_trace_steps", []) if item.get("aiRunId") == run_id]) + 1,
                "stepType": "llm_review",
                "name": "LiteLLM 对话与 Prompt 审计",
                "status": "completed",
                "conversationId": run.get("llmConversationId"),
                "promptHash": (run.get("llmMetadata") or {}).get("promptHash"),
                "responseHash": (run.get("llmMetadata") or {}).get("responseHash"),
                "reasoningProcess": run.get("reasoningProcess"),
                "resultText": run.get("llmResultText"),
                "createdAt": server_time(),
            }
        )
        run["findingDrafts"] = guarded_drafts
        status = "完成"
    except Exception:
        run["status"] = "失败"
        run["finishedAt"] = server_time()
        run["errorCode"] = "AI_RUN_FAILED"
        run["errorMessage"] = service_failure_message("LiteLLM AI 复核")
        status = "失败"
    flush_state()
    return {"projectId": project_id, "nodeId": node_id, "runId": run_id, "status": status}


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def llm_compare(self, run_id: str) -> dict[str, Any]:
    refresh_worker_state()
    run = repo.find_one("llm_compare_runs", run_id, id_field="runId")
    if not run:
        load_state()
        run = repo.find_one("llm_compare_runs", run_id, id_field="runId")
    if not run:
        return {"runId": run_id, "status": "missing"}
    if run.get("status") in {"完成", "失败"} and run.get("finishedAt"):
        flush_state()
        return {"runId": run_id, "status": run.get("status"), "alreadyCompleted": True}
    results = []
    try:
        run["status"] = "运行中"
        version_ids = compare_document_version_ids(run)
        grounding_input = build_grounded_review_input(repo.state, version_ids)
        grounding_block = grounding_prompt_block(grounding_input)
        compare_payload = {
            "task": "Compare model answers for a human reviewer. Do not issue a final business approval, rejection, or compliance conclusion.",
            "compareOnly": True,
            "question": run.get("question") or "请对比审查意见。",
            "strictGroundingPolicy": grounding_block["strictGroundingPolicy"],
            "requirements": [
                "Answer only as a model comparison assistant.",
                "Do not state that documents are compliant, valid, authentic, covered, or pass unless the exact fact is present in groundedOcrEvidence.",
                "If OCR evidence is insufficient, say that the comparison requires human confirmation.",
                *grounding_block["requirements"],
            ],
            "groundedOcrEvidence": grounding_block["groundedOcrEvidence"],
            "evidenceLinkIds": run.get("evidenceLinkIds") or [],
            "requiredOutput": {
                "answer": "Short compare-only response in Chinese.",
                "mustInclude": ["groundingStatus", "requiresHumanConfirmation"],
            },
        }
        messages = [
            {
                "role": "system",
                "content": "You compare LLM answers for reviewers. You must stay evidence-only and compare-only.",
            },
            {"role": "user", "content": json.dumps(compare_payload, ensure_ascii=False)},
        ]
        run["groundingStatus"] = grounding_input.get("groundingStatus")
        run["groundingInputSummary"] = grounding_input.get("summary") or {}
        run["promptAudit"] = {
            "messagesHash": stable_hash_payload(messages),
            "payloadPolicy": "compare_only_grounded_ocr_evidence",
            "messages": messages,
        }
        for model in run.get("modelCodes") or ["default-chat", "compare-fast"]:
            response = LiteLLMClient().chat_sync(
                messages,
                model=model,
                temperature=0.1,
            )
            answer = LiteLLMClient.first_message_text(response)
            unsupported = unsupported_claims(answer or "", [str(item) for item in grounding_input.get("evidenceTextCorpus") or []])
            result_grounding_status = "grounded" if grounding_input.get("groundingStatus") == "grounded" and not unsupported else "insufficient_evidence"
            if result_grounding_status != "grounded":
                answer = f"证据不足，以下仅作为模型回答对比参考，不能作为业务通过结论：{str(answer or '')[:1200]}"
            results.append(
                {
                    "modelCode": model,
                    "answer": answer,
                    "confidence": 0.8 if result_grounding_status == "grounded" else 0.5,
                    "evidenceLinkIds": run.get("evidenceLinkIds") or ["EV-24-001"],
                    "groundingStatus": result_grounding_status,
                    "unsupportedClaims": unsupported,
                    "requiresHumanConfirmation": True,
                    "compareOnly": True,
                    "latencyMs": 0,
                }
            )
        run["results"] = results
        run["status"] = "完成"
        run["finishedAt"] = server_time()
    except Exception:
        run["status"] = "失败"
        run["errorCode"] = "EXTERNAL_TOOL_FAILED"
        run["errorMessage"] = service_failure_message("LiteLLM 模型对比")
        run["finishedAt"] = server_time()
    flush_state()
    return {"runId": run_id, "status": run.get("status")}


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def export_package(self, export_id: str) -> dict[str, Any]:
    refresh_worker_state()
    task = repo.find_one("export_tasks", export_id)
    if not task:
        load_state()
        task = repo.find_one("export_tasks", export_id)
    if task:
        if task.get("status") == "已取消":
            flush_state()
            return {"exportId": export_id, "status": "canceled"}
        if task.get("status") == "可下载" and task.get("storageKey"):
            flush_state()
            return {"exportId": export_id, "status": "可下载", "alreadyCompleted": True}
        repo.mark_task_running(task, "导出 worker 开始处理。")
        task["progress"] = 80
        try:
            repo.attach_export_artifact(task)
        except Exception:
            repo.mark_task_failed(task, f"EXTERNAL_TOOL_FAILED: {service_failure_message('对象存储导出')}")
            flush_state()
            raise
        task["status"] = "可下载"
        task["progress"] = 100
        task["finishedAt"] = server_time()
        task["updatedAt"] = task["finishedAt"]
        repo.append_task_log(task, "info", "导出任务完成。")
    flush_state()
    return {"exportId": export_id, "status": task.get("status") if task else "missing"}
