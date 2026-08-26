from __future__ import annotations

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
from libs.db.repository import repo
from libs.integrations import task_dispatcher
from libs.project_analysis.domain import (
    create_project_analysis_run,
    project_analysis_run_view,
    project_analysis_status_view,
)
from libs.project_analysis.prompt import project_analysis_preview

project_analysis_router = APIRouter()


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
    return next(
        (
            row
            for row in repo.state.get("model_route_versions") or []
            if row.get("modelAlias") == "project-review-large"
            and row.get("status") == "production"
        ),
        None,
    )


def _preview(project_id: str) -> dict[str, Any]:
    route = _model_route()
    if not route:
        raise ValueError("PROJECT_ANALYSIS_MODEL_ROUTE_UNAVAILABLE")
    return project_analysis_preview(repo.state, project_id, model_route=route)


def _public_preview(preview: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in preview.items()
        if key not in {"request", "snapshot"}
    }


@project_analysis_router.get(
    "/projects/{project_id}/inspection/full-project-analysis/preview"
)
def get_project_analysis_preview(request: Request, project_id: str):
    if error := _authorize(request, project_id, write=False):
        return error
    try:
        preview = _preview(project_id)
    except ValueError as exc:
        return fail(errors.CONFLICT, request, message=str(exc))
    return ok({"preview": _public_preview(preview)}, request)


@project_analysis_router.post(
    "/projects/{project_id}/inspection/full-project-analysis/runs"
)
def create_project_analysis(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        if error := _authorize(request, project_id, write=True):
            return error
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
        if preview["contextLimitExceeded"]:
            return fail(
                errors.VALIDATION_ERROR,
                request,
                message="PROJECT_ANALYSIS_CONTEXT_LIMIT_EXCEEDED",
                data=_public_preview(preview),
            )
        snapshot = {**preview["snapshot"], "tenantId": request_tenant_id(request)}
        snapshots = repo.state.setdefault("project_analysis_snapshots", [])
        if not any(row.get("snapshotHash") == snapshot["snapshotHash"] for row in snapshots):
            snapshots.append(snapshot)
        run = create_project_analysis_run(
            repo.state,
            tenant_id=request_tenant_id(request),
            project_id=project_id,
            snapshot=snapshot,
            preview=preview,
            actor_id=str(request_user_id(request) or "AUTO"),
        )
        if not run.get("dispatch"):
            run["dispatch"] = task_dispatcher.dispatch_project_analysis(
                str(run["projectAnalysisRunId"])
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


@project_analysis_router.get(
    "/projects/{project_id}/inspection/full-project-analysis/runs"
)
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
    return ok({"items": [project_analysis_run_view(row) for row in rows], "total": len(rows)}, request)


def _run_for_request(
    request: Request, project_id: str, run_id: str
) -> dict[str, Any] | None:
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
    return ok({"status": project_analysis_status_view(run)}, request)
