# Monolithic Project Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a project-scoped “一键分析” workflow that builds one deduplicated full-project Prompt, performs exactly one large-context LLM call, shows honest phase progress, validates every result, and derives node ReviewRuns for human confirmation.

**Architecture:** A new `libs/project_analysis` package owns immutable project snapshots, `fileCorpus/fileRefs` Prompt assembly, token gating, output validation, and node-result persistence. FastAPI exposes preview/run/history/status endpoints; Celery advances durable phases and performs one `project-review-large` call; Vue displays a separate one-click control and phase-aware progress drawer.

**Tech Stack:** Python 3.12, FastAPI, repository JSONB state collections, Celery/Redis, existing Qwen runtime gateway, Vue 3, Element Plus, TypeScript, pytest, Node assert unit runner, Playwright CLI.

**Spec:** `docs/superpowers/specs/2026-08-26-monolithic-project-analysis-design.md`

## Global Constraints

- One ProjectAnalysisRun performs at most one successful LLM call.
- The request contains every active mounted node document in one immutable snapshot, with OCR stored once in `project.fileCorpus` and nodes resolving it through `fileRefs`.
- Nodes without active mounted evidence never enter the Prompt.
- No evidence truncation, summarization fallback, or automatic shard fallback is allowed.
- Context overflow fails before model dispatch with `PROJECT_ANALYSIS_CONTEXT_LIMIT_EXCEEDED`.
- The model-running phase is indeterminate; only verifiable phase counts produce determinate progress.
- Model output is advisory-only and cannot change formal business state.
- `projectSummary` is always recomputed by the backend.
- Invalid evidence/rule references are downgraded before persistence.
- Existing auto-review ProjectReviewRun/EvidenceShard behavior remains unchanged.
- Remove every active mega-Prompt instruction that refers to `node.linkedFiles`; use `node.fileRefs` and `project.fileCorpus` only.
- Every task follows test-first RED/GREEN cycles and commits independently.

---

### Task 1: Immutable Project Snapshot, Deduplicated Prompt, and Context Gate

**Files:**
- Create: `backend/libs/project_analysis/__init__.py`
- Create: `backend/libs/project_analysis/prompt.py`
- Modify: `backend/libs/review_evidence.py`
- Modify: `backend/libs/qwen_runtime.py`
- Modify: `backend/config/qwen_runtime.yaml`
- Modify: `backend/config/litellm.yaml`
- Test: `backend/tests/test_project_analysis_prompt.py`
- Modify: `backend/tests/test_export_review_evidence_package.py`

**Interfaces:**
- Produces `clean_project_ocr_text(source: str) -> str`.
- Produces `build_project_analysis_snapshot(state, project_id, *, business_pack_id, prompt_version, model_route) -> dict[str, Any]`.
- Produces `build_project_analysis_request(state, snapshot, *, model_alias="project-review-large") -> dict[str, Any]`.
- Produces `project_analysis_preview(state, project_id, *, model_route) -> dict[str, Any]`.
- Produces `ProjectAnalysisContextLimitError(estimated_tokens, max_context_tokens, reserved_output_tokens)`.

- [x] **Step 1: Write failing Prompt contract tests**

  Add fixtures with two nodes sharing one document and one node with a second document. Assert one `fileCorpus` entry per document version, all `fileRefs` resolve, shared OCR occurs once, active latest versions are used, rejected/unmounted evidence is excluded, and zero-evidence nodes are absent.

  ```python
  request = build_project_analysis_request(state, snapshot)
  payload = json.loads(request["messages"][1]["content"])
  assert set(payload["project"]["fileCorpus"]) == {"DV-1", "DV-2"}
  assert payload["project"]["nodes"][0]["fileRefs"][0]["fileId"] in payload["project"]["fileCorpus"]
  assert request["messages"][1]["content"].count('"fullOcrText"') == 2
  assert "linkedFiles" not in request["messages"][1]["content"]
  ```

- [x] **Step 2: Run the focused test and verify RED**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_project_analysis_prompt.py`.

  Expected: import failure for `libs.project_analysis.prompt`.

- [x] **Step 3: Implement conservative OCR cleanup and stable snapshot hashing**

  Move the reusable HTML-to-text behavior behind `clean_project_ocr_text`: remove tags/image paths/control characters, decode entities, preserve row/cell order, and emit source/cleaned hashes. Build the snapshot from `active_node_document_versions`, current business-pack node rules, requirements, OCR hashes, mount revisions, Prompt version, and model-route version.

- [x] **Step 4: Implement one-request Prompt assembly**

  Emit exactly two messages. The system message requires direct lookup with `project.fileCorpus[fileId]`, exact quotedText/ruleRefs, node file-boundary enforcement, and human confirmation. The user message contains node rules, `fileRefs`, unique `fileCorpus`, and `AIAllReviewResult@2.0.0` output schema.

- [x] **Step 5: Write and verify the context-overflow RED test**

  Configure a literal route with `maxContextTokens=100`, `reservedOutputTokens=20`, and a request estimated above 80 tokens. Assert preview reports the overflow and run preparation raises `ProjectAnalysisContextLimitError` before the injected model callable is invoked.

- [x] **Step 6: Add the `project-review-large` model route**

  Add explicit aliases/config entries with no fallback to `review-chat`. Read `maxContextTokens` and `reservedOutputTokens` from the active model route. Estimate input through existing UTF-8 byte token estimation, which is conservative for Chinese, and return the estimate plus available input tokens.

- [x] **Step 7: Remove the legacy linkedFiles instruction**

  Replace `Use only files in the current node linkedFiles when grounding that node.` with `Use only fileCorpus entries referenced by the current node.fileRefs.` in the reusable mega-Prompt generator and regenerate test/test2 artifacts.

- [x] **Step 8: Run Prompt/export tests and commit**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_project_analysis_prompt.py tests/test_export_review_evidence_package.py`.

  Commit with `git commit -m "feat: build monolithic project analysis prompts"`.

---

### Task 2: Strict Output Validation and Derived Node ReviewRuns

**Files:**
- Create: `backend/libs/project_analysis/validation.py`
- Create: `backend/libs/project_analysis/results.py`
- Modify: `backend/libs/review_orchestrator/execution.py`
- Test: `backend/tests/test_project_analysis_validation.py`
- Test: `backend/tests/test_project_analysis_results.py`

**Interfaces:**
- Produces `validate_project_analysis_output(raw_text: str, snapshot: dict, request_payload: dict) -> dict[str, Any]`.
- Produces `recompute_project_analysis_summary(node_reviews: list[dict]) -> dict[str, Any]`.
- Produces `persist_project_analysis_node_results(state, project_run, validated_output) -> list[dict[str, Any]]`.

- [x] **Step 1: Write failing validation tests from the observed test2 failure modes**

  Cover: out-of-node file refs, unresolved corpus IDs, file/version/name mismatch, non-verbatim quotedText, non-contiguous combined quotes, `configuredRequirements` rule source, ellipsis rule quotes, missing positive-claim evidence, incorrect project summary counts, false `requiresHumanConfirmation`, and confidence 1.0 on invalid grounding.

  ```python
  result = validate_project_analysis_output(json.dumps(model_output), snapshot, payload)
  finding = result["nodeReviews"][0]["findings"][0]
  assert finding["groundingStatus"] == "insufficient_evidence"
  assert finding["confidence"] <= 0.55
  assert "EVIDENCE_FILE_OUTSIDE_NODE" in {item["code"] for item in finding["validationFailures"]}
  ```

- [x] **Step 2: Run validation tests and verify RED**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_project_analysis_validation.py`.

  Expected: missing validator import.

- [x] **Step 3: Implement fail-closed validation**

  Parse only a JSON object with matching schema/project IDs and exactly the snapshot node IDs. Validate every evidence and rule reference byte-for-byte against the request payload. Preserve diagnostics, downgrade invalid findings, force human confirmation, and recompute all summary counts from validated node reviews.

- [x] **Step 4: Write failing node persistence tests**

  Assert one derived ReviewRun per snapshot node, one shared model-attempt ID, no second model call, node/project/run IDs on every FindingDraft, historical ReviewRuns retained, status `waiting_human_review`, and no `repo.set_node_status` call for advisory analysis.

- [x] **Step 5: Implement derived ReviewRun persistence**

  Create terminal advisory ReviewRuns with `triggerType=manual_full_project_analysis`, `projectAnalysisRunId`, `sharedModelAttemptId`, immutable snapshot IDs, and validated findings. Persist idempotently per project-analysis-run/node.

- [x] **Step 6: Run result tests and commit**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_project_analysis_validation.py tests/test_project_analysis_results.py`.

  Commit with `git commit -m "feat: validate and attach project analysis results"`.

---

### Task 3: ProjectAnalysisRun Domain, APIs, and Honest Status Contract

**Files:**
- Create: `backend/libs/project_analysis/domain.py`
- Create: `backend/apps/api/project_analysis_routes.py`
- Modify: `backend/apps/api/main.py`
- Modify: `backend/libs/db/repository.py`
- Modify: `backend/libs/security/actions.py`
- Test: `backend/tests/test_project_analysis_domain.py`
- Test: `backend/tests/test_project_analysis_api.py`

**Interfaces:**
- Produces `create_project_analysis_run`, `advance_project_analysis_phase`, `append_project_analysis_event`, `project_analysis_status_view`, and `project_analysis_run_view`.
- Adds preview, create, list, detail, and lightweight status endpoints from the spec.

- [x] **Step 1: Write failing domain tests**

  Assert legal phase order, exact counters, heartbeats, terminal immutability, idempotency key derived from tenant/project/snapshot/prompt/model-route, and no fake percentage during `model_running`.

  ```python
  view = project_analysis_status_view(run)
  assert view["phase"] == "model_running"
  assert view["progressMode"] == "indeterminate"
  assert "percent" not in view
  ```

- [x] **Step 2: Run domain tests and verify RED**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_project_analysis_domain.py`.

- [x] **Step 3: Add state collections and phase domain**

  Add repository mappings/defaults/load scopes for `project_analysis_snapshots`, `project_analysis_runs`, and `project_analysis_events`. Implement legal transitions: `preparing_snapshot -> building_prompt -> queued -> model_running -> validating_output -> persisting_results -> waiting_human_review`, plus `failed` and `partial_failure` branches.

- [x] **Step 4: Write failing API tests**

  Cover inspection/admin authorization, tenant/project isolation, Preview token limit data, ETag snapshot conflict, Idempotency-Key replay, list/detail ordering, lightweight status counters, audit log creation, zero-evidence project behavior, and disabled model route.

- [x] **Step 5: Implement and register APIs**

  Reuse existing `_authorize`/mutation/idempotency conventions. POST accepts `snapshotHash`; rebuild Preview and reject if the hash changed. Create the run in `queued` only after context checks pass, persist it, audit it, and dispatch the prepare task.

- [x] **Step 6: Run API tests and commit**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_project_analysis_domain.py tests/test_project_analysis_api.py`.

  Commit with `git commit -m "feat: expose full project analysis APIs"`.

---

### Task 4: Single Model Call Worker Pipeline and Durable Progress

**Files:**
- Create: `backend/libs/project_analysis/execution.py`
- Modify: `backend/apps/worker/tasks.py`
- Modify: `backend/apps/worker/celery_app.py`
- Test: `backend/tests/test_project_analysis_execution.py`
- Test: `backend/tests/test_project_analysis_worker.py`

**Interfaces:**
- Celery tasks `project_analysis_prepare`, `project_analysis_execute_model`, `project_analysis_validate_output`, and `project_analysis_persist_results`.
- Produces `execute_project_analysis_model(state, run_id, *, client) -> dict[str, Any]`.

- [x] **Step 1: Write the failing single-call execution test**

  Inject a complete fake Qwen client response and assert exactly one `chat_sync` call, alias `project-review-large`, JSON response format, one ModelAttempt, stored Prompt/output hashes, provider usage, heartbeat timestamps, and phase transition to `validating_output`.

- [x] **Step 2: Run execution tests and verify RED**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_project_analysis_execution.py`.

- [x] **Step 3: Implement the single model call**

  Load the immutable snapshot/request by ID, set `model_running`, persist a heartbeat before dispatch, call Qwen once, reject provider truncation, update normalized usage/cost, and store raw-vault context. Do not loop by node or shard.

- [x] **Step 4: Write failing phase-chain worker tests**

  Assert queue routing (`business.light`, `llm.remote`), each task consumes/persists only its phase, retries preserve completed phases, validation counts increment, persistence counts increment, and partial persistence retries only missing nodes.

- [x] **Step 5: Implement task chaining and failure records**

  Each successful task dispatches the next task with only `run_id`. Exceptions call `advance_project_analysis_phase(..., "failed")` with phase/errorCode; model failures never alter OCR or node business state.

- [x] **Step 6: Run worker tests and commit**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_project_analysis_execution.py tests/test_project_analysis_worker.py tests/test_celery_priority_contract.py`.

  Commit with `git commit -m "feat: execute one-call project analysis workflow"`.

---

### Task 5: One-Click Analysis Button and Progress Drawer

**Files:**
- Create: `frontend/src/api/aicheck/projectAnalysis.ts`
- Modify: `frontend/src/api/aicheck/index.ts`
- Create: `frontend/src/views/AICheck/projectAnalysisPresentation.ts`
- Create: `frontend/src/views/AICheck/projectAnalysisPresentation.test.ts`
- Create: `frontend/src/views/AICheck/components/ProjectAnalysisControl.vue`
- Create: `frontend/src/views/AICheck/projectAnalysisWorkbenchIntegration.test.ts`
- Modify: `frontend/src/views/AICheck/Workbench.vue`

**Interfaces:**
- Typed API methods for preview, create, list, detail, and status.
- `ProjectAnalysisControl` accepts `projectId` and emits `run-started`.

- [x] **Step 1: Write failing API and presentation tests**

  Assert exact URLs, POST headers, Preview rendering, determinate counter labels for preparation/validation/persistence, indeterminate model-running state, elapsed/heartbeat text, context-overflow copy, completed copy, and failed copy.

- [x] **Step 2: Run frontend unit tests and verify RED**

  Run `cd frontend && pnpm test:unit`.

- [x] **Step 3: Implement typed API and pure presentation helpers**

  Define explicit `ProjectAnalysisPreview`, `ProjectAnalysisRun`, `ProjectAnalysisStatus`, phase union, counters, error detail, and model-limit fields. Keep label/progress computation outside Vue for deterministic tests.

- [x] **Step 4: Write failing Workbench integration test**

  Assert the inspection/admin-only “一键分析” button appears after AutoReviewControl, changes project scope on project switch, and does not replace the existing auto-review control.

- [x] **Step 5: Implement the drawer and polling**

  Load Preview on open, require confirmation, POST with snapshot hash/idempotency, poll status every two seconds while non-terminal, show exact phase counts, use Element Plus indeterminate progress for `model_running`, restore active/latest run after drawer reopen, and stop polling on component disposal/project switch.

- [x] **Step 6: Run frontend verification and commit**

  Run:

  ```bash
  cd frontend
  pnpm test:unit
  pnpm ts:check
  pnpm eslint \
    src/api/aicheck/projectAnalysis.ts \
    src/views/AICheck/projectAnalysisPresentation.ts \
    src/views/AICheck/components/ProjectAnalysisControl.vue \
    src/views/AICheck/Workbench.vue
  pnpm build:test
  ```

  Commit with `git commit -m "feat: add full project analysis progress drawer"`.

---

### Task 6: Deployment Contracts, Browser Acceptance, and Merge to Main

**Files:**
- Modify: `backend/scripts/deployment_report.py`
- Modify: `backend/tests/test_deployment_report.py`
- Modify: `backend/tests/test_compose_drift.py`
- Modify: `openapi/generated/openapi.json`
- Modify: `docs/superpowers/specs/2026-08-26-monolithic-project-analysis-design.md`

**Interfaces:**
- Deployment check `review.monolithic-project-analysis`.

- [x] **Step 1: Write failing deployment contract assertions**

  Require all five routes, three collections, four Celery tasks, queue routing, `project-review-large`, one-call source terms, context-limit guard, validation source terms, and frontend control presence.

- [x] **Step 2: Implement deployment check and export OpenAPI**

  Add the contract check without source-text-only behavior where executable state can be inspected. Run `cd backend && ../.venv/bin/python -m scripts.openapi_route_coverage --export ../openapi/generated/openapi.json`.

- [x] **Step 3: Run complete backend/frontend regression**

  Run:

  ```bash
  cd backend
  ../.venv/bin/python -m pytest -q
  cd ../frontend
  pnpm test:unit
  pnpm ts:check
  pnpm build:test
  ```

- [x] **Step 4: Perform Playwright CLI acceptance**

  Start local backend/frontend, log in as inspection, verify button placement, Preview counts, run confirmation, each phase presentation, indeterminate model stage, completed/failed recovery, project switch isolation, and zero console errors. Close browser and stop local services.

- [x] **Step 5: Update design status and verify clean branch**

  Mark the design “已实现并验收”, record exact test/browser evidence, run `git diff --check`, and confirm `git status --porcelain -uall` is empty.

- [x] **Step 6: Merge locally to main and verify the merged result**

  From the main checkout, preserve/resolve any untracked files before merge, run `git merge codex/auto-review`, rerun the focused project-analysis backend/frontend tests on `main`, and only then remove the worktree/feature branch if the worktree is clean.

  Commit any final generated artifacts with `git commit -m "test: verify monolithic project analysis"` before merging.
