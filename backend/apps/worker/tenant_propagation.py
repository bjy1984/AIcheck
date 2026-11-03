"""后台任务带上院（租户）：入队时把当前院写进消息头，worker 执行前切到那个院。

2026-11-02 多特检院第一阶段。存储按院分区（repo.state 取当前请求的院），API 请求天然隔离；
但多数 Celery 任务（OCR 解析、AI 复核、项目分析……）不带院，worker 里一律落到默认院——
第二个院的任务要么找不到自己的数据，要么项目号撞上时写进默认院。

逐个任务加 tenant_id 参数容易漏，新任务也会再漏，所以在 Celery 的发布/执行钩子里统一做：
- before_task_publish：消息头没有院就补上发布方当前的院（API 请求里就是登录人的院）；
- task_prerun / task_postrun：worker 里按消息头切换、执行完复原。
已经自带 tenant_id 参数的任务（文档分类等）照旧，在任务里再设一次同一个值，不冲突。
"""

from __future__ import annotations

from typing import Any

from celery.signals import before_task_publish, task_postrun, task_prerun

from libs.security.tenant import (
    current_tenant_id,
    reset_request_tenant_id,
    set_request_tenant_id,
    valid_tenant_id,
)

TENANT_HEADER = "aicheck_tenant_id"
_TOKEN_ATTR = "_aicheck_tenant_token"


@before_task_publish.connect(weak=False)
def stamp_tenant_header(headers: dict[str, Any] | None = None, **_: Any) -> None:
    if headers is not None and not valid_tenant_id(headers.get(TENANT_HEADER)):
        headers[TENANT_HEADER] = current_tenant_id()


@task_prerun.connect(weak=False)
def enter_task_tenant(task: Any = None, **_: Any) -> None:
    request = getattr(task, "request", None)
    tenant_id = valid_tenant_id(getattr(request, TENANT_HEADER, None)) if request is not None else None
    if tenant_id:
        setattr(request, _TOKEN_ATTR, set_request_tenant_id(tenant_id))


@task_postrun.connect(weak=False)
def leave_task_tenant(task: Any = None, **_: Any) -> None:
    request = getattr(task, "request", None)
    token = getattr(request, _TOKEN_ATTR, None) if request is not None else None
    if token is not None:
        reset_request_tenant_id(token)
        setattr(request, _TOKEN_ATTR, None)
