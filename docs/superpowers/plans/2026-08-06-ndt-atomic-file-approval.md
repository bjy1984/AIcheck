# NDT Atomic File Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add NDT atomic material upload entries and let each uploaded file be adjusted and submitted for approval independently without completeness or OCR gates.

**Architecture:** Reuse project documents and node bindings. Extend upload metadata so every document has an atomic `materialTypeCode`, then create independent draft bindings to default NDT nodes 35–42. Add an NDT-specific single-document submission endpoint that validates ownership and binding scope only; the frontend renders the atomic catalog and per-file actions while OCR remains asynchronous status information.

**Tech Stack:** Vue 3, TypeScript, Element Plus, FastAPI-style Python routes, repository-backed state, Node assertion tests, pytest contract tests.

## Global Constraints

- NDT node IDs remain 35–42.
- Every file is independently editable and independently submitted.
- Upload never auto-submits.
- Completeness and OCR state never block single-file submission.
- Default node mappings are adjustable only within 35–42.
- Existing NDT film, record, and report workflows remain available.

---

### Task 1: Atomic material catalog and status helpers

**Files:**
- Create: `frontend/src/utils/ndtAtomicMaterials.ts`
- Create: `frontend/src/utils/ndtAtomicMaterials.test.ts`
- Modify: `frontend/src/types/aicheck.ts`

**Interfaces:**
- Produces: `NDT_ATOMIC_MATERIALS`, `ndtAtomicMaterialByCode(code)`, `ndtFileApprovalStatus(file)`.
- Consumes: `DocumentAsset` and `NodeFileBinding`.

- [ ] **Step 1: Write the failing catalog tests**

Assert that the catalog contains the 21 codes from the design, all default nodes are within 35–42, `ndt_entrustment` maps to `[37, 42]`, and document status aggregation returns `草稿`, `待审查`, `需补正`, or `已通过` from only that document's bindings.

- [ ] **Step 2: Run the test and verify RED**

Run: `cd frontend && pnpm tsx src/utils/ndtAtomicMaterials.test.ts`

Expected: FAIL because `ndtAtomicMaterials.ts` does not exist.

- [ ] **Step 3: Implement the catalog and helper**

Use this public shape:

```ts
export type NdtAtomicMaterial = {
  code: string
  name: string
  group: string
  defaultNodeIds: number[]
}

export const NDT_NODE_IDS = [35, 36, 37, 38, 39, 40, 41, 42] as const
export const NDT_ATOMIC_MATERIALS: NdtAtomicMaterial[] = [
  { code: 'ndt_quality_assurance_manual', name: '无损检测单位质量保证手册', group: 'R35 质量保证体系', defaultNodeIds: [35] },
  { code: 'ndt_controlled_record_form', name: '受控记录表格', group: 'R35 质量保证体系', defaultNodeIds: [35] },
  { code: 'ndt_controlled_report_form', name: '受控报告表格', group: 'R35 质量保证体系', defaultNodeIds: [35] },
  { code: 'ndt_project_personnel_appointment', name: '项目人员任命文件', group: 'R35 质量保证体系', defaultNodeIds: [35] },
  { code: 'ndt_equipment_calibration_report', name: '检测仪器及设备检定报告', group: 'R35 质量保证体系', defaultNodeIds: [35] },
  { code: 'ndt_plan', name: '无损检测方案', group: 'R36 检测方案', defaultNodeIds: [36] },
  { code: 'ndt_nonconforming_control_procedure', name: '不合格品与不符合项控制程序', group: 'R37 问题处理', defaultNodeIds: [37] },
  { code: 'ndt_entrustment', name: '无损检测委托单', group: 'R37/R42 委托资料', defaultNodeIds: [37, 42] },
  { code: 'ndt_nonconformity_notice', name: '不合格品联络单或意见书', group: 'R37 问题处理', defaultNodeIds: [37] },
  { code: 'ndt_disposition_feedback', name: '不合格品处理反馈见证文件', group: 'R37 问题处理', defaultNodeIds: [37] },
  { code: 'ndt_person_roster', name: '无损检测人员明细表', group: 'R38 人员资格', defaultNodeIds: [38] },
  { code: 'ndt_person_certificate', name: '无损检测人员资格证', group: 'R38 人员资格', defaultNodeIds: [38] },
  { code: 'ndt_practice_registration_certificate', name: '无损检测人员执业注册证', group: 'R38 人员资格', defaultNodeIds: [38] },
  { code: 'ndt_employment_contract', name: '无损检测人员劳动合同证明', group: 'R38 人员资格', defaultNodeIds: [38] },
  { code: 'ndt_procedure', name: '单项无损检测工艺文件', group: 'R39 工艺文件', defaultNodeIds: [39] },
  { code: 'ndt_operation_instruction', name: '无损检测操作指导书', group: 'R39 工艺文件', defaultNodeIds: [39] },
  { code: 'ndt_record', name: '无损检测记录', group: 'R40/R42 记录', defaultNodeIds: [40, 42] },
  { code: 'ndt_report', name: '无损检测报告', group: 'R40/R41/R42 报告', defaultNodeIds: [40, 41, 42] },
  { code: 'radiographic_film', name: '射线检测底片或数字影像', group: 'R41/R42 底片', defaultNodeIds: [41, 42] },
  { code: 'ndt_field_spot_check_record', name: '射线检测现场抽查记录', group: 'R42 现场抽查', defaultNodeIds: [42] },
  { code: 'ndt_outsourcing_contract', name: '委托无损检测合同', group: 'R42 现场抽查', defaultNodeIds: [42] }
]
export const ndtFileApprovalStatus = (file: Pick<DocumentAsset, 'bindings'>) => {
  const bindings = file.bindings || []
  if (bindings.some((item) => item.bindingStatus === '需补正')) return '需补正'
  if (bindings.length && bindings.every((item) => item.bindingStatus === '已通过')) return '已通过'
  if (bindings.some((item) => item.bindingStatus === '已提交')) return '待审查'
  return '草稿'
}
```

Add `materialTypeName?: string | null` to `DocumentAsset`.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `cd frontend && pnpm tsx src/utils/ndtAtomicMaterials.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/ndtAtomicMaterials.ts frontend/src/utils/ndtAtomicMaterials.test.ts frontend/src/types/aicheck.ts
git commit -m "feat: add NDT atomic material catalog"
```

### Task 2: Preserve atomic metadata and create per-file draft bindings

**Files:**
- Modify: `backend/libs/db/repository.py`
- Modify: `backend/apps/api/routes.py`
- Modify: `backend/tests/test_contract.py`
- Modify: `frontend/src/api/aicheck/index.ts`

**Interfaces:**
- Upload file input accepts `materialCategory`, `materialTypeCode`, `materialTypeName`, and `nodeIds`.
- Upload completion returns `documents` with per-file `documentId`, `documentVersionId`, and `bindingIds`.

- [ ] **Step 1: Write the failing backend contract test**

Create an upload session containing two files with:

```json
{
  "materialCategory": "无损检测资料",
  "materialTypeCode": "ndt_quality_assurance_manual",
  "materialTypeName": "无损检测单位质量保证手册",
  "nodeIds": [35]
}
```

Complete the session and assert that both documents preserve the metadata and each receives a distinct `草稿挂载` binding to node 35.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd backend && pytest tests/test_contract.py -k 'ndt_atomic_upload_creates_independent_draft_bindings' -q`

Expected: FAIL because upload records discard atomic metadata and completion does not create bindings.

- [ ] **Step 3: Extend repository document creation**

Add keyword parameters to `_build_document_records` and `create_upload_session` so the document and session file preserve `materialTypeCode`, `materialTypeName`, and normalized unique `nodeIds`.

- [ ] **Step 4: Add NDT upload validation and completion binding creation**

In `routes.py`, when `materialCategory == "无损检测资料"` and `materialTypeCode` is present:

```py
node_ids = sorted({int(value) for value in file.get("nodeIds") or []})
if not node_ids or any(node_id < 35 or node_id > 42 for node_id in node_ids):
    return fail(errors.VALIDATION_ERROR, request, message="无损检测资料只能关联节点35至42。")
```

On completion, create one binding per `(documentId, nodeId)` with `bindingStatus: "草稿挂载"` and return bindings grouped by document. Do not submit them.

- [ ] **Step 5: Extend frontend API types**

Update `DocumentUploadSessionFile` and `UploadSessionCompletePayload` with the atomic fields and per-document binding results.

- [ ] **Step 6: Run focused and upload regression tests**

Run: `cd backend && pytest tests/test_contract.py -k 'upload_session or ndt_atomic_upload' -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/libs/db/repository.py backend/apps/api/routes.py backend/tests/test_contract.py frontend/src/api/aicheck/index.ts
git commit -m "feat: create NDT draft bindings on atomic upload"
```

### Task 3: NDT single-file submission endpoint

**Files:**
- Modify: `backend/apps/api/routes.py`
- Modify: `backend/libs/security/actions.py`
- Modify: `backend/tests/test_contract.py`
- Modify: `frontend/src/api/aicheck/index.ts`
- Modify: `frontend/mock/aicheck/index.mock.ts`

**Interfaces:**
- Produces: `submitNdtMaterialFileApi(projectId, { documentId, bindingIds, submitterComment }, options)`.
- Route: `POST /projects/{project_id}/ndt/material-submissions`.

- [ ] **Step 1: Write failing endpoint tests**

Cover these independent cases:

1. One document with one or more draft bindings in 35–42 submits successfully.
2. Another document from the same upload remains draft.
3. `currentOcrStatus` values `排队中` and `识别失败` do not block submission.
4. Empty bindings, mixed-document bindings, cross-project documents, nodes outside 35–42, and already submitted bindings fail atomically.

- [ ] **Step 2: Run the tests and verify RED**

Run: `cd backend && pytest tests/test_contract.py -k 'ndt_material_submission' -q`

Expected: FAIL with route not found.

- [ ] **Step 3: Implement the backend endpoint**

Validate exactly one document and its selected bindings, call the normal mutation and member-scope guards, update only those bindings to `已提交`, set the affected nodes to `待审查`, and create one submission snapshot plus one inspection todo. Do not call `ndt_submission_readiness` and do not read OCR state.

- [ ] **Step 4: Register the permission and frontend client**

Map the route to `ndt:submit`, add the typed frontend API client, and add equivalent mock behavior for test-mode UI verification.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `cd backend && pytest tests/test_contract.py -k 'ndt_material_submission' -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/api/routes.py backend/libs/security/actions.py backend/tests/test_contract.py frontend/src/api/aicheck/index.ts frontend/mock/aicheck/index.mock.ts
git commit -m "feat: submit NDT files for approval independently"
```

### Task 4: Atomic upload drawer and per-file approval UI

**Files:**
- Modify: `frontend/src/views/AICheck/components/UploadSessionDrawer.vue`
- Modify: `frontend/src/views/AICheck/components/NdtWorkflowPanel.vue`
- Modify: `frontend/src/views/AICheck/Workbench.vue`
- Modify: `frontend/src/utils/acceptanceFlows.ts`
- Modify: `frontend/src/utils/acceptanceFlows.test.ts`

**Interfaces:**
- `NdtWorkflowPanel` emits `uploadMaterial(material: NdtAtomicMaterial)` and `submitMaterialFile(documentId, bindingIds)`.
- `UploadSessionDrawer` accepts atomic type and node options, and emits `{ files, nodeIds }`.

- [ ] **Step 1: Write failing frontend behavior tests**

Add pure behavior tests proving that an atomic upload action retains its material code and default nodes, that only nodes 35–42 can be selected, and that per-file submit payload contains bindings for exactly one document.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd frontend && pnpm tsx src/utils/acceptanceFlows.test.ts`

Expected: FAIL because the atomic action and single-file payload helpers do not exist.

- [ ] **Step 3: Replace the seven-class checklist**

Render the 21 catalog entries grouped by nodes 35–42. Remove class-level `已覆盖` and completeness summary. Show counts based on exact `materialTypeCode`.

- [ ] **Step 4: Extend the upload drawer**

Display atomic type and a multi-select of nodes 35–42. Preselect defaults and return selected node IDs without auto-submitting.

- [ ] **Step 5: Wire upload completion**

Send atomic metadata and node IDs for every selected file. On completion, close the drawer, refresh project data, and report that files were saved as drafts and OCR was queued.

- [ ] **Step 6: Add the per-file table actions**

For project documents with `materialCategory === "无损检测资料"`, show atomic type, rule tags, OCR state, approval state, `调整规则`, and `提交审批`. Filter submit binding IDs to the selected document only.

- [ ] **Step 7: Integrate report and film image upload**

Ensure report documents use `ndt_report` and film images use `radiographic_film`, so both appear in the same per-file list while retaining their dedicated metadata flows.

- [ ] **Step 8: Run frontend tests and type check**

Run:

```bash
cd frontend
pnpm tsx src/utils/ndtAtomicMaterials.test.ts
pnpm tsx src/utils/acceptanceFlows.test.ts
pnpm ts:check
```

Expected: all commands PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/views/AICheck/components/UploadSessionDrawer.vue frontend/src/views/AICheck/components/NdtWorkflowPanel.vue frontend/src/views/AICheck/Workbench.vue frontend/src/utils/acceptanceFlows.ts frontend/src/utils/acceptanceFlows.test.ts
git commit -m "feat: add NDT atomic upload and file approval UI"
```

### Task 5: End-to-end verification

**Files:**
- Modify if required: `frontend/e2e/aicheck-smoke.spec.ts`

**Interfaces:**
- Verifies the complete NDT user flow against mock mode and the backend contract separately.

- [ ] **Step 1: Add the failing browser scenario**

Log in as `ndt`, upload two files under the same atomic type, confirm both are drafts, adjust one file's nodes, submit only that file, and assert the second stays draft. Assert submission remains enabled while OCR is not complete.

- [ ] **Step 2: Run the scenario and verify RED before final UI wiring**

Run: `cd frontend && pnpm playwright test e2e/aicheck-smoke.spec.ts -g 'NDT atomic files submit independently'`

- [ ] **Step 3: Correct scenario wiring if the browser test exposes a mismatch**

Limit corrections to these defined contracts: upload payload contains the selected atomic metadata and node IDs; completion returns independent draft bindings; the row submit action sends only that row's document and binding IDs; OCR state is display-only. Re-run the same browser test after each correction.

- [ ] **Step 4: Run full relevant verification**

Run:

```bash
cd backend && pytest tests/test_contract.py -k 'ndt or upload_session' -q
cd ../frontend && pnpm ts:check
pnpm tsx src/utils/ndtAtomicMaterials.test.ts
pnpm tsx src/utils/acceptanceFlows.test.ts
pnpm playwright test e2e/aicheck-smoke.spec.ts -g 'NDT atomic files submit independently'
```

Expected: all commands PASS without new warnings.

- [ ] **Step 5: Visually verify the NDT workbench**

Capture and inspect the atomic catalog, upload drawer, two-file draft state, and one-file submitted state at 1280×720. Confirm labels, node selectors, status tags, and actions are visible without implying completeness.

- [ ] **Step 6: Commit**

```bash
git add frontend/e2e/aicheck-smoke.spec.ts
git commit -m "test: cover NDT atomic file approval flow"
```
