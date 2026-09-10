"""AC-R11-03：施工方案的焊接与试验内容是否满足施工标准要求。

判据全部来自规则包冻结的 constructionPlanProcessRules；工具不自行推导限值。
这组用例钉住四类结果的边界，重点是「该写没写」判不符合而不是证据不足——
方案本来就该写，把它算成缺证据等于替施工单位开脱。
"""
from copy import deepcopy

from libs.review_orchestrator.r11_facts import frozen_construction_plan_process_rules
from libs.review_tools.r11_process_standards import evaluate_r11_process_standards

SCOPE = {"projectId": "P", "objectType": "pipeline", "objectId": "PL-1", "planVersionId": "PLAN-V1"}
REF = [{"documentVersionId": "PLAN-V1", "pageNo": 12, "quotedText": "焊接与试验专项要求"}]


def domain(name, requirements, *, applicable=True, refs=None):
    return {**SCOPE, "domain": name, "applicable": applicable,
            "evidenceRefs": deepcopy(refs if refs is not None else REF),
            "requirements": deepcopy(requirements)}


def complete_domains():
    return [
        domain("welding", {"fillerMetal": "E5015", "preheat": "100℃", "postWeldHeatTreatment": "690℃×2h",
                           "ndtCoverage": "20%"}),
        domain("pressureTest", {"method": "液压", "testPressure": "1.5倍设计压力", "holdMinutes": 15,
                                "testPressureMeetsRatio": True, "pneumaticTest": False,
                                # 归属明确：本方案只对一个对象说了一次耐压试验
                                "objectMappingResolved": True}),
        domain("ndt", {"method": "RT", "coverage": "20%", "acceptanceCriteria": "Ⅲ级",
                       "coverageMeetsRequirement": True, "acceptanceLevelMeetsRequirement": True}),
        domain("leakTest", {"method": "气密性试验", "acceptanceCriteria": "无可察泄漏"}),
    ]


def run(domains, **extra):
    arguments = {"projectId": "P", "scope": deepcopy(SCOPE), "domains": deepcopy(domains),
                 "standardRules": frozen_construction_plan_process_rules()}
    arguments.update(extra)
    return evaluate_r11_process_standards(arguments)


def codes(output, status):
    return {row["code"] for row in output["facts"]["processChecks"] if row["result"] == status}


def test_frozen_rules_are_loaded_from_the_clause_package_and_declare_their_limits():
    rules = frozen_construction_plan_process_rules()
    assert set(rules["domains"]) == {"welding", "pressureTest", "ndt", "leakTest"}
    review = rules["sourceReview"]
    assert review["humanVerified"] is False, "不得伪造人工核对"
    assert review["limitations"], "来源局限必须写明"


def test_complete_plan_passes_every_domain():
    output = run(complete_domains())
    assert output["result"] == "passed", output["facts"]["processChecks"]
    assert set(output["facts"]["evaluatedDomains"]) == {"welding", "pressureTest", "ndt", "leakTest"}
    assert output["evidenceRefs"], "通过也要带出原文引用"


def test_missing_required_item_is_a_nonconformance_not_missing_evidence():
    """焊接域没写焊后热处理——方案本来就该写，判不符合。"""
    domains = complete_domains()
    domains[0]["requirements"].pop("postWeldHeatTreatment")
    output = run(domains)
    assert output["result"] == "failed"
    assert "welding_requirements_postweldheattreatment" in codes(output, "failed")


def test_domain_absent_from_the_plan_is_a_nonconformance():
    """冻结规则要求覆盖泄漏试验，方案里整个领域都没有。"""
    output = run([row for row in complete_domains() if row["domain"] != "leakTest"])
    assert output["result"] == "failed"
    assert "leaktest_domain_missing" in codes(output, "failed")


def test_value_below_the_standard_limit_fails():
    """保压 6 分钟低于 GB/T 20801.1-2025 的 10 分钟。"""
    domains = complete_domains()
    domains[1]["requirements"]["holdMinutes"] = 6
    output = run(domains)
    assert output["result"] == "failed"
    assert "pressuretest_hold_minutes" in codes(output, "failed")


def test_pneumatic_ceiling_only_applies_when_the_plan_says_it_is_pneumatic():
    """气压上限带适用性开关：明确不是气压则不适用；开关缺失则证据不足，不放过。"""
    domains = complete_domains()
    domains[1]["requirements"]["pneumaticTest"] = True
    domains[1]["requirements"]["testPressureExceedsMax"] = True
    assert "pressuretest_pneumatic_ratio_ceiling" in codes(run(domains), "failed")

    domains[1]["requirements"].pop("pneumaticTest")
    unknown = run(domains)
    assert unknown["result"] == "evidence_insufficient"
    assert "pressuretest_pneumatic_ratio_ceiling" in codes(unknown, "evidence_insufficient")


def test_derived_boolean_without_a_value_is_not_treated_as_false():
    """比例是否达标取不到值时保留证据不足，不能当成不达标，也不能当成达标。"""
    domains = complete_domains()
    domains[2]["requirements"].pop("coverageMeetsRequirement")
    output = run(domains)
    assert output["result"] == "evidence_insufficient"
    assert "ndt_coverage_meets_grade_requirement" in codes(output, "evidence_insufficient")


def test_explicitly_not_applicable_domain_is_not_a_nonconformance():
    domains = complete_domains()
    domains[3]["applicable"] = False
    output = run(domains)
    assert output["result"] == "passed"
    assert "leaktest_not_applicable" in codes(output, "not_applicable")


def test_unknown_applicability_stays_insufficient():
    domains = complete_domains()
    domains[3]["applicable"] = None
    output = run(domains)
    assert output["result"] == "evidence_insufficient"
    assert "leaktest_applicability_unknown" in codes(output, "evidence_insufficient")


def test_evidence_must_come_from_the_selected_plan_version():
    domains = complete_domains()
    domains[0]["evidenceRefs"] = [{"documentVersionId": "OTHER-VERSION", "pageNo": 3}]
    output = run(domains)
    assert output["result"] == "evidence_insufficient"
    assert "welding_evidence_not_from_selected_document" in codes(output, "evidence_insufficient")


def test_ambiguous_or_foreign_object_never_selects_a_row():
    foreign = complete_domains()
    foreign[0]["objectId"] = "PL-OTHER"
    assert run(foreign)["result"] == "evidence_insufficient"

    duplicated = complete_domains() + [complete_domains()[0]]
    assert run(duplicated)["result"] == "evidence_insufficient"

    unknown_domain = complete_domains() + [domain("somethingElse", {})]
    output = run(unknown_domain)
    assert output["result"] == "evidence_insufficient"
    assert "r11_process_unknown_domain" in codes(output, "evidence_insufficient")


def test_missing_frozen_rules_or_scope_never_produce_a_verdict():
    assert evaluate_r11_process_standards({"projectId": "P"})["result"] == "evidence_insufficient"
    no_rules = {"projectId": "P", "scope": deepcopy(SCOPE), "domains": complete_domains(), "standardRules": {}}
    output = evaluate_r11_process_standards(no_rules)
    assert output["result"] == "evidence_insufficient"
    assert "r11_process_standard_rules_missing" in codes(output, "evidence_insufficient")


def test_selection_issues_downgrade_a_pass():
    output = run(complete_domains(), selectionIssues=[{"code": "r11_selected_source_missing_or_ambiguous"}])
    assert output["result"] == "evidence_insufficient"


def test_tool_is_registered_and_bound_to_the_atomic_check():
    from libs.business_pack.loader import load_business_pack
    from libs.review_tools.business_tools import BUSINESS_TOOL_NAMES

    assert "evaluate_r11_process_standards" in BUSINESS_TOOL_NAMES
    pack = load_business_pack()
    bindings = (pack.get("atomicCheckToolBindingSet") or {}).get("bindings") or pack.get("atomicCheckToolBindings") or []
    binding = next(item for item in bindings if item.get("atomicCheckId") == "AC-R11-03")
    assert "evaluate_r11_process_standards" in binding["tools"]
    assert "evaluate_construction_plan" not in binding["tools"]
    # implementationStatus 在本专案只表示是否属试点实装范围（R04/R05/R12-R34），
    # 不表示有没有专用工具——AC-R11-02 早有 evaluate_r11_project_parameters，仍标 binding_only。
    # 这里跟随既有口径，改它会动到业务包契约的分组断言。
    assert binding["implementationStatus"] == "binding_only"


def test_pneumatic_yield_ceiling_is_a_second_limit_not_covered_by_the_1_33_check():
    """GB/T 20801.1-2025 8.6.1.4 e) 2）：气压试验还有屈服强度极限时试验压力的 90% 这一上限。

    只判 1.33 倍等于只判了一半——算不出第二个上限时必须保留证据不足，
    不能因为 1.33 倍那一条通过就放行。
    """
    domains = complete_domains()
    domains[1]["requirements"].update(pneumaticTest=True, testPressureExceedsMax=False)

    # 第二个上限算不出来 → 证据不足，而不是通过
    unresolved = run(domains)
    assert unresolved["result"] == "evidence_insufficient"
    assert "pressuretest_pneumatic_yield_ceiling" in codes(unresolved, "evidence_insufficient")

    # 明确没超过 → 通过
    domains[1]["requirements"]["testPressureExceedsYieldCeiling"] = False
    assert run(domains)["result"] == "passed"

    # 1.33 倍没超但屈服上限超了 → 仍然不符合
    domains[1]["requirements"]["testPressureExceedsYieldCeiling"] = True
    exceeded = run(domains)
    assert exceeded["result"] == "failed"
    assert "pressuretest_pneumatic_yield_ceiling" in codes(exceeded, "failed")

    # 液压试验不适用这一条
    domains[1]["requirements"].update(pneumaticTest=False)
    domains[1]["requirements"].pop("testPressureExceedsYieldCeiling")
    assert run(domains)["result"] == "passed"
