from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def render_document_pages(source_path: Path, *, profile: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    policy = (profile or {}).get("preprocessPolicy") or {}
    dpi = int(policy.get("renderDpi") or 300)
    max_long_side = int(policy.get("maxLongSide") or 0)
    max_pages = int(policy.get("maxPages") or os.getenv("AICHECK_OCR_MAX_RENDER_PAGES", "30"))
    suffix = source_path.suffix.lower()
    if suffix == ".pdf":
        rendered = render_pdf_pages(source_path, dpi=dpi, max_pages=max_pages, max_long_side=max_long_side, profile=profile)
        return rendered
    if suffix in {".tif", ".tiff"}:
        rendered = render_tiff_pages(source_path, max_pages=max_pages, max_long_side=max_long_side)
        if rendered:
            return rendered
    if suffix in {".heic", ".heif"}:
        rendered = render_heic_page(source_path, max_long_side=max_long_side)
        if rendered:
            return rendered
    page_path = constrain_image_page(source_path, max_long_side=max_long_side, page_no=1, source_path=source_path)
    return [
        image_page_record(
            page_path,
            page_no=1,
            source_type=suffix.lstrip(".") or "image",
            render_dpi=None,
            document_path=source_path,
        )
    ]


def public_document_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for page in pages:
        output.append(
            {
                "pageNo": page.get("pageNo"),
                "width": page.get("width"),
                "height": page.get("height"),
                "rotation": page.get("rotation", 0),
                "renderDpi": page.get("renderDpi"),
                "requestedRenderDpi": page.get("requestedRenderDpi"),
                "effectiveRenderDpi": page.get("effectiveRenderDpi"),
                "sourceType": page.get("sourceType"),
                "totalPages": page.get("totalPages"),
                "renderedPages": page.get("renderedPages"),
                "truncated": page.get("truncated"),
                "coordinateSystem": page.get("coordinateSystem"),
                "sourceCoordinateSystem": page.get("sourceCoordinateSystem"),
                "renderScaleX": page.get("renderScaleX"),
                "renderScaleY": page.get("renderScaleY"),
                "imageHash": page.get("imageHash"),
            }
        )
    return output


def render_pdf_pages(
    source_path: Path,
    *,
    dpi: int,
    max_pages: int,
    max_long_side: int = 0,
    profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        import fitz  # type: ignore
    except Exception:
        return []
    try:
        document = fitz.open(str(source_path))
    except Exception:
        return []
    pages: list[dict[str, Any]] = []
    out_dir = rendered_page_cache_dir(source_path, dpi=dpi, max_pages=max_pages, max_long_side=max_long_side)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        total_pages = int(getattr(document, "page_count", 0) or len(document))
        selected_indices = select_pdf_page_indices(total_pages, max_pages, profile=profile)
        rendered_pages = [index + 1 for index in selected_indices]
        truncated = len(selected_indices) < total_pages
        for page_index in selected_indices:
            page = document[page_index]
            page_no = page_index + 1
            dpi_scale = dpi / 72.0
            if max_long_side > 0:
                max_scale = max_long_side / max(float(page.rect.width), float(page.rect.height), 1.0)
                scale = min(dpi_scale, max_scale)
            else:
                scale = dpi_scale
            matrix = fitz.Matrix(scale, scale)
            target = out_dir / f"page-{page_no}.png"
            if not target.exists():
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                pixmap.save(str(target))
            page_path = target
            pages.append(
                image_page_record(
                    page_path,
                    page_no=page_no,
                    source_type="pdf",
                    render_dpi=int(round(scale * 72)),
                    document_path=source_path,
                    rotation=int(page.rotation or 0),
                    source_width=float(page.rect.width),
                    source_height=float(page.rect.height),
                    source_coordinate_system="pdf_points",
                    render_scale_x=scale,
                    render_scale_y=scale,
                    requested_render_dpi=dpi,
                    effective_render_dpi=int(round(scale * 72)),
                    total_pages=total_pages,
                    rendered_pages=rendered_pages,
                    truncated=truncated,
                )
            )
    finally:
        document.close()
    return pages


def select_pdf_page_indices(
    total_pages: int,
    max_pages: int,
    *,
    profile: dict[str, Any] | None = None,
) -> list[int]:
    total_pages = max(int(total_pages or 0), 0)
    if total_pages <= 0:
        return []
    max_pages = max(int(max_pages or total_pages), 1)
    if total_pages <= max_pages:
        return list(range(total_pages))
    requires_tail = profile_requires_tail_pages(profile)
    if not requires_tail:
        return list(range(min(total_pages, max_pages)))
    protected = {0}
    if total_pages >= 2:
        protected.add(total_pages - 1)
    if max_pages >= 3 and total_pages >= 3:
        protected.add(total_pages - 2)
    remaining_slots = max(max_pages - len(protected), 0)
    body: list[int] = []
    if remaining_slots > 0:
        for index in range(total_pages):
            if index in protected:
                continue
            body.append(index)
            if len(body) >= remaining_slots:
                break
    return sorted(protected.union(body))


def profile_requires_tail_pages(profile: dict[str, Any] | None) -> bool:
    if not isinstance(profile, dict):
        return False
    seal_required = bool((profile.get("sealRules") or {}).get("required"))
    signature_required = bool((profile.get("signatureRules") or {}).get("required"))
    return seal_required or signature_required


def render_tiff_pages(source_path: Path, *, max_pages: int, max_long_side: int = 0) -> list[dict[str, Any]]:
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return []
    out_dir = rendered_page_cache_dir(source_path, dpi=0, max_pages=max_pages)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict[str, Any]] = []
    try:
        with Image.open(str(source_path)) as image:
            page_index = 0
            while page_index < max_pages:
                try:
                    image.seek(page_index)
                except EOFError:
                    break
                page_no = page_index + 1
                target = out_dir / f"page-{page_no}.png"
                if not target.exists():
                    image.convert("RGB").save(str(target))
                page_path = constrain_image_page(target, max_long_side=max_long_side, page_no=page_no, source_path=source_path)
                pages.append(
                    image_page_record(
                        page_path,
                        page_no=page_no,
                        source_type="tiff",
                        render_dpi=None,
                        document_path=source_path,
                    )
                )
                page_index += 1
    except Exception:
        return []
    return pages


def render_heic_page(source_path: Path, *, max_long_side: int = 0) -> list[dict[str, Any]]:
    out_dir = rendered_page_cache_dir(source_path, dpi=0, max_pages=1)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "page-1.png"
    if not target.exists() and not convert_heic_with_pillow(source_path, target) and not convert_heic_with_sips(source_path, target):
        return []
    page_path = constrain_image_page(target, max_long_side=max_long_side, page_no=1, source_path=source_path)
    return [
        image_page_record(
            page_path,
            page_no=1,
            source_type=source_path.suffix.lower().lstrip(".") or "heic",
            render_dpi=None,
            document_path=source_path,
        )
    ]


def constrain_image_page(
    path: Path,
    *,
    max_long_side: int,
    page_no: int,
    source_path: Path,
) -> Path:
    if max_long_side <= 0:
        return path
    width, height = image_size(path)
    if not width or not height or max(width, height) <= max_long_side:
        return path
    out_dir = rendered_page_cache_dir(source_path, dpi=0, max_pages=page_no)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"page-{page_no}-max-{max_long_side}.png"
    if target.exists():
        return target
    ratio = max_long_side / float(max(width, height))
    new_size = (max(1, int(round(width * ratio))), max(1, int(round(height * ratio))))
    if resize_with_pillow(path, target, new_size) or resize_with_cv2(path, target, new_size):
        return target
    return path


def resize_with_pillow(path: Path, target: Path, size: tuple[int, int]) -> bool:
    try:
        from PIL import Image  # type: ignore

        resampling = getattr(Image, "Resampling", Image).LANCZOS
        with Image.open(str(path)) as image:
            image.convert("RGB").resize(size, resampling).save(target)
        return target.exists()
    except Exception:
        return False


def resize_with_cv2(path: Path, target: Path, size: tuple[int, int]) -> bool:
    try:
        import cv2  # type: ignore

        image = cv2.imread(str(path))
        if image is None:
            return False
        resized = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
        return bool(cv2.imwrite(str(target), resized))
    except Exception:
        return False


def convert_heic_with_pillow(source_path: Path, target: Path) -> bool:
    try:
        from PIL import Image  # type: ignore

        with Image.open(str(source_path)) as image:
            image.convert("RGB").save(str(target))
        return target.exists()
    except Exception:
        return False


def convert_heic_with_sips(source_path: Path, target: Path) -> bool:
    if shutil.which("sips") is None:
        return False
    try:
        completed = subprocess.run(
            ["sips", "-s", "format", "png", str(source_path), "--out", str(target)],
            check=False,
            capture_output=True,
            encoding="utf-8",
            timeout=30,
        )
    except Exception:
        return False
    return completed.returncode == 0 and target.exists()


def image_page_record(
    path: Path,
    *,
    page_no: int,
    source_type: str,
    render_dpi: int | None,
    document_path: Path | None = None,
    rotation: int = 0,
    source_width: float | None = None,
    source_height: float | None = None,
    source_coordinate_system: str | None = None,
    render_scale_x: float | None = None,
    render_scale_y: float | None = None,
    requested_render_dpi: int | None = None,
    effective_render_dpi: int | None = None,
    total_pages: int | None = None,
    rendered_pages: list[int] | None = None,
    truncated: bool | None = None,
) -> dict[str, Any]:
    width, height = image_size(path)
    return {
        "pageNo": page_no,
        "path": str(path),
        "documentPath": str(document_path or path),
        "sourceType": source_type,
        "renderDpi": render_dpi,
        "requestedRenderDpi": requested_render_dpi,
        "effectiveRenderDpi": effective_render_dpi,
        "width": width,
        "height": height,
        "totalPages": total_pages,
        "renderedPages": rendered_pages,
        "truncated": truncated,
        "coordinateSystem": "rendered_pixels",
        "sourceCoordinateSystem": source_coordinate_system,
        "sourceWidth": source_width,
        "sourceHeight": source_height,
        "renderScaleX": render_scale_x,
        "renderScaleY": render_scale_y,
        "rotation": rotation,
        "imageHash": file_hash(path) if path.exists() else None,
    }


def image_size(path: Path) -> tuple[int | None, int | None]:
    try:
        import cv2  # type: ignore

        image = cv2.imread(str(path))
        if image is not None:
            height, width = image.shape[:2]
            return int(width), int(height)
    except Exception:
        pass
    try:
        from PIL import Image  # type: ignore

        with Image.open(str(path)) as image:
            width, height = image.size
            return int(width), int(height)
    except Exception:
        return None, None


def rendered_page_cache_dir(source_path: Path, *, dpi: int, max_pages: int, max_long_side: int = 0) -> Path:
    base = Path(os.getenv("AICHECK_OCR_PAGE_CACHE_DIR") or (Path(tempfile.gettempdir()) / "aicheck-ocr-page-cache"))
    payload = (
        f"{source_path}:{file_hash(source_path) if source_path.exists() else ''}:"
        f"dpi={dpi}:max={max_pages}:maxLongSide={max_long_side}"
    )
    key = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return base / key


def file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"
