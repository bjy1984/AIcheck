from __future__ import annotations

import subprocess

from apps.ocr_service import engines
from scripts import ocr_prefetch_models
from scripts.ocr_prefetch_models import prefetch_report


def test_paddlex_seal_engine_available_with_subprocess_runtime(monkeypatch, tmp_path) -> None:
    seal_det = tmp_path / "PP-OCRv4_server_seal_det"
    seal_rec = tmp_path / "PP-OCRv4_server_rec"
    seal_det.mkdir()
    seal_rec.mkdir()
    python_bin = tmp_path / "python"
    python_bin.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setenv("AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE", "true")
    monkeypatch.setenv("AICHECK_OCR_SUBPROCESS_PYTHON", str(python_bin))
    monkeypatch.setenv("AICHECK_SEAL_DET_MODEL_DIR", str(seal_det))
    monkeypatch.setenv("AICHECK_SEAL_REC_MODEL_DIR", str(seal_rec))
    monkeypatch.setattr(engines, "subprocess_package_available", lambda package: package == "paddlex")

    engine = engines.PaddlexSealEngine()
    status = engine.status()

    assert engine.available() is True
    assert status["available"] is True
    assert status["executionMode"] in {"inprocess", "subprocess"}
    assert status["missingModelDirs"] == []


def test_paddlex_seal_engine_auto_enables_when_local_models_exist(monkeypatch, tmp_path) -> None:
    seal_det = tmp_path / "PP-OCRv4_server_seal_det"
    seal_rec = tmp_path / "PP-OCRv4_server_rec"
    seal_det.mkdir()
    seal_rec.mkdir()
    python_bin = tmp_path / "python"
    python_bin.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.delenv("AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE", raising=False)
    monkeypatch.setenv("AICHECK_OCR_SUBPROCESS_PYTHON", str(python_bin))
    monkeypatch.setenv("AICHECK_SEAL_DET_MODEL_DIR", str(seal_det))
    monkeypatch.setenv("AICHECK_SEAL_REC_MODEL_DIR", str(seal_rec))
    monkeypatch.setattr(engines, "subprocess_package_available", lambda package: package == "paddlex")

    engine = engines.PaddlexSealEngine()
    status = engine.status()

    assert engine.available() is True
    assert status["enabled"] == "auto"


def test_paddlex_seal_engine_can_be_explicitly_disabled(monkeypatch, tmp_path) -> None:
    seal_det = tmp_path / "PP-OCRv4_server_seal_det"
    seal_rec = tmp_path / "PP-OCRv4_server_rec"
    seal_det.mkdir()
    seal_rec.mkdir()
    python_bin = tmp_path / "python"
    python_bin.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setenv("AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE", "false")
    monkeypatch.setenv("AICHECK_OCR_SUBPROCESS_PYTHON", str(python_bin))
    monkeypatch.setenv("AICHECK_SEAL_DET_MODEL_DIR", str(seal_det))
    monkeypatch.setenv("AICHECK_SEAL_REC_MODEL_DIR", str(seal_rec))
    monkeypatch.setattr(engines, "subprocess_package_available", lambda package: package == "paddlex")

    engine = engines.PaddlexSealEngine()

    assert engine.available() is False


def test_pp_structure_engine_available_with_subprocess_runtime(monkeypatch, tmp_path) -> None:
    model_names = [
        "PP-DocLayout-L",
        "PP-OCRv6_medium_det",
        "PP-OCRv6_medium_rec",
        "SLANeXt_wired",
        "RT-DETR-L_wired_table_cell_det",
        "SLANeXt_wireless",
        "RT-DETR-L_wireless_table_cell_det",
    ]
    for model_name in model_names:
        (tmp_path / model_name).mkdir()
    python_bin = tmp_path / "python"
    python_bin.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setenv("AICHECK_OCR_SUBPROCESS_PYTHON", str(python_bin))
    monkeypatch.setenv("AICHECK_PPSTRUCTURE_LAYOUT_MODEL_DIR", str(tmp_path / "PP-DocLayout-L"))
    monkeypatch.setenv("AICHECK_PADDLEOCR_DET_MODEL_DIR", str(tmp_path / "PP-OCRv6_medium_det"))
    monkeypatch.setenv("AICHECK_PADDLEOCR_REC_MODEL_DIR", str(tmp_path / "PP-OCRv6_medium_rec"))
    monkeypatch.setenv("AICHECK_PPSTRUCTURE_WIRED_TABLE_STRUCTURE_MODEL_DIR", str(tmp_path / "SLANeXt_wired"))
    monkeypatch.setenv("AICHECK_PPSTRUCTURE_WIRED_TABLE_CELLS_MODEL_DIR", str(tmp_path / "RT-DETR-L_wired_table_cell_det"))
    monkeypatch.setenv("AICHECK_PPSTRUCTURE_WIRELESS_TABLE_STRUCTURE_MODEL_DIR", str(tmp_path / "SLANeXt_wireless"))
    monkeypatch.setenv("AICHECK_PPSTRUCTURE_WIRELESS_TABLE_CELLS_MODEL_DIR", str(tmp_path / "RT-DETR-L_wireless_table_cell_det"))
    monkeypatch.setattr(engines, "subprocess_package_available", lambda package: package == "paddleocr")

    engine = engines.PpStructureEngine()
    status = engine.status()

    assert engine.available() is True
    assert status["available"] is True
    assert status["executionMode"] in {"inprocess", "subprocess"}
    assert status["missingModelDirs"] == []


def test_vl_and_docling_engines_can_report_subprocess_availability(monkeypatch, tmp_path) -> None:
    python_bin = tmp_path / "python"
    python_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    vl_dir = tmp_path / "paddleocr-vl"
    vl_layout_dir = vl_dir / "PP-DocLayoutV3"
    vl_rec_dir = vl_dir / "PaddleOCR-VL-1.6-0.9B"
    docling_dir = tmp_path / "docling"
    vl_layout_dir.mkdir(parents=True)
    vl_rec_dir.mkdir()
    docling_dir.mkdir()
    (docling_dir / "artifact.lock").write_text("local-docling-artifact", encoding="utf-8")

    monkeypatch.setenv("AICHECK_OCR_SUBPROCESS_PYTHON", str(python_bin))
    monkeypatch.setenv("PADDLEOCR_VL_MODEL_DIR", str(vl_dir))
    monkeypatch.setenv("AICHECK_PADDLEOCR_VL_LAYOUT_MODEL_DIR", str(vl_layout_dir))
    monkeypatch.setenv("AICHECK_PADDLEOCR_VL_REC_MODEL_DIR", str(vl_rec_dir))
    monkeypatch.setenv("DOCLING_ARTIFACTS_PATH", str(docling_dir))
    monkeypatch.setattr(
        engines,
        "subprocess_package_available",
        lambda package: package in {"paddleocr", "docling", "transformers"},
    )

    vl_status = engines.PaddleOcrVlEngine().status()
    docling_status = engines.DoclingLocalEngine().status()

    assert vl_status["available"] is True
    assert vl_status["missingModelDirs"] == []
    assert vl_status["executionMode"] in {"inprocess", "subprocess"}
    assert docling_status["available"] is True
    assert docling_status["executionMode"] in {"inprocess", "subprocess"}


def test_vl_engine_accepts_paddlex_vl_1_6_alias(monkeypatch, tmp_path) -> None:
    python_bin = tmp_path / "python"
    python_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    vl_dir = tmp_path / "paddleocr-vl"
    (vl_dir / "PP-DocLayoutV3").mkdir(parents=True)
    (vl_dir / "PaddleOCR-VL-1.6").mkdir()

    monkeypatch.setenv("AICHECK_OCR_SUBPROCESS_PYTHON", str(python_bin))
    monkeypatch.setenv("PADDLEOCR_VL_MODEL_DIR", str(vl_dir))
    monkeypatch.setattr(
        engines,
        "subprocess_package_available",
        lambda package: package in {"paddleocr", "transformers"},
    )

    status = engines.PaddleOcrVlEngine().status()

    assert status["available"] is True
    assert status["missingModelDirs"] == []
    assert status["modelDirs"]["vl_rec"].endswith("PaddleOCR-VL-1.6")


def test_vl_and_docling_engines_require_explicit_model_artifact_paths(monkeypatch, tmp_path) -> None:
    python_bin = tmp_path / "python"
    python_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("AICHECK_OCR_SUBPROCESS_PYTHON", str(python_bin))
    monkeypatch.delenv("PADDLEOCR_VL_MODEL_DIR", raising=False)
    monkeypatch.delenv("DOCLING_ARTIFACTS_PATH", raising=False)
    monkeypatch.setattr(
        engines,
        "subprocess_package_available",
        lambda package: package in {"paddleocr", "docling"},
    )

    assert engines.PaddleOcrVlEngine().status()["available"] is False
    assert engines.DoclingLocalEngine().status()["available"] is False


def test_normalize_paddlex_seal_result_expands_json_payload_without_false_positive() -> None:
    raw = [
        {
            "res": {
                "layout_det_res": {"boxes": [{"label": "table", "score": 0.9}]},
                "seal_res_list": [],
            }
        },
        {
            "res": {
                "seal_res_list": [
                    {
                        "coordinate": [10, 20, 110, 140],
                        "seal_rec_res": {
                            "rec_texts": ["广东星燃石化设计院有限公司", "压力管道", "专用章"],
                            "rec_scores": [0.93, 0.91, 0.9],
                        },
                    }
                ]
            }
        },
    ]

    seals = engines.normalize_seal_result(raw)

    assert len(seals) == 1
    assert seals[0]["bbox"] == [10.0, 20.0, 110.0, 140.0]
    assert "广东星燃石化设计院有限公司" in seals[0]["sealName"]
    assert seals[0]["ocrConfidence"] > 0.9


def test_normalize_paddlex_seal_result_accepts_generator() -> None:
    raw = (item for item in [{"sealName": "测试专用章", "bbox": [1, 2, 3, 4], "score": 0.88}])

    seals = engines.normalize_seal_result(raw)

    assert seals[0]["sealName"] == "测试专用章"
    assert seals[0]["bbox"] == [1, 2, 3, 4]


def test_normalize_structure_result_expands_paddlex_json_payload() -> None:
    raw = [
        {
            "res": {
                "layout_det_res": {
                    "boxes": [
                        {"label": "table", "score": 0.92, "coordinate": [0, 0, 100, 80], "res": {"html": "<table><tr><th>管号</th></tr><tr><td>PL8301</td></tr></table>"}},
                        {"label": "text", "score": 0.88, "coordinate": [120, 0, 240, 60]},
                    ]
                }
            }
        }
    ]

    tables, blocks = engines.normalize_structure_result(raw, "pp_structure_v3")

    assert len(blocks) == 2
    assert len(tables) == 1
    assert tables[0]["rows"] == 2
    assert tables[0]["columns"] == 1


def test_normalize_vl_result_extracts_markdown_html_and_layout() -> None:
    raw = [
        {
            "pageNo": 1,
            "markdown": "# 管道特性表\n\n| 管号 | 口径 |\n| --- | --- |\n| PL8301 | DN100 |",
            "html": "<table><tr><th>管号</th><th>口径</th></tr><tr><td>PL8301</td><td>DN100</td></tr></table>",
            "layout_det_res": {"boxes": [{"label": "table", "coordinate": [10, 20, 100, 120], "score": 0.9}]},
        }
    ]

    text, fragments, tables, blocks = engines.normalize_vl_result(raw, "paddleocr_vl_1_6")

    assert "管道特性表" in text
    assert fragments[0]["sourceEngine"] == "paddleocr_vl_1_6"
    assert fragments[0]["confidence"] == 0.66
    assert "evidence_bbox_missing" in fragments[0]["qualityFlags"]
    assert any(table["rows"] == 2 and table["columns"] == 2 for table in tables)
    assert blocks[0]["blockType"] == "table"


def test_normalize_docling_payload_marks_markdown_only_as_low_evidence() -> None:
    fragments, tables, blocks = engines.normalize_docling_payload({}, "仅有 Markdown 文本", "docling_local")

    assert tables == []
    assert blocks == []
    assert fragments[0]["confidence"] == 0.62
    assert fragments[0]["bbox"] is None
    assert "docling_markdown_only" in fragments[0]["qualityFlags"]
    assert "evidence_bbox_missing" in fragments[0]["qualityFlags"]


def test_normalize_docling_payload_scores_table_by_evidence() -> None:
    payload = {
        "tables": [
            {
                "label": "table",
                "prov": [{"page_no": 1, "bbox": {"l": 0, "t": 0, "r": 100, "b": 50}}],
                "data": {
                    "table_cells": [
                        {
                            "start_row_offset_idx": 0,
                            "start_col_offset_idx": 0,
                            "text": "管号",
                            "column_header": True,
                            "bbox": {"l": 0, "t": 0, "r": 40, "b": 20},
                        },
                        {
                            "start_row_offset_idx": 1,
                            "start_col_offset_idx": 0,
                            "text": "PL8301",
                            "bbox": {"l": 0, "t": 20, "r": 40, "b": 40},
                        },
                    ]
                },
            }
        ]
    }

    fragments, tables, blocks = engines.normalize_docling_payload(payload, "", "docling_local")

    assert fragments == []
    assert blocks[0]["blockType"] == "table"
    assert tables[0]["structureConfidence"] > 0.8
    assert "docling_structured_table" in tables[0]["qualityFlags"]
    assert "table_evidence_missing" not in tables[0]["qualityFlags"]


def test_ocr_prefetch_verify_only_reports_missing_models(tmp_path) -> None:
    python_bin = tmp_path / "python"
    python_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "official_models" / "PP-OCRv6_medium_det").mkdir(parents=True)

    report = prefetch_report(
        python_bin=python_bin,
        cache_home=tmp_path,
        models=["PP-OCRv6_medium_det", "SLANeXt_wired"],
        verify_only=True,
    )

    assert report["ok"] is False
    assert report["models"][0]["status"] == "present"
    assert report["models"][1]["status"] == "missing"
    assert report["failures"][0]["code"] == "OCR_PREFETCH_MODEL_MISSING"


def test_ocr_prefetch_verify_only_accepts_vl_alias_and_docling_artifacts(tmp_path) -> None:
    python_bin = tmp_path / "python"
    python_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    vl_alias = tmp_path / "official_models" / "PaddleOCR-VL-1.6"
    vl_alias.mkdir(parents=True)
    for filename in ["config.json", "model.safetensors", "processor_config.json"]:
        (vl_alias / filename).write_text("{}", encoding="utf-8")
    docling_dir = tmp_path / "docling"
    docling_dir.mkdir()
    (docling_dir / "model.bin").write_text("local-docling-artifact", encoding="utf-8")

    report = prefetch_report(
        python_bin=python_bin,
        cache_home=tmp_path,
        models=["PaddleOCR-VL-1.6-0.9B"],
        include_docling=True,
        docling_output_dir=docling_dir,
        verify_only=True,
    )

    assert report["ok"] is True
    assert report["models"][0]["status"] == "present"
    assert report["models"][0]["path"].endswith("PaddleOCR-VL-1.6")
    assert report["docling"]["status"] == "present"


def test_ocr_prefetch_uses_hf_snapshot_for_vl(monkeypatch, tmp_path) -> None:
    python_bin = tmp_path / "python"
    python_bin.write_text("#!/bin/sh\n", encoding="utf-8")

    def fake_run(args, **kwargs):
        local_dir = tmp_path / "official_models" / "PaddleOCR-VL-1.6"
        local_dir.mkdir(parents=True)
        for filename in ["config.json", "model.safetensors", "processor_config.json"]:
            (local_dir / filename).write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=str(local_dir), stderr="")

    monkeypatch.setattr(ocr_prefetch_models.subprocess, "run", fake_run)

    report = prefetch_report(
        python_bin=python_bin,
        cache_home=tmp_path,
        models=["PaddleOCR-VL-1.6-0.9B"],
        verify_only=False,
        vl_download_method="hf-snapshot",
    )

    assert report["ok"] is True
    assert report["vlDownloadMethod"] == "hf-snapshot"
    assert report["models"][0]["method"] == "hf-snapshot"
    assert report["models"][0]["path"].endswith("PaddleOCR-VL-1.6")
