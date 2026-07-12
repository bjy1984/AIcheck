from __future__ import annotations

import os

from celery import Celery

REDIS_URL = os.getenv("AICHECK_REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "aicheck_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["apps.worker.tasks"],
)

celery_app.conf.update(
    task_routes={
        "apps.worker.tasks.parse_document": {"queue": "cpu.heavy", "priority": 7},
        "apps.worker.tasks.ocr_pipeline_structure_scan": {"queue": "cpu.heavy", "priority": 9},
        "apps.worker.tasks.ocr_pipeline_seal_scan": {"queue": "cpu.heavy", "priority": 9},
        "apps.worker.tasks.ocr_pipeline_evidence_fusion": {"queue": "business.light", "priority": 9},
        "apps.worker.tasks.recognize_seals": {"queue": "cpu.heavy", "priority": 9},
        "apps.worker.tasks.slice_knowledge": {"queue": "cpu.heavy", "priority": 2},
        "apps.worker.tasks.embed_knowledge": {"queue": "cpu.heavy", "priority": 1},
        "apps.worker.tasks.ocr_pipeline_qwen_extract": {"queue": "llm.remote", "priority": 9},
        "apps.worker.tasks.ocr_pipeline_finalize": {"queue": "business.light", "priority": 9},
        "apps.worker.tasks.document_ai_shadow_extract": {"queue": "document-ai.shadow"},
        "apps.worker.tasks.document_audit_pipeline_comparison": {"queue": "audit-pipeline.compare"},
        "apps.worker.tasks.ai_recheck": {"queue": "llm.remote", "priority": 10},
        "apps.worker.tasks.llm_compare": {"queue": "llm.remote", "priority": 5},
        "apps.worker.tasks.export_package": {"queue": "business.light", "priority": 3},
    },
    task_default_queue="business.light",
    task_default_priority=5,
    task_queue_max_priority=10,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_retry_delay=10,
    worker_prefetch_multiplier=1,
    # Kombu's Redis transport checks priority_steps from left to right. Keep
    # the public task contract intuitive: larger numbers run first.
    broker_transport_options={
        "priority_steps": list(range(10, -1, -1)),
        "sep": ":",
    },
)
