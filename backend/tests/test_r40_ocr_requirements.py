from copy import deepcopy

import pytest
from test_ndt_procedure_ocr_profile import source
from test_r40_ocr_parameters import inputs as base_inputs
from test_r40_parameters import evaluate

from apps.ocr_service.service import apply_profile_postprocessing
from libs.ocr.profiles import profile_for


def inputs(requirement="至少10%"):
    state, run = base_inputs()
    tables = state["ocr_parse_results"][0]["tables"]
    tables.pop()  # No normalized requirement table; use actual postprocessed fields.
    tables[1]["normalizedRows"][0]["requirementsVersionId"] = "REQ-V"
    state["documents"].append({"id": "REQ", "tenantId": "T", "projectId": "P"})
    state["versions"].append({"id": "REQ-V", "tenantId": "T", "documentId": "REQ"})
    run["inputDocumentVersionIds"].append("REQ-V")
    parse = source("文件类型：工艺规程", "检测方法：RT", "检测比例要求：" + requirement)
    apply_profile_postprocessing(parse, profile_for("ndt_procedure_v1"))
    parse.update(id="REQ-PARSE", tenantId="T", documentVersionId="REQ-V", profileId="ndt_procedure_v1")
    state["ocr_parse_results"].append(parse)
    return state, run


@pytest.mark.parametrize("requirement,expected", [("至少10%", "passed"), ("≥20%", "passed"), ("至少21%", "failed"),
    ("不超过10%", "failed"), ("等于20%", "passed"), ("20%", "evidence_insufficient"),
    ("按设计要求", "evidence_insufficient"), ("至少0.2", "evidence_insufficient")])
def test_original_requirement_and_record_reach_comparison(requirement, expected):
    state, run = inputs(requirement)
    before = deepcopy(state)
    output = evaluate(state, run)
    assert output["result"] == expected
    assert state == before
    if expected in {"passed", "failed"}:
        assert any(ref["documentVersionId"] == "REQ-V" and ref["pageNo"] == 3 for ref in output["evidenceRefs"])
        assert any(ref["documentVersionId"] == "REC-V" for ref in output["evidenceRefs"])


@pytest.mark.parametrize("case", ["not_selected", "no_assignment", "wrong_method", "duplicate_parse", "low_confidence", "page_excluded"])
def test_unassigned_or_ambiguous_requirement_is_not_borrowed(case):
    from libs.review_document_scope import freeze_document_scope

    state, run = inputs()
    if case == "not_selected": run["inputDocumentVersionIds"].remove("REQ-V")
    if case == "no_assignment": state["ocr_parse_results"][0]["tables"][1]["normalizedRows"][0].pop("requirementsVersionId")
    if case == "wrong_method":
        parse = state["ocr_parse_results"][-1]
        next(row for row in parse["fields"] if row["fieldCode"] == "method")["fieldValue"] = "UT"
        parse["fragments"][1]["text"] = "检测方法：UT"
    if case == "duplicate_parse": state["ocr_parse_results"].append(deepcopy(state["ocr_parse_results"][-1]))
    if case == "low_confidence": state["ocr_parse_results"][-1]["fields"][-1]["confidence"] = .3
    if case == "page_excluded":
        run["inputDocumentPageRanges"] = {"REQ-V": {"start": 1, "end": 2}}
        run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    assert evaluate(state, run)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("grade,expected", [("等于AB", "passed"), ("等于A", "failed"), ("AB", "evidence_insufficient")])
def test_grade_requirement_needs_an_explicit_equality_operator(grade, expected):
    state, run = inputs()
    state["ocr_parse_results"][0]["tables"][1]["normalizedRows"][0]["requiredParameters"] = ["technical_grade"]
    record = state["ocr_parse_results"][1]
    record["fields"][-1].update(fieldCode="technical_grade", fieldValue="AB")
    record["fragments"][-1]["text"] = "技术等级：AB"
    parse = source("文件类型：工艺规程", "检测方法：RT", "技术等级要求：" + grade)
    apply_profile_postprocessing(parse, profile_for("ndt_procedure_v1"))
    parse.update(id="REQ-PARSE", tenantId="T", documentVersionId="REQ-V", profileId="ndt_procedure_v1")
    state["ocr_parse_results"][-1] = parse
    assert evaluate(state, run)["result"] == expected
