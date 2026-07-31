# MinerU Layout Compatibility and Default Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept both current MinerU VLM `layout.json` results and legacy `*_middle.json` results, while making the unified OCR provider configurable between `local` and `mineru` with MinerU as the deployment default.

**Architecture:** The MinerU normalizer selects one validated page-layout artifact, preferring legacy `*_middle.json` and falling back to a unique basename `layout.json`; the selected artifact keeps an accurate persisted artifact key. Unified document OCR resolves an explicit `ocrOptions.provider` first, then `AICHECK_OCR_DEFAULT_PROVIDER`, and fails closed for values outside `local` and `mineru`. Only the remote OCR worker receives the MinerU API key.

**Tech Stack:** Python 3.12, pytest, FastAPI/Celery worker functions, Docker Compose YAML, existing OCR repository and object-storage contracts.

## Global Constraints

- MinerU model remains fixed at `vlm`.
- Supported providers are exactly `local` and `mineru`.
- `AICHECK_OCR_DEFAULT_PROVIDER` defaults to `mineru` when unset.
- Explicit `ocrOptions.provider` overrides the environment default.
- Invalid explicit or configured provider values fail with `OCR_PROVIDER_UNSUPPORTED`.
- MinerU credentials remain absent from API, local workers, and the offline local OCR service.
- Signed upload URLs and the API key never enter jobs, responses, logs, or artifacts.
- Existing legacy `*_middle.json` results remain compatible.

---

### Task 1: MinerU VLM Layout Artifact Compatibility

**Files:**

- Modify: `backend/tests/test_mineru_ocr.py`
- Modify: `backend/libs/mineru_ocr.py`

**Interfaces:**

- Produces: `page_layout_artifact(members: Mapping[str, bytes]) -> tuple[str, str]` returning `(member_name, artifact_key)`.
- Consumes: the selected JSON object through existing `mineru_pages()`.
- Produces artifact key `middle_json` for `*_middle.json` and `layout_json` for basename `layout.json`.

- [ ] **Step 1: Write the failing current-VLM-layout test**

Add a fixture path that writes `layout.json` instead of `*_middle.json`, matching the live provider shape:

```python
def test_normalizes_current_vlm_layout_json_without_middle_json() -> None:
    bundle = _normalize(
        _zip_bytes(
            include_middle=False,
            extra_members={
                "layout.json": json.dumps(
                    {"pdf_info": [{"page_idx": 0, "page_size": [595, 841]}]}
                ).encode("utf-8")
            },
        )
    )

    assert bundle.result["pages"][0]["width"] == 595.0
    assert "layout_json" in bundle.artifacts
    assert "middle_json" not in bundle.artifacts
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
cd backend
/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q \
  tests/test_mineru_ocr.py::test_normalizes_current_vlm_layout_json_without_middle_json
```

Expected: FAIL with `MINERU_MIDDLE_JSON_MISSING`.

- [ ] **Step 3: Add failure/precedence tests**

Add tests proving:

```python
def test_legacy_middle_json_wins_when_both_layout_formats_exist() -> None: ...
def test_missing_all_page_layout_artifacts_has_stable_error() -> None: ...
def test_multiple_layout_json_members_are_rejected_as_ambiguous() -> None: ...
```

Literal assertions require legacy width to win, missing error code to equal
`MINERU_PAGE_LAYOUT_MISSING`, and ambiguous layouts to equal
`MINERU_ARTIFACT_AMBIGUOUS`.

- [ ] **Step 4: Implement minimal layout selection**

Implement a helper that:

```python
middle = unique_artifact_name(..., required=False, ...)
if middle:
    return middle, "middle_json"
layouts = sorted(
    name for name in members
    if PurePosixPath(name).name.lower() == "layout.json"
)
if len(layouts) > 1:
    raise MinerUNormalizationError("MINERU_ARTIFACT_AMBIGUOUS", ...)
if not layouts:
    raise MinerUNormalizationError("MINERU_PAGE_LAYOUT_MISSING", ...)
return layouts[0], "layout_json"
```

Pass the selected bytes to `mineru_pages()` and serialize them under the selected artifact key without renaming a `layout.json` payload to `middle_json`.

- [ ] **Step 5: Run normalizer tests and verify GREEN**

Run:

```bash
/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q \
  backend/tests/test_mineru_ocr.py
```

Expected: all tests pass.

---

### Task 2: Configurable Unified OCR Provider

**Files:**

- Modify: `backend/tests/test_mineru_worker.py`
- Modify: `backend/apps/worker/tasks.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/.env.example`
- Modify ignored local file: `/Volumes/7up/github/knowledgetools/backend/.env`

**Interfaces:**

- Produces: `default_ocr_provider(env: Mapping[str, str] | None = None) -> str`.
- Produces: `resolve_ocr_provider(options: Mapping[str, Any], env: Mapping[str, str] | None = None) -> str`.
- Consumes: `ocrOptions.provider` and `AICHECK_OCR_DEFAULT_PROVIDER`.

- [ ] **Step 1: Write provider resolution tests**

Add literal behavior tests:

```python
def test_default_ocr_provider_is_mineru_when_unset(monkeypatch): ...
def test_explicit_local_provider_overrides_default_mineru(monkeypatch): ...
def test_configured_local_provider_is_used_when_request_omits_provider(monkeypatch): ...
def test_invalid_configured_provider_fails_closed(monkeypatch): ...
```

The first three assert the selected execution branch through `parse_document`; the invalid case asserts `OCR_PROVIDER_UNSUPPORTED` and no local or remote dispatch.

- [ ] **Step 2: Run provider tests and verify RED**

Run:

```bash
/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q \
  backend/tests/test_mineru_worker.py -k 'provider'
```

Expected: the omitted-provider case selects local instead of MinerU and fails.

- [ ] **Step 3: Implement provider resolution**

Add focused helpers near `parse_document`:

```python
def default_ocr_provider(env=None) -> str:
    source = env if env is not None else os.environ
    return str(source.get("AICHECK_OCR_DEFAULT_PROVIDER") or "mineru").strip().lower()

def resolve_ocr_provider(options, env=None) -> str:
    explicit = str(options.get("provider") or "").strip().lower()
    return explicit or default_ocr_provider(env)
```

Validate the resolved value before creating or dispatching provider-specific work. Preserve the explicit provider in the job options only when MinerU is selected.

- [ ] **Step 4: Isolate existing non-provider tests**

Set this test-only default before application imports in `backend/tests/conftest.py`:

```python
os.environ.setdefault("AICHECK_OCR_DEFAULT_PROVIDER", "local")
```

Tests specifically covering the deployment default must delete or override this variable with `monkeypatch`.

- [ ] **Step 5: Document local and deployment configuration**

Add to `.env.example` and the ignored local `backend/.env`:

```dotenv
AICHECK_OCR_DEFAULT_PROVIDER=mineru
```

Do not expose or duplicate `AICHECK_MINERU_API_KEY`.

- [ ] **Step 6: Run provider and existing OCR worker tests**

Run:

```bash
/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q \
  backend/tests/test_mineru_worker.py backend/tests/test_ocr_job_idempotency.py
```

Expected: all tests pass.

---

### Task 3: Compose Configuration and Live Acceptance

**Files:**

- Modify: `backend/tests/test_mineru_compose.py`
- Modify: `backend/docker-compose.yml`
- Modify: `backend/docker-compose.accuracy-pipeline.yml`
- Modify: `backend/docker-compose.deploy.yml`
- Modify: `backend/README.md`

**Interfaces:**

- Consumes: `${AICHECK_OCR_DEFAULT_PROVIDER:-mineru}` in workers that run `parse_document`.
- Preserves: MinerU key only on `ocr-remote-worker-service`.

- [ ] **Step 1: Write failing Compose behavior tests**

Assert parsed YAML behavior, not source text:

```python
for compose in COMPOSE_FILES:
    services = _compose(compose)["services"]
    assert services["worker-service"]["environment"][
        "AICHECK_OCR_DEFAULT_PROVIDER"
    ].endswith(":-mineru}")
    assert "AICHECK_MINERU_API_KEY" not in services["worker-service"]["environment"]
```

Also assert `.env.example` documents `AICHECK_OCR_DEFAULT_PROVIDER=mineru`.

- [ ] **Step 2: Run Compose tests and verify RED**

Run:

```bash
/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q \
  backend/tests/test_mineru_compose.py
```

Expected: missing `AICHECK_OCR_DEFAULT_PROVIDER` assertions fail.

- [ ] **Step 3: Add Provider selection to worker environments**

Add:

```yaml
AICHECK_OCR_DEFAULT_PROVIDER: ${AICHECK_OCR_DEFAULT_PROVIDER:-mineru}
```

to the base worker environment used by `worker-service`/OCR-dispatch workers. Do not add the MinerU API key outside `ocr-remote-worker-service`.

- [ ] **Step 4: Run static and focused verification**

Run:

```bash
uvx ruff check backend/libs/mineru_ocr.py backend/apps/worker/tasks.py \
  backend/tests/test_mineru_ocr.py backend/tests/test_mineru_worker.py \
  backend/tests/test_mineru_compose.py
git diff --check
/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q \
  backend/tests/test_mineru_client.py backend/tests/test_mineru_ocr.py \
  backend/tests/test_mineru_worker.py backend/tests/test_mineru_api.py \
  backend/tests/test_mineru_compose.py backend/tests/test_ocr_job_idempotency.py \
  backend/tests/test_security_hardening.py
```

Expected: Ruff clean, no whitespace errors, and all selected tests pass.

- [ ] **Step 5: Execute the real upload API**

Start the existing Colima/MinIO stack, run the FastAPI upload route in inline dispatch mode using `Scan/20260623104523.pdf`, then assert and display:

```python
assert response["code"] == 0
assert response["data"]["status"] == "success"
assert response["data"]["resultSummary"]["fragmentCount"] > 0
assert "layout_json" in response["data"]["artifactReferences"]
```

Fetch `normalized_json` from MinIO and assert page size `595 x 841`, MinerU provenance, table output, and seal candidate output. Redact the API key and signed URLs from all displayed evidence.

- [ ] **Step 6: Complete security and completion audit**

Verify the ignored env file contains one non-empty MinerU key and
`AICHECK_OCR_DEFAULT_PROVIDER=mineru`, mode remains `0600`, the file is ignored/untracked, and no tracked diff contains a long `sk-...` pattern. Review every acceptance criterion in the approved spec before committing.

