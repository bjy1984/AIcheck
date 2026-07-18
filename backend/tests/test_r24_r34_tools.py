from __future__ import annotations

from libs.review_orchestrator.deterministic_tools import check_welder_work_coverage, decode_welder_qualification
from libs.review_tools.r24_r34_tools import (
    check_wps_pqr_coverage,
    evaluate_heat_treatment,
    evaluate_heat_treatment_instruments,
    evaluate_pipe_fit_up,
    evaluate_weld_appearance,
    evaluate_weld_repair,
    evaluate_welding_consumable,
    evaluate_welding_consumable_control,
    evaluate_welding_process,
    resolve_pwht_applicability,
)


def test_r24_sample_code_covers_20_steel_89_by_4_5_gtaw() -> None:
    arguments = {
        "qualificationCodes": ["GTAW-FeII-6G-3/57-FefS-02/11/12"],
        "workItems": [{"weldingMethod": "GTAW", "materialGrade": "20", "position": "6G", "thickness": 4.5, "diameter": 89}],
        "reviewDate": "2026-07-17",
    }
    decoded = decode_welder_qualification(arguments)
    covered = check_welder_work_coverage(arguments)

    assert decoded["facts"]["decodedItems"][0]["thicknessMax"] == 6
    assert decoded["facts"]["decodedItems"][0]["diameterMin"] == 25
    assert decoded["facts"]["decodedItems"][0]["processFactors"] == ["02", "11", "12"]
    assert covered["result"] == "passed"


def test_r24_after_2026_transition_fails_closed_without_verified_profile() -> None:
    output = check_welder_work_coverage(
        {
            "qualificationCodes": ["GTAW-FeII-6G-3/57-FefS-02/11/12"],
            "workItems": [{"weldingMethod": "GTAW", "materialGrade": "20", "position": "6G", "thickness": 4.5, "diameter": 89}],
            "reviewDate": "2026-08-01",
        }
    )
    assert output["result"] == "evidence_insufficient"
    assert output["facts"]["reason"] == "tsg_z6002_2026_effective_profile_not_verified"


def _wps_pqr_arguments() -> dict:
    return {
        "wpsItems": [{"wpsNo": "WPS-1", "pqrNo": "PQR-1", "approved": True, "weldingMethod": "GTAW", "materialCategory": "FeII", "currentMin": 80, "currentMax": 110, "voltageMin": 10, "voltageMax": 14, "weldingSpeedMin": 70, "weldingSpeedMax": 100, "interpassTemperatureMin": 20, "interpassTemperatureMax": 120}],
        "pqrItems": [{"pqrNo": "PQR-1", "approved": True, "weldingMethod": "GTAW", "materialCategory": "FeII", "currentMin": 70, "currentMax": 120, "voltageMin": 9, "voltageMax": 15, "weldingSpeedMin": 60, "weldingSpeedMax": 110, "interpassTemperatureMin": 10, "interpassTemperatureMax": 150, "thicknessMin": 2, "thicknessMax": 8}],
        "workItems": [{"id": "L-1", "weldingMethod": "GTAW", "materialCategory": "FeII", "thickness": 4.5, "current": 90, "voltage": 12, "weldingSpeed": 80, "interpassTemperature": 80}],
    }


def test_r25_wps_pqr_approval_parameter_and_actual_thickness_coverage() -> None:
    assert check_wps_pqr_coverage(_wps_pqr_arguments())["result"] == "passed"


def test_r25_bonding_fails_closed_without_verified_standard_profile() -> None:
    output = check_wps_pqr_coverage({**_wps_pqr_arguments(), "processType": "bonding"})
    assert output["result"] == "evidence_insufficient"
    assert output["facts"]["reason"] == "bonding_standard_rule_profile_not_verified"


def test_r26_consumable_mtc_uses_product_profile_and_physical_batch() -> None:
    output = evaluate_welding_consumable(
        {
            "qualityCertificates": [{"id": "MTC-1", "materialGrade": "E4315", "specification": "3.2", "batchNo": "B-1", "standardRef": "GB/T 5117-2012", "originalSeen": True, "chemicalComposition": {"S": 0.01}, "mechanicalProperties": {"tensile": 500}}],
            "designRequirements": [{"id": "C-1", "materialGrade": "E4315", "specification": "3.2", "standardRef": "GB/T 5117-2012"}],
            "physicalItems": [{"batchNo": "B-1"}],
            "productStandardProfiles": {"gbt51172012": {"chemicalComposition": {"S": {"max": 0.035}}, "mechanicalProperties": {"tensile": {"min": 430}}}},
        }
    )
    assert output["result"] == "passed"


def test_r27_full_management_chain_passes() -> None:
    records = [
        {"recordKind": "acceptance", "conclusion": "合格"},
        {"recordKind": "storage", "temperature": 20, "humidity": 45},
        {"recordKind": "drying", "dryingTemperature": 350, "dryingMinutes": 60},
        {"recordKind": "issue", "batchNo": "B-1", "materialGrade": "E4315"},
        {"recordKind": "use", "batchNo": "B-1", "materialGrade": "E4315", "expired": False, "mixedUse": False},
        {"recordKind": "return", "batchNo": "B-1", "materialGrade": "E4315"},
    ]
    requirements = {"temperature": {"min": 5, "max": 30}, "humidity": {"max": 60}, "dryingTemperature": {"min": 340, "max": 360}, "dryingMinutes": {"min": 60}}
    assert evaluate_welding_consumable_control({"managementRecords": records, "controlRequirements": requirements})["result"] == "passed"


def test_r28_material_conditioned_fit_up_limits() -> None:
    output = evaluate_pipe_fit_up(
        {"fitUpRecords": [{"id": "J-1", "materialGroup": "carbon steel", "thickness": 10, "misalignment": 1, "gap": 2, "gapMin": 1.5, "gapMax": 2.5, "bevelAngle": 35, "bevelAngleMin": 30, "bevelAngleMax": 40, "forcedFitUp": False}]}
    )
    assert output["result"] == "passed"
    assert output["facts"]["fitUpMatrix"][0]["misalignmentLimitMM"] == 1


def test_r29_requires_complete_traceable_record_and_linked_r24_r25() -> None:
    output = evaluate_welding_process(
        {
            "weldingRecords": [{"weldNo": "W-1", "welderCertificateNo": "WC-1", "weldingMethod": "GTAW", "current": 90, "voltage": 12, "weldingSpeed": 80, "interpassTemperature": 80, "weldMapRef": "MAP-1", "traceable": True}],
            "welderCoverageResult": {"result": "passed"},
            "wpsPqrCoverageResult": {"result": "passed"},
        }
    )
    assert output["result"] == "passed"


def test_r30_table43_dimensions_and_surface_defects() -> None:
    output = evaluate_weld_appearance(
        {"appearanceRecords": [{"weldNo": "W-1", "inspectionGrade": "I", "jointType": "butt", "thickness": 10, "crack": False, "lackOfFusion": False, "surfacePore": False, "exposedSlag": False, "undercutDepth": 0, "reinforcement": 2.5, "width": 8, "widthMin": 7, "widthMax": 9}]}
    )
    assert output["result"] == "passed"


def test_r31_more_than_two_repairs_requires_special_technical_approval() -> None:
    base = {"weldNo": "W-1", "repairApplicationNo": "RA-1", "repairProcedureNo": "RP-1", "repairProcedureApproved": True, "causeAnalysis": "夹渣", "sameLocationRepairCount": 3, "originalInspectionMethod": "RT", "postRepairNdtReportNo": "RT-1", "postRepairNdtMethod": "RT", "postRepairNdtResult": "合格"}
    assert evaluate_weld_repair({"repairRecords": [{**base, "revisedSpecialMeasures": True, "technicalHeadApproved": True}]})["result"] == "passed"
    assert evaluate_weld_repair({"repairRecords": [{**base, "revisedSpecialMeasures": False, "technicalHeadApproved": True}]})["result"] == "failed"


def _carbon_pwht_weld() -> dict:
    return {"weldNo": "W-1", "materialGroup": "carbon_manganese", "governingThickness": 30}


def test_r32_shared_pwht_applicability_and_procedure() -> None:
    weld = _carbon_pwht_weld()
    resolved = resolve_pwht_applicability({"weldItems": [weld]})
    reviewed = evaluate_heat_treatment(
        {"profile": "heat_treatment_procedure", "weldItems": [weld], "procedureCards": [{"weldNo": "W-1", "approved": True, "qualificationReportNo": "PQR-1", "heatingRate": 160, "holdingTemperature": 620, "holdingMinutes": 75, "coolingRate": 210}], "qualificationReports": [{"pqrNo": "PQR-1", "approved": True}]}
    )
    assert resolved["facts"]["pwhtApplicabilityMatrix"][0]["required"] is True
    assert reviewed["result"] == "passed"
    assert reviewed["facts"]["pwhtProcedureMatrix"][0]["applicabilityKey"] == resolved["facts"]["pwhtApplicabilityMatrix"][0]["applicabilityKey"]


def test_r33_instrument_calibration_and_point_layout() -> None:
    records = [{"instrumentType": kind, "calibrationCertificateNo": f"C-{index}", "validUntil": "2027-01-01"} for index, kind in enumerate(("thermocouple", "controller", "recorder"), 1)]
    output = evaluate_heat_treatment_instruments({"weldItems": [_carbon_pwht_weld()], "instrumentRecords": records, "temperaturePointLayouts": [{"drawingNo": "TP-1"}], "reviewDate": "2026-07-17"})
    assert output["result"] == "passed"


def test_r33_is_not_applicable_when_all_welds_do_not_require_pwht() -> None:
    output = evaluate_heat_treatment_instruments({"weldItems": [{"weldNo": "W-2", "materialGroup": "carbon_manganese", "governingThickness": 10}]})
    assert output["result"] == "not_applicable"


def test_r34_hardness_is_material_and_design_conditioned_not_fixed_generic_200() -> None:
    weld = {**_carbon_pwht_weld(), "designHardnessMaxHBW": 200}
    report = {"weldNo": "W-1", "curveContinuous": True, "curveRef": "CURVE-1", "heatingRate": 160, "holdingTemperature": 620, "holdingMinutes": 75, "coolingRate": 210}
    hardness = {"weldNo": "W-1", "hardnessMethod": "HBW", "testedJointCount": 1, "lotJointCount": 10, "localHeatTreatment": False, "readings": [{"zone": "weld", "value": 190}, {"zone": "HAZ", "value": 195}]}
    passed = evaluate_heat_treatment({"profile": "heat_treatment_result", "weldItems": [weld], "heatTreatmentReports": [report], "hardnessReports": [hardness]})
    missing_design_limit = evaluate_heat_treatment({"profile": "heat_treatment_result", "weldItems": [_carbon_pwht_weld()], "heatTreatmentReports": [report], "hardnessReports": [hardness]})
    assert passed["result"] == "passed"
    assert missing_design_limit["result"] == "evidence_insufficient"
