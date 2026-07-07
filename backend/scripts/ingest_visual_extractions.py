from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.contracts.responses import server_time
from libs.db.repository import flush_state, load_state, repo
from libs.knowledge_indexing import (
    EMBED_BATCH_SIZE,
    OFFLINE_EMBEDDING_MODEL,
    OFFLINE_VECTOR_DIMENSIONS,
    STANDARD_INDEX_VERSION,
    build_vector_rows,
    chunk_text,
    offline_hash_embeddings,
)


VISUAL_EXTRACTION_ROOT = BACKEND_ROOT / "data" / "visual_extractions"
VISUAL_SOURCE_METHOD = "codex_visual_manual_extraction"
VISUAL_CONTEXT_TYPE = "visual_extracted_reference"
VISUAL_EXTRACTION_VERSION = "visual-extraction-v1"


def compact_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def relative_or_raw_path(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    path = Path(raw)
    if not path.is_absolute():
        return raw
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT.resolve()))
    except ValueError:
        return raw


def load_sidecar(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Sidecar must be a JSON object: {path}")
    if payload.get("sourceMethod") != VISUAL_SOURCE_METHOD:
        raise ValueError(f"Sidecar sourceMethod must be {VISUAL_SOURCE_METHOD}: {path}")
    pages = payload.get("pages")
    if not isinstance(pages, list):
        raise ValueError(f"Sidecar pages must be a list: {path}")
    return payload


def sidecar_paths(args: argparse.Namespace) -> list[Path]:
    if args.sidecar:
        return [Path(item).expanduser().resolve() for item in args.sidecar]
    if args.file_id:
        return [(VISUAL_EXTRACTION_ROOT / f"{file_id}.json").resolve() for file_id in args.file_id]
    if args.all:
        return sorted(VISUAL_EXTRACTION_ROOT.glob("*.json"))
    raise SystemExit("Pass --all, --file-id, or --sidecar.")


def find_file(sidecar: dict[str, Any]) -> dict[str, Any]:
    file_id = str(sidecar.get("fileId") or "").strip()
    if file_id:
        file = repo.find_one("knowledge_files", file_id)
        if file:
            return file
    source_relative_path = str(sidecar.get("sourceRelativePath") or "").strip()
    if source_relative_path:
        for file in repo.state.get("knowledge_files", []):
            if file.get("sourceRelativePath") == source_relative_path:
                return file
    raise KeyError(f"Cannot resolve sidecar file: {file_id or source_relative_path}")


def remove_existing_visual_records(file_id: str) -> dict[str, int]:
    old_visual_chunk_ids = {
        str(item.get("id"))
        for item in repo.state.get("knowledge_chunks", [])
        if item.get("fileId") == file_id
        and (
            str(item.get("id") or "").startswith("VCHK-")
            or item.get("sourceMethod") == VISUAL_SOURCE_METHOD
            or item.get("contextType") == VISUAL_CONTEXT_TYPE
        )
    }
    old_vector_ids = {
        str(item.get("id"))
        for item in repo.state.get("knowledge_vectors", [])
        if item.get("fileId") == file_id
        and (
            str(item.get("chunkId") or "") in old_visual_chunk_ids
            or str(item.get("id") or "").startswith("KV-VCHK-")
            or (item.get("payload") or {}).get("sourceMethod") == VISUAL_SOURCE_METHOD
        )
    }
    old_clause_ids = {
        str(item.get("id"))
        for item in repo.state.get("knowledge_clauses", [])
        if item.get("fileId") == file_id
        and (
            str(item.get("chunkId") or item.get("clauseId") or "") in old_visual_chunk_ids
            or str(item.get("id") or "").startswith("KC-VCHK-")
        )
    }
    repo.state["knowledge_chunks"] = [
        item for item in repo.state.get("knowledge_chunks", []) if str(item.get("id")) not in old_visual_chunk_ids
    ]
    repo.state["knowledge_vectors"] = [
        item for item in repo.state.get("knowledge_vectors", []) if str(item.get("id")) not in old_vector_ids
    ]
    repo.state["knowledge_clauses"] = [
        item for item in repo.state.get("knowledge_clauses", []) if str(item.get("id")) not in old_clause_ids
    ]
    return {"chunks": len(old_visual_chunk_ids), "vectors": len(old_vector_ids), "clauses": len(old_clause_ids)}


def page_section_path(file: dict[str, Any], page: dict[str, Any], page_no: int) -> list[str]:
    file_name = str(file.get("fileName") or file.get("sourceRelativePath") or file.get("id"))
    raw_path = page.get("sectionPath") or []
    section_path = [str(item).strip() for item in raw_path if str(item or "").strip()]
    if not section_path or section_path[0] != file_name:
        section_path.insert(0, file_name)
    title = compact_text(page.get("title"))
    if title and title not in section_path:
        section_path.append(title)
    if len(section_path) == 1:
        section_path.append(f"第 {page_no} 页")
    return section_path


def page_text(page: dict[str, Any]) -> str:
    body_parts: list[str] = []
    for key in ("summary", "extractedText", "text"):
        value = compact_text(page.get(key))
        if value and value not in body_parts:
            body_parts.append(value)
    if not body_parts:
        return ""
    parts: list[str] = []
    title = compact_text(page.get("title"))
    if title:
        parts.append(title)
    for value in body_parts:
        if value not in parts:
            parts.append(value)
    return "\n".join(parts).strip()


def visual_chunks_from_sidecar(file: dict[str, Any], sidecar: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    chunks: list[dict[str, Any]] = []
    skipped_pages = 0
    pages = sorted(
        [item for item in sidecar.get("pages") or [] if isinstance(item, dict)],
        key=lambda item: int(item.get("pageNo") or 0),
    )
    for page in pages:
        page_no = int(page.get("pageNo") or 0)
        if page_no <= 0:
            skipped_pages += 1
            continue
        text = page_text(page)
        if not text:
            skipped_pages += 1
            continue
        section_path = page_section_path(file, page, page_no)
        image_path = relative_or_raw_path(page.get("imagePath"))
        confidence = str(page.get("confidence") or sidecar.get("confidence") or "medium")
        needs_human_verification = bool(page.get("needsHumanVerification", sidecar.get("needsHumanVerification", True)))
        for piece_index, piece in enumerate(chunk_text(text), start=1):
            chunk_id = f"VCHK-{file['id']}-{page_no:04d}-{piece_index:02d}"
            chunks.append(
                {
                    "id": chunk_id,
                    "fileId": file["id"],
                    "documentId": file.get("documentId"),
                    "documentVersionId": file.get("documentVersionId"),
                    "sourceId": file.get("sourceId"),
                    "sourceRelativePath": file.get("sourceRelativePath"),
                    "chunkNo": 800000 + page_no * 100 + piece_index,
                    "text": piece,
                    "pageNo": page_no,
                    "bbox": page.get("bbox"),
                    "sectionPath": section_path,
                    "tokenCount": max(1, len(piece) // 2),
                    "indexVersion": STANDARD_INDEX_VERSION,
                    "pageIndexNodeIds": [],
                    "sourceMethod": VISUAL_SOURCE_METHOD,
                    "contextType": VISUAL_CONTEXT_TYPE,
                    "visualExtractionVersion": VISUAL_EXTRACTION_VERSION,
                    "pageImagePath": image_path,
                    "confidence": confidence,
                    "needsHumanVerification": needs_human_verification,
                    "createdAt": None,
                }
            )
    return chunks, skipped_pages


def mark_task_success(task_type: str, file: dict[str, Any], message: str) -> None:
    task = repo.upsert_knowledge_task(
        task_type=task_type,
        target_id=file["id"],
        target_name=file.get("fileName") or file["id"],
        document_id=file.get("documentId"),
        version_id=file.get("documentVersionId"),
        status="成功",
        progress=100,
    )
    now = server_time()
    task["finishedAt"] = now
    task["updatedAt"] = now
    task.pop("errorMessage", None)
    repo.append_task_log(task, "info", message)


def update_file_status(file: dict[str, Any], *, visual_chunk_count: int, skipped_pages: int) -> None:
    file_chunks = [item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == file.get("id")]
    file_vectors = [item for item in repo.state.get("knowledge_vectors", []) if item.get("fileId") == file.get("id")]
    dimensions = {int(item.get("dimensions") or 0) for item in file_vectors if item.get("dimensions")}
    complete = bool(file_chunks) and len(file_vectors) == len(file_chunks) and dimensions == {OFFLINE_VECTOR_DIMENSIONS}
    now = server_time()
    file["sliceStatus"] = "已切片" if file_chunks else "切片失败"
    file["vectorStatus"] = "已向量化" if complete else "向量化失败"
    file["chunkCount"] = len(file_chunks)
    file["vectorCount"] = len(file_vectors)
    file["embeddingModel"] = OFFLINE_EMBEDDING_MODEL
    file["indexVersion"] = STANDARD_INDEX_VERSION
    file["vectorDimensions"] = OFFLINE_VECTOR_DIMENSIONS if dimensions else file.get("vectorDimensions")
    file["visualExtractionStatus"] = "已提取" if visual_chunk_count else "提取失败"
    file["visualChunkCount"] = visual_chunk_count
    file["visualSkippedPageCount"] = skipped_pages
    file["visualExtractionVersion"] = VISUAL_EXTRACTION_VERSION
    file["needsHumanVerification"] = True
    file["updatedAt"] = now
    version = repo.find_one("versions", str(file.get("documentVersionId") or ""))
    if version:
        version["sliceStatus"] = file["sliceStatus"]
        version["vectorStatus"] = file["vectorStatus"]
        version["visualExtractionStatus"] = file["visualExtractionStatus"]
        version["updatedAt"] = now
    document = repo.find_one("documents", str(file.get("documentId") or ""))
    if document:
        document["visualExtractionStatus"] = file["visualExtractionStatus"]
        document["updatedAt"] = now


def update_source_counts(source_id: str) -> None:
    source = repo.find_one("knowledge_sources", source_id)
    if not source:
        return
    files = [item for item in repo.state.get("knowledge_files", []) if item.get("sourceId") == source_id]
    source["fileCount"] = len(files)
    source["chunkCount"] = sum(int(item.get("chunkCount") or 0) for item in files)
    source["vectorCount"] = sum(int(item.get("vectorCount") or 0) for item in files)
    if files and all(item.get("vectorStatus") == "已向量化" for item in files):
        source["vectorStatus"] = "已向量化"
    elif any(item.get("vectorStatus") == "向量化失败" for item in files):
        source["vectorStatus"] = "部分失败"
    else:
        source["vectorStatus"] = "待向量化"
    source["embeddingModel"] = OFFLINE_EMBEDDING_MODEL
    source["indexVersion"] = STANDARD_INDEX_VERSION
    source["updatedAt"] = server_time()


def ingest_sidecar(path: Path) -> dict[str, Any]:
    sidecar = load_sidecar(path)
    file = find_file(sidecar)
    removed = remove_existing_visual_records(str(file["id"]))
    chunks, skipped_pages = visual_chunks_from_sidecar(file, sidecar)
    now = server_time()
    for chunk in chunks:
        chunk["createdAt"] = now
        chunk["updatedAt"] = now
    repo.state.setdefault("knowledge_chunks", []).extend(chunks)

    vector_rows: list[dict[str, Any]] = []
    for offset in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[offset : offset + EMBED_BATCH_SIZE]
        vectors = offline_hash_embeddings([str(chunk.get("text") or "") for chunk in batch])
        vector_rows.extend(
            build_vector_rows(
                file,
                batch,
                vectors,
                embedding_model=OFFLINE_EMBEDDING_MODEL,
                index_version=STANDARD_INDEX_VERSION,
            )
        )
    chunk_by_id = {str(item.get("id")): item for item in chunks}
    for row in vector_rows:
        chunk = chunk_by_id.get(str(row.get("chunkId")), {})
        row["createdAt"] = now
        row["updatedAt"] = now
        row["sourceMethod"] = VISUAL_SOURCE_METHOD
        row["contextType"] = VISUAL_CONTEXT_TYPE
        row["pageImagePath"] = chunk.get("pageImagePath")
        row["visualExtractionVersion"] = VISUAL_EXTRACTION_VERSION
        payload = row.setdefault("payload", {})
        payload["sourceMethod"] = VISUAL_SOURCE_METHOD
        payload["contextType"] = VISUAL_CONTEXT_TYPE
        payload["pageImagePath"] = chunk.get("pageImagePath")
        payload["confidence"] = chunk.get("confidence")
        payload["needsHumanVerification"] = chunk.get("needsHumanVerification")
        payload["visualExtractionVersion"] = VISUAL_EXTRACTION_VERSION
    repo.state.setdefault("knowledge_vectors", []).extend(vector_rows)

    update_file_status(file, visual_chunk_count=len(chunks), skipped_pages=skipped_pages)
    if chunks:
        mark_task_success("slice", file, "Visual manual extraction chunks ingested without OCR.")
        mark_task_success("vector", file, "offline-hash-v1 vectors generated for visual manual extraction chunks.")
    source_id = str(file.get("sourceId") or "KS-STANDARD-RULES")
    repo.sync_standard_page_index_for_source(source_id)
    update_source_counts(source_id)
    return {
        "sidecar": str(path),
        "fileId": file.get("id"),
        "sourceRelativePath": file.get("sourceRelativePath"),
        "status": "success" if chunks else "failed",
        "removed": removed,
        "visualChunkCount": len(chunks),
        "skippedPages": skipped_pages,
        "chunkCount": file.get("chunkCount"),
        "vectorCount": file.get("vectorCount"),
        "vectorStatus": file.get("vectorStatus"),
        "embeddingModel": OFFLINE_EMBEDDING_MODEL,
        "indexVersion": STANDARD_INDEX_VERSION,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest Codex visual manual extraction sidecars into knowledge vectors.")
    parser.add_argument("--sidecar", action="append", default=[], help="Path to a visual extraction JSON sidecar. Can repeat.")
    parser.add_argument("--file-id", action="append", default=[], help="Read backend/data/visual_extractions/{fileId}.json. Can repeat.")
    parser.add_argument("--all", action="store_true", help="Ingest all visual extraction sidecars.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_state()
    paths = sidecar_paths(args)
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        print(json.dumps({"status": "failed", "reason": "missing_sidecar", "missing": missing}, ensure_ascii=False))
        return 2
    results = [ingest_sidecar(path) for path in paths]
    flush_state()
    failed = [item for item in results if item.get("status") != "success"]
    summary = {
        "status": "success" if not failed else "partial_success",
        "processed": len(results),
        "failed": len(failed),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, separators=(",", ":") if args.json else None, indent=None if args.json else 2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
