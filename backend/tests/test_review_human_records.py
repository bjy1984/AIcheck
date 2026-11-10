"""AI审查助手看得到人工留下的东西（2026-11-10）。

监检改过 OCR 认错的字段、给过人工意见，审查流水线都认；对话助手原来读的是 OCR 原值，
也不知道节点已经有人工意见。这里覆盖：只读汇总、修正值覆盖到助手读到的字段、
修正/意见一变就让旧工具结果和旧回答过期、每轮上下文里带上人工记录。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.api import review_session_evidence as evidence
from apps.api import routes as routes_module
from apps.api.main import app
from apps.api.review_human_records import human_review_records
from libs.db.repository import repo
from libs.review_input_data import apply_field_corrections_to_parse_results

PROJECT = "P-HUMAN"
NODE = 7


def correction(
    cid: str, *, status: str = "active", node: int = NODE, project: str = PROJECT, **extra
):
    return {
        "id": cid,
        "projectId": project,
        "nodeId": node,
        "factPath": f"field:{cid}",
        "fieldId": cid,
        "fieldName": "证书编号",
        "originalValue": "ABC-1O3",
        "correctedValue": "ABC-103",
        "documentVersionId": "DV-1",
        "reason": "OCR 把 0 认成了 O",
        "status": status,
        "correctedBy": "张工",
        "createdAt": "2026-11-10 09:00:00",
        **extra,
    }


def opinion(
    oid: str, result: str, created: str, *, node: int = NODE, project: str = PROJECT, text: str = ""
):
    return {
        "id": oid,
        "projectId": project,
        "nodeId": node,
        "result": result,
        "opinion": text,
        "reviewerName": "张工",
        "createdAt": created,
    }


EVIDENCE = [
    {
        "id": "E1",
        "documentVersionId": "DV-1",
        "fileName": "焊工证.pdf",
        "manualStatus": "confirmed",
    },
    {"id": "E2", "documentVersionId": "DV-2", "fileName": "施工图.pdf", "manualStatus": "rejected"},
    {"id": "E3", "documentVersionId": "DV-3", "manualStatus": "pending"},
]


# ---- 只读汇总 ----


def test_summary_lists_active_corrections_latest_opinion_and_evidence_decisions() -> None:
    state = {
        "fact_corrections": [
            correction("FC-1"),
            correction("FC-2", status="superseded"),
            correction("FC-3", status="revoked"),
            correction("FC-OTHER-NODE", node=NODE + 1),
            correction("FC-OTHER-PROJECT", project="P-OTHER"),
        ],
        "review_opinions": [
            opinion("OPN-OLD", "需补正", "2026-11-09 10:00:00", text="缺证书"),
            opinion("OPN-NEW", "满足要求", "2026-11-10 10:00:00", text="已补交"),
            opinion("OPN-OTHER", "需补正", "2026-11-11 10:00:00", node=NODE + 1),
        ],
    }
    out = human_review_records(state, PROJECT, NODE, evidence_links=EVIDENCE)

    assert out["hasHumanRecords"] is True
    assert out["correctionCount"] == 1 and out["withdrawnCorrectionCount"] == 2
    row = out["factCorrections"][0]
    assert (row["correctionId"], row["originalValue"], row["correctedValue"]) == (
        "FC-1",
        "ABC-1O3",
        "ABC-103",
    )
    assert row["fileName"] == "焊工证.pdf" and row["correctedBy"] == "张工"
    assert (
        out["latestOpinion"]["opinionId"] == "OPN-NEW"
        and out["latestOpinion"]["result"] == "满足要求"
    )
    assert out["opinionCount"] == 2, "别的节点的意见不算"
    assert out["evidenceDecisions"] == {"confirmed": 1, "rejected": 1, "pending": 1}
    assert "人工修正" in out["notice"]


def test_summary_is_empty_but_well_formed_when_nobody_touched_the_node() -> None:
    out = human_review_records(
        {}, PROJECT, NODE, evidence_links=[{"id": "E", "manualStatus": "pending"}]
    )
    assert out["hasHumanRecords"] is False
    assert (
        out["factCorrections"] == []
        and out["latestOpinion"] is None
        and out["correctionCount"] == 0
    )


def test_summary_truncates_long_text_and_caps_the_list() -> None:
    state = {
        "fact_corrections": [
            correction(f"FC-{i}", createdAt=f"2026-11-10 09:00:{i:02d}") for i in range(30)
        ]
    }
    state["fact_corrections"][0]["reason"] = "长" * 500
    out = human_review_records(state, PROJECT, NODE, limits={"items": 5, "chars": 20})
    assert len(out["factCorrections"]) == 5 and out["correctionCount"] == 30
    assert out["factCorrections"][0]["correctionId"] == "FC-29", "新的在前"
    long = human_review_records(state, PROJECT, NODE, limits={"items": 30, "chars": 20})
    assert (
        next(r for r in long["factCorrections"] if r["correctionId"] == "FC-0")["reason"]
        == "长" * 20 + "…"
    )


# ---- 助手读到的字段是修正后的值 ----


def parse_result():
    return {
        "documentVersionId": "DV-1",
        "documentType": "焊工证",
        "fields": [
            {"fieldName": "证书编号", "fieldValue": "ABC-1O3", "pageNo": 1, "confidence": 0.4},
            {"fieldName": "姓名", "fieldValue": "李四", "pageNo": 1},
        ],
    }


def test_correction_scope_overrides_ocr_value_without_a_review_run() -> None:
    state = {"fact_corrections": [correction("FC-1")]}
    scope = {"correctionScope": {"projectId": PROJECT, "nodeId": NODE}}

    patched = apply_field_corrections_to_parse_results(state, [parse_result()], context=scope)
    fields = {f["fieldName"]: f for f in patched[0]["fields"]}
    assert (
        fields["证书编号"]["fieldValue"] == "ABC-103"
        and fields["证书编号"]["humanCorrected"] is True
    )
    assert (
        fields["证书编号"]["originalValue"] == "ABC-1O3" and fields["证书编号"]["confidence"] == 1.0
    )
    assert "humanCorrected" not in fields["姓名"]

    # 别的节点、别的项目、没给范围：保持 OCR 原值
    for context in (
        {"correctionScope": {"projectId": PROJECT, "nodeId": NODE + 1}},
        {"correctionScope": {"projectId": "P-OTHER", "nodeId": NODE}},
        {},
    ):
        untouched = apply_field_corrections_to_parse_results(
            state, [parse_result()], context=context
        )
        assert untouched[0]["fields"][0]["fieldValue"] == "ABC-1O3"
    # 持久化的 OCR 结果本身没被改
    assert parse_result()["fields"][0]["fieldValue"] == "ABC-1O3"


def dispatch(tool: str, arguments: dict | None = None, *, evidence_links=None):
    return routes_module.review_conversation_agent_tool_output(
        tool,
        arguments or {},
        session={},
        project={"id": PROJECT, "name": "人工记录测试"},
        node={"nodeId": NODE, "name": "焊工资格"},
        basis={},
        basis_items=[],
        readiness={},
        evidence_links=evidence_links if evidence_links is not None else EVIDENCE,
        review_run=None,
    )


@pytest.fixture
def seeded(monkeypatch):
    monkeypatch.setitem(repo.state, "fact_corrections", [correction("FC-1")])
    monkeypatch.setitem(
        repo.state,
        "review_opinions",
        [opinion("OPN-1", "需补正", "2026-11-10 10:00:00", text="证书编号不符")],
    )
    monkeypatch.setitem(repo.state, "ocr_parse_results", [parse_result()])


def test_assemble_judgment_facts_shows_the_corrected_value(seeded) -> None:
    out = dispatch("assemble_node_judgment_facts")
    fields = {f["value"]: f for f in out["documents"][0]["fields"]}
    assert "ABC-103" in fields and "ABC-1O3" not in fields, "助手不能再拿 OCR 原值回答"
    assert (
        fields["ABC-103"]["humanCorrected"] is True
        and fields["ABC-103"]["originalValue"] == "ABC-1O3"
    )


def test_conversation_tool_is_registered_dispatched_and_never_cached(seeded) -> None:
    names = {item["function"]["name"] for item in routes_module.REVIEW_CONVERSATION_AGENT_TOOLS}
    assert "get_human_review_records" in names
    assert "get_human_review_records" in routes_module.REVIEW_SESSION_TOOL_MEMORY_EXCLUDED_TOOLS

    out = dispatch("get_human_review_records")
    assert out["correctionCount"] == 1 and out["latestOpinion"]["result"] == "需补正"
    summary = routes_module.review_conversation_tool_result_summary("get_human_review_records", out)
    assert "人工修正 1 处" in summary and "人工意见 有" in summary


# ---- 修正或意见一变，旧结果和旧回答过期 ----


def test_fingerprint_moves_when_a_correction_or_opinion_changes_and_only_for_that_node(
    monkeypatch,
) -> None:
    session = {"projectId": PROJECT, "nodeId": NODE}
    monkeypatch.setitem(repo.state, "node_evidence_links", [])
    monkeypatch.setitem(repo.state, "bindings", [])
    monkeypatch.setitem(repo.state, "fact_corrections", [])
    monkeypatch.setitem(repo.state, "review_opinions", [])
    empty = evidence.review_session_evidence_fingerprint(session)

    repo.state["fact_corrections"].append(correction("FC-1"))
    corrected = evidence.review_session_evidence_fingerprint(session)
    assert corrected != empty

    repo.state["fact_corrections"][0]["status"] = "revoked"
    revoked = evidence.review_session_evidence_fingerprint(session)
    assert revoked not in (empty, corrected), "撤销也是一次变化"

    repo.state["review_opinions"].append(opinion("OPN-1", "满足要求", "2026-11-10 10:00:00"))
    assert evidence.review_session_evidence_fingerprint(session) != revoked

    # 别的节点的记录不影响本节点
    repo.state["fact_corrections"] = [correction("FC-X", node=NODE + 5)]
    repo.state["review_opinions"] = []
    assert evidence.review_session_evidence_fingerprint(session) == empty


# ---- 每轮上下文里带人工记录 ----

CLIENT = TestClient(app)
HDCP = "P-2026-HDCP-001"
HDCP_NODE = 16
OWNER = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}


class CapturingRuntime:
    def __init__(self):
        self.contexts: list[dict] = []

    def chat_sync(self, messages, model, **kwargs):
        payload = messages[1]["content"].rsplit("\n\n", 1)[0]
        self.contexts.append(json.loads(payload))
        return {
            "provider": "test",
            "model": "test-model",
            "choices": [{"message": {"content": "需要人工确认。"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }


def test_every_question_carries_the_human_records_and_the_prompt_explains_them(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_EXECUTION_MODE", "inline")
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    fake = CapturingRuntime()
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: fake)
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None
    repo.state["fact_corrections"].append(correction("FC-CTX", project=HDCP, node=HDCP_NODE))
    repo.state["review_opinions"].insert(
        0,
        opinion(
            "OPN-CTX",
            "需补正",
            "2026-11-10 10:00:00",
            project=HDCP,
            node=HDCP_NODE,
            text="补交证书",
        ),
    )

    created = CLIENT.post(
        f"/api/projects/{HDCP}/inspection/nodes/{HDCP_NODE}/review-sessions",
        headers={**OWNER, "Idempotency-Key": "human-records-session"},
        json={"currentTask": "核对焊工资格"},
    ).json()["data"]["session"]
    asked = CLIENT.post(
        f"/api/review-sessions/{created['id']}/messages",
        headers={**OWNER, "Idempotency-Key": "human-records-ask", "If-Match": created["etag"]},
        json={"content": "证书编号是多少？"},
    )
    assert asked.status_code == 200, asked.text

    human = fake.contexts[-1]["humanRecords"]
    assert human["hasHumanRecords"] is True and human["correctionCount"] == 1
    assert human["factCorrections"][0]["correctedValue"] == "ABC-103"
    assert human["latestOpinion"]["result"] == "需补正"
    prompt = routes_module.REVIEW_CONVERSATION_SYSTEM_PROMPT
    assert (
        "get_human_review_records" in prompt and "人工已修正" in prompt and "人工已出意见" in prompt
    )
