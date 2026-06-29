from __future__ import annotations

import importlib.util
import json
import os
import select
import subprocess
import textwrap
import threading
import time
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from uuid import uuid4


def env_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default))


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


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

        source_path = variant_source_path(source_path, variant)
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
    required_package = "paddleocr"

    def available(self) -> bool:
        return super().available() and paddle_text_model_dirs_available()

    def status(self) -> dict[str, Any]:
        det_dir = model_dir("AICHECK_PADDLEOCR_DET_MODEL_DIR", "PP-OCRv6_medium_det")
        rec_dir = model_dir("AICHECK_PADDLEOCR_REC_MODEL_DIR", "PP-OCRv6_medium_rec")
        return {
            "engine": self.name,
            "version": self.version,
            "available": self.available(),
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
        ocr = PaddleOCR(
            text_detection_model_dir=det_dir,
            text_recognition_model_dir=rec_dir,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
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
        return super().available() and all(path.exists() for path in pp_structure_model_dirs().values())

    def status(self) -> dict[str, Any]:
        dirs = pp_structure_model_dirs()
        return {
            "engine": self.name,
            "version": self.version,
            "available": self.available(),
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
        from paddleocr import PPStructureV3  # type: ignore

        source_path = variant_source_path(source_path, variant)
        dirs = pp_structure_model_dirs()
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
        engine = PPStructureV3(
            layout_detection_model_dir=str(dirs["layout"]),
            text_detection_model_dir=str(dirs["text_det"]),
            text_recognition_model_dir=str(dirs["text_rec"]),
            wired_table_structure_recognition_model_dir=str(dirs["wired_table_structure"]),
            wired_table_cells_detection_model_dir=str(dirs["wired_table_cells"]),
            wireless_table_structure_recognition_model_dir=str(dirs["wireless_table_structure"]),
            wireless_table_cells_detection_model_dir=str(dirs["wireless_table_cells"]),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            use_table_recognition=True,
            use_seal_recognition=False,
            use_formula_recognition=False,
            use_chart_recognition=False,
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
        script = textwrap.dedent(
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
            completed = subprocess.run(
                [python_bin, "-c", script, str(source_path), os.getenv("AICHECK_OPENCV_TABLE_GRID_MAX_CELLS", "1800")],
                check=False,
                capture_output=True,
                encoding="utf-8",
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
        if env_bool("AICHECK_OCR_ENABLE_PERSISTENT_SUBPROCESS", False):
            try:
                return self.parse_with_persistent_worker(Path(python_bin), source_path, det_dir, rec_dir)
            except Exception:
                self.reset_worker()
                # Fall through to the one-shot subprocess path. The caller still receives a normal engine result.
        script = textwrap.dedent(
            """
            import json
            import sys
            from paddleocr import PaddleOCR

            image_path, det_dir, rec_dir = sys.argv[1:4]
            ocr = PaddleOCR(
                text_detection_model_dir=det_dir,
                text_recognition_model_dir=rec_dir,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                text_det_limit_side_len=2400,
                text_det_limit_type="max",
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
                            "confidence": float(scores[index]) if index < len(scores) else 0.8,
                            "sourceEngine": "paddle_ocr_subprocess",
                        }
                    )
            print(json.dumps({"ok": bool(fragments), "fragments": fragments, "text": "\\n".join(item["text"] for item in fragments)}, ensure_ascii=False))
            """
        )
        env = ocr_subprocess_env()
        timeout = float(os.getenv("AICHECK_OCR_SUBPROCESS_TIMEOUT", "180"))
        completed = subprocess.run(
            [python_bin, "-c", script, str(source_path), str(det_dir), str(rec_dir)],
            check=False,
            capture_output=True,
            encoding="utf-8",
            env=env,
            timeout=timeout,
        )
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
    ) -> dict[str, Any]:
        with self._worker_lock:
            worker = self.ensure_worker(python_bin, det_dir, rec_dir)
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

    def ensure_worker(self, python_bin: Path, det_dir: Path, rec_dir: Path) -> subprocess.Popen[str]:
        if self._worker is not None and self._worker.poll() is None:
            return self._worker
        self.reset_worker()
        self._worker = subprocess.Popen(
            [str(python_bin), "-u", "-c", paddle_ocr_worker_script(), str(det_dir), str(rec_dir)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            env=ocr_subprocess_env(),
            bufsize=1,
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
        if worker is None:
            return
        if worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=3)
            except subprocess.TimeoutExpired:
                worker.kill()


def paddle_ocr_worker_script() -> str:
    return textwrap.dedent(
        """
        import json
        import sys
        from paddleocr import PaddleOCR

        det_dir, rec_dir = sys.argv[1:3]
        ocr = PaddleOCR(
            text_detection_model_dir=det_dir,
            text_recognition_model_dir=rec_dir,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_det_limit_side_len=2400,
            text_det_limit_type="max",
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
                            "confidence": float(scores[index]) if index < len(scores) else 0.8,
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


def ocr_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
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
        enabled = os.getenv("AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE", "false").lower() in {"1", "true", "yes", "on"}
        return enabled and super().available() and all(path.exists() for path in seal_model_dirs().values())

    def status(self) -> dict[str, Any]:
        dirs = seal_model_dirs()
        return {
            "engine": self.name,
            "version": self.version,
            "available": self.available(),
            "enabled": os.getenv("AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE", "false"),
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
        from paddlex import create_pipeline  # type: ignore

        source_path = variant_source_path(source_path, variant)
        missing = [key for key, path in seal_model_dirs().items() if not path.exists()]
        if missing:
            return {
                "ok": False,
                "diagnostics": [{"code": "SEAL_MODEL_MISSING", "level": "warning", "message": f"Seal local model directories are missing: {', '.join(missing)}."}],
                "engine": self.name,
                "engineVersion": self.version,
            }
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
            "max_pages": int(os.getenv("AICHECK_AGENTDESIGN_SEAL_MAX_PAGES", "1")),
            "max_candidates_per_page": int(os.getenv("AICHECK_AGENTDESIGN_SEAL_MAX_CANDIDATES", "6")),
            "max_ocr_candidates_per_page": int(os.getenv("AICHECK_AGENTDESIGN_SEAL_MAX_OCR_CANDIDATES", "3")),
            "production_document_timeout_seconds": float(os.getenv("AICHECK_AGENTDESIGN_SEAL_DOCUMENT_TIMEOUT", "120")),
            "production_candidate_timeout_seconds": float(os.getenv("AICHECK_AGENTDESIGN_SEAL_CANDIDATE_TIMEOUT", "35")),
            "enable_vl": False,
            "enable_page_subject_extraction": env_bool("AICHECK_AGENTDESIGN_SEAL_PAGE_SUBJECT", False),
            "enable_ppocr5": env_bool("AICHECK_AGENTDESIGN_SEAL_ENABLE_PPOCR5", False),
            "debug_arc_artifacts": False,
        }
        script = textwrap.dedent(
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
            completed = subprocess.run(
                [python_bin, "-c", script, str(source_path), str(backend_path), json.dumps(config)],
                check=False,
                capture_output=True,
                encoding="utf-8",
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
    version = "opencv-color-candidate@1"

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
        script = textwrap.dedent(
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
                    "mask": cv2.inRange(hsv, np.array([85, 35, 35]), np.array([140, 255, 255])),
                    "kernel": 13,
                    "aspect": (0.45, 3.2),
                    "max_area_ratio": 0.05,
                    "max_bbox_ratio": 0.05,
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

            seals = []
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
                    if w < 40 or h < 25 or touches_border(x, y, w, h):
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
                    if len(selected) >= 4:
                        break
                for index, (area, x, y, w, h, fill_ratio) in enumerate(selected, start=1):
                    seal_type = "visual_red_seal_candidate" if color == "red" else "visual_blue_stamp_candidate"
                    confidence = min(0.95, 0.55 + area / float(width * height) * 50 + min(fill_ratio, 0.45) * 0.2)
                    seals.append(
                        {
                            "sealId": f"{color}_candidate_{index}",
                            "pageNo": 1,
                            "sealType": seal_type,
                            "sealName": "视觉印章候选" if color == "red" else "视觉蓝章候选",
                            "bbox": [int(x), int(y), int(x + w), int(y + h)],
                            "polygon": [[int(x), int(y)], [int(x + w), int(y)], [int(x + w), int(y + h)], [int(x), int(y + h)]],
                            "pageWidth": int(width),
                            "pageHeight": int(height),
                            "visualColor": color,
                            "visualConfidence": round(confidence, 4),
                            "ocrConfidence": 0.0,
                            "fields": [{"fieldName": "印章颜色", "fieldValue": color, "confidence": 0.8, "bbox": [int(x), int(y), int(x + w), int(y + h)]}],
                            "qualityFlags": ["visual_candidate_only", "requires_seal_ocr_text"],
                        }
                    )
            print(json.dumps({"ok": bool(seals), "seals": seals, "diagnostics": []}, ensure_ascii=False))
            """
        )
        env = os.environ.copy()
        env.update({"PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        completed = subprocess.run(
            [python_bin, "-c", script, str(source_path)],
            check=False,
            capture_output=True,
            encoding="utf-8",
            env=env,
            timeout=float(os.getenv("AICHECK_OCR_VISUAL_SEAL_TIMEOUT", "60")),
        )
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
    required_env = "PADDLEOCR_VL_MODEL_DIR"
    required_package = "paddleocr"

    def parse(
        self,
        source_path: Path,
        *,
        file_name: str | None = None,
        profile: dict[str, Any] | None = None,
        variant: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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

    def parse(
        self,
        source_path: Path,
        *,
        file_name: str | None = None,
        profile: dict[str, Any] | None = None,
        variant: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from docling.document_converter import DocumentConverter  # type: ignore

        source_path = variant_source_path(source_path, variant)
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
        PaddleOcrSubprocessEngine(),
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


def model_dir(env_name: str, model_name: str, *, root_envs: tuple[str, ...] = ("AICHECK_PADDLEX_MODEL_CACHE", "PADDLEOCR_MODEL_DIR", "PADDLEX_MODEL_DIR")) -> Path:
    if os.getenv(env_name):
        return Path(os.environ[env_name])
    candidates: list[Path] = []
    for root_env in root_envs:
        if not os.getenv(root_env):
            continue
        root = Path(os.environ[root_env])
        candidates.extend([root if root.name == model_name else root / model_name, root / "official_models" / model_name])
    candidates.append(Path("/models") / model_name)
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


def seal_model_dirs() -> dict[str, Path]:
    return {
        "seal_det": model_dir("AICHECK_SEAL_DET_MODEL_DIR", "PP-OCRv4_server_seal_det"),
        "seal_rec": model_dir("AICHECK_SEAL_REC_MODEL_DIR", "PP-OCRv4_server_rec"),
    }


def agentdesign_backend_path() -> Path:
    return Path(os.getenv("AICHECK_AGENTDESIGN_BACKEND", "/Volumes/Volume/project/agentdesign/mvp-system/backend"))


def subprocess_model_dir(env_name: str, model_name: str) -> Path:
    return model_dir(env_name, model_name)


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
            html = item.get("html") or res_html
            table_structure = html_table_to_structure(str(html or ""))
            tables.append(
                {
                    "tableId": f"table_{len(tables) + 1}",
                    "pageNo": int(item.get("pageNo") or item.get("page_no") or 1),
                    "bbox": bbox,
                    "rows": table_structure["rows"],
                    "columns": table_structure["columns"],
                    "cells": table_structure["cells"],
                    "html": html,
                    "markdown": item.get("markdown"),
                    "normalizedRows": table_structure["normalizedRows"],
                    "structureConfidence": item.get("confidence") or item.get("score") or 0.8,
                    "sourceEngine": source_engine,
                }
            )
    return tables, blocks


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
                "pageNo": int(item.get("page_index") or 1),
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
