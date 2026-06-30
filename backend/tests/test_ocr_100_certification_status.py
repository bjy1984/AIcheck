from __future__ import annotations

import json
from pathlib import Path

from scripts.ocr_100_certification_status import build_certification_status


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_ocr_100_certification_status_reports_missing_evidence_reports(tmp_path: Path) -> None:
    report = build_certification_status(
        {
            "scorecard": tmp_path / "missing-scorecard.json",
            "closurePlan": None,
            "intakeVerify": None,
            "intakePipeline": None,
            "reviewedLabelGate": None,
        }
    )

    assert report["ok"] is False
    assert report["summary"]["status"] == "needs_evidence_reports"
    assert report["summary"]["missingReportCount"] == 5
    assert {item["code"] for item in report["blockers"]} == {"REPORT_MISSING"}


def test_ocr_100_certification_status_prioritizes_sample_placeholders(tmp_path: Path) -> None:
    scorecard = write_json(tmp_path / "scorecard.json", {"ok": False, "score": 79, "blockers": ["fewer than 100 cases"], "sections": []})
    closure = write_json(
        tmp_path / "closure.json",
        {
            "summary": {
                "tasks": 30,
                "humanLabeled": 0,
                "readyForEval": 0,
                "requiredReadyForEval": 100,
                "collectionMissingCases": 75,
            },
            "scenarioPlan": {
                "ndt_rt_profile": {
                    "targetCases": 10,
                    "queuedCases": 1,
                    "readyForEval": 0,
                    "collectionMissingCases": 9,
                }
            },
        },
    )
    intake = write_json(
        tmp_path / "verify.json",
        {
            "ok": True,
            "readyToIngest": False,
            "summary": {
                "slots": 75,
                "filledSlots": 0,
                "placeholderSlots": 75,
                "scenarioSummary": {"ndt_rt_profile": {"slots": 9, "filled": 0, "placeholders": 9}},
            },
        },
    )
    pipeline = write_json(tmp_path / "pipeline.json", {"ok": True, "readyToExecute": False, "summary": {"readyToExecute": False}})
    gate = write_json(tmp_path / "gate.json", {"ok": False, "summary": {"readyForEval": 0, "humanLabeled": 0, "tasks": 30}, "failures": []})

    report = build_certification_status(
        {
            "scorecard": scorecard,
            "closurePlan": closure,
            "intakeVerify": intake,
            "intakePipeline": pipeline,
            "reviewedLabelGate": gate,
        }
    )

    assert report["summary"]["status"] == "needs_sample_files"
    assert report["summary"]["placeholderSampleSlots"] == 75
    assert any(item["code"] == "SAMPLE_MANIFEST_PLACEHOLDERS" for item in report["blockers"])
    assert report["scenarioGaps"][0]["scenario"] == "ndt_rt_profile"


def test_ocr_100_certification_status_reports_human_label_gap_after_samples_ready(tmp_path: Path) -> None:
    scorecard = write_json(tmp_path / "scorecard.json", {"ok": False, "score": 89, "blockers": ["fewer than 100 cases"], "sections": []})
    closure = write_json(
        tmp_path / "closure.json",
        {"summary": {"readyForEval": 20, "requiredReadyForEval": 100, "collectionMissingCases": 0}},
    )
    intake = write_json(tmp_path / "verify.json", {"ok": True, "readyToIngest": True, "summary": {"filledSlots": 75, "placeholderSlots": 0}})
    pipeline = write_json(tmp_path / "pipeline.json", {"ok": True, "readyToExecute": True, "summary": {"readyToExecute": True}})
    gate = write_json(
        tmp_path / "gate.json",
        {
            "ok": False,
            "summary": {"ready": False, "readyForEval": 20, "humanLabeled": 25, "tasks": 100, "evalSetWritten": False},
            "failures": [{"code": "ANNOTATION_READINESS_NOT_READY", "message": "not ready"}],
        },
    )

    report = build_certification_status(
        {
            "scorecard": scorecard,
            "closurePlan": closure,
            "intakeVerify": intake,
            "intakePipeline": pipeline,
            "reviewedLabelGate": gate,
        }
    )

    assert report["summary"]["status"] == "needs_human_labels"
    assert report["summary"]["readyForEval"] == 20
    assert any(item["code"] == "HUMAN_GOLD_SET_INCOMPLETE" for item in report["blockers"])


def test_ocr_100_certification_status_complete_when_scorecard_passes(tmp_path: Path) -> None:
    scorecard = write_json(
        tmp_path / "scorecard.json",
        {
            "ok": True,
            "score": 100,
            "blockers": [],
            "sections": [
                {"name": "runtime", "status": "pass"},
                {"name": "evaluation", "status": "pass"},
                {"name": "sample-probes", "status": "pass"},
                {"name": "observability", "status": "pass"},
            ],
        },
    )
    closure = write_json(tmp_path / "closure.json", {"summary": {"readyForEval": 100, "requiredReadyForEval": 100, "collectionMissingCases": 0}})
    intake = write_json(tmp_path / "verify.json", {"ok": True, "readyToIngest": True, "summary": {"filledSlots": 0, "placeholderSlots": 0}})
    pipeline = write_json(tmp_path / "pipeline.json", {"ok": True, "readyToExecute": True, "summary": {"readyToExecute": True}})
    gate = write_json(tmp_path / "gate.json", {"ok": True, "summary": {"ready": True, "readyForEval": 100, "humanLabeled": 100, "evalSetWritten": True}})

    report = build_certification_status(
        {
            "scorecard": scorecard,
            "closurePlan": closure,
            "intakeVerify": intake,
            "intakePipeline": pipeline,
            "reviewedLabelGate": gate,
        }
    )

    assert report["ok"] is True
    assert report["summary"]["status"] == "complete"
    assert report["summary"]["score"] == 100
