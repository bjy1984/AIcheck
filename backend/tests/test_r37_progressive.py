from copy import deepcopy

import pytest

from libs.review_tools.business_tools import dispatch_business_tool


def sourced(**values):
    return {"projectId": "P1", "organizationId": "ORG1", "evidenceRefs": [{"documentVersionId": "V1", "pageNo": 2}], **values}


def report(obj, **values):
    return sourced(eventId="E1", batchId="B1", objectId=obj, method="UT", scope="whole", acceptanceCriteriaId="UT-V1", phase="initial", inspectedAt="2026-09-09T12:00:00+08:00", status="qualified", defectIds=[], **values)


def arguments():
    return {"projectId": "P1", "organizationId": "ORG1",
            "event": {**report("W0"), "status": "unqualified", "isWeld": True, "inspectionMode": "sampling"},
            "batch": sourced(batchId="B1", complete=True, memberCount=8, members=[sourced(batchId="B1", objectId=f"W{i}", similarityGroupId="G1", welderId="S1") for i in range(8)]),
            "firstReports": [report("W1"), report("W2")], "secondReports": [], "fullReports": []}


def run(body):
    return dispatch_business_tool("evaluate_r37_progressive_inspection", body)


def second_stage(body):
    body["firstReports"][0].update(status="unqualified", defectIds=["D1"])
    body["secondReports"] = [report("W3", parentObjectId="W1", parentDefectId="D1"), report("W4", parentObjectId="W1", parentDefectId="D1")]


def test_first_stage_completion_does_not_accept_unrepaired_batch():
    body = arguments()
    before = deepcopy(body)
    output = run(body)
    assert output["result"] == "passed"
    assert output["facts"]["stage"] == "first_complete"
    assert output["facts"]["batchAcceptance"] == "not_evaluated"
    assert output["facts"]["repairRequiredObjectIds"] == ["W0"]
    assert output["evidenceRefs"] and body == before


def test_second_stage_is_two_per_defect_not_two_for_whole_batch():
    body = arguments()
    second_stage(body)
    assert run(body)["facts"]["stage"] == "second_complete"
    body["firstReports"][0]["defectIds"].append("D2")
    output = run(body)
    assert output["result"] == "evidence_insufficient"
    assert output["facts"]["missingGroups"] == [{"parentObjectId": "W1", "parentDefectId": "D2", "additionalCountRequired": 2}]
    body["secondReports"].extend([report("W5", parentObjectId="W1", parentDefectId="D2"), report("W6", parentObjectId="W1", parentDefectId="D2")])
    assert run(body)["result"] == "passed"


def test_second_stage_failure_escalates_to_full_batch_with_prior_coverage_retained():
    body = arguments()
    second_stage(body)
    body["secondReports"][0].update(status="unqualified", defectIds=["D3"])
    output = run(body)
    assert output["result"] == "evidence_insufficient"
    assert output["facts"]["missingObjectIds"] == ["W5", "W6", "W7"]
    body["fullReports"] = [report(f"W{i}") for i in (5, 6, 7)]
    output = run(body)
    assert output["result"] == "passed" and output["facts"]["stage"] == "full_complete"
    assert output["facts"]["repairRequiredObjectIds"] == ["W0", "W1", "W3"]
    assert output["facts"]["batchAcceptance"] == "not_evaluated"


def test_full_escalation_does_not_wait_for_remaining_second_stage_groups():
    body = arguments()
    second_stage(body)
    body["firstReports"][0]["defectIds"].append("D2")
    body["secondReports"][0].update(status="unqualified", defectIds=["D3"])
    assert run(body)["facts"]["stage"] == "full"


@pytest.mark.parametrize("case", ["missing_first", "wrong_welder", "wrong_kind", "reused", "wrong_scope", "wrong_method", "wrong_batch", "wrong_project", "wrong_phase", "missing_defects", "missing_evidence", "count", "duplicate_member", "unknown_parent"])
def test_incomplete_or_mismatched_progression_cannot_pass(case):
    body = arguments()
    if case == "missing_first":
        body["firstReports"].pop()
    elif case == "wrong_welder":
        body["batch"]["members"][1]["welderId"] = "OTHER"
    elif case == "wrong_kind":
        body["batch"]["members"][1]["similarityGroupId"] = "OTHER"
    elif case == "reused":
        body["firstReports"][1] = deepcopy(body["firstReports"][0])
    elif case == "missing_defects":
        body["firstReports"][0]["status"] = "unqualified"
    elif case == "count":
        body["batch"]["memberCount"] = 7
    elif case == "duplicate_member":
        body["batch"]["members"][1]["objectId"] = "W0"
    elif case == "unknown_parent":
        second_stage(body)
        body["secondReports"][0]["parentDefectId"] = "OTHER"
    else:
        key, value = {"wrong_scope": ("scope", "partial"), "wrong_method": ("method", "RT"), "wrong_batch": ("batchId", "OTHER"), "wrong_project": ("projectId", "OTHER"), "wrong_phase": ("phase", "repair_reinspection"), "missing_evidence": ("evidenceRefs", [])}[case]
        body["firstReports"][0][key] = value
    assert run(body)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("field,value,stage", [("phase", "repair_reinspection", "repair_only"), ("inspectionMode", "full", "not_required"), ("status", "qualified", "not_required")])
def test_non_triggering_events_do_not_force_additional_inspection(field, value, stage):
    body = arguments()
    body["event"][field] = value
    output = run(body)
    assert output["result"] == "not_applicable" and output["facts"]["stage"] == stage
    assert output["facts"]["batchAcceptance"] == "not_evaluated"


def test_second_stage_cannot_predate_its_specific_failed_parent():
    body = arguments()
    second_stage(body)
    body["firstReports"][0]["inspectedAt"] = "2026-09-09T13:00:00+08:00"
    assert run(body)["result"] == "evidence_insufficient"
    for row in body["secondReports"]:
        row["inspectedAt"] = "2026-09-09T05:00:00Z"
    assert run(body)["result"] == "passed"


def test_members_cannot_be_reused_for_different_defects():
    body = arguments()
    second_stage(body)
    body["firstReports"][0]["defectIds"].append("D2")
    body["secondReports"].append({**body["secondReports"][0], "parentDefectId": "D2"})
    assert run(body)["result"] == "evidence_insufficient"
