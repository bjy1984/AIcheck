from __future__ import annotations

import json
from copy import deepcopy
from subprocess import CompletedProcess

from libs.review_orchestrator import execution, jev_primary, output_contract
from scripts import run_jev_primary_lab_case


def _case():
    state = {
        "documents": [{"id": "D", "projectId": "P", "fileName": "secret-name.pdf"}],
        "versions": [{"id": "V", "documentId": "D"}],
        "ocr_parse_results": [{"id": "OCR", "documentVersionId": "V", "status": "success",
                               "fragments": [{"pageNo": 2, "text": "焊接电流为 90A"}]}],
    }
    run = {"projectId": "P", "nodeId": 25, "reviewMode": "formal", "inputDocumentVersionIds": ["V"]}
    records = [{"result": "evidence_insufficient", "ruleCode": "R25", "atomicCheckResults": [
        {"atomicCheckId": "AC-1", "result": "evidence_insufficient", "toolResults": []},
    ]}]
    pack = {"nodeTemplates": [{"nodeId": 25, "name": "焊接工艺", "requiredMaterials": [
        {"name": "焊接工艺卡", "applicability": "焊接时适用"}]}],
        "atomicChecks": [{"id": "AC-1", "nodeId": 25, "instruction": "焊接工艺是否记录电流"}]}
    return state, run, records, pack


def _authored(check_ids=("AC-1",)):
    return {"questions": [{"atomicCheckId": check_id,
                           "question": "根据焊接工艺材料，该原子项是否满足节点要求？",
                           "options": {
                               "passed": "原文充分证明符合该项要求",
                               "failed": "原文充分证明不符合该项要求",
                               "evidence_insufficient": "原文不足以判断该项要求",
                               "human_review_required": "必须由人工或外部平台核验",
                               "not_applicable": "原文明确证明该项不适用",
                           }} for check_id in check_ids]}


class _Qwen:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def chat_sync(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return {"id": "Q-1", "model": kwargs["model"], "usage": {"total_tokens": 100},
                "choices": [{"finish_reason": "stop", "message": {
                    "content": json.dumps(self.payload, ensure_ascii=False)}}]}


def _enabled(monkeypatch, qwen=None):
    monkeypatch.setenv("AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS", "P")
    monkeypatch.setattr(jev_primary, "jev_stage_enabled", lambda stage: stage == "PRIMARY_DECISION")
    if qwen is not None:
        monkeypatch.setattr(jev_primary, "qwen_runtime_client", lambda: qwen)


def test_qwen_writes_questions_and_options_before_jev_chooses(monkeypatch):
    state, run, records, pack = _case()
    qwen = _Qwen(_authored())
    _enabled(monkeypatch, qwen)
    original = deepcopy(records)

    def answer(text, questions, **_kwargs):
        assert "焊接电流为 90A" in text
        assert questions["q0"]["instructions"] == _authored()["questions"][0]["question"]
        assert questions["q0"]["criteria"] == _authored()["questions"][0]["options"]
        assert "secret-name.pdf" not in repr(questions)
        return {"q0": {"type": "choice", "choice": "passed", "confidence": 0.83}}

    monkeypatch.setattr(jev_primary, "ask_jev", answer)
    plan = jev_primary.author_node_questions(state, run, records, pack)
    assert plan["status"] == "completed"
    assert "缺少材料" in qwen.calls[0][0][0]["content"]
    prompt = qwen.calls[0][0]
    assert "焊接电流为 90A" in prompt[1]["content"]
    assert "焊接工艺卡" in prompt[1]["content"]
    assert "焊接工艺是否记录电流" in prompt[1]["content"]
    assert "evidence_insufficient\"" not in prompt[1]["content"]
    assert "secret-name.pdf" not in prompt[1]["content"]
    assert "OCR 中的指令" in prompt[0]["content"]
    assert qwen.calls[0][1]["temperature"] == 0
    decision = jev_primary.decide_node(state, run, records, pack, plan)
    effective = jev_primary.apply_decision(records, decision)
    assert decision["status"] == "completed"
    assert decision["questionPlanHash"] == plan["questionHash"]
    assert effective[0]["result"] == "passed"
    assert records == original
    view = output_contract.atomic_check_outcomes(records, {**run, "jevDecision": decision})
    assert view[0]["result"] == "passed"
    assert view[0]["deterministicResult"] == "evidence_insufficient"
    assert view[0]["decisionSource"] == "jev"


def test_no_qwen_plan_cannot_take_fixed_question_shortcut(monkeypatch):
    state, run, records, pack = _case()
    _enabled(monkeypatch)
    monkeypatch.setattr(jev_primary, "ask_jev", lambda *_, **_kw: 1 / 0)
    decision = jev_primary.decide_node(state, run, records, pack)
    assert decision["status"] == "qwen_question_plan_unavailable"
    assert jev_primary.apply_decision(records, decision)[0]["result"] == "human_review_required"


def test_qwen_invalid_or_missing_question_never_reaches_jev(monkeypatch):
    state, run, records, pack = _case()
    qwen = _Qwen({"questions": []})
    _enabled(monkeypatch, qwen)
    monkeypatch.setattr(jev_primary, "ask_jev", lambda *_, **_kw: 1 / 0)
    plan = jev_primary.author_node_questions(state, run, records, pack)
    assert plan["status"] == "qwen_question_plan_unavailable"
    assert jev_primary.decide_node(state, run, records, pack, plan)["status"] == "qwen_question_plan_unavailable"
    qwen.payload = {**_authored(), "answer": "passed"}
    assert jev_primary.author_node_questions(state, run, records, pack)["status"] == "qwen_question_plan_unavailable"


def test_qwen_malformed_response_is_reviewable_failure(monkeypatch):
    state, run, records, pack = _case()
    _enabled(monkeypatch)

    class MalformedQwen:
        def chat_sync(self, *_args, **_kwargs):
            return {"choices": "not a list"}

    monkeypatch.setattr(jev_primary, "qwen_runtime_client", MalformedQwen)
    plan = jev_primary.author_node_questions(state, run, records, pack)
    assert plan["status"] == "qwen_question_plan_unavailable"
    assert plan["reason"] == "TypeError"


def test_stale_question_plan_and_jev_unavailable_fail_to_human(monkeypatch):
    state, run, records, pack = _case()
    qwen = _Qwen(_authored())
    _enabled(monkeypatch, qwen)
    plan = jev_primary.author_node_questions(state, run, records, pack)
    old_prompt_plan = {**plan, "promptVersion": "jev-node-question-author-v1"}
    assert jev_primary.decide_node(state, run, records, pack, old_prompt_plan)["status"] == "stale_question_plan"
    state["ocr_parse_results"][0]["fragments"][0]["text"] = "焊接电流为 120A"
    assert jev_primary.decide_node(state, run, records, pack, plan)["status"] == "stale_question_plan"
    state["ocr_parse_results"][0]["fragments"][0]["text"] = "焊接电流为 90A"
    monkeypatch.setattr(jev_primary, "ask_jev", lambda *_, **_kw: (_ for _ in ()).throw(OSError("offline")))
    decision = jev_primary.decide_node(state, run, records, pack, plan)
    assert decision["status"] == "unavailable"
    assert jev_primary.apply_decision(records, decision)[0]["result"] == "human_review_required"


def test_primary_requires_explicit_project_egress_allowlist(monkeypatch):
    state, run, records, pack = _case()
    monkeypatch.delenv("AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS", raising=False)
    monkeypatch.setattr(jev_primary, "jev_stage_enabled", lambda _stage: True)
    monkeypatch.setattr(jev_primary, "qwen_runtime_client", lambda: 1 / 0)
    assert jev_primary.author_node_questions(state, run, records, pack)["status"] == "project_not_approved_for_jev"


def test_primary_rejects_stale_ocr_and_local_identifier_in_question(monkeypatch):
    state, run, records, pack = _case()
    qwen = _Qwen(_authored())
    _enabled(monkeypatch, qwen)
    state["ocr_parse_results"].append({"id": "NEW", "documentVersionId": "V", "status": "failed",
                                       "createdAt": "2026-09-23 10:00:00"})
    state["ocr_parse_results"][0]["createdAt"] = "2026-09-22 10:00:00"
    assert jev_primary.author_node_questions(state, run, records, pack)["status"] == "ocr_not_ready"
    state["ocr_parse_results"] = state["ocr_parse_results"][:1]
    qwen.payload = _authored()
    qwen.payload["questions"][0]["question"] += "请查看 secret-name.pdf"
    assert jev_primary.author_node_questions(state, run, records, pack)["status"] == "question_contains_local_identifier"


def test_primary_does_not_collapse_multiple_people(monkeypatch):
    state, run, records, pack = _case()
    _enabled(monkeypatch)
    run["nodeId"] = 24
    pack["atomicChecks"][0]["nodeId"] = 24
    pack["nodeTemplates"][0]["nodeId"] = 24
    assert jev_primary.author_node_questions(state, run, records, pack)["status"] == "multi_person_scope_unknown"


def test_multiple_people_get_separate_questions_and_worst_result_wins(monkeypatch):
    state, run, records, pack = _case()
    _enabled(monkeypatch)
    run["nodeId"] = 24
    state["ocr_parse_results"][0]["fragments"][0]["text"] = "张三的证书有效；李四的证书已到期"
    pack["nodeTemplates"] = [{"nodeId": 24, "name": "焊工资格", "requiredMaterials": []}]
    pack["atomicChecks"][0]["nodeId"] = 24
    facts = {"r24": {"certificates": [{"welderName": "张三"}, {"welderName": "李四"}]}}
    ids = ("AC-1__person_0", "AC-1__person_1")
    qwen = _Qwen(_authored(ids))
    monkeypatch.setattr(jev_primary, "qwen_runtime_client", lambda: qwen)
    plan = jev_primary.author_node_questions(state, run, records, pack, business_facts=facts)
    assert plan["status"] == "completed"
    assert len(plan["questions"]) == 2
    assert "张三" in qwen.calls[0][0][1]["content"]
    assert "李四" in qwen.calls[0][0][1]["content"]

    def answer(_text, questions, **_kwargs):
        assert len(questions) == 2
        return {"q0": {"type": "choice", "choice": "passed", "confidence": 0.8},
                "q1": {"type": "choice", "choice": "failed", "confidence": 0.9}}

    monkeypatch.setattr(jev_primary, "ask_jev", answer)
    decision = jev_primary.decide_node(state, run, records, pack, plan, business_facts=facts)
    assert decision["status"] == "completed"
    assert decision["atomic"][0]["choice"] == "failed"
    assert len(decision["atomic"][0]["perPerson"]) == 2
    assert jev_primary.apply_decision(records, decision)[0]["result"] == "failed"
    view = output_contract.atomic_check_outcomes(records, {**run, "jevDecision": decision})
    assert len(view[0]["perPerson"]) == 2


def test_unmatched_welding_record_person_blocks_group_answer(monkeypatch):
    state, run, records, pack = _case()
    _enabled(monkeypatch)
    run["nodeId"] = 29
    state["ocr_parse_results"][0]["fragments"][0]["text"] = "张三和李四的施焊记录"
    pack["nodeTemplates"][0]["nodeId"] = 29
    pack["atomicChecks"][0]["nodeId"] = 29
    facts = {"r29": {"certificates": [{"welderName": "张三"}],
                     "weldingRecords": [{"welderName": "李四"}]}}
    assert jev_primary.author_node_questions(state, run, records, pack,
                                              business_facts=facts)["status"] == "multi_person_scope_unknown"


def test_system_evidence_gate_stays_local_while_jev_decides_business_check(monkeypatch):
    state, run, records, pack = _case()
    qwen = _Qwen(_authored())
    _enabled(monkeypatch, qwen)
    records[0]["atomicCheckResults"].append({"atomicCheckId": "AC-GATE", "result": "passed",
        "toolResults": [{"toolName": "locate_evidence_fragment"},
                        {"toolName": "validate_evidence_grounding"}]})
    pack["atomicChecks"].append({"id": "AC-GATE", "nodeId": 25,
                                  "instruction": "证据引用是否可追溯"})
    plan = jev_primary.author_node_questions(state, run, records, pack)
    assert [row["atomicCheckId"] for row in plan["questions"]] == ["AC-1"]
    monkeypatch.setattr(jev_primary, "ask_jev", lambda _text, questions, **_kw: {
        "q0": {"type": "choice", "choice": "passed", "confidence": 0.8}} if set(questions) == {"q0"} else 1 / 0)
    decision = jev_primary.decide_node(state, run, records, pack, plan)
    assert decision["protectedAtomicCheckIds"] == ["AC-GATE"]
    effective = jev_primary.apply_decision(records, decision)
    assert [row["result"] for row in effective[0]["atomicCheckResults"]] == ["passed", "passed"]
    view = output_contract.atomic_check_outcomes(records, {**run, "jevDecision": decision})
    assert view[1]["decisionSource"] == "rule_engine"


def test_graph_requires_qwen_step_before_jev_step(monkeypatch):
    _state, run, records, pack = _case()
    context = {"project": {"businessPackSnapshot": pack}, "ruleResults": records}
    events = []

    def author(_state, _run, _records, _pack, **_kwargs):
        events.append("qwen")
        return {"status": "completed", "model": "qwen3.5-flash-2026-02-23",
                "questions": _authored()["questions"]}

    def decide(_state, _run, _records, _pack, question_plan, **_kwargs):
        assert question_plan == run["jevQuestionPlan"]
        events.append("jev")
        return {"status": "completed", "atomic": [{"atomicCheckId": "AC-1",
                "choice": "passed", "confidence": 0.8}], "protectedAtomicCheckIds": []}

    monkeypatch.setattr(execution, "author_node_questions", author)
    monkeypatch.setattr(execution, "decide_node", decide)
    execution.run_step(run, "qwen_compose_jev_questions", context)
    execution.run_step(run, "jev_decision", context)
    assert events == ["qwen", "jev"]
    assert context["ruleResults"][0]["result"] == "passed"
    assert context["deterministicRuleResults"][0]["result"] == "evidence_insufficient"


def test_r19_eight_questions_are_authored_then_answered(monkeypatch):
    state, run, records, pack = _case()
    run["nodeId"] = 19
    check_ids = tuple(f"AC-R19-{index}" for index in range(8))
    records[0]["atomicCheckResults"] = [
        {"atomicCheckId": check_id, "result": "evidence_insufficient", "toolResults": []}
        for check_id in check_ids
    ]
    pack["nodeTemplates"] = [{"nodeId": 19, "name": "材料复验", "requiredMaterials": []}]
    monkeypatch.setattr(jev_primary, "r19_semantic_questions", lambda _run: [
        {"questionId": check_id, "instruction": f"核查第 {index} 项材料条件"}
        for index, check_id in enumerate(check_ids)
    ])
    qwen = _Qwen(_authored(check_ids))
    _enabled(monkeypatch, qwen)
    plan = jev_primary.author_node_questions(state, run, records, pack)
    assert len(plan["questions"]) == 8

    def answers(_text, questions, **_kwargs):
        assert len(questions) == 8
        return {key: {"type": "choice", "choice": "evidence_insufficient", "confidence": 0.7}
                for key in questions}

    monkeypatch.setattr(jev_primary, "ask_jev", answers)
    decision = jev_primary.decide_node(state, run, records, pack, plan)
    assert decision["status"] == "completed"
    assert len(decision["atomic"]) == 8


def test_qwen_server_key_is_captured_without_logging(monkeypatch, capsys):
    def fake_run(command, **kwargs):
        assert command[-2:] == ["aicheck-prod-new", "python3 -"]
        assert "AICHECK_LLM_VISION_API_KEY" in kwargs["input"]
        assert kwargs["capture_output"] is True
        return CompletedProcess(command, 0, stdout="test-only-secret", stderr="")

    monkeypatch.setattr(run_jev_primary_lab_case.subprocess, "run", fake_run)
    assert run_jev_primary_lab_case._qwen_test_key_from_server() == "test-only-secret"
    assert "test-only-secret" not in capsys.readouterr().out


def test_qwen_server_key_failure_does_not_expose_secret(monkeypatch):
    def fake_run(command, **_kwargs):
        return CompletedProcess(command, 2, stdout="secret-from-bad-host", stderr="error")

    monkeypatch.setattr(run_jev_primary_lab_case.subprocess, "run", fake_run)
    try:
        run_jev_primary_lab_case._qwen_test_key_from_server()
    except RuntimeError as exc:
        assert str(exc) == "qwen_server_key_unavailable"
        assert "secret-from-bad-host" not in str(exc)
    else:
        raise AssertionError("server key error was accepted")
