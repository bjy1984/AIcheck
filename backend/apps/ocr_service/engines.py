from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any


def env_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default))


class LocalOcrEngine:
    name = "local_ocr_engine"
    version = "unknown"
    required_env: str | None = None
    required_package: str | None = None

    def available(self) -> bool:
        if self.required_package and importlib.util.find_spec(self.required_package) is None:
            return False
        if self.required_env:
            return env_path(self.required_env, "").exists()
        return True

    def status(self) -> dict[str, Any]:
        model_dir = str(env_path(self.required_env, "")) if self.required_env else None
        return {
            "engine": self.name,
            "version": self.version,
            "available": self.available(),
            "modelDir": model_dir,
            "package": self.required_package,
        }

    def parse(self, source_path: Path, *, file_name: str | None = None, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError


class PyMuPdfTextLayerEngine(LocalOcrEngine):
    name = "pymupdf_text_layer"
    version = "fitz"
    required_package = "fitz"

    def parse(self, source_path: Path, *, file_name: str | None = None, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        import fitz  # type: ignore

        fragments: list[dict[str, Any]] = []
        pages: list[dict[str, Any]] = []
        with fitz.open(str(source_path)) as document:
            for page_index, page in enumerate(document):
                page_no = page_index + 1
                text = page.get_text("text").strip()
                rect = page.rect
                pages.append(
                    {
                        "pageNo": page_no,
                        "width": float(rect.width),
                        "height": float(rect.height),
                        "rotation": int(page.rotation or 0),
                    }
                )
                if text:
                    fragments.append(
                        {
                            "pageNo": page_no,
                            "text": text,
                            "bbox": [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)],
                            "confidence": 1.0,
                            "sourceEngine": self.name,
                        }
                    )
        return {
            "ok": bool(fragments),
            "text": "\n".join(item["text"] for item in fragments),
            "pages": pages,
            "fragments": fragments,
            "diagnostics": []
            if fragments
            else [{"code": "PDF_TEXT_LAYER_EMPTY", "level": "info", "message": "PDF text layer is empty."}],
            "engine": self.name,
            "engineVersion": self.version,
        }


class PaddleOcrEngine(LocalOcrEngine):
    name = "paddle_ocr_v6"
    version = "paddleocr@3.7.0"
    required_env = "PADDLEOCR_MODEL_DIR"
    required_package = "paddleocr"

    def parse(self, source_path: Path, *, file_name: str | None = None, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        from paddleocr import PaddleOCR  # type: ignore

        model_dir = str(env_path("PADDLEOCR_MODEL_DIR", "/models/paddleocr"))
        try:
            ocr = PaddleOCR(
                ocr_version="PP-OCRv6",
                text_detection_model_dir=model_dir,
                text_recognition_model_dir=model_dir,
            )
        except TypeError:
            ocr = PaddleOCR(ocr_version="PP-OCRv6")
        raw = ocr.predict(str(source_path))
        fragments: list[dict[str, Any]] = []
        for page_index, page_result in enumerate(raw if isinstance(raw, list) else [raw]):
            fragments.extend(normalize_paddle_fragments(page_result, page_index + 1, self.name))
        return {
            "ok": bool(fragments),
            "text": "\n".join(item["text"] for item in fragments),
            "fragments": fragments,
            "diagnostics": [],
            "engine": self.name,
            "engineVersion": self.version,
        }


class PpStructureEngine(LocalOcrEngine):
    name = "pp_structure_v3"
    version = "pp-structure@3.7.0"
    required_env = "PADDLEOCR_MODEL_DIR"
    required_package = "paddleocr"

    def parse(self, source_path: Path, *, file_name: str | None = None, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        from paddleocr import PPStructureV3  # type: ignore

        engine = PPStructureV3()
        raw = engine.predict(str(source_path))
        tables, layout_blocks = normalize_structure_result(raw, self.name)
        return {
            "ok": bool(tables or layout_blocks),
            "tables": tables,
            "layoutBlocks": layout_blocks,
            "diagnostics": [],
            "engine": self.name,
            "engineVersion": self.version,
        }


class PaddlexSealEngine(LocalOcrEngine):
    name = "paddlex_seal_recognition"
    version = "paddlex-seal@3.7.0"
    required_env = "PADDLEX_MODEL_DIR"
    required_package = "paddlex"

    def parse(self, source_path: Path, *, file_name: str | None = None, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        from paddlex import create_pipeline  # type: ignore

        pipeline = create_pipeline(pipeline="seal_recognition")
        raw = pipeline.predict(str(source_path))
        seals = normalize_seal_result(raw)
        diagnostics = []
        seal_rules = (profile or {}).get("sealRules") or {}
        if seal_rules.get("required") and not seals:
            diagnostics.append({"code": "SEAL_NOT_FOUND", "level": "warning", "message": "未识别到必需印章。"})
        return {
            "ok": bool(seals) or not seal_rules.get("required"),
            "seals": seals,
            "diagnostics": diagnostics,
            "engine": self.name,
            "engineVersion": self.version,
        }


class PaddleOcrVlEngine(LocalOcrEngine):
    name = "paddleocr_vl_1_6"
    version = "paddleocr-vl@1.6"
    required_env = "PADDLEOCR_VL_MODEL_DIR"
    required_package = "paddleocr"

    def parse(self, source_path: Path, *, file_name: str | None = None, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "ok": False,
            "diagnostics": [
                {
                    "code": "ENGINE_ADAPTER_NOT_ENABLED",
                    "level": "info",
                    "message": "PaddleOCR-VL local fallback adapter is registered but not enabled for inline parse.",
                }
            ],
            "engine": self.name,
            "engineVersion": self.version,
        }


class DoclingLocalEngine(LocalOcrEngine):
    name = "docling_local"
    version = "docling-local"
    required_env = "DOCLING_ARTIFACTS_PATH"
    required_package = "docling"

    def parse(self, source_path: Path, *, file_name: str | None = None, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        from docling.document_converter import DocumentConverter  # type: ignore

        converter = DocumentConverter()
        result = converter.convert(str(source_path))
        text = result.document.export_to_markdown()
        return {
            "ok": bool(text.strip()),
            "text": text,
            "fragments": [{"pageNo": 1, "text": text, "bbox": None, "confidence": 0.95, "sourceEngine": self.name}],
            "diagnostics": [],
            "engine": self.name,
            "engineVersion": self.version,
        }


def local_engines() -> list[LocalOcrEngine]:
    return [
        PyMuPdfTextLayerEngine(),
        PaddleOcrEngine(),
        PpStructureEngine(),
        PaddlexSealEngine(),
        PaddleOcrVlEngine(),
        DoclingLocalEngine(),
    ]


def normalize_paddle_fragments(raw: Any, page_no: int, source_engine: str) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        texts = raw.get("rec_texts") or raw.get("texts") or []
        scores = raw.get("rec_scores") or raw.get("scores") or []
        boxes = raw.get("dt_polys") or raw.get("boxes") or []
        for index, text in enumerate(texts):
            if not text:
                continue
            fragments.append(
                {
                    "pageNo": page_no,
                    "text": str(text),
                    "bbox": boxes[index] if index < len(boxes) else None,
                    "confidence": scores[index] if index < len(scores) else 0.8,
                    "sourceEngine": source_engine,
                }
            )
    elif isinstance(raw, list):
        for item in raw:
            fragments.extend(normalize_paddle_fragments(item, page_no, source_engine))
    return fragments


def normalize_structure_result(raw: Any, source_engine: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tables: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    items = raw if isinstance(raw, list) else [raw]
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        block_type = str(item.get("type") or item.get("label") or "layout")
        bbox = item.get("bbox") or item.get("box")
        res = item.get("res")
        res_text = res.get("text") if isinstance(res, dict) else None
        res_html = res.get("html") if isinstance(res, dict) else None
        blocks.append(
            {
                "blockId": f"layout_{index + 1}",
                "blockType": block_type,
                "pageNo": int(item.get("pageNo") or item.get("page_no") or 1),
                "bbox": bbox,
                "text": item.get("text") or res_text,
                "confidence": item.get("confidence") or item.get("score") or 0.8,
                "sourceEngine": source_engine,
            }
        )
        if "table" in block_type.lower():
            tables.append(
                {
                    "tableId": f"table_{len(tables) + 1}",
                    "pageNo": int(item.get("pageNo") or item.get("page_no") or 1),
                    "bbox": bbox,
                    "rows": 0,
                    "columns": 0,
                    "cells": [],
                    "html": item.get("html") or res_html,
                    "markdown": item.get("markdown"),
                    "normalizedRows": [],
                    "structureConfidence": item.get("confidence") or item.get("score") or 0.8,
                    "sourceEngine": source_engine,
                }
            )
    return tables, blocks


def normalize_seal_result(raw: Any) -> list[dict[str, Any]]:
    seals: list[dict[str, Any]] = []
    items = raw if isinstance(raw, list) else [raw]
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        text = item.get("text") or item.get("sealName") or item.get("rec_text") or ""
        seals.append(
            {
                "sealId": f"seal_{index + 1}",
                "pageNo": int(item.get("pageNo") or item.get("page_no") or 1),
                "sealType": item.get("sealType") or "unknown",
                "sealName": str(text),
                "bbox": item.get("bbox") or item.get("box"),
                "polygon": item.get("polygon") or item.get("dt_poly"),
                "visualConfidence": item.get("visualConfidence") or item.get("det_score") or item.get("score") or 0.8,
                "ocrConfidence": item.get("ocrConfidence") or item.get("rec_score") or item.get("score") or 0.8,
                "fields": item.get("fields") or [],
                "qualityFlags": item.get("qualityFlags") or [],
            }
        )
    return seals
