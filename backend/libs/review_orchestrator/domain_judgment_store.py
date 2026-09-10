"""agent 读出来的事实存进 state，事实构建再从 state 读——不在事实构建里调模型。

这个间接层不是为了解耦好看，是为了保住可重放性。`replay_review_acceptance` 的
前提是"同样的输入必得同样的输出"，靠的是 OFFLINE_TOOLS 里那批工具不碰网络。
如果事实构建直接调模型，验收重放就变成每次重新问一遍模型——同一份 fixture 两次
跑出不同结论，整套冻结判据的意义随之消失。

所以 agent 的产出被当作**证据**记进 state：它和 OCR 的表格一样，是一次性产生、
此后只被读取的资料。冻结进 fixture 之后，重放读的是当时记下来的那份，不会再花钱，
也不会飘。

对不上号的判定宁可不用：projectId / nodeId / domain / objectId / recordVersionId
五项全等才算数。少一项就可能把甲管线的结论安到乙管线头上。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

COLLECTION = "domain_judgments"
_KEYS = ("projectId", "nodeId", "domain", "objectId", "recordVersionId")


def judgment_for(
    state: dict[str, Any],
    *,
    project_id: Any,
    node_id: Any,
    domain: Any,
    object_id: Any,
    record_version_id: Any,
) -> dict[str, Any] | None:
    """五项全等才返回；命中多条视为来源含糊，一条都不给。"""
    wanted = {
        "projectId": project_id, "nodeId": node_id, "domain": domain,
        "objectId": object_id, "recordVersionId": record_version_id,
    }
    hits = [
        row for row in state.get(COLLECTION) or []
        if isinstance(row, dict) and all(row.get(key) == wanted[key] for key in _KEYS)
    ]
    return deepcopy(hits[0]) if len(hits) == 1 else None


def merge_judgment(row: dict[str, Any], judgment: dict[str, Any] | None) -> dict[str, Any]:
    """把 agent 填的值并进 domain row。

    **表格里已有的值优先。** agent 读的是正文，表格是结构化原件；两者冲突时以原件
    为准，而且不能让一次模型调用悄悄改写 OCR 抽出来的数字。
    """
    if not judgment:
        return row
    merged = deepcopy(row)
    for path, value in (judgment.get("values") or {}).items():
        target = merged
        keys = str(path).split(".")
        for key in keys[:-1]:
            existing = target.get(key)
            target = existing if isinstance(existing, dict) else target.setdefault(key, {})
        if keys[-1] not in target:
            target[keys[-1]] = deepcopy(value)
    refs = merged.setdefault("evidenceRefs", [])
    for ref in judgment.get("evidenceRefs") or []:
        if ref not in refs:
            refs.append(deepcopy(ref))
    if judgment.get("rejected"):
        # 模型给了值但引用对不上的那些路径要留痕，不能只在日志里。
        merged["judgmentRejections"] = deepcopy(judgment["rejected"])
    return merged
