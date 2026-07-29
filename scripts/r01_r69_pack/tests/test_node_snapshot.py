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


if __name__ == "__main__":
    unittest.main()
