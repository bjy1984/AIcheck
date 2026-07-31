from __future__ import annotations

import hashlib
import os
from typing import Any

from libs.capacity_guard import cpu_heavy_dispatch_status
from libs.security.tenant import current_tenant_id
from libs.task_priority import broker_priority


def dispatch_mode() -> str:
    return os.getenv("AICHECK_TASK_DISPATCH", "disabled").strip().lower() or "disabled"


def cpu_heavy_dispatch_blocker(mode: str) -> dict[str, Any] | None:
    if mode != "celery":
        return None
    status = cpu_heavy_dispatch_status()
    if status["allowed"]:
        return None
    return {
        "mode": mode,
        "taskId": None,
        "queue": "cpu.heavy",
        "statusReason": status["statusReason"],
        "capacity": status["capacity"],
    }


def deterministic_task_id(scope: str, value: str) -> str:
    digest = hashlib.sha256(f"{scope}:{value}".encode("utf-8")).hexdigest()[:24]
    return f"aicheck-{scope}-{digest}"


def dispatch_parse_document(document_id: str, version_id: str, storage_key: str, file_name: str | None = None) -> dict[str, Any]:
    mode = dispatch_mode()
    if mode == "inline":
        from apps.worker.tasks import parse_document

        return {"mode": mode, "result": parse_document.run(document_id, version_id, storage_key, file_name)}
    if mode == "celery":
        queue = "ocr.parse_document"
        from apps.worker.tasks import parse_document

        result = parse_document.apply_async(
            args=[document_id, version_id, storage_key, file_name],
            queue=queue,
            priority=broker_priority(7),
            task_id=deterministic_task_id("ocr-document", version_id),
        )
        return {
            "mode": mode,
            "taskId": result.id,
            "queue": queue,
            "priority": 7,
            "statusReason": "ocr_prepare_queued",
        }
    return {"mode": mode, "taskId": None}


def dispatch_slice(file_id: str) -> dict[str, Any]:
    mode = dispatch_mode()
    if mode == "inline":
        from apps.worker.tasks import slice_knowledge

        return {"mode": mode, "result": slice_knowledge.run(file_id)}
    if mode == "celery":
        if blocker := cpu_heavy_dispatch_blocker(mode):
            return blocker
        from apps.worker.tasks import slice_knowledge

        result = slice_knowledge.apply_async(args=[file_id], queue="cpu.heavy", priority=broker_priority(2))
        return {"mode": mode, "taskId": result.id, "queue": "cpu.heavy", "priority": 2}
    return {"mode": mode, "taskId": None}


def dispatch_embed(file_id: str) -> dict[str, Any]:
    mode = dispatch_mode()
    if mode == "inline":
        from apps.worker.tasks import embed_knowledge

        return {"mode": mode, "result": embed_knowledge.run(file_id)}
    if mode == "celery":
        if blocker := cpu_heavy_dispatch_blocker(mode):
            return blocker
        from apps.worker.tasks import embed_knowledge

        result = embed_knowledge.apply_async(args=[file_id], queue="cpu.heavy", priority=broker_priority(1))
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


def dispatch_ocr_pipeline_official(run_id: str) -> dict[str, Any]:
    return _dispatch_ocr_pipeline_stage(
        run_id,
        task_name="ocr_pipeline_official_extract",
        queue="ocr.remote",
        status_reason="official_ocr_queued",
    )


def dispatch_mineru_ocr(job_record_id: str) -> dict[str, Any]:
    mode = dispatch_mode()
    tenant_id = current_tenant_id()
    if mode == "inline":
        from apps.worker.tasks import mineru_ocr_extract

        return {
            "mode": mode,
            "result": mineru_ocr_extract.run(job_record_id, tenant_id),
        }
    if mode == "celery":
        from apps.worker.tasks import mineru_ocr_extract

        result = mineru_ocr_extract.apply_async(
            args=[job_record_id, tenant_id],
            queue="ocr.remote",
            priority=broker_priority(9),
            task_id=deterministic_task_id(
                "mineru-ocr",
                f"{tenant_id}:{job_record_id}",
            ),
        )
        return {
            "mode": mode,
            "taskId": result.id,
            "queue": "ocr.remote",
            "priority": 9,
            "statusReason": "mineru_ocr_queued",
        }
    return {
        "mode": mode,
        "taskId": None,
        "statusReason": "mineru_ocr_requires_task_dispatch",
    }


def dispatch_ocr_pipeline_qwen(run_id: str) -> dict[str, Any]:
    mode = dispatch_mode()
    if mode == "celery":
        from apps.worker.tasks import ocr_pipeline_qwen_extract

        result = ocr_pipeline_qwen_extract.apply_async(
            args=[run_id],
            queue="llm.remote",
            priority=broker_priority(9),
            task_id=deterministic_task_id("ocr-qwen", run_id),
        )
        return {
            "mode": mode,
            "taskId": result.id,
            "queue": "llm.remote",
            "priority": 9,
            "statusReason": "qwen_grounded_extract_queued",
        }
    return {"mode": mode, "taskId": None, "statusReason": "ocr_pipeline_requires_celery"}


def dispatch_ocr_pipeline_structure(run_id: str) -> dict[str, Any]:
    return _dispatch_ocr_pipeline_stage(
        run_id,
        task_name="ocr_pipeline_structure_scan",
        queue="cpu.heavy",
        status_reason="ocr_structure_scan_queued",
    )


def dispatch_ocr_pipeline_seal(run_id: str) -> dict[str, Any]:
    return _dispatch_ocr_pipeline_stage(
        run_id,
        task_name="ocr_pipeline_seal_scan",
        queue="cpu.heavy",
        status_reason="ocr_seal_scan_queued",
    )


def dispatch_ocr_pipeline_fusion(run_id: str) -> dict[str, Any]:
    return _dispatch_ocr_pipeline_stage(
        run_id,
        task_name="ocr_pipeline_evidence_fusion",
        queue="business.light",
        status_reason="ocr_evidence_fusion_queued",
    )


def _dispatch_ocr_pipeline_stage(
    run_id: str,
    *,
    task_name: str,
    queue: str,
    status_reason: str,
) -> dict[str, Any]:
    mode = dispatch_mode()
    if mode != "celery":
        return {"mode": mode, "taskId": None, "statusReason": "ocr_pipeline_requires_celery"}
    if queue == "cpu.heavy" and (blocker := cpu_heavy_dispatch_blocker(mode)):
        return blocker
    from apps.worker import tasks

    task = getattr(tasks, task_name)
    result = task.apply_async(
        args=[run_id],
        queue=queue,
        priority=broker_priority(9),
        task_id=deterministic_task_id(task_name.replace("_", "-"), run_id),
    )
    return {
        "mode": mode,
        "taskId": result.id,
        "queue": queue,
        "priority": 9,
        "statusReason": status_reason,
    }


def dispatch_ocr_pipeline_finalize(run_id: str) -> dict[str, Any]:
    mode = dispatch_mode()
    if mode == "celery":
        from apps.worker.tasks import ocr_pipeline_finalize

        result = ocr_pipeline_finalize.apply_async(
            args=[run_id],
            queue="business.light",
            priority=broker_priority(9),
            task_id=deterministic_task_id("ocr-finalize", run_id),
        )
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


def dispatch_review_conversation(
    *,
    session_id: str,
    assistant_message_id: str,
    user_text: str,
    context: dict[str, Any],
    execution_id: str,
) -> dict[str, Any]:
    """派发 Version B 对话 Agent 执行到任务队列。

    context 为 API 进程在请求线程内构建的纯数据快照（含请求级可见性过滤结果），
    worker 侧不再重建请求上下文；跨进程互斥与取消由 agent_executions 心跳承担。
    """
    mode = dispatch_mode()
    if mode == "inline":
        from apps.worker.tasks import review_conversation_execute

        return {
            "mode": mode,
            "result": review_conversation_execute.run(
                session_id, assistant_message_id, user_text, context, execution_id
            ),
        }
    if mode == "celery":
        from apps.worker.tasks import review_conversation_execute

        result = review_conversation_execute.apply_async(
            args=[session_id, assistant_message_id, user_text, context, execution_id],
            queue="llm.remote",
            priority=broker_priority(8),
            task_id=deterministic_task_id("review-conversation", execution_id),
        )
        return {
            "mode": mode,
            "taskId": result.id,
            "queue": "llm.remote",
            "priority": 8,
            "statusReason": "review_conversation_queued",
        }
    return {
        "mode": mode,
        "taskId": None,
        "statusReason": "review_conversation_requires_task_dispatch",
    }
