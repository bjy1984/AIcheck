from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response


app = FastAPI(title="AIcheck isolated validation fault proxy", version="1.0")
_lock = asyncio.Lock()
_fault: dict[str, Any] = {
    "mode": "pass",
    "statusCode": 503,
    "delaySeconds": 0.0,
    "remaining": 0,
}


def _token_valid(request: Request) -> bool:
    expected = str(os.getenv("AICHECK_FAULT_PROXY_TOKEN") or "").strip()
    if not expected:
        return False
    authorization = str(request.headers.get("authorization") or "")
    supplied = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    return supplied == expected


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "upstreamConfigured": bool(str(os.getenv("AICHECK_FAULT_PROXY_UPSTREAM") or "").strip()),
        "fault": dict(_fault),
    }


@app.post("/__fault__/configure")
async def configure_fault(request: Request, payload: dict[str, Any]):
    if not _token_valid(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    mode = str(payload.get("mode") or "pass").strip().lower()
    if mode not in {"pass", "status", "delay"}:
        return JSONResponse({"error": "invalid_mode"}, status_code=400)
    try:
        status_code = max(400, min(int(payload.get("statusCode") or 503), 599))
        delay_seconds = max(0.0, min(float(payload.get("delaySeconds") or 0), 600.0))
        remaining = max(0, min(int(payload.get("remaining") or 0), 1000))
    except (TypeError, ValueError):
        return JSONResponse({"error": "invalid_fault_configuration"}, status_code=400)
    async with _lock:
        _fault.update(
            {
                "mode": mode,
                "statusCode": status_code,
                "delaySeconds": delay_seconds,
                "remaining": remaining,
            }
        )
    return {"ok": True, "fault": dict(_fault)}


async def _consume_fault() -> dict[str, Any]:
    async with _lock:
        current = dict(_fault)
        if int(_fault.get("remaining") or 0) > 0:
            _fault["remaining"] = int(_fault["remaining"]) - 1
            current["active"] = current.get("mode") != "pass"
        else:
            current["active"] = False
        return current


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(request: Request, path: str):
    upstream = str(os.getenv("AICHECK_FAULT_PROXY_UPSTREAM") or "").strip().rstrip("/")
    if not upstream:
        return JSONResponse({"error": "upstream_not_configured"}, status_code=503)
    fault = await _consume_fault()
    if fault.get("active") and fault.get("mode") == "delay":
        await asyncio.sleep(float(fault.get("delaySeconds") or 0))
    if fault.get("active") and fault.get("mode") == "status":
        return JSONResponse(
            {"error": "injected_failure", "statusCode": fault["statusCode"]},
            status_code=int(fault["statusCode"]),
        )
    excluded_headers = {"host", "content-length", "connection"}
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in excluded_headers
    }
    timeout = float(os.getenv("AICHECK_FAULT_PROXY_TIMEOUT_SECONDS", "360"))
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        try:
            response = await client.request(
                request.method,
                f"{upstream}/{path}",
                params=request.query_params,
                headers=headers,
                content=await request.body(),
            )
        except httpx.HTTPError as exc:
            return JSONResponse({"error": "upstream_unavailable", "reason": exc.__class__.__name__}, status_code=502)
    response_headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in {"content-length", "transfer-encoding", "connection", "content-encoding"}
    }
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=response_headers,
        media_type=response.headers.get("content-type"),
    )
