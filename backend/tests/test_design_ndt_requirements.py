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


@pytest.mark.parametrize("level", ["Ⅱ", "II", "ii", "2"])
def test_equivalent_exact_levels_reach_real_rule_pass(level):
    text = f"GB/T 20801.1-2025。RT，检测比例100%，验收等级{level}级"
    assert review_ndt(text, PIPELINE)["result"] == "passed"


def test_pipe_table_cell_without_ratio_keyword_is_read():
    # ECD202 管道特性表 p32：表头「检验比例%」在上一行，单元格只写「RT10%」
    row = "A01-PL-02 | Φ89x3.0 | M1E | GC2 | 甲醇 | 水 | 0.413 | RT10% | III级 | √ | 水"
    details = design_ndt_requirements(row)
    assert details["coveragePercent"] == 10
    assert details["methodRequirements"][0]["acceptanceLevel"] == "III"


def test_method_mentioned_elsewhere_without_values_does_not_erase_table_values():
    # 图签只写「损伤比例 | RT10%」没有合格等级；不能因此把特性表里的 Ⅲ 级抹掉
    text = "介质名称 | 甲醇 | 损伤比例 | RT10%\nA01-PL-02 | GC2 | 水 | 0.413 | RT10% | III级 | √"
    details = design_ndt_requirements(text)
    assert details["acceptanceLevelMeetsRequirement"] is True
    from libs.review_orchestrator.design_ndt_requirements import method_value_summary
    assert method_value_summary(details["methodRequirements"], "acceptanceLevel", "级") == "III级"
    assert method_value_summary(details["methodRequirements"], "coveragePercent", "%") == "10%"


def test_method_with_no_value_anywhere_still_counts_as_missing():
    from libs.review_orchestrator.design_ndt_requirements import method_value_summary
    details = design_ndt_requirements("RT10%，III级；UT 检测")
    assert method_value_summary(details["methodRequirements"], "acceptanceLevel", "级") is None
    assert details["acceptanceLevelMeetsRequirement"] is None


@pytest.mark.parametrize("level", ["VIII", "12", "SMARTII", "Ⅰ/Ⅱ", "Ⅲ或Ⅱ", "Ⅲ或者Ⅱ", "不符合Ⅱ", "未达到Ⅱ", "不低于Ⅱ", "Ⅱ级不合格"])
def test_unresolved_level_expression_cannot_be_extracted_as_passing_grade(level):
    text = f"GB/T 20801.1-2025。RT，检测比例100%，验收等级{level}级"
    assert review_ndt(text, PIPELINE)["result"] != "passed"
