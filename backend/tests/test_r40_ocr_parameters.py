from copy import deepcopy

import pytest
from test_r40_ocr_records import raw_fixture
from test_r40_parameters import evaluate


def inputs(value="20%"):
    state, run = raw_fixture()
    tables = state["ocr_parse_results"][0]["tables"]
    member = tables[1]["normalizedRows"][0]
    member.update(requiredParameters=["detection_ratio"], parameterRequirementsComplete=True)
    tables.append({"tableId": "REQ", "businessSchema": "ndt_parameter_requirements", "pageNo": 1,
        "structureConfidence": .95, "contentMarkdown": "检测比例至少10%（合成要求）", "normalizedRows": [{
            "projectId": "P", "objectId": "W1", "method": "RT", "eventId": "E1", "parameter": "detection_ratio",
            "operator": "gte", "value": 10, "unit": "%"}]})
    record = state["ocr_parse_results"][1]
    record["fragments"].append({"text": "检测比例：" + value, "pageNo": 6, "bbox": [1, 2, 30, 40], "confidence": .95})
    record["fields"].append({"fieldCode": "detection_ratio", "fieldValue": value, "pageNo": 6, "bbox": [1, 2, 30, 40], "confidence": .95})
    return state, run


@pytest.mark.parametrize("raw,expected", [("20%", "passed"), ("10％", "passed"), ("9.9%", "failed"),
    ("0.2", "evidence_insufficient"), ("110%", "evidence_insufficient"), ("不少于10%", "evidence_insufficient")])
def test_explicit_record_percentage_reaches_parameter_comparison(raw, expected):
    state, run = inputs(raw)
    before = deepcopy(state)
    output = evaluate(state, run)
    assert output["result"] == expected
    assert state == before
    if expected in {"passed", "failed"}:
        assert any(ref["documentVersionId"] == "REC-V" and ref["pageNo"] == 6 for ref in output["evidenceRefs"])


@pytest.mark.parametrize("case", ["report_only", "low_confidence", "other_record", "outside_pages"])
def test_report_or_unmatched_record_is_not_measurement(case):
    from libs.review_document_scope import freeze_document_scope

    state, run = inputs()
    record = state["ocr_parse_results"][1]
    if case == "report_only":
        report = state["ocr_parse_results"][2]
        report["fields"].append(record["fields"].pop())
        report["fragments"].append(record["fragments"].pop())
    if case == "low_confidence": record["fields"][-1]["confidence"] = .5
    if case == "other_record":
        next(row for row in record["fields"] if row["fieldCode"] == "detection_event_no")["fieldValue"] = "OTHER"
        record["fragments"][2]["text"] = "检测事件编号：OTHER"
    if case == "outside_pages":
        run["inputDocumentPageRanges"] = {"REC-V": {"start": 1, "end": 5}}
        run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    assert evaluate(state, run)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("grade,expected", [("AB", "passed"), ("A", "failed")])
def test_explicit_technical_grade_uses_exact_equality(grade, expected):
    state, run = inputs()
    tables = state["ocr_parse_results"][0]["tables"]
    tables[1]["normalizedRows"][0]["requiredParameters"] = ["technical_grade"]
    tables[-1]["normalizedRows"][0].update(parameter="technical_grade", value="AB", unit="", operator="eq")
    record = state["ocr_parse_results"][1]
    record["fields"][-1].update(fieldCode="technical_grade", fieldValue=grade)
    record["fragments"][-1]["text"] = "技术等级：" + grade
    assert evaluate(state, run)["result"] == expected


def test_existing_parameter_table_is_not_replaced_by_raw_matching_value():
    state, run = inputs()
    tables = state["ocr_parse_results"][0]["tables"]
    table = deepcopy(tables[-1])
    table.update(tableId="VALUE", businessSchema="ndt_parameter_values")
    table["normalizedRows"][0].update(value=9)
    tables.append(table)
    assert evaluate(state, run)["result"] == "failed"
