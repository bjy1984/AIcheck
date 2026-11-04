"""院级审查口径开关接口（2026-11-04，意见反馈审批方案第二阶段）。逻辑在 libs/review_policies.py。

- 院管理员：GET /admin/review-policies 看本院每个开关的生效值和来源；PUT …/{key} 改本院的选择（null = 跟随平台默认）
- 平台管理员：同一页多看各院怎么选的分布；PUT /platform/review-policy-defaults/{key} 改平台默认值

值存在各院的 admin_config 单例里（reviewPolicies / 平台院 reviewPolicyDefaults）：单例每次加载都会读，
审查时 libs/review_policies 还会直接从库里读，worker 内存旧了也不会按旧口径判。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, Request

from apps.api import routes as api
from apps.api.platform_routes import _guard
from libs import institutes
from libs import review_policies as rp
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.repository import repo
from libs.security.auth import is_platform_admin

review_policy_router = APIRouter()


def platform_guard(request: Request):
    return _guard(request, "只有平台管理员可以改平台默认口径。")


def _config(state: dict[str, Any]) -> dict[str, Any]:
    config = state.get("admin_config")
    if not isinstance(config, dict):
        config = {}
        state["admin_config"] = config
    return config


def _platform_defaults() -> dict[str, Any]:
    with institutes.platform_scope() as state:
        return dict(_config(state).get("reviewPolicyDefaults") or {})


def _adoption(platform_defaults: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """各院（含平台院）每个开关的生效值分布：多数院选同一种时，平台可以把它升级成默认值。"""
    tenants = [(institutes.platform_tenant_id(), "平台（默认院）")] + [
        (str(row.get("id")), str(row.get("name") or row.get("id")))
        for row in institutes.list_institutes() if row.get("status") != institutes.DELETED
    ]
    adoption = {key: {value: [] for value in rp.options_for(key)} for key in rp.POLICIES}
    for tenant_id, name in tenants:
        # 直接读库里那一行（2026-11-04 审计：原来为读一行把每个院整院加载进内存）
        choices = rp.admin_config_for(tenant_id).get("reviewPolicies")
        for key, item in rp.resolve(choices, platform_defaults).items():
            adoption[key].setdefault(item["value"], []).append({"name": name, "source": item["source"]})
    return adoption


@review_policy_router.get("/admin/review-policies")
def list_review_policies(request: Request):
    actor_role, error = api.effective_role_for_request(request)
    if error:
        return error
    if actor_role != "admin":
        return fail(errors.FORBIDDEN, request, message="只有管理员可以查看审查口径。", http_status=403)
    tenant_choices = dict(_config(repo.state).get("reviewPolicies") or {})
    platform_defaults = _platform_defaults()
    resolved = rp.resolve(tenant_choices, platform_defaults)
    platform_admin = is_platform_admin(getattr(request.state, "auth_user", None))
    adoption = _adoption(platform_defaults) if platform_admin else None
    items = [
        {
            "key": key,
            "label": spec["label"],
            "description": spec["description"],
            "appliesTo": spec["appliesTo"],
            "options": [{"value": value, "label": label} for value, label in spec["options"].items()],
            "codeDefault": spec["default"],
            "platformDefault": platform_defaults.get(key) if rp.valid_value(key, platform_defaults.get(key)) else None,
            "instituteValue": tenant_choices.get(key) if rp.valid_value(key, tenant_choices.get(key)) else None,
            "effective": resolved[key],
            **({"adoption": adoption[key]} if adoption else {}),
        }
        for key, spec in rp.POLICIES.items()
    ]
    return ok({"items": items, "platformAdmin": platform_admin}, request)


def _set(request: Request, key: str, body: dict[str, Any], *, field: str, audit_action: str):
    if key not in rp.POLICIES:
        return fail(errors.NOT_FOUND, request, message="没有这个口径开关。")
    value = body.get("value")
    if value is not None and not rp.valid_value(key, value):
        return fail(errors.VALIDATION_ERROR, request, message="这个开关不支持该选项（选项里没有「符合」）。",
                    data={"allowed": sorted(rp.options_for(key))})
    config = _config(repo.state)
    before = dict(config.get(field) or {})
    choices = dict(before)
    if value is None:
        choices.pop(key, None)
    else:
        choices[key] = value
    config[field] = choices
    api.bump_singleton_revision(config)
    request.state.flush_state_keys = {"audit_logs"}
    request.state.flush_singleton_keys = {"admin_config"}
    # 平台默认变了影响所有院：整个缓存都清；本院的选择只清本院
    rp.invalidate(None if field == "reviewPolicyDefaults" else api.request_tenant_id(request))
    audit_id = repo.add_audit(audit_action, "ReviewPolicy", key, before={key: before.get(key)}, after={key: value})
    return ok({"key": key, "value": value, "auditLogId": audit_id}, request)


@review_policy_router.put("/admin/review-policies/{key}")
def set_institute_review_policy(request: Request, key: str, body: dict[str, Any] = Body(default_factory=dict),
                                idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    actor_role, error = api.effective_role_for_request(request)
    if error:
        return error
    if actor_role != "admin":
        return fail(errors.FORBIDDEN, request, message="只有管理员可以改审查口径。", http_status=403)
    return api.idempotent(request, idempotency_key,
                          lambda: _set(request, key, body, field="reviewPolicies", audit_action="修改本院审查口径"),
                          fingerprint_source={"key": key, "body": body})


@review_policy_router.put("/platform/review-policy-defaults/{key}")
def set_platform_review_policy_default(request: Request, key: str, body: dict[str, Any] = Body(default_factory=dict),
                                       idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if error := platform_guard(request):
        return error
    return api.idempotent(request, idempotency_key,
                          lambda: _set(request, key, body, field="reviewPolicyDefaults", audit_action="修改平台默认审查口径"),
                          fingerprint_source={"key": key, "body": body})
