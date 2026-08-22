# AI 监检端到端缺陷修整实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 2026-08-22 端到端测试发现的注册、项目授权、单位隔离、批量上传和 AI 调度缺陷，使管理员与项目负责人均可发起公开注册，注册成员可按角色安全办理业务，并通过正式环境回归门禁。

**Architecture:** 注册链路继续采用“项目链接不绑定角色、申请人自选角色、审核通过后创建账号”的模型，但把公开访问、申请持久化、组织映射和项目授权做成服务端强约束。文件读取统一经过“项目成员＋节点范围＋来源单位”授权函数，不能只在前端过滤。上传会话按整批事务一致性处理，AI 调度的 ready 必须来自真实运行依赖而不是仅检查配置值。

**Tech Stack:** FastAPI、PostgreSQL 状态仓储、Vue 3、Element Plus、TypeScript、Node assert 单测、pytest、Playwright。

**Spec:** `audit-reports/e2e-20260822/test-report.md`

## Global Constraints

- 匿名访问只开放 `GET /registration-links/{token}` 和 `POST /registration-links/{token}/apply`；链接生成、停用、申请列表和审核仍必须登录。
- 可注册角色固定为 `inspection`、`contractor`、`ndt`、`owner`；不得允许 `admin` 或 `fde`。
- 待审核期间不得创建 `users` 记录或可登录凭证。
- 审核通过必须在同一持久化事务中创建用户、项目成员授权、更新申请状态和审计记录。
- 项目成员的组织必须由项目角色映射取得：`ownerOrgName`、`contractorOrgName`、`ndtOrgName`、`inspectionOrgName`。
- 施工方和无损检测方只能读取本单位文件；监检方可读取授权节点内参建方文件；建设方只读已正式提交资料。
- 不降低 OCR、切片、向量化、证据确认和 `If-Match` 现有门禁。
- Temporal 模式在服务、schema 或 worker 未就绪时必须 fail-fast；不得把“已配置”当成“可调度”。
- 修复不得依赖兼容 mock、Demo 用户、关闭鉴权或生产环境强制降级。
- 当前工作区已有用户改动；实施时只提交本任务明确列出的文件，不使用 `git add .`。

---

## 里程碑和发布顺序

| 阶段 | 范围 | 上线门禁 |
|---|---|---|
| M1 安全主链路 | Task 1–3 | 公开注册可用、成员授权完整、施工方/NDT 无跨单位读取 |
| M2 资料办理 | Task 4 | 15 文件多选不丢失、8 份 NDT 文件全部自动挂载 |
| M3 AI 稳定性 | Task 5–6 | Temporal fail-fast、AI 时间线与建议结论一致、控制台无组件告警 |
| M4 全链路复测 | Task 7 | 原测试方案全部重跑，P0/P1 为 0，正式 AI 复核有真实证据链 |

## 文件结构与职责

- `backend/apps/api/main.py`：精确声明匿名注册链接路由，不扩大公共面。
- `backend/apps/api/project_registration_routes.py`：注册链接、申请和审批流程；写入 scoped persistence。
- `backend/libs/db/repository.py`：注册集合持久化、文档来源单位标识和上传会话批量一致性。
- `backend/apps/api/routes.py`：复用项目成员授权规则、统一文档读取授权、NDT 批量挂载。
- `backend/libs/integrations/task_dispatcher.py`：AI 调度就绪判断。
- `backend/libs/node_review_timeline.py`：AI/人工时间线结论摘要。
- `frontend/src/views/AICheck/AdminOverview.vue`：管理员注册链接入口。
- `frontend/src/views/AICheck/Workbench.vue`：项目负责人注册链接入口与 AI 结果展示。
- `frontend/src/views/AICheck/components/ProjectRegistrationPanel.vue`：管理员和项目负责人复用的生成/审核面板。
- `frontend/src/views/AICheck/components/UploadFilePicker.vue`：多文件选择状态合并。
- `backend/tests/test_project_registration.py`：注册权限和状态机单测。
- `backend/tests/test_project_registration_persistence.py`：注册申请 PostgreSQL 重启恢复测试。
- `backend/tests/test_role_isolation_audit_fixes.py`：跨单位文档读取回归。
- `backend/tests/test_upload_scoped_persistence.py`：多文件上传和 NDT 挂载回归。
- `backend/tests/test_task_lifecycle_p1.py`：AI 调度就绪与失败状态回归。
- `frontend/src/views/AICheck/projectRegistrationEntry.test.ts`：前端双入口结构回归。
- `frontend/src/views/AICheck/components/uploadFileSelection.test.ts`：多选文件不丢失回归。
- `frontend/src/views/AICheck/aiTimelineConclusion.test.ts`：时间线结论一致性回归。
- `frontend/e2e/project-registration-upload-review.spec.ts`：独立端到端验收脚本。

---

### Task 1: 恢复管理员和项目负责人的公开注册入口

**Defects:** P0-01、P0-02

**Files:**
- Modify: `backend/apps/api/main.py:445-460`
- Modify: `frontend/src/views/AICheck/AdminOverview.vue:342-348, 3580-3810`
- Modify: `frontend/src/views/AICheck/Workbench.vue`
- Modify: `frontend/src/types/aicheck.ts`
- Modify: `frontend/src/api/aicheck/index.ts`
- Test: `backend/tests/test_project_registration.py`
- Create: `frontend/src/views/AICheck/projectRegistrationEntry.test.ts`

**Interfaces:**
- Produces: `canManageRegistration: boolean` in the current workbench context.
- Consumes: existing `ProjectRegistrationPanel(projectId, projectName)`.
- Security boundary: only exact anonymous inspect/apply routes bypass authentication.

- [ ] **Step 1: Add failing public-route tests**

Add cases that force `AICHECK_REQUIRE_AUTH=true` and call both prefixed and unprefixed routes without authorization:

```python
@pytest.mark.parametrize("prefix", ["", "/api"])
def test_registration_link_inspect_and_apply_are_public_when_auth_is_required(monkeypatch, prefix):
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    token = _make_link()["data"]["token"]
    assert client.get(f"{prefix}/registration-links/{token}").json()["code"] == 0
    applied = client.post(
        f"{prefix}/registration-links/{token}/apply",
        json={"username": f"public-{prefix or 'root'}", "role": "contractor", "password": GOOD_PASSWORD},
    ).json()
    assert applied["code"] == 0
    assert applied["data"]["status"] == "待审核"
```

Also assert that anonymous `POST /projects/{id}/registration-links`, disable, list, and review still return 401.

- [ ] **Step 2: Run the tests and confirm they fail with `AUTH_REQUIRED`**

Run:

```bash
cd backend
.venv/bin/pytest -q tests/test_project_registration.py -k 'public_when_auth_is_required or anonymous_cannot_manage'
```

Expected: inspect/apply fail before the fix; management endpoints remain protected.

- [ ] **Step 3: Implement an exact public-route matcher**

In `main.py`, avoid a broad `startswith('/api/registration-links/')` rule. Add a helper that accepts only:

```python
PUBLIC_REGISTRATION_LINK_PATTERN = re.compile(
    r"^(?:/api)?/registration-links/[^/]+(?:/apply)?$"
)

def is_public_registration_request(request: Request) -> bool:
    path = request.url.path
    if request.method == "GET":
        return bool(re.fullmatch(r"(?:/api)?/registration-links/[^/]+", path))
    if request.method == "POST":
        return bool(re.fullmatch(r"(?:/api)?/registration-links/[^/]+/apply", path))
    return False
```

Return `False` from `auth_required_for_path()` only when this helper is true.

- [ ] **Step 4: Add a front-end structural test for both entry points**

The test must assert:

```ts
assert.match(adminOverview, /<ProjectRegistrationPanel/)
assert.match(adminOverview, /v-model="projectRegistrationVisible"/)
assert.match(workbench, /canManageRegistration/)
assert.match(workbench, /ProjectRegistrationPanel/)
```

It must also verify the admin drawer is outside all `ElTabPane` blocks, not nested under the organization tab.

- [ ] **Step 5: Move the admin drawer and expose project-leader capability**

- Move the admin `ElDrawer` containing `ProjectRegistrationPanel` to the root of `AdminOverview` after `ElTabs`.
- Add `canManageRegistration` to the backend workbench context using the same `can_manage_project_registration()` rule as the API.
- Extend the TypeScript payload type with `canManageRegistration: boolean`.
- In the inspection workbench, show “注册链接与审核” only when this value is true and mount the same `ProjectRegistrationPanel` in a drawer.
- Do not infer project-leader status solely from role `inspection`.

- [ ] **Step 6: Run registration and front-end unit tests**

```bash
cd backend
.venv/bin/pytest -q tests/test_project_registration.py
cd ../frontend
pnpm test:unit
pnpm ts:check
```

- [ ] **Step 7: Commit the public registration entry fix**

```bash
git add backend/apps/api/main.py backend/tests/test_project_registration.py \
  frontend/src/views/AICheck/AdminOverview.vue frontend/src/views/AICheck/Workbench.vue \
  frontend/src/types/aicheck.ts frontend/src/api/aicheck/index.ts \
  frontend/src/views/AICheck/projectRegistrationEntry.test.ts
git commit -m "fix: restore public project registration entry"
```

---

### Task 2: 持久化注册状态并创建完整项目成员授权

**Defects:** P0-03、P1-01、P1-02

**Files:**
- Modify: `backend/libs/db/repository.py:88-197`
- Modify: `backend/apps/api/project_registration_routes.py:111-408`
- Modify: `backend/apps/api/routes.py:5581-5697`
- Test: `backend/tests/test_project_registration.py`
- Create: `backend/tests/test_project_registration_persistence.py`

**Interfaces:**
- Produces persistent collections `project_invitations` and `registration_requests`.
- Reuses `resolve_project_member_grant(project_id, role) -> {nodeScope, actions}`.
- Produces complete `ProjectMember` records with `orgId`, `orgName`, `nodeScope`, `actions`, `revision`, and `updatedAt`.

- [ ] **Step 1: Add failing member-grant tests**

For all four roles, approve an application and assert:

```python
ROLE_ORG_FIELDS = {
    "inspection": "inspectionOrgName",
    "contractor": "contractorOrgName",
    "ndt": "ndtOrgName",
    "owner": "ownerOrgName",
}

assert member["orgName"] == project[ROLE_ORG_FIELDS[role]]
assert member["orgId"]
assert member["nodeScope"]
assert member["actions"]
assert "project:view" in member["actions"]
```

After approval, log in and assert `/api/workbench/projects?role={role}` contains the project without a manual repair call.

- [ ] **Step 2: Add a failing PostgreSQL restart test**

Use `isolated_postgres_url`, create one link and one pending application, dispose the repository, create a fresh repository against the same schema, and assert:

```python
assert restored_invite["useCount"] == 1
assert restored_request["status"] == "待审核"
assert "passwordHash" in restored_request
```

After approval and a second reload, assert the request remains `已通过` and the password hash is never returned by the list endpoint.

- [ ] **Step 3: Register both collections with the repository**

Add to `STATE_COLLECTIONS`:

```python
"project_invitations": "project_invitations",
"registration_requests": "registration_requests",
```

Ensure `runtime_initial_state()` and empty repository initialization include them automatically through `STATE_COLLECTIONS`.

- [ ] **Step 4: Make every registration mutation declare scoped records**

Add a route-local helper returning only the affected invitation, request, user, member, audit and admin singleton. Each create/disable/apply/review producer must set `request.state.scoped_flush_records` before returning.

The approval transaction must persist these records together:

```python
{
    "project_invitations": [invite],
    "registration_requests": [record],
    "users": [user],
    "project_members": [member],
    "audit_logs": [audit],
    "admin_config": repo.state["admin_config"],
}
```

- [ ] **Step 5: Reuse the canonical grant resolver during approval**

Replace the minimal member literal with the same grant contract used by `authorize_member()`:

```python
org_field = {
    "inspection": "inspectionOrgName",
    "contractor": "contractorOrgName",
    "ndt": "ndtOrgName",
    "owner": "ownerOrgName",
}[record["role"]]
org_name = str(project.get(org_field) or "")
org = find_org_unit(None, org_name)
grant = resolve_project_member_grant(project_id, record["role"])
member = {
    "id": f"PM-{secrets.token_hex(4).upper()}",
    "projectId": project_id,
    "userId": user["id"],
    "name": record["displayName"],
    "orgId": (org or {}).get("id"),
    "orgName": org_name,
    "role": record["role"],
    "nodeScope": grant["nodeScope"],
    "actions": grant["actions"],
    "status": "启用",
    "isProjectLeader": False,
    "updatedAt": server_time(),
    "revision": 1,
}
```

Also reject approval when the project has no configured organization for the requested role; do not silently fall back to the contractor organization.

- [ ] **Step 6: Prevent duplicate user/member creation under concurrent review**

Add an idempotency and concurrency test where two reviewers approve the same request. Assert exactly one `users` row, one project member and one successful review response. Keep the second response as conflict or idempotent replay.

- [ ] **Step 7: Run persistence and registration tests**

```bash
cd backend
.venv/bin/pytest -q tests/test_project_registration.py tests/test_project_registration_persistence.py
```

- [ ] **Step 8: Commit registration persistence and grant creation**

```bash
git add backend/libs/db/repository.py backend/apps/api/project_registration_routes.py \
  backend/apps/api/routes.py backend/tests/test_project_registration.py \
  backend/tests/test_project_registration_persistence.py
git commit -m "fix: persist registration and grant project access"
```

---

### Task 3: 强制施工方和无损检测方单位级文件隔离

**Defect:** P0-04

**Files:**
- Modify: `backend/libs/db/repository.py:1079-1168, 1255-1396`
- Modify: `backend/apps/api/routes.py:3216-3323, 6831-6877, 6976-7005`
- Test: `backend/tests/test_role_isolation_audit_fixes.py`
- Test: `backend/tests/test_read_endpoint_handler_guards.py`
- Create: `backend/tests/test_document_org_isolation.py`

**Interfaces:**
- Produces `sourceOrgId: string | None` on new documents and knowledge-file projections.
- Produces `document_read_error(request, project_id, document) -> JSONResponse | None`.
- All list/detail/preview/download/office-preview endpoints consume the same authorization result.

- [ ] **Step 1: Add failing list and direct-ID tests**

Create contractor A, contractor B and NDT documents in the same project. Assert:

```python
assert contractor_a_files == {"DOC-CONTRACTOR-A"}
assert contractor_b_files == {"DOC-CONTRACTOR-B"}
assert ndt_files == {"DOC-NDT-A"}
assert inspection_files == {"DOC-CONTRACTOR-A", "DOC-CONTRACTOR-B", "DOC-NDT-A"}
```

For each unauthorized document, assert 403 or non-enumerating 404 from:

- document detail;
- preview URL;
- download URL;
- original bytes;
- office preview;
- node package and project file list.

- [ ] **Step 2: Add stable source organization identity**

Extend upload session creation with `source_org_id`, and store both `sourceOrgId` and `sourceOrgName` on documents and knowledge-file projections. Resolve the ID from the current active project member, never from caller-supplied JSON.

Existing documents without `sourceOrgId` use normalized `sourceOrgName` only as a compatibility fallback.

- [ ] **Step 3: Implement one actor-aware visibility function**

The function must apply this matrix:

```python
if role in {"admin", "fde", "inspection"}:
    return True
if role in {"contractor", "ndt"}:
    return document.sourceOrgId == member.orgId  # name fallback for legacy rows
if role == "owner":
    return document_is_submitted(document)
return False
```

Node scope remains an additional condition; it does not replace organization matching.

- [ ] **Step 4: Apply the guard to every read path**

Filter project file lists and node packages before serialization. Direct resource endpoints must call the same guard after resolving `documentId`, preventing URL guessing from bypassing list filtering.

- [ ] **Step 5: Add same-name/different-ID regression coverage**

Two organizations with the same display name but different IDs must not share files. This verifies the implementation prioritizes `sourceOrgId` over names.

- [ ] **Step 6: Run security regression tests**

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_document_org_isolation.py \
  tests/test_role_isolation_audit_fixes.py \
  tests/test_read_endpoint_handler_guards.py \
  tests/test_idempotency_membership_scope.py
```

- [ ] **Step 7: Commit organization-level file isolation**

```bash
git add backend/libs/db/repository.py backend/apps/api/routes.py \
  backend/tests/test_document_org_isolation.py \
  backend/tests/test_role_isolation_audit_fixes.py \
  backend/tests/test_read_endpoint_handler_guards.py
git commit -m "fix: isolate project files by participant organization"
```

---

### Task 4: 修复多文件选择和 NDT 批量挂载一致性

**Defects:** P1-03、P1-04

**Files:**
- Modify: `frontend/src/views/AICheck/components/UploadFilePicker.vue:1-55`
- Modify: `frontend/src/views/AICheck/components/uploadFileSelection.ts`
- Modify: `frontend/src/views/AICheck/components/uploadFileSelection.test.ts`
- Modify: `backend/apps/api/routes.py:6976-7170, 7489-7525`
- Modify: `backend/libs/db/repository.py:1255-1404`
- Modify: `backend/tests/test_upload_scoped_persistence.py`
- Create: `backend/tests/test_multi_file_upload_session.py`

**Interfaces:**
- Produces `rawFilesFromUploadList(uploadFiles: UploadFile[]): File[]`.
- Complete-session response invariant: `fileCount == len(documents) == len(completedFiles)` for NDT atomic uploads.
- Each NDT atomic document produces bindings for all declared `nodeIds`.

- [ ] **Step 1: Add a failing 15-file selection test**

Simulate Element Plus firing `on-change` once per selected file while its `uploadFiles` argument grows from 1 to 15. Assert the final model contains all 15 unique identities in selection order.

- [ ] **Step 2: Change the picker to consume the complete upload list**

Use the second `on-change` argument:

```ts
const handleUploadChange = (_current: UploadFile, uploadFiles: UploadFile[]) => {
  appendFiles(uploadFiles.flatMap((item) => (item.raw ? [item.raw] : [])))
}
```

Keep `appendUniqueUploadFiles` as the single deduplication policy. Preserve the existing unsupported-extension warning.

- [ ] **Step 3: Add a failing eight-file HTTP upload test**

Against isolated PostgreSQL:

1. Create one 8-file NDT atomic session.
2. PUT all eight file bodies.
3. Complete the session.
4. Assert eight documents have current versions with hash and `bodyUploaded=true`.
5. Assert all eight response `documents` entries exist.
6. Assert expected binding counts: organization certificate 1, six person certificates 6, plan 2.

- [ ] **Step 4: Make upload file updates merge-safe**

Before updating a session file, reload the authoritative session/document/version rows inside the mutation transaction. Persist the entire affected upload session plus every document/version in that session, not only the last file touched. Completion must fail atomically if any expected version lacks a stored body hash.

- [ ] **Step 5: Make NDT draft creation total, not best-effort**

`create_ndt_atomic_drafts_for_completed_session()` must return one result per atomic input or a structured error. Remove silent `continue` on invalid IDs. Complete-session code must compare the atomic input document IDs with the created result IDs and return a validation failure without marking the session complete when they differ.

- [ ] **Step 6: Run upload tests**

```bash
cd frontend
pnpm test:unit
pnpm ts:check
cd ../backend
.venv/bin/pytest -q tests/test_upload_scoped_persistence.py tests/test_multi_file_upload_session.py
```

- [ ] **Step 7: Commit batch upload consistency**

```bash
git add frontend/src/views/AICheck/components/UploadFilePicker.vue \
  frontend/src/views/AICheck/components/uploadFileSelection.ts \
  frontend/src/views/AICheck/components/uploadFileSelection.test.ts \
  backend/apps/api/routes.py backend/libs/db/repository.py \
  backend/tests/test_upload_scoped_persistence.py backend/tests/test_multi_file_upload_session.py
git commit -m "fix: preserve multi-file uploads and ndt bindings"
```

---

### Task 5: 让 AI 调度就绪状态与真实依赖一致

**Defect:** P1-05

**Files:**
- Modify: `backend/libs/integrations/task_dispatcher.py:308-330`
- Modify: `backend/libs/runtime_readiness.py`
- Modify: `backend/apps/api/routes.py:9724-9765`
- Test: `backend/tests/test_task_lifecycle_p1.py`
- Test: `backend/tests/test_main_chain_e2e.py`

**Interfaces:**
- Produces `ai_recheck_dispatch_readiness() -> {ready, mode, reason, dependencies}`.
- Temporal readiness requires service connectivity, workflow schema and fresh review-worker heartbeat.
- Inline mode remains explicitly available for local development only.

- [ ] **Step 1: Add failing Temporal dependency tests**

Cover these states independently:

| Temporal service | Schema | Worker heartbeat | Expected ready |
|---|---|---|---|
| false | true | true | false |
| true | false | true | false |
| true | true | false | false |
| true | true | true | true |

Also assert the failure response includes dependency-specific reason codes.

- [ ] **Step 2: Pass runtime readiness into dispatcher readiness**

Replace the current unconditional branch for `orchestration_mode == 'temporal'`. Use one shared readiness provider so `/healthz` and AI dispatch cannot disagree.

Expected shape:

```python
{
    "ready": False,
    "mode": "temporal",
    "statusReason": "temporal_worker_unavailable",
    "dependencies": {
        "service": False,
        "schema": False,
        "workerHeartbeat": False,
    },
}
```

- [ ] **Step 3: Fail before creating a queued AI run when dependencies are unavailable**

For formal review, return 409 with a stable business reason and keep node state unchanged. For gap precheck, use the existing local summary only when deployment policy explicitly enables it; label the result `local_disabled_fallback` and never present it as external-model DeepThink.

- [ ] **Step 4: Add deployment preflight coverage**

Update deployment verification so production fails when Temporal mode is configured but the DNS target, schema or worker heartbeat is unavailable.

- [ ] **Step 5: Run lifecycle and readiness tests**

```bash
cd backend
.venv/bin/pytest -q tests/test_task_lifecycle_p1.py tests/test_main_chain_e2e.py tests/test_verify_deployment.py
```

- [ ] **Step 6: Commit AI readiness corrections**

```bash
git add backend/libs/integrations/task_dispatcher.py backend/libs/runtime_readiness.py \
  backend/apps/api/routes.py backend/tests/test_task_lifecycle_p1.py \
  backend/tests/test_main_chain_e2e.py backend/tests/test_verify_deployment.py
git commit -m "fix: gate ai dispatch on live workflow readiness"
```

---

### Task 6: 统一 AI 时间线结论并清除 Element Plus 组件告警

**Defects:** P1-06、P2-01

**Files:**
- Modify: `backend/libs/node_review_timeline.py:40-75`
- Modify: `frontend/src/views/AICheck/Workbench.vue:1745-1785, 5845-5867`
- Modify: `frontend/src/views/AICheck/AdminOverview.vue:1-45`
- Modify: `frontend/src/views/AICheck/autoClassifyAndBatchReview.test.ts`
- Create: `frontend/src/views/AICheck/aiTimelineConclusion.test.ts`

**Interfaces:**
- Timeline AI event conclusion comes from `ai_run.suggestion.result` for completed runs.
- Failed runs show failure reason and never reuse the initial queued placeholder.

- [ ] **Step 1: Add a failing timeline conclusion test**

Given a completed run with `suggestion.result='证据不足'`, assert the timeline event contains:

```python
assert event["conclusion"] == "证据不足"
assert event["summary"] == "证据不足"
```

Given a failed run with no result, assert the summary includes the normalized failure message.

- [ ] **Step 2: Fix timeline result selection**

In `node_review_timeline.py`, derive `conclusion` from the nested suggestion first, then any legacy top-level conclusion:

```python
suggestion = run.get("suggestion") if isinstance(run.get("suggestion"), dict) else {}
conclusion = str(suggestion.get("result") or run.get("conclusion") or "").strip()
```

Do not label a completed run “未给出结论” when the nested suggestion has a result.

- [ ] **Step 3: Add missing Element Plus imports**

Import `ElDropdown`, `ElDropdownItem`, and `ElDropdownMenu` in `AdminOverview.vue`. Add a structural test that every `El*` component used in the template is either imported or globally registered.

- [ ] **Step 4: Run front-end checks and a browser console smoke**

```bash
cd frontend
pnpm test:unit
pnpm ts:check
pnpm test:e2e --grep "inspection switches AI review"
```

Expected: zero unresolved-component warnings for the admin and inspection routes.

- [ ] **Step 5: Commit timeline and component fixes**

```bash
git add backend/libs/node_review_timeline.py \
  frontend/src/views/AICheck/Workbench.vue frontend/src/views/AICheck/AdminOverview.vue \
  frontend/src/views/AICheck/autoClassifyAndBatchReview.test.ts \
  frontend/src/views/AICheck/aiTimelineConclusion.test.ts
git commit -m "fix: align ai timeline conclusions and component imports"
```

---

### Task 7: 建立独立环境的全链路回归与发布门禁

**Scope:** 全部 P0/P1 修复后的最终验收

**Files:**
- Create: `frontend/e2e/project-registration-upload-review.spec.ts`
- Modify: `frontend/playwright.config.ts`
- Modify: `backend/tests/conftest.py`
- Modify: `DEPLOYMENT.md`
- Create: `audit-reports/e2e-remediation-acceptance/README.md`

**Interfaces:**
- E2E 数据库必须使用独立 schema 或独立数据库，禁止连接正在运行的业务库。
- E2E 输出固定保存至 `audit-reports/e2e-remediation-acceptance/`。

- [ ] **Step 1: Enforce isolated test persistence**

Make integration/E2E commands require `AICHECK_TEST_POSTGRES_URL`. Generate a unique schema per run and fail before tests start if the resolved DSN equals the live application DSN without an isolated `search_path`.

- [ ] **Step 2: Implement one serial end-to-end browser spec**

The spec must execute without API workarounds:

1. Admin creates a project.
2. Admin generates link A.
3. Project leader generates link B.
4. Anonymous contractor/NDT/owner/inspection users submit applications.
5. Verify pre-approval login fails.
6. Admin and project leader cross-approve.
7. Verify all four users see the project with correct permissions.
8. Contractor selects 15 files in one chooser and uploads them.
9. NDT uploads 8 typed files and receives complete bindings.
10. Contractor cannot see NDT drafts; NDT cannot see contractor drafts.
11. Owner cannot upload.
12. After OCR/slice/vector readiness, submit both packages.
13. Inspection runs AI review and sees the same conclusion in timeline and result panel.

- [ ] **Step 3: Add environment gates before the browser run**

The runner must assert:

- API, PostgreSQL and object storage ready;
- OCR provider ready;
- embedding/slicing worker ready;
- Temporal service, schema and Review Worker ready;
- fixed clause packages bound to the new project.

Do not switch to inline deterministic mode for the final formal-review acceptance.

- [ ] **Step 4: Run the complete verification suite**

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_project_registration.py \
  tests/test_project_registration_persistence.py \
  tests/test_document_org_isolation.py \
  tests/test_upload_scoped_persistence.py \
  tests/test_multi_file_upload_session.py \
  tests/test_task_lifecycle_p1.py

cd ../frontend
pnpm test:unit
pnpm ts:check
pnpm lint
pnpm build:pro
pnpm playwright test e2e/project-registration-upload-review.spec.ts
```

- [ ] **Step 5: Record acceptance evidence**

The acceptance report must include:

- project ID and build SHA;
- both link issuers and all four registered roles;
- file counts 15 and 8;
- cross-unit isolation API results;
- OCR/slice/vector completion counts;
- AI Run ID, result, confidence, evidence and rule references;
- screenshots for admin link, leader link, uploads, AI result and permission denials;
- zero P0/P1 open defects.

- [ ] **Step 6: Update deployment documentation**

Document the exact required services, preflight command, isolated-test DSN requirement and rollback rule: any registration failure, cross-unit file exposure or AI evidence mismatch blocks release.

- [ ] **Step 7: Commit the final regression gate**

```bash
git add frontend/e2e/project-registration-upload-review.spec.ts frontend/playwright.config.ts \
  backend/tests/conftest.py DEPLOYMENT.md audit-reports/e2e-remediation-acceptance/README.md
git commit -m "test: gate release on project registration workflow"
```

---

## Definition of Done

修整完成必须同时满足：

- 管理员和项目负责人均能从页面生成链接并审核本项目申请。
- 未登录用户能打开有效链接并提交申请，但不能调用任何管理接口。
- 审核前无账号；审核后账号、组织、项目成员、节点范围和动作权限完整。
- 注册邀请、申请和审核状态在 API 重启后保持一致。
- 施工方、无损检测方和建设方无法通过列表或直接资源 ID 读取越权文件。
- 浏览器一次选择 15 个文件时 UI 保留 15 个；NDT 8 文件生成 8 份结构化结果和全部节点绑定。
- Temporal 不可用时前端收到明确门禁信息；Temporal 就绪时 ReviewRun 可完成。
- AI 时间线、建议结论和人工确认区使用同一结论值。
- 管理端和四角色工作台控制台无 unresolved Element Plus component 告警。
- 独立 PostgreSQL 环境中的最终 E2E 全部通过，并生成新的验收报告。

## 回滚策略

- M1 若导致登录或项目成员授权回归，仅回滚 M1 对应提交，不回滚已有安全审计修复。
- M2 若批量上传出现部分成功，关闭前端批量入口并保留单文件上传，直到事务一致性测试通过。
- M3 若 Temporal 调度仍不稳定，正式 AI 复核保持禁用并显示环境门禁；不得自动切到未标识的降级结论。
- 任意跨单位文件读取复现时立即停止发布并撤回该版本。

