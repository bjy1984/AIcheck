"""The evaluation snapshot must contain only selected current-version records."""

import json
import stat
import zlib

import pytest

from scripts.export_jev_seven_project_snapshot import PROJECT_IDS, _private_write, build_snapshot
from scripts.preflight_jev_document_routing import preflight_project_corpus


def _state():
    projects = [{"id": project_id, "businessPackId": "engineering_inspection_v1"}
                for project_id in PROJECT_IDS]
    documents = [{"id": f"D-{index}", "projectId": project_id, "currentVersionId": f"V-{index}"}
                 for index, project_id in enumerate(PROJECT_IDS)]
    versions = [{"id": f"V-{index}", "documentId": f"D-{index}"}
                for index in range(7)]
    parses = [{"documentVersionId": f"V-{index}",
               "fragments": [{"pageNo": 1, "text": f"approved OCR {index}"}]}
              for index in range(7)]
    return {"projects": [*projects, {"id": "OTHER-PROJECT"}],
            "documents": [*documents, {"id": "D-OTHER", "projectId": "OTHER-PROJECT",
                                     "currentVersionId": "V-OTHER"}],
            "versions": [*versions, {"id": "V-OTHER", "documentId": "D-OTHER"},
                         {"id": "V-OLD", "documentId": "D-0"}],
            "ocr_parse_results": [*parses, {"documentVersionId": "V-OLD",
                                            "fragments": [{"text": "STALE"}]},
                                  {"documentVersionId": "V-OTHER",
                                   "fragments": [{"text": "FOREIGN"}]}],
            "node_evidence_links": [], "requirements": [], "tree_nodes": [],
            "admin_config": {"materialReviewPoints": [
                {"id": "MRP-25", "nodeId": 25, "businessPackId": "engineering_inspection_v1",
                 "nodeName": "材料", "reviewContent": "材料文件归属", "enabled": True}]}}


def test_snapshot_filters_foreign_and_historical_data_then_preflights(tmp_path):
    snapshot = build_snapshot(_state())
    assert len(snapshot["projects"]) == len(snapshot["documents"]) == len(snapshot["versions"]) == 7
    assert len(snapshot["ocr_parse_results"]) == 7
    assert "FOREIGN" not in json.dumps(snapshot)
    assert "STALE" not in json.dumps(snapshot)
    assert preflight_project_corpus(snapshot, expected_project_count=7)["readyCount"] == 7
    output = tmp_path / "private.json.zlib"
    _private_write(output, zlib.compress(json.dumps(snapshot).encode()))
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(zlib.decompress(output.read_bytes()))["source"] == snapshot["source"]
    with pytest.raises(FileExistsError):
        _private_write(output, b"overwrite")


def test_snapshot_fails_when_an_approved_project_has_no_current_version():
    state = _state()
    state["versions"] = [row for row in state["versions"] if row["id"] != "V-0"]
    with pytest.raises(ValueError, match="current_versions_missing_or_duplicated"):
        build_snapshot(state)
