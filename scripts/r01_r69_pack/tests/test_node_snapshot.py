from pathlib import Path
import unittest

from scripts.r01_r69_pack.node_snapshot import load_node_snapshot


ROOT = Path(__file__).resolve().parents[3]


class NodeSnapshotTest(unittest.TestCase):
    def test_snapshot_has_contiguous_nodes_and_requirements(self):
        snapshot = load_node_snapshot(
            ROOT / "scripts/r01_r69_pack/data/requirement_map.json"
        )
        self.assertEqual([node.code for node in snapshot.nodes], list(range(1, 70)))
        self.assertEqual(len(snapshot.requirements), 166)
        self.assertEqual(snapshot.requirements_for_node(69), [])

    def test_every_requirement_has_resolution(self):
        snapshot = load_node_snapshot(
            ROOT / "scripts/r01_r69_pack/data/requirement_map.json"
        )
        self.assertTrue(
            all(
                row.status in {"已提供", "本场景不适用"}
                for row in snapshot.requirements
            )
        )
        self.assertTrue(
            all(row.locator or row.rationale for row in snapshot.requirements)
        )

    def test_visual_requirements_bind_independent_attachments(self):
        snapshot = load_node_snapshot(
            ROOT / "scripts/r01_r69_pack/data/requirement_map.json"
        )
        photos = [
            row.logical_document_id
            for row in snapshot.requirements
            if row.material_type_code == "field_photo"
        ]
        films = [
            row.logical_document_id
            for row in snapshot.requirements
            if row.material_type_code == "radiographic_film"
        ]
        queries = [
            row.logical_document_id
            for row in snapshot.requirements
            if row.material_type_code == "external_query_screenshot"
        ]
        self.assertEqual(len(photos), 11)
        self.assertEqual(len(set(photos)), 11)
        self.assertEqual(len(films), 3)
        self.assertEqual(len(set(films)), 3)
        self.assertEqual(queries, ["B00-QUERY-001"])

    def test_source_backed_requirements_have_page_level_locators(self):
        snapshot = load_node_snapshot(
            ROOT / "scripts/r01_r69_pack/data/requirement_map.json"
        )
        source_backed = [
            row
            for row in snapshot.requirements
            if row.node in {1, 2, 3, 4, 5, 6, 8, 9, 12, 13, 14, 24, 26,
                            27, 29, 35, 37, 38, 40, 41, 42, 43, 44, 45,
                            47, 59, 60, 61, 62, 68}
        ]
        self.assertTrue(
            all(".pdf#p" in row.locator for row in source_backed),
            "来源证据要求必须定位到仓库PDF及页码",
        )


if __name__ == "__main__":
    unittest.main()
