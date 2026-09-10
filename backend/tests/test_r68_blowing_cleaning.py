"""R68 管道清理、吹扫和清洗：第三批走通"冻结判据"机制的通用解释器规则。

原先 AC-R68-01 绑的 evaluate_blowing_cleaning 在 business_tools 里没有实现，
落到通用解释器且 ruleChecks 无人产生——资料再齐也只返回"未配置"的证据不足。

吹洗方法各有各的条文要求，判据按方法开关分支适用。这里重点钉住：
不是这种方法就不适用、方法本身取不到值就保持证据不足、该记没记判不符合。
"""
from copy import deepcopy

from libs.review_tools.r68_blowing_cleaning import (
    evaluate_r68_blowing_cleaning,
    frozen_blowing_cleaning_rules,
)

SCOPE = {"projectId": "P", "objectType": "pipeline", "objectId": "PL-1", "recordVersionId": "REC-V1"}
REF = [{"documentVersionId": "REC-V1", "pageNo": 7, "quotedText": "吹扫清洗记录"}]


def complete(**overrides):
    fields = {
        "plan": {"documentNo": "BC-2026-07", "method": "空气吹扫", "issuedBeforeInstallation": True,
                 "reservedPositionsMarked": True, "methodConformsToSelectionRules": True,
                 "instrumentsRemovedOrBypassed": True, "nonBlowableItemsPresent": False,
                 "lowTemperatureService": False},
        "medium": {"name": "干燥压缩空气", "airBlowing": True, "waterFlush": False, "steamBlowing": False,
                   "chemicalCleaning": False, "austeniticStainlessWaterFlush": False,
                   "flammableOrToxic": False, "strongOxidizerService": False},
        "pressure": {"notExceedingDesignPressure": True},
        "sequence": {},
        "safety": {"ownerAndDesignerRequirementsProvided": True},
        "acceptance": {"conclusion": "合格", "meetsStandardAndDesign": True, "reprotectionApplied": True},
    }
    payload = deepcopy(fields)
    for path, value in overrides.items():
        head, _, tail = path.partition("__")
        if value is None:
            payload[head].pop(tail, None)
        else:
            payload[head][tail] = value
    return [{**SCOPE, "domain": "blowingCleaning", "applicable": True, "evidenceRefs": deepcopy(REF), **payload}]


def run(domains, **extra):
    arguments = {"projectId": "P", "scope": deepcopy(SCOPE), "domains": deepcopy(domains),
                 "standardRules": frozen_blowing_cleaning_rules()}
    arguments.update(extra)
    return evaluate_r68_blowing_cleaning(arguments)


def codes(output, status):
    return {row["code"] for row in output["facts"]["processChecks"] if row["result"] == status}


def test_frozen_rules_declare_their_source_and_limits():
    rules = frozen_blowing_cleaning_rules()
    assert set(rules["domains"]) == {"blowingCleaning"}
    review = rules["sourceReview"]
    assert review["humanVerified"] is False, "不得伪造人工核对"
    assert any("GB 50235" in text for text in review["limitations"]), "只 visual_verified 的来源未纳入判据必须写明"
    assert all(item["verifiedBy"] is None for item in rules["domains"]["blowingCleaning"]["checks"])


def test_complete_air_blowing_record_passes():
    output = run(complete())
    assert output["result"] == "passed", [row for row in output["facts"]["processChecks"]
                                          if row["result"] not in {"passed", "not_applicable"}]
    assert output["evidenceRefs"]


def test_plan_must_be_issued_before_installation():
    """7.9.1.4：吹扫、清洗方案应在管道安装之前提出。"""
    output = run(complete(plan__issuedBeforeInstallation=False))
    assert output["result"] == "failed"
    assert "blowingcleaning_plan_issued_before_installation" in codes(output, "failed")


def test_instruments_must_be_removed_or_bypassed_before_blowing():
    """7.9.1.6：吹洗前不应安装孔板、调节阀、安全阀、仪表等。"""
    output = run(complete(plan__instrumentsRemovedOrBypassed=False))
    assert output["result"] == "failed"
    assert "blowingcleaning_instruments_removed_or_bypassed" in codes(output, "failed")


def test_air_blowing_pressure_must_not_exceed_design_pressure():
    """7.9.3：空气的吹扫压力不应超过容器和管道的设计压力。"""
    output = run(complete(pressure__notExceedingDesignPressure=False))
    assert output["result"] == "failed"
    assert "blowingcleaning_air_pressure_not_exceeding_design" in codes(output, "failed")


def test_air_rules_do_not_apply_to_a_water_flush():
    output = run(complete(medium__airBlowing=False, medium__waterFlush=True,
                          pressure__notExceedingDesignPressure=None,
                          acceptance__waterDrained=True))
    assert output["result"] == "passed"
    assert "blowingcleaning_air_pressure_not_exceeding_design" in codes(output, "not_applicable")


def test_unknown_method_flag_stays_insufficient_instead_of_being_waived():
    output = run(complete(medium__airBlowing=None))
    assert output["result"] == "evidence_insufficient"
    assert "blowingcleaning_air_pressure_not_exceeding_design" in codes(output, "evidence_insufficient")


def test_austenitic_stainless_water_flush_has_a_chloride_ceiling():
    """7.9.2：冲洗奥氏体不锈钢管道时，水中氯离子含量不应超过 50 mg/L。"""
    base = dict(medium__airBlowing=False, medium__waterFlush=True,
                medium__austeniticStainlessWaterFlush=True,
                pressure__notExceedingDesignPressure=None, acceptance__waterDrained=True)
    over = run(complete(**base, medium__chlorideMgPerL=63))
    assert over["result"] == "failed"
    assert "blowingcleaning_water_chloride_within_limit" in codes(over, "failed")

    within = run(complete(**base, medium__chlorideMgPerL=42))
    assert within["result"] == "passed"


def test_steam_blowing_requires_preheat_cycle_and_thermal_service():
    """7.9.4.1 与 7.9.1.5 d)：非热力管道不准许采用蒸汽吹扫。"""
    base = dict(medium__airBlowing=False, medium__steamBlowing=True,
                pressure__notExceedingDesignPressure=None,
                plan__thermalPipelineConfirmed=True,
                sequence__preheatDrainAndDisplacementChecked=True,
                sequence__heatCoolReheatCycle=True,
                safety__temporaryLineAndSilencerCompliant=True)
    assert run(complete(**base))["result"] == "passed"

    non_thermal = run(complete(**{**base, "plan__thermalPipelineConfirmed": False}))
    assert non_thermal["result"] == "failed"
    assert "blowingcleaning_steam_only_on_thermal_pipelines" in codes(non_thermal, "failed")

    no_cycle = run(complete(**{**base, "sequence__heatCoolReheatCycle": False}))
    assert no_cycle["result"] == "failed"
    assert "blowingcleaning_steam_heat_cool_reheat_cycle" in codes(no_cycle, "failed")


def test_chemical_cleaning_requires_a_qualified_formula_and_compliant_waste_disposal():
    base = dict(medium__airBlowing=False, medium__chemicalCleaning=True,
                pressure__notExceedingDesignPressure=None,
                safety__protectiveEquipmentProvided=True,
                plan__cleaningSolutionFormulaQualified=True,
                acceptance__wasteDisposalCompliant=True)
    assert run(complete(**base))["result"] == "passed"

    unqualified = run(complete(**{**base, "plan__cleaningSolutionFormulaQualified": False}))
    assert unqualified["result"] == "failed"
    assert "blowingcleaning_chemical_cleaning_formula_qualified" in codes(unqualified, "failed")

    waste = run(complete(**{**base, "acceptance__wasteDisposalCompliant": False}))
    assert waste["result"] == "failed"
    assert "blowingcleaning_chemical_waste_disposal_compliant" in codes(waste, "failed")


def test_flammable_or_toxic_medium_needs_documented_precautions_and_a_marked_area():
    output = run(complete(medium__flammableOrToxic=True,
                          safety__preventiveMeasuresDocumented=False,
                          safety__workAreaIsolatedAndMarked=False))
    assert output["result"] == "failed"
    assert {"blowingcleaning_hazardous_medium_precautions_documented",
            "blowingcleaning_hazardous_medium_work_area_isolated_and_marked"} <= codes(output, "failed")


def test_strong_oxidizer_service_must_be_degreased_before_installation():
    """7.9.1.2：强氧化性流体管道应在装配后、安装前分段或单件进行脱脂。"""
    output = run(complete(medium__strongOxidizerService=True, plan__degreasingBeforeInstallation=False))
    assert output["result"] == "failed"
    assert "blowingcleaning_degreasing_before_installation_for_strong_oxidizer" in codes(output, "failed")


def test_pipes_must_be_sealed_after_cleaning():
    """7.9.1.9：应及时采取封闭管口或充氮保护等措施防止再污染。"""
    output = run(complete(acceptance__reprotectionApplied=False))
    assert output["result"] == "failed"
    assert "blowingcleaning_reprotection_after_cleaning" in codes(output, "failed")


def test_missing_required_item_is_a_nonconformance_not_missing_evidence():
    """记录没写吹洗方法——记录本来就该有这一项。"""
    output = run(complete(plan__method=None))
    assert output["result"] == "failed"
    assert "blowingcleaning_plan_method" in codes(output, "failed")


def test_evidence_must_come_from_the_selected_record_version():
    domains = complete()
    domains[0]["evidenceRefs"] = [{"documentVersionId": "OTHER", "pageNo": 1}]
    output = run(domains)
    assert output["result"] == "evidence_insufficient"
    assert "blowingcleaning_evidence_not_from_selected_document" in codes(output, "evidence_insufficient")


def test_missing_frozen_rules_never_produce_a_verdict():
    output = evaluate_r68_blowing_cleaning(
        {"projectId": "P", "scope": deepcopy(SCOPE), "domains": complete(), "standardRules": {}})
    assert output["result"] == "evidence_insufficient"
    assert "r68_blowing_standard_rules_missing" in codes(output, "evidence_insufficient")


def test_binding_and_registration_point_at_the_dedicated_tool():
    from libs.business_pack.loader import load_business_pack
    from libs.review_orchestrator.ndt_fact_builders import NDT_FACT_BUILDERS
    from libs.review_tools.business_tools import BUSINESS_TOOL_NAMES

    assert "evaluate_r68_blowing_cleaning" in BUSINESS_TOOL_NAMES
    assert 68 in NDT_FACT_BUILDERS
    pack = load_business_pack()
    bindings = (pack.get("atomicCheckToolBindingSet") or {}).get("bindings") or pack.get("atomicCheckToolBindings") or []
    binding = next(item for item in bindings if item.get("atomicCheckId") == "AC-R68-01")
    assert "evaluate_r68_blowing_cleaning" in binding["tools"]
    assert "evaluate_blowing_cleaning" not in binding["tools"]
    assert binding["requiredFacts"] == ["r68.blowingCleaning"]
