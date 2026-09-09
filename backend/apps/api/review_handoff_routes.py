"""Authorized, append-only workstation handoff drafts; no publication or execution."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Body, Request

from apps.api import document_access_policy
from apps.api import routes as api
from libs.contracts import errors
from libs.contracts.responses import fail, ok, server_time
from libs.db.repository import repo
from libs.review_handoffs import create_handoff_draft, validate_handoff_draft

router = APIRouter()
FIELDS = {"sourceRunId", "targetRunId", "kind", "subject", "payload", "evidenceRefs"}


def _guard(request, project_id, nodes=None):
    if os.getenv("AICHECK_WORKSTATIONS_ENABLED", "").lower() not in {"true", "1", "yes"}:
        return fail(errors.NOT_FOUND, request)
    role, error = api.effective_role_for_request(request)
    if error:
        return error
    if role != "inspection" or not api.request_user_id(request):
        return fail(errors.FORBIDDEN, request)
    if not repo.require_project(project_id):
        return fail(errors.NOT_FOUND, request)
    return api.member_node_scope_error(request, project_id, role, node_ids=nodes)


def _runs(request, project_id, source_id, target_id):
    repo.ensure_deferred_loaded("review_runs", "review_handoffs")
    runs = [next((row for row in repo.state.get("review_runs", [])
                  if (row.get("reviewRunId") or row.get("id")) == run_id), None) for run_id in (source_id, target_id)]
    if any(not row or row.get("projectId") != project_id
           or api.tenant_id_for_record(row) != api.request_tenant_id(request) for row in runs):
        return None, fail(errors.NOT_FOUND, request)
    if error := _guard(request, project_id, [row["nodeId"] for row in runs]):
        return None, error
    visible = document_access_policy.actor_visible_evidence_repository(api._DOCUMENT_ACCESS_SERVICES, request, project_id)
    versions = {row["id"] for row in visible.state.get("versions", [])
                if api.tenant_id_for_record(row) == api.request_tenant_id(request)}
    if any(set(row.get("inputDocumentVersionIds") or []) - versions for row in runs):
        return None, fail(errors.FORBIDDEN, request)
    return runs, None


@router.post("/projects/{project_id}/review-handoffs")
def save_handoff(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict)):
    if error := _guard(request, project_id):
        return error
    if set(body) != FIELDS:
        return fail(errors.VALIDATION_ERROR, request, message="交接草稿字段不完整或包含不可写字段。")
    runs, error = _runs(request, project_id, body["sourceRunId"], body["targetRunId"])
    if error:
        return error
    if error := api.mutation_guard(request, project_id, node_ids=[row["nodeId"] for row in runs]):
        return error
    try:
        draft = create_handoff_draft(*runs, kind=body["kind"], subject=body["subject"],
                                     payload=body["payload"], evidence_refs=body["evidenceRefs"])
    except (TypeError, ValueError) as exc:
        return fail(errors.VALIDATION_ERROR, request, message=str(exc))
    existing = repo.find_one("review_handoffs", draft["id"])
    if existing:
        return ok(repo.clone(existing), request)
    record = {"id": draft["id"], "tenantId": api.request_tenant_id(request), "projectId": project_id,
              "sourceNodeId": runs[0]["nodeId"], "targetNodeId": runs[1]["nodeId"], "draft": draft,
              "createdByUserId": api.request_user_id(request), "createdAt": server_time()}
    repo.state.setdefault("review_handoffs", []).append(record)
    return ok(repo.clone(record), request)


@router.get("/projects/{project_id}/review-handoffs/{handoff_id}")
def get_handoff(request: Request, project_id: str, handoff_id: str):
    if error := _guard(request, project_id):
        return error
    repo.ensure_deferred_loaded("review_handoffs")
    record = repo.find_one("review_handoffs", handoff_id)
    if (not record or record.get("projectId") != project_id
            or api.tenant_id_for_record(record) != api.request_tenant_id(request)):
        return fail(errors.NOT_FOUND, request)
    draft = record["draft"]
    runs, error = _runs(request, project_id, draft["source"]["runId"], draft["target"]["runId"])
    if error:
        return error
    try:
        validate_handoff_draft(draft, *runs, subject=draft["subject"])
        validation = {"status": "current_draft", "authoritative": False}
    except (TypeError, ValueError) as exc:
        validation = {"status": "stale_or_invalid", "authoritative": False, "reason": str(exc)}
    return ok({**repo.clone(record), "validation": validation}, request)
