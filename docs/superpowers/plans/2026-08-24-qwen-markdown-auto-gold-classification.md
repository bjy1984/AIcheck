# Qwen Markdown Auto-Gold Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-call Qwen3.8-Max multi-label classifier that consumes only MinerU Markdown, writes versioned automatic gold labels, reuses the existing admin Prompt template manager, and verifies the contract against all 23 files under `test/`.

**Architecture:** MinerU persists a Markdown snapshot and hash on the OCR job, then dispatches an idempotent `classify_document_auto_gold` Celery task to the existing `llm.remote` queue. A focused classification service resolves the production Prompt template, calls the existing Qwen OpenAI-compatible client with a strict JSON Schema, grounds every `contentEvidence` quote in the Markdown, persists an immutable run and gold-label version, and projects the multi-label result onto the document and project knowledge file.

**Tech Stack:** Python 3.12, FastAPI, Celery/Redis, PostgreSQL JSONB repository, httpx OpenAI-compatible Chat Completions, Vue 3/Element Plus existing admin Prompt UI, pytest, Node frontend contract tests.

**Spec:** `docs/superpowers/specs/2026-08-24-qwen-markdown-auto-gold-classification-design.md`

## Global Constraints

- Model ID is exactly `qwen3.8-max` through the dedicated `documentClassifier` role.
- Qwen receives MinerU Markdown and category definitions only; filenames, directories, extensions, upload metadata, and frontend guesses are forbidden.
- One Qwen call only: no human confirmation, second model call, or model voting.
- Local schema, enum, freshness, and Markdown quote grounding checks are mandatory before auto-gold acceptance.
- The authoritative category enum is the 16 `materialCategory` values in `backend/config/material_review_points.json`.
- All accepted auto-gold records are immutable versions; replacement supersedes rather than deletes old versions.
- Existing admin `/admin/prompt-templates` CRUD/publish flow is reused.
- Existing `materialTypeCode` is not guessed by this category classifier.
- Every production behavior is implemented test-first and each test must be observed failing for the intended reason.

---

## File Structure

### New files

- `backend/libs/document_auto_gold.py`: pure category snapshot, Prompt rendering, Qwen output schema, evidence grounding, and immutable gold-record construction.
- `backend/tests/test_document_auto_gold.py`: pure contract tests for multi-label parsing, evidence grounding, forbidden context, and versioning.
- `backend/tests/test_document_auto_gold_worker.py`: task/service tests for Prompt resolution, one Qwen call, persistence, staleness, retries, and projection.
- `backend/ocr_eval/test_gold_manifest.json`: exact 23-file checksum and expected-category manifest.
- `backend/scripts/test_gold_manifest.py`: deterministic manifest audit and checksum CLI.
- `backend/tests/test_test_gold_manifest.py`: corpus count, checksum, mixed-folder override, and no-path-to-model tests.
- `backend/tests/test_document_classifier_prompt_admin.py`: Prompt seed, CRUD/publish, and classification-template variable restrictions.

### Modified files

- `backend/libs/qwen_runtime.py`: add `documentClassifier` role/environment override.
- `backend/config/qwen_runtime.yaml`: default `documentClassifier: qwen3.8-max`.
- `backend/.env.example`: document classifier model override example.
- `backend/libs/db/repository.py`: register and initialize classification-run and gold-label collections.
- `backend/libs/db/seed.py`: seed the production classifier Prompt template.
- `backend/libs/mineru_ocr.py`: expose the decoded MinerU Markdown snapshot in `MinerUNormalizedBundle` without adding it to normalized OCR JSON.
- `backend/apps/worker/celery_app.py`: route classification task to the existing `llm.remote` queue.
- `backend/libs/integrations/task_dispatcher.py`: deterministic classification dispatch.
- `backend/apps/worker/tasks.py`: create/run/persist classification, hook MinerU completion, and flush new state collections.
- `backend/libs/document_intelligence.py`: stop the legacy filename/OCR classifier on the MinerU auto-gold path and expose projection helpers.
- `backend/apps/api/routes.py`: include classification runs/gold labels in document detail metadata and validate classifier Prompt variables.
- `frontend/src/views/AICheck/AdminOverview.vue`: show a classifier-specific guidance alert and hide irrelevant planner/critic fields for the classifier template while retaining the existing editor.
- `frontend/src/views/AICheck/adminOverviewSections.test.ts`: verify the classifier template remains editable through the existing admin section.

---

### Task 1: Pure multi-label auto-gold contract

**Files:**
- Create: `backend/libs/document_auto_gold.py`
- Create: `backend/tests/test_document_auto_gold.py`
- Read: `backend/config/material_review_points.json`

**Interfaces:**
- Produces: `category_definition_snapshot(path: Path) -> dict[str, Any]`
- Produces: `classification_response_format(categories: list[str]) -> dict[str, Any]`
- Produces: `validate_classification_output(raw: dict[str, Any], markdown: str, categories: list[str]) -> dict[str, Any]`
- Produces: `build_gold_label_record(...) -> dict[str, Any]`

- [ ] **Step 1: Write failing category-snapshot tests**

```python
def test_category_snapshot_contains_exact_16_backend_categories():
    snapshot = category_definition_snapshot(CONFIG)
    assert len(snapshot["categories"]) == 16
    assert snapshot["schemaHash"].startswith("sha256:")
    assert "资质证照" in [item["category"] for item in snapshot["categories"]]

def test_category_snapshot_is_stable_for_same_source():
    assert category_definition_snapshot(CONFIG)["schemaHash"] == category_definition_snapshot(CONFIG)["schemaHash"]
```

- [ ] **Step 2: Run snapshot tests and verify RED**

Run: `/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_document_auto_gold.py -k category_snapshot`

Expected: import failure because `libs.document_auto_gold` does not exist.

- [ ] **Step 3: Implement deterministic category snapshot**

Implement recursive extraction from `material_review_points.json`, grouping `materialTypeCode`, `materialTypeName`, and `evidenceItems` under each category. Serialize with sorted keys and compact separators before SHA-256 hashing.

```python
def category_definition_snapshot(path: Path = MATERIAL_REVIEW_POINTS) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    # group enabled items by materialCategory and return sorted categories
```

- [ ] **Step 4: Run snapshot tests and verify GREEN**

Run: `/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_document_auto_gold.py -k category_snapshot`

Expected: PASS.

- [ ] **Step 5: Write failing schema and grounding tests**

Cover:

```python
def test_validate_accepts_multiple_grounded_labels(): ...
def test_validate_rejects_unknown_category(): ...
def test_validate_rejects_duplicate_category(): ...
def test_validate_rejects_quote_missing_from_markdown(): ...
def test_validate_matches_quote_after_whitespace_normalization_only(): ...
def test_validate_does_not_accept_semantic_or_punctuation_rewrite_as_quote(): ...
def test_response_format_is_strict_json_schema_and_has_no_filename_fields(): ...
```

- [ ] **Step 6: Run grounding tests and verify RED**

Run: `/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_document_auto_gold.py -k 'validate or response_format'`

Expected: FAIL because validation functions are missing.

- [ ] **Step 7: Implement minimal schema and grounding validation**

Use exact Markdown substring first, then a whitespace-only normalized comparison. Return normalized labels with `category`, bounded float `confidence`, compact `decisionSummary`, and non-empty `contentEvidence`.

- [ ] **Step 8: Add failing immutable gold-record tests**

```python
def test_gold_record_keeps_all_lineage_hashes_and_multi_labels(): ...
def test_next_gold_version_supersedes_previous_without_mutating_it(): ...
```

- [ ] **Step 9: Implement gold-record builders and run full Task 1 tests**

Run: `/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_document_auto_gold.py`

Expected: PASS.

- [ ] **Step 10: Commit Task 1**

```bash
git add backend/libs/document_auto_gold.py backend/tests/test_document_auto_gold.py
git commit -m "feat: add grounded document auto-gold contract"
```

---

### Task 2: Qwen3.8-Max document-classifier role

**Files:**
- Modify: `backend/libs/qwen_runtime.py`
- Modify: `backend/config/qwen_runtime.yaml`
- Modify: `backend/.env.example`
- Modify: `backend/tests/test_qwen_runtime.py`
- Modify: `backend/tests/test_qwen_readiness.py`

**Interfaces:**
- Produces: model role `documentClassifier`
- Produces: env override `AICHECK_LLM_MODEL_DOCUMENT_CLASSIFIER`
- Consumes: existing `QwenRuntimeClient.chat_sync(..., model="document-classifier")`

- [ ] **Step 1: Write failing role-resolution tests**

```python
def test_document_classifier_alias_resolves_to_qwen38_max():
    config = qwen_runtime_config(path=CONFIG, env={"AICHECK_QWEN_CALL_MODE": "official_api", "QWEN_API_KEY": "x"})
    assert config["models"]["documentClassifier"] == "qwen3.8-max"

def test_document_classifier_env_override():
    resolved = model_names_with_env_overrides({}, {"AICHECK_LLM_MODEL_DOCUMENT_CLASSIFIER": "custom-classifier"})
    assert resolved["documentClassifier"] == "custom-classifier"
```

- [ ] **Step 2: Run and verify RED**

Run: `/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_qwen_runtime.py tests/test_qwen_readiness.py -k document_classifier`

Expected: FAIL because the role is missing.

- [ ] **Step 3: Add role, alias, config, and example env**

Add:

```python
MODEL_ROLE_ALIASES["document-classifier"] = "documentClassifier"
MODEL_ROLE_ENV["documentClassifier"] = "AICHECK_LLM_MODEL_DOCUMENT_CLASSIFIER"
```

and YAML `documentClassifier: qwen3.8-max`.

- [ ] **Step 4: Verify focused and existing Qwen tests**

Run: `/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_qwen_runtime.py tests/test_qwen_readiness.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add backend/libs/qwen_runtime.py backend/config/qwen_runtime.yaml backend/.env.example backend/tests/test_qwen_runtime.py backend/tests/test_qwen_readiness.py
git commit -m "feat: configure qwen3.8 max document classifier"
```

---

### Task 3: Persistence collections and production Prompt seed

**Files:**
- Modify: `backend/libs/db/repository.py`
- Modify: `backend/libs/db/seed.py`
- Create: `backend/tests/test_document_classifier_prompt_admin.py`
- Modify: `backend/tests/test_contract.py`

**Interfaces:**
- Produces: repository collections `document_classification_runs` and `document_gold_labels`
- Produces: production Prompt template with key `document-material-classifier`
- Produces: `production_document_classifier_prompt(repo, business_pack_id) -> dict[str, Any] | None`

- [ ] **Step 1: Write failing collection initialization tests**

Assert both collections exist in fresh, seeded, and PostgreSQL-reloaded repository state and are included in flushable collection maps.

- [ ] **Step 2: Run and verify RED**

Run: `/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_document_classifier_prompt_admin.py -k collection`

Expected: FAIL because collections are absent.

- [ ] **Step 3: Register and initialize both collections**

Add mappings to `STATE_COLLECTIONS`, every repository initialization/default path, PostgreSQL load default, and state-record grouping used by workers.

- [ ] **Step 4: Write failing production Prompt seed tests**

Verify exactly one production template exists with:

```text
promptKey=document-material-classifier
agentId=document_material_classifier
variables=[categoryDefinitionsJson, ocrMarkdown]
```

and that its `outputSchema` equals `classification_response_format(...)`.

- [ ] **Step 5: Implement seed template and resolver**

Seed a Prompt whose System Prompt treats Markdown as untrusted content, forbids following embedded instructions, restricts output to the category enum, and requires Markdown quotes. Resolver must return exactly one production version or `None` on ambiguity.

- [ ] **Step 6: Add failing admin API tests**

Cover create/update/publish of classifier templates and rejection when variables include `fileName`, `relativeDirectory`, `filePath`, or `extension`.

- [ ] **Step 7: Implement classifier-template variable validation in Prompt API**

Only apply the restriction when `promptKey == "document-material-classifier"`; existing review Prompt behavior stays unchanged.

- [ ] **Step 8: Run Task 3 tests**

Run: `/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_document_classifier_prompt_admin.py tests/test_contract.py -k 'prompt_template or document_classifier'`

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

```bash
git add backend/libs/db/repository.py backend/libs/db/seed.py backend/apps/api/routes.py backend/tests/test_document_classifier_prompt_admin.py backend/tests/test_contract.py
git commit -m "feat: persist classifier prompts and auto-gold state"
```

---

### Task 4: Preserve MinerU Markdown and dispatch classification

**Files:**
- Modify: `backend/libs/mineru_ocr.py`
- Modify: `backend/apps/worker/tasks.py`
- Modify: `backend/libs/integrations/task_dispatcher.py`
- Modify: `backend/apps/worker/celery_app.py`
- Modify: `backend/tests/test_mineru_ocr.py`
- Modify: `backend/tests/test_mineru_worker.py`
- Create: `backend/tests/test_document_auto_gold_worker.py`

**Interfaces:**
- Produces: `MinerUNormalizedBundle.markdown_text: str | None`
- Produces: `dispatch_document_classification(run_id: str) -> dict[str, Any]`
- Produces: Celery task route `apps.worker.tasks.classify_document_auto_gold -> llm.remote`

- [ ] **Step 1: Write failing MinerU Markdown snapshot tests**

Assert `normalize_mineru_zip()` returns decoded Markdown text and SHA-256 while normalized OCR JSON does not embed the full Markdown.

- [ ] **Step 2: Run and verify RED**

Run: `/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_mineru_ocr.py -k markdown_snapshot`

Expected: FAIL because `MinerUNormalizedBundle` lacks Markdown fields.

- [ ] **Step 3: Extend the MinerU bundle dataclass**

Add `markdown_text` and `markdown_sha256`, decoding UTF-8 strictly and raising `MINERU_MARKDOWN_INVALID` for invalid bytes. Keep the existing Markdown artifact unchanged.

- [ ] **Step 4: Write failing deterministic dispatch tests**

Verify Celery mode routes one deterministic task to `llm.remote`; inline and disabled modes preserve existing dispatcher semantics.

- [ ] **Step 5: Implement route and dispatcher**

Use task ID hash scope `document-auto-gold` with the classification run ID. Route to the already deployed `llm.remote` workers so no new worker topology is required.

- [ ] **Step 6: Write failing MinerU completion hook test**

After successful MinerU apply, assert one queued classification run contains only the Markdown snapshot/hash and lineage IDs; assert serialized Qwen input context has no filename/path keys.

- [ ] **Step 7: Implement classification-run preparation after MinerU success**

Create or reuse a run keyed by:

```text
documentVersionId + parseResultId + markdownSha256 + promptHash + categorySchemaHash + model
```

Persist it before dispatch. Missing Markdown records `mineru_markdown_missing` and does not dispatch.

- [ ] **Step 8: Run MinerU and dispatch tests**

Run: `/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_mineru_ocr.py tests/test_mineru_worker.py tests/test_document_auto_gold_worker.py -k 'markdown or dispatch or prepare'`

Expected: PASS.

- [ ] **Step 9: Commit Task 4**

```bash
git add backend/libs/mineru_ocr.py backend/apps/worker/tasks.py backend/libs/integrations/task_dispatcher.py backend/apps/worker/celery_app.py backend/tests/test_mineru_ocr.py backend/tests/test_mineru_worker.py backend/tests/test_document_auto_gold_worker.py
git commit -m "feat: dispatch auto-gold classification from mineru markdown"
```

---

### Task 5: Single-call Qwen classification worker and auto-gold persistence

**Files:**
- Modify: `backend/apps/worker/tasks.py`
- Modify: `backend/libs/document_auto_gold.py`
- Modify: `backend/libs/document_intelligence.py`
- Modify: `backend/tests/test_document_auto_gold_worker.py`
- Modify: `backend/tests/test_document_intelligence.py`

**Interfaces:**
- Produces: `classify_document_auto_gold(self, run_id: str) -> dict[str, Any]`
- Produces: `apply_auto_gold_projection(repo, gold: dict[str, Any]) -> dict[str, Any]`
- Consumes: `QwenRuntimeClient.chat_sync(..., model="document-classifier", response_format=strict_schema)`

- [ ] **Step 1: Write failing one-call success test**

Use a transport-backed Qwen client response and assert:

- exactly one HTTP request;
- request model is `qwen3.8-max`;
- rendered messages contain Markdown and category definitions;
- rendered messages do not contain source filename or directory;
- accepted run and active gold record are persisted;
- both category labels are projected to document/knowledge file;
- highest-confidence category becomes legacy `materialCategory`;
- `materialTypeCode` is unchanged.

- [ ] **Step 2: Run and verify RED**

Run: `/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_document_auto_gold_worker.py -k one_call_success`

Expected: FAIL because the task is absent.

- [ ] **Step 3: Implement Prompt rendering and one Qwen call**

Call the existing client with strict JSON Schema, `stream=False`, and no `max_tokens`. Persist a `model_call_attempts` record with `callKind=document_material_classification`, Prompt hashes, usage, elapsed time, provider request ID, and raw response capture reference.

- [ ] **Step 4: Implement local acceptance and immutable gold write**

Validate freshness immediately before the gold transaction. Insert the new gold, supersede old active gold for the same document, mark run accepted, then project labels.

- [ ] **Step 5: Write failing negative-path tests**

Cover:

```text
unknown category -> failed, no gold
ungrounded quote -> failed, no gold
invalid JSON -> retry then failed
stale document version -> stale, no gold
new Prompt version -> new run and new gold version
same idempotency key -> replay without second Qwen call
Qwen 429/5xx -> Celery retry state retained
```

- [ ] **Step 6: Implement minimal negative-path behavior**

Do not fall back to `classify_material()` or any filename rule.

- [ ] **Step 7: Run worker and intelligence tests**

Run: `/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_document_auto_gold_worker.py tests/test_document_intelligence.py`

Expected: PASS.

- [ ] **Step 8: Commit Task 5**

```bash
git add backend/apps/worker/tasks.py backend/libs/document_auto_gold.py backend/libs/document_intelligence.py backend/tests/test_document_auto_gold_worker.py backend/tests/test_document_intelligence.py
git commit -m "feat: generate qwen auto-gold document labels"
```

---

### Task 6: Document detail metadata and admin Prompt guidance

**Files:**
- Modify: `backend/apps/api/routes.py`
- Modify: `backend/tests/test_contract.py`
- Modify: `frontend/src/views/AICheck/AdminOverview.vue`
- Modify: `frontend/src/views/AICheck/adminOverviewSections.test.ts`

**Interfaces:**
- Produces document detail fields: `classificationRuns`, `activeGoldLabel`, `goldLabelHistory`
- Reuses existing Prompt CRUD/publish API without a new route.

- [ ] **Step 1: Write failing document-detail tests**

Assert inspection/admin-visible detail returns classification lineage while unauthorized cross-project actors remain denied by existing `document_read_error`.

- [ ] **Step 2: Implement detail projections and run focused tests**

Run: `/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_contract.py -k 'document_detail and gold_label'`

Expected: PASS after implementation.

- [ ] **Step 3: Write failing frontend Prompt guidance contract**

The static contract must find classifier-specific copy and variable names `categoryDefinitionsJson` and `ocrMarkdown`, and verify planner/critic sections are conditionally hidden for `document-material-classifier`.

- [ ] **Step 4: Implement minimal existing-page guidance**

In the existing drawer, show an alert explaining that only MinerU Markdown is sent. Keep System/User/output schema editors; hide planner/critic fields for this Prompt Key. Do not add a new admin route.

- [ ] **Step 5: Run frontend contracts**

Run: `pnpm node scripts/run-unit-tests.mjs --filter adminOverviewSections`

If the runner does not support `--filter`, run: `pnpm test:unit`.

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

```bash
git add backend/apps/api/routes.py backend/tests/test_contract.py frontend/src/views/AICheck/AdminOverview.vue frontend/src/views/AICheck/adminOverviewSections.test.ts
git commit -m "feat: expose auto-gold lineage and classifier prompt guidance"
```

---

### Task 7: `test/` 23-file gold manifest and audit gate

**Files:**
- Create: `backend/ocr_eval/test_gold_manifest.json`
- Create: `backend/scripts/test_gold_manifest.py`
- Create: `backend/tests/test_test_gold_manifest.py`
- Read: `frontend/e2e/project-registration-upload-review.spec.ts`

**Interfaces:**
- Produces: `audit_test_gold_manifest(repo_root: Path, manifest_path: Path) -> dict[str, Any]`
- Produces CLI exit 0 only for exact 23-file checksum and label coverage.

- [ ] **Step 1: Write failing exact-corpus tests**

Assert:

- exactly 23 non-`.DS_Store` files;
- manifest keys equal repository-relative test paths;
- every entry has SHA-256 and one-or-more expected categories;
- mixed folders 1, 6, 7, 9, and 10 use file-level labels;
- all expected categories belong to the 16-category snapshot;
- copied E2E file list equals the manifest file set.

- [ ] **Step 2: Run and verify RED**

Run: `/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_test_gold_manifest.py`

Expected: FAIL because manifest/auditor are absent.

- [ ] **Step 3: Implement manifest auditor**

The auditor reads paths and hashes only for corpus verification. It must expose a separate `model_input_for_case()` returning only stored MinerU Markdown/category definitions; tests assert no path/name enters that output.

- [ ] **Step 4: Create explicit 23-file manifest**

Use top-folder labels only as human expected outputs. Add file-level overrides for mixed folders. Record unsupported current ontology cases with the closest valid 16-category label, not a new category string.

- [ ] **Step 5: Run corpus tests and audit CLI**

Run:

```bash
/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_test_gold_manifest.py
/Volumes/7up/github/knowledgetools/backend/.venv/bin/python scripts/test_gold_manifest.py --repo-root .. --manifest ocr_eval/test_gold_manifest.json
```

Expected: 23 files, 23 hashes valid, zero unknown categories, exit 0.

- [ ] **Step 6: Commit Task 7**

```bash
git add backend/ocr_eval/test_gold_manifest.json backend/scripts/test_gold_manifest.py backend/tests/test_test_gold_manifest.py
git commit -m "test: add 23-file document classification gold corpus"
```

---

### Task 8: Integration, compatibility, and completion audit

**Files:**
- Modify as failures require, limited to files named in Tasks 1-7.
- Update: `docs/superpowers/plans/2026-08-24-qwen-markdown-auto-gold-classification.md` checkboxes.

**Interfaces:**
- Proves every requirement in the design spec with test or source evidence.

- [ ] **Step 1: Run backend focused suite**

```bash
/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q \
  tests/test_document_auto_gold.py \
  tests/test_document_auto_gold_worker.py \
  tests/test_document_classifier_prompt_admin.py \
  tests/test_test_gold_manifest.py \
  tests/test_qwen_runtime.py \
  tests/test_qwen_readiness.py \
  tests/test_mineru_ocr.py \
  tests/test_mineru_worker.py \
  tests/test_document_intelligence.py \
  tests/test_document_upload_intelligence_e2e.py \
  tests/test_material_targeting.py
```

Expected: all pass.

- [ ] **Step 2: Run backend regression suite for touched large modules**

```bash
/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q \
  tests/test_contract.py \
  tests/test_multi_file_upload_session.py \
  tests/test_mineru_client.py \
  tests/test_mineru_postgres_worker.py
```

Expected: all pass.

- [ ] **Step 3: Run frontend checks**

```bash
cd frontend
pnpm test:unit
pnpm ts:check
```

Expected: pass with no new errors.

- [ ] **Step 4: Run static filename-leak audit**

Assert Qwen classification message construction contains neither `fileName` nor directory/path fields and that tests rename the same source without changing the request body.

Run: `rg -n "fileName|relativeDirectory|filePath" backend/libs/document_auto_gold.py backend/tests/test_document_auto_gold_worker.py`

Expected: only negative assertions/test fixtures, no production message field.

- [ ] **Step 5: Run worktree integrity checks**

```bash
git diff --check
git status --short
git log --oneline --decorate -10
```

Expected: no whitespace errors; only intentional changes; task commits present.

- [ ] **Step 6: Perform requirement-by-requirement completion audit**

Create a checklist against all 10 acceptance criteria in the spec and record the exact test/source evidence for each. Do not mark the goal complete if the live Qwen model identity, Markdown-only request, Prompt editing, persistence, or 23-file gate lacks evidence.

- [ ] **Step 7: Final commit for integration-only fixes**

```bash
git add -u
git commit -m "test: verify qwen auto-gold classification flow"
```

Before running `git add -u`, inspect `git diff --name-only` and confirm every tracked modification belongs to this feature. Skip this commit when integration required no additional changes.
