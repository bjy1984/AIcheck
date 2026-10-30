"""R08：本地时间线没收录的标准，逐个到 std.samr.gov.cn 核版本状态。

时间线只收了 TSG 和少数 GB/T，设计文件引用的标准大多在外面（ECD202 储罐 8：65 条里 58 条「未收录」）。
原来绑在 AC-R08-01 上的 lookup_standard_status 调用时不带标准号，每次都 VALIDATION_ERROR，
在线核验从没真正跑过；GB/T 12771-2008、12777-2008、12459-2017 这些早已废止的版本就一直是「未收录」。

只查带年份的编号：没有年份的引用问的是「现行版」，平台答的也是现行版，核不出被引用的是哪一版。
查询对上游是真实请求，所以有四道限制：开关默认关（生产由 runtime.env 打开）、条数上限、
请求间隔、总时限；连续失败三次就停，剩下的标「未查」，不拖垮整个审查。
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

from libs.integrations.external_registry_queries import query_standard_status
from libs.integrations.std_samr_client import (
    StdSamrConfigurationError,
    StdSamrProtocolError,
    StdSamrRequestError,
    normalize_standard_ref,
)

ENABLE_ENV = "AICHECK_STANDARD_ONLINE_LOOKUP"
MAX_REFERENCES = 60
INTERVAL_SECONDS = 0.5
DEADLINE_SECONDS = 240.0
MAX_CONSECUTIVE_FAILURES = 3
CACHE_TTL_SECONDS = 6 * 3600
SOURCE = "std.samr.gov.cn"
RESOLVED_VERDICTS = {"current", "superseded", "not_yet_effective"}

_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


def online_lookup_enabled() -> bool:
    return os.getenv(ENABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def clear_cache() -> None:
    _CACHE.clear()


def lookup_standard_statuses(
    references: list[str],
    review_date: Any = None,
    *,
    query: Callable[..., dict[str, Any]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """返回 {lookups: 已核到现行/废止/尚未实施的, unresolved: 没核成的及原因, skipped: 没查的及原因}。

    lookups 里每条的 standardRef 原样是传入的写法，调用方按它对回去。
    """
    query = query or query_standard_status
    lookups: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    started = monotonic()
    failures = 0
    stopped: str | None = None
    queried = 0
    review_key = str(review_date or "")[:10]
    for raw in references:
        ref = str(raw or "").strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        try:
            canonical = normalize_standard_ref(ref)
        except StdSamrConfigurationError:
            skipped.append({"standardRef": ref, "reason": "invalid_ref"})
            continue
        if canonical.year is None:
            skipped.append({"standardRef": ref, "reason": "no_year"})
            continue
        if stopped:
            unresolved.append({"standardRef": ref, "reason": stopped})
            continue
        if queried >= MAX_REFERENCES:
            unresolved.append({"standardRef": ref, "reason": "over_limit"})
            continue
        if monotonic() - started > DEADLINE_SECONDS:
            stopped = "deadline_exceeded"
            unresolved.append({"standardRef": ref, "reason": stopped})
            continue
        cache_key = (canonical.display, review_key)
        cached = _CACHE.get(cache_key)
        if cached and monotonic() - cached[0] < CACHE_TTL_SECONDS:
            entry = {**cached[1], "standardRef": ref}
            if entry["verdict"] in RESOLVED_VERDICTS:
                lookups.append(entry)
            else:
                unresolved.append({"standardRef": ref, "reason": str(entry["verdict"])})
            continue
        if queried:
            sleep(INTERVAL_SECONDS)
        queried += 1
        try:
            result = query(ref, review_date or None)
        except StdSamrConfigurationError:
            stopped = "misconfigured"
            unresolved.append({"standardRef": ref, "reason": stopped})
            continue
        except (StdSamrRequestError, StdSamrProtocolError, OSError):
            failures += 1
            unresolved.append({"standardRef": ref, "reason": "upstream_failed"})
            if failures >= MAX_CONSECUTIVE_FAILURES:
                stopped = "not_queried_after_repeated_failures"
            continue
        failures = 0
        entry = _entry(ref, result)
        _CACHE[cache_key] = (monotonic(), entry)
        if entry["verdict"] in RESOLVED_VERDICTS:
            lookups.append(entry)
        else:
            unresolved.append({"standardRef": ref, "reason": str(entry["verdict"] or "no_verdict")})
    return {"lookups": lookups, "unresolved": unresolved, "skipped": skipped}


def _entry(ref: str, result: dict[str, Any]) -> dict[str, Any]:
    platform = next((item for item in result.get("standardReferences") or [] if isinstance(item, dict)), {})
    return {
        "standardRef": ref,
        "verdict": str(result.get("verdict") or ""),
        "status": platform.get("status"),
        "effectiveFrom": platform.get("effectiveFrom"),
        "withdrawnOn": platform.get("withdrawnOn"),
        "replacedBy": platform.get("replacedBy"),
        "platformCode": platform.get("standardRef"),
        "reviewDate": result.get("reviewDate"),
        "source": SOURCE,
    }
