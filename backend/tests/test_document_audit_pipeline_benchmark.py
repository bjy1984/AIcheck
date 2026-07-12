from __future__ import annotations

from scripts.document_audit_pipeline_benchmark import build_report


def prediction(field_value: str, *, latency_ms: int = 1000) -> dict:
    return {
        "jsonValid": True,
        "documentFields": {"report_no": {"value": field_value}},
        "findings": [
            {
                "findingType": "report_check",
                "severity": "medium",
                "suggestedAction": "human_confirm",
                "standardRefs": ["NB/T 47013.2-2015"],
            }
        ],
        "validation": {"invalidReferenceCount": 0, "ungroundedSubstantiveFindingCount": 0},
        "formalEvidenceReady": False,
        "endToEndTimeMs": latency_ms,
    }


def case(case_id: str, qwen_value: str, challenger_value: str) -> dict:
    return {
        "caseId": case_id,
        "gold": {
            "approved": True,
            "reviewers": ["reviewer-a", "reviewer-b"],
            "fields": {"report_no": {"value": "RT-001"}},
            "findings": [
                {
                    "findingType": "report_check",
                    "severity": "medium",
                    "suggestedAction": "human_confirm",
                    "standardRefs": ["NB/T 47013.2-2015"],
                }
            ],
        },
        "predictions": {
            "qwen_vl_audit_v1": prediction(qwen_value),
            "paddle_nuextract_deepseek_v1": prediction(challenger_value),
        },
    }


def test_pipeline_benchmark_refuses_unreviewed_accuracy_claims() -> None:
    report = build_report({"cases": [{"caseId": "unreviewed", "gold": {"approved": False}}]})

    assert report["status"] == "blocked"
    assert report["accuracyClaimed"] is False
    assert report["pipelines"]["qwen_vl_audit_v1"]["fieldExactMatch"] is None
    assert "DOUBLE_REVIEWED_GOLD_BELOW_30" in report["blockers"]


def test_pipeline_benchmark_can_pass_with_150_double_reviewed_cases() -> None:
    cases = [case(f"case-{index}", "wrong", "RT-001") for index in range(150)]

    report = build_report({"cases": cases})

    assert report["status"] == "pilot_passed"
    assert report["pipelines"]["qwen_vl_audit_v1"]["fieldExactMatch"] == 0.0
    assert report["pipelines"]["paddle_nuextract_deepseek_v1"]["fieldExactMatch"] == 1.0
    assert report["pairedChallengerVsQwenVl"]["ci95"][0] > 0
    assert all(report["pilotGates"].values())


def test_pipeline_benchmark_blocks_ungrounded_substantive_findings() -> None:
    cases = [case(f"case-{index}", "wrong", "RT-001") for index in range(150)]
    cases[0]["predictions"]["paddle_nuextract_deepseek_v1"]["validation"][
        "ungroundedSubstantiveFindingCount"
    ] = 1

    report = build_report({"cases": cases})

    assert report["status"] == "blocked"
    assert report["pilotGates"]["ungroundedSubstantiveFindingsZero"] is False
