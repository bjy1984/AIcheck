from __future__ import annotations

import json
from pathlib import Path

from scripts.ocr_100_annotation_draft_labels import draft_labels_from_suggestions


def test_draft_labels_from_suggestions_prefills_machine_draft_without_readiness(tmp_path: Path) -> None:
    source = tmp_path / "prelabelled_tasks.json"
    output = tmp_path / "draft_tasks.json"
    source.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "taskId": "label-case-1",
                        "caseId": "case-1",
                        "scenario": "piping_table_profile",
                        "collectionStatus": "needs_labeling",
                        "suggestedExpected": {
                            "qualityStatus": "auto_usable",
                            "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [1, 1, 10, 10]}],
                            "tables": [{"businessSchema": "piping_characteristic_list", "bbox": [2, 2, 20, 20]}],
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = draft_labels_from_suggestions(source, output_path=output, only_auto_usable=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    task = payload["tasks"][0]

    assert result["summary"]["drafted"] == 1
    assert task["collectionStatus"] == "needs_human_review"
    assert task["labeledExpected"]["fields"][0]["fieldCode"] == "pipe_no"
    assert task["labeledExpected"]["review"]["source"] == "machine_suggestion_draft"
    assert task["labeledExpected"]["review"]["requiresHumanConfirmation"] is True
    assert task["machineDraftLabel"]["requiresHumanConfirmation"] is True
    assert result["readiness"]["summary"]["humanLabeled"] == 0
    assert result["readiness"]["summary"]["readyForEval"] == 0
    assert result["readiness"]["summary"]["blockerCounts"]["machine_draft_not_human_confirmed"] == 1


def test_draft_labels_preserves_existing_human_label_by_default(tmp_path: Path) -> None:
    source = tmp_path / "labeled_tasks.json"
    output = tmp_path / "draft_tasks.json"
    source.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "caseId": "case-1",
                        "collectionStatus": "ready_for_eval",
                        "labeler": "human-a",
                        "reviewer": "human-b",
                        "labeledExpected": {
                            "fields": [{"fieldCode": "human", "value": "A", "bbox": [1, 1, 10, 10]}],
                        },
                        "suggestedExpected": {
                            "qualityStatus": "auto_usable",
                            "fields": [{"fieldCode": "machine", "value": "B", "bbox": [2, 2, 20, 20]}],
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = draft_labels_from_suggestions(source, output_path=output)
    task = json.loads(output.read_text(encoding="utf-8"))["tasks"][0]

    assert result["summary"]["drafted"] == 0
    assert result["summary"]["skipped"]["existing_human_label"] == ["case-1"]
    assert task["collectionStatus"] == "ready_for_eval"
    assert task["labeledExpected"]["fields"][0]["fieldCode"] == "human"
