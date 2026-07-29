from pathlib import Path
import unittest

from scripts.r01_r69_pack.model import load_project_master
from scripts.r01_r69_pack.source_extract import extract_source_facts


ROOT = Path(__file__).resolve().parents[3]


class ProjectModelTest(unittest.TestCase):
    def test_source_identity_is_reused(self):
        facts = extract_source_facts(ROOT)
        self.assertEqual(
            facts.project_name,
            "珠海恒基达鑫国际化工仓储股份有限公司一、二期装车站新增两套卸车系统项目",
        )
        self.assertEqual(facts.design_organization, "广东星燃石化设计院有限公司")
        self.assertIn("QX201903S-13-Y-07", facts.drawing_numbers)
        self.assertIn("QX201903S-13-Y-10", facts.drawing_numbers)

    def test_master_has_exact_object_counts(self):
        master = load_project_master(
            ROOT / "scripts/r01_r69_pack/data/project_master.json"
        )
        self.assertEqual(len(master.lines), 11)
        self.assertEqual(len(master.welds), 30)
        self.assertEqual(len(master.material_batches), 5)
        self.assertEqual(master.validate(), [])


if __name__ == "__main__":
    unittest.main()
