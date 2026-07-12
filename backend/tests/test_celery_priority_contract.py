from __future__ import annotations

from apps.worker.celery_app import celery_app


def _route(task_name: str) -> dict:
    return dict(celery_app.conf.task_routes[task_name])


def test_redis_priority_steps_run_larger_numbers_first() -> None:
    steps = list(celery_app.conf.broker_transport_options["priority_steps"])

    assert steps == list(range(10, -1, -1))
    assert steps[0] == celery_app.conf.task_queue_max_priority
    assert steps[-1] == 0


def test_ocr_follow_up_stages_precede_new_documents_and_embedding() -> None:
    parse_priority = _route("apps.worker.tasks.parse_document")["priority"]
    structure_priority = _route("apps.worker.tasks.ocr_pipeline_structure_scan")["priority"]
    seal_priority = _route("apps.worker.tasks.ocr_pipeline_seal_scan")["priority"]
    embedding_priority = _route("apps.worker.tasks.embed_knowledge")["priority"]

    assert structure_priority > parse_priority > embedding_priority
    assert seal_priority > parse_priority > embedding_priority


def test_ai_recheck_priority_is_represented_by_redis_steps() -> None:
    priority = _route("apps.worker.tasks.ai_recheck")["priority"]

    assert priority in celery_app.conf.broker_transport_options["priority_steps"]
