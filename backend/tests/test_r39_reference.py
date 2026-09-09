from copy import deepcopy

import pytest
from test_r39_content_facts import fixture as existing_fixture
from test_r39_facts import evaluate
from test_r39_node_plan import execute

from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool


def arguments():
    scope = {"projectId": "P1", "organizationId": "ORG1", "method": "UT",
             "instructionDocumentId": "DOC1", "instructionDocumentVersionId": "DV1",
             "procedureDocumentId": "PROC1", "procedureDocumentVersionId": "PV1"}
    def record(version, **values):
        return {**scope, **values, "evidenceRefs": [{"documentVersionId": version, "pageNo": 2, "quotedText": "Synthetic reference source"}]}
    return {"projectId": "P1", "scope": scope, "basis": record("QMSV1", applicable=True),
            "instructionReference": record("DV1", referencedProcedureNumber="UT-01", referencedProcedureVersion="B"),
            "procedureIdentity": record("PV1", procedureNumber="UT-01", procedureVersion="B")}


def run(body):
    return dispatch_runtime_tool({}, "evaluate_r39_procedure_reference", body)


def test_four_states_and_exact_revision_no_implicit_normalization():
    body = arguments()
    before = deepcopy(body)
    assert run(body)["result"] == "passed"
    assert body == before
    body["procedureIdentity"]["procedureVersion"] = "A"
    assert run(body)["result"] == "failed"
    body["procedureIdentity"].pop("procedureVersion")
    assert run(body)["result"] == "evidence_insufficient"
    body["basis"]["applicable"] = False
    assert run(body)["result"] == "not_applicable"


@pytest.mark.parametrize("case", ["wrong_source", "other_project", "missing_quote", "same_document", "missing_basis", "scope_conflict", "numeric_revision"])
def test_unknown_or_wrong_identity_cannot_pass(case):
    body = arguments()
    if case == "wrong_source":
        body["instructionReference"]["evidenceRefs"][0]["documentVersionId"] = "PV1"
    elif case == "other_project":
        body["projectId"] = "OTHER"
    elif case == "missing_quote":
        body["procedureIdentity"]["evidenceRefs"][0]["quotedText"] = ""
    elif case == "same_document":
        body["scope"]["procedureDocumentId"] = "DOC1"
    elif case == "missing_basis":
        body.pop("basis")
    elif case == "scope_conflict":
        body["basis"]["applicable"] = False
        body["procedureIdentity"]["organizationId"] = "OTHER"
    else:
        body["procedureIdentity"]["procedureVersion"] = 1
    assert run(body)["result"] == "evidence_insufficient"


def fixture():
    state, review = existing_fixture()
    body = arguments()
    state["documents"].append({"id": "PROC1", "projectId": "P1", "tenantId": "T1"})
    state["versions"].append({"id": "PV1", "documentId": "PROC1", "tenantId": "T1"})
    review["inputDocumentVersionIds"].append("PV1")
    state["ocr_parse_results"].append({"documentVersionId": "PV1", "tenantId": "T1", "tables": []})
    def table(schema, record):
        return {"tableId": schema, "businessSchema": schema, "pageNo": 2, "structureConfidence": .95,
                "contentMarkdown": "Synthetic reference source", "normalizedRows": [deepcopy(record)]}
    state["ocr_parse_results"][0]["tables"].append(table("ndt_reference_basis", body["basis"]))
    state["ocr_parse_results"][1]["tables"].extend([
        table("ndt_reference_context", body["scope"]),
        table("ndt_instruction_reference", body["instructionReference"])])
    state["ocr_parse_results"][2]["tables"].append(table("ndt_procedure_identity", body["procedureIdentity"]))
    return state, review


@pytest.mark.parametrize("case,expected", [("ok", "passed"), ("mismatch", "failed"), ("unselected", "evidence_insufficient"),
    ("duplicate", "evidence_insufficient"), ("low_confidence", "evidence_insufficient"), ("wrong_source", "evidence_insufficient"),
    ("other_project", "evidence_insufficient"), ("not_applicable", "not_applicable")])
def test_selected_sources_through_builder_and_runtime(case, expected):
    state, review = fixture()
    procedure_table = state["ocr_parse_results"][2]["tables"][0]
    if case == "mismatch":
        procedure_table["normalizedRows"][0]["procedureVersion"] = "A"
    elif case == "unselected":
        review["inputDocumentVersionIds"].remove("PV1")
    elif case == "duplicate":
        procedure_table["normalizedRows"] *= 2
    elif case == "low_confidence":
        procedure_table["structureConfidence"] = .4
    elif case == "wrong_source":
        state["ocr_parse_results"][1]["tables"].append(procedure_table)
        state["ocr_parse_results"][2]["tables"] = []
    elif case == "other_project":
        state["documents"][-1]["projectId"] = "OTHER"
    elif case == "not_applicable":
        state["ocr_parse_results"][0]["tables"][-1]["normalizedRows"][0]["applicable"] = False
    before = deepcopy(state)
    _, output = evaluate(state, review, "evaluate_r39_procedure_reference")
    assert output["result"] == expected, output
    assert state == before
    assert output["facts"]["wholeRuleAcceptance"] == "not_evaluated"


def test_actual_node_plan_includes_comparison_but_keeps_remaining_release_gate():
    state, review = fixture()
    output = execute(state, review)
    tool = next(item for item in output["atomicResults"][0]["toolResults"] if item["toolName"] == "evaluate_r39_procedure_reference")
    assert tool["result"] == "passed"
    assert output["result"] == "evidence_insufficient"
    state["ocr_parse_results"][2]["tables"][0]["normalizedRows"][0]["procedureVersion"] = "A"
    assert execute(state, review)["result"] == "failed"
