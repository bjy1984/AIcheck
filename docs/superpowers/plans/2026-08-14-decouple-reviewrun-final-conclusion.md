# ReviewRun Final Conclusion Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the AI Review B final human conclusion a project-node review opinion that can be submitted independently of every ReviewRun lifecycle state.

**Architecture:** The existing node-level `review-opinions` endpoint remains the only writer for the formal business conclusion. The Review B workspace projection exposes a role-based `canSubmitReviewOpinion` permission and prioritizes the latest node opinion, while the Vue workbench submits `projectId + nodeId` through `saveReviewOpinionApi`; ReviewRun human-decision APIs remain unchanged for AI feedback and FDE audit flows.

**Tech Stack:** Python 3, FastAPI, pytest, Vue 3 Composition API, TypeScript 5.7, Element Plus, Node `assert` source-contract tests, pnpm/Vite, Docker/SSH deployment script.

## Global Constraints

- Final human conclusions belong to `projectId + nodeId`, never `reviewRunId`.
- Allowed conclusions are exactly `满足要求`, `需补正`, `不适用`, and `证据不足`.
- No ReviewRun, or a queued, running, waiting-human-input, failed, cancelled, or completed ReviewRun, must not disable conclusion submission.
- Submitting a node conclusion must not change ReviewRun status, `humanDecision`, orchestration, or AI feedback.
- Existing role, node-scope, evidence selection, and “满足要求” readiness validation remain enforced.
- Keep `/api/review-runs/{reviewRunId}/human-decision` for ReviewRun audit/FDE consumers, but remove it from the Review B formal-conclusion UI path.
- Do not modify unrelated files or the existing untracked `audit-reports/admin-menu-20260814/` directory.

---

### Task 1: Project node conclusion permission and projection

**Files:**
- Modify: `backend/apps/api/routes.py:9860-9930`
- Test: `backend/tests/test_review_b_workspace.py`

**Interfaces:**
- Consumes: `review_opinions` records keyed by `projectId + nodeId`, the existing `can_review` role calculation, and optional ReviewRun state.
- Produces: `permissions.canSubmitReviewOpinion: bool`; `latestHumanDecision` that prefers the newest node review opinion and falls back to ReviewRun human-decision data only for compatibility.

- [ ] **Step 1: Write failing backend projection tests**

Add a parameterized test proving the new permission ignores ReviewRun state, including the no-run case:

```python
@pytest.mark.parametrize(
    "run_status",
    [None, "queued", "running", "waiting_human_input", "waiting_human_review", "failed", "cancelled"],
)
def test_review_b_node_conclusion_permission_is_independent_of_review_run(run_status) -> None:
    if run_status:
        repo.state["review_runs"].insert(
            0,
            {
                "id": f"RRUN-DECOUPLE-{run_status}",
                "reviewRunId": f"RRUN-DECOUPLE-{run_status}",
                "projectId": PROJECT_ID,
                "nodeId": NODE_ID,
                "status": run_status,
                "revision": 1,
            },
        )

    workspace = assert_ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace",
            headers=HEADERS,
        )
    )

    assert workspace["permissions"]["canSubmitReviewOpinion"] is True
```

Add a projection precedence test with a ReviewRun `humanDecision` and a newer node opinion:

```python
def test_review_b_latest_human_decision_prefers_node_review_opinion() -> None:
    repo.state["review_runs"].insert(0, {
        "id": "RRUN-DECOUPLE-PRECEDENCE",
        "reviewRunId": "RRUN-DECOUPLE-PRECEDENCE",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "status": "accepted_by_human",
        "humanDecision": {"decision": "accept", "comment": "AI feedback only"},
        "revision": 1,
    })
    opinion = {
        "id": "OPN-DECOUPLE",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "result": "证据不足",
        "opinion": "节点正式结论",
        "createdAt": "2026-08-14 12:00:00",
    }
    repo.state["review_opinions"].insert(0, opinion)

    workspace = assert_ok(client.get(
        f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace",
        headers=HEADERS,
    ))

    assert workspace["latestHumanDecision"] == opinion
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
cd backend
python -m pytest tests/test_review_b_workspace.py \
  -k "node_conclusion_permission or latest_human_decision_prefers" -q
```

Expected: FAIL because `canSubmitReviewOpinion` is absent and `latestHumanDecision` currently prefers ReviewRun `humanDecision`.

- [ ] **Step 3: Implement the minimal projection change**

In `review_workspace_payload`, add the role-based permission without reading `run_status`, retain `canSubmitHumanDecision` for old clients, and reverse the conclusion precedence:

```python
"permissions": {
    "canStartReview": can_review and bool(available_modes),
    "canSubmitHumanInput": can_review and bool(active_task),
    "canSubmitHumanDecision": can_review and run_status == "waiting_human_review",
    "canSubmitReviewOpinion": can_review,
    "canManageEvidence": can_review,
},
```

```python
"latestHumanDecision": (
    repo.clone(review_opinions[0])
    if review_opinions
    else repo.clone((review_run or {}).get("humanDecision"))
),
```

- [ ] **Step 4: Run focused and neighboring backend tests**

Run:

```bash
cd backend
python -m pytest tests/test_review_b_workspace.py -q
python -m pytest tests/test_backend_audit_remediation.py tests/test_fde_console.py -q
```

Expected: all selected tests pass; ReviewRun human-decision contracts remain green.

- [ ] **Step 5: Commit the backend projection change**

```bash
git add backend/apps/api/routes.py backend/tests/test_review_b_workspace.py
git commit -m "feat: decouple node conclusion permission from ReviewRun"
```

### Task 2: Review B node conclusion submission UI

**Files:**
- Modify: `frontend/src/types/ai-review-b.ts:88-105`
- Modify: `frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue`
- Create: `frontend/src/views/AIReviewB/finalConclusion.ts`
- Create: `frontend/src/views/AIReviewB/finalConclusionDecoupling.test.ts`

**Interfaces:**
- Consumes: `saveReviewOpinionApi(projectId, nodeId, payload, { etag })`, `ReviewOpinion['result']`, `workspace.project.etag`, selected confirmed evidence links, and `permissions.canSubmitReviewOpinion`.
- Produces: `canSubmitFinalConclusion()`, `buildFinalConclusionPayload()`, a four-option node conclusion form, and `handleSaveReviewOpinion()` that does not require, mutate, or submit a ReviewRun.

- [ ] **Step 1: Write a failing frontend behavior test**

Create `finalConclusionDecoupling.test.ts` with table-driven permission assertions and literal payload expectations:

```ts
import assert from 'node:assert/strict'
import {
  buildFinalConclusionPayload,
  canSubmitFinalConclusion
} from './finalConclusion'

for (const runStatus of [undefined, 'queued', 'running', 'waiting_human_input', 'failed']) {
  assert.equal(
    canSubmitFinalConclusion({ canSubmitReviewOpinion: true }, runStatus),
    true
  )
}
assert.equal(canSubmitFinalConclusion({ canSubmitReviewOpinion: false }, 'waiting_human_review'), false)

assert.deepEqual(
  buildFinalConclusionPayload('证据不足', '  证据尚未闭合  ', [
    { id: 'EV-CONFIRMED', manualStatus: 'confirmed' },
    { id: 'EV-PENDING', manualStatus: 'pending' }
  ]),
  {
    result: '证据不足',
    opinion: '证据尚未闭合',
    evidenceLinkIds: ['EV-CONFIRMED']
  }
)

console.log('Review B final conclusion decoupling contract passed')
```

- [ ] **Step 2: Run frontend unit tests and verify RED**

Run: `cd frontend && pnpm test:unit`

Expected: the new behavior test fails because `finalConclusion.ts` and its exported functions do not exist.

- [ ] **Step 3: Implement the pure conclusion boundary**

Create `finalConclusion.ts` with a permission resolver that deliberately ignores the optional ReviewRun status and a payload builder that trims the opinion and keeps only confirmed evidence:

```ts
import type { EvidenceLink, ReviewOpinion } from '@/types/aicheck'

export const canSubmitFinalConclusion = (
  permissions: { canSubmitReviewOpinion?: boolean } | undefined,
  _reviewRunStatus?: string
) => permissions?.canSubmitReviewOpinion === true

export const buildFinalConclusionPayload = (
  result: ReviewOpinion['result'],
  opinion: string,
  selectedEvidence: Array<Pick<EvidenceLink, 'id' | 'manualStatus'>>
) => ({
  result,
  opinion: opinion.trim(),
  evidenceLinkIds: selectedEvidence
    .filter((item) => item.manualStatus === 'confirmed')
    .map((item) => item.id)
})
```

Run: `cd frontend && pnpm test:unit`

Expected: all behavior tests pass, proving run status cannot affect permission and pending evidence cannot enter the formal payload.

- [ ] **Step 4: Update the workspace type and component state**

Add `canSubmitReviewOpinion: boolean` to `ReviewBWorkspace.permissions`. Import `saveReviewOpinionApi`, `ReviewOpinion`, `buildFinalConclusionPayload`, and `canSubmitFinalConclusion`; remove `submitReviewBHumanDecisionApi`. Replace the ReviewRun decision state with:

```ts
const reviewResult = ref<ReviewOpinion['result']>('证据不足')
const reviewOpinion = ref('')
const canSubmitReviewOpinion = computed(
  () => canSubmitFinalConclusion(workspace.value?.permissions, runStatus.value)
)
```

- [ ] **Step 5: Replace the submit handler**

Implement a node-scoped handler that validates the opinion, passes only confirmed selected evidence, uses the project etag, and refreshes the workspace:

```ts
const handleSaveReviewOpinion = async () => {
  if (!canSubmitReviewOpinion.value) return
  if (!reviewOpinion.value.trim()) {
    ElMessage.warning('请填写人工复核意见')
    return
  }
  await ElMessageBox.confirm('是否保存当前节点的人工复核结论？', '保存人工复核结论', {
    type: 'warning',
    confirmButtonText: '确认保存',
    cancelButtonText: '取消'
  })
  actionLoading.value = true
  try {
    await saveReviewOpinionApi(
      activeProjectId.value,
      activeNodeId.value,
      buildFinalConclusionPayload(reviewResult.value, reviewOpinion.value, selectedEvidence.value),
      {
        etag: workspace.value?.project.etag
      }
    )
    ElMessage.success('人工复核结论已保存')
    await refreshLiveState()
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '人工复核结论保存失败。'))
  } finally {
    actionLoading.value = false
  }
}
```

- [ ] **Step 6: Replace the template controls and copy**

Remove the ReviewRun prerequisite alert. Bind the radio group and button to `canSubmitReviewOpinion`, and render exactly:

```vue
<ElRadioGroup v-model="reviewResult" :disabled="!canSubmitReviewOpinion">
  <ElRadioButton value="满足要求">满足要求</ElRadioButton>
  <ElRadioButton value="需补正">需补正</ElRadioButton>
  <ElRadioButton value="不适用">不适用</ElRadioButton>
  <ElRadioButton value="证据不足">证据不足</ElRadioButton>
</ElRadioGroup>
```

Keep the opinion textarea enabled for users with submission permission and change the button click to `handleSaveReviewOpinion`.

- [ ] **Step 7: Format and run focused frontend checks**

Run:

```bash
cd frontend
pnpm prettier --write src/types/ai-review-b.ts \
  src/views/AIReviewB/ConversationalReviewWorkbenchB.vue \
  src/views/AIReviewB/finalConclusion.ts \
  src/views/AIReviewB/finalConclusionDecoupling.test.ts
pnpm test:unit
pnpm ts:check
```

Expected: all unit scripts and TypeScript checks pass.

- [ ] **Step 8: Commit the frontend workflow change**

```bash
git add frontend/src/types/ai-review-b.ts \
  frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue \
  frontend/src/views/AIReviewB/finalConclusion.ts \
  frontend/src/views/AIReviewB/finalConclusionDecoupling.test.ts
git commit -m "feat: submit Review B conclusions by project node"
```

### Task 3: Cross-layer regression, publish, and server update

**Files:**
- Verify: `backend/apps/api/routes.py`
- Verify: `frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue`
- Use: `backend/scripts/deploy_to_server.sh`

**Interfaces:**
- Consumes: the committed backend projection and frontend node submission flow.
- Produces: verified commits on `origin/main`, rebuilt backend and frontend on `dev-bjy`, and passing production health/behavior checks.

- [ ] **Step 1: Add and run the backend mutation invariant test**

Extend `backend/tests/test_review_b_workspace.py` with a test that creates a running ReviewRun, submits a non-passing node opinion, and verifies the ReviewRun is untouched:

```python
def test_node_review_opinion_does_not_mutate_running_review_run() -> None:
    run = {
        "id": "RRUN-DECOUPLE-INVARIANT",
        "reviewRunId": "RRUN-DECOUPLE-INVARIANT",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "status": "running",
        "revision": 1,
    }
    repo.state["review_runs"].insert(0, run)
    workspace = assert_ok(client.get(
        f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-workspace",
        headers=HEADERS,
    ))

    response = assert_ok(client.post(
        f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-opinions",
        headers={
            **HEADERS,
            "Idempotency-Key": "review-b-node-opinion-independent",
            "If-Match": workspace["project"]["etag"],
        },
        json={"result": "证据不足", "opinion": "先形成节点人工结论", "evidenceLinkIds": []},
    ))

    assert response["opinion"]["result"] == "证据不足"
    assert run["status"] == "running"
    assert "humanDecision" not in run
```

Run:

```bash
cd backend
python -m pytest tests/test_review_b_workspace.py \
  -k "node_review_opinion_does_not_mutate" -q
```

Expected: PASS against the existing node opinion writer; the test permanently guards the cross-layer invariant.

- [ ] **Step 2: Run complete relevant quality gates**

Run:

```bash
cd backend
python -m pytest tests/test_review_b_workspace.py tests/test_backend_audit_remediation.py tests/test_fde_console.py -q

cd ../frontend
pnpm test:unit
pnpm ts:check
pnpm lint
pnpm build:pro
```

Expected: all commands exit 0; the production bundle builds successfully.

- [ ] **Step 3: Commit the invariant test and confirm exact scope**

```bash
git add backend/tests/test_review_b_workspace.py
git commit -m "test: guard ReviewRun-independent node conclusions"
git status --short
git diff --check HEAD~4..HEAD
git log -5 --oneline
```

Expected: only the pre-existing untracked `audit-reports/admin-menu-20260814/` remains; no approved code or docs are unstaged.

- [ ] **Step 4: Push verified commits**

Run: `git push origin main`

Expected: `origin/main` advances to the verified local HEAD.

- [ ] **Step 5: Deploy the committed backend and frontend**

Run: `bash backend/scripts/deploy_to_server.sh`

Expected: the script archives current HEAD, rebuilds/recreates `aicheck-api`, rebuilds and reloads frontend assets, then passes readyz, login, authorization, and business-chain probes.

- [ ] **Step 6: Verify the deployed decoupling markers**

Run read-only checks through the configured `dev-bjy` alias:

```bash
ssh dev-bjy 'curl -fsS http://127.0.0.1:8081/api/readyz'
ssh dev-bjy 'docker exec aicheck-api python -c "from pathlib import Path; s=Path(\"/app/apps/api/routes.py\").read_text(); assert \"canSubmitReviewOpinion\" in s; print(\"backend marker: ok\")"'
ssh dev-bjy 'grep -R -q "满足要求" /home/dev-bjy/aicheck-web/dist/assets && echo "frontend marker: ok"'
```

Expected: readyz reports `"ready":true`, and both deployed markers print `ok`.

- [ ] **Step 7: Confirm local and remote repository state**

Run:

```bash
git status --short
git rev-parse HEAD
git rev-parse origin/main
ssh dev-bjy 'cd /home/dev-bjy/AIcheck && docker run --rm --entrypoint sh -v /home/dev-bjy:/w -w /w/AIcheck docker.m.daocloud.io/alpine/git:latest -c "git log --oneline -1"'
```

Expected: local HEAD equals `origin/main`, and the server deployment commit message contains the deployed short SHA.
