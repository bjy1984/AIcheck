"""N-34：requiredType 不是 reconcile 的派生字段，降级要靠显式 id 的对齐脚本。

钉两件事：不一致清单只列同业务包、且配置里存在的条目；apply 只改显式指定的 id 并留痕。
"""

from __future__ import annotations

from scripts.align_material_review_point_required_type import apply_alignment, required_type_drift

ASSET = [
    {"id": "MRP-24-welder_roster-08506E", "requiredType": "可选"},
    {"id": "MRP-24-welder_certificate-000001", "requiredType": "必传"},
]


def _points() -> list[dict]:
    return [
        {"id": "MRP-24-welder_roster-08506E", "nodeId": 24, "materialTypeCode": "welder_roster", "requiredType": "必传"},
        {"id": "MRP-24-welder_certificate-000001", "nodeId": 24, "materialTypeCode": "welder_certificate", "requiredType": "必传"},
        {"id": "MRP-99-custom-ADMIN1", "nodeId": 99, "materialTypeCode": "custom", "requiredType": "必传"},
        {"id": "MRP-24-welder_roster-08506E", "businessPackId": "other_pack", "requiredType": "必传"},
    ]


def test_drift_lists_only_mismatched_points_of_the_pack() -> None:
    drift = required_type_drift(_points(), ASSET, "engineering_inspection_v1")
    assert [item["id"] for item in drift] == ["MRP-24-welder_roster-08506E"]
    assert drift[0]["current"] == "必传" and drift[0]["target"] == "可选"


def test_apply_changes_only_the_listed_ids_and_records_the_old_value() -> None:
    points = _points()
    drift = required_type_drift(points, ASSET, "engineering_inspection_v1")
    assert apply_alignment(points, drift, set()) == []
    assert points[0]["requiredType"] == "必传", "没有显式 id 时一条都不能改"
    applied = apply_alignment(points, drift, {"MRP-24-welder_roster-08506E"})
    assert applied == ["MRP-24-welder_roster-08506E"]
    assert points[0]["requiredType"] == "可选"
    assert points[0]["requiredTypeAlignedFrom"] == "必传"
    assert points[1]["requiredType"] == "必传"
