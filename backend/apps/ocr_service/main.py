from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from base64 import urlsafe_b64decode
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import FileResponse

from apps.ocr_service.result_cache import prune_ocr_cache
from apps.ocr_service.service import AGENTDESIGN_BACKEND, ocr_service
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.ocr.welder_certificate_tool import extract_welder_certificate_from_payload


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(ocr_service.jobs.recover_interrupted_jobs)
    await asyncio.to_thread(prune_ocr_cache)
    if os.getenv("AICHECK_OCR_DEEP_READY_PROBE", "false").lower() in {"1", "true", "yes", "on"}:
        await asyncio.to_thread(ocr_service.run_readiness_probe)
    maintenance_task = asyncio.create_task(cache_maintenance_loop())
    try:
        yield
    finally:
        maintenance_task.cancel()


async def cache_maintenance_loop() -> None:
    while True:
        await asyncio.sleep(6 * 3600)
        await asyncio.to_thread(prune_ocr_cache)


app = FastAPI(title="AIcheck Document Intelligence Service", version="1.0.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz(request: Request):
    payload = ocr_service.health_payload()
    payload["service"] = payload.get("service", "ocr-service")
    payload["pipelineAvailable"] = payload.get("pipelineAvailable")
    payload["pipelineBackend"] = str(AGENTDESIGN_BACKEND)
    payload["placeholderAllowed"] = payload.get("placeholderAllowed")
    return ok(payload, request)


@app.get("/readyz")
async def readyz(request: Request):
    payload = ocr_service.readiness_payload()
    if payload["ready"]:
        return ok(payload, request)
    return fail(errors.EXTERNAL_TOOL_FAILED, request, message="本地 OCR 模型或引擎未就绪。", data=payload, http_status=503)


@app.get("/internal/ocr/doctor")
async def runtime_doctor(request: Request):
    return ok(ocr_service.runtime_doctor_payload(), request)


@app.post("/internal/ocr/parse")
async def parse_document(request: Request, payload: dict):
    storage_key = str(payload.get("storageKey") or "").strip()
    if not storage_key:
        return fail(errors.VALIDATION_ERROR, request, message="storageKey 不能为空。")
    return ok(
        ocr_service.parse_document(
            storage_key,
            file_name=payload.get("fileName"),
            profile_id=payload.get("profileId"),
            document_type=payload.get("documentType"),
            document_version_id=payload.get("documentVersionId"),
            business_pack_id=payload.get("businessPackId"),
            options=payload.get("options") if isinstance(payload.get("options"), dict) else None,
        ),
        request,
    )


@app.post("/internal/ocr/parse-upload")
async def parse_uploaded_document(request: Request):
    metadata = "{}"
    encoded_metadata = request.headers.get("X-AICheck-Ocr-Metadata-B64")
    if encoded_metadata:
        try:
            metadata = urlsafe_b64decode(encoded_metadata.encode("ascii")).decode("utf-8")
        except Exception:
            return fail(errors.VALIDATION_ERROR, request, message="X-AICheck-Ocr-Metadata-B64 无效。")
    try:
        payload = json.loads(metadata or "{}")
    except json.JSONDecodeError:
        return fail(errors.VALIDATION_ERROR, request, message="metadata 必须是 JSON。")
    body = await request.body()
    if not body:
        return fail(errors.VALIDATION_ERROR, request, message="上传文件内容不能为空。")
    file_name = str(payload.get("fileName") or "document").strip() or "document"
    suffix = Path(file_name).suffix
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="aicheck-ocr-upload-", suffix=suffix, delete=False) as tmp:
            tmp.write(body)
            tmp_path = tmp.name
        return ok(
            ocr_service.parse_document(
                tmp_path,
                file_name=file_name,
                profile_id=payload.get("profileId"),
                document_type=payload.get("documentType"),
                document_version_id=payload.get("documentVersionId"),
                business_pack_id=payload.get("businessPackId"),
                options=payload.get("options") if isinstance(payload.get("options"), dict) else None,
            ),
            request,
        )
    finally:
        try:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


@app.post("/internal/ocr/page-preview")
async def page_preview(request: Request, payload: dict):
    storage_key = str(payload.get("storageKey") or "").strip()
    if not storage_key:
        return fail(errors.VALIDATION_ERROR, request, message="storageKey 不能为空。")
    try:
        page_no = int(payload.get("pageNo") or 1)
    except (TypeError, ValueError):
        page_no = 1
    page = ocr_service.render_page_preview(
        storage_key,
        file_name=payload.get("fileName"),
        profile_id=payload.get("profileId"),
        document_type=payload.get("documentType"),
        options=payload.get("options") if isinstance(payload.get("options"), dict) else None,
        page_no=page_no,
    )
    page_path = Path(str((page or {}).get("path") or ""))
    if not page or not page_path.is_file():
        return fail(errors.NOT_FOUND, request, message="OCR 页图预览不存在。")
    return FileResponse(
        str(page_path),
        media_type="image/png",
        filename=f"ocr-page-{int(page.get('pageNo') or 1)}.png",
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, max-age=300",
            "X-AICheck-Page-No": str(page.get("pageNo") or 1),
            "X-AICheck-Page-Width": str(page.get("width") or ""),
            "X-AICheck-Page-Height": str(page.get("height") or ""),
        },
    )


@app.post("/internal/ocr/seal-read")
async def read_seal_crop(request: Request):
    """读一张**已裁好的**印章图，返回章上的文字。

    为什么单开一条：整份文档那条路要先有「印章用途」的候选切图才会把活派给
    印章引擎，直接丢一张裁图进去会一路 skipped，理由是 no_routed_variant——
    看起来像引擎坏了，其实是没派活。MinerU 已经把印章裁好了，这里直接调管线。

    模型只在这个容器里，图片不出本机。
    """
    from libs.seal_local_reader import read_seal_image

    body = await request.body()
    if not body:
        return fail(errors.VALIDATION_ERROR, request, message="印章图片内容不能为空。")
    suffix = str(request.headers.get("X-AICheck-Seal-Suffix") or ".jpg")
    try:
        return ok(read_seal_image(body, suffix=suffix if suffix.startswith(".") else ".jpg"), request)
    except Exception as exc:  # 读不出只是印章少个属性，不该把整条链路带崩
        logging.getLogger(__name__).exception("印章读字失败")
        return fail(
            errors.EXTERNAL_TOOL_FAILED,
            request,
            message=f"印章识别失败：{type(exc).__name__}",
        )


@app.post("/internal/tools/ocr/welder-certificate/extract")
async def extract_welder_certificate(request: Request, payload: dict):
    storage_key = str(payload.get("storageKey") or "").strip()
    if storage_key:
        parse_result = ocr_service.parse_document(
            storage_key,
            file_name=payload.get("fileName"),
            profile_id=payload.get("profileId") or "welder_certificate_v1",
            document_type=payload.get("documentType") or "welder_certificate",
            document_version_id=payload.get("documentVersionId"),
            business_pack_id=payload.get("businessPackId"),
            options=payload.get("options") if isinstance(payload.get("options"), dict) else None,
        )
        return ok(extract_welder_certificate_from_payload({"ocrResult": parse_result}), request)
    if not any(key in payload for key in ["ocrResult", "parseResult", "text", "fragments"]):
        return fail(
            errors.VALIDATION_ERROR,
            request,
            message="请提供 storageKey、ocrResult、parseResult 或 text。",
        )
    return ok(extract_welder_certificate_from_payload(payload), request)


@app.post("/internal/document-parse/jobs")
async def create_document_parse_job(request: Request, payload: dict, background_tasks: BackgroundTasks):
    storage_key = str(payload.get("storageKey") or "").strip()
    if not storage_key:
        return fail(errors.VALIDATION_ERROR, request, message="storageKey 不能为空。")
    job = ocr_service.create_job(payload)
    if not job.get("reused"):
        background_tasks.add_task(ocr_service.run_job, job["jobId"])
    return ok(job, request)


@app.get("/internal/document-parse/jobs/{job_id}")
async def get_document_parse_job(request: Request, job_id: str):
    job = ocr_service.jobs.get_job(job_id)
    if not job:
        return fail(errors.NOT_FOUND, request, message="OCR Job 不存在。")
    return ok(job, request)


@app.post("/internal/document-parse/jobs/{job_id}/cancel")
async def cancel_document_parse_job(request: Request, job_id: str):
    job = ocr_service.jobs.cancel(job_id)
    if not job:
        return fail(errors.NOT_FOUND, request, message="OCR Job 不存在。")
    return ok(job, request)


@app.post("/internal/document-parse/jobs/{job_id}/retry")
async def retry_document_parse_job(request: Request, job_id: str, background_tasks: BackgroundTasks):
    job = ocr_service.retry_job(job_id)
    if not job:
        return fail(errors.NOT_FOUND, request, message="OCR Job 不存在。")
    background_tasks.add_task(ocr_service.run_job, job["jobId"])
    return ok(job, request)


@app.get("/internal/document-parse/results/{parse_result_id}")
async def get_document_parse_result(request: Request, parse_result_id: str):
    result = ocr_service.jobs.get_result(parse_result_id)
    if not result:
        return fail(errors.NOT_FOUND, request, message="OCR 解析结果不存在。")
    return ok(result, request)
