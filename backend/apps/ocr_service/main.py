from __future__ import annotations

from fastapi import FastAPI, Request

from apps.ocr_service.service import ocr_service
from libs.contracts.responses import ok

app = FastAPI(title="AIcheck OCR Service", version="0.1.0")


@app.get("/healthz")
async def healthz(request: Request):
    return ok({"status": "ok", "service": "ocr-service"}, request)


@app.post("/internal/ocr/parse")
async def parse_document(request: Request, payload: dict):
    return ok(
        ocr_service.parse_document(payload["storageKey"], file_name=payload.get("fileName")),
        request,
    )
