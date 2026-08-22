# 施工方工作台交互 UI 调整实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有施工方工作台从“分类清单与宽表格驱动”调整为目标稿所示的“状态总览、统一上传、监检意见和资料台账”四段式工作台，同时保留文件挂载、版本、替换、补正、失败重试和待办定位能力。

**Architecture:** `Workbench.vue` 继续负责项目数据加载、接口调用和弹窗状态；从 `WorkbenchRoleStaticSections.vue` 中抽出施工方专属页面，由纯函数视图模型统一计算统计卡、意见和文件行。上传入口复用现有上传会话接口，普通项目文件改为页面内选择/拖拽，替换文件和指定分类上传仍复用抽屉。

**Tech Stack:** Vue 3、TypeScript、Element Plus、Vite、Node `assert` 单元测试、Playwright E2E、FastAPI（仅在确认需要补正截止日期时调整）。

**Spec:** `uidesign.md` 第 5、13、14 节；目标视觉为用户提供的“施工资料工作台”截图。

## Global Constraints

- 仅调整 `contractor` 角色；不得改变监检、无损检测、建设方和后台工作台布局。
- 不改变现有角色权限、提交校验、幂等键、审计留痕和历史提交快照。
- 已提交文件不提供物理删除或直接替换；修改必须走补正或追加版本流程。
- 文件处理状态只显示“上传中、上传成功、失败重新上传”，不得暴露 OCR、切片、向量化内部阶段。
- 业务状态与文件处理状态分开计算；只有处理成功且业务状态允许时才能提交。
- 保留 `focusContractorNode()` 的精确节点筛选和“查看全部资料”退出路径。
- 保留当前未提交改动：资料分类指引不重新加入“当前节点缺项”和“需补正文件名”裸列表。
- 不引入新的 UI 框架或状态管理依赖。

---

## 一、现状与目标差异

| 区域 | 当前实现 | 目标稿 | 修改结论 |
|---|---|---|---|
| 页面标题 | “施工方工作台 · 项目文件库与补正反馈”，右侧有“批量上传文件” | “施工资料工作台”，标题下说明上传、识别、补正的工作方式 | 调整标题和说明，移除重复的页头上传按钮 |
| 状态总览 | 已有 `workbenchAuditCards` 计算，但施工方被模板条件隐藏 | 首屏显示“待处理意见、待提交、审核中”三张卡 | 新增施工方专属、可点击的状态卡并与下方列表联动 |
| 上传入口 | 页头按钮打开 `UploadSessionDrawer` | 页面内显示大面积拖拽区和“选择文件”按钮 | 抽取共享文件选择器，普通上传内嵌；替换上传继续使用抽屉 |
| 资料分类 | 十类分类清单占据首屏，并逐类提供上传入口 | 分类由系统自动识别，首屏不展示分类清单 | 分类清单移出首屏；类别仍保留为筛选项和行内识别结果 |
| 监检意见 | 位于完整文件台账之后，以宽表格展示 | 与上传区并列，优先展示最紧急意见 | 改为紧凑意见卡，待反馈项默认展开，其余折叠 |
| 文件台账 | 12 个以上字段，右侧 5 个并排操作，依赖横向滚动 | 5 个主列，次要信息组合展示，低频动作进入“更多” | 精简主列，保留详情抽屉承载节点、用途、反馈和版本信息 |
| 筛选 | 状态、类别、用途、排序分两行展示 | 状态 Tab + 搜索 + 类别/状态/时间筛选 | 状态改为一级 Tab；“未关联、已作废”放入状态下拉，不丢能力 |
| 补正办理 | “上传补正、关联文件、提交反馈”三个独立按钮 | 意见卡提供“查看意见”和“上传补正资料” | 查看打开现有补正详情；上传和提交仍绑定同一补正单 |
| 最近上传 | 无页面内上传摘要 | 显示上传文件数、已识别数和结果图标 | 从项目文件和统一处理状态派生，不新增统计接口 |

## 二、文件结构

**Create**

- `frontend/src/views/AICheck/components/contractor/contractorWorkbenchViewModel.ts`：施工方状态、统计、意见优先级和文件列表的纯函数映射。
- `frontend/src/views/AICheck/components/contractor/contractorWorkbenchViewModel.test.ts`：上述状态口径和筛选联动测试。
- `frontend/src/views/AICheck/components/contractor/ContractorWorkbenchSection.vue`：施工方完整页面结构。
- `frontend/src/views/AICheck/components/contractor/ContractorStatusCards.vue`：三张可点击统计卡。
- `frontend/src/views/AICheck/components/contractor/ContractorUploadPanel.vue`：统一上传区和最近上传摘要。
- `frontend/src/views/AICheck/components/contractor/ContractorFeedbackPanel.vue`：监检意见卡列表。
- `frontend/src/views/AICheck/components/contractor/ContractorFileLedger.vue`：状态 Tab、筛选器和精简资料表。
- `frontend/src/views/AICheck/components/UploadFilePicker.vue`：抽屉与页面内上传区共用的文件选择、去重和移除能力。
- `frontend/src/views/AICheck/components/uploadFileSelection.ts`：文件去重和上传按钮资格的纯函数。
- `frontend/src/views/AICheck/components/uploadFileSelection.test.ts`：共享文件选择逻辑测试。

**Modify**

- `frontend/src/views/AICheck/Workbench.vue`：调整施工方标题；接入内嵌上传事件；移除重复页头按钮；继续持有接口和弹窗动作。
- `frontend/src/views/AICheck/components/WorkbenchRoleStaticSections.vue`：施工方分支改为渲染 `ContractorWorkbenchSection`；建设方和其他角色逻辑保持原位。
- `frontend/src/views/AICheck/components/UploadSessionDrawer.vue`：复用 `UploadFilePicker`，避免维护两套选文件逻辑。
- `frontend/src/types/aicheck.ts`：只在后端同时提供时，为 `RectificationItem` 增加可选 `dueAt`。
- `frontend/e2e/aicheck-smoke.spec.ts`：按新结构验证施工方核心流程和窄屏回流。
- `frontend/src/views/AICheck/autoClassifyAndBatchReview.test.ts`、`uploadedMaterialActions.test.ts`、`todoJumpHonesty.test.ts`、`orgDelegationAndGaps.test.ts`：源文件断言迁移到施工方新组件或视图模型。

**Optional backend change**

- `backend/apps/api/routes.py`、`backend/tests/test_contract.py`：仅当业务确认目标稿中的“截止日期”为真实字段时，退回补正请求接收并返回可选 `dueAt`。未确认前页面显示“未设置截止日期”，不得根据创建时间伪造。

---

### Task 1: 固化施工方状态与统计口径

**Files:**
- Create: `frontend/src/views/AICheck/components/contractor/contractorWorkbenchViewModel.ts`
- Create: `frontend/src/views/AICheck/components/contractor/contractorWorkbenchViewModel.test.ts`
- Uses: `frontend/src/utils/documentPipelineStatus.ts`
- Uses: `frontend/src/utils/acceptanceFlows.ts`

**Interfaces:**
- Produces: `ContractorPrimaryTab = '全部' | '待提交' | '审核中' | '需补正' | '已通过'`
- Produces: `buildContractorWorkbenchModel(packageData: NodePackagePayload): ContractorWorkbenchModel`
- Produces: `ContractorFileFilters`
- Produces: `filterContractorFiles(rows: readonly ContractorFileRow[], filters: ContractorFileFilters): ContractorFileRow[]`
- Produces: `primaryActionFor(row: Pick<ContractorFileRow, 'status'>): '选择环节' | '提交' | '办理补正' | '预览'`

- [ ] **Step 1: 写状态映射失败测试**

```ts
assert.deepEqual(model.summaryCards.map((item) => item.key), [
  'feedback',
  'pending',
  'reviewing'
])
assert.equal(model.summaryCards.find((item) => item.key === 'feedback')?.count, 1)
assert.equal(model.primaryTabs.find((item) => item.key === '待提交')?.count, 1)
assert.equal(model.recentUpload.total, 8)
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `cd frontend && pnpm test:unit`

Expected: FAIL，提示 `buildContractorWorkbenchModel` 尚未定义。

- [ ] **Step 3: 实现纯函数视图模型**

映射规则：

```ts
const PRIMARY_TABS = ['全部', '待提交', '审核中', '需补正', '已通过'] as const

const pendingFeedback = rectifications.filter((item) => item.status === '待反馈')
const reviewing = files.filter((file) => documentBindingSummary(file) === '审核中')
const pending = files.filter((file) => documentBindingSummary(file) === '待提交')
```

同时保留 `未关联`、`已作废` 作为下拉筛选值；分类来源必须继续区分 `auto`、`manual`、`inferred`。

- [ ] **Step 4: 运行单元测试**

Run: `cd frontend && pnpm test:unit`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/AICheck/components/contractor/contractorWorkbenchViewModel.ts frontend/src/views/AICheck/components/contractor/contractorWorkbenchViewModel.test.ts
git commit -m "refactor: centralize contractor workbench view state"
```

### Task 2: 拆出施工方专属页面并接入状态卡

**Files:**
- Create: `frontend/src/views/AICheck/components/contractor/ContractorWorkbenchSection.vue`
- Create: `frontend/src/views/AICheck/components/contractor/ContractorStatusCards.vue`
- Modify: `frontend/src/views/AICheck/components/WorkbenchRoleStaticSections.vue`
- Modify: `frontend/src/views/AICheck/Workbench.vue`

**Interfaces:**
- `ContractorWorkbenchSection` 消费 `project`、`node`、`packageData`、`readOnly`。
- 保持现有 `focusContractorNode(node)` 暴露接口。
- 状态卡发出 `filter-change`，值为 `feedback | pending | reviewing | null`。

- [ ] **Step 1: 写结构断言失败测试**

在新组件测试中断言存在三个卡片名称、`aria-pressed` 和真实列表锚点。

- [ ] **Step 2: 运行测试并确认失败**

Run: `cd frontend && pnpm test:unit`

- [ ] **Step 3: 抽出施工方分支**

`WorkbenchRoleStaticSections.vue` 中施工方分支只负责透传 props、events 和 expose；不得复制建设方逻辑。顶部项目栏和面包屑继续使用“施工方工作台”，仅页面主标题和说明调整为：

```ts
const contractorPageTitle = '施工资料工作台'
const contractorPageIntro =
  '统一上传项目资料并提交，根据监检意见补充完善相关资料。'
```

施工方分支不得再使用 `${currentRoleConfig.title} · ${pageHeadline}` 拼接主标题，不显示页面面包屑；删除页头重复的“批量上传文件”按钮。

- [ ] **Step 4: 实现状态卡联动**

- 点击“待处理意见”滚动到 `#contractor-feedback-list`。
- 点击“待提交”或“审核中”设置文件 Tab 并滚动到 `#contractor-file-list`。
- 再次点击已选卡片清除筛选。
- 状态卡使用 `<button>`，提供 `aria-pressed` 和可见焦点。

- [ ] **Step 5: 验证现有待办定位仍工作**

Run: `cd frontend && pnpm test:unit`

Expected: `todoJumpHonesty.test.ts` PASS。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/AICheck/Workbench.vue frontend/src/views/AICheck/components/WorkbenchRoleStaticSections.vue frontend/src/views/AICheck/components/contractor
git commit -m "refactor: introduce contractor task dashboard"
```

### Task 3: 将普通上传改为页面内上传

**Files:**
- Create: `frontend/src/views/AICheck/components/UploadFilePicker.vue`
- Create: `frontend/src/views/AICheck/components/uploadFileSelection.ts`
- Create: `frontend/src/views/AICheck/components/uploadFileSelection.test.ts`
- Create: `frontend/src/views/AICheck/components/contractor/ContractorUploadPanel.vue`
- Modify: `frontend/src/views/AICheck/components/UploadSessionDrawer.vue`
- Modify: `frontend/src/views/AICheck/components/contractor/ContractorWorkbenchSection.vue`
- Modify: `frontend/src/views/AICheck/Workbench.vue`

**Interfaces:**
- `UploadFilePicker` emits `change(files: File[])`。
- `ContractorUploadPanel` emits `submit(files: File[])`。
- `uniqueUploadFiles(files: readonly File[]): File[]` 负责按名称、大小和最后修改时间去重。
- `canSubmitInlineUpload(files: readonly File[], loading: boolean): boolean` 负责按钮资格。
- `Workbench.vue` 继续复用 `handleCreateUploadSession(files)`，不新增上传 API。

- [ ] **Step 1: 写文件去重和提交资格失败测试**

```ts
assert.equal(uniqueUploadFiles([fileA, fileA]).length, 1)
assert.equal(canSubmitInlineUpload([], false), false)
assert.equal(canSubmitInlineUpload([fileA], false), true)
```

- [ ] **Step 2: 抽取共享文件选择器**

从 `UploadSessionDrawer.vue` 迁移扩展名限制、文件去重、移除和文件表格；抽屉仅负责标题、目标分类、节点选择和提交按钮。

- [ ] **Step 3: 实现目标稿上传区**

- 支持拖拽和“选择文件”。
- 支持 `.pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png,.zip`。
- 选择文件后直接调用现有上传会话流程。
- 上传中禁用重复提交；错误保留在上传区并提供重试。
- 上传完成后刷新项目数据并启动现有处理状态轮询。

- [ ] **Step 4: 实现最近上传摘要**

按 `updatedAt` 取最近 8 个文件，显示总数、已成功数、处理中数和失败数；摘要可点击并切换资料列表的处理状态筛选。

- [ ] **Step 5: 保留替换上传路径**

`handleReplaceProjectFile()` 仍打开 `UploadSessionDrawer`，必须继续验证“一次只能替换一个文件”和 `replaceDocumentId`。

- [ ] **Step 6: 验证**

Run: `cd frontend && pnpm test:unit && pnpm ts:check`

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/AICheck/components/UploadFilePicker.vue frontend/src/views/AICheck/components/UploadSessionDrawer.vue frontend/src/views/AICheck/components/contractor frontend/src/views/AICheck/Workbench.vue
git commit -m "feat: add inline contractor document upload"
```

### Task 4: 将监检反馈表改为意见办理面板

**Files:**
- Create: `frontend/src/views/AICheck/components/contractor/ContractorFeedbackPanel.vue`
- Modify: `frontend/src/views/AICheck/components/contractor/ContractorWorkbenchSection.vue`
- Modify: `frontend/src/views/AICheck/components/RectificationDetailDialog.vue`

**Interfaces:**
- `ContractorFeedbackPanel` emits `view(rectificationId)`、`upload-correction({ rectificationId, nodeId })`、`rectify(rectificationId)`。
- `RectificationDetailDialog` 增加 `mode: 'view' | 'submit'`，查看模式不显示反馈输入和提交按钮。

- [ ] **Step 1: 写意见排序失败测试**

```ts
assert.deepEqual(sortFeedback(rows).map((item) => item.status), [
  '待反馈',
  '已重新提交',
  '已关闭'
])
```

- [ ] **Step 2: 实现意见卡**

- 默认展开第一条“待反馈”。
- 展示编号、问题标题、补正说明、问题类型、关联文件数量和截止日期。
- 其余意见显示单行摘要，可展开。
- “上传补正资料”必须把当前 `rectificationId` 和 `nodeId` 传入后续补正流程。

上传补正资料使用现有接口完成以下顺序，不新增旁路数据结构：

1. `createDocumentUploadSessionApi()` 与 `completeDocumentUploadSessionApi()` 创建文件和版本；
2. `bindDocumentsToNodeApi()` 将新文件以 `usage: '补正附件'` 绑定到意见对应节点；
3. 刷新项目包并打开当前补正单的 `RectificationDetailDialog`；
4. 用户确认说明后，由 `submitRectificationApi()` 提交 `rectificationId` 和新绑定 ID。

若第 1 步成功但第 2 步失败，页面必须明确提示“文件已上传但尚未关联补正意见”，并提供“关联文件”恢复入口，不得再次上传同一文件。

- [ ] **Step 3: 实现查看模式**

“查看意见”打开 `RectificationDetailDialog` 的只读模式；“提交反馈”仍走原有 `submitRectificationApi`，不得新建旁路接口。

- [ ] **Step 4: 处理截止日期缺口**

若 `RectificationItem.dueAt` 不存在，显示“未设置截止日期”；不得用 `createdAt` 加固定天数推算。

- [ ] **Step 5: 验证**

Run: `cd frontend && pnpm test:unit && pnpm ts:check`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/AICheck/components/contractor frontend/src/views/AICheck/components/RectificationDetailDialog.vue
git commit -m "feat: prioritize contractor rectification feedback"
```

### Task 5: 将文件宽表改为精简资料台账

**Files:**
- Create: `frontend/src/views/AICheck/components/contractor/ContractorFileLedger.vue`
- Modify: `frontend/src/views/AICheck/components/contractor/ContractorWorkbenchSection.vue`
- Modify: `frontend/src/views/AICheck/uploadedMaterialActions.test.ts`
- Modify: `frontend/src/views/AICheck/autoClassifyAndBatchReview.test.ts`
- Modify: `frontend/src/views/AICheck/todoJumpHonesty.test.ts`
- Modify: `frontend/src/views/AICheck/orgDelegationAndGaps.test.ts`

**Interfaces:**
- 主列固定为：文件名、系统识别、上传信息、当前状态、操作。
- 保留现有事件：`file-view`、`file-replace`、`file-bind`、`file-submit`、`file-retry-upload`、`file-delete`。

- [ ] **Step 1: 写主操作映射失败测试**

```ts
assert.equal(primaryActionFor({ status: '未关联' }), '选择环节')
assert.equal(primaryActionFor({ status: '待提交' }), '提交')
assert.equal(primaryActionFor({ status: '需补正' }), '办理补正')
assert.equal(primaryActionFor({ status: '审核中' }), '预览')
```

- [ ] **Step 2: 实现 Tab 和筛选器**

- 一级 Tab：全部、待提交、审核中、需补正、已通过。
- 搜索：文件名、编号、来源单位、反馈编号。
- 下拉：资料类别、完整业务状态。
- 时间：按更新时间范围过滤。
- 保留节点筛选提示和“查看全部资料”。

- [ ] **Step 3: 精简列和操作**

- 文件名下显示类型、版本、大小。
- 系统识别显示类别及 `自动识别/推测` 来源；人工确认类别不重复标记。
- 上传信息组合显示上传人、时间、来源单位。
- 当前状态主标签显示业务状态；仅在处理未完成或失败时附加处理状态。
- 每行只显示“预览 + 当前主操作 + 更多”。替换、删除、历史版本和选择环节按状态进入“更多”。

- [ ] **Step 4: 更新源文件测试**

将原来读取 `WorkbenchRoleStaticSections.vue` 的施工方断言迁移到 `ContractorWorkbenchSection.vue`、`ContractorFileLedger.vue` 或 `contractorWorkbenchViewModel.ts`；不得通过复制无效字符串让测试假通过。

- [ ] **Step 5: 验证**

Run: `cd frontend && pnpm test:unit && pnpm ts:check && pnpm lint:eslint:check`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/AICheck/components/contractor frontend/src/views/AICheck/*.test.ts
git commit -m "feat: simplify contractor document ledger"
```

### Task 6: 补齐响应式、键盘和视觉状态

**Files:**
- Modify: `frontend/src/views/AICheck/components/contractor/ContractorWorkbenchSection.vue`
- Modify: `frontend/src/views/AICheck/components/contractor/ContractorStatusCards.vue`
- Modify: `frontend/src/views/AICheck/components/contractor/ContractorUploadPanel.vue`
- Modify: `frontend/src/views/AICheck/components/contractor/ContractorFeedbackPanel.vue`
- Modify: `frontend/src/views/AICheck/components/contractor/ContractorFileLedger.vue`

- [ ] **Step 1: 实现桌面布局**

- 统计卡三等分。
- 上传区与意见区使用约 `56% / 44%` 双列。
- 资料列表独占下一行。
- 沿用现有蓝、绿、橙、红 token，不新增渐变和装饰色。

- [ ] **Step 2: 实现断点**

- `>= 1280px`：目标稿双列。
- `768px–1279px`：上传区和意见区上下排列，表格隐藏来源单位。
- `< 768px`：状态卡纵向排列，文件台账使用卡片式摘要，操作保持可达。

- [ ] **Step 3: 补齐可访问性**

- 状态卡、意见折叠项和“更多”使用语义按钮。
- 拖拽区具备键盘选择文件入口。
- 焦点样式清晰；状态同时使用文字，不只依赖颜色。
- 主要点击目标最小高度 40px，表格文字动作最小高度 32px。

- [ ] **Step 4: 静态和类型验证**

Run: `cd frontend && pnpm ts:check && pnpm lint && pnpm build:pro`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/AICheck/components/contractor
git commit -m "style: align contractor workbench with task-first layout"
```

### Task 7: 更新端到端验收并做视觉对比

**Files:**
- Modify: `frontend/e2e/aicheck-smoke.spec.ts`
- Create: `audit-reports/contractor-workbench-redesign-plan-20260820/02-target-implementation.png`

- [ ] **Step 1: 更新施工方 E2E 用例**

验证：

```ts
await expect(pageRoot).toContainText('施工资料工作台')
await expect(page.getByRole('button', { name: /待处理意见/ })).toBeVisible()
await expect(page.getByText('统一上传资料')).toBeVisible()
await expect(page.getByText('监检审查意见')).toBeVisible()
await expect(page.getByText('上传资料列表')).toBeVisible()
```

继续验证内嵌上传、节点关联、补正详情、提交反馈和 390px 无页面级横向溢出。

- [ ] **Step 2: 运行定向 E2E**

Run: `cd frontend && pnpm playwright test e2e/aicheck-smoke.spec.ts --grep "contractor project file library"`

Expected: PASS。

- [ ] **Step 3: 运行完整前端门禁**

Run: `cd frontend && pnpm test:unit && pnpm ts:check && pnpm lint && pnpm build:pro`

Expected: 全部 PASS。

- [ ] **Step 4: 视觉对比**

在与目标稿一致的桌面视口截取实现页面，重点核对：首屏层级、双列比例、表格密度、状态色、间距、边框、圆角和固定操作列。修复明显差异后重新截图。

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/aicheck-smoke.spec.ts audit-reports/contractor-workbench-redesign-plan-20260820/02-target-implementation.png
git commit -m "test: verify contractor workbench redesign"
```

### Task 8（可选）: 增加补正截止日期

只有业务确认监检人员需要设置截止日期时执行此任务。

**Files:**
- Modify: `backend/apps/api/routes.py`
- Modify: `backend/tests/test_contract.py`
- Modify: `frontend/src/types/aicheck.ts`
- Modify: `frontend/src/views/AICheck/components/contractor/ContractorFeedbackPanel.vue`

- [ ] **Step 1: 写后端失败测试**

```py
result = assert_ok(client.post(url, json={
    "bindingIds": ["BIND-16-001"],
    "reason": "补充质量证明材料",
    "dueAt": "2026-08-25T23:59:59+08:00",
}, headers=inspection_headers))
assert result["rectification"]["dueAt"] == "2026-08-25T23:59:59+08:00"
```

- [ ] **Step 2: 校验并持久化可选 `dueAt`**

要求为合法 ISO 8601 且晚于当前时间；未传时保持 `null`，不自动生成日期。

- [ ] **Step 3: 更新类型和意见卡**

`RectificationItem` 增加 `dueAt?: string | null`，待反馈意见显示日期；临期和逾期分别使用橙色和红色。

- [ ] **Step 4: 验证**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contract.py -k "return_correction" -q`

Run: `cd frontend && pnpm test:unit && pnpm ts:check`

- [ ] **Step 5: Commit**

```bash
git add backend/apps/api/routes.py backend/tests/test_contract.py frontend/src/types/aicheck.ts frontend/src/views/AICheck/components/contractor/ContractorFeedbackPanel.vue
git commit -m "feat: add rectification due dates"
```

---

## 三、验收标准

- 首屏顺序为：标题说明 → 三张状态卡 → 上传与监检意见双列 → 上传资料列表。
- 点击状态卡能准确定位并筛选对应内容；清除筛选后恢复完整列表。
- 普通上传不再先打开抽屉，拖拽和选择文件均调用现有上传会话流程。
- 上传、识别、挂载、提交、补正和审核状态不会混成一个标签。
- 自动识别和低可信度推测在列表中可区分；人工确认类别不显示多余来源标记。
- 未关联、已作废、节点定位、版本替换、失败重试和历史补正能力仍可达。
- 已提交文件不可删除或直接替换。
- 监检意见默认优先待反馈项，上传补正资料自动绑定意见编号。
- 1440px 桌面布局与目标稿结构一致；390px 宽度无页面级横向滚动。
- 前端单测、类型检查、lint、生产构建及施工方定向 E2E 全部通过。

## 四、阶段验收门禁

每个阶段完成后停止继续开发，由产品或测试人员按本节验收；上一阶段未通过时，不进入下一阶段。

### 阶段 1：页面骨架与状态卡

- 页面主标题显示“施工资料工作台”，不显示“当前位置：施工方工作台 / 项目文件库”面包屑。
- 标题下说明为“统一上传项目资料并提交，根据监检意见补充完善相关资料。”
- 首屏按“待处理意见、待提交、审核中”顺序显示三张卡片。
- 卡片数字分别来自待反馈补正单、草稿挂载文件、已提交待审文件；不得使用固定数字。
- 点击“待处理意见”滚动到审核反馈区域；点击“待提交”或“审核中”滚动到资料列表并应用对应筛选。
- 再次点击已选卡片取消卡片筛选，资料列表恢复“全部”。
- 当前资料分类清单、文件表、节点待办定位和反馈办理入口保持可用。
- 自动门禁：`pnpm test:unit`、`pnpm ts:check`、lint 和生产构建通过。

### 阶段 2：内嵌上传与意见办理

- 首屏上传区支持点击选择和拖拽多个文件，不再先打开普通上传抽屉。
- “上传资料列表”位于任务区之后，先于“资料分类与上传指引”展示。
- “资料分类与上传指引”作为页面最后一个区域，只显示序号、资料类别、建议包含资料和上传提示；不显示“已上传”和“操作”。
- 文件扩展名、去重、移除、错误重试和替换上传规则与现有实现一致。
- 上传过程中禁止重复提交；上传完成后能在“最近上传”和资料列表中看到文件。
- 页面显示最近 8 份资料的上传成功、处理中和失败数量，三者合计等于摘要总数。
- 监检意见与上传区并列；第一条待反馈意见默认展开，其余意见可展开。
- “查看意见”只读；“上传补正资料”上传后绑定当前补正单对应节点；绑定失败时不得要求重复上传。
- 自动门禁：阶段 1 用例继续通过，新增上传与意见单测、类型检查通过。

### 阶段 3：资料台账与操作收口

- 主表只保留“文件名、系统识别、上传信息、当前状态、操作”五个主列。
- Tab 为“全部、待提交、审核中、需补正、已通过”，数量与真实列表一致。
- “未关联、已作废”仍能通过状态筛选找到，不因精简 Tab 而消失。
- 自动识别、低可信度推测和人工确认的分类样式可区分。
- 每行只突出一个符合当前状态的主操作；替换、删除、节点关联、历史版本进入“更多”。
- 已提交资料不能删除或直接替换；上传未成功的资料不能提交。
- 从待办跳转仍按节点 ID 精确筛选，并显示退出节点筛选的入口。
- 自动门禁：全部前端单测、类型检查和 ESLint 通过。

### 阶段 4：响应式与完整回归

- 1440px 桌面首屏结构和目标稿一致：三张状态卡、上传/意见双列、资料列表通栏。
- 768px–1279px 上传区和意见区上下排列，不出现内容裁切。
- 390px 宽度无页面级横向滚动，主要操作均可通过键盘访问。
- 状态不仅使用颜色表达；焦点状态可见；主按钮高度至少 40px。
- 上传、预览、替换、节点关联、单文件提交、失败重试、查看意见和提交补正的核心路径均通过。
- 自动门禁：单测、类型检查、lint、生产构建、施工方定向 E2E 全部通过。
- 视觉门禁：使用相同桌面视口与目标截图对比，P0/P1/P2 视觉问题清零后才交付。

## 五、推荐排期

| 阶段 | 内容 | 预计工作量 |
|---|---|---:|
| P0 | 状态视图模型、页面拆分、三张状态卡 | 1.5 人日 |
| P1 | 内嵌上传、最近上传摘要 | 1.5 人日 |
| P2 | 意见面板、精简资料台账、动作收口 | 2 人日 |
| P3 | 响应式、无障碍、E2E 与视觉回归 | 1.5 人日 |
| Optional | 补正截止日期前后端支持 | 1 人日 |

不含可选截止日期时，建议按 **6.5 人日** 安排；若视觉稿在实现过程中不再调整，可压缩至约 **5 人日**。
