from __future__ import annotations

from copy import deepcopy
import os

import pytest

from apps.mineru_worker import worker as worker_module
from apps.mineru_worker.queue import ClaimedMinerUJob
from apps.worker import tasks
from libs.db.repository import InMemoryRepository
from libs.integrations.mineru_client import MinerUProtocolError
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
    assert raised.value.diagnostics == [
        {
            "code": "MINERU_TIMEOUT",
            "level": "error",
            "retryable": True,
            "stage": "submit",
        }
    ]
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
