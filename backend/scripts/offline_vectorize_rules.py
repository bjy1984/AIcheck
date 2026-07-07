from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from apps.api.routes import (
    RULES_BUSINESS_RULES_PATH,
    RULES_STANDARDS_ROOT,
    STANDARD_LIBRARY_SOURCE_NAME,
    create_imported_knowledge_records,
    iter_rules_import_files,
    knowledge_source_for_import,
    remove_knowledge_file_records,
    safe_relative_path,
    safe_upload_file_name,
    stable_knowledge_record_seed,
    sync_knowledge_source_counts,
)
from libs.contracts.responses import server_time
from libs.db.repository import flush_state, load_state, repo
from libs.db.seed import STANDARD_RULES_SOURCE_ID, STANDARD_RULES_VERSION
from libs.integrations.embedding_client import EmbeddingClient
from libs.integrations.ocr_client import OcrClient
from libs.knowledge_indexing import (
    EMBED_BATCH_SIZE,
    OFFLINE_EMBEDDING_MODEL,
    STANDARD_INDEX_VERSION,
    active_embedding_target,
    offline_hash_embeddings,
    units_from_fragments,
    units_from_local_file,
)


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name) or default)
    except (TypeError, ValueError):
        return default


def mark_ocr_success(
    document: dict[str, Any],
    version: dict[str, Any],
    file: dict[str, Any],
    task: dict[str, Any],
    *,
    message: str,
) -> None:
    now = server_time()
    document["currentOcrStatus"] = "已识别"
    document["updatedAt"] = now
    version["ocrStatus"] = "已识别"
    version["updatedAt"] = now
    file["ocrStatus"] = "已识别"
    file["updatedAt"] = now
    task["status"] = "成功"
    task["progress"] = 100
    task["finishedAt"] = now
    task["updatedAt"] = now
    repo.append_task_log(task, "info", message)


def mark_ocr_failed(document: dict[str, Any], version: dict[str, Any], file: dict[str, Any], task: dict[str, Any]) -> None:
    now = server_time()
    message = "离线文本抽取失败：没有可抽取 text layer，未生成假切片或假向量。"
    document["currentOcrStatus"] = "识别失败"
    document["updatedAt"] = now
    version["ocrStatus"] = "识别失败"
    version["sliceStatus"] = "切片失败"
    version["vectorStatus"] = "向量化失败"
    version["updatedAt"] = now
    file["ocrStatus"] = "识别失败"
    file["sliceStatus"] = "切片失败"
    file["vectorStatus"] = "向量化失败"
    file["updatedAt"] = now
    repo.mark_task_failed(task, message)
    slice_task = repo.upsert_knowledge_task(
        task_type="slice",
        target_id=file["id"],
        target_name=file["fileName"],
        document_id=document["id"],
        version_id=version["id"],
    )
    vector_task = repo.upsert_knowledge_task(
        task_type="vector",
        target_id=file["id"],
        target_name=file["fileName"],
        document_id=document["id"],
        version_id=version["id"],
    )
    repo.mark_task_failed(slice_task, "切片任务失败：离线文本抽取为空。")
    repo.mark_task_failed(vector_task, "向量化任务失败：没有可向量化切片。")


def pdf_page_count(path: Path) -> int:
    if path.suffix.lower() != ".pdf":
        return 0
    try:
        import fitz  # type: ignore

        with fitz.open(str(path)) as document:
            return int(document.page_count)
    except Exception:
        return 0


def should_use_remote_ocr(path: Path, units: list[dict[str, Any]]) -> bool:
    if path.suffix.lower() != ".pdf":
        return False
    if not units:
        return True
    page_count = pdf_page_count(path)
    covered_pages = {int(item.get("pageNo") or 0) for item in units if item.get("pageNo")}
    text_chars = sum(len(str(item.get("text") or "")) for item in units)
    if page_count and len(covered_pages) < max(1, int(page_count * 0.75)):
        return True
    return text_chars < 240


def remote_ocr_units(path: Path, document: dict[str, Any], version: dict[str, Any], file: dict[str, Any], task: dict[str, Any]) -> list[dict[str, Any]]:
    client = OcrClient()
    if not client.enabled:
        return []
    payload = {
        "documentId": document["id"],
        "documentVersionId": version["id"],
        "documentType": "standard",
        "profileId": "standard_rules_ocr_v1",
        "storageKey": version.get("storageKey"),
        "fileName": file.get("fileName") or path.name,
        "options": {
            "standardIndexingStrategy": "auto_text_layer_then_remote_ocr",
            "preferTextLayer": True,
            "enableFallback": True,
            "enableTables": env_bool("AICHECK_RULES_OCR_ENABLE_TABLES", False),
            "enableSeals": False,
            "quickMode": env_bool("AICHECK_RULES_OCR_QUICK_MODE", True),
            "disableRemediation": env_bool("AICHECK_RULES_OCR_DISABLE_REMEDIATION", True),
            "renderDpi": env_int("AICHECK_RULES_OCR_RENDER_DPI", 220),
            "maxLongSide": env_int("AICHECK_RULES_OCR_MAX_LONG_SIDE", 1800),
            "variants": ["original", "gray_clahe"],
            "disableResultCache": True,
        },
    }
    job = repo.create_ocr_job_record(
        document_id=document["id"],
        version_id=version["id"],
        storage_key=str(version.get("storageKey") or ""),
        file_name=str(file.get("fileName") or path.name),
        profile_id="standard_rules_ocr_v1",
        document_type="standard",
    )
    result = client.parse_upload_sync(path, payload, timeout=env_int("AICHECK_REMOTE_OCR_TIMEOUT_SECONDS", 7200))
    repo.finish_ocr_job_record(job, result)
    applied = repo.apply_ocr_result(document["id"], version["id"], result)
    if applied.get("status") != "success":
        return []
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    return units_from_fragments(file, fragments)


def embedding_vectors_for_chunks(chunks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str, str, int, str | None]:
    texts = [str(chunk.get("text") or "") for chunk in chunks]
    client = EmbeddingClient()
    if client.enabled and not env_bool("AICHECK_EMBEDDING_FORCE_OFFLINE_HASH", False):
        vectors: list[dict[str, Any]] = []
        try:
            for offset in range(0, len(texts), EMBED_BATCH_SIZE):
                for item in client.embed_sync(texts[offset : offset + EMBED_BATCH_SIZE], timeout=180):
                    vectors.append({**item, "index": offset + int(item.get("index") or 0)})
            return vectors, client.model_id, client.index_version, client.dimensions, None
        except Exception as exc:
            if not env_bool("AICHECK_EMBEDDING_ALLOW_HASH_FALLBACK", False):
                raise RuntimeError("remote_embedding_unavailable") from exc
    vectors = []
    for offset in range(0, len(texts), EMBED_BATCH_SIZE):
        for item in offline_hash_embeddings(texts[offset : offset + EMBED_BATCH_SIZE]):
            vectors.append({**item, "index": offset + int(item.get("index") or 0)})
    return vectors, OFFLINE_EMBEDDING_MODEL, STANDARD_INDEX_VERSION, int(active_embedding_target()["dimensions"]), "hash_fallback"


def vectorize_imported_file(path: Path, source: dict[str, Any], context_type: str) -> dict[str, Any]:
    relative_path = safe_relative_path(str(path.relative_to(WORKSPACE_ROOT)), path.name)
    file_name = safe_upload_file_name(path.name)
    data = path.read_bytes()
    record_seed = stable_knowledge_record_seed(str(source["id"]), relative_path)
    stable_file_id = f"KF-KB-{record_seed}"
    existing_file = repo.find_one("knowledge_files", stable_file_id)
    removed = remove_knowledge_file_records(existing_file) if existing_file else {}
    document, version, knowledge_file, ocr_task, _storage = create_imported_knowledge_records(
        source=source,
        file_name=file_name,
        content_type=mimetypes.guess_type(file_name)[0] or "application/octet-stream",
        data=data,
        relative_path=relative_path,
        original_file_name=file_name,
        context_description=f"离线导入自 {relative_path}；来源限定为 rules。",
        uploader_name="offline-vectorizer",
        record_seed=record_seed,
        storage_key_override=f"local://{relative_path}",
        storage_bucket_override="local",
        context_type=context_type,
    )
    repo.state["documents"].insert(0, document)
    repo.state["versions"].insert(0, version)
    repo.state["knowledge_files"].insert(0, knowledge_file)
    repo.state["knowledge_tasks"].insert(0, ocr_task)
    repo.upsert_knowledge_task(
        task_type="slice",
        target_id=knowledge_file["id"],
        target_name=knowledge_file["fileName"],
        document_id=document["id"],
        version_id=version["id"],
    )
    repo.upsert_knowledge_task(
        task_type="vector",
        target_id=knowledge_file["id"],
        target_name=knowledge_file["fileName"],
        document_id=document["id"],
        version_id=version["id"],
    )
    units = units_from_local_file(path)
    source_method = "local_text_layer"
    if should_use_remote_ocr(path, units):
        remote_units = remote_ocr_units(path, document, version, knowledge_file, ocr_task)
        if remote_units:
            units = remote_units
            source_method = "remote_ocr"
    if not units:
        mark_ocr_failed(document, version, knowledge_file, ocr_task)
        return {
            "path": relative_path,
            "status": "failed",
            "reason": "empty_text_layer",
            "removed": removed,
            "chunkCount": 0,
            "vectorCount": 0,
        }
    mark_ocr_success(
        document,
        version,
        knowledge_file,
        ocr_task,
        message="远程 OCR 原文抽取完成。" if source_method == "remote_ocr" else "本地 text layer/文本解析完成。",
    )
    slice_result = repo.apply_slice_result(knowledge_file["id"], units)
    chunks = sorted(
        [item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == knowledge_file["id"]],
        key=lambda item: int(item.get("chunkNo") or 0),
    )
    vectors, embedding_model, index_version, expected_dimensions, vector_status_reason = embedding_vectors_for_chunks(chunks)
    embed_result = repo.apply_embed_result(
        knowledge_file["id"],
        len(vectors),
        vectors=vectors,
        embedding_model=embedding_model,
        index_version=index_version,
        expected_dimensions=expected_dimensions,
        vector_status_reason=vector_status_reason,
    )
    return {
        "path": relative_path,
        "contextType": context_type,
        "sourceMethod": source_method,
        "status": "success" if slice_result.get("status") == "success" and embed_result.get("status") == "success" else "failed",
        "removed": removed,
        "chunkCount": int(knowledge_file.get("chunkCount") or 0),
        "vectorCount": int(knowledge_file.get("vectorCount") or 0),
        "vectorStatus": knowledge_file.get("vectorStatus"),
        "embeddingModel": knowledge_file.get("embeddingModel"),
        "indexVersion": knowledge_file.get("indexVersion"),
        "vectorStatusReason": knowledge_file.get("vectorStatusReason"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline vectorize rules/standards plus rules/业务规则.md.")
    parser.add_argument("--reset", action="store_true", help="Remove existing KS-STANDARD-RULES records before importing.")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N files.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not RULES_STANDARDS_ROOT.exists():
        print(json.dumps({"status": "failed", "reason": "missing_rules_standards"}, ensure_ascii=False))
        return 2
    if not RULES_BUSINESS_RULES_PATH.exists():
        print(json.dumps({"status": "failed", "reason": "missing_business_rules_context"}, ensure_ascii=False))
        return 2
    repo.configure_sync_postgres()
    load_state()
    source = knowledge_source_for_import(
        STANDARD_RULES_SOURCE_ID,
        source_name=STANDARD_LIBRARY_SOURCE_NAME,
        source_type="standard",
        source_version=STANDARD_RULES_VERSION,
        source_status="启用",
        vector_status="待向量化",
    )
    if args.reset:
        for file in list(repo.state.get("knowledge_files", [])):
            if file.get("sourceId") == source["id"]:
                remove_knowledge_file_records(file)
    import_files = iter_rules_import_files()
    if args.limit > 0:
        import_files = import_files[: args.limit]
    results = []
    for item in import_files:
        try:
            results.append(
                vectorize_imported_file(item["path"], source, str(item.get("contextType") or "standard_reference"))
            )
        except Exception as exc:
            path = item["path"]
            relative_path = safe_relative_path(str(path.relative_to(WORKSPACE_ROOT)), path.name)
            results.append(
                {
                    "path": relative_path,
                    "contextType": str(item.get("contextType") or "standard_reference"),
                    "status": "failed",
                    "reason": exc.__class__.__name__,
                    "chunkCount": 0,
                    "vectorCount": 0,
                }
            )
            if not env_bool("AICHECK_RULES_REBUILD_CONTINUE_ON_ERROR", True):
                raise
    repo.sync_standard_page_index_for_source(str(source["id"]))
    sync_knowledge_source_counts(source)
    repo.add_audit("离线向量化 rules 标准规范库", "KnowledgeSource", str(source["id"]))
    flush_state()
    failed = [item for item in results if item.get("status") != "success"]
    summary = {
        "status": "success" if not failed else "partial_success",
        "sourceId": source["id"],
        "standardsRoot": str(RULES_STANDARDS_ROOT.relative_to(WORKSPACE_ROOT)),
        "businessRulesPath": str(RULES_BUSINESS_RULES_PATH.relative_to(WORKSPACE_ROOT)),
        "processed": len(results),
        "succeeded": len(results) - len(failed),
        "failed": len(failed),
        "chunkCount": source.get("chunkCount"),
        "vectorStatus": source.get("vectorStatus"),
        "embeddingModel": active_embedding_target()["embeddingModel"] if EmbeddingClient().enabled else OFFLINE_EMBEDDING_MODEL,
        "indexVersion": active_embedding_target()["indexVersion"] if EmbeddingClient().enabled else STANDARD_INDEX_VERSION,
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, separators=(",", ":") if args.json else None, indent=None if args.json else 2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
