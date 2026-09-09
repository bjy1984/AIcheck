"""Authorized, append-only workstation handoff drafts; no publication or execution."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Body, Query, Request

from apps.api import document_access_policy
from apps.api import routes as api
from libs.contracts import errors
from libs.contracts.responses import fail, ok, server_time
from libs.db.repository import repo
from libs.review_handoff_evidence import inspect_handoff_evidence
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


def _visible_versions(request, project_id):
    visible = document_access_policy.actor_visible_evidence_repository(api._DOCUMENT_ACCESS_SERVICES, request, project_id)
    return {row["id"] for row in visible.state.get("versions", [])
            if api.tenant_id_for_record(row) == api.request_tenant_id(request)}


def _runs(request, project_id, source_id, target_id, visible_versions=None):
    repo.ensure_deferred_loaded("review_runs", "review_handoffs")
    runs = [next((row for row in repo.state.get("review_runs", [])
                  if (row.get("reviewRunId") or row.get("id")) == run_id), None) for run_id in (source_id, target_id)]
    if any(not row or row.get("projectId") != project_id
           or api.tenant_id_for_record(row) != api.request_tenant_id(request) for row in runs):
        return None, fail(errors.NOT_FOUND, request)
    if error := _guard(request, project_id, [row["nodeId"] for row in runs]):
        return None, error
    versions = _visible_versions(request, project_id) if visible_versions is None else visible_versions
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


def _record_view(request, project_id, record, visible_versions):
    draft = record["draft"]
    # Check frozen inputs as well as current runs: editing a source run must not
    # make an old restricted document disappear from the read authorization check.
    for endpoint in (draft["source"], draft["target"]):
        if not isinstance(endpoint.get("documentVersionIds"), list) or set(endpoint["documentVersionIds"]) - visible_versions:
            return None, fail(errors.FORBIDDEN, request)
    if {row.get("documentVersionId") for row in draft.get("evidenceRefs", [])} - visible_versions:
        return None, fail(errors.FORBIDDEN, request)
    runs, error = _runs(request, project_id, draft["source"]["runId"], draft["target"]["runId"], visible_versions)
    if error:
        return None, error
    try:
        validate_handoff_draft(draft, *runs, subject=draft["subject"])
        repo.ensure_deferred_loaded("ocr_parse_results")
        validation = {"status": "current_draft", "authoritative": False,
                      "evidenceLocationCheck": inspect_handoff_evidence(draft, repo.state.get("ocr_parse_results", []))}
    except (TypeError, ValueError) as exc:
        validation = {"status": "stale_or_invalid", "authoritative": False, "reason": str(exc)}
    return {**repo.clone(record), "validation": validation}, None


@router.get("/projects/{project_id}/review-handoffs")
def list_handoffs(request: Request, project_id: str, page: int = Query(default=1, ge=1),
                  page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
                  source_run_id: str | None = Query(default=None, alias="sourceRunId"),
                  target_run_id: str | None = Query(default=None, alias="targetRunId")):
    if error := _guard(request, project_id):
        return error
    repo.ensure_deferred_loaded("review_handoffs", "review_runs")
    visible_versions = _visible_versions(request, project_id)
    items = []
    for record in repo.state.get("review_handoffs", []):
        if record.get("projectId") != project_id or api.tenant_id_for_record(record) != api.request_tenant_id(request):
            continue
        draft = record.get("draft") or {}
        if source_run_id is not None and draft.get("source", {}).get("runId") != source_run_id:
            continue
        if target_run_id is not None and draft.get("target", {}).get("runId") != target_run_id:
            continue
        view, error = _record_view(request, project_id, record, visible_versions)
        if error is None:
            items.append(view)
    items.sort(key=lambda row: (row.get("createdAt") or "", row["id"]), reverse=True)
    start = (page - 1) * page_size
    return ok({"items": items[start:start + page_size], "total": len(items), "page": page, "pageSize": page_size}, request)


@router.get("/projects/{project_id}/review-handoffs/{handoff_id}")
def get_handoff(request: Request, project_id: str, handoff_id: str):
    if error := _guard(request, project_id):
        return error
    repo.ensure_deferred_loaded("review_handoffs")
    record = repo.find_one("review_handoffs", handoff_id)
    if (not record or record.get("projectId") != project_id
            or api.tenant_id_for_record(record) != api.request_tenant_id(request)):
        return fail(errors.NOT_FOUND, request)
    view, error = _record_view(request, project_id, record, _visible_versions(request, project_id))
    return error if error is not None else ok(view, request)
