from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import secrets
import shutil
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import fitz
import httpx
from fastapi import FastAPI, HTTPException, Request
from PIL import Image


PADDLE_URL = os.getenv("PADDLE_URL", "http://127.0.0.1:18110").rstrip("/")
NUEXTRACT_URL = os.getenv("NUEXTRACT_URL", "http://127.0.0.1:18220").rstrip("/")
API_KEY = os.getenv("DOCUMENT_AI_API_KEY", "")
MAX_WAITING = 2
MAX_PAGES = 6
MAX_CANDIDATES = 64
MAX_PRIOR_TOKENS = 12_000
MAX_OUTPUT_TOKENS = 2048
DEADLINE_SECONDS = 180
MAX_UPLOAD_BYTES = int(os.getenv("DOCUMENT_AI_MAX_UPLOAD_BYTES", str(128 * 1024 * 1024)))
UPLOAD_ROOT = Path(os.getenv("DOCUMENT_AI_UPLOAD_ROOT", "/usrdata/aicheck-cache/document-ai/uploads"))


class QueueGate:
    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(1)
        self._lock = asyncio.Lock()
        self.active = 0
        self.waiting = 0

    @asynccontextmanager
    async def slot(self):
        queued_at = time.monotonic()
        registered = False
        acquired = False
        async with self._lock:
            if self.active >= 1 and self.waiting >= MAX_WAITING:
                raise HTTPException(
                    status_code=429,
                    detail={"code": "DOCUMENT_AI_QUEUE_FULL", "retryAfterSeconds": 15},
                    headers={"Retry-After": "15"},
                )
            self.waiting += 1
            registered = True
        try:
            await self._semaphore.acquire()
            async with self._lock:
                self.waiting -= 1
                self.active += 1
                registered = False
                acquired = True
            yield round((time.monotonic() - queued_at) * 1000)
        finally:
            if registered:
                async with self._lock:
                    self.waiting = max(0, self.waiting - 1)
            if acquired:
                async with self._lock:
                    self.active = max(0, self.active - 1)
                self._semaphore.release()


queue_gate = QueueGate()
app = FastAPI(title="AIcheck Document AI Shadow", version="2")


def require_auth(request: Request) -> None:
    if not API_KEY:
        raise HTTPException(503, detail={"code": "DOCUMENT_AI_API_KEY_MISSING"})
    authorization = request.headers.get("authorization", "")
    expected = f"Bearer {API_KEY}"
    if not secrets.compare_digest(authorization, expected):
        raise HTTPException(401, detail={"code": "DOCUMENT_AI_AUTH_REQUIRED"})


def decode_metadata(request: Request) -> dict[str, Any]:
    encoded = request.headers.get("x-aicheck-document-ai-metadata-b64", "")
    if not encoded:
        raise HTTPException(400, detail={"code": "DOCUMENT_AI_METADATA_REQUIRED"})
    try:
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded + padding).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(400, detail={"code": "DOCUMENT_AI_METADATA_INVALID"}) from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, detail={"code": "DOCUMENT_AI_METADATA_INVALID"})
    return payload


def conservative_token_estimate(value: Any) -> int:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return max(1, (len(raw.encode("utf-8")) + 2) // 3)


def validate_request_metadata(metadata: dict[str, Any]) -> tuple[dict[str, Any], list[int]]:
    if metadata.get("advisoryOnly") is not True:
        raise HTTPException(400, detail={"code": "SHADOW_ADVISORY_ONLY_REQUIRED"})
    prior = metadata.get("evidencePrior")
    if not isinstance(prior, dict) or prior.get("schemaVersion") != "EvidencePrior@2":
        raise HTTPException(400, detail={"code": "EVIDENCE_PRIOR_V2_REQUIRED"})
    candidates = prior.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > MAX_CANDIDATES:
        raise HTTPException(400, detail={"code": "EVIDENCE_PRIOR_CANDIDATE_LIMIT"})
    if conservative_token_estimate(prior) > MAX_PRIOR_TOKENS:
        raise HTTPException(400, detail={"code": "EVIDENCE_PRIOR_TOKEN_LIMIT"})
    selected_pages = metadata.get("selectedPageNos") or prior.get("selectedPageNos") or [1]
    if not isinstance(selected_pages, list):
        raise HTTPException(400, detail={"code": "SELECTED_PAGES_INVALID"})
    try:
        selected_pages = sorted({int(page_no) for page_no in selected_pages})
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, detail={"code": "SELECTED_PAGES_INVALID"}) from exc
    if not selected_pages or len(selected_pages) > MAX_PAGES or min(selected_pages) < 1:
        raise HTTPException(400, detail={"code": "SELECTED_PAGES_LIMIT"})
    constraints = metadata.get("constraints") if isinstance(metadata.get("constraints"), dict) else {}
    if int(constraints.get("maxOutputTokens") or MAX_OUTPUT_TOKENS) > MAX_OUTPUT_TOKENS:
        raise HTTPException(400, detail={"code": "OUTPUT_TOKEN_LIMIT"})
    return prior, selected_pages


def save_upload(data: bytes, file_name: str, run_dir: Path) -> Path:
    suffix = Path(file_name).suffix.lower() or ".bin"
    target = run_dir / f"source{suffix}"
    target.write_bytes(data)
    return target


def render_selected_pages(source_path: Path, selected_pages: list[int], run_dir: Path) -> dict[int, Path]:
    rendered: dict[int, Path] = {}
    with source_path.open("rb") as handle:
        signature = handle.read(4)
    if signature == b"%PDF":
        document = fitz.open(source_path)
        try:
            for page_no in selected_pages:
                if page_no > document.page_count:
                    raise HTTPException(400, detail={"code": "SELECTED_PAGE_OUT_OF_RANGE", "pageNo": page_no})
                pixmap = document.load_page(page_no - 1).get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72), alpha=False)
                target = run_dir / f"page-{page_no:04d}.png"
                pixmap.save(target)
                rendered[page_no] = target
        finally:
            document.close()
        return rendered
    if selected_pages != [1]:
        raise HTTPException(400, detail={"code": "IMAGE_INPUT_ONLY_HAS_PAGE_ONE"})
    try:
        with Image.open(source_path) as image:
            target = run_dir / "page-0001.png"
            image.convert("RGB").save(target, "PNG")
            rendered[1] = target
    except Exception as exc:
        raise HTTPException(400, detail={"code": "DOCUMENT_IMAGE_INVALID"}) from exc
    return rendered


def normalize_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) < 4:
        return None
    try:
        x1, y1, x2, y2 = [float(value[index]) for index in range(4)]
    except (TypeError, ValueError):
        return None
    return [x1, y1, x2, y2] if x2 > x1 and y2 > y1 else None


def difficult_rois(prior: dict[str, Any], rendered_pages: dict[int, Path]) -> list[tuple[int, list[float], str]]:
    rois: list[tuple[int, list[float], str]] = []
    for diagnostic in prior.get("diagnostics") or []:
        if not isinstance(diagnostic, dict) or diagnostic.get("code") != "TABLE_CONTENT_SPARSE":
            continue
        page_no = int(diagnostic.get("pageNo") or 1)
        retry_plan = diagnostic.get("retryPlan") if isinstance(diagnostic.get("retryPlan"), dict) else {}
        for bbox in retry_plan.get("tiles") or []:
            normalized = normalize_bbox(bbox)
            if normalized and page_no in rendered_pages:
                rois.append((page_no, normalized, "sparse_table"))
    for candidate in prior.get("candidates") or []:
        if not isinstance(candidate, dict) or candidate.get("candidateType") != "seal_crop":
            continue
        if candidate.get("formalEvidenceEligible") is True:
            continue
        page_no = int(candidate.get("pageNo") or 1)
        bbox = normalize_bbox(candidate.get("bbox"))
        if bbox and page_no in rendered_pages:
            rois.append((page_no, bbox, "seal"))
    return rois[:4]


def crop_rois(
    rois: list[tuple[int, list[float], str]],
    rendered_pages: dict[int, Path],
    run_dir: Path,
) -> tuple[list[Path], list[dict[str, Any]]]:
    crops: list[Path] = []
    diagnostics: list[dict[str, Any]] = []
    for index, (page_no, bbox, purpose) in enumerate(rois, start=1):
        with Image.open(rendered_pages[page_no]) as image:
            x1 = max(0, min(image.width, int(bbox[0])))
            y1 = max(0, min(image.height, int(bbox[1])))
            x2 = max(0, min(image.width, int(bbox[2])))
            y2 = max(0, min(image.height, int(bbox[3])))
            if x2 <= x1 or y2 <= y1:
                diagnostics.append({"code": "SHADOW_ROI_OUT_OF_RANGE", "pageNo": page_no, "bbox": bbox})
                continue
            target = run_dir / f"roi-{index:02d}-{purpose}.png"
            image.crop((x1, y1, x2, y2)).convert("RGB").save(target, "PNG")
            crops.append(target)
    return crops, diagnostics


def flatten_strings(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            strings.extend(flatten_strings(child))
    elif isinstance(value, list):
        for child in value:
            strings.extend(flatten_strings(child))
    elif isinstance(value, str) and value.strip():
        strings.append(" ".join(value.split()))
    return strings


async def paddle_supplement(crops: list[Path]) -> tuple[str, str | None, list[dict[str, Any]]]:
    if not crops:
        return "", None, []
    snippets: list[str] = []
    revision = None
    diagnostics: list[dict[str, Any]] = []
    headers = {"Authorization": f"Bearer {API_KEY}"}
    async with httpx.AsyncClient(timeout=120) as client:
        for crop in crops:
            try:
                response = await client.post(
                    f"{PADDLE_URL}/v1/parse",
                    headers=headers,
                    files={"file": (crop.name, crop.read_bytes(), "image/png")},
                )
                response.raise_for_status()
                payload = response.json()
                revision = str(payload.get("revision") or revision or "") or None
                snippets.extend(flatten_strings(payload.get("pages"))[:30])
            except Exception as exc:
                diagnostics.append({"code": "SHADOW_PADDLE_ROI_FAILED", "reason": type(exc).__name__})
    context = "\n".join(dict.fromkeys(snippets))[:2400]
    return context, revision, diagnostics


def build_nuextract_template(structured: dict[str, Any]) -> dict[str, Any]:
    fields = {
        str(field): {"value": "", "sourceCandidateIds": []}
        for field in structured.get("fields") or []
        if str(field).strip()
    }
    tables = {
        str(table): [{"cells": {}, "sourceCandidateIds": []}]
        for table in structured.get("tables") or []
        if str(table).strip()
    }
    return {"fields": fields, "tables": tables, "seals": []}


async def call_nuextract(
    rendered_pages: dict[int, Path],
    metadata: dict[str, Any],
    prior: dict[str, Any],
    paddle_context: str,
    *,
    include_tables: bool = True,
) -> dict[str, Any]:
    structured = metadata.get("structuredExtraction") if isinstance(metadata.get("structuredExtraction"), dict) else {}
    definitions = structured.get("fieldDefinitions") if isinstance(structured.get("fieldDefinitions"), dict) else {}
    instructions = (
        "Return valid JSON matching the template. Cite only EvidencePrior candidateId values in sourceCandidateIds. "
        "Do not invent bbox or page numbers. If visible content has no supporting candidate, leave sourceCandidateIds empty. "
        "Empty sourceCandidateIds means directVisionOnly and advisory-only. "
        "Return values and sourceCandidateIds only: no explanations, OCR transcripts, bbox, page objects, or confidence prose. "
        "Use at most three minimal sourceCandidateIds per value. Do not transcribe a full table. "
        "For each requested table return at most four rows most relevant to the requested fields and at most twelve cells per row. "
        + ("Field semantics: " + json.dumps(definitions, ensure_ascii=False) + ". " if definitions else "")
        + ("Supplemental difficult-ROI scanner text is advisory and has no candidate IDs:\n" + paddle_context if paddle_context else "")
        + (" Extract fields only; omit all tables in this retry." if not include_tables else "")
    )
    files = [
        ("files", (path.name, path.read_bytes(), "image/png"))
        for _, path in sorted(rendered_pages.items())
    ]
    form = {
        "template": json.dumps(
            build_nuextract_template(structured)
            if include_tables
            else {**build_nuextract_template(structured), "tables": {}},
            ensure_ascii=False,
        ),
        "instructions": instructions,
        "evidence_prior": json.dumps(prior, ensure_ascii=False),
        "enable_thinking": "false",
    }
    async with httpx.AsyncClient(timeout=DEADLINE_SECONDS) as client:
        response = await client.post(
            f"{NUEXTRACT_URL}/v1/extract",
            headers={"Authorization": f"Bearer {API_KEY}"},
            files=files,
            data=form,
        )
        response.raise_for_status()
        return response.json()


async def dependency_probe(path: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {API_KEY}"}
    output: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=10) as client:
        for name, url in (("paddle", PADDLE_URL), ("nuextract3", NUEXTRACT_URL)):
            try:
                response = await client.get(f"{url}{path}", headers=headers)
                output[name] = {"reachable": response.is_success, "statusCode": response.status_code}
            except Exception as exc:
                output[name] = {"reachable": False, "reason": type(exc).__name__}
    return output


@app.get("/healthz")
async def healthz(request: Request):
    require_auth(request)
    dependencies = await dependency_probe("/healthz")
    return {"status": "ok", "dependencies": dependencies}


@app.get("/readyz")
async def readyz(request: Request):
    require_auth(request)
    dependencies = await dependency_probe("/readyz")
    ready = all(item.get("reachable") for item in dependencies.values())
    if not ready:
        raise HTTPException(503, detail={"ready": False, "dependencies": dependencies})
    return {"ready": True, "dependencies": dependencies}


@app.get("/internal/doctor")
async def doctor(request: Request):
    require_auth(request)
    dependencies = await dependency_probe("/healthz")
    return {
        "status": "ok" if all(item.get("reachable") for item in dependencies.values()) else "degraded",
        "mode": "shadow",
        "advisoryOnly": True,
        "queue": {"active": queue_gate.active, "waiting": queue_gate.waiting, "maxWaiting": MAX_WAITING},
        "limits": {
            "maxPages": MAX_PAGES,
            "maxCandidates": MAX_CANDIDATES,
            "maxPriorTokens": MAX_PRIOR_TOKENS,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "deadlineSeconds": DEADLINE_SECONDS,
        },
        "dependencies": dependencies,
    }


@app.post("/v1/hybrid/extract")
async def hybrid_extract(request: Request):
    require_auth(request)
    metadata = decode_metadata(request)
    prior, selected_pages = validate_request_metadata(metadata)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, detail={"code": "DOCUMENT_TOO_LARGE"})
        except ValueError as exc:
            raise HTTPException(400, detail={"code": "CONTENT_LENGTH_INVALID"}) from exc
    body = await request.body()
    if not body:
        raise HTTPException(400, detail={"code": "DOCUMENT_BODY_REQUIRED"})
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, detail={"code": "DOCUMENT_TOO_LARGE"})
    raw_run_id = str(metadata.get("runId") or f"DOCSH-{uuid.uuid4().hex[:16].upper()}")
    run_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw_run_id)[:80] or f"DOCSH-{uuid.uuid4().hex[:16].upper()}"
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix=f"{run_id}-", dir=UPLOAD_ROOT))
    started = time.monotonic()
    diagnostics: list[dict[str, Any]] = []
    try:
        source = save_upload(body, str(metadata.get("fileName") or "source.bin"), run_dir)
        rendered_pages = render_selected_pages(source, selected_pages, run_dir)
        rois = difficult_rois(prior, rendered_pages)
        crops, crop_diagnostics = crop_rois(rois, rendered_pages, run_dir)
        diagnostics.extend(crop_diagnostics)
        async with queue_gate.slot() as queue_time_ms:
            pipeline_task = asyncio.create_task(paddle_supplement(crops))
            while not pipeline_task.done():
                if await request.is_disconnected():
                    pipeline_task.cancel()
                    raise HTTPException(499, detail={"code": "CLIENT_DISCONNECTED"})
                if time.monotonic() - started >= DEADLINE_SECONDS:
                    pipeline_task.cancel()
                    raise HTTPException(504, detail={"code": "DOCUMENT_AI_DEADLINE"})
                await asyncio.sleep(0.1)
            paddle_context, paddle_revision, paddle_diagnostics = await pipeline_task
            diagnostics.extend(paddle_diagnostics)
            nuextract_task = asyncio.create_task(call_nuextract(rendered_pages, metadata, prior, paddle_context))
            while not nuextract_task.done():
                if await request.is_disconnected():
                    nuextract_task.cancel()
                    raise HTTPException(499, detail={"code": "CLIENT_DISCONNECTED"})
                if time.monotonic() - started >= DEADLINE_SECONDS:
                    nuextract_task.cancel()
                    raise HTTPException(504, detail={"code": "DOCUMENT_AI_DEADLINE"})
                await asyncio.sleep(0.1)
            nu_response = await nuextract_task
            primary_elapsed = float(nu_response.get("elapsedSeconds") or 0)
            json_retry_count = 0
            table_extraction_deferred = False
            if nu_response.get("parsed") is None:
                diagnostics.append({"code": "NUEXTRACT_JSON_INVALID_FIELD_ONLY_RETRY"})
                json_retry_count = 1
                table_extraction_deferred = True
                retry_task = asyncio.create_task(
                    call_nuextract(
                        rendered_pages,
                        metadata,
                        prior,
                        paddle_context,
                        include_tables=False,
                    )
                )
                while not retry_task.done():
                    if await request.is_disconnected():
                        retry_task.cancel()
                        raise HTTPException(499, detail={"code": "CLIENT_DISCONNECTED"})
                    if time.monotonic() - started >= DEADLINE_SECONDS:
                        retry_task.cancel()
                        raise HTTPException(504, detail={"code": "DOCUMENT_AI_DEADLINE"})
                    await asyncio.sleep(0.1)
                retry_response = await retry_task
                retry_elapsed = float(retry_response.get("elapsedSeconds") or 0)
                nu_response = retry_response
            else:
                retry_elapsed = 0.0
        if nu_response.get("parsed") is None:
            raise HTTPException(502, detail={"code": "NUEXTRACT_JSON_INVALID_AFTER_RETRY"})
        total_ms = round((time.monotonic() - started) * 1000)
        return {
            "runId": run_id,
            "advisoryOnly": True,
            "formalEvidenceReady": False,
            "structuredOutput": nu_response.get("parsed"),
            "modelRevision": nu_response.get("revision"),
            "paddleModelRevision": paddle_revision,
            "queueTimeMs": queue_time_ms,
            "inferenceTimeMs": round((primary_elapsed + retry_elapsed) * 1000),
            "totalTimeMs": total_ms,
            "jsonRetryCount": json_retry_count,
            "tableExtractionDeferred": table_extraction_deferred,
            "selectedPageNos": selected_pages,
            "diagnostics": diagnostics,
        }
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
