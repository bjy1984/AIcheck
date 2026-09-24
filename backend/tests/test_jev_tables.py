from __future__ import annotations

from libs.review_orchestrator import jev_tables
from libs.review_orchestrator.r24_r34_facts import _extract_records, build_r25_business_facts


def _source():
    table = {"pageNo": 2, "normalizedRows": [
        {"报告编号": "LS-1", "抗拉强度": "560"},
        {"报告编号": "LS-2", "抗拉强度": "570"},
    ]}
    state = {
        "documents": [{"id": "D", "projectId": "P", "fileName": "焊接工艺评定报告.pdf"}],
        "document_versions": [{"id": "V", "documentId": "D"}],
        "ocr_parse_results": [{"documentVersionId": "V", "fields": [
            {"fieldName": "报告编号", "fieldValue": "PQR-1", "pageNo": 1}],
            "tables": [table]}],
    }
    run = {"projectId": "P", "nodeId": 25, "inputDocumentVersionIds": ["V"]}
    return state, run, table


def test_recorded_mechanical_table_prediction_removes_false_pqr_rows():
    state, run, table = _source()
    assert len(build_r25_business_facts(state, run)["r25"]["pqrItems"]) == 2
    run["jevTableClassifications"] = {"model": jev_tables.MODEL, "tables": {"V": [{
        "tableIndex": 1, "tableHash": jev_tables.table_hash(table),
        "tableType": {"choice": "mech_test", "confidence": 0.99}, "rowRoles": [],
    }]}}
    assert len(build_r25_business_facts(state, run)["r25"]["pqrItems"]) == 1
    # R26 的焊材质量证明可能恰恰需要力学性能数据，不能一刀切清掉。
    assert len(_extract_records(state, state["ocr_parse_results"][0], "R26", "welding_consumable_certificate",
                                classifications=run["jevTableClassifications"])) == 2


def test_stale_or_low_confidence_predictions_fall_back_to_existing_rows():
    state, run, table = _source()
    for digest, confidence in (("stale", 0.99), (jev_tables.table_hash(table), 0.89)):
        run["jevTableClassifications"] = {"model": jev_tables.MODEL, "tables": {"V": [{
            "tableIndex": 1, "tableHash": digest,
            "tableType": {"choice": "mech_test", "confidence": confidence}, "rowRoles": [],
        }]}}
        assert len(build_r25_business_facts(state, run)["r25"]["pqrItems"]) == 2


def test_worker_classifier_uses_full_document_and_recorded_answers(monkeypatch):
    state, run, table = _source()
    seen = []

    def fake_ask(full_state, questions):
        seen.append(full_state)
        return {key: {"type": "choice", "choice": "mech_test" if key == "table_type" else "header",
                      "confidence": 0.98} for key in questions}

    monkeypatch.setattr(jev_tables, "jev_stage_enabled", lambda _: True)
    monkeypatch.setattr(jev_tables, "ask_jev", fake_ask)
    result = jev_tables.classify_review_tables(state, run)
    assert "PQR-1" in seen[0] and "LS-2" in seen[0]
    assert result["tables"]["V"][0]["tableHash"] == jev_tables.table_hash(table)
    assert [row["choice"] for row in result["tables"]["V"][0]["rowRoles"]] == ["header", "header"]


def test_disabled_classifier_does_not_call_network(monkeypatch):
    state, run, _ = _source()
    monkeypatch.setattr(jev_tables, "jev_stage_enabled", lambda _: False)
    monkeypatch.setattr(jev_tables, "ask_jev", lambda *_: 1 / 0)
    assert jev_tables.classify_review_tables(state, run)["status"] == "disabled"


def test_classifier_ignores_stale_table_when_same_version_was_reparsed(monkeypatch):
    state, run, old_table = _source()
    state["ocr_parse_results"][0].update(id="OLD", status="success", createdAt="2026-08-01 10:00:00")
    new_table = {"pageNo": 3, "normalizedRows": [{"工艺编号": "WPS-NEW", "电流": "90A"}]}
    state["ocr_parse_results"].append({
        "id": "NEW", "documentVersionId": "V", "status": "success",
        "createdAt": "2026-08-02 10:00:00", "tables": [new_table],
    })
    seen = []

    def fake_ask(full_state, questions):
        seen.append((full_state, questions))
        return {key: {"type": "choice", "choice": "wps_parameters" if key == "table_type" else "data",
                      "confidence": 0.99} for key in questions}

    monkeypatch.setattr(jev_tables, "jev_stage_enabled", lambda _: True)
    monkeypatch.setattr(jev_tables, "ask_jev", fake_ask)
    result = jev_tables.classify_review_tables(state, run)

    assert len(seen) == 1
    assert "WPS-NEW" in seen[0][0] and "LS-1" not in seen[0][0]
    assert result["tables"]["V"][0]["tableHash"] == jev_tables.table_hash(new_table)
    assert result["tables"]["V"][0]["tableHash"] != jev_tables.table_hash(old_table)


def test_r25_deterministic_facts_use_only_latest_successful_ocr_attempt():
    state, run, _ = _source()
    state["ocr_parse_results"][0].update(id="OLD", status="success", createdAt="2026-08-01 10:00:00")
    state["ocr_parse_results"].append({
        "id": "NEW", "documentVersionId": "V", "status": "success",
        "createdAt": "2026-08-02 10:00:00",
        "fields": [{"fieldName": "报告编号", "fieldValue": "PQR-NEW", "pageNo": 1}],
        "tables": [{"pageNo": 3, "normalizedRows": [{"报告编号": "PQR-NEW", "抗拉强度": "560"}]}],
    })

    facts = build_r25_business_facts(state, run)["r25"]

    assert len(facts["pqrItems"]) == 1
    assert facts["pqrItems"][0]["documentNo"] == "PQR-NEW"


def test_r25_deterministic_facts_do_not_use_stale_success_after_new_ocr_failed():
    state, run, _ = _source()
    state["ocr_parse_results"][0].update(id="OLD", status="success", createdAt="2026-08-01 10:00:00")
    state["ocr_parse_results"].append({
        "id": "FAILED", "documentVersionId": "V", "status": "failed",
        "createdAt": "2026-08-02 10:00:00", "fields": [{"fieldName": "报告编号", "fieldValue": "PQR-STALE"}],
    })

    facts = build_r25_business_facts(state, run)["r25"]

    assert facts["pqrItems"] == []


def test_narrow_fallback_excludes_single_cell_section_and_empty_template():
    data = {"栏目": "正式记录", "电流": "90A", "电压": "20V"}
    parse = {"documentVersionId": "SYN-V1", "tables": [{"normalizedRows": [
        {"栏目": "焊接参数", "电流": "", "电压": ""},
        data,
        {"栏目": "待填写", "电流": "", "电压": ""},
    ]}]}
    assert jev_tables.business_rows(parse, None) == [data]
