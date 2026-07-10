from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.verify_deployment import REQUIRED_LITELLM_ALIASES
from libs.embedding_models import EMBEDDING_DEFAULT_ALIAS, allowed_embedding_model_ids, embedding_runtime_config


REQUIRED_SERVICES = {
    "api-service",
    "worker-service",
    "review-worker-service",
    "workflow-migrate",
    "ocr-service",
    "embedding-service",
    "redis",
    "minio",
    "postgres",
    "litellm-service",
    "temporal-service",
    "temporal-ui",
}
REQUIRED_WORKER_QUEUES = {
    "ocr.parse_document",
    "ocr.recognize_seals",
    "knowledge.slice",
    "knowledge.embed",
    "inspection.ai_recheck",
    "llm.compare",
    "export.package",
}
REQUIRED_VOLUMES = {"minio-data", "postgres-data"}
REQUIRED_HEALTHCHECKS = {
    "api-service": "8000/healthz",
    "worker-service": "celery",
    "review-worker-service": "temporalio.client",
    "ocr-service": "8010/readyz",
    "embedding-service": "7997/health",
    "postgres": "pg_isready",
    "redis": "redis-cli",
    "minio": "mc ready",
    "litellm-service": "4000/health",
    "temporal-service": "cluster health",
}


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""
    data: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"pass", "warn"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate AIcheck deployment config without Docker.")
    parser.add_argument("--compose-file", default="docker-compose.yml")
    parser.add_argument("--dockerfile", default="Dockerfile")
    parser.add_argument("--ocr-dockerfile", default="Dockerfile.ocr")
    parser.add_argument("--ocr-requirements", default="requirements-ocr.txt")
    parser.add_argument("--litellm-config", default="config/litellm.yaml")
    parser.add_argument("--strict-production", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


class DeploymentConfigValidator:
    def __init__(
        self,
        compose_file: Path,
        litellm_config: Path,
        *,
        dockerfile: Path | None = None,
        ocr_dockerfile: Path | None = None,
        ocr_requirements: Path | None = None,
        strict_production: bool = False,
    ) -> None:
        self.compose_file = compose_file
        self.litellm_config = litellm_config
        self.dockerfile = dockerfile or compose_file.parent / "Dockerfile"
        self.ocr_dockerfile = ocr_dockerfile or compose_file.parent / "Dockerfile.ocr"
        self.ocr_requirements = ocr_requirements or compose_file.parent / "requirements-ocr.txt"
        self.strict_production = strict_production
        self.results: list[CheckResult] = []
        self.compose: dict[str, Any] = {}
        self.litellm: dict[str, Any] = {}
        self.dockerfile_text = ""
        self.ocr_dockerfile_text = ""
        self.ocr_requirements_text = ""

    def run(self) -> list[CheckResult]:
        self.load_files()
        if self.dockerfile_text:
            self.check_dockerfile()
        if self.ocr_requirements_text:
            self.check_ocr_requirements()
        if self.ocr_dockerfile_text:
            self.check_ocr_dockerfile()
        if self.compose:
            self.check_services()
            self.check_service_dependencies()
            self.check_commands_and_ports()
            self.check_healthchecks()
            self.check_environment()
            self.check_ocr_runtime_artifacts()
            self.check_runtime_assets()
            self.check_volumes()
        if self.litellm:
            self.check_litellm_config()
        return self.results

    def add(self, name: str, status: str, detail: str = "", data: dict[str, Any] | None = None) -> None:
        if status == "warn" and self.strict_production:
            status = "fail"
        self.results.append(CheckResult(name=name, status=status, detail=detail, data=data))

    def load_files(self) -> None:
        for label, path in [("compose.load", self.compose_file), ("litellm.load", self.litellm_config)]:
            if not path.exists():
                self.add(label, "fail", f"File not found: {path}")
                continue
            try:
                loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception as exc:
                self.add(label, "fail", f"YAML parse failed: {exc}")
                continue
            if not isinstance(loaded, dict):
                self.add(label, "fail", f"Top-level YAML must be a mapping: {path}")
                continue
            if label == "compose.load":
                self.compose = loaded
            else:
                self.litellm = loaded
            self.add(label, "pass", str(path))
        if not self.dockerfile.exists():
            self.add("dockerfile.load", "fail", f"File not found: {self.dockerfile}")
            return
        try:
            self.dockerfile_text = self.dockerfile.read_text(encoding="utf-8")
        except Exception as exc:
            self.add("dockerfile.load", "fail", f"Dockerfile read failed: {exc}")
            return
        if not self.dockerfile_text.strip():
            self.add("dockerfile.load", "fail", f"Dockerfile is empty: {self.dockerfile}")
            return
        self.add("dockerfile.load", "pass", str(self.dockerfile))
        self.ocr_dockerfile_text = read_text_file(self.ocr_dockerfile, "dockerfile.ocr-load", self)
        self.ocr_requirements_text = read_text_file(self.ocr_requirements, "requirements.ocr-load", self)

    def services(self) -> dict[str, Any]:
        services = self.compose.get("services") or {}
        return services if isinstance(services, dict) else {}

    def service(self, name: str) -> dict[str, Any]:
        service = self.services().get(name) or {}
        return service if isinstance(service, dict) else {}

    def check_services(self) -> None:
        services = set(self.services())
        missing = sorted(REQUIRED_SERVICES - services)
        extra = sorted(services - REQUIRED_SERVICES)
        self.add(
            "compose.services",
            "fail" if missing else "pass",
            f"Missing services: {', '.join(missing)}" if missing else "Required services are declared.",
            {"services": sorted(services), "extra": extra},
        )

    def check_dockerfile(self) -> None:
        text = self.dockerfile_text
        failures = []
        if not re.search(r"^FROM\s+python:3\.12-slim\b", text, flags=re.MULTILINE):
            failures.append("Dockerfile must use python:3.12-slim base image")
        if "COPY requirements.txt" not in text:
            failures.append("Dockerfile must copy requirements.txt before application code")
        if "pip install" not in text or "-r requirements.txt" not in text:
            failures.append("Dockerfile must install requirements.txt")
        if "COPY . ." not in text:
            failures.append("Dockerfile must copy application source")
        user_match = re.search(r"^USER\s+(.+)$", text, flags=re.MULTILINE)
        if not user_match:
            failures.append("Dockerfile must switch to a non-root runtime user")
        elif user_match.group(1).strip().lower() in {"root", "0"}:
            failures.append("Dockerfile runtime user must not be root")
        if "useradd" not in text and "adduser" not in text:
            failures.append("Dockerfile must create an explicit runtime user")
        exposed_ports: set[str] = set()
        for line in re.findall(r"^EXPOSE\s+(.+)$", text, flags=re.MULTILINE):
            exposed_ports.update(part.split("/")[0] for part in line.split())
        missing_ports = sorted({"8000", "8010"} - exposed_ports)
        if missing_ports:
            failures.append(f"Dockerfile must expose API/OCR ports: {', '.join(missing_ports)}")
        self.add(
            "dockerfile.build-contract",
            "fail" if failures else "pass",
            "; ".join(failures) if failures else "Backend image installs dependencies, runs non-root, and exposes API/OCR ports.",
        )

    def check_ocr_requirements(self) -> None:
        required = {
            "PyMuPDF",
            "paddlepaddle",
            "paddleocr",
            "paddlex[ocr]",
            "opencv-python-headless",
            "docling",
            "transformers",
        }
        present = {
            line.split("==", 1)[0].split(">=", 1)[0].split("<", 1)[0].strip()
            for line in self.ocr_requirements_text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        missing = sorted(required - present)
        self.add(
            "requirements.ocr-baseline",
            "fail" if missing else "pass",
            f"Missing OCR packages: {', '.join(missing)}" if missing else "OCR dependency baseline includes PaddleOCR, PaddleX, PyMuPDF, OpenCV, Docling, and Transformers.",
            {"packages": sorted(present)},
        )

    def check_ocr_dockerfile(self) -> None:
        text = self.ocr_dockerfile_text
        failures = []
        if not re.search(r"^FROM\s+python:3\.12-slim\b", text, flags=re.MULTILINE):
            failures.append("Dockerfile.ocr must use python:3.12-slim base image")
        if "COPY requirements.txt requirements-ocr.txt" not in text:
            failures.append("Dockerfile.ocr must copy base and OCR requirements together")
        if "pip install" not in text or "-r requirements.txt" not in text or "-r requirements-ocr.txt" not in text:
            failures.append("Dockerfile.ocr must install base and OCR requirements")
        for arg in (
            "AICHECK_APT_DEBIAN_MIRROR",
            "AICHECK_APT_SECURITY_MIRROR",
            "AICHECK_PIP_INDEX_URL",
        ):
            if f"ARG {arg}" not in text:
                failures.append(f"Dockerfile.ocr must expose build arg {arg}")
        if "pip config set global.index-url" not in text:
            failures.append("Dockerfile.ocr must support configurable pip index for offline-friendly builds")
        for package in ("libgomp1", "libglib2.0-0"):
            if package not in text:
                failures.append(f"Dockerfile.ocr must install system package {package}")
        if "COPY . ." not in text:
            failures.append("Dockerfile.ocr must copy application source")
        user_match = re.search(r"^USER\s+(.+)$", text, flags=re.MULTILINE)
        if not user_match:
            failures.append("Dockerfile.ocr must switch to a non-root runtime user")
        elif user_match.group(1).strip().lower() in {"root", "0"}:
            failures.append("Dockerfile.ocr runtime user must not be root")
        if "useradd" not in text and "adduser" not in text:
            failures.append("Dockerfile.ocr must create an explicit runtime user")
        exposed_ports: set[str] = set()
        for line in re.findall(r"^EXPOSE\s+(.+)$", text, flags=re.MULTILINE):
            exposed_ports.update(part.split("/")[0] for part in line.split())
        if "8010" not in exposed_ports:
            failures.append("Dockerfile.ocr must expose OCR port 8010")
        self.add(
            "dockerfile.ocr-build-contract",
            "fail" if failures else "pass",
            "; ".join(failures) if failures else "OCR image installs PaddleOCR baseline dependencies and runs non-root.",
        )

    def check_service_dependencies(self) -> None:
        expected = {
            "api-service": {"workflow-migrate", "postgres", "redis", "minio", "litellm-service", "temporal-service", "ocr-service", "embedding-service"},
            "worker-service": {"postgres", "redis", "api-service", "minio", "ocr-service", "litellm-service"},
            "review-worker-service": {"workflow-migrate", "postgres", "temporal-service", "litellm-service"},
            "workflow-migrate": {"postgres"},
            "ocr-service": {"minio"},
            "litellm-service": {"postgres", "embedding-service"},
            "temporal-service": {"postgres"},
            "temporal-ui": {"temporal-service"},
        }
        failures = []
        for name, required in expected.items():
            declared = depends_on_services(self.service(name).get("depends_on"))
            missing = sorted(required - declared)
            if missing:
                failures.append(f"{name}: missing {', '.join(missing)}")
        healthy_dependencies = {
            "api-service": {"postgres", "redis", "minio", "litellm-service", "temporal-service", "ocr-service", "embedding-service"},
            "worker-service": {"postgres", "redis", "api-service", "minio", "ocr-service", "litellm-service"},
            "review-worker-service": {"postgres", "temporal-service", "litellm-service"},
            "ocr-service": {"minio"},
            "litellm-service": {"postgres", "embedding-service"},
            "temporal-service": {"postgres"},
            "temporal-ui": {"temporal-service"},
        }
        for service_name, dependencies in healthy_dependencies.items():
            for dependency in dependencies:
                if depends_on_condition(self.service(service_name).get("depends_on"), dependency) != "service_healthy":
                    failures.append(f"{service_name}: {dependency} must use condition=service_healthy")
        for service_name in ("api-service", "review-worker-service"):
            if depends_on_condition(self.service(service_name).get("depends_on"), "workflow-migrate") != "service_completed_successfully":
                failures.append(
                    f"{service_name}: workflow-migrate must use condition=service_completed_successfully"
                )
        self.add(
            "compose.depends-on",
            "fail" if failures else "pass",
            "; ".join(failures) if failures else "Service dependencies cover database, queue, object storage, OCR, and LiteLLM.",
        )

    def check_commands_and_ports(self) -> None:
        failures = []
        api_command = command_text(self.service("api-service").get("command"))
        worker_command = command_text(self.service("worker-service").get("command"))
        review_worker_command = command_text(self.service("review-worker-service").get("command"))
        ocr_command = command_text(self.service("ocr-service").get("command"))
        litellm_command = command_text(self.service("litellm-service").get("command"))
        embedding_command = command_text(self.service("embedding-service").get("command"))
        workflow_migrate_command = command_text(self.service("workflow-migrate").get("command"))
        embedding_env = self.service("embedding-service").get("environment") or {}
        if "uvicorn apps.api.main:app" not in api_command or "--port 8000" not in api_command:
            failures.append("api-service command must run FastAPI on port 8000")
        if "celery" not in worker_command or "apps.worker.celery_app.celery_app" not in worker_command:
            failures.append("worker-service command must run Celery app")
        if "python -m apps.review_worker.main" not in review_worker_command:
            failures.append("review-worker-service command must run the Temporal ReviewRun worker")
        if "python -m scripts.setup_langgraph_checkpoint" not in workflow_migrate_command:
            failures.append("workflow-migrate must run the LangGraph checkpoint schema setup")
        queue_list = set(re.split(r"[, ]+", worker_command))
        missing_queues = sorted(REQUIRED_WORKER_QUEUES - queue_list)
        if missing_queues:
            failures.append(f"worker-service missing queues: {', '.join(missing_queues)}")
        if "uvicorn apps.ocr_service.main:app" not in ocr_command or "--port 8010" not in ocr_command:
            failures.append("ocr-service command must run OCR API on port 8010")
        if "litellm.yaml" not in litellm_command or "--port 4000" not in litellm_command:
            failures.append("litellm-service command must load config/litellm.yaml on port 4000")
        if "uvicorn apps.embedding_service.main:app" not in embedding_command or "7997" not in embedding_command:
            failures.append("embedding-service command must run local embedding API on port 7997")
        if "AICHECK_EMBEDDING_MODEL_ID" not in embedding_env:
            failures.append("embedding-service must read AICHECK_EMBEDDING_MODEL_ID from environment")
        if str(embedding_env.get("AICHECK_EMBEDDING_SERVED_MODEL_NAME") or "") and EMBEDDING_DEFAULT_ALIAS not in str(
            embedding_env.get("AICHECK_EMBEDDING_SERVED_MODEL_NAME")
        ):
            failures.append("embedding-service must expose the stable embedding-default served model name")
        if "--api-key" in embedding_command:
            failures.append("embedding-service must read INFINITY_API_KEY from environment instead of exposing it in the process command")
        port_expectations = {
            "api-service": ("127.0.0.1:8000:8000",),
            "ocr-service": ("127.0.0.1:8010:8010",),
            "embedding-service": ("127.0.0.1:7997:7997",),
            "minio": ("127.0.0.1:9000:9000",),
            "litellm-service": ("127.0.0.1:4001:4000",),
            "postgres": ("127.0.0.1:5432:5432", "127.0.0.1:${AICHECK_POSTGRES_HOST_PORT:-15432}:5432"),
            "temporal-service": ("127.0.0.1:7233:7233",),
            "temporal-ui": ("127.0.0.1:8088:8080",),
        }
        for service_name, expected_ports in port_expectations.items():
            ports = normalize_ports(self.service(service_name).get("ports"))
            if not any(expected_port in ports for expected_port in expected_ports):
                failures.append(f"{service_name} missing port mapping {' or '.join(expected_ports)}")
        self.add(
            "compose.commands-ports",
            "fail" if failures else "pass",
            "; ".join(failures) if failures else "Commands, queues, PostgreSQL service, and public ports are valid.",
        )

    def check_healthchecks(self) -> None:
        failures = []
        for service_name, expected_marker in REQUIRED_HEALTHCHECKS.items():
            healthcheck = self.service(service_name).get("healthcheck")
            if not isinstance(healthcheck, dict):
                failures.append(f"{service_name}: missing healthcheck")
                continue
            test = command_text(healthcheck.get("test"))
            if expected_marker not in test:
                failures.append(f"{service_name}: healthcheck must contain {expected_marker!r}")
            if service_name == "litellm-service":
                if "Authorization" not in test or "LITELLM_MASTER_KEY" not in test:
                    failures.append("litellm-service: healthcheck must authenticate with LITELLM_MASTER_KEY")
                if "unhealthy_count" not in test:
                    failures.append("litellm-service: healthcheck must fail when LiteLLM reports unhealthy providers")
            for key in ("interval", "timeout", "retries"):
                if key not in healthcheck:
                    failures.append(f"{service_name}: healthcheck missing {key}")
        self.add(
            "compose.healthchecks",
            "fail" if failures else "pass",
            "; ".join(failures) if failures else "Core services declare production healthchecks.",
        )

    def check_environment(self) -> None:
        failures = []
        warnings = []
        required_env = {
            "api-service": {
                "AICHECK_DATABASE_URL",
                "AICHECK_REDIS_URL",
                "AICHECK_TASK_DISPATCH",
                "AICHECK_REVIEW_ORCHESTRATION",
                "AICHECK_AUDIT_INPUT_MODE",
                "TEMPORAL_ADDRESS",
                "TEMPORAL_NAMESPACE",
                "AICHECK_REVIEW_WORKFLOW_TASK_QUEUE",
                "AICHECK_REVIEW_LLM_EXECUTION",
                "AICHECK_LANGGRAPH_DISABLE",
                "AICHECK_LANGGRAPH_CHECKPOINT_DISABLE",
                "AICHECK_LANGGRAPH_CHECKPOINT_SETUP",
                "LANGGRAPH_CHECKPOINT_DSN",
                "AICHECK_MINIO_ENDPOINT",
                "AICHECK_JWT_SECRET",
                "AICHECK_JWT_ISSUER",
                "AICHECK_JWT_AUDIENCE",
                "AICHECK_JWT_TTL_MINUTES",
                "AICHECK_STRICT_PRODUCTION",
                "AICHECK_ALLOW_DEV_TOKENS",
                "AICHECK_ENABLE_COMPATIBILITY_MOCKS",
                "AICHECK_CORS_ALLOWED_ORIGINS",
                "AICHECK_ALLOWED_HOSTS",
                "AICHECK_REQUIRE_AUTH",
                "AICHECK_ENABLE_DEMO_USERS",
                "LITELLM_BASE_URL",
                "LITELLM_API_KEY",
                "AICHECK_QWEN_CALL_MODE",
                "AICHECK_QWEN_ALLOW_SERVER_FALLBACK",
                "QWEN_API_BASE",
                "QWEN_API_KEY",
                "AICHECK_OCR_BASE_URL",
                "AICHECK_EMBEDDING_PROVIDER",
                "AICHECK_EMBEDDING_API_BASE",
            },
            "worker-service": {
                "AICHECK_STRICT_PRODUCTION",
                "AICHECK_DATABASE_URL",
                "AICHECK_REDIS_URL",
                "AICHECK_TASK_DISPATCH",
                "AICHECK_REVIEW_ORCHESTRATION",
                "AICHECK_AUDIT_INPUT_MODE",
                "AICHECK_OCR_BASE_URL",
                "LITELLM_BASE_URL",
                "LITELLM_API_KEY",
                "AICHECK_QWEN_CALL_MODE",
                "AICHECK_QWEN_ALLOW_SERVER_FALLBACK",
                "QWEN_API_BASE",
                "QWEN_API_KEY",
            },
            "review-worker-service": {
                "AICHECK_STRICT_PRODUCTION",
                "AICHECK_DATABASE_URL",
                "AICHECK_REVIEW_ORCHESTRATION",
                "AICHECK_AUDIT_INPUT_MODE",
                "TEMPORAL_ADDRESS",
                "TEMPORAL_NAMESPACE",
                "AICHECK_REVIEW_WORKFLOW_TASK_QUEUE",
                "AICHECK_REVIEW_GRAPH_TASK_QUEUE",
                "AICHECK_REVIEW_LLM_TASK_QUEUE",
                "AICHECK_REVIEW_RETRIEVAL_TASK_QUEUE",
                "AICHECK_REVIEW_VALIDATION_TASK_QUEUE",
                "AICHECK_REVIEW_LLM_EXECUTION",
                "AICHECK_LANGGRAPH_DISABLE",
                "AICHECK_LANGGRAPH_CHECKPOINT_DISABLE",
                "AICHECK_LANGGRAPH_CHECKPOINT_SETUP",
                "LANGGRAPH_CHECKPOINT_DSN",
                "LITELLM_BASE_URL",
                "LITELLM_API_KEY",
                "AICHECK_QWEN_CALL_MODE",
                "AICHECK_QWEN_ALLOW_SERVER_FALLBACK",
                "QWEN_API_BASE",
                "QWEN_API_KEY",
            },
            "workflow-migrate": {
                "LANGGRAPH_CHECKPOINT_DSN",
            },
            "ocr-service": {
                "AICHECK_AGENTDESIGN_BACKEND",
                "AICHECK_OCR_ALLOW_PLACEHOLDER",
                "AICHECK_OCR_OFFLINE_ONLY",
                "AICHECK_OCR_DISABLE_NETWORK",
                "PADDLEOCR_MODEL_DIR",
                "PADDLEX_MODEL_DIR",
                "PADDLEOCR_VL_MODEL_DIR",
                "DOCLING_ARTIFACTS_PATH",
            },
            "litellm-service": {
                "DATABASE_URL",
                "LITELLM_MASTER_KEY",
                "DEEPSEEK_API_KEY",
                "INFINITY_API_KEY",
                "AICHECK_LITELLM_STRICT_PROVIDER_HEALTH",
                "NO_PROXY",
                "no_proxy",
            },
            "embedding-service": {
                "DO_NOT_TRACK",
                "HF_HOME",
                "HF_ENDPOINT",
                "TRANSFORMERS_CACHE",
                "INFINITY_API_KEY",
                "AICHECK_EMBEDDING_MODEL_ID",
                "AICHECK_EMBEDDING_SERVED_MODEL_NAME",
                "AICHECK_EMBEDDING_ENGINE",
            },
            "postgres": {
                "POSTGRES_DB",
                "POSTGRES_USER",
                "POSTGRES_PASSWORD",
                "LITELLM_POSTGRES_DB",
                "WORKFLOW_POSTGRES_DB",
            },
            "temporal-service": {
                "DB",
                "POSTGRES_USER",
                "POSTGRES_PWD",
                "POSTGRES_SEEDS",
            },
            "temporal-ui": {
                "TEMPORAL_ADDRESS",
            },
        }
        for service_name, keys in required_env.items():
            env = environment_map(self.service(service_name).get("environment"))
            missing = sorted(keys - set(env))
            if missing:
                failures.append(f"{service_name}: missing {', '.join(missing)}")
        api_env = environment_map(self.service("api-service").get("environment"))
        worker_env = environment_map(self.service("worker-service").get("environment"))
        review_worker_env = environment_map(self.service("review-worker-service").get("environment"))
        ocr_env = environment_map(self.service("ocr-service").get("environment"))
        if default_value(api_env.get("AICHECK_REQUIRE_AUTH")) != "true":
            failures.append("api-service default AICHECK_REQUIRE_AUTH must be true")
        if default_value(api_env.get("AICHECK_ENABLE_DEMO_USERS")) != "false":
            failures.append("api-service default AICHECK_ENABLE_DEMO_USERS must be false")
        if default_value(api_env.get("AICHECK_STRICT_PRODUCTION")) != "true":
            failures.append("api-service default AICHECK_STRICT_PRODUCTION must be true")
        if default_value(api_env.get("AICHECK_ALLOW_DEV_TOKENS")) != "false":
            failures.append("api-service default AICHECK_ALLOW_DEV_TOKENS must be false")
        if default_value(api_env.get("AICHECK_ENABLE_COMPATIBILITY_MOCKS")) != "false":
            failures.append("api-service default AICHECK_ENABLE_COMPATIBILITY_MOCKS must be false")
        if default_value(worker_env.get("AICHECK_STRICT_PRODUCTION")) != "true":
            failures.append("worker-service default AICHECK_STRICT_PRODUCTION must be true")
        if default_value(review_worker_env.get("AICHECK_STRICT_PRODUCTION")) != "true":
            failures.append("review-worker-service default AICHECK_STRICT_PRODUCTION must be true")
        if "*" in default_value(api_env.get("AICHECK_CORS_ALLOWED_ORIGINS")):
            failures.append("api-service AICHECK_CORS_ALLOWED_ORIGINS must not contain wildcard")
        if "*" in default_value(api_env.get("AICHECK_ALLOWED_HOSTS")):
            failures.append("api-service AICHECK_ALLOWED_HOSTS must not contain wildcard")
        if "postgres:5432" not in default_value(api_env.get("AICHECK_DATABASE_URL")):
            failures.append("api-service AICHECK_DATABASE_URL must target postgres:5432")
        if default_value(worker_env.get("AICHECK_TASK_DISPATCH")) != "celery":
            failures.append("worker-service default AICHECK_TASK_DISPATCH must be celery")
        if default_value(api_env.get("AICHECK_REVIEW_ORCHESTRATION")) != "temporal":
            failures.append("api-service default AICHECK_REVIEW_ORCHESTRATION must be temporal")
        if default_value(review_worker_env.get("AICHECK_REVIEW_ORCHESTRATION")) != "temporal":
            failures.append("review-worker-service AICHECK_REVIEW_ORCHESTRATION must be temporal")
        if default_value(review_worker_env.get("AICHECK_REVIEW_LLM_EXECUTION")) != "litellm":
            failures.append("review-worker-service default AICHECK_REVIEW_LLM_EXECUTION must be litellm")
        if default_value(api_env.get("AICHECK_AUDIT_INPUT_MODE")) != "ocr_llm":
            failures.append("api-service default AICHECK_AUDIT_INPUT_MODE must be ocr_llm")
        if default_value(worker_env.get("AICHECK_AUDIT_INPUT_MODE")) != "ocr_llm":
            failures.append("worker-service default AICHECK_AUDIT_INPUT_MODE must be ocr_llm")
        if default_value(review_worker_env.get("AICHECK_AUDIT_INPUT_MODE")) != "ocr_llm":
            failures.append("review-worker-service default AICHECK_AUDIT_INPUT_MODE must be ocr_llm")
        if default_value(review_worker_env.get("AICHECK_LANGGRAPH_DISABLE")) != "false":
            failures.append("review-worker-service default AICHECK_LANGGRAPH_DISABLE must be false")
        if "postgres:5432" not in default_value(api_env.get("LANGGRAPH_CHECKPOINT_DSN")):
            failures.append("api-service LANGGRAPH_CHECKPOINT_DSN must target postgres:5432")
        if "postgres:5432" not in default_value(review_worker_env.get("LANGGRAPH_CHECKPOINT_DSN")):
            failures.append("review-worker-service LANGGRAPH_CHECKPOINT_DSN must target postgres:5432")
        if default_value(ocr_env.get("AICHECK_OCR_ALLOW_PLACEHOLDER")) != "false":
            failures.append("ocr-service default AICHECK_OCR_ALLOW_PLACEHOLDER must be false")
        if default_value(ocr_env.get("AICHECK_OCR_OFFLINE_ONLY")) != "true":
            failures.append("ocr-service default AICHECK_OCR_OFFLINE_ONLY must be true")
        if default_value(ocr_env.get("AICHECK_OCR_DISABLE_NETWORK")) != "true":
            failures.append("ocr-service default AICHECK_OCR_DISABLE_NETWORK must be true")
        litellm_env = environment_map(self.service("litellm-service").get("environment"))
        litellm_image = str(self.service("litellm-service").get("image") or "")
        if not re.search(r"ghcr\.io/berriai/litellm:[^}\s]+@sha256:[a-f0-9]{64}", litellm_image):
            failures.append("litellm-service image must be pinned to a release tag and sha256 digest")
        proxy_failures = litellm_proxy_bypass_failures(litellm_env)
        failures.extend(proxy_failures)
        weak_markers = {
            "AICHECK_JWT_SECRET": "change-me",
            "AICHECK_MINIO_SECRET_KEY": "dev-password",
            "LITELLM_API_KEY": "sk-aicheck-dev",
            "AICHECK_POSTGRES_PASSWORD": "aicheck",
            "DEEPSEEK_API_KEY": "",
        }
        for service_name in ["api-service", "worker-service", "review-worker-service", "litellm-service", "postgres", "temporal-service"]:
            env = environment_map(self.service(service_name).get("environment"))
            for key, weak in weak_markers.items():
                value = env.get(key)
                if value is None:
                    continue
                fallback = default_value(value)
                if fallback == weak or (weak and weak in fallback):
                    warnings.append(f"{service_name}: {key} has weak/default fallback")
        if failures:
            self.add("compose.environment", "fail", "; ".join(failures))
            return
        self.add(
            "compose.environment",
            "warn" if warnings else "pass",
            "; ".join(warnings) if warnings else "Required service environment and production-safe defaults are present.",
        )

    def check_runtime_assets(self) -> None:
        backend_root_candidates = [
            self.litellm_config.parent.parent,
            self.dockerfile.parent,
            Path(__file__).resolve().parents[1],
            self.compose_file.parent,
        ]
        backend_root = next(
            (
                candidate
                for candidate in backend_root_candidates
                if (candidate / "config" / "material_review_points.json").is_file()
            ),
            self.compose_file.parent,
        )
        asset_path = backend_root / "config" / "material_review_points.json"
        failures = []
        payload: dict[str, Any] = {}
        if not asset_path.exists():
            failures.append(f"material review asset missing: {asset_path}")
        else:
            try:
                payload = json.loads(asset_path.read_text(encoding="utf-8"))
            except Exception as exc:
                failures.append(f"material review asset invalid: {exc}")
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        if len(items) != 151:
            failures.append(f"material review asset must contain 151 items, got {len(items)}")
        if not payload.get("sourceSha256"):
            failures.append("material review asset must record sourceSha256")
        if payload.get("itemCount") != len(items):
            failures.append("material review asset itemCount does not match items")
        source_name = str(payload.get("source") or "").strip()
        source_path = backend_root.parent / source_name if source_name else None
        if source_path and source_path.is_file():
            actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
            if actual_hash != payload.get("sourceSha256"):
                failures.append("material review asset sourceSha256 does not match the mapping document")
        self.add(
            "runtime.material-review-asset",
            "fail" if failures else "pass",
            "; ".join(failures) if failures else "Versioned material review asset contains 151 items.",
            {"itemCount": len(items), "version": payload.get("version")},
        )

    def check_ocr_runtime_artifacts(self) -> None:
        failures = []
        ocr_service = self.service("ocr-service")
        build = ocr_service.get("build") or {}
        if not isinstance(build, dict) or str(build.get("dockerfile") or "") != "Dockerfile.ocr":
            failures.append("ocr-service must build from Dockerfile.ocr")
        build_args = build.get("args") if isinstance(build, dict) else {}
        if not isinstance(build_args, dict):
            failures.append("ocr-service build args must be a mapping")
        else:
            for arg in (
                "AICHECK_APT_DEBIAN_MIRROR",
                "AICHECK_APT_SECURITY_MIRROR",
                "AICHECK_PIP_INDEX_URL",
            ):
                if arg not in build_args:
                    failures.append(f"ocr-service build must pass {arg}")
        ocr_env = environment_map(ocr_service.get("environment"))
        backend_path = default_value(ocr_env.get("AICHECK_AGENTDESIGN_BACKEND"))
        if backend_path != "/opt/agentdesign/mvp-system/backend":
            failures.append("ocr-service AICHECK_AGENTDESIGN_BACKEND must default to /opt/agentdesign/mvp-system/backend")
        volumes = normalize_volumes(ocr_service.get("volumes"))
        if not any(volume_targets_path(volume, "/opt/agentdesign") for volume in volumes):
            failures.append("ocr-service must mount optional AICHECK_AGENTDESIGN_HOST_PATH fallback to /opt/agentdesign:ro")
        if not any(volume_targets_path(volume, "/models") for volume in volumes):
            failures.append("ocr-service must mount AICHECK_OCR_MODELS_HOST_PATH to /models:ro")
        if any(str(volume).startswith("${AICHECK_AGENTDESIGN_HOST_PATH:?") for volume in volumes):
            failures.append("ocr-service agentdesign mount must be optional unless AICHECK_ENABLE_AGENTDESIGN_SEAL_OCR is enabled")
        if not any(str(volume).startswith("${AICHECK_OCR_MODELS_HOST_PATH:?") for volume in volumes):
            failures.append("ocr-service model mount must require AICHECK_OCR_MODELS_HOST_PATH")
        if not any(volume.endswith(":/opt/agentdesign:ro") or ":/opt/agentdesign:ro," in volume for volume in volumes):
            failures.append("ocr-service agentdesign mount must be read-only")
        if not any(volume.endswith(":/models:ro") or ":/models:ro," in volume for volume in volumes):
            failures.append("ocr-service model mount must be read-only")
        self.add(
            "compose.ocr-artifacts",
            "fail" if failures else "pass",
            "; ".join(failures)
            if failures
            else "OCR service requires local model artifacts and mounts OCR artifacts read-only.",
            {"backendPath": backend_path, "volumes": sorted(volumes)},
        )

    def check_volumes(self) -> None:
        volumes = self.compose.get("volumes") or {}
        declared = set(volumes) if isinstance(volumes, dict) else set()
        missing = sorted(REQUIRED_VOLUMES - declared)
        self.add(
            "compose.volumes",
            "fail" if missing else "pass",
            f"Missing volumes: {', '.join(missing)}" if missing else "Persistent data volumes are declared.",
        )

    def check_litellm_config(self) -> None:
        model_list = self.litellm.get("model_list") or []
        if not isinstance(model_list, list):
            self.add("litellm.model-list", "fail", "model_list must be a list.")
            return
        aliases = {str(item.get("model_name")) for item in model_list if isinstance(item, dict)}
        missing = sorted(REQUIRED_LITELLM_ALIASES - aliases)
        failures = []
        for item in model_list:
            if not isinstance(item, dict):
                failures.append("model_list contains a non-object item")
                continue
            name = item.get("model_name")
            params = item.get("litellm_params") or {}
            if not isinstance(params, dict) or not params.get("model") or not params.get("api_key"):
                failures.append(f"{name}: missing litellm_params.model/api_key")
                continue
            if name == "embedding-default":
                runtime = embedding_runtime_config({})
                if str(params.get("model") or "") != runtime["litellmModel"]:
                    failures.append("embedding-default must use the stable local Infinity served-model alias")
                if str(params.get("api_base") or "") != "http://embedding-service:7997":
                    failures.append("embedding-default api_base must target embedding-service:7997")
                if str(params.get("api_key") or "") != "os.environ/INFINITY_API_KEY":
                    failures.append("embedding-default api_key must read os.environ/INFINITY_API_KEY")
                info = item.get("model_info") or {}
                if str(info.get("default_model_id") or "") not in allowed_embedding_model_ids():
                    failures.append("embedding-default model_info.default_model_id must be a registered embedding model")
                if info.get("hot_swappable") is not True:
                    failures.append("embedding-default model_info.hot_swappable must be true")
        settings = self.litellm.get("general_settings") or {}
        if settings.get("master_key") != "os.environ/LITELLM_MASTER_KEY":
            failures.append("general_settings.master_key must read os.environ/LITELLM_MASTER_KEY")
        if settings.get("database_url") != "os.environ/DATABASE_URL":
            failures.append("general_settings.database_url must read os.environ/DATABASE_URL")
        if settings.get("store_model_in_db") is not True:
            failures.append("general_settings.store_model_in_db must be true")
        if missing:
            failures.append(f"missing aliases: {', '.join(missing)}")
        self.add(
            "litellm.config",
            "fail" if failures else "pass",
            "; ".join(failures) if failures else "LiteLLM aliases, provider params, master key, and database settings are valid.",
            {"aliases": sorted(aliases)},
        )


def depends_on_services(raw: Any) -> set[str]:
    if isinstance(raw, dict):
        return set(raw)
    if isinstance(raw, list):
        return {str(item) for item in raw}
    return set()


def depends_on_condition(raw: Any, service_name: str) -> str | None:
    if isinstance(raw, dict):
        value = raw.get(service_name)
        if isinstance(value, dict):
            return str(value.get("condition") or "")
        if value is not None:
            return "service_started"
    if isinstance(raw, list) and service_name in {str(item) for item in raw}:
        return "service_started"
    return None


def command_text(raw: Any) -> str:
    if isinstance(raw, list):
        return " ".join(str(item) for item in raw)
    return str(raw or "")


def normalize_ports(raw: Any) -> set[str]:
    if not isinstance(raw, list):
        return set()
    return {str(item).strip('"') for item in raw}


def read_text_file(path: Path, label: str, validator: DeploymentConfigValidator) -> str:
    if not path.exists():
        validator.add(label, "fail", f"File not found: {path}")
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        validator.add(label, "fail", f"File read failed: {exc}")
        return ""
    if not text.strip():
        validator.add(label, "fail", f"File is empty: {path}")
        return ""
    validator.add(label, "pass", str(path))
    return text


def normalize_volumes(raw: Any) -> set[str]:
    if not isinstance(raw, list):
        return set()
    result = set()
    for item in raw:
        if isinstance(item, dict):
            source = item.get("source") or item.get("src") or ""
            target = item.get("target") or item.get("dst") or item.get("destination") or ""
            mode = item.get("read_only")
            suffix = ":ro" if mode is True else ""
            result.add(f"{source}:{target}{suffix}")
        else:
            result.add(str(item).strip('"'))
    return result


def volume_targets_path(volume: str, target_path: str) -> bool:
    marker = f":{target_path}"
    return volume.endswith(marker) or f"{marker}:" in volume


def environment_map(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    if isinstance(raw, list):
        result = {}
        for item in raw:
            key, _, value = str(item).partition("=")
            if key:
                result[key] = value
        return result
    return {}


def default_value(value: str | None) -> str:
    if not value:
        return ""
    match = re.match(r"\$\{[^:}]+:-(.*)\}$", value)
    return match.group(1) if match else value


def litellm_proxy_bypass_failures(env: dict[str, str]) -> list[str]:
    failures: list[str] = []
    required_markers = {"127.0.0.1", "localhost"}
    for key in ("NO_PROXY", "no_proxy"):
        raw_value = env.get(key)
        effective_value = default_value(raw_value)
        tokens = {
            token.strip()
            for token in re.split(r"[, ]+", effective_value)
            if token.strip()
        }
        missing = sorted(required_markers - tokens)
        if missing:
            failures.append(
                f"litellm-service: {key} must include {', '.join(missing)} "
                "so Prisma query-engine localhost health probes bypass HTTP proxies"
            )
    return failures


def print_results(results: list[CheckResult], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"ok": all(item.ok for item in results), "checks": [asdict(item) for item in results]}, ensure_ascii=False, indent=2))
        return
    for item in results:
        suffix = f" - {item.detail}" if item.detail else ""
        print(f"[{item.status.upper()}] {item.name}{suffix}")


def main() -> int:
    args = parse_args()
    validator = DeploymentConfigValidator(
        Path(args.compose_file),
        Path(args.litellm_config),
        dockerfile=Path(args.dockerfile),
        ocr_dockerfile=Path(args.ocr_dockerfile),
        ocr_requirements=Path(args.ocr_requirements),
        strict_production=args.strict_production,
    )
    results = validator.run()
    print_results(results, as_json=args.json)
    return 0 if all(item.ok for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
