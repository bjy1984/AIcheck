from __future__ import annotations


VERSIONS = {
    "rule_version": "rule-v1",
    "clause_package_version": "clauses-v1",
    "prompt_version": "prompt-v1",
    "strategy_version": "strategy-v1",
}


def _document(document_id: str, version_id: str) -> dict:
    return {
        "id": document_id,
        "projectId": "P-1",
        "currentVersionId": version_id,
    }


def _version(document_id: str, version_id: str) -> dict:
    return {
        "id": version_id,
        "documentId": document_id,
        "contentHash": f"sha256:{version_id.lower()}",
    }


def _link(
    document_id: str,
    version_id: str,
    *,
    manual_status: str = "confirmed",
    revision: int = 1,
) -> dict:
    return {
        "id": f"NEL-{version_id}",
        "projectId": "P-1",
        "nodeId": 1,
        "documentId": document_id,
        "documentVersionId": version_id,
        "manualStatus": manual_status,
        "revision": revision,
    }


def _parse_result(version_id: str, suffix: str = "v1") -> dict:
    return {
        "id": f"OCR-{version_id}",
        "parseResultId": f"OCR-{version_id}",
        "documentVersionId": version_id,
        "artifactHash": f"sha256:ocr-{version_id.lower()}-{suffix}",
        "status": "success",
    }


def _state(*rows: tuple[str, str]) -> dict:
    documents = [_document(document_id, version_id) for document_id, version_id in rows]
    versions = [_version(document_id, version_id) for document_id, version_id in rows]
    return {
        "documents": documents,
        "document_versions": versions,
        "versions": versions,
        "node_evidence_links": [_link(document_id, version_id) for document_id, version_id in rows],
        "ocr_parse_results": [_parse_result(version_id) for _, version_id in rows],
    }


def _build_snapshot(state: dict) -> dict:
    from libs.review_evidence import build_evidence_snapshot

    return build_evidence_snapshot(state, "P-1", 1, **VERSIONS)


def test_snapshot_contains_every_current_document_mounted_across_separate_uploads() -> None:
    state = _state(
        ("DOC-LICENSE", "DV-LICENSE-V1"),
        ("DOC-DRAWING", "DV-DRAWING-V1"),
        ("DOC-SEAL", "DV-SEAL-V1"),
    )

    snapshot = _build_snapshot(state)

    assert [row["documentVersionId"] for row in snapshot["documentVersions"]] == [
        "DV-DRAWING-V1",
        "DV-LICENSE-V1",
        "DV-SEAL-V1",
    ]
    assert snapshot["documentVersionCount"] == 3


def test_new_version_replaces_old_active_version_but_history_remains_in_state() -> None:
    state = _state(("DOC-LICENSE", "DV-LICENSE-V2"))
    state["document_versions"].insert(0, _version("DOC-LICENSE", "DV-LICENSE-V1"))
    state["versions"] = state["document_versions"]
    state["node_evidence_links"].insert(0, _link("DOC-LICENSE", "DV-LICENSE-V1"))
    state["ocr_parse_results"].insert(0, _parse_result("DV-LICENSE-V1"))

    snapshot = _build_snapshot(state)

    assert [row["documentVersionId"] for row in snapshot["documentVersions"]] == [
        "DV-LICENSE-V2"
    ]
    assert {row["id"] for row in state["document_versions"]} == {
        "DV-LICENSE-V1",
        "DV-LICENSE-V2",
    }


def test_rejected_and_unmounted_links_do_not_enter_the_active_snapshot() -> None:
    state = _state(("DOC-REJECTED", "DV-REJECTED-V1"), ("DOC-ACTIVE", "DV-ACTIVE-V1"))
    state["node_evidence_links"][0]["manualStatus"] = "rejected"
    state["node_evidence_links"].append(
        {
            **_link("DOC-OTHER", "DV-OTHER-V1"),
            "projectId": "P-2",
        }
    )

    snapshot = _build_snapshot(state)

    assert [row["documentVersionId"] for row in snapshot["documentVersions"]] == [
        "DV-ACTIVE-V1"
    ]


def test_snapshot_hash_changes_when_later_upload_changes_the_cumulative_input() -> None:
    first_state = _state(("DOC-LICENSE", "DV-LICENSE-V1"))
    second_state = _state(
        ("DOC-LICENSE", "DV-LICENSE-V1"),
        ("DOC-DRAWING", "DV-DRAWING-V1"),
    )

    first = _build_snapshot(first_state)
    second = _build_snapshot(second_state)

    assert first["snapshotHash"] != second["snapshotHash"]
    assert first["evidenceSnapshotId"] != second["evidenceSnapshotId"]


def test_snapshot_hash_changes_when_ocr_output_changes_for_the_same_document_version() -> None:
    state_before = _state(("DOC-LICENSE", "DV-LICENSE-V1"))
    state_after = _state(("DOC-LICENSE", "DV-LICENSE-V1"))
    state_after["ocr_parse_results"][0] = _parse_result("DV-LICENSE-V1", suffix="v2")

    before = _build_snapshot(state_before)
    after = _build_snapshot(state_after)

    assert before["snapshotHash"] != after["snapshotHash"]
