# Optional Project Region Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow an administrator to leave the project region blank while preserving required business-pack selection, generated project type, and project-name validation.

**Architecture:** Keep `region` as the existing string field for compatibility, but remove it from both frontend and backend required-field checks. The selected business pack remains the source of truth for the generated read-only `type` field, and automated tests cover both the wizard transition and API validation boundary.

**Tech Stack:** Vue 3, TypeScript, Element Plus, Playwright, FastAPI, pytest

## Global Constraints

- `businessPackId` remains required and user-selected.
- `type` remains generated from the selected business pack and read-only.
- `region` remains visible but optional; an omitted value is stored as an empty string.
- `name` remains required.
- Do not add an administrative-region dictionary or change existing project data.

---

### Task 1: Make backend region validation optional

**Files:**
- Modify: `backend/tests/test_contract.py:9014-9034`
- Modify: `backend/apps/api/routes.py:28505-28545`

**Interfaces:**
- Consumes: `POST /admin/projects` request body with optional `region?: string`.
- Produces: `create_admin_project()` validation where `missingFields` excludes `region` and the stored project keeps `region: ""` when omitted.

- [ ] **Step 1: Change the contract assertion to define the desired behavior**

In `test_project_creation_rejects_missing_or_invalid_real_configuration_without_partial_writes`, replace the assertion that requires `region` with assertions that the response still rejects missing participant configuration but does not report `region` as missing:

```python
missing_fields = missing["data"]["missingFields"]
assert "region" not in missing_fields
assert "ownerOrgName" in missing_fields
assert "contractorOrgName" in missing_fields
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
cd backend
.venv/bin/python -m pytest -q tests/test_contract.py::test_project_creation_rejects_missing_or_invalid_real_configuration_without_partial_writes
```

Expected: FAIL because `missingFields` still contains `region`.

- [ ] **Step 3: Remove region from backend required fields**

In `create_admin_project`, change:

```python
required_fields = ["name", "region"] + [
```

to:

```python
required_fields = ["name"] + [
```

Keep the existing normalization:

```python
region = str(body.get("region") or "").strip()
```

and keep `"region": region` in the stored project so the response schema remains compatible.

- [ ] **Step 4: Run the backend test and verify GREEN**

Run the same pytest command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit the backend behavior**

```bash
git add backend/apps/api/routes.py backend/tests/test_contract.py
git commit -m "fix: make project region optional"
```

### Task 2: Make the project wizard treat region as optional

**Files:**
- Modify: `frontend/e2e/aicheck-smoke.spec.ts:1880-1925`
- Modify: `frontend/src/views/AICheck/AdminOverview.vue:2065-2082`
- Modify: `frontend/src/views/AICheck/AdminOverview.vue:5178-5184`

**Interfaces:**
- Consumes: `projectWizardForm.businessPackId`, generated `projectWizardForm.type`, required `projectWizardForm.name`, and optional `projectWizardForm.region`.
- Produces: `validateProjectWizardStep(): boolean` that advances with an empty region and emits a specific generated-type failure only if type generation fails.

- [ ] **Step 1: Add a focused failing wizard test**

Add this Playwright test immediately before the existing full project-creation test:

```ts
test('admin can continue when optional project region is blank', async ({ page }) => {
  await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/admin/overview')!)

  await page.getByRole('button', { name: '新建项目' }).evaluate((element) => {
    ;(element as HTMLButtonElement).click()
  })
  const wizard = page.locator('.el-dialog').filter({ hasText: '项目立项向导' })
  await expect(wizard).toBeVisible()
  await wizard
    .locator('.el-form-item')
    .filter({ hasText: '项目名称' })
    .locator('input')
    .fill('区域选填测试项目')

  await expect(wizard).toContainText('区域（选填）')
  await wizard.getByRole('button', { name: '下一步' }).click()
  await expect(wizard).toContainText('参建单位')
  await expect(wizard.getByRole('combobox', { name: '建设单位' })).toBeVisible()
})
```

- [ ] **Step 2: Run the frontend test and verify RED**

Run:

```bash
cd frontend
pnpm playwright test e2e/aicheck-smoke.spec.ts -g "admin can continue when optional project region is blank"
```

Expected: FAIL because the label is currently `区域` and the wizard remains on step 1 with the combined warning.

- [ ] **Step 3: Implement the minimal frontend validation change**

Replace the combined validation:

```ts
if (!projectWizardForm.type.trim() || !projectWizardForm.region.trim()) {
  ElMessage.warning('请填写项目类型和区域')
  return false
}
```

with generated-type validation only:

```ts
if (!projectWizardForm.type.trim()) {
  ElMessage.warning('项目类型生成失败，请重新选择压力管道类别')
  return false
}
```

Change the form item to:

```vue
<ElFormItem label="区域（选填）">
  <ElInput v-model="projectWizardForm.region" placeholder="例如：广东省广州市" />
</ElFormItem>
```

- [ ] **Step 4: Run the focused frontend test and verify GREEN**

Run the same Playwright command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit the frontend behavior**

```bash
git add frontend/src/views/AICheck/AdminOverview.vue frontend/e2e/aicheck-smoke.spec.ts
git commit -m "fix: allow blank project region in wizard"
```

### Task 3: Run regression verification

**Files:**
- Verify: `backend/apps/api/routes.py`
- Verify: `backend/tests/test_contract.py`
- Verify: `frontend/src/views/AICheck/AdminOverview.vue`
- Verify: `frontend/e2e/aicheck-smoke.spec.ts`

**Interfaces:**
- Consumes: the backend and frontend behavior produced by Tasks 1 and 2.
- Produces: evidence that the optional-region flow works without weakening business-pack, project-name, participant-unit, or initial-member validation.

- [ ] **Step 1: Run backend project validation regressions**

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_contract.py::test_project_creation_rejects_missing_or_invalid_real_configuration_without_partial_writes \
  tests/test_contract.py::test_project_creation_routes_are_idempotent_and_return_initial_members
```

Expected: both tests PASS. If the existing successful-creation fixture still reports invalid initial users, report it separately and do not weaken production validation to make the fixture pass.

- [ ] **Step 2: Run frontend type checking**

```bash
cd frontend
pnpm ts:check
```

Expected: PASS with no TypeScript errors.

- [ ] **Step 3: Run both wizard tests**

```bash
cd frontend
pnpm playwright test e2e/aicheck-smoke.spec.ts -g "admin (can continue when optional project region is blank|creates project through setup wizard)"
```

Expected: both tests PASS.

- [ ] **Step 4: Check patch integrity**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only the intended source, test, and plan files are changed or committed.

- [ ] **Step 5: Record final verification commit if needed**

If Task 3 requires no source changes, do not create an empty commit. If a test-only correction is necessary, commit only that correction:

```bash
git add backend/tests/test_contract.py frontend/e2e/aicheck-smoke.spec.ts
git commit -m "test: cover optional project region"
```
