from copy import deepcopy

import pytest
from test_r36_tools import arguments, run

from libs.review_tools.r36_requirements import combine_r36_requirements


def with_standard():
    body = arguments()
    standard = deepcopy(body["requirements"][0])
    standard.update(standardRef="EXPLICIT-STANDARD", clauseRef="8.3", ratioPercent=100,
                    evidenceRefs=[{"documentVersionId": "STANDARD-V1", "pageNo": 10}])
    body["standardRequirements"] = [standard]
    return body


def test_design_and_standard_are_both_evaluated_without_overwriting_sources():
    body = with_standard()
    before = deepcopy(body)
    assert run(body)["result"] == "failed"  # Meets design 20%, does not meet supplied standard 100%.
    body["plan"]["items"][0]["ratioPercent"] = 100
    output = run(body)
    assert output["result"] == "passed"
    assert {ref["documentVersionId"] for ref in output["evidenceRefs"]} == {"DESIGN-V1", "PLAN-V1", "STANDARD-V1"}
    assert body["requirements"] == before["requirements"] and body["standardRequirements"] == before["standardRequirements"]


def test_disjoint_basis_is_insufficient_not_a_plan_failure():
    body = with_standard()
    body["standardRequirements"][0]["acceptanceLevel"] = "I"
    output = run(body)
    assert output["result"] == "evidence_insufficient"
    conflict = next(row for row in output["facts"]["planChecks"] if row["code"] == "r36_acceptanceLevel_requirements_conflict")
    assert {ref["documentVersionId"] for ref in conflict["evidenceRefs"]} == {"DESIGN-V1", "STANDARD-V1"}
    body["requirements"][0]["allowedAcceptanceLevels"] = ["I", "II"]
    body["standardRequirements"][0]["allowedAcceptanceLevels"] = ["I"]
    body["plan"]["items"][0].update(acceptanceLevel="I", ratioPercent=100)
    assert run(body)["result"] == "passed"


def test_optional_standard_does_not_cancel_mandatory_design():
    body = with_standard()
    body["standardRequirements"][0]["required"] = False
    body["plan"]["items"][0]["ratioPercent"] = 10
    assert run(body)["result"] == "failed"


@pytest.mark.parametrize("case", ["missing_clause", "duplicate", "malformed", "spoof_design_origin"])
def test_unidentified_or_ambiguous_sources_do_not_pass(case):
    body = with_standard()
    if case == "missing_clause":
        body["standardRequirements"][0].pop("clauseRef")
    elif case == "duplicate":
        body["standardRequirements"].append(deepcopy(body["standardRequirements"][0]))
    elif case == "malformed":
        body["standardRequirements"][0]["standardRef"] = []
    else:
        extra = {**body["requirements"][0], "standardRef": "FAKE", "requirementOrigin": "standard"}
        body["requirements"].append(extra)
    assert run(body)["result"] == "evidence_insufficient"


def test_source_origin_is_assigned_by_collection_not_claimed_by_row():
    rows, issues = combine_r36_requirements([{**arguments()["requirements"][0], "requirementOrigin": "standard"}], [])
    assert issues == [] and rows[0]["requirementOrigin"] == "design"


def test_stricter_design_is_not_overridden_by_standard():
    body = with_standard()
    body["requirements"][0]["ratioPercent"] = 100
    body["standardRequirements"][0]["ratioPercent"] = 20
    assert run(body)["result"] == "failed"
    body["plan"]["items"][0]["ratioPercent"] = 100
    assert run(body)["result"] == "passed"


def test_optional_design_does_not_cancel_mandatory_standard():
    body = with_standard()
    body["requirements"][0]["required"] = False
    assert run(body)["result"] == "failed"


def test_distinct_standard_clauses_jointly_constrain_plan():
    body = with_standard()
    another = deepcopy(body["standardRequirements"][0])
    another.update(clauseRef="8.4", ratioPercent=50)
    body["standardRequirements"].append(another)
    body["plan"]["items"][0]["ratioPercent"] = 50
    assert run(body)["result"] == "failed"
    body["plan"]["items"][0]["ratioPercent"] = 100
    assert run(body)["result"] == "passed"


def test_disjoint_timing_retains_conflicting_sources():
    body = with_standard()
    body["standardRequirements"][0]["timing"] = "before_pwht"
    output = run(body)
    assert output["result"] == "evidence_insufficient"
    conflict = next(row for row in output["facts"]["planChecks"] if row["code"] == "r36_timing_requirements_conflict")
    assert {ref["documentVersionId"] for ref in conflict["evidenceRefs"]} == {"DESIGN-V1", "STANDARD-V1"}
