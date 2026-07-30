from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import mimetypes
import re
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Request

from libs.contracts import errors
from libs.contracts.errors import BusinessErrorCode
from libs.contracts.responses import fail, ok
from libs.db.repository import flush_state_records, repo
from libs.integrations import task_dispatcher
from libs.integrations.storage import object_storage


router = APIRouter(tags=["MinerU OCR"])

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
_SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
}
_OPTION_NAMES = ("language", "pageRanges", "noCache", "cacheTolerance")


class MinerUApiError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        error: BusinessErrorCode = errors.VALIDATION_ERROR,
    ) -> None:
        super().__init__(message)
        self.error = error


@router.post("/internal/ocr/mineru/tasks")
def create_mineru_task(
    request: Request,
    payload: dict[str, Any],
):
    try:
        source = validate_mineru_task_payload(payload)
        job = create_mineru_job_record(source)
    except MinerUApiError as exc:
        return fail(exc.error, request, message=str(exc))
    dispatch = task_dispatcher.dispatch_mineru_ocr(str(job["id"]))
    if not dispatch.get("taskId") and dispatch.get("mode") != "inline":
        repo.update_ocr_job_record(
            job,
            status="failed",
            stage="dispatch",
            progress=100,
            diagnostics=[
                {
                    "code": "MINERU_DISPATCH_UNAVAILABLE",
                    "level": "error",
                    "retryable": True,
                }
            ],
        )
    else:
        job["dispatchTaskId"] = dispatch.get("taskId")
        job["dispatchMode"] = dispatch.get("mode")
        job["updatedAt"] = job.get("updatedAt")
    flush_state_records({"ocr_jobs": [job]})
    return ok(public_mineru_job(job, dispatch=dispatch), request)


@router.post("/internal/ocr/mineru/tasks/upload")
async def upload_mineru_task(request: Request):
    try:
        metadata = decode_upload_metadata(
            request.headers.get("X-AICheck-Ocr-Metadata-B64")
        )
        body = await limited_request_body(request, limit=MAX_UPLOAD_BYTES)
        storage_key = store_mineru_upload(body, metadata)
        source = validate_mineru_task_payload(
            {**metadata, "storageKey": storage_key}
        )
        job = create_mineru_job_record(source)
    except MinerUApiError as exc:
        return fail(exc.error, request, message=str(exc))
    dispatch = task_dispatcher.dispatch_mineru_ocr(str(job["id"]))
    if not dispatch.get("taskId") and dispatch.get("mode") != "inline":
        repo.update_ocr_job_record(
            job,
            status="failed",
            stage="dispatch",
            progress=100,
            diagnostics=[
                {
                    "code": "MINERU_DISPATCH_UNAVAILABLE",
                    "level": "error",
                    "retryable": True,
                }
            ],
        )
    else:
        job["dispatchTaskId"] = dispatch.get("taskId")
        job["dispatchMode"] = dispatch.get("mode")
    flush_state_records({"ocr_jobs": [job]})
    return ok(public_mineru_job(job, dispatch=dispatch), request)


@router.get("/internal/ocr/mineru/tasks/{job_id}")
def get_mineru_task(request: Request, job_id: str):
    job = repo.find_one("ocr_jobs", job_id)
    if not job or job.get("provider") != "mineru":
        return fail(
            errors.NOT_FOUND,
            request,
            message="MinerU OCR Job 不存在。",
        )
    return ok(public_mineru_job(job), request)


def validate_mineru_task_payload(
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise MinerUApiError("请求体必须是 JSON 对象。")
    url = str(payload.get("url") or "").strip()
    storage_key = str(payload.get("storageKey") or "").strip()
    if bool(url) == bool(storage_key):
        raise MinerUApiError("必须且只能提供 url 或 storageKey。")
    forbidden_model_keys = {
        "model",
        "modelVersion",
        "model_version",
    }
    nested_options = payload.get("options")
    if nested_options is not None and not isinstance(nested_options, dict):
        raise MinerUApiError("options 必须是对象。")
    nested_options = nested_options or {}
    if forbidden_model_keys.intersection(payload) or forbidden_model_keys.intersection(
        nested_options
    ):
        raise MinerUApiError("MinerU 模型固定为 vlm，不能覆盖。")
    file_name = str(payload.get("fileName") or "").strip()
    if not file_name:
        source_path = urlsplit(url or storage_key).path
        file_name = Path(source_path).name
    _validate_file_name(file_name)
    if url:
        validate_public_https_url(url)
    else:
        parsed_storage = urlsplit(storage_key)
        if parsed_storage.scheme not in {"minio", "local"}:
            raise MinerUApiError("storageKey 必须使用 minio:// 或 local://。")
    options: dict[str, Any] = {}
    for key in _OPTION_NAMES:
        value = (
            payload[key]
            if key in payload
            else nested_options.get(key)
        )
        if value is not None:
            options[key] = value
    _validate_options(options)
    document_id = str(payload.get("documentId") or "").strip()
    version_id = str(
        payload.get("documentVersionId")
        or payload.get("versionId")
        or ""
    ).strip()
    if bool(document_id) != bool(version_id):
        raise MinerUApiError(
            "documentId 与 documentVersionId 必须同时提供。"
        )
    if document_id:
        document = repo.find_one("documents", document_id)
        version = repo.find_one("versions", version_id)
        if (
            not document
            or not version
            or str(version.get("documentId") or "") != document_id
        ):
            raise MinerUApiError("文档绑定不存在。")
    return {
        "url": url or None,
        "storageKey": storage_key or url,
        "fileName": file_name,
        "profileId": str(payload.get("profileId") or "").strip() or None,
        "documentType": (
            str(payload.get("documentType") or "").strip() or None
        ),
        "documentId": document_id,
        "documentVersionId": version_id,
        "options": options,
    }


def create_mineru_job_record(source: dict[str, Any]) -> dict[str, Any]:
    return repo.create_ocr_job_record(
        document_id=str(source.get("documentId") or ""),
        version_id=str(source.get("documentVersionId") or ""),
        storage_key=str(source.get("storageKey") or ""),
        file_name=str(source.get("fileName") or ""),
        profile_id=source.get("profileId"),
        document_type=source.get("documentType"),
        provider="mineru",
        source_url=source.get("url"),
        options=source.get("options") or {},
    )


def public_mineru_job(
    job: dict[str, Any],
    *,
    dispatch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_dispatch = None
    if dispatch is not None:
        safe_dispatch = {
            key: dispatch.get(key)
            for key in (
                "mode",
                "taskId",
                "queue",
                "priority",
                "statusReason",
            )
            if dispatch.get(key) is not None
        }
    result = {
        "jobId": job.get("id"),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "progress": int(job.get("progress") or 0),
        "provider": "mineru",
        "model": "vlm",
        "sourceType": job.get("sourceType"),
        "fileName": job.get("fileName"),
        "profileId": job.get("profileId"),
        "documentType": job.get("documentType"),
        "documentId": job.get("documentId") or None,
        "documentVersionId": job.get("documentVersionId") or None,
        "providerTaskId": job.get("providerTaskId"),
        "providerTaskType": job.get("providerTaskType"),
        "parseResultId": job.get("parseResultId"),
        "resultSummary": job.get("resultSummary") or {},
        "artifactReferences": job.get("artifactReferences") or {},
        "diagnostics": job.get("diagnostics") or [],
        "createdAt": job.get("createdAt"),
        "updatedAt": job.get("updatedAt"),
        "finishedAt": job.get("finishedAt"),
        "pollUrl": f"/internal/ocr/mineru/tasks/{job.get('id')}",
    }
    if safe_dispatch is not None:
        result["dispatch"] = safe_dispatch
    return result


def decode_upload_metadata(value: str | None) -> dict[str, Any]:
    if not value or len(value) > 24 * 1024:
        raise MinerUApiError("上传元数据缺失或过大。")
    try:
        raw = base64.b64decode(value, validate=True)
        metadata = json.loads(raw.decode("utf-8"))
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        raise MinerUApiError("上传元数据格式无效。") from exc
    if not isinstance(metadata, dict):
        raise MinerUApiError("上传元数据必须是 JSON 对象。")
    if any(key in metadata for key in ("url", "storageKey")):
        raise MinerUApiError("上传元数据不能自行指定来源。")
    return metadata


async def limited_request_body(
    request: Request,
    *,
    limit: int,
) -> bytes:
    content_length = request.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > limit:
                raise MinerUApiError(
                    "上传文件超过 200MB 限制。",
                    error=errors.FILE_TOO_LARGE,
                )
        except ValueError as exc:
            raise MinerUApiError("Content-Length 无效。") from exc
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise MinerUApiError(
                "上传文件超过 200MB 限制。",
                error=errors.FILE_TOO_LARGE,
            )
        chunks.append(chunk)
    if total == 0:
        raise MinerUApiError("上传文件不能为空。")
    return b"".join(chunks)


def store_mineru_upload(
    body: bytes,
    metadata: dict[str, Any],
) -> str:
    file_name = str(metadata.get("fileName") or "").strip()
    _validate_file_name(file_name)
    content_type = (
        mimetypes.guess_type(file_name)[0]
        or "application/octet-stream"
    )
    object_name = (
        f"pipelines/mineru/uploads/{uuid4().hex}/{file_name}"
    )
    try:
        storage_key = object_storage.put_bytes(
            "ocr-artifacts",
            object_name,
            body,
            content_type=content_type,
        )
    except Exception as exc:
        raise MinerUApiError(
            "MinerU 上传暂不可用。",
            error=errors.OBJECT_STORAGE_REQUIRED,
        ) from exc
    if not storage_key:
        raise MinerUApiError(
            "MinerU 上传暂不可用。",
            error=errors.OBJECT_STORAGE_REQUIRED,
        )
    return storage_key


def validate_public_https_url(value: str) -> None:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise MinerUApiError("url 格式无效。") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise MinerUApiError(
            "url 必须是无查询参数的公网 HTTPS 地址。"
        )
    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise MinerUApiError("url 域名无法解析。") from exc
    resolved = {
        str(address[4][0])
        for address in addresses
        if address and len(address) >= 5 and address[4]
    }
    if not resolved:
        raise MinerUApiError("url 域名无法解析。")
    for address in resolved:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise MinerUApiError("url 域名解析结果无效。") from exc
        if not ip.is_global:
            raise MinerUApiError("url 必须解析到公网地址。")


def _validate_file_name(file_name: str) -> None:
    if (
        not file_name
        or len(file_name) > 255
        or Path(file_name).name != file_name
        or "/" in file_name
        or "\\" in file_name
    ):
        raise MinerUApiError("fileName 格式无效。")
    if Path(file_name).suffix.lower() not in _SUPPORTED_EXTENSIONS:
        raise MinerUApiError(
            "MinerU 不支持该文件类型。",
            error=errors.UNSUPPORTED_FILE_TYPE,
        )


def _validate_options(options: dict[str, Any]) -> None:
    language = options.get("language")
    if language is not None and (
        not isinstance(language, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", language)
    ):
        raise MinerUApiError("language 格式无效。")
    page_ranges = options.get("pageRanges")
    if page_ranges is not None:
        if not isinstance(page_ranges, str) or not page_ranges.strip():
            raise MinerUApiError("pageRanges 格式无效。")
        selected_pages: set[int] = set()
        for token in page_ranges.split(","):
            token = token.strip()
            match = re.fullmatch(r"([1-9]\d*)(?:-([1-9]\d*))?", token)
            if not match:
                raise MinerUApiError("pageRanges 格式无效。")
            start = int(match.group(1))
            end = int(match.group(2) or start)
            if end < start or end > 100_000:
                raise MinerUApiError("pageRanges 格式无效。")
            selected_pages.update(range(start, end + 1))
            if len(selected_pages) > 200:
                raise MinerUApiError("pageRanges 最多选择 200 页。")
    no_cache = options.get("noCache")
    if no_cache is not None and not isinstance(no_cache, bool):
        raise MinerUApiError("noCache 必须是布尔值。")
    tolerance = options.get("cacheTolerance")
    if tolerance is not None and (
        isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
        or float(tolerance) < 0
    ):
        raise MinerUApiError("cacheTolerance 必须是非负数。")
