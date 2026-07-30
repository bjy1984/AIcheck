"""对话 Agent 执行治理：会话级互斥（内存槽 + DB 心跳）、执行记录生命周期、协同取消、中断恢复、后台执行 runner。

从 apps/api/routes.py 纯搬移抽离（B1 重构）；对 routes 命名空间的引用
统一经 _r() 晚绑定，保持 monkeypatch 与运行语义不变。
"""

from __future__ import annotations

import os
import threading
import time
from libs.db.repository import repo
from typing import Any, Iterable


def _r():
    """晚绑定访问 apps.api.routes 命名空间。

    抽离前这些引用都是 routes 模块全局名（晚绑定）；统一经 _r() 访问保持
    完全相同的语义 —— 测试对 routes 属性的 monkeypatch（如 qwen_runtime_client、
    review_conversation_agent_tool_output）依然对本模块内部调用生效。
    """
    from apps.api import routes

    return routes


REVIEW_SESSION_EXECUTION_LOCK = threading.Lock()
REVIEW_SESSION_ACTIVE_EXECUTIONS: dict[str, dict[str, Any]] = {}
REVIEW_SESSION_EXECUTION_STALE_SECONDS = float(
    os.getenv("AICHECK_REVIEW_CONVERSATION_EXECUTION_STALE_SECONDS", "900")
)


class ReviewConversationCancelled(Exception):
    """用户请求停止当前 Conversation Agent 回答。"""


def acquire_review_session_execution(session_id: str, execution_id: str) -> dict[str, Any] | None:
    """注册会话级执行槽。成功返回执行记录；该会话已有活跃执行时返回 None。

    执行线程已退出或超过陈旧阈值的残留槽位会被回收，避免异常退出后会话永久锁死。

    Postgres 模式下同时做跨进程 best-effort 互斥：其他 worker 心跳仍新鲜的 running
    执行记录视为占用。注意「检查—再登记」并非原子操作，仍存在毫秒级竞态窗口；
    完全原子性需要 DB 唯一约束或 advisory lock（见 AGENT_IMPLEMENTATION_REVIEW.md）。
    """
    if _r().postgres_persistence_configured():
        try:
            _r().refresh_state_from_postgres_for_live_read({"agent_executions"})
        except Exception:  # noqa: BLE001 - 刷新失败退回本地视图
            pass
        for record in repo.state.get("agent_executions", []):
            if (
                str(record.get("sessionId") or "") == session_id
                and str(record.get("status") or "") == "running"
                and str(record.get("id") or "") != execution_id
                and _r().agent_execution_heartbeat_fresh(record)
            ):
                return None
    now = time.monotonic()
    with _r().REVIEW_SESSION_EXECUTION_LOCK:
        existing = _r().REVIEW_SESSION_ACTIVE_EXECUTIONS.get(session_id)
        if existing is not None:
            started = float(existing.get("startedAtMonotonic") or 0.0)
            thread = existing.get("thread")
            thread_alive = bool(thread is not None and thread.is_alive())
            if thread_alive and now - started < _r().REVIEW_SESSION_EXECUTION_STALE_SECONDS:
                return None
            _r().REVIEW_SESSION_ACTIVE_EXECUTIONS.pop(session_id, None)
        entry: dict[str, Any] = {
            "executionId": execution_id,
            "sessionId": session_id,
            "cancelEvent": threading.Event(),
            "startedAtMonotonic": now,
            "startedAt": _r().server_time(),
            "thread": None,
        }
        _r().REVIEW_SESSION_ACTIVE_EXECUTIONS[session_id] = entry
        return entry


def release_review_session_execution(session_id: str, execution_id: str) -> None:
    with _r().REVIEW_SESSION_EXECUTION_LOCK:
        existing = _r().REVIEW_SESSION_ACTIVE_EXECUTIONS.get(session_id)
        if existing is not None and existing.get("executionId") == execution_id:
            _r().REVIEW_SESSION_ACTIVE_EXECUTIONS.pop(session_id, None)


def active_review_session_execution_view(session_id: str) -> dict[str, Any] | None:
    with _r().REVIEW_SESSION_EXECUTION_LOCK:
        entry = _r().REVIEW_SESSION_ACTIVE_EXECUTIONS.get(session_id)
        if entry is None:
            return None
        return {
            "executionId": entry.get("executionId"),
            "startedAt": entry.get("startedAt"),
        }


def review_conversation_execution_mode() -> str:
    """background：请求立即返回占位消息，Agent Loop 在后台线程执行；inline：同步执行（兼容/测试）。"""
    return (
        os.getenv("AICHECK_REVIEW_CONVERSATION_EXECUTION_MODE", "background").strip().lower()
    )


# 斜线命令精确匹配：只有显式以斜线命令开头的输入才路由到确定性回答。
# 自然语言问题（即使包含“检索证据”“查看条款”等字样）一律交给 Agent 处理，
# 避免快捷命令劫持普通提问。


def record_agent_execution_started(
    *,
    execution_id: str,
    session: dict[str, Any],
    assistant_message_id: str,
    review_run_id: str | None,
    execution_mode: str,
) -> dict[str, Any]:
    _r().ensure_review_session_state()
    record = {
        "id": execution_id,
        "schemaVersion": "ReviewAgentExecution@1",
        "sessionId": session.get("id"),
        "projectId": session.get("projectId"),
        "nodeId": session.get("nodeId"),
        "reviewRunId": review_run_id,
        "assistantMessageId": assistant_message_id,
        "executionMode": execution_mode,
        "status": "running",
        "cancelRequested": False,
        "turnCount": 0,
        "toolCallCount": 0,
        "failureReason": None,
        "startedAt": _r().server_time(),
        "startedEpoch": time.time(),
        "heartbeatAt": _r().server_time(),
        "heartbeatEpoch": time.time(),
        "finishedAt": None,
        "tenantId": _r().tenant_id_for_record(session),
        "createdAt": _r().server_time(),
        "updatedAt": _r().server_time(),
    }
    repo.state["agent_executions"].insert(0, record)
    _r().persist_review_session_records(agent_executions=[record])
    return record


def finalize_agent_execution_record(execution_id: str, **updates: Any) -> dict[str, Any] | None:
    record = repo.find_one("agent_executions", execution_id)
    if not record:
        return None
    record.update(updates)
    if not record.get("finishedAt"):
        record["finishedAt"] = _r().server_time()
    record["updatedAt"] = _r().server_time()
    _r().persist_review_session_records(agent_executions=[record])
    return record


def recover_interrupted_agent_executions(session: dict[str, Any]) -> None:
    """进程重启后，把仍标记为 running 但没有内存执行槽的执行记录收敛为 interrupted。

    同时把对应的占位 assistant 消息终结为 failed，避免前端永远等待。
    """
    _r().ensure_review_session_state()
    session_id = str(session.get("id") or "")
    with _r().REVIEW_SESSION_EXECUTION_LOCK:
        active = _r().REVIEW_SESSION_ACTIVE_EXECUTIONS.get(session_id)
        active_id = str((active or {}).get("executionId") or "")
    for record in repo.state.get("agent_executions", []):
        if str(record.get("sessionId") or "") != session_id:
            continue
        if str(record.get("status") or "") != "running":
            continue
        if str(record.get("id") or "") == active_id:
            continue
        if _r().agent_execution_heartbeat_fresh(record):
            # 心跳仍新鲜：该执行由其他进程（另一 worker / Celery）持有，不得误判为中断。
            continue
        record["status"] = "interrupted"
        record["failureReason"] = "EXECUTION_INTERRUPTED"
        record["finishedAt"] = _r().server_time()
        record["updatedAt"] = _r().server_time()
        _r().persist_review_session_records(agent_executions=[record])
        message = repo.find_one(
            "review_messages", str(record.get("assistantMessageId") or "")
        )
        if message is not None and message.get("status") == "running":
            message["status"] = "failed"
            message["contentBlocks"] = [
                {
                    "type": "text",
                    "text": "该回答执行因服务重启中断，请重新发送问题。",
                }
            ]
            message["execution"] = {
                **(message.get("execution") or {}),
                "failureReason": "EXECUTION_INTERRUPTED",
            }
            message["sequence"] = _r().next_review_session_sequence("review_messages", session_id)
            message["updatedAt"] = _r().server_time()
            _r().persist_review_session_records(review_messages=[message])
        _r().append_review_session_event(
            session,
            event_type="agent.execution.interrupted",
            title="检测到中断的 AI 执行，已标记为失败",
            payload={"executionId": record.get("id")},
        )


# ---- 会话级工具结果记忆 ----
# 同一会话内，不同消息之间复用只读/确定性工具结果；上下文动作（选证据、切换
# ReviewRun 等）会递增 toolMemoryRevision，旧版本条目自动失效。


REVIEW_SESSION_HEARTBEAT_STALE_SECONDS = max(
    30.0, float(os.getenv("AICHECK_REVIEW_CONVERSATION_HEARTBEAT_STALE_SECONDS", "180"))
)


def agent_execution_heartbeat_fresh(record: dict[str, Any]) -> bool:
    """心跳仍新鲜（epoch 秒差在阈值内）视为该执行仍在某个进程内存活。"""
    epoch = record.get("heartbeatEpoch") or record.get("startedEpoch")
    try:
        value = float(epoch)
    except (TypeError, ValueError):
        # 无 epoch（旧记录或数据损坏）视为不新鲜，允许恢复流程收敛。
        return False
    return (time.time() - value) < _r().REVIEW_SESSION_HEARTBEAT_STALE_SECONDS


def touch_agent_execution_heartbeat(execution_id: str) -> None:
    record = repo.find_one("agent_executions", execution_id)
    if record is None:
        return
    record["heartbeatEpoch"] = time.time()
    record["heartbeatAt"] = _r().server_time()
    record["updatedAt"] = _r().server_time()
    _r().persist_review_session_records(agent_executions=[record])


def review_conversation_cancel_requested(execution_id: str) -> bool:
    """跨进程取消：cancel_execution 动作把 cancelRequested 写入执行记录，
    Loop 每轮从共享存储刷新后检查，Celery worker / 其他进程也能被取消。"""
    if not execution_id:
        return False
    if _r().postgres_persistence_configured():
        try:
            _r().refresh_state_from_postgres_for_live_read({"agent_executions"})
        except Exception:  # noqa: BLE001 - 刷新失败时退回本地视图
            pass
    record = repo.find_one("agent_executions", execution_id)
    return bool(record is not None and record.get("cancelRequested"))


def run_review_conversation_execution(
    *,
    session_id: str,
    assistant_message_id: str,
    user_text: str,
    context: dict[str, Any],
    execution_entry: dict[str, Any],
) -> None:
    """执行 Conversation Agent Loop 并把结果回填到占位 assistant 消息。

    background 模式下运行在独立线程中，不得访问 Request；请求相关上下文均已在
    review_assistant_request_context 捕获为普通数据。完成或失败后重新给消息分配
    sequence，保证增量拉取（sequence > after）的客户端能看到最终内容。
    """
    execution_id = str(execution_entry.get("executionId") or "")
    try:
        session = repo.find_one("review_sessions", session_id)
        message = repo.find_one("review_messages", assistant_message_id)
        if not session or not message:
            return
        agent_result = _r().review_conversation_llm_answer(
            session,
            user_text,
            project=context["project"],
            node=context["node"],
            basis_items=context["basis_items"],
            evidence_links=context["evidence_links"],
            review_run=context["review_run"],
            readiness=context["readiness"],
            basis=context["basis"],
            cancel_event=execution_entry.get("cancelEvent"),
            execution_id=execution_id,
            episodic_memory=context.get("episodic_memory"),
        )
        blocks, execution = _r().review_agent_answer_blocks(
            agent_result, session=session, context=context
        )
        message["contentBlocks"] = blocks
        message["execution"] = execution
        message["status"] = "cancelled" if execution.get("mode") == "cancelled" else "completed"
        message["sequence"] = _r().next_review_session_sequence("review_messages", session_id)
        message["updatedAt"] = _r().server_time()
        # 滚动会话摘要：确定性抽取本轮问题/结论/工具/证据缺口，随会话持久化。
        _r().update_review_session_conversation_digest(
            session,
            user_text=user_text,
            answer_text=next(
                (str(block.get("text") or "") for block in blocks if block.get("type") == "text"),
                "",
            ),
            tools_used=agent_result.get("toolsUsed"),
            message_id=str(message["id"]),
            execution_mode=str(execution.get("mode") or "llm_agent"),
        )
        session["revision"] = _r().record_revision(session) + 1
        session["updatedAt"] = _r().server_time()
        _r().append_review_session_event(
            session,
            event_type="agent.message.completed",
            title="AI 复核助手已回复",
            payload={
                "messageId": message["id"],
                "contentBlockCount": len(blocks),
                "execution": repo.clone(execution),
            },
            review_run_id=str(message.get("reviewRunId") or "") or None,
        )
        _r().finalize_agent_execution_record(
            execution_id,
            status=str(message.get("status") or "completed"),
            turnCount=int(execution.get("turnCount") or 0),
            toolCallCount=int(execution.get("toolCallCount") or 0),
            provider=execution.get("provider"),
            model=execution.get("model"),
            usage=repo.clone(execution.get("usage")) if execution.get("usage") else None,
            failureReason=execution.get("failureReason"),
            finishedAt=_r().server_time(),
        )
        # 定向持久化：最终消息与会话状态立即对其他 worker 可见。
        _r().persist_review_session_records(
            review_messages=[message],
            review_sessions=[session],
        )
    except Exception as exc:  # noqa: BLE001 - 兜底：占位消息不能永远停留在 running
        failure_reason = str(getattr(exc, "reason", None) or exc.__class__.__name__)[:160]
        message = repo.find_one("review_messages", assistant_message_id)
        session = repo.find_one("review_sessions", session_id)
        if message:
            message["status"] = "failed"
            message["contentBlocks"] = [
                {
                    "type": "text",
                    "text": "本次 AI 回答执行失败，请稍后重试；已完成的执行动态见时间线。",
                }
            ]
            message["execution"] = {
                "executionId": execution_id,
                "mode": "deterministic_fallback",
                "modelCalled": False,
                "agentEnabled": True,
                "toolCallCount": 0,
                "turnCount": 0,
                "failureReason": failure_reason,
            }
            message["sequence"] = _r().next_review_session_sequence("review_messages", session_id)
            message["updatedAt"] = _r().server_time()
        if session:
            session["revision"] = _r().record_revision(session) + 1
            session["updatedAt"] = _r().server_time()
            _r().append_review_session_event(
                session,
                event_type="agent.message.failed",
                title="AI 回复生成失败",
                payload={"messageId": assistant_message_id, "failureReason": failure_reason},
            )
        _r().finalize_agent_execution_record(
            execution_id,
            status="failed",
            failureReason=failure_reason,
            finishedAt=_r().server_time(),
        )
        if message:
            _r().persist_review_session_records(review_messages=[message])
        if session:
            _r().persist_review_session_records(review_sessions=[session])
    finally:
        # 定向持久化已在成功/失败分支完成；此处只需释放会话执行槽。
        _r().release_review_session_execution(session_id, execution_id)

