# NDT Concurrent Submission Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make NDT single-file approval resilient to asynchronous OCR updates, persist only its exact mutation scope, and return an actionable conflict response.

**Architecture:** Refresh only the persisted collections required by the NDT submission before resolving the document and bindings. Build an explicit record set for upload-created bindings and NDT submission mutations so request middleware uses scoped persistence. Represent persistence compare-and-swap failures with a dedicated exception and translate them at the middleware boundary into a business conflict response.

**Tech Stack:** FastAPI, Python 3.12, repository JSONB persistence, pytest.

## Global Constraints

- OCR remains advisory and never blocks NDT single-file approval.
- NDT submission must continue to include all current bindings for exactly one document.
- Unknown exceptions continue to use the existing generic server-error path.
- Preserve the user-owned `audit-reports/2026-08-05-ndt-upload-audit/` directory.

---

### Task 1: Persist upload-created NDT bindings

**Files:**
- Modify: `backend/apps/api/routes.py:6060-6095`
- Test: `backend/tests/test_upload_scoped_persistence.py`

**Interfaces:**
- Consumes: `upload_session_state_records(session_id: str)` and repository upload-session records.
- Produces: an additional `bindings` entry containing only bindings for documents in that upload session.

- [ ] **Step 1: Write a failing test**

Create an NDT upload session, create its draft binding, call `upload_session_state_records`, and assert the returned `bindings` contains the exact binding ID and document ID.

- [ ] **Step 2: Verify RED**

Run: `cd backend && .venv/bin/pytest tests/test_upload_scoped_persistence.py -q`

Expected: FAIL because `bindings` is absent.

- [ ] **Step 3: Implement the minimal scoped record addition**

Add bindings filtered by the session's `document_ids`; do not add unrelated bindings or OCR/vector collections.

- [ ] **Step 4: Verify GREEN**

Run the same pytest command and confirm all tests pass.

### Task 2: Refresh latest state and scope NDT submission persistence

**Files:**
- Modify: `backend/apps/api/routes.py:13345-13480`
- Test: `backend/tests/test_contract.py:8750-8950`

**Interfaces:**
- Consumes: `load_state(selected_state_keys)` and the NDT `documentId`/`bindingIds` request.
- Produces: `ndt_material_submission_state_records(submission_id, document_id, binding_ids, node_ids, todo_ids)` and a request-local scoped flush callback.

- [ ] **Step 1: Write failing behavior tests**

Add tests that simulate a persisted OCR update before submission and assert the route reloads the latest `documents`, `versions`, `bindings`, and `tree_nodes` state before validation. Add a test that captures `flush_mutation_records` and asserts the exact state-key set is `documents`, `bindings`, `tree_nodes`, `submissions`, `todos`, and `audit_logs` after middleware adds the audit record.

- [ ] **Step 2: Verify RED**

Run the two new test cases directly. Expected failures: no targeted reload and the route falls through to full-state persistence.

- [ ] **Step 3: Implement latest-state loading**

Move resolution of requested bindings inside the idempotent producer after `load_state({"documents", "versions", "bindings", "tree_nodes"})`. Re-read the document and bindings only after that refresh.

- [ ] **Step 4: Implement the exact mutation record helper**

Return only the modified document, requested bindings, affected nodes, newly created submission, and new todos. Give the NDT submission a stable `id` equal to `submissionId`. Assign the helper to `request.state.scoped_flush_records` before returning success.

- [ ] **Step 5: Verify GREEN**

Run the new tests and the existing NDT contract tests.

### Task 3: Return an explicit concurrency conflict

**Files:**
- Modify: `backend/libs/db/repository.py:220-240,2529-2535,2880-3940`
- Modify: `backend/libs/contracts/errors.py:1-115`
- Modify: `backend/apps/api/main.py:245-320`
- Test: `backend/tests/test_contract.py`
- Test: `backend/tests/test_postgres_real_integration.py`

**Interfaces:**
- Produces: `ConcurrentPersistenceError`, `errors.RESOURCE_STATE_CHANGED`, and middleware response HTTP 409 with reason `RESOURCE_STATE_CHANGED`.

- [ ] **Step 1: Write a failing API test**

Force the NDT submission scoped flush to raise `ConcurrentPersistenceError` and assert status 409, reason `RESOURCE_STATE_CHANGED`, and message `文件状态已更新，请刷新后重试。`.

- [ ] **Step 2: Verify RED**

Run the new test directly. Expected: current generic handler returns status 500 and `EXTERNAL_TOOL_FAILED`.

- [ ] **Step 3: Add the dedicated exception and error contract**

Replace only repository compare-and-swap `RuntimeError` raises with `ConcurrentPersistenceError`. Add error code `40906 / RESOURCE_STATE_CHANGED`.

- [ ] **Step 4: Translate the exception at the mutation middleware boundary**

Restore failed request state, then return `fail(errors.RESOURCE_STATE_CHANGED, ..., http_status=409)` using the NDT request's explicit conflict message. Do not catch unrelated exceptions.

- [ ] **Step 5: Verify GREEN**

Run the API conflict test and persistence conflict test.

### Task 4: Full verification and commit

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run focused backend tests**

Run: `cd backend && .venv/bin/pytest tests/test_upload_scoped_persistence.py tests/test_contract.py -k 'ndt or resource_state_changed' -q`

- [ ] **Step 2: Run complete backend tests**

Run: `cd backend && .venv/bin/pytest -q`

- [ ] **Step 3: Run static and diff checks**

Run: `git diff --check` and inspect `git diff --stat` plus relevant diffs.

- [ ] **Step 4: Restart the local API and verify the NDT page**

Restart the non-reloading Uvicorn process, refresh `http://localhost:4000/#/workbench/ndt`, and verify the existing document can submit without an OCR concurrency error after its correct business rule is selected.

- [ ] **Step 5: Commit**

Commit only the implementation and tests; do not stage the user-owned audit report directory.
