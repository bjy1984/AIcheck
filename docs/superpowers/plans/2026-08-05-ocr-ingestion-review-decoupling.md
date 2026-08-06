# OCR Ingestion and Review Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every technically usable MinerU result continue through PostgreSQL-backed slicing and vectorization while keeping formal review readiness independent.

**Architecture:** Add a content-only ingestion classifier beside the existing review classifier. Repository application and knowledge task scheduling consume the ingestion classifier; review APIs continue consuming quality gates. Contractor UI renders only ingestion stages, and an idempotent repair command promotes historical usable `抽取不完整` records without changing their review evidence.

**Tech Stack:** Python 3.12, pytest, FastAPI repository state persisted in PostgreSQL JSON records, Vue 3, TypeScript, Node assert tests.

## Global Constraints

- A successful MinerU call with at least one usable text fragment or usable table is ingestion success.
- Missing fields, seals, bbox, and confidence affect review readiness only and never block slicing or vectorization.
- Empty or invalid MinerU output is OCR failure and does not enqueue downstream work.
- Redis and Celery must not be introduced into this upload pipeline.
- Local and server deployments use the same application behavior and PostgreSQL task path.
- Existing review-facing `outcomeStatus` remains compatible.

---

### Task 1: Separate ingestion classification from review classification

**Files:**
- Modify: `backend/libs/ocr_readiness.py`
- Modify: `backend/tests/test_ocr_readiness.py`

**Interfaces:**
- Produces: `parse_result_ingestion_status(parse_result: dict[str, Any] | None) -> str`, returning `usable`, `empty`, or `failed`.
- Preserves: `parse_result_outcome_status(parse_result)`, retaining review-oriented `completed`, `partial`, or `failed` behavior.

- [ ] **Step 1: Write failing classifier tests**

Add tests asserting that review-incomplete text and table-only results are `usable`, whitespace-only output is `empty`, and execution failure is `failed`:

```python
def test_ingestion_status_accepts_review_incomplete_text() -> None:
    result = parse_result(
        fragments=[{"text": "材料代用单"}],
        quality={"status": "needs_human_review", "reasons": ["REQUIRED_FIELD_MISSING"]},
    )
    assert parse_result_ingestion_status(result) == "usable"


def test_ingestion_status_accepts_non_empty_table_without_fragments() -> None:
    result = parse_result(fragments=[])
    result["tables"] = [{"html": "<table><tr><td>DN50</td></tr></table>"}]
    assert parse_result_ingestion_status(result) == "usable"


def test_ingestion_status_rejects_empty_artifacts() -> None:
    result = parse_result(fragments=[{"text": "   "}])
    result["tables"] = [{"rows": []}]
    assert parse_result_ingestion_status(result) == "empty"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && .venv/bin/pytest tests/test_ocr_readiness.py -q`

Expected: collection fails because `parse_result_ingestion_status` is not defined.

- [ ] **Step 3: Implement the content-only classifier**

Add focused helpers that reuse content semantics without checking quality:

```python
def parse_result_ingestion_status(parse_result: dict[str, Any] | None) -> str:
    execution_status = str((parse_result or {}).get("status") or "").lower()
    if execution_status not in {"success", "succeeded", "completed"}:
        return "failed"
    fragments = [item for item in (parse_result or {}).get("fragments", []) if isinstance(item, dict)]
    tables = [item for item in (parse_result or {}).get("tables", []) if isinstance(item, dict)]
    if any(_has_content(item) for item in [*fragments, *tables]):
        return "usable"
    return "empty"
```

- [ ] **Step 4: Run classifier tests and verify GREEN**

Run: `cd backend && .venv/bin/pytest tests/test_ocr_readiness.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the classifier**

```bash
git add backend/libs/ocr_readiness.py backend/tests/test_ocr_readiness.py
git commit -m "feat: separate OCR ingestion classification"
```

### Task 2: Make repository application and PostgreSQL post-processing use ingestion status

**Files:**
- Modify: `backend/libs/db/repository.py`
- Modify: `backend/apps/worker/tasks.py`
- Modify: `backend/tests/test_material_targeting.py`
- Modify: `backend/tests/test_mineru_postgres_worker.py`

**Interfaces:**
- Consumes: `parse_result_ingestion_status` from Task 1.
- Produces: `apply_ocr_result` result status `success`, `empty`, or `failed`; usable results expose their review outcome separately as `reviewOutcomeStatus`.
- Preserves: parse result quality, `outcomeStatus`, and review readiness data.

- [ ] **Step 1: Replace the coupled repository test with failing decoupling tests**

Change the existing quality-blocked test to expect:

```python
assert applied["status"] == "success"
assert applied["reviewOutcomeStatus"] == "partial"
assert document["currentOcrStatus"] == "已识别"
assert version["sliceStatus"] == "待切片"
assert version["vectorStatus"] == "待向量化"
assert [item for item in repo.state["extracted_fields"] if item.get("documentVersionId") == version["id"]]
```

Add an empty-result case expecting `识别失败`, `未切片`, and no extracted fields.

- [ ] **Step 2: Run repository tests and verify RED**

Run: `cd backend && .venv/bin/pytest tests/test_material_targeting.py -q`

Expected: the quality-blocked case reports `partial` and remains `抽取不完整`.

- [ ] **Step 3: Update `apply_ocr_result`**

Use ingestion status for durable pipeline state and retain review outcome for review consumers:

```python
ingestion_status = parse_result_ingestion_status(result)
review_outcome_status = parse_result_outcome_status(result)
success = ingestion_status == "usable"
status = "已识别" if success else "识别失败"
```

For usable results, continue normal field/evidence normalization and downstream `待切片`/`待向量化` setup regardless of `review_outcome_status`. For empty results, return a retryable failure without normalizing evidence.

- [ ] **Step 4: Add a failing PostgreSQL worker integration test**

Create a job tied to a real repository document/version and return a parse result with fragments plus `outcomeStatus="partial"` and missing-field quality. Assert the worker finishes the OCR job successfully, changes the document to `已识别`, and creates or advances the knowledge post-processing task.

- [ ] **Step 5: Run worker integration tests and verify RED**

Run: `cd backend && .venv/bin/pytest tests/test_mineru_postgres_worker.py -q`

Expected: downstream state is not scheduled for the partial review outcome.

- [ ] **Step 6: Make worker finalization terminal and non-misleading**

Ensure the MinerU pipeline records ingestion success independently. Mark lightweight-worker stages not executed during upload as `skipped` with `skipReasons=["review_pipeline_separate"]` instead of leaving them `queued`. Keep `formalEvidenceReady` and the review pipeline result independent.

- [ ] **Step 7: Run backend target tests and verify GREEN**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_ocr_readiness.py tests/test_material_targeting.py tests/test_mineru_postgres_worker.py tests/test_mineru_worker.py -q
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit backend decoupling**

```bash
git add backend/libs/db/repository.py backend/apps/worker/tasks.py backend/tests/test_material_targeting.py backend/tests/test_mineru_postgres_worker.py
git commit -m "fix: decouple OCR ingestion from review quality"
```

### Task 3: Correct contractor pipeline presentation

**Files:**
- Modify: `frontend/src/utils/documentPipelineStatus.ts`
- Modify: `frontend/src/utils/documentPipelineStatus.test.ts`
- Modify: `frontend/src/types/aicheck.ts`

**Interfaces:**
- Consumes: technical `currentOcrStatus`, `sliceStatus`, and `vectorStatus` only.
- Produces: contractor-facing processing labels without review readiness leakage.

- [ ] **Step 1: Add failing status mapping cases**

Add cases proving terminal or legacy review labels cannot remain `OCR 中`:

```typescript
[{ currentOcrStatus: '抽取不完整', sliceStatus: '待切片' }, '待切片'],
[{ currentOcrStatus: '抽取不完整', sliceStatus: '已切片', vectorStatus: '待向量化' }, '待向量化'],
[{ currentOcrStatus: '识别失败' }, '失败可重试']
```

- [ ] **Step 2: Run frontend test and verify RED**

Run: `cd frontend && pnpm exec tsx src/utils/documentPipelineStatus.test.ts`

Expected: legacy `抽取不完整` maps to `OCR 中`.

- [ ] **Step 3: Restrict `OCR 中` to active technical states**

Map only `识别中` to `OCR 中`. Treat legacy `抽取不完整` as a terminal OCR artifact and continue rendering slice/vector status. Remove `抽取不完整` from the new `DocumentAsset.currentOcrStatus` union while accepting it as a compatibility string at API boundaries.

- [ ] **Step 4: Run frontend checks and verify GREEN**

Run:

```bash
cd frontend
pnpm exec tsx src/utils/documentPipelineStatus.test.ts
pnpm ts:check
```

Expected: status tests and TypeScript checks pass.

- [ ] **Step 5: Commit frontend status correction**

```bash
git add frontend/src/utils/documentPipelineStatus.ts frontend/src/utils/documentPipelineStatus.test.ts frontend/src/types/aicheck.ts
git commit -m "fix: keep review readiness out of upload status"
```

### Task 4: Repair historical review-incomplete ingestion records

**Files:**
- Create: `backend/scripts/repair_ocr_ingestion_status.py`
- Create: `backend/tests/test_repair_ocr_ingestion_status.py`

**Interfaces:**
- Consumes: repository documents, versions, knowledge files/tasks, and latest parse results.
- Produces: dry-run JSON schema `aicheck-ocr-ingestion-repair@1`; `--apply` performs idempotent status repair and enqueues missing post-processing work through repository APIs.

- [ ] **Step 1: Write failing dry-run and apply tests**

Create repository fixtures and assert exact repair behavior:

```python
def test_dry_run_finds_usable_incomplete_without_mutating() -> None:
    repository, document, version = incomplete_repository(fragments=[{"text": "材料代用单"}])
    before = deepcopy(repository.state)
    repairs = build_repairs(repository)
    assert repairs == [{
        "documentId": document["id"],
        "documentVersionId": version["id"],
        "ingestionStatus": "usable",
        "before": "抽取不完整",
        "after": "已识别",
    }]
    assert repository.state == before


def test_apply_is_idempotent_and_preserves_completed_stages() -> None:
    repository, document, version = incomplete_repository(fragments=[{"text": "材料代用单"}])
    version["sliceStatus"] = "已切片"
    version["vectorStatus"] = "已向量化"
    first = apply_repairs(repository, build_repairs(repository))
    second = apply_repairs(repository, build_repairs(repository))
    assert first["promotedCount"] == 1
    assert second["promotedCount"] == 0
    assert document["currentOcrStatus"] == "已识别"
    assert version["sliceStatus"] == "已切片"
    assert version["vectorStatus"] == "已向量化"
```

- [ ] **Step 2: Run repair tests and verify RED**

Run: `cd backend && .venv/bin/pytest tests/test_repair_ocr_ingestion_status.py -q`

Expected: import fails because the repair module does not exist.

- [ ] **Step 3: Implement repair planning and application**

Expose pure functions with these signatures:

```python
def build_repairs(repository: InMemoryRepository) -> list[dict]
def apply_repairs(repository: InMemoryRepository, repairs: list[dict]) -> dict[str, int]
```

The CLI loads only required PostgreSQL collections, defaults to dry-run, accepts `--apply` and `--json`, flushes only changed records, and uses idempotent task creation. Never regress `已切片` or `已向量化`.

- [ ] **Step 4: Run repair tests and verify GREEN**

Run: `cd backend && .venv/bin/pytest tests/test_repair_ocr_ingestion_status.py -q`

Expected: all repair tests pass.

- [ ] **Step 5: Dry-run against the local PostgreSQL database**

Run:

```bash
cd backend
AICHECK_DATABASE_URL=postgresql:///aicheck .venv/bin/python -m scripts.repair_ocr_ingestion_status --json
```

Expected: JSON report lists the current S02 record as a usable promotion candidate without changing database state.

- [ ] **Step 6: Apply and rerun to prove idempotency**

Run the command with `--apply --json`, then run dry-run again. Expected: S02 becomes `已识别` and eligible for post-processing; the second report has zero pending repairs.

- [ ] **Step 7: Commit historical repair**

```bash
git add backend/scripts/repair_ocr_ingestion_status.py backend/tests/test_repair_ocr_ingestion_status.py
git commit -m "fix: repair usable OCR ingestion states"
```

### Task 5: Complete regression and runtime verification

**Files:**
- Modify only if a regression exposes a requirement gap in Tasks 1-4.

**Interfaces:**
- Consumes: all deliverables from Tasks 1-4.
- Produces: test and runtime evidence for the complete design.

- [ ] **Step 1: Run backend regression suite for affected domains**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_ocr_readiness.py tests/test_material_targeting.py tests/test_mineru_ocr.py tests/test_mineru_worker.py tests/test_mineru_postgres_worker.py tests/test_repository_postgres_concurrency.py tests/test_repair_ocr_ingestion_status.py -q
```

Expected: all tests pass without warnings caused by this change.

- [ ] **Step 2: Run frontend checks**

Run:

```bash
cd frontend
pnpm exec tsx src/utils/documentPipelineStatus.test.ts
pnpm ts:check
```

Expected: both commands pass.

- [ ] **Step 3: Inspect repaired runtime state**

Query local PostgreSQL through repository APIs and verify the S02 document has OCR `已识别`, a terminal successful OCR job, persisted fragments/tables, review readiness `incomplete`, and a downstream task that reaches sliced/vectorized terminal state.

- [ ] **Step 4: Verify no Redis/Celery upload dependency**

Confirm the upload route dispatches MinerU through the PostgreSQL job and downstream work through the PostgreSQL knowledge task queue. Verify no newly changed code calls Celery or requires Redis.

- [ ] **Step 5: Review the final diff and repository status**

Run:

```bash
git diff origin/main...HEAD --check
git status --short --branch
```

Expected: no uncommitted implementation changes and no whitespace errors.
