from __future__ import annotations

import os
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.routes import mock_router, router
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.mongo import close_mongo, init_mongo_if_configured
from libs.db.repository import repo
from libs.security.auth import decode_token


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_mongo_if_configured(app)
    yield
    await close_mongo(app)


app = FastAPI(
    title="AIcheck Backend API",
    version="0.1.0",
    description="FastAPI backend for AIcheck with MongoDB-ready repository, OCR/worker integration, and LiteLLM gateway support.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def attach_operation_id(request: Request, call_next):
    request.state.operation_id = request.headers.get("X-Operation-Id") or f"OP-{uuid4().hex[:12].upper()}"
    if auth_required(request):
        claims = decode_token(request.headers.get("Authorization", ""))
        if claims is None:
            return fail(errors.AUTH_REQUIRED, request)
        request.state.auth = claims
    response = await call_next(request)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and repo.mongo is not None:
        await repo.flush_to_mongo()
    return response


def auth_required(request: Request) -> bool:
    if os.getenv("AICHECK_REQUIRE_AUTH", "false").lower() != "true":
        return False
    public_prefixes = (
        "/healthz",
        "/api/healthz",
        "/auth/login",
        "/api/auth/login",
        "/mock/",
        "/api/mock/",
        "/docs",
        "/openapi.json",
    )
    return not request.url.path.startswith(public_prefixes)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return fail(errors.VALIDATION_ERROR, request, data={"errors": exc.errors()})


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        {
            "code": errors.EXTERNAL_TOOL_FAILED.code,
            "message": "服务内部错误，请稍后重试。",
            "data": {"reason": errors.EXTERNAL_TOOL_FAILED.reason},
            "operationId": getattr(request.state, "operation_id", None),
            "serverTime": ok(None, request)["serverTime"],
        },
        status_code=500,
    )


@app.get("/healthz", tags=["system"])
async def healthz(request: Request):
    return ok({"status": "ok", "service": "api-service"}, request)


@app.get("/api/healthz", tags=["system"])
async def api_healthz(request: Request):
    return ok({"status": "ok", "service": "api-service"}, request)


app.include_router(mock_router)
app.include_router(mock_router, prefix="/api")
app.include_router(router)
app.include_router(router, prefix="/api")
