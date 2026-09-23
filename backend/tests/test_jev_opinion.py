from __future__ import annotations

from libs.review_orchestrator import jev_opinion


def _case():
    state = {
        "documents": [{"id": "D", "projectId": "P", "fileName": "许可证.pdf"}],
        "document_versions": [{"id": "V", "documentId": "D"}],
        "ocr_parse_results": [{"documentVersionId": "V", "fragments": [
            {"text": "许可范围 GC1", "pageNo": 1}]}],
    }
    run = {"projectId": "P", "nodeId": 1, "inputDocumentVersionIds": ["V"]}
    rule_results = [{"atomicCheckResults": [{"atomicCheckId": "AC-R01-02", "result": "passed"}]}]
    pack = {"atomicChecks": [{"id": "AC-R01-02", "nodeId": 1,
                               "instruction": "GC2 管道须有 GC2 或 GC1 设计许可"}]}
    return state, run, rule_results, pack


def test_shadow_opinion_records_disagreement_without_mutating_verdict(monkeypatch):
    state, run, rule_results, pack = _case()
    monkeypatch.setattr(jev_opinion, "jev_stage_enabled", lambda _: True)

    def fake_ask(full_state, questions):
        assert "许可范围 GC1" in full_state
        assert questions["q0"]["criteria"]["evidence_insufficient"]
        return {"q0": {"type": "choice", "choice": "evidence_insufficient", "confidence": 0.61},
                "p0": {"type": "choice", "choice": "V:p1", "confidence": 0.9}}

    monkeypatch.setattr(jev_opinion, "ask_jev", fake_ask)
    result = jev_opinion.second_opinions(state, run, rule_results, pack)
    assert result["status"] == "completed"
    assert result["atomic"] == [{"atomicCheckId": "AC-R01-02", "choice": "evidence_insufficient",
                                  "confidence": 0.61, "model": "jev-1.13.0", "agreesWithRuleEngine": False,
                                  "suggestedSupportPage": "V:p1",
                                  "sourceDocumentVersionIds": ["V"]}]
    assert rule_results[0]["atomicCheckResults"][0]["result"] == "passed"


def test_unapproved_egress_does_not_call_model(monkeypatch):
    state, run, rule_results, pack = _case()
    monkeypatch.setattr(jev_opinion, "jev_stage_enabled", lambda _: False)
    monkeypatch.setattr(jev_opinion, "ask_jev", lambda *_: 1 / 0)
    assert jev_opinion.second_opinions(state, run, rule_results, pack)["status"] == "disabled"


def test_multiple_whole_files_with_conflicting_answers_are_human_only(monkeypatch):
    state, run, rule_results, pack = _case()
    state["documents"].append({"id": "D2", "projectId": "P", "fileName": "图纸.pdf"})
    state["document_versions"].append({"id": "V2", "documentId": "D2"})
    state["ocr_parse_results"].append({"documentVersionId": "V2", "fragments": [
        {"text": "GC2", "pageNo": 1}]})
    run["inputDocumentVersionIds"] = ["V", "V2"]
    monkeypatch.setattr(jev_opinion, "jev_stage_enabled", lambda _: True)
    monkeypatch.setattr(jev_opinion, "MAX_STATE_CHARS", 90)
    calls = []

    def fake_ask(full_state, questions):
        calls.append(full_state)
        return {"q0": {"type": "choice", "choice": "passed" if len(calls) == 1 else "failed",
                       "confidence": 0.93}}

    monkeypatch.setattr(jev_opinion, "ask_jev", fake_ask)
    result = jev_opinion.second_opinions(state, run, rule_results, pack)
    assert len(calls) == 2
    assert result["atomic"][0]["choice"] == "human_review_required"
    assert result["atomic"][0]["confidence"] == 0.0


def test_welder_opinion_is_asked_per_person(monkeypatch):
    state, run, rule_results, pack = _case()
    run["nodeId"] = 24
    pack["atomicChecks"][0]["nodeId"] = 24
    business = {"r24": {"certificates": [{"welderName": "王一"}, {"welderName": "李二"}]}}
    monkeypatch.setattr(jev_opinion, "jev_stage_enabled", lambda _: True)

    def fake_ask(_full_state, questions):
        assert "李二" in questions["q0_n0"]["instructions"]
        assert "王一" in questions["q0_n1"]["instructions"]
        return {key: {"type": "choice", "choice": "passed" if key == "q0_n0" else "failed"
                if key == "q0_n1" else "none", "confidence": 0.8} for key in questions}

    monkeypatch.setattr(jev_opinion, "ask_jev", fake_ask)
    result = jev_opinion.second_opinions(state, run, rule_results, pack, business_facts=business)
    opinion = result["atomic"][0]
    assert [row["person"] for row in opinion["perPerson"]] == ["李二", "王一"]
    assert opinion["choice"] == "human_review_required"
    assert opinion["confidence"] == 0.0
