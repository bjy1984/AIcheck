from __future__ import annotations

import json

from scripts.ocr_100_annotation_prelabel import prelabel_annotation_tasks


def test_ocr_100_annotation_prelabel_uses_embedded_parse_result(tmp_path) -> None:
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
                        "sourcePath": "Scan/IMG_6509.heic",
                        "expectedTemplate": {},
                        "parseResult": {
                            "status": "success",
                            "fields": [
                                {"fieldCode": "pipe_no", "fieldValue": "PL8301", "bbox": [10, 20, 200, 80], "confidence": 0.91}
                            ],
                            "tables": [
                                {
                                    "tableId": "T1",
                                    "businessSchema": "piping_characteristic_table_v1",
                                    "rows": 12,
                                    "columns": 8,
                                    "bbox": [10, 90, 800, 500],
                                    "businessRows": [{"pipeNo": "PL8301", "medium": "water"}],
                                }
                            ],
                            "seals": [{"sealName": "压力管道设计许可印章", "bbox": [700, 520, 900, 720], "ocrConfidence": 0.88}],
                            "quality": {"status": "auto_usable", "evidenceCompleteness": 1.0},
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = prelabel_annotation_tasks(tasks, output_path=tmp_path / "prelabel.json", source_base_dir=tmp_path)
    output = json.loads((tmp_path / "prelabel.json").read_text(encoding="utf-8"))
    task = output["tasks"][0]

    assert report["summary"]["suggested"] == 1
    assert task["prelabelStatus"] == "suggested"
    assert task["suggestedExpected"]["fields"][0]["fieldCode"] == "pipe_no"
    assert task["suggestedExpected"]["tables"][0]["requiredBusinessKeys"] == ["medium", "pipeNo"]
    assert task["suggestedExpected"]["seals"][0]["nameContains"] == "压力管道设计许可印章"
    assert task["prelabelSummary"]["blockers"] == []


def test_ocr_100_annotation_prelabel_uses_result_dir(tmp_path) -> None:
    tasks = tmp_path / "annotation_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "taskId": "label-real-seal",
                        "caseId": "real-seal",
                        "scenario": "seal_text_profile",
                        "profileId": "seal_text_v1",
                        "documentType": "sealed_document",
                        "sourcePath": "Scan/IMG_6524.heic",
                        "expectedTemplate": {},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    (result_dir / "real-seal.json").write_text(
        json.dumps(
            {
                "status": "success",
                "seals": [{"sealName": "设计许可印章", "bbox": [1, 2, 30, 40]}],
                "quality": {"status": "auto_usable"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    prelabel_annotation_tasks(tasks, output_path=tmp_path / "prelabel.json", source_base_dir=tmp_path, result_dir=result_dir)
    task = json.loads((tmp_path / "prelabel.json").read_text(encoding="utf-8"))["tasks"][0]

    assert task["prelabelSummary"]["source"] == "result_dir"
    assert task["suggestedExpected"]["seals"][0]["bbox"] == [1, 2, 30, 40]


def test_ocr_100_annotation_prelabel_run_ocr_prefers_heic_preview(tmp_path) -> None:
    pack = tmp_path / "pack"
    previews = pack / "previews"
    previews.mkdir(parents=True)
    preview = previews / "case_image.png"
    preview.write_bytes(b"png")
    tasks = pack / "annotation_tasks.json"
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
                        "sourcePath": "Scan/IMG_6509.heic",
                        "previewPaths": ["previews/case_image.png"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    seen = {}

    def fake_parse(case):
        seen["source"] = case["source"]
        return {
            "status": "success",
            "fields": [{"fieldCode": "pipe_no", "fieldValue": "PL8301", "bbox": [0, 0, 10, 10]}],
            "quality": {"status": "auto_usable"},
        }

    prelabel_annotation_tasks(
        pack,
        output_path=tmp_path / "prelabel.json",
        source_base_dir=tmp_path,
        run_ocr=True,
        parse_runner=fake_parse,
    )

    assert seen["source"] == str(preview.resolve())


def test_ocr_100_annotation_prelabel_filters_case_ids(tmp_path) -> None:
    tasks = tmp_path / "annotation_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {"caseId": "case-a", "scenario": "seal_text_profile", "sourcePath": "a.png"},
                    {"caseId": "case-b", "scenario": "seal_text_profile", "sourcePath": "b.png"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = prelabel_annotation_tasks(
        tasks,
        output_path=tmp_path / "prelabel.json",
        source_base_dir=tmp_path,
        case_ids=["case-b"],
    )
    output = json.loads((tmp_path / "prelabel.json").read_text(encoding="utf-8"))

    assert report["summary"]["sourceTasks"] == 2
    assert report["summary"]["tasks"] == 1
    assert output["tasks"][0]["caseId"] == "case-b"


def test_ocr_100_annotation_prelabel_saves_raw_result_artifacts(tmp_path) -> None:
    tasks = tmp_path / "annotation_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "caseId": "case-a",
                        "scenario": "seal_text_profile",
                        "sourcePath": "a.png",
                        "parseResult": {
                            "status": "success",
                            "seals": [{"sealName": "设计许可印章", "bbox": [1, 2, 30, 40]}],
                            "quality": {"status": "auto_usable"},
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    save_dir = tmp_path / "raw"

    report = prelabel_annotation_tasks(
        tasks,
        output_path=tmp_path / "prelabel.json",
        source_base_dir=tmp_path,
        save_result_dir=save_dir,
    )
    raw = json.loads((save_dir / "case-a.json").read_text(encoding="utf-8"))

    assert raw["status"] == "success"
    assert raw["seals"][0]["sealName"] == "设计许可印章"
    assert report["summary"]["events"][0]["savedResultPath"].endswith("case-a.json")


def test_ocr_100_annotation_prelabel_saves_failed_result_artifacts(tmp_path) -> None:
    tasks = tmp_path / "annotation_tasks.json"
    tasks.write_text(
        json.dumps({"tasks": [{"caseId": "case-a", "scenario": "seal_text_profile", "sourcePath": "missing.png"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    save_dir = tmp_path / "raw"

    prelabel_annotation_tasks(
        tasks,
        output_path=tmp_path / "prelabel.json",
        source_base_dir=tmp_path,
        run_ocr=True,
        save_result_dir=save_dir,
    )
    raw = json.loads((save_dir / "case-a.json").read_text(encoding="utf-8"))

    assert raw["status"] == "failed"
    assert raw["diagnostics"][0]["code"] == "OCR_PRELABEL_FAILED"
