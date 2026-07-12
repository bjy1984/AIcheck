from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from libs.audit_context import current_request_audit_context
from libs.contracts.responses import server_time
from libs.integrations.storage import ObjectStorageUnavailable, object_storage, parse_storage_url
from libs.knowledge_indexing import (
    OFFLINE_EMBEDDING_MODEL,
    OFFLINE_VECTOR_DIMENSIONS,
    PAGE_INDEX_VERSION,
    STANDARD_INDEX_VERSION,
    build_chunks_for_file,
    build_page_index_nodes_for_source,
    build_vector_rows,
    clause_from_chunk,
    cosine_similarity,
    vector_payload_for_pg,
)
from libs.ocr_readiness import parse_result_outcome_status, parse_result_quality_blockers

from .seed import ROLE_ACTIONS, ROLE_NODE_MAP, ensure_inspection_project_members, fresh_state


STATE_COLLECTIONS = {
    "projects": "projects",
    "tree_nodes": "project_nodes",
    "requirements": "node_requirements",
    "documents": "documents",
    "versions": "document_versions",
    "bindings": "node_bindings",
    "evidence_links": "evidence_links",
    "node_evidence_links": "node_evidence_links",
    "material_targeting_runs": "material_targeting_runs",
    "extracted_fields": "extracted_fields",
    "ai_runs": "ai_runs",
    "review_runs": "review_runs",
    "review_step_runs": "review_step_runs",
    "review_graph_nodes": "review_graph_nodes",
    "review_tool_calls": "review_tool_calls",
    "review_events": "review_events",
    "retrieval_traces": "retrieval_traces",
    "rule_check_results": "rule_check_results",
    "ai_feedback": "ai_feedback",
    "access_grants": "access_grants",
    "ai_trace_steps": "ai_trace_steps",
    "ai_run_replays": "ai_run_replays",
    "feedback_triage": "feedback_triage",
    "evaluation_sets": "evaluation_sets",
    "evaluation_cases": "evaluation_cases",
    "evaluation_case_results": "evaluation_case_results",
    "evaluation_runs": "evaluation_runs",
    "evaluation_metrics": "evaluation_metrics",
    "evaluation_reports": "evaluation_reports",
    "agent_versions": "agent_versions",
    "prompt_versions": "prompt_versions",
    "prompt_templates": "prompt_templates",
    "model_route_versions": "model_route_versions",
    "ocr_profile_versions": "ocr_profile_versions",
    "ocr_jobs": "ocr_jobs",
    "ocr_parse_results": "ocr_parse_results",
    "ocr_pipeline_runs": "ocr_pipeline_runs",
    "ocr_stage_runs": "ocr_stage_runs",
    "document_ai_shadow_runs": "document_ai_shadow_runs",
    "document_audit_pipeline_comparison_runs": "document_audit_pipeline_comparison_runs",
    "model_call_attempts": "model_call_attempts",
    "ocr_corrections": "ocr_corrections",
    "ocr_eval_runs": "ocr_eval_runs",
    "ocr_annotation_tasks": "ocr_annotation_tasks",
    "ocr_annotation_imports": "ocr_annotation_imports",
    "fde_capability_test_upload_sessions": "fde_capability_test_upload_sessions",
    "fde_capability_test_runs": "fde_capability_test_runs",
    "capability_bundles": "capability_bundles",
    "release_plans": "release_plans",
    "release_approvals": "release_approvals",
    "release_gates": "release_gates",
    "incidents": "incidents",
    "incident_rca": "incident_rca",
    "business_pack_installations": "business_pack_installations",
    "business_pack_overrides": "business_pack_overrides",
    "cost_budgets": "cost_budgets",
    "cost_budget_change_requests": "cost_budget_change_requests",
    "data_exports": "data_exports",
    "masking_policies": "masking_policies",
    "delivery_acceptance_reports": "delivery_acceptance_reports",
    "review_findings": "review_findings",
    "review_opinions": "review_opinions",
    "reports": "reports",
    "archive_items": "archive_items",
    "export_tasks": "export_tasks",
    "ndt_films": "ndt_films",
    "ndt_records": "ndt_records",
    "ndt_reports": "ndt_reports",
    "ndt_feedback": "ndt_feedback",
    "todos": "todos",
    "messages": "messages",
    "knowledge_sources": "knowledge_sources",
    "knowledge_files": "knowledge_files",
    "knowledge_tasks": "knowledge_tasks",
    "knowledge_chunks": "knowledge_chunks",
    "knowledge_vectors": "knowledge_vectors",
    "knowledge_embedding_batches": "knowledge_embedding_batches",
    "knowledge_clauses": "knowledge_clauses",
    "knowledge_page_index_nodes": "knowledge_page_index_nodes",
    "knowledge_vector_corrections": "knowledge_vector_corrections",
    "knowledge_chunk_quarantines": "knowledge_chunk_quarantines",
    "rule_versions": "rule_versions",
    "llm_compare_runs": "llm_compare_runs",
    "project_members": "project_members",
    "users": "users",
    "roles": "roles",
    "business_packs": "business_packs",
    "submission_drafts": "submission_drafts",
    "submissions": "submissions",
    "rectifications": "rectifications",
    "upload_sessions": "upload_sessions",
    "audit_logs": "audit_logs",
    "operation_previews": "operation_previews",
}

SINGLETON_COLLECTIONS = {
    "admin_config": "admin_configs",
    "knowledge_config": "knowledge_configs",
}

IDEMPOTENCY_COLLECTION = "idempotency_keys"


def demo_data_enabled() -> bool:
    return os.getenv("AICHECK_ENABLE_DEMO_DATA", "false").strip().lower() == "true"


def compatibility_mock_data_enabled() -> bool:
    return os.getenv("AICHECK_ENABLE_COMPATIBILITY_MOCKS", "false").strip().lower() == "true"


def blank_state() -> dict[str, Any]:
    state = fresh_state()
    for key in STATE_COLLECTIONS:
        state[key] = []
    state["admin_config"] = {
        key: ([] if isinstance(value, list) else {})
        for key, value in state.get("admin_config", {}).items()
    }
    knowledge_config = state.get("knowledge_config", {})
    knowledge_config["updatedBy"] = "system"
    knowledge_config["updatedAt"] = None
    state["knowledge_config"] = knowledge_config
    state["idempotency"] = {}
    return state


def runtime_initial_state() -> dict[str, Any]:
    return fresh_state() if demo_data_enabled() else blank_state()


class InMemoryRepository:
    def __init__(self) -> None:
        self.state = runtime_initial_state()
        self.state.setdefault("knowledge_chunks", [])
        self.state.setdefault("knowledge_vectors", [])
        self.state.setdefault("knowledge_embedding_batches", [])
        self.state.setdefault("knowledge_clauses", [])
        self.state.setdefault("knowledge_page_index_nodes", [])
        self.state.setdefault("knowledge_vector_corrections", [])
        self.state.setdefault("knowledge_chunk_quarantines", [])
        self.state.setdefault("node_evidence_links", [])
        self.state.setdefault("material_targeting_runs", [])
        self.state.setdefault("upload_sessions", [])
        self.state.setdefault("ocr_jobs", [])
        self.state.setdefault("ocr_parse_results", [])
        self.state.setdefault("ocr_pipeline_runs", [])
        self.state.setdefault("ocr_stage_runs", [])
        self.state.setdefault("document_ai_shadow_runs", [])
        self.state.setdefault("document_audit_pipeline_comparison_runs", [])
        self.state.setdefault("model_call_attempts", [])
        self.state.setdefault("ocr_corrections", [])
        self.state.setdefault("ocr_eval_runs", [])
        self.state.setdefault("ocr_annotation_tasks", [])
        self.state.setdefault("ocr_annotation_imports", [])
        self.state.setdefault("fde_capability_test_upload_sessions", [])
        self.state.setdefault("fde_capability_test_runs", [])
        self.state.setdefault("review_runs", [])
        self.state.setdefault("operation_previews", [])
        self.state.setdefault("review_step_runs", [])
        self.state.setdefault("review_graph_nodes", [])
        self.state.setdefault("review_tool_calls", [])
        self.state.setdefault("review_events", [])
        self.state.setdefault("retrieval_traces", [])
        self.state.setdefault("rule_check_results", [])
        self.state.setdefault("prompt_templates", [])
        self.state.setdefault("cost_budget_change_requests", [])
        self.state.setdefault("masking_policies", [])
        self.postgres_dsn: str | None = None
        self.sync_postgres = None
        self.postgres_enabled = False
        self.sqlite_path: str | None = None
        self.sqlite_enabled = False
        self._flush_lock = asyncio.Lock()
        self._sync_postgres_lock = threading.RLock()

    def reset(self) -> None:
        self.state = runtime_initial_state()
        self.state.setdefault("knowledge_chunks", [])
        self.state.setdefault("knowledge_vectors", [])
        self.state.setdefault("knowledge_embedding_batches", [])
        self.state.setdefault("knowledge_clauses", [])
        self.state.setdefault("knowledge_page_index_nodes", [])
        self.state.setdefault("knowledge_vector_corrections", [])
        self.state.setdefault("knowledge_chunk_quarantines", [])
        self.state.setdefault("node_evidence_links", [])
        self.state.setdefault("material_targeting_runs", [])
        self.state.setdefault("upload_sessions", [])
        self.state.setdefault("ocr_jobs", [])
        self.state.setdefault("ocr_parse_results", [])
        self.state.setdefault("ocr_pipeline_runs", [])
        self.state.setdefault("ocr_stage_runs", [])
        self.state.setdefault("document_ai_shadow_runs", [])
        self.state.setdefault("document_audit_pipeline_comparison_runs", [])
        self.state.setdefault("model_call_attempts", [])
        self.state.setdefault("ocr_corrections", [])
        self.state.setdefault("ocr_eval_runs", [])
        self.state.setdefault("ocr_annotation_tasks", [])
        self.state.setdefault("ocr_annotation_imports", [])
        self.state.setdefault("fde_capability_test_upload_sessions", [])
        self.state.setdefault("fde_capability_test_runs", [])
        self.state.setdefault("review_runs", [])
        self.state.setdefault("review_step_runs", [])
        self.state.setdefault("review_graph_nodes", [])
        self.state.setdefault("review_tool_calls", [])
        self.state.setdefault("review_events", [])
        self.state.setdefault("retrieval_traces", [])
        self.state.setdefault("rule_check_results", [])
        self.state.setdefault("prompt_templates", [])
        self.state.setdefault("cost_budget_change_requests", [])
        self.state.setdefault("masking_policies", [])

    def clone(self, value: Any) -> Any:
        return deepcopy(value)

    def list(self, collection: str) -> list[dict[str, Any]]:
        return self.state[collection]

    def find_one(self, collection: str, object_id: str, id_field: str = "id") -> dict[str, Any] | None:
        return next((item for item in self.state[collection] if item.get(id_field) == object_id), None)

    def require_project(self, project_id: str) -> dict[str, Any] | None:
        return self.find_one("projects", project_id)

    def role_actions(self, role: str) -> list[str]:
        return list(ROLE_ACTIONS.get(role, ROLE_ACTIONS["inspection"]))

    def role_current_node_id(self, project: dict[str, Any], role: str) -> int:
        project_id = project.get("id")
        node_ids = {
            int(node["nodeId"])
            for node in self.state.get("tree_nodes", [])
            if node.get("projectId") == project_id and node.get("nodeId") is not None
        }
        role_node_id = ROLE_NODE_MAP.get(role)
        if role_node_id is not None and (not node_ids or int(role_node_id) in node_ids):
            return int(role_node_id)
        if project.get("currentNodeId") is not None:
            return int(project["currentNodeId"])
        if node_ids:
            return sorted(node_ids)[0]
        return int(ROLE_NODE_MAP.get("inspection", 24))

    def project_for_role(self, project: dict[str, Any], role: str) -> dict[str, Any]:
        cloned = self.clone(project)
        cloned["currentNodeId"] = self.role_current_node_id(project, role)
        cloned["riskLevel"] = self.project_risk_level(project["id"])
        if project.get("status") == "已归档":
            cloned["actions"] = ["project:view", "archive:view", "archive:download"]
        else:
            cloned["actions"] = self.role_actions(role)
        return cloned

    def project_risk_level(self, project_id: str) -> str:
        if any(item.get("projectId") == project_id and item.get("status") == "失败" for item in self.state["ai_runs"]):
            return "高"
        if any(item.get("projectId") == project_id and item.get("status") == "失败" for item in self.state["export_tasks"]):
            return "高"
        failed_knowledge_task_project_ids = {
            (self.find_one("knowledge_files", item.get("targetId")) or {}).get("projectId")
            for item in self.state["knowledge_tasks"]
            if item.get("status") == "失败"
        }
        if project_id in failed_knowledge_task_project_ids:
            return "高"
        project_nodes = [item for item in self.state["tree_nodes"] if item.get("projectId") == project_id]
        risky_statuses = {"需补正", "退回补正中", "识别失败", "失败"}
        if any(item.get("status") in risky_statuses for item in project_nodes):
            return "高"
        if any(item.get("projectId") == project_id and item.get("status") == "待反馈" for item in self.state["rectifications"]):
            return "高"
        if any(item.get("projectId") == project_id and item.get("status") == "待反馈" for item in self.state["ndt_feedback"]):
            return "高"
        pending_statuses = {"待提交", "待审查", "AI 预审中", "复审中", "报告生成/复核中", "部分提交"}
        if any(item.get("status") in pending_statuses for item in project_nodes):
            return "中"
        project = self.require_project(project_id)
        if project and (int(project.get("todoCount") or 0) > 0 or int(project.get("messageCount") or 0) > 0):
            return "中"
        return "低"

    def node(self, project_id: str, node_id: int) -> dict[str, Any] | None:
        return next(
            (
                node
                for node in self.state["tree_nodes"]
                if node["projectId"] == project_id and int(node["nodeId"]) == int(node_id)
            ),
            None,
        )

    def node_groups(self, project_id: str) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        project_nodes = sorted(
            [item for item in self.state["tree_nodes"] if item["projectId"] == project_id],
            key=lambda item: int(item.get("nodeId") or 0),
        )
        for node in project_nodes:
            group = next((item for item in groups if item["groupName"] == node["groupName"]), None)
            if not group:
                group = {"groupName": node["groupName"], "nodes": []}
                groups.append(group)
            group["nodes"].append(self.clone(node))
        return groups

    def project_documents(self, project_id: str) -> list[dict[str, Any]]:
        documents = []
        for item in self.state["documents"]:
            if item["projectId"] != project_id:
                continue
            cloned = self.clone(item)
            knowledge_file = next(
                (
                    file
                    for file in self.state.get("knowledge_files", [])
                    if file.get("documentId") == item.get("id")
                    or file.get("documentVersionId") == item.get("currentVersionId")
                ),
                None,
            )
            if knowledge_file:
                cloned["sliceStatus"] = knowledge_file.get("sliceStatus")
                cloned["vectorStatus"] = knowledge_file.get("vectorStatus")
                cloned["chunkCount"] = knowledge_file.get("chunkCount", 0)
                cloned["vectorCount"] = knowledge_file.get("vectorCount", 0)
                cloned["embeddingModel"] = knowledge_file.get("embeddingModel")
            documents.append(cloned)
        return documents

    def versions_for_document(self, document_id: str) -> list[dict[str, Any]]:
        return [self.clone(item) for item in self.state["versions"] if item["documentId"] == document_id]

    def current_version(self, document_id: str) -> dict[str, Any] | None:
        return next((item for item in self.versions_for_document(document_id) if item.get("isCurrent")), None)

    def bindings_for_node(self, project_id: str, node_id: int) -> list[dict[str, Any]]:
        return [
            self.clone(item)
            for item in self.state["bindings"]
            if item["projectId"] == project_id and int(item["nodeId"]) == int(node_id)
        ]

    def bindings_for_project(self, project_id: str) -> list[dict[str, Any]]:
        return [self.clone(item) for item in self.state["bindings"] if item["projectId"] == project_id]

    def fields_for_versions(self, version_ids: set[str]) -> list[dict[str, Any]]:
        return [
            self.clone(item)
            for item in self.state["extracted_fields"]
            if item["documentVersionId"] in version_ids
        ]

    def evidence_for_versions(self, version_ids: set[str]) -> list[dict[str, Any]]:
        return [
            self.clone(item)
            for item in self.state["evidence_links"]
            if item.get("documentVersionId") in version_ids or item.get("objectId") in version_ids
        ]

    def add_audit(self, action: str, object_type: str, object_id: str, result: str = "成功") -> str:
        audit_id = f"AUD-{uuid4().hex[:10].upper()}"
        actor = current_request_audit_context()
        self.state["audit_logs"].insert(
            0,
            {
                "id": audit_id,
                "actorId": actor.get("actorId") or "system",
                "actorName": actor.get("actorName") or "系统",
                "actorOrgName": actor.get("actorOrgName"),
                "operationId": actor.get("operationId"),
                "action": action,
                "objectType": object_type,
                "objectId": object_id,
                "result": result,
                "createdAt": server_time(),
            },
        )
        return audit_id

    def mutation_result(
        self,
        action: str,
        object_type: str,
        object_id: str,
        *,
        next_status: str | None = None,
        changed: list[dict[str, Any]] | None = None,
        affected_ids: list[str] | None = None,
        todo_delta: int = 0,
        message_delta: int = 0,
    ) -> dict[str, Any]:
        audit_id = self.add_audit(action, object_type, object_id)
        return {
            "id": f"MUT-{uuid4().hex[:10].upper()}",
            "objectType": object_type,
            "objectId": object_id,
            "nextStatus": next_status,
            "changed": changed or [],
            "todoDelta": todo_delta,
            "messageDelta": message_delta,
            "auditLogId": audit_id,
            "affectedIds": affected_ids or [object_id],
        }

    def set_node_status(self, project_id: str, node_id: int, status: str) -> dict[str, Any]:
        node = self.node(project_id, node_id)
        before = node.get("status") if node else None
        if node is not None:
            node["status"] = status
            node["revision"] = int(node.get("revision", 1)) + 1
        return {"field": f"nodes.{node_id}.status", "before": before, "after": status}

    def touch_project(self, project_id: str, status: str | None = None, current_node_id: int | None = None) -> None:
        project = self.require_project(project_id)
        if not project:
            return
        if status:
            project["status"] = status
        if current_node_id:
            project["currentNodeId"] = current_node_id
        project["updatedAt"] = server_time()
        project["revision"] = int(project.get("revision", 1)) + 1

    def signed_get(self, file_name: str, url: str, content_type: str | None = None, file_size: int | None = None) -> dict[str, Any]:
        if str(url or "").startswith("mock://") and not compatibility_mock_data_enabled():
            raise ObjectStorageUnavailable("模拟文件地址已禁用，且没有可用的真实文件产物。")
        signed_url = object_storage.presigned_get_url(url, file_name=file_name)
        if not signed_url and object_storage.required and (parse_storage_url(url) or str(url).startswith("mock://")):
            raise ObjectStorageUnavailable("Object storage is required in production but signed GET could not be created.")
        payload = {
            "url": signed_url or url,
            "method": "GET",
            "expiresAt": object_storage.expires_at(),
            "fileName": file_name,
        }
        if content_type:
            payload["contentType"] = content_type
        if file_size:
            payload["fileSize"] = file_size
        return payload

    def signed_put(
        self,
        bucket: str,
        object_name: str,
        fallback_url: str,
        *,
        content_type: str | None = None,
        require_signed: bool = False,
    ) -> str:
        signed_url = object_storage.presigned_put_url(bucket, object_name, content_type=content_type)
        if signed_url:
            return signed_url
        if object_storage.required:
            raise ObjectStorageUnavailable("对象存储不可用，无法生成真实上传地址。")
        if require_signed and str(fallback_url or "").startswith("mock://"):
            raise ObjectStorageUnavailable("对象存储不可用，无法生成真实上传地址。")
        return fallback_url

    def document_storage_url(self, document: dict[str, Any], *, fallback_prefix: str) -> str:
        version = self.current_version(document["id"])
        bucket = (version or {}).get("storageBucket")
        storage_key = (version or {}).get("storageKey")
        if isinstance(storage_key, str) and parse_storage_url(storage_key):
            return storage_key
        if isinstance(storage_key, str) and storage_key.startswith("mock://"):
            if not compatibility_mock_data_enabled():
                raise ObjectStorageUnavailable("资料只有模拟存储地址，不能用于正式预览或下载。")
            return storage_key
        if isinstance(storage_key, str) and storage_key.startswith(("local://", "http://", "https://")):
            return storage_key
        if bucket and storage_key:
            return f"minio://{bucket}/{storage_key}"
        if object_storage.required:
            raise ObjectStorageUnavailable("Object storage is required in production but the document has no storage object.")
        if compatibility_mock_data_enabled():
            return f"mock://{fallback_prefix}/documents/{document['id']}?versionId={document.get('currentVersionId')}"
        raise ObjectStorageUnavailable("资料尚未绑定可用的真实存储对象。")

    def document_content_type(self, document: dict[str, Any]) -> str | None:
        raw_type = str(document.get("fileType") or "").lower()
        if "/" in raw_type:
            return raw_type
        suffix = raw_type or str(document.get("fileName") or "").rsplit(".", 1)[-1].lower()
        content_types = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "bmp": "image/bmp",
            "heic": "image/heic",
            "heif": "image/heif",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        return content_types.get(suffix)

    def document_preview_type(self, document: dict[str, Any]) -> str:
        raw_type = str(document.get("fileType") or "").lower()
        file_name = str(document.get("fileName") or "").lower()
        suffix = file_name.rsplit(".", 1)[-1] if "." in file_name else raw_type
        if raw_type == "application/pdf" or suffix == "pdf":
            return "pdf"
        if raw_type.startswith("image/") or suffix in {"png", "jpg", "jpeg", "webp", "bmp", "heic", "heif"}:
            return "image"
        if suffix in {"xlsx", "docx"}:
            return "office"
        return "unsupported"

    def document_preview(self, document: dict[str, Any]) -> dict[str, Any]:
        preview_type = self.document_preview_type(document)
        return {
            **self.document_signed_get(document, fallback_prefix="preview"),
            "previewType": preview_type,
            "readonly": True,
            "pageCount": 3 if preview_type == "pdf" else None,
        }

    def document_download(self, document: dict[str, Any]) -> dict[str, Any]:
        return self.document_signed_get(document, fallback_prefix="download")

    def document_signed_get(self, document: dict[str, Any], *, fallback_prefix: str) -> dict[str, Any]:
        content_type = self.document_content_type(document)
        version = self.current_version(document["id"]) or {}
        primary = self.signed_get(
            document["fileName"],
            self.document_storage_url(document, fallback_prefix=fallback_prefix),
            content_type,
            file_size=int(version.get("fileSize") or 0) or None,
        )
        if not str(primary.get("url") or "").startswith("minio://"):
            return primary
        if not compatibility_mock_data_enabled():
            raise ObjectStorageUnavailable("对象存储未返回可访问的签名地址。")
        return self.signed_get(
            document["fileName"],
            f"mock://{fallback_prefix}/documents/{document['id']}?versionId={document.get('currentVersionId')}",
            content_type,
            file_size=int(version.get("fileSize") or 0) or None,
        )

    def create_document(
        self,
        project_id: str,
        file_name: str,
        file_type: str,
        *,
        source_org_name: str | None = None,
        uploader_name: str | None = None,
        material_category: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        doc, version, knowledge_file, knowledge_task = self._build_document_records(
            project_id,
            file_name,
            file_type,
            source_org_name=source_org_name,
            uploader_name=uploader_name,
            material_category=material_category,
        )
        self._insert_document_records(doc, version, knowledge_file, knowledge_task)
        return doc, version

    def _build_document_records(
        self,
        project_id: str,
        file_name: str,
        file_type: str,
        *,
        source_org_name: str | None = None,
        uploader_name: str | None = None,
        material_category: str | None = None,
        file_size: int = 0,
        content_hash: str | None = None,
        seed: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        seed = seed or uuid4().hex[:8].upper()
        document_id = f"DOC-{seed}"
        version_id = f"DV-{seed}-V1"
        now = server_time()
        project = self.require_project(project_id)
        resolved_source_org_name = source_org_name or (project or {}).get("contractorOrgName") or "项目参建单位"
        resolved_uploader_name = uploader_name or "系统"
        resolved_material_category = str(material_category or "").strip()
        doc = {
            "id": document_id,
            "projectId": project_id,
            "businessPackId": (project or {}).get("businessPackId"),
            "materialTypeCode": "generic_review_material",
            "materialCategory": resolved_material_category or None,
            "fileName": file_name,
            "fileType": file_type or file_name.split(".")[-1],
            "sourceOrgName": resolved_source_org_name,
            "uploaderName": resolved_uploader_name,
            "currentVersionId": version_id,
            "fileStatus": "已上传",
            "currentOcrStatus": "排队中",
            "updatedAt": now,
            "actions": ["file:view", "file:bind", "file:preview", "file:download"],
        }
        version = {
            "id": version_id,
            "documentId": document_id,
            "versionNo": "V1",
            "hash": content_hash,
            "fileSize": max(0, int(file_size or 0)),
            "storageKey": f"documents/{project_id}/{version_id}",
            "storageBucket": "documents",
            "ocrStatus": "排队中",
            "sliceStatus": "未切片",
            "vectorStatus": "未向量化",
            "uploaderName": resolved_uploader_name,
            "uploadTime": now,
            "isCurrent": True,
        }
        knowledge_file = {
            "id": f"KF-{document_id}",
            "fileName": file_name,
            "sourceId": "KS-PROJECT-FILE",
            "sourceName": "项目文件知识库",
            "projectId": project_id,
            "projectName": project.get("name") if project else "",
            "documentId": document_id,
            "documentVersionId": version_id,
            "materialCategory": resolved_material_category or None,
            "ocrStatus": "排队中",
            "sliceStatus": "未切片",
            "vectorStatus": "待向量化",
            "chunkCount": 0,
            "vectorCount": 0,
            "updatedAt": now,
            "actions": ["knowledge:view", "knowledge:reindex"],
        }
        knowledge_task = {
            "id": f"KT-{seed}",
            "taskType": "ocr",
            "targetType": "file",
            "targetId": knowledge_file["id"],
            "targetName": file_name,
            "documentId": document_id,
            "documentVersionId": version_id,
            "status": "排队中",
            "progress": 0,
            "createdAt": now,
            "actions": ["knowledge:task-retry"],
        }
        return doc, version, knowledge_file, knowledge_task

    def _insert_document_records(
        self,
        doc: dict[str, Any],
        version: dict[str, Any],
        knowledge_file: dict[str, Any],
        knowledge_task: dict[str, Any],
    ) -> None:
        self.state["documents"].insert(0, doc)
        self.state["versions"].insert(0, version)
        self.state["knowledge_files"].insert(0, knowledge_file)
        self.state["knowledge_tasks"].insert(0, knowledge_task)

    def create_upload_session(
        self,
        project_id: str,
        files: list[dict[str, Any]],
        *,
        require_signed_urls: bool = False,
        local_upload_url_prefix: str | None = None,
        upload_headers: dict[str, str] | None = None,
        source_org_name: str | None = None,
        uploader_name: str | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        session_id = f"UPS-{uuid4().hex[:10].upper()}"
        upload_token = uuid4().hex
        upload_urls = []
        session_files = []
        pending_records: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        for file in files:
            doc, version, knowledge_file, knowledge_task = self._build_document_records(
                project_id,
                file.get("fileName") or "未命名资料.pdf",
                file.get("fileType") or "pdf",
                source_org_name=source_org_name,
                uploader_name=uploader_name,
                material_category=file.get("materialCategory"),
                file_size=int(file.get("fileSize") or 0),
                content_hash=str(file.get("contentHash") or "").strip() or None,
            )
            content_type = file.get("fileType") or "application/octet-stream"
            fallback_url = f"mock://upload/{session_id}/{doc['id']}"
            local_upload = False
            if local_upload_url_prefix and not object_storage.required:
                fallback_url = f"{local_upload_url_prefix.rstrip('/')}/{session_id}/files/{version['id']}"
                local_upload = True
            # signed_put wraps object_storage.presigned_put_url and enforces production storage.
            upload_url = self.signed_put(
                "documents",
                version["storageKey"],
                fallback_url,
                content_type=content_type,
                require_signed=require_signed_urls,
            )
            headers = {"Content-Type": content_type}
            if local_upload and upload_url == fallback_url:
                headers.update(upload_headers or {})
                headers["X-Upload-Session-Token"] = upload_token
            upload_urls.append(
                {
                    "fileName": doc["fileName"],
                    "materialCategory": doc.get("materialCategory"),
                    "documentId": doc["id"],
                    "documentVersionId": version["id"],
                    "url": upload_url,
                    "method": "PUT",
                    "expiresAt": object_storage.expires_at(),
                    "headers": headers,
                }
            )
            session_files.append(
                {
                    "documentId": doc["id"],
                    "documentVersionId": version["id"],
                    "fileName": doc["fileName"],
                    "materialCategory": doc.get("materialCategory"),
                    "storageBucket": "documents",
                    "storageKey": version["storageKey"],
                    "status": "待上传",
                }
            )
            pending_records.append((doc, version, knowledge_file, knowledge_task))
        for records in pending_records:
            self._insert_document_records(*records)
        self.state["upload_sessions"].insert(
            0,
            {
                "id": session_id,
                "projectId": project_id,
                "status": "待上传",
                "files": session_files,
                "uploadToken": upload_token,
                "createdAt": server_time(),
                "expiresAt": object_storage.expires_at(),
            },
        )
        return session_id, upload_urls

    def complete_upload_session(self, session_id: str) -> list[dict[str, Any]]:
        session = self.find_one("upload_sessions", session_id)
        if not session:
            return []
        session["status"] = "已完成"
        session["completedAt"] = server_time()
        return self.clone(session.get("files") or [])

    def upload_session_files(self, session_id: str) -> list[dict[str, Any]]:
        session = self.find_one("upload_sessions", session_id)
        return self.clone(session.get("files") or []) if session else []

    def upsert_knowledge_task(
        self,
        *,
        task_type: str,
        target_id: str,
        target_name: str,
        document_id: str | None = None,
        version_id: str | None = None,
        status: str = "排队中",
        progress: int = 0,
    ) -> dict[str, Any]:
        existing = next(
            (
                item
                for item in self.state["knowledge_tasks"]
                if item.get("taskType") == task_type and item.get("targetId") == target_id
            ),
            None,
        )
        if existing:
            existing.update({"status": status, "progress": progress, "updatedAt": server_time()})
            self._bump_revision(existing)
            return existing
        seed = uuid4().hex[:8].upper()
        now = server_time()
        task = {
            "id": f"KT-{seed}",
            "taskType": task_type,
            "targetType": "file",
            "targetId": target_id,
            "targetName": target_name,
            "documentId": document_id,
            "documentVersionId": version_id,
            "status": status,
            "progress": progress,
            "createdAt": now,
            "updatedAt": now,
            "revision": 1,
            "actions": ["knowledge:task-retry"],
        }
        self.state["knowledge_tasks"].insert(0, task)
        return task

    def _bump_revision(self, item: dict[str, Any]) -> None:
        item["revision"] = int(item.get("revision") or 1) + 1

    def append_task_log(self, task: dict[str, Any], level: str, message: str) -> dict[str, Any]:
        entry = {"createdAt": server_time(), "level": level, "message": message}
        task.setdefault("logs", []).append(entry)
        return entry

    def ocr_task_for(self, document_id: str, version_id: str, file_name: str | None = None) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in self.state["knowledge_tasks"]
                if item.get("taskType") == "ocr"
                and (
                    item.get("documentVersionId") == version_id
                    or item.get("targetId") == f"KF-{document_id}"
                    or (file_name and item.get("targetName") == file_name)
                )
            ),
            None,
        )

    def knowledge_file_for_version(self, version_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self.state.get("knowledge_files", []) if item.get("documentVersionId") == version_id),
            None,
        )

    def mark_task_running(self, task: dict[str, Any] | None, message: str) -> None:
        if not task:
            return
        task["status"] = "运行中"
        task["progress"] = max(int(task.get("progress") or 0), 10)
        task["startedAt"] = server_time()
        task["updatedAt"] = task["startedAt"]
        self._bump_revision(task)
        self.append_task_log(task, "info", message)

    def mark_task_failed(self, task: dict[str, Any] | None, message: str) -> None:
        if not task:
            return
        task["status"] = "失败"
        task["errorMessage"] = message
        task["finishedAt"] = server_time()
        task["updatedAt"] = task["finishedAt"]
        self._bump_revision(task)
        self.append_task_log(task, "error", message)

    def create_or_resume_ocr_pipeline_run(
        self,
        *,
        run_key: str,
        document_id: str,
        version_id: str,
        storage_key: str,
        storage_bucket: str | None,
        file_name: str | None,
        profile_id: str | None,
        document_type: str | None,
        mode: str,
        pipeline_version: str,
        project_id: str | None = None,
        operation_id: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        from libs.ocr_accuracy_pipeline import initial_stage_records

        existing = next(
            (
                item
                for item in self.state.setdefault("ocr_pipeline_runs", [])
                if item.get("runKey") == run_key and item.get("status") not in {"canceled"}
            ),
            None,
        )
        now = server_time()
        if existing:
            existing_stages = [
                stage
                for stage in self.state.setdefault("ocr_stage_runs", [])
                if stage.get("pipelineRunId") == existing.get("id")
            ]
            if not existing_stages:
                existing_stages = initial_stage_records(
                    str(existing.get("id") or ""),
                    now=now,
                    document_id=document_id,
                    version_id=version_id,
                )
                self.state["ocr_stage_runs"].extend(existing_stages)
            for stage in existing_stages:
                stage.setdefault("documentId", document_id)
                stage.setdefault("documentVersionId", version_id)
            if existing.get("status") in {"failed", "partial"}:
                existing.update(
                    {
                        "status": "queued",
                        "currentStage": "prepare",
                        "progress": 0,
                        "finishedAt": None,
                        "failureReason": None,
                        "blockingReasons": [],
                        "recommendedAction": None,
                        "formalEvidenceReady": False,
                        "updatedAt": now,
                    }
                )
                for stage in self.state.setdefault("ocr_stage_runs", []):
                    if stage.get("pipelineRunId") == existing.get("id") and stage.get("status") in {
                        "failed",
                        "retrying",
                        "blocked",
                    }:
                        stage.update(
                            {
                                "status": "queued",
                                "startedAt": None,
                                "finishedAt": None,
                                "failureReason": None,
                                "blockingReasons": [],
                                "updatedAt": now,
                            }
                        )
            existing["taskId"] = task_id or existing.get("taskId")
            existing["operationId"] = operation_id or existing.get("operationId")
            existing["updatedAt"] = now
            return existing
        run_id = f"OCRPIPE-{uuid4().hex[:12].upper()}"
        run = {
            "id": run_id,
            "pipelineRunId": run_id,
            "runKey": run_key,
            "pipelineVersion": pipeline_version,
            "mode": mode,
            "status": "queued",
            "currentStage": "prepare",
            "progress": 0,
            "documentId": document_id,
            "documentVersionId": version_id,
            "projectId": project_id,
            "storageKey": storage_key,
            "storageBucket": storage_bucket,
            "fileName": file_name,
            "profileId": profile_id,
            "documentType": document_type,
            "operationId": operation_id,
            "taskId": task_id,
            "ocrJobRecordId": None,
            "parseResultId": None,
            "baselineParseResultId": None,
            "qwenModel": None,
            "qwenProvider": None,
            "qwenUsage": {},
            "qwenBatchCount": 0,
            "groundingValidation": {},
            "artifactUrls": {},
            "blockingReasons": [],
            "recommendedAction": None,
            "formalEvidenceReady": False,
            "advisoryOnly": mode != "active",
            "attempt": 0,
            "createdAt": now,
            "updatedAt": now,
            "startedAt": None,
            "finishedAt": None,
            "failureReason": None,
        }
        self.state["ocr_pipeline_runs"].insert(0, run)
        self.state.setdefault("ocr_stage_runs", []).extend(
            initial_stage_records(
                run_id,
                now=now,
                document_id=document_id,
                version_id=version_id,
            )
        )
        return run

    def ocr_pipeline_stages(self, run_id: str) -> list[dict[str, Any]]:
        from libs.ocr_accuracy_pipeline import PIPELINE_STAGE_PROGRESS

        return sorted(
            [item for item in self.state.setdefault("ocr_stage_runs", []) if item.get("pipelineRunId") == run_id],
            key=lambda item: PIPELINE_STAGE_PROGRESS.get(str(item.get("stage") or ""), 999),
        )

    def mark_ocr_pipeline_stage(
        self,
        run: dict[str, Any] | None,
        stage_name: str,
        status: str,
        *,
        engine_status: dict[str, Any] | None = None,
        blocking_reasons: list[dict[str, Any]] | None = None,
        artifact_url: str | None = None,
        artifact_hash: str | None = None,
        failure_reason: str | None = None,
    ) -> dict[str, Any] | None:
        if not run:
            return None
        from libs.ocr_accuracy_pipeline import PIPELINE_STAGE_PROGRESS

        now = server_time()
        stage = next(
            (
                item
                for item in self.state.setdefault("ocr_stage_runs", [])
                if item.get("pipelineRunId") == run.get("id") and item.get("stage") == stage_name
            ),
            None,
        )
        if stage is None:
            return None
        stage["status"] = status
        stage["updatedAt"] = now
        if status in {"running", "retrying"}:
            stage["startedAt"] = stage.get("startedAt") or now
            if status == "running":
                stage["attempt"] = int(stage.get("attempt") or 0) + 1
        if status in {"success", "failed", "skipped", "blocked", "partial"}:
            stage["finishedAt"] = now
            if stage.get("startedAt"):
                try:
                    started_at = datetime.strptime(str(stage["startedAt"]), "%Y-%m-%d %H:%M:%S")
                    finished_at = datetime.strptime(now, "%Y-%m-%d %H:%M:%S")
                    stage["elapsedSeconds"] = max(0, round((finished_at - started_at).total_seconds(), 3))
                except ValueError:
                    stage["elapsedSeconds"] = None
        if engine_status is not None:
            stage["engineStatus"] = self.clone(engine_status)
        if blocking_reasons is not None:
            stage["blockingReasons"] = self.clone(blocking_reasons)
        if artifact_url is not None:
            stage["artifactUrl"] = artifact_url
        if artifact_hash is not None:
            stage["artifactHash"] = artifact_hash
        if failure_reason is not None:
            stage["failureReason"] = failure_reason
        run["currentStage"] = stage_name
        run["updatedAt"] = now
        if status == "running":
            run["status"] = "running"
            run["startedAt"] = run.get("startedAt") or now
            run["attempt"] = max(int(run.get("attempt") or 0), int(stage.get("attempt") or 0))
        if status == "retrying":
            run["status"] = "queued"
        if status in {"success", "skipped", "partial"}:
            run["progress"] = max(int(run.get("progress") or 0), int(PIPELINE_STAGE_PROGRESS.get(stage_name, 0)))
        if status in {"failed", "blocked"}:
            run["status"] = "failed" if status == "failed" else "partial"
            run["failureReason"] = failure_reason
        return stage

    def finish_ocr_pipeline_run(
        self,
        run: dict[str, Any] | None,
        *,
        status: str,
        blocking_reasons: list[dict[str, Any]] | None = None,
        recommended_action: str | None = None,
        formal_evidence_ready: bool = False,
    ) -> dict[str, Any] | None:
        if not run:
            return None
        now = server_time()
        run.update(
            {
                "status": status,
                "progress": 100 if status == "completed" else int(run.get("progress") or 0),
                "blockingReasons": self.clone(blocking_reasons or []),
                "recommendedAction": recommended_action,
                "formalEvidenceReady": bool(formal_evidence_ready),
                "finishedAt": now,
                "updatedAt": now,
            }
        )
        return run

    def create_ocr_job_record(
        self,
        *,
        document_id: str,
        version_id: str,
        storage_key: str,
        file_name: str | None = None,
        profile_id: str | None = None,
        document_type: str | None = None,
        record_id: str | None = None,
    ) -> dict[str, Any]:
        if record_id:
            existing = self.find_one("ocr_jobs", record_id)
            if existing:
                return existing
        now = server_time()
        job = {
            "id": record_id or f"OCRJOB-BIZ-{uuid4().hex[:10].upper()}",
            "jobId": None,
            "documentId": document_id,
            "documentVersionId": version_id,
            "storageKey": storage_key,
            "fileName": file_name,
            "profileId": profile_id,
            "documentType": document_type,
            "status": "queued",
            "createdAt": now,
            "startedAt": None,
            "updatedAt": now,
            "finishedAt": None,
            "parseResultId": None,
            "engineRuns": [],
            "diagnostics": [],
            "resultSummary": {},
            "retryOfJobId": None,
            "immutable": True,
        }
        self.state.setdefault("ocr_jobs", []).insert(0, job)
        return job

    def mark_ocr_job_running(self, job: dict[str, Any] | None, *, pipeline_run_id: str | None = None) -> None:
        if not job:
            return
        now = server_time()
        job["status"] = "running"
        job["startedAt"] = job.get("startedAt") or now
        job["updatedAt"] = now
        if pipeline_run_id:
            job["pipelineRunId"] = pipeline_run_id

    def finish_ocr_job_record(self, job: dict[str, Any] | None, result: dict[str, Any]) -> dict[str, Any] | None:
        if not job:
            return None
        now = server_time()
        parse_result_id = result.get("parseResultId") or f"PARSE-{uuid4().hex[:12].upper()}"
        result_record = {
            "id": parse_result_id,
            "parseResultId": parse_result_id,
            "jobRecordId": job.get("id"),
            "externalJobId": result.get("jobId") or result.get("externalJobId") or job.get("jobId"),
            "documentId": job.get("documentId"),
            "documentVersionId": job.get("documentVersionId"),
            "storageKey": result.get("storageKey") or job.get("storageKey"),
            "fileName": result.get("fileName") or job.get("fileName"),
            "status": result.get("status") or "failed",
            "profileId": result.get("profileId") or job.get("profileId"),
            "documentType": result.get("documentType") or job.get("documentType"),
            "parserVersion": result.get("parserVersion"),
            "engineVersion": result.get("engineVersion"),
            "modelManifest": result.get("modelManifest") or {},
            "engineRuns": result.get("engineRuns") or [],
            "diagnostics": result.get("diagnostics") or [],
            "pages": result.get("pages") or [],
            "fragments": result.get("fragments") or [],
            "layoutBlocks": result.get("layoutBlocks") or [],
            "tables": result.get("tables") or [],
            "seals": result.get("seals") or [],
            "fields": result.get("fields") or [],
            "quality": result.get("quality") or {},
            "inputHash": stable_doc_id(str(result.get("storageKey") or job.get("storageKey") or "")),
            "outputHash": stable_doc_id(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str)),
            "createdAt": result.get("createdAt") or now,
            "finishedAt": now,
            "immutable": True,
        }
        parse_results = self.state.setdefault("ocr_parse_results", [])
        existing_index = next(
            (
                index
                for index, item in enumerate(parse_results)
                if str(item.get("parseResultId") or item.get("id") or "") == str(parse_result_id)
            ),
            None,
        )
        if existing_index is None:
            parse_results.insert(0, result_record)
        else:
            parse_results[existing_index] = result_record
        job["jobId"] = result_record["externalJobId"]
        job["status"] = "success" if result_record["status"] == "success" else "failed"
        job["parseResultId"] = parse_result_id
        job["finishedAt"] = now
        job["updatedAt"] = now
        job["engineRuns"] = result_record["engineRuns"]
        job["diagnostics"] = result_record["diagnostics"]
        job["resultSummary"] = {
            "fieldCount": len(result_record["fields"]),
            "fragmentCount": len(result_record["fragments"]),
            "tableCount": len(result_record["tables"]),
            "sealCount": len(result_record["seals"]),
        }
        return result_record

    def create_ocr_correction(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = server_time()
        field = self.find_one("extracted_fields", str(payload.get("fieldId") or ""))
        before = self.clone(field) if field else None
        if field:
            if "correctedValue" in payload:
                field["fieldValue"] = str(payload["correctedValue"])
            if payload.get("correctedBbox") is not None:
                field["bbox"] = payload["correctedBbox"]
            field["reviewStatus"] = "已修正"
            field["correctedAt"] = now
            field["correctionReason"] = payload.get("reason") or "FDE OCR 纠错"
        correction = {
            "id": payload.get("id") or f"OCRC-{uuid4().hex[:8].upper()}",
            "fieldId": payload.get("fieldId"),
            "documentVersionId": payload.get("documentVersionId") or (field or {}).get("documentVersionId"),
            "targetType": payload.get("targetType") or "field",
            "correctionType": payload.get("correctionType") or "field_value",
            "before": before,
            "after": self.clone(field) if field else payload.get("after"),
            "reason": payload.get("reason") or "FDE OCR 纠错",
            "shouldEnterEvaluationSet": bool(payload.get("shouldEnterEvaluationSet", True)),
            "createdByRole": payload.get("createdByRole") or "fde",
            "createdAt": now,
        }
        self.state.setdefault("ocr_corrections", []).insert(0, correction)
        return correction

    def create_ocr_eval_run(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        now = server_time()
        results = self.state.get("ocr_parse_results", [])
        corrections = self.state.get("ocr_corrections", [])
        fields = [field for result in results for field in result.get("fields", []) if isinstance(field, dict)]
        tables = [table for result in results for table in result.get("tables", []) if isinstance(table, dict)]
        seals = [seal for result in results for seal in result.get("seals", []) if isinstance(seal, dict)]
        low_conf = [field for field in fields if float(field.get("confidence") if field.get("confidence") is not None else 0) < 0.85]
        total_results = len(results) or 1
        success_count = len([item for item in results if item.get("status") == "success"])
        case_count = payload.get("caseCount")
        metrics = {
            "fileSuccessRate": round(success_count / total_results, 4),
            "fieldAccuracyProxy": round(1 - (len(low_conf) / (len(fields) or 1)), 4),
            "tableStructureUsableRate": round(len([item for item in tables if float(item.get("structureConfidence") or 0) >= 0.8]) / (len(tables) or 1), 4),
            "sealDetectionProxy": round(len(seals) / (len(results) or 1), 4),
            "manualCorrectionRate": round(len(corrections) / (len(fields) or 1), 4),
            "caseCount": int(case_count if case_count is not None else len(results)),
        }
        run = {
            "id": payload.get("id") or f"OCREVAL-{uuid4().hex[:8].upper()}",
            "profileId": payload.get("profileId") or "all",
            "status": "completed",
            "startedAt": now,
            "finishedAt": now,
            "metrics": metrics,
            "gateResults": [
                {"gate": "file_success", "passed": metrics["fileSuccessRate"] >= 0.95},
                {"gate": "field_accuracy_proxy", "passed": metrics["fieldAccuracyProxy"] >= 0.85},
                {"gate": "manual_correction_rate", "passed": metrics["manualCorrectionRate"] <= 0.2},
            ],
            "evaluationReport": payload.get("evaluationReport") or {},
            "evaluationSummary": payload.get("evaluationSummary") or {},
            "scenarioMetrics": payload.get("scenarioMetrics") or {},
            "caseDiagnostics": payload.get("caseDiagnostics") or [],
            "createdByRole": payload.get("createdByRole") or "fde",
        }
        self.state.setdefault("ocr_eval_runs", []).insert(0, run)
        return run

    def apply_ocr_result(self, document_id: str, version_id: str, result: dict[str, Any]) -> dict[str, Any]:
        document = self.find_one("documents", document_id)
        version = self.find_one("versions", version_id)
        knowledge_file = next(
            (item for item in self.state["knowledge_files"] if item.get("documentVersionId") == version_id),
            None,
        )
        task = next(
            (
                item
                for item in self.state["knowledge_tasks"]
                if item.get("documentVersionId") == version_id
                or item.get("targetId") == f"KF-{document_id}"
                or item.get("targetName") == result.get("fileName")
            ),
            None,
        )
        outcome_status = parse_result_outcome_status(result)
        success = outcome_status == "completed"
        partial = outcome_status == "partial"
        now = server_time()
        status = "已识别" if success else "抽取不完整" if partial else "识别失败"
        if document:
            document["currentOcrStatus"] = status
            document["updatedAt"] = now
        if version:
            version["ocrStatus"] = status
            version["sliceStatus"] = "待切片" if success else "未切片"
            version["vectorStatus"] = "待向量化" if success else "未向量化"
        if knowledge_file:
            knowledge_file["ocrStatus"] = status
            knowledge_file["sliceStatus"] = "待切片" if success else "未切片"
            knowledge_file["vectorStatus"] = "待向量化" if success else "未向量化"
            knowledge_file["updatedAt"] = now
        if task:
            task["status"] = "成功" if success else "需复核" if partial else "失败"
            task["progress"] = 100 if success or partial else task.get("progress", 0)
            task["finishedAt"] = now
            task["updatedAt"] = now
            self._bump_revision(task)
            if not success:
                quality_blockers = parse_result_quality_blockers(result)
                diagnostic_messages = [
                    str(item.get("code") or item.get("message") or item)
                    if isinstance(item, dict)
                    else str(item)
                    for item in result.get("diagnostics") or []
                ]
                task["errorMessage"] = "; ".join(quality_blockers or diagnostic_messages or ["OCR failed"])
                self.append_task_log(task, "warning" if partial else "error", task["errorMessage"])
            else:
                task.pop("errorMessage", None)
                self.append_task_log(task, "info", "OCR 任务完成。")

        if not success:
            return {
                "documentId": document_id,
                "versionId": version_id,
                "status": "partial" if partial else "failed",
                "outcomeStatus": outcome_status,
                "qualityReasons": parse_result_quality_blockers(result),
                "fieldCount": 0,
            }

        self.state["extracted_fields"] = [
            item for item in self.state["extracted_fields"] if item.get("documentVersionId") != version_id
        ]
        self.state["evidence_links"] = [
            item
            for item in self.state["evidence_links"]
            if item.get("documentVersionId") != version_id or item.get("objectType") == "knowledgeClause"
        ]
        fields = normalize_fields(result)
        if not fields:
            fields = fields_from_fragments(result)
        for index, field in enumerate(fields, start=1):
            field_id = f"FIELD-{version_id}-{index}"
            evidence_id = f"EV-{version_id}-{index}"
            page_no = int(field.get("pageNo") or 1)
            confidence = float(first_present(field, "confidence", default=0.8))
            self.state["extracted_fields"].append(
                {
                    "id": field_id,
                    "documentVersionId": version_id,
                    "fieldName": field["fieldName"],
                    "fieldValue": field["fieldValue"],
                    "pageNo": page_no,
                    "bbox": field.get("bbox"),
                    "confidence": confidence,
                    "extractionMethod": field.get("extractionMethod") or "PaddleOCR+seal",
                    "reviewStatus": "已确认" if confidence >= 0.85 else "低置信度",
                    "evidenceLinkId": evidence_id,
                }
            )
            self.state["evidence_links"].append(
                {
                    "id": evidence_id,
                    "objectType": "extractedField",
                    "objectId": field_id,
                    "documentId": document_id,
                    "documentVersionId": version_id,
                    "fileName": (document or {}).get("fileName") or result.get("fileName"),
                    "pageNo": page_no,
                    "fieldName": field["fieldName"],
                    "quotedText": str(field["fieldValue"])[:200],
                    "bbox": field.get("bbox"),
                    "confidence": confidence,
                }
            )
        if knowledge_file:
            source = self.find_one("knowledge_sources", knowledge_file.get("sourceId"))
            if (source or {}).get("sourceType") != "rule":
                self.upsert_knowledge_task(
                    task_type="slice",
                    target_id=knowledge_file["id"],
                    target_name=knowledge_file["fileName"],
                    document_id=document_id,
                    version_id=version_id,
                )
                self.upsert_knowledge_task(
                    task_type="vector",
                    target_id=knowledge_file["id"],
                    target_name=knowledge_file["fileName"],
                    document_id=document_id,
                    version_id=version_id,
                )
        return {"documentId": document_id, "versionId": version_id, "status": "success", "fieldCount": len(fields)}

    def apply_slice_result(self, file_id: str, fragments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        file = self.find_one("knowledge_files", file_id)
        if not file:
            return {"fileId": file_id, "status": "missing", "chunkCount": 0}
        source = self.find_one("knowledge_sources", file.get("sourceId"))
        if (source or {}).get("sourceType") == "rule":
            return {"fileId": file_id, "status": "skipped", "chunkCount": 0, "reason": "business_rule_not_indexed"}
        source_fragments = [item for item in fragments or [] if isinstance(item, dict) and str(item.get("text") or "").strip()]
        if not source_fragments:
            file["sliceStatus"] = "切片失败"
            file["chunkCount"] = 0
            file["vectorStatus"] = "向量化失败"
            file["vectorCount"] = 0
            file["updatedAt"] = server_time()
            task = next(
                (item for item in self.state["knowledge_tasks"] if item.get("taskType") == "slice" and item.get("targetId") == file_id),
                None,
            )
            self.mark_task_failed(task, "切片任务失败：未抽取到可切片文本。")
            return {"fileId": file_id, "status": "failed", "chunkCount": 0, "errorMessage": "empty_text"}
        chunks = build_chunks_for_file(file, source_fragments, index_version=STANDARD_INDEX_VERSION)
        now = server_time()
        for chunk in chunks:
            chunk["createdAt"] = now
            chunk["updatedAt"] = now
        self.state["knowledge_chunks"] = [
            item for item in self.state.get("knowledge_chunks", []) if item.get("fileId") != file_id
        ]
        self.state["knowledge_vectors"] = [
            item for item in self.state.get("knowledge_vectors", []) if item.get("fileId") != file_id
        ]
        self.state.setdefault("knowledge_chunks", []).extend(chunks)
        file["sliceStatus"] = "已切片"
        file["chunkCount"] = len([item for item in self.state["knowledge_chunks"] if item.get("fileId") == file_id])
        file["vectorStatus"] = "待向量化"
        file["vectorCount"] = 0
        file["indexVersion"] = STANDARD_INDEX_VERSION
        file["updatedAt"] = server_time()
        if source:
            self.sync_standard_page_index_for_source(str(source.get("id")))
        task = next(
            (item for item in self.state["knowledge_tasks"] if item.get("taskType") == "slice" and item.get("targetId") == file_id),
            None,
        )
        if task:
            task["status"] = "成功"
            task["progress"] = 100
            task["finishedAt"] = server_time()
            task["updatedAt"] = task["finishedAt"]
            self._bump_revision(task)
            self.append_task_log(task, "info", "切片任务完成。")
        return {"fileId": file_id, "status": "success", "chunkCount": file["chunkCount"]}

    def sync_standard_page_index_for_source(self, source_id: str) -> None:
        source = self.find_one("knowledge_sources", source_id)
        if not source or source.get("sourceType") == "rule":
            return
        source_files = [item for item in self.state.get("knowledge_files", []) if item.get("sourceId") == source_id]
        if not source_files:
            return
        file_ids = {str(item.get("id")) for item in source_files}
        source_chunks = [item for item in self.state.get("knowledge_chunks", []) if str(item.get("fileId") or "") in file_ids]
        if not source_chunks:
            return
        generated_nodes = build_page_index_nodes_for_source(source, source_files, source_chunks)
        source_version = str(source.get("version") or "inspection_kb@1.0.0")
        files_by_id = {str(item.get("id")): item for item in source_files}
        generated_clauses = [
            clause_from_chunk(files_by_id[str(chunk.get("fileId"))], chunk, source_version)
            for chunk in source_chunks
            if str(chunk.get("fileId") or "") in files_by_id
        ]
        self.state["knowledge_page_index_nodes"] = [
            item
            for item in self.state.get("knowledge_page_index_nodes", [])
            if not (item.get("kbDocId") == source_id and item.get("indexVersion") == PAGE_INDEX_VERSION)
        ]
        self.state.setdefault("knowledge_page_index_nodes", []).extend(generated_nodes)
        self.state["knowledge_clauses"] = [
            item
            for item in self.state.get("knowledge_clauses", [])
            if not (
                item.get("kbDocId") == source_id
                and str(item.get("chunkId") or item.get("clauseId") or "").startswith(("CHK-", "VCHK-"))
            )
        ]
        self.state.setdefault("knowledge_clauses", []).extend(generated_clauses)

    def apply_embed_result(
        self,
        file_id: str,
        vector_count: int | None = None,
        *,
        vectors: list[dict[str, Any]] | None = None,
        embedding_model: str = OFFLINE_EMBEDDING_MODEL,
        index_version: str = STANDARD_INDEX_VERSION,
        expected_dimensions: int = OFFLINE_VECTOR_DIMENSIONS,
        vector_status_reason: str | None = None,
    ) -> dict[str, Any]:
        file = self.find_one("knowledge_files", file_id)
        if not file:
            return {"fileId": file_id, "status": "missing", "vectorCount": 0}
        source = self.find_one("knowledge_sources", file.get("sourceId"))
        if (source or {}).get("sourceType") == "rule":
            return {"fileId": file_id, "status": "skipped", "vectorCount": 0, "reason": "business_rule_not_indexed"}
        chunks = sorted(
            [item for item in self.state.get("knowledge_chunks", []) if item.get("fileId") == file_id],
            key=lambda item: int(item.get("chunkNo") or 0),
        )
        vector_rows = build_vector_rows(
            file,
            chunks,
            vectors or [],
            embedding_model=embedding_model,
            index_version=index_version,
        )
        self.state["knowledge_vectors"] = [
            item for item in self.state.get("knowledge_vectors", []) if item.get("fileId") != file_id
        ]
        now = server_time()
        for row in vector_rows:
            row["createdAt"] = now
            row["updatedAt"] = now
        self.state.setdefault("knowledge_vectors", []).extend(vector_rows)
        count = len(vector_rows)
        expected_count = len(chunks)
        dimensions = {int(item.get("dimensions") or 0) for item in vector_rows if item.get("dimensions")}
        complete = bool(expected_count) and count == expected_count and dimensions == {int(expected_dimensions)}
        if vector_count is not None and vector_count != count:
            complete = False
        file["vectorStatus"] = "已向量化" if complete else "向量化失败"
        file["vectorCount"] = count
        file["embeddingModel"] = embedding_model
        file["indexVersion"] = index_version
        file["vectorStatusReason"] = vector_status_reason or ("complete" if complete else "vector_count_or_dimension_mismatch")
        if dimensions:
            file["vectorDimensions"] = next(iter(dimensions))
        file["updatedAt"] = server_time()
        task = next(
            (item for item in self.state["knowledge_tasks"] if item.get("taskType") == "vector" and item.get("targetId") == file_id),
            None,
        )
        if task:
            if complete:
                task["status"] = "成功"
                task["progress"] = 100
                task["finishedAt"] = server_time()
                task["updatedAt"] = task["finishedAt"]
                task.pop("errorMessage", None)
                self._bump_revision(task)
                self.append_task_log(task, "info", "向量化任务完成。")
            else:
                self.mark_task_failed(task, f"向量化任务失败：向量 {count}/{expected_count} 条，维度集合 {sorted(dimensions)}。")
        return {
            "fileId": file_id,
            "status": "success" if complete else "failed",
            "vectorCount": count,
            "embeddingModel": embedding_model,
            "indexVersion": index_version,
            "vectorStatusReason": file.get("vectorStatusReason"),
        }

    def _build_knowledge_vector_rows(
        self,
        file: dict[str, Any],
        chunks: list[dict[str, Any]],
        vectors: list[dict[str, Any]],
        *,
        embedding_model: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        now = server_time()
        vectors_by_index = {int(item.get("index") or index): item for index, item in enumerate(vectors)}
        for index, chunk in enumerate(chunks):
            vector = vectors_by_index.get(index) or {}
            embedding = vector.get("embedding") if isinstance(vector, dict) else None
            if not isinstance(embedding, list):
                continue
            rows.append(
                {
                    "id": f"KV-{chunk['id']}",
                    "fileId": file["id"],
                    "chunkId": chunk["id"],
                    "documentId": file.get("documentId"),
                    "documentVersionId": file.get("documentVersionId"),
                    "projectId": file.get("projectId"),
                    "vectorNo": index + 1,
                    "embedding": embedding,
                    "dimensions": len(embedding),
                    "embeddingModel": embedding_model,
                    "indexVersion": "proj-v2026.06.26",
                    "createdAt": now,
                    "updatedAt": now,
                }
            )
        return rows

    def attach_export_artifact(self, task: dict[str, Any], *, content_type: str | None = None, body: bytes | None = None) -> dict[str, Any]:
        file_name = task.get("fileName") or f"{task['id']}.zip"
        suffix = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "zip"
        content_type = content_type or ("application/pdf" if suffix == "pdf" else "application/zip")
        artifact_body = body or build_export_artifact(file_name, task, content_type, self)
        object_key = f"{task.get('projectId') or 'global'}/{task['id']}/{file_name}"
        stored_url = object_storage.put_bytes("exports", object_key, artifact_body, content_type=content_type)
        if stored_url:
            task["downloadUrl"] = stored_url
            task["storageBucket"] = "exports"
            task["storageKey"] = object_key
            task["fileSize"] = len(artifact_body)
            task["contentType"] = content_type
        elif object_storage.required:
            raise ObjectStorageUnavailable("Object storage is required in production but export artifact could not be stored.")
        else:
            export_root = Path(
                os.getenv(
                    "AICHECK_LOCAL_EXPORT_ROOT",
                    str(Path(__file__).resolve().parents[2] / "data" / "runtime-exports"),
                )
            ).expanduser().resolve()
            target = (export_root / object_key).resolve()
            if export_root not in target.parents:
                raise ObjectStorageUnavailable("导出产物路径越界。")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(artifact_body)
            task["downloadUrl"] = f"/api/exports/{task['id']}/artifact"
            task["localArtifactPath"] = str(target)
            task["fileSize"] = len(artifact_body)
            task["contentType"] = content_type
        task["contentHash"] = f"sha256-{hashlib.sha256(artifact_body).hexdigest()}"
        return task

    def configure_sync_postgres(self, dsn: str | None = None) -> None:
        with self._sync_postgres_lock:
            target_dsn = dsn or os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")
            if not target_dsn:
                return
            if self.sync_postgres is not None and self.postgres_dsn == target_dsn:
                return
            try:
                import psycopg
            except Exception as exc:
                raise RuntimeError(f"psycopg is required to use PostgreSQL persistence: {exc}") from exc
            self.close_sync_postgres()
            self.sync_postgres = psycopg.connect(target_dsn, autocommit=False)
            self.postgres_dsn = target_dsn
            self.postgres_enabled = True

    def close_sync_postgres(self) -> None:
        with self._sync_postgres_lock:
            connection = self.sync_postgres
            self.sync_postgres = None
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def default_sqlite_path(self) -> Path:
        backend_root = Path(__file__).resolve().parents[2]
        configured = os.getenv("AICHECK_SQLITE_PATH")
        if configured:
            configured_path = Path(configured).expanduser()
            if not configured_path.is_absolute():
                configured_path = backend_root / configured_path
            return configured_path.resolve()
        return backend_root / "data" / "aicheck.sqlite3"

    def configure_sqlite(self, path: str | os.PathLike[str] | None = None) -> None:
        if os.getenv("AICHECK_SQLITE_DISABLE", "false").lower() == "true":
            self.sqlite_enabled = False
            self.sqlite_path = None
            return
        target_path = Path(path).expanduser().resolve() if path else self.default_sqlite_path()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        self.sqlite_path = str(target_path)
        self.sqlite_enabled = True

    def sqlite_connection(self) -> sqlite3.Connection:
        self.configure_sqlite(self.sqlite_path)
        if not self.sqlite_path:
            raise RuntimeError("AICHECK_SQLITE_PATH is required to use SQLite persistence.")
        connection = sqlite3.connect(self.sqlite_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def ensure_sqlite_schema(self) -> None:
        with self.sqlite_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS aicheck_state (
                    collection text NOT NULL,
                    object_id text NOT NULL,
                    payload text NOT NULL,
                    updated_at text NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (collection, object_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS aicheck_singletons (
                    name text PRIMARY KEY,
                    payload text NOT NULL,
                    updated_at text NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    scope text PRIMARY KEY,
                    payload text NOT NULL,
                    updated_at text NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_aicheck_state_collection ON aicheck_state (collection)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_idempotency_updated_at ON idempotency_records (updated_at DESC)"
            )

    def _fresh_state_for_persistence_load(self) -> dict[str, Any]:
        loaded = runtime_initial_state()
        loaded.setdefault("knowledge_chunks", [])
        loaded.setdefault("knowledge_vectors", [])
        loaded.setdefault("knowledge_embedding_batches", [])
        loaded.setdefault("knowledge_clauses", [])
        loaded.setdefault("knowledge_page_index_nodes", [])
        loaded.setdefault("knowledge_vector_corrections", [])
        loaded.setdefault("knowledge_chunk_quarantines", [])
        loaded.setdefault("node_evidence_links", [])
        loaded.setdefault("material_targeting_runs", [])
        loaded.setdefault("upload_sessions", [])
        loaded.setdefault("ocr_jobs", [])
        loaded.setdefault("ocr_parse_results", [])
        loaded.setdefault("ocr_pipeline_runs", [])
        loaded.setdefault("ocr_stage_runs", [])
        loaded.setdefault("document_ai_shadow_runs", [])
        loaded.setdefault("document_audit_pipeline_comparison_runs", [])
        loaded.setdefault("model_call_attempts", [])
        loaded.setdefault("ocr_corrections", [])
        loaded.setdefault("ocr_eval_runs", [])
        loaded.setdefault("ocr_annotation_tasks", [])
        loaded.setdefault("ocr_annotation_imports", [])
        loaded.setdefault("fde_capability_test_upload_sessions", [])
        loaded.setdefault("fde_capability_test_runs", [])
        loaded.setdefault("review_runs", [])
        loaded.setdefault("review_step_runs", [])
        loaded.setdefault("review_graph_nodes", [])
        loaded.setdefault("review_tool_calls", [])
        loaded.setdefault("review_events", [])
        loaded.setdefault("retrieval_traces", [])
        loaded.setdefault("rule_check_results", [])
        loaded.setdefault("prompt_templates", [])
        loaded.setdefault("cost_budget_change_requests", [])
        loaded.setdefault("masking_policies", [])
        return loaded

    def apply_seed_compatibility_defaults(self, loaded: dict[str, Any]) -> bool:
        """Backfill fields added after an existing local database was initialized."""
        changed = False
        seeded = fresh_state()
        if not loaded.get("prompt_templates"):
            loaded["prompt_templates"] = seeded.get("prompt_templates", [])
            changed = True
        if not loaded.get("admin_config", {}).get("materialReviewPoints"):
            loaded.setdefault("admin_config", {})["materialReviewPoints"] = self.clone(
                seeded.get("admin_config", {}).get("materialReviewPoints", [])
            )
            changed = True

        seeded_ai_runs = {
            str(item.get("id")): item for item in seeded.get("ai_runs", []) if item.get("id")
        }
        for run in loaded.get("ai_runs", []):
            if not isinstance(run, dict):
                continue
            seeded_run = seeded_ai_runs.get(str(run.get("id") or ""))
            if not seeded_run:
                continue
            for field in [
                "llmConversationId",
                "promptAudit",
                "llmMetadata",
                "reasoningProcess",
                "llmResultText",
            ]:
                if not run.get(field) and seeded_run.get(field):
                    run[field] = self.clone(seeded_run[field])
                    changed = True

        seeded_trace_steps = {
            str(item.get("id")): item
            for item in seeded.get("ai_trace_steps", [])
            if item.get("id")
        }
        for step in loaded.get("ai_trace_steps", []):
            if not isinstance(step, dict):
                continue
            seeded_step = seeded_trace_steps.get(str(step.get("id") or ""))
            if not seeded_step:
                continue
            for field in ["conversationId", "promptHash", "responseHash", "reasoningProcess", "resultText"]:
                if not step.get(field) and seeded_step.get(field):
                    step[field] = self.clone(seeded_step[field])
                    changed = True
        if ensure_inspection_project_members(
            loaded.get("projects", []),
            loaded.setdefault("project_members", []),
            loaded.get("tree_nodes", []),
        ):
            changed = True
        return changed

    def persistence_object_id(self, collection_name: str, doc: dict[str, Any], index: int) -> str:
        object_id = str(doc.get("id") or doc.get("reviewRunId") or doc.get("jobId") or doc.get("parseResultId") or index)
        if collection_name == STATE_COLLECTIONS["requirements"] and doc.get("projectId") and doc.get("id"):
            return f"{doc['projectId']}:{doc['id']}"
        return object_id

    def load_from_sqlite(self, selected_state_keys: set[str] | None = None) -> None:
        self.configure_sqlite(self.sqlite_path)
        if not self.sqlite_enabled:
            return
        self.ensure_sqlite_schema()
        loaded = self._fresh_state_for_persistence_load()
        with self.sqlite_connection() as connection:
            selected_collections = [
                STATE_COLLECTIONS[state_key]
                for state_key in sorted(selected_state_keys or set())
                if state_key in STATE_COLLECTIONS
            ]
            if selected_state_keys is not None:
                placeholders = ",".join("?" for _ in selected_collections) or "NULL"
                rows = connection.execute(
                    f"SELECT collection, payload FROM aicheck_state WHERE collection IN ({placeholders}) ORDER BY collection, object_id",
                    selected_collections,
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT collection, payload FROM aicheck_state ORDER BY collection, object_id"
                ).fetchall()
            has_project_seed = any(row[0] == STATE_COLLECTIONS["projects"] for row in rows)
            grouped: dict[str, list[dict[str, Any]]] = {}
            for collection_name, payload in rows:
                grouped.setdefault(collection_name, []).append(json.loads(payload))
            for state_key, collection_name in STATE_COLLECTIONS.items():
                documents = grouped.get(collection_name, [])
                if has_project_seed or documents:
                    loaded[state_key] = documents
            for name, payload in connection.execute("SELECT name, payload FROM aicheck_singletons").fetchall():
                loaded[name] = json.loads(payload)
            loaded["idempotency"] = {
                scope: json.loads(payload)
                for scope, payload in connection.execute("SELECT scope, payload FROM idempotency_records").fetchall()
            }
        backfilled = (
            self.apply_seed_compatibility_defaults(loaded)
            if selected_state_keys is None and demo_data_enabled()
            else False
        )
        self.state = loaded
        if selected_state_keys is not None:
            return
        if not has_project_seed and demo_data_enabled():
            self.flush_to_sqlite()
        elif backfilled:
            self.flush_to_sqlite()

    def flush_to_sqlite(self) -> None:
        self.configure_sqlite(self.sqlite_path)
        if not self.sqlite_enabled:
            return
        self.ensure_sqlite_schema()
        with self.sqlite_connection() as connection:
            connection.execute("BEGIN")
            connection.execute("DELETE FROM aicheck_state")
            connection.execute("DELETE FROM aicheck_singletons")
            connection.execute("DELETE FROM idempotency_records")
            for state_key, collection_name in STATE_COLLECTIONS.items():
                docs = [self.clone(item) for item in self.state.get(state_key, [])]
                for index, doc in enumerate(docs):
                    object_id = self.persistence_object_id(collection_name, doc, index)
                    connection.execute(
                        """
                        INSERT INTO aicheck_state (collection, object_id, payload, updated_at)
                        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(collection, object_id)
                        DO UPDATE SET payload = excluded.payload, updated_at = CURRENT_TIMESTAMP
                        """,
                        (collection_name, object_id, json.dumps(doc, ensure_ascii=False)),
                    )
            for state_key in SINGLETON_COLLECTIONS:
                connection.execute(
                    """
                    INSERT INTO aicheck_singletons (name, payload, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(name)
                    DO UPDATE SET payload = excluded.payload, updated_at = CURRENT_TIMESTAMP
                    """,
                    (state_key, json.dumps(self.clone(self.state.get(state_key)), ensure_ascii=False)),
                )
            for scope, payload in self.state.get("idempotency", {}).items():
                connection.execute(
                    """
                    INSERT INTO idempotency_records (scope, payload, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(scope)
                    DO UPDATE SET payload = excluded.payload, updated_at = CURRENT_TIMESTAMP
                    """,
                    (scope, json.dumps(self.clone(payload), ensure_ascii=False)),
                )
            connection.commit()

    def postgres_connection(self, dsn: str | None = None):
        try:
            import psycopg
        except Exception as exc:
            raise RuntimeError(f"psycopg is required to use PostgreSQL persistence: {exc}") from exc
        target_dsn = dsn or self.postgres_dsn or os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")
        if not target_dsn:
            raise RuntimeError("AICHECK_DATABASE_URL is required to use PostgreSQL persistence.")
        return psycopg.connect(target_dsn, autocommit=False)

    def ensure_postgres_schema(self) -> None:
        with self._sync_postgres_lock:
            self.configure_sync_postgres()
            if self.sync_postgres is None:
                return
            with self.sync_postgres.transaction():
                self.sync_postgres.execute(
                    """
                    CREATE TABLE IF NOT EXISTS aicheck_state (
                        collection text NOT NULL,
                        object_id text NOT NULL,
                        payload jsonb NOT NULL,
                        updated_at timestamptz NOT NULL DEFAULT now(),
                        PRIMARY KEY (collection, object_id)
                    )
                    """
                )
                self.sync_postgres.execute(
                    """
                    CREATE TABLE IF NOT EXISTS aicheck_singletons (
                        name text PRIMARY KEY,
                        payload jsonb NOT NULL,
                        updated_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                self.sync_postgres.execute(
                    """
                    CREATE TABLE IF NOT EXISTS idempotency_records (
                        scope text PRIMARY KEY,
                        payload jsonb NOT NULL,
                        updated_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                self.sync_postgres.execute(
                    "CREATE INDEX IF NOT EXISTS idx_aicheck_state_collection ON aicheck_state (collection)"
                )
                self.sync_postgres.execute(
                    "CREATE INDEX IF NOT EXISTS idx_aicheck_state_payload_gin ON aicheck_state USING gin (payload)"
                )
                self.sync_postgres.execute(
                    "CREATE INDEX IF NOT EXISTS idx_idempotency_updated_at ON idempotency_records (updated_at DESC)"
                )

    def load_from_sync_postgres(self, selected_state_keys: set[str] | None = None) -> None:
        with self._sync_postgres_lock:
            self.configure_sync_postgres()
            if self.sync_postgres is None:
                return
            self.ensure_postgres_schema()
            loaded = self._fresh_state_for_persistence_load()
            selected_collections = [
                STATE_COLLECTIONS[state_key]
                for state_key in sorted(selected_state_keys or set())
                if state_key in STATE_COLLECTIONS
            ]
            if selected_state_keys is not None:
                rows = self.sync_postgres.execute(
                    "SELECT collection, payload FROM aicheck_state WHERE collection = ANY(%s) ORDER BY collection, object_id",
                    (selected_collections,),
                ).fetchall()
            else:
                rows = self.sync_postgres.execute(
                    "SELECT collection, payload FROM aicheck_state ORDER BY collection, object_id"
                ).fetchall()
            has_project_seed = any(row[0] == STATE_COLLECTIONS["projects"] for row in rows)
            grouped: dict[str, list[dict[str, Any]]] = {}
            for collection_name, payload in rows:
                grouped.setdefault(collection_name, []).append(json.loads(json.dumps(payload)))
            for state_key, collection_name in STATE_COLLECTIONS.items():
                documents = grouped.get(collection_name, [])
                if has_project_seed or documents:
                    loaded[state_key] = documents
            for name, payload in self.sync_postgres.execute("SELECT name, payload FROM aicheck_singletons").fetchall():
                loaded[name] = json.loads(json.dumps(payload))
            loaded["idempotency"] = {
                scope: json.loads(json.dumps(payload))
                for scope, payload in self.sync_postgres.execute("SELECT scope, payload FROM idempotency_records").fetchall()
            }
            backfilled = (
                self.apply_seed_compatibility_defaults(loaded)
                if selected_state_keys is None and demo_data_enabled()
                else False
            )
            self.state = loaded
            # psycopg starts a transaction for the SELECTs above when autocommit is off.
            # End that read transaction before any writer tries to flush the JSONB state.
            self.sync_postgres.commit()
            if selected_state_keys is not None:
                return
            if not has_project_seed and demo_data_enabled():
                self.flush_to_sync_postgres()
            elif backfilled:
                self.flush_to_sync_postgres()

    def load_ocr_task_state_from_sync_postgres(self, document_id: str, version_id: str) -> None:
        """Load only state needed by one OCR task, excluding unrelated historical parse payloads."""
        with self._sync_postgres_lock:
            self.configure_sync_postgres()
            if self.sync_postgres is None:
                return
            self.ensure_postgres_schema()
            loaded = self._fresh_state_for_persistence_load()
            global_collections = [
                STATE_COLLECTIONS[state_key]
                for state_key in (
                    "projects",
                    "project_members",
                    "tree_nodes",
                    "requirements",
                    "knowledge_sources",
                    "users",
                )
            ]
            scoped_collections = [
                STATE_COLLECTIONS[state_key]
                for state_key in (
                    "documents",
                    "versions",
                    "bindings",
                    "evidence_links",
                    "node_evidence_links",
                    "material_targeting_runs",
                    "extracted_fields",
                    "knowledge_files",
                    "knowledge_tasks",
                    "ocr_jobs",
                    "ocr_parse_results",
                    "ocr_pipeline_runs",
                    "ocr_stage_runs",
                    "document_ai_shadow_runs",
                    "document_audit_pipeline_comparison_runs",
                )
            ]
            rows = self.sync_postgres.execute(
                """
                SELECT collection, payload
                FROM aicheck_state
                WHERE collection = ANY(%s)
                   OR (
                        collection = ANY(%s)
                        AND (
                            object_id = ANY(%s)
                            OR payload ->> 'documentId' = %s
                            OR payload ->> 'documentVersionId' = %s
                        )
                   )
                ORDER BY collection, object_id
                """,
                (
                    global_collections,
                    scoped_collections,
                    [document_id, version_id],
                    document_id,
                    version_id,
                ),
            ).fetchall()
            grouped: dict[str, list[dict[str, Any]]] = {}
            for collection_name, payload in rows:
                grouped.setdefault(collection_name, []).append(json.loads(json.dumps(payload)))
            for state_key, collection_name in STATE_COLLECTIONS.items():
                if collection_name in global_collections or collection_name in scoped_collections:
                    loaded[state_key] = grouped.get(collection_name, [])
            for name, payload in self.sync_postgres.execute("SELECT name, payload FROM aicheck_singletons").fetchall():
                loaded[name] = json.loads(json.dumps(payload))
            loaded["idempotency"] = {}
            self.state = loaded
            self.sync_postgres.commit()

    def flush_to_sync_postgres(self) -> None:
        with self._sync_postgres_lock:
            self.configure_sync_postgres()
            if self.sync_postgres is None:
                return
            self.ensure_postgres_schema()
            with self.sync_postgres.transaction():
                self.sync_postgres.execute("SELECT pg_advisory_xact_lock(hashtext('aicheck_state_flush'))")
                self.sync_postgres.execute("DELETE FROM aicheck_state")
                self.sync_postgres.execute("DELETE FROM aicheck_singletons")
                self.sync_postgres.execute("DELETE FROM idempotency_records")
                for state_key, collection_name in STATE_COLLECTIONS.items():
                    docs = [self.clone(item) for item in self.state.get(state_key, [])]
                    for index, doc in enumerate(docs):
                        object_id = self.persistence_object_id(collection_name, doc, index)
                        self.sync_postgres.execute(
                            """
                            INSERT INTO aicheck_state (collection, object_id, payload, updated_at)
                            VALUES (%s, %s, %s::jsonb, now())
                            ON CONFLICT (collection, object_id)
                            DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                            """,
                            (collection_name, object_id, json.dumps(doc, ensure_ascii=False)),
                        )
                for state_key in SINGLETON_COLLECTIONS:
                    self.sync_postgres.execute(
                        """
                        INSERT INTO aicheck_singletons (name, payload, updated_at)
                        VALUES (%s, %s::jsonb, now())
                        ON CONFLICT (name)
                        DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                        """,
                        (state_key, json.dumps(self.clone(self.state.get(state_key)), ensure_ascii=False)),
                    )
                for scope, payload in self.state.get("idempotency", {}).items():
                    self.sync_postgres.execute(
                        """
                        INSERT INTO idempotency_records (scope, payload, updated_at)
                        VALUES (%s, %s::jsonb, now())
                        ON CONFLICT (scope)
                        DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                        """,
                        (scope, json.dumps(self.clone(payload), ensure_ascii=False)),
                    )
            self.sync_postgres.commit()
            if self.state.get("knowledge_vectors"):
                self.flush_knowledge_vectors_to_pgvector()

    def upsert_state_records_to_sync_postgres(
        self,
        records_by_state_key: dict[str, list[dict[str, Any]]],
    ) -> None:
        """Persist selected records without replacing another process's state snapshot."""
        self.sync_state_records_to_sync_postgres(records_by_state_key, {})

    def sync_state_records_to_sync_postgres(
        self,
        records_by_state_key: dict[str, list[dict[str, Any]]],
        deleted_object_ids_by_state_key: dict[str, list[str]],
    ) -> None:
        """Delete stale scoped rows and upsert their replacements in one transaction."""
        with self._sync_postgres_lock:
            self.configure_sync_postgres()
            if self.sync_postgres is None:
                return
            self.ensure_postgres_schema()
            with self.sync_postgres.transaction():
                for state_key, object_ids in deleted_object_ids_by_state_key.items():
                    collection_name = STATE_COLLECTIONS.get(state_key)
                    if not collection_name:
                        raise KeyError(f"Unknown state collection: {state_key}")
                    selected_ids = sorted({str(item) for item in object_ids if item})
                    if selected_ids:
                        self.sync_postgres.execute(
                            "DELETE FROM aicheck_state WHERE collection = %s AND object_id = ANY(%s)",
                            (collection_name, selected_ids),
                        )
                for state_key, docs in records_by_state_key.items():
                    collection_name = STATE_COLLECTIONS.get(state_key)
                    if not collection_name:
                        raise KeyError(f"Unknown state collection: {state_key}")
                    for index, doc in enumerate(docs):
                        if not isinstance(doc, dict):
                            continue
                        object_id = self.persistence_object_id(collection_name, doc, index)
                        self.sync_postgres.execute(
                            """
                            INSERT INTO aicheck_state (collection, object_id, payload, updated_at)
                            VALUES (%s, %s, %s::jsonb, now())
                            ON CONFLICT (collection, object_id)
                            DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                            """,
                            (collection_name, object_id, json.dumps(self.clone(doc), ensure_ascii=False)),
                        )
            self.sync_postgres.commit()

    def sync_state_records_to_sqlite(
        self,
        records_by_state_key: dict[str, list[dict[str, Any]]],
        deleted_object_ids_by_state_key: dict[str, list[str]],
    ) -> None:
        self.configure_sqlite(self.sqlite_path)
        if not self.sqlite_enabled:
            return
        self.ensure_sqlite_schema()
        with self.sqlite_connection() as connection:
            connection.execute("BEGIN")
            for state_key, object_ids in deleted_object_ids_by_state_key.items():
                collection_name = STATE_COLLECTIONS.get(state_key)
                if not collection_name:
                    raise KeyError(f"Unknown state collection: {state_key}")
                connection.executemany(
                    "DELETE FROM aicheck_state WHERE collection = ? AND object_id = ?",
                    [(collection_name, str(object_id)) for object_id in object_ids if object_id],
                )
            for state_key, docs in records_by_state_key.items():
                collection_name = STATE_COLLECTIONS.get(state_key)
                if not collection_name:
                    raise KeyError(f"Unknown state collection: {state_key}")
                for index, doc in enumerate(docs):
                    if not isinstance(doc, dict):
                        continue
                    object_id = self.persistence_object_id(collection_name, doc, index)
                    connection.execute(
                        """
                        INSERT INTO aicheck_state (collection, object_id, payload, updated_at)
                        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(collection, object_id)
                        DO UPDATE SET payload = excluded.payload, updated_at = CURRENT_TIMESTAMP
                        """,
                        (collection_name, object_id, json.dumps(self.clone(doc), ensure_ascii=False)),
                    )
            connection.commit()

    def upsert_idempotency_records_to_sync_postgres(self, scopes: list[str]) -> None:
        with self._sync_postgres_lock:
            self.configure_sync_postgres()
            if self.sync_postgres is None:
                return
            self.ensure_postgres_schema()
            with self.sync_postgres.transaction():
                for scope in scopes:
                    payload = self.state.get("idempotency", {}).get(scope)
                    if not isinstance(payload, dict):
                        continue
                    self.sync_postgres.execute(
                        """
                        INSERT INTO idempotency_records (scope, payload, updated_at)
                        VALUES (%s, %s::jsonb, now())
                        ON CONFLICT (scope)
                        DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                        """,
                        (scope, json.dumps(self.clone(payload), ensure_ascii=False)),
                    )
            self.sync_postgres.commit()

    def ensure_pgvector_schema(self) -> bool:
        with self._sync_postgres_lock:
            if self.sync_postgres is None:
                return False
            try:
                self.sync_postgres.execute("CREATE EXTENSION IF NOT EXISTS vector")
                self.sync_postgres.execute(
                    """
                    CREATE TABLE IF NOT EXISTS knowledge_vector_index (
                        id text PRIMARY KEY,
                        file_id text,
                        chunk_id text,
                        document_id text,
                        document_version_id text,
                        source_id text,
                        embedding vector(1024) NOT NULL,
                        dimensions integer NOT NULL,
                        embedding_model text NOT NULL,
                        index_version text NOT NULL,
                        metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
                        updated_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                self.sync_postgres.execute("CREATE INDEX IF NOT EXISTS idx_kvi_source ON knowledge_vector_index (source_id)")
                self.sync_postgres.execute("CREATE INDEX IF NOT EXISTS idx_kvi_index_version ON knowledge_vector_index (index_version)")
                self.sync_postgres.execute(
                    "CREATE INDEX IF NOT EXISTS idx_kvi_embedding_cosine ON knowledge_vector_index USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
                )
                self.sync_postgres.commit()
                return True
            except Exception:
                try:
                    self.sync_postgres.rollback()
                except Exception:
                    pass
                return False

    def flush_knowledge_vectors_to_pgvector(self) -> None:
        with self._sync_postgres_lock:
            if self.sync_postgres is None or not self.ensure_pgvector_schema():
                return
            try:
                self.sync_postgres.execute("DELETE FROM knowledge_vector_index")
                for row in self.state.get("knowledge_vectors", []) or []:
                    if int(row.get("dimensions") or 0) != OFFLINE_VECTOR_DIMENSIONS:
                        continue
                    payload = vector_payload_for_pg(row)
                    embedding = payload.get("embedding")
                    if not isinstance(embedding, list) or not embedding:
                        continue
                    embedding_literal = "[" + ",".join(str(float(item)) for item in embedding) + "]"
                    self.sync_postgres.execute(
                        """
                        INSERT INTO knowledge_vector_index (
                            id, file_id, chunk_id, document_id, document_version_id, source_id,
                            embedding, dimensions, embedding_model, index_version, metadata, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s, %s::jsonb, now())
                        ON CONFLICT (id)
                        DO UPDATE SET
                            file_id = EXCLUDED.file_id,
                            chunk_id = EXCLUDED.chunk_id,
                            document_id = EXCLUDED.document_id,
                            document_version_id = EXCLUDED.document_version_id,
                            source_id = EXCLUDED.source_id,
                            embedding = EXCLUDED.embedding,
                            dimensions = EXCLUDED.dimensions,
                            embedding_model = EXCLUDED.embedding_model,
                            index_version = EXCLUDED.index_version,
                            metadata = EXCLUDED.metadata,
                            updated_at = now()
                        """,
                        (
                            payload["id"],
                            payload["file_id"],
                            payload["chunk_id"],
                            payload["document_id"],
                            payload["document_version_id"],
                            payload["source_id"],
                            embedding_literal,
                            payload["dimensions"],
                            payload["embedding_model"],
                            payload["index_version"],
                            payload["metadata"],
                        ),
                    )
                self.sync_postgres.commit()
            except Exception:
                try:
                    self.sync_postgres.rollback()
                except Exception:
                    pass

    def search_knowledge_vectors(
        self,
        embedding: list[float],
        *,
        top_k: int = 5,
        source_id: str | None = None,
        index_version: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._sync_postgres_lock:
            self.configure_sync_postgres()
            if self.sync_postgres is None or len(embedding) != OFFLINE_VECTOR_DIMENSIONS or not self.ensure_pgvector_schema():
                return []
            embedding_literal = "[" + ",".join(str(float(item)) for item in embedding) + "]"
            filters = []
            params: list[Any] = []
            if source_id:
                filters.append("source_id = %s")
                params.append(source_id)
            if index_version:
                filters.append("index_version = %s")
                params.append(index_version)
            where = "WHERE " + " AND ".join(filters) if filters else ""
            rows = self.sync_postgres.execute(
                f"""
                SELECT id, file_id, chunk_id, document_id, document_version_id, source_id,
                       dimensions, embedding_model, index_version, metadata,
                       embedding <=> %s::vector AS distance
                FROM knowledge_vector_index
                {where}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (embedding_literal, *params, embedding_literal, int(top_k or 5)),
            ).fetchall()
            hits: list[dict[str, Any]] = []
            for row in rows:
                (
                    vector_id,
                    file_id,
                    chunk_id,
                    document_id,
                    document_version_id,
                    row_source_id,
                    dimensions,
                    embedding_model,
                    row_index_version,
                    metadata,
                    distance,
                ) = row
                hits.append(
                    {
                        "id": vector_id,
                        "fileId": file_id,
                        "chunkId": chunk_id,
                        "documentId": document_id,
                        "documentVersionId": document_version_id,
                        "sourceId": row_source_id,
                        "dimensions": dimensions,
                        "embeddingModel": embedding_model,
                        "indexVersion": row_index_version,
                        "metadata": json.loads(json.dumps(metadata, ensure_ascii=False, default=str)),
                        "distance": float(distance) if distance is not None else None,
                    }
                )
            return hits

    def search_local_knowledge_vectors(
        self,
        embedding: list[float],
        *,
        top_k: int = 5,
        source_id: str | None = None,
        index_version: str | None = None,
    ) -> list[dict[str, Any]]:
        if not embedding:
            return []
        hits: list[dict[str, Any]] = []
        query_embedding = [float(item) for item in embedding]
        for row in self.state.get("knowledge_vectors", []) or []:
            if source_id and row.get("sourceId") != source_id:
                continue
            if index_version and row.get("indexVersion") != index_version:
                continue
            row_embedding = row.get("embedding")
            if not isinstance(row_embedding, list) or len(row_embedding) != len(query_embedding):
                continue
            score = cosine_similarity(query_embedding, [float(item) for item in row_embedding])
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            hits.append(
                {
                    "id": row.get("id"),
                    "fileId": row.get("fileId"),
                    "chunkId": row.get("chunkId"),
                    "documentId": row.get("documentId"),
                    "documentVersionId": row.get("documentVersionId"),
                    "sourceId": row.get("sourceId"),
                    "sourceRelativePath": row.get("sourceRelativePath"),
                    "dimensions": row.get("dimensions"),
                    "embeddingModel": row.get("embeddingModel"),
                    "indexVersion": row.get("indexVersion"),
                    "metadata": {
                        **self.clone(payload),
                        "pageNo": row.get("pageNo"),
                        "sectionPath": row.get("sectionPath") or [],
                        "pageIndexNodeIds": row.get("pageIndexNodeIds") or [],
                    },
                    "score": score,
                    "distance": 1.0 - score,
                }
            )
        hits.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return hits[: int(top_k or 5)]

    def build_admin_overview(self) -> dict[str, Any]:
        config = self.clone(self.state["admin_config"])
        config["metrics"] = [
            {"key": "project", "label": "项目数", "value": len(self.state["projects"]), "tone": "blue"},
            {"key": "member", "label": "授权成员", "value": len(self.state["project_members"]), "tone": "green"},
            {"key": "rule", "label": "规则版本", "value": len(self.state["rule_versions"]), "tone": "orange"},
            {"key": "audit", "label": "审计记录", "value": len(self.state["audit_logs"]), "tone": "gray"},
        ]
        config["ruleVersions"] = self.clone(self.state["rule_versions"])
        return config


def stable_doc_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def normalize_fields(result: dict[str, Any]) -> list[dict[str, Any]]:
    fields = []
    for raw in result.get("fields") or []:
        if not isinstance(raw, dict):
            continue
        name = first_present(raw, "fieldName", "name", "key", "label")
        value = first_present(raw, "fieldValue", "value", "text")
        if name and value is not None:
            fields.append(
                {
                    "fieldName": str(name),
                    "fieldValue": str(value),
                    "pageNo": first_present(raw, "pageNo", "page", default=1),
                    "bbox": first_present(raw, "bbox", "box"),
                    "confidence": first_present(raw, "confidence", "score", default=0.8),
                    "extractionMethod": first_present(raw, "extractionMethod", "method"),
                }
            )
    return fields


def fields_from_fragments(result: dict[str, Any]) -> list[dict[str, Any]]:
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    fields = []
    for index, fragment in enumerate(fragments[:5], start=1):
        text = str(fragment.get("text") or "").strip()
        if not text:
            continue
        fields.append(
            {
                "fieldName": "OCR文本" if index == 1 else f"OCR文本{index}",
                "fieldValue": text[:200],
                "pageNo": first_present(fragment, "pageNo", default=1),
                "bbox": fragment.get("bbox"),
                "confidence": first_present(fragment, "confidence", default=0.8),
                "extractionMethod": "PaddleOCR",
            }
        )
    return fields


def first_present(raw: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return default


def build_export_artifact(
    file_name: str,
    task: dict[str, Any],
    content_type: str,
    repository: InMemoryRepository,
) -> bytes:
    if content_type == "application/pdf" or file_name.lower().endswith(".pdf"):
        return build_pdf_artifact(file_name, task, repository)
    return build_zip_artifact(file_name, task, repository)


def export_context(task: dict[str, Any], repository: InMemoryRepository) -> dict[str, Any]:
    project_id = task.get("projectId")
    report_id = task.get("reportId")
    project = repository.require_project(project_id) if project_id else None
    reports = []
    if report_id:
        report = repository.find_one("reports", str(report_id))
        reports = [repository.clone(report)] if report else []
    elif project_id:
        reports = [repository.clone(item) for item in repository.state["reports"] if item.get("projectId") == project_id]
    documents = [repository.clone(item) for item in repository.state["documents"] if not project_id or item.get("projectId") == project_id]
    document_ids = {item["id"] for item in documents}
    archive_items = [
        repository.clone(item)
        for item in repository.state["archive_items"]
        if not project_id or item.get("projectId") == project_id
    ]
    evidence_links = [
        repository.clone(item)
        for item in repository.state["evidence_links"]
        if not document_ids or item.get("documentId") in document_ids
    ]
    return {
        "project": repository.clone(project) if project else None,
        "reports": reports,
        "documents": documents,
        "archiveItems": archive_items,
        "evidenceLinks": evidence_links,
        "counts": {
            "reports": len(reports),
            "documents": len(documents),
            "archiveItems": len(archive_items),
            "evidenceLinks": len(evidence_links),
        },
    }


def build_zip_artifact(file_name: str, task: dict[str, Any], repository: InMemoryRepository) -> bytes:
    import io
    import zipfile

    context = export_context(task, repository)
    manifest = {
        "schemaVersion": "aicheck-export-v1",
        "generatedAt": server_time(),
        "taskId": task.get("id"),
        "exportType": task.get("exportType"),
        "projectId": task.get("projectId"),
        "reportId": task.get("reportId"),
        "fileName": file_name,
        "counts": context["counts"],
        "contents": [
            "manifest.json",
            "task.json",
            "project.json",
            "reports.json",
            "documents.json",
            "archive_items.json",
            "evidence_links.json",
            "README.txt",
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json_dump(manifest))
        archive.writestr("task.json", json_dump(task))
        archive.writestr("project.json", json_dump(context["project"] or {}))
        archive.writestr("reports.json", json_dump(context["reports"]))
        archive.writestr("documents.json", json_dump(context["documents"]))
        archive.writestr("archive_items.json", json_dump(context["archiveItems"]))
        archive.writestr("evidence_links.json", json_dump(context["evidenceLinks"]))
        archive.writestr(
            "README.txt",
            "AIcheck export package\n"
            f"Task: {task.get('id')}\n"
            f"Type: {task.get('exportType')}\n"
            f"Project: {task.get('projectId') or 'global'}\n"
            "This package contains machine-readable manifest and business snapshots for audit and recovery.\n",
        )
    return buffer.getvalue()


def build_pdf_artifact(file_name: str, task: dict[str, Any], repository: InMemoryRepository) -> bytes:
    context = export_context(task, repository)
    project = context["project"] or {}
    report = context["reports"][0] if context["reports"] else {}
    lines = [
        "AIcheck Export Report",
        f"Task: {task.get('id')}",
        f"File: {file_name}",
        f"Project: {project.get('code') or project.get('id') or task.get('projectId') or '-'}",
        f"Report: {report.get('title') or report.get('reportNo') or task.get('reportId') or '-'}",
        f"Export Type: {task.get('exportType') or '-'}",
        f"Generated At: {server_time()}",
        f"Documents: {context['counts']['documents']}",
        f"Evidence Links: {context['counts']['evidenceLinks']}",
    ]
    return simple_pdf(lines)


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def simple_pdf(lines: list[str]) -> bytes:
    content_lines = ["BT", "/F1 12 Tf", "72 760 Td", "14 TL"]
    for index, line in enumerate(lines):
        prefix = "" if index == 0 else "T* "
        content_lines.append(f"{prefix}({pdf_escape(line)}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")[:120]


repo = InMemoryRepository()


def postgres_persistence_configured() -> bool:
    return bool(repo.sync_postgres is not None or repo.postgres_dsn or os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL"))


def load_state(selected_state_keys: set[str] | None = None) -> None:
    if postgres_persistence_configured():
        repo.load_from_sync_postgres(selected_state_keys)
        return
    repo.load_from_sqlite(selected_state_keys)


def load_ocr_task_state(document_id: str, version_id: str) -> None:
    if postgres_persistence_configured():
        repo.load_ocr_task_state_from_sync_postgres(document_id, version_id)
        return
    load_state(OCR_WORKER_STATE_KEYS_FOR_SQLITE)


OCR_WORKER_STATE_KEYS_FOR_SQLITE = {
    "projects",
    "project_members",
    "tree_nodes",
    "requirements",
    "knowledge_sources",
    "documents",
    "versions",
    "bindings",
    "evidence_links",
    "node_evidence_links",
    "material_targeting_runs",
    "extracted_fields",
    "knowledge_files",
    "knowledge_tasks",
    "ocr_jobs",
    "ocr_parse_results",
    "ocr_pipeline_runs",
    "ocr_stage_runs",
    "document_ai_shadow_runs",
    "document_audit_pipeline_comparison_runs",
    "users",
}


def flush_state() -> None:
    if postgres_persistence_configured():
        repo.flush_to_sync_postgres()
        return
    if not (repo.sqlite_enabled or repo.sqlite_path or os.getenv("AICHECK_SQLITE_PATH")):
        return
    repo.flush_to_sqlite()


def flush_state_records(records_by_state_key: dict[str, list[dict[str, Any]]]) -> None:
    records = {
        state_key: [item for item in docs if isinstance(item, dict)]
        for state_key, docs in records_by_state_key.items()
        if docs
    }
    if not records:
        return
    if postgres_persistence_configured():
        repo.upsert_state_records_to_sync_postgres(records)
        return
    if repo.sqlite_enabled or repo.sqlite_path or os.getenv("AICHECK_SQLITE_PATH"):
        repo.flush_to_sqlite()


def sync_state_records(
    records_by_state_key: dict[str, list[dict[str, Any]]],
    deleted_object_ids_by_state_key: dict[str, list[str]],
) -> None:
    records = {
        state_key: [item for item in docs if isinstance(item, dict)]
        for state_key, docs in records_by_state_key.items()
    }
    deletions = {
        state_key: [str(item) for item in object_ids if item]
        for state_key, object_ids in deleted_object_ids_by_state_key.items()
    }
    if postgres_persistence_configured():
        repo.sync_state_records_to_sync_postgres(records, deletions)
        return
    if repo.sqlite_enabled or repo.sqlite_path or os.getenv("AICHECK_SQLITE_PATH"):
        repo.sync_state_records_to_sqlite(records, deletions)


def flush_idempotency_records(scopes: list[str]) -> None:
    selected = [scope for scope in scopes if scope]
    if not selected:
        return
    if postgres_persistence_configured():
        repo.upsert_idempotency_records_to_sync_postgres(selected)
        return
    if repo.sqlite_enabled or repo.sqlite_path or os.getenv("AICHECK_SQLITE_PATH"):
        repo.flush_to_sqlite()
