from __future__ import annotations

from scripts.ocr_98_release_gate import REQUIRED_FAULT_COMPONENTS, build_ocr_98_release_gate


def clean_evidence() -> dict:
    return {
        "annotation_readiness": {"summary": {"humanLabeled": 100, "readyForEval": 100}},
        "evaluation_report": {
            "ok": True,
            "summary": {"cases": 100},
            "metrics": {"fieldValueAccuracy": 0.99, "fieldBboxHitRate": 0.985},
            "thresholdFailures": [],
            "cases": [
                {
                    "caseId": f"case-{index}",
                    "passed": True,
                    "metrics": {"fieldValueAccuracy": 0.99, "fieldBboxHitRate": 0.985},
                    "sourceSha256": f"sha256:{index:064x}",
                    "labeler": "annotator-a",
                    "reviewer": "reviewer-b",
                    "reviewedAt": "2026-07-12T00:00:00Z",
                }
                for index in range(100)
            ],
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


def test_ocr_98_gate_rejects_duplicate_cases_and_forged_summary() -> None:
    evidence = clean_evidence()
    evidence["evaluation_report"]["cases"][1] = dict(evidence["evaluation_report"]["cases"][0])
    evidence["evaluation_report"]["summary"]["cases"] = 120
    evidence["evaluation_report"]["metrics"]["fieldValueAccuracy"] = 1.0

    report = build_ocr_98_release_gate(**evidence)
    failed = {item["name"] for item in report["failures"]}

    assert report["ok"] is False
    assert "evaluation.case-count-consistent" in failed
    assert "evaluation.unique-case-ids" in failed
    assert "evaluation.fieldValueAccuracy-consistent" in failed


def test_ocr_98_gate_rejects_missing_provenance_and_failed_case() -> None:
    evidence = clean_evidence()
    evidence["evaluation_report"]["cases"][0]["sourceSha256"] = ""
    evidence["evaluation_report"]["cases"][0]["passed"] = False
    evidence["evaluation_report"]["ok"] = False
    evidence["evaluation_report"]["thresholdFailures"] = [{"metric": "fieldValueAccuracy"}]

    report = build_ocr_98_release_gate(**evidence)
    failed = {item["name"] for item in report["failures"]}

    assert "evaluation.report-ok" in failed
    assert "evaluation.threshold-failures" in failed
    assert "evaluation.all-cases-pass" in failed
    assert "evaluation.provenance-complete" in failed
