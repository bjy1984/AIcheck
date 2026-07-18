from __future__ import annotations

from pathlib import Path

from scripts.import_scan_test_scenario import (
    fragments_from_ocr,
    normalize_ocr_payload,
    resolve_import_source_path,
    vision_bbox_to_xyxy,
)


def test_heic_import_uses_full_resolution_png(tmp_path: Path) -> None:
    source = tmp_path / "IMG_6508.heic"
    source.write_bytes(b"heic")
    png = tmp_path / "png" / "IMG_6508.png"
    png.parent.mkdir()
    png.write_bytes(b"png")

    assert resolve_import_source_path(tmp_path, source) == png


def test_vision_bbox_is_converted_from_bottom_left_xywh_to_top_left_xyxy() -> None:
    bbox = vision_bbox_to_xyxy([0.1, 0.7, 0.2, 0.1], 1000, 2000)

    assert bbox == [100.0, 400.0, 300.0, 600.0]


def test_normalize_image_ocr_payload_adds_png_dimensions_and_valid_bbox(tmp_path: Path) -> None:
    from PIL import Image

    png = tmp_path / "IMG_6508.png"
    Image.new("RGB", (1000, 2000), "white").save(png)
    raw = {
        "source_file": "IMG_6508.heic",
        "pages": [
            {
                "source_page": 1,
                "observations": [
                    {"text": "压力管道", "boundingBox": [0.1, 0.7, 0.2, 0.1]},
                ],
            }
        ],
    }

    normalized = normalize_ocr_payload(raw, png)
    page = normalized["pages"][0]
    observation = page["observations"][0]

    assert page["path"] == str(png)
    assert page["coordinateSystem"] == "rendered_pixels"
    assert page["sourceImageWidth"] == 1000
    assert page["sourceImageHeight"] == 2000
    assert observation["bbox"] == [100.0, 400.0, 300.0, 600.0]
    assert observation["coordinateSystem"] == "rendered_pixels"

    fragments = fragments_from_ocr(normalized)
    assert fragments[0]["bbox"] == [100.0, 400.0, 300.0, 600.0]
    assert fragments[0]["coordinateSystem"] == "rendered_pixels"


def test_normalize_pdf_ocr_payload_uses_pdf_page_coordinates(tmp_path: Path) -> None:
    import fitz

    pdf = tmp_path / "drawing.pdf"
    with fitz.open() as document:
        document.new_page(width=600, height=800)
        document.save(pdf)
    raw = {
        "source_file": pdf.name,
        "pages": [
            {
                "source_page": 1,
                "observations": [
                    {"text": "施工图", "boundingBox": [0.1, 0.7, 0.2, 0.1]},
                ],
            }
        ],
    }

    normalized = normalize_ocr_payload(raw, pdf)
    page = normalized["pages"][0]

    assert page["coordinateSystem"] == "pdf_points"
    assert page["width"] == 600
    assert page["height"] == 800
    assert page["observations"][0]["bbox"] == [60.0, 160.0, 180.0, 240.0]
