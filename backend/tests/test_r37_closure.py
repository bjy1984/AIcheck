from copy import deepcopy

import pytest
from test_r37_progressive import arguments as progressive_arguments
from test_r37_progressive import sourced
from test_r37_reinspection import arguments as reinspection_arguments

from libs.review_tools.business_tools import dispatch_business_tool


def arguments():
    progress, repair = progressive_arguments(), reinspection_arguments()
    event = {**progress["event"], "inventoryId": "PG1"}
    case = {**repair["case"], "eventId": "E1", "objectId": "W0"}
    original = {**repair["originalInspection"], "objectId": "W0", "requirements": [{key: event[key] for key in ("method", "scope", "acceptanceCriteriaId")}]}
    disposition = {**repair["disposition"], "objectId": "W0", "completedAt": "2026-09-09T13:00:00+08:00"}
    report = {**repair["reinspections"][0], "objectId": "W0", "inspectedAt": "2026-09-09T14:00:00+08:00", **original["requirements"][0]}
    return {"projectId": "P1", "organizationId": "ORG1", "progressiveInventory": sourced(inventoryId="PG1", complete=True, eventCount=1),
            "progressiveEvents": [event], "inspectionBatches": [progress["batch"]], "inspectionBatchMembers": progress["batch"]["members"],
            "progressiveReports": [{**row, "stage": "first", "inventoryId": "PG1"} for row in progress["firstReports"]],
            "caseInventory": sourced(inventoryId="INV1", complete=True, caseCount=1, cases=[case]),
            "originalInspections": [original], "dispositions": [disposition], "reinspections": [report],
            "closureLinks": [sourced(eventId="E1", objectId="W0", caseId=case["caseId"], repairRound=1, caseInventoryId="INV1", progressiveInventoryId="PG1")]}


def run(body):
    return dispatch_business_tool("evaluate_r37_defect_closure", body)


def test_complete_join_recomputes_both_paths_and_preserves_records():
    body = arguments()
    before = deepcopy(body)
    output = run(body)
    assert output["result"] == "passed", output
    assert output["facts"]["closureChecks"][0]["objectId"] == "W0"
    assert output["facts"]["batchAcceptance"] == "not_evaluated"
    assert body == before and output["evidenceRefs"]


@pytest.mark.parametrize("case", ["missing_link", "duplicate_link", "old_inventory", "other_event", "missing_case", "different_criteria", "repair_before_defect", "fake_pass", "not_applicable_bypass"])
def test_incomplete_or_misaligned_closure_cannot_pass(case):
    body = arguments()
    if case == "missing_link":
        body["closureLinks"] = []
    elif case == "duplicate_link":
        body["closureLinks"] *= 2
    elif case == "old_inventory":
        body["closureLinks"][0]["caseInventoryId"] = "OLD"
    elif case == "other_event":
        body["caseInventory"]["cases"][0]["eventId"] = "OTHER"
    elif case == "missing_case":
        body["caseInventory"].update(cases=[], caseCount=0)
        body["dispositions"] = body["reinspections"] = []
    elif case == "different_criteria":
        body["originalInspections"][0]["requirements"][0]["acceptanceCriteriaId"] = "WEAKER"
        body["reinspections"][0]["acceptanceCriteriaId"] = "WEAKER"
    elif case == "repair_before_defect":
        body["dispositions"][0]["completedAt"] = "2026-09-09T11:00:00+08:00"
    else:
        body["reinspections"] = []
        body["progressionResult"] = body["reinspectionResult"] = {"result": "passed"}
        if case == "not_applicable_bypass":
            body["applicability"] = {"required": False, "evidenceRefs": body["caseInventory"]["evidenceRefs"]}
    assert run(body)["result"] == "evidence_insufficient"


def test_later_qualified_round_closes_without_rewriting_earlier_failure():
    body = arguments()
    body["reinspections"][0]["status"] = "unqualified"
    assert run(body)["result"] == "failed"
    old_case = body["caseInventory"]["cases"][0]
    body["caseInventory"]["cases"].append({**old_case, "repairRound": 2})
    body["caseInventory"]["caseCount"] = 2
    body["dispositions"].append({**body["dispositions"][0], "repairRound": 2, "completedAt": "2026-09-09T15:00:00+08:00"})
    body["reinspections"].append({**body["reinspections"][0], "repairRound": 2, "status": "qualified", "inspectedAt": "2026-09-09T16:00:00+08:00"})
    assert run(body)["result"] == "evidence_insufficient"  # Link still names round 1.
    body["closureLinks"][0]["repairRound"] = 2
    output = run(body)
    assert output["result"] == "passed"
    assert output["facts"]["reinspection"]["facts"]["caseResults"][0]["result"] == "failed"
    body["reinspections"][0]["inspectedAt"] = "2026-09-09T17:00:00+08:00"
    assert run(body)["result"] == "evidence_insufficient"  # Round number alone cannot override a later failure.
    body["dispositions"][1]["completedAt"] = "2026-09-09T18:00:00+08:00"
    body["reinspections"][1]["inspectedAt"] = "2026-09-09T19:00:00+08:00"
    assert run(body)["result"] == "passed"


def test_complete_empty_inventories_are_not_applicable():
    body = arguments()
    body["progressiveInventory"]["eventCount"] = 0
    body["progressiveEvents"] = body["progressiveReports"] = []
    body["caseInventory"].update(cases=[], caseCount=0)
    body["dispositions"] = body["reinspections"] = body["closureLinks"] = []
    assert run(body)["result"] == "not_applicable"
