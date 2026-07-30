# MinerU OCR Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit MinerU `vlm` OCR provider, asynchronous URL/storage/upload endpoints, and full MinerU-result adaptation into the existing AIcheck OCR persistence contract without changing default local OCR behavior.

**Architecture:** A synchronous HTTP client encapsulates MinerU's asynchronous upstream protocol, while a separate normalizer converts result Zip artifacts into AIcheck pages, fragments, tables, seals, fields, diagnostics, and rendered-pixel evidence. API routes create authoritative `ocr_jobs`; an `ocr.remote` Celery worker performs the remote work, persists `ocr_parse_results` and `ocr-artifacts`, and applies results only when a real document/version binding exists.

**Tech Stack:** Python 3.12+, FastAPI, Celery, httpx, pytest, existing AIcheck repository/object-storage abstractions.

## Global Constraints

- MinerU uses the precise parsing API at `https://mineru.net/api/v4`.
- Every submission uses `model_version="vlm"`.
- Every submission enables OCR, formula recognition, and table recognition.
- Existing OCR remains local unless an independent MinerU endpoint is used or `options.provider == "mineru"`.
- URL, `storageKey`, and uploaded bytes are mutually exclusive source types.
- MinerU credentials live only in ignored `backend/.env`; committed files contain placeholders only.
- MinerU credentials and signed upload URLs never appear in logs, exceptions, API responses, Jobs, or artifacts.
- MinerU output must be persisted through existing `ocr_jobs`, `ocr_parse_results`, `ocr-artifacts`, and `apply_ocr_result()` contracts.
- MinerU coordinates must satisfy `rendered_pixels_mapped_v2`; unmappable coordinates must be flagged rather than fabricated.
- The local `ocr-service` container remains offline and never receives MinerU environment variables.

---

## File Structure

- Create `backend/libs/integrations/mineru_client.py`: MinerU configuration, protocol client, state polling, bounded downloads, and typed safe errors.
- Create `backend/libs/mineru_ocr.py`: safe Zip extraction, artifact discovery, content normalization, coordinate mapping, table conversion, seal candidates, and artifact serialization.
- Create `backend/apps/api/mineru_ocr_routes.py`: internal URL/storage/upload task creation and status reads.
- Modify `backend/apps/api/main.py`: include the MinerU router and allow the existing OCR metadata header.
- Modify `backend/libs/db/repository.py`: store Provider/source/options/progress metadata and update OCR Jobs without exposing secrets.
- Modify `backend/apps/worker/tasks.py`: execute MinerU Jobs, persist artifacts/results, apply bound results, and route explicit document OCR requests.
- Modify `backend/libs/integrations/task_dispatcher.py`: dispatch MinerU Jobs to `ocr.remote`.
- Modify `backend/apps/worker/celery_app.py`: route the MinerU task to `ocr.remote`.
- Modify `backend/docker-compose.yml`: add an `ocr.remote` worker with MinerU-only environment access.
- Modify `backend/docker-compose.accuracy-pipeline.yml`: pass MinerU configuration only to the existing `ocr-remote-worker-service`.
- Modify `backend/docker-compose.deploy.yml`: add the production `ocr.remote` worker and MinerU configuration.
- Modify `backend/.env.example`: document non-secret MinerU settings and a credential placeholder.
- Modify ignored `backend/.env`: write the user-provided real MinerU key locally.
- Create `backend/tests/test_mineru_client.py`: protocol and secret-safety tests.
- Create `backend/tests/test_mineru_ocr.py`: normalization and Zip-safety tests.
- Create `backend/tests/test_mineru_worker.py`: persistence, artifact, application, and explicit-provider tests.
- Create `backend/tests/test_mineru_api.py`: API source validation, task creation, status, and upload tests.
- Modify `backend/README.md`: document MinerU configuration and explicit usage.

---

### Task 1: MinerU Protocol Client

**Files:**

- Create: `backend/libs/integrations/mineru_client.py`
- Create: `backend/tests/test_mineru_client.py`

**Interfaces:**

- Produces: `MinerUConfig`, `MinerUError`, `MinerUProtocolError`, `MinerUJobFailed`, `load_mineru_config()`, and `MinerUClient`.
- Produces: `MinerUClient.submit_url(url, *, data_id, options) -> dict[str, Any]`.
- Produces: `MinerUClient.submit_file(path, *, data_id, options) -> dict[str, Any]`.
- Produces: `MinerUClient.wait_for_result(submission, *, progress_callback=None) -> dict[str, Any]`.
- Produces: `MinerUClient.download_result(url) -> bytes`.
- Consumes: only environment/config values and a supplied/default `httpx` transport.

- [ ] **Step 1: Read the test-design rules before changing tests**

Run:

```bash
sed -n '1,260p' /Users/hankieyooly/.codex/plugins/cache/openai-curated-remote/superpowers/6.2.0/skills/test-driven-development/writing-good-tests.md
```

Expected: the full test-design reference is reviewed before creating the test file.

- [ ] **Step 2: Write failing protocol tests**

Create `backend/tests/test_mineru_client.py` with tests equivalent to:

```python
from pathlib import Path

import httpx
import pytest

from libs.integrations.mineru_client import (
    MinerUClient,
    MinerUConfig,
    MinerUProtocolError,
)


def config() -> MinerUConfig:
    return MinerUConfig(
        base_url="https://mineru.net",
        api_key="sk-test-secret",
        model_version="vlm",
        request_timeout_seconds=5,
        poll_interval_seconds=0,
        job_timeout_seconds=5,
        max_download_bytes=1024 * 1024,
    )


def test_submit_url_uses_precise_v4_vlm_contract() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200,
            json={"code": 0, "data": {"task_id": "TASK-1"}, "msg": "ok"},
        )

    client = MinerUClient(config(), transport=httpx.MockTransport(handler))
    submission = client.submit_url(
        "https://files.example/document.pdf",
        data_id="OCRJOB-1",
        options={"language": "ch", "pageRanges": "1-3"},
    )

    request = seen["request"]
    assert request.url.path == "/api/v4/extract/task"
    assert request.headers["Authorization"] == "Bearer sk-test-secret"
    body = __import__("json").loads(request.content)
    assert body["model_version"] == "vlm"
    assert body["is_ocr"] is True
    assert body["enable_formula"] is True
    assert body["enable_table"] is True
    assert submission == {"kind": "task", "providerTaskId": "TASK-1"}


def test_submit_file_puts_bytes_without_content_type(tmp_path: Path) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-test")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "batch_id": "BATCH-1",
                        "file_urls": ["https://upload.example/signed-secret"],
                    },
                    "msg": "ok",
                },
            )
        assert request.headers.get("Content-Type") is None
        return httpx.Response(200)

    client = MinerUClient(config(), transport=httpx.MockTransport(handler))
    submission = client.submit_file(source, data_id="OCRJOB-1", options={})

    assert submission == {"kind": "batch", "providerTaskId": "BATCH-1"}
    assert seen[1].content == b"%PDF-test"


def test_nonzero_provider_code_is_safe_and_does_not_leak_secret() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={"code": "A0202", "msg": "Token sk-test-secret invalid"},
        )
    )
    client = MinerUClient(config(), transport=transport)

    with pytest.raises(MinerUProtocolError) as raised:
        client.submit_url("https://files.example/document.pdf", data_id="JOB-1", options={})

    assert "sk-test-secret" not in str(raised.value)
    assert raised.value.code == "A0202"
    assert raised.value.retryable is False
```

Add focused tests for:

- `GET /api/v4/extract/task/{task_id}` and `GET /api/v4/extract-results/batch/{batch_id}`.
- terminal states `done` and `failed`.
- progress callback for `pending`, `running`, and `converting`.
- retryable HTTP 429/5xx and MinerU `-10001`, `-60007`, `-60009`.
- non-retryable authentication/validation/limit codes.
- invalid JSON, missing `task_id`, missing `batch_id`, or missing `full_zip_url`.
- download byte limit and timeout.
- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_mineru_client.py -q
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'libs.integrations.mineru_client'`.

- [ ] **Step 4: Implement the minimal client**

Create `backend/libs/integrations/mineru_client.py` with these public structures:

```python
@dataclass(frozen=True)
class MinerUConfig:
    base_url: str
    api_key: str
    model_version: str
    request_timeout_seconds: float
    poll_interval_seconds: float
    job_timeout_seconds: float
    max_download_bytes: int


def load_mineru_config(
    env: Mapping[str, str] | None = None,
    *,
    validate: bool = True,
) -> MinerUConfig:
    source = env if env is not None else os.environ
    config = MinerUConfig(
        base_url=str(source.get("AICHECK_MINERU_BASE_URL") or "https://mineru.net").rstrip("/"),
        api_key=str(source.get("AICHECK_MINERU_API_KEY") or ""),
        model_version=str(source.get("AICHECK_MINERU_MODEL_VERSION") or "vlm"),
        request_timeout_seconds=float(source.get("AICHECK_MINERU_TIMEOUT_SECONDS") or 60),
        poll_interval_seconds=max(float(source.get("AICHECK_MINERU_POLL_INTERVAL_SECONDS") or 3), 0),
        job_timeout_seconds=float(source.get("AICHECK_MINERU_JOB_TIMEOUT_SECONDS") or 1800),
        max_download_bytes=int(source.get("AICHECK_MINERU_MAX_DOWNLOAD_BYTES") or 536870912),
    )
    if validate and not config.api_key:
        raise MinerUProtocolError("MINERU_NOT_CONFIGURED", "MinerU API key is not configured.")
    if config.model_version != "vlm":
        raise MinerUProtocolError("MINERU_MODEL_INVALID", "MinerU model must be vlm.")
    return config


class MinerUError(RuntimeError):
    def __init__(self, code: str, safe_message: str, *, retryable: bool = False) -> None:
        super().__init__(safe_message)
        self.code = code
        self.retryable = retryable


class MinerUProtocolError(MinerUError):
    pass


class MinerUJobFailed(MinerUError):
    pass


class MinerUClient:
    def __init__(
        self,
        config: MinerUConfig | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config or load_mineru_config()
        kwargs: dict[str, Any] = {"timeout": self.config.request_timeout_seconds}
        if transport is not None:
            kwargs["transport"] = transport
        self.client = httpx.Client(**kwargs)

    def submit_url(self, url: str, *, data_id: str, options: Mapping[str, Any]) -> dict[str, Any]:
        body = mineru_request_options(options)
        body.update({"url": url, "data_id": data_id})
        payload = self._request_json("POST", "/api/v4/extract/task", json=body)
        task_id = str((payload.get("data") or {}).get("task_id") or "")
        if not task_id:
            raise MinerUProtocolError("MINERU_TASK_ID_MISSING", "MinerU response omitted task_id.")
        return {"kind": "task", "providerTaskId": task_id}

    def submit_file(self, path: Path, *, data_id: str, options: Mapping[str, Any]) -> dict[str, Any]:
        body = mineru_request_options(options)
        body["files"] = [{"name": path.name, "data_id": data_id, "is_ocr": True}]
        payload = self._request_json("POST", "/api/v4/file-urls/batch", json=body)
        data = payload.get("data") or {}
        batch_id = str(data.get("batch_id") or "")
        upload_urls = data.get("file_urls") or []
        if not batch_id or len(upload_urls) != 1:
            raise MinerUProtocolError("MINERU_UPLOAD_URL_MISSING", "MinerU response omitted upload data.")
        upload = self.client.put(str(upload_urls[0]), content=path.read_bytes())
        if upload.status_code >= 400:
            raise MinerUProtocolError(
                "MINERU_UPLOAD_FAILED",
                "MinerU file upload failed.",
                retryable=upload.status_code == 429 or upload.status_code >= 500,
            )
        return {"kind": "batch", "providerTaskId": batch_id}

    def wait_for_result(
        self,
        submission: Mapping[str, Any],
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.config.job_timeout_seconds
        while time.monotonic() < deadline:
            status = self._task_status(submission)
            if progress_callback is not None:
                progress_callback(status)
            if status["state"] == "done":
                return status
            if status["state"] == "failed":
                raise MinerUJobFailed("MINERU_JOB_FAILED", "MinerU parsing failed.")
            if self.config.poll_interval_seconds:
                time.sleep(self.config.poll_interval_seconds)
        raise MinerUJobFailed("MINERU_JOB_TIMEOUT", "MinerU parsing timed out.", retryable=True)

    def download_result(self, url: str) -> bytes:
        chunks: list[bytes] = []
        total = 0
        with self.client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise MinerUProtocolError("MINERU_DOWNLOAD_FAILED", "MinerU result download failed.", retryable=True)
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > self.config.max_download_bytes:
                    raise MinerUProtocolError("MINERU_DOWNLOAD_TOO_LARGE", "MinerU result exceeded the download limit.")
                chunks.append(chunk)
        return b"".join(chunks)
```

Implementation requirements:

- Implement `mineru_request_options(options)` to return the fixed `model_version`, OCR, formula, and table flags plus the four allowlisted optional values.
- Implement `_request_json(method, path, json=None)` to attach the Bearer header, validate HTTP/JSON/provider codes, and raise only sanitized errors.
- Implement `_task_status(submission)` to query the correct single/batch endpoint and return a common `{state, full_zip_url, extract_progress}` mapping.
- Construct request bodies from an allowlist: `language`, `pageRanges`, `noCache`, and `cacheTolerance`.
- Translate option names to MinerU's snake_case names.
- Hard-code/validate `model_version == "vlm"`.
- Always set `is_ocr`, `enable_formula`, and `enable_table` to `True`.
- Use a monotonic deadline in `wait_for_result`.
- Never include response messages verbatim when they may echo credentials or signed URLs.
- Use streamed reads and fail before `max_download_bytes`.

- [ ] **Step 5: Run client tests and verify GREEN**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_mineru_client.py -q
```

Expected: PASS with no warnings.

- [ ] **Step 6: Commit the client**

```bash
git add backend/libs/integrations/mineru_client.py backend/tests/test_mineru_client.py
git commit -m "feat: add MinerU precise parsing client"
```

---

### Task 2: MinerU Artifact Normalization

**Files:**

- Create: `backend/libs/mineru_ocr.py`
- Create: `backend/tests/test_mineru_ocr.py`

**Interfaces:**

- Consumes: downloaded MinerU Zip bytes and local OCR identity/profile data.
- Produces: `normalize_mineru_zip(zip_bytes, storage_key, file_name, profile_id, document_type, provider_task_id) -> MinerUNormalizedBundle`.
- Produces: a `result` compatible with `repo.finish_ocr_job_record()`.
- Produces: an artifact map safe for `object_storage.put_bytes()`.

- [ ] **Step 1: Write a failing representative normalization test**

Create `backend/tests/test_mineru_ocr.py` with an in-memory Zip fixture and assertions equivalent to:

```python
import io
import json
import zipfile

from libs.mineru_ocr import normalize_mineru_zip


def mineru_zip() -> bytes:
    content = [
        {
            "type": "text",
            "text": "压力管道安装记录",
            "text_level": 1,
            "bbox": [100, 200, 900, 260],
            "page_idx": 0,
        },
        {
            "type": "table",
            "table_body": "<table><tr><th>管线号</th><th>规格</th></tr><tr><td>PL001</td><td>DN100</td></tr></table>",
            "bbox": [100, 300, 900, 700],
            "page_idx": 0,
        },
        {
            "type": "image",
            "sub_type": "seal",
            "img_path": "images/seal.png",
            "bbox": [700, 750, 900, 950],
            "page_idx": 0,
        },
    ]
    middle = {
        "pdf_info": [{"page_idx": 0, "page_size": [1200, 1800]}],
        "_backend": "vlm",
        "_version_name": "3.0",
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("full.md", "# 压力管道安装记录")
        archive.writestr("document_content_list.json", json.dumps(content, ensure_ascii=False))
        archive.writestr("document_middle.json", json.dumps(middle, ensure_ascii=False))
        archive.writestr("images/seal.png", b"png")
    return output.getvalue()


def test_normalizes_mineru_vlm_into_local_ocr_contract() -> None:
    bundle = normalize_mineru_zip(
        mineru_zip(),
        storage_key="minio://documents/doc.pdf",
        file_name="doc.pdf",
        profile_id="generic_document_v1",
        document_type="generic_document",
        provider_task_id="TASK-1",
    )

    result = bundle.result
    assert result["status"] == "success"
    assert result["parserVersion"] == "mineru-vlm-adapter@1"
    assert result["pages"][0]["pageNo"] == 1
    assert result["pages"][0]["width"] == 1200
    assert result["fragments"][0]["bbox"] == [120.0, 360.0, 1080.0, 468.0]
    assert result["fragments"][0]["coordinateSystem"] == "rendered_pixels"
    assert result["fragments"][0]["sourceCoordinateSystem"] == "mineru_normalized_1000"
    assert result["tables"][0]["rows"] == 2
    assert result["tables"][0]["columns"] == 2
    assert result["tables"][0]["normalizedRows"][0]["管线号"] == "PL001"
    assert result["seals"][0]["candidateOnly"] is True
    assert result["seals"][0]["canSatisfyRequiredSeal"] is False
    assert "provider_confidence_unavailable" in result["quality"]["reasons"]
    assert bundle.artifacts["markdown"].data.startswith(b"#")
```

Add tests for:

- formulas, lists, code, captions, headers, and page footnotes.
- stable fragment IDs and reading order.
- multiple pages.
- unmappable bbox produces `coordinate_transform_unmapped`.
- missing Provider confidence never produces a high fixed score.
- empty/bad table HTML preserves a candidate plus diagnostic.
- missing `content_list` fails.
- absent Markdown is diagnostic-only.
- absolute paths, `..`, symlinks, too many members, oversized members, and excessive total expansion are rejected.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_mineru_ocr.py -q
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'libs.mineru_ocr'`.

- [ ] **Step 3: Implement safe normalization**

Create `backend/libs/mineru_ocr.py` with public structures:

```python
@dataclass(frozen=True)
class MinerUArtifact:
    name: str
    data: bytes
    content_type: str
    sha256: str


@dataclass(frozen=True)
class MinerUNormalizedBundle:
    result: dict[str, Any]
    artifacts: dict[str, MinerUArtifact]


def normalize_mineru_zip(
    zip_bytes: bytes,
    *,
    storage_key: str,
    file_name: str,
    profile_id: str | None,
    document_type: str | None,
    provider_task_id: str,
) -> MinerUNormalizedBundle:
    members = validated_zip_members(zip_bytes)
    content_name = unique_artifact_name(members, "_content_list.json", required=True)
    middle_name = unique_artifact_name(members, "_middle.json", required=True)
    markdown_name = primary_markdown_name(members)
    content = json.loads(members[content_name].decode("utf-8"))
    middle = json.loads(members[middle_name].decode("utf-8"))
    pages = mineru_pages(middle)
    result = build_mineru_result(
        content,
        pages=pages,
        storage_key=storage_key,
        file_name=file_name,
        profile_id=profile_id,
        document_type=document_type,
        provider_task_id=provider_task_id,
    )
    artifacts = build_mineru_artifacts(
        zip_bytes,
        content_bytes=members[content_name],
        middle_bytes=members[middle_name],
        markdown_bytes=members[markdown_name] if markdown_name else None,
        result=result,
    )
    return MinerUNormalizedBundle(result=result, artifacts=artifacts)
```

Implementation requirements:

- Implement the exact private helpers used above in the same module: `validated_zip_members`, `unique_artifact_name`, `primary_markdown_name`, `mineru_pages`, `build_mineru_result`, and `build_mineru_artifacts`.
- Validate every Zip member before extraction/read.
- Discover artifacts by suffix rather than assuming the input basename.
- Parse `middle.json` page sizes and map 0–1000 content-list bboxes to rendered pixels.
- Reuse `apps.ocr_service.engines.html_table_to_structure`.
- Convert `image/sub_type=seal` to advisory seal candidates.
- Add `sourceEngine="mineru_vlm"` and mapping provenance to evidence objects.
- Populate `pages`, `fragments`, `layoutBlocks`, `tables`, `seals`, `fields`, `quality`, `diagnostics`, `engineRuns`, `metadata`, and `groundingValidation`.
- Keep extracted raw files in memory or a controlled temporary directory that is always cleaned.
- Include the original Zip, Markdown, content list, middle JSON, and normalized JSON in `artifacts`.

- [ ] **Step 4: Run normalization tests and verify GREEN**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_mineru_ocr.py -q
```

Expected: PASS with no warnings.

- [ ] **Step 5: Commit the normalizer**

```bash
git add backend/libs/mineru_ocr.py backend/tests/test_mineru_ocr.py
git commit -m "feat: normalize MinerU OCR artifacts"
```

---

### Task 3: Persistent Remote Worker

**Files:**

- Modify: `backend/libs/db/repository.py:1437-1553`
- Modify: `backend/apps/worker/tasks.py`
- Modify: `backend/libs/integrations/task_dispatcher.py`
- Modify: `backend/apps/worker/celery_app.py`
- Create: `backend/tests/test_mineru_worker.py`

**Interfaces:**

- Consumes: `MinerUClient` and `normalize_mineru_zip`.
- Produces: `repo.update_ocr_job_record(job, status, stage, progress, provider_task_id, provider_task_type, diagnostics)`.
- Produces: Celery task `mineru_ocr_extract(job_record_id: str) -> dict[str, Any]`.
- Produces: `task_dispatcher.dispatch_mineru_ocr(job_record_id) -> dict[str, Any]`.
- Persists: `ocr_jobs`, `ocr_parse_results`, document OCR state, and `ocr-artifacts`.

- [ ] **Step 1: Write failing repository and worker tests**

Create `backend/tests/test_mineru_worker.py` with tests equivalent to:

```python
from types import SimpleNamespace

from apps.worker import tasks
from libs.db.repository import repo


def test_mineru_worker_persists_and_applies_bound_result(monkeypatch) -> None:
    job = repo.create_ocr_job_record(
        document_id="DOC-1",
        version_id="VER-1",
        storage_key="minio://documents/doc.pdf",
        file_name="doc.pdf",
        profile_id="generic_document_v1",
        document_type="generic_document",
        provider="mineru",
        options={"provider": "mineru"},
    )
    repo.state["documents"].append({"id": "DOC-1"})
    repo.state["versions"].append({"id": "VER-1", "documentId": "DOC-1"})

    fake_bundle = SimpleNamespace(
        result={
            "status": "success",
            "storageKey": job["storageKey"],
            "fileName": job["fileName"],
            "pages": [{"pageNo": 1}],
            "fragments": [{"pageNo": 1, "text": "合格"}],
            "tables": [],
            "seals": [],
            "fields": [],
            "diagnostics": [],
            "engineRuns": [{"engine": "mineru_vlm", "status": "success"}],
            "metadata": {"provider": "mineru", "model": "vlm"},
        },
        artifacts={},
    )
    fake_client = SimpleNamespace(
        submit_file=lambda *_args, **_kwargs: {"kind": "batch", "providerTaskId": "BATCH-1"},
        wait_for_result=lambda *_args, **_kwargs: {"full_zip_url": "https://cdn.example/result.zip"},
        download_result=lambda *_args, **_kwargs: b"zip",
    )
    monkeypatch.setattr(tasks, "MinerUClient", lambda: fake_client)
    monkeypatch.setattr(tasks, "mineru_source_path", lambda _job: (SimpleNamespace(), None))
    monkeypatch.setattr(tasks, "normalize_mineru_zip", lambda *_args, **_kwargs: fake_bundle)
    applied = []
    monkeypatch.setattr(repo, "apply_ocr_result", lambda doc, ver, result: applied.append((doc, ver, result)) or {"status": "success"})

    output = tasks.mineru_ocr_extract.run(job["id"])

    assert output["status"] == "success"
    assert repo.find_one("ocr_jobs", job["id"])["status"] == "success"
    assert repo.find_one("ocr_parse_results", output["parseResultId"], id_field="parseResultId")
    assert applied[0][0:2] == ("DOC-1", "VER-1")


def test_unbound_mineru_job_does_not_apply_business_result(monkeypatch) -> None:
    job = repo.create_ocr_job_record(
        document_id="",
        version_id="",
        storage_key="https://files.example/doc.pdf",
        file_name="doc.pdf",
        provider="mineru",
        source_url="https://files.example/doc.pdf",
        options={},
    )
    applied = []
    monkeypatch.setattr(repo, "apply_ocr_result", lambda *args: applied.append(args))
    monkeypatch.setattr(tasks, "run_mineru_job", lambda current: {"status": "success", "storageKey": current["storageKey"]})

    tasks.mineru_ocr_extract.run(job["id"])

    assert applied == []


def test_explicit_provider_dispatches_remote_and_default_stays_local(monkeypatch) -> None:
    repo.state["documents"].append({"id": "DOC-1"})
    repo.state["versions"].append(
        {"id": "VER-1", "documentId": "DOC-1", "ocrOptions": {"provider": "mineru"}}
    )
    dispatched = []
    local_calls = []
    monkeypatch.setattr(
        tasks.task_dispatcher,
        "dispatch_mineru_ocr",
        lambda job_id: dispatched.append(job_id) or {"taskId": "CELERY-1"},
    )
    monkeypatch.setattr(tasks, "parse_with_ocr_service", lambda *args, **kwargs: local_calls.append(args))

    result = tasks.parse_document.run("DOC-1", "VER-1", "minio://documents/doc.pdf", "doc.pdf")

    assert result["status"] == "queued"
    assert len(dispatched) == 1
    assert local_calls == []
```

Add tests for:

- Job stages `submit`, `upload`, `poll`, `download`, `normalize`, `persist`.
- progress callback persistence.
- artifact object names under `pipelines/mineru/{job_id}/`.
- URL source vs storage source.
- local temporary-file cleanup.
- failed MinerU task persists failure diagnostics.
- retryable exceptions use bounded Celery retry; non-retryable exceptions finish the Job.
- artifacts contain no Token or signed upload URL.
- actual document/version bindings call `apply_ocr_result`; missing bindings do not.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_mineru_worker.py -q
```

Expected: FAIL because repository parameters, progress method, worker task, and dispatcher do not exist.

- [ ] **Step 3: Extend the OCR Job repository contract**

Modify `create_ocr_job_record()` to accept:

```python
provider: str | None = None
source_url: str | None = None
options: dict[str, Any] | None = None
```

Persist only safe request values:

```python
job.update(
    {
        "provider": provider,
        "sourceUrl": redact_url_query(source_url),
        "sourceType": "url" if source_url else "storage",
        "options": sanitize_mineru_options(options or {}),
        "stage": "queued",
        "progress": 0,
        "providerTaskId": None,
        "providerTaskType": None,
    }
)
```

Add:

```python
def update_ocr_job_record(
    self,
    job: dict[str, Any] | None,
    *,
    status: str | None = None,
    stage: str | None = None,
    progress: int | None = None,
    provider_task_id: str | None = None,
    provider_task_type: str | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not job:
        return None
    now = server_time()
    if status is not None:
        job["status"] = status
    if stage is not None:
        job["stage"] = stage
    if progress is not None:
        job["progress"] = max(0, min(int(progress), 100 if status in {"success", "failed"} else 99))
    if provider_task_id is not None:
        job["providerTaskId"] = provider_task_id
    if provider_task_type is not None:
        job["providerTaskType"] = provider_task_type
    if diagnostics is not None:
        job["diagnostics"] = self.clone(diagnostics)
    job["updatedAt"] = now
    return job
```

The method must bound progress to 0–99 before terminal completion and update timestamps.

- [ ] **Step 4: Implement dispatch and Celery routing**

Add to `task_dispatcher.py`:

```python
def dispatch_mineru_ocr(job_record_id: str) -> dict[str, Any]:
    mode = dispatch_mode()
    if mode == "inline":
        from apps.worker.tasks import mineru_ocr_extract
        return {"mode": mode, "result": mineru_ocr_extract.run(job_record_id)}
    if mode == "celery":
        from apps.worker.tasks import mineru_ocr_extract
        result = mineru_ocr_extract.apply_async(
            args=[job_record_id],
            queue="ocr.remote",
            priority=broker_priority(9),
            task_id=deterministic_task_id("mineru-ocr", job_record_id),
        )
        return {
            "mode": mode,
            "taskId": result.id,
            "queue": "ocr.remote",
            "priority": 9,
            "statusReason": "mineru_ocr_queued",
        }
    return {"mode": mode, "taskId": None, "statusReason": "mineru_ocr_requires_task_dispatch"}
```

Add the task route:

```python
"apps.worker.tasks.mineru_ocr_extract": {
    "queue": "ocr.remote",
    "priority": broker_priority(9),
},
```

- [ ] **Step 5: Implement the worker orchestration**

Add `mineru_ocr_extract` to `apps/worker/tasks.py`. Its sequence must be:

1. refresh `ocr_jobs`, `ocr_parse_results`, `documents`, and `versions`;
2. load the Job and validate `provider == "mineru"`;
3. mark running/submit;
4. submit URL or download `storageKey` then submit file;
5. persist Provider task kind/ID;
6. poll with progress heartbeats;
7. bounded-download Zip;
8. normalize;
9. store raw and normalized artifacts with SHA-256;
10. add artifact references to result metadata;
11. call `finish_ocr_job_record`;
12. call `apply_ocr_result` only when both real records exist;
13. flush the precise mutated state records;
14. clean temporary source files in `finally`.

Use stable safe diagnostics such as:

- `MINERU_NOT_CONFIGURED`
- `MINERU_SUBMIT_FAILED`
- `MINERU_JOB_FAILED`
- `MINERU_JOB_TIMEOUT`
- `MINERU_RESULT_DOWNLOAD_FAILED`
- `MINERU_RESULT_INVALID`
- `MINERU_PERSIST_FAILED`

- [ ] **Step 6: Run worker tests and verify GREEN**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_mineru_worker.py tests/test_celery_priority_contract.py -q
```

Expected: PASS with no warnings.

- [ ] **Step 7: Commit worker integration**

```bash
git add backend/libs/db/repository.py backend/apps/worker/tasks.py backend/libs/integrations/task_dispatcher.py backend/apps/worker/celery_app.py backend/tests/test_mineru_worker.py
git commit -m "feat: persist MinerU OCR jobs"
```

---

### Task 4: Internal API and Explicit Provider Routing

**Files:**

- Create: `backend/apps/api/mineru_ocr_routes.py`
- Modify: `backend/apps/api/main.py:19-21,103-113,1087-1092`
- Modify: `backend/apps/worker/tasks.py:743-910`
- Create: `backend/tests/test_mineru_api.py`
- Modify: `backend/tests/test_mineru_worker.py`

**Interfaces:**

- Produces: `POST /internal/ocr/mineru/tasks`.
- Produces: `POST /internal/ocr/mineru/tasks/upload`.
- Produces: `GET /internal/ocr/mineru/tasks/{job_id}`.
- Consumes: repository job methods and `dispatch_mineru_ocr`.
- Extends: document OCR routing when version `ocrOptions.provider == "mineru"`.

- [ ] **Step 1: Write failing API contract tests**

Create `backend/tests/test_mineru_api.py` with tests equivalent to:

```python
from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo


client = TestClient(app)


def test_create_url_mineru_task(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.api.mineru_ocr_routes.task_dispatcher.dispatch_mineru_ocr",
        lambda job_id: {"mode": "celery", "taskId": "CELERY-1", "queue": "ocr.remote"},
    )

    response = client.post(
        "/internal/ocr/mineru/tasks",
        json={
            "url": "https://files.example/document.pdf",
            "fileName": "document.pdf",
            "profileId": "generic_document_v1",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert data["provider"] == "mineru"
    assert data["model"] == "vlm"
    assert data["pollUrl"].endswith(data["jobId"])


def test_rejects_multiple_sources() -> None:
    response = client.post(
        "/internal/ocr/mineru/tasks",
        json={
            "url": "https://files.example/document.pdf",
            "storageKey": "minio://documents/document.pdf",
            "fileName": "document.pdf",
        },
    )
    assert response.json()["code"] != 0


def test_rejects_private_url() -> None:
    response = client.post(
        "/internal/ocr/mineru/tasks",
        json={"url": "https://127.0.0.1/document.pdf", "fileName": "document.pdf"},
    )
    assert response.json()["code"] != 0
    assert "127.0.0.1" not in str(response.json())
```

Add tests for:

- missing sources.
- supported and unsupported extensions.
- `pageRanges` grammar and 200-page bound.
- source URL DNS results in public vs private/reserved addresses.
- task-dispatch unavailable marks Job failed instead of returning false success.
- status reads return summary/artifact references but no secret fields.
- raw upload metadata decoding, empty body, 200MB bound, and object-storage failure.
- upload stores bytes and creates a storage-backed MinerU Job.

- [ ] **Step 2: Run API tests and verify RED**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_mineru_api.py -q
```

Expected: FAIL because `apps.api.mineru_ocr_routes` and its routes do not exist.

- [ ] **Step 3: Implement request validation and routes**

Create `backend/apps/api/mineru_ocr_routes.py` with:

```python
router = APIRouter()


@router.post("/internal/ocr/mineru/tasks")
def create_mineru_task(request: Request, payload: dict[str, Any]):
    source = validate_mineru_task_payload(payload)
    job = create_mineru_job_record(source)
    dispatch = task_dispatcher.dispatch_mineru_ocr(str(job["id"]))
    if not dispatch.get("taskId") and dispatch.get("mode") != "inline":
        repo.update_ocr_job_record(
            job,
            status="failed",
            stage="dispatch",
            diagnostics=[{"code": "MINERU_DISPATCH_UNAVAILABLE", "level": "error"}],
        )
    flush_state_records({"ocr_jobs": [job]})
    return ok(public_mineru_job(job, dispatch=dispatch), request)


@router.post("/internal/ocr/mineru/tasks/upload")
async def upload_mineru_task(request: Request):
    metadata = decode_upload_metadata(request.headers.get("X-AICheck-Ocr-Metadata-B64"))
    body = await limited_request_body(request, limit=200 * 1024 * 1024)
    storage_key = store_mineru_upload(body, metadata)
    return create_mineru_task(request, {**metadata, "storageKey": storage_key})


@router.get("/internal/ocr/mineru/tasks/{job_id}")
def get_mineru_task(request: Request, job_id: str):
    job = repo.find_one("ocr_jobs", job_id)
    if not job or job.get("provider") != "mineru":
        return fail(errors.NOT_FOUND, request, message="MinerU OCR Job 不存在。")
    return ok(public_mineru_job(job), request)
```

Validation helpers must:

- Implement the exact helpers used above in the route module: `validate_mineru_task_payload`, `create_mineru_job_record`, `public_mineru_job`, `decode_upload_metadata`, `limited_request_body`, and `store_mineru_upload`.
- require exactly one source;
- accept only MinerU-supported file extensions;
- require HTTPS and resolve/check every URL address;
- validate safe `data_id` derived from local Job ID;
- allow only `language`, `pageRanges`, `noCache`, and `cacheTolerance`;
- ensure caller cannot set `model_version`;
- enforce upload byte size before object-store write.

Use existing `ok()` and `fail()` envelopes, configured tenant context, `repo.create_ocr_job_record`, precise `flush_state_records`, and `task_dispatcher.dispatch_mineru_ocr`.

Include the router with and without `/api` prefix, matching existing API behavior. Add `X-AICheck-Ocr-Metadata-B64` to allowed request headers.

- [ ] **Step 4: Verify API GREEN**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_mineru_api.py -q
```

Expected: PASS with no warnings.

- [ ] **Step 5: Write a failing explicit-provider route test**

Add a test to `test_mineru_worker.py` that creates a version with:

```python
{"id": "VER-1", "documentId": "DOC-1", "ocrOptions": {"provider": "mineru"}}
```

Then call `parse_document.run("DOC-1", "VER-1", "minio://documents/doc.pdf", "doc.pdf")` with `task_dispatcher.dispatch_mineru_ocr` replaced by a recorder. Assert:

- the MinerU dispatcher is called;
- local `parse_with_ocr_service` is not called;
- the result is `queued`;
- the Job contains `provider="mineru"`.

Add the inverse test with no Provider and assert the existing local function is called.

- [ ] **Step 6: Run explicit-provider tests and verify RED**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_mineru_worker.py -q -k provider
```

Expected: FAIL because `parse_document` does not inspect `ocrOptions.provider`.

- [ ] **Step 7: Implement the explicit-provider branch**

In `parse_document`, after `ocr_options` are assembled and before official/local Provider selection:

```python
requested_provider = str(ocr_options.get("provider") or "").strip().lower()
if requested_provider not in {"", "local", "mineru"}:
    failure_result = {
        "storageKey": storage_key,
        "fileName": file_name,
        "status": "failed",
        "diagnostics": [{"code": "OCR_PROVIDER_UNSUPPORTED", "level": "error"}],
    }
    repo.finish_ocr_job_record(ocr_job_record, failure_result)
    persist_ocr_pipeline_progress(pipeline_run, task=task, ocr_job=ocr_job_record)
    return failure_result
if requested_provider == "mineru":
    ocr_job_record.update({"provider": "mineru", "options": ocr_options, "stage": "queued", "progress": 0})
    dispatch = task_dispatcher.dispatch_mineru_ocr(str(ocr_job_record["id"]))
    pipeline_run.update({"provider": "mineru", "model": "vlm", "mineruDispatch": dispatch})
    persist_ocr_pipeline_progress(pipeline_run, task=task, ocr_job=ocr_job_record)
    return {
        "documentId": document_id,
        "versionId": version_id,
        "status": "queued",
        "pipelineRunId": pipeline_run.get("id"),
        "ocrJobRecordId": ocr_job_record.get("id"),
        "dispatch": dispatch,
        "provider": "mineru",
    }
```

Preserve all current behavior when Provider is absent or `local`.

- [ ] **Step 8: Run API/provider tests and verify GREEN**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_mineru_api.py tests/test_mineru_worker.py tests/test_ocr_pipeline_hardening.py -q
```

Expected: PASS with no warnings.

- [ ] **Step 9: Commit API and routing**

```bash
git add backend/apps/api/mineru_ocr_routes.py backend/apps/api/main.py backend/apps/worker/tasks.py backend/tests/test_mineru_api.py backend/tests/test_mineru_worker.py
git commit -m "feat: expose MinerU OCR tasks"
```

---

### Task 5: Deployment Configuration, Local Secret, and Verification

**Files:**

- Modify: `backend/.env.example`
- Modify ignored local file: `backend/.env`
- Modify: `backend/docker-compose.yml`
- Modify: `backend/docker-compose.accuracy-pipeline.yml`
- Modify: `backend/docker-compose.deploy.yml`
- Modify: `backend/README.md`
- Create: `backend/tests/test_mineru_compose.py`

**Interfaces:**

- Supplies MinerU configuration only to `ocr.remote`.
- Documents explicit API and Provider usage.
- Keeps the real secret outside Git.

- [ ] **Step 1: Write failing configuration isolation tests**

Create `backend/tests/test_mineru_compose.py`:

```python
from pathlib import Path

import yaml


BACKEND = Path(__file__).resolve().parents[1]


def compose(name: str) -> dict:
    return yaml.safe_load((BACKEND / name).read_text(encoding="utf-8"))


def test_base_compose_isolates_mineru_secret_to_remote_ocr_worker() -> None:
    payload = compose("docker-compose.yml")
    services = payload["services"]
    remote = services["ocr-remote-worker-service"]["environment"]
    assert "AICHECK_MINERU_API_KEY" in remote
    assert "AICHECK_MINERU_API_KEY" not in services["ocr-service"]["environment"]


def test_env_example_documents_fixed_vlm_provider() -> None:
    text = (BACKEND / ".env.example").read_text(encoding="utf-8")
    assert "AICHECK_MINERU_API_KEY=replace-with-mineru-api-key" in text
    assert "AICHECK_MINERU_MODEL_VERSION=vlm" in text
```

Add checks for the accuracy and deploy Compose files and for the `ocr.remote` queue command.

- [ ] **Step 2: Run configuration tests and verify RED**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_mineru_compose.py -q
```

Expected: FAIL because the service and variables are absent.

- [ ] **Step 3: Add committed non-secret configuration**

Add to `.env.example`:

```dotenv
AICHECK_MINERU_BASE_URL=https://mineru.net
AICHECK_MINERU_API_KEY=replace-with-mineru-api-key
AICHECK_MINERU_MODEL_VERSION=vlm
AICHECK_MINERU_TIMEOUT_SECONDS=60
AICHECK_MINERU_POLL_INTERVAL_SECONDS=3
AICHECK_MINERU_JOB_TIMEOUT_SECONDS=1800
AICHECK_MINERU_MAX_DOWNLOAD_BYTES=536870912
```

Refactor worker environment mappings to named YAML anchors where necessary, then add `ocr-remote-worker-service` with:

```yaml
command: celery -A apps.worker.celery_app.celery_app worker --loglevel=INFO --concurrency=2 --prefetch-multiplier=1 -Q ocr.remote
environment:
  <<: *worker-environment
  AICHECK_MINERU_BASE_URL: ${AICHECK_MINERU_BASE_URL:-https://mineru.net}
  AICHECK_MINERU_API_KEY: ${AICHECK_MINERU_API_KEY:?AICHECK_MINERU_API_KEY is required}
  AICHECK_MINERU_MODEL_VERSION: vlm
  AICHECK_MINERU_TIMEOUT_SECONDS: ${AICHECK_MINERU_TIMEOUT_SECONDS:-60}
  AICHECK_MINERU_POLL_INTERVAL_SECONDS: ${AICHECK_MINERU_POLL_INTERVAL_SECONDS:-3}
  AICHECK_MINERU_JOB_TIMEOUT_SECONDS: ${AICHECK_MINERU_JOB_TIMEOUT_SECONDS:-1800}
```

Do not add any MinerU variables to `ocr-service`.

- [ ] **Step 4: Safely write the real local key**

Use a non-echoing, exact-key update that:

- reads the user-provided value from the current task context;
- replaces an existing `AICHECK_MINERU_API_KEY` line or appends one;
- never prints the value;
- leaves file mode at `0600`;
- verifies only that the key exists and is non-empty.

Required final local state:

```text
backend/.env contains exactly one non-empty AICHECK_MINERU_API_KEY assignment
```

Never stage `backend/.env`.

- [ ] **Step 5: Document usage**

Add to `backend/README.md`:

```text
POST /internal/ocr/mineru/tasks
POST /internal/ocr/mineru/tasks/upload
GET  /internal/ocr/mineru/tasks/{jobId}
```

Document:

- URL and storage examples.
- raw upload metadata header.
- fixed `vlm` behavior.
- `options.provider="mineru"` explicit routing.
- local OCR remains default.
- `ocr.remote` worker requirement.

- [ ] **Step 6: Run configuration tests and Compose validation**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_mineru_compose.py -q
docker compose --env-file .env config --quiet
docker compose --env-file .env -f docker-compose.yml -f docker-compose.accuracy-pipeline.yml config --quiet
```

Expected: all commands exit 0 and no secret is printed.

- [ ] **Step 7: Run the complete targeted and OCR regression suite**

Run:

```bash
cd backend
.venv/bin/python -m pytest \
  tests/test_mineru_client.py \
  tests/test_mineru_ocr.py \
  tests/test_mineru_worker.py \
  tests/test_mineru_api.py \
  tests/test_mineru_compose.py \
  tests/test_contract.py \
  tests/test_ocr_pipeline_hardening.py \
  tests/test_celery_priority_contract.py \
  -q
```

Expected: PASS with no errors or warnings introduced by MinerU.

- [ ] **Step 8: Run static checks**

Run:

```bash
cd backend
.venv/bin/python -m ruff check \
  apps/api/mineru_ocr_routes.py \
  apps/api/main.py \
  apps/worker/tasks.py \
  libs/integrations/mineru_client.py \
  libs/integrations/task_dispatcher.py \
  libs/mineru_ocr.py \
  libs/db/repository.py \
  tests/test_mineru_client.py \
  tests/test_mineru_ocr.py \
  tests/test_mineru_worker.py \
  tests/test_mineru_api.py \
  tests/test_mineru_compose.py
```

Expected: exit 0.

- [ ] **Step 9: Perform the completion audit**

Verify without printing the secret:

```bash
git check-ignore -v backend/.env
git status --short
git diff --check
test "$(grep -c '^AICHECK_MINERU_API_KEY=.' backend/.env)" -eq 1
! git ls-files --error-unmatch backend/.env
```

Then inspect code/test evidence for every acceptance criterion in the design:

1. three source forms;
2. fixed precise `vlm`;
3. local default unchanged;
4. explicit Provider routing;
5. Zip parsing and local structure adaptation;
6. existing Job/ParseResult/artifact persistence;
7. bound document application and unbound isolation;
8. bounded errors/retries and secret safety.

- [ ] **Step 10: Commit deployment and documentation**

```bash
git add \
  backend/.env.example \
  backend/docker-compose.yml \
  backend/docker-compose.accuracy-pipeline.yml \
  backend/docker-compose.deploy.yml \
  backend/README.md \
  backend/tests/test_mineru_compose.py
git commit -m "chore: configure MinerU OCR worker"
```

Do not stage `backend/.env`.
