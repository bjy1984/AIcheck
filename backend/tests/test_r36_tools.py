from copy import deepcopy

import pytest

from libs.review_tools.business_tools import dispatch_business_tool


def arguments():
    refs = [{"documentVersionId": "DESIGN-V1", "pageNo": 2}]
    requirement = {"projectId": "P1", "objectId": "W1", "method": "UT", "required": True, "ratioPercent": 20,
                   "timing": "after_pwht", "acceptanceLevel": "II", "evidenceRefs": refs}
    item = {**deepcopy(requirement), "planId": "PLAN1", "evidenceRefs": [{"documentVersionId": "PLAN-V1", "pageNo": 3}]}
    return {"projectId": "P1", "applicability": {"required": True, "evidenceRefs": refs},
            "requirements": [requirement], "plan": {"projectId": "P1", "planId": "PLAN1", "approved": True,
            "personnelReady": True, "equipmentReady": True, "evidenceRefs": item["evidenceRefs"], "items": [item]}}


def run(body):
    return dispatch_business_tool("evaluate_r36_ndt_plan", body)


def test_r36_four_states_and_input_preservation():
    body = arguments()
    before = deepcopy(body)
    assert run(body)["result"] == "passed" and body == before
    body["plan"]["items"][0]["ratioPercent"] = 10
    assert run(body)["result"] == "failed"
    body["plan"]["items"] = []
    assert run(body)["result"] == "evidence_insufficient"
    body["applicability"]["required"] = False
    assert run(body)["result"] == "not_applicable"
    body["applicability"]["evidenceRefs"] = []
    assert run(body)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("value,expected", [(20, "passed"), (100, "passed"), (19.9, "failed"), (None, "evidence_insufficient"), (-1, "evidence_insufficient"), (101, "evidence_insufficient"), (True, "evidence_insufficient"), ("NaN", "evidence_insufficient"), ("Infinity", "evidence_insufficient"), ("20%", "evidence_insufficient")])
def test_r36_percent_units_and_boundaries(value, expected):
    body = arguments()
    body["plan"]["items"][0]["ratioPercent"] = value
    assert run(body)["result"] == expected


@pytest.mark.parametrize("case", ["method", "object", "project", "no_evidence", "template", "duplicate_requirement", "duplicate_item", "level_label"])
def test_r36_unmatched_or_unsupported_facts_are_insufficient(case):
    body = arguments()
    item = body["plan"]["items"][0]
    if case in {"method", "object", "project"}:
        item[{"method": "method", "object": "objectId", "project": "projectId"}[case]] = "OTHER"
    elif case == "no_evidence":
        item["evidenceRefs"] = []
    elif case == "template":
        body["plan"]["approved"] = "template"
    elif case == "duplicate_requirement":
        body["requirements"].append(deepcopy(body["requirements"][0]))
    elif case == "duplicate_item":
        body["plan"]["items"].append(deepcopy(item))
    elif case == "level_label":
        item["acceptanceLevel"] = "I"
    assert run(body)["result"] == "evidence_insufficient"


def test_optional_inspection_is_not_mandatory_and_explicit_accepted_levels_are_used():
    body = arguments()
    body["requirements"].append({"projectId": "P1", "required": False, "evidenceRefs": body["requirements"][0]["evidenceRefs"]})
    assert run(body)["result"] == "passed"
    body["requirements"][0]["allowedAcceptanceLevels"] = ["I", "II"]
    body["plan"]["items"][0]["acceptanceLevel"] = "I"
    assert run(body)["result"] == "passed"
    body["plan"]["items"][0]["acceptanceLevel"] = "III"
    assert run(body)["result"] == "failed"
    body["requirements"][0]["allowedAcceptanceLevels"] = ["I"]
    assert run(body)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("field", ["approved", "personnelReady", "equipmentReady"])
def test_r36_explicit_readiness_failure_and_unknown_are_distinct(field):
    body = arguments()
    body["plan"][field] = False
    assert run(body)["result"] == "failed"
    body["plan"][field] = None
    assert run(body)["result"] == "evidence_insufficient"


def test_r36_generic_presence_profile_is_not_a_site_plan():
    assert run({"facts": {"document": "exists"}, "requiredFields": ["document"], "ruleChecks": []})["result"] == "evidence_insufficient"


@pytest.mark.parametrize("value", [None, "OTHER"])
def test_r36_items_cannot_reuse_another_plans_approval(value):
    body = arguments()
    body["plan"]["items"][0]["planId"] = value
    assert run(body)["result"] == "evidence_insufficient"


def test_r36_missing_plan_identity_is_not_inferred():
    body = arguments()
    body["plan"].pop("planId")
    assert run(body)["result"] == "evidence_insufficient"
