"""幂等重放的授权摘要该看多大范围——只看**请求所涉项目**。

## 为什么不是全局

全局快照是个真实事故的根源：任何管理员把用户加进一个新项目，
该用户在**其他所有项目**里已缓存的幂等重放会全部永久 FORBIDDEN——
0819 实测：审计脚本反复把监检员加进审计项目，其 242 条缓存记录
全部被击穿，工作台一打开就是「当前授权上下文已变化」。

授权判定（mutation_guard）本来就只看**本项目**的成员关系，
摘要的粒度应当与它一致。

all_projects=True 保留旧口径，只用于识别旧格式记录并就地升级。
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import Request

from libs.db.repository import repo
from libs.security.tenant import tenant_id_for_record

_PROJECT_IN_PATH = re.compile(r"/projects/([^/]+)")


def authorization_scope_project_id(request: Request) -> str | None:
    """请求路径里的项目 id；不带项目的路径返回 None。"""
    match = _PROJECT_IN_PATH.search(str(request.url.path or ""))
    return match.group(1) if match else None


def authorization_membership_snapshot(
    request: Request,
    user_id: str | None,
    tenant_id: str,
    *,
    all_projects: bool = False,
) -> list[tuple[str, tuple[int, ...], str]]:
    """授权摘要里的成员关系快照，默认限定在请求所涉项目。"""
    scope_project = None if all_projects else authorization_scope_project_id(request)
    return sorted(
        (
            str(item.get("projectId") or ""),
            tuple(sorted(int(node_id) for node_id in item.get("nodeScope") or [])),
            str(item.get("status") or ""),
        )
        for item in repo.state.get("project_members", [])
        if str(item.get("userId") or "") == str(user_id or "")
        and tenant_id_for_record(item) == tenant_id
        and (all_projects or str(item.get("projectId") or "") == scope_project)
    )


def replay_authorization_digests(
    request: Request,
    *,
    fingerprint,
    tenant_id: str,
    actor_id: str,
    role: str,
    user_id: str | None,
) -> tuple[str, str]:
    """(新格式, 旧格式) 两个授权摘要。

    旧格式（全局成员快照）只用于识别历史记录并就地升级：
    旧口径仍吻合说明授权没有实质变化，不该把用户拒在外面。
    """
    base: dict[str, Any] = {"tenantId": tenant_id, "actorId": actor_id, "role": role}
    current = fingerprint(
        {**base, "memberships": authorization_membership_snapshot(request, user_id, tenant_id)}
    )
    legacy = fingerprint(
        {
            **base,
            "memberships": authorization_membership_snapshot(
                request, user_id, tenant_id, all_projects=True
            ),
        }
    )
    return current, legacy
