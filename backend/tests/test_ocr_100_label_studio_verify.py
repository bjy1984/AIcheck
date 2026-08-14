from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

from scripts.ocr_100_label_studio_export import export_label_studio_pack
from scripts.ocr_100_label_studio_verify import (
    label_studio_verify_markdown,
    verify_label_studio_pack,
)


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


def test_label_studio_verify_accepts_complete_export(tmp_path: Path) -> None:
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
                        "sourcePath": "Scan/IMG_6509.heic",
                        "previewPaths": ["previews/sample.png"],
                        "suggestedExpected": {
                            "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [10, 5, 30, 15]}]
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    export_label_studio_pack(pack, output_dir=out)

    report = verify_label_studio_pack(out, annotation_tasks=pack)
    markdown = label_studio_verify_markdown(report)

    assert report["ok"] is True
    assert report["summary"]["tasks"] == 1
    assert report["summary"]["predictionTasks"] == 1
    assert report["summary"]["imageFailures"] == 0
    assert "ready for human annotation" in markdown


def test_label_studio_verify_rejects_missing_preview_image(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "label_config.xml").write_text("<View><RectangleLabels name=\"bbox\" toName=\"image\" /></View>", encoding="utf-8")
    (out / "label_studio_summary.json").write_text(
        json.dumps(
            {
                "tasks": 1,
                "sourceTasks": 1,
                "predictionTasks": 0,
                "skipped": 0,
                "localFilesRoot": str(tmp_path),
                "imageUrlPrefix": "/data/local-files/?d=",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (out / "label_studio_tasks.json").write_text(
        json.dumps(
            [
                {
                    "data": {"image": "/data/local-files/?d=missing.png", "case_id": "case-1"},
                    "meta": {"imageWidth": 100, "imageHeight": 50},
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = verify_label_studio_pack(out)

    assert report["ok"] is False
    assert report["summary"]["imageFailures"] == 1
    assert report["failures"][0]["code"] == "LABEL_STUDIO_IMAGE_MISSING"


def test_label_studio_verify_reports_summary_count_mismatch(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    image = tmp_path / "sample.png"
    image.write_bytes(png_bytes(100, 50))
    (out / "label_config.xml").write_text("<View><RectangleLabels name=\"bbox\" toName=\"image\" /></View>", encoding="utf-8")
    (out / "label_studio_summary.json").write_text(
        json.dumps(
            {
                "tasks": 2,
                "sourceTasks": 2,
                "predictionTasks": 0,
                "skipped": 0,
                "localFilesRoot": str(tmp_path),
                "imageUrlPrefix": "/data/local-files/?d=",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (out / "label_studio_tasks.json").write_text(
        json.dumps(
            [
                {
                    "data": {"image": "/data/local-files/?d=sample.png", "case_id": "case-1"},
                    "meta": {"imageWidth": 100, "imageHeight": 50},
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = verify_label_studio_pack(out)

    assert report["ok"] is False
    assert any(item["code"] == "LABEL_STUDIO_SUMMARY_TASK_COUNT_MISMATCH" for item in report["failures"])
