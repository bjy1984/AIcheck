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


# ------------------------------------------------- P3+: node embeddings + LLM judge


def test_page_index_embedding_input_and_rows() -> None:
    from libs.knowledge_indexing import (
        build_node_vector_rows,
        page_index_embedding_input,
        page_index_vector_index_version,
    )

    node = {"pageIndexNodeId": "PIN-1", "title": "无损检测 附录A",
            "sectionPath": ["NB_T 47013.pdf", "附录A"], "summary": "附录A 无损检测报告签章要求",
            "linkedClauseIds": ["C1"], "startPage": 90}
    text = page_index_embedding_input(node)
    assert "无损检测 附录A" in text and "签章要求" in text
    assert page_index_vector_index_version("iv@1") == "iv@1::pageindex"
    rows = build_node_vector_rows("KS-1", [node], [{"index": 0, "embedding": [0.6, 0.8]}],
                                  embedding_model="m", index_version="iv@1")
    assert rows[0]["id"] == "KNV-PIN-1"
    assert rows[0]["chunkId"] == "PIN-1"
    assert rows[0]["indexVersion"] == "iv@1::pageindex"
    assert rows[0]["payload"]["objectType"] == "pageIndexNode"


def test_tree_search_fuses_dense_node_ranks() -> None:
    state = {
        "knowledge_page_index_nodes": [
            {"pageIndexNodeId": "N-LEX", "nodeId": "a", "parentNodeId": None,
             "title": "无损检测 正文", "summary": "无损检测 检测比例", "children": [],
             "linkedClauseIds": ["C1"], "status": "effective"},
            {"pageIndexNodeId": "N-DENSE", "nodeId": "b", "parentNodeId": None,
             "title": "射线照相底片评定", "summary": "底片黑度 灵敏度", "children": [],
             "linkedClauseIds": ["C2"], "status": "effective"},
        ],
        "knowledge_sources": [],
    }
    result = page_index_tree_search(state, ["无损检测"], query="无损检测",
                                    dense_node_ranks={"N-DENSE": 1}, top_k=3)
    ids = [item["pageIndexNodeId"] for item in result["selectedNodes"]]
    assert "N-DENSE" in ids  # dense-only node kept despite zero BM25
    assert result["denseNodeHitCount"] == 1


def test_local_node_vector_search_via_collection() -> None:
    from libs.db.repository import repo
    from libs.knowledge_indexing import (
        STANDARD_INDEX_VERSION,
        offline_hash_embedding,
        page_index_vector_index_version,
    )

    repo.reset()
    try:
        node_iv = page_index_vector_index_version(STANDARD_INDEX_VERSION)
        repo.state["knowledge_node_vectors"] = [
            {"id": "KNV-P1", "chunkId": "PIN-1", "indexVersion": node_iv,
             "embedding": offline_hash_embedding("无损检测 附录A 签章要求"), "sourceId": "KS-1"},
        ]
        hits = repo.search_local_knowledge_vectors(
            offline_hash_embedding("无损检测 附录 签章"),
            top_k=3, index_version=node_iv, collection="knowledge_node_vectors",
        )
        assert hits and hits[0]["chunkId"] == "PIN-1"
    finally:
        repo.reset()


def test_llm_judge_parse_apply_and_degrade(monkeypatch) -> None:
    from libs.review_judge import (
        apply_judgments_to_drafts,
        judge_review_findings,
        parse_judge_response,
    )

    drafts = [
        {"title": "质量证明书符合", "description": "核对通过", "confidence": 0.9},
        {"title": "焊工证有效", "description": "证书在有效期内", "confidence": 0.8},
    ]
    judgments = parse_judge_response(
        '{"judgments": [{"index": 0, "verdict": "supported", "confidence": 0.9},'
        ' {"index": 1, "verdict": "unsupported", "confidence": 0.8},'
        ' {"index": 9, "verdict": "supported"}]}',
        finding_count=2,
    )
    assert len(judgments) == 2
    assert apply_judgments_to_drafts(drafts, judgments) == 1
    assert drafts[1]["groundingStatus"] == "insufficient_evidence"
    assert drafts[1]["confidence"] == 0.55

    def chat_ok(messages, *, max_tokens, timeout):
        return '{"judgments": [{"index": 0, "verdict": "supported", "confidence": 1.0}]}'

    summary = judge_review_findings(chat_ok, [drafts[0]])
    assert summary["status"] == "ok"
    assert summary["metrics"]["llmJudgeGroundedRate"] == 1.0

    def chat_boom(messages, *, max_tokens, timeout):
        raise RuntimeError("down")

    degraded = judge_review_findings(chat_boom, [drafts[0]])
    assert degraded["status"] == "degraded"


def test_llm_judge_disabled_by_default(monkeypatch) -> None:
    from libs.review_judge import llm_judge_enabled
    from libs.review_orchestrator.execution import maybe_run_llm_judge

    monkeypatch.delenv("AICHECK_REVIEW_LLM_JUDGE", raising=False)
    assert llm_judge_enabled() is False
    assert maybe_run_llm_judge({"reviewRunId": "RR-1"}, {"findingDrafts": [{"title": "t"}]}) is None
