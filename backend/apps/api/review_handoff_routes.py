"""Authorized, append-only workstation handoff drafts; no publication or execution."""
from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, Body, Header, Query, Request

from apps.api import document_access_policy
from apps.api import routes as api
from libs.contracts import errors
from libs.contracts.responses import fail, ok, server_time
from libs.db.repository import repo
from libs.review_handoff_evidence import inspect_handoff_evidence
from libs.review_handoff_sources import inspect_handoff_sources
from libs.review_handoff_verification import append_verification, verification_view
from libs.review_handoffs import create_handoff_draft, validate_handoff_draft
from libs.review_workstations import digest, station_snapshot

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
    repo.state.setdefault("review_handoffs", [])
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


def _source_check(runs):
    repo.ensure_deferred_loaded("ocr_parse_results", "fact_corrections")
    return inspect_handoff_sources(runs, repo.state)


@router.post("/projects/{project_id}/review-handoffs")
def save_handoff(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict),
                 idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
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
        if _source_check(runs)["requiresRevalidation"]:
            raise ValueError("handoff_endpoint_sources_changed_recreate_run")
        draft = create_handoff_draft(*runs, kind=body["kind"], subject=body["subject"],
                                     payload=body["payload"], evidence_refs=body["evidenceRefs"])
    except (TypeError, ValueError) as exc:
        return fail(errors.VALIDATION_ERROR, request, message=str(exc))
    def produce():
        existing = repo.find_one("review_handoffs", draft["id"])
        if existing:
            return ok(repo.clone(existing), request)
        record = {"id": draft["id"], "tenantId": api.request_tenant_id(request), "projectId": project_id,
                  "sourceNodeId": runs[0]["nodeId"], "targetNodeId": runs[1]["nodeId"], "draft": draft,
                  "createdByUserId": api.request_user_id(request), "createdAt": server_time()}
        repo.state.setdefault("review_handoffs", []).append(record)
        return ok(repo.clone(record), request)

    return api.idempotent(request, idempotency_key, produce,
                          fingerprint_source={"body": body, "snapshotHash": draft["snapshotHash"]})


def _evidence_documents(draft, project_id):
    """Resolve IDs from visible repository versions, never caller-supplied document IDs."""
    selected = {ref.get("documentVersionId") for ref in draft.get("evidenceRefs", [])}
    tenant_id = draft["source"]["tenantId"]
    documents = {row["id"]: row for row in repo.state.get("documents", [])
                 if row.get("projectId") == project_id and api.tenant_id_for_record(row) == tenant_id}
    return [{"documentVersionId": row["id"], "documentId": row["documentId"],
             "fileName": row.get("fileName") or documents[row["documentId"]].get("fileName"),
             "fileType": row.get("fileType") or documents[row["documentId"]].get("fileType")}
            for row in repo.state.get("versions", []) if row.get("id") in selected
            and row.get("documentId") in documents and api.tenant_id_for_record(row) == tenant_id]


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
        source_check = _source_check(runs)
        if source_check["requiresRevalidation"]:
            validation = {"status": "stale_or_invalid", "authoritative": False,
                          "reason": "handoff_endpoint_sources_changed_recreate_run",
                          "inputSourceCheck": source_check}
            return {**repo.clone(record), "validation": validation,
                    "verification": verification_view(record, validation),
                    "evidenceDocuments": _evidence_documents(draft, project_id)}, None
        validation = {"status": "current_draft", "authoritative": False,
                      "inputSourceCheck": source_check,
                      "evidenceLocationCheck": inspect_handoff_evidence(draft, repo.state.get("ocr_parse_results", []))}
    except (TypeError, ValueError) as exc:
        validation = {"status": "stale_or_invalid", "authoritative": False, "reason": str(exc)}
    return {**repo.clone(record), "validation": validation,
            "evidenceDocuments": _evidence_documents(draft, project_id),
            "verification": verification_view(record, validation)}, None


@router.get("/projects/{project_id}/review-handoffs/targets")
def handoff_targets(request: Request, project_id: str, sourceRunId: str = Query(...),
                    page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100)):
    if error := _guard(request, project_id):
        return error
    visible = _visible_versions(request, project_id)
    runs, error = _runs(request, project_id, sourceRunId, sourceRunId, visible)
    if error:
        return error
    source = runs[0]
    allowed_nodes = api.authorized_node_scope(request, project_id)
    items = []
    for candidate in repo.state.get("review_runs", []):
        if (candidate.get("projectId") != project_id
                or api.tenant_id_for_record(candidate) != api.request_tenant_id(request)
                or candidate.get("businessPackId") != source.get("businessPackId")
                or candidate.get("nodeId") == source.get("nodeId")
                or (allowed_nodes is not None and candidate.get("nodeId") not in allowed_nodes)
                or set(candidate.get("inputDocumentVersionIds") or []) - visible):
            continue
        try:
            station = station_snapshot(candidate)
        except (TypeError, ValueError):
            continue
        if not station:
            continue
        items.append({"runId": candidate.get("reviewRunId") or candidate.get("id"),
                      "nodeId": candidate.get("nodeId"), "stationId": station["stationId"],
                      "status": candidate.get("status"), "createdAt": candidate.get("createdAt")})
    items.sort(key=lambda row: (str(row["createdAt"] or ""), str(row["runId"])), reverse=True)
    start = (page - 1) * pageSize
    return ok({"items": items[start:start + pageSize], "total": len(items), "page": page, "pageSize": pageSize}, request)


def _context_handoff_ids(request, project_id, run_id, visible):
    from libs.review_handoff_inputs import frozen_handoff_items

    runs, error = _runs(request, project_id, run_id, run_id, visible)
    if error:
        return set(), error
    run = runs[0]
    if "handoffInputsSnapshot" not in run:
        return set(), None
    try:
        items = frozen_handoff_items(run)
    except (TypeError, ValueError, KeyError):
        return set(), fail(errors.CONFLICT, request, message="本任务的交接依赖记录无法核对。")
    for item in items:
        for endpoint in (item["draft"]["source"], item["draft"]["target"]):
            if set(endpoint.get("documentVersionIds") or []) - visible:
                return set(), fail(errors.FORBIDDEN, request)
            if error := _guard(request, project_id, [endpoint["nodeId"]]):
                return set(), error
    return {item["handoffId"] for item in items}, None


@router.get("/projects/{project_id}/review-handoffs")
def list_handoffs(request: Request, project_id: str, page: int = Query(default=1, ge=1),
                  page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
                  source_run_id: str | None = Query(default=None, alias="sourceRunId"),
                  target_run_id: str | None = Query(default=None, alias="targetRunId"),
                  event_id: str | None = Query(default=None, alias="eventId")):
    if error := _guard(request, project_id):
        return error
    if error := _refresh_dependency_state(request):
        return error
    if error := _guard(request, project_id):
        return error
    repo.ensure_deferred_loaded("review_handoffs", "review_runs")
    visible_versions = _visible_versions(request, project_id)
    used_ids = set()
    if target_run_id:
        used_ids, error = _context_handoff_ids(request, project_id, target_run_id, visible_versions)
        if error:
            return ok({"items": [], "total": 0, "page": page, "pageSize": page_size}, request)
    items = []
    for record in repo.state.get("review_handoffs", []):
        if record.get("projectId") != project_id or api.tenant_id_for_record(record) != api.request_tenant_id(request):
            continue
        draft = record.get("draft") or {}
        if source_run_id is not None and draft.get("source", {}).get("runId") != source_run_id:
            continue
        if target_run_id is not None and draft.get("target", {}).get("runId") != target_run_id and record["id"] not in used_ids:
            continue
        if event_id is not None and draft.get("subject", {}).get("eventId") != event_id:
            continue
        view, error = _record_view(request, project_id, record, visible_versions)
        if error is None:
            if target_run_id:
                view["readContext"] = {"runId": target_run_id, "relation": "used_input" if record["id"] in used_ids else "received"}
            items.append(view)
    items.sort(key=lambda row: (row.get("createdAt") or "", row["id"]), reverse=True)
    start = (page - 1) * page_size
    return ok({"items": items[start:start + page_size], "total": len(items), "page": page, "pageSize": page_size}, request)


@router.post("/projects/{project_id}/review-handoffs/{handoff_id}/verifications")
def verify_handoff(request: Request, project_id: str, handoff_id: str,
                   body: dict[str, Any] = Body(default_factory=dict),
                   idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if error := _guard(request, project_id):
        return error
    repo.ensure_deferred_loaded("review_handoffs")
    repo.state.setdefault("review_handoffs", [])
    record = repo.find_one("review_handoffs", handoff_id)
    if not record or record.get("projectId") != project_id or api.tenant_id_for_record(record) != api.request_tenant_id(request):
        return fail(errors.NOT_FOUND, request)
    view, error = _record_view(request, project_id, record, _visible_versions(request, project_id))
    if error is not None:
        return error
    if error := api.mutation_guard(request, project_id, node_ids=[record["sourceNodeId"], record["targetNodeId"]]):
        return error
    if "review:save" not in repo.role_actions("inspection"):
        return fail(errors.FORBIDDEN, request)
    validation = view["validation"]
    if validation["status"] != "current_draft" or validation["inputSourceCheck"]["status"] != "current":
        return fail(errors.VALIDATION_ERROR, request, message="handoff_current_frozen_sources_required")
    if (body.get("outcome") == "verified" and record["draft"]["kind"] != "collaboration"
            and validation["evidenceLocationCheck"]["status"] != "locations_found"):
        return fail(errors.VALIDATION_ERROR, request, message="handoff_evidence_locations_required")
    def produce():
        try:
            append_verification(record, body, actor=api.request_user_id(request), created_at=server_time())
        except (TypeError, ValueError) as exc:
            return fail(errors.VALIDATION_ERROR, request, message=str(exc))
        return ok(repo.clone(record), request)
    return api.idempotent(request, idempotency_key, produce,
                          fingerprint_source={"body": body, "snapshotHash": record["draft"]["snapshotHash"]})


@router.get("/projects/{project_id}/review-handoffs/{handoff_id}")
def get_handoff(request: Request, project_id: str, handoff_id: str, contextRunId: str | None = Query(default=None)):
    if error := _guard(request, project_id):
        return error
    if error := _refresh_dependency_state(request):
        return error
    if error := _guard(request, project_id):
        return error
    repo.ensure_deferred_loaded("review_handoffs")
    repo.state.setdefault("review_handoffs", [])
    record = repo.find_one("review_handoffs", handoff_id)
    if (not record or record.get("projectId") != project_id
            or api.tenant_id_for_record(record) != api.request_tenant_id(request)):
        return fail(errors.NOT_FOUND, request)
    view, error = _record_view(request, project_id, record, _visible_versions(request, project_id))
    if error is not None:
        return error
    if contextRunId:
        used_ids, error = _context_handoff_ids(request, project_id, contextRunId, _visible_versions(request, project_id))
        if error:
            return error
        if record["draft"]["target"]["runId"] != contextRunId and handoff_id not in used_ids:
            return fail(errors.NOT_FOUND, request)
        view["readContext"] = {"runId": contextRunId, "relation": "used_input" if handoff_id in used_ids else "received"}
    return ok(view, request)


@router.get("/projects/{project_id}/review-runs/{run_id}/pipeline-conflicts")
def get_pipeline_conflicts(request: Request, project_id: str, run_id: str):
    if error := _guard(request, project_id):
        return error
    visible = _visible_versions(request, project_id)
    runs, error = _runs(request, project_id, run_id, run_id, visible)
    if error:
        return error
    run = runs[0]
    report = run.get("pipelineConflictReport")
    if not isinstance(report, dict) or report.get("schemaVersion") != "pipeline-conflict-report-v1":
        return fail(errors.NOT_FOUND, request)
    if (report.get("projectId") != project_id or report.get("tenantId") != api.request_tenant_id(request)
            or report.get("reviewRunId") != run_id or report.get("nodeId") != run.get("nodeId")):
        return fail(errors.NOT_FOUND, request)
    frozen_versions = report.get("documentVersionIds")
    if not isinstance(frozen_versions, list) or set(frozen_versions) - visible:
        return fail(errors.FORBIDDEN, request)
    # Original failure evidence remains historical even if the task record changes.
    return ok({"report": repo.clone(report), "historical": True, "authoritative": False}, request)


def handoff_replay_error(request: Request, cached: dict[str, Any]):
    """Recheck live and frozen access before the middleware returns a cached draft."""
    match = re.fullmatch(r"(?:/api)?/projects/([^/]+)/review-handoffs(?:/([^/]+)/verifications)?", request.url.path)
    if request.method != "POST" or not match:
        return None
    project_id = match.group(1)
    if error := _guard(request, project_id):
        return error
    record = (cached.get("response") or {}).get("data")
    if not isinstance(record, dict) or not isinstance(record.get("draft"), dict):
        return fail(errors.IDEMPOTENCY_KEY_CONFLICT, request)
    view, error = _record_view(request, project_id, record, _visible_versions(request, project_id))
    if error is not None:
        return error
    if match.group(2):
        current = repo.find_one("review_handoffs", match.group(2))
        if current is None or digest(current) != digest(record):
            return fail(errors.IDEMPOTENCY_KEY_CONFLICT, request)
        if error := api.mutation_guard(request, project_id, node_ids=[current["sourceNodeId"], current["targetNodeId"]]):
            return error
        if "review:save" not in repo.role_actions("inspection"):
            return fail(errors.FORBIDDEN, request)
        if view["validation"].get("inputSourceCheck", {}).get("status") != "current":
            return fail(errors.IDEMPOTENCY_KEY_CONFLICT, request)
    if view["validation"]["status"] != "current_draft":
        return fail(errors.IDEMPOTENCY_KEY_CONFLICT, request)
    return None


def _dependency_status(request, project_id, run_id, visible):
    from libs.review_handoff_inputs import handoff_dependency_status

    runs, error = _runs(request, project_id, run_id, run_id, visible)
    if error:
        return None, error
    run = runs[0]
    snapshot = run.get("handoffInputsSnapshot") or {}
    for item in snapshot.get("items", []):
        draft = item.get("draft") or {}
        for side in ("source", "target"):
            if set((draft.get(side) or {}).get("documentVersionIds") or []) - visible:
                return None, fail(errors.FORBIDDEN, request)
        if error := _guard(request, project_id, [draft["source"]["nodeId"], draft["target"]["nodeId"]]):
            return None, error
    repo.ensure_deferred_loaded("ocr_parse_results", "fact_corrections")
    status = handoff_dependency_status(run, repo.state)
    return {"reviewRunId": run_id, **status, "historicalResultsPreserved": True}, None


def _refresh_dependency_state(request):
    if repo.sync_postgres is None:
        return None
    try:
        repo.refresh_collections_incrementally({
            "review_runs", "review_handoffs", "review_sessions", "documents", "versions",
            "ocr_parse_results", "fact_corrections",
        }, strict=True)
    except Exception:  # noqa: BLE001 -- never report cached dependencies as freshly verified after a database failure
        return fail(errors.REVIEW_STATE_UNAVAILABLE, request, http_status=503)
    return None


@router.get("/projects/{project_id}/review-runs/{run_id}/handoff-dependencies")
def get_handoff_dependencies(request: Request, project_id: str, run_id: str):
    if error := _guard(request, project_id):
        return error
    if error := _refresh_dependency_state(request):
        return error
    if error := _guard(request, project_id):
        return error
    status, error = _dependency_status(request, project_id, run_id, _visible_versions(request, project_id))
    return error if error is not None else ok(status, request)


@router.get("/projects/{project_id}/review-handoff-node-statuses")
def get_handoff_node_statuses(request: Request, project_id: str):
    if error := _guard(request, project_id):
        return error
    if error := _refresh_dependency_state(request):
        return error
    if error := _guard(request, project_id):
        return error
    repo.ensure_deferred_loaded("review_runs", "review_handoffs", "review_sessions")
    visible = _visible_versions(request, project_id)
    groups = api.filter_node_groups_for_scope(repo.node_groups(project_id), api.authorized_node_scope(request, project_id))
    items = []
    for node_id in sorted({node["nodeId"] for group in groups for node in group["nodes"]}):
        session = api.active_review_session(request, project_id, node_id)
        run = api.latest_review_run_for_node(project_id, node_id, review_run_id=(session or {}).get("activeReviewRunId"))
        if run is None:
            items.append({"nodeId": node_id, "status": "not_used", "requiresRevalidation": False})
            continue
        run_id = run.get("reviewRunId") or run.get("id")
        try:
            status, error = _dependency_status(request, project_id, run_id, visible)
        except (TypeError, ValueError, KeyError):
            status, error = None, True
        if error is not None:
            items.append({"nodeId": node_id, "status": "unavailable", "requiresRevalidation": None})
        else:
            items.append({"nodeId": node_id, "reviewRunId": run_id, "status": status["status"],
                          "requiresRevalidation": status["requiresRevalidation"]})
    return ok({"projectId": project_id, "items": items, "requiresRevalidationCount": sum(row["requiresRevalidation"] is True for row in items),
               "unavailableCount": sum(row["status"] == "unavailable" for row in items),
               "automaticRerun": False, "historicalResultsPreserved": True}, request)
