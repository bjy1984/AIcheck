from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libs.db.seed import PROJECT_ID
from libs.security.auth import ROLE_DEFAULT_PATHS


DEFAULT_ROLES = ("admin", "inspection", "contractor", "ndt", "owner")
REQUIRED_LITELLM_ALIASES = {"default-chat", "review-chat", "embedding-default", "compare-fast"}
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
    litellm_provider_probes: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AIcheck deployment from the outside.")
    parser.add_argument("--api-base", default=os.getenv("AICHECK_API_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--ocr-base", default=os.getenv("AICHECK_VERIFY_OCR_BASE_URL", "http://127.0.0.1:8010"))
    parser.add_argument("--litellm-base", default=os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:4001"))
    parser.add_argument("--litellm-api-key", default=os.getenv("LITELLM_API_KEY"))
    parser.add_argument("--project-id", default=os.getenv("AICHECK_DEFAULT_PROJECT_ID", PROJECT_ID))
    parser.add_argument("--roles", default=",".join(DEFAULT_ROLES), help="Comma-separated login roles to verify.")
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
        "--write-probes",
        action="store_true",
        help="Run signed PUT upload, signed GET preview/download, OCR task, and export write probes against the target project.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--timeout", type=float, default=8.0)
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
    return VerifyConfig(
        api_base=args.api_base.rstrip("/"),
        ocr_base=None if args.skip_ocr else (args.ocr_base or "").rstrip("/"),
        litellm_base=None if args.skip_litellm else (args.litellm_base or "").rstrip("/"),
        litellm_api_key=args.litellm_api_key,
        project_id=args.project_id,
        roles=roles,
        strict_production=args.strict_production,
        skip_ocr=args.skip_ocr,
        skip_litellm=args.skip_litellm,
        write_probes=args.write_probes,
        ocr_object_probe=args.ocr_object_probe,
        litellm_provider_probes=args.litellm_provider_probes,
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

    def run(self) -> list[CheckResult]:
        self.check_api_health()
        self.check_strict_production_flags()
        self.check_auth_gate()
        self.check_role_logins()
        self.check_mongo_transaction_probe()
        self.check_admin_reads_rejected()
        self.check_project_and_task_reads()
        self.check_write_probes()
        self.check_identity_spoof_rejected()
        self.check_action_bypass_rejected()
        self.check_read_scope_rejected()
        self.check_ocr_health()
        self.check_ocr_parse_contract()
        self.check_ocr_bad_request_contract()
        self.check_litellm_health()
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
        response = client.request(method, path, **kwargs)
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
        required = {"service", "authRequired", "demoUsersEnabled", "mongoEnabled", "objectStorageEnabled"}
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
            "mongoEnabled": True,
            "mongoTransactions": True,
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
            status_code, payload = self.request_json(
                self.api,
                "POST",
                "/api/auth/login",
                json={"username": role, "password": role},
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

    def check_mongo_transaction_probe(self) -> None:
        if not self.config.strict_production and not self.api_health.get("mongoTransactions"):
            self.add("mongo.transaction-probe", "skip", "MongoDB transactions are disabled.")
            return
        status_code, payload = self.request_json(
            self.api,
            "GET",
            "/api/system/mongo-transaction-probe",
            headers=self.auth_headers("admin"),
        )
        data = self.envelope_data("mongo.transaction-probe", status_code, payload)
        if data is None:
            return
        failures = []
        if self.config.strict_production:
            if data.get("mongoEnabled") is not True:
                failures.append("mongoEnabled must be true")
            if data.get("transactionsConfigured") is not True:
                failures.append("transactionsConfigured must be true")
            if data.get("transactionProbe") != "pass":
                failures.append(f"transactionProbe must be pass, got {data.get('transactionProbe')!r}")
        elif data.get("transactionsConfigured") and data.get("transactionProbe") == "failed":
            failures.append("transaction probe failed")
        if failures:
            self.add("mongo.transaction-probe", "fail", "; ".join(failures), data)
            return
        status = "pass" if data.get("transactionProbe") == "pass" else "skip"
        detail = "MongoDB transaction probe passed." if status == "pass" else str(data.get("reason") or "MongoDB transaction probe skipped.")
        self.add("mongo.transaction-probe", status, detail, data)

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

        export_headers = self.auth_headers("inspection")
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
            if not self.check_signed_get_url(f"api.write-probes.document-{label}-get", data):
                return False
        return True

    def check_signed_get_url(self, name: str, payload: dict[str, Any]) -> bool:
        url = str(payload.get("url") or "")
        parsed = urlparse(url)
        if payload.get("method") != "GET":
            self.add(name, "fail", f"Expected method GET, got {payload.get('method')!r}.")
            return False
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

    def check_read_scope_rejected(self) -> None:
        if not self.api_health.get("authRequired") or "contractor" not in self.tokens:
            self.add("auth.read-scope", "skip", "Auth is disabled or contractor token is unavailable.")
            return
        headers = {"Authorization": f"Bearer {self.tokens['contractor']}"}
        forbidden_cases = [
            ("node-package", f"/api/projects/{self.config.project_id}/nodes/40/package"),
            ("role-query", f"/api/projects/{self.config.project_id}/workbench/context?role=inspection"),
            ("document-detail", f"/api/projects/{self.config.project_id}/documents/DOC-20260625-004"),
            ("knowledge-file", "/api/knowledge/files/KF-DOC-20260625-004"),
        ]
        failures = []
        for label, path in forbidden_cases:
            status_code, payload = self.request_json(self.api, "GET", path, headers=headers)
            if not (status_code == 200 and isinstance(payload, dict) and payload.get("data", {}).get("reason") == "FORBIDDEN"):
                failures.append(f"{label}: {payload}")
        if failures:
            self.add("auth.read-scope", "fail", "; ".join(failures))
            return
        self.add("auth.read-scope", "pass", "Out-of-scope direct reads and role-query spoofing are rejected.")
        self.check_aggregate_scope(headers)

    def check_aggregate_scope(self, headers: dict[str, str]) -> None:
        aggregate_cases = [
            ("search", f"/api/search?projectId={self.config.project_id}&keyword=RT", {"DOC-20260625-004"}),
            ("knowledge-files", f"/api/knowledge/project-files?projectId={self.config.project_id}", {"KF-DOC-20260625-004"}),
            ("knowledge-tasks", "/api/knowledge/tasks", {"KT-20260626-001"}),
        ]
        failures = []
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
        self.add("auth.aggregate-scope", "pass", "Out-of-scope demo resources are absent from aggregate lists.")

    def check_ocr_health(self) -> None:
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
        failures = [f"Missing fields: {', '.join(missing)}"] if missing else []
        failures.extend(strict_failures)
        self.add(
            "ocr.health",
            "fail" if failures else "pass",
            "; ".join(failures) if failures else "OCR health flags are present.",
            data,
        )

    def check_ocr_parse_contract(self) -> None:
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

    def check_litellm_health(self) -> None:
        if self.config.skip_litellm or self.litellm is None:
            self.add("litellm.health", "skip", "LiteLLM check disabled.")
            return
        try:
            response = self.litellm.get("/health")
        except Exception as exc:
            self.add("litellm.health", "fail", str(exc))
            return
        self.add("litellm.health", "pass" if response.status_code < 400 else "fail", f"HTTP {response.status_code}")
        if not self.config.litellm_api_key:
            self.add("litellm.models", "fail", "LITELLM_API_KEY is required for /v1/models.")
            return
        headers = {"Authorization": f"Bearer {self.config.litellm_api_key}"} if self.config.litellm_api_key else {}
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
        self.check_litellm_provider_probes(headers)

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
                    "max_tokens": 16,
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
