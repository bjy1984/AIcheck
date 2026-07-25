# Agent Raw Event Vault Design

## Status

Approved design for implementation.

Baseline: `main@f700387d`.

## Problem

AICheck retains a useful audit ledger, prompt snapshots, lineage, hashes, model usage, structured findings, and human decisions. It cannot, however, reconstruct every formal Agent execution byte for byte.

The current gaps are:

- the complete provider response body is discarded after its hash and selected fields are extracted;
- `reasoningProcess` and `resultText` are truncated;
- not every Agent turn persists the complete message list;
- tool arguments and tool results are summarized or represented only by hashes;
- provider error bodies are reduced to a status and reason;
- some records are updated in place instead of being retained as an append-only raw history;
- some events are persisted only after a larger workflow step completes.

The required outcome is a Raw Event Vault that preserves the original Agent execution stream independently from the existing human-readable audit summaries.

## Confirmed Product Decisions

- Cover every formal Agent path, not a list of hard-coded R node numbers.
- Capture at shared model-transport, Agent-turn, and tool-execution boundaries.
- Preserve original content without application-layer encryption for now.
- Prefer business continuity when raw archival is degraded.
- Retain raw archives permanently.
- Add FDE and system-administrator viewing, verification, and download capabilities.
- Keep the existing summary-oriented audit records for compatibility and efficient UI display.

## Goals

1. Reconstruct the bytes sent to and received from every formal model call.
2. Reconstruct every Agent turn, tool request, tool result, and provider error in order.
3. Detect missing, reordered, or modified events and payload objects.
4. Preserve already-captured events when a worker or Agent run is interrupted.
5. Continue business execution when MinIO archival is temporarily unavailable.
6. Make archival gaps explicit and recoverable instead of silently claiming completeness.
7. Provide a read-only FDE experience and an offline-verifiable export package.
8. Avoid coupling raw capture to current node identifiers or Agent implementations.

## Non-Goals

- Capturing API keys, authorization headers, cookies, or infrastructure credentials.
- Encrypting raw payloads at the application layer in this release.
- Replacing `model_call_attempts`, `review_tool_calls`, `review_events`, `ai_trace_steps`, or existing audit logs.
- Exposing raw data to contractor, inspection, owner, NDT, or other ordinary business roles.
- Adding an application delete, edit, retention-expiry, or cleanup operation.
- Replaying a provider call automatically. The export is evidence for reconstruction and offline analysis, not permission to repeat an external side effect.

## Architecture

### 1. Raw Capture Boundary

A focused `RawCapture` service records raw events. Model clients, Agent turn loops, and the common tool executor call this service instead of writing vault records directly.

Capture is based on execution boundaries:

- model transport: exact request and response bodies;
- Agent loop: complete messages before and after each turn;
- tool dispatch: original tool-call arguments and complete return value or exception;
- run lifecycle: completeness and recovery state.

Node IDs, rule IDs, stages, and Agent versions are event metadata. They do not select a different storage implementation.

### 2. PostgreSQL Event Index

`raw_vault_events` is an append-only index. Each row identifies one immutable event and points to its payload object. It contains enough information to validate ordering and payload integrity without loading the payload.

Application code receives insert and select behavior only. PostgreSQL rejects update and delete operations on this table through database-level enforcement. Corrections and state changes are represented by later events.

Capture events are inserted immediately with a deterministic target bucket and object key, but without a MinIO version ID. A later `archive.payload.archived` event records the verified MinIO version ID. Delivery state is therefore never updated on the original event.

### 3. Durable Delivery Outbox

`raw_vault_outbox` temporarily stores the captured bytes and delivery state. It is intentionally mutable because the archive worker must claim, retry, and complete delivery.

The outbox is not the immutable archive. It is the durable bridge that lets the business workflow continue while MinIO is unavailable. A payload is removed from the outbox only after the object version, byte length, and SHA-256 have been verified and the corresponding archived event is committed.

### 4. MinIO Raw Vault

A dedicated logical bucket, `agent-raw-vault`, stores the original payload bytes. It is separate from documents, previews, OCR artifacts, and audit anchors.

The bucket uses:

- versioning;
- Object Lock;
- legal hold on archived raw payload versions;
- no application delete path;
- stable object names derived from tenant, run, sequence, and event ID.

Permanent retention means the application never sets an expiry and places every archived version under legal hold. Releasing a legal hold is an external emergency-governance operation, not an AICheck product function.

### 5. Archive Relay

A background relay reads `raw_vault_outbox`, writes objects idempotently, verifies the stored bytes, appends delivery events, and updates run completeness projections.

The relay follows the existing outbox and background-worker patterns. It uses stable idempotency keys so a retry cannot create a second logical event even if MinIO contains multiple physical versions.

### 6. Read and Export Service

A read-only service provides:

- event timeline and archive status;
- on-demand payload reads;
- event-chain and object-hash verification;
- single-object download;
- complete run-package export.

The complete run package contains:

- `manifest.json`;
- `events.jsonl`;
- every raw payload at its manifest path;
- an integrity report with independently recomputable hashes.

## Definition of Original Bytes

### Provider Requests

The vault stores the exact UTF-8 HTTP request body passed to the HTTP transport. To make this meaningful, model clients must serialize the payload explicitly and send those exact bytes rather than asking the HTTP library to serialize a Python object internally.

The stored request excludes transport secrets:

- `Authorization`;
- API keys;
- cookies;
- proxy credentials.

Allowed transport metadata includes content type, provider request ID, provider name, model endpoint identity without query secrets, and non-secret correlation headers.

### Provider Responses

The vault stores the exact response body bytes returned by the HTTP transport before JSON parsing, normalization, reasoning extraction, validation, or truncation. The parsed response remains available to current business logic.

Provider error responses store the same raw body bytes plus HTTP status and safe transport metadata. Network failures without a response body store a deterministic UTF-8 JSON exception envelope containing the exception type, sanitized message, phase, and timestamps.

### Agent Messages

Each turn snapshot stores the complete message list and tool schema visible to the Agent at that boundary. Snapshots are deterministic UTF-8 JSON bytes. They are not shortened for display.

### Tool Calls

For provider-originated tool calls, the vault stores:

- provider tool-call ID;
- tool name;
- original arguments string exactly as received;
- parsed arguments as deterministic UTF-8 JSON when parsing succeeds.

For internal tool results, there is no prior wire representation. The vault therefore defines the original archived representation as deterministic UTF-8 JSON serialized immediately at the common return boundary. Exceptions use a deterministic error envelope. Neither representation is compacted or field-filtered.

## Event Model

Core event types are:

- `llm.request.prepared`;
- `llm.response.received`;
- `llm.error.received`;
- `agent.turn.before_model`;
- `agent.turn.after_model`;
- `tool.call.requested`;
- `tool.call.completed`;
- `tool.call.failed`;
- `archive.payload.archived`;
- `archive.payload.retry_scheduled`;
- `run.archive.completed`;
- `run.archive.incomplete`;
- `run.archive.unrecoverable_gap`.

Every event includes:

```json
{
  "id": "RAWEVT-...",
  "schemaVersion": "aicheck-agent-raw-event@1",
  "tenantId": "TENANT-...",
  "projectId": "P-...",
  "reviewRunId": "RRUN-...",
  "aiRunId": "AIRUN-...",
  "modelCallAttemptId": "MCALL-...",
  "providerToolCallId": "call_...",
  "stage": "review_generate_findings",
  "eventType": "llm.response.received",
  "turn": 2,
  "sequence": 8,
  "payloadMediaType": "application/json",
  "payloadByteLength": 18452,
  "payloadHash": "sha256:...",
  "objectBucket": "agent-raw-vault",
  "objectKey": "tenant/run/000008-RAWEVT-....json",
  "previousEventHash": "sha256:...",
  "eventHash": "sha256:...",
  "createdAt": "..."
}
```

Nullable correlation fields are omitted when they do not apply. `sequence` is strictly increasing within a raw run stream. Concurrent writers acquire a run-scoped PostgreSQL advisory transaction lock before assigning the next sequence and chain head.

`eventHash` binds the immutable event metadata, `payloadHash`, and `previousEventHash`. It does not include mutable delivery-attempt fields, which live in the outbox.

`archive.payload.archived` carries the source event ID, verified object version ID, stored byte length, stored payload hash, and delivery timestamp. `archive.payload.retry_scheduled` carries retry metadata without changing either the source event or a prior delivery event.

## Data Flow

### Successful Model Call

1. The client constructs and serializes the exact request body.
2. `RawCapture` inserts `llm.request.prepared` and its outbox payload.
3. The client sends those same bytes.
4. The client receives response body bytes.
5. `RawCapture` inserts `llm.response.received` and its outbox payload before business parsing.
6. Existing parsing, reasoning extraction, validation, and finding generation continue.
7. The relay archives pending objects and appends archive delivery events.
8. When every required event is archived and the chain verifies, the run receives `run.archive.completed`.

### Provider Error

1. The request event is captured as usual.
2. The error response body and status are captured before conversion to `IntegrationServiceError`.
3. Existing retry and failure behavior continues independently.
4. All retry attempts receive distinct `modelCallAttemptId` values and event sequences.

### Tool Call

1. The Agent loop captures `tool.call.requested` before dispatch.
2. The common executor runs the tool.
3. The complete result or error envelope is captured immediately.
4. Existing `review_tool_calls.outputSummary` is still generated for current UI consumers.

### Interrupted Run

Every event is committed independently at its boundary. A later worker crash cannot remove earlier events. The absence of a terminal completeness event keeps the run in `archive_incomplete` until reconciliation determines whether pending data can be delivered or a gap is unrecoverable.

## Business-Priority Failure Semantics

Raw archival must not trigger a duplicate model call or duplicate tool side effect.

### MinIO Failure

- Business execution continues.
- Payload bytes remain in PostgreSQL outbox.
- The run projection becomes `archive_incomplete`.
- Retries use exponential backoff with bounded jitter and a stable idempotency key.
- Recovery to a fully verified archive appends `run.archive.completed`.

### Raw Outbox Write Failure

- Business execution continues when the existing business path can still persist.
- The process emits a structured critical log and metric.
- The in-memory run is marked with an archival gap and the next successful business persistence records `run.archive.unrecoverable_gap`.
- No later component may infer `complete` merely because no outbox row exists.
- The model or tool call is not repeated for archival purposes.

### Payload Verification Failure

- The outbox payload remains retained.
- The event becomes `hash_mismatch`.
- Automatic overwrite of the locked object is forbidden.
- The relay writes a new object version only as an explicit repair attempt and keeps both version IDs in the evidence trail.

## Completeness Projection

Each ReviewRun and AIRun exposes one derived archival state:

- `complete`: all required boundary events exist, all objects are archived, and all hashes verify;
- `archive_incomplete`: one or more payloads are pending or a terminal event is absent;
- `unrecoverable_gap`: execution continued after a capture that cannot be reconstructed;
- `hash_mismatch`: an event or object fails integrity verification.

The projection is derived from raw events and outbox state. It is not authoritative by itself and may be rebuilt.

## Access Control and Audit

Raw Vault access is limited to:

- system administrator;
- FDE.

Ordinary business roles cannot list, read, verify, or export raw payloads.

Every raw payload view, single-object download, run export, and explicit integrity verification writes an entry to the existing audit chain with actor, target run, operation, result, and operation ID.

The Raw Vault API is read-only. It has no mutation or deletion endpoint.

## API Design

The backend adds:

- `GET /api/fde/review-runs/{reviewRunId}/raw-vault`
  - returns status, counts, gaps, chain head, and paginated event metadata;
- `GET /api/fde/raw-vault/events/{eventId}/payload`
  - streams one payload with its media type and integrity headers;
- `POST /api/fde/review-runs/{reviewRunId}/raw-vault/verify`
  - performs an explicit chain and object verification and returns findings;
- `GET /api/fde/review-runs/{reviewRunId}/raw-vault/export`
  - streams a complete run package.

Listing never embeds large payloads. Payload and export endpoints stream data instead of loading an entire run into API memory.

## FDE User Experience

ReviewRun details gain an “原始运行档案” section with:

- completeness status and gap warning;
- permanent-retention indicator;
- event counts by type;
- chronological turn and event timeline;
- filters for model, tool, error, and archive events;
- lazy raw JSON/text viewer;
- copy-hash and single-object download actions;
- verify-integrity action and result panel;
- complete-run export action.

The UI displays `complete`, `archive_incomplete`, `unrecoverable_gap`, and `hash_mismatch` explicitly. A missing archive is never presented as a successful archive.

Large payloads are loaded only when requested. The viewer caps rendered DOM size while preserving full server-side download; the UI must clearly label when only a display window is rendered.

## Existing Audit Compatibility

Current summary records remain:

- `model_call_attempts`;
- `review_tool_calls`;
- `review_events`;
- `ai_trace_steps`;
- ReviewRun lineage and prompt audit;
- human accept, edit, and reject records.

They continue to drive current pages and reports. New raw event IDs are added as correlation references where useful. Truncated display fields may remain for compatibility, but they are no longer the only retained copy.

## Observability

Metrics include:

- captured events and bytes by event type;
- pending outbox rows and bytes;
- oldest pending age;
- archive retry and failure counts;
- complete, incomplete, unrecoverable-gap, and hash-mismatch run counts;
- MinIO write latency;
- export size and duration.

Health and deployment verification report Raw Vault configuration, relay readiness, bucket Object Lock/versioning/legal-hold capability, pending backlog, and integrity status. A production release gate fails when Raw Vault schema or bucket protections are absent. Because business priority is the selected runtime policy, a transient backlog raises a production alert but does not make the main API unhealthy.

## Verification and Acceptance

### Byte Equality

Tests use a recording transport and assert that:

- archived request bytes equal the bytes sent to the provider;
- archived success response bytes equal the bytes returned by the provider;
- archived error response bytes equal the provider error body;
- reasoning and result content are not truncated.

### Agent and Tool Coverage

Tests assert that:

- every formal model client path uses the shared capture boundary;
- multi-turn runs store every complete message snapshot;
- provider tool-call IDs link request and result events;
- original argument strings are retained;
- complete tool results and error envelopes are retained;
- node-specialized execution branches cannot bypass common capture.

### Recovery

Tests simulate:

- MinIO unavailable while business execution succeeds;
- retained outbox bytes and `archive_incomplete`;
- idempotent delivery after MinIO recovery;
- worker interruption between any two boundaries;
- an unrecoverable capture gap without a false `complete` state.

### Integrity

Tests modify:

- an object byte;
- event ordering;
- `previousEventHash`;
- manifest content.

Each modification must fail verification with a specific integrity finding.

### Export

An exported package must be verifiable offline using only the manifest, JSONL index, and payload files. The verifier recalculates payload hashes, event hashes, event order, and the manifest root.

### Regression

Existing ReviewRun, model-call-attempt, tool-summary, human-decision, authentication, and FDE tests remain green. Raw archival degradation cannot alter model retry counts or repeat a tool execution.

## Rollout

1. Apply database migration and create the locked bucket.
2. Deploy capture in shadow mode with FDE visibility disabled.
3. Verify byte equality, outbox delivery, capacity metrics, and no duplicate business execution.
4. Enable FDE read and verification APIs.
5. Enable the FDE page and export.
6. Make Raw Vault readiness part of production deployment verification.

Runs created before this feature are labeled `legacy_not_captured`. Existing hashes and audit records remain available, but the product does not claim that legacy runs are byte-reconstructable.

## Risks and Controls

- **Permanent capacity growth:** expose byte-growth metrics, backlog alerts, and capacity forecasts; do not silently expire data.
- **Main database growth during MinIO outage:** alert on pending bytes and oldest age; keep payloads until verified delivery.
- **Provider client drift:** contract tests require every formal client to expose request and response bytes through the shared boundary.
- **Large FDE payloads:** lazy loading, streaming downloads, and a display-only render window.
- **False completeness:** terminal completeness requires explicit required-event checks, empty outbox state for the run, and successful integrity verification.
- **Raw data visibility:** restrict access to administrator/FDE and audit every read even though this deployment classifies the content as non-secret.
