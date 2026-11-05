"""监检的节点审计任务队列（只读）：GET /projects/{project_id}/inspection/node-audit-tasks。

口径和取数见 libs.node_audit_tasks。前端顶栏「审计任务」按钮轮询这个接口：
有任务在排或在跑时每 15 秒一次，其余时候 60 秒一次——所以这里只读原始记录、
不调 review_run_view（它每个运行还要算图摘要和条款快照，69 个节点太重）。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request

from apps.api import routes as api
from libs.contracts import errors
from libs.contracts.responses import fail, ok, server_time
from libs.db.repository import repo
from libs.node_audit_tasks import build_node_audit_tasks
from libs.review_orchestrator.execution import review_run_looks_abandoned, review_run_queue_status

router = APIRouter()


@router.get("/projects/{project_id}/inspection/node-audit-tasks")
def list_node_audit_tasks(request: Request, project_id: str):
    role_error = api._inspection_audit_role_error(request)
    if role_error:
        return role_error
    project = repo.require_project(project_id)
    if not project:
        return fail(errors.NOT_FOUND, request)
    scope = api.authorized_node_scope(request, project_id)
    if scope == set():
        return fail(errors.FORBIDDEN, request)
    tenant_id = api.tenant_id_for_record(project)

    def visible(item: dict) -> bool:
        return (
            item.get("projectId") == project_id
            and api.tenant_id_for_record(item) == tenant_id
            and (scope is None or int(item.get("nodeId") or 0) in scope)
        )

    now_text = server_time()
    try:
        now = datetime.strptime(str(now_text)[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")  # noqa: DTZ007 -- 服务器本地时间口径
    except ValueError:
        now = datetime.now()  # noqa: DTZ005 -- 同上
    payload = build_node_audit_tasks(
        ai_runs=[item for item in repo.state.get("ai_runs", []) if visible(item)],
        review_runs=[item for item in repo.state.get("review_runs", []) if visible(item)],
        opinions=[
            item
            for item in repo.state.get("review_opinions", [])
            if item.get("projectId") == project_id
            and (scope is None or int(item.get("nodeId") or 0) in scope)
        ],
        nodes=[
            node
            for node in repo.state.get("tree_nodes", [])
            if node.get("projectId") == project_id
            and (scope is None or int(node.get("nodeId") or 0) in scope)
        ],
        now=now,
        looks_abandoned=review_run_looks_abandoned,
        queue_status=review_run_queue_status,
    )
    return ok({**payload, "projectId": project_id, "dataAsOf": now_text}, request)
