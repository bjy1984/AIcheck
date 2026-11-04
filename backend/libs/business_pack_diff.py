"""项目冻结的业务包副本 vs 现行业务包：改了哪些、影响哪些节点（2026-11-04，意见反馈审批方案第三阶段）。

既有项目建项目时把业务包冻结成副本（project.businessPackSnapshot），执行用副本：平台修好的规则，
旧项目不生效。这里给出「升级会改什么」的预览，再由管理员选择套用到哪些项目
（POST /admin/business-pack/updates/apply，内部走与 /projects/{id}/business-pack/apply 相同的步骤）。
历史运行各自冻结了当时的规则，不受影响。
"""

from __future__ import annotations

import json
from typing import Any

SECTION_LABELS = {
    "ruleSets": "规则",
    "atomicChecks": "原子检查",
    "atomicCheckToolBindings": "检查工具绑定",
    "standardClauseBindings": "标准条款绑定",
    "standardClausePackages": "条款包",
    "standardCatalog": "标准目录",
    "materialTypes": "资料类型",
    "nodeTemplates": "节点模板",
    "roles": "角色",
    "reportTemplates": "报告模板",
    "workflowStateMachines": "流程",
    "workflowActions": "流程动作",
    "agentSops": "AI 作业规程",
    "toolCatalog": "工具目录",
    "thinkingModeCatalog": "思考模式",
    "atomicCheckToolBindingSet": "检查工具绑定配置",
    "standardClauseBindingSet": "标准条款绑定配置",
    "standardClausePackageSet": "条款包配置",
    "atomicCheckSet": "原子检查配置",
    "standardCatalogSet": "标准目录配置",
}
IGNORED = {"snapshotHash", "loadedAt", "fixtures", "version"}
ID_KEYS = ("id", "atomicCheckId", "bindingId", "packageId", "code", "nodeId")
# 整组配置（dict）改了，影响它对应清单里的所有节点；只改版本号、计数不算（2026-11-04 审计）
SET_COMPANIONS = {
    "atomicCheckToolBindingSet": "atomicCheckToolBindings",
    "standardClauseBindingSet": "standardClauseBindings",
    "standardClausePackageSet": "standardClausePackages",
    "atomicCheckSet": "atomicChecks",
    "standardCatalogSet": "standardCatalog",
}
SET_IGNORED = {"version", "atomicCheckCount"}


def _key(item: dict[str, Any], index: int) -> str:
    for key in ID_KEYS:
        if item.get(key) not in (None, ""):
            return f"{key}:{item[key]}"
    return f"#{index}"


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _digits(values: Any) -> set[int]:
    return {int(raw) for raw in values or [] if str(raw).isdigit()}


class _Index:
    """把各类条目对到节点：资料类型经节点模板和规则，标准经条款绑定，试点规则经规则号。"""

    def __init__(self, *packs: dict[str, Any]) -> None:
        self.atomic: dict[str, int] = {}
        self.material: dict[str, set[int]] = {}
        self.standard: dict[str, set[int]] = {}
        self.rule: dict[str, set[int]] = {}
        for pack in packs:
            for item in _dicts(pack.get("atomicChecks")):
                if str(item.get("nodeId") or "").isdigit():
                    self.atomic[str(item.get("id"))] = int(item["nodeId"])
            for item in _dicts(pack.get("nodeTemplates")):
                if str(item.get("nodeId") or "").isdigit():
                    for material in _dicts(item.get("requiredMaterials")):
                        self.material.setdefault(str(material.get("materialTypeCode")), set()).add(int(item["nodeId"]))
            for item in _dicts(pack.get("ruleSets")):
                nodes = _digits(item.get("nodeIds"))
                rule_id = str(item.get("id") or "")
                for code in {rule_id, rule_id.rsplit("-", 1)[-1]} - {""}:
                    self.rule.setdefault(code, set()).update(nodes)
                for code in item.get("materialTypeCodes") or []:
                    self.material.setdefault(str(code), set()).update(nodes)
            for item in _dicts(pack.get("standardClauseBindings")):
                if str(item.get("nodeId") or "").isdigit():
                    for ref in (item.get("documentVersionId"), item.get("knowledgeFileId")):
                        if ref:
                            self.standard.setdefault(str(ref), set()).add(int(item["nodeId"]))

    def nodes(self, section: str, item: dict[str, Any]) -> set[int]:
        nodes = _digits(item.get("nodeIds"))
        if str(item.get("nodeId") or "").isdigit():
            nodes.add(int(item["nodeId"]))
        if str(item.get("atomicCheckId") or "") in self.atomic:
            nodes.add(self.atomic[str(item["atomicCheckId"])])
        if section == "materialTypes":
            nodes |= self.material.get(str(item.get("code")), set())
        if section == "standardCatalog":
            for ref in (item.get("documentVersionId"), item.get("knowledgeFileId")):
                nodes |= self.standard.get(str(ref), set())
        return nodes


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)] if isinstance(value, list) else []


def _list_section(name: str, before: Any, after: Any, index: _Index) -> tuple[dict[str, Any] | None, set[int]]:
    before, after = before if isinstance(before, list) else [], after if isinstance(after, list) else []
    if any(not isinstance(item, dict) for item in before + after):
        # 字符串清单（如流程动作）：原来按 dict 过滤，改了也看不出来
        old_values, new_values = {_canon(item) for item in before}, {_canon(item) for item in after}
        if old_values == new_values:
            return None, set()
        added, removed = sorted(new_values - old_values), sorted(old_values - new_values)
        return {"name": name, "label": SECTION_LABELS.get(name, name), "added": len(added), "removed": len(removed),
                "changed": 0 if (added or removed) else 1, "sample": [json.loads(item) for item in (added + removed)[:6]]}, set()
    old_items = {_key(item, i): item for i, item in enumerate(before)}
    new_items = {_key(item, i): item for i, item in enumerate(after)}
    added = sorted(set(new_items) - set(old_items))
    removed = sorted(set(old_items) - set(new_items))
    changed = sorted(key for key in set(old_items) & set(new_items) if _canon(old_items[key]) != _canon(new_items[key]))
    if not (added or removed or changed):
        return None, set()
    affected: set[int] = set()
    for key in added + changed:
        affected |= index.nodes(name, new_items[key])
    for key in removed + changed:
        affected |= index.nodes(name, old_items[key])
    return {"name": name, "label": SECTION_LABELS.get(name, name), "added": len(added), "removed": len(removed),
            "changed": len(changed), "sample": [key.split(":", 1)[-1] for key in (changed + added + removed)[:6]]}, affected


def _set_nodes(name: str, before: Any, after: Any, old: dict[str, Any], new: dict[str, Any], index: _Index) -> set[int]:
    before, after = before if isinstance(before, dict) else {}, after if isinstance(after, dict) else {}
    nodes: set[int] = set()
    if name == "atomicCheckToolBindingSet":
        for code in {str(item) for item in before.get("pilotRules") or []} ^ {str(item) for item in after.get("pilotRules") or []}:
            nodes |= index.rule.get(code, set())
    rest = SET_IGNORED | ({"pilotRules"} if name == "atomicCheckToolBindingSet" else set())
    if _canon({k: v for k, v in before.items() if k not in rest}) != _canon({k: v for k, v in after.items() if k not in rest}):
        companion = SET_COMPANIONS[name]
        for pack in (old, new):
            for item in _dicts(pack.get(companion)):
                nodes |= index.nodes(companion, item)
    return nodes


def pack_diff(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    old = old or {}
    index = _Index(old, new)
    sections: list[dict[str, Any]] = []
    other_changes: list[str] = []
    affected: set[int] = set()
    for name in sorted(set(old) | set(new)):
        if name in IGNORED:
            continue
        before, after = old.get(name), new.get(name)
        if isinstance(before, list) or isinstance(after, list):
            section, nodes = _list_section(name, before, after, index)
            if section:
                sections.append(section)
                affected |= nodes
        elif _canon(before) != _canon(after):
            if name in SET_COMPANIONS:
                nodes = _set_nodes(name, before, after, old, new, index)
                if not nodes and _canon({k: v for k, v in (before or {}).items() if k not in SET_IGNORED}) == _canon(
                        {k: v for k, v in (after or {}).items() if k not in SET_IGNORED}):
                    continue  # 只改了版本号或计数
                affected |= nodes
            other_changes.append(name)
    return {
        "fromVersion": old.get("version"),
        "toVersion": new.get("version"),
        "upToDate": not sections and not other_changes,
        "sections": sections,
        "otherChanges": other_changes,
        "otherChangeLabels": [SECTION_LABELS.get(name, name) for name in other_changes],
        "affectedNodeIds": sorted(affected),
    }


REQUIREMENT_FIELDS = ("name", "requiredType", "materialTypeCode", "businessPackId", "businessPackVersion",
                      "templateNodeCode", "note", "responsibleParty", "applicability")


def reconcile_requirements(state: dict[str, Any], project_id: str, fresh: list[dict[str, Any]]) -> dict[str, Any]:
    """升级时把项目的资料清单行对到新业务包（2026-11-04 审计）。

    原来只补新增的行，已有行的名称、必传/选传、说明一直停在旧版。没挂资料的行直接按新版更新；
    挂了资料的不动（名称改了会断开按名称的挂载匹配），列出来交人工；新版里没有了的行不删，
    标上 retiredInPackVersion 并列出来。
    """
    fresh_by_id = {str(item["id"]): item for item in fresh}
    bindings = [row for row in state.get("bindings") or [] if isinstance(row, dict) and row.get("projectId") == project_id]
    updated, kept_bound, retired = [], [], []
    for row in state.get("requirements") or []:
        if not isinstance(row, dict) or row.get("projectId") != project_id:
            continue
        target = fresh_by_id.get(str(row.get("id")))
        bound = any(str(item.get("requirementId") or "") == str(row.get("id"))
                    or (row.get("name") and item.get("requirementName") == row.get("name")) for item in bindings)
        if target is None:
            if not row.get("retiredInPackVersion"):
                row["retiredInPackVersion"] = next(iter(fresh), {}).get("businessPackVersion")
            retired.append(str(row.get("id")))
            continue
        row.pop("retiredInPackVersion", None)
        differs = any(row.get(field) != target.get(field) for field in REQUIREMENT_FIELDS if field != "businessPackVersion")
        if bound:
            if differs:
                kept_bound.append(str(row.get("id")))
            continue
        if differs or row.get("businessPackVersion") != target.get("businessPackVersion"):
            row.update({field: target.get(field) for field in REQUIREMENT_FIELDS})
            if differs:
                updated.append(str(row.get("id")))
    return {"updatedRequirementIds": updated, "boundRequirementIdsNotUpdated": kept_bound,
            "retiredRequirementIds": retired}
