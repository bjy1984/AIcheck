from __future__ import annotations

from pathlib import Path

from apps.ocr_service import service


def test_resolve_source_path_prefers_allowed_local_relative_file(tmp_path: Path, monkeypatch) -> None:
    samples = tmp_path / "Scan"
    samples.mkdir()
    source = samples / "sample.pdf"
    source.write_bytes(b"%PDF-1.4 sample")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", str(samples))

    def fail_download(*args, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("local relative sample should be resolved before object storage")

    monkeypatch.setattr(service.object_storage, "download_to_temp", fail_download)

    resolved = service.resolve_source_path("Scan/sample.pdf", "sample.pdf")

    assert resolved == Path("Scan/sample.pdf")


def test_resolve_source_path_blocks_disallowed_absolute_local_file(tmp_path: Path, monkeypatch) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    source = outside / "secret.pdf"
    source.write_bytes(b"%PDF-1.4 secret")
    monkeypatch.setenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", str(allowed))

    def fail_download(*args, **kwargs):  # pragma: no cover - absolute local paths should not fall through
        raise AssertionError("disallowed absolute local path must not be treated as object storage")

    monkeypatch.setattr(service.object_storage, "download_to_temp", fail_download)

    assert service.resolve_source_path(str(source), source.name) is None


def test_resolve_source_path_blocks_symlink_escape_from_allowed_dir(tmp_path: Path, monkeypatch) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    target = outside / "secret.pdf"
    target.write_bytes(b"%PDF-1.4 secret")
    link = allowed / "linked-secret.pdf"
    link.symlink_to(target)
    monkeypatch.setenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", str(allowed))

    assert service.direct_path_allowed(link) is False
    assert service.resolve_source_path(str(link), link.name) is None


def test_resolve_source_path_allows_any_direct_path_only_with_explicit_switch(tmp_path: Path, monkeypatch) -> None:
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4 outside")
    monkeypatch.setenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", str(tmp_path / "allowed"))
    monkeypatch.setenv("AICHECK_OCR_ALLOW_DIRECT_PATHS", "true")

    assert service.resolve_source_path(str(outside), outside.name) == outside


def test_resolve_source_path_downloads_minio_url_to_temp(tmp_path: Path, monkeypatch) -> None:
    downloaded = tmp_path / "downloaded.pdf"
    downloaded.write_bytes(b"%PDF-1.4 downloaded")
    calls: list[tuple[str, str, str]] = []

    def fake_download(bucket: str, object_name: str, *, suffix: str = ""):
        calls.append((bucket, object_name, suffix))
        return downloaded

    monkeypatch.setattr(service.object_storage, "download_to_temp", fake_download)

    assert service.resolve_source_path("minio://documents/path/to/sample.pdf", "sample.pdf") == downloaded
    assert calls == [("documents", "path/to/sample.pdf", ".pdf")]


def test_resolve_source_path_falls_through_empty_object_download(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", str(tmp_path))
    monkeypatch.setattr(service.object_storage, "download_to_temp", lambda *args, **kwargs: None)

    assert service.resolve_source_path("missing-object.pdf", "missing-object.pdf") is None
