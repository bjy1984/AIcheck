"""R47／R48／R50／R53／R54／R55：第四批走通"冻结判据"机制的通用解释器规则。

六条原先分别绑 evaluate_static_grounding、evaluate_crossing_structure、
evaluate_corrosion_protection、evaluate_pipe_installation、evaluate_compensator、
evaluate_support_components——这些名字在 business_tools 里都没有实现，落到通用
解释器且 ruleChecks 无人产生，资料再齐也只返回"未配置"的证据不足。

这批判据里数值条款比前几批多，用例重点钉在条文明列的那些数字上。
"""
from copy import deepcopy

import pytest

from libs.review_tools.installation_domain_rules import (
    evaluate_r47_static_grounding,
    evaluate_r48_weld_layout,
    evaluate_r50_sleeve_insulation,
    evaluate_r52_prefabrication,
    evaluate_r53_equipment_connection,
    evaluate_r53_installation_connections,
    evaluate_r54_compensator,
    evaluate_r55_supports,
    frozen_installation_rules,
)

SCOPE = {"projectId": "P", "objectType": "pipeline", "objectId": "PL-1", "recordVersionId": "REC-V1"}
REF = [{"documentVersionId": "REC-V1", "pageNo": 4, "quotedText": "安装记录"}]

CASES = {
    "evaluate_r47_static_grounding": (evaluate_r47_static_grounding, "staticGrounding", {
        "design": {"staticGroundingRequired": True},
        "site": {"highSoilResistivity": False},
        "pipeline": {"stainlessOrNonFerrous": False},
        "installation": {"groundingLocation": "R-3 法兰组", "connectionMethod": "焊接",
                         "matchesDesignDocument": True, "metalFlangeBoltedWithoutBondingWire": False},
        "measurement": {"groundResistanceOhm": 8.4, "maxJointBondingResistanceOhm": 0.012,
                        "designDefaultLimitApplies": True, "bondingResistanceExceeded": False,
                        "resistanceOutOfLimit": False, "testedAfterInstallation": True},
    }),
    "evaluate_r48_weld_layout": (evaluate_r48_weld_layout, "weldLayout", {
        "weldLayout": {"girthWeldSpacingMm": 260, "pipeOuterDiameterMm": 219, "nominalDiameterDn": 200,
                       "spacingMeetsThicknessMultiple": True, "dnAtLeast150": True, "dnBelow150": False,
                       "bendStartDistanceMm": 240, "bendClearanceMeetsOuterDiameter": True,
                       "supportClearanceMm": 90, "postWeldHeatTreatmentRequired": False,
                       "branchOpeningClearanceMm": 120, "branchClearanceMeetsBoreDiameter": True,
                       "openingOnWeld": False, "reinforcementPadPresent": False,
                       "crossWeldOrCloseLongitudinalSeam": False},
        "crossing": {"throughWallRoadOrRail": True, "sleeveInstalled": True,
                     "girthWeldInsideSleeve": False},
    }),
    "evaluate_r50_sleeve_insulation": (evaluate_r50_sleeve_insulation, "sleeveInsulation", {
        "sleeve": {"externalCoatingGrade": "特加强级", "endSealMaterial": "热收缩密封件",
                   "gradeBasedOnSoilCorrosivity": True, "roadRailCrossingOrDepthChangeBend": True,
                   "coatingGradeExtraReinforced": True, "insulatedFromAbovegroundPiping": True,
                   "steelSleeveUsed": True, "insulatingSupportInstalled": True,
                   "endsSealedWithNonConductiveMaterial": True},
    }),
    "evaluate_r53_installation_connections": (evaluate_r53_installation_connections, "installationConnections", {
        "installation": {"connectionMethod": "法兰连接", "recordNo": "IN-2026-19",
                         "noForcedFitUp": True, "spoolCleanedAndCapped": True, "noAdditionalLoad": True,
                         "alloyOrSpecialMaterial": False,
                         "flangeJointPresent": True, "sealingFacesInspected": True,
                         "singleGasketPerPair": True, "flangeParallelismMmPer200mm": 0.4,
                         "noBoltForcingToCorrectDeflection": True, "boltHoleOffsetMm": 1.5,
                         "boltsSameSpecAndFullyEngaged": True, "gc1FlangeJoint": False,
                         "threadedJointPresent": False, "sealWeldedThreadedJoint": False,
                         "tubeFittingPresent": False, "ferruleFittingPresent": False,
                         "stuffingBoxJointPresent": False},
    }),
    "evaluate_r52_prefabrication": (evaluate_r52_prefabrication, "prefabrication", {
        "prefabrication": {"recordNo": "PF-2026-08", "componentType": "热煨弯管",
                           "thermalCuttingUsed": True, "cutSurfaceCleaned": True,
                           "cuttingMethodSuitsMaterial": True, "surfaceDamageRepaired": False,
                           "markingPreservedOrTransferred": True,
                           "lowTemperatureStainlessOrNonFerrous": False,
                           "bendFabricated": True, "notGc1OrSevereCyclic": True,
                           "bendFromWeldedPipe": False,
                           "bendUnderInternalPressure": True, "bendUnderExternalPressure": False,
                           "bendOvalityPercent": 4.2,
                           "wrinkleHeightWithinThreePercentOfDiameter": True,
                           "wavePitchAtLeastTwelveTimesWrinkleHeight": True,
                           "bendFinalThicknessNotBelowDesign": True,
                           "plateWeldedPipeDn400OrAbove": False,
                           "miterBendFabricated": False, "miterBendAboveDn400": False},
    }),
    "evaluate_r53_equipment_connection": (evaluate_r53_equipment_connection, "equipmentConnection", {
        "equipment": {"tagNo": "P-101A", "connectionRecordNo": "EQ-2026-11",
                      "connectedAfterAnchorBoltsTightened": True, "rotatingEquipment": True,
                      "freeStateAlignmentChecked": True, "parallelismWithinTable41": True,
                      "concentricityWithinTable41": True, "dialGaugeMonitoringApplied": True,
                      "ratedSpeedAbove6000": False, "ratedSpeedAtMost6000": True,
                      "displacementMm": 0.03, "largeStorageTankConnection": False,
                      "realignmentCheckedAfterTestAndFlush": True},
    }),
    "evaluate_r54_compensator": (evaluate_r54_compensator, "compensator", {
        "compensator": {"type": "金属波纹膨胀节", "installationRecordNo": "CP-2026-04",
                        "matchesDesignAndProductDocuments": True, "metalBellowsType": True,
                        "flowMarkerMatchesFlowDirection": True,
                        "notUsedToAbsorbInstallationDeviation": True, "bellowsFreeOfDamage": True,
                        "liftingNotAppliedToBellows": True, "pressureTestAfterGuidesAndAnchors": True,
                        "shippingRestraintsRemoved": True, "manufacturerInstructionsFollowed": True,
                        "prestretchRequired": False},
    }),
    "evaluate_r55_supports": (evaluate_r55_supports, "supports", {
        "support": {"type": "滑动支架", "location": "K3+120", "inspectionResult": "合格",
                    "matchesDesignAndProductDocuments": True, "fabricationVisualAccepted": True,
                    "fullPenetrationWeldRequired": True, "fullPenetrationNdtPercent": 25,
                    "fullPenetrationNdtLengthMm": 240, "rustProtectionApplied": True,
                    "positionCorrectAndContactGood": True,
                    "hangerRodVerticalOrOffsetPerDesign": True, "compensatorPresent": False,
                    "uncompensatedStraightRun": False, "springSupportPresent": False,
                    "weldedByQualifiedWelderWithoutDefects": True,
                    "branchFromThermallyMovingMain": False, "guideOrSlidingSupportPresent": True,
                    "slidingFaceCleanWithoutBinding": True,
                    "noTackWeldOrInstrumentBracketOnSlidingSupport": True},
    }),
}


def build(tool_name, overrides=None):
    _fn, domain_name, fields = CASES[tool_name]
    payload = deepcopy(fields)
    for path, value in (overrides or {}).items():
        head, _, tail = path.partition(".")
        payload.setdefault(head, {})
        if value is None:
            payload[head].pop(tail, None)
        else:
            payload[head][tail] = value
    return [{**SCOPE, "domain": domain_name, "applicable": True, "evidenceRefs": deepcopy(REF), **payload}]


def run(tool_name, overrides=None, **extra):
    fn, _domain, _fields = CASES[tool_name]
    arguments = {"projectId": "P", "scope": deepcopy(SCOPE), "domains": build(tool_name, overrides),
                 "standardRules": frozen_installation_rules(tool_name)}
    arguments.update(extra)
    return fn(arguments)


def codes(output, status):
    return {row["code"] for row in output["facts"]["processChecks"] if row["result"] == status}


@pytest.mark.parametrize("tool_name", sorted(CASES))
def test_frozen_rules_declare_source_and_limits(tool_name):
    rules = frozen_installation_rules(tool_name)
    review = rules["sourceReview"]
    assert review["humanVerified"] is False, "不得伪造人工核对"
    assert len(review["limitations"]) >= 3, "来源局限必须写明"
    domain = next(iter(rules["domains"].values()))
    assert all(item["verifiedBy"] is None for item in domain["checks"])
    assert all(item["standardRef"] == "STD-GBT-20801.1-2025" for item in domain["checks"])


@pytest.mark.parametrize("tool_name", sorted(CASES))
def test_complete_record_passes(tool_name):
    output = run(tool_name)
    assert output["result"] == "passed", [row for row in output["facts"]["processChecks"]
                                          if row["result"] not in {"passed", "not_applicable"}]
    assert output["evidenceRefs"]


@pytest.mark.parametrize("tool_name", sorted(CASES))
def test_missing_frozen_rules_never_produce_a_verdict(tool_name):
    fn, _domain, _fields = CASES[tool_name]
    output = fn({"projectId": "P", "scope": deepcopy(SCOPE), "domains": build(tool_name), "standardRules": {}})
    assert output["result"] == "evidence_insufficient"


@pytest.mark.parametrize("tool_name", sorted(CASES))
def test_evidence_must_come_from_the_selected_record_version(tool_name):
    domains = build(tool_name)
    domains[0]["evidenceRefs"] = [{"documentVersionId": "OTHER", "pageNo": 1}]
    fn, _domain, _fields = CASES[tool_name]
    output = fn({"projectId": "P", "scope": deepcopy(SCOPE), "domains": domains,
                 "standardRules": frozen_installation_rules(tool_name)})
    assert output["result"] == "evidence_insufficient"


def test_r47_bonding_resistance_ceiling_is_thirty_milliohm():
    """7.7.13.1：每对接头间的跨接电阻不应大于 0.03Ω。"""
    over = run("evaluate_r47_static_grounding", {"measurement.maxJointBondingResistanceOhm": 0.045})
    assert over["result"] == "failed"
    assert "staticgrounding_joint_bonding_resistance_within_limit" in codes(over, "failed")

    edge = run("evaluate_r47_static_grounding", {"measurement.maxJointBondingResistanceOhm": 0.03})
    assert edge["result"] == "passed", "0.03Ω 本身是'不大于'，属于合格"


def test_r47_ground_resistance_limit_switches_with_soil_resistivity():
    """7.7.13.2 默认 100Ω；G.9.5 山区等高土壤电阻率场所 1000Ω。"""
    plain = run("evaluate_r47_static_grounding", {"measurement.groundResistanceOhm": 260})
    assert plain["result"] == "failed"
    assert "staticgrounding_ground_resistance_within_default_limit" in codes(plain, "failed")

    mountain = run("evaluate_r47_static_grounding",
                   {"measurement.groundResistanceOhm": 260, "site.highSoilResistivity": True,
                    "measurement.designDefaultLimitApplies": False})
    assert mountain["result"] == "passed"
    assert "staticgrounding_ground_resistance_within_high_resistivity_limit" in codes(mountain, "passed")


def test_r47_design_specifying_its_own_limit_is_not_silently_waived():
    """设计另有规定时 100Ω 判据不适用，但不应因此看起来像判过了。"""
    output = run("evaluate_r47_static_grounding", {"measurement.designDefaultLimitApplies": False})
    assert "staticgrounding_ground_resistance_within_default_limit" in codes(output, "not_applicable")

    unknown = run("evaluate_r47_static_grounding", {"measurement.designDefaultLimitApplies": None})
    assert unknown["result"] == "evidence_insufficient"


def test_r47_stainless_pipe_needs_a_same_material_transition_plate():
    output = run("evaluate_r47_static_grounding",
                 {"pipeline.stainlessOrNonFerrous": True, "installation.sameMaterialTransitionPlate": False})
    assert output["result"] == "failed"
    assert "staticgrounding_dissimilar_metal_transition_plate" in codes(output, "failed")


def test_r48_girth_weld_spacing_floor_depends_on_nominal_diameter():
    """7.4.6 a)：DN≥150 时不小于 150 mm。"""
    output = run("evaluate_r48_weld_layout", {"weldLayout.girthWeldSpacingMm": 120})
    assert output["result"] == "failed"
    assert "weldlayout_spacing_ge_150mm_for_large_dn" in codes(output, "failed")

    small = run("evaluate_r48_weld_layout",
                {"weldLayout.girthWeldSpacingMm": 120, "weldLayout.dnAtLeast150": False,
                 "weldLayout.dnBelow150": True, "weldLayout.nominalDiameterDn": 100,
                 "weldLayout.spacingMeetsOuterDiameter": True})
    assert small["result"] == "passed"
    assert "weldlayout_spacing_ge_150mm_for_large_dn" in codes(small, "not_applicable")


def test_r48_opening_on_a_weld_requires_accepted_ndt_first():
    """7.4.6 e)：无法避免在焊缝上开孔时，检测合格后方可开孔。"""
    output = run("evaluate_r48_weld_layout",
                 {"weldLayout.openingOnWeld": True, "weldLayout.openingAreaNdtAccepted": False})
    assert output["result"] == "failed"
    assert "weldlayout_opening_on_weld_ndt_accepted" in codes(output, "failed")


def test_r48_girth_weld_inside_a_sleeve_needs_full_ndt():
    """7.7.1.6：套管内管段如有环焊缝，应 100% 无损检测。"""
    output = run("evaluate_r48_weld_layout",
                 {"crossing.girthWeldInsideSleeve": True,
                  "crossing.sleeveGirthWeldFullNdtAccepted": False})
    assert output["result"] == "failed"
    assert "weldlayout_sleeve_girth_weld_full_ndt" in codes(output, "failed")


def test_r50_steel_sleeve_needs_insulating_support_and_sealed_ends():
    """附录G G.6.7.2 d)：套管间设绝缘支撑，两端以牢固的非导电材料密封。"""
    output = run("evaluate_r50_sleeve_insulation",
                 {"sleeve.insulatingSupportInstalled": False,
                  "sleeve.endsSealedWithNonConductiveMaterial": False})
    assert output["result"] == "failed"
    assert {"sleeveinsulation_insulating_support_between_sleeve_and_pipe",
            "sleeveinsulation_sleeve_ends_nonconductive_seal"} <= codes(output, "failed")

    no_sleeve = run("evaluate_r50_sleeve_insulation",
                    {"sleeve.steelSleeveUsed": False, "sleeve.insulatingSupportInstalled": None,
                     "sleeve.endsSealedWithNonConductiveMaterial": None})
    assert no_sleeve["result"] == "passed"


def test_r50_road_crossing_requires_the_extra_reinforced_grade():
    output = run("evaluate_r50_sleeve_insulation", {"sleeve.coatingGradeExtraReinforced": False})
    assert output["result"] == "failed"
    assert "sleeveinsulation_crossing_coating_grade_extra_reinforced" in codes(output, "failed")


def test_r53_flange_parallelism_and_bolt_hole_offset_have_hard_numbers():
    """7.7.2.3：平行度不大于 1 mm/200 mm；螺栓孔偏移不大于 3 mm。"""
    tilted = run("evaluate_r53_installation_connections",
                 {"installation.flangeParallelismMmPer200mm": 1.8})
    assert tilted["result"] == "failed"
    assert "installationconnections_flange_parallelism_within_limit" in codes(tilted, "failed")

    offset = run("evaluate_r53_installation_connections", {"installation.boltHoleOffsetMm": 4.2})
    assert offset["result"] == "failed"
    assert "installationconnections_bolt_hole_offset_within_limit" in codes(offset, "failed")


def test_r53_gc1_flange_joints_need_an_approved_written_procedure():
    output = run("evaluate_r53_installation_connections",
                 {"installation.gc1FlangeJoint": True,
                  "installation.writtenFlangeProcedureApproved": False})
    assert output["result"] == "failed"
    assert "installationconnections_gc1_flange_joint_written_procedure_approved" in codes(output, "failed")


def test_r53_thread_rules_do_not_apply_to_a_flanged_joint():
    output = run("evaluate_r53_installation_connections")
    assert "installationconnections_thread_compound_suitable_for_service" in codes(output, "not_applicable")

    unknown = run("evaluate_r53_installation_connections", {"installation.threadedJointPresent": None})
    assert unknown["result"] == "evidence_insufficient", "有没有螺纹接头取不到，不能按不适用放过"


def test_r52_bend_ovality_ceiling_depends_on_pressure_direction():
    """7.3.3.4 a) 2)：内压弯管不圆度不大于 8%；外压弯管不大于 3%。"""
    inner = run("evaluate_r52_prefabrication", {"prefabrication.bendOvalityPercent": 9.5})
    assert inner["result"] == "failed"
    assert "prefabrication_internal_pressure_bend_ovality_within_limit" in codes(inner, "failed")

    outer = run("evaluate_r52_prefabrication",
                {"prefabrication.bendUnderInternalPressure": False,
                 "prefabrication.bendUnderExternalPressure": True,
                 "prefabrication.bendOvalityPercent": 4.2})
    assert outer["result"] == "failed", "4.2% 对内压合格，对外压不合格"
    assert "prefabrication_external_pressure_bend_ovality_within_limit" in codes(outer, "failed")


def test_r52_gc1_and_severe_cyclic_service_may_not_use_a_field_bend():
    """7.3.3.1：GC1 级和剧烈循环工况的管道不应采用制作弯管。"""
    output = run("evaluate_r52_prefabrication", {"prefabrication.notGc1OrSevereCyclic": False})
    assert output["result"] == "failed"
    assert "prefabrication_field_bend_not_used_on_gc1_or_severe_cyclic" in codes(output, "failed")


def test_r52_plate_welded_rules_do_not_apply_to_a_bend():
    output = run("evaluate_r52_prefabrication")
    assert output["result"] == "passed"
    assert "prefabrication_plate_welded_shell_course_length" in codes(output, "not_applicable")


def test_r52_plate_welded_pipe_has_several_hard_floors():
    base = {"prefabrication.componentType": "板焊管", "prefabrication.bendFabricated": False,
            "prefabrication.bendUnderInternalPressure": False,
            "prefabrication.bendUnderExternalPressure": False,
            "prefabrication.bendFromWeldedPipe": False,
            "prefabrication.plateWeldedPipeDn400OrAbove": True,
            "prefabrication.shellCourseLengthMm": 420,
            "prefabrication.adjacentCourseSeamOffsetMm": 160,
            "prefabrication.longitudinalSeamSpacingMm": 260,
            "prefabrication.peakValueMm": 3.2, "prefabrication.peakWithinThicknessRule": True,
            "prefabrication.straightnessPercentOfLength": 0.12,
            "prefabrication.misalignmentWithinTable32": True,
            "prefabrication.circumferenceAndDiameterWithinTable31": True}
    assert run("evaluate_r52_prefabrication", base)["result"] == "passed"

    short = run("evaluate_r52_prefabrication", {**base, "prefabrication.shellCourseLengthMm": 240})
    assert short["result"] == "failed"
    assert "prefabrication_plate_welded_shell_course_length" in codes(short, "failed")

    peak = run("evaluate_r52_prefabrication", {**base, "prefabrication.peakValueMm": 6.1})
    assert peak["result"] == "failed"
    assert "prefabrication_plate_welded_peak_within_limit" in codes(peak, "failed")

    bent = run("evaluate_r52_prefabrication", {**base, "prefabrication.straightnessPercentOfLength": 0.35})
    assert bent["result"] == "failed"
    assert "prefabrication_plate_welded_straightness_within_limit" in codes(bent, "failed")


def test_r52_hard_stamp_on_stainless_is_a_nonconformance():
    """7.3.2.2：低温用钢、不锈钢及有色金属不准许使用硬印标记。"""
    output = run("evaluate_r52_prefabrication",
                 {"prefabrication.lowTemperatureStainlessOrNonFerrous": True,
                  "prefabrication.hardStampAvoided": False})
    assert output["result"] == "failed"
    assert "prefabrication_no_hard_stamp_on_restricted_material" in codes(output, "failed")


def test_r53_equipment_connection_must_follow_anchor_bolt_tightening():
    """7.7.6.1：管道与设备的连接应在设备安装定位并紧固地脚螺栓后进行。"""
    output = run("evaluate_r53_equipment_connection",
                 {"equipment.connectedAfterAnchorBoltsTightened": False})
    assert output["result"] == "failed"
    assert "equipmentconnection_connected_after_equipment_anchored" in codes(output, "failed")


def test_r53_displacement_ceiling_switches_with_rated_speed():
    """7.7.6.2 b)：>6000 r/min 小于 0.02 mm；≤6000 r/min 小于 0.05 mm。"""
    normal = run("evaluate_r53_equipment_connection", {"equipment.displacementMm": 0.03})
    assert normal["result"] == "passed"
    assert "equipmentconnection_displacement_below_high_speed_limit" in codes(normal, "not_applicable")

    fast = run("evaluate_r53_equipment_connection",
               {"equipment.ratedSpeedAbove6000": True, "equipment.ratedSpeedAtMost6000": False,
                "equipment.displacementMm": 0.03})
    assert fast["result"] == "failed"
    assert "equipmentconnection_displacement_below_high_speed_limit" in codes(fast, "failed")


def test_r53_static_equipment_does_not_inherit_rotating_equipment_rules():
    output = run("evaluate_r53_equipment_connection",
                 {"equipment.rotatingEquipment": False, "equipment.freeStateAlignmentChecked": None,
                  "equipment.parallelismWithinTable41": None, "equipment.concentricityWithinTable41": None,
                  "equipment.dialGaugeMonitoringApplied": None,
                  "equipment.realignmentCheckedAfterTestAndFlush": None,
                  "equipment.ratedSpeedAtMost6000": False, "equipment.displacementMm": None})
    assert output["result"] == "passed"
    assert "equipmentconnection_parallelism_within_table41" in codes(output, "not_applicable")


def test_r53_realignment_must_be_rechecked_after_test_and_flush():
    """7.7.6.4：试压、吹扫与清洗合格后应对接口进行复位检查。"""
    output = run("evaluate_r53_equipment_connection",
                 {"equipment.realignmentCheckedAfterTestAndFlush": False})
    assert output["result"] == "failed"
    assert "equipmentconnection_realignment_checked_after_test_and_flush" in codes(output, "failed")


def test_r54_pressure_test_before_guides_are_installed_is_a_nonconformance():
    """附录P P.4 e)：导向与固定支架正确安装完毕前不应进行压力试验或抽真空。"""
    output = run("evaluate_r54_compensator", {"compensator.pressureTestAfterGuidesAndAnchors": False})
    assert output["result"] == "failed"
    assert "compensator_pressure_test_after_guides_and_anchors" in codes(output, "failed")


def test_r54_bellows_must_not_be_used_to_absorb_installation_deviation():
    output = run("evaluate_r54_compensator", {"compensator.notUsedToAbsorbInstallationDeviation": False})
    assert output["result"] == "failed"
    assert "compensator_not_used_to_absorb_installation_deviation" in codes(output, "failed")


def test_r54_bellows_rules_do_not_apply_to_a_non_bellows_compensator():
    output = run("evaluate_r54_compensator",
                 {"compensator.metalBellowsType": False, "compensator.type": "方形补偿器",
                  "compensator.flowMarkerMatchesFlowDirection": None,
                  "compensator.notUsedToAbsorbInstallationDeviation": None,
                  "compensator.bellowsFreeOfDamage": None, "compensator.liftingNotAppliedToBellows": None,
                  "compensator.pressureTestAfterGuidesAndAnchors": None,
                  "compensator.shippingRestraintsRemoved": None,
                  "compensator.manufacturerInstructionsFollowed": None})
    assert output["result"] == "passed"
    assert "compensator_flow_marker_matches_flow_direction" in codes(output, "not_applicable")


def test_r55_full_penetration_weld_sampling_has_two_floors():
    """7.3.8.3：检测数量不少于 20%，且焊缝长度不小于 200 mm。两个下限都要满足。"""
    ratio = run("evaluate_r55_supports", {"support.fullPenetrationNdtPercent": 10})
    assert ratio["result"] == "failed"
    assert "supports_full_penetration_weld_ndt_ratio" in codes(ratio, "failed")

    length = run("evaluate_r55_supports", {"support.fullPenetrationNdtLengthMm": 120})
    assert length["result"] == "failed"
    assert "supports_full_penetration_weld_ndt_length" in codes(length, "failed")


def test_r55_uncompensated_straight_run_may_carry_only_one_anchor():
    output = run("evaluate_r55_supports",
                 {"support.uncompensatedStraightRun": True, "support.singleAnchorOnStraightRun": False})
    assert output["result"] == "failed"
    assert "supports_single_anchor_on_uncompensated_straight_run" in codes(output, "failed")


def test_r55_spring_restraints_must_be_removed_at_the_right_time():
    """7.7.12.5：临时固定件应待系统安装、试压、隔热完毕后，在试车前拆除。"""
    output = run("evaluate_r55_supports",
                 {"support.springSupportPresent": True, "support.springHeightAdjustedPerDesign": True,
                  "support.temporaryRestraintRemovedAfterInsulationAndTest": False})
    assert output["result"] == "failed"
    assert "supports_spring_temporary_restraint_removed_at_right_time" in codes(output, "failed")


def test_r55_missing_required_item_is_a_nonconformance_not_missing_evidence():
    output = run("evaluate_r55_supports", {"support.location": None})
    assert output["result"] == "failed"
    assert "supports_support_location" in codes(output, "failed")


def test_bindings_and_registration_point_at_the_dedicated_tools():
    from libs.business_pack.loader import load_business_pack
    from libs.review_orchestrator.ndt_fact_builders import NDT_FACT_BUILDERS
    from libs.review_tools.business_tools import BUSINESS_TOOL_NAMES

    pack = load_business_pack()
    bindings = (pack.get("atomicCheckToolBindingSet") or {}).get("bindings") or pack.get("atomicCheckToolBindings") or []
    for check_id, tool_name, node_id, fact in (
        ("AC-R47-01", "evaluate_r47_static_grounding", 47, "r47.staticGrounding"),
        ("AC-R48-01", "evaluate_r48_weld_layout", 48, "r48.weldLayout"),
        ("AC-R50-01", "evaluate_r50_sleeve_insulation", 50, "r50.sleeveInsulation"),
        ("AC-R52-01", "evaluate_r52_prefabrication", 52, "r52.prefabrication"),
        ("AC-R53-01", "evaluate_r53_installation_connections", 53, "r53.installationConnections"),
        ("AC-R53-02", "evaluate_r53_equipment_connection", 53, "r53.equipmentConnection"),
        ("AC-R54-01", "evaluate_r54_compensator", 54, "r54.compensator"),
        ("AC-R55-01", "evaluate_r55_supports", 55, "r55.supports"),
    ):
        assert tool_name in BUSINESS_TOOL_NAMES
        assert node_id in NDT_FACT_BUILDERS
        binding = next(item for item in bindings if item.get("atomicCheckId") == check_id)
        assert tool_name in binding["tools"]
        assert binding["requiredFacts"] == [fact]
