"""一張記錄表列了多個對象（多條管線）時，讓監檢員指定這次審哪一個。

事實構建遇到多個對象不替人挑（挑第一行等於替被審方決定），判「來源對象衝突」，
並列出候選對象（對象號、所在文件與頁碼）。監檢員選定後，以 selectedObjectIds
重新發起審查：只放行這些對象，凍結進審查任務並計入 inputHash。
"""
from __future__ import annotations

from typing import Any

MAX_SELECTED_OBJECTS = 20


def candidate_objects(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """表格行 → 候選對象清單（按對象號去重，保留第一次出現的位置）。"""
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
    """從一個節點的業務事實裡收集所有「對象衝突」給出的候選對象。"""
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
    """發起審查時指定的對象號：1–20 個不同的非空字串。"""
    if (not isinstance(value, list) or not value or len(value) > MAX_SELECTED_OBJECTS
            or any(not isinstance(item, str) or not item.strip() or len(item) > 120 for item in value)
            or len({item.strip() for item in value}) != len(value)):
        raise ValueError(f"请选择 1–{MAX_SELECTED_OBJECTS} 个不同的审查对象。")
    return [item.strip() for item in value]
