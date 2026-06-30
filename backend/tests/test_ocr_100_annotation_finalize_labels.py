from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ocr_100_annotation_finalize_labels import finalize_human_labels


def machine_draft_task() -> dict:
    return {
        "taskId": "label-case-1",
        "caseId": "case-1",
        "scenario": "piping_table_profile",
        "profileId": "piping_characteristic_list_v1",
        "documentType": "engineering_table_photo",
        "collectionStatus": "needs_human_review",
        "sourcePath": "Scan/IMG_6509.heic",
        "machineDraftLabel": {"source": "machine_suggestion_draft"},
        "labeledExpected": {
            "qualityStatus": "auto_usable",
            "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [10, 20, 200, 80]}],
            "tables": [{"businessSchema": "piping_characteristic_table_v1", "bbox": [10, 90, 800, 500]}],
            "review": {
                "source": "machine_suggestion_draft",
                "labeler": "machine_prelabel",
                "requiresHumanConfirmation": True,
            },
        },
    }


def test_finalize_labels_refuses_machine_draft_without_explicit_confirmation(tmp_path: Path) -> None:
    source = tmp_path / "draft_tasks.json"
    output = tmp_path / "labeled_tasks.json"
    source.write_text(json.dumps({"tasks": [machine_draft_task()]}, ensure_ascii=False), encoding="utf-8")

    result = finalize_human_labels(
        source,
        output_path=output,
        labeler="标注员A",
        reviewer="复核员B",
        confirm_human_reviewed=False,
    )

    assert result["ok"] is False
    assert result["summary"]["outputWritten"] is False
    assert result["summary"]["finalized"] == 0
    assert result["report"]["failures"][0]["code"] == "OCR_100_FINALIZE_MACHINE_DRAFT_REQUIRES_CONFIRMATION"
    assert not output.exists()


def test_finalize_labels_converts_confirmed_machine_draft_to_ready_for_eval(tmp_path: Path) -> None:
    source = tmp_path / "draft_tasks.json"
    output = tmp_path / "labeled_tasks.json"
    report_output = tmp_path / "report.json"
    source.write_text(json.dumps({"tasks": [machine_draft_task()]}, ensure_ascii=False), encoding="utf-8")

    result = finalize_human_labels(
        source,
        output_path=output,
        report_output=report_output,
        labeler="标注员A",
        reviewer="复核员B",
        comment="人工已核对字段、表格和证据框。",
        confirm_human_reviewed=True,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    task = payload["tasks"][0]

    assert result["ok"] is True
    assert result["summary"]["outputWritten"] is True
    assert result["summary"]["readiness"]["readyForEval"] == 1
    assert "machineDraftLabel" not in task
    assert task["collectionStatus"] == "ready_for_eval"
    assert task["labeler"] == "标注员A"
    assert task["reviewer"] == "复核员B"
    assert task["labeledExpected"]["review"]["source"] == "human_review"
    assert task["labeledExpected"]["review"]["previousSource"] == "machine_suggestion_draft"
    assert task["labeledExpected"]["review"]["requiresHumanConfirmation"] is False
    assert report_output.exists()


def test_finalize_labels_rejects_same_labeler_and_reviewer(tmp_path: Path) -> None:
    source = tmp_path / "draft_tasks.json"
    source.write_text(json.dumps({"tasks": [machine_draft_task()]}, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="reviewer must be different"):
        finalize_human_labels(
            source,
            output_path=tmp_path / "labeled_tasks.json",
            labeler="同一人",
            reviewer="同一人",
            confirm_human_reviewed=True,
        )


def test_finalize_labels_blocks_invalid_human_expected(tmp_path: Path) -> None:
    task = machine_draft_task()
    task["labeledExpected"]["fields"][0]["bbox"] = [0, 0, 0, 0]
    source = tmp_path / "draft_tasks.json"
    output = tmp_path / "labeled_tasks.json"
    source.write_text(json.dumps({"tasks": [task]}, ensure_ascii=False), encoding="utf-8")

    result = finalize_human_labels(
        source,
        output_path=output,
        labeler="标注员A",
        reviewer="复核员B",
        confirm_human_reviewed=True,
    )

    assert result["ok"] is False
    assert result["summary"]["outputWritten"] is False
    assert any(failure["code"] == "OCR_100_FINALIZE_READINESS_FAILED" for failure in result["report"]["failures"])
    assert not output.exists()
