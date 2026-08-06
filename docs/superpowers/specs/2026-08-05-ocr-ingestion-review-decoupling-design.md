# OCR Ingestion and Review Decoupling Design

## Goal

Separate document ingestion from review evidence quality so that a successful MinerU extraction continues through slicing and vectorization even when required review fields, seals, confidence, or formal evidence are incomplete.

## Confirmed Success Rule

A MinerU job is an ingestion success when:

1. the remote call and result normalization complete successfully; and
2. the normalized result contains at least one usable text fragment or one usable table.

A fragment is usable when one of its text/content fields contains non-whitespace text. A table is usable when it contains non-empty HTML, text, rows, or cells. Bounding boxes, extracted business fields, seals, and provider confidence are not required for ingestion success.

MinerU transport failures, invalid result archives, normalization failures, and normalized results with no usable fragment or table are ingestion failures.

## Domain Boundaries

### Ingestion domain

The ingestion domain owns these states:

- document OCR: `排队中`, `识别中`, `已识别`, `识别失败`
- slicing: `未切片`, `待切片`, `切片中`, `已切片`, `切片失败`
- vectorization: `未向量化`, `待向量化`, `向量化中`, `已向量化`, `向量化失败`

`currentOcrStatus` and version/file `ocrStatus` describe only technical OCR execution and content usability. They must not contain or derive from review readiness such as `抽取不完整`.

The PostgreSQL MinerU worker applies the ingestion result. A usable result sets OCR to `已识别`, slicing to `待切片`, and vectorization to `待向量化`, then idempotently enqueues the existing PostgreSQL post-processing task. A failed or empty result sets OCR to `识别失败` and does not enqueue post-processing.

Slicing and vectorization failures remain local to their own stages and never rewrite OCR status.

### Review domain

The review domain owns:

- `ocrReadiness.status`
- `quality.status` and `quality.reasons`
- missing and low-confidence fields
- required table and seal checks
- evidence positioning and bbox coverage
- `formalEvidenceReady`
- review actions and human correction

Review readiness is derived independently from the latest parse result and the selected review profile. Its public states remain `not_started`, `ready`, `incomplete`, `inconsistent`, and `failed` where required by existing contracts.

Missing fields, missing seals, low confidence, or absent bbox may produce `incomplete` and `formalEvidenceReady=false`, but cannot change ingestion OCR, slice, or vector statuses.

## Backend Contracts

Introduce two explicit classifiers with non-overlapping responsibilities:

```python
def parse_result_ingestion_status(parse_result: dict[str, Any] | None) -> str:
    """Return 'usable', 'empty', or 'failed'."""

def parse_result_review_status(parse_result: dict[str, Any] | None) -> str:
    """Return 'ready', 'incomplete', or 'failed'."""
```

`parse_result_ingestion_status` evaluates execution status and usable content only. `parse_result_review_status` evaluates quality gates and formal evidence readiness. Existing `parse_result_outcome_status` may remain temporarily as a compatibility alias for review-facing consumers, but ingestion code must not call it.

`InMemoryRepository.apply_ocr_result` must:

1. classify the result with `parse_result_ingestion_status`;
2. persist the parse result and review quality unchanged;
3. mark usable OCR as `已识别` regardless of review readiness;
4. make post-processing eligible for every usable result;
5. mark empty or failed OCR as `识别失败` with a retryable diagnostic; and
6. never use missing fields, seals, bbox, or confidence as an ingestion failure.

The OCR pipeline run may retain its review-oriented `partial` result for compatibility, but the durable OCR job must complete as `success` when ingestion is usable. Stage records that are not executed by the lightweight MinerU worker must not remain misleadingly `queued`; they must be marked `skipped` with an explicit reason or completed by a separate review workflow.

## API and UI Contracts

Contractor and other upload/history views display only the ingestion pipeline:

```text
排队中 → OCR 中 → 待切片 → 切片中 → 待向量化 → 向量化中 → 已完成
```

Stage-specific failures display `失败可重试`. A review-incomplete result must never display `OCR 中` after the OCR job has reached a terminal state.

Review workbench and file detail views display review readiness separately, including `需复核` and its concrete reasons. Review readiness is not added to the contractor processing-status column.

The API continues returning `ocrReadiness` for review consumers. Project document list reads continue returning `currentOcrStatus`, `sliceStatus`, and `vectorStatus` for ingestion consumers.

## Historical Repair

Provide an idempotent repair command for records currently marked `抽取不完整`:

1. load the latest parse result for each affected document version;
2. classify ingestion with the new classifier;
3. change usable records to `已识别` on document, version, and knowledge file;
4. set missing downstream stages to `待切片` and `待向量化` without regressing completed stages;
5. idempotently enqueue missing PostgreSQL post-processing work;
6. leave review quality and readiness data unchanged; and
7. convert empty/failed results to `识别失败` without creating downstream work.

The command supports a dry-run summary before applying changes and is valid with the same PostgreSQL configuration used locally and on servers.

## Error and Retry Semantics

- MinerU transport, provider, download, archive, or normalization failure: OCR `识别失败`; retry OCR.
- MinerU success with no usable fragment or table: OCR `识别失败`; retry OCR or inspect the source document.
- Usable OCR with incomplete review evidence: OCR `已识别`; continue indexing; review `incomplete`.
- Slicing failure: OCR remains `已识别`; retry slicing.
- Vectorization failure: OCR and slicing remain successful; retry vectorization.
- Review workflow failure: ingestion states remain unchanged; retry or manually review within the review domain.

## Compatibility and Deployment

No Redis or Celery dependency is introduced. MinerU and document post-processing continue using PostgreSQL-backed workers. The design requires no new database table because state objects are already persisted as JSON records, but newly introduced fields and status values must remain backward compatible with existing API readers.

Local and server deployments use the same classifiers and worker code. Startup scripts are not modified unless verification shows a missing worker process; the decoupling itself is application behavior, not an environment-specific switch.

## Verification

Automated tests must prove:

1. usable fragments plus missing required fields and seals produce ingestion success and review incomplete;
2. a usable table without fragments produces ingestion success;
3. whitespace-only fragments and empty tables produce ingestion failure;
4. provider or normalization failure produces ingestion failure and no post-processing task;
5. usable results set OCR `已识别`, slicing `待切片`, and vectorization `待向量化`;
6. PostgreSQL post-processing proceeds for review-incomplete usable OCR;
7. review APIs retain missing-field and missing-seal reasons;
8. contractor status mapping never displays terminal review-incomplete work as `OCR 中`;
9. historical repair is dry-run capable and idempotent; and
10. existing successful, failed, manually corrected, sliced, and vectorized records do not regress.

Runtime verification must upload one document known to be review-incomplete and demonstrate a terminal OCR job, persisted fragments/tables, completed slicing/vectorization, and an independent review status of `incomplete`.
