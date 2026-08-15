# Review Workbench Title and Dialog Position Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the standalone review workbench and move the shared evidence locator dialog to 32px below the viewport top.

**Architecture:** Keep the change at the two existing presentation boundaries: the standalone workbench header owns the brand title, and `EvidenceLocatorDialog` owns its Element Plus dialog position. Add a focused source-contract test so future template edits cannot silently restore the old title or the default `15vh` dialog position.

**Tech Stack:** Vue 3, TypeScript 5.7, Element Plus 2.11, Node `assert`, Vite 6, pnpm.

## Global Constraints

- The visible title must be exactly “压力管道监检工作台”.
- The old visible title “AI 工程监检复核工作台” must not remain in the workbench component.
- The evidence locator dialog must use `top="32px"`.
- Do not change global dialog styles or other dialogs.
- Do not change backend behavior, routes, APIs, authentication, or database state.
- Publish only the frontend after pushing the verified commits to `origin/main`.

---

### Task 1: Lock the presentation contract with a failing test

**Files:**
- Create: `frontend/src/views/AIReviewB/reviewWorkbenchPresentation.test.ts`
- Read: `frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue`
- Read: `frontend/src/views/AICheck/components/EvidenceLocatorDialog.vue`

**Interfaces:**
- Consumes: the two Vue single-file components as UTF-8 source text.
- Produces: a regression contract for the exact title and `ElDialog` top attribute.

- [ ] **Step 1: Write the failing source-contract test**

```ts
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const workbenchSource = readFileSync(
  resolve(currentDir, 'ConversationalReviewWorkbenchB.vue'),
  'utf8'
)
const locatorDialogSource = readFileSync(
  resolve(currentDir, '../AICheck/components/EvidenceLocatorDialog.vue'),
  'utf8'
)

assert.match(workbenchSource, /<strong>压力管道监检工作台<\/strong>/)
assert.doesNotMatch(workbenchSource, /AI 工程监检复核工作台/)
assert.match(
  locatorDialogSource,
  /<ElDialog\s+v-model="visible"\s+:title="locationTitle"\s+width="1040px"\s+top="32px"\s+append-to-body\s*>/
)
```

- [ ] **Step 2: Run the unit suite and verify RED**

Run: `cd frontend && pnpm test:unit`

Expected: the new test fails because the old title is still present and `EvidenceLocatorDialog` has no `top="32px"` attribute.

### Task 2: Apply the minimal template changes

**Files:**
- Modify: `frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue:1157`
- Modify: `frontend/src/views/AICheck/components/EvidenceLocatorDialog.vue:184`
- Test: `frontend/src/views/AIReviewB/reviewWorkbenchPresentation.test.ts`

**Interfaces:**
- Consumes: the exact source contract from Task 1.
- Produces: the approved visible title and dialog offset without global CSS changes.

- [ ] **Step 1: Replace the standalone title**

Change the header markup to:

```vue
<strong>压力管道监检工作台</strong>
```

- [ ] **Step 2: Set the dialog top offset**

Change the dialog opening tag to:

```vue
<ElDialog
  v-model="visible"
  :title="locationTitle"
  width="1040px"
  top="32px"
  append-to-body
>
```

- [ ] **Step 3: Run the unit suite and verify GREEN**

Run: `cd frontend && pnpm test:unit`

Expected: all unit scripts pass, including `reviewWorkbenchPresentation.test.ts`.

- [ ] **Step 4: Run focused formatting and static checks**

Run:

```bash
cd frontend
pnpm prettier --write src/views/AIReviewB/reviewWorkbenchPresentation.test.ts src/views/AIReviewB/ConversationalReviewWorkbenchB.vue src/views/AICheck/components/EvidenceLocatorDialog.vue
pnpm ts:check
pnpm lint:eslint:check
pnpm lint:style:check
```

Expected: every command exits 0 without errors.

- [ ] **Step 5: Commit the tested UI change**

```bash
git add frontend/src/views/AIReviewB/reviewWorkbenchPresentation.test.ts frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue frontend/src/views/AICheck/components/EvidenceLocatorDialog.vue
git commit -m "fix: rename review workbench and raise locator dialog"
```

### Task 3: Build, publish, and verify production

**Files:**
- Verify: `frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue`
- Verify: `frontend/src/views/AICheck/components/EvidenceLocatorDialog.vue`
- Use: `backend/scripts/deploy_to_server.sh`

**Interfaces:**
- Consumes: the committed and tested frontend change from Task 2.
- Produces: matching local/remote Git revisions and updated static assets on the production server.

- [ ] **Step 1: Run the production build**

Run: `cd frontend && pnpm build:pro`

Expected: the operability audit and Vite production build both exit 0.

- [ ] **Step 2: Verify Git scope and push main**

Run:

```bash
git diff --check
git status --short --branch
git push origin main
```

Expected: no whitespace errors; only approved commits are ahead before push; `origin/main` advances successfully.

- [ ] **Step 3: Deploy frontend assets only**

Run: `bash backend/scripts/deploy_to_server.sh --frontend`

Expected: the static bundle is rebuilt, uploaded, extracted, and Nginx reloads; built-in health, authentication, permission, business-chain, and topology probes pass.

- [ ] **Step 4: Verify deployed markers and health independently**

Run:

```bash
ssh dev-bjy 'grep -Rao "压力管道监检工作台" /home/dev-bjy/aicheck-web/dist/assets | head -1; grep -Rao "top:\"32px\"" /home/dev-bjy/aicheck-web/dist/assets | head -1; curl -fsS http://127.0.0.1:8081/api/readyz'
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

Expected: both deployed markers are found, readiness reports `"ready":true`, the worktree is clean, and local/remote SHAs match.
