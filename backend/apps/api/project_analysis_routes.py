from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Body, Header, Request

from apps.api.routes import (
    effective_role_for_request,
    idempotent,
    mutation_guard,
    request_tenant_id,
    request_user_id,
)
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.repository import flush_state, repo
from libs.db.seed import MODEL_ROUTE_VERSIONS
from libs.integrations import task_dispatcher
from libs.project_analysis.domain import (
    advance_project_analysis_phase,
    create_project_analysis_run,
    project_analysis_run_view,
    project_analysis_status_view,
    reap_stalled_project_analysis_runs,
)
from libs.project_analysis.execution import project_analysis_model_timeout_seconds
from libs.project_analysis.prompt import project_analysis_preview
from libs.project_analysis.queue_probe import queue_status_for_task, queue_task_is_pending

project_analysis_router = APIRouter()
LOGGER = logging.getLogger(__name__)


def _authorize(request: Request, project_id: str, *, write: bool) -> Any | None:
    role, identity_error = effective_role_for_request(request)
    if identity_error:
        return identity_error
    if not repo.require_project(project_id):
        return fail(errors.NOT_FOUND, request)
    if role not in {"inspection", "admin"}:
        return fail(errors.FORBIDDEN, request, message="仅监检人员或管理员可执行一键分析。")
    return mutation_guard(request, project_id, if_match="*") if write else None


def _model_route() -> dict[str, Any] | None:
    active = next(
        (
            row
            for row in repo.state.get("model_route_versions") or []
            if row.get("modelAlias") == "project-review-large" and row.get("status") == "production"
        ),
        None,
    )
    if active:
        return active
    return next(
        (
            repo.clone(row)
            for row in MODEL_ROUTE_VERSIONS
            if row.get("modelAlias") == "project-review-large" and row.get("status") == "production"
        ),
        None,
    )


def _preview(project_id: str) -> dict[str, Any]:
    route = _model_route()
    if not route:
        raise ValueError("PROJECT_ANALYSIS_MODEL_ROUTE_UNAVAILABLE")
    return project_analysis_preview(repo.state, project_id, model_route=route)


def _public_preview(preview: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in preview.items() if key not in {"request", "snapshot"}}


@project_analysis_router.get("/projects/{project_id}/inspection/full-project-analysis/preview")
def get_project_analysis_preview(request: Request, project_id: str):
    if error := _authorize(request, project_id, write=False):
        return error
    try:
        preview = _preview(project_id)
    except ValueError as exc:
        return fail(errors.CONFLICT, request, message=str(exc))
    return ok({"preview": _public_preview(preview)}, request)


@project_analysis_router.post("/projects/{project_id}/inspection/full-project-analysis/runs")
def create_project_analysis(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if error := _authorize(request, project_id, write=True):
        return error

    reaped = reap_stalled_project_analysis_runs(
        repo.state,
        project_id=project_id,
        model_running_timeout=timedelta(
            seconds=project_analysis_model_timeout_seconds() + 300
        ),
        queue_alive=queue_task_is_pending,
    )
    if reaped:
        flush_state({"project_analysis_runs", "project_analysis_events"})

    def produce():
        try:
            preview = _preview(project_id)
        except ValueError as exc:
            return fail(errors.CONFLICT, request, message=str(exc))
        if str(body.get("snapshotHash") or "") != str(preview["snapshotHash"]):
            return fail(
                errors.ETAG_CONFLICT,
                request,
                data={"currentSnapshotHash": preview["snapshotHash"]},
            )
        if int(preview.get("includedNodeCount") or 0) == 0:
            return fail(
                errors.VALIDATION_ERROR,
                request,
                message="PROJECT_ANALYSIS_EMPTY_SCOPE",
            )
        if preview["contextLimitExceeded"]:
            return fail(
                errors.VALIDATION_ERROR,
                request,
                message="PROJECT_ANALYSIS_CONTEXT_LIMIT_EXCEEDED",
                data=_public_preview(preview),
            )
        frozen_request = repo.clone(preview["request"])
        request_hash = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    frozen_request,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
        snapshot = {
            **preview["snapshot"],
            "tenantId": request_tenant_id(request),
            "request": frozen_request,
            "requestHash": request_hash,
        }
        snapshots = repo.state.setdefault("project_analysis_snapshots", [])
        existing_snapshot = next(
            (row for row in snapshots if row.get("snapshotHash") == snapshot["snapshotHash"]),
            None,
        )
        if existing_snapshot is None:
            snapshots.append(snapshot)
        elif not existing_snapshot.get("request"):
            existing_snapshot["request"] = frozen_request
            existing_snapshot["requestHash"] = request_hash
        run = create_project_analysis_run(
            repo.state,
            tenant_id=request_tenant_id(request),
            project_id=project_id,
            snapshot=snapshot,
            preview=preview,
            actor_id=str(request_user_id(request) or "AUTO"),
        )
        if not run.get("dispatch"):
            # 先落库再派发：worker 拿到任务比本请求结束后的中间件统一落库更快，
            # prepare 首跳会 PROJECT_ANALYSIS_RUN_NOT_FOUND，白烧一次重试退避
            # （实测约 17 秒）。和 worker 侧 prepare→execute 的「先提交再派发」同理。
            # celery 的派发信封确定性可先算：连信封一起落库，本请求之后不再改
            # run 行，收尾中间件就没有这一行的增量，worker 落库不会撞
            # ConcurrentPersistenceError。
            envelope = task_dispatcher.project_analysis_dispatch_envelope(
                str(run["projectAnalysisRunId"])
            )
            if envelope:
                run["dispatch"] = envelope
            flush_state(
                {
                    "project_analysis_runs",
                    "project_analysis_snapshots",
                    "project_analysis_events",
                }
            )
            try:
                dispatched = task_dispatcher.dispatch_project_analysis(
                    str(run["projectAnalysisRunId"])
                )
                if not envelope:
                    run["dispatch"] = dispatched
            except Exception as exc:  # noqa: BLE001 - broker failure must become a retryable API result
                # run 已经落库，不能再从内存里删掉了事——那会留下一个永远
                # preparing_snapshot 的 DB 孤儿。改为落 failed 终态；failed 运行
                # 不会被幂等复用，broker 恢复后重试会创建新运行。
                run["dispatch"] = None  # 信封已预写但任务从未发出去
                advance_project_analysis_phase(
                    repo.state,
                    run,
                    "failed",
                    errorCode="DISPATCH_FAILED",
                    errorMessage="全工程分析任务派发失败：Redis/Celery 不可用。",
                )
                flush_state({"project_analysis_runs", "project_analysis_events"})
                LOGGER.warning("project_analysis_dispatch_failed: %s", type(exc).__name__)
                return fail(
                    errors.AI_RUN_FAILED,
                    request,
                    message="全工程分析任务派发失败，请确认 Redis 和 Celery worker 可用后重试。",
                    http_status=503,
                )
        audit_id = repo.add_audit(
            "发起工程一键分析",
            "ProjectAnalysisRun",
            str(run["projectAnalysisRunId"]),
        )
        return ok(
            {"run": project_analysis_run_view(run), "auditLogId": audit_id},
            request,
        )

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "body": body},
    )


@project_analysis_router.get("/projects/{project_id}/inspection/full-project-analysis/runs")
def list_project_analysis_runs(request: Request, project_id: str):
    if error := _authorize(request, project_id, write=False):
        return error
    tenant_id = request_tenant_id(request)
    rows = [
        row
        for row in repo.state.get("project_analysis_runs") or []
        if row.get("tenantId") == tenant_id and row.get("projectId") == project_id
    ]
    rows.sort(key=lambda row: str(row.get("createdAt") or ""), reverse=True)
    return ok(
        {"items": [project_analysis_run_view(row) for row in rows], "total": len(rows)}, request
    )


def _run_for_request(request: Request, project_id: str, run_id: str) -> dict[str, Any] | None:
    return next(
        (
            row
            for row in repo.state.get("project_analysis_runs") or []
            if row.get("tenantId") == request_tenant_id(request)
            and row.get("projectId") == project_id
            and row.get("projectAnalysisRunId") == run_id
        ),
        None,
    )


@project_analysis_router.get(
    "/projects/{project_id}/inspection/full-project-analysis/runs/{run_id}"
)
def get_project_analysis_run(request: Request, project_id: str, run_id: str):
    if error := _authorize(request, project_id, write=False):
        return error
    run = _run_for_request(request, project_id, run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    return ok({"run": project_analysis_run_view(run)}, request)


@project_analysis_router.get(
    "/projects/{project_id}/inspection/full-project-analysis/runs/{run_id}/status"
)
def get_project_analysis_status(request: Request, project_id: str, run_id: str):
    if error := _authorize(request, project_id, write=False):
        return error
    run = _run_for_request(request, project_id, run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    return ok({"status": project_analysis_status_view(run, queue_probe=queue_status_for_task)}, request)
