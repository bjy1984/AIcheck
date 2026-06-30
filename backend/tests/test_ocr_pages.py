from __future__ import annotations

from pathlib import Path

from apps.ocr_service.pages import (
    file_hash,
    public_document_pages,
    render_document_pages,
    rendered_page_cache_dir,
)


def write_rgb_image(path: Path, *, size: tuple[int, int] = (80, 60), color: tuple[int, int, int] = (240, 248, 255)) -> None:
    from PIL import Image

    Image.new("RGB", size, color).save(path)


def test_render_document_pages_returns_image_record_for_plain_image(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    write_rgb_image(source, size=(120, 90))

    pages = render_document_pages(source, profile={"preprocessPolicy": {"renderDpi": 400}})

    assert len(pages) == 1
    assert pages[0]["pageNo"] == 1
    assert pages[0]["path"] == str(source)
    assert pages[0]["documentPath"] == str(source)
    assert pages[0]["sourceType"] == "png"
    assert pages[0]["renderDpi"] is None
    assert pages[0]["width"] == 120
    assert pages[0]["height"] == 90
    assert pages[0]["imageHash"].startswith("sha256:")


def test_render_document_pages_scales_large_image_to_profile_max_long_side(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_OCR_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    source = tmp_path / "large.png"
    write_rgb_image(source, size=(320, 160))

    pages = render_document_pages(source, profile={"preprocessPolicy": {"maxLongSide": 200}})

    assert len(pages) == 1
    assert pages[0]["pageNo"] == 1
    assert pages[0]["documentPath"] == str(source)
    assert pages[0]["path"] != str(source)
    assert pages[0]["width"] == 200
    assert pages[0]["height"] == 100
    assert Path(str(pages[0]["path"])).exists()


def test_render_document_pages_converts_heic_to_cached_png(tmp_path: Path, monkeypatch) -> None:
    import apps.ocr_service.pages as pages_module

    monkeypatch.setenv("AICHECK_OCR_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    source = tmp_path / "IMG_6509.heic"
    source.write_bytes(b"fake-heic")
    monkeypatch.setattr(pages_module, "convert_heic_with_pillow", lambda source_path, target: False)
    monkeypatch.setattr(pages_module.shutil, "which", lambda name: "/usr/bin/sips" if name == "sips" else None)

    def fake_run(args, **kwargs):
        target = Path(args[-1])
        write_rgb_image(target, size=(160, 120), color=(255, 255, 255))

        class Completed:
            returncode = 0

        return Completed()

    monkeypatch.setattr(pages_module.subprocess, "run", fake_run)

    pages = render_document_pages(source)

    assert len(pages) == 1
    assert pages[0]["pageNo"] == 1
    assert pages[0]["sourceType"] == "heic"
    assert pages[0]["documentPath"] == str(source)
    assert Path(str(pages[0]["path"])).suffix == ".png"
    assert pages[0]["width"] == 160
    assert pages[0]["height"] == 120
    assert pages[0]["imageHash"].startswith("sha256:")


def test_render_document_pages_splits_tiff_pages_and_respects_max_pages(tmp_path: Path, monkeypatch) -> None:
    from PIL import Image

    monkeypatch.setenv("AICHECK_OCR_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    source = tmp_path / "multi.tiff"
    first = Image.new("RGB", (40, 30), (255, 255, 255))
    second = Image.new("RGB", (50, 35), (230, 240, 255))
    third = Image.new("RGB", (60, 45), (220, 230, 250))
    first.save(source, save_all=True, append_images=[second, third])

    pages = render_document_pages(source, profile={"preprocessPolicy": {"maxPages": 2}})

    assert [page["pageNo"] for page in pages] == [1, 2]
    assert all(page["sourceType"] == "tiff" for page in pages)
    assert all(Path(str(page["path"])).exists() for page in pages)
    assert pages[0]["documentPath"] == str(source)
    assert pages[1]["documentPath"] == str(source)
    assert pages[0]["imageHash"].startswith("sha256:")
    assert pages[1]["imageHash"].startswith("sha256:")


def test_public_document_pages_drops_internal_paths(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    write_rgb_image(source)
    pages = render_document_pages(source)

    public = public_document_pages(pages)

    assert public == [
        {
            "pageNo": 1,
            "width": 80,
            "height": 60,
            "rotation": 0,
            "renderDpi": None,
            "sourceType": "png",
            "imageHash": file_hash(source),
        }
    ]
    assert "path" not in public[0]
    assert "documentPath" not in public[0]


def test_rendered_page_cache_dir_is_stable_and_content_sensitive(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_OCR_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    source = tmp_path / "source.png"
    write_rgb_image(source)

    first = rendered_page_cache_dir(source, dpi=300, max_pages=2)
    second = rendered_page_cache_dir(source, dpi=300, max_pages=2)
    changed_dpi = rendered_page_cache_dir(source, dpi=400, max_pages=2)

    assert first == second
    assert first != changed_dpi
    assert first.parent == tmp_path / "page-cache"

    source.write_bytes(b"changed")
    changed_content = rendered_page_cache_dir(source, dpi=300, max_pages=2)
    assert changed_content != first
