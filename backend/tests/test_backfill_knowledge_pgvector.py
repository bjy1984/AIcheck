from __future__ import annotations

import json

import pytest

from scripts.backfill_knowledge_pgvector import (
    canonical_digest,
    prepare_row,
    vector_literal,
)


def vector_payload(values):
    return {
        "id": "KV-1",
        "fileId": "KF-1",
        "chunkId": "CHK-1",
        "documentId": "KDOC-1",
        "documentVersionId": "KDV-1",
        "sourceId": "KS-STANDARD-RULES",
        "embedding": values,
        "dimensions": len(values),
        "embeddingModel": "Qwen/Qwen3-Embedding-0.6B",
        "indexVersion": "knowledge-index-qwen3-0.6b@1024",
        "pageNo": 1,
    }


def test_vector_literal_validates_and_records_norm() -> None:
    literal, norm = vector_literal([0.6, 0.8], dimensions=2)

    assert literal == "[0.59999999999999998,0.80000000000000004]"
    assert norm == pytest.approx(1.0)


@pytest.mark.parametrize(
    "values",
    [
        [1.0],
        [0.0, 0.0],
        [float("nan"), 1.0],
        ["invalid", 1.0],
    ],
)
def test_vector_literal_rejects_invalid_vectors(values) -> None:
    with pytest.raises(ValueError):
        vector_literal(values, dimensions=2)


def test_prepare_row_keeps_metadata_without_duplicate_embedding() -> None:
    payload = vector_payload([0.6, 0.8])

    prepared = prepare_row("KV-1", payload, dimensions=2)
    metadata = json.loads(prepared["metadata"])

    assert prepared["source_id"] == "KS-STANDARD-RULES"
    assert prepared["chunk_id"] == "CHK-1"
    assert prepared["norm"] == pytest.approx(1.0)
    assert "embedding" not in metadata
    assert metadata["pageNo"] == 1


def test_canonical_digest_is_order_independent() -> None:
    first = [("KV-2", vector_payload([0.0, 1.0])), ("KV-1", vector_payload([1.0, 0.0]))]
    second = list(reversed(first))

    assert canonical_digest(first) == canonical_digest(second)
