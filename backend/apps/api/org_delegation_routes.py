"""组织内的权限下放（0817 第 5 条）。

    「各个组织内的负责人。拥有权限分配」

## 邀请注册已经从这里撤掉

原先这里还有一套「组织邀请链接」：绑组织和角色、单次有效、提交即建账号。
后来需求改成**按项目发链接、注册者自选角色、项目负责人审核通过**
（apps/api/project_registration_routes.py），两套并存会出问题：

- 两条路都能建账号，但一条即时生效、一条要审核——
  **同一个系统里两种「注册」意味着两种安全边界**，
  而看界面的人分不出自己走的是哪一条；
- 组织邀请那条没有审核，是两者中更宽的一条。留着它，
  等于给「必须审核」这个新要求留了个绕过口。

所以撤掉，只保留角色分配。

## 这里剩下的部分仍有安全后果

A 组织的负责人不能改 B 组织的人，也不能把谁提成系统管理员。
护栏写死在服务端，每条都有反向用例——
「能做什么」好验，「不能做什么」不验就等于没有。

三条硬规则：

1. **只能动同组织的人。** 跨组织一律 403，不管请求里写了什么。
2. **不能授出 admin / fde。** 否则「组织内的权限分配」就成了提权通道。
3. **不能改自己。** 自己给自己升权是所有越权里最常见的一种。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, Request

from libs.contracts import errors
from libs.contracts.responses import fail, ok, server_time
from libs.db.repository import repo

org_delegation_router = APIRouter()

# 组织负责人不能授出的角色。给出去就等于开了提权通道。
PROTECTED_ROLES = {"admin", "fde"}



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
