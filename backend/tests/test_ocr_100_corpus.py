from __future__ import annotations

import json

from apps.ocr_service.evaluation import OCR_100_REQUIRED_SCENARIOS
from scripts.ocr_100_corpus import OCR_100_SCENARIO_TARGETS, build_corpus_report, collection_todo_csv, has_evidence


def test_ocr_100_corpus_accepts_100_cases_with_required_scenarios(tmp_path) -> None:
    cases = []
    index = 0
    for scenario in OCR_100_REQUIRED_SCENARIOS:
        for _ in range(OCR_100_SCENARIO_TARGETS[scenario]):
            cases.append(
                {
                    "caseId": f"case-{index:03d}",
                    "scenario": scenario,
                    "result": {"status": "success"},
                    "expected": {
                        "fields": [{"fieldCode": "report_no", "value": f"R-{index:03d}", "bbox": [0, 0, 10, 10]}],
                        "tables": [{"businessSchema": "table_v1", "bbox": [0, 0, 20, 20]}],
                        "seals": [{"nameContains": "seal", "bbox": [20, 20, 40, 40]}],
                    },
                }
            )
            index += 1
    eval_set = tmp_path / "set.json"
    eval_set.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")

    report = build_corpus_report([eval_set])

    assert report["ok"] is True
    assert report["summary"]["cases"] == 100
    assert report["summary"]["missingScenarios"] == []
    assert sum(report["summary"]["scenarioTargets"].values()) == 100
    assert sum(report["summary"]["scenarioTargetGaps"].values()) == 0
    assert report["failures"] == []


def test_ocr_100_corpus_rejects_small_duplicate_or_non_evidence_cases(tmp_path) -> None:
    eval_set = tmp_path / "small.json"
    eval_set.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "caseId": "dup",
                        "scenario": "piping_table_profile",
                        "result": {"status": "success"},
                        "expected": {"fields": [{"fieldCode": "pipe_no", "value": "PL8301"}]},
                    },
                    {
                        "caseId": "dup",
                        "scenario": "piping_table_profile",
                        "result": {"status": "success"},
                        "expected": {"fields": [{"fieldCode": "pipe_no", "value": "PL8302", "bbox": [0, 0, 1, 1]}]},
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_corpus_report([eval_set])
    codes = {item["code"] for item in report["failures"]}

    assert report["ok"] is False
    assert "OCR_100_CORPUS_TOO_SMALL" in codes
    assert "OCR_100_CORPUS_SCENARIO_MISSING" in codes
    assert "OCR_100_CORPUS_SCENARIO_TARGET_MISSING" in codes
    assert "OCR_100_CORPUS_CASE_ID_DUPLICATE" in codes
    assert "OCR_100_CORPUS_EXPECTED_EVIDENCE_MISSING" in codes
    assert report["summary"]["scenarioTargetGaps"]["piping_table_profile"] == OCR_100_SCENARIO_TARGETS["piping_table_profile"] - 2


def test_ocr_100_corpus_requires_positive_area_evidence() -> None:
    assert has_evidence({"bbox": [0, 0, 0, 0]}) is False
    assert has_evidence({"bbox": [10, 10, 10, 20]}) is False
    assert has_evidence({"bbox": [0, 0, 10, 10]}) is True
    assert has_evidence({"polygon": [[0, 0], [10, 0], [10, 10], [0, 10]]}) is True
    assert has_evidence({"polygon": [[0, 0], [0, 0], [0, 0]]}) is False


def test_ocr_100_corpus_bootstrap_expands_templates_to_target_distribution(tmp_path) -> None:
    template = {
        "caseId": "template-piping",
        "scenario": "piping_table_profile",
        "profileId": "piping_characteristic_list_v1",
        "documentType": "engineering_table_photo",
        "result": {
            "status": "success",
            "fields": [{"fieldCode": "pipe_no", "fieldValue": "PL8301", "bbox": [0, 0, 10, 10]}],
            "tables": [{"businessSchema": "table_v1", "bbox": [0, 0, 20, 20]}],
            "seals": [{"sealName": "design seal", "bbox": [20, 20, 40, 40]}],
            "quality": {"status": "auto_usable", "evidenceCompleteness": 1.0},
        },
        "expected": {
            "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [0, 0, 10, 10]}],
            "tables": [{"businessSchema": "table_v1", "bbox": [0, 0, 20, 20]}],
            "seals": [{"nameContains": "seal", "bbox": [20, 20, 40, 40]}],
            "qualityStatus": "auto_usable",
            "minEvidenceCompleteness": 1.0,
        },
    }
    eval_set = tmp_path / "template.json"
    eval_set.write_text(json.dumps({"cases": [template]}, ensure_ascii=False), encoding="utf-8")

    report = build_corpus_report([eval_set], bootstrap_to_targets=True)

    assert report["ok"] is True
    assert report["bootstrap"]["derivedCases"] > 0
    assert report["summary"]["cases"] == 100
    assert sum(report["summary"]["scenarioTargetGaps"].values()) == 0
    assert len({case["caseId"] for case in report["cases"]}) == 100
    assert all(case["bootstrapGenerated"] is True for case in report["cases"])
    quality_case = next(case for case in report["cases"] if case["scenario"] == "quality_certificate_profile")
    assert quality_case["fixtureDerived"] is True
    assert quality_case["profileId"] == "quality_certificate_v1"
    assert quality_case["collectionStatus"] == "needs_real_sample_replacement"


def test_ocr_100_corpus_require_real_samples_rejects_bootstrap_cases(tmp_path) -> None:
    cases = []
    index = 0
    for scenario in OCR_100_REQUIRED_SCENARIOS:
        for _ in range(OCR_100_SCENARIO_TARGETS[scenario]):
            cases.append(
                {
                    "caseId": f"case-{index:03d}",
                    "scenario": scenario,
                    "bootstrapGenerated": True,
                    "collectionStatus": "needs_real_sample_replacement",
                    "result": {"status": "success"},
                    "expected": {
                        "fields": [{"fieldCode": "report_no", "value": f"R-{index:03d}", "bbox": [0, 0, 10, 10]}],
                        "tables": [{"businessSchema": "table_v1", "bbox": [0, 0, 20, 20]}],
                        "seals": [{"nameContains": "seal", "bbox": [20, 20, 40, 40]}],
                    },
                }
            )
            index += 1
    eval_set = tmp_path / "set.json"
    eval_set.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")

    report = build_corpus_report([eval_set], require_real_samples=True)
    codes = {item["code"] for item in report["failures"]}

    assert report["ok"] is False
    assert "OCR_100_CORPUS_SYNTHETIC_CASE" in codes
    assert "OCR_100_CORPUS_NEEDS_REAL_SAMPLE_REPLACEMENT" in codes
    assert report["collectionPlan"]["totalTargetCases"] == 100
    assert report["collectionPlan"]["totalMissingCases"] == 0
    assert report["summary"]["requireRealSamples"] is True


def test_ocr_100_corpus_collection_plan_reports_missing_scenario_targets(tmp_path) -> None:
    eval_set = tmp_path / "small.json"
    eval_set.write_text(json.dumps({"cases": []}, ensure_ascii=False), encoding="utf-8")

    report = build_corpus_report([eval_set])
    item = next(item for item in report["collectionPlan"]["items"] if item["scenario"] == "quality_certificate_profile")

    assert report["collectionPlan"]["totalMissingCases"] == 100
    assert item["profileId"] == "quality_certificate_v1"
    assert item["missingCases"] == OCR_100_SCENARIO_TARGETS["quality_certificate_profile"]
    assert "core fields" in item["minimumExpectedAnnotations"]
    assert "quality certificates" in item["collectionHint"]
    assert len(report["collectionPlan"]["caseTemplates"]) == 100
    template = next(case for case in report["collectionPlan"]["caseTemplates"] if case["scenario"] == "quality_certificate_profile")
    assert template["caseId"].startswith("real-quality_certificate_profile-")
    assert template["collectionStatus"] == "needs_labeling"
    assert template["expected"]["fields"][0]["bbox"] == [0, 0, 0, 0]


def test_ocr_100_corpus_collection_todo_csv_is_actionable(tmp_path) -> None:
    eval_set = tmp_path / "small.json"
    eval_set.write_text(json.dumps({"cases": []}, ensure_ascii=False), encoding="utf-8")
    report = build_corpus_report([eval_set])

    content = collection_todo_csv(report["collectionPlan"])

    assert "caseId,scenario,profileId" in content
    assert "real-ndt_ut_profile-001,ndt_ut_profile,ndt_ut_report_v1" in content
    assert "Collect real ultrasonic testing reports" in content
    assert "real-sample-path" in content
