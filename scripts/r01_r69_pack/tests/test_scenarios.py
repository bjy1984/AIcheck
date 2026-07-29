from __future__ import annotations

from pathlib import Path
import unittest

from scripts.r01_r69_pack.build_pack import build_selected
from scripts.r01_r69_pack.content_factory import load_content_library


ROOT = Path(__file__).resolve().parents[3]
CONTENT_DIR = ROOT / "scripts/r01_r69_pack/data/content"


class ScenarioTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library = load_content_library(CONTENT_DIR)

    def dry_build(self, *folders: str):
        return build_selected(ROOT, set(folders), render=False)

    def assert_contains_all(self, result, tokens):
        text = result.searchable_text()
        for token in tokens:
            self.assertIn(token, text)


class BaseScenarioTest(ScenarioTestBase):
    def test_m00_b00_counts_and_base_facts(self):
        result = self.dry_build("M00", "B00")
        self.assertEqual((result.logical_count, result.physical_count), (16, 32))
        self.assertEqual(result.errors, [])
        self.assert_contains_all(
            result,
            ["QX201903S-13-Y-07", "0.55 MPa", "0.825 MPa", "PL8301"],
        )


class MaterialScenarioTest(ScenarioTestBase):
    def test_s01_has_foreign_and_new_material_chain(self):
        result = self.dry_build("S01")
        self.assertEqual((result.logical_count, result.physical_count), (7, 14))
        self.assert_contains_all(
            result,
            ["境外制造清单", "企业标准", "验证性复验", "技术评审", "型式试验", "标志移植"],
        )

    def test_s02_material_substitution_is_approved_and_closed(self):
        result = self.dry_build("S02")
        self.assertEqual((result.logical_count, result.physical_count), (5, 10))
        self.assert_contains_all(
            result,
            ["代用申请", "技术比较", "强度校核", "设计批准", "安装合格", "合格闭环"],
        )
        self.assertLess(
            result.event_date("S02", "设计批准"),
            result.event_date("S02", "材料采购"),
        )


class WeldingScenarioTest(ScenarioTestBase):
    def test_s03_exception_and_pwht_chain(self):
        result = self.dry_build("S03")
        self.assertEqual((result.logical_count, result.physical_count), (9, 18))
        self.assertEqual(
            result.event_statuses("W-S03-003"),
            [
                "施焊完成",
                "首次RT不合格",
                "返修批准",
                "返修完成",
                "RT复检合格",
                "焊后热处理完成",
                "硬度合格",
            ],
        )
        self.assertTrue(result.pwht_curve_is_continuous("W-S03-003"))
        self.assertLessEqual(result.max_hardness("W-S03-003"), 225)


class InstallationScenarioTest(ScenarioTestBase):
    def test_s04_crossing_and_cp_records(self):
        result = self.dry_build("S04")
        self.assertEqual((result.logical_count, result.physical_count), (6, 10))
        self.assertFalse(result.photo_requires_ocr("S04-PHOTO-001"))
        self.assertTrue(
            all(-1.20 <= value <= -0.85 for value in result.cp_potentials())
        )

    def test_s05_accessories_are_individually_traceable(self):
        result = self.dry_build("S05")
        self.assertEqual((result.logical_count, result.physical_count), (5, 10))
        self.assertEqual(
            result.accessory_ids(),
            {"PSV-8301-TEST", "RD-8301-TEST", "ESDV-8301-TEST"},
        )
        self.assertTrue(result.all_accessory_results_qualified())


class PressureAlternativeScenarioTest(ScenarioTestBase):
    def test_s06_is_isolated_and_closed(self):
        result = self.dry_build("S06")
        self.assertEqual((result.logical_count, result.physical_count), (5, 10))
        self.assertNotIn("B00-PRESSURE-REPORT", result.acceptance_evidence_ids())
        self.assertEqual(result.rt_coverage("W-S06-001"), 100)
        self.assertEqual(result.mt_coverage("W-S06-001"), 100)
        self.assertEqual(
            result.leak_test(), {"pressure_mpa": 0.55, "minutes": 30}
        )
        self.assertEqual(result.final_status(), "合格闭环")


if __name__ == "__main__":
    unittest.main()
