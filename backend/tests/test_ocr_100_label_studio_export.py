from __future__ import annotations

import json
import struct
import zlib

from scripts.ocr_100_label_studio_export import export_label_studio_pack


def png_bytes(width: int, height: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return len(payload).to_bytes(4, "big") + kind + payload + checksum.to_bytes(4, "big")

    raw = b"\x00" + b"\xff\xff\xff" * width
    data = raw * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(data))
        + chunk(b"IEND", b"")
    )


def test_label_studio_export_writes_config_tasks_and_predictions(tmp_path) -> None:
    pack = tmp_path / "pack"
    previews = pack / "previews"
    previews.mkdir(parents=True)
    (previews / "sample.png").write_bytes(png_bytes(100, 50))
    (pack / "annotation_tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "taskId": "label-case-1",
                        "caseId": "case-1",
                        "scenario": "piping_table_profile",
                        "profileId": "piping_characteristic_list_v1",
                        "documentType": "engineering_table_photo",
                        "sourcePath": "Scan/IMG_6509.heic",
                        "previewPaths": ["previews/sample.png"],
                        "suggestedExpected": {
                            "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [10, 5, 30, 15]}],
                            "tables": [{"businessSchema": "table_v1", "bbox": [0, 10, 80, 40]}],
                            "seals": [{"nameContains": "设计许可", "bbox": [60, 20, 90, 45]}],
                        },
                        "prelabelStatus": "suggested",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = export_label_studio_pack(pack, output_dir=tmp_path / "out")
    tasks = json.loads((tmp_path / "out" / "label_studio_tasks.json").read_text(encoding="utf-8"))
    config = (tmp_path / "out" / "label_config.xml").read_text(encoding="utf-8")

    assert report["ok"] is True
    assert report["summary"]["tasks"] == 1
    assert report["summary"]["predictionTasks"] == 1
    assert tasks[0]["data"]["image"] == "/data/local-files/?d=previews/sample.png"
    assert len(tasks[0]["predictions"][0]["result"]) == 3
    assert tasks[0]["predictions"][0]["result"][0]["value"]["x"] == 10.0
    assert tasks[0]["predictions"][0]["result"][0]["value"]["width"] == 20.0
    assert "<RectangleLabels" in config
    assert "label_json" in config


def test_label_studio_export_skips_tasks_without_preview_by_default(tmp_path) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "annotation_tasks.json").write_text(
        json.dumps({"tasks": [{"caseId": "case-1", "scenario": "seal_text_profile", "sourcePath": "missing.png"}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    report = export_label_studio_pack(pack, output_dir=tmp_path / "out")
    tasks = json.loads((tmp_path / "out" / "label_studio_tasks.json").read_text(encoding="utf-8"))

    assert report["ok"] is False
    assert report["summary"]["tasks"] == 0
    assert report["summary"]["skipped"] == 1
    assert tasks == []


def test_label_studio_export_can_allow_skipped_draft_batches(tmp_path) -> None:
    pack = tmp_path / "pack"
    previews = pack / "previews"
    previews.mkdir(parents=True)
    (previews / "sample.png").write_bytes(png_bytes(100, 50))
    (pack / "annotation_tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "caseId": "case-1",
                        "scenario": "seal_text_profile",
                        "sourcePath": "Scan/sample.png",
                        "previewPaths": ["previews/sample.png"],
                    },
                    {"caseId": "case-2", "scenario": "seal_text_profile", "sourcePath": "missing.png"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = export_label_studio_pack(pack, output_dir=tmp_path / "out", allow_skipped=True)

    assert report["ok"] is True
    assert report["summary"]["allowSkipped"] is True
    assert report["summary"]["tasks"] == 1
    assert report["summary"]["skipped"] == 1


def test_label_studio_export_supports_external_preview_base_dir(tmp_path) -> None:
    preview_root = tmp_path / "pack"
    previews = preview_root / "previews"
    previews.mkdir(parents=True)
    (previews / "sample.png").write_bytes(png_bytes(100, 50))
    tasks_file = tmp_path / "prelabelled.json"
    tasks_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "caseId": "case-1",
                        "scenario": "piping_table_profile",
                        "previewPaths": ["previews/sample.png"],
                        "suggestedExpected": {"tables": [{"businessSchema": "table_v1", "bbox": [10, 10, 80, 40]}]},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = export_label_studio_pack(
        tasks_file,
        output_dir=tmp_path / "out",
        preview_base_dir=preview_root,
        local_files_root=preview_root,
    )
    tasks = json.loads((tmp_path / "out" / "label_studio_tasks.json").read_text(encoding="utf-8"))

    assert report["ok"] is True
    assert report["summary"]["tasks"] == 1
    assert report["summary"]["predictionTasks"] == 1
    assert tasks[0]["data"]["image"] == "/data/local-files/?d=previews/sample.png"


def test_label_studio_export_filters_predictions_for_page_level_tasks(tmp_path) -> None:
    pack = tmp_path / "pack"
    previews = pack / "previews"
    previews.mkdir(parents=True)
    (previews / "sample_p2.png").write_bytes(png_bytes(100, 50))
    (pack / "annotation_tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "taskId": "label-case-1-p2",
                        "parentTaskId": "label-case-1",
                        "caseId": "case-1",
                        "scenario": "piping_table_profile",
                        "pageNo": 2,
                        "previewPaths": ["previews/sample_p2.png"],
                        "suggestedExpected": {
                            "fields": [
                                {"fieldCode": "pipe_no", "value": "P1", "pageNo": 1, "bbox": [10, 5, 30, 15]},
                                {"fieldCode": "pipe_no", "value": "P2", "pageNo": 2, "bbox": [20, 5, 40, 15]},
                            ]
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = export_label_studio_pack(pack, output_dir=tmp_path / "out")
    tasks = json.loads((tmp_path / "out" / "label_studio_tasks.json").read_text(encoding="utf-8"))

    assert report["ok"] is True
    assert tasks[0]["data"]["page_no"] == 2
    assert tasks[0]["meta"]["parentTaskId"] == "label-case-1"
    assert len(tasks[0]["predictions"][0]["result"]) == 1
    assert tasks[0]["predictions"][0]["result"][0]["meta"]["pageNo"] == 2
