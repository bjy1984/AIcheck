"""组织内的邀请注册与权限下放（0817 第 4、5 条）。

    「4、邀请链接注册」
    「5、各个组织内的负责人。拥有权限分配」

## 这是本轮唯一有安全后果的改动

前面几条改错了最多是显示不对、判定不准。**这一条改错了是越权**：
A 组织的负责人能改到 B 组织的人，或者把自己提成系统管理员。
所以护栏写死在服务端，并且每条都有反向用例——
「能做什么」好验，「不能做什么」不验就等于没有。

四条硬规则：

1. **只能动同组织的人。** 跨组织一律 403，不管请求里写了什么。
2. **不能授出 admin / fde。** 否则「组织内的权限分配」就变成了提权通道。
3. **不能改自己。** 自己给自己升权是所有越权里最常见的一种。
4. **邀请链接单次有效、会过期、绑死组织和角色。** 链接会被转发、被截图、
   被贴进群里——它必须是「一次性的、只能干一件事的」东西。

## 为什么不做成通用的权限模型改造

那需要把所有按角色过滤数据的地方都改成按「角色 + 组织」，漏一处就是
跨组织读到别人的数据。这里只开一个**受限的下放口**：负责人在自己组织内
改成员角色，其余判权路径一律不动。范围小，才检查得完。
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, Header, Request

from libs.contracts import errors
from libs.contracts.responses import fail, ok, server_time
from libs.db.repository import repo

org_delegation_router = APIRouter()

# 组织负责人不能授出的角色。给出去就等于开了提权通道。
PROTECTED_ROLES = {"admin", "fde"}

# 邀请链接的有效期。太长等于长期有效的后门。
INVITE_TTL_HOURS = 72

INVITATIONS = "org_invitations"


def _now() -> datetime:
    return datetime.now(UTC)


def _actor(request: Request) -> dict[str, Any] | None:
    auth = getattr(request.state, "auth", None) or {}
    username = auth.get("sub") or auth.get("username")
    if not username:
        return None
    return next(
        (u for u in repo.state.get("users", []) if str(u.get("username")) == str(username)),
        None,
    )


def _is_org_leader(user: dict[str, Any] | None, org_id: str) -> bool:
    if not user:
        return False
    if str(user.get("role")) == "admin":
        return True  # 系统管理员本来就管得着所有组织
    return bool(user.get("isOrgLeader")) and str(user.get("orgId") or "") == str(org_id)


def _guard(request: Request, org_id: str) -> tuple[dict[str, Any] | None, Any]:
    """返回 (actor, 错误响应)。有错误就直接把它返回出去。"""
    actor = _actor(request)
    if not actor:
        return None, fail(errors.UNAUTHORIZED, request, http_status=401)
    if not _is_org_leader(actor, org_id):
        # 不区分「不是负责人」和「组织不存在」——区分了就成了组织存在性的探测口
        return None, fail(errors.FORBIDDEN, request, http_status=403, message="只有本组织负责人可以操作。")
    return actor, None


# --------------------------------------------------------------------------
# 第 4 条：邀请链接注册
# --------------------------------------------------------------------------


@org_delegation_router.post("/org-units/{org_id}/invitations")
def create_invitation(
    request: Request,
    org_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    from apps.api.routes import idempotent

    actor, error = _guard(request, org_id)
    if error:
        return error

    role = str(body.get("role") or "").strip()
    if not role:
        return fail(errors.VALIDATION_ERROR, request, message="必须指定邀请的角色。")
    if role in PROTECTED_ROLES:
        # 「组织内的权限分配」不该能造出系统管理员
        return fail(errors.FORBIDDEN, request, http_status=403, message=f"不能通过邀请授予 {role} 角色。")

    def produce():
        token = secrets.token_urlsafe(24)
        invitation = {
            "token": token,
            "orgId": org_id,
            "role": role,
            "createdBy": actor.get("id"),
            "createdAt": server_time(),
            "expiresAt": (_now() + timedelta(hours=INVITE_TTL_HOURS)).isoformat(),
            # 单次有效：链接会被转发、被截图、被贴进群里
            "usedAt": None,
            "usedBy": None,
        }
        repo.state.setdefault(INVITATIONS, []).insert(0, invitation)
        repo.add_audit("创建组织邀请", "OrgInvitation", token[:8], result="成功")
        return ok(
            {
                "token": token,
                "orgId": org_id,
                "role": role,
                "expiresAt": invitation["expiresAt"],
                "expiresInHours": INVITE_TTL_HOURS,
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


def _find_invitation(token: str) -> dict[str, Any] | None:
    return next(
        (i for i in repo.state.get(INVITATIONS, []) if str(i.get("token")) == str(token)),
        None,
    )


def _invitation_problem(invitation: dict[str, Any] | None) -> str:
    """邀请为什么不能用。**对外只回一句笼统的话**——
    区分「不存在」「已用过」「已过期」等于给撞令牌的人送反馈。"""
    if not invitation:
        return "INVITE_INVALID"
    if invitation.get("usedAt"):
        return "INVITE_INVALID"
    try:
        expires = datetime.fromisoformat(str(invitation.get("expiresAt")))
    except ValueError:
        return "INVITE_INVALID"
    if expires <= _now():
        return "INVITE_INVALID"
    return ""


@org_delegation_router.get("/invitations/{token}")
def inspect_invitation(request: Request, token: str):
    """注册页用它显示「你被邀请加入 X，角色 Y」。

    不需要登录——邀请链接的收件人本来就还没有账号。
    只回组织名和角色，不回任何成员信息。
    """
    invitation = _find_invitation(token)
    if _invitation_problem(invitation):
        return fail(errors.NOT_FOUND, request, message="邀请链接无效或已过期。")
    org = next(
        (o for o in repo.state.get("org_units", []) if str(o.get("id")) == str(invitation["orgId"])),
        None,
    )
    return ok(
        {
            "orgId": invitation["orgId"],
            "orgName": (org or {}).get("name") or "",
            "role": invitation["role"],
            "expiresAt": invitation["expiresAt"],
        },
        request,
    )


@org_delegation_router.post("/invitations/{token}/accept")
def accept_invitation(request: Request, token: str, body: dict[str, Any] = Body(default_factory=dict)):
    """凭邀请链接建账号。

    口令由**注册者自己**在页面上设置，服务端只做长度校验后交给既有的
    用户创建逻辑处理——这里不生成、不打印、不记录任何口令。
    """
    invitation = _find_invitation(token)
    if _invitation_problem(invitation):
        return fail(errors.NOT_FOUND, request, message="邀请链接无效或已过期。")

    from apps.api.routes import (
        build_admin_user_record,
        find_org_unit,
        password_strength_errors,
        upsert_admin_config_user,
    )

    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    if not username:
        return fail(errors.VALIDATION_ERROR, request, message="用户名不能为空。")
    # 口令强度**复用后台建用户那一套**。自己另写一套弱一点的规则，
    # 等于开了一条绕过口令策略的注册通道。
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

    org = find_org_unit(invitation["orgId"], "")
    user = build_admin_user_record(
        {
            "username": username,
            "password": password,
            "role": invitation["role"],
            "orgId": invitation["orgId"],
            "name": str(body.get("displayName") or username),
        },
        org=org,
    )
    user["authVersion"] = 1
    user["mustChangePassword"] = False
    repo.state["users"].insert(0, user)
    upsert_admin_config_user(user)
    invitation["usedAt"] = server_time()
    invitation["usedBy"] = user.get("id")
    repo.add_audit("邀请注册", "User", str(user.get("id")), result="成功")
    # 不回口令、不回令牌：注册完让他正常登录
    return ok({"userId": user.get("id"), "username": username, "role": invitation["role"]}, request)


# --------------------------------------------------------------------------
# 第 5 条：组织负责人分配权限
# --------------------------------------------------------------------------


@org_delegation_router.post("/org-units/{org_id}/members/{user_id}/role")
def assign_member_role(
    request: Request,
    org_id: str,
    user_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    from apps.api.routes import idempotent

    actor, error = _guard(request, org_id)
    if error:
        return error

    role = str(body.get("role") or "").strip()
    if not role:
        return fail(errors.VALIDATION_ERROR, request, message="必须指定角色。")
    if role in PROTECTED_ROLES:
        return fail(errors.FORBIDDEN, request, http_status=403, message=f"不能授予 {role} 角色。")

    target = next(
        (u for u in repo.state.get("users", []) if str(u.get("id")) == str(user_id)), None
    )
    # 目标不在本组织时和「不存在」回同一句：区分了就成了成员探测口
    if not target or str(target.get("orgId") or "") != str(org_id):
        return fail(errors.NOT_FOUND, request, message="该成员不在本组织。")
    if str(target.get("id")) == str(actor.get("id")):
        # 自己给自己改权是所有越权里最常见的一种
        return fail(errors.FORBIDDEN, request, http_status=403, message="不能修改自己的角色。")
    if str(target.get("role")) in PROTECTED_ROLES:
        return fail(errors.FORBIDDEN, request, http_status=403, message="不能修改管理员的角色。")

    def produce():
        before = target.get("role")
        target["role"] = role
        # 改角色必须让对方重新登录：旧令牌里带着旧角色，不失效的话
        # 降权在下一次续期之前根本不生效。
        target["authVersion"] = int(target.get("authVersion") or 0) + 1
        repo.add_audit(
            f"组织内调整角色 {before} -> {role}", "User", str(user_id), result="成功"
        )
        return ok({"userId": user_id, "role": role, "previousRole": before}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)
