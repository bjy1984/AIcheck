"""平台管理：开通特检院（租户）和它的院管理员——多特检院第二阶段（2026-11-02）。

只有平台管理员能用（平台院的管理员，见 libs.security.auth.is_platform_admin）。各特检院的
院管理员也是 admin，但只管本院；他们调这里一律 403。
独立 router，排在主 router 前面注册；路径用 /platform/，不进 routes.py 的 GET /admin/{kind} 通配。
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Body, Header, Request

from apps.api import routes as api
from libs import institutes
from libs.contracts import errors
from libs.contracts.responses import fail, ok, server_time
from libs.db.repository import flush_state, repo
from libs.name_release import release_username
from libs.security.auth import (
    DEFAULT_INITIAL_PASSWORD,
    hash_password,
    is_platform_admin,
    password_strength_errors,
)
from libs.security.tenant import configured_tenant_id as platform_tenant_id

platform_router = APIRouter()
CODE_RE = re.compile(r"[A-Z0-9][A-Z0-9-]{1,31}")


def _guard(request: Request):
    _, error = api.effective_role_for_request(request)
    if error:
        return error
    if not is_platform_admin(getattr(request.state, "auth_user", None)):
        return fail(errors.FORBIDDEN, request, http_status=403, message="只有平台管理员可以管理特检院。")
    return None


def _institute_view(row: dict[str, Any]) -> dict[str, Any]:
    with institutes.tenant_scope(str(row["id"])) as state:
        users = [user for user in state.get("users") or [] if isinstance(user, dict)]
        projects = len([item for item in state.get("projects") or [] if isinstance(item, dict)])
    return {
        **repo.clone(row),
        "userCount": len(users),
        "adminUsernames": sorted(str(user.get("username")) for user in users if user.get("role") == "admin"),
        "projectCount": projects,
    }


def _add_institute_admin(state: dict[str, Any], username: str, name: str, password: str, org: dict[str, Any] | None,
                         *, audit_action: str) -> dict[str, Any]:
    """在当前院（调用方已切进 tenant_scope）建一个院管理员并落库。"""
    admin = api.build_admin_user_record({"username": username, "role": "admin", "name": name, "password": password}, org=org)
    admin["authVersion"] = max(1, int(admin.get("authVersion") or 0))
    # 平台定的初始密码平台知道：院管理员首次登录必须先改成只有自己知道的
    admin["mustChangePassword"] = True
    state.setdefault("users", []).insert(0, admin)
    api.upsert_admin_config_user(admin)
    repo.add_audit(audit_action, "User", admin["id"])
    flush_state({"users", "audit_logs"}, selected_singleton_keys={"admin_config"})
    return admin


def _institute_or_error(request: Request, tenant_id: str):
    institute = institutes.find_institute(tenant_id)
    if institute is None or institute.get("status") == institutes.DELETED:
        return None, fail(errors.NOT_FOUND, request, message="没有这个特检院（平台院的管理员在「组织用户」里管理）。")
    return institute, None


@platform_router.get("/platform/institutes")
def list_platform_institutes(request: Request):
    if error := _guard(request):
        return error
    platform = {"id": platform_tenant_id(), "code": "PLATFORM", "name": "平台（默认院）", "status": institutes.ACTIVE, "builtin": True}
    rows = [row for row in institutes.list_institutes() if row.get("status") != institutes.DELETED]
    return ok({"items": [_institute_view(platform), *(_institute_view(row) for row in rows)]}, request)


@platform_router.post("/platform/institutes")
def create_platform_institute(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """开通一个特检院，同时建好它的第一个院管理员。"""
    if error := _guard(request):
        return error
    code = str(body.get("code") or "").strip().upper()
    name = " ".join(str(body.get("name") or "").split())[:80]
    username = str(body.get("adminUsername") or "").strip()
    if not CODE_RE.fullmatch(code):
        return fail(errors.VALIDATION_ERROR, request, message="单位代码用 2–32 位大写字母、数字或连字符，例如 GDTJ。")
    if not name or not username:
        return fail(errors.VALIDATION_ERROR, request, message="请填写特检院名称和院管理员用户名。")
    # 单位代码只在「没删除的院」里唯一（2026-11-04 用户：删了的院代码要能再用）。删过的院数据还在
    # 原分区里，新院另开一个分区（TENANT-QDTJ-2……），旧数据和审计记录不会被新院接手
    existing = institutes.list_institutes()
    if code == "PLATFORM" or any(str(row.get("code") or "").upper() == code and row.get("status") != institutes.DELETED
                                 for row in existing):
        return fail(errors.CONFLICT, request, http_status=409, message="这个单位代码已经用过了。")
    taken = {str(row.get("id")) for row in existing} | {platform_tenant_id()}
    tenant_id, suffix = f"TENANT-{code}", 1
    while tenant_id in taken:
        suffix += 1
        tenant_id = f"TENANT-{code}-{suffix}"
    if conflict := institutes.username_conflict_message(username, for_tenant=tenant_id):
        return fail(errors.CONFLICT, request, http_status=409, message=conflict)
    password = str(body.get("adminPassword") or "").strip() or DEFAULT_INITIAL_PASSWORD
    if problems := password_strength_errors(username, password):
        return fail(errors.VALIDATION_ERROR, request, message="初始密码不符合要求。", data={"problems": problems})

    def produce():
        actor = api.request_actor_name(request)
        institute = {"id": tenant_id, "code": code, "name": name, "status": institutes.ACTIVE,
                     "createdAt": server_time(), "createdBy": actor}
        with institutes.tenant_scope(tenant_id) as state:
            # 特检院本身就是监检单位：先建好以院命名的监检组织，院管理员马上就能给监检人员建号
            # （监检等业务角色必须绑定组织，新院原来一个组织都没有）
            org = {"id": f"ORG-{code}", "name": name, "type": "inspection", "contactName": "", "contactPhone": "",
                   "status": "启用", "projectCount": 0, "updatedAt": server_time(), "revision": 1}
            api.admin_org_units().insert(0, org)
            _add_institute_admin(state, username, str(body.get("adminName") or username), password, org,
                                 audit_action="平台开通特检院并建院管理员")
        with institutes.platform_scope() as state:
            state.setdefault(institutes.INSTITUTES, []).append(institute)
            institutes.save_in_current_tenant(institutes.INSTITUTES, institute)
        institutes.register_username(username, tenant_id)
        # 新院一开通就带上平台的通用规则，否则复核找不到已发布的规则
        rules = institutes.sync_platform_rules(tenant_id)
        audit_id = repo.add_audit("开通特检院", "Institute", tenant_id, after={"name": name, "admin": username, "rules": rules})
        request.state.scoped_flush_records = dict  # 只落本次审计；院、账号、目录上面已各自落库
        return ok({"institute": _institute_view(institute), "auditLogId": audit_id}, request)

    return api.idempotent(request, idempotency_key, produce, fingerprint_source={"body": body})


@platform_router.post("/platform/institutes/{tenant_id}/status")
def set_platform_institute_status(
    request: Request,
    tenant_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """停用后这个院的人立即登不进来（已发的令牌也失效），数据保留；启用即恢复。"""
    if error := _guard(request):
        return error
    status = str(body.get("status") or "")
    if status not in {institutes.ACTIVE, institutes.DISABLED}:
        return fail(errors.VALIDATION_ERROR, request, message="状态只能是 active 或 disabled。")
    def produce():
        with institutes.platform_scope() as state:
            row = next((item for item in state.setdefault(institutes.INSTITUTES, []) if item.get("id") == tenant_id), None)
            if row is None or row.get("status") == institutes.DELETED:
                return fail(errors.NOT_FOUND, request, message="没有这个特检院（平台院不能停用）。")
            before = row.get("status")
            row.update({"status": status, "updatedAt": server_time(), "updatedBy": api.request_actor_name(request)})
            institutes.save_in_current_tenant(institutes.INSTITUTES, row)
            view = repo.clone(row)
        audit_id = repo.add_audit("修改特检院状态", "Institute", tenant_id, before={"status": before}, after={"status": status})
        request.state.scoped_flush_records = dict
        return ok({"institute": view, "auditLogId": audit_id}, request)

    return api.idempotent(request, idempotency_key, produce, fingerprint_source={"tenantId": tenant_id, "body": body})


@platform_router.post("/platform/institutes/sync-rules")
def sync_platform_rules_to_institutes(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """平台改了通用规则后，把最新版同步到所有特检院（各院自己的项目规则不动）。"""
    if error := _guard(request):
        return error

    def produce():
        # 删除的院不再同步：没人能登录，白写一遍规则（2026-11-04 线上同步时连删除的 6 个院也同步了）
        results = {row["id"]: institutes.sync_platform_rules(str(row["id"]))
                   for row in institutes.list_institutes() if row.get("status") != institutes.DELETED}
        audit_id = repo.add_audit("同步平台规则到各特检院", "Institute", "ALL", after=results)
        request.state.scoped_flush_records = dict
        return ok({"results": results, "auditLogId": audit_id}, request)

    return api.idempotent(request, idempotency_key, produce, fingerprint_source={"body": body})


@platform_router.post("/platform/institutes/{tenant_id}/admins")
def add_platform_institute_admin(
    request: Request,
    tenant_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """给特检院再加一个院管理员（原来只能在开通时建一个）。"""
    if error := _guard(request):
        return error
    institute, error = _institute_or_error(request, tenant_id)
    if error:
        return error
    username = str(body.get("username") or "").strip()
    if not username:
        return fail(errors.VALIDATION_ERROR, request, message="请填写院管理员用户名。")
    if conflict := institutes.username_conflict_message(username, for_tenant=tenant_id):
        return fail(errors.CONFLICT, request, http_status=409, message=conflict)
    password = str(body.get("password") or "").strip() or DEFAULT_INITIAL_PASSWORD
    if problems := password_strength_errors(username, password):
        return fail(errors.VALIDATION_ERROR, request, message="初始密码不符合要求。", data={"problems": problems})

    def produce():
        with institutes.tenant_scope(tenant_id) as state:
            if any(str(user.get("username")) == username for user in state.get("users") or []):
                return fail(errors.CONFLICT, request, http_status=409, message="该院已有这个用户名。")
            org = next((item for item in api.admin_org_units() if item.get("id") == f"ORG-{institute['code']}"), None)
            admin = _add_institute_admin(state, username, str(body.get("name") or username), password, org,
                                         audit_action="平台为特检院新增院管理员")
        institutes.register_username(username, tenant_id)
        audit_id = repo.add_audit("新增院管理员", "Institute", tenant_id, after={"admin": username})
        request.state.scoped_flush_records = dict
        return ok({"admin": {"username": admin["username"], "name": admin.get("name")}, "auditLogId": audit_id}, request)

    return api.idempotent(request, idempotency_key, produce, fingerprint_source={"tenantId": tenant_id, "body": body})


@platform_router.post("/platform/institutes/{tenant_id}/admins/{username}/reset-password")
def reset_platform_institute_admin_password(
    request: Request,
    tenant_id: str,
    username: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """院管理员忘了密码：平台重置成新的初始密码，下次登录必须先改；已登录的会话立即失效。"""
    if error := _guard(request):
        return error
    _, error = _institute_or_error(request, tenant_id)
    if error:
        return error
    password = str(body.get("password") or "").strip() or DEFAULT_INITIAL_PASSWORD
    if problems := password_strength_errors(username, password):
        return fail(errors.VALIDATION_ERROR, request, message="新密码不符合要求。", data={"problems": problems})

    def produce():
        with institutes.tenant_scope(tenant_id) as state:
            user = next((item for item in state.get("users") or []
                         if str(item.get("username")) == username and item.get("role") == "admin"), None)
            if user is None:
                return fail(errors.NOT_FOUND, request, message="该院没有这个院管理员。")
            user["passwordHash"] = hash_password(password)
            user.pop("password", None)
            user["mustChangePassword"] = True
            # 版本号加一：旧令牌里的 ver 对不上，已登录的会话立即失效
            user["authVersion"] = int(user.get("authVersion") or 0) + 1
            user["updatedAt"] = server_time()
            repo.add_audit("平台重置院管理员密码", "User", str(user.get("id")))
            flush_state({"users", "audit_logs"}, selected_singleton_keys=set())
        audit_id = repo.add_audit("重置院管理员密码", "Institute", tenant_id, after={"admin": username})
        request.state.scoped_flush_records = dict
        return ok({"username": username, "mustChangePassword": True, "auditLogId": audit_id}, request)

    return api.idempotent(request, idempotency_key, produce,
                          fingerprint_source={"tenantId": tenant_id, "username": username, "body": body})


@platform_router.delete("/platform/institutes/{tenant_id}")
def delete_platform_institute(
    request: Request,
    tenant_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """删除没有项目的特检院（2026-11-04 用户：开通错了、测试建的院删不掉）。

    只做「停用 + 从列表隐藏 + 让出院内用户名」，数据和审计记录都留在库里：审计是哈希链，
    不能删。还有项目的院只能停用。单位代码可以给新开的院再用，新院另开数据分区。
    """
    if error := _guard(request):
        return error
    institute, error = _institute_or_error(request, tenant_id)
    if error:
        return error
    if _institute_view(institute)["projectCount"]:
        return fail(errors.CONFLICT, request, http_status=409, message="这个特检院已有项目，不能删除，只能停用。")

    def produce():
        released: list[str] = []
        with institutes.tenant_scope(tenant_id) as state:
            for user in state.get("users") or []:
                if not isinstance(user, dict):
                    continue
                user.update({"status": "停用", "deletedAt": server_time(), "updatedAt": server_time()})
                # 版本号加一：已发的令牌立即失效
                user["authVersion"] = int(user.get("authVersion") or 0) + 1
                if original := release_username(user):
                    released.append(original)
                api.upsert_admin_config_user(user)
            repo.add_audit("平台删除特检院：停用并让出院内用户名", "Institute", tenant_id, after={"released": released})
            flush_state({"users", "audit_logs"}, selected_singleton_keys={"admin_config"})
        for username in released:
            institutes.unregister_username(username, tenant_id)
        with institutes.platform_scope() as state:
            row = next(item for item in state.setdefault(institutes.INSTITUTES, []) if item.get("id") == tenant_id)
            row.update({"status": institutes.DELETED, "deletedAt": server_time(), "updatedBy": api.request_actor_name(request)})
            institutes.save_in_current_tenant(institutes.INSTITUTES, row)
        audit_id = repo.add_audit("删除特检院", "Institute", tenant_id, after={"releasedUsernames": released})
        request.state.scoped_flush_records = dict
        return ok({"deleted": True, "tenantId": tenant_id, "releasedUsernames": released, "auditLogId": audit_id}, request)

    return api.idempotent(request, idempotency_key, produce, fingerprint_source={"tenantId": tenant_id, "delete": True})
