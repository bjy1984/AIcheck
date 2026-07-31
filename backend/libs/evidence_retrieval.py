from __future__ import annotations

from hashlib import sha256
from time import perf_counter
from typing import Any
from uuid import uuid4

from libs.contracts.responses import server_time
from libs.knowledge_dense import dense_knowledge_hits
from libs.knowledge_retrieval import bm25_scores_for_texts, rrf_fusion_config
from libs.security.tenant import current_tenant_id

INEFFECTIVE_DOCUMENT_STATUSES = {
    "archived",
    "invalid",
    "invalidated",
    "withdrawn",
    "作废",
    "失效",
    "已作废",
    "已失效",
    "已归档",
    "已撤回",
    "撤回",
    "无效",
    "归档",
}


def _record_id(record: dict[str, Any]) -> str:
    return str(record.get("id") or "")


def _document_is_effective(document: dict[str, Any]) -> bool:
    statuses = {
        str(document.get(field) or "").strip().lower()
        for field in ("status", "fileStatus")
        if str(document.get(field) or "").strip()
    }
    return (
        statuses.isdisjoint(INEFFECTIVE_DOCUMENT_STATUSES)
        and document.get("effective") is not False
        and document.get("isEffective") is not False
        and not document.get("withdrawnAt")
        and not document.get("invalidatedAt")
    )


def scoped_evidence_chunks(
    repo: Any,
    *,
    project_id: str,
    document_version_ids: list[str],
) -> list[dict[str, Any]]:
    """Resolve project-authorized chunks from repository relationships."""
    state = repo.state
    allowed_versions = {
        str(version_id)
        for version_id in document_version_ids
        if str(version_id or "").strip()
    }
    if not allowed_versions:
        return []

    documents = {
        _record_id(document): document
        for document in state.get("documents", [])
        if str(document.get("projectId") or "") == str(project_id)
        and _document_is_effective(document)
    }
    versions = {
        _record_id(version): version
        for version in state.get("versions", [])
        if _record_id(version) in allowed_versions
        and str(version.get("documentId") or "") in documents
    }
    files: dict[str, dict[str, Any]] = {}
    for file_record in state.get("knowledge_files", []):
        version_id = str(file_record.get("documentVersionId") or "")
        document_id = str(file_record.get("documentId") or "")
        version = versions.get(version_id)
        if (
            str(file_record.get("sourceId") or "") != "KS-PROJECT-FILE"
            or str(file_record.get("projectId") or "") != str(project_id)
            or version is None
            or document_id not in documents
            or str(version.get("documentId") or "") != document_id
        ):
            continue
        files[_record_id(file_record)] = file_record

    scoped: list[dict[str, Any]] = []
    for chunk in state.get("knowledge_chunks", []):
        file_record = files.get(str(chunk.get("fileId") or ""))
        if file_record is None:
            continue
        version_id = str(chunk.get("documentVersionId") or file_record.get("documentVersionId") or "")
        if (
            version_id not in versions
            or version_id != str(file_record.get("documentVersionId") or "")
            or not str(chunk.get("text") or "").strip()
        ):
            continue
        document_id = str(file_record.get("documentId") or "")
        scoped.append(
            {
                **chunk,
                "_file": file_record,
                "_document": documents[document_id],
                "_version": versions[version_id],
            }
        )
    return scoped


def evidence_lexical_text(chunk: dict[str, Any]) -> str:
    file_record = chunk.get("_file") or {}
    section_path = " ".join(str(item or "") for item in chunk.get("sectionPath") or [])
    return " ".join(
        part
        for part in [
            str(file_record.get("fileName") or ""),
            section_path,
            str(chunk.get("text") or ""),
        ]
        if part
    )


def evidence_lexical_query(query: str) -> str:
    """Treat punctuation as separators so it cannot become BM25 evidence."""
    return " ".join("".join(character if character.isalnum() else " " for character in query).split())


def _valid_bbox(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return False
    try:
        left, top, right, bottom = (float(item) for item in value)
    except (TypeError, ValueError):
        return False
    return right > left and bottom > top


def evidence_eligibility(candidate: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not str(candidate.get("documentId") or "").strip():
        reasons.append("missing_document_id")
    if not str(candidate.get("documentVersionId") or "").strip():
        reasons.append("missing_document_version_id")
    try:
        valid_page = int(candidate.get("pageNo") or 0) > 0
    except (TypeError, ValueError):
        valid_page = False
    if not valid_page:
        reasons.append("invalid_page_no")
    if candidate.get("bbox") is None:
        reasons.append("missing_bbox")
    elif not _valid_bbox(candidate.get("bbox")):
        reasons.append("invalid_bbox")
    quoted_text = str(candidate.get("quotedText") or "").strip()
    if not quoted_text:
        reasons.append("missing_quoted_text")
    elif quoted_text == str(candidate.get("fileName") or "").strip():
        reasons.append("quoted_text_is_file_name")
    if not str(candidate.get("chunkId") or candidate.get("fragmentId") or "").strip():
        reasons.append("missing_source_identifier")
    return not reasons, reasons


def normalize_evidence_candidate(
    chunk: dict[str, Any],
    *,
    project_id: str,
    bm25_score: float = 0.0,
    bm25_rank: int | None = None,
    dense_rank: int | None = None,
    fused_score: float | None = None,
) -> dict[str, Any]:
    file_record = chunk.get("_file") or {}
    document = chunk.get("_document") or {}
    version = chunk.get("_version") or {}
    chunk_id = str(chunk.get("id") or chunk.get("chunkId") or "")
    fragment_id = str(chunk.get("fragmentId") or "")
    source_key = chunk_id or fragment_id
    if source_key:
        candidate_id = f"EVC-{source_key}"
    else:
        identity = "|".join(
            [
                str(project_id),
                str(file_record.get("id") or chunk.get("fileId") or ""),
                str(chunk.get("pageNo") or ""),
                str(chunk.get("text") or ""),
            ]
        )
        candidate_id = f"EVC-{sha256(identity.encode('utf-8')).hexdigest()[:16].upper()}"
    candidate = {
        "id": candidate_id,
        "candidateId": candidate_id,
        "evidenceId": candidate_id,
        "projectId": str(project_id),
        "documentId": str(document.get("id") or file_record.get("documentId") or ""),
        "documentVersionId": str(
            version.get("id") or chunk.get("documentVersionId") or file_record.get("documentVersionId") or ""
        ),
        "fileId": str(file_record.get("id") or chunk.get("fileId") or ""),
        "fileName": str(file_record.get("fileName") or ""),
        "pageNo": chunk.get("pageNo"),
        "bbox": chunk.get("bbox"),
        "quotedText": str(chunk.get("text") or "").strip(),
        "chunkId": chunk_id,
        "fragmentId": fragment_id or None,
        "sourceId": str(chunk.get("sourceId") or file_record.get("sourceId") or ""),
        "sectionPath": list(chunk.get("sectionPath") or []),
        "bm25Score": round(float(bm25_score), 8),
        "bm25Rank": bm25_rank,
        "denseRank": dense_rank,
        "fusedScore": round(float(fused_score), 8) if fused_score is not None else None,
        "manualStatus": "pending",
        "manualStatusLabel": "待确认",
        "requiresHumanConfirmation": True,
    }
    eligible, rejection_reasons = evidence_eligibility(candidate)
    candidate.update(
        {
            "formalEvidenceEligible": eligible,
            "evidenceTier": "formal" if eligible else "advisory",
            "rejectionReasons": rejection_reasons,
        }
    )
    return candidate


def _locator_completeness(candidate: dict[str, Any]) -> int:
    return sum(
        [
            bool(candidate.get("documentId")),
            bool(candidate.get("documentVersionId")),
            bool(candidate.get("pageNo")),
            _valid_bbox(candidate.get("bbox")),
            bool(candidate.get("quotedText")),
            bool(candidate.get("chunkId") or candidate.get("sourceId")),
        ]
    )


def search_project_evidence(
    repo: Any,
    *,
    project_id: str,
    node_id: int,
    document_version_ids: list[str],
    query: str,
    top_k: int = 20,
    review_run_id: str | None = None,
    persist_trace: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    effective_query = str(query or "").strip() or f"节点 {node_id} 材料证据"
    allowed_versions = list(
        dict.fromkeys(
            str(version_id)
            for version_id in document_version_ids
            if str(version_id or "").strip()
        )
    )
    scoped_chunks = scoped_evidence_chunks(
        repo,
        project_id=project_id,
        document_version_ids=allowed_versions,
    )
    bm25_started = perf_counter()
    bm25_scores = bm25_scores_for_texts(
        [(str(chunk.get("id") or ""), evidence_lexical_text(chunk)) for chunk in scoped_chunks],
        evidence_lexical_query(effective_query),
    )
    lexical_order = sorted(bm25_scores, key=lambda chunk_id: (-bm25_scores[chunk_id], chunk_id))
    bm25_ranks = {chunk_id: rank for rank, chunk_id in enumerate(lexical_order, start=1)}
    bm25_elapsed_ms = round((perf_counter() - bm25_started) * 1000, 3)
    chunks_by_id = {str(chunk.get("id") or ""): chunk for chunk in scoped_chunks}
    dense_started = perf_counter()
    dense_hits: list[dict[str, Any]] = []
    dense_meta: dict[str, Any] = {
        "status": "degraded" if not allowed_versions else "skipped",
        "denseDegraded": not allowed_versions,
        "reason": "empty_version_scope" if not allowed_versions else None,
        "hitCount": 0,
    }
    if allowed_versions:
        try:
            dense_hits, dense_meta = dense_knowledge_hits(
                repo,
                effective_query,
                top_k=max(int(top_k) * 2, 20),
                source_id="KS-PROJECT-FILE",
                document_version_ids=allowed_versions,
            )
        except Exception as exc:  # noqa: BLE001 - Dense failures degrade to BM25.
            dense_hits = []
            dense_meta = {
                "status": "degraded",
                "denseDegraded": True,
                "reason": "dense_retrieval_exception",
                "errorType": exc.__class__.__name__,
                "hitCount": 0,
            }
    dense_meta = {**dense_meta}
    dense_meta.setdefault("embeddingModel", None)
    dense_meta.setdefault("indexVersion", None)
    dense_ranks: dict[str, int] = {}
    for hit in dense_hits:
        chunk_id = str(hit.get("chunkId") or "")
        if chunk_id in chunks_by_id and chunk_id not in dense_ranks:
            dense_ranks[chunk_id] = len(dense_ranks) + 1
    fusion = rrf_fusion_config()
    candidate_ids = set(bm25_ranks) | set(dense_ranks)
    ranked_candidates = [
        normalize_evidence_candidate(
            chunks_by_id[chunk_id],
            project_id=project_id,
            bm25_score=bm25_scores.get(chunk_id, 0.0),
            bm25_rank=bm25_ranks.get(chunk_id),
            dense_rank=dense_ranks.get(chunk_id),
            fused_score=(
                (
                    1.0 / (fusion["k"] + bm25_ranks[chunk_id])
                    if chunk_id in bm25_ranks
                    else 0.0
                )
                + (
                    fusion["denseWeight"] / (fusion["k"] + dense_ranks[chunk_id])
                    if chunk_id in dense_ranks
                    else 0.0
                )
            ),
        )
        for chunk_id in candidate_ids
    ]
    ranked_candidates.sort(
        key=lambda candidate: (
            -float(candidate.get("fusedScore") or 0.0),
            -float(candidate.get("bm25Score") or 0.0),
            -_locator_completeness(candidate),
            str(candidate.get("candidateId") or ""),
        )
    )
    ranked_candidates = ranked_candidates[: max(0, int(top_k))]
    formal_candidates = [
        candidate for candidate in ranked_candidates if candidate["formalEvidenceEligible"]
    ]
    advisory_candidates = [
        candidate for candidate in ranked_candidates if not candidate["formalEvidenceEligible"]
    ]
    trace_id = f"RTR-{uuid4().hex[:8].upper()}"
    tenant_id = current_tenant_id()
    trace = {
        "id": trace_id,
        "retrievalTraceId": trace_id,
        "reviewRunId": review_run_id,
        "query": effective_query,
        "queryType": "material_evidence_search",
        "projectId": str(project_id),
        "nodeId": node_id,
        "tenantId": tenant_id,
        "filters": {
            "projectId": str(project_id),
            "nodeId": node_id,
            "tenantId": tenant_id,
            "documentVersionIds": allowed_versions,
        },
        "bm25Retrieval": {
            "candidateCount": len(bm25_ranks),
            "elapsedMs": bm25_elapsed_ms,
        },
        "denseRetrieval": {
            **dense_meta,
            "candidateCount": len(dense_ranks),
            "elapsedMs": round((perf_counter() - dense_started) * 1000, 3),
        },
        "fusion": {
            "method": "rrf",
            "k": fusion["k"],
            "denseWeight": fusion["denseWeight"],
        },
        "candidateCount": len(ranked_candidates),
        "formalCandidateCount": len(formal_candidates),
        "advisoryCandidateCount": len(advisory_candidates),
        "degraded": bool(dense_meta.get("denseDegraded")),
        "fallbackReason": dense_meta.get("reason") if dense_meta.get("denseDegraded") else None,
        "candidates": ranked_candidates,
        "elapsedMs": round((perf_counter() - started) * 1000, 3),
        "createdAt": server_time(),
    }
    if persist_trace:
        try:
            repo.state.setdefault("retrieval_traces", []).append(trace)
            trace["persistence"] = {"status": "persisted"}
        except Exception as exc:  # noqa: BLE001 - trace storage cannot discard retrieval.
            trace["persistence"] = {
                "status": "degraded",
                "reason": "trace_persistence_failed",
                "errorType": exc.__class__.__name__,
            }
            trace["degraded"] = True
            trace["fallbackReason"] = trace.get("fallbackReason") or "trace_persistence_failed"
    else:
        trace["persistence"] = {"status": "skipped"}
    return {
        "formalCandidates": formal_candidates,
        "advisoryCandidates": advisory_candidates,
        "allCandidates": ranked_candidates,
        "trace": trace,
        "degraded": bool(trace.get("degraded")),
        "fallbackReason": trace.get("fallbackReason"),
    }
