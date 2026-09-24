"""The evaluation snapshot must contain only selected current-version records."""

import json
import stat
import sys
import types
import zlib

import pytest

from scripts import export_jev_seven_project_snapshot as exporter
from scripts.export_jev_seven_project_snapshot import (
    PROJECT_IDS,
    _database_state,
    _private_write,
    build_snapshot,
)
from scripts.preflight_jev_document_routing import preflight_project_corpus


def _state():
    projects = [{"id": project_id, "businessPackId": "engineering_inspection_v1"}
                for project_id in PROJECT_IDS]
    documents = [{"id": f"D-{index}", "projectId": project_id, "currentVersionId": f"V-{index}"}
                 for index, project_id in enumerate(PROJECT_IDS)]
    versions = [{"id": f"V-{index}", "documentId": f"D-{index}", "tenantId": "TENANT-DEFAULT"}
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
    # 版本行要带租户：R35 以后的来源检查按版本租户过滤，缺了就一条都读不到。
    assert {row["tenantId"] for row in snapshot["versions"]} == {"TENANT-DEFAULT"}
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


def test_local_source_fingerprint_rows_keep_full_shape_and_project_scope():
    state = _state()
    state["fact_corrections"] = [
        {"projectId": PROJECT_IDS[0], "documentVersionId": "V-0", "fieldId": "F",
         "correctedByUserId": "LOCAL-ONLY", "correctedValue": "revised"},
        {"projectId": "OTHER-PROJECT", "documentVersionId": "V-OTHER", "fieldId": "F2"},
    ]
    state["extracted_fields"] = [{"documentVersionId": "V-0", "localValue": "kept"},
                                 {"documentVersionId": "V-OTHER", "localValue": "foreign"}]
    state["evidence_links"] = [{"documentVersionId": "V-0", "localMarker": "kept"}]
    snapshot = build_snapshot(state)
    assert snapshot["fact_corrections"] == [state["fact_corrections"][0]]
    assert snapshot["extracted_fields"] == [state["extracted_fields"][0]]
    assert snapshot["evidence_links"] == state["evidence_links"]


def test_database_export_reads_the_document_versions_collection(monkeypatch):
    queried_collections = []

    class Cursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, params=()):
            if query.startswith("SET TRANSACTION"):
                return Cursor([])
            if "aicheck_singletons" in query:
                return Cursor([({"materialReviewPoints": []},)])
            collection = params[1]
            queried_collections.append(collection)
            if collection == "documents":
                return Cursor([({"id": "D", "currentVersionId": "V"},)])
            if collection == "document_versions":
                return Cursor([({"id": "V", "documentId": "D"},)])
            return Cursor([])

    monkeypatch.setitem(sys.modules, "psycopg", types.SimpleNamespace(
        connect=lambda _url: Connection(), Error=Exception,
    ))
    state = _database_state("postgresql://test")
    assert state["versions"] == [{"id": "V", "documentId": "D"}]
    assert "document_versions" in queried_collections
    assert "versions" not in queried_collections


def test_explicit_private_replay_ignores_ambient_database_url(tmp_path, monkeypatch):
    source = tmp_path / "source.json.zlib"
    source.write_bytes(zlib.compress(json.dumps(_state()).encode()))
    source.chmod(0o600)
    output = tmp_path / "snapshot.json.zlib"
    monkeypatch.setenv("AICHECK_DATABASE_URL", "postgresql://must-not-be-read")
    monkeypatch.setattr(exporter, "_database_state", lambda _url: 1 / 0)
    monkeypatch.setattr(sys, "argv", ["export", "--state-zlib", str(source), "--output", str(output)])
    assert exporter.main() == 0
    assert output.exists()
