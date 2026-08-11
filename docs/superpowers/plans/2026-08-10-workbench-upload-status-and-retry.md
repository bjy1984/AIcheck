# Workbench Upload Status and Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make contractor and NDT workbenches expose only `上传中`, `上传成功`, and clickable `失败重新上传`, reuse the stored original file for retry, and reject submission until the full document pipeline succeeds.

**Architecture:** Keep detailed OCR/slice/vector state in the backend, but map it to a shared business-facing frontend state. Add a document retry endpoint that validates a failed current version, verifies its stored original, resets derived artifacts through the existing knowledge-file pipeline helper, and dispatches one parse task. Enforce the same completed-pipeline predicate in both contractor and NDT submission routes so the frontend cannot be bypassed.

**Tech Stack:** FastAPI, pytest, in-memory repository and task dispatcher; Vue 3, TypeScript, Element Plus, Node test runner.

## Global Constraints

- Contractor and NDT workbenches show only `上传中`, `上传成功`, and `失败重新上传` for document processing.
- A document is `上传成功` only when OCR is one of `已识别`, `人工修正`, or `抽取不完整`, slice status is `已切片`, and vector status is `已向量化`.
- Any failed internal stage maps to `失败重新上传`; every other incomplete or unknown combination maps to `上传中`.
- Retry reuses the current stored original and current `documentVersionId`; it does not create or copy a document/version.
- Contractor and NDT submission APIs must reject documents that are not fully processed.
- FDE and knowledge-management screens keep their technical status detail.

---

### Task 1: Shared business upload state

**Files:**
- Modify: `frontend/src/utils/documentPipelineStatus.ts`
- Modify: `frontend/src/utils/documentPipelineStatus.test.ts`

**Interfaces:**
- Consumes: `DocumentPipelineState { currentOcrStatus?, sliceStatus?, vectorStatus? }`.
- Produces: `DocumentUploadStatus = '上传中' | '上传成功' | '失败重新上传'`, `documentPipelineStatus(file): DocumentUploadStatus`, and `isDocumentUploadSuccessful(file): boolean`.

- [ ] **Step 1: Replace expectations with the business-facing state matrix**

```ts
const cases = [
  [{ currentOcrStatus: '排队中' }, '上传中'],
  [{ currentOcrStatus: '识别中' }, '上传中'],
  [{ currentOcrStatus: '已识别', sliceStatus: '切片中' }, '上传中'],
  [{ currentOcrStatus: '已识别', sliceStatus: '已切片', vectorStatus: '向量化中' }, '上传中'],
  [{ currentOcrStatus: '已识别', sliceStatus: '已切片', vectorStatus: '已向量化' }, '上传成功'],
  [{ currentOcrStatus: '人工修正', sliceStatus: '已切片', vectorStatus: '已向量化' }, '上传成功'],
  [{ currentOcrStatus: '已识别', sliceStatus: '切片失败' }, '失败重新上传'],
  [{ currentOcrStatus: '已识别', sliceStatus: '已切片', vectorStatus: '向量化失败' }, '失败重新上传'],
  [{ currentOcrStatus: '未知状态' }, '上传中']
] as const
```

Add assertions that `isDocumentUploadSuccessful` is true only for the complete cases.

- [ ] **Step 2: Run the unit test and verify the old technical labels fail**

Run: `cd frontend && pnpm exec esno src/utils/documentPipelineStatus.test.ts`

Expected: FAIL because current implementation returns values such as `排队中`, `OCR 中`, and `已完成`.

- [ ] **Step 3: Implement the minimal status predicate and mapping**

```ts
export type DocumentUploadStatus = '上传中' | '上传成功' | '失败重新上传'

export const isDocumentUploadSuccessful = (file: DocumentPipelineState): boolean =>
  ['已识别', '人工修正', '抽取不完整'].includes(String(file.currentOcrStatus || '')) &&
  String(file.sliceStatus || '') === '已切片' &&
  String(file.vectorStatus || '') === '已向量化'

export const documentPipelineStatus = (file: DocumentPipelineState): DocumentUploadStatus => {
  const statuses = [file.currentOcrStatus, file.sliceStatus, file.vectorStatus].map((value) =>
    String(value || '')
  )
  if (statuses.some((status) => status.includes('失败'))) return '失败重新上传'
  return isDocumentUploadSuccessful(file) ? '上传成功' : '上传中'
}
```

- [ ] **Step 4: Run the focused unit test**

Run: `cd frontend && pnpm exec esno src/utils/documentPipelineStatus.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit the state mapping**

```bash
git add frontend/src/utils/documentPipelineStatus.ts frontend/src/utils/documentPipelineStatus.test.ts
git commit -m "feat: simplify workbench upload states"
```

### Task 2: Stored-original retry endpoint

**Files:**
- Modify: `backend/apps/api/routes.py`
- Modify: `backend/libs/security/actions.py`
- Modify: `backend/tests/test_contract.py`

**Interfaces:**
- Consumes: `project_document_original_context`, `project_document_storage_object`, `project_document_local_original_path`, `dispatch_knowledge_file_ocr_pipeline`, `mutation_guard`, and `idempotent`.
- Produces: `POST /projects/{project_id}/documents/{document_id}/retry-upload`, returning `documentId`, `documentVersionId`, `uploadStatus: '上传中'`, and `queuedTask`.

- [ ] **Step 1: Add a failing endpoint contract test**

Create a failed document/version/knowledge-file fixture in `test_contract.py`, retain copies of its IDs and bindings, monkeypatch `task_dispatcher.dispatch_parse_document`, and assert:

```python
response = client.post(
    f"/projects/{project_id}/documents/{document_id}/retry-upload",
    headers={
        "X-Role": "contractor",
        "X-User-Id": "USER-CONTRACTOR-001",
        "Idempotency-Key": "retry-failed-upload-once",
    },
)
result = assert_ok(response)
assert result["documentId"] == document_id
assert result["documentVersionId"] == version_id
assert result["uploadStatus"] == "上传中"
assert repo.find_one("documents", document_id)["currentOcrStatus"] == "识别中"
assert repo.find_one("versions", version_id)["sliceStatus"] == "未切片"
assert repo.find_one("versions", version_id)["vectorStatus"] == "待向量化"
assert repo.find_one("knowledge_files", knowledge_file_id)["chunkCount"] == 0
assert existing_binding_ids == [item["id"] for item in document_bindings(project_id, document_id)]
assert dispatched == [(document_id, version_id, expected_storage_url, file_name)]
```

Add rejection cases for a non-failed document, a cross-project document, an owner role, and a missing local/object-storage original. Replay the same idempotency key and assert only one dispatch.

- [ ] **Step 2: Run the endpoint tests and verify the route is missing**

Run: `cd backend && pytest tests/test_contract.py -k 'retry_failed_upload' -q`

Expected: FAIL with a not-found response or missing route contract.

- [ ] **Step 3: Register retry permission and implement validation**

Add the action mapping:

```python
("POST", r"/projects/[^/]+/documents/[^/]+/retry-upload$", "file:upload"),
```

In the route, call `mutation_guard`, load the project-owned current document/version, require a contractor or NDT role, require at least one failed OCR/slice/vector status, and locate the matching `knowledge_files` record. Verify `local://` storage with `project_document_local_original_path`; verify MinIO-style storage with `object_storage.object_metadata(bucket, key)`. Return `VALIDATION_ERROR` with `原文件已不存在，请重新选择本地文件上传。` if neither exists.

- [ ] **Step 4: Reset derived state through the existing pipeline helper**

Call:

```python
queued_task = dispatch_knowledge_file_ocr_pipeline(
    knowledge_file,
    reason="用户从工作台重新上传失败文件",
)
repo.add_audit("重新上传失败文件", "Document", document_id)
```

Return the stable response fields and use `idempotent(..., fingerprint_source={"documentId": document_id, "versionId": version["id"]})`. Set scoped persistence records for the document, version, knowledge file/task, derived chunks, and OCR pipeline records touched by the helper.

- [ ] **Step 5: Run focused backend tests**

Run: `cd backend && pytest tests/test_contract.py -k 'retry_failed_upload' -q`

Expected: PASS.

- [ ] **Step 6: Commit the retry endpoint**

```bash
git add backend/apps/api/routes.py backend/libs/security/actions.py backend/tests/test_contract.py
git commit -m "feat: retry failed uploads from stored originals"
```

### Task 3: Backend submission gate

**Files:**
- Modify: `backend/apps/api/routes.py`
- Modify: `backend/tests/test_contract.py`

**Interfaces:**
- Produces: `document_upload_pipeline_complete(document): bool` using the current document, version, and knowledge file; both contractor and NDT submission routes call it before mutating submission state.

- [ ] **Step 1: Convert the existing NDT no-gate test into failure/success coverage**

Replace `test_ndt_atomic_documents_submit_independently_without_ocr_gate` with assertions that queued and failed documents return `VALIDATION_ERROR`, leave bindings in `草稿挂载`, and create no submission. Then set OCR/slice/vector to the complete combination and assert the same request succeeds.

Add contractor project-pool and binding-based submission cases that are rejected while incomplete and accepted after the same complete combination.

- [ ] **Step 2: Run the submission tests and verify incomplete files currently pass**

Run: `cd backend && pytest tests/test_contract.py -k 'submission_requires_upload_success or atomic_documents_require_upload_success' -q`

Expected: FAIL because current routes do not gate on the document pipeline.

- [ ] **Step 3: Implement one shared backend predicate**

```python
def document_upload_pipeline_complete(document: dict[str, Any]) -> bool:
    version_id = str(document.get("currentVersionId") or "")
    version = repo.find_one("versions", version_id) or {}
    knowledge_file = next(
        (item for item in repo.state.get("knowledge_files", []) if str(item.get("documentVersionId") or "") == version_id),
        {},
    )
    ocr_status = str(document.get("currentOcrStatus") or version.get("ocrStatus") or knowledge_file.get("ocrStatus") or "")
    slice_status = str(knowledge_file.get("sliceStatus") or version.get("sliceStatus") or "")
    vector_status = str(knowledge_file.get("vectorStatus") or version.get("vectorStatus") or "")
    return ocr_status in {"已识别", "人工修正", "抽取不完整"} and slice_status == "已切片" and vector_status == "已向量化"
```

Before either submission mutation, collect affected document IDs and return `VALIDATION_ERROR` with `文件上传处理尚未成功，暂不能提交。` plus `incompleteDocumentIds` when any predicate is false.

- [ ] **Step 4: Run focused and neighboring submission tests**

Run: `cd backend && pytest tests/test_contract.py -k 'submission_requires_upload_success or atomic_documents_require_upload_success or ndt_atomic' -q`

Expected: PASS.

- [ ] **Step 5: Commit the backend gate**

```bash
git add backend/apps/api/routes.py backend/tests/test_contract.py
git commit -m "fix: require completed uploads before submission"
```

### Task 4: Frontend retry API and contractor workbench

**Files:**
- Modify: `frontend/src/api/aicheck/index.ts`
- Create: `frontend/src/utils/documentUploadActions.ts`
- Create: `frontend/src/utils/documentUploadActions.test.ts`
- Modify: `frontend/src/views/AICheck/components/WorkbenchRoleStaticSections.vue`
- Modify: `frontend/src/views/AICheck/Workbench.vue`

**Interfaces:**
- Produces: `retryDocumentUploadApi(projectId, documentId, options)` and `file-retry-upload` event from `WorkbenchRoleStaticSections`.
- Consumes: Task 1 status/predicate and Task 2 endpoint.

- [ ] **Step 1: Add failing business-action assertions**

Add table-driven assertions that contractor rows are submittable only when their workflow status is eligible and upload status is `上传成功`, and retryable only when upload status is `失败重新上传`.

- [ ] **Step 2: Run the source-level test and verify the retry interaction is absent**

Run: `cd frontend && pnpm exec esno src/utils/documentUploadActions.test.ts`

Expected: FAIL because the business-action utility does not exist.

- [ ] **Step 3: Add the API and contractor event**

```ts
export const retryDocumentUploadApi = (
  projectId: string,
  documentId: string,
  options?: MutationHeaderOptions
) => request.post({
  url: `/api/projects/${projectId}/documents/${documentId}/retry-upload`,
  headers: mutationHeaders(options)
})
```

Implement `canSubmitDocumentUpload(workflowEligible, uploadStatus)` and `canRetryDocumentUpload(uploadStatus)`. Add `file-retry-upload: [documentId: string]` to the component emits. Render `失败重新上传` as a link button in the processing-status cell; all other states remain tags. Disable contractor submission unless the business status is `上传成功`, and update the tooltip to explain that upload processing must finish.

- [ ] **Step 4: Wire the page handler**

Add `handleRetryProjectFileUpload(documentId)` that calls the API with a unique idempotency key, shows `已重新上传，正在处理` on success, and runs `loadProjectBundle()`. Wire it to the role component event.

- [ ] **Step 5: Run focused tests and type checking**

Run: `cd frontend && pnpm exec esno src/utils/documentUploadActions.test.ts && pnpm exec esno src/utils/documentPipelineStatus.test.ts && pnpm ts:check`

Expected: PASS.

- [ ] **Step 6: Commit contractor integration**

```bash
git add frontend/src/api/aicheck/index.ts frontend/src/utils/documentUploadActions.ts frontend/src/utils/documentUploadActions.test.ts frontend/src/views/AICheck/components/WorkbenchRoleStaticSections.vue frontend/src/views/AICheck/Workbench.vue
git commit -m "feat: retry failed contractor uploads"
```

### Task 5: NDT workbench state and retry interaction

**Files:**
- Modify: `frontend/src/views/AICheck/components/NdtWorkflowPanel.vue`
- Modify: `frontend/src/views/AICheck/Workbench.vue`
- Modify: `frontend/src/utils/documentUploadActions.test.ts`

**Interfaces:**
- Produces: `retryUpload: [documentId: string]` from `NdtWorkflowPanel`.
- Consumes: Task 1 status/predicate and Task 4 page retry handler.

- [ ] **Step 1: Extend the failing business-action test for NDT**

Assert NDT rows are submittable only when the approval state is editable and the upload status is `上传成功`; failed uploads remain retryable but not submittable.

- [ ] **Step 2: Run the test and verify current NDT behavior fails**

Run: `cd frontend && pnpm exec esno src/utils/documentUploadActions.test.ts`

Expected: FAIL because the table shows raw OCR status and permits submission while processing.

- [ ] **Step 3: Implement NDT status, gate, copy, and event**

Import `isDocumentUploadSuccessful`, compute `uploadStatus` on each atomic row, set `canSubmit: canEdit && isDocumentUploadSuccessful(file)`, render the three-state value, and make only `失败重新上传` a link button. Replace the OCR section copy with business language stating that upload processing must succeed before submission.

- [ ] **Step 4: Reuse the page retry handler and wire the event**

Add `@retry-upload="handleRetryProjectFileUpload"` to `NdtWorkflowPanel`; keep a single endpoint and loading/error path for contractor and NDT.

- [ ] **Step 5: Run frontend verification**

Run: `cd frontend && pnpm exec esno src/utils/documentUploadActions.test.ts && pnpm exec esno src/utils/documentPipelineStatus.test.ts && pnpm ts:check && pnpm lint:eslint:check`

Expected: PASS with no new errors.

- [ ] **Step 6: Commit NDT integration**

```bash
git add frontend/src/views/AICheck/components/NdtWorkflowPanel.vue frontend/src/views/AICheck/Workbench.vue frontend/src/utils/documentUploadActions.test.ts
git commit -m "feat: gate NDT submission on upload success"
```

### Task 6: End-to-end regression verification

**Files:**
- Modify only if verification exposes a defect in files already listed above.

**Interfaces:**
- Consumes all completed tasks.
- Produces verified behavior for retry, status mapping, and submission gates.

- [ ] **Step 1: Run backend focused regression tests**

Run: `cd backend && pytest tests/test_contract.py -k 'retry_failed_upload or upload_success or ndt_atomic' -q`

Expected: PASS.

- [ ] **Step 2: Run frontend tests and static checks**

Run: `cd frontend && pnpm exec esno src/utils/documentPipelineStatus.test.ts && pnpm exec esno src/utils/documentUploadActions.test.ts && pnpm ts:check && pnpm lint:eslint:check`

Expected: PASS.

- [ ] **Step 3: Run whitespace and scope checks**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only intentional task files are changed.

- [ ] **Step 4: Commit any verification-only corrections**

If verification required an in-scope correction, stage only the affected files and commit with `fix: close upload retry regression`. If no correction was needed, do not create an empty commit.
