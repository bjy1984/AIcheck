"""「AI审查」对话助手的记忆（2026-11-09，对照 Anthropic〈The components of agent memory〉）。

平台里只有这一个 AI 会记事。会话按「院＋项目＋节点＋监检本人」各开一本，对话全文进库。
这里管四件事，独立模块，不往 routes.py 里加（巨石棘轮）：

1. 会话归属：按编号读写会话时也只认本人。原先只有「找我的会话」按本人过滤，
   同院同节点的另一位监检拿到编号就能读别人的对话、往里发问（11-09 实测）。
2. 对话历史的时效：只带最近 HISTORY_DAYS 天；证据或 ReviewRun 变过之后的旧回答
   标 staleContext。文章说得直白：过期的笔记，后来的会话会读到并相信它。
   工具记忆早就随证据指纹失效，对话历史一直没有——上周说「焊工证过期」，
   施工方补交之后再问，模型看到的还是那句旧结论。
3. 新对话与交接要点：结束当前会话（留档不删），新会话开头带上上一本的几行要点。
   要点用确定性方式摘，不让模型自己写：审查结论以确定性工具和人工确认为准，
   AI 自己写下的东西不能变成「事实」。
4. 个人回答偏好：每人一段自己写、可改可清的短文字，只影响表达方式，不影响判定。

会话路由仍在 routes.py，这里的函数由它调用；routes.py 反过来被这里按需导入（同
review_session_evidence 的做法），所以对 routes 的引用都放在函数里。
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from libs.contracts import errors
from libs.contracts.responses import SERVER_TZ, fail, server_time
from libs.db.repository import repo

HISTORY_DAYS = max(1, int(os.getenv("AICHECK_REVIEW_CONVERSATION_HISTORY_DAYS", "7")))
RECENT_MESSAGE_LIMIT = 6
MESSAGE_CHARS = 1200
CARRY_OVER_ITEM_LIMIT = 5
CARRY_OVER_UNANSWERED_LIMIT = 3
QUESTION_CHARS = 120
ANSWER_CHARS = 200
PREFERENCE_MAX_CHARS = 300
PREFERENCES_COLLECTION = "review_assistant_preferences"
# 没有落定的回答不进记忆：占位「正在核查中…」和失败提示都不是模型说过的话
UNSETTLED_STATUSES = {"running", "failed", "cancelled"}
# 模型没跑成时的降级文案（「本次未能回答你的问题…」）同理：它说的是「没答上」，不是答案
FALLBACK_MODES = {"deterministic_fallback", "local_disabled_fallback"}


# ---- 1. 会话归属 ----


def owner_id_for_request(request: Request) -> str:
    from apps.api import routes as api

    return api.request_user_id(request) or "USER-UNKNOWN"


def session_owner_error(request: Request, session: dict[str, Any]) -> JSONResponse | None:
    """不是本人的会话一律按「不存在」回，别人的会话连存在与否都不透露。"""
    owner = str(session.get("createdBy") or "")
    if owner and owner != owner_id_for_request(request):
        return fail(errors.NOT_FOUND, request)
    return None


def session_closed_error(request: Request, session: dict[str, Any]) -> JSONResponse | None:
    """已结束的对话只读：能翻看，不能再发问或改上下文。"""
    if str(session.get("status") or "active") == "active":
        return None
    return fail(
        errors.CONFLICT,
        request,
        message="这段对话已结束，请在新对话里继续。",
        http_status=409,
    )


def new_session_record(
    request: Request,
    project_id: str,
    node_id: int,
    *,
    current_task: str,
    review_run_id: Any = None,
) -> dict[str, Any]:
    from apps.api import routes as api

    now = server_time()
    confirmed_evidence_ids = [
        str(item.get("id"))
        for item in api.build_node_evidence_readiness(repo, project_id, node_id).get("nodeEvidenceLinks", [])
        if item.get("id") and item.get("manualStatus") == "confirmed"
    ]
    return {
        "id": f"RSESSION-{uuid4().hex[:10].upper()}",
        "projectId": project_id,
        "nodeId": node_id,
        "role": api.effective_role_for_request(request)[0] or "inspection",
        "status": "active",
        "currentTask": current_task,
        "activeReviewRunId": review_run_id,
        "selectedEvidenceLinkIds": confirmed_evidence_ids,
        "selectedJudgmentIds": [],
        "contextRevision": 1,
        "revision": 1,
        "createdBy": owner_id_for_request(request),
        "createdByName": api.request_actor_name(request),
        "tenantId": api.request_tenant_id(request),
        "createdAt": now,
        "updatedAt": now,
    }


# ---- 2. 对话历史的时效 ----


def parse_server_time(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=SERVER_TZ)
    except ValueError:
        return None


def message_context_stamp(session: dict[str, Any]) -> dict[str, Any]:
    """回答落库时记下当时的证据指纹，之后据此判断它是不是在旧证据下说的。"""
    return {"evidenceFingerprint": str(session.get("evidenceFingerprint") or "")}


def message_text(message: dict[str, Any]) -> str:
    return "\n".join(
        str(block.get("text") or "")
        for block in message.get("contentBlocks") or []
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
    )


def answer_unsettled(message: dict[str, Any]) -> bool:
    if str(message.get("status") or "") in UNSETTLED_STATUSES:
        return True
    execution = message.get("execution") if isinstance(message.get("execution"), dict) else {}
    return str(execution.get("mode") or "") in FALLBACK_MODES


def session_messages(session_id: str) -> list[dict[str, Any]]:
    rows = [item for item in repo.state.get("review_messages", []) if item.get("sessionId") == session_id]
    return sorted(rows, key=lambda item: int(item.get("sequence") or 0))


def settled_session_messages(session_id: str) -> list[dict[str, Any]]:
    return [item for item in session_messages(session_id) if not answer_unsettled(item)]


def answer_is_stale(message: dict[str, Any], *, fingerprint: str, review_run_id: str) -> bool:
    # 没有指纹的是本次改动之前的老回答：当时的证据已无从核对，按需重新核实处理
    if "evidenceFingerprint" not in message:
        return True
    if str(message.get("evidenceFingerprint") or "") != fingerprint:
        return True
    return str(message.get("reviewRunId") or "") != review_run_id


def last_message_at(session_id: str) -> datetime | None:
    stamps = [
        parse_server_time(item.get("createdAt"))
        for item in repo.state.get("review_messages", [])
        if item.get("sessionId") == session_id
    ]
    stamps = [stamp for stamp in stamps if stamp is not None]
    return max(stamps) if stamps else None


def history_cutoff(now: datetime | None = None) -> datetime:
    return (now or datetime.now(SERVER_TZ)) - timedelta(days=HISTORY_DAYS)


def recent_conversation(
    session: dict[str, Any],
    *,
    user_text: str,
    review_run_id: str,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """交给模型的近期对话：只含最近 HISTORY_DAYS 天、已落定的消息，不含本次提问本身。"""
    cutoff = history_cutoff(now)
    fingerprint = str(session.get("evidenceFingerprint") or "")
    rows = []
    for item in settled_session_messages(str(session.get("id") or "")):
        created = parse_server_time(item.get("createdAt"))
        text = message_text(item)
        if not text or (created is not None and created < cutoff):
            continue
        rows.append((item, text))
    # 本次提问已经先落库了，它在 question 字段里，不该在「历史」里再出现一次
    if rows and rows[-1][0].get("role") == "user" and rows[-1][1].strip() == user_text.strip():
        rows.pop()
    conversation = []
    for item, text in rows[-RECENT_MESSAGE_LIMIT:]:
        entry: dict[str, Any] = {
            "role": item.get("role"),
            "at": item.get("createdAt"),
            "text": text[:MESSAGE_CHARS],
        }
        if item.get("role") == "assistant":
            entry["staleContext"] = answer_is_stale(
                item, fingerprint=fingerprint, review_run_id=review_run_id
            )
        conversation.append(entry)
    return conversation


def conversation_memory_context(
    session: dict[str, Any],
    *,
    user_text: str,
    review_run_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """一次提问带给模型的全部记忆：近期对话、上一段对话要点、个人回答偏好。"""
    context: dict[str, Any] = {
        "recentConversation": recent_conversation(
            session, user_text=user_text, review_run_id=review_run_id, now=now
        ),
        "conversationHistoryDays": HISTORY_DAYS,
    }
    carry_over = session.get("carryOver")
    if isinstance(carry_over, dict) and (carry_over.get("items") or carry_over.get("unanswered")):
        context["previousSession"] = {
            "lastActivityAt": carry_over.get("lastActivityAt"),
            "items": repo.clone(carry_over.get("items") or []),
            "unanswered": repo.clone(carry_over.get("unanswered") or []),
            "notice": "上一段对话的要点，只作线索；结论必须按当前证据重新核实。",
        }
    preference = preference_text(
        str(session.get("tenantId") or ""), str(session.get("createdBy") or "")
    )
    if preference:
        context["userPreferences"] = preference
    return context


def session_memory_view(session: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """给界面看的记忆状态：AI 参考多少天的对话、这本会话是否已闲置过期。"""
    last = last_message_at(str(session.get("id") or ""))
    return {
        "historyDays": HISTORY_DAYS,
        "lastMessageAt": last.strftime("%Y-%m-%d %H:%M:%S") if last else None,
        "historyExpired": bool(last and last < history_cutoff(now)),
    }


# ---- 3. 新对话与交接要点 ----

_TABLE_ROW = re.compile(r"^\s*\|")
_LINK = re.compile(r"\[([^\]]+)\]\((?:basis|evidence):[^)]+\)")
_MARKDOWN_NOISE = re.compile(r"^[#>*\-\s]+|[*`]+")
_CONCLUSION_CELL = re.compile(r"\|\s*结论[^|\n]*\|\s*([^|\n]+)")


def answer_verdict(text: str) -> str | None:
    """只从表格的「结论」格里认结论；散文里的「符合」多半是「是否符合」，不能当结论。"""
    match = _CONCLUSION_CELL.search(text)
    if not match:
        return None
    cell = match.group(1)
    for verdict in ("不符合", "证据不足", "符合"):
        if verdict in cell:
            return verdict
    return None


def answer_gist(text: str) -> str:
    """回答的第一句说明：跳过表格和标题，去掉引用链接和 Markdown 记号。"""
    for line in text.splitlines():
        if not line.strip() or _TABLE_ROW.match(line) or line.lstrip().startswith("#"):
            continue
        plain = _MARKDOWN_NOISE.sub("", _LINK.sub(r"\1", line)).strip()
        if plain:
            return plain[:ANSWER_CHARS]
    return ""


def build_carry_over(previous: dict[str, Any]) -> dict[str, Any] | None:
    """从上一本会话摘几行要点：问了什么、当时怎么答的、哪些没答完。

    斜杠命令（/检索证据 等）不算问题；没有落定的回答、模型没跑成的降级回答都算「没答完」。"""
    rows = session_messages(str(previous.get("id") or ""))
    items: list[dict[str, Any]] = []
    unanswered: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None

    def close_pending() -> None:
        if pending is not None:
            unanswered.append({"askedAt": pending.get("createdAt"), "question": message_text(pending)[:QUESTION_CHARS]})

    for item in rows:
        if item.get("role") == "user":
            close_pending()
            text = message_text(item).strip()
            pending = item if text and not text.startswith("/") else None
            continue
        if pending is None or item.get("role") != "assistant":
            continue
        if answer_unsettled(item):
            close_pending()
        else:
            answer = message_text(item)
            items.append(
                {
                    "askedAt": pending.get("createdAt"),
                    "question": message_text(pending)[:QUESTION_CHARS],
                    "verdict": answer_verdict(answer),
                    "answer": answer_gist(answer),
                }
            )
        pending = None
    close_pending()
    if not items and not unanswered:
        return None
    last = last_message_at(str(previous.get("id") or ""))
    return {
        "fromSessionId": previous.get("id"),
        "lastActivityAt": last.strftime("%Y-%m-%d %H:%M:%S") if last else previous.get("updatedAt"),
        "items": items[-CARRY_OVER_ITEM_LIMIT:],
        "unanswered": unanswered[-CARRY_OVER_UNANSWERED_LIMIT:],
        "createdAt": server_time(),
    }


# ---- 4. 个人回答偏好 ----


def preference_row(tenant_id: str, user_id: str) -> dict[str, Any] | None:
    if not tenant_id or not user_id:
        return None
    return next(
        (
            row
            for row in repo.state.get(PREFERENCES_COLLECTION, [])
            if str(row.get("tenantId") or "") == tenant_id and str(row.get("userId") or "") == user_id
        ),
        None,
    )


def preference_text(tenant_id: str, user_id: str) -> str:
    row = preference_row(tenant_id, user_id) or {}
    return str(row.get("text") or "").strip()[:PREFERENCE_MAX_CHARS]
