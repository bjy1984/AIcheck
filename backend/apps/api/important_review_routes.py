"""Important-node review: reuse existing scoped documents, AI dispatch and audit results."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Body, Header, Request

from apps.api import routes as api
from apps.api.document_access_policy import actor_visible_evidence_repository
from apps.api.review_input_selection import (
    ReviewInputSelectionError,
    resolve_review_input_selection,
)
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.repository import repo
from libs.important_node_review import NODE_IDS, recommend_nodes, skill_catalog

important_review_router = APIRouter()
PREFIX = "/projects/{project_id}/inspection/important-review"


def guard(request, project_id, node_ids=None):
    role, error = api.effective_role_for_request(request)
    if error:
        return error
    if role != "inspection" or not api.request_user_id(request):
        return fail(errors.FORBIDDEN, request, message="仅授权监检人员可使用重要节点审查。", http_status=403)
    project = repo.require_project(project_id)
    if not project:
        return fail(errors.NOT_FOUND, request)
    if error := api.scope_error_for_record(request, project, project_id):
        return error
    return api.member_node_scope_error(request, project_id, role, node_ids=node_ids)


def allowed_catalog(request, project_id):
    return [node for node in skill_catalog() if guard(request, project_id, [node["nodeId"]]) is None]


@important_review_router.get(PREFIX)
def important_review_config(request: Request, project_id: str):
    if error := guard(request, project_id):
        return error
    enabled = os.getenv("AICHECK_WORKSTATIONS_ENABLED", "").lower() in {"1", "true", "yes"}
    return ok({"nodes": allowed_catalog(request, project_id), "enabled": enabled,
               "disabledReason": "" if enabled else "当前环境尚未开启指定资料审查，请管理员启用工位审查配置。"}, request)


@important_review_router.post(PREFIX + "/analyze")
def analyze_important_review(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict)):
    if error := guard(request, project_id):
        return error
    if set(body) - {"inputDocumentVersionIds"}:
        return fail(errors.VALIDATION_ERROR, request, message="节点分析仅接受所选文件版本。")
    catalog = allowed_catalog(request, project_id)
    if not catalog:
        return fail(errors.FORBIDDEN, request)
    try:
        selection = resolve_review_input_selection(api._DOCUMENT_ACCESS_SERVICES, request, project_id,
                                                  catalog[0]["nodeId"], body)
        if not selection:
            raise ReviewInputSelectionError("请选择本次审查资料。")
    except ReviewInputSelectionError as exc:
        return fail(errors.VALIDATION_ERROR, request, message=str(exc))
    detached = actor_visible_evidence_repository(api._DOCUMENT_ACCESS_SERVICES, request, project_id)
    versions = {row["id"]: row for row in detached.state.get("versions", [])}
    docs = {row["id"]: row for row in detached.state.get("documents", [])}
    chosen = [{**docs[versions[version]["documentId"]], "currentVersionId": version} for version in selection[0]]
    return ok({"nodes": recommend_nodes(catalog, chosen, detached.state.get("ocr_parse_results", []),
                                        detached.state.get("bindings", []))}, request)


@important_review_router.post(PREFIX + "/nodes/{node_id}/runs")
def start_important_review(request: Request, project_id: str, node_id: int,
                           body: dict[str, Any] = Body(default_factory=dict),
                           idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if error := guard(request, project_id, [node_id]):
        return error
    if node_id not in NODE_IDS or set(body) - {"inputDocumentVersionIds"} or not body.get("inputDocumentVersionIds"):
        return fail(errors.VALIDATION_ERROR, request, message="请选择重要节点及本次文件版本。")
    # gap_precheck accepts unbound files and never changes the node's formal business status.
    return api.ai_recheck(request, project_id, node_id, {
        **body, "reviewMode": "gap_precheck", "auditInputMode": "ocr_llm", "importantNodeReview": True,
    }, idempotency_key, None)


@important_review_router.get(PREFIX + "/runs")
def list_important_reviews(request: Request, project_id: str):
    if error := guard(request, project_id):
        return error
    visible = actor_visible_evidence_repository(api._DOCUMENT_ACCESS_SERVICES, request, project_id)
    versions = {row["id"]: row for row in visible.state.get("versions", [])}
    documents = {row["id"]: row for row in visible.state.get("documents", [])}
    candidates = sorted((row for row in repo.state.get("ai_runs", [])
                         if row.get("projectId") == project_id and row.get("importantReviewSnapshot")
                         and api.tenant_id_for_record(row) == api.request_tenant_id(request)),
                        key=lambda row: str(row.get("startedAt") or ""), reverse=True)
    items, seen = [], set()
    for source in candidates:
        node_id = source.get("nodeId")
        if node_id in seen or guard(request, project_id, [node_id]) is not None:
            continue
        selected = source.get("inputDocumentVersionIds") or []
        if any(version not in versions for version in selected):
            continue  # Never disclose evidence after access has been withdrawn.
        seen.add(node_id)
        review_id = source.get("reviewRunId")
        if review_id:
            api.refresh_review_run_from_postgres(review_id)
        run = (repo.find_one("review_runs", review_id, id_field="reviewRunId") if review_id else None)
        if run and api.scope_error_for_record(request, run, project_id) is not None:
            continue
        view = api.review_run_view(run) if run else {}
        files = [{"documentId": versions[value]["documentId"], "versionId": value,
                  "fileName": documents.get(versions[value]["documentId"], {}).get("fileName") or value}
                 for value in selected]
        changed = any(documents.get(row["documentId"], {}).get("currentVersionId") != row["versionId"] for row in files)
        # Return recorded outcomes only. No default 'passed' for empty or failed tasks.
        items.append({"id": source["id"], "nodeId": node_id, "reviewRunId": review_id,
                      "status": view.get("status") or source.get("status"),
                      "startedAt": source.get("startedAt"), "documents": files, "documentsChanged": changed,
                      "rule": source["importantReviewSnapshot"],
                      "errorMessage": view.get("errorMessage") or view.get("dispatchErrorMessage") or source.get("errorMessage"),
                      "atomicCheckOutcomes": view.get("atomicCheckOutcomes") or [],
                      "findingDrafts": view.get("findingDrafts") or source.get("findingDrafts") or [],
                      "automationLimitations": view.get("automationLimitations") or [],
                      "summary": (source.get("suggestion") or {}).get("opinionDraft") if not run else None})
    return ok({"items": items}, request)
