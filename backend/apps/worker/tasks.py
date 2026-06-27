from __future__ import annotations

from typing import Any

from apps.ocr_service.service import ocr_service
from apps.worker.celery_app import celery_app
from libs.contracts.responses import server_time
from libs.db.repository import repo
from libs.integrations.litellm_client import LiteLLMClient
from libs.integrations.ocr_client import OcrClient


def load_state() -> None:
    repo.load_from_sync_mongo()


def flush_state() -> None:
    repo.flush_to_sync_mongo()


def parse_with_ocr_service(storage_key: str, file_name: str | None = None) -> dict[str, Any]:
    client = OcrClient()
    if client.enabled:
        return client.parse_sync(storage_key, file_name=file_name)
    return ocr_service.parse_document(storage_key, file_name=file_name)


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def parse_document(self, document_id: str, version_id: str, storage_key: str, file_name: str | None = None) -> dict[str, Any]:
    load_state()
    task = repo.ocr_task_for(document_id, version_id, file_name)
    if task and task.get("status") == "已取消":
        flush_state()
        return {"documentId": document_id, "versionId": version_id, "status": "canceled"}
    repo.mark_task_running(task, "OCR worker 开始处理。")
    result = parse_with_ocr_service(storage_key, file_name=file_name)
    applied = repo.apply_ocr_result(document_id, version_id, result)
    flush_state()
    return {**result, "applied": applied}


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def recognize_seals(self, document_id: str, version_id: str) -> dict[str, Any]:
    load_state()
    version = repo.find_one("versions", version_id)
    storage_key = version.get("storageKey") if version else version_id
    result = parse_with_ocr_service(
        storage_key,
        file_name=(repo.find_one("documents", document_id) or {}).get("fileName"),
    )
    flush_state()
    return {"documentId": document_id, "versionId": version_id, "seals": result.get("seals") or []}


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def slice_knowledge(self, file_id: str) -> dict[str, Any]:
    load_state()
    task = next((item for item in repo.state["knowledge_tasks"] if item.get("taskType") == "slice" and item.get("targetId") == file_id), None)
    if task and task.get("status") == "已取消":
        flush_state()
        return {"fileId": file_id, "status": "canceled", "chunkCount": 0}
    repo.mark_task_running(task, "切片 worker 开始处理。")
    file = repo.find_one("knowledge_files", file_id)
    fragments = []
    if file:
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
    return result


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def embed_knowledge(self, file_id: str) -> dict[str, Any]:
    load_state()
    chunks = [item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == file_id]
    vector_count = len(chunks) or 1
    task = next((item for item in repo.state["knowledge_tasks"] if item.get("taskType") == "vector" and item.get("targetId") == file_id), None)
    if task and task.get("status") == "已取消":
        flush_state()
        return {"fileId": file_id, "status": "canceled", "vectorCount": 0}
    repo.mark_task_running(task, "向量化 worker 开始处理。")
    try:
        if chunks:
            LiteLLMClient().embed_sync([item["text"] for item in chunks[:16]], model="embedding-default")
        result = repo.apply_embed_result(file_id, vector_count)
    except Exception as exc:
        result = {"fileId": file_id, "status": "failed", "errorMessage": str(exc)}
        if task:
            repo.mark_task_failed(task, f"EXTERNAL_TOOL_FAILED: {exc}")
    flush_state()
    return result


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def ai_recheck(self, project_id: str, node_id: int, run_id: str) -> dict[str, Any]:
    load_state()
    run = repo.find_one("ai_runs", run_id)
    if not run:
        return {"projectId": project_id, "nodeId": node_id, "runId": run_id, "status": "missing"}
    node = repo.node(project_id, node_id)
    fields = [
        item
        for item in repo.state["extracted_fields"]
        if item.get("documentVersionId") in set(run.get("inputDocumentVersionIds") or [])
    ]
    prompt = (
        f"请基于压力管道监检规则复核节点 {node_id} {node.get('name') if node else ''}。"
        f"OCR字段: {fields[:12]}"
    )
    try:
        response = LiteLLMClient().chat_sync(
            [{"role": "system", "content": "你是压力管道监督检验 AI 复核助手。"}, {"role": "user", "content": prompt}],
            model=run.get("model") or "review-chat",
            temperature=0.1,
        )
        answer = LiteLLMClient.first_message_text(response) or "AI 复核完成，建议人工确认关键证据链。"
        run["status"] = "完成"
        run["finishedAt"] = server_time()
        run["steps"] = [
            {
                "id": f"STEP-{run_id}",
                "title": "LiteLLM 复核",
                "inputSummary": f"{len(fields)} 个 OCR 字段",
                "action": "chat.completions",
                "conclusion": "完成",
                "evidenceLinkIds": [item["id"] for item in repo.state["evidence_links"][:3]],
            }
        ]
        run["suggestion"].update(
            {
                "result": "需人工确认",
                "opinionDraft": answer[:800],
                "confidence": 0.82,
                "manualConfirmItems": ["证据链和原件一致性"],
            }
        )
        run["evidenceLinks"] = repo.clone(repo.state["evidence_links"][:5])
        status = "完成"
    except Exception as exc:
        run["status"] = "失败"
        run["finishedAt"] = server_time()
        run["errorCode"] = "AI_RUN_FAILED"
        run["errorMessage"] = str(exc)
        status = "失败"
    flush_state()
    return {"projectId": project_id, "nodeId": node_id, "runId": run_id, "status": status}


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def llm_compare(self, run_id: str) -> dict[str, Any]:
    load_state()
    run = repo.find_one("llm_compare_runs", run_id, id_field="runId")
    if not run:
        return {"runId": run_id, "status": "missing"}
    results = []
    try:
        run["status"] = "运行中"
        for model in run.get("modelCodes") or ["default-chat", "compare-fast"]:
            response = LiteLLMClient().chat_sync(
                [{"role": "user", "content": run.get("question") or "请对比审查意见。"}],
                model=model,
                temperature=0.1,
            )
            results.append(
                {
                    "modelCode": model,
                    "answer": LiteLLMClient.first_message_text(response),
                    "confidence": 0.8,
                    "evidenceLinkIds": run.get("evidenceLinkIds") or ["EV-24-001"],
                    "latencyMs": 0,
                }
            )
        run["results"] = results
        run["status"] = "完成"
        run["finishedAt"] = server_time()
    except Exception as exc:
        run["status"] = "失败"
        run["errorCode"] = "EXTERNAL_TOOL_FAILED"
        run["errorMessage"] = str(exc)
        run["finishedAt"] = server_time()
    flush_state()
    return {"runId": run_id, "status": run.get("status")}


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def export_package(self, export_id: str) -> dict[str, Any]:
    load_state()
    task = repo.find_one("export_tasks", export_id)
    if task:
        task["status"] = "可下载"
        task["progress"] = 100
        task["finishedAt"] = server_time()
        repo.attach_export_artifact(task)
    flush_state()
    return {"exportId": export_id, "status": "可下载"}
