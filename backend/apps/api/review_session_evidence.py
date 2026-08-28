"""会话工具记忆的证据指纹失效（自 routes.py 拆出，棘轮约束）。

只有会话上下文动作才失效记忆是不够的：自动挂载不经过那个端点，
缓存的资质核对结果会把新上传的证书挡在视野外（2026-08-29 审计发现）。
"""

from __future__ import annotations

from typing import Any

from libs.contracts.responses import server_time
from libs.db.repository import repo


def review_session_evidence_fingerprint(session: dict[str, Any]) -> str:
    """本会话节点的证据指纹：证据链接与绑定的 (id, revision, 状态) 稳定哈希。

    任何证据变化（自动挂载、人工绑定、驳回）都会改变指纹。"""
    from apps.api.routes import stable_hash_payload

    project_id = str(session.get("projectId") or "")
    node_id = int(session.get("nodeId") or 0)
    rows = []
    for state_key in ("node_evidence_links", "bindings"):
        for row in repo.state.get(state_key, []):
            if (
                str(row.get("projectId") or "") == project_id
                and int(row.get("nodeId") or 0) == node_id
            ):
                rows.append(
                    (
                        state_key,
                        str(row.get("id") or ""),
                        int(row.get("revision") or 0),
                        str(row.get("manualStatus") or row.get("bindingStatus") or ""),
                    )
                )
    return stable_hash_payload(sorted(rows))


def refresh_review_session_evidence_fingerprint(session: dict[str, Any]) -> bool:
    """证据指纹变化时使会话工具记忆失效；返回是否失效过。

    首次（会话尚无指纹）只记指纹不失效——那时记忆本来就是空的。"""
    from apps.api.routes import (
        append_review_session_event,
        review_session_tool_memory_revision,
    )

    fingerprint = review_session_evidence_fingerprint(session)
    previous = str(session.get("evidenceFingerprint") or "")
    if previous == fingerprint:
        return False
    session["evidenceFingerprint"] = fingerprint
    if not previous:
        return False
    session["toolMemoryRevision"] = review_session_tool_memory_revision(session) + 1
    session["updatedAt"] = server_time()
    append_review_session_event(
        session,
        event_type="session.context.updated",
        title="节点证据已变化，会话工具记忆已失效",
        payload={"reason": "evidence_fingerprint_changed"},
    )
    return True
