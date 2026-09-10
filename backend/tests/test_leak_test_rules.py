"""R64／R66／R67 泄漏试验：第二批走通"冻结判据"机制的通用解释器规则。

三条原先都绑 evaluate_leak_test，而那个名字在 business_tools 里没有实现，
落到通用解释器且 ruleChecks 无人产生——资料再齐也只返回"未配置"的证据不足。
"""
from copy import deepcopy

import pytest

from libs.review_tools.leak_test_rules import (
    evaluate_r64_alternative_test,
    evaluate_r66_leak_test_conditions,
    evaluate_r67_leak_test_method,
    frozen_leak_rules,
)

SCOPE = {"projectId": "P", "objectType": "pipeline", "objectId": "PL-1", "recordVersionId": "REC-V1"}
REF = [{"documentVersionId": "REC-V1", "pageNo": 5, "quotedText": "泄漏试验记录"}]

CASES = {
    "evaluate_r64_alternative_test": (evaluate_r64_alternative_test, "alternativeTest", {
        "basis": {"writtenApproval": "三方会签 2026-08-02", "bothTestsImpracticalDocumented": True},
        "method": {"name": "氦质谱吸枪法", "sensitiveLeakTest": True, "sensitivityMeetsThreshold": True},
        "results": {"conclusion": "合格"},
    }),
    "evaluate_r66_leak_test_conditions": (evaluate_r66_leak_test_conditions, "leakTestConditions", {
        "gauges": {"calibrationValidUntil": "2026-12-31", "calibrationValidAtTest": True},
        "medium": {"name": "干燥空气"},
        "conditions": {"mediumTemperature": "18℃", "ambientTemperature": "20℃"},
        "pressure": {"testPressureMPa": 1.0, "airtightnessTest": True, "equalsDesignPressure": True,
                     "exceeds1_6MPa": False, "vacuumPipeline": False},
        "vacuumTest": {"performedAfterPressureTest": False},
    }),
    "evaluate_r67_leak_test_method": (evaluate_r67_leak_test_method, "leakTestMethod", {
        "method": {"name": "气密性试验", "acuteToxicCategory1Or2Gas": False,
                   "airtightnessSubstitutesSensitive": False,
                   "leakTestExemptionClaimed": False, "leakHazardMedium": True,
                   "leakTestPerformedOrExempted": True, "bubbleDirectPressure": False,
                   "halogenLeakDetection": False, "heliumLeakDetection": False,
                   "heliumMixtureUsed": False},
        "report": {"standardRef": "GB/T 20801.1-2025", "holdMinutes": 30, "result": "无可察泄漏",
                   "itemsComplete": True},
    }),
}


def build(tool_name, overrides=None):
    _fn, domain_name, fields = CASES[tool_name]
    payload = deepcopy(fields)
    for path, value in (overrides or {}).items():
        head, _, tail = path.partition(".")
        if tail:
            payload.setdefault(head, {})
            if value is None:
                payload[head].pop(tail, None)
            else:
                payload[head][tail] = value
        elif value is None:
            payload.pop(head, None)
        else:
            payload[head] = value
    return [{**SCOPE, "domain": domain_name, "applicable": True, "evidenceRefs": deepcopy(REF), **payload}]


def run(tool_name, overrides=None, **extra):
    fn, _domain, _fields = CASES[tool_name]
    arguments = {"projectId": "P", "scope": deepcopy(SCOPE), "domains": build(tool_name, overrides),
                 "standardRules": frozen_leak_rules(tool_name)}
    arguments.update(extra)
    return fn(arguments)


def codes(output, status):
    return {row["code"] for row in output["facts"]["processChecks"] if row["result"] == status}


@pytest.mark.parametrize("tool_name", sorted(CASES))
def test_frozen_rules_declare_source_and_limits(tool_name):
    rules = frozen_leak_rules(tool_name)
    review = rules["sourceReview"]
    assert review["humanVerified"] is False, "不得伪造人工核对"
    assert review["limitations"], "来源局限必须写明"
    domain = next(iter(rules["domains"].values()))
    assert all(item["verifiedBy"] is None for item in domain["checks"])


@pytest.mark.parametrize("tool_name", sorted(CASES))
def test_complete_record_passes(tool_name):
    output = run(tool_name)
    assert output["result"] == "passed", output["facts"]["processChecks"]
    assert output["evidenceRefs"]


@pytest.mark.parametrize("tool_name", sorted(CASES))
def test_missing_frozen_rules_never_produce_a_verdict(tool_name):
    fn, _domain, _fields = CASES[tool_name]
    output = fn({"projectId": "P", "scope": deepcopy(SCOPE), "domains": build(tool_name), "standardRules": {}})
    assert output["result"] == "evidence_insufficient"


def test_r64_requires_written_evidence_that_both_tests_are_impractical():
    """8.6.1.7：液压与气压都不切实际才可免除或替代。没有书面依据就是不符合。"""
    output = run("evaluate_r64_alternative_test", {"basis.bothTestsImpracticalDocumented": False})
    assert output["result"] == "failed"
    assert "alternativetest_precondition_documented" in codes(output, "failed")

    unknown = run("evaluate_r64_alternative_test", {"basis.bothTestsImpracticalDocumented": None})
    assert unknown["result"] == "evidence_insufficient", "取不到不能当成没有依据，也不能当成有"


def test_r64_sensitivity_rule_only_applies_to_sensitive_leak_tests():
    not_sensitive = run("evaluate_r64_alternative_test",
                        {"method.sensitiveLeakTest": False, "method.sensitivityMeetsThreshold": None})
    assert not_sensitive["result"] == "passed"
    assert "alternativetest_sensitivity_meets_threshold" in codes(not_sensitive, "not_applicable")

    below = run("evaluate_r64_alternative_test", {"method.sensitivityMeetsThreshold": False})
    assert below["result"] == "failed"


def test_r66_airtightness_pressure_must_equal_design_pressure():
    """8.6.2.3：气密性试验压力为设计压力。"""
    output = run("evaluate_r66_leak_test_conditions", {"pressure.equalsDesignPressure": False})
    assert output["result"] == "failed"
    assert "leaktestconditions_airtightness_pressure_equals_design" in codes(output, "failed")

    hydro = run("evaluate_r66_leak_test_conditions",
                {"pressure.airtightnessTest": False, "pressure.equalsDesignPressure": None})
    assert hydro["result"] == "passed"
    assert "leaktestconditions_airtightness_pressure_equals_design" in codes(hydro, "not_applicable")


def test_r66_high_pressure_needs_tripartite_approval():
    """试验压力大于 1.6MPa 要三方同意；不超过时该判据不适用。"""
    high = run("evaluate_r66_leak_test_conditions",
               {"pressure.exceeds1_6MPa": True, "pressure.tripartiteApprovalObtained": False})
    assert high["result"] == "failed"
    assert "leaktestconditions_tripartite_approval_above_1_6mpa" in codes(high, "failed")

    unknown = run("evaluate_r66_leak_test_conditions", {"pressure.exceeds1_6MPa": None})
    assert unknown["result"] == "evidence_insufficient"


def test_r66_missing_recorded_condition_is_a_nonconformance():
    """介质温度没记——记录本来就该有这一项。"""
    output = run("evaluate_r66_leak_test_conditions", {"conditions.mediumTemperature": None})
    assert output["result"] == "failed"
    assert "leaktestconditions_conditions_mediumtemperature" in codes(output, "failed")


def test_r67_sensitivity_threshold_applies_to_acutely_toxic_media():
    """8.6.2.2：急性毒性危害类别 1 介质、类别 2 气体介质要优先用灵敏度不低于 1e-5 的方法。"""
    toxic = run("evaluate_r67_leak_test_method",
                {"method.acuteToxicCategory1Or2Gas": True, "method.sensitivityMeetsThreshold": False})
    assert toxic["result"] == "failed"
    assert "leaktestmethod_sensitivity_meets_threshold" in codes(toxic, "failed")

    unknown = run("evaluate_r67_leak_test_method", {"method.acuteToxicCategory1Or2Gas": None})
    assert unknown["result"] == "evidence_insufficient", "介质类别不明不能按不适用放过"


def test_r67_substitution_requires_tripartite_approval():
    output = run("evaluate_r67_leak_test_method",
                 {"method.airtightnessSubstitutesSensitive": True, "method.substitutionApprovalObtained": False})
    assert output["result"] == "failed"
    assert "leaktestmethod_substitution_tripartite_approval" in codes(output, "failed")


def test_r67_rejects_a_non_accepting_conclusion():
    output = run("evaluate_r67_leak_test_method", {"report.result": "发现渗漏"})
    assert output["result"] == "failed"
    assert "leaktestmethod_result_accepted" in codes(output, "failed")


def test_bindings_and_registration_point_at_the_dedicated_tools():
    from libs.business_pack.loader import load_business_pack
    from libs.review_orchestrator.ndt_fact_builders import NDT_FACT_BUILDERS
    from libs.review_tools.business_tools import BUSINESS_TOOL_NAMES

    pack = load_business_pack()
    bindings = (pack.get("atomicCheckToolBindingSet") or {}).get("bindings") or pack.get("atomicCheckToolBindings") or []
    for check_id, tool_name, node_id in (("AC-R64-01", "evaluate_r64_alternative_test", 64),
                                         ("AC-R66-01", "evaluate_r66_leak_test_conditions", 66),
                                         ("AC-R67-01", "evaluate_r67_leak_test_method", 67)):
        assert tool_name in BUSINESS_TOOL_NAMES
        assert node_id in NDT_FACT_BUILDERS
        binding = next(item for item in bindings if item.get("atomicCheckId") == check_id)
        assert tool_name in binding["tools"] and "evaluate_leak_test" not in binding["tools"]


# 2026-09-10 补：8.6.2.1.3 豁免、敏感性方法门槛与 8.6.3 真空度试验。
# 这三条原先在现况清单第 7 项里列为未完成。

def test_r67_exemption_needs_both_conditions_at_once():
    """8.6.2.1.3：经气压试验合格**且**试验后未经拆卸，两个条件缺一不可。"""
    output = run("evaluate_r67_leak_test_method",
                 {"method.leakTestExemptionClaimed": True,
                  "method.pneumaticPassedAndNotDisassembled": False})
    assert output["result"] == "failed"
    assert "leaktestmethod_exemption_requires_pneumatic_pass_and_no_disassembly" in codes(output, "failed")

    unknown = run("evaluate_r67_leak_test_method",
                  {"method.leakTestExemptionClaimed": True,
                   "method.pneumaticPassedAndNotDisassembled": None})
    assert unknown["result"] == "evidence_insufficient", "两个条件是否同时满足取不到，不能当成满足"


def test_r67_leak_hazard_medium_must_be_tested_or_exempted():
    """8.6.2.1.1：输送泄漏危害性介质的管道，压力试验后还应当进行泄漏试验。"""
    output = run("evaluate_r67_leak_test_method", {"method.leakTestPerformedOrExempted": False})
    assert output["result"] == "failed"
    assert "leaktestmethod_leak_hazard_medium_requires_leak_test" in codes(output, "failed")


def test_r67_sensitivity_floors_differ_by_method():
    """卤素法 1e-5、氦质谱法 1e-6——门槛不同，不能用同一个数放行。"""
    halogen = run("evaluate_r67_leak_test_method",
                  {"method.halogenLeakDetection": True, "method.sensitivityPaM3PerS": 5e-6})
    assert halogen["result"] == "passed", "5e-6 优于卤素法要求的 1e-5"

    helium = run("evaluate_r67_leak_test_method",
                 {"method.heliumLeakDetection": True, "method.sensitivityPaM3PerS": 5e-6})
    assert helium["result"] == "failed", "同一个 5e-6 达不到氦质谱法的 1e-6"
    assert "leaktestmethod_helium_method_sensitivity" in codes(helium, "failed")


def test_r67_helium_mixture_must_scale_the_sensitivity():
    output = run("evaluate_r67_leak_test_method",
                 {"method.heliumLeakDetection": True, "method.sensitivityPaM3PerS": 1e-7,
                  "method.heliumMixtureUsed": True, "method.mixtureSensitivityScaled": False})
    assert output["result"] == "failed"
    assert "leaktestmethod_helium_mixture_sensitivity_scaled" in codes(output, "failed")


def test_r67_bubble_method_pressure_floor():
    """8.6.2.2.3 a) 1)：气泡法试验压力不小于 25% 设计压力。"""
    output = run("evaluate_r67_leak_test_method",
                 {"method.bubbleDirectPressure": True, "method.testPressurePercentOfDesign": 18,
                  "method.noRepeatingOrContinuousBubbles": True})
    assert output["result"] == "failed"
    assert "leaktestmethod_bubble_method_test_pressure_floor" in codes(output, "failed")


def test_r66_vacuum_degree_test_duration_and_rise():
    """8.6.3：真空管道压力试验合格后还应做 24h 真空度试验，增压率不大于 5%。"""
    base = {"pressure.vacuumPipeline": True, "pressure.vacuumInternalPressureMPa": 0.1,
            "pressure.airtightnessTest": False, "pressure.equalsDesignPressure": None,
            "vacuumTest.performedAfterPressureTest": True,
            "vacuumTest.durationHours": 24, "vacuumTest.pressureRisePercent": 3.2}
    assert run("evaluate_r66_leak_test_conditions", base)["result"] == "passed"

    short = run("evaluate_r66_leak_test_conditions", {**base, "vacuumTest.durationHours": 8})
    assert short["result"] == "failed"
    assert "leaktestconditions_vacuum_degree_test_duration" in codes(short, "failed")

    risen = run("evaluate_r66_leak_test_conditions", {**base, "vacuumTest.pressureRisePercent": 7.5})
    assert risen["result"] == "failed"
    assert "leaktestconditions_vacuum_pressure_rise_within_limit" in codes(risen, "failed")


def test_r66_vacuum_rules_do_not_apply_to_a_normal_pipeline():
    output = run("evaluate_r66_leak_test_conditions")
    assert output["result"] == "passed"
    assert "leaktestconditions_vacuum_degree_test_performed" in codes(output, "not_applicable")
