from __future__ import annotations

import argparse
import io
import json
import math
import sys
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.db.repository import load_state, repo
from libs.db.seed import STANDARD_RULES_SOURCE_ID
from libs.knowledge_indexing import noise_like_text


def bbox_extents(raw: Any) -> list[float] | None:
    if not isinstance(raw, list) or len(raw) < 4:
        return None
    if isinstance(raw[0], list):
        points: list[tuple[float, float]] = []
        for point in raw:
            if not isinstance(point, list) or len(point) < 2:
                continue
            try:
                x = float(point[0])
                y = float(point[1])
            except (TypeError, ValueError):
                continue
            if math.isfinite(x) and math.isfinite(y):
                points.append((x, y))
        if not points:
            return None
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return [min(xs), min(ys), max(xs), max(ys)]
    try:
        values = [float(value) for value in raw[:4]]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in values):
        return None
    x1, y1, x2, y2 = values
    return [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]


def union_boxes(boxes: list[list[float]]) -> list[float] | None:
    if not boxes:
        return None
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def noise_like(text: Any) -> bool:
    return noise_like_text(text)


def standard_files() -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id") or ""): item
        for item in repo.state.get("knowledge_files", [])
        if str(item.get("sourceId") or "") == STANDARD_RULES_SOURCE_ID
    }


def parse_pages_by_version() -> dict[str, dict[int, dict[str, Any]]]:
    pages_by_version: dict[str, dict[int, dict[str, Any]]] = {}
    for result in repo.state.get("ocr_parse_results", []):
        if not isinstance(result, dict):
            continue
        version_id = str(result.get("documentVersionId") or "")
        if not version_id:
            continue
        page_map = pages_by_version.setdefault(version_id, {})
        for page in result.get("pages") or []:
            if not isinstance(page, dict):
                continue
            try:
                page_no = int(page.get("pageNo") or page.get("page") or 0)
            except (TypeError, ValueError):
                page_no = 0
            if page_no > 0:
                page_map[page_no] = page
    return pages_by_version


def source_path_for_file(file: dict[str, Any]) -> Path | None:
    raw = str(file.get("sourceRelativePath") or file.get("storageKey") or file.get("fileName") or "")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = WORKSPACE_ROOT / path
    try:
        resolved = path.resolve()
    except OSError:
        return None
    return resolved if resolved.is_file() else None


def page_dimensions(path: Path | None, page_no: int) -> tuple[float | None, float | None, float | None, float | None]:
    if not path:
        return None, None, None, None
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            import fitz  # type: ignore

            with fitz.open(str(path)) as doc:
                if not doc:
                    return None, None, None, None
                page = doc[max(0, min(page_no - 1, len(doc) - 1))]
                width = float(page.rect.width)
                height = float(page.rect.height)
                return width, height, math.ceil(width * 2), math.ceil(height * 2)
        except Exception:
            return None, None, None, None
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.thumbnail((1600, 1600))
            width, height = image.size
            return float(width), float(height), float(width), float(height)
    except Exception:
        return None, None, None, None


def chunk_roi_boxes(chunk: dict[str, Any]) -> list[list[float]]:
    roi = chunk.get("roi") if isinstance(chunk.get("roi"), dict) else {}
    boxes: list[list[float]] = []
    for box in roi.get("boxes") or []:
        if not isinstance(box, dict):
            continue
        extents = bbox_extents(box.get("bbox") or box.get("polygon"))
        if extents:
            boxes.append(extents)
    if boxes:
        return boxes
    extents = bbox_extents(chunk.get("bbox"))
    return [extents] if extents else []


def infer_source_size(
    *,
    chunk: dict[str, Any],
    union: list[float] | None,
    file: dict[str, Any],
    ocr_pages: dict[str, dict[int, dict[str, Any]]],
) -> tuple[str, float | None, float | None, float | None, float | None]:
    roi = chunk.get("roi") if isinstance(chunk.get("roi"), dict) else {}
    source_width = roi.get("sourceImageWidth")
    source_height = roi.get("sourceImageHeight")
    preview_width = roi.get("previewWidth")
    preview_height = roi.get("previewHeight")
    coordinate_system = str(roi.get("coordinateSystem") or "")
    if source_width and source_height:
        return coordinate_system or "roi_declared", float(source_width), float(source_height), float(preview_width or source_width), float(preview_height or source_height)
    source_method = str(chunk.get("sourceMethod") or "").lower()
    page_no = int(chunk.get("pageNo") or 1)
    ocr_page = ocr_pages.get(str(file.get("documentVersionId") or ""), {}).get(page_no, {})
    if "ocr" in source_method and isinstance(ocr_page, dict):
        ocr_width = ocr_page.get("sourceImageWidth") or ocr_page.get("imageWidth") or ocr_page.get("width")
        ocr_height = ocr_page.get("sourceImageHeight") or ocr_page.get("imageHeight") or ocr_page.get("height")
        if ocr_width and ocr_height:
            return str(ocr_page.get("coordinateSystem") or "rendered_pixels"), float(ocr_width), float(ocr_height), float(ocr_width), float(ocr_height)
    path = source_path_for_file(file)
    page_width, page_height, rendered_width, rendered_height = page_dimensions(path, page_no)
    if "ocr" in source_method and page_width and page_height and rendered_width and rendered_height:
        if page_width < 1000 and page_height < 1600:
            return "ocr_preview_px", rendered_width, rendered_height, rendered_width, rendered_height
        if union and (union[2] > page_width * 1.05 or union[3] > page_height * 1.05):
            return "ocr_preview_px", rendered_width, rendered_height, rendered_width, rendered_height
        return "ocr_image_px", page_width, page_height, rendered_width, rendered_height
    return "pdf_page_points" if page_width and page_height else "unknown", page_width, page_height, rendered_width, rendered_height


def roi_applicable(file: dict[str, Any]) -> bool:
    path = source_path_for_file(file)
    if not path:
        return False
    return path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


def inside_bounds(box: list[float], width: float | None, height: float | None) -> bool:
    if not width or not height:
        return False
    x1, y1, x2, y2 = box
    return x2 > x1 and y2 > y1 and x1 >= 0 and y1 >= 0 and x2 <= width * 1.02 and y2 <= height * 1.02


def render_overlay(path: Path, page_no: int, boxes: list[list[float]], width: float | None, height: float | None, target: Path) -> bool:
    try:
        from PIL import Image, ImageDraw

        if path.suffix.lower() == ".pdf":
            import fitz  # type: ignore

            with fitz.open(str(path)) as doc:
                page = doc[max(0, min(page_no - 1, len(doc) - 1))]
                scale = 2
                if width and page.rect.width:
                    scale = max(0.2, min(6.0, float(width) / float(page.rect.width)))
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
        else:
            image = Image.open(path).convert("RGB")
        draw = ImageDraw.Draw(image)
        for box in boxes:
            draw.rectangle(box, outline=(37, 99, 235), width=4)
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target)
        return True
    except Exception:
        return False


def audit(limit: int = 0, overlay_dir: Path | None = None) -> dict[str, Any]:
    load_state()
    files = standard_files()
    ocr_pages = parse_pages_by_version()
    chunks = [
        chunk
        for chunk in repo.state.get("knowledge_chunks", [])
        if str(chunk.get("fileId") or "") in files
    ]
    if limit > 0:
        chunks = chunks[:limit]
    warning_counts: dict[str, int] = {}
    coordinate_counts: dict[str, int] = {}
    issue_rows: list[dict[str, Any]] = []
    covered = 0
    in_bounds = 0
    dimensions_ready = 0
    multi_box = 0
    noise = 0
    applicable = 0
    non_applicable = 0
    overlays: list[str] = []
    for chunk in chunks:
        file = files.get(str(chunk.get("fileId") or ""), {})
        applies = roi_applicable(file)
        if applies:
            applicable += 1
        else:
            non_applicable += 1
        boxes = chunk_roi_boxes(chunk)
        union = union_boxes(boxes)
        coordinate_system, width, height, _preview_width, _preview_height = infer_source_size(
            chunk=chunk,
            union=union,
            file=file,
            ocr_pages=ocr_pages,
        )
        coordinate_counts[coordinate_system] = coordinate_counts.get(coordinate_system, 0) + 1
        if applies and boxes:
            covered += 1
        if len(boxes) > 1:
            multi_box += 1
        if applies and width and height:
            dimensions_ready += 1
        chunk_in_bounds = bool(boxes) and all(inside_bounds(box, width, height) for box in boxes)
        if applies and chunk_in_bounds:
            in_bounds += 1
        if noise_like(chunk.get("text")):
            noise += 1
            warning_counts["noise_like_watermark"] = warning_counts.get("noise_like_watermark", 0) + 1
        if applies and not boxes:
            warning_counts["missing_roi"] = warning_counts.get("missing_roi", 0) + 1
        if applies and boxes and not chunk_in_bounds:
            warning_counts["roi_out_of_bounds"] = warning_counts.get("roi_out_of_bounds", 0) + 1
        if applies and (not width or not height):
            warning_counts["source_dimensions_missing"] = warning_counts.get("source_dimensions_missing", 0) + 1
        if applies and (not boxes or not chunk_in_bounds or not width or not height or noise_like(chunk.get("text"))) and len(issue_rows) < 200:
            issue_rows.append(
                {
                    "chunkId": chunk.get("id") or chunk.get("chunkId"),
                    "fileName": file.get("fileName"),
                    "pageNo": chunk.get("pageNo"),
                    "coordinateSystem": coordinate_system,
                    "sourceWidth": width,
                    "sourceHeight": height,
                    "bbox": chunk.get("bbox"),
                    "textPreview": str(chunk.get("text") or "")[:160],
                    "issues": [
                        issue
                        for issue, present in {
                            "missing_roi": not boxes,
                            "roi_out_of_bounds": boxes and not chunk_in_bounds,
                            "source_dimensions_missing": not width or not height,
                            "noise_like_watermark": noise_like(chunk.get("text")),
                        }.items()
                        if present
                    ],
                }
            )
        if overlay_dir and boxes and len(overlays) < 30:
            path = source_path_for_file(file)
            if path:
                target = overlay_dir / f"{chunk.get('id') or chunk.get('chunkId')}.png"
                if render_overlay(path, int(chunk.get("pageNo") or 1), boxes, width, height, target):
                    overlays.append(str(target))
    total = len(chunks)
    denominator = applicable or total
    coverage = covered / denominator if denominator else 0.0
    in_bounds_rate = in_bounds / covered if covered else 0.0
    dimensions_rate = dimensions_ready / denominator if denominator else 0.0
    noise_rate = noise / total if total else 0.0
    score = round(100 * (0.42 * coverage + 0.34 * in_bounds_rate + 0.16 * dimensions_rate + 0.08 * max(0.0, 1 - noise_rate)), 2)
    return {
        "schemaVersion": "KnowledgeRoiQualityAudit@1.0.0",
        "score": score,
        "metrics": {
            "fileCount": len(files),
            "chunkCount": total,
            "roiApplicableCount": applicable,
            "roiNotApplicableTextSourceCount": non_applicable,
            "roiCoveredCount": covered,
            "roiCoverage": round(coverage, 4),
            "roiInBoundsCount": in_bounds,
            "roiInBoundsRate": round(in_bounds_rate, 4),
            "sourceDimensionsReadyCount": dimensions_ready,
            "sourceDimensionsReadyRate": round(dimensions_rate, 4),
            "multiBoxChunkCount": multi_box,
            "noiseLikeWatermarkCount": noise,
            "noiseLikeWatermarkRate": round(noise_rate, 4),
        },
        "coordinateSystemCounts": coordinate_counts,
        "warningCounts": warning_counts,
        "issues": issue_rows,
        "overlays": overlays,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit knowledge ROI/bbox quality for rules standards.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--limit", type=int, default=0, help="Limit audited chunks for fast sampling.")
    parser.add_argument("--overlay-dir", type=Path, default=None, help="Optional directory for sample ROI overlay PNGs.")
    parser.add_argument("--fail-under", type=float, default=None, help="Exit non-zero when score is below this value.")
    args = parser.parse_args()
    report = audit(limit=args.limit, overlay_dir=args.overlay_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        metrics = report["metrics"]
        print(f"ROI score: {report['score']}")
        print(f"Chunks: {metrics['chunkCount']} | coverage: {metrics['roiCoverage']:.2%} | in bounds: {metrics['roiInBoundsRate']:.2%}")
        print(f"Warnings: {json.dumps(report['warningCounts'], ensure_ascii=False)}")
    if args.fail_under is not None and float(report["score"]) < args.fail_under:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
