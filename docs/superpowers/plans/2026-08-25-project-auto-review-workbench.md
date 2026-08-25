# Project Auto Review Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a project-scoped automatic-review control beside “AI审查 / 完整工作台”, with policy configuration, status, and manual full-project execution.

**Architecture:** Typed API methods expose the four backend endpoints. A focused `AutoReviewControl.vue` owns loading, ETag updates, the settings drawer, and immediate-run actions; Workbench only supplies the active project ID and renders the control for inspection users.

**Tech Stack:** Vue 3 Composition API, TypeScript, Element Plus, existing Axios mutation helpers, node:test/esbuild unit runner, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-25-project-auto-review-design.md`

## Global Constraints

- The setting belongs to the active project, never to the user or tenant globally.
- Only inspection users see the control; backend remains authoritative for permissions.
- Closing the switch affects future triggers and does not cancel active runs.
- The UI must distinguish realtime, daily, combined, and disabled modes.
- Policy writes carry policy ETag and Idempotency-Key.
- Manual full-project review remains advisory and requires human confirmation.

---

### Task 1: Typed Auto-Review API Client

**Files:**
- Modify: `frontend/src/api/aicheck/index.ts`
- Test: `frontend/src/api/aicheck/autoReviewApi.test.ts`

**Interfaces:**
- Produces `AutoReviewPolicy`, `AutoReviewStatus`, `getProjectAutoReviewPolicyApi`, `updateProjectAutoReviewPolicyApi`, `getProjectAutoReviewStatusApi`, and `runProjectAutoReviewApi`.

- [ ] Write failing tests against an injected request adapter proving exact methods, URLs, ETag, and idempotency headers.
- [ ] Run the focused frontend unit test and verify RED.
- [ ] Implement API types and methods using the existing request/mutation-header helpers.
- [ ] Run tests and verify GREEN.
- [ ] Commit with `git commit -m "feat: add auto review frontend API"`.

### Task 2: AutoReviewControl Component

**Files:**
- Create: `frontend/src/views/AICheck/components/AutoReviewControl.vue`
- Create: `frontend/src/views/AICheck/autoReviewPresentation.ts`
- Test: `frontend/src/views/AICheck/autoReviewPresentation.test.ts`
- Test: `frontend/src/views/AICheck/autoReviewControl.test.ts`

**Interfaces:**
- Props: `projectId: string`, `disabled?: boolean`.
- Emits: `policy-updated`, `run-started`.

- [ ] Write failing presentation tests for disabled/realtime/daily/combined labels and pending/running/failed status summaries.
- [ ] Write a failing component contract test requiring button, drawer, realtime checkbox, daily checkbox, time input, timezone select, save, and immediate-run button.
- [ ] Implement presentation helpers and component loading/error states.
- [ ] Save policy with current policy ETag and a unique idempotency key; refresh status after save/run.
- [ ] Verify GREEN and commit with `git commit -m "feat: add project auto review control"`.

### Task 3: Workbench Integration

**Files:**
- Modify: `frontend/src/views/AICheck/Workbench.vue`
- Test: `frontend/src/views/AICheck/autoReviewWorkbenchIntegration.test.ts`

**Interfaces:**
- Consumes active project ID and inspection role.
- Renders `AutoReviewControl` immediately after the existing `view-segmented` control.

- [ ] Write a failing integration test proving import, inspection-only rendering, active project binding, and position beside the segmented view.
- [ ] Implement the focused Workbench integration without adding policy logic to the large page component.
- [ ] Run unit and TypeScript checks.
- [ ] Commit with `git commit -m "feat: expose auto review in inspection workbench"`.

### Task 4: Browser Acceptance

**Files:**
- Modify: `frontend/e2e/aicheck-smoke.spec.ts`

**Interfaces:**
- Verifies project switching, drawer values, enabling combined mode, status label, and manual full-project run confirmation.

- [ ] Add the failing Playwright flow using the inspection account.
- [ ] Run the focused browser test and verify RED.
- [ ] Fix accessibility or responsive issues found by the browser flow.
- [ ] Run `pnpm ts:check`, focused unit tests, and focused Playwright test.
- [ ] Commit with `git commit -m "test: cover project auto review workbench flow"`.
