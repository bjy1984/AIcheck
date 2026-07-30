from __future__ import annotations

from libs.knowledge_dense import dense_knowledge_hits
from libs.knowledge_indexing import STANDARD_INDEX_VERSION, cosine_similarity, offline_hash_embedding
from libs.knowledge_retrieval import dense_rank_map, retrieve_knowledge_clauses, rrf_fusion_config
from libs.review_orchestrator.execution import build_review_retrieval_query


def make_state() -> dict:
    files = [
        {
            "id": "F1",
            "sourceId": "KS-STANDARD-RULES",
            "fileName": "GBT 5310 高压锅炉用无缝钢管.pdf",
            "contextType": "standard_reference",
        },
    ]
    chunks = [
        {
            "id": "CHK-A",
            "fileId": "F1",
            "pageNo": 3,
            "text": "焊工资格证有效期为四年，持证项目应覆盖对应焊接方法。",
            "sectionPath": ["标准", "6.1 焊工资格"],
            "bbox": [1, 1, 2, 2],
        },
        {
            "id": "CHK-B",
            "fileId": "F1",
            "pageNo": 9,
            "text": "水压试验压力不应低于设计压力的一点五倍，保压时间不少于十分钟。",
            "sectionPath": ["标准", "8.2 水压试验"],
            "bbox": [1, 1, 2, 2],
        },
        {
            "id": "CHK-C",
            "fileId": "F1",
            "pageNo": 12,
            "text": "材料牌号与炉批号应与质量证明书一致，复验取样应符合规定。",
            "sectionPath": ["标准", "5.3 材料复验"],
            "bbox": [1, 1, 2, 2],
        },
    ]
    return {
        "knowledge_sources": [
            {"id": "KS-STANDARD-RULES", "version": "kb@1", "status": "启用", "sourceType": "standard"}
        ],
        "knowledge_files": files,
        "knowledge_chunks": chunks,
        "knowledge_clauses": [],
        "evidence_links": [],
        "knowledge_page_index_nodes": [],
    }


class FakeRepo:
    postgres_enabled = False
    sync_postgres = None

    def __init__(self, state: dict) -> None:
        self.state = state

    def search_local_knowledge_vectors(self, embedding, *, top_k=5, source_id=None, index_version=None):
        hits = []
        for row in self.state.get("knowledge_vectors", []):
            if index_version and row.get("indexVersion") != index_version:
                continue
            score = cosine_similarity(embedding, row.get("embedding") or [])
            hits.append({"chunkId": row.get("chunkId"), "score": score})
        hits.sort(key=lambda item: item["score"], reverse=True)
        return hits[:top_k]


def test_no_dense_preserves_lexical_order() -> None:
    result = retrieve_knowledge_clauses(make_state(), query="焊工资格证有效期", top_k=3)
    clauses = result["clauses"]
    assert clauses
    assert clauses[0]["clauseId"] == "CHK-A"
    assert clauses[0]["lexicalRank"] == 1
    assert clauses[0]["denseRank"] is None
    assert "fusedScore" in clauses[0]
    assert result["trace"]["fusion"]["method"] == "rrf"
    assert result["trace"]["denseRetrieval"]["status"] == "not_provided"


def test_dense_hits_fuse_via_rrf() -> None:
    dense = [{"chunkId": "CHK-B"}, {"chunkId": "CHK-C"}]
    result = retrieve_knowledge_clauses(
        make_state(),
        query="焊工资格证有效期",
        top_k=3,
        dense_hits=dense,
        dense_meta={"status": "ok", "denseDegraded": False, "hitCount": 2},
    )
    by_id = {item["clauseId"]: item for item in result["clauses"]}
    assert by_id["CHK-B"]["denseRank"] == 1
    assert by_id["CHK-B"]["retrievalMode"] == "hybrid_dense_local"
    # RRF: dense-rank-1 may overtake near-tied lexical candidates, but the
    # lexical leader must still be selected in the top-k.
    assert "CHK-A" in [item["clauseId"] for item in result["clauses"]]
    assert result["trace"]["denseRetrieval"]["status"] == "ok"


def test_dense_only_candidate_included_despite_zero_lexical_score() -> None:
    result = retrieve_knowledge_clauses(
        make_state(),
        query="zzzz 材料牌号 炉批号",
        top_k=3,
        dense_hits=[{"chunkId": "CHK-B"}],
    )
    ids = [item["clauseId"] for item in result["clauses"]]
    assert "CHK-B" in ids
    assert "CHK-C" in ids[:2]


def test_exact_route_still_wins_over_dense() -> None:
    state = make_state()
    state["knowledge_clauses"] = [
        {
            "id": "KC-1",
            "clauseId": "CL-1",
            "clauseNo": "6.4.2",
            "kbDocId": "KS-STANDARD-RULES",
            "title": "表面质量",
            "text": "表面质量要求……",
            "pageNo": 2,
            "bbox": [1, 1, 2, 2],
            "fileId": "F1",
            "sectionPath": ["标准"],
        }
    ]
    result = retrieve_knowledge_clauses(
        state, query="6.4.2 条 表面质量", top_k=3, dense_hits=[{"chunkId": "CHK-A"}]
    )
    assert result["trace"]["selectedRoute"] == "exact_clause_lookup"
    assert result["clauses"][0]["clauseId"] == "CL-1"
    assert result["clauses"][0]["retrievalMode"] == "exact_clause_lookup"


def test_preferred_route_overrides_length_heuristic() -> None:
    long_query = "焊工资格证有效期 " + "工程检验资料审查 材料牌号 规格 材质 检验结论 " * 4
    assert len(long_query) >= 80
    hinted = retrieve_knowledge_clauses(
        make_state(), query=long_query, top_k=3, preferred_route="hybrid_review_basis_search"
    )
    assert hinted["trace"]["selectedRoute"] == "hybrid_review_basis_search"
    default = retrieve_knowledge_clauses(make_state(), query=long_query, top_k=3)
    assert default["trace"]["selectedRoute"] == "pageindex_tree_search"


def test_dense_rank_map_variants() -> None:
    assert dense_rank_map(None, ["a", "b", "a"]) == {"a": 1, "b": 2}
    assert dense_rank_map([{"chunkId": "x"}, {"chunkId": "y"}], None) == {"x": 1, "y": 2}


def test_rrf_fusion_config_defaults(monkeypatch) -> None:
    monkeypatch.delenv("AICHECK_RETRIEVAL_RRF_K", raising=False)
    monkeypatch.delenv("AICHECK_RETRIEVAL_DENSE_WEIGHT", raising=False)
    config = rrf_fusion_config()
    assert config["k"] == 60.0
    assert config["denseWeight"] == 0.7


def test_dense_helper_offline_hash_mode(monkeypatch) -> None:
    monkeypatch.delenv("AICHECK_EMBEDDING_API_BASE", raising=False)
    monkeypatch.delenv("AICHECK_EMBEDDING_BASE_URL", raising=False)
    monkeypatch.delenv("AICHECK_RETRIEVAL_DENSE_DISABLE", raising=False)
    state = {
        "knowledge_vectors": [
            {
                "chunkId": "CHK-A",
                "indexVersion": STANDARD_INDEX_VERSION,
                "embedding": offline_hash_embedding("焊工资格证有效期为四年"),
            },
            {
                "chunkId": "CHK-B",
                "indexVersion": STANDARD_INDEX_VERSION,
                "embedding": offline_hash_embedding("水压试验压力保压时间"),
            },
        ]
    }
    hits, meta = dense_knowledge_hits(FakeRepo(state), "焊工资格证有效期", top_k=2)
    assert meta["status"] == "ok"
    assert meta["denseDegraded"] is False
    assert hits[0]["chunkId"] == "CHK-A"


def test_dense_helper_remote_failure_skips_instead_of_hash_query(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_EMBEDDING_API_BASE", "http://embedding.invalid:1")
    monkeypatch.delenv("AICHECK_EMBEDDING_FORCE_OFFLINE_HASH", raising=False)
    hits, meta = dense_knowledge_hits(FakeRepo({"knowledge_vectors": []}), "任意问题", top_k=2, timeout=0.2)
    assert hits == []
    assert meta["denseDegraded"] is True
    assert meta["reason"] == "remote_embedding_unavailable_dense_skipped"


def test_dense_helper_disable_flag(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_RETRIEVAL_DENSE_DISABLE", "true")
    hits, meta = dense_knowledge_hits(FakeRepo({}), "q", top_k=2)
    assert hits == []
    assert meta["status"] == "disabled"


def test_build_review_retrieval_query_content_aware() -> None:
    context = {
        "node": {"name": "R12 焊工资格审查"},
        "currentRule": {
            "name": "焊工持证校验",
            "criteria": "持证项目覆盖焊接方法，证书在有效期内",
        },
        "fields": [
            {"fieldName": "焊工姓名", "fieldValue": "张三"},
            {"fieldName": "证书编号", "fieldValue": "HG-2024-001"},
        ],
    }
    query = build_review_retrieval_query({}, context)
    assert "R12 焊工资格审查" in query
    assert "持证项目" in query
    assert "HG-2024-001" in query
    assert len(query) <= 512
    assert build_review_retrieval_query({}, {}) == "节点 审查依据"
