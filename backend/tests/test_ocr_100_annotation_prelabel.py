from __future__ import annotations

import json
import os

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
                                    "businessSchemas": ["piping_characteristic_table_v1", "piping_characteristic_table"],
                                    "matchedRequiredTables": ["piping_characteristic_table"],
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
    assert task["suggestedExpected"]["tables"][0]["businessSchemas"] == [
        "piping_characteristic_table_v1",
        "piping_characteristic_table",
    ]
    assert task["suggestedExpected"]["tables"][0]["matchedRequiredTables"] == ["piping_characteristic_table"]
    assert task["suggestedExpected"]["seals"][0]["nameContains"] == "压力管道设计许可印章"
    assert task["prelabelSummary"]["blockers"] == []


def test_ocr_100_annotation_prelabel_normalizes_inverted_bbox_and_polygon(tmp_path) -> None:
    tasks = tmp_path / "annotation_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "taskId": "label-docling-bbox",
                        "caseId": "docling-bbox",
                        "scenario": "quality_certificate_profile",
                        "profileId": "quality_certificate_v1",
                        "sourcePath": "Scan/case.png",
                        "expectedTemplate": {},
                        "parseResult": {
                            "status": "success",
                            "fields": [
                                {
                                    "fieldCode": "manufacturer",
                                    "fieldValue": "河北广浩管件有限公司",
                                    "bbox": [250, 88, 642, 58],
                                    "confidence": 0.9,
                                }
                            ],
                            "tables": [
                                {
                                    "tableId": "docling_table_10",
                                    "businessSchema": "material_chemical_composition_table",
                                    "rows": 7,
                                    "columns": 7,
                                    "bbox": [20.99, 500.98, 403.61, 129.75],
                                    "structureConfidence": 0.9,
                                }
                            ],
                            "seals": [
                                {
                                    "sealName": "质检专用章",
                                    "polygon": [[700, 520], [900, 520], [900, 720], [700, 720]],
                                    "ocrConfidence": 0.88,
                                }
                            ],
                            "quality": {"status": "needs_human_review", "evidenceCompleteness": 1.0},
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    prelabel_annotation_tasks(tasks, output_path=tmp_path / "prelabel.json", source_base_dir=tmp_path)
    task = json.loads((tmp_path / "prelabel.json").read_text(encoding="utf-8"))["tasks"][0]

    assert task["suggestedExpected"]["fields"][0]["bbox"] == [250.0, 58.0, 642.0, 88.0]
    assert task["suggestedExpected"]["tables"][0]["bbox"] == [20.99, 129.75, 403.61, 500.98]
    assert task["suggestedExpected"]["seals"][0]["bbox"] == [700.0, 520.0, 900.0, 720.0]
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


def test_ocr_100_annotation_prelabel_run_ocr_prefers_pdf_preview(tmp_path) -> None:
    pack = tmp_path / "pack"
    previews = pack / "previews"
    previews.mkdir(parents=True)
    preview = previews / "case_p1.png"
    preview.write_bytes(b"png")
    source = tmp_path / "Scan" / "case.pdf"
    source.parent.mkdir()
    source.write_bytes(b"%PDF")
    tasks = pack / "annotation_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "taskId": "label-pdf",
                        "caseId": "pdf-case",
                        "scenario": "construction_record_profile",
                        "profileId": "construction_record_v1",
                        "documentType": "construction_record",
                        "sourcePath": str(source),
                        "previewPaths": ["previews/case_p1.png"],
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
            "fields": [{"fieldCode": "project_name", "fieldValue": "项目", "bbox": [0, 0, 10, 10]}],
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


def test_ocr_100_annotation_prelabel_passes_retry_options_and_timeouts(tmp_path, monkeypatch) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    source = pack / "case.png"
    source.write_bytes(b"png")
    tasks = pack / "annotation_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "caseId": "case-timeout",
                        "scenario": "seal_text_profile",
                        "sourcePath": str(source),
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    seen = {}
    monkeypatch.delenv("AICHECK_OCR_SUBPROCESS_TIMEOUT", raising=False)

    def fake_parse(case):
        seen["options"] = case["options"]
        seen["timeout"] = os.environ.get("AICHECK_OCR_SUBPROCESS_TIMEOUT")
        return {
            "status": "success",
            "seals": [{"sealName": "公司章", "bbox": [1, 1, 10, 10]}],
            "quality": {"status": "auto_usable"},
        }

    report = prelabel_annotation_tasks(
        pack,
        output_path=tmp_path / "prelabel.json",
        source_base_dir=tmp_path,
        run_ocr=True,
        disable_result_cache=True,
        disable_remediation=True,
        engine_timeout_seconds=12,
        parse_runner=fake_parse,
    )

    assert seen["options"] == {"disableResultCache": True, "disableRemediation": True}
    assert seen["timeout"] == "12.0"
    assert os.environ.get("AICHECK_OCR_SUBPROCESS_TIMEOUT") is None
    assert report["summary"]["engineTimeoutSeconds"] == 12
    assert report["summary"]["disableRemediation"] is True


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
