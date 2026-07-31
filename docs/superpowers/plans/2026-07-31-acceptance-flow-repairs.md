# Acceptance Flow Repairs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the four broken acceptance flows for structured NDT films, inspection-authored evidence, the R69 manual evaluation package, and contractor multi-node submissions.

**Architecture:** Keep the existing backend domain routes and add the missing frontend orchestration. Put deterministic UI decisions in small pure TypeScript helpers, retain explicit NDT film registration, and configure R69 through the engineering business pack so node requirements, readiness, and the human-decision gate use one source of truth.

**Tech Stack:** Vue 3 `<script setup>`, TypeScript 5.7, Element Plus, Axios API wrappers, FastAPI, pytest, YAML business packs, Node `assert` executed with `esno`, Playwright/in-app browser regression.

## Global Constraints

- Do not infer film metadata from filenames and do not weaken the RT report-to-film linkage gate.
- Inspection evidence upload must create real documents, bind the uploaded versions to the current node with usage `监检资料`, and submit the exact created bindings.
- R69 must require `REQ-69-01` and must retain `automatedDecisionAllowed: false`; only inspection personnel may save the final evaluation.
- Contractor direct submission must submit every pending binding already attached to that document and must never create an implicit binding to the currently viewed node.
- Existing project, organization, person, certificate, drawing, and file numbering must be reused in browser regression.
- JPG site photos are valid upload evidence without OCR text; their final assessment remains manual.

---

### Task 1: Pure frontend acceptance-flow decisions

**Files:**
- Create: `frontend/src/utils/acceptanceFlows.ts`
- Create: `frontend/src/utils/acceptanceFlows.test.ts`

**Interfaces:**
- Consumes: `DocumentAsset` and `NodeFileBinding` from `@/types/aicheck`.
- Produces: `resolveNdtMaterialAction(category, key)`, `documentBindingSummary(file)`, `submittableDocumentBindings(file)`, and `buildDocumentSubmissionPayload(file)`.

- [ ] **Step 1: Write the failing behavior test**

Create a Node-assert test with literal fixtures proving these breaks:

```ts
assert.equal(resolveNdtMaterialAction('底片与影像资料', 'register'), 'register-film')
assert.equal(resolveNdtMaterialAction('底片与影像资料', 'upload'), 'upload-material')
assert.equal(resolveNdtMaterialAction('检测报告', 'upload'), 'upload-report')

const file = documentWithBindings([
  binding('B-R21', 21, '草稿挂载'),
  binding('B-R24', 24, '已提交'),
  binding('B-R69', 69, '需补正')
])
assert.equal(documentBindingSummary(file), '需补正')
assert.deepEqual(buildDocumentSubmissionPayload(file), {
  nodeIds: [21, 69],
  bindingIds: ['B-R21', 'B-R69']
})
assert.equal(buildDocumentSubmissionPayload(documentWithBindings([])), undefined)
```

Fixtures must contain every `NodeFileBinding` field, so a partial double cannot hide a contract change.

- [ ] **Step 2: Run the test and verify RED**

Run: `cd frontend && pnpm exec esno src/utils/acceptanceFlows.test.ts`

Expected: FAIL because `acceptanceFlows.ts` does not exist.

- [ ] **Step 3: Implement the deterministic rules**

Implement literal status precedence and stable binding order:

```ts
export const submittableDocumentBindings = (file: DocumentAsset) =>
  (file.bindings || []).filter((item) => ['草稿挂载', '需补正'].includes(item.bindingStatus))

export const buildDocumentSubmissionPayload = (file: DocumentAsset) => {
  const bindings = submittableDocumentBindings(file)
  if (!bindings.length) return undefined
  return {
    nodeIds: Array.from(new Set(bindings.map((item) => item.nodeId))).sort((a, b) => a - b),
    bindingIds: bindings.map((item) => item.id)
  }
}
```

`documentBindingSummary` returns `未关联`, `需补正`, `待提交`, `审核中`, or `已通过` using all bindings. `resolveNdtMaterialAction` returns `register-film`, `upload-report`, `upload-material`, or `feedback`.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `cd frontend && pnpm exec esno src/utils/acceptanceFlows.test.ts`

Expected: exit 0 with all literal assertions completed.

- [ ] **Step 5: Commit the helper and its regression test**

```bash
git add frontend/src/utils/acceptanceFlows.ts frontend/src/utils/acceptanceFlows.test.ts
git commit -m "test: cover acceptance flow decisions"
```

### Task 2: Explicit NDT film registration entry

**Files:**
- Modify: `frontend/src/views/AICheck/components/NdtWorkflowPanel.vue`
- Modify: `frontend/src/utils/acceptanceFlows.test.ts`

**Interfaces:**
- Consumes: `resolveNdtMaterialAction` from Task 1 and the existing `createFilm` event.
- Produces: a visible `新增底片编号` action and a validated form emitting `Pick<NdtFilm, 'filmNo' | 'weldNo' | 'method'> & Partial<NdtFilm>`.

- [ ] **Step 1: Add the failing routing assertions**

Add assertions that the two film actions are distinct and that the report upload still routes to `upload-report`. Also add a literal valid payload fixture containing `filmNo`, `weldNo`, `method`, `pipelineNo`, `reportNo`, `filmPackageNo`, `imageFileName`, `standardCode`, `evaluationLevel`, `evaluatorName`, and `reviewerName`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd frontend && pnpm exec esno src/utils/acceptanceFlows.test.ts`

Expected: FAIL until the new `register` action branch is defined.

- [ ] **Step 3: Add the form and event wiring**

In `NdtWorkflowPanel.vue`:

- Extend `NdtMaterialAction` with `{ key: 'register'; label: '新增底片编号'; category: '底片与影像资料' }`.
- Put both `新增底片编号` and `上传底片/影像` in the film row.
- Add an `ElDialog` with required `底片编号`, `焊口编号`, and `检测方法`, plus the traceability fields listed above.
- Validate required fields with `ElForm`; on success emit `createFilm` with trimmed values and close the dialog.
- Route actions through `resolveNdtMaterialAction`, preserving `uploadReport`, `uploadMaterial`, and feedback scrolling.
- Display `filmError` in an `ElAlert` near the form so API failures remain actionable.

- [ ] **Step 4: Verify helper, type check, and build**

Run:

```bash
cd frontend
pnpm exec esno src/utils/acceptanceFlows.test.ts
pnpm ts:check
pnpm build:test
```

Expected: all commands exit 0; the build contains separate film registration and film-image upload controls.

- [ ] **Step 5: Commit the NDT UI**

```bash
git add frontend/src/views/AICheck/components/NdtWorkflowPanel.vue frontend/src/utils/acceptanceFlows.test.ts
git commit -m "feat: expose structured NDT film registration"
```

### Task 3: Inspection-authored attachment upload, binding, and submission

**Files:**
- Modify: `frontend/src/api/aicheck/index.ts`
- Modify: `frontend/src/views/AICheck/Workbench.vue`
- Modify: `backend/tests/test_contract.py`

**Interfaces:**
- Produces API wrappers `createInspectionAttachmentUploadSessionApi(projectId, nodeId, files, options)` and `bindInspectionDocumentsApi(projectId, nodeId, bindings, options)`.
- Uses existing signed PUT, `completeDocumentUploadSessionApi`, and `submitNodePackageApi`.
- The binding response uses `affectedIds` as the exact submission `bindingIds`.

- [ ] **Step 1: Write the failing backend integration test**

Add `test_inspection_attachment_can_be_uploaded_bound_and_submitted_to_current_node` to `backend/tests/test_contract.py`. The test must:

1. POST one JPG file to `/projects/{project_id}/inspection/nodes/21/attachments` as `inspection`.
2. PUT real bytes to the returned signed URL and complete the upload.
3. POST the returned document/version to `/inspection/nodes/21/file-bindings` with usage `监检资料`.
4. Submit exactly the returned `affectedIds` to `/submissions`.
5. Assert source organization is the inspection organization, binding status is `已提交`, node 21 is `待审查`, and the JPG can complete without extracted OCR text.
6. Assert a contractor request to the inspection attachment route is `FORBIDDEN`.

- [ ] **Step 2: Run the focused backend test and verify RED**

Run: `cd backend && .venv/bin/pytest tests/test_contract.py::test_inspection_attachment_can_be_uploaded_bound_and_submitted_to_current_node -q`

Expected: FAIL on the missing role-specific permission or lost attachment context; record the actual failure before changing production code.

- [ ] **Step 3: Make the backend route contract complete**

Keep the existing routes and make only the failing contract change:

- Preserve every file's `materialCategory`, defaulting to `监检现场补充证据`.
- Enforce inspection role plus `file:upload`, `file:bind`, and `submission:submit` through existing guards and node scope.
- Preserve `affectedIds` from `bind_documents`; do not invent document IDs or bindings.
- Do not require OCR fields for JPG completion.

- [ ] **Step 4: Run the backend test and verify GREEN**

Run: `cd backend && .venv/bin/pytest tests/test_contract.py::test_inspection_attachment_can_be_uploaded_bound_and_submitted_to_current_node -q`

Expected: PASS.

- [ ] **Step 5: Add frontend API wrappers and orchestration**

In `Workbench.vue`, add `uploadDrawerMode: 'project' | 'inspection'` and `handleOpenInspectionUploadDrawer()`.

For inspection mode, execute exactly:

```text
create inspection attachment session
→ signed PUT for each selected file
→ complete the session
→ bind all returned document/version pairs to activeNodeId with usage 监检资料
→ submit bindRes.data.affectedIds for activeNodeId
→ refresh project bundle, audit workspace, and submission history
```

Show `上传监检资料` only when `role === 'inspection'`, the node workspace is active, the project is writable, and the role has `file:upload`. Keep the drawer open and show the stage-specific error unless all stages succeed.

- [ ] **Step 6: Verify frontend and focused backend behavior**

Run:

```bash
cd frontend
pnpm ts:check
pnpm build:test
cd ../backend
.venv/bin/pytest tests/test_contract.py::test_inspection_attachment_can_be_uploaded_bound_and_submitted_to_current_node -q
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit the inspection flow**

```bash
git add frontend/src/api/aicheck/index.ts frontend/src/views/AICheck/Workbench.vue backend/tests/test_contract.py
git commit -m "feat: add inspection evidence upload flow"
```

### Task 4: R69 required evidence and manual-decision boundary

**Files:**
- Modify: `backend/business_packs/engineering_inspection_v1/nodes.yaml`
- Modify: `backend/tests/test_business_pack.py`
- Modify: `backend/tests/test_contract.py`

**Interfaces:**
- Produces `REQ-69-01` using existing material type `quality_system_document` and action `file:bind`.
- Retains R69 `executionMode: manual_evaluation` and `automatedDecisionAllowed: false`.

- [ ] **Step 1: Write the failing business-pack test**

Extend `test_engineering_pack_has_complete_standard_clause_packages_and_atomic_checks` or add a focused test with literal assertions:

```python
r69_node = next(node for node in pack["nodes"] if int(node["nodeId"]) == 69)
assert "file:bind" in r69_node["actions"]
assert r69_node["requiredMaterials"] == [{
    "id": "REQ-69-01",
    "materialTypeCode": "quality_system_document",
    "name": "施工单位质量保证体系实施状况评价工作流记录",
    "requiredType": "必传",
    "responsibleParty": "监检人员现场补充",
    "applicability": "始终适用",
    "note": "覆盖当前项目、R01-R68状态、评价人员、评价日期、评价结果和签发信息。",
}]
```

Keep the existing assertion that R69 automated decisions are false.

- [ ] **Step 2: Run the business-pack test and verify RED**

Run: `cd backend && .venv/bin/pytest tests/test_business_pack.py -q`

Expected: FAIL because R69 has no required material and no `file:bind` action.

- [ ] **Step 3: Configure R69**

Add the exact requirement above to node 69 in `nodes.yaml`. Do not change `rules.yaml` decision mode. Use the existing source standard and manual-evaluation wording.

- [ ] **Step 4: Add the runtime contract test**

Add a contract assertion that the R69 node package returns one requirement with ID `REQ-69-01`, reports progress `0/1` before evidence, and refuses a positive human result without confirmed evidence. Reuse the inspection upload flow from Task 3 to attach the existing R69 XLSX and assert the binding is visible; the automated review must remain advisory/manual.

- [ ] **Step 5: Run pack and contract tests and verify GREEN**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_business_pack.py -q
.venv/bin/pytest tests/test_contract.py -q -k 'r69 or inspection_attachment'
```

Expected: all selected tests pass; R69 still cannot be auto-decided.

- [ ] **Step 6: Commit the R69 configuration**

```bash
git add backend/business_packs/engineering_inspection_v1/nodes.yaml backend/tests/test_business_pack.py backend/tests/test_contract.py
git commit -m "feat: require R69 evaluation workflow evidence"
```

### Task 5: Contractor multi-node direct submission and aggregate status

**Files:**
- Modify: `frontend/src/views/AICheck/Workbench.vue`
- Modify: `frontend/src/views/AICheck/components/WorkbenchRoleStaticSections.vue`
- Modify: `frontend/src/views/AICheck/components/NodePackagePanel.vue`
- Modify: `frontend/src/utils/acceptanceFlows.test.ts`
- Modify: `backend/tests/test_contract.py`

**Interfaces:**
- Consumes: `buildDocumentSubmissionPayload` and `documentBindingSummary` from Task 1.
- Produces: direct submission payload containing only the file's actual pending `bindingIds` and their deduplicated `nodeIds`.

- [ ] **Step 1: Extend the failing helper test**

Add literal cases for no binding, all submitted, mixed submitted/draft, passed/correction, and duplicate node IDs. Assert that output ordering is stable and that submitted/passed bindings are excluded from a new submission.

- [ ] **Step 2: Run the helper test and verify RED**

Run: `cd frontend && pnpm exec esno src/utils/acceptanceFlows.test.ts`

Expected: FAIL for at least the mixed or duplicate-node case before the integration change.

- [ ] **Step 3: Use the helpers in all contractor displays**

- In `Workbench.vue`, compute the summary pending count from `documentBindingSummary(file)`.
- In `WorkbenchRoleStaticSections.vue`, remove first-binding status decisions and show the aggregate result; show all related node IDs in `relationNode`.
- In `NodePackagePanel.vue`, use the same aggregate status for the project-pool file row.

- [ ] **Step 4: Fix direct submission payload**

`handleSubmitProjectFile(documentId)` must locate the document in `nodePackage.projectFiles`, call `buildDocumentSubmissionPayload`, and send:

```ts
{
  nodeIds: payload.nodeIds,
  bindingIds: payload.bindingIds,
  batchName: `${file.fileName} 多节点文件提交`,
  submitterComment: '从项目文件库提交该文件的全部待提交挂载。'
}
```

Do not send `documentIds` or the active node. If the file is unbound, warn `请先关联审核环节`; if it has no pending bindings, warn `该文件没有待提交或待补正的挂载`.

- [ ] **Step 5: Add backend multi-node exact-binding regression**

Create a document with bindings on nodes 21, 24, and 69, mark node 24 binding `已提交`, submit only node 21 and 69 binding IDs, then assert those two become `已提交`, node 24 remains unchanged, no active-node binding is created, and the returned submission lists exactly node IDs `[21, 69]`.

- [ ] **Step 6: Run focused tests, type check, and build**

Run:

```bash
cd frontend
pnpm exec esno src/utils/acceptanceFlows.test.ts
pnpm ts:check
pnpm build:test
cd ../backend
.venv/bin/pytest tests/test_contract.py -q -k 'multi_node or inspection_attachment or r69'
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit contractor consistency repairs**

```bash
git add frontend/src/views/AICheck/Workbench.vue frontend/src/views/AICheck/components/WorkbenchRoleStaticSections.vue frontend/src/views/AICheck/components/NodePackagePanel.vue frontend/src/utils/acceptanceFlows.test.ts backend/tests/test_contract.py
git commit -m "fix: submit actual document bindings"
```

### Task 6: Full automated and real-page acceptance regression

**Files:**
- Modify only if a regression exposes a product defect: files already listed in Tasks 2–5.
- Evidence source: `files/测试说明.md` and its role-specific source directories.

**Interfaces:**
- Produces reproducible evidence that all four user-visible flows work on project `QX201903S-13-Y`.

- [ ] **Step 1: Run the complete automated verification set**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_business_pack.py tests/test_contract.py -q
cd ../frontend
pnpm exec esno src/utils/acceptanceFlows.test.ts
pnpm ts:check
pnpm build:test
```

Expected: every command exits 0 with no skipped targeted regression.

- [ ] **Step 2: Restart local services from the repaired branch**

Restart backend on `127.0.0.1:8000` and frontend live mode on `127.0.0.1:4100`, preserving the in-app browser tab for handoff. Confirm `/api/health` and the login page respond before testing.

- [ ] **Step 3: Regress the NDT flow in the real page**

Login as `ndt`, open the existing project, select `新增底片编号`, register a unique RT film using the file package's weld/project numbering, upload the matching JPG from the NDT role directory, then upload an RT PDF and select the new film. Assert the report is created and its detail lists the new film ID.

- [ ] **Step 4: Regress inspection evidence in R21 and R69**

Login as `inspection`:

- At R21 upload the role-directory JPG through `上传监检资料`; assert it is bound and submitted although OCR has no text.
- At R69 upload the role-directory XLSX; assert the requirement appears as `1/1` or as evidence awaiting manual confirmation, and assert no positive conclusion is generated automatically.
- Confirm the same upload control is present for R24, R28, R30, R44, and R48–R53.

- [ ] **Step 5: Regress contractor multi-node submission**

Login as `contractor`, upload or select one file, associate it with at least two test nodes, and submit from the file row while a different node is active. Assert every selected pending binding becomes `已提交`, the unrelated active node receives no new binding, and the file list no longer reports it as pending.

- [ ] **Step 6: Inspect final repository state**

Run:

```bash
git diff --check
git status --short
git log --oneline --decorate -8
```

Expected: no unintended generated files are staged; the runtime-only `backend/.venv` symlink may remain untracked while services run.

- [ ] **Step 7: Commit any regression-only correction and publish**

If Step 3–5 required a correction, rerun the exact failing automated test first, commit only the scoped files, push `codex/r01-r69-acceptance-pack-pr`, and update the existing pull request. Do not mark the goal complete until the visible browser state proves all four flows.
