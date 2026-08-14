from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env"
REQUIRED_ENV = {
    "AICHECK_OCR_MODELS_HOST_PATH": "local OCR model artifact directory",
    "AICHECK_MINIO_SECRET_KEY": "MinIO root password and signing secret",
    "AICHECK_JWT_SECRET": "JWT signing secret",
    "LITELLM_API_KEY": "LiteLLM master key used by API/worker probes",
    "AICHECK_POSTGRES_PASSWORD": "Unified PostgreSQL password for AIcheck, LiteLLM, Temporal, and LangGraph",
    "AICHECK_DATABASE_URL": "AIcheck business PostgreSQL connection URL",
    "DEEPSEEK_API_KEY": "DeepSeek provider key consumed by LiteLLM review-chat/deepseek-reasoner",
}
PRODUCTION_FLAG_DEFAULTS = {
    "AICHECK_REQUIRE_AUTH": "true",
    "AICHECK_ENABLE_DEMO_USERS": "false",
    "AICHECK_OCR_ALLOW_PLACEHOLDER": "false",
    "AICHECK_OCR_OFFLINE_ONLY": "true",
    "AICHECK_OCR_DISABLE_NETWORK": "true",
    "AICHECK_REVIEW_ORCHESTRATION": "temporal",
}
HOST_PORTS = {
    8000: "api-service",
    8010: "ocr-service",
    4001: "litellm-service",
    9000: "minio-api",
    9001: "minio-console",
    6379: "redis",
    5432: "postgres",
    7233: "temporal-service",
    8088: "temporal-ui",
}
PLACEHOLDER_MARKERS = ("replace-with", "change-me", "placeholder", "example", "sk-aicheck-dev")
SECRET_STRENGTH_RULES = {
    "AICHECK_MINIO_SECRET_KEY": {
        "min_length": 16,
        "min_unique": 8,
        "description": "MinIO secret key",
    },
    "AICHECK_JWT_SECRET": {
        "min_length": 32,
        "min_unique": 12,
        "description": "JWT signing secret",
    },
    "LITELLM_API_KEY": {
        "min_length": 16,
        "min_unique": 8,
        "description": "LiteLLM master key",
    },
    "AICHECK_POSTGRES_PASSWORD": {
        "min_length": 16,
        "min_unique": 8,
        "description": "Unified PostgreSQL password",
    },
}
OCR_BUNDLED_MODEL_DIRS = ("paddleocr", "paddlex", "paddleocr-vl", "docling")
OCR_FLAT_MODEL_DIRS = {
    "AICHECK_PADDLEOCR_DET_MODEL_DIR": ("PP-OCRv6_medium_det",),
    "AICHECK_PADDLEOCR_REC_MODEL_DIR": ("PP-OCRv6_medium_rec",),
    "AICHECK_PPSTRUCTURE_LAYOUT_MODEL_DIR": ("PP-DocLayout-L",),
    "AICHECK_PPSTRUCTURE_WIRED_TABLE_STRUCTURE_MODEL_DIR": ("SLANeXt_wired",),
    "AICHECK_PPSTRUCTURE_WIRED_TABLE_CELLS_MODEL_DIR": ("RT-DETR-L_wired_table_cell_det",),
    "AICHECK_PPSTRUCTURE_WIRELESS_TABLE_STRUCTURE_MODEL_DIR": ("SLANeXt_wireless",),
    "AICHECK_PPSTRUCTURE_WIRELESS_TABLE_CELLS_MODEL_DIR": ("RT-DETR-L_wireless_table_cell_det",),
    "AICHECK_SEAL_DET_MODEL_DIR": ("PP-OCRv4_server_seal_det",),
    "AICHECK_SEAL_REC_MODEL_DIR": ("PP-OCRv4_server_rec",),
    "AICHECK_PADDLEOCR_VL_LAYOUT_MODEL_DIR": ("PP-DocLayoutV3",),
    "AICHECK_PADDLEOCR_VL_REC_MODEL_DIR": ("PaddleOCR-VL-1.6-0.9B", "PaddleOCR-VL-1.6"),
    "AICHECK_PADDLEOCR_VL_DOC_ORI_MODEL_DIR": ("PP-LCNet_x1_0_doc_ori",),
    "AICHECK_PADDLEOCR_VL_DOC_UNWARP_MODEL_DIR": ("UVDoc",),
}


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""
    data: dict[str, object] | None = None
    remediation: list[str] | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"pass", "warn"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check local prerequisites before running the 96+ live probes."
    )
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--strict-production", action="store_true")
    parser.add_argument(
        "--require-ports-free",
        action="store_true",
        help=(
            "Fail when default host ports are already open. By default open ports are warnings "
            "because the stack may already be running."
        ),
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def effective_env(env_file: Path, process_env: Mapping[str, str] | None = None) -> dict[str, str]:
    merged = parse_env_file(env_file)
    merged.update(dict(process_env if process_env is not None else os.environ))
    return merged


def is_placeholder(value: str | None) -> bool:
    if value is None or not value.strip():
        return True
    lower_value = value.strip().lower()
    return any(marker in lower_value for marker in PLACEHOLDER_MARKERS)


def env_bool(values: Mapping[str, str], name: str, default: bool = False) -> bool:
    value = values.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def secret_strength_issues(value: str | None, *, min_length: int, min_unique: int) -> list[str]:
    text = value or ""
    issues: list[str] = []
    if len(text) < min_length:
        issues.append(f"length<{min_length}")
    if len(set(text)) < min_unique:
        issues.append(f"unique_chars<{min_unique}")
    return issues


def tcp_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


class PreflightChecker:
    def __init__(
        self,
        *,
        env_file: Path = DEFAULT_ENV_FILE,
        strict_production: bool = False,
        require_ports_free: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.env_file = env_file
        self.strict_production = strict_production
        self.require_ports_free = require_ports_free
        self.env = effective_env(env_file, env)
        self.results: list[CheckResult] = []

    def run(self) -> list[CheckResult]:
        self.check_docker()
        self.check_env_file()
        self.check_required_env()
        self.check_secret_strength()
        self.check_production_flags()
        self.check_agentdesign()
        self.check_ocr_models()
        self.check_ports()
        self.check_live_probe_command()
        return self.results

    def add(
        self,
        name: str,
        status: str,
        detail: str = "",
        data: dict[str, object] | None = None,
        remediation: list[str] | None = None,
    ) -> None:
        self.results.append(
            CheckResult(
                name=name,
                status=status,
                detail=detail,
                data=data,
                remediation=remediation,
            )
        )

    def check_docker(self) -> None:
        docker = shutil.which("docker")
        if not docker:
            self.add(
                "runtime.docker",
                "fail",
                "docker CLI was not found on PATH.",
                remediation=[
                    "Install Docker Desktop or Docker Engine on the deployment host.",
                    "Verify `docker --version` succeeds in the same shell used for deployment.",
                ],
            )
            self.add(
                "runtime.compose",
                "fail",
                "docker compose cannot be checked without docker CLI.",
                remediation=[
                    "Install the Docker Compose v2 plugin with Docker.",
                    "Verify `docker compose version` succeeds before running live probes.",
                ],
            )
            return

        version = self.run_command([docker, "--version"])
        self.add(
            "runtime.docker",
            "pass" if version[0] else "fail",
            version[1],
            remediation=None
            if version[0]
            else ["Fix the Docker installation until `docker --version` exits with code 0."],
        )

        compose = self.run_command([docker, "compose", "version"])
        self.add(
            "runtime.compose",
            "pass" if compose[0] else "fail",
            compose[1],
            remediation=None
            if compose[0]
            else ["Install or repair Docker Compose v2 until `docker compose version` passes."],
        )

    def run_command(self, command: list[str]) -> tuple[bool, str]:
        try:
            completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=8)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)
        output = (completed.stdout or completed.stderr or "").strip()
        return completed.returncode == 0, output

    def check_env_file(self) -> None:
        if self.env_file.exists():
            self.add("env.file", "pass", f"{self.env_file} exists.")
        else:
            self.add(
                "env.file",
                "fail",
                f"{self.env_file} is missing. Copy backend/.env.example and replace placeholders.",
                remediation=[
                    "Run `cd backend && cp .env.example .env`.",
                    "Replace every `replace-with-*` value in backend/.env with production secrets.",
                ],
            )

    def check_required_env(self) -> None:
        missing = sorted(key for key in REQUIRED_ENV if not self.env.get(key))
        placeholders = sorted(key for key in REQUIRED_ENV if is_placeholder(self.env.get(key)))
        if missing:
            self.add(
                "env.required",
                "fail",
                "Missing required variables: " + ", ".join(missing),
                {
                    "missing": missing,
                    "required": REQUIRED_ENV,
                },
                [
                    f"Set {key} in {self.env_file} or the deployment environment."
                    for key in missing
                ],
            )
            return
        if self.strict_production and placeholders:
            self.add(
                "env.required",
                "fail",
                "Placeholder values remain: " + ", ".join(placeholders),
                {
                    "placeholders": placeholders,
                    "required": REQUIRED_ENV,
                },
                [
                    f"Replace placeholder value for {key} with a real production secret or path."
                    for key in placeholders
                ],
            )
            return
        status = "warn" if placeholders else "pass"
        detail = "Required variables are present."
        if placeholders:
            detail = "Required variables are present, but placeholders remain: " + ", ".join(placeholders)
        remediation = [
            f"Replace placeholder value for {key} before production live probes."
            for key in placeholders
        ] or None
        self.add("env.required", status, detail, {"variables": sorted(REQUIRED_ENV)}, remediation)

    def check_secret_strength(self) -> None:
        pending = sorted(
            key for key in SECRET_STRENGTH_RULES if not self.env.get(key) or is_placeholder(self.env.get(key))
        )
        if pending:
            self.add(
                "env.secret-strength",
                "warn",
                "Secret strength check is waiting for non-placeholder values: " + ", ".join(pending),
                {"pending": pending, "rules": SECRET_STRENGTH_RULES},
                [
                    f"Set a real production value for {key}, then rerun the preflight."
                    for key in pending
                ],
            )
            return
        problems: dict[str, list[str]] = {}
        for key, rule in SECRET_STRENGTH_RULES.items():
            value = self.env.get(key)
            issues = secret_strength_issues(
                value,
                min_length=int(rule["min_length"]),
                min_unique=int(rule["min_unique"]),
            )
            if issues:
                problems[key] = issues
        if not problems:
            self.add(
                "env.secret-strength",
                "pass",
                "Internal production secrets meet minimum length and diversity requirements.",
            )
            return
        status = "fail" if self.strict_production else "warn"
        self.add(
            "env.secret-strength",
            status,
            "Weak internal secret values: "
            + "; ".join(f"{key} ({', '.join(issues)})" for key, issues in problems.items()),
            {"problems": problems, "rules": SECRET_STRENGTH_RULES},
            [
                (
                    f"Regenerate {key} as a random secret with at least "
                    f"{rule['min_length']} characters and {rule['min_unique']} unique characters."
                )
                for key, rule in SECRET_STRENGTH_RULES.items()
                if key in problems
            ],
        )

    def check_production_flags(self) -> None:
        failures: list[str] = []
        for key, expected in PRODUCTION_FLAG_DEFAULTS.items():
            actual = self.env.get(key, expected).strip().lower()
            if actual != expected:
                failures.append(f"{key}={actual}, expected {expected}")
        if failures:
            self.add(
                "env.production-flags",
                "fail",
                "; ".join(failures),
                remediation=[
                    f"Set {key}={expected} in {self.env_file}."
                    for key, expected in PRODUCTION_FLAG_DEFAULTS.items()
                ],
            )
            return
        self.add(
            "env.production-flags",
            "pass",
            "Authentication, OCR, PostgreSQL, and orchestration flags are production-ready.",
        )

    def check_agentdesign(self) -> None:
        if not env_bool(self.env, "AICHECK_ENABLE_AGENTDESIGN_SEAL_OCR", False):
            self.add(
                "agentdesign.path",
                "pass",
                "agentdesign seal OCR is disabled; backend-native OCR does not require seal_ocr/pipeline.py.",
                {"enabled": False, "hostPath": self.env.get("AICHECK_AGENTDESIGN_HOST_PATH")},
            )
            return
        raw_path = self.env.get("AICHECK_AGENTDESIGN_HOST_PATH")
        if not raw_path:
            self.add(
                "agentdesign.path",
                "fail",
                "AICHECK_AGENTDESIGN_HOST_PATH is missing.",
                remediation=[
                    "Set AICHECK_AGENTDESIGN_HOST_PATH when AICHECK_ENABLE_AGENTDESIGN_SEAL_OCR=true.",
                    "The path must contain requirements/mvp-ocr.txt and mvp-system/backend/seal_ocr/pipeline.py.",
                ],
            )
            return
        root = Path(raw_path).expanduser()
        pipeline = root / "mvp-system" / "backend" / "seal_ocr" / "pipeline.py"
        requirements = root / "requirements" / "mvp-ocr.txt"
        missing = [str(path) for path in (pipeline, requirements) if not path.exists()]
        if missing:
            self.add(
                "agentdesign.path",
                "fail",
                "Missing OCR reference files: " + ", ".join(missing),
                {"missing": missing},
                [
                    "Point AICHECK_AGENTDESIGN_HOST_PATH at a complete agentdesign checkout, or set AICHECK_ENABLE_AGENTDESIGN_SEAL_OCR=false.",
                    "Verify requirements/mvp-ocr.txt and mvp-system/backend/seal_ocr/pipeline.py exist.",
                ],
            )
            return
        self.add("agentdesign.path", "pass", f"{root} contains the expected OCR baseline files.")

    def check_ocr_models(self) -> None:
        raw_path = self.env.get("AICHECK_OCR_MODELS_HOST_PATH")
        if not raw_path:
            self.add(
                "ocr.models",
                "fail",
                "AICHECK_OCR_MODELS_HOST_PATH is missing.",
                remediation=[
                    "Set AICHECK_OCR_MODELS_HOST_PATH to the local OCR model artifact directory.",
                    "The path must contain paddleocr, paddlex, paddleocr-vl, and docling subdirectories.",
                ],
            )
            return
        root = Path(raw_path).expanduser()
        bundled_missing = [name for name in OCR_BUNDLED_MODEL_DIRS if not (root / name).exists()]
        if not bundled_missing:
            self.add(
                "ocr.models",
                "pass",
                f"{root} contains required local OCR model directories.",
                {"layout": "bundled", "root": str(root), "required": list(OCR_BUNDLED_MODEL_DIRS)},
            )
            return

        flat_missing = self.missing_flat_ocr_model_dirs(root)
        docling_ready = self.docling_artifacts_ready(root)
        if not flat_missing and docling_ready:
            self.add(
                "ocr.models",
                "pass",
                f"{root} contains the required explicit OCR model directories.",
                {
                    "layout": "flat-explicit",
                    "root": str(root),
                    "modelDirectories": {
                        key: str(self.resolve_host_model_path(root, self.env.get(key) or aliases[0]))
                        for key, aliases in OCR_FLAT_MODEL_DIRS.items()
                    },
                    "doclingArtifactsPath": str(self.resolve_docling_artifacts_path(root)),
                },
            )
            return

        missing = [] if not flat_missing else list(bundled_missing)
        missing.extend(flat_missing)
        if not docling_ready:
            missing.append("DOCLING_ARTIFACTS_PATH")
        missing = sorted(set(missing))
        if missing:
            self.add(
                "ocr.models",
                "fail",
                "Missing local OCR model directories: " + ", ".join(missing),
                {
                    "missing": missing,
                    "root": str(root),
                    "supportedLayouts": ["bundled", "flat-explicit"],
                    "bundledMissing": bundled_missing,
                    "flatMissing": flat_missing,
                    "doclingReady": docling_ready,
                },
                [
                    "Download or copy the approved local OCR model artifact bundle before deployment.",
                    "For a bundled artifact, provide paddleocr, paddlex, paddleocr-vl, and docling subdirectories.",
                    "For a PaddleX official_models cache, set the explicit AICHECK_*_MODEL_DIR variables and DOCLING_ARTIFACTS_PATH.",
                    "Verify the model bundle is mounted read-only to /models in ocr-service.",
                ],
            )
            return

    def missing_flat_ocr_model_dirs(self, root: Path) -> list[str]:
        missing: list[str] = []
        for env_name, aliases in OCR_FLAT_MODEL_DIRS.items():
            configured = self.env.get(env_name)
            if configured:
                candidates = [self.resolve_host_model_path(root, configured)]
            else:
                candidates = [root / alias for alias in aliases]
            if not any(candidate.exists() and candidate.is_dir() for candidate in candidates):
                missing.append(env_name)
        return missing

    def resolve_host_model_path(self, root: Path, value: str) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute() and path.parts[:2] == ("/", "models"):
            return root.joinpath(*path.parts[2:])
        if path.is_absolute() and path.parts[:3] == ("/", "opt", "agentdesign"):
            agentdesign_root = Path(self.env.get("AICHECK_AGENTDESIGN_HOST_PATH", "/opt/agentdesign")).expanduser()
            return agentdesign_root.joinpath(*path.parts[3:])
        return path if path.is_absolute() else root / path

    def resolve_docling_artifacts_path(self, root: Path) -> Path:
        configured = self.env.get("DOCLING_ARTIFACTS_PATH")
        if configured:
            return self.resolve_host_model_path(root, configured)
        return root / "docling"

    def docling_artifacts_ready(self, root: Path) -> bool:
        path = self.resolve_docling_artifacts_path(root)
        if not path.exists() or not path.is_dir():
            return False
        return any(item.is_file() for item in path.rglob("*"))

    def check_ports(self) -> None:
        open_ports = {port: service for port, service in HOST_PORTS.items() if tcp_port_open(port)}
        if not open_ports:
            self.add("host.ports", "pass", "Default Compose ports are currently free.")
            return
        status = "fail" if self.require_ports_free else "warn"
        detail = "Default Compose ports are already open: " + ", ".join(
            f"{service}:{port}" for port, service in sorted(open_ports.items())
        )
        self.add(
            "host.ports",
            status,
            detail,
            {"openPorts": open_ports},
            [
                "Stop the conflicting local services before starting Compose, or",
                "Change the published ports in docker-compose.yml for this host.",
            ],
        )

    def check_live_probe_command(self) -> None:
        blockers = [result.name for result in self.results if result.status == "fail"]
        if blockers:
            self.add(
                "probe.command-ready",
                "fail",
                "Cannot run 96+ live probes until these checks pass: " + ", ".join(blockers),
                {"blockers": blockers},
                [
                    "Resolve the blocking checks listed in data.blockers.",
                    "Then run `python scripts/check_96_preflight.py --strict-production` again.",
                ],
            )
            return
        self.add(
            "probe.command-ready",
            "pass",
            (
                "Run deployment_report.py with --include-live --write-probes --ocr-object-probe "
                "--litellm-management-probes --litellm-provider-probes after docker compose is healthy."
            ),
            {
                "command": (
                    "python scripts/deployment_report.py --strict-production --include-live "
                    "--write-probes --ocr-object-probe --litellm-management-probes --litellm-provider-probes "
                    "--output-dir ./deployment-reports/latest"
                )
            },
        )


def render_text(results: list[CheckResult]) -> str:
    lines = ["AIcheck 96+ Preflight", ""]
    for item in results:
        lines.append(f"- {item.status.upper()} {item.name}: {item.detail}")
        if item.remediation:
            for step in item.remediation:
                lines.append(f"  remediation: {step}")
    summary = summarize(results)
    lines.extend(
        [
            "",
            "Summary: total={total}, pass={pass}, warn={warn}, fail={fail}.".format(**summary),
        ]
    )
    return "\n".join(lines) + "\n"


def summarize(results: list[CheckResult]) -> dict[str, int]:
    summary = {"total": len(results), "pass": 0, "warn": 0, "fail": 0}
    for item in results:
        if item.status in summary:
            summary[item.status] += 1
    return summary


def main() -> int:
    args = parse_args()
    checker = PreflightChecker(
        env_file=Path(args.env_file),
        strict_production=bool(args.strict_production),
        require_ports_free=bool(args.require_ports_free),
    )
    results = checker.run()
    if args.json:
        payload = {
            "ok": all(item.ok for item in results),
            "summary": summarize(results),
            "checks": [asdict(item) for item in results],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(results), end="")
    return 0 if all(item.ok for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
