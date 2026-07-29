from __future__ import annotations

from pathlib import Path
import zipfile

from PIL import Image
from pypdf import PdfReader


TEST_WARNING = "测试专用／合成资料／不得用于真实工程"
TEST_WARNING_ASCII = "TEST-ONLY / SYNTHETIC / NOT FOR REAL ENGINEERING USE"
BODY_FONT = "Hiragino Sans GB"
HEADING_FONT = "Heiti SC"
SERIF_FONT = "Songti SC"

THEME = {
    "ink": "233142",
    "navy": "264A73",
    "slate": "5B677A",
    "pale": "EAF0F6",
    "line": "AEB9C5",
    "alert": "B3261E",
    "exception": "FCE8E6",
    "qualified": "E6F4EA",
}


def safe_file_stem(value: str) -> str:
    for char in '<>:"/\\|?*':
        value = value.replace(char, "_")
    return value.strip().rstrip(".")


def output_file_name(content: dict, extension: str) -> str:
    stem = content.get("file_stem") or (
        f"{content['logical_id']}_{content['title']}"
    )
    return f"{safe_file_stem(stem)}.{extension.lstrip('.')}"


def has_test_marking(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        metadata = " ".join(str(value) for value in (reader.metadata or {}).values())
        payload = f"{text}\n{metadata}"
        return TEST_WARNING in payload or TEST_WARNING_ASCII in payload
    if suffix in {".docx", ".xlsx"}:
        with zipfile.ZipFile(path) as archive:
            payload = b"\n".join(
                archive.read(name)
                for name in archive.namelist()
                if name.endswith(".xml") or name.endswith(".rels")
            )
        text = payload.decode("utf-8", errors="ignore")
        return (
            TEST_WARNING in text
            or TEST_WARNING.replace("／", "/") in text
            or TEST_WARNING_ASCII in text
        )
    if suffix in {".jpg", ".jpeg", ".png"}:
        with Image.open(path) as image:
            comment = image.info.get("comment", b"")
            if isinstance(comment, bytes):
                comment = comment.decode("utf-8", errors="ignore")
            exif = image.getexif()
            metadata = " ".join(str(value) for value in exif.values())
            return TEST_WARNING in f"{comment} {metadata}"
    return False
