# 监检工作台 AI 审查区域切换实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `/workbench/inspection` 内保留唯一项目和节点导航，让右侧默认显示 AI 审查并可切换到原审查列表。

**Architecture:** `Workbench.vue` 作为唯一页面外壳和上下文所有者；`ConversationalReviewWorkbenchB.vue` 新增嵌入模式，接收父级项目和节点，只渲染 AI 对话与上下文区域。查询参数 `view=ai|list` 保存区域状态，默认 `ai`。

**Tech Stack:** Vue 3、Vue Router、TypeScript、Element Plus、Playwright。

## Global Constraints

- 监检默认路径保持 `/workbench/inspection`。
- 只切换右侧内容区域，不跳转整页。
- 三秒轮询和后端接口本轮不调整。
- 旧 `/ai-review-b` 独立页面保留。
- 其他角色行为不变。

---

### Task 1: 区域状态契约

**Files:**
- Create: `frontend/src/views/AICheck/inspectionWorkspaceView.ts`
- Create: `frontend/src/views/AICheck/inspectionWorkspaceView.test.ts`

**Interfaces:**
- Produces: `type InspectionWorkspaceView = 'ai' | 'list'` 和 `resolveInspectionWorkspaceView(value: unknown): InspectionWorkspaceView`。

- [ ] 写测试，断言缺失、非法值和 `ai` 返回 `ai`，只有 `list` 返回 `list`。
- [ ] 运行 `cd frontend && pnpm test:unit`，确认函数缺失导致失败。
- [ ] 实现最小解析函数并确认全部单测通过。

### Task 2: AI 审查组件嵌入模式

**Files:**
- Modify: `frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue`
- Create: `frontend/src/views/AIReviewB/embeddedReviewWorkbench.test.ts`

**Interfaces:**
- Consumes: `embedded?: boolean`、`projectId?: string`、`nodeId?: number`。
- Produces: 嵌入模式下只加载指定节点工作区，不加载项目列表/项目树，不替换独立 AI 路由。

- [ ] 写嵌入上下文生命周期测试，覆盖首次上下文、项目/节点变化和独立模式初始化决策。
- [ ] 运行单测并确认缺少嵌入上下文控制器而失败。
- [ ] 抽取小型上下文控制器，组件根据模式选择独立初始化或父级上下文初始化。
- [ ] 给顶栏和节点栏增加嵌入条件，并增加嵌入布局样式。
- [ ] 运行单测和类型检查。

### Task 3: 主工作台区域切换

**Files:**
- Modify: `frontend/src/views/AICheck/Workbench.vue`
- Modify: `frontend/e2e/aicheck-smoke.spec.ts`

**Interfaces:**
- Consumes: `resolveInspectionWorkspaceView()` 和嵌入式 `ConversationalReviewWorkbenchB`。
- Produces: `view=ai|list` 同页切换，默认 AI，保持项目和节点查询参数。

- [ ] 先添加 Playwright 用例：登录监检工作台默认看见 AI 对话且只有一个节点树；切换审查列表不改变路由路径和节点；切回恢复 AI。
- [ ] 运行聚焦 E2E，确认默认仍显示审查列表而失败。
- [ ] 在主工作台添加区域状态、查询参数同步、切换按钮和两个内容容器。
- [ ] 项目总览选择强制进入 `list`，节点选择保持当前区域。
- [ ] 运行聚焦 E2E、前端单测和类型检查。

### Task 4: 验证

**Files:**
- No production files unless a new failing regression test demonstrates a defect.

**Interfaces:**
- Produces: 自动化和真实浏览器验收证据。

- [ ] 运行 `cd frontend && pnpm test:unit && pnpm ts:check && pnpm build:pro`。
- [ ] 运行监检工作台相关 Playwright 用例。
- [ ] 启动本地前后端，用监检账号验证默认 AI、列表切换、节点切换和刷新恢复。
- [ ] 抽查 contractor 默认工作台没有区域切换。
- [ ] 运行 `git diff --check` 并复核变更只涉及文档和前端页面。
