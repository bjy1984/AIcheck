from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.integrations.external_registry_queries import (
    query_standard_search,
    query_standard_status,
)
from libs.integrations.std_samr_client import (
    StdSamrConfigurationError,
    StdSamrProtocolError,
    StdSamrRequestError,
    normalize_query,
    normalize_standard_ref,
    parse_review_date,
)

logger = logging.getLogger("aicheck.api.std_samr")
router = APIRouter(tags=["National standards public registry"])


class StdSamrSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    page: int = Field(default=1, ge=1, le=100_000)


class StdSamrVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    standardRef: str
    reviewDate: str | None = None


class StdSamrBriefModel(BaseModel):
    tid: str
    pid: str
    code: str
    name: str
    status: str
    issueDate: str | None = None
    effectiveDate: str | None = None
    detailUrl: str


class StdSamrSearchResultModel(BaseModel):
    status: Literal["COMPLETED"]
    query: str
    queryEndpoint: str
    total: int
    rows: list[StdSamrBriefModel]


class StdSamrSearchResponse(BaseModel):
    code: Literal[0]
    data: StdSamrSearchResultModel
    operationId: str
    serverTime: str


class StdSamrStandardReference(BaseModel):
    standardRef: str
    status: str
    effectiveFrom: str | None = None
    withdrawnOn: str | None = None
    replacedBy: str | None = None


class StdSamrVerifyResultModel(BaseModel):
    status: Literal["COMPLETED"]
    citedRef: str
    canonicalRef: str
    verdict: str
    matched: StdSamrBriefModel | None = None
    currentExecution: StdSamrBriefModel | None = None
    standardReferences: list[StdSamrStandardReference]
    detail: dict[str, Any] | None = None
    queryEndpoint: str
    queriedAt: str


class StdSamrVerifyResponse(BaseModel):
    code: Literal[0]
    data: StdSamrVerifyResultModel
    operationId: str
    serverTime: str








def log_std_samr_failure(request: Request, exc: Exception, *, operation: str) -> None:
    logger.warning(
        operation,
        extra={
            "operation_id": getattr(request.state, "operation_id", None),
            "failure_type": type(exc).__name__,
        },
    )


@router.post(
    "/std-samr/standards/search",
    response_model=StdSamrSearchResponse,
    responses={
        502: {"description": "std.samr.gov.cn upstream failed."},
        503: {"description": "std.samr integration configuration is invalid."},
    },
    summary="检索全国标准信息公共服务平台标准条目",
)
async def search_std_samr_standards(body: StdSamrSearchRequest, request: Request):
    try:
        query = normalize_query(body.query)
    except StdSamrConfigurationError:
        return fail(errors.VALIDATION_ERROR, request, message="请输入有效的检索关键词。")
    try:
        result = await asyncio.to_thread(query_standard_search, query, page=body.page)
    except StdSamrConfigurationError as exc:
        log_std_samr_failure(request, exc, operation="std_samr_search_failed")
        return fail(errors.STD_SAMR_SERVICE_MISCONFIGURED, request, http_status=503)
    except (StdSamrRequestError, StdSamrProtocolError) as exc:
        log_std_samr_failure(request, exc, operation="std_samr_search_failed")
        return fail(errors.STD_SAMR_UPSTREAM_FAILED, request, http_status=502)
    return ok(result, request)


@router.post(
    "/std-samr/standards/verify",
    response_model=StdSamrVerifyResponse,
    responses={
        502: {"description": "std.samr.gov.cn upstream failed."},
        503: {"description": "std.samr integration configuration is invalid."},
    },
    summary="核验标准编号是否为现行有效版本",
)
async def verify_std_samr_standard(body: StdSamrVerifyRequest, request: Request):
    try:
        normalize_standard_ref(body.standardRef)
        review_date = parse_review_date(body.reviewDate)
    except StdSamrConfigurationError as exc:
        message = str(exc) if "reviewDate" in str(exc) else "请输入有效的标准编号。"
        return fail(errors.VALIDATION_ERROR, request, message=message)
    try:
        result = await asyncio.to_thread(query_standard_status, body.standardRef, review_date)
    except StdSamrConfigurationError as exc:
        log_std_samr_failure(request, exc, operation="std_samr_verify_failed")
        return fail(errors.STD_SAMR_SERVICE_MISCONFIGURED, request, http_status=503)
    except (StdSamrRequestError, StdSamrProtocolError) as exc:
        log_std_samr_failure(request, exc, operation="std_samr_verify_failed")
        return fail(errors.STD_SAMR_UPSTREAM_FAILED, request, http_status=502)
    return ok(result, request)
