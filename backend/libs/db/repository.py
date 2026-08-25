from __future__ import annotations

import asyncio
import base64
import hashlib
import json

import orjson
import logging
import os
import re
import sqlite3
import threading
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from libs.audit_context import current_request_audit_context
from libs.contracts.responses import server_time
from libs.db.state_freshness import StateFreshnessProbe
from libs.field_confidence import field_review_status, is_low_confidence
from libs.material_auto_classify import classify_material
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
from libs.ocr_readiness import (
    parse_result_ingestion_status,
    parse_result_outcome_status,
    parse_result_quality_blockers,
)
from libs.security.tenant import (
    apply_default_tenant,
    tenant_id_for_record,
)
from libs.security.tenant import (
    current_tenant_id as configured_tenant_id,
)

from .seed import (
    ROLE_ACTIONS,
    ROLE_NODE_MAP,
    ensure_inspection_project_members,
    ensure_test_project_members,
    fresh_state,
)

LOGGER = logging.getLogger("aicheck.repository")


# 空集合的水位线：一个不可能比任何真实 updated_at 更大的时刻。
# 不给空集合记水位线的话，它每次刷新都被判成「从没加载过」而整表重来——
# 而整表重来正是这套增量机制要消灭的东西。
_EPOCH_WATERMARK = datetime(1970, 1, 1, tzinfo=UTC)


class ConcurrentPersistenceError(RuntimeError):
    """Raised when optimistic persistence detects a newer stored record."""


class IllegalNodeStatusTransition(RuntimeError):
    """节点状态跳变不合法时抛出（N-4）。"""


# 已办结的终态：监检给出结论后，节点不应被其他流程无声改回。
NODE_STATUS_TERMINAL_STATUSES = {"已通过", "不适用"}
# 能重新打开终态节点的去向：都是显式的审查动作，有审计、有触发人。
# 「复审中」是人工发起的复审，「业务核验中」是人工触发的 AI 重跑——两者都合法。
NODE_STATUS_REOPENABLE_TARGETS = {"复审中", "业务核验中"}
# 明确禁止的去向：把已办结的节点拖回流程起点，等于无声推翻监检的终审结论。
# 只挡这几个而不是「白名单之外全挡」——真实业务里状态推进的路径不止一条，
# 定得太死会把正常流程也拦下来。
NODE_STATUS_FORBIDDEN_REOPEN_TARGETS = {"待提交", "部分提交", "需补正"}


STATE_COLLECTIONS = {
    "projects": "projects",
    "tree_nodes": "project_nodes",
    "requirements": "node_requirements",
    "documents": "documents",
    "versions": "document_versions",
    "bindings": "node_bindings",
    "evidence_links": "evidence_links",
    "node_evidence_links": "node_evidence_links",
    "evidence_snapshots": "evidence_snapshots",
    "evidence_manifests": "evidence_manifests",
    "evidence_shards": "evidence_shards",
    "fact_corrections": "fact_corrections",
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
    "project_invitations": "project_invitations",
    "registration_requests": "registration_requests",
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
    def __init__(self, *, seed: bool = True) -> None:
        """seed=False 用于「造完立刻整体替换 state」的游离视图。

        默认播种是主仓库需要的；但 project_document_read_view() 这类场景会在
        下一行就把 state 换掉，播种纯属浪费——线上实测 InMemoryRepository()
        单次 172ms（要重建 demo 种子、发布条款 release、绑定 69 个节点），
        占该函数总耗时 242ms 的 71%，而产物一次都没被读过。

        注意 seed=False 不能退回 blank_state()：它自己先调 fresh_state() 再把
        集合逐个清空，照样付全额播种成本。这里直接给空骨架，由调用方立即替换。
        """
        self._tenant_states: dict[str, dict[str, Any]] = {}
        self._tenant_persistence_baselines: dict[str, dict[tuple[str, str], str]] = {}
        self._tenant_singleton_baselines: dict[str, dict[str, str]] = {}
        self._tenant_idempotency_baselines: dict[str, dict[str, str]] = {}
        self._tenant_pgvector_baseline_ids: dict[str, set[str]] = {}
        self._loaded_tenants: set[str] = set()
        self.state = runtime_initial_state() if seed else {key: [] for key in STATE_COLLECTIONS}
        self._persistence_baseline: dict[tuple[str, str], str] = {}
        self._singleton_baseline: dict[str, str] = {}
        self._idempotency_baseline: dict[str, str] = {}
        self._pgvector_baseline_ids: set[str] = set()
        # 正在被某个请求改写、不许被并发加载覆盖的记录（见 pin_object）
        self._pinned_objects: set[tuple[str, str]] = set()
        self.apply_tenant_scope()
        self.state.setdefault("knowledge_chunks", [])
        self.state.setdefault("knowledge_vectors", [])
        self.state.setdefault("knowledge_embedding_batches", [])
        self.state.setdefault("knowledge_clauses", [])
        self.state.setdefault("knowledge_page_index_nodes", [])
        self.state.setdefault("knowledge_vector_corrections", [])
        self.state.setdefault("knowledge_chunk_quarantines", [])
        self.state.setdefault("node_evidence_links", [])
        self.state.setdefault("evidence_snapshots", [])
        self.state.setdefault("evidence_manifests", [])
        self.state.setdefault("evidence_shards", [])
        self.state.setdefault("fact_corrections", [])
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
        # 进程外写入的探测器（issue #9），见 libs/db/state_freshness
        self._state_probe = StateFreshnessProbe()
        # 每个集合已加载到哪个时刻。有它才能只拉变化的行，
        # 没有它（进程刚起、或该集合从没整表加载过）就退回整表加载。
        self._collection_watermarks: dict[tuple[str, str], Any] = {}

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

    def collection_is_loaded(self, state_key: str, tenant_id: str | None = None) -> bool:
        """这个集合在本进程里整表加载过吗？

        有水位线就等于加载过（水位线是整表加载时记下的）。增量刷新只拉「变化的行」，
        对**从没加载过**的集合来说，那等于什么都没拉——内存里是空的，
        而调用方会当成「库里就是没有」。所以增量之前必须先确认它加载过。
        """
        collection_name = STATE_COLLECTIONS.get(state_key, state_key)
        key = (str(tenant_id or configured_tenant_id()), str(collection_name))
        return key in self._collection_watermarks

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
        self.state.setdefault("evidence_snapshots", [])
        self.state.setdefault("evidence_manifests", [])
        self.state.setdefault("evidence_shards", [])
        self.state.setdefault("fact_corrections", [])
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

    def material_type_name_for_code(self, project_id: str | None, code: str) -> str:
        """按业务包的 materialTypes 把资料类型码解析成名称，解析不出就返回空串。

        名称是业务包里的权威定义，不该要求上传方再传一遍——传了不一致更麻烦。
        """
        if not code:
            return ""
        try:
            from libs.business_pack import DEFAULT_BUSINESS_PACK_ID, load_business_pack
        except Exception:
            return ""
        project = self.require_project(str(project_id or "")) or {}
        pack_id = project.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID
        try:
            pack = load_business_pack(str(pack_id))
        except Exception:
            return ""
        for item in pack.get("materialTypes") or []:
            if str(item.get("code") or "") == code:
                return str(item.get("name") or "")
        return ""

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
            return min(node_ids)
        return int(ROLE_NODE_MAP.get("inspection", 24))

    def project_for_role(self, project: dict[str, Any], role: str) -> dict[str, Any]:
        """按角色裁剪的项目对外表示。不带 businessPackSnapshot——它单个 383 KB，
        前端只用 businessPackSnapshotHash 判断版本（见 versioned_project 的说明）。

        剔除必须发生在深拷贝**之前**：原先是先 clone 整个项目再 pop 掉快照，
        等于每次都完整拷贝一份马上要丢的 383 KB。审计项总览一次要过 69 个节点，
        这一项就吃掉 494 ms——实测改成先剔除后拷贝是 1 ms。
        """
        cloned = self.clone(
            {key: value for key, value in project.items() if key != "businessPackSnapshot"}
        )
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
            self._reject_illegal_node_transition(project_id, node_id, before, status)
            node["status"] = status
            node["revision"] = int(node.get("revision", 1)) + 1
        return {"field": f"nodes.{node_id}.status", "before": before, "after": status}

    def _reject_illegal_node_transition(
        self, project_id: str, node_id: int, before: Any, after: str
    ) -> None:
        """拦住不该发生的节点状态跳变（N-4）。

        15 个调用点各自 set_node_status、互不知晓，没有任何前置状态校验——
        已通过的节点可以被任意改回「待提交」，监检的终审结论就这么被无声推翻。
        这里只挡明确非法的跳变，合法路径一律放行：真实业务里状态推进的路径不止一条，
        定得太死会把正常流程也拦下来。
        """
        current = str(before or "")
        target = str(after or "")
        if not current or current == target:
            return
        if current in NODE_STATUS_TERMINAL_STATUSES and target in NODE_STATUS_FORBIDDEN_REOPEN_TARGETS:
            raise IllegalNodeStatusTransition(
                f"节点 {node_id} 当前为「{current}」，不能直接变更为「{target}」。"
                f"已办结的节点需先经复审重新打开（{'、'.join(sorted(NODE_STATUS_REOPENABLE_TARGETS))}）。"
            )

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
        source_org_id: str | None = None,
        source_org_name: str | None = None,
        uploader_name: str | None = None,
        material_category: str | None = None,
        material_type_code: str | None = None,
        material_type_name: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        doc, version, knowledge_file, knowledge_task = self._build_document_records(
            project_id,
            file_name,
            file_type,
            source_org_id=source_org_id,
            source_org_name=source_org_name,
            uploader_name=uploader_name,
            material_category=material_category,
            material_type_code=material_type_code,
            material_type_name=material_type_name,
        )
        # 0817 第 2 条：施工方不必先选类别，上传后自动判。
        # **只在他没选时才判**——人选过的不许被机器覆盖。
        # 建议单独放 autoClassification，不直接写进 materialCategory：
        # 「系统猜的」和「人定的」混在一个字段里，之后谁也说不清哪个是哪个。
        if not material_category:
            suggestion = classify_material(file_name=file_name)
            if suggestion:
                doc["autoClassification"] = suggestion
                doc["materialCategory"] = suggestion["materialCategory"]
                doc["materialTypeCode"] = suggestion["materialTypeCode"]
                doc["materialTypeName"] = suggestion["materialTypeName"]
        self._insert_document_records(doc, version, knowledge_file, knowledge_task)
        return doc, version

    def _build_document_records(
        self,
        project_id: str,
        file_name: str,
        file_type: str,
        *,
        source_org_id: str | None = None,
        source_org_name: str | None = None,
        uploader_name: str | None = None,
        material_category: str | None = None,
        material_type_code: str | None = None,
        material_type_name: str | None = None,
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
        resolved_source_org_id = str(source_org_id or "").strip() or None
        resolved_source_org_name = source_org_name or (project or {}).get("contractorOrgName") or "项目参建单位"
        resolved_uploader_name = uploader_name or "系统"
        resolved_material_category = str(material_category or "").strip()
        resolved_material_type_code = str(material_type_code or "").strip()
        resolved_material_type_name = str(material_type_name or "").strip()
        # M-8：上传时声明了 materialTypeCode，名称却要调用方再传一遍，不传就落 None。
        # 业务包的 materialTypes 里就有权威名称，按 code 解析即可——NDT 专用路径是
        # 硬编码把名称填上的，通用路径没接上，于是同一份资料从两条路进来长得不一样。
        if resolved_material_type_code and not resolved_material_type_name:
            resolved_material_type_name = self.material_type_name_for_code(
                project_id, resolved_material_type_code
            )
        doc = {
            "id": document_id,
            "projectId": project_id,
            "businessPackId": (project or {}).get("businessPackId"),
            "materialTypeCode": resolved_material_type_code or "generic_review_material",
            "materialTypeName": resolved_material_type_name or None,
            "materialCategory": resolved_material_category or None,
            "fileName": file_name,
            "fileType": file_type or file_name.split(".")[-1],
            "sourceOrgId": resolved_source_org_id,
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
            # 第一版也要记文件名：不记的话历史列表里 V1 一栏是空的，
            # 而它恰恰是「原来传的是什么」这个问题的答案。
            "fileName": file_name,
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
            "materialTypeCode": resolved_material_type_code or "generic_review_material",
            "materialTypeName": resolved_material_type_name or None,
            "sourceOrgId": resolved_source_org_id,
            "sourceOrgName": resolved_source_org_name,
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

    def next_document_version(
        self,
        document: dict[str, Any],
        *,
        file_name: str | None = None,
        file_size: int = 0,
        content_hash: str | None = None,
        uploader_name: str | None = None,
    ) -> dict[str, Any]:
        """在既有文档上追加一个新版本，旧版本让位为历史。

        「替换」不是删掉重传：删掉重传会换一个新的 documentId，
        挂接关系、证据引用、审查意见里指向的那份资料就全断了——
        监检那边看到的是「原来那份不见了，多了一份陌生的」。
        同一个文档下加版本，历史留痕，引用不断。

        只在这里更新 isCurrent 与 currentVersionId，不动 bindings：
        绑定挂在文档上，本来就该跟着走。
        """
        document_id = str(document.get("id") or "")
        existing = [item for item in self.state["versions"] if item.get("documentId") == document_id]
        next_no = len(existing) + 1
        now = server_time()
        version_id = f"{document_id.replace('DOC-', 'DV-')}-V{next_no}"
        project_id = str(document.get("projectId") or "")
        for item in existing:
            if item.get("isCurrent"):
                item["isCurrent"] = False
                item["replacedAt"] = now
                item["updatedAt"] = now
        version = {
            "id": version_id,
            "documentId": document_id,
            "versionNo": f"V{next_no}",
            "hash": (content_hash or "").strip() or None,
            "fileSize": max(0, int(file_size or 0)),
            "storageKey": f"documents/{project_id}/{version_id}",
            "storageBucket": "documents",
            "ocrStatus": "排队中",
            "sliceStatus": "未切片",
            "vectorStatus": "未向量化",
            # 每个版本记自己的文件名。文档名保持不变（标识要稳），
            # 但「这一版换进去的是哪个文件」必须看得见——
            # 否则替换之后界面上还是原来那个名字，用户无从确认换对了没有。
            "fileName": (file_name or "").strip() or document.get("fileName"),
            "uploaderName": uploader_name or document.get("uploaderName") or "系统",
            "uploadTime": now,
            "isCurrent": True,
            "tenantId": configured_tenant_id(),
            "createdAt": now,
            "updatedAt": now,
        }
        self.state["versions"].append(version)
        document["currentVersionId"] = version_id
        document["currentOcrStatus"] = "排队中"
        document["fileStatus"] = "已上传"
        document["updatedAt"] = now
        return version

    def create_upload_session(
        self,
        project_id: str,
        files: list[dict[str, Any]],
        *,
        require_signed_urls: bool = False,
        local_upload_url_prefix: str | None = None,
        upload_headers: dict[str, str] | None = None,
        source_org_id: str | None = None,
        source_org_name: str | None = None,
        creator_user_id: str | None = None,
        uploader_name: str | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        session_id = f"UPS-{uuid4().hex[:10].upper()}"
        upload_token = uuid4().hex
        upload_urls = []
        session_files = []
        pending_records: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        for file in files:
            replace_document_id = str(file.get("replaceDocumentId") or "").strip()
            if replace_document_id:
                # 替换：在既有文档上加版本，不新建文档
                target = self.find_one("documents", replace_document_id)
                if target is None or str(target.get("projectId") or "") != project_id:
                    raise ValueError(f"要替换的资料不存在：{replace_document_id}")
                doc = target
                version = self.next_document_version(
                    target,
                    file_name=str(file.get("fileName") or "").strip() or None,
                    file_size=int(file.get("fileSize") or 0),
                    # contentHash in create-session input is only a later completion
                    # claim. No bytes have been stored yet, so it cannot authorize V2.
                    content_hash=None,
                    uploader_name=uploader_name,
                )
                knowledge_file = next(
                    (
                        item
                        for item in self.state["knowledge_files"]
                        if item.get("documentId") == replace_document_id
                    ),
                    None,
                )
                if knowledge_file is not None:
                    knowledge_file["documentVersionId"] = version["id"]
                    knowledge_file["ocrStatus"] = "排队中"
                    knowledge_file["updatedAt"] = server_time()
                knowledge_task = None
            else:
                doc, version, knowledge_file, knowledge_task = self._build_document_records(
                    project_id,
                    file.get("fileName") or "未命名资料.pdf",
                    file.get("fileType") or "pdf",
                    source_org_id=source_org_id,
                    source_org_name=source_org_name,
                    uploader_name=uploader_name,
                    material_category=file.get("materialCategory"),
                    material_type_code=file.get("materialTypeCode"),
                    material_type_name=file.get("materialTypeName"),
                    file_size=int(file.get("fileSize") or 0),
                    # Never seed bodyUploaded from an uploader-controlled declaration.
                    content_hash=None,
                    ocr_options=(
                        file.get("ocrOptions")
                        if isinstance(file.get("ocrOptions"), dict)
                        else None
                    ),
                )
            content_type = file.get("fileType") or "application/octet-stream"
            node_ids = sorted(
                {
                    int(node_id)
                    for node_id in (file.get("nodeIds") or [])
                    if str(node_id).strip().isdigit()
                }
            )
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
                    "materialTypeCode": doc.get("materialTypeCode"),
                    "materialTypeName": doc.get("materialTypeName"),
                    "nodeIds": node_ids,
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
                    "materialTypeCode": doc.get("materialTypeCode"),
                    "materialTypeName": doc.get("materialTypeName"),
                    "nodeIds": node_ids,
                    "storageBucket": "documents",
                    "storageKey": version["storageKey"],
                    "status": "待上传",
                }
            )
            # M-8：声明的 nodeIds 原先只回显在响应里、不落库，资料仍是游离状态，
            # 上传方以为已归属、实际还要再手工挂一次。NDT 专用路径是在会话建好后
            # 手工回填 document["nodeId"] 才对的；通用路径这里补上同样的落库。
            if node_ids:
                doc["nodeId"] = node_ids[0]
                if knowledge_file:
                    knowledge_file["nodeId"] = node_ids[0]
            # 替换分支的文档/版本已经在 next_document_version 里就地更新过了，
            # 再走一次插入会把同一个文档插两遍——列表上会出现两条同名资料。
            if not replace_document_id:
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
                "creatorOrgId": str(source_org_id or "").strip() or None,
                "creatorUserId": str(creator_user_id or "").strip() or None,
                "createdAt": server_time(),
                "expiresAt": object_storage.expires_at(),
            },
        )
        return session_id, upload_urls

    _UPLOAD_SESSION_TRANSACTION_STATE_KEYS = (
        "upload_sessions",
        "documents",
        "versions",
        "bindings",
        "ndt_reports",
        "knowledge_files",
        "knowledge_tasks",
    )

    def _remove_upload_session_from_memory(self, session_id: str) -> None:
        # A missing session does not imply its documents were deleted: replacement
        # sessions intentionally point at pre-existing documents.
        self.state["upload_sessions"] = [
            item for item in self.state.get("upload_sessions", [])
            if str(item.get("id") or "") != session_id
        ]
        self._persistence_baseline.pop(
            (STATE_COLLECTIONS["upload_sessions"], session_id), None
        )

    def _merge_authoritative_upload_session_rows(
        self,
        session: dict[str, Any],
        rows_by_state_key: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        document_ids = {
            str(item.get("documentId") or "")
            for item in session.get("files") or []
            if item.get("documentId")
        }
        version_ids = {
            str(item.get("documentVersionId") or "")
            for item in session.get("files") or []
            if item.get("documentVersionId")
        }
        session_id = str(session.get("id") or "")
        predicates = {
            "upload_sessions": lambda item: str(item.get("id") or "") == session_id,
            "documents": lambda item: str(item.get("id") or "") in document_ids,
            "versions": lambda item: (
                str(item.get("id") or "") in version_ids
                or str(item.get("documentId") or "") in document_ids
            ),
            "bindings": lambda item: str(item.get("documentId") or "") in document_ids,
            "ndt_reports": lambda item: str(item.get("fileId") or "") in document_ids,
            "knowledge_files": lambda item: str(item.get("documentId") or "") in document_ids,
            "knowledge_tasks": lambda item: (
                str(item.get("documentId") or "") in document_ids
                or str(item.get("documentVersionId") or "") in version_ids
            ),
        }
        authoritative = {"upload_sessions": [session], **rows_by_state_key}
        for state_key in self._UPLOAD_SESSION_TRANSACTION_STATE_KEYS:
            incoming = authoritative.get(state_key, [])
            predicate = predicates[state_key]
            self.state[state_key] = [
                *incoming,
                *[item for item in self.state.get(state_key, []) if not predicate(item)],
            ]
            apply_default_tenant(self.state[state_key], tenant_id=configured_tenant_id())
        return self.find_one("upload_sessions", session_id) or session

    def _load_upload_session_from_postgres_for_update(
        self,
        session_id: str,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        if self.sync_postgres is None:
            return None
        session_collection = STATE_COLLECTIONS["upload_sessions"]
        row = self.sync_postgres.execute(
            """
            SELECT payload FROM aicheck_state
            WHERE tenant_id = %s AND collection = %s AND object_id = %s
            FOR UPDATE
            """,
            (tenant_id, session_collection, session_id),
        ).fetchone()
        if not row:
            self._remove_upload_session_from_memory(session_id)
            return None
        session = dict(row[0])
        document_ids = sorted(
            {
                str(item.get("documentId") or "")
                for item in session.get("files") or []
                if item.get("documentId")
            }
        )
        version_ids = sorted(
            {
                str(item.get("documentVersionId") or "")
                for item in session.get("files") or []
                if item.get("documentVersionId")
            }
        )
        rows_by_state_key: dict[str, list[dict[str, Any]]] = {}
        if document_ids:
            rows_by_state_key["documents"] = [
                dict(item[0])
                for item in self.sync_postgres.execute(
                    """
                    SELECT payload FROM aicheck_state
                    WHERE tenant_id = %s AND collection = %s AND object_id = ANY(%s)
                    FOR UPDATE
                    """,
                    (tenant_id, STATE_COLLECTIONS["documents"], document_ids),
                ).fetchall()
            ]
            for state_key, document_field in (
                ("versions", "documentId"),
                ("bindings", "documentId"),
                ("ndt_reports", "fileId"),
                ("knowledge_files", "documentId"),
                ("knowledge_tasks", "documentId"),
            ):
                rows_by_state_key[state_key] = [
                    dict(item[0])
                    for item in self.sync_postgres.execute(
                        """
                        SELECT payload FROM aicheck_state
                        WHERE tenant_id = %s AND collection = %s
                          AND payload ->> %s = ANY(%s)
                        FOR UPDATE
                        """,
                        (
                            tenant_id,
                            STATE_COLLECTIONS[state_key],
                            document_field,
                            document_ids,
                        ),
                    ).fetchall()
                ]
        else:
            rows_by_state_key.update(
                {
                    "documents": [],
                    "versions": [],
                    "bindings": [],
                    "ndt_reports": [],
                    "knowledge_files": [],
                    "knowledge_tasks": [],
                }
            )
        if version_ids:
            known_version_ids = {
                str(item.get("id") or "") for item in rows_by_state_key.get("versions", [])
            }
            missing_versions = sorted(set(version_ids) - known_version_ids)
            if missing_versions:
                rows_by_state_key.setdefault("versions", []).extend(
                    dict(item[0])
                    for item in self.sync_postgres.execute(
                        """
                        SELECT payload FROM aicheck_state
                        WHERE tenant_id = %s AND collection = %s AND object_id = ANY(%s)
                        FOR UPDATE
                        """,
                        (tenant_id, STATE_COLLECTIONS["versions"], missing_versions),
                    ).fetchall()
                )
        return self._merge_authoritative_upload_session_rows(session, rows_by_state_key)

    def _load_upload_session_from_sqlite_for_update(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            """
            SELECT payload FROM aicheck_state
            WHERE tenant_id = ? AND collection = ? AND object_id = ?
            """,
            (tenant_id, STATE_COLLECTIONS["upload_sessions"], session_id),
        ).fetchone()
        if not row:
            self._remove_upload_session_from_memory(session_id)
            return None
        session = json.loads(row[0])
        document_ids = sorted(
            {
                str(item.get("documentId") or "")
                for item in session.get("files") or []
                if item.get("documentId")
            }
        )
        rows_by_state_key: dict[str, list[dict[str, Any]]] = {}
        placeholders = ",".join("?" for _ in document_ids) or "NULL"
        for state_key, selector in (
            ("documents", "object_id"),
            ("versions", "json_extract(payload, '$.documentId')"),
            ("bindings", "json_extract(payload, '$.documentId')"),
            ("ndt_reports", "json_extract(payload, '$.fileId')"),
            ("knowledge_files", "json_extract(payload, '$.documentId')"),
            ("knowledge_tasks", "json_extract(payload, '$.documentId')"),
        ):
            rows_by_state_key[state_key] = [
                json.loads(item[0])
                for item in connection.execute(
                    f"""
                    SELECT payload FROM aicheck_state
                    WHERE tenant_id = ? AND collection = ?
                      AND {selector} IN ({placeholders})
                    """,
                    [tenant_id, STATE_COLLECTIONS[state_key], *document_ids],
                ).fetchall()
            ]
        return self._merge_authoritative_upload_session_rows(session, rows_by_state_key)

    def _upload_session_aggregate_records(
        self,
        session_id: str,
    ) -> dict[str, list[dict[str, Any]]]:
        session = self.find_one("upload_sessions", session_id)
        if not session:
            return {}
        document_ids = {
            str(item.get("documentId") or "")
            for item in session.get("files") or []
            if item.get("documentId")
        }
        return {
            "upload_sessions": [session],
            "documents": [
                item for item in self.state.get("documents", [])
                if str(item.get("id") or "") in document_ids
            ],
            "versions": [
                item for item in self.state.get("versions", [])
                if str(item.get("documentId") or "") in document_ids
            ],
            "bindings": [
                item for item in self.state.get("bindings", [])
                if str(item.get("documentId") or "") in document_ids
            ],
            "ndt_reports": [
                item for item in self.state.get("ndt_reports", [])
                if str(item.get("fileId") or "") in document_ids
            ],
            "knowledge_files": [
                item for item in self.state.get("knowledge_files", [])
                if str(item.get("documentId") or "") in document_ids
            ],
            "knowledge_tasks": [
                item for item in self.state.get("knowledge_tasks", [])
                if str(item.get("documentId") or "") in document_ids
            ],
        }

    def _persist_upload_session_records_to_postgres(
        self,
        records_by_state_key: dict[str, list[dict[str, Any]]],
        tenant_id: str,
    ) -> None:
        if self.sync_postgres is None:
            return
        for state_key, documents in records_by_state_key.items():
            collection = STATE_COLLECTIONS[state_key]
            for index, document in enumerate(documents):
                scoped = self.persistence_tenant_document(document)
                object_id = self.persistence_object_id(collection, scoped, index)
                payload = self.canonical_persistence_payload(scoped)
                self.sync_postgres.execute(
                    """
                    INSERT INTO aicheck_state
                        (tenant_id, collection, object_id, payload, updated_at)
                    VALUES (%s, %s, %s, %s::jsonb, now())
                    ON CONFLICT (tenant_id, collection, object_id)
                    DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                    """,
                    (tenant_id, collection, object_id, payload),
                )

    def _persist_upload_session_records_to_sqlite(
        self,
        connection: sqlite3.Connection,
        records_by_state_key: dict[str, list[dict[str, Any]]],
        tenant_id: str,
    ) -> None:
        for state_key, documents in records_by_state_key.items():
            collection = STATE_COLLECTIONS[state_key]
            for index, document in enumerate(documents):
                scoped = self.persistence_tenant_document(document)
                object_id = self.persistence_object_id(collection, scoped, index)
                payload = self.canonical_persistence_payload(scoped)
                connection.execute(
                    """
                    INSERT INTO aicheck_state
                        (tenant_id, collection, object_id, payload, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT (tenant_id, collection, object_id)
                    DO UPDATE SET payload = excluded.payload, updated_at = CURRENT_TIMESTAMP
                    """,
                    (tenant_id, collection, object_id, payload),
                )

    def mutate_upload_session_atomically(
        self,
        session_id: str,
        mutation: Callable[[dict[str, Any] | None], tuple[Any, bool]],
    ) -> Any:
        """Run upload aggregate reload, mutation, and persistence under one lock."""
        with self._sync_postgres_lock:
            tenant_id = configured_tenant_id()
            if (
                self.sync_postgres is not None
                or self.postgres_dsn
                or os.getenv("AICHECK_DATABASE_URL")
                or os.getenv("DATABASE_URL")
            ):
                self.configure_sync_postgres()
                if self.sync_postgres is None:
                    raise RuntimeError("PostgreSQL upload transaction is unavailable.")
                self.ensure_postgres_schema()
                # Freshness probes use the shared synchronous connection and may leave
                # a read transaction open. End it before taking the session xact lock.
                self.sync_postgres.commit()
                with self.sync_postgres.transaction():
                    self.sync_postgres.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (f"aicheck:upload-session:{tenant_id}:{session_id}",),
                    )
                    session = self._load_upload_session_from_postgres_for_update(
                        session_id, tenant_id
                    )
                    self.update_scoped_persistence_baseline(
                        self._upload_session_aggregate_records(session_id), {}
                    )
                    snapshot = {
                        key: self.clone(self.state.get(key, []))
                        for key in self._UPLOAD_SESSION_TRANSACTION_STATE_KEYS
                    }
                    try:
                        result, should_commit = mutation(session)
                        if not should_commit:
                            for key, value in snapshot.items():
                                self.state[key] = value
                            return result
                        records = self._upload_session_aggregate_records(session_id)
                        self._persist_upload_session_records_to_postgres(records, tenant_id)
                    except BaseException:
                        for key, value in snapshot.items():
                            self.state[key] = value
                        raise
                self.sync_postgres.commit()
                self.update_scoped_persistence_baseline(records, {})
                return result

            if self.sqlite_enabled or self.sqlite_path or os.getenv("AICHECK_SQLITE_PATH"):
                self.configure_sqlite(self.sqlite_path)
                self.ensure_sqlite_schema()
                with self.sqlite_connection() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    session = self._load_upload_session_from_sqlite_for_update(
                        connection, session_id, tenant_id
                    )
                    self.update_scoped_persistence_baseline(
                        self._upload_session_aggregate_records(session_id), {}
                    )
                    snapshot = {
                        key: self.clone(self.state.get(key, []))
                        for key in self._UPLOAD_SESSION_TRANSACTION_STATE_KEYS
                    }
                    try:
                        result, should_commit = mutation(session)
                        if not should_commit:
                            for key, value in snapshot.items():
                                self.state[key] = value
                            connection.rollback()
                            return result
                        records = self._upload_session_aggregate_records(session_id)
                        self._persist_upload_session_records_to_sqlite(
                            connection, records, tenant_id
                        )
                        connection.commit()
                    except BaseException:
                        for key, value in snapshot.items():
                            self.state[key] = value
                        connection.rollback()
                        raise
                self.update_scoped_persistence_baseline(records, {})
                return result

            snapshot = {
                key: self.clone(self.state.get(key, []))
                for key in self._UPLOAD_SESSION_TRANSACTION_STATE_KEYS
            }
            try:
                result, should_commit = mutation(
                    self.find_one("upload_sessions", session_id)
                )
                if not should_commit:
                    for key, value in snapshot.items():
                        self.state[key] = value
                return result
            except BaseException:
                for key, value in snapshot.items():
                    self.state[key] = value
                raise

    @staticmethod
    def _require_upload_session_file_target(
        session: dict[str, Any] | None,
        document_version_id: str,
        *,
        project_id: str | None,
        upload_token: str | None,
        allowed_file_statuses: set[str] | None = None,
    ) -> dict[str, Any]:
        if not session or (project_id and str(session.get("projectId") or "") != project_id):
            raise ValueError("UPLOAD_SESSION_NOT_FOUND")
        if upload_token is not None and upload_token != session.get("uploadToken"):
            raise ValueError("UPLOAD_SESSION_TOKEN_INVALID")
        if session.get("status") != "待上传":
            raise ValueError("UPLOAD_SESSION_NOT_PENDING")
        file_entry = next(
            (
                item
                for item in session.get("files") or []
                if str(item.get("documentVersionId") or "") == document_version_id
            ),
            None,
        )
        if not file_entry:
            raise ValueError("UPLOAD_SESSION_FILE_NOT_FOUND")
        allowed_statuses = allowed_file_statuses or {"待上传"}
        if str(file_entry.get("status") or "") not in allowed_statuses:
            raise ValueError("UPLOAD_SESSION_FILE_NOT_PENDING")
        return file_entry

    def validate_upload_session_file_target(
        self,
        session_id: str,
        document_version_id: str,
        *,
        project_id: str,
        upload_token: str,
    ) -> dict[str, Any]:
        def inspect(session: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
            file_entry = self._require_upload_session_file_target(
                session,
                document_version_id,
                project_id=project_id,
                upload_token=upload_token,
                allowed_file_statuses={"待上传", "待落盘"},
            )
            document_id = str(file_entry.get("documentId") or "")
            document = self.find_one("documents", document_id)
            version = self.find_one("versions", document_version_id)
            if (
                not document
                or not version
                or str(version.get("documentId") or "") != document_id
                or str(document.get("currentVersionId") or "") != document_version_id
            ):
                raise ValueError("UPLOAD_SESSION_AGGREGATE_INCOMPLETE")
            return self.clone(file_entry), False

        return self.mutate_upload_session_atomically(session_id, inspect)

    def stage_upload_session_file(
        self,
        session_id: str,
        document_version_id: str,
        *,
        storage_bucket: str,
        storage_key: str,
        file_size: int,
        content_type: str,
        content_hash: str,
        temporary_storage_key: str | None = None,
        staging_id: str | None = None,
        project_id: str | None = None,
        upload_token: str | None = None,
    ) -> dict[str, Any]:
        """Durably reserve a verified body for post-commit filesystem promotion."""

        def mutate(session: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
            file_entry = self._require_upload_session_file_target(
                session,
                document_version_id,
                project_id=project_id,
                upload_token=upload_token,
            )
            document_id = str(file_entry.get("documentId") or "")
            document = self.find_one("documents", document_id)
            version = self.find_one("versions", document_version_id)
            if (
                not document
                or not version
                or str(version.get("documentId") or "") != document_id
                or str(document.get("currentVersionId") or "") != document_version_id
            ):
                raise ValueError("UPLOAD_SESSION_AGGREGATE_INCOMPLETE")
            staged_at = server_time()
            resolved_staging_id = str(staging_id or uuid4().hex)
            file_entry.update(
                {
                    "status": "待落盘",
                    "promotionStatus": "待落盘",
                    "promotionRetryable": True,
                    "stagedStorageBucket": storage_bucket,
                    "stagedStorageKey": storage_key,
                    "stagedFileSize": max(0, int(file_size)),
                    "stagedContentType": content_type,
                    "stagedContentHash": str(content_hash or "").strip() or None,
                    "stagedTemporaryStorageKey": (
                        str(temporary_storage_key or "").strip() or None
                    ),
                    "stagingId": resolved_staging_id,
                    "stagedAt": staged_at,
                }
            )
            for field in (
                "promotionErrorCode",
                "promotionFailedAt",
                "promotionCleanupRequired",
                "recoveryStorageKey",
                "staleRecoveryStorageKeys",
            ):
                file_entry.pop(field, None)
            assert session is not None
            session["updatedAt"] = staged_at
            return (
                {
                    "session": self.clone(session),
                    "file": self.clone(file_entry),
                    "document": self.clone(document),
                    "version": self.clone(version),
                },
                True,
            )

        return self.mutate_upload_session_atomically(session_id, mutate)

    def finalize_upload_session_file_promotion(
        self,
        session_id: str,
        document_version_id: str,
        *,
        project_id: str | None = None,
        upload_token: str | None = None,
        expected_staging_id: str | None = None,
        recovery_token: str | None = None,
    ) -> dict[str, Any]:
        """Publish the hash/body-uploaded state only after filesystem promotion."""

        def mutate(session: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
            if not session or (project_id and str(session.get("projectId") or "") != project_id):
                raise ValueError("UPLOAD_SESSION_NOT_FOUND")
            if upload_token is not None and upload_token != session.get("uploadToken"):
                raise ValueError("UPLOAD_SESSION_TOKEN_INVALID")
            if session.get("status") != "待上传":
                raise ValueError("UPLOAD_SESSION_NOT_PENDING")
            file_entry = next(
                (
                    item for item in session.get("files") or []
                    if str(item.get("documentVersionId") or "") == document_version_id
                ),
                None,
            )
            if not file_entry or file_entry.get("status") != "待落盘":
                raise ValueError("UPLOAD_SESSION_FILE_NOT_STAGED")
            if (
                expected_staging_id
                and str(file_entry.get("stagingId") or "") != expected_staging_id
            ):
                raise ValueError("UPLOAD_SESSION_STAGE_CHANGED")
            if recovery_token:
                if (
                    str(file_entry.get("recoveryToken") or "") != recovery_token
                    or file_entry.get("promotionStatus") != "恢复中"
                ):
                    raise ValueError("UPLOAD_SESSION_RECOVERY_LEASE_CHANGED")
            elif file_entry.get("promotionStatus") == "恢复中":
                raise ValueError("UPLOAD_SESSION_RECOVERY_IN_PROGRESS")
            document_id = str(file_entry.get("documentId") or "")
            document = self.find_one("documents", document_id)
            version = self.find_one("versions", document_version_id)
            if (
                not document
                or not version
                or str(version.get("documentId") or "") != document_id
                or str(document.get("currentVersionId") or "") != document_version_id
            ):
                raise ValueError("UPLOAD_SESSION_AGGREGATE_INCOMPLETE")
            uploaded_at = server_time()
            published_storage_key = (
                file_entry.get("recoveryStorageKey")
                if recovery_token
                else file_entry.get("stagedStorageKey")
            )
            version.update(
                {
                    "storageBucket": file_entry.get("stagedStorageBucket") or "local",
                    "storageKey": published_storage_key,
                    "fileSize": max(0, int(file_entry.get("stagedFileSize") or 0)),
                    "hash": str(file_entry.get("stagedContentHash") or "").strip() or None,
                    "uploadTime": uploaded_at,
                }
            )
            document.update(
                {
                    "fileStatus": "已上传",
                    "currentOcrStatus": "排队中",
                    "updatedAt": uploaded_at,
                }
            )
            file_entry.update(
                {
                    "status": "已上传",
                    "promotionStatus": "已落盘",
                    "promotionRetryable": False,
                    "storageBucket": version.get("storageBucket"),
                    "storageKey": version.get("storageKey"),
                    "fileSize": version.get("fileSize"),
                    "contentType": file_entry.get("stagedContentType"),
                    "uploadedAt": uploaded_at,
                }
            )
            for field in (
                "stagedStorageBucket",
                "stagedStorageKey",
                "stagedFileSize",
                "stagedContentType",
                "stagedContentHash",
                "stagedTemporaryStorageKey",
                "stagedAt",
                "promotionErrorCode",
                "promotionFailedAt",
                "promotionCleanupRequired",
                "stagingId",
                "recoveryToken",
                    "recoveryLeaseAt",
                    "recoveryStorageKey",
                    "staleRecoveryStorageKeys",
            ):
                file_entry.pop(field, None)
            assert session is not None
            session["updatedAt"] = uploaded_at
            return (
                {
                    "session": self.clone(session),
                    "file": self.clone(file_entry),
                    "document": self.clone(document),
                    "version": self.clone(version),
                },
                True,
            )

        return self.mutate_upload_session_atomically(session_id, mutate)

    def fail_upload_session_file_promotion(
        self,
        session_id: str,
        document_version_id: str,
        *,
        error_code: str,
        cleanup_required: bool = False,
        expected_staging_id: str | None = None,
        recovery_token: str | None = None,
    ) -> dict[str, Any]:
        """Compensate a failed promotion/finalization without claiming body upload."""

        def mutate(session: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
            if not session:
                return {"session": None, "file": None}, False
            file_entry = next(
                (
                    item for item in session.get("files") or []
                    if str(item.get("documentVersionId") or "") == document_version_id
                ),
                None,
            )
            if not file_entry:
                return {"session": self.clone(session), "file": None}, False
            if file_entry.get("status") == "已上传":
                return {
                    "session": self.clone(session),
                    "file": self.clone(file_entry),
                    "applied": False,
                }, False
            if (
                expected_staging_id
                and str(file_entry.get("stagingId") or "") != expected_staging_id
            ):
                return {
                    "session": self.clone(session),
                    "file": self.clone(file_entry),
                    "applied": False,
                }, False
            if recovery_token:
                if str(file_entry.get("recoveryToken") or "") != recovery_token:
                    return {
                        "session": self.clone(session),
                        "file": self.clone(file_entry),
                        "applied": False,
                    }, False
            elif file_entry.get("promotionStatus") == "恢复中":
                return {
                    "session": self.clone(session),
                    "file": self.clone(file_entry),
                    "applied": False,
                }, False
            failed_at = server_time()
            file_entry.update(
                {
                    "status": "待落盘" if cleanup_required else "待上传",
                    "promotionStatus": "待清理" if cleanup_required else "失败",
                    "promotionRetryable": True,
                    "promotionErrorCode": str(error_code or "PROMOTION_FAILED")[:120],
                    "promotionFailedAt": failed_at,
                    "promotionCleanupRequired": bool(cleanup_required),
                }
            )
            file_entry.pop("recoveryToken", None)
            file_entry.pop("recoveryLeaseAt", None)
            if not cleanup_required:
                for field in (
                    "stagedStorageBucket",
                    "stagedStorageKey",
                    "stagedFileSize",
                    "stagedContentType",
                    "stagedContentHash",
                    "stagedTemporaryStorageKey",
                    "stagedAt",
                    "stagingId",
                    "recoveryStorageKey",
                    "staleRecoveryStorageKeys",
                ):
                    file_entry.pop(field, None)
            version = self.find_one("versions", document_version_id)
            if version:
                version["hash"] = None
            document = self.find_one("documents", str(file_entry.get("documentId") or ""))
            if document:
                document["fileStatus"] = "上传失败"
                document["updatedAt"] = failed_at
            session["updatedAt"] = failed_at
            return {
                "session": self.clone(session),
                "file": self.clone(file_entry),
                "applied": True,
            }, True

        return self.mutate_upload_session_atomically(session_id, mutate)

    def claim_upload_session_file_recovery(
        self,
        session_id: str,
        document_version_id: str,
        *,
        expected_staging_id: str,
        recovery_token: str | None = None,
    ) -> dict[str, Any]:
        """CAS-claim one staged generation before recovery touches filesystem paths."""

        def mutate(session: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
            if not session:
                return {"session": None, "file": None, "applied": False}, False
            file_entry = next(
                (
                    item for item in session.get("files") or []
                    if str(item.get("documentVersionId") or "") == document_version_id
                ),
                None,
            )
            if (
                not file_entry
                or file_entry.get("status") != "待落盘"
                or str(file_entry.get("stagingId") or "") != expected_staging_id
            ):
                return {
                    "session": self.clone(session),
                    "file": self.clone(file_entry) if file_entry else None,
                    "applied": False,
                }, False
            existing_token = str(file_entry.get("recoveryToken") or "")
            lease_at = str(file_entry.get("recoveryLeaseAt") or "")
            if recovery_token:
                if existing_token != recovery_token:
                    return {
                        "session": self.clone(session),
                        "file": self.clone(file_entry),
                        "applied": False,
                    }, False
                file_entry["recoveryLeaseAt"] = server_time()
                session["updatedAt"] = file_entry["recoveryLeaseAt"]
                return {
                    "session": self.clone(session),
                    "file": self.clone(file_entry),
                    "recoveryToken": recovery_token,
                    "applied": True,
                }, True
            lease_stale = False
            if existing_token and lease_at:
                try:
                    lease_stale = datetime.strptime(
                        server_time(), "%Y-%m-%d %H:%M:%S"
                    ) - datetime.strptime(
                        lease_at, "%Y-%m-%d %H:%M:%S"
                    ) > timedelta(minutes=2)
                except ValueError:
                    lease_stale = True
            if existing_token and not lease_stale:
                return {
                    "session": self.clone(session),
                    "file": self.clone(file_entry),
                    "applied": False,
                }, False
            new_recovery_token = uuid4().hex
            previous_recovery_key = str(file_entry.get("recoveryStorageKey") or "")
            stale_recovery_keys = [
                str(item) for item in file_entry.get("staleRecoveryStorageKeys") or []
                if str(item)
            ]
            if previous_recovery_key and previous_recovery_key not in stale_recovery_keys:
                stale_recovery_keys.append(previous_recovery_key)
            staged_storage_key = str(file_entry.get("stagedStorageKey") or "")
            recovery_storage_key = (
                f"{staged_storage_key}.recovery-{new_recovery_token}"
                if staged_storage_key
                else ""
            )
            file_entry["promotionStatus"] = "恢复中"
            file_entry["recoveryToken"] = new_recovery_token
            file_entry["recoveryLeaseAt"] = server_time()
            file_entry["recoveryStorageKey"] = recovery_storage_key
            file_entry["staleRecoveryStorageKeys"] = stale_recovery_keys
            session["updatedAt"] = file_entry["recoveryLeaseAt"]
            return {
                "session": self.clone(session),
                "file": self.clone(file_entry),
                "recoveryToken": new_recovery_token,
                "applied": True,
            }, True

        return self.mutate_upload_session_atomically(session_id, mutate)

    def update_upload_session_file(
        self,
        session_id: str,
        document_version_id: str,
        *,
        storage_bucket: str,
        storage_key: str,
        file_size: int,
        content_type: str,
        content_hash: str,
        temporary_storage_key: str | None = None,
        staging_id: str | None = None,
        project_id: str | None = None,
        upload_token: str | None = None,
    ) -> dict[str, Any]:
        """Compatibility wrapper for non-filesystem callers and existing tests."""
        staged = self.stage_upload_session_file(
            session_id,
            document_version_id,
            storage_bucket=storage_bucket,
            storage_key=storage_key,
            file_size=file_size,
            content_type=content_type,
            content_hash=content_hash,
            temporary_storage_key=temporary_storage_key,
            staging_id=staging_id,
            project_id=project_id,
            upload_token=upload_token,
        )
        return self.finalize_upload_session_file_promotion(
            session_id,
            document_version_id,
            project_id=project_id,
            upload_token=upload_token,
            expected_staging_id=str(staged["file"].get("stagingId") or ""),
        )

    def upload_session_missing_body_hashes(self, session_id: str) -> list[str]:
        session = self.find_one("upload_sessions", session_id)
        if not session:
            return []
        missing: list[str] = []
        for file_entry in session.get("files") or []:
            version_id = str(file_entry.get("documentVersionId") or "").strip()
            version = self.find_one("versions", version_id) if version_id else None
            if not version or not str(version.get("hash") or "").strip():
                missing.append(version_id)
        return missing

    def complete_upload_session(self, session_id: str) -> list[dict[str, Any]]:
        session = self.find_one("upload_sessions", session_id)
        if not session:
            return []
        missing_version_ids = self.upload_session_missing_body_hashes(session_id)
        if missing_version_ids:
            raise ValueError("UPLOAD_SESSION_BODY_HASH_MISSING:" + ",".join(missing_version_ids))
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
        tasks = [
            item for item in self.state["knowledge_tasks"]
            if item.get("taskType") == "ocr"
        ]
        if version_id:
            exact_version = next(
                (
                    item for item in tasks
                    if str(item.get("documentVersionId") or "") == str(version_id)
                    and (
                        not document_id
                        or str(item.get("documentId") or "") == str(document_id)
                    )
                ),
                None,
            )
            if exact_version:
                return exact_version
            if document_id:
                legacy_target = next(
                    (
                        item for item in tasks
                        if str(item.get("targetId") or "") == f"KF-{document_id}"
                        and not str(item.get("documentVersionId") or "")
                        and (
                            not item.get("documentId")
                            or str(item.get("documentId") or "") == str(document_id)
                        )
                    ),
                    None,
                )
                if legacy_target:
                    return legacy_target
            return None
        if document_id:
            exact_document = next(
                (
                    item for item in tasks
                    if str(item.get("documentId") or "") == str(document_id)
                ),
                None,
            )
            if exact_document:
                return exact_document
            legacy_target = next(
                (
                    item for item in tasks
                    if str(item.get("targetId") or "") == f"KF-{document_id}"
                ),
                None,
            )
            if legacy_target:
                return legacy_target
            return None
        if file_name:
            return next(
                (
                    item for item in tasks
                    if str(item.get("targetName") or "") == str(file_name)
                ),
                None,
            )
        return None

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
        storage_bucket: str | None = None,
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
            # 桶名要跟着 key 一起记。上传会话存的是桶相对键（documents/项目/版本），
            # 桶名单独放在版本记录里；只带 key 的任务到了 worker 就拼不回对象地址。
            "storageBucket": storage_bucket or "documents",
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
        low_conf = [field for field in fields if is_low_confidence(field.get("confidence"))]
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
        ingestion_status = parse_result_ingestion_status(result)
        review_outcome_status = parse_result_outcome_status(result)
        success = ingestion_status == "usable"
        now = server_time()
        status = "已识别" if success else "识别失败"
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
            task["status"] = "成功" if success else "失败"
            task["progress"] = 100 if success else task.get("progress", 0)
            task["finishedAt"] = now
            task["updatedAt"] = now
            self._bump_revision(task)
            if not success:
                diagnostic_messages = [
                    str(item.get("code") or item.get("message") or item)
                    if isinstance(item, dict)
                    else str(item)
                    for item in result.get("diagnostics") or []
                ]
                task["errorMessage"] = "; ".join(
                    diagnostic_messages
                    or ["OCR result did not contain usable text or table content."]
                )
                self.append_task_log(task, "error", task["errorMessage"])
            else:
                task.pop("errorMessage", None)
                self.append_task_log(task, "info", "OCR 任务完成。")

        if not success:
            return {
                "documentId": document_id,
                "versionId": version_id,
                "status": "failed",
                "ingestionStatus": ingestion_status,
                "reviewOutcomeStatus": review_outcome_status,
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
        # 「引擎不报置信度」不等于「置信度低」。
        #
        # MinerU 的 VLM 通道逐片不给分数，适配层如实记了
        # provider_confidence_unavailable，可数值仍然是 0.0；落到这里被
        # `confidence >= 0.85` 一刀切成「低置信度」，结果是一整份许可证
        # 每个字段都显示成可疑——线上实测 5/5 全中。
        # 审查员看到满屏低置信度，要么逐条人工复核（白费工），
        # 要么开始无视这个标记（那它就再也不起作用了）。
        # 标成「置信度未知」：既不冒充已确认，也不诬告识别质量。
        confidence_unavailable = "provider_confidence_unavailable" in (
            ((result.get("quality") or {}).get("reasons") or [])
        )
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
                    # 阈值口径只有一份：libs/field_confidence。
                    # 原先这里和 routes.py 各写一个 0.85，改一处就会出现
                    # 「字段标着已确认，却仍然挂在阻塞项里」。
                    "reviewStatus": field_review_status(
                        confidence, confidence_unavailable=confidence_unavailable
                    ),
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
        return {
            "documentId": document_id,
            "versionId": version_id,
            "status": "success",
            "ingestionStatus": ingestion_status,
            "reviewOutcomeStatus": review_outcome_status,
            "qualityReasons": parse_result_quality_blockers(result),
            "fieldCount": len(fields),
        }

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
        if not chunks:
            # 抽到了文本，却一条分块都没留下——**全被噪声规则隔离了**。
            #
            # 这和「没抽到文本」是两回事，必须分开报：原先两者都走到下面那段，
            # 结果是 sliceStatus=已切片、chunkCount=0，看起来像切成功了，
            # 而报审那边提示「切片还在进行中」——切片早就完了，只是一个都没留下。
            # 报错指向的环节不是出问题的环节，这是本项目反复栽的同一个坑。
            #
            # 0819 实测：一份纯英文的资料整份被 symbol_ascii_only 隔离
            # （规则本身没错：中文语料里纯 ASCII 片段多是页眉页脚页码）。
            file["sliceStatus"] = "切片失败"
            file["chunkCount"] = 0
            file["vectorStatus"] = "向量化失败"
            file["vectorCount"] = 0
            file["sliceStatusReason"] = "all_chunks_quarantined"
            file["updatedAt"] = server_time()
            task = next(
                (
                    item
                    for item in self.state["knowledge_tasks"]
                    if item.get("taskType") == "slice" and item.get("targetId") == file_id
                ),
                None,
            )
            self.mark_task_failed(
                task,
                "切片任务失败：抽出的文本全部被判为噪声（页眉页脚、纯符号或纯英文），没有可索引内容。",
            )
            return {
                "fileId": file_id,
                "status": "failed",
                "chunkCount": 0,
                "errorMessage": "all_chunks_quarantined",
            }
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
        loaded.setdefault("evidence_snapshots", [])
        loaded.setdefault("evidence_manifests", [])
        loaded.setdefault("evidence_shards", [])
        loaded.setdefault("fact_corrections", [])
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

    def repair_clause_binding_drift(self, loaded: dict[str, Any]) -> bool:
        """修复「内容对、标签错」的项目条款绑定。

        规则重编号后，旧 release 的 packageId/sourceRuleId 用旧编号，而 nodeId 与条款
        内容已是新编号口径——同一条记录里两个编号指向不同规则。判定结果不受影响
        （条款内容是对的），但事后核查无法凭 clausePackageId 定位到真正使用的条款，
        而可溯源正是这个系统的核心价值。

        旧 release 自身就带着这个矛盾，不存在一个「正确的旧版本」可以保全，所以只能
        按当前业务包重绑——这是修复损坏，不是给项目换标准版本。

        判的是「记录自相矛盾」，不是「版本旧」：钉在旧版本但自洽的项目是合法的业务
        选择（业务方明确「标准换版暂不考虑」），不能一并冲掉。

        刻意不放在 apply_seed_compatibility_defaults 里——那个函数挂在
        demo_data_enabled() 下（默认 false），真实部署里根本不跑。数据完整性修复
        不能依赖 demo 播种开关。
        """
        from libs.business_pack import list_business_packs, load_business_pack
        from libs.business_pack.clause_store import (
            bind_project_node_clause_packages,
            clause_binding_inconsistencies,
            ensure_clause_state,
            publish_standard_clause_release,
        )

        ensure_clause_state(loaded)
        corrupt = clause_binding_inconsistencies(loaded)
        corrupt_project_ids = {item["projectId"] for item in corrupt if item["projectId"]}

        # 「一条绑定都没有」和「绑定自相矛盾」是同一类损坏的两种形态，都得修。
        #
        # 上一版只查矛盾，结果主项目 P-2026-HDCP-001 漏网：它钉在 2026.06.99，
        # 而那个 release 早已不存在（库里只发布了 2026.07.16），于是既没有绑定、
        # 也不会被矛盾检测挑中。后果不是报错，是每次打开节点都掉进知识检索兜底——
        # 线上实测每个节点首次 5.5 秒。
        #
        # 判据是「项目钉住的版本没有已发布的 release」：这时它不可能有条款依据，
        # 保留这个钉住没有任何意义。钉在**存在**的旧 release 上则照旧不动。
        published_releases = {
            str(item.get("releaseId") or "")
            for item in loaded.get("standard_clause_packages_db") or []
            if isinstance(item, dict) and item.get("lifecycleStatus") == "published"
        }
        bound_project_ids = {
            str(item.get("projectId") or "")
            for item in loaded.get("project_node_clause_packages") or []
            if isinstance(item, dict)
        }
        # 只有「本身带条款包」的业务包才谈得上绑定缺失。
        # compliance_audit_v1 / device_inspection_v1 没有 standardClausePackages，
        # 它们的项目永远绑不出东西——若当成损坏，每次启动都会重试一遍，
        # 把启动时间从 30 秒拉到 80 秒（实测线上 502 的直接原因）。
        #
        # 判据取自 YAML 业务包而不是「已发布 release」：首次修复时 release 还没发布，
        # 拿发布结果当前提会自我否定。
        packs_with_clauses = {
            str(summary["id"])
            for summary in list_business_packs()
            if load_business_pack(summary["id"]).get("standardClausePackages")
        }
        orphaned_project_ids = set()
        for project in loaded.get("projects", []):
            project_id = str(project.get("id") or "")
            if not project_id or project_id in bound_project_ids:
                continue
            pack_id = str(project.get("businessPackId") or "")
            if pack_id not in packs_with_clauses:
                continue  # 该业务包没有条款包，绑不出东西，不是损坏
            version = str(project.get("businessPackVersion") or "")
            if version and f"{pack_id}@{version}" in published_releases:
                continue  # 钉住的版本确实存在，只是还没绑——留给正常播种路径
            orphaned_project_ids.add(project_id)
        if orphaned_project_ids:
            LOGGER.warning(
                "检测到 %d 个项目没有任何条款绑定且钉住的业务包版本已不存在，"
                "按当前业务包重绑：%s",
                len(orphaned_project_ids),
                sorted(orphaned_project_ids),
            )
        corrupt_project_ids |= orphaned_project_ids

        if not corrupt_project_ids:
            return False
        if corrupt:
            LOGGER.warning(
                "检测到 %d 条条款绑定自相矛盾（nodeId 与 sourceRuleId 指向不同规则），"
                "涉及 %d 个项目，按当前业务包重绑：%s",
                len(corrupt),
                len({item["projectId"] for item in corrupt if item["projectId"]}),
                sorted({item["projectId"] for item in corrupt if item["projectId"]}),
            )

        for summary in list_business_packs():
            pack = load_business_pack(summary["id"])
            if not pack.get("standardClausePackages"):
                continue
            publish_standard_clause_release(loaded, pack)
            for project in loaded.get("projects", []):
                if project.get("businessPackId") != pack["id"]:
                    continue
                if str(project.get("id") or "") not in corrupt_project_ids:
                    continue
                bind_project_node_clause_packages(
                    loaded,
                    project,
                    pack,
                    bound_at=project.get("updatedAt"),
                )
                # 重绑后项目实际依据的就是新版本，version 必须跟上，否则
                # 「标签与内容不一致」只是从绑定记录挪到了项目记录上。
                project["businessPackVersion"] = pack["version"]

        remaining = clause_binding_inconsistencies(loaded)
        if remaining:
            LOGGER.error(
                "重绑后仍有 %d 条条款绑定自相矛盾，条款溯源不可信：%s",
                len(remaining),
                remaining[:5],
            )
        return True

    # 这些字段由业务包**生成**（scripts/generate_material_review_asset.py），
    # 后台没有单独的编辑入口，只随配置包整体导入导出。所以它们以配置文件为准。
    # 不在这个名单里的字段（备注、启用状态之类）一律不碰。
    MATERIAL_REVIEW_DERIVED_FIELDS = (
        "materialCategory",
        "businessModule",
        "materialTypeCode",
        "materialTypeName",
        "reviewClass",
    )

    def reconcile_material_review_points(
        self, loaded: dict[str, Any], seeded: dict[str, Any]
    ) -> bool:
        """把库里已有条目的**派生字段**对齐到配置文件。

        ## 为什么必须有这一步

        原先只有「库里没有才播种」。一旦播过种，**改配置文件就再也不生效了**——
        而且不报错：文件是新的，容器里也是新的，接口却一直回答旧值。

        2026-08-17 实测踩到：把两条 manufacturing_license 的资料类别从
        「资质证照」改成「材料验收与复验」，容器内文件确认已更新，
        接口仍然返回「资质证照」。查到这里才发现配置文件只是种子。

        **配置文件看起来是真相，实际只是初始值**——这是这个仓库里最贵的一类
        误解，因为它让「我改了」和「线上变了」之间断开，而中间没有任何提示。

        只对齐生成字段，按 id 匹配；库里多出来的条目原样保留（可能是配置包
        导入的），不做删除——对齐不该变成清空。
        """
        current = loaded.get("admin_config", {}).get("materialReviewPoints") or []
        expected = {
            str(item.get("id")): item
            for item in seeded.get("admin_config", {}).get("materialReviewPoints", [])
            if item.get("id")
        }
        if not expected:
            return False

        drifted: list[str] = []
        for item in current:
            source = expected.get(str(item.get("id")))
            if not source:
                continue
            for field in self.MATERIAL_REVIEW_DERIVED_FIELDS:
                if field not in source:
                    continue
                if item.get(field) != source[field]:
                    item[field] = source[field]
                    drifted.append(f"{item.get('id')}.{field}")
        if drifted:
            # 说清楚改了什么。静默地改数据比不改更难查。
            LOGGER.info(
                "资料审查点与配置文件不一致，已按配置对齐 %d 处：%s",
                len(drifted),
                drifted[:10],
            )
        return bool(drifted)

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
        elif self.reconcile_material_review_points(loaded, seeded):
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

    # 落库主键的候选字段。没有任何一个命中时会退化成**列表下标**，
    # 而下标不是身份：
    #
    #   submissions 是 insert(0, …) 插到头部的。新来一条，其余 60 条的
    #   主键整体位移一格 → 谁的 baseline 都对不上 → ConcurrentPersistenceError。
    #   api 和 4 个 worker 各自持有一份 state 各自 flush，列表顺序一旦分叉，
    #   它们就会互相覆盖对方的行，且**永远**再也协调不回来。
    #
    # 0818 线上实测就是这个形态：62 条 submissions 里 60 条按下标落库，
    # embed_knowledge 反复抛 submissions/2 冲突，新 API 容器连启动都过不去
    # （启动期一次写入即触发）。报错指向 submissions，被卡住的却是向量化和整个进程。
    #
    # 加字段时想清楚：这里要的是**跨进程稳定**的身份，不是「本地看着唯一」。
    PERSISTENCE_ID_FIELDS = (
        "id",
        "reviewRunId",
        "jobId",
        "parseResultId",
        "submissionId",
        "runId",
        "taskId",
    )

    def persistence_object_id(self, collection_name: str, doc: dict[str, Any], index: int) -> str:
        object_id = str(
            next(
                (value for field in self.PERSISTENCE_ID_FIELDS if (value := doc.get(field))),
                index,
            )
        )
        if collection_name == STATE_COLLECTIONS["requirements"] and doc.get("projectId") and doc.get("id"):
            return f"{doc['projectId']}:{doc['id']}"
        return object_id

    @staticmethod
    def canonical_persistence_payload(value: Any) -> str:
        """落库前的规范化表示，只用于**和基线比对**是否改过。

        用 orjson 而不是标准库 json：这个函数会对整份状态逐条调用，
        标准库实测 18 秒、orjson 2.6 秒（7 倍）。而这段时间占着解释器，
        同进程的所有请求都被挤住——0819 实测一次写入期间
        /api/healthz 要 16~26 秒，**不是写慢，是全站都慢**。

        OPT_NON_STR_KEYS 不能少：库里有以整数为键的映射，
        不带这个选项 orjson 会直接抛错，而标准库 json 会把它转成字符串。
        两边行为必须一致，否则同一条记录会被判成「改过」，天天重写。

        输出统一 decode 成 str：基线是字符串，比对的是字符串。
        """
        return orjson.dumps(
            value,
            option=orjson.OPT_SORT_KEYS | orjson.OPT_NON_STR_KEYS,
            default=str,
        ).decode("utf-8")

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
        """给要落库的记录打上本进程的租户标记。

        **返回的是浅拷贝，嵌套结构与内存状态共享**——调用方只能读它（序列化），
        不能改它的嵌套内容，否则会直接改到运行中的状态。
        现有调用点都是「取来→序列化→丢弃」，符合这个约定。

        原先这里是 deepcopy。它只为序列化一次就被丢掉，代价却极高：
        76323 条记录实测 deepcopy 7.4 秒、浅拷贝 0.1 秒（74 倍）。
        而落库前要对整份状态逐条做这件事，这段时间占着解释器，
        同进程的所有请求都被挤住——0819 实测一次写入期间
        /api/healthz 要十几秒，**不是写慢，是全站都慢**。
        """
        tenant_id = configured_tenant_id()
        explicit_tenant = str(document.get("tenantId") or document.get("tenant_id") or "").strip()
        if explicit_tenant and explicit_tenant != tenant_id:
            raise RuntimeError("Cross-tenant persistence is not allowed in this process.")
        if not explicit_tenant:
            document["tenantId"] = tenant_id
        scoped = dict(document)
        scoped.pop("tenant_id", None)
        scoped["tenantId"] = tenant_id
        return scoped

    def assert_persistence_baseline(self, key: tuple[str, str], stored_payload: Any) -> None:
        expected = self._persistence_baseline.get(key)
        actual = self.canonical_persistence_payload(stored_payload) if stored_payload is not None else None
        if expected != actual:
            raise ConcurrentPersistenceError(
                f"Concurrent persistence update detected for {key[0]}/{key[1]}; reload before retrying."
            )

    def pin_object(self, collection_name: str, object_id: str) -> None:
        """把一条记录钉住：并发的作用域加载不许用库里的副本覆盖它。

        `repo.state` 是**进程级共享**的，多个请求同时在上面读写。作用域加载
        最后一步是 `self.state[key] = [*incoming, *retained]`——incoming 是刚从
        库里读出来的克隆，同 id 的内存对象直接被顶掉，连 baseline 也一并改写。

        于是任何一个请求都可能在任何时刻，把另一个请求正在改的对象无声丢弃。

        2026-08-15 线上实测：监检点「发起缺项预审」，工作台每 3 秒轮询一次，
        审查跑完了（事件一路到 review_run.waiting_human），库里那条运行却仍是
        queued、revision=1——**执行改的那个对象在中途被换掉了，落库落的是旧的。**

        钉住只影响「覆盖」这一步：库里的新数据照常进 baseline 以外的判断，
        只是不拿它去顶一个正在被改的对象。执行结束必须解钉（unpin_object）。
        """
        self._pinned_objects.add((collection_name, str(object_id)))

    def unpin_object(self, collection_name: str, object_id: str) -> None:
        self._pinned_objects.discard((collection_name, str(object_id)))

    def object_is_pinned(self, collection_name: str, object_id: str) -> bool:
        return (collection_name, str(object_id)) in self._pinned_objects

    def apply_loaded_collection(self, state_key: str, incoming: list[dict[str, Any]]) -> None:
        """用加载结果替换一个集合，但**保留钉住的那几条**。

        原来这里是 `self.state[state_key] = loaded.get(state_key, [])`——整张列表
        丢弃重建。别的请求正在改的对象就此消失，改动无声蒸发。

        钉住的记录（pin_object）跳过替换；其余照旧。
        """
        if not self._pinned_objects:
            self.state[state_key] = incoming
            return
        collection_name = STATE_COLLECTIONS.get(state_key, state_key)
        pinned = [
            item
            for index, item in enumerate(self.state.get(state_key, []))
            if isinstance(item, dict)
            and self.object_is_pinned(
                collection_name, self.persistence_object_id(collection_name, item, index)
            )
        ]
        if not pinned:
            self.state[state_key] = incoming
            return
        pinned_ids = {
            self.persistence_object_id(collection_name, item, index)
            for index, item in enumerate(pinned)
        }
        self.state[state_key] = [
            *pinned,
            *[
                item
                for index, item in enumerate(incoming)
                if self.persistence_object_id(collection_name, item, index) not in pinned_ids
            ],
        ]

    def pinned_baseline_entries(self) -> dict[tuple[str, str], str]:
        """钉住记录的 baseline 快照。

        光保住对象还不够：加载会把 baseline 一起换成库里的值，落库时就会
        判定「没改过」而跳过写入——同一次丢失，换个入口而已。
        """
        return {key: value for key, value in self._persistence_baseline.items() if key in self._pinned_objects}

    def unchanged_since_baseline(self, key: tuple[str, str], payload: str) -> bool:
        """这条记录本次没被改过，因此没有任何内容需要写。

        作用域 flush（review_run_state_records 之类）交上来的是**整个聚合**，
        里面混着这次根本没动过的共享记录——最典型的是 ai_runs：
        执行期间 worker 进程会写它。于是出现这样一条链：

            我们加载 ai_run（记下 baseline）
              → worker 改了库里的 ai_run
              → 我们 flush，批次里捎带着那条没改过的 ai_run
              → baseline 与库里对不上 → ConcurrentPersistenceError
              → **整个事务回滚**，审查运行的完成状态一起没了

        2026-08-15 实测就是这么丢的：接口返回 waiting_human_review，
        库里永远停在 queued。冲突记录是 ai_runs，被牺牲的是 review_runs——
        **报错的和丢数据的不是同一条记录**，这也是它难查的原因。

        没改过就不写，冲突自然不成立；真改过还撞上，守卫照旧拦。
        """
        return self._persistence_baseline.get(key) == payload

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

    def load_from_sqlite(
        self, selected_state_keys: set[str] | None = None, tenant_id: str | None = None
    ) -> None:
        """按租户加载 SQLite 持久化状态（同 load_from_sync_postgres 的 N-5 修复）。"""
        self.configure_sqlite(self.sqlite_path)
        if not self.sqlite_enabled:
            return
        self.ensure_sqlite_schema()
        effective_tenant_id = str(tenant_id or configured_tenant_id())
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
                    [*selected_collections, effective_tenant_id],
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT collection, object_id, payload
                    FROM aicheck_state
                    WHERE tenant_id = ?
                    ORDER BY collection, object_id
                    """,
                    (effective_tenant_id,),
                ).fetchall()
            has_project_seed = any(row[0] == STATE_COLLECTIONS["projects"] for row in rows)
            grouped: dict[str, list[dict[str, Any]]] = {}
            for collection_name, _, payload in rows:
                grouped.setdefault(collection_name, []).append(json.loads(payload))
            for state_key, collection_name in STATE_COLLECTIONS.items():
                documents = grouped.get(collection_name, [])
                if selected_state_keys is not None and state_key in selected_state_keys or has_project_seed or documents:
                    loaded[state_key] = documents
            singleton_rows = connection.execute(
                """
                SELECT name, payload FROM aicheck_singletons
                WHERE tenant_id = ?
                """,
                (effective_tenant_id,),
            ).fetchall()
            for name, payload in singleton_rows:
                loaded[name] = json.loads(payload)
            idempotency_rows = connection.execute(
                "SELECT scope, payload FROM idempotency_records WHERE tenant_id = ?",
                (effective_tenant_id,),
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
            pinned_baseline = self.pinned_baseline_entries()
            for state_key in selected_state_keys:
                if state_key in STATE_COLLECTIONS:
                    self.apply_loaded_collection(state_key, loaded.get(state_key, []))
            self._persistence_baseline = {
                key: value
                for key, value in self._persistence_baseline.items()
                if key[0] not in selected_collections_set
            }
            self._persistence_baseline.update(loaded_baseline)
            self._persistence_baseline.update(pinned_baseline)
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
            # 与 demo 开关无关：损坏的条款溯源在任何部署里都必须修
            backfilled = self.repair_clause_binding_drift(self.state) or backfilled
        if not has_project_seed and demo_data_enabled() or backfilled:
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
                    raise ConcurrentPersistenceError(
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

    def refresh_stale_state_from_postgres(
        self, *, tenant_id: str | None = None, force: bool = False
    ) -> set[str]:
        """把进程外写入的集合重新加载进内存，返回实际重载了哪些（issue #9）。

        全量状态驻留内存、只在启动时加载一次，进程外的写入——worker 落库、运维
        改口令、修数脚本——本进程一概看不见，得重启容器才生效。线上踩过两次。

        两级探针，先问一个数，再问改了哪几个集合；只重载真变了的。
        探测失败一律当没变化并继续用内存数据：探针不是数据源，它挂了让整个 API
        跟着挂是本末倒置，而多用一会儿旧数据，下次探针成功就自愈。
        """
        with self._sync_postgres_lock:
            self.configure_sync_postgres()
            if self.sync_postgres is None:
                return set()
            effective_tenant_id = str(tenant_id or configured_tenant_id())
            try:
                row = self.sync_postgres.execute(
                    "SELECT max(updated_at) FROM aicheck_state WHERE tenant_id = %s",
                    (effective_tenant_id,),
                ).fetchone()
            except Exception as exc:  # noqa: BLE001 — 见 docstring：探测失败不阻断请求
                LOGGER.warning("state_freshness_probe_failed: %s", exc)
                return set()
            global_max = row[0] if row else None
            if not force and not self._state_probe.needs_second_stage(global_max=global_max):
                # 一级没动就到此为止——这正是这套机制便宜的原因
                self._state_probe.stale_collections(global_max=global_max, force=force)
                return set()
            try:
                rows = self.sync_postgres.execute(
                    """
                    SELECT collection, max(updated_at) FROM aicheck_state
                    WHERE tenant_id = %s GROUP BY collection
                    """,
                    (effective_tenant_id,),
                ).fetchall()
            except Exception as exc:  # noqa: BLE001 — 同上
                LOGGER.warning("state_freshness_detail_probe_failed: %s", exc)
                return set()
            collection_max = {str(item[0]): item[1] for item in rows}
            stale_collections = self._state_probe.stale_collections(
                global_max=global_max, collection_max=collection_max, force=force
            )
            if not stale_collections:
                return set()
            # 库里的表名换回 state 的键名——两边命名不一致，直接拿表名去 load 会静默漏掉
            reverse = {table: key for key, table in STATE_COLLECTIONS.items()}
            state_keys = {reverse[name] for name in stale_collections if name in reverse}
            if not state_keys:
                return set()
        # 只拉变化的行。整表重载的代价见 refresh_collections_incrementally：
        # 向量化期间每个请求要先付 25 秒以上，页面看起来就是一直在转圈。
        self.refresh_collections_incrementally(state_keys, tenant_id=tenant_id)
        LOGGER.info("state_reloaded_from_postgres: %s", sorted(state_keys))
        return state_keys

    def refresh_collections_incrementally(
        self, state_keys: set[str], tenant_id: str | None = None
    ) -> None:
        """只把**变化过的行**拉回内存，而不是整张表重来。

        ## 为什么必须这样

        请求中间件发现某个集合过期就整表重载。而向量化每写一个断点批次就
        弄脏两张大表：knowledge_vectors 61 MB（重载 17.4 秒）、
        knowledge_embedding_batches 21 MB（7.6 秒）。于是只要有**任何一份资料
        在向量化**，其后每个 API 请求都要先付 25 秒以上——知识网络页面实测
        47 秒才出内容，看起来就是「一直在转圈」。而那个页面自己构建只要 0.15 秒。

        这不是批量重建才有的问题：正常业务上传一份资料，同样会让全站变慢几分钟。

        ## 判断变化的方式

        - 变化行：updated_at > 本集合水位线（这些行取 payload）；
        - 删除行：另查一次**只取 object_id** 的全量清单做差集——
          只有 id 的查询很便宜，而漏掉删除会让内存里留下库里已经没有的记录。

        没有水位线时（进程刚起、或该集合没整表加载过）退回整表加载，
        这样行为与原先完全一致，只是快了。
        """
        with self._sync_postgres_lock:
            effective_tenant_id = str(tenant_id or configured_tenant_id())
            self.configure_sync_postgres()
            if self.sync_postgres is None:
                return
            full_reload_keys: set[str] = set()
            for state_key in sorted(state_keys):
                collection_name = STATE_COLLECTIONS.get(state_key)
                if not collection_name:
                    continue
                watermark = self._collection_watermarks.get((effective_tenant_id, collection_name))
                if watermark is None:
                    full_reload_keys.add(state_key)
                    continue
                try:
                    changed = self.sync_postgres.execute(
                        """
                        SELECT object_id, payload, updated_at FROM aicheck_state
                        WHERE tenant_id = %s AND collection = %s AND updated_at > %s
                        """,
                        (effective_tenant_id, collection_name, watermark),
                    ).fetchall()
                    live_ids = {
                        str(row[0])
                        for row in self.sync_postgres.execute(
                            "SELECT object_id FROM aicheck_state WHERE tenant_id = %s AND collection = %s",
                            (effective_tenant_id, collection_name),
                        ).fetchall()
                    }
                except Exception as exc:  # noqa: BLE001 - 增量失败就退回整表，别让请求挂掉
                    LOGGER.warning("incremental_refresh_failed: %s %s", collection_name, exc)
                    full_reload_keys.add(state_key)
                    continue
                self._merge_incremental_collection(
                    state_key,
                    collection_name,
                    changed,
                    live_ids,
                    tenant_id=effective_tenant_id,
                )
            if full_reload_keys:
                # 锁是可重入的（RLock），整表加载会自己再取一次
                self.load_from_sync_postgres(full_reload_keys, tenant_id=tenant_id)

    def _merge_incremental_collection(
        self,
        state_key: str,
        collection_name: str,
        changed_rows: list[Any],
        live_ids: set[str],
        *,
        tenant_id: str,
    ) -> None:
        """把变化行并进内存列表，并删掉库里已经不存在的记录。

        钉住的对象（pin_object）不动：别的请求正在改它，用库里的副本覆盖等于
        让那次改动无声蒸发——整表加载路径同样有这条保护，见 apply_loaded_collection。
        """
        current = [item for item in (self.state.get(state_key) or []) if isinstance(item, dict)]
        index_by_id: dict[str, int] = {}
        for index, item in enumerate(current):
            index_by_id.setdefault(self.persistence_object_id(collection_name, item, index), index)

        highest = self._collection_watermarks.get((tenant_id, collection_name))
        appended: list[dict[str, Any]] = []
        for object_id, payload, updated_at in changed_rows:
            key = str(object_id)
            if self.object_is_pinned(collection_name, key):
                continue
            document = json.loads(json.dumps(payload))
            position = index_by_id.get(key)
            if position is None:
                appended.append(document)
            else:
                current[position] = document
            self._persistence_baseline[(collection_name, key)] = self.canonical_persistence_payload(payload)
            if highest is None or (updated_at is not None and updated_at > highest):
                highest = updated_at

        merged = [*appended, *current] if appended else current
        if len(merged) != len(live_ids) or appended:
            kept: list[dict[str, Any]] = []
            for index, item in enumerate(merged):
                object_id = self.persistence_object_id(collection_name, item, index)
                if object_id in live_ids or self.object_is_pinned(collection_name, object_id):
                    kept.append(item)
                else:
                    self._persistence_baseline.pop((collection_name, object_id), None)
            merged = kept

        self.state[state_key] = merged
        apply_default_tenant(self.state.get(state_key), tenant_id=tenant_id)
        if highest is not None:
            self._collection_watermarks[(tenant_id, collection_name)] = highest

    def load_from_sync_postgres(
        self, selected_state_keys: set[str] | None = None, tenant_id: str | None = None
    ) -> None:
        """按租户加载持久化状态。

        N-5：写入按 JWT 里的 tid 落库，读取却一律按 configured_tenant_id() 环境变量。
        多租户部署重启后，非 configured 租户的数据在库里存在却永不加载，而
        main.py 又把 claims.tid 标记为「已加载」——对使用方等同于数据丢失。
        现在按请求租户参数化；不传时仍回落到 configured_tenant_id()，单租户部署行为不变。
        """
        with self._sync_postgres_lock:
            effective_tenant_id = str(tenant_id or configured_tenant_id())
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
                    SELECT collection, object_id, payload, updated_at FROM aicheck_state
                    WHERE collection = ANY(%s)
                      AND tenant_id = %s
                    ORDER BY collection, object_id
                    """,
                    (selected_collections, effective_tenant_id),
                ).fetchall()
            else:
                rows = self.sync_postgres.execute(
                    """
                    SELECT collection, object_id, payload, updated_at FROM aicheck_state
                    WHERE tenant_id = %s
                    ORDER BY collection, object_id
                    """,
                    (configured_tenant_id(),),
                ).fetchall()
            has_project_seed = any(row[0] == STATE_COLLECTIONS["projects"] for row in rows)
            grouped: dict[str, list[dict[str, Any]]] = {}
            # 记下每个集合加载到哪个时刻——下次刷新才有可能只拉变化的行
            for collection_name, _, payload, updated_at in rows:
                # 不再 json.loads(json.dumps(payload)) 兜一圈：psycopg 每行都返回
                # 新解析出来的对象，没有共享，那次「防御性深拷贝」纯属白做——
                # 线上实测 46321 行要 15.5 秒，占整份加载的 43%。
                grouped.setdefault(collection_name, []).append(payload)
                key = (effective_tenant_id, str(collection_name))
                seen = self._collection_watermarks.get(key)
                if updated_at is not None and (seen is None or updated_at > seen):
                    self._collection_watermarks[key] = updated_at
            for collection_name in selected_collections or []:
                # 空集合也要有水位线，否则每次都判成「没加载过」而整表重来
                self._collection_watermarks.setdefault((effective_tenant_id, str(collection_name)), _EPOCH_WATERMARK)
            # 建立过期探针的基线——见 StateFreshnessProbe.prime 的说明：
            # 不建的话下一次探测只建基线、不刷新，worker 会一直读到旧数据。
            collection_max: dict[str, Any] = {}
            global_max: Any = None
            for collection_name, _object_id, _payload, updated_at in rows:
                if updated_at is None:
                    continue
                name = str(collection_name)
                if collection_max.get(name) is None or updated_at > collection_max[name]:
                    collection_max[name] = updated_at
                if global_max is None or updated_at > global_max:
                    global_max = updated_at
            self._state_probe.prime(global_max=global_max, collection_max=collection_max)
            for state_key, collection_name in STATE_COLLECTIONS.items():
                documents = grouped.get(collection_name, [])
                if selected_state_keys is not None and state_key in selected_state_keys or has_project_seed or documents:
                    loaded[state_key] = documents
            singleton_rows = self.sync_postgres.execute(
                "SELECT name, payload FROM aicheck_singletons WHERE tenant_id = %s",
                (effective_tenant_id,),
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
                for collection_name, object_id, payload, _updated_at in rows
            }
            self.mark_tenant_loaded()
            if selected_state_keys is not None:
                selected_collections_set = {
                    STATE_COLLECTIONS[key] for key in selected_state_keys if key in STATE_COLLECTIONS
                }
                pinned_baseline = self.pinned_baseline_entries()
                for state_key in selected_state_keys:
                    if state_key in STATE_COLLECTIONS:
                        self.apply_loaded_collection(state_key, loaded.get(state_key, []))
                self._persistence_baseline = {
                    key: value
                    for key, value in self._persistence_baseline.items()
                    if key[0] not in selected_collections_set
                }
                self._persistence_baseline.update(loaded_baseline)
                self._persistence_baseline.update(pinned_baseline)
                self.apply_tenant_scope()
                self.sync_postgres.commit()
                return
            self.state = loaded
            self.mark_tenant_loaded()
            # 整表加载完成 → 每个集合都算「加载过」，**包括一行都没有的**。
            #
            # 漏掉空集合的后果不是数据错，是性能塌方：collection_is_loaded 对它们
            # 永远返回 False，于是 refresh_worker_state 每次都判定「还没加载过」
            # 而整份重来。线上实测——worker 每个任务白付 38 秒，改了增量也没用，
            # 因为根本走不到增量那条路。
            for collection_name in STATE_COLLECTIONS.values():
                self._collection_watermarks.setdefault(
                    (effective_tenant_id, str(collection_name)), _EPOCH_WATERMARK
                )
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
                # 与 demo 开关无关：损坏的条款溯源在任何部署里都必须修
                backfilled = self.repair_clause_binding_drift(self.state) or backfilled
            # psycopg starts a transaction for the SELECTs above when autocommit is off.
            # End that read transaction before any writer tries to flush the JSONB state.
            self.sync_postgres.commit()
            if not has_project_seed and demo_data_enabled() or backfilled:
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

    def project_document_read_view(self, project_id: str) -> InMemoryRepository:
        """Return a detached project-document view from current PostgreSQL rows.

        Worker writes must become visible to API reads without replacing the
        process-local repository state used by concurrent requests.
        """

        with self._sync_postgres_lock:
            self.configure_sync_postgres()
            if self.sync_postgres is None:
                return self
            self.ensure_postgres_schema()
            tenant_id = configured_tenant_id()
            project_collections = {
                STATE_COLLECTIONS["documents"],
                STATE_COLLECTIONS["bindings"],
                STATE_COLLECTIONS["knowledge_files"],
            }
            rows = self.sync_postgres.execute(
                """
                SELECT collection, object_id, payload
                FROM aicheck_state
                WHERE tenant_id = %s
                  AND collection = ANY(%s)
                  AND payload ->> 'projectId' = %s
                ORDER BY collection, updated_at DESC, object_id DESC
                """,
                (tenant_id, sorted(project_collections), project_id),
            ).fetchall()
            records: dict[tuple[str, str], dict[str, Any]] = {
                (str(collection), str(object_id)): json.loads(json.dumps(payload))
                for collection, object_id, payload in rows
            }
            document_ids = {
                str(payload.get("id") or object_id)
                for (collection, object_id), payload in records.items()
                if collection == STATE_COLLECTIONS["documents"]
            }
            version_ids = {
                str(payload.get("currentVersionId"))
                for (collection, _), payload in records.items()
                if collection == STATE_COLLECTIONS["documents"] and payload.get("currentVersionId")
            }
            if document_ids or version_ids:
                related_collections = {
                    STATE_COLLECTIONS[state_key]
                    for state_key in (
                        "versions",
                        "bindings",
                        "knowledge_files",
                        "knowledge_tasks",
                        "ocr_jobs",
                        "ocr_parse_results",
                        "ocr_pipeline_runs",
                        "extracted_fields",
                        "evidence_links",
                        "node_evidence_links",
                    )
                }
                related_rows = self.sync_postgres.execute(
                    """
                    SELECT collection, object_id, payload
                    FROM aicheck_state
                    WHERE tenant_id = %s
                      AND collection = ANY(%s)
                      AND (
                           payload ->> 'projectId' = %s
                           OR payload ->> 'documentId' = ANY(%s)
                           OR payload ->> 'documentVersionId' = ANY(%s)
                           OR object_id = ANY(%s)
                      )
                    ORDER BY collection, object_id
                    """,
                    (
                        tenant_id,
                        sorted(related_collections),
                        project_id,
                        sorted(document_ids),
                        sorted(version_ids),
                        sorted(document_ids | version_ids),
                    ),
                ).fetchall()
                for collection, object_id, payload in related_rows:
                    records[(str(collection), str(object_id))] = json.loads(json.dumps(payload))
                version_ids.update(
                    str(payload.get("id") or object_id)
                    for (collection, object_id), payload in records.items()
                    if collection == STATE_COLLECTIONS["versions"]
                )
            pipeline_ids = {
                str(payload.get("id") or object_id)
                for (collection, object_id), payload in records.items()
                if collection == STATE_COLLECTIONS["ocr_pipeline_runs"]
            }
            if pipeline_ids:
                stage_rows = self.sync_postgres.execute(
                    """
                    SELECT collection, object_id, payload
                    FROM aicheck_state
                    WHERE tenant_id = %s
                      AND collection = %s
                      AND payload ->> 'pipelineRunId' = ANY(%s)
                    ORDER BY object_id
                    """,
                    (tenant_id, STATE_COLLECTIONS["ocr_stage_runs"], sorted(pipeline_ids)),
                ).fetchall()
                for collection, object_id, payload in stage_rows:
                    records[(str(collection), str(object_id))] = json.loads(json.dumps(payload))
            self.sync_postgres.commit()

        collection_to_state = {value: key for key, value in STATE_COLLECTIONS.items()}
        detached_state: dict[str, Any] = {state_key: [] for state_key in STATE_COLLECTIONS}
        detached_state["idempotency"] = {}
        for (collection, _), payload in records.items():
            state_key = collection_to_state.get(collection)
            if state_key:
                detached_state[state_key].append(payload)
        # seed=False：下一行就整体替换 state，播种出来的东西一次都不会被读
        view = InMemoryRepository(seed=False)
        view.state = detached_state
        view.apply_tenant_scope()
        return view

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
                collection_name = STATE_COLLECTIONS[state_key]
                # 钉住的记录不许被库里的副本顶掉——那会把别的请求正在改的对象丢了。
                incoming = [
                    item
                    for index, item in enumerate(incoming)
                    if not self.object_is_pinned(
                        collection_name, self.persistence_object_id(collection_name, item, index)
                    )
                ]
                incoming_ids = {
                    self.persistence_object_id(collection_name, item, index)
                    for index, item in enumerate(incoming)
                }
                retained = [
                    item
                    for index, item in enumerate(self.state.get(state_key, []))
                    if self.persistence_object_id(collection_name, item, index) not in incoming_ids
                ]
                self.state[state_key] = [*incoming, *retained]
            self._persistence_baseline.update(
                {
                    (str(collection_name), str(object_id)): self.canonical_persistence_payload(payload)
                    for collection_name, object_id, payload in rows
                    if not self.object_is_pinned(str(collection_name), str(object_id))
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
        # 算 diff 放在锁**外面**。
        #
        # 这一步要把当前状态序列化一遍去和基线比对：全量时实测 17.4 秒
        # （其中 knowledge_vectors 一张表 61 MB 就占 8.7 秒）。原先它在锁内，
        # 而同一把锁也是读路径要拿的——于是一次写入期间，**所有请求**都在锁上排队：
        # 0819 实测 /api/healthz 连续 36s、53s、28s，不只是写慢，是全站都慢。
        #
        # 算 diff 只读内存状态、不碰数据库，放在锁外不影响一致性：
        # 真正需要串行的是下面那段数据库事务，而它本来就有乐观锁守卫
        # （assert_persistence_baseline）——并发写会被它挡下并回滚重来。
        plan = self._build_flush_dirty_plan(
            selected_state_keys=selected_state_keys,
            selected_singleton_keys=selected_singleton_keys,
        )
        if not plan["has_work"]:
            return
        with self._sync_postgres_lock:
            if self.sync_postgres is None:
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
                            raise ConcurrentPersistenceError(
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
                                raise ConcurrentPersistenceError(
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
                        if self.unchanged_since_baseline(key, payload):
                            continue
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
                                raise ConcurrentPersistenceError(
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
                    if self.unchanged_since_baseline(key, payload):
                        continue
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
                            raise ConcurrentPersistenceError(
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
                # D-4：知识库里注册了 2560/4096 维的 embedding 档案，但 pgvector 表是
                # 按 OFFLINE_VECTOR_DIMENSIONS 建的。维度不匹配的向量原先直接 continue
                # 跳过——flush 不写、检索返回空，全程无报错，换了模型档案的人只会看到
                # 「检索没结果」而不知道向量根本没入库。
                skipped_dimensions: dict[int, int] = {}
                for row in self.state.get("knowledge_vectors", []) or []:
                    row_dimensions = int(row.get("dimensions") or 0)
                    if row_dimensions != OFFLINE_VECTOR_DIMENSIONS:
                        skipped_dimensions[row_dimensions] = skipped_dimensions.get(row_dimensions, 0) + 1
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
                if skipped_dimensions:
                    detail = "、".join(
                        f"{dimensions} 维 {count} 条" for dimensions, count in sorted(skipped_dimensions.items())
                    )
                    LOGGER.error(
                        "pgvector_dimension_mismatch: 有向量因维度与索引表不符而未入库（%s）。"
                        "索引表按 %s 维建立；这些向量既不会被写入、也不会被检索到，"
                        "更换 embedding 模型档案后需要重建索引表并重新向量化。",
                        detail,
                        OFFLINE_VECTOR_DIMENSIONS,
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
                # 原先连日志都没有：向量整批没入库，检索永远返回空，而调用方看到的
                # 是「知识库没覆盖到」。回滚要吞异常（回滚本身失败无从补救），
                # 但原始失败必须留下痕迹。
                LOGGER.exception("pgvector_flush_failed: 知识向量刷写 pgvector 失败，本批未入库")
                try:
                    self.sync_postgres.rollback()
                except Exception:
                    LOGGER.exception("pgvector_flush_rollback_failed: 回滚同样失败")

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
            if self.sync_postgres is None or not self.ensure_pgvector_schema():
                return []
            if len(embedding) != OFFLINE_VECTOR_DIMENSIONS:
                # 写入侧维度不符已经会报错，检索侧不能反过来沉默：
                # 「查询向量维度不对」和「库里确实没有相关内容」都返回空列表，
                # 调用方无从分辨，只会以为是知识库没覆盖到。
                LOGGER.error(
                    "pgvector_query_dimension_mismatch: 查询向量 %s 维，索引表按 %s 维建立，"
                    "本次检索必然返回空——这不是「没有匹配内容」，是查询用的 embedding "
                    "模型档案与索引表不一致。",
                    len(embedding),
                    OFFLINE_VECTOR_DIMENSIONS,
                )
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


def load_state(selected_state_keys: set[str] | None = None, tenant_id: str | None = None) -> None:
    """加载持久化状态；不传 tenant_id 时按 configured_tenant_id() 回落（N-5）。"""
    if postgres_persistence_configured():
        repo.load_from_sync_postgres(selected_state_keys, tenant_id=tenant_id)
        return
    repo.load_from_sqlite(selected_state_keys, tenant_id=tenant_id)


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
            "evidence_snapshots",
            "evidence_manifests",
            "evidence_shards",
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
