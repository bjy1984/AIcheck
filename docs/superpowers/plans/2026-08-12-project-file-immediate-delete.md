# 项目文件即时删除实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户确认删除后文件立即从列表消失，失败时可靠恢复，并缩短后端删除持久化耗时。

**Architecture:** 以纯 TypeScript 状态转换函数承载乐观移除和恢复，工作台只负责调用 API 与安排静默校准。后端删除路由显式声明删除函数可能修改的状态集合，让现有持久化中间件执行局部脏数据检测。

**Tech Stack:** Vue 3、TypeScript、Node assert 单测 runner、FastAPI、Pytest、PostgreSQL 状态仓库、Git、SSH。

## Global Constraints

- 确认删除后立即隐藏文件；接口失败时恢复到原位置并提示。
- 接口成功后只静默刷新当前节点包，不重新加载整个工作台。
- 不改变删除权限、已提交文件保护、审计和幂等语义。
- 不引入新依赖。

---

### Task 1: 前端可回滚乐观删除

**Files:**
- Create: `frontend/src/views/AICheck/projectFileDeletion.ts`
- Create: `frontend/src/views/AICheck/projectFileDeletion.test.ts`
- Modify: `frontend/src/views/AICheck/Workbench.vue:3178-3214`

**Interfaces:**
- Consumes: `NodePackagePayload`、目标 `documentId`。
- Produces: `removeProjectFileLocally(packageData, documentId): ProjectFileRemoval` 与 `restoreProjectFileLocally(packageData, removal): NodePackagePayload`。

- [ ] **Step 1: 写失败测试**

使用手工构造的节点包断言：目标文件被立即移除并记录原索引；恢复后顺序与原列表相同；
不存在的目标不改变列表；重复恢复不产生重复项。

- [ ] **Step 2: 运行测试并确认失败原因正确**

Run: `cd frontend && pnpm test:unit`

Expected: FAIL，原因是 `projectFileDeletion` 模块不存在。

- [ ] **Step 3: 实现最小状态转换函数并接入工作台**

确认框完成后调用 `removeProjectFileLocally` 并立即写回 `nodePackage`。接口失败或空响应时调用
`restoreProjectFileLocally`；成功时调用 `void loadNodePackage(activeNodeId.value, { silent: true })`
进行后台校准，不再调用 `loadProjectBundle()`。

- [ ] **Step 4: 运行前端测试**

Run: `cd frontend && pnpm test:unit`

Expected: 所有单元测试通过。

---

### Task 2: 后端删除请求局部持久化

**Files:**
- Modify: `backend/apps/api/routes.py:2212-2347,7824-7870`
- Modify: `backend/tests/test_contract.py:6950-7010`

**Interfaces:**
- Consumes: `remove_project_document_records` 当前修改的状态集合。
- Produces: `PROJECT_DOCUMENT_DELETE_STATE_KEYS: frozenset[str]`，并通过 `request.state.flush_state_keys` 传给现有中间件。

- [ ] **Step 1: 写失败测试**

在删除契约测试中监视 `repo.flush_to_sync_postgres`，断言收到的 `selected_state_keys` 精确包含
`documents`、`versions`、`bindings`、`extracted_fields`、`evidence_links`、
`knowledge_files`、`knowledge_chunks`、`knowledge_vectors`、`knowledge_tasks`、`ocr_jobs`、
`ocr_parse_results`、`ocr_corrections`、`upload_sessions`、`submission_drafts` 和 `audit_logs`。

- [ ] **Step 2: 运行定向测试并确认失败原因正确**

Run: `cd backend && pytest -q tests/test_contract.py -k project_file_upload_retry_and_delete`

Expected: FAIL，实际 `selected_state_keys` 为 `None`。

- [ ] **Step 3: 设置删除请求的局部状态集合**

定义不可变状态键集合；删除函数成功完成后、返回响应前，将该集合复制到
`request.state.flush_state_keys`。保留中间件对审计和幂等结果的现有处理。

- [ ] **Step 4: 运行后端定向测试**

Run: `cd backend && pytest -q tests/test_contract.py -k project_file_upload_retry_and_delete`

Expected: PASS，且原有关联删除断言继续通过。

---

### Task 3: 回归验证、提交和发布

**Files:**
- Verify: all files changed in Tasks 1-2

**Interfaces:**
- Consumes: Task 1 和 Task 2 的已通过实现。
- Produces: 可发布的前后端提交与服务器验证结果。

- [ ] **Step 1: 运行完整前端验证**

Run: `cd frontend && pnpm test:unit && pnpm ts:check && pnpm build:pro`

- [ ] **Step 2: 运行后端相关回归**

Run: `cd backend && pytest -q tests/test_contract.py -k 'project_file_upload_retry_and_delete or project_document_endpoints_use_detached_latest_read_view'`

- [ ] **Step 3: 检查差异和工作树**

Run: `git diff --check && git status --short && git diff --stat`

- [ ] **Step 4: 提交并推送当前分支**

```bash
git add docs/superpowers/specs/2026-08-12-project-file-immediate-delete-design.md \
  docs/superpowers/plans/2026-08-12-project-file-immediate-delete.md \
  frontend/src/views/AICheck/projectFileDeletion.ts \
  frontend/src/views/AICheck/projectFileDeletion.test.ts \
  frontend/src/views/AICheck/Workbench.vue \
  backend/apps/api/routes.py backend/tests/test_contract.py
git commit -m "fix: remove project files from workbench immediately"
git push origin codex/local-data-server-migration
```

- [ ] **Step 5: 通过现有部署脚本同步服务器并验证**

使用仓库既有跳板机部署参数发布前端与后端，随后检查服务健康状态、部署版本，并用测试角色
执行一次未提交文件删除验证。
