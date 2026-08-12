"""外部登记系统的查询入口：全国特种设备公示（CNSE）与国家标准信息公共服务平台。

这几个函数原先住在 apps/api/cnse_routes.py 与 apps/api/std_samr_routes.py 里，
但它们不是 HTTP handler——没有路由装饰器，不碰 Request/Response，只是把
libs/integrations 里的客户端包一层。放在路由文件里的后果是：
libs/review_orchestrator/runtime_tools.py 为了调用它们，必须在**模块级**
`from apps.api.cnse_routes import ...`，业务规则工具装载即绑定到 API 层。

客户端本来就在 libs/integrations 下，查询入口理应在它们旁边。路由文件改为
从这里导入，对外 HTTP 契约不变。
"""

from __future__ import annotations

import math
import os
from datetime import date
from typing import Any

from libs.integrations.cnse_client import (
    DEFAULT_ORIGIN as CNSE_DEFAULT_ORIGIN,
)
from libs.integrations.cnse_client import (
    CnseApiClient,
    CnseConfigurationError,
)
from libs.integrations.std_samr_client import (
    DEFAULT_ORIGIN as STD_SAMR_DEFAULT_ORIGIN,
)
from libs.integrations.std_samr_client import (
    StdSamrClient,
    parse_review_date,
)


def configured_cnse_origin() -> str:
    return str(os.getenv("AICHECK_CNSE_ORIGIN") or CNSE_DEFAULT_ORIGIN).strip()


def configured_cnse_min_confidence() -> float:
    raw = str(os.getenv("AICHECK_CNSE_MIN_CONFIDENCE") or "0.50").strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise CnseConfigurationError("minimum confidence is invalid") from exc
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise CnseConfigurationError("minimum confidence must be within [0, 1]")
    return value


def configured_std_samr_origin() -> str:
    return str(os.getenv("AICHECK_STD_SAMR_ORIGIN") or STD_SAMR_DEFAULT_ORIGIN).strip()


def query_cnse_organizations(keyword: str) -> dict[str, Any]:
    """Execute the complete challenge/recognition/search flow in one session."""

    with CnseApiClient(
        origin=configured_cnse_origin(),
        min_confidence=configured_cnse_min_confidence(),
    ) as client:
        return dict(client.query(keyword).to_dict())


def query_cnse_persons(id_number: str) -> dict[str, Any]:
    """Execute the person challenge/check/search flow in one session."""

    with CnseApiClient(
        origin=configured_cnse_origin(),
        min_confidence=configured_cnse_min_confidence(),
    ) as client:
        return dict(client.query_person(id_number).to_dict())


def query_standard_search(query: str, *, page: int = 1) -> dict[str, Any]:
    """Execute a std.samr.gov.cn search and return the public contract."""

    with StdSamrClient(origin=configured_std_samr_origin()) as client:
        return dict(client.search(query, page=page).to_dict(origin=client.origin))


def query_standard_status(standard_ref: str, review_date: date | str | None = None) -> dict[str, Any]:
    """Verify a cited standard against std.samr.gov.cn."""

    as_of = parse_review_date(review_date)
    with StdSamrClient(origin=configured_std_samr_origin()) as client:
        return dict(client.verify(standard_ref, review_date=as_of).to_dict(origin=client.origin))
