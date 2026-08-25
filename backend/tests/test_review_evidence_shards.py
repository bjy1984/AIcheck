from __future__ import annotations


def _artifact(index: int, *, payload: dict | None = None) -> dict:
    return {
        "artifactId": f"EART-{index:04d}",
        "artifactType": "fragment",
        "documentVersionId": "DV-1",
        "sourceId": f"FRAGMENT-{index:04d}",
        "payload": payload or {"pageNo": index, "text": f"evidence-{index}"},
        "contentHash": f"sha256:{index:064d}",
    }


def _manifest(artifacts: list[dict]) -> dict:
    return {
        "evidenceManifestId": "EMAN-1",
        "evidenceSnapshotId": "ESNAP-1",
        "projectId": "P-1",
        "nodeId": 1,
        "artifacts": artifacts,
        "counts": {"total": len(artifacts)},
        "manifestHash": "sha256:manifest",
    }


def test_sharding_changes_call_count_without_dropping_or_duplicating_artifacts() -> None:
    from libs.review_evidence import build_evidence_shards, evidence_coverage_report

    manifest = _manifest([_artifact(index) for index in range(1, 251)])

    shards = build_evidence_shards(manifest, max_shard_estimated_tokens=500)
    report = evidence_coverage_report(manifest, shards)

    assert len(shards) > 1
    assert report["expectedArtifactCount"] == 250
    assert report["processedArtifactCount"] == 250
    assert report["missingArtifactIds"] == []
    assert report["duplicateArtifactIds"] == []
    assert report["coveragePassed"] is True


def test_oversized_table_is_split_by_rows_and_cells_without_loss() -> None:
    from libs.review_evidence import build_evidence_shards, evidence_coverage_report

    rows = [{"row": index, "value": f"row-value-{index}"} for index in range(150)]
    cells = [
        {"rowIndex": index // 5, "columnIndex": index % 5, "text": f"cell-{index}"}
        for index in range(205)
    ]
    table = {
        **_artifact(1),
        "artifactType": "table",
        "sourceId": "TABLE-1",
        "payload": {
            "id": "TABLE-1",
            "pageNo": 1,
            "tableName": "制造许可范围",
            "rows": rows,
            "cells": cells,
        },
    }
    manifest = _manifest([table])

    shards = build_evidence_shards(manifest, max_shard_estimated_tokens=450)
    segments = [
        segment
        for shard in shards
        for segment in shard["artifactSegments"]
        if segment["artifactId"] == "EART-0001"
    ]
    reconstructed_rows = [
        row
        for segment in sorted(segments, key=lambda item: item["segmentIndex"])
        for row in segment["payloadSlice"].get("rows", [])
    ]
    reconstructed_cells = [
        cell
        for segment in sorted(segments, key=lambda item: item["segmentIndex"])
        for cell in segment["payloadSlice"].get("cells", [])
    ]

    assert len(segments) > 1
    assert reconstructed_rows == rows
    assert reconstructed_cells == cells
    assert evidence_coverage_report(manifest, shards)["coveragePassed"] is True


def test_oversized_fragment_text_is_split_with_reconstructable_character_ranges() -> None:
    from libs.review_evidence import build_evidence_shards

    original = "设计许可证许可范围GC1覆盖GC2。" * 600
    manifest = _manifest([_artifact(1, payload={"pageNo": 1, "text": original})])

    shards = build_evidence_shards(manifest, max_shard_estimated_tokens=300)
    segments = sorted(
        [segment for shard in shards for segment in shard["artifactSegments"]],
        key=lambda item: item["segmentIndex"],
    )

    assert len(segments) > 1
    assert "".join(segment["payloadSlice"]["text"] for segment in segments) == original
    assert segments[0]["characterRange"]["start"] == 0
    assert segments[-1]["characterRange"]["end"] == len(original)


def test_coverage_gate_detects_a_missing_segment() -> None:
    from libs.review_evidence import build_evidence_shards, evidence_coverage_report

    original = "完整OCR原文" * 800
    manifest = _manifest([_artifact(1, payload={"pageNo": 1, "text": original})])
    shards = build_evidence_shards(manifest, max_shard_estimated_tokens=250)
    shards[-1]["artifactSegments"].pop()
    shards[-1]["artifactIds"] = [
        segment["artifactId"] for segment in shards[-1]["artifactSegments"]
    ]

    report = evidence_coverage_report(manifest, shards)

    assert report["coveragePassed"] is False
    assert report["incompleteArtifactIds"] == ["EART-0001"]
