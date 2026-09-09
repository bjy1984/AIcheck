"""Project-scoped draft editing for authorized inspection members."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Body, Header, Request

from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.repository import repo
from libs.rule_conditions import evaluate_conditions, validate_conditions

project_rule_router = APIRouter()
EDITABLE_FIELDS = {
    "executionConditions",
    "inspectionCategory", "inspectionItem", "inspectionClass", "standardText", "witnessText",
    "agentThinking", "toolchainThinking", "nodeIds", "criteria", "checkMethod", "description",
    "name", "version", "sourceDocument", "sourceSequence", "reviewClass",
}


def _guard(request, project_id, node_ids=None):
    from apps.api import routes as api

    if os.getenv("AICHECK_WORKSTATIONS_ENABLED", "").lower() not in {"true", "1", "yes"}:
        return fail(errors.NOT_FOUND, request)
    role, identity_error = api.effective_role_for_request(request)
    if identity_error:
        return identity_error
    if role != "inspection" or not api.request_user_id(request):
        return fail(errors.FORBIDDEN, request, message="工程规则编辑需要已授权的监检身份。")
    if not repo.require_project(project_id):
        return fail(errors.NOT_FOUND, request)
    return api.member_node_scope_error(request, project_id, role, node_ids=node_ids)


def _body_error(request, body):
    if set(body) - EDITABLE_FIELDS:
        return fail(errors.VALIDATION_ERROR, request, message="请求包含不可编辑的身份、状态或执行字段。")
    if "executionConditions" in body:
        try:
            validate_conditions(body["executionConditions"])
        except (TypeError, ValueError) as exc:
            return fail(errors.VALIDATION_ERROR, request, message=str(exc))
    return None


@project_rule_router.get("/projects/{project_id}/rules/versions")
def list_project_rules(request: Request, project_id: str):
    from apps.api import routes as api

    if error := _guard(request, project_id):
        return error
    project = repo.require_project(project_id)
    items = []
    for rule in repo.state.get("rule_versions", []):
        if rule.get("projectId") not in {None, "", project_id}:
            continue
        if str(rule.get("businessPackId") or api.DEFAULT_BUSINESS_PACK_ID) != str(project.get("businessPackId") or api.DEFAULT_BUSINESS_PACK_ID):
            continue
        if _guard(request, project_id, api.parse_rule_node_ids(rule.get("nodeIds"))) is None:
            items.append(api.versioned_record("rule-version", rule))
    return ok({"items": sorted(items, key=api.rule_version_sort_key), "total": len(items)}, request)


@project_rule_router.post("/projects/{project_id}/rules/versions")
def create_project_rule(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict),
                        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    from apps.api import routes as api

    if error := _body_error(request, body):
        return error
    nodes = api.parse_rule_node_ids(body.get("nodeIds"))
    if error := _guard(request, project_id, nodes):
        return error
    if not nodes:
        return fail(errors.VALIDATION_ERROR, request, message="请选择规则适用节点。")
    project = repo.require_project(project_id)
    return api.create_rule_version(request, {**body, "projectId": project_id,
        "businessPackId": project.get("businessPackId") or api.DEFAULT_BUSINESS_PACK_ID}, idempotency_key)


@project_rule_router.patch("/projects/{project_id}/rules/versions/{version_id}")
def edit_project_rule(request: Request, project_id: str, version_id: str,
                      body: dict[str, Any] = Body(default_factory=dict),
                      idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                      if_match: str | None = Header(default=None, alias="If-Match")):
    from apps.api import routes as api

    if error := _guard(request, project_id):
        return error
    rule = repo.find_one("rule_versions", version_id)
    if not rule or rule.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    if error := _body_error(request, body):
        return error
    nodes = api.parse_rule_node_ids(rule.get("nodeIds")) + api.normalize_business_rule_version_record({**rule, **body})["nodeIds"]
    if error := _guard(request, project_id, nodes):
        return error
    if "nodeIds" in body and not api.parse_rule_node_ids(body["nodeIds"]):
        return fail(errors.VALIDATION_ERROR, request, message="规则必须保留适用节点。")
    if not if_match:
        return fail(errors.VALIDATION_ERROR, request, message="编辑规则需要 If-Match 版本标记。")
    return api.update_rule_version(request, version_id, body, idempotency_key, if_match)


@project_rule_router.post("/projects/{project_id}/rules/versions/{version_id}/fork")
def fork_project_rule(request: Request, project_id: str, version_id: str,
                      body: dict[str, Any] = Body(default_factory=dict),
                      idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    from apps.api import routes as api

    if error := _guard(request, project_id):
        return error
    source = repo.find_one("rule_versions", version_id)
    if not source or source.get("projectId") not in {None, "", project_id}:
        return fail(errors.NOT_FOUND, request)
    if error := _body_error(request, body):
        return error
    nodes = api.parse_rule_node_ids(source.get("nodeIds")) + api.normalize_business_rule_version_record({**source, **body})["nodeIds"]
    if error := _guard(request, project_id, nodes):
        return error
    if "nodeIds" in body and not api.parse_rule_node_ids(body["nodeIds"]):
        return fail(errors.VALIDATION_ERROR, request, message="规则必须保留适用节点。")
    return api.fork_rule_version(request, version_id, {**body, "projectId": project_id}, idempotency_key)


@project_rule_router.post("/projects/{project_id}/rules/versions/{version_id}/trial")
def trial_project_rule(request: Request, project_id: str, version_id: str,
                       body: dict[str, Any] = Body(default_factory=dict)):
    from apps.api import routes as api

    if error := _guard(request, project_id):
        return error
    rule = repo.find_one("rule_versions", version_id)
    if not rule or rule.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    if error := _guard(request, project_id, api.parse_rule_node_ids(rule.get("nodeIds"))):
        return error
    try:
        result = evaluate_conditions(rule.get("executionConditions"), body.get("facts"))
    except (TypeError, ValueError) as exc:
        return fail(errors.VALIDATION_ERROR, request, message=str(exc))
    return ok({"mode": "draft_trial", "advisoryOnly": True, "ruleVersionId": version_id,
               "ruleRevision": rule.get("revision"), "evidenceVerified": False, **result}, request)
