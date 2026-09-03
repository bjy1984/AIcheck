"""看一眼 Redis 队列：一键分析的任务还在排队吗、前面还有几个。

## 为什么必须有

2026-09-03 深度审计「一键分析有机率不起作用」：llm.remote 只有一个 worker 槽位，
OCR 大模型抽取、资料分类、节点 AI 复核、一键分析全排这一条队。运行进入
`queued` 后没有任何心跳——lastHeartbeatAt 停在进队那一刻；状态视图和巡检收敛器
都按「30 分钟无活动 = 僵尸」处理，于是**排队超过 30 分钟的运行会被判死**：
界面显示失败、库里落 failed，等 worker 终于取到任务时运行已是终态，模型调用
直接报「terminal run is immutable」。08-27 实测一个运行在队列里等了 38 分钟。

这里直接问 broker：任务 id 还在 llm.remote（含优先级子队列）里，就是活的，
顺便算出前面还有几条消息，界面可以告诉用户「排队中，前面还有 N 个任务」。

Kombu 的 Redis 传输：优先级子队列名是 `{queue}{sep}{priority}`（priority 0 用裸名），
消费时按 priority_steps 从小到大 BRPOP，同一列表 LPUSH 入、RPOP 出——
即数字小的子队列先消费，列表尾部（最早入队）先消费。

Redis 不可用时 fail-open：返回 pending=None，调用方按原来的时间阈值判断。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

DEFAULT_QUEUE = "llm.remote"
_TASK_ID_PATTERN = re.compile(r'"id"\s*:\s*"([^"]+)"')


def _redis_client():
    try:
        import redis  # noqa: PLC0415 - 依赖 celery[redis]，按需加载

        url = (
            os.getenv("AICHECK_REDIS_URL")
            or os.getenv("AICHECK_CELERY_BROKER_URL")
            or "redis://aicheck-redis:6379/0"
        )
        return redis.Redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5)
    except Exception:  # noqa: BLE001 - fail-open
        return None


def _priority_queue_names(queue: str) -> list[str]:
    from apps.worker.celery_app import celery_app  # noqa: PLC0415 - 只为读同一份配置

    options = celery_app.conf.broker_transport_options or {}
    steps = list(options.get("priority_steps") or [0])
    sep = str(options.get("sep") or "\x06\x16")
    return [queue if int(step) == 0 else f"{queue}{sep}{int(step)}" for step in sorted(steps)]


def _message_task_id(raw: Any) -> str:
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")
    try:
        payload = json.loads(text)
        headers = payload.get("headers") if isinstance(payload, dict) else None
        if isinstance(headers, dict) and headers.get("id"):
            return str(headers["id"])
    except (ValueError, TypeError):
        pass
    match = _TASK_ID_PATTERN.search(text)
    return match.group(1) if match else ""


def pending_task_ids(queue: str = DEFAULT_QUEUE, *, client=None) -> list[str] | None:
    """按消费顺序列出队列里等待中的任务 id；Redis 不可用返回 None。"""
    connection = client if client is not None else _redis_client()
    if connection is None:
        return None
    ordered: list[str] = []
    try:
        for name in _priority_queue_names(queue):
            items = connection.lrange(name, 0, -1) or []
            # LPUSH 入队：列表头是最新的，尾部最早，消费从尾部开始
            for raw in reversed(list(items)):
                task_id = _message_task_id(raw)
                if task_id:
                    ordered.append(task_id)
    except Exception:  # noqa: BLE001 - fail-open
        return None
    return ordered


def queue_status_for_task(task_id: str | None, queue: str = DEFAULT_QUEUE, *, client=None) -> dict[str, Any]:
    """{"pending": True/False/None, "ahead": 前面还有几条}——None 表示问不到 broker。"""
    if not task_id:
        return {"pending": None, "ahead": None}
    ids = pending_task_ids(queue, client=client)
    if ids is None:
        return {"pending": None, "ahead": None}
    if task_id not in ids:
        return {"pending": False, "ahead": None}
    return {"pending": True, "ahead": ids.index(task_id)}


def queue_task_is_pending(task_id: str | None, queue: str = DEFAULT_QUEUE) -> bool | None:
    return queue_status_for_task(task_id, queue).get("pending")
