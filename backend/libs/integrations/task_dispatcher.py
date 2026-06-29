from __future__ import annotations

import os
from typing import Any


def dispatch_mode() -> str:
    return os.getenv("AICHECK_TASK_DISPATCH", "disabled").strip().lower() or "disabled"


def dispatch_parse_document(document_id: str, version_id: str, storage_key: str, file_name: str | None = None) -> dict[str, Any]:
    mode = dispatch_mode()
    if mode == "inline":
        from apps.worker.tasks import parse_document

        return {"mode": mode, "result": parse_document.run(document_id, version_id, storage_key, file_name)}
    if mode == "celery":
        from apps.worker.tasks import parse_document

        result = parse_document.delay(document_id, version_id, storage_key, file_name)
        return {"mode": mode, "taskId": result.id}
    return {"mode": mode, "taskId": None}


def dispatch_slice(file_id: str) -> dict[str, Any]:
    mode = dispatch_mode()
    if mode == "inline":
        from apps.worker.tasks import slice_knowledge

        return {"mode": mode, "result": slice_knowledge.run(file_id)}
    if mode == "celery":
        from apps.worker.tasks import slice_knowledge

        result = slice_knowledge.delay(file_id)
        return {"mode": mode, "taskId": result.id}
    return {"mode": mode, "taskId": None}


def dispatch_embed(file_id: str) -> dict[str, Any]:
    mode = dispatch_mode()
    if mode == "inline":
        from apps.worker.tasks import embed_knowledge

        return {"mode": mode, "result": embed_knowledge.run(file_id)}
    if mode == "celery":
        from apps.worker.tasks import embed_knowledge

        result = embed_knowledge.delay(file_id)
        return {"mode": mode, "taskId": result.id}
    return {"mode": mode, "taskId": None}


def dispatch_ai_recheck(project_id: str, node_id: int, run_id: str) -> dict[str, Any]:
    orchestration_mode = os.getenv("AICHECK_REVIEW_ORCHESTRATION", "legacy").strip().lower() or "legacy"
    if orchestration_mode in {"temporal", "inline"}:
        from libs.review_orchestrator import dispatch_review_run

        return dispatch_review_run(run_id)
    mode = dispatch_mode()
    if mode == "inline":
        from apps.worker.tasks import ai_recheck

        return {"mode": mode, "result": ai_recheck.run(project_id, node_id, run_id)}
    if mode == "celery":
        from apps.worker.tasks import ai_recheck

        result = ai_recheck.delay(project_id, node_id, run_id)
        return {"mode": mode, "taskId": result.id}
    return {"mode": mode, "taskId": None}


def dispatch_llm_compare(run_id: str) -> dict[str, Any]:
    mode = dispatch_mode()
    if mode == "inline":
        from apps.worker.tasks import llm_compare

        return {"mode": mode, "result": llm_compare.run(run_id)}
    if mode == "celery":
        from apps.worker.tasks import llm_compare

        result = llm_compare.delay(run_id)
        return {"mode": mode, "taskId": result.id}
    return {"mode": mode, "taskId": None}


def dispatch_export(export_id: str) -> dict[str, Any]:
    mode = dispatch_mode()
    if mode == "inline":
        from apps.worker.tasks import export_package

        return {"mode": mode, "result": export_package.run(export_id)}
    if mode == "celery":
        from apps.worker.tasks import export_package

        result = export_package.delay(export_id)
        return {"mode": mode, "taskId": result.id}
    return {"mode": mode, "taskId": None}
