from copy import deepcopy

import pytest

from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool
from libs.review_tools.r39_approval import SCOPE_FIELDS


def arguments():
    scope = dict(zip(SCOPE_FIELDS, ("P1", "ORG1", "DOC1", "DV1", "instruction", "UT", "CYCLE1", "QMS1", "QMSV1"), strict=True))
    refs = [{"documentVersionId": "QMSV1", "pageNo": 2, "quotedText": "Synthetic QMS requirements"}]
    steps = [{"stepId": role, "role": role, "required": True, "authorizedSignerIds": [person],
              "authorizationComplete": True, "after": [], "distinctFrom": [], "evidenceRefs": deepcopy(refs)}
             for role, person in (("author", "A"), ("reviewer", "B"), ("approver", "C"))]
    steps[1]["after"] = ["author"]
    steps[2]["after"] = ["reviewer"]
    steps[2]["distinctFrom"] = ["author"]
    signatures = [{**scope, "stepId": step["stepId"], "role": step["role"], "signerId": step["authorizedSignerIds"][0],
                   "approved": True, "signedAt": f"2026-09-09T0{i}:00:00+00:00",
                   "evidenceRefs": [{"documentVersionId": "DV1", "pageNo": 3, "quotedText": "Synthetic signature"}]}
                  for i, step in enumerate(steps)]
    return {"projectId": "P1", "scope": scope,
            "requirements": {**scope, "complete": True, "applicable": True, "steps": steps, "evidenceRefs": deepcopy(refs)},
            "signatureInventory": {**scope, "complete": True, "signatures": signatures, "evidenceRefs": deepcopy(signatures[0]["evidenceRefs"])}}


def run(body):
    return dispatch_runtime_tool({}, "evaluate_r39_approval_chain", body)


def test_four_states_preserve_inputs_and_partial_claim():
    body = arguments()
    before = deepcopy(body)
    result = run(body)
    assert result["result"] == "passed" and body == before
    assert result["facts"]["wholeRuleAcceptance"] == "not_evaluated"
    assert result["facts"]["evidenceVerified"] is False
    assert {r["documentVersionId"] for r in result["evidenceRefs"]} == {"QMSV1", "DV1"}
    body["signatureInventory"]["signatures"][0]["approved"] = False
    assert run(body)["result"] == "failed"
    body["signatureInventory"]["signatures"] = []
    assert run(body)["result"] == "evidence_insufficient"
    for step in body["requirements"]["steps"]:
        step.update(required=False, after=[], distinctFrom=[])
    assert run(body)["result"] == "not_applicable"


@pytest.mark.parametrize("field", SCOPE_FIELDS)
@pytest.mark.parametrize("record", ["requirements", "signatureInventory", "signature"])
def test_scope_mismatch_never_passes(field, record):
    body = arguments()
    target = body[record] if record != "signature" else body["signatureInventory"]["signatures"][0]
    target[field] = "OTHER"
    assert run(body)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("change,expected", [({"approved": False}, "failed"), ({"role": "OTHER"}, "failed"),
    ({"signerId": "OTHER"}, "failed"), ({"approved": "true"}, "evidence_insufficient"),
    ({"approved": 1}, "evidence_insufficient"), ({"signedAt": "2026-09-09"}, "evidence_insufficient"),
    ({"signedAt": "invalid"}, "evidence_insufficient"), ({"evidenceRefs": []}, "evidence_insufficient")])
def test_signature_facts(change, expected):
    body = arguments()
    body["signatureInventory"]["signatures"][2].update(change)
    assert run(body)["result"] == expected


@pytest.mark.parametrize("case", ["cycle", "unknown_dependency", "optional_dependency", "self_dependency", "duplicate_step", "unsupported_condition", "incomplete_authorization", "empty_authorization", "duplicate_signer", "missing_after"])
def test_invalid_requirements_cannot_be_skipped(case):
    body = arguments()
    steps = body["requirements"]["steps"]
    if case == "cycle":
        steps[0]["after"] = ["approver"]
    elif case == "unknown_dependency":
        steps[0]["distinctFrom"] = ["UNKNOWN"]
    elif case == "optional_dependency":
        steps[0]["required"] = False
    elif case == "self_dependency":
        steps[0]["after"] = ["author"]
    elif case == "duplicate_step":
        steps.append(deepcopy(steps[0]))
    elif case == "unsupported_condition":
        steps[0]["requiredCertificateLevel"] = "III"
    elif case == "incomplete_authorization":
        steps[0]["authorizationComplete"] = 1
    elif case == "empty_authorization":
        steps[0]["authorizedSignerIds"] = []
    elif case == "duplicate_signer":
        steps[0]["authorizedSignerIds"] *= 2
    else:
        steps[0].pop("after")
    assert run(body)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("case", ["duplicate", "orphan", "missing", "incomplete_inventory", "incomplete_requirements", "missing_basis", "wrong_project"])
def test_inventory_and_basis_validation(case):
    body = arguments()
    signatures = body["signatureInventory"]["signatures"]
    if case == "duplicate":
        signatures.append(deepcopy(signatures[0]))
    elif case == "orphan":
        signatures.append({**deepcopy(signatures[0]), "stepId": "OTHER"})
    elif case == "missing":
        signatures.pop()
    elif case == "incomplete_inventory":
        body["signatureInventory"]["complete"] = False
    elif case == "incomplete_requirements":
        body["requirements"]["complete"] = False
    elif case == "missing_basis":
        body["requirements"]["evidenceRefs"] = []
    else:
        body["projectId"] = "OTHER"
    assert run(body)["result"] == "evidence_insufficient"


def test_order_timezone_equivalence_and_explicit_person_separation():
    body = arguments()
    signatures = body["signatureInventory"]["signatures"]
    signatures[2]["signedAt"] = "2026-09-09T00:30:00+00:00"
    assert run(body)["result"] == "failed"
    signatures[2]["signedAt"] = "2026-09-09T09:00:00+08:00"
    assert run(body)["result"] == "passed"
    signatures[2]["signerId"] = "A"
    body["requirements"]["steps"][2]["authorizedSignerIds"] = ["A"]
    assert run(body)["result"] == "failed"
    body["requirements"]["steps"][2]["distinctFrom"] = []
    assert run(body)["result"] == "passed"


def test_no_default_approver_or_invented_qualification():
    body = arguments()
    body["requirements"]["steps"] = body["requirements"]["steps"][:2]
    body["signatureInventory"]["signatures"].pop()
    assert run(body)["result"] == "passed"


def test_unsupported_global_requirements_are_not_silently_ignored():
    body = arguments()
    body["requirements"]["mustApproveBeforeIssue"] = True
    assert run(body)["result"] == "evidence_insufficient"
