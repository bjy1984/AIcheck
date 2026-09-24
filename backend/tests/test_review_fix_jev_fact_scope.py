"""逐份资料核对事实时不得改写冻结的资料范围（页范围同样生效）。"""
from __future__ import annotations

from libs.jev_evaluation_input import approved_ocr_text
from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator import jev_fact_check


def _state():
    return {
        "documents": [{"id": "D1", "projectId": "P", "fileName": "安装许可证.pdf"},
                      {"id": "D2", "projectId": "P", "fileName": "焊工证.pdf"},
                      {"id": "D3", "projectId": "P", "fileName": "未选资料.pdf"}],
        "versions": [{"id": "V1", "documentId": "D1"}, {"id": "V2", "documentId": "D2"},
                     {"id": "V3", "documentId": "D3"}],
        "ocr_parse_results": [
            {"id": "O1", "documentVersionId": "V1", "status": "success",
             "fragments": [{"pageNo": 1, "text": "封面 OUTSIDE_PAGE"},
                           {"pageNo": 2, "text": "特种设备生产许可证 有效期：2024年9月7日至2028年9月6日"}]},
            {"id": "O2", "documentVersionId": "V2", "status": "success",
             "fragments": [{"pageNo": 1, "text": "焊工证 姓名：张三 OTHER_DOCUMENT"}]},
            {"id": "O3", "documentVersionId": "V3", "status": "success",
             "fragments": [{"pageNo": 1, "text": "NOT_FROZEN"}]},
        ],
    }


def _frozen_run(state):
    run = {"projectId": "P", "nodeId": 2, "reviewMode": "formal", "inputDocumentVersionIds": ["V1", "V2"],
           "inputDocumentPageRanges": {"V1": {"start": 2, "end": 2}}}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    return run


def _verification(version="V1"):
    return {"atomicCheckId": "AC-R02-02", "certificateType": "installation_license", "certificates": [{
        "label": "TS3841999-2028", "certificateType": "installation_license", "holder": "示例管道安装有限公司",
        "certificateNo": "TS3841999-2028", "validFrom": "2024-07-31", "validUntil": "2024-09-07",
        "evidenceRefs": [{"documentVersionId": version, "pageNo": 2}]}]}


def test_subset_reads_only_that_version_within_the_frozen_pages():
    state = _state()
    run = _frozen_run(state)
    status, text = approved_ocr_text(state, run, versions=["V1"])
    assert status == "ready"
    assert "2024年9月7日" in text
    assert "OUTSIDE_PAGE" not in text and "OTHER_DOCUMENT" not in text


def test_subset_cannot_reach_outside_the_frozen_scope():
    state = _state()
    run = _frozen_run(state)
    assert approved_ocr_text(state, run, versions=["V3"]) == ("invalid_scope", "")
    assert approved_ocr_text(state, run, versions=["V1", "V1"]) == ("invalid_scope", "")
    assert approved_ocr_text(state, run, versions=[]) == ("invalid_scope", "")
    # 冻结后改写版本清单仍按原来的方式拒绝。
    assert approved_ocr_text(state, {**run, "inputDocumentVersionIds": ["V1"]}) == ("invalid_scope", "")


def test_per_document_fact_check_keeps_the_frozen_run(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS", "P")
    monkeypatch.setattr(jev_fact_check, "jev_stage_enabled", lambda stage: stage == "FACT_CHECK")
    sent = []

    def answer(text, questions, **_kwargs):
        sent.append(text)
        return {key: {"type": "choice", "choice": "yes", "confidence": 0.97} for key in questions}

    monkeypatch.setattr(jev_fact_check, "ask_jev", answer)
    state = _state()
    run = _frozen_run(state)
    result = jev_fact_check.check_certificate_facts(state, run, _verification())
    assert result["status"] == "completed"
    assert {row["status"] for row in result["facts"]} == {"completed"}
    assert len(sent) == 1
    assert "2024年9月7日" in sent[0]
    assert "OUTSIDE_PAGE" not in sent[0] and "OTHER_DOCUMENT" not in sent[0]


def test_fact_from_a_version_outside_the_frozen_scope_is_not_sent(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS", "P")
    monkeypatch.setattr(jev_fact_check, "jev_stage_enabled", lambda stage: stage == "FACT_CHECK")
    monkeypatch.setattr(jev_fact_check, "ask_jev", lambda *_a, **_k: 1 / 0)
    state = _state()
    result = jev_fact_check.check_certificate_facts(state, _frozen_run(state), _verification("V3"))
    assert result["status"] == "invalid_scope"


def test_page_window_and_locate_use_the_frozen_run():
    state = _state()
    run = _frozen_run(state)
    located = jev_fact_check.locate_value(state, run, ["V1"], "validUntil", "2024-09-07")
    assert located and located["documentVersionId"] == "V1" and located["pageNo"] == 2
    assert jev_fact_check.locate_value(state, run, ["V1"], "certificateNo", "OUTSIDE_PAGE") is None


def test_long_document_page_windows_keep_the_frozen_run(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS", "P")
    monkeypatch.setattr(jev_fact_check, "jev_stage_enabled", lambda stage: stage == "FACT_CHECK")
    monkeypatch.setattr(jev_fact_check, "approved_ocr_text", lambda *_a, **_k: ("overlong_document", ""))
    sent = []

    def answer(text, questions, **_kwargs):
        sent.append(text)
        return {key: {"type": "choice", "choice": "yes", "confidence": 0.97} for key in questions}

    monkeypatch.setattr(jev_fact_check, "ask_jev", answer)
    state = _state()
    result = jev_fact_check.check_certificate_facts(state, _frozen_run(state), _verification())
    assert result["status"] == "completed"
    assert sent and all("OUTSIDE_PAGE" not in text and "OTHER_DOCUMENT" not in text for text in sent)
    assert any("2024年9月7日" in text for text in sent)
