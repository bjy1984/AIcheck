from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from libs.contracts.responses import server_time


TOKEN_RE = re.compile(r"[A-Za-z0-9_.:-]+|[\u4e00-\u9fff]{1,4}")
EXACT_CLAUSE_RE = re.compile(r"(?<![A-Za-z0-9_.:-])([A-Z]{2,}[-_][A-Z0-9_.:-]*\d[A-Z0-9_.:-]*|\d+(?:\.\d+){1,5})(?:\s*条)?", re.IGNORECASE)
PAGEINDEX_QUERY_TERMS = (
    "附录",
    "跨章节",
    "跨章",
    "多章节",
    "长文档",
    "长手册",
    "章节",
    "正文",
    "引用",
    "条文之间",
)


def query_tokens(query: str) -> list[str]:
    tokens = [item.lower() for item in TOKEN_RE.findall(query or "") if item.strip()]
    seen: set[str] = set()
    deduped: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            deduped.append(token)
    return deduped


def normalize_clause_ref(value: Any) -> str:
    return str(value or "").strip().replace("第", "").replace("条", "").lower()


def detect_exact_clause_refs(query: str) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for match in EXACT_CLAUSE_RE.findall(query or ""):
        ref = normalize_clause_ref(match)
        if ref and ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return refs


def build_router_signals(query: str, tokens: list[str]) -> dict[str, Any]:
    exact_refs = detect_exact_clause_refs(query)
    needs_pageindex = any(term in (query or "") for term in PAGEINDEX_QUERY_TERMS) or len(query or "") >= 80
    return {
        "exactClauseRefs": exact_refs,
        "needsPageIndex": needs_pageindex,
        "tokenCount": len(tokens),
        "queryLength": len(query or ""),
    }


def classify_retrieval_route(query: str, tokens: list[str]) -> str:
    signals = build_router_signals(query, tokens)
    if signals["exactClauseRefs"]:
        return "exact_clause_lookup"
    if signals["needsPageIndex"]:
        return "pageindex_tree_search"
    return "hybrid_review_basis_search"


def source_version_by_id(state: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("id")): str(item.get("version") or "kb@draft")
        for item in state.get("knowledge_sources", [])
        if isinstance(item, dict) and item.get("id")
    }


def normalize_clause(candidate: dict[str, Any], *, default_version: str = "inspection_kb@1.0.0") -> dict[str, Any]:
    clause_id = str(candidate.get("clauseId") or candidate.get("id") or candidate.get("objectId") or f"clause-{uuid4().hex[:8]}")
    text = str(candidate.get("text") or candidate.get("quotedText") or candidate.get("description") or "")
    return {
        "id": str(candidate.get("id") or clause_id),
        "clauseId": clause_id,
        "kbDocId": candidate.get("kbDocId") or candidate.get("sourceId") or "KS-STANDARD-RULES",
        "kbVersion": candidate.get("kbVersion") or candidate.get("version") or default_version,
        "clauseNo": candidate.get("clauseNo") or clause_id.split("-")[-1],
        "title": candidate.get("title") or candidate.get("name") or clause_id,
        "text": text,
        "pageNo": candidate.get("pageNo"),
        "bbox": candidate.get("bbox"),
        "sectionPath": candidate.get("sectionPath") or [],
        "scope": candidate.get("scope") or {},
        "tags": candidate.get("tags") or [],
        "status": candidate.get("status") or "effective",
        "sourceEvidenceLinkId": candidate.get("sourceEvidenceLinkId"),
        "documentVersionId": candidate.get("documentVersionId"),
        "fileId": candidate.get("fileId"),
    }


def knowledge_clause_candidates(state: dict[str, Any], *, kb_version: str | None = None) -> list[dict[str, Any]]:
    source_versions = source_version_by_id(state)
    default_version = kb_version or next(iter(source_versions.values()), "inspection_kb@1.0.0")
    candidates: list[dict[str, Any]] = []

    for clause in state.get("knowledge_clauses", []) or []:
        if isinstance(clause, dict):
            candidates.append(normalize_clause(clause, default_version=default_version))

    for link in state.get("evidence_links", []) or []:
        if not isinstance(link, dict) or link.get("objectType") != "knowledgeClause":
            continue
        candidates.append(
            normalize_clause(
                {
                    "id": f"KC-{link.get('objectId') or link.get('id')}",
                    "clauseId": link.get("objectId") or link.get("id"),
                    "kbDocId": link.get("kbDocId") or "KS-STANDARD-RULES",
                    "kbVersion": link.get("kbVersion") or source_versions.get("KS-STANDARD-RULES") or default_version,
                    "title": link.get("title") or link.get("objectId") or "知识条款",
                    "text": link.get("quotedText"),
                    "pageNo": link.get("pageNo"),
                    "bbox": link.get("bbox"),
                    "sourceEvidenceLinkId": link.get("id"),
                    "tags": [link.get("fieldName")] if link.get("fieldName") else [],
                },
                default_version=default_version,
            )
        )

    files_by_id = {
        item.get("id"): item
        for item in state.get("knowledge_files", []) or []
        if isinstance(item, dict) and item.get("id")
    }
    sources_by_id = {
        item.get("id"): item
        for item in state.get("knowledge_sources", []) or []
        if isinstance(item, dict) and item.get("id")
    }
    for chunk in state.get("knowledge_chunks", []) or []:
        if not isinstance(chunk, dict):
            continue
        file = files_by_id.get(chunk.get("fileId")) or {}
        source = sources_by_id.get(file.get("sourceId")) or {}
        if file.get("indexEnabled") is False or source.get("sourceType") == "rule":
            continue
        source_id = file.get("sourceId") or "KS-PROJECT-FILE"
        candidates.append(
            normalize_clause(
                {
                    "id": f"KC-{chunk.get('id')}",
                    "clauseId": chunk.get("id"),
                    "kbDocId": source_id,
                    "kbVersion": source_versions.get(str(source_id)) or default_version,
                    "title": file.get("fileName") or chunk.get("id"),
                    "text": chunk.get("text"),
                    "pageNo": chunk.get("pageNo"),
                    "bbox": chunk.get("bbox"),
                    "fileId": chunk.get("fileId"),
                    "documentVersionId": chunk.get("documentVersionId"),
                    "scope": {"projectId": file.get("projectId"), "nodeId": file.get("nodeId")},
                    "tags": [file.get("nodeName"), file.get("fileName")],
                },
                default_version=default_version,
            )
        )

    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if candidate.get("status") in {"deprecated", "retired", "停用"}:
            continue
        clause_id = str(candidate["clauseId"])
        unique.setdefault(clause_id, candidate)
    return list(unique.values())


def normalize_page_index_node(candidate: dict[str, Any], *, default_version: str = "inspection_kb@1.0.0") -> dict[str, Any]:
    node_id = str(candidate.get("pageIndexNodeId") or candidate.get("id") or candidate.get("nodeId") or f"pin-{uuid4().hex[:8]}")
    return {
        "id": str(candidate.get("id") or node_id),
        "pageIndexNodeId": node_id,
        "kbDocId": candidate.get("kbDocId") or candidate.get("sourceId") or "KS-STANDARD-RULES",
        "kbVersion": candidate.get("kbVersion") or candidate.get("version") or default_version,
        "nodeId": str(candidate.get("nodeId") or node_id),
        "parentNodeId": candidate.get("parentNodeId"),
        "title": candidate.get("title") or candidate.get("name") or node_id,
        "summary": candidate.get("summary") or candidate.get("text") or "",
        "startPage": candidate.get("startPage"),
        "endPage": candidate.get("endPage"),
        "sectionPath": candidate.get("sectionPath") or [],
        "children": candidate.get("children") or [],
        "linkedClauseIds": candidate.get("linkedClauseIds") or [],
        "businessPackId": candidate.get("businessPackId") or (candidate.get("metadata") or {}).get("businessPackId"),
        "nodeTypes": candidate.get("nodeTypes") or (candidate.get("metadata") or {}).get("nodeTypes") or [],
        "materialTypes": candidate.get("materialTypes") or (candidate.get("metadata") or {}).get("materialTypes") or [],
        "tags": candidate.get("tags") or [],
        "status": candidate.get("status") or "effective",
    }


def page_index_node_candidates(state: dict[str, Any], *, kb_version: str | None = None) -> list[dict[str, Any]]:
    source_versions = source_version_by_id(state)
    default_version = kb_version or next(iter(source_versions.values()), "inspection_kb@1.0.0")
    unique: dict[str, dict[str, Any]] = {}
    for node in state.get("knowledge_page_index_nodes", []) or []:
        if not isinstance(node, dict):
            continue
        normalized = normalize_page_index_node(node, default_version=default_version)
        if normalized.get("status") in {"deprecated", "retired", "停用"}:
            continue
        unique.setdefault(str(normalized["pageIndexNodeId"]), normalized)
    return list(unique.values())


def clause_score(clause: dict[str, Any], tokens: list[str], *, node_id: int | None = None, business_pack_id: str | None = None) -> float:
    haystack = " ".join(
        str(part or "")
        for part in [
            clause.get("clauseId"),
            clause.get("clauseNo"),
            clause.get("title"),
            clause.get("text"),
            " ".join(str(item or "") for item in clause.get("tags") or []),
        ]
    ).lower()
    score = 0.0
    for token in tokens:
        if token and token in haystack:
            score += 2.0 if len(token) > 1 else 0.25
    scope = clause.get("scope") or {}
    node_ids = {int(item) for item in scope.get("nodeIds") or [] if str(item).isdigit()}
    if node_id is not None and (scope.get("nodeId") == node_id or node_id in node_ids):
        score += 3.0
    if business_pack_id and scope.get("businessPackId") == business_pack_id:
        score += 1.0
    if clause.get("sourceEvidenceLinkId"):
        score += 0.5
    return score


def token_overlap_score(haystack: str, tokens: list[str]) -> float:
    lowered = haystack.lower()
    score = 0.0
    for token in tokens:
        if token and token in lowered:
            score += 2.0 if len(token) > 1 else 0.25
    return score


def exact_clause_score(clause: dict[str, Any], exact_refs: list[str]) -> float:
    if not exact_refs:
        return 0.0
    searchable = " ".join(
        normalize_clause_ref(part)
        for part in [
            clause.get("clauseId"),
            clause.get("clauseNo"),
            clause.get("id"),
            clause.get("title"),
            " ".join(str(item or "") for item in clause.get("tags") or []),
        ]
    )
    score = 0.0
    for ref in exact_refs:
        if ref and ref == normalize_clause_ref(clause.get("clauseNo")):
            score += 50.0
        elif ref and ref == normalize_clause_ref(clause.get("clauseId")):
            score += 45.0
        elif ref and ref in searchable:
            score += 30.0
    return score


def pageindex_clause_score(clause: dict[str, Any], tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    section_text = " ".join(str(item or "") for item in clause.get("sectionPath") or []).lower()
    page_score = 0.0
    for token in tokens:
        if token and token in section_text:
            page_score += 2.0
    if clause.get("pageNo") is not None:
        page_score += 0.5
    if clause.get("bbox"):
        page_score += 0.5
    return page_score


def page_index_node_score(
    node: dict[str, Any],
    tokens: list[str],
    *,
    node_id: int | None = None,
    business_pack_id: str | None = None,
) -> float:
    haystack = " ".join(
        str(part or "")
        for part in [
            node.get("pageIndexNodeId"),
            node.get("title"),
            node.get("summary"),
            " ".join(str(item or "") for item in node.get("sectionPath") or []),
            " ".join(str(item or "") for item in node.get("tags") or []),
            " ".join(str(item or "") for item in node.get("linkedClauseIds") or []),
        ]
    )
    score = token_overlap_score(haystack, tokens)
    if tokens and score <= 0:
        return 0.0
    if node.get("startPage") is not None and node.get("endPage") is not None:
        score += 0.5
    if business_pack_id and node.get("businessPackId") == business_pack_id:
        score += 1.0
    node_types = {str(item) for item in node.get("nodeTypes") or []}
    if node_id is not None and str(node_id) in node_types:
        score += 1.0
    return score


def page_index_tree_search(
    state: dict[str, Any],
    tokens: list[str],
    *,
    business_pack_id: str | None = None,
    node_id: int | None = None,
    kb_version: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    nodes = page_index_node_candidates(state, kb_version=kb_version)
    scored: list[dict[str, Any]] = []
    for node in nodes:
        score = page_index_node_score(node, tokens, node_id=node_id, business_pack_id=business_pack_id)
        if score <= 0 and tokens:
            continue
        scored.append({**node, "score": round(score or 0.1, 4)})
    scored.sort(key=lambda item: (float(item.get("score") or 0), len(item.get("linkedClauseIds") or [])), reverse=True)
    selected_nodes = scored[: max(1, int(top_k or 5))]
    linked_clause_ids: list[str] = []
    for node in selected_nodes:
        for clause_id in node.get("linkedClauseIds") or []:
            if clause_id and clause_id not in linked_clause_ids:
                linked_clause_ids.append(str(clause_id))
    node_by_id = {str(node.get("nodeId")): node for node in nodes}
    tree_path: list[dict[str, Any]] = []
    for node in selected_nodes[:3]:
        current: dict[str, Any] | None = node
        lineage: list[dict[str, Any]] = []
        while current:
            lineage.append(
                {
                    "pageIndexNodeId": current.get("pageIndexNodeId"),
                    "nodeId": current.get("nodeId"),
                    "title": current.get("title"),
                }
            )
            parent_id = current.get("parentNodeId")
            current = node_by_id.get(str(parent_id)) if parent_id is not None else None
        tree_path.extend(reversed(lineage))
    return {
        "candidateNodeCount": len(nodes),
        "selectedNodes": [
            {
                "pageIndexNodeId": node.get("pageIndexNodeId"),
                "nodeId": node.get("nodeId"),
                "title": node.get("title"),
                "summary": node.get("summary"),
                "startPage": node.get("startPage"),
                "endPage": node.get("endPage"),
                "sectionPath": node.get("sectionPath"),
                "linkedClauseIds": node.get("linkedClauseIds"),
                "score": node.get("score"),
            }
            for node in selected_nodes
        ],
        "linkedClauseIds": linked_clause_ids,
        "treeSearchPath": tree_path,
    }


def retrieve_knowledge_clauses(
    state: dict[str, Any],
    *,
    query: str,
    review_run_id: str | None = None,
    business_pack_id: str | None = None,
    node_id: int | None = None,
    kb_version: str | None = None,
    top_k: int = 5,
    query_type: str = "review_basis_search",
) -> dict[str, Any]:
    tokens = query_tokens(query)
    router_signals = build_router_signals(query, tokens)
    selected_route = classify_retrieval_route(query, tokens)
    exact_refs = list(router_signals.get("exactClauseRefs") or [])
    candidates = knowledge_clause_candidates(state, kb_version=kb_version)
    page_index_result = (
        page_index_tree_search(
            state,
            tokens,
            business_pack_id=business_pack_id,
            node_id=node_id,
            kb_version=kb_version,
            top_k=top_k,
        )
        if selected_route == "pageindex_tree_search"
        else {"candidateNodeCount": len(page_index_node_candidates(state, kb_version=kb_version)), "selectedNodes": [], "linkedClauseIds": [], "treeSearchPath": []}
    )
    page_index_clause_ids = {str(item) for item in page_index_result.get("linkedClauseIds") or []}
    page_index_node_ids_by_clause: dict[str, list[str]] = {}
    for node in page_index_result.get("selectedNodes") or []:
        node_ref = str(node.get("pageIndexNodeId") or "")
        for clause_id in node.get("linkedClauseIds") or []:
            if clause_id and node_ref:
                page_index_node_ids_by_clause.setdefault(str(clause_id), []).append(node_ref)
    scored: list[dict[str, Any]] = []
    for clause in candidates:
        base_score = clause_score(clause, tokens, node_id=node_id, business_pack_id=business_pack_id)
        route_score = 0.0
        retrieval_mode = "hybrid_bm25_dense_local"
        if selected_route == "exact_clause_lookup":
            route_score = exact_clause_score(clause, exact_refs)
            if route_score > 0:
                retrieval_mode = "exact_clause_lookup"
                base_score = (base_score * 0.1) + route_score + 100.0
        elif selected_route == "pageindex_tree_search":
            route_score = pageindex_clause_score(clause, tokens)
            if str(clause.get("clauseId")) in page_index_clause_ids:
                route_score += 50.0
                retrieval_mode = "pageindex_tree_local"
            if route_score > 0:
                retrieval_mode = "pageindex_tree_local"
        score = base_score + route_score
        if score <= 0 and tokens:
            continue
        scored.append({**clause, "score": round(score or 0.1, 4), "retrievalMode": retrieval_mode})
    scored.sort(
        key=lambda item: (
            item.get("retrievalMode") == "exact_clause_lookup",
            item.get("retrievalMode") == "pageindex_tree_local",
            float(item.get("score") or 0),
            item.get("sourceEvidenceLinkId") is not None,
        ),
        reverse=True,
    )
    selected = scored[: max(1, int(top_k or 5))]
    if not selected and candidates:
        selected = [{**candidates[0], "score": 0.1, "retrievalMode": "clause_fallback"}]
    trace_id = f"RTR-{uuid4().hex[:8].upper()}"
    trace = {
        "id": trace_id,
        "retrievalTraceId": trace_id,
        "reviewRunId": review_run_id,
        "query": query,
        "queryType": query_type,
        "routerVersion": "knowledge-router-v1",
        "selectedRoute": selected_route,
        "routerSignals": router_signals,
        "queryRouter": {
            "selectedRoute": selected_route,
            "signals": router_signals,
            "fallbackRoute": "hybrid_review_basis_search",
        },
        "filters": {
            "businessPackId": business_pack_id,
            "nodeId": node_id,
            "effectiveAt": server_time(),
        },
        "retrievers": [
            {"type": "exact_clause_lookup", "enabled": selected_route == "exact_clause_lookup", "clauseRefs": exact_refs},
            {"type": "clause_index", "topK": min(top_k, 5), "candidateCount": len(candidates)},
            {"type": "hybrid_bm25_dense", "topK": top_k, "implementation": "local_token_overlap_until_vector_index"},
            {
                "type": "pageindex_tree",
                "enabled": selected_route == "pageindex_tree_search",
                "implementation": "local_page_index_nodes",
                "candidateNodeCount": page_index_result.get("candidateNodeCount"),
                "selectedNodeCount": len(page_index_result.get("selectedNodes") or []),
            },
        ],
        "pageIndexTree": page_index_result,
        "selectedClauses": [
            {
                "clauseId": item.get("clauseId"),
                "kbDocId": item.get("kbDocId"),
                "kbVersion": item.get("kbVersion"),
                "clauseNo": item.get("clauseNo"),
                "title": item.get("title"),
                "text": item.get("text"),
                "pageNo": item.get("pageNo"),
                "bbox": item.get("bbox"),
                "score": item.get("score"),
                "retrievalMode": item.get("retrievalMode"),
                "pageIndexNodeIds": page_index_node_ids_by_clause.get(str(item.get("clauseId")), []),
                "sourceEvidenceLinkId": item.get("sourceEvidenceLinkId"),
            }
            for item in selected
        ],
        "kbVersion": kb_version or (selected[0].get("kbVersion") if selected else "inspection_kb@1.0.0"),
        "createdAt": server_time(),
    }
    return {"trace": trace, "clauses": selected}


def answer_draft_from_clauses(question: str, clauses: list[dict[str, Any]]) -> str:
    if not clauses:
        return f"围绕“{question}”，未检索到可用条款，建议转人工补充依据。"
    first = clauses[0]
    return (
        f"围绕“{question}”，优先引用 {first.get('clauseNo') or first.get('clauseId')} "
        f"（{first.get('title')}）进行核验，并结合 OCR 证据、规则结果和人工确认形成正式结论。"
    )
