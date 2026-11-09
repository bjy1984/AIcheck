"""「AI审查」对话助手的记忆接口：新对话、不再带上上次要点、个人回答偏好。

规则与取数在 review_session_memory；这里只是接口。独立 router，不往 routes.py 里加（巨石棘轮）。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, Header, Request

from apps.api import review_session_memory as memory
from apps.api import review_session_retention as retention
from apps.api import routes as api
from libs.contracts import errors
from libs.contracts.responses import fail, ok, server_time
from libs.db.repository import repo

review_session_memory_router = APIRouter()


def _writable_session(request: Request, session_id: str, if_match: str | None):
    """取一本可写的会话：存在、本人、在授权范围内、未结束、etag 对得上。"""
    api.ensure_review_session_state()
    session = repo.find_one("review_sessions", session_id)
    if not session:
        return None, fail(errors.NOT_FOUND, request)
    guard = api.mutation_guard(
        request,
        str(session.get("projectId") or ""),
        if_match="*",
        node_ids=[int(session.get("nodeId") or 0)],
    )
    if guard:
        return None, guard
    scope_error = api.review_session_scope_error(request, session)
    if scope_error:
        return None, scope_error
    precondition_error = api.review_session_precondition_error(request, session, if_match)
    if precondition_error:
        return None, precondition_error
    return session, None


def _touch(session: dict[str, Any]) -> None:
    session["revision"] = api.record_revision(session) + 1
    session["updatedAt"] = server_time()


def _flush_sessions(request: Request, *sessions: dict[str, Any]) -> None:
    # 只落这几本会话：事件由 append_review_session_event 自己即时落库
    request.state.scoped_flush_records = lambda: {"review_sessions": [repo.clone(item) for item in sessions]}


@review_session_memory_router.post("/review-sessions/{session_id}/restart")
def restart_review_session(
    request: Request,
    session_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    """结束当前对话、开一本新的。旧会话留档不删，新会话带上旧会话的几行要点。"""

    def produce():
        previous, error = _writable_session(request, session_id, if_match)
        if error:
            return error
        if api.active_review_session_execution_view(session_id):
            return fail(
                errors.CONFLICT,
                request,
                message="当前还有一次回答在执行，请等它完成或先停止，再开始新对话。",
                http_status=409,
            )
        project_id = str(previous.get("projectId") or "")
        node_id = int(previous.get("nodeId") or 0)
        project = repo.require_project(project_id) or {}
        node = repo.node(project_id, node_id) or {}
        basis = api.node_business_basis(project, node_id) or {}
        current_task, task_error = api.validated_plain_text(
            body.get("currentTask") or basis.get("inspectionItem") or node.get("name"),
            limit=300,
            field_name="当前任务",
        )
        if task_error:
            return fail(errors.VALIDATION_ERROR, request, message=task_error)
        carry_over = memory.build_carry_over(previous)
        retention.mark_archived(previous, reason="new_conversation", actor=memory.owner_id_for_request(request))
        session = memory.new_session_record(
            request,
            project_id,
            node_id,
            current_task=current_task or "",
            review_run_id=previous.get("activeReviewRunId"),
        )
        session["previousSessionId"] = previous.get("id")
        if carry_over:
            session["carryOver"] = carry_over
        repo.state["review_sessions"].insert(0, session)
        api.append_review_session_event(
            previous,
            event_type="session.archived",
            title="对话已结束，已开始新对话",
            payload={"nextSessionId": session["id"]},
        )
        api.append_review_session_event(
            session,
            event_type="session.created",
            title="AI 复核会话已建立（新对话）",
            payload={
                "currentTask": current_task,
                "previousSessionId": previous.get("id"),
                "carryOverItemCount": len((carry_over or {}).get("items") or []),
            },
        )
        _flush_sessions(request, previous, session)
        return ok(
            {
                "session": api.review_session_view(session),
                "archivedSessionId": previous.get("id"),
            },
            request,
        )

    return api.idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"sessionId": session_id, "action": "restart", "body": body},
    )


@review_session_memory_router.post("/review-sessions/{session_id}/carry-over/dismiss")
def dismiss_review_session_carry_over(
    request: Request,
    session_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    """不再把上一段对话的要点带给 AI：用户能看见 AI 被告知了什么，也能拿掉它。"""

    def produce():
        session, error = _writable_session(request, session_id, if_match)
        if error:
            return error
        if not session.get("carryOver"):
            return ok({"session": api.review_session_view(session)}, request)
        session["carryOver"] = None
        session["carryOverDismissedAt"] = server_time()
        _touch(session)
        api.append_review_session_event(
            session,
            event_type="session.context.updated",
            title="已不再带上上一段对话的要点",
            payload={"reason": "carry_over_dismissed"},
        )
        _flush_sessions(request, session)
        return ok({"session": api.review_session_view(session)}, request)

    return api.idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"sessionId": session_id, "action": "dismiss_carry_over"},
    )


def _preference_actor(request: Request):
    """回答偏好只给用得上对话助手的监检；按院＋本人存取，谁也读不到别人的。"""
    role, error = api.effective_role_for_request(request)
    if error:
        return None, error
    user_id = api.request_user_id(request)
    if role != "inspection" or not user_id:
        return None, fail(
            errors.FORBIDDEN,
            request,
            message="仅监检人员可设置 AI 回答偏好。",
            http_status=403,
        )
    return (api.request_tenant_id(request), user_id), None


def _preference_view(row: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "text": str((row or {}).get("text") or ""),
        "updatedAt": (row or {}).get("updatedAt"),
        "maxLength": memory.PREFERENCE_MAX_CHARS,
    }


@review_session_memory_router.get("/review-assistant/preferences")
def get_review_assistant_preferences(request: Request):
    actor, error = _preference_actor(request)
    if error:
        return error
    return ok({"preferences": _preference_view(memory.preference_row(*actor))}, request)


@review_session_memory_router.put("/review-assistant/preferences")
def put_review_assistant_preferences(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """保存或清空（传空字符串）个人回答偏好。清空保留这一行，只把文字置空。"""
    actor, error = _preference_actor(request)
    if error:
        return error
    text, text_error = api.validated_plain_text(
        body.get("text"),
        limit=memory.PREFERENCE_MAX_CHARS,
        field_name="回答偏好",
    )
    if text_error:
        return fail(errors.VALIDATION_ERROR, request, message=text_error)

    def produce():
        tenant_id, user_id = actor
        now = server_time()
        row = memory.preference_row(tenant_id, user_id)
        if row is None:
            row = {
                "id": f"RAPREF-{uuid4().hex[:10].upper()}",
                "tenantId": tenant_id,
                "userId": user_id,
                "createdAt": now,
                "revision": 0,
            }
            repo.state.setdefault(memory.PREFERENCES_COLLECTION, []).append(row)
        row["text"] = text or ""
        row["updatedAt"] = now
        row["revision"] = int(row.get("revision") or 0) + 1
        repo.add_audit(
            "清空 AI 回答偏好" if not text else "更新 AI 回答偏好",
            "ReviewAssistantPreference",
            row["id"],
        )
        request.state.scoped_flush_records = lambda: {memory.PREFERENCES_COLLECTION: [repo.clone(row)]}
        return ok({"preferences": _preference_view(row)}, request)

    return api.idempotent(request, idempotency_key, produce, fingerprint_source={"body": body})
