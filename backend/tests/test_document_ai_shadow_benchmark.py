from __future__ import annotations

from scripts.document_ai_shadow_benchmark import build_report


def prediction(value: str, *, candidate_id: str = "EP2-FIELD-1") -> dict:
    return {
        "jsonValid": True,
        "totalTimeMs": 1000,
        "structuredOutput": {
            "fields": {
                "report_no": {
                    "value": value,
                    "sourceCandidateIds": [candidate_id],
                    "evidencePageNo": 1,
                    "evidenceBbox": [10, 10, 100, 40],
                }
            }
        },
        "attributionValidation": {
            "invalidCandidateIdCount": 0,
            "statusCounts": {"validated": 1, "unsupported": 0},
        },
    }


def case(case_id: str, baseline_value: str, hybrid_value: str) -> dict:
    return {
        "caseId": case_id,
        "gold": {
            "approved": True,
            "reviewers": ["reviewer-a", "reviewer-b"],
            "fields": {
                "report_no": {"value": "RT-001", "pageNo": 1, "bbox": [10, 10, 100, 40]}
            },
        },
        "predictions": {
            "baseline": prediction(baseline_value),
            "paddle_vl_fusion": prediction(hybrid_value),
            "nuextract_direct": prediction(hybrid_value),
            "hybrid": prediction(hybrid_value),
            "paddle_text_nuextract": prediction(hybrid_value),
        },
    }


def test_benchmark_refuses_accuracy_claim_without_double_reviewed_gold() -> None:
    report = build_report({"cases": [{"caseId": "unreviewed", "gold": {"approved": False}}]})

    assert report["status"] == "blocked"
    assert report["accuracyClaimed"] is False
    assert report["reviewedGoldCases"] == 0
    assert report["groups"]["hybrid"]["fieldExactMatch"] is None
    assert "DOUBLE_REVIEWED_GOLD_BELOW_30" in report["blockers"]


def test_benchmark_uses_only_double_reviewed_cases_and_computes_paired_delta() -> None:
    report = build_report(
        {
            "cases": [
                case("case-1", "wrong", "RT-001"),
                case("case-2", "RT-001", "RT-001"),
                {"caseId": "ignored", "gold": {"approved": True, "reviewers": ["one"]}},
            ]
        }
    )

    assert report["reviewedGoldCases"] == 2
    assert report["groups"]["baseline"]["fieldExactMatch"] == 0.5
    assert report["groups"]["hybrid"]["fieldExactMatch"] == 1.0
    assert report["pairedHybridVsBaseline"]["delta"] == 0.5
    assert report["status"] == "blocked"


def test_benchmark_requires_and_can_pass_all_statistical_evidence_and_latency_gates() -> None:
    cases = []
    for index in range(150):
        item = case(f"case-{index}", "wrong", "RT-001")
        item["pageCount"] = 1 if index % 2 == 0 else 6
        item["gold"]["tables"] = {
            "rt_table": [{"cells": {"detection_ratio": "10%", "technical_grade": "AB"}}]
        }
        for group, group_prediction in item["predictions"].items():
            group_prediction["selectedPageNos"] = list(range(1, item["pageCount"] + 1))
            group_prediction["structuredOutput"]["tables"] = {
                "rt_table": [
                    {
                        "cells": {
                            "detection_ratio": "5%" if group == "baseline" else "10%",
                            "technical_grade": "A" if group == "baseline" else "AB",
                        },
                        "sourceCandidateIds": ["EP2-CELL-1"],
                    }
                ]
            }
        cases.append(item)

    report = build_report({"cases": cases})

    assert report["status"] == "pilot_passed"
    assert report["groups"]["hybrid"]["fieldMacroAccuracy"] == 1.0
    assert report["groups"]["hybrid"]["tableRowF1"] == 1.0
    assert report["groups"]["hybrid"]["tableCellF1"] == 1.0
    assert report["groups"]["hybrid"]["pageAccuracy"] == 1.0
    assert report["groups"]["hybrid"]["bboxAccuracyAtIou50"] == 1.0
    assert report["groups"]["hybrid"]["hallucinationRate"] == 0.0
    assert report["groups"]["hybrid"]["singlePageP95LatencyMs"] == 1000.0
    assert report["groups"]["hybrid"]["sixPageP95LatencyMs"] == 1000.0
    assert all(report["pilotGates"].values())
