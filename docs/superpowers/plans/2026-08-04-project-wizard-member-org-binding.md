# Project Wizard Member Organization Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make project-wizard member selection and project creation validate organization membership by stable `orgId`, with a legacy name fallback.

**Architecture:** Add one small frontend organization-membership utility shared by candidate filtering and selection clearing. Add one backend helper that compares a projected user with the selected organization record, then use it in project creation while canonicalizing projected organization names from stable IDs.

**Tech Stack:** Vue 3, TypeScript, Node test runner, FastAPI, pytest

## Global Constraints

- Keep business role, enabled-state, business-pack, and node-scope rules unchanged.
- Prefer `orgId` only when both the user and selected organization have IDs.
- Fall back to trimmed organization-name equality for legacy records missing an ID.
- Do not change the wizard layout or project-create request shape.

---

### Task 1: Frontend organization membership

**Files:**
- Create: `frontend/src/views/AICheck/utils/projectWizardMembers.ts`
- Create: `frontend/tests/project-wizard-members.test.mjs`
- Modify: `frontend/src/views/AICheck/AdminOverview.vue:1237-1270`

**Interfaces:**
- Produces: `userBelongsToOrganization(user, organization): boolean`
- Consumes: `user.orgId`, `user.orgName`, `organization.id`, and `organization.name`

- [x] **Step 1: Write the failing frontend test**

Create table-driven cases asserting that a user with `orgId: 'ORG-CONTRACTOR-1'` and stale `orgName` matches an organization with that ID, while a user with another non-empty ID does not match even if the name is equal. Include a legacy case where IDs are absent and trimmed names match.

- [x] **Step 2: Run the frontend test to verify RED**

Run: `node --experimental-strip-types --test tests/project-wizard-members.test.mjs`

Expected: FAIL because `projectWizardMembers.ts` does not exist.

- [x] **Step 3: Implement the frontend helper and use it**

Implement:

```ts
export const userBelongsToOrganization = (user, organization) => {
  const userOrgId = String(user.orgId || '').trim()
  const organizationId = String(organization?.id || '').trim()
  if (userOrgId && organizationId) return userOrgId === organizationId
  return Boolean(organization) && String(user.orgName || '').trim() === String(organization.name || '').trim()
}
```

In `wizardUsersByRole`, resolve the selected organization from enabled role options and filter with this helper. In `handleWizardOrgChange`, clear the selected user only when the helper returns false.

- [x] **Step 4: Run frontend verification**

Run:

```bash
node --experimental-strip-types --test tests/project-wizard-members.test.mjs
pnpm ts:check
pnpm exec eslint src/views/AICheck/AdminOverview.vue src/views/AICheck/utils/projectWizardMembers.ts
```

Expected: all commands exit 0.

### Task 2: Backend project-create organization validation

**Files:**
- Modify: `backend/apps/api/routes.py:3220-3245,28490-28580`
- Modify: `backend/tests/test_contract.py:9020-9060`

**Interfaces:**
- Produces: `user_belongs_to_org(user: dict[str, Any], org: dict[str, Any] | None, expected_org_name: str) -> bool`
- Consumes: the selected organization resolved by `find_org_unit(org_name=expected_org_name)`

- [x] **Step 1: Write the failing backend route test**

Temporarily set the seeded contractor user's `orgId` to the selected contractor organization's ID and its `orgName` to an old name. Submit a full `admin_project_create_payload` and assert success plus four created members. Restore the original user data in `finally`.

- [x] **Step 2: Run the backend test to verify RED**

Run: `.venv/bin/pytest tests/test_contract.py -k "project_creation_accepts_member_with_matching_org_id" -q`

Expected: FAIL with `VALIDATION_ERROR` and “用户所属组织与项目参建单位不一致”。

- [x] **Step 3: Implement canonical projection and ID-based validation**

Change `admin_user_projection` so a resolved organization supplies the canonical `orgName`. Add `user_belongs_to_org`: compare non-empty IDs when both exist, otherwise compare trimmed names. Resolve `expected_org` in the project-create loop and replace the direct string comparison with the helper.

- [x] **Step 4: Add and run the negative case**

Add a test user whose non-empty `orgId` points to another organization while its `orgName` equals the selected contractor name. Assert project creation returns `VALIDATION_ERROR` and performs no partial project/member writes.

Run: `.venv/bin/pytest tests/test_contract.py -k "project_creation_" -q`

Expected: all selected project-creation tests pass.

### Task 3: Integrated verification

**Files:**
- Modify: `docs/superpowers/plans/2026-08-04-project-wizard-member-org-binding.md`

- [x] **Step 1: Run focused verification**

```bash
cd backend && .venv/bin/pytest tests/test_contract.py -k "project_creation_" -q
cd ../frontend && node --experimental-strip-types --test tests/project-wizard-members.test.mjs
cd ../frontend && pnpm ts:check
```

- [x] **Step 2: Run formatting and patch checks**

```bash
cd frontend && pnpm exec eslint src/views/AICheck/AdminOverview.vue src/views/AICheck/utils/projectWizardMembers.ts
cd .. && git diff --check
```

- [x] **Step 3: Commit implementation**

```bash
git add backend/apps/api/routes.py backend/tests/test_contract.py frontend/src/views/AICheck/AdminOverview.vue frontend/src/views/AICheck/utils/projectWizardMembers.ts frontend/tests/project-wizard-members.test.mjs docs/superpowers/plans/2026-08-04-project-wizard-member-org-binding.md
git commit -m "fix: match project members by organization id"
```
