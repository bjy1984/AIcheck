from copy import deepcopy

import pytest
from test_r39_facts import evaluate
from test_r39_inventory_consistency import TOOL, body
from test_r39_inventory_consistency import fixture as inventory_fixture

from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool


def zero_application_body():
    value = body()
    value["applicationInventory"].update(members=[], declaredApplicationCount=0)
    value["applicationDocumentLinks"] = []
    value["unappliedInstructions"] = [{**deepcopy(value["documentInventory"]["members"][0]), "reason": "not_yet_applied", "applied": False}]
    return value


def test_sourced_zero_applications_is_not_an_omitted_inventory():
    value = zero_application_body()
    before = deepcopy(value)
    assert dispatch_runtime_tool({}, TOOL, value)["result"] == "passed"
    output = dispatch_runtime_tool({}, "evaluate_r39_first_use_validation", {
        "projectId": "P1", "inventory": value["applicationInventory"], "applications": []})
    assert output["result"] == "not_applicable"
    assert output["facts"]["coverage"]["requiredCount"] == 0
    assert output["facts"]["coverage"]["complete"]
    assert value == before


@pytest.mark.parametrize("count", [None, False, "0", 0.0, -1, 1])
def test_zero_count_requires_explicit_integer_not_coercion(count):
    value = zero_application_body()
    if count is None: value["applicationInventory"].pop("declaredApplicationCount")
    else: value["applicationInventory"]["declaredApplicationCount"] = count
    assert dispatch_runtime_tool({}, TOOL, value)["result"] == "evidence_insufficient"
    assert dispatch_runtime_tool({}, "evaluate_r39_first_use_validation", {
        "projectId": "P1", "inventory": value["applicationInventory"], "applications": []})["result"] == "evidence_insufficient"


@pytest.mark.parametrize("case", ["missing", "no_refs", "wrong_reason", "wrong_version", "applied", "duplicate", "malformed"])
def test_unapplied_declaration_is_required_and_scoped(case):
    value = zero_application_body()
    declaration = value["unappliedInstructions"][0]
    if case == "missing": value.pop("unappliedInstructions")
    elif case == "no_refs": declaration["evidenceRefs"] = []
    elif case == "wrong_reason": declaration["reason"] = "record_not_found"
    elif case == "wrong_version": declaration["documentVersionId"] = "OLD"
    elif case == "applied": declaration["applied"] = True
    elif case == "duplicate": value["unappliedInstructions"] *= 2
    else: value["unappliedInstructions"] = {}
    assert dispatch_runtime_tool({}, TOOL, value)["result"] == "evidence_insufficient"


def test_unapplied_claim_cannot_hide_a_declared_actual_application():
    value = body()
    value["unappliedInstructions"] = zero_application_body()["unappliedInstructions"]
    output = dispatch_runtime_tool({}, TOOL, value)
    assert output["result"] == "evidence_insufficient"
    assert any(issue["code"] == "r39_unapplied_instruction_declaration_conflicting" for issue in output["facts"]["issues"])


def test_used_and_unapplied_instructions_can_coexist():
    value = body()
    document = deepcopy(value["documentInventory"]["members"][0])
    document.update(documentId="DOC2", documentVersionId="DV2")
    value["documentInventory"]["members"].append(document)
    approval = deepcopy(value["approvalInventory"]["members"][0])
    approval.update(documentId="DOC2", documentVersionId="DV2")
    value["approvalInventory"]["members"].append(approval)
    reference = deepcopy(value["referenceInventory"]["members"][0])
    reference.update(instructionDocumentId="DOC2", instructionDocumentVersionId="DV2")
    value["referenceInventory"]["members"].append(reference)
    value["unappliedInstructions"] = [{**document, "reason": "not_yet_applied", "applied": False}]
    assert dispatch_runtime_tool({}, TOOL, value)["result"] == "passed"


def test_zero_inventory_cannot_hide_supplied_application_records():
    value = zero_application_body()
    assert dispatch_runtime_tool({}, "evaluate_r39_first_use_validation", {
        "projectId": "P1", "inventory": value["applicationInventory"], "applications": [{}]})["result"] == "evidence_insufficient"
    value = body()
    value["applicationInventory"]["declaredApplicationCount"] = 0
    assert dispatch_runtime_tool({}, TOOL, value)["result"] == "evidence_insufficient"


def fixture():
    state, review = inventory_fixture()
    tables = state["ocr_parse_results"][0]["tables"]
    for table in tables:
        if table["businessSchema"] == "ndt_application_inventory":
            table["normalizedRows"][0]["declaredApplicationCount"] = 0
        elif table["businessSchema"] in {"ndt_application_members", "ndt_application_document_links"}:
            table["normalizedRows"] = []
    record = zero_application_body()["unappliedInstructions"][0]
    record["reviewedDocumentVersionId"] = record.pop("documentVersionId")
    tables.append({"tableId": "unapplied", "businessSchema": "ndt_unapplied_instructions", "pageNo": 2,
                   "structureConfidence": .95, "contentMarkdown": "Synthetic declaration: not yet applied", "normalizedRows": [record]})
    return state, review


@pytest.mark.parametrize("case", ["pass", "low_confidence", "no_statement", "wrong_version", "missing_count"])
def test_frozen_source_to_node_distinguishes_no_application_from_missing_evidence(case):
    state, review = fixture()
    tables = state["ocr_parse_results"][0]["tables"]
    if case == "low_confidence": tables[-1]["structureConfidence"] = .1
    elif case == "no_statement": tables.pop()
    elif case == "wrong_version": tables[-1]["normalizedRows"][0]["reviewedDocumentVersionId"] = "OLD"
    elif case == "missing_count":
        next(table for table in tables if table["businessSchema"] == "ndt_application_inventory")["normalizedRows"][0].pop("declaredApplicationCount")
    before = deepcopy(state)
    _, output = evaluate(state, review, TOOL)
    assert output["result"] == ("passed" if case == "pass" else "evidence_insufficient"), output
    assert state == before
    from test_r39_node_plan import execute

    node = execute(state, review)
    assert node["result"] == "evidence_insufficient"
    actual = next(tool for item in node["atomicResults"] for tool in item["toolResults"] if tool["toolName"] == TOOL)
    assert actual["result"] == output["result"]
