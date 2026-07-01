from __future__ import annotations

import json
from pathlib import Path

from scripts.ocr_100_annotation_merge_prelabels import merge_prelabel_packs


def test_merge_prelabels_updates_suggestion_by_case_id(tmp_path: Path) -> None:
    base = tmp_path / "prelabelled_tasks.json"
    update = tmp_path / "refreshed.json"
    base.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "caseId": "case-1",
                        "sourcePath": "Scan/a.png",
                        "suggestedExpected": {"qualityStatus": "failed"},
                        "prelabelStatus": "suggested",
                    },
                    {
                        "caseId": "case-2",
                        "sourcePath": "Scan/b.png",
                        "suggestedExpected": {"qualityStatus": "failed"},
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    update.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "caseId": "case-1",
                        "suggestedExpected": {
                            "qualityStatus": "auto_usable",
                            "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [1, 1, 10, 10]}],
                        },
                        "prelabelStatus": "suggested",
                        "prelabelSummary": {"fieldSuggestions": 1},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = merge_prelabel_packs(base, [update])
    tasks = {task["caseId"]: task for task in result["payload"]["tasks"]}

    assert result["summary"]["mergedCaseIds"] == ["case-1"]
    assert tasks["case-1"]["suggestedExpected"]["qualityStatus"] == "auto_usable"
    assert tasks["case-1"]["prelabelSummary"]["fieldSuggestions"] == 1
    assert tasks["case-2"]["suggestedExpected"]["qualityStatus"] == "failed"
    assert tasks["case-1"]["prelabelMerge"]["source"] == str(update)


def test_merge_prelabels_preserves_human_labels_by_default(tmp_path: Path) -> None:
    base = tmp_path / "labeled_tasks.json"
    update = tmp_path / "refreshed.json"
    base.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "caseId": "case-1",
                        "collectionStatus": "ready_for_eval",
                        "labeledExpected": {"fields": [{"fieldCode": "human", "value": "A", "bbox": [1, 1, 10, 10]}]},
                        "suggestedExpected": {"qualityStatus": "failed"},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    update.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "caseId": "case-1",
                        "collectionStatus": "needs_labeling",
                        "labeledExpected": {"fields": [{"fieldCode": "machine", "value": "B", "bbox": [2, 2, 20, 20]}]},
                        "suggestedExpected": {"qualityStatus": "auto_usable"},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = merge_prelabel_packs(base, [update])
    task = result["payload"]["tasks"][0]

    assert task["collectionStatus"] == "ready_for_eval"
    assert task["labeledExpected"]["fields"][0]["fieldCode"] == "human"
    assert task["suggestedExpected"]["qualityStatus"] == "auto_usable"
    assert task["prelabelMerge"]["preservedHumanLabel"] is True
    assert result["summary"]["skippedHumanLabelCaseIds"] == ["case-1"]
