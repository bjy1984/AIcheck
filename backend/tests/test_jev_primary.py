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
        "atomicChecks": [{"id": "AC-1", "nodeId": 25, "instruction": "焊接工艺是否记录电流",
                          "checkType": "evidence_and_llm_semantic_judgment"}]}
    return state, run, records, pack


def _enabled(monkeypatch, _unused=None):
    monkeypatch.setenv("AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS", "P")
    monkeypatch.setattr(jev_primary, "jev_stage_enabled", lambda stage: stage == "PRIMARY_DECISION")


def test_frozen_questions_and_jev_only_hints_beside_rule_result(monkeypatch):
    state, run, records, pack = _case()
    _enabled(monkeypatch)
    original = deepcopy(records)
    plan = jev_primary.author_node_questions(state, run, records, pack)
    assert plan["status"] == "completed" and plan["model"] == "frozen-template"
    question = plan["questions"][0]

    def answer(text, questions, **_kwargs):
        assert "焊接电流为 90A" in text
        assert questions["q0"]["instructions"] == question["question"]
        assert questions["q0"]["criteria"] == jev_primary.FROZEN_OPTIONS
        assert "secret-name.pdf" not in repr(questions)
        return {"q0": {"type": "choice", "choice": "passed", "confidence": 0.83}}

    monkeypatch.setattr(jev_primary, "ask_jev", answer)
    assert "焊接工艺是否记录电流" in question["question"]
    assert "焊接电流为 90A" not in question["question"], "题目不能夹带 OCR 原文"
    assert "缺少资料不能当成不适用" in question["options"]["not_applicable"]
    decision = jev_primary.decide_node(state, run, records, pack, plan)
    effective = jev_primary.attach_hints(records, decision)
    assert decision["status"] == "completed"
    assert decision["role"] == "advisory"
    assert decision["questionPlanHash"] == plan["questionHash"]
    assert decision["opinionResult"] == "passed"
    assert decision["disagreementAtomicCheckIds"] == ["AC-1"]
    # A 0.83 "passed" from Jev never turns the rule's evidence_insufficient into a pass.
    assert effective[0]["result"] == "evidence_insufficient"
    assert effective[0]["atomicCheckResults"][0]["result"] == "evidence_insufficient"
    assert effective[0]["atomicCheckResults"][0]["jevHint"] == {
        "choice": "passed", "confidence": 0.83, "agreesWithRuleEngine": False}
    assert effective[0]["jevDisagreementAtomicCheckIds"] == ["AC-1"]
    assert records == original
    view = output_contract.atomic_check_outcomes(effective, {**run, "jevDecision": decision})
    assert view[0]["result"] == "evidence_insufficient"
    assert view[0]["decisionSource"] == "rule_engine"
    assert view[0]["jevHint"]["choice"] == "passed"
    assert jev_primary.jev_hint_summary(decision) == {"jevHint": {
        "status": "completed", "disagreementCount": 1, "opinionResult": "passed"}}


def test_no_qwen_plan_cannot_take_fixed_question_shortcut(monkeypatch):
    state, run, records, pack = _case()
    _enabled(monkeypatch)
    monkeypatch.setattr(jev_primary, "ask_jev", lambda *_, **_kw: 1 / 0)
    decision = jev_primary.decide_node(state, run, records, pack)
    assert decision["status"] == "qwen_question_plan_unavailable"
    hinted = jev_primary.attach_hints(records, decision)
    assert hinted[0]["result"] == "evidence_insufficient"
    assert hinted[0]["jevHintStatus"] == "qwen_question_plan_unavailable"
    assert "jevHint" not in hinted[0]["atomicCheckResults"][0]


def test_same_inputs_always_give_the_same_questions(monkeypatch):
    # 旧版每次运行让 Qwen 重新出题，同输入重跑题目哈希全变。
    state, run, records, pack = _case()
    _enabled(monkeypatch)
    first = jev_primary.author_node_questions(state, run, records, pack)
    second = jev_primary.author_node_questions(state, run, records, pack)
    assert first["questionHash"] == second["questionHash"] and first["questions"] == second["questions"]


def test_stale_question_plan_and_jev_unavailable_fail_to_human(monkeypatch):
    state, run, records, pack = _case()
    _enabled(monkeypatch)
    plan = jev_primary.author_node_questions(state, run, records, pack)
    old_prompt_plan = {**plan, "promptVersion": "jev-node-question-author-v2"}
    assert jev_primary.decide_node(state, run, records, pack, old_prompt_plan)["status"] == "stale_question_plan"
    state["ocr_parse_results"][0]["fragments"][0]["text"] = "焊接电流为 120A"
    assert jev_primary.decide_node(state, run, records, pack, plan)["status"] == "stale_question_plan"
    state["ocr_parse_results"][0]["fragments"][0]["text"] = "焊接电流为 90A"
    monkeypatch.setattr(jev_primary, "ask_jev", lambda *_, **_kw: (_ for _ in ()).throw(OSError("offline")))
    decision = jev_primary.decide_node(state, run, records, pack, plan)
    assert decision["status"] == "unavailable"
    assert jev_primary.attach_hints(records, decision)[0]["result"] == "evidence_insufficient"


def test_primary_requires_explicit_project_egress_allowlist(monkeypatch):
    state, run, records, pack = _case()
    monkeypatch.delenv("AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS", raising=False)
    monkeypatch.setattr(jev_primary, "jev_stage_enabled", lambda _stage: True)
    assert jev_primary.author_node_questions(state, run, records, pack)["status"] == "project_not_approved_for_jev"
    records[0]["atomicCheckResults"][0]["result"] = records[0]["result"] = "failed"
    decision = jev_primary.decide_node(state, run, records, pack)
    # A project outside the allowlist keeps the rule's failure visible.
    assert jev_primary.attach_hints(records, decision)[0]["atomicCheckResults"][0]["result"] == "failed"


def test_primary_rejects_stale_ocr_and_local_identifier_in_question(monkeypatch):
    state, run, records, pack = _case()
    _enabled(monkeypatch)
    state["ocr_parse_results"].append({"id": "NEW", "documentVersionId": "V", "status": "failed",
                                       "createdAt": "2026-09-23 10:00:00"})
    state["ocr_parse_results"][0]["createdAt"] = "2026-09-22 10:00:00"
    assert jev_primary.author_node_questions(state, run, records, pack)["status"] == "ocr_not_ready"
    state["ocr_parse_results"] = state["ocr_parse_results"][:1]
    pack["atomicChecks"][0]["instruction"] += "，参见 secret-name.pdf"
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
    plan = jev_primary.author_node_questions(state, run, records, pack, business_facts=facts)
    assert plan["status"] == "completed"
    assert len(plan["questions"]) == 2
    assert "仅评价持证人张三" in plan["questions"][0]["question"]
    assert "仅评价持证人李四" in plan["questions"][1]["question"]

    def answer(_text, questions, **_kwargs):
        assert len(questions) == 2
        return {"q0": {"type": "choice", "choice": "passed", "confidence": 0.8},
                "q1": {"type": "choice", "choice": "failed", "confidence": 0.9}}

    monkeypatch.setattr(jev_primary, "ask_jev", answer)
    decision = jev_primary.decide_node(state, run, records, pack, plan, business_facts=facts)
    assert decision["status"] == "completed"
    assert decision["atomic"][0]["choice"] == "failed"
    assert len(decision["atomic"][0]["perPerson"]) == 2
    hinted = jev_primary.attach_hints(records, decision)
    assert hinted[0]["result"] == "evidence_insufficient"
    view = output_contract.atomic_check_outcomes(hinted, {**run, "jevDecision": decision})
    assert view[0]["jevHint"]["choice"] == "failed"
    assert len(view[0]["jevHint"]["perPerson"]) == 2


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


def test_system_evidence_gate_stays_local_while_jev_hints_business_check(monkeypatch):
    state, run, records, pack = _case()
    _enabled(monkeypatch)
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
    assert decision["ruleOwnedAtomicCheckIds"] == ["AC-GATE"]
    effective = jev_primary.attach_hints(records, decision)
    assert [row["result"] for row in effective[0]["atomicCheckResults"]] == ["evidence_insufficient", "passed"]
    view = output_contract.atomic_check_outcomes(effective, {**run, "jevDecision": decision})
    assert view[0]["jevHint"]["choice"] == "passed"
    assert "jevHint" not in view[1]


def test_certificate_and_calculation_checks_are_never_sent_to_jev(monkeypatch):
    state, run, records, pack = _case()
    _enabled(monkeypatch)
    for check_id, tool in (("AC-CERT", "check_certificate_validity"), ("AC-DATE", "check_date_covers"),
                           ("AC-WELDER", "verify_welder_on_platform")):
        records[0]["atomicCheckResults"].append({"atomicCheckId": check_id, "result": "failed",
            "toolResults": [{"toolName": "extract_document_fields"}, {"toolName": tool},
                            {"toolName": "validate_evidence_grounding"}]})
        pack["atomicChecks"].append({"id": check_id, "nodeId": 25, "instruction": f"{tool} 是否满足"})
    plan = jev_primary.author_node_questions(state, run, records, pack)
    assert [row["atomicCheckId"] for row in plan["questions"]] == ["AC-1"]
    assert "check_certificate_validity" not in json.dumps(plan["questions"], ensure_ascii=False)
    monkeypatch.setattr(jev_primary, "ask_jev", lambda _text, questions, **_kw: {
        key: {"type": "choice", "choice": "passed", "confidence": 1.0} for key in questions})
    decision = jev_primary.decide_node(state, run, records, pack, plan)
    assert decision["ruleOwnedAtomicCheckIds"] == ["AC-CERT", "AC-DATE", "AC-WELDER"]
    effective = jev_primary.attach_hints(records, decision)
    assert [row["result"] for row in effective[0]["atomicCheckResults"]] == [
        "evidence_insufficient", "failed", "failed", "failed"]
    assert [("jevHint" in row) for row in effective[0]["atomicCheckResults"]] == [True, False, False, False]


def test_only_certificate_checks_means_no_jev_question(monkeypatch):
    state, run, records, pack = _case()
    _enabled(monkeypatch)
    records[0]["atomicCheckResults"][0]["toolResults"] = [{"toolName": "check_certificate_validity"}]
    assert jev_primary.author_node_questions(state, run, records, pack)["status"] == "no_semantic_checks"


def test_graph_requires_qwen_step_before_jev_step(monkeypatch):
    _state, run, records, pack = _case()
    context = {"project": {"businessPackSnapshot": pack}, "ruleResults": records}
    events = []

    def author(_state, _run, _records, _pack, **_kwargs):
        events.append("qwen")
        return {"status": "completed", "model": "qwen3.5-flash-2026-02-23",
                "questions": [{"atomicCheckId": "AC-1", "question": "冻结题目：焊接工艺是否记录电流？",
                               "options": jev_primary.FROZEN_OPTIONS}]}

    def decide(_state, _run, _records, _pack, question_plan, **_kwargs):
        assert question_plan == run["jevQuestionPlan"]
        events.append("jev")
        return {"status": "completed", "atomic": [{"atomicCheckId": "AC-1",
                "choice": "passed", "confidence": 0.8}], "ruleOwnedAtomicCheckIds": []}

    monkeypatch.setattr(execution, "author_node_questions", author)
    monkeypatch.setattr(execution, "decide_node", decide)
    execution.run_step(run, "qwen_compose_jev_questions", context)
    execution.run_step(run, "jev_decision", context)
    assert events == ["qwen", "jev"]
    assert context["ruleResults"][0]["result"] == "evidence_insufficient"
    assert context["ruleResults"][0]["atomicCheckResults"][0]["jevHint"]["choice"] == "passed"
    assert records[0]["atomicCheckResults"][0].get("jevHint") is None


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
    _enabled(monkeypatch)
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


def test_token_limit_refusal_is_its_own_status(monkeypatch):
    state, run, records, pack = _case()
    _enabled(monkeypatch)
    plan = jev_primary.author_node_questions(state, run, records, pack)
    monkeypatch.setattr(jev_primary, "ask_jev",
                        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("jev_request_overlong")))
    decision = jev_primary.decide_node(state, run, records, pack, plan)
    assert decision["status"] == "request_overlong"
    assert jev_primary.attach_hints(records, decision)[0]["result"] == "evidence_insufficient"


def test_deterministic_rule_checks_never_get_a_jev_opinion(monkeypatch):
    # 业务包标为确定性规则的原子项由冻结判据的工具判定；让 Jev 再判等于重算门槛，实测会错。
    state, run, records, pack = _case()
    _enabled(monkeypatch)
    pack["atomicChecks"][0]["checkType"] = "evidence_and_deterministic_rule"
    plan = jev_primary.author_node_questions(state, run, records, pack)
    assert plan["status"] == "no_semantic_checks"
    decision = jev_primary.decide_node(state, run, records, pack, plan)
    assert jev_primary.attach_hints(records, decision) == records


def test_a_name_seen_only_inside_a_longer_name_is_not_in_scope(monkeypatch):
    state, run, records, pack = _case()
    _enabled(monkeypatch)
    run["nodeId"] = 24
    pack["nodeTemplates"] = [{"nodeId": 24, "name": "焊工资格", "requiredMaterials": []}]
    pack["atomicChecks"][0]["nodeId"] = 24
    facts = {"r24": {"certificates": [{"welderName": "李卫"}, {"welderName": "李卫伍"}]}}
    state["ocr_parse_results"][0]["fragments"][0]["text"] = "李卫伍的焊工证有效期至2027年8月31日"
    assert jev_primary.author_node_questions(state, run, records, pack,
                                             business_facts=facts)["status"] == "multi_person_scope_unknown"
    assert jev_primary._appears_on_its_own("李卫", ["李卫", "李卫伍"], "李卫伍与李卫的焊工证")
