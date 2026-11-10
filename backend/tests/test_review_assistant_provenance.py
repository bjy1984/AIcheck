"""助手回答记下「当时看到的人工记录」，过期时说清原因；回答偏好贴着生成位置再说一遍（2026-11-10）。

原来旧回答只有一个布尔的 staleContext：模型只知道「过期了」，不知道是人工改了字段、
还是证据变了。现在回答落库时记 humanRecordsSeen，过期时给 staleReason。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.api import review_session_memory as memory
from apps.api import routes as routes_module
from apps.api.main import app
from apps.api.review_human_records import human_records_change_text, human_records_signature
from libs.db.repository import repo

client = TestClient(app)
PROJECT = "P-2026-HDCP-001"
NODE = 16
OWNER = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}


def correction(cid: str, status: str = "active") -> dict:
    return {
        "id": cid,
        "projectId": PROJECT,
        "nodeId": NODE,
        "factPath": f"field:{cid}",
        "fieldId": cid,
        "fieldName": "证书编号",
        "originalValue": "ABC-1O3",
        "correctedValue": "ABC-103",
        "status": status,
        "createdAt": "2026-11-10 09:00:00",
    }


def opinion(oid: str, result: str, created: str) -> dict:
    return {"id": oid, "projectId": PROJECT, "nodeId": NODE, "result": result, "createdAt": created}


# ---- 指纹与变化描述 ----


def test_signature_lists_active_corrections_and_latest_opinion() -> None:
    state = {
        "fact_corrections": [
            correction("FC-B"),
            correction("FC-A"),
            correction("FC-OLD", "revoked"),
        ],
        "review_opinions": [
            opinion("O1", "需补正", "2026-11-09 10:00:00"),
            opinion("O2", "满足要求", "2026-11-10 10:00:00"),
        ],
    }
    sig = human_records_signature(state, PROJECT, NODE)
    assert sig == {
        "correctionIds": ["FC-A", "FC-B"],
        "opinionId": "O2",
        "opinionResult": "满足要求",
    }
    assert human_records_signature({}, PROJECT, NODE) == {
        "correctionIds": [],
        "opinionId": None,
        "opinionResult": None,
    }
    assert human_records_signature(state, PROJECT, NODE + 1)["correctionIds"] == []


def test_change_text_says_what_changed_and_is_empty_when_nothing_did() -> None:
    seen = {"correctionIds": ["FC-1"], "opinionId": None, "opinionResult": None}
    assert human_records_change_text(seen, seen) == ""
    now = {"correctionIds": ["FC-1", "FC-2"], "opinionId": "O1", "opinionResult": "需补正"}
    text = human_records_change_text(seen, now)
    assert "新增人工修正 1 处" in text and "人工意见变为“需补正”" in text
    assert "撤销或替换人工修正 1 处" in human_records_change_text(
        now, {**now, "correctionIds": ["FC-2"]}
    )


# ---- 过期原因 ----

REASONS = {
    "legacy": "早于记忆改造",
    "evidence": "证据或人工记录有变化",
    "run": "新的复核运行",
}


def test_stale_reason_distinguishes_human_records_evidence_and_run() -> None:
    reason = memory.answer_stale_reason
    base = {
        "evidenceFingerprint": "fp1",
        "reviewRunId": "R1",
        "humanRecordsSeen": {"correctionIds": [], "opinionId": None, "opinionResult": None},
    }
    now = {"correctionIds": ["FC-1"], "opinionId": None, "opinionResult": None}

    assert (
        reason(base, fingerprint="fp1", review_run_id="R1", human_records=base["humanRecordsSeen"])
        is None
    )
    assert REASONS["legacy"] in reason({"reviewRunId": "R1"}, fingerprint="fp1", review_run_id="R1")
    assert (
        reason(base, fingerprint="fp2", review_run_id="R1", human_records=now)
        == "此后人工记录有变化：新增人工修正 1 处"
    )
    # 没有 humanRecordsSeen 的回答（这次改动之前落库的）：只能笼统地说
    no_seen = {"evidenceFingerprint": "fp1", "reviewRunId": "R1"}
    assert REASONS["evidence"] in reason(
        no_seen, fingerprint="fp2", review_run_id="R1", human_records=now
    )
    # 指纹变了但人工记录没变：是证据变了
    assert REASONS["evidence"] in reason(
        base, fingerprint="fp2", review_run_id="R1", human_records=base["humanRecordsSeen"]
    )
    assert REASONS["run"] in reason(
        base, fingerprint="fp1", review_run_id="R2", human_records=base["humanRecordsSeen"]
    )
    assert memory.answer_is_stale(base, fingerprint="fp2", review_run_id="R1") is True


# ---- 端到端：问 → 人工改字段 → 再问 ----


class RawRuntime:
    def __init__(self) -> None:
        self.raw: list[str] = []

    def chat_sync(self, messages, model, **kwargs):
        self.raw.append(messages[1]["content"])
        return {
            "provider": "test",
            "model": "test-model",
            "choices": [{"message": {"content": "需要人工确认。"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

    def context(self, index: int = -1) -> dict:
        return json.loads(self.raw[index].rsplit("\n\n", 1)[0])


@pytest.fixture
def runtime(monkeypatch) -> RawRuntime:
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_EXECUTION_MODE", "inline")
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    fake = RawRuntime()
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: fake)
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None
    return fake


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def ask(session_id: str, text: str, key: str):
    session = repo.find_one("review_sessions", session_id)
    return client.post(
        f"/api/review-sessions/{session_id}/messages",
        headers={
            **OWNER,
            "Idempotency-Key": key,
            "If-Match": routes_module.record_etag("review-session", session),
        },
        json={"content": text},
    )


def new_session() -> str:
    created = data(
        client.post(
            f"/api/projects/{PROJECT}/inspection/nodes/{NODE}/review-sessions",
            headers={**OWNER, "Idempotency-Key": "prov-session"},
            json={"currentTask": "核对焊工资格"},
        )
    )
    return created["session"]["id"]


def test_answer_records_what_it_saw_and_later_says_why_it_is_stale(runtime) -> None:
    sid = new_session()
    data(ask(sid, "证书编号是多少？", "prov-ask-1"))
    first = [
        m
        for m in repo.state["review_messages"]
        if m["sessionId"] == sid and m["role"] == "assistant"
    ][-1]
    assert first["humanRecordsSeen"] == {
        "correctionIds": [],
        "opinionId": None,
        "opinionResult": None,
    }

    # 之后监检把字段改了
    repo.state["fact_corrections"].append(correction("FC-LATER"))
    data(ask(sid, "现在呢？", "prov-ask-2"))

    history = runtime.context()["recentConversation"]
    answers = [entry for entry in history if entry["role"] == "assistant"]
    assert answers and answers[-1]["staleContext"] is True
    assert answers[-1]["staleReason"] == "此后人工记录有变化：新增人工修正 1 处"
    second = [
        m
        for m in repo.state["review_messages"]
        if m["sessionId"] == sid and m["role"] == "assistant"
    ][-1]
    assert second["humanRecordsSeen"]["correctionIds"] == ["FC-LATER"]


def test_fresh_answers_carry_no_stale_reason(runtime) -> None:
    sid = new_session()
    data(ask(sid, "第一问", "prov-fresh-1"))
    data(ask(sid, "第二问", "prov-fresh-2"))
    answers = [e for e in runtime.context()["recentConversation"] if e["role"] == "assistant"]
    assert answers and all(e["staleContext"] is False and "staleReason" not in e for e in answers)


# ---- 回答偏好贴着生成位置 ----


def test_preference_is_repeated_right_before_generation_and_context_still_parses(runtime) -> None:
    sid = new_session()
    data(
        client.put(
            "/api/review-assistant/preferences",
            headers={**OWNER, "Idempotency-Key": "prov-pref"},
            json={"text": "先给结论，回答不超过 150 字。"},
        )
    )
    data(ask(sid, "焊工证？", "prov-pref-ask"))

    raw = runtime.raw[-1]
    tail = raw.rsplit("\n\n", 1)[1]
    assert "请全程用中文" in tail
    assert tail.rstrip().endswith("先给结论，回答不超过 150 字。")
    assert "不改变判定" in tail
    assert runtime.context()["userPreferences"] == "先给结论，回答不超过 150 字。", (
        "下游按最后一处空行切出的 JSON 仍可解析"
    )


def test_no_preference_means_no_extra_line(runtime) -> None:
    sid = new_session()
    data(ask(sid, "焊工证？", "prov-nopref-ask"))
    tail = runtime.raw[-1].rsplit("\n\n", 1)[1]
    assert "用户回答偏好" not in tail and "\n" not in tail.strip()
    assert "staleReason" in routes_module.REVIEW_CONVERSATION_SYSTEM_PROMPT
