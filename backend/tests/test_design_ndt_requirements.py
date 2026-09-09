from itertools import permutations

import pytest
from test_regulatory_review_chain import review_ndt

from libs.review_orchestrator.design_ndt_requirements import design_ndt_requirements

PIPELINE = {"pipelineId": "P1", "pipelineGrade": "GC2", "mediumToxicity": "无毒", "leakHazard": "否"}


@pytest.mark.parametrize("clauses", list(permutations(["RT，检测比例100%，Ⅱ级", "UT，检测比例100%，Ⅱ级"])))
def test_one_failing_method_cannot_be_hidden_by_order(clauses):
    text = "GB/T 20801.1-2025。" + "；".join(clauses)
    details = design_ndt_requirements(text)
    assert details["acceptanceLevelMeetsRequirement"] is False
    assert {row["method"]: row["acceptanceLevelMeetsRequirement"] for row in details["methodRequirements"]} == {"RT": True, "UT": False}
    assert review_ndt(text, PIPELINE)["result"] == "failed"


@pytest.mark.parametrize("clauses", list(permutations(["RT，检测比例20%，Ⅲ级", "UT，检测比例100%，Ⅰ级"])))
def test_different_valid_requirements_reach_real_rules(clauses):
    text = "GB/T 20801.1-2025。" + "；".join(clauses)
    details = design_ndt_requirements(text)
    assert details["coveragePercent"] is None
    assert details["requiredAcceptance"] is None
    assert details["acceptanceLevelMeetsRequirement"] is True
    assert review_ndt(text, PIPELINE)["result"] == "passed"


@pytest.mark.parametrize("text", ["RT，检测比例100%，Ⅱ级；UT", "RT，检测比例100%，Ⅱ级；PT，检测比例100%，Ⅱ级", "RT检测比例20%，Ⅲ级，UT检测比例100%，Ⅰ级", "RT替代UT，检测比例100%，Ⅰ级", "RT/UT，检测比例100%，Ⅱ级", "RT或UT，检测比例100%，Ⅱ级"])
def test_missing_unsupported_or_ambiguous_method_cannot_pass(text):
    details = design_ndt_requirements(text)
    assert details["acceptanceLevelMeetsRequirement"] is None
    assert review_ndt("GB/T 20801.1-2025。" + text, PIPELINE)["result"] != "passed"


def test_explicit_shared_method_list_checks_both():
    details = design_ndt_requirements("RT和UT，检测比例100%，Ⅱ级")
    assert details["acceptanceLevelMeetsRequirement"] is False
    assert len(details["methodRequirements"]) == 2


def test_method_aliases_do_not_create_duplicates_or_substring_matches():
    assert design_ndt_requirements("SMART OUTPUT")['methods'] == []
    assert design_ndt_requirements("射线检测(RT)，检测比例20%，Ⅲ级")['methods'] == ['RT']
    rows = design_ndt_requirements("相控阵超声(PAUT)，检测比例100%，Ⅱ级")["methodRequirements"]
    assert [row["method"] for row in rows] == ["PAUT"]
    assert rows[0]["requiredAcceptance"]["method"] == "phasedArray"
