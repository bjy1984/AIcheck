from __future__ import annotations

import os

from fastapi import FastAPI, Request

from apps.ocr_service.service import AGENTDESIGN_BACKEND, ocr_service
from libs.contracts import errors
from libs.contracts.responses import fail, ok

app = FastAPI(title="AIcheck OCR Service", version="0.1.0")


@app.get("/healthz")
async def healthz(request: Request):
    return ok(
        {
            "status": "ok",
            "service": "ocr-service",
            "pipelineAvailable": ocr_service.pipeline is not None,
            "pipelineBackend": str(AGENTDESIGN_BACKEND),
            "placeholderAllowed": os.getenv("AICHECK_OCR_ALLOW_PLACEHOLDER", "true").lower() == "true",
        },
        request,
    )


@app.post("/internal/ocr/parse")
async def parse_document(request: Request, payload: dict):
    storage_key = str(payload.get("storageKey") or "").strip()
    if not storage_key:
        return fail(errors.VALIDATION_ERROR, request, message="storageKey 不能为空。")
    return ok(
        ocr_service.parse_document(storage_key, file_name=payload.get("fileName")),
        request,
    )
