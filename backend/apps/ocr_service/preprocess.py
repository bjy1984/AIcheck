from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import textwrap
from copy import deepcopy
from pathlib import Path
from typing import Any

from apps.ocr_service.pages import render_document_pages
from apps.ocr_service.result_cache import (
    EVIDENCE_CONTRACT_VERSION,
    PAGE_SELECTION_VERSION,
    REMEDIATION_VERSION,
)

PREPROCESS_CACHE_SCHEMA = "aicheck-ocr-preprocess-cache-v2"


def generate_image_variants(
    source_path: Path,
    *,
    profile: dict[str, Any],
    page_quality: list[dict[str, Any]],
    pages: list[dict[str, Any]] | None = None,
    options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    requested = requested_variant_names(profile, page_quality, options=options)
    quality_by_page = {
        int(item.get("pageNo") or 1): (item.get("quality") if isinstance(item.get("quality"), dict) else {})
        for item in page_quality
        if isinstance(item, dict)
    }
    pages = pages if pages is not None else render_document_pages(source_path, profile=profile)
    variants = [build_original_variant(Path(str(page.get("path") or source_path)), page=page) for page in pages]
    cache_dir = variant_cache_dir(source_path, profile, requested, options=options)
    cached_variants = load_cached_variants(cache_dir)
    if cached_variants is not None:
        return [*variants, *cached_variants]

    generated: list[dict[str, Any]] = []
    out_dir = cache_dir or Path(tempfile.mkdtemp(prefix="aicheck-ocr-variants-"))
    out_dir.mkdir(parents=True, exist_ok=True)
    for page in pages:
        page_no = int(page.get("pageNo") or 1)
        page_path = Path(str(page.get("path") or source_path))
        quality = quality_by_page.get(page_no) or {}
        image = load_image(page_path)
        if image is None:
            generated.extend(
                generate_variants_subprocess(
                    page_path,
                    requested,
                    quality,
                    out_dir=out_dir,
                    page_no=page_no,
                    document_path=Path(str(page.get("documentPath") or source_path)),
                )
            )
            continue
        cv2, np, raw = image
        variant_builders = {
            "deskew": lambda: deskew_image(cv2, np, raw, float(quality.get("skewAngle") or 0.0)),
            "gray_clahe": lambda: gray_clahe_image(cv2, raw),
            "denoise_light": lambda: denoise_light_image(cv2, raw),
            "adaptive_threshold": lambda: adaptive_threshold_image(cv2, raw),
            "table_line_enhanced": lambda: table_line_enhanced_image(cv2, np, raw),
            "seal_color_mask": lambda: seal_color_mask_image(cv2, raw),
        }
        for name in requested:
            if name == "original" or name not in variant_builders:
                continue
            try:
                variant_image = variant_builders[name]()
            except Exception:
                continue
            if variant_image is None:
                continue
            target = out_dir / f"page-{page_no}-{name}.png"
            if not cv2.imwrite(str(target), variant_image):
                continue
            generated.append(
                {
                    "variantId": f"page_{page_no}_{name}",
                    "pageNo": page_no,
                    "path": str(target),
                    "documentPath": str(page.get("documentPath") or source_path),
                    "sourceType": page.get("sourceType"),
                    "coordinateSystem": page.get("coordinateSystem"),
                    "sourceCoordinateSystem": page.get("sourceCoordinateSystem"),
                    "renderScaleX": page.get("renderScaleX"),
                    "renderScaleY": page.get("renderScaleY"),
                    "preprocessChain": preprocess_chain_for(name),
                    "imageHash": file_hash(target),
                    "purpose": purpose_for_variant(name),
                    "source": "generated",
                    "coordinateTransformStatus": "unmapped" if name in {"deskew"} else "original",
                }
            )
    save_cached_variants(cache_dir, generated)
    return [*variants, *generated]


def requested_variant_names(
    profile: dict[str, Any],
    page_quality: list[dict[str, Any]],
    *,
    options: dict[str, Any] | None = None,
) -> list[str]:
    policy = profile.get("preprocessPolicy") or {}
    requested = list((options or {}).get("variants") or policy.get("variants") or ["original"])
    qualities = [(item.get("quality") if isinstance(item.get("quality"), dict) else {}) for item in page_quality]
    quality = merged_quality_flags(qualities)
    if quality.get("hasTableCandidate") and "table_line_enhanced" not in requested:
        requested.append("table_line_enhanced")
    if quality.get("hasSealCandidate") and "seal_color_mask" not in requested:
        requested.append("seal_color_mask")
    if quality.get("isLowQuality"):
        for name in ["deskew", "gray_clahe"]:
            if name not in requested:
                requested.append(name)
    return cap_requested_variants(requested, quality)


def merged_quality_flags(qualities: list[dict[str, Any]]) -> dict[str, Any]:
    if not qualities:
        return {}
    return {
        "hasTableCandidate": any(item.get("hasVisualTableCandidate") or item.get("hasTableCandidate") for item in qualities),
        "hasSealCandidate": any(item.get("hasVisualSealCandidate") or item.get("hasSealCandidate") for item in qualities),
        "isLowQuality": any(item.get("isLowQuality") for item in qualities),
        "skewAngle": max((abs(float(item.get("skewAngle") or 0.0)) for item in qualities), default=0.0),
    }


def generate_variants_subprocess(
    source_path: Path,
    requested: list[str],
    quality: dict[str, Any],
    *,
    out_dir: Path | None = None,
    page_no: int = 1,
    document_path: Path | None = None,
) -> list[dict[str, Any]]:
    python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
    if not python_bin or not Path(python_bin).exists():
        return []
    out_dir = out_dir or Path(tempfile.mkdtemp(prefix="aicheck-ocr-variants-"))
    out_dir.mkdir(parents=True, exist_ok=True)
    script = textwrap.dedent(
        """
        import json
        import sys
        from pathlib import Path
        import cv2
        import numpy as np

        source = Path(sys.argv[1])
        out_dir = Path(sys.argv[2])
        requested = json.loads(sys.argv[3])
        image = cv2.imread(str(source))
        if image is None:
            print(json.dumps([]))
            raise SystemExit(0)
        out_dir.mkdir(parents=True, exist_ok=True)

        def write(name, img):
            path = out_dir / f"{source.stem or 'page'}-{name}.png"
            ok = cv2.imwrite(str(path), img)
            return str(path) if ok else None

        outputs = []
        for name in requested:
            if name == "original":
                continue
            try:
                if name == "deskew":
                    img = image.copy()
                elif name == "gray_clahe":
                    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                    img = cv2.cvtColor(clahe.apply(gray), cv2.COLOR_GRAY2BGR)
                elif name == "denoise_light":
                    img = cv2.fastNlMeansDenoisingColored(image, None, 4, 4, 7, 21)
                elif name == "adaptive_threshold":
                    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
                    binary = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 11)
                    img = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
                elif name == "table_line_enhanced":
                    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 9)
                    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, image.shape[1] // 80), 1))
                    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(25, image.shape[0] // 80)))
                    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, hk, iterations=1)
                    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vk, iterations=1)
                    lines = cv2.add(horizontal, vertical)
                    closed = cv2.morphologyEx(lines, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
                    img = cv2.addWeighted(image, 0.75, cv2.cvtColor(closed, cv2.COLOR_GRAY2BGR), 0.25, 0)
                elif name == "seal_color_mask":
                    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
                    red = cv2.inRange(hsv, (0, 15, 35), (15, 255, 255)) | cv2.inRange(hsv, (160, 15, 35), (180, 255, 255))
                    blue = cv2.inRange(hsv, (85, 35, 35), (140, 255, 255))
                    mask = cv2.bitwise_or(red, blue)
                    kept = cv2.bitwise_and(image, image, mask=mask)
                    background = cv2.cvtColor(255 - mask, cv2.COLOR_GRAY2BGR)
                    img = cv2.addWeighted(kept, 1.0, background, 0.85, 0)
                else:
                    continue
                path = write(name, img)
                if path:
                    outputs.append({"name": name, "path": path})
            except Exception:
                continue
        print(json.dumps(outputs, ensure_ascii=False))
        """
    )
    completed = subprocess.run(
        [python_bin, "-c", script, str(source_path), str(out_dir), json.dumps(requested)],
        check=False,
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )
    if completed.returncode != 0:
        return []
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        return []
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return []
    variants = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict) or not item.get("path") or not item.get("name"):
            continue
        path = Path(str(item["path"]))
        if not path.exists():
            continue
        name = str(item["name"])
        variants.append(
            {
                "variantId": f"page_{page_no}_{name}",
                "pageNo": page_no,
                "path": str(path),
                "documentPath": str(document_path or source_path),
                "coordinateSystem": "rendered_pixels",
                "preprocessChain": preprocess_chain_for(name),
                "imageHash": file_hash(path),
                "purpose": purpose_for_variant(name),
                "source": "generated",
                "coordinateTransformStatus": "unmapped" if name in {"deskew"} else "original",
            }
        )
    return variants


def variant_cache_dir(
    source_path: Path,
    profile: dict[str, Any],
    requested: list[str],
    *,
    options: dict[str, Any] | None = None,
) -> Path | None:
    if bool((options or {}).get("disableVariantCache")) or os.getenv("AICHECK_OCR_DISABLE_VARIANT_CACHE") == "true":
        return None
    if not source_path.exists():
        return None
    base = Path(os.getenv("AICHECK_OCR_PREPROCESS_CACHE_DIR") or (Path(tempfile.gettempdir()) / "aicheck-ocr-preprocess-cache"))
    source_hash = file_hash(source_path)
    payload = {
        "schemaVersion": PREPROCESS_CACHE_SCHEMA,
        "evidenceContractVersion": EVIDENCE_CONTRACT_VERSION,
        "pageSelectionVersion": PAGE_SELECTION_VERSION,
        "remediationVersion": REMEDIATION_VERSION,
        "sourceHash": source_hash,
        "profileId": profile.get("profileId"),
        "preprocessPolicy": profile.get("preprocessPolicy") or {},
        "requested": requested,
    }
    key = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
    return base / key


def load_cached_variants(cache_dir: Path | None) -> list[dict[str, Any]] | None:
    if cache_dir is None:
        return None
    manifest_path = cache_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != PREPROCESS_CACHE_SCHEMA:
        return None
    variants = []
    for variant in manifest.get("variants") or []:
        if not isinstance(variant, dict) or not variant.get("path"):
            return None
        path = Path(str(variant["path"]))
        if not path.exists():
            return None
        output = deepcopy(variant)
        output["cacheHit"] = True
        variants.append(output)
    return variants or None


def save_cached_variants(cache_dir: Path | None, variants: list[dict[str, Any]]) -> None:
    if cache_dir is None:
        return
    cacheable = [
        {**deepcopy(variant), "cacheHit": False}
        for variant in variants
        if isinstance(variant, dict) and variant.get("path") and Path(str(variant["path"])).exists()
    ]
    if not cacheable:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": PREPROCESS_CACHE_SCHEMA,
        "evidenceContractVersion": EVIDENCE_CONTRACT_VERSION,
        "pageSelectionVersion": PAGE_SELECTION_VERSION,
        "remediationVersion": REMEDIATION_VERSION,
        "variants": cacheable,
    }
    try:
        (cache_dir / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def cap_requested_variants(requested: list[str], quality: dict[str, Any]) -> list[str]:
    deduped = []
    for name in requested:
        if name not in deduped:
            deduped.append(name)
    if "original" not in deduped:
        deduped.insert(0, "original")
    has_table = bool(quality.get("hasTableCandidate"))
    has_seal = bool(quality.get("hasSealCandidate"))
    limit = 5 if quality.get("isLowQuality") else 4 if has_table and has_seal else 3 if has_table or has_seal else 2
    selected = ["original"]
    priority = [
        "table_line_enhanced" if has_table else "",
        "seal_color_mask" if has_seal else "",
        "deskew" if quality.get("isLowQuality") or abs(float(quality.get("skewAngle") or 0.0)) > 0.8 else "",
        "gray_clahe",
        "adaptive_threshold",
        "denoise_light",
    ]
    for name in priority:
        if name and name in deduped and name not in selected and len(selected) < limit:
            selected.append(name)
    for name in deduped:
        if name not in selected and len(selected) < limit:
            selected.append(name)
    return selected


def build_original_variant(source_path: Path, *, page: dict[str, Any] | None = None) -> dict[str, Any]:
    page_no = int((page or {}).get("pageNo") or 1)
    return {
        "variantId": f"page_{page_no}_original",
        "pageNo": page_no,
        "path": str(source_path),
        "documentPath": str((page or {}).get("documentPath") or source_path),
        "sourceType": (page or {}).get("sourceType"),
        "coordinateSystem": (page or {}).get("coordinateSystem"),
        "sourceCoordinateSystem": (page or {}).get("sourceCoordinateSystem"),
        "renderScaleX": (page or {}).get("renderScaleX"),
        "renderScaleY": (page or {}).get("renderScaleY"),
        "pageWidth": (page or {}).get("width"),
        "pageHeight": (page or {}).get("height"),
        "preprocessChain": ["original"],
        "imageHash": file_hash(source_path) if source_path.exists() else None,
        "purpose": "general",
        "source": "original",
        "coordinateTransformStatus": "original",
    }


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


def deskew_image(cv2: Any, np: Any, image: Any, angle: float) -> Any:
    if abs(angle) < 0.3:
        return image.copy()
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def gray_clahe_image(cv2: Any, image: Any) -> Any:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)


def denoise_light_image(cv2: Any, image: Any) -> Any:
    return cv2.fastNlMeansDenoisingColored(image, None, 4, 4, 7, 21)


def adaptive_threshold_image(cv2: Any, image: Any) -> Any:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    binary = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 11)
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)


def table_line_enhanced_image(cv2: Any, np: Any, image: Any) -> Any:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 9)
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, image.shape[1] // 80), 1))
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(25, image.shape[0] // 80)))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel, iterations=1)
    lines = cv2.add(horizontal, vertical)
    closed = cv2.morphologyEx(lines, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
    result = cv2.addWeighted(image, 0.75, cv2.cvtColor(closed, cv2.COLOR_GRAY2BGR), 0.25, 0)
    return result


def seal_color_mask_image(cv2: Any, image: Any) -> Any:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, (0, 15, 35), (15, 255, 255)) | cv2.inRange(hsv, (160, 15, 35), (180, 255, 255))
    blue = cv2.inRange(hsv, (85, 35, 35), (140, 255, 255))
    mask = cv2.bitwise_or(red, blue)
    kept = cv2.bitwise_and(image, image, mask=mask)
    background = cv2.cvtColor(255 - mask, cv2.COLOR_GRAY2BGR)
    return cv2.addWeighted(kept, 1.0, background, 0.85, 0)


def preprocess_chain_for(name: str) -> list[str]:
    return {
        "deskew": ["deskew"],
        "gray_clahe": ["grayscale", "clahe"],
        "denoise_light": ["denoise_light"],
        "adaptive_threshold": ["grayscale", "gaussian_blur", "adaptive_threshold"],
        "table_line_enhanced": ["grayscale", "adaptive_threshold", "line_enhance"],
        "seal_color_mask": ["hsv_mask", "red_blue_color_preserve"],
    }.get(name, [name])


def purpose_for_variant(name: str) -> str:
    if name.startswith("table"):
        return "table"
    if name.startswith("seal"):
        return "seal"
    if name in {"gray_clahe", "denoise_light", "adaptive_threshold", "deskew"}:
        return "text"
    return "general"


def file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"
