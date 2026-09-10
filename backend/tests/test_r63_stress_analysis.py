"""R63 柔性（应力）分析：第三批走通"冻结判据"机制的通用解释器规则。

原先 AC-R63-01 绑的 evaluate_stress_analysis 在 business_tools 里没有实现，
落到通用解释器且 ruleChecks 无人产生——资料再齐也只返回"未配置"的证据不足。

重点钉住 8.6.1.7 的"同时满足"：只看柔性分析这一项就宣布可免除压力试验，
正是把局部评估当成完整结论。
"""
from copy import deepcopy

from libs.review_tools.r63_stress_analysis import (
    evaluate_r63_stress_analysis,
    frozen_stress_analysis_rules,
)

SCOPE = {"projectId": "P", "objectType": "pipeline_system", "objectId": "SYS-1", "reportVersionId": "RPT-V1"}
REF = [{"documentVersionId": "RPT-V1", "pageNo": 12, "quotedText": "柔性分析报告"}]


def complete(**overrides):
    fields = {
        "report": {"issuer": "某设计院", "reportNo": "SA-2026-031"},
        "coverage": {"analyzedSystems": ["SYS-1"], "coversAllExemptedSystems": True},
        "parameters": {"designTemperature": "180℃", "designPressure": 2.5,
                       "propertiesFromCycleExtremes": True, "equivalentCyclesAboveOneMillion": False,
                       "matchDesignDocument": True},
        "design": {"expansionJointPresent": False},
        "exemption": {"pressureTestExemptionClaimed": True, "allPreconditionsMet": True},
        "result": {"displacementStressRangeWithinLimit": True, "stressRangeFactorDerivedFromCycles": True,
                   "conclusion": "合格"},
    }
    payload = deepcopy(fields)
    for path, value in overrides.items():
        head, _, tail = path.partition("__")
        if value is None:
            payload[head].pop(tail, None)
        else:
            payload[head][tail] = value
    return [{**SCOPE, "domain": "stressAnalysis", "applicable": True, "evidenceRefs": deepcopy(REF), **payload}]


def run(domains, **extra):
    arguments = {"projectId": "P", "scope": deepcopy(SCOPE), "domains": deepcopy(domains),
                 "standardRules": frozen_stress_analysis_rules()}
    arguments.update(extra)
    return evaluate_r63_stress_analysis(arguments)


def codes(output, status):
    return {row["code"] for row in output["facts"]["processChecks"] if row["result"] == status}


def test_frozen_rules_declare_their_source_and_limits():
    rules = frozen_stress_analysis_rules()
    assert set(rules["domains"]) == {"stressAnalysis"}
    review = rules["sourceReview"]
    assert review["humanVerified"] is False, "不得伪造人工核对"
    assert any("R35" in text for text in review["limitations"]), "8.6.1.7 a) c) 由别的规则判定必须写明"
    assert all(item["verifiedBy"] is None for item in rules["domains"]["stressAnalysis"]["checks"])


def test_complete_report_passes():
    output = run(complete())
    assert output["result"] == "passed", output["facts"]["processChecks"]
    assert output["evidenceRefs"]


def test_exemption_needs_all_three_preconditions_not_just_flexibility_analysis():
    """8.6.1.7：同时满足 a) b) c) 才可免除。柔性分析本身合格不代表可以免除。"""
    output = run(complete(exemption__allPreconditionsMet=False))
    assert output["result"] == "failed"
    assert "stressanalysis_exemption_requires_all_preconditions" in codes(output, "failed")

    unknown = run(complete(exemption__allPreconditionsMet=None))
    assert unknown["result"] == "evidence_insufficient", "三项是否齐备取不到，不能当成齐备"


def test_exemption_rules_do_not_apply_when_no_exemption_is_claimed():
    output = run(complete(exemption__pressureTestExemptionClaimed=False,
                          exemption__allPreconditionsMet=None,
                          coverage__coversAllExemptedSystems=None))
    assert output["result"] == "passed"
    assert "stressanalysis_exemption_requires_all_preconditions" in codes(output, "not_applicable")
    assert "stressanalysis_coverage_includes_all_exempted_systems" in codes(output, "not_applicable")


def test_analysis_not_covering_every_exempted_system_fails():
    output = run(complete(coverage__coversAllExemptedSystems=False))
    assert output["result"] == "failed"
    assert "stressanalysis_coverage_includes_all_exempted_systems" in codes(output, "failed")


def test_high_cycle_service_requires_a_separate_fatigue_analysis():
    """6.7.5.5 注：当量循环次数 N 大于 10^6 时公式(36)与图 13 不适用。"""
    output = run(complete(parameters__equivalentCyclesAboveOneMillion=True,
                          result__fatigueAnalysisPerformed=False))
    assert output["result"] == "failed"
    assert "stressanalysis_fatigue_analysis_above_one_million_cycles" in codes(output, "failed")

    below = run(complete())
    assert "stressanalysis_fatigue_analysis_above_one_million_cycles" in codes(below, "not_applicable")


def test_expansion_joint_body_must_be_designed_outside_the_range_factor():
    output = run(complete(design__expansionJointPresent=True,
                          result__expansionJointDesignedSeparately=False))
    assert output["result"] == "failed"
    assert "stressanalysis_expansion_joint_designed_separately" in codes(output, "failed")


def test_displacement_stress_range_over_limit_is_a_nonconformance():
    output = run(complete(result__displacementStressRangeWithinLimit=False))
    assert output["result"] == "failed"
    assert "stressanalysis_displacement_stress_range_within_limit" in codes(output, "failed")


def test_a_non_accepting_conclusion_is_rejected():
    output = run(complete(result__conclusion="不满足"))
    assert output["result"] == "failed"
    assert "stressanalysis_conclusion_accepted" in codes(output, "failed")


def test_missing_required_item_is_a_nonconformance_not_missing_evidence():
    """报告没写出具单位——报告本来就该有这一项。"""
    output = run(complete(report__issuer=None))
    assert output["result"] == "failed"
    assert "stressanalysis_report_issuer" in codes(output, "failed")


def test_evidence_must_come_from_the_selected_report_version():
    domains = complete()
    domains[0]["evidenceRefs"] = [{"documentVersionId": "OTHER", "pageNo": 1}]
    output = run(domains)
    assert output["result"] == "evidence_insufficient"
    assert "stressanalysis_evidence_not_from_selected_document" in codes(output, "evidence_insufficient")


def test_missing_frozen_rules_never_produce_a_verdict():
    output = evaluate_r63_stress_analysis(
        {"projectId": "P", "scope": deepcopy(SCOPE), "domains": complete(), "standardRules": {}})
    assert output["result"] == "evidence_insufficient"
    assert "r63_stress_standard_rules_missing" in codes(output, "evidence_insufficient")


def test_binding_and_registration_point_at_the_dedicated_tool():
    from libs.business_pack.loader import load_business_pack
    from libs.review_orchestrator.ndt_fact_builders import NDT_FACT_BUILDERS
    from libs.review_tools.business_tools import BUSINESS_TOOL_NAMES

    assert "evaluate_r63_stress_analysis" in BUSINESS_TOOL_NAMES
    assert 63 in NDT_FACT_BUILDERS
    pack = load_business_pack()
    bindings = (pack.get("atomicCheckToolBindingSet") or {}).get("bindings") or pack.get("atomicCheckToolBindings") or []
    binding = next(item for item in bindings if item.get("atomicCheckId") == "AC-R63-01")
    assert "evaluate_r63_stress_analysis" in binding["tools"]
    assert "evaluate_stress_analysis" not in binding["tools"]
    assert binding["requiredFacts"] == ["r63.stressAnalysis"]
