from __future__ import annotations

import json

from scripts.ocr_100_annotation_export import export_annotation_tasks


def test_ocr_100_annotation_export_rejects_placeholders(tmp_path) -> None:
    tasks = tmp_path / "annotation_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "taskId": "label-real-piping",
                        "caseId": "real-piping",
                        "scenario": "piping_table_profile",
                        "profileId": "piping_characteristic_list_v1",
                        "documentType": "engineering_table_photo",
                        "collectionStatus": "needs_labeling",
                        "sourcePath": "Scan/IMG_6509.heic",
                        "fileName": "IMG_6509.heic",
                        "expectedTemplate": {
                            "fields": [{"fieldCode": "replace-with-core-field", "value": "replace-with-label", "bbox": [0, 0, 0, 0]}],
                            "tables": [{"businessSchema": "replace-with-table-schema", "bbox": [0, 0, 0, 0]}],
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = export_annotation_tasks(tasks, output_path=tmp_path / "release.json")
    codes = {failure["code"] for failure in report["failures"]}

    assert report["ok"] is False
    assert report["summary"]["outputWritten"] is False
    assert "OCR_100_ANNOTATION_INCOMPLETE" in codes
    assert "OCR_100_CORPUS_EXPECTED_EVIDENCE_MISSING" in codes
    assert not (tmp_path / "release.json").exists()


def test_ocr_100_annotation_export_writes_labeled_eval_set(tmp_path) -> None:
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    tasks = pack_dir / "annotation_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "taskId": "label-real-piping",
                        "caseId": "real-piping",
                        "scenario": "piping_table_profile",
                        "profileId": "piping_characteristic_list_v1",
                        "documentType": "engineering_table_photo",
                        "collectionStatus": "needs_labeling",
                        "sourcePath": "Scan/IMG_6509.heic",
                        "fileName": "IMG_6509.heic",
                        "labeler": "annotator-1",
                        "labeledExpected": {
                            "qualityStatus": "auto_usable",
                            "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [10, 20, 200, 80]}],
                            "tables": [{"businessSchema": "piping_characteristic_table_v1", "bbox": [10, 90, 800, 500]}],
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = export_annotation_tasks(pack_dir, output_path=tmp_path / "release.json")
    payload = json.loads((tmp_path / "release.json").read_text(encoding="utf-8"))

    assert report["ok"] is True
    assert report["summary"]["outputWritten"] is True
    assert payload["cases"][0]["collectionStatus"] == "labeled"
    assert payload["cases"][0]["annotation"]["labeler"] == "annotator-1"
    assert payload["cases"][0]["expected"]["fields"][0]["fieldCode"] == "pipe_no"


def test_ocr_100_annotation_export_rejects_machine_draft_labels(tmp_path) -> None:
    tasks = tmp_path / "annotation_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "taskId": "label-real-piping",
                        "caseId": "real-piping",
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
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = export_annotation_tasks(tasks, output_path=tmp_path / "release.json")
    codes = {failure["code"] for failure in report["failures"]}

    assert report["ok"] is False
    assert "OCR_100_ANNOTATION_MACHINE_DRAFT_NOT_CONFIRMED" in codes
    assert not (tmp_path / "release.json").exists()


def test_ocr_100_annotation_export_can_write_incomplete_for_review(tmp_path) -> None:
    tasks = tmp_path / "annotation_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "caseId": "real-pending",
                        "scenario": "seal_text_profile",
                        "profileId": "seal_text_v1",
                        "documentType": "sealed_document",
                        "sourcePath": "Scan/IMG_6524.heic",
                        "expectedTemplate": {"seals": [{"nameContains": "replace-with-seal-text", "bbox": [0, 0, 0, 0]}]},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = export_annotation_tasks(tasks, output_path=tmp_path / "draft.json", allow_incomplete=True)

    assert report["ok"] is True
    assert report["summary"]["failureCount"] > 0
    assert report["summary"]["outputWritten"] is True
    assert (tmp_path / "draft.json").exists()
