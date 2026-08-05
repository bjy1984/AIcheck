# PostgreSQL Document Post-processing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete uploaded MinerU documents through OCR, slicing, and vectorization without Redis/Celery while always showing contractors the latest persisted documents and accurate processing states.

**Architecture:** Extend the existing PostgreSQL lease queue and independent MinerU worker to consume durable knowledge tasks after OCR. Add a bounded project document read view backed directly by PostgreSQL, and centralize frontend status mapping so queued and active stages are not conflated.

**Tech Stack:** Python 3, FastAPI, psycopg/PostgreSQL JSONB, Celery task implementations invoked locally, Vue 3/TypeScript, Vitest, pytest.

## Global Constraints

- MinerU normalized OCR output must remain byte-for-structure compatible with the previously verified interface contract.
- The MinerU upload and post-processing path must not require Redis or a Celery worker.
- PostgreSQL task claims are tenant-scoped, leased, retryable, and restart-safe.
- Existing unrelated changes in contractor UI files must be preserved.

---

### Task 1: Durable knowledge-task queue

**Files:**
- Modify: `backend/apps/mineru_worker/queue.py`
- Test: `backend/tests/test_mineru_postgres_queue.py`

**Interfaces:**
- Produces: `ClaimedKnowledgeTask`, `claim_knowledge_tasks()`, `finish_knowledge_claim()`, and `reschedule_knowledge_claim()`.
- Consumes: `aicheck_state` rows in the existing `knowledge_tasks` collection.

- [ ] **Step 1: Write failing tests** for exclusive slice claims, vector dependency ordering, expired-lease reclamation, and retry due times.
- [ ] **Step 2: Run tests to verify failure:** `pytest -q backend/tests/test_mineru_postgres_queue.py` must fail because the knowledge queue API is absent.
- [ ] **Step 3: Implement minimal queue SQL** using `FOR UPDATE SKIP LOCKED`, tenant IDs, lease tokens, `nextAttemptAt`, and slice-before-vector eligibility.
- [ ] **Step 4: Run tests to verify pass:** `pytest -q backend/tests/test_mineru_postgres_queue.py`.
- [ ] **Step 5: Commit:** `git add backend/apps/mineru_worker/queue.py backend/tests/test_mineru_postgres_queue.py && git commit -m "feat: lease document postprocessing tasks in postgres"`.

### Task 2: Redis-free slice and vector execution

**Files:**
- Modify: `backend/apps/worker/tasks.py`
- Modify: `backend/apps/mineru_worker/worker.py`
- Test: `backend/tests/test_mineru_postgres_worker.py`
- Test: `backend/tests/test_mineru_worker.py`

**Interfaces:**
- Produces: `execute_postgres_knowledge_task(task_type: str, file_id: str) -> dict[str, Any]`.
- Consumes: claimed knowledge tasks from Task 1 and the existing `slice_knowledge`/`embed_knowledge` implementations.

- [ ] **Step 1: Write failing tests** proving the worker processes OCR, then slice, then vector; does not call `apply_async`; reschedules transient exceptions; and preserves `EXPECTED_FRAGMENTS` exactly.
- [ ] **Step 2: Run tests to verify failure:** `pytest -q backend/tests/test_mineru_postgres_worker.py backend/tests/test_mineru_worker.py`.
- [ ] **Step 3: Add local execution controls** so slicing skips `dispatch_embed` and embedding processes all chunks without a Celery continuation.
- [ ] **Step 4: Extend the worker loop** to claim eligible knowledge tasks, execute them under their tenant context, acknowledge successes, and reschedule retryable failures.
- [ ] **Step 5: Run tests to verify pass:** `pytest -q backend/tests/test_mineru_postgres_worker.py backend/tests/test_mineru_worker.py`.
- [ ] **Step 6: Commit:** `git add backend/apps/worker/tasks.py backend/apps/mineru_worker/worker.py backend/tests/test_mineru_postgres_worker.py backend/tests/test_mineru_worker.py && git commit -m "feat: process document indexing without celery"`.

### Task 3: Fresh PostgreSQL project-document reads

**Files:**
- Modify: `backend/libs/db/repository.py`
- Modify: `backend/apps/api/routes.py`
- Test: `backend/tests/test_contract.py`
- Test: `backend/tests/test_mineru_postgres_worker.py`

**Interfaces:**
- Produces: `project_document_read_view(project_id: str) -> InMemoryRepository` returning a detached bounded snapshot, or the current repository when PostgreSQL is unavailable.
- Consumes: project-scoped rows for documents, versions, bindings, OCR state, knowledge files, and knowledge tasks.

- [ ] **Step 1: Write failing tests** that mutate PostgreSQL from a simulated worker after API state loads and assert both `/documents` and `/nodes/{nodeId}/package` return the new document and latest slice/vector status without restarting the API.
- [ ] **Step 2: Run tests to verify failure:** run the named new tests with `pytest -q` and confirm stale results.
- [ ] **Step 3: Implement the detached read view** with bounded tenant/project SQL and no mutation of `repo.state`.
- [ ] **Step 4: Use the read view** for project documents, bindings, versions, fields, and OCR readiness in both endpoints.
- [ ] **Step 5: Run tests to verify pass:** run the new tests plus `pytest -q backend/tests/test_contract.py -k "documents or node_package"`.
- [ ] **Step 6: Commit:** `git add backend/libs/db/repository.py backend/apps/api/routes.py backend/tests/test_contract.py backend/tests/test_mineru_postgres_worker.py && git commit -m "fix: read project documents from postgres snapshot"`.

### Task 4: Accurate contractor processing labels

**Files:**
- Create: `frontend/src/utils/documentPipelineStatus.ts`
- Create: `frontend/src/utils/documentPipelineStatus.test.ts`
- Modify: `frontend/src/views/AICheck/components/WorkbenchRoleStaticSections.vue`
- Modify: `frontend/src/views/AICheck/components/NdtWorkflowPanel.vue`

**Interfaces:**
- Produces: `documentPipelineStatus(file) -> string`.
- Consumes: `currentOcrStatus`, `sliceStatus`, and `vectorStatus` from `DocumentAsset`-compatible objects.

- [ ] **Step 1: Write failing table tests** for queued OCR, running OCR, queued slice, running slice, queued vector, running vector, complete, and failed states.
- [ ] **Step 2: Run test to verify failure:** `npm --prefix frontend run test -- documentPipelineStatus.test.ts`.
- [ ] **Step 3: Implement the shared mapper** with explicit exact-state handling and failure precedence.
- [ ] **Step 4: Replace duplicate component mappers** while preserving the user's existing table-column ordering edits.
- [ ] **Step 5: Run tests to verify pass:** `npm --prefix frontend run test -- documentPipelineStatus.test.ts` and frontend type checking.
- [ ] **Step 6: Commit:** stage only the shared utility, tests, and intentional component hunks; commit as `fix: show accurate document pipeline states`.

### Task 5: Regression and live-state verification

**Files:**
- Modify only if a test exposes a defect in files already listed above.

**Interfaces:**
- Consumes all deliverables from Tasks 1–4.
- Produces verification evidence for the completed workflow.

- [ ] **Step 1: Run backend focused tests:** MinerU queue, worker, health, OCR, dispatcher, and upload contract suites.
- [ ] **Step 2: Run PostgreSQL integration tests** with `AICHECK_TEST_POSTGRES_URL` and confirm leases plus fresh reads against a real database.
- [ ] **Step 3: Run frontend tests and type checking** for the shared status mapper and affected AICheck components.
- [ ] **Step 4: Inspect the two previously stuck documents** and confirm they advance from queued slice through vector completion, or safely requeue them if their persisted tasks predate the worker change.
- [ ] **Step 5: Review `git diff` and `git status`** to ensure unrelated frontend edits remain intact.
- [ ] **Step 6: Commit any verified repair-only adjustments** with a narrowly scoped message.
