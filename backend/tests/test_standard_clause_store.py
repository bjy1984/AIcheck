from __future__ import annotations

import sqlite3

from libs.business_pack import load_business_pack
from libs.business_pack.clause_store import (
    CLAUSE_STATE_COLLECTIONS,
    bind_project_node_clause_packages,
    clause_package_snapshot_for_project_node,
    freeze_review_run_clause_snapshot,
    publish_standard_clause_release,
    review_run_clause_snapshot,
)
from libs.db.repository import InMemoryRepository
from libs.db.repository import repo
import libs.review_orchestrator.execution as execution


def test_clause_release_is_idempotent_and_review_snapshot_is_immutable() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    state = {key: [] for key in CLAUSE_STATE_COLLECTIONS}
    project = {
        "id": "P-CLAUSE-STORE-001",
        "businessPackId": pack["id"],
        "businessPackVersion": pack["version"],
        "updatedAt": "2026-07-11 12:00:00",
    }

    first = publish_standard_clause_release(state, pack)
    second = publish_standard_clause_release(state, pack)

    assert first == second
    assert first == {
            "standard_document_versions": 33,
            "standard_clause_references": 175,
            "standard_clause_locators": 243,
        "standard_clause_packages_db": 69,
            "standard_clause_package_items": 189,
    }
    assert bind_project_node_clause_packages(state, project, pack) == 69
    assert len(state["project_node_clause_packages"]) == 69

    snapshot = clause_package_snapshot_for_project_node(state, project["id"], 1)
    assert snapshot
    assert snapshot["sourceRuleId"] == "R01"
    assert len(snapshot["clauses"]) == 4
    assert snapshot["clauses"][0]["referenceRole"] == "primary"
    assert snapshot["clauses"][0]["sourcePage"] == 27
    assert snapshot["clauses"][0]["previewUrl"].endswith("#page=27")
    assert snapshot["clauses"][0]["locators"][0]["previewUrl"].endswith("#page=27")

    frozen = freeze_review_run_clause_snapshot(
        state,
        review_run_id="RRUN-CLAUSE-001",
        project_id=project["id"],
        node_id=1,
        created_at="2026-07-11 12:30:00",
    )
    assert frozen
    package = next(item for item in state["standard_clause_packages_db"] if item["id"] == snapshot["packageStorageId"])
    package["compiledPayload"]["clauses"][0]["sourcePage"] = 999
    historical = review_run_clause_snapshot(state, "RRUN-CLAUSE-001")
    assert historical
    assert historical["clauses"][0]["sourcePage"] == 27
    assert historical["snapshotHash"] == snapshot["snapshotHash"]


def test_clause_collections_persist_to_sqlite(tmp_path) -> None:
    repository = InMemoryRepository()
    repository.configure_sqlite(tmp_path / "clause-store.sqlite3")
    selected = {
        key: repository.state.get(key, [])
        for key in CLAUSE_STATE_COLLECTIONS
    }
    repository.sync_state_records_to_sqlite(selected, {})

    with sqlite3.connect(repository.sqlite_path) as connection:
        counts = dict(
            connection.execute(
                "SELECT collection, count(*) FROM aicheck_state "
                "WHERE collection LIKE '%clause%' OR collection = 'standard_document_versions' "
                "GROUP BY collection"
            ).fetchall()
        )
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE '%clause%'"
            ).fetchall()
        }

    assert counts["standard_document_versions"] == 33
    assert counts["standard_clause_packages"] == 69
    assert counts["project_node_clause_packages"] >= 69
    assert "idx_project_node_clause_packages_lookup" in indexes
    assert "idx_review_run_clause_snapshots_lookup" in indexes


def test_review_run_creation_freezes_the_ai_run_clause_package(monkeypatch) -> None:
    repo.reset()
    monkeypatch.setattr(execution, "flush_state_records", lambda records: None)
    snapshot = clause_package_snapshot_for_project_node(repo.state, "P-2026-HDCP-001", 1)
    assert snapshot
    ai_run = {
        "id": "AIRUN-CLAUSE-FREEZE-001",
        "projectId": "P-2026-HDCP-001",
        "nodeId": 1,
        "businessPackId": "engineering_inspection_v1",
        "businessPackVersion": snapshot["businessPackVersion"],
        "businessPackSnapshotHash": "pack-hash",
        "clausePackageId": snapshot["packageStorageId"],
        "clausePackageSnapshotHash": snapshot["snapshotHash"],
        "clausePackageSnapshot": snapshot,
        "inputDocumentVersionIds": [],
    }
    repo.state["ai_runs"].append(ai_run)

    review_run = execution.create_review_run_from_ai_run(ai_run, mode="inline")
    frozen = next(
        item
        for item in repo.state["review_run_clause_snapshots"]
        if item["reviewRunId"] == review_run["reviewRunId"]
    )

    assert review_run["clausePackageSnapshotHash"] == snapshot["snapshotHash"]
    assert frozen["snapshotPayload"]["sourceRuleId"] == "R01"
    assert frozen["snapshotPayload"]["clauses"][0]["sourcePage"] == 27
    assert "review_run_clause_snapshots" in execution.review_run_state_records(review_run["reviewRunId"])
    assert execution.review_run_view(review_run)["clausePackageSnapshot"]["snapshotHash"] == snapshot["snapshotHash"]
