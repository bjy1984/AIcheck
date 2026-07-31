from __future__ import annotations

from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from scripts.r01_r69_pack.render_common import TEST_WARNING
from scripts.r01_r69_pack.validate_pack import validate_pack


ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "files/R01-R69全节点业务验收测试包"


class PackValidatorTest(unittest.TestCase):
    def test_complete_pack_passes(self):
        report = validate_pack(PACK)
        self.assertEqual(report.errors, [])
        self.assertEqual(
            report.metrics,
            {
                "nodes": 69,
                "requirements": 166,
                "logical_documents": 76,
                "physical_files": 136,
                "referenced_source_files": 12,
                "evidence_universe_files": 148,
                "field_photos": 11,
                "radiographic_films": 3,
                "external_query_screenshots": 1,
                "signed_generated_files": 136,
                "lines": 11,
                "welds": 30,
                "material_batches": 5,
            },
        )

    def test_missing_pdf_is_reported(self):
        with TemporaryDirectory() as temp:
            fixture = Path(temp) / PACK.name
            shutil.copytree(PACK, fixture)
            target = next(
                fixture.joinpath("S03_焊缝返修与热处理").glob(
                    "*REPAIR-001*.pdf"
                )
            )
            target.unlink()
            report = validate_pack(fixture)
            self.assertIn("缺少配对PDF", "\n".join(report.errors))

    def test_photo_is_presence_only(self):
        report = validate_pack(PACK)
        self.assertEqual(report.photo_ocr_attempts, 0)

    def test_missing_referenced_source_is_reported(self):
        with TemporaryDirectory() as temp:
            report = validate_pack(PACK, source_root=Path(temp))
            self.assertIn("缺少引用原始证据", "\n".join(report.errors))

    def test_missing_visual_attachment_is_reported(self):
        with TemporaryDirectory() as temp:
            fixture = Path(temp) / PACK.name
            shutil.copytree(PACK, fixture)
            target = next(fixture.rglob("*PHOTO-001*.jpg"))
            target.unlink()
            report = validate_pack(fixture)
            self.assertIn("缺少文件", "\n".join(report.errors))

    def test_generated_image_without_signature_badge_is_reported(self):
        with TemporaryDirectory() as temp:
            fixture = Path(temp) / PACK.name
            shutil.copytree(PACK, fixture)
            target = next(fixture.rglob("*PHOTO-001*.jpg"))
            image = Image.new("RGB", (800, 500), "white")
            exif = Image.Exif()
            exif[270] = TEST_WARNING
            image.save(
                target,
                quality=90,
                exif=exif,
                comment=TEST_WARNING.encode("utf-8"),
            )
            report = validate_pack(fixture)
            self.assertIn("缺少测试签章形态", "\n".join(report.errors))


if __name__ == "__main__":
    unittest.main()
