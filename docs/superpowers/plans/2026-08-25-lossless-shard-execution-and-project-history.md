# Lossless Shard Execution and Project Review History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute every persisted EvidenceShard as an auditable review input, aggregate all shard findings back to the node ReviewRun, and expose/finalize project-level review history without changing formal business status.

**Architecture:** `review_evidence.py` projects one persisted shard into the existing `EvidenceGroundedReviewInput` contract without reconstructing omitted content. The review orchestrator calls the configured node model once per shard, records the shard/model-attempt lineage, and only advances to human review after processing coverage is 100%; project APIs then summarize the already node-scoped child results, while a coordinator task finalizes running parents.

**Tech Stack:** Python 3.12, FastAPI, existing repository JSONB collections, Celery, pytest, Vue 3/TypeScript, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-25-project-auto-review-design.md`

## Global Constraints

- A later upload triggers a new immutable snapshot containing every currently active document version mounted to that node.
- Every OCR field, table, seal, fragment, and evidence link in the manifest must occur in exactly one reconstructable shard segment set.
- Model physical context limits are handled by more calls and smaller shards, never by silent array slicing or string truncation.
- A node may reach `waiting_human_review` only when every expected shard completed and no shard failed.
- Every model attempt records its `evidenceShardId`, input/output hashes, usage, and cost; every aggregated finding records source shard and model-attempt IDs.
- Findings remain scoped by `projectId`, `nodeId`, and `reviewRunId`, always require human confirmation, and never update formal business status for advisory auto-review.
- One shard or one node failure does not erase sibling results; incomplete state stays explicit and retryable at shard/node scope.
- All behavior changes follow test-first RED/GREEN cycles and are committed independently.

---

### Task 1: EvidenceShard Projection and Processing Coverage

**Files:**
- Modify: `backend/libs/review_evidence.py`
- Test: `backend/tests/test_review_evidence_shard_projection.py`
- Modify: `backend/tests/test_review_evidence_shards.py`

**Interfaces:**
- Produces `grounding_input_for_evidence_shard(shard: dict[str, Any]) -> dict[str, Any]`.
- Produces `update_evidence_processing_coverage(manifest: dict[str, Any], shards: list[dict[str, Any]]) -> dict[str, Any]` through the existing `evidence_coverage_report` contract.
- `coveragePassed` means both structural artifact coverage and successful processing coverage; `structuralCoveragePassed` reports the lossless partition independently.

- [ ] **Step 1: Write the failing projection test**

  Create a hand-authored shard containing a split table row segment, a seal, a fragment, a field, and an evidence link. Assert that `grounding_input_for_evidence_shard` returns only those payload slices, preserves `artifactSegmentId`, `artifactId`, `documentVersionId`, page/bbox/source IDs, and does not contain content from a sibling shard.

- [ ] **Step 2: Run the projection test and verify RED**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_review_evidence_shard_projection.py`.

  Expected: import failure for `grounding_input_for_evidence_shard`.

- [ ] **Step 3: Implement shard projection without rereading the full document**

  Convert each `artifactSegments[].payloadSlice` into the matching `fields`, `tables`, `seals`, `fragments`, or `evidenceLinks` list. Add `artifactId`, `artifactSegmentId`, `segmentIndex`, and `segmentCount` lineage to each projected item. Build `evidenceTextCorpus`, summary counts, `groundingStatus`, and strict grounding warnings using the existing grounding helpers or equivalent public contract fields; never fetch artifacts outside the supplied shard.

- [ ] **Step 4: Write the failing processing coverage test**

  Assert that a structurally complete set of `pending` shards yields `structuralCoveragePassed=true` and `coveragePassed=false`; all `completed` yields `coveragePassed=true`; any `failed` shard yields `coveragePassed=false` and increments `failedShardCount`.

- [ ] **Step 5: Run the coverage test and verify RED**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_review_evidence_shards.py tests/test_review_evidence_shard_projection.py`.

  Expected: pending shards currently report `coveragePassed=true`.

- [ ] **Step 6: Implement separate structural and processing gates**

  Return literal fields `structuralCoveragePassed`, `processingCoveragePassed`, and `coveragePassed = structuralCoveragePassed and processingCoveragePassed`. Treat zero expected artifacts as structurally valid only when no unexpected segments exist, but require the run to record an explicit no-evidence outcome rather than a successful evidence-processing claim.

- [ ] **Step 7: Run focused evidence tests and commit**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_review_evidence_shards.py tests/test_review_evidence_shard_projection.py tests/test_review_evidence_manifest.py tests/test_review_evidence_snapshot.py`.

  Commit with `git commit -m "feat: project review inputs from persisted evidence shards"`.

---

### Task 2: Per-Shard Model Attempts and NodeFindingAggregate

**Files:**
- Create: `backend/libs/review_orchestrator/shard_execution.py`
- Modify: `backend/libs/review_orchestrator/execution.py`
- Modify: `backend/libs/db/repository.py`
- Test: `backend/tests/test_review_evidence_shard_execution.py`

**Interfaces:**
- Produces `review_run_evidence_package(state, review_run) -> tuple[dict[str, Any], list[dict[str, Any]]]`.
- Produces `aggregate_shard_findings(review_run, shard_results) -> dict[str, Any]` with `findingDrafts`, `sourceEvidenceShardIds`, `sourceModelAttemptIds`, `conflicts`, and `aggregateHash`.
- The existing model-call implementation accepts `evidence_shard_id` and uses logical call ID `review:{reviewRunId}:generate_findings:{evidenceShardId}`.

- [ ] **Step 1: Write a failing deterministic execution test**

  Build a ReviewRun with two persisted shards, execute `llm_generate_findings` in deterministic mode, and assert both shards become `completed`, each records its processing mode and timestamps, the ReviewRun coverage passes, and the node receives one deduplicated advisory finding rather than one duplicated finding per shard.

- [ ] **Step 2: Run the deterministic test and verify RED**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_review_evidence_shard_execution.py -k deterministic`.

  Expected: persisted shard statuses remain `pending`.

- [ ] **Step 3: Implement persisted package lookup and deterministic processing**

  Resolve manifest/shards strictly by the IDs stored on the immutable ReviewRun. Deterministic/mock execution projects every shard, records its processed input hash, marks it completed, then creates the existing deterministic draft once and links the aggregate to all source shard IDs.

- [ ] **Step 4: Write a failing multi-call model test**

  Stub only the external Qwen chat boundary with two complete JSON responses. Assert two shards cause two calls; each prompt contains its own shard content and not sibling content; model attempts carry distinct `evidenceShardId` values; shard `modelAttemptIds` point back to those attempts; the aggregate preserves distinct findings and merges exact duplicates' evidence/source lineage.

- [ ] **Step 5: Run the model test and verify RED**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_review_evidence_shard_execution.py -k model`.

  Expected: only one full-input model call occurs.

- [ ] **Step 6: Extract one-call execution and add shard orchestration**

  Keep parsing, cost accounting, guardrails, and provider handling in one reusable single-call function. For each persisted shard, clone the node context, replace only `groundingInput` and evidence lists with `grounding_input_for_evidence_shard`, call the model, append the attempt ID to the shard, and persist shard state after every transition. Store all attempt metadata on the ReviewRun without truncating audit fields.

- [ ] **Step 7: Implement loss-preserving aggregation**

  Deduplicate only exact semantic duplicates keyed by normalized `findingType`, title, description, severity, and suggested action. Union evidence/rule/KB refs and source lineage in stable order. Preserve non-identical and conflicting findings; add a conflict record when the same finding type/fact key has incompatible descriptions or actions. Re-run existing grounding/reference/schema/critic gates against the full node evidence after aggregation.

- [ ] **Step 8: Write a failing incomplete-shard gate test**

  Make the second external call fail. Assert the first shard remains completed, the second becomes failed with an auditable failure reason, the ReviewRun status is `review_incomplete`, coverage is false, and no formal node status transition occurs.

- [ ] **Step 9: Run the incomplete test and verify RED**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_review_evidence_shard_execution.py -k incomplete`.

  Expected: the ReviewRun is currently reported as generic `failed` or incorrectly advances to human review.

- [ ] **Step 10: Add the completion gate and retry-safe behavior**

  Before `waiting_human_review`, recompute coverage from persisted shards. If any shard is pending/failed, set `status=currentStep=review_incomplete`, retain successful shard output for retry, expose the failing shard IDs/reasons, and do not update the business node. A retry processes only non-completed shards and re-aggregates the immutable snapshot.

- [ ] **Step 11: Run focused orchestration tests and commit**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_review_evidence_shard_execution.py tests/test_review_evidence_run_integration.py tests/test_review_grounding_no_silent_truncation.py`.

  Commit with `git commit -m "feat: aggregate lossless review shard model calls"`.

---

### Task 3: ProjectReviewSummary and History APIs

**Files:**
- Modify: `backend/libs/auto_review.py`
- Modify: `backend/apps/api/auto_review_routes.py`
- Test: `backend/tests/test_project_auto_review_history.py`
- Modify: `frontend/src/api/aicheck/autoReview.ts`

**Interfaces:**
- Produces `build_project_review_summary(state, project_run) -> dict[str, Any]`.
- Adds `GET /projects/{project_id}/inspection/project-review-runs`.
- Adds `GET /projects/{project_id}/inspection/project-review-runs/{project_review_run_id}`.

- [ ] **Step 1: Write failing API tests**

  Seed two tenants and two projects with parent/child runs and node findings. Assert list/detail endpoints enforce inspection/admin authorization, tenant/project isolation, newest-first ordering, 404 for a foreign parent ID, completion counts, node summaries, highest severity, finding count, shard coverage, and source lineage.

- [ ] **Step 2: Run the history tests and verify RED**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_project_auto_review_history.py`.

  Expected: both routes return 404.

- [ ] **Step 3: Implement read-only project summaries**

  Summarize only child ReviewRuns listed on the parent. Include each node's `nodeId`, `reviewRunId`, status, finding count, highest severity, snapshot/manifest/shard IDs, coverage, and failure reason. Derive common risks and priority node IDs from completed child findings without copying or mutating node FindingDraft records.

- [ ] **Step 4: Implement isolated list/detail routes**

  Reuse `_authorize`, filter on request tenant and path project, return a stable summary envelope, and include audit lineage in detail. Do not require mutation headers for GET.

- [ ] **Step 5: Add typed frontend read methods**

  Add `listProjectReviewRuns(projectId)` and `getProjectReviewRun(projectId, id)` types/methods to the existing auto-review API module without changing the current drawer behavior.

- [ ] **Step 6: Run API and type tests and commit**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_project_auto_review_history.py tests/test_auto_review_api.py tests/test_project_auto_review_runs.py`.

  Run `cd frontend && pnpm vitest run src/api/aicheck/autoReviewApi.test.ts && pnpm ts:check`.

  Commit with `git commit -m "feat: expose project auto review history"`.

---

### Task 4: Automatic Parent Finalization, Observability, and Acceptance

**Files:**
- Modify: `backend/apps/worker/tasks.py`
- Modify: `backend/apps/worker/celery_app.py`
- Modify: `backend/libs/auto_review.py`
- Modify: `backend/scripts/deployment_report.py`
- Modify: `backend/tests/test_auto_review_scheduler.py`
- Modify: `backend/tests/test_deployment_report.py`
- Modify: `frontend/e2e/aicheck-smoke.spec.ts`

**Interfaces:**
- Adds Celery task `auto_review_finalize_project_runs` on `business.light` every 60 seconds.
- Project status and detail responses expose pending/running/completed/failed node and shard counts.

- [ ] **Step 1: Write a failing finalizer test**

  Seed one running parent whose children are complete/failed and another with a pending child. Execute the worker task and assert only the terminal parent is finalized, its ProjectReviewSummary is stored, and the pending parent stays running.

- [ ] **Step 2: Run the finalizer test and verify RED**

  Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_auto_review_scheduler.py -k finalize`.

  Expected: no finalizer task is registered.

- [ ] **Step 3: Implement and schedule parent reconciliation**

  Add a coordinator that scans running/partial parents, calls `finalize_project_review_run`, persists updated parents plus summaries, and is idempotent on repeated scans. Register/route/schedule the Celery task without adding an undeployed service.

- [ ] **Step 4: Extend observable status and deployment checks**

  Add shard progress and last failure fields to project status/history. Update the executable deployment report to fail when the finalizer task/beat entry, evidence collections, history routes, or shard processing coverage gate is absent.

- [ ] **Step 5: Add a Playwright project-scope acceptance flow**

  Extend the existing authenticated smoke test to open the monitoring workbench, switch projects, verify different auto-review labels, open/save the drawer, start a manual full-project run, and assert the returned/status UI remains advisory. Mock only the API network boundary with complete response payloads when a live worker/model is not available.

- [ ] **Step 6: Run the complete focused regression matrix**

  Run:

  ```bash
  cd backend
  ../.venv/bin/python -m pytest -q \
    tests/test_auto_review_*.py \
    tests/test_project_auto_review_*.py \
    tests/test_review_evidence_*.py \
    tests/test_review_grounding_no_silent_truncation.py \
    tests/test_export_review_evidence_package.py \
    tests/test_deployment_report.py \
    tests/test_celery_priority_contract.py \
    tests/test_compose_drift.py
  ```

  Run:

  ```bash
  cd frontend
  pnpm vitest run \
    src/api/aicheck/autoReviewApi.test.ts \
    src/views/AICheck/autoReviewPresentation.test.ts \
    src/views/AICheck/autoReviewWorkbenchIntegration.test.ts
  pnpm ts:check
  pnpm eslint \
    src/api/aicheck/autoReview.ts \
    src/views/AICheck/components/AutoReviewControl.vue \
    src/views/AICheck/Workbench.vue
  pnpm build:test
  pnpm playwright test e2e/aicheck-smoke.spec.ts --grep "project auto review"
  ```

- [ ] **Step 7: Run the spec acceptance audit and commit**

  Check every bullet in section 18 of `docs/superpowers/specs/2026-08-25-project-auto-review-design.md` against a test result or browser/API observation. Record exact commands and any known environment-only warning in the final handoff.

  Commit with `git commit -m "test: verify lossless project auto review completion"`.

