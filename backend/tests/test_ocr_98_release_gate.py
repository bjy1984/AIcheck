from __future__ import annotations

from scripts.ocr_98_release_gate import REQUIRED_FAULT_COMPONENTS, build_ocr_98_release_gate


def clean_evidence() -> dict:
    return {
        "annotation_readiness": {"summary": {"humanLabeled": 50, "readyForEval": 50}},
        "evaluation_report": {
            "summary": {"cases": 50},
            "metrics": {"fieldValueAccuracy": 0.99, "fieldBboxHitRate": 0.985},
            "cases": [{"caseId": f"case-{index}"} for index in range(50)],
        },
        "pipeline_evidence": {
            "tableRowStructureAccuracy": 0.98,
            "aiStandardReferenceErrorRate": 0,
            "wrongExpiryReferenceCount": 0,
            "formalConclusionWithoutConfirmedEvidenceCount": 0,
            "criticalWorkflowPassRate": 1,
            "releaseProbeSkipCount": 0,
        },
        "fault_injection": {
            "components": {name: {"status": "pass", "skipped": False} for name in REQUIRED_FAULT_COMPONENTS},
            "duplicateRecordCount": 0,
            "hangingBusinessStateCount": 0,
        },
        "user_acceptance": {"participants": 5, "taskSuccessRate": 1, "sus": 88},
    }


def test_ocr_98_gate_accepts_complete_real_evidence() -> None:
    report = build_ocr_98_release_gate(**clean_evidence())

    assert report["ok"] is True
    assert report["scoreBand"] == "98-99"
    assert report["failures"] == []


def test_ocr_98_gate_rejects_unreviewed_or_skipped_evidence() -> None:
    evidence = clean_evidence()
    evidence["annotation_readiness"]["summary"]["humanLabeled"] = 0
    evidence["evaluation_report"]["cases"][0]["fixtureDerived"] = True
    evidence["fault_injection"]["components"]["ocr"] = {"status": "skip", "skipped": True}
    evidence["user_acceptance"]["sus"] = 80

    report = build_ocr_98_release_gate(**evidence)
    failed = {item["name"] for item in report["failures"]}

    assert report["ok"] is False
    assert "annotations.human-labeled" in failed
    assert "evaluation.no-derived-cases" in failed
    assert "reliability.fault-injection" in failed
    assert "acceptance.sus" in failed
