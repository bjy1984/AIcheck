"""审查点 id 重键：只按 (nodeId, materialTypeCode) 唯一匹配，改写所有引用，不动匹配不上的。"""

from __future__ import annotations

from scripts.migrate_material_review_point_ids import build_id_mapping, rewrite_references

ASSET = [
    {"id": "MRP-24-welder_roster-08506E", "nodeId": 24, "materialTypeCode": "welder_roster"},
    {"id": "MRP-24-welder_certificate-NEW001", "nodeId": 24, "materialTypeCode": "welder_certificate"},
    {"id": "MRP-16-quality_certificate-A", "nodeId": 16, "materialTypeCode": "quality_certificate"},
    {"id": "MRP-16-quality_certificate-B", "nodeId": 16, "materialTypeCode": "quality_certificate"},
]


def _state() -> dict:
    return {
        "admin_config": {
            "materialReviewPoints": [
                {"id": "MRP-24-welder_roster-EE4835", "nodeId": 24, "materialTypeCode": "welder_roster"},
                {"id": "MRP-24-welder_certificate-NEW001", "nodeId": 24, "materialTypeCode": "welder_certificate"},
                {"id": "MRP-16-quality_certificate-OLD", "nodeId": 16, "materialTypeCode": "quality_certificate"},
                {"id": "MRP-99-custom-ADMIN1", "nodeId": 99, "materialTypeCode": "custom"},
            ]
        },
        "node_evidence_links": [
            {"id": "NEL-1", "reviewPointId": "MRP-24-welder_roster-EE4835"},
            {"id": "NEL-2", "reviewPointId": "MRP-16-quality_certificate-OLD"},
        ],
        "bindings": [
            {"id": "B-1", "reviewPointIds": ["MRP-24-welder_roster-EE4835", "X"], "requirementId": "MRP-24-welder_roster-EE4835"},
            {"id": "B-2", "reviewPointIds": [], "requirementId": "REQ-24-01"},
        ],
        "rectifications": [{"id": "REC-1", "supplementRequirements": [{"id": "MRP-24-welder_roster-EE4835"}]}],
    }


def test_mapping_only_covers_unique_matches() -> None:
    state = _state()
    mapping, unmatched = build_id_mapping(state["admin_config"]["materialReviewPoints"], ASSET, "engineering_inspection_v1")
    assert mapping == {"MRP-24-welder_roster-EE4835": "MRP-24-welder_roster-08506E"}
    assert [item["id"] for item in unmatched] == ["MRP-16-quality_certificate-OLD", "MRP-99-custom-ADMIN1"]
    assert unmatched[0]["candidates"] == ["MRP-16-quality_certificate-A", "MRP-16-quality_certificate-B"]


def test_rewrite_touches_every_reference_and_keeps_history() -> None:
    state = _state()
    mapping, _ = build_id_mapping(state["admin_config"]["materialReviewPoints"], ASSET, "engineering_inspection_v1")
    counts = rewrite_references(state, mapping)
    assert counts == {"materialReviewPoints": 1, "node_evidence_links": 1, "bindings": 1, "rectifications": 1}
    point = state["admin_config"]["materialReviewPoints"][0]
    assert point["id"] == "MRP-24-welder_roster-08506E" and point["previousIds"] == ["MRP-24-welder_roster-EE4835"]
    assert state["node_evidence_links"][0]["reviewPointId"] == "MRP-24-welder_roster-08506E"
    assert state["node_evidence_links"][1]["reviewPointId"] == "MRP-16-quality_certificate-OLD", "匹配不上的不动"
    assert state["bindings"][0]["reviewPointIds"] == ["MRP-24-welder_roster-08506E", "X"]
    assert state["bindings"][0]["requirementId"] == "MRP-24-welder_roster-08506E"
    assert state["bindings"][1]["requirementId"] == "REQ-24-01"
    assert state["rectifications"][0]["supplementRequirements"][0]["id"] == "MRP-24-welder_roster-08506E"
