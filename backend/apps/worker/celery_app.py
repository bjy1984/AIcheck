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
        "apps.worker.tasks.parse_document": {"queue": "ocr.parse_document"},
        "apps.worker.tasks.recognize_seals": {"queue": "ocr.recognize_seals"},
        "apps.worker.tasks.slice_knowledge": {"queue": "knowledge.slice"},
        "apps.worker.tasks.embed_knowledge": {"queue": "knowledge.embed"},
        "apps.worker.tasks.ai_recheck": {"queue": "inspection.ai_recheck"},
        "apps.worker.tasks.llm_compare": {"queue": "llm.compare"},
        "apps.worker.tasks.export_package": {"queue": "export.package"},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_retry_delay=10,
    worker_prefetch_multiplier=1,
)
