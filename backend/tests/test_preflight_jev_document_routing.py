from __future__ import annotations

import json

from libs.business_pack import build_project_requirements, build_project_tree
from libs.db.seed import DEFAULT_BUSINESS_PACK, DEFAULT_MATERIAL_REVIEW_POINTS
from scripts.preflight_jev_document_routing import preflight_directory


def test_offline_preflight_reports_capacity_without_leaking_ocr_text(tmp_path) -> None:
    (tmp_path / "short.md").write_text("焊接工艺卡 WPS-001", encoding="utf-8")
    (tmp_path / "long.md").write_text("长" * 40_000, encoding="utf-8")
    points = [{"nodeId": 25, "nodeName": "焊接工艺", "reviewContent": "核对工艺卡",
               "materialTypeName": "焊接工艺卡", "fileContent": "编号和参数"}]

    report = preflight_directory(tmp_path, points)

    assert report["fileCount"] == 2
    assert report["readyCount"] == 1
    assert report["requestCount"] == 1
    assert {row["caseId"]: row["status"] for row in report["files"]} == {
        "long": "overlong_document", "short": "ready",
    }
    assert "WPS-001" not in json.dumps(report, ensure_ascii=False)


def test_preflight_uses_the_same_69_node_fallback_as_runtime(tmp_path) -> None:
    (tmp_path / "record.md").write_text("质量体系评价记录", encoding="utf-8")
    report = preflight_directory(
        tmp_path, DEFAULT_MATERIAL_REVIEW_POINTS,
        requirements=build_project_requirements(DEFAULT_BUSINESS_PACK, project_id="EVAL"),
        tree_nodes=build_project_tree("EVAL", DEFAULT_BUSINESS_PACK),
        project_id="EVAL", business_pack_id=DEFAULT_BUSINESS_PACK["id"],
    )
    assert report["nodeCount"] == 69
    assert report["files"][0]["status"] == "ready"
