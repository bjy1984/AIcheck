# Admin Project Creation Flow Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the administrator project wizard fail early on unusable participant organizations, return a compact creation payload, render readable project details, and document safe Redis-free local development without weakening strict production.

**Architecture:** Keep authorization truth in the backend and expose no cross-organization fallback. Add small frontend pure helpers for candidate availability and detail formatting, trim only the create-response projections while retaining the stored snapshot, and make local non-strict mode explicit in the runbook. Existing backend validation and strict-production fail-closed behavior remain intact.

**Tech Stack:** Vue 3, TypeScript, Element Plus, Node test runner, FastAPI, Python, pytest, Playwright/in-app browser.

## Global Constraints

- Work directly on the existing `main` branch.
- Do not infer or automatically migrate a user to another organization.
- Candidate users must be enabled, role-matched, and belong to the selected organization using stable organization ID first.
- Persist the complete `businessPackSnapshot`; remove it only from the project creation response projections.
- Keep strict production fail-closed when Redis is unavailable.
- Keep project region optional.

---

### Task 1: Frontend Step-Two Member Availability Gate

**Files:**
- Modify: `frontend/src/views/AICheck/utils/projectWizardMembers.ts`
- Modify: `frontend/src/views/AICheck/AdminOverview.vue`
- Test: `frontend/tests/project-wizard-members.test.mjs`

**Interfaces:**
- Consumes: existing `userBelongsToOrganization(user, organization): boolean` and `wizardUsersByRole(role)`.
- Produces: `findFirstRoleWithoutCandidates<Role>(roles, candidatesByRole): Role | undefined` and `missingWizardMemberMessage(roleLabel, orgName): string`.

- [ ] **Step 1: Write failing helper tests**

Add tests proving that the first role with no candidates is returned, all-populated roles return `undefined`, and the message names both role and organization.

```ts
test('finds the first required role without an eligible member', () => {
  const role = findFirstRoleWithoutCandidates(['owner', 'contractor'], (item) =>
    item === 'owner' ? [{ id: 'USER-OWNER' }] : []
  )
  assert.equal(role, 'contractor')
})
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd frontend && node --test tests/project-wizard-members.test.mjs`

Expected: FAIL because the new helpers are not exported.

- [ ] **Step 3: Implement the minimal pure helpers**

Implement the two exports without UI dependencies. The error text must be `所选{角色标签}「{组织名称}」暂无启用且角色匹配的用户，请先在组织用户中配置。`.

- [ ] **Step 4: Wire the gate into wizard step 2**

After required organization names are non-empty, call `findFirstRoleWithoutCandidates(projectWizardRoles.value, wizardUsersByRole)`. If a role is returned, show `ElMessage.warning(missingWizardMemberMessage(roleLabel(role), wizardOrgNameByRole(role)))` and return `false`. Keep step 3 member-selection validation unchanged.

- [ ] **Step 5: Run focused tests and type checking**

Run:

```bash
cd frontend
node --test tests/project-wizard-members.test.mjs
pnpm ts:check
```

Expected: all tests and type checking pass.

### Task 2: Compact Project Creation Response

**Files:**
- Modify: `backend/apps/api/routes.py`
- Test: `backend/tests/test_contract.py`
- Test: `backend/tests/test_business_pack.py`

**Interfaces:**
- Consumes: `versioned_project(project)` and `project_detail_payload(project_id)`.
- Produces: `project_without_business_pack_snapshot(project): dict[str, Any]`, used only for creation responses.

- [ ] **Step 1: Add failing response-contract assertions**

In the existing project creation tests, assert:

```python
assert "businessPackSnapshot" not in created["project"]
assert "businessPackSnapshot" not in created["detail"]["project"]
stored = repo.require_project(created["project"]["id"])
assert stored["businessPackSnapshot"]["snapshotHash"]
```

Also assert `businessPackVersion`, `businessPackSnapshotHash`, `createdNodeCount`, and `createdRequirementCount` remain present.

- [ ] **Step 2: Run focused backend tests and verify RED**

Run:

```bash
cd backend
pytest tests/test_contract.py::test_project_creation_routes_are_idempotent_and_return_initial_members tests/test_business_pack.py::test_business_pack_catalog_validate_and_project_reuse -q
```

Expected: FAIL because both response projections currently include the snapshot.

- [ ] **Step 3: Add a compact project projection**

Clone the versioned project, remove `businessPackSnapshot`, and return the clone. Do not mutate repository state.

```python
def project_without_business_pack_snapshot(project: dict[str, Any]) -> dict[str, Any]:
    summary = versioned_project(project)
    summary.pop("businessPackSnapshot", None)
    return summary
```

- [ ] **Step 4: Apply the projection to both create-response locations**

Use the helper for top-level `project`. Clone `detail_data` and replace only `detail_data["project"]` with the compact projection. Keep the dedicated snapshot endpoint unchanged.

- [ ] **Step 5: Run focused and related backend tests**

Run:

```bash
cd backend
pytest tests/test_contract.py -k 'project_creation' -q
pytest tests/test_business_pack.py -q
```

Expected: all selected tests pass.

### Task 3: Readable Project Detail Values

**Files:**
- Create: `frontend/src/views/AICheck/utils/projectDetailPresentation.ts`
- Create: `frontend/tests/project-detail-presentation.test.mjs`
- Modify: `frontend/src/views/AICheck/AdminOverview.vue`

**Interfaces:**
- Produces: `formatProjectRegion(value): string`, `formatParticipantType(value): string`, and `formatNodeScope(values): string`.
- Consumes: project detail region, participant `unitType`, and member `nodeScope` values.

- [ ] **Step 1: Write failing presentation tests**

Cover blank/whitespace regions, `owner`, `contractor`, `ndt`, `inspection`, unknown types, `[1,2,3,4,8,10,11,12]`, `[1..69]`, duplicates/out-of-order input, and an empty scope.

```ts
assert.equal(formatNodeScope([1, 2, 3, 4, 8, 10, 11, 12]), '1–4、8、10–12（8 个节点）')
assert.equal(formatProjectRegion('   '), '-')
assert.equal(formatParticipantType('contractor'), '施工方')
```

- [ ] **Step 2: Run the new test and verify RED**

Run: `cd frontend && node --test tests/project-detail-presentation.test.mjs`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the pure formatters**

Sort and deduplicate positive integer node IDs, collapse consecutive runs, join runs with `、`, and append the unique count. Return `-` for no valid nodes. Map known participant types to Chinese and preserve unknown non-empty values.

- [ ] **Step 4: Replace raw values in the detail drawer**

Render region through `formatProjectRegion`, participant type through `formatParticipantType`, and node scope through `formatNodeScope`.

- [ ] **Step 5: Run unit tests and type checking**

Run:

```bash
cd frontend
node --test tests/project-detail-presentation.test.mjs
pnpm ts:check
```

Expected: all tests and type checking pass.

### Task 4: Actionable Redis Security Error and Explicit Local Mode

**Files:**
- Modify: `frontend/src/utils/aicheckError.ts`
- Create: `frontend/tests/aicheck-error.test.mjs`
- Modify: `backend/README.md`
- Test: `backend/tests/test_security_hardening.py`

**Interfaces:**
- Consumes: backend reason `SECURITY_BACKEND_UNAVAILABLE` and `AICHECK_STRICT_PRODUCTION`.
- Produces: a recovery hint directing local developers to start Redis or use non-strict local mode.

- [ ] **Step 1: Write a failing frontend error-message test**

```ts
const message = getAicheckErrorMessage({
  response: { data: { message: '安全服务不可用', data: { reason: 'SECURITY_BACKEND_UNAVAILABLE' } } }
}, '登录失败')
assert.match(message, /启动 Redis/)
assert.match(message, /本地开发模式/)
```

- [ ] **Step 2: Run the error test and verify RED**

Run: `cd frontend && node --test tests/aicheck-error.test.mjs`

Expected: FAIL because the reason has no recovery hint.

- [ ] **Step 3: Add the reason hint**

Add `SECURITY_BACKEND_UNAVAILABLE` to `reasonHints` without changing generic fallback behavior.

- [ ] **Step 4: Make local non-strict startup explicit**

Update the backend Local Run command to include `AICHECK_STRICT_PRODUCTION=false`. Explain that local non-strict mode uses in-memory security sessions when Redis is absent, while strict production requires Redis and deliberately refuses to start or serve security operations without it.

- [ ] **Step 5: Verify both security modes**

Run:

```bash
cd frontend
node --test tests/aicheck-error.test.mjs
cd ../backend
pytest tests/test_security_hardening.py -k 'security_backend or strict_health' -q
```

Expected: frontend recovery text passes; backend strict-mode tests continue to pass.

### Task 5: Integrated Verification and Browser Acceptance

**Files:**
- Modify only if an acceptance defect is discovered: files from Tasks 1–4 and their tests.

**Interfaces:**
- Consumes: running backend at `http://127.0.0.1:8000` and frontend live mode.
- Produces: evidence that the administrator can complete the full project creation flow.

- [ ] **Step 1: Run the complete focused verification set**

Run:

```bash
cd frontend
node --test tests/project-wizard-members.test.mjs tests/project-detail-presentation.test.mjs tests/aicheck-error.test.mjs
pnpm ts:check
cd ../backend
pytest tests/test_contract.py -k 'project_creation' -q
pytest tests/test_business_pack.py tests/test_security_hardening.py -q
```

Expected: all commands pass with no new warnings or errors.

- [ ] **Step 2: Restart or confirm local services in non-strict mode**

Confirm `/healthz` responds, the frontend proxies `/api`, and the administrator login succeeds. Do not stop a user-managed service unless replacement is necessary.

- [ ] **Step 3: Verify the early failure path in the browser**

Open the administrator project wizard, leave region blank, choose a participant organization with no eligible enabled user, and verify the wizard remains on step 2 with a role-and-organization-specific warning.

- [ ] **Step 4: Complete the success path in the browser**

Choose participant organizations that have eligible users, advance to step 3, select all initial members, create the project, and open the details drawer.

- [ ] **Step 5: Inspect response and display evidence**

Verify the create response omits `businessPackSnapshot`, is materially smaller than the former approximately 2.2 MB response, and the drawer shows `-` for blank region, Chinese participant types, and `1–69（69 个节点）`.

- [ ] **Step 6: Review the final diff and commit**

Run `git diff --check`, inspect only intended files, then commit the implementation and tests with a focused message.
