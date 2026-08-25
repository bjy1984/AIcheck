from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Header, Request

from apps.api.routes import (
    ai_recheck,
    effective_role_for_request,
    idempotent,
    mutation_guard,
    request_tenant_id,
    versioned_record,
)
from libs.auto_review import (
    active_mounted_node_ids,
    build_project_review_summary,
    create_project_review_run,
    default_auto_review_policy,
    dispatch_project_review_run,
    validate_auto_review_policy,
)
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
    child_review_run_ids = {
        str(item)
        for project_run in project_runs
        for item in project_run.get("childReviewRunIds") or []
        if item
    }
    child_runs = [
        row
        for row in repo.state.get("review_runs") or []
        if isinstance(row, dict)
        and str(row.get("reviewRunId") or row.get("id") or "")
        in child_review_run_ids
        and str(row.get("projectId") or "") == str(project_id)
        and str(row.get("tenantId") or tenant_id) == str(tenant_id)
    ]
    incomplete_runs = [
        row
        for row in child_runs
        if str(row.get("status") or "") == "review_incomplete"
    ]
    latest_failure = incomplete_runs[0] if incomplete_runs else None
    return ok(
        {
            "policy": versioned_record("auto-review-policy", policy),
            "pendingNodeCount": len(
                {int(row.get("nodeId") or 0) for row in candidates if row.get("status") == "pending"}
                - {0}
            ),
            "runningProjectRunCount": sum(row.get("status") == "running" for row in project_runs),
            "failedProjectRunCount": sum(row.get("status") in {"failed", "partial"} for row in project_runs),
            "runningNodeReviewCount": sum(
                str(row.get("status") or "") in {"queued", "running", "retry_pending"}
                for row in child_runs
            ),
            "reviewIncompleteNodeCount": len(incomplete_runs),
            "shardProgress": {
                "expectedShardCount": sum(
                    int((row.get("evidenceCoverage") or {}).get("expectedShardCount") or 0)
                    for row in child_runs
                ),
                "completedShardCount": sum(
                    int((row.get("evidenceCoverage") or {}).get("completedShardCount") or 0)
                    for row in child_runs
                ),
                "failedShardCount": sum(
                    int((row.get("evidenceCoverage") or {}).get("failedShardCount") or 0)
                    for row in child_runs
                ),
            },
            "latestFailure": (
                {
                    "reviewRunId": latest_failure.get("reviewRunId")
                    or latest_failure.get("id"),
                    "nodeId": latest_failure.get("nodeId"),
                    "errorCode": latest_failure.get("errorCode"),
                    "failedEvidenceShardIds": repo.clone(
                        latest_failure.get("failedEvidenceShardIds") or []
                    ),
                }
                if latest_failure
                else None
            ),
            "latestProjectRun": project_runs[0] if project_runs else None,
        },
        request,
    )


@auto_review_router.get(
    "/projects/{project_id}/inspection/project-review-runs"
)
def list_project_review_runs(request: Request, project_id: str):
    error = _authorize(request, project_id, write=False)
    if error:
        return error
    tenant_id = request_tenant_id(request)
    rows = [
        row
        for row in repo.state.get("project_review_runs") or []
        if isinstance(row, dict)
        and str(row.get("tenantId") or "") == tenant_id
        and str(row.get("projectId") or "") == str(project_id)
    ]
    rows.sort(
        key=lambda row: str(
            row.get("createdAt") or row.get("startedAt") or row.get("id") or ""
        ),
        reverse=True,
    )
    return ok(
        {
            "projectReviewRuns": [
                {
                    **repo.clone(row),
                    "summary": build_project_review_summary(repo.state, row),
                }
                for row in rows
            ],
            "total": len(rows),
        },
        request,
    )


@auto_review_router.get(
    "/projects/{project_id}/inspection/project-review-runs/{project_review_run_id}"
)
def get_project_review_run(
    request: Request, project_id: str, project_review_run_id: str
):
    error = _authorize(request, project_id, write=False)
    if error:
        return error
    tenant_id = request_tenant_id(request)
    project_run = next(
        (
            row
            for row in repo.state.get("project_review_runs") or []
            if isinstance(row, dict)
            and str(row.get("tenantId") or "") == tenant_id
            and str(row.get("projectId") or "") == str(project_id)
            and str(row.get("projectReviewRunId") or row.get("id") or "")
            == str(project_review_run_id)
        ),
        None,
    )
    if not project_run:
        return fail(errors.NOT_FOUND, request)
    return ok(
        {
            "projectReviewRun": repo.clone(project_run),
            "summary": build_project_review_summary(repo.state, project_run),
        },
        request,
    )


@auto_review_router.post("/projects/{project_id}/inspection/auto-review/run")
def run_project_auto_review(
    request: Request,
    project_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        error = _authorize(request, project_id, write=True)
        if error:
            return error
        tenant_id = request_tenant_id(request)
        policy = _policy_for_project(tenant_id, project_id)
        node_ids = active_mounted_node_ids(repo.state, project_id)
        parent = create_project_review_run(
            repo.state,
            tenant_id=tenant_id,
            project_id=project_id,
            trigger_type="manual_full",
            policy=policy,
            node_ids=node_ids,
        )

        def start_node_review(target_project_id: str, node_id: int, metadata: dict) -> dict:
            response = ai_recheck(
                request,
                target_project_id,
                node_id,
                {
                    "reviewMode": "gap_precheck",
                    "projectReviewRunId": metadata["projectReviewRunId"],
                    "triggerType": metadata["triggerType"],
                    "autoReviewPolicyRevision": metadata["autoReviewPolicyRevision"],
                },
                None,
                request.headers.get("X-Role"),
            )
            if hasattr(response, "body"):
                payload = json.loads(response.body)
            else:
                payload = response
            if not isinstance(payload, dict) or int(payload.get("code") or 0) != 0:
                raise RuntimeError(str((payload or {}).get("message") or "node review start failed"))
            data = payload.get("data") or {}
            latest_run = data.get("latestRun") or {}
            return {
                "aiRunId": latest_run.get("id") or data.get("runId"),
                "reviewRunId": latest_run.get("reviewRunId") or (data.get("dispatch") or {}).get("reviewRunId"),
                "evidenceSnapshotHash": latest_run.get("evidenceSnapshotHash"),
                "status": latest_run.get("status"),
            }

        dispatch_project_review_run(
            repo.state,
            parent,
            start_node_review=start_node_review,
        )
        audit_id = repo.add_audit(
            "手动发起全工程自动审查",
            "ProjectReviewRun",
            str(parent["projectReviewRunId"]),
        )
        return ok({"projectReviewRun": parent, "auditLogId": audit_id}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "triggerType": "manual_full"},
    )
