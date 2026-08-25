from __future__ import annotations

import argparse
import ast
import inspect
import json
import os
import re
import subprocess
import sys
import textwrap
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.api.main import app
from libs.contracts import errors
from libs.contracts.responses import SERVER_TZ, fail, ok
from libs.db.indexes import POSTGRES_INDEXES
from libs.db.repository import (
    IDEMPOTENCY_COLLECTION,
    SINGLETON_COLLECTIONS,
    STATE_COLLECTIONS,
    InMemoryRepository,
    build_export_artifact,
    repo,
)
from libs.db.seed import PROJECT_ID, ROLE_ACTIONS
from libs.integrations.litellm_client import LiteLLMClient
from libs.integrations.storage import DEFAULT_BUCKETS, ObjectStorage, parse_storage_url
from libs.security.actions import MUTATING_METHODS, required_action_for_request
from libs.security.auth import ROLE_DEFAULT_PATHS, verify_password
from scripts.audit_frontend_contract import audit
from scripts.build_release_manifest import verify_manifest as verify_release_manifest
from scripts.create_roles import ROLE_SPECS, build_plan, validate_strong_passwords
from scripts.security_release_gate import validate_scan_directory
from scripts.validate_deployment_config import DeploymentConfigValidator
from scripts.verify_deployment import (
    DEFAULT_ROLES,
    CheckResult,
    DeploymentVerifier,
    VerifyConfig,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
MUTATION_HEADER_EXEMPT_URLS = {
    "/api/admin/config-diff/preview",
    "/api/admin/config-overview/publish-preview",
    "/api/business-packs/${packId}/validate",
    "/api/business-packs/{pack_id}/validate",
    "/api/business-packs/validate-all",
    "/api/fde/business-packs/validate-all",
    "/api/knowledge/reindex-preview",
    "/api/knowledge/retrieval-test",
    # 原始数据完整性校验：只读校验，后端同名路由已在 READ_ONLY_POST_ROUTES 中豁免，
    # 前端侧此前漏加，导致两份名单口径不一致。
    "/api/fde/review-runs/${reviewRunId}/raw-vault/verify",
    "/api/rules/versions/${versionId}/${action}-preview",
    # 邀请注册：调用者**还没有账号**，幂等头依赖当前用户身份，无从生成。
    # 后端同名路由也在 PUBLIC_MUTATION_ROUTES 里豁免，两份名单口径一致。
    # 防重复的闸门是邀请令牌本身：单次有效、会过期、绑死组织和角色。
    # 这份名单比对的是**源码里的原样字符串**，不是后端的路由模板——
    # 两份名单是两个口径，加豁免时都得加。
    "/api/registration-links/${encodeURIComponent(token)}/apply",
}
PUBLIC_MUTATION_ROUTES = {
    ("POST", "/mock/user/login"),
    ("POST", "/api/mock/user/login"),
    ("POST", "/auth/login"),
    ("POST", "/api/auth/login"),
    ("POST", "/auth/logout"),
    ("POST", "/api/auth/logout"),
    ("POST", "/auth/change-password"),
    ("POST", "/api/auth/change-password"),
    # 项目注册申请：申请人还没有账号，不可能带登录态和幂等键。
    # 闸门是**审核**——提交只是排队，不产生任何可用凭证。
    ("POST", "/registration-links/{token}/apply"),
    ("POST", "/api/registration-links/{token}/apply"),
}
READ_ONLY_POST_ROUTES = {
    # 外部登记信息检索：用 POST 只为传递结构化查询条件，不写任何状态，
    # 因此没有幂等键可言（已核对 cnse_routes.py / std_samr_routes.py 均不改 repo.state）。
    ("POST", "/cnse/organizations/search"),
    ("POST", "/api/cnse/organizations/search"),
    ("POST", "/cnse/persons/search"),
    ("POST", "/api/cnse/persons/search"),
    ("POST", "/std-samr/standards/search"),
    ("POST", "/api/std-samr/standards/search"),
    ("POST", "/std-samr/standards/verify"),
    ("POST", "/api/std-samr/standards/verify"),
    ("POST", "/business-packs/{pack_id}/validate"),
    ("POST", "/api/business-packs/{pack_id}/validate"),
    ("POST", "/business-packs/validate-all"),
    ("POST", "/api/business-packs/validate-all"),
    ("POST", "/fde/business-packs/validate-all"),
    ("POST", "/api/fde/business-packs/validate-all"),
    ("POST", "/fde/review-runs/{review_run_id}/raw-vault/verify"),
    ("POST", "/api/fde/review-runs/{review_run_id}/raw-vault/verify"),
    ("POST", "/api/fde/review-runs/${reviewRunId}/raw-vault/verify"),
    ("POST", "/knowledge/retrieval-test"),
    ("POST", "/api/knowledge/retrieval-test"),
    ("POST", "/admin/config-diff/preview"),
    ("POST", "/api/admin/config-diff/preview"),
    ("POST", "/admin/config-overview/publish-preview"),
    ("POST", "/api/admin/config-overview/publish-preview"),
    ("POST", "/knowledge/reindex-preview"),
    ("POST", "/api/knowledge/reindex-preview"),
    ("POST", "/rules/versions/{version_id}/{action}-preview"),
    ("POST", "/api/rules/versions/{version_id}/{action}-preview"),
}
REQUIRED_WORKER_TASKS = {
    "parse_document": {
        "queue": "ocr.parse_document",
        "dispatcher": "dispatch_parse_document",
    },
    "recognize_seals": {
        "queue": "cpu.heavy",
        "dispatcher": None,
    },
    "slice_knowledge": {
        "queue": "cpu.heavy",
        "dispatcher": "dispatch_slice",
    },
    "embed_knowledge": {
        "queue": "cpu.heavy",
        "dispatcher": "dispatch_embed",
    },
    "ocr_pipeline_official_extract": {
        "queue": "ocr.remote",
        "dispatcher": "dispatch_ocr_pipeline_official",
    },
    "ocr_pipeline_qwen_extract": {
        "queue": "llm.remote",
        "dispatcher": "dispatch_ocr_pipeline_qwen",
    },
    "ocr_pipeline_structure_scan": {
        "queue": "cpu.heavy",
        "dispatcher": "dispatch_ocr_pipeline_structure",
    },
    "ocr_pipeline_seal_scan": {
        "queue": "cpu.heavy",
        "dispatcher": "dispatch_ocr_pipeline_seal",
    },
    "ocr_pipeline_evidence_fusion": {
        "queue": "business.light",
        "dispatcher": "dispatch_ocr_pipeline_fusion",
    },
    "ocr_pipeline_finalize": {
        "queue": "business.light",
        "dispatcher": "dispatch_ocr_pipeline_finalize",
    },
    "ai_recheck": {
        "queue": "llm.remote",
        "dispatcher": "dispatch_ai_recheck",
    },
    "llm_compare": {
        "queue": "llm.remote",
        "dispatcher": "dispatch_llm_compare",
    },
    "export_package": {
        "queue": "business.light",
        "dispatcher": "dispatch_export",
    },
}
REQUIRED_PLAN_COLLECTIONS = {
    "projects",
    "project_nodes",
    "documents",
    "document_versions",
    "node_bindings",
    "submissions",
    "rectifications",
    "ai_runs",
    "evidence_links",
    "reports",
    "archive_items",
    "export_tasks",
    "knowledge_files",
    "knowledge_tasks",
    "knowledge_clauses",
    "knowledge_page_index_nodes",
    "todos",
    "messages",
    "audit_logs",
    "admin_configs",
}
CRITICAL_POSTGRES_INDEXES = [
    {"table": "aicheck_state", "fields": ["tenant_id", "collection", "object_id"], "unique": True},
    {"table": "aicheck_state", "fields": ["tenant_id", "collection"]},
    {"table": "aicheck_state", "fields": ["payload"], "type": "gin"},
    {"table": "aicheck_singletons", "fields": ["tenant_id", "name"], "unique": True},
    {"table": "idempotency_records", "fields": ["tenant_id", "scope"], "unique": True},
]
REQUIRED_STORAGE_BUCKETS = (
    "documents",
    "previews",
    "exports",
    "ocr-artifacts",
    "audit-anchors",
    "agent-raw-vault",
)
REQUIRED_STORAGE_METHODS = {
    "ensure_buckets": {
        "params": [],
        "source": ["bucket_names", "bucket_exists", "make_bucket"],
    },
    "presigned_put_url": {
        "params": ["bucket", "object_name", "content_type"],
        "source": ["ensure_buckets", "presigned_put_object"],
    },
    "presigned_get_url": {
        "params": ["url", "file_name"],
        "source": ["parse_storage_url", "ensure_buckets", "presigned_get_object"],
    },
    "put_bytes": {
        "params": ["bucket", "object_name", "data", "content_type"],
        "source": ["ensure_buckets", "put_object", "minio://"],
    },
    "download_to_temp": {
        "params": ["bucket", "object_name"],
        "source": ["fget_object"],
    },
}
REQUIRED_REPOSITORY_STORAGE_CALLS = {
    "signed_get": ["presigned_get_url"],
    "signed_put": ["presigned_put_url"],
    "document_storage_url": ["minio://"],
    "create_upload_session": ["presigned_put_url", "documents"],
    "attach_export_artifact": ["put_bytes", "exports"],
}
REQUIRED_OCR_HEALTH_FIELDS = {
    "service",
    "pipelineAvailable",
    "pipelineBackend",
    "placeholderAllowed",
    "executable",
    "warmedUp",
    "capacityReady",
    "lastSuccessfulInferenceAt",
    "memoryHeadroom",
}
REQUIRED_OCR_RESULT_FIELDS = {"storageKey", "fileName", "status", "fragments", "fields", "seals", "diagnostics"}
REQUIRED_OCR_EVALUATION_METRICS = {
    "fieldBboxHitRate",
    "fieldRecall",
    "fieldValueAccuracy",
    "fieldEvidenceRecall",
    "tableBboxHitRate",
    "tableEvidenceRecall",
    "tableRecall",
    "sealBboxHitRate",
    "sealEvidenceRecall",
    "sealRecall",
    "qualityStatusMatch",
    "qualityReasonRecall",
    "qualityEvidenceCompletenessMatch",
}
REQUIRED_LITELLM_CLIENT_METHODS = {
    "__init__": ["LITELLM_API_KEY", "production_mode_enabled", "sk-aicheck-dev", "RuntimeError"],
    "chat": ["/v1/chat/completions", "Authorization", "Bearer", "default-chat", "messages"],
    "chat_sync": ["/v1/chat/completions", "Authorization", "Bearer", "default-chat", "messages"],
    "embed": ["/v1/embeddings", "Authorization", "Bearer", "embedding-default", "input"],
    "embed_sync": ["/v1/embeddings", "Authorization", "Bearer", "embedding-default", "input"],
    "_response_json": ["IntegrationServiceError", "INVALID_JSON", "INVALID_RESPONSE", "status_code"],
    "first_message_text": ["choices", "message", "content"],
}
REQUIRED_LITELLM_WORKER_USAGE = {
    "embed_knowledge": ["offline_hash_embeddings", "OFFLINE_EMBEDDING_MODEL", "offline_hash"],
    "ai_recheck": ["qwen_runtime_client().chat_sync", "review-chat", "AI_RUN_FAILED", "first_message_text"],
    "llm_compare": ["qwen_runtime_client().chat_sync", "default-chat", "compare-fast", "EXTERNAL_TOOL_FAILED"],
}
REQUIRED_REVIEW_RUN_ROUTES = [
    {"method": "POST", "suffix": "/projects/{project_id}/inspection/nodes/{node_id}/ai-recheck"},
    {"method": "GET", "suffix": "/review-runs/{review_run_id}"},
    {"method": "GET", "suffix": "/review-runs/{review_run_id}/timeline"},
    {"method": "GET", "suffix": "/review-runs/{review_run_id}/graph"},
    {"method": "POST", "suffix": "/review-runs/{review_run_id}/human-decision"},
    {"method": "POST", "suffix": "/review-runs/{review_run_id}/cancel"},
    {"method": "POST", "suffix": "/review-runs/{review_run_id}/rerun"},
    {"method": "GET", "suffix": "/fde/review-runs"},
    {"method": "GET", "suffix": "/fde/review-runs/{review_run_id}"},
    {"method": "GET", "suffix": "/fde/review-runs/{review_run_id}/graph"},
    {"method": "GET", "suffix": "/fde/review-runs/{review_run_id}/temporal-history"},
    {"method": "POST", "suffix": "/fde/review-runs/{review_run_id}/replay"},
    {"method": "POST", "suffix": "/fde/review-runs/{review_run_id}/shadow-run"},
]
REQUIRED_REVIEW_GRAPH_STEP_KEYS = [
    "load_context",
    "load_ocr_result",
    "run_rule_engine",
    "retrieve_knowledge",
    "build_prompt",
    "llm_generate_findings",
    "schema_validation",
    "evidence_validation",
    "reference_validation",
    "critic_review",
    "quality_gate",
    "persist_drafts",
]
REQUIRED_REVIEW_COLLECTIONS = {
    "review_runs",
    "evidence_snapshots",
    "evidence_manifests",
    "evidence_shards",
    "review_step_runs",
    "review_graph_nodes",
    "review_tool_calls",
    "review_events",
    "retrieval_traces",
    "rule_check_results",
}
REQUIRED_REVIEW_ALLOWED_TOOLS = {
    "get_project_context",
    "get_node_requirements",
    "get_document_ocr_result",
    "run_rule_engine",
    "retrieve_clauses",
    "search_knowledge_base",
    "call_qwen_runtime_chat",
    "create_review_finding_draft",
}
REQUIRED_REVIEW_FORBIDDEN_TOOLS = {
    "approve_review",
    "issue_formal_correction",
    "close_correction",
    "change_project_status",
    "archive_project",
    "delete_document",
    "modify_audit_log",
    "grant_permission",
}
REQUIRED_KNOWLEDGE_RULE_ROUTES = [
    {"method": "GET", "suffix": "/knowledge/overview"},
    {"method": "GET", "suffix": "/knowledge/sources"},
    {"method": "POST", "suffix": "/knowledge/sources"},
    {"method": "GET", "suffix": "/knowledge/sources/{source_id}"},
    {"method": "PUT", "suffix": "/knowledge/sources/{source_id}"},
    {"method": "GET", "suffix": "/knowledge/project-files"},
    {"method": "GET", "suffix": "/knowledge/files/{file_id}"},
    {"method": "GET", "suffix": "/knowledge/files/{file_id}/chunks"},
    {"method": "GET", "suffix": "/knowledge/files/{file_id}/vectors"},
    {"method": "GET", "suffix": "/knowledge/files/{file_id}/reasoning-references"},
    {"method": "GET", "suffix": "/knowledge/clauses"},
    {"method": "GET", "suffix": "/knowledge/page-index-nodes"},
    {"method": "POST", "suffix": "/knowledge/files/{file_id}/reindex"},
    {"method": "GET", "suffix": "/knowledge/tasks"},
    {"method": "POST", "suffix": "/knowledge/tasks/{task_id}/retry"},
    {"method": "POST", "suffix": "/knowledge/retrieval-test"},
    {"method": "GET", "suffix": "/knowledge/config"},
    {"method": "PUT", "suffix": "/knowledge/config"},
    {"method": "GET", "suffix": "/rules/versions"},
    {"method": "GET", "suffix": "/rules/versions/{version_id}/diff"},
    {"method": "POST", "suffix": "/rules/versions/{version_id}/publish"},
    {"method": "POST", "suffix": "/rules/versions/{version_id}/rollback"},
]
REQUIRED_KNOWLEDGE_RULE_COLLECTIONS = {
    "knowledge_sources",
    "knowledge_files",
    "knowledge_tasks",
    "knowledge_chunks",
    "knowledge_clauses",
    "knowledge_page_index_nodes",
    "knowledge_configs",
    "rule_versions",
    "retrieval_traces",
    "rule_check_results",
}
REQUIRED_FDE_RELEASE_ROUTES = [
    {"method": "GET", "suffix": "/fde/releases"},
    {"method": "POST", "suffix": "/fde/releases"},
    {"method": "POST", "suffix": "/fde/releases/{release_id}/submit"},
    {"method": "POST", "suffix": "/fde/releases/{release_id}/approve"},
    {"method": "POST", "suffix": "/fde/releases/{release_id}/start-shadow"},
    {"method": "POST", "suffix": "/fde/releases/{release_id}/request-canary"},
    {"method": "POST", "suffix": "/fde/releases/{release_id}/rollback"},
]
REQUIRED_FDE_RELEASE_COLLECTIONS = {
    "capability_bundles",
    "release_plans",
    "release_approvals",
    "release_gates",
    "evaluation_reports",
    "evaluation_sets",
}
REQUIRED_FEEDBACK_HR_ROUTES = [
    {"method": "GET", "suffix": "/fde/feedback"},
    {"method": "POST", "suffix": "/fde/feedback/{feedback_id}/triage"},
    {"method": "GET", "suffix": "/fde/evaluation-sets"},
]
REQUIRED_FEEDBACK_HR_COLLECTIONS = {
    "ai_feedback",
    "feedback_triage",
    "evaluation_sets",
    "evaluation_cases",
    "evaluation_case_results",
    "retrieval_traces",
}
REQUIRED_RULE_CHECK_RESULT_FIELDS = {
    "id",
    "reviewRunId",
    "ruleCode",
    "ruleSetVersion",
    "result",
    "severity",
    "message",
    "linkedClauseIds",
    "evidenceRefs",
    "suggestedAction",
    "createdAt",
}
REQUIRED_RETRIEVAL_TRACE_FIELDS = {
    "id",
    "retrievalTraceId",
    "reviewRunId",
    "query",
    "queryType",
    "routerVersion",
    "selectedRoute",
    "routerSignals",
    "queryRouter",
    "pageIndexTree",
    "filters",
    "retrievers",
    "selectedClauses",
    "kbVersion",
    "createdAt",
}
REQUIRED_EXPORT_ZIP_CONTENTS = {
    "manifest.json",
    "task.json",
    "project.json",
    "reports.json",
    "documents.json",
    "archive_items.json",
    "evidence_links.json",
    "README.txt",
}
PRODUCTION_ROLES = ("admin", "inspection", "contractor", "ndt", "owner", "fde")
ROLE_REQUIRED_ACTIONS = {
    "admin": {"admin:config", "admin:export", "project:authorize-member", "knowledge:manage"},
    "inspection": {"review:save", "review:return-correction", "ai:recheck", "report:generate"},
    "contractor": {"file:upload", "file:bind", "submission:submit", "rectification:submit"},
    "ndt": {"ndt:film-create", "ndt:record-import", "ndt:report-upload", "ndt:submit"},
    "owner": {"project:view", "file:view", "report:view", "archive:view", "archive:download"},
    "fde": {
        "fde:dashboard:view",
        "fde:ai-run:view-masked",
        "fde:feedback:triage",
        "fde:evaluation:run",
        "fde:release:submit",
        "fde:business-pack:install",
        "fde:security:manage",
    },
}
OWNER_FORBIDDEN_WRITE_ACTIONS = {
    "file:upload",
    "file:bind",
    "submission:submit",
    "review:save",
    "review:return-correction",
    "admin:config",
    "knowledge:manage",
    "ndt:submit",
}
ROLE_CONTRACT_TEST_PASSWORDS = {
    role: f"Aicheck!2026-{index}Z"
    for index, role in enumerate(PRODUCTION_ROLES, start=1)
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AIcheck deployment acceptance evidence report.")
    parser.add_argument("--strict-production", action="store_true")
    parser.add_argument("--include-live", action="store_true", help="Run live API/OCR/LiteLLM probes in addition to static checks.")
    parser.add_argument("--api-base", default=os.getenv("AICHECK_API_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--ocr-base", default=os.getenv("AICHECK_VERIFY_OCR_BASE_URL", "http://127.0.0.1:8010"))
    parser.add_argument("--litellm-base", default=os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:4001"))
    parser.add_argument("--litellm-api-key-file", default=os.getenv("LITELLM_API_KEY_FILE"))
    parser.add_argument("--project-id", default=PROJECT_ID)
    parser.add_argument("--roles", default=",".join(DEFAULT_ROLES))
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--skip-litellm", action="store_true")
    parser.add_argument("--write-probes", action="store_true")
    parser.add_argument("--ocr-object-probe", action="store_true")
    parser.add_argument("--review-run-probe", action="store_true")
    parser.add_argument("--review-run-wait-seconds", type=float, default=float(os.getenv("AICHECK_VERIFY_REVIEW_RUN_WAIT_SECONDS", "20")))
    parser.add_argument("--litellm-management-probes", action="store_true")
    parser.add_argument("--litellm-provider-probes", action="store_true")
    parser.add_argument("--qwen-official-probe", action="store_true")
    parser.add_argument("--release-gate", action="store_true", help="Require every production live/write/model probe without skips.")
    parser.add_argument("--security-scan-dir", help="Directory containing SBOM, Trivy, pip-audit, and pnpm-audit evidence.")
    parser.add_argument("--ocr-98-gate-report", help="Current passing OCR/audit 98+ release-gate JSON report.")
    parser.add_argument("--release-manifest", help="Immutable release manifest binding source, images, frontend, rules, and business packs.")
    parser.add_argument("--backup-recoverability-report", help="Fresh passing backup/PITR/replication/restore-drill evidence.")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--output-dir", help="Optional directory for report.json and report.md.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    return parser.parse_args()


def release_manifest_contract_section(args: argparse.Namespace) -> dict[str, Any]:
    path_value = getattr(args, "release_manifest", None)
    required = bool(getattr(args, "release_gate", False))
    if not path_value:
        check = {
            "name": "release.manifest",
            "status": "fail" if required else "skip",
            "detail": "--release-manifest is required for a release gate." if required else "No release manifest supplied.",
            "data": None,
        }
        return {"name": "release-manifest", "ok": not required, "skipped": not required, "checks": [check]}
    path = Path(path_value).expanduser().resolve()
    failures: list[str] = []
    document: dict[str, Any] = {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        verify_release_manifest(document)
    except Exception as exc:
        failures.append(str(exc))
    if document:
        if document.get("schemaVersion") != "aicheck-release-manifest-v1":
            failures.append("schemaVersion must be aicheck-release-manifest-v1")
        source = document.get("source") if isinstance(document.get("source"), dict) else {}
        current_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
        if source.get("gitSha") != current_sha:
            failures.append(f"manifest gitSha {source.get('gitSha')!r} does not match current source {current_sha!r}")
        if source.get("dirty") is not False:
            failures.append("manifest source must be clean")
        backend = document.get("backend") if isinstance(document.get("backend"), dict) else {}
        digest = str(backend.get("imageDigest") or "")
        if required and not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
            failures.append("backend imageDigest must be an immutable sha256 digest")
        required_hashes = {
            "source archive": source.get("archiveHash"),
            "frontend assets": ((document.get("frontend") or {}).get("dist") or {}).get("aggregateHash"),
            "business packs": (backend.get("businessPacks") or {}).get("aggregateHash"),
            "rules": (document.get("rules") or {}).get("aggregateHash"),
            "material mapping": (backend.get("materialMapping") or {}).get("sha256"),
        }
        for label, value in required_hashes.items():
            if not isinstance(value, str) or not value.startswith("sha256:"):
                failures.append(f"{label} hash is missing")
    check = {
        "name": "release.manifest",
        "status": "fail" if failures else "pass",
        "detail": "; ".join(failures) if failures else "Release manifest is authentic and bound to the current source and immutable artifacts.",
        "data": {
            "releaseId": document.get("releaseId"),
            "manifestHash": document.get("manifestHash"),
            "gitSha": (document.get("source") or {}).get("gitSha") if document else None,
        },
    }
    return {"name": "release-manifest", "ok": not failures, "checks": [check]}


def backup_recoverability_contract_section(args: argparse.Namespace) -> dict[str, Any]:
    path_value = getattr(args, "backup_recoverability_report", None)
    required = bool(getattr(args, "release_gate", False))
    if not path_value:
        return {
            "name": "backup-recoverability",
            "ok": not required,
            "skipped": not required,
            "checks": [
                {
                    "name": "backup.recoverability",
                    "status": "fail" if required else "skip",
                    "detail": "--backup-recoverability-report is required for a release gate." if required else "No recoverability report supplied.",
                    "data": None,
                }
            ],
        }
    failures: list[str] = []
    document: dict[str, Any] = {}
    try:
        import hashlib

        document = json.loads(Path(path_value).expanduser().read_text(encoding="utf-8"))
        expected_hash = str(document.get("reportHash") or "")
        unsigned = {key: value for key, value in document.items() if key != "reportHash"}
        actual_hash = "sha256:" + hashlib.sha256(
            json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if expected_hash != actual_hash:
            failures.append("recoverability report hash mismatch")
        if document.get("schemaVersion") != "aicheck-backup-recoverability-v1":
            failures.append("schemaVersion must be aicheck-backup-recoverability-v1")
        checks = document.get("checks") if isinstance(document.get("checks"), list) else []
        if document.get("ok") is not True or not checks or any(
            not isinstance(item, dict) or item.get("status") != "pass" for item in checks
        ):
            failures.append("backup recoverability checks are not all passing")
    except Exception as exc:
        failures.append(str(exc))
    check = {
        "name": "backup.recoverability",
        "status": "fail" if failures else "pass",
        "detail": "; ".join(failures) if failures else "Physical, logical, offsite replication, RPO, RTO, and restore-drill evidence is current.",
        "data": {"reportHash": document.get("reportHash"), "generatedAt": document.get("generatedAt")},
    }
    return {"name": "backup-recoverability", "ok": not failures, "checks": [check]}


class DeploymentReportBuilder:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args

    def build(self) -> dict[str, Any]:
        sections = [
            self.config_section(),
            self.auth_contract_section(),
            self.data_contract_section(),
            self.storage_contract_section(),
            self.ocr_service_contract_section(),
            self.litellm_client_contract_section(),
            self.knowledge_rule_contract_section(),
            self.review_orchestration_contract_section(),
            self.fde_governance_contract_section(),
            self.feedback_hr_contract_section(),
            self.export_artifact_contract_section(),
            self.worker_contract_section(),
            self.api_contract_section(),
            self.frontend_contract_section(),
        ]
        if bool(getattr(self.args, "release_manifest", None)) or bool(getattr(self.args, "release_gate", False)):
            sections.append(release_manifest_contract_section(self.args))
        if bool(getattr(self.args, "backup_recoverability_report", None)) or bool(getattr(self.args, "release_gate", False)):
            sections.append(backup_recoverability_contract_section(self.args))
        if bool(getattr(self.args, "release_gate", False)):
            sections.append(release_gate_contract_section(self.args))
        if self.args.include_live:
            sections.append(self.live_section())
        else:
            sections.append(
                {
                    "name": "live-deployment",
                    "ok": True,
                    "skipped": True,
                    "checks": [
                        {
                            "name": "live.probes",
                            "status": "skip",
                            "detail": "Pass --include-live to run target API/OCR/LiteLLM probes.",
                            "data": None,
                        }
                    ],
                }
            )
        summary = summarize_sections(sections)
        return {
            "schemaVersion": "aicheck-deployment-report-v1",
            "generatedAt": datetime.now(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "strictProduction": bool(self.args.strict_production),
            "includeLive": bool(self.args.include_live),
            "ok": summary["fail"] == 0,
            "summary": summary,
            "sections": sections,
        }

    def config_section(self) -> dict[str, Any]:
        validator = DeploymentConfigValidator(
            BACKEND_ROOT / "docker-compose.yml",
            BACKEND_ROOT / "config/litellm.yaml",
            strict_production=bool(self.args.strict_production),
        )
        results = validator.run()
        return {
            "name": "deployment-config",
            "ok": all(item.ok for item in results),
            "checks": [asdict(item) for item in results],
        }

    def api_contract_section(self) -> dict[str, Any]:
        envelope_check = response_envelope_contract_check()
        idempotency_check = backend_mutation_idempotency_check()
        action_check = backend_action_coverage_check()
        return {
            "name": "api-contract",
            "ok": envelope_check["status"] == "pass"
            and idempotency_check["status"] == "pass"
            and action_check["status"] == "pass",
            "checks": [envelope_check, idempotency_check, action_check],
        }

    def data_contract_section(self) -> dict[str, Any]:
        check = postgres_index_contract_check()
        return {
            "name": "data-contract",
            "ok": check["status"] == "pass",
            "checks": [check],
        }

    def storage_contract_section(self) -> dict[str, Any]:
        check = storage_contract_check()
        return {
            "name": "storage-contract",
            "ok": check["status"] == "pass",
            "checks": [check],
        }

    def ocr_service_contract_section(self) -> dict[str, Any]:
        check = ocr_service_contract_check()
        profile_check = ocr_profile_contract_check()
        evaluation_check = ocr_evaluation_contract_check()
        return {
            "name": "ocr-service-contract",
            "ok": check["status"] == "pass"
            and profile_check["status"] == "pass"
            and evaluation_check["status"] == "pass",
            "checks": [check, profile_check, evaluation_check],
        }

    def litellm_client_contract_section(self) -> dict[str, Any]:
        check = litellm_client_contract_check()
        return {
            "name": "litellm-client-contract",
            "ok": check["status"] == "pass",
            "checks": [check],
        }

    def review_orchestration_contract_section(self) -> dict[str, Any]:
        check = review_orchestration_contract_check()
        coverage_check = lossless_evidence_coverage_check()
        return {
            "name": "review-orchestration-contract",
            "ok": check["status"] == "pass"
            and coverage_check["status"] in {"pass", "skip"},
            "checks": [check, coverage_check],
        }

    def fde_governance_contract_section(self) -> dict[str, Any]:
        check = fde_governance_contract_check()
        return {
            "name": "fde-governance-contract",
            "ok": check["status"] == "pass",
            "checks": [check],
        }

    def feedback_hr_contract_section(self) -> dict[str, Any]:
        check = feedback_hr_contract_check()
        return {
            "name": "feedback-hr-contract",
            "ok": check["status"] == "pass",
            "checks": [check],
        }

    def knowledge_rule_contract_section(self) -> dict[str, Any]:
        check = knowledge_rule_contract_check()
        return {
            "name": "knowledge-rule-contract",
            "ok": check["status"] == "pass",
            "checks": [check],
        }

    def export_artifact_contract_section(self) -> dict[str, Any]:
        check = export_artifact_contract_check()
        return {
            "name": "export-artifact-contract",
            "ok": check["status"] == "pass",
            "checks": [check],
        }

    def auth_contract_section(self) -> dict[str, Any]:
        check = role_contract_check()
        security_check = auth_security_contract_check()
        return {
            "name": "auth-contract",
            "ok": check["status"] == "pass" and security_check["status"] == "pass",
            "checks": [check, security_check],
        }

    def worker_contract_section(self) -> dict[str, Any]:
        check = worker_task_contract_check()
        hardening_check = ocr_pipeline_hardening_contract_check()
        return {
            "name": "worker-contract",
            "ok": check["status"] == "pass" and hardening_check["status"] == "pass",
            "checks": [check, hardening_check],
        }

    def frontend_contract_section(self) -> dict[str, Any]:
        result = audit(
            REPO_ROOT / "frontend" / "src" / "api",
            ["aicheck/**/*.ts", "login/**/*.ts"],
            include_mock=False,
        )
        check = {
            "name": "frontend.contract",
            "status": "pass" if result.ok else "fail",
            "detail": f"frontend={result.frontend_count}, backend={result.backend_count}, missing={len(result.missing)}",
            "data": {
                "frontendCount": result.frontend_count,
                "backendCount": result.backend_count,
                "missing": [asdict(item) for item in result.missing],
            },
        }
        mutation_check = frontend_mutation_header_check(REPO_ROOT / "frontend" / "src" / "api" / "aicheck" / "index.ts")
        helper_check = frontend_mutation_helper_check(REPO_ROOT / "frontend" / "src" / "api" / "aicheck" / "index.ts")
        return {
            "name": "frontend-contract",
            "ok": result.ok and mutation_check["status"] == "pass" and helper_check["status"] == "pass",
            "checks": [check, mutation_check, helper_check],
        }

    def release_runtime_check(self, api_client: httpx.Client) -> CheckResult | None:
        manifest_path = getattr(self.args, "release_manifest", None)
        if not manifest_path:
            return None
        manifest = json.loads(Path(manifest_path).expanduser().read_text(encoding="utf-8"))
        try:
            response = api_client.get("/api/runtime/ui-context")
            payload = response.json()
        except Exception as exc:
            return CheckResult("release.runtime-identity", "fail", str(exc))
        if response.status_code != 200 or not isinstance(payload, dict) or payload.get("code") != 0:
            return CheckResult("release.runtime-identity", "fail", f"Unexpected runtime identity response: HTTP {response.status_code}")
        runtime = payload.get("data") or {}
        release = runtime.get("release") if isinstance(runtime, dict) else {}
        expected = {
            "releaseId": manifest.get("releaseId"),
            "gitSha": (manifest.get("source") or {}).get("gitSha"),
            "backendDigest": (manifest.get("backend") or {}).get("imageDigest"),
            "frontendAssetHash": ((manifest.get("frontend") or {}).get("dist") or {}).get("aggregateHash"),
            "rulesHash": (manifest.get("rules") or {}).get("aggregateHash"),
            "businessPackHash": ((manifest.get("backend") or {}).get("businessPacks") or {}).get("aggregateHash"),
            "materialMappingHash": ((manifest.get("backend") or {}).get("materialMapping") or {}).get("sha256"),
            "manifestHash": manifest.get("manifestHash"),
        }
        mismatches = [
            f"{key}: expected {value!r}, got {(release or {}).get(key)!r}"
            for key, value in expected.items()
            if value != (release or {}).get(key)
        ]
        return CheckResult(
            "release.runtime-identity",
            "fail" if mismatches else "pass",
            "; ".join(mismatches) if mismatches else "Runtime identity matches the immutable release manifest.",
            {"releaseId": (release or {}).get("releaseId"), "manifestHash": (release or {}).get("manifestHash")},
        )

    def live_section(self) -> dict[str, Any]:
        roles = [item.strip() for item in str(self.args.roles).split(",") if item.strip()]
        litellm_api_key = os.getenv("LITELLM_API_KEY", "")
        key_file = getattr(self.args, "litellm_api_key_file", None)
        if key_file:
            key_path = Path(key_file).expanduser()
            if key_path.stat().st_mode & 0o077:
                raise RuntimeError("--litellm-api-key-file must not be group/world accessible")
            litellm_api_key = key_path.read_text(encoding="utf-8").strip()
        config = VerifyConfig(
            api_base=str(self.args.api_base).rstrip("/"),
            ocr_base=None if self.args.skip_ocr else str(self.args.ocr_base).rstrip("/"),
            litellm_base=None if self.args.skip_litellm else str(self.args.litellm_base).rstrip("/"),
            litellm_api_key=litellm_api_key,
            project_id=str(self.args.project_id),
            roles=roles,
            strict_production=bool(self.args.strict_production),
            skip_ocr=bool(self.args.skip_ocr),
            skip_litellm=bool(self.args.skip_litellm),
            write_probes=bool(self.args.write_probes),
            ocr_object_probe=bool(self.args.ocr_object_probe),
            review_run_probe=bool(self.args.review_run_probe),
            review_run_wait_seconds=max(0.0, float(self.args.review_run_wait_seconds or 0.0)),
            litellm_management_probes=bool(self.args.litellm_management_probes),
            litellm_provider_probes=bool(self.args.litellm_provider_probes),
            qwen_official_probe=bool(getattr(self.args, "qwen_official_probe", False)),
        )
        with httpx.Client(base_url=config.api_base, timeout=self.args.timeout) as api_client:
            storage_client = httpx.Client(timeout=self.args.timeout)
            ocr_client = httpx.Client(base_url=config.ocr_base, timeout=self.args.timeout) if config.ocr_base else None
            litellm_client = httpx.Client(base_url=config.litellm_base, timeout=self.args.timeout) if config.litellm_base else None
            try:
                verifier = DeploymentVerifier(
                    config,
                    api_client=api_client,
                    ocr_client=ocr_client,
                    litellm_client=litellm_client,
                    storage_client=storage_client,
                )
                results = verifier.run()
                runtime_check = self.release_runtime_check(api_client)
                if runtime_check is not None:
                    results.append(runtime_check)
            finally:
                storage_client.close()
                if ocr_client:
                    ocr_client.close()
                if litellm_client:
                    litellm_client.close()
        return {
            "name": "live-deployment",
            "ok": (
                all(item.status == "pass" for item in results)
                if bool(getattr(self.args, "release_gate", False))
                else all(item.ok or item.status == "skip" for item in results)
            ),
            "checks": [asdict(item) for item in results],
        }


def summarize_sections(sections: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"pass": 0, "warn": 0, "fail": 0, "skip": 0, "total": 0}
    for section in sections:
        for check in section.get("checks", []):
            status = str(check.get("status") or "")
            if status in summary:
                summary[status] += 1
            summary["total"] += 1
    return summary


def strip_typescript_comments(source: str) -> str:
    without_block_comments = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//.*", "", without_block_comments)


def has_mutation_headers_config(snippet: str) -> bool:
    cleaned = strip_typescript_comments(snippet)
    return bool(re.search(r"(?m)^\s*headers\s*:\s*mutationHeaders\s*\(", cleaned))


def extract_request_calls(source: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    pattern = re.compile(r"request\.(post|put|patch|delete)\s*\(\s*\{")
    for match in pattern.finditer(source):
        open_brace = source.find("{", match.end() - 1)
        if open_brace < 0:
            continue
        depth = 0
        close_brace = None
        for index, char in enumerate(source[open_brace:], open_brace):
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    close_brace = index + 1
                    break
        snippet = source[match.start() : close_brace or match.start() + 500]
        url_match = re.search(r"url:\s*(?:`([^`]+)`|'([^']+)'|\"([^\"]+)\")", snippet)
        calls.append(
            {
                "method": match.group(1).upper(),
                "line": source[: match.start()].count("\n") + 1,
                "url": next((item for item in (url_match.groups() if url_match else ()) if item), ""),
                "hasMutationHeaders": has_mutation_headers_config(snippet),
            }
        )
    return calls


def frontend_mutation_header_check(api_file: Path) -> dict[str, Any]:
    source = api_file.read_text(encoding="utf-8")
    calls = extract_request_calls(source)
    missing = [
        call
        for call in calls
        if not call["hasMutationHeaders"] and call["url"] not in MUTATION_HEADER_EXEMPT_URLS
    ]
    exempt = [
        call
        for call in calls
        if not call["hasMutationHeaders"] and call["url"] in MUTATION_HEADER_EXEMPT_URLS
    ]
    status = "pass" if not missing else "fail"
    return {
        "name": "frontend.mutation-headers",
        "status": status,
        "detail": f"mutations={len(calls)}, missing={len(missing)}, exempt={len(exempt)}",
        "data": {
            "missing": missing,
            "exempt": exempt,
        },
    }


def frontend_mutation_helper_check(api_file: Path) -> dict[str, Any]:
    source = strip_typescript_comments(api_file.read_text(encoding="utf-8"))
    helper_match = re.search(
        r"const\s+mutationHeaders\s*=\s*\([^)]*\)\s*=>\s*\{(?P<body>.*?)\n\}",
        source,
        flags=re.DOTALL,
    )
    missing: list[str] = []
    if not helper_match:
        missing.append("mutationHeaders helper")
        body = ""
    else:
        body = helper_match.group("body")
    required_patterns = {
        "Idempotency-Key": r"Idempotency-Key",
        "idempotency fallback": r"idempotencyKey|\bcrypto\.randomUUID\b|Date\.now",
        "If-Match": r"If-Match",
        "etag option": r"options\?\.etag|options\.etag",
    }
    for label, pattern in required_patterns.items():
        if not re.search(pattern, body):
            missing.append(label)
    status = "pass" if not missing else "fail"
    return {
        "name": "frontend.mutation-helper",
        "status": status,
        "detail": "mutationHeaders carries Idempotency-Key and If-Match." if not missing else "Missing: " + ", ".join(missing),
        "data": {"missing": missing},
    }


def normalize_index_spec(spec: Any) -> dict[str, Any]:
    options: dict[str, Any] = {}
    keys = spec
    if isinstance(spec, dict):
        keys = spec.get("keys") or []
        options = dict(spec.get("options") or {})
    elif isinstance(spec, tuple) and len(spec) == 2 and isinstance(spec[0], str):
        keys = [spec]
    elif isinstance(spec, list) and spec and isinstance(spec[0], str):
        keys = [tuple(spec)]
    normalized_keys = [tuple(item) for item in keys]
    return {
        "fields": [str(item[0]) for item in normalized_keys],
        "keys": [[item[0], item[1]] for item in normalized_keys],
        "unique": bool(options.get("unique")),
    }


def normalized_postgres_indexes(indexes: dict[str, list[Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    source = indexes if indexes is not None else POSTGRES_INDEXES
    normalized: dict[str, list[dict[str, Any]]] = {}
    for table, specs in source.items():
        table_indexes = []
        for spec in specs:
            if isinstance(spec, dict):
                table_indexes.append(
                    {
                        "fields": list(spec.get("fields") or []),
                        "unique": bool(spec.get("unique")),
                        "type": spec.get("type", "btree"),
                    }
                )
            else:
                table_indexes.append(normalize_index_spec(spec))
        normalized[table] = table_indexes
    return normalized


def postgres_index_contract_check(indexes: dict[str, list[Any]] | None = None) -> dict[str, Any]:
    normalized = normalized_postgres_indexes(indexes)
    indexed_tables = set(normalized)
    persisted_collections = (
        set(STATE_COLLECTIONS.values()) | set(SINGLETON_COLLECTIONS.values()) | {IDEMPOTENCY_COLLECTION}
    )
    required_tables = {"aicheck_state", "aicheck_singletons", "idempotency_records"}
    missing_tables = sorted(required_tables - indexed_tables)
    missing_plan_collections = sorted(REQUIRED_PLAN_COLLECTIONS - persisted_collections)
    missing_critical = []
    for required in CRITICAL_POSTGRES_INDEXES:
        table_indexes = normalized.get(str(required["table"]), [])
        fields = list(required["fields"])
        unique = bool(required.get("unique", False))
        index_type = required.get("type")
        found = any(
            item["fields"][: len(fields)] == fields
            and (not unique or item["unique"])
            and (not index_type or item.get("type") == index_type)
            for item in table_indexes
        )
        if not found:
            missing_critical.append(required)
    status = "pass" if not missing_tables and not missing_plan_collections and not missing_critical else "fail"
    return {
        "name": "postgres.index-contract",
        "status": status,
        "detail": (
            f"tables={len(indexed_tables)}, persistedCollections={len(persisted_collections)}, "
            f"tableMissing={len(missing_tables)}, planMissing={len(missing_plan_collections)}, "
            f"criticalMissing={len(missing_critical)}"
        ),
        "data": {
            "indexedTables": sorted(indexed_tables),
            "persistedCollections": sorted(persisted_collections),
            "missingTables": missing_tables,
            "missingPlanCollections": missing_plan_collections,
            "missingCriticalIndexes": missing_critical,
        },
    }


def storage_contract_check(
    *,
    default_buckets: tuple[str, ...] | list[str] | None = None,
    storage_class: Any | None = None,
    repository_class: Any | None = None,
    parse_url_func: Any | None = None,
) -> dict[str, Any]:
    buckets = tuple(default_buckets if default_buckets is not None else DEFAULT_BUCKETS)
    storage_type = storage_class or ObjectStorage
    repository_type = repository_class or InMemoryRepository
    parse_func = parse_url_func or parse_storage_url

    missing_buckets = sorted(set(REQUIRED_STORAGE_BUCKETS) - set(buckets))
    unexpected_buckets = sorted(set(buckets) - set(REQUIRED_STORAGE_BUCKETS))
    duplicate_buckets = sorted({bucket for bucket in buckets if buckets.count(bucket) > 1})

    method_failures: list[dict[str, Any]] = []
    for method_name, required in REQUIRED_STORAGE_METHODS.items():
        method = getattr(storage_type, method_name, None)
        if method is None or not callable(method):
            method_failures.append({"method": method_name, "reason": "missing"})
            continue
        try:
            signature = inspect.signature(method)
            params = signature.parameters
        except (TypeError, ValueError):
            params = {}
        missing_params = [name for name in required["params"] if name not in params]
        source = source_for_callable(method)
        missing_source_terms = [term for term in required["source"] if term not in source]
        if missing_params or missing_source_terms:
            method_failures.append(
                {
                    "method": method_name,
                    "missingParams": missing_params,
                    "missingSourceTerms": missing_source_terms,
                }
            )

    repository_failures: list[dict[str, Any]] = []
    for method_name, required_terms in REQUIRED_REPOSITORY_STORAGE_CALLS.items():
        method = getattr(repository_type, method_name, None)
        if method is None or not callable(method):
            repository_failures.append({"method": method_name, "reason": "missing"})
            continue
        source = source_for_callable(method)
        missing_terms = [term for term in required_terms if term not in source]
        if missing_terms:
            repository_failures.append({"method": method_name, "missingSourceTerms": missing_terms})

    parse_failures: list[str] = []
    try:
        parsed = parse_func("minio://documents/path/to/%E6%8A%A5%E5%91%8A.pdf")
    except Exception as exc:
        parsed = None
        parse_failures.append(f"parse_storage_url raised {exc.__class__.__name__}")
    if parsed != ("documents", "path/to/报告.pdf"):
        parse_failures.append("parse_storage_url must decode minio bucket/object paths")

    status = (
        "pass"
        if not missing_buckets
        and not unexpected_buckets
        and not duplicate_buckets
        and not method_failures
        and not repository_failures
        and not parse_failures
        else "fail"
    )
    return {
        "name": "storage.bucket-contract",
        "status": status,
        "detail": (
            f"buckets={len(buckets)}, missingBuckets={len(missing_buckets)}, "
            f"unexpectedBuckets={len(unexpected_buckets)}, methodFailures={len(method_failures)}, "
            f"repositoryFailures={len(repository_failures)}, parseFailures={len(parse_failures)}"
        ),
        "data": {
            "requiredBuckets": list(REQUIRED_STORAGE_BUCKETS),
            "configuredBuckets": list(buckets),
            "missingBuckets": missing_buckets,
            "unexpectedBuckets": unexpected_buckets,
            "duplicateBuckets": duplicate_buckets,
            "methodFailures": method_failures,
            "repositoryFailures": repository_failures,
            "parseFailures": parse_failures,
        },
    }


def ocr_service_contract_check(
    *,
    ocr_main_module: Any | None = None,
    service_module: Any | None = None,
    fusion_module: Any | None = None,
) -> dict[str, Any]:
    if ocr_main_module is None:
        from apps.ocr_service import main as ocr_main_module
    if service_module is None:
        from apps.ocr_service import service as service_module
    if fusion_module is None:
        from apps.ocr_service import fusion as fusion_module

    health_failures: list[str] = []
    health_func = getattr(ocr_main_module, "healthz", None)
    health_source = source_for_callable(health_func) if callable(health_func) else ""
    service_type_for_health = getattr(service_module, "OcrService", None)
    service_health_source = source_for_callable(getattr(service_type_for_health, "health_payload", None))
    missing_health_fields = sorted(
        field for field in REQUIRED_OCR_HEALTH_FIELDS if field not in health_source + service_health_source
    )
    if not callable(health_func):
        health_failures.append("healthz endpoint is missing")
    if missing_health_fields:
        health_failures.append("missing health fields: " + ", ".join(missing_health_fields))
    if "ok(" not in health_source:
        health_failures.append("healthz must return the shared ok() response envelope")

    parse_failures: list[str] = []
    parse_func = getattr(ocr_main_module, "parse_document", None)
    parse_source = source_for_callable(parse_func) if callable(parse_func) else ""
    required_parse_terms = ["storageKey", "VALIDATION_ERROR", "ocr_service.parse_document", "ok("]
    missing_parse_terms = [term for term in required_parse_terms if term not in parse_source]
    if not callable(parse_func):
        parse_failures.append("parse endpoint is missing")
    if missing_parse_terms:
        parse_failures.append("missing parse endpoint terms: " + ", ".join(missing_parse_terms))
    doctor_failures: list[str] = []
    doctor_func = getattr(ocr_main_module, "runtime_doctor", None)
    doctor_source = source_for_callable(doctor_func) if callable(doctor_func) else ""
    if not callable(doctor_func):
        doctor_failures.append("runtime doctor endpoint is missing")
    elif "ocr_service.runtime_doctor_payload" not in doctor_source or "ok(" not in doctor_source:
        doctor_failures.append("runtime doctor endpoint must return ocr_service.runtime_doctor_payload in ok() envelope")

    service_failures: list[str] = []
    service_type = getattr(service_module, "OcrService", None)
    parse_method = getattr(service_type, "parse_document", None) if service_type else None
    local_parse_method = getattr(service_type, "parse_with_local_engines", None) if service_type else None
    doctor_method = getattr(service_type, "runtime_doctor_payload", None) if service_type else None
    service_source = source_for_callable(service_type) if service_type else ""
    parse_method_source = source_for_callable(parse_method) if callable(parse_method) else ""
    local_parse_source = source_for_callable(local_parse_method) if callable(local_parse_method) else ""
    required_service_terms = [
        "resolve_source_path",
        "AICHECK_OCR_ALLOW_PLACEHOLDER",
        "failed_result",
        "normalize_ocr_result",
    ]
    missing_service_terms = [term for term in required_service_terms if term not in parse_method_source]
    if not service_type:
        service_failures.append("OcrService class is missing")
    elif "_load_pipeline" not in service_source:
        service_failures.append("OcrService must load the agentdesign pipeline")
    if not callable(parse_method):
        service_failures.append("OcrService.parse_document is missing")
    if missing_service_terms:
        service_failures.append("missing OcrService.parse_document terms: " + ", ".join(missing_service_terms))
    doctor_method_source = source_for_callable(doctor_method) if callable(doctor_method) else ""
    if not callable(doctor_method):
        doctor_failures.append("OcrService.runtime_doctor_payload is missing")
    elif "build_runtime_doctor" not in doctor_method_source:
        doctor_failures.append("OcrService.runtime_doctor_payload must call build_runtime_doctor")
    resolve_source = source_for_callable(getattr(service_module, "resolve_source_path", None))
    for term in ["parse_storage_url", "download_to_temp"]:
        if term not in resolve_source:
            service_failures.append(f"resolve_source_path must use {term}")
    preprocess_failures: list[str] = []
    for term in [
        "requested_variant_names",
        "preprocessStatus",
        "missingVariants",
        "PREPROCESS_VARIANT_GENERATION_UNAVAILABLE",
    ]:
        if term not in local_parse_source:
            preprocess_failures.append(f"parse_with_local_engines missing {term}")
    quality_gate_failures: list[str] = []
    quality_gate_source = source_for_callable(getattr(fusion_module, "build_quality_gate", None))
    fusion_source = source_for_callable(fusion_module)
    for term in [
        "minFieldConfidence",
        "FIELD_LOW_CONFIDENCE",
        "lowConfidenceFields",
        "field_low_confidence",
        "FIELD_EVIDENCE_MISSING",
        "TABLE_EVIDENCE_MISSING",
        "SEAL_EVIDENCE_MISSING",
        "missingEvidence",
    ]:
        if term not in quality_gate_source and term not in fusion_source:
            quality_gate_failures.append(f"quality gate missing {term}")

    result_failures: list[str] = []
    normalize_func = getattr(service_module, "normalize_ocr_result", None)
    failed_func = getattr(service_module, "failed_result", None)
    try:
        normalized = normalize_func(
            {
                "text": "certificate A-001",
                "fields": [
                    {
                        "fieldName": "certificate_number",
                        "fieldValue": "A-001",
                        "pageNo": 1,
                        "bbox": [0, 0, 10, 10],
                        "confidence": 0.93,
                    }
                ],
                "seals": [
                    {
                        "page_index": 0,
                        "polygon": [1, 1, 8, 8],
                        "fields": {
                            "organization_name": {
                                "value": "Example Org",
                                "calibrated_confidence": 0.91,
                            }
                        },
                    }
                ],
                "diagnostics": [{"message": "ok"}],
            },
            "minio://documents/a.pdf",
            "a.pdf",
        )
    except Exception as exc:
        normalized = {}
        result_failures.append(f"normalize_ocr_result raised {exc.__class__.__name__}")
    if not isinstance(normalized, dict):
        normalized = {}
        result_failures.append("normalize_ocr_result must return a dict")
    missing_normalized_fields = sorted(REQUIRED_OCR_RESULT_FIELDS - set(normalized))
    if missing_normalized_fields:
        result_failures.append("missing normalized result fields: " + ", ".join(missing_normalized_fields))
    if normalized.get("status") != "success":
        result_failures.append("normalize_ocr_result must return status=success for valid raw results")
    if not all(isinstance(normalized.get(key), list) for key in ["fragments", "fields", "seals", "diagnostics"]):
        result_failures.append("normalized fragments/fields/seals/diagnostics must be lists")
    if len(normalized.get("fields") or []) < 2:
        result_failures.append("normalize_ocr_result must include raw fields and seal-derived fields")

    try:
        failed = failed_func("minio://documents/missing.pdf", "missing.pdf", "missing source")
    except Exception as exc:
        failed = {}
        result_failures.append(f"failed_result raised {exc.__class__.__name__}")
    if not isinstance(failed, dict):
        failed = {}
        result_failures.append("failed_result must return a dict")
    missing_failed_fields = sorted(REQUIRED_OCR_RESULT_FIELDS - set(failed))
    if missing_failed_fields:
        result_failures.append("missing failed result fields: " + ", ".join(missing_failed_fields))
    if failed.get("status") != "failed":
        result_failures.append("failed_result must return status=failed")
    if not all(isinstance(failed.get(key), list) for key in ["fragments", "fields", "seals", "diagnostics"]):
        result_failures.append("failed fragments/fields/seals/diagnostics must be lists")

    failures = (
        health_failures
        + parse_failures
        + doctor_failures
        + service_failures
        + preprocess_failures
        + quality_gate_failures
        + result_failures
    )
    status = "pass" if not failures else "fail"
    return {
        "name": "ocr.service-contract",
        "status": status,
        "detail": (
            "OCR service health, parse endpoint, source resolution, and result envelope are valid."
            if not failures
            else f"failures={len(failures)}"
        ),
        "data": {
            "healthFailures": health_failures,
            "parseFailures": parse_failures,
            "doctorFailures": doctor_failures,
            "serviceFailures": service_failures,
            "preprocessFailures": preprocess_failures,
            "qualityGateFailures": quality_gate_failures,
            "resultFailures": result_failures,
            "requiredHealthFields": sorted(REQUIRED_OCR_HEALTH_FIELDS),
            "requiredResultFields": sorted(REQUIRED_OCR_RESULT_FIELDS),
        },
    }


def ocr_evaluation_contract_check(
    *,
    evaluation_module: Any | None = None,
    cli_path: Path | None = None,
    fixture_path: Path | None = None,
    scorecard_path: Path | None = None,
) -> dict[str, Any]:
    if evaluation_module is None:
        from apps.ocr_service import evaluation as evaluation_module

    cli = cli_path or BACKEND_ROOT / "scripts" / "ocr_eval_set.py"
    scorecard_cli = scorecard_path or BACKEND_ROOT / "scripts" / "ocr_100_scorecard.py"
    corpus_cli = BACKEND_ROOT / "scripts" / "ocr_100_corpus.py"
    prefetch_cli = BACKEND_ROOT / "scripts" / "ocr_prefetch_models.py"
    fixture = fixture_path or BACKEND_ROOT / "ocr_eval" / "piping_release_set.json"
    failures: list[str] = []
    data: dict[str, Any] = {
        "requiredMetrics": sorted(REQUIRED_OCR_EVALUATION_METRICS),
        "metricFailures": [],
        "cliFailures": [],
        "scorecardFailures": [],
        "corpusFailures": [],
        "prefetchFailures": [],
        "fixtureFailures": [],
    }

    evaluate_cases = getattr(evaluation_module, "evaluate_cases", None)
    compact_evaluation_report = getattr(evaluation_module, "compact_evaluation_report", None)
    ocr_100_thresholds = getattr(evaluation_module, "ocr_100_thresholds", None)
    merge_thresholds = getattr(evaluation_module, "merge_thresholds", None)
    if not callable(evaluate_cases):
        failures.append("apps.ocr_service.evaluation.evaluate_cases is missing")
        data["metricFailures"].append("evaluate_cases missing")
    if not callable(compact_evaluation_report):
        failures.append("apps.ocr_service.evaluation.compact_evaluation_report is missing")
        data["metricFailures"].append("compact_evaluation_report missing")
    if not callable(ocr_100_thresholds):
        failures.append("apps.ocr_service.evaluation.ocr_100_thresholds is missing")
        data["metricFailures"].append("ocr_100_thresholds missing")
    if not callable(merge_thresholds):
        failures.append("apps.ocr_service.evaluation.merge_thresholds is missing")
        data["metricFailures"].append("merge_thresholds missing")
    if callable(ocr_100_thresholds):
        try:
            strict_thresholds = ocr_100_thresholds()
        except Exception as exc:
            strict_thresholds = {}
            failures.append(f"ocr_100_thresholds raised {exc.__class__.__name__}")
            data["metricFailures"].append(f"ocr_100_thresholds runtime error: {exc.__class__.__name__}")
        if isinstance(strict_thresholds, dict):
            data["strict100Thresholds"] = {
                "minCases": strict_thresholds.get("minCases"),
                "requiredScenarioCount": len(strict_thresholds.get("requiredScenarios") or []),
                "metricCount": len(strict_thresholds.get("metrics") or {}),
            }
            if int(strict_thresholds.get("minCases") or 0) < 100:
                failures.append("OCR 100 thresholds must require at least 100 cases")
                data["metricFailures"].append("strict100 minCases too low")
            missing_strict_metrics = sorted(REQUIRED_OCR_EVALUATION_METRICS - set(strict_thresholds.get("metrics") or {}))
            if missing_strict_metrics:
                failures.append("OCR 100 thresholds missing metrics: " + ", ".join(missing_strict_metrics))
                data["metricFailures"].extend(f"strict100.{metric}" for metric in missing_strict_metrics)
            if len(strict_thresholds.get("requiredScenarios") or []) < 10:
                failures.append("OCR 100 thresholds must require broad scenario coverage")
                data["metricFailures"].append("strict100 requiredScenarios too small")
    if callable(evaluate_cases):
        try:
            report = evaluate_cases(
                [
                    {
                        "caseId": "deployment-contract-ocr-eval",
                        "minScore": 1,
                        "result": {
                            "parseResultId": "PARSE-CONTRACT",
                            "status": "success",
                            "fields": [{"fieldCode": "pipe_no", "fieldValue": "PL8301", "bbox": [0, 0, 10, 10]}],
                            "tables": [
                                {
                                    "businessSchema": "piping_characteristic_table_v1",
                                    "rows": 2,
                                    "columns": 2,
                                    "bbox": [10, 10, 80, 80],
                                    "businessRows": [{"pipeNo": "PL8301"}],
                                }
                            ],
                            "seals": [{"sealName": "pressure pipe design license seal", "ocrConfidence": 0.9, "bbox": [100, 100, 180, 180]}],
                            "quality": {"status": "needs_human_review", "reasons": ["TABLE_HEURISTIC_REVIEW_REQUIRED"]},
                        },
                        "expected": {
                            "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [0, 0, 10, 10]}],
                            "tables": [
                                {
                                    "businessSchema": "piping_characteristic_table_v1",
                                    "requiredBusinessKeys": ["pipeNo"],
                                    "bbox": [10, 10, 80, 80],
                                }
                            ],
                            "seals": [{"nameContains": "design license", "minConfidence": 0.8, "bbox": [100, 100, 180, 180]}],
                            "qualityStatus": "needs_human_review",
                            "qualityReasons": ["TABLE_HEURISTIC_REVIEW_REQUIRED"],
                        },
                    }
                ]
            )
        except Exception as exc:
            report = {}
            failures.append(f"evaluate_cases raised {exc.__class__.__name__}")
            data["metricFailures"].append(f"runtime error: {exc.__class__.__name__}")
        metrics = report.get("metrics") if isinstance(report, dict) else {}
        missing_metrics = sorted(REQUIRED_OCR_EVALUATION_METRICS - set(metrics or {}))
        if missing_metrics:
            failures.append("missing OCR evaluation metrics: " + ", ".join(missing_metrics))
            data["metricFailures"].extend(missing_metrics)
        if isinstance(report, dict) and not report.get("ok"):
            failures.append("inline OCR evaluation contract case did not pass")
            data["metricFailures"].append("inline contract case failed")
        details = ((report.get("cases") or [{}])[0].get("details") or {}) if isinstance(report, dict) else {}
        missing_detail_keys = sorted(set(["fields", "tables", "seals", "quality"]) - set(details))
        if missing_detail_keys:
            failures.append("missing OCR evaluation details: " + ", ".join(missing_detail_keys))
            data["metricFailures"].extend(f"details.{key}" for key in missing_detail_keys)
        if not isinstance(report.get("findingCounts") if isinstance(report, dict) else None, dict):
            failures.append("OCR evaluation report must expose findingCounts")
            data["metricFailures"].append("findingCounts missing")
        if callable(compact_evaluation_report):
            compact = compact_evaluation_report(report if isinstance(report, dict) else {})
            required_compact_keys = {"ok", "summary", "metrics", "findingCounts", "thresholdFailures", "scenarioMetrics", "failedCases"}
            missing_compact_keys = sorted(required_compact_keys - set(compact if isinstance(compact, dict) else {}))
            if missing_compact_keys:
                failures.append("OCR compact evaluation report missing keys: " + ", ".join(missing_compact_keys))
                data["metricFailures"].extend(f"compact.{key}" for key in missing_compact_keys)
            else:
                data["compactSummary"] = {
                    "ok": compact.get("ok"),
                    "failedCases": len(compact.get("failedCases") or []),
                    "scenarioCount": len(compact.get("scenarioMetrics") or {}),
                }
            try:
                contract_repo = InMemoryRepository()
                persisted = contract_repo.create_ocr_eval_run(
                    {
                        "id": "OCREVAL-CONTRACT-COMPACT",
                        "profileId": "deployment_contract",
                        "caseCount": 1,
                        "evaluationSummary": compact,
                    }
                )
            except Exception as exc:
                persisted = {}
                failures.append(f"repository OCR evaluationSummary persistence raised {exc.__class__.__name__}")
                data["metricFailures"].append(f"evaluationSummary persistence runtime error: {exc.__class__.__name__}")
            if not isinstance(persisted, dict) or not persisted.get("evaluationSummary"):
                failures.append("Repository must preserve OCR evaluationSummary")
                data["metricFailures"].append("evaluationSummary persistence missing")
            if isinstance(persisted, dict) and (persisted.get("metrics") or {}).get("caseCount") != 1:
                failures.append("Repository must preserve explicit OCR evaluation caseCount")
                data["metricFailures"].append("evaluation caseCount persistence mismatch")
        try:
            evidence_report = evaluate_cases(
                [
                    {
                        "caseId": "deployment-contract-field-evidence-negative",
                        "minScore": 0,
                        "result": {
                            "parseResultId": "PARSE-CONTRACT-NO-EVIDENCE",
                            "status": "success",
                            "fields": [{"fieldCode": "pipe_no", "fieldValue": "PL8301"}],
                            "tables": [{"businessSchema": "piping_characteristic_table_v1", "businessRows": [{"pipeNo": "PL8301"}]}],
                            "seals": [{"sealName": "pressure pipe design license seal", "ocrConfidence": 0.9}],
                            "quality": {"status": "auto_usable", "reasons": [], "evidenceCompleteness": 1.0},
                        },
                        "expected": {
                            "fields": [{"fieldCode": "pipe_no", "value": "PL8301"}],
                            "tables": [{"businessSchema": "piping_characteristic_table_v1", "requiredBusinessKeys": ["pipeNo"]}],
                            "seals": [{"nameContains": "design license", "minConfidence": 0.8}],
                            "maxEvidenceCompleteness": 0.99,
                        },
                    }
                ]
            )
        except Exception as exc:
            evidence_report = {}
            failures.append(f"field evidence negative case raised {exc.__class__.__name__}")
            data["metricFailures"].append(f"field evidence runtime error: {exc.__class__.__name__}")
        evidence_findings = {
            item.get("code")
            for item in (((evidence_report.get("cases") or [{}])[0]).get("findings") or [])
            if isinstance(item, dict)
        } if isinstance(evidence_report, dict) else set()
        if "OCR_EVAL_FIELD_EVIDENCE_MISSING" not in evidence_findings or evidence_report.get("ok"):
            failures.append("OCR evaluation must fail field values without bbox/polygon evidence")
            data["metricFailures"].append("field evidence negative case failed")
        if "OCR_EVAL_TABLE_EVIDENCE_MISSING" not in evidence_findings or evidence_report.get("ok"):
            failures.append("OCR evaluation must fail matched tables without bbox/polygon evidence")
            data["metricFailures"].append("table evidence negative case failed")
        if "OCR_EVAL_SEAL_EVIDENCE_MISSING" not in evidence_findings or evidence_report.get("ok"):
            failures.append("OCR evaluation must fail matched seals without bbox/polygon evidence")
            data["metricFailures"].append("seal evidence negative case failed")
        if "OCR_EVAL_QUALITY_EVIDENCE_COMPLETENESS_MISMATCH" not in evidence_findings or evidence_report.get("ok"):
            failures.append("OCR evaluation must fail mismatched quality.evidenceCompleteness")
            data["metricFailures"].append("quality evidence completeness negative case failed")
        evidence_finding_counts = evidence_report.get("findingCounts") if isinstance(evidence_report, dict) else {}
        for code in [
            "OCR_EVAL_FIELD_EVIDENCE_MISSING",
            "OCR_EVAL_TABLE_EVIDENCE_MISSING",
            "OCR_EVAL_SEAL_EVIDENCE_MISSING",
            "OCR_EVAL_QUALITY_EVIDENCE_COMPLETENESS_MISMATCH",
        ]:
            if not isinstance(evidence_finding_counts, dict) or int(evidence_finding_counts.get(code) or 0) < 1:
                failures.append(f"OCR evaluation findingCounts missing {code}")
                data["metricFailures"].append(f"findingCounts.{code} missing")
        data["inlineReportSummary"] = report.get("summary") if isinstance(report, dict) else None

    if not cli.exists():
        failures.append(f"OCR evaluation CLI is missing: {cli}")
        data["cliFailures"].append("missing")
    else:
        cli_source = cli.read_text(encoding="utf-8")
        for term in [
            "evaluate_cases",
            "thresholds",
            "markdown_report",
            "normalize_case_paths",
            "resolve_local_reference",
            "write_text_file",
            "compact_evaluation_report",
            "--run-ocr",
            "--strict-100",
            "--min-average-score",
            "--output",
            "--summary-output",
            "--markdown-output",
            "ocr_100_thresholds",
            "merge_thresholds",
        ]:
            if term not in cli_source:
                failures.append(f"OCR evaluation CLI missing term: {term}")
                data["cliFailures"].append(term)

    if not scorecard_cli.exists():
        failures.append(f"OCR 100 scorecard CLI is missing: {scorecard_cli}")
        data["scorecardFailures"].append("missing")
    else:
        scorecard_source = scorecard_cli.read_text(encoding="utf-8")
        for term in [
            "build_ocr_100_scorecard",
            "ocr_100_thresholds",
            "--eval-set",
            "--sample-summary",
            "--runtime-doctor-json",
            "--run-ocr",
            "--output",
        ]:
            if term not in scorecard_source:
                failures.append(f"OCR 100 scorecard CLI missing term: {term}")
                data["scorecardFailures"].append(term)
    try:
        from apps.api import routes as api_routes_module

        quality_source = source_for_callable(getattr(api_routes_module, "fde_ocr_quality_snapshot", None))
        quality_source += source_for_callable(getattr(api_routes_module, "fde_ocr_100_scorecard_snapshot", None))
    except Exception as exc:
        quality_source = ""
        failures.append(f"FDE OCR quality contract source unavailable: {exc.__class__.__name__}")
        data["scorecardFailures"].append(f"fde source unavailable: {exc.__class__.__name__}")
    for term in ["ocr100Scorecard", "build_ocr_100_scorecard", "runtime_doctor_report", "sample_summaries"]:
        if term not in quality_source:
            failures.append(f"FDE OCR quality endpoint missing OCR 100 term: {term}")
            data["scorecardFailures"].append(f"fde.{term}")

    if not corpus_cli.exists():
        failures.append(f"OCR 100 corpus CLI is missing: {corpus_cli}")
        data["corpusFailures"].append("missing")
    else:
        corpus_source = corpus_cli.read_text(encoding="utf-8")
        for term in [
            "build_corpus_report",
            "ocr_100_thresholds",
            "OCR_100_REQUIRED_SCENARIOS",
            "--allow-missing-expected-evidence",
            "--output",
            "--report-output",
            "OCR_100_CORPUS_TOO_SMALL",
            "OCR_100_CORPUS_EXPECTED_EVIDENCE_MISSING",
        ]:
            if term not in corpus_source:
                failures.append(f"OCR 100 corpus CLI missing term: {term}")
                data["corpusFailures"].append(term)

    if not prefetch_cli.exists():
        failures.append(f"OCR model prefetch CLI is missing: {prefetch_cli}")
        data["prefetchFailures"].append("missing")
    else:
        prefetch_source = prefetch_cli.read_text(encoding="utf-8")
        for term in [
            "OCR_100_PADDLEX_MODELS",
            "create_model",
            "--ocr-100",
            "--verify-only",
            "PADDLE_PDX_CACHE_HOME",
            "OCR_PREFETCH_MODEL_MISSING",
        ]:
            if term not in prefetch_source:
                failures.append(f"OCR model prefetch CLI missing term: {term}")
                data["prefetchFailures"].append(term)

    if not fixture.exists():
        failures.append(f"OCR release evaluation fixture is missing: {fixture}")
        data["fixtureFailures"].append("missing")
    elif callable(evaluate_cases):
        try:
            payload = json.loads(fixture.read_text(encoding="utf-8"))
            cases = payload.get("cases") if isinstance(payload, dict) else payload
            thresholds = payload.get("thresholds") if isinstance(payload, dict) and isinstance(payload.get("thresholds"), dict) else None
            if not isinstance(cases, list) or not cases:
                failures.append("OCR release evaluation fixture must contain cases[]")
                data["fixtureFailures"].append("cases[] missing")
            else:
                fixture_report = evaluate_cases(cases, thresholds=thresholds)
                data["fixtureSummary"] = fixture_report.get("summary")
                data["fixtureScenarios"] = sorted((fixture_report.get("scenarios") or {}).keys())
                if not fixture_report.get("ok"):
                    failures.append("OCR release evaluation fixture does not pass")
                    data["fixtureFailures"].append("fixture failed")
        except Exception as exc:
            failures.append(f"OCR release evaluation fixture failed to load: {exc.__class__.__name__}")
            data["fixtureFailures"].append(exc.__class__.__name__)

    return {
        "name": "ocr.evaluation-contract",
        "status": "pass" if not failures else "fail",
        "detail": "OCR release evaluation set and runner are usable." if not failures else f"failures={len(failures)}",
        "data": data,
    }


def ocr_profile_contract_check() -> dict[str, Any]:
    from libs.ocr.profiles import OCR_PROFILES, validate_profiles

    failures = validate_profiles()
    profile_ids = sorted(OCR_PROFILES)
    business_profiles = [profile_id for profile_id in profile_ids if profile_id != "generic_document_v1"]
    status = "pass" if not failures else "fail"
    return {
        "name": "ocr.profile-contract",
        "status": status,
        "detail": (
            f"profiles={len(profile_ids)}, businessProfiles={len(business_profiles)}, failures=0"
            if not failures
            else f"profiles={len(profile_ids)}, failures={len(failures)}"
        ),
        "data": {
            "profileIds": profile_ids,
            "businessProfileIds": business_profiles,
            "failures": failures,
            "requiredQualityRuleKeys": [
                "criticalConflictFields",
                "minFieldConfidence",
                "minTableStructureConfidence",
            ],
        },
    }


def litellm_client_contract_check(
    *,
    client_class: Any | None = None,
    worker_tasks_module: Any | None = None,
) -> dict[str, Any]:
    client_type = client_class or LiteLLMClient
    if worker_tasks_module is None:
        from apps.worker import tasks as worker_tasks_module

    client_failures: list[dict[str, Any]] = []
    for method_name, required_terms in REQUIRED_LITELLM_CLIENT_METHODS.items():
        method = getattr(client_type, method_name, None)
        if method is None or not callable(method):
            client_failures.append({"method": method_name, "reason": "missing"})
            continue
        source = source_for_callable(method)
        missing_terms = [term for term in required_terms if term not in source]
        if missing_terms:
            client_failures.append({"method": method_name, "missingSourceTerms": missing_terms})

    worker_failures: list[dict[str, Any]] = []
    for task_name, required_terms in REQUIRED_LITELLM_WORKER_USAGE.items():
        task = getattr(worker_tasks_module, task_name, None)
        if task is None or not callable(task):
            worker_failures.append({"task": task_name, "reason": "missing"})
            continue
        source = source_for_callable(getattr(task, "run", task))
        missing_terms = [term for term in required_terms if term not in source]
        if missing_terms:
            worker_failures.append({"task": task_name, "missingSourceTerms": missing_terms})

    runtime_failures: list[str] = []
    requests: list[dict[str, Any]] = []

    def success_transport(request: httpx.Request) -> httpx.Response:
        try:
            body = json.loads(request.content.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            body = {}
        requests.append(
            {
                "path": request.url.path,
                "authorization": request.headers.get("Authorization"),
                "body": body,
            }
        )
        if request.url.path.endswith("/v1/chat/completions"):
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ok"}}]},
                request=request,
            )
        if request.url.path.endswith("/v1/embeddings"):
            return httpx.Response(
                200,
                json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]},
                request=request,
            )
        return httpx.Response(404, json={"error": "unexpected path"}, request=request)

    try:
        probe_client = client_type(
            base_url="http://litellm",
            api_key="sk-contract-test",
            transport=httpx.MockTransport(success_transport),
        )
        chat_response = probe_client.chat_sync([{"role": "user", "content": "ping"}])
        embed_response = probe_client.embed_sync(["ping"])
        if probe_client.first_message_text(chat_response) != "ok":
            runtime_failures.append("first_message_text must extract assistant content")
        if not embed_response.get("data"):
            runtime_failures.append("embedding response must preserve data")
    except Exception as exc:
        runtime_failures.append(f"mocked LiteLLM request failed: {exc.__class__.__name__}: {exc}")

    chat_request = next((item for item in requests if item["path"] == "/v1/chat/completions"), None)
    embed_request = next((item for item in requests if item["path"] == "/v1/embeddings"), None)
    if not chat_request:
        runtime_failures.append("chat_sync must call /v1/chat/completions")
    elif chat_request["authorization"] != "Bearer sk-contract-test" or chat_request["body"].get("model") != "default-chat":
        runtime_failures.append("chat_sync must send Bearer auth and default-chat model")
    if not embed_request:
        runtime_failures.append("embed_sync must call /v1/embeddings")
    elif embed_request["authorization"] != "Bearer sk-contract-test" or embed_request["body"].get("model") != "embedding-default":
        runtime_failures.append("embed_sync must send Bearer auth and embedding-default model")

    def failure_transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "upstream key sk-secret-litellm is invalid"}},
            request=request,
        )

    try:
        failing_client = client_type(
            base_url="http://litellm",
            api_key="sk-contract-test",
            transport=httpx.MockTransport(failure_transport),
        )
        failing_client.chat_sync([{"role": "user", "content": "ping"}])
        runtime_failures.append("HTTP provider failures must raise a sanitized integration error")
    except Exception as exc:
        text = str(exc)
        if "sk-secret-litellm" in text or "upstream key" in text:
            runtime_failures.append("provider error details leaked from LiteLLM client")
        if "LiteLLM" not in text or "HTTP 401" not in text:
            runtime_failures.append("LiteLLM HTTP failures must keep service name and HTTP status")

    status = "pass" if not client_failures and not worker_failures and not runtime_failures else "fail"
    return {
        "name": "litellm.client-contract",
        "status": status,
        "detail": (
            "LiteLLM client and worker usage match OpenAI-compatible gateway contract."
            if status == "pass"
            else (
                f"clientFailures={len(client_failures)}, workerFailures={len(worker_failures)}, "
                f"runtimeFailures={len(runtime_failures)}"
            )
        ),
        "data": {
            "clientFailures": client_failures,
            "workerFailures": worker_failures,
            "runtimeFailures": runtime_failures,
            "requiredMethods": sorted(REQUIRED_LITELLM_CLIENT_METHODS),
            "requiredWorkerTasks": sorted(REQUIRED_LITELLM_WORKER_USAGE),
        },
    }


def knowledge_rule_contract_check(
    *,
    fastapi_app: Any | None = None,
    execution_module: Any | None = None,
    retrieval_module: Any | None = None,
    readiness_module: Any | None = None,
) -> dict[str, Any]:
    if execution_module is None:
        from libs.review_orchestrator import execution as execution_module
    if retrieval_module is None:
        import libs.knowledge_retrieval as retrieval_module
    if readiness_module is None:
        import libs.knowledge_readiness as readiness_module

    app_obj = fastapi_app or app
    routes_to_check = list(getattr(app_obj, "routes", []) or [])
    api_routes_module = None
    if fastapi_app is None:
        from apps.api import routes as api_routes

        api_routes_module = api_routes
        routes_to_check.extend(getattr(api_routes.router, "routes", []) or [])
    if api_routes_module is None:
        from apps.api import routes as api_routes

        api_routes_module = api_routes
    route_failures: list[dict[str, Any]] = []
    route_summaries: list[dict[str, Any]] = []
    for required in REQUIRED_KNOWLEDGE_RULE_ROUTES:
        expected_method = str(required["method"])
        expected_suffix = str(required["suffix"])
        found = False
        for route in routes_to_check:
            route_path = str(getattr(route, "path", ""))
            route_methods = {str(method).upper() for method in (getattr(route, "methods", set()) or set())}
            if route_path.endswith(expected_suffix) and expected_method in route_methods:
                route_summaries.append({"method": expected_method, "path": route_path})
                found = True
                break
        if not found:
            route_failures.append({"method": expected_method, "suffix": expected_suffix})

    collection_failures: list[str] = []
    repository_collections = set(STATE_COLLECTIONS.values()) | set(SINGLETON_COLLECTIONS.values())
    missing_repository = sorted(REQUIRED_KNOWLEDGE_RULE_COLLECTIONS - repository_collections)
    if missing_repository:
        collection_failures.append("knowledge/rule collections missing repository mapping: " + ", ".join(missing_repository))
    if "idx_aicheck_state_payload_gin" not in {item.get("name") for item in POSTGRES_INDEXES.get("aicheck_state", [])}:
        collection_failures.append("PostgreSQL JSONB payload GIN index is missing for knowledge/rule collections")

    run_step_source = source_for_callable(getattr(execution_module, "run_step", None))
    retrieval_source = (
        source_for_callable(getattr(retrieval_module, "retrieve_knowledge_clauses", None))
        + source_for_callable(getattr(retrieval_module, "knowledge_clause_candidates", None))
    )
    knowledge_rule_source = run_step_source + retrieval_source
    field_failures: list[str] = []
    missing_rule_fields = sorted(field for field in REQUIRED_RULE_CHECK_RESULT_FIELDS if field not in run_step_source)
    missing_trace_fields = sorted(field for field in REQUIRED_RETRIEVAL_TRACE_FIELDS if field not in knowledge_rule_source)
    if missing_rule_fields:
        field_failures.append("RuleCheckResult missing fields in run_step: " + ", ".join(missing_rule_fields))
    run_step_uses_retrieval_trace = (
        "retrieve_knowledge_clauses" in run_step_source
        and "retrieval_traces" in run_step_source
        and "trace" in run_step_source
    )
    if not run_step_uses_retrieval_trace:
        field_failures.append(
            "RetrievalTrace missing fields in run_step: "
            + ", ".join(sorted(REQUIRED_RETRIEVAL_TRACE_FIELDS))
        )
    elif missing_trace_fields:
        field_failures.append("RetrievalTrace missing fields in run_step: " + ", ".join(missing_trace_fields))
    for term in [
        "clause_index",
        "hybrid_bm25_dense",
        "exact_clause_lookup",
        "pageindex_tree",
        "pageIndexTree",
        "local_page_index_nodes",
        "queryRouter",
        "selectedRoute",
        "search_knowledge_base",
        "run_rule_engine",
    ]:
        if term not in knowledge_rule_source:
            field_failures.append(f"knowledge/rule source missing term: {term}")

    readiness_source = (
        source_for_callable(getattr(readiness_module, "build_knowledge_rule_scorecard", None))
        + source_for_callable(getattr(readiness_module, "source_index_section", None))
        + source_for_callable(getattr(readiness_module, "rule_clause_section", None))
        + source_for_callable(getattr(readiness_module, "retrieval_router_section", None))
        + source_for_callable(getattr(readiness_module, "evaluation_governance_section", None))
        + source_for_callable(getattr(readiness_module, "run_retrieval_probes", None))
        + repr(getattr(readiness_module, "REQUIRED_KNOWLEDGE_ROUTES", {}))
    )
    for term in [
        "aicheck-knowledge-rule-scorecard-v1",
        "source-index",
        "rule-clause",
        "retrieval-router",
        "evaluation-governance",
        "REQUIRED_KNOWLEDGE_ROUTES",
        "exact_clause_lookup",
        "hybrid_review_basis_search",
        "pageindex_tree_search",
        "retrievalProbes",
        "retrievalRecall",
        "wrongReferenceRate",
        "persisted RetrievalTrace",
    ]:
        if term not in readiness_source:
            field_failures.append(f"knowledge readiness scorecard missing term: {term}")
    overview_source = source_for_callable(getattr(api_routes_module, "knowledge_overview", None))
    for term in ["scorecard", "build_knowledge_rule_scorecard"]:
        if term not in overview_source:
            field_failures.append(f"knowledge overview missing scorecard term: {term}")

    validation_failures: list[str] = []
    required_validation_sources = {
        "validate_review_schema": [
            "REVIEW_FINDING_REQUIRED_FIELDS",
            "FINDING_SCHEMA_MISSING_FIELDS",
            "FINDING_MUST_REQUIRE_HUMAN_CONFIRMATION",
        ],
        "validate_review_evidence_refs": [
            "EVIDENCE_LINK_NOT_FOUND",
            "EVIDENCE_REF_BAD_BBOX",
            "documentVersionId",
            "pageNo",
            "bbox",
        ],
        "validate_review_references": [
            "RULE_REF_NOT_FOUND",
            "KB_RETRIEVAL_TRACE_NOT_FOUND",
            "KB_CLAUSE_NOT_IN_TRACE",
            "selectedClauses",
            "ruleSetVersion",
            "kbVersion",
        ],
        "review_quality_gate": [
            "schema_validation",
            "evidence_validation",
            "reference_validation",
            "requiresHumanReview",
            "ready_for_human_review",
        ],
    }
    for name, terms in required_validation_sources.items():
        source = source_for_callable(getattr(execution_module, name, None))
        if not source:
            validation_failures.append(f"{name} is missing")
            continue
        missing_terms = [term for term in terms if term not in source]
        if missing_terms:
            validation_failures.append(f"{name} missing source terms: " + ", ".join(missing_terms))

    failures = route_failures + collection_failures + field_failures + validation_failures
    status = "pass" if not failures else "fail"
    return {
        "name": "knowledge-rule.contract",
        "status": status,
        "detail": (
            "Knowledge source, rule version, retrieval trace, rule-check, and reference validation contracts are present."
            if status == "pass"
            else f"failures={len(failures)}"
        ),
        "data": {
            "routeFailures": route_failures,
            "collectionFailures": collection_failures,
            "fieldFailures": field_failures,
            "validationFailures": validation_failures,
            "routeCount": len(route_summaries),
            "requiredRoutes": REQUIRED_KNOWLEDGE_RULE_ROUTES,
            "requiredCollections": sorted(REQUIRED_KNOWLEDGE_RULE_COLLECTIONS),
            "requiredRuleCheckFields": sorted(REQUIRED_RULE_CHECK_RESULT_FIELDS),
            "requiredRetrievalTraceFields": sorted(REQUIRED_RETRIEVAL_TRACE_FIELDS),
            "readinessScorecard": "build_knowledge_rule_scorecard" in readiness_source,
        },
    }


def lossless_evidence_coverage_check(
    *,
    manifests: list[dict[str, Any]] | None = None,
    coverages: list[dict[str, Any]] | None = None,
    review_runs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    manifest_rows = [
        row
        for row in (manifests if manifests is not None else repo.state.get("evidence_manifests") or [])
        if isinstance(row, dict)
    ]
    default_runs = [
        *(repo.state.get("review_runs") or []),
        *(repo.state.get("ai_runs") or []),
    ]
    run_rows = [
        row
        for row in (review_runs if review_runs is not None else default_runs)
        if isinstance(row, dict)
    ]
    if coverages is None:
        coverage_rows = [
            {
                "evidenceManifestId": row.get("evidenceManifestId"),
                **(row.get("evidenceCoverage") or {}),
            }
            for row in run_rows
            if row.get("evidenceManifestId") and isinstance(row.get("evidenceCoverage"), dict)
        ]
    else:
        coverage_rows = [row for row in coverages if isinstance(row, dict)]

    if not manifest_rows:
        return {
            "name": "review.lossless-evidence-coverage",
            "status": "skip",
            "detail": "No persisted EvidenceManifest records are available yet.",
            "data": {
                "gateStatus": "not_applicable",
                "manifestCount": 0,
                "missingArtifactCount": 0,
                "failures": [],
            },
        }

    coverage_by_manifest: dict[str, list[dict[str, Any]]] = {}
    for coverage in coverage_rows:
        manifest_id = str(coverage.get("evidenceManifestId") or "")
        if manifest_id:
            coverage_by_manifest.setdefault(manifest_id, []).append(coverage)

    failures: list[dict[str, Any]] = []
    missing_artifact_count = 0
    for manifest in manifest_rows:
        manifest_id = str(
            manifest.get("evidenceManifestId") or manifest.get("id") or ""
        )
        expected = int((manifest.get("counts") or {}).get("total") or 0)
        candidates = coverage_by_manifest.get(manifest_id) or []
        if not candidates:
            failures.append(
                {
                    "evidenceManifestId": manifest_id,
                    "code": "MISSING_COVERAGE_REPORT",
                }
            )
            missing_artifact_count += expected
            continue
        coverage = candidates[-1]
        missing_ids = [str(item) for item in coverage.get("missingArtifactIds") or []]
        duplicate_ids = [str(item) for item in coverage.get("duplicateArtifactIds") or []]
        incomplete_ids = [str(item) for item in coverage.get("incompleteArtifactIds") or []]
        processed = int(coverage.get("processedArtifactCount") or 0)
        missing_count = max(len(missing_ids), max(0, expected - processed))
        missing_artifact_count += missing_count
        if (
            coverage.get("coveragePassed") is not True
            or missing_count
            or duplicate_ids
            or incomplete_ids
        ):
            failures.append(
                {
                    "evidenceManifestId": manifest_id,
                    "code": "INCOMPLETE_EVIDENCE_COVERAGE",
                    "expectedArtifactCount": expected,
                    "processedArtifactCount": processed,
                    "missingArtifactIds": missing_ids,
                    "duplicateArtifactIds": duplicate_ids,
                    "incompleteArtifactIds": incomplete_ids,
                }
            )

    terminal_statuses = {
        "waiting_human_review",
        "accepted_by_human",
        "edited_by_human",
        "rejected_by_human",
        "completed",
        "完成",
    }
    for run in run_rows:
        if (
            str(run.get("status") or "") in terminal_statuses
            and run.get("evidenceManifestId")
            and (run.get("evidenceCoverage") or {}).get("coveragePassed") is not True
        ):
            failures.append(
                {
                    "reviewRunId": run.get("reviewRunId") or run.get("id"),
                    "evidenceManifestId": run.get("evidenceManifestId"),
                    "code": "TERMINAL_REVIEW_WITH_INCOMPLETE_EVIDENCE",
                }
            )

    status = "fail" if failures else "pass"
    return {
        "name": "review.lossless-evidence-coverage",
        "status": status,
        "detail": (
            "Every EvidenceManifest has complete, unique artifact coverage."
            if status == "pass"
            else f"Lossless evidence coverage blocked: failures={len(failures)}."
        ),
        "data": {
            "gateStatus": "blocked" if failures else "passed",
            "manifestCount": len(manifest_rows),
            "coverageReportCount": len(coverage_rows),
            "missingArtifactCount": missing_artifact_count,
            "failures": failures,
        },
    }


def review_orchestration_contract_check(
    *,
    fastapi_app: Any | None = None,
    execution_module: Any | None = None,
    dispatcher_module: Any | None = None,
    graph_module: Any | None = None,
    readiness_module: Any | None = None,
    worker_main_module: Any | None = None,
    workflow_module: Any | None = None,
    activities_module: Any | None = None,
) -> dict[str, Any]:
    if execution_module is None:
        from libs.review_orchestrator import execution as execution_module
    if dispatcher_module is None:
        from libs.review_orchestrator import dispatcher as dispatcher_module
    if graph_module is None:
        from libs.review_orchestrator import graph as graph_module
    if readiness_module is None:
        from libs.review_orchestrator import readiness as readiness_module
    worker_main_source = ""
    workflow_source = ""
    activities_source = ""
    if worker_main_module is None:
        worker_main_source = (BACKEND_ROOT / "apps" / "review_worker" / "main.py").read_text(encoding="utf-8")
    if workflow_module is None:
        workflow_source = (BACKEND_ROOT / "apps" / "review_worker" / "workflows.py").read_text(encoding="utf-8")
    if activities_module is None:
        activities_source = (BACKEND_ROOT / "apps" / "review_worker" / "activities.py").read_text(encoding="utf-8")

    app_obj = fastapi_app or app
    routes_to_check = list(getattr(app_obj, "routes", []) or [])
    api_routes_module = None
    if fastapi_app is None:
        from apps.api import routes as api_routes_module

        routes_to_check.extend(getattr(api_routes_module.router, "routes", []) or [])
    route_failures: list[dict[str, Any]] = []
    route_summaries: list[dict[str, Any]] = []
    for required in REQUIRED_REVIEW_RUN_ROUTES:
        expected_method = str(required["method"])
        expected_suffix = str(required["suffix"])
        found = False
        for route in routes_to_check:
            route_path = str(getattr(route, "path", ""))
            route_methods = {str(method).upper() for method in (getattr(route, "methods", set()) or set())}
            if route_path.endswith(expected_suffix) and expected_method in route_methods:
                route_summaries.append({"method": expected_method, "path": route_path})
                found = True
                break
        if not found:
            route_failures.append({"method": expected_method, "suffix": expected_suffix})

    graph_failures: list[str] = []
    steps = getattr(execution_module, "REVIEW_GRAPH_STEPS", []) or []
    step_keys = [str(item.get("key")) for item in steps if isinstance(item, dict)]
    missing_steps = [key for key in REQUIRED_REVIEW_GRAPH_STEP_KEYS if key not in step_keys]
    if missing_steps:
        graph_failures.append("missing graph steps: " + ", ".join(missing_steps))
    if len(step_keys) < len(REQUIRED_REVIEW_GRAPH_STEP_KEYS):
        graph_failures.append("graph step count is below contract")
    edges = getattr(execution_module, "REVIEW_GRAPH_EDGES", []) or []
    if len(edges) < max(0, len(step_keys) - 1):
        graph_failures.append("graph edges must connect the ordered review steps")
    task_queues = {
        str(item.get("taskQueue"))
        for item in steps
        if isinstance(item, dict) and item.get("taskQueue")
    }
    required_task_queues = {"review.graph", "review.validation", "review.retrieval", "review.llm"}
    missing_task_queues = sorted(required_task_queues - task_queues)
    if missing_task_queues:
        graph_failures.append("missing graph task queues: " + ", ".join(missing_task_queues))

    state_failures: list[str] = []
    collections = set(getattr(execution_module, "REVIEW_STATE_COLLECTIONS", []) or [])
    missing_collections = sorted(REQUIRED_REVIEW_COLLECTIONS - collections)
    if missing_collections:
        state_failures.append("missing review state collections: " + ", ".join(missing_collections))
    if "idx_aicheck_state_payload_gin" not in {item.get("name") for item in POSTGRES_INDEXES.get("aicheck_state", [])}:
        state_failures.append("PostgreSQL JSONB payload GIN index is missing for review state collections")
    if not REQUIRED_REVIEW_COLLECTIONS.issubset(set(STATE_COLLECTIONS.values())):
        missing_state_map = sorted(REQUIRED_REVIEW_COLLECTIONS - set(STATE_COLLECTIONS.values()))
        state_failures.append("review state collections missing repository mapping: " + ", ".join(missing_state_map))

    tool_failures: list[str] = []
    allowed_tools = set(getattr(execution_module, "ALLOWED_AGENT_TOOLS", set()) or set())
    forbidden_tools = set(getattr(execution_module, "FORBIDDEN_AGENT_TOOLS", set()) or set())
    missing_allowed = sorted(REQUIRED_REVIEW_ALLOWED_TOOLS - allowed_tools)
    missing_forbidden = sorted(REQUIRED_REVIEW_FORBIDDEN_TOOLS - forbidden_tools)
    overlap = sorted(allowed_tools & forbidden_tools)
    if missing_allowed:
        tool_failures.append("missing allowed tools: " + ", ".join(missing_allowed))
    if missing_forbidden:
        tool_failures.append("missing forbidden tools: " + ", ".join(missing_forbidden))
    if overlap:
        tool_failures.append("tools cannot be both allowed and forbidden: " + ", ".join(overlap))

    source_failures: list[str] = []

    def require_source_terms(label: str, source: str, terms: list[str]) -> None:
        missing = [term for term in terms if term not in source]
        if missing:
            source_failures.append(f"{label} missing source terms: " + ", ".join(missing))

    require_source_terms(
        "create_review_run_from_ai_run",
        source_for_callable(getattr(execution_module, "create_review_run_from_ai_run", None)),
        [
            "workflowEngine",
            "ReviewRunWorkflow",
            "modelGateway",
            "qwen_runtime",
            "ids_hashes_versions_only",
            "payloadCodecRequiredInProduction",
            "stable_hash_payload",
            "seed_graph_nodes",
        ],
    )
    require_source_terms(
        "execute_review_run_inline",
        # 真身在 _execute_review_run_inline，外层只负责落库（2026-08-15）。
        # 契约要钉的是「inline 路径确实跑审查图」，所以两段源码合起来看；
        # 只看外层会把一层薄包装误判成「审查图没了」。
        source_for_callable(getattr(execution_module, "execute_review_run_inline", None))
        + source_for_callable(getattr(execution_module, "_execute_review_run_inline", None)),
        [
            "execute_review_graph",
            "graphRunner",
            "waiting_human_review",
            "graph_nodes_for_review_run",
            "findingDrafts",
            "outputHash",
        ],
    )
    require_source_terms(
        "run_step",
        source_for_callable(getattr(execution_module, "run_step", None)),
        [
            "run_rule_engine",
            "retrieve_knowledge",
            "schema_validation",
            "evidence_validation",
            "reference_validation",
            "quality_gate",
            "retrieval_traces",
            "rule_check_results",
        ],
    )
    require_source_terms(
        "generate_finding_drafts",
        source_for_callable(getattr(execution_module, "generate_finding_drafts", None)),
        [
            "qwen_runtime_client().chat_sync",
            "review-chat",
            "response_format",
            "call_qwen_runtime_chat",
            "stable_hash_payload",
            "normalize_llm_findings",
        ],
    )
    require_source_terms(
        "human_decision_for_review_run",
        source_for_callable(getattr(execution_module, "human_decision_for_review_run", None)),
        ["accepted_by_human", "edited_by_human", "rejected_by_human", "persist_confirmed_findings"],
    )
    require_source_terms(
        "graph_view_for_review_run",
        source_for_callable(getattr(execution_module, "graph_view_for_review_run", None)),
        ["artifactSummary", "artifacts", "ruleCheckResults", "retrievalTraces", "validationFailures"],
    )
    require_source_terms(
        "build_review_orchestration_scorecard",
        source_for_callable(getattr(readiness_module, "build_review_orchestration_scorecard", None)),
        ["workflow_section", "graph_section", "evidence_section", "governance_section", "targetScore", "blockers"],
    )
    require_source_terms(
        "fde_review_run_detail",
        source_for_callable(getattr(api_routes_module, "fde_review_run_detail", None)) if api_routes_module is not None else "",
        ["scorecard", "build_review_orchestration_scorecard", "temporal_history_summary", "graph_view_for_review_run"],
    )
    fde_console_source = ""
    try:
        fde_console_source = (REPO_ROOT / "frontend" / "src" / "views" / "AICheck" / "FdeConsole.vue").read_text(encoding="utf-8")
    except FileNotFoundError:
        source_failures.append("FDE ReviewRun artifact visualization source is missing")
    require_source_terms(
        "FDE ReviewRun artifact visualization",
        fde_console_source,
        [
            "reviewRuleResultRows",
            "reviewRetrievalTraceRows",
            "reviewFindingDraftRows",
            "ruleCheckResults",
            "retrievalTraces",
            "findingDrafts",
            "规则结果",
            "检索 Trace",
            "Finding Draft",
        ],
    )
    require_source_terms(
        "clone_review_run_for_replay",
        source_for_callable(getattr(execution_module, "clone_review_run_for_replay", None)),
        ["parentReviewRunId", "RRUN-REPLAY", "findingDrafts", "humanDecision", "seed_graph_nodes"],
    )
    require_source_terms(
        "dispatch_review_run",
        source_for_callable(getattr(dispatcher_module, "dispatch_review_run", None)),
        ["review_orchestration_mode", "create_review_run_from_ai_run", "dispatch_existing_review_run"],
    )
    require_source_terms(
        "dispatch_existing_review_run",
        source_for_callable(getattr(dispatcher_module, "dispatch_existing_review_run", None)),
        ["review_orchestration_mode", "execute_review_run_inline", "start_temporal_workflow", "REVIEW_ORCHESTRATION_DISABLED"],
    )
    require_source_terms(
        "start_temporal_workflow",
        source_for_callable(getattr(dispatcher_module, "start_temporal_workflow", None))
        + source_for_callable(getattr(dispatcher_module, "_start_temporal_workflow", None)),
        ["Client.connect", "start_workflow", "ReviewRunWorkflow", "workflowId", "task_queue", "TEMPORAL_START_FAILED"],
    )
    require_source_terms(
        "temporal signals",
        source_for_callable(getattr(dispatcher_module, "signal_review_run_human_decision", None))
        + source_for_callable(getattr(dispatcher_module, "signal_review_run_cancel", None))
        + source_for_callable(getattr(dispatcher_module, "_run_temporal_signal", None))
        + source_for_callable(getattr(dispatcher_module, "_signal_temporal_workflow", None)),
        ["submit_human_decision", "cancel_review", "get_workflow_handle", "handle.signal", "TEMPORAL_SIGNAL_FAILED"],
    )
    require_source_terms(
        "execute_review_graph",
        source_for_callable(getattr(graph_module, "execute_review_graph", None)),
        ["StateGraph", "START", "END", "thread_id", "graph.compile", "execute_manual_graph"],
    )
    require_source_terms(
        "langgraph_checkpointer_context",
        source_for_callable(getattr(graph_module, "langgraph_checkpointer_context", None)),
        ["LANGGRAPH_CHECKPOINT_DSN", "PostgresSaver", "from_conn_string", "postgres"],
    )
    worker_main_source = worker_main_source or source_for_callable(getattr(worker_main_module, "main", None))
    require_source_terms(
        "review worker main",
        worker_main_source,
        ["Client.connect", "Worker", "ReviewRunWorkflow", "run_review_graph_activity", "AICHECK_REVIEW_WORKFLOW_TASK_QUEUE"],
    )
    workflow_cls = getattr(workflow_module, "ReviewRunWorkflow", None) if workflow_module is not None else None
    workflow_source = workflow_source or source_for_callable(workflow_cls)
    require_source_terms(
        "ReviewRunWorkflow",
        workflow_source,
        [
            "workflow.defn",
            "workflow.run",
            "workflow.execute_activity",
            "workflow.wait_condition",
            "workflow.signal",
            "submit_human_decision",
            "cancel_review",
            "workflow.query",
        ],
    )
    activities_source = activities_source or source_for_callable(getattr(activities_module, "run_review_graph_activity", None))
    require_source_terms(
        "run_review_graph_activity",
        activities_source,
        ["activity.defn", "load_review_run_state", "execute_review_run_inline", "flush_state_records"],
    )

    failures = route_failures + graph_failures + state_failures + tool_failures + source_failures
    status = "pass" if not failures else "fail"
    return {
        "name": "review-orchestration.contract",
        "status": status,
        "detail": (
            "Temporal/LangGraph ReviewRun orchestration, routes, state, tools, and replay contracts are present."
            if status == "pass"
            else f"failures={len(failures)}"
        ),
        "data": {
            "routeFailures": route_failures,
            "graphFailures": graph_failures,
            "stateFailures": state_failures,
            "toolFailures": tool_failures,
            "sourceFailures": source_failures,
            "routeCount": len(route_summaries),
            "stepKeys": step_keys,
            "taskQueues": sorted(task_queues),
            "collections": sorted(collections),
            "allowedTools": sorted(allowed_tools),
            "forbiddenTools": sorted(forbidden_tools),
            "requiredRoutes": REQUIRED_REVIEW_RUN_ROUTES,
            "frontendArtifactVisualization": "reviewRuleResultRows" in fde_console_source,
        },
    }


def fde_governance_contract_check(
    *,
    fastapi_app: Any | None = None,
    api_routes_module: Any | None = None,
) -> dict[str, Any]:
    app_obj = fastapi_app or app
    routes_to_check = list(getattr(app_obj, "routes", []) or [])
    if api_routes_module is None:
        from apps.api import routes as api_routes_module
    if fastapi_app is None:
        routes_to_check.extend(getattr(api_routes_module.router, "routes", []) or [])

    route_failures: list[dict[str, Any]] = []
    route_summaries: list[dict[str, Any]] = []
    for required in REQUIRED_FDE_RELEASE_ROUTES:
        expected_method = str(required["method"])
        expected_suffix = str(required["suffix"])
        found = False
        for route in routes_to_check:
            route_path = str(getattr(route, "path", ""))
            route_methods = {str(method).upper() for method in (getattr(route, "methods", set()) or set())}
            if route_path.endswith(expected_suffix) and expected_method in route_methods:
                route_summaries.append({"method": expected_method, "path": route_path})
                found = True
                break
        if not found:
            route_failures.append({"method": expected_method, "suffix": expected_suffix})

    collection_failures: list[str] = []
    repository_collections = set(STATE_COLLECTIONS.values()) | set(SINGLETON_COLLECTIONS.values())
    missing_repository = sorted(REQUIRED_FDE_RELEASE_COLLECTIONS - repository_collections)
    if missing_repository:
        collection_failures.append("FDE release collections missing repository mapping: " + ", ".join(missing_repository))
    if "idx_aicheck_state_payload_gin" not in {item.get("name") for item in POSTGRES_INDEXES.get("aicheck_state", [])}:
        collection_failures.append("PostgreSQL JSONB payload GIN index is missing for FDE release collections")

    source_failures: list[str] = []

    def require_source_terms(label: str, source: str, terms: list[str]) -> None:
        missing = [term for term in terms if term not in source]
        if missing:
            source_failures.append(f"{label} missing source terms: " + ", ".join(missing))

    require_source_terms(
        "fde_release_gate_results",
        source_for_callable(getattr(api_routes_module, "fde_release_gate_results", None))
        + source_for_callable(getattr(api_routes_module, "fde_find_evaluation_report", None)),
        [
            "evaluation_report",
            "risk_set",
            "rollback_plan",
            "release_approval",
            "release_approvals",
            "riskLevel",
            "evaluationRunId",
            "status\") == \"passed\"",
            "评估报告未通过",
        ],
    )
    require_source_terms(
        "fde_create_release_plan",
        source_for_callable(getattr(api_routes_module, "fde_create_release_plan", None)),
        ["fde_release_gate_results", "blocked_by_gate", "blockingReasons", "capabilityBundleId"],
    )
    require_source_terms(
        "fde_submit_release_plan",
        source_for_callable(getattr(api_routes_module, "fde_submit_release_plan", None)),
        ["fde_release_gate_results", "blocked_by_gate", "submitted", "blockingReasons"],
    )
    require_source_terms(
        "fde_approve_release_plan",
        source_for_callable(getattr(api_routes_module, "fde_approve_release_plan", None)),
        ["role != \"admin\"", "FORBIDDEN", "release_approvals", "approvedByRole", "fde_release_gate_results"],
    )
    require_source_terms(
        "fde_start_shadow_release",
        source_for_callable(getattr(api_routes_module, "fde_start_shadow_release", None)),
        ["fde_release_gate_results", "blocked_by_gate", "shadow_running", "shadowSampleRate"],
    )
    require_source_terms(
        "fde_request_canary_release",
        source_for_callable(getattr(api_routes_module, "fde_request_canary_release", None)),
        ["fde_release_gate_results", "shadow_running", "shadow_passed", "blocked_by_gate", "canary_requested"],
    )
    try:
        from libs.business_pack import loader as business_pack_loader_module
        from libs.business_pack import readiness as business_pack_readiness_module
    except Exception as exc:  # pragma: no cover - defensive contract reporting
        source_failures.append(f"business pack portability source unavailable: {exc.__class__.__name__}")
        business_pack_scorecard_source = ""
        business_pack_loader_source = ""
    else:
        business_pack_scorecard_source = (
            source_for_callable(getattr(business_pack_readiness_module, "build_business_pack_portability_scorecard", None))
            + source_for_callable(getattr(business_pack_readiness_module, "pack_catalog_section", None))
            + source_for_callable(getattr(business_pack_readiness_module, "boundary_section", None))
            + source_for_callable(getattr(business_pack_readiness_module, "fixture_section", None))
            + source_for_callable(getattr(business_pack_readiness_module, "delivery_section", None))
        )
        business_pack_loader_source = source_for_callable(
            getattr(business_pack_loader_module, "validate_all_business_packs", None)
        )
    require_source_terms(
        "business pack portability scorecard",
        business_pack_scorecard_source,
        [
            "aicheck-business-pack-portability-scorecard-v1",
            "catalog",
            "core-boundary",
            "fixtures",
            "delivery",
            "projectMembers",
            "scan_core_boundary",
            "targetScore",
            "blockers",
        ],
    )
    require_source_terms(
        "validate_all_business_packs",
        business_pack_loader_source,
        ["scorecard", "build_business_pack_portability_scorecard"],
    )
    require_source_terms(
        "fde_validate_business_packs",
        source_for_callable(getattr(api_routes_module, "fde_validate_business_packs", None)),
        ["validate_all_business_packs", "fde:business-pack:validate"],
    )
    fde_console_source = ""
    try:
        fde_console_source = (REPO_ROOT / "frontend" / "src" / "views" / "AICheck" / "FdeConsole.vue").read_text(encoding="utf-8")
    except FileNotFoundError:
        source_failures.append("FDE business pack scorecard source is missing")
    require_source_terms(
        "FDE business pack scorecard UI",
        fde_console_source,
        ["packValidation.scorecard", "可迁移评分", "门禁分段", "可交付包", "阻断项"],
    )

    failures = route_failures + collection_failures + source_failures
    status = "pass" if not failures else "fail"
    return {
        "name": "fde.governance-contract",
        "status": status,
        "detail": (
            "FDE high-risk release gates require evaluation, risk set, rollback plan, non-FDE approval, shadow, and canary controls."
            if status == "pass"
            else f"failures={len(failures)}"
        ),
        "data": {
            "routeFailures": route_failures,
            "collectionFailures": collection_failures,
            "sourceFailures": source_failures,
            "routeCount": len(route_summaries),
            "requiredRoutes": REQUIRED_FDE_RELEASE_ROUTES,
            "requiredCollections": sorted(REQUIRED_FDE_RELEASE_COLLECTIONS),
            "businessPackPortabilityScorecard": "build_business_pack_portability_scorecard" in business_pack_scorecard_source,
            "frontendBusinessPackScorecard": "packValidation.scorecard" in fde_console_source,
        },
    }


def feedback_hr_contract_check(
    *,
    fastapi_app: Any | None = None,
    api_routes_module: Any | None = None,
    execution_module: Any | None = None,
) -> dict[str, Any]:
    app_obj = fastapi_app or app
    routes_to_check = list(getattr(app_obj, "routes", []) or [])
    if api_routes_module is None:
        from apps.api import routes as api_routes_module
    if execution_module is None:
        from libs.review_orchestrator import execution as execution_module
    if fastapi_app is None:
        routes_to_check.extend(getattr(api_routes_module.router, "routes", []) or [])

    route_failures: list[dict[str, Any]] = []
    route_summaries: list[dict[str, Any]] = []
    for required in REQUIRED_FEEDBACK_HR_ROUTES:
        expected_method = str(required["method"])
        expected_suffix = str(required["suffix"])
        found = False
        for route in routes_to_check:
            route_path = str(getattr(route, "path", ""))
            route_methods = {str(method).upper() for method in (getattr(route, "methods", set()) or set())}
            if route_path.endswith(expected_suffix) and expected_method in route_methods:
                route_summaries.append({"method": expected_method, "path": route_path})
                found = True
                break
        if not found:
            route_failures.append({"method": expected_method, "suffix": expected_suffix})

    collection_failures: list[str] = []
    repository_collections = set(STATE_COLLECTIONS.values()) | set(SINGLETON_COLLECTIONS.values())
    missing_repository = sorted(REQUIRED_FEEDBACK_HR_COLLECTIONS - repository_collections)
    if missing_repository:
        collection_failures.append("AI HR collections missing repository mapping: " + ", ".join(missing_repository))
    if "idempotency_records_pkey" not in {item.get("name") for item in POSTGRES_INDEXES.get("idempotency_records", [])}:
        collection_failures.append("idempotency_records primary key is missing for idempotent feedback promotion")

    source_failures: list[str] = []

    def require_source_terms(label: str, source: str, terms: list[str]) -> None:
        missing = [term for term in terms if term not in source]
        if missing:
            source_failures.append(f"{label} missing source terms: " + ", ".join(missing))

    require_source_terms(
        "human_decision_for_review_run",
        source_for_callable(getattr(execution_module, "human_decision_for_review_run", None)),
        ["record_human_feedback_for_review_run", "feedback"],
    )
    require_source_terms(
        "record_human_feedback_for_review_run",
        source_for_callable(getattr(execution_module, "record_human_feedback_for_review_run", None)),
        [
            "ai_feedback",
            "accepted",
            "edited",
            "rejected_false_positive",
            "originalAiOutput",
            "correctedOutput",
            "shouldEnterEvaluationSet",
            "inputDocumentVersionIds",
            "immutableSourceRun",
        ],
    )
    require_source_terms(
        "fde_triage_feedback",
        source_for_callable(getattr(api_routes_module, "fde_triage_feedback", None)),
        ["fde_upsert_evaluation_case_from_feedback", "fde_feedback_governance_view", "evaluationCase", "feedback_triage", "rootCause"],
    )
    require_source_terms(
        "fde_feedback_governance_view",
        source_for_callable(getattr(api_routes_module, "fde_feedback_governance_view", None)),
        [
            "governanceState",
            "evaluationCaseId",
            "evaluationSetId",
            "canUseForEval",
            "canUseForTraining",
            "adjudicationRequired",
            "sampleUsage",
            "promoted_to_eval",
            "needs_adjudication",
        ],
    )
    require_source_terms(
        "fde_upsert_evaluation_case_from_feedback",
        source_for_callable(getattr(api_routes_module, "fde_upsert_evaluation_case_from_feedback", None)),
        [
            "evaluation_cases",
            "sourceFeedbackId",
            "expectedFindings",
            "expectedEvidence",
            "approved_for_eval",
            "canUseForEval",
            "canUseForTraining",
        ],
    )
    require_source_terms(
        "fde_create_evaluation_run",
        source_for_callable(getattr(api_routes_module, "fde_create_evaluation_run", None)),
        [
            "LEGACY_NON_CERTIFYING_PROFILE",
            "PRODUCTION_CERTIFICATION_PROFILE",
            "fde_create_legacy_non_certifying_evaluation",
            "fde_create_production_certification_evaluation",
        ],
    )
    require_source_terms(
        "fde_create_legacy_non_certifying_evaluation",
        source_for_callable(getattr(api_routes_module, "fde_create_legacy_non_certifying_evaluation", None)),
        [
            "fde_build_evaluation_case_results",
            "fde_evaluation_case_summary",
            "caseResults",
            "caseSummary",
            "casePassRate",
            "findingRecall",
            "evidenceCoverage",
            "retrievalRecall",
            "wrongReferenceRate",
            "fde_persist_evaluation_result",
        ],
    )
    require_source_terms(
        "fde_persist_evaluation_result",
        source_for_callable(getattr(api_routes_module, "fde_persist_evaluation_result", None)),
        ["evaluation_case_results", "caseResults", "evaluation_metrics"],
    )
    require_source_terms(
        "fde_build_evaluation_case_results",
        source_for_callable(getattr(api_routes_module, "fde_build_evaluation_case_results", None)),
        [
            "fde_evaluate_retrieval_for_case",
            "retrievalPassed",
        ],
    )
    require_source_terms(
        "fde_evaluate_retrieval_for_case",
        source_for_callable(getattr(api_routes_module, "fde_evaluate_retrieval_for_case", None)),
        [
            "retrieve_knowledge_clauses",
            "fde_evaluation_retrieval",
            "expectedClauseIds",
            "retrievalTraceId",
            "selectedRoute",
            "missingClauseIds",
            "unexpectedTopClauseId",
        ],
    )
    fde_console_source = ""
    try:
        fde_console_source = (REPO_ROOT / "frontend" / "src" / "views" / "AICheck" / "FdeConsole.vue").read_text(encoding="utf-8")
    except FileNotFoundError:
        source_failures.append("FDE feedback governance visualization source is missing")
    require_source_terms(
        "FDE feedback governance visualization",
        fde_console_source,
        [
            "governanceState",
            "evaluationCaseId",
            "canUseForEval",
            "canUseForTraining",
            "adjudicationRequired",
            "评估样本",
            "入评估",
            "仲裁",
        ],
    )

    failures = route_failures + collection_failures + source_failures
    status = "pass" if not failures else "fail"
    return {
        "name": "feedback.hr-contract",
        "status": status,
        "detail": (
            "Human review decisions create immutable AI feedback and FDE triage can promote feedback into evaluation cases."
            if status == "pass"
            else f"failures={len(failures)}"
        ),
        "data": {
            "routeFailures": route_failures,
            "collectionFailures": collection_failures,
            "sourceFailures": source_failures,
            "routeCount": len(route_summaries),
            "requiredRoutes": REQUIRED_FEEDBACK_HR_ROUTES,
            "requiredCollections": sorted(REQUIRED_FEEDBACK_HR_COLLECTIONS),
            "frontendFeedbackGovernance": "governanceState" in fde_console_source,
        },
    }


def export_artifact_contract_check(
    *,
    builder: Any | None = None,
    repository_class: Any | None = None,
) -> dict[str, Any]:
    artifact_builder = builder or build_export_artifact
    repo_type = repository_class or InMemoryRepository
    failures: list[str] = []
    zip_details: dict[str, Any] = {}
    pdf_details: dict[str, Any] = {}

    try:
        repository = repo_type()
    except Exception as exc:
        repository = None
        failures.append(f"repository initialization failed: {exc.__class__.__name__}")

    task = {
        "id": "EXP-CONTRACT-001",
        "projectId": PROJECT_ID,
        "reportId": "RPT-20260625-001",
        "exportType": "archive-package",
        "fileName": "contract.zip",
    }

    try:
        zip_body = artifact_builder("contract.zip", task, "application/zip", repository)
    except Exception as exc:
        zip_body = b""
        failures.append(f"zip artifact build failed: {exc.__class__.__name__}")
    if not isinstance(zip_body, (bytes, bytearray)) or not zip_body:
        failures.append("zip artifact must return non-empty bytes")
        zip_body = b""
    else:
        import io
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(zip_body)) as archive:
                names = set(archive.namelist())
                missing_contents = sorted(REQUIRED_EXPORT_ZIP_CONTENTS - names)
                if missing_contents:
                    failures.append("zip artifact missing contents: " + ", ".join(missing_contents))
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                zip_details = {
                    "names": sorted(names),
                    "manifestSchema": manifest.get("schemaVersion"),
                    "manifestTaskId": manifest.get("taskId"),
                    "manifestProjectId": manifest.get("projectId"),
                    "manifestContents": manifest.get("contents"),
                }
                if manifest.get("schemaVersion") != "aicheck-export-v1":
                    failures.append("manifest.schemaVersion must be aicheck-export-v1")
                if manifest.get("taskId") != task["id"]:
                    failures.append("manifest.taskId must match export task id")
                if manifest.get("projectId") != PROJECT_ID:
                    failures.append("manifest.projectId must match task projectId")
                if not isinstance(manifest.get("counts"), dict):
                    failures.append("manifest.counts must be present")
                manifest_contents = set(manifest.get("contents") or [])
                missing_manifest_contents = sorted(REQUIRED_EXPORT_ZIP_CONTENTS - manifest_contents)
                if missing_manifest_contents:
                    failures.append("manifest.contents missing: " + ", ".join(missing_manifest_contents))
        except Exception as exc:
            failures.append(f"zip artifact is not a valid package: {exc.__class__.__name__}")

    pdf_task = {**task, "id": "EXP-CONTRACT-PDF", "fileName": "contract.pdf", "exportType": "report"}
    try:
        pdf_body = artifact_builder("contract.pdf", pdf_task, "application/pdf", repository)
    except Exception as exc:
        pdf_body = b""
        failures.append(f"pdf artifact build failed: {exc.__class__.__name__}")
    if not isinstance(pdf_body, (bytes, bytearray)) or not pdf_body:
        failures.append("pdf artifact must return non-empty bytes")
        pdf_body = b""
    else:
        pdf_details = {"size": len(pdf_body), "header": bytes(pdf_body[:8]).decode("ascii", errors="ignore")}
        if not bytes(pdf_body).startswith(b"%PDF-"):
            failures.append("pdf artifact must start with %PDF-")
        if b"AIcheck Export Report" not in bytes(pdf_body):
            failures.append("pdf artifact must contain AIcheck Export Report heading")

    status = "pass" if not failures else "fail"
    return {
        "name": "export.artifact-contract",
        "status": status,
        "detail": (
            "Export ZIP/PDF artifacts include manifest, audit snapshots, and PDF summary."
            if status == "pass"
            else f"failures={len(failures)}"
        ),
        "data": {
            "failures": failures,
            "requiredZipContents": sorted(REQUIRED_EXPORT_ZIP_CONTENTS),
            "zip": zip_details,
            "pdf": pdf_details,
        },
    }


def source_for_callable(item: Any) -> str:
    source_override = getattr(item, "__source__", None)
    if source_override is not None:
        return str(source_override)
    try:
        return inspect.getsource(item)
    except (OSError, TypeError):
        return ""


def worker_task_contract_check(
    *,
    task_routes: dict[str, Any] | None = None,
    tasks_module: Any | None = None,
    dispatcher_module: Any | None = None,
) -> dict[str, Any]:
    if task_routes is None:
        from apps.worker.celery_app import celery_app

        task_routes = dict(celery_app.conf.task_routes)
    if tasks_module is None:
        from apps.worker import tasks as tasks_module
    if dispatcher_module is None:
        from libs.integrations import task_dispatcher as dispatcher_module

    missing_tasks = []
    route_mismatches = []
    retry_missing = []
    dispatcher_missing = []
    dispatcher_mismatches = []
    for task_name, required in REQUIRED_WORKER_TASKS.items():
        task = getattr(tasks_module, task_name, None)
        full_name = f"apps.worker.tasks.{task_name}"
        if task is None:
            missing_tasks.append(task_name)
            route = task_routes.get(full_name)
        else:
            full_name = str(getattr(task, "name", full_name))
            route = task_routes.get(full_name)
            retry_kwargs = getattr(task, "retry_kwargs", {}) or {}
            task_source = source_for_callable(getattr(task, "run", task))
            manual_retry = ".retry(" in task_source and int(getattr(task, "max_retries", 0) or 0) >= 1
            if Exception not in tuple(getattr(task, "autoretry_for", ()) or ()) and not manual_retry:
                retry_missing.append({"task": task_name, "reason": "missing Exception autoretry"})
            if not getattr(task, "retry_backoff", False) and not manual_retry:
                retry_missing.append({"task": task_name, "reason": "missing retry_backoff"})
            if int(retry_kwargs.get("max_retries") or getattr(task, "max_retries", 0) or 0) < 1:
                retry_missing.append({"task": task_name, "reason": "missing max_retries"})
        expected_queue = str(required["queue"])
        actual_queue = route.get("queue") if isinstance(route, dict) else None
        if actual_queue != expected_queue:
            route_mismatches.append(
                {
                    "task": task_name,
                    "expectedQueue": expected_queue,
                    "actualQueue": actual_queue,
                }
            )
        dispatcher_name = required.get("dispatcher")
        if not dispatcher_name:
            continue
        dispatcher = getattr(dispatcher_module, str(dispatcher_name), None)
        if dispatcher is None:
            dispatcher_missing.append(str(dispatcher_name))
            continue
        source = source_for_callable(dispatcher)
        if "_dispatch_ocr_pipeline_stage" in source:
            source += source_for_callable(getattr(dispatcher_module, "_dispatch_ocr_pipeline_stage", None))
        requires_inline = task_name not in {
            "ocr_pipeline_structure_scan",
            "ocr_pipeline_seal_scan",
            "ocr_pipeline_evidence_fusion",
            "ocr_pipeline_official_extract",
            "ocr_pipeline_qwen_extract",
            "ocr_pipeline_finalize",
        }
        if (
            task_name not in source
            or not any(marker in source for marker in (".delay(", ".apply_async("))
            or (requires_inline and ".run(" not in source)
        ):
            dispatcher_mismatches.append(
                {
                    "dispatcher": str(dispatcher_name),
                    "task": task_name,
                    "reason": "dispatcher must expose inline .run and celery .delay paths",
                }
            )
    status = (
        "pass"
        if not missing_tasks
        and not route_mismatches
        and not retry_missing
        and not dispatcher_missing
        and not dispatcher_mismatches
        else "fail"
    )
    return {
        "name": "worker.task-contract",
        "status": status,
        "detail": (
            f"tasks={len(REQUIRED_WORKER_TASKS)}, missingTasks={len(missing_tasks)}, "
            f"routeMismatches={len(route_mismatches)}, retryMissing={len(retry_missing)}, "
            f"dispatcherMissing={len(dispatcher_missing)}, dispatcherMismatches={len(dispatcher_mismatches)}"
        ),
        "data": {
            "requiredQueues": {
                task_name: required["queue"] for task_name, required in REQUIRED_WORKER_TASKS.items()
            },
            "missingTasks": missing_tasks,
            "routeMismatches": route_mismatches,
            "retryMissing": retry_missing,
            "dispatcherMissing": dispatcher_missing,
            "dispatcherMismatches": dispatcher_mismatches,
        },
    }


def ocr_pipeline_hardening_contract_check() -> dict[str, Any]:
    tasks_source = (BACKEND_ROOT / "apps/worker/tasks.py").read_text(encoding="utf-8")
    service_source = (BACKEND_ROOT / "apps/ocr_service/service.py").read_text(encoding="utf-8")
    prior_source = (BACKEND_ROOT / "libs/document_ai_shadow.py").read_text(encoding="utf-8")
    dispatcher_source = (BACKEND_ROOT / "libs/integrations/task_dispatcher.py").read_text(encoding="utf-8")
    compose_source = (BACKEND_ROOT / "docker-compose.accuracy-pipeline.yml").read_text(encoding="utf-8")
    validation_compose = (BACKEND_ROOT / "docker-compose.ocr-validation.yml").read_text(encoding="utf-8")
    required = {
        "real structure task": "def ocr_pipeline_structure_scan" in tasks_source,
        "real seal task": "def ocr_pipeline_seal_scan" in tasks_source,
        "stage engine allowlist": '"engineAllowlist"' in tasks_source and "engine_allowlist" in service_source,
        "fast-first explicitly disabled": '"disableFastFirst": True' in tasks_source,
        "heavy engine execution required": "_engine_not_executed" in tasks_source,
        "tesseract fallback-only": "tesseract_fallback_satisfied" in service_source,
        "evidence prior v3": 'EVIDENCE_PRIOR_VERSION = "EvidencePrior@3"' in prior_source,
        "strict table attribution": "_candidate_matches_table_context" in prior_source,
        "pipeline advisory locks": "@pipeline_task_lock" in tasks_source,
        "deterministic task ids": "deterministic_task_id" in dispatcher_source,
        "model attempt ledger": "model_call_attempts" in tasks_source,
        "host OCR cache bind": "/data/aicheck/ocr-cache" in compose_source,
        "disk capacity gate": "AICHECK_DISK_PAUSE_PERCENT" in compose_source,
        "isolated validation postgres": "postgres-ocr-validation" in validation_compose,
        "isolated validation redis": "redis-ocr-validation" in validation_compose,
        "isolated validation minio": "minio-ocr-validation" in validation_compose,
        "fault proxies": "ocr-fault-proxy" in validation_compose and "qwen-fault-proxy" in validation_compose,
    }
    failures = sorted(label for label, passed in required.items() if not passed)
    return {
        "name": "ocr.pipeline-hardening-contract",
        "status": "pass" if not failures else "fail",
        "detail": f"checks={len(required)}, failures={len(failures)}",
        "data": {"checks": required, "failures": failures},
    }


def role_contract_check(
    *,
    role_default_paths: dict[str, str] | None = None,
    role_actions: dict[str, list[str]] | None = None,
    role_specs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    paths = role_default_paths if role_default_paths is not None else ROLE_DEFAULT_PATHS
    actions = role_actions if role_actions is not None else ROLE_ACTIONS
    specs = role_specs if role_specs is not None else ROLE_SPECS
    missing_roles = []
    bad_paths = []
    missing_actions = []
    owner_write_leaks = []
    missing_specs = []
    for role in PRODUCTION_ROLES:
        if role not in paths or role not in actions:
            missing_roles.append(role)
            continue
        if role == "inspection":
            expected_path = "/ai-review-b"
        elif role == "admin":
            expected_path = "/admin/overview"
        elif role == "fde":
            # cc2600f 重构治理台后 FDE 落地页改为治理总览；前端路由、登录跳转
            # (libs/security/auth.py) 和菜单三处一致，此处的期望值当时漏了同步。
            expected_path = "/fde/dashboard"
        else:
            expected_path = f"/workbench/{role}"
        if paths.get(role) != expected_path:
            bad_paths.append({"role": role, "expected": expected_path, "actual": paths.get(role)})
        required_actions = ROLE_REQUIRED_ACTIONS[role]
        role_action_set = set(actions.get(role) or [])
        missing = sorted(required_actions - role_action_set)
        if missing:
            missing_actions.append({"role": role, "missing": missing})
        if role == "owner":
            leaked = sorted(OWNER_FORBIDDEN_WRITE_ACTIONS & role_action_set)
            if leaked:
                owner_write_leaks.append({"role": role, "actions": leaked})
        spec = specs.get(role)
        if not spec:
            missing_specs.append(role)
            continue
        if spec.get("username") != role:
            missing_specs.append(role)
        if not spec.get("userId") or not spec.get("orgId"):
            missing_specs.append(role)
        if not spec.get("platformOnly") and not spec.get("nodeScope"):
            missing_specs.append(role)
        if bool(spec.get("readonly")) != (role == "owner"):
            missing_specs.append(role)
    plan_failures = []
    try:
        strong_passwords = ROLE_CONTRACT_TEST_PASSWORDS
        validate_strong_passwords(list(PRODUCTION_ROLES), strong_passwords)
        plan = build_plan(list(PRODUCTION_ROLES), PROJECT_ID, passwords=strong_passwords, show_passwords=False)
    except Exception as exc:
        plan = {}
        plan_failures.append(f"build_plan failed: {exc}")
    auth_users = plan.get("authUsers", []) if isinstance(plan, dict) else []
    project_members = plan.get("projectMembers", []) if isinstance(plan, dict) else []
    login_accounts = plan.get("loginAccounts", []) if isinstance(plan, dict) else []
    project_member_roles = [role for role in PRODUCTION_ROLES if not specs.get(role, {}).get("platformOnly")]
    if len(auth_users) != len(PRODUCTION_ROLES):
        plan_failures.append("authUsers must cover all production roles")
    if len(project_members) != len(project_member_roles):
        plan_failures.append("projectMembers must cover all project-scoped production roles")
    if len(login_accounts) != len(PRODUCTION_ROLES):
        plan_failures.append("loginAccounts must cover all production roles")
    for user in auth_users:
        role = str(user.get("role"))
        password_hash = str(user.get("passwordHash") or "")
        if not password_hash.startswith("pbkdf2_sha256$"):
            plan_failures.append(f"{role} passwordHash must use pbkdf2_sha256")
        if not verify_password(str(strong_passwords.get(role)), password_hash):
            plan_failures.append(f"{role} passwordHash must verify supplied password")
        if user.get("defaultPath") != paths.get(role):
            plan_failures.append(f"{role} auth user defaultPath mismatch")
    status = (
        "pass"
        if not missing_roles
        and not bad_paths
        and not missing_actions
        and not owner_write_leaks
        and not missing_specs
        and not plan_failures
        else "fail"
    )
    return {
        "name": "auth.role-contract",
        "status": status,
        "detail": (
            f"roles={len(PRODUCTION_ROLES)}, missingRoles={len(missing_roles)}, badPaths={len(bad_paths)}, "
            f"missingActions={len(missing_actions)}, ownerWriteLeaks={len(owner_write_leaks)}, "
            f"specFailures={len(missing_specs)}, planFailures={len(plan_failures)}"
        ),
        "data": {
            "roles": list(PRODUCTION_ROLES),
            "missingRoles": sorted(set(missing_roles)),
            "badPaths": bad_paths,
            "missingActions": missing_actions,
            "ownerWriteLeaks": owner_write_leaks,
            "missingSpecs": sorted(set(missing_specs)),
            "planFailures": plan_failures,
        },
    }


def auth_security_contract_check() -> dict[str, Any]:
    auth_source = (BACKEND_ROOT / "libs/security/auth.py").read_text(encoding="utf-8")
    main_source = (BACKEND_ROOT / "apps/api/main.py").read_text(encoding="utf-8")
    compose_source = (BACKEND_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    route_source = (BACKEND_ROOT / "apps/api/routes.py").read_text(encoding="utf-8")
    required = {
        "dev token gated": "if not dev_tokens_allowed()" in auth_source,
        "jwt version claim": '"ver": user_auth_version' in auth_source,
        "jwt issuer": '"iss": jwt_issuer()' in auth_source,
        "jwt audience": '"aud": jwt_audience()' in auth_source,
        "canonical server role": 'claims.get("role") != user_record.get("role")' in main_source,
        "password change gate": "PASSWORD_CHANGE_REQUIRED" in main_source,
        "mock route conditional": "if compatibility_mocks_enabled():" in main_source,
        "mock users redacted": "users = [public_user(user)" in route_source,
        "cors allowlist": "allow_origins=cors_allowed_origins()" in main_source,
        "cors credentials disabled": "allow_credentials=False" in main_source,
        "strict production compose": "AICHECK_STRICT_PRODUCTION: ${AICHECK_STRICT_PRODUCTION:-true}" in compose_source,
        "production dev tokens disabled": "AICHECK_ALLOW_DEV_TOKENS: ${AICHECK_ALLOW_DEV_TOKENS:-false}" in compose_source,
        "production mocks disabled": "AICHECK_ENABLE_COMPATIBILITY_MOCKS: ${AICHECK_ENABLE_COMPATIBILITY_MOCKS:-false}" in compose_source,
        "litellm digest pinned": bool(re.search(r"ghcr\.io/berriai/litellm:[^}\s]+@sha256:[a-f0-9]{64}", compose_source)),
    }
    failures = sorted(label for label, passed in required.items() if not passed)
    return {
        "name": "auth.security-contract",
        "status": "pass" if not failures else "fail",
        "detail": f"checks={len(required)}, failures={len(failures)}",
        "data": {"checks": required, "failures": failures},
    }


def release_gate_contract_section(args: argparse.Namespace) -> dict[str, Any]:
    required_flags = {
        "strictProduction": bool(getattr(args, "strict_production", False)),
        "includeLive": bool(getattr(args, "include_live", False)),
        "writeProbes": bool(getattr(args, "write_probes", False)),
        "ocrEnabled": not bool(getattr(args, "skip_ocr", False)),
        "ocrObjectProbe": bool(getattr(args, "ocr_object_probe", False)),
        "reviewRunProbe": bool(getattr(args, "review_run_probe", False)),
        "litellmEnabled": not bool(getattr(args, "skip_litellm", False)),
        "litellmManagementProbes": bool(getattr(args, "litellm_management_probes", False)),
        "litellmProviderProbes": bool(getattr(args, "litellm_provider_probes", False)),
        "qwenOfficialProbe": bool(getattr(args, "qwen_official_probe", False)),
        "securityScanEvidence": bool(getattr(args, "security_scan_dir", None)),
        "ocr98GateEvidence": bool(getattr(args, "ocr_98_gate_report", None)),
        "httpsEndpoint": str(getattr(args, "api_base", "")).strip().lower().startswith("https://"),
    }
    failures = sorted(label for label, enabled in required_flags.items() if not enabled)
    check = {
        "name": "release.required-probes",
        "status": "pass" if not failures else "fail",
        "detail": f"required={len(required_flags)}, missing={len(failures)}",
        "data": {"flags": required_flags, "missing": failures},
    }
    scan_dir = getattr(args, "security_scan_dir", None)
    if scan_dir:
        security_report = validate_scan_directory(Path(scan_dir))
        security_check = {
            "name": "release.security-scans",
            "status": security_report["status"],
            "detail": f"services={len(security_report['services'])}, failures={len(security_report['failures'])}",
            "data": security_report,
        }
    else:
        security_check = {
            "name": "release.security-scans",
            "status": "fail",
            "detail": "Pass --security-scan-dir with current SBOM and vulnerability scan evidence.",
            "data": {"failures": ["security scan evidence is required"]},
        }
    ocr_98_path = getattr(args, "ocr_98_gate_report", None)
    if ocr_98_path:
        try:
            ocr_98_report = json.loads(Path(ocr_98_path).read_text(encoding="utf-8"))
            ocr_98_passed = isinstance(ocr_98_report, dict) and ocr_98_report.get("ok") is True
            ocr_98_check = {
                "name": "release.ocr-98-gate",
                "status": "pass" if ocr_98_passed else "fail",
                "detail": "OCR/audit 98+ evidence passed." if ocr_98_passed else "OCR/audit 98+ evidence is not passing.",
                "data": ocr_98_report,
            }
        except (OSError, json.JSONDecodeError) as exc:
            ocr_98_check = {
                "name": "release.ocr-98-gate",
                "status": "fail",
                "detail": f"Invalid OCR/audit 98+ evidence: {exc}",
                "data": None,
            }
    else:
        ocr_98_check = {
            "name": "release.ocr-98-gate",
            "status": "fail",
            "detail": "Pass --ocr-98-gate-report with current passing evidence.",
            "data": None,
        }
    return {
        "name": "release-gate",
        "ok": not failures and security_check["status"] == "pass" and ocr_98_check["status"] == "pass",
        "checks": [check, security_check, ocr_98_check],
    }


def iter_effective_routes(route_source: Any | None = None):
    for route in (route_source if route_source is not None else app.routes):
        route_contexts = getattr(route, "effective_route_contexts", None)
        if callable(route_contexts):
            yield from route_contexts()
            continue
        yield route


def backend_action_coverage_check(route_source: Any | None = None) -> dict[str, Any]:
    covered = []
    missing = []
    exempt = []
    for route in iter_effective_routes(route_source):
        path = str(getattr(route, "path", ""))
        methods = set(getattr(route, "methods", set()) or set()) & MUTATING_METHODS
        for method in sorted(methods):
            key = (method, path)
            if key in PUBLIC_MUTATION_ROUTES:
                exempt.append({"method": method, "path": path, "category": "public"})
                continue
            if key in READ_ONLY_POST_ROUTES:
                exempt.append({"method": method, "path": path, "category": "read-only-post"})
                continue
            action = required_action_for_request(method, path)
            item = {"method": method, "path": path, "action": action}
            if action:
                covered.append(item)
            else:
                missing.append(item)
    status = "pass" if not missing else "fail"
    return {
        "name": "api.action-coverage",
        "status": status,
        "detail": f"mutatingRoutes={len(covered) + len(missing) + len(exempt)}, covered={len(covered)}, missing={len(missing)}, exempt={len(exempt)}",
        "data": {
            "missing": missing,
            "covered": covered,
            "exempt": exempt,
        },
    }


def response_envelope_contract_check(ok_func: Any | None = None, fail_func: Any | None = None) -> dict[str, Any]:
    ok_callable = ok_func or ok
    fail_callable = fail_func or fail
    failures: list[str] = []
    try:
        success = ok_callable({"probe": True})
    except Exception as exc:
        success = {}
        failures.append(f"ok() raised {exc.__class__.__name__}")
    if not isinstance(success, dict):
        failures.append("ok() must return a dict envelope")
        success = {}
    if success.get("code") != 0:
        failures.append("ok.code must be 0")
    if "data" not in success:
        failures.append("ok.data is required")
    for field in ["operationId", "serverTime"]:
        if not isinstance(success.get(field), str) or not success.get(field):
            failures.append(f"ok.{field} must be a non-empty string")
    if "ok" in success:
        failures.append("legacy ok field must not be present")

    try:
        error_response = fail_callable(errors.FORBIDDEN)
        error_payload = json.loads(error_response.body.decode("utf-8"))
        status_code = int(error_response.status_code)
    except Exception as exc:
        error_payload = {}
        status_code = 0
        failures.append(f"fail() raised {exc.__class__.__name__}")
    if status_code != 200:
        failures.append("fail() default HTTP status must be 200")
    if not isinstance(error_payload, dict):
        failures.append("fail() must return a JSON object envelope")
        error_payload = {}
    if error_payload.get("code") == 0 or not isinstance(error_payload.get("code"), int):
        failures.append("fail.code must be a non-zero integer")
    if not isinstance(error_payload.get("message"), str) or not error_payload.get("message"):
        failures.append("fail.message must be a non-empty string")
    data = error_payload.get("data")
    if not isinstance(data, dict) or data.get("reason") != errors.FORBIDDEN.reason:
        failures.append("fail.data.reason must contain the business error reason")
    for field in ["operationId", "serverTime"]:
        if not isinstance(error_payload.get(field), str) or not error_payload.get(field):
            failures.append(f"fail.{field} must be a non-empty string")
    if "ok" in error_payload:
        failures.append("legacy fail ok field must not be present")

    status = "pass" if not failures else "fail"
    return {
        "name": "api.response-envelope",
        "status": status,
        "detail": "ok()/fail() response envelope matches frontend contract." if not failures else "; ".join(failures),
        "data": {
            "failures": failures,
            "successFields": sorted(success),
            "errorFields": sorted(error_payload),
        },
    }


def called_function_names(source: str) -> set[str]:
    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


_TRUSTED_DELEGATE_MODULE_PREFIXES = ("apps.api", "libs")
_MAX_DELEGATE_CALL_DEPTH = 8
_MAX_DELEGATE_CALLABLES = 64


def resolved_handler_callables(source: str, globals_map: dict[str, Any]) -> list[Any]:
    """Resolve direct call targets from a handler's own globals without name matching."""
    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError:
        return []

    def resolve(expression: ast.expr) -> Any | None:
        if isinstance(expression, ast.Name):
            return globals_map.get(expression.id)
        if isinstance(expression, ast.Attribute):
            owner = resolve(expression.value)
            if isinstance(owner, ModuleType):
                return getattr(owner, expression.attr, None)
        return None

    return [
        candidate
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (candidate := resolve(node.func)) is not None
    ]


def is_trusted_project_callable(candidate: Any) -> bool:
    module_name = getattr(candidate, "__module__", "")
    return bool(
        callable(candidate)
        and isinstance(module_name, str)
        and any(module_name == prefix or module_name.startswith(f"{prefix}.") for prefix in _TRUSTED_DELEGATE_MODULE_PREFIXES)
    )


def calls_trusted_idempotent_delegate(endpoint: Any, source: str) -> bool:
    """Boundedly follow trusted project-local helpers resolved from real globals.

    The analyzer follows callable objects, not terminal AST spellings. Only
    `apps.api` and `libs` callables may extend the graph; arbitrary imports,
    same-named functions, cycles, and unexpectedly deep graphs fail closed.
    """
    globals_map = getattr(endpoint, "__globals__", None)
    if not isinstance(globals_map, dict):
        return False

    visited: set[int] = {id(endpoint)}

    def helper_calls_idempotent(candidate: Any, depth: int) -> bool:
        if (
            depth > _MAX_DELEGATE_CALL_DEPTH
            or len(visited) >= _MAX_DELEGATE_CALLABLES
            or not is_trusted_project_callable(candidate)
            or id(candidate) in visited
        ):
            return False
        visited.add(id(candidate))
        candidate_source = source_for_callable(candidate)
        if "idempotent" in called_function_names(candidate_source):
            return True
        candidate_globals = getattr(candidate, "__globals__", None)
        if not isinstance(candidate_globals, dict):
            return False
        return any(
            helper_calls_idempotent(next_candidate, depth + 1)
            for next_candidate in resolved_handler_callables(candidate_source, candidate_globals)
        )

    return any(
        helper_calls_idempotent(candidate, 1)
        for candidate in resolved_handler_callables(source, globals_map)
    )


def backend_mutation_idempotency_check(route_source: Any | None = None) -> dict[str, Any]:
    routes: list[dict[str, Any]] = []
    for route in iter_effective_routes(route_source):
        path = str(getattr(route, "path", ""))
        methods = set(getattr(route, "methods", set()) or set()) & MUTATING_METHODS
        if not methods:
            continue
        endpoint = getattr(route, "endpoint", None)
        source_override = getattr(endpoint, "__source__", None)
        if source_override is not None:
            source = str(source_override)
        else:
            try:
                source = inspect.getsource(endpoint) if endpoint is not None else ""
            except (OSError, TypeError):
                source = ""
        called_names = called_function_names(source)
        for method in sorted(methods):
            key = (method, path)
            if key in PUBLIC_MUTATION_ROUTES:
                category = "public"
            elif key in READ_ONLY_POST_ROUTES:
                category = "read-only-post"
            elif "idempotent" in called_names:
                category = "direct"
            elif calls_trusted_idempotent_delegate(endpoint, source):
                category = "delegated"
            else:
                category = "missing"
            routes.append(
                {
                    "method": method,
                    "path": path,
                    "endpoint": getattr(endpoint, "__name__", ""),
                    "category": category,
                }
            )
    missing = [route for route in routes if route["category"] == "missing"]
    direct = [route for route in routes if route["category"] == "direct"]
    delegated = [route for route in routes if route["category"] == "delegated"]
    exempt = [route for route in routes if route["category"] in {"public", "read-only-post"}]
    status = "pass" if not missing else "fail"
    return {
        "name": "api.mutation-idempotency",
        "status": status,
        "detail": (
            f"mutatingRoutes={len(routes)}, missing={len(missing)}, "
            f"direct={len(direct)}, delegated={len(delegated)}, exempt={len(exempt)}"
        ),
        "data": {
            "missing": missing,
            "direct": direct,
            "delegated": delegated,
            "exempt": exempt,
        },
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# AIcheck Deployment Acceptance Report",
        "",
        f"- Generated at: {report['generatedAt']}",
        f"- Strict production: {report['strictProduction']}",
        f"- Live probes: {report['includeLive']}",
        f"- Overall: {'PASS' if report['ok'] else 'FAIL'}",
        "",
        "| Section | Check | Status | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for section in report["sections"]:
        for check in section.get("checks", []):
            lines.append(
                "| {section} | {name} | {status} | {detail} |".format(
                    section=section["name"],
                    name=check.get("name", ""),
                    status=str(check.get("status", "")).upper(),
                    detail=str(check.get("detail") or "").replace("|", "\\|"),
                )
            )
    lines.append("")
    summary = report["summary"]
    lines.append(
        f"Summary: total={summary['total']}, pass={summary['pass']}, warn={summary['warn']}, fail={summary['fail']}, skip={summary['skip']}."
    )
    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any], output_dir: str | None) -> None:
    if not output_dir:
        return
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "report.md").write_text(markdown_report(report), encoding="utf-8")


def main() -> int:
    args = parse_args()
    report = DeploymentReportBuilder(args).build()
    write_outputs(report, args.output_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(markdown_report(report), end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
