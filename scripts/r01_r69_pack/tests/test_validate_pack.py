from __future__ import annotations

from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

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
                "logical_documents": 58,
                "physical_files": 114,
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


if __name__ == "__main__":
    unittest.main()
