"""R45 防腐层电火花检测：第一条走通"冻结判据"机制的通用解释器规则。

原先 AC-R45-01 绑的 evaluate_corrosion_protection 在 business_tools 里没有实现，
落到通用解释器，而它要的 ruleChecks 全仓没人产生——资料再齐也只返回
`requiredFields_not_configured`。这组用例证明这条路已经走通，并钉住四种结果的边界。
"""
from copy import deepcopy

from libs.review_tools.r45_holiday_test import evaluate_r45_holiday_test, frozen_holiday_test_rules

SCOPE = {"projectId": "P", "objectType": "pipeline", "objectId": "PL-1", "recordVersionId": "REC-V1"}
REF = [{"documentVersionId": "REC-V1", "pageNo": 3, "quotedText": "电火花检测记录"}]


def domain(fields, *, applicable=True, refs=None):
    return {**SCOPE, "domain": "holidayTest", "applicable": applicable,
            "evidenceRefs": deepcopy(refs if refs is not None else REF), **deepcopy(fields)}


def complete():
    return [domain({
        "detector": {"calibrationCertificateNo": "JD-2026-118", "calibrationValidUntil": "2026-12-31",
                     "calibrationValidAtTest": True},
        "test": {"voltage": "5kV", "results": "未发现漏点", "coveragePercent": 100,
                 "fieldJointOrRepairPresent": True, "holidaysFound": False,
                 "reportItemsComplete": True},
    })]


def run(domains, **extra):
    arguments = {"projectId": "P", "scope": deepcopy(SCOPE), "domains": deepcopy(domains),
                 "standardRules": frozen_holiday_test_rules()}
    arguments.update(extra)
    return evaluate_r45_holiday_test(arguments)


def codes(output, status):
    return {row["code"] for row in output["facts"]["processChecks"] if row["result"] == status}


def test_frozen_rules_declare_their_source_and_limits():
    rules = frozen_holiday_test_rules()
    assert set(rules["domains"]) == {"holidayTest"}
    review = rules["sourceReview"]
    assert review["humanVerified"] is False, "不得伪造人工核对"
    assert len(review["limitations"]) >= 3, "只作存在性与布尔判定这件事必须写明"
    assert all(item["verifiedBy"] is None for item in rules["domains"]["holidayTest"]["checks"])


def test_complete_record_passes():
    output = run(complete())
    assert output["result"] == "passed", output["facts"]["processChecks"]
    assert output["evidenceRefs"]


def test_expired_calibration_is_a_nonconformance():
    domains = complete()
    domains[0]["detector"]["calibrationValidAtTest"] = False
    output = run(domains)
    assert output["result"] == "failed"
    assert "holidaytest_detector_calibration_valid" in codes(output, "failed")


def test_partial_coverage_on_field_joints_fails():
    """GB/T 19285-2026 5.3.2.2(c)：补口补伤应 100% 漏点检测。"""
    domains = complete()
    domains[0]["test"]["coveragePercent"] = 80
    output = run(domains)
    assert output["result"] == "failed"
    assert "holidaytest_field_joint_coverage_full" in codes(output, "failed")


def test_coverage_rule_does_not_apply_without_field_joints_or_repairs():
    domains = complete()
    domains[0]["test"].update(fieldJointOrRepairPresent=False, coveragePercent=0)
    output = run(domains)
    assert output["result"] == "passed"
    assert "holidaytest_field_joint_coverage_full" in codes(output, "not_applicable")


def test_unknown_applicability_of_a_rule_stays_insufficient():
    domains = complete()
    domains[0]["test"].pop("fieldJointOrRepairPresent")
    output = run(domains)
    assert output["result"] == "evidence_insufficient"
    assert "holidaytest_field_joint_coverage_full" in codes(output, "evidence_insufficient")


def test_holidays_found_require_a_closed_repair_recheck():
    domains = complete()
    domains[0]["test"].update(holidaysFound=True, repairsRecheckedAndPassed=False)
    output = run(domains)
    assert output["result"] == "failed"
    assert "holidaytest_repair_recheck_closed" in codes(output, "failed")

    domains[0]["test"].update(repairsRecheckedAndPassed=True)
    assert run(domains)["result"] == "passed"


def test_missing_required_item_is_a_nonconformance_not_missing_evidence():
    """检测电压没记——记录本来就该有这一项。"""
    domains = complete()
    domains[0]["test"].pop("voltage")
    output = run(domains)
    assert output["result"] == "failed"
    assert "holidaytest_test_voltage" in codes(output, "failed")


def test_evidence_must_come_from_the_selected_record_version():
    domains = complete()
    domains[0]["evidenceRefs"] = [{"documentVersionId": "OTHER", "pageNo": 1}]
    output = run(domains)
    assert output["result"] == "evidence_insufficient"
    assert "holidaytest_evidence_not_from_selected_document" in codes(output, "evidence_insufficient")


def test_missing_frozen_rules_never_produce_a_verdict():
    output = evaluate_r45_holiday_test(
        {"projectId": "P", "scope": deepcopy(SCOPE), "domains": complete(), "standardRules": {}})
    assert output["result"] == "evidence_insufficient"
    assert "r45_holiday_standard_rules_missing" in codes(output, "evidence_insufficient")


def test_binding_and_registration_point_at_the_dedicated_tool():
    from libs.business_pack.loader import load_business_pack
    from libs.review_orchestrator.ndt_fact_builders import NDT_FACT_BUILDERS
    from libs.review_tools.business_tools import BUSINESS_TOOL_NAMES

    assert "evaluate_r45_holiday_test" in BUSINESS_TOOL_NAMES
    assert 45 in NDT_FACT_BUILDERS
    pack = load_business_pack()
    bindings = (pack.get("atomicCheckToolBindingSet") or {}).get("bindings") or pack.get("atomicCheckToolBindings") or []
    binding = next(item for item in bindings if item.get("atomicCheckId") == "AC-R45-01")
    assert "evaluate_r45_holiday_test" in binding["tools"]
    assert "evaluate_corrosion_protection" not in binding["tools"]
    assert binding["requiredFacts"] == ["r45.holidayTest"]
