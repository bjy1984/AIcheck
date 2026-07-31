from __future__ import annotations

from pathlib import Path
import unittest

from scripts.r01_r69_pack.build_pack import build_selected
from scripts.r01_r69_pack.content_factory import STANDARDS, load_content_library


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
        self.assertEqual((result.logical_count, result.physical_count), (26, 45))
        self.assertEqual(result.errors, [])
        self.assert_contains_all(
            result,
            ["QX201903S-13-Y-07", "0.55 MPa", "0.825 MPa", "PL8301"],
        )

    def test_standard_titles_and_effective_dates_are_exact(self):
        standards = {row[0]: row for row in STANDARDS}
        self.assertEqual(standards["TSG 31—2025"][1], "工业管道安全技术规程")
        self.assertEqual(
            standards["TSG 92—2026"][1],
            "承压类特种设备安全附件安全技术规程",
        )
        self.assertEqual(standards["TSG 08—2026"][1], "特种设备使用管理规则")
        self.assertEqual(standards["TSG 31—2025"][4], "2026-01-01")
        self.assertEqual(standards["TSG 92—2026"][4], "2026-07-01")
        self.assertEqual(standards["TSG 08—2026"][4], "2026-05-01")
        self.assertIn("samr.gov.cn", standards["TSG 31—2025"][6])


class MaterialScenarioTest(ScenarioTestBase):
    def test_s01_has_foreign_and_new_material_chain(self):
        result = self.dry_build("S01")
        self.assertEqual((result.logical_count, result.physical_count), (8, 15))
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
        curve = result.scenario_data["S03"]["pwhtCurve"]
        holding_minutes = [
            row["minute"]
            for row in curve
            if row["weld"] == "W-S03-003"
            and 660 <= row["tc1"] <= 700
            and 660 <= row["tc2"] <= 700
        ]
        self.assertGreaterEqual(max(holding_minutes) - min(holding_minutes), 60)
        self.assertLessEqual(result.max_hardness("W-S03-003"), 225)
        initial = next(
            doc for doc in result.documents
            if doc["logical_id"] == "S03-NDT-INITIAL-001"
        )
        self.assertEqual(
            initial["evidence_panels"][0]["label"],
            "测试模拟底片图，不得作为真实检测底片",
        )


class InstallationScenarioTest(ScenarioTestBase):
    def test_s04_crossing_and_cp_records(self):
        result = self.dry_build("S04")
        self.assertEqual((result.logical_count, result.physical_count), (11, 15))
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
        self.assertEqual((result.logical_count, result.physical_count), (6, 11))
        self.assertNotIn("B00-PRESSURE-REPORT", result.acceptance_evidence_ids())
        self.assertEqual(result.rt_coverage("W-S06-001"), 100)
        self.assertEqual(result.mt_coverage("W-S06-001"), 100)
        self.assertEqual(
            result.leak_test(), {"pressure_mpa": 0.55, "minutes": 30}
        )
        self.assertEqual(result.final_status(), "合格闭环")


if __name__ == "__main__":
    unittest.main()
