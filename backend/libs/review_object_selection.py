"""一张记录表列了多个对象（多条管线）时，让监检员指定这次审哪一个。

事实构建遇到多个对象不替人挑（挑第一行等于替被审方决定），判「来源对象冲突」，
并列出候选对象（对象号、所在文件与页码）。监检员选定后，以 selectedObjectIds
重新发起审查：只放行这些对象，冻结进审查任务并计入 inputHash。
"""
from __future__ import annotations

from typing import Any

MAX_SELECTED_OBJECTS = 20


def candidate_objects(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """表格行 → 候选对象清单（按对象号去重，保留第一次出现的位置）。"""
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        object_id = str(row.get("objectId") or "").strip()
        if not object_id or object_id in seen:
            continue
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        seen[object_id] = {"objectId": object_id, "objectType": row.get("objectType"),
                           "documentVersionId": row.get("documentVersionId") or row.get("recordVersionId"),
                           "pageNo": evidence.get("pageNo")}
    return list(seen.values())


def collect_object_candidates(facts: Any, *, depth: int = 0) -> list[dict[str, Any]]:
    """从一个节点的业务事实里收集所有「对象冲突」给出的候选对象。"""
    if depth > 4 or not isinstance(facts, dict):
        return []
    found: list[dict[str, Any]] = []
    for key, value in facts.items():
        if key == "candidateObjects" and isinstance(value, list):
            found.extend(item for item in value if isinstance(item, dict) and item.get("objectId"))
        elif isinstance(value, dict):
            found.extend(collect_object_candidates(value, depth=depth + 1))
    unique: dict[str, dict[str, Any]] = {}
    for item in found:
        unique.setdefault(str(item["objectId"]), item)
    return list(unique.values())


def validated_selected_object_ids(value: Any) -> list[str]:
    """发起审查时指定的对象号：1–20 个不同的非空字串。"""
    if (not isinstance(value, list) or not value or len(value) > MAX_SELECTED_OBJECTS
            or any(not isinstance(item, str) or not item.strip() or len(item) > 120 for item in value)
            or len({item.strip() for item in value}) != len(value)):
        raise ValueError(f"请选择 1–{MAX_SELECTED_OBJECTS} 个不同的审查对象。")
    return [item.strip() for item in value]
