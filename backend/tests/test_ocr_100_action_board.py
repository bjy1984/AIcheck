from __future__ import annotations

import json
from pathlib import Path

from scripts.ocr_100_action_board import action_board_csv, action_board_markdown, build_action_board, write_action_handoff


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_action_board_combines_collection_label_and_candidate_actions(tmp_path: Path) -> None:
    status = write_json(
        tmp_path / "status.json",
        {
            "summary": {
                "status": "needs_sample_files",
                "score": 79.0,
                "readyForEval": 0,
                "requiredReadyForEval": 100,
                "collectionMissingCases": 2,
                "placeholderSampleSlots": 2,
            }
        },
    )
    closure = write_json(
        tmp_path / "closure.json",
        {
            "scenarioPlan": {
                "ndt_rt_profile": {
                    "targetCases": 10,
                    "queuedCases": 8,
                    "readyForEval": 0,
                    "collectionMissingCases": 2,
                    "collectionHint": "Collect RT reports.",
                    "minimumExpectedAnnotations": ["core fields", "table bbox"],
                }
            }
        },
    )
    tasks = write_json(
        tmp_path / "prelabelled_tasks.json",
        {
            "tasks": [
                {
                    "taskId": "task-1",
                    "caseId": "case-1",
                    "scenario": "ndt_rt_profile",
                    "profileId": "ndt_rt_report_v1",
                    "documentType": "ndt_report",
                    "collectionStatus": "needs_labeling",
                    "sourcePath": "Scan/rt.pdf",
                    "suggestedExpected": {"fields": [{"fieldCode": "report_no", "value": "RT-001", "bbox": [1, 1, 20, 20]}]},
                }
            ]
        },
    )
    candidates = write_json(
        tmp_path / "candidates.json",
        {
            "summary": {
                "newCandidates": 1,
                "duplicates": 3,
                "newScenarioCounts": {"ndt_rt_profile": 1},
            }
        },
    )

    board = build_action_board(
        certification_status_path=status,
        closure_plan_path=closure,
        annotation_tasks_path=tasks,
        candidates_path=candidates,
    )

    lanes = {action["lane"] for action in board["actions"]}
    assert board["ok"] is False
    assert board["summary"]["collectionMissingCases"] == 2
    assert board["summary"]["newLocalCandidates"] == 1
    assert board["summary"]["scenarioReviewBacklog"]["ndt_rt_profile"]["reviewBacklogCases"] == 1
    assert board["summary"]["scenarioReviewBacklog"]["ndt_rt_profile"]["missingReadyCases"] == 10
    assert {"collect_samples", "label_existing", "triage_candidates"} <= lanes
    assert any(action["id"] == "collect-ndt_rt_profile" for action in board["actions"])
    collect_action = next(action for action in board["actions"] if action["id"] == "collect-ndt_rt_profile")
    assert collect_action["dropDirectory"].endswith("/samples/ndt_rt_profile")
    assert collect_action["missingCases"] == 2
    assert collect_action["checklist"] == ["core fields", "table bbox"]
    assert any(action["id"] == "label-case-1" for action in board["actions"])
    label_action = next(action for action in board["actions"] if action["id"] == "label-case-1")
    assert label_action["taskId"] == "task-1"
    assert label_action["caseId"] == "case-1"
    markdown = action_board_markdown(board)
    csv_text = action_board_csv(board)
    assert "OCR 100 Action Board" in markdown
    assert "## Scenario Gaps" in markdown
    assert "ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe/samples/ndt_rt_profile" in markdown
    assert "dropDirectory" in csv_text
    assert "checklist" in csv_text
    assert "core fields; table bbox" in csv_text
    assert "triage-new-candidates" in csv_text
    manifest = write_action_handoff(board, tmp_path / "handoff")
    assert manifest["schemaVersion"] == "aicheck-ocr-100-action-handoff-v1"
    assert manifest["laneCounts"]["collect_samples"] == 1
    assert manifest["laneCounts"]["label_existing"] == 1
    collect_markdown = (tmp_path / "handoff" / "collect_samples.md").read_text(encoding="utf-8")
    label_csv = (tmp_path / "handoff" / "label_existing.csv").read_text(encoding="utf-8")
    readme = (tmp_path / "handoff" / "README.md").read_text(encoding="utf-8")
    assert "Collect Real OCR Samples" in collect_markdown
    assert "ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe/samples/ndt_rt_profile" in collect_markdown
    assert "case-1" in label_csv
    assert "Human Label Existing OCR Samples" in (tmp_path / "handoff" / "label_existing.md").read_text(encoding="utf-8")
    assert "Execution Order" in readme
    assert "Scenario Gaps" in readme


def test_action_board_adds_release_eval_action_when_labels_are_ready(tmp_path: Path) -> None:
    status = write_json(
        tmp_path / "status.json",
        {
            "summary": {
                "status": "needs_release_eval_export",
                "score": 94,
                "readyForEval": 100,
                "requiredReadyForEval": 100,
                "collectionMissingCases": 0,
            }
        },
    )
    closure = write_json(tmp_path / "closure.json", {"scenarioPlan": {}})

    board = build_action_board(certification_status_path=status, closure_plan_path=closure)

    assert any(action["id"] == "export-release-eval-set" for action in board["actions"])


def test_action_board_has_no_actions_when_complete(tmp_path: Path) -> None:
    status = write_json(
        tmp_path / "status.json",
        {
            "summary": {
                "status": "complete",
                "score": 100,
                "readyForEval": 100,
                "requiredReadyForEval": 100,
                "collectionMissingCases": 0,
            }
        },
    )
    closure = write_json(tmp_path / "closure.json", {"scenarioPlan": {}})

    board = build_action_board(certification_status_path=status, closure_plan_path=closure)

    assert board["ok"] is True
    assert board["actions"] == []
