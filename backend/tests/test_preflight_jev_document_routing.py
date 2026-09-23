from __future__ import annotations

import json

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
