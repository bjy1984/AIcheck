from __future__ import annotations

import os
from copy import deepcopy

import pytest

from apps.mineru_worker import worker as worker_module
from apps.mineru_worker.queue import ClaimedKnowledgeTask, ClaimedMinerUJob
from apps.worker import tasks
from libs.db.repository import InMemoryRepository
from libs.integrations.mineru_client import MinerUProtocolError
from libs.security.tenant import current_tenant_id
from scripts.migrate_backend import apply_migrations

EXPECTED_FRAGMENTS = [
    {
        "candidateId": "MINERU-CAND-VERIFIED",
        "sourceCandidateIds": ["MINERU-CAND-VERIFIED"],
        "pageNo": 1,
        "text": "施工图审查合格",
        "bbox": [10, 20, 300, 60],
        "coordinateSystem": "rendered_pixels",
        "sourceEngine": "mineru_vlm",
    }
]


def make_job(repository: InMemoryRepository) -> dict:
    return repository.create_ocr_job_record(
        document_id="",
        version_id="",
        storage_key="https://files.example/verified.pdf",
        file_name="verified.pdf",
        provider="mineru",
        source_url="https://files.example/verified.pdf",
        options={},
    )


@pytest.mark.parametrize(("retry_index", "countdown"), [(0, 10), (1, 30), (2, 90)])
def test_postgres_execution_requests_existing_retry_delays(
    monkeypatch: pytest.MonkeyPatch,
    retry_index: int,
    countdown: int,
) -> None:
    repository = InMemoryRepository()
    job = make_job(repository)
    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "refresh_worker_state", lambda *_args: None)
    monkeypatch.setattr(tasks, "flush_state_records", lambda _records: None)
    monkeypatch.setattr(
        tasks,
        "run_mineru_job",
        lambda _job: (_ for _ in ()).throw(
            MinerUProtocolError("MINERU_TIMEOUT", "Timed out.", retryable=True)
        ),
    )

    with pytest.raises(tasks.MinerUPostgresRetry) as raised:
        tasks.execute_mineru_postgres_job(
            job["id"],
            tenant_id="TENANT-DEFAULT",
            retry_index=retry_index,
        )

    assert raised.value.countdown == countdown
    # 本用例钉的是重试延迟，诊断只需确认关键字段（新增可归因字段不该让它红）
    diagnostic = raised.value.diagnostics[0]
    assert diagnostic["code"] == "MINERU_TIMEOUT"
    assert diagnostic["level"] == "error"
    assert diagnostic["retryable"] is True
    assert diagnostic["stage"] == "submit"
    assert job["status"] == "queued"
    assert job["stage"] == "retrying"


def test_postgres_execution_finalizes_after_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryRepository()
    job = make_job(repository)
    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "refresh_worker_state", lambda *_args: None)
    monkeypatch.setattr(tasks, "flush_state_records", lambda _records: None)
    monkeypatch.setattr(
        tasks,
        "run_mineru_job",
        lambda _job: (_ for _ in ()).throw(
            MinerUProtocolError("MINERU_TIMEOUT", "Timed out.", retryable=True)
        ),
    )

    output = tasks.execute_mineru_postgres_job(
        job["id"],
        tenant_id="TENANT-DEFAULT",
        retry_index=3,
    )

    assert output["status"] == "failed"
    assert job["status"] == "failed"


def test_postgres_execution_preserves_verified_ocr_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryRepository()
    job = make_job(repository)
    expected = {
        "parseResultId": "PARSE-MINERU-VERIFIED",
        "status": "success",
        "outcomeStatus": "completed",
        "storageKey": job["storageKey"],
        "fileName": job["fileName"],
        "pages": [{"pageNo": 1}],
        "fragments": deepcopy(EXPECTED_FRAGMENTS),
        "layoutBlocks": [],
        "tables": [],
        "seals": [],
        "signatures": [],
        "fields": [],
        "quality": {"status": "usable", "blockingReasons": []},
        "diagnostics": [],
        "engineRuns": [{"engine": "mineru_vlm", "status": "success"}],
        "metadata": {"provider": "mineru", "model": "vlm"},
    }
    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "refresh_worker_state", lambda *_args: None)
    monkeypatch.setattr(tasks, "flush_state_records", lambda _records: None)
    monkeypatch.setattr(tasks, "run_mineru_job", lambda _job: deepcopy(expected))

    output = tasks.execute_mineru_postgres_job(
        job["id"],
        tenant_id="TENANT-DEFAULT",
        retry_index=0,
    )

    assert output["status"] == "success"
    parse_result = repository.find_one(
        "ocr_parse_results",
        "PARSE-MINERU-VERIFIED",
        id_field="parseResultId",
    )
    assert parse_result["fragments"] == EXPECTED_FRAGMENTS


def test_postgres_execution_indexes_usable_review_incomplete_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryRepository()
    document, version = repository.create_document(
        "PRJ-001",
        "扫描件-postocr.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    job = repository.create_ocr_job_record(
        document_id=document["id"],
        version_id=version["id"],
        storage_key=version["storageKey"],
        file_name=document["fileName"],
        provider="mineru",
        options={},
    )
    pipeline = repository.create_or_resume_ocr_pipeline_run(
        run_key=f"mineru:{version['id']}",
        document_id=document["id"],
        version_id=version["id"],
        storage_key=version["storageKey"],
        storage_bucket=version.get("storageBucket"),
        file_name=document["fileName"],
        profile_id="material_substitution_approval_v1",
        document_type="material_substitution_approval",
        mode="active",
        pipeline_version="mineru-postgres-v1",
        project_id=document["projectId"],
        task_id=None,
    )
    job["pipelineRunId"] = pipeline["id"]
    result = {
        "parseResultId": "PARSE-MINERU-REVIEW-INCOMPLETE",
        "status": "success",
        "outcomeStatus": "partial",
        "storageKey": version["storageKey"],
        "fileName": document["fileName"],
        "documentType": "material_substitution_approval",
        "profileId": "material_substitution_approval_v1",
        "pages": [{"pageNo": 1}],
        "fragments": deepcopy(EXPECTED_FRAGMENTS),
        "layoutBlocks": [],
        "tables": [],
        "seals": [],
        "signatures": [],
        "fields": [],
        "quality": {
            "status": "needs_human_review",
            "reasons": ["REQUIRED_FIELD_MISSING", "SEAL_NOT_FOUND"],
            "blockingReasons": [],
        },
        "diagnostics": [],
        "engineRuns": [{"engine": "mineru_vlm", "status": "success"}],
        "metadata": {"provider": "mineru", "model": "vlm"},
    }
    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "refresh_worker_state", lambda *_args: None)
    monkeypatch.setattr(tasks, "refresh_ocr_worker_state", lambda *_args: None)
    monkeypatch.setattr(tasks, "flush_state_records", lambda _records: None)
    monkeypatch.setattr(tasks, "run_mineru_job", lambda _job: deepcopy(result))
    classification_seen_by_slice: list[str] = []

    def capture_slice(file_id: str, expect_parse_result_id: str | None = None) -> dict:
        knowledge_file = repository.find_one("knowledge_files", file_id)
        classification_seen_by_slice.append(str((knowledge_file or {}).get("materialTypeCode") or ""))
        return {
            "mode": "test",
            "taskId": "slice-test",
            "expectParseResultId": expect_parse_result_id,
        }

    monkeypatch.setattr(tasks.task_dispatcher, "dispatch_slice", capture_slice)

    output = tasks.execute_mineru_postgres_job(
        job["id"],
        tenant_id="TENANT-DEFAULT",
        retry_index=0,
    )

    assert output["status"] == "success"
    assert output["applied"]["reviewOutcomeStatus"] == "partial"
    assert document["currentOcrStatus"] == "已识别"
    assert version["sliceStatus"] == "待切片"
    assert version["vectorStatus"] == "待向量化"
    assert document["materialTypeCode"] == "material_substitution_approval"
    assert classification_seen_by_slice == ["material_substitution_approval"]
    downstream = [
        item
        for item in repository.state["knowledge_tasks"]
        if item.get("documentVersionId") == version["id"]
    ]
    assert {item.get("taskType") for item in downstream} >= {"slice", "vector"}
    stages = {
        item["stage"]: item
        for item in repository.ocr_pipeline_stages(str(job.get("pipelineRunId") or ""))
    }
    for stage_name in ("qwen_extract", "grounding_validate", "finalize"):
        assert stages[stage_name]["status"] == "skipped"
        assert stages[stage_name]["engineStatus"]["skipReasons"] == [
            "review_pipeline_separate"
        ]


def test_worker_finishes_successful_claim_with_tenant_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = ClaimedMinerUJob("TENANT-WORKER", "OCRJOB-WORKER", "lease-1", 0)
    executed: list[tuple[str, str, int]] = []
    finished: list[ClaimedMinerUJob] = []
    heartbeats: list[dict] = []
    monkeypatch.setattr(worker_module, "claim_jobs", lambda *_args, **_kwargs: [claim])
    monkeypatch.setattr(
        worker_module,
        "execute_mineru_postgres_job",
        lambda job_id, *, tenant_id, retry_index: executed.append((job_id, tenant_id, retry_index))
        or {"status": "success"},
    )
    monkeypatch.setattr(
        worker_module,
        "finish_claim",
        lambda _dsn, current: finished.append(current) or True,
    )
    monkeypatch.setattr(worker_module, "reschedule_claim", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        worker_module,
        "write_heartbeat",
        lambda _dsn, _worker_id, payload: heartbeats.append(payload),
    )

    worker = worker_module.MinerUPostgresWorker("postgresql:///unused", worker_id="worker-a")

    assert worker.run_once() == 1
    assert executed == [("OCRJOB-WORKER", "TENANT-WORKER", 0)]
    assert finished == [claim]
    assert heartbeats[-1]["activeCount"] == 0
    assert heartbeats[-1]["lastError"] is None


def test_worker_reschedules_retry_and_handles_empty_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = ClaimedMinerUJob("TENANT-WORKER", "OCRJOB-RETRY", "lease-2", 1)
    claims = [[claim], []]
    rescheduled: list[tuple[ClaimedMinerUJob, list[dict], int]] = []
    monkeypatch.setattr(worker_module, "claim_jobs", lambda *_args, **_kwargs: claims.pop(0))
    monkeypatch.setattr(
        worker_module,
        "execute_mineru_postgres_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            tasks.MinerUPostgresRetry(
                countdown=30,
                diagnostics=[{"code": "MINERU_TIMEOUT", "retryable": True}],
            )
        ),
    )
    monkeypatch.setattr(worker_module, "finish_claim", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(worker_module, "claim_knowledge_tasks", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        worker_module,
        "reschedule_claim",
        lambda _dsn, current, *, diagnostics, delay_seconds: rescheduled.append(
            (current, diagnostics, delay_seconds)
        )
        or True,
    )
    monkeypatch.setattr(worker_module, "write_heartbeat", lambda *_args, **_kwargs: None)
    worker = worker_module.MinerUPostgresWorker("postgresql:///unused", worker_id="worker-a")

    assert worker.run_once() == 1
    assert rescheduled == [
        (claim, [{"code": "MINERU_TIMEOUT", "retryable": True}], 30)
    ]
    assert worker.run_once() == 0


def test_postgres_knowledge_execution_uses_local_task_bodies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        tasks.slice_knowledge,
        "run",
        lambda file_id, dispatch_next=True: calls.append(
            ("slice", file_id, dispatch_next)
        )
        or {"status": "success"},
    )
    monkeypatch.setattr(
        tasks.embed_knowledge,
        "run",
        lambda file_id, offset=0, allow_celery_continuation=True: calls.append(
            ("vector", file_id, offset, allow_celery_continuation)
        )
        or {"status": "success"},
    )

    assert tasks.execute_postgres_knowledge_task(
        "slice", "KF-LOCAL", tenant_id="TENANT-LOCAL"
    )["status"] == "success"
    assert tasks.execute_postgres_knowledge_task(
        "vector", "KF-LOCAL", tenant_id="TENANT-LOCAL"
    )["status"] == "success"
    assert calls == [
        ("slice", "KF-LOCAL", False),
        ("vector", "KF-LOCAL", 0, False),
    ]


def test_worker_processes_postgres_knowledge_claim_without_celery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = ClaimedKnowledgeTask(
        "TENANT-WORKER",
        "KT-SLICE",
        "slice",
        "KF-1",
        "knowledge-lease",
        0,
    )
    executed: list[tuple[str, str, str]] = []
    finished: list[ClaimedKnowledgeTask] = []
    monkeypatch.setattr(worker_module, "claim_jobs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        worker_module,
        "claim_knowledge_tasks",
        lambda *_args, **_kwargs: [claim],
    )
    monkeypatch.setattr(
        worker_module,
        "execute_postgres_knowledge_task",
        lambda task_type, target_id, *, tenant_id: executed.append(
            (task_type, target_id, tenant_id)
        )
        or {"status": "success"},
    )
    monkeypatch.setattr(
        worker_module,
        "finish_knowledge_claim",
        lambda _dsn, current: finished.append(current) or True,
    )
    monkeypatch.setattr(worker_module, "write_heartbeat", lambda *_args, **_kwargs: None)

    worker = worker_module.MinerUPostgresWorker("postgresql:///unused", worker_id="worker-a")

    assert worker.run_once() == 1
    assert executed == [("slice", "KF-1", "TENANT-WORKER")]
    assert finished == [claim]


def test_worker_reschedules_failed_knowledge_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = ClaimedKnowledgeTask(
        "TENANT-WORKER",
        "KT-VECTOR",
        "vector",
        "KF-1",
        "knowledge-lease",
        1,
    )
    rescheduled: list[tuple[ClaimedKnowledgeTask, str, int]] = []
    monkeypatch.setattr(worker_module, "claim_jobs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        worker_module,
        "claim_knowledge_tasks",
        lambda *_args, **_kwargs: [claim],
    )
    monkeypatch.setattr(
        worker_module,
        "execute_postgres_knowledge_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("temporary")),
    )
    monkeypatch.setattr(
        worker_module,
        "reschedule_knowledge_claim",
        lambda _dsn, current, *, error_message, delay_seconds: rescheduled.append(
            (current, error_message, delay_seconds)
        )
        or True,
    )
    monkeypatch.setattr(worker_module, "write_heartbeat", lambda *_args, **_kwargs: None)

    worker = worker_module.MinerUPostgresWorker("postgresql:///unused", worker_id="worker-a")

    assert worker.run_once() == 1
    assert rescheduled == [(claim, "RuntimeError", 30)]


@pytest.mark.skipif(
    not os.getenv("AICHECK_TEST_POSTGRES_URL"),
    reason="AICHECK_TEST_POSTGRES_URL is required for PostgreSQL worker integration tests",
)
def test_real_postgres_worker_persists_verified_result(
    monkeypatch: pytest.MonkeyPatch,
    isolated_postgres_url: str,
) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    apply_migrations(isolated_postgres_url)
    seed_repository = InMemoryRepository()
    job = make_job(seed_repository)
    job["tenantId"] = "TENANT-MINERU-E2E"
    expected = {
        "parseResultId": "PARSE-MINERU-E2E",
        "status": "success",
        "outcomeStatus": "completed",
        "storageKey": job["storageKey"],
        "fileName": job["fileName"],
        "pages": [{"pageNo": 1}],
        "fragments": deepcopy(EXPECTED_FRAGMENTS),
        "layoutBlocks": [],
        "tables": [],
        "seals": [],
        "signatures": [],
        "fields": [],
        "quality": {"status": "usable", "blockingReasons": []},
        "diagnostics": [],
        "engineRuns": [{"engine": "mineru_vlm", "status": "success"}],
        "metadata": {"provider": "mineru", "model": "vlm"},
    }
    with psycopg.connect(isolated_postgres_url, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO aicheck_state (tenant_id, collection, object_id, payload)
            VALUES (%s, 'ocr_jobs', %s, %s)
            """,
            (job["tenantId"], job["id"], Jsonb(job)),
        )
    tasks.repo.close_sync_postgres()
    tasks.repo.postgres_dsn = None
    tasks.repo.postgres_enabled = False
    monkeypatch.setenv("AICHECK_DATABASE_URL", isolated_postgres_url)
    monkeypatch.setattr(tasks, "run_mineru_job", lambda _job: deepcopy(expected))
    try:
        worker = worker_module.MinerUPostgresWorker(
            isolated_postgres_url,
            worker_id="worker-e2e",
        )
        assert worker.run_once() == 1
        with psycopg.connect(isolated_postgres_url) as connection:
            job_payload = dict(
                connection.execute(
                    """
                    SELECT payload FROM aicheck_state
                    WHERE tenant_id = %s AND collection = 'ocr_jobs' AND object_id = %s
                    """,
                    (job["tenantId"], job["id"]),
                ).fetchone()[0]
            )
            parse_payload = dict(
                connection.execute(
                    """
                    SELECT payload FROM aicheck_state
                    WHERE tenant_id = %s AND collection = 'ocr_parse_results' AND object_id = %s
                    """,
                    (job["tenantId"], expected["parseResultId"]),
                ).fetchone()[0]
            )
        assert job_payload["status"] == "success"
        assert "leaseToken" not in job_payload
        assert parse_payload["fragments"] == EXPECTED_FRAGMENTS
    finally:
        tasks.repo.close_sync_postgres()
        tasks.repo.postgres_dsn = None
        tasks.repo.postgres_enabled = False


@pytest.mark.skipif(
    not os.getenv("AICHECK_TEST_POSTGRES_URL"),
    reason="AICHECK_TEST_POSTGRES_URL is required for PostgreSQL read-view tests",
)
def test_project_document_read_view_uses_latest_postgres_without_mutating_api_state(
    isolated_postgres_url: str,
) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    apply_migrations(isolated_postgres_url)
    tenant_id = current_tenant_id()
    project_id = "P-FRESH-READ"
    records = [
        (
            "documents",
            "DOC-FRESH",
            {
                "id": "DOC-FRESH",
                "projectId": project_id,
                "currentVersionId": "VER-FRESH",
                "fileName": "fresh.pdf",
                "currentOcrStatus": "已识别",
            },
        ),
        (
            "document_versions",
            "VER-FRESH",
            {"id": "VER-FRESH", "documentId": "DOC-FRESH", "isCurrent": True},
        ),
        (
            "knowledge_files",
            "KF-FRESH",
            {
                "id": "KF-FRESH",
                "projectId": project_id,
                "documentId": "DOC-FRESH",
                "documentVersionId": "VER-FRESH",
                "sliceStatus": "已切片",
                "vectorStatus": "待向量化",
                "chunkCount": 4,
            },
        ),
        (
            "node_bindings",
            "BIND-FRESH",
            {
                "id": "BIND-FRESH",
                "projectId": project_id,
                "nodeId": 16,
                "documentId": "DOC-FRESH",
                "documentVersionId": "VER-FRESH",
            },
        ),
    ]
    with psycopg.connect(isolated_postgres_url, autocommit=True) as connection:
        for collection, object_id, payload in records:
            connection.execute(
                """
                INSERT INTO aicheck_state (tenant_id, collection, object_id, payload)
                VALUES (%s, %s, %s, %s)
                """,
                (tenant_id, collection, object_id, Jsonb(payload)),
            )

    repository = InMemoryRepository()
    repository.state["documents"] = []
    repository.configure_sync_postgres(isolated_postgres_url)

    view = repository.project_document_read_view(project_id)

    assert repository.state["documents"] == []
    assert view is not repository
    documents = view.project_documents(project_id)
    assert len(documents) == 1
    assert documents[0]["id"] == "DOC-FRESH"
    assert documents[0]["sliceStatus"] == "已切片"
    assert documents[0]["vectorStatus"] == "待向量化"
    assert documents[0]["chunkCount"] == 4
    assert view.bindings_for_project(project_id)[0]["id"] == "BIND-FRESH"
