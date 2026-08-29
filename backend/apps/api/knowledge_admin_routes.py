"""知识库管理与规则导入路由（自 routes.py 拆出，2026-08-28）。

单体棘轮拆分：本模块为原 routes.py 中 /knowledge/* 与 /business-rules/import
的完整迁移，零行为变化——URL、鉴权、幂等、审计留痕全部原样。
共享辅助从 apps.api.routes 导入（该方向无环：routes 不导入本模块）。
测试会 monkeypatch routes 模块上的 WORKSPACE_ROOT / RULES_* / retrieve_knowledge_clauses，
这些名字必须经 routes_module 属性访问——按值 from-import 会让 patch 失效。
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from apps.api import routes as routes_module
from libs.db.repository import ensure_collections_loaded, requires_collections
from libs.ocr_structured_view import build_ocr_structured_view
from apps.api.routes import (
    ALLOWED_KNOWLEDGE_UPLOAD_TYPES,
    DEFAULT_BUSINESS_PACK_ID,
    EmbeddingClient,
    KNOWLEDGE_TASK_STATUS_ORDER,
    MAX_UPLOAD_BYTES,
    OFFLINE_EMBEDDING_MODEL,
    STANDARD_INDEX_VERSION,
    STANDARD_LIBRARY_SOURCE_NAME,
    STANDARD_RULES_SOURCE_ID,
    STANDARD_RULES_VERSION,
    active_embedding_target,
    admin_user_snapshot,
    attach_document_ocr_readiness,
    answer_draft_from_clauses,
    bounded_form_value,
    build_business_pack_knowledge_network,
    build_knowledge_rule_scorecard,
    bump_record_revision,
    compact_plain_text,
    consume_operation_preview,
    create_imported_knowledge_records,
    create_operation_preview,
    dispatch_knowledge_file_index_pipeline,
    dispatch_knowledge_file_ocr_pipeline,
    display_upload_file_name,
    errors,
    fail,
    filter_keyword,
    first_form_value,
    idempotent,
    iter_rules_import_files,
    knowledge_file_is_business_rule,
    knowledge_file_original_context,
    knowledge_file_original_payload,
    knowledge_file_source_type,
    knowledge_ocr_storage_key,
    knowledge_source_for_import,
    knowledge_task_is_business_rule,
    load_business_pack,
    local_storage_path,
    multipart_upload_fingerprint,
    offline_hash_embedding,
    ok,
    operation_fingerprint,
    page,
    parse_business_rule_upload,
    parse_multipart_uploads,
    record_if_match_valid,
    record_visible_for_request,
    repo,
    request_user_id,
    resolve_knowledge_file_id,
    role_from_query,
    safe_relative_path,
    safe_upload_file_name,
    scope_error_for_record,
    server_time,
    stable_knowledge_record_seed,
    store_knowledge_upload,
    strict_production,
    sync_knowledge_source_counts,
    task_dispatcher,
    upload_file_type_tokens,
    validate_operation_preview,
    versioned_record,
)

knowledge_admin_router = APIRouter()
router = knowledge_admin_router  # 迁移块内的装饰器沿用 @router，别名保持 diff 最小


@requires_collections("knowledge_vectors", "knowledge_page_index_nodes")
def remove_knowledge_file_records(file: dict[str, Any]) -> dict[str, int]:
    file_id = str(file.get("id") or "")
    document_id = str(file.get("documentId") or "")
    version_ids = {
        str(item.get("id"))
        for item in repo.state.get("versions", [])
        if document_id and item.get("documentId") == document_id and item.get("id")
    }
    if file.get("documentVersionId"):
        version_ids.add(str(file["documentVersionId"]))
    chunk_ids = {
        str(item.get("id"))
        for item in repo.state.get("knowledge_chunks", [])
        if item.get("fileId") == file_id
        or (document_id and item.get("documentId") == document_id)
        or str(item.get("documentVersionId") or "") in version_ids
    }

    before = {
        "files": len(repo.state.get("knowledge_files", [])),
        "documents": len(repo.state.get("documents", [])),
        "versions": len(repo.state.get("versions", [])),
        "chunks": len(repo.state.get("knowledge_chunks", [])),
        "vectors": len(repo.state.get("knowledge_vectors", [])),
        "tasks": len(repo.state.get("knowledge_tasks", [])),
        "evidenceLinks": len(repo.state.get("evidence_links", [])),
    }
    repo.state["knowledge_files"] = [
        item for item in repo.state.get("knowledge_files", []) if item.get("id") != file_id
    ]
    repo.state["documents"] = [
        item for item in repo.state.get("documents", []) if item.get("id") != document_id
    ]
    repo.state["versions"] = [
        item
        for item in repo.state.get("versions", [])
        if not (document_id and item.get("documentId") == document_id) and str(item.get("id") or "") not in version_ids
    ]
    repo.state["knowledge_chunks"] = [
        item
        for item in repo.state.get("knowledge_chunks", [])
        if item.get("fileId") != file_id
        and not (document_id and item.get("documentId") == document_id)
        and str(item.get("documentVersionId") or "") not in version_ids
    ]
    repo.state["knowledge_vectors"] = [
        item
        for item in repo.state.get("knowledge_vectors", [])
        if item.get("fileId") != file_id
        and str(item.get("chunkId") or "") not in chunk_ids
        and not (document_id and item.get("documentId") == document_id)
        and str(item.get("documentVersionId") or "") not in version_ids
    ]
    repo.state["knowledge_tasks"] = [
        item
        for item in repo.state.get("knowledge_tasks", [])
        if item.get("targetId") != file_id
        and not (document_id and item.get("documentId") == document_id)
        and str(item.get("documentVersionId") or "") not in version_ids
    ]
    repo.state["evidence_links"] = [
        item
        for item in repo.state.get("evidence_links", [])
        if item.get("fileId") != file_id
        and item.get("knowledgeFileId") != file_id
        and not (document_id and item.get("documentId") == document_id)
        and str(item.get("documentVersionId") or "") not in version_ids
        and str(item.get("chunkId") or item.get("knowledgeChunkId") or "") not in chunk_ids
    ]
    after = {
        "files": len(repo.state.get("knowledge_files", [])),
        "documents": len(repo.state.get("documents", [])),
        "versions": len(repo.state.get("versions", [])),
        "chunks": len(repo.state.get("knowledge_chunks", [])),
        "vectors": len(repo.state.get("knowledge_vectors", [])),
        "tasks": len(repo.state.get("knowledge_tasks", [])),
        "evidenceLinks": len(repo.state.get("evidence_links", [])),
    }
    return {key: before[key] - after[key] for key in before}


@router.get("/knowledge/overview")
def knowledge_overview(request: Request):
    ensure_collections_loaded("knowledge_vectors", "knowledge_page_index_nodes")
    sources = repo.state["knowledge_sources"]
    files = repo.state["knowledge_files"]
    tasks = repo.state["knowledge_tasks"]
    indexable_sources = [source for source in sources if source.get("sourceType") != "rule"]
    indexable_files = [file for file in files if not knowledge_file_is_business_rule(file)]
    indexable_tasks = [task for task in tasks if not knowledge_task_is_business_rule(task)]
    files_by_source: dict[str, list[dict[str, Any]]] = {}
    for file in indexable_files:
        files_by_source.setdefault(str(file.get("sourceId") or ""), []).append(file)
    chunks_by_file: dict[str, int] = {}
    for chunk in repo.state.get("knowledge_chunks", []):
        file_id = str(chunk.get("fileId") or "")
        chunks_by_file[file_id] = chunks_by_file.get(file_id, 0) + 1
    vectors_by_file: dict[str, int] = {}
    for vector in repo.state.get("knowledge_vectors", []):
        file_id = str(vector.get("fileId") or "")
        vectors_by_file[file_id] = vectors_by_file.get(file_id, 0) + 1
    libraries = []
    for source in indexable_sources:
        source_files = files_by_source.get(str(source.get("id") or ""), [])
        chunk_count = sum(chunks_by_file.get(str(file.get("id") or ""), 0) for file in source_files)
        vector_count = sum(vectors_by_file.get(str(file.get("id") or ""), 0) for file in source_files)
        libraries.append(
            {
                "key": source["id"],
                "name": source.get("name") or "--",
                "sourceType": source.get("sourceType"),
                "fileCount": len(source_files),
                "chunkCount": chunk_count,
                "vectorCount": vector_count,
                "indexVersion": source.get("version"),
                "status": source.get("status") or "未知",
                "updatedAt": source.get("updatedAt"),
            }
        )
    # 哈希伪向量的标记落在知识文件的 vectorStatusReason 上（见 worker 的
    # embedding_batches_for_chunks）。这里汇总出来，让降级在界面上可见。
    vectorized_files = [
        item for item in indexable_files if str(item.get("vectorStatus") or "") == "已向量化"
    ]
    degraded_vector_files = [
        item
        for item in vectorized_files
        if "hash" in str(item.get("vectorStatusReason") or "").lower()
    ]
    return ok(
        {
            "metrics": [
                {"key": "source", "label": "知识源", "value": len(indexable_sources), "tone": "blue"},
                {"key": "file", "label": "项目文件", "value": len(indexable_files), "tone": "green"},
                {"key": "task", "label": "运行任务", "value": len([item for item in indexable_tasks if item["status"] in {"排队中", "运行中"}]), "tone": "orange"},
                {"key": "failed", "label": "失败任务", "value": len([item for item in indexable_tasks if item["status"] == "失败"]), "tone": "red"},
                # D-2：哈希伪向量与真语义向量同表同维存储，仅索引版本不同。检索侧配对
                # 逻辑本身没错，但没有任何地方指出「索引里有多少是降级向量」——
                # embedding 服务配置错误时系统照常运行，检索结果近似随机而无人察觉。
                {
                    "key": "degradedVector",
                    "label": "降级向量文件",
                    "value": len(degraded_vector_files),
                    "tone": "red" if degraded_vector_files else "gray",
                },
            ],
            "libraries": libraries,
            "scorecard": build_knowledge_rule_scorecard(repo.state),
            "vectorQuality": {
                "degradedFileCount": len(degraded_vector_files),
                "vectorizedFileCount": len(vectorized_files),
                "degradedRatio": (
                    round(len(degraded_vector_files) / len(vectorized_files), 3) if vectorized_files else 0.0
                ),
                "degradedFiles": [
                    {
                        "fileId": item.get("id"),
                        "fileName": item.get("fileName"),
                        "reason": item.get("vectorStatusReason"),
                        "indexVersion": item.get("indexVersion"),
                    }
                    for item in degraded_vector_files[:20]
                ],
                "note": "降级向量由字符哈希生成、没有语义，检索结果不可信；应修复 embedding 服务后重建索引。",
            },
        },
        request,
    )


@router.get("/knowledge/network")
def knowledge_network(
    request: Request,
    businessPackId: str = Query(default=DEFAULT_BUSINESS_PACK_ID),
    includeRuntime: bool = Query(default=True),
):
    try:
        pack = load_business_pack(businessPackId)
    except (FileNotFoundError, ValueError, KeyError):
        return fail(errors.NOT_FOUND, request, message="未找到指定业务包，无法构建知识网络。")
    graph = build_business_pack_knowledge_network(
        pack,
        runtime_state=repo.state if includeRuntime else None,
    )
    return ok(graph, request)


@router.get("/knowledge/sources")
def list_knowledge_sources(request: Request, keyword: str | None = None, sourceType: str | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [versioned_record("knowledge-source", item) for item in repo.state["knowledge_sources"] if item.get("sourceType") != "rule"]
    if sourceType:
        items = [item for item in items if item["sourceType"] == sourceType]
    if status:
        items = [item for item in items if item["status"] == status]
    items = filter_keyword(items, keyword, ["name", "version", "status"])
    return ok(page(items, page_no, page_size), request)


@router.post("/knowledge/sources")
def create_knowledge_source(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        name = compact_plain_text(body.get("name"), 120)
        source_type = compact_plain_text(body.get("sourceType"), 40)
        if not name or not source_type:
            return fail(errors.VALIDATION_ERROR, request, message="知识源名称和类型不能为空。")
        if source_type not in {"standard", "project-file", "manual"}:
            return fail(errors.VALIDATION_ERROR, request, message="知识源类型不受支持。")
        if source_type == "rule":
            return fail(errors.VALIDATION_ERROR, request, message="业务判断规则请通过监检业务判断规则管理导入，不进入知识库索引。")
        source = {
            "id": f"KS-{uuid4().hex[:8].upper()}",
            "name": name,
            "sourceType": source_type,
            "version": body.get("version"),
            "status": body.get("status") or "启用",
            "fileCount": int(body.get("fileCount") or 0),
            "chunkCount": int(body.get("chunkCount") or 0),
            "vectorStatus": body.get("vectorStatus") or "待向量化",
            "updatedAt": server_time(),
            "actions": ["knowledge:view", "knowledge:manage", "knowledge:reindex"],
            "revision": 1,
        }
        repo.state["knowledge_sources"].insert(0, source)
        audit_id = repo.add_audit("新增知识源", "KnowledgeSource", source["id"])
        return ok({"source": versioned_record("knowledge-source", source), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/knowledge/sources/{source_id}")
def get_knowledge_source(request: Request, source_id: str):
    source = repo.find_one("knowledge_sources", source_id)
    if not source:
        return fail(errors.NOT_FOUND, request)
    if source.get("sourceType") == "rule":
        return fail(errors.NOT_FOUND, request, message="业务规则不作为知识源展示。")
    return ok({"source": versioned_record("knowledge-source", source)}, request)


@router.put("/knowledge/sources/{source_id}")
@router.patch("/knowledge/sources/{source_id}")
def update_knowledge_source(
    request: Request,
    source_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        source = repo.find_one("knowledge_sources", source_id)
        if not source:
            return fail(errors.NOT_FOUND, request)
        effective_if_match = if_match if if_match is not None else request.headers.get("If-Match")
        if not record_if_match_valid("knowledge-source", source, effective_if_match):
            return fail(errors.ETAG_CONFLICT, request)
        changed = []
        for field in ["name", "sourceType", "version", "status", "fileCount", "chunkCount", "vectorStatus"]:
            if field in body and source.get(field) != body[field]:
                if field == "sourceType" and body[field] == "rule":
                    return fail(errors.VALIDATION_ERROR, request, message="业务判断规则请通过监检业务判断规则管理导入，不进入知识库索引。")
                changed.append({"field": field, "before": source.get(field), "after": body[field]})
                source[field] = body[field]
        if changed:
            bump_record_revision(source)
        audit_id = repo.add_audit("更新知识源", "KnowledgeSource", source_id)
        return ok({"source": versioned_record("knowledge-source", source), "auditLogId": audit_id, "changed": changed}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"sourceId": source_id, "body": body})


@router.post("/knowledge/sources/{source_id}/enable")
def enable_knowledge_source(request: Request, source_id: str, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    return update_knowledge_source(request, source_id, {"status": "启用"}, idempotency_key=idempotency_key, if_match=if_match)


@router.post("/knowledge/sources/{source_id}/disable")
def disable_knowledge_source(request: Request, source_id: str, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    return update_knowledge_source(request, source_id, {"status": "停用"}, idempotency_key=idempotency_key, if_match=if_match)


@router.post("/knowledge/standards/import-from-rules")
def import_standards_from_rules_folder(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        if not routes_module.RULES_STANDARDS_ROOT.exists():
            return fail(
                errors.NOT_FOUND,
                request,
                message="未找到 rules/standards 标准规范目录。",
            )
        if not routes_module.RULES_BUSINESS_RULES_PATH.exists():
            return fail(
                errors.NOT_FOUND,
                request,
                message="未找到 rules/业务规则.md 业务规则上下文文件。",
            )
        import_files = iter_rules_import_files()
        standard_files = [item for item in import_files if item.get("contextType") == "standard_reference"]
        if not standard_files:
            return fail(
                errors.VALIDATION_ERROR,
                request,
                message="rules/standards 目录中没有可导入的标准规范文件。",
            )

        source = knowledge_source_for_import(
            str(body.get("sourceId") or STANDARD_RULES_SOURCE_ID),
            source_name=str(body.get("sourceName") or STANDARD_LIBRARY_SOURCE_NAME),
            source_type="standard",
            source_version=str(body.get("sourceVersion") or STANDARD_RULES_VERSION),
            source_status=str(body.get("sourceStatus") or "启用"),
            vector_status="待向量化",
        )
        reset_existing = bool(body.get("reset") or body.get("reinitialize") or body.get("replaceExisting"))
        removed_records = {"files": 0, "documents": 0, "versions": 0, "chunks": 0, "tasks": 0, "evidenceLinks": 0}
        reset_aliases_by_path: dict[str, str] = {}
        scanned_relative_paths = {
            safe_relative_path(str(item["path"].relative_to(routes_module.WORKSPACE_ROOT)), item["path"].name)
            for item in import_files
        }
        if reset_existing:
            existing_files = [
                item for item in list(repo.state.get("knowledge_files", [])) if item.get("sourceId") == source["id"]
            ]
            reset_aliases_by_path = {
                str(item.get("sourceRelativePath") or item.get("originalFileName") or item.get("fileName") or ""): str(
                    item.get("id") or ""
                )
                for item in existing_files
                if item.get("id")
            }
            source["fileIdAliases"] = {}
            for existing_file in existing_files:
                removed = remove_knowledge_file_records(existing_file)
                removed_records = {
                    key: removed_records.get(key, 0) + int(removed.get(key, 0)) for key in removed_records
                }
        else:
            stale_files = [
                item
                for item in list(repo.state.get("knowledge_files", []))
                if item.get("sourceId") == source["id"]
                and str(item.get("sourceRelativePath") or item.get("originalFileName") or item.get("fileName") or "") not in scanned_relative_paths
            ]
            for stale_file in stale_files:
                removed = remove_knowledge_file_records(stale_file)
                removed_records = {
                    key: removed_records.get(key, 0) + int(removed.get(key, 0)) for key in removed_records
                }
        uploader = admin_user_snapshot(request_user_id(request), role_from_query(x_role=request.headers.get("X-Role")))
        uploader_name = uploader.get("name") or "知识库管理员"

        imported_files: list[dict[str, Any]] = []
        imported_tasks: list[dict[str, Any]] = []
        dispatches: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []

        rebuild_index = bool(body.get("rebuildIndex") or body.get("buildIndex") or body.get("dispatchIndex"))
        for import_item in import_files:
            path = import_item["path"]
            context_type = str(import_item.get("contextType") or "standard_reference")
            relative_path = safe_relative_path(str(path.relative_to(routes_module.WORKSPACE_ROOT)), path.name)
            file_name = safe_upload_file_name(path.name)
            file_size = path.stat().st_size
            content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
            if file_size < 1:
                skipped.append({"fileName": file_name, "reason": "文件内容为空"})
                continue
            if file_size > MAX_UPLOAD_BYTES:
                skipped.append({"fileName": file_name, "reason": f"超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上传限制"})
                continue
            if not (upload_file_type_tokens(file_name, content_type) & ALLOWED_KNOWLEDGE_UPLOAD_TYPES):
                skipped.append({"fileName": file_name, "reason": "文件类型不支持"})
                continue

            data = path.read_bytes()
            file_hash = hashlib.sha256(data).hexdigest()
            record_seed = stable_knowledge_record_seed(str(source["id"]), relative_path)
            stable_file_id = f"KF-KB-{record_seed}"
            duplicate_path = repo.find_one("knowledge_files", stable_file_id)
            if duplicate_path:
                existing_version = repo.find_one("versions", duplicate_path.get("documentVersionId")) or {}
                if existing_version.get("hash") == file_hash:
                    skipped.append({"fileName": file_name, "reason": f"已存在相同路径：{duplicate_path.get('fileName')}"})
                    continue
                removed = remove_knowledge_file_records(duplicate_path)
                removed_records = {
                    key: removed_records.get(key, 0) + int(removed.get(key, 0)) for key in removed_records
                }

            document, version, knowledge_file, task, _storage = create_imported_knowledge_records(
                source=source,
                file_name=file_name,
                content_type=content_type,
                data=data,
                relative_path=relative_path,
                original_file_name=file_name,
                context_description=f"来自 {relative_path}；按 rules/业务规则.md 引用标准整理入库。",
                uploader_name=uploader_name,
                record_seed=record_seed,
                storage_key_override=f"local://{relative_path}",
                storage_bucket_override="local",
                context_type=context_type,
            )
            old_file_id = reset_aliases_by_path.get(relative_path)
            if old_file_id and old_file_id != knowledge_file["id"]:
                source.setdefault("fileIdAliases", {})[old_file_id] = knowledge_file["id"]
            repo.state["documents"].insert(0, document)
            repo.state["versions"].insert(0, version)
            repo.state["knowledge_files"].insert(0, knowledge_file)
            repo.state["knowledge_tasks"].insert(0, task)
            dispatch = dispatch_knowledge_file_ocr_pipeline(
                knowledge_file,
                reason=f"管理员导入 rules 标准规范后自动投递 OCR：{task['id']}",
            )
            imported_files.append(versioned_record("knowledge-file", knowledge_file))
            imported_tasks.append(versioned_record("knowledge-task", task))
            dispatches.append({"knowledgeTaskId": task["id"], **dispatch})
            if rebuild_index:
                slice_dispatch = task_dispatcher.dispatch_slice(knowledge_file["id"])
                vector_dispatch = task_dispatcher.dispatch_embed(knowledge_file["id"])
                dispatches.append({"knowledgeTaskId": knowledge_file["id"], "pipelineStage": "slice", **slice_dispatch})
                dispatches.append({"knowledgeTaskId": knowledge_file["id"], "pipelineStage": "vector", **vector_dispatch})

        sync_knowledge_source_counts(source)
        audit_id = repo.add_audit(
            "重新初始化 rules 标准规范库" if reset_existing else "导入 rules 标准规范库",
            "KnowledgeSource",
            source["id"],
        )
        return ok(
            {
                "source": versioned_record("knowledge-source", source),
                "files": imported_files,
                "tasks": imported_tasks,
                "dispatches": dispatches,
                "skipped": skipped,
                "summary": {
                    "sourceId": source["id"],
                    "standardsRoot": str(routes_module.RULES_STANDARDS_ROOT.relative_to(routes_module.WORKSPACE_ROOT)),
                    "businessRulesPath": str(routes_module.RULES_BUSINESS_RULES_PATH.relative_to(routes_module.WORKSPACE_ROOT)),
                    "scanned": len(import_files),
                    "standardFiles": len(standard_files),
                    "businessRuleContextFiles": len(import_files) - len(standard_files),
                    "imported": len(imported_files),
                    "skipped": len(skipped),
                    "reset": reset_existing,
                    "rebuildIndex": rebuild_index,
                    "removed": removed_records["files"],
                },
                "auditLogId": audit_id,
            },
            request,
        )

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"action": "import_standards_from_rules_folder", "body": body},
    )


@router.post("/business-rules/import")
async def import_business_rules(
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fields, uploads, parse_error = await parse_multipart_uploads(request)
    if parse_error:
        return parse_error
    if not uploads:
        return fail(errors.VALIDATION_ERROR, request, message="请选择要导入的业务规则文件。")

    def produce():
        now = server_time()
        import_version = first_form_value(fields, "importVersion", "")
        if not import_version:
            import_version = first_form_value(fields, "version", "")
        if not import_version:
            import_version = f"rule-draft-{now[:16].replace('-', '').replace(':', '').replace(' ', '-')}"
        imported_rules: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        existing_ids = {str(item.get("id")) for item in repo.state.get("rule_versions", [])}
        existing_rule_versions = {
            (str(item.get("ruleKey")), str(item.get("version")))
            for item in repo.state.get("rule_versions", [])
        }

        for upload in uploads:
            source_file_name = safe_upload_file_name(upload["fileName"])
            parsed_rules, error_message = parse_business_rule_upload(
                upload,
                import_version=import_version,
                imported_at=now,
            )
            if error_message:
                skipped.append({"fileName": source_file_name, "reason": error_message})
                continue
            for parsed_rule in parsed_rules:
                parsed_rule["status"] = "草稿"
                parsed_rule["sourceFileName"] = source_file_name
                parsed_rule["importBatchVersion"] = import_version
                parsed_rule["importHash"] = hashlib.sha256(upload["data"]).hexdigest()
                if str(parsed_rule.get("id")) in existing_ids:
                    parsed_rule["id"] = f"{parsed_rule['id']}-IMPORT-{uuid4().hex[:6].upper()}"
                rule_version_key = (str(parsed_rule.get("ruleKey")), str(parsed_rule.get("version")))
                if rule_version_key in existing_rule_versions:
                    parsed_rule["version"] = f"{parsed_rule['version']}-{uuid4().hex[:6].upper()}"
                    rule_version_key = (str(parsed_rule.get("ruleKey")), str(parsed_rule.get("version")))
                existing_ids.add(str(parsed_rule.get("id")))
                existing_rule_versions.add(rule_version_key)
                repo.state["rule_versions"].insert(0, parsed_rule)
                imported_rules.append(versioned_record("rule-version", parsed_rule))

        if not imported_rules and skipped:
            return fail(
                errors.VALIDATION_ERROR,
                request,
                message="业务规则文件未导入。",
                data={"skipped": skipped},
            )
        audit_id = repo.add_audit("导入业务规则文件", "RuleVersion", import_version)
        return ok(
            {
                "rules": imported_rules,
                "importedRules": imported_rules,
                "skipped": skipped,
                "summary": {
                    "importVersion": import_version,
                    "imported": len(imported_rules),
                    "skipped": len(skipped),
                    "status": "草稿",
                },
                "auditLogId": audit_id,
            },
            request,
        )

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"fields": fields, "uploads": multipart_upload_fingerprint(uploads)},
    )


@router.post("/knowledge/files/import")
async def import_knowledge_files(
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fields, uploads, parse_error = await parse_multipart_uploads(request)
    if parse_error:
        return parse_error
    if not uploads:
        return fail(errors.VALIDATION_ERROR, request, message="请选择要导入知识库的文件。")

    def produce():
        source_id = first_form_value(fields, "sourceId", STANDARD_RULES_SOURCE_ID) or STANDARD_RULES_SOURCE_ID
        source_name = first_form_value(fields, "sourceName", STANDARD_LIBRARY_SOURCE_NAME)
        source_type = first_form_value(fields, "sourceType", "standard")
        if source_type == "rule":
            return fail(errors.VALIDATION_ERROR, request, message="业务判断规则请通过监检业务判断规则管理导入，不进入知识库切片或向量索引。")
        source_version = first_form_value(fields, "sourceVersion", "")
        source_status = first_form_value(fields, "sourceStatus", "")
        vector_status = first_form_value(fields, "vectorStatus", "")
        project_id = first_form_value(fields, "projectId", "").strip()
        project_name = first_form_value(fields, "projectName", "").strip()
        project = None
        if project_id:
            project = repo.require_project(project_id)
            if not project:
                return fail(errors.NOT_FOUND, request, message="项目不存在或无权访问。")
            project_name = str(project.get("name") or project_name or project_id)
        source = knowledge_source_for_import(
            source_id,
            source_name=source_name,
            source_type=source_type,
            source_version=source_version,
            source_status=source_status,
            vector_status=vector_status,
        )
        relative_paths = fields.get("relativePaths") or []
        display_names = fields.get("fileNames") or []
        context_descriptions = fields.get("contextDescriptions") or []
        uploader = admin_user_snapshot(request_user_id(request), role_from_query(x_role=request.headers.get("X-Role")))
        uploader_name = uploader.get("name") or "知识库管理员"

        imported_files: list[dict[str, Any]] = []
        imported_tasks: list[dict[str, Any]] = []
        dispatches: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []

        for index, upload in enumerate(uploads):
            original_file_name = safe_upload_file_name(upload["fileName"])
            file_name = display_upload_file_name(
                bounded_form_value(display_names, index, limit=180),
                original_file_name,
            )
            context_description = bounded_form_value(context_descriptions, index, limit=500)
            data = upload["data"]
            content_type = str(upload.get("contentType") or mimetypes.guess_type(original_file_name)[0] or "application/octet-stream")
            relative_path = safe_relative_path(relative_paths[index] if index < len(relative_paths) else None, file_name)
            if not data:
                skipped.append({"fileName": file_name, "reason": "文件内容为空"})
                continue
            if len(data) > MAX_UPLOAD_BYTES:
                skipped.append({"fileName": file_name, "reason": f"超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上传限制"})
                continue
            if not (upload_file_type_tokens(original_file_name, content_type) & ALLOWED_KNOWLEDGE_UPLOAD_TYPES):
                skipped.append({"fileName": file_name, "reason": "文件类型不支持"})
                continue

            file_hash = hashlib.sha256(data).hexdigest()
            duplicate = next(
                (
                    file
                    for file in repo.state.get("knowledge_files", [])
                    if file.get("sourceId") == source["id"]
                    and (repo.find_one("versions", file.get("documentVersionId")) or {}).get("hash") == file_hash
                ),
                None,
            )
            if duplicate:
                skipped.append({"fileName": file_name, "reason": f"已存在相同内容：{duplicate.get('fileName')}"})
                continue

            document, version, knowledge_file, task, _storage = create_imported_knowledge_records(
                source=source,
                file_name=file_name,
                content_type=content_type,
                data=data,
                relative_path=relative_path,
                original_file_name=original_file_name,
                context_description=context_description,
                uploader_name=uploader_name,
                project_id=project_id or None,
                project_name=project_name,
            )
            repo.state["documents"].insert(0, document)
            repo.state["versions"].insert(0, version)
            repo.state["knowledge_files"].insert(0, knowledge_file)
            repo.state["knowledge_tasks"].insert(0, task)
            dispatch = dispatch_knowledge_file_ocr_pipeline(
                knowledge_file,
                reason=f"管理员导入知识库文件后自动投递 OCR：{task['id']}",
            )
            imported_files.append(versioned_record("knowledge-file", knowledge_file))
            imported_tasks.append(versioned_record("knowledge-task", task))
            dispatches.append({"knowledgeTaskId": task["id"], **dispatch})

        if imported_files:
            sync_knowledge_source_counts(source)
        audit_id = repo.add_audit("导入知识库文件", "KnowledgeSource", source["id"])
        return ok(
            {
                "source": versioned_record("knowledge-source", source),
                "files": imported_files,
                "tasks": imported_tasks,
                "dispatches": dispatches,
                "skipped": skipped,
                "auditLogId": audit_id,
            },
            request,
        )

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"fields": fields, "uploads": multipart_upload_fingerprint(uploads)},
    )


@router.get("/knowledge/project-files")
def list_knowledge_files(request: Request, keyword: str | None = None, projectId: str | None = None, nodeId: int | None = None, status: str | None = None, sourceType: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = []
    for item in repo.state["knowledge_files"]:
        if not record_visible_for_request(request, item) or knowledge_file_is_business_rule(item):
            continue
        source = repo.find_one("knowledge_sources", item.get("sourceId")) or {}
        item_source_type = item.get("sourceType") or source.get("sourceType") or "project-file"
        if sourceType:
            if item_source_type != sourceType:
                continue
        elif item_source_type != "project-file":
            continue
        items.append(repo.clone(item))
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if nodeId:
        items = [item for item in items if int(item.get("nodeId") or 0) == int(nodeId)]
    if status:
        items = [item for item in items if status in {item.get("ocrStatus"), item.get("sliceStatus"), item.get("vectorStatus")}]
    items = filter_keyword(items, keyword, ["fileName", "projectName", "nodeName", "sourceRelativePath", "originalFileName"])
    if sourceType == "standard":
        items.sort(
            key=lambda item: str(
                item.get("sourceRelativePath") or item.get("originalFileName") or item.get("fileName") or ""
            ).lower()
        )
    return ok(page(items, page_no, page_size), request)


def standard_canonical_for_file(request: Request, file_id: str) -> dict[str, Any] | None:
    """Return persisted canonical data only for a visible standard knowledge file.

    This intentionally never builds a canonical record on a read path: rebuilding has
    provenance and versioning consequences and belongs to the explicit migration flow.
    Callers which need to surface scope errors should validate the file context first.
    """
    resolved_file_id = resolve_knowledge_file_id(file_id)
    file = repo.find_one("knowledge_files", resolved_file_id)
    if not file or file.get("sourceType") != "standard":
        return None
    if scope_error_for_record(request, file):
        return None
    return repo.find_one("standard_knowledge_records", resolved_file_id, id_field="knowledgeFileId")


def canonical_relation_counts(record: dict[str, Any]) -> dict[str, int]:
    return {
        key: len(record.get(key) or [])
        for key in ("normativeReferences", "replacementRelations", "businessRelations")
    }


def canonical_history_summary(record: dict[str, Any]) -> dict[str, Any]:
    history = record.get("history") or []
    return {
        "sourceCount": len(history),
        "sourceIds": [item.get("sourceId") for item in history if item.get("sourceId")],
    }


def compact_standard_canonical(record: dict[str, Any]) -> dict[str, Any]:
    """Return the bounded representation embedded in the legacy file-detail API."""
    return {
        key: repo.clone(record[key])
        for key in (
            "id",
            "knowledgeFileId",
            "documentId",
            "documentVersionId",
            "canonicalVersion",
            "kbVersion",
            "identity",
            "version",
            "metadata",
            "completeness",
            "sourceFingerprint",
        )
        if key in record
    } | {
        "relationCounts": canonical_relation_counts(record),
        "historySummary": canonical_history_summary(record),
    }


def canonical_detail_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        **repo.clone(record.get("completeness") or {}),
        "relationCounts": canonical_relation_counts(record),
        "history": canonical_history_summary(record),
    }


def scoped_standard_canonical(
    record: dict[str, Any],
    *,
    include_blocks: bool,
    include_history: bool,
    section: str | None,
    page_no: int | None,
) -> dict[str, Any]:
    """Clone and filter response content without changing the persisted canonical record."""
    scoped = repo.clone(record)
    if not include_blocks:
        scoped.pop("blocks", None)
    if not include_history:
        scoped.pop("history", None)

    if section is None and page_no is None:
        return scoped

    content_keys = (
        "sections",
        "clauses",
        "blocks",
        "tables",
        "equations",
        "images",
        "seals",
        "normativeReferences",
        "replacementRelations",
        "businessRelations",
    )
    for key in content_keys:
        items = scoped.get(key)
        if not isinstance(items, list):
            continue
        filtered = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if page_no is not None and item.get("pageNo") != page_no:
                continue
            if section is not None:
                section_values = {
                    str(item.get("section") or ""),
                    str(item.get("sectionId") or ""),
                    str(item.get("id") or ""),
                    str(item.get("title") or ""),
                    str(item.get("clauseNo") or ""),
                }
                if section not in section_values:
                    continue
            filtered.append(item)
        scoped[key] = filtered
    return scoped


@router.get("/knowledge/files/{file_id}/canonical")
def knowledge_file_canonical(
    request: Request,
    file_id: str,
    include_blocks: bool = Query(default=True, alias="includeBlocks"),
    include_history: bool = Query(default=True, alias="includeHistory"),
    section: str | None = None,
    page_no: int | None = Query(default=None, alias="pageNo"),
):
    file, _, _, context_error = knowledge_file_original_context(request, file_id)
    if context_error:
        return context_error
    record = standard_canonical_for_file(request, str(file["id"]))
    if not record:
        return fail(errors.NOT_FOUND, request, message="未找到标准规范规范化记录。")
    return ok(
        scoped_standard_canonical(
            record,
            include_blocks=include_blocks,
            include_history=include_history,
            section=section,
            page_no=page_no,
        ),
        request,
    )


@router.get("/knowledge/files/{file_id}/canonical/sources/{source_id}")
def knowledge_file_canonical_source(request: Request, file_id: str, source_id: str):
    file, _, _, context_error = knowledge_file_original_context(request, file_id)
    if context_error:
        return context_error
    record = standard_canonical_for_file(request, str(file["id"]))
    if not record:
        return fail(errors.NOT_FOUND, request, message="未找到标准规范规范化记录。")
    source = next(
        (item for item in record.get("history") or [] if item.get("sourceId") == source_id),
        None,
    )
    if not source:
        return fail(errors.NOT_FOUND, request, message="未找到规范化记录来源。")
    return ok(repo.clone(source), request)


@router.get("/knowledge/files/{file_id}")
def knowledge_file_detail(request: Request, file_id: str):
    file, document, _, context_error = knowledge_file_original_context(request, file_id)
    if context_error:
        return context_error
    latest_task = next((item for item in repo.state["knowledge_tasks"] if item.get("targetId") == file_id), None)
    original = knowledge_file_original_payload(request, file_id, document)
    canonical = standard_canonical_for_file(request, str(file["id"]))
    canonical_payload = (
        {
            "canonical": compact_standard_canonical(canonical),
            "canonicalSummary": canonical_detail_summary(canonical),
            "activeParseResultId": canonical.get("activeParseResultId"),
            "completeness": repo.clone(canonical.get("completeness") or {}),
        }
        if canonical
        else {}
    )
    versions = repo.versions_for_document(document["id"])
    version_ids = {item["id"] for item in versions}
    return ok(
        {
            "file": repo.clone(file),
            "document": attach_document_ocr_readiness(repo, document),
            "currentVersion": repo.current_version(document["id"]),
            "versions": versions,
            "bindings": [
                repo.clone(item)
                for item in repo.state.get("bindings", [])
                if item.get("documentId") == document["id"]
            ],
            "extractedFields": repo.fields_for_versions(version_ids),
            "evidenceLinks": repo.evidence_for_versions(version_ids),
            "ocrStructured": build_ocr_structured_view(repo, document),
            "latestTask": versioned_record("knowledge-task", latest_task) if latest_task else None,
            "vectorSummary": {
                "vectorStatus": file.get("vectorStatus"),
                "vectorCount": file.get("vectorCount", 0),
                "indexVersion": "proj-v2026.06.26",
                "dimensions": 1024,
                "updatedAt": file.get("updatedAt"),
            },
            **canonical_payload,
            **original,
        },
        request,
    )


@router.put("/knowledge/files/{file_id}")
@router.patch("/knowledge/files/{file_id}")
def update_knowledge_file(
    request: Request,
    file_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        resolved_file_id = resolve_knowledge_file_id(file_id)
        file = repo.find_one("knowledge_files", resolved_file_id)
        if not file:
            return fail(errors.NOT_FOUND, request)
        if knowledge_file_is_business_rule(file):
            return fail(errors.VALIDATION_ERROR, request, message="业务规则不作为知识文件管理。")
        scope_error = scope_error_for_record(request, file)
        if scope_error:
            return scope_error
        effective_if_match = if_match if if_match is not None else request.headers.get("If-Match")
        if not record_if_match_valid("knowledge-file", file, effective_if_match):
            return fail(errors.ETAG_CONFLICT, request)

        document = repo.find_one("documents", file.get("documentId"))
        version = repo.find_one("versions", file.get("documentVersionId"))
        changed = []
        now = server_time()
        if "fileName" in body:
            next_name = display_upload_file_name(
                str(body.get("fileName") or ""),
                str(file.get("originalFileName") or file.get("fileName") or "未命名文件"),
            )
            if file.get("fileName") != next_name:
                changed.append({"field": "fileName", "before": file.get("fileName"), "after": next_name})
                file["fileName"] = next_name
                if document:
                    document["fileName"] = next_name
                    document["updatedAt"] = now
                if version:
                    version["fileName"] = next_name
        if "sourceRelativePath" in body:
            next_path = safe_relative_path(str(body.get("sourceRelativePath") or ""), file.get("fileName") or resolved_file_id)
            if file.get("sourceRelativePath") != next_path:
                changed.append({"field": "sourceRelativePath", "before": file.get("sourceRelativePath"), "after": next_path})
                file["sourceRelativePath"] = next_path
        if "contextDescription" in body:
            next_context = str(body.get("contextDescription") or "").strip()[:500]
            if file.get("contextDescription") != next_context:
                changed.append({"field": "contextDescription", "before": file.get("contextDescription"), "after": next_context})
                file["contextDescription"] = next_context
                if document:
                    document["contextDescription"] = next_context
                    document["updatedAt"] = now
                if version:
                    version["contextDescription"] = next_context
        if "projectId" in body:
            next_project_id = str(body.get("projectId") or "").strip()
            next_project_name = str(body.get("projectName") or "").strip()
            if next_project_id:
                project = repo.require_project(next_project_id)
                if not project:
                    return fail(errors.NOT_FOUND, request, message="项目不存在或无权访问。")
                next_project_name = str(project.get("name") or next_project_name or next_project_id)
            else:
                next_project_name = ""
            if file.get("projectId") != (next_project_id or None):
                changed.append({"field": "projectId", "before": file.get("projectId"), "after": next_project_id or None})
                file["projectId"] = next_project_id or None
                if document:
                    document["projectId"] = next_project_id or None
                    document["updatedAt"] = now
            if file.get("projectName") != next_project_name:
                changed.append({"field": "projectName", "before": file.get("projectName"), "after": next_project_name})
                file["projectName"] = next_project_name
        if changed:
            bump_record_revision(file)
            source = repo.find_one("knowledge_sources", file.get("sourceId"))
            if source:
                sync_knowledge_source_counts(source)
        audit_id = repo.add_audit("更新知识库文件", "KnowledgeFile", resolved_file_id)
        return ok({"file": versioned_record("knowledge-file", file), "auditLogId": audit_id, "changed": changed}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"fileId": file_id, "body": body})


@router.delete("/knowledge/files/{file_id}")
def delete_knowledge_file(
    request: Request,
    file_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        resolved_file_id = resolve_knowledge_file_id(file_id)
        file = repo.find_one("knowledge_files", resolved_file_id)
        if not file:
            return fail(errors.NOT_FOUND, request)
        if knowledge_file_is_business_rule(file):
            return fail(errors.VALIDATION_ERROR, request, message="业务规则不作为知识文件管理。")
        scope_error = scope_error_for_record(request, file)
        if scope_error:
            return scope_error
        effective_if_match = if_match if if_match is not None else request.headers.get("If-Match")
        if not record_if_match_valid("knowledge-file", file, effective_if_match):
            return fail(errors.ETAG_CONFLICT, request)
        source = repo.find_one("knowledge_sources", file.get("sourceId"))
        removed = remove_knowledge_file_records(file)
        if source:
            sync_knowledge_source_counts(source)
        audit_id = repo.add_audit("删除知识库文件", "KnowledgeFile", resolved_file_id)
        return ok(
            {
                "fileId": resolved_file_id,
                "source": versioned_record("knowledge-source", source) if source else None,
                "removed": removed,
                "auditLogId": audit_id,
            },
            request,
        )

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"fileId": file_id, "body": body},
    )


@router.post("/knowledge/files/{file_id}/replace")
async def replace_knowledge_file_version(
    request: Request,
    file_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    ensure_collections_loaded("knowledge_vectors")
    fields, uploads, parse_error = await parse_multipart_uploads(request)
    if parse_error:
        return parse_error
    if len(uploads) != 1:
        return fail(errors.VALIDATION_ERROR, request, message="请选择 1 个文件作为新版本。")

    body_fingerprint = {
        "fileId": file_id,
        "fileName": uploads[0].get("fileName"),
        "size": len(uploads[0].get("data") or b""),
        "hash": hashlib.sha256(uploads[0].get("data") or b"").hexdigest(),
        "fields": fields,
    }

    def produce():
        resolved_file_id = resolve_knowledge_file_id(file_id)
        file = repo.find_one("knowledge_files", resolved_file_id)
        if not file:
            return fail(errors.NOT_FOUND, request)
        if knowledge_file_is_business_rule(file):
            return fail(errors.VALIDATION_ERROR, request, message="业务规则不作为知识文件管理。")
        scope_error = scope_error_for_record(request, file)
        if scope_error:
            return scope_error
        effective_if_match = if_match if if_match is not None else request.headers.get("If-Match")
        if not record_if_match_valid("knowledge-file", file, effective_if_match):
            return fail(errors.ETAG_CONFLICT, request)

        document = repo.find_one("documents", file.get("documentId"))
        if not document:
            return fail(errors.NOT_FOUND, request, message="未找到关联原始文档。")

        upload = uploads[0]
        original_file_name = safe_upload_file_name(upload["fileName"])
        file_name = display_upload_file_name(first_form_value(fields, "fileName", file.get("fileName") or ""), original_file_name)
        data = upload["data"]
        content_type = str(upload.get("contentType") or mimetypes.guess_type(original_file_name)[0] or "application/octet-stream")
        if not data:
            return fail(errors.VALIDATION_ERROR, request, message="新版本文件内容为空。")
        if len(data) > MAX_UPLOAD_BYTES:
            return fail(errors.VALIDATION_ERROR, request, message=f"超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上传限制。")
        if not (upload_file_type_tokens(original_file_name, content_type) & ALLOWED_KNOWLEDGE_UPLOAD_TYPES):
            return fail(errors.VALIDATION_ERROR, request, message="文件类型不支持。")

        source = repo.find_one("knowledge_sources", file.get("sourceId")) or {}
        existing_versions = [
            item for item in repo.state.get("versions", []) if item.get("documentId") == document["id"]
        ]
        version_numbers = []
        for item in existing_versions:
            match = re.search(r"(\d+)$", str(item.get("versionNo") or ""))
            if match:
                version_numbers.append(int(match.group(1)))
        next_no = max(version_numbers or [1]) + 1
        version_no = f"V{next_no}"
        version_id = f"KDV-{uuid4().hex[:10].upper()}-{version_no}"
        context_description = first_form_value(fields, "contextDescription", file.get("contextDescription") or "")[:500]
        relative_path = safe_relative_path(first_form_value(fields, "relativePath", file.get("sourceRelativePath") or ""), file_name)
        uploader = admin_user_snapshot(request_user_id(request), role_from_query(x_role=request.headers.get("X-Role")))
        uploader_name = uploader.get("name") or "知识库管理员"
        storage_key, storage_bucket = store_knowledge_upload(
            source_id=str(file.get("sourceId") or STANDARD_RULES_SOURCE_ID),
            file_id=resolved_file_id,
            file_name=file_name,
            content_type=content_type,
            data=data,
        )
        now = server_time()
        for item in existing_versions:
            item["isCurrent"] = False
        new_version = {
            "id": version_id,
            "documentId": document["id"],
            "versionNo": version_no,
            "hash": hashlib.sha256(data).hexdigest(),
            "fileSize": len(data),
            "fileName": file_name,
            "originalFileName": original_file_name,
            "contextDescription": context_description,
            "storageKey": storage_key,
            "storageBucket": storage_bucket,
            "ocrStatus": "识别中",
            "sliceStatus": "未切片",
            "vectorStatus": "待向量化",
            "uploaderName": uploader_name,
            "uploadTime": now,
            "isCurrent": True,
        }
        repo.state["versions"].insert(0, new_version)
        document.update(
            {
                "fileName": file_name,
                "originalFileName": original_file_name,
                "fileType": Path(file_name).suffix.lower().lstrip(".") or content_type,
                "contextDescription": context_description,
                "currentVersionId": version_id,
                "fileStatus": "已上传",
                "currentOcrStatus": "识别中",
                "updatedAt": now,
            }
        )
        file.update(
            {
                "fileName": file_name,
                "originalFileName": original_file_name,
                "sourceName": source.get("name") or file.get("sourceName"),
                "contextDescription": context_description,
                "documentVersionId": version_id,
                "ocrStatus": "识别中",
                "sliceStatus": "未切片",
                "vectorStatus": "待向量化",
                "chunkCount": 0,
                "vectorCount": 0,
                "sourceRelativePath": relative_path,
                "updatedAt": now,
            }
        )
        bump_record_revision(file)
        repo.state["knowledge_chunks"] = [
            item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") != resolved_file_id
        ]
        repo.state["knowledge_vectors"] = [
            item for item in repo.state.get("knowledge_vectors", []) if item.get("fileId") != resolved_file_id
        ]
        task = {
            "id": f"KT-{uuid4().hex[:8].upper()}",
            "taskType": "ocr",
            "targetType": "file",
            "targetId": resolved_file_id,
            "targetName": file_name,
            "documentId": document["id"],
            "documentVersionId": version_id,
            "status": "排队中",
            "progress": 0,
            "createdAt": now,
            "updatedAt": now,
            "revision": 1,
            "actions": ["knowledge:task-retry"],
        }
        repo.state["knowledge_tasks"].insert(0, task)
        dispatch = task_dispatcher.dispatch_parse_document(document["id"], version_id, storage_key, file_name)
        task["lastDispatch"] = dispatch
        if source:
            sync_knowledge_source_counts(source)
        audit_id = repo.add_audit("替换知识库文件版本", "KnowledgeFile", resolved_file_id)
        return ok(
            {
                "file": versioned_record("knowledge-file", file),
                "currentVersion": repo.clone(new_version),
                "task": versioned_record("knowledge-task", task),
                "dispatch": dispatch,
                "auditLogId": audit_id,
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body_fingerprint)


@router.get("/knowledge/files/{file_id}/chunks")
def knowledge_file_chunks(
    request: Request,
    file_id: str,
    page_no: int = Query(default=1, alias="page"),
    page_size: int = Query(default=20, alias="pageSize"),
    document_page: int | None = Query(default=None, alias="pageNo"),
):
    """`pageNo` 按原文页码筛切片，别和分页的 `page` 搞混。

    证据定位对话框只要「条款所在那一页」的 OCR 文本。没有这个筛选，
    前端就得把整份规范的切片全拉回来再自己挑——一份 TSG 上万条，
    为了看一页正文传几兆，值不当。
    """
    file_id = resolve_knowledge_file_id(file_id)
    file = repo.find_one("knowledge_files", file_id)
    if file:
        if knowledge_file_is_business_rule(file):
            return fail(errors.NOT_FOUND, request, message="业务规则不参与知识库切片。")
        scope_error = scope_error_for_record(request, file)
        if scope_error:
            return scope_error
    chunks = [repo.clone(item) for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == file_id]
    if document_page is not None:
        chunks = [item for item in chunks if int(item.get("pageNo") or 0) == int(document_page)]
    chunks.sort(key=lambda item: (int(item.get("pageNo") or 0), int(item.get("chunkNo") or 0)))
    # 与 OCR 详情页同一条约定：不下发引擎 html。结构化行不够时就地补算。
    from libs.knowledge_indexing import table_view_fields_from_html

    for chunk in chunks:
        html = str(chunk.pop("tableHtml", "") or "").strip()
        if (
            str(chunk.get("blockType") or "").lower() == "table"
            and html
            and not (isinstance(chunk.get("tableColumns"), list) and chunk.get("tableColumns"))
        ):
            chunk.update(table_view_fields_from_html(html))
    return ok(page(chunks, page_no, page_size), request)


@router.get("/knowledge/files/{file_id}/original")
def knowledge_file_original(request: Request, file_id: str, disposition: str = Query(default="inline")):
    _, document, version, context_error = knowledge_file_original_context(request, file_id)
    if context_error:
        return context_error
    file_name = str(document.get("fileName") or version.get("fileName") or f"{file_id}.bin")
    content_type = repo.document_content_type(document) or "application/octet-stream"
    disposition_type = "attachment" if disposition == "attachment" else "inline"
    local_path = local_storage_path(version.get("storageKey"))
    if local_path:
        if not local_path.is_file():
            return fail(errors.NOT_FOUND, request, message="原文文件不存在或已被移除。")
        return FileResponse(
            local_path,
            media_type=content_type,
            filename=file_name,
            content_disposition_type=disposition_type,
        )
    signed = repo.document_download(document)
    signed_url = str(signed.get("url") or "")
    if signed_url.startswith(("http://", "https://")):
        return RedirectResponse(signed_url)
    return fail(errors.NOT_FOUND, request, message="当前原文存储地址不可直接预览或下载。")


def evidence_link_references_knowledge_file(link: dict[str, Any], file: dict[str, Any], chunk_ids: set[str]) -> bool:
    file_id = str(file.get("id") or "")
    document_id = str(file.get("documentId") or "")
    version_id = str(file.get("documentVersionId") or "")
    if file_id and str(link.get("fileId") or link.get("knowledgeFileId") or "") == file_id:
        return True
    if document_id and str(link.get("documentId") or "") == document_id:
        return True
    if version_id and str(link.get("documentVersionId") or "") == version_id:
        return True
    if chunk_ids and str(link.get("chunkId") or link.get("knowledgeChunkId") or "") in chunk_ids:
        return True
    object_type = str(link.get("objectType") or "").lower()
    object_id = str(link.get("objectId") or "")
    if object_type in {"document", "documentasset"} and document_id and object_id == document_id:
        return True
    if object_type in {"documentversion", "version"} and version_id and object_id == version_id:
        return True
    if object_type in {"knowledgefile", "file"} and file_id and object_id == file_id:
        return True
    return bool(object_type in {"knowledgechunk", "chunk"} and chunk_ids and object_id in chunk_ids)


def evidence_link_ids_from_run(run: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("evidenceLinkId", "sourceEvidenceLinkId"):
        if run.get(key):
            ids.add(str(run[key]))
    for key in ("evidenceLinkIds", "sourceEvidenceLinkIds"):
        ids.update(str(item) for item in run.get(key) or [] if item)
    for step in run.get("steps") or []:
        if not isinstance(step, dict):
            continue
        for key in ("evidenceLinkId", "sourceEvidenceLinkId"):
            if step.get(key):
                ids.add(str(step[key]))
        for key in ("evidenceLinkIds", "sourceEvidenceLinkIds"):
            ids.update(str(item) for item in step.get(key) or [] if item)
    return ids


def trace_associated_with_run(trace: dict[str, Any], run: dict[str, Any]) -> bool:
    run_id = str(run.get("id") or run.get("runId") or "")
    if not run_id:
        return False
    trace_run_ids = {
        str(trace.get("runId") or ""),
        str(trace.get("aiRunId") or ""),
        str(trace.get("reviewRunId") or ""),
        str(trace.get("sourceRunId") or ""),
    }
    if run_id in trace_run_ids:
        return True
    run_trace_ids = {str(item) for item in run.get("retrievalTraceIds") or [] if item}
    trace_id = str(trace.get("retrievalTraceId") or trace.get("id") or "")
    return bool(trace_id and trace_id in run_trace_ids)


def nested_reference_matches_knowledge_file(
    value: Any,
    *,
    file: dict[str, Any],
    chunk_ids: set[str],
    matching_evidence_link_ids: set[str],
) -> bool:
    file_id = str(file.get("id") or "")
    document_id = str(file.get("documentId") or "")
    version_id = str(file.get("documentVersionId") or "")
    if isinstance(value, list):
        return any(
            nested_reference_matches_knowledge_file(
                item,
                file=file,
                chunk_ids=chunk_ids,
                matching_evidence_link_ids=matching_evidence_link_ids,
            )
            for item in value
        )
    if not isinstance(value, dict):
        return False

    if file_id and str(value.get("fileId") or value.get("knowledgeFileId") or value.get("targetFileId") or "") == file_id:
        return True
    if document_id and str(value.get("documentId") or "") == document_id:
        return True
    if version_id and str(value.get("documentVersionId") or value.get("versionId") or "") == version_id:
        return True
    if chunk_ids and str(value.get("chunkId") or value.get("knowledgeChunkId") or value.get("kbChunkId") or "") in chunk_ids:
        return True

    object_type = str(value.get("objectType") or value.get("targetType") or "").lower()
    object_id = str(value.get("objectId") or value.get("targetId") or "")
    if object_type in {"document", "documentasset"} and document_id and object_id == document_id:
        return True
    if object_type in {"documentversion", "version"} and version_id and object_id == version_id:
        return True
    if object_type in {"knowledgefile", "file"} and file_id and object_id == file_id:
        return True
    if object_type in {"knowledgechunk", "chunk"} and chunk_ids and object_id in chunk_ids:
        return True

    evidence_id = str(value.get("evidenceLinkId") or value.get("sourceEvidenceLinkId") or "")
    if evidence_id and evidence_id in matching_evidence_link_ids:
        return True
    evidence_ids = {str(item) for item in value.get("evidenceLinkIds") or [] if item}
    if evidence_ids & matching_evidence_link_ids:
        return True

    return any(
        nested_reference_matches_knowledge_file(
            child,
            file=file,
            chunk_ids=chunk_ids,
            matching_evidence_link_ids=matching_evidence_link_ids,
        )
        for child in value.values()
        if isinstance(child, (dict, list))
    )


def reference_text_from_match(match: dict[str, Any]) -> str:
    for key in ("quotedText", "text", "fieldValue", "title", "fileName"):
        if match.get(key):
            return str(match[key])
    return "该推理运行引用了当前文件。"


@router.get("/knowledge/files/{file_id}/vectors")
def knowledge_file_vectors(request: Request, file_id: str):
    ensure_collections_loaded("knowledge_vectors")
    file_id = resolve_knowledge_file_id(file_id)
    file = repo.find_one("knowledge_files", file_id)
    if not file:
        return fail(errors.NOT_FOUND, request)
    if knowledge_file_is_business_rule(file):
        return fail(errors.NOT_FOUND, request, message="业务规则不参与知识库向量化。")
    scope_error = scope_error_for_record(request, file)
    if scope_error:
        return scope_error
    vectors = [
        {
            key: value
            for key, value in repo.clone(item).items()
            if key != "embedding"
        }
        for item in repo.state.get("knowledge_vectors", [])
        if item.get("fileId") == file_id
    ]
    dimensions = next((item.get("dimensions") for item in vectors if item.get("dimensions")), 1024)
    return ok(
        {
            "vectorStatus": file.get("vectorStatus"),
            "vectorCount": file.get("vectorCount", len(vectors)),
            "storedVectorCount": len(vectors),
            "indexVersion": "proj-v2026.06.26",
            "dimensions": dimensions,
            "embeddingModel": file.get("embeddingModel") or OFFLINE_EMBEDDING_MODEL,
            "updatedAt": file.get("updatedAt"),
            "vectors": vectors,
        },
        request,
    )


@router.get("/knowledge/files/{file_id}/reasoning-references")
def knowledge_file_reasoning_refs(request: Request, file_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    file_id = resolve_knowledge_file_id(file_id)
    file = repo.find_one("knowledge_files", file_id)
    if not file:
        return fail(errors.NOT_FOUND, request)
    if knowledge_file_is_business_rule(file):
        return fail(errors.NOT_FOUND, request, message="业务规则不作为知识文件引用。")
    scope_error = scope_error_for_record(request, file)
    if scope_error:
        return scope_error

    chunks = [item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == file_id]
    chunk_ids = {str(item.get("id") or item.get("chunkId")) for item in chunks if item.get("id") or item.get("chunkId")}
    matching_evidence_links = [
        link
        for link in repo.state.get("evidence_links", [])
        if evidence_link_references_knowledge_file(link, file, chunk_ids)
    ]
    matching_evidence_link_ids = {str(item.get("id")) for item in matching_evidence_links if item.get("id")}
    refs = []
    seen_run_ids: set[str] = set()
    for run in repo.state["ai_runs"]:
        if not record_visible_for_request(request, run):
            continue
        run_matches = [
            link
            for link in run.get("evidenceLinks") or []
            if isinstance(link, dict) and evidence_link_references_knowledge_file(link, file, chunk_ids)
        ]
        run_evidence_ids = evidence_link_ids_from_run(run)
        run_matches.extend(link for link in matching_evidence_links if str(link.get("id") or "") in run_evidence_ids)
        trace_matches = [
            trace
            for trace in repo.state.get("retrieval_traces", [])
            if trace_associated_with_run(trace, run)
            and nested_reference_matches_knowledge_file(
                trace,
                file=file,
                chunk_ids=chunk_ids,
                matching_evidence_link_ids=matching_evidence_link_ids,
            )
        ]
        if not run_matches and not trace_matches:
            continue
        run_id = str(run.get("id") or run.get("runId") or "")
        if run_id in seen_run_ids:
            continue
        seen_run_ids.add(run_id)
        quoted_texts = [reference_text_from_match(item) for item in [*run_matches, *trace_matches]]
        refs.append(
            {
                "runId": run_id,
                "nodeId": run.get("nodeId"),
                "subject": run.get("subject"),
                "model": run.get("model"),
                "quotedText": "；".join(dict.fromkeys(quoted_texts)),
                "createdAt": run.get("finishedAt") or run.get("startedAt") or run.get("createdAt"),
            }
        )
    return ok(page(refs, page_no, page_size), request)


@router.post("/knowledge/files/{file_id}/reindex")
def reindex_file(request: Request, file_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        resolved_file_id = resolve_knowledge_file_id(file_id)
        file = repo.find_one("knowledge_files", resolved_file_id)
        if not file:
            return fail(errors.NOT_FOUND, request)
        if knowledge_file_is_business_rule(file):
            return fail(errors.VALIDATION_ERROR, request, message="业务判断规则不参与知识库重建索引，请在监检业务判断规则管理中发布或回滚。")
        scope_error = scope_error_for_record(request, file)
        if scope_error:
            return scope_error
        task = {"id": f"KT-{uuid4().hex[:8].upper()}", "taskType": "reindex", "targetType": "file", "targetId": resolved_file_id, "targetName": file["fileName"], "status": "排队中", "progress": 0, "createdAt": server_time(), "updatedAt": server_time(), "revision": 1, "actions": ["knowledge:task-retry"]}
        repo.state["knowledge_tasks"].insert(0, task)
        try:
            include_ocr = bool(body.get("includeOcr") or body.get("ocr"))
            if include_ocr:
                dispatches = [
                    dispatch_knowledge_file_ocr_pipeline(
                        file,
                        reason=f"管理员触发重建索引，重新投递 OCR：{task['id']}",
                    )
                ]
            else:
                dispatches = dispatch_knowledge_file_index_pipeline(
                    file,
                    reason=f"管理员触发重建索引，重新投递切片和向量化：{task['id']}",
                )
            task["status"] = "成功"
            task["progress"] = 100
            task["finishedAt"] = server_time()
            task["lastDispatch"] = {"dispatches": dispatches}
            repo.append_task_log(task, "info", f"重建索引已创建 {len(dispatches)} 个子任务。")
        except ValueError:
            repo.mark_task_failed(task, "重建索引失败：找不到关联文档版本。")
            return fail(errors.NOT_FOUND, request, message="找不到关联文档版本。")
        return ok({"task": versioned_record("knowledge-task", task), "dispatches": dispatches}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/knowledge/tasks")
def list_knowledge_tasks(request: Request, taskType: str | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [
        versioned_record("knowledge-task", item)
        for item in repo.state["knowledge_tasks"]
        if record_visible_for_request(request, item) and not knowledge_task_is_business_rule(item)
    ]
    if taskType:
        items = [item for item in items if item["taskType"] == taskType]
    if status:
        items = [item for item in items if item["status"] == status]
    items.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    items.sort(key=lambda item: KNOWLEDGE_TASK_STATUS_ORDER.get(str(item.get("status")), 99))
    return ok(page(items, page_no, page_size), request)


@router.get("/knowledge/tasks/{task_id}")
def knowledge_task_detail(request: Request, task_id: str):
    task = repo.find_one("knowledge_tasks", task_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, task)
    if scope_error:
        return scope_error
    return ok({"task": versioned_record("knowledge-task", task)}, request)


@router.get("/knowledge/tasks/{task_id}/logs")
def knowledge_task_logs(request: Request, task_id: str):
    task = repo.find_one("knowledge_tasks", task_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, task)
    if scope_error:
        return scope_error
    logs = task.get("logs") or [{"createdAt": task.get("createdAt") or server_time(), "level": "info", "message": f"任务 {task_id} 已进入队列。"}]
    return ok(logs, request)


def retry_dispatch_for_knowledge_task(request: Request, task: dict[str, Any]) -> tuple[list[dict[str, Any]], JSONResponse | None]:
    task_type = task.get("taskType")
    dispatches: list[dict[str, Any]] = []
    task["attempts"] = int(task.get("attempts") or 0) + 1
    task["status"] = "排队中"
    task["progress"] = 0
    task["updatedAt"] = server_time()
    task.pop("errorMessage", None)
    task.pop("finishedAt", None)
    repo.append_task_log(task, "info", f"第 {task['attempts']} 次重试已投递。")

    if task_type == "ocr":
        file = repo.find_one("knowledge_files", task.get("targetId"))
        document_id = task.get("documentId") or (file or {}).get("documentId")
        version_id = task.get("documentVersionId") or (file or {}).get("documentVersionId")
        version = repo.find_one("versions", version_id) if version_id else None
        document = repo.find_one("documents", document_id) if document_id else None
        if not document or not version:
            repo.mark_task_failed(task, "OCR 重试失败：找不到关联文档版本。")
            return [], fail(errors.NOT_FOUND, request, message="找不到关联文档版本。")
        task["documentId"] = document["id"]
        task["documentVersionId"] = version["id"]
        if file:
            dispatches.append(
                dispatch_knowledge_file_ocr_pipeline(
                    file,
                    reason=f"管理员重试 OCR 任务：{task['id']}",
                )
            )
        else:
            dispatches.append(
                task_dispatcher.dispatch_parse_document(
                    document["id"],
                    version["id"],
                    knowledge_ocr_storage_key(version),
                    document.get("fileName") or task.get("targetName"),
                )
            )
    elif task_type == "slice":
        file = repo.find_one("knowledge_files", task.get("targetId"))
        if not file:
            repo.mark_task_failed(task, "切片重试失败：找不到关联知识文件。")
            return [], fail(errors.NOT_FOUND, request, message="找不到关联知识文件。")
        if knowledge_file_is_business_rule(file):
            repo.mark_task_failed(task, "业务规则不参与知识库切片。")
            return [], fail(errors.VALIDATION_ERROR, request, message="业务规则不参与知识库切片。")
        dispatches.append(task_dispatcher.dispatch_slice(task["targetId"]))
    elif task_type in {"vector", "embed"}:
        file = repo.find_one("knowledge_files", task.get("targetId"))
        if not file:
            repo.mark_task_failed(task, "向量化重试失败：找不到关联知识文件。")
            return [], fail(errors.NOT_FOUND, request, message="找不到关联知识文件。")
        if knowledge_file_is_business_rule(file):
            repo.mark_task_failed(task, "业务规则不参与知识库向量化。")
            return [], fail(errors.VALIDATION_ERROR, request, message="业务规则不参与知识库向量化。")
        dispatches.append(task_dispatcher.dispatch_embed(task["targetId"]))
    elif task_type == "reindex":
        target_type = task.get("targetType")
        if target_type == "file":
            targets = [repo.find_one("knowledge_files", task.get("targetId"))]
        else:
            targets = [item for item in repo.state["knowledge_files"] if item.get("sourceId") == task.get("targetId")]
        targets = [item for item in targets if item and not knowledge_file_is_business_rule(item)]
        if not targets:
            repo.mark_task_failed(task, "重建索引失败：找不到可重建的知识文件。")
            return [], fail(errors.NOT_FOUND, request, message="找不到可重建的知识文件。")
        try:
            for file in targets:
                dispatches.extend(
                    dispatch_knowledge_file_index_pipeline(
                        file,
                        reason=f"管理员重试重建索引任务：{task['id']}",
                    )
                )
        except ValueError:
            repo.mark_task_failed(task, "重建索引失败：找不到关联文档版本。")
            return [], fail(errors.NOT_FOUND, request, message="找不到关联文档版本。")
        task["status"] = "成功"
        task["progress"] = 100
        task["finishedAt"] = server_time()
        repo.append_task_log(task, "info", f"重建索引已创建 {len(dispatches)} 个子任务。")
    else:
        repo.mark_task_failed(task, f"不支持的任务类型：{task_type}")
        return [], fail(errors.VALIDATION_ERROR, request, message=f"不支持的任务类型：{task_type}")

    task["lastDispatch"] = dispatches[0] if len(dispatches) == 1 else {"dispatches": dispatches}
    return dispatches, None


@router.post("/knowledge/tasks/{task_id}/retry")
def retry_knowledge_task(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        task = repo.find_one("knowledge_tasks", task_id)
        if not task:
            return fail(errors.NOT_FOUND, request)
        scope_error = scope_error_for_record(request, task)
        if scope_error:
            return scope_error
        if not record_if_match_valid("knowledge-task", task, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        dispatches, error = retry_dispatch_for_knowledge_task(request, task)
        if error:
            return error
        bump_record_revision(task)
        return ok({"task": versioned_record("knowledge-task", task), "dispatches": dispatches}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"taskId": task_id, "body": body})


@router.post("/knowledge/tasks/{task_id}/cancel")
def cancel_knowledge_task(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        task = repo.find_one("knowledge_tasks", task_id)
        if not task:
            return fail(errors.NOT_FOUND, request)
        scope_error = scope_error_for_record(request, task)
        if scope_error:
            return scope_error
        if not record_if_match_valid("knowledge-task", task, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        cancel_reason = compact_plain_text(body.get("reason"), 1000) or "用户请求取消任务。"
        dispatch = task.get("lastDispatch") if isinstance(task.get("lastDispatch"), dict) else {}
        celery_task_ids = [
            str(item.get("taskId"))
            for item in (dispatch.get("dispatches") or [dispatch])
            if isinstance(item, dict) and item.get("taskId")
        ]
        task["status"] = "cancel_requested"
        task["cancelRequestedAt"] = server_time()
        task["cancelReason"] = cancel_reason
        revoke_results = []
        for celery_task_id in celery_task_ids:
            try:
                from apps.worker.celery_app import celery_app

                celery_app.control.revoke(celery_task_id, terminate=False)
                revoke_results.append({"taskId": celery_task_id, "status": "requested"})
            except Exception as exc:
                revoke_results.append({"taskId": celery_task_id, "status": "failed", "reason": exc.__class__.__name__})
        task["cancelDispatches"] = revoke_results
        if not celery_task_ids or all(item["status"] == "requested" for item in revoke_results):
            task["status"] = "已取消"
            task["cancelledAt"] = server_time()
        else:
            task["status"] = "cancel_failed"
        bump_record_revision(task)
        if task["status"] == "已取消":
            repo.append_task_log(task, "info", f"任务已取消。原因：{cancel_reason}")
        else:
            repo.append_task_log(task, "warning", f"任务取消状态：{task['status']}。原因：{cancel_reason}")
        return ok({"task": versioned_record("knowledge-task", task), "revokeResults": revoke_results}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"taskId": task_id, "body": body})


def normalized_knowledge_reindex_payload(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": str(body.get("scope") or "all"),
        "includeOcr": bool(body.get("includeOcr") or body.get("ocr")),
        "sourceId": str(body.get("sourceId") or "").strip() or None,
        "sourceType": str(body.get("sourceType") or "").strip() or None,
        "projectId": str(body.get("projectId") or "").strip() or None,
        "onlyIncomplete": bool(body.get("onlyIncomplete")),
        "limit": max(0, int(body.get("limit") or 0)),
        "reason": str(body.get("reason") or "").strip(),
    }


def knowledge_reindex_targets(payload: dict[str, Any]) -> list[dict[str, Any]]:
    scope = payload["scope"]
    source_id = payload.get("sourceId")
    source_type = payload.get("sourceType")
    project_id = payload.get("projectId")
    targets = [item for item in repo.state["knowledge_files"] if not knowledge_file_is_business_rule(item)]
    if scope == "source" and source_id:
        targets = [item for item in targets if item.get("sourceId") == source_id]
    elif scope == "source":
        source_ids = {
            item["id"]
            for item in repo.state["knowledge_sources"]
            if item.get("sourceType") != "rule" and (not source_type or item.get("sourceType") == source_type)
        }
        targets = [item for item in targets if item.get("sourceId") in source_ids]
    if source_type:
        targets = [item for item in targets if knowledge_file_source_type(item) == source_type]
    if scope == "project" and project_id:
        targets = [item for item in targets if item.get("projectId") == project_id]
    if payload.get("onlyIncomplete"):
        targets = [
            item
            for item in targets
            if item.get("ocrStatus") != "已识别"
            or item.get("sliceStatus") != "已切片"
            or item.get("vectorStatus") != "已向量化"
        ]
    limit = int(payload.get("limit") or 0)
    return targets[:limit] if limit > 0 else targets


def knowledge_reindex_base_fingerprint(targets: list[dict[str, Any]]) -> str:
    return operation_fingerprint(
        [
            {
                "id": item.get("id"),
                "updatedAt": item.get("updatedAt"),
                "ocrStatus": item.get("ocrStatus"),
                "sliceStatus": item.get("sliceStatus"),
                "vectorStatus": item.get("vectorStatus"),
            }
            for item in targets
        ]
    )


@router.post("/knowledge/reindex-preview")
def preview_batch_reindex(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    payload = normalized_knowledge_reindex_payload(body)
    if not payload["reason"]:
        return fail(errors.VALIDATION_ERROR, request, message="知识索引重建必须填写操作原因。")
    targets = knowledge_reindex_targets(payload)
    impact = {
        "scope": payload["scope"],
        "matchedFiles": len(targets),
        "estimatedTasks": len(targets) * (3 if payload["includeOcr"] else 2),
        "includeOcr": payload["includeOcr"],
        "onlyIncomplete": payload["onlyIncomplete"],
        "sampleFiles": [str(item.get("fileName") or item.get("id")) for item in targets[:5]],
        "warnings": ["将重建 OCR、切片和向量" if payload["includeOcr"] else "将重建切片和向量"] if targets else ["当前范围没有匹配文件"],
    }
    preview = create_operation_preview(
        request,
        kind="knowledge_reindex",
        payload=payload,
        base_fingerprint=knowledge_reindex_base_fingerprint(targets),
        impact=impact,
    )
    return ok({**preview, "impact": impact}, request)


@router.post("/knowledge/reindex")
def batch_reindex(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    payload = normalized_knowledge_reindex_payload(body)
    if (body.get("previewId") or strict_production()) and not payload["reason"]:
        return fail(errors.VALIDATION_ERROR, request, message="知识索引重建必须填写操作原因。")
    preview, preview_error = validate_operation_preview(
        request,
        preview_id=str(body.get("previewId") or "") or None,
        kind="knowledge_reindex",
        payload=payload,
        base_fingerprint=knowledge_reindex_base_fingerprint(knowledge_reindex_targets(payload)),
    )
    if preview_error:
        return preview_error

    def produce():
        scope = payload["scope"]
        include_ocr = payload["includeOcr"]
        source_id = str(payload.get("sourceId") or "")
        source_type = str(payload.get("sourceType") or "")
        project_id = str(payload.get("projectId") or "")
        targets = knowledge_reindex_targets(payload)

        ids: list[str] = []
        dispatches: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []
        for target in targets:
            task = {"id": f"KT-{uuid4().hex[:8].upper()}", "taskType": "reindex", "targetType": "file", "targetId": target["id"], "targetName": target.get("fileName") or target.get("name"), "status": "排队中", "progress": 0, "createdAt": server_time(), "updatedAt": server_time(), "revision": 1, "actions": ["knowledge:task-retry"]}
            repo.state["knowledge_tasks"].insert(0, task)
            ids.append(task["id"])
            try:
                if include_ocr:
                    child_dispatches = [
                        dispatch_knowledge_file_ocr_pipeline(
                            target,
                            reason=f"管理员批量重建知识库，重新投递 OCR：{task['id']}；原因：{payload['reason'] or '兼容调用未填写'}",
                        )
                    ]
                else:
                    child_dispatches = dispatch_knowledge_file_index_pipeline(
                        target,
                        reason=f"管理员批量重建知识库，重新投递切片和向量化：{task['id']}；原因：{payload['reason'] or '兼容调用未填写'}",
                    )
                task["status"] = "成功"
                task["progress"] = 100
                task["finishedAt"] = server_time()
                task["lastDispatch"] = {"dispatches": child_dispatches}
                repo.append_task_log(task, "info", f"重建索引已创建 {len(child_dispatches)} 个子任务。")
                dispatches.extend({"parentTaskId": task["id"], **item} for item in child_dispatches)
            except ValueError:
                repo.mark_task_failed(task, "重建索引失败：找不到关联文档版本。")
                failed.append({"taskId": task["id"], "targetId": str(target.get("id") or ""), "reason": "找不到关联文档版本"})

        source = repo.find_one("knowledge_sources", source_id) if source_id else None
        if source:
            sync_knowledge_source_counts(source)
        consume_operation_preview(preview)
        return ok(
            {
                "taskIds": ids,
                "dispatches": dispatches,
                "summary": {
                    "scope": scope,
                    "sourceId": source_id or None,
                    "sourceType": source_type or None,
                    "projectId": project_id or None,
                    "includeOcr": include_ocr,
                    "matched": len(targets),
                    "dispatched": len(dispatches),
                    "failed": len(failed),
                },
                "failed": failed,
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/knowledge/retrieval-test")
def retrieval_test(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    question = compact_plain_text(body.get("question"), 1000)
    if not question:
        return fail(errors.VALIDATION_ERROR, request, message="检索问题不能为空。")
    dense_hits: list[dict[str, Any]] = []
    embedding_model = OFFLINE_EMBEDDING_MODEL
    index_version = body.get("indexVersion") or STANDARD_INDEX_VERSION
    vector_status_reason = None
    if os.getenv("AICHECK_RETRIEVAL_DENSE_DISABLE", "false").lower() != "true":
        query_embedding = None
        embedding_client = EmbeddingClient()
        if embedding_client.enabled and os.getenv("AICHECK_EMBEDDING_FORCE_OFFLINE_HASH", "false").lower() != "true":
            try:
                vectors = embedding_client.embed_sync([str(question)], timeout=30)
                query_embedding = (vectors[0] if vectors else {}).get("embedding")
                embedding_model = embedding_client.model_id
                index_version = body.get("indexVersion") or embedding_client.index_version
            except Exception:
                vector_status_reason = "remote_embedding_unavailable_hash_fallback"
        if not isinstance(query_embedding, list) or not query_embedding:
            query_embedding = offline_hash_embedding(str(question))
            embedding_model = OFFLINE_EMBEDDING_MODEL
            index_version = body.get("indexVersion") or STANDARD_INDEX_VERSION
        search_args = {
            "top_k": int(body.get("topK") or 5),
            "source_id": body.get("sourceId"),
            "index_version": index_version,
        }
        if repo.postgres_enabled and repo.sync_postgres is not None:
            dense_hits = repo.search_knowledge_vectors(query_embedding, **search_args)
        if not dense_hits:
            dense_hits = repo.search_local_knowledge_vectors(query_embedding, **search_args)
    retrieval = routes_module.retrieve_knowledge_clauses(
        repo.state,
        query=str(question),
        business_pack_id=body.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
        node_id=int(body.get("nodeId")) if str(body.get("nodeId") or "").isdigit() else None,
        kb_version=body.get("kbVersion"),
        top_k=int(body.get("topK") or 5),
        query_type="interactive_retrieval_test",
        dense_chunk_ids=[str(item.get("chunkId")) for item in dense_hits if item.get("chunkId")],
    )
    return ok(
        {
            "answerDraft": answer_draft_from_clauses(str(question), retrieval["clauses"]),
            "hits": retrieval["trace"]["selectedClauses"],
            "retrievalTrace": retrieval["trace"],
            "latencyMs": 12,
            "denseHits": dense_hits,
            "embeddingModel": embedding_model,
            "indexVersion": index_version,
            "activeEmbeddingModel": active_embedding_target()["embeddingModel"],
            "activeIndexVersion": active_embedding_target()["indexVersion"],
            "vectorStatusReason": vector_status_reason or "ok",
            "usedIndexVersions": sorted({item.get("kbVersion") for item in retrieval["clauses"] if item.get("kbVersion")}),
        },
        request,
    )


@router.get("/knowledge/clauses")
def list_knowledge_clauses(
    request: Request,
    keyword: str | None = None,
    nodeId: int | None = None,
    businessPackId: str | None = None,
    page_no: int = Query(default=1, alias="page"),
    page_size: int = Query(default=20, alias="pageSize"),
):
    retrieval = routes_module.retrieve_knowledge_clauses(
        repo.state,
        query=keyword or "审查依据",
        business_pack_id=businessPackId or DEFAULT_BUSINESS_PACK_ID,
        node_id=nodeId,
        top_k=max(page_no * page_size, page_size),
        query_type="clause_list",
    )
    items = retrieval["trace"]["selectedClauses"]
    return ok(page(items, page_no, page_size), request)


@router.get("/knowledge/page-index-nodes")
def list_knowledge_page_index_nodes(
    request: Request,
    keyword: str | None = None,
    kbDocId: str | None = None,
    parentNodeId: str | None = None,
    page_no: int = Query(default=1, alias="page"),
    page_size: int = Query(default=20, alias="pageSize"),
):
    ensure_collections_loaded("knowledge_page_index_nodes")
    items = [repo.clone(item) for item in repo.state.get("knowledge_page_index_nodes", [])]
    if kbDocId:
        items = [item for item in items if item.get("kbDocId") == kbDocId]
    if parentNodeId is not None:
        items = [item for item in items if str(item.get("parentNodeId")) == str(parentNodeId)]
    items = filter_keyword(items, keyword, ["title", "summary", "nodeId", "pageIndexNodeId"])
    if keyword:
        query = str(keyword).lower()
        items.sort(
            key=lambda item: (
                query in str(item.get("title") or "").lower(),
                query in str(item.get("summary") or "").lower(),
                not bool(item.get("children")),
            ),
            reverse=True,
        )
    return ok(page(items, page_no, page_size), request)
