from __future__ import annotations

import json

from libs.business_pack import build_project_requirements, build_project_tree
from libs.db.seed import DEFAULT_BUSINESS_PACK, DEFAULT_MATERIAL_REVIEW_POINTS
from scripts.preflight_jev_document_routing import preflight_directory, preflight_project_corpus


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


def _project_snapshot() -> dict:
    point = {"nodeId": 25, "nodeName": "焊接工艺", "reviewContent": "核对工艺卡",
             "materialTypeName": "焊接工艺卡", "fileContent": "编号和参数"}
    return {
        "source": "read_only_seven_project_ocr_snapshot",
        "projects": [{"id": "P", "businessPackId": "engineering_inspection_v1"}],
        "documents": [
            {"id": "D1", "projectId": "P", "currentVersionId": "V1"},
            {"id": "D2", "projectId": "P", "currentVersionId": "V2"},
        ],
        "versions": [{"id": "V1", "documentId": "D1"}, {"id": "V2", "documentId": "D2"}],
        "ocr_parse_results": [
            {"id": "OLD", "documentVersionId": "V1", "status": "success",
             "createdAt": "2026-08-01 10:00:00", "fragments": [{"pageNo": 1, "text": "STALE-PRIVATE-OCR"}]},
            {"id": "NEW", "documentVersionId": "V1", "status": "success",
             "createdAt": "2026-08-02 10:00:00", "fragments": [{"pageNo": 1, "text": "LATEST-PRIVATE-OCR"}]},
            {"id": "FAILED", "documentVersionId": "V2", "status": "failed",
             "createdAt": "2026-08-02 10:00:00", "fragments": [{"pageNo": 1, "text": "FAILED-PRIVATE-OCR"}]},
        ],
        "node_evidence_links": [{"projectId": "P", "documentVersionId": "V1", "nodeId": 25}],
        "routingPointsByProject": {"P": [point]}, "configuredPoints": [point],
        "requirements": [], "tree_nodes": [],
    }


def test_project_corpus_preflight_counts_ready_versions_and_unready_latest_ocr_without_text_leak():
    report = preflight_project_corpus(_project_snapshot(), expected_project_count=1)

    assert report["projectCount"] == 1
    assert report["documentCount"] == 2
    assert report["readyCount"] == 1
    assert report["ocrAttemptCount"] == 3
    assert report["duplicateOcrVersionCount"] == 1
    assert report["requestCount"] == 1
    assert report["projects"][0]["statusCounts"] == {"ocr_not_ready": 1, "ready": 1}
    assert report["invalidEvidenceLinks"] == {}
    assert "PRIVATE-OCR" not in json.dumps(report)


def test_project_corpus_preflight_flags_cross_project_evidence_link():
    snapshot = _project_snapshot()
    snapshot["node_evidence_links"][0]["projectId"] = "OTHER"

    report = preflight_project_corpus(snapshot, expected_project_count=1)

    assert report["invalidEvidenceLinks"] == {"wrong_project": 1}
