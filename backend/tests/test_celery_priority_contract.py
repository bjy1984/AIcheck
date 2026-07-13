from __future__ import annotations

import pytest

from apps.worker.celery_app import celery_app
from libs.task_priority import MAX_TASK_PRIORITY, broker_priority


def _route(task_name: str) -> dict:
    return dict(celery_app.conf.task_routes[task_name])


def test_redis_priority_steps_remain_sorted_for_kombu_bisect() -> None:
    steps = list(celery_app.conf.broker_transport_options["priority_steps"])
    assert steps == list(range(MAX_TASK_PRIORITY + 1))
    assert steps[0] == 0
    assert steps[-1] == celery_app.conf.task_queue_max_priority


def test_ocr_follow_up_stages_precede_new_documents_and_embedding() -> None:
    parse_priority = _route("apps.worker.tasks.parse_document")["priority"]
    structure_priority = _route("apps.worker.tasks.ocr_pipeline_structure_scan")["priority"]
    seal_priority = _route("apps.worker.tasks.ocr_pipeline_seal_scan")["priority"]
    embedding_priority = _route("apps.worker.tasks.embed_knowledge")["priority"]
    assert structure_priority < parse_priority < embedding_priority
    assert seal_priority < parse_priority < embedding_priority
    assert parse_priority == broker_priority(7)


def test_celery_long_tasks_have_bounded_runtime_and_safe_visibility_timeout() -> None:
    assert celery_app.conf.task_soft_time_limit > 0
    assert celery_app.conf.task_time_limit > celery_app.conf.task_soft_time_limit
    assert celery_app.conf.broker_transport_options["visibility_timeout"] > celery_app.conf.task_time_limit
    assert celery_app.conf.worker_max_tasks_per_child > 0
    assert celery_app.conf.worker_max_memory_per_child > 0
    assert celery_app.conf.result_expires > 0


def test_ai_recheck_priority_is_represented_by_redis_steps() -> None:
    priority = _route("apps.worker.tasks.ai_recheck")["priority"]
    assert priority == broker_priority(10) == 0
    assert priority in celery_app.conf.broker_transport_options["priority_steps"]


@pytest.mark.parametrize("value", [-1, MAX_TASK_PRIORITY + 1])
def test_broker_priority_rejects_out_of_range_values(value: int) -> None:
    with pytest.raises(ValueError):
        broker_priority(value)


@pytest.mark.parametrize(
    ("dispatcher_name", "task_name", "args", "semantic_priority"),
    [
        ("dispatch_parse_document", "parse_document", ("DOC-1", "DV-1", "minio://documents/a.pdf", "a.pdf"), 7),
        ("dispatch_slice", "slice_knowledge", ("KF-1",), 2),
        ("dispatch_embed", "embed_knowledge", ("KF-1",), 1),
    ],
)
def test_dispatchers_map_semantic_priority_only_at_broker_boundary(
    monkeypatch,
    dispatcher_name: str,
    task_name: str,
    args: tuple,
    semantic_priority: int,
) -> None:
    from apps.worker import tasks
    from libs.integrations import task_dispatcher

    captured = {}

    class Result:
        id = "TASK-1"

    def fake_apply_async(*, args, queue, priority, **kwargs):
        captured.update(args=args, queue=queue, priority=priority, kwargs=kwargs)
        return Result()

    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "celery")
    monkeypatch.setattr(task_dispatcher, "cpu_heavy_dispatch_blocker", lambda _mode: None)
    monkeypatch.setattr(getattr(tasks, task_name), "apply_async", fake_apply_async)

    response = getattr(task_dispatcher, dispatcher_name)(*args)

    assert captured["priority"] == broker_priority(semantic_priority)
    assert response["priority"] == semantic_priority
