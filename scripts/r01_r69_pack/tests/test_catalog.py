from pathlib import Path
import unittest

from scripts.r01_r69_pack.catalog import load_catalog
from scripts.r01_r69_pack.model import load_project_master
from scripts.r01_r69_pack.node_snapshot import load_node_snapshot


ROOT = Path(__file__).resolve().parents[3]


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.master = load_project_master(
            ROOT / "scripts/r01_r69_pack/data/project_master.json"
        )
        cls.snapshot = load_node_snapshot(
            ROOT / "scripts/r01_r69_pack/data/requirement_map.json"
        )

    def test_exact_logical_and_physical_counts(self):
        catalog = load_catalog(
            ROOT / "scripts/r01_r69_pack/data/document_catalog.json"
        )
        self.assertEqual(len(catalog.documents), 58)
        self.assertEqual(catalog.expected_physical_file_count(), 114)
        self.assertEqual(
            catalog.logical_counts_by_folder(),
            {
                "M00": 4,
                "B00": 12,
                "S01": 7,
                "S02": 5,
                "S03": 9,
                "S04": 6,
                "S05": 5,
                "S06": 5,
                "V00": 5,
            },
        )

    def test_catalog_covers_r01_to_r68(self):
        catalog = load_catalog(
            ROOT / "scripts/r01_r69_pack/data/document_catalog.json"
        )
        covered = sorted(
            {node for document in catalog.documents for node in document.r_nodes}
        )
        self.assertEqual(covered, list(range(1, 69)))
        self.assertEqual(catalog.validate(self.master, self.snapshot), [])


if __name__ == "__main__":
    unittest.main()
