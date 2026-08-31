from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from apps.worker import tasks
from libs.db.repository import InMemoryRepository
from libs.db.seed import PROJECT_ID
from libs.integrations import task_dispatcher
from libs.security.tenant import current_tenant_id, reset_request_tenant_id, set_request_tenant_id


def _repository_with_ocr() -> tuple[InMemoryRepository, dict, dict]:
    repository = InMemoryRepository()
    document, version = repository.create_document(
        PROJECT_ID,
        "扫描件001.pdf",
        "application/pdf",
    )
    result = {
        "parseResultId": "PARSE-LLM-CLASSIFY-1",
        "status": "success",
        "fragments": [
            {
                "pageNo": 1,
                "text": "特种设备设计许可证 许可项目：压力管道设计",
                "bbox": [10, 10, 500, 80],
                "confidence": 0.96,
            }
        ],
        "fields": [],
        "tables": [],
        "seals": [],
    }
    job = repository.create_ocr_job_record(
        document_id=document["id"],
        version_id=version["id"],
        storage_key=version["storageKey"],
        file_name=document["fileName"],
    )
    repository.finish_ocr_job_record(job, result)
    repository.apply_ocr_result(document["id"], version["id"], result)
    return repository, document, version


class SuccessfulClient:
    def chat_sync(self, *_args, **_kwargs) -> dict:
        return {
            "id": "chatcmpl-worker-1",
            "model": "qwen3.8-max",
            "provider": "Model Studio / DashScope",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "materialTypeCode": "design_license",
                                "confidence": 0.96,
                                "reason": "正文明确为设计许可证",
                                "contentEvidence": ["许可项目：压力管道设计"],
                            },
                            ensure_ascii=False,
                        )
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        }


class FailingClient:
    def chat_sync(self, *_args, **_kwargs) -> dict:
        raise RuntimeError("classification service unavailable")


def test_worker_applies_llm_classification_then_runs_existing_targeting_once(monkeypatch) -> None:
    repository, document, version = _repository_with_ocr()
    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "refresh_ocr_worker_state", lambda *_args: None)
    monkeypatch.setattr(tasks, "flush_state_records", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "qwen_runtime_client", lambda: SuccessfulClient())

    result = tasks.classify_document_material.run(
        PROJECT_ID,
        document["id"],
        version["id"],
    )

    assert result["status"] == "completed"
    assert result["classification"]["materialTypeCode"] == "design_license"
    assert result["classification"]["classificationSource"] == "llm_classifier"
    assert document["classificationSource"] == "llm_classifier"
    runs = [
        item
        for item in repository.state["material_targeting_runs"]
        if item.get("documentVersionId") == version["id"]
    ]
    assert len(runs) == 1
    attempts = [
        item
        for item in repository.state["model_call_attempts"]
        if item.get("documentVersionId") == version["id"]
        and item.get("callKind") == "document_material_classification"
    ]
    assert len(attempts) == 1
    assert attempts[0]["status"] == "success"


def test_worker_final_failure_uses_rule_classifier_without_blocking_targeting(monkeypatch) -> None:
    repository, document, version = _repository_with_ocr()
    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "refresh_ocr_worker_state", lambda *_args: None)
    monkeypatch.setattr(tasks, "flush_state_records", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "qwen_runtime_client", lambda: FailingClient())

    result = tasks.classify_document_material.run(
        PROJECT_ID,
        document["id"],
        version["id"],
    )

    assert result["status"] == "completed"
    assert result["classification"]["materialTypeCode"] == "design_license"
    assert result["classification"]["classificationSource"] == "ocr_classifier"
    assert result["classificationFallback"] == {"used": True, "reason": "RuntimeError"}
    runs = [
        item
        for item in repository.state["material_targeting_runs"]
        if item.get("documentVersionId") == version["id"]
    ]
    assert len(runs) == 1
    attempts = [
        item
        for item in repository.state["model_call_attempts"]
        if item.get("documentVersionId") == version["id"]
        and item.get("callKind") == "document_material_classification"
    ]
    assert len(attempts) == 1
    assert attempts[0]["status"] == "failed"


def test_worker_rechecks_current_version_after_model_returns(monkeypatch) -> None:
    repository, document, version = _repository_with_ocr()
    monkeypatch.setattr(tasks, "repo", repository)
    refresh_count = 0

    def refresh_then_advance_version(*_args) -> None:
        nonlocal refresh_count
        refresh_count += 1
        if refresh_count == 2:
            document["currentVersionId"] = "DV-NEWER-V2"

    monkeypatch.setattr(tasks, "refresh_ocr_worker_state", refresh_then_advance_version)
    monkeypatch.setattr(tasks, "flush_state_records", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "qwen_runtime_client", lambda: SuccessfulClient())

    result = tasks.classify_document_material.run(
        PROJECT_ID,
        document["id"],
        version["id"],
    )

    assert refresh_count == 2
    assert result["status"] == "stale_version"
    assert document.get("classificationSource") != "llm_classifier"
    assert repository.state["material_targeting_runs"] == []


def test_worker_rechecks_current_version_before_rule_fallback(monkeypatch) -> None:
    repository, document, version = _repository_with_ocr()
    monkeypatch.setattr(tasks, "repo", repository)
    refresh_count = 0

    def refresh_then_advance_version(*_args) -> None:
        nonlocal refresh_count
        refresh_count += 1
        if refresh_count == 2:
            document["currentVersionId"] = "DV-NEWER-V2"

    monkeypatch.setattr(tasks, "refresh_ocr_worker_state", refresh_then_advance_version)
    monkeypatch.setattr(tasks, "flush_state_records", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "qwen_runtime_client", lambda: FailingClient())

    result = tasks.classify_document_material.run(
        PROJECT_ID,
        document["id"],
        version["id"],
    )

    assert refresh_count == 2
    assert result["status"] == "stale_version"
    assert document.get("classificationSource") != "ocr_classifier"
    assert repository.state["material_targeting_runs"] == []


def test_completed_classification_redelivery_does_not_call_model_or_target_again(monkeypatch) -> None:
    repository, document, version = _repository_with_ocr()
    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "refresh_ocr_worker_state", lambda *_args: None)
    monkeypatch.setattr(tasks, "flush_state_records", lambda *_args, **_kwargs: None)
    client = SuccessfulClient()
    call_count = 0
    original_chat_sync = client.chat_sync

    def count_chat_sync(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_chat_sync(*args, **kwargs)

    client.chat_sync = count_chat_sync
    monkeypatch.setattr(tasks, "qwen_runtime_client", lambda: client)

    first = tasks.classify_document_material.run(
        PROJECT_ID,
        document["id"],
        version["id"],
    )
    second = tasks.classify_document_material.run(
        PROJECT_ID,
        document["id"],
        version["id"],
    )

    assert first["status"] == "completed"
    assert second["status"] == "completed"
    assert second["alreadyCompleted"] is True
    assert call_count == 1
    runs = [
        item
        for item in repository.state["material_targeting_runs"]
        if item.get("documentVersionId") == version["id"]
    ]
    assert len(runs) == 1


def test_reapplied_ocr_does_not_requeue_completed_classification(monkeypatch) -> None:
    repository, document, version = _repository_with_ocr()
    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "refresh_ocr_worker_state", lambda *_args: None)
    monkeypatch.setattr(tasks, "flush_state_records", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "qwen_runtime_client", lambda: SuccessfulClient())
    first = tasks.classify_document_material.run(
        PROJECT_ID,
        document["id"],
        version["id"],
    )
    monkeypatch.setattr(
        tasks.task_dispatcher,
        "dispatch_document_classification",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("completed document version must not be requeued")
        ),
    )

    second = tasks.queue_document_classification_after_ocr(
        PROJECT_ID,
        document["id"],
        version["id"],
    )

    assert first["status"] == "completed"
    assert second["alreadyCompleted"] is True
    assert len(repository.state["material_targeting_runs"]) == 1


def test_uncertain_success_persistence_retries_commit_without_rerunning_targeting(monkeypatch) -> None:
    repository, document, version = _repository_with_ocr()
    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "refresh_ocr_worker_state", lambda *_args: None)
    client = SuccessfulClient()
    call_count = 0
    original_chat_sync = client.chat_sync

    def count_chat_sync(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_chat_sync(*args, **kwargs)

    client.chat_sync = count_chat_sync
    monkeypatch.setattr(tasks, "qwen_runtime_client", lambda: client)
    persist_count = 0

    def fail_first_persistence(_records) -> None:
        nonlocal persist_count
        persist_count += 1
        if persist_count == 1:
            raise RuntimeError("database response lost")

    monkeypatch.setattr(tasks, "flush_state_records", fail_first_persistence)

    with pytest.raises(RuntimeError, match="database response lost"):
        tasks.classify_document_material.run(
            PROJECT_ID,
            document["id"],
            version["id"],
        )
    second = tasks.classify_document_material.run(
        PROJECT_ID,
        document["id"],
        version["id"],
    )

    assert second["alreadyCompleted"] is True
    assert call_count == 1
    runs = [
        item
        for item in repository.state["material_targeting_runs"]
        if item.get("documentVersionId") == version["id"]
    ]
    assert len(runs) == 1


def test_worker_establishes_and_restores_dispatched_tenant_context(monkeypatch) -> None:
    repository, document, version = _repository_with_ocr()
    repository._tenant_states["TENANT-CLASSIFY-A"] = repository.state
    monkeypatch.setattr(tasks, "repo", repository)
    seen_tenants: list[str] = []
    monkeypatch.setattr(
        tasks,
        "refresh_ocr_worker_state",
        lambda *_args: seen_tenants.append(current_tenant_id()),
    )
    monkeypatch.setattr(tasks, "flush_state_records", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "qwen_runtime_client", lambda: SuccessfulClient())
    before = current_tenant_id()

    result = tasks.classify_document_material.run(
        PROJECT_ID,
        document["id"],
        version["id"],
        "TENANT-CLASSIFY-A",
    )

    assert result["status"] == "completed"
    assert seen_tenants == ["TENANT-CLASSIFY-A", "TENANT-CLASSIFY-A"]
    assert current_tenant_id() == before


def test_classification_dispatch_carries_tenant_and_uses_tenant_scoped_task_id(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "celery")
    monkeypatch.setattr(
        tasks.classify_document_material,
        "apply_async",
        lambda **kwargs: calls.append(kwargs) or SimpleNamespace(id="TASK-TENANT-1"),
    )
    token = set_request_tenant_id("TENANT-CLASSIFY-A")
    try:
        result = task_dispatcher.dispatch_document_classification(
            PROJECT_ID,
            "DOC-TENANT-1",
            "DV-TENANT-1",
        )
    finally:
        reset_request_tenant_id(token)

    assert result["taskId"] == "TASK-TENANT-1"
    assert calls[0]["args"] == [
        PROJECT_ID,
        "DOC-TENANT-1",
        "DV-TENANT-1",
        "TENANT-CLASSIFY-A",
    ]
    first_task_id = calls[0]["task_id"]
    token = set_request_tenant_id("TENANT-CLASSIFY-B")
    try:
        task_dispatcher.dispatch_document_classification(
            PROJECT_ID,
            "DOC-TENANT-1",
            "DV-TENANT-1",
        )
    finally:
        reset_request_tenant_id(token)
    assert calls[1]["args"][-1] == "TENANT-CLASSIFY-B"
    assert calls[1]["task_id"] != first_task_id


def test_inline_dispatch_does_not_run_remote_model_inside_ocr_worker(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "inline")
    monkeypatch.setattr(
        tasks.classify_document_material,
        "run",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("inline OCR path must not call the remote classifier")
        ),
    )

    result = task_dispatcher.dispatch_document_classification(
        PROJECT_ID,
        "DOC-INLINE-1",
        "DV-INLINE-1",
    )

    assert result == {
        "mode": "inline",
        "taskId": None,
        "statusReason": "document_classification_requires_async_dispatch",
    }


def test_persistence_retry_budget_extends_beyond_model_retry_budget() -> None:
    class RetryRequested(RuntimeError):
        pass

    retry_calls: list[dict] = []
    fake_task = SimpleNamespace(
        request=SimpleNamespace(retries=2, called_directly=False),
        retry=lambda **kwargs: retry_calls.append(kwargs) or RetryRequested("retry"),
    )

    with pytest.raises(RetryRequested, match="retry"):
        tasks._retry_persistence_or_raise(fake_task, RuntimeError("commit uncertain"))

    assert retry_calls[0]["max_retries"] == 4


def test_queued_dispatch_does_not_run_rule_targeting_first(monkeypatch) -> None:
    repository, document, version = _repository_with_ocr()
    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(
        tasks.task_dispatcher,
        "dispatch_document_classification",
        lambda *_args: {
            "mode": "celery",
            "taskId": "task-classify-1",
            "queue": "llm.remote",
        },
    )

    result = tasks.queue_document_classification_after_ocr(
        PROJECT_ID,
        document["id"],
        version["id"],
    )

    knowledge_file = repository.knowledge_file_for_version(version["id"])
    assert result["status"] == "classification_queued"
    assert result["targeting"]["status"] == "awaiting_llm_classification"
    assert document["classificationStatus"] == "queued"
    assert knowledge_file is not None
    assert knowledge_file["classificationStatus"] == "queued"
    assert repository.state["material_targeting_runs"] == []


def test_pending_classification_is_persisted_before_worker_dispatch(monkeypatch) -> None:
    repository, document, version = _repository_with_ocr()
    monkeypatch.setattr(tasks, "repo", repository)
    events: list[str] = []
    monkeypatch.setattr(
        tasks,
        "flush_state_records",
        lambda records: events.append(
            "persist:" + str(records["documents"][0].get("classificationStatus"))
        ),
    )
    monkeypatch.setattr(
        tasks.task_dispatcher,
        "dispatch_document_classification",
        lambda *_args: events.append("dispatch")
        or {"mode": "celery", "taskId": "task-classify-1", "queue": "llm.remote"},
    )

    tasks.queue_document_classification_after_ocr(
        PROJECT_ID,
        document["id"],
        version["id"],
    )

    assert events[:2] == ["persist:queued", "dispatch"]


def test_pending_classification_persistence_failure_does_not_dispatch_or_raise(monkeypatch) -> None:
    repository, document, version = _repository_with_ocr()
    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(
        tasks,
        "flush_state_records",
        lambda _records: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )
    monkeypatch.setattr(
        tasks.task_dispatcher,
        "dispatch_document_classification",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("unpersisted classification must not be dispatched")
        ),
    )

    result = tasks.queue_document_classification_after_ocr(
        PROJECT_ID,
        document["id"],
        version["id"],
    )

    assert result["status"] == "classification_deferred"
    assert result["reason"] == "classification_state_persistence_runtimeerror"
    assert result["targeting"]["status"] == "awaiting_classification_retry"


def test_ocr_boundary_contains_unexpected_classification_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks,
        "queue_document_classification_after_ocr",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("unexpected classifier bug")),
    )

    result = tasks.safe_queue_document_classification_after_ocr(
        PROJECT_ID,
        "DOC-SAFE-1",
        "DV-SAFE-1",
    )

    assert result["status"] == "classification_deferred"
    assert result["reason"] == "classification_boundary_runtimeerror"
    assert result["targeting"]["status"] == "awaiting_classification_retry"


def test_unavailable_dispatch_falls_back_to_existing_rule_classifier(monkeypatch) -> None:
    repository, document, version = _repository_with_ocr()
    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(
        tasks.task_dispatcher,
        "dispatch_document_classification",
        lambda *_args: {
            "mode": "disabled",
            "taskId": None,
            "statusReason": "document_classification_requires_task_dispatch",
        },
    )

    result = tasks.queue_document_classification_after_ocr(
        PROJECT_ID,
        document["id"],
        version["id"],
    )

    assert result["status"] == "completed"
    assert result["classification"]["classificationSource"] == "ocr_classifier"
    runs = [
        item
        for item in repository.state["material_targeting_runs"]
        if item.get("documentVersionId") == version["id"]
    ]
    assert len(runs) == 1
