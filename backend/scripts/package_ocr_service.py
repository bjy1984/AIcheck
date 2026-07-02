from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


OCR_PACKAGE_EXCLUDE_DIRS = {"__pycache__", "__MACOSX", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
OCR_PACKAGE_EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
OCR_PACKAGE_EXCLUDE_PREFIXES = ("._",)


def should_include_package_member(path: Path) -> bool:
    parts = set(path.parts)
    if parts.intersection(OCR_PACKAGE_EXCLUDE_DIRS):
        return False
    if path.name.startswith(OCR_PACKAGE_EXCLUDE_PREFIXES):
        return False
    if path.suffix in OCR_PACKAGE_EXCLUDE_SUFFIXES:
        return False
    return True


def build_ocr_service_package(source_dir: Path, output_path: Path) -> dict[str, Any]:
    source_dir = source_dir.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    if not source_dir.exists() or not source_dir.is_dir():
        raise ValueError(f"OCR service source directory does not exist: {source_dir}")

    members: list[str] = []
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source_dir)
            if not should_include_package_member(relative):
                continue
            archive_name = str(Path("ocr_service") / relative)
            archive.write(path, archive_name)
            members.append(archive_name)

    return {
        "schemaVersion": "aicheck-ocr-service-package-v1",
        "sourceDir": str(source_dir),
        "outputPath": str(output_path),
        "memberCount": len(members),
        "excluded": {
            "dirs": sorted(OCR_PACKAGE_EXCLUDE_DIRS),
            "suffixes": sorted(OCR_PACKAGE_EXCLUDE_SUFFIXES),
            "prefixes": list(OCR_PACKAGE_EXCLUDE_PREFIXES),
        },
        "members": members,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a clean AIcheck OCR service package.")
    parser.add_argument(
        "--source-dir",
        default=str(Path(__file__).resolve().parents[1] / "apps" / "ocr_service"),
        help="OCR service source directory. Defaults to backend/apps/ocr_service.",
    )
    parser.add_argument("--output", required=True, help="Output zip path.")
    args = parser.parse_args()

    report = build_ocr_service_package(Path(args.source_dir), Path(args.output))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
