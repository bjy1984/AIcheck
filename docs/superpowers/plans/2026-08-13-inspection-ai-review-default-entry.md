# 监检人员默认进入 AI 审查页实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将监检人员所有无显式深链接的初始入口统一切换到 `/ai-review-b`，同时保留原监检工作台和其他角色入口。

**Architecture:** 以前端 `getRoleDefaultPath()` 和后端 `ROLE_DEFAULT_PATHS` 作为两端统一入口来源，现有登录、权限守卫、密码修改和动态菜单继续消费这些来源。AI 审查页沿用已有的无参数项目/节点选择与 URL 回写逻辑，不新增状态存储或重定向层。

**Tech Stack:** Vue 3、Vue Router、TypeScript、Pinia、FastAPI、Pytest、Playwright。

## Global Constraints

- 仅改变 `inspection` 角色默认入口，其他角色保持原路径。
- `/workbench/inspection` 必须继续可直接访问。
- 合法的监检深链接及其查询参数不能被默认入口覆盖。
- 不改变 AI 审查业务接口、权限模型或工作区初始化逻辑。
- 前后端默认路径与部署契约必须保持一致。

---

### Task 1: 前端角色默认入口契约

**Files:**
- Create: `frontend/src/utils/roleAccess.test.ts`
- Modify: `frontend/src/utils/roleAccess.ts:15-82`
- Test: `frontend/src/utils/roleAccess.test.ts`

**Interfaces:**
- Consumes: `getRoleDefaultPath(role?: string): string`、`resolveRoleEntryPath(role?: string, redirect?: string): string`、`isPathAllowedForRole(path: string, role?: string): boolean`。
- Produces: `inspection` 的默认路径 `/ai-review-b`；保留 `/workbench/inspection` 作为合法监检深链接。

- [ ] **Step 1: 写入失败的前端行为测试**

```ts
import assert from 'node:assert/strict'
import { getRoleDefaultPath, resolveRoleEntryPath } from './roleAccess'

assert.equal(getRoleDefaultPath('inspection'), '/ai-review-b')
assert.equal(resolveRoleEntryPath('inspection'), '/ai-review-b')
assert.equal(resolveRoleEntryPath('inspection', '/'), '/ai-review-b')
assert.equal(
  resolveRoleEntryPath('inspection', '/ai-review-b?projectId=P-1&nodeId=2'),
  '/ai-review-b?projectId=P-1&nodeId=2'
)
assert.equal(
  resolveRoleEntryPath('inspection', '/workbench/inspection?projectId=P-1&nodeId=2'),
  '/workbench/inspection?projectId=P-1&nodeId=2'
)
assert.equal(resolveRoleEntryPath('inspection', '/workbench/contractor'), '/ai-review-b')
assert.equal(getRoleDefaultPath('contractor'), '/workbench/contractor')
assert.equal(getRoleDefaultPath('ndt'), '/workbench/ndt')
assert.equal(getRoleDefaultPath('owner'), '/workbench/owner')
assert.equal(getRoleDefaultPath('admin'), '/admin/overview')
assert.equal(getRoleDefaultPath('fde'), '/fde/dashboard')
```

- [ ] **Step 2: 运行测试并确认因旧默认路径失败**

Run: `cd frontend && pnpm test:unit`

Expected: `roleAccess.test.ts` 失败，实际值为 `/workbench/inspection`；既有测试继续执行。

- [ ] **Step 3: 最小化修改前端角色默认路径**

```ts
export const ROLE_DEFAULT_PATHS: Record<AicheckRole, string> = {
  inspection: '/ai-review-b',
  contractor: '/workbench/contractor',
  ndt: '/workbench/ndt',
  owner: '/workbench/owner',
  admin: '/admin/overview',
  fde: '/fde/dashboard',
  test: '/workbench/inspection'
}
```

同时将监检角色的合法路径判断扩展为同时允许 `/ai-review-b` 与 `/workbench/inspection`；不能依赖新的默认路径把旧工作台排除。

- [ ] **Step 4: 运行前端单元测试并确认通过**

Run: `cd frontend && pnpm test:unit`

Expected: 所有 `*.test.ts` 通过，零失败。

- [ ] **Step 5: 提交前端入口改动**

```bash
git add frontend/src/utils/roleAccess.ts frontend/src/utils/roleAccess.test.ts
git commit -m "feat: default inspection users to AI review"
```

### Task 2: 后端认证、菜单和部署契约

**Files:**
- Modify: `backend/libs/security/auth.py:42-50`
- Modify: `backend/scripts/deployment_report.py:2972-2981`
- Modify: `backend/tests/test_contract.py:5624-5647`
- Modify: `backend/tests/test_review_b_workspace.py:88-96`
- Modify: `backend/tests/test_deployment_report.py:520-558`

**Interfaces:**
- Consumes: `ROLE_DEFAULT_PATHS`、`simple_routes(role)`、`role_contract_check(...)`、认证接口 `/api/auth/login`。
- Produces: 后端登录/用户公开数据返回 `/ai-review-b`，监检动态菜单重定向到 `/ai-review-b`，部署契约认可这一角色特例。

- [ ] **Step 1: 修改后端测试的期望行为**

在 `test_login_compatibility_paths` 中把监检字面期望改为 `/ai-review-b`；在 `test_review_b_routes_and_api_are_limited_to_inspection_role` 中增加：

```py
workbench_route = next(route for route in routes if route["path"] == "/workbench")
assert workbench_route["redirect"] == "/ai-review-b"
```

在部署契约测试输入中把监检路径改为 `/ai-review-b`，并保持测试只报告 contractor 的错误路径。

- [ ] **Step 2: 运行聚焦测试并确认因后端旧路径失败**

Run: `cd backend && .venv/bin/pytest tests/test_contract.py::test_login_compatibility_paths tests/test_review_b_workspace.py::test_review_b_routes_and_api_are_limited_to_inspection_role tests/test_deployment_report.py::test_role_contract_check_fails_bad_paths_owner_write_and_missing_specs -q`

Expected: 监检默认路径、菜单重定向或部署契约期望至少一项失败，实际值仍为 `/workbench/inspection`。

- [ ] **Step 3: 最小化修改后端默认路径和部署契约**

```py
ROLE_DEFAULT_PATHS = {
    "inspection": "/ai-review-b",
    "contractor": "/workbench/contractor",
    "ndt": "/workbench/ndt",
    "owner": "/workbench/owner",
    "admin": "/admin/overview",
    "fde": "/fde/dashboard",
    "test": "/workbench/inspection",
}
```

`role_contract_check` 对 `inspection` 使用 `/ai-review-b` 作为字面期望，对 `admin`、`fde` 和其余角色保留既有规则。

- [ ] **Step 4: 运行聚焦后端测试并确认通过**

Run: `cd backend && .venv/bin/pytest tests/test_contract.py::test_login_compatibility_paths tests/test_review_b_workspace.py::test_review_b_routes_and_api_are_limited_to_inspection_role tests/test_deployment_report.py::test_role_contract_check_fails_bad_paths_owner_write_and_missing_specs -q`

Expected: 3 passed。

- [ ] **Step 5: 提交后端契约改动**

```bash
git add backend/libs/security/auth.py backend/scripts/deployment_report.py backend/tests/test_contract.py backend/tests/test_review_b_workspace.py backend/tests/test_deployment_report.py
git commit -m "feat: align inspection default route contracts"
```

### Task 3: 全量验证和本地系统验证

**Files:**
- Modify only if a failing verification exposes a confirmed regression; any fix must start with a focused failing test.

**Interfaces:**
- Consumes: 前后端入口行为和已有本地启动命令。
- Produces: 自动化、类型检查、构建和真实浏览器登录导航证据。

- [ ] **Step 1: 运行前端全量单元测试和类型检查**

Run: `cd frontend && pnpm test:unit && pnpm ts:check`

Expected: 两个命令均退出 0。

- [ ] **Step 2: 运行相关后端测试集合**

Run: `cd backend && .venv/bin/pytest tests/test_contract.py tests/test_review_b_workspace.py tests/test_deployment_report.py -q`

Expected: 零失败。

- [ ] **Step 3: 构建前端生产包**

Run: `cd frontend && pnpm build:pro`

Expected: 审计与 Vite 构建均退出 0。

- [ ] **Step 4: 启动本地后端和前端**

Run backend: `cd backend && .venv/bin/uvicorn apps.api.main:app --host 127.0.0.1 --port 8000`

Run frontend: `cd frontend && pnpm dev:live:frontend-only --host 127.0.0.1`

Expected: 后端健康接口可访问，Vite 输出本地 URL。

- [ ] **Step 5: 用真实浏览器验证角色入口和往返导航**

使用监检账号验证：无重定向登录进入 `/ai-review-b`；页面自动选择项目和节点并回写查询参数；刷新保持上下文；“审查列表”进入 `/workbench/inspection`；旧工作台“AI审查”按钮返回 AI 审查页。再使用 contractor 账号抽查仍进入 `/workbench/contractor`。

- [ ] **Step 6: 检查最终改动范围**

Run: `git status --short && git diff HEAD~2 --check && git log -3 --oneline`

Expected: 无空白错误；仅包含设计、计划、入口配置及对应测试改动。
