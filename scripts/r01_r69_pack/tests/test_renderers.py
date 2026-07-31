from __future__ import annotations

import json
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from PIL import Image
from pypdf import PdfReader

from scripts.r01_r69_pack import convert_pdf
from scripts.r01_r69_pack.convert_pdf import (
    LO_FONT_DIR,
    _sheet_page_images,
    convert_office_to_pdf,
    convert_xlsx_to_pdf,
    validate_pdf,
)
from scripts.r01_r69_pack.content_factory import load_content_library
from scripts.r01_r69_pack.render_common import (
    TEST_WARNING,
    has_signature_marking,
    has_test_marking,
)
from scripts.r01_r69_pack.render_docx import render_docx
from scripts.r01_r69_pack.render_graphics import (
    render_pdf_graphic,
    render_test_photo,
)
from scripts.r01_r69_pack.render_xlsx import render_xlsx
from scripts.r01_r69_pack.test_seal import (
    render_test_seal_png,
    signature_contract,
)


ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "scripts/r01_r69_pack/data"


class RendererTest(unittest.TestCase):
    def setUp(self) -> None:
        self.master = json.loads(
            (DATA / "project_master.json").read_text(encoding="utf-8")
        )

    def test_docx_xlsx_and_pdf_are_renderable(self):
        content = {
            "logical_id": "TEST-RENDER-001",
            "title": "混合格式渲染测试记录",
            "document_number": "TEST-RENDER-001",
            "revision": "A",
            "date": "2026-04-01",
            "sections": [
                {
                    "heading": "1 编制说明",
                    "paragraphs": [
                        "本记录用于验证中文工程资料渲染链路。",
                        TEST_WARNING,
                    ],
                }
            ],
            "tables": [
                {
                    "title": "检验记录",
                    "headers": ["序号", "对象", "结果"],
                    "rows": [["1", "PL8301", "合格"]],
                }
            ],
            "approvals": [
                {
                    "role": "编制",
                    "name": "TEST-编制人",
                    "date": "2026-04-01",
                    "record": "电子记录（测试）",
                }
            ],
            "workbook": {
                "sheets": [
                    {
                        "name": "记录",
                        "headers": ["序号", "对象", "结果"],
                        "rows": [[1, "PL8301", "合格"]],
                    }
                ]
            },
        }
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            docx_path = render_docx(content, self.master, out)
            xlsx_path = render_xlsx(content, self.master, out)
            self.assertTrue(docx_path.exists())
            self.assertTrue(xlsx_path.exists())
            docx_pdf = convert_office_to_pdf(docx_path, out)
            xlsx_pdf = convert_xlsx_to_pdf(
                xlsx_path,
                out,
                [sheet["name"] for sheet in content["workbook"]["sheets"]],
            )
            self.assertEqual(validate_pdf(docx_pdf), [])
            self.assertEqual(validate_pdf(xlsx_pdf), [])
            self.assertTrue(has_test_marking(docx_path))
            self.assertTrue(has_test_marking(xlsx_path))
            self.assertTrue(has_test_marking(docx_pdf))
            self.assertTrue(has_test_marking(xlsx_pdf))
            self.assertTrue(has_signature_marking(docx_path))
            self.assertTrue(has_signature_marking(xlsx_path))
            self.assertTrue(has_signature_marking(docx_pdf))
            self.assertTrue(has_signature_marking(xlsx_pdf))

    def test_libreoffice_font_setup_uses_writable_temp_directory(self):
        with TemporaryDirectory() as tmp:
            self.assertTrue(hasattr(convert_pdf, "libreoffice_environment"))
            env = convert_pdf.libreoffice_environment(Path(tmp))
            font_dir = Path(env["SAL_FONTPATH"])
            self.assertTrue(font_dir.is_dir())
            self.assertTrue(font_dir.joinpath("ArialUnicode.ttf").exists())
            self.assertFalse(str(font_dir).startswith(str(LO_FONT_DIR)))

    def test_graphics_and_every_artifact_have_test_marking(self):
        content = {
            "logical_id": "TEST-GRAPHIC-001",
            "title": "穿越结构与焊缝布置图",
            "document_number": "TEST-GRAPHIC-001",
            "revision": "A",
            "date": "2026-04-01",
        }
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            pdf_path = render_pdf_graphic(content, self.master, out)
            photo_path = render_test_photo(content, out)
            self.assertEqual(validate_pdf(pdf_path), [])
            self.assertTrue(photo_path.exists())
            self.assertTrue(has_test_marking(pdf_path))
            self.assertTrue(has_test_marking(photo_path))
            self.assertTrue(has_signature_marking(pdf_path))
            self.assertTrue(has_signature_marking(photo_path))
            pdf_text = "\n".join(
                page.extract_text() or "" for page in PdfReader(pdf_path).pages
            )
            self.assertIn("测试专用章", pdf_text)

    def test_docx_and_xlsx_embed_safe_test_signature_graphics(self):
        content = {
            "logical_id": "TEST-SIGN-001",
            "folder": "B00",
            "title": "测试签章渲染记录",
            "document_number": "TEST-SIGN-001",
            "revision": "A",
            "date": "2026-07-15",
            "sections": [{"heading": "1 结论", "paragraphs": [TEST_WARNING]}],
            "tables": [],
            "approvals": [
                {"role": "批准", "name": "测试批准负责人丙", "date": "2026-07-15"}
            ],
            "workbook": {
                "sheets": [
                    {"name": "记录", "headers": ["对象", "结果"], "rows": [["PL8303", "合格"]]}
                ]
            },
        }
        contract = signature_contract(content)
        self.assertIn("测试专用", contract["label"])
        seal = render_test_seal_png(contract["label"], contract["role"])
        self.assertGreater(len(seal), 1000)
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            docx_path = render_docx(content, self.master, out)
            xlsx_path = render_xlsx(content, self.master, out)
            with zipfile.ZipFile(docx_path) as archive:
                self.assertTrue(
                    any(name.startswith("word/media/") for name in archive.namelist())
                )
                xml = b"".join(
                    archive.read(name)
                    for name in archive.namelist()
                    if name.endswith(".xml")
                ).decode("utf-8", errors="ignore")
                self.assertIn("电子签署（测试）", xml)
            with zipfile.ZipFile(xlsx_path) as archive:
                self.assertTrue(
                    any(name.startswith("xl/media/") for name in archive.namelist())
                )
                xml = b"".join(
                    archive.read(name)
                    for name in archive.namelist()
                    if name.endswith(".xml")
                ).decode("utf-8", errors="ignore")
                self.assertIn("电子签署（测试）", xml)

    def test_docx_signature_block_does_not_create_sparse_trailing_page(self):
        content = load_content_library(DATA / "content")["S02-WPS-001"]
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            docx_path = render_docx(content, self.master, out)
            pdf_path = convert_office_to_pdf(docx_path, out)
            self.assertLessEqual(len(PdfReader(pdf_path).pages), 2)

    def test_evidence_image_kinds_are_distinct_and_marked(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = []
            sizes = []
            for kind, stem in (
                ("field_photo", "TEST-PHOTO"),
                ("radiographic_film", "TEST-FILM"),
                ("external_query_screenshot", "TEST-QUERY"),
            ):
                path = render_test_photo(
                    {
                        "logical_id": stem,
                        "file_stem": stem,
                        "title": stem,
                        "graphic_kind": kind,
                        "evidence_object": "PL8303／W-B00-001",
                    },
                    out,
                )
                paths.append(path)
                with Image.open(path) as image:
                    sizes.append(image.size)
                    comment = image.info.get("comment", b"")
                    if isinstance(comment, bytes):
                        comment = comment.decode("utf-8")
                    self.assertIn(kind, comment)
                self.assertTrue(has_test_marking(path))
            self.assertEqual(len(set(sizes)), 3)
            self.assertEqual(
                len({hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}),
                3,
            )

    def test_xlsx_continuation_page_repeats_four_row_header(self):
        image = Image.new("RGB", (400, 1000), "white")
        for x in range(image.width):
            for y in range(100, 108):
                image.putpixel((x, y), (38, 74, 115))
            for y in range(250, 252):
                image.putpixel((x, y), (242, 242, 242))
        pages = _sheet_page_images(image)
        self.assertGreater(len(pages), 1)
        self.assertEqual(pages[1].getpixel((200, 104)), (38, 74, 115))
        self.assertEqual(pages[0].height, 252)


if __name__ == "__main__":
    unittest.main()
