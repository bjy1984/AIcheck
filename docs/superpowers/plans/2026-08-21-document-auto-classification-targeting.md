# Document Auto Classification And Targeting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every successful ordinary project-document OCR result produce a persisted material classification, deterministic automatic node targeting, searchable unclassified fallback data, and an end-to-end verified upload-to-submit lifecycle.

**Architecture:** Add one OCR post-processing service that classifies and persists the document before it runs material targeting. Invoke it from every successful OCR provider path before slice dispatch; classification then becomes metadata for chunks and vectors, while targeting runs independently of slice/vector completion. AI review falls back to current-project unclassified versions only when a node has no targeted input versions.

**Tech Stack:** Python 3.12, FastAPI, Celery, repository state/PostgreSQL persistence, pytest, existing OCR/material-targeting/knowledge-indexing libraries.

**Spec:** `docs/superpowers/specs/2026-08-21-document-auto-classification-targeting-design.md`

## Global Constraints

- “上传成功” remains exactly: file body exists, OCR recognized, slicing completed, vectorization completed.
- Classification and targeting never become additional upload-success blockers.
- Any classification confidence greater than zero selects the highest-ranked type.
- Zero confidence always persists `unclassified_material` / `未分类资料`.
- Automatic classification does not read manual correction state as an input.
- No high/low-confidence manual confirmation workflow is added.
- Automatic bindings are draft bindings, idempotent, multi-node capable, and never delete manual bindings.
- Classification completes before slicing starts; targeting and slicing do not depend on one another after classification.

---

### Task 1: Scored Material Classification Contract

**Files:**
- Modify: `backend/libs/material_auto_classify.py`
- Modify: `backend/tests/test_material_auto_classify.py`

**Interfaces:**
- Produces: `classify_material(file_name: str = "", ocr_text: str = "", profile_id: str = "", document_type: str = "") -> dict[str, Any]`
- Produces: constants `UNCLASSIFIED_MATERIAL_CODE`, `UNCLASSIFIED_MATERIAL_NAME`, `CLASSIFIER_VERSION`
- Classification result fields: `materialCategory`, `materialTypeCode`, `materialTypeName`, `classificationStatus`, `classificationConfidence`, `classificationSource`, `classificationReasons`, `classifierVersion`

- [ ] **Step 1: Write failing classifier behavior tests**

Add literal assertions for:

```python
def test_zero_signal_returns_uniform_unclassified_result():
    result = classify_material(file_name="扫描件001.pdf")
    assert result["materialTypeCode"] == "unclassified_material"
    assert result["materialTypeName"] == "未分类资料"
    assert result["classificationStatus"] == "unclassified"
    assert result["classificationConfidence"] == 0.0


def test_any_positive_signal_selects_a_classification():
    result = classify_material(file_name="scan.pdf", ocr_text="本页为材料复验报告")
    assert result["materialTypeCode"] == "material_retest_report"
    assert result["classificationConfidence"] > 0
    assert result["classificationStatus"] == "classified"


def test_document_type_beats_weaker_text_signal():
    result = classify_material(
        file_name="材料复验报告.pdf",
        ocr_text="材料复验报告",
        document_type="design_license",
    )
    assert result["materialTypeCode"] == "design_license"
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
/Volumes/7up/github/knowledgetools/backend/.venv/bin/pytest -q backend/tests/test_material_auto_classify.py
```

Expected: failures because zero-signal classification returns `None`, confidence fields do not exist, and OCR type hints are not accepted.

- [ ] **Step 3: Implement scored candidates and the uniform zero result**

Implement source weights with deterministic tie-breaking:

```python
SOURCE_CONFIDENCE = {
    "documentType": 1.0,
    "profileId": 0.95,
    "fileName": 0.85,
    "ocrText": 0.6,
}
```

Choose `max(candidates, key=(confidence, source_rank, keyword_length, -config_order))`. Always return a result dict; produce the uniform unclassified record when no candidate exists.

- [ ] **Step 4: Run the classifier tests and verify GREEN**

Run the command from Step 2. Expected: all classifier tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/libs/material_auto_classify.py backend/tests/test_material_auto_classify.py
git commit -m "feat: score uploaded material classifications"
```

---

### Task 2: Persist Classification Before Slice Metadata Is Built

**Files:**
- Create: `backend/libs/document_intelligence.py`
- Create: `backend/tests/test_document_intelligence.py`
- Modify: `backend/libs/db/repository.py`

**Interfaces:**
- Consumes: Task 1 `classify_material(...)`
- Produces: `persist_document_classification(repo, document, knowledge_file, classification) -> dict[str, Any]`
- Produces: `process_document_classification_and_targeting(repo, project_id, document_id, document_version_id, *, triggered_by) -> dict[str, Any]`

- [ ] **Step 1: Write failing persistence tests**

Test a real `InMemoryRepository` document and OCR parse record:

```python
def test_post_ocr_classification_updates_document_and_knowledge_file():
    result = process_document_classification_and_targeting(
        repository,
        PROJECT_ID,
        document["id"],
        version["id"],
        triggered_by="test",
    )
    knowledge_file = repository.knowledge_file_for_version(version["id"])
    assert result["classification"]["materialTypeCode"] == "design_license"
    assert document["materialTypeCode"] == "design_license"
    assert knowledge_file["materialTypeCode"] == "design_license"
    assert document["classificationStatus"] == "classified"
```

Also test zero-signal persistence and a forced classifier exception that persists `classificationError` while returning `status=completed`.

- [ ] **Step 2: Run the tests and verify RED**

```bash
/Volumes/7up/github/knowledgetools/backend/.venv/bin/pytest -q backend/tests/test_document_intelligence.py
```

Expected: import failure because `libs.document_intelligence` does not exist.

- [ ] **Step 3: Implement the post-OCR service**

Flatten only the current parse result’s fragments, fields, tables, and seals. Persist classification fields on both records before calling targeting. For `unclassified_material`, return:

```python
{
    "status": "completed",
    "classification": classification,
    "targeting": {
        "status": "skipped_unclassified",
        "createdBindingCount": 0,
        "createdLinkCount": 0,
    },
}
```

Catch classification exceptions, construct the uniform unclassified result with `classificationError=exc.__class__.__name__`, persist it, and continue.

- [ ] **Step 4: Run tests and verify GREEN**

Run the command from Step 2. Expected: all document-intelligence tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/libs/document_intelligence.py backend/libs/db/repository.py backend/tests/test_document_intelligence.py
git commit -m "feat: persist post-ocr document intelligence"
```

---

### Task 3: Deterministic Targeting Without Confidence Confirmation

**Files:**
- Modify: `backend/libs/material_targeting.py`
- Modify: `backend/tests/test_material_targeting.py`
- Modify: `backend/tests/test_document_intelligence.py`

**Interfaces:**
- Consumes: persisted classification from Task 2
- Produces: `score_review_point(...)["bindingEligible"]: bool`
- Produces: system-confirmed `NodeEvidenceLink` and idempotent `BIND-AUTO-*` binding for every eligible point

- [ ] **Step 1: Write failing targeting tests**

Add tests proving:

```python
def test_positive_type_and_locatable_fact_auto_bind_without_confidence_gate():
    point["minConfidence"] = 0.99
    run = run_material_targeting(repository, PROJECT_ID, document_id, version_id)
    assert run["createdBindingCount"] == 1
    assert run["createdLinks"][0]["manualStatus"] == "confirmed"


def test_targeting_rerun_does_not_duplicate_auto_binding():
    first = run_material_targeting(repository, PROJECT_ID, document_id, version_id)
    second = run_material_targeting(repository, PROJECT_ID, document_id, version_id)
    assert first["createdBindings"][0]["id"] == second["createdBindings"][0]["id"]
    assert len([b for b in repository.state["bindings"] if b["id"].startswith("BIND-AUTO-")]) == 1
```

Add a multi-node fixture and assert one document creates distinct draft bindings for every deterministically eligible node.

- [ ] **Step 2: Run tests and verify RED**

```bash
/Volumes/7up/github/knowledgetools/backend/.venv/bin/pytest -q backend/tests/test_material_targeting.py backend/tests/test_document_intelligence.py
```

Expected: failures because `minConfidence` filters the candidate and generated evidence is pending manual confirmation.

- [ ] **Step 3: Replace confidence decisions with `bindingEligible`**

Set eligibility from exact/compatible material match plus at least one formal locatable evidence fact and passed source/context gates. Keep numeric score and reasons for diagnostics only. Remove `minConfidence` from candidate acceptance and set automatic evidence links to confirmed system status.

- [ ] **Step 4: Run tests and verify GREEN**

Run the command from Step 2. Expected: all targeting and intelligence tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/libs/material_targeting.py backend/tests/test_material_targeting.py backend/tests/test_document_intelligence.py
git commit -m "feat: deterministically target classified documents"
```

---

### Task 4: Connect Every OCR Provider Before Slice Dispatch

**Files:**
- Modify: `backend/apps/worker/tasks.py`
- Modify: `backend/tests/test_mineru_postgres_worker.py`
- Modify: `backend/tests/test_ocr_accuracy_pipeline.py`
- Create: `backend/tests/test_ocr_postprocessing_order.py`

**Interfaces:**
- Consumes: Task 2 `process_document_classification_and_targeting(...)`
- Produces: every successful OCR task response includes `documentIntelligence`
- Ordering contract: classification persistence completes before `task_dispatcher.dispatch_slice(...)`

- [ ] **Step 1: Write failing provider-order tests**

Use real repository side effects and replace only the external OCR provider. Assert that the slice dispatcher observes the knowledge file’s final type:

```python
def capture_slice(file_id, expect_parse_result_id=None):
    knowledge_file = repo.find_one("knowledge_files", file_id)
    observed.append(knowledge_file["materialTypeCode"])
    return {"mode": "test", "taskId": "slice-test"}

assert observed == ["design_license"]
```

Cover the MinerU success path and the shared `pipeline_apply_result` path.

- [ ] **Step 2: Run tests and verify RED**

```bash
/Volumes/7up/github/knowledgetools/backend/.venv/bin/pytest -q backend/tests/test_ocr_postprocessing_order.py backend/tests/test_mineru_postgres_worker.py backend/tests/test_ocr_accuracy_pipeline.py
```

Expected: MinerU dispatches slice without classification and existing pipeline code invokes targeting directly instead of the unified service.

- [ ] **Step 3: Wire the unified service**

Replace direct `run_material_targeting(...)` calls in `pipeline_apply_result`. In MinerU, invoke the unified service after `repo.apply_ocr_result(...)` and before `dispatch_slice(...)`. Preserve OCR success if targeting throws; return the diagnostic result under `documentIntelligence`.

- [ ] **Step 4: Run tests and verify GREEN**

Run the command from Step 2. Expected: all provider and ordering tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/worker/tasks.py backend/tests/test_mineru_postgres_worker.py backend/tests/test_ocr_accuracy_pipeline.py backend/tests/test_ocr_postprocessing_order.py
git commit -m "feat: run document intelligence before slicing"
```

---

### Task 5: Carry Classification Into Chunks And Add AI Unclassified Fallback

**Files:**
- Modify: `backend/libs/knowledge_indexing.py`
- Modify: `backend/libs/material_targeting.py`
- Modify: `backend/tests/test_knowledge_indexing.py`
- Modify: `backend/tests/test_material_targeting.py`

**Interfaces:**
- Produces chunk fields: `projectId`, `materialTypeCode`, `materialTypeName`, `classificationStatus`, `classificationConfidence`
- Produces: `unclassified_input_versions_for_project(repo, project_id) -> list[str]`
- Changes: `targeting_input_versions_for_node(...)` falls back only when evidence links and bindings both yield no versions

- [ ] **Step 1: Write failing metadata and fallback tests**

```python
def test_chunks_capture_final_classification_metadata():
    chunks = build_chunks_for_file(
        {"id": "KF-1", "projectId": "P-1", "materialTypeCode": "unclassified_material",
         "materialTypeName": "未分类资料", "classificationStatus": "unclassified",
         "classificationConfidence": 0.0},
        [{"pageNo": 1, "text": "无法分类但可检索的工程事实"}],
    )
    assert chunks[0]["materialTypeCode"] == "unclassified_material"
    assert chunks[0]["projectId"] == "P-1"


def test_node_input_versions_fall_back_to_ready_unclassified_documents():
    assert targeting_input_versions_for_node(repository, PROJECT_ID, 1) == [version_id]
```

Include negative fixtures for another project, non-current version, OCR failure, unsliced file, and unvectorized file.

- [ ] **Step 2: Run tests and verify RED**

```bash
/Volumes/7up/github/knowledgetools/backend/.venv/bin/pytest -q backend/tests/test_knowledge_indexing.py backend/tests/test_material_targeting.py
```

Expected: chunk metadata fields are missing and node input versions remain empty.

- [ ] **Step 3: Implement metadata propagation and fallback**

Copy classification metadata in `build_chunks_for_file`; existing `build_vector_rows` will retain it in vector payload. Implement fallback filtering by project, current version, `unclassified_material`, OCR recognized, slice complete, and vector complete. Do not create bindings during fallback.

- [ ] **Step 4: Run tests and verify GREEN**

Run the command from Step 2. Expected: metadata and fallback tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/libs/knowledge_indexing.py backend/libs/material_targeting.py backend/tests/test_knowledge_indexing.py backend/tests/test_material_targeting.py
git commit -m "feat: search ready unclassified project materials"
```

---

### Task 6: Ordinary Upload-To-Submit End-To-End Coverage

**Files:**
- Create: `backend/tests/test_document_upload_intelligence_e2e.py`
- Modify: `backend/tests/test_main_chain_e2e.py`

**Interfaces:**
- Exercises production upload-session routes, worker tasks, repository persistence, targeting, slicing, vectorization, and submission routes

- [ ] **Step 1: Write the failing ordinary-upload E2E test**

The test must use:

```text
POST /api/projects/{project}/documents/upload-session
PUT /api/projects/{project}/documents/upload-session/{session}/files/{version}
POST /api/projects/{project}/documents/upload-session/{session}/complete
```

Then run a controlled OCR result with locatable fields, call real slice and embed tasks using offline hash embeddings, and submit through `POST /api/projects/{project}/submissions`.

Assert literal outcomes for `design_license→R01`, `quality_certificate→R16`, `welder_certificate→R24`, and `ndt_report→R40`. Add a zero-signal case that becomes unclassified, creates no binding, completes slice/vector, and is returned as the node input fallback only when the node has no targeted documents.

- [ ] **Step 2: Run the E2E tests and verify RED**

```bash
AICHECK_TASK_DISPATCH=inline AICHECK_EMBEDDING_FORCE_OFFLINE_HASH=true \
/Volumes/7up/github/knowledgetools/backend/.venv/bin/pytest -q \
  backend/tests/test_document_upload_intelligence_e2e.py \
  backend/tests/test_main_chain_e2e.py
```

Expected: the new test fails at automatic classification/targeting or provider ordering before implementation is complete.

- [ ] **Step 3: Make only integration corrections exposed by the E2E test**

Do not add new features. Correct route/task persistence ordering, fixture evidence, or response propagation required for the already-designed behavior.

- [ ] **Step 4: Run E2E tests and verify GREEN**

Run the command from Step 2. Expected: all selected E2E tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_document_upload_intelligence_e2e.py backend/tests/test_main_chain_e2e.py backend/apps backend/libs
git commit -m "test: cover upload classification targeting lifecycle"
```

---

### Task 7: Full Verification And Requirement Audit

**Files:**
- Modify only if verification exposes a regression in files already listed above.

**Interfaces:**
- Produces fresh verification evidence for the completed branch

- [ ] **Step 1: Run focused backend tests**

```bash
/Volumes/7up/github/knowledgetools/backend/.venv/bin/pytest -q \
  backend/tests/test_material_auto_classify.py \
  backend/tests/test_document_intelligence.py \
  backend/tests/test_material_targeting.py \
  backend/tests/test_knowledge_indexing.py \
  backend/tests/test_ocr_postprocessing_order.py \
  backend/tests/test_document_upload_intelligence_e2e.py \
  backend/tests/test_main_chain_e2e.py
```

- [ ] **Step 2: Run the complete backend test suite**

```bash
/Volumes/7up/github/knowledgetools/backend/.venv/bin/pytest -q backend/tests
```

- [ ] **Step 3: Run static checks**

```bash
/Volumes/7up/github/knowledgetools/backend/.venv/bin/ruff check backend/libs backend/apps/worker backend/tests
python3 -m compileall -q backend/libs backend/apps
git diff --check
```

- [ ] **Step 4: Audit every spec requirement against code and tests**

Confirm all sections in `docs/superpowers/specs/2026-08-21-document-auto-classification-targeting-design.md` map to a passing test. Explicitly verify that no classification/manual-confirmation queue was introduced and `document_upload_pipeline_complete()` retains the four-item definition.

- [ ] **Step 5: Commit any verification-only corrections**

```bash
git add backend docs/superpowers
git commit -m "chore: close document intelligence verification"
```

Skip this commit when verification required no code or document corrections.
