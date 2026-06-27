from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libs.db.seed import PROJECT_ID
from libs.security.auth import ROLE_DEFAULT_PATHS


DEFAULT_ROLES = ("admin", "inspection", "contractor", "ndt", "owner")


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
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--timeout", type=float, default=8.0)
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> VerifyConfig:
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
    )


class DeploymentVerifier:
    def __init__(
        self,
        config: VerifyConfig,
        *,
        api_client: httpx.Client,
        ocr_client: httpx.Client | None = None,
        litellm_client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.api = api_client
        self.ocr = ocr_client
        self.litellm = litellm_client
        self.results: list[CheckResult] = []
        self.api_health: dict[str, Any] = {}
        self.tokens: dict[str, str] = {}

    def run(self) -> list[CheckResult]:
        self.check_api_health()
        self.check_strict_production_flags()
        self.check_auth_gate()
        self.check_role_logins()
        self.check_admin_reads_rejected()
        self.check_project_and_task_reads()
        self.check_identity_spoof_rejected()
        self.check_action_bypass_rejected()
        self.check_read_scope_rejected()
        self.check_ocr_health()
        self.check_litellm_health()
        return self.results

    def add(self, name: str, status: str, detail: str = "", data: dict[str, Any] | None = None) -> None:
        self.results.append(CheckResult(name=name, status=status, detail=detail, data=data))

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
        self.add(
            "ocr.health",
            "fail" if missing else "pass",
            f"Missing fields: {', '.join(missing)}" if missing else "OCR health flags are present.",
            data,
        )

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
        self.add("litellm.models", "pass" if models.status_code < 400 else "fail", f"HTTP {models.status_code}")


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
            )
            results = verifier.run()
        finally:
            if ocr_client:
                ocr_client.close()
            if litellm_client:
                litellm_client.close()
    print_results(results, as_json=args.json)
    return 0 if all(item.ok or item.status == "skip" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
