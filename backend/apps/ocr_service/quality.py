from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path
from typing import Any

from apps.ocr_service.pages import render_document_pages
from apps.ocr_service.utils import parse_bool


def probe_page_quality(
    source_path: Path,
    *,
    profile: dict[str, Any] | None = None,
    pages: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    pages = pages if pages is not None else render_document_pages(source_path, profile=profile)
    qualities = []
    for page in pages:
        page_path = Path(str(page.get("path") or source_path))
        quality = probe_image_quality(page_path, profile=profile, page=page)
        qualities.append(quality)
    return qualities or [unreadable_quality(source_path, profile=profile, page_no=1)]


def probe_image_quality(
    source_path: Path,
    *,
    profile: dict[str, Any] | None = None,
    page: dict[str, Any] | None = None,
) -> dict[str, Any]:
    page_no = int((page or {}).get("pageNo") or 1)
    image = load_image(source_path)
    if image is None:
        subprocess_quality = probe_page_quality_subprocess(source_path)
        if subprocess_quality is not None:
            quality = subprocess_quality[0].setdefault("quality", {})
            subprocess_quality[0]["pageNo"] = page_no
            apply_business_need_flags(quality, profile)
            return subprocess_quality[0]
        return unreadable_quality(source_path, profile=profile, page_no=page_no, page=page)
    cv2, np, raw = image
    height, width = raw.shape[:2]
    gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean()) / 255.0
    contrast = float(gray.std()) / 128.0
    background = cv2.blur(gray, (51, 51))
    background_unevenness = float(background.std()) / 128.0
    noise_score = float(abs(gray.astype("float32") - cv2.medianBlur(gray, 3).astype("float32")).mean()) / 32.0
    edge_density = float((cv2.Canny(gray, 80, 160) > 0).mean())
    color_presence = estimate_color_presence(cv2, raw)
    line_clues = table_clue_metrics(cv2, np, gray)
    table_clue_score = max(edge_density * 22.0, line_clues["gridRegularityScore"])
    has_table_candidate = table_clue_score >= 0.38
    has_seal_candidate = color_presence["red"] > 0.0005 or color_presence["blue"] > 0.0008
    skew_angle = estimate_skew_angle(cv2, np, gray)
    is_low_quality = blur_score < 90 or contrast < 0.18 or background_unevenness > 0.35 or abs(skew_angle) > 1.0
    return [
        {
            "pageNo": page_no,
            "quality": {
                "sourceType": (page or {}).get("sourceType") or source_path.suffix.lower().lstrip(".") or "image",
                "isImageReadable": True,
                "width": int(width),
                "height": int(height),
                "estimatedDpi": (page or {}).get("renderDpi") or estimate_dpi(width, height),
                "blurScore": round(blur_score, 4),
                "skewAngle": round(skew_angle, 4),
                "orientation": int((page or {}).get("rotation") or 0),
                "brightness": round(brightness, 4),
                "contrast": round(contrast, 4),
                "backgroundUnevenness": round(background_unevenness, 4),
                "noiseScore": round(noise_score, 4),
                "edgeDensity": round(edge_density, 6),
                "colorPresence": color_presence,
                "hasLargeDarkBorder": has_large_dark_border(gray),
                "requiresTableExtraction": bool((profile or {}).get("requiredTables")),
                "hasVisualTableCandidate": has_table_candidate,
                "hasTableCandidate": has_table_candidate,
                "tableClueScore": round(min(table_clue_score, 1.0), 4),
                **line_clues,
                "requiresSealSearch": parse_bool(((profile or {}).get("sealRules") or {}).get("required"), False) is True,
                "hasVisualSealCandidate": has_seal_candidate,
                "hasSealCandidate": has_seal_candidate,
                "isLowQuality": is_low_quality,
            },
        }
    ][0]


def unreadable_quality(
    source_path: Path,
    *,
    profile: dict[str, Any] | None,
    page_no: int,
    page: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "pageNo": page_no,
        "quality": {
            "sourceType": (page or {}).get("sourceType") or source_path.suffix.lower().lstrip(".") or "unknown",
            "isImageReadable": False,
            "isLowQuality": False,
            "requiresTableExtraction": bool((profile or {}).get("requiredTables")),
            "hasVisualTableCandidate": False,
            "hasTableCandidate": False,
            "tableClueScore": 0.0,
            "requiresSealSearch": parse_bool(((profile or {}).get("sealRules") or {}).get("required"), False) is True,
            "hasVisualSealCandidate": False,
            "hasSealCandidate": False,
        },
    }


def apply_business_need_flags(quality: dict[str, Any], profile: dict[str, Any] | None) -> None:
    quality["requiresTableExtraction"] = bool((profile or {}).get("requiredTables"))
    quality["hasVisualTableCandidate"] = bool(quality.get("hasTableCandidate"))
    quality["tableClueScore"] = float(quality.get("tableClueScore") or quality.get("edgeDensity") or 0.0)
    quality["requiresSealSearch"] = parse_bool(((profile or {}).get("sealRules") or {}).get("required"), False) is True
    quality["hasVisualSealCandidate"] = bool(quality.get("hasSealCandidate"))


def table_clue_metrics(cv2: Any, np: Any, gray: Any) -> dict[str, Any]:
    try:
        binary = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_MEAN_C,
            cv2.THRESH_BINARY_INV,
            35,
            9,
        )
        width = gray.shape[1]
        height = gray.shape[0]
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(width // 80, 12), 1))
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(height // 80, 12)))
        horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
        vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)
        intersections = cv2.bitwise_and(horizontal, vertical)
        pixel_count = max(float(width * height), 1.0)
        horizontal_density = float((horizontal > 0).sum()) / pixel_count
        vertical_density = float((vertical > 0).sum()) / pixel_count
        intersection_count = int((intersections > 0).sum())
        grid_score = min(horizontal_density * 18.0 + vertical_density * 18.0 + min(intersection_count / 900.0, 0.35), 1.0)
        return {
            "horizontalLineDensity": round(horizontal_density, 6),
            "verticalLineDensity": round(vertical_density, 6),
            "lineIntersectionCount": intersection_count,
            "gridRegularityScore": round(grid_score, 4),
        }
    except Exception:
        return {
            "horizontalLineDensity": 0.0,
            "verticalLineDensity": 0.0,
            "lineIntersectionCount": 0,
            "gridRegularityScore": 0.0,
        }


def probe_page_quality_subprocess(source_path: Path) -> list[dict[str, Any]] | None:
    python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
    if not python_bin or not Path(python_bin).exists():
        return None
    script = textwrap.dedent(
        """
        import json
        import sys
        import cv2
        import numpy as np

        image = cv2.imread(sys.argv[1])
        if image is None:
            print(json.dumps(None))
            raise SystemExit(0)
        height, width = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean()) / 255.0
        contrast = float(gray.std()) / 128.0
        background = cv2.blur(gray, (51, 51))
        background_unevenness = float(background.std()) / 128.0
        noise_score = float(abs(gray.astype("float32") - cv2.medianBlur(gray, 3).astype("float32")).mean()) / 32.0
        edge_density = float((cv2.Canny(gray, 80, 160) > 0).mean())
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        red = cv2.inRange(hsv, (0, 15, 35), (15, 255, 255)) | cv2.inRange(hsv, (160, 15, 35), (180, 255, 255))
        blue = cv2.inRange(hsv, (85, 35, 35), (140, 255, 255))
        pixel_count = max(float(height * width), 1.0)
        color_presence = {"red": round(float((red > 0).sum()) / pixel_count, 6), "blue": round(float((blue > 0).sum()) / pixel_count, 6)}
        payload = [{
            "pageNo": 1,
            "quality": {
                "sourceType": "image",
                "isImageReadable": True,
                "width": int(width),
                "height": int(height),
                "estimatedDpi": 300 if max(width, height) >= 3200 else 220 if max(width, height) >= 2400 else 150 if max(width, height) >= 1600 else None,
                "blurScore": round(blur_score, 4),
                "skewAngle": 0.0,
                "orientation": 0,
                "brightness": round(brightness, 4),
                "contrast": round(contrast, 4),
                "backgroundUnevenness": round(background_unevenness, 4),
                "noiseScore": round(noise_score, 4),
                "edgeDensity": round(edge_density, 6),
                "colorPresence": color_presence,
                "hasLargeDarkBorder": False,
                "hasTableCandidate": edge_density > 0.015,
                "hasSealCandidate": color_presence["red"] > 0.0005 or color_presence["blue"] > 0.0008,
                "isLowQuality": blur_score < 90 or contrast < 0.18 or background_unevenness > 0.35,
            },
        }]
        print(json.dumps(payload, ensure_ascii=False))
        """
    )
    completed = subprocess.run(
        [python_bin, "-c", script, str(source_path)],
        check=False,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    )
    if completed.returncode != 0:
        return None
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, list) else None


def load_image(source_path: Path):
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return None
    image = cv2.imread(str(source_path))
    if image is None:
        return None
    return cv2, np, image


def estimate_color_presence(cv2: Any, image: Any) -> dict[str, float]:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, (0, 15, 35), (15, 255, 255)) | cv2.inRange(hsv, (160, 15, 35), (180, 255, 255))
    blue = cv2.inRange(hsv, (85, 35, 35), (140, 255, 255))
    pixel_count = max(float(image.shape[0] * image.shape[1]), 1.0)
    return {
        "red": round(float((red > 0).sum()) / pixel_count, 6),
        "blue": round(float((blue > 0).sum()) / pixel_count, 6),
    }


def estimate_skew_angle(cv2: Any, np: Any, gray: Any) -> float:
    try:
        edges = cv2.Canny(gray, 80, 160)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=120, minLineLength=max(gray.shape[1] // 5, 80), maxLineGap=20)
        if lines is None:
            return 0.0
        angles = []
        for line in lines[:80]:
            x1, y1, x2, y2 = line[0]
            angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
            if -15 <= angle <= 15:
                angles.append(angle)
        if not angles:
            return 0.0
        return float(np.median(angles))
    except Exception:
        return 0.0


def has_large_dark_border(gray: Any) -> bool:
    height, width = gray.shape[:2]
    border = max(8, min(height, width) // 80)
    strips = [
        gray[:border, :],
        gray[-border:, :],
        gray[:, :border],
        gray[:, -border:],
    ]
    return any(float(strip.mean()) < 45 for strip in strips)


def estimate_dpi(width: int, height: int) -> int | None:
    long_side = max(width, height)
    if long_side >= 3200:
        return 300
    if long_side >= 2400:
        return 220
    if long_side >= 1600:
        return 150
    return None
