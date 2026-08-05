# PostgreSQL Document Post-processing Design

## Problem

MinerU OCR jobs are now durable PostgreSQL jobs, but their successful completion only persists OCR artifacts and creates queued `knowledge_tasks`. Slice and vector work is still dispatched through Redis/Celery, so a deployment without Redis leaves documents permanently at `待切片`. The contractor UI currently maps every non-complete slice state to `切片中`, hiding the difference between queued and running work.

The API also serves project documents from process-local repository state. When the independent worker updates PostgreSQL, a long-running API process can keep returning a stale document list and stale processing statuses until it restarts.

## Accepted Architecture

The existing independent MinerU process becomes the document post-processing worker. It continues to lease MinerU OCR jobs from PostgreSQL and additionally leases `slice` and `vector` records from the existing `knowledge_tasks` collection. Slice and vector tasks use the same PostgreSQL lease-token, retry-delay, and `FOR UPDATE SKIP LOCKED` rules as OCR jobs. Vector work is eligible only after the matching slice task has succeeded.

The worker invokes the already validated slice and embedding implementations directly, with Celery continuation and downstream dispatch disabled. This preserves the normalized MinerU OCR result contract and the existing knowledge chunk/vector formats while removing Redis from the MinerU document path. A process crash leaves an expiring lease; a later worker reclaims the task.

Project document read endpoints construct a bounded read-only view from the latest PostgreSQL rows for the requested project. The view includes documents, versions, bindings, OCR results/pipeline state, knowledge files, and knowledge tasks. It must not replace or mutate the API process's global repository state.

## Processing State Contract

- OCR success persists the normalized MinerU result unchanged and queues `slice` and `vector` knowledge tasks.
- A claimed slice task is `执行中`; successful slicing is `成功` and sets the file to `已切片`.
- A vector task remains queued until slicing succeeds. Once claimed it is `执行中`; success sets the file to `已向量化`.
- Retryable failures return a task to `排队中` with `attempts` and `nextAttemptAt`; terminal failures retain the existing failure statuses and diagnostic log.
- UI labels distinguish `待切片`, `切片中`, `待向量化`, `向量化中`, `已完成`, and `失败可重试`.

## Compatibility and Safety

- MinerU normalization, fragments, layout blocks, tables, fields, evidence coordinates, and artifact references are not transformed by this change.
- Existing Celery task entry points remain available for deployments that still use Celery outside the MinerU PostgreSQL path.
- Lease updates require the current token, preventing an expired worker from acknowledging another worker's claim.
- All reads and queue claims remain tenant-scoped.
- Existing unrelated frontend edits are preserved.

## Verification

Tests cover exclusive PostgreSQL claims, dependency ordering, retry scheduling, worker dispatch without Celery, exact MinerU fragment preservation, fresh project document reads, and status-label mapping. Focused backend and frontend tests run before the full relevant regression suite.
