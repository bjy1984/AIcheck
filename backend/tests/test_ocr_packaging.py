from __future__ import annotations

import zipfile
from pathlib import Path


def test_ocr_service_package_excludes_cache_files(tmp_path: Path) -> None:
    from scripts.package_ocr_service import build_ocr_service_package

    source = tmp_path / "ocr_service"
    (source / "engines").mkdir(parents=True)
    (source / "__pycache__").mkdir()
    (source / "__MACOSX").mkdir()
    (source / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (source / "engines" / "base.py").write_text("class Engine: pass\n", encoding="utf-8")
    (source / "__pycache__" / "main.cpython-312.pyc").write_bytes(b"cache")
    (source / "__MACOSX" / "._main.py").write_bytes(b"mac")
    (source / "._main.py").write_bytes(b"mac resource fork")
    (source / "engines" / "base.pyc").write_bytes(b"bytecode")

    output = tmp_path / "ocr_service.zip"
    report = build_ocr_service_package(source, output)

    assert report["memberCount"] == 2
    assert output.exists()
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())

    assert names == {"ocr_service/main.py", "ocr_service/engines/base.py"}
