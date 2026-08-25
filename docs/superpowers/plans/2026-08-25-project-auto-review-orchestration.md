# Project Auto Review Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add project-scoped auto-review policies, durable evidence-change candidates, immediate and daily triggers, ProjectReviewRun parents, and idempotent node ReviewRun children.

**Architecture:** `libs/auto_review.py` owns policy validation, dirty snapshot detection, candidate idempotency, and parent/child run state. OCR targeting emits durable `auto_review_outbox` events after mounting succeeds; a Celery task consumes immediate events and a Celery Beat scan reconciles due daily policies and missed events.

**Tech Stack:** Python 3, FastAPI, repository JSONB state collections, Celery/Redis, pytest, existing node `ai_recheck` and lossless EvidenceSnapshot foundation.

**Spec:** `docs/superpowers/specs/2026-08-25-project-auto-review-design.md`

## Global Constraints

- Policy scope is one project; switching projects loads a different policy.
- Automatic review is always `gap_precheck` and advisory-only.
- New evidence triggers review, but each child ReviewRun uses the full current cumulative node snapshot.
- The idempotency key is tenant/project/node/snapshot/policy revision.
- An in-flight snapshot is immutable; later evidence creates a pending successor candidate.
- Closing the policy stops new automatic runs but does not cancel active runs.
- OCR success must not depend on model availability; OCR writes an outbox event only.
- Every task follows TDD and commits independently.

---

### Task 1: AutoReviewPolicy and Candidate Domain

**Files:**
- Create: `backend/libs/auto_review.py`
- Modify: `backend/libs/db/repository.py`
- Test: `backend/tests/test_auto_review_policy.py`

**Interfaces:**
- Produces `default_auto_review_policy(project_id, tenant_id)`, `validate_auto_review_policy(payload, existing)`, `auto_review_candidate_key(...)`, and `upsert_auto_review_candidate(state, ...)`.

- [ ] Write failing tests for project isolation, realtime/daily/both modes, HH:MM/timezone validation, revision increments, disabled policy behavior, and duplicate candidate keys.
- [ ] Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_auto_review_policy.py` and verify RED.
- [ ] Add repository mappings and defaults for `auto_review_policies`, `auto_review_candidates`, `project_review_runs`, and `auto_review_outbox`.
- [ ] Implement policy validation with these exact trigger values:

```python
TRIGGER_MODES = {"ocr_mounted", "daily_schedule"}
AUTO_REVIEW_MODE = "gap_precheck"

def validate_auto_review_policy(payload, existing):
    trigger_modes = sorted(set(payload.get("triggerModes") or []))
    if any(mode not in TRIGGER_MODES for mode in trigger_modes):
        raise ValueError("unsupported trigger mode")
    daily_time = str(payload.get("dailyTime") or existing.get("dailyTime") or "02:00")
    datetime.strptime(daily_time, "%H:%M")
    ZoneInfo(str(payload.get("timezone") or existing.get("timezone") or "Asia/Shanghai"))
    return {**existing, **payload, "triggerModes": trigger_modes, "reviewMode": AUTO_REVIEW_MODE}
```

- [ ] Implement candidate key as a stable hash of tenantId, projectId, nodeId, evidenceSnapshotHash, and policyRevision; upsert must return the existing record for the same key.
- [ ] Run tests and verify GREEN.
- [ ] Commit with `git commit -m "feat: add project auto review policy domain"`.

---

### Task 2: Project Policy and Manual Full-Review APIs

**Files:**
- Create: `backend/apps/api/auto_review_routes.py`
- Modify: `backend/apps/api/main.py`
- Test: `backend/tests/test_auto_review_api.py`

**Interfaces:**
- `GET /projects/{project_id}/inspection/auto-review-policy`
- `PUT /projects/{project_id}/inspection/auto-review-policy`
- `GET /projects/{project_id}/inspection/auto-review-status`
- `POST /projects/{project_id}/inspection/auto-review/run`

- [ ] Write failing API tests proving project isolation, inspection/admin authorization, ETag revision conflict, Idempotency-Key behavior, manual full-run response, and audit log creation.
- [ ] Run the focused test and verify RED.
- [ ] Register `auto_review_router` with and without `/api` prefix in `apps/api/main.py`.
- [ ] Implement GET/PUT using existing `mutation_guard`, `idempotent`, project visibility, and `versioned_record` patterns; PUT persists one record per tenant/project.
- [ ] Implement status counts from pending candidates and project runs.
- [ ] Implement manual run by calling `create_project_review_run(..., trigger_type="manual_full")` for every node with active mounted evidence.
- [ ] Run tests and verify GREEN.
- [ ] Commit with `git commit -m "feat: expose project auto review controls"`.

---

### Task 3: ProjectReviewRun Parent and Node Child Dispatch

**Files:**
- Modify: `backend/libs/auto_review.py`
- Modify: `backend/libs/review_orchestrator/execution.py`
- Test: `backend/tests/test_project_auto_review_runs.py`

**Interfaces:**
- Produces `dirty_nodes_for_project`, `create_project_review_run`, `dispatch_project_review_run`, and `finalize_project_review_run`.
- Consumes current `build_evidence_snapshot` and existing node ReviewRun dispatch.

- [ ] Write failing tests proving only dirty nodes run, all current mounted versions enter each child snapshot, same snapshot/policy is idempotent, active run plus later evidence creates a successor candidate, one node failure does not fail siblings, and parent completion counts are accurate.
- [ ] Run focused tests and verify RED.
- [ ] Implement dirty comparison against latest successful node ReviewRun `evidenceSnapshotHash`; rules/prompt/strategy version changes also make a node dirty.
- [ ] Create parent records with `expectedNodeIds`, `childReviewRunIds`, `completedNodeIds`, `failedNodeIds`, `triggerType`, and policy snapshot.
- [ ] Add `projectReviewRunId`, `triggerType`, and `autoReviewPolicyRevision` to child AiRun/ReviewRun records.
- [ ] Dispatch one existing node review per dirty node with `reviewMode=gap_precheck`; never create a monolithic project model call.
- [ ] Finalize parent as `completed`, `partial`, or `failed` from child terminal states without changing node business status.
- [ ] Run tests and verify GREEN.
- [ ] Commit with `git commit -m "feat: orchestrate project and node auto reviews"`.

---

### Task 4: OCR Mount Outbox Trigger

**Files:**
- Modify: `backend/libs/material_targeting.py`
- Modify: `backend/libs/document_intelligence.py`
- Modify: `backend/apps/worker/tasks.py`
- Test: `backend/tests/test_auto_review_ocr_trigger.py`

**Interfaces:**
- Produces `node.evidence.mounted` records in `auto_review_outbox` only after NodeEvidenceLink persistence.
- Consumes project policy and affected node IDs from material targeting.

- [ ] Write failing tests proving no event before OCR success, no event when targeting creates no links, one deduplicated event for multiple links to the same node, disabled policy creates no candidate, and OCR completion remains successful when auto-review dispatch is unavailable.
- [ ] Run focused tests and verify RED.
- [ ] Add `createdNodeIds` to targeting results.
- [ ] After successful targeting persistence, call `enqueue_auto_review_evidence_event(state, project_id, document_version_id, node_ids)`; event ID is stable for project/version/mount revision.
- [ ] Keep event persistence in the same state flush as targeting records; never call a model from the OCR worker.
- [ ] Run tests and verify GREEN.
- [ ] Commit with `git commit -m "feat: enqueue auto review after OCR mounting"`.

---

### Task 5: Immediate Consumer and Daily Scheduler

**Files:**
- Modify: `backend/apps/worker/celery_app.py`
- Modify: `backend/apps/worker/tasks.py`
- Modify: `backend/docker-compose.yml`
- Modify: `backend/docker-compose.deploy.yml`
- Test: `backend/tests/test_auto_review_scheduler.py`

**Interfaces:**
- Celery tasks `auto_review_scan_due_projects`, `auto_review_consume_evidence_events`, `auto_review_start_project_run`, and `auto_review_finalize_project`.

- [ ] Write failing tests for project-local timezone due calculation, once-per-local-day execution, realtime debounce, lease/retry handling, missed-event reconciliation, and disabled policy skip.
- [ ] Run focused tests and verify RED.
- [ ] Configure Celery Beat entries every 60 seconds for event consumption and due-project scanning.
- [ ] Route coordinator tasks to `business.light`; child reviews continue on `llm.remote`.
- [ ] Add `auto-review-beat-service` to local and deploy compose with the same environment and health dependencies as worker-service.
- [ ] Use durable status transitions `pending -> delivering -> completed|retry_pending|dead_letter` with leases and bounded exponential retry.
- [ ] Run tests and verify GREEN.
- [ ] Commit with `git commit -m "feat: schedule immediate and daily auto reviews"`.

---

### Task 6: Orchestration Contract and Integration Verification

**Files:**
- Modify: `backend/scripts/deployment_report.py`
- Modify: `backend/tests/test_deployment_report.py`
- Test: `backend/tests/test_auto_review_end_to_end.py`

**Interfaces:**
- Deployment check `review.auto-review-orchestration`.

- [ ] Write a failing end-to-end test: enable realtime policy, OCR and mount license, observe parent/child run; upload drawing later, observe a second child snapshot containing license and drawing; verify findings remain node-scoped.
- [ ] Write failing deployment checks for missing routes, collections, Celery tasks, beat entries, and UI-independent business-state guard.
- [ ] Implement the contract check and orchestration audit fields.
- [ ] Run focused tests plus all evidence foundation tests.
- [ ] Run `cd backend && ../.venv/bin/python -m pytest -q tests/test_auto_review_*.py tests/test_review_evidence_*.py tests/test_deployment_report.py`.
- [ ] Commit with `git commit -m "test: verify project auto review orchestration"`.
