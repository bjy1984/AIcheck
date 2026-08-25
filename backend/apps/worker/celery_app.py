from __future__ import annotations

import os

from celery import Celery

from libs.task_priority import MAX_TASK_PRIORITY, broker_priority

REDIS_URL = os.getenv("AICHECK_REDIS_URL", "redis://localhost:6379/0")
TASK_SOFT_TIME_LIMIT_SECONDS = int(os.getenv("AICHECK_CELERY_TASK_SOFT_TIME_LIMIT_SECONDS", "3900"))
TASK_TIME_LIMIT_SECONDS = int(os.getenv("AICHECK_CELERY_TASK_TIME_LIMIT_SECONDS", "4200"))
VISIBILITY_TIMEOUT_SECONDS = int(
    os.getenv(
        "AICHECK_CELERY_VISIBILITY_TIMEOUT_SECONDS",
        str(max(TASK_TIME_LIMIT_SECONDS + 900, 5100)),
    )
)

celery_app = Celery(
    "aicheck_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["apps.worker.tasks"],
)

celery_app.conf.update(
    task_routes={
        "apps.worker.tasks.parse_document": {"queue": "ocr.parse_document", "priority": broker_priority(7)},
        "apps.worker.tasks.ocr_pipeline_structure_scan": {"queue": "cpu.heavy", "priority": broker_priority(9)},
        "apps.worker.tasks.ocr_pipeline_seal_scan": {"queue": "cpu.heavy", "priority": broker_priority(9)},
        "apps.worker.tasks.ocr_pipeline_evidence_fusion": {"queue": "business.light", "priority": broker_priority(9)},
        "apps.worker.tasks.recognize_seals": {"queue": "cpu.heavy", "priority": broker_priority(9)},
        "apps.worker.tasks.slice_knowledge": {"queue": "cpu.heavy", "priority": broker_priority(2)},
        "apps.worker.tasks.embed_knowledge": {"queue": "cpu.heavy", "priority": broker_priority(1)},
        "apps.worker.tasks.mineru_ocr_extract": {"queue": "ocr.remote", "priority": broker_priority(9)},
        "apps.worker.tasks.ocr_pipeline_official_extract": {"queue": "ocr.remote", "priority": broker_priority(9)},
        "apps.worker.tasks.ocr_pipeline_qwen_extract": {"queue": "llm.remote", "priority": broker_priority(9)},
        "apps.worker.tasks.ocr_pipeline_finalize": {"queue": "business.light", "priority": broker_priority(9)},
        "apps.worker.tasks.document_ai_shadow_extract": {"queue": "document-ai.shadow"},
        "apps.worker.tasks.document_audit_pipeline_comparison": {"queue": "audit-pipeline.compare"},
        "apps.worker.tasks.ai_recheck": {"queue": "llm.remote", "priority": broker_priority(10)},
        "apps.worker.tasks.review_conversation_execute": {"queue": "llm.remote", "priority": broker_priority(8)},
        "apps.worker.tasks.llm_compare": {"queue": "llm.remote", "priority": broker_priority(5)},
        "apps.worker.tasks.export_package": {"queue": "business.light", "priority": broker_priority(3)},
        "apps.worker.tasks.auto_review_consume_evidence_events": {"queue": "business.light", "priority": broker_priority(8)},
        "apps.worker.tasks.auto_review_scan_due_projects": {"queue": "business.light", "priority": broker_priority(7)},
    },
    beat_schedule={
        "auto-review-consume-evidence-events": {
            "task": "apps.worker.tasks.auto_review_consume_evidence_events",
            "schedule": 60.0,
        },
        "auto-review-scan-due-projects": {
            "task": "apps.worker.tasks.auto_review_scan_due_projects",
            "schedule": 60.0,
        },
    },
    task_default_queue="business.light",
    task_default_priority=broker_priority(5),
    task_queue_max_priority=MAX_TASK_PRIORITY,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_retry_delay=10,
    task_soft_time_limit=TASK_SOFT_TIME_LIMIT_SECONDS,
    task_time_limit=TASK_TIME_LIMIT_SECONDS,
    result_expires=int(os.getenv("AICHECK_CELERY_RESULT_EXPIRES_SECONDS", "86400")),
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=int(os.getenv("AICHECK_CELERY_MAX_TASKS_PER_CHILD", "50")),
    worker_max_memory_per_child=int(os.getenv("AICHECK_CELERY_MAX_MEMORY_KB_PER_CHILD", "2097152")),
    broker_transport_options={
        "priority_steps": list(range(MAX_TASK_PRIORITY + 1)),
        "sep": ":",
        "visibility_timeout": VISIBILITY_TIMEOUT_SECONDS,
    },
    result_backend_transport_options={"visibility_timeout": VISIBILITY_TIMEOUT_SECONDS},
)
