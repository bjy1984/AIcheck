from __future__ import annotations

import asyncio
import logging
import math
import os
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.integrations.cnse_client import (
    DEFAULT_ORIGIN,
    CnseApiClient,
    CnseConfigurationError,
    CnseProtocolError,
    CnseRecognitionError,
    CnseRequestError,
    normalize_keyword,
)


logger = logging.getLogger("aicheck.api.cnse")
router = APIRouter(tags=["CNSE public registry"])


class CnseOrganizationSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str


class CnseOrganizationRow(BaseModel):
    dwid: str
    fzjg: str
    zsyxq: str
    dwmc: str
    dwlb: str
    sjgxsj: str
    zsyxqyz: str


class CnseTargetCenter(BaseModel):
    x: int
    y: int


class CnseMatchBox(CnseTargetCenter):
    width: int
    height: int


class CnseOrganizationSearchResult(BaseModel):
    status: Literal["COMPLETED"]
    algorithm: str
    captureMode: Literal["api"]
    confidence: float
    moveLength: int
    apiYHeight: int
    keyword: str
    queryEndpoint: str
    total: int
    rows: list[CnseOrganizationRow]
    targetCenter: CnseTargetCenter
    matchBox: CnseMatchBox


class CnseOrganizationSearchResponse(BaseModel):
    code: Literal[0]
    data: CnseOrganizationSearchResult
    operationId: str
    serverTime: str


def configured_cnse_origin() -> str:
    return str(os.getenv("AICHECK_CNSE_ORIGIN") or DEFAULT_ORIGIN).strip()


def configured_cnse_min_confidence() -> float:
    raw = str(os.getenv("AICHECK_CNSE_MIN_CONFIDENCE") or "0.50").strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise CnseConfigurationError("minimum confidence is invalid") from exc
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise CnseConfigurationError("minimum confidence is invalid")
    return value


def query_cnse_organizations(keyword: str) -> dict[str, Any]:
    """Execute the complete challenge/recognition/search flow in one session."""

    with CnseApiClient(
        origin=configured_cnse_origin(),
        min_confidence=configured_cnse_min_confidence(),
    ) as client:
        return dict(client.query(keyword).to_dict())


def log_cnse_failure(request: Request, exc: Exception) -> None:
    logger.warning(
        "cnse_organization_search_failed",
        extra={
            "operation_id": getattr(request.state, "operation_id", None),
            "failure_type": type(exc).__name__,
        },
    )


@router.post(
    "/cnse/organizations/search",
    response_model=CnseOrganizationSearchResponse,
    responses={
        502: {"description": "CNSE upstream or CAPTCHA recognition failed."},
        503: {"description": "CNSE integration configuration is invalid."},
    },
    summary="查询全国特种设备公示单位信息",
)
async def search_cnse_organizations(body: CnseOrganizationSearchRequest, request: Request):
    """Query CNSE without exposing its CAPTCHA challenge or session to callers."""

    try:
        keyword = normalize_keyword(body.keyword)
    except CnseConfigurationError:
        return fail(errors.VALIDATION_ERROR, request, message="请输入有效的单位名称。")
    try:
        result = await asyncio.to_thread(query_cnse_organizations, keyword)
    except CnseConfigurationError as exc:
        log_cnse_failure(request, exc)
        return fail(errors.CNSE_SERVICE_MISCONFIGURED, request, http_status=503)
    except CnseRecognitionError as exc:
        log_cnse_failure(request, exc)
        return fail(errors.CNSE_RECOGNITION_FAILED, request, http_status=502)
    except (CnseRequestError, CnseProtocolError) as exc:
        log_cnse_failure(request, exc)
        return fail(errors.CNSE_UPSTREAM_FAILED, request, http_status=502)
    return ok(result, request)
