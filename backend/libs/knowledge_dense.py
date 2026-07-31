from __future__ import annotations

import os
from typing import Any

from libs.knowledge_indexing import (
    OFFLINE_EMBEDDING_MODEL,
    STANDARD_INDEX_VERSION,
    offline_hash_embedding,
)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DEFAULT_QUERY_INSTRUCTION = "给定工程检验审查问题，检索最相关的标准条款和审查依据"


def query_text_for_model(query: str, model_id: str) -> str:
    """Qwen3-Embedding is instruction-tuned with asymmetric query/document
    prompts — instructed queries measurably improve retrieval. Documents are
    embedded plain; only the query side gets the instruction."""
    if not _env_bool("AICHECK_EMBEDDING_QUERY_INSTRUCTION", True):
        return query
    if "qwen3-embedding" not in str(model_id or "").lower():
        return query
    task = str(os.getenv("AICHECK_EMBEDDING_QUERY_INSTRUCTION_TEXT") or DEFAULT_QUERY_INSTRUCTION)
    return f"Instruct: {task}\nQuery: {query}"


def dense_knowledge_hits(
    repo: Any,
    query: str,
    *,
    top_k: int = 20,
    source_id: str | None = None,
    index_version: str | None = None,
    document_version_ids: list[str] | None = None,
    timeout: float = 30,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compute query embedding and return ranked dense hits plus diagnostics.

    Production rule: never fall back to the offline hash embedding for the QUERY
    when the target index was built with a semantic model — the index_version
    filter would silently return zero hits. In that case dense retrieval is
    skipped and the caller gets ``denseDegraded: True`` so traces and readiness
    can surface the degradation instead of hiding it.
    """
    meta: dict[str, Any] = {
        "status": "ok",
        "denseDegraded": False,
        "embeddingModel": None,
        "indexVersion": None,
        "reason": None,
        "hitCount": 0,
    }
    if _env_bool("AICHECK_RETRIEVAL_DENSE_DISABLE", False):
        meta.update({"status": "disabled", "reason": "dense_retrieval_disabled"})
        return [], meta

    from libs.integrations.embedding_client import EmbeddingClient

    force_offline = _env_bool("AICHECK_EMBEDDING_FORCE_OFFLINE_HASH", False)
    client = EmbeddingClient()
    query_embedding: list[float] | None = None
    if client.enabled and not force_offline:
        try:
            vectors = client.embed_sync([query_text_for_model(str(query or ""), client.model_id)], timeout=timeout)
            candidate = (vectors[0] if vectors else {}).get("embedding")
            if isinstance(candidate, list) and candidate:
                query_embedding = candidate
        except Exception:  # noqa: BLE001 - remote embedding failure degrades to BM25.
            query_embedding = None
        if query_embedding is None:
            # Fail loud: skip dense entirely rather than hash-querying a semantic index.
            meta.update(
                {
                    "status": "degraded",
                    "denseDegraded": True,
                    "reason": "remote_embedding_unavailable_dense_skipped",
                    "embeddingModel": client.model_id,
                    "indexVersion": index_version or client.index_version,
                }
            )
            return [], meta
        meta["embeddingModel"] = client.model_id
        meta["indexVersion"] = index_version or client.index_version
    else:
        # Offline-hash is the configured target here (client disabled or forced
        # offline), so hash query vs hash index is consistent.
        query_embedding = offline_hash_embedding(str(query or ""))
        meta["embeddingModel"] = OFFLINE_EMBEDDING_MODEL
        meta["indexVersion"] = index_version or STANDARD_INDEX_VERSION

    search_args: dict[str, Any] = {
        "top_k": int(top_k or 20),
        "source_id": source_id,
        "index_version": meta["indexVersion"],
    }
    if document_version_ids is not None:
        search_args["document_version_ids"] = document_version_ids
    hits: list[dict[str, Any]] = []
    try:
        if getattr(repo, "postgres_enabled", False) and getattr(repo, "sync_postgres", None) is not None:
            hits = repo.search_knowledge_vectors(query_embedding, **search_args)
        if not hits:
            hits = repo.search_local_knowledge_vectors(query_embedding, **search_args)
    except Exception:  # noqa: BLE001 - vector-store failure degrades to BM25.
        meta.update({"status": "degraded", "denseDegraded": True, "reason": "vector_search_failed"})
        return [], meta
    meta["hitCount"] = len(hits)
    return hits, meta
