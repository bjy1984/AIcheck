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
    flush_state,
    load_state,
    postgres_persistence_configured,
    repo,
)
from libs.security.tenant import configured_tenant_id as platform_tenant_id
from libs.security.tenant import current_tenant_id, reset_request_tenant_id, set_request_tenant_id

INSTITUTES = "institutes"
USER_DIRECTORY = "user_directory"
ACTIVE, DISABLED, DELETED = "active", "disabled", "deleted"


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


def _home_tenant(row: dict[str, Any]) -> str:
    """目录项指向的院。老格式（2026-11-04 之前，从未成功落库过）用的是 tenantId。"""
    return str(row.get("homeTenantId") or row.get("tenantId") or "")


def tenant_for_username(username: str | None) -> str | None:
    key = _directory_key(username or "")
    if not key:
        return None
    with platform_scope() as state:
        row = next((item for item in state.setdefault(USER_DIRECTORY, []) if item.get("id") == key), None)
    return _home_tenant(row) if row and not row.get("released") else None


def register_username(username: str, tenant_id: str) -> None:
    """非平台院的新账号登进目录。平台院的账号不登：找不到目录项就落平台院。"""
    if tenant_id == platform_tenant_id():
        return
    # 账号所在院记在 homeTenantId：tenantId 是这条目录记录本身的院标记（平台院），
    # 落库会核对它与当前院一致；原来写成 tenantId=新院，开通特检院在这一步被拒（2026-11-04 生产）
    entry = {"id": _directory_key(username), "username": username, "homeTenantId": tenant_id, "createdAt": server_time()}
    with platform_scope() as state:
        rows = state.setdefault(USER_DIRECTORY, [])
        rows[:] = [row for row in rows if row.get("id") != entry["id"]]
        rows.append(entry)
        save_in_current_tenant(USER_DIRECTORY, entry)


def unregister_username(username: str, tenant_id: str) -> None:
    """账号让出用户名（删除时只能停用、改了名）后，目录里原名那条标成已释放：登录不再按它找院、也不再占名。

    落库只能写不能删，所以不删行；同名再注册时 register_username 会整条换掉。
    """
    key = _directory_key(username)
    with platform_scope() as state:
        row = next((item for item in state.setdefault(USER_DIRECTORY, []) if item.get("id") == key), None)
        if row is None or _home_tenant(row) != tenant_id or row.get("released"):
            return
        row.update({"released": True, "releasedAt": server_time()})
        save_in_current_tenant(USER_DIRECTORY, row)


def unregister_username_after_save(request: Any, username: str | None, tenant_id: str) -> None:
    """请求自己的落库成功后再让出目录里的用户名（2026-11-04 审计）。

    unregister_username 立刻落库；若随后请求自己的落库失败（409），账号还叫原名，目录却已标成释放，
    这个院的账号就登录不了了。所以挂到请求收尾（apps/api/main.py 落库成功后执行 after_save）。
    """
    if not username:
        return
    callbacks = getattr(request.state, "after_save", None)
    if callbacks is None:
        callbacks = []
        request.state.after_save = callbacks
    callbacks.append(lambda: unregister_username(str(username), str(tenant_id)))


def username_conflict_message(username: str, for_tenant: str | None = None) -> str | None:
    """建账号前调用：平台上别的院已有同名账号就返回提示。账号所在院自己的重名由原来的检查负责。

    for_tenant 是新账号要建在哪个院，默认当前院；平台管理员替新院建账号时要显式传。
    """
    key = _directory_key(username)
    current = str(for_tenant or current_tenant_id())
    with platform_scope() as state:
        directory = {item.get("id"): _home_tenant(item) for item in state.setdefault(USER_DIRECTORY, []) if not item.get("released")}
        in_platform = any(_directory_key(user.get("username")) == key for user in state.get("users") or [])
    owner = directory.get(key) or (platform_tenant_id() if in_platform else None)
    if owner and owner != current:
        return "该用户名已被其他单位使用，请换一个。"
    return None


def ensure_tenant_loaded(tenant_id: str) -> None:
    """公开接口（注册链接）按链接切到院时，那个院在本进程可能还没加载过。"""
    with tenant_scope(tenant_id):
        pass


# ── 平台通用规则下发到各院（第三阶段）──────────────────────────────────────
#
# 规则版本有 17 处读取，不少是边读边改（发布、回滚），挨个改成「本院 + 平台」合并读太险。
# 改为把平台的通用规则（不属于任何项目的）同步一份给各院，打上 syncedFromPlatform：
# 院管理员不能改这些（knowledge:manage 在非平台院一律 403），平台改了再同步一次即可；
# 院自己的项目规则不动。效果上仍是「平台维护、各院只读」。

SYNCED_FROM_PLATFORM = "syncedFromPlatform"


def _platform_owned_rules(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from libs.rule_scope import rule_scope

    return [repo.clone(row) for row in rows if isinstance(row, dict) and not rule_scope(row)[0]]


def sync_platform_rules(tenant_id: str) -> dict[str, int]:
    """把平台院的通用规则版本同步到某个院：新增、更新，平台已删的也从院里删掉。"""
    if tenant_id == platform_tenant_id():
        return {"synced": 0, "removed": 0}
    with platform_scope() as state:
        platform_rules = _platform_owned_rules(state.get("rule_versions") or [])
    platform_ids = {str(row.get("id")) for row in platform_rules}
    with tenant_scope(tenant_id) as state:
        rows = state.setdefault("rule_versions", [])
        own = [row for row in rows if not row.get(SYNCED_FROM_PLATFORM)]
        own_ids = {str(row.get("id")) for row in own}
        removed = [row for row in rows if row.get(SYNCED_FROM_PLATFORM) and str(row.get("id")) not in platform_ids]
        # 复制过来的规则要改标成本院：带着平台院的 tenantId 落库会被拒（Cross-tenant persistence，
        # 2026-11-04 生产上开通特检院在这一步报错，测试平台院没规则可复制，没测出来）
        synced = [{**{k: v for k, v in row.items() if k != "tenant_id"}, SYNCED_FROM_PLATFORM: True, "tenantId": tenant_id}
                  for row in platform_rules if str(row.get("id")) not in own_ids]
        rows[:] = own + synced
        # 和加载时的基线比对落库：新增、更新、删除一次写完；只碰 rule_versions
        flush_state({"rule_versions"}, selected_singleton_keys=set())
    return {"synced": len(synced), "removed": len(removed)}


# ── 标准原文共用平台标准库（第三阶段）───────────────────────────────────────
#
# 依据条款、标准原文在各院打开时读的是 /knowledge/files/{id}/… 这些只读接口；标准文件只在
# 平台院有。main.py 对「非平台院的 GET、读的是平台院的标准文件」把这一次请求切到平台院，
# 文件元数据、OCR 文字和对象存储原件（平台院路径不带院前缀）就都对了。只放行标准文件：
# 平台院知识库里还有平台自己的项目资料，列表接口和项目文件一律不切。


def platform_standard_file_exists(file_id: str) -> bool:
    from libs.knowledge_retrieval import is_standard_knowledge_file

    with platform_scope() as state:
        file = next((row for row in state.get("knowledge_files") or [] if str(row.get("id")) == str(file_id)), None)
        if file is None:
            return False
        source = next(
            (row for row in state.get("knowledge_sources") or [] if row.get("id") == file.get("sourceId")), {}
        )
    return is_standard_knowledge_file({**file, "sourceType": file.get("sourceType") or source.get("sourceType")})


def platform_standard_listing() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """平台院的标准来源和标准文件（只读副本，标 sharedFromPlatform），给院里的知识库列表页用。

    只取标准：平台院知识库里的项目文件来源和项目文件不出平台院。
    """
    from libs.knowledge_retrieval import is_project_file_source, is_standard_knowledge_file

    with platform_scope() as state:
        sources = {row.get("id"): row for row in state.get("knowledge_sources") or [] if isinstance(row, dict)}
        standard_sources = [
            {**repo.clone(row), SHARED_FROM_PLATFORM_FLAG: True}
            for row in sources.values()
            if row.get("sourceType") == "standard" and not is_project_file_source(row)
        ]
        standard_files = [
            {**repo.clone(row), SHARED_FROM_PLATFORM_FLAG: True}
            for row in state.get("knowledge_files") or []
            if isinstance(row, dict)
            and is_standard_knowledge_file(
                {**row, "sourceType": row.get("sourceType") or (sources.get(row.get("sourceId")) or {}).get("sourceType")}
            )
        ]
    return standard_sources, standard_files


SHARED_FROM_PLATFORM_FLAG = "sharedFromPlatform"
