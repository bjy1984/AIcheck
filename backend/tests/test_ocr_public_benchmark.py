from __future__ import annotations

import json

from apps.ocr_service.public_benchmarks import build_public_benchmark_index, public_dataset_registry


def test_public_dataset_registry_marks_public_sets_as_foundation_only() -> None:
    registry = public_dataset_registry()

    assert registry["productionCertificationEligible"] is False
    assert {"doclaynet", "pubtabnet", "ctdar"} <= set(registry["datasets"])
    assert registry["datasets"]["doclaynet"]["sourceUrl"].startswith("https://")


def test_doclaynet_public_benchmark_indexes_coco_layout_cases(tmp_path) -> None:
    image = tmp_path / "page.png"
    image.write_bytes(b"fake")
    (tmp_path / "val.json").write_text(
        json.dumps(
            {
                "images": [{"id": 1, "file_name": "page.png", "width": 100, "height": 200}],
                "categories": [{"id": 7, "name": "Table"}],
                "annotations": [{"image_id": 1, "category_id": 7, "bbox": [10, 20, 30, 40], "area": 1200}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_public_benchmark_index("doclaynet", tmp_path, split="val")

    assert report["ok"] is True
    assert report["foundationBenchmark"] is True
    assert report["productionCertificationEligible"] is False
    assert report["summary"]["cases"] == 1
    assert report["summary"]["expectedLayoutBlocks"] == 1
    assert report["cases"][0]["expected"]["layoutBlocks"][0]["label"] == "Table"
    assert report["cases"][0]["expected"]["layoutBlocks"][0]["bbox"] == [10.0, 20.0, 40.0, 60.0]


def test_pubtabnet_public_benchmark_indexes_html_table_cases(tmp_path) -> None:
    image = tmp_path / "PMC_1.png"
    image.write_bytes(b"fake")
    (tmp_path / "PubTabNet_2.0.0.jsonl").write_text(
        json.dumps(
            {
                "filename": "PMC_1.png",
                "split": "val",
                "html": {"structure": {"tokens": ["<table>", "</table>"]}, "cells": [{"tokens": ["A"]}]},
                "bbox": [1, 2, 30, 40],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_public_benchmark_index("pubtabnet", tmp_path, split="val")

    assert report["ok"] is True
    assert report["summary"]["expectedTables"] == 1
    assert report["summary"]["expectedTableCells"] == 1
    table = report["cases"][0]["expected"]["tables"][0]
    assert table["html"] == "<table></table>"
    assert table["bbox"] == [1.0, 2.0, 30.0, 40.0]


def test_ctdar_public_benchmark_indexes_table_polygons(tmp_path) -> None:
    (tmp_path / "doc.png").write_bytes(b"fake")
    (tmp_path / "doc.xml").write_text(
        '<PcGts><Page><TableRegion id="t1"><Coords points="0,0 10,0 10,20 0,20"/></TableRegion></Page></PcGts>',
        encoding="utf-8",
    )

    report = build_public_benchmark_index("ctdar", tmp_path)

    assert report["ok"] is True
    assert report["summary"]["expectedTables"] == 1
    table = report["cases"][0]["expected"]["tables"][0]
    assert table["polygon"] == [[0.0, 0.0], [10.0, 0.0], [10.0, 20.0], [0.0, 20.0]]
    assert table["bbox"] == [0.0, 0.0, 10.0, 20.0]


def test_public_benchmark_missing_root_reports_blocker(tmp_path) -> None:
    report = build_public_benchmark_index("doclaynet", tmp_path / "missing")

    assert report["ok"] is False
    assert "dataset root does not exist" in report["blockers"][0]
