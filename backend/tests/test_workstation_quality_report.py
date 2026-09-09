from copy import deepcopy

import pytest

from scripts.workstation_quality_report import GROUPS, build_report


def case(number, gold, baseline, workstation, full):
    digest = f"{number:064x}"
    return {
        "caseId": str(number),
        "ruleId": "R37",
        "inputSha256": digest,
        "gold": {"result": gold, "approved": True, "reviewers": ["synthetic-A", "synthetic-B"]},
        "predictions": {
            group: {
                "result": result,
                "inputSha256": digest,
                "model": "test-model",
                "modelSettingsSha256": "s" * 64,
                "implementationVersion": group,
            }
            for group, result in zip(GROUPS, (baseline, workstation, full), strict=True)
        },
    }


def report(cases):
    return build_report({"schemaVersion": "workstation-quality-cases-v1", "cases": cases})


def test_paired_metrics_distinguish_unsafe_pass_abstention_and_regression():
    cases = [
        case(1, "failed", "passed", "evidence_insufficient", "failed"),
        case(2, "passed", "passed", "passed", "failed"),
        case(3, "passed", "evidence_insufficient", "passed", "passed"),
        case(4, "evidence_insufficient", "passed", "passed", "evidence_insufficient"),
    ]
    before = deepcopy(cases)
    result = report(cases)
    assert result["pairedReviewedCases"] == 4
    base, station, full = [result["groups"][group] for group in GROUPS]
    assert base["unsafePassOnNoncompliance"]["rate"] == 1
    assert station["unsafePassOnNoncompliance"]["rate"] == 0
    assert station["noncomplianceNotDetected"]["rate"] == 1
    assert full["falseNoncompliance"]["rate"] == 0.5
    assert base["unsupportedPass"]["rate"] == 1
    assert full["unsupportedPass"]["rate"] == 0
    delta = result["comparisonsToBaseline"]["full"]
    assert delta["improved"] == 3 and delta["regressed"] == 1
    assert delta["agreementDelta"] == 0.5
    assert delta["relativeErrorReduction"] == pytest.approx(2 / 3)
    assert not result["publicationApproved"]
    assert cases == before


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda c: c["gold"].update(reviewers=["same", " same "]), "gold_not_double_reviewed"),
        (lambda c: c["predictions"].pop("full"), "three_group_predictions_incomplete"),
        (
            lambda c: c["predictions"]["full"].update(inputSha256="other"),
            "prediction_input_mismatch",
        ),
        (lambda c: c["predictions"]["full"].update(model="other"), "model_or_settings_mismatch"),
        (
            lambda c: c["predictions"]["full"].pop("implementationVersion"),
            "prediction_configuration_missing",
        ),
    ],
)
def test_unmatched_case_excluded_from_all_three_groups(mutation, reason):
    value = case(1, "failed", "passed", "failed", "failed")
    mutation(value)
    result = report([value])
    assert result["pairedReviewedCases"] == 0
    assert result["excludedCases"] == [{"caseId": "1", "reason": reason}]
    assert all(group["exactAgreement"]["rate"] is None for group in result["groups"].values())


def test_execution_error_remains_in_denominator_and_is_not_safe_detection():
    result = report([case(1, "failed", "failed", "execution_error", "human_review_required")])
    for group in ("workstation", "full"):
        assert result["groups"][group]["exactAgreement"] == {"count": 0, "total": 1, "rate": 0}
        assert result["groups"][group]["noncomplianceNotDetected"]["rate"] == 1
        assert result["comparisonsToBaseline"][group]["regressed"] == 1
        assert result["comparisonsToBaseline"][group]["relativeErrorReduction"] is None


def test_missing_operational_measures_are_not_zero_and_report_coverage():
    first = case(1, "passed", "passed", "passed", "passed")
    second = case(2, "passed", "passed", "passed", "passed")
    first["predictions"]["full"].update(costCny=0, humanSeconds=30)
    result = report([first, second])
    measured = result["groups"]["full"]["operationalMeasures"]
    assert measured["costCny"] == {"measuredCases": 1, "total": 0, "mean": 0}
    assert measured["latencySeconds"] == {"measuredCases": 0, "total": None, "mean": None}
    assert measured["humanSeconds"]["mean"] == 30


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), "10"])
def test_invalid_cost_rejected(value):
    record = case(1, "passed", "passed", "passed", "passed")
    record["predictions"]["full"]["costCny"] = value
    with pytest.raises(ValueError, match="operational_measure_invalid"):
        report([record])


def test_duplicate_input_cannot_inflate_sample_count():
    first = case(1, "passed", "passed", "passed", "passed")
    second = deepcopy(first)
    second["caseId"] = "another-label"
    with pytest.raises(ValueError, match="duplicate_frozen_case"):
        report([first, second])


def test_metrics_separate_rules_and_empty_classes():
    first = case(1, "failed", "passed", "failed", "failed")
    second = case(2, "passed", "failed", "passed", "passed")
    second["ruleId"] = "R25"
    result = report([first, second])
    assert result["byRule"]["R25"]["baseline"]["unsafePassOnNoncompliance"]["rate"] is None
    assert result["byRule"]["R37"]["baseline"]["unsafePassOnNoncompliance"]["rate"] == 1


def test_paired_cost_reduction_uses_only_jointly_measured_cases():
    first = case(1, "passed", "passed", "passed", "passed")
    second = case(2, "passed", "passed", "passed", "passed")
    first["predictions"]["baseline"]["costCny"] = 10
    first["predictions"]["full"]["costCny"] = 5
    second["predictions"]["full"]["costCny"] = 100
    result = report([first, second])
    assert result["comparisonsToBaseline"]["full"]["pairedOperationalMeasures"]["costCny"] == {
        "pairedCases": 1,
        "meanDelta": -5,
        "relativeReduction": 0.5,
    }


def test_malformed_configuration_is_excluded_not_crashed():
    record = case(1, "passed", "passed", "passed", "passed")
    record["predictions"]["full"]["modelSettingsSha256"] = []
    assert report([record])["excludedCases"][0]["reason"] == "prediction_configuration_missing"
