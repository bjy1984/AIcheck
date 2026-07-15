from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from uuid import uuid4

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libs.db.seed import PROJECT_ID
from libs.qwen_runtime import qwen_runtime_config
from libs.security.auth import ROLE_DEFAULT_PATHS


DEFAULT_ROLES = ("admin", "inspection", "contractor", "ndt", "owner", "fde")
REQUIRED_LITELLM_ALIASES = {"default-chat", "review-chat", "deepseek-reasoner", "embedding-default", "compare-fast"}
SECRET_TEXT_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9._-]{6,}"),
    re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"(?i)(['\"]?(?:authorization|api[_-]?key|password|secret|token)['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+"
    ),
]
SENSITIVE_FIELD_NAMES = {"authorization", "api_key", "apikey", "password", "secret", "token"}


def deployment_probe_pdf() -> bytes:
    text_stream = b"BT /F1 18 Tf 72 720 Td (AIcheck OCR verifier) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(text_stream)).encode("ascii") + b" >>\nstream\n" + text_stream + b"\nendstream",
    ]
    parts = [b"%PDF-1.4\n"]
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(sum(len(part) for part in parts))
        parts.append(f"{index} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref_offset = sum(len(part) for part in parts)
    xref = [b"xref\n", f"0 {len(objects) + 1}\n".encode("ascii"), b"0000000000 65535 f \n"]
    for offset in offsets[1:]:
        xref.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    parts.extend(
        [
            *xref,
            b"trailer\n",
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode("ascii"),
            b"startxref\n",
            f"{xref_offset}\n".encode("ascii"),
            b"%%EOF\n",
        ]
    )
    return b"".join(parts)


def redact_sensitive_text(text: str) -> str:
    redacted = text
    redacted = SECRET_TEXT_PATTERNS[0].sub("sk-***", redacted)
    redacted = SECRET_TEXT_PATTERNS[1].sub(r"\1***", redacted)
    redacted = SECRET_TEXT_PATTERNS[2].sub(r"\1***", redacted)
    return redacted


def is_sensitive_field_name(name: object) -> bool:
    normalized = str(name).replace("-", "_").lower()
    return normalized in SENSITIVE_FIELD_NAMES or any(
        normalized.endswith(f"_{field}") for field in SENSITIVE_FIELD_NAMES
    )


def redact_sensitive_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***" if is_sensitive_field_name(key) else redact_sensitive_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_value(item) for item in value)
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def role_login_password(role: str) -> str:
    normalized = role.upper().replace("-", "_")
    return (
        os.getenv(f"AICHECK_VERIFY_PASSWORD_{normalized}")
        or os.getenv(f"AICHECK_BOOTSTRAP_PASSWORD_{normalized}")
        or role
    )


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""
    data: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "pass"


@dataclass
class VerifyConfig:
    api_base: str
    ocr_base: str | None
    litellm_base: str | None
    litellm_api_key: str | None
    project_id: str
    roles: list[str]
    strict_production: bool
    skip_ocr: bool
    skip_litellm: bool
    write_probes: bool
    ocr_object_probe: bool
    review_run_probe: bool
    review_run_wait_seconds: float
    litellm_management_probes: bool
    litellm_provider_probes: bool
    qwen_official_probe: bool
    role_credentials: dict[str, dict[str, str]] = field(default_factory=dict)
    ocr_wait_seconds: float = 240.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AIcheck deployment from the outside.")
    parser.add_argument("--api-base", default=os.getenv("AICHECK_API_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--ocr-base", default=os.getenv("AICHECK_VERIFY_OCR_BASE_URL", "http://127.0.0.1:8010"))
    parser.add_argument("--litellm-base", default=os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:4001"))
    parser.add_argument("--litellm-api-key-file", default=os.getenv("LITELLM_API_KEY_FILE"))
    parser.add_argument("--project-id", default=os.getenv("AICHECK_DEFAULT_PROJECT_ID", PROJECT_ID))
    parser.add_argument("--roles", default=",".join(DEFAULT_ROLES), help="Comma-separated login roles to verify.")
    parser.add_argument(
        "--role-credentials-file",
        default=os.getenv("AICHECK_VERIFY_ROLE_CREDENTIALS_FILE"),
        help="Permission-0600 JSON file containing roles.{role}.username/password.",
    )
    parser.add_argument("--strict-production", action="store_true", help="Fail if production security/storage flags are not enabled.")
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--skip-litellm", action="store_true")
    parser.add_argument(
        "--ocr-object-probe",
        action="store_true",
        help="After --write-probes upload, ask OCR service to parse the uploaded MinIO object. This may be slow.",
    )
    parser.add_argument(
        "--litellm-provider-probes",
        action="store_true",
        help="Run real chat and embedding calls through LiteLLM. This may consume provider quota.",
    )
    parser.add_argument(
        "--qwen-official-probe",
        action="store_true",
        help="Run a real Qwen official API chat completion probe. This may consume provider quota.",
    )
    parser.add_argument(
        "--litellm-management-probes",
        action="store_true",
        help="Create and delete a temporary LiteLLM virtual key to verify DB-backed key, budget, and rate-limit management.",
    )
    parser.add_argument(
        "--write-probes",
        action="store_true",
        help="Run signed PUT upload, signed GET preview/download, OCR task, and export write probes against the target project.",
    )
    parser.add_argument(
        "--review-run-probe",
        action="store_true",
        help=(
            "Create a ReviewRun through ai-recheck, verify graph/timeline/human-decision endpoints, "
            "and verify FDE diagnostic replay. Requires roles inspection,fde."
        ),
    )
    parser.add_argument(
        "--review-run-wait-seconds",
        type=float,
        default=float(os.getenv("AICHECK_VERIFY_REVIEW_RUN_WAIT_SECONDS", "20")),
        help="Maximum seconds for --review-run-probe to wait for Temporal/LangGraph worker progress in strict production.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument(
        "--ocr-wait-seconds",
        type=float,
        default=float(os.getenv("AICHECK_VERIFY_OCR_WAIT_SECONDS", "240")),
        help="Maximum seconds to wait for the queued official OCR object probe.",
    )
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> VerifyConfig:
    if args.ocr_object_probe and args.skip_ocr:
        raise SystemExit("--ocr-object-probe cannot be used with --skip-ocr.")
    if args.ocr_object_probe and not args.write_probes:
        raise SystemExit("--ocr-object-probe requires --write-probes so the verifier has an uploaded object to parse.")
    roles = [item.strip() for item in args.roles.split(",") if item.strip()]
    unknown = [role for role in roles if role not in ROLE_DEFAULT_PATHS]
    if unknown:
        raise SystemExit(f"Unsupported roles: {', '.join(unknown)}")
    if args.review_run_probe:
        missing = sorted({"inspection", "fde"} - set(roles))
        if missing:
            raise SystemExit("--review-run-probe requires --roles including inspection,fde.")
    litellm_api_key = os.getenv("LITELLM_API_KEY")
    key_file = getattr(args, "litellm_api_key_file", None)
    if key_file:
        key_path = Path(key_file).expanduser()
        if key_path.stat().st_mode & 0o077:
            raise SystemExit("--litellm-api-key-file must not be group/world accessible.")
        litellm_api_key = key_path.read_text(encoding="utf-8").strip()
    role_credentials: dict[str, dict[str, str]] = {}
    credentials_file = getattr(args, "role_credentials_file", None)
    if credentials_file:
        credentials_path = Path(credentials_file).expanduser()
        if credentials_path.stat().st_mode & 0o077:
            raise SystemExit("--role-credentials-file must not be group/world accessible.")
        payload = json.loads(credentials_path.read_text(encoding="utf-8"))
        raw_roles = payload.get("roles") if isinstance(payload, dict) else None
        if not isinstance(raw_roles, dict):
            raise SystemExit("--role-credentials-file must contain a roles object.")
        role_credentials = {
            str(role): {
                "username": str(value.get("username") or role),
                "password": str(value.get("password") or ""),
            }
            for role, value in raw_roles.items()
            if isinstance(value, dict)
        }
    return VerifyConfig(
        api_base=args.api_base.rstrip("/"),
        ocr_base=None if args.skip_ocr else (args.ocr_base or "").rstrip("/"),
        litellm_base=None if args.skip_litellm else (args.litellm_base or "").rstrip("/"),
        litellm_api_key=litellm_api_key,
        project_id=args.project_id,
        roles=roles,
        strict_production=args.strict_production,
        skip_ocr=args.skip_ocr,
        skip_litellm=args.skip_litellm,
        write_probes=args.write_probes,
        ocr_object_probe=args.ocr_object_probe,
        review_run_probe=args.review_run_probe,
        review_run_wait_seconds=max(0.0, float(args.review_run_wait_seconds or 0.0)),
        litellm_management_probes=args.litellm_management_probes,
        litellm_provider_probes=args.litellm_provider_probes,
        qwen_official_probe=args.qwen_official_probe,
        role_credentials=role_credentials,
        ocr_wait_seconds=max(1.0, float(args.ocr_wait_seconds or 240)),
    )


class DeploymentVerifier:
    def __init__(
        self,
        config: VerifyConfig,
        *,
        api_client: httpx.Client,
        ocr_client: httpx.Client | None = None,
        litellm_client: httpx.Client | None = None,
        storage_client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.api = api_client
        self.ocr = ocr_client
        self.litellm = litellm_client
        self.storage = storage_client or api_client
        self.results: list[CheckResult] = []
        self.api_health: dict[str, Any] = {}
        self.tokens: dict[str, str] = {}
        self.official_ocr_probe_passed = False

    def official_ocr_mode(self) -> bool:
        services = self.api_health.get("serviceReadiness") if isinstance(self.api_health, dict) else {}
        ocr = services.get("ocr") if isinstance(services, dict) else {}
        return str((ocr or {}).get("providerMode") or "").lower() == "official"

    def run(self) -> list[CheckResult]:
        self.check_api_health()
        self.check_strict_production_flags()
        self.check_auth_gate()
        self.check_role_logins()
        self.check_postgres_transaction_probe()
        self.check_admin_reads_rejected()
        self.check_project_and_task_reads()
        self.check_write_probes()
        self.check_review_run_probe()
        self.check_identity_spoof_rejected()
        self.check_action_bypass_rejected()
        self.check_read_scope_rejected()
        self.check_ocr_health()
        self.check_ocr_readyz()
        self.check_ocr_runtime_doctor()
        self.check_ocr_parse_contract()
        self.check_ocr_bad_request_contract()
        self.check_litellm_health()
        self.check_qwen_official_probe()
        return self.results

    def add(self, name: str, status: str, detail: str = "", data: dict[str, Any] | None = None) -> None:
        safe_data = redact_sensitive_value(data) if data is not None else None
        self.results.append(
            CheckResult(
                name=name,
                status=status,
                detail=redact_sensitive_text(detail),
                data=safe_data,
            )
        )

    def request_json(self, client: httpx.Client, method: str, path: str, **kwargs: Any) -> tuple[int, Any]:
        try:
            response = client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            return 598, {"code": "REQUEST_TIMEOUT", "errorType": exc.__class__.__name__}
        except httpx.RequestError as exc:
            return 599, {"code": "REQUEST_FAILED", "errorType": exc.__class__.__name__}
        try:
            payload = response.json()
        except Exception:
            payload = response.text
        return response.status_code, payload

    def envelope_data(self, name: str, status_code: int, payload: Any) -> dict[str, Any] | None:
        if status_code != 200:
            self.add(name, "fail", f"HTTP {status_code}")
            return None
        if not isinstance(payload, dict) or payload.get("code") != 0:
            self.add(name, "fail", f"Unexpected envelope: {payload}")
            return None
        return payload.get("data") or {}

    def check_api_health(self) -> None:
        try:
            status_code, payload = self.request_json(self.api, "GET", "/api/healthz")
        except Exception as exc:
            self.add("api.health", "fail", str(exc))
            return
        data = self.envelope_data("api.health", status_code, payload)
        if data is None:
            return
        self.api_health = data
        required = {"service", "authRequired", "demoUsersEnabled", "postgresEnabled", "objectStorageEnabled"}
        missing = sorted(required - set(data))
        if missing:
            self.add("api.health", "fail", f"Missing fields: {', '.join(missing)}", data)
            return
        self.add("api.health", "pass", "API health envelope and runtime flags are present.", data)

    def check_strict_production_flags(self) -> None:
        if not self.config.strict_production or not self.api_health:
            return
        expected = {
            "authRequired": True,
            "demoUsersEnabled": False,
            "postgresEnabled": True,
            "postgresTransactions": True,
            "objectStorageEnabled": True,
        }
        mismatches = [
            f"{key} expected {expected_value!r}, got {self.api_health.get(key)!r}"
            for key, expected_value in expected.items()
            if self.api_health.get(key) is not expected_value
        ]
        self.add(
            "api.strict-production",
            "fail" if mismatches else "pass",
            "; ".join(mismatches) if mismatches else "Production flags match expected values.",
        )

    def check_auth_gate(self) -> None:
        if not self.api_health.get("authRequired"):
            self.add("auth.gate", "skip", "AICHECK_REQUIRE_AUTH is false.")
            return
        status_code, payload = self.request_json(self.api, "GET", "/api/auth/me")
        if status_code == 200 and isinstance(payload, dict) and payload.get("data", {}).get("reason") == "AUTH_REQUIRED":
            self.add("auth.gate", "pass", "Protected endpoint rejects anonymous access.")
            return
        self.add("auth.gate", "fail", f"Expected AUTH_REQUIRED, got {payload}")

    def check_role_logins(self) -> None:
        for role in self.config.roles:
            credential = self.config.role_credentials.get(role) or {}
            username = str(credential.get("username") or role)
            password = str(credential.get("password") or role_login_password(role))
            status_code, payload = self.request_json(
                self.api,
                "POST",
                "/api/auth/login",
                json={"username": username, "password": password},
            )
            data = self.envelope_data(f"auth.login.{role}", status_code, payload)
            if data is None:
                continue
            user = data.get("user") or {}
            token = data.get("token")
            expected_path = ROLE_DEFAULT_PATHS[role]
            if user.get("role") != role or user.get("defaultPath") != expected_path or not token:
                self.add(f"auth.login.{role}", "fail", f"Unexpected login data: {data}")
                continue
            self.tokens[role] = token
            self.add(f"auth.login.{role}", "pass", f"defaultPath={expected_path}")
            self.check_auth_me(role, token)

    def check_auth_me(self, role: str, token: str) -> None:
        status_code, payload = self.request_json(
            self.api,
            "GET",
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = self.envelope_data(f"auth.me.{role}", status_code, payload)
        if data is None:
            return
        if data.get("defaultRole") != role:
            self.add(f"auth.me.{role}", "fail", f"Expected role {role}, got {data.get('defaultRole')}")
            return
        self.add(f"auth.me.{role}", "pass")

    def auth_headers(self, preferred_role: str = "admin") -> dict[str, str]:
        token = self.tokens.get(preferred_role) or next(iter(self.tokens.values()), "")
        return {"Authorization": f"Bearer {token}"} if token else {}

    def check_project_and_task_reads(self) -> None:
        headers = self.auth_headers("inspection")
        for name, path in [
            ("api.projects", "/api/workbench/projects"),
            ("api.knowledge-tasks", "/api/knowledge/tasks"),
        ]:
            status_code, payload = self.request_json(self.api, "GET", path, headers=headers)
            data = self.envelope_data(name, status_code, payload)
            if data is not None:
                self.add(name, "pass")

    def check_postgres_transaction_probe(self) -> None:
        if not self.config.strict_production and not self.api_health.get("postgresTransactions"):
            self.add("postgres.transaction-probe", "skip", "PostgreSQL persistence is disabled.")
            return
        status_code, payload = self.request_json(
            self.api,
            "GET",
            "/api/system/postgres-transaction-probe",
            headers=self.auth_headers("admin"),
        )
        data = self.envelope_data("postgres.transaction-probe", status_code, payload)
        if data is None:
            return
        failures = []
        if self.config.strict_production:
            if data.get("postgresEnabled") is not True:
                failures.append("postgresEnabled must be true")
            if data.get("transactionsConfigured") is not True:
                failures.append("transactionsConfigured must be true")
            if data.get("transactionProbe") != "pass":
                failures.append(f"transactionProbe must be pass, got {data.get('transactionProbe')!r}")
        elif data.get("transactionsConfigured") and data.get("transactionProbe") == "failed":
            failures.append("transaction probe failed")
        if failures:
            self.add("postgres.transaction-probe", "fail", "; ".join(failures), data)
            return
        status = "pass" if data.get("transactionProbe") == "pass" else "skip"
        detail = "PostgreSQL transaction probe passed." if status == "pass" else str(data.get("reason") or "PostgreSQL transaction probe skipped.")
        self.add("postgres.transaction-probe", status, detail, data)

    def check_write_probes(self) -> None:
        if not self.config.write_probes:
            self.add("api.write-probes", "skip", "Write probes disabled; pass --write-probes to verify upload/OCR/export mutations.")
            return
        headers = self.auth_headers("contractor")
        suffix = uuid4().hex[:8]
        file_name = f"deployment-verify-{suffix}.pdf"
        status_code, payload = self.request_json(
            self.api,
            "POST",
            f"/api/projects/{self.config.project_id}/documents/upload-session",
            headers={**headers, "Idempotency-Key": f"verify-upload-{suffix}"},
            json={"files": [{"fileName": file_name, "fileSize": 1024, "fileType": "application/pdf"}]},
        )
        data = self.envelope_data("api.write-probes.upload-session", status_code, payload)
        if data is None:
            self.add("api.write-probes", "fail", "Upload session probe failed.")
            return
        upload_urls = data.get("uploadUrls") or []
        session_id = data.get("uploadSessionId")
        if not session_id or not upload_urls or upload_urls[0].get("method") != "PUT":
            self.add("api.write-probes", "fail", f"Unexpected upload session payload: {data}")
            return
        document_id = upload_urls[0].get("documentId")
        if not document_id:
            self.add("api.write-probes", "fail", f"Upload session missing documentId: {data}")
            return
        if not self.check_signed_put_url(upload_urls[0]):
            self.add("api.write-probes", "fail", "Signed PUT probe failed.")
            return

        status_code, payload = self.request_json(
            self.api,
            "POST",
            f"/api/projects/{self.config.project_id}/documents/upload-session/{session_id}/complete",
            headers=headers,
        )
        complete = self.envelope_data("api.write-probes.upload-complete", status_code, payload)
        if complete is None:
            self.add("api.write-probes", "fail", "Upload complete probe failed.")
            return
        if int(complete.get("fileCount") or 0) < 1 or not isinstance(complete.get("queuedTasks"), list):
            self.add("api.write-probes", "fail", f"Unexpected upload complete payload: {complete}")
            return

        status_code, payload = self.request_json(
            self.api,
            "GET",
            "/api/knowledge/tasks?taskType=ocr&pageSize=50",
            headers=headers,
        )
        tasks = self.envelope_data("api.write-probes.ocr-task", status_code, payload)
        if tasks is None:
            self.add("api.write-probes", "fail", "OCR task list probe failed.")
            return
        task_items = tasks.get("items") if isinstance(tasks, dict) else []
        if not any(isinstance(item, dict) and item.get("targetName") == file_name for item in task_items or []):
            self.add("api.write-probes", "fail", f"Created upload did not appear in OCR tasks: {tasks}")
            return
        if not self.check_document_signed_get_urls(str(document_id), headers):
            self.add("api.write-probes", "fail", "Document signed GET preview/download probe failed.")
            return
        if not self.check_uploaded_document_ocr_parse(str(document_id), file_name, headers):
            self.add("api.write-probes", "fail", "Uploaded object OCR parse probe failed.")
            return

        export_headers = self.auth_headers("admin")
        status_code, payload = self.request_json(
            self.api,
            "POST",
            "/api/exports",
            headers={**export_headers, "Idempotency-Key": f"verify-export-{suffix}"},
            json={"projectId": self.config.project_id, "fileName": f"deployment-verify-{suffix}.zip"},
        )
        export = self.envelope_data("api.write-probes.export-create", status_code, payload)
        if export is None:
            self.add("api.write-probes", "fail", "Export create probe failed.")
            return
        export_id = export.get("exportId")
        task = export.get("task") or {}
        if not export_id or task.get("status") not in {"排队中", "运行中", "可下载"}:
            self.add("api.write-probes", "fail", f"Unexpected export payload: {export}")
            return
        status_code, payload = self.request_json(self.api, "GET", f"/api/exports/{export_id}", headers=export_headers)
        detail = self.envelope_data("api.write-probes.export-detail", status_code, payload)
        if detail is None or not isinstance(detail.get("task"), dict):
            self.add("api.write-probes", "fail", f"Export detail probe failed: {payload}")
            return
        self.add(
            "api.write-probes",
            "pass",
            "Signed PUT, upload complete, document signed GETs, OCR task creation, optional OCR object parse, and export task probes passed.",
        )

    def check_review_run_probe(self) -> None:
        if not self.config.review_run_probe:
            self.add(
                "api.review-run-probe",
                "skip",
                "Pass --review-run-probe with --roles including inspection,fde to verify Temporal/LangGraph ReviewRun orchestration.",
            )
            return
        missing_tokens = [role for role in ["inspection", "fde"] if role not in self.tokens]
        if missing_tokens:
            self.add("api.review-run-probe", "fail", f"Missing login token(s): {', '.join(missing_tokens)}")
            return
        suffix = uuid4().hex[:8]
        inspection_headers = self.auth_headers("inspection")
        fde_headers = self.auth_headers("fde")

        status_code, payload = self.request_json(
            self.api,
            "POST",
            f"/api/projects/{self.config.project_id}/inspection/nodes/24/ai-recheck",
            headers={**inspection_headers, "Idempotency-Key": f"verify-review-run-{suffix}"},
        )
        created = self.envelope_data("api.review-run-probe.create", status_code, payload)
        if created is None:
            self.add("api.review-run-probe", "fail", "ReviewRun create probe failed.")
            return
        dispatch = created.get("dispatch") if isinstance(created.get("dispatch"), dict) else {}
        latest_run = created.get("latestRun") if isinstance(created.get("latestRun"), dict) else {}
        review_run_id = str(dispatch.get("reviewRunId") or latest_run.get("reviewRunId") or "")
        dispatch_mode = str(dispatch.get("mode") or "")
        dispatch_status = str(dispatch.get("status") or "")
        if not review_run_id:
            self.add("api.review-run-probe", "fail", f"ai-recheck did not return reviewRunId: {created}")
            return
        if dispatch_status in {"failed_to_start", "missing"}:
            self.add("api.review-run-probe", "fail", f"ReviewRun dispatch failed: {dispatch}", {"dispatch": dispatch})
            return
        if self.config.strict_production and dispatch_mode != "temporal":
            self.add(
                "api.review-run-probe",
                "fail",
                f"Strict production ReviewRun probe requires Temporal dispatch, got mode={dispatch_mode!r}.",
                {"dispatch": dispatch},
            )
            return

        detail, graph, timeline, progressed = self.wait_for_review_run_progress(review_run_id, inspection_headers)
        if detail is None:
            self.add("api.review-run-probe", "fail", "ReviewRun detail probe failed.")
            return
        run = detail.get("run") if isinstance(detail.get("run"), dict) else {}
        run_failures = []
        if run.get("reviewRunId") != review_run_id:
            run_failures.append("detail run.reviewRunId mismatch")
        if not run.get("workflowEngine"):
            run_failures.append("workflowEngine is missing")
        if not run.get("graphEngine"):
            run_failures.append("graphEngine is missing")
        if run.get("modelGateway") != "qwen_runtime":
            run_failures.append(f"modelGateway expected qwen_runtime, got {run.get('modelGateway')!r}")
        if run_failures:
            self.add("api.review-run-probe", "fail", "; ".join(run_failures), {"run": run})
            return
        if graph is None:
            self.add("api.review-run-probe", "fail", "ReviewRun graph probe failed.")
            return
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        edges = graph.get("edges") if isinstance(graph, dict) else None
        if not isinstance(nodes, list) or not nodes:
            self.add("api.review-run-probe", "fail", "ReviewRun graph returned no nodes.", {"graph": graph})
            return
        if not isinstance(edges, list) or len(edges) < max(0, len(nodes) - 1):
            self.add("api.review-run-probe", "fail", "ReviewRun graph edges are incomplete.", {"nodeCount": len(nodes), "edges": edges})
            return
        if any(not isinstance(node, dict) or not node.get("nodeKey") or not node.get("status") for node in nodes):
            self.add("api.review-run-probe", "fail", "ReviewRun graph nodes must include nodeKey/status.", {"nodes": nodes[:3]})
            return
        if timeline is None:
            self.add("api.review-run-probe", "fail", "ReviewRun timeline probe failed.")
            return
        events = timeline.get("events") if isinstance(timeline, dict) else None
        if not isinstance(events, list) or not events:
            self.add("api.review-run-probe", "fail", "ReviewRun timeline returned no events.", {"timeline": timeline})
            return
        if self.config.strict_production and not progressed:
            node_statuses = sorted({str(node.get("status") or "") for node in nodes if isinstance(node, dict)})
            self.add(
                "api.review-run-probe",
                "fail",
                f"ReviewRun graph did not progress within {self.config.review_run_wait_seconds:g}s.",
                {"reviewRunId": review_run_id, "runStatus": run.get("status"), "nodeStatuses": node_statuses},
            )
            return

        decision = self.get_required_envelope(
            "api.review-run-probe.human-decision",
            "POST",
            f"/api/review-runs/{review_run_id}/human-decision",
            headers={**inspection_headers, "Idempotency-Key": f"verify-review-run-decision-{suffix}"},
            json={"decision": "accept", "comment": "deployment verifier accepted this temporary ReviewRun."},
        )
        if decision is None:
            self.add("api.review-run-probe", "fail", "ReviewRun human decision probe failed.")
            return
        decision_run = decision.get("reviewRun") if isinstance(decision.get("reviewRun"), dict) else {}
        if decision_run.get("status") != "accepted_by_human":
            self.add("api.review-run-probe", "fail", f"Expected accepted_by_human, got {decision_run.get('status')!r}.", decision)
            return

        fde_detail = self.get_required_envelope(
            "fde.review-run-probe.detail",
            "GET",
            f"/api/fde/review-runs/{review_run_id}",
            headers=fde_headers,
        )
        if fde_detail is None:
            self.add("api.review-run-probe", "fail", "FDE ReviewRun detail probe failed.")
            return
        if not isinstance(fde_detail.get("graph"), dict) or not isinstance(fde_detail.get("temporal"), dict):
            self.add("api.review-run-probe", "fail", "FDE ReviewRun detail must include graph and temporal summaries.", fde_detail)
            return
        scorecard = fde_detail.get("scorecard") if isinstance(fde_detail.get("scorecard"), dict) else {}
        if self.config.strict_production and (
            scorecard.get("targetScore") != 100
            or scorecard.get("ok") is not True
            or float(scorecard.get("score") or 0) < 100
        ):
            self.add(
                "api.review-run-probe",
                "fail",
                "Strict production ReviewRun probe requires FDE orchestration scorecard 100.",
                {"reviewRunId": review_run_id, "scorecard": scorecard},
            )
            return

        replay = self.get_required_envelope(
            "fde.review-run-probe.replay",
            "POST",
            f"/api/fde/review-runs/{review_run_id}/replay",
            headers={**fde_headers, "Idempotency-Key": f"verify-review-run-replay-{suffix}"},
            json={"runMode": "diagnostic_replay", "reason": "deployment verifier immutable replay probe"},
        )
        if replay is None:
            self.add("api.review-run-probe", "fail", "FDE ReviewRun replay probe failed.")
            return
        replay_run = replay.get("reviewRun") if isinstance(replay.get("reviewRun"), dict) else {}
        if replay_run.get("parentReviewRunId") != review_run_id or replay_run.get("reviewRunId") == review_run_id:
            self.add("api.review-run-probe", "fail", f"Unexpected replay payload: {replay}")
            return

        self.add(
            "api.review-run-probe",
            "pass",
            "ReviewRun create/detail/graph/timeline/human-decision and FDE diagnostic replay probes passed.",
            {
                "reviewRunId": review_run_id,
                "dispatchMode": dispatch_mode,
                "workflowEngine": run.get("workflowEngine"),
                "graphEngine": run.get("graphEngine"),
                "graphRunner": run.get("graphRunner"),
                "graphProgressed": progressed,
                "scorecardScore": scorecard.get("score"),
                "scorecardOk": scorecard.get("ok"),
                "nodeCount": len(nodes),
                "eventCount": len(events),
                "replayReviewRunId": replay_run.get("reviewRunId"),
            },
        )

    def wait_for_review_run_progress(
        self,
        review_run_id: str,
        headers: dict[str, str],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, bool]:
        deadline = time.monotonic() + self.config.review_run_wait_seconds
        latest_detail: dict[str, Any] | None = None
        latest_graph: dict[str, Any] | None = None
        latest_timeline: dict[str, Any] | None = None
        latest_progressed = False
        while True:
            latest_detail = self.get_required_envelope(
                "api.review-run-probe.detail",
                "GET",
                f"/api/review-runs/{review_run_id}",
                headers=headers,
            )
            latest_graph = self.get_required_envelope(
                "api.review-run-probe.graph",
                "GET",
                f"/api/review-runs/{review_run_id}/graph",
                headers=headers,
            )
            latest_timeline = self.get_required_envelope(
                "api.review-run-probe.timeline",
                "GET",
                f"/api/review-runs/{review_run_id}/timeline",
                headers=headers,
            )
            if latest_detail is None or latest_graph is None or latest_timeline is None:
                return latest_detail, latest_graph, latest_timeline, False
            latest_progressed = self.review_run_progressed(latest_detail, latest_graph)
            if latest_progressed or not self.config.strict_production or time.monotonic() >= deadline:
                return latest_detail, latest_graph, latest_timeline, latest_progressed
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))

    def review_run_progressed(self, detail: dict[str, Any], graph: dict[str, Any]) -> bool:
        run = detail.get("run") if isinstance(detail.get("run"), dict) else {}
        if run.get("status") not in {None, "", "created", "queued"}:
            return True
        nodes = graph.get("nodes") if isinstance(graph, dict) else []
        progressed_statuses = {"running", "succeeded", "failed", "skipped"}
        return any(isinstance(node, dict) and node.get("status") in progressed_statuses for node in nodes)

    def get_required_envelope(self, name: str, method: str, path: str, **kwargs: Any) -> dict[str, Any] | None:
        status_code, payload = self.request_json(self.api, method, path, **kwargs)
        return self.envelope_data(name, status_code, payload)

    def check_signed_put_url(self, upload_url: dict[str, Any]) -> bool:
        url = str(upload_url.get("url") or "")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            if self.config.strict_production:
                self.add("api.write-probes.signed-put", "fail", f"Production signed PUT URL must be HTTP(S), got {url!r}.")
                return False
            self.add("api.write-probes.signed-put", "skip", f"Non-HTTP signed URL {url!r}; skipping object upload probe.")
            return True
        headers = {str(key): str(value) for key, value in (upload_url.get("headers") or {}).items()}
        content_type = headers.get("Content-Type") or headers.get("content-type") or "application/pdf"
        headers.setdefault("Content-Type", content_type)
        body = deployment_probe_pdf()
        try:
            response = self.storage.request("PUT", url, headers=headers, content=body)
        except Exception as exc:
            self.add("api.write-probes.signed-put", "fail", str(exc))
            return False
        if response.status_code >= 400:
            self.add("api.write-probes.signed-put", "fail", f"HTTP {response.status_code}")
            return False
        self.add("api.write-probes.signed-put", "pass", f"HTTP {response.status_code}")
        return True

    def check_uploaded_document_ocr_parse(self, document_id: str, file_name: str, headers: dict[str, str]) -> bool:
        if not self.config.ocr_object_probe:
            self.add("ocr.uploaded-object-parse", "skip", "Pass --ocr-object-probe with --write-probes to parse the uploaded object.")
            return True
        if self.official_ocr_mode():
            deadline = time.monotonic() + self.config.ocr_wait_seconds
            latest_readiness: dict[str, Any] = {}
            while time.monotonic() < deadline:
                status_code, payload = self.request_json(
                    self.api,
                    "GET",
                    f"/api/projects/{self.config.project_id}/documents/{document_id}",
                    headers=headers,
                )
                detail = self.envelope_data("api.write-probes.document-ocr-status", status_code, payload)
                if detail is None:
                    return False
                document = detail.get("document") if isinstance(detail.get("document"), dict) else detail
                latest_readiness = (
                    document.get("ocrReadiness")
                    if isinstance(document, dict) and isinstance(document.get("ocrReadiness"), dict)
                    else {}
                )
                status_value = str(latest_readiness.get("status") or "")
                if status_value in {"ready", "incomplete", "failed", "inconsistent"}:
                    break
                time.sleep(min(2.0, max(0.1, deadline - time.monotonic())))
            failures = []
            if latest_readiness.get("status") not in {"ready", "incomplete"}:
                failures.append(f"terminal OCR readiness expected, got {latest_readiness.get('status')!r}")
            if not latest_readiness.get("parseResultId"):
                failures.append("parseResultId is missing")
            if int(latest_readiness.get("fragmentCount") or 0) < 1:
                failures.append("official OCR returned no text fragments")
            if latest_readiness.get("providerMode") != "official":
                failures.append(f"providerMode expected official, got {latest_readiness.get('providerMode')!r}")
            if latest_readiness.get("formalEvidenceReady") is True:
                failures.append("uncertified deployment probe must not become formal evidence ready")
            if failures:
                self.add("ocr.uploaded-object-parse", "fail", "; ".join(failures), latest_readiness)
                return False
            self.official_ocr_probe_passed = True
            self.add(
                "ocr.uploaded-object-parse",
                "pass",
                "API -> Celery -> official OCR produced grounded, non-formal parse evidence.",
                {
                    "parseResultId": latest_readiness.get("parseResultId"),
                    "pipelineRunId": latest_readiness.get("pipelineRunId"),
                    "fragmentCount": latest_readiness.get("fragmentCount"),
                    "costCny": latest_readiness.get("costCny"),
                },
            )
            return True
        if self.config.skip_ocr or self.ocr is None:
            self.add("ocr.uploaded-object-parse", "fail", "OCR client is disabled.")
            return False
        status_code, payload = self.request_json(
            self.api,
            "GET",
            f"/api/projects/{self.config.project_id}/documents/{document_id}",
            headers=headers,
        )
        detail = self.envelope_data("api.write-probes.document-detail", status_code, payload)
        if detail is None:
            return False
        current_version = detail.get("currentVersion") if isinstance(detail, dict) else None
        storage_key = (current_version or {}).get("storageKey") if isinstance(current_version, dict) else None
        if not storage_key:
            self.add("ocr.uploaded-object-parse", "fail", f"Document detail missing currentVersion.storageKey: {detail}")
            return False
        try:
            status_code, payload = self.request_json(
                self.ocr,
                "POST",
                "/internal/ocr/parse",
                json={"storageKey": storage_key, "fileName": file_name},
            )
        except Exception as exc:
            self.add("ocr.uploaded-object-parse", "fail", str(exc))
            return False
        data = self.envelope_data("ocr.uploaded-object-parse", status_code, payload)
        if data is None:
            return False
        required = {"storageKey", "status", "fragments", "fields", "diagnostics"}
        missing = sorted(required - set(data))
        if missing:
            self.add("ocr.uploaded-object-parse", "fail", f"Missing fields: {', '.join(missing)}", data)
            return False
        if data.get("status") != "success":
            self.add("ocr.uploaded-object-parse", "fail", f"Expected status=success, got {data.get('status')!r}.", data)
            return False
        if not isinstance(data.get("fragments"), list):
            self.add("ocr.uploaded-object-parse", "fail", "fragments must be a list.", data)
            return False
        self.add("ocr.uploaded-object-parse", "pass", "OCR service parsed the uploaded object.", {"storageKey": storage_key})
        return True

    def check_document_signed_get_urls(self, document_id: str, headers: dict[str, str]) -> bool:
        for label, path in [
            ("preview", f"/api/projects/{self.config.project_id}/documents/{document_id}/preview-url"),
            ("download", f"/api/projects/{self.config.project_id}/documents/{document_id}/download-url"),
        ]:
            status_code, payload = self.request_json(self.api, "GET", path, headers=headers)
            data = self.envelope_data(f"api.write-probes.document-{label}", status_code, payload)
            if data is None:
                return False
            if not self.check_signed_get_url(f"api.write-probes.document-{label}-get", data, headers=headers):
                return False
        return True

    def check_signed_get_url(self, name: str, payload: dict[str, Any], *, headers: dict[str, str]) -> bool:
        url = str(payload.get("url") or "")
        parsed = urlparse(url)
        if payload.get("method") != "GET":
            self.add(name, "fail", f"Expected method GET, got {payload.get('method')!r}.")
            return False
        if parsed.scheme not in {"http", "https"} and url.startswith("/api/"):
            try:
                response = self.api.request("GET", url, headers=headers)
            except Exception as exc:
                self.add(name, "fail", str(exc))
                return False
            if response.status_code >= 400:
                self.add(name, "fail", f"HTTP {response.status_code}")
                return False
            self.add(name, "pass", f"HTTP {response.status_code} via authenticated API proxy.")
            return True
        if parsed.scheme not in {"http", "https"}:
            if self.config.strict_production:
                self.add(name, "fail", f"Production signed GET URL must be HTTP(S), got {url!r}.")
                return False
            self.add(name, "skip", f"Non-HTTP signed URL {url!r}; skipping object download probe.")
            return True
        try:
            response = self.storage.request("GET", url)
        except Exception as exc:
            self.add(name, "fail", str(exc))
            return False
        if response.status_code >= 400:
            self.add(name, "fail", f"HTTP {response.status_code}")
            return False
        self.add(name, "pass", f"HTTP {response.status_code}")
        return True

    def check_admin_reads_rejected(self) -> None:
        if not self.api_health.get("authRequired") or "contractor" not in self.tokens:
            self.add("auth.admin-reads", "skip", "Auth is disabled or contractor token is unavailable.")
            return
        failures = []
        contractor_headers = {"Authorization": f"Bearer {self.tokens['contractor']}"}
        for path in ["/api/admin/config-overview", "/api/knowledge/sources", "/api/rules/versions"]:
            status_code, payload = self.request_json(self.api, "GET", path, headers=contractor_headers)
            if not (status_code == 200 and isinstance(payload, dict) and payload.get("data", {}).get("reason") == "FORBIDDEN"):
                failures.append(f"{path}: {payload}")
        if "admin" in self.tokens:
            status_code, payload = self.request_json(
                self.api,
                "GET",
                "/api/admin/config-overview",
                headers={"Authorization": f"Bearer {self.tokens['admin']}"},
            )
            if self.envelope_data("auth.admin-reads.admin-access", status_code, payload) is None:
                failures.append(f"admin access: {payload}")
        if failures:
            self.add("auth.admin-reads", "fail", "; ".join(failures))
            return
        self.add("auth.admin-reads", "pass", "Business roles cannot read admin/global knowledge configuration endpoints.")

    def check_identity_spoof_rejected(self) -> None:
        if not self.api_health.get("authRequired") or "contractor" not in self.tokens:
            self.add("auth.identity-spoof", "skip", "Auth is disabled or contractor token is unavailable.")
            return
        status_code, payload = self.request_json(
            self.api,
            "POST",
            f"/api/projects/{self.config.project_id}/inspection/nodes/24/ai-recheck",
            headers={
                "Authorization": f"Bearer {self.tokens['contractor']}",
                "X-Role": "inspection",
            },
        )
        if status_code == 200 and isinstance(payload, dict) and payload.get("data", {}).get("reason") == "FORBIDDEN":
            self.add("auth.identity-spoof", "pass", "Role spoofing is rejected.")
            return
        self.add("auth.identity-spoof", "fail", f"Expected FORBIDDEN, got {payload}")

    def check_action_bypass_rejected(self) -> None:
        if not self.api_health.get("authRequired") or "contractor" not in self.tokens:
            self.add("auth.action-bypass", "skip", "Auth is disabled or contractor token is unavailable.")
            return
        cases = [
            (
                "report.generate",
                "POST",
                f"/api/projects/{self.config.project_id}/inspection/nodes/24/report-review",
                {"includeEvidence": True, "reportScope": "currentNode"},
            ),
            ("admin.publish", "POST", "/api/admin/config-overview/publish", {"scope": "all"}),
        ]
        failures = []
        for label, method, path, body in cases:
            status_code, payload = self.request_json(
                self.api,
                method,
                path,
                headers={"Authorization": f"Bearer {self.tokens['contractor']}"},
                json=body,
            )
            if not (status_code == 200 and isinstance(payload, dict) and payload.get("data", {}).get("reason") == "FORBIDDEN"):
                failures.append(f"{label}: {payload}")
        if failures:
            self.add("auth.action-bypass", "fail", "; ".join(failures))
            return
        self.add("auth.action-bypass", "pass", "Unauthorized role actions are rejected without relying on X-Action-Code.")

    @staticmethod
    def raw_envelope_data(status_code: int, payload: Any) -> Any | None:
        if status_code != 200 or not isinstance(payload, dict) or payload.get("code") != 0:
            return None
        return payload.get("data") if payload.get("data") is not None else {}

    @staticmethod
    def rejection_reason(payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        data = payload.get("data")
        if isinstance(data, dict):
            return str(data.get("reason") or "")
        return str(payload.get("reason") or "")

    @staticmethod
    def response_leaks_resource(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        data = payload.get("data")
        if not isinstance(data, dict):
            return False
        harmless = {"reason", "message", "requestId", "request_id"}
        return any(key not in harmless for key in data)

    @staticmethod
    def page_items(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return [item for item in data["items"] if isinstance(item, dict)]
        return []

    def admin_scope_candidates(self) -> dict[str, list[str]]:
        headers = self.auth_headers("admin")
        candidates: dict[str, list[str]] = {
            "node": ["40"],
            "document": ["DOC-20260625-004"],
            "knowledge-file": ["KF-DOC-20260625-004"],
            "knowledge-task": ["KT-20260626-001"],
        }

        status_code, payload = self.request_json(
            self.api,
            "GET",
            f"/api/projects/{self.config.project_id}/tree",
            headers=headers,
        )
        tree = self.raw_envelope_data(status_code, payload)
        if isinstance(tree, dict):
            for group in tree.get("groups") or []:
                if not isinstance(group, dict):
                    continue
                for node in group.get("nodes") or []:
                    if isinstance(node, dict) and node.get("id") is not None:
                        candidates["node"].append(str(node["id"]))

        list_paths = {
            "document": f"/api/projects/{self.config.project_id}/documents?page=1&pageSize=200",
            "knowledge-file": f"/api/knowledge/project-files?projectId={quote(self.config.project_id, safe='')}&page=1&pageSize=200",
            "knowledge-task": "/api/knowledge/tasks?page=1&pageSize=200",
        }
        for kind, path in list_paths.items():
            status_code, payload = self.request_json(self.api, "GET", path, headers=headers)
            data = self.raw_envelope_data(status_code, payload)
            for item in self.page_items(data):
                identifier = item.get("id") or item.get("taskId")
                if identifier:
                    candidates[kind].append(str(identifier))

        return {kind: list(dict.fromkeys(values)) for kind, values in candidates.items()}

    def discover_out_of_scope_resources(self, contractor_headers: dict[str, str]) -> tuple[dict[str, str], list[str]]:
        admin_headers = self.auth_headers("admin")
        candidates = self.admin_scope_candidates()
        path_builders = {
            "node": lambda value: f"/api/projects/{self.config.project_id}/nodes/{quote(value, safe='')}/package",
            "document": lambda value: f"/api/projects/{self.config.project_id}/documents/{quote(value, safe='')}",
            "knowledge-file": lambda value: f"/api/knowledge/files/{quote(value, safe='')}",
            "knowledge-task": lambda value: f"/api/knowledge/tasks/{quote(value, safe='')}",
        }
        discovered: dict[str, str] = {}
        failures: list[str] = []
        for kind, builder in path_builders.items():
            unexpected: list[str] = []
            for candidate in candidates[kind]:
                path = builder(candidate)
                admin_status, admin_payload = self.request_json(self.api, "GET", path, headers=admin_headers)
                if self.raw_envelope_data(admin_status, admin_payload) is None:
                    continue
                status_code, payload = self.request_json(self.api, "GET", path, headers=contractor_headers)
                reason = self.rejection_reason(payload)
                if reason in {"FORBIDDEN", "NOT_FOUND"} and not self.response_leaks_resource(payload):
                    discovered[kind] = candidate
                    break
                if self.raw_envelope_data(status_code, payload) is not None:
                    continue
                unexpected.append(f"{candidate}={reason or status_code}")
            if kind in {"node", "document", "knowledge-file"} and kind not in discovered:
                suffix = f" ({', '.join(unexpected[:3])})" if unexpected else ""
                failures.append(f"no known-existing out-of-scope {kind} target{suffix}")
        return discovered, failures

    def check_read_scope_rejected(self) -> None:
        if (
            not self.api_health.get("authRequired")
            or "contractor" not in self.tokens
            or "admin" not in self.tokens
        ):
            status = "fail" if self.config.strict_production else "skip"
            self.add("auth.read-scope", status, "Auth is disabled or admin/contractor token is unavailable.")
            return
        headers = {"Authorization": f"Bearer {self.tokens['contractor']}"}
        discovered, failures = self.discover_out_of_scope_resources(headers)

        status_code, payload = self.request_json(
            self.api,
            "GET",
            f"/api/projects/{self.config.project_id}/workbench/context?role=inspection",
            headers=headers,
        )
        if self.rejection_reason(payload) != "FORBIDDEN":
            failures.append(f"role-query: expected FORBIDDEN, got {payload}")
        if failures:
            self.add("auth.read-scope", "fail", "; ".join(failures))
            return
        self.add(
            "auth.read-scope",
            "pass",
            "Known-existing out-of-scope reads and role-query spoofing are rejected without resource disclosure.",
            {"verifiedKinds": sorted(discovered)},
        )
        self.check_aggregate_scope(headers, discovered)

    def check_aggregate_scope(self, headers: dict[str, str], discovered: dict[str, str]) -> None:
        aggregate_cases: list[tuple[str, str, set[str]]] = []
        document_id = discovered.get("document")
        if document_id:
            aggregate_cases.append(
                (
                    "search",
                    f"/api/search?projectId={quote(self.config.project_id, safe='')}&keyword={quote(document_id, safe='')}",
                    {document_id},
                )
            )
        knowledge_file_id = discovered.get("knowledge-file")
        if knowledge_file_id:
            aggregate_cases.append(
                (
                    "knowledge-files",
                    f"/api/knowledge/project-files?projectId={quote(self.config.project_id, safe='')}&page=1&pageSize=200",
                    {knowledge_file_id},
                )
            )
        knowledge_task_id = discovered.get("knowledge-task")
        if knowledge_task_id:
            aggregate_cases.append(
                ("knowledge-tasks", "/api/knowledge/tasks?page=1&pageSize=200", {knowledge_task_id})
            )
        failures = []
        if not aggregate_cases:
            failures.append("no known-existing aggregate-scope targets")
        for label, path, forbidden_ids in aggregate_cases:
            status_code, payload = self.request_json(self.api, "GET", path, headers=headers)
            data = self.envelope_data(f"auth.aggregate-scope.{label}", status_code, payload)
            if data is None:
                failures.append(f"{label}: bad envelope")
                continue
            items = data.get("items") if isinstance(data, dict) else data
            if not isinstance(items, list):
                failures.append(f"{label}: expected list/items payload")
                continue
            returned_ids = {str(item.get("id") or item.get("runId")) for item in items if isinstance(item, dict)}
            leaked = sorted(forbidden_ids & returned_ids)
            if leaked:
                failures.append(f"{label}: leaked {', '.join(leaked)}")
        if failures:
            self.add("auth.aggregate-scope", "fail", "; ".join(failures))
            return
        self.add("auth.aggregate-scope", "pass", "Known-existing out-of-scope resources are absent from aggregate lists.")

    def check_ocr_health(self) -> None:
        if self.official_ocr_mode():
            services = self.api_health.get("serviceReadiness") or {}
            ocr = services.get("ocr") if isinstance(services, dict) else {}
            failures = []
            if ocr.get("configured") is not True:
                failures.append("official OCR must be configured")
            if ocr.get("providerMode") != "official":
                failures.append("providerMode must be official")
            if ocr.get("localHeavyFallbackEnabled") is not False:
                failures.append("local heavy fallback must be disabled")
            if ocr.get("silentFallbackEnabled") is not False:
                failures.append("silent provider fallback must be disabled")
            self.add(
                "ocr.health",
                "fail" if failures else "pass",
                "; ".join(failures) if failures else "Official OCR runtime configuration is healthy.",
                ocr,
            )
            return
        if self.config.skip_ocr or self.ocr is None:
            self.add("ocr.health", "skip", "OCR check disabled.")
            return
        try:
            status_code, payload = self.request_json(self.ocr, "GET", "/healthz")
        except Exception as exc:
            self.add("ocr.health", "fail", str(exc))
            return
        data = self.envelope_data("ocr.health", status_code, payload)
        if data is None:
            return
        fields = {"pipelineAvailable", "pipelineBackend", "placeholderAllowed"}
        missing = sorted(fields - set(data))
        strict_failures = []
        if self.config.strict_production:
            if data.get("pipelineAvailable") is not True:
                strict_failures.append("pipelineAvailable must be true")
            if data.get("placeholderAllowed") is not False:
                strict_failures.append("placeholderAllowed must be false")
            if data.get("offlineOnly") is not True:
                strict_failures.append("offlineOnly must be true")
            if data.get("networkDisabled") is not True:
                strict_failures.append("networkDisabled must be true")
        failures = [f"Missing fields: {', '.join(missing)}"] if missing else []
        failures.extend(strict_failures)
        self.add(
            "ocr.health",
            "fail" if failures else "pass",
            "; ".join(failures) if failures else "OCR health flags are present.",
            data,
        )

    def check_ocr_readyz(self) -> None:
        if self.official_ocr_mode():
            services = self.api_health.get("serviceReadiness") or {}
            ocr = services.get("ocr") if isinstance(services, dict) else {}
            circuit = ocr.get("circuitBreaker") if isinstance(ocr, dict) else {}
            capacity = ocr.get("capacityControl") if isinstance(ocr, dict) else {}
            failures = []
            if not isinstance(capacity, dict) or capacity.get("ready") is not True:
                failures.append("distributed OCR capacity control is not ready")
            if isinstance(circuit, dict) and circuit.get("open") is True:
                failures.append("official OCR circuit is open")
            if self.config.ocr_object_probe and not self.official_ocr_probe_passed:
                failures.append("queued official OCR object probe did not pass")
            self.add(
                "ocr.readyz",
                "fail" if failures else "pass",
                "; ".join(failures) if failures else "Official OCR capacity, circuit, and live probe are ready.",
                {"capacityControl": capacity, "circuitBreaker": circuit},
            )
            return
        if self.config.skip_ocr or self.ocr is None:
            self.add("ocr.readyz", "skip", "OCR check disabled.")
            return
        try:
            status_code, payload = self.request_json(self.ocr, "GET", "/readyz")
        except Exception as exc:
            self.add("ocr.readyz", "fail", str(exc))
            return
        data = self.envelope_data("ocr.readyz", status_code, payload)
        if data is None:
            return
        failures = []
        if data.get("ready") is not True:
            failures.append("ready must be true")
        if self.config.strict_production:
            if data.get("placeholderAllowed") is not False:
                failures.append("placeholderAllowed must be false")
            if data.get("offlineOnly") is not True:
                failures.append("offlineOnly must be true")
            if data.get("networkDisabled") is not True:
                failures.append("networkDisabled must be true")
            model_manifest = data.get("modelManifest") if isinstance(data, dict) else None
            model_dirs = model_manifest.get("modelDirs") if isinstance(model_manifest, dict) else {}
            if not model_dirs or any(not item.get("exists") for item in model_dirs.values() if isinstance(item, dict)):
                failures.append("all local OCR model directories must exist")
        self.add(
            "ocr.readyz",
            "fail" if failures else "pass",
            "; ".join(failures) if failures else "OCR readyz confirms local model readiness.",
            data,
        )

    def check_ocr_runtime_doctor(self) -> None:
        if self.official_ocr_mode():
            services = self.api_health.get("serviceReadiness") or {}
            ocr = services.get("ocr") if isinstance(services, dict) else {}
            capacity = ocr.get("capacityControl") if isinstance(ocr, dict) else {}
            failures = []
            if not isinstance(capacity, dict) or capacity.get("distributed") is not True:
                failures.append("official OCR must use distributed control")
            if ocr.get("formalReadinessProfileAllowlist") not in ([], None):
                failures.append("formal readiness allowlist must stay empty before certification")
            self.add(
                "ocr.runtime-doctor",
                "fail" if failures else "pass",
                "; ".join(failures) if failures else "Official OCR control policies pass.",
                ocr,
            )
            return
        if self.config.skip_ocr or self.ocr is None:
            self.add("ocr.runtime-doctor", "skip", "OCR check disabled.")
            return
        try:
            status_code, payload = self.request_json(self.ocr, "GET", "/internal/ocr/doctor")
        except Exception as exc:
            self.add("ocr.runtime-doctor", "fail", str(exc))
            return
        data = self.envelope_data("ocr.runtime-doctor", status_code, payload)
        if data is None:
            return
        failures = []
        if data.get("schemaVersion") != "aicheck-ocr-runtime-doctor-v1":
            failures.append("schemaVersion must be aicheck-ocr-runtime-doctor-v1")
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        checks = data.get("checks") if isinstance(data.get("checks"), list) else []
        if not summary or not checks:
            failures.append("doctor summary/checks must be present")
        failed_checks = [item for item in checks if isinstance(item, dict) and item.get("status") == "fail"]
        if self.config.strict_production and failed_checks:
            failures.append("runtime doctor has failed checks: " + ", ".join(str(item.get("name")) for item in failed_checks[:8]))
        self.add(
            "ocr.runtime-doctor",
            "fail" if failures else "pass",
            "; ".join(failures) if failures else "OCR runtime doctor confirms package/model/preprocess readiness.",
            data,
        )

    def check_ocr_parse_contract(self) -> None:
        if self.official_ocr_mode():
            if self.config.ocr_object_probe and self.official_ocr_probe_passed:
                self.add("ocr.parse-contract", "pass", "Queued official OCR object probe validated the parse contract.")
            else:
                self.add("ocr.parse-contract", "fail", "Official OCR parse contract requires --write-probes --ocr-object-probe.")
            return
        if self.config.skip_ocr or self.ocr is None:
            self.add("ocr.parse-contract", "skip", "OCR check disabled.")
            return
        try:
            status_code, payload = self.request_json(
                self.ocr,
                "POST",
                "/internal/ocr/parse",
                json={"storageKey": "__deployment_verify_missing__.pdf", "fileName": "__deployment_verify_missing__.pdf"},
            )
        except Exception as exc:
            self.add("ocr.parse-contract", "fail", str(exc))
            return
        data = self.envelope_data("ocr.parse-contract", status_code, payload)
        if data is None:
            return
        required = {"storageKey", "status", "fragments", "fields", "diagnostics"}
        missing = sorted(required - set(data))
        valid_status = data.get("status") in {"success", "failed"}
        list_fields = all(isinstance(data.get(key), list) for key in ["fragments", "fields", "diagnostics"])
        if missing or not valid_status or not list_fields:
            self.add("ocr.parse-contract", "fail", f"Unexpected OCR parse payload: {data}", data)
            return
        self.add("ocr.parse-contract", "pass", f"OCR parse contract returned status={data.get('status')}.", data)

    def check_ocr_bad_request_contract(self) -> None:
        if self.official_ocr_mode():
            status_code, payload = self.request_json(
                self.api,
                "POST",
                f"/api/projects/{self.config.project_id}/documents/upload-session",
                headers=self.auth_headers("contractor"),
                json={},
            )
            reason = payload.get("data", {}).get("reason") if isinstance(payload, dict) else None
            if status_code in {400, 422} or reason == "VALIDATION_ERROR":
                self.add("ocr.bad-request", "pass", "Malformed official OCR upload requests are rejected.")
            else:
                self.add("ocr.bad-request", "fail", f"Expected validation failure, got HTTP {status_code}.")
            return
        if self.config.skip_ocr or self.ocr is None:
            self.add("ocr.bad-request", "skip", "OCR check disabled.")
            return
        try:
            status_code, payload = self.request_json(self.ocr, "POST", "/internal/ocr/parse", json={})
        except Exception as exc:
            self.add("ocr.bad-request", "fail", str(exc))
            return
        if status_code == 200 and isinstance(payload, dict) and payload.get("data", {}).get("reason") == "VALIDATION_ERROR":
            self.add("ocr.bad-request", "pass", "Malformed OCR parse requests return VALIDATION_ERROR.")
            return
        self.add("ocr.bad-request", "fail", f"Expected VALIDATION_ERROR, got {payload}")

    def litellm_headers(self) -> dict[str, str]:
        if not self.config.litellm_api_key:
            return {}
        return {"Authorization": f"Bearer {self.config.litellm_api_key}"}

    def check_litellm_health(self) -> None:
        if self.config.skip_litellm or self.litellm is None:
            self.add("litellm.health", "skip", "LiteLLM check disabled.")
            return
        headers = self.litellm_headers()
        try:
            response = self.litellm.get("/health/liveliness", headers=headers)
            if response.status_code == 404:
                response = self.litellm.get("/health", headers=headers)
        except Exception as exc:
            self.add("litellm.health", "fail", str(exc))
            return
        if response.status_code >= 400:
            self.add("litellm.health", "fail", f"HTTP {response.status_code}")
        else:
            health_data: dict[str, Any] | None = None
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                unhealthy_count = payload.get("unhealthy_count")
                unhealthy_endpoints = payload.get("unhealthy_endpoints")
                unhealthy_models = []
                if isinstance(unhealthy_endpoints, list):
                    unhealthy_models = sorted(
                        {
                            str(item.get("model"))
                            for item in unhealthy_endpoints
                            if isinstance(item, dict) and item.get("model")
                        }
                    )
                health_data = {
                    "healthyCount": payload.get("healthy_count"),
                    "unhealthyCount": unhealthy_count,
                    "unhealthyModels": unhealthy_models,
                }
                if isinstance(unhealthy_count, int) and unhealthy_count > 0:
                    self.add(
                        "litellm.health",
                        "fail",
                        f"HTTP {response.status_code}; LiteLLM reports {unhealthy_count} unhealthy endpoint(s).",
                        health_data,
                    )
                else:
                    self.add("litellm.health", "pass", f"HTTP {response.status_code}", health_data)
            else:
                self.add("litellm.health", "pass", f"HTTP {response.status_code}")
        if not self.config.litellm_api_key:
            self.add("litellm.models", "fail", "LITELLM_API_KEY is required for /v1/models.")
            return
        try:
            models = self.litellm.get("/v1/models", headers=headers)
        except Exception as exc:
            self.add("litellm.models", "fail", str(exc))
            return
        if models.status_code >= 400:
            self.add("litellm.models", "fail", f"HTTP {models.status_code}")
            return
        self.add("litellm.models", "pass", f"HTTP {models.status_code}")
        try:
            payload = models.json()
        except Exception as exc:
            self.add("litellm.aliases", "fail", f"/v1/models returned non-JSON payload: {exc}")
            return
        model_ids = {
            str(item.get("id") or item.get("model_name") or item.get("model") or "")
            for item in payload.get("data", [])
            if isinstance(item, dict)
        }
        missing = sorted(REQUIRED_LITELLM_ALIASES - model_ids)
        aliases_ok = not missing
        self.add(
            "litellm.aliases",
            "fail" if missing else "pass",
            f"Missing model aliases: {', '.join(missing)}" if missing else "Required model aliases are available.",
            {"modelIds": sorted(model_ids)},
        )
        if not aliases_ok:
            return
        self.check_litellm_management_probes(headers)
        self.check_litellm_provider_probes(headers)

    def check_litellm_management_probes(self, headers: dict[str, str]) -> None:
        if not self.config.litellm_management_probes:
            self.add(
                "litellm.management-probes",
                "skip",
                "Pass --litellm-management-probes to verify DB-backed virtual key, budget, and rate-limit management.",
            )
            return
        if not self.config.litellm_api_key:
            self.add("litellm.management-probes", "fail", "LITELLM_API_KEY is required for key management probes.")
            return
        key_alias = f"aicheck-deploy-verify-{uuid.uuid4().hex[:10]}"
        requested = {
            "models": ["default-chat", "embedding-default"],
            "key_alias": key_alias,
            "duration": "30m",
            "max_budget": 0.01,
            "rpm_limit": 1,
            "tpm_limit": 256,
            "metadata": {"purpose": "aicheck-deployment-verifier"},
        }
        generated_key = ""
        try:
            response = self.litellm.post("/key/generate", headers=headers, json=requested)
        except Exception as exc:
            self.add("litellm.management-probes", "fail", str(exc))
            return
        if response.status_code >= 400:
            self.add(
                "litellm.management-probes",
                "fail",
                f"/key/generate HTTP {response.status_code}",
                self.safe_response_error_data(response),
            )
            return
        try:
            payload = response.json()
        except Exception as exc:
            self.add("litellm.management-probes", "fail", f"/key/generate returned non-JSON payload: {exc}")
            return
        if not isinstance(payload, dict):
            self.add("litellm.management-probes", "fail", "/key/generate returned non-object JSON payload.")
            return
        generated_key = str(payload.get("key") or payload.get("token") or "")
        if not generated_key:
            self.add("litellm.management-probes", "fail", "/key/generate returned no virtual key.")
            return
        delete_payload = {"key_aliases": [key_alias]}
        try:
            delete_response = self.litellm.post("/key/delete", headers=headers, json=delete_payload)
        except Exception as exc:
            self.add("litellm.management-probes", "fail", f"Temporary key was created but cleanup failed: {exc}")
            return
        if delete_response.status_code >= 400:
            self.add(
                "litellm.management-probes",
                "fail",
                f"Temporary key was created but /key/delete returned HTTP {delete_response.status_code}",
                self.safe_response_error_data(delete_response),
            )
            return
        self.add(
            "litellm.management-probes",
            "pass",
            "Created and deleted a temporary LiteLLM virtual key with budget and rate-limit settings.",
            {
                "keyAlias": key_alias,
                "models": requested["models"],
                "maxBudget": requested["max_budget"],
                "rpmLimit": requested["rpm_limit"],
                "tpmLimit": requested["tpm_limit"],
                "keyCreated": bool(generated_key),
                "keyDeleted": True,
            },
        )

    def safe_response_error_data(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        error = payload.get("error")
        if isinstance(error, dict):
            return {"error": error}
        if isinstance(error, str):
            return {"error": error}
        return {"response": payload}

    def check_litellm_provider_probes(self, headers: dict[str, str]) -> None:
        if not self.config.litellm_provider_probes:
            self.add("litellm.provider-probes", "skip", "Pass --litellm-provider-probes to verify real chat and embedding calls.")
            return
        self.check_litellm_chat_probe(headers)
        self.check_litellm_embedding_probe(headers)

    def check_litellm_chat_probe(self, headers: dict[str, str]) -> None:
        try:
            response = self.litellm.post(
                "/v1/chat/completions",
                headers=headers,
                json={
                    "model": "default-chat",
                    "messages": [
                        {"role": "system", "content": "You are a deployment verifier. Reply briefly."},
                        {"role": "user", "content": "Reply with: AIcheck verifier ok"},
                    ],
                    # Reasoning models can consume a small output budget entirely
                    # on hidden reasoning and return no visible assistant content.
                    "max_tokens": 128,
                    "temperature": 0,
                },
            )
        except Exception as exc:
            self.add("litellm.chat-probe", "fail", str(exc))
            return
        if response.status_code >= 400:
            self.add("litellm.chat-probe", "fail", f"HTTP {response.status_code}")
            return
        try:
            payload = response.json()
        except Exception as exc:
            self.add("litellm.chat-probe", "fail", f"Non-JSON response: {exc}")
            return
        choices = payload.get("choices") if isinstance(payload, dict) else None
        message = choices[0].get("message", {}) if isinstance(choices, list) and choices else {}
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            self.add("litellm.chat-probe", "fail", "Chat completion returned no assistant content.")
            return
        self.add("litellm.chat-probe", "pass", "default-chat returned assistant content.", {"model": "default-chat"})

    def check_litellm_embedding_probe(self, headers: dict[str, str]) -> None:
        try:
            response = self.litellm.post(
                "/v1/embeddings",
                headers=headers,
                json={"model": "embedding-default", "input": "AIcheck deployment verifier"},
            )
        except Exception as exc:
            self.add("litellm.embedding-probe", "fail", str(exc))
            return
        if response.status_code >= 400:
            self.add("litellm.embedding-probe", "fail", f"HTTP {response.status_code}")
            return
        try:
            payload = response.json()
        except Exception as exc:
            self.add("litellm.embedding-probe", "fail", f"Non-JSON response: {exc}")
            return
        data = payload.get("data") if isinstance(payload, dict) else None
        embedding = data[0].get("embedding") if isinstance(data, list) and data else None
        if not isinstance(embedding, list) or not embedding:
            self.add("litellm.embedding-probe", "fail", "Embedding response returned no vector.")
            return
        self.add(
            "litellm.embedding-probe",
            "pass",
            f"embedding-default returned vector dimension={len(embedding)}.",
            {"model": "embedding-default", "dimension": len(embedding)},
        )

    def check_qwen_official_probe(self) -> None:
        if not self.config.qwen_official_probe:
            self.add("qwen.official-probe", "skip", "Pass --qwen-official-probe to verify the official Qwen API.")
            return
        runtime = qwen_runtime_config()
        official = runtime.get("officialProvider") or {}
        base_url = str(os.getenv(str(official.get("baseUrlEnv") or "QWEN_API_BASE")) or official.get("defaultBaseUrl") or "").rstrip("/")
        api_key_env = str(official.get("apiKeyEnv") or "QWEN_API_KEY")
        api_key = os.getenv(api_key_env)
        model = str(((official.get("models") or {}).get("default")) or "qwen3.7-plus")
        if not base_url:
            self.add("qwen.official-probe", "fail", "Qwen official API base URL is not configured.")
            return
        if not api_key:
            self.add("qwen.official-probe", "fail", f"{api_key_env} is required for Qwen official API probe.")
            return
        try:
            response = httpx.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a deployment verifier. Reply briefly."},
                        {"role": "user", "content": "Reply with: AIcheck Qwen verifier ok"},
                    ],
                    "max_tokens": 128,
                    "temperature": 0,
                },
                timeout=15,
            )
        except Exception as exc:
            self.add("qwen.official-probe", "fail", str(exc), {"model": model, "baseUrl": base_url})
            return
        if response.status_code >= 400:
            self.add(
                "qwen.official-probe",
                "fail",
                f"HTTP {response.status_code}",
                self.safe_response_error_data(response),
            )
            return
        try:
            payload = response.json()
        except Exception as exc:
            self.add("qwen.official-probe", "fail", f"Non-JSON response: {exc}")
            return
        choices = payload.get("choices") if isinstance(payload, dict) else None
        message = choices[0].get("message", {}) if isinstance(choices, list) and choices else {}
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            self.add("qwen.official-probe", "fail", "Qwen official API returned no assistant content.")
            return
        self.add("qwen.official-probe", "pass", "Qwen official API returned assistant content.", {"model": model, "baseUrl": base_url})


def print_results(results: list[CheckResult], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"ok": all(item.ok or item.status == "skip" for item in results), "checks": [asdict(item) for item in results]}, ensure_ascii=False, indent=2))
        return
    for item in results:
        suffix = f" - {item.detail}" if item.detail else ""
        print(f"[{item.status.upper()}] {item.name}{suffix}")


def main() -> int:
    args = parse_args()
    config = config_from_args(args)
    with httpx.Client(base_url=config.api_base, timeout=args.timeout) as api_client:
        ocr_client = None
        litellm_client = None
        storage_client = httpx.Client(timeout=args.timeout)
        if config.ocr_base:
            ocr_client = httpx.Client(base_url=config.ocr_base, timeout=args.timeout)
        if config.litellm_base:
            litellm_client = httpx.Client(base_url=config.litellm_base, timeout=args.timeout)
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
            if ocr_client:
                ocr_client.close()
            if litellm_client:
                litellm_client.close()
            storage_client.close()
    print_results(results, as_json=args.json)
    return 0 if all(item.ok or item.status == "skip" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
