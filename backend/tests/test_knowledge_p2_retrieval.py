from __future__ import annotations

from libs.knowledge_retrieval import (
    auto_alias_rules_from_state,
    page_index_tree_search,
    retrieve_knowledge_clauses,
)
from libs.review_grounding import kb_citation_related
from libs.review_orchestrator.execution import validate_review_references


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


def tree_state() -> dict:
    nodes = [
        {"pageIndexNodeId": "ROOT", "nodeId": "root", "parentNodeId": None, "title": "标准库",
         "summary": "", "children": ["FILE-1", "FILE-2"], "linkedClauseIds": [], "status": "effective"},
        {"pageIndexNodeId": "FILE-1", "nodeId": "f1", "parentNodeId": "ROOT",
         "title": "GBT 3087 低中压锅炉用无缝钢管.pdf", "summary": "锅炉管订货 尺寸 技术要求",
         "children": ["PAGE-1A"], "linkedClauseIds": [], "status": "effective"},
        {"pageIndexNodeId": "FILE-2", "nodeId": "f2", "parentNodeId": "ROOT",
         "title": "NB_T 47013 无损检测.pdf", "summary": "无损检测 通用要求 附录",
         "children": ["PAGE-2A", "PAGE-2B"], "linkedClauseIds": [], "status": "effective"},
        {"pageIndexNodeId": "PAGE-1A", "nodeId": "p1a", "parentNodeId": "FILE-1",
         "title": "锅炉管 第 3 页", "summary": "水压试验要求", "children": [],
         "linkedClauseIds": ["CHK-BOILER"], "startPage": 3, "endPage": 3, "status": "effective"},
        {"pageIndexNodeId": "PAGE-2A", "nodeId": "p2a", "parentNodeId": "FILE-2",
         "title": "无损检测 附录A", "summary": "附录A 无损检测报告签章要求", "children": [],
         "linkedClauseIds": ["CHK-NDT-1"], "startPage": 90, "endPage": 91, "status": "effective"},
        {"pageIndexNodeId": "PAGE-2B", "nodeId": "p2b", "parentNodeId": "FILE-2",
         "title": "无损检测 正文", "summary": "无损检测 通用检测比例", "children": [],
         "linkedClauseIds": ["CHK-NDT-2"], "startPage": 12, "endPage": 12, "status": "effective"},
    ]
    return {"knowledge_page_index_nodes": nodes, "knowledge_sources": []}


# ------------------------------------------------- hierarchical PageIndex


def test_pageindex_two_stage_descends_into_best_file() -> None:
    result = page_index_tree_search(tree_state(), ["无损检测", "附录"], top_k=3)
    assert result["searchStrategy"] == "hierarchical_two_stage"
    selected_ids = [item["pageIndexNodeId"] for item in result["selectedNodes"]]
    assert selected_ids
    assert "PAGE-2A" in selected_ids
    assert "ROOT" not in selected_ids
    assert "CHK-NDT-1" in result["linkedClauseIds"]
    path_ids = [item["pageIndexNodeId"] for item in result["treeSearchPath"]]
    assert "ROOT" in path_ids
    assert "FILE-2" in path_ids


def test_pageindex_flat_scan_without_hierarchy() -> None:
    state = {
        "knowledge_page_index_nodes": [
            {"pageIndexNodeId": "N1", "nodeId": "n1", "parentNodeId": None, "title": "无损检测要求",
             "summary": "", "children": [], "linkedClauseIds": ["C1"], "status": "effective"},
        ],
        "knowledge_sources": [],
    }
    result = page_index_tree_search(state, ["无损检测"], top_k=3)
    assert result["searchStrategy"] == "flat_scan"
    assert result["selectedNodes"][0]["pageIndexNodeId"] == "N1"


# ------------------------------------------------- auto-mined aliases


def test_auto_alias_rules_mined_from_file_names() -> None:
    state = {
        "knowledge_files": [
            {"id": "KF-1", "fileName": "GBT 8163-2018 输送流体用无缝钢管.pdf"},
            {"id": "KF-2", "fileName": "notes.txt"},
        ]
    }
    rules = auto_alias_rules_from_state(state)
    assert len(rules) == 1
    rule = rules[0]
    assert rule["source"] == "auto_file_name"
    assert rule["prefix"] == "GBT"
    assert rule["number"] == "8163"
    assert "输送流体用无缝钢管" in rule["phrases"]
    assert rule["boost"] == 60.0


def test_retrieval_applies_auto_alias_boost() -> None:
    state = make_state()
    state["knowledge_files"].append(
        {"id": "F2", "sourceId": "KS-STANDARD-RULES",
         "fileName": "GBT 8163-2018 输送流体用无缝钢管.pdf", "contextType": "standard_reference"}
    )
    state["knowledge_chunks"].append(
        {
            "id": "CHK-D",
            "fileId": "F2",
            "pageNo": 2,
            "text": "本标准规定了输送流体用无缝钢管的质量证明书和验收要求。",
            "sectionPath": ["GBT 8163-2018 输送流体用无缝钢管.pdf", "范围"],
            "bbox": [1, 1, 2, 2],
        }
    )
    result = retrieve_knowledge_clauses(state, query="输送流体用无缝钢管 质量证明书按什么验收", top_k=3)
    top = result["clauses"][0]
    assert top["clauseId"] == "CHK-D"
    assert any(match.get("source") == "auto_file_name" for match in top.get("aliasMatches") or [])
    assert "auto_file_name" in result["trace"]["aliasSources"]


# ------------------------------------------------- honest empty results


def test_no_basis_found_returns_empty_instead_of_arbitrary_clause() -> None:
    state = {
        "knowledge_sources": [], "knowledge_files": [], "knowledge_chunks": [],
        "knowledge_clauses": [], "evidence_links": [], "knowledge_page_index_nodes": [],
    }
    result = retrieve_knowledge_clauses(state, query="不存在的内容", top_k=3)
    assert result["clauses"] == []
    assert result["trace"]["noBasisFound"] is True
    assert result["trace"]["selectedClauses"] == []


# ------------------------------------------------- kbRef groundedness


def test_kb_citation_related_heuristic() -> None:
    clause = "低中压锅炉用无缝钢管应按 GB/T 3087-2022 的规定验收，质量证明书应齐全。"
    assert kb_citation_related("质量证明书应符合 GB/T 3087-2022 的验收规定", clause) is True
    assert kb_citation_related("焊工资格证书有效期超期，持证项目不覆盖", "水压试验保压时间不少于十分钟") is False


def test_reference_validation_reports_kb_citation_precision() -> None:
    drafts = [
        {
            "title": "质量证明书应符合 GB/T 3087-2022 验收规定",
            "description": "质量证明书验收依据核对。",
            "ruleRefs": [{"ruleCode": "R1", "ruleSetVersion": "v1"}],
            "kbRefs": [
                {"retrievalTraceId": "RTR-1", "clauseIds": ["C-GOOD", "C-BAD"], "kbVersion": "kb@1"}
            ],
        }
    ]
    traces = [
        {
            "retrievalTraceId": "RTR-1",
            "selectedClauses": [
                {"clauseId": "C-GOOD", "text": "低中压锅炉用无缝钢管应按 GB/T 3087-2022 的规定验收，质量证明书应齐全。"},
                {"clauseId": "C-BAD", "text": "水压试验保压时间不少于十分钟"},
            ],
        }
    ]
    result = validate_review_references(drafts, [{"ruleCode": "R1"}], traces)
    assert result["passed"] is True
    warning_codes = [item.get("code") for item in result.get("warnings") or []]
    assert "KB_CLAUSE_TEXT_UNRELATED" in warning_codes
    metrics = result["metrics"]
    assert metrics["kbCitationCheckedCount"] == 2
    assert metrics["kbCitationUnrelatedCount"] == 1
    assert metrics["kbCitationPrecision"] == 0.5


# ------------------------------------------------- local dense tenant filter


def test_local_dense_search_filters_foreign_tenants() -> None:
    from libs.db.repository import repo

    repo.reset()
    try:
        repo.state["knowledge_vectors"] = [
            {"id": "KV1", "chunkId": "C1", "embedding": [1.0, 0.0], "indexVersion": "v", "sourceId": "S"},
            {"id": "KV2", "chunkId": "C2", "embedding": [1.0, 0.0], "indexVersion": "v", "sourceId": "S",
             "tenantId": "TENANT-OTHER"},
        ]
        hits = repo.search_local_knowledge_vectors([1.0, 0.0], top_k=5)
        chunk_ids = {hit["chunkId"] for hit in hits}
        assert "C1" in chunk_ids
        assert "C2" not in chunk_ids
    finally:
        repo.reset()


# ------------------------------------------------- P3: BM25 node scoring + candidate cache


def test_bm25_scores_for_texts_generic() -> None:
    from libs.knowledge_retrieval import bm25_scores_for_texts

    scores = bm25_scores_for_texts(
        [("N1", "无损检测 附录 签章要求"), ("N2", "水压试验 保压时间")],
        "无损检测 附录",
    )
    assert "N1" in scores
    assert "N2" not in scores


def test_pageindex_node_scoring_uses_bm25_terms() -> None:
    state = {
        "knowledge_page_index_nodes": [
            {"pageIndexNodeId": "N1", "nodeId": "n1", "parentNodeId": None,
             "title": "含炉批号材料复验记录", "summary": "", "children": [],
             "linkedClauseIds": ["C1"], "status": "effective"},
        ],
        "knowledge_sources": [],
    }
    result = page_index_tree_search(state, ["炉批号"], query="炉批号 复验", top_k=3)
    assert result["selectedNodes"][0]["pageIndexNodeId"] == "N1"


def test_candidate_cache_reuses_and_invalidates(monkeypatch) -> None:
    from libs.knowledge_retrieval import knowledge_clause_candidates_cached

    monkeypatch.delenv("AICHECK_RETRIEVAL_CANDIDATE_CACHE", raising=False)
    state = make_state()
    first = knowledge_clause_candidates_cached(state)
    second = knowledge_clause_candidates_cached(state)
    assert first is second
    state["knowledge_chunks"].append(
        {
            "id": "CHK-NEW", "fileId": "F1", "pageNo": 20,
            "text": "新增条款内容，用于验证缓存失效逻辑是否正确工作。",
            "sectionPath": ["标准", "9.9 新增"], "bbox": [1, 1, 2, 2],
        }
    )
    third = knowledge_clause_candidates_cached(state)
    assert second is not third
    assert "CHK-NEW" in {item["clauseId"] for item in third}


def test_candidate_cache_disabled_by_env(monkeypatch) -> None:
    from libs.knowledge_retrieval import knowledge_clause_candidates_cached

    monkeypatch.setenv("AICHECK_RETRIEVAL_CANDIDATE_CACHE", "false")
    state = make_state()
    assert knowledge_clause_candidates_cached(state) is not knowledge_clause_candidates_cached(state)
