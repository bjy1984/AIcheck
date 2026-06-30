from __future__ import annotations

import json

from scripts.ocr_annotation_readiness import build_annotation_readiness_report


def test_annotation_readiness_blocks_unconfirmed_machine_suggestions(tmp_path) -> None:
    tasks = tmp_path / "prelabelled_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "taskId": "label-case-1",
                        "caseId": "case-1",
                        "scenario": "piping_table_profile",
                        "collectionStatus": "needs_labeling",
                        "expectedTemplate": {
                            "fields": [{"fieldCode": "pipe_no", "value": "replace-with-label", "bbox": [0, 0, 0, 0]}],
                            "tables": [{"businessSchema": "table_v1", "bbox": [0, 0, 0, 0]}],
                        },
                        "suggestedExpected": {
                            "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [10, 10, 30, 20]}]
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_annotation_readiness_report(tasks)

    assert report["ok"] is False
    assert report["summary"]["tasks"] == 1
    assert report["summary"]["humanLabeled"] == 0
    assert report["summary"]["readyForEval"] == 0
    assert report["summary"]["blockerCounts"]["missing_human_label"] == 1
    assert report["summary"]["blockerCounts"]["machine_suggestion_not_confirmed"] == 1
    assert "placeholder_labels" in report["summary"]["blockerCounts"]
    assert "zero_area_bbox" in report["summary"]["blockerCounts"]


def test_annotation_readiness_does_not_count_machine_draft_as_human_label(tmp_path) -> None:
    tasks = tmp_path / "draft_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "taskId": "label-case-1",
                        "caseId": "case-1",
                        "scenario": "piping_table_profile",
                        "collectionStatus": "needs_human_review",
                        "machineDraftLabel": {"source": "machine_suggestion_draft"},
                        "labeledExpected": {
                            "qualityStatus": "auto_usable",
                            "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [10, 10, 30, 20]}],
                            "tables": [{"businessSchema": "piping_characteristic_list", "bbox": [1, 1, 80, 40]}],
                            "review": {
                                "source": "machine_suggestion_draft",
                                "labeler": "machine_prelabel",
                                "requiresHumanConfirmation": True,
                            },
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_annotation_readiness_report(tasks)

    assert report["ok"] is False
    assert report["summary"]["humanLabeled"] == 0
    assert report["summary"]["missingHumanLabels"] == 1
    assert report["summary"]["readyForEval"] == 0
    assert report["tasks"][0]["hasMachineDraftLabel"] is True
    assert report["tasks"][0]["hasHumanLabel"] is False
    assert report["summary"]["blockerCounts"]["machine_draft_not_human_confirmed"] == 1
    assert report["summary"]["blockerCounts"]["missing_human_label"] == 1


def test_annotation_readiness_accepts_labeled_positive_evidence(tmp_path) -> None:
    tasks = tmp_path / "labeled_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "taskId": "label-case-1",
                        "caseId": "case-1",
                        "scenario": "piping_table_profile",
                        "collectionStatus": "ready_for_eval",
                        "labeler": "标注员A",
                        "reviewer": "复核员B",
                        "labeledExpected": {
                            "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [10, 10, 30, 20]}],
                            "tables": [{"businessSchema": "table_v1", "bbox": [0, 10, 80, 40]}],
                            "seals": [{"nameContains": "设计许可", "bbox": [60, 20, 90, 45]}],
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_annotation_readiness_report(tasks)

    assert report["ok"] is True
    assert report["summary"]["humanLabeled"] == 1
    assert report["summary"]["readyForEval"] == 1
    assert report["summary"]["completionRate"] == 1
    assert report["summary"]["blockerCounts"] == {}
    assert report["nextActions"] == ["Export the tasks with ocr_100_annotation_export.py and run ocr_eval_set.py."]


def test_annotation_readiness_directory_prefers_labeled_tasks(tmp_path) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "annotation_tasks.json").write_text(
        json.dumps({"tasks": [{"caseId": "draft", "scenario": "seal_text_profile"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (pack / "labeled_tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "caseId": "ready",
                        "scenario": "seal_text_profile",
                        "collectionStatus": "ready_for_eval",
                        "labeler": "标注员A",
                        "reviewer": "复核员B",
                        "labeledExpected": {"seals": [{"nameContains": "公司", "bbox": [1, 1, 10, 10]}]},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_annotation_readiness_report(pack)

    assert report["ok"] is True
    assert report["tasks"][0]["caseId"] == "ready"
