from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, Request

from apps.api.routes import (
    effective_role_for_request,
    idempotent,
    mutation_guard,
    request_tenant_id,
    versioned_record,
)
from libs.auto_review import default_auto_review_policy, validate_auto_review_policy
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.repository import repo


auto_review_router = APIRouter()


def _policy_for_project(tenant_id: str, project_id: str) -> dict[str, Any]:
    existing = next(
        (
            row
            for row in repo.state.get("auto_review_policies") or []
            if str(row.get("tenantId") or "") == str(tenant_id)
            and str(row.get("projectId") or "") == str(project_id)
        ),
        None,
    )
    return existing or default_auto_review_policy(project_id, tenant_id)


def _authorize(request: Request, project_id: str, *, write: bool) -> Any | None:
    role, identity_error = effective_role_for_request(request)
    if identity_error:
        return identity_error
    if not repo.require_project(project_id):
        return fail(errors.NOT_FOUND, request)
    if role not in {"inspection", "admin"}:
        return fail(errors.FORBIDDEN, request, message="仅监检人员或管理员可管理自动审查。")
    if write:
        # 此端点的 If-Match 属于 AutoReviewPolicy，不是 Project。权限、归档和
        # 节点范围仍复用 mutation_guard，但项目版本比较必须显式跳过；策略版本
        # 在 produce() 中按自己的 ETag 校验。
        return mutation_guard(request, project_id, if_match="*")
    return None


@auto_review_router.get("/projects/{project_id}/inspection/auto-review-policy")
def get_auto_review_policy(request: Request, project_id: str):
    error = _authorize(request, project_id, write=False)
    if error:
        return error
    tenant_id = request_tenant_id(request)
    policy = _policy_for_project(tenant_id, project_id)
    return ok({"policy": versioned_record("auto-review-policy", policy)}, request)


@auto_review_router.put("/projects/{project_id}/inspection/auto-review-policy")
def update_auto_review_policy(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        error = _authorize(request, project_id, write=True)
        if error:
            return error
        tenant_id = request_tenant_id(request)
        existing = _policy_for_project(tenant_id, project_id)
        current_view = versioned_record("auto-review-policy", existing)
        if not if_match:
            return fail(errors.PRECONDITION_REQUIRED, request)
        if if_match not in {"*", str(current_view["etag"])}:
            return fail(errors.ETAG_CONFLICT, request)
        try:
            updated = validate_auto_review_policy(body, existing)
        except ValueError as exc:
            return fail(errors.VALIDATION_ERROR, request, message=str(exc))
        rows = repo.state.setdefault("auto_review_policies", [])
        rows[:] = [row for row in rows if str(row.get("id") or "") != str(updated["id"])]
        rows.insert(0, updated)
        audit_id = repo.add_audit("更新项目自动审查策略", "AutoReviewPolicy", str(updated["id"]))
        return ok(
            {
                "policy": versioned_record("auto-review-policy", updated),
                "auditLogId": audit_id,
            },
            request,
        )

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "body": body},
    )


@auto_review_router.get("/projects/{project_id}/inspection/auto-review-status")
def get_auto_review_status(request: Request, project_id: str):
    error = _authorize(request, project_id, write=False)
    if error:
        return error
    tenant_id = request_tenant_id(request)
    policy = _policy_for_project(tenant_id, project_id)
    candidates = [
        row
        for row in repo.state.get("auto_review_candidates") or []
        if str(row.get("tenantId") or "") == str(tenant_id)
        and str(row.get("projectId") or "") == str(project_id)
    ]
    project_runs = [
        row
        for row in repo.state.get("project_review_runs") or []
        if str(row.get("tenantId") or "") == str(tenant_id)
        and str(row.get("projectId") or "") == str(project_id)
    ]
    return ok(
        {
            "policy": versioned_record("auto-review-policy", policy),
            "pendingNodeCount": len(
                {int(row.get("nodeId") or 0) for row in candidates if row.get("status") == "pending"}
                - {0}
            ),
            "runningProjectRunCount": sum(row.get("status") == "running" for row in project_runs),
            "failedProjectRunCount": sum(row.get("status") in {"failed", "partial"} for row in project_runs),
            "latestProjectRun": project_runs[0] if project_runs else None,
        },
        request,
    )
