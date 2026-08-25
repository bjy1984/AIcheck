from __future__ import annotations

from libs.review_evidence import build_evidence_snapshot


VERSIONS = {
    "rule_version": "rule-v1",
    "clause_package_version": "clauses-v1",
    "prompt_version": "prompt-v1",
    "strategy_version": "strategy-v1",
}


def _rows(prefix: str, count: int, **common: object) -> list[dict]:
    return [{"id": f"{prefix}-{index:03d}", **common} for index in range(1, count + 1)]


def _manifest_state(
    *,
    field_count: int = 0,
    table_count: int = 0,
    seal_count: int = 0,
    fragment_count: int = 0,
    evidence_link_count: int = 0,
) -> tuple[dict, dict]:
    version_id = "DV-1"
    tables = [
        {
            "id": f"TABLE-{index:03d}",
            "pageNo": index,
            "rows": [{"column": f"row-{index}"}],
            "cells": [{"rowIndex": 0, "columnIndex": 0, "text": f"cell-{index}"}],
        }
        for index in range(1, table_count + 1)
    ]
    state = {
        "documents": [{"id": "DOC-1", "projectId": "P-1", "currentVersionId": version_id}],
        "document_versions": [
            {"id": version_id, "documentId": "DOC-1", "contentHash": "sha256:document"}
        ],
        "node_evidence_links": [
            {
                "id": "NEL-1",
                "projectId": "P-1",
                "nodeId": 1,
                "documentId": "DOC-1",
                "documentVersionId": version_id,
                "manualStatus": "confirmed",
                "revision": 1,
            }
        ],
        "ocr_parse_results": [
            {
                "id": "OCR-1",
                "parseResultId": "OCR-1",
                "documentVersionId": version_id,
                "artifactHash": "sha256:ocr",
                "status": "success",
                "tables": tables,
                "seals": _rows("SEAL", seal_count, pageNo=1, text="seal text"),
                "fragments": _rows("FRAGMENT", fragment_count, pageNo=1, text="fragment text"),
            }
        ],
        "extracted_fields": [
            {
                "id": f"FIELD-{index:03d}",
                "documentVersionId": version_id,
                "fieldName": f"field-{index}",
                "fieldValue": f"value-{index}",
                "pageNo": 1,
            }
            for index in range(1, field_count + 1)
        ],
        "evidence_links": [
            {
                "id": f"EV-{index:03d}",
                "documentVersionId": version_id,
                "quotedText": f"evidence-{index}",
                "pageNo": 1,
                "bbox": [1, 2, 30, 40],
            }
            for index in range(1, evidence_link_count + 1)
        ],
    }
    snapshot = build_evidence_snapshot(state, "P-1", 1, **VERSIONS)
    return state, snapshot


def test_manifest_inventories_every_artifact_without_legacy_collection_caps() -> None:
    from libs.review_evidence import build_evidence_manifest

    state, snapshot = _manifest_state(
        field_count=95,
        table_count=24,
        seal_count=23,
        fragment_count=130,
        evidence_link_count=90,
    )

    manifest = build_evidence_manifest(state, snapshot)

    assert manifest["counts"] == {
        "fields": 95,
        "tables": 24,
        "seals": 23,
        "fragments": 130,
        "evidenceLinks": 90,
        "total": 362,
    }
    assert len(manifest["artifacts"]) == 362


def test_manifest_preserves_every_table_row_and_cell() -> None:
    from libs.review_evidence import build_evidence_manifest

    state, snapshot = _manifest_state(table_count=1)
    table = state["ocr_parse_results"][0]["tables"][0]
    table["rows"] = [{"row": index, "value": f"value-{index}"} for index in range(75)]
    table["cells"] = [
        {"rowIndex": index // 5, "columnIndex": index % 5, "text": f"cell-{index}"}
        for index in range(205)
    ]

    manifest = build_evidence_manifest(state, snapshot)

    artifact = next(row for row in manifest["artifacts"] if row["artifactType"] == "table")
    assert len(artifact["payload"]["rows"]) == 75
    assert len(artifact["payload"]["cells"]) == 205
    assert artifact["payload"]["rows"][-1]["value"] == "value-74"
    assert artifact["payload"]["cells"][-1]["text"] == "cell-204"


def test_manifest_excludes_artifacts_from_versions_outside_the_snapshot() -> None:
    from libs.review_evidence import build_evidence_manifest

    state, snapshot = _manifest_state(field_count=1, fragment_count=1)
    state["extracted_fields"].append(
        {"id": "FIELD-OTHER", "documentVersionId": "DV-OTHER", "fieldValue": "outside"}
    )
    state["evidence_links"].append(
        {"id": "EV-OTHER", "documentVersionId": "DV-OTHER", "quotedText": "outside"}
    )

    manifest = build_evidence_manifest(state, snapshot)

    assert {row["documentVersionId"] for row in manifest["artifacts"]} == {"DV-1"}
    assert manifest["counts"]["total"] == 2


def test_manifest_ids_and_hashes_are_stable_for_the_same_snapshot() -> None:
    from libs.review_evidence import build_evidence_manifest

    state, snapshot = _manifest_state(field_count=2, fragment_count=2)

    first = build_evidence_manifest(state, snapshot)
    second = build_evidence_manifest(state, snapshot)

    assert first["evidenceManifestId"] == second["evidenceManifestId"]
    assert first["manifestHash"] == second["manifestHash"]
    assert [row["artifactId"] for row in first["artifacts"]] == [
        row["artifactId"] for row in second["artifacts"]
    ]
