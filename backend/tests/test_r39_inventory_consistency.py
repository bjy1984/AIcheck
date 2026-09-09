from copy import deepcopy

import pytest
from test_r39_facts import evaluate
from test_r39_reference import arguments as reference_arguments
from test_r39_tools import arguments as application_arguments

from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool
from libs.review_tools.r39_inventory_consistency import INVENTORIES

TOOL = "evaluate_r39_inventory_consistency"


def body():
    reference = reference_arguments()["scope"]
    application = application_arguments()["scope"]
    documents = [{"projectId": "P1", "organizationId": "ORG1", "documentId": reference[prefix + "DocumentId"],
                  "documentVersionId": reference[prefix + "DocumentVersionId"], "documentKind": prefix, "method": "UT"}
                 for prefix in ("instruction", "procedure")]
    approvals = [{**document, "approvalCycleId": "CYCLE1", "procedureId": "QMS1", "procedureVersion": "QMSV1"} for document in documents]
    refs = [{"documentVersionId": "QMSV1", "pageNo": 2, "quotedText": "Synthetic declared inventory"}]
    value = {"projectId": "P1"}
    for key, members in (("referenceInventory", [reference]), ("documentInventory", documents),
                         ("approvalInventory", approvals), ("applicationInventory", [application])):
        value[key] = {"projectId": "P1", "complete": True, "evidenceRefs": deepcopy(refs),
                      "members": [{**member, "evidenceRefs": deepcopy(refs)} for member in members]}
    value["applicationDocumentLinks"] = [{**application, "instructionDocumentId": "DOC1", "instructionDocumentVersionId": "DV1", "evidenceRefs": refs}]
    return value


def test_consistency_is_not_whole_rule_acceptance():
    value = body()
    before = deepcopy(value)
    output = dispatch_runtime_tool({}, TOOL, value)
    assert output["result"] == "passed"
    assert output["facts"]["realWorldCompleteness"] == "not_evaluated"
    assert output["facts"]["wholeRuleAcceptance"] == "not_evaluated"
    assert value == before


def test_same_instruction_revision_cannot_map_to_different_files_across_events():
    value = body()
    extra = deepcopy(value["applicationInventory"]["members"][0])
    extra["eventId"] = "EVENT2"
    value["applicationInventory"]["members"].append(extra)
    link = deepcopy(value["applicationDocumentLinks"][0])
    link.update(eventId="EVENT2", instructionDocumentVersionId="OTHER")
    value["applicationDocumentLinks"].append(link)
    output = dispatch_runtime_tool({}, TOOL, value)
    assert output["result"] == "evidence_insufficient"
    assert any(issue["code"] == "r39_instruction_revision_maps_to_multiple_documents" for issue in output["facts"]["issues"])


def test_generic_profile_cannot_establish_inventory_consistency():
    assert dispatch_runtime_tool({}, TOOL, {"profile": "test", "ruleChecks": [{"operator": "present", "actual": True}]})["result"] == "evidence_insufficient"


@pytest.mark.parametrize("name", INVENTORIES)
@pytest.mark.parametrize("case", ["missing", "incomplete", "duplicate", "unscoped", "no_refs"])
def test_invalid_inventory_blocks_consistency(name, case):
    value = body()
    if case == "missing": value.pop(name)
    elif case == "incomplete": value[name]["complete"] = False
    elif case == "duplicate": value[name]["members"] *= 2
    elif case == "unscoped": value[name]["members"][0]["projectId"] = "OTHER"
    else: value[name]["members"][0]["evidenceRefs"] = []
    assert dispatch_runtime_tool({}, TOOL, value)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("case,code", [
    ("missing_approval", "r39_document_missing_from_inventory"),
    ("wrong_approval_revision", "r39_document_missing_content_inventory"),
    ("wrong_reference_revision", "r39_document_missing_content_inventory"),
    ("missing_content", "r39_document_missing_content_inventory"),
    ("missing_links", "r39_application_document_links_missing"),
    ("wrong_link_revision", "r39_application_document_missing_content"),
    ("unknown_event", "r39_application_link_not_in_inventory"),
    ("duplicate_link", "r39_application_document_link_duplicate"),
    ("unmapped_application", "r39_application_document_link_missing"),
])
def test_cross_inventory_gaps_are_explained_without_business_failure(case, code):
    value = body()
    if case == "missing_approval": value["approvalInventory"]["members"].pop()
    elif case == "wrong_approval_revision": value["approvalInventory"]["members"][0]["documentVersionId"] = "OLD"
    elif case == "wrong_reference_revision": value["referenceInventory"]["members"][0]["instructionDocumentVersionId"] = "OLD"
    elif case == "missing_content": value["documentInventory"]["members"].pop()
    elif case == "missing_links": value["applicationDocumentLinks"] = []
    elif case == "wrong_link_revision": value["applicationDocumentLinks"][0]["instructionDocumentVersionId"] = "OLD"
    elif case == "unknown_event": value["applicationDocumentLinks"][0]["eventId"] = "OTHER"
    elif case == "duplicate_link": value["applicationDocumentLinks"] *= 2
    else:
        extra = deepcopy(value["applicationInventory"]["members"][0])
        extra["eventId"] = "OTHER"
        value["applicationInventory"]["members"].append(extra)
    output = dispatch_runtime_tool({}, TOOL, value)
    assert output["result"] == "evidence_insufficient"
    assert any(issue["code"] == code for issue in output["facts"]["issues"])


def fixture():
    value = body()
    state = {"documents": [{"id": doc, "tenantId": "T1", "projectId": "P1"} for doc in ("DOC1", "PROC1", "QMS1")],
             "versions": [{"id": version, "tenantId": "T1", "documentId": doc} for doc, version in (("DOC1", "DV1"), ("PROC1", "PV1"), ("QMS1", "QMSV1"))],
             "ocr_parse_results": [{"documentVersionId": "QMSV1", "tenantId": "T1", "tables": []}]}
    schemas = {"referenceInventory": ("ndt_reference_inventory", "ndt_reference_members"),
               "documentInventory": ("ndt_content_document_inventory", "ndt_content_document_members"),
               "approvalInventory": ("ndt_approval_cycle_inventory", "ndt_approval_cycle_members"),
               "applicationInventory": ("ndt_application_inventory", "ndt_application_members")}

    def table(schema, records):
        rows = deepcopy(records)
        for row in rows:
            if "documentVersionId" in row: row["reviewedDocumentVersionId"] = row.pop("documentVersionId")
        return {"tableId": schema, "businessSchema": schema, "pageNo": 2, "structureConfidence": .95,
                "contentMarkdown": "Synthetic inventory sources", "normalizedRows": rows}

    for key, (header, member) in schemas.items():
        state["ocr_parse_results"][0]["tables"].extend([table(header, [{"projectId": "P1", "complete": True}]), table(member, value[key]["members"])])
    state["ocr_parse_results"][0]["tables"].append(table("ndt_application_document_links", value["applicationDocumentLinks"]))
    review = {"projectId": "P1", "tenantId": "T1", "nodeId": 39, "inputDocumentVersionIds": ["DV1", "PV1", "QMSV1"]}
    return state, review


@pytest.mark.parametrize("case", ["pass", "wrong_revision", "low_confidence", "missing_inventory", "untrusted_inventory"])
def test_frozen_source_and_real_node_never_equate_consistency_with_review_completion(case):
    state, review = fixture()
    tables = state["ocr_parse_results"][0]["tables"]
    if case == "wrong_revision": tables[-1]["normalizedRows"][0]["instructionDocumentVersionId"] = "OLD"
    elif case == "low_confidence": tables[-1]["structureConfidence"] = .1
    elif case == "missing_inventory": tables.pop(0)
    elif case == "untrusted_inventory": tables[0]["structureConfidence"] = .1
    before = deepcopy(state)
    _, output = evaluate(state, review, TOOL)
    assert output["result"] == ("passed" if case == "pass" else "evidence_insufficient"), output
    assert state == before
    from test_r39_node_plan import execute

    node = execute(state, review)
    tool = next(tool for item in node["atomicResults"] for tool in item["toolResults"] if tool["toolName"] == TOOL)
    assert tool["result"] == output["result"]
    assert node["result"] == "evidence_insufficient"
