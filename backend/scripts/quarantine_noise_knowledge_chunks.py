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
from libs.db.repository import flush_state, load_state, repo
from libs.knowledge_indexing import OFFLINE_VECTOR_DIMENSIONS, noise_like_text, stable_id

DEFAULT_SOURCE_ID = "KS-STANDARD-RULES"
QUARANTINE_VERSION = "noise-watermark-quarantine-v1"


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
    file["vectorStatusReason"] = None if complete else "after_noise_quarantine_vector_parity_failed"
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
    noise_chunks = [
        item
        for item in repo.state.get("knowledge_chunks", [])
        if str(item.get("fileId") or "") in selected_file_ids and noise_like_text(item.get("text"))
    ]
    chunk_ids = {str(item.get("id") or "") for item in noise_chunks}
    noise_vectors = [item for item in repo.state.get("knowledge_vectors", []) if vector_chunk_id(item) in chunk_ids]
    noise_clauses = [item for item in repo.state.get("knowledge_clauses", []) if clause_chunk_id(item) in chunk_ids]
    by_file: dict[str, dict[str, Any]] = {}
    for chunk in noise_chunks:
        file_id = str(chunk.get("fileId") or "")
        row = by_file.setdefault(
            file_id,
            {
                "fileId": file_id,
                "sourceRelativePath": chunk.get("sourceRelativePath"),
                "chunkCount": 0,
                "vectorCount": 0,
                "clauseCount": 0,
            },
        )
        row["chunkCount"] += 1
    for vector in noise_vectors:
        row = by_file.setdefault(str(vector.get("fileId") or ""), {"fileId": vector.get("fileId")})
        row["vectorCount"] = int(row.get("vectorCount") or 0) + 1
    for clause in noise_clauses:
        row = by_file.setdefault(str(clause.get("fileId") or ""), {"fileId": clause.get("fileId")})
        row["clauseCount"] = int(row.get("clauseCount") or 0) + 1
    return {
        "sourceId": source_id,
        "chunkIds": chunk_ids,
        "chunks": noise_chunks,
        "vectors": noise_vectors,
        "clauses": noise_clauses,
        "byFile": sorted(by_file.values(), key=lambda item: (-int(item.get("chunkCount") or 0), str(item.get("sourceRelativePath") or ""))),
    }


def apply_quarantine(plan: dict[str, Any]) -> dict[str, Any]:
    now = server_time()
    chunk_ids = set(plan["chunkIds"])
    vectors_by_chunk: dict[str, list[dict[str, Any]]] = {}
    for vector in plan["vectors"]:
        vectors_by_chunk.setdefault(vector_chunk_id(vector), []).append(vector)
    clauses_by_chunk: dict[str, list[dict[str, Any]]] = {}
    for clause in plan["clauses"]:
        clauses_by_chunk.setdefault(clause_chunk_id(clause), []).append(clause)

    existing = {
        str(item.get("chunkId") or ""): item
        for item in repo.state.setdefault("knowledge_chunk_quarantines", [])
    }
    for chunk in plan["chunks"]:
        chunk_id = str(chunk.get("id") or "")
        quarantine = {
            "id": stable_id("KQ", QUARANTINE_VERSION, chunk_id),
            "chunkId": chunk_id,
            "fileId": chunk.get("fileId"),
            "documentId": chunk.get("documentId"),
            "documentVersionId": chunk.get("documentVersionId"),
            "sourceId": chunk.get("sourceId"),
            "sourceRelativePath": chunk.get("sourceRelativePath"),
            "pageNo": chunk.get("pageNo"),
            "reason": "noise_like_watermark",
            "quarantineVersion": QUARANTINE_VERSION,
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

    impacted_file_ids = {str(item.get("fileId") or "") for item in plan["chunks"]}
    files = source_files(str(plan["sourceId"]))
    for file_id in impacted_file_ids:
        file = files.get(file_id)
        if file:
            update_file_counts(file)
    repo.sync_standard_page_index_for_source(str(plan["sourceId"]))
    update_source_counts(str(plan["sourceId"]))
    return {
        "quarantinedChunks": len(plan["chunks"]),
        "quarantinedVectors": len(plan["vectors"]),
        "quarantinedClauses": len(plan["clauses"]),
        "impactedFiles": len(impacted_file_ids),
        "byFile": plan["byFile"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Move watermark/download-site knowledge chunks out of the active vector index.")
    parser.add_argument("--source-id", default=DEFAULT_SOURCE_ID)
    parser.add_argument("--file-id", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_state()
    plan = build_plan(str(args.source_id), set(args.file_id) if args.file_id else None)
    if args.dry_run:
        result = {
            "status": "dry_run",
            "sourceId": args.source_id,
            "chunkCount": len(plan["chunks"]),
            "vectorCount": len(plan["vectors"]),
            "clauseCount": len(plan["clauses"]),
            "byFile": plan["byFile"],
        }
    else:
        result = {"status": "success", **apply_quarantine(plan)}
        flush_state()
    print(json.dumps(result, ensure_ascii=False, indent=None if args.json else 2, separators=(",", ":") if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
