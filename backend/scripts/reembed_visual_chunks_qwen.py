from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.db.repository import flush_state, load_state, repo
from libs.integrations.embedding_client import EmbeddingClient
from libs.knowledge_indexing import (
    EMBED_BATCH_SIZE,
    QWEN3_EMBEDDING_MODEL,
    QWEN3_INDEX_VERSION,
)

DEFAULT_SOURCE_ID = "KS-STANDARD-RULES"
VISUAL_SOURCE_METHOD = "codex_visual_manual_extraction"


def chunk_id(row: dict[str, Any]) -> str:
    return str(row.get("chunkId") or (row.get("payload") or {}).get("chunkId") or "")


def candidate_file_ids(source_id: str) -> list[str]:
    source_file_ids = {
        str(item.get("id") or "")
        for item in repo.state.get("knowledge_files", [])
        if str(item.get("sourceId") or "") == source_id
    }
    visual_chunk_ids_by_file: dict[str, set[str]] = {}
    for chunk in repo.state.get("knowledge_chunks", []):
        file_id = str(chunk.get("fileId") or "")
        if file_id not in source_file_ids:
            continue
        if chunk.get("sourceMethod") == VISUAL_SOURCE_METHOD or chunk.get("contextType") == "visual_extracted_reference":
            visual_chunk_ids_by_file.setdefault(file_id, set()).add(str(chunk.get("id") or ""))
    if not visual_chunk_ids_by_file:
        return []
    hash_visual_file_ids: set[str] = set()
    for vector in repo.state.get("knowledge_vectors", []):
        file_id = str(vector.get("fileId") or "")
        if file_id not in visual_chunk_ids_by_file:
            continue
        if chunk_id(vector) in visual_chunk_ids_by_file[file_id] and vector.get("embeddingModel") != QWEN3_EMBEDDING_MODEL:
            hash_visual_file_ids.add(file_id)
    return sorted(hash_visual_file_ids)


def embed_file(file_id: str, client: EmbeddingClient) -> dict[str, Any]:
    file = repo.find_one("knowledge_files", file_id)
    if not file:
        return {"fileId": file_id, "status": "missing"}
    chunks = sorted(
        [item for item in repo.state.get("knowledge_chunks", []) if str(item.get("fileId") or "") == file_id],
        key=lambda item: int(item.get("chunkNo") or 0),
    )
    vectors: list[dict[str, Any]] = []
    for offset in range(0, len(chunks), EMBED_BATCH_SIZE):
        texts = [str(chunk.get("text") or "") for chunk in chunks[offset : offset + EMBED_BATCH_SIZE]]
        for item in client.embed_sync(texts):
            vectors.append({**item, "index": offset + int(item.get("index") or 0)})
    result = repo.apply_embed_result(
        file_id,
        len(vectors),
        vectors=vectors,
        embedding_model=client.model_id,
        index_version=client.index_version,
        expected_dimensions=client.dimensions,
        vector_status_reason="reembedded_visual_chunks_qwen",
    )
    return {
        **result,
        "sourceRelativePath": file.get("sourceRelativePath"),
        "chunkCount": len(chunks),
        "dimensions": client.dimensions,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-embed visual manual extraction chunks with the active Qwen3 embedding service.")
    parser.add_argument("--source-id", default=DEFAULT_SOURCE_ID)
    parser.add_argument("--file-id", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_state()
    file_ids = list(dict.fromkeys(args.file_id or candidate_file_ids(str(args.source_id))))
    if args.dry_run:
        result = {"status": "dry_run", "sourceId": args.source_id, "fileIds": file_ids, "fileCount": len(file_ids)}
        print(json.dumps(result, ensure_ascii=False, indent=None if args.json else 2, separators=(",", ":") if args.json else None))
        return 0
    client = EmbeddingClient()
    if not client.enabled:
        print(json.dumps({"status": "failed", "reason": "embedding_service_not_configured"}, ensure_ascii=False))
        return 2
    health = client.health()
    if client.model_id != QWEN3_EMBEDDING_MODEL or client.index_version != QWEN3_INDEX_VERSION or client.dimensions != 1024:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "unexpected_embedding_target",
                    "model": client.model_id,
                    "indexVersion": client.index_version,
                    "dimensions": client.dimensions,
                },
                ensure_ascii=False,
            )
        )
        return 2
    results = [embed_file(file_id, client) for file_id in file_ids]
    flush_state()
    failed = [item for item in results if item.get("status") != "success"]
    result = {
        "status": "success" if not failed else "partial_success",
        "health": health,
        "processed": len(results),
        "failed": len(failed),
        "results": results,
    }
    print(json.dumps(result, ensure_ascii=False, indent=None if args.json else 2, separators=(",", ":") if args.json else None))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
