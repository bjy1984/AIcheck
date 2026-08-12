# 施工方工作台权限对齐实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 施工方工作台不再调用无权读取的报告/归档接口，同时保持后端 403 权限边界。

**Architecture:** 新建纯函数表达报告/归档加载能力，工作台用该函数选择加载或清空本地状态。纯函数由 Vitest 覆盖，服务器发布仅更新前端静态文件。

**Tech Stack:** Vue 3、TypeScript、Vitest、Vite、Git、SSH。

## Global Constraints

- `contractor` 和 `ndt` 不请求报告/归档接口。
- `inspection` 和 `owner` 保持现有加载行为。
- 不修改后端角色动作表或 403 行为。

---

### Task 1: 对齐工作台加载能力

**Files:**
- Create: `frontend/src/views/AICheck/workbenchRoleAccess.ts`
- Create: `frontend/src/views/AICheck/workbenchRoleAccess.test.ts`
- Modify: `frontend/src/views/AICheck/Workbench.vue:2068-2079,2249-2262`

**Interfaces:**
- Consumes: `RoleCode`。
- Produces: `canLoadReportArchive(role: RoleCode): boolean`。

- [ ] **Step 1: 写失败测试**

断言 `contractor`、`ndt` 返回 `false`，`inspection`、`owner` 返回 `true`。

- [ ] **Step 2: 运行定向测试并确认因模块缺失而失败**

Run: `cd frontend && pnpm vitest run src/views/AICheck/workbenchRoleAccess.test.ts`

- [ ] **Step 3: 实现纯函数并接入工作台**

`loadReportArchive` 在无能力角色下清空 `reports`、`archiveItems` 并返回；项目包加载统一调用该函数，不再为角色复制分支。

- [ ] **Step 4: 验证测试、类型和生产构建**

Run: `cd frontend && pnpm vitest run src/views/AICheck/workbenchRoleAccess.test.ts && pnpm exec vue-tsc --noEmit && pnpm build:pro`

- [ ] **Step 5: 提交、推送并发布前端**

提交修复到当前分支，推送 `origin/codex/local-data-server-migration`，运行 `backend/scripts/deploy_to_server.sh --frontend`，再验证施工方页面及后端权限边界。
