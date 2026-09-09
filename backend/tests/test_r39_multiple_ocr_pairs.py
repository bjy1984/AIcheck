from copy import deepcopy

import pytest
from test_r39_facts import evaluate
from test_r39_reference_ocr_fields import fixture as one_pair_fixture

from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool


def fixture():
    state, review = one_pair_fixture()
    for parse in deepcopy(state["ocr_parse_results"]):
        version = parse["documentVersionId"] + "-2"
        parse["documentVersionId"] = version
        for row in parse["fields"]:
            if row["fieldCode"] in {"procedure_no", "referenced_procedure_no"}:
                row["fieldValue"] += "-2"
        for row in parse["fragments"]:
            if "编号：" in row["text"]:
                row["text"] += "-2"
        state["ocr_parse_results"].append(parse)
        state["documents"].append({"id": version, "projectId": "P1", "tenantId": "T1", "materialTypeCode": "ndt_procedure"})
        state["versions"].append({"id": version, "documentId": version, "tenantId": "T1"})
        review["inputDocumentVersionIds"].append(version)
    return state, review


@pytest.mark.parametrize("case", ["pass", "missing_revision", "low_confidence", "duplicate_parse", "ambiguous_target", "no_parse"])
@pytest.mark.parametrize("known_failure", [False, True])
def test_multiple_files_keep_independent_revision_findings(case, known_failure):
    state, review = fixture()
    if known_failure:
        procedure = state["ocr_parse_results"][1]
        next(row for row in procedure["fields"] if row["fieldCode"] == "procedure_revision")["fieldValue"] = "C"
        next(row for row in procedure["fragments"] if row["text"] == "版次：B")["text"] = "版次：C"
    procedure = state["ocr_parse_results"][3]
    revision = next(row for row in procedure["fields"] if row["fieldCode"] == "procedure_revision")
    if case == "missing_revision": procedure["fields"].remove(revision)
    elif case == "low_confidence": revision["confidence"] = .1
    elif case == "duplicate_parse": state["ocr_parse_results"].append(deepcopy(procedure))
    elif case == "ambiguous_target":
        extra = deepcopy(procedure)
        extra["documentVersionId"] = "AMBIGUOUS"
        state["ocr_parse_results"].append(extra)
        state["versions"].append({"id": "AMBIGUOUS", "documentId": "PV1-2", "tenantId": "T1"})
        review["inputDocumentVersionIds"].append("AMBIGUOUS")
    elif case == "no_parse": state["ocr_parse_results"].remove(procedure)
    before = deepcopy(state)
    _, output = evaluate(state, review, "evaluate_r39_procedure_reference")
    assert output["result"] == ("failed" if known_failure else "passed" if case == "pass" else "evidence_insufficient"), output
    coverage = output["facts"]["coverage"]
    assert coverage["comparedPairCount"] == (2 if case == "pass" else 1)
    assert coverage["complete"] is (case == "pass")
    assert output["facts"]["wholeRuleAcceptance"] == "not_evaluated"
    assert state == before
    state["ocr_parse_results"].reverse()
    _, reversed_output = evaluate(state, review, "evaluate_r39_procedure_reference")
    for key in ("result", "facts", "evidenceRefs"):
        assert reversed_output[key] == output[key]
    from test_r39_node_plan import execute

    node = execute(state, review)
    actual = next(tool for item in node["atomicResults"] for tool in item["toolResults"] if tool["toolName"] == "evaluate_r39_procedure_reference")
    assert actual["result"] == output["result"]
    assert node["result"] == ("failed" if known_failure else "evidence_insufficient")


@pytest.mark.parametrize("case", ["duplicate_pair", "outside_selection", "nested", "bad_issues", "bad_selected"])
def test_collection_cannot_hide_invalid_or_duplicate_pair(case):
    state, review = fixture()
    facts, _ = evaluate(state, review, "evaluate_r39_procedure_reference")
    value = deepcopy(facts["r39"]["procedureReference"])
    if case == "duplicate_pair": value["fieldPairs"].append(deepcopy(value["fieldPairs"][0]))
    elif case == "outside_selection": value["selectedDocumentVersionIds"].pop()
    elif case == "nested": value["fieldPairs"][0]["fieldPairs"] = []
    elif case == "bad_issues": value["selectionIssues"] = "invalid"
    else: value["selectedDocumentVersionIds"] = [None]
    assert dispatch_runtime_tool({}, "evaluate_r39_procedure_reference", value)["result"] == "evidence_insufficient"


def test_incomplete_same_number_procedure_is_not_silently_removed_from_matching():
    state, review = fixture()
    extra = deepcopy(state["ocr_parse_results"][3])
    extra["documentVersionId"] = "INCOMPLETE"
    extra["fields"] = [row for row in extra["fields"] if row["fieldCode"] != "procedure_revision"]
    state["ocr_parse_results"].append(extra)
    state["versions"].append({"id": "INCOMPLETE", "documentId": "PV1-2", "tenantId": "T1"})
    review["inputDocumentVersionIds"].append("INCOMPLETE")
    _, output = evaluate(state, review, "evaluate_r39_procedure_reference")
    assert output["result"] == "evidence_insufficient"
    assert output["facts"]["coverage"]["comparedPairCount"] == 1
    assert any(issue["code"] == "r39_ocr_reference_target_missing_or_ambiguous" for issue in output["facts"]["selectionIssues"])
