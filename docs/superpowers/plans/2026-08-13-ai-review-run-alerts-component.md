# AI Review Run Alerts Component Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract AI evidence-budget and run-failure alerts from `Workbench.vue` without changing behavior, restoring the monolith line-count gate.

**Architecture:** A focused Vue component owns alert rendering, local failure-detail expansion state, and scoped alert styles. `Workbench.vue` keeps all computed business data and retry behavior, passing values down and receiving one `retry` event.

**Tech Stack:** Vue 3 `<script setup>`, TypeScript, Element Plus, Node assertion tests, pytest.

## Global Constraints

- Do not change routes, APIs, display copy, retry conditions, or evidence-budget rules.
- Do not modify `backend/monolith-baseline.json`.
- Keep `handleAiRecheck` in `Workbench.vue`.
- The final `Workbench.vue` line count must not exceed 9875.

---

### Task 1: Extract AI review run alerts and restore the quality gate

**Files:**
- Create: `frontend/src/views/AICheck/components/AiReviewRunAlerts.vue`
- Create: `frontend/src/views/AICheck/aiReviewRunAlerts.test.ts`
- Modify: `frontend/src/views/AICheck/Workbench.vue`
- Modify: `backend/tests/test_verify_deployment.py`

**Interfaces:**
- Consumes: `evidenceBudget`, `failure`, and `failureKindLabel` values already computed by `Workbench.vue`.
- Produces: `AiReviewRunAlerts` component with a `retry` event handled by `handleAiRecheck`.

- [x] **Step 1: Add a failing extraction contract test**

Create `aiReviewRunAlerts.test.ts` that reads the parent and component sources and asserts the parent renders `AiReviewRunAlerts`, forwards the three inputs, handles `@retry="handleAiRecheck"`, and no longer contains `.ai-truncation` or `.ai-failure` style definitions.

- [x] **Step 2: Verify the new contract test fails**

Run: `cd frontend && pnpm test:unit`

Expected: `aiReviewRunAlerts.test.ts` fails because the component does not exist yet.

- [x] **Step 3: Implement the focused component**

Create `AiReviewRunAlerts.vue` with structural prop types for evidence budget and failure data, a local `ref(false)` for failure-detail expansion, and `defineEmits<{ retry: [] }>()`. Move the existing alert markup and `.ai-truncation*`/`.ai-failure*` rules unchanged into the component.

- [x] **Step 4: Replace parent markup and presentation state**

Import and render the component in `Workbench.vue`, remove `aiFailureDetailExpanded`, remove the migrated alert markup/styles, and connect `@retry="handleAiRecheck"`.

- [x] **Step 5: Keep the deployment verifier fixture aligned**

Retain the already red/green-verified literal `/ai-review-b` inspection login path in `backend/tests/test_verify_deployment.py`; production behavior is unchanged.

- [x] **Step 6: Run focused verification**

Run:

```bash
cd frontend && pnpm test:unit && pnpm ts:check
cd ../backend && .venv/bin/pytest -q tests/test_monolith_ratchet.py tests/test_verify_deployment.py
```

Expected: all commands exit 0 and the monolith ratchet passes without baseline changes.

- [x] **Step 7: Run full verification**

Run:

```bash
cd frontend && pnpm build:pro
cd ../backend && .venv/bin/pytest -q
cd .. && git diff --check
```

Expected: production build succeeds, the complete backend suite has zero failures, and `git diff --check` reports no errors.

- [ ] **Step 8: Commit and push**

```bash
git add frontend/src/views/AICheck/components/AiReviewRunAlerts.vue \
  frontend/src/views/AICheck/aiReviewRunAlerts.test.ts \
  frontend/src/views/AICheck/Workbench.vue \
  backend/tests/test_verify_deployment.py \
  docs/superpowers/plans/2026-08-13-ai-review-run-alerts-component.md
git commit -m "refactor: extract AI review run alerts"
git push origin main
```
