from copy import deepcopy

import pytest

from libs.review_tools.business_tools import dispatch_business_tool


def arguments():
    def sourced(**values):
        return {"projectId": "P1", "organizationId": "ORG1", "evidenceRefs": [{"documentVersionId": "V1", "pageNo": 2}], **values}
    case = sourced(inventoryId="INV1", caseId="C1", objectId="W1", repairRound=1, exceedsAcceptance=True, originalInspectionId="I1")
    requirement = {"method": "UT", "scope": "whole_circumference", "acceptanceCriteriaId": "UT-CRITERIA-V1"}
    report = sourced(**{key: case[key] for key in ("inventoryId", "caseId", "objectId", "repairRound")},
                     **requirement, inspectedAt="2026-09-08T10:00:00+08:00", status="qualified")
    return {"projectId": "P1", "organizationId": "ORG1", "case": case,
            "originalInspection": sourced(inspectionId="I1", objectId="W1", requirements=[requirement]),
            "disposition": sourced(**{key: case[key] for key in ("inventoryId", "caseId", "objectId", "repairRound")}, action="repair", completedAt="2026-09-08T09:00:00+08:00"),
            "reinspections": [report]}


def run(body):
    return dispatch_business_tool("evaluate_r37_reinspection", body)


def test_repair_and_replacement_require_the_correct_target_without_mutating_inputs():
    body = arguments()
    before = deepcopy(body)
    assert run(body)["result"] == "passed"
    assert body == before
    body["disposition"].update(action="replace", replacementObjectId="W2")
    assert run(body)["result"] == "evidence_insufficient"
    body["reinspections"][0]["objectId"] = "W2"
    output = run(body)
    assert output["result"] == "passed"
    assert output["standardBasis"]["clauses"] == ["8.1.3", "8.3.3.4"]
    assert output["evidenceRefs"]


@pytest.mark.parametrize("case", ["missing", "duplicate", "wrong_method", "wrong_round", "bool_round", "wrong_inventory", "wrong_project", "wrong_org", "scope", "criteria", "evidence", "naive_time", "unknown_status"])
def test_missing_or_incompatible_reinspection_cannot_pass(case):
    body = arguments()
    report = body["reinspections"][0]
    if case == "missing":
        body["reinspections"] = []
    elif case == "duplicate":
        body["reinspections"].append(deepcopy(report))
    else:
        key, value = {"wrong_method": ("method", "RT"), "wrong_round": ("repairRound", 0), "bool_round": ("repairRound", True),
            "wrong_inventory": ("inventoryId", "OTHER"), "wrong_project": ("projectId", "OTHER"), "wrong_org": ("organizationId", "OTHER"),
            "scope": ("scope", "partial"), "criteria": ("acceptanceCriteriaId", "OTHER"), "evidence": ("evidenceRefs", []),
            "naive_time": ("inspectedAt", "2026-09-08T10:00:00"), "unknown_status": ("status", "pending")}[case]
        report[key] = value
    assert run(body)["result"] == "evidence_insufficient"


def test_unqualified_or_precompletion_reports_fail():
    body = arguments()
    body["reinspections"][0]["status"] = "unqualified"
    assert run(body)["result"] == "failed"
    body["reinspections"][0].update(status="qualified", inspectedAt="2026-09-08T00:59:59Z")
    assert run(body)["result"] == "failed"
    body["reinspections"][0]["inspectedAt"] = "2026-09-08T01:00:00Z"
    assert run(body)["result"] == "passed"


def test_unqualified_under_other_criteria_remains_unresolved():
    body = arguments()
    body["reinspections"][0].update(status="unqualified", acceptanceCriteriaId="OTHER")
    assert run(body)["result"] == "evidence_insufficient"


def test_all_original_methods_must_be_reinspected():
    body = arguments()
    extra = {**body["originalInspection"]["requirements"][0], "method": "RT", "acceptanceCriteriaId": "RT-CRITERIA-V1"}
    body["originalInspection"]["requirements"].append(extra)
    assert run(body)["result"] == "evidence_insufficient"
    body["reinspections"].append({**body["reinspections"][0], **extra})
    assert run(body)["result"] == "passed"


def test_not_applicable_requires_scoped_defect_evidence():
    body = arguments()
    body["case"]["exceedsAcceptance"] = False
    assert run(body)["result"] == "not_applicable"
    body["case"]["evidenceRefs"] = []
    assert run(body)["result"] == "evidence_insufficient"


def test_undated_unqualified_report_does_not_establish_reinspection_failure():
    body = arguments()
    body["reinspections"][0].update(status="unqualified", inspectedAt=None)
    assert run(body)["result"] == "evidence_insufficient"
