from pathlib import Path
import json
import re
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

    def test_master_reuses_source_organizations_without_full_national_ids(self):
        path = ROOT / "scripts/r01_r69_pack/data/project_master.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        names = {row["name"] for row in payload["organizations"]}
        self.assertTrue(
            {
                "贵州化工建设有限责任公司",
                "南京金鑫检测工程有限责任公司",
                "广州声华科技股份有限公司",
                "广东省特种设备检测研究院珠海检测院",
                "河北广浩管件有限公司",
                "烟台鲁宝钢管有限责任公司",
            }.issubset(names)
        )
        self.assertEqual(len(payload["sourceEvidence"]), 12)
        self.assertEqual(
            {row["category"] for row in payload["sourceTruth"]},
            {"壁厚", "介质", "管线范围", "无损检测单位", "证书时效"},
        )
        self.assertIsNone(re.search(r"(?<!\d)\d{18}(?!\d)", json.dumps(payload)))


if __name__ == "__main__":
    unittest.main()
