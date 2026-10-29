"""检索标签如实、PageIndex 路由默认关闭。

2026-10-29 生产审计：检索轨迹里 180 个选中结果全标 hybrid_bm25_dense_local，没有
一个用到向量；PageIndex 路由在审查里从未被正确触发，每次检索却都要把 5469 个节点
归一化一遍、把整张延迟集合拉进内存。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api import main
from libs import knowledge_readiness
from libs.db.repository import repo
from libs.knowledge_indexing import build_page_index_nodes_for_source, clause_from_chunk
from libs.knowledge_retrieval import (
    LEXICAL_RETRIEVAL_MODE,
    classify_retrieval_route,
    query_tokens,
    retrieve_knowledge_clauses,
)

PAGEINDEX_QUESTION = "请结合正文和附录跨章节说明无损检测报告签章要求"


class _Untouchable(list):
    """路由关闭时不许读节点：任何读取都直接失败。"""

    def __iter__(self):
        raise AssertionError("PageIndex nodes were read while the route is off")

    def __len__(self):
        raise AssertionError("PageIndex nodes were read while the route is off")


def _standard_state() -> dict:
    source = {"id": "KS-STANDARD-RULES", "name": "标准规范库", "version": "inspection_kb@1.0.0",
              "sourceType": "standard", "status": "启用"}
    files = [
        {"id": "KF-RT", "sourceId": "KS-STANDARD-RULES", "fileName": "NB-T 47013.2 射线检测.pdf",
         "sourceRelativePath": "rules/standards/rt.pdf", "contextType": "standard_reference"},
        {"id": "KF-PIPE", "sourceId": "KS-STANDARD-RULES", "fileName": "GB 50235 管道施工.pdf",
         "sourceRelativePath": "rules/standards/pipe.pdf", "contextType": "standard_reference"},
    ]
    chunks = [
        {"id": f"CHK-KF-RT-{i}", "fileId": "KF-RT", "chunkNo": i, "pageNo": i, "bbox": [0, 0, 1, 1],
         "text": f"射线检测底片黑度应符合要求，第{i}段，像质计灵敏度。", "sectionPath": ["rt.pdf", f"第 {i} 页"],
         "contextType": "standard_reference", "sourceMethod": "remote_ocr"}
        for i in range(1, 9)
    ]
    chunks.append(
        {"id": "CHK-KF-PIPE-9", "fileId": "KF-PIPE", "chunkNo": 9, "pageNo": 9, "bbox": [0, 0, 1, 1],
         "text": "无损检测报告应由持证人员签字并加盖检测单位公章，附录 C 规定签章要求。",
         "sectionPath": ["pipe.pdf", "第 9 页"], "contextType": "standard_reference", "sourceMethod": "remote_ocr"}
    )
    files_by_id = {item["id"]: item for item in files}
    nodes = build_page_index_nodes_for_source(source, files, chunks)
    clauses = [clause_from_chunk(files_by_id[chunk["fileId"]], chunk, source["version"]) for chunk in chunks]
    return {"knowledge_sources": [source], "knowledge_files": files, "knowledge_chunks": chunks,
            "knowledge_clauses": clauses, "knowledge_page_index_nodes": nodes, "evidence_links": []}


def test_router_never_picks_pageindex_unless_explicitly_enabled() -> None:
    tokens = query_tokens(PAGEINDEX_QUESTION)
    assert classify_retrieval_route(PAGEINDEX_QUESTION, tokens) == "hybrid_review_basis_search"
    assert classify_retrieval_route("规" * 90, query_tokens("规" * 90)) == "hybrid_review_basis_search"
    assert classify_retrieval_route(PAGEINDEX_QUESTION, tokens, enable_pageindex=True) == "pageindex_tree_search"
    # 精确条款号仍然优先于一切
    assert classify_retrieval_route("TSG-D7006-D2.4.1 条附录", query_tokens("TSG-D7006-D2.4.1 条附录"),
                                    enable_pageindex=True) == "exact_clause_lookup"


def test_default_retrieval_does_not_touch_page_index_nodes() -> None:
    state = _standard_state()
    state["knowledge_page_index_nodes"] = _Untouchable()

    trace = retrieve_knowledge_clauses(state, query=PAGEINDEX_QUESTION, top_k=5)["trace"]

    assert trace["selectedRoute"] == "hybrid_review_basis_search"
    assert trace["routerSignals"]["needsPageIndex"] is True
    assert trace["routerSignals"]["pageIndexEnabled"] is False
    assert trace["pageIndexTree"] == {
        "enabled": False, "candidateNodeCount": None, "selectedNodes": [], "linkedClauseIds": [], "treeSearchPath": [],
    }
    pageindex_retriever = next(item for item in trace["retrievers"] if item["type"] == "pageindex_tree")
    assert pageindex_retriever["enabled"] is False


def test_default_label_is_lexical_and_dense_only_when_dense_hits() -> None:
    state = _standard_state()

    lexical = retrieve_knowledge_clauses(state, query="射线检测底片黑度", top_k=3)["trace"]
    assert {item["retrievalMode"] for item in lexical["selectedClauses"]} == {LEXICAL_RETRIEVAL_MODE}
    dense_retriever = next(item for item in lexical["retrievers"] if item["type"] == "hybrid_bm25_dense")
    assert dense_retriever["enabled"] is False and dense_retriever["denseHitCount"] == 0

    dense = retrieve_knowledge_clauses(
        state, query="射线检测底片黑度", top_k=3, dense_chunk_ids=["CHK-KF-RT-3"]
    )["trace"]
    modes = {item["clauseId"]: item["retrievalMode"] for item in dense["selectedClauses"]}
    assert modes["CHK-KF-RT-3"] == "hybrid_dense_local"
    assert {mode for clause_id, mode in modes.items() if clause_id != "CHK-KF-RT-3"} == {LEXICAL_RETRIEVAL_MODE}
    assert next(item for item in dense["retrievers"] if item["type"] == "hybrid_bm25_dense")["enabled"] is True


def test_pageindex_label_only_for_clauses_linked_through_the_tree() -> None:
    state = _standard_state()

    trace = retrieve_knowledge_clauses(state, query=PAGEINDEX_QUESTION, top_k=5, enable_pageindex=True)["trace"]

    assert trace["selectedRoute"] == "pageindex_tree_search"
    assert trace["pageIndexTree"]["enabled"] is True
    assert trace["pageIndexTree"]["candidateNodeCount"] == len(state["knowledge_page_index_nodes"])
    linked = set(trace["pageIndexTree"]["linkedClauseIds"])
    assert "CHK-KF-PIPE-9" in linked
    assert trace["selectedClauses"][0]["clauseId"] == "CHK-KF-PIPE-9"
    for item in trace["selectedClauses"]:
        # 原先只要有页码和 bbox 就标 pageindex_tree_local，整库都会被标成 PageIndex 命中
        expected = "pageindex_tree_local" if item["clauseId"] in linked else LEXICAL_RETRIEVAL_MODE
        assert item["retrievalMode"] == expected, item["clauseId"]


def _probe(route: str, *, passed: bool = True) -> dict:
    return {"expectedRoute": route, "passed": passed, "retrieverTypes": ["hybrid_bm25_dense"],
            "selectedClauseCount": 1, "evidenceBacked": True, "pageIndexNodeCount": 0}


def test_readiness_marks_pageindex_not_applicable_without_capping_the_score() -> None:
    assert "pageindex_tree_search" not in knowledge_readiness.REQUIRED_KNOWLEDGE_ROUTES

    section = knowledge_readiness.retrieval_router_section(
        [_probe(route) for route in knowledge_readiness.REQUIRED_KNOWLEDGE_ROUTES]
    )
    assert section["score"] == section["maxScore"] == 30
    assert section["status"] == "pass"
    assert section["notApplicable"] == [
        {"route": "pageindex_tree_search", "reason": "PageIndex 路由默认关闭，不适用"}
    ]

    failed = knowledge_readiness.retrieval_router_section(
        [_probe("exact_clause_lookup"), _probe("hybrid_review_basis_search", passed=False)]
    )
    assert failed["score"] < 30
    assert failed["blockers"] == ["retrieval probe failed: hybrid_review_basis_search"]


@pytest.fixture
def isolated_repo(monkeypatch):
    repo.reset()
    monkeypatch.setattr(repo, "postgres_enabled", False)
    monkeypatch.setattr(repo, "sync_postgres", None)
    monkeypatch.setattr(repo, "postgres_dsn", None)
    monkeypatch.setattr(repo, "sqlite_enabled", False)
    monkeypatch.setattr(repo, "sqlite_path", None)


def test_retrieval_test_dense_hits_are_standard_only_and_carry_no_text(isolated_repo, monkeypatch) -> None:
    from libs.knowledge_indexing import STANDARD_INDEX_VERSION, offline_hash_embedding

    monkeypatch.setenv("AICHECK_EMBEDDING_FORCE_OFFLINE_HASH", "true")
    question = "焊工资格证有效期"
    embedding = offline_hash_embedding(question)

    def vector_row(row_id: str, source_id: str, text: str) -> dict:
        return {"id": f"KV-{row_id}", "fileId": f"KF-{row_id}", "chunkId": f"CHK-{row_id}", "sourceId": source_id,
                "embedding": embedding, "dimensions": len(embedding), "indexVersion": STANDARD_INDEX_VERSION,
                "pageNo": 3, "sectionPath": ["焊工资格"], "payload": {"text": text, "pageNo": 3}}

    repo.state["knowledge_vectors"] = [
        vector_row("STD", "KS-STANDARD-RULES", "焊工资格证有效期为四年。"),
        # GB 11643 示例号码
        vector_row("PF", "KS-PROJECT-FILE", "焊工 身份证号 11010519491231002X"),
    ]
    client = TestClient(main.app)

    data = client.post("/knowledge/retrieval-test", json={"question": question, "topK": 5}).json()["data"]

    assert [hit["chunkId"] for hit in data["denseHits"]] == ["CHK-STD"]
    hit = data["denseHits"][0]
    assert hit["pageNo"] == 3 and hit["sourceId"] == "KS-STANDARD-RULES"
    assert "metadata" not in hit and "payload" not in hit and "text" not in hit
    assert "11010519491231002X" not in repr(data)

    refused = client.post(
        "/knowledge/retrieval-test", json={"question": question, "sourceId": "KS-PROJECT-FILE"}
    ).json()
    assert refused["code"] != 0 and refused["data"]["reason"] == "VALIDATION_ERROR"


def test_inspection_standards_search_no_longer_loads_page_index_nodes(isolated_repo, monkeypatch) -> None:
    from libs.db import repository

    requested: list[str] = []
    real_loader = repository.ensure_collections_loaded

    def recording_loader(*collections):
        requested.extend(collections)
        return real_loader(*collections)

    monkeypatch.setattr(repository, "ensure_collections_loaded", recording_loader)
    response = TestClient(main.app).get("/api/inspection-services/standards", params={"keyword": "附录 签章要求"})

    assert response.status_code == 200, response.text
    assert "knowledge_page_index_nodes" not in requested
