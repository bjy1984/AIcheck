"""R19 Jev answers applicability plus a three-way judgment without taking control."""

from copy import deepcopy

from libs.review_orchestrator import jev_opinion
from libs.review_orchestrator.r19_agent import R19_REVIEW_QUESTIONS


def _case():
    state = {
        "documents": [{"id": "D", "projectId": "P", "fileName": "境外材料.pdf"}],
        "versions": [{"id": "V", "documentId": "D"}],
        "ocr_parse_results": [{"id": "OCR", "documentVersionId": "V", "fragments": [
            {"text": "境外材料炉批 H1，产品证明与复验记录见本页。", "pageNo": 2},
        ]}],
    }
    run = {"projectId": "P", "nodeId": 19, "reviewMode": "formal",
           "inputDocumentVersionIds": ["V"]}
    results = [{"atomicCheckResults": [
        {"atomicCheckId": item["questionId"], "result": "passed"}
        for item in R19_REVIEW_QUESTIONS
    ]}]
    return state, run, results


def test_r19_records_eight_shadow_choices_and_support_pages_without_changing_review(monkeypatch):
    state, run, results = _case()
    original_state, original_run, original_results = deepcopy((state, run, results))
    monkeypatch.setattr(jev_opinion, "jev_stage_enabled", lambda _: True)

    def recorded_answers(full_state, questions):
        assert "境外材料炉批 H1" in full_state
        assert "已核实且无冲突的规则检查：[]" in full_state
        assert len([key for key in questions if key.startswith("a")]) == 8
        assert len([key for key in questions if key.startswith("j")]) == 8
        answers = {}
        for index in range(8):
            applicability = "not_applicable" if index == 3 else "unknown" if index == 4 else "applicable"
            judgment = "failed" if index == 1 else "evidence_insufficient" if index == 2 else "passed"
            answers[f"a{index}"] = {"type": "choice", "choice": applicability, "confidence": 0.87}
            answers[f"j{index}"] = {"type": "choice", "choice": judgment, "confidence": 0.81}
            answers[f"p{index}"] = {"type": "choice", "choice": "V:p2", "confidence": 0.9}
        return answers

    monkeypatch.setattr(jev_opinion, "ask_jev", recorded_answers)
    shadow = jev_opinion.second_opinions(state, run, results, {})

    assert shadow["status"] == "completed"
    assert shadow["comparisonSource"] == "r19_semantic_review"
    assert [row["atomicCheckId"] for row in shadow["atomic"]] == [
        item["questionId"] for item in R19_REVIEW_QUESTIONS]
    assert [row["choice"] for row in shadow["atomic"][:5]] == [
        "passed", "failed", "evidence_insufficient", "not_applicable", "evidence_insufficient"]
    assert shadow["atomic"][0]["confidence"] == 0.81
    assert shadow["atomic"][3]["confidence"] == 0.87
    assert shadow["atomic"][1]["agreesWithCurrentResult"] is False
    assert shadow["atomic"][0]["agreesWithCurrentResult"] is True
    assert all(row["agreesWithRuleEngine"] is None for row in shadow["atomic"])
    assert all(row["suggestedSupportPage"] == "V:p2" for row in shadow["atomic"])
    assert (state, run, results) == (original_state, original_run, original_results)


def test_r19_disabled_missing_failed_and_overlong_do_not_call_jev(monkeypatch):
    state, run, results = _case()
    monkeypatch.setattr(jev_opinion, "ask_jev", lambda *_: 1 / 0)
    monkeypatch.setattr(jev_opinion, "jev_stage_enabled", lambda _: False)
    assert jev_opinion.second_opinions(state, run, results, {})["status"] == "disabled"
    monkeypatch.setattr(jev_opinion, "jev_stage_enabled", lambda _: True)
    state["ocr_parse_results"] = []
    assert jev_opinion.second_opinions(state, run, results, {})["status"] == "missing_document_text"
    state, run, results = _case()
    state["ocr_parse_results"][0]["status"] = "failed"
    assert jev_opinion.second_opinions(state, run, results, {})["status"] == "ocr_not_ready"
    state, run, results = _case()
    state["ocr_parse_results"][0]["fragments"][0]["text"] = "长" * 40_000
    assert jev_opinion.second_opinions(state, run, results, {})["status"] == "overlong_documents"


def test_r19_unreachable_or_incomplete_answer_only_marks_shadow_unavailable(monkeypatch):
    state, run, results = _case()
    monkeypatch.setattr(jev_opinion, "jev_stage_enabled", lambda _: True)
    for error in (OSError("offline"), ValueError("jev_incomplete_answers")):
        def fail(_state, _questions, error=error):
            raise error
        monkeypatch.setattr(jev_opinion, "ask_jev", fail)
        assert jev_opinion.second_opinions(state, run, results, {})["status"] == "unavailable"
        assert all(row["result"] == "passed" for row in results[0]["atomicCheckResults"])
