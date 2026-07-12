from __future__ import annotations

import importlib.util
import json
import os
import select
import signal
import shutil
import subprocess
import textwrap
import threading
import time
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from uuid import uuid4

from apps.ocr_service.utils import parse_bool


def env_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default))


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def inprocess_paddle_enabled() -> bool:
    if env_bool("AICHECK_OCR_ENABLE_INPROCESS_PADDLE", False):
        return True
    return not bool(os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON"))


def subprocess_resource_limit_preamble(env_name: str, default_mb: int) -> str:
    return textwrap.dedent(
        f"""
        import os
        try:
            import resource
            _limit_mb = int(os.getenv("{env_name}", os.getenv("AICHECK_OCR_SUBPROCESS_MEMORY_LIMIT_MB", "{default_mb}")) or 0)
            if _limit_mb > 0:
                _limit_bytes = _limit_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (_limit_bytes, _limit_bytes))
        except Exception:
            pass
        """
    )


def run_ocr_subprocess(
    args: list[str],
    *,
    env: dict[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    """Run OCR subprocesses in their own process group so timeouts clean child workers."""
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        terminate_process_group(process)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        exc.stdout = stdout
        exc.stderr = stderr
        raise exc
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        process.terminate()
    try:
        process.wait(timeout=3)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except Exception:
        process.kill()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass


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

    def parse(
        self,
        source_path: Path,
        *,
        file_name: str | None = None,
        profile: dict[str, Any] | None = None,
        variant: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


class PyMuPdfTextLayerEngine(LocalOcrEngine):
    name = "pymupdf_text_layer"
    version = "fitz"
    required_package = "fitz"

    def parse(
        self,
        source_path: Path,
        *,
        file_name: str | None = None,
        profile: dict[str, Any] | None = None,
        variant: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import fitz  # type: ignore

        if isinstance(variant, dict) and variant.get("documentPath"):
            source_path = Path(str(variant["documentPath"]))
        else:
            source_path = variant_source_path(source_path, variant)
        fragments: list[dict[str, Any]] = []
        pages: list[dict[str, Any]] = []
        with fitz.open(str(source_path)) as document:
            for page_index, page in enumerate(document):
                page_no = page_index + 1
                rect = page.rect
                pages.append(
                    {
                        "pageNo": page_no,
                        "width": float(rect.width),
                        "height": float(rect.height),
                        "rotation": int(page.rotation or 0),
                    }
                )
                words = page.get_text("words") or []
                line_texts: list[str] = []
                for word_index, word in enumerate(words):
                    if not isinstance(word, (list, tuple)) or len(word) < 5:
                        continue
                    text = str(word[4]).strip()
                    if not text:
                        continue
                    fragments.append(
                        {
                            "pageNo": page_no,
                            "text": text,
                            "bbox": [float(word[0]), float(word[1]), float(word[2]), float(word[3])],
                            "confidence": 1.0,
                            "sourceEngine": self.name,
                            "fragmentType": "word",
                            "wordIndex": word_index,
                        }
                    )
                    line_texts.append(text)
                page_text = page.get_text("text").strip()
                if page_text and not words:
                    fragments.append(
                        {
                            "pageNo": page_no,
                            "text": page_text,
                            "bbox": [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)],
                            "confidence": 1.0,
                            "sourceEngine": self.name,
                            "fragmentType": "page",
                        }
                    )
        return {
            "ok": bool(fragments),
            "text": "\n".join(item["text"] for item in fragments),
            "pages": pages,
            "fragments": fragments,
            "metadata": {
                "documentLevel": True,
                "engineScope": "document",
                "sourceCoordinateSystem": "pdf_points",
            },
            "diagnostics": []
            if fragments
            else [{"code": "PDF_TEXT_LAYER_EMPTY", "level": "info", "message": "PDF text layer is empty."}],
            "engine": self.name,
            "engineVersion": self.version,
        }


class PaddleOcrEngine(LocalOcrEngine):
    name = "paddle_ocr_v6"
    version = "paddleocr@3.7.0"
    required_package = "paddleocr"

    def available(self) -> bool:
        return inprocess_paddle_enabled() and super().available() and paddle_text_model_dirs_available()

    def status(self) -> dict[str, Any]:
        det_dir = model_dir("AICHECK_PADDLEOCR_DET_MODEL_DIR", "PP-OCRv6_medium_det")
        rec_dir = model_dir("AICHECK_PADDLEOCR_REC_MODEL_DIR", "PP-OCRv6_medium_rec")
        return {
            "engine": self.name,
            "version": self.version,
            "available": self.available(),
            "disabledReason": None if inprocess_paddle_enabled() else "subprocess_ocr_python_configured",
            "detModelDir": str(det_dir),
            "recModelDir": str(rec_dir),
            "package": self.required_package,
        }

    def parse(
        self,
        source_path: Path,
        *,
        file_name: str | None = None,
        profile: dict[str, Any] | None = None,
        variant: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from paddleocr import PaddleOCR  # type: ignore

        source_path = variant_source_path(source_path, variant)
        det_dir = str(model_dir("AICHECK_PADDLEOCR_DET_MODEL_DIR", "PP-OCRv6_medium_det"))
        rec_dir = str(model_dir("AICHECK_PADDLEOCR_REC_MODEL_DIR", "PP-OCRv6_medium_rec"))
        runtime = paddle_runtime_options(profile)
        if isinstance(variant, dict) and isinstance(variant.get("ocrRuntimeOverrides"), dict):
            runtime.update(variant["ocrRuntimeOverrides"])
        ocr = PaddleOCR(
            text_detection_model_dir=det_dir,
            text_recognition_model_dir=rec_dir,
            use_doc_orientation_classify=runtime["use_doc_orientation_classify"],
            use_doc_unwarping=runtime["use_doc_unwarping"],
            use_textline_orientation=runtime["use_textline_orientation"],
            text_det_limit_side_len=runtime["text_det_limit_side_len"],
            text_det_limit_type="max",
            enable_mkldnn=False,
        )
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
    required_package = "paddleocr"

    def available(self) -> bool:
        return self.package_available() and all(path.exists() for path in pp_structure_model_dirs().values())

    def package_available(self) -> bool:
        inprocess_ready = importlib.util.find_spec(self.required_package) is not None
        subprocess_ready = subprocess_package_available("paddleocr")
        return inprocess_ready or subprocess_ready

    def execution_mode(self) -> str:
        if subprocess_package_available("paddleocr"):
            return "subprocess"
        if importlib.util.find_spec(self.required_package) is not None:
            return "inprocess"
        return "unavailable"

    def status(self) -> dict[str, Any]:
        dirs = pp_structure_model_dirs()
        return {
            "engine": self.name,
            "version": self.version,
            "available": self.available(),
            "executionMode": self.execution_mode(),
            "python": os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON"),
            "subprocessPackageAvailable": subprocess_package_available("paddleocr"),
            "modelDirs": {key: str(path) for key, path in dirs.items()},
            "missingModelDirs": [key for key, path in dirs.items() if not path.exists()],
            "package": self.required_package,
        }

    def parse(
        self,
        source_path: Path,
        *,
        file_name: str | None = None,
        profile: dict[str, Any] | None = None,
        variant: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_path = variant_source_path(source_path, variant)
        dirs = pp_structure_model_dirs()
        names = pp_structure_model_names(dirs)
        missing = [key for key, path in dirs.items() if not path.exists()]
        if missing:
            return {
                "ok": False,
                "diagnostics": [
                    {
                        "code": "PP_STRUCTURE_MODEL_MISSING",
                        "level": "warning",
                        "message": f"PP-Structure local model directories are missing: {', '.join(missing)}.",
                    }
                ],
                "engine": self.name,
                "engineVersion": self.version,
            }
        if self.execution_mode() == "subprocess":
            return self.parse_with_subprocess(source_path, profile=profile)
        from paddleocr import PPStructureV3  # type: ignore

        runtime = paddle_runtime_options(profile)
        engine = PPStructureV3(
            layout_detection_model_name=names["layout"],
            layout_detection_model_dir=str(dirs["layout"]),
            text_detection_model_name=names["text_det"],
            text_detection_model_dir=str(dirs["text_det"]),
            text_recognition_model_name=names["text_rec"],
            text_recognition_model_dir=str(dirs["text_rec"]),
            wired_table_structure_recognition_model_name=names["wired_table_structure"],
            wired_table_structure_recognition_model_dir=str(dirs["wired_table_structure"]),
            wired_table_cells_detection_model_name=names["wired_table_cells"],
            wired_table_cells_detection_model_dir=str(dirs["wired_table_cells"]),
            wireless_table_structure_recognition_model_name=names["wireless_table_structure"],
            wireless_table_structure_recognition_model_dir=str(dirs["wireless_table_structure"]),
            wireless_table_cells_detection_model_name=names["wireless_table_cells"],
            wireless_table_cells_detection_model_dir=str(dirs["wireless_table_cells"]),
            use_doc_orientation_classify=runtime["use_doc_orientation_classify"],
            use_doc_unwarping=runtime["use_doc_unwarping"],
            use_textline_orientation=runtime["use_textline_orientation"],
            use_table_recognition=True,
            use_seal_recognition=False,
            use_formula_recognition=False,
            use_chart_recognition=False,
            use_region_detection=False,
            **paddle_predictor_options(),
        )
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

    def parse_with_subprocess(self, source_path: Path, *, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
        if not python_bin or not Path(python_bin).exists():
            return {
                "ok": False,
                "diagnostics": [{"code": "PP_STRUCTURE_SUBPROCESS_NOT_CONFIGURED", "level": "info", "message": "AICHECK_OCR_SUBPROCESS_PYTHON is not configured."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        dirs = pp_structure_model_dirs()
        names = pp_structure_model_names(dirs)
        script = subprocess_resource_limit_preamble("AICHECK_PP_STRUCTURE_MEMORY_LIMIT_MB", 1536) + textwrap.dedent(
            """
            import json
            import sys
            from paddleocr import PPStructureV3

            image_path = sys.argv[1]
            dirs = json.loads(sys.argv[2])
            runtime = json.loads(sys.argv[3])
            names = json.loads(sys.argv[4])
            predictor = json.loads(sys.argv[5])

            def basic(value):
                if isinstance(value, (str, int, float, bool)) or value is None:
                    return value
                if isinstance(value, dict):
                    return {str(k): basic(v) for k, v in value.items() if str(k) not in {"input_img", "img", "dt_polys"}}
                if isinstance(value, (list, tuple)):
                    return [basic(v) for v in value]
                if hasattr(value, "tolist"):
                    try:
                        return value.tolist()
                    except Exception:
                        return str(value)
                json_payload = getattr(value, "json", None)
                if isinstance(json_payload, dict):
                    return basic(json_payload)
                if callable(json_payload):
                    try:
                        return basic(json_payload())
                    except Exception:
                        pass
                if hasattr(value, "items"):
                    try:
                        return {str(k): basic(v) for k, v in value.items() if str(k) not in {"input_img", "img", "dt_polys"}}
                    except Exception:
                        return str(value)
                return str(value)

            engine = PPStructureV3(
                layout_detection_model_name=names["layout"],
                layout_detection_model_dir=dirs["layout"],
                text_detection_model_name=names["text_det"],
                text_detection_model_dir=dirs["text_det"],
                text_recognition_model_name=names["text_rec"],
                text_recognition_model_dir=dirs["text_rec"],
                wired_table_structure_recognition_model_name=names["wired_table_structure"],
                wired_table_structure_recognition_model_dir=dirs["wired_table_structure"],
                wired_table_cells_detection_model_name=names["wired_table_cells"],
                wired_table_cells_detection_model_dir=dirs["wired_table_cells"],
                wireless_table_structure_recognition_model_name=names["wireless_table_structure"],
                wireless_table_structure_recognition_model_dir=dirs["wireless_table_structure"],
                wireless_table_cells_detection_model_name=names["wireless_table_cells"],
                wireless_table_cells_detection_model_dir=dirs["wireless_table_cells"],
                use_doc_orientation_classify=bool(runtime.get("use_doc_orientation_classify")),
                use_doc_unwarping=bool(runtime.get("use_doc_unwarping")),
                use_textline_orientation=bool(runtime.get("use_textline_orientation")),
                use_table_recognition=True,
                use_seal_recognition=False,
                use_formula_recognition=False,
                use_chart_recognition=False,
                use_region_detection=False,
                **predictor,
            )
            raw = [basic(item) for item in engine.predict(image_path)]
            print("AICHECK_PP_STRUCTURE_RESULT " + json.dumps(raw, ensure_ascii=False), flush=True)
            """
        )
        try:
            completed = run_ocr_subprocess(
                [
                    python_bin,
                    "-c",
                    script,
                    str(source_path),
                    json.dumps({key: str(path) for key, path in dirs.items()}),
                    json.dumps(paddle_runtime_options(profile)),
                    json.dumps(names),
                    json.dumps(paddle_predictor_options()),
                ],
                env=ocr_subprocess_env(),
                timeout=float(os.getenv("AICHECK_PP_STRUCTURE_TIMEOUT", "180")),
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "diagnostics": [{"code": "PP_STRUCTURE_TIMEOUT", "level": "warning", "message": "PP-Structure subprocess timed out."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        if completed.returncode != 0:
            return {
                "ok": False,
                "diagnostics": [{"code": "PP_STRUCTURE_FAILED", "level": "warning", "message": (completed.stderr or completed.stdout or "PP-Structure subprocess failed")[-1200:]}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        payload_line = next(
            (line for line in reversed(completed.stdout.splitlines()) if line.startswith("AICHECK_PP_STRUCTURE_RESULT ")),
            "",
        )
        if not payload_line:
            return {
                "ok": False,
                "diagnostics": [{"code": "PP_STRUCTURE_EMPTY", "level": "warning", "message": "PP-Structure subprocess returned no parseable payload."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        raw = json.loads(payload_line.replace("AICHECK_PP_STRUCTURE_RESULT ", "", 1))
        tables, layout_blocks = normalize_structure_result(raw, self.name)
        return {
            "ok": bool(tables or layout_blocks),
            "tables": tables,
            "layoutBlocks": layout_blocks,
            "diagnostics": [],
            "engine": self.name,
            "engineVersion": self.version,
            "workerMode": "subprocess",
        }


class OpenCvTableGridSubprocessEngine(LocalOcrEngine):
    name = "opencv_table_grid_subprocess"
    version = "opencv-grid@2"

    def available(self) -> bool:
        if not env_bool("AICHECK_ENABLE_OPENCV_TABLE_GRID", True):
            return False
        python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
        return bool(python_bin and Path(python_bin).exists())

    def status(self) -> dict[str, Any]:
        return {
            "engine": self.name,
            "version": self.version,
            "available": self.available(),
            "enabled": os.getenv("AICHECK_ENABLE_OPENCV_TABLE_GRID", "true"),
            "python": os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON"),
        }

    def parse(
        self,
        source_path: Path,
        *,
        file_name: str | None = None,
        profile: dict[str, Any] | None = None,
        variant: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
        if not python_bin:
            return {
                "ok": False,
                "diagnostics": [
                    {
                        "code": "OPENCV_TABLE_GRID_NOT_CONFIGURED",
                        "level": "info",
                        "message": "AICHECK_OCR_SUBPROCESS_PYTHON is not configured.",
                    }
                ],
                "engine": self.name,
                "engineVersion": self.version,
            }
        source_path = variant_source_path(source_path, variant)
        script = subprocess_resource_limit_preamble("AICHECK_OPENCV_TABLE_GRID_MEMORY_LIMIT_MB", 768) + textwrap.dedent(
            """
            import json
            import sys
            import cv2
            import numpy as np

            image_path = sys.argv[1]
            image = cv2.imread(image_path)
            if image is None:
                print(json.dumps({"ok": False, "diagnostics": [{"code": "IMAGE_READ_FAILED", "level": "error", "message": "image read failed"}]}, ensure_ascii=False))
                raise SystemExit(0)
            height, width = image.shape[:2]
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 9)
            edges = cv2.Canny(gray, 40, 120)
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            blue = cv2.inRange(hsv, np.array((80, 25, 20), np.uint8), np.array((135, 255, 255), np.uint8))

            def grouped_positions(mask, axis, min_ratio, min_gap=10):
                projection = np.sum(mask > 0, axis=axis)
                span = width if axis == 1 else height
                threshold = max(20, span * min_ratio)
                runs = []
                start = None
                for idx, value in enumerate(projection):
                    if value >= threshold and start is None:
                        start = idx
                    elif value < threshold and start is not None:
                        if idx - start >= 1:
                            runs.append((start, idx - 1))
                        start = None
                if start is not None:
                    runs.append((start, len(projection) - 1))
                positions = [int(round((left + right) / 2)) for left, right in runs]
                filtered = []
                for pos in positions:
                    if not filtered or pos - filtered[-1] >= min_gap:
                        filtered.append(pos)
                    else:
                        filtered[-1] = int(round((filtered[-1] + pos) / 2))
                return filtered

            def detect_grid(base_mask, source, kernel_divisor, y_ratio, x_ratio):
                horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(18, width // kernel_divisor), 1))
                vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(18, height // kernel_divisor)))
                horizontal = cv2.morphologyEx(base_mask, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)
                vertical = cv2.morphologyEx(base_mask, cv2.MORPH_OPEN, vertical_kernel, iterations=1)
                horizontal = cv2.morphologyEx(horizontal, cv2.MORPH_CLOSE, np.ones((2, 9), np.uint8), iterations=1)
                vertical = cv2.morphologyEx(vertical, cv2.MORPH_CLOSE, np.ones((9, 2), np.uint8), iterations=1)
                ys = grouped_positions(horizontal, axis=1, min_ratio=y_ratio)
                xs = grouped_positions(vertical, axis=0, min_ratio=x_ratio)
                rows = max(len(ys) - 1, 0)
                columns = max(len(xs) - 1, 0)
                if rows < 3 or columns < 3:
                    return None
                x_span = max(xs) - min(xs)
                y_span = max(ys) - min(ys)
                area_ratio = (x_span * y_span) / max(width * height, 1)
                # Prefer broad, regular grids, but avoid rewarding one-pixel noise explosions.
                score = min(rows, 80) * min(columns, 80) + area_ratio * 120
                return {
                    "xs": xs,
                    "ys": ys,
                    "rows": rows,
                    "columns": columns,
                    "score": float(score),
                    "lineSource": source,
                    "kernelDivisor": kernel_divisor,
                    "thresholds": {"yRatio": y_ratio, "xRatio": x_ratio},
                }

            attempts = [
                (adaptive, "adaptive_strict", 90, 0.18, 0.08),
                (adaptive, "adaptive_balanced", 180, 0.04, 0.06),
                (adaptive, "adaptive_sensitive", 240, 0.035, 0.05),
                (edges, "canny_balanced", 180, 0.02, 0.04),
                (edges, "canny_sensitive", 240, 0.02, 0.035),
                (blue, "blue_grid", 90, 0.08, 0.08),
            ]
            candidates = [detect_grid(*attempt) for attempt in attempts]
            candidates = [candidate for candidate in candidates if candidate]
            diagnostics = []
            if not candidates:
                diagnostics.append({"code": "OPENCV_TABLE_GRID_NOT_FOUND", "level": "info", "message": "not enough grid lines detected"})
                print(json.dumps({"ok": False, "tables": [], "diagnostics": diagnostics}, ensure_ascii=False))
                raise SystemExit(0)
            selected = sorted(candidates, key=lambda item: item["score"], reverse=True)[0]
            ys = selected["ys"]
            xs = selected["xs"]

            max_cells = int(sys.argv[2])
            cells = []
            for row in range(len(ys) - 1):
                y0, y1 = int(ys[row]), int(ys[row + 1])
                if y1 - y0 < 8:
                    continue
                for col in range(len(xs) - 1):
                    x0, x1 = int(xs[col]), int(xs[col + 1])
                    if x1 - x0 < 8:
                        continue
                    if len(cells) < max_cells:
                        cells.append({
                            "cellId": f"grid_cell_{row + 1}_{col + 1}",
                            "row": row,
                            "col": col,
                            "rowspan": 1,
                            "colspan": 1,
                            "text": "",
                            "bbox": [x0, y0, x1, y1],
                            "confidence": 0.82,
                            "isHeader": row <= 1,
                        })
            rows = max(len(ys) - 1, 0)
            columns = max(len(xs) - 1, 0)
            cell_count = rows * columns
            confidence = min(0.95, 0.72 + min(cell_count, 900) / 5000.0)
            table = {
                "tableId": "opencv_grid_table_1",
                "pageNo": 1,
                "bbox": [min(xs), min(ys), max(xs), max(ys)],
                "rows": rows,
                "columns": columns,
                "structureConfidence": round(confidence, 4),
                "cells": cells,
                "gridLineXs": xs,
                "gridLineYs": ys,
                "gridCellCount": cell_count,
                "gridDetection": {
                    "lineSource": selected["lineSource"],
                    "kernelDivisor": selected["kernelDivisor"],
                    "thresholds": selected["thresholds"],
                    "candidateCount": len(candidates),
                    "score": round(selected["score"], 4),
                },
                "sourceEngine": "opencv_table_grid_subprocess",
                "qualityFlags": ["opencv_grid_structure"],
            }
            print(json.dumps({"ok": True, "tables": [table], "diagnostics": diagnostics}, ensure_ascii=False))
            """
        )
        try:
            completed = run_ocr_subprocess(
                [python_bin, "-c", script, str(source_path), os.getenv("AICHECK_OPENCV_TABLE_GRID_MAX_CELLS", "1800")],
                env=ocr_subprocess_env(),
                timeout=float(os.getenv("AICHECK_OPENCV_TABLE_GRID_TIMEOUT", "35")),
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "diagnostics": [
                    {
                        "code": "OPENCV_TABLE_GRID_TIMEOUT",
                        "level": "warning",
                        "message": "OpenCV table grid detection timed out.",
                    }
                ],
                "engine": self.name,
                "engineVersion": self.version,
            }
        if completed.returncode != 0:
            return {
                "ok": False,
                "diagnostics": [
                    {
                        "code": "OPENCV_TABLE_GRID_FAILED",
                        "level": "warning",
                        "message": (completed.stderr or completed.stdout or "OpenCV table grid failed")[-1000:],
                    }
                ],
                "engine": self.name,
                "engineVersion": self.version,
            }
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        payload = json.loads(lines[-1]) if lines else {}
        return {**payload, "engine": self.name, "engineVersion": self.version}


class PaddleOcrSubprocessEngine(LocalOcrEngine):
    name = "paddle_ocr_subprocess"
    version = "paddleocr@3.7.0-subprocess"

    def __init__(self) -> None:
        self._worker: subprocess.Popen[str] | None = None
        self._worker_key: str | None = None
        self._worker_lock = threading.Lock()

    def available(self) -> bool:
        python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
        if not python_bin or not Path(python_bin).exists():
            return False
        det_dir = subprocess_model_dir("AICHECK_PADDLEOCR_DET_MODEL_DIR", "PP-OCRv6_medium_det")
        rec_dir = subprocess_model_dir("AICHECK_PADDLEOCR_REC_MODEL_DIR", "PP-OCRv6_medium_rec")
        return det_dir.exists() and rec_dir.exists()

    def status(self) -> dict[str, Any]:
        python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
        det_dir = subprocess_model_dir("AICHECK_PADDLEOCR_DET_MODEL_DIR", "PP-OCRv6_medium_det")
        rec_dir = subprocess_model_dir("AICHECK_PADDLEOCR_REC_MODEL_DIR", "PP-OCRv6_medium_rec")
        return {
            "engine": self.name,
            "version": self.version,
            "available": self.available(),
            "python": python_bin,
            "detModelDir": str(det_dir),
            "recModelDir": str(rec_dir),
            "persistentEnabled": env_bool("AICHECK_OCR_ENABLE_PERSISTENT_SUBPROCESS", False),
            "warmedUp": self._worker is not None and self._worker.poll() is None,
        }

    def parse(
        self,
        source_path: Path,
        *,
        file_name: str | None = None,
        profile: dict[str, Any] | None = None,
        variant: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
        if not python_bin:
            return {
                "ok": False,
                "diagnostics": [{"code": "SUBPROCESS_OCR_NOT_CONFIGURED", "level": "info", "message": "AICHECK_OCR_SUBPROCESS_PYTHON is not configured."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        source_path = variant_source_path(source_path, variant)
        det_dir = subprocess_model_dir("AICHECK_PADDLEOCR_DET_MODEL_DIR", "PP-OCRv6_medium_det")
        rec_dir = subprocess_model_dir("AICHECK_PADDLEOCR_REC_MODEL_DIR", "PP-OCRv6_medium_rec")
        runtime = paddle_runtime_options(profile)
        if isinstance(variant, dict) and isinstance(variant.get("ocrRuntimeOverrides"), dict):
            runtime.update(variant["ocrRuntimeOverrides"])
        persistent_safe = not (
            runtime.get("use_doc_orientation_classify")
            or runtime.get("use_doc_unwarping")
            or runtime.get("use_textline_orientation")
        )
        if env_bool("AICHECK_OCR_ENABLE_PERSISTENT_SUBPROCESS", False) and persistent_safe:
            try:
                return self.parse_with_persistent_worker(Path(python_bin), source_path, det_dir, rec_dir, runtime)
            except Exception as exc:
                self.reset_worker()
                if not env_bool("AICHECK_OCR_FALLBACK_TO_ONESHOT", False):
                    return {
                        "ok": False,
                        "diagnostics": [
                            {
                                "code": "PERSISTENT_SUBPROCESS_OCR_FAILED",
                                "level": "warning",
                                "message": f"PaddleOCR persistent worker failed: {exc.__class__.__name__}",
                            }
                        ],
                        "engine": self.name,
                        "engineVersion": self.version,
                    }
                # Optional compatibility fallback for environments that prefer slow one-shot OCR over fast failure.
        script = subprocess_resource_limit_preamble("AICHECK_PADDLEOCR_MEMORY_LIMIT_MB", 1536) + textwrap.dedent(
            """
            import json
            import sys
            from paddleocr import PaddleOCR

            image_path, det_dir, rec_dir, runtime_json = sys.argv[1:5]
            runtime = json.loads(runtime_json)
            ocr = PaddleOCR(
                text_detection_model_dir=det_dir,
                text_recognition_model_dir=rec_dir,
                use_doc_orientation_classify=bool(runtime.get("use_doc_orientation_classify")),
                use_doc_unwarping=bool(runtime.get("use_doc_unwarping")),
                use_textline_orientation=bool(runtime.get("use_textline_orientation")),
                text_det_limit_side_len=int(runtime.get("text_det_limit_side_len") or 2400),
                text_det_limit_type="max",
                enable_mkldnn=False,
            )
            raw = ocr.predict(image_path)
            fragments = []
            pages = raw if isinstance(raw, list) else [raw]
            for page_index, page in enumerate(pages):
                if not isinstance(page, dict):
                    if hasattr(page, "json") and callable(page.json):
                        page = page.json()
                    elif hasattr(page, "dict") and callable(page.dict):
                        page = page.dict()
                if not isinstance(page, dict):
                    continue
                texts = page.get("rec_texts") or page.get("texts") or []
                scores = page.get("rec_scores") or page.get("scores") or []
                boxes = page.get("dt_polys") or page.get("boxes") or []
                for index, text in enumerate(texts):
                    if not text:
                        continue
                    box = boxes[index] if index < len(boxes) else None
                    if hasattr(box, "tolist"):
                        box = box.tolist()
                    fragments.append(
                        {
                            "pageNo": page_index + 1,
                            "text": str(text),
                            "bbox": box,
                            "confidence": float(scores[index]) if index < len(scores) and scores[index] is not None else 0.0,
                            "sourceEngine": "paddle_ocr_subprocess",
                        }
                    )
            print(json.dumps({"ok": bool(fragments), "fragments": fragments, "text": "\\n".join(item["text"] for item in fragments)}, ensure_ascii=False))
            """
        )
        env = ocr_subprocess_env()
        timeout = float(os.getenv("AICHECK_OCR_SUBPROCESS_TIMEOUT", "180"))
        try:
            completed = run_ocr_subprocess(
                [python_bin, "-c", script, str(source_path), str(det_dir), str(rec_dir), json.dumps(runtime)],
                env=env,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "diagnostics": [
                    {
                        "code": "SUBPROCESS_OCR_TIMEOUT",
                        "level": "warning",
                        "message": "PaddleOCR subprocess timed out.",
                    }
                ],
                "engine": self.name,
                "engineVersion": self.version,
            }
        if completed.returncode != 0:
            return {
                "ok": False,
                "diagnostics": [
                    {
                        "code": "SUBPROCESS_OCR_FAILED",
                        "level": "error",
                        "message": (completed.stderr or completed.stdout or "PaddleOCR subprocess failed.")[-1000:],
                    }
                ],
                "engine": self.name,
                "engineVersion": self.version,
            }
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        payload = json.loads(lines[-1]) if lines else {}
        return {
            **payload,
            "diagnostics": [],
            "engine": self.name,
            "engineVersion": self.version,
            "workerMode": "oneshot",
        }

    def parse_with_persistent_worker(
        self,
        python_bin: Path,
        source_path: Path,
        det_dir: Path,
        rec_dir: Path,
        runtime: dict[str, Any],
    ) -> dict[str, Any]:
        with self._worker_lock:
            worker = self.ensure_worker(python_bin, det_dir, rec_dir, runtime)
            if worker.stdin is None:
                raise RuntimeError("PaddleOCR worker stdin is unavailable.")
            request_id = uuid4().hex
            worker.stdin.write(json.dumps({"requestId": request_id, "imagePath": str(source_path)}, ensure_ascii=False) + "\n")
            worker.stdin.flush()
            payload = self.read_worker_response(worker, request_id)
            return {
                **payload,
                "diagnostics": payload.get("diagnostics") or [],
                "engine": self.name,
                "engineVersion": self.version,
                "workerMode": "persistent",
            }

    def ensure_worker(
        self,
        python_bin: Path,
        det_dir: Path,
        rec_dir: Path,
        runtime: dict[str, Any],
    ) -> subprocess.Popen[str]:
        worker_key = json.dumps(
            {
                "detDir": str(det_dir),
                "recDir": str(rec_dir),
                "runtime": runtime,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        if self._worker is not None and self._worker.poll() is None and self._worker_key == worker_key:
            return self._worker
        self.reset_worker()
        self._worker_key = worker_key
        self._worker = subprocess.Popen(
            [str(python_bin), "-u", "-c", paddle_ocr_worker_script(), str(det_dir), str(rec_dir), json.dumps(runtime)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            env=ocr_subprocess_env(),
            bufsize=1,
            start_new_session=True,
        )
        return self._worker

    def read_worker_response(self, worker: subprocess.Popen[str], request_id: str) -> dict[str, Any]:
        if worker.stdout is None:
            raise RuntimeError("PaddleOCR worker stdout is unavailable.")
        timeout = float(os.getenv("AICHECK_OCR_PERSISTENT_WORKER_TIMEOUT", os.getenv("AICHECK_OCR_SUBPROCESS_TIMEOUT", "180")))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if worker.poll() is not None:
                raise RuntimeError("PaddleOCR persistent worker exited.")
            readable, _, _ = select.select([worker.stdout], [], [], max(deadline - time.monotonic(), 0.1))
            if not readable:
                continue
            line = worker.stdout.readline()
            if not line:
                continue
            if not line.startswith("AICHECK_OCR_RESULT "):
                continue
            payload = json.loads(line.removeprefix("AICHECK_OCR_RESULT ").strip())
            if payload.get("requestId") not in {None, request_id}:
                continue
            payload.pop("requestId", None)
            return payload
        raise TimeoutError("PaddleOCR persistent worker timed out.")

    def reset_worker(self) -> None:
        worker = self._worker
        self._worker = None
        self._worker_key = None
        if worker is None:
            return
        if worker.poll() is None:
            terminate_process_group(worker)
            try:
                worker.wait(timeout=3)
            except subprocess.TimeoutExpired:
                worker.kill()


def paddle_ocr_worker_script() -> str:
    return subprocess_resource_limit_preamble("AICHECK_PADDLEOCR_MEMORY_LIMIT_MB", 4096) + textwrap.dedent(
        """
        import json
        import sys
        from paddleocr import PaddleOCR

        det_dir, rec_dir = sys.argv[1:3]
        runtime = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        ocr = PaddleOCR(
            text_detection_model_dir=det_dir,
            text_recognition_model_dir=rec_dir,
            use_doc_orientation_classify=bool(runtime.get("use_doc_orientation_classify")),
            use_doc_unwarping=bool(runtime.get("use_doc_unwarping")),
            use_textline_orientation=bool(runtime.get("use_textline_orientation")),
            text_det_limit_side_len=int(runtime.get("text_det_limit_side_len") or 2400),
            text_det_limit_type="max",
            enable_mkldnn=False,
        )

        def parse_one(image_path):
            raw = ocr.predict(image_path)
            fragments = []
            pages = raw if isinstance(raw, list) else [raw]
            for page_index, page in enumerate(pages):
                if not isinstance(page, dict):
                    if hasattr(page, "json") and callable(page.json):
                        page = page.json()
                    elif hasattr(page, "dict") and callable(page.dict):
                        page = page.dict()
                if not isinstance(page, dict):
                    continue
                texts = page.get("rec_texts") or page.get("texts") or []
                scores = page.get("rec_scores") or page.get("scores") or []
                boxes = page.get("dt_polys") or page.get("boxes") or []
                for index, text in enumerate(texts):
                    if not text:
                        continue
                    box = boxes[index] if index < len(boxes) else None
                    if hasattr(box, "tolist"):
                        box = box.tolist()
                    fragments.append(
                        {
                            "pageNo": page_index + 1,
                            "text": str(text),
                            "bbox": box,
                            "confidence": float(scores[index]) if index < len(scores) and scores[index] is not None else 0.0,
                            "sourceEngine": "paddle_ocr_subprocess",
                        }
                    )
            return {"ok": bool(fragments), "fragments": fragments, "text": "\\n".join(item["text"] for item in fragments)}

        for line in sys.stdin:
            try:
                request = json.loads(line)
                payload = parse_one(str(request.get("imagePath") or ""))
                payload["requestId"] = request.get("requestId")
            except Exception as exc:
                payload = {
                    "ok": False,
                    "requestId": request.get("requestId") if isinstance(locals().get("request"), dict) else None,
                    "diagnostics": [
                        {
                            "code": "PERSISTENT_SUBPROCESS_OCR_FAILED",
                            "level": "error",
                            "message": f"{exc.__class__.__name__}: {exc}",
                        }
                    ],
                }
            print("AICHECK_OCR_RESULT " + json.dumps(payload, ensure_ascii=False), flush=True)
        """
    )


class TesseractCliEngine(LocalOcrEngine):
    name = "tesseract_cli"
    version = "tesseract-cli"

    def available(self) -> bool:
        return shutil.which(os.getenv("AICHECK_TESSERACT_BIN", "tesseract")) is not None

    def status(self) -> dict[str, Any]:
        return {
            "engine": self.name,
            "version": self.version,
            "available": self.available(),
            "binary": shutil.which(os.getenv("AICHECK_TESSERACT_BIN", "tesseract")),
            "languages": os.getenv("AICHECK_TESSERACT_LANG", "chi_sim+eng"),
        }

    def parse(
        self,
        source_path: Path,
        *,
        file_name: str | None = None,
        profile: dict[str, Any] | None = None,
        variant: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        binary = shutil.which(os.getenv("AICHECK_TESSERACT_BIN", "tesseract"))
        if not binary:
            return {
                "ok": False,
                "diagnostics": [{"code": "TESSERACT_NOT_CONFIGURED", "level": "info", "message": "tesseract binary is not available."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        source_path = variant_source_path(source_path, variant)
        try:
            completed = run_ocr_subprocess(
                [
                    binary,
                    str(source_path),
                    "stdout",
                    "-l",
                    os.getenv("AICHECK_TESSERACT_LANG", "chi_sim+eng"),
                    "--psm",
                    os.getenv("AICHECK_TESSERACT_PSM", "6"),
                ],
                env=os.environ.copy(),
                timeout=float(os.getenv("AICHECK_TESSERACT_TIMEOUT", "45")),
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "diagnostics": [{"code": "TESSERACT_TIMEOUT", "level": "warning", "message": "Tesseract OCR timed out."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        text = (completed.stdout or "").strip()
        if completed.returncode != 0 and not text:
            return {
                "ok": False,
                "diagnostics": [{"code": "TESSERACT_FAILED", "level": "warning", "message": (completed.stderr or "Tesseract OCR failed.")[-1200:]}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        if not text:
            return {
                "ok": False,
                "diagnostics": [{"code": "TESSERACT_EMPTY", "level": "info", "message": "Tesseract returned no text."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        return {
            "ok": True,
            "text": text,
            "fragments": [{"pageNo": 1, "text": text, "bbox": None, "confidence": 0.55, "sourceEngine": self.name}],
            "diagnostics": [],
            "engine": self.name,
            "engineVersion": self.version,
        }


def ocr_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    predictor = paddle_predictor_options()
    env.update(
        {
            "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
            "PADDLE_PDX_CPU_NUM_THREADS": str(predictor["cpu_threads"]),
            "OMP_NUM_THREADS": os.getenv("AICHECK_PADDLE_SUBPROCESS_OMP_THREADS", "1"),
            "MKL_NUM_THREADS": os.getenv("AICHECK_PADDLE_SUBPROCESS_OMP_THREADS", "1"),
            "OPENBLAS_NUM_THREADS": os.getenv("AICHECK_PADDLE_SUBPROCESS_OMP_THREADS", "1"),
            "FLAGS_use_mkldnn": "0",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    cache_home = os.getenv("PADDLE_PDX_CACHE_HOME")
    model_cache = os.getenv("AICHECK_PADDLEX_MODEL_CACHE")
    if not cache_home and model_cache:
        path = Path(model_cache)
        if path.name == "official_models":
            cache_home = str(path.parent)
        elif (path / "official_models").exists():
            cache_home = str(path)
    if cache_home:
        env["PADDLE_PDX_CACHE_HOME"] = cache_home
    return env


class PaddlexSealEngine(LocalOcrEngine):
    name = "paddlex_seal_recognition"
    version = "paddlex-seal@3.7.0"
    required_package = "paddlex"

    def available(self) -> bool:
        enabled = seal_pipeline_enabled()
        return enabled and self.package_available() and all(path.exists() for path in seal_model_dirs().values())

    def package_available(self) -> bool:
        return importlib.util.find_spec(self.required_package) is not None or subprocess_package_available("paddlex")

    def execution_mode(self) -> str:
        if subprocess_package_available("paddlex"):
            return "subprocess"
        if importlib.util.find_spec(self.required_package) is not None:
            return "inprocess"
        return "unavailable"

    def status(self) -> dict[str, Any]:
        dirs = seal_model_dirs()
        return {
            "engine": self.name,
            "version": self.version,
            "available": self.available(),
            "enabled": os.getenv("AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE", "auto"),
            "executionMode": self.execution_mode(),
            "python": os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON"),
            "subprocessPackageAvailable": subprocess_package_available("paddlex"),
            "modelDirs": {key: str(path) for key, path in dirs.items()},
            "missingModelDirs": [key for key, path in dirs.items() if not path.exists()],
            "package": self.required_package,
        }

    def parse(
        self,
        source_path: Path,
        *,
        file_name: str | None = None,
        profile: dict[str, Any] | None = None,
        variant: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_path = variant_source_path(source_path, variant)
        missing = [key for key, path in seal_model_dirs().items() if not path.exists()]
        if missing:
            return {
                "ok": False,
                "diagnostics": [{"code": "SEAL_MODEL_MISSING", "level": "warning", "message": f"Seal local model directories are missing: {', '.join(missing)}."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        if self.execution_mode() == "subprocess":
            return self.parse_with_subprocess(source_path, profile=profile)
        from paddlex import create_pipeline  # type: ignore

        dirs = seal_model_dirs()
        pipeline = create_pipeline(
            config=seal_pipeline_config(dirs),
            **paddle_predictor_options(),
        )
        raw = pipeline.predict(str(source_path))
        seals = normalize_seal_result(raw)
        diagnostics = []
        seal_rules = (profile or {}).get("sealRules") or {}
        required_seal = parse_bool(seal_rules.get("required"), False) is True
        if required_seal and not seals:
            diagnostics.append({"code": "SEAL_NOT_FOUND", "level": "warning", "message": "未识别到必需印章。"})
        return {
            "ok": bool(seals) or not required_seal,
            "seals": seals,
            "diagnostics": diagnostics,
            "engine": self.name,
            "engineVersion": self.version,
        }

    def parse_with_subprocess(self, source_path: Path, *, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
        if not python_bin or not Path(python_bin).exists():
            return {
                "ok": False,
                "diagnostics": [{"code": "PADDLEX_SEAL_SUBPROCESS_NOT_CONFIGURED", "level": "info", "message": "AICHECK_OCR_SUBPROCESS_PYTHON is not configured."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        script = subprocess_resource_limit_preamble("AICHECK_PADDLEX_SEAL_MEMORY_LIMIT_MB", 1536) + textwrap.dedent(
            """
            import json
            import sys
            from paddlex import create_pipeline

            image_path = sys.argv[1]
            config = json.loads(sys.argv[2])
            predictor = json.loads(sys.argv[3])

            def basic(value):
                if isinstance(value, (str, int, float, bool)) or value is None:
                    return value
                if isinstance(value, dict):
                    return {str(k): basic(v) for k, v in value.items() if str(k) not in {"input_img", "img", "dt_polys"}}
                if isinstance(value, (list, tuple)):
                    return [basic(v) for v in value]
                if hasattr(value, "tolist"):
                    try:
                        return value.tolist()
                    except Exception:
                        return str(value)
                json_payload = getattr(value, "json", None)
                if isinstance(json_payload, dict):
                    return basic(json_payload)
                if callable(json_payload):
                    try:
                        return basic(json_payload())
                    except Exception:
                        pass
                if hasattr(value, "items"):
                    try:
                        return {str(k): basic(v) for k, v in value.items() if str(k) not in {"input_img", "img", "dt_polys"}}
                    except Exception:
                        return str(value)
                return str(value)

            pipeline = create_pipeline(
                config=config,
                **predictor,
            )
            raw = [basic(item) for item in pipeline.predict(image_path)]
            print("AICHECK_PADDLEX_SEAL_RESULT " + json.dumps(raw, ensure_ascii=False), flush=True)
            """
        )
        try:
            completed = run_ocr_subprocess(
                [
                    python_bin,
                    "-c",
                    script,
                    str(source_path),
                    json.dumps(seal_pipeline_config(seal_model_dirs())),
                    json.dumps(paddle_predictor_options()),
                ],
                env=ocr_subprocess_env(),
                timeout=float(os.getenv("AICHECK_PADDLEX_SEAL_TIMEOUT", "160")),
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "diagnostics": [{"code": "PADDLEX_SEAL_TIMEOUT", "level": "warning", "message": "PaddleX seal subprocess timed out."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        if completed.returncode != 0:
            return {
                "ok": False,
                "diagnostics": [{"code": "PADDLEX_SEAL_FAILED", "level": "warning", "message": (completed.stderr or completed.stdout or "PaddleX seal subprocess failed")[-1200:]}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        payload_line = next(
            (line for line in reversed(completed.stdout.splitlines()) if line.startswith("AICHECK_PADDLEX_SEAL_RESULT ")),
            "",
        )
        if not payload_line:
            return {
                "ok": False,
                "diagnostics": [{"code": "PADDLEX_SEAL_EMPTY", "level": "warning", "message": "PaddleX seal subprocess returned no parseable payload."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        raw = json.loads(payload_line.replace("AICHECK_PADDLEX_SEAL_RESULT ", "", 1))
        seals = normalize_seal_result(raw)
        seal_rules = (profile or {}).get("sealRules") or {}
        diagnostics = []
        required_seal = parse_bool(seal_rules.get("required"), False) is True
        if required_seal and not seals:
            diagnostics.append({"code": "SEAL_NOT_FOUND", "level": "warning", "message": "未识别到必需印章。"})
        return {
            "ok": bool(seals) or not required_seal,
            "seals": seals,
            "diagnostics": diagnostics,
            "engine": self.name,
            "engineVersion": self.version,
            "workerMode": "subprocess",
        }


class AgentdesignSealOcrSubprocessEngine(LocalOcrEngine):
    name = "agentdesign_seal_ocr_subprocess"
    version = "agentdesign-seal-ocr@local"

    def available(self) -> bool:
        if not env_bool("AICHECK_ENABLE_AGENTDESIGN_SEAL_OCR", False):
            return False
        python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
        backend_path = agentdesign_backend_path()
        return bool(python_bin and Path(python_bin).exists() and backend_path.exists())

    def status(self) -> dict[str, Any]:
        backend_path = agentdesign_backend_path()
        return {
            "engine": self.name,
            "version": self.version,
            "available": self.available(),
            "enabled": os.getenv("AICHECK_ENABLE_AGENTDESIGN_SEAL_OCR", "false"),
            "python": os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON"),
            "backendPath": str(backend_path),
            "timeoutSeconds": float(os.getenv("AICHECK_AGENTDESIGN_SEAL_TIMEOUT", "140")),
        }

    def parse(
        self,
        source_path: Path,
        *,
        file_name: str | None = None,
        profile: dict[str, Any] | None = None,
        variant: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
        backend_path = agentdesign_backend_path()
        if not python_bin or not Path(python_bin).exists() or not backend_path.exists():
            return {
                "ok": False,
                "diagnostics": [
                    {
                        "code": "AGENTDESIGN_SEAL_OCR_NOT_CONFIGURED",
                        "level": "info",
                        "message": "agentdesign seal OCR subprocess is not configured.",
                    }
                ],
                "engine": self.name,
                "engineVersion": self.version,
            }
        source_path = variant_source_path(source_path, variant)
        config = {
            "max_pages": seal_max_pages(profile),
            "max_candidates_per_page": int(os.getenv("AICHECK_AGENTDESIGN_SEAL_MAX_CANDIDATES", "6")),
            "max_ocr_candidates_per_page": int(os.getenv("AICHECK_AGENTDESIGN_SEAL_MAX_OCR_CANDIDATES", "3")),
            "production_document_timeout_seconds": float(os.getenv("AICHECK_AGENTDESIGN_SEAL_DOCUMENT_TIMEOUT", "120")),
            "production_candidate_timeout_seconds": float(os.getenv("AICHECK_AGENTDESIGN_SEAL_CANDIDATE_TIMEOUT", "35")),
            "enable_vl": False,
            "enable_page_subject_extraction": env_bool("AICHECK_AGENTDESIGN_SEAL_PAGE_SUBJECT", False),
            "enable_ppocr5": env_bool("AICHECK_AGENTDESIGN_SEAL_ENABLE_PPOCR5", False),
            "debug_arc_artifacts": False,
        }
        script = subprocess_resource_limit_preamble("AICHECK_AGENTDESIGN_SEAL_MEMORY_LIMIT_MB", 1536) + textwrap.dedent(
            """
            import json
            import os
            import sys

            image_path, backend_path, config_json = sys.argv[1:4]
            sys.path.insert(0, backend_path)
            from seal_ocr import SealOcrConfig, recognize_document

            kwargs = json.loads(config_json)
            cfg = SealOcrConfig(**kwargs)
            payload = recognize_document(image_path, config=cfg)
            print("AICHECK_AGENTDESIGN_SEAL_RESULT " + json.dumps(payload, ensure_ascii=False), flush=True)
            """
        )
        env = ocr_subprocess_env()
        env["PYTHONPATH"] = f"{backend_path}{os.pathsep}{env.get('PYTHONPATH', '')}"
        try:
            completed = run_ocr_subprocess(
                [python_bin, "-c", script, str(source_path), str(backend_path), json.dumps(config)],
                env=env,
                timeout=float(os.getenv("AICHECK_AGENTDESIGN_SEAL_TIMEOUT", "140")),
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "diagnostics": [
                    {
                        "code": "AGENTDESIGN_SEAL_OCR_TIMEOUT",
                        "level": "warning",
                        "message": "agentdesign seal OCR timed out; visual seal candidate fallback remains available.",
                    }
                ],
                "engine": self.name,
                "engineVersion": self.version,
            }
        if completed.returncode != 0:
            return {
                "ok": False,
                "diagnostics": [
                    {
                        "code": "AGENTDESIGN_SEAL_OCR_FAILED",
                        "level": "warning",
                        "message": (completed.stderr or completed.stdout or "agentdesign seal OCR failed")[-1200:],
                    }
                ],
                "engine": self.name,
                "engineVersion": self.version,
            }
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        payload_line = next((line for line in reversed(lines) if line.startswith("AICHECK_AGENTDESIGN_SEAL_RESULT ")), "")
        if not payload_line:
            return {
                "ok": False,
                "diagnostics": [
                    {
                        "code": "AGENTDESIGN_SEAL_OCR_EMPTY",
                        "level": "warning",
                        "message": "agentdesign seal OCR returned no parseable payload.",
                    }
                ],
                "engine": self.name,
                "engineVersion": self.version,
            }
        payload = json.loads(payload_line.replace("AICHECK_AGENTDESIGN_SEAL_RESULT ", "", 1))
        seals = normalize_agentdesign_seal_result(payload)
        diagnostics = [
            {
                "code": "AGENTDESIGN_SEAL_OCR_REVIEW_REQUIRED",
                "level": "warning",
                "message": "agentdesign seal OCR produced review-required seal results.",
            }
        ] if any("review_required" in (seal.get("qualityFlags") or []) for seal in seals) else []
        return {
            "ok": bool(seals),
            "seals": seals,
            "diagnostics": [*normalize_agentdesign_diagnostics(payload.get("diagnostics") or []), *diagnostics],
            "engine": self.name,
            "engineVersion": self.version,
            "documentSummary": payload.get("document_summary"),
        }


class VisualSealCandidateSubprocessEngine(LocalOcrEngine):
    name = "visual_seal_candidate_subprocess"
    version = "opencv-color-candidate@5"

    def available(self) -> bool:
        python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
        return bool(python_bin and Path(python_bin).exists())

    def status(self) -> dict[str, Any]:
        return {
            "engine": self.name,
            "version": self.version,
            "available": self.available(),
            "python": os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON"),
        }

    def parse(
        self,
        source_path: Path,
        *,
        file_name: str | None = None,
        profile: dict[str, Any] | None = None,
        variant: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
        if not python_bin:
            return {
                "ok": False,
                "diagnostics": [{"code": "VISUAL_SEAL_NOT_CONFIGURED", "level": "info", "message": "AICHECK_OCR_SUBPROCESS_PYTHON is not configured."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        source_path = variant_source_path(source_path, variant)
        script = subprocess_resource_limit_preamble("AICHECK_VISUAL_SEAL_MEMORY_LIMIT_MB", 1024) + textwrap.dedent(
            """
            import json
            import os
            import re
            import sys
            import tempfile
            import cv2
            import numpy as np
            try:
                from apps.ocr_service.seal_text import extract_structured_seal_fields_from_lines
            except Exception:
                extract_structured_seal_fields_from_lines = None

            image_path = sys.argv[1]
            max_candidates = max(0, int(os.getenv("AICHECK_OCR_VISUAL_SEAL_MAX_CANDIDATES", "2") or 0))
            max_ocr_candidates = max(0, int(os.getenv("AICHECK_OCR_VISUAL_SEAL_MAX_OCR_CANDIDATES", "1") or 0))
            image = cv2.imread(image_path)
            if image is None:
                print(json.dumps({"ok": False, "diagnostics": [{"code": "IMAGE_READ_FAILED", "level": "error", "message": "image read failed"}]}, ensure_ascii=False))
                raise SystemExit(0)
            height, width = image.shape[:2]
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            masks = {
                "red": {
                    "mask": cv2.inRange(hsv, np.array([0, 15, 35]), np.array([15, 255, 255])) | cv2.inRange(hsv, np.array([160, 15, 35]), np.array([180, 255, 255])),
                    "kernel": 31,
                    "aspect": (0.35, 2.4),
                    "max_area_ratio": 0.08,
                    "max_bbox_ratio": 0.12,
                },
                "blue": {
                    "mask": cv2.inRange(hsv, np.array([90, 45, 20]), np.array([130, 255, 205])),
                    "kernel": 17,
                    "aspect": (0.45, 6.0),
                    "min_width": 70,
                    "min_height": 70,
                    "max_area_ratio": 0.08,
                    "max_bbox_ratio": 0.055,
                },
            }

            def touches_border(x, y, w_box, h_box):
                return x <= width * 0.01 or y <= height * 0.01 or x + w_box >= width * 0.99 or y + h_box >= height * 0.99

            def contained_by_existing(candidate, selected):
                _, x, y, w_box, h_box, _ = candidate
                center_x = x + w_box / 2
                center_y = y + h_box / 2
                for existing in selected:
                    _, ex, ey, ew, eh, _ = existing
                    if ex <= center_x <= ex + ew and ey <= center_y <= ey + eh:
                        return True
                return False

            crop_ocr = None
            seal_text_keywords = [
                "专用章",
                "单位名称",
                "业务范围",
                "资质证书",
                "有效期",
                "设计院",
                "有限公司",
                "许可",
            ]

            def object_to_dict(value):
                if isinstance(value, dict):
                    return value
                json_value = getattr(value, "json", None)
                if callable(json_value):
                    return json_value()
                if isinstance(json_value, dict):
                    return json_value
                dict_value = getattr(value, "dict", None)
                if callable(dict_value):
                    return dict_value()
                return {}

            def get_crop_ocr():
                global crop_ocr
                if crop_ocr is not None:
                    return crop_ocr
                det_dir = os.getenv("AICHECK_PADDLEOCR_DET_MODEL_DIR")
                rec_dir = os.getenv("AICHECK_PADDLEOCR_REC_MODEL_DIR")
                if not det_dir or not rec_dir:
                    return None
                try:
                    from paddleocr import PaddleOCR

                    crop_ocr = PaddleOCR(
                        text_detection_model_dir=det_dir,
                        text_recognition_model_dir=rec_dir,
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                        text_det_limit_side_len=1200,
                        text_det_limit_type="max",
                        enable_mkldnn=False,
                    )
                    return crop_ocr
                except Exception:
                    return None

            def ocr_image_lines(ocr, image_path):
                try:
                    raw = ocr.predict(image_path)
                except Exception:
                    return []
                page = raw[0] if isinstance(raw, list) and raw else raw
                page = object_to_dict(page)
                texts = page.get("rec_texts") or page.get("texts") or []
                scores = page.get("rec_scores") or page.get("scores") or []
                lines = []
                for index, text in enumerate(texts):
                    text = str(text or "").strip()
                    if not text:
                        continue
                    try:
                        score = float(scores[index]) if index < len(scores) else 0.0
                    except Exception:
                        score = 0.0
                    lines.append((text, score))
                return lines

            def score_seal_lines(lines):
                if not lines:
                    return 0.0
                text_values = [text for text, score in lines if text and score >= 0.2]
                if not text_values:
                    return 0.0
                avg_score = sum(score for _, score in lines) / max(len(lines), 1)
                keyword_hits = sum(1 for text in text_values for keyword in seal_text_keywords if keyword in text)
                cjk_count = sum(1 for text in text_values for char in text if "\\u4e00" <= char <= "\\u9fff")
                return avg_score + min(len(text_values), 10) * 0.08 + keyword_hits * 0.35 + min(cjk_count / 120.0, 0.5)

            def split_label_value(text, label):
                if label not in text:
                    return ""
                value = text.split(label, 1)[1].lstrip("：:;； ").strip()
                return value

            def seal_fields_from_lines(lines, bbox):
                if extract_structured_seal_fields_from_lines is not None:
                    return extract_structured_seal_fields_from_lines(lines, [int(value) for value in bbox])
                field_bbox = [int(value) for value in bbox]
                texts = [text for text, _ in lines]
                line_scores = {text: float(score or 0.0) for text, score in lines}
                fields = []

                def add(name, value, confidence=0.9):
                    value = str(value or "").strip()
                    if value:
                        fields.append({"fieldName": name, "fieldValue": value, "confidence": confidence, "bbox": field_bbox})

                title = next((text for text in texts if "章" in text), "")
                if title:
                    add("印章名称", title)
                for text in texts:
                    text_score = line_scores.get(text, 0.0)
                    matched_effective_date = False
                    for label, name in [
                        ("单位名称", "单位名称"),
                        ("资质证书编号", "资质证书编号"),
                        ("有效期至", "有效期至"),
                        ("有效期", "有效期"),
                    ]:
                        if label == "有效期" and matched_effective_date:
                            continue
                        value = split_label_value(text, label)
                        if value:
                            add(name, value)
                            if label == "有效期至":
                                matched_effective_date = True
                    if "业务范围" in text:
                        value = split_label_value(text, "业务范围")
                        if value:
                            add("业务范围", value)
                    upper_text = text.upper().replace(" ", "")
                    if "TS" in upper_text:
                        match = re.search(r"TS\\d{6,}[-—]?\\d{4}", upper_text)
                        add("许可证编号", match.group(0) if match else text)
                    date_match = re.search(r"(?:19|20)\\d{2}年\\d{1,2}月\\d{1,2}日|(?:19|20)\\d{2}[-/.]\\d{1,2}[-/.]\\d{1,2}", text)
                    if date_match and not any(field.get("fieldName") == "日期" for field in fields):
                        add("日期", date_match.group(0), confidence=text_score or 0.8)
                    if "有限公司" in text and not any(field.get("fieldName") == "单位名称" for field in fields):
                        score = text_score
                        if score >= 0.45:
                            add("单位名称", text, confidence=max(score, 0.6))
                business_index = next((index for index, text in enumerate(texts) if "业务范围" in text), -1)
                if business_index >= 0 and not any(field.get("fieldName") == "业务范围" for field in fields):
                    following = []
                    for text in texts[business_index + 1 :]:
                        if any(stop in text for stop in ["资质证书", "有效期", "单位名称"]):
                            break
                        following.append(text)
                    add("业务范围", " ".join(following))
                raw_texts = [
                    text
                    for text, score in lines
                    if not ("有限公司" in text and float(score or 0.0) < 0.45)
                ]
                add("印章原文", "\\n".join(raw_texts), confidence=sum(score for _, score in lines) / max(len(lines), 1) if lines else 0.0)
                return fields

            def extract_crop_seal_text(x, y, w_box, h_box):
                ocr = get_crop_ocr()
                if ocr is None:
                    return {"lines": [], "fields": [], "confidence": 0.0}
                padding = max(6, int(max(w_box, h_box) * 0.03))
                x1 = max(0, x - padding)
                y1 = max(0, y - padding)
                x2 = min(width, x + w_box + padding)
                y2 = min(height, y + h_box + padding)
                crop = image[y1:y2, x1:x2]
                if crop.size == 0:
                    return {"lines": [], "fields": [], "confidence": 0.0}
                lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
                l_channel, a_channel, b_channel = cv2.split(lab)
                l_channel = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(l_channel)
                clahe_crop = cv2.cvtColor(cv2.merge([l_channel, a_channel, b_channel]), cv2.COLOR_LAB2BGR)
                variants = {
                    "raw": crop,
                    "raw_2x": cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC),
                    "clahe": clahe_crop,
                    "clahe_2x": cv2.resize(clahe_crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC),
                    "cw": cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE),
                    "ccw": cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE),
                    "180": cv2.rotate(crop, cv2.ROTATE_180),
                }

                def useful_seal_line(text, score):
                    text = str(text or "").strip()
                    if not text:
                        return False
                    upper_text = text.upper().replace(" ", "")
                    if "TS" in upper_text:
                        return True
                    if "年" in text and "月" in text and "日" in text:
                        return True
                    if any(keyword in text for keyword in seal_text_keywords):
                        return True
                    if "有限公司" in text and float(score or 0.0) < 0.45:
                        return False
                    return float(score or 0.0) >= 0.88

                def merge_lines(primary, candidates):
                    merged = []
                    seen = {}
                    for text, score in [*primary, *candidates]:
                        if not useful_seal_line(text, score):
                            continue
                        key = str(text).replace(" ", "")
                        if key in seen:
                            if score > merged[seen[key]][1]:
                                merged[seen[key]] = (text, score)
                            continue
                        seen[key] = len(merged)
                        merged.append((text, score))
                    return merged

                best_lines = []
                all_lines = []
                best_score = 0.0
                with tempfile.TemporaryDirectory() as temp_dir:
                    for name, variant_image in variants.items():
                        variant_path = os.path.join(temp_dir, f"seal_{name}.png")
                        cv2.imwrite(variant_path, variant_image)
                        lines = ocr_image_lines(ocr, variant_path)
                        all_lines.extend(lines)
                        score = score_seal_lines(lines)
                        if score > best_score:
                            best_score = score
                            best_lines = lines
                useful_lines = merge_lines(best_lines, all_lines)
                confidence = sum(score for _, score in useful_lines) / max(len(useful_lines), 1) if useful_lines else 0.0
                bbox = [int(x), int(y), int(x + w_box), int(y + h_box)]
                return {
                    "lines": useful_lines,
                    "fields": seal_fields_from_lines(useful_lines, bbox),
                    "confidence": confidence,
                }

            seals = []
            ocr_candidate_count = 0
            for color, config in masks.items():
                mask = config["mask"]
                kernel = np.ones((config["kernel"], config["kernel"]), np.uint8)
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8), iterations=1)
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                candidates = []
                for contour in contours:
                    area = float(cv2.contourArea(contour))
                    if area < max(1000.0, width * height * 0.00008):
                        continue
                    x, y, w, h = cv2.boundingRect(contour)
                    min_width = int(config.get("min_width", 40))
                    min_height = int(config.get("min_height", 25))
                    if w < min_width or h < min_height or touches_border(x, y, w, h):
                        continue
                    aspect = w / float(h)
                    min_aspect, max_aspect = config["aspect"]
                    if aspect < min_aspect or aspect > max_aspect:
                        continue
                    if (w * h) / float(width * height) > config["max_bbox_ratio"]:
                        continue
                    if area / float(width * height) > config["max_area_ratio"]:
                        continue
                    fill_ratio = area / float(w * h)
                    candidates.append((area, x, y, w, h, fill_ratio))
                selected = []
                for candidate in sorted(candidates, reverse=True):
                    if contained_by_existing(candidate, selected):
                        continue
                    selected.append(candidate)
                    if len(selected) >= max_candidates:
                        break
                for index, (area, x, y, w, h, fill_ratio) in enumerate(selected, start=1):
                    seal_type = "visual_red_seal_candidate" if color == "red" else "visual_blue_stamp_candidate"
                    confidence = min(0.95, 0.55 + area / float(width * height) * 50 + min(fill_ratio, 0.45) * 0.2)
                    if ocr_candidate_count < max_ocr_candidates:
                        crop_text = extract_crop_seal_text(x, y, w, h)
                        ocr_candidate_count += 1
                    else:
                        crop_text = {"lines": [], "fields": [], "confidence": 0.0}
                    crop_lines = [text for text, _ in crop_text["lines"]]
                    fields = [{"fieldName": "印章颜色", "fieldValue": color, "confidence": 0.8, "bbox": [int(x), int(y), int(x + w), int(y + h)]}]
                    fields.extend(crop_text["fields"])
                    field_title = next((field.get("fieldValue") for field in fields if field.get("fieldName") == "印章名称" and field.get("fieldValue")), "")
                    seal_name = str(field_title or (crop_lines[0] if crop_lines else ("视觉印章候选" if color == "red" else "视觉蓝章候选")))
                    quality_flags = ["visual_candidate_only", "seal_text_from_crop_ocr"] if crop_lines else ["visual_candidate_only", "requires_seal_ocr_text"]
                    seals.append(
                        {
                            "sealId": f"{color}_candidate_{index}",
                            "pageNo": 1,
                            "sealType": seal_type,
                            "sealName": seal_name,
                            "text": "\\n".join(crop_lines),
                            "fullText": "\\n".join(crop_lines),
                            "bbox": [int(x), int(y), int(x + w), int(y + h)],
                            "polygon": [[int(x), int(y)], [int(x + w), int(y)], [int(x + w), int(y + h)], [int(x), int(y + h)]],
                            "pageWidth": int(width),
                            "pageHeight": int(height),
                            "visualColor": color,
                            "visualConfidence": round(confidence, 4),
                            "ocrConfidence": round(float(crop_text["confidence"]), 4),
                            "fields": fields,
                            "qualityFlags": quality_flags,
                        }
                    )
            print(json.dumps({"ok": bool(seals), "seals": seals, "diagnostics": []}, ensure_ascii=False))
            """
        )
        env = os.environ.copy()
        env.update({"PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        backend_root = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = f"{backend_root}{os.pathsep}{env.get('PYTHONPATH', '')}"
        try:
            completed = run_ocr_subprocess(
                [python_bin, "-c", script, str(source_path)],
                env=env,
                timeout=float(os.getenv("AICHECK_OCR_VISUAL_SEAL_TIMEOUT", "60")),
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "diagnostics": [{"code": "VISUAL_SEAL_TIMEOUT", "level": "warning", "message": "visual seal detection timed out."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        if completed.returncode != 0:
            return {
                "ok": False,
                "diagnostics": [{"code": "VISUAL_SEAL_FAILED", "level": "warning", "message": (completed.stderr or completed.stdout or "visual seal detection failed")[-1000:]}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        payload = json.loads(lines[-1]) if lines else {}
        return {**payload, "engine": self.name, "engineVersion": self.version}


class PaddleOcrVlEngine(LocalOcrEngine):
    name = "paddleocr_vl_1_6"
    version = "paddleocr-vl@1.6"
    required_package = "paddleocr"

    def enabled(self) -> bool:
        if os.getenv("AICHECK_ENABLE_PADDLEOCR_VL") is not None:
            return env_bool("AICHECK_ENABLE_PADDLEOCR_VL", False)
        explicit_model_envs = (
            "PADDLEOCR_VL_MODEL_DIR",
            "AICHECK_PADDLEOCR_VL_LAYOUT_MODEL_DIR",
            "AICHECK_PADDLEOCR_VL_REC_MODEL_DIR",
        )
        return any(bool(os.getenv(name)) for name in explicit_model_envs)

    def available(self) -> bool:
        if not self.enabled():
            return False
        dirs = paddleocr_vl_model_dirs()
        required = ["layout", "vl_rec"]
        return (
            self.package_available()
            and self.transformers_available()
            and self.capacity_ready()
            and all(dirs[key].exists() for key in required)
        )

    def capacity_ready(self) -> bool:
        memory_limit_mb = int(os.getenv("AICHECK_PADDLEOCR_VL_MEMORY_LIMIT_MB", "8192") or 0)
        minimum_memory_mb = int(os.getenv("AICHECK_PADDLEOCR_VL_MIN_MEMORY_MB", "10240") or 0)
        return memory_limit_mb >= minimum_memory_mb

    def package_available(self) -> bool:
        return importlib.util.find_spec(self.required_package) is not None or subprocess_package_available("paddleocr")

    def transformers_available(self) -> bool:
        return importlib.util.find_spec("transformers") is not None or subprocess_package_available("transformers")

    def status(self) -> dict[str, Any]:
        dirs = paddleocr_vl_model_dirs()
        enabled = self.enabled()
        force_subprocess = env_bool("AICHECK_PADDLEOCR_VL_FORCE_SUBPROCESS", True)
        inprocess_ready = importlib.util.find_spec(self.required_package) is not None and importlib.util.find_spec("transformers") is not None
        subprocess_ready = subprocess_package_available("paddleocr") and subprocess_package_available("transformers")
        capacity_ready = self.capacity_ready()
        return {
            "engine": self.name,
            "version": self.version,
            "available": self.available(),
            "enabled": str(enabled).lower(),
            "executionMode": "disabled" if not enabled else "unavailable" if not capacity_ready else "subprocess" if subprocess_ready and (force_subprocess or not inprocess_ready) else "inprocess" if inprocess_ready else "unavailable",
            "python": os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON"),
            "modelDir": os.getenv("PADDLEOCR_VL_MODEL_DIR"),
            "modelDirs": {key: str(path) for key, path in dirs.items()},
            "missingModelDirs": [key for key in ["layout", "vl_rec"] if not dirs[key].exists()],
            "package": self.required_package,
            "transformersAvailable": self.transformers_available(),
            "capacityReady": capacity_ready,
            "memoryLimitMb": int(os.getenv("AICHECK_PADDLEOCR_VL_MEMORY_LIMIT_MB", "8192") or 0),
            "minimumMemoryMb": int(os.getenv("AICHECK_PADDLEOCR_VL_MIN_MEMORY_MB", "10240") or 0),
        }

    def parse(
        self,
        source_path: Path,
        *,
        file_name: str | None = None,
        profile: dict[str, Any] | None = None,
        variant: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_path = variant_source_path(source_path, variant)
        dirs = paddleocr_vl_model_dirs()
        missing = [key for key in ["layout", "vl_rec"] if not dirs[key].exists()]
        if missing:
            return {
                "ok": False,
                "diagnostics": [
                    {
                        "code": "PADDLEOCR_VL_MODEL_MISSING",
                        "level": "warning",
                        "message": f"PaddleOCR-VL local model directories are missing: {', '.join(missing)}.",
                    }
                ],
                "engine": self.name,
                "engineVersion": self.version,
            }
        if env_bool("AICHECK_PADDLEOCR_VL_FORCE_SUBPROCESS", True) or importlib.util.find_spec(self.required_package) is None:
            return self.parse_with_subprocess(source_path, dirs=dirs)
        from paddleocr import PaddleOCRVL  # type: ignore

        engine = PaddleOCRVL(
            pipeline_version="v1.6",
            layout_detection_model_dir=str(dirs["layout"]),
            vl_rec_model_dir=str(dirs["vl_rec"]),
            doc_orientation_classify_model_dir=str(dirs["doc_orientation"]) if dirs["doc_orientation"].exists() else None,
            doc_unwarping_model_dir=str(dirs["doc_unwarping"]) if dirs["doc_unwarping"].exists() else None,
            use_doc_orientation_classify=dirs["doc_orientation"].exists(),
            use_doc_unwarping=dirs["doc_unwarping"].exists(),
            use_layout_detection=True,
            use_chart_recognition=False,
            use_seal_recognition=False,
            format_block_content=True,
            merge_layout_blocks=True,
        )
        raw = engine.predict(str(source_path))
        text, fragments, tables, layout_blocks = normalize_vl_result(raw, self.name)
        return {
            "ok": bool(text.strip() or fragments or tables or layout_blocks),
            "text": text,
            "fragments": fragments,
            "tables": tables,
            "layoutBlocks": layout_blocks,
            "metadata": {
                "documentLevel": str(source_path).lower().endswith(".pdf"),
                "engineScope": "document" if str(source_path).lower().endswith(".pdf") else "page",
            },
            "diagnostics": [],
            "engine": self.name,
            "engineVersion": self.version,
        }

    def parse_with_subprocess(self, source_path: Path, *, dirs: dict[str, Path]) -> dict[str, Any]:
        python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
        if not python_bin or not Path(python_bin).exists():
            return {
                "ok": False,
                "diagnostics": [{"code": "PADDLEOCR_VL_SUBPROCESS_NOT_CONFIGURED", "level": "info", "message": "AICHECK_OCR_SUBPROCESS_PYTHON is not configured."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        script = subprocess_resource_limit_preamble("AICHECK_PADDLEOCR_VL_MEMORY_LIMIT_MB", 8192) + textwrap.dedent(
            """
            import json
            import sys
            from paddleocr import PaddleOCRVL

            image_path = sys.argv[1]
            dirs = json.loads(sys.argv[2])

            def basic(value):
                if isinstance(value, (str, int, float, bool)) or value is None:
                    return value
                if isinstance(value, dict):
                    return {str(k): basic(v) for k, v in value.items() if str(k) not in {"input_img", "img"}}
                if isinstance(value, (list, tuple)):
                    return [basic(v) for v in value]
                if hasattr(value, "tolist"):
                    try:
                        return value.tolist()
                    except Exception:
                        return str(value)
                json_payload = getattr(value, "json", None)
                if isinstance(json_payload, dict):
                    return basic(json_payload)
                if callable(json_payload):
                    try:
                        return basic(json_payload())
                    except Exception:
                        pass
                if hasattr(value, "items"):
                    try:
                        return {str(k): basic(v) for k, v in value.items() if str(k) not in {"input_img", "img"}}
                    except Exception:
                        return str(value)
                return str(value)

            engine = PaddleOCRVL(
                pipeline_version="v1.6",
                layout_detection_model_dir=dirs["layout"],
                vl_rec_model_dir=dirs["vl_rec"],
                doc_orientation_classify_model_dir=dirs.get("doc_orientation") or None,
                doc_unwarping_model_dir=dirs.get("doc_unwarping") or None,
                use_doc_orientation_classify=bool(dirs.get("doc_orientation")),
                use_doc_unwarping=bool(dirs.get("doc_unwarping")),
                use_layout_detection=True,
                use_chart_recognition=False,
                use_seal_recognition=False,
                format_block_content=True,
                merge_layout_blocks=True,
            )
            raw = [basic(item) for item in engine.predict(image_path)]
            print("AICHECK_PADDLEOCR_VL_RESULT " + json.dumps(raw, ensure_ascii=False), flush=True)
            """
        )
        payload_dirs = {
            "layout": str(dirs["layout"]),
            "vl_rec": str(dirs["vl_rec"]),
            "doc_orientation": str(dirs["doc_orientation"]) if dirs["doc_orientation"].exists() else "",
            "doc_unwarping": str(dirs["doc_unwarping"]) if dirs["doc_unwarping"].exists() else "",
        }
        try:
            completed = run_ocr_subprocess(
                [python_bin, "-c", script, str(source_path), json.dumps(payload_dirs)],
                env=ocr_subprocess_env(),
                timeout=float(os.getenv("AICHECK_PADDLEOCR_VL_TIMEOUT", "120")),
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "diagnostics": [{"code": "PADDLEOCR_VL_TIMEOUT", "level": "warning", "message": "PaddleOCR-VL subprocess timed out."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        if completed.returncode != 0:
            return {
                "ok": False,
                "diagnostics": [{"code": "PADDLEOCR_VL_FAILED", "level": "warning", "message": (completed.stderr or completed.stdout or "PaddleOCR-VL subprocess failed")[-1200:]}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        payload_line = next((line for line in reversed(completed.stdout.splitlines()) if line.startswith("AICHECK_PADDLEOCR_VL_RESULT ")), "")
        if not payload_line:
            return {
                "ok": False,
                "diagnostics": [{"code": "PADDLEOCR_VL_EMPTY", "level": "warning", "message": "PaddleOCR-VL subprocess returned no parseable payload."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        raw = json.loads(payload_line.replace("AICHECK_PADDLEOCR_VL_RESULT ", "", 1))
        text, fragments, tables, layout_blocks = normalize_vl_result(raw, self.name)
        return {
            "ok": bool(text.strip() or fragments or tables or layout_blocks),
            "text": text,
            "fragments": fragments,
            "tables": tables,
            "layoutBlocks": layout_blocks,
            "metadata": {
                "documentLevel": str(source_path).lower().endswith(".pdf"),
                "engineScope": "document" if str(source_path).lower().endswith(".pdf") else "page",
            },
            "diagnostics": [],
            "engine": self.name,
            "engineVersion": self.version,
            "workerMode": "subprocess",
        }


class DoclingLocalEngine(LocalOcrEngine):
    name = "docling_local"
    version = "docling-local"
    required_env = "DOCLING_ARTIFACTS_PATH"
    required_package = "docling"

    def available(self) -> bool:
        return self.package_available() and docling_artifacts_ready()

    def package_available(self) -> bool:
        return importlib.util.find_spec(self.required_package) is not None or subprocess_package_available("docling")

    def status(self) -> dict[str, Any]:
        model_dir = os.getenv(self.required_env)
        return {
            "engine": self.name,
            "version": self.version,
            "available": self.available(),
            "executionMode": "inprocess" if importlib.util.find_spec(self.required_package) is not None else "subprocess" if subprocess_package_available("docling") else "unavailable",
            "python": os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON"),
            "modelDir": model_dir,
            "artifactsReady": docling_artifacts_ready(),
            "package": self.required_package,
        }

    def parse(
        self,
        source_path: Path,
        *,
        file_name: str | None = None,
        profile: dict[str, Any] | None = None,
        variant: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if importlib.util.find_spec(self.required_package) is None:
            return self.parse_with_subprocess(variant_source_path(source_path, variant))
        from docling.document_converter import DocumentConverter  # type: ignore

        source_path = variant_source_path(source_path, variant)
        converter = DocumentConverter()
        result = converter.convert(str(source_path))
        text = result.document.export_to_markdown()
        payload = docling_document_payload(result.document)
        fragments, tables, layout_blocks = normalize_docling_payload(payload, text, self.name)
        return {
            "ok": bool(text.strip() or fragments or tables or layout_blocks),
            "text": text,
            "fragments": fragments,
            "tables": tables,
            "layoutBlocks": layout_blocks,
            "metadata": {
                "documentLevel": str(source_path).lower().endswith(".pdf"),
                "engineScope": "document" if str(source_path).lower().endswith(".pdf") else "page",
            },
            "diagnostics": [],
            "engine": self.name,
            "engineVersion": self.version,
        }

    def parse_with_subprocess(self, source_path: Path) -> dict[str, Any]:
        python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
        if not python_bin or not Path(python_bin).exists():
            return {
                "ok": False,
                "diagnostics": [{"code": "DOCLING_SUBPROCESS_NOT_CONFIGURED", "level": "info", "message": "AICHECK_OCR_SUBPROCESS_PYTHON is not configured."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        script = textwrap.dedent(
            """
            import json
            import sys
            from docling.document_converter import DocumentConverter

            source_path = sys.argv[1]
            converter = DocumentConverter()
            result = converter.convert(source_path)
            text = result.document.export_to_markdown()
            payload = {}
            for method in ("export_to_dict", "dict", "model_dump"):
                fn = getattr(result.document, method, None)
                if callable(fn):
                    try:
                        payload = fn()
                        break
                    except Exception:
                        pass
            print("AICHECK_DOCLING_RESULT " + json.dumps({"text": text, "document": payload}, ensure_ascii=False), flush=True)
            """
        )
        try:
            completed = run_ocr_subprocess(
                [python_bin, "-c", script, str(source_path)],
                env=ocr_subprocess_env(),
                timeout=float(os.getenv("AICHECK_DOCLING_TIMEOUT", "180")),
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "diagnostics": [{"code": "DOCLING_TIMEOUT", "level": "warning", "message": "Docling subprocess timed out."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        if completed.returncode != 0:
            return {
                "ok": False,
                "diagnostics": [{"code": "DOCLING_FAILED", "level": "warning", "message": (completed.stderr or completed.stdout or "Docling subprocess failed")[-1200:]}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        payload_line = next((line for line in reversed(completed.stdout.splitlines()) if line.startswith("AICHECK_DOCLING_RESULT ")), "")
        if not payload_line:
            return {
                "ok": False,
                "diagnostics": [{"code": "DOCLING_EMPTY", "level": "warning", "message": "Docling subprocess returned no parseable payload."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
        payload = json.loads(payload_line.replace("AICHECK_DOCLING_RESULT ", "", 1))
        text = str(payload.get("text") or "")
        fragments, tables, layout_blocks = normalize_docling_payload(payload.get("document") or {}, text, self.name)
        return {
            "ok": bool(text.strip() or fragments or tables or layout_blocks),
            "text": text,
            "fragments": fragments,
            "tables": tables,
            "layoutBlocks": layout_blocks,
            "metadata": {
                "documentLevel": str(source_path).lower().endswith(".pdf"),
                "engineScope": "document" if str(source_path).lower().endswith(".pdf") else "page",
            },
            "diagnostics": [],
            "engine": self.name,
            "engineVersion": self.version,
            "workerMode": "subprocess",
        }


def docling_document_payload(document: Any) -> dict[str, Any]:
    for method in ("export_to_dict", "dict", "model_dump"):
        fn = getattr(document, method, None)
        if callable(fn):
            try:
                payload = fn()
            except Exception:
                continue
            if isinstance(payload, dict):
                return payload
    return {}


def normalize_docling_payload(payload: dict[str, Any], markdown: str, engine_name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    fragments: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    layout_blocks: list[dict[str, Any]] = []
    for index, item in enumerate(flatten_docling_items(payload), start=1):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("type") or item.get("self_ref") or "")
        text = str(item.get("text") or item.get("orig") or item.get("content") or "").strip()
        page_no = docling_page_no(item)
        bbox = docling_bbox(item)
        if "table" in label.lower() or item.get("data") or item.get("cells"):
            table = docling_table(item, index=index, page_no=page_no, bbox=bbox, engine_name=engine_name)
            if table:
                tables.append(table)
                layout_blocks.append({"blockId": f"docling_table_{index}", "blockType": "table", "pageNo": page_no, "bbox": bbox, "sourceEngine": engine_name})
                continue
        if text:
            confidence = 0.9 if bbox else 0.68
            quality_flags = ["docling_block"]
            if not bbox:
                quality_flags.append("evidence_bbox_missing")
            fragments.append(
                {
                    "pageNo": page_no,
                    "text": text,
                    "bbox": bbox,
                    "confidence": confidence,
                    "sourceEngine": engine_name,
                    "fragmentType": "docling_block",
                    "qualityFlags": quality_flags,
                }
            )
            layout_blocks.append({"blockId": f"docling_text_{index}", "blockType": label or "text", "pageNo": page_no, "bbox": bbox, "sourceEngine": engine_name})
    if not fragments and markdown.strip():
        fragments.append(
            {
                "pageNo": 1,
                "text": markdown,
                "bbox": None,
                "confidence": 0.62,
                "sourceEngine": engine_name,
                "fragmentType": "markdown",
                "qualityFlags": ["docling_markdown_only", "evidence_bbox_missing"],
            }
        )
    return fragments, tables, layout_blocks


def flatten_docling_items(payload: Any) -> list[Any]:
    if isinstance(payload, dict):
        items: list[Any] = []
        for key in ("texts", "tables", "groups", "pictures", "items", "children", "body"):
            value = payload.get(key)
            if isinstance(value, list):
                items.extend(value)
        if not items:
            for value in payload.values():
                if isinstance(value, (dict, list)):
                    items.extend(flatten_docling_items(value))
        return items
    if isinstance(payload, list):
        items = []
        for value in payload:
            if isinstance(value, dict):
                items.append(value)
                items.extend(flatten_docling_items(value))
            elif isinstance(value, list):
                items.extend(flatten_docling_items(value))
        return items
    return []


def docling_page_no(item: dict[str, Any]) -> int:
    prov = item.get("prov")
    if isinstance(prov, list) and prov and isinstance(prov[0], dict):
        return int(prov[0].get("page_no") or prov[0].get("pageNo") or 1)
    return int(item.get("pageNo") or item.get("page_no") or 1)


def docling_bbox(item: dict[str, Any]) -> list[float] | None:
    prov = item.get("prov")
    bbox = None
    if isinstance(prov, list) and prov and isinstance(prov[0], dict):
        bbox = prov[0].get("bbox")
    bbox = bbox or item.get("bbox")
    if isinstance(bbox, dict):
        keys = ("l", "t", "r", "b")
        if all(key in bbox for key in keys):
            return [float(bbox["l"]), float(bbox["t"]), float(bbox["r"]), float(bbox["b"])]
        keys = ("x0", "y0", "x1", "y1")
        if all(key in bbox for key in keys):
            return [float(bbox["x0"]), float(bbox["y0"]), float(bbox["x1"]), float(bbox["y1"])]
    if isinstance(bbox, list) and len(bbox) == 4:
        try:
            return [float(value) for value in bbox]
        except (TypeError, ValueError):
            return None
    return None


def docling_table(item: dict[str, Any], *, index: int, page_no: int, bbox: list[float] | None, engine_name: str) -> dict[str, Any] | None:
    cells = item.get("cells") or ((item.get("data") or {}).get("table_cells") if isinstance(item.get("data"), dict) else None)
    if not isinstance(cells, list):
        return None
    normalized_cells = []
    for cell_index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            continue
        row = first_int(
            cell.get("start_row_offset_idx"),
            cell.get("row"),
            cell.get("row_idx"),
            default=0,
        )
        col = first_int(
            cell.get("start_col_offset_idx"),
            cell.get("col"),
            cell.get("col_idx"),
            default=0,
        )
        text = str(cell.get("text") or cell.get("content") or "").strip()
        normalized_cells.append(
            {
                "cellId": f"docling_cell_{index}_{cell_index}",
                "row": row,
                "col": col,
                "rowspan": int(cell.get("rowspan") or 1),
                "colspan": int(cell.get("colspan") or 1),
                "text": text,
                "bbox": docling_bbox(cell),
                "confidence": 0.9 if docling_bbox(cell) else 0.68,
                "isHeader": bool(cell.get("column_header") or cell.get("row_header") or row == 0),
            }
        )
    if not normalized_cells:
        return None
    return {
        "tableId": f"docling_table_{index}",
        "pageNo": page_no,
        "bbox": bbox,
        "rows": max((cell["row"] for cell in normalized_cells), default=0) + 1,
        "columns": max((cell["col"] for cell in normalized_cells), default=0) + 1,
        "cells": normalized_cells,
        "normalizedRows": table_cells_to_rows(normalized_cells),
        "structureConfidence": docling_table_confidence(normalized_cells, bbox),
        "sourceEngine": engine_name,
        "qualityFlags": docling_table_quality_flags(normalized_cells, bbox),
    }


def first_int(*values: Any, default: int = 0) -> int:
    for value in values:
        if isinstance(value, bool):
            continue
        try:
            if value is None or value == "":
                continue
            return int(value)
        except (TypeError, ValueError):
            continue
    return default


def docling_table_confidence(cells: list[dict[str, Any]], bbox: list[float] | None) -> float:
    if not cells:
        return 0.0
    cell_evidence = len([cell for cell in cells if cell.get("bbox")]) / max(len(cells), 1)
    fill_rate = len([cell for cell in cells if str(cell.get("text") or "").strip()]) / max(len(cells), 1)
    base = 0.58 + fill_rate * 0.18 + cell_evidence * 0.16 + (0.06 if bbox else 0.0)
    return round(min(base, 0.94), 4)


def docling_table_quality_flags(cells: list[dict[str, Any]], bbox: list[float] | None) -> list[str]:
    flags = ["docling_structured_table"]
    if not bbox:
        flags.append("table_evidence_missing")
    if any(not cell.get("bbox") for cell in cells):
        flags.append("cell_evidence_missing")
    return flags


def table_cells_to_rows(cells: list[dict[str, Any]]) -> list[dict[str, str]]:
    header_by_col = {
        int(cell.get("col") or 0): str(cell.get("text") or f"col_{int(cell.get('col') or 0)}")
        for cell in cells
        if cell.get("isHeader")
    }
    rows: dict[int, dict[str, str]] = {}
    for cell in cells:
        row = int(cell.get("row") or 0)
        if row == 0 and header_by_col:
            continue
        col = int(cell.get("col") or 0)
        key = header_by_col.get(col) or f"col_{col}"
        rows.setdefault(row, {})[key] = str(cell.get("text") or "")
    return [rows[index] for index in sorted(rows)]


def local_engines() -> list[LocalOcrEngine]:
    return [
        PyMuPdfTextLayerEngine(),
        PaddleOcrSubprocessEngine(),
        TesseractCliEngine(),
        PaddleOcrEngine(),
        PpStructureEngine(),
        OpenCvTableGridSubprocessEngine(),
        PaddlexSealEngine(),
        AgentdesignSealOcrSubprocessEngine(),
        VisualSealCandidateSubprocessEngine(),
        PaddleOcrVlEngine(),
        DoclingLocalEngine(),
    ]


def variant_source_path(source_path: Path, variant: dict[str, Any] | None) -> Path:
    if isinstance(variant, dict) and variant.get("path"):
        candidate = Path(str(variant["path"]))
        if candidate.exists():
            return candidate
    return source_path


def paddle_runtime_options(profile: dict[str, Any] | None) -> dict[str, Any]:
    policy = (profile or {}).get("preprocessPolicy") or {}
    ocr_policy = policy.get("ocr") or {}
    return {
        "use_doc_orientation_classify": bool(ocr_policy.get("useDocOrientationClassify", policy.get("useDocOrientationClassify", False))),
        "use_doc_unwarping": bool(ocr_policy.get("useDocUnwarping", policy.get("useDocUnwarping", False))),
        "use_textline_orientation": bool(ocr_policy.get("useTextlineOrientation", policy.get("useTextlineOrientation", False))),
        "text_det_limit_side_len": int(ocr_policy.get("textDetLimitSideLen") or policy.get("textDetLimitSideLen") or 2400),
    }


def paddle_predictor_options() -> dict[str, Any]:
    try:
        cpu_threads = int(os.getenv("AICHECK_PADDLE_CPU_THREADS", "1"))
    except (TypeError, ValueError):
        cpu_threads = 1
    return {
        "device": os.getenv("AICHECK_PADDLE_DEVICE", "cpu").strip() or "cpu",
        "enable_mkldnn": False,
        "cpu_threads": max(1, min(cpu_threads, 4)),
    }


def seal_pipeline_enabled() -> bool:
    value = os.getenv("AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE")
    if value is None or value.strip().lower() == "auto":
        return True
    return value.strip().lower() in {"1", "true", "yes", "on"}


def seal_max_pages(profile: dict[str, Any] | None) -> int:
    seal_policy = ((profile or {}).get("preprocessPolicy") or {}).get("seal") or {}
    if seal_policy.get("maxPages"):
        return int(seal_policy["maxPages"])
    if parse_bool(((profile or {}).get("sealRules") or {}).get("required"), False) is True:
        return int(os.getenv("AICHECK_AGENTDESIGN_SEAL_MAX_PAGES", "6"))
    return int(os.getenv("AICHECK_AGENTDESIGN_SEAL_MAX_PAGES", "1"))


def model_dir(
    env_name: str,
    model_name: str,
    *,
    aliases: tuple[str, ...] = (),
    root_envs: tuple[str, ...] = (
        "AICHECK_PADDLEX_MODEL_CACHE",
        "PADDLEOCR_MODEL_DIR",
        "PADDLEX_MODEL_DIR",
        "PADDLEOCR_VL_MODEL_DIR",
    ),
) -> Path:
    if os.getenv(env_name):
        return Path(os.environ[env_name])
    candidates: list[Path] = []
    for root_env in root_envs:
        if not os.getenv(root_env):
            continue
        root = Path(os.environ[root_env])
        for name in (model_name, *aliases):
            candidates.extend([root if root.name == name else root / name, root / "official_models" / name])
    for name in (model_name, *aliases):
        candidates.append(Path("/models") / name)
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0] if candidates else Path("/models") / model_name)


def paddle_text_model_dirs_available() -> bool:
    return model_dir("AICHECK_PADDLEOCR_DET_MODEL_DIR", "PP-OCRv6_medium_det").exists() and model_dir("AICHECK_PADDLEOCR_REC_MODEL_DIR", "PP-OCRv6_medium_rec").exists()


def pp_structure_model_dirs() -> dict[str, Path]:
    return {
        "layout": model_dir("AICHECK_PPSTRUCTURE_LAYOUT_MODEL_DIR", "PP-DocLayout-L"),
        "text_det": model_dir("AICHECK_PADDLEOCR_DET_MODEL_DIR", "PP-OCRv6_medium_det"),
        "text_rec": model_dir("AICHECK_PADDLEOCR_REC_MODEL_DIR", "PP-OCRv6_medium_rec"),
        "wired_table_structure": model_dir("AICHECK_PPSTRUCTURE_WIRED_TABLE_STRUCTURE_MODEL_DIR", "SLANeXt_wired"),
        "wired_table_cells": model_dir("AICHECK_PPSTRUCTURE_WIRED_TABLE_CELLS_MODEL_DIR", "RT-DETR-L_wired_table_cell_det"),
        "wireless_table_structure": model_dir("AICHECK_PPSTRUCTURE_WIRELESS_TABLE_STRUCTURE_MODEL_DIR", "SLANeXt_wireless"),
        "wireless_table_cells": model_dir("AICHECK_PPSTRUCTURE_WIRELESS_TABLE_CELLS_MODEL_DIR", "RT-DETR-L_wireless_table_cell_det"),
    }


def pp_structure_model_names(dirs: dict[str, Path]) -> dict[str, str]:
    defaults = {
        "layout": "PP-DocLayout-L",
        "text_det": "PP-OCRv6_medium_det",
        "text_rec": "PP-OCRv6_medium_rec",
        "wired_table_structure": "SLANeXt_wired",
        "wired_table_cells": "RT-DETR-L_wired_table_cell_det",
        "wireless_table_structure": "SLANeXt_wireless",
        "wireless_table_cells": "RT-DETR-L_wireless_table_cell_det",
    }
    env_names = {
        "layout": "AICHECK_PPSTRUCTURE_LAYOUT_MODEL_NAME",
        "text_det": "AICHECK_PADDLEOCR_DET_MODEL_NAME",
        "text_rec": "AICHECK_PADDLEOCR_REC_MODEL_NAME",
        "wired_table_structure": "AICHECK_PPSTRUCTURE_WIRED_TABLE_STRUCTURE_MODEL_NAME",
        "wired_table_cells": "AICHECK_PPSTRUCTURE_WIRED_TABLE_CELLS_MODEL_NAME",
        "wireless_table_structure": "AICHECK_PPSTRUCTURE_WIRELESS_TABLE_STRUCTURE_MODEL_NAME",
        "wireless_table_cells": "AICHECK_PPSTRUCTURE_WIRELESS_TABLE_CELLS_MODEL_NAME",
    }
    names: dict[str, str] = {}
    for key, default in defaults.items():
        env_value = os.getenv(env_names[key])
        dir_name = dirs.get(key).name if dirs.get(key) else ""
        names[key] = str(env_value or dir_name or default)
    return names


def seal_model_dirs() -> dict[str, Path]:
    return {
        "layout": model_dir("AICHECK_SEAL_LAYOUT_MODEL_DIR", "PP-DocLayoutV3"),
        "doc_orientation": model_dir("AICHECK_SEAL_DOC_ORI_MODEL_DIR", "PP-LCNet_x1_0_doc_ori"),
        "doc_unwarping": model_dir("AICHECK_SEAL_DOC_UNWARP_MODEL_DIR", "UVDoc"),
        "seal_det": model_dir("AICHECK_SEAL_DET_MODEL_DIR", "PP-OCRv4_server_seal_det"),
        "seal_rec": model_dir("AICHECK_SEAL_REC_MODEL_DIR", "PP-OCRv4_server_rec"),
    }


def seal_pipeline_config(dirs: dict[str, Path]) -> dict[str, Any]:
    return {
        "pipeline_name": "seal_recognition",
        "use_doc_preprocessor": True,
        "use_layout_detection": True,
        "SubModules": {
            "LayoutDetection": {
                "module_name": "layout_detection",
                "model_name": dirs["layout"].name,
                "model_dir": str(dirs["layout"]),
                "threshold": 0.5,
                "layout_nms": True,
                "layout_unclip_ratio": 1.0,
                "layout_merge_bboxes_mode": "small",
            }
        },
        "SubPipelines": {
            "DocPreprocessor": {
                "pipeline_name": "doc_preprocessor",
                "use_doc_orientation_classify": True,
                "use_doc_unwarping": True,
                "SubModules": {
                    "DocOrientationClassify": {
                        "module_name": "doc_text_orientation",
                        "model_name": dirs["doc_orientation"].name,
                        "model_dir": str(dirs["doc_orientation"]),
                    },
                    "DocUnwarping": {
                        "module_name": "image_unwarping",
                        "model_name": dirs["doc_unwarping"].name,
                        "model_dir": str(dirs["doc_unwarping"]),
                    },
                },
            },
            "SealOCR": {
                "pipeline_name": "OCR",
                "text_type": "seal",
                "use_doc_preprocessor": False,
                "use_textline_orientation": False,
                "SubModules": {
                    "TextDetection": {
                        "module_name": "seal_text_detection",
                        "model_name": dirs["seal_det"].name,
                        "model_dir": str(dirs["seal_det"]),
                        "limit_side_len": 736,
                        "limit_type": "min",
                        "max_side_len": 4000,
                        "thresh": 0.2,
                        "box_thresh": 0.6,
                        "unclip_ratio": 0.5,
                    },
                    "TextRecognition": {
                        "module_name": "text_recognition",
                        "model_name": dirs["seal_rec"].name,
                        "model_dir": str(dirs["seal_rec"]),
                        "batch_size": 1,
                        "score_thresh": 0,
                    },
                },
            },
        },
    }


def paddleocr_vl_model_dirs() -> dict[str, Path]:
    return {
        "layout": model_dir("AICHECK_PADDLEOCR_VL_LAYOUT_MODEL_DIR", "PP-DocLayoutV3"),
        "vl_rec": model_dir("AICHECK_PADDLEOCR_VL_REC_MODEL_DIR", "PaddleOCR-VL-1.6-0.9B", aliases=("PaddleOCR-VL-1.6",)),
        "doc_orientation": model_dir("AICHECK_PADDLEOCR_VL_DOC_ORI_MODEL_DIR", "PP-LCNet_x1_0_doc_ori"),
        "doc_unwarping": model_dir("AICHECK_PADDLEOCR_VL_DOC_UNWARP_MODEL_DIR", "UVDoc"),
    }


def agentdesign_backend_path() -> Path:
    return Path(os.getenv("AICHECK_AGENTDESIGN_BACKEND", "/Volumes/Volume/project/agentdesign/mvp-system/backend"))


def subprocess_model_dir(env_name: str, model_name: str) -> Path:
    return model_dir(env_name, model_name)


def required_env_path_exists(env_name: str | None) -> bool:
    if not env_name:
        return True
    value = os.getenv(env_name)
    return bool(value and Path(value).exists())


def docling_artifacts_ready() -> bool:
    value = os.getenv("DOCLING_ARTIFACTS_PATH")
    if not value:
        return False
    path = Path(value)
    if not path.exists() or not path.is_dir():
        return False
    return any(item.is_file() for item in path.rglob("*"))


def subprocess_package_available(package_name: str) -> bool:
    python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
    if not python_bin or not Path(python_bin).exists():
        return False
    script = "import importlib.util,sys; raise SystemExit(0 if importlib.util.find_spec(sys.argv[1]) is not None else 1)"
    try:
        completed = subprocess.run(
            [python_bin, "-c", script, package_name],
            check=False,
            capture_output=True,
            encoding="utf-8",
            env=ocr_subprocess_env(),
            timeout=10,
        )
    except Exception:
        return False
    return completed.returncode == 0


def first_numeric(raw: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key not in raw or raw[key] is None:
            continue
        try:
            return float(raw[key])
        except (TypeError, ValueError):
            continue
    return float(default)


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
                    "confidence": float(scores[index]) if index < len(scores) and scores[index] is not None else 0.0,
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
    items: list[Any] = []
    for raw_item in iterable_raw_items(raw):
        items.extend(extract_structure_items(raw_item))
    for index, item in enumerate(items):
        item = dict_like_payload(item)
        if not isinstance(item, dict):
            continue
        block_type = str(item.get("type") or item.get("label") or "layout")
        bbox = item.get("bbox") or item.get("box") or bbox_from_coordinate(item.get("coordinate"))
        res = item.get("res")
        res_text = res.get("text") if isinstance(res, dict) else None
        res_html = res.get("html") if isinstance(res, dict) else None
        blocks.append(
            {
                "blockId": f"layout_{index + 1}",
                "blockType": block_type,
                "pageNo": normalize_page_no(item, fallback=1),
                "bbox": bbox,
                "text": item.get("text") or res_text,
                "confidence": first_numeric(item, "confidence", "score", default=0.0),
                "sourceEngine": source_engine,
            }
        )
        if "table" in block_type.lower():
            html = item.get("html") or res_html
            table_structure = html_table_to_structure(str(html or ""))
            if table_structure["rows"] <= 0 or table_structure["columns"] <= 0 or not table_structure["cells"]:
                continue
            tables.append(
                {
                    "tableId": f"table_{len(tables) + 1}",
                    "pageNo": normalize_page_no(item, fallback=1),
                    "bbox": bbox,
                    "rows": table_structure["rows"],
                    "columns": table_structure["columns"],
                    "cells": table_structure["cells"],
                    "html": html,
                    "markdown": item.get("markdown"),
                    "normalizedRows": table_structure["normalizedRows"],
                    "structureConfidence": first_numeric(item, "confidence", "score", default=0.0),
                    "sourceEngine": source_engine,
                }
            )
    return tables, blocks


def normalize_vl_result(raw: Any, source_engine: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    fragments: list[dict[str, Any]] = []
    tables, layout_blocks = normalize_structure_result(raw, source_engine)
    seen_text: set[str] = set()
    for page_index, raw_item in enumerate(iterable_raw_items(raw), start=1):
        item = dict_like_payload(raw_item)
        page_no = page_index
        if isinstance(item, dict):
            page_no = normalize_page_no(item, fallback=page_index)
            text_values = vl_text_values(item)
            html_values = recursive_values_for_keys(item, {"html"})
            for html in html_values:
                if not isinstance(html, str) or not html.strip():
                    continue
                table_structure = html_table_to_structure(html)
                if table_structure["cells"]:
                    tables.append(
                        {
                            "tableId": f"vl_html_table_{len(tables) + 1}",
                            "pageNo": page_no,
                            "bbox": None,
                            "rows": table_structure["rows"],
                            "columns": table_structure["columns"],
                            "cells": table_structure["cells"],
                            "html": html,
                            "normalizedRows": table_structure["normalizedRows"],
                            "structureConfidence": 0.78,
                            "sourceEngine": source_engine,
                            "qualityFlags": ["paddleocr_vl_html_table"],
                        }
                    )
        elif isinstance(item, str):
            text_values = [item]
        else:
            text_values = []
        for text in text_values:
            normalized = "\n".join(part.strip() for part in str(text).splitlines() if part.strip())
            if not normalized or normalized in seen_text:
                continue
            seen_text.add(normalized)
            fragments.append(
                {
                    "pageNo": page_no,
                    "text": normalized,
                    "bbox": None,
                    "confidence": 0.66,
                    "sourceEngine": source_engine,
                    "qualityFlags": ["paddleocr_vl_text", "evidence_bbox_missing"],
                }
            )
    return "\n".join(item["text"] for item in fragments), fragments, tables, layout_blocks


def vl_text_values(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in [
        "markdown",
        "markdown_text",
        "markdownText",
        "text",
        "content",
        "result",
        "block_content",
        "blockContent",
    ]:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(part) for part in value if isinstance(part, str) and part.strip())
    for value in recursive_values_for_keys(item, {"markdown", "text", "content", "result"}):
        if isinstance(value, str) and value.strip():
            values.append(value)
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped[:20]


def extract_structure_items(item: Any) -> list[Any]:
    item = dict_like_payload(item)
    if not isinstance(item, dict):
        return []
    if isinstance(item.get("res"), dict):
        nested = dict(item["res"])
        for key in ["type", "label", "bbox", "box", "coordinate", "pageNo", "page_no", "confidence", "score", "markdown"]:
            if key not in nested and key in item:
                nested[key] = item[key]
        item = nested
    extracted: list[Any] = []
    table_res_list = item.get("table_res_list")
    if isinstance(table_res_list, list):
        extracted.extend(table_res_list)
    layout = item.get("layout_det_res")
    layout = dict_like_payload(layout)
    if isinstance(layout, dict) and isinstance(layout.get("boxes"), list):
        extracted.extend(layout["boxes"])
    if extracted:
        return extracted
    if any(key in item for key in ["type", "label", "bbox", "box", "coordinate", "html", "res"]):
        return [item]
    return []


class TableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self._current_row: list[dict[str, Any]] | None = None
        self._current_cell: dict[str, Any] | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._current_row = []
            return
        if tag not in {"td", "th"} or self._current_row is None:
            return
        attr_map = {key.lower(): value for key, value in attrs}
        self._current_cell = {
            "rowspan": positive_int(attr_map.get("rowspan"), 1),
            "colspan": positive_int(attr_map.get("colspan"), 1),
            "isHeader": tag == "th",
        }
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            cell = self._current_cell
            cell["text"] = normalize_cell_text("".join(self._text_parts))
            self._current_row.append(cell)
            self._current_cell = None
            self._text_parts = []
            return
        if tag == "tr" and self._current_row is not None:
            if any(str(cell.get("text") or "").strip() for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None


def html_table_to_structure(html: str) -> dict[str, Any]:
    if not html.strip():
        return {"rows": 0, "columns": 0, "cells": [], "normalizedRows": []}
    parser = TableHtmlParser()
    try:
        parser.feed(html)
    except Exception:
        return {"rows": 0, "columns": 0, "cells": [], "normalizedRows": []}
    occupied: set[tuple[int, int]] = set()
    cells: list[dict[str, Any]] = []
    max_row = 0
    max_col = 0
    for row_index, row in enumerate(parser.rows):
        col_index = 0
        for raw_cell in row:
            while (row_index, col_index) in occupied:
                col_index += 1
            rowspan = int(raw_cell.get("rowspan") or 1)
            colspan = int(raw_cell.get("colspan") or 1)
            for row_offset in range(rowspan):
                for col_offset in range(colspan):
                    occupied.add((row_index + row_offset, col_index + col_offset))
            cells.append(
                {
                    "cellId": f"cell_{len(cells) + 1}",
                    "row": row_index,
                    "col": col_index,
                    "rowspan": rowspan,
                    "colspan": colspan,
                    "text": str(raw_cell.get("text") or ""),
                    "bbox": None,
                    "confidence": 0.8,
                    "isHeader": bool(raw_cell.get("isHeader") or row_index == 0),
                }
            )
            max_row = max(max_row, row_index + rowspan)
            max_col = max(max_col, col_index + colspan)
            col_index += colspan
    return {
        "rows": max(max_row, len(parser.rows)),
        "columns": max_col,
        "cells": cells,
        "normalizedRows": normalized_rows_from_cells(cells),
    }


def normalized_rows_from_cells(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not cells:
        return []
    rows = sorted({int(cell.get("row") or 0) for cell in cells})
    header_rows: list[int] = []
    for row_no in rows:
        row_cells = [cell for cell in cells if int(cell.get("row") or 0) == row_no]
        if row_cells and all(cell.get("isHeader") for cell in row_cells):
            header_rows.append(row_no)
            continue
        break
    if not header_rows:
        header_rows = [rows[0]]
    last_header_row = max(header_rows)
    header_by_col: dict[int, str] = {}
    for header_row in header_rows:
        for cell in sorted((item for item in cells if int(item.get("row") or 0) == header_row), key=lambda item: int(item.get("col") or 0)):
            text = normalize_header_text(str(cell.get("text") or ""))
            if not text:
                continue
            col = int(cell.get("col") or 0)
            colspan = int(cell.get("colspan") or 1)
            for offset in range(colspan):
                header_by_col[col + offset] = text
    normalized = []
    for row_no in sorted({int(cell.get("row") or 0) for cell in cells if int(cell.get("row") or 0) > last_header_row}):
        row: dict[str, str] = {}
        for cell in sorted((item for item in cells if int(item.get("row") or 0) == row_no), key=lambda item: int(item.get("col") or 0)):
            value = normalize_cell_text(str(cell.get("text") or ""))
            if not value:
                continue
            key = header_by_col.get(int(cell.get("col") or 0)) or f"col_{int(cell.get('col') or 0) + 1}"
            if key in row and row[key]:
                key = f"{key}_{int(cell.get('col') or 0) + 1}"
            row[key] = value
        if row:
            normalized.append(row)
    return normalized


def positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 1)


def normalize_cell_text(value: str) -> str:
    return " ".join(unescape(value).split())


def normalize_header_text(value: str) -> str:
    return normalize_cell_text(value).strip(" ：:")


def normalize_seal_result(raw: Any) -> list[dict[str, Any]]:
    seals: list[dict[str, Any]] = []
    items = []
    for item in iterable_raw_items(raw):
        items.extend(extract_seal_items(item))
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        text = item.get("text") or item.get("sealName") or item.get("rec_text") or inferred_seal_text(item)
        bbox = item.get("bbox") or item.get("box") or bbox_from_coordinate(item.get("coordinate"))
        polygon = item.get("polygon") or item.get("dt_poly") or item.get("points")
        if not text and not bbox and not polygon:
            continue
        inferred_confidence = inferred_score(item)
        seals.append(
            {
                "sealId": f"seal_{index + 1}",
                "pageNo": int(item.get("pageNo") or item.get("page_no") or 1),
                "sealType": item.get("sealType") or "unknown",
                "sealName": str(text),
                "bbox": bbox,
                "polygon": polygon,
                "visualConfidence": first_numeric(
                    item,
                    "visualConfidence",
                    "det_score",
                    "score",
                    default=float(inferred_confidence or 0.0),
                ),
                "ocrConfidence": first_numeric(
                    item,
                    "ocrConfidence",
                    "rec_score",
                    "score",
                    default=float(inferred_ocr_score(item) or inferred_confidence or 0.0),
                ),
                "fields": item.get("fields") or [],
                "qualityFlags": item.get("qualityFlags") or [],
            }
        )
    return seals


def iterable_raw_items(raw: Any) -> list[Any]:
    if isinstance(raw, (list, tuple)):
        return list(raw)
    if isinstance(raw, dict) or isinstance(raw, (str, bytes)) or raw is None:
        return [raw]
    if hasattr(raw, "__iter__"):
        try:
            return list(raw)
        except TypeError:
            return [raw]
    return [raw]


def extract_seal_items(item: Any) -> list[Any]:
    item = dict_like_payload(item)
    if not isinstance(item, dict):
        return []
    if isinstance(item.get("res"), dict):
        item = item["res"]
    seal_res_list = item.get("seal_res_list")
    if isinstance(seal_res_list, list):
        layout = dict_like_payload(item.get("layout_det_res"))
        layout_boxes = layout.get("boxes") if isinstance(layout, dict) else []
        seal_boxes = [
            box
            for raw_box in (layout_boxes if isinstance(layout_boxes, list) else [])
            if isinstance((box := dict_like_payload(raw_box)), dict)
            and str(box.get("label") or box.get("type") or "").lower() == "seal"
        ]
        extracted: list[Any] = []
        for index, child in enumerate(seal_res_list):
            child = dict_like_payload(child)
            if isinstance(child, dict) and index < len(seal_boxes):
                child = dict(child)
                layout_box = seal_boxes[index]
                if not any(child.get(key) is not None for key in ["bbox", "box", "coordinate"]):
                    child["coordinate"] = layout_box.get("coordinate") or layout_box.get("bbox") or layout_box.get("box")
                if not any(child.get(key) is not None for key in ["det_score", "score", "visualConfidence"]):
                    child["det_score"] = layout_box.get("score") or layout_box.get("confidence")
            extracted.extend(extract_seal_items(child))
        return extracted
    if any(
        key in item
        for key in [
            "sealName", "text", "rec_text", "rec_texts", "bbox", "box", "coordinate",
            "polygon", "dt_poly", "dt_polys", "rec_polys", "points",
        ]
    ):
        return [item]
    for key in ["seal_rec_res", "ocr_res", "rec_res", "det_res"]:
        if isinstance(item.get(key), dict):
            nested = extract_seal_items(item[key])
            if nested:
                return nested
    return []


def dict_like_payload(value: Any) -> Any:
    json_payload = getattr(value, "json", None)
    if isinstance(json_payload, dict):
        return json_payload
    if callable(json_payload):
        try:
            payload = json_payload()
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    if isinstance(value, dict):
        return value
    if hasattr(value, "items"):
        try:
            return dict(value.items())
        except Exception:
            return value
    return value


def inferred_seal_text(item: dict[str, Any]) -> str:
    values = recursive_values_for_keys(item, {"rec_text", "rec_texts", "text", "texts"})
    flattened: list[str] = []
    for value in values:
        if isinstance(value, str) and value.strip():
            flattened.append(value.strip())
        elif isinstance(value, list):
            flattened.extend(str(part).strip() for part in value if str(part).strip())
    return " ".join(flattened[:8])


def inferred_score(item: dict[str, Any]) -> float | None:
    values = recursive_values_for_keys(item, {"score", "scores", "rec_score", "rec_scores", "det_score", "det_scores"})
    numeric: list[float] = []
    for value in values:
        if isinstance(value, (int, float)):
            numeric.append(float(value))
        elif isinstance(value, list):
            for part in value:
                if isinstance(part, (int, float)):
                    numeric.append(float(part))
    if not numeric:
        return None
    return max(0.0, min(1.0, sum(numeric) / len(numeric)))


def inferred_ocr_score(item: dict[str, Any]) -> float | None:
    values = recursive_values_for_keys(item, {"rec_score", "rec_scores"})
    numeric: list[float] = []
    for value in values:
        if isinstance(value, (int, float)):
            numeric.append(float(value))
        elif isinstance(value, list):
            for part in value:
                if isinstance(part, (int, float)):
                    numeric.append(float(part))
    if not numeric:
        return None
    return max(0.0, min(1.0, sum(numeric) / len(numeric)))


def recursive_values_for_keys(value: Any, target_keys: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in target_keys:
                found.append(child)
            found.extend(recursive_values_for_keys(child, target_keys))
    elif isinstance(value, list):
        for child in value:
            found.extend(recursive_values_for_keys(child, target_keys))
    return found


def bbox_from_coordinate(value: Any) -> list[float] | None:
    if isinstance(value, list) and len(value) >= 4 and all(isinstance(item, (int, float)) for item in value[:4]):
        return [float(item) for item in value[:4]]
    return None


def normalize_agentdesign_seal_result(raw: Any) -> list[dict[str, Any]]:
    seals: list[dict[str, Any]] = []
    raw_seals = raw.get("seals") if isinstance(raw, dict) else []
    for index, item in enumerate(raw_seals if isinstance(raw_seals, list) else [], start=1):
        if not isinstance(item, dict):
            continue
        fields = normalize_agentdesign_seal_fields(item.get("fields") or {})
        seal_name = agentdesign_seal_name(fields)
        confidence = agentdesign_seal_confidence(fields)
        decision = str(item.get("decision") or "").upper()
        quality_flags = ["agentdesign_seal_ocr"]
        if decision and decision != "AUTO_PASS":
            quality_flags.append("review_required")
        candidate = ((item.get("audit_trace") or {}).get("candidate") or {}) if isinstance(item.get("audit_trace"), dict) else {}
        seal_type = agentdesign_seal_type(fields, candidate)
        polygon = item.get("polygon") or []
        bbox = bbox_from_polygon(polygon)
        seals.append(
            {
                "sealId": str(item.get("seal_result_id") or f"agentdesign_seal_{index}"),
                "pageNo": normalize_page_no(item, fallback=1),
                "sealType": seal_type,
                "sealName": seal_name,
                "bbox": bbox,
                "polygon": polygon,
                "visualConfidence": confidence,
                "ocrConfidence": confidence,
                "fields": fields,
                "qualityFlags": quality_flags,
                "decision": decision or None,
                "decisionReason": item.get("decision_reason") or [],
                "sealInstanceId": item.get("seal_instance_id"),
            }
        )
    return seals


def normalize_page_no(item: dict[str, Any], *, fallback: int = 1) -> int:
    try:
        if item.get("pageNo") is not None:
            return int(item["pageNo"])
        if item.get("page_no") is not None:
            return int(item["page_no"])
        if item.get("page_index") is not None:
            return int(item["page_index"]) + 1
    except (TypeError, ValueError):
        return fallback
    return fallback


def normalize_agentdesign_seal_fields(raw_fields: Any) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    if not isinstance(raw_fields, dict):
        return fields
    for field_code, raw in raw_fields.items():
        if not isinstance(raw, dict) or raw.get("value") in (None, ""):
            continue
        confidence = raw.get("calibrated_confidence") or raw.get("visual_confidence") or 0.0
        fields.append(
            {
                "fieldName": str(field_code),
                "fieldCode": str(field_code),
                "fieldValue": str(raw.get("value")),
                "confidence": float(confidence or 0.0),
                "source": raw.get("source"),
                "alternatives": raw.get("alternatives") or [],
                "conflicts": raw.get("conflicts") or [],
            }
        )
    return fields


def agentdesign_seal_name(fields: list[dict[str, Any]]) -> str:
    values = {str(field.get("fieldCode")): str(field.get("fieldValue") or "") for field in fields}
    parts = [
        values.get("organization_name") or values.get("issuer_or_seal_name") or "",
        values.get("seal_type") or "",
        values.get("license_scope") or "",
    ]
    return " ".join(part for part in parts if part).strip()


def agentdesign_seal_confidence(fields: list[dict[str, Any]]) -> float:
    confidences = [float(field.get("confidence") or 0.0) for field in fields if field.get("confidence") is not None]
    return round(sum(confidences) / len(confidences), 4) if confidences else 0.0


def agentdesign_seal_type(fields: list[dict[str, Any]], candidate: dict[str, Any]) -> str:
    values = {str(field.get("fieldCode")): str(field.get("fieldValue") or "") for field in fields}
    seal_type = values.get("seal_type") or ""
    candidate_type = str(candidate.get("candidate_type") or "")
    if "特种设备设计许可" in seal_type:
        return "special_equipment_design_permit_seal"
    if "出图" in seal_type:
        return "drawing_approval_seal"
    if "检验" in seal_type:
        return "inspection_testing_seal"
    if candidate_type:
        return candidate_type
    return "agentdesign_seal"


def bbox_from_polygon(polygon: Any) -> list[float] | None:
    if not isinstance(polygon, list) or not polygon:
        return None
    points = []
    for point in polygon:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                points.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
    if not points:
        return None
    return [min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points), max(y for _, y in points)]


def normalize_agentdesign_diagnostics(raw_diagnostics: Any) -> list[dict[str, Any]]:
    diagnostics = []
    for item in raw_diagnostics if isinstance(raw_diagnostics, list) else []:
        if isinstance(item, dict):
            diagnostics.append(
                {
                    "code": str(item.get("code") or "AGENTDESIGN_SEAL_DIAGNOSTIC"),
                    "level": str(item.get("level") or "info"),
                    "message": str(item.get("message") or item),
                }
            )
    return diagnostics
