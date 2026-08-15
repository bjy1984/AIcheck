# AI Review Sidebars Collapse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independent, accessible collapse and expand controls for the standalone AI Review left and right sidebars while leaving embedded mode unchanged.

**Architecture:** Put the four layout-state decisions and accessible labels in a small pure resolver next to the existing workbench-context resolver, then consume that resolver from the Vue component. Keep both sidebars mounted and hide only their content so node-tree and form state survive collapse; CSS state classes shrink either side to a 28px control rail.

**Tech Stack:** Vue 3 Composition API, TypeScript 5.7, Element Plus, CSS Grid, Node `assert` unit tests, Vite production build.

## Global Constraints

- The feature applies only to standalone `/ai-review-b`; embedded workbench behavior must not change.
- Both sidebars start expanded and operate independently.
- A collapsed sidebar keeps a 28px control rail and a keyboard-accessible toggle.
- Toggle controls expose `aria-expanded`, `aria-controls`, and action-specific Chinese labels.
- Sidebar content stays mounted while hidden so local UI state is preserved.
- Do not add persistence, dependencies, backend changes, route changes, authentication changes, or database changes.
- Deploy with `bash backend/scripts/deploy_to_server.sh --frontend`; do not replace or restart the API container.

---

### Task 1: Model the four sidebar layout states

**Files:**
- Modify: `frontend/src/views/AIReviewB/embeddedReviewWorkbench.ts`
- Test: `frontend/src/views/AIReviewB/embeddedReviewWorkbench.test.ts`

**Interfaces:**
- Consumes: `embedded: boolean`, `leftCollapsed: boolean`, `rightCollapsed: boolean`.
- Produces: `resolveReviewSidebarLayout(input): ReviewSidebarLayout`, with `layoutClasses`, `leftLabel`, `rightLabel`, `leftExpanded`, and `rightExpanded`.

- [ ] **Step 1: Write the failing behavior tests**

Add table-driven assertions with literal expectations for standalone expanded, left collapsed, right collapsed, both collapsed, and embedded inputs:

```ts
assert.deepEqual(
  resolveReviewSidebarLayout({ embedded: false, leftCollapsed: true, rightCollapsed: false }),
  {
    layoutClasses: ['is-left-collapsed'],
    leftLabel: '展开节点导航',
    rightLabel: '收起上下文',
    leftExpanded: false,
    rightExpanded: true
  }
)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd frontend && pnpm test:unit`

Expected: FAIL because `resolveReviewSidebarLayout` is not exported.

- [ ] **Step 3: Implement the minimal pure resolver**

Add the input/result types and resolver. Embedded mode must return no collapse classes and both regions expanded regardless of input flags; standalone mode returns only the active collapse classes and action labels.

```ts
export const resolveReviewSidebarLayout = (input: ReviewSidebarLayoutInput): ReviewSidebarLayout => {
  const leftCollapsed = !input.embedded && input.leftCollapsed
  const rightCollapsed = !input.embedded && input.rightCollapsed
  return {
    layoutClasses: [
      ...(leftCollapsed ? ['is-left-collapsed'] : []),
      ...(rightCollapsed ? ['is-right-collapsed'] : [])
    ],
    leftLabel: leftCollapsed ? '展开节点导航' : '收起节点导航',
    rightLabel: rightCollapsed ? '展开上下文' : '收起上下文',
    leftExpanded: !leftCollapsed,
    rightExpanded: !rightCollapsed
  }
}
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `cd frontend && pnpm test:unit`

Expected: all unit test scripts pass with no warnings.

- [ ] **Step 5: Commit the tested state model**

```bash
git add frontend/src/views/AIReviewB/embeddedReviewWorkbench.ts frontend/src/views/AIReviewB/embeddedReviewWorkbench.test.ts
git commit -m "test: cover AI review sidebar layout states"
```

### Task 2: Render accessible controls and responsive rails

**Files:**
- Modify: `frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue`
- Test: `frontend/src/views/AIReviewB/embeddedReviewWorkbench.test.ts`

**Interfaces:**
- Consumes: `resolveReviewSidebarLayout()` from Task 1.
- Produces: independent `leftSidebarCollapsed` and `rightSidebarCollapsed` refs, computed layout metadata, controls targeting `review-node-sidebar-content` and `review-context-panel-content`, and `is-left-collapsed`/`is-right-collapsed` grid states.

- [ ] **Step 1: Extend the behavior test for toggle transitions**

Add assertions that calling the pure resolver after flipping only one boolean changes only that side's expanded state, label, and layout class; the other side remains expanded.

```ts
const afterRightToggle = resolveReviewSidebarLayout({
  embedded: false,
  leftCollapsed: false,
  rightCollapsed: true
})
assert.equal(afterRightToggle.leftExpanded, true)
assert.equal(afterRightToggle.rightExpanded, false)
assert.equal(afterRightToggle.rightLabel, '展开上下文')
assert.deepEqual(afterRightToggle.layoutClasses, ['is-right-collapsed'])
```

- [ ] **Step 2: Run unit tests and verify the added scenario passes against the state model**

Run: `cd frontend && pnpm test:unit`

Expected: PASS, establishing the component-facing transition contract before template/CSS integration.

- [ ] **Step 3: Wire the component state and controls**

Import `ArrowRight` and `resolveReviewSidebarLayout`; add two default-false refs and a computed `sidebarLayout`. Bind the layout classes to `.review-b-layout`. For standalone mode, render one native `button` at each sidebar edge with `type="button"`, dynamic `aria-label`/`title`, `aria-expanded`, `aria-controls`, and click handlers that flip only the corresponding ref. Wrap each existing sidebar body in an ID-bearing content container controlled with `v-show`; do not render the new controls in embedded mode.

- [ ] **Step 4: Add the four CSS grid states and rail styling**

Add transitions and explicit selectors:

```css
.review-b-layout.is-left-collapsed {
  grid-template-columns: 28px minmax(650px, 1fr) 330px;
}

.review-b-layout.is-right-collapsed {
  grid-template-columns: minmax(300px, 404px) minmax(650px, 1fr) 28px;
}

.review-b-layout.is-left-collapsed.is-right-collapsed {
  grid-template-columns: 28px minmax(650px, 1fr) 28px;
}
```

Position each circular toggle on the rail boundary with a 32px hit target. In the `width <= 1380px` media query, repeat the three state overrides using the narrow expanded widths while preserving 28px collapsed rails. Scope selectors so `.review-b-shell.is-embedded` keeps its existing two-column grid.

- [ ] **Step 5: Run formatting and focused verification**

Run:

```bash
cd frontend
pnpm prettier --write src/views/AIReviewB/ConversationalReviewWorkbenchB.vue src/views/AIReviewB/embeddedReviewWorkbench.ts src/views/AIReviewB/embeddedReviewWorkbench.test.ts
pnpm test:unit
pnpm ts:check
```

Expected: unit tests and TypeScript checks pass without errors.

- [ ] **Step 6: Commit the UI implementation**

```bash
git add frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue frontend/src/views/AIReviewB/embeddedReviewWorkbench.test.ts
git commit -m "feat: add AI review sidebar collapse controls"
```

### Task 3: Verify, publish, and update only the frontend

**Files:**
- Verify: `frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue`
- Verify: `backend/scripts/deploy_to_server.sh`

**Interfaces:**
- Consumes: committed UI changes from Tasks 1 and 2.
- Produces: a passing production build, pushed `main`, updated static frontend assets, and healthy web/API checks.

- [ ] **Step 1: Run the complete frontend quality gate**

Run:

```bash
cd frontend
pnpm test:unit
pnpm ts:check
pnpm lint
pnpm build:pro
```

Expected: all commands exit 0; the production build completes and static operability audit reports no new failures.

- [ ] **Step 2: Confirm the exact Git scope**

Run: `git status --short && git diff --check && git log -4 --oneline`

Expected: no unstaged application changes, no whitespace errors, and only the approved docs/tests/component/helper commits ahead of the previous main tip.

- [ ] **Step 3: Push main**

Run: `git push origin main`

Expected: remote `main` advances to the verified local commit.

- [ ] **Step 4: Deploy static frontend assets only**

Run: `bash backend/scripts/deploy_to_server.sh --frontend`

Expected: frontend build/assets update successfully and the script does not recreate the API service.

- [ ] **Step 5: Verify production health and deployed markers**

Use the server alias and configured deployment URLs from the script to verify the site returns HTTP 200, API `/readyz` returns HTTP 200, the API container restart count has not increased, and the deployed JavaScript contains the Chinese sidebar action labels.

- [ ] **Step 6: Record final repository state**

Run: `git status --short && git rev-parse HEAD && git rev-parse origin/main`

Expected: clean worktree and identical local/remote main SHAs.
