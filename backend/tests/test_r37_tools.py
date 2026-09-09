from copy import deepcopy

import pytest

from libs.review_tools.business_tools import dispatch_business_tool


def arguments():
    def sourced(**values):
        return {"projectId": "P1", "organizationId": "ORG1", "status": "conforming",
                "evidenceRefs": [{"documentVersionId": "V1", "pageNo": 3}], **values}
    case = sourced(inventoryId="INV1", caseId="N1", objectId="W1", commissionId="C1", repairRound=1)
    return {"projectId": "P1", "organizationId": "ORG1", "applicability": sourced(required=True),
            "procedure": sourced(), "caseInventory": sourced(inventoryId="INV1", complete=True, caseCount=1, cases=[case]),
            "commissions": [sourced(commissionId="C1", objectIds=["W1"])],
            "notices": [deepcopy(case)], "feedback": [deepcopy(case)]}


def run(body):
    return dispatch_business_tool("evaluate_ndt_nonconformance", body)


def test_complete_sourced_witness_chain_passes_without_mutating_inputs():
    body = arguments()
    before = deepcopy(body)
    output = run(body)
    assert output["result"] == "passed"
    assert output["ruleVersion"] == "r37-nonconformance-witness-chain-v2"
    assert output["evidenceRefs"]
    assert body == before


@pytest.mark.parametrize("part", ["procedure", "commissions", "notices", "feedback"])
def test_explicit_nonconformance_is_failed(part):
    body = arguments()
    record = body[part][0] if isinstance(body[part], list) else body[part]
    record["status"] = "nonconforming"
    assert run(body)["result"] == "failed"


@pytest.mark.parametrize("case", ["feedback_missing", "wrong_round", "bool_round", "wrong_object", "wrong_case", "wrong_commission", "wrong_project", "wrong_org", "missing_evidence", "template", "duplicate", "orphan", "inventory_incomplete", "unmatched_object", "malformed_status"])
def test_incomplete_or_unmatched_witness_cannot_pass(case):
    body = arguments()
    record = body["feedback"][0]
    if case == "feedback_missing":
        body["feedback"] = []
    elif case == "wrong_round":
        record["repairRound"] = 0
    elif case == "bool_round":
        record["repairRound"] = True
    elif case.startswith("wrong_"):
        key = {"wrong_object": "objectId", "wrong_case": "caseId", "wrong_commission": "commissionId", "wrong_project": "projectId", "wrong_org": "organizationId"}[case]
        record[key] = "OTHER"
    elif case == "missing_evidence":
        record["evidenceRefs"] = []
    elif case == "template":
        record["status"] = "template"
    elif case == "duplicate":
        body["feedback"].append(deepcopy(record))
    elif case == "orphan":
        body["feedback"].append({**record, "caseId": "UNLISTED"})
    elif case == "inventory_incomplete":
        body["caseInventory"]["complete"] = False
    elif case == "unmatched_object":
        body["commissions"][0]["objectIds"] = ["W2"]
    else:
        record["status"] = []
    assert run(body)["result"] == "evidence_insufficient"


def test_empty_case_inventory_requires_explicit_complete_evidence():
    body = arguments()
    body["caseInventory"]["cases"] = []
    body["caseInventory"]["caseCount"] = 0
    body["notices"] = body["feedback"] = []
    assert run(body)["result"] == "passed"  # Procedure and commission still checked.
    body["caseInventory"].pop("complete")
    assert run(body)["result"] == "evidence_insufficient"


def test_not_applicable_needs_sourced_explicit_statement():
    body = arguments()
    body["applicability"]["required"] = False
    assert run(body)["result"] == "not_applicable"
    body["applicability"]["evidenceRefs"] = []
    assert run(body)["result"] == "evidence_insufficient"


def test_generic_document_presence_profile_cannot_bypass_dedicated_tool():
    assert run({"requiredFields": ["procedure"], "procedure": True, "ruleChecks": [{"passed": True}]})["result"] == "evidence_insufficient"
