from __future__ import annotations

import json
from pathlib import Path

from scripts.ocr_100_closure_plan import build_ocr_100_closure_plan, closure_plan_markdown


def test_ocr_100_closure_plan_reports_human_label_and_collection_gaps(tmp_path: Path) -> None:
    tasks = tmp_path / "prelabelled_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "caseId": "piping-1",
                        "scenario": "piping_table_profile",
                        "profileId": "piping_characteristic_list_v1",
                        "collectionStatus": "needs_labeling",
                        "sourcePath": "Scan/IMG_6509.heic",
                        "suggestedExpected": {
                            "qualityStatus": "auto_usable",
                            "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [1, 1, 10, 10]}],
                            "tables": [{"businessSchema": "piping_characteristic_table", "bbox": [1, 12, 100, 80]}],
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    scorecard = tmp_path / "scorecard.json"
    scorecard.write_text(
        json.dumps(
            {
                "score": 79.0,
                "ok": False,
                "blockers": ["evaluation set has fewer than 100 cases"],
                "sections": [
                    {"name": "runtime", "status": "pass"},
                    {"name": "evaluation", "status": "fail"},
                    {"name": "sample-probes", "status": "pass"},
                    {"name": "observability", "status": "pass"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"missingOcrText": 0}, ensure_ascii=False), encoding="utf-8")
    retry = tmp_path / "retry.json"
    retry.write_text(json.dumps({"retryCandidates": 0}, ensure_ascii=False), encoding="utf-8")

    plan = build_ocr_100_closure_plan(tasks, scorecard_path=scorecard, manifest_audit_path=manifest, retry_plan_path=retry, limit=5)

    assert plan["summary"]["status"] == "needs_sample_collection"
    assert plan["summary"]["automationReady"] is True
    assert plan["summary"]["score"] == 79.0
    assert plan["summary"]["readyForEval"] == 0
    assert plan["summary"]["missingReadyCases"] == 100
    assert plan["scenarioPlan"]["piping_table_profile"]["queuedCases"] == 1
    assert plan["scenarioPlan"]["piping_table_profile"]["collectionMissingCases"] == 11
    assert plan["gates"][3]["gate"] == "automation_retry"
    assert plan["gates"][3]["complete"] is True
    assert any("Collect/import additional real samples" in action for action in plan["nextActions"])


def test_ocr_100_closure_plan_markdown_includes_commands(tmp_path: Path) -> None:
    tasks = tmp_path / "prelabelled_tasks.json"
    tasks.write_text(json.dumps({"tasks": []}, ensure_ascii=False), encoding="utf-8")

    plan = build_ocr_100_closure_plan(tasks)
    markdown = closure_plan_markdown(plan)

    assert "# OCR 100 Closure Plan" in markdown
    assert "Scenario Closure" in markdown
    assert "ocr_100_scorecard.py" in markdown
