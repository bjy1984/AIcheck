from __future__ import annotations

import argparse
import ast
import inspect
import json
import os
import re
import sys
import textwrap
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libs.contracts.responses import SERVER_TZ
from libs.db.seed import PROJECT_ID
from libs.security.actions import MUTATING_METHODS, required_action_for_request
from apps.api.main import app
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.indexes import MONGO_INDEXES
from libs.db.repository import (
    IDEMPOTENCY_COLLECTION,
    InMemoryRepository,
    SINGLETON_COLLECTIONS,
    STATE_COLLECTIONS,
    build_export_artifact,
)
from libs.db.seed import ROLE_ACTIONS
from libs.integrations.litellm_client import LiteLLMClient
from libs.integrations.storage import DEFAULT_BUCKETS, ObjectStorage, parse_storage_url
from libs.security.auth import ROLE_DEFAULT_PATHS, verify_password
from scripts.audit_frontend_contract import audit
from scripts.create_roles import ROLE_SPECS, build_plan, validate_strong_passwords
from scripts.validate_deployment_config import DeploymentConfigValidator
from scripts.verify_deployment import DEFAULT_ROLES, DeploymentVerifier, VerifyConfig


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
MUTATION_HEADER_EXEMPT_URLS = {
    "/api/admin/config-diff/preview",
    "/api/business-packs/${packId}/validate",
    "/api/business-packs/{pack_id}/validate",
    "/api/business-packs/validate-all",
    "/api/fde/business-packs/validate-all",
    "/api/knowledge/retrieval-test",
}
PUBLIC_MUTATION_ROUTES = {
    ("POST", "/mock/user/login"),
    ("POST", "/api/mock/user/login"),
    ("POST", "/auth/login"),
    ("POST", "/api/auth/login"),
    ("POST", "/auth/logout"),
    ("POST", "/api/auth/logout"),
}
READ_ONLY_POST_ROUTES = {
    ("POST", "/business-packs/{pack_id}/validate"),
    ("POST", "/api/business-packs/{pack_id}/validate"),
    ("POST", "/business-packs/validate-all"),
    ("POST", "/api/business-packs/validate-all"),
    ("POST", "/fde/business-packs/validate-all"),
    ("POST", "/api/fde/business-packs/validate-all"),
    ("POST", "/knowledge/retrieval-test"),
    ("POST", "/api/knowledge/retrieval-test"),
    ("POST", "/admin/config-diff/preview"),
    ("POST", "/api/admin/config-diff/preview"),
}
IDEMPOTENT_DELEGATE_CALLS = {
    "admin_generic_create",
    "admin_generic_update",
    "bind_documents",
    "create_admin_project",
    "create_upload_session",
    "update_knowledge_source",
}
REQUIRED_WORKER_TASKS = {
    "parse_document": {
        "queue": "ocr.parse_document",
        "dispatcher": "dispatch_parse_document",
    },
    "recognize_seals": {
        "queue": "ocr.recognize_seals",
        "dispatcher": None,
    },
    "slice_knowledge": {
        "queue": "knowledge.slice",
        "dispatcher": "dispatch_slice",
    },
    "embed_knowledge": {
        "queue": "knowledge.embed",
        "dispatcher": "dispatch_embed",
    },
    "ai_recheck": {
        "queue": "inspection.ai_recheck",
        "dispatcher": "dispatch_ai_recheck",
    },
    "llm_compare": {
        "queue": "llm.compare",
        "dispatcher": "dispatch_llm_compare",
    },
    "export_package": {
        "queue": "export.package",
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
    "todos",
    "messages",
    "audit_logs",
    "admin_configs",
}
CRITICAL_MONGO_INDEXES = [
    {"collection": "project_nodes", "fields": ["projectId", "nodeId", "status"]},
    {"collection": "documents", "fields": ["projectId", "nodeId", "status"]},
    {"collection": "document_versions", "fields": ["documentId", "id"]},
    {"collection": "knowledge_tasks", "fields": ["taskType", "status", "targetType", "targetId"]},
    {"collection": "evidence_links", "fields": ["targetType", "targetId"]},
    {"collection": "audit_logs", "fields": ["createdAt", "objectType", "objectId"]},
    {"collection": IDEMPOTENCY_COLLECTION, "fields": ["scope"], "unique": True},
    {"collection": "project_members", "fields": ["projectId", "userId", "role"], "unique": True},
]
REQUIRED_STORAGE_BUCKETS = ("documents", "previews", "exports", "ocr-artifacts")
REQUIRED_STORAGE_METHODS = {
    "ensure_buckets": {
        "params": [],
        "source": ["DEFAULT_BUCKETS", "bucket_exists", "make_bucket"],
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
REQUIRED_OCR_HEALTH_FIELDS = {"service", "pipelineAvailable", "pipelineBackend", "placeholderAllowed"}
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
    "embed_knowledge": ["LiteLLMClient().embed_sync", "embedding-default", "EXTERNAL_TOOL_FAILED"],
    "ai_recheck": ["LiteLLMClient().chat_sync", "review-chat", "AI_RUN_FAILED", "first_message_text"],
    "llm_compare": ["LiteLLMClient().chat_sync", "default-chat", "compare-fast", "EXTERNAL_TOOL_FAILED"],
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
    parser.add_argument("--litellm-api-key", default=os.getenv("LITELLM_API_KEY", ""))
    parser.add_argument("--project-id", default=PROJECT_ID)
    parser.add_argument("--roles", default=",".join(DEFAULT_ROLES))
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--skip-litellm", action="store_true")
    parser.add_argument("--write-probes", action="store_true")
    parser.add_argument("--ocr-object-probe", action="store_true")
    parser.add_argument("--litellm-management-probes", action="store_true")
    parser.add_argument("--litellm-provider-probes", action="store_true")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--output-dir", help="Optional directory for report.json and report.md.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    return parser.parse_args()


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
            self.export_artifact_contract_section(),
            self.worker_contract_section(),
            self.api_contract_section(),
            self.frontend_contract_section(),
        ]
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
        check = mongo_index_contract_check()
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

    def export_artifact_contract_section(self) -> dict[str, Any]:
        check = export_artifact_contract_check()
        return {
            "name": "export-artifact-contract",
            "ok": check["status"] == "pass",
            "checks": [check],
        }

    def auth_contract_section(self) -> dict[str, Any]:
        check = role_contract_check()
        return {
            "name": "auth-contract",
            "ok": check["status"] == "pass",
            "checks": [check],
        }

    def worker_contract_section(self) -> dict[str, Any]:
        check = worker_task_contract_check()
        return {
            "name": "worker-contract",
            "ok": check["status"] == "pass",
            "checks": [check],
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

    def live_section(self) -> dict[str, Any]:
        roles = [item.strip() for item in str(self.args.roles).split(",") if item.strip()]
        config = VerifyConfig(
            api_base=str(self.args.api_base).rstrip("/"),
            ocr_base=None if self.args.skip_ocr else str(self.args.ocr_base).rstrip("/"),
            litellm_base=None if self.args.skip_litellm else str(self.args.litellm_base).rstrip("/"),
            litellm_api_key=str(self.args.litellm_api_key or ""),
            project_id=str(self.args.project_id),
            roles=roles,
            strict_production=bool(self.args.strict_production),
            skip_ocr=bool(self.args.skip_ocr),
            skip_litellm=bool(self.args.skip_litellm),
            write_probes=bool(self.args.write_probes),
            ocr_object_probe=bool(self.args.ocr_object_probe),
            litellm_management_probes=bool(self.args.litellm_management_probes),
            litellm_provider_probes=bool(self.args.litellm_provider_probes),
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
            finally:
                storage_client.close()
                if ocr_client:
                    ocr_client.close()
                if litellm_client:
                    litellm_client.close()
        return {
            "name": "live-deployment",
            "ok": all(item.ok or item.status == "skip" for item in results),
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


def normalized_mongo_indexes(indexes: dict[str, list[Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    source = indexes if indexes is not None else MONGO_INDEXES
    return {
        collection: [normalize_index_spec(spec) for spec in specs]
        for collection, specs in source.items()
    }


def mongo_index_contract_check(indexes: dict[str, list[Any]] | None = None) -> dict[str, Any]:
    normalized = normalized_mongo_indexes(indexes)
    indexed_collections = set(normalized)
    persisted_collections = (
        set(STATE_COLLECTIONS.values()) | set(SINGLETON_COLLECTIONS.values()) | {IDEMPOTENCY_COLLECTION}
    )
    missing_persisted = sorted(persisted_collections - indexed_collections)
    missing_plan_collections = sorted(REQUIRED_PLAN_COLLECTIONS - indexed_collections)
    missing_critical = []
    for required in CRITICAL_MONGO_INDEXES:
        collection_indexes = normalized.get(str(required["collection"]), [])
        fields = list(required["fields"])
        unique = bool(required.get("unique", False))
        found = any(
            item["fields"][: len(fields)] == fields and (not unique or item["unique"])
            for item in collection_indexes
        )
        if not found:
            missing_critical.append(required)
    status = "pass" if not missing_persisted and not missing_plan_collections and not missing_critical else "fail"
    return {
        "name": "mongo.index-contract",
        "status": status,
        "detail": (
            f"collections={len(indexed_collections)}, persistedMissing={len(missing_persisted)}, "
            f"planMissing={len(missing_plan_collections)}, criticalMissing={len(missing_critical)}"
        ),
        "data": {
            "indexedCollections": sorted(indexed_collections),
            "persistedCollections": sorted(persisted_collections),
            "missingPersisted": missing_persisted,
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
    missing_health_fields = sorted(field for field in REQUIRED_OCR_HEALTH_FIELDS if field not in health_source)
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
) -> dict[str, Any]:
    if evaluation_module is None:
        from apps.ocr_service import evaluation as evaluation_module

    cli = cli_path or BACKEND_ROOT / "scripts" / "ocr_eval_set.py"
    fixture = fixture_path or BACKEND_ROOT / "ocr_eval" / "piping_release_set.json"
    failures: list[str] = []
    data: dict[str, Any] = {
        "requiredMetrics": sorted(REQUIRED_OCR_EVALUATION_METRICS),
        "metricFailures": [],
        "cliFailures": [],
        "fixtureFailures": [],
    }

    evaluate_cases = getattr(evaluation_module, "evaluate_cases", None)
    compact_evaluation_report = getattr(evaluation_module, "compact_evaluation_report", None)
    if not callable(evaluate_cases):
        failures.append("apps.ocr_service.evaluation.evaluate_cases is missing")
        data["metricFailures"].append("evaluate_cases missing")
    if not callable(compact_evaluation_report):
        failures.append("apps.ocr_service.evaluation.compact_evaluation_report is missing")
        data["metricFailures"].append("compact_evaluation_report missing")
    else:
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
            "--min-average-score",
            "--output",
            "--summary-output",
            "--markdown-output",
        ]:
            if term not in cli_source:
                failures.append(f"OCR evaluation CLI missing term: {term}")
                data["cliFailures"].append(term)

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
    from apps.ocr_service.profiles import OCR_PROFILES, validate_profiles

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
        except Exception:
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
            if Exception not in tuple(getattr(task, "autoretry_for", ()) or ()):
                retry_missing.append({"task": task_name, "reason": "missing Exception autoretry"})
            if not getattr(task, "retry_backoff", False):
                retry_missing.append({"task": task_name, "reason": "missing retry_backoff"})
            if int(retry_kwargs.get("max_retries") or 0) < 1:
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
        if task_name not in source or ".delay(" not in source or ".run(" not in source:
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
        if role == "admin":
            expected_path = "/admin/overview"
        elif role == "fde":
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
            elif called_names & IDEMPOTENT_DELEGATE_CALLS:
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
