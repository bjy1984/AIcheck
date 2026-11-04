"""按需剖析单个请求：平台管理员加 `?_profile=1` 才开，结果只写服务器日志（2026-11-04）。

生产总览服务器端要 1.2 秒，本机演示数据只要 0.03 秒——慢在生产数据形态上。另起进程加载
整库去剖析会顶爆内存（生产 API 被 OOM 杀过），所以在正在跑的 API 进程里剖这一次请求。
普通请求不受影响：没带参数、或不是平台管理员，就是空的上下文。
"""

from __future__ import annotations

import cProfile
import io
import logging
import pstats
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger("aicheck.request_profile")


def _enabled(request: Any) -> bool:
    from libs.security.auth import is_platform_admin

    try:
        return request.query_params.get("_profile") == "1" and is_platform_admin(
            getattr(request.state, "auth_user", None)
        )
    except Exception:  # noqa: BLE001 -- profiling is diagnostics only; never break the request
        return False


@contextmanager
def request_profile(request: Any, label: str, *, top: int = 25) -> Iterator[None]:
    if not _enabled(request):
        yield
        return
    profiler = cProfile.Profile()
    profiler.enable()
    try:
        yield
    finally:
        profiler.disable()
        out = io.StringIO()
        stats = pstats.Stats(profiler, stream=out)
        stats.sort_stats("cumulative").print_stats(r"(apps|libs)/", top)
        out.write("\n-- by own time --\n")
        stats.sort_stats("tottime").print_stats(r"(apps|libs)/", top)
        logger.warning("request_profile %s\n%s", label, out.getvalue())
