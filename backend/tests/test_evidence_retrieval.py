from __future__ import annotations

from libs.db.repository import InMemoryRepository
from libs.knowledge_dense import dense_knowledge_hits


def vector_row(vector_id: str, document_version_id: str, embedding: list[float]) -> dict:
    return {
        "id": vector_id,
        "documentVersionId": document_version_id,
        "embedding": embedding,
        "indexVersion": "offline-hash-v1",
    }


def test_local_dense_search_rejects_vectors_outside_version_allowlist() -> None:
    """Removing the local version filter must expose blocked vector rows."""
    repository = InMemoryRepository()
    repository.state["knowledge_vectors"] = [
        vector_row("KV-ALLOWED", "DV-ALLOWED", [1.0, 0.0]),
        vector_row("KV-BLOCKED", "DV-BLOCKED", [1.0, 0.0]),
    ]

    hits = repository.search_local_knowledge_vectors(
        [1.0, 0.0],
        document_version_ids=["DV-ALLOWED"],
    )

    assert [item["documentVersionId"] for item in hits] == ["DV-ALLOWED"]


class RecordingCursor:
    def __init__(self) -> None:
        self.query = ""
        self.params: tuple[object, ...] = ()

    def execute(self, query: str, params: tuple[object, ...]) -> "RecordingCursor":
        self.query = query
        self.params = params
        return self

    def fetchall(self) -> list[tuple[object, ...]]:
        return []


def test_postgres_dense_search_binds_document_version_allowlist(monkeypatch) -> None:
    """Removing the PostgreSQL allowlist predicate must return all version rows."""
    repository = InMemoryRepository()
    cursor = RecordingCursor()
    repository.sync_postgres = cursor
    monkeypatch.setattr(repository, "configure_sync_postgres", lambda: None)
    monkeypatch.setattr(repository, "ensure_pgvector_schema", lambda *args: True)

    repository.search_knowledge_vectors(
        [1.0] * 1024,
        document_version_ids=["DV-BLOCKED", "DV-ALLOWED", "DV-ALLOWED"],
    )

    assert "document_version_id = ANY(%s)" in cursor.query
    assert ["DV-ALLOWED", "DV-BLOCKED"] in cursor.params


def test_dense_knowledge_hits_forwards_document_version_allowlist(monkeypatch) -> None:
    """Removing dense forwarding must prevent a version-scoped local hit."""
    monkeypatch.setenv("AICHECK_EMBEDDING_FORCE_OFFLINE_HASH", "1")

    class VersionScopedRepository:
        postgres_enabled = False
        sync_postgres = None

        def search_local_knowledge_vectors(self, embedding, **kwargs):
            if kwargs.get("document_version_ids") == ["DV-ALLOWED"]:
                return [{"documentVersionId": "DV-ALLOWED"}]
            return []

    hits, _ = dense_knowledge_hits(
        VersionScopedRepository(),
        "version-scoped evidence",
        document_version_ids=["DV-ALLOWED"],
    )

    assert [item["documentVersionId"] for item in hits] == ["DV-ALLOWED"]
