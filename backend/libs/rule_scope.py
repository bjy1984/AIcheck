"""Scope identity shared by rule selection, replacement and rollback."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.business_pack.loader import DEFAULT_BUSINESS_PACK_ID, matching_rule_for_node


def rule_scope(rule: dict[str, Any]) -> tuple[str, str]:
    return (
        str(rule.get("projectId") or ""),
        str(rule.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID),
    )


def same_rule_scope(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return rule_scope(left) == rule_scope(right)


def review_rule_node_ids(rule: dict[str, Any]) -> set[int]:
    node_ids: set[int] = set()
    for raw in rule.get("nodeIds") or []:
        if str(raw).isdigit():
            node_ids.add(int(raw))
    return node_ids


def select_published_rule(rows: list[dict[str, Any]], node_id: int, *, business_pack_id: str | None = None, project_id: str | None = None) -> dict[str, Any] | None:
    candidates = []
    for rule in rows:
        if rule.get("status") != "已发布":
            continue
        if node_id not in review_rule_node_ids(rule):
            continue
        owner_project, owner_pack = rule_scope(rule)
        if owner_project and owner_project != project_id:
            continue
        if owner_pack != (business_pack_id or DEFAULT_BUSINESS_PACK_ID):
            continue
        candidates.append(rule)
    candidates.sort(key=lambda item: _rule_preference(item, project_id), reverse=True)
    return deepcopy(candidates[0]) if candidates else None


def _rule_preference(rule: dict[str, Any], project_id: str | None) -> tuple[Any, ...]:
    """越大越优先：项目内规则 > 发布时间新 > 覆盖节点少 > 规则 id 大。

    第三项（覆盖节点少者优先）是 2026-09-11 加的。老种子 `RULE-WELDER-202606`
    （焊工资格核验）一条规则声明 nodeIds [24, 25, 27, 28]，与业务包里
    R25/R27 的 publishedAt 完全相同（06-26 09:12），并列时只靠入参顺序决胜——
    实测节点 25/27 侥幸取到了对的规则，但这不牢靠。声明「只管这一个节点」的规则
    比「一口气管四个」的更贴近该节点，先取窄的。第四项只为可复现，不含业务含义。
    """
    return (
        bool(project_id and rule_scope(rule)[0] == project_id),
        str(rule.get("publishedAt") or rule.get("updatedAt") or rule.get("importedAt") or ""),
        -len(review_rule_node_ids(rule)),
        str(rule.get("id") or ""),
    )


def select_rule_for_project(
    rows: list[dict[str, Any]],
    node_id: int,
    *,
    project: dict[str, Any] | None,
    business_pack_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any] | None:
    """已发布规则，但业务包规则以项目冻结的那一版为准。

    业务包规则（RULE-ENG-INSP-Rxx）在规则库里只有一条共用记录，各项目的业务包却在建项目
    或「规则升级」时按当时版本冻结。两边版本不同时，确定性工具按项目冻结包的参数执行，
    给 Agent 的审查规程却来自共用记录，同一个节点就会出现两套口径。2026-11-09 生产复查：
    共用 R01 还是 v20260714（GC2 只认 GC2/GC1 许可），09.23 业务包的项目工具已按 v20260923
    （GCD 也覆盖 GC2）判定，测试项目3 的 27 次节点 1 复核规程与工具相反。

    所以：选中的是同一条业务包规则（id 相同）、版本却和项目冻结包里的不同，就用项目冻结包
    里那一版。项目内规则照旧最优先；管理员在规则库「基于正式规则创建草稿」再发布的改版是
    另一个 id，不受影响，发布后照常生效。
    """
    project = project or {}
    # 项目记录可能取不到（规则库视图、测试替身），项目内规则仍按传入的项目号挑
    project_id = project_id or str(project.get("id") or "") or None
    published = select_published_rule(rows, node_id, business_pack_id=business_pack_id, project_id=project_id)
    if not published or rule_scope(published)[0]:
        return published
    pack = project.get("businessPackSnapshot")
    pack_id = business_pack_id or DEFAULT_BUSINESS_PACK_ID
    if not isinstance(pack, dict) or str(project.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID) != pack_id:
        return published
    frozen = matching_rule_for_node(pack, node_id)
    if (
        not frozen
        or str(frozen.get("id") or "") != str(published.get("id") or "")
        or not frozen.get("version")
        or frozen.get("version") == published.get("version")
    ):
        return published
    return {
        **deepcopy(frozen),
        "businessPackId": pack_id,
        "businessPackVersion": pack.get("version"),
        "ruleSource": "project-business-pack",
        "sharedRuleVersion": published.get("version"),
    }
