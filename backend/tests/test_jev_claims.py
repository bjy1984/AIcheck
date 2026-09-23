from __future__ import annotations

from copy import deepcopy

from libs.review_orchestrator import jev_claims


def _case():
    state = {
        "documents": [{"id": "D", "projectId": "P", "fileName": "工艺卡.pdf"}],
        "document_versions": [{"id": "V", "documentId": "D"}],
        "ocr_parse_results": [{"documentVersionId": "V", "fragments": [
            {"text": "焊接电流 90A", "pageNo": 1}]}],
    }
    run = {"projectId": "P", "nodeId": 25, "inputDocumentVersionIds": ["V"]}
    drafts = [{"id": "F1", "title": "电流记录不一致", "description": "焊接电流为 900A，超出规程范围。",
               "claims": ["焊接电流为 900A"], "confidence": 0.9, "groundingStatus": "grounded",
               "unsupportedClaims": []}]
    return state, run, drafts


def _fake_answer(_state, questions):
    assert "焊接电流 90A" in _state
    assert "焊接电流为 900A" in questions["c0_0"]["instructions"]
    return {"c0_0": {"type": "choice", "choice": "not_in_materials", "confidence": 0.99}}


def test_claims_are_shadow_only_before_calibration(monkeypatch):
    state, run, drafts = _case()
    original = deepcopy(drafts)
    monkeypatch.setattr(jev_claims, "jev_stage_enabled", lambda _: True)
    monkeypatch.setattr(jev_claims, "ask_jev", _fake_answer)
    monkeypatch.delenv("AICHECK_JEV_CALIBRATION_APPROVED", raising=False)
    result = jev_claims.verify_finding_claims(state, run, [], drafts)
    assert result["findings"][0]["claims"][0]["choice"] == "not_in_materials"
    assert result["rejectionGateApplied"] is False
    assert drafts == original


def test_calibrated_gate_removes_rejected_claim_from_human_output(monkeypatch):
    state, run, drafts = _case()
    monkeypatch.setattr(jev_claims, "jev_stage_enabled", lambda _: True)
    monkeypatch.setattr(jev_claims, "ask_jev", _fake_answer)
    monkeypatch.setenv("AICHECK_JEV_CALIBRATION_APPROVED", "true")
    monkeypatch.setenv("AICHECK_JEV_CLAIM_GATE_ENABLED", "true")
    monkeypatch.setenv("AICHECK_JEV_CLAIM_REJECT_CONFIDENCE", "0.95")
    result = jev_claims.verify_finding_claims(state, run, [], drafts)
    assert result["rejectionGateApplied"] is True
    assert "900A" not in drafts[0]["description"]
    assert drafts[0]["groundingStatus"] == "insufficient_evidence"
    assert drafts[0]["unsupportedClaims"] == ["焊接电流为 900A"]


def test_unfaithful_decomposition_is_never_sent_as_a_question(monkeypatch):
    state, run, drafts = _case()
    drafts[0]["claims"] = ["焊接电流为 9000A"]
    monkeypatch.setattr(jev_claims, "jev_stage_enabled", lambda _: True)
    monkeypatch.setattr(jev_claims, "ask_jev", lambda *_: 1 / 0)
    result = jev_claims.verify_finding_claims(state, run, [], drafts)
    assert result["findings"][0]["decompositionStatus"] == "incomplete"
    assert result["findings"][0]["claims"][0]["choice"] == "unfaithful_decomposition"


def test_multi_welder_claim_without_unique_person_stays_manual(monkeypatch):
    state, run, drafts = _case()
    run["nodeId"] = 24
    drafts[0]["claims"] = ["焊接电流为 900A"]
    business = {"r24": {"certificates": [{"welderName": "王一"}, {"welderName": "李二"}]}}
    monkeypatch.setattr(jev_claims, "jev_stage_enabled", lambda _: True)
    monkeypatch.setattr(jev_claims, "ask_jev", lambda *_: 1 / 0)
    result = jev_claims.verify_finding_claims(state, run, [], drafts, business_facts=business)
    assert result["findings"][0]["claims"][0]["choice"] == "ambiguous_person"
    assert result["findings"][0]["decompositionStatus"] == "incomplete"


def test_calibrated_gate_fails_closed_when_jev_unavailable(monkeypatch):
    state, run, drafts = _case()
    monkeypatch.setattr(jev_claims, "jev_stage_enabled", lambda _: True)
    monkeypatch.setattr(jev_claims, "ask_jev", lambda *_: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setenv("AICHECK_JEV_CALIBRATION_APPROVED", "true")
    monkeypatch.setenv("AICHECK_JEV_CLAIM_GATE_ENABLED", "true")
    monkeypatch.setenv("AICHECK_JEV_CLAIM_REJECT_CONFIDENCE", "0.95")
    result = jev_claims.verify_finding_claims(state, run, [], drafts)
    assert result["status"] == "unavailable"
    assert "900A" not in drafts[0]["description"]
    assert drafts[0]["unsupportedClaims"] == ["claim_check_unavailable"]


def test_missing_ocr_text_fails_closed_without_calling_model(monkeypatch):
    state, run, drafts = _case()
    state["ocr_parse_results"] = []
    monkeypatch.setattr(jev_claims, "jev_stage_enabled", lambda _: True)
    monkeypatch.setattr(jev_claims, "ask_jev", lambda *_: 1 / 0)
    monkeypatch.setenv("AICHECK_JEV_CALIBRATION_APPROVED", "true")
    monkeypatch.setenv("AICHECK_JEV_CLAIM_GATE_ENABLED", "true")
    monkeypatch.setenv("AICHECK_JEV_CLAIM_REJECT_CONFIDENCE", "0.95")
    result = jev_claims.verify_finding_claims(state, run, [], drafts)
    assert result["status"] == "missing_document_text"
    assert drafts[0]["groundingStatus"] == "insufficient_evidence"
    assert "900A" not in drafts[0]["description"]
