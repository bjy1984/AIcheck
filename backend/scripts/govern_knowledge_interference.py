from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.contracts.responses import server_time
from libs.db.repository import ensure_collections_loaded, flush_state, load_state, repo
from libs.knowledge_indexing import (
    OFFLINE_VECTOR_DIMENSIONS,
    chunk_quality_fields,
    metadata_interference_reasons,
    quarantine_interference_reasons,
    stable_id,
)

DEFAULT_SOURCE_ID = "KS-STANDARD-RULES"
GOVERNANCE_VERSION = "knowledge-interference-governance-v1"


def source_files(source_id: str) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id")): item
        for item in repo.state.get("knowledge_files", [])
        if str(item.get("sourceId") or "") == source_id
    }


def vector_chunk_id(row: dict[str, Any]) -> str:
    return str(row.get("chunkId") or (row.get("payload") or {}).get("chunkId") or "")


def clause_chunk_id(row: dict[str, Any]) -> str:
    return str(row.get("chunkId") or row.get("clauseId") or "")


def chunk_context(chunk: dict[str, Any], files: dict[str, dict[str, Any]]) -> str:
    file = files.get(str(chunk.get("fileId") or "")) or {}
    return str(chunk.get("contextType") or file.get("contextType") or "standard_reference")


def update_file_counts(file: dict[str, Any]) -> None:
    file_id = str(file.get("id") or "")
    chunks = [item for item in repo.state.get("knowledge_chunks", []) if str(item.get("fileId") or "") == file_id]
    vectors = [item for item in repo.state.get("knowledge_vectors", []) if str(item.get("fileId") or "") == file_id]
    dimensions = {int(item.get("dimensions") or 0) for item in vectors if item.get("dimensions")}
    complete = bool(chunks) and len(chunks) == len(vectors) and dimensions == {OFFLINE_VECTOR_DIMENSIONS}
    now = server_time()
    file["chunkCount"] = len(chunks)
    file["vectorCount"] = len(vectors)
    file["sliceStatus"] = "已切片" if chunks else "切片失败"
    file["vectorStatus"] = "已向量化" if complete else "向量化失败"
    file["vectorStatusReason"] = None if complete else "after_interference_governance_vector_parity_failed"
    file["updatedAt"] = now
    version = repo.find_one("versions", str(file.get("documentVersionId") or ""))
    if version:
        version["sliceStatus"] = file["sliceStatus"]
        version["vectorStatus"] = file["vectorStatus"]
        version["updatedAt"] = now


def update_source_counts(source_id: str) -> None:
    source = repo.find_one("knowledge_sources", source_id)
    if not source:
        return
    files = [item for item in repo.state.get("knowledge_files", []) if item.get("sourceId") == source_id]
    source["fileCount"] = len(files)
    source["chunkCount"] = sum(int(item.get("chunkCount") or 0) for item in files)
    source["vectorCount"] = sum(int(item.get("vectorCount") or 0) for item in files)
    source["vectorStatus"] = (
        "已向量化"
        if files and all(item.get("vectorStatus") == "已向量化" for item in files)
        else "部分失败"
    )
    source["updatedAt"] = server_time()


def build_plan(source_id: str, file_ids: set[str] | None = None) -> dict[str, Any]:
    files = source_files(source_id)
    selected_file_ids = set(files)
    if file_ids:
        selected_file_ids &= file_ids

    quarantine_chunks: list[dict[str, Any]] = []
    metadata_chunks: list[dict[str, Any]] = []
    quarantine_reasons_by_chunk: dict[str, list[str]] = {}
    metadata_reasons_by_chunk: dict[str, list[str]] = {}

    for chunk in repo.state.get("knowledge_chunks", []):
        if str(chunk.get("fileId") or "") not in selected_file_ids:
            continue
        context_type = chunk_context(chunk, files)
        text = chunk.get("text")
        quarantine_reasons = quarantine_interference_reasons(text, context_type=context_type)
        if quarantine_reasons:
            quarantine_chunks.append(chunk)
            quarantine_reasons_by_chunk[str(chunk.get("id") or "")] = quarantine_reasons
            continue
        metadata_reasons = metadata_interference_reasons(text, context_type=context_type)
        if metadata_reasons:
            existing_flags = {str(item) for item in chunk.get("qualityFlags") or []}
            if chunk.get("retrievalWeightTier") == "metadata" and set(metadata_reasons).issubset(existing_flags):
                continue
            metadata_chunks.append(chunk)
            metadata_reasons_by_chunk[str(chunk.get("id") or "")] = metadata_reasons

    chunk_ids = {str(item.get("id") or "") for item in quarantine_chunks}
    quarantine_vectors = [item for item in repo.state.get("knowledge_vectors", []) if vector_chunk_id(item) in chunk_ids]
    quarantine_clauses = [item for item in repo.state.get("knowledge_clauses", []) if clause_chunk_id(item) in chunk_ids]

    by_file: dict[str, dict[str, Any]] = {}
    for chunk in quarantine_chunks:
        file_id = str(chunk.get("fileId") or "")
        row = by_file.setdefault(
            file_id,
            {
                "fileId": file_id,
                "sourceRelativePath": chunk.get("sourceRelativePath"),
                "quarantinedChunks": 0,
                "metadataMarkedChunks": 0,
                "reasons": {},
            },
        )
        row["quarantinedChunks"] += 1
        for reason in quarantine_reasons_by_chunk.get(str(chunk.get("id") or ""), []):
            row["reasons"][reason] = int(row["reasons"].get(reason) or 0) + 1
    for chunk in metadata_chunks:
        file_id = str(chunk.get("fileId") or "")
        row = by_file.setdefault(
            file_id,
            {
                "fileId": file_id,
                "sourceRelativePath": chunk.get("sourceRelativePath"),
                "quarantinedChunks": 0,
                "metadataMarkedChunks": 0,
                "reasons": {},
            },
        )
        row["metadataMarkedChunks"] += 1
        for reason in metadata_reasons_by_chunk.get(str(chunk.get("id") or ""), []):
            row["reasons"][reason] = int(row["reasons"].get(reason) or 0) + 1

    return {
        "sourceId": source_id,
        "chunkIds": chunk_ids,
        "quarantineChunks": quarantine_chunks,
        "quarantineVectors": quarantine_vectors,
        "quarantineClauses": quarantine_clauses,
        "metadataChunks": metadata_chunks,
        "quarantineReasonsByChunk": quarantine_reasons_by_chunk,
        "metadataReasonsByChunk": metadata_reasons_by_chunk,
        "byFile": sorted(
            by_file.values(),
            key=lambda item: (
                -int(item.get("quarantinedChunks") or 0),
                -int(item.get("metadataMarkedChunks") or 0),
                str(item.get("sourceRelativePath") or ""),
            ),
        ),
    }


def mark_metadata_chunks(plan: dict[str, Any], files: dict[str, dict[str, Any]]) -> None:
    metadata_ids = {str(item.get("id") or "") for item in plan["metadataChunks"]}
    quality_by_chunk: dict[str, dict[str, Any]] = {}
    for chunk in plan["metadataChunks"]:
        context_type = chunk_context(chunk, files)
        fields = chunk_quality_fields(chunk.get("text"), context_type=context_type)
        if not fields:
            continue
        existing_flags = list(chunk.get("qualityFlags") or [])
        fields["qualityFlags"] = sorted({*existing_flags, *fields.get("qualityFlags", [])})
        chunk.update(fields)
        chunk["qualityGovernanceVersion"] = GOVERNANCE_VERSION
        quality_by_chunk[str(chunk.get("id") or "")] = fields

    for clause in repo.state.get("knowledge_clauses", []):
        chunk_id = clause_chunk_id(clause)
        if chunk_id not in metadata_ids or chunk_id not in quality_by_chunk:
            continue
        clause.update(quality_by_chunk[chunk_id])
        clause["qualityGovernanceVersion"] = GOVERNANCE_VERSION

    for vector in repo.state.get("knowledge_vectors", []):
        chunk_id = vector_chunk_id(vector)
        if chunk_id not in metadata_ids or chunk_id not in quality_by_chunk:
            continue
        fields = quality_by_chunk[chunk_id]
        vector.update(fields)
        payload = vector.get("payload") if isinstance(vector.get("payload"), dict) else {}
        payload.update(fields)
        vector["payload"] = payload
        vector["qualityGovernanceVersion"] = GOVERNANCE_VERSION


def apply_plan(plan: dict[str, Any]) -> dict[str, Any]:
    now = server_time()
    files = source_files(str(plan["sourceId"]))
    chunk_ids = set(plan["chunkIds"])
    mark_metadata_chunks(plan, files)

    vectors_by_chunk: dict[str, list[dict[str, Any]]] = {}
    for vector in plan["quarantineVectors"]:
        vectors_by_chunk.setdefault(vector_chunk_id(vector), []).append(vector)
    clauses_by_chunk: dict[str, list[dict[str, Any]]] = {}
    for clause in plan["quarantineClauses"]:
        clauses_by_chunk.setdefault(clause_chunk_id(clause), []).append(clause)

    existing = {
        str(item.get("chunkId") or ""): item
        for item in repo.state.setdefault("knowledge_chunk_quarantines", [])
    }
    for chunk in plan["quarantineChunks"]:
        chunk_id = str(chunk.get("id") or "")
        quarantine = {
            "id": stable_id("KQ", GOVERNANCE_VERSION, chunk_id),
            "chunkId": chunk_id,
            "fileId": chunk.get("fileId"),
            "documentId": chunk.get("documentId"),
            "documentVersionId": chunk.get("documentVersionId"),
            "sourceId": chunk.get("sourceId"),
            "sourceRelativePath": chunk.get("sourceRelativePath"),
            "pageNo": chunk.get("pageNo"),
            "reason": "weak_interference",
            "reasons": plan["quarantineReasonsByChunk"].get(chunk_id, []),
            "quarantineVersion": GOVERNANCE_VERSION,
            "quarantinedAt": now,
            "text": chunk.get("text"),
            "chunk": chunk,
            "vectors": vectors_by_chunk.get(chunk_id, []),
            "clauses": clauses_by_chunk.get(chunk_id, []),
        }
        existing[chunk_id] = quarantine

    repo.state["knowledge_chunk_quarantines"] = list(existing.values())
    repo.state["knowledge_chunks"] = [
        item for item in repo.state.get("knowledge_chunks", []) if str(item.get("id") or "") not in chunk_ids
    ]
    repo.state["knowledge_vectors"] = [
        item for item in repo.state.get("knowledge_vectors", []) if vector_chunk_id(item) not in chunk_ids
    ]
    repo.state["knowledge_clauses"] = [
        item for item in repo.state.get("knowledge_clauses", []) if clause_chunk_id(item) not in chunk_ids
    ]

    impacted_file_ids = {
        str(item.get("fileId") or "")
        for item in [*plan["quarantineChunks"], *plan["metadataChunks"]]
        if item.get("fileId")
    }
    for file_id in impacted_file_ids:
        file = files.get(file_id)
        if file:
            update_file_counts(file)
    repo.sync_standard_page_index_for_source(str(plan["sourceId"]))
    update_source_counts(str(plan["sourceId"]))
    return {
        "quarantinedChunks": len(plan["quarantineChunks"]),
        "quarantinedVectors": len(plan["quarantineVectors"]),
        "quarantinedClauses": len(plan["quarantineClauses"]),
        "metadataMarkedChunks": len(plan["metadataChunks"]),
        "impactedFiles": len(impacted_file_ids),
        "byFile": plan["byFile"],
    }


def sample_rows(items: list[dict[str, Any]], reasons_by_chunk: dict[str, list[str]], limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items[:limit]:
        chunk_id = str(item.get("id") or "")
        rows.append(
            {
                "id": chunk_id,
                "fileId": item.get("fileId"),
                "pageNo": item.get("pageNo"),
                "reasons": reasons_by_chunk.get(chunk_id, []),
                "text": str(item.get("text") or "")[:220],
                "sourceRelativePath": item.get("sourceRelativePath"),
            }
        )
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Govern low-value and metadata interference in rules knowledge chunks.")
    parser.add_argument("--source-id", default=DEFAULT_SOURCE_ID)
    parser.add_argument("--file-id", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_state()
    # 本脚本会重建 knowledge_vectors/page_index（按 fileId 剔除后重写）。
    # 它们是延迟加载集合，load_state 会跳过——内存空时重建等于清库。
    ensure_collections_loaded("knowledge_vectors", "knowledge_page_index_nodes")
    plan = build_plan(str(args.source_id), set(args.file_id) if args.file_id else None)
    if args.dry_run:
        result = {
            "status": "dry_run",
            "sourceId": args.source_id,
            "quarantineChunkCount": len(plan["quarantineChunks"]),
            "quarantineVectorCount": len(plan["quarantineVectors"]),
            "quarantineClauseCount": len(plan["quarantineClauses"]),
            "metadataMarkedChunkCount": len(plan["metadataChunks"]),
            "byFile": plan["byFile"],
            "quarantineSamples": sample_rows(plan["quarantineChunks"], plan["quarantineReasonsByChunk"]),
            "metadataSamples": sample_rows(plan["metadataChunks"], plan["metadataReasonsByChunk"]),
        }
    else:
        result = {"status": "success", **apply_plan(plan)}
        flush_state()
    print(json.dumps(result, ensure_ascii=False, indent=None if args.json else 2, separators=(",", ":") if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
