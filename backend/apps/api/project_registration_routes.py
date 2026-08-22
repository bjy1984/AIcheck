"""按项目生成注册链接 → 自选角色注册 → 项目负责人后台审核。

    「根据项目生成注册链接 - 用户通过链接进去选择角色注册 -
      项目负责人在后台审核通过」

## 和上一版组织邀请的三处差别

| | 上一版（组织邀请） | 这一版（项目注册） |
|---|---|---|
| 链接绑什么 | 组织 + 角色 | **项目**，不绑角色 |
| 角色谁定 | 邀请人写死 | **注册者自选** |
| 生效时机 | 提交即建账号 | **审核通过才建账号** |

上一版把角色写死，理由是「自选角色的链接等于公开提权入口」。
**加了审核这一关之后这个理由不成立了**：审核才是闸门，自选只是填表。

## 但这带来一条新的硬要求

**待审期间绝不能存在可用账号。**

所以这里不走「先建用户再标 pending」——那种做法一旦哪个查询忘了过滤
pending，人就登进来了，而且不会报错。这里根本不建 user 记录：
申请只是一条 registration_requests，批准的那一刻才创建用户。
没有账号，就没有「忘了过滤」的可能。

## 链接是多次可用的

一个项目发一个链接给一群人，这是这个流程的意义。所以不能沿用
「单次有效」——但也不能就此无限制：

- 有效期照旧（过期即废）
- 有使用次数上限（防止链接外流后被灌注册）
- 可以随时停用

真正的闸门是审核，链接只是入口。
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

from fastapi import APIRouter, Body, Header, Request

from libs.contracts import errors
from libs.contracts.responses import fail, ok, server_time
from libs.db.repository import repo

project_registration_router = APIRouter()

# 注册者能自选的角色。admin / fde 不在里面——审核人也无权在这里造管理员。
SELECTABLE_ROLES = ("inspection", "contractor", "ndt", "owner")

INVITE_TTL_HOURS = 168  # 7 天：项目级链接要发给一群人，比组织邀请长一些
MAX_USES = 200  # 链接外流后被灌注册的上限

INVITES = "project_invitations"
REQUESTS = "registration_requests"
ROLE_ORG_FIELDS = {
    "inspection": "inspectionOrgName",
    "contractor": "contractorOrgName",
    "ndt": "ndtOrgName",
    "owner": "ownerOrgName",
}
_REGISTRATION_IDENTITY_LOCK = Lock()


def _now() -> datetime:
    return datetime.now(UTC)


def _actor(request: Request) -> dict[str, Any] | None:
    auth = getattr(request.state, "auth", None) or {}
    username = auth.get("sub") or auth.get("username")
    if not username:
        return None
    return next(
        (u for u in repo.state.get("users", []) if str(u.get("username")) == str(username)), None
    )


def can_manage_project_registration(user: dict[str, Any] | None, project_id: str) -> bool:
    """谁能发链接、谁能审核。

    admin，或者这个项目的成员里被标了负责人的人。
    **不看全局的 isOrgLeader**：那是组织层的身份，和「这个项目的负责人」
    不是一回事——甲公司的负责人不该能审乙项目的注册。
    """
    if not user:
        return False
    if str(user.get("role")) == "admin":
        return True
    return any(
        str(member.get("projectId")) == str(project_id)
        and str(member.get("userId")) == str(user.get("id"))
        and bool(member.get("isProjectLeader"))
        for member in repo.state.get("project_members", [])
    )


def _guard(request: Request, project_id: str):
    actor = _actor(request)
    if not actor:
        return None, fail(errors.UNAUTHORIZED, request, http_status=401)
    if not can_manage_project_registration(actor, project_id):
        return None, fail(
            errors.FORBIDDEN, request, http_status=403, message="只有项目负责人可以操作。"
        )
    return actor, None


def _registration_flush_records(
    *,
    invite: dict[str, Any] | None = None,
    registration_request: dict[str, Any] | None = None,
    user: dict[str, Any] | None = None,
    member: dict[str, Any] | None = None,
    admin_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for state_key, item in (
        (INVITES, invite),
        (REQUESTS, registration_request),
        ("users", user),
        ("project_members", member),
    ):
        if item is not None:
            records[state_key] = [item]
    if admin_config is not None:
        records["admin_config"] = admin_config
    return records


# --------------------------------------------------------------------------
# 一、项目负责人生成注册链接
# --------------------------------------------------------------------------


@project_registration_router.post("/projects/{project_id}/registration-links")
def create_registration_link(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    from apps.api.routes import idempotent

    actor, error = _guard(request, project_id)
    if error:
        return error
    if not repo.require_project(project_id):
        return fail(errors.NOT_FOUND, request)

    def produce():
        token = secrets.token_urlsafe(24)
        invite = {
            "id": f"PINV-{secrets.token_hex(8).upper()}",
            "token": token,
            "projectId": project_id,
            "createdBy": actor.get("id"),
            "createdAt": server_time(),
            "expiresAt": (_now() + timedelta(hours=INVITE_TTL_HOURS)).isoformat(),
            "maxUses": int(body.get("maxUses") or MAX_USES),
            "useCount": 0,
            "disabled": False,
        }
        repo.state.setdefault(INVITES, []).insert(0, invite)
        repo.add_audit("创建项目注册链接", "ProjectInvitation", token[:8], result="成功")
        request.state.scoped_flush_records = lambda: _registration_flush_records(invite=invite)
        return ok(
            {
                "token": token,
                "projectId": project_id,
                "expiresAt": invite["expiresAt"],
                "maxUses": invite["maxUses"],
                "selectableRoles": list(SELECTABLE_ROLES),
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@project_registration_router.post("/projects/{project_id}/registration-links/{token}/disable")
def disable_registration_link(
    request: Request,
    project_id: str,
    token: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """停用链接。发出去的东西必须能收回来。"""
    from apps.api.routes import idempotent

    _, error = _guard(request, project_id)
    if error:
        return error
    invite = next(
        (
            i
            for i in repo.state.get(INVITES, [])
            if str(i.get("token")) == token and str(i.get("projectId")) == project_id
        ),
        None,
    )
    if not invite:
        return fail(errors.NOT_FOUND, request, message="链接不存在。")

    def produce():
        invite["disabled"] = True
        repo.add_audit("停用项目注册链接", "ProjectInvitation", token[:8], result="成功")
        request.state.scoped_flush_records = lambda: _registration_flush_records(invite=invite)
        return ok({"token": token, "disabled": True}, request)

    return idempotent(request, idempotency_key, produce)


# --------------------------------------------------------------------------
# 二、注册者：看链接、选角色、提交申请
# --------------------------------------------------------------------------


def _invite_usable(invite: dict[str, Any] | None) -> bool:
    """能不能用。**对外只回一句笼统的话**——区分「不存在」「已停用」「已过期」
    「用完了」等于给撞令牌的人送反馈。"""
    if not invite or invite.get("disabled"):
        return False
    if int(invite.get("useCount") or 0) >= int(invite.get("maxUses") or MAX_USES):
        return False
    try:
        return datetime.fromisoformat(str(invite.get("expiresAt"))) > _now()
    except ValueError:
        return False


def _find_invite(token: str) -> dict[str, Any] | None:
    return next(
        (i for i in repo.state.get(INVITES, []) if str(i.get("token")) == str(token)), None
    )


@project_registration_router.get("/registration-links/{token}")
def inspect_registration_link(request: Request, token: str):
    """注册页用它显示「你要加入哪个项目」和可选角色。不需要登录。"""
    invite = _find_invite(token)
    if not _invite_usable(invite):
        return fail(errors.NOT_FOUND, request, message="注册链接无效或已过期。")
    project = repo.require_project(str(invite["projectId"]))
    return ok(
        {
            "projectId": invite["projectId"],
            "projectName": (project or {}).get("name") or "",
            # 角色由注册者自选——审核才是闸门
            "selectableRoles": list(SELECTABLE_ROLES),
            "expiresAt": invite["expiresAt"],
        },
        request,
    )


@project_registration_router.post("/registration-links/{token}/apply")
def submit_registration(request: Request, token: str, body: dict[str, Any] = Body(default_factory=dict)):
    with _REGISTRATION_IDENTITY_LOCK:
        return _submit_registration_locked(request, token, body)


def _submit_registration_locked(request: Request, token: str, body: dict[str, Any]):
    """提交注册申请。**不建用户**——批准的那一刻才建。

    先建用户再标 pending 的话，只要哪个查询忘了过滤 pending，人就登进来了，
    而且不会报错。没有账号，就没有「忘了过滤」的可能。
    """
    from apps.api.routes import password_strength_errors

    invite = _find_invite(token)
    if not _invite_usable(invite):
        return fail(errors.NOT_FOUND, request, message="注册链接无效或已过期。")

    username = str(body.get("username") or "").strip()
    role = str(body.get("role") or "").strip()
    password = str(body.get("password") or "")

    if not username:
        return fail(errors.VALIDATION_ERROR, request, message="用户名不能为空。")
    if role not in SELECTABLE_ROLES:
        # 不在可选名单里的一律拒——包括 admin/fde
        return fail(errors.VALIDATION_ERROR, request, message="所选角色不可用。")
    problems = password_strength_errors(username, password)
    if problems:
        return fail(
            errors.VALIDATION_ERROR,
            request,
            message="口令不符合安全要求。",
            data={"field": "password", "problems": problems},
        )
    if any(str(u.get("username")) == username for u in repo.state.get("users", [])):
        return fail(errors.CONFLICT, request, http_status=409, message="该用户名已存在。")
    if any(
        str(r.get("username")) == username and str(r.get("status")) == "待审核"
        for r in repo.state.get(REQUESTS, [])
    ):
        return fail(errors.CONFLICT, request, http_status=409, message="该用户名已有待审核的申请。")

    from libs.security.auth import hash_password

    record = {
        "id": f"REG-{secrets.token_hex(4).upper()}",
        "projectId": invite["projectId"],
        "username": username,
        "displayName": str(body.get("displayName") or username),
        "mobile": str(body.get("mobile") or ""),
        "role": role,
        # 口令在申请阶段就定好并**只存哈希**：批准时直接建账号，
        # 不用再让申请人设一次，也不用由审核人代设——
        # 代设意味着审核人知道别人的口令。
        "passwordHash": hash_password(password),
        "status": "待审核",
        "createdAt": server_time(),
        "reviewedAt": None,
        "reviewedBy": None,
        "rejectReason": "",
    }
    repo.state.setdefault(REQUESTS, []).insert(0, record)
    invite["useCount"] = int(invite.get("useCount") or 0) + 1
    repo.add_audit("提交项目注册申请", "RegistrationRequest", record["id"], result="成功")
    request.state.scoped_flush_records = lambda: _registration_flush_records(
        invite=invite, registration_request=record
    )
    # 不回任何令牌：账号还不存在，现在还不能登录
    return ok(
        {"requestId": record["id"], "status": record["status"], "message": "已提交，等待项目负责人审核。"},
        request,
    )


# --------------------------------------------------------------------------
# 三、项目负责人审核
# --------------------------------------------------------------------------


@project_registration_router.get("/projects/{project_id}/registration-requests")
def list_registration_requests(request: Request, project_id: str, status: str | None = None):
    _, error = _guard(request, project_id)
    if error:
        return error
    items = [
        {k: v for k, v in item.items() if k != "passwordHash"}  # 哈希不出接口
        for item in repo.state.get(REQUESTS, [])
        if str(item.get("projectId")) == str(project_id)
        and (not status or str(item.get("status")) == status)
    ]
    return ok({"items": items, "total": len(items)}, request)


@project_registration_router.post(
    "/projects/{project_id}/registration-requests/{request_id}/review"
)
def review_registration_request(
    request: Request,
    project_id: str,
    request_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    with _REGISTRATION_IDENTITY_LOCK:
        return _review_registration_request_locked(
            request,
            project_id,
            request_id,
            body,
            idempotency_key,
        )


def _review_registration_request_locked(
    request: Request,
    project_id: str,
    request_id: str,
    body: dict[str, Any],
    idempotency_key: str | None,
):
    """通过或拒绝。通过时才真正创建账号。"""
    from apps.api.routes import (
        build_admin_user_record,
        find_org_unit,
        idempotent,
        resolve_project_member_grant,
        upsert_admin_config_user,
    )

    actor, error = _guard(request, project_id)
    if error:
        return error

    record = next(
        (
            item
            for item in repo.state.get(REQUESTS, [])
            if str(item.get("id")) == request_id and str(item.get("projectId")) == str(project_id)
        ),
        None,
    )
    if not record:
        return fail(errors.NOT_FOUND, request, message="申请不存在。")
    if str(record.get("status")) != "待审核":
        # 已经处理过的不许再处理一次：重复审批会重复建账号
        return fail(
            errors.CONFLICT, request, http_status=409, message=f"该申请已{record.get('status')}。"
        )

    approved = bool(body.get("approved"))
    reason = str(body.get("reason") or "").strip()
    if not approved and not reason:
        # 拒绝必须写理由。不写的话申请人只看到「被拒了」，不知道要改什么
        return fail(errors.VALIDATION_ERROR, request, message="拒绝时必须填写理由。")

    project = repo.require_project(project_id) or {}
    org_name = str(project.get(ROLE_ORG_FIELDS[record["role"]]) or "").strip()
    org = find_org_unit(None, org_name) if org_name else None
    if approved and not org:
        return fail(
            errors.VALIDATION_ERROR,
            request,
            message="项目未配置该注册角色对应的组织。",
        )
    if approved and any(
        str(item.get("username")) == str(record["username"])
        for item in repo.state.get("users", [])
    ):
        return fail(
            errors.CONFLICT,
            request,
            http_status=409,
            message="该用户名已创建账号。",
        )

    def produce():
        if not approved:
            record.update(
                {
                    "status": "已拒绝",
                    "reviewedAt": server_time(),
                    "reviewedBy": actor.get("id"),
                    "rejectReason": reason,
                }
            )
            repo.add_audit("拒绝注册申请", "RegistrationRequest", request_id, result="成功")
            request.state.scoped_flush_records = lambda: _registration_flush_records(
                registration_request=record
            )
            return ok({"requestId": request_id, "status": "已拒绝"}, request)

        user = build_admin_user_record(
            {
                "username": record["username"],
                "role": record["role"],
                "name": record["displayName"],
                "mobile": record.get("mobile") or "",
                "orgName": org_name,
            },
            org=org,
        )
        # 口令沿用申请时定的那个：审核人不该知道、也不该代设别人的口令
        user["passwordHash"] = record["passwordHash"]
        user["authVersion"] = 1
        user["mustChangePassword"] = False
        if any(
            str(item.get("projectId")) == str(project_id)
            and str(item.get("userId")) == str(user["id"])
            for item in repo.state.get("project_members", [])
        ):
            return fail(
                errors.CONFLICT,
                request,
                http_status=409,
                message="该用户已是项目成员。",
            )
        repo.state["users"].insert(0, user)
        upsert_admin_config_user(user)
        # 建账号的同时把他加进项目成员，否则批准了却进不了这个项目
        grant = resolve_project_member_grant(project_id, record["role"])
        member = {
            "id": f"PM-{secrets.token_hex(4).upper()}",
            "projectId": project_id,
            "userId": user["id"],
            "name": record["displayName"],
            "orgId": org["id"],
            "orgName": org_name,
            "role": record["role"],
            "nodeScope": grant["nodeScope"],
            "actions": grant["actions"],
            "status": "启用",
            "isProjectLeader": False,
            "updatedAt": server_time(),
            "revision": 1,
        }
        repo.state.setdefault("project_members", []).insert(0, member)
        record.update(
            {"status": "已通过", "reviewedAt": server_time(), "reviewedBy": actor.get("id")}
        )
        repo.add_audit("通过注册申请", "RegistrationRequest", request_id, result="成功")
        request.state.scoped_flush_records = lambda: _registration_flush_records(
            registration_request=record,
            user=user,
            member=member,
            admin_config=repo.state["admin_config"],
        )
        return ok({"requestId": request_id, "status": "已通过", "userId": user["id"]}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)
