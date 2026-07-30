from __future__ import annotations

import httpx
import pytest

import libs.integrations.reranker_client as reranker_client_module
from libs.integrations.reranker_client import RerankerClient
from libs.knowledge_dense import query_text_for_model
from libs.knowledge_indexing import (
    chunk_text,
    embedding_input_for_chunk,
    merge_small_fragments,
)
from libs.knowledge_retrieval import (
    apply_cross_encoder_rerank,
    bm25_scores_for_clauses,
    lexical_terms,
    retrieve_knowledge_clauses,
)


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


# ---------------------------------------------------------------- BM25


def test_lexical_terms_align_at_any_offset() -> None:
    terms = lexical_terms("材料牌号与炉批号")
    assert any("牌号" in term for term in terms)
    assert any("批号" in term for term in terms)


def test_bm25_downweights_common_terms_and_normalizes_length() -> None:
    common = "工程 检验 资料"
    clauses = [
        {"clauseId": "SHORT", "title": "", "text": f"{common} 蠕变强度试验要求", "tags": []},
        {"clauseId": "LONG", "title": "", "text": f"{common} 蠕变强度试验要求 " + "无关填充内容 " * 120, "tags": []},
        {"clauseId": "NOISE", "title": "", "text": f"{common} 完全无关的其他内容", "tags": []},
    ]
    scores = bm25_scores_for_clauses(clauses, "蠕变强度试验")
    assert scores.get("SHORT", 0) > scores.get("NOISE", 0)
    assert scores.get("SHORT", 0) >= scores.get("LONG", 0)


def test_retrieve_ranks_relevant_first_with_bm25() -> None:
    result = retrieve_knowledge_clauses(make_state(), query="水压试验 保压时间", top_k=3)
    assert result["clauses"][0]["clauseId"] == "CHK-B"
    assert result["clauses"][0]["bm25Score"] > 0
    retriever = next(item for item in result["trace"]["retrievers"] if item["type"] == "hybrid_bm25_dense")
    assert retriever["lexicalScoring"] == "okapi_bm25_jieba_or_ngram"


# ---------------------------------------------------------------- reranker client


def test_reranker_client_parses_infinity_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rerank"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.92},
                    {"index": 0, "relevance_score": 0.11},
                ]
            },
        )

    client = RerankerClient(base_url="http://reranker.test", transport=httpx.MockTransport(handler))
    results = client.rerank("查询", ["文档甲", "文档乙"])
    assert results[0] == {"index": 1, "relevanceScore": 0.92}
    assert results[1] == {"index": 0, "relevanceScore": 0.11}


def test_reranker_client_disabled_without_base_url(monkeypatch) -> None:
    monkeypatch.delenv("AICHECK_RERANK_API_BASE", raising=False)
    monkeypatch.delenv("AICHECK_RERANK_BASE_URL", raising=False)
    client = RerankerClient()
    assert client.enabled is False
    with pytest.raises(RuntimeError):
        client.rerank("q", ["doc"])


# ---------------------------------------------------------------- rerank integration


def _scored() -> list[dict]:
    return [
        {"clauseId": "A", "title": "甲", "text": "文本甲", "retrievalMode": "hybrid_bm25_dense_local", "fusedScore": 0.03},
        {"clauseId": "B", "title": "乙", "text": "文本乙", "retrievalMode": "hybrid_bm25_dense_local", "fusedScore": 0.02},
    ]


def test_rerank_reorders_with_configured_client(monkeypatch) -> None:
    class FakeClient:
        model_id = "fake-reranker"
        enabled = True

        def __init__(self, *args, **kwargs) -> None:
            pass

        def rerank(self, query, documents, **kwargs):
            return [{"index": 1, "relevanceScore": 9.0}, {"index": 0, "relevanceScore": 1.0}]

    monkeypatch.setattr(reranker_client_module, "RerankerClient", FakeClient)
    scored = _scored()
    info = apply_cross_encoder_rerank({}, "q", scored, top_k=2)
    assert info["applied"] is True
    assert scored[0]["clauseId"] == "B"
    assert scored[0]["rerankScore"] == 9.0


def test_rerank_skipped_without_endpoint(monkeypatch) -> None:
    monkeypatch.delenv("AICHECK_RERANK_API_BASE", raising=False)
    monkeypatch.delenv("AICHECK_RERANK_BASE_URL", raising=False)
    scored = _scored()
    info = apply_cross_encoder_rerank({}, "q", scored, top_k=2)
    assert info["applied"] is False
    assert info["reason"] == "rerank_endpoint_not_configured"
    assert scored[0]["clauseId"] == "A"


def test_rerank_respects_config_flag() -> None:
    info = apply_cross_encoder_rerank({"knowledge_config": {"rerankEnabled": False}}, "q", _scored(), top_k=2)
    assert info["configEnabled"] is False


def test_rerank_degrades_on_client_error(monkeypatch) -> None:
    class BrokenClient:
        model_id = "broken"
        enabled = True

        def __init__(self, *args, **kwargs) -> None:
            pass

        def rerank(self, query, documents, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(reranker_client_module, "RerankerClient", BrokenClient)
    scored = _scored()
    info = apply_cross_encoder_rerank({}, "q", scored, top_k=2)
    assert info["status"] == "degraded"
    assert scored[0]["clauseId"] == "A"


def test_trace_contains_rerank_block() -> None:
    result = retrieve_knowledge_clauses(make_state(), query="焊工资格证有效期", top_k=3)
    assert "rerank" in result["trace"]
    assert "cross_encoder_rerank" in [item.get("type") for item in result["trace"]["retrievers"]]


# ---------------------------------------------------------------- chunking


def test_chunk_text_overlap_carries_sentence_tail() -> None:
    sentences = [f"第{i}句：本条给出压力试验的第{i}项要求，保压时间与压力等级应符合规定。" for i in range(1, 80)]
    text = "".join(sentences)
    pieces = chunk_text(text, 600, overlap_chars=120)
    assert len(pieces) > 2
    for left, right in zip(pieces, pieces[1:]):
        first_line = right.split("\n", 1)[0]
        assert first_line in left
    joined = "".join(pieces)
    for sentence in sentences:
        assert sentence in joined


def test_merge_small_fragments_merges_lines_and_unions_bbox() -> None:
    units = [
        {"pageNo": 1, "text": "焊缝外观检查", "bbox": [0, 0, 100, 10], "ocrConfidence": 0.98},
        {"pageNo": 1, "text": "不得有裂纹和未熔合", "bbox": [0, 12, 100, 22], "ocrConfidence": 0.91},
        {"pageNo": 2, "text": "另一页内容", "bbox": [0, 0, 50, 10]},
    ]
    merged = merge_small_fragments(units, min_chars=280)
    assert len(merged) == 2
    assert merged[0]["text"] == "焊缝外观检查\n不得有裂纹和未熔合"
    assert merged[0]["bbox"] == [0, 0, 100, 22]
    assert merged[0]["ocrConfidence"] == 0.91
    assert merged[1]["pageNo"] == 2


def test_merge_small_fragments_respects_headings() -> None:
    units = [
        {"pageNo": 1, "text": "前言内容"},
        {"pageNo": 1, "text": "3.2 技术要求"},
    ]
    assert len(merge_small_fragments(units, min_chars=280)) == 2


def test_embedding_input_prefixes_section_path(monkeypatch) -> None:
    monkeypatch.delenv("AICHECK_EMBEDDING_CONTEXT_PREFIX", raising=False)
    chunk = {"text": "表面质量要求……", "sectionPath": ["GBT5310.pdf", "6.4 表面质量"]}
    assert embedding_input_for_chunk(chunk) == "GBT5310.pdf / 6.4 表面质量\n表面质量要求……"
    monkeypatch.setenv("AICHECK_EMBEDDING_CONTEXT_PREFIX", "false")
    assert embedding_input_for_chunk(chunk) == "表面质量要求……"


# ---------------------------------------------------------------- query instruction


def test_qwen_query_gets_instruction(monkeypatch) -> None:
    monkeypatch.delenv("AICHECK_EMBEDDING_QUERY_INSTRUCTION", raising=False)
    text = query_text_for_model("焊工资格证有效期", "Qwen/Qwen3-Embedding-0.6B")
    assert text.startswith("Instruct: ")
    assert text.endswith("Query: 焊工资格证有效期")


def test_non_qwen_query_unchanged() -> None:
    assert query_text_for_model("q", "BAAI/bge-m3") == "q"


def test_query_instruction_disabled_by_env(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_EMBEDDING_QUERY_INSTRUCTION", "false")
    assert query_text_for_model("q", "Qwen/Qwen3-Embedding-0.6B") == "q"


# ---------------------------------------------------------------- pgvector tables


def test_pgvector_table_name_per_dimension() -> None:
    from libs.db.repository import pgvector_table_for_dimensions

    assert pgvector_table_for_dimensions(1024) == "knowledge_vector_index"
    assert pgvector_table_for_dimensions(2560) == "knowledge_vector_index_2560"
    assert pgvector_table_for_dimensions(4096) == "knowledge_vector_index_4096"
