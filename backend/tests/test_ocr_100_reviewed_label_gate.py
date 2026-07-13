from __future__ import annotations

import json
from pathlib import Path

from scripts.ocr_100_reviewed_label_gate import run_reviewed_label_gate


def ready_expected() -> dict:
    return {
        "qualityStatus": "auto_usable",
        "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [10, 10, 30, 20]}],
        "tables": [{"businessSchema": "piping_characteristic_table_v1", "bbox": [0, 10, 80, 40]}],
        "review": {
            "source": "human_review",
            "labeler": "annotator-a",
            "reviewer": "reviewer-b",
            "requiresHumanConfirmation": False,
        },
    }


def write_tasks(path: Path, tasks: list[dict]) -> None:
    path.write_text(json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2), encoding="utf-8")


def test_reviewed_label_gate_blocks_unreviewed_tasks(tmp_path: Path) -> None:
    tasks = tmp_path / "annotation_tasks.json"
    write_tasks(
        tasks,
        [
            {
                "taskId": "label-case-1",
                "caseId": "case-1",
                "scenario": "piping_table_profile",
                "profileId": "piping_characteristic_list_v1",
                "documentType": "engineering_table_photo",
                "collectionStatus": "needs_labeling",
                "sourcePath": "Scan/IMG_6509.heic",
                "expectedTemplate": {
                    "fields": [{"fieldCode": "replace-with-field", "value": "replace-with-label", "bbox": [0, 0, 0, 0]}],
                    "tables": [{"businessSchema": "replace-with-table", "bbox": [0, 0, 0, 0]}],
                },
            }
        ],
    )

    report = run_reviewed_label_gate(tasks, output_dir=tmp_path / "gate")

    assert report["ok"] is False
    assert report["summary"]["readinessOk"] is False
    assert report["summary"]["evalSetWritten"] is False
    assert {failure["code"] for failure in report["failures"]} == {
        "ANNOTATION_READINESS_NOT_READY",
        "OCR_100_SCORECARD_REQUIRED",
    }
    assert (tmp_path / "gate" / "readiness.json").exists()
    assert not (tmp_path / "gate" / "ocr_100_labeled_release_set.json").exists()


def test_reviewed_label_gate_exports_ready_release_eval_set(tmp_path: Path) -> None:
    tasks = tmp_path / "labeled_tasks.json"
    write_tasks(
        tasks,
        [
            {
                "taskId": "label-case-1",
                "caseId": "case-1",
                "scenario": "piping_table_profile",
                "profileId": "piping_characteristic_list_v1",
                "documentType": "engineering_table_photo",
                "collectionStatus": "ready_for_eval",
                "sourcePath": "Scan/IMG_6509.heic",
                "fileName": "IMG_6509.heic",
                "labeler": "annotator-a",
                "reviewer": "reviewer-b",
                "labeledExpected": ready_expected(),
            }
        ],
    )

    report = run_reviewed_label_gate(tasks, output_dir=tmp_path / "gate", certification_mode=False)
    eval_set = json.loads((tmp_path / "gate" / "ocr_100_labeled_release_set.json").read_text(encoding="utf-8"))

    assert report["ok"] is True
    assert report["summary"]["readyForEval"] == 1
    assert report["summary"]["exportOk"] is True
    assert report["summary"]["scorecardScore"] is None
    assert report["summary"]["certificationEligible"] is False
    assert eval_set["cases"][0]["collectionStatus"] == "ready_for_eval"
    assert eval_set["cases"][0]["expected"]["review"]["reviewer"] == "reviewer-b"


def test_reviewed_label_gate_certification_requires_scorecard(tmp_path: Path) -> None:
    tasks = tmp_path / "labeled_tasks.json"
    write_tasks(
        tasks,
        [
            {
                "taskId": "label-case-1",
                "caseId": "case-1",
                "scenario": "piping_table_profile",
                "profileId": "piping_characteristic_list_v1",
                "documentType": "engineering_table_photo",
                "collectionStatus": "ready_for_eval",
                "sourcePath": "Scan/IMG_6509.heic",
                "fileName": "IMG_6509.heic",
                "labeler": "annotator-a",
                "reviewer": "reviewer-b",
                "labeledExpected": ready_expected(),
            }
        ],
    )

    report = run_reviewed_label_gate(tasks, output_dir=tmp_path / "gate")

    assert report["ok"] is False
    assert report["summary"]["certificationEligible"] is False
    assert "OCR_100_SCORECARD_REQUIRED" in {item["code"] for item in report["failures"]}


def test_reviewed_label_gate_imports_label_studio_export_before_readiness(tmp_path: Path) -> None:
    tasks = tmp_path / "annotation_tasks.json"
    write_tasks(
        tasks,
        [
            {
                "taskId": "label-case-1",
                "caseId": "case-1",
                "scenario": "piping_table_profile",
                "profileId": "piping_characteristic_list_v1",
                "documentType": "engineering_table_photo",
                "sourcePath": "Scan/IMG_6509.heic",
                "fileName": "IMG_6509.heic",
            }
        ],
    )
    label_export = tmp_path / "label_studio_export.json"
    label_export.write_text(
        json.dumps(
            [
                {
                    "data": {"case_id": "case-1"},
                    "annotations": [
                        {
                            "id": 101,
                            "result": [
                                {
                                    "from_name": "label_json",
                                    "to_name": "image",
                                    "type": "textarea",
                                    "value": {"text": [json.dumps(ready_expected(), ensure_ascii=False)]},
                                }
                            ],
                        }
                    ],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = run_reviewed_label_gate(
        tasks,
        label_studio_export=label_export,
        output_dir=tmp_path / "gate",
        certification_mode=False,
    )
    labeled = json.loads((tmp_path / "gate" / "labeled_tasks.json").read_text(encoding="utf-8"))

    assert report["ok"] is True
    assert report["summary"]["importOk"] is True
    assert report["summary"]["readinessOk"] is True
    assert labeled["tasks"][0]["collectionStatus"] == "ready_for_eval"
    assert labeled["tasks"][0]["labeledExpected"]["fields"][0]["fieldCode"] == "pipe_no"
