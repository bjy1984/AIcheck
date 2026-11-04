"""删除时只能停用的用户/组织：保留记录，但把名字让出来（2026-11-04 用户确认）。

被项目引用的用户、被用户或项目引用的组织，「删除」只能停用——历史记录和审计要能追溯。
但原来停用后名字一直占着：青岛特检院的 qdns 删不掉、同名组织建不了、开通特检院时
院管理员用户名报「已被其他单位使用」。现在改名成带「已删除」标记的名字，原名放进
releasedName 留档，原名即可再用。已经停用过的记录再点一次「删除」也会走这里。
"""

from __future__ import annotations

from typing import Any

DELETED_MARK = "已删除"
ORG_NAME_FIELDS = ("ownerOrgName", "contractorOrgName", "ndtOrgName", "inspectionOrgName")


def _suffix(record: dict[str, Any]) -> str:
    raw = str(record.get("id") or "")
    return raw.split("-")[-1][-8:] or raw[-8:]


def is_released(value: str | None) -> bool:
    return DELETED_MARK in str(value or "")


def released_username(user: dict[str, Any]) -> str:
    username = str(user.get("username") or "")
    return username if is_released(username) else f"{username}~{DELETED_MARK}-{_suffix(user)}"


def released_org_name(org: dict[str, Any]) -> str:
    name = str(org.get("name") or "")
    return name if is_released(name) else f"{name}（{DELETED_MARK}-{_suffix(org)}）"


def release_username(user: dict[str, Any]) -> str | None:
    """改用户名，返回被让出的原名；已经让过的返回 None。"""
    original = str(user.get("username") or "")
    if not original or is_released(original):
        return None
    user["releasedUsername"] = original
    user["username"] = released_username(user)
    return original


def release_org_name(state: dict[str, Any], users: list[dict[str, Any]], org: dict[str, Any]) -> str | None:
    """改组织名，并把按名字引用它的用户、项目成员、项目字段一起改过去，免得新建的同名组织「接手」旧引用。"""
    original = str(org.get("name") or "")
    if not original or is_released(original):
        return None
    new_name = released_org_name(org)
    org.update({"name": new_name, "releasedName": original})
    org_id = org.get("id")
    for row in [*users, *(state.get("project_members") or [])]:
        if row.get("orgId") == org_id or (not row.get("orgId") and row.get("orgName") == original):
            row["orgName"] = new_name
    for project in state.get("projects") or []:
        for field in ORG_NAME_FIELDS:
            if project.get(field) == original:
                project[field] = new_name
    return original
