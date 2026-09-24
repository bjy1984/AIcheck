"""審查插件（Jev 等）：列出可選插件，並按工程開關。

開關會決定本工程之後新建的審查要不要把 OCR 送到外部模型，所以只許系統管理員操作；
已建立的審查按建立時凍結的快照執行，不受影響。插件只做加強，不改結論。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, Request

from apps.api import routes as api
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.review_plugins import plugin_catalog
from libs.review_plugins.settings import validated_plugin_settings

review_plugin_router = APIRouter()


@review_plugin_router.get("/review-plugins")
def list_review_plugins(request: Request):
    """可選的審查插件，以及本部署能不能用（只有布林值，不含金鑰或內部設定）。"""
    return ok({"items": plugin_catalog()}, request)


@review_plugin_router.put("/projects/{project_id}/review-plugins")
def update_project_review_plugins(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = api.mutation_guard(request, project_id, x_role=x_role, if_match=if_match)
        if guard:
            return guard
        role, _identity_error = api.effective_role_for_request(request, x_role)
        if role != "admin":
            return fail(errors.FORBIDDEN, request, message="只有系统管理员能为工程开关审查插件（涉及资料外发）。")
        project = api.repo.require_project(project_id)
        try:
            plugins = {**(project.get("reviewPlugins") or {}), **validated_plugin_settings(body.get("reviewPlugins"))}
        except ValueError as exc:
            return fail(errors.VALIDATION_ERROR, request, message=str(exc))
        changed = []
        if plugins != project.get("reviewPlugins"):
            changed.append({"field": "reviewPlugins", "before": project.get("reviewPlugins"), "after": plugins})
            project["reviewPlugins"] = plugins
            api.repo.touch_project(project_id)
        return ok({"project": api.versioned_project(project),
                   **api.repo.mutation_result("开关审查插件", "Project", project_id, changed=changed)}, request)

    return api.idempotent(request, idempotency_key, produce, fingerprint_source={"projectId": project_id, "body": body})
