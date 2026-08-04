from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import sqlite3
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
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
from libs.security.tenant import (
    apply_default_tenant,
    current_tenant_id as configured_tenant_id,
    tenant_id_for_record,
)

from .seed import (
    ROLE_ACTIONS,
    ROLE_NODE_MAP,
    ensure_inspection_project_members,
    ensure_test_project_members,
    fresh_state,
)


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
    "review_sessions": "review_sessions",
    "review_messages": "review_messages",
    "review_session_events": "review_session_events",
    "agent_executions": "agent_executions",
    "workflow_outbox": "workflow_outbox",
    "workflow_inbox": "workflow_inbox",
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
    "report_templates": "report_templates",
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
    "standard_document_versions": "standard_document_versions",
    "standard_clause_references": "standard_clause_references",
    "standard_clause_locators": "standard_clause_locators",
    "standard_clause_packages_db": "standard_clause_packages",
    "standard_clause_package_items": "standard_clause_package_items",
    "project_node_clause_packages": "project_node_clause_packages",
    "review_run_clause_snapshots": "review_run_clause_snapshots",
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


def production_runtime_ddl_disabled() -> bool:
    environment = os.getenv("AICHECK_ENV", "development").strip().lower()
    allow_runtime_ddl = os.getenv("AICHECK_ALLOW_RUNTIME_DDL", "false").strip().lower() == "true"
    return environment in {"production", "prod"} and not allow_runtime_ddl


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


def redact_url_query(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(str(value))
    except ValueError:
        return None
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "", "")
    )


def sanitize_mineru_options(options: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(options[key])
        for key in ("provider", "language", "pageRanges", "noCache", "cacheTolerance")
        if key in options and options[key] is not None
    }


class InMemoryRepository:
    def __init__(self) -> None:
        self._tenant_states: dict[str, dict[str, Any]] = {}
        self._tenant_persistence_baselines: dict[str, dict[tuple[str, str], str]] = {}
        self._tenant_singleton_baselines: dict[str, dict[str, str]] = {}
        self._tenant_idempotency_baselines: dict[str, dict[str, str]] = {}
        self._tenant_pgvector_baseline_ids: dict[str, set[str]] = {}
        self._loaded_tenants: set[str] = set()
        self.state = runtime_initial_state()
        self._persistence_baseline: dict[tuple[str, str], str] = {}
        self._singleton_baseline: dict[str, str] = {}
        self._idempotency_baseline: dict[str, str] = {}
        self._pgvector_baseline_ids: set[str] = set()
        self.apply_tenant_scope()
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
        self.state.setdefault("review_sessions", [])
        self.state.setdefault("review_messages", [])
        self.state.setdefault("review_session_events", [])
        self.state.setdefault("agent_executions", [])
        self.state.setdefault("workflow_outbox", [])
        self.state.setdefault("workflow_inbox", [])
        self.state.setdefault("retrieval_traces", [])
        self.state.setdefault("rule_check_results", [])
        self.state.setdefault("prompt_templates", [])
        self.state.setdefault("report_templates", [])
        self.state.setdefault("cost_budget_change_requests", [])
        self.state.setdefault("masking_policies", [])
        self.postgres_dsn: str | None = None
        self.sync_postgres = None
        self.postgres_enabled = False
        self._postgres_schema_ready = False
        self.sqlite_path: str | None = None
        self.sqlite_enabled = False
        self._flush_lock = asyncio.Lock()
        self._sync_postgres_lock = threading.RLock()

    @property
    def state(self) -> dict[str, Any]:
        tenant_id = configured_tenant_id()
        state = self._tenant_states.get(tenant_id)
        if state is None:
            state = runtime_initial_state()
            for state_key in STATE_COLLECTIONS:
                apply_default_tenant(state.get(state_key), tenant_id=tenant_id)
            for state_key in SINGLETON_COLLECTIONS:
                apply_default_tenant(state.get(state_key), tenant_id=tenant_id)
            self._tenant_states[tenant_id] = state
        return state

    @state.setter
    def state(self, value: dict[str, Any]) -> None:
        self._tenant_states[configured_tenant_id()] = value

    @property
    def _persistence_baseline(self) -> dict[tuple[str, str], str]:
        return self._tenant_persistence_baselines.setdefault(configured_tenant_id(), {})

    @_persistence_baseline.setter
    def _persistence_baseline(self, value: dict[tuple[str, str], str]) -> None:
        self._tenant_persistence_baselines[configured_tenant_id()] = value

    @property
    def _singleton_baseline(self) -> dict[str, str]:
        return self._tenant_singleton_baselines.setdefault(configured_tenant_id(), {})

    @_singleton_baseline.setter
    def _singleton_baseline(self, value: dict[str, str]) -> None:
        self._tenant_singleton_baselines[configured_tenant_id()] = value

    @property
    def _idempotency_baseline(self) -> dict[str, str]:
        return self._tenant_idempotency_baselines.setdefault(configured_tenant_id(), {})

    @_idempotency_baseline.setter
    def _idempotency_baseline(self, value: dict[str, str]) -> None:
        self._tenant_idempotency_baselines[configured_tenant_id()] = value

    @property
    def _pgvector_baseline_ids(self) -> set[str]:
        return self._tenant_pgvector_baseline_ids.setdefault(configured_tenant_id(), set())

    @_pgvector_baseline_ids.setter
    def _pgvector_baseline_ids(self, value: set[str]) -> None:
        self._tenant_pgvector_baseline_ids[configured_tenant_id()] = value

    def tenant_is_loaded(self, tenant_id: str | None = None) -> bool:
        return str(tenant_id or configured_tenant_id()) in self._loaded_tenants

    def mark_tenant_loaded(self, tenant_id: str | None = None) -> None:
        self._loaded_tenants.add(str(tenant_id or configured_tenant_id()))

    def invalidate_tenant(self, tenant_id: str | None = None) -> None:
        self._loaded_tenants.discard(str(tenant_id or configured_tenant_id()))

    def snapshot_current_tenant_runtime(self, *, include_state: bool = True) -> dict[str, Any]:
        """Capture request-local mutable state so a failed persistence boundary can be rolled back."""

        tenant_id = configured_tenant_id()
        return {
            "tenantId": tenant_id,
            "state": self.clone(self.state) if include_state else None,
            "persistenceBaseline": dict(self._persistence_baseline) if include_state else None,
            "singletonBaseline": dict(self._singleton_baseline) if include_state else None,
            "idempotencyBaseline": dict(self._idempotency_baseline) if include_state else None,
            "pgvectorBaselineIds": set(self._pgvector_baseline_ids) if include_state else None,
            "wasLoaded": tenant_id in self._loaded_tenants,
        }

    def restore_tenant_runtime(self, snapshot: dict[str, Any], *, invalidate: bool = False) -> None:
        tenant_id = str(snapshot.get("tenantId") or configured_tenant_id())
        if tenant_id != configured_tenant_id():
            raise RuntimeError("Cannot restore a tenant snapshot outside its tenant context.")
        if snapshot.get("state") is None:
            self.reset()
            self._loaded_tenants.discard(tenant_id)
            return
        self.state = self.clone(snapshot["state"])
        self._persistence_baseline = dict(snapshot.get("persistenceBaseline") or {})
        self._singleton_baseline = dict(snapshot.get("singletonBaseline") or {})
        self._idempotency_baseline = dict(snapshot.get("idempotencyBaseline") or {})
        self._pgvector_baseline_ids = set(snapshot.get("pgvectorBaselineIds") or set())
        if invalidate:
            self._loaded_tenants.discard(tenant_id)
        elif snapshot.get("wasLoaded"):
            self._loaded_tenants.add(tenant_id)
        else:
            self._loaded_tenants.discard(tenant_id)

    def reset(self) -> None:
        self._loaded_tenants.discard(configured_tenant_id())
        self.state = runtime_initial_state()
        self._persistence_baseline = {}
        self._singleton_baseline = {}
        self._idempotency_baseline = {}
        self._pgvector_baseline_ids = set()
        self.apply_tenant_scope()
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
        self.state.setdefault("review_sessions", [])
        self.state.setdefault("review_messages", [])
        self.state.setdefault("review_session_events", [])
        self.state.setdefault("agent_executions", [])
        self.state.setdefault("workflow_outbox", [])
        self.state.setdefault("workflow_inbox", [])
        self.state.setdefault("retrieval_traces", [])
        self.state.setdefault("rule_check_results", [])
        self.state.setdefault("prompt_templates", [])
        self.state.setdefault("report_templates", [])
        self.state.setdefault("cost_budget_change_requests", [])
        self.state.setdefault("masking_policies", [])

    def apply_tenant_scope(self) -> None:
        tenant_id = configured_tenant_id()
        for state_key in STATE_COLLECTIONS:
            apply_default_tenant(self.state.get(state_key), tenant_id=tenant_id)
        for state_key in SINGLETON_COLLECTIONS:
            apply_default_tenant(self.state.get(state_key), tenant_id=tenant_id)
        for user in self.state.get("users", []):
            if isinstance(user, dict):
                user.setdefault("tenantId", tenant_id)

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

    def add_audit(
        self,
        action: str,
        object_type: str,
        object_id: str,
        result: str = "成功",
        *,
        project_id: str | None = None,
        node_id: int | None = None,
        error_code: str | None = None,
        before: Any = None,
        after: Any = None,
        outcome: str | None = None,
    ) -> str:
        audit_id = f"AUD-{uuid4().hex[:10].upper()}"
        actor = current_request_audit_context()
        tenant_id = str(actor.get("tenantId") or configured_tenant_id())
        request_path = str(actor.get("requestPath") or "")
        project_match = re.search(r"/projects/([^/]+)", request_path)
        node_match = re.search(r"/nodes/(\d+)", request_path)
        resolved_project_id = project_id or (project_match.group(1) if project_match else None)
        resolved_node_id = node_id if node_id is not None else (int(node_match.group(1)) if node_match else None)
        if object_type in {"ReviewRun", "AIRun", "AiRun"}:
            collection = "review_runs" if object_type == "ReviewRun" else "ai_runs"
            id_field = "reviewRunId" if collection == "review_runs" else "id"
            record = self.find_one(collection, object_id, id_field=id_field) or self.find_one(collection, object_id)
            if record:
                resolved_project_id = resolved_project_id or record.get("projectId")
                resolved_node_id = resolved_node_id if resolved_node_id is not None else record.get("nodeId")
                tenant_id = tenant_id_for_record(record)
        if not resolved_project_id or resolved_node_id is None:
            scoped_record = next(
                (
                    item
                    for state_key in STATE_COLLECTIONS
                    for item in self.state.get(state_key, [])
                    if isinstance(item, dict)
                    and tenant_id_for_record(item) == tenant_id
                    and str(item.get("id") or item.get("reviewRunId") or "") == str(object_id)
                ),
                None,
            )
            if scoped_record:
                resolved_project_id = resolved_project_id or scoped_record.get("projectId")
                if not resolved_project_id and object_type.lower() in {"project", "inspectionproject"}:
                    resolved_project_id = scoped_record.get("id")
                resolved_node_id = (
                    resolved_node_id if resolved_node_id is not None else scoped_record.get("nodeId")
                )
        tenant_events = [
            item
            for item in self.state.get("audit_logs", [])
            if tenant_id_for_record(item) == tenant_id
        ]
        previous = max(tenant_events, key=lambda item: int(item.get("sequence") or 0), default=None)
        sequence = int((previous or {}).get("sequence") or 0) + 1
        previous_hash = str((previous or {}).get("eventHash") or "GENESIS")
        before_hash = (
            "sha256:" + hashlib.sha256(json.dumps(before, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
            if before is not None
            else None
        )
        after_hash = (
            "sha256:" + hashlib.sha256(json.dumps(after, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
            if after is not None
            else None
        )
        created_at = server_time()
        resolved_outcome = outcome or ("success" if result == "成功" else "failed")
        event = {
            "id": audit_id,
            "tenantId": tenant_id,
            "projectId": resolved_project_id,
            "nodeId": int(resolved_node_id) if resolved_node_id not in {None, ""} else None,
            "actorId": actor.get("actorId") or "system",
            "actorName": actor.get("actorName") or "系统",
            "actorRole": actor.get("actorRole"),
            "actorOrgId": actor.get("actorOrgId"),
            "actorOrgName": actor.get("actorOrgName"),
            "operationId": actor.get("operationId"),
            "action": action,
            "objectType": object_type,
            "objectId": object_id,
            "result": result,
            "outcome": resolved_outcome,
            "reasonCode": error_code,
            "httpMethod": actor.get("httpMethod"),
            "route": request_path or None,
            "ipAddress": actor.get("clientIp"),
            "userAgent": str(actor.get("userAgent") or "")[:512] or None,
            "beforeHash": before_hash,
            "afterHash": after_hash,
            "sequence": sequence,
            "previousHash": previous_hash,
            "createdAt": created_at,
        }
        canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        event["eventHash"] = "sha256:" + hashlib.sha256(f"{previous_hash}:{canonical}".encode()).hexdigest()
        event["integrityStatus"] = "verified"
        self.state["audit_logs"].insert(0, event)
        return audit_id

    def verify_audit_chain(self, tenant_id: str) -> dict[str, Any]:
        tenant_events = [
            self.clone(item)
            for item in self.state.get("audit_logs", [])
            if tenant_id_for_record(item) == tenant_id
        ]
        chained = [item for item in tenant_events if item.get("sequence") and item.get("eventHash")]
        chained.sort(key=lambda item: (int(item.get("sequence") or 0), str(item.get("id") or "")))
        expected_previous = "GENESIS"
        expected_sequence = 1
        failures: list[dict[str, Any]] = []
        for event in chained:
            sequence = int(event.get("sequence") or 0)
            stored_hash = str(event.pop("eventHash", ""))
            event.pop("integrityStatus", None)
            previous_hash = str(event.get("previousHash") or "")
            canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
            computed_hash = "sha256:" + hashlib.sha256(
                f"{expected_previous}:{canonical}".encode()
            ).hexdigest()
            if sequence != expected_sequence or previous_hash != expected_previous or stored_hash != computed_hash:
                failures.append(
                    {
                        "id": event.get("id"),
                        "sequence": sequence,
                        "expectedSequence": expected_sequence,
                        "previousHashMatches": previous_hash == expected_previous,
                        "eventHashMatches": stored_hash == computed_hash,
                    }
                )
            expected_previous = stored_hash
            expected_sequence = sequence + 1
        legacy_count = len(tenant_events) - len(chained)
        legacy_seal = next(
            (
                item
                for item in chained
                if item.get("reasonCode") == "LEGACY_IMPORT_SEAL"
                and item.get("objectType") == "legacy_audit_manifest"
            ),
            None,
        )
        legacy_metadata = legacy_seal.get("metadata") if isinstance(legacy_seal, dict) else None
        legacy_manifest = None
        if isinstance(legacy_metadata, dict):
            legacy_manifest = {
                "manifestHash": legacy_metadata.get("manifestHash"),
                "manifestReference": legacy_metadata.get("manifestReference"),
                "integrityStatus": legacy_metadata.get("legacyIntegrityStatus") or "legacy_unverified",
                "sealEventId": legacy_seal.get("id"),
                "sealSequence": legacy_seal.get("sequence"),
            }
        return {
            "tenantId": tenant_id,
            "status": "verified" if not failures else "tampered",
            "coverageStatus": (
                "complete"
                if legacy_count == 0
                else "legacy_unverified_sealed"
                if legacy_manifest
                else "legacy_unverified_unsealed"
            ),
            "verifiedEventCount": len(chained) - len(failures),
            "chainedEventCount": len(chained),
            "legacyUnverifiedEventCount": legacy_count,
            # Backwards-compatible alias.  Consumers should migrate to the
            # semantically accurate legacyUnverifiedEventCount field.
            "legacyUnsealedEventCount": legacy_count,
            "legacyManifest": legacy_manifest,
            "failures": failures[:20],
            "headHash": expected_previous if chained else None,
        }

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
        ocr_options: dict[str, Any] | None = None,
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
        if ocr_options:
            version["ocrOptions"] = deepcopy(ocr_options)
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
                ocr_options=(
                    file.get("ocrOptions")
                    if isinstance(file.get("ocrOptions"), dict)
                    else None
                ),
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
        provider: str | None = None,
        source_url: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if record_id:
            existing = self.find_one("ocr_jobs", record_id)
            if existing:
                return existing
        now = server_time()
        safe_source_url = redact_url_query(source_url)
        job = {
            "id": record_id or f"OCRJOB-BIZ-{uuid4().hex[:10].upper()}",
            "jobId": None,
            "tenantId": configured_tenant_id(),
            "documentId": document_id,
            "documentVersionId": version_id,
            "storageKey": safe_source_url if source_url else storage_key,
            "fileName": file_name,
            "profileId": profile_id,
            "documentType": document_type,
            "provider": provider,
            "sourceUrl": safe_source_url,
            "sourceType": "url" if source_url else "storage",
            "options": sanitize_mineru_options(options or {}),
            "status": "queued",
            "stage": "queued",
            "progress": 0,
            "providerTaskId": None,
            "providerTaskType": None,
            "providerUploadState": None,
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

    def update_ocr_job_record(
        self,
        job: dict[str, Any] | None,
        *,
        status: str | None = None,
        stage: str | None = None,
        progress: int | None = None,
        provider_task_id: str | None = None,
        provider_task_type: str | None = None,
        provider_upload_state: str | None = None,
        diagnostics: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        if not job:
            return None
        now = server_time()
        if status is not None:
            job["status"] = status
            if status == "running":
                job["startedAt"] = job.get("startedAt") or now
            if status in {"success", "failed", "canceled"}:
                job["finishedAt"] = job.get("finishedAt") or now
        if stage is not None:
            job["stage"] = stage
        if progress is not None:
            terminal = (status or job.get("status")) in {
                "success",
                "failed",
                "canceled",
            }
            upper_bound = 100 if terminal else 99
            job["progress"] = max(0, min(int(progress), upper_bound))
        if provider_task_id is not None:
            job["providerTaskId"] = provider_task_id
        if provider_task_type is not None:
            job["providerTaskType"] = provider_task_type
        if provider_upload_state is not None:
            job["providerUploadState"] = provider_upload_state
        if diagnostics is not None:
            job["diagnostics"] = self.clone(diagnostics)
        job["updatedAt"] = now
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
            "outcomeStatus": result.get("outcomeStatus"),
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
            "signatures": result.get("signatures") or [],
            "fields": result.get("fields") or [],
            "quality": result.get("quality") or {},
            "metadata": result.get("metadata") or {},
            "groundingValidation": result.get("groundingValidation") or {},
            "costCny": float(result.get("costCny") or 0.0),
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
        job["stage"] = "completed" if result_record["status"] == "success" else "failed"
        job["progress"] = 100
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
                if not bool(getattr(self.sync_postgres, "closed", False)) and not bool(
                    getattr(self.sync_postgres, "broken", False)
                ):
                    return
                self.close_sync_postgres()
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
            self._postgres_schema_ready = False
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def ensure_sync_postgres_connection(self, dsn: str | None = None) -> bool:
        """Probe and reconnect the shared synchronous PostgreSQL session."""

        with self._sync_postgres_lock:
            target_dsn = dsn or self.postgres_dsn or os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")
            if not target_dsn:
                return False
            for _ in range(2):
                try:
                    self.configure_sync_postgres(target_dsn)
                    if self.sync_postgres is None:
                        return False
                    row = self.sync_postgres.execute("SELECT 1").fetchone()
                    self.sync_postgres.rollback()
                    if row and int(row[0]) == 1:
                        return True
                except Exception:
                    self.close_sync_postgres()
            return False

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
                    tenant_id text NOT NULL DEFAULT 'TENANT-DEFAULT',
                    collection text NOT NULL,
                    object_id text NOT NULL,
                    payload text NOT NULL,
                    updated_at text NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (tenant_id, collection, object_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS aicheck_singletons (
                    tenant_id text NOT NULL DEFAULT 'TENANT-DEFAULT',
                    name text NOT NULL,
                    payload text NOT NULL,
                    updated_at text NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (tenant_id, name)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    tenant_id text NOT NULL DEFAULT 'TENANT-DEFAULT',
                    scope text NOT NULL,
                    payload text NOT NULL,
                    updated_at text NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (tenant_id, scope)
                )
                """
            )
            self._migrate_sqlite_tenant_keys(connection)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_aicheck_state_collection ON aicheck_state (tenant_id, collection)"
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_project_node_clause_packages_lookup
                ON aicheck_state (
                    json_extract(payload, '$.projectId'),
                    CAST(json_extract(payload, '$.nodeId') AS INTEGER)
                )
                WHERE collection = 'project_node_clause_packages'
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_review_run_clause_snapshots_lookup
                ON aicheck_state (json_extract(payload, '$.reviewRunId'))
                WHERE collection = 'review_run_clause_snapshots'
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_idempotency_updated_at ON idempotency_records (tenant_id, updated_at DESC)"
            )

    def _migrate_sqlite_tenant_keys(self, connection: sqlite3.Connection) -> None:
        """Upgrade legacy local databases to the same composite tenant keys as PostgreSQL."""

        state_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(aicheck_state)")}
        if "tenant_id" not in state_columns:
            connection.execute("ALTER TABLE aicheck_state RENAME TO aicheck_state_legacy_tenant_key")
            connection.execute(
                """
                CREATE TABLE aicheck_state (
                    tenant_id text NOT NULL DEFAULT 'TENANT-DEFAULT',
                    collection text NOT NULL,
                    object_id text NOT NULL,
                    payload text NOT NULL,
                    updated_at text NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (tenant_id, collection, object_id)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO aicheck_state (tenant_id, collection, object_id, payload, updated_at)
                SELECT COALESCE(NULLIF(json_extract(payload, '$.tenantId'), ''), 'TENANT-DEFAULT'),
                       collection, object_id, payload, updated_at
                FROM aicheck_state_legacy_tenant_key
                """
            )
            connection.execute("DROP TABLE aicheck_state_legacy_tenant_key")

        singleton_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(aicheck_singletons)")}
        if "tenant_id" not in singleton_columns:
            connection.execute("ALTER TABLE aicheck_singletons RENAME TO aicheck_singletons_legacy_tenant_key")
            connection.execute(
                """
                CREATE TABLE aicheck_singletons (
                    tenant_id text NOT NULL DEFAULT 'TENANT-DEFAULT',
                    name text NOT NULL,
                    payload text NOT NULL,
                    updated_at text NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (tenant_id, name)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO aicheck_singletons (tenant_id, name, payload, updated_at)
                SELECT COALESCE(NULLIF(json_extract(payload, '$.tenantId'), ''), 'TENANT-DEFAULT'),
                       name, payload, updated_at
                FROM aicheck_singletons_legacy_tenant_key
                """
            )
            connection.execute("DROP TABLE aicheck_singletons_legacy_tenant_key")

        idempotency_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(idempotency_records)")}
        if "tenant_id" not in idempotency_columns:
            connection.execute("ALTER TABLE idempotency_records RENAME TO idempotency_records_legacy_tenant_key")
            connection.execute(
                """
                CREATE TABLE idempotency_records (
                    tenant_id text NOT NULL DEFAULT 'TENANT-DEFAULT',
                    scope text NOT NULL,
                    payload text NOT NULL,
                    updated_at text NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (tenant_id, scope)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO idempotency_records (tenant_id, scope, payload, updated_at)
                SELECT COALESCE(NULLIF(json_extract(payload, '$.tenantId'), ''),
                                NULLIF(substr(scope, 1, instr(scope, ':') - 1), ''),
                                'TENANT-DEFAULT'),
                       scope, payload, updated_at
                FROM idempotency_records_legacy_tenant_key
                """
            )
            connection.execute("DROP TABLE idempotency_records_legacy_tenant_key")

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
        loaded.setdefault("review_sessions", [])
        loaded.setdefault("review_messages", [])
        loaded.setdefault("review_session_events", [])
        loaded.setdefault("agent_executions", [])
        loaded.setdefault("retrieval_traces", [])
        loaded.setdefault("rule_check_results", [])
        loaded.setdefault("prompt_templates", [])
        loaded.setdefault("report_templates", [])
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
        if not loaded.get("report_templates"):
            loaded["report_templates"] = seeded.get("report_templates", [])
            changed = True
        if not loaded.get("admin_config", {}).get("materialReviewPoints"):
            loaded.setdefault("admin_config", {})["materialReviewPoints"] = self.clone(
                seeded.get("admin_config", {}).get("materialReviewPoints", [])
            )
            changed = True
        from libs.business_pack import list_business_packs, load_business_pack
        from libs.business_pack.clause_store import (
            bind_project_node_clause_packages,
            ensure_clause_state,
            publish_standard_clause_release,
        )

        ensure_clause_state(loaded)
        clause_state_was_missing = not loaded.get("standard_clause_packages_db")
        project_bindings_were_missing = not loaded.get("project_node_clause_packages")
        if clause_state_was_missing or project_bindings_were_missing:
            for summary in list_business_packs():
                pack = load_business_pack(summary["id"])
                if not pack.get("standardClausePackages"):
                    continue
                publish_standard_clause_release(loaded, pack)
                for project in loaded.get("projects", []):
                    if project.get("businessPackId") != pack["id"]:
                        continue
                    if project.get("businessPackVersion") not in {None, "", pack["version"]}:
                        continue
                    bind_project_node_clause_packages(
                        loaded,
                        project,
                        pack,
                        bound_at=project.get("updatedAt"),
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
        if ensure_test_project_members(
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

    @staticmethod
    def canonical_persistence_payload(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

    def capture_persistence_baseline(self) -> None:
        baseline: dict[tuple[str, str], str] = {}
        for state_key, collection_name in STATE_COLLECTIONS.items():
            for index, doc in enumerate(self.state.get(state_key, [])):
                if not isinstance(doc, dict):
                    continue
                object_id = self.persistence_object_id(collection_name, doc, index)
                baseline[(collection_name, object_id)] = self.canonical_persistence_payload(
                    self.persistence_tenant_document(doc)
                )
        self._persistence_baseline = baseline
        self._singleton_baseline = {
            state_key: self.canonical_persistence_payload(
                self.persistence_tenant_document(self.state.get(state_key) or {})
            )
            for state_key in SINGLETON_COLLECTIONS
        }
        self._idempotency_baseline = {
            str(scope): self.canonical_persistence_payload(payload)
            for scope, payload in self.state.get("idempotency", {}).items()
        }

    def current_persistence_documents(
        self,
        selected_state_keys: set[str] | None = None,
    ) -> dict[tuple[str, str], dict[str, Any]]:
        documents: dict[tuple[str, str], dict[str, Any]] = {}
        state_items = (
            ((key, STATE_COLLECTIONS[key]) for key in selected_state_keys if key in STATE_COLLECTIONS)
            if selected_state_keys is not None
            else STATE_COLLECTIONS.items()
        )
        for state_key, collection_name in state_items:
            for index, doc in enumerate(self.state.get(state_key, [])):
                if not isinstance(doc, dict):
                    continue
                object_id = self.persistence_object_id(collection_name, doc, index)
                documents[(collection_name, object_id)] = self.persistence_tenant_document(doc)
        return documents

    def persistence_tenant_document(self, document: dict[str, Any]) -> dict[str, Any]:
        """Bind persisted records to this process's configured tenant."""

        tenant_id = configured_tenant_id()
        explicit_tenant = str(document.get("tenantId") or document.get("tenant_id") or "").strip()
        if explicit_tenant and explicit_tenant != tenant_id:
            raise RuntimeError("Cross-tenant persistence is not allowed in this process.")
        if not explicit_tenant:
            document["tenantId"] = tenant_id
        scoped = self.clone(document)
        scoped.pop("tenant_id", None)
        scoped["tenantId"] = tenant_id
        return scoped

    def assert_persistence_baseline(self, key: tuple[str, str], stored_payload: Any) -> None:
        expected = self._persistence_baseline.get(key)
        actual = self.canonical_persistence_payload(stored_payload) if stored_payload is not None else None
        if expected != actual:
            raise RuntimeError(
                f"Concurrent persistence update detected for {key[0]}/{key[1]}; reload before retrying."
            )

    def prepare_audit_records_for_postgres_transaction(
        self,
        records_by_state_key: dict[str, list[dict[str, Any]]],
        tenant_id: str,
    ) -> None:
        """Serialize and re-chain new audit events under a tenant-scoped DB lock."""

        audits = [item for item in records_by_state_key.get("audit_logs", []) if isinstance(item, dict)]
        if not audits or self.sync_postgres is None:
            return
        self.sync_postgres.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (f"aicheck:audit:{tenant_id}",),
        )
        head = self.sync_postgres.execute(
            """
            SELECT sequence, event_hash
            FROM audit_events
            WHERE tenant_id = %s AND sequence IS NOT NULL
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (tenant_id,),
        ).fetchone()
        sequence = int(head[0]) if head else 0
        previous_hash = str(head[1]) if head and head[1] else "GENESIS"
        for event in sorted(audits, key=lambda item: (str(item.get("createdAt") or ""), str(item.get("id") or ""))):
            event_id = str(event.get("id") or "")
            if not event_id:
                continue
            existing = self.sync_postgres.execute(
                "SELECT sequence, event_hash FROM audit_events WHERE tenant_id = %s AND id = %s",
                (tenant_id, event_id),
            ).fetchone()
            if existing:
                continue
            sequence += 1
            event["tenantId"] = tenant_id
            event["sequence"] = sequence
            event["previousHash"] = previous_hash
            canonical_event = {
                key: value
                for key, value in event.items()
                if key not in {"eventHash", "integrityStatus"}
            }
            canonical = json.dumps(
                canonical_event,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            )
            event_hash = "sha256:" + hashlib.sha256(f"{previous_hash}:{canonical}".encode()).hexdigest()
            event["eventHash"] = event_hash
            event["integrityStatus"] = "verified"
            previous_hash = event_hash

    def update_scoped_persistence_baseline(
        self,
        records_by_state_key: dict[str, list[dict[str, Any]]],
        deleted_object_ids_by_state_key: dict[str, list[str]],
    ) -> None:
        for state_key, object_ids in deleted_object_ids_by_state_key.items():
            collection_name = STATE_COLLECTIONS.get(state_key)
            if not collection_name:
                continue
            for object_id in object_ids:
                self._persistence_baseline.pop((collection_name, str(object_id)), None)
        for state_key, docs in records_by_state_key.items():
            collection_name = STATE_COLLECTIONS.get(state_key)
            if not collection_name:
                continue
            for index, doc in enumerate(docs):
                if not isinstance(doc, dict):
                    continue
                doc = self.persistence_tenant_document(doc)
                object_id = self.persistence_object_id(collection_name, doc, index)
                self._persistence_baseline[(collection_name, object_id)] = self.canonical_persistence_payload(doc)

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
                    f"""
                    SELECT collection, object_id, payload
                    FROM aicheck_state
                    WHERE collection IN ({placeholders})
                      AND tenant_id = ?
                    ORDER BY collection, object_id
                    """,
                    [*selected_collections, configured_tenant_id()],
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT collection, object_id, payload
                    FROM aicheck_state
                    WHERE tenant_id = ?
                    ORDER BY collection, object_id
                    """,
                    (configured_tenant_id(),),
                ).fetchall()
            has_project_seed = any(row[0] == STATE_COLLECTIONS["projects"] for row in rows)
            grouped: dict[str, list[dict[str, Any]]] = {}
            for collection_name, _, payload in rows:
                grouped.setdefault(collection_name, []).append(json.loads(payload))
            for state_key, collection_name in STATE_COLLECTIONS.items():
                documents = grouped.get(collection_name, [])
                if selected_state_keys is not None and state_key in selected_state_keys:
                    loaded[state_key] = documents
                elif has_project_seed or documents:
                    loaded[state_key] = documents
            singleton_rows = connection.execute(
                """
                SELECT name, payload FROM aicheck_singletons
                WHERE tenant_id = ?
                """,
                (configured_tenant_id(),),
            ).fetchall()
            for name, payload in singleton_rows:
                loaded[name] = json.loads(payload)
            idempotency_rows = connection.execute(
                "SELECT scope, payload FROM idempotency_records WHERE tenant_id = ?",
                (configured_tenant_id(),),
            ).fetchall()
            loaded["idempotency"] = {scope: json.loads(payload) for scope, payload in idempotency_rows}
        loaded_baseline = {
            (str(collection_name), str(object_id)): self.canonical_persistence_payload(json.loads(payload))
            for collection_name, object_id, payload in rows
        }
        self.mark_tenant_loaded()
        if selected_state_keys is not None:
            selected_collections_set = {
                STATE_COLLECTIONS[key] for key in selected_state_keys if key in STATE_COLLECTIONS
            }
            for state_key in selected_state_keys:
                if state_key in STATE_COLLECTIONS:
                    self.state[state_key] = loaded.get(state_key, [])
            self._persistence_baseline = {
                key: value
                for key, value in self._persistence_baseline.items()
                if key[0] not in selected_collections_set
            }
            self._persistence_baseline.update(loaded_baseline)
            self.apply_tenant_scope()
            return
        self.state = loaded
        self._persistence_baseline = {
            **loaded_baseline
        }
        self._singleton_baseline = {
            str(name): self.canonical_persistence_payload(json.loads(payload))
            for name, payload in singleton_rows
        }
        self._idempotency_baseline = {
            str(scope): self.canonical_persistence_payload(json.loads(payload))
            for scope, payload in idempotency_rows
        }
        self.apply_tenant_scope()
        backfilled = False
        if selected_state_keys is None:
            if demo_data_enabled():
                backfilled = self.apply_seed_compatibility_defaults(self.state)
            else:
                backfilled = ensure_test_project_members(
                    self.state.get("projects", []),
                    self.state.setdefault("project_members", []),
                    self.state.get("tree_nodes", []),
                )
        if not has_project_seed and demo_data_enabled():
            self.flush_to_sqlite()
        elif backfilled:
            self.flush_to_sqlite()

    def _build_flush_dirty_plan(
        self,
        *,
        selected_state_keys: set[str] | None = None,
        selected_singleton_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        """Single-pass dirty detection for scoped or full persistence flush."""

        current_documents = self.current_persistence_documents(selected_state_keys)
        if selected_state_keys is not None:
            selected_collections = {
                STATE_COLLECTIONS[key] for key in selected_state_keys if key in STATE_COLLECTIONS
            }
            baseline_keys = {
                key for key in self._persistence_baseline if key[0] in selected_collections
            }
        else:
            baseline_keys = set(self._persistence_baseline)

        deleted_keys = sorted(baseline_keys - set(current_documents))
        vector_collection = STATE_COLLECTIONS["knowledge_vectors"]
        vector_dirty = any(key[0] == vector_collection for key in deleted_keys)

        dirty_documents: dict[tuple[str, str], tuple[dict[str, Any], str]] = {}
        for key, doc in current_documents.items():
            payload = self.canonical_persistence_payload(doc)
            if self._persistence_baseline.get(key) == payload:
                continue
            dirty_documents[key] = (doc, payload)
            if key[0] == vector_collection:
                vector_dirty = True

        singleton_keys = (
            {key for key in selected_singleton_keys if key in SINGLETON_COLLECTIONS}
            if selected_singleton_keys is not None
            else set(SINGLETON_COLLECTIONS)
        )
        dirty_singletons: dict[str, str] = {}
        for state_key in singleton_keys:
            value = self.persistence_tenant_document(self.state.get(state_key) or {})
            payload = self.canonical_persistence_payload(value)
            if self._singleton_baseline.get(state_key) == payload:
                continue
            dirty_singletons[state_key] = payload

        current_idempotency = {
            str(scope): self.clone(value)
            for scope, value in self.state.get("idempotency", {}).items()
        }
        deleted_idempotency = sorted(set(self._idempotency_baseline) - set(current_idempotency))
        dirty_idempotency: dict[str, str] = {}
        for scope, value in current_idempotency.items():
            payload = self.canonical_persistence_payload(value)
            if self._idempotency_baseline.get(scope) == payload:
                continue
            dirty_idempotency[scope] = payload

        new_audit_records: list[dict[str, Any]] = []
        if selected_state_keys is None or "audit_logs" in selected_state_keys:
            audit_collection = STATE_COLLECTIONS["audit_logs"]
            for index, doc in enumerate(self.state.get("audit_logs", [])):
                if not isinstance(doc, dict):
                    continue
                object_id = self.persistence_object_id(audit_collection, doc, index)
                if (audit_collection, object_id) not in self._persistence_baseline:
                    new_audit_records.append(doc)

        has_work = bool(
            dirty_documents
            or deleted_keys
            or dirty_singletons
            or dirty_idempotency
            or deleted_idempotency
            or new_audit_records
        )
        return {
            "dirty_documents": dirty_documents,
            "deleted_keys": deleted_keys,
            "dirty_singletons": dirty_singletons,
            "dirty_idempotency": dirty_idempotency,
            "deleted_idempotency": deleted_idempotency,
            "new_audit_records": new_audit_records,
            "vector_dirty": vector_dirty,
            "has_work": has_work,
        }

    def _refresh_prepared_audit_dirty_payloads(
        self,
        dirty_documents: dict[tuple[str, str], tuple[dict[str, Any], str]],
        new_audit_records: list[dict[str, Any]],
    ) -> None:
        if not new_audit_records:
            return
        audit_collection = STATE_COLLECTIONS["audit_logs"]
        prepared_ids = {id(item) for item in new_audit_records}
        for index, doc in enumerate(self.state.get("audit_logs", [])):
            if not isinstance(doc, dict) or id(doc) not in prepared_ids:
                continue
            object_id = self.persistence_object_id(audit_collection, doc, index)
            refreshed = self.persistence_tenant_document(doc)
            payload = self.canonical_persistence_payload(refreshed)
            dirty_documents[(audit_collection, object_id)] = (refreshed, payload)

    def _apply_flush_baseline_updates(
        self,
        *,
        dirty_documents: dict[tuple[str, str], tuple[dict[str, Any], str]],
        deleted_keys: list[tuple[str, str]],
        dirty_singletons: dict[str, str],
        dirty_idempotency: dict[str, str],
        deleted_idempotency: list[str],
    ) -> None:
        for collection_name, object_id in deleted_keys:
            self._persistence_baseline.pop((collection_name, object_id), None)
        for key, (_doc, payload) in dirty_documents.items():
            self._persistence_baseline[key] = payload
        for state_key, payload in dirty_singletons.items():
            self._singleton_baseline[state_key] = payload
        for scope in deleted_idempotency:
            self._idempotency_baseline.pop(scope, None)
        for scope, payload in dirty_idempotency.items():
            self._idempotency_baseline[scope] = payload

    def flush_to_sqlite(
        self,
        selected_state_keys: set[str] | None = None,
        selected_singleton_keys: set[str] | None = None,
    ) -> None:
        self.configure_sqlite(self.sqlite_path)
        if not self.sqlite_enabled:
            return
        self.ensure_sqlite_schema()
        plan = self._build_flush_dirty_plan(
            selected_state_keys=selected_state_keys,
            selected_singleton_keys=selected_singleton_keys,
        )
        if not plan["has_work"]:
            return
        dirty_documents: dict[tuple[str, str], tuple[dict[str, Any], str]] = plan["dirty_documents"]
        deleted_keys: list[tuple[str, str]] = plan["deleted_keys"]
        dirty_singletons: dict[str, str] = plan["dirty_singletons"]
        dirty_idempotency: dict[str, str] = plan["dirty_idempotency"]
        deleted_idempotency: list[str] = plan["deleted_idempotency"]
        tenant_id = configured_tenant_id()
        with self.sqlite_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for collection_name, object_id in deleted_keys:
                row = connection.execute(
                    "SELECT payload FROM aicheck_state WHERE tenant_id = ? AND collection = ? AND object_id = ?",
                    (tenant_id, collection_name, object_id),
                ).fetchone()
                self.assert_persistence_baseline(
                    (collection_name, object_id),
                    json.loads(row[0]) if row else None,
                )
                connection.execute(
                    "DELETE FROM aicheck_state WHERE tenant_id = ? AND collection = ? AND object_id = ?",
                    (tenant_id, collection_name, object_id),
                )
            for (collection_name, object_id), (_doc, payload) in dirty_documents.items():
                key = (collection_name, object_id)
                row = connection.execute(
                    "SELECT payload FROM aicheck_state WHERE tenant_id = ? AND collection = ? AND object_id = ?",
                    (tenant_id, collection_name, object_id),
                ).fetchone()
                if key in self._persistence_baseline:
                    self.assert_persistence_baseline(key, json.loads(row[0]) if row else None)
                elif row:
                    if self.canonical_persistence_payload(json.loads(row[0])) == payload:
                        continue
                    raise RuntimeError(
                        f"Concurrent persistence insert detected for {collection_name}/{object_id}."
                    )
                connection.execute(
                    """
                    INSERT INTO aicheck_state (tenant_id, collection, object_id, payload, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(tenant_id, collection, object_id)
                    DO UPDATE SET payload = excluded.payload, updated_at = CURRENT_TIMESTAMP
                    """,
                    (tenant_id, collection_name, object_id, payload),
                )
            for state_key, payload in dirty_singletons.items():
                row = connection.execute(
                    "SELECT payload FROM aicheck_singletons WHERE tenant_id = ? AND name = ?",
                    (tenant_id, state_key),
                ).fetchone()
                actual = self.canonical_persistence_payload(json.loads(row[0])) if row else None
                expected = self._singleton_baseline.get(state_key)
                if expected != actual and actual != payload:
                    raise RuntimeError(f"Concurrent singleton update detected for {state_key}.")
                connection.execute(
                    """
                    INSERT INTO aicheck_singletons (tenant_id, name, payload, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(tenant_id, name)
                    DO UPDATE SET payload = excluded.payload, updated_at = CURRENT_TIMESTAMP
                    """,
                    (tenant_id, state_key, payload),
                )
            for scope in deleted_idempotency:
                row = connection.execute(
                    "SELECT payload FROM idempotency_records WHERE tenant_id = ? AND scope = ?",
                    (tenant_id, scope),
                ).fetchone()
                actual = self.canonical_persistence_payload(json.loads(row[0])) if row else None
                if actual != self._idempotency_baseline[scope]:
                    raise RuntimeError(f"Concurrent idempotency update detected for {scope}.")
                connection.execute(
                    "DELETE FROM idempotency_records WHERE tenant_id = ? AND scope = ?",
                    (tenant_id, scope),
                )
            for scope, payload in dirty_idempotency.items():
                row = connection.execute(
                    "SELECT payload FROM idempotency_records WHERE tenant_id = ? AND scope = ?",
                    (tenant_id, scope),
                ).fetchone()
                actual = self.canonical_persistence_payload(json.loads(row[0])) if row else None
                expected = self._idempotency_baseline.get(scope)
                if expected != actual and actual != payload:
                    raise RuntimeError(f"Concurrent idempotency update detected for {scope}.")
                connection.execute(
                    """
                    INSERT INTO idempotency_records (tenant_id, scope, payload, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(tenant_id, scope)
                    DO UPDATE SET payload = excluded.payload, updated_at = CURRENT_TIMESTAMP
                    """,
                    (tenant_id, scope, payload),
                )
            connection.commit()
        self._apply_flush_baseline_updates(
            dirty_documents=dirty_documents,
            deleted_keys=deleted_keys,
            dirty_singletons=dirty_singletons,
            dirty_idempotency=dirty_idempotency,
            deleted_idempotency=deleted_idempotency,
        )

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
            if self._postgres_schema_ready:
                return
            if production_runtime_ddl_disabled():
                required_tables = {
                    "aicheck_state",
                    "aicheck_singletons",
                    "idempotency_records",
                    "schema_migrations",
                    "audit_events",
                    "audit_chain_anchors",
                    "service_heartbeats",
                }
                if os.getenv("AICHECK_REQUIRE_PGVECTOR", "true").strip().lower() == "true":
                    required_tables.add("knowledge_vector_index")
                present = {
                    str(name)
                    for (name,) in self.sync_postgres.execute(
                        "SELECT relname FROM pg_class WHERE relname = ANY(%s)",
                        (sorted(required_tables),),
                    ).fetchall()
                }
                missing = sorted(required_tables - present)
                if missing:
                    self.sync_postgres.rollback()
                    raise RuntimeError(
                        "Database migrations are required before production startup; missing tables: "
                        + ", ".join(missing)
                    )
                migration = self.sync_postgres.execute(
                    "SELECT version FROM schema_migrations WHERE version = %s",
                    ("0001_backend_audit_hardening",),
                ).fetchone()
                self.sync_postgres.commit()
                if not migration:
                    raise RuntimeError("Database migration 0001_backend_audit_hardening is required.")
                self._postgres_schema_ready = True
                return
            with self.sync_postgres.transaction():
                self.sync_postgres.execute(
                    """
                    CREATE TABLE IF NOT EXISTS aicheck_state (
                        tenant_id text NOT NULL DEFAULT 'TENANT-DEFAULT',
                        collection text NOT NULL,
                        object_id text NOT NULL,
                        payload jsonb NOT NULL,
                        updated_at timestamptz NOT NULL DEFAULT now(),
                        PRIMARY KEY (tenant_id, collection, object_id)
                    )
                    """
                )
                self.sync_postgres.execute(
                    """
                    CREATE TABLE IF NOT EXISTS aicheck_singletons (
                        tenant_id text NOT NULL DEFAULT 'TENANT-DEFAULT',
                        name text NOT NULL,
                        payload jsonb NOT NULL,
                        updated_at timestamptz NOT NULL DEFAULT now(),
                        PRIMARY KEY (tenant_id, name)
                    )
                    """
                )
                self.sync_postgres.execute(
                    """
                    CREATE TABLE IF NOT EXISTS idempotency_records (
                        tenant_id text NOT NULL DEFAULT 'TENANT-DEFAULT',
                        scope text NOT NULL,
                        payload jsonb NOT NULL,
                        updated_at timestamptz NOT NULL DEFAULT now(),
                        PRIMARY KEY (tenant_id, scope)
                    )
                    """
                )
                self.sync_postgres.execute(
                    """
                    CREATE TABLE IF NOT EXISTS service_heartbeats (
                        service_id text PRIMARY KEY,
                        service_role text NOT NULL,
                        instance_id text NOT NULL,
                        payload jsonb NOT NULL DEFAULT '{}'::jsonb,
                        last_seen_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                self.sync_postgres.execute(
                    "CREATE INDEX IF NOT EXISTS idx_aicheck_state_collection ON aicheck_state (tenant_id, collection)"
                )
                self.sync_postgres.execute(
                    "CREATE INDEX IF NOT EXISTS idx_aicheck_state_payload_gin ON aicheck_state USING gin (payload)"
                )
                self.sync_postgres.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_project_node_clause_packages_lookup
                    ON aicheck_state ((payload ->> 'projectId'), ((payload ->> 'nodeId')::integer))
                    WHERE collection = 'project_node_clause_packages'
                    """
                )
                self.sync_postgres.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_review_run_clause_snapshots_lookup
                    ON aicheck_state ((payload ->> 'reviewRunId'))
                    WHERE collection = 'review_run_clause_snapshots'
                    """
                )
                self.sync_postgres.execute(
                    "CREATE INDEX IF NOT EXISTS idx_idempotency_updated_at ON idempotency_records (tenant_id, updated_at DESC)"
                )
            self._postgres_schema_ready = True

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
                    """
                    SELECT collection, object_id, payload FROM aicheck_state
                    WHERE collection = ANY(%s)
                      AND tenant_id = %s
                    ORDER BY collection, object_id
                    """,
                    (selected_collections, configured_tenant_id()),
                ).fetchall()
            else:
                rows = self.sync_postgres.execute(
                    """
                    SELECT collection, object_id, payload FROM aicheck_state
                    WHERE tenant_id = %s
                    ORDER BY collection, object_id
                    """,
                    (configured_tenant_id(),),
                ).fetchall()
            has_project_seed = any(row[0] == STATE_COLLECTIONS["projects"] for row in rows)
            grouped: dict[str, list[dict[str, Any]]] = {}
            for collection_name, _, payload in rows:
                grouped.setdefault(collection_name, []).append(json.loads(json.dumps(payload)))
            for state_key, collection_name in STATE_COLLECTIONS.items():
                documents = grouped.get(collection_name, [])
                if selected_state_keys is not None and state_key in selected_state_keys:
                    loaded[state_key] = documents
                elif has_project_seed or documents:
                    loaded[state_key] = documents
            singleton_rows = self.sync_postgres.execute(
                "SELECT name, payload FROM aicheck_singletons WHERE tenant_id = %s",
                (configured_tenant_id(),),
            ).fetchall()
            for name, payload in singleton_rows:
                loaded[name] = json.loads(json.dumps(payload))
            idempotency_rows = self.sync_postgres.execute(
                "SELECT scope, payload FROM idempotency_records WHERE tenant_id = %s",
                (configured_tenant_id(),),
            ).fetchall()
            loaded["idempotency"] = {scope: json.loads(json.dumps(payload)) for scope, payload in idempotency_rows}
            loaded_baseline = {
                (str(collection_name), str(object_id)): self.canonical_persistence_payload(payload)
                for collection_name, object_id, payload in rows
            }
            self.mark_tenant_loaded()
            if selected_state_keys is not None:
                selected_collections_set = {
                    STATE_COLLECTIONS[key] for key in selected_state_keys if key in STATE_COLLECTIONS
                }
                for state_key in selected_state_keys:
                    if state_key in STATE_COLLECTIONS:
                        self.state[state_key] = loaded.get(state_key, [])
                self._persistence_baseline = {
                    key: value
                    for key, value in self._persistence_baseline.items()
                    if key[0] not in selected_collections_set
                }
                self._persistence_baseline.update(loaded_baseline)
                self.apply_tenant_scope()
                self.sync_postgres.commit()
                return
            self.state = loaded
            self.mark_tenant_loaded()
            self._persistence_baseline = {
                **loaded_baseline
            }
            self._singleton_baseline = {
                str(name): self.canonical_persistence_payload(payload)
                for name, payload in singleton_rows
            }
            self._idempotency_baseline = {
                str(scope): self.canonical_persistence_payload(payload)
                for scope, payload in idempotency_rows
            }
            self.apply_tenant_scope()
            self._pgvector_baseline_ids = {
                str(item.get("id"))
                for item in self.state.get("knowledge_vectors", [])
                if isinstance(item, dict) and item.get("id")
            }
            backfilled = False
            if selected_state_keys is None:
                if demo_data_enabled():
                    backfilled = self.apply_seed_compatibility_defaults(self.state)
                else:
                    backfilled = ensure_test_project_members(
                        self.state.get("projects", []),
                        self.state.setdefault("project_members", []),
                        self.state.get("tree_nodes", []),
                    )
            # psycopg starts a transaction for the SELECTs above when autocommit is off.
            # End that read transaction before any writer tries to flush the JSONB state.
            self.sync_postgres.commit()
            if not has_project_seed and demo_data_enabled():
                self.flush_to_sync_postgres()
            elif backfilled:
                self.flush_to_sync_postgres()

    def query_state_page_from_sync_postgres(
        self,
        state_key: str,
        *,
        tenant_id: str,
        filters: dict[str, Any] | None = None,
        keyword: str | None = None,
        keyword_fields: tuple[str, ...] | list[str] | None = None,
        page: int = 1,
        page_size: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Read a bounded tenant-scoped page without materializing global state.

        Published HTTP APIs use the offset fields (page/pageSize/total).  A
        non-empty cursor opts into keyset traversal while retaining the common
        response fields for backwards compatibility.
        """
        with self._sync_postgres_lock:
            self.configure_sync_postgres()
            if self.sync_postgres is None:
                return {
                    "items": [],
                    "page": max(1, int(page or 1)),
                    "pageSize": max(1, min(int(page_size or 20), 200)),
                    "total": 0,
                    "hasMore": False,
                    "nextCursor": None,
                    "paginationMode": "offset",
                }
            collection_name = STATE_COLLECTIONS.get(state_key)
            if not collection_name:
                raise KeyError(f"Unknown state collection: {state_key}")
            safe_page = max(1, int(page or 1))
            safe_size = max(1, min(int(page_size or 20), 200))
            base_clauses = ["tenant_id = %s", "collection = %s"]
            base_params: list[Any] = [tenant_id, collection_name]
            for field, value in (filters or {}).items():
                if value is None or value == "":
                    continue
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", str(field)):
                    raise ValueError(f"Unsafe JSON filter field: {field}")
                base_clauses.append("payload ->> %s = %s")
                base_params.extend([str(field), str(value)])

            normalized_keyword = str(keyword or "").strip()
            if normalized_keyword:
                fields = tuple(keyword_fields or ())
                if not fields:
                    raise ValueError("keyword_fields are required when keyword is provided")
                keyword_clauses: list[str] = []
                keyword_params: list[Any] = []
                for field in fields:
                    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", str(field)):
                        raise ValueError(f"Unsafe JSON keyword field: {field}")
                    keyword_clauses.append("COALESCE(payload ->> %s, '') ILIKE %s")
                    keyword_params.extend([str(field), f"%{normalized_keyword}%"])
                base_clauses.append(f"({' OR '.join(keyword_clauses)})")
                base_params.extend(keyword_params)

            normalized_cursor: str | None
            if cursor is None:
                normalized_cursor = None
            elif isinstance(cursor, str):
                normalized_cursor = cursor.strip() or None
            else:
                raise ValueError("Invalid keyset cursor")

            cursor_timestamp: datetime | None = None
            cursor_object_id: str | None = None
            if normalized_cursor:
                try:
                    padded = normalized_cursor + "=" * (-len(normalized_cursor) % 4)
                    decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
                    cursor_payload = json.loads(decoded.decode("utf-8"))
                    if not isinstance(cursor_payload, list) or len(cursor_payload) != 2:
                        raise ValueError("cursor payload must contain timestamp and object id")
                    cursor_updated_at, raw_cursor_object_id = cursor_payload
                    cursor_timestamp = datetime.fromisoformat(str(cursor_updated_at).replace("Z", "+00:00"))
                    if cursor_timestamp.tzinfo is None:
                        raise ValueError("cursor timestamp must include timezone")
                    cursor_object_id = str(raw_cursor_object_id)
                    if not cursor_object_id or len(cursor_object_id) > 512 or "\x00" in cursor_object_id:
                        raise ValueError("cursor object id is invalid")
                except Exception as exc:
                    raise ValueError("Invalid keyset cursor") from exc

            count_row = self.sync_postgres.execute(
                f"SELECT count(*) FROM aicheck_state WHERE {' AND '.join(base_clauses)}",
                tuple(base_params),
            ).fetchone()
            total = int(count_row[0]) if count_row else 0

            clauses = list(base_clauses)
            params = list(base_params)
            if normalized_cursor:
                assert cursor_timestamp is not None and cursor_object_id is not None
                clauses.append("(updated_at, object_id) < (%s::timestamptz, %s)")
                params.extend([cursor_timestamp.isoformat(), cursor_object_id])
                limit_params = [safe_size + 1]
                pagination_mode = "keyset"
            else:
                limit_params = [safe_size, (safe_page - 1) * safe_size]
                pagination_mode = "offset"

            pagination_sql = "LIMIT %s" if normalized_cursor else "LIMIT %s OFFSET %s"
            rows = self.sync_postgres.execute(
                f"""
                SELECT object_id, payload, updated_at
                FROM aicheck_state
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC, object_id DESC
                {pagination_sql}
                """,
                tuple([*params, *limit_params]),
            ).fetchall()
            self.sync_postgres.commit()
            selected = rows[:safe_size]
            if normalized_cursor:
                has_more = len(rows) > safe_size
            else:
                has_more = ((safe_page - 1) * safe_size) + len(selected) < total
            next_cursor = None
            if has_more and selected:
                object_id, _, updated_at = selected[-1]
                encoded = json.dumps([updated_at.isoformat(), str(object_id)], separators=(",", ":"))
                next_cursor = base64.urlsafe_b64encode(encoded.encode("utf-8")).decode("ascii").rstrip("=")
            return {
                "items": [self.clone(payload) for _, payload, _ in selected],
                "page": safe_page,
                "pageSize": safe_size,
                "total": total,
                "hasMore": has_more,
                "nextCursor": next_cursor,
                "paginationMode": pagination_mode,
            }

    def load_review_run_scope_from_sync_postgres(self, review_run_id: str) -> None:
        """Merge one ReviewRun aggregate into memory without loading unrelated historical state."""
        with self._sync_postgres_lock:
            self.configure_sync_postgres()
            if self.sync_postgres is None:
                return
            rows = self.sync_postgres.execute(
                """
                SELECT collection, object_id, payload
                FROM aicheck_state
                WHERE tenant_id = %s
                  AND (
                       (collection = 'review_runs' AND object_id = %s)
                       OR payload ->> 'reviewRunId' = %s
                  )
                ORDER BY collection, object_id
                """,
                (configured_tenant_id(), review_run_id, review_run_id),
            ).fetchall()
            review_run = next(
                (payload for collection, _, payload in rows if collection == STATE_COLLECTIONS["review_runs"]),
                None,
            )
            if review_run:
                ai_run_id = str(review_run.get("aiRunId") or "")
                project_id = str(review_run.get("projectId") or "")
                node_id = str(review_run.get("nodeId") or "")
                document_version_ids = [
                    str(item) for item in review_run.get("inputDocumentVersionIds") or [] if item
                ]
                document_scope_collections = [
                    STATE_COLLECTIONS[state_key]
                    for state_key in (
                        "versions",
                        "ocr_parse_results",
                        "extracted_fields",
                        "evidence_links",
                        "node_evidence_links",
                    )
                ]
                extra_rows = self.sync_postgres.execute(
                    """
                    SELECT collection, object_id, payload
                    FROM aicheck_state
                    WHERE tenant_id = %s
                      AND (
                           (collection = 'ai_runs' AND object_id = %s)
                           OR (collection = 'ai_trace_steps' AND payload ->> 'aiRunId' = %s)
                           OR (
                                collection = 'project_nodes'
                                AND payload ->> 'projectId' = %s
                                AND payload ->> 'nodeId' = %s
                           )
                           OR (
                                collection = ANY(%s)
                                AND (
                                    object_id = ANY(%s)
                                    OR payload ->> 'documentVersionId' = ANY(%s)
                                )
                           )
                      )
                    ORDER BY collection, object_id
                    """,
                    (
                        configured_tenant_id(),
                        ai_run_id,
                        ai_run_id,
                        project_id,
                        node_id,
                        document_scope_collections,
                        document_version_ids,
                        document_version_ids,
                    ),
                ).fetchall()
                rows.extend(extra_rows)
            self.sync_postgres.commit()

            state_key_by_collection = {value: key for key, value in STATE_COLLECTIONS.items()}
            grouped: dict[str, list[dict[str, Any]]] = {}
            for collection_name, _, payload in rows:
                state_key = state_key_by_collection.get(str(collection_name))
                if state_key:
                    grouped.setdefault(state_key, []).append(self.clone(payload))
            for state_key, incoming in grouped.items():
                incoming_ids = {
                    self.persistence_object_id(STATE_COLLECTIONS[state_key], item, index)
                    for index, item in enumerate(incoming)
                }
                retained = [
                    item
                    for index, item in enumerate(self.state.get(state_key, []))
                    if self.persistence_object_id(STATE_COLLECTIONS[state_key], item, index) not in incoming_ids
                ]
                self.state[state_key] = [*incoming, *retained]
            self._persistence_baseline.update(
                {
                    (str(collection_name), str(object_id)): self.canonical_persistence_payload(payload)
                    for collection_name, object_id, payload in rows
                }
            )
            self.apply_tenant_scope()

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
                SELECT collection, object_id, payload
                FROM aicheck_state
                WHERE tenant_id = %s
                  AND (
                       collection = ANY(%s)
                       OR (
                            collection = ANY(%s)
                            AND (
                                object_id = ANY(%s)
                                OR payload ->> 'documentId' = %s
                                OR payload ->> 'documentVersionId' = %s
                            )
                       )
                  )
                ORDER BY collection, object_id
                """,
                (
                    configured_tenant_id(),
                    global_collections,
                    scoped_collections,
                    [document_id, version_id],
                    document_id,
                    version_id,
                ),
            ).fetchall()
            grouped: dict[str, list[dict[str, Any]]] = {}
            for collection_name, _, payload in rows:
                grouped.setdefault(collection_name, []).append(json.loads(json.dumps(payload)))
            for state_key, collection_name in STATE_COLLECTIONS.items():
                if collection_name in global_collections or collection_name in scoped_collections:
                    loaded[state_key] = grouped.get(collection_name, [])
            for name, payload in self.sync_postgres.execute(
                "SELECT name, payload FROM aicheck_singletons WHERE tenant_id = %s",
                (configured_tenant_id(),),
            ).fetchall():
                loaded[name] = json.loads(json.dumps(payload))
            loaded["idempotency"] = {}
            self.state = loaded
            self._persistence_baseline = {
                (str(collection_name), str(object_id)): self.canonical_persistence_payload(payload)
                for collection_name, object_id, payload in rows
            }
            self._singleton_baseline = {
                str(name): self.canonical_persistence_payload(payload)
                for name, payload in self.sync_postgres.execute(
                    "SELECT name, payload FROM aicheck_singletons WHERE tenant_id = %s",
                    (configured_tenant_id(),),
                ).fetchall()
            }
            self._idempotency_baseline = {}
            self.apply_tenant_scope()
            self.sync_postgres.commit()

    def flush_to_sync_postgres(
        self,
        selected_state_keys: set[str] | None = None,
        selected_singleton_keys: set[str] | None = None,
    ) -> None:
        with self._sync_postgres_lock:
            self.configure_sync_postgres()
            if self.sync_postgres is None:
                return
            self.ensure_postgres_schema()
            plan = self._build_flush_dirty_plan(
                selected_state_keys=selected_state_keys,
                selected_singleton_keys=selected_singleton_keys,
            )
            if not plan["has_work"]:
                return
            dirty_documents: dict[tuple[str, str], tuple[dict[str, Any], str]] = plan["dirty_documents"]
            deleted_keys: list[tuple[str, str]] = plan["deleted_keys"]
            dirty_singletons: dict[str, str] = plan["dirty_singletons"]
            dirty_idempotency: dict[str, str] = plan["dirty_idempotency"]
            deleted_idempotency: list[str] = plan["deleted_idempotency"]
            new_audit_records: list[dict[str, Any]] = plan["new_audit_records"]
            vector_dirty = bool(plan["vector_dirty"])
            tenant_id = configured_tenant_id()
            with self.sync_postgres.transaction():
                if new_audit_records:
                    self.prepare_audit_records_for_postgres_transaction(
                        {"audit_logs": new_audit_records},
                        tenant_id,
                    )
                    self._refresh_prepared_audit_dirty_payloads(dirty_documents, new_audit_records)
                for collection_name, object_id in deleted_keys:
                    row = self.sync_postgres.execute(
                        "SELECT payload FROM aicheck_state WHERE tenant_id = %s AND collection = %s AND object_id = %s FOR UPDATE",
                        (tenant_id, collection_name, object_id),
                    ).fetchone()
                    self.assert_persistence_baseline((collection_name, object_id), row[0] if row else None)
                    self.sync_postgres.execute(
                        "DELETE FROM aicheck_state WHERE tenant_id = %s AND collection = %s AND object_id = %s",
                        (tenant_id, collection_name, object_id),
                    )
                for (collection_name, object_id), (_doc, payload) in dirty_documents.items():
                    key = (collection_name, object_id)
                    row = self.sync_postgres.execute(
                        "SELECT payload FROM aicheck_state WHERE tenant_id = %s AND collection = %s AND object_id = %s FOR UPDATE",
                        (tenant_id, collection_name, object_id),
                    ).fetchone()
                    if key in self._persistence_baseline:
                        self.assert_persistence_baseline(key, row[0] if row else None)
                        self.sync_postgres.execute(
                            "UPDATE aicheck_state SET payload = %s::jsonb, updated_at = now() WHERE tenant_id = %s AND collection = %s AND object_id = %s",
                            (payload, tenant_id, collection_name, object_id),
                        )
                    elif row:
                        if self.canonical_persistence_payload(row[0]) != payload:
                            raise RuntimeError(
                                f"Concurrent persistence insert detected for {collection_name}/{object_id}."
                            )
                    else:
                        cursor = self.sync_postgres.execute(
                            """
                            INSERT INTO aicheck_state (tenant_id, collection, object_id, payload, updated_at)
                            VALUES (%s, %s, %s, %s::jsonb, now())
                            ON CONFLICT (tenant_id, collection, object_id) DO NOTHING
                            """,
                            (tenant_id, collection_name, object_id, payload),
                        )
                        if cursor.rowcount == 0:
                            concurrent = self.sync_postgres.execute(
                                "SELECT payload FROM aicheck_state WHERE tenant_id = %s AND collection = %s AND object_id = %s",
                                (tenant_id, collection_name, object_id),
                            ).fetchone()
                            if not concurrent or self.canonical_persistence_payload(concurrent[0]) != payload:
                                raise RuntimeError(
                                    f"Concurrent persistence insert detected for {collection_name}/{object_id}."
                                )
                for state_key, payload in dirty_singletons.items():
                    row = self.sync_postgres.execute(
                        "SELECT payload FROM aicheck_singletons WHERE tenant_id = %s AND name = %s FOR UPDATE",
                        (tenant_id, state_key),
                    ).fetchone()
                    actual = self.canonical_persistence_payload(row[0]) if row else None
                    expected = self._singleton_baseline.get(state_key)
                    if expected != actual and actual != payload:
                        raise RuntimeError(f"Concurrent singleton update detected for {state_key}.")
                    self.sync_postgres.execute(
                        """
                        INSERT INTO aicheck_singletons (tenant_id, name, payload, updated_at)
                        VALUES (%s, %s, %s::jsonb, now())
                        ON CONFLICT (tenant_id, name)
                        DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                        """,
                        (tenant_id, state_key, payload),
                    )
                for scope in deleted_idempotency:
                    row = self.sync_postgres.execute(
                        "SELECT payload FROM idempotency_records WHERE tenant_id = %s AND scope = %s FOR UPDATE",
                        (tenant_id, scope),
                    ).fetchone()
                    actual = self.canonical_persistence_payload(row[0]) if row else None
                    if actual != self._idempotency_baseline[scope]:
                        raise RuntimeError(f"Concurrent idempotency update detected for {scope}.")
                    self.sync_postgres.execute(
                        "DELETE FROM idempotency_records WHERE tenant_id = %s AND scope = %s",
                        (tenant_id, scope),
                    )
                for scope, payload in dirty_idempotency.items():
                    row = self.sync_postgres.execute(
                        "SELECT payload FROM idempotency_records WHERE tenant_id = %s AND scope = %s FOR UPDATE",
                        (tenant_id, scope),
                    ).fetchone()
                    actual = self.canonical_persistence_payload(row[0]) if row else None
                    expected = self._idempotency_baseline.get(scope)
                    if expected != actual and actual != payload:
                        raise RuntimeError(f"Concurrent idempotency update detected for {scope}.")
                    self.sync_postgres.execute(
                        """
                        INSERT INTO idempotency_records (tenant_id, scope, payload, updated_at)
                        VALUES (%s, %s, %s::jsonb, now())
                        ON CONFLICT (tenant_id, scope)
                        DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                        """,
                        (tenant_id, scope, payload),
                    )
            self.sync_postgres.commit()
            self._apply_flush_baseline_updates(
                dirty_documents=dirty_documents,
                deleted_keys=deleted_keys,
                dirty_singletons=dirty_singletons,
                dirty_idempotency=dirty_idempotency,
                deleted_idempotency=deleted_idempotency,
            )
            if vector_dirty:
                self.flush_knowledge_vectors_to_pgvector()

    def upsert_state_records_to_sync_postgres(
        self,
        records_by_state_key: dict[str, list[dict[str, Any]]],
        idempotency_scopes: list[str] | None = None,
    ) -> None:
        """Persist selected records without replacing another process's state snapshot."""
        self.sync_state_records_to_sync_postgres(records_by_state_key, {}, idempotency_scopes=idempotency_scopes)

    def sync_state_records_to_sync_postgres(
        self,
        records_by_state_key: dict[str, list[dict[str, Any]]],
        deleted_object_ids_by_state_key: dict[str, list[str]],
        *,
        idempotency_scopes: list[str] | None = None,
    ) -> None:
        """Commit scoped business state and idempotency completion in one transaction."""
        with self._sync_postgres_lock:
            self.configure_sync_postgres()
            if self.sync_postgres is None:
                return
            self.ensure_postgres_schema()
            tenant_id = configured_tenant_id()
            with self.sync_postgres.transaction():
                self.prepare_audit_records_for_postgres_transaction(records_by_state_key, tenant_id)
                for state_key, object_ids in deleted_object_ids_by_state_key.items():
                    collection_name = STATE_COLLECTIONS.get(state_key)
                    if not collection_name:
                        raise KeyError(f"Unknown state collection: {state_key}")
                    selected_ids = sorted({str(item) for item in object_ids if item})
                    for object_id in selected_ids:
                        key = (collection_name, object_id)
                        if key not in self._persistence_baseline:
                            raise RuntimeError(f"Cannot delete {collection_name}/{object_id} without a loaded baseline.")
                        row = self.sync_postgres.execute(
                            "SELECT payload FROM aicheck_state WHERE tenant_id = %s AND collection = %s AND object_id = %s FOR UPDATE",
                            (tenant_id, collection_name, object_id),
                        ).fetchone()
                        self.assert_persistence_baseline(key, row[0] if row else None)
                        self.sync_postgres.execute(
                            "DELETE FROM aicheck_state WHERE tenant_id = %s AND collection = %s AND object_id = %s",
                            (tenant_id, collection_name, object_id),
                        )
                for state_key, docs in records_by_state_key.items():
                    collection_name = STATE_COLLECTIONS.get(state_key)
                    if not collection_name:
                        raise KeyError(f"Unknown state collection: {state_key}")
                    for index, doc in enumerate(docs):
                        if not isinstance(doc, dict):
                            continue
                        doc = self.persistence_tenant_document(doc)
                        object_id = self.persistence_object_id(collection_name, doc, index)
                        key = (collection_name, object_id)
                        payload = self.canonical_persistence_payload(doc)
                        row = self.sync_postgres.execute(
                            "SELECT payload FROM aicheck_state WHERE tenant_id = %s AND collection = %s AND object_id = %s FOR UPDATE",
                            (tenant_id, collection_name, object_id),
                        ).fetchone()
                        if key in self._persistence_baseline:
                            self.assert_persistence_baseline(key, row[0] if row else None)
                            self.sync_postgres.execute(
                                "UPDATE aicheck_state SET payload = %s::jsonb, updated_at = now() WHERE tenant_id = %s AND collection = %s AND object_id = %s",
                                (payload, tenant_id, collection_name, object_id),
                            )
                        elif row:
                            if self.canonical_persistence_payload(row[0]) != payload:
                                raise RuntimeError(
                                    f"Concurrent persistence insert detected for {collection_name}/{object_id}."
                                )
                        else:
                            self.sync_postgres.execute(
                                "INSERT INTO aicheck_state (tenant_id, collection, object_id, payload, updated_at) VALUES (%s, %s, %s, %s::jsonb, now())",
                                (tenant_id, collection_name, object_id, payload),
                            )
                for scope in idempotency_scopes or []:
                    idempotency_payload = self.state.get("idempotency", {}).get(scope)
                    if not isinstance(idempotency_payload, dict):
                        continue
                    encoded = self.canonical_persistence_payload(idempotency_payload)
                    row = self.sync_postgres.execute(
                        "SELECT payload FROM idempotency_records WHERE tenant_id = %s AND scope = %s FOR UPDATE",
                        (tenant_id, scope),
                    ).fetchone()
                    if row and self.canonical_persistence_payload(row[0]) != encoded:
                        raise RuntimeError(
                            f"Idempotency scope {scope} was concurrently completed with another response."
                        )
                    if not row:
                        self.sync_postgres.execute(
                            "INSERT INTO idempotency_records (tenant_id, scope, payload, updated_at) VALUES (%s, %s, %s::jsonb, now())",
                            (tenant_id, scope, encoded),
                        )
            self.sync_postgres.commit()
            self.update_scoped_persistence_baseline(records_by_state_key, deleted_object_ids_by_state_key)
            for scope in idempotency_scopes or []:
                payload = self.state.get("idempotency", {}).get(scope)
                if isinstance(payload, dict):
                    self._idempotency_baseline[scope] = self.canonical_persistence_payload(payload)

    def sync_state_records_to_sqlite(
        self,
        records_by_state_key: dict[str, list[dict[str, Any]]],
        deleted_object_ids_by_state_key: dict[str, list[str]],
        *,
        idempotency_scopes: list[str] | None = None,
    ) -> None:
        self.configure_sqlite(self.sqlite_path)
        if not self.sqlite_enabled:
            return
        self.ensure_sqlite_schema()
        tenant_id = configured_tenant_id()
        with self.sqlite_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for state_key, object_ids in deleted_object_ids_by_state_key.items():
                collection_name = STATE_COLLECTIONS.get(state_key)
                if not collection_name:
                    raise KeyError(f"Unknown state collection: {state_key}")
                for object_id in [str(item) for item in object_ids if item]:
                    key = (collection_name, object_id)
                    if key not in self._persistence_baseline:
                        raise RuntimeError(f"Cannot delete {collection_name}/{object_id} without a loaded baseline.")
                    row = connection.execute(
                        "SELECT payload FROM aicheck_state WHERE tenant_id = ? AND collection = ? AND object_id = ?",
                        (tenant_id, collection_name, object_id),
                    ).fetchone()
                    self.assert_persistence_baseline(key, json.loads(row[0]) if row else None)
                    connection.execute(
                        "DELETE FROM aicheck_state WHERE tenant_id = ? AND collection = ? AND object_id = ?",
                        (tenant_id, collection_name, object_id),
                    )
            for state_key, docs in records_by_state_key.items():
                collection_name = STATE_COLLECTIONS.get(state_key)
                if not collection_name:
                    raise KeyError(f"Unknown state collection: {state_key}")
                for index, doc in enumerate(docs):
                    if not isinstance(doc, dict):
                        continue
                    doc = self.persistence_tenant_document(doc)
                    object_id = self.persistence_object_id(collection_name, doc, index)
                    key = (collection_name, object_id)
                    payload = self.canonical_persistence_payload(doc)
                    row = connection.execute(
                        "SELECT payload FROM aicheck_state WHERE tenant_id = ? AND collection = ? AND object_id = ?",
                        (tenant_id, collection_name, object_id),
                    ).fetchone()
                    if key in self._persistence_baseline:
                        self.assert_persistence_baseline(key, json.loads(row[0]) if row else None)
                        connection.execute(
                            "UPDATE aicheck_state SET payload = ?, updated_at = CURRENT_TIMESTAMP WHERE tenant_id = ? AND collection = ? AND object_id = ?",
                            (payload, tenant_id, collection_name, object_id),
                        )
                    elif row:
                        if self.canonical_persistence_payload(json.loads(row[0])) != payload:
                            raise RuntimeError(
                                f"Concurrent persistence insert detected for {collection_name}/{object_id}."
                            )
                    else:
                        connection.execute(
                            "INSERT INTO aicheck_state (tenant_id, collection, object_id, payload, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                            (tenant_id, collection_name, object_id, payload),
                        )
            for scope in idempotency_scopes or []:
                idempotency_payload = self.state.get("idempotency", {}).get(scope)
                if not isinstance(idempotency_payload, dict):
                    continue
                encoded = self.canonical_persistence_payload(idempotency_payload)
                row = connection.execute(
                    "SELECT payload FROM idempotency_records WHERE tenant_id = ? AND scope = ?",
                    (tenant_id, scope),
                ).fetchone()
                if row and self.canonical_persistence_payload(json.loads(row[0])) != encoded:
                    raise RuntimeError(
                        f"Idempotency scope {scope} was concurrently completed with another response."
                    )
                if not row:
                    connection.execute(
                        "INSERT INTO idempotency_records (tenant_id, scope, payload, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                        (tenant_id, scope, encoded),
                    )
            connection.commit()
        self.update_scoped_persistence_baseline(records_by_state_key, deleted_object_ids_by_state_key)
        for scope in idempotency_scopes or []:
            payload = self.state.get("idempotency", {}).get(scope)
            if isinstance(payload, dict):
                self._idempotency_baseline[scope] = self.canonical_persistence_payload(payload)

    def upsert_idempotency_records_to_sync_postgres(self, scopes: list[str]) -> None:
        with self._sync_postgres_lock:
            self.configure_sync_postgres()
            if self.sync_postgres is None:
                return
            self.ensure_postgres_schema()
            tenant_id = configured_tenant_id()
            with self.sync_postgres.transaction():
                for scope in scopes:
                    payload = self.state.get("idempotency", {}).get(scope)
                    if not isinstance(payload, dict):
                        continue
                    encoded = self.canonical_persistence_payload(payload)
                    row = self.sync_postgres.execute(
                        "SELECT payload FROM idempotency_records WHERE tenant_id = %s AND scope = %s FOR UPDATE",
                        (tenant_id, scope),
                    ).fetchone()
                    if row and self.canonical_persistence_payload(row[0]) != encoded:
                        raise RuntimeError(f"Idempotency scope {scope} was concurrently completed with another response.")
                    if not row:
                        self.sync_postgres.execute(
                            "INSERT INTO idempotency_records (tenant_id, scope, payload, updated_at) VALUES (%s, %s, %s::jsonb, now())",
                            (tenant_id, scope, encoded),
                        )
            self.sync_postgres.commit()
            for scope in scopes:
                payload = self.state.get("idempotency", {}).get(scope)
                if isinstance(payload, dict):
                    self._idempotency_baseline[scope] = self.canonical_persistence_payload(payload)

    def upsert_idempotency_records_to_sqlite(self, scopes: list[str]) -> None:
        self.configure_sqlite(self.sqlite_path)
        if not self.sqlite_enabled:
            return
        self.ensure_sqlite_schema()
        tenant_id = configured_tenant_id()
        with self.sqlite_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for scope in scopes:
                payload = self.state.get("idempotency", {}).get(scope)
                if not isinstance(payload, dict):
                    continue
                encoded = self.canonical_persistence_payload(payload)
                row = connection.execute(
                    "SELECT payload FROM idempotency_records WHERE tenant_id = ? AND scope = ?",
                    (tenant_id, scope),
                ).fetchone()
                if row and self.canonical_persistence_payload(json.loads(row[0])) != encoded:
                    raise RuntimeError(f"Idempotency scope {scope} was concurrently completed with another response.")
                if not row:
                    connection.execute(
                        "INSERT INTO idempotency_records (tenant_id, scope, payload, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                        (tenant_id, scope, encoded),
                    )
            connection.commit()
        for scope in scopes:
            payload = self.state.get("idempotency", {}).get(scope)
            if isinstance(payload, dict):
                self._idempotency_baseline[scope] = self.canonical_persistence_payload(payload)

    def ensure_pgvector_schema(self) -> bool:
        with self._sync_postgres_lock:
            if self.sync_postgres is None:
                return False
            try:
                if production_runtime_ddl_disabled():
                    present = self.sync_postgres.execute(
                        "SELECT to_regclass('public.knowledge_vector_index')"
                    ).fetchone()
                    self.sync_postgres.commit()
                    return bool(present and present[0])
                self.sync_postgres.execute("CREATE EXTENSION IF NOT EXISTS vector")
                self.sync_postgres.execute(
                    """
                    CREATE TABLE IF NOT EXISTS knowledge_vector_index (
                        tenant_id text NOT NULL DEFAULT 'TENANT-DEFAULT',
                        id text NOT NULL,
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
                        updated_at timestamptz NOT NULL DEFAULT now(),
                        PRIMARY KEY (tenant_id, id)
                    )
                    """
                )
                self.sync_postgres.execute(
                    "ALTER TABLE knowledge_vector_index ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'TENANT-DEFAULT'"
                )
                self.sync_postgres.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_kvi_tenant_id ON knowledge_vector_index (tenant_id, id)"
                )
                self.sync_postgres.execute(
                    "CREATE INDEX IF NOT EXISTS idx_kvi_tenant_source ON knowledge_vector_index (tenant_id, source_id)"
                )
                self.sync_postgres.execute(
                    "CREATE INDEX IF NOT EXISTS idx_kvi_tenant_index_version ON knowledge_vector_index (tenant_id, index_version)"
                )
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
                persisted_ids: list[str] = []
                for row in self.state.get("knowledge_vectors", []) or []:
                    if int(row.get("dimensions") or 0) != OFFLINE_VECTOR_DIMENSIONS:
                        continue
                    payload = vector_payload_for_pg(row)
                    embedding = payload.get("embedding")
                    if not isinstance(embedding, list) or not embedding:
                        continue
                    persisted_ids.append(str(payload["id"]))
                    embedding_literal = "[" + ",".join(str(float(item)) for item in embedding) + "]"
                    self.sync_postgres.execute(
                        """
                        INSERT INTO knowledge_vector_index (
                            tenant_id, id, file_id, chunk_id, document_id, document_version_id, source_id,
                            embedding, dimensions, embedding_model, index_version, metadata, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s, %s::jsonb, now())
                        ON CONFLICT (tenant_id, id)
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
                            configured_tenant_id(),
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
                stale_ids = sorted(self._pgvector_baseline_ids - set(persisted_ids))
                if stale_ids:
                    self.sync_postgres.execute(
                        "DELETE FROM knowledge_vector_index WHERE tenant_id = %s AND id = ANY(%s)",
                        (configured_tenant_id(), stale_ids),
                    )
                self.sync_postgres.commit()
                self._pgvector_baseline_ids = set(persisted_ids)
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
            filters = ["tenant_id = %s"]
            params: list[Any] = [configured_tenant_id()]
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
                "extractionMethod": first_present(
                    fragment,
                    "extractionMethod",
                    "sourceEngine",
                    default="ocr_fragment_fallback",
                ),
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


def load_review_run_state(review_run_id: str) -> None:
    """Load only one ReviewRun aggregate for worker execution when PostgreSQL is available."""

    if postgres_persistence_configured():
        repo.load_review_run_scope_from_sync_postgres(review_run_id)
        return
    load_state(
        {
            "review_runs",
            "review_step_runs",
            "review_graph_nodes",
            "review_tool_calls",
            "review_events",
            "workflow_outbox",
            "workflow_inbox",
            "retrieval_traces",
            "rule_check_results",
            "ai_feedback",
            "review_run_clause_snapshots",
            "model_call_attempts",
            "ai_runs",
            "ai_trace_steps",
            "review_findings",
            "tree_nodes",
            "node_evidence_links",
            "documents",
            "versions",
            "extracted_fields",
            "evidence_links",
            "ocr_parse_results",
        }
    )


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


def flush_state(
    selected_state_keys: set[str] | None = None,
    selected_singleton_keys: set[str] | None = None,
) -> None:
    repo.apply_tenant_scope()
    if postgres_persistence_configured():
        repo.flush_to_sync_postgres(
            selected_state_keys=selected_state_keys,
            selected_singleton_keys=selected_singleton_keys,
        )
        return
    if not (repo.sqlite_enabled or repo.sqlite_path or os.getenv("AICHECK_SQLITE_PATH")):
        return
    repo.flush_to_sqlite(
        selected_state_keys=selected_state_keys,
        selected_singleton_keys=selected_singleton_keys,
    )


def flush_state_records(records_by_state_key: dict[str, list[dict[str, Any]]]) -> None:
    flush_mutation_records(records_by_state_key, [])


def flush_mutation_records(
    records_by_state_key: dict[str, list[dict[str, Any]]],
    idempotency_scopes: list[str],
) -> None:
    """Atomically commit a request's state/audit/outbox records and idempotency result."""

    records = {
        state_key: [
            apply_default_tenant(item, tenant_id=configured_tenant_id())
            for item in docs
            if isinstance(item, dict)
        ]
        for state_key, docs in records_by_state_key.items()
        if docs
    }
    selected_scopes = [scope for scope in idempotency_scopes if scope]
    if not records and not selected_scopes:
        return
    if postgres_persistence_configured():
        repo.upsert_state_records_to_sync_postgres(records, idempotency_scopes=selected_scopes)
        return
    if repo.sqlite_enabled or repo.sqlite_path or os.getenv("AICHECK_SQLITE_PATH"):
        repo.sync_state_records_to_sqlite(records, {}, idempotency_scopes=selected_scopes)


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
        repo.upsert_idempotency_records_to_sqlite(selected)
