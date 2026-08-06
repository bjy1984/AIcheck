# NDT User-Facing Language Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace NDT implementation terminology and rule numbers with user-facing Chinese business language while preserving node IDs internally.

**Architecture:** Add one canonical node-ID-to-business-name mapping beside the NDT material catalog. All NDT upload, draft, rule-selection, and approval views derive visible rule labels from that mapping; backend request fields and node IDs remain unchanged.

**Tech Stack:** Vue 3, TypeScript, Element Plus, FastAPI, pytest, Node `assert`/`tsx` tests.

## Global Constraints

- The NDT interface must not display “原子资料”, “原子资料类型”, or “规则挂载”.
- Business rules must display full Chinese names and must not display `R+数字` or node-number ranges.
- Node IDs 35–42 remain unchanged in API payloads and storage.
- Upload-as-draft, pre-submit rule adjustment, asynchronous OCR, and per-file approval behavior must not change.
- Other modules such as R12 and R19 are outside this change.

---

### Task 1: Canonical NDT business-rule labels

**Files:**
- Modify: `frontend/src/utils/ndtAtomicMaterials.ts`
- Modify: `frontend/src/utils/ndtAtomicMaterials.test.ts`

**Interfaces:**
- Produces: `NDT_BUSINESS_RULE_NAMES: Record<NdtNodeId, string>`
- Produces: `ndtBusinessRuleNames(nodeIds: readonly number[]): string[]`
- Preserves: `NDT_ATOMIC_MATERIALS` codes and `defaultNodeIds`

- [ ] **Step 1: Write the failing catalog test**

Add assertions that IDs 35–42 map to the eight approved full business names and that every returned label fails `/R\d+/` matching.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm exec tsx src/utils/ndtAtomicMaterials.test.ts`

Expected: FAIL because `NDT_BUSINESS_RULE_NAMES` and `ndtBusinessRuleNames` are not exported.

- [ ] **Step 3: Add the canonical mapping and helper**

Implement the exact mapping from the approved design and replace catalog `group` strings containing rule numbers with joined full business names.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && pnpm exec tsx src/utils/ndtAtomicMaterials.test.ts`

Expected: PASS with all eight IDs mapped and no numbered display labels.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/ndtAtomicMaterials.ts frontend/src/utils/ndtAtomicMaterials.test.ts
git commit -m "refactor: add NDT business rule labels"
```

### Task 2: Replace NDT page, drawer, and API-facing terminology

**Files:**
- Create: `frontend/src/utils/ndtUserFacingLanguage.test.ts`
- Modify: `frontend/src/views/AICheck/components/NdtWorkflowPanel.vue`
- Modify: `frontend/src/views/AICheck/components/UploadSessionDrawer.vue`
- Modify: `frontend/src/views/AICheck/Workbench.vue`
- Modify: `backend/apps/api/routes.py`
- Modify: `backend/tests/test_contract.py`

**Interfaces:**
- Consumes: `ndtBusinessRuleNames(nodeIds)` from Task 1.
- Preserves: upload payload `nodeIds`, rule-adjustment endpoint, and single-file submission endpoint.

- [ ] **Step 1: Write failing user-language tests**

Create a TypeScript source-language test that reads the two NDT Vue components and asserts the rendered source contains none of `原子资料`, `原子资料类型`, `规则挂载`, or `R35` through `R42`. Extend the existing backend contract test to assert NDT validation response messages contain neither `原子` nor `规则挂载`.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:

```bash
cd frontend && pnpm exec tsx src/utils/ndtUserFacingLanguage.test.ts
cd backend && .venv/bin/pytest tests/test_contract.py -k 'ndt_atomic' -q
```

Expected: frontend test fails on current visible strings; backend test fails on current NDT validation messages.

- [ ] **Step 3: Replace visible terminology**

Use these user-facing labels:

- `无损检测资料上传`
- `资料类型`
- `适用业务规则`
- `调整适用业务规则`
- `已上传资料`

Remove the duplicate “默认挂载” column. Render checkbox and table labels with `ndtBusinessRuleNames`, while keeping node IDs as checkbox values and API payloads.

- [ ] **Step 4: Replace NDT backend user messages**

Change NDT-only validation errors, todo titles, and audit labels to “无损检测资料” and “适用业务规则”. Do not rename API fields, route paths, constants, or stored submission types.

- [ ] **Step 5: Run focused tests to verify they pass**

Run the two commands from Step 2 and confirm both exit successfully.

- [ ] **Step 6: Run regression checks**

Run:

```bash
cd frontend && pnpm ts:check
cd frontend && pnpm exec eslint src/utils/ndtAtomicMaterials.ts src/utils/ndtAtomicMaterials.test.ts src/utils/ndtUserFacingLanguage.test.ts src/views/AICheck/Workbench.vue src/views/AICheck/components/NdtWorkflowPanel.vue src/views/AICheck/components/UploadSessionDrawer.vue
cd frontend && pnpm exec stylelint src/views/AICheck/components/NdtWorkflowPanel.vue src/views/AICheck/components/UploadSessionDrawer.vue --cache-location node_modules/.cache/stylelint-ndt-copy
cd backend && .venv/bin/pytest tests/test_contract.py -k 'ndt or upload_session' -q
```

Expected: all commands exit successfully.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/utils/ndtUserFacingLanguage.test.ts frontend/src/views/AICheck/components/NdtWorkflowPanel.vue frontend/src/views/AICheck/components/UploadSessionDrawer.vue frontend/src/views/AICheck/Workbench.vue backend/apps/api/routes.py backend/tests/test_contract.py
git commit -m "fix: use business language in NDT workflow"
```
