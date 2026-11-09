"""「AI审查」对话的保留期限（2026-11-09，agent-memory 评估 F 项）。

两件事：

1. **回答落定后压缩流式增量事件。** 串流时每一小段正文、推理都落一条
   `agent.message.delta` / `agent.reasoning.delta`（生产 11-09：128 + 38 条、约 129 KB，
   占会话事件的三分之一），它们只在「回答还在跑」时给前端渐进显示用
   （ConversationalReviewWorkbenchB.applyStreamingDeltas 只认 running 的占位消息）。
   回答落定后，正文和推理都已存进最终消息，增量就是重复的一份——整库常驻 API 内存，
   重复的一份就是白占内存。
   **只在存档完整时压**：正文在 review_conversation_llm_answer 里截到 4000 字，推理存档超过
   24000 字会丢掉较早的轮次或截掉超长的一轮（review_reasoning_transcript 会写明「完整内容见
   会话事件流」）。这两种情况下增量是唯一的全量记录，留着不动。
   正文增量只压最后一轮的：前几轮模型边调工具边说的话不在最终消息里，那些增量是唯一的记录。
   **压的是内容不是行**：事件列表按发生时间重排编号，前端拿编号当游标增量拉取；删行会让
   编号整体前移，正在轮询的页面就漏掉新事件。所以行和编号都留着，只去掉 payload.content，
   记下原长度和存进了哪条消息；payloadHash 仍是原文的指纹。

2. **闲置的会话自动归档。** 超过 AICHECK_REVIEW_SESSION_ARCHIVE_AFTER_MONTHS 个月（按 30 天
   一个月；0 = 不归档）没有任何对话的会话，不再当作「当前会话」，下次打开时归档（只读、留档、
   能翻看，和「新对话」一样），新会话带上它的要点。用户一直不回来的，由
   scripts/review_session_retention.py 批量归档。
   **前端建会话用固定的幂等键**，请求中间件按键原样重放旧响应——会话归档后再用老键去建，
   拿回来的永远是那本已归档的。所以工作区额外给一个「会话代次」（最近一本不能再用的会话编号），
   前端拼进键里：同一代内重试照样去重，换代才真的新建。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

from fastapi import Request

from apps.api import review_session_index
from apps.api import review_session_memory as memory
from libs.contracts.responses import SERVER_TZ, server_time
from libs.db.repository import repo

ARCHIVE_AFTER_MONTHS = max(0.0, float(os.getenv("AICHECK_REVIEW_SESSION_ARCHIVE_AFTER_MONTHS", "3")))
DAYS_PER_MONTH = 30
STREAM_DELTA_EVENTS = {"agent.message.delta", "agent.reasoning.delta"}
# 与 routes.review_conversation_llm_answer 里 `"text": content[:4000]` 一致：到了这个长度就可能是被截过的
ANSWER_TEXT_ARCHIVE_CHARS = 4000
# review_reasoning_transcript 截断时写进存档的字样：见到就说明存档不全
REASONING_TRUNCATION_MARKERS = ("未存档", "已截去")


# ---- 1. 压缩流式增量 ----


def answer_archive_complete(message: dict[str, Any]) -> bool:
    """最终消息里的正文与推理是不是全量：是，增量才是重复的。"""
    execution = message.get("execution") if isinstance(message.get("execution"), dict) else {}
    if message.get("role") != "assistant" or str(message.get("status") or "") != "completed":
        return False
    if str(execution.get("mode") or "") != "llm_agent":
        return False
    if len(memory.message_text(message)) >= ANSWER_TEXT_ARCHIVE_CHARS:
        return False
    reasoning = "\n".join(
        str(block.get("text") or "")
        for block in message.get("contentBlocks") or []
        if isinstance(block, dict) and block.get("type") == "reasoning"
    )
    return not any(marker in reasoning for marker in REASONING_TRUNCATION_MARKERS)


def stream_deltas_with_content(message: dict[str, Any]) -> list[dict[str, Any]]:
    """这条回答名下、还带着正文的增量事件（不管能不能压）。"""
    execution = message.get("execution") if isinstance(message.get("execution"), dict) else {}
    execution_id = str(execution.get("executionId") or "")
    if not execution_id:
        return []
    return [
        event
        for event in review_session_index.session_rows("review_session_events", str(message.get("sessionId") or ""))
        if event.get("eventType") in STREAM_DELTA_EVENTS
        and isinstance(event.get("payload"), dict)
        and str(event["payload"].get("executionId") or "") == execution_id
        and "content" in event["payload"]
    ]


def delta_archived_in_message(event: dict[str, Any], message: dict[str, Any]) -> bool:
    """这条增量的内容在最终消息里有没有一份。

    推理每一轮都进存档；正文只有最后一轮进最终消息——前面几轮模型边调工具边说的话
    （「初步说明：我先核对当前上下文」）别处没有，压了就丢了。"""
    if event.get("eventType") == "agent.reasoning.delta":
        return True
    execution = message.get("execution") if isinstance(message.get("execution"), dict) else {}
    final_turn = execution.get("turnCount")
    turn = (event.get("payload") or {}).get("turn")
    return final_turn is not None and turn is not None and int(turn) == int(final_turn)


def compactable_stream_deltas(message: dict[str, Any]) -> list[dict[str, Any]]:
    """能压的增量：存档完整、且内容确实在最终消息里的那些；回答没落定或存档被截过都返回空。"""
    if not answer_archive_complete(message):
        return []
    return [event for event in stream_deltas_with_content(message) if delta_archived_in_message(event, message)]


def compact_stream_deltas(message: dict[str, Any]) -> list[dict[str, Any]]:
    """去掉增量事件里与最终消息重复的正文；返回改过的事件，调用方负责落库。"""
    events = compactable_stream_deltas(message)
    now = server_time()
    for event in events:
        payload = dict(event["payload"])
        content = str(payload.pop("content", "") or "")
        payload.update(
            {
                "compacted": True,
                "chars": len(content),
                "archivedInMessageId": message.get("id"),
                "compactedAt": now,
            }
        )
        event["payload"] = payload
    return events


# ---- 2. 闲置会话归档 ----


def session_last_activity(session: dict[str, Any]) -> datetime | None:
    """最后一次对话的时间；没说过话就按建会话的时间。系统动作（证据变化、跟随新运行）不算。"""
    stamps = [memory.last_message_at(str(session.get("id") or "")), memory.parse_server_time(session.get("createdAt"))]
    stamps = [stamp for stamp in stamps if stamp is not None]
    return max(stamps) if stamps else None


def session_idle_expired(session: dict[str, Any], *, now: datetime | None = None) -> bool:
    if ARCHIVE_AFTER_MONTHS <= 0 or str(session.get("status") or "active") != "active":
        return False
    last = session_last_activity(session)
    if last is None:
        return False
    return last < (now or datetime.now(SERVER_TZ)) - timedelta(days=ARCHIVE_AFTER_MONTHS * DAYS_PER_MONTH)


def mark_archived(session: dict[str, Any], *, reason: str, actor: str) -> None:
    now = server_time()
    session["status"] = "archived"
    session["archivedAt"] = now
    session["archivedBy"] = actor
    session["archivedReason"] = reason
    session["revision"] = int(session.get("revision") or 1) + 1
    session["updatedAt"] = now


def _own_node_sessions(request: Request, project_id: str, node_id: int) -> list[dict[str, Any]]:
    from apps.api import routes as api

    owner = memory.owner_id_for_request(request)
    tenant = api.request_tenant_id(request)
    return [
        item
        for item in repo.state.get("review_sessions", [])
        if item.get("projectId") == project_id
        and int(item.get("nodeId") or 0) == int(node_id)
        and item.get("createdBy") == owner
        and api.tenant_id_for_record(item) == tenant
    ]


def archive_idle_sessions(request: Request, project_id: str, node_id: int) -> list[dict[str, Any]]:
    """本人在这个节点上闲置超期的会话改成已归档（建新会话时调），返回改过的会话。"""
    from apps.api import routes as api

    archived = []
    for session in _own_node_sessions(request, project_id, node_id):
        if not session_idle_expired(session):
            continue
        mark_archived(session, reason="idle", actor="system:idle")
        api.append_review_session_event(
            session,
            event_type="session.archived",
            title=f"对话闲置超过 {ARCHIVE_AFTER_MONTHS:g} 个月，已归档",
            payload={"reason": "idle", "archiveAfterMonths": ARCHIVE_AFTER_MONTHS},
        )
        archived.append(session)
    return archived


def latest_closed_session(request: Request, project_id: str, node_id: int) -> dict[str, Any] | None:
    """本人在这个节点上最近一本不能再用的会话：已归档，或闲置超期还没来得及归档。"""
    closed = [
        item
        for item in _own_node_sessions(request, project_id, node_id)
        if str(item.get("status") or "active") != "active" or session_idle_expired(item)
    ]
    return max(closed, key=lambda item: str(item.get("createdAt") or ""), default=None)


def session_generation(request: Request, project_id: str, node_id: int) -> str:
    """前端建会话的幂等键要拼上它：上一本会话不能用了，键就得换，否则中间件重放旧响应。"""
    return str((latest_closed_session(request, project_id, node_id) or {}).get("id") or "")


def link_previous_session(request: Request, session: dict[str, Any], project_id: str, node_id: int) -> None:
    """新会话接上上一本（已归档的）会话：记下编号、带上要点。"""
    previous = latest_closed_session(request, project_id, node_id)
    if not previous or previous.get("id") == session.get("id"):
        return
    session["previousSessionId"] = previous.get("id")
    carry_over = memory.build_carry_over(previous)
    if carry_over:
        session["carryOver"] = carry_over
