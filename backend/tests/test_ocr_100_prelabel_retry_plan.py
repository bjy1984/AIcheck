from __future__ import annotations

import json
from pathlib import Path

from scripts.ocr_100_prelabel_retry_plan import (
    build_prelabel_retry_plan,
    prelabel_retry_plan_csv,
    prelabel_retry_plan_shell,
)


def test_prelabel_retry_plan_prioritizes_stale_failed_results(tmp_path: Path) -> None:
    tasks = tmp_path / "prelabelled_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "caseId": "case-failed",
                        "scenario": "ndt_rt_profile",
                        "profileId": "ndt_rt_report_v1",
                        "sourcePath": "Scan/a.pdf",
                        "prelabelStatus": "suggested",
                        "prelabelSummary": {"source": "result_dir"},
                        "suggestedExpected": {
                            "qualityStatus": "failed",
                            "diagnostics": [{"code": "NO_LOCAL_OCR_RESULT", "level": "error"}],
                        },
                    },
                    {
                        "caseId": "case-ok",
                        "scenario": "piping_table_profile",
                        "sourcePath": "Scan/b.png",
                        "prelabelStatus": "suggested",
                        "suggestedExpected": {
                            "qualityStatus": "auto_usable",
                            "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [1, 1, 10, 10]}],
                        },
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plan = build_prelabel_retry_plan(
        tasks,
        limit=10,
        batch_size=2,
        refresh_output="refreshed.json",
        merged_output="merged.json",
        result_dir="results",
        source_base_dir="..",
    )

    assert plan["summary"]["retryCandidates"] == 1
    item = plan["retryCandidates"][0]
    assert item["caseId"] == "case-failed"
    assert item["retryRecommended"] is True
    assert "no_local_ocr_result" in item["retryReasons"]
    assert "stale_failed_result_dir" in item["retryReasons"]
    assert plan["batches"][0]["caseIds"] == ["case-failed"]
    assert "--case-id case-failed" in plan["batches"][0]["prelabelCommand"]
    assert "--retry-fast-timeouts" in plan["batches"][0]["prelabelCommand"]
    assert "--engine-timeout-seconds 60.0" in plan["batches"][0]["prelabelCommand"]
    assert "--disable-remediation" in plan["batches"][0]["prelabelCommand"]
    assert "case-failed" in prelabel_retry_plan_csv(plan)
    assert "ocr_100_annotation_prelabel.py" in prelabel_retry_plan_shell(plan)


def test_prelabel_retry_plan_requires_review_before_retry_for_manifest_mismatch(tmp_path: Path) -> None:
    tasks = tmp_path / "prelabelled_tasks.json"
    audit = tmp_path / "manifest_audit.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "caseId": "case-mismatch",
                        "scenario": "quality_certificate_profile",
                        "sourcePath": "Scan/c.png",
                        "prelabelStatus": "suggested",
                        "suggestedExpected": {"qualityStatus": "failed"},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    audit.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "caseId": "case-mismatch",
                        "status": "mismatch",
                        "declaredScenario": "quality_certificate_profile",
                        "suggestedScenario": "evidence_profile",
                        "ocrTextAvailable": True,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plan = build_prelabel_retry_plan(
        tasks,
        manifest_audit_path=audit,
        limit=10,
        batch_size=2,
        refresh_output="refreshed.json",
        merged_output="merged.json",
        result_dir="results",
        source_base_dir="..",
    )

    assert plan["summary"]["retryCandidates"] == 0
    assert plan["summary"]["reviewBeforeRetry"] == 1
    item = plan["reviewBeforeRetry"][0]
    assert item["caseId"] == "case-mismatch"
    assert item["reviewBeforeRetry"] is True
    assert "manifest_mismatch_review_required" in item["reviewReasons"]


def test_prelabel_retry_plan_can_include_mismatches_when_requested(tmp_path: Path) -> None:
    tasks = tmp_path / "prelabelled_tasks.json"
    audit = tmp_path / "manifest_audit.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "caseId": "case-mismatch",
                        "scenario": "quality_certificate_profile",
                        "sourcePath": "Scan/c.png",
                        "prelabelStatus": "suggested",
                        "suggestedExpected": {"qualityStatus": "failed"},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    audit.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "caseId": "case-mismatch",
                        "status": "mismatch",
                        "suggestedScenario": "evidence_profile",
                        "ocrTextAvailable": True,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plan = build_prelabel_retry_plan(
        tasks,
        manifest_audit_path=audit,
        include_mismatches=True,
        limit=10,
        batch_size=1,
        refresh_output="refreshed.json",
        merged_output="merged.json",
        result_dir="results",
        source_base_dir="..",
    )

    assert plan["summary"]["retryCandidates"] == 1
    assert plan["retryCandidates"][0]["caseId"] == "case-mismatch"
    assert "manifest_mismatch_included" in plan["retryCandidates"][0]["retryReasons"]
