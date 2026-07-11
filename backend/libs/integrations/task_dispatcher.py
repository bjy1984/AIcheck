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

        result = parse_document.apply_async(
            args=[document_id, version_id, storage_key, file_name],
            queue="cpu.heavy",
            priority=7,
        )
        return {"mode": mode, "taskId": result.id, "queue": "cpu.heavy", "priority": 7}
    return {"mode": mode, "taskId": None}


def dispatch_slice(file_id: str) -> dict[str, Any]:
    mode = dispatch_mode()
    if mode == "inline":
        from apps.worker.tasks import slice_knowledge

        return {"mode": mode, "result": slice_knowledge.run(file_id)}
    if mode == "celery":
        from apps.worker.tasks import slice_knowledge

        result = slice_knowledge.apply_async(args=[file_id], queue="cpu.heavy", priority=2)
        return {"mode": mode, "taskId": result.id, "queue": "cpu.heavy", "priority": 2}
    return {"mode": mode, "taskId": None}


def dispatch_embed(file_id: str) -> dict[str, Any]:
    mode = dispatch_mode()
    if mode == "inline":
        from apps.worker.tasks import embed_knowledge

        return {"mode": mode, "result": embed_knowledge.run(file_id)}
    if mode == "celery":
        from apps.worker.tasks import embed_knowledge

        result = embed_knowledge.apply_async(args=[file_id], queue="cpu.heavy", priority=1)
        return {"mode": mode, "taskId": result.id, "queue": "cpu.heavy", "priority": 1}
    return {"mode": mode, "taskId": None}


def dispatch_document_ai_shadow(run_id: str) -> dict[str, Any]:
    """Document AI is intentionally asynchronous and never runs inline with baseline OCR."""
    mode = dispatch_mode()
    if mode == "celery":
        from apps.worker.tasks import document_ai_shadow_extract

        result = document_ai_shadow_extract.delay(run_id)
        return {"mode": mode, "taskId": result.id, "statusReason": "shadow_queued"}
    return {
        "mode": mode,
        "taskId": None,
        "statusReason": "document_ai_shadow_requires_celery",
    }


def dispatch_ocr_pipeline_qwen(run_id: str) -> dict[str, Any]:
    mode = dispatch_mode()
    if mode == "celery":
        from apps.worker.tasks import ocr_pipeline_qwen_extract

        result = ocr_pipeline_qwen_extract.apply_async(args=[run_id], queue="llm.remote", priority=9)
        return {
            "mode": mode,
            "taskId": result.id,
            "queue": "llm.remote",
            "priority": 9,
            "statusReason": "qwen_grounded_extract_queued",
        }
    return {"mode": mode, "taskId": None, "statusReason": "ocr_pipeline_requires_celery"}


def dispatch_ocr_pipeline_finalize(run_id: str) -> dict[str, Any]:
    mode = dispatch_mode()
    if mode == "celery":
        from apps.worker.tasks import ocr_pipeline_finalize

        result = ocr_pipeline_finalize.apply_async(args=[run_id], queue="business.light", priority=9)
        return {
            "mode": mode,
            "taskId": result.id,
            "queue": "business.light",
            "priority": 9,
            "statusReason": "ocr_pipeline_finalize_queued",
        }
    return {"mode": mode, "taskId": None, "statusReason": "ocr_pipeline_requires_celery"}


def dispatch_document_audit_pipeline_comparison(run_id: str) -> dict[str, Any]:
    """Pipeline A/B calls are isolated from OCR, ReviewRun, and formal business queues."""
    mode = dispatch_mode()
    if mode == "celery":
        from apps.worker.tasks import document_audit_pipeline_comparison

        result = document_audit_pipeline_comparison.delay(run_id)
        return {"mode": mode, "taskId": result.id, "statusReason": "pipeline_comparison_queued"}
    return {
        "mode": mode,
        "taskId": None,
        "statusReason": "pipeline_comparison_requires_celery",
    }


def ai_recheck_dispatch_readiness() -> dict[str, Any]:
    orchestration_mode = os.getenv("AICHECK_REVIEW_ORCHESTRATION", "legacy").strip().lower() or "legacy"
    if orchestration_mode in {"temporal", "inline"}:
        return {
            "ready": True,
            "mode": orchestration_mode,
            "orchestrationMode": orchestration_mode,
            "statusReason": "review_orchestration_enabled",
        }
    mode = dispatch_mode()
    if mode in {"inline", "celery"}:
        return {
            "ready": True,
            "mode": mode,
            "orchestrationMode": orchestration_mode,
            "statusReason": "task_dispatch_enabled",
        }
    return {
        "ready": False,
        "mode": mode,
        "orchestrationMode": orchestration_mode,
        "statusReason": "AICHECK_TASK_DISPATCH is disabled; AI recheck will not be queued.",
    }


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
