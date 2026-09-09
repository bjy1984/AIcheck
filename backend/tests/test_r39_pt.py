from copy import deepcopy

import pytest
from test_r39_facts import evaluate
from test_r39_reference import fixture as existing_fixture

from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool
from libs.review_tools.r39_pt import SCOPE_FIELDS

TOOL = "evaluate_r39_pt_emulsifier_application"


def test_generic_profile_cannot_manufacture_method_compliance():
    output = dispatch_runtime_tool({}, TOOL, {"profile": "test", "ruleChecks": [{"operator": "present", "actual": True}]})
    assert output["result"] == "evidence_insufficient"


def arguments():
    scope = dict(zip(SCOPE_FIELDS, ("P1", "ORG1", "DOC1", "DV1", "instruction", "PT", "W1", "EV1"), strict=True))
    def record(version, **values):
        return {**scope, **values, "evidenceRefs": [{"documentVersionId": version, "pageNo": 2, "quotedText": "Synthetic PT source"}]}
    return {"projectId": "P1", "scope": scope,
            "basis": record("QMSV1", standard="NB/T 47013.5-2015", clause="6.3.2", applicable=True),
            "process": record("DV1", removalMethod="D", emulsifierApplication="spray")}


@pytest.mark.parametrize("removal,application,expected", [
    ("D", "spray", "passed"), ("D", "dip", "passed"), ("D", "pour", "passed"),
    ("B", "dip", "passed"), ("B", "pour", "passed"), ("B", "spray", "failed"),
    ("D", "brush", "failed"), ("B", "brush", "failed"), ("A", "none", "not_applicable"),
    ("C", "none", "not_applicable"), ("A", "brush", "evidence_insufficient"),
    ("B", "none", "evidence_insufficient"), ("D", "none", "evidence_insufficient"),
    (None, "spray", "evidence_insufficient"), ("D", None, "evidence_insufficient"),
    ([], "spray", "evidence_insufficient"), ("D", {}, "evidence_insufficient"),
    ("UNKNOWN", "spray", "evidence_insufficient"), ("D", "unknown", "evidence_insufficient"),
])
def test_application_matrix(removal, application, expected):
    body = arguments()
    body["process"].update(removalMethod=removal, emulsifierApplication=application)
    before = deepcopy(body)
    output = dispatch_runtime_tool({}, TOOL, body)
    assert output["result"] == expected
    assert output["facts"]["wholeRuleAcceptance"] == "not_evaluated"
    assert output["facts"]["evidenceVerified"] is False
    assert body == before


@pytest.mark.parametrize("field", SCOPE_FIELDS)
def test_scope_conflict_never_hides_behind_not_applicable(field):
    body = arguments()
    body["process"].update(removalMethod="A", emulsifierApplication="none")
    body["process"][field] = "OTHER"
    assert dispatch_runtime_tool({}, TOOL, body)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("case", ["no_basis", "wrong_standard", "wrong_clause", "unsupported_method", "no_ref", "wrong_version"])
def test_missing_or_mismatched_basis_and_source(case):
    body = arguments()
    if case == "no_basis": body.pop("basis")
    elif case == "wrong_standard": body["basis"]["standard"] = "NB/T 47013.1-2015"
    elif case == "wrong_clause": body["basis"]["clause"] = "6.2.2"
    elif case == "unsupported_method": body["scope"]["method"] = "UT"
    elif case == "no_ref": body["process"]["evidenceRefs"] = []
    else: body["process"]["evidenceRefs"][0]["documentVersionId"] = "OTHER"
    assert dispatch_runtime_tool({}, TOOL, body)["result"] == "evidence_insufficient"


def fixture():
    state, review = existing_fixture()
    body = arguments()
    for key, schema, index in (("scope", "ndt_pt_context", 1), ("basis", "ndt_pt_basis", 0), ("process", "ndt_pt_process", 1)):
        row = deepcopy(body[key])
        row["reviewedDocumentVersionId"] = row.pop("documentVersionId")
        state["ocr_parse_results"][index]["tables"].append({"tableId": schema, "businessSchema": schema,
            "pageNo": 2, "contentMarkdown": "Synthetic PT source", "structureConfidence": .95, "normalizedRows": [row]})
    return state, review


@pytest.mark.parametrize("case,expected", [("pass", "passed"), ("fail", "failed"), ("na", "not_applicable"),
    ("missing", "evidence_insufficient"), ("duplicate", "evidence_insufficient"), ("low_confidence", "evidence_insufficient"),
    ("other_object", "evidence_insufficient"), ("wrong_document", "evidence_insufficient")])
def test_frozen_source_to_real_execution(case, expected):
    state, review = fixture()
    table = state["ocr_parse_results"][1]["tables"][-1]
    row = table["normalizedRows"][0]
    if case == "fail": row["emulsifierApplication"] = "brush"
    elif case == "na": row.update(removalMethod="A", emulsifierApplication="none")
    elif case == "missing": table["normalizedRows"] = []
    elif case == "duplicate": table["normalizedRows"] *= 2
    elif case == "low_confidence": row["confidence"] = .1
    elif case == "other_object": row["objectId"] = "W2"
    elif case == "wrong_document": row["reviewedDocumentVersionId"] = "PV1"
    before = deepcopy(state)
    _, output = evaluate(state, review, TOOL)
    assert output["result"] == expected, output
    assert state == before
    if case in {"pass", "fail", "na"}:
        from test_r39_node_plan import execute

        node = execute(state, review)
        actual = next(tool for item in node["atomicResults"] for tool in item["toolResults"] if tool["toolName"] == TOOL)
        assert actual["result"] == expected
        assert node["result"] == ("failed" if case == "fail" else "evidence_insufficient")
