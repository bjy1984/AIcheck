"""Shared rule write validation, including platform and rollback entry points."""
from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from libs.contracts import errors
from libs.contracts.responses import fail
from libs.db.repository import repo
from libs.rule_condition_bindings import compile_condition_bindings
from libs.rule_conditions import validate_conditions


def rule_project_mutation_error(request: Request, rule: dict[str, Any], *, publishing: bool = False) -> JSONResponse | None:
    from apps.api import routes as api

    project_id = rule.get("projectId")
    if project_id:
        if not isinstance(project_id, str):
            return fail(errors.VALIDATION_ERROR, request, message="工程 ID 必须是字符串。")
        project = repo.require_project(project_id)
        if not project:
            return fail(errors.NOT_FOUND, request)
        if project.get("status") == "已归档":
            return fail(errors.ARCHIVED_READONLY, request)
        role, identity_error = api.effective_role_for_request(request)
        if identity_error:
            return identity_error
        if scope_error := api.member_node_scope_error(request, project_id, role, node_ids=api.parse_rule_node_ids(rule.get("nodeIds"))):
            return scope_error
        if str(rule.get("businessPackId") or api.DEFAULT_BUSINESS_PACK_ID) != str(project.get("businessPackId") or api.DEFAULT_BUSINESS_PACK_ID):
            return fail(errors.VALIDATION_ERROR, request, message="规则业务包必须与工程一致。")
    # Platform access remains governed by knowledge:manage middleware.
    conditions = rule.get("executionConditions")
    if conditions is not None:
        try:
            validate_conditions(conditions)
            if any("atomicCheckId" in check for check in conditions["checks"]):
                project = repo.require_project(project_id) if project_id else {}
                pack = (project or {}).get("businessPackSnapshot") or api.load_business_pack(rule.get("businessPackId") or api.DEFAULT_BUSINESS_PACK_ID)
                compile_condition_bindings({**rule, "businessPackId": rule.get("businessPackId") or api.DEFAULT_BUSINESS_PACK_ID}, pack)
        except (TypeError, ValueError) as exc:
            return fail(errors.VALIDATION_ERROR, request, message=f"判定条件无效：{exc}")
        if publishing:
            return fail(errors.VALIDATION_ERROR, request,
                        message="结构化条件尚未接入正式判定工具，当前仅支持草稿试跑，不能发布或回滚为生效规则。")
    return None
