# 监检端已提交资料视图与提交生命周期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让监检平台只展示施工方和无损检测机构正式提交审查的资料，准确展示提交状态与提交审查时间，并落实提交后禁止撤回、仅允许监检退回后重新提交的生命周期。

**Architecture:** 后端新增监检专用已提交资料读模型，以 submission 为提交事实来源，统一解析项目资料池、节点资料和 NDT 单文件三种提交。共享节点资料包继续服务提交方草稿管理；监检前端改用专用接口。提交方撤回接口改为稳定拒绝，监检退回在同一事务内更新目标挂载、补正记录和待办，重新提交保留完整历史链。

**Tech Stack:** FastAPI、现有内存/SQLite/PostgreSQL 仓储、pytest、Vue 3、TypeScript、Element Plus、vue-tsc。

## Global Constraints

- 文件上传完成后仅为提交方草稿，未正式提交的资料不得出现在监检接口、数量、搜索或分页中。
- 提交审查时间必须来自正式 submission，不得回退到文件上传时间或 `updatedAt`。
- OCR 状态及异步更新时间不得改变提交状态、提交时间或监检可见性。
- 施工方和无损检测机构提交审查后不得撤回；只有监检人员退回后才能修改并重新提交。
- 同一文件存在草稿和已提交挂载时，监检端只返回已提交范围。
- 在 main 工作区直接执行，保留用户已有未跟踪目录 `audit-reports/2026-08-05-ndt-upload-audit/`。

---

### Task 1: 定义监检已提交资料后端契约

**Files:**
- Modify: `backend/tests/test_contract.py`
- Modify: `backend/apps/api/routes.py`

**Interfaces:**
- Produces: `GET /projects/{project_id}/inspection/submitted-documents`
- Produces: `build_inspection_submitted_document_rows(project_id, scope) -> list[dict[str, Any]]`
- Response: `{schemaVersion, items, page, pageSize, total, dataAsOf}`

- [ ] **Step 1: 写失败契约测试**

在 `backend/tests/test_contract.py` 创建三类文件及 submission：仅上传文件、项目资料池提交文件、节点挂载提交文件、NDT 单文件提交文件。断言接口只返回后三类，且响应中的 `submittedAt` 等于对应 submission 时间。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest -q backend/tests/test_contract.py -k "inspection_submitted_documents"`

Expected: FAIL，接口返回 404 或缺少约定字段。

- [ ] **Step 3: 实现最小读模型与接口**

在 `backend/apps/api/routes.py` 中：

```python
def build_inspection_submitted_document_rows(
    project_id: str,
    scope: set[int] | None,
) -> list[dict[str, Any]]:
    ...

@router.get("/projects/{project_id}/inspection/submitted-documents")
def inspection_submitted_documents(
    request: Request,
    project_id: str,
    keyword: str | None = None,
    page_no: int = Query(default=1, alias="page", ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=200),
):
    ...
```

读模型按 submission `submittedAt` 倒序建立文档最新有效提交；项目级 submission 读取 `documentIds`，节点及 NDT submission 通过 `bindingIds` 解析文档。响应只包含有效提交范围内的挂载，并附加 OCR readiness。

- [ ] **Step 4: 增加权限、搜索、分页和混合挂载测试**

断言 contractor/ndt 角色返回 403；搜索和 total 只统计正式提交资料；同一文档的草稿挂载不出现在 `submittedBindings`。

- [ ] **Step 5: 运行后端定向测试**

Run: `pytest -q backend/tests/test_contract.py -k "inspection_submitted_documents"`

Expected: PASS。

- [ ] **Step 6: 提交本任务**

```bash
git add backend/apps/api/routes.py backend/tests/test_contract.py
git commit -m "feat: add inspection submitted document view"
```

### Task 2: 禁止提交方撤回并统一监检退回状态

**Files:**
- Modify: `backend/tests/test_contract.py`
- Modify: `backend/apps/api/routes.py`
- Modify: `backend/libs/contracts/errors.py`

**Interfaces:**
- Produces: error code `SUBMISSION_WITHDRAW_NOT_ALLOWED`
- Changes: `POST /projects/{project_id}/submissions/{submission_id}/withdraw-items` always rejects without mutation
- Changes: `POST /projects/{project_id}/inspection/nodes/{node_id}/actions/return-correction` accepts `bindingIds` and marks them `需补正`

- [ ] **Step 1: 写禁止撤回失败测试**

提交节点资料后调用撤回接口，断言 HTTP 409、`reason = SUBMISSION_WITHDRAW_NOT_ALLOWED`、挂载仍为 `已提交`、submission 和节点状态未改变。

- [ ] **Step 2: 写监检退回失败测试**

用 inspection 身份携带 `bindingIds` 和原因调用退回接口，断言目标挂载变为 `需补正`，未选中的已提交挂载保持原状，补正记录保存 `submissionId`、`bindingIds`、`returnedAt` 和原因，并创建提交方待办。

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest -q backend/tests/test_contract.py -k "withdraw_not_allowed or return_correction_updates_bindings"`

Expected: FAIL，现有撤回会修改挂载，退回不会修改挂载。

- [ ] **Step 4: 实现稳定拒绝和精确退回**

撤回接口在身份及项目权限校验后直接返回 409，不执行状态变更。退回接口验证 `bindingIds` 均属于当前项目、当前节点和有效提交，拒绝草稿、已通过或归档挂载；使用单一服务端时间写入补正记录和挂载状态。

- [ ] **Step 5: 更新动作下发**

从施工方和 NDT 可用动作中移除 `submission:withdraw`，保留类型兼容但不再由服务端下发。

- [ ] **Step 6: 运行定向测试**

Run: `pytest -q backend/tests/test_contract.py -k "withdraw or return_correction or ndt_atomic_submission"`

Expected: 新规则测试 PASS；旧撤回成功断言需改为禁止撤回断言。

- [ ] **Step 7: 提交本任务**

```bash
git add backend/apps/api/routes.py backend/libs/contracts/errors.py backend/tests/test_contract.py
git commit -m "fix: enforce inspection-only correction returns"
```

### Task 3: 建立退回后重新提交的历史链

**Files:**
- Modify: `backend/tests/test_contract.py`
- Modify: `backend/apps/api/routes.py`

**Interfaces:**
- Consumes: `rectification.bindingIds`, `rectification.submissionId`
- Produces: new submission fields `previousSubmissionId`, `rectificationId`

- [ ] **Step 1: 写重新提交失败测试**

构造“初次提交 → 监检退回 → 重新提交”，断言产生两个不同 submission，新 submission 的 `submittedAt` 晚于或等于退回时间，包含 `previousSubmissionId` 和 `rectificationId`，原 submission 保持不变。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest -q backend/tests/test_contract.py -k "resubmission_preserves_history"`

Expected: FAIL，当前重新提交缺少历史关联。

- [ ] **Step 3: 在通用节点提交和 NDT 单文件提交中关联补正记录**

提交 `需补正` 挂载时查找覆盖相同 binding 的最新待反馈补正记录，将其标记为已重新提交，并把原 submission 与 rectification 标识写入新 submission。使用新 `submittedAt`，不得覆盖原记录。

- [ ] **Step 4: 验证监检读模型状态**

扩展 Task 1 测试，断言退回时 `reviewStatus = 需补正`，重新提交后 `reviewStatus = 已重新提交`，列表时间更新为新 submission 时间。

- [ ] **Step 5: 运行定向测试**

Run: `pytest -q backend/tests/test_contract.py -k "resubmission or inspection_submitted_documents"`

Expected: PASS。

- [ ] **Step 6: 提交本任务**

```bash
git add backend/apps/api/routes.py backend/tests/test_contract.py
git commit -m "feat: preserve correction resubmission history"
```

### Task 4: 迁移监检前端并移除撤回交互

**Files:**
- Modify: `frontend/src/types/aicheck.ts`
- Modify: `frontend/src/api/aicheck/index.ts`
- Modify: `frontend/src/views/AICheck/Workbench.vue`
- Modify: `frontend/src/views/AICheck/components/WorkbenchActionBar.vue`
- Modify: `frontend/src/views/AICheck/components/SubmissionBatchDialog.vue`
- Modify: `frontend/src/utils/acceptanceFlows.test.ts`

**Interfaces:**
- Produces: `InspectionSubmittedDocument` and `InspectionSubmittedDocumentsPayload`
- Produces: `getInspectionSubmittedDocumentsApi(projectId, params)`
- Consumes: backend `reviewStatus`, `submittedAt`, `submittedBindings`

- [ ] **Step 1: 添加类型和 API 客户端**

定义监检资料响应类型，并增加 `/inspection/submitted-documents` 客户端函数。不得在类型或 UI 中用 `uploadTime`/`updatedAt` 作为提交时间回退。

- [ ] **Step 2: 将监检列表改为专用状态源**

新增 `inspectionSubmittedDocuments` 状态和加载函数，仅在 inspection 角色加载。删除 `inspectionOverviewFileRows` 对 `nodePackage.projectFiles` 的映射，排序、分页和 total 使用专用响应。

- [ ] **Step 3: 修正文案与字段**

标题改为“已提交审查资料”，说明改为“仅展示施工方和无损检测机构已正式提交监检审查的资料”，列名改为“提交人”“审查/OCR 状态”“提交审查时间”，空状态改为“暂无已提交审查资料”。

- [ ] **Step 4: 移除撤回入口和逻辑**

删除 Workbench 的 `withdrawSubmissionItemsApi` 引用与处理函数；删除操作栏撤回按钮、提交弹窗撤回表单和重试分支。历史抽屉保留旧撤回记录只读展示。

- [ ] **Step 5: 更新前端静态测试**

从测试 fixture 的 actions 中移除 `submission:withdraw`，并新增源代码断言或纯函数测试，确保监检列表不依赖 `projectFiles` 和上传时间回退。

- [ ] **Step 6: 运行前端验证**

Run: `cd frontend && pnpm ts:check`

Run: `cd frontend && node --import tsx src/utils/acceptanceFlows.test.ts`

Expected: PASS。

- [ ] **Step 7: 提交本任务**

```bash
git add frontend/src/types/aicheck.ts frontend/src/api/aicheck/index.ts frontend/src/views/AICheck/Workbench.vue frontend/src/views/AICheck/components/WorkbenchActionBar.vue frontend/src/views/AICheck/components/SubmissionBatchDialog.vue frontend/src/utils/acceptanceFlows.test.ts
git commit -m "fix: show only submitted documents to inspection"
```

### Task 5: 全量回归与完成审计

**Files:**
- Modify if required by failures: files touched in Tasks 1–4

**Interfaces:**
- Verifies: all goal requirements and existing submission/OCR regressions

- [ ] **Step 1: 运行后端相关测试组**

Run: `pytest -q backend/tests/test_contract.py -k "submission or correction or inspection or ndt_atomic"`

Expected: PASS。

- [ ] **Step 2: 运行后端完整契约测试**

Run: `pytest -q backend/tests/test_contract.py`

Expected: PASS。

- [ ] **Step 3: 运行前端类型、静态测试和构建**

Run: `cd frontend && pnpm ts:check`

Run: `cd frontend && node --import tsx src/utils/acceptanceFlows.test.ts`

Run: `cd frontend && pnpm build:test`

Expected: 全部 PASS。

- [ ] **Step 4: 静态口径审计**

Run: `rg -n "上传文件列表|label=\"上传时间\"|withdrawSubmissionItemsApi|撤回未提交" frontend/src/views/AICheck frontend/src/api/aicheck/index.ts`

Expected: 监检总览和提交方操作区无旧口径或撤回入口；允许历史抽屉只读出现“撤回”。

- [ ] **Step 5: 检查工作区与提交最终修复**

Run: `git status --short`

只保留用户原有未跟踪审计目录，不包含意外生成文件。若验证修复产生代码改动，使用独立提交：

```bash
git add <验证修复涉及的明确文件>
git commit -m "test: verify submitted document lifecycle"
```
