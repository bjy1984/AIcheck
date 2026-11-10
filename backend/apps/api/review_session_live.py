"""审查会话 live read 的节流与运行事件投影缓存（2026-11-10，「停止回答」转圈太久）。

生产实测（测试项目3 节点 1，RSESSION-5BF4010E5A，11-10 00:43）：问一句话从发出到
回答落定 1 分 44 秒，其中模型本身只占约 47 秒；同时期每个消息/事件轮询要 5–10 秒。
原因是助手面板自己的轮询把 API 进程压满了，而 Agent 就跑在同一个进程的后台线程里：

- 每次会话刷新都把同节点所有运行（31 条、17 MB）和它们的运行事件（630 条、13 MB）
  从 Postgres 整份重读、解析、深拷贝。SSE 每 0.5 秒刷一次，聊天期间运行根本不动。
- 事件快照每次都对 630 条运行事件的 details 做一遍 json.dumps（量大小）和 sha256，
  而且 SSE 是在事件循环线程里做的，挡住了所有请求的收发。

这里只做两件事：会话自己的行照旧 0.4 秒节流；运行与运行事件单独节流到 3 秒。
运行事件只追加不改（_shared.append_review_event 写入后没有任何地方再改它），
所以按事件 id 缓存「折叠后的 payload + 原文哈希」是安全的。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

#: 运行与运行事件多久重读一次。正式复核每个节点要跑 5–13 分钟，3 秒的进度粒度足够；
#: 前端兜底轮询也是 3 秒一轮。
RUN_REFRESH_INTERVAL_SECONDS = 3.0

#: 缓存上限。超过就整体清空重建——比维护 LRU 简单，清空的代价只是重算一轮。
_PROJECTION_CACHE_LIMIT = 10000

_LOCK = threading.Lock()
_LAST_SESSION_REFRESH: dict[str, float] = {}
_LAST_RUN_REFRESH: dict[str, float] = {}
_PROJECTION_CACHE: dict[str, tuple[dict[str, Any], str]] = {}


def plan_refresh(
    key: str,
    now: float,
    *,
    min_interval_seconds: float,
    include_runs: bool,
    run_interval_seconds: float = RUN_REFRESH_INTERVAL_SECONDS,
) -> tuple[bool, bool]:
    """(要不要刷新会话的行, 要不要连运行一起刷新)。决定刷新时同时记下时间。"""
    with _LOCK:
        if now - _LAST_SESSION_REFRESH.get(key, float("-inf")) < min_interval_seconds:
            return False, False
        _LAST_SESSION_REFRESH[key] = now
        refresh_runs = (
            include_runs and now - _LAST_RUN_REFRESH.get(key, float("-inf")) >= run_interval_seconds
        )
        if refresh_runs:
            _LAST_RUN_REFRESH[key] = now
        return True, refresh_runs


def run_event_projection(
    item: dict[str, Any],
    compute: Callable[[dict[str, Any]], tuple[dict[str, Any], str]],
) -> tuple[dict[str, Any], str]:
    """运行事件的 (折叠后的 payload, 原文哈希)，按事件 id 缓存。没有 id 的不缓存。

    compute 要交回一份独立副本（别引用 state 里的 dict）；返回的是缓存里的同一份，
    调用方要自己复制再交出去。
    """
    event_id = str(item.get("id") or "")
    if not event_id:
        return compute(item)
    cached = _PROJECTION_CACHE.get(event_id)
    if cached is not None:
        return cached
    projected = compute(item)
    with _LOCK:
        if len(_PROJECTION_CACHE) >= _PROJECTION_CACHE_LIMIT:
            _PROJECTION_CACHE.clear()
        _PROJECTION_CACHE[event_id] = projected
    return projected


def reset_for_tests() -> None:
    with _LOCK:
        _LAST_SESSION_REFRESH.clear()
        _LAST_RUN_REFRESH.clear()
        _PROJECTION_CACHE.clear()
