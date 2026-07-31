from pathlib import Path
import unittest

from scripts.r01_r69_pack.catalog import load_catalog
from scripts.r01_r69_pack.model import load_project_master
from scripts.r01_r69_pack.node_snapshot import load_node_snapshot


ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = ROOT / "scripts/r01_r69_pack/data/document_catalog.json"


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
        catalog = load_catalog(CATALOG_PATH)
        self.assertEqual(len(catalog.documents), 76)
        self.assertEqual(catalog.expected_physical_file_count(), 136)
        self.assertEqual(
            catalog.logical_counts_by_folder(),
            {
                "M00": 7,
                "B00": 19,
                "S01": 8,
                "S02": 5,
                "S03": 9,
                "S04": 11,
                "S05": 5,
                "S06": 6,
                "V00": 6,
            },
        )

    def test_independent_visual_evidence_and_r69_workflow_are_cataloged(self):
        catalog = load_catalog(CATALOG_PATH)
        photos = {
            document.logical_id
            for document in catalog.documents
            if "PHOTO" in document.logical_id
        }
        films = {
            document.logical_id
            for document in catalog.documents
            if "FILM" in document.logical_id
        }
        queries = {
            document.logical_id
            for document in catalog.documents
            if "QUERY" in document.logical_id
        }
        self.assertEqual(len(photos), 11)
        self.assertEqual(len(films), 3)
        self.assertEqual(queries, {"B00-QUERY-001"})
        r69 = next(
            document
            for document in catalog.documents
            if document.logical_id == "V00-R69-001"
        )
        self.assertEqual(r69.r_nodes, (69,))

    def test_catalog_covers_r01_to_r69(self):
        catalog = load_catalog(CATALOG_PATH)
        covered = sorted(
            {node for document in catalog.documents for node in document.r_nodes}
        )
        self.assertEqual(covered, list(range(1, 70)))
        self.assertEqual(catalog.validate(self.master, self.snapshot), [])


if __name__ == "__main__":
    unittest.main()
