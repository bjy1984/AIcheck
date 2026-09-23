from __future__ import annotations

from libs.review_orchestrator import execution, jev_fact_check, jev_primary, output_contract

R02_SUSPECT = ("安装（施工）单位许可证·有效期截止日=2024-09-07"
               "（原文第1页：「特种设备生产许可证有效期：2024年9月7日至2028年9月6日」）")


def _state():
    return {
        "documents": [{"id": "D1", "projectId": "P", "fileName": "安装许可证.pdf"},
                      {"id": "D2", "projectId": "P", "fileName": "焊工证.pdf"}],
        "versions": [{"id": "V1", "documentId": "D1"}, {"id": "V2", "documentId": "D2"}],
        "ocr_parse_results": [
            {"id": "O1", "documentVersionId": "V1", "status": "success",
             "fragments": [{"pageNo": 1, "text": "特种设备生产许可证 有效期：2024年9月7日至2028年9月6日"}]},
            {"id": "O2", "documentVersionId": "V2", "status": "success",
             "fragments": [{"pageNo": 1, "text": "焊工证 姓名：张三"}]},
        ],
    }


def _run():
    return {"projectId": "P", "nodeId": 2, "reviewMode": "formal", "inputDocumentVersionIds": ["V1", "V2"]}


def _verification(valid_until="2024-09-07"):
    return {"atomicCheckId": "AC-R02-02", "certificateType": "installation_license", "certificates": [{
        "label": "TS3841999-2028", "certificateType": "installation_license", "holder": "示例管道安装有限公司",
        "certificateNo": "TS3841999-2028", "validFrom": "2024-07-31", "validUntil": valid_until,
        "evidenceRefs": [{"documentVersionId": "V1", "pageNo": 1}]}]}


def _enabled(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS", "P")
    monkeypatch.setattr(jev_fact_check, "jev_stage_enabled", lambda stage: stage == "FACT_CHECK")


def test_questions_come_from_the_rule_facts_with_a_fixed_template():
    questions = jev_fact_check.fact_questions(_verification())
    assert list(questions) == ["V1"]
    texts = [item["instructions"] for item in questions["V1"]]
    assert texts[0] == ("只看示例管道安装有限公司的安装（施工）单位许可证：它的有效期截止日是否为2024年9月7日？"
                        "起始日、发证日期和其他证书的日期都不是截止日。")
    assert [item["field"] for item in questions["V1"]] == ["validUntil", "validFrom", "certificateNo", "holder"]
    assert texts[-1].startswith("只看证件编号为TS3841999-2028的安装（施工）单位许可证：它的持证单位或持证人是否为示例管道安装有限公司")
    assert jev_fact_check.fact_questions(_verification()) == questions, "同样的事实必须得到同样的题目"


def test_a_rejected_extracted_value_is_marked_suspect_and_only_its_document_is_sent(monkeypatch):
    _enabled(monkeypatch)
    sent = []

    def answer(text, questions, **_kwargs):
        sent.append(text)
        return {key: {"type": "choice", "choice": "no" if key == "f0" else "yes",
                      "confidence": 0.98 if key == "f0" else 0.95} for key in questions}

    monkeypatch.setattr(jev_fact_check, "ask_jev", answer)
    result = jev_fact_check.check_certificate_facts(_state(), _run(), _verification())
    assert result["status"] == "completed"
    assert result["suspects"] == [R02_SUSPECT]
    assert len(sent) == 1 and "2028年9月6日" in sent[0] and "张三" not in sent[0]
    assert result["atomicCheckId"] == "AC-R02-02"


def test_low_confidence_no_is_not_a_suspect(monkeypatch):
    _enabled(monkeypatch)
    monkeypatch.setattr(jev_fact_check, "ask_jev", lambda _text, questions, **_kw: {
        key: {"type": "choice", "choice": "no", "confidence": 0.5} for key in questions})
    result = jev_fact_check.check_certificate_facts(_state(), _run(), _verification())
    assert result["suspects"] == []
    assert all(row["lowConfidence"] for row in result["facts"])


def test_gates_and_failures_never_raise(monkeypatch):
    assert jev_fact_check.check_certificate_facts(_state(), _run(), _verification())["status"] == "disabled"
    _enabled(monkeypatch)
    assert jev_fact_check.check_certificate_facts(
        _state(), {**_run(), "projectId": "OTHER"}, _verification())["status"] == "project_not_approved_for_jev"
    assert jev_fact_check.check_certificate_facts(
        _state(), {**_run(), "reviewMode": "advisory"}, _verification())["status"] == "nonformal_run"
    assert jev_fact_check.check_certificate_facts(_state(), _run(), None)["status"] == "no_certificate_facts"
    monkeypatch.setattr(jev_fact_check, "ask_jev",
                        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("jev_request_overlong")))
    result = jev_fact_check.check_certificate_facts(_state(), _run(), _verification())
    assert result["status"] == "request_overlong" and result["suspects"] == []
    monkeypatch.setattr(jev_fact_check, "ask_jev", lambda *_a, **_k: (_ for _ in ()).throw(OSError("offline")))
    assert jev_fact_check.check_certificate_facts(_state(), _run(), _verification())["status"] == "unavailable"


def test_fact_with_more_than_one_source_document_is_not_asked():
    verification = _verification()
    verification["certificates"][0]["evidenceRefs"].append({"documentVersionId": "V2"})
    assert jev_fact_check.fact_questions(verification) == {}


def test_graph_step_records_fact_check_and_output_shows_it_on_the_certificate_check(monkeypatch):
    _enabled(monkeypatch)
    monkeypatch.setattr(jev_fact_check, "ask_jev", lambda _text, questions, **_kw: {
        key: {"type": "choice", "choice": "no" if key == "f0" else "yes", "confidence": 0.97} for key in questions})
    monkeypatch.setattr(execution, "decide_node", lambda *_a, **_k: {"status": "no_semantic_checks", "atomic": []})
    monkeypatch.setattr(execution.repo, "state", _state())
    records = [{"result": "failed", "ruleCode": "R02", "atomicCheckResults": [
        {"atomicCheckId": "AC-R02-02", "result": "failed", "toolResults": []}]}]
    run = _run()
    context = {"project": {"businessPackSnapshot": {}}, "ruleResults": records,
               "certificateVerification": _verification()}
    output = execution.run_step(run, "jev_decision", context)
    assert output["factSuspectCount"] == 1
    assert context["ruleResults"][0]["atomicCheckResults"][0]["result"] == "failed", "核对不改规则结论"
    view = output_contract.atomic_check_outcomes(context["ruleResults"], run)
    assert view[0]["result"] == "failed"
    assert view[0]["jevFactCheck"]["suspects"] == [R02_SUSPECT]
    summary = jev_primary.jev_hint_summary(run["jevDecision"], run["jevFactCheck"])
    assert summary == {"jevHint": {"factCheckStatus": "completed",
                                   "factSuspects": [R02_SUSPECT]}}


def test_look_alike_holders_in_one_document_are_named_with_their_certificate_number():
    # 边界实测：同表「李卫／李卫伍」时 Jev 以 0.41 把李卫答错过。
    certificates = [
        {"certificateType": "welder_certificate", "holder": holder, "certificateNo": number,
         "validUntil": until, "evidenceRefs": [{"documentVersionId": "V2"}]}
        for holder, number, until in (("李卫", "110101199001010011", "2025-11-30"),
                                      ("李卫伍", "110101199202020022", "2027-08-31"))]
    questions = jev_fact_check.fact_questions({"certificateType": "welder_certificate", "certificates": certificates})
    texts = [item["instructions"] for item in questions["V2"] if item["field"] == "validUntil"]
    assert texts[0].startswith("只看李卫（证件编号110101199001010011）的焊工资格证")
    assert texts[1].startswith("只看李卫伍的焊工资格证")


def _design_facts(versions=("V1",)):
    return {"designSpecialRequirements": {"domains": {
        "pressureTest": {"specified": True, "source": {"documentVersionIds": list(versions)},
                         "requirements": {"method": "液压试验", "testPressure": "1.5倍设计压力",
                                          "gaugeCount": 2, "gaugeAccuracyClass": 1.6,
                                          "hydroTest": True, "pressureTestStatements": None}},
        "leakTest": {"specified": False, "source": {"documentVersionIds": list(versions)}, "requirements": {}},
    }}}


def _design_rules():
    return [{"atomicCheckResults": [{"atomicCheckId": "AC-R09-01", "result": "evidence_insufficient",
                                     "toolResults": [{"toolName": "evaluate_design_special_requirements"}]}]}]


def test_design_test_requirements_become_fact_questions_without_arithmetic():
    items = jev_fact_check.design_fact_items(_design_facts(), _design_rules())
    assert [(item["field"], item["value"]) for item in items] == [
        ("pressureTest.method", "液压试验"), ("pressureTest.testPressure", "1.5倍设计压力"),
        ("pressureTest.gaugeAccuracyClass", "1.6"), ("pressureTest.gaugeCount", "2")]
    assert all(item["atomicCheckId"] == "AC-R09-01" for item in items)
    assert items[1]["instructions"] == ("只看设计文件中关于耐压试验的要求：试验压力是否写为1.5倍设计压力？"
                                        "只核对原文写明的内容，不做换算或推算；其他试验的要求不算。")


def test_design_facts_without_a_known_source_or_rule_are_not_asked():
    assert jev_fact_check.design_fact_items(_design_facts(versions=()), _design_rules()) == []
    assert jev_fact_check.design_fact_items(_design_facts(), []) == []


def test_certificate_and_design_suspects_attach_to_their_own_checks(monkeypatch):
    _enabled(monkeypatch)
    monkeypatch.setattr(jev_fact_check, "ask_jev", lambda _text, questions, **_kw: {
        key: {"type": "choice", "choice": "no" if key == "f0" else "yes", "confidence": 0.95} for key in questions})
    items = (jev_fact_check.certificate_fact_items(_verification())
             + jev_fact_check.design_fact_items(_design_facts(), _design_rules()))
    result = jev_fact_check.check_facts(_state(), _run(), items)
    assert result["atomicCheckIds"] == ["AC-R02-02", "AC-R09-01"]
    # 证书与设计说明同在 V1：一次请求，第一个事实（证书截止日）被否决。
    assert result["suspects"] == [R02_SUSPECT]
    records = [{"ruleCode": "R", "atomicCheckResults": [
        {"atomicCheckId": "AC-R02-02", "result": "failed", "toolResults": []},
        {"atomicCheckId": "AC-R09-01", "result": "evidence_insufficient", "toolResults": []}]}]
    view = output_contract.atomic_check_outcomes(records, {**_run(), "jevFactCheck": result})
    assert view[0]["jevFactCheck"]["suspects"] == [R02_SUSPECT]
    assert view[1]["jevFactCheck"]["suspects"] == []
    assert {row["field"] for row in view[1]["jevFactCheck"]["facts"]} >= {"pressureTest.method"}


def test_a_suspect_value_not_written_anywhere_says_so(monkeypatch):
    _enabled(monkeypatch)
    monkeypatch.setattr(jev_fact_check, "ask_jev", lambda _text, questions, **_kw: {
        key: {"type": "choice", "choice": "no" if key == "f0" else "yes", "confidence": 0.95} for key in questions})
    result = jev_fact_check.check_certificate_facts(_state(), _run(), _verification(valid_until="2026-01-31"))
    assert result["suspects"] == ["安装（施工）单位许可证·有效期截止日=2026-01-31（原文中找不到这个值）"]
    assert "located" not in result["facts"][0]
