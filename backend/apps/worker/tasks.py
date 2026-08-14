from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from apps.ocr_service.service import ocr_service
from apps.worker.celery_app import celery_app
from libs.aliyun_ocr import AliyunOcrError, AliyunOcrRetryableError
from libs.audit_runtime import audit_runtime_for_run, audit_runtime_public_config
from libs.business_pack import build_ai_review_prompt, load_business_pack, matching_rule_for_node
from libs.contracts.responses import server_time
from libs.db.repository import (
    STATE_COLLECTIONS,
    flush_state,
    flush_state_records,
    load_ocr_task_state,
    load_state,
    repo,
    sync_state_records,
)
from libs.deepseek_runtime import DeepSeekAuditClient, deepseek_runtime_public_config
from libs.document_ai_shadow import (
    EVIDENCE_PRIOR_VERSION,
    build_evidence_prior,
    compare_shadow_to_baseline,
    document_ai_shadow_enabled,
    stable_payload_hash,
    validate_shadow_attribution,
)
from libs.document_audit_pipeline_comparison import (
    QwenVisionAuditClient,
    build_deepseek_messages,
    build_qwen_vision_messages,
    build_shared_industry_context,
    collect_source_candidate_ids,
    compare_pipeline_results,
    normalize_pipeline_result,
    parse_json_model_output,
    persist_pipeline_comparison_run,
    schedule_pipeline_comparison,
)
from libs.integrations import task_dispatcher
from libs.integrations.document_ai_client import DocumentAiClient
from libs.integrations.embedding_client import EmbeddingClient
from libs.integrations.errors import IntegrationServiceError, safe_reason
from libs.integrations.litellm_client import LiteLLMClient
from libs.integrations.mineru_client import MinerUClient, MinerUError
from libs.integrations.ocr_client import OcrClient
from libs.integrations.storage import object_storage, parse_storage_url
from libs.knowledge_indexing import (
    EMBED_BATCH_SIZE,
    OFFLINE_EMBEDDING_MODEL,
    STANDARD_INDEX_VERSION,
    active_embedding_target,
    local_path_from_storage_key,
    noise_like_text,
    offline_hash_embeddings,
    units_from_local_file,
)
from libs.material_targeting import run_material_targeting
from libs.mineru_ocr import (
    MinerUNormalizationError,
    MinerUNormalizedBundle,
    normalize_mineru_zip,
)
from libs.model_usage import model_cost_cny, normalize_model_usage
from libs.ocr.profiles import profile_for
from libs.ocr_accuracy_pipeline import (
    SEAL_ENGINES,
    STRUCTURE_ENGINES,
    build_batch_prior,
    build_batch_priors,
    default_profile,
    fuse_stage_parse_results,
    infer_preliminary_profile_id,
    merge_batch_outputs,
    merge_grounded_fields,
    normalize_qwen_structured_output,
    page_batches,
    page_numbers,
    parse_qwen_json,
    pipeline_enabled,
    pipeline_mode,
    pipeline_run_key,
    pipeline_version,
    profile_from_ocr_result,
    qwen_messages,
    render_candidate_rois,
    render_pages,
    required_field_blockers,
    stage_engine_summary,
    temporary_pipeline_directory,
    validate_batch_output,
    validated_ocr_fields,
)
from libs.ocr_runtime import (
    ocr_runtime_config,
    official_ocr_enabled,
    official_ocr_primary_enabled,
)
from libs.official_ocr_pipeline import official_ocr_extract, profile_result_complete
from libs.pipeline_lock import pipeline_task_lock
from libs.qwen_runtime import (
    QwenRuntimeClient,
    build_qwen_runtime_client,
    qwen_runtime_public_config,
)
from libs.raw_vault import raw_context_from_record
from libs.review_grounding import (
    apply_grounding_guardrails,
    build_grounded_review_input,
    grounding_prompt_block,
    unsupported_claims,
)
from libs.security.tenant import (
    current_tenant_id,
    reset_request_tenant_id,
    set_request_tenant_id,
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]


def ocr_result_state_records(document_id: str, version_id: str) -> dict[str, list[dict[str, Any]]]:
    knowledge_file_ids = {
        str(item.get("id"))
        for item in repo.state.get("knowledge_files", [])
        if str(item.get("documentId") or "") == document_id
        or str(item.get("documentVersionId") or "") == version_id
    }
    return {
        "documents": [item for item in repo.state.get("documents", []) if str(item.get("id") or "") == document_id],
        "versions": [item for item in repo.state.get("versions", []) if str(item.get("id") or "") == version_id],
        "knowledge_files": [
            item for item in repo.state.get("knowledge_files", []) if str(item.get("id") or "") in knowledge_file_ids
        ],
        "knowledge_tasks": [
            item
            for item in repo.state.get("knowledge_tasks", [])
            if str(item.get("documentId") or "") == document_id
            or str(item.get("documentVersionId") or "") == version_id
            or str(item.get("targetId") or "") in knowledge_file_ids
        ],
        "ocr_jobs": [
            item
            for item in repo.state.get("ocr_jobs", [])
            if str(item.get("documentId") or "") == document_id
            and str(item.get("documentVersionId") or "") == version_id
        ],
        "ocr_parse_results": [
            item for item in repo.state.get("ocr_parse_results", []) if str(item.get("documentVersionId") or "") == version_id
        ],
        "ocr_pipeline_runs": [
            item for item in repo.state.get("ocr_pipeline_runs", []) if str(item.get("documentVersionId") or "") == version_id
        ],
        "ocr_stage_runs": [
            item
            for item in repo.state.get("ocr_stage_runs", [])
            if any(
                run.get("id") == item.get("pipelineRunId")
                for run in repo.state.get("ocr_pipeline_runs", [])
                if str(run.get("documentVersionId") or "") == version_id
            )
        ],
        "extracted_fields": [
            item for item in repo.state.get("extracted_fields", []) if str(item.get("documentVersionId") or "") == version_id
        ],
        "evidence_links": [
            item
            for item in repo.state.get("evidence_links", [])
            if str(item.get("documentId") or "") == document_id
            or str(item.get("documentVersionId") or "") == version_id
        ],
        "node_evidence_links": [
            item
            for item in repo.state.get("node_evidence_links", [])
            if str(item.get("documentId") or "") == document_id
            or str(item.get("documentVersionId") or "") == version_id
        ],
        "bindings": [
            item
            for item in repo.state.get("bindings", [])
            if str(item.get("documentId") or "") == document_id
            or str(item.get("documentVersionId") or "") == version_id
        ],
        "material_targeting_runs": [
            item
            for item in repo.state.get("material_targeting_runs", [])
            if str(item.get("documentId") or "") == document_id
            and str(item.get("documentVersionId") or "") == version_id
        ],
    }


def state_record_ids(records: dict[str, list[dict[str, Any]]]) -> dict[str, set[str]]:
    output: dict[str, set[str]] = {}
    for state_key, items in records.items():
        collection_name = STATE_COLLECTIONS.get(state_key)
        if not collection_name:
            continue
        output[state_key] = {
            repo.persistence_object_id(collection_name, item, index)
            for index, item in enumerate(items)
        }
    return output


def stable_hash_payload(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def persist_document_ai_shadow_run(run: dict[str, Any]) -> None:
    sync_state_records({"document_ai_shadow_runs": [run]}, {})


def document_ai_shadow_run_id(parse_result_id: str, profile_id: str) -> str:
    seed = hashlib.sha256(f"{parse_result_id}|{profile_id}|{EVIDENCE_PRIOR_VERSION}".encode("utf-8")).hexdigest()
    return f"DOCSH-{seed[:18].upper()}"


def schedule_document_ai_shadow(
    *,
    document_id: str,
    version_id: str,
    storage_key: str,
    file_name: str | None,
    profile_id: str | None,
    parse_result: dict[str, Any],
    operation_id: str | None,
) -> dict[str, Any] | None:
    if not document_ai_shadow_enabled(profile_id):
        return None
    parse_result_id = str(parse_result.get("parseResultId") or parse_result.get("id") or "")
    if not parse_result_id:
        return {"status": "not_dispatched", "statusReason": "missing_parse_result_id"}
    run_id = document_ai_shadow_run_id(parse_result_id, str(profile_id))
    existing = repo.find_one("document_ai_shadow_runs", run_id)
    if existing and str(existing.get("status") or "") in {"queued", "running", "success"}:
        return {
            "runId": run_id,
            "status": existing.get("status"),
            "taskId": existing.get("taskId"),
            "alreadyScheduled": True,
        }
    version = repo.find_one("versions", version_id) or {}
    structured = profile_for(str(profile_id)).get("structuredExtraction") or {}
    now = server_time()
    run = existing or {
        "id": run_id,
        "runId": run_id,
        "schemaVersion": "DocumentAiShadowRun@1",
        "advisoryOnly": True,
        "businessImpact": "none",
        "documentId": document_id,
        "documentVersionId": version_id,
        "parseResultId": parse_result_id,
        "profileId": profile_id,
        "templateVersion": structured.get("templateVersion"),
        "evidencePriorVersion": EVIDENCE_PRIOR_VERSION,
        "storageKey": storage_key,
        "storageBucket": version.get("storageBucket"),
        "fileName": file_name,
        "baselineHash": stable_payload_hash(parse_result),
        "operationId": operation_id,
        "createdAt": now,
    }
    run.update(
        {
            "status": "queued",
            "failureReason": None,
            "updatedAt": now,
            "queuedAt": now,
        }
    )
    if run not in repo.state.setdefault("document_ai_shadow_runs", []):
        repo.state["document_ai_shadow_runs"].insert(0, run)
    persist_document_ai_shadow_run(run)
    try:
        dispatch = task_dispatcher.dispatch_document_ai_shadow(run_id)
    except Exception as exc:  # pragma: no cover - Celery broker boundary
        dispatch = {
            "mode": task_dispatcher.dispatch_mode(),
            "taskId": None,
            "statusReason": f"dispatch_{exc.__class__.__name__.lower()}",
        }
    run["dispatch"] = dispatch
    run["taskId"] = dispatch.get("taskId")
    if not dispatch.get("taskId"):
        run["status"] = "dispatch_failed"
        run["failureReason"] = str(dispatch.get("statusReason") or "shadow_dispatch_failed")
    run["updatedAt"] = server_time()
    persist_document_ai_shadow_run(run)
    return {
        "runId": run_id,
        "status": run.get("status"),
        "taskId": run.get("taskId"),
        "statusReason": (run.get("dispatch") or {}).get("statusReason"),
    }


def qwen_runtime_client() -> QwenRuntimeClient:
    return build_qwen_runtime_client(LiteLLMClient)


def compare_document_version_ids(run: dict[str, Any]) -> set[str]:
    version_ids = {str(item) for item in run.get("documentVersionIds") or [] if item}
    evidence_ids = {str(item) for item in run.get("evidenceLinkIds") or [] if item}
    if evidence_ids:
        version_ids.update(
            str(item.get("documentVersionId"))
            for item in repo.state.get("evidence_links", [])
            if str(item.get("id") or "") in evidence_ids and item.get("documentVersionId")
        )
    if version_ids:
        return version_ids
    project_id = run.get("projectId")
    node_id = run.get("nodeId")
    for ai_run in repo.state.get("ai_runs", []):
        if project_id and ai_run.get("projectId") != project_id:
            continue
        if node_id is not None and int(ai_run.get("nodeId") or -1) != int(node_id):
            continue
        version_ids.update(str(item) for item in ai_run.get("inputDocumentVersionIds") or [] if item)
    return version_ids


def production_prompt_template_for_run(run: dict[str, Any]) -> dict[str, Any] | None:
    business_pack_id = run.get("businessPackId")
    prompt_version = str(run.get("promptVersion") or "")
    templates = [
        item
        for item in repo.state.get("prompt_templates", [])
        if item.get("businessPackId") in {None, "", business_pack_id}
        and item.get("status") in {"production", "published", "active", "启用", "已发布"}
    ]
    exact = next(
        (
            item
            for item in templates
            if prompt_version
            and (
                item.get("id") == prompt_version
                or item.get("promptVersionId") == prompt_version
                or item.get("version") == prompt_version
            )
        ),
        None,
    )
    return repo.clone(exact or (templates[0] if templates else None))


def service_failure_message(service: str) -> str:
    return f"{service} 调用失败，请检查服务健康、模型配置、凭据和网络连通性。"


def worker_ocr_http_enabled() -> bool:
    if os.getenv("AICHECK_OCR_BASE_URL"):
        return True
    return os.getenv("AICHECK_WORKER_OCR_ENABLE_LOCAL_FALLBACK", "false").lower() in {"1", "true", "yes", "on"}


def worker_ocr_in_process_allowed() -> bool:
    return os.getenv("AICHECK_WORKER_OCR_ALLOW_IN_PROCESS", "false").lower() in {"1", "true", "yes", "on"}


def worker_state_persistence_enabled() -> bool:
    return (
        repo.sync_postgres is not None
        or repo.postgres_dsn
        or os.getenv("AICHECK_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or repo.sqlite_enabled
    )


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def refresh_worker_state(selected_state_keys: set[str] | None = None) -> None:
    if worker_state_persistence_enabled():
        load_state(selected_state_keys)


def refresh_ocr_worker_state(document_id: str, version_id: str) -> None:
    if worker_state_persistence_enabled():
        load_ocr_task_state(document_id, version_id)


def split_text_fragments(
    text: str,
    *,
    page_no: int = 1,
    max_chars: int = 1600,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []
    chunks = []
    for offset in range(0, len(normalized), max_chars):
        chunk_text = normalized[offset : offset + max_chars].strip()
        if chunk_text:
            chunks.append({"pageNo": page_no, "text": chunk_text, **(metadata or {})})
    return chunks


def latest_successful_ocr_parse_result(version_id: str | None) -> dict[str, Any] | None:
    if not version_id:
        return None
    results = [
        item
        for item in repo.state.get("ocr_parse_results", [])
        if item.get("documentVersionId") == version_id and item.get("status") == "success"
    ]
    results.sort(key=lambda item: str(item.get("finishedAt") or item.get("createdAt") or ""), reverse=True)
    return results[0] if results else None


def knowledge_slice_fragments_from_ocr(file: dict[str, Any]) -> list[dict[str, Any]]:
    result = latest_successful_ocr_parse_result(file.get("documentVersionId"))
    raw_fragments = [item for item in (result or {}).get("fragments") or [] if isinstance(item, dict)]
    if not raw_fragments:
        return []
    engine_runs = [item for item in (result or {}).get("engineRuns") or [] if isinstance(item, dict)]
    engine_name = next(
        (
            str(item.get("engine") or item.get("name") or "")
            for item in engine_runs
            if item.get("engine") or item.get("name")
        ),
        "",
    )
    diagnostic_codes = {
        str(item.get("code") or "")
        for item in (result or {}).get("diagnostics") or []
        if isinstance(item, dict)
    }
    source_method = "pymupdf_text_layer" if "PDF_TEXT_LAYER_FAST_PATH" in diagnostic_codes else "remote_ocr"
    if len(raw_fragments) == 1:
        fragment = raw_fragments[0]
        metadata = {
            "bbox": fragment.get("bbox"),
            "sourceMethod": fragment.get("sourceMethod") or source_method,
            "ocrEngine": fragment.get("ocrEngine") or fragment.get("sourceEngine") or engine_name or "ocr_service",
            "ocrConfidence": fragment.get("ocrConfidence") or fragment.get("confidence"),
        }
        return split_text_fragments(str(fragment.get("text") or ""), page_no=int(fragment.get("pageNo") or 1), metadata=metadata)
    pages: dict[int, list[dict[str, Any]]] = {}
    for fragment in raw_fragments:
        text = str(fragment.get("text") or "").strip()
        if not text or noise_like_text(text):
            continue
        page_no = int(fragment.get("pageNo") or 1)
        pages.setdefault(page_no, []).append(fragment)
    fragments: list[dict[str, Any]] = []
    for page_no in sorted(pages):
        page_fragments = pages[page_no]
        for fragment_index, fragment in enumerate(page_fragments, start=1):
            text = str(fragment.get("text") or "").strip()
            if not text or noise_like_text(text):
                continue
            confidence = fragment.get("ocrConfidence") or fragment.get("confidence")
            try:
                confidence_value = float(confidence) if str(confidence or "").strip() else None
            except (TypeError, ValueError):
                confidence_value = None
            metadata = {
                "bbox": fragment.get("bbox"),
                "roi": {
                    "schemaVersion": "FdeRoi@1.0.0",
                    "pageNo": page_no,
                    "sourceMethod": fragment.get("sourceMethod") or source_method,
                    "boxes": [
                        {
                            "id": str(fragment.get("id") or fragment.get("fragmentId") or f"p{page_no}-f{fragment_index}"),
                            "pageNo": page_no,
                            "bbox": fragment.get("bbox"),
                            "polygon": fragment.get("polygon") or fragment.get("bbox"),
                            "text": text,
                            "confidence": confidence,
                            "sourceFragmentId": fragment.get("id") or fragment.get("fragmentId"),
                            "sourceMethod": fragment.get("sourceMethod") or source_method,
                        }
                    ],
                    "qualityWarnings": [],
                },
                "sourceMethod": fragment.get("sourceMethod") or source_method,
                "ocrEngine": fragment.get("ocrEngine") or fragment.get("sourceEngine") or engine_name or "ocr_service",
                "ocrConfidence": confidence_value,
                "sourceFragmentId": fragment.get("id") or fragment.get("fragmentId") or f"p{page_no}-f{fragment_index}",
            }
            fragments.extend(split_text_fragments(text, page_no=page_no, metadata=metadata))
    return fragments


def embedding_batches_for_chunks(chunks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str, str, int, str | None]:
    texts = [str(chunk.get("text") or "") for chunk in chunks]
    force_offline = env_bool("AICHECK_EMBEDDING_FORCE_OFFLINE_HASH", False)
    client = EmbeddingClient()
    if client.enabled and not force_offline:
        vectors: list[dict[str, Any]] = []
        try:
            for offset in range(0, len(texts), EMBED_BATCH_SIZE):
                for item in client.embed_sync(texts[offset : offset + EMBED_BATCH_SIZE]):
                    if not isinstance(item, dict):
                        continue
                    vectors.append({**item, "index": offset + int(item.get("index") or 0)})
            return vectors, client.model_id, client.index_version, client.dimensions, None
        except Exception as exc:
            if not env_bool("AICHECK_EMBEDDING_ALLOW_HASH_FALLBACK", False):
                raise RuntimeError("remote_embedding_unavailable") from exc
            target = active_embedding_target()
            fallback_reason = "remote_embedding_unavailable_hash_fallback"
            vectors = []
            for offset in range(0, len(texts), EMBED_BATCH_SIZE):
                for item in offline_hash_embeddings(texts[offset : offset + EMBED_BATCH_SIZE]):
                    vectors.append({**item, "index": offset + int(item.get("index") or 0)})
            return vectors, OFFLINE_EMBEDDING_MODEL, STANDARD_INDEX_VERSION, int(target["dimensions"]), fallback_reason
    # D-2：EmbeddingClient 未启用时，这里原先直接落哈希伪向量且 fallback_reason 为
    # None——与真语义向量同表同维存储，无任何标记。embedding 服务配置错了系统照常
    # 运行，检索结果近似随机，使用方无从察觉。
    # 现在把它当配置错误：要用哈希向量必须显式声明（离线自测/评测场景），
    # 否则拒绝入库，让问题在写入时就暴露。
    if not force_offline and not env_bool("AICHECK_EMBEDDING_ALLOW_HASH_FALLBACK", False):
        raise RuntimeError(
            "embedding_client_not_configured: 未配置可用的 embedding 服务。"
            "哈希伪向量没有语义、会让检索结果近似随机，不能静默入库。"
            "如确实要在离线环境自测，请显式设 AICHECK_EMBEDDING_FORCE_OFFLINE_HASH=true "
            "或 AICHECK_EMBEDDING_ALLOW_HASH_FALLBACK=true。"
        )
    vectors = []
    for offset in range(0, len(texts), EMBED_BATCH_SIZE):
        for item in offline_hash_embeddings(texts[offset : offset + EMBED_BATCH_SIZE]):
            vectors.append({**item, "index": offset + int(item.get("index") or 0)})
    # 即便是显式声明的离线模式，也要留下降级标记——否则索引里的哈希向量依旧不可辨认。
    fallback_reason = (
        "forced_offline_hash_embedding" if force_offline else "embedding_client_disabled_hash_fallback"
    )
    return (
        vectors,
        OFFLINE_EMBEDDING_MODEL,
        STANDARD_INDEX_VERSION,
        int(active_embedding_target()["dimensions"]),
        fallback_reason,
    )


ACCURACY_BASELINE_TEXT_ENGINES = [
    "pymupdf_text_layer",
    "paddle_ocr_subprocess",
    "tesseract_cli",
]


def accuracy_pipeline_baseline_options(options: dict[str, Any] | None = None) -> dict[str, Any]:
    baseline = deepcopy(options or {})
    baseline.update(
        {
            "engineAllowlist": list(ACCURACY_BASELINE_TEXT_ENGINES),
            "enableTables": False,
            "enableSeals": False,
            "forceHeavyEngines": False,
        }
    )
    return baseline


def parse_with_ocr_service(
    storage_key: str,
    file_name: str | None = None,
    *,
    document_id: str | None = None,
    version_id: str | None = None,
    profile_id: str | None = None,
    document_type: str | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if worker_ocr_http_enabled():
        client = OcrClient()
    else:
        client = None
    if client is not None and client.enabled:
        local_source_path = local_path_from_storage_key(storage_key, WORKSPACE_ROOT)
        upload_local_file = env_bool("AICHECK_OCR_UPLOAD_LOCAL_FILES", True)
        if local_source_path and upload_local_file and hasattr(client, "parse_upload_sync"):
            return client.parse_upload_sync(
                local_source_path,
                {
                    "documentId": document_id,
                    "documentVersionId": version_id,
                    "documentType": document_type,
                    "profileId": profile_id,
                    "storageKey": storage_key,
                    "fileName": file_name,
                    "options": {"enableTables": True, "enableSeals": True, "enableFallback": True, **(options or {})},
                },
            )
        parsed_storage = parse_storage_url(storage_key)
        upload_object = env_bool("AICHECK_OCR_UPLOAD_OBJECTS", False)
        if parsed_storage and upload_object and hasattr(client, "parse_upload_sync"):
            bucket, object_name = parsed_storage
            downloaded = object_storage.download_to_temp(
                bucket,
                object_name,
                suffix=Path(file_name or object_name).suffix,
            )
            if downloaded is None:
                raise RuntimeError("OCR source object could not be downloaded for parse-upload")
            try:
                return client.parse_upload_sync(
                    downloaded,
                    {
                        "documentId": document_id,
                        "documentVersionId": version_id,
                        "documentType": document_type,
                        "profileId": profile_id,
                        "storageKey": storage_key,
                        "fileName": file_name,
                        "options": {"enableTables": True, "enableSeals": True, "enableFallback": True, **(options or {})},
                    },
                )
            finally:
                shutil.rmtree(downloaded.parent, ignore_errors=True)
        use_job_api = os.getenv("AICHECK_OCR_USE_JOB_API", "true").lower() != "false"
        if use_job_api and hasattr(client, "parse_via_job_sync"):
            return client.parse_via_job_sync(
                {
                    "documentId": document_id,
                    "documentVersionId": version_id,
                    "documentType": document_type,
                    "profileId": profile_id,
                    "storageKey": storage_key,
                    "fileName": file_name,
                    "options": {"enableTables": True, "enableSeals": True, "enableFallback": True, **(options or {})},
                }
            )
        return client.parse_sync(
            storage_key,
            file_name=file_name,
            profile_id=profile_id,
            document_type=document_type,
            document_version_id=version_id,
            options={"enableTables": True, "enableSeals": True, "enableFallback": True, **(options or {})},
        )
    if not worker_ocr_in_process_allowed():
        raise RuntimeError(
            "OCR service is not configured. Set AICHECK_OCR_BASE_URL for remote OCR "
            "or explicitly set AICHECK_WORKER_OCR_ALLOW_IN_PROCESS=true in development."
        )
    return ocr_service.parse_document(
        storage_key,
        file_name=file_name,
        profile_id=profile_id,
        document_type=document_type,
        document_version_id=version_id,
        options=options,
    )


def store_ocr_pipeline_artifact(run: dict[str, Any], stage: str, payload: Any) -> tuple[str | None, str]:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    artifact_hash = "sha256:" + hashlib.sha256(body).hexdigest()
    object_name = f"pipelines/{run['id']}/{stage}/{artifact_hash.split(':', 1)[1]}.json"
    url = object_storage.put_bytes("ocr-artifacts", object_name, body, content_type="application/json")
    run.setdefault("artifactUrls", {})[stage] = url
    return url, artifact_hash


def pipeline_engine_status(result: dict[str, Any]) -> dict[str, Any]:
    runs = [item for item in result.get("engineRuns") or [] if isinstance(item, dict)]
    return {
        str(item.get("engine") or item.get("engineId") or f"engine-{index}"): {
            "status": item.get("status"),
            "durationMs": item.get("durationMs"),
            "errorCode": item.get("errorCode"),
        }
        for index, item in enumerate(runs, start=1)
    }


def persist_ocr_pipeline_progress(
    run: dict[str, Any],
    *,
    task: dict[str, Any] | None = None,
    ocr_job: dict[str, Any] | None = None,
) -> None:
    records: dict[str, list[dict[str, Any]]] = {
        "ocr_pipeline_runs": [run],
        "ocr_stage_runs": repo.ocr_pipeline_stages(str(run.get("id") or "")),
    }
    if task:
        records["knowledge_tasks"] = [task]
    if ocr_job:
        records["ocr_jobs"] = [ocr_job]
    flush_state_records(records)


def pipeline_apply_result(
    document_id: str,
    version_id: str,
    result: dict[str, Any],
    previous_record_ids: dict[str, set[str]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    applied = repo.apply_ocr_result(document_id, version_id, result)
    targeting = None
    if applied.get("status") == "success":
        document = repo.find_one("documents", document_id)
        if document and document.get("projectId"):
            targeting = run_material_targeting(
                repo,
                str(document["projectId"]),
                document_id,
                version_id,
                triggered_by="ocr_accuracy_pipeline",
            )
    current_records = ocr_result_state_records(document_id, version_id)
    current_record_ids = state_record_ids(current_records)
    deleted_record_ids = {
        state_key: sorted(object_ids - current_record_ids.get(state_key, set()))
        for state_key, object_ids in previous_record_ids.items()
        if object_ids - current_record_ids.get(state_key, set())
    }
    sync_state_records(current_records, deleted_record_ids)
    return applied, targeting


def mark_local_pipeline_stages(
    run: dict[str, Any],
    result: dict[str, Any],
    profile: dict[str, Any],
    *,
    artifact_url: str | None,
    artifact_hash: str,
) -> None:
    engine_status = pipeline_engine_status(result)
    has_text = bool(result.get("fragments") or result.get("fields"))
    repo.mark_ocr_pipeline_stage(
        run,
        "text_scan",
        "success" if has_text else "partial",
        engine_status=engine_status,
        blocking_reasons=[] if has_text else [{"code": "OCR_TEXT_EMPTY"}],
        artifact_url=artifact_url,
        artifact_hash=artifact_hash,
    )
    required_tables = profile.get("requiredTables") or []
    repo.mark_ocr_pipeline_stage(
        run,
        "structure_scan",
        "queued" if required_tables else "skipped",
        engine_status={} if required_tables else {"skipReasons": ["profile_has_no_required_tables"]},
    )
    seal_required = bool((profile.get("sealRules") or {}).get("required"))
    repo.mark_ocr_pipeline_stage(
        run,
        "seal_signature_scan",
        "queued" if seal_required else "skipped",
        engine_status={} if seal_required else {"skipReasons": ["profile_does_not_require_seal"]},
    )
    repo.mark_ocr_pipeline_stage(
        run,
        "evidence_fusion",
        "queued",
        engine_status={},
    )


def _persist_mineru_job(job: dict[str, Any]) -> None:
    flush_state_records({"ocr_jobs": [job]})


def _finalize_mineru_pipeline(
    job: dict[str, Any],
    result: dict[str, Any],
    result_record: dict[str, Any] | None,
) -> None:
    run_id = str(job.get("pipelineRunId") or "")
    if not run_id:
        return
    run = repo.find_one("ocr_pipeline_runs", run_id)
    if not run:
        return
    profile = profile_for(
        str(result.get("profileId") or job.get("profileId") or "") or None,
        str(
            result.get("documentType")
            or job.get("documentType")
            or ""
        )
        or None,
    )
    quality = (
        result.get("quality")
        if isinstance(result.get("quality"), dict)
        else {}
    )
    outcome_status = str(result.get("outcomeStatus") or "partial")
    raw_blocking_reasons = quality.get("blockingReasons")
    blocking_reasons = [
        deepcopy(reason)
        if isinstance(reason, dict)
        else {"code": str(reason)}
        for reason in (
            raw_blocking_reasons or []
        )
    ]
    failed = str(result.get("status") or "") != "success"
    if failed:
        repo.mark_ocr_pipeline_stage(
            run,
            "text_scan",
            "failed",
            engine_status=pipeline_engine_status(result),
            blocking_reasons=blocking_reasons,
            failure_reason="mineru_ocr_failed",
        )
        repo.finish_ocr_pipeline_run(
            run,
            status="failed",
            blocking_reasons=blocking_reasons,
            recommended_action="检查 MinerU 远程任务后重试。",
        )
        return

    repo.mark_ocr_pipeline_stage(run, "prepare", "success")
    has_text = bool(result.get("fragments") or result.get("fields"))
    normalized_reference = (
        job.get("artifactReferences", {}).get("normalized_json", {})
        if isinstance(job.get("artifactReferences"), dict)
        else {}
    )
    repo.mark_ocr_pipeline_stage(
        run,
        "text_scan",
        "success" if has_text else "partial",
        engine_status=pipeline_engine_status(result),
        blocking_reasons=[] if has_text else [{"code": "OCR_TEXT_EMPTY"}],
        artifact_url=normalized_reference.get("storageUrl"),
        artifact_hash=normalized_reference.get("sha256"),
    )
    required_tables = bool(profile.get("requiredTables"))
    repo.mark_ocr_pipeline_stage(
        run,
        "structure_scan",
        (
            "success"
            if required_tables and result.get("tables")
            else "partial"
            if required_tables
            else "skipped"
        ),
        engine_status={"mineru_vlm": {"status": "success"}},
        blocking_reasons=(
            []
            if not required_tables or result.get("tables")
            else [{"code": "REQUIRED_TABLE_MISSING"}]
        ),
    )
    seal_required = bool((profile.get("sealRules") or {}).get("required"))
    formal_seal = any(
        bool(item.get("canSatisfyRequiredSeal"))
        for item in result.get("seals") or []
        if isinstance(item, dict)
    )
    repo.mark_ocr_pipeline_stage(
        run,
        "seal_signature_scan",
        (
            "success"
            if seal_required and formal_seal
            else "partial"
            if seal_required
            else "skipped"
        ),
        engine_status={"mineru_vlm": {"status": "success"}},
        blocking_reasons=(
            []
            if not seal_required or formal_seal
            else [{"code": "SEAL_TEXT_LOW_CONFIDENCE"}]
        ),
    )
    for separate_review_stage in ("qwen_extract", "grounding_validate", "finalize"):
        repo.mark_ocr_pipeline_stage(
            run,
            separate_review_stage,
            "skipped",
            engine_status={"skipReasons": ["review_pipeline_separate"]},
        )
    repo.mark_ocr_pipeline_stage(
        run,
        "evidence_fusion",
        "success" if outcome_status == "completed" else "partial",
        blocking_reasons=blocking_reasons,
    )
    run.update(
        {
            "providerMode": "explicit_remote",
            "provider": "mineru",
            "model": "vlm",
            "cloudGrounded": True,
            "parseResultId": (
                (result_record or {}).get("parseResultId")
                or result.get("parseResultId")
            ),
            "artifactUrls": {
                **(run.get("artifactUrls") or {}),
                "mineru": deepcopy(job.get("artifactReferences") or {}),
            },
        }
    )
    repo.finish_ocr_pipeline_run(
        run,
        status=(
            "completed" if outcome_status == "completed" else "partial"
        ),
        blocking_reasons=blocking_reasons,
        recommended_action=(
            None
            if outcome_status == "completed"
            else "复核 MinerU 未满足的必填证据。"
        ),
        formal_evidence_ready=outcome_status == "completed",
    )


def mineru_source_path(
    job: dict[str, Any],
) -> tuple[Path | None, Path | None]:
    storage_key = str(job.get("storageKey") or "")
    parsed = parse_storage_url(storage_key)
    suffix = Path(str(job.get("fileName") or "")).suffix
    if parsed:
        downloaded = object_storage.download_to_temp(
            parsed[0],
            parsed[1],
            suffix=suffix,
        )
        return downloaded, downloaded.parent if downloaded else None
    local_path = local_path_from_storage_key(storage_key, WORKSPACE_ROOT)
    if local_path and local_path.is_file():
        return local_path, None
    direct_path = Path(storage_key)
    if direct_path.is_file():
        return direct_path, None
    return None, None


def _mineru_progress_value(status: dict[str, Any]) -> int:
    state = str(status.get("state") or "")
    if state == "pending":
        return 20
    if state == "converting":
        return 65
    if state == "done":
        return 70
    progress = status.get("extract_progress")
    if state == "running" and isinstance(progress, dict):
        completed = int(progress.get("extracted_pages") or 0)
        total = int(progress.get("total_pages") or 0)
        if total > 0:
            return min(60, 25 + int(35 * completed / total))
    return 35


def _mineru_provider_progress(
    status: dict[str, Any],
) -> dict[str, int] | None:
    progress = status.get("extract_progress")
    if not isinstance(progress, dict):
        return None
    try:
        extracted_pages = int(progress.get("extracted_pages") or 0)
        total_pages = int(progress.get("total_pages") or 0)
    except (TypeError, ValueError):
        return None
    if extracted_pages < 0 or total_pages < 0:
        return None
    return {
        "extractedPages": extracted_pages,
        "totalPages": total_pages,
    }


def _store_mineru_artifacts(
    job: dict[str, Any],
    bundle: MinerUNormalizedBundle,
) -> dict[str, dict[str, Any]]:
    references: dict[str, dict[str, Any]] = {}
    for artifact_key, artifact in bundle.artifacts.items():
        safe_name = Path(artifact.name).name
        object_name = (
            f"pipelines/mineru/{job['id']}/{safe_name}"
        )
        storage_url = object_storage.put_bytes(
            "ocr-artifacts",
            object_name,
            artifact.data,
            content_type=artifact.content_type,
        )
        if not storage_url:
            # Local/dev without object storage: keep the parse result usable
            # and skip artifact archiving. When storage is configured or
            # required, failing to persist must fail the job.
            if not object_storage.enabled and not object_storage.required:
                continue
            raise MinerUNormalizationError(
                "MINERU_PERSIST_FAILED",
                "MinerU artifact storage is unavailable.",
            )
        references[artifact_key] = {
            "objectName": object_name,
            "storageUrl": storage_url,
            "contentType": artifact.content_type,
            "byteLength": len(artifact.data),
            "sha256": artifact.sha256,
        }
    job["artifactReferences"] = references
    return references


def run_mineru_job(job: dict[str, Any]) -> dict[str, Any]:
    client = MinerUClient()
    source_temp_root: Path | None = None
    try:
        options = job.get("options")
        options = options if isinstance(options, dict) else {}
        provider_task_id = str(job.get("providerTaskId") or "")
        provider_task_type = str(job.get("providerTaskType") or "")
        submission: dict[str, Any] | None = None
        if provider_task_id:
            if provider_task_type not in {"task", "batch"}:
                raise MinerUNormalizationError(
                    "MINERU_PROVIDER_TASK_INVALID",
                    "MinerU provider task metadata is invalid.",
                )
            checkpoint = {
                "kind": provider_task_type,
                "providerTaskId": provider_task_id,
            }
            if (
                provider_task_type == "batch"
                and job.get("providerUploadState") != "uploaded"
            ):
                provider_state = client.submission_state(checkpoint)
                if provider_state != "waiting-file":
                    repo.update_ocr_job_record(
                        job,
                        provider_upload_state="uploaded",
                    )
                    _persist_mineru_job(job)
                    submission = checkpoint
            else:
                submission = checkpoint
        if submission is None and job.get("sourceType") == "url":
            source_url = str(job.get("sourceUrl") or "")
            if not source_url:
                raise MinerUNormalizationError(
                    "MINERU_SOURCE_MISSING",
                    "MinerU URL source is missing.",
                )
            repo.update_ocr_job_record(
                job,
                status="running",
                stage="submit",
                progress=5,
            )
            _persist_mineru_job(job)
            submission = client.submit_url(
                source_url,
                data_id=str(job["id"]),
                options=options,
            )
        elif submission is None:
            repo.update_ocr_job_record(
                job,
                status="running",
                stage="upload",
                progress=5,
            )
            _persist_mineru_job(job)
            source_path, source_temp_root = mineru_source_path(job)
            if not source_path or not source_path.is_file():
                raise MinerUNormalizationError(
                    "MINERU_SOURCE_MISSING",
                    "MinerU source file is unavailable.",
                )

            def submission_callback(
                checkpoint: dict[str, str],
            ) -> None:
                repo.update_ocr_job_record(
                    job,
                    status="running",
                    stage="upload",
                    progress=10,
                    provider_task_id=str(
                        checkpoint["providerTaskId"]
                    ),
                    provider_task_type=str(checkpoint["kind"]),
                    provider_upload_state=(
                        str(checkpoint["uploadState"])
                        if checkpoint.get("uploadState")
                        else None
                    ),
                )
                _persist_mineru_job(job)

            submission = client.submit_file(
                source_path,
                data_id=str(job["id"]),
                options=options,
                submission_callback=submission_callback,
            )
            repo.update_ocr_job_record(
                job,
                provider_upload_state="uploaded",
            )
            _persist_mineru_job(job)
        repo.update_ocr_job_record(
            job,
            status="running",
            stage="poll",
            progress=20,
            provider_task_id=str(submission["providerTaskId"]),
            provider_task_type=str(submission["kind"]),
        )
        _persist_mineru_job(job)

        def progress_callback(status: dict[str, Any]) -> None:
            provider_progress = _mineru_provider_progress(status)
            if provider_progress is not None:
                job["providerProgress"] = provider_progress
            repo.update_ocr_job_record(
                job,
                status="running",
                stage="poll",
                progress=_mineru_progress_value(status),
            )
            _persist_mineru_job(job)

        provider_result = client.wait_for_result(
            submission,
            progress_callback=progress_callback,
        )
        result_url = str(provider_result.get("full_zip_url") or "")
        if not result_url:
            raise MinerUNormalizationError(
                "MINERU_RESULT_URL_MISSING",
                "MinerU result URL is missing.",
            )
        repo.update_ocr_job_record(
            job,
            status="running",
            stage="download",
            progress=70,
        )
        _persist_mineru_job(job)
        zip_bytes = client.download_result(result_url)
        repo.update_ocr_job_record(
            job,
            status="running",
            stage="normalize",
            progress=80,
        )
        _persist_mineru_job(job)
        bundle = normalize_mineru_zip(
            zip_bytes,
            storage_key=str(job.get("storageKey") or ""),
            file_name=str(job.get("fileName") or "document.pdf"),
            profile_id=(
                str(job.get("profileId")) if job.get("profileId") else None
            ),
            document_type=(
                str(job.get("documentType"))
                if job.get("documentType")
                else None
            ),
            provider_task_id=str(job.get("providerTaskId") or ""),
        )
        repo.update_ocr_job_record(
            job,
            status="running",
            stage="persist",
            progress=90,
        )
        _persist_mineru_job(job)
        artifact_references = _store_mineru_artifacts(job, bundle)
        result = deepcopy(bundle.result)
        metadata = result.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            result["metadata"] = metadata
        metadata["artifactReferences"] = deepcopy(artifact_references)
        return result
    finally:
        if source_temp_root is not None:
            shutil.rmtree(source_temp_root, ignore_errors=True)


def _mineru_failure_code(job: dict[str, Any], exc: Exception) -> str:
    if isinstance(exc, (MinerUError, MinerUNormalizationError)):
        return str(exc.code)
    return {
        "submit": "MINERU_SUBMIT_FAILED",
        "upload": "MINERU_SUBMIT_FAILED",
        "poll": "MINERU_JOB_FAILED",
        "download": "MINERU_RESULT_DOWNLOAD_FAILED",
        "normalize": "MINERU_RESULT_INVALID",
        "persist": "MINERU_PERSIST_FAILED",
    }.get(str(job.get("stage") or ""), "MINERU_JOB_FAILED")


def _execute_mineru_ocr_extract(
    self,
    job_record_id: str,
    *,
    retry_handler: Callable[[int, list[dict[str, Any]]], None] | None = None,
) -> dict[str, Any]:
    refresh_worker_state(
        {"ocr_jobs", "ocr_parse_results", "documents", "versions"}
    )
    job = repo.find_one("ocr_jobs", job_record_id)
    if not job:
        return {
            "jobId": job_record_id,
            "status": "failed",
            "diagnostics": [
                {
                    "code": "MINERU_JOB_NOT_FOUND",
                    "level": "error",
                    "retryable": False,
                }
            ],
        }
    if job.get("provider") != "mineru":
        diagnostics = [
            {
                "code": "MINERU_PROVIDER_INVALID",
                "level": "error",
                "retryable": False,
            }
        ]
        repo.update_ocr_job_record(
            job,
            status="failed",
            stage="failed",
            progress=100,
            diagnostics=diagnostics,
        )
        _persist_mineru_job(job)
        return {
            "jobId": job_record_id,
            "status": "failed",
            "diagnostics": diagnostics,
        }
    if job.get("status") in {"success", "failed", "canceled"}:
        response = {
            "jobId": job_record_id,
            "status": str(job.get("status")),
            "alreadyCompleted": True,
        }
        if job.get("parseResultId"):
            response["parseResultId"] = job.get("parseResultId")
        return response
    document_id = str(job.get("documentId") or "")
    version_id = str(job.get("documentVersionId") or "")
    if document_id and version_id:
        refresh_ocr_worker_state(document_id, version_id)
        job = repo.find_one("ocr_jobs", job_record_id) or job
    repo.update_ocr_job_record(
        job,
        status="running",
        stage="submit",
        progress=1,
    )
    _persist_mineru_job(job)
    try:
        result = run_mineru_job(job)
        result_record = repo.finish_ocr_job_record(job, result)
        _finalize_mineru_pipeline(job, result, result_record)
        bound_document = (
            repo.find_one("documents", document_id) if document_id else None
        )
        bound_version = (
            repo.find_one("versions", version_id) if version_id else None
        )
        applied = None
        if (
            bound_document is not None
            and bound_version is not None
            and str(bound_version.get("documentId") or "") == document_id
        ):
            applied = repo.apply_ocr_result(document_id, version_id, result)
            flush_state_records(
                ocr_result_state_records(document_id, version_id)
            )
        else:
            flush_state_records(
                {
                    "ocr_jobs": [job],
                    "ocr_parse_results": [result_record]
                    if result_record
                    else [],
                }
            )
        return {
            "jobId": job_record_id,
            "status": "success",
            "parseResultId": (
                (result_record or {}).get("parseResultId")
                or result.get("parseResultId")
            ),
            "applied": applied,
            "artifactReferences": deepcopy(
                job.get("artifactReferences") or {}
            ),
        }
    except Exception as exc:  # noqa: BLE001 - Celery task boundary persists a safe failure.
        code = _mineru_failure_code(job, exc)
        retryable = bool(getattr(exc, "retryable", False))
        failed_stage = str(job.get("stage") or "unknown")
        diagnostics = [
            {
                "code": code,
                "level": "error",
                "retryable": retryable,
                "stage": failed_stage,
            }
        ]
        retry_index = int(getattr(self.request, "retries", 0) or 0)
        called_directly = bool(
            getattr(self.request, "called_directly", False)
        )
        if retryable and not called_directly and retry_index < 3:
            repo.update_ocr_job_record(
                job,
                status="queued",
                stage="retrying",
                progress=min(int(job.get("progress") or 0), 99),
                diagnostics=diagnostics,
            )
            _persist_mineru_job(job)
            countdown = (10, 30, 90)[min(retry_index, 2)]
            if retry_handler is not None:
                retry_handler(countdown, deepcopy(diagnostics))
            raise self.retry(exc=exc, countdown=countdown)
        failure_result = {
            "storageKey": job.get("storageKey"),
            "fileName": job.get("fileName"),
            "status": "failed",
            "outcomeStatus": "failed",
            "diagnostics": diagnostics,
            "fragments": [],
            "layoutBlocks": [],
            "tables": [],
            "seals": [],
            "signatures": [],
            "fields": [],
            "engineRuns": [
                {
                    "engine": "mineru_vlm",
                    "status": "failed",
                    "errorCode": code,
                }
            ],
            "metadata": {"provider": "mineru", "model": "vlm"},
        }
        result_record = repo.finish_ocr_job_record(job, failure_result)
        _finalize_mineru_pipeline(job, failure_result, result_record)
        bound_document = (
            repo.find_one("documents", document_id) if document_id else None
        )
        bound_version = (
            repo.find_one("versions", version_id) if version_id else None
        )
        if (
            bound_document is not None
            and bound_version is not None
            and str(bound_version.get("documentId") or "") == document_id
        ):
            repo.apply_ocr_result(document_id, version_id, failure_result)
        if document_id and version_id:
            failure_records = ocr_result_state_records(
                document_id,
                version_id,
            )
        else:
            failure_records = {
                "ocr_jobs": [job],
                "ocr_parse_results": [result_record]
                if result_record
                else [],
            }
        flush_state_records(failure_records)
        return {
            "jobId": job_record_id,
            "status": "failed",
            "diagnostics": diagnostics,
        }


class MinerUPostgresRetry(RuntimeError):
    def __init__(
        self,
        *,
        countdown: int,
        diagnostics: list[dict[str, Any]],
    ) -> None:
        super().__init__("MinerU PostgreSQL job should be retried.")
        self.countdown = int(countdown)
        self.diagnostics = deepcopy(diagnostics)


def execute_mineru_postgres_job(
    job_record_id: str,
    *,
    tenant_id: str,
    retry_index: int,
) -> dict[str, Any]:
    """Run the validated MinerU task body with PostgreSQL-owned retries."""

    class Request:
        retries = max(0, int(retry_index))
        called_directly = False

    class TaskContext:
        request = Request()

        @staticmethod
        def retry(*_args, **_kwargs):
            raise AssertionError("PostgreSQL retry handler was not invoked")

    def request_retry(
        countdown: int,
        diagnostics: list[dict[str, Any]],
    ) -> None:
        raise MinerUPostgresRetry(
            countdown=countdown,
            diagnostics=diagnostics,
        )

    tenant_context = set_request_tenant_id(tenant_id)
    try:
        return _execute_mineru_ocr_extract(
            TaskContext(),
            job_record_id,
            retry_handler=request_retry,
        )
    finally:
        reset_request_tenant_id(tenant_context)


@celery_app.task(bind=True, max_retries=3)
@pipeline_task_lock(
    "mineru-ocr",
    lambda _self, job_record_id, tenant_id=None: (
        f"{tenant_id or current_tenant_id()}:{job_record_id}"
    ),
)
def mineru_ocr_extract(
    self,
    job_record_id: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    tenant_context = set_request_tenant_id(
        str(tenant_id or current_tenant_id())
    )
    try:
        return _execute_mineru_ocr_extract(self, job_record_id)
    finally:
        reset_request_tenant_id(tenant_context)


def default_ocr_provider(
    env: Mapping[str, str] | None = None,
) -> str:
    source = env if env is not None else os.environ
    configured = str(
        source.get("AICHECK_OCR_DEFAULT_PROVIDER") or ""
    ).strip()
    return (configured or "mineru").lower()


def resolve_ocr_provider(
    options: Mapping[str, Any],
    env: Mapping[str, str] | None = None,
) -> str:
    explicit = str(options.get("provider") or "").strip().lower()
    return explicit or default_ocr_provider(env)


@celery_app.task(bind=True, max_retries=3)
@pipeline_task_lock("ocr-document", lambda _self, _document_id, version_id, *_args, **_kwargs: str(version_id))
def parse_document(self, document_id: str, version_id: str, storage_key: str, file_name: str | None = None) -> dict[str, Any]:
    refresh_ocr_worker_state(document_id, version_id)
    task = repo.ocr_task_for(document_id, version_id, file_name)
    version = repo.find_one("versions", version_id)
    if task is None and version is None:
        refresh_ocr_worker_state(document_id, version_id)
        task = repo.ocr_task_for(document_id, version_id, file_name)
        version = repo.find_one("versions", version_id)
    if task and task.get("status") == "已取消":
        return {"documentId": document_id, "versionId": version_id, "status": "canceled"}
    if task and task.get("status") == "成功" and (version or {}).get("ocrStatus") == "已识别":
        return {"documentId": document_id, "versionId": version_id, "status": "success", "alreadyCompleted": True}
    repo.mark_task_running(task, "OCR worker 开始处理。")
    document = repo.find_one("documents", document_id)
    profile_id = (version or {}).get("ocrProfileId") or (document or {}).get("ocrProfileId")
    document_type = (version or {}).get("documentType") or (document or {}).get("documentType")
    preliminary_profile_id = infer_preliminary_profile_id(file_name, profile_id, document_type)
    knowledge_file = repo.knowledge_file_for_version(version_id)
    has_business_ocr_profile = preliminary_profile_id != "generic_document_v1" or bool(document_type)
    ocr_options: dict[str, Any] = {}
    if isinstance((version or {}).get("ocrOptions"), dict):
        ocr_options.update(deepcopy(version["ocrOptions"]))
    requested_provider = resolve_ocr_provider(ocr_options)
    if not has_business_ocr_profile:
        ocr_options.update(
            {
                "quickMode": True,
                "enableTables": False,
                "enableSeals": False,
                "enableFallback": False,
                "disableRemediation": True,
            }
        )
    if (knowledge_file or {}).get("sourceType") == "standard":
        ocr_options.update(
            {
                "standardIndexingStrategy": "auto_text_layer_then_remote_ocr",
                "preferTextLayer": True,
                "enableFallback": True,
            }
        )
    resolved_profile = default_profile(preliminary_profile_id, document_type)
    resolved_profile_id = str(resolved_profile.get("profileId") or profile_id or "generic_document_v1")
    accuracy_pipeline_requested = pipeline_enabled(
        resolved_profile_id,
        source_type=(knowledge_file or {}).get("sourceType"),
    )
    if accuracy_pipeline_requested:
        ocr_options = accuracy_pipeline_baseline_options(ocr_options)
    run_key = pipeline_run_key(document_id, version_id, storage_key, resolved_profile_id)
    pipeline_run = repo.create_or_resume_ocr_pipeline_run(
        run_key=run_key,
        document_id=document_id,
        version_id=version_id,
        storage_key=storage_key,
        storage_bucket=str((version or {}).get("storageBucket") or "documents"),
        file_name=file_name,
        profile_id=resolved_profile_id,
        document_type=document_type,
        mode=pipeline_mode(),
        pipeline_version=pipeline_version(),
        project_id=str((document or {}).get("projectId") or "") or None,
        operation_id=(task or {}).get("operationId"),
        task_id=str(getattr(self.request, "id", "") or "") or None,
    )
    if pipeline_run.get("status") == "completed":
        return {
            "documentId": document_id,
            "versionId": version_id,
            "status": "success",
            "alreadyCompleted": True,
            "pipelineRunId": pipeline_run.get("id"),
        }
    repo.mark_ocr_pipeline_stage(pipeline_run, "prepare", "running")
    repo.mark_ocr_pipeline_stage(pipeline_run, "prepare", "success")
    repo.mark_ocr_pipeline_stage(pipeline_run, "text_scan", "queued")
    ocr_job_record = repo.create_ocr_job_record(
        document_id=document_id,
        version_id=version_id,
        storage_key=storage_key,
        file_name=file_name,
        profile_id=resolved_profile_id,
        document_type=document_type,
        provider="mineru" if requested_provider == "mineru" else None,
        options=(
            {**ocr_options, "provider": "mineru"}
            if requested_provider == "mineru"
            else None
        ),
    )
    pipeline_run["ocrJobRecordId"] = ocr_job_record.get("id")
    if requested_provider not in {"", "local", "mineru"}:
        failure_result = {
            "storageKey": storage_key,
            "fileName": file_name,
            "status": "failed",
            "outcomeStatus": "failed",
            "diagnostics": [
                {
                    "code": "OCR_PROVIDER_UNSUPPORTED",
                    "level": "error",
                }
            ],
            "fragments": [],
            "layoutBlocks": [],
            "tables": [],
            "seals": [],
            "signatures": [],
            "fields": [],
            "engineRuns": [],
        }
        repo.finish_ocr_job_record(ocr_job_record, failure_result)
        repo.mark_ocr_pipeline_stage(
            pipeline_run,
            "text_scan",
            "failed",
            blocking_reasons=[
                {"code": "OCR_PROVIDER_UNSUPPORTED"}
            ],
        )
        repo.finish_ocr_pipeline_run(
            pipeline_run,
            status="failed",
            blocking_reasons=[
                {"code": "OCR_PROVIDER_UNSUPPORTED"}
            ],
            recommended_action="Use provider local or mineru.",
        )
        if document and version:
            repo.apply_ocr_result(document_id, version_id, failure_result)
            flush_state_records(ocr_result_state_records(document_id, version_id))
        persist_ocr_pipeline_progress(
            pipeline_run,
            task=task,
            ocr_job=ocr_job_record,
        )
        return {
            **failure_result,
            "documentId": document_id,
            "versionId": version_id,
            "pipelineRunId": pipeline_run.get("id"),
            "ocrJobRecordId": ocr_job_record.get("id"),
        }
    if requested_provider == "mineru":
        pipeline_run.update(
            {
                "providerMode": "explicit_remote",
                "provider": "mineru",
                "model": "vlm",
                "cloudGrounded": True,
            }
        )
        ocr_job_record["pipelineRunId"] = pipeline_run.get("id")
        persist_ocr_pipeline_progress(
            pipeline_run,
            task=task,
            ocr_job=ocr_job_record,
        )
        dispatch = task_dispatcher.dispatch_mineru_ocr(
            str(ocr_job_record["id"])
        )
        pipeline_run["mineruDispatch"] = dispatch
        if not dispatch.get("taskId") and dispatch.get("mode") not in {"inline", "postgres"}:
            diagnostics = [
                {
                    "code": "MINERU_DISPATCH_UNAVAILABLE",
                    "level": "error",
                    "retryable": True,
                }
            ]
            repo.update_ocr_job_record(
                ocr_job_record,
                status="failed",
                stage="dispatch",
                progress=100,
                diagnostics=diagnostics,
            )
            repo.mark_ocr_pipeline_stage(
                pipeline_run,
                "text_scan",
                "failed",
                blocking_reasons=diagnostics,
            )
            repo.finish_ocr_pipeline_run(
                pipeline_run,
                status="failed",
                blocking_reasons=diagnostics,
                recommended_action=(
                    "Check the ocr.remote worker and retry."
                ),
            )
            if document and version:
                repo.apply_ocr_result(
                    document_id,
                    version_id,
                    {
                        "storageKey": storage_key,
                        "fileName": file_name,
                        "status": "failed",
                        "outcomeStatus": "failed",
                        "diagnostics": diagnostics,
                    },
                )
                flush_state_records(
                    ocr_result_state_records(document_id, version_id)
                )
            persist_ocr_pipeline_progress(
                pipeline_run,
                task=task,
                ocr_job=ocr_job_record,
            )
            return {
                "documentId": document_id,
                "versionId": version_id,
                "status": "failed",
                "provider": "mineru",
                "pipelineRunId": pipeline_run.get("id"),
                "ocrJobRecordId": ocr_job_record.get("id"),
                "dispatch": dispatch,
                "diagnostics": diagnostics,
            }
        if task:
            task["progress"] = max(int(task.get("progress") or 0), 15)
            task["updatedAt"] = server_time()
            repo.append_task_log(task, "info", "MinerU OCR queued.")
        persist_ocr_pipeline_progress(
            pipeline_run,
            task=task,
            ocr_job=ocr_job_record,
        )
        inline_result = (
            dispatch.get("result")
            if dispatch.get("mode") == "inline"
            and isinstance(dispatch.get("result"), dict)
            else None
        )
        return {
            "documentId": document_id,
            "versionId": version_id,
            "status": (
                str(inline_result.get("status") or "failed")
                if inline_result
                else "queued"
            ),
            "provider": "mineru",
            "model": "vlm",
            "pipelineRunId": pipeline_run.get("id"),
            "ocrJobRecordId": ocr_job_record.get("id"),
            "dispatch": dispatch,
        }
    runtime = ocr_runtime_config()
    current_pipeline_mode = str(pipeline_run.get("mode") or pipeline_mode())
    official_shadow = official_ocr_enabled(runtime) and current_pipeline_mode == "shadow"
    if accuracy_pipeline_requested and official_ocr_primary_enabled(current_pipeline_mode, runtime):
        pipeline_run["officialOcrJobRecordId"] = ocr_job_record.get("id")
        pipeline_run.update(
            {
                "providerMode": runtime["mode"],
                "provider": runtime["official"]["provider"],
                "model": runtime["official"]["primaryModel"],
                "cloudGrounded": False,
                "costCny": 0.0,
            }
        )
        required_tables = bool(resolved_profile.get("requiredTables"))
        seal_required = bool((resolved_profile.get("sealRules") or {}).get("required"))
        repo.mark_ocr_pipeline_stage(
            pipeline_run,
            "structure_scan",
            "queued" if required_tables else "skipped",
            engine_status={} if required_tables else {"skipReasons": ["profile_has_no_required_tables"]},
        )
        repo.mark_ocr_pipeline_stage(
            pipeline_run,
            "seal_signature_scan",
            "queued" if seal_required else "skipped",
            engine_status={} if seal_required else {"skipReasons": ["profile_does_not_require_seal"]},
        )
        repo.mark_ocr_pipeline_stage(pipeline_run, "evidence_fusion", "queued")
        dispatch = _dispatch_pipeline_stage_once(
            pipeline_run,
            "officialOcrDispatch",
            task_dispatcher.dispatch_ocr_pipeline_official,
        )
        if not dispatch.get("taskId"):
            reason = str(dispatch.get("statusReason") or "official_ocr_dispatch_failed")
            repo.mark_ocr_pipeline_stage(pipeline_run, "text_scan", "failed", failure_reason=reason)
            repo.finish_ocr_pipeline_run(
                pipeline_run,
                status="failed",
                blocking_reasons=[{"code": "OFFICIAL_OCR_DISPATCH_FAILED"}],
                recommended_action="Check the ocr.remote worker and retry.",
                formal_evidence_ready=False,
            )
            repo.mark_task_failed(task, "Official OCR could not be queued.")
            persist_ocr_pipeline_progress(pipeline_run, task=task, ocr_job=ocr_job_record)
            return {
                "documentId": document_id,
                "versionId": version_id,
                "status": "failed",
                "pipelineRunId": pipeline_run.get("id"),
                "ocrJobRecordId": ocr_job_record.get("id"),
                "dispatch": dispatch,
            }
        if task:
            task["progress"] = max(int(task.get("progress") or 0), 15)
            task["updatedAt"] = server_time()
            repo.append_task_log(task, "info", "Official OCR queued.")
        persist_ocr_pipeline_progress(pipeline_run, task=task, ocr_job=ocr_job_record)
        return {
            "documentId": document_id,
            "versionId": version_id,
            "status": "queued",
            "pipelineRunId": pipeline_run.get("id"),
            "ocrJobRecordId": ocr_job_record.get("id"),
            "dispatch": dispatch,
            "providerMode": runtime["mode"],
        }

    repo.mark_ocr_pipeline_stage(pipeline_run, "text_scan", "running")
    repo.mark_ocr_job_running(ocr_job_record, pipeline_run_id=str(pipeline_run.get("id") or ""))
    persist_ocr_pipeline_progress(pipeline_run, task=task, ocr_job=ocr_job_record)
    previous_record_ids = state_record_ids(ocr_result_state_records(document_id, version_id))
    try:
        result = parse_with_ocr_service(
            storage_key,
            file_name=file_name,
            document_id=document_id,
            version_id=version_id,
            profile_id=resolved_profile_id,
            document_type=document_type,
            options=ocr_options,
        )
        if str(result.get("status") or "").lower() != "success":
            raise RuntimeError("ocr_service_returned_failed_result")
    except Exception as exc:
        failure_result = {
            "storageKey": storage_key,
            "fileName": file_name,
            "status": "failed",
            "fragments": [],
            "fields": [],
            "seals": [],
            "diagnostics": [service_failure_message("OCR 服务"), {"code": exc.__class__.__name__.upper()}],
        }
        repo.finish_ocr_job_record(ocr_job_record, failure_result)
        retry_index = int(getattr(self.request, "retries", 0) or 0)
        should_retry = not bool(getattr(self.request, "called_directly", False)) and task_dispatcher.dispatch_mode() == "celery"
        if retry_index < 3 and should_retry:
            countdown = (10, 30, 90)[retry_index]
            repo.mark_ocr_pipeline_stage(
                pipeline_run,
                "text_scan",
                "retrying",
                failure_reason=exc.__class__.__name__,
            )
            pipeline_run["recommendedAction"] = f"系统将在 {countdown} 秒后重试本地扫描。"
            if task:
                task["status"] = "排队中"
                task["progress"] = 5
                task["updatedAt"] = server_time()
                repo.append_task_log(task, "warning", pipeline_run["recommendedAction"])
            try:
                persist_ocr_pipeline_progress(pipeline_run, task=task, ocr_job=ocr_job_record)
            except Exception:
                pass
            raise self.retry(exc=exc, countdown=countdown)
        repo.mark_ocr_pipeline_stage(
            pipeline_run,
            "text_scan",
            "failed",
            blocking_reasons=[{"code": "OCR_SERVICE_FAILED"}],
            failure_reason=exc.__class__.__name__,
        )
        repo.finish_ocr_pipeline_run(
            pipeline_run,
            status="failed",
            blocking_reasons=[{"code": "OCR_SERVICE_FAILED"}],
            recommended_action="检查 OCR 服务后从任务中心重试。",
        )
        failed_applied, _ = pipeline_apply_result(
            document_id,
            version_id,
            failure_result,
            previous_record_ids,
        )
        persist_ocr_pipeline_progress(pipeline_run, task=task, ocr_job=ocr_job_record)
        return {
            **failure_result,
            "applied": failed_applied,
            "pipelineRunId": pipeline_run.get("id"),
            "ocrJobRecordId": ocr_job_record.get("id"),
        }
    parse_result_record = repo.finish_ocr_job_record(ocr_job_record, result)
    routed_profile = profile_from_ocr_result(parse_result_record or result, resolved_profile)
    routed_profile_id = str(routed_profile.get("profileId") or resolved_profile_id)
    route_metadata = (parse_result_record or result).get("metadata")
    route_metadata = route_metadata if isinstance(route_metadata, dict) else {}
    pipeline_run["requestedProfileId"] = resolved_profile_id
    pipeline_run["profileId"] = routed_profile_id
    pipeline_run["documentType"] = routed_profile.get("documentType") or document_type
    pipeline_run["detectedProfileId"] = route_metadata.get("detectedProfileId") or routed_profile_id
    pipeline_run["profileRouteReason"] = route_metadata.get("profileRouteReason") or (
        "filename_signal" if preliminary_profile_id != str(profile_id or "generic_document_v1") else "requested_profile"
    )
    pipeline_run["baselineParseResultId"] = (parse_result_record or {}).get("parseResultId")
    pipeline_run["parseResultId"] = (parse_result_record or {}).get("parseResultId")
    pipeline_run["pipelineOptions"] = {
        key: ocr_options[key]
        for key in ["disableResultCache", "disableEngineResultCache", "disableVariantCache", "runAllVariants"]
        if key in ocr_options
    }
    local_artifact_url, local_artifact_hash = store_ocr_pipeline_artifact(
        pipeline_run,
        "local_scan",
        parse_result_record or result,
    )
    mark_local_pipeline_stages(
        pipeline_run,
        parse_result_record or result,
        routed_profile,
        artifact_url=local_artifact_url,
        artifact_hash=local_artifact_hash,
    )
    accuracy_pipeline_enabled = pipeline_enabled(
        routed_profile_id,
        source_type=(knowledge_file or {}).get("sourceType"),
    )
    applied: dict[str, Any] = {"status": "queued"}
    targeting = None
    if current_pipeline_mode != "active" or not accuracy_pipeline_enabled:
        applied, targeting = pipeline_apply_result(document_id, version_id, result, previous_record_ids)
    next_dispatch = None
    document_ai_shadow_dispatch = None
    qwen_pipeline_dispatch = None
    pipeline_stage_dispatch = None
    if accuracy_pipeline_enabled:
        # Persist the baseline parse result before a worker on another queue can consume it.
        flush_state_records(ocr_result_state_records(document_id, version_id))
        required_tables = bool(routed_profile.get("requiredTables"))
        seal_required = bool((routed_profile.get("sealRules") or {}).get("required"))
        if official_shadow:
            official_job = repo.create_ocr_job_record(
                document_id=document_id,
                version_id=version_id,
                storage_key=storage_key,
                file_name=file_name,
                profile_id=routed_profile_id,
                document_type=routed_profile.get("documentType") or document_type,
                record_id=f"{ocr_job_record['id']}-OFFICIAL",
            )
            pipeline_run["officialOcrJobRecordId"] = official_job.get("id")
            pipeline_run.update(
                {
                    "providerMode": runtime["mode"],
                    "provider": runtime["official"]["provider"],
                    "model": runtime["official"]["primaryModel"],
                    "cloudGrounded": False,
                    "costCny": 0.0,
                }
            )
            pipeline_stage_dispatch = _dispatch_pipeline_stage_once(
                pipeline_run,
                "officialOcrDispatch",
                task_dispatcher.dispatch_ocr_pipeline_official,
            )
        elif required_tables:
            pipeline_stage_dispatch = _dispatch_pipeline_stage_once(
                pipeline_run,
                "structureDispatch",
                task_dispatcher.dispatch_ocr_pipeline_structure,
            )
        elif seal_required:
            pipeline_stage_dispatch = _dispatch_pipeline_stage_once(
                pipeline_run,
                "sealDispatch",
                task_dispatcher.dispatch_ocr_pipeline_seal,
            )
        else:
            pipeline_stage_dispatch = _dispatch_pipeline_stage_once(
                pipeline_run,
                "fusionDispatch",
                task_dispatcher.dispatch_ocr_pipeline_fusion,
            )
        if not pipeline_stage_dispatch.get("taskId"):
            repo.mark_ocr_pipeline_stage(
                pipeline_run,
                (
                    "text_scan"
                    if official_shadow
                    else "structure_scan"
                    if required_tables
                    else "seal_signature_scan"
                    if seal_required
                    else "evidence_fusion"
                ),
                "failed",
                failure_reason=str(
                    pipeline_stage_dispatch.get("statusReason")
                    or "pipeline_stage_dispatch_failed"
                ),
            )
            repo.finish_ocr_pipeline_run(
                pipeline_run,
                status="failed" if current_pipeline_mode == "active" else "partial",
                blocking_reasons=[{"code": "PIPELINE_STAGE_DISPATCH_FAILED"}],
                recommended_action="检查 cpu.heavy/business.light worker 后重试。",
            )
    else:
        repo.mark_ocr_pipeline_stage(pipeline_run, "evidence_fusion", "success")
        repo.mark_ocr_pipeline_stage(pipeline_run, "qwen_extract", "skipped")
        repo.mark_ocr_pipeline_stage(pipeline_run, "grounding_validate", "skipped")
        repo.mark_ocr_pipeline_stage(pipeline_run, "finalize", "running")
        repo.mark_ocr_pipeline_stage(pipeline_run, "finalize", "success")
        repo.finish_ocr_pipeline_run(
            pipeline_run,
            status="completed" if applied.get("status") == "success" else "partial",
            blocking_reasons=[],
            formal_evidence_ready=False,
        )
    if applied.get("status") == "success" and not accuracy_pipeline_enabled:
        try:
            document_ai_shadow_dispatch = schedule_document_ai_shadow(
                document_id=document_id,
                version_id=version_id,
                storage_key=storage_key,
                file_name=file_name,
                profile_id=resolved_profile_id,
                parse_result=parse_result_record or result,
                operation_id=str(getattr(self.request, "id", "") or "") or None,
            )
        except Exception as exc:  # Shadow must never change baseline OCR completion.
            document_ai_shadow_dispatch = {
                "status": "not_dispatched",
                "statusReason": f"shadow_setup_{exc.__class__.__name__.lower()}",
            }
        if knowledge_file:
            next_dispatch = task_dispatcher.dispatch_slice(knowledge_file["id"])
    persist_ocr_pipeline_progress(pipeline_run, task=task, ocr_job=ocr_job_record)
    return {
        **result,
        "applied": applied,
        "nextDispatch": next_dispatch,
        "targeting": targeting,
        "ocrJobRecordId": ocr_job_record.get("id"),
        "ocrParseResultId": (parse_result_record or {}).get("parseResultId"),
        "documentAiShadowDispatch": document_ai_shadow_dispatch,
        "pipelineRunId": pipeline_run.get("id"),
        "pipelineStageDispatch": pipeline_stage_dispatch,
        "qwenPipelineDispatch": qwen_pipeline_dispatch,
    }


def _pipeline_stage_context(run_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    refresh_worker_state(
        {
            "documents",
            "versions",
            "ocr_jobs",
            "ocr_parse_results",
            "ocr_pipeline_runs",
            "ocr_stage_runs",
            "model_call_attempts",
        }
    )
    run = repo.find_one("ocr_pipeline_runs", run_id)
    if not run:
        return None, None, {}
    baseline = repo.find_one(
        "ocr_parse_results",
        str(run.get("baselineParseResultId") or ""),
        id_field="parseResultId",
    )
    profile = default_profile(run.get("profileId"), run.get("documentType"))
    return run, baseline, profile


def _stage_record(run: dict[str, Any], stage: str) -> dict[str, Any] | None:
    return next(
        (item for item in repo.ocr_pipeline_stages(str(run.get("id") or "")) if item.get("stage") == stage),
        None,
    )


def _dispatch_pipeline_stage_once(
    run: dict[str, Any],
    key: str,
    dispatcher: Any,
) -> dict[str, Any]:
    existing = run.get(key)
    if isinstance(existing, dict) and existing.get("taskId"):
        return existing
    dispatched = dispatcher(str(run.get("id") or ""))
    run[key] = dispatched
    persist_ocr_pipeline_progress(run)
    return dispatched


def _next_after_structure(run: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    if bool((profile.get("sealRules") or {}).get("required")):
        return _dispatch_pipeline_stage_once(
            run,
            "sealDispatch",
            task_dispatcher.dispatch_ocr_pipeline_seal,
        )
    return _dispatch_pipeline_stage_once(
        run,
        "fusionDispatch",
        task_dispatcher.dispatch_ocr_pipeline_fusion,
    )


def _next_after_seal(run: dict[str, Any]) -> dict[str, Any]:
    return _dispatch_pipeline_stage_once(
        run,
        "fusionDispatch",
        task_dispatcher.dispatch_ocr_pipeline_fusion,
    )


def _persist_pipeline_stage_result(
    run: dict[str, Any],
    stage: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    identity = hashlib.sha256(
        f"{run.get('id')}:{stage}:{run.get('pipelineVersion')}".encode("utf-8")
    ).hexdigest()[:16].upper()
    job_id = f"OCRJOB-STAGE-{identity}"
    parse_result_id = f"PARSE-STAGE-{identity}"
    stage_result = deepcopy(result)
    stage_result["parseResultId"] = parse_result_id
    job = repo.create_ocr_job_record(
        document_id=str(run.get("documentId") or ""),
        version_id=str(run.get("documentVersionId") or ""),
        storage_key=str(run.get("storageKey") or ""),
        file_name=run.get("fileName"),
        profile_id=run.get("profileId"),
        document_type=run.get("documentType"),
        record_id=job_id,
    )
    job["pipelineStage"] = stage
    repo.mark_ocr_job_running(job, pipeline_run_id=str(run.get("id") or ""))
    record = repo.finish_ocr_job_record(job, stage_result) or stage_result
    record["pipelineStage"] = stage
    record["pipelineRunId"] = run.get("id")
    result_key = {
        "structure_scan": "structureParseResultId",
        "seal_signature_scan": "sealParseResultId",
        "evidence_fusion": "fusedParseResultId",
    }.get(stage, f"{stage}ParseResultId")
    run[result_key] = record.get("parseResultId") or record.get("id")
    flush_state_records(
        {
            "ocr_jobs": [job],
            "ocr_parse_results": [record],
            "ocr_pipeline_runs": [run],
        }
    )
    return record


def _pipeline_stage_parse_options(
    stage: str,
    baseline_parse_result_id: str,
    pipeline_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    common = {
        "baselineParseResultId": baseline_parse_result_id,
        "disableFastFirst": True,
        "forceHeavyEngines": True,
        "quickMode": False,
        "enableFallback": False,
        "tesseractPolicy": "disabled",
        **{
            key: value
            for key, value in (pipeline_options or {}).items()
            if key in {"disableResultCache", "disableEngineResultCache", "disableVariantCache", "runAllVariants"}
        },
    }
    if stage == "structure_scan":
        return {
            **common,
            "engineAllowlist": sorted(STRUCTURE_ENGINES),
            "enableTables": True,
            "enableSeals": False,
            "disableRemediation": True,
        }
    return {
        **common,
        "engineAllowlist": sorted(SEAL_ENGINES),
        "enableTables": False,
        "enableSeals": True,
        "disableRemediation": False,
        "enableSealCropEvidence": True,
    }


def _run_pipeline_heavy_stage(
    run: dict[str, Any],
    baseline: dict[str, Any],
    profile: dict[str, Any],
    *,
    stage: str,
    expected_engines: set[str],
) -> tuple[dict[str, Any], dict[str, Any], str, list[dict[str, Any]]]:
    result = parse_with_ocr_service(
        str(run.get("storageKey") or ""),
        file_name=run.get("fileName"),
        document_id=str(run.get("documentId") or ""),
        version_id=str(run.get("documentVersionId") or ""),
        profile_id=str(profile.get("profileId") or run.get("profileId") or ""),
        document_type=str(profile.get("documentType") or run.get("documentType") or ""),
        options=_pipeline_stage_parse_options(
            stage,
            str(baseline.get("parseResultId") or baseline.get("id") or ""),
            run.get("pipelineOptions") if isinstance(run.get("pipelineOptions"), dict) else {},
        ),
    )
    summary = stage_engine_summary(result, expected_engines)
    status, blockers = _heavy_stage_outcome(stage, result, summary)
    return result, summary, status, blockers


def _heavy_stage_outcome(
    stage: str,
    result: dict[str, Any],
    summary: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    executed = set(summary.get("engineExecuted") or [])
    succeeded = set(summary.get("engineSucceeded") or [])
    if not executed:
        raise RuntimeError(f"{stage}_engine_not_executed")
    if stage == "structure_scan":
        usable = "pp_structure_v3" in succeeded and bool(result.get("tables"))
        blockers = [] if usable else [{"code": "PP_STRUCTURE_RESULT_NOT_USABLE"}]
    else:
        usable = "paddlex_seal_recognition" in succeeded and bool(result.get("seals"))
        blockers = [] if usable else [{"code": "SEAL_MODEL_RESULT_NOT_USABLE"}]
    return "success" if usable else "partial", blockers


def _append_local_stage_blockers(run: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    existing = [item for item in run.get("localStageBlockingReasons") or [] if isinstance(item, dict)]
    known = {stable_payload_hash(item) for item in existing}
    for blocker in blockers:
        digest = stable_payload_hash(blocker)
        if digest not in known:
            existing.append(deepcopy(blocker))
            known.add(digest)
    run["localStageBlockingReasons"] = existing


def _complete_saved_heavy_stage(
    run: dict[str, Any],
    *,
    stage: str,
    parse_result: dict[str, Any],
    expected_engines: set[str],
) -> str:
    summary = stage_engine_summary(parse_result, expected_engines)
    status, blockers = _heavy_stage_outcome(stage, parse_result, summary)
    artifact_url, artifact_hash = store_ocr_pipeline_artifact(run, stage, parse_result)
    repo.mark_ocr_pipeline_stage(
        run,
        stage,
        status,
        engine_status=summary,
        blocking_reasons=blockers,
        artifact_url=artifact_url,
        artifact_hash=artifact_hash,
    )
    _append_local_stage_blockers(run, blockers)
    persist_ocr_pipeline_progress(run)
    return status


def _persist_retry_state(run: dict[str, Any]) -> None:
    try:
        persist_ocr_pipeline_progress(run)
    except Exception:
        # The Celery retry still needs to be scheduled when PostgreSQL is briefly unavailable.
        pass


@celery_app.task(bind=True, max_retries=3)
@pipeline_task_lock("ocr-structure", lambda _self, run_id: str(run_id))
def ocr_pipeline_structure_scan(self, run_id: str) -> dict[str, Any]:
    run, baseline, profile = _pipeline_stage_context(run_id)
    if not run:
        return {"pipelineRunId": run_id, "status": "missing"}
    existing = _stage_record(run, "structure_scan")
    if run.get("structureParseResultId") and (existing or {}).get("status") in {"success", "partial"}:
        return {"pipelineRunId": run_id, "status": (existing or {}).get("status"), "nextDispatch": _next_after_structure(run, profile)}
    if not baseline:
        return {"pipelineRunId": run_id, "status": "failed", "failureReason": "baseline_parse_result_missing"}
    repo.mark_ocr_pipeline_stage(run, "structure_scan", "running")
    persist_ocr_pipeline_progress(run)
    try:
        saved_result = repo.find_one(
            "ocr_parse_results",
            str(run.get("structureParseResultId") or ""),
            id_field="parseResultId",
        )
        if saved_result:
            status = _complete_saved_heavy_stage(
                run,
                stage="structure_scan",
                parse_result=saved_result,
                expected_engines=STRUCTURE_ENGINES,
            )
            next_dispatch = _next_after_structure(run, profile)
            persist_ocr_pipeline_progress(run)
            return {"pipelineRunId": run_id, "status": status, "resumedFromSavedResult": True, "nextDispatch": next_dispatch}
        result, _summary, _status, _blockers = _run_pipeline_heavy_stage(
            run,
            baseline,
            profile,
            stage="structure_scan",
            expected_engines=STRUCTURE_ENGINES,
        )
        record = _persist_pipeline_stage_result(run, "structure_scan", result)
        status = _complete_saved_heavy_stage(
            run,
            stage="structure_scan",
            parse_result=record,
            expected_engines=STRUCTURE_ENGINES,
        )
        next_dispatch = _next_after_structure(run, profile)
        persist_ocr_pipeline_progress(run)
        return {"pipelineRunId": run_id, "status": status, "nextDispatch": next_dispatch}
    except Exception as exc:
        retry_index = int(getattr(self.request, "retries", 0) or 0)
        if retry_index < 3:
            countdown = (10, 30, 90)[retry_index]
            repo.mark_ocr_pipeline_stage(run, "structure_scan", "retrying", failure_reason=exc.__class__.__name__)
            _persist_retry_state(run)
            raise self.retry(exc=exc, countdown=countdown)
        blockers = [{"code": "PP_STRUCTURE_EXECUTION_FAILED"}]
        repo.mark_ocr_pipeline_stage(run, "structure_scan", "partial", blocking_reasons=blockers, failure_reason=exc.__class__.__name__)
        _append_local_stage_blockers(run, blockers)
        persist_ocr_pipeline_progress(run)
        next_dispatch = _next_after_structure(run, profile) if run.get("mode") != "active" else None
        persist_ocr_pipeline_progress(run)
        return {"pipelineRunId": run_id, "status": "partial", "nextDispatch": next_dispatch}


@celery_app.task(bind=True, max_retries=3)
@pipeline_task_lock("ocr-seal", lambda _self, run_id: str(run_id))
def ocr_pipeline_seal_scan(self, run_id: str) -> dict[str, Any]:
    run, baseline, profile = _pipeline_stage_context(run_id)
    if not run:
        return {"pipelineRunId": run_id, "status": "missing"}
    existing = _stage_record(run, "seal_signature_scan")
    if run.get("sealParseResultId") and (existing or {}).get("status") in {"success", "partial"}:
        return {"pipelineRunId": run_id, "status": (existing or {}).get("status"), "nextDispatch": _next_after_seal(run)}
    if not baseline:
        return {"pipelineRunId": run_id, "status": "failed", "failureReason": "baseline_parse_result_missing"}
    repo.mark_ocr_pipeline_stage(run, "seal_signature_scan", "running")
    persist_ocr_pipeline_progress(run)
    try:
        saved_result = repo.find_one(
            "ocr_parse_results",
            str(run.get("sealParseResultId") or ""),
            id_field="parseResultId",
        )
        if saved_result:
            status = _complete_saved_heavy_stage(
                run,
                stage="seal_signature_scan",
                parse_result=saved_result,
                expected_engines=SEAL_ENGINES,
            )
            next_dispatch = _next_after_seal(run)
            persist_ocr_pipeline_progress(run)
            return {"pipelineRunId": run_id, "status": status, "resumedFromSavedResult": True, "nextDispatch": next_dispatch}
        result, _summary, _status, _blockers = _run_pipeline_heavy_stage(
            run,
            baseline,
            profile,
            stage="seal_signature_scan",
            expected_engines=SEAL_ENGINES,
        )
        record = _persist_pipeline_stage_result(run, "seal_signature_scan", result)
        status = _complete_saved_heavy_stage(
            run,
            stage="seal_signature_scan",
            parse_result=record,
            expected_engines=SEAL_ENGINES,
        )
        next_dispatch = _next_after_seal(run)
        persist_ocr_pipeline_progress(run)
        return {"pipelineRunId": run_id, "status": status, "nextDispatch": next_dispatch}
    except Exception as exc:
        retry_index = int(getattr(self.request, "retries", 0) or 0)
        if retry_index < 3:
            countdown = (10, 30, 90)[retry_index]
            repo.mark_ocr_pipeline_stage(run, "seal_signature_scan", "retrying", failure_reason=exc.__class__.__name__)
            _persist_retry_state(run)
            raise self.retry(exc=exc, countdown=countdown)
        blockers = [{"code": "SEAL_ENGINE_EXECUTION_FAILED"}]
        repo.mark_ocr_pipeline_stage(run, "seal_signature_scan", "partial", blocking_reasons=blockers, failure_reason=exc.__class__.__name__)
        _append_local_stage_blockers(run, blockers)
        persist_ocr_pipeline_progress(run)
        next_dispatch = _next_after_seal(run) if run.get("mode") != "active" else None
        persist_ocr_pipeline_progress(run)
        return {"pipelineRunId": run_id, "status": "partial", "nextDispatch": next_dispatch}


@celery_app.task(bind=True, max_retries=2)
@pipeline_task_lock("ocr-fusion", lambda _self, run_id: str(run_id))
def ocr_pipeline_evidence_fusion(self, run_id: str) -> dict[str, Any]:
    run, baseline, profile = _pipeline_stage_context(run_id)
    if not run:
        return {"pipelineRunId": run_id, "status": "missing"}
    existing = _stage_record(run, "evidence_fusion")
    if run.get("fusedParseResultId") and (existing or {}).get("status") == "success":
        dispatch = _dispatch_pipeline_stage_once(run, "qwenDispatch", task_dispatcher.dispatch_ocr_pipeline_qwen)
        return {"pipelineRunId": run_id, "status": "success", "nextDispatch": dispatch}
    if not baseline:
        return {"pipelineRunId": run_id, "status": "failed", "failureReason": "baseline_parse_result_missing"}
    repo.mark_ocr_pipeline_stage(run, "evidence_fusion", "running")
    persist_ocr_pipeline_progress(run)
    try:
        structure_result = repo.find_one(
            "ocr_parse_results",
            str(run.get("structureParseResultId") or ""),
            id_field="parseResultId",
        )
        seal_result = repo.find_one(
            "ocr_parse_results",
            str(run.get("sealParseResultId") or ""),
            id_field="parseResultId",
        )
        fused = fuse_stage_parse_results(baseline, structure_result, seal_result)
        record = _persist_pipeline_stage_result(run, "evidence_fusion", fused)
        run["fusedParseResultId"] = record.get("parseResultId") or record.get("id")
        artifact_url, artifact_hash = store_ocr_pipeline_artifact(run, "evidence_fusion", record)
        repo.mark_ocr_pipeline_stage(
            run,
            "evidence_fusion",
            "success",
            engine_status=pipeline_engine_status(fused),
            artifact_url=artifact_url,
            artifact_hash=artifact_hash,
        )
        repo.mark_ocr_pipeline_stage(run, "qwen_extract", "queued")
        persist_ocr_pipeline_progress(run)
        dispatch = _dispatch_pipeline_stage_once(run, "qwenDispatch", task_dispatcher.dispatch_ocr_pipeline_qwen)
        if not dispatch.get("taskId"):
            raise RuntimeError("qwen_dispatch_failed")
        persist_ocr_pipeline_progress(run)
        return {"pipelineRunId": run_id, "status": "success", "nextDispatch": dispatch}
    except Exception as exc:
        retry_index = int(getattr(self.request, "retries", 0) or 0)
        if retry_index < 2:
            countdown = (5, 15)[retry_index]
            repo.mark_ocr_pipeline_stage(run, "evidence_fusion", "retrying", failure_reason=exc.__class__.__name__)
            _persist_retry_state(run)
            raise self.retry(exc=exc, countdown=countdown)
        repo.mark_ocr_pipeline_stage(
            run,
            "evidence_fusion",
            "failed",
            blocking_reasons=[{"code": "EVIDENCE_FUSION_FAILED"}],
            failure_reason=exc.__class__.__name__,
        )
        repo.finish_ocr_pipeline_run(
            run,
            status="failed" if run.get("mode") == "active" else "partial",
            blocking_reasons=[{"code": "EVIDENCE_FUSION_FAILED"}],
            recommended_action="从最后成功的 OCR 阶段恢复融合。",
        )
        persist_ocr_pipeline_progress(run)
        return {"pipelineRunId": run_id, "status": run.get("status"), "failureReason": exc.__class__.__name__}


def _load_official_page_checkpoints(run: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    output: dict[int, list[dict[str, Any]]] = {}
    for raw_page_no, checkpoint in (run.get("officialPageCheckpoints") or {}).items():
        if not isinstance(checkpoint, dict):
            continue
        parsed = parse_storage_url(str(checkpoint.get("artifactUrl") or ""))
        if not parsed:
            continue
        downloaded = None
        try:
            downloaded = object_storage.download_to_temp(parsed[0], parsed[1], suffix=".json")
            if not downloaded:
                continue
            payload = json.loads(downloaded.read_text(encoding="utf-8"))
            calls = payload.get("calls") if isinstance(payload, dict) else None
            if isinstance(calls, list):
                output[int(raw_page_no)] = [item for item in calls if isinstance(item, dict)]
        except (OSError, ValueError, TypeError):
            continue
        finally:
            if downloaded:
                shutil.rmtree(downloaded.parent, ignore_errors=True)
    return output


_MODEL_CALL_LEDGER_LOCK = threading.Lock()


def _persist_official_ocr_attempt(run: dict[str, Any], raw: dict[str, Any]) -> str:
    with _MODEL_CALL_LEDGER_LOCK:
        existing_ledger_id = str(raw.get("modelCallLedgerId") or "")
        if existing_ledger_id:
            return existing_ledger_id
        now = server_time()
        attempt_number = 1 + len(
            [
                item
                for item in repo.state.get("model_call_attempts", [])
                if item.get("pipelineRunId") == run.get("id")
                and item.get("callKind") == raw.get("task")
                and item.get("pageNo") == raw.get("pageNo")
            ]
        )
        attempt = {
            "id": f"MCALL-{uuid4().hex[:12].upper()}",
            "pipelineRunId": run.get("id"),
            "documentId": run.get("documentId"),
            "documentVersionId": run.get("documentVersionId"),
            "stage": "official_ocr",
            "callKind": raw.get("task"),
            "provider": raw.get("provider"),
            "model": raw.get("model"),
            "providerRequestId": raw.get("requestId") or raw.get("providerRequestId"),
            "status": raw.get("status") or "success",
            "attempt": attempt_number,
            "pageNo": raw.get("pageNo"),
            "elapsedMs": int(raw.get("durationMs") or 0),
            "usage": deepcopy(raw.get("usage") or {}),
            "usageNormalized": normalize_model_usage(raw.get("usage") or {}),
            "costNormalized": {
                "currency": "CNY",
                "input": 0.0,
                "output": 0.0,
                "cacheWrite": 0.0,
                "cacheRead": 0.0,
                "ocrApi": float(raw.get("costCny") or 0.0),
                "total": float(raw.get("costCny") or 0.0),
                "priceVersion": "dashscope-qwen-ocr-2026-07",
            },
            "estimatedCostCny": float(raw.get("costCny") or 0.0),
            "input": deepcopy(raw.get("input") or {}),
            "failureReason": raw.get("failureReason"),
            "finishReason": raw.get("finishReason"),
            "outputTruncated": bool(raw.get("outputTruncated")),
            "maxOutputTokens": raw.get("maxOutputTokens"),
            "callId": raw.get("callId"),
            "createdAt": now,
            "startedAt": now,
            "finishedAt": now,
            "updatedAt": now,
            "priceVersion": "dashscope-qwen-ocr-2026-07",
        }
        repo.state.setdefault("model_call_attempts", []).insert(0, attempt)
        run.setdefault("modelCallAttemptIds", []).append(attempt["id"])
    _persist_model_call_attempt(attempt)
    return attempt["id"]


def _persist_official_ocr_attempts(run: dict[str, Any], result: dict[str, Any]) -> None:
    for raw in result.get("modelCallAttempts") or []:
        if not isinstance(raw, dict) or raw.get("modelCallLedgerId"):
            continue
        _persist_official_ocr_attempt(run, raw)


def _dispatch_after_official_ocr(
    run: dict[str, Any],
    result: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    run["groundedFields"] = deepcopy(result.get("fields") or [])
    run["groundingValidation"] = deepcopy(result.get("groundingValidation") or {})
    complete = profile_result_complete(result, profile)
    if complete:
        repo.mark_ocr_pipeline_stage(
            run,
            "qwen_extract",
            "skipped",
            engine_status={"skipReasons": ["official_ocr_complete_and_grounded"]},
        )
        repo.mark_ocr_pipeline_stage(run, "grounding_validate", "queued")
        dispatch = _dispatch_pipeline_stage_once(
            run,
            "finalizeDispatch",
            task_dispatcher.dispatch_ocr_pipeline_finalize,
        )
    else:
        run["qwenRescueOnly"] = True
        repo.mark_ocr_pipeline_stage(run, "qwen_extract", "queued")
        dispatch = _dispatch_pipeline_stage_once(
            run,
            "qwenDispatch",
            task_dispatcher.dispatch_ocr_pipeline_qwen,
        )
    if not dispatch.get("taskId"):
        raise RuntimeError(str(dispatch.get("statusReason") or "official_ocr_next_dispatch_failed"))
    return dispatch


@celery_app.task(bind=True, max_retries=3)
@pipeline_task_lock("ocr-official", lambda _self, run_id: str(run_id))
def ocr_pipeline_official_extract(self, run_id: str) -> dict[str, Any]:
    refresh_worker_state(
        {
            "projects",
            "documents",
            "versions",
            "knowledge_files",
            "knowledge_tasks",
            "ocr_jobs",
            "ocr_parse_results",
            "ocr_pipeline_runs",
            "ocr_stage_runs",
            "model_call_attempts",
            "extracted_fields",
            "evidence_links",
            "node_evidence_links",
        }
    )
    run = repo.find_one("ocr_pipeline_runs", run_id)
    if not run:
        return {"pipelineRunId": run_id, "status": "missing"}
    profile = default_profile(run.get("profileId"), run.get("documentType"))
    existing = repo.find_one(
        "ocr_parse_results",
        str(run.get("officialParseResultId") or ""),
        id_field="parseResultId",
    )
    text_stage = _stage_record(run, "text_scan")
    if existing and (text_stage or {}).get("status") in {"success", "partial"}:
        dispatch = _dispatch_after_official_ocr(run, existing, profile)
        persist_ocr_pipeline_progress(run)
        return {
            "pipelineRunId": run_id,
            "status": (text_stage or {}).get("status"),
            "resumedFromSavedResult": True,
            "nextDispatch": dispatch,
        }

    runtime = ocr_runtime_config(validate=True)
    repo.mark_ocr_pipeline_stage(run, "text_scan", "running")
    run.update(
        {
            "taskId": str(getattr(self.request, "id", "") or run.get("taskId") or "") or None,
            "providerMode": runtime["mode"],
            "provider": runtime["official"]["provider"],
            "model": runtime["official"]["primaryModel"],
            "updatedAt": server_time(),
            "lastHeartbeatAt": server_time(),
            "providerWaitReason": None,
            "deadLetteredAt": None,
        }
    )
    job = repo.find_one(
        "ocr_jobs",
        str(run.get("officialOcrJobRecordId") or run.get("ocrJobRecordId") or ""),
    )
    repo.mark_ocr_job_running(job, pipeline_run_id=run_id)
    task = (
        repo.ocr_task_for(
            str(run.get("documentId") or ""),
            str(run.get("documentVersionId") or ""),
            run.get("fileName"),
        )
        if run.get("mode") == "active"
        else None
    )
    if task:
        task["progress"] = max(int(task.get("progress") or 0), 25)
        task["updatedAt"] = server_time()
        repo.append_task_log(task, "info", "Official OCR started.")
    persist_ocr_pipeline_progress(run, task=task, ocr_job=job)
    source_temp: Path | None = None
    work_directory = temporary_pipeline_directory(f"{run_id}-official")
    try:
        source_path, source_temp = document_ai_source_path(run)
        if not source_path or not source_path.is_file():
            raise RuntimeError("official_ocr_source_missing")
        cached_pages = _load_official_page_checkpoints(run)

        def page_completed(
            page_no: int,
            completed: int,
            total: int,
            calls: list[dict[str, Any]],
        ) -> None:
            artifact_url, artifact_hash = store_ocr_pipeline_artifact(
                run,
                f"official_page_{page_no}",
                {
                    "schemaVersion": "OfficialOcrPageCheckpoint@1",
                    "pipelineRunId": run_id,
                    "pageNo": page_no,
                    "calls": calls,
                },
            )
            run.setdefault("officialPageCheckpoints", {})[str(page_no)] = {
                "artifactUrl": artifact_url,
                "artifactHash": artifact_hash,
            }
            run["pageProgress"] = {
                "completed": completed,
                "total": total,
                "currentPage": page_no,
                "status": "running",
            }
            run["lastHeartbeatAt"] = server_time()
            if task:
                task["progress"] = max(
                    int(task.get("progress") or 0),
                    min(60, 25 + int(35 * completed / max(total, 1))),
                )
                task["updatedAt"] = server_time()
            persist_ocr_pipeline_progress(run, task=task, ocr_job=job)

        result = official_ocr_extract(
            source_path,
            profile=profile,
            runtime=runtime,
            work_directory=work_directory,
            page_call_cache=cached_pages,
            page_completed=page_completed,
            attempt_recorder=lambda raw: _persist_official_ocr_attempt(run, raw),
            budget_key=run_id,
        )
        run["pageProgress"] = {
            "completed": len(result.get("pages") or []),
            "total": len(result.get("pages") or []),
            "currentPage": None,
            "status": "completed",
        }
        if str(result.get("status") or "").lower() != "success":
            raise RuntimeError("official_ocr_returned_failed_result")
        result["storageKey"] = run.get("storageKey")
        result["fileName"] = run.get("fileName")
        _persist_official_ocr_attempts(run, result)
        record = repo.finish_ocr_job_record(job, result) or result
        parse_result_id = record.get("parseResultId") or record.get("id")
        run["officialParseResultId"] = parse_result_id
        if not run.get("baselineParseResultId"):
            run["baselineParseResultId"] = parse_result_id
        run["fusedParseResultId"] = parse_result_id
        run["parseResultId"] = parse_result_id
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        run.update(
            {
                "providerMode": metadata.get("providerMode") or runtime["mode"],
                "provider": metadata.get("provider") or runtime["official"]["provider"],
                "model": metadata.get("model") or runtime["official"]["primaryModel"],
                "cloudGrounded": bool(metadata.get("cloudGrounded")),
                "providerRequestIds": deepcopy(metadata.get("providerRequestIds") or []),
                "costCny": float(metadata.get("costCny") or result.get("costCny") or 0.0),
                "modelCallCount": int(metadata.get("modelCallCount") or 0),
                "formalReadinessProfileAllowed": bool(metadata.get("formalReadinessProfileAllowed")),
                "lastHeartbeatAt": server_time(),
            }
        )
        artifact_url, artifact_hash = store_ocr_pipeline_artifact(run, "official_ocr", record)
        text_status = "success" if result.get("fragments") or result.get("fields") else "partial"
        repo.mark_ocr_pipeline_stage(
            run,
            "text_scan",
            text_status,
            engine_status=pipeline_engine_status(result),
            blocking_reasons=[] if text_status == "success" else [{"code": "OCR_TEXT_EMPTY"}],
            artifact_url=artifact_url,
            artifact_hash=artifact_hash,
        )
        required_tables = bool(profile.get("requiredTables"))
        table_executed = any(
            "table_parsing" in (item.get("tasks") or [])
            for item in result.get("engineRuns") or []
            if isinstance(item, dict)
        )
        if required_tables:
            repo.mark_ocr_pipeline_stage(
                run,
                "structure_scan",
                "success" if table_executed and result.get("tables") else "partial",
                engine_status=pipeline_engine_status(result),
                blocking_reasons=(
                    []
                    if table_executed and result.get("tables")
                    else [{"code": "TABLE_EVIDENCE_MISSING"}]
                ),
            )
        seal_required = bool((profile.get("sealRules") or {}).get("required"))
        if seal_required:
            repo.mark_ocr_pipeline_stage(
                run,
                "seal_signature_scan",
                "success" if result.get("seals") else "partial",
                engine_status=pipeline_engine_status(result),
                blocking_reasons=[] if result.get("seals") else [{"code": "SEAL_EVIDENCE_MISSING"}],
            )
        repo.mark_ocr_pipeline_stage(
            run,
            "evidence_fusion",
            "success",
            engine_status=pipeline_engine_status(result),
            artifact_url=artifact_url,
            artifact_hash=artifact_hash,
        )
        dispatch = _dispatch_after_official_ocr(run, result, profile)
        if task:
            task["progress"] = max(int(task.get("progress") or 0), 65)
            task["updatedAt"] = server_time()
            repo.append_task_log(task, "info", "Official OCR completed; grounding validation queued.")
        persist_ocr_pipeline_progress(run, task=task, ocr_job=job)
        return {
            "pipelineRunId": run_id,
            "status": text_status,
            "provider": run.get("provider"),
            "model": run.get("model"),
            "costCny": run.get("costCny"),
            "nextDispatch": dispatch,
        }
    except Exception as exc:
        retry_index = int(getattr(self.request, "retries", 0) or 0)
        max_attempts = max(1, int(runtime["official"].get("maxAttempts") or 3))
        retryable = isinstance(exc, AliyunOcrRetryableError) or not isinstance(exc, AliyunOcrError)
        if retryable and retry_index + 1 < max_attempts:
            retry_delays = (10, 30, 90)
            default_countdown = retry_delays[min(retry_index, len(retry_delays) - 1)]
            countdown = max(1, int(getattr(exc, "retry_after", 0) or default_countdown))
            repo.mark_ocr_pipeline_stage(run, "text_scan", "retrying", failure_reason=exc.__class__.__name__)
            run["providerWaitReason"] = str(getattr(exc, "reason", None) or exc.__class__.__name__)
            run["retryFromPage"] = (run.get("pageProgress") or {}).get("currentPage")
            run["recommendedAction"] = f"Official OCR will retry in {countdown} seconds."
            _persist_retry_state(run)
            raise self.retry(exc=exc, countdown=countdown)
        blockers = [{"code": "OFFICIAL_OCR_FAILED"}]
        run["deadLetteredAt"] = server_time()
        run["deadLetterReason"] = str(getattr(exc, "reason", None) or exc.__class__.__name__)
        repo.mark_ocr_pipeline_stage(
            run,
            "text_scan",
            "failed",
            blocking_reasons=blockers,
            failure_reason=exc.__class__.__name__,
        )
        repo.finish_ocr_pipeline_run(
            run,
            status="failed",
            blocking_reasons=blockers,
            recommended_action="Check official OCR quota, network, or circuit status and retry.",
            formal_evidence_ready=False,
        )
        if job and not run.get("baselineParseResultId"):
            failure_result = {
                "storageKey": run.get("storageKey"),
                "fileName": run.get("fileName"),
                "status": "failed",
                "fragments": [],
                "fields": [],
                "tables": [],
                "seals": [],
                "quality": {
                    "status": "failed",
                    "reasons": ["OFFICIAL_OCR_FAILED"],
                    "blockingReasons": blockers,
                },
                "diagnostics": [{"code": exc.__class__.__name__.upper()}],
            }
            repo.finish_ocr_job_record(job, failure_result)
        if task:
            repo.mark_task_failed(task, "Official OCR failed.")
        persist_ocr_pipeline_progress(run, task=task, ocr_job=job)
        return {
            "pipelineRunId": run_id,
            "status": "failed",
            "failureReason": exc.__class__.__name__,
            "blockingReasons": blockers,
        }
    finally:
        shutil.rmtree(work_directory, ignore_errors=True)
        if source_temp:
            shutil.rmtree(source_temp, ignore_errors=True)


def _qwen_cost_estimate_cny(usage: dict[str, Any]) -> float:
    return float(model_cost_cny(usage)["total"])


def _persist_model_call_attempt(attempt: dict[str, Any]) -> None:
    flush_state_records({"model_call_attempts": [attempt]})


def qwen_structured_pipeline_call(
    run: dict[str, Any],
    messages: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    call_kind: str,
    context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = server_time()
    attempt = {
        "id": f"MCALL-{uuid4().hex[:12].upper()}",
        "pipelineRunId": run.get("id"),
        "documentId": run.get("documentId"),
        "documentVersionId": run.get("documentVersionId"),
        "stage": "qwen_extract",
        "callKind": call_kind,
        "provider": "Model Studio / DashScope",
        "modelAlias": "qwen-vision-review",
        "status": "running",
        "attempt": 1 + len(
            [
                item
                for item in repo.state.get("model_call_attempts", [])
                if item.get("pipelineRunId") == run.get("id") and item.get("callKind") == call_kind
            ]
        ),
        "context": deepcopy(context),
        "createdAt": now,
        "startedAt": now,
        "updatedAt": now,
        "usage": {},
        "estimatedCostCny": 0.0,
        "priceVersion": "dashscope-cn-beijing-qwen3.7-plus-2026-07",
    }
    repo.state.setdefault("model_call_attempts", []).insert(0, attempt)
    run.setdefault("modelCallAttemptIds", []).append(attempt["id"])
    _persist_model_call_attempt(attempt)
    started = time.monotonic()
    try:
        response = QwenRuntimeClient().chat_sync(
            messages,
            model="qwen-vision-review",
            stream=False,
            response_format={"type": "json_object"},
            enable_thinking=False,
            temperature=0.0,
            max_tokens=int(os.getenv("AICHECK_OCR_QWEN_MAX_TOKENS", "8192")),
            timeout=float(os.getenv("AICHECK_OCR_QWEN_TIMEOUT_SECONDS", "180")),
            _raw_capture_context=raw_context_from_record(
                {**run, "pipelineRunId": run.get("id")},
                model_call_attempt_id=str(attempt["id"]),
                stage=str(attempt["stage"]),
                turn=1,
            ),
        )
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        normalized_usage = normalize_model_usage(usage)
        normalized_cost = model_cost_cny(usage)
        attempt.update(
            {
                "status": "response_received",
                "provider": response.get("provider") or attempt["provider"],
                "model": response.get("model"),
                "providerRequestId": response.get("id"),
                "usage": deepcopy(usage),
                "usageNormalized": normalized_usage,
                "costNormalized": normalized_cost,
                "estimatedCostCny": normalized_cost["total"],
                "elapsedMs": round((time.monotonic() - started) * 1000),
                "updatedAt": server_time(),
            }
        )
        _persist_model_call_attempt(attempt)
        try:
            parsed = normalize_qwen_structured_output(parse_qwen_json(response), profile)
        except Exception as exc:
            attempt.update(
                {
                    "status": "invalid_output",
                    "failureReason": exc.__class__.__name__,
                    "finishedAt": server_time(),
                    "updatedAt": server_time(),
                }
            )
            _persist_model_call_attempt(attempt)
            raise
        attempt.update(
            {
                "status": "success",
                "finishedAt": server_time(),
                "updatedAt": server_time(),
            }
        )
        _persist_model_call_attempt(attempt)
        return response, parsed
    except Exception as exc:
        if attempt.get("status") not in {"invalid_output", "success"}:
            attempt.update(
                {
                    "status": "failed",
                    "failureReason": exc.__class__.__name__,
                    "elapsedMs": round((time.monotonic() - started) * 1000),
                    "finishedAt": server_time(),
                    "updatedAt": server_time(),
                }
            )
            _persist_model_call_attempt(attempt)
        raise


@celery_app.task(bind=True, max_retries=3)
@pipeline_task_lock("ocr-qwen", lambda _self, run_id: str(run_id))
def ocr_pipeline_qwen_extract(self, run_id: str) -> dict[str, Any]:
    refresh_worker_state(
        {
            "documents",
            "versions",
            "knowledge_files",
            "knowledge_tasks",
            "ocr_jobs",
            "ocr_parse_results",
            "ocr_pipeline_runs",
            "ocr_stage_runs",
            "model_call_attempts",
        }
    )
    run = repo.find_one("ocr_pipeline_runs", run_id)
    if not run:
        return {"pipelineRunId": run_id, "status": "missing"}
    if run.get("status") in {"completed", "partial"} and run.get("qwenStructuredOutput"):
        return {"pipelineRunId": run_id, "status": run.get("status"), "alreadyCompleted": True}
    qwen_stage = _stage_record(run, "qwen_extract")
    if run.get("qwenStructuredOutput") and (qwen_stage or {}).get("status") == "success":
        dispatch = task_dispatcher.dispatch_ocr_pipeline_finalize(run_id)
        run["finalizeDispatch"] = dispatch
        persist_ocr_pipeline_progress(run)
        return {
            "pipelineRunId": run_id,
            "status": "success",
            "alreadyExtracted": True,
            "finalizeDispatch": dispatch,
        }
    parse_result = repo.find_one(
        "ocr_parse_results",
        str(run.get("fusedParseResultId") or run.get("baselineParseResultId") or ""),
        id_field="parseResultId",
    )
    if not parse_result:
        repo.mark_ocr_pipeline_stage(
            run,
            "qwen_extract",
            "failed",
            failure_reason="baseline_parse_result_missing",
        )
        repo.finish_ocr_pipeline_run(
            run,
            status="failed",
            blocking_reasons=[{"code": "BASELINE_PARSE_RESULT_MISSING"}],
            recommended_action="重新执行本地 OCR 扫描。",
        )
        persist_ocr_pipeline_progress(run)
        return {"pipelineRunId": run_id, "status": "failed", "failureReason": "baseline_parse_result_missing"}
    profile = default_profile(run.get("profileId"), run.get("documentType"))
    repo.mark_ocr_pipeline_stage(run, "qwen_extract", "running")
    run["taskId"] = str(getattr(self.request, "id", "") or run.get("taskId") or "") or None
    persist_ocr_pipeline_progress(run)
    source_temp: Path | None = None
    work_directory = temporary_pipeline_directory(run_id)
    try:
        source_path, source_temp = document_ai_source_path(run)
        if not source_path or not source_path.is_file():
            raise RuntimeError("ocr_pipeline_source_missing")
        batch_outputs: list[dict[str, Any]] = []
        batch_validations: list[dict[str, Any]] = []
        all_candidates: dict[str, dict[str, Any]] = {}
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        finish_reasons: list[str] = []
        qwen_model = None
        qwen_provider = None
        selected_batches = page_batches(parse_result)
        if run.get("qwenRescueOnly"):
            evidence_pages = sorted(
                {
                    int(item.get("pageNo") or 1)
                    for collection in ("fields", "tables", "seals")
                    for item in parse_result.get(collection) or []
                    if isinstance(item, dict)
                }
            )
            selected_batches = [(evidence_pages or page_numbers(parse_result))[:4]]
        for batch_index, selected_pages in enumerate(selected_batches, start=1):
            batch_directory = work_directory / f"batch-{batch_index:03d}"
            rendered = render_pages(source_path, selected_pages, batch_directory / "pages")
            if not rendered:
                continue
            priors = build_batch_priors(parse_result, profile, selected_pages)
            for window_index, prior in enumerate(priors, start=1):
                compact_prior = prior["compact"]
                for candidate in compact_prior.get("candidates") or []:
                    if isinstance(candidate, dict) and candidate.get("candidateId"):
                        all_candidates[str(candidate["candidateId"])] = candidate
                rois = render_candidate_rois(
                    rendered,
                    parse_result,
                    compact_prior,
                    batch_directory / f"rois-{window_index:02d}",
                    limit=6 if run.get("qwenRescueOnly") else 12,
                )
                response, parsed_output = qwen_structured_pipeline_call(
                    run,
                    qwen_messages(rendered, rois, profile, compact_prior),
                    profile,
                    call_kind="primary",
                    context={
                        "batch": batch_index,
                        "window": window_index,
                        "selectedPageNos": selected_pages,
                        "priorHash": prior["compactPriorHash"],
                    },
                )
                qwen_model = response.get("model") or qwen_model
                qwen_provider = response.get("provider") or qwen_provider
                choices = response.get("choices") if isinstance(response.get("choices"), list) else []
                finish_reason = str((choices[0] or {}).get("finish_reason") or "unknown") if choices else "unknown"
                finish_reasons.append(finish_reason)
                if finish_reason == "length":
                    raise RuntimeError("qwen_output_truncated")
                response_usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
                for key in usage:
                    usage[key] += int(response_usage.get(key) or 0)
                attribution = validate_batch_output(parsed_output, compact_prior)
                batch_outputs.append(attribution["structuredOutput"])
                batch_validations.append(
                    {
                        "batch": batch_index,
                        "window": window_index,
                        "selectedPageNos": selected_pages,
                        "tableWindow": compact_prior.get("tableWindow"),
                        "priorHash": prior["compactPriorHash"],
                        "validation": attribution["validation"],
                    }
                )
        if not batch_outputs:
            raise RuntimeError("qwen_pipeline_no_batches")
        structured_output = merge_batch_outputs(batch_outputs)
        required_fields = {
            str(value)
            for value in profile.get("requiredFields") or []
            if str(value) and str(value) != "seal"
        }
        extracted_fields = {
            str(key)
            for key, item in (structured_output.get("fields") or {}).items()
            if isinstance(item, dict) and item.get("value") is not None and item.get("value") != ""
        }
        unresolved_fields = sorted(required_fields - extracted_fields)
        conflicts = structured_output.get("conflicts") if isinstance(structured_output.get("conflicts"), list) else []
        if (unresolved_fields or conflicts) and not run.get("qwenRescueOnly"):
            issue_fields = set(unresolved_fields) | {
                str(item.get("fieldCode")) for item in conflicts if isinstance(item, dict) and item.get("fieldCode")
            }
            rescue_pages = sorted(
                {
                    int(candidate.get("pageNo") or 1)
                    for candidate in all_candidates.values()
                    if str(candidate.get("semanticKey") or "") in issue_fields
                }
            )[:4]
            if not rescue_pages:
                rescue_pages = page_numbers(parse_result)[:4]
            rescue_directory = work_directory / "rescue"
            rescue_rendered = render_pages(source_path, rescue_pages, rescue_directory / "pages")
            rescue_prior = build_batch_prior(parse_result, profile, rescue_pages)
            rescue_compact = rescue_prior["compact"]
            for candidate in rescue_compact.get("candidates") or []:
                if isinstance(candidate, dict) and candidate.get("candidateId"):
                    all_candidates[str(candidate["candidateId"])] = candidate
            rescue_rois = render_candidate_rois(
                rescue_rendered,
                parse_result,
                rescue_compact,
                rescue_directory / "rois",
                limit=16,
            )
            rescue_messages = qwen_messages(rescue_rendered, rescue_rois, profile, rescue_compact)
            rescue_messages[-1]["content"].append(
                {
                    "type": "text",
                    "text": (
                        "这是仅针对缺失字段或冲突值的第二轮裁决。优先处理字段："
                        + ", ".join(sorted(issue_fields))
                        + "。只能从候选 ID 中选择；仍无法确认时保持 null。"
                    ),
                }
            )
            rescue_response, rescue_output = qwen_structured_pipeline_call(
                run,
                rescue_messages,
                profile,
                call_kind="rescue",
                context={
                    "selectedPageNos": rescue_pages,
                    "priorHash": rescue_prior["compactPriorHash"],
                    "issueFields": sorted(issue_fields),
                },
            )
            rescue_usage = rescue_response.get("usage") if isinstance(rescue_response.get("usage"), dict) else {}
            rescue_choices = rescue_response.get("choices") if isinstance(rescue_response.get("choices"), list) else []
            rescue_finish_reason = (
                str((rescue_choices[0] or {}).get("finish_reason") or "unknown") if rescue_choices else "unknown"
            )
            finish_reasons.append(rescue_finish_reason)
            if rescue_finish_reason == "length":
                raise RuntimeError("qwen_rescue_output_truncated")
            for key in usage:
                usage[key] += int(rescue_usage.get(key) or 0)
            rescue_attribution = validate_batch_output(
                rescue_output,
                rescue_compact,
            )
            batch_outputs.insert(0, rescue_attribution["structuredOutput"])
            batch_validations.append(
                {
                    "batch": "rescue",
                    "selectedPageNos": rescue_pages,
                    "priorHash": rescue_prior["compactPriorHash"],
                    "validation": rescue_attribution["validation"],
                    "issueFields": sorted(issue_fields),
                }
            )
            structured_output = merge_batch_outputs(batch_outputs)
        grounded_fields = validated_ocr_fields(structured_output, profile, all_candidates)
        validation_summary = {
            "batchCount": len(batch_validations),
            "batches": batch_validations,
            "validatedFieldCount": len(grounded_fields),
            "invalidCandidateIdCount": sum(
                int(((item.get("validation") or {}).get("invalidCandidateIdCount") or 0))
                for item in batch_validations
            ),
            "unsupportedAttributionCount": sum(
                int((((item.get("validation") or {}).get("statusCounts") or {}).get("unsupported") or 0))
                for item in batch_validations
            ),
            "droppedUnsupportedAttributionCount": sum(
                int(((item.get("validation") or {}).get("droppedUnsupportedAttributionCount") or 0))
                for item in batch_validations
            ),
            "candidateRepairCount": sum(
                int(((item.get("validation") or {}).get("candidateRepairCount") or 0))
                for item in batch_validations
            ),
        }
        artifact_payload = {
            "schemaVersion": "OcrQwenGroundedOutput@1",
            "pipelineRunId": run_id,
            "model": qwen_model,
            "provider": qwen_provider,
            "structuredOutput": structured_output,
            "groundedFields": grounded_fields,
            "groundingValidation": validation_summary,
            "finishReasons": finish_reasons,
        }
        artifact_url, artifact_hash = store_ocr_pipeline_artifact(run, "qwen_extract", artifact_payload)
        run.update(
            {
                "qwenModel": qwen_model,
                "qwenProvider": qwen_provider,
                "qwenUsage": usage,
                "qwenBatchCount": len(batch_validations),
                "qwenStructuredOutput": structured_output,
                "groundedFields": grounded_fields,
                "groundingValidation": validation_summary,
                "qwenFinishReasons": finish_reasons,
                "updatedAt": server_time(),
            }
        )
        repo.mark_ocr_pipeline_stage(
            run,
            "qwen_extract",
            "success",
            engine_status={"qwen3.7-plus": {"status": "success", "batchCount": len(batch_validations)}},
            artifact_url=artifact_url,
            artifact_hash=artifact_hash,
        )
        persist_ocr_pipeline_progress(run)
        dispatch = task_dispatcher.dispatch_ocr_pipeline_finalize(run_id)
        run["finalizeDispatch"] = dispatch
        if not dispatch.get("taskId"):
            raise RuntimeError("ocr_pipeline_finalize_dispatch_failed")
        persist_ocr_pipeline_progress(run)
        return {
            "pipelineRunId": run_id,
            "status": "success",
            "batchCount": len(batch_validations),
            "validatedFieldCount": len(grounded_fields),
            "finalizeDispatch": dispatch,
        }
    except Exception as exc:
        retry_index = int(getattr(self.request, "retries", 0) or 0)
        if retry_index < 3:
            countdown = (10, 30, 90)[retry_index]
            repo.mark_ocr_pipeline_stage(run, "qwen_extract", "retrying", failure_reason=exc.__class__.__name__)
            run["recommendedAction"] = f"Qwen 复核将在 {countdown} 秒后重试。"
            _persist_retry_state(run)
            raise self.retry(exc=exc, countdown=countdown)
        repo.mark_ocr_pipeline_stage(
            run,
            "qwen_extract",
            "failed",
            blocking_reasons=[{"code": "QWEN_EXTRACTION_FAILED"}],
            failure_reason=exc.__class__.__name__,
        )
        repo.finish_ocr_pipeline_run(
            run,
            status="failed" if run.get("mode") == "active" else "partial",
            blocking_reasons=[{"code": "QWEN_EXTRACTION_FAILED"}],
            recommended_action="检查 Qwen 官方 API 配置或额度后重试。",
        )
        if run.get("mode") == "active":
            failed = deepcopy(parse_result)
            failed["status"] = "success"
            failed["outcomeStatus"] = "partial"
            failed.setdefault("quality", {})["status"] = "needs_human_review"
            failed["quality"].setdefault("blockingReasons", []).append({"code": "QWEN_EXTRACTION_FAILED"})
            failed["quality"].setdefault("reasons", []).append("FIELD_EVIDENCE_MISSING")
            pipeline_apply_result(
                str(run.get("documentId") or ""),
                str(run.get("documentVersionId") or ""),
                failed,
                state_record_ids(
                    ocr_result_state_records(
                        str(run.get("documentId") or ""),
                        str(run.get("documentVersionId") or ""),
                    )
                ),
            )
        persist_ocr_pipeline_progress(run)
        return {"pipelineRunId": run_id, "status": run.get("status"), "failureReason": exc.__class__.__name__}
    finally:
        shutil.rmtree(work_directory, ignore_errors=True)
        if source_temp:
            shutil.rmtree(source_temp, ignore_errors=True)


def _ocr_pipeline_finalize_impl(run_id: str) -> dict[str, Any]:
    refresh_worker_state(
        {
            "projects",
            "documents",
            "versions",
            "bindings",
            "knowledge_files",
            "knowledge_tasks",
            "ocr_jobs",
            "ocr_parse_results",
            "ocr_pipeline_runs",
            "ocr_stage_runs",
            "extracted_fields",
            "evidence_links",
            "node_evidence_links",
            "material_targeting_runs",
        }
    )
    run = repo.find_one("ocr_pipeline_runs", run_id)
    if not run:
        return {"pipelineRunId": run_id, "status": "missing"}
    if run.get("status") in {"completed", "partial"} and run.get("finishedAt"):
        return {"pipelineRunId": run_id, "status": run.get("status"), "alreadyCompleted": True}
    baseline = repo.find_one(
        "ocr_parse_results",
        str(run.get("fusedParseResultId") or run.get("baselineParseResultId") or ""),
        id_field="parseResultId",
    )
    if not baseline:
        return {"pipelineRunId": run_id, "status": "failed", "failureReason": "baseline_parse_result_missing"}
    repo.mark_ocr_pipeline_stage(run, "grounding_validate", "running")
    persist_ocr_pipeline_progress(run)
    profile = default_profile(run.get("profileId"), run.get("documentType"))
    merged = merge_grounded_fields(baseline, run.get("groundedFields") or [])
    blockers = [
        *[item for item in run.get("localStageBlockingReasons") or [] if isinstance(item, dict)],
        *required_field_blockers(merged, profile),
    ]
    validation = run.get("groundingValidation") if isinstance(run.get("groundingValidation"), dict) else {}
    if int(validation.get("invalidCandidateIdCount") or 0) > 0:
        blockers.append({"code": "INVALID_CANDIDATE_ID"})
    if int(validation.get("unsupportedAttributionCount") or 0) > 0:
        blockers.append({"code": "UNSUPPORTED_ATTRIBUTION"})
    if bool(validation.get("outputTruncated")):
        blockers.append({"code": "OCR_OUTPUT_TRUNCATED"})
    runtime = ocr_runtime_config()
    formal_profile_allowed = str(profile.get("profileId") or "") in set(
        runtime.get("formalReadinessProfileAllowlist") or []
    )
    formal_readiness_blockers = (
        [{"code": "PROFILE_NOT_CERTIFIED_FOR_FORMAL_READINESS"}]
        if run.get("mode") == "active" and not formal_profile_allowed
        else []
    )
    run["formalReadinessBlockingReasons"] = formal_readiness_blockers
    if blockers:
        repo.mark_ocr_pipeline_stage(
            run,
            "grounding_validate",
            "partial",
            blocking_reasons=blockers,
        )
    else:
        repo.mark_ocr_pipeline_stage(run, "grounding_validate", "success")
    repo.mark_ocr_pipeline_stage(run, "finalize", "running")
    applied: dict[str, Any] | None = None
    targeting: dict[str, Any] | None = None
    if run.get("mode") == "active":
        authoritative = deepcopy(merged)
        authoritative["parseResultId"] = f"{baseline.get('parseResultId')}-QWEN"
        authoritative["parserVersion"] = f"{baseline.get('parserVersion') or 'ocr'}+{pipeline_version()}"
        authoritative["outcomeStatus"] = "completed" if not blockers else "partial"
        authoritative["status"] = "success"
        authoritative.setdefault("quality", {})["status"] = "usable" if not blockers else "needs_human_review"
        authoritative["quality"]["blockingReasons"] = blockers
        authoritative["quality"]["reasons"] = sorted(
            {
                str(item.get("code") or "FIELD_EVIDENCE_MISSING")
                for item in blockers
                if isinstance(item, dict)
            }
            | ({"FIELD_EVIDENCE_MISSING"} if blockers else set())
        )
        job = repo.find_one("ocr_jobs", str(run.get("ocrJobRecordId") or ""))
        authoritative_record = repo.finish_ocr_job_record(job, authoritative) if job else authoritative
        run["parseResultId"] = (authoritative_record or {}).get("parseResultId")
        previous_ids = state_record_ids(
            ocr_result_state_records(str(run.get("documentId") or ""), str(run.get("documentVersionId") or ""))
        )
        applied, targeting = pipeline_apply_result(
            str(run.get("documentId") or ""),
            str(run.get("documentVersionId") or ""),
            authoritative,
            previous_ids,
        )
        knowledge_file = repo.knowledge_file_for_version(str(run.get("documentVersionId") or ""))
        if applied.get("status") == "success" and knowledge_file:
            run["nextDispatch"] = task_dispatcher.dispatch_slice(str(knowledge_file["id"]))
    repo.mark_ocr_pipeline_stage(run, "finalize", "success")
    final_status = "completed" if not blockers else "partial"
    formal_ready = bool(run.get("mode") == "active" and formal_profile_allowed and not blockers)
    run["formalReadinessProfileAllowed"] = formal_profile_allowed
    repo.finish_ocr_pipeline_run(
        run,
        status=final_status,
        blocking_reasons=blockers,
        recommended_action="确认 OCR 候选证据。" if not blockers else "在 FDE 中复核缺失或冲突字段。",
        formal_evidence_ready=formal_ready,
    )
    artifact_url, artifact_hash = store_ocr_pipeline_artifact(
        run,
        "finalize",
        {
            "schemaVersion": "OcrAccuracyPipelineResult@1",
            "pipelineRunId": run_id,
            "mode": run.get("mode"),
            "status": final_status,
            "blockingReasons": blockers,
            "formalReadinessBlockingReasons": formal_readiness_blockers,
            "formalEvidenceReady": formal_ready,
            "applied": applied,
            "targeting": targeting,
        },
    )
    repo.mark_ocr_pipeline_stage(
        run,
        "finalize",
        "success",
        artifact_url=artifact_url,
        artifact_hash=artifact_hash,
    )
    persist_ocr_pipeline_progress(run)
    return {
        "pipelineRunId": run_id,
        "status": final_status,
        "mode": run.get("mode"),
        "formalEvidenceReady": formal_ready,
        "blockingReasons": blockers,
        "formalReadinessBlockingReasons": formal_readiness_blockers,
        "applied": applied,
    }


@celery_app.task(bind=True, max_retries=2)
@pipeline_task_lock("ocr-finalize", lambda _self, run_id: str(run_id))
def ocr_pipeline_finalize(self, run_id: str) -> dict[str, Any]:
    try:
        return _ocr_pipeline_finalize_impl(run_id)
    except Exception as exc:
        refresh_worker_state({"ocr_pipeline_runs", "ocr_stage_runs"})
        run = repo.find_one("ocr_pipeline_runs", run_id)
        if run is None:
            raise
        failed_stage = str(run.get("currentStage") or "finalize")
        retry_index = int(getattr(self.request, "retries", 0) or 0)
        if retry_index < 2:
            countdown = (5, 15)[retry_index]
            repo.mark_ocr_pipeline_stage(run, failed_stage, "retrying", failure_reason=exc.__class__.__name__)
            run["recommendedAction"] = f"结果收敛将在 {countdown} 秒后重试。"
            _persist_retry_state(run)
            raise self.retry(exc=exc, countdown=countdown)
        repo.mark_ocr_pipeline_stage(
            run,
            failed_stage,
            "failed",
            blocking_reasons=[{"code": "PIPELINE_FINALIZE_FAILED"}],
            failure_reason=exc.__class__.__name__,
        )
        repo.finish_ocr_pipeline_run(
            run,
            status="failed" if run.get("mode") == "active" else "partial",
            blocking_reasons=[{"code": "PIPELINE_FINALIZE_FAILED"}],
            recommended_action="在任务中心重试结果收敛，Shadow 基线结果保持不变。",
            formal_evidence_ready=False,
        )
        persist_ocr_pipeline_progress(run)
        return {
            "pipelineRunId": run_id,
            "status": run.get("status"),
            "failureReason": exc.__class__.__name__,
        }


def document_ai_source_path(run: dict[str, Any]) -> tuple[Path | None, Path | None]:
    storage_key = str(run.get("storageKey") or "")
    local_path = local_path_from_storage_key(storage_key, WORKSPACE_ROOT)
    if local_path:
        return local_path, None
    parsed = parse_storage_url(storage_key)
    if parsed:
        bucket, object_name = parsed
    else:
        bucket = str(run.get("storageBucket") or "")
        object_name = storage_key
    if not bucket or not object_name:
        return None, None
    suffix = Path(str(run.get("fileName") or object_name)).suffix
    downloaded = object_storage.download_to_temp(bucket, object_name, suffix=suffix)
    return downloaded, downloaded.parent if downloaded else None


def document_ai_structured_output(response: dict[str, Any]) -> Any:
    output = response.get("structuredOutput")
    if output is None:
        output = response.get("output")
    if output is None and isinstance(response.get("result"), dict):
        output = response["result"].get("structuredOutput") or response["result"].get("output")
    if isinstance(output, str):
        text = output.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0].strip()
            if text.startswith("json"):
                text = text[4:].lstrip()
        try:
            output = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("document_ai_invalid_structured_json") from exc
    if not isinstance(output, (dict, list)):
        raise RuntimeError("document_ai_missing_structured_output")
    return output


@celery_app.task(bind=True)
def document_ai_shadow_extract(self, run_id: str) -> dict[str, Any]:
    refresh_worker_state({"documents", "versions", "ocr_parse_results", "document_ai_shadow_runs"})
    run = repo.find_one("document_ai_shadow_runs", run_id)
    if run is None:
        return {"runId": run_id, "status": "missing"}
    if run.get("status") == "success":
        return {"runId": run_id, "status": "success", "alreadyCompleted": True}
    run.update(
        {
            "status": "running",
            "taskId": str(getattr(self.request, "id", "") or run.get("taskId") or "") or None,
            "startedAt": server_time(),
            "updatedAt": server_time(),
            "advisoryOnly": True,
            "businessImpact": "none",
        }
    )
    persist_document_ai_shadow_run(run)
    temporary_directory: Path | None = None
    try:
        parse_result = repo.find_one("ocr_parse_results", str(run.get("parseResultId") or ""), id_field="parseResultId")
        if not parse_result:
            raise RuntimeError("baseline_parse_result_missing")
        if stable_payload_hash(parse_result) != str(run.get("baselineHash") or ""):
            raise RuntimeError("baseline_hash_mismatch")
        profile = profile_for(str(run.get("profileId") or ""))
        structured = profile.get("structuredExtraction")
        if not isinstance(structured, dict) or structured.get("mode") != "shadow":
            raise RuntimeError("structured_extraction_profile_missing")
        prior_bundle = build_evidence_prior(parse_result, profile)
        compact_prior = prior_bundle["compact"]
        run.update(
            {
                "fullPriorHash": prior_bundle["fullPriorHash"],
                "priorHash": prior_bundle["compactPriorHash"],
                "priorCandidateCount": compact_prior.get("candidateCount"),
                "priorOmittedCandidateCount": compact_prior.get("omittedCandidateCount"),
                "priorEstimatedTokenCount": compact_prior.get("estimatedTokenCount"),
                "selectedPageNos": compact_prior.get("selectedPageNos"),
                "priorDiagnostics": compact_prior.get("diagnostics") or [],
                "evidencePrior": compact_prior,
                "updatedAt": server_time(),
            }
        )
        persist_document_ai_shadow_run(run)
        source_path, temporary_directory = document_ai_source_path(run)
        if not source_path or not source_path.is_file():
            raise RuntimeError("document_ai_source_missing")
        client = DocumentAiClient()
        response = client.extract_upload_sync(
            source_path,
            {
                "schemaVersion": "DocumentAiHybridExtractRequest@1",
                "runId": run_id,
                "advisoryOnly": True,
                "profileId": profile.get("profileId"),
                "templateVersion": structured.get("templateVersion"),
                "fileName": run.get("fileName"),
                "structuredExtraction": structured,
                "selectedPageNos": compact_prior.get("selectedPageNos"),
                "evidencePrior": compact_prior,
                "baselineHash": run.get("baselineHash"),
                "constraints": {
                    "maxPages": 6,
                    "maxCandidates": 64,
                    "maxPriorTokens": 12000,
                    "maxOutputTokens": 2048,
                    "deadlineSeconds": 180,
                },
            },
        )
        structured_output = document_ai_structured_output(response)
        attribution = validate_shadow_attribution(structured_output, compact_prior)
        validated_output = attribution["structuredOutput"]
        run.update(
            {
                "status": "success",
                "remoteRunId": response.get("runId") or response.get("remoteRunId"),
                "modelRevision": response.get("modelRevision") or response.get("nuExtractRevision"),
                "paddleModelRevision": response.get("paddleModelRevision") or response.get("paddleRevision"),
                "structuredOutput": validated_output,
                "attributionValidation": attribution["validation"],
                "outputDiff": compare_shadow_to_baseline(parse_result, validated_output),
                "diagnostics": response.get("diagnostics") or [],
                "queueTimeMs": response.get("queueTimeMs"),
                "inferenceTimeMs": response.get("inferenceTimeMs"),
                "totalTimeMs": response.get("totalTimeMs"),
                "jsonRetryCount": response.get("jsonRetryCount"),
                "tableExtractionDeferred": bool(response.get("tableExtractionDeferred")),
                "formalEvidenceReady": False,
                "advisoryOnly": True,
                "businessImpact": "none",
                "finishedAt": server_time(),
                "updatedAt": server_time(),
                "failureReason": None,
            }
        )
        persist_document_ai_shadow_run(run)
        try:
            run["pipelineComparisonDispatch"] = schedule_pipeline_comparison(run)
        except Exception as exc:  # Pipeline A/B must never affect Document AI Shadow success.
            run["pipelineComparisonDispatch"] = {
                "status": "not_dispatched",
                "statusReason": f"pipeline_comparison_setup_{exc.__class__.__name__.lower()}",
            }
    except Exception as exc:  # Shadow failures are observable but never propagated into baseline OCR.
        reason = (
            exc.reason
            if isinstance(exc, IntegrationServiceError) and exc.reason
            else safe_reason(str(exc).strip().upper())
            or exc.__class__.__name__.upper()
        )
        status_code = exc.status_code if isinstance(exc, IntegrationServiceError) else None
        run.update(
            {
                "status": "failed",
                "failureReason": reason,
                "failureStatusCode": status_code,
                "formalEvidenceReady": False,
                "advisoryOnly": True,
                "businessImpact": "none",
                "finishedAt": server_time(),
                "updatedAt": server_time(),
            }
        )
    finally:
        persist_document_ai_shadow_run(run)
        if temporary_directory:
            shutil.rmtree(temporary_directory, ignore_errors=True)
    return {
        "runId": run_id,
        "status": run.get("status"),
        "advisoryOnly": True,
        "businessImpact": "none",
        "failureReason": run.get("failureReason"),
        "pipelineComparisonDispatch": run.get("pipelineComparisonDispatch"),
    }


def render_pipeline_comparison_pages(
    source_path: Path,
    selected_page_nos: list[int],
    output_directory: Path,
) -> list[Path]:
    selected = sorted({int(value) for value in selected_page_nos if int(value) > 0})[:6]
    if not selected:
        selected = [1]
    output_directory.mkdir(parents=True, exist_ok=True)
    with source_path.open("rb") as handle:
        signature = handle.read(4)
    if signature == b"%PDF":
        import fitz

        document = fitz.open(source_path)
        rendered = []
        try:
            for page_no in selected:
                if page_no > document.page_count:
                    raise RuntimeError("pipeline_comparison_page_out_of_range")
                page = document.load_page(page_no - 1)
                long_side = max(float(page.rect.width), float(page.rect.height), 1.0)
                scale = max(1.0, min(3.0, 1800.0 / long_side))
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                target = output_directory / f"page-{page_no:04d}.png"
                pixmap.save(target)
                rendered.append(target)
        finally:
            document.close()
        return rendered
    if selected != [1]:
        raise RuntimeError("pipeline_comparison_image_has_only_page_one")
    from PIL import Image

    target = output_directory / "page-0001.png"
    with Image.open(source_path) as image:
        converted = image.convert("RGB")
        converted.thumbnail((1800, 1800))
        converted.save(target, "PNG", optimize=True)
    return [target]


def pipeline_candidate_ids(document_ai_run: dict[str, Any]) -> set[str]:
    structured = document_ai_run.get("structuredOutput") if isinstance(document_ai_run.get("structuredOutput"), dict) else {}
    return collect_source_candidate_ids(structured)


@celery_app.task(bind=True)
def document_audit_pipeline_comparison(self, run_id: str) -> dict[str, Any]:
    refresh_worker_state(
        {
            "documents",
            "versions",
            "bindings",
            "rule_versions",
            "retrieval_traces",
            "document_ai_shadow_runs",
            "document_audit_pipeline_comparison_runs",
        }
    )
    run = repo.find_one("document_audit_pipeline_comparison_runs", run_id)
    if run is None:
        return {"runId": run_id, "status": "missing"}
    if run.get("status") == "success":
        return {"runId": run_id, "status": "success", "alreadyCompleted": True}
    run.update(
        {
            "status": "running",
            "taskId": str(getattr(self.request, "id", "") or run.get("taskId") or "") or None,
            "startedAt": server_time(),
            "updatedAt": server_time(),
            "advisoryOnly": True,
            "formalEvidenceReady": False,
            "businessImpact": "none",
            "runtime": deepseek_runtime_public_config(),
        }
    )
    persist_pipeline_comparison_run(run)
    source_temp: Path | None = None
    page_temp = Path(tempfile.mkdtemp(prefix=f"aicheck-pipeline-{run_id}-"))
    try:
        document_ai_run = repo.find_one(
            "document_ai_shadow_runs",
            str(run.get("documentAiShadowRunId") or ""),
        )
        if not document_ai_run or document_ai_run.get("status") != "success":
            raise RuntimeError("document_ai_shadow_run_missing")
        source_path, source_temp = document_ai_source_path(document_ai_run)
        if not source_path or not source_path.is_file():
            raise RuntimeError("pipeline_comparison_source_missing")
        page_paths = render_pipeline_comparison_pages(
            source_path,
            [int(value) for value in document_ai_run.get("selectedPageNos") or [1]],
            page_temp,
        )
        industry_context = build_shared_industry_context(document_ai_run)
        context_hash = stable_hash_payload(industry_context)

        qwen_started = time.monotonic()
        qwen_response = QwenVisionAuditClient().chat_sync(
            build_qwen_vision_messages(page_paths, industry_context)
        )
        qwen_time_ms = round((time.monotonic() - qwen_started) * 1000)

        deepseek_started = time.monotonic()
        deepseek_client = DeepSeekAuditClient()
        deepseek_messages = build_deepseek_messages(document_ai_run, industry_context)
        deepseek_response = deepseek_client.chat_sync(deepseek_messages)
        deepseek_retry_count = 0
        deepseek_effective_thinking = "enabled"
        try:
            deepseek_payload = parse_json_model_output(deepseek_response)
        except (TypeError, ValueError):
            deepseek_retry_count = 1
            deepseek_effective_thinking = "disabled"
            deepseek_response = deepseek_client.chat_sync(deepseek_messages, thinking_type="disabled")
            deepseek_payload = parse_json_model_output(deepseek_response)
        deepseek_time_ms = round((time.monotonic() - deepseek_started) * 1000)

        qwen_payload = parse_json_model_output(qwen_response)
        baseline_result = normalize_pipeline_result(
            qwen_payload,
            pipeline_id=str(run.get("baselinePipelineId") or "qwen_vl_audit_v1"),
            industry_context=industry_context,
            allowed_candidate_ids=set(),
            direct_vision_only=True,
        )
        challenger_result = normalize_pipeline_result(
            deepseek_payload,
            pipeline_id=str(run.get("challengerPipelineId") or "paddle_nuextract_deepseek_v1"),
            industry_context=industry_context,
            allowed_candidate_ids=pipeline_candidate_ids(document_ai_run),
            fixed_document_fields=(document_ai_run.get("structuredOutput") or {}).get("fields") or {},
            fixed_tables=(document_ai_run.get("structuredOutput") or {}).get("tables") or {},
        )
        metrics = compare_pipeline_results(baseline_result, challenger_result)
        challenger_message = ((deepseek_response.get("choices") or [{}])[0].get("message") or {})
        upstream_time_ms = int(document_ai_run.get("totalTimeMs") or 0)
        run.update(
            {
                "status": "success",
                "sharedIndustryContext": industry_context,
                "sharedIndustryContextHash": context_hash,
                "baselineResult": baseline_result,
                "challengerResult": challenger_result,
                "comparisonMetrics": metrics,
                "baselineModelResolved": qwen_response.get("model") or run.get("baselineModel"),
                "challengerModelResolved": deepseek_response.get("model") or run.get("challengerModel"),
                "baselineResponseHash": stable_hash_payload(qwen_response),
                "challengerResponseHash": stable_hash_payload(deepseek_response),
                "baselineUsage": qwen_response.get("usage") or {},
                "challengerUsage": deepseek_response.get("usage") or {},
                "baselineFinishReason": ((qwen_response.get("choices") or [{}])[0] or {}).get("finish_reason"),
                "challengerFinishReason": ((deepseek_response.get("choices") or [{}])[0] or {}).get("finish_reason"),
                "challengerReasoningHash": stable_hash_payload(challenger_message.get("reasoning_content") or ""),
                "challengerReasoningLength": len(str(challenger_message.get("reasoning_content") or "")),
                "baselineTimeMs": qwen_time_ms,
                "challengerUpstreamDocumentAiTimeMs": upstream_time_ms,
                "challengerDeepSeekTimeMs": deepseek_time_ms,
                "challengerDeepSeekRetryCount": deepseek_retry_count,
                "challengerDeepSeekEffectiveThinking": deepseek_effective_thinking,
                "challengerEndToEndTimeMs": upstream_time_ms + deepseek_time_ms,
                "formalEvidenceReady": False,
                "advisoryOnly": True,
                "businessImpact": "none",
                "finishedAt": server_time(),
                "updatedAt": server_time(),
                "failureReason": None,
                "rawReasoningStored": False,
            }
        )
    except Exception as exc:  # Comparison failure must never affect either production or Shadow source results.
        reason = (
            exc.reason
            if isinstance(exc, IntegrationServiceError) and exc.reason
            else safe_reason(str(exc).strip().upper())
            or exc.__class__.__name__.upper()
        )
        run.update(
            {
                "status": "failed",
                "failureReason": reason,
                "formalEvidenceReady": False,
                "advisoryOnly": True,
                "businessImpact": "none",
                "finishedAt": server_time(),
                "updatedAt": server_time(),
            }
        )
    finally:
        persist_pipeline_comparison_run(run)
        shutil.rmtree(page_temp, ignore_errors=True)
        if source_temp:
            shutil.rmtree(source_temp, ignore_errors=True)
    return {
        "runId": run_id,
        "status": run.get("status"),
        "advisoryOnly": True,
        "businessImpact": "none",
        "failureReason": run.get("failureReason"),
    }


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def recognize_seals(self, document_id: str, version_id: str) -> dict[str, Any]:
    refresh_worker_state()
    load_state()
    version = repo.find_one("versions", version_id)
    storage_key = version.get("storageKey") if version else version_id
    result = parse_with_ocr_service(
        storage_key,
        file_name=(repo.find_one("documents", document_id) or {}).get("fileName"),
        document_id=document_id,
        version_id=version_id,
    )
    flush_state()
    return {"documentId": document_id, "versionId": version_id, "seals": result.get("seals") or []}


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def slice_knowledge(self, file_id: str, dispatch_next: bool = True) -> dict[str, Any]:
    refresh_worker_state()
    task = next((item for item in repo.state["knowledge_tasks"] if item.get("taskType") == "slice" and item.get("targetId") == file_id), None)
    file = repo.find_one("knowledge_files", file_id)
    if task is None and file is None:
        load_state()
        task = next((item for item in repo.state["knowledge_tasks"] if item.get("taskType") == "slice" and item.get("targetId") == file_id), None)
        file = repo.find_one("knowledge_files", file_id)
    if task and task.get("status") == "已取消":
        flush_state()
        return {"fileId": file_id, "status": "canceled", "chunkCount": 0}
    if task and task.get("status") == "成功" and (file or {}).get("sliceStatus") == "已切片":
        chunk_count = len([item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == file_id])
        flush_state()
        return {"fileId": file_id, "status": "success", "chunkCount": chunk_count, "alreadyCompleted": True}
    repo.mark_task_running(task, "切片 worker 开始处理。")
    if not file:
        repo.mark_task_failed(task, "切片任务失败：找不到关联知识文件。")
        flush_state()
        return {"fileId": file_id, "status": "missing", "chunkCount": 0}
    fragments = knowledge_slice_fragments_from_ocr(file)
    if not fragments:
        version = repo.find_one("versions", file.get("documentVersionId"))
        source_path = local_path_from_storage_key((version or {}).get("storageKey"), WORKSPACE_ROOT)
        if source_path:
            fragments = units_from_local_file(source_path)
    if not fragments:
        fields = [
            item
            for item in repo.state["extracted_fields"]
            if item.get("documentVersionId") == file.get("documentVersionId")
        ]
        fragments = [
            {"pageNo": item.get("pageNo") or 1, "text": f"{item.get('fieldName')}: {item.get('fieldValue')}"}
            for item in fields
        ]
    result = repo.apply_slice_result(file_id, fragments or None)
    flush_state()
    if result.get("status") == "success" and dispatch_next:
        result["nextDispatch"] = task_dispatcher.dispatch_embed(file_id)
    return result


@celery_app.task(bind=True, max_retries=3)
def embed_knowledge(
    self,
    file_id: str,
    offset: int = 0,
    allow_celery_continuation: bool = True,
) -> dict[str, Any]:
    # Deployment contract marker: embedding_batches_for_chunks keeps offline_hash_embeddings / offline_hash fallback.
    refresh_worker_state()
    chunks = sorted(
        [item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == file_id],
        key=lambda item: int(item.get("chunkNo") or 0),
    )
    embedding_model = OFFLINE_EMBEDDING_MODEL
    index_version = STANDARD_INDEX_VERSION
    expected_dimensions = int(active_embedding_target()["dimensions"])
    task = next((item for item in repo.state["knowledge_tasks"] if item.get("taskType") == "vector" and item.get("targetId") == file_id), None)
    file = repo.find_one("knowledge_files", file_id)
    if task is None and file is None and not chunks:
        load_state()
        chunks = sorted(
            [item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == file_id],
            key=lambda item: int(item.get("chunkNo") or 0),
        )
        task = next((item for item in repo.state["knowledge_tasks"] if item.get("taskType") == "vector" and item.get("targetId") == file_id), None)
        file = repo.find_one("knowledge_files", file_id)
    vector_count = len(chunks) or 1
    if task and task.get("status") == "已取消":
        flush_state()
        return {"fileId": file_id, "status": "canceled", "vectorCount": 0}
    if task and task.get("status") == "成功" and (file or {}).get("vectorStatus") == "已向量化":
        task.pop("errorMessage", None)
        flush_state()
        return {"fileId": file_id, "status": "success", "vectorCount": int((file or {}).get("vectorCount") or vector_count), "alreadyCompleted": True}
    if int(offset or 0) == 0:
        repo.mark_task_running(task, "向量化 worker 开始处理。")
        repo.state["knowledge_embedding_batches"] = [
            item for item in repo.state.get("knowledge_embedding_batches", []) if item.get("fileId") != file_id
        ]
    if not file:
        repo.mark_task_failed(task, "向量化任务失败：找不到关联知识文件。")
        flush_state()
        return {"fileId": file_id, "status": "missing", "vectorCount": 0}
    try:
        vectors: list[dict[str, Any]] = []
        fallback_reason = None
        if chunks:
            checkpoint_size = (
                max(1, min(int(os.getenv("AICHECK_EMBEDDING_CHECKPOINT_BATCH_SIZE", "8")), EMBED_BATCH_SIZE))
                if allow_celery_continuation and task_dispatcher.dispatch_mode() == "celery"
                else len(chunks)
            )
            start = max(0, int(offset or 0))
            end = min(start + checkpoint_size, len(chunks))
            batch_vectors, embedding_model, index_version, expected_dimensions, fallback_reason = embedding_batches_for_chunks(
                chunks[start:end]
            )
            vectors = [{**item, "index": start + int(item.get("index") or 0)} for item in batch_vectors]
            batch_record = {
                "id": f"EMBBATCH-{file_id}-{start}",
                "fileId": file_id,
                "offset": start,
                "endOffset": end,
                "vectors": vectors,
                "embeddingModel": embedding_model,
                "indexVersion": index_version,
                "dimensions": expected_dimensions,
                "fallbackReason": fallback_reason,
                "updatedAt": server_time(),
            }
            repo.state["knowledge_embedding_batches"] = [
                item
                for item in repo.state.get("knowledge_embedding_batches", [])
                if not (item.get("fileId") == file_id and int(item.get("offset") or 0) == start)
            ]
            repo.state.setdefault("knowledge_embedding_batches", []).append(batch_record)
            if task:
                task["progress"] = max(10, int(end / max(len(chunks), 1) * 95))
                task["embeddingCheckpoint"] = {"nextOffset": end, "totalChunks": len(chunks)}
                task["updatedAt"] = server_time()
            if (
                end < len(chunks)
                and allow_celery_continuation
                and task_dispatcher.dispatch_mode() == "celery"
            ):
                continuation = embed_knowledge.apply_async(
                    args=[file_id, end],
                    queue="cpu.heavy",
                    priority=task_dispatcher.broker_priority(1),
                )
                if task:
                    task["lastDispatch"] = {
                        "mode": "celery",
                        "taskId": continuation.id,
                        "queue": "cpu.heavy",
                        "priority": 1,
                    }
                flush_state()
                return {
                    "fileId": file_id,
                    "status": "checkpointed",
                    "nextOffset": end,
                    "totalChunks": len(chunks),
                    "taskId": continuation.id,
                }
            all_batches = sorted(
                [item for item in repo.state.get("knowledge_embedding_batches", []) if item.get("fileId") == file_id],
                key=lambda item: int(item.get("offset") or 0),
            )
            vectors = [vector for batch in all_batches for vector in batch.get("vectors") or []]
            vector_count = len(vectors)
            if all_batches:
                embedding_model = str(all_batches[-1].get("embeddingModel") or embedding_model)
                index_version = str(all_batches[-1].get("indexVersion") or index_version)
                expected_dimensions = int(all_batches[-1].get("dimensions") or expected_dimensions)
                fallback_reason = next(
                    (str(item.get("fallbackReason")) for item in all_batches if item.get("fallbackReason")),
                    None,
                )
        result = repo.apply_embed_result(
            file_id,
            vector_count,
            vectors=vectors,
            embedding_model=embedding_model,
            index_version=index_version,
            expected_dimensions=expected_dimensions,
            vector_status_reason=fallback_reason,
        )
        repo.state["knowledge_embedding_batches"] = [
            item for item in repo.state.get("knowledge_embedding_batches", []) if item.get("fileId") != file_id
        ]
    except Exception as exc:
        retry_index = int(getattr(self.request, "retries", 0) or 0)
        if retry_index < 3:
            countdown = (10, 30, 90)[retry_index]
            if task:
                task["status"] = "排队中"
                task["updatedAt"] = server_time()
                repo.append_task_log(task, "warning", f"向量批次失败，将在 {countdown} 秒后重试。")
            flush_state()
            raise self.retry(exc=exc, countdown=countdown)
        message = "EXTERNAL_TOOL_FAILED: embedding 向量化失败，请检查远程 Qwen3 服务、隧道和向量索引状态。"
        result = {"fileId": file_id, "status": "failed", "errorMessage": message}
        if task:
            repo.mark_task_failed(task, message)
    flush_state()
    return result


def execute_postgres_knowledge_task(
    task_type: str,
    file_id: str,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    """Execute one persisted post-processing task without Celery dispatch."""

    tenant_context = set_request_tenant_id(tenant_id)
    try:
        if task_type == "slice":
            return slice_knowledge.run(file_id, False)
        if task_type == "vector":
            return embed_knowledge.run(file_id, 0, False)
        raise ValueError(f"Unsupported PostgreSQL knowledge task type: {task_type}")
    finally:
        reset_request_tenant_id(tenant_context)


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def ai_recheck(self, project_id: str, node_id: int, run_id: str) -> dict[str, Any]:
    refresh_worker_state()
    run = repo.find_one("ai_runs", run_id)
    if not run:
        load_state()
        run = repo.find_one("ai_runs", run_id)
    if not run:
        return {"projectId": project_id, "nodeId": node_id, "runId": run_id, "status": "missing"}
    if run.get("status") in {"完成", "失败"} and run.get("finishedAt"):
        flush_state()
        return {"projectId": project_id, "nodeId": node_id, "runId": run_id, "status": run.get("status"), "alreadyCompleted": True}
    node = repo.node(project_id, node_id)
    project = repo.require_project(project_id)
    pack = (project or {}).get("businessPackSnapshot") or load_business_pack(
        run.get("businessPackId") or (project or {}).get("businessPackId") or "engineering_inspection_v1"
    )
    audit_runtime = audit_runtime_for_run(run)
    version_ids = set(run.get("inputDocumentVersionIds") or [])
    if audit_runtime["useOcrEvidence"]:
        grounding_input = build_grounded_review_input(repo.state, version_ids)
    else:
        grounding_input = {
            "schemaVersion": "PureLlmReviewInput@1.0.0",
            "documentVersionIds": sorted(version_ids),
            "auditInputMode": audit_runtime["mode"],
            "groundingPolicy": audit_runtime["groundingPolicy"],
            "groundingStatus": "insufficient_evidence",
            "blockingIssues": [{"code": "PURE_LLM_REVIEW_NO_OCR_EVIDENCE"}],
            "fields": [],
            "tables": [],
            "seals": [],
            "fragments": [],
            "evidenceLinks": [],
            "quality": [],
            "evidenceTextCorpus": [],
            "summary": {"groundingStatus": "insufficient_evidence", "auditInputMode": audit_runtime["mode"]},
            "reviewWarnings": [{"code": "PURE_LLM_REVIEW_ADVISORY_ONLY"}],
        }
    grounding_block = grounding_prompt_block(grounding_input)
    fields = grounding_input.get("fields") or []
    evidence_links = grounding_input.get("evidenceLinks") or []
    rule = matching_rule_for_node(pack, node_id)
    prompt_template = production_prompt_template_for_run(run)
    prompt = build_ai_review_prompt(pack, node=node, fields=fields, rule=rule, prompt_template=prompt_template)
    review_task_json = json.dumps(
        {
            "task": "Generate ReviewFindingDraftList JSON only.",
            "requirements": [
                "Every finding must require human confirmation.",
                "Do not infer names, dates, validity, project coverage, certificate authenticity, seal text, or table values that are not present in evidence.",
                *grounding_block["requirements"],
            ],
            "strictGroundingPolicy": grounding_block["strictGroundingPolicy"],
            "auditInputMode": audit_runtime["mode"],
            "auditRuntime": audit_runtime_public_config(mode=audit_runtime["mode"]),
            "projectId": project_id,
            "nodeId": node_id,
            "fixedClausePackage": run.get("clausePackageSnapshot") or {},
            "fieldCount": len(fields),
            "groundingStatus": grounding_input.get("groundingStatus"),
            "groundedOcrEvidence": grounding_block["groundedOcrEvidence"],
            "evidenceLinkIds": [item.get("id") for item in evidence_links],
        },
        ensure_ascii=False,
    )
    user_prompt = prompt["user"].replace("{{reviewTaskJson}}", review_task_json)
    if review_task_json not in user_prompt:
        user_prompt = f"{user_prompt}\n\n{review_task_json}"
    messages = [{"role": "system", "content": prompt["system"]}, {"role": "user", "content": user_prompt}]
    run["promptAudit"] = {
        "promptVersion": run.get("promptVersion"),
        "promptTemplateId": (prompt_template or {}).get("id"),
        "promptTemplateName": (prompt_template or {}).get("name"),
        "promptTemplateVersion": (prompt_template or {}).get("version"),
        "messagesHash": stable_hash_payload(messages),
        "systemPrompt": prompt["system"],
        "userPrompt": user_prompt,
        "plannerPrompt": (prompt.get("template") or {}).get("plannerPrompt") or "",
        "criticPrompt": (prompt.get("template") or {}).get("criticPrompt") or "",
        "messages": messages,
        "payloadPolicy": "full_prompt_stored_for_audit",
    }
    try:
        qwen_runtime = qwen_runtime_public_config()
        response = qwen_runtime_client().chat_sync(
            messages,
            model=run.get("model") or "review-chat",
            temperature=0.1,
            _raw_capture_context=raw_context_from_record(
                run,
                run_stream_id=str(run.get("reviewRunId") or run.get("id")),
                stage="worker_review_chat",
                turn=1,
            ),
        )
        answer = QwenRuntimeClient.first_message_text(response) or "AI 复核完成，建议人工确认关键证据链。"
        message = ((response.get("choices") or [{}])[0].get("message") or {}) if isinstance(response.get("choices"), list) else {}
        conversation_id = str(response.get("id") or response.get("conversation_id") or f"llm-{stable_hash_payload(response)[7:23]}")
        run["llmConversationId"] = conversation_id
        run["llmMetadata"] = {
            "llmExecution": "qwen_runtime",
            "llmCalled": True,
            "conversationId": conversation_id,
            "modelAlias": run.get("model") or "review-chat",
            "modelResolved": response.get("model") or run.get("model") or "review-chat",
            "qwenRuntime": qwen_runtime,
            "promptVersion": run.get("promptVersion"),
            "promptTemplateId": (prompt_template or {}).get("id"),
            "promptHash": run["promptAudit"]["messagesHash"],
            "responseHash": stable_hash_payload(response),
            "usage": response.get("usage") or {},
            "groundingStatus": grounding_input.get("groundingStatus"),
            "auditInputMode": audit_runtime["mode"],
            "groundingInputSummary": grounding_input.get("summary") or {},
            "reasoningProcess": str(
                message.get("reasoning_content")
                or message.get("reasoning")
                or message.get("reasoningSummary")
                or "模型返回审查建议；未返回单独的公开推理摘要。"
            )[:3000],
            "resultText": answer[:4000],
        }
        run["reasoningProcess"] = run["llmMetadata"]["reasoningProcess"]
        run["llmResultText"] = run["llmMetadata"]["resultText"]
        run["status"] = "完成"
        run["finishedAt"] = server_time()
        rule_ref = {
            "ruleCode": (rule or {}).get("ruleKey") or (rule or {}).get("id"),
            "ruleSetVersion": run.get("ruleVersion") or (rule or {}).get("version"),
        }
        legacy_draft = {
            "id": f"FND-DRAFT-{run_id}",
            "projectId": project_id,
            "nodeId": node_id,
            "businessPackId": run.get("businessPackId"),
            "businessPackVersion": run.get("businessPackVersion"),
            "businessPackSnapshotHash": run.get("businessPackSnapshotHash"),
            "agentId": run.get("agentId"),
            "agentVersion": run.get("agentVersion"),
            "findingType": "ai_review_suggestion",
            "severity": "medium",
            "title": "AI 资料复核建议",
            "description": answer[:800],
            "evidenceLinkIds": [item.get("id") for item in evidence_links[:3] if isinstance(item, dict)],
            "evidenceRefs": [
                {
                    "evidenceLinkId": item.get("id"),
                    "documentVersionId": item.get("documentVersionId"),
                    "pageNo": item.get("pageNo"),
                    "bbox": item.get("bbox"),
                    "source": "evidence_link",
                }
                for item in evidence_links[:3]
                if isinstance(item, dict)
            ],
            "ruleRefs": [rule_ref] if rule_ref.get("ruleCode") else [],
            "kbRefs": [],
            "confidence": 0.82,
            "suggestedAction": "human_confirm",
            "requiresHumanConfirmation": True,
            "status": "pending_human_review",
        }
        guarded_drafts = apply_grounding_guardrails([legacy_draft], grounding_input)
        guarded_draft = guarded_drafts[0] if guarded_drafts else legacy_draft
        run["llmMetadata"]["groundingStatus"] = guarded_draft.get("groundingStatus")
        run["llmMetadata"]["unsupportedClaims"] = guarded_draft.get("unsupportedClaims") or []
        run["steps"] = [
            {
                "id": f"STEP-{run_id}",
                "title": "QwenRuntime 复核",
                "inputSummary": f"{len(fields)} 个 OCR 字段",
                "action": "chat.completions",
                "conclusion": "完成",
                "evidenceLinkIds": [item.get("id") for item in evidence_links[:3] if isinstance(item, dict)],
            }
        ]
        run["suggestion"].update(
            {
                "result": "需人工确认",
                "opinionDraft": str(guarded_draft.get("description") or answer)[:800],
                "confidence": guarded_draft.get("confidence", 0.5),
                "manualConfirmItems": ["证据链和原件一致性"],
            }
        )
        run["evidenceLinks"] = repo.clone(evidence_links[:5])
        repo.state.setdefault("ai_trace_steps", []).append(
            {
                "id": f"TRACE-{run_id}-LLM-{stable_hash_payload(response)[7:13].upper()}",
                "aiRunId": run_id,
                "traceId": f"TRACE-{run_id}",
                "sequence": len([item for item in repo.state.get("ai_trace_steps", []) if item.get("aiRunId") == run_id]) + 1,
                "stepType": "llm_review",
                "name": "QwenRuntime 对话与 Prompt 审计",
                "status": "completed",
                "conversationId": run.get("llmConversationId"),
                "promptHash": (run.get("llmMetadata") or {}).get("promptHash"),
                "responseHash": (run.get("llmMetadata") or {}).get("responseHash"),
                "reasoningProcess": run.get("reasoningProcess"),
                "resultText": run.get("llmResultText"),
                "createdAt": server_time(),
            }
        )
        run["findingDrafts"] = guarded_drafts
        status = "完成"
    except Exception:
        run["status"] = "失败"
        run["finishedAt"] = server_time()
        run["errorCode"] = "AI_RUN_FAILED"
        run["errorMessage"] = service_failure_message("QwenRuntime AI 复核")
        status = "失败"
    flush_state()
    return {"projectId": project_id, "nodeId": node_id, "runId": run_id, "status": status}


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def llm_compare(self, run_id: str) -> dict[str, Any]:
    refresh_worker_state()
    run = repo.find_one("llm_compare_runs", run_id, id_field="runId")
    if not run:
        load_state()
        run = repo.find_one("llm_compare_runs", run_id, id_field="runId")
    if not run:
        return {"runId": run_id, "status": "missing"}
    if run.get("status") in {"完成", "失败"} and run.get("finishedAt"):
        flush_state()
        return {"runId": run_id, "status": run.get("status"), "alreadyCompleted": True}
    results = []
    try:
        run["status"] = "运行中"
        version_ids = compare_document_version_ids(run)
        grounding_input = build_grounded_review_input(repo.state, version_ids)
        grounding_block = grounding_prompt_block(grounding_input)
        compare_payload = {
            "task": "Compare model answers for a human reviewer. Do not issue a final business approval, rejection, or compliance conclusion.",
            "compareOnly": True,
            "question": run.get("question") or "请对比审查意见。",
            "strictGroundingPolicy": grounding_block["strictGroundingPolicy"],
            "requirements": [
                "Answer only as a model comparison assistant.",
                "Do not state that documents are compliant, valid, authentic, covered, or pass unless the exact fact is present in groundedOcrEvidence.",
                "If OCR evidence is insufficient, say that the comparison requires human confirmation.",
                *grounding_block["requirements"],
            ],
            "groundedOcrEvidence": grounding_block["groundedOcrEvidence"],
            "evidenceLinkIds": run.get("evidenceLinkIds") or [],
            "requiredOutput": {
                "answer": "Short compare-only response in Chinese.",
                "mustInclude": ["groundingStatus", "requiresHumanConfirmation"],
            },
        }
        messages = [
            {
                "role": "system",
                "content": "You compare LLM answers for reviewers. You must stay evidence-only and compare-only.",
            },
            {"role": "user", "content": json.dumps(compare_payload, ensure_ascii=False)},
        ]
        run["groundingStatus"] = grounding_input.get("groundingStatus")
        run["groundingInputSummary"] = grounding_input.get("summary") or {}
        run["promptAudit"] = {
            "messagesHash": stable_hash_payload(messages),
            "payloadPolicy": "compare_only_grounded_ocr_evidence",
            "messages": messages,
        }
        for model in run.get("modelCodes") or ["default-chat", "compare-fast"]:
            qwen_runtime = qwen_runtime_public_config()
            response = qwen_runtime_client().chat_sync(
                messages,
                model=model,
                temperature=0.1,
                _raw_capture_context=raw_context_from_record(
                    run,
                    run_stream_id=str(run.get("reviewRunId") or run.get("id")),
                    stage="worker_model_comparison",
                    turn=len(results) + 1,
                ),
            )
            answer = QwenRuntimeClient.first_message_text(response)
            unsupported = unsupported_claims(answer or "", [str(item) for item in grounding_input.get("evidenceTextCorpus") or []])
            result_grounding_status = "grounded" if grounding_input.get("groundingStatus") == "grounded" and not unsupported else "insufficient_evidence"
            if result_grounding_status != "grounded":
                answer = f"证据不足，以下仅作为模型回答对比参考，不能作为业务通过结论：{str(answer or '')[:1200]}"
            results.append(
                {
                    "modelCode": model,
                    "modelResolved": response.get("model") or model,
                    "qwenRuntime": qwen_runtime,
                    "answer": answer,
                    "confidence": 0.8 if result_grounding_status == "grounded" else 0.5,
                    "evidenceLinkIds": run.get("evidenceLinkIds") or [],
                    "groundingStatus": result_grounding_status,
                    "unsupportedClaims": unsupported,
                    "requiresHumanConfirmation": True,
                    "compareOnly": True,
                    "latencyMs": 0,
                }
            )
        run["results"] = results
        run["status"] = "完成"
        run["finishedAt"] = server_time()
    except Exception:
        run["status"] = "失败"
        run["errorCode"] = "EXTERNAL_TOOL_FAILED"
        run["errorMessage"] = service_failure_message("QwenRuntime 模型对比")
        run["finishedAt"] = server_time()
    flush_state()
    return {"runId": run_id, "status": run.get("status")}


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def export_package(self, export_id: str) -> dict[str, Any]:
    refresh_worker_state()
    task = repo.find_one("export_tasks", export_id)
    if not task:
        load_state()
        task = repo.find_one("export_tasks", export_id)
    if task:
        if task.get("status") == "已取消":
            flush_state()
            return {"exportId": export_id, "status": "canceled"}
        if task.get("status") == "可下载" and task.get("storageKey"):
            flush_state()
            return {"exportId": export_id, "status": "可下载", "alreadyCompleted": True}
        repo.mark_task_running(task, "导出 worker 开始处理。")
        task["progress"] = 80
        try:
            repo.attach_export_artifact(task)
        except Exception:
            repo.mark_task_failed(task, f"EXTERNAL_TOOL_FAILED: {service_failure_message('对象存储导出')}")
            flush_state()
            raise
        task["status"] = "可下载"
        task["progress"] = 100
        task["finishedAt"] = server_time()
        task["updatedAt"] = task["finishedAt"]
        repo.append_task_log(task, "info", "导出任务完成。")
    flush_state()
    return {"exportId": export_id, "status": task.get("status") if task else "missing"}


@celery_app.task(bind=True, max_retries=0)
def review_conversation_execute(
    self,
    session_id: str,
    assistant_message_id: str,
    user_text: str,
    context: dict[str, Any],
    execution_id: str,
) -> dict[str, Any]:
    """Version B 对话 Agent 的队列执行入口：在 worker 进程内运行 Agent Loop。

    上下文快照由 API 进程构建后原样传入（纯 JSON 数据）；worker 只负责执行与回填。
    不做 Celery 层自动重试：模型级有限重试已在 Loop 内部实现，任务级重复执行会
    产生重复回答。跨进程取消经 agent_executions.cancelRequested 生效。
    """
    load_state()
    # 延迟导入：避免 worker 启动即加载 API 层；对话 Agent 辅助函数目前仍在 routes.py，
    # 抽离到 libs/review_conversation/ 是后续正式工作流化的一部分。
    from apps.api import routes as api_routes

    entry: dict[str, Any] = {
        "executionId": execution_id,
        "sessionId": session_id,
        "cancelEvent": threading.Event(),
        "startedAtMonotonic": time.monotonic(),
        "startedAt": server_time(),
        "thread": None,
    }
    with api_routes.REVIEW_SESSION_EXECUTION_LOCK:
        api_routes.REVIEW_SESSION_ACTIVE_EXECUTIONS[session_id] = entry
    api_routes.run_review_conversation_execution(
        session_id=session_id,
        assistant_message_id=assistant_message_id,
        user_text=user_text,
        context=context,
        execution_entry=entry,
    )
    return {"executionId": execution_id, "sessionId": session_id}
