from __future__ import annotations

import json

from scripts.ocr_100_label_studio_import import import_label_studio_annotations


def write_tasks(path, tasks):
    path.write_text(json.dumps({"tasks": tasks}, ensure_ascii=False), encoding="utf-8")


def test_label_studio_import_uses_label_json_textarea(tmp_path) -> None:
    tasks_file = tmp_path / "annotation_tasks.json"
    write_tasks(
        tasks_file,
        [
            {
                "taskId": "label-case-1",
                "caseId": "case-1",
                "scenario": "quality_certificate_profile",
                "profileId": "quality_certificate_v1",
                "documentType": "quality_certificate",
                "sourcePath": "Scan/sample.pdf",
                "expectedTemplate": {"fields": [{"fieldCode": "replace-with-core-field", "value": "replace-with-label", "bbox": [0, 0, 0, 0]}]},
            }
        ],
    )
    label_export = tmp_path / "label_studio_export.json"
    expected = {
        "qualityStatus": "auto_usable",
        "fields": [{"fieldCode": "certificate_no", "value": "QC-001", "bbox": [10, 20, 80, 45]}],
        "seals": [{"sealType": "company_official_seal", "nameContains": "测试公司", "bbox": [120, 30, 180, 90]}],
    }
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
                                    "value": {"text": [json.dumps(expected, ensure_ascii=False)]},
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

    report = import_label_studio_annotations(label_export, annotation_tasks=tasks_file, output_path=tmp_path / "out.json")
    output = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))

    assert report["ok"] is True
    assert report["summary"]["importedTasks"] == 1
    assert report["summary"]["jsonExpectedTasks"] == 1
    assert output["tasks"][0]["collectionStatus"] == "labeled"
    assert output["tasks"][0]["labeledExpected"]["fields"][0]["fieldCode"] == "certificate_no"
    assert output["tasks"][0]["certificationBlockers"] == []


def test_label_studio_import_builds_expected_from_regions_and_suggestions(tmp_path) -> None:
    tasks_file = tmp_path / "annotation_tasks.json"
    write_tasks(
        tasks_file,
        [
            {
                "taskId": "label-case-1",
                "caseId": "case-1",
                "scenario": "piping_table_profile",
                "profileId": "piping_characteristic_list_v1",
                "documentType": "engineering_table_photo",
                "sourcePath": "Scan/IMG_6509.heic",
                "expectedTemplate": {"qualityStatus": "auto_usable|needs_human_review|failed", "minEvidenceCompleteness": 0.95},
                "suggestedExpected": {
                    "fields": [
                        {
                            "fieldCode": "pipe_no",
                            "value": "PL8301",
                            "bbox": [5, 5, 25, 15],
                            "sourceEngine": "paddle_ocr_subprocess",
                        }
                    ],
                    "tables": [
                        {
                            "businessSchema": "piping_characteristic_table_v1",
                            "bbox": [10, 20, 90, 60],
                            "minRows": 10,
                            "minColumns": 12,
                            "sourceEngine": "opencv_table_grid_subprocess",
                        }
                    ]
                },
            }
        ],
    )
    label_export = tmp_path / "label_studio_export.json"
    label_export.write_text(
        json.dumps(
            [
                {
                    "data": {"case_id": "case-1"},
                    "meta": {"imageWidth": 100, "imageHeight": 100},
                    "annotations": [
                        {
                            "id": 102,
                            "updated_at": "2026-06-29T10:00:00Z",
                            "result": [
                                {
                                    "from_name": "quality_status",
                                    "type": "choices",
                                    "value": {"choices": ["auto_usable"]},
                                },
                                {
                                    "id": "r1",
                                    "from_name": "bbox",
                                    "to_name": "image",
                                    "type": "rectanglelabels",
                                    "value": {"x": 10, "y": 20, "width": 80, "height": 40, "rectanglelabels": ["Table"]},
                                },
                                {
                                    "id": "r2",
                                    "from_name": "bbox",
                                    "to_name": "image",
                                    "type": "rectanglelabels",
                                    "value": {"x": 5, "y": 5, "width": 20, "height": 10, "rectanglelabels": ["Field"]},
                                },
                            ],
                        }
                    ],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = import_label_studio_annotations(label_export, annotation_tasks=tasks_file, output_path=tmp_path / "out.json")
    output = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    table = output["tasks"][0]["labeledExpected"]["tables"][0]
    field = output["tasks"][0]["labeledExpected"]["fields"][0]

    assert report["ok"] is True
    assert report["summary"]["regionExpectedTasks"] == 1
    assert output["tasks"][0]["labeledExpected"]["qualityStatus"] == "auto_usable"
    assert field["bbox"] == [5, 5, 25, 15]
    assert field["fieldCode"] == "pipe_no"
    assert table["bbox"] == [10, 20, 90, 60]
    assert table["businessSchema"] == "piping_characteristic_table_v1"
    assert table["minRows"] == 10
    assert table["sourceEngine"] == "opencv_table_grid_subprocess"


def test_label_studio_import_leaves_placeholders_when_region_has_no_metadata(tmp_path) -> None:
    tasks_file = tmp_path / "annotation_tasks.json"
    write_tasks(
        tasks_file,
        [
            {
                "taskId": "label-case-1",
                "caseId": "case-1",
                "scenario": "seal_text_profile",
                "profileId": "seal_text_v1",
                "documentType": "sealed_document",
                "sourcePath": "Scan/sample.heic",
                "expectedTemplate": {"seals": [{"nameContains": "replace-with-seal-text", "bbox": [0, 0, 0, 0]}]},
            }
        ],
    )
    label_export = tmp_path / "label_studio_export.json"
    label_export.write_text(
        json.dumps(
            [
                {
                    "data": {"case_id": "case-1"},
                    "meta": {"imageWidth": 200, "imageHeight": 100},
                    "annotations": [
                        {
                            "id": 103,
                            "result": [
                                {
                                    "from_name": "bbox",
                                    "type": "rectanglelabels",
                                    "value": {"x": 25, "y": 20, "width": 50, "height": 40, "rectanglelabels": ["Seal"]},
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

    report = import_label_studio_annotations(label_export, annotation_tasks=tasks_file, output_path=tmp_path / "out.json")
    output = json.loads((tmp_path / "out.draft.json").read_text(encoding="utf-8"))
    seal = output["tasks"][0]["labeledExpected"]["seals"][0]

    assert seal["bbox"] == [50, 20, 150, 60]
    assert seal["nameContains"] == "replace-with-seal-text"
    assert "placeholder_labels" in output["tasks"][0]["certificationBlockers"]
    assert report["ok"] is False
    assert report["summary"]["failureCount"] >= 1
    assert report["summary"]["outputWritten"] is False


def test_label_studio_import_can_allow_incomplete_draft(tmp_path) -> None:
    tasks_file = tmp_path / "annotation_tasks.json"
    write_tasks(
        tasks_file,
        [
            {
                "taskId": "label-case-1",
                "caseId": "case-1",
                "scenario": "seal_text_profile",
                "profileId": "seal_text_v1",
                "documentType": "sealed_document",
                "sourcePath": "Scan/sample.heic",
                "expectedTemplate": {"seals": [{"nameContains": "replace-with-seal-text", "bbox": [0, 0, 0, 0]}]},
            }
        ],
    )
    label_export = tmp_path / "label_studio_export.json"
    label_export.write_text(
        json.dumps(
            [
                {
                    "data": {"case_id": "case-1"},
                    "meta": {"imageWidth": 200, "imageHeight": 100},
                    "annotations": [
                        {
                            "id": 103,
                            "result": [
                                {
                                    "from_name": "bbox",
                                    "type": "rectanglelabels",
                                    "value": {"x": 25, "y": 20, "width": 50, "height": 40, "rectanglelabels": ["Seal"]},
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

    report = import_label_studio_annotations(
        label_export,
        annotation_tasks=tasks_file,
        output_path=tmp_path / "out.json",
        allow_incomplete=True,
    )

    assert report["ok"] is True
    assert report["summary"]["allowIncomplete"] is True
    assert report["summary"]["failureCount"] >= 1


def test_label_studio_import_ignores_predictions_by_default(tmp_path) -> None:
    tasks_file = tmp_path / "annotation_tasks.json"
    write_tasks(
        tasks_file,
        [
            {
                "taskId": "label-case-1",
                "caseId": "case-1",
                "scenario": "piping_table_profile",
                "sourcePath": "Scan/sample.heic",
                "suggestedExpected": {"tables": [{"businessSchema": "table_v1", "bbox": [1, 2, 30, 40]}]},
            }
        ],
    )
    label_export = tmp_path / "label_studio_export.json"
    label_export.write_text(
        json.dumps(
            [
                {
                    "data": {"case_id": "case-1"},
                    "predictions": [
                        {
                            "result": [
                                {
                                    "from_name": "bbox",
                                    "type": "rectanglelabels",
                                    "value": {"x": 1, "y": 2, "width": 29, "height": 38, "rectanglelabels": ["Table"]},
                                }
                            ]
                        }
                    ],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = import_label_studio_annotations(label_export, annotation_tasks=tasks_file, output_path=tmp_path / "out.json")
    output = json.loads((tmp_path / "out.draft.json").read_text(encoding="utf-8"))

    assert report["summary"]["importedTasks"] == 0
    assert report["summary"]["skippedTasks"] == 1
    assert report["summary"]["outputWritten"] is False
    assert "labeledExpected" not in output["tasks"][0]
