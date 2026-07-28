"""Version B 对话 Agent 端点级冒烟测试（直接调用端点函数，绕过 HTTP 层）。

用法：cd backend && python scripts/run_review_b_smoke.py（无需 pytest，正常安装环境即可跑）。
覆盖 13 条端点级冒烟：斜线精确匹配、Agent Loop 去重与强制收束、单工具错误隔离、
模型重试、串流 delta、会话工具记忆、Token 预算、后台执行/取消/忙锁、执行记录与心跳、
Celery 回退、中断恢复。使用真实 repo 种子数据与真实执行路径，仅绕过 HTTP 路由层，
因此不替代 pytest 全量套件（HTTP 契约、鉴权中间件等仍由 tests/ 覆盖）。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback

os.environ.setdefault("AICHECK_ENABLE_DEMO_DATA", "true")
os.environ.setdefault("AICHECK_ENABLE_COMPATIBILITY_MOCKS", "true")
os.environ.setdefault("AICHECK_OCR_PROVIDER_MODE", "local")
os.environ.setdefault("AICHECK_ALLOW_DEV_TOKENS", "true")
os.environ["AICHECK_REVIEW_CONVERSATION_EXECUTION_MODE"] = "inline"

from starlette.requests import Request

from apps.api import routes as R
from libs.db.repository import repo
from libs.integrations.errors import IntegrationServiceError

PROJECT_ID = "P-2026-HDCP-001"
NODE_ID = 1
RESULTS: list[tuple[str, str, str]] = []
_key_counter = [0]


def fake_request(path: str = "/api/test", method: str = "POST") -> Request:
    headers = [
        (b"x-role", b"inspection"),
        (b"x-user-id", b"USER-INSPECTION-001"),
        (b"host", b"testserver"),
    ]
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "scheme": "http",
        "app": None,
    }
    return Request(scope)


def payload_of(response) -> dict:
    if isinstance(response, dict):  # ok() 返回普通 dict；fail() 返回 JSONResponse
        return response
    return json.loads(bytes(response.body))


def assert_ok(response) -> dict:
    data = payload_of(response)
    assert data.get("code") == 0, f"non-zero code: {data}"
    return data["data"]


def next_key(prefix: str) -> str:
    _key_counter[0] += 1
    return f"{prefix}-{_key_counter[0]}"


def reset_state() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None
    with R.REVIEW_SESSION_EXECUTION_LOCK:
        R.REVIEW_SESSION_ACTIVE_EXECUTIONS.clear()


def create_session() -> dict:
    data = assert_ok(
        R.create_node_review_session(
            fake_request(), PROJECT_ID, NODE_ID,
            body={"currentTask": "核对设计单位许可证"},
            idempotency_key=next_key("session"),
        )
    )
    return data["session"]


def post_message(session: dict, content: str, *, etag: str | None = None) -> dict:
    return assert_ok(
        R.create_review_session_message(
            fake_request(), session["id"],
            body={"content": content},
            idempotency_key=next_key("msg"),
            if_match=etag or session["etag"],
        )
    )


def get_events(session_id: str) -> list[dict]:
    return assert_ok(R.list_review_session_events(fake_request(method="GET"), session_id, after=0))["events"]


def get_messages(session_id: str) -> list[dict]:
    return assert_ok(R.list_review_session_messages(fake_request(method="GET"), session_id, after=0))["messages"]


def wait_final(session_id: str, message_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        message = next((m for m in get_messages(session_id) if m["id"] == message_id), None)
        if message and message.get("status") != "running":
            return message
        time.sleep(0.05)
    raise AssertionError("assistant message did not finalize in time")


def run(name: str, func) -> None:
    reset_state()
    saved_env = dict(os.environ)
    saved_qwen = R.qwen_runtime_client
    saved_tool_output = R.review_conversation_agent_tool_output
    try:
        func()
        RESULTS.append((name, "PASS", ""))
    except Exception:
        RESULTS.append((name, "FAIL", traceback.format_exc(limit=8)))
    finally:
        R.qwen_runtime_client = saved_qwen
        R.review_conversation_agent_tool_output = saved_tool_output
        os.environ.clear()
        os.environ.update(saved_env)


def make_runtime(handler):
    class _Runtime:
        def chat_sync(self, messages, model, **kwargs):
            return handler(messages, model, **kwargs)

    return _Runtime()


# ---------------- tests ----------------

def test_slash_deterministic_basis():
    session = create_session()
    data = post_message(session, "/标准条款")
    assert data["status"] == "completed"
    blocks = data["assistantMessage"]["contentBlocks"]
    assert any(b["type"] == "basis_card" for b in blocks), blocks
    messages = get_messages(session["id"])
    assert [m["sequence"] for m in messages] == [1, 2]
    events = get_events(session["id"])
    assert [e["eventType"] for e in events[:3]] == [
        "session.created", "user.message.created", "agent.message.completed",
    ]


def test_natural_language_not_hijacked():
    os.environ["AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION"] = "litellm"
    R.qwen_runtime_client = lambda: make_runtime(
        lambda messages, model, **k: {
            "provider": "t", "model": "m",
            "choices": [{"message": {"content": "这是 Agent 的回答。"}}],
        }
    )
    session = create_session()
    data = post_message(session, "为什么不能补充证据？帮我查看条款相关的问题。")
    execution = data["assistantMessage"]["execution"]
    assert execution["mode"] == "llm_agent", execution
    texts = [b["text"] for b in data["assistantMessage"]["contentBlocks"] if b["type"] == "text"]
    assert texts == ["这是 Agent 的回答。"], texts


def test_free_form_agent_context_and_references():
    os.environ["AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION"] = "litellm"
    seen = {}

    def handler(messages, model, **kwargs):
        seen["model"] = model
        seen["has_fixed_basis"] = '"fixedBasis"' in str(messages[-1].get("content") or "")
        seen["prompt_has_citation_rule"] = "[显示文本](basis:basisRefId)" in str(messages[0].get("content") or "")
        return {
            "provider": "test-qwen", "model": "qwen-review-test",
            "choices": [{"message": {"content": "当前证据仍需人工确认。"}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 28},
        }

    R.qwen_runtime_client = lambda: make_runtime(handler)
    session = create_session()
    data = post_message(session, "请结合当前证据说明许可证有效期风险。")
    execution = data["assistantMessage"]["execution"]
    assert seen == {"model": "review-chat", "has_fixed_basis": True, "prompt_has_citation_rule": True}, seen
    assert execution["mode"] == "llm_agent" and execution["modelCalled"] is True
    assert execution["usage"] == {"inputTokens": 120, "outputTokens": 28, "totalTokens": 148}, execution
    text_block = next(b for b in data["assistantMessage"]["contentBlocks"] if b["type"] == "text")
    basis_refs = [r for r in text_block["references"] if r["kind"] == "basis"]
    assert basis_refs and basis_refs[0]["referenceId"].startswith("LOC-"), basis_refs[:1]


def test_tool_loop_dedup_and_max_turns():
    os.environ["AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION"] = "litellm"
    os.environ["AICHECK_REVIEW_CONVERSATION_AGENT_MAX_TURNS"] = "3"
    calls = {"n": 0, "tool_choices": []}

    def handler(messages, model, **kwargs):
        calls["n"] += 1
        calls["tool_choices"].append(kwargs.get("tool_choice"))
        if kwargs.get("tool_choice") == "none":
            assert "轮次上限" in str(messages[-1].get("content") or "")
            return {"provider": "t", "model": "m", "choices": [{"message": {"content": "已收束。"}}]}
        return {
            "provider": "t", "model": "m",
            "choices": [{"message": {"content": "", "tool_calls": [
                {"id": f"c{calls['n']}", "function": {"name": "get_review_context", "arguments": "{}"}}
            ]}}],
        }

    R.qwen_runtime_client = lambda: make_runtime(handler)
    session = create_session()
    data = post_message(session, "请核查名称一致性。")
    execution = data["assistantMessage"]["execution"]
    assert execution["turnCount"] == 3 and calls["tool_choices"] == ["auto", "auto", "none"], (execution, calls)
    dup_flags = [e["payload"].get("duplicate") for e in get_events(session["id"])
                 if e["eventType"] == "agent.tool_call.completed"]
    assert dup_flags == [False, True], dup_flags


def test_tool_failure_isolated():
    os.environ["AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION"] = "litellm"
    calls = {"n": 0, "saw_failed_tool_msg": False}

    def handler(messages, model, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"provider": "t", "model": "m", "choices": [{"message": {"content": "", "tool_calls": [
                {"id": "c1", "function": {"name": "get_review_context", "arguments": "{}"}}]}}]}
        calls["saw_failed_tool_msg"] = any(
            '"failed"' in str(m.get("content") or "") for m in messages if m.get("role") == "tool")
        return {"provider": "t", "model": "m", "choices": [{"message": {"content": "尽管工具失败，仍给出结论。"}}]}

    def broken(tool_name, arguments, **kwargs):
        raise RuntimeError("tool exploded")

    R.qwen_runtime_client = lambda: make_runtime(handler)
    R.review_conversation_agent_tool_output = broken
    session = create_session()
    data = post_message(session, "请核查当前节点。")
    execution = data["assistantMessage"]["execution"]
    assert execution["mode"] == "llm_agent" and execution["toolCallCount"] == 1, execution
    assert calls["saw_failed_tool_msg"] is True
    failed = [e for e in get_events(session["id"])
              if e["eventType"] == "agent.tool_call.completed" and e["payload"].get("status") == "failed"]
    assert failed, "no failed tool event"


def test_model_retry_on_timeout():
    os.environ["AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION"] = "litellm"
    calls = {"n": 0}

    def handler(messages, model, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrationServiceError("QwenRuntime", "chat.completions", reason="TIMEOUTEXCEPTION")
        return {"provider": "t", "model": "m", "choices": [{"message": {"content": "重试后成功。"}}]}

    R.qwen_runtime_client = lambda: make_runtime(handler)
    session = create_session()
    data = post_message(session, "请核查当前节点。")
    assert calls["n"] == 2
    assert data["assistantMessage"]["execution"]["turnCount"] == 1
    types = {e["eventType"] for e in get_events(session["id"])}
    assert "agent.model_call.retried" in types, types


def test_streamed_deltas_suppress_per_turn():
    os.environ["AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION"] = "litellm"

    def handler(messages, model, **kwargs):
        h = kwargs.get("stream_handler")
        assert h is not None, "first attempt should stream"
        h("content", "第一段")
        h("content", "第二段结论完成。")
        return {"provider": "t", "model": "m",
                "choices": [{"message": {"content": "第一段第二段结论完成。"}}]}

    R.qwen_runtime_client = lambda: make_runtime(handler)
    session = create_session()
    post_message(session, "请核查当前节点。")
    deltas = [e for e in get_events(session["id"]) if e["eventType"] == "agent.message.delta"]
    assert len(deltas) == 1 and deltas[0]["payload"].get("streamed") is True, deltas
    assert deltas[0]["payload"].get("content") == "第一段第二段结论完成。", deltas[0]["payload"]


def test_session_tool_memory_across_messages():
    os.environ["AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION"] = "litellm"
    calls = {"n": 0, "prev_findings": False, "memory_notice": False}

    def handler(messages, model, **kwargs):
        calls["n"] += 1
        if calls["n"] in (1, 3):
            if calls["n"] == 3:
                calls["prev_findings"] = '"previousToolFindings"' in str(messages[1].get("content") or "")
            return {"provider": "t", "model": "m", "choices": [{"message": {"content": "", "tool_calls": [
                {"id": f"c{calls['n']}", "function": {"name": "get_review_context", "arguments": "{}"}}]}}]}
        if calls["n"] == 4:
            calls["memory_notice"] = any(
                "fromSessionMemory" in str(m.get("content") or "") for m in messages if m.get("role") == "tool")
        return {"provider": "t", "model": "m", "choices": [{"message": {"content": f"结论 {calls['n']}"}}]}

    R.qwen_runtime_client = lambda: make_runtime(handler)
    session = create_session()
    first = post_message(session, "请核对当前节点的规则与就绪状态。")
    second = post_message(session, "再确认一次上下文情况。", etag=first["session"]["etag"])
    assert calls["n"] == 4 and calls["prev_findings"] and calls["memory_notice"], calls
    assert second["assistantMessage"]["execution"]["mode"] == "llm_agent"


def test_budget_exhaustion_forces_final():
    os.environ["AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION"] = "litellm"
    os.environ["AICHECK_REVIEW_CONVERSATION_INPUT_TOKEN_BUDGET"] = "4000"
    point = next(item for item in repo.state["admin_config"]["materialReviewPoints"]
                 if int(item.get("nodeId") or 0) == NODE_ID)
    for index in range(12):
        repo.state["node_evidence_links"].append({
            "id": f"NEL-BUDGET-{index:02d}", "projectId": PROJECT_ID, "nodeId": NODE_ID,
            "reviewPointId": point["id"], "documentId": f"DOC-B{index:02d}",
            "documentVersionId": f"DV-B{index:02d}", "fileName": f"预算证据{index:02d}.pdf",
            "manualStatus": "pending", "supportStatus": "命中", "confidence": 0.9,
            "source": "material_targeting", "pageNo": 1, "fieldName": "内容",
            "quotedText": "证" * 600, "formalEvidenceEligible": True, "evidenceTier": "formal",
        })

    def handler(messages, model, **kwargs):
        assert kwargs.get("tool_choice") == "none"
        assert "Token 预算上限" in str(messages[-1].get("content") or "")
        return {"provider": "t", "model": "m", "choices": [{"message": {"content": "预算受限结论。"}}]}

    R.qwen_runtime_client = lambda: make_runtime(handler)
    session = create_session()
    data = post_message(session, "请全面核查当前节点全部证据。")
    execution = data["assistantMessage"]["execution"]
    assert execution["turnCount"] == 1 and execution["toolCallCount"] == 0, execution
    types = {e["eventType"] for e in get_events(session["id"])}
    assert "agent.budget.exhausted" in types, types


def test_background_accept_cancel_and_lock():
    os.environ["AICHECK_REVIEW_CONVERSATION_EXECUTION_MODE"] = "background"
    os.environ["AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION"] = "litellm"
    release = threading.Event()

    def handler(messages, model, **kwargs):
        release.wait(timeout=5)
        return {"provider": "t", "model": "m", "choices": [{"message": {"content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "get_review_context", "arguments": "{}"}}]}}]}

    R.qwen_runtime_client = lambda: make_runtime(handler)
    session = create_session()
    accepted = post_message(session, "整体核查当前节点。")
    assert accepted["status"] == "accepted"
    assert accepted["assistantMessage"]["status"] == "running"
    # 忙锁：第二条消息应 409
    busy = R.create_review_session_message(
        fake_request(), session["id"], body={"content": "再问一个。"},
        idempotency_key=next_key("busy"), if_match=accepted["session"]["etag"])
    assert busy.status_code == 409, busy.status_code
    # 取消
    cancel = assert_ok(R.run_review_session_action(
        fake_request(), session["id"], "cancel_execution", body={},
        idempotency_key=next_key("cancel"), if_match=None))
    assert cancel["cancelRequested"] is True
    release.set()
    final = wait_final(session["id"], accepted["assistantMessage"]["id"])
    assert final["status"] == "cancelled", final["status"]
    assert final["execution"]["failureReason"] == "USER_CANCELLED"
    types = {e["eventType"] for e in get_events(session["id"])}
    assert {"agent.execution.cancel_requested", "agent.execution.cancelled"} <= types, types


def test_agent_executions_and_heartbeat():
    os.environ["AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION"] = "litellm"
    R.qwen_runtime_client = lambda: make_runtime(
        lambda messages, model, **k: {"provider": "t", "model": "m",
                                      "choices": [{"message": {"content": "执行记录测试。"}}]})
    session = create_session()
    slash = post_message(session, "/标准条款")
    empty = assert_ok(R.list_review_session_agent_executions(fake_request(method="GET"), session["id"]))
    assert empty["executions"] == []
    free = post_message(session, "请核查当前节点。", etag=slash["session"]["etag"])
    executions = assert_ok(R.list_review_session_agent_executions(fake_request(method="GET"), session["id"]))["executions"]
    assert len(executions) == 1, executions
    record = executions[0]
    assert record["status"] == "completed" and record["executionMode"] == "inline"
    assert record["assistantMessageId"] == free["assistantMessage"]["id"]
    assert record["heartbeatAt"] and record["heartbeatEpoch"] > 0 and record["finishedAt"]


def test_celery_mode_falls_back_to_thread():
    os.environ["AICHECK_REVIEW_CONVERSATION_EXECUTION_MODE"] = "celery"
    os.environ["AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION"] = "litellm"
    os.environ.pop("AICHECK_TASK_DISPATCH", None)
    R.qwen_runtime_client = lambda: make_runtime(
        lambda messages, model, **k: {"provider": "t", "model": "m",
                                      "choices": [{"message": {"content": "Celery 回退回答。"}}]})
    session = create_session()
    accepted = post_message(session, "请核查当前节点。")
    assert accepted["status"] == "accepted"
    final = wait_final(session["id"], accepted["assistantMessage"]["id"])
    assert final["status"] == "completed"
    types = {e["eventType"] for e in get_events(session["id"])}
    assert {"agent.execution.dispatch_failed", "agent.message.completed"} <= types, types


def test_recovery_of_interrupted_execution():
    os.environ["AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION"] = "litellm"
    R.qwen_runtime_client = lambda: make_runtime(
        lambda messages, model, **k: {"provider": "t", "model": "m",
                                      "choices": [{"message": {"content": "恢复后的回答。"}}]})
    session = create_session()
    # 伪造一条无内存槽、心跳过期的 running 执行记录 + running 占位消息（模拟进程重启遗留）
    stale_message = {
        "id": "RMSG-STALE01", "sessionId": session["id"], "sequence": 99, "role": "assistant",
        "messageType": "review_response", "status": "running",
        "contentBlocks": [{"type": "text", "text": "…"}],
        "createdAt": "2026-07-26 00:00:00", "tenantId": None,
    }
    repo.state["review_messages"].append(stale_message)
    repo.state["agent_executions"].insert(0, {
        "id": "RAGENT-STALE01", "schemaVersion": "ReviewAgentExecution@1",
        "sessionId": session["id"], "projectId": PROJECT_ID, "nodeId": NODE_ID,
        "assistantMessageId": "RMSG-STALE01", "executionMode": "background",
        "status": "running", "cancelRequested": False,
        "startedAt": "2026-07-26 00:00:00", "startedEpoch": time.time() - 10_000,
        "heartbeatEpoch": time.time() - 10_000, "heartbeatAt": "2026-07-26 00:00:00",
        "turnCount": 0, "toolCallCount": 0, "failureReason": None, "finishedAt": None,
        "tenantId": None, "createdAt": "2026-07-26 00:00:00", "updatedAt": "2026-07-26 00:00:00",
    })
    data = post_message(session, "请核查当前节点。")
    assert data["assistantMessage"]["execution"]["mode"] == "llm_agent"
    records = {r["id"]: r for r in repo.state["agent_executions"]}
    assert records["RAGENT-STALE01"]["status"] == "interrupted", records["RAGENT-STALE01"]["status"]
    stale = next(m for m in get_messages(session["id"]) if m["id"] == "RMSG-STALE01")
    assert stale["status"] == "failed"


TESTS = [
    ("slash_deterministic_basis", test_slash_deterministic_basis),
    ("natural_language_not_hijacked", test_natural_language_not_hijacked),
    ("free_form_agent_context_and_references", test_free_form_agent_context_and_references),
    ("tool_loop_dedup_and_max_turns", test_tool_loop_dedup_and_max_turns),
    ("tool_failure_isolated", test_tool_failure_isolated),
    ("model_retry_on_timeout", test_model_retry_on_timeout),
    ("streamed_deltas_suppress_per_turn", test_streamed_deltas_suppress_per_turn),
    ("session_tool_memory_across_messages", test_session_tool_memory_across_messages),
    ("budget_exhaustion_forces_final", test_budget_exhaustion_forces_final),
    ("background_accept_cancel_and_lock", test_background_accept_cancel_and_lock),
    ("agent_executions_and_heartbeat", test_agent_executions_and_heartbeat),
    ("celery_mode_falls_back_to_thread", test_celery_mode_falls_back_to_thread),
    ("recovery_of_interrupted_execution", test_recovery_of_interrupted_execution),
]

for name, func in TESTS:
    run(name, func)

failed = [r for r in RESULTS if r[1] == "FAIL"]
for name, status, detail in RESULTS:
    print(f"{status:4} {name}")
    if detail:
        print(detail)
print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
sys.exit(1 if failed else 0)
