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
    "agentSops": "AI 作业规程",
    "toolCatalog": "工具目录",
    "thinkingModeCatalog": "思考模式",
}
IGNORED = {"snapshotHash", "loadedAt", "fixtures", "version"}
ID_KEYS = ("id", "atomicCheckId", "bindingId", "packageId", "code", "nodeId")


def _key(item: dict[str, Any], index: int) -> str:
    for key in ID_KEYS:
        if item.get(key) not in (None, ""):
            return f"{key}:{item[key]}"
    return f"#{index}"


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _node_ids(item: dict[str, Any], atomic_nodes: dict[str, int]) -> set[int]:
    nodes: set[int] = set()
    for raw in item.get("nodeIds") or []:
        if str(raw).isdigit():
            nodes.add(int(raw))
    if str(item.get("nodeId") or "").isdigit():
        nodes.add(int(item["nodeId"]))
    if item.get("atomicCheckId") in atomic_nodes:
        nodes.add(atomic_nodes[item["atomicCheckId"]])
    return nodes


def pack_diff(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    old = old or {}
    atomic_nodes = {
        str(item.get("id")): int(item["nodeId"])
        for pack in (old, new) for item in pack.get("atomicChecks") or []
        if isinstance(item, dict) and str(item.get("nodeId") or "").isdigit()
    }
    sections: list[dict[str, Any]] = []
    other_changes: list[str] = []
    affected: set[int] = set()
    for name in sorted(set(old) | set(new)):
        if name in IGNORED:
            continue
        before, after = old.get(name), new.get(name)
        if isinstance(before, list) or isinstance(after, list):
            old_items = {_key(item, i): item for i, item in enumerate(before or []) if isinstance(item, dict)}
            new_items = {_key(item, i): item for i, item in enumerate(after or []) if isinstance(item, dict)}
            added = sorted(set(new_items) - set(old_items))
            removed = sorted(set(old_items) - set(new_items))
            changed = sorted(key for key in set(old_items) & set(new_items) if _canon(old_items[key]) != _canon(new_items[key]))
            if not (added or removed or changed):
                continue
            for key in added + changed:
                affected |= _node_ids(new_items[key], atomic_nodes)
            for key in removed + changed:
                affected |= _node_ids(old_items[key], atomic_nodes)
            sections.append({"name": name, "label": SECTION_LABELS.get(name, name), "added": len(added),
                             "removed": len(removed), "changed": len(changed),
                             "sample": [key.split(":", 1)[-1] for key in (changed + added + removed)[:6]]})
        elif _canon(before) != _canon(after):
            other_changes.append(name)
    return {
        "fromVersion": old.get("version"),
        "toVersion": new.get("version"),
        "upToDate": not sections and not other_changes,
        "sections": sections,
        "otherChanges": other_changes,
        "affectedNodeIds": sorted(affected),
    }
