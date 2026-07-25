# Agent Raw Event Vault Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve every formal Agent model exchange, turn snapshot, tool request, tool result, and provider error as a permanent, hash-verifiable raw archive with FDE inspection and export.

**Architecture:** A new `libs.raw_vault` boundary inserts immutable event metadata and durable payload bytes into PostgreSQL, while a review-worker relay archives bytes to a dedicated locked MinIO bucket. Qwen/LiteLLM transports and the common Agent/tool execution paths emit events through that boundary; read-only APIs and the existing FDE console expose status, payloads, verification, and export without replacing current audit summaries.

**Tech Stack:** Python 3.12, FastAPI, psycopg 3, PostgreSQL, MinIO, httpx, pytest, Vue 3, TypeScript, Element Plus, Playwright.

## Global Constraints

- Cover every formal Agent path through shared model-transport, Agent-turn, and tool-execution boundaries; do not branch storage behavior by R node number.
- Preserve original content without application-layer encryption.
- Business execution continues during archival degradation; archival failure must never trigger a duplicate model call or tool side effect.
- Raw archives are permanent: bucket versioning, Object Lock, legal hold, and no application delete/edit endpoint.
- Provider request and response bodies must be byte-equal to the HTTP transport bodies; secrets in headers are never captured.
- Existing summary audit records and human-decision behavior remain compatible.
- Raw reads are limited to system administrator and FDE and every read/export/verify action is audited.
- The unrelated working-tree change in `frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue` must not be overwritten or committed.

---

### Task 1: Immutable PostgreSQL Schema

**Files:**
- Create: `backend/db/migrations/0002_agent_raw_event_vault.sql`
- Modify: `backend/db/migrations/manifest.json`
- Modify: `backend/tests/test_backend_migrations.py`

**Interfaces:**
- Produces tables `raw_vault_events` and `raw_vault_outbox`.
- Produces append-only trigger `trg_raw_vault_events_append_only`.
- Later tasks rely on `(tenant_id, run_stream_id, sequence)` uniqueness and outbox leasing columns.

- [ ] **Step 1: Write the failing migration tests**

Add assertions that migration `0002_agent_raw_event_vault` exists, that `raw_vault_events` rejects update/delete, and that the same run stream cannot reuse a sequence:

```python
assert apply_migrations(isolated_postgres_url) == [
    "0001_backend_audit_hardening",
    "0002_agent_raw_event_vault",
]
with psycopg.connect(isolated_postgres_url, autocommit=False) as connection:
    connection.execute(
        """
        INSERT INTO raw_vault_events
          (tenant_id, id, run_stream_id, event_type, sequence,
           has_payload, payload_hash, payload_byte_length, previous_event_hash, event_hash,
           object_bucket, object_key, payload_media_type, metadata)
        VALUES
          ('TENANT-A', 'RAWEVT-1', 'RRUN-1', 'llm.request.prepared', 1,
           true, 'sha256:req', 2, 'GENESIS', 'sha256:event',
           'agent-raw-vault', 'TENANT-A/RRUN-1/000001-RAWEVT-1.json',
           'application/json', '{}'::jsonb)
        """
    )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        connection.execute("UPDATE raw_vault_events SET event_type='tampered' WHERE id='RAWEVT-1'")
```

- [ ] **Step 2: Run the migration tests and verify RED**

Run:

```bash
cd backend
.venv/bin/pytest -q tests/test_backend_migrations.py
```

Expected: failure because migration `0002_agent_raw_event_vault` and its tables do not exist.

- [ ] **Step 3: Add the migration**

Create the two tables with explicit columns rather than placing raw bytes in `aicheck_state`:

```sql
CREATE TABLE raw_vault_events (
    tenant_id text NOT NULL,
    id text NOT NULL,
    run_stream_id text NOT NULL,
    project_id text,
    review_run_id text,
    ai_run_id text,
    model_call_attempt_id text,
    provider_tool_call_id text,
    stage text,
    event_type text NOT NULL,
    turn integer,
    sequence bigint NOT NULL,
    has_payload boolean NOT NULL,
    payload_media_type text,
    payload_byte_length bigint CHECK (payload_byte_length >= 0),
    payload_hash text,
    object_bucket text,
    object_key text,
    previous_event_hash text NOT NULL,
    event_hash text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, run_stream_id, sequence),
    UNIQUE (event_hash),
    CHECK (
      (has_payload AND payload_media_type IS NOT NULL AND payload_byte_length IS NOT NULL
        AND payload_hash IS NOT NULL AND object_bucket IS NOT NULL AND object_key IS NOT NULL)
      OR
      (NOT has_payload AND payload_media_type IS NULL AND payload_byte_length IS NULL
        AND payload_hash IS NULL AND object_bucket IS NULL AND object_key IS NULL)
    )
);

CREATE TABLE raw_vault_outbox (
    tenant_id text NOT NULL,
    event_id text NOT NULL,
    run_stream_id text NOT NULL,
    payload bytea NOT NULL,
    payload_hash text NOT NULL,
    object_bucket text NOT NULL,
    object_key text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    attempts integer NOT NULL DEFAULT 0,
    lease_token text,
    lease_until timestamptz,
    next_attempt_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, event_id),
    FOREIGN KEY (tenant_id, event_id) REFERENCES raw_vault_events (tenant_id, id)
);
```

Add indexes for run timelines and pending delivery, plus a trigger that raises `raw_vault_events are append-only` on update/delete.

- [ ] **Step 4: Freeze the migration checksum**

Run:

```bash
cd backend
sha256sum db/migrations/0002_agent_raw_event_vault.sql
```

Append the reported digest to `db/migrations/manifest.json` with `immutable: true`, and update the exact expected manifest map in `tests/test_backend_migrations.py`.

- [ ] **Step 5: Run migration tests and verify GREEN**

Run:

```bash
cd backend
.venv/bin/pytest -q tests/test_backend_migrations.py
```

Expected: all migration tests pass; PostgreSQL integration tests run when `AICHECK_TEST_POSTGRES_URL` is configured and otherwise report their existing skips.

- [ ] **Step 6: Commit**

```bash
git add backend/db/migrations backend/tests/test_backend_migrations.py
git commit -m "feat: add immutable raw vault schema"
```

### Task 2: RawCapture Core and Integrity Chain

**Files:**
- Create: `backend/libs/raw_vault.py`
- Create: `backend/tests/test_raw_vault.py`
- Create: `backend/tests/test_raw_vault_postgres_integration.py`

**Interfaces:**
- Produces `RawCaptureContext`, `CapturedRawEvent`, `RawVaultStore`, `InMemoryRawVaultStore`, `PostgresRawVaultStore`, `RawCapture`, and `verify_event_chain`.
- `RawCapture.capture_bytes(context, event_type, payload, media_type, metadata=None) -> CapturedRawEvent` is the only payload insertion boundary.
- `RawCapture.append_metadata_event(context, event_type, metadata) -> CapturedRawEvent` adds a chained event without creating an outbox row.

- [ ] **Step 1: Write failing unit tests for deterministic events**

```python
def test_capture_preserves_bytes_and_chains_events() -> None:
    store = InMemoryRawVaultStore()
    capture = RawCapture(store=store)
    context = RawCaptureContext(tenant_id="TENANT-A", run_stream_id="RRUN-1", review_run_id="RRUN-1")

    first = capture.capture_bytes(context, "llm.request.prepared", b'{"x":1}', "application/json")
    second = capture.capture_bytes(context, "llm.response.received", b'{"ok":true}', "application/json")

    assert store.payload_for(first.id) == b'{"x":1}'
    assert second.sequence == 2
    assert second.previous_event_hash == first.event_hash
    assert verify_event_chain(store.events_for_run("TENANT-A", "RRUN-1")).status == "verified"
```

Also test concurrent sequence allocation, zero-length bodies, non-JSON bytes, stable object keys, and a modified payload hash producing `hash_mismatch`.

- [ ] **Step 2: Run unit tests and verify RED**

Run:

```bash
cd backend
.venv/bin/pytest -q tests/test_raw_vault.py
```

Expected: import failure for missing `libs.raw_vault`.

- [ ] **Step 3: Implement the core types and canonical hash**

Use frozen dataclasses and canonical metadata JSON:

```python
@dataclass(frozen=True)
class RawCaptureContext:
    tenant_id: str
    run_stream_id: str
    project_id: str | None = None
    review_run_id: str | None = None
    ai_run_id: str | None = None
    model_call_attempt_id: str | None = None
    provider_tool_call_id: str | None = None
    stage: str | None = None
    turn: int | None = None

class RawCapture:
    def capture_bytes(
        self,
        context: RawCaptureContext,
        event_type: str,
        payload: bytes,
        media_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> CapturedRawEvent:
        return self.store.append(context, event_type, bytes(payload), media_type, metadata or {})

    def append_metadata_event(
        self,
        context: RawCaptureContext,
        event_type: str,
        metadata: dict[str, Any],
    ) -> CapturedRawEvent:
        return self.store.append_metadata(context, event_type, metadata)
```

The event hash input is `previous_event_hash + ':' + canonical_event_without_event_hash`; `payload_hash` is SHA-256 of the exact byte string.

- [ ] **Step 4: Write failing PostgreSQL store tests**

Test that one transaction acquires `pg_advisory_xact_lock(hashtext('aicheck:raw-vault:' || tenant || ':' || run))`, assigns the next sequence, inserts event metadata and outbox bytes, and rolls back both when either insert fails.

- [ ] **Step 5: Implement `PostgresRawVaultStore`**

Use psycopg transactions and `SELECT ... ORDER BY sequence DESC LIMIT 1` under the advisory lock. Do not update an existing event on idempotency conflict; return the existing event only when its payload hash and event type match, otherwise raise an integrity error.

Provide `capture_best_effort(...)` that catches storage failures, emits a structured critical log/metric callback, and returns a `RawCaptureFailure` without repeating the business operation.

- [ ] **Step 6: Run core tests and verify GREEN**

```bash
cd backend
.venv/bin/pytest -q tests/test_raw_vault.py tests/test_raw_vault_postgres_integration.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/libs/raw_vault.py backend/tests/test_raw_vault*.py
git commit -m "feat: add raw capture integrity core"
```

### Task 3: MinIO Archive Relay and Permanent Retention

**Files:**
- Modify: `backend/libs/integrations/storage.py`
- Create: `backend/apps/review_worker/raw_vault_relay.py`
- Modify: `backend/apps/review_worker/main.py`
- Modify: `backend/apps/review_worker/outbox.py`
- Modify: `backend/docker-compose.yml`
- Create: `backend/tests/test_raw_vault_relay.py`
- Modify: `backend/tests/test_audit_anchor_minio_integration.py`

**Interfaces:**
- Produces `ObjectStorage.put_locked_bytes(bucket, object_name, data, content_type) -> StoredObjectVersion`.
- Produces `claim_pending_raw_payloads`, `finish_raw_payload`, and `run_raw_vault_relay`.

- [ ] **Step 1: Write failing relay tests**

```python
def test_relay_keeps_payload_until_verified_archive(fake_store, fake_minio) -> None:
    claimed = claim_pending_raw_payloads(fake_store.dsn, limit=10)
    fake_minio.fail_once = True
    finish = deliver_raw_payload(claimed[0], fake_minio)
    assert finish.status == "retry_pending"
    assert fake_store.outbox_payload(claimed[0].event_id) == b"original"

    finish = deliver_raw_payload(claimed[0], fake_minio)
    assert finish.status == "archived"
    assert fake_minio.bytes_at(claimed[0].object_key) == b"original"
```

Test legal hold invocation, stored-byte hash verification, idempotent retry, bounded lease recovery, and a metadata-only `archive.payload.archived` event containing the MinIO version ID without producing another outbox row.

- [ ] **Step 2: Run relay tests and verify RED**

```bash
cd backend
.venv/bin/pytest -q tests/test_raw_vault_relay.py tests/test_audit_anchor_minio_integration.py
```

- [ ] **Step 3: Extend object storage**

Add `agent-raw-vault` to logical bucket configuration and return immutable storage metadata:

```python
@dataclass(frozen=True)
class StoredObjectVersion:
    bucket: str
    object_name: str
    version_id: str | None
    etag: str | None
    byte_length: int
    sha256: str
```

`put_locked_bytes` must put the exact bytes, read them back for SHA-256 verification, and place the resulting version under legal hold. If legal hold cannot be confirmed in strict production mode, delivery fails and the outbox bytes remain.

- [ ] **Step 4: Implement relay leasing and retry**

Use `FOR UPDATE SKIP LOCKED`, a 60-second lease, exponential backoff with bounded jitter, and stable event IDs. An archived payload appends a new delivery event rather than updating the source event.

- [ ] **Step 5: Supervise the relay**

Start `run_raw_vault_relay()` beside Temporal outbox, audit-anchor, and heartbeat tasks in `review_worker.main`. Add `rawVaultRelay: true` to the worker heartbeat.

Add Compose environment variables:

```yaml
AICHECK_RAW_VAULT_BUCKET: ${AICHECK_RAW_VAULT_BUCKET:-agent-raw-vault}
AICHECK_RAW_VAULT_POLL_SECONDS: ${AICHECK_RAW_VAULT_POLL_SECONDS:-1}
AICHECK_RAW_VAULT_BATCH_SIZE: ${AICHECK_RAW_VAULT_BATCH_SIZE:-20}
```

- [ ] **Step 6: Run relay tests and verify GREEN**

```bash
cd backend
.venv/bin/pytest -q tests/test_raw_vault_relay.py tests/test_audit_anchor_minio_integration.py tests/test_review_workflow_outbox.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/libs/integrations/storage.py backend/apps/review_worker backend/docker-compose.yml backend/tests
git commit -m "feat: archive raw events with durable relay"
```

### Task 4: Byte-Exact Model Transport Capture

**Files:**
- Modify: `backend/libs/integrations/litellm_client.py`
- Modify: `backend/libs/qwen_runtime.py`
- Create: `backend/libs/integrations/raw_http_capture.py`
- Modify: `backend/tests/test_qwen_runtime.py`
- Create: `backend/tests/test_litellm_raw_capture.py`
- Modify: `backend/libs/review_orchestrator/execution.py`
- Modify: `backend/apps/worker/tasks.py`
- Modify: `backend/apps/api/routes.py`

**Interfaces:**
- Produces `RawModelCallContext` and `post_json_with_raw_capture` sync/async helpers.
- Model methods accept keyword-only `_raw_capture_context: RawCaptureContext | None`; this key is removed before provider serialization.
- Returned parsed dictionaries stay backward compatible.

- [ ] **Step 1: Write failing byte-equality tests**

Use `httpx.MockTransport` to record `request.content` and return deliberate whitespace/non-ASCII response bytes:

```python
def handler(request: httpx.Request) -> httpx.Response:
    sent.append(request.content)
    return httpx.Response(200, content=b'{"choices":[{"message":{"content":"完整"}}], "usage": {}}')

response = client.chat_sync(messages, _raw_capture_context=context)
events = raw_store.events_for_run("TENANT-A", "RRUN-1")
assert raw_store.payload_for(events[0].id) == sent[0]
assert raw_store.payload_for(events[1].id) == b'{"choices":[{"message":{"content":"完整"}}], "usage": {}}'
```

Add 400/500 response-body tests and a transport-exception envelope test. Assert `Authorization` never appears in captured payload or metadata.

- [ ] **Step 2: Run transport tests and verify RED**

```bash
cd backend
.venv/bin/pytest -q tests/test_qwen_runtime.py tests/test_litellm_raw_capture.py
```

- [ ] **Step 3: Implement explicit request serialization**

Serialize once with deterministic UTF-8 JSON and send the same bytes:

```python
body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
capture.capture_best_effort(context, "llm.request.prepared", body, "application/json", metadata)
response = client.post(url, headers=safe_runtime_headers, content=body)
capture.capture_best_effort(context, event_type, response.content, response.headers.get("content-type", "application/octet-stream"), response_metadata)
```

Capture response bytes before calling `response.json()` and before raising `IntegrationServiceError`.

- [ ] **Step 4: Pass capture context from every formal call site**

Construct context from ReviewRun/AIRun/model attempt IDs in `review_orchestrator/execution.py`, worker tasks, and conversational API Agent loops. Server-mode Qwen delegates capture to LiteLLM once; official-mode Qwen captures at its own transport. Add assertions preventing double capture.

- [ ] **Step 5: Remove raw-data truncation as the only copy**

Keep existing `reasoningProcess[:3000]` and `resultText[:4000]` summary fields for compatibility, but assert their complete source response exists in the Raw Vault and correlate `rawRequestEventId`/`rawResponseEventId` on `model_call_attempts`.

- [ ] **Step 6: Run model and orchestrator tests**

```bash
cd backend
.venv/bin/pytest -q tests/test_qwen_runtime.py tests/test_litellm_raw_capture.py tests/test_review_orchestration_100_probe.py tests/test_review_b_workspace.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/libs/integrations backend/libs/qwen_runtime.py backend/libs/review_orchestrator/execution.py backend/apps backend/tests
git commit -m "feat: capture byte-exact model exchanges"
```

### Task 5: Complete Agent Turns and Tool Exchanges

**Files:**
- Modify: `backend/libs/review_orchestrator/execution.py`
- Modify: `backend/libs/review_tools/executor.py`
- Modify: `backend/apps/api/routes.py`
- Modify: `backend/apps/worker/tasks.py`
- Create: `backend/tests/test_raw_vault_agent_capture.py`
- Modify: `backend/tests/test_review_b_workspace.py`

**Interfaces:**
- Produces `capture_agent_turn(...)`, `capture_tool_request(...)`, and `capture_tool_result(...)` helpers in `libs.raw_vault`.
- Common tool execution receives optional `raw_context` and `turn`; callers remain valid when context is absent.

- [ ] **Step 1: Write failing multi-turn/tool tests**

```python
def test_agent_loop_archives_every_message_and_complete_tool_exchange(monkeypatch) -> None:
    result = run_agent_with_two_tool_turns(...)
    events = raw_store.events_for_run(TENANT, result.review_run_id)
    assert [e.event_type for e in events].count("agent.turn.before_model") == 3
    requested = next(e for e in events if e.event_type == "tool.call.requested")
    completed = next(e for e in events if e.event_type == "tool.call.completed")
    assert raw_store.payload_for(requested.id) == b'{"nodeId":12}'
    assert json.loads(raw_store.payload_for(completed.id))["nonSummaryField"] == "retained"
    assert completed.provider_tool_call_id == requested.provider_tool_call_id
```

Add forbidden-tool, malformed-arguments, tool-exception, worker interruption, and node-specialized execution-path cases.

- [ ] **Step 2: Run Agent capture tests and verify RED**

```bash
cd backend
.venv/bin/pytest -q tests/test_raw_vault_agent_capture.py tests/test_review_b_workspace.py
```

- [ ] **Step 3: Capture turn snapshots**

Immediately before each model call, archive deterministic JSON containing the complete messages, tools, tool choice, model parameters, turn, and stage. Immediately after parsing the provider message, archive the complete updated message list. Do not truncate arrays or text.

- [ ] **Step 4: Capture tools at the common boundary**

Before dispatch, archive the original provider `arguments` string and parsed arguments. At return, serialize the complete result with `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)` and archive it before creating `compact_tool_output()`.

On exceptions, archive:

```json
{"exceptionType":"ValueError","message":"sanitized message","phase":"tool_execution","toolName":"..."}
```

Then preserve current error propagation and summary behavior.

- [ ] **Step 5: Add interruption and no-duplicate assertions**

Raise after each capture boundary and prove earlier events remain. Simulate archival failure and assert model-call count and tool invocation count stay exactly one.

- [ ] **Step 6: Run Agent/tool suites and verify GREEN**

```bash
cd backend
.venv/bin/pytest -q tests/test_raw_vault_agent_capture.py tests/test_review_b_workspace.py tests/test_review_business_tools.py tests/test_llm_tool_schemas.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/libs/review_orchestrator backend/libs/review_tools backend/apps backend/tests
git commit -m "feat: archive complete agent turns and tools"
```

### Task 6: Verification, Read APIs, and Offline Export

**Files:**
- Create: `backend/libs/raw_vault_export.py`
- Modify: `backend/apps/api/routes.py`
- Create: `backend/scripts/verify_raw_vault_export.py`
- Create: `backend/tests/test_raw_vault_api.py`
- Create: `backend/tests/test_raw_vault_export.py`

**Interfaces:**
- Produces `build_raw_vault_summary`, `verify_raw_vault_run`, and streaming `build_raw_vault_export`.
- Adds the four FDE endpoints from the approved design.

- [ ] **Step 1: Write failing authorization and integrity tests**

Test that FDE/admin can list/read/verify/export, contractor receives 403, each raw read appends an audit event, payload responses contain `X-Raw-Payload-SHA256`, and a modified object produces `hash_mismatch`.

- [ ] **Step 2: Write failing export round-trip test**

```python
archive = build_raw_vault_export(store, storage, TENANT, "RRUN-1")
with zipfile.ZipFile(io.BytesIO(archive)) as package:
    manifest = json.loads(package.read("manifest.json"))
    assert package.read(manifest["payloads"][0]["path"]) == original_bytes
assert verify_export_bytes(archive).status == "verified"
```

- [ ] **Step 3: Run API/export tests and verify RED**

```bash
cd backend
.venv/bin/pytest -q tests/test_raw_vault_api.py tests/test_raw_vault_export.py
```

- [ ] **Step 4: Implement read-only endpoints**

Add:

```text
GET  /api/fde/review-runs/{reviewRunId}/raw-vault
GET  /api/fde/raw-vault/events/{eventId}/payload
POST /api/fde/review-runs/{reviewRunId}/raw-vault/verify
GET  /api/fde/review-runs/{reviewRunId}/raw-vault/export
```

Use existing FDE/admin authorization and `repo.audit(...)`. Stream payload/export responses; never embed payload bodies in list responses.

- [ ] **Step 5: Implement offline verifier**

The CLI accepts one zip path, recalculates every payload hash, event hash, previous-event link, sequence, and manifest root, prints JSON, and exits non-zero on any mismatch:

```bash
cd backend
.venv/bin/python scripts/verify_raw_vault_export.py /path/to/RRUN-1-raw-vault.zip
```

- [ ] **Step 6: Run API/export tests and verify GREEN**

```bash
cd backend
.venv/bin/pytest -q tests/test_raw_vault_api.py tests/test_raw_vault_export.py tests/test_fde_console.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/libs/raw_vault_export.py backend/apps/api/routes.py backend/scripts/verify_raw_vault_export.py backend/tests
git commit -m "feat: expose and verify raw vault archives"
```

### Task 7: FDE Raw Archive UI

**Files:**
- Modify: `frontend/src/api/aicheck/index.ts`
- Create: `frontend/src/views/AICheck/components/FdeRawVaultPanel.vue`
- Modify: `frontend/src/views/AICheck/FdeConsole.vue`
- Modify: `frontend/e2e/aicheck-smoke.spec.ts`

**Interfaces:**
- Produces `FdeRawVaultSummary`, `FdeRawVaultEvent`, and API functions for list, payload, verify, and export.
- `FdeRawVaultPanel` receives `reviewRunId: string` and lazy-loads archive data.

- [ ] **Step 1: Add failing E2E assertions**

Mock the new endpoints and assert the ReviewRun view shows status, event timeline, incomplete-gap warning, lazy payload drawer, verify result, and export action. Assert large payloads are fetched only after clicking an event.

- [ ] **Step 2: Run focused E2E and verify RED**

```bash
cd frontend
pnpm exec playwright test e2e/aicheck-smoke.spec.ts --grep "原始运行档案"
```

- [ ] **Step 3: Add API types and methods**

```typescript
export type FdeRawVaultEvent = {
  id: string
  eventType: string
  sequence: number
  turn?: number
  payloadHash: string
  payloadByteLength: number
  payloadMediaType: string
  createdAt: string
}

export type FdeRawVaultSummary = {
  reviewRunId: string
  status: 'complete' | 'archive_incomplete' | 'unrecoverable_gap' | 'hash_mismatch' | 'legacy_not_captured'
  chainHead?: string
  eventCount: number
  pendingCount: number
  events: FdeRawVaultEvent[]
}
```

Use `responseType: 'blob'` for payload and export downloads.

- [ ] **Step 4: Build the focused panel**

Implement status tags, event filters, timeline, lazy JSON/text drawer with a visible display-window warning, copy Hash, single payload download, verification, and complete export. Do not add edit/delete controls.

- [ ] **Step 5: Integrate without touching the user's unrelated file**

Mount the panel in `FdeConsole.vue` ReviewRun detail. Do not modify `ConversationalReviewWorkbenchB.vue`.

- [ ] **Step 6: Run frontend verification**

```bash
cd frontend
pnpm ts:check
pnpm lint:eslint:check
pnpm exec playwright test e2e/aicheck-smoke.spec.ts --grep "原始运行档案"
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/aicheck/index.ts frontend/src/views/AICheck/FdeConsole.vue frontend/src/views/AICheck/components/FdeRawVaultPanel.vue frontend/e2e/aicheck-smoke.spec.ts
git commit -m "feat: add FDE raw vault inspection"
```

### Task 8: Production Readiness and Full Verification

**Files:**
- Modify: `backend/apps/api/main.py`
- Modify: `backend/scripts/validate_deployment_config.py`
- Modify: `backend/scripts/verify_deployment.py`
- Modify: `backend/scripts/deployment_report.py`
- Modify: `DEPLOYMENT.md`
- Create: `backend/tests/test_raw_vault_readiness.py`

**Interfaces:**
- Health/readiness exposes Raw Vault configured state, relay heartbeat, pending count/bytes, oldest age, and integrity failures.
- Strict deployment verification requires schema, versioning, Object Lock, legal hold capability, and relay readiness.

- [ ] **Step 1: Write failing readiness tests**

Assert strict production fails for missing schema, missing locked bucket, absent relay heartbeat, or a bucket that cannot apply legal hold. Assert a temporary outbox backlog is an alert field but does not make `/healthz` fail.

- [ ] **Step 2: Run readiness tests and verify RED**

```bash
cd backend
.venv/bin/pytest -q tests/test_raw_vault_readiness.py tests/test_validate_deployment_config.py
```

- [ ] **Step 3: Implement health, metrics, and gates**

Expose:

```json
{
  "rawVault": {
    "configured": true,
    "relayReady": true,
    "bucketLocked": true,
    "pendingCount": 0,
    "pendingBytes": 0,
    "oldestPendingAgeSeconds": null,
    "integrityFailureCount": 0
  }
}
```

Add production checks and document permanent retention, backup/restore, capacity monitoring, and the business-priority `archive_incomplete` semantics.

- [ ] **Step 4: Run focused readiness tests**

```bash
cd backend
.venv/bin/pytest -q tests/test_raw_vault_readiness.py tests/test_validate_deployment_config.py tests/test_backend_migrations.py
```

- [ ] **Step 5: Run the complete backend regression suite**

```bash
cd backend
.venv/bin/pytest -q
```

Expected: zero failures; environment-dependent integration tests may retain their declared skips.

- [ ] **Step 6: Run the complete frontend verification**

```bash
cd frontend
pnpm ts:check
pnpm lint
pnpm build:pro
```

Expected: all commands exit zero.

- [ ] **Step 7: Run static deployment verification**

```bash
cd backend
.venv/bin/python scripts/migrate_backend.py --verify-only
.venv/bin/python scripts/validate_deployment_config.py --strict-production
```

Expected: migration manifest verified and strict production configuration accepted.

- [ ] **Step 8: Confirm scope and commit**

```bash
git status --short
git diff --check
git add backend/apps/api/main.py backend/scripts backend/tests/test_raw_vault_readiness.py DEPLOYMENT.md
git commit -m "feat: enforce raw vault production readiness"
```

The final status must show no change to the user's pre-existing `frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue`.
