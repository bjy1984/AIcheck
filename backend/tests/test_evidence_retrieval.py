from __future__ import annotations

import pytest
from starlette.responses import JSONResponse

from libs import evidence_retrieval, knowledge_retrieval
from libs.db.repository import InMemoryRepository
from libs.evidence_retrieval import search_project_evidence
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

    def execute(self, query: str, params: tuple[object, ...]) -> RecordingCursor:
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


def evidence_repository(
    *,
    chunk_bbox: list[float] | tuple[float, float, float, float] | None = (
        10.0,
        20.0,
        110.0,
        60.0,
    ),
    two_chunks: bool = False,
) -> InMemoryRepository:
    repository = InMemoryRepository()
    repository.state["documents"] = [
        {"id": "DOC-P1", "projectId": "P-1", "status": "有效"},
        {"id": "DOC-P2", "projectId": "P-2", "status": "有效"},
    ]
    repository.state["versions"] = [
        {"id": "DV-P1", "documentId": "DOC-P1"},
        {"id": "DV-P1-OLD", "documentId": "DOC-P1"},
        {"id": "DV-P2", "documentId": "DOC-P2"},
    ]
    repository.state["knowledge_files"] = [
        {
            "id": "KF-P1",
            "sourceId": "KS-PROJECT-FILE",
            "projectId": "P-1",
            "documentId": "DOC-P1",
            "documentVersionId": "DV-P1",
            "fileName": "设计许可证.pdf",
        },
        {
            "id": "KF-P1-OLD",
            "sourceId": "KS-PROJECT-FILE",
            "projectId": "P-1",
            "documentId": "DOC-P1",
            "documentVersionId": "DV-P1-OLD",
            "fileName": "旧许可证.pdf",
        },
        {
            "id": "KF-P2",
            "sourceId": "KS-PROJECT-FILE",
            "projectId": "P-2",
            "documentId": "DOC-P2",
            "documentVersionId": "DV-P2",
            "fileName": "其他项目许可证.pdf",
        },
    ]
    repository.state["knowledge_chunks"] = [
        {
            "id": "CHK-BM25",
            "fileId": "KF-P1",
            "documentVersionId": "DV-P1",
            "pageNo": 3,
            "bbox": chunk_bbox,
            "sectionPath": ["资质证照"],
            "text": "许可证有效期至 2028-12-31",
        },
        {
            "id": "CHK-OLD",
            "fileId": "KF-P1-OLD",
            "documentVersionId": "DV-P1-OLD",
            "pageNo": 2,
            "bbox": [10.0, 20.0, 110.0, 60.0],
            "text": "许可证有效期至 2020-01-01",
        },
        {
            "id": "CHK-P2",
            "fileId": "KF-P2",
            "documentVersionId": "DV-P2",
            "pageNo": 4,
            "bbox": [10.0, 20.0, 110.0, 60.0],
            "text": "许可证有效期至 2035-01-01",
        },
    ]
    if two_chunks:
        repository.state["knowledge_chunks"].append(
            {
                "id": "CHK-DENSE",
                "fileId": "KF-P1",
                "documentVersionId": "DV-P1",
                "pageNo": 8,
                "bbox": [20.0, 30.0, 120.0, 70.0],
                "sectionPath": ["焊接记录"],
                "text": "焊缝外观检查记录完整",
            }
        )
    repository.state["knowledge_vectors"] = []
    repository.state["retrieval_traces"] = []
    return repository


def test_evidence_bm25_is_project_and_version_scoped() -> None:
    """Removing repository-backed scope checks must expose another version/project."""
    repository = evidence_repository()

    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=["DV-P1"],
        query="许可证 有效期",
    )

    assert {item["documentVersionId"] for item in result["allCandidates"]} == {"DV-P1"}
    assert result["formalCandidates"][0]["quotedText"] == "许可证有效期至 2028-12-31"
    assert result["trace"]["queryType"] == "material_evidence_search"


def test_evidence_without_bbox_is_advisory() -> None:
    """Treating a missing locator as formal evidence must fail this classification."""
    repository = evidence_repository(chunk_bbox=None)
    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=["DV-P1"],
        query="许可证",
    )

    assert result["formalCandidates"] == []
    assert result["advisoryCandidates"][0]["rejectionReasons"] == ["missing_bbox"]


@pytest.mark.parametrize(
    "bbox",
    [
        [float("nan"), 20.0, 110.0, 60.0],
        [10.0, 20.0, float("inf"), 60.0],
        [float("-inf"), 20.0, 110.0, 60.0],
    ],
    ids=["nan", "positive-infinity", "negative-infinity"],
)
def test_evidence_non_finite_bbox_is_advisory(bbox: list[float]) -> None:
    """Accepting any non-finite coordinate must expose it as formal evidence."""
    repository = evidence_repository(chunk_bbox=bbox)

    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=["DV-P1"],
        query="许可证",
    )

    assert result["formalCandidates"] == []
    assert result["advisoryCandidates"][0]["formalEvidenceEligible"] is False
    assert result["advisoryCandidates"][0]["rejectionReasons"] == ["invalid_bbox"]
    assert JSONResponse(result).status_code == 200


def test_evidence_finite_positive_bbox_remains_formal() -> None:
    """Rejecting finite positive-area coordinates must demote valid evidence."""
    repository = evidence_repository(chunk_bbox=[10.0, 20.0, 110.0, 60.0])

    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=["DV-P1"],
        query="许可证",
    )

    assert result["advisoryCandidates"] == []
    assert result["formalCandidates"][0]["formalEvidenceEligible"] is True
    assert result["formalCandidates"][0]["rejectionReasons"] == []


def test_evidence_rrf_fuses_bm25_and_dense_rankings(monkeypatch) -> None:
    """Dropping either channel rank or the RRF sum must fail hybrid retrieval."""
    repository = evidence_repository(two_chunks=True)
    monkeypatch.setenv("AICHECK_RETRIEVAL_RRF_K", "60")
    monkeypatch.setenv("AICHECK_RETRIEVAL_DENSE_WEIGHT", "0.7")
    monkeypatch.setattr(
        evidence_retrieval,
        "dense_knowledge_hits",
        lambda *args, **kwargs: (
            [{"chunkId": "CHK-DENSE", "documentVersionId": "DV-P1"}],
            {"status": "ok", "denseDegraded": False, "hitCount": 1},
        ),
    )

    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=["DV-P1"],
        query="许可证 有效期",
    )

    candidates = {item["chunkId"]: item for item in result["allCandidates"]}
    assert candidates["CHK-BM25"]["bm25Rank"] == 1
    assert candidates["CHK-DENSE"]["denseRank"] == 1
    assert candidates["CHK-BM25"]["fusedScore"] == round(1 / 61, 8)
    assert candidates["CHK-DENSE"]["fusedScore"] == round((1 / 62) + (0.7 / 61), 8)
    assert [item["chunkId"] for item in result["allCandidates"]] == ["CHK-DENSE", "CHK-BM25"]
    assert result["trace"]["fusion"]["method"] == "rrf"


def test_evidence_dense_exception_degrades_to_bm25(monkeypatch) -> None:
    """Letting a Dense exception discard lexical evidence must fail this fallback."""
    repository = evidence_repository()

    def fail_dense(*args, **kwargs):
        raise RuntimeError("vector store unavailable")

    monkeypatch.setattr(evidence_retrieval, "dense_knowledge_hits", fail_dense)
    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=["DV-P1"],
        query="许可证 有效期",
    )

    assert [item["chunkId"] for item in result["allCandidates"]] == ["CHK-BM25"]
    assert result["trace"]["denseRetrieval"]["denseDegraded"] is True
    assert result["degraded"] is True


def test_evidence_empty_version_scope_returns_no_live_candidates() -> None:
    """Treating an empty allowlist as no filter must expose repository evidence."""
    repository = evidence_repository()
    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=[],
        query="许可证",
    )

    assert result["allCandidates"] == []
    assert result["formalCandidates"] == []
    assert result["advisoryCandidates"] == []
    assert result["degraded"] is True
    assert result["fallbackReason"] == "empty_version_scope"


def test_evidence_no_channel_hit_returns_no_arbitrary_candidate(monkeypatch) -> None:
    """Reintroducing a candidates[0] fallback must return an unrelated chunk."""
    repository = evidence_repository()
    monkeypatch.setattr(
        evidence_retrieval,
        "dense_knowledge_hits",
        lambda *args, **kwargs: (
            [],
            {"status": "ok", "denseDegraded": False, "hitCount": 0},
        ),
    )
    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=["DV-P1"],
        query="unmatched-query-token",
    )

    assert result["allCandidates"] == []


def test_evidence_dense_hits_are_intersected_with_project_scope(monkeypatch) -> None:
    """Trusting vector payload scope must expose a cross-project Dense hit."""
    repository = evidence_repository()
    monkeypatch.setattr(
        evidence_retrieval,
        "dense_knowledge_hits",
        lambda *args, **kwargs: (
            [{"chunkId": "CHK-P2", "documentVersionId": "DV-P2"}],
            {"status": "ok", "denseDegraded": False, "hitCount": 1},
        ),
    )
    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=["DV-P1"],
        query="unmatched-query-token",
    )

    assert result["allCandidates"] == []
    assert result["trace"]["denseRetrieval"]["candidateCount"] == 0


def test_evidence_empty_query_uses_deterministic_node_query(monkeypatch) -> None:
    """Passing a blank query through unchanged must lose relevant lexical evidence."""
    repository = evidence_repository()
    repository.state["knowledge_chunks"][0]["text"] = "节点 1 材料证据摘要"
    monkeypatch.setattr(
        evidence_retrieval,
        "dense_knowledge_hits",
        lambda *args, **kwargs: (
            [],
            {"status": "ok", "denseDegraded": False, "hitCount": 0},
        ),
    )

    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=["DV-P1"],
        query="  ",
    )

    assert [item["chunkId"] for item in result["allCandidates"]] == ["CHK-BM25"]
    assert result["trace"]["query"] == "节点 1 材料证据"


def test_evidence_trace_persistence_failure_keeps_candidates(monkeypatch) -> None:
    """Propagating a trace append error must discard otherwise valid retrieval."""

    class FailingTraceList(list):
        def append(self, item) -> None:
            raise RuntimeError("trace store unavailable")

    repository = evidence_repository()
    repository.state["retrieval_traces"] = FailingTraceList()
    monkeypatch.setattr(
        evidence_retrieval,
        "dense_knowledge_hits",
        lambda *args, **kwargs: (
            [],
            {"status": "ok", "denseDegraded": False, "hitCount": 0},
        ),
    )

    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=["DV-P1"],
        query="许可证",
    )

    assert [item["chunkId"] for item in result["allCandidates"]] == ["CHK-BM25"]
    assert result["trace"]["persistence"] == {
        "status": "degraded",
        "reason": "trace_persistence_failed",
        "errorType": "RuntimeError",
    }


def test_evidence_generic_file_source_does_not_replace_chunk_source() -> None:
    """Using the generic file source must make a source-less chunk look formal."""
    candidate = evidence_retrieval.normalize_evidence_candidate(
        {
            "pageNo": 1,
            "bbox": [1, 1, 2, 2],
            "text": "许可证有效",
            "_file": {
                "id": "KF-P1",
                "sourceId": "KS-PROJECT-FILE",
                "fileName": "许可证.pdf",
            },
            "_document": {"id": "DOC-P1"},
            "_version": {"id": "DV-P1"},
        },
        project_id="P-1",
    )

    assert candidate["formalEvidenceEligible"] is False
    assert candidate["rejectionReasons"] == ["missing_source_identifier"]


def test_evidence_trace_has_stable_tenant_and_dense_diagnostics(monkeypatch) -> None:
    """Hard-coded null tenant or missing dense keys must break trace consumers."""
    repository = evidence_repository()
    monkeypatch.setenv("AICHECK_TENANT_ID", "TENANT-EVIDENCE")

    def fail_dense(*args, **kwargs):
        raise RuntimeError("vector store unavailable")

    monkeypatch.setattr(evidence_retrieval, "dense_knowledge_hits", fail_dense)
    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=["DV-P1"],
        query="许可证",
    )

    assert result["trace"]["tenantId"] == "TENANT-EVIDENCE"
    assert result["trace"]["filters"]["tenantId"] == "TENANT-EVIDENCE"
    assert result["trace"]["denseRetrieval"]["embeddingModel"] is None
    assert result["trace"]["denseRetrieval"]["indexVersion"] is None


def test_evidence_withdrawn_document_is_excluded() -> None:
    """Ignoring canonical fileStatus must expose withdrawn document evidence."""
    repository = evidence_repository()
    repository.state["documents"][0]["fileStatus"] = "已撤回"

    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=["DV-P1"],
        query="许可证",
    )

    assert result["allCandidates"] == []


def test_evidence_void_document_is_excluded() -> None:
    """Ignoring canonical fileStatus must expose void document evidence."""
    repository = evidence_repository()
    repository.state["documents"][0]["fileStatus"] = "已作废"

    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=["DV-P1"],
        query="许可证",
    )

    assert result["allCandidates"] == []


def search_evidence_without_jieba(
    monkeypatch,
    repository: InMemoryRepository,
    *,
    query: str,
) -> dict:
    monkeypatch.setattr(knowledge_retrieval, "_jieba_module", lambda: None)
    monkeypatch.setattr(
        evidence_retrieval,
        "dense_knowledge_hits",
        lambda *args, **kwargs: (
            [],
            {"status": "ok", "denseDegraded": False, "hitCount": 0},
        ),
    )
    knowledge_retrieval.lexical_terms.cache_clear()
    try:
        return search_project_evidence(
            repository,
            project_id="P-1",
            node_id=1,
            document_version_ids=["DV-P1"],
            query=query,
        )
    finally:
        knowledge_retrieval.lexical_terms.cache_clear()


def test_evidence_no_jieba_matches_punctuated_standard_number(monkeypatch) -> None:
    """Normalizing only the query must lose an exact GB/T standard match."""
    repository = evidence_repository()
    repository.state["knowledge_files"][0]["fileName"] = "GB/T 3087-2022.pdf"
    repository.state["knowledge_chunks"][0]["text"] = "检验依据 GB/T 3087-2022"

    result = search_evidence_without_jieba(
        monkeypatch,
        repository,
        query="GB/T 3087-2022",
    )

    assert [item["chunkId"] for item in result["allCandidates"]] == ["CHK-BM25"]


def test_evidence_no_jieba_matches_hyphenated_path(monkeypatch) -> None:
    """Normalizing only the query must lose an exact path/file-name match."""
    repository = evidence_repository()
    repository.state["knowledge_files"][0]["fileName"] = "docs/license-v2.pdf"
    repository.state["knowledge_chunks"][0]["text"] = "归档路径 docs/license-v2.pdf"

    result = search_evidence_without_jieba(
        monkeypatch,
        repository,
        query="docs/license-v2.pdf",
    )

    assert [item["chunkId"] for item in result["allCandidates"]] == ["CHK-BM25"]
