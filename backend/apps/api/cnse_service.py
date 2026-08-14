from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import APIKeyHeader

from apps.api.cnse_routes import router as cnse_router
from libs.contracts.responses import ok
from libs.security.runtime import allowed_hosts

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def configured_api_key() -> str:
    return str(os.getenv("AICHECK_CNSE_API_KEY") or "").strip()


async def require_api_key(api_key: str | None = Security(API_KEY_HEADER)) -> None:
    expected = configured_api_key()
    if len(expected.encode("utf-8")) < 32:
        raise HTTPException(status_code=503, detail="CNSE API key is not configured")
    if not api_key or not hmac.compare_digest(api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing CNSE API key")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if len(configured_api_key().encode("utf-8")) < 32:
        raise RuntimeError("AICHECK_CNSE_API_KEY must contain at least 32 bytes")
    yield


app = FastAPI(
    title="AIcheck CNSE Organization API",
    version="1.0.0",
    description="Dedicated external CNSE lookup service backed by AIcheck captcha-safe integration.",
    lifespan=lifespan,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())


@app.middleware("http")
async def attach_operation_id(request: Request, call_next):
    request.state.operation_id = request.headers.get("X-Operation-Id") or (
        f"OP-{uuid4().hex[:12].upper()}"
    )
    return await call_next(request)


@app.get("/healthz", tags=["system"])
@app.get("/api/healthz", tags=["system"])
async def healthz(request: Request):
    return ok({"status": "ok", "service": "aicheck-cnse-api"}, request)


app.include_router(
    cnse_router,
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)
