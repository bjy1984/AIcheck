# PostgreSQL-backed MinerU Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make verified uploads return success without Redis by persisting MinerU OCR jobs in PostgreSQL and processing them in an independent lightweight worker while preserving the existing validated OCR payload contract.

**Architecture:** The API synchronously performs only the existing bounded OCR-job preparation and records `ocr_jobs.status=queued`; it never contacts MinerU. A standalone worker leases those jobs from `aicheck_state` with PostgreSQL row locking, then invokes the existing MinerU client, checkpoint, normalization, artifact, and result-application chain.

**Tech Stack:** Python 3.12, FastAPI, psycopg/PostgreSQL JSONB state store, pytest, existing MinerU HTTP client and normalization code.

## Global Constraints

- MinerU request options and normalized OCR result fields must remain compatible with the existing validated tests and fixtures.
- No Redis or Celery call may occur on the MinerU upload-complete path.
- PostgreSQL is mandatory for `AICHECK_MINERU_EXECUTION_MODE=postgres`; SQLite is not a queue fallback.
- Non-MinerU Celery workloads remain unchanged.
- Preserve unrelated dirty-worktree changes.

---

### Task 1: PostgreSQL MinerU dispatch contract

**Files:**
- Modify: `backend/libs/integrations/task_dispatcher.py`
- Modify: `backend/apps/worker/tasks.py`
- Modify: `backend/apps/api/mineru_ocr_routes.py`
- Test: `backend/tests/test_mineru_worker.py`
- Test: `backend/tests/test_mineru_api.py`

**Interfaces:**
- Produces: `mineru_execution_mode() -> str` and PostgreSQL dispatch payload `{mode: "postgres", jobId: str, statusReason: "mineru_job_persisted"}`.
- Preserves: existing `dispatch_mineru_ocr(job_record_id)` inline and Celery modes when explicitly configured.

- [ ] **Step 1: Write failing dispatch tests**

Add tests proving `AICHECK_MINERU_EXECUTION_MODE=postgres` returns an accepted PostgreSQL dispatch without calling `apply_async`, and API job creation does not mark a PostgreSQL-dispatched job failed.

```python
def test_dispatch_mineru_ocr_persists_for_postgres_worker(monkeypatch):
    monkeypatch.setenv("AICHECK_MINERU_EXECUTION_MODE", "postgres")
    monkeypatch.setattr(tasks.mineru_ocr_extract, "apply_async", lambda **_: pytest.fail("Celery called"))
    assert task_dispatcher.dispatch_mineru_ocr("OCRJOB-1") == {
        "mode": "postgres",
        "jobId": "OCRJOB-1",
        "statusReason": "mineru_job_persisted",
    }
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/test_mineru_worker.py::test_dispatch_mineru_ocr_persists_for_postgres_worker tests/test_mineru_api.py::test_postgres_dispatch_is_accepted -q`

Expected: FAIL because PostgreSQL MinerU dispatch is not implemented.

- [ ] **Step 3: Remove the Redis inline fallback and implement the dispatch mode**

Delete the current exception-driven environment mutation in `dispatch_parse_document`. Add an independent MinerU execution-mode resolver and return a PostgreSQL acceptance descriptor from `dispatch_mineru_ocr`. Update MinerU callers so `mode=postgres` is accepted without a Celery task ID.

```python
def mineru_execution_mode() -> str:
    return os.getenv("AICHECK_MINERU_EXECUTION_MODE", "celery").strip().lower() or "celery"

if mineru_execution_mode() == "postgres":
    return {"mode": "postgres", "jobId": job_record_id, "statusReason": "mineru_job_persisted"}
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command and `cd backend && .venv/bin/python -m pytest tests/test_mineru_worker.py tests/test_mineru_api.py -q`.

- [ ] **Step 5: Commit**

Commit only Task 1 files with message `feat: add postgres MinerU dispatch mode`.

### Task 2: Upload completion persists MinerU work without Redis

**Files:**
- Modify: `backend/libs/integrations/task_dispatcher.py`
- Modify: `backend/apps/api/routes.py`
- Test: `backend/tests/test_contract.py`

**Interfaces:**
- Produces: `dispatch_parse_document(...)` result with `mode=postgres` after bounded `parse_document.run(...)` preparation for MinerU.
- Consumes: `resolve_ocr_provider` and the PostgreSQL `dispatch_mineru_ocr` contract from Task 1.

- [ ] **Step 1: Write a failing upload regression test**

Add a contractor upload test that configures MinerU PostgreSQL execution, makes Celery `apply_async` raise if called, completes the upload, asserts HTTP success, and verifies exactly one queued MinerU `ocr_jobs` record bound to the uploaded document/version.

```python
monkeypatch.setenv("AICHECK_MINERU_EXECUTION_MODE", "postgres")
monkeypatch.setattr(tasks.parse_document, "apply_async", lambda **_: pytest.fail("Celery called"))
completed = assert_ok(client.post(complete_url, json=complete_body, headers=contractor_headers))
jobs = [job for job in repo.state["ocr_jobs"] if job.get("documentVersionId") == version_id]
assert completed["fileCount"] == 1
assert [(job["provider"], job["status"]) for job in jobs] == [("mineru", "queued")]
```

- [ ] **Step 2: Run the regression and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contract.py::test_mineru_upload_complete_persists_job_without_redis -q`

Expected: FAIL because completion still enters Celery dispatch.

- [ ] **Step 3: Implement bounded MinerU job preparation**

When the resolved provider is MinerU and execution mode is PostgreSQL, execute only the existing preparation path synchronously. Treat the resulting persisted job as queued; do not call MinerU, Redis, or Celery. Leave other provider paths unchanged.

```python
if requested_provider == "mineru" and mineru_execution_mode() == "postgres":
    result = parse_document.run(document_id, version_id, storage_key, file_name)
    return {"mode": "postgres", "result": result, "statusReason": "mineru_job_persisted"}
```

- [ ] **Step 4: Verify GREEN and adjacent upload contracts**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contract.py -q -k 'upload_session or contractor_default_project_upload'`.

- [ ] **Step 5: Commit**

Commit Task 2 files with message `fix: decouple MinerU upload completion from Redis`.

### Task 3: PostgreSQL lease queue

**Files:**
- Create: `backend/apps/mineru_worker/__init__.py`
- Create: `backend/apps/mineru_worker/queue.py`
- Test: `backend/tests/test_mineru_postgres_queue.py`

**Interfaces:**
- Produces: `claim_jobs(dsn: str, worker_id: str, limit: int, lease_seconds: int) -> list[ClaimedMinerUJob]`.
- Produces: `finish_claim(dsn: str, claim: ClaimedMinerUJob) -> bool`.
- Produces: `reschedule_claim(dsn: str, claim: ClaimedMinerUJob, diagnostics: list[dict], delay_seconds: int) -> bool`.
- Produces: `write_heartbeat(dsn: str, worker_id: str, payload: dict) -> None`.

- [ ] **Step 1: Write failing PostgreSQL queue tests**

Use the configured test PostgreSQL database with isolated tenant/job IDs. Cover single-claim ownership, concurrent `SKIP LOCKED` exclusion, expired-lease reclaim, token-checked finish, reschedule timing, and heartbeat persistence.

```python
first = claim_jobs(dsn, "worker-a", limit=1, lease_seconds=60)
second = claim_jobs(dsn, "worker-b", limit=1, lease_seconds=60)
assert [claim.job_id for claim in first] == [job_id]
assert second == []
assert finish_claim(dsn, replace(first[0], lease_token="wrong")) is False
assert finish_claim(dsn, first[0]) is True
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/test_mineru_postgres_queue.py -q`

Expected: FAIL because the queue module does not exist.

- [ ] **Step 3: Implement the minimal queue**

Use explicit psycopg transactions and JSONB payload updates. Never log or return source signed URLs or API keys. Preserve tenant ID in each claim and update only the row whose lease token still matches.

```python
@dataclass(frozen=True)
class ClaimedMinerUJob:
    tenant_id: str
    job_id: str
    lease_token: str
    attempts: int

CLAIM_SQL = """
SELECT tenant_id, object_id, payload
FROM aicheck_state
WHERE collection = 'ocr_jobs'
  AND payload ->> 'provider' = 'mineru'
  AND payload ->> 'status' IN ('queued', 'running')
  AND (payload ->> 'status' = 'queued' OR NULLIF(payload ->> 'leaseUntil', '')::timestamptz <= now())
  AND (NULLIF(payload ->> 'nextAttemptAt', '') IS NULL OR NULLIF(payload ->> 'nextAttemptAt', '')::timestamptz <= now())
ORDER BY updated_at, object_id
FOR UPDATE SKIP LOCKED
LIMIT %s
"""
```

- [ ] **Step 4: Run tests and verify GREEN**

Run the Step 2 command twice to catch leaked leases or test-state coupling.

- [ ] **Step 5: Commit**

Commit Task 3 files with message `feat: add PostgreSQL MinerU job leases`.

### Task 4: Independent MinerU worker and retry behavior

**Files:**
- Create: `backend/apps/mineru_worker/worker.py`
- Create: `backend/apps/mineru_worker/main.py`
- Modify: `backend/apps/worker/tasks.py`
- Test: `backend/tests/test_mineru_postgres_worker.py`

**Interfaces:**
- Produces: `MinerUPostgresWorker.run_once() -> int` and `MinerUPostgresWorker.run() -> None`.
- Consumes: queue interfaces from Task 3 and existing `mineru_ocr_extract`/`run_mineru_job` execution chain.
- Produces: retry signal for retryable failures without persisting a premature terminal OCR result.

- [ ] **Step 1: Write failing worker tests**

Cover successful claim execution, tenant propagation, retry delays of 10/30/90 seconds, terminal failure after three retries, graceful empty polls, and preservation of the hand-checked normalized result fixture.

```python
processed = worker.run_once()
assert processed == 1
persisted = read_job(dsn, job_id)
assert persisted["status"] == "success"
assert read_parse_result(dsn, persisted["parseResultId"])["fragments"] == EXPECTED_FRAGMENTS
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/test_mineru_postgres_worker.py -q`

Expected: FAIL because the worker does not exist.

- [ ] **Step 3: Implement worker execution and retry boundary**

Refactor only the retry boundary around the existing MinerU execution function. The successful result path must still call the same `run_mineru_job`, `finish_ocr_job_record`, `_finalize_mineru_pipeline`, and `apply_ocr_result` functions. The worker reschedules retryable diagnostics in PostgreSQL and finalizes terminal results through the existing code.

```python
class MinerUPostgresWorker:
    def run_once(self) -> int:
        claims = claim_jobs(self.dsn, self.worker_id, limit=self.batch_size, lease_seconds=self.lease_seconds)
        for claim in claims:
            self._execute(claim)
        return len(claims)
```

- [ ] **Step 4: Verify GREEN and OCR compatibility**

Run: `cd backend && .venv/bin/python -m pytest tests/test_mineru_postgres_worker.py tests/test_mineru_worker.py tests/test_mineru_client.py tests/test_mineru_ocr.py -q`.

- [ ] **Step 5: Commit**

Commit Task 4 files with message `feat: run MinerU OCR from PostgreSQL worker`.

### Task 5: Health and local startup integration

**Files:**
- Modify: `backend/apps/api/main.py`
- Create: `scripts/start-local-dev.zsh`
- Test: `backend/tests/test_mineru_worker_health.py`
- Test: `backend/tests/test_local_startup_script.py`

**Interfaces:**
- Produces: health payload field `mineruWorker` with `required`, `ready`, `instanceId`, `activeCount`, `lastSeenAt`, and `lastError`.
- Produces: local launcher that manages `backend.pid`, `mineru-worker.pid`, `frontend.pid` and corresponding logs.

- [ ] **Step 1: Write failing health and launcher behavior tests**

Test heartbeat freshness through a real `service_heartbeats` row. Execute the launcher in a controlled dry-run environment and assert that it starts/checks the worker independently instead of grepping source text.

```python
payload = asyncio.run(health_payload())
assert payload["mineruWorker"]["required"] is True
assert payload["mineruWorker"]["ready"] is True
assert payload["mineruWorker"]["instanceId"] == "mineru-test"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/test_mineru_worker_health.py tests/test_local_startup_script.py -q`

Expected: FAIL because health and launcher integration do not exist.

- [ ] **Step 3: Implement health and startup integration**

Add a bounded PostgreSQL heartbeat query to API health. Build the repository launcher from the supplied script, add `AICHECK_MINERU_EXECUTION_MODE=postgres`, start the worker with `nohup`, wait for a fresh heartbeat, and include its log in the final tail.

```zsh
export AICHECK_MINERU_EXECUTION_MODE="postgres"
nohup .venv/bin/python -m apps.mineru_worker.main > "$MINERU_WORKER_LOG" 2>&1 &
print $! > "$LOG_DIR/mineru-worker.pid"
```

- [ ] **Step 4: Verify GREEN**

Run the Step 2 command.

- [ ] **Step 5: Commit**

Commit Task 5 files with message `feat: start and monitor PostgreSQL MinerU worker`.

### Task 6: End-to-end verification and startup log audit

**Files:**
- Modify only if a failing verification identifies a scoped defect.

**Interfaces:**
- Verifies all interfaces produced by Tasks 1-5.

- [ ] **Step 1: Run focused backend suites**

Run: `cd backend && .venv/bin/python -m pytest tests/test_mineru_api.py tests/test_mineru_client.py tests/test_mineru_ocr.py tests/test_mineru_worker.py tests/test_mineru_postgres_queue.py tests/test_mineru_postgres_worker.py tests/test_mineru_worker_health.py tests/test_local_startup_script.py -q`.

- [ ] **Step 2: Run upload contract coverage**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contract.py -q -k 'upload_session or contractor_default_project_upload'`.

- [ ] **Step 3: Start the local stack without Redis**

Run the new launcher with Redis and Celery absent. Confirm API, MinerU worker, and frontend readiness.

- [ ] **Step 4: Audit logs**

Check `tmp/dev-server-logs/backend.log`, `mineru-worker.log`, and `frontend.log`. Acceptance requires no Redis connection traceback, one worker-ready event, and successful health payload readiness.

- [ ] **Step 5: Exercise a real upload**

Upload one supported test document through the contractor API, confirm immediate upload success and queued job, then wait for worker completion and compare persisted OCR result keys and provenance with the validated MinerU contract.

- [ ] **Step 6: Run diff and hygiene checks**

Run: `git diff --check`, inspect `git status --short`, and confirm unrelated frontend modifications are untouched.

- [ ] **Step 7: Commit any verification-only fix**

If Step 1-6 required a scoped correction, commit it separately with a message describing that correction. Otherwise create no extra commit.
