from copy import deepcopy

import pytest
from test_ndt_procedure_ocr_profile import source
from test_r40_record_correspondence import evaluate, fixture

from apps.ocr_service.service import apply_profile_postprocessing
from libs.ocr.profiles import profile_for


def raw_fixture():
    state, run = fixture()
    state["ocr_parse_results"][0]["tables"] = state["ocr_parse_results"][0]["tables"][:2]
    for version, kind, label in (("REC-V", "检测记录", "检测记录编号"), ("REP-V", "检测报告", "引用记录编号")):
        state["documents"].append({"id": version, "projectId": "P", "tenantId": "T"})
        state["versions"].append({"id": version, "documentId": version, "tenantId": "T"})
        run["inputDocumentVersionIds"].append(version)
        parse = source(f"文件类型：{kind}", f"{label}：REC1", "检测事件编号：E1", "焊口编号：W1", "检测方法：RT")
        parse.update(id=version, documentVersionId=version, tenantId="T", profileId="ndt_rt_report_v1")
        apply_profile_postprocessing(parse, profile_for("ndt_rt_report_v1"))
        # Simulate the existing OCR field contract for method/weld; preserve exact fragments.
        for code, index, value in (("weld_no", 3, "W1"), ("detection_method", 4, "RT")):
            parse["fields"] = [row for row in parse["fields"] if row["fieldCode"] != code]
            fragment = parse["fragments"][index]
            parse["fields"].append({"fieldCode": code, "fieldValue": value, "pageNo": fragment["pageNo"],
                                    "bbox": fragment["bbox"], "confidence": .94})
        state["ocr_parse_results"].append(parse)
    return state, run


@pytest.mark.parametrize("case,expected", [("matched", "passed"), ("wrong_reference", "failed"),
    ("missing_event", "evidence_insufficient"), ("multiple_objects", "evidence_insufficient"),
    ("other_event", "evidence_insufficient"), ("low_confidence", "evidence_insufficient"),
    ("unlocated_value", "evidence_insufficient"), ("duplicate_report", "evidence_insufficient")])
def test_raw_identity_maps_only_to_explicit_sourced_event(case, expected):
    state, run = raw_fixture()
    report = state["ocr_parse_results"][-1]
    if case == "wrong_reference":
        next(row for row in report["fields"] if row["fieldCode"] == "referenced_record_no")["fieldValue"] = "REC2"
        report["fragments"][1]["text"] = "引用记录编号：REC2"
    if case == "missing_event": report["fields"] = [row for row in report["fields"] if row["fieldCode"] != "detection_event_no"]
    if case in {"multiple_objects", "other_event"}:
        code, index, value = ("weld_no", 3, "W1、W2") if case == "multiple_objects" else ("detection_event_no", 2, "E2")
        next(row for row in report["fields"] if row["fieldCode"] == code)["fieldValue"] = value
        report["fragments"][index]["text"] = value
    if case == "low_confidence": report["fields"][0]["confidence"] = .4
    if case == "unlocated_value": report["fragments"][1]["text"] = "无原文支持"
    if case == "duplicate_report": state["ocr_parse_results"].append(deepcopy(report))
    before = deepcopy(state)
    output = evaluate(state, run)
    assert output["result"] == expected
    assert state == before
    assert output["facts"]["wholeRuleAcceptance"] == "not_evaluated"
    if expected in {"passed", "failed"}:
        assert {ref["documentVersionId"] for ref in output["evidenceRefs"]} == {"V", "REC-V", "REP-V"}
        assert any(ref["id"].startswith("R40-FIELD-") for ref in output["evidenceRefs"])


def test_partial_business_table_is_not_bypassed_by_matching_raw_fields():
    state, run = raw_fixture()
    original_state, _ = fixture()
    state["ocr_parse_results"][0]["tables"].append(original_state["ocr_parse_results"][0]["tables"][2])
    assert evaluate(state, run)["result"] == "evidence_insufficient"


def test_page_selection_cannot_read_event_identity_outside_frozen_range():
    from libs.review_document_scope import freeze_document_scope

    state, run = raw_fixture()
    run["inputDocumentPageRanges"] = {"REP-V": {"start": 1, "end": 2}}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    assert evaluate(state, run)["result"] == "evidence_insufficient"
