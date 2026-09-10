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
    evaluate_r56_accessory_documents,
    evaluate_r56_accessory_installation,
    evaluate_r57_safety_valve_calibration,
    evaluate_r58_emergency_valve_test,
    evaluate_r46_cathodic_protection,
    evaluate_r10_comparison_table,
    evaluate_r10_compliance_declaration,
    evaluate_r10_standard_adoption,
    evaluate_r43_material_certificate,
    evaluate_r44_coating_construction,
    evaluate_r47_static_grounding,
    evaluate_r48_weld_layout,
    evaluate_r49_crossing_construction,
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
    "evaluate_r10_standard_adoption": (evaluate_r10_standard_adoption, "alternativeStandardAdoption", {
        "design": {"adoptedStandardType": "境外标准 ASME B31.3",
                   "designBasisDocumentNo": "DS-2026-01",
                   "designBasisRecordsStandards": True,
                   "adoptionConclusionConsistentWithClause19": True,
                   "stationProcessPiping": False, "designedToGb34275": False},
    }),
    "evaluate_r10_compliance_declaration": (evaluate_r10_compliance_declaration, "complianceDeclaration", {
        "declaration": {"alternativeStandardAdopted": True,
                        "declarationPresent": True, "comparisonTablePresent": True,
                        "carriedInDesignOrEngineeringSpecification": True},
    }),
    "evaluate_r10_comparison_table": (evaluate_r10_comparison_table, "comparisonTableCoverage", {
        "comparisonTable": {"documentNo": "CT-2026-01", "alternativeStandardAdopted": True,
                            "coveredSafetyTopics": ["2.1.1", "2.2.2", "2.4", "2.5", "1.10", "3.1.6",
                                                    "3.2.1", "3.1.4.1", "3.2.4", "4.3.1", "4.2.8",
                                                    "4.4.2", "4.4.3", "4.5", "4.5.6"],
                            "everyRowHasConformityStatement": True,
                            "standardAndActualColumnsFilled": True,
                            "hasNonConformingItems": False},
    }),
    "evaluate_r43_material_certificate": (evaluate_r43_material_certificate, "materialCertificate", {
        "certificate": {"documentNo": "MC-2026-77", "materialGrade": "20#",
                        "certificatesAndMarksReviewed": True, "gradeMatchesSpecification": True,
                        "requiredProcessingAndTestsEvidenced": True,
                        "complianceStatementSubmitted": True},
    }),
    "evaluate_r44_coating_construction": (evaluate_r44_coating_construction, "coatingConstruction", {
        "coating": {"recordNo": "CT-2026-31", "coatingType": "三层PE",
                    "prefabCoatingCheckedBeforeFitUp": True, "prefabCoatingDefectFound": False,
                    "fieldJointOrRepairPresent": True, "selfInspectionCompleted": True,
                    "thicknessMeasuredAtFourPositions": True, "thicknessMeetsDesign": True,
                    "holidayTestCoveragePercent": 100, "noHolidayRemaining": True,
                    "adhesionTestedAndAccepted": True,
                    "backfillCompleted": True, "fullLineHolidaySurveyCompleted": True,
                    "directionalDrillingCrossing": False, "resistivityBelowThreshold": False,
                    "qualityDocumentsHandedOver": True, "manufacturerDocumentsTraceable": True},
    }),
    "evaluate_r56_accessory_documents": (evaluate_r56_accessory_documents, "safetyAccessoryDocuments", {
        "accessory": {"accessoryType": "安全阀", "model": "A48Y-16C", "manufacturer": "某阀门厂",
                      "typeTestPassed": True, "withinTypeTestCoverage": True,
                      "standardWithinAnnexB": True, "standardOutsideAnnexB": False,
                      "shipmentDocuments": ["产品合格证", "产品质量证明书", "使用说明书"],
                      "certificateSignedByQualityEngineer": True,
                      "certificateStatesManufacturerAndLicenceNo": True,
                      "certificateItemsCompleteForType": True,
                      "nameplateShowsLicenceNumber": True,
                      "materialCertificateTraceableAndStamped": True,
                      "materialFromNonManufacturer": False},
    }),
    "evaluate_r56_accessory_installation": (evaluate_r56_accessory_installation, "safetyAccessoryInstallation", {
        "installation": {"accessoryType": "安全阀", "tagNo": "PSV-101", "location": "V-101 顶部",
                         "modelAndSizeMatchDesign": True, "reliefDevice": True,
                         "totalReliefCapacityMeetsSystem": True,
                         "flowAreaNotLessThanPort": True,
                         "positionAllowsReliefAndMaintenance": True,
                         "nameplateLegibleOnSite": True,
                         "safetyValve": True, "mountedVertically": True,
                         "connectionMatchesMediumPhase": True, "inletPressureLossPercent": 1.4,
                         "outletNotObstructed": True, "isolationValvePresent": False,
                         "ruptureDisc": False, "emergencyValve": False,
                         "pullOffTypeValve": False, "solenoidTypeValve": False},
    }),
    "evaluate_r57_safety_valve_calibration": (evaluate_r57_safety_valve_calibration, "safetyValveCalibration", {
        "report": {"reportNo": "SV-2026-08", "setPressureMpa": 1.6,
                   "calibrationDate": "2026-06-01", "nextCalibrationDate": "2028-06-01",
                   "calibrationIntervalYears": 2, "problemsFoundInService": False,
                   "mediumMatchesService": True, "onlineCalibration": False,
                   "offlineCalibration": True, "macroInspectionAndDisassemblyDone": True,
                   "damagedPartsFound": False, "setPressureTestCount": 3,
                   "allSetPressureResultsAccepted": True, "nameplateRangeMarked": True,
                   "setPressureWithinNameplateRange": True, "pilotOperatedValve": False,
                   "powerAssistedValve": False, "setPressureAbove42Mpa": False,
                   "sealTestAccepted": True, "conclusion": "合格",
                   "signedByCalibratorAndApprover": True,
                   "recordedItems": ["使用单位", "制造单位", "安全阀型号", "产品编号",
                                      "被保护设备种类", "工作介质", "整定压力", "密封试验压力",
                                      "校验介质", "校验方式", "校验结论", "校验日期", "下次校验日期"]},
    }),
    "evaluate_r58_emergency_valve_test": (evaluate_r58_emergency_valve_test, "emergencyValveTest", {
        "report": {"reportNo": "EV-2026-03", "valveModel": "QDF-50", "cutOffType": "过流切断型",
                   "testedItems": ["壳体强度试验", "内密封试验", "紧急切断性能试验"],
                   "externalSealTestApplicable": False, "cutOffPressureAccuracyApplicable": False,
                   "multiFunctionValve": False, "acceptedBeforeShipment": True,
                   "certificateSignedAndStamped": True,
                   "firstProductionOrRestartAfterOneYear": False,
                   "inService": True, "periodicSelfCheckPerformed": True,
                   "annualCheckDue": False, "abnormalConditionFound": False,
                   "conclusion": "合格",
                   "certificateItems": ["产品型号", "公称压力", "公称尺寸", "最高工作压力",
                                         "制造日期", "产品编号或批号", "设计制造标准", "适用温度",
                                         "适用介质", "切断型式或切断功能", "切断功能的性能参数",
                                         "阀体阀盖和密封面材料"],
                   "nameplateItems": ["特种设备生产许可证编号", "制造单位名称或商标", "产品型号",
                                       "公称压力", "公称尺寸", "最高工作压力", "制造日期",
                                       "产品编号或批号", "设计制造标准", "切断型式或切断功能"]},
    }),
    "evaluate_r46_cathodic_protection": (evaluate_r46_cathodic_protection, "cathodicProtection", {
        "cathodicProtection": {"deviceType": "牺牲阳极", "recordNo": "CP-2026-12",
                               "insulationDeviceInstalled": True, "insulationResistanceMohm": 46,
                               "insulationTestConditionsMet": True,
                               "insulationVerifiedAfterInstallation": True,
                               "insulatingFlangeUsed": False, "conductiveMediumPipeline": False,
                               "sacrificialAnodeUsed": True, "backfillFullyEncasesAnode": True,
                               "anodeCableSound": True, "baggedAnodeUsed": True,
                               "baggedAnodeKeptDry": True, "anodeCentredAndTamped": True,
                               "braceletAnodeUsed": False, "impressedCurrentUsed": False,
                               "handoverInspectionCompleted": True,
                               "handoverDocumentTypes": ["实际施工图和竣工图", "设计变更文件",
                                                          "产品和设备技术文件", "安装施工记录",
                                                          "调试试验记录", "隐蔽工程记录"],
                               "asBuiltDeviationsMarked": True,
                               "installationRecordItems": ["安装位置", "投产日期",
                                                            "阳极数量类型尺寸深度填料及间距",
                                                            "电缆规格和绝缘类型"]},
    }),
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
    "evaluate_r49_crossing_construction": (evaluate_r49_crossing_construction, "crossingConstruction", {
        "crossing": {"location": "K2+430 穿越厂区道路", "recordNo": "CR-2026-05",
                     "throughRoadWallFloorOrStructure": True, "sleeveOrCulvertInstalled": True,
                     "sleeveInstalled": True, "noWeldInsideSleeve": True,
                     "throughWall": False, "throughFloor": False, "throughRoof": False,
                     "annulusFilledWithHarmlessIncombustible": True,
                     "buriedSection": True, "coatingAppliedBeforeInstallation": True,
                     "coatingUndamagedAtInstallation": True,
                     "foundationAcceptedBeforeInstallation": True,
                     "backfillAfterTestAndCoatingAccepted": True,
                     "concealedWorkRecordFiled": True, "installationRecordFiled": True},
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
    expected_ref = {"evaluate_r49_crossing_construction": "STD-GB-50235-2010",
                    "evaluate_r44_coating_construction": "STD-GBT-19285-2026",
                    "evaluate_r10_standard_adoption": "STD-TSG-31-2025",
                    "evaluate_r10_compliance_declaration": "STD-TSG-31-2025",
                    "evaluate_r10_comparison_table": "STD-TSG-31-2025",
                    "evaluate_r46_cathodic_protection": "STD-GBT-33378-2025",
                    "evaluate_r57_safety_valve_calibration": "STD-TSG-92-2026",
                    "evaluate_r58_emergency_valve_test": "STD-TSG-92-2026",
                    "evaluate_r56_accessory_documents": "STD-TSG-92-2026",
                    "evaluate_r56_accessory_installation": "STD-TSG-92-2026"}.get(
        tool_name, "STD-GBT-20801.1-2025")
    assert all(item["standardRef"] == expected_ref for item in domain["checks"])


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


def test_r10_comparison_table_must_cover_every_annex_b_row():
    """TSG 31-2025 附件B 有 15 个行目。少一行就是覆盖不全，不是"大致齐全"。"""
    full = run("evaluate_r10_comparison_table")
    assert full["result"] == "passed", full["facts"]["processChecks"]

    missing = run("evaluate_r10_comparison_table",
                  {"comparisonTable.coveredSafetyTopics": ["2.1.1", "2.2.2", "3.1.6", "4.5"]})
    assert missing["result"] == "failed"
    assert "comparisontablecoverage_covers_all_annex_b_items" in codes(missing, "failed")


def test_r10_nonconforming_rows_must_be_handled_under_clause_1_9():
    output = run("evaluate_r10_comparison_table",
                 {"comparisonTable.hasNonConformingItems": True,
                  "comparisonTable.nonConformingItemsHandled": False})
    assert output["result"] == "failed"
    assert "comparisontablecoverage_nonconforming_items_handled_per_clause_1_9" in codes(output, "failed")


def test_r10_declaration_and_table_are_both_required_when_another_standard_is_used():
    """1.9(3)：符合性申明**及**比照表，两者都要。只有申明不算数。"""
    output = run("evaluate_r10_compliance_declaration",
                 {"declaration.comparisonTablePresent": False})
    assert output["result"] == "failed"
    assert "compliancedeclaration_comparison_table_present" in codes(output, "failed")


def test_r10_declaration_rules_do_not_apply_when_no_other_standard_is_used():
    """没采用其他标准时整域不适用——本域没有无条件必需项，不能把"不适用"判成"该写没写"。"""
    output = run("evaluate_r10_compliance_declaration",
                 {"declaration.alternativeStandardAdopted": False,
                  "declaration.declarationPresent": None,
                  "declaration.comparisonTablePresent": None,
                  "declaration.carriedInDesignOrEngineeringSpecification": None})
    assert output["result"] == "not_applicable"
    assert codes(output, "failed") == set()

    unknown = run("evaluate_r10_compliance_declaration",
                  {"declaration.alternativeStandardAdopted": None})
    assert unknown["result"] == "evidence_insufficient", "采用与否不明，不能按不适用放过"


def test_r10_station_piping_rule_only_applies_to_station_process_piping():
    output = run("evaluate_r10_standard_adoption")
    assert "alternativestandardadoption_station_piping_uses_permitted_standard" in codes(output, "not_applicable")

    station = run("evaluate_r10_standard_adoption",
                  {"design.stationProcessPiping": True, "design.stationStandardPermitted": False})
    assert station["result"] == "failed"


def test_r10_records_that_the_registered_clause_number_should_be_corrected():
    """规则包登记的是 3.1.3.1（只管境外标准），实际依据是 1.9(3)（采用其他标准）。"""
    review = frozen_installation_rules("evaluate_r10_standard_adoption")["sourceReview"]
    assert any("1.9(3)" in text for text in review["limitations"])


def test_r43_only_uses_the_clause_whose_text_was_actually_verified():
    """规则包为 R43 登记的 GB/T 19285-2026 4.2、5.1 是管段划分与建设期检验一般规定，

    与"材料质量证明文件"对不上。判据只从核到的 8.5 来，挂错的事写在局限里，不凭印象补。
    """
    rules = frozen_installation_rules("evaluate_r43_material_certificate")
    assert [doc["clauseNo"] for doc in rules["sourceReview"]["documents"]] == ["8.5"]
    assert any("挂错" in text for text in rules["sourceReview"]["limitations"])
    assert any("型式试验" in text for text in rules["sourceReview"]["limitations"]), \
        "绑定声明了却无条款支撑的事实，必须说明未生成判据"


def test_r43_material_grade_mismatch_is_a_nonconformance():
    output = run("evaluate_r43_material_certificate", {"certificate.gradeMatchesSpecification": False})
    assert output["result"] == "failed"
    assert "materialcertificate_material_grade_matches_specification" in codes(output, "failed")


def test_r44_field_joints_need_full_holiday_coverage_and_no_remaining_holiday():
    """GB/T 19285-2026 5.3.2.2 c)：补伤补口区 100% 漏点检测，且不应有漏点。"""
    partial = run("evaluate_r44_coating_construction", {"coating.holidayTestCoveragePercent": 80})
    assert partial["result"] == "failed"
    assert "coatingconstruction_field_joint_holiday_test_full_coverage" in codes(partial, "failed")

    remaining = run("evaluate_r44_coating_construction", {"coating.noHolidayRemaining": False})
    assert remaining["result"] == "failed"
    assert "coatingconstruction_field_joint_no_holiday_remaining" in codes(remaining, "failed")


def test_r44_directional_drilling_resistivity_floor_and_timing():
    """5.3.3：电阻率不小于 5000 Ω·m²，且在穿越完成 15 d 后、未与其他管段连接前检测。"""
    base = {"coating.directionalDrillingCrossing": True,
            "coating.coatingResistivityOhmM2": 6400,
            "coating.resistivityTestedAfterFifteenDaysBeforeTieIn": True}
    assert run("evaluate_r44_coating_construction", base)["result"] == "passed"

    low = run("evaluate_r44_coating_construction",
              {**base, "coating.coatingResistivityOhmM2": 3200,
               "coating.resistivityBelowThreshold": True,
               "coating.extraCathodicProtectionApplied": False})
    assert low["result"] == "failed"
    assert {"coatingconstruction_directional_drilling_coating_resistivity",
            "coatingconstruction_insufficient_resistivity_triggers_extra_cathodic_protection"} <= codes(low, "failed")

    early = run("evaluate_r44_coating_construction",
                {**base, "coating.resistivityTestedAfterFifteenDaysBeforeTieIn": False})
    assert early["result"] == "failed"
    assert "coatingconstruction_directional_drilling_resistivity_timing" in codes(early, "failed")


def test_r44_resistivity_rules_do_not_apply_without_a_directional_drilling_crossing():
    output = run("evaluate_r44_coating_construction")
    assert output["result"] == "passed"
    assert "coatingconstruction_directional_drilling_coating_resistivity" in codes(output, "not_applicable")


def test_r44_admits_that_insulation_has_no_clause_behind_it():
    """节点名含"保温"，但 5.3.2~5.3.4 没有保温条文——不能装作判了。"""
    review = frozen_installation_rules("evaluate_r44_coating_construction")["sourceReview"]
    assert any("保温" in text for text in review["limitations"])


def test_r56_a_type_test_certificate_alone_is_not_enough():
    """TSG 92-2026 4.1：未经型式试验合格**或者超过证书覆盖范围**的产品都不应出厂。

    有证书不等于这个规格被覆盖——只核"有没有证书"正是把局部检查当成完整结论。
    """
    uncovered = run("evaluate_r56_accessory_documents", {"accessory.withinTypeTestCoverage": False})
    assert uncovered["result"] == "failed"
    assert "safetyaccessorydocuments_within_type_test_certificate_coverage" in codes(uncovered, "failed")

    unknown = run("evaluate_r56_accessory_documents", {"accessory.withinTypeTestCoverage": None})
    assert unknown["result"] == "evidence_insufficient", "覆盖范围取不到，不能当成覆盖了"


def test_r56_shipment_documents_must_cover_all_three_kinds():
    """3.3.4.2(1)：至少提供产品合格证、产品质量证明书、使用说明书。"""
    output = run("evaluate_r56_accessory_documents",
                 {"accessory.shipmentDocuments": ["产品合格证"]})
    assert output["result"] == "failed"
    assert "safetyaccessorydocuments_shipment_documents_complete" in codes(output, "failed")


def test_r56_standard_outside_annex_b_needs_a_comparison_table():
    output = run("evaluate_r56_accessory_documents")
    assert "safetyaccessorydocuments_comparison_table_when_outside_annex_b" in codes(output, "not_applicable")

    outside = run("evaluate_r56_accessory_documents",
                  {"accessory.standardWithinAnnexB": False, "accessory.standardOutsideAnnexB": True,
                   "accessory.comparisonTableProvided": False})
    assert outside["result"] == "failed"
    assert {"safetyaccessorydocuments_product_standard_within_annex_b",
            "safetyaccessorydocuments_comparison_table_when_outside_annex_b"} <= codes(outside, "failed")


def test_r56_safety_valve_inlet_pressure_loss_ceiling_is_three_percent():
    """附件D D4.2(7)：入口端压力损失之和不得高于整定压力的 3%。"""
    output = run("evaluate_r56_accessory_installation",
                 {"installation.inletPressureLossPercent": 4.5})
    assert output["result"] == "failed"
    assert "safetyaccessoryinstallation_safety_valve_inlet_pressure_loss_within_three_percent" in codes(output, "failed")


def test_r56_rupture_disc_rules_do_not_apply_to_a_safety_valve():
    output = run("evaluate_r56_accessory_installation")
    assert output["result"] == "passed", [row for row in output["facts"]["processChecks"]
                                          if row["result"] not in {"passed", "not_applicable"}]
    assert "safetyaccessoryinstallation_rupture_disc_no_added_gasket_or_rework" in codes(output, "not_applicable")


def test_r56_rupture_disc_installation_faults_are_nonconformances():
    base = {"installation.accessoryType": "爆破片装置", "installation.safetyValve": False,
            "installation.ruptureDisc": True,
            "installation.mountedVertically": None, "installation.connectionMatchesMediumPhase": None,
            "installation.inletPressureLossPercent": None, "installation.outletNotObstructed": None,
            "installation.discUndamagedBeforeInstallation": True,
            "installation.discDirectionCorrectAndDischargeClear": True,
            "installation.discNameplateVisible": True,
            "installation.noAddedGasketOrRework": True,
            "installation.dischargePipeCoaxial": True}
    assert run("evaluate_r56_accessory_installation", base)["result"] == "passed"

    gasket = run("evaluate_r56_accessory_installation", {**base, "installation.noAddedGasketOrRework": False})
    assert gasket["result"] == "failed"
    assert "safetyaccessoryinstallation_rupture_disc_no_added_gasket_or_rework" in codes(gasket, "failed")


def test_r56_accessory_type_unknown_stays_insufficient():
    """类型取不到值时不按不适用放过。"""
    output = run("evaluate_r56_accessory_installation", {"installation.safetyValve": None})
    assert output["result"] == "evidence_insufficient"


def test_r57_calibration_interval_may_not_exceed_five_years():
    """TSG 92-2026 附件D D5.2.3.2.2：安全阀最长校验周期不应当超过 5 年。"""
    over = run("evaluate_r57_safety_valve_calibration", {"report.calibrationIntervalYears": 6})
    assert over["result"] == "failed"
    assert "safetyvalvecalibration_calibration_interval_within_five_years" in codes(over, "failed")

    edge = run("evaluate_r57_safety_valve_calibration", {"report.calibrationIntervalYears": 5})
    assert edge["result"] == "passed", "正好 5 年是'不超过'，属于合格"


def test_r57_set_pressure_needs_three_repeat_tests_all_accepted():
    """D5.2.6.2.2(1)：再进行 3 次重复性试验，3 次结果均应符合产品标准。"""
    fewer = run("evaluate_r57_safety_valve_calibration", {"report.setPressureTestCount": 2})
    assert fewer["result"] == "failed"
    assert "safetyvalvecalibration_set_pressure_repeated_three_times" in codes(fewer, "failed")

    partial = run("evaluate_r57_safety_valve_calibration", {"report.allSetPressureResultsAccepted": False})
    assert partial["result"] == "failed"
    assert "safetyvalvecalibration_all_three_results_meet_product_standard" in codes(partial, "failed")


def test_r57_online_calibration_needs_a_stated_reason():
    """D5.2.6.1：一般应离线校验，在线校验只在三种情形下允许。"""
    output = run("evaluate_r57_safety_valve_calibration",
                 {"report.onlineCalibration": True, "report.offlineCalibration": False,
                  "report.onlineCalibrationJustified": False,
                  "report.macroInspectionAndDisassemblyDone": None})
    assert output["result"] == "failed"
    assert "safetyvalvecalibration_online_calibration_only_when_permitted" in codes(output, "failed")


def test_r57_high_pressure_valve_rule_only_applies_above_42mpa():
    output = run("evaluate_r57_safety_valve_calibration")
    assert "safetyvalvecalibration_high_pressure_valve_uses_gbt32291" in codes(output, "not_applicable")

    high = run("evaluate_r57_safety_valve_calibration",
               {"report.setPressureAbove42Mpa": True, "report.testedPerGbt32291": False})
    assert high["result"] == "failed"


def test_r57_report_missing_next_calibration_date_is_a_nonconformance():
    output = run("evaluate_r57_safety_valve_calibration", {"report.nextCalibrationDate": None})
    assert output["result"] == "failed"
    assert "safetyvalvecalibration_report_nextcalibrationdate" in codes(output, "failed")


def test_r58_factory_test_items_must_all_be_present():
    """附件F F3.3.1：出厂检验项目至少包括壳体强度、内密封、紧急切断性能三项。"""
    output = run("evaluate_r58_emergency_valve_test",
                 {"report.testedItems": ["壳体强度试验", "内密封试验"]})
    assert output["result"] == "failed"
    assert "emergencyvalvetest_factory_test_items_complete" in codes(output, "failed")


def test_r58_multifunction_valve_must_have_every_function_tested():
    output = run("evaluate_r58_emergency_valve_test",
                 {"report.multiFunctionValve": True, "report.everyFunctionTested": False})
    assert output["result"] == "failed"
    assert "emergencyvalvetest_every_function_tested_on_multifunction_valve" in codes(output, "failed")


def test_r58_abnormal_condition_must_stop_use():
    """F5.3：出现阀体损坏、密封面损坏等情况应停止使用并立即修理或更换。"""
    output = run("evaluate_r58_emergency_valve_test",
                 {"report.abnormalConditionFound": True,
                  "report.stoppedAndRepairedOrReplaced": False})
    assert output["result"] == "failed"
    assert "emergencyvalvetest_abnormal_condition_stops_use" in codes(output, "failed")


def test_r58_certificate_missing_a_required_item_is_a_nonconformance():
    output = run("evaluate_r58_emergency_valve_test",
                 {"report.certificateItems": ["产品型号", "公称压力"]})
    assert output["result"] == "failed"
    assert "emergencyvalvetest_certificate_items_complete" in codes(output, "failed")


def test_tsg92_rules_admit_the_clause_status_was_not_upgraded():
    """入库文本核对不等于原件比对，条款核验状态未改写，必须写明。"""
    for tool in ("evaluate_r57_safety_valve_calibration", "evaluate_r58_emergency_valve_test"):
        review = frozen_installation_rules(tool)["sourceReview"]
        assert review["documents"][0]["locatorVerification"] == "visual_verified"
        assert any("visual_verified" in text for text in review["limitations"])
        assert any("OCR" in text for text in review["limitations"])


def test_r46_insulation_resistance_must_exceed_ten_megohm():
    """GB/T 33378-2025 6.3.2.1：绝缘装置两侧电阻值应大于 10 MΩ。"""
    low = run("evaluate_r46_cathodic_protection", {"cathodicProtection.insulationResistanceMohm": 6})
    assert low["result"] == "failed"
    assert "cathodicprotection_insulation_resistance_above_ten_megohm" in codes(low, "failed")

    edge = run("evaluate_r46_cathodic_protection", {"cathodicProtection.insulationResistanceMohm": 10})
    assert edge["result"] == "failed", "条文是'大于 10 MΩ'，正好 10 不算合格"


def test_r46_test_conditions_are_judged_separately_from_the_reading():
    """读数达标不代表测试条件对：安装前、干燥空气、1 kV 摇表是另一件事。"""
    output = run("evaluate_r46_cathodic_protection",
                 {"cathodicProtection.insulationTestConditionsMet": False})
    assert output["result"] == "failed"
    assert "cathodicprotection_insulation_test_conditions_met" in codes(output, "failed")


def test_r46_impressed_current_rules_do_not_apply_to_a_sacrificial_anode_system():
    output = run("evaluate_r46_cathodic_protection")
    assert output["result"] == "passed", [row for row in output["facts"]["processChecks"]
                                          if row["result"] not in {"passed", "not_applicable"}]
    assert "cathodicprotection_power_supply_rating_matches_design" in codes(output, "not_applicable")


def test_r46_handover_documents_must_cover_all_six_kinds():
    """6.9.2 a)~f) 是六类，缺一类就是资料不全。"""
    output = run("evaluate_r46_cathodic_protection",
                 {"cathodicProtection.handoverDocumentTypes": ["实际施工图和竣工图", "安装施工记录"]})
    assert output["result"] == "failed"
    assert "cathodicprotection_handover_documents_complete" in codes(output, "failed")


def test_r46_records_that_potential_and_protection_ratio_are_out_of_scope():
    """保护电位、极化时间与保护率大于 90% 不在本节点登记的条款范围，不能装作判了。"""
    review = frozen_installation_rules("evaluate_r46_cathodic_protection")["sourceReview"]
    assert any("90%" in text for text in review["limitations"])
    assert any("GB/T 21448-2017" in text for text in review["limitations"])


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


def test_r49_weld_inside_a_sleeve_is_a_nonconformance():
    """GB 50235-2010 7.1.5-1：管道焊缝不应设置在套管内。"""
    output = run("evaluate_r49_crossing_construction", {"crossing.noWeldInsideSleeve": False})
    assert output["result"] == "failed"
    assert "crossingconstruction_no_weld_inside_sleeve" in codes(output, "failed")


def test_r49_floor_sleeve_must_stand_fifty_millimetres_above_the_floor():
    """7.1.5-3：穿过楼板的套管应高出楼面 50 mm。"""
    low = run("evaluate_r49_crossing_construction",
              {"crossing.throughFloor": True, "crossing.sleeveHeightAboveFloorMm": 20})
    assert low["result"] == "failed"
    assert "crossingconstruction_floor_sleeve_height_above_floor" in codes(low, "failed")

    ok = run("evaluate_r49_crossing_construction",
             {"crossing.throughFloor": True, "crossing.sleeveHeightAboveFloorMm": 50})
    assert ok["result"] == "passed", "刚好 50 mm 属于合格"


def test_r49_wall_and_roof_rules_do_not_apply_to_a_road_crossing():
    output = run("evaluate_r49_crossing_construction")
    assert output["result"] == "passed"
    assert {"crossingconstruction_wall_sleeve_length_covers_wall",
            "crossingconstruction_roof_crossing_flashing_and_cap"} <= codes(output, "not_applicable")


def test_r49_buried_backfill_before_the_tests_pass_is_a_nonconformance():
    """7.1.11：试压、防腐检验合格后才回填。"""
    output = run("evaluate_r49_crossing_construction",
                 {"crossing.backfillAfterTestAndCoatingAccepted": False})
    assert output["result"] == "failed"
    assert "crossingconstruction_buried_backfill_after_test_and_coating_accepted" in codes(output, "failed")


def test_r49_above_ground_run_does_not_inherit_the_buried_sequence_rules():
    output = run("evaluate_r49_crossing_construction",
                 {"crossing.buriedSection": False,
                  "crossing.coatingAppliedBeforeInstallation": None,
                  "crossing.coatingUndamagedAtInstallation": None,
                  "crossing.foundationAcceptedBeforeInstallation": None,
                  "crossing.backfillAfterTestAndCoatingAccepted": None,
                  "crossing.concealedWorkRecordFiled": None})
    assert output["result"] == "passed"
    assert "crossingconstruction_buried_backfill_after_test_and_coating_accepted" in codes(output, "not_applicable")


def test_r49_source_review_admits_the_text_came_from_ocr_not_the_original():
    review = frozen_installation_rules("evaluate_r49_crossing_construction")["sourceReview"]
    assert review["method"] == "agent_mineru_ocr_reading"
    assert any("OCR" in text for text in review["limitations"]), "OCR 重建不等于原件比对，必须写明"
    assert any("visual_verified" in text for text in review["limitations"]), "未升级条款核验状态也要写明"


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
        ("AC-R10-01", "evaluate_r10_standard_adoption", 10, "r10.alternativeStandardAdoption"),
        ("AC-R10-02", "evaluate_r10_comparison_table", 10, "r10.comparisonTableCoverage"),
        ("AC-R10-03", "evaluate_r10_compliance_declaration", 10, "r10.complianceDeclaration"),
        ("AC-R43-01", "evaluate_r43_material_certificate", 43, "r43.materialCertificate"),
        ("AC-R44-01", "evaluate_r44_coating_construction", 44, "r44.coatingConstruction"),
        ("AC-R46-01", "evaluate_r46_cathodic_protection", 46, "r46.cathodicProtection"),
        ("AC-R56-01", "evaluate_r56_accessory_documents", 56, "r56.safetyAccessoryDocuments"),
        ("AC-R56-02", "evaluate_r56_accessory_installation", 56, "r56.safetyAccessoryInstallation"),
        ("AC-R57-01", "evaluate_r57_safety_valve_calibration", 57, "r57.safetyValveCalibration"),
        ("AC-R58-01", "evaluate_r58_emergency_valve_test", 58, "r58.emergencyValveTest"),
        ("AC-R47-01", "evaluate_r47_static_grounding", 47, "r47.staticGrounding"),
        ("AC-R48-01", "evaluate_r48_weld_layout", 48, "r48.weldLayout"),
        ("AC-R49-01", "evaluate_r49_crossing_construction", 49, "r49.crossingConstruction"),
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
