"""AI 审查助手报的原子项结论必须与节点页（复核留痕）一致。

2026-11-09 生产实测（测试项目3 节点 1，RRUN-B0C1A8F9EB）：节点页 AC-R01-01/02/04 通过、
03/05 证据不足；同样证据下助手一次说「无证据不足原子项」，一次说五项全部证据不足。
这里的留痕照搬那次复核的形状，两段回答原文照搬生产库里存的消息。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.api import routes as routes_module
from apps.api.main import app
from libs import review_assistant_atomic_results as atomic_results
from libs.db.repository import repo
from libs.review_orchestrator import output_contract

client = TestClient(app)
HEADERS = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
PROJECT_ID = "P-2026-HDCP-001"
NODE_ID = 1
RUN_ID = "RRUN-ATOMIC-R01"

# 生产 23:20 的回答（只调了单项工具，末尾自己补了总括）
ANSWER_NO_INSUFFICIENT = """**结论：设计单位许可范围可以覆盖本工程 GC2 管道。**

| 核查项 | 结论 | 关键证据 | 适用标准条款 |
|--------|------|----------|--------------|
| 许可范围覆盖 GC2 | 符合 | 许可证范围含 GC1，按规则覆盖 GC1/GC2/GCD | [TSG 07—2019 E1.1](basis:LOC-472EFBCE9035) |
| 许可证有效性 | 符合 | 编号 TS1844171-2028，平台核验有效至 2028-01-17 | [TSG D7006—2020 D2.1](basis:LOC-18CB6BBB5C60) |

无证据不足原子项。"""

# 生产 23:25 新会话的回答（对话内重跑，五项全部证据不足）
ANSWER_ALL_INSUFFICIENT = """## 核查结论

| 核查项 | 结论 | 关键证据 | 适用标准条款 |
|--------|------|----------|--------------|
| AC-R01-01 设计单位名称一致性 | 证据不足 | — | [TSG D7006—2020 D2.1](basis:LOC-18CB6BBB5C60) |
| AC-R01-02 许可范围覆盖 | 证据不足 | — | [TSG 07—2019 E1.1](basis:LOC-472EFBCE9035) |
| AC-R01-03 许可证有效期 | 证据不足 | — | [TSG 31—2025 3.1.1-3.1.2](basis:LOC-5DE1B5BB6337) |
| AC-R01-04 许可级别覆盖 | 证据不足 | — | [TSG 07—2019 E1.2.2](basis:LOC-472EFBCE9035) |
| AC-R01-05 设计许可印章 | 证据不足 | — | [TSG 31—2025 3.1.1-3.1.2](basis:LOC-5DE1B5BB6337) |

**结论**：上次"许可范围覆盖 GC2"的结论**目前不成立**，5 个原子项均证据不足。"""


def _atomic(check_id: str, result: str, warnings: list[str] | None = None) -> dict:
    return {
        "atomicCheckId": check_id,
        "sourceRuleId": "R01",
        "result": result,
        "warnings": warnings or [],
        "toolResults": [
            {"toolName": "check_design_license_scope", "result": "passed",
             "checks": [{"code": "scope_covers_GC2", "passed": True}]},
        ],
    }


def _seed_formal_run(*, input_versions: list[str] | None = None) -> dict:
    project = repo.require_project(PROJECT_ID) or {}
    tenant_id = routes_module.tenant_id_for_record(project)
    run = {
        "id": RUN_ID,
        "reviewRunId": RUN_ID,
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "tenantId": tenant_id,
        "businessPackId": project.get("businessPackId"),
        "status": "waiting_human_review",
        "reviewMode": "formal",
        "createdAt": "2026-11-03 21:34:09",
        "inputDocumentVersionIds": input_versions or [],
        "findingDrafts": [],
    }
    repo.state["review_runs"].insert(0, run)
    repo.state["rule_check_results"].append(
        {
            "id": "RCHK-ATOMIC-R01",
            "reviewRunId": RUN_ID,
            "tenantId": tenant_id,
            "ruleCode": "engineering-inspection-r01",
            "result": "evidence_insufficient",
            "atomicCheckResults": [
                _atomic("AC-R01-01", "passed"),
                _atomic("AC-R01-02", "passed"),
                _atomic("AC-R01-03", "evidence_insufficient", ["construction_period_not_in_node_documents"]),
                _atomic("AC-R01-04", "passed"),
                _atomic("AC-R01-05", "evidence_insufficient", ["evidence_trace_waits_for:AC-R01-03"]),
            ],
        }
    )
    return run


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_EXECUTION_MODE", "inline")
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def _snapshot() -> dict:
    run = _seed_formal_run()
    return atomic_results.formal_snapshot(repo.state, run)


def test_snapshot_is_what_the_node_page_shows() -> None:
    run = _seed_formal_run()
    snapshot = atomic_results.formal_snapshot(repo.state, run)
    node_page = output_contract.review_view_with_limitations(run, repo.state)["atomicCheckOutcomes"]
    assert [(item["atomicCheckId"], item["result"]) for item in snapshot["items"]] == [
        (item["atomicCheckId"], item["result"]) for item in node_page
    ]
    assert snapshot["counts"] == {"passed": 3, "evidence_insufficient": 2}
    reasons = {item["atomicCheckId"]: item.get("reason") for item in snapshot["items"]}
    assert "施工期" in reasons["AC-R01-03"]
    assert "AC-R01-03" in reasons["AC-R01-05"]
    assert reasons["AC-R01-01"] is None


def test_no_run_or_no_records_is_not_a_conclusion() -> None:
    assert atomic_results.formal_snapshot(repo.state, None)["available"] is False
    empty = atomic_results.formal_snapshot(repo.state, {"reviewRunId": "RRUN-NOTHING", "status": "failed"})
    assert empty["available"] is False
    assert empty["reason"] == "no_recorded_atomic_results"


def test_made_up_no_insufficient_claim_is_corrected() -> None:
    text, check = atomic_results.reconcile_answer(ANSWER_NO_INSUFFICIENT, _snapshot())
    assert check["status"] == "corrected"
    assert check["mismatches"] == [{"kind": "no_insufficient", "quote": "无证据不足原子项"}]
    assert text.startswith(ANSWER_NO_INSUFFICIENT)  # 模型原文保留，只追加
    correction = text[len(ANSWER_NO_INSUFFICIENT):]
    assert "以复核留痕为准" in correction
    assert "AC-R01-03" in correction and "AC-R01-05" in correction
    assert correction.count("：证据不足") == 2 and correction.count("：符合") == 3


def test_rerun_that_contradicts_the_record_is_corrected_item_by_item() -> None:
    text, check = atomic_results.reconcile_answer(ANSWER_ALL_INSUFFICIENT, _snapshot())
    assert check["status"] == "corrected"
    wrong = {item["atomicCheckId"] for item in check["mismatches"] if item.get("atomicCheckId")}
    assert wrong == {"AC-R01-01", "AC-R01-02", "AC-R01-04"}
    assert {"kind": "all_insufficient", "quote": "原子项均证据不足"} in check["mismatches"]
    assert "AC-R01-01 上文写作“证据不足”，留痕为“符合”" in text


def test_answer_that_matches_the_record_is_left_alone() -> None:
    answer = (
        "| 核查项 | 结论 |\n|---|---|\n"
        "| AC-R01-01 名称一致 | 符合 |\n| AC-R01-02 范围覆盖 | 符合 |\n"
        "| AC-R01-03 有效期覆盖施工期 | 证据不足 |\n| AC-R01-04 级别覆盖 | 符合 |\n"
        "| AC-R01-05 印章 | 证据不足 |\n\n证据不足的原子项：AC-R01-03、AC-R01-05；其余原子项均符合。"
    )
    text, check = atomic_results.reconcile_answer(answer, _snapshot())
    assert text == answer
    assert check == {"status": "consistent", "reviewRunId": RUN_ID}


def test_shorthand_ids_and_partial_wording_are_read_correctly() -> None:
    snapshot = _snapshot()
    _, check = atomic_results.reconcile_answer(
        "AC-R01-01/02/04 通过。\nAC-R01-03、05 证据不足：无施工期出处证据不足以判符合。", snapshot
    )
    assert check["status"] == "consistent", check
    _, wrong = atomic_results.reconcile_answer("AC-R01-01/02/03 通过。", snapshot)
    assert [item["atomicCheckId"] for item in wrong["mismatches"]] == ["AC-R01-03"]


def test_listing_atomic_items_but_dropping_unpassed_ones_is_completed() -> None:
    text, check = atomic_results.reconcile_answer("证据不足的原子项：AC-R01-03。", _snapshot())
    assert check["status"] == "completed_omissions"
    assert check["omitted"] == ["AC-R01-05"]
    assert "上文没有提到以下未通过的原子项（AC-R01-05）" in text


def test_single_item_answer_without_atomic_claims_is_not_touched() -> None:
    answer = "设计单位许可范围含 GC1，可以覆盖本工程 GC2 管道。"
    assert atomic_results.reconcile_answer(answer, _snapshot()) == (answer, {"status": "consistent", "reviewRunId": RUN_ID})


def test_without_records_a_blanket_claim_gets_a_caveat() -> None:
    snapshot = atomic_results.formal_snapshot(repo.state, None)
    text, check = atomic_results.reconcile_answer(ANSWER_NO_INSUFFICIENT, snapshot)
    assert check["status"] == "unsupported_claim"
    assert "没有原子项结论留痕" in text
    assert atomic_results.reconcile_answer("许可证在有效期内。", snapshot) == ("许可证在有效期内。", None)


def test_formal_judgment_tool_returns_the_record_instead_of_rerunning() -> None:
    run = _seed_formal_run()
    project = repo.require_project(PROJECT_ID) or {}
    output = routes_module.review_conversation_agent_tool_output(
        "run_node_formal_judgment", {}, session={}, project=project, node={"nodeId": NODE_ID},
        basis={}, basis_items=[], readiness={}, evidence_links=[], review_run=run,
    )
    assert output["source"] == "formal_review_run"
    assert output["advisory"] is False
    assert output["reviewRunId"] == RUN_ID
    assert output["summary"] == {"atomicCheckCount": 5, "passedCount": 3, "failedCount": 0, "evidenceInsufficientCount": 2}
    assert "bindingSetLifecycleStatus" not in output  # 留痕已过正式复核的放行门，不再拿 draft 说事
    summary = routes_module.review_conversation_tool_result_summary("run_node_formal_judgment", output)
    assert summary.startswith("复核留痕（R01）")


def test_evidence_changed_after_the_run_is_flagged_not_rejudged() -> None:
    run = _seed_formal_run(input_versions=["DV-OLD-1"])
    snapshot = atomic_results.formal_snapshot(
        repo.state, run, evidence_links=[{"documentVersionId": "DV-NEW-1"}, {"documentVersionId": "DV-X", "manualStatus": "rejected"}]
    )
    assert snapshot["evidenceChangedSinceRun"] == {"added": 1, "removed": 1}
    assert snapshot["counts"] == {"passed": 3, "evidence_insufficient": 2}
    assert "重新发起正式复核" in snapshot["notice"]


def test_advisory_rerun_notice_respects_pilot_rules() -> None:
    draft_pilot = {"lifecycleStatus": "draft", "pilotRules": ["R01"]}
    notices = atomic_results.advisory_rerun_notices(draft_pilot, "R01", has_facts=True)
    assert len(notices) == 1 and "不是节点结论" in notices[0]
    assert not any("未列入试点" in item for item in notices)
    notices = atomic_results.advisory_rerun_notices({"lifecycleStatus": "draft"}, "R01", has_facts=False)
    assert any("未列入试点" in item for item in notices)
    assert any("暂无事实装配器" in item for item in notices)


def test_advisory_rerun_takes_grounding_facts_from_the_same_place_as_formal_review() -> None:
    claimed = [{"factId": "F1"}]
    refs = [{"id": "E1"}]
    assert atomic_results.grounding_inputs({"judgment": {"claimedFacts": claimed, "evidenceRefs": refs}}) == (claimed, refs)
    assert atomic_results.grounding_inputs({}) == ([], [])


class _AtomicRuntime:
    """第 1 轮调 run_node_formal_judgment，第 2 轮给出预设回答。"""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.turn = 0
        self.first_context = ""
        self.tool_payloads: list[str] = []

    def chat_sync(self, messages, model, **kwargs):
        self.turn += 1
        if self.turn == 1:
            self.first_context = str(messages[1]["content"])
            call = {"id": "call-1", "type": "function", "function": {"name": "run_node_formal_judgment", "arguments": "{}"}}
            return {"provider": "test", "model": "test", "choices": [{"message": {"content": "", "tool_calls": [call]}}]}
        self.tool_payloads = [str(item.get("content") or "") for item in messages if item.get("role") == "tool"]
        return {"provider": "test", "model": "test", "choices": [{"message": {"content": self.answer}}]}


def _ask(monkeypatch, answer: str) -> tuple[dict, _AtomicRuntime]:
    _seed_formal_run()
    runtime = _AtomicRuntime(answer)
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION", "litellm")
    monkeypatch.setattr(routes_module, "qwen_runtime_client", lambda: runtime)
    session = client.post(
        f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-sessions",
        headers={**HEADERS, "Idempotency-Key": "atomic-session"},
        json={"currentTask": "核对设计单位许可证"},
    ).json()["data"]["session"]
    response = client.post(
        f"/api/review-sessions/{session['id']}/messages",
        headers={**HEADERS, "Idempotency-Key": f"atomic-message-{len(answer)}", "If-Match": session["etag"]},
        json={"content": "这个节点设计单位的许可范围能否覆盖本工程的 GC2 管道？"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["assistantMessage"], runtime


def test_assistant_sees_the_record_and_cannot_contradict_it(monkeypatch) -> None:
    message, runtime = _ask(monkeypatch, ANSWER_NO_INSUFFICIENT)
    context = json.loads(runtime.first_context.split("\n\n")[0])
    recorded = context["formalAtomicResults"]
    assert recorded["available"] is True and recorded["reviewRunId"] == RUN_ID
    assert {item["atomicCheckId"]: item["result"] for item in recorded["items"]}["AC-R01-03"] == "evidence_insufficient"
    tool_output = json.loads(runtime.tool_payloads[0])
    assert tool_output["source"] == "formal_review_run"
    assert tool_output["summary"]["evidenceInsufficientCount"] == 2

    text = next(block["text"] for block in message["contentBlocks"] if block["type"] == "text")
    assert text.startswith(ANSWER_NO_INSUFFICIENT)
    assert "以复核留痕为准" in text and "AC-R01-05" in text
    assert message["execution"]["atomicConsistency"]["status"] == "corrected"


def test_consistent_assistant_answer_passes_through(monkeypatch) -> None:
    answer = "结论：AC-R01-01、02、04 符合；AC-R01-03、05 证据不足（施工期无节点资料出处）。"
    message, _ = _ask(monkeypatch, answer)
    text = next(block["text"] for block in message["contentBlocks"] if block["type"] == "text")
    assert text == answer
    assert message["execution"]["atomicConsistency"] == {"status": "consistent", "reviewRunId": RUN_ID}
