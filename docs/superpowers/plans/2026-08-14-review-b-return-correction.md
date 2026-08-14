# Review B Return Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent Review B return-correction action that atomically creates a “需补正” opinion, a return or supplement request, node/material state changes, and an assignee todo without changing ReviewRun.

**Architecture:** Extend the existing node `return-correction` mutation with an opt-in B payload while preserving the legacy binding-only request. Extend `review-workspace` with return permission and submitted binding candidates. Put frontend mode/default/payload rules in a pure helper and render the form in a focused dialog component.

**Tech Stack:** FastAPI, Python 3.12, pytest, Vue 3, TypeScript, Element Plus, Node `assert`, pnpm/Vite.

## Global Constraints

- The action is independent from ReviewRun and never changes ReviewRun status or `humanDecision`.
- The button remains available when no submitted bindings exist; that state creates a supplement request.
- Submitted bindings and missing requirements default to selected but remain editable.
- A B request atomically writes the “需补正” opinion, rectification/supplement record, node and applicable binding state, todo, and audit.
- Legacy callers that omit `mode`, `opinion`, and `supplementRequirements` keep their current binding-return behavior.
- Preserve the untracked `audit-reports/admin-menu-20260814/` directory.

---

### Task 1: Review workspace return candidates

**Files:**
- Modify: `backend/apps/api/routes.py`
- Modify: `frontend/src/types/ai-review-b.ts`
- Test: `backend/tests/test_review_b_workspace.py`

**Interfaces:**
- Produces `permissions.canReturnCorrection: bool` and `returnableBindings: list[dict]` on `ReviewBWorkspace`.

- [ ] Write a failing test that inserts one “已提交” and one “草稿挂载” binding for the node, calls `review-workspace`, and expects only the submitted binding plus `canReturnCorrection is True`.
- [ ] Run `backend/.venv/bin/python -m pytest backend/tests/test_review_b_workspace.py -k return_correction_projection -q` and confirm missing fields fail.
- [ ] Build `returnable_bindings` from `project_bindings`, enriching each with the bound document's `materialTypeName` and `materialCategory`; add the permission from the inspection role's `review:return-correction` action.
- [ ] Add the matching frontend types.
- [ ] Run the focused test and `pnpm ts:check`; commit `feat: expose Review B return correction candidates`.

### Task 2: Atomic return and supplement mutation

**Files:**
- Modify: `backend/apps/api/routes.py`
- Modify: `frontend/src/api/aicheck/index.ts`
- Test: `backend/tests/test_review_b_workspace.py`

**Interfaces:**
- Extends `returnCorrectionApi` payload with `mode`, `opinion`, and `supplementRequirements`.
- Returns `rectificationType` and optional `opinion`.

- [ ] Write failing API tests for:
  - B `return_correction` with one valid submitted binding creates exactly one “需补正” opinion, one rectification, changes the binding/node, creates one todo, and leaves a running ReviewRun unchanged.
  - B `supplement_request` with no binding and one server-recognized missing requirement creates the opinion, supplement record, node state and todo without creating/changing a binding.
  - empty supplement request fails before any collection count changes.
  - a legacy binding-only request still succeeds without creating an opinion.
- [ ] Run the four focused tests and confirm RED on unsupported mode/opinion/supplement behavior.
- [ ] Normalize supplement items against `build_node_evidence_readiness(...)["missingRequirements"]`; allow non-empty `source="manual"` items, reject forged system items, and require at least one normalized item.
- [ ] Branch the existing mutation by mode after all validation. For B payloads create a full `ReviewOpinion` with fixed result `需补正`; create the rectification with `rectificationType`, `bindingIds`, and `supplementRequirements`; mutate bindings only in return mode; always set node status and create the responsible todo.
- [ ] Keep the legacy no-mode branch and existing response fields compatible.
- [ ] Run focused tests, `test_main_chain_e2e.py`, `test_audit_fix_regressions.py -k return`, and `test_contract.py -k return_correction`; commit `feat: atomically create Review B correction requests`.

### Task 3: Dual-mode Review B dialog

**Files:**
- Create: `frontend/src/views/AIReviewB/returnCorrection.ts`
- Create: `frontend/src/views/AIReviewB/returnCorrection.test.ts`
- Create: `frontend/src/views/AIReviewB/components/ReturnCorrectionDialog.vue`
- Modify: `frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue`

**Interfaces:**
- `createReturnCorrectionDraft(bindings, missingRequirements, defaultOpinion)` selects all candidates and chooses `return_correction` when bindings exist, otherwise `supplement_request`.
- `buildReturnCorrectionPayload(draft)` includes selected binding IDs or selected system/manual supplement items and rejects empty reason/task data.

- [ ] Write failing table-driven helper tests for submitted-binding defaults, missing-requirement defaults, newline-separated manual items, partial selection, and empty supplement validation.
- [ ] Run `pnpm test:unit` and confirm the missing helper fails.
- [ ] Implement the pure helper until tests pass.
- [ ] Build `ReturnCorrectionDialog.vue` with a required reason textarea, checkbox lists, a manual-items textarea in supplement mode, default selection on every open, inline validation, and a submit event.
- [ ] Add the independent button to the final-conclusion card. Keep it enabled when `returnableBindings` is empty, open the dialog with `missingRequirements`, confirm the affected count/assignee, call `returnCorrectionApi` with the project etag and selected evidence, close only on success, then refresh workspace.
- [ ] Run Prettier, unit tests, TypeScript, scoped ESLint/Stylelint, relevant backend tests, and `pnpm build:pro`.
- [ ] Commit `feat: add Review B return correction dialog`.

### Task 4: Completion audit

**Files:**
- Verify all files above and the spec.

- [ ] Run `backend/.venv/bin/python -m pytest backend/tests/test_review_b_workspace.py backend/tests/test_main_chain_e2e.py backend/tests/test_audit_fix_regressions.py -q`.
- [ ] Run `pnpm test:unit && pnpm ts:check && pnpm build:pro` from `frontend`.
- [ ] Check every explicit spec requirement against API responses, helper tests, component wiring, and Git diff.
- [ ] Confirm `git diff --check`, exact status, and commits; leave the unrelated audit directory untouched.
