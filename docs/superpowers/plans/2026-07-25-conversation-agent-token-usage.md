# Conversation Agent Token Usage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and display provider-reported input, output, and total Token consumption for each complete conversational Agent exchange.

**Architecture:** Normalize provider usage after every internal model call and accumulate only canonical counters on the assistant message. Keep raw per-turn usage in session events, then render the persisted exchange aggregate beneath the assistant response with a small frontend compatibility reader for historical snake_case messages.

**Tech Stack:** FastAPI/Python, pytest, Vue 3/TypeScript, vue-tsc, ESLint.

## Global Constraints

- Count every internal model turn belonging to one user request.
- Display only input, output, and total Token counts.
- Use provider-reported usage only; do not display estimates as measured usage.
- Preserve partial usage when a later Agent turn fails.
- Do not add a new statistics endpoint or persistence collection.
- Keep raw per-turn provider usage unchanged in audit events.

---

### Task 1: Canonical exchange-level usage

**Files:**
- Modify: `backend/tests/test_review_b_workspace.py`
- Modify: `backend/apps/api/routes.py:9060-9360`

**Interfaces:**
- Consumes: `normalize_model_usage(raw: dict[str, Any] | None) -> dict[str, int | str]`
- Produces: `assistantMessage.execution.usage = {"inputTokens": int, "outputTokens": int, "totalTokens": int}` when measurable usage exists

- [ ] **Step 1: Change the single-turn route test to require canonical usage**

In `test_review_b_free_form_message_uses_qwen_runtime_when_enabled`, replace the raw usage expectation with:

```python
"usage": {
    "inputTokens": 120,
    "outputTokens": 28,
    "totalTokens": 148,
},
```

- [ ] **Step 2: Change the multi-turn test to require one exchange aggregate**

In `test_review_b_agent_runs_bounded_read_only_tool_loop`, assert:

```python
assert execution["usage"] == {
    "inputTokens": 190,
    "outputTokens": 34,
    "totalTokens": 224,
}
```

- [ ] **Step 3: Require partial usage on fallback**

In `test_review_b_agent_fallback_keeps_tool_results`, assert:

```python
assert execution["usage"] == {
    "inputTokens": 50,
    "outputTokens": 8,
    "totalTokens": 58,
}
```

- [ ] **Step 4: Run the focused tests and verify RED**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_review_b_workspace.py \
  -k 'free_form_message_uses_qwen_runtime_when_enabled or runs_bounded_read_only_tool_loop or fallback_keeps_tool_results' -q
```

Expected: the canonical usage assertions fail because the route still returns raw provider keys and omits usage on fallback.

- [ ] **Step 5: Normalize and aggregate each model call**

Import `normalize_model_usage` in `backend/apps/api/routes.py`. Replace raw-key accumulation with canonical accumulation:

```python
normalized_usage = normalize_model_usage(usage)
for key in ("inputTokens", "outputTokens", "totalTokens"):
    total_usage[key] += int(normalized_usage.get(key) or 0)
usage_available = usage_available or any(
    int(normalized_usage.get(key) or 0) > 0
    for key in ("inputTokens", "outputTokens", "totalTokens")
)
```

Initialize the aggregate with the three canonical counters and track whether measurable provider usage has been seen.

- [ ] **Step 6: Attach usage only when available**

Build the successful and fallback execution dictionaries so they include:

```python
**({"usage": repo.clone(total_usage)} if usage_available else {}),
```

Keep `agent.model_call.completed.payload.usage` as the original raw provider object.

- [ ] **Step 7: Run the focused tests and verify GREEN**

Run the command from Step 4.

Expected: all three selected tests pass.

- [ ] **Step 8: Run the full backend conversation-workspace test file**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_review_b_workspace.py -q
```

Expected: all tests pass.

### Task 2: Assistant-message Token display

**Files:**
- Modify: `frontend/src/types/ai-review-b.ts:142-165`
- Modify: `frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue:350-375`
- Modify: `frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue:1230-1250`
- Modify: `frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue:1769-1805`

**Interfaces:**
- Consumes: `ReviewBMessage.execution.usage`
- Produces: `messageTokenUsageLabel(message: ReviewBMessage) -> string`

- [ ] **Step 1: Tighten the frontend usage contract**

Add:

```ts
export type ReviewBTokenUsage = {
  inputTokens?: number
  outputTokens?: number
  totalTokens?: number
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
}
```

Change `ReviewBMessage.execution.usage` from `Record<string, number>` to `ReviewBTokenUsage`.

- [ ] **Step 2: Add a compatibility formatter**

In `ConversationalReviewWorkbenchB.vue`, add a function which:

- returns an empty string for non-assistant messages or absent/all-zero usage;
- reads camelCase first and legacy snake_case second;
- derives total as input plus output only when a reported total is absent;
- clamps invalid values to zero;
- formats integers with `Intl.NumberFormat('zh-CN')`;
- returns `输入 N · 输出 N · 总计 N Token`.

- [ ] **Step 3: Render the label beneath execution metadata**

Add:

```vue
<p v-if="messageTokenUsageLabel(message)" class="message-token-usage">
  {{ messageTokenUsageLabel(message) }}
</p>
```

after the existing execution metadata paragraph.

- [ ] **Step 4: Add subdued presentation styles**

Add a small muted metadata style without a status dot:

```css
.message-token-usage {
  margin: 3px 0 0 12px;
  font-size: 11px;
  line-height: 1.4;
  color: #98a2b3;
}
```

- [ ] **Step 5: Run frontend static verification**

Run:

```bash
cd frontend
pnpm ts:check
pnpm exec eslint src/types/ai-review-b.ts src/views/AIReviewB/ConversationalReviewWorkbenchB.vue
```

Expected: both commands exit successfully.

### Task 3: Integrated verification

**Files:**
- Verify only

**Interfaces:**
- Consumes: backend assistant-message contract and frontend renderer
- Produces: verified feature

- [ ] **Step 1: Re-run backend regression tests**

```bash
cd backend
.venv/bin/pytest tests/test_review_b_workspace.py tests/test_model_usage_accounting.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Re-run frontend checks**

```bash
cd frontend
pnpm ts:check
pnpm exec eslint src/types/ai-review-b.ts src/views/AIReviewB/ConversationalReviewWorkbenchB.vue
```

Expected: both commands exit successfully.

- [ ] **Step 3: Inspect the final diff**

```bash
git diff --check
git diff --stat
git status --short
```

Expected: no whitespace errors and only the planned backend, frontend, test, spec, and plan changes are present.

- [ ] **Step 4: Commit the implementation**

```bash
git add \
  backend/apps/api/routes.py \
  backend/tests/test_review_b_workspace.py \
  frontend/src/types/ai-review-b.ts \
  frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue \
  docs/superpowers/plans/2026-07-25-conversation-agent-token-usage.md
git commit -m "feat: show conversation agent token usage"
```
