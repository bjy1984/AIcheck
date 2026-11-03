"""特检院（租户）注册表与全局用户名目录——多特检院第二阶段（2026-11-02）。

服务器由平台方托管，每个特检院是一个租户，有自己的院管理员。两份全局数据都放在
部署默认院（平台院）里：
- institutes：登记过的特检院。只有登记过、且启用中的院才能登录；原来 shared 模式下
  匿名登录带任意 tenantId 都会在内存里凭空建出一个院。
- user_directory：非平台院用户的「用户名 → 院」。用户登录不用选单位，按用户名找到院；
  也靠它保证用户名在全平台唯一。平台院自己的用户不进目录，找不到就落平台院，
  所以已有账号不用回填。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from libs.contracts.responses import server_time
from libs.db.repository import (
    flush_mutation_records,
    load_state,
    postgres_persistence_configured,
    repo,
)
from libs.security.tenant import configured_tenant_id as platform_tenant_id
from libs.security.tenant import current_tenant_id, reset_request_tenant_id, set_request_tenant_id

INSTITUTES = "institutes"
USER_DIRECTORY = "user_directory"
ACTIVE, DISABLED = "active", "disabled"


def _persistent() -> bool:
    return bool(postgres_persistence_configured() or repo.sqlite_enabled or repo.sqlite_path or os.getenv("AICHECK_SQLITE_PATH"))


@contextmanager
def tenant_scope(tenant_id: str) -> Iterator[dict[str, Any]]:
    """临时切到某个院读写它的 state；没加载过就先加载。"""
    token = set_request_tenant_id(tenant_id)
    try:
        if not repo.tenant_is_loaded(tenant_id):
            if _persistent():
                load_state(tenant_id=tenant_id)
            repo.mark_tenant_loaded(tenant_id)
        yield repo.state
    finally:
        reset_request_tenant_id(token)


def platform_scope():
    return tenant_scope(platform_tenant_id())


def save_in_current_tenant(collection: str, *rows: dict[str, Any]) -> None:
    """只落这几行：跨院写入不能指望请求收尾的落盘，它只管请求自己的院。"""
    flush_mutation_records({collection: [repo.clone(row) for row in rows]}, [])


def list_institutes() -> list[dict[str, Any]]:
    with platform_scope() as state:
        return [repo.clone(row) for row in state.setdefault(INSTITUTES, [])]


def find_institute(tenant_id: str) -> dict[str, Any] | None:
    return next((row for row in list_institutes() if row.get("id") == tenant_id), None)


def tenant_login_allowed(tenant_id: str | None) -> bool:
    """平台院永远可以；其他院必须登记过且启用中。"""
    tenant = str(tenant_id or "")
    if tenant == platform_tenant_id():
        return True
    institute = find_institute(tenant)
    return bool(institute and institute.get("status") == ACTIVE)


def _directory_key(username: str) -> str:
    return str(username or "").strip().casefold()


def tenant_for_username(username: str | None) -> str | None:
    key = _directory_key(username or "")
    if not key:
        return None
    with platform_scope() as state:
        row = next((item for item in state.setdefault(USER_DIRECTORY, []) if item.get("id") == key), None)
    return str(row["tenantId"]) if row else None


def register_username(username: str, tenant_id: str) -> None:
    """非平台院的新账号登进目录。平台院的账号不登：找不到目录项就落平台院。"""
    if tenant_id == platform_tenant_id():
        return
    entry = {"id": _directory_key(username), "username": username, "tenantId": tenant_id, "createdAt": server_time()}
    with platform_scope() as state:
        rows = state.setdefault(USER_DIRECTORY, [])
        rows[:] = [row for row in rows if row.get("id") != entry["id"]]
        rows.append(entry)
        save_in_current_tenant(USER_DIRECTORY, entry)


def username_conflict_message(username: str, for_tenant: str | None = None) -> str | None:
    """建账号前调用：平台上别的院已有同名账号就返回提示。账号所在院自己的重名由原来的检查负责。

    for_tenant 是新账号要建在哪个院，默认当前院；平台管理员替新院建账号时要显式传。
    """
    key = _directory_key(username)
    current = str(for_tenant or current_tenant_id())
    with platform_scope() as state:
        directory = {item.get("id"): item.get("tenantId") for item in state.setdefault(USER_DIRECTORY, [])}
        in_platform = any(_directory_key(user.get("username")) == key for user in state.get("users") or [])
    owner = directory.get(key) or (platform_tenant_id() if in_platform else None)
    if owner and owner != current:
        return "该用户名已被其他单位使用，请换一个。"
    return None
