from __future__ import annotations

from typing import Any

from libs.knowledge_retrieval import retrieve_knowledge_clauses


REQUIRED_KNOWLEDGE_ROUTES = {
    "exact_clause_lookup": "5.3.2 条",
    "hybrid_review_basis_search": "焊工资格证有效期如何校验？",
    "pageindex_tree_search": "请结合正文和附录跨章节说明无损检测报告签章要求",
}


def build_knowledge_rule_scorecard(state: dict[str, Any]) -> dict[str, Any]:
    probes = run_retrieval_probes(state)
    sections = [
        source_index_section(state),
        rule_clause_section(state),
        retrieval_router_section(probes),
        evaluation_governance_section(state),
    ]
    score = round(sum(float(section["score"]) for section in sections), 2)
    blockers = [
        blocker
        for section in sections
        for blocker in section.get("blockers", [])
    ]
    return {
        "schemaVersion": "aicheck-knowledge-rule-scorecard-v1",
        "targetScore": 100,
        "score": score,
        "ok": score >= 100 and not blockers,
        "sections": sections,
        "blockers": blockers,
        "retrievalProbes": probes,
    }


def source_index_section(state: dict[str, Any]) -> dict[str, Any]:
    sources = [item for item in state.get("knowledge_sources") or [] if isinstance(item, dict)]
    tasks = [item for item in state.get("knowledge_tasks") or [] if isinstance(item, dict)]
    blockers: list[str] = []
    points = 0.0
    if sources:
        points += 5
    else:
        blockers.append("knowledge sources are missing")
    enabled_sources = [item for item in sources if item.get("status") in {"启用", "effective", "production"}]
    if enabled_sources:
        points += 5
    else:
        blockers.append("no enabled knowledge source exists")
    if sum(safe_int(item.get("chunkCount")) for item in sources) > 0:
        points += 5
    else:
        blockers.append("knowledge chunks are missing")
    vector_ready = [item for item in sources if item.get("vectorStatus") == "已向量化"]
    if sources and len(vector_ready) / len(sources) >= 0.6:
        points += 5
    else:
        blockers.append("less than 60% of knowledge sources are vectorized")
    failed_tasks = [item for item in tasks if item.get("status") in {"失败", "failed"}]
    governed_failures = [
        item
        for item in failed_tasks
        if item.get("errorMessage") and any(str(action).endswith("task-retry") for action in item.get("actions") or [])
    ]
    if not failed_tasks or len(governed_failures) == len(failed_tasks):
        points += 5
    else:
        blockers.append(f"{len(failed_tasks) - len(governed_failures)} failed knowledge tasks lack retry governance")
    return section("source-index", points, 25, blockers)


def rule_clause_section(state: dict[str, Any]) -> dict[str, Any]:
    clauses = [item for item in state.get("knowledge_clauses") or [] if isinstance(item, dict)]
    rules = [item for item in state.get("rule_versions") or [] if isinstance(item, dict)]
    blockers: list[str] = []
    points = 0.0
    if len(clauses) >= 3:
        points += 5
    else:
        blockers.append("knowledge clause coverage is below 3 clauses")
    if clauses and all(item.get("pageNo") is not None and item.get("bbox") for item in clauses):
        points += 5
    else:
        blockers.append("one or more clauses lack page/bbox evidence")
    if clauses and all((item.get("scope") or {}).get("businessPackId") for item in clauses):
        points += 5
    else:
        blockers.append("one or more clauses lack businessPack scope")
    if any(item.get("status") in {"已发布", "production", "published"} for item in rules):
        points += 5
    else:
        blockers.append("no published rule version exists")
    if rules and all(item.get("promptVersion") and item.get("outputSchemaVersion") for item in rules):
        points += 5
    else:
        blockers.append("one or more rules lack prompt/output schema version")
    return section("rule-clause", points, 25, blockers)


def retrieval_router_section(probes: list[dict[str, Any]]) -> dict[str, Any]:
    blockers: list[str] = []
    points = 0.0
    probes_by_route = {str(item.get("expectedRoute")): item for item in probes}
    for route in REQUIRED_KNOWLEDGE_ROUTES:
        probe = probes_by_route.get(route) or {}
        if probe.get("passed"):
            points += 6
        else:
            blockers.append(f"retrieval probe failed: {route}")
    if any("hybrid_bm25_dense" in item.get("retrieverTypes", []) for item in probes):
        points += 4
    else:
        blockers.append("Hybrid BM25+dense retriever is not exposed")
    page_probe = probes_by_route.get("pageindex_tree_search") or {}
    if safe_int(page_probe.get("pageIndexNodeCount")) > 0:
        points += 4
    else:
        blockers.append("PageIndex probe did not return selected nodes")
    if probes and all(safe_int(item.get("selectedClauseCount")) > 0 for item in probes):
        points += 4
    else:
        blockers.append("one or more retrieval probes returned no clauses")
    if probes and all(item.get("evidenceBacked") for item in probes):
        points += 4
    else:
        blockers.append("one or more retrieval probes lack page/bbox evidence")
    return section("retrieval-router", points, 30, blockers)


def evaluation_governance_section(state: dict[str, Any]) -> dict[str, Any]:
    config = state.get("knowledge_config") if isinstance(state.get("knowledge_config"), dict) else {}
    cases = [item for item in state.get("evaluation_cases") or [] if isinstance(item, dict)]
    reports = [item for item in state.get("evaluation_reports") or [] if isinstance(item, dict)]
    traces = [item for item in state.get("retrieval_traces") or [] if isinstance(item, dict)]
    blockers: list[str] = []
    points = 0.0
    if config.get("evidenceStrictMode") is True and config.get("rerankEnabled") is True:
        points += 4
    else:
        blockers.append("knowledge config must enable rerank and evidence strict mode")
    if any(item.get("expectedClauseIds") for item in cases):
        points += 4
    else:
        blockers.append("evaluation cases with expectedClauseIds are missing")
    if any(item.get("status") == "passed" for item in reports):
        points += 4
    else:
        blockers.append("no passed evaluation report exists")
    retrieval_metrics = latest_retrieval_metrics(reports)
    if retrieval_metrics.get("retrievalRecall") is not None and safe_float(retrieval_metrics.get("retrievalRecall")) >= 0.9:
        points += 2
    else:
        blockers.append("retrievalRecall metric is missing or below 0.9")
    if retrieval_metrics.get("wrongReferenceRate") is not None and safe_float(retrieval_metrics.get("wrongReferenceRate")) <= 0.03:
        points += 2
    else:
        blockers.append("wrongReferenceRate metric is missing or above 0.03")
    if traces:
        points += 4
    else:
        blockers.append("persisted RetrievalTrace records are missing")
    return section("evaluation-governance", points, 20, blockers)


def run_retrieval_probes(state: dict[str, Any]) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    for expected_route, query in REQUIRED_KNOWLEDGE_ROUTES.items():
        result = retrieve_knowledge_clauses(
            state,
            query=query,
            top_k=3,
            query_type="knowledge_scorecard_probe",
        )
        trace = result.get("trace") or {}
        selected_clauses = trace.get("selectedClauses") or []
        retriever_types = [
            str(item.get("type"))
            for item in trace.get("retrievers") or []
            if isinstance(item, dict) and item.get("type")
        ]
        primary_clause = selected_clauses[0] if selected_clauses and isinstance(selected_clauses[0], dict) else {}
        evidence_backed = bool(primary_clause.get("pageNo") is not None and primary_clause.get("bbox"))
        probes.append(
            {
                "query": query,
                "expectedRoute": expected_route,
                "selectedRoute": trace.get("selectedRoute"),
                "passed": trace.get("selectedRoute") == expected_route and bool(selected_clauses),
                "selectedClauseCount": len(selected_clauses),
                "topClauseId": (selected_clauses[0] or {}).get("clauseId") if selected_clauses else None,
                "retrieverTypes": retriever_types,
                "pageIndexNodeCount": len((trace.get("pageIndexTree") or {}).get("selectedNodes") or []),
                "evidenceBacked": evidence_backed,
            }
        )
    return probes


def latest_retrieval_metrics(reports: list[dict[str, Any]]) -> dict[str, Any]:
    for report in reports:
        metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
        if "retrievalRecall" in metrics or "wrongReferenceRate" in metrics:
            return metrics
        case_summary = report.get("caseSummary") if isinstance(report.get("caseSummary"), dict) else {}
        if "retrievalRecall" in case_summary or "wrongReferenceRate" in case_summary:
            return case_summary
    return {}


def section(name: str, score: float, max_score: float, blockers: list[str]) -> dict[str, Any]:
    score = round(min(max(score, 0.0), max_score), 2)
    return {
        "name": name,
        "score": score,
        "maxScore": max_score,
        "status": "pass" if score >= max_score and not blockers else "fail",
        "blockers": blockers,
    }


def safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
