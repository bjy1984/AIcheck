# PostgreSQL-backed MinerU Worker Design

## Goal

Decouple document upload and MinerU OCR from Redis/Celery so that a verified file upload completes successfully even when Redis is unavailable, while preserving the already-validated MinerU request, normalization, persistence, and OCR result contracts.

## Scope

This change applies only to the MinerU document OCR path. Celery remains available for non-MinerU work such as local/official OCR pipeline stages, knowledge slicing and embedding, AI review, comparison, and export. PostgreSQL remains mandatory for the new MinerU worker mode; SQLite is not a supported queue backend for this mode.

## Architecture

The API process performs only bounded preparation work after validating an upload:

1. Mark the upload session complete.
2. Resolve the document version's OCR provider.
3. For MinerU, create or resume the existing OCR pipeline and durable `ocr_jobs` record in PostgreSQL without contacting MinerU.
4. Return the existing upload-complete success response with an accepted PostgreSQL dispatch descriptor.

An independent `mineru_worker` process polls PostgreSQL for eligible MinerU `ocr_jobs`. It claims work with `FOR UPDATE SKIP LOCKED`, writes a lease token and expiry into the job payload, loads the document/version scope, and runs the existing MinerU execution chain. Multiple workers may run safely; expired leases make interrupted work reclaimable.

The execution chain remains:

`MinerUClient` → provider submission/checkpoint polling → result ZIP download → `normalize_mineru_zip` → artifact persistence → `finish_ocr_job_record` → `apply_ocr_result`.

No alternate normalizer, response adapter, or OCR result schema is introduced.

## Dispatch Boundary

`AICHECK_MINERU_EXECUTION_MODE=postgres` selects the new path and is independent of `AICHECK_TASK_DISPATCH`. In this mode:

- `dispatch_parse_document` performs the bounded preparation needed to persist the MinerU job, but does not invoke a remote provider.
- `dispatch_mineru_ocr` returns an accepted PostgreSQL dispatch result rather than calling Celery.
- Callers treat `mode=postgres` as successfully queued even though there is no Celery task ID.
- Non-MinerU providers retain their existing dispatch behavior.

The current Redis-error inline fallback and its process-wide environment mutation are removed completely.

## PostgreSQL Claim and Lease Contract

The worker claims rows from `aicheck_state` where:

- `collection = 'ocr_jobs'`;
- `payload.provider = 'mineru'`;
- status is `queued`, or status is `running` with an expired lease;
- `nextAttemptAt` is absent or due.

Claiming and payload update occur in one transaction using `FOR UPDATE SKIP LOCKED`. Claimed payloads contain `leaseToken`, `leaseUntil`, `workerId`, `attempts`, and an updated timestamp. Completion removes lease metadata. A worker only finalizes a claim when its lease token still owns the job.

Provider checkpoints already stored as `providerTaskId`, `providerTaskType`, and `providerUploadState` remain authoritative. A reclaimed job resumes the existing MinerU provider task instead of submitting a duplicate.

## Retry and Failure Semantics

The worker uses the existing safe MinerU diagnostics and retryability classification. Retryable provider/network failures are rescheduled in PostgreSQL with delays of 10, 30, and 90 seconds. After three retry attempts, or for a non-retryable failure, the existing failure result is persisted.

Upload and OCR outcomes are independent:

- A verified file and persisted OCR job produce upload success.
- A temporarily unavailable worker leaves OCR status queued.
- MinerU failure changes OCR/job status to failed and remains retryable through the OCR task interface.
- Queue/provider failures never retroactively turn a successful file upload into an upload failure.

## OCR Compatibility Requirements

The following contracts must remain byte-for-byte or structurally equivalent to the current validated MinerU implementation:

- MinerU `vlm` request options and supported source handling;
- provider task checkpoint fields;
- normalized pages, fragments, layout blocks, tables, seals, signatures, fields, quality, diagnostics, metadata, and grounding validation;
- rendered-pixel coordinates and MinerU provenance fields;
- parse-result and artifact reference persistence;
- document/version/knowledge-task status transitions after success or terminal failure.

Existing MinerU client, normalization, worker, and API contract tests remain unchanged and must pass. New tests compare the PostgreSQL worker's persisted OCR result against the same validated fixture used by the existing MinerU worker tests.

## Worker Process and Observability

The worker is a small Python process with no HTTP server. It:

- validates PostgreSQL and MinerU configuration at startup;
- logs a single structured readiness line;
- polls at a configurable interval, defaulting to one second;
- processes a bounded number of concurrent jobs, defaulting to one;
- emits claim, resume, success, retry, and terminal-failure events without secrets or signed URLs;
- handles `SIGTERM`/`SIGINT` and stops claiming new jobs while allowing the active call to finish within the process shutdown window.

A heartbeat record in PostgreSQL exposes worker ID, readiness, last poll, active job count, and last error. The API health payload reports MinerU worker readiness separately from upload readiness.

## Local Startup Integration

The local launcher starts three independent processes: API, MinerU worker, and frontend. It writes `mineru-worker.log` and `mineru-worker.pid`, verifies the worker heartbeat after starting the API, and includes the worker log in the final log tail. Redis and Celery are not started for the MinerU upload path.

The launcher exports `AICHECK_MINERU_EXECUTION_MODE=postgres`. It must not leave `AICHECK_TASK_DISPATCH=celery` as a hidden prerequisite for MinerU. Existing Celery configuration may remain for other features.

## Testing and Acceptance

Acceptance requires all of the following:

1. With nothing listening on port 6379, completing a contractor upload returns success and persists one queued MinerU OCR job.
2. The worker claims that job from PostgreSQL and persists the same normalized OCR content contract as the existing validated MinerU path.
3. Restarting the worker after provider submission resumes from the stored provider task ID without a second submission.
4. Two workers cannot execute the same live lease concurrently.
5. An expired lease is reclaimable.
6. Retryable failures follow the 10/30/90-second schedule; terminal failures do not affect the completed upload status.
7. Existing MinerU API, normalization, and worker tests pass without changing their expected OCR payloads.
8. Local startup logs show PostgreSQL ready, API ready, MinerU worker ready, frontend ready, and no Redis connection traceback.

## Non-goals

- Removing Redis from login security, official OCR distributed controls, or all Celery workloads.
- Changing MinerU models, request options, result normalization, evidence rules, or UI payloads.
- Replacing PostgreSQL with a new queue product.
