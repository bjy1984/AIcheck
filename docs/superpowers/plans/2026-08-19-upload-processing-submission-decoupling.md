# Upload, Processing, and Submission Decoupling Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让施工方和无损检测机构在文件本体完成落库后即可首次提交，同时将 OCR、切片、向量化、自动分类和无损检测内容完整性检查作为非阻塞的后台状态与问题提示。

**Architecture:** 以“文件本体是否落库”作为上传成功的唯一事实源，并把上传状态、后台处理状态、提交状态和业务完整性状态拆成独立模型。施工方普通资料提交与无损检测单份资料提交共享文件本体校验，但保留不同页面、类别提醒和后续业务流程；无损检测报告完整性由纯函数生成结构化问题清单，提交接口只阻塞身份、对象归属、文件本体、重复/并发和非法状态。

**Tech Stack:** Vue 3, TypeScript, Vitest, Python 3, FastAPI, pytest

---

### Task 1: Split frontend upload and processing state

**Files:**
- Modify: `frontend/src/utils/documentPipelineStatus.ts`
- Modify: `frontend/src/utils/documentPipelineStatus.test.ts`
- Modify: `frontend/src/utils/documentUploadActions.ts`
- Modify: `frontend/src/utils/documentUploadActions.test.ts`
- Modify: `frontend/src/utils/ndtDisabledReason.test.ts`

**Step 1: Write failing status tests**

Add cases proving that a document with `bodyUploaded: true` is `上传成功` and can be submitted while OCR is queued, failed, or incomplete. Add independent processing expectations such as `等待处理`, `处理中`, `处理失败`, and `处理完成`. Retain the `bodyUploaded: false` case as `失败重新上传` and non-submittable.

**Step 2: Run the focused tests and confirm failure**

Run: `cd frontend && npm test -- --run src/utils/documentPipelineStatus.test.ts src/utils/documentUploadActions.test.ts src/utils/ndtDisabledReason.test.ts`

Expected: assertions for queued/failed OCR submission fail because the current model derives upload success from OCR, slicing, and vectorization.

**Step 3: Implement independent status functions**

Refactor the utility so the public model follows these rules:

```ts
export type DocumentUploadStatus = '上传中' | '上传成功' | '失败重新上传'
export type DocumentProcessingStatus = '等待处理' | '处理中' | '处理失败' | '处理完成'

export const documentUploadStatus = (file: DocumentPipelineState): DocumentUploadStatus =>
  file.bodyUploaded === false ? '失败重新上传' : '上传成功'

export const canSubmitDocument = (file: DocumentPipelineState): boolean =>
  documentUploadStatus(file) === '上传成功'
```

Derive processing status only from OCR/slice/vector fields. Keep a compatibility export only where existing callers require a staged migration, and make its semantics explicit rather than using it for submission eligibility.

**Step 4: Update action eligibility and messages**

Make contractor and NDT submit actions depend on workflow eligibility plus upload status only. OCR/processing failure should produce a non-blocking warning, not a disabled reason; only file-body upload failure should instruct re-upload.

**Step 5: Run focused tests**

Run: `cd frontend && npm test -- --run src/utils/documentPipelineStatus.test.ts src/utils/documentUploadActions.test.ts src/utils/ndtDisabledReason.test.ts`

Expected: PASS.

**Step 6: Commit**

```bash
git add frontend/src/utils/documentPipelineStatus.ts frontend/src/utils/documentPipelineStatus.test.ts frontend/src/utils/documentUploadActions.ts frontend/src/utils/documentUploadActions.test.ts frontend/src/utils/ndtDisabledReason.test.ts
git commit -m "refactor: split upload and processing status"
```

### Task 2: Preserve distinct role UIs while removing filename inference

**Files:**
- Modify: `frontend/src/views/AICheck/components/WorkbenchRoleStaticSections.vue`
- Modify: `frontend/src/views/AICheck/components/NdtWorkflowPanel.vue`
- Modify: `frontend/src/types/aicheck.ts`
- Test: existing frontend typecheck and component/unit suites

**Step 1: Add or update tests for view-facing helpers**

Where behavior is expressed through utilities, add assertions that an unclassified uploaded file displays `待识别`, retains submission eligibility, and exposes upload and processing statuses independently. Do not add a filename-pattern expectation.

**Step 2: Run the focused frontend tests and confirm the old behavior fails**

Run the Task 1 command plus any component-specific test discovered for these views.

Expected: the current contractor row still reports inferred category and uses processing state as upload state.

**Step 3: Update contractor rows and table**

Remove `inferMaterialCategory` from uploaded-file row construction. Use only backend/manual category values; otherwise render `待识别`. Keep the contractor category guidance section visible. Add separate `上传状态` and `后台处理` columns, and base submit/retry buttons only on upload status. Processing failure should display as a warning without disabling submission.

**Step 4: Update NDT rows and table**

Keep the NDT-specific page structure, report/film/record guidance, and later package actions. Add separate upload and processing fields for file rows, show `待识别` when no backend category exists, and ensure initial submit eligibility uses only upload status plus existing workflow ownership/state checks.

**Step 5: Run frontend verification**

Run:

```bash
cd frontend
npm test -- --run
npm run typecheck
```

Expected: PASS with no TypeScript errors.

**Step 6: Commit**

```bash
git add frontend/src/views/AICheck/components/WorkbenchRoleStaticSections.vue frontend/src/views/AICheck/components/NdtWorkflowPanel.vue frontend/src/types/aicheck.ts frontend/src/utils
git commit -m "feat: show independent document lifecycle states"
```

### Task 3: Allow contractor submission immediately after file landing

**Files:**
- Modify: `backend/tests/test_contract.py`
- Modify: `backend/tests/test_main_chain_e2e.py`
- Modify: `backend/apps/api/routes.py`

**Step 1: Rewrite contract tests to the new invariant**

Replace tests that require OCR/vector completion with cases proving:

```python
# current version has a content hash, while OCR is queued or failed
response = submit_project_or_bound_document(...)
assert response.status_code == 200
```

Keep or add a paired case where a document shell has no uploaded body and submission returns `409` with `DOCUMENT_BODY_MISSING`. Update the E2E OCR-failure scenario to assert that diagnostics remain visible while submission succeeds.

**Step 2: Run focused backend tests and confirm failure**

Run:

```bash
cd backend
pytest -q tests/test_contract.py -k "contractor and submission and upload"
pytest -q tests/test_main_chain_e2e.py -k "failed_ocr"
```

Expected: queued/failed pipeline submissions receive the current pipeline-blocking conflict.

**Step 3: Remove pipeline blockers from contractor submission routes**

Delete `blocked_pipeline_documents(...)` checks from both project-level and bound contractor submission paths. Retain `unuploaded_document_error(...)`, role/project authorization, current-version validation, legal state transitions, duplicate/idempotency behavior, and audit events.

**Step 4: Run the focused tests**

Run the commands from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/apps/api/routes.py backend/tests/test_contract.py backend/tests/test_main_chain_e2e.py
git commit -m "feat: decouple contractor submission from processing"
```

### Task 4: Make NDT category and bindings optional for first submission

**Files:**
- Modify: `backend/tests/test_contract.py`
- Modify: `backend/apps/api/routes.py`

**Step 1: Add failing NDT submission cases**

Add contract tests for:

- a body-uploaded NDT file with no `materialCategory`, no `materialTypeCode`, and no binding IDs submits successfully;
- a body-uploaded NDT file submits while OCR/vector processing is queued or failed;
- a document shell without a file body is rejected with `DOCUMENT_BODY_MISSING`;
- explicitly supplied stale, cross-document, cross-project, or invalid-state binding IDs remain rejected;
- repeat submission remains rejected or idempotently resolved according to the existing contract.

**Step 2: Run focused tests and confirm failure**

Run: `cd backend && pytest -q tests/test_contract.py -k "ndt and atomic and submission"`

Expected: unclassified/unbound or processing-incomplete documents are rejected by current category, binding, or pipeline gates.

**Step 3: Refactor the NDT atomic submission endpoint**

Change `POST /projects/{project_id}/ndt/material-submissions` so it:

1. validates project, role, document ownership/current version and document-body presence;
2. treats category and type as optional metadata;
3. validates binding IDs only when the caller supplies them;
4. allows no binding IDs and routes the item to the existing fallback/ordinary material pool;
5. does not inspect OCR, chunk, vector, automatic classification, or business content for first-submission eligibility;
6. preserves duplicate, illegal-state, historical-version, and authorization checks.

**Step 4: Run focused tests**

Run the command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/apps/api/routes.py backend/tests/test_contract.py
git commit -m "feat: accept unclassified NDT material submissions"
```

### Task 5: Convert NDT readiness blockers into post-submit completeness issues

**Files:**
- Create: `backend/libs/ndt_completeness.py`
- Create: `backend/tests/test_ndt_completeness.py`
- Modify: `backend/tests/test_contract.py`
- Modify: `backend/apps/api/routes.py`

**Step 1: Write pure completeness-engine tests**

Cover the existing report rules as classified issues rather than blockers:

- OCR pending/failure and missing extracted fields become `processingIssues`;
- missing report number, method, RT detection ratio, grade-like conclusion, linked film, or submitted film become `businessIssues`;
- field coordinates/bounding boxes and ambiguous content requiring review become `manualChecks`;
- complete reports return no business issue while preserving any independent manual check.

Each issue must have a stable `code`, human-readable `message`, and relevant object ID.

**Step 2: Run the pure tests and confirm failure**

Run: `cd backend && pytest -q tests/test_ndt_completeness.py`

Expected: import failure because the completeness module does not exist.

**Step 3: Implement the pure completeness module**

Implement aggregation without route/database dependencies. Return a stable schema:

```python
{
    "schemaVersion": "ndt-business-completeness-v1",
    "completenessStatus": "待补充",
    "processingIssues": [],
    "businessIssues": [],
    "manualChecks": [],
    "issueCount": 0,
}
```

`completenessStatus` must reflect the most actionable remaining class while never serving as initial-submit eligibility.

**Step 4: Add a failing route contract test**

Create an NDT report with incomplete OCR/business fields but a valid uploaded file body, call `POST /projects/{project_id}/ndt/submissions`, and assert success plus a structured `ndtCompleteness` snapshot. Add a body-missing counterpart that still fails.

**Step 5: Integrate non-blocking completeness into package confirmation**

Replace `ndt_submission_readiness` rejection with completeness calculation. Continue to block invalid IDs, project/tenant visibility, illegal report/film states, missing file bodies, duplicates, and concurrent state conflicts. Store and return the issue snapshot under `ndtCompleteness`; if the compatibility field `ndtReadiness` remains, mark it non-blocking and derive it from the same issue data so there is only one source of truth.

**Step 6: Run NDT tests**

Run:

```bash
cd backend
pytest -q tests/test_ndt_completeness.py
pytest -q tests/test_contract.py -k "ndt"
```

Expected: PASS.

**Step 7: Commit**

```bash
git add backend/libs/ndt_completeness.py backend/tests/test_ndt_completeness.py backend/apps/api/routes.py backend/tests/test_contract.py
git commit -m "feat: report NDT completeness after submission"
```

### Task 6: Cross-layer regression and delivery verification

**Files:**
- Modify only files required by failures attributable to Tasks 1-5

**Step 1: Run backend regression suites**

Run:

```bash
cd backend
pytest -q tests/test_contract.py tests/test_main_chain_e2e.py tests/test_ndt_completeness.py
```

Expected: PASS.

**Step 2: Run frontend regression suites**

Run:

```bash
cd frontend
npm test -- --run
npm run typecheck
```

Expected: PASS.

**Step 3: Run repository quality gates**

Discover the repository-supported lint/contract commands from package scripts and project documentation, then run the applicable non-destructive checks. Always run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors, no unexpected generated artifacts, and only intentional changes before the final commit.

**Step 4: Verify the acceptance matrix explicitly**

Confirm with automated evidence that:

| Scenario | Expected |
|---|---|
| file body uploaded, processing queued/failed | first submission succeeds |
| category/type absent | first submission succeeds |
| NDT content fields incomplete | submission succeeds and returns issues |
| file body absent | submission fails |
| unauthorized/cross-project/invalid state | submission fails |
| duplicate or concurrent submission | existing protection remains |
| role UI | contractor and NDT layouts remain distinct with category reminders |
| document row | upload status and processing status appear independently |

**Step 5: Commit any regression-only fixes**

```bash
git add <only-files-changed-by-regression-fixes>
git commit -m "test: cover decoupled document submission flow"
```

**Step 6: Final handoff**

Report changed behavior, the exact verification commands and results, any intentionally deferred second/third-phase work, and links to the design and implementation plan.
