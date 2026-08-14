from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_96_preflight import PreflightChecker, parse_env_file

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env"
DEFAULT_LOCAL_COMPOSE_FILE = BACKEND_ROOT / "docker-compose.local-ocr.yml"
LOCAL_OCR_SERVICES = ("local-ocr-service", "local-ocr-worker")
DEFAULT_DOCKER_STORAGE_PREFIX = Path("/Volumes/7up")
REQUIRED_LOCAL_ENV = {
    "AICHECK_OCR_MODELS_HOST_PATH": "local OCR model artifact directory mounted to /models",
    "AICHECK_MINIO_SECRET_KEY": "MinIO secret used by the local OCR service",
    "AICHECK_POSTGRES_PASSWORD": "PostgreSQL password used by the local OCR worker",
}
EXPECTED_OCR_FLAGS = {
    "AICHECK_OCR_ALLOW_PLACEHOLDER": "false",
    "AICHECK_OCR_OFFLINE_ONLY": "true",
    "AICHECK_OCR_DISABLE_NETWORK": "true",
}
LOCAL_DEP_PORTS = {
    "postgres": ("AICHECK_LOCAL_POSTGRES_PORT", 15432),
    "redis": ("AICHECK_LOCAL_REDIS_PORT", 6379),
    "minio": ("AICHECK_LOCAL_MINIO_PORT", 9000),
}


@dataclass
class LocalOcrCheck:
    name: str
    status: str
    detail: str = ""
    data: dict[str, Any] | None = None
    remediation: list[str] | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"pass", "warn", "skip"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare the local OCR service described in deployment.md. By default the "
            "script checks the environment and prints the exact Docker Compose command; "
            "use --start to actually start the OCR containers."
        )
    )
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--compose-file", default=str(DEFAULT_LOCAL_COMPOSE_FILE))
    parser.add_argument("--start", action="store_true", help="Start local OCR containers.")
    parser.add_argument(
        "--no-worker",
        action="store_true",
        help="Start/check only local-ocr-service. Uploaded files need the worker to run OCR.",
    )
    parser.add_argument(
        "--skip-local-deps-check",
        action="store_true",
        help="Do not check host Postgres/Redis/MinIO ports before starting local OCR.",
    )
    parser.add_argument(
        "--allow-non-7up-docker-storage",
        action="store_true",
        help="Allow Docker image storage outside /Volumes/7up. Not recommended for OCR images.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify an already running OCR service without starting containers.",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="When used with --start, skip HTTP health/ready/doctor verification.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def merge_env(env_file: Path, process_env: Mapping[str, str] | None = None) -> dict[str, str]:
    values = parse_env_file(env_file)
    values.update(dict(process_env if process_env is not None else os.environ))
    return values


def tcp_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def run_command(
    command: list[str],
    *,
    cwd: Path = BACKEND_ROOT,
    timeout: float = 600,
) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    return completed.returncode == 0, output


def http_json(url: str, *, timeout: float = 5.0) -> tuple[int, dict[str, Any]]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
            return int(response.status), payload
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {"error": str(exc)}
        return int(exc.code), payload


def payload_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def parse_colima_mount_locations(config_file: Path) -> list[Path]:
    if not config_file.exists():
        return []
    locations: list[Path] = []
    pattern = re.compile(r"^\s*-\s+location:\s+(.+?)\s*$")
    for line in config_file.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        raw_location = match.group(1).strip().strip("'\"")
        if not raw_location:
            continue
        locations.append(Path(raw_location).expanduser().resolve(strict=False))
    return locations


def path_is_covered_by_mount(path: Path, mounts: list[Path]) -> bool:
    resolved_path = path.expanduser().resolve(strict=False)
    return any(is_relative_to(resolved_path, mount) for mount in mounts)


class LocalOcrInstaller:
    def __init__(
        self,
        *,
        env_file: Path = DEFAULT_ENV_FILE,
        compose_file: Path = DEFAULT_LOCAL_COMPOSE_FILE,
        include_worker: bool = True,
        skip_local_deps_check: bool = False,
        require_7up_docker_storage: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.env_file = env_file
        self.compose_file = compose_file
        self.include_worker = include_worker
        self.skip_local_deps_check = skip_local_deps_check
        self.require_7up_docker_storage = require_7up_docker_storage
        self.env = merge_env(env_file, env)
        self.checks: list[LocalOcrCheck] = []

    def add(
        self,
        name: str,
        status: str,
        detail: str = "",
        data: dict[str, Any] | None = None,
        remediation: list[str] | None = None,
    ) -> None:
        self.checks.append(LocalOcrCheck(name, status, detail, data, remediation))

    @property
    def services(self) -> list[str]:
        if self.include_worker:
            return list(LOCAL_OCR_SERVICES)
        return ["local-ocr-service"]

    def run_checks(self) -> list[LocalOcrCheck]:
        self.check_env_file()
        self.check_compose_file()
        self.check_docker()
        self.check_docker_storage()
        self.check_required_env()
        self.check_ocr_flags()
        self.check_model_layout()
        self.check_model_bind_mount()
        self.check_dispatch_mode()
        self.check_local_dependency_ports()
        self.add_start_command()
        return self.checks

    def check_env_file(self) -> None:
        if self.env_file.exists():
            self.add("env.file", "pass", f"{self.env_file} exists.")
            return
        self.add(
            "env.file",
            "fail",
            f"{self.env_file} is missing.",
            remediation=[
                "Run `cd backend && cp .env.example .env`.",
                "Fill OCR model path, MinIO secret, and PostgreSQL password before starting OCR.",
            ],
        )

    def check_compose_file(self) -> None:
        if not self.compose_file.exists():
            self.add(
                "compose.file",
                "fail",
                f"{self.compose_file} is missing.",
                remediation=["Restore backend/docker-compose.local-ocr.yml."],
            )
            return
        text = self.compose_file.read_text(encoding="utf-8")
        missing = [service for service in LOCAL_OCR_SERVICES if f"{service}:" not in text]
        status = "fail" if missing else "pass"
        detail = (
            "Missing local OCR services: " + ", ".join(missing)
            if missing
            else "Local OCR compose file contains service and worker definitions."
        )
        self.add("compose.file", status, detail, {"services": list(LOCAL_OCR_SERVICES)})

    def check_docker(self) -> None:
        docker = shutil.which("docker")
        if not docker:
            self.add(
                "runtime.docker",
                "fail",
                "docker CLI was not found on PATH.",
                remediation=["Install Docker Desktop or Docker Engine."],
            )
            return
        docker_ok, docker_output = run_command([docker, "--version"], timeout=8)
        self.add("runtime.docker", "pass" if docker_ok else "fail", docker_output)
        compose_ok, compose_output = run_command([docker, "compose", "version"], timeout=8)
        self.add(
            "runtime.compose",
            "pass" if compose_ok else "fail",
            compose_output,
            remediation=None if compose_ok else ["Install or repair Docker Compose v2."],
        )

    def required_docker_storage_prefix(self) -> Path:
        return Path(
            self.env.get("AICHECK_DOCKER_STORAGE_HOST_PREFIX")
            or str(DEFAULT_DOCKER_STORAGE_PREFIX)
        ).expanduser()

    def check_docker_storage(self) -> None:
        if not self.require_7up_docker_storage:
            self.add(
                "docker.storage",
                "skip",
                "Docker storage prefix check was skipped.",
            )
            return
        docker = shutil.which("docker")
        if not docker:
            self.add(
                "docker.storage",
                "fail",
                "Cannot check Docker storage without docker CLI.",
            )
            return
        prefix = self.required_docker_storage_prefix().resolve(strict=False)
        ok, context_name = run_command([docker, "context", "show"], timeout=8)
        if not ok or not context_name.strip():
            self.add(
                "docker.storage",
                "fail",
                "Cannot determine active Docker context.",
                remediation=["Fix `docker context show` before building OCR images."],
            )
            return
        ok, raw_context = run_command(
            [
                docker,
                "context",
                "inspect",
                context_name.strip(),
                "--format",
                "{{json .}}",
            ],
            timeout=8,
        )
        if not ok:
            self.add(
                "docker.storage",
                "fail",
                "Cannot inspect active Docker context.",
                remediation=["Fix `docker context inspect` before building OCR images."],
            )
            return
        try:
            context = json.loads(raw_context)
        except json.JSONDecodeError:
            self.add("docker.storage", "fail", "Docker context inspect did not return JSON.")
            return
        host = (
            context.get("Endpoints", {})
            .get("docker", {})
            .get("Host", "")
        )
        storage_path = self.infer_docker_storage_path(str(host))
        if storage_path is None:
            self.add(
                "docker.storage",
                "fail",
                "Docker storage path could not be inferred from active context.",
                {"context": context_name.strip(), "host": host, "requiredPrefix": str(prefix)},
                [
                    (
                        "Use a Docker context whose host-side image storage can be verified "
                        "under /Volumes/7up before building OCR images."
                    ),
                    "For Colima, move ~/.colima to /Volumes/7up and keep ~/.colima as a symlink.",
                ],
            )
            return
        resolved_storage = storage_path.resolve(strict=False)
        if is_relative_to(resolved_storage, prefix):
            self.add(
                "docker.storage",
                "pass",
                f"Docker context storage is under {prefix}.",
                {
                    "context": context_name.strip(),
                    "host": host,
                    "storagePath": str(resolved_storage),
                    "requiredPrefix": str(prefix),
                },
            )
            return
        self.add(
            "docker.storage",
            "fail",
            f"Docker image storage is not under {prefix}: {resolved_storage}",
            {
                "context": context_name.strip(),
                "host": host,
                "storagePath": str(resolved_storage),
                "requiredPrefix": str(prefix),
            },
            [
                "Stop Colima before moving storage: `colima stop`.",
                (
                    "Move Colima data to the 7up disk, for example "
                    "`mkdir -p /Volumes/7up/docker && mv ~/.colima "
                    "/Volumes/7up/docker/.colima && ln -s "
                    "/Volumes/7up/docker/.colima ~/.colima`."
                ),
                (
                    "Start Colima again with Docker runtime: "
                    "`colima start --runtime docker --disk 100 --mount /Volumes/7up:w`."
                ),
            ],
        )

    def infer_docker_storage_path(self, host: str) -> Path | None:
        if not host.startswith("unix://"):
            return None
        socket_path = Path(host.removeprefix("unix://")).expanduser()
        parts = socket_path.parts
        if ".colima" not in parts:
            return None
        colima_index = parts.index(".colima")
        return Path(*parts[: colima_index + 1])

    def active_docker_context(self) -> tuple[str, str, Path | None] | None:
        docker = shutil.which("docker")
        if not docker:
            return None
        ok, context_name = run_command([docker, "context", "show"], timeout=8)
        if not ok or not context_name.strip():
            return None
        ok, raw_context = run_command(
            [
                docker,
                "context",
                "inspect",
                context_name.strip(),
                "--format",
                "{{json .}}",
            ],
            timeout=8,
        )
        if not ok:
            return None
        try:
            context = json.loads(raw_context)
        except json.JSONDecodeError:
            return None
        host = str(context.get("Endpoints", {}).get("docker", {}).get("Host", ""))
        return context_name.strip(), host, self.infer_docker_storage_path(host)

    def check_required_env(self) -> None:
        missing = [key for key in REQUIRED_LOCAL_ENV if not self.env.get(key)]
        if missing:
            self.add(
                "env.required",
                "fail",
                "Missing local OCR variables: " + ", ".join(missing),
                {"missing": missing, "required": REQUIRED_LOCAL_ENV},
                [f"Set {key} in {self.env_file}." for key in missing],
            )
            return
        self.add(
            "env.required",
            "pass",
            "Local OCR variables are present.",
            {"variables": sorted(REQUIRED_LOCAL_ENV)},
        )

    def check_ocr_flags(self) -> None:
        failures = []
        for key, expected in EXPECTED_OCR_FLAGS.items():
            actual = (self.env.get(key) or expected).strip().lower()
            if actual != expected:
                failures.append(f"{key}={actual}, expected {expected}")
        subprocess_python = (self.env.get("AICHECK_OCR_SUBPROCESS_PYTHON") or "").strip()
        if subprocess_python and subprocess_python != "/usr/local/bin/python":
            self.add(
                "env.ocr-subprocess-python",
                "warn",
                (
                    "Docker OCR should normally use /usr/local/bin/python. "
                    f"Current value is {subprocess_python}."
                ),
                remediation=[
                    "Set AICHECK_OCR_SUBPROCESS_PYTHON=/usr/local/bin/python for Docker OCR.",
                    "Use host .venv OCR Python only for bare-metal probe scripts.",
                ],
            )
        else:
            self.add(
                "env.ocr-subprocess-python",
                "pass",
                "Docker OCR subprocess Python is set to the image runtime.",
            )
        if failures:
            self.add(
                "env.ocr-flags",
                "fail",
                "; ".join(failures),
                remediation=[
                    f"Set {key}={expected} in {self.env_file}."
                    for key, expected in EXPECTED_OCR_FLAGS.items()
                ],
            )
            return
        self.add(
            "env.ocr-flags",
            "pass",
            "OCR offline and no-placeholder flags match deployment.md.",
        )

    def check_model_layout(self) -> None:
        checker = PreflightChecker(env_file=self.env_file, env=self.env)
        checker.check_ocr_models()
        for item in checker.results:
            self.add(
                item.name,
                item.status,
                item.detail,
                item.data,
                item.remediation,
            )

    def check_model_bind_mount(self) -> None:
        raw_model_path = self.env.get("AICHECK_OCR_MODELS_HOST_PATH")
        if not raw_model_path:
            self.add(
                "ocr.models-bind-mount",
                "skip",
                "Cannot check model bind mount before AICHECK_OCR_MODELS_HOST_PATH is set.",
            )
            return
        model_path = Path(raw_model_path).expanduser().resolve(strict=False)
        context_info = self.active_docker_context()
        if context_info is None:
            self.add(
                "ocr.models-bind-mount",
                "warn",
                "Cannot inspect active Docker context for model bind mount coverage.",
            )
            return
        context_name, host, storage_path = context_info
        if storage_path is None or ".colima" not in storage_path.parts:
            self.add(
                "ocr.models-bind-mount",
                "skip",
                "Model bind mount coverage check is only enforced for Colima contexts.",
                {"context": context_name, "host": host},
            )
            return
        config_file = storage_path / "default" / "colima.yaml"
        mounts = parse_colima_mount_locations(config_file)
        home_mount = Path.home().resolve(strict=False)
        effective_mounts = mounts or [home_mount]
        if path_is_covered_by_mount(model_path, effective_mounts):
            self.add(
                "ocr.models-bind-mount",
                "pass",
                "Colima can bind-mount the OCR model directory.",
                {
                    "context": context_name,
                    "modelPath": str(model_path),
                    "mounts": [str(item) for item in effective_mounts],
                },
            )
            return
        self.add(
            "ocr.models-bind-mount",
            "fail",
            f"Colima does not mount OCR model path into the VM: {model_path}",
            {
                "context": context_name,
                "host": host,
                "modelPath": str(model_path),
                "configFile": str(config_file),
                "mounts": [str(item) for item in effective_mounts],
            },
            [
                "Stop Colima: `colima stop`.",
                (
                    "Restart it with the 7up disk mounted: "
                    "`colima start --runtime docker --disk 100 --mount /Volumes/7up:w`."
                ),
                (
                    "Then rerun `python scripts/setup_local_ocr.py --start`; "
                    "the OCR container should see /models/PP-OCRv6_medium_det."
                ),
            ],
        )

    def check_dispatch_mode(self) -> None:
        mode = (self.env.get("AICHECK_TASK_DISPATCH") or "").strip().lower()
        if mode == "celery":
            self.add(
                "env.dispatch",
                "pass",
                "AICHECK_TASK_DISPATCH=celery; upload complete will enqueue OCR tasks.",
            )
            return
        self.add(
            "env.dispatch",
            "fail",
            (
                "AICHECK_TASK_DISPATCH must be celery for uploaded files to trigger "
                f"the worker; current={mode or '<unset>'}."
            ),
            remediation=["Set AICHECK_TASK_DISPATCH=celery in backend/.env and restart the API."],
        )

    def check_local_dependency_ports(self) -> None:
        if self.skip_local_deps_check:
            self.add("local.deps", "skip", "Local dependency port check was skipped.")
            return
        failures = []
        open_ports: dict[str, int] = {}
        for service, (env_key, default_port) in LOCAL_DEP_PORTS.items():
            port = int(self.env.get(env_key) or default_port)
            if tcp_port_open("127.0.0.1", port):
                open_ports[service] = port
            else:
                failures.append(f"{service}:127.0.0.1:{port}")
        if failures:
            self.add(
                "local.deps",
                "fail",
                "Local dependency ports are not reachable: " + ", ".join(failures),
                {"reachable": open_ports, "missing": failures},
                [
                    "Start the local Postgres, Redis, and MinIO containers first.",
                    (
                        "Set AICHECK_LOCAL_POSTGRES_PORT, AICHECK_LOCAL_REDIS_PORT, "
                        "or AICHECK_LOCAL_MINIO_PORT if your ports differ."
                    ),
                ],
            )
            return
        self.add(
            "local.deps",
            "pass",
            "Local Postgres, Redis, and MinIO ports are reachable.",
            {"reachable": open_ports},
        )

    def compose_command(self) -> list[str]:
        return [
            "docker",
            "compose",
            "--env-file",
            str(self.env_file),
            "-f",
            str(self.compose_file),
            "up",
            "-d",
            "--build",
            *self.services,
        ]

    def add_start_command(self) -> None:
        command = self.compose_command()
        self.add(
            "start.command",
            "pass",
            "Run with --start or execute the command manually.",
            {"command": " ".join(command), "services": self.services},
        )

    def start(self, *, timeout: float = 1200) -> LocalOcrCheck:
        blockers = [item.name for item in self.checks if item.status == "fail"]
        if blockers:
            check = LocalOcrCheck(
                "start.compose",
                "fail",
                "Cannot start local OCR until blocking checks pass: " + ", ".join(blockers),
                {"blockers": blockers},
            )
            self.checks.append(check)
            return check
        command = self.compose_command()
        ok, output = run_command(command, timeout=timeout)
        check = LocalOcrCheck(
            "start.compose",
            "pass" if ok else "fail",
            "Local OCR containers started." if ok else output[-4000:],
            {"command": " ".join(command), "services": self.services},
            None
            if ok
            else ["Inspect `docker compose` output and fix the reported build/start error."],
        )
        self.checks.append(check)
        return check

    def verify_http(self, *, timeout_seconds: float) -> list[LocalOcrCheck]:
        deadline = time.time() + timeout_seconds
        base_url = f"http://127.0.0.1:{int(self.env.get('AICHECK_LOCAL_OCR_PORT') or 8010)}"
        health_payload: dict[str, Any] | None = None
        ready_payload: dict[str, Any] | None = None
        doctor_payload: dict[str, Any] | None = None
        last_error = ""
        while time.time() < deadline:
            try:
                health_code, health_payload = http_json(f"{base_url}/healthz")
                ready_code, ready_payload = http_json(f"{base_url}/readyz")
                if health_code == 200 and ready_code == 200:
                    break
                last_error = f"health={health_code}, ready={ready_code}"
            except Exception as exc:  # pragma: no cover - defensive for unexpected URL errors
                last_error = str(exc)
            time.sleep(2)

        health_data = payload_data(health_payload or {})
        ready_data = payload_data(ready_payload or {})
        health_failures = []
        if health_data.get("pipelineAvailable") is not True:
            health_failures.append("pipelineAvailable must be true")
        if health_data.get("placeholderAllowed") is not False:
            health_failures.append("placeholderAllowed must be false")
        self.add(
            "ocr.health",
            "fail" if health_failures else "pass",
            "; ".join(health_failures) if health_failures else "OCR health endpoint is ready.",
            health_data or {"lastError": last_error},
        )

        ready_failures = []
        if ready_data.get("ready") is not True:
            ready_failures.append("ready must be true")
        if ready_data.get("offlineOnly") is not True:
            ready_failures.append("offlineOnly must be true")
        if ready_data.get("networkDisabled") is not True:
            ready_failures.append("networkDisabled must be true")
        self.add(
            "ocr.readyz",
            "fail" if ready_failures else "pass",
            (
                "; ".join(ready_failures)
                if ready_failures
                else "OCR readyz confirms local model readiness."
            ),
            ready_data or {"lastError": last_error},
        )

        try:
            doctor_code, doctor_payload = http_json(f"{base_url}/internal/ocr/doctor", timeout=8)
        except Exception as exc:  # pragma: no cover - defensive for unexpected URL errors
            doctor_code, doctor_payload = 0, {"error": str(exc)}
        doctor_data = payload_data(doctor_payload or {})
        doctor_failures = []
        if doctor_code != 200:
            doctor_failures.append(f"doctor returned HTTP {doctor_code}")
        if doctor_data.get("schemaVersion") != "aicheck-ocr-runtime-doctor-v1":
            doctor_failures.append("schemaVersion must be aicheck-ocr-runtime-doctor-v1")
        failed_checks = [
            item.get("name")
            for item in doctor_data.get("checks", [])
            if isinstance(item, dict) and item.get("status") == "fail"
        ]
        if failed_checks:
            doctor_failures.append(
                "failed doctor checks: " + ", ".join(str(item) for item in failed_checks[:8])
            )
        self.add(
            "ocr.runtime-doctor",
            "fail" if doctor_failures else "pass",
            "; ".join(doctor_failures) if doctor_failures else "OCR runtime doctor passed.",
            doctor_data or {"lastError": last_error},
        )
        return self.checks


def summarize(checks: list[LocalOcrCheck]) -> dict[str, int]:
    summary = {"total": len(checks), "pass": 0, "warn": 0, "skip": 0, "fail": 0}
    for item in checks:
        if item.status in summary:
            summary[item.status] += 1
    return summary


def render_text(checks: list[LocalOcrCheck]) -> str:
    lines = ["AIcheck Local OCR Setup", ""]
    for item in checks:
        lines.append(f"- {item.status.upper()} {item.name}: {item.detail}")
        if item.remediation:
            for step in item.remediation:
                lines.append(f"  remediation: {step}")
    lines.append("")
    lines.append(
        "Summary: total={total}, pass={pass}, warn={warn}, skip={skip}, fail={fail}.".format(
            **summarize(checks)
        )
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    installer = LocalOcrInstaller(
        env_file=Path(args.env_file),
        compose_file=Path(args.compose_file),
        include_worker=not bool(args.no_worker),
        skip_local_deps_check=bool(args.skip_local_deps_check),
        require_7up_docker_storage=not bool(args.allow_non_7up_docker_storage),
    )
    checks = installer.run_checks()
    if args.start:
        start_result = installer.start()
        if start_result.ok and not args.skip_verify:
            installer.verify_http(timeout_seconds=float(args.timeout_seconds))
    elif args.verify:
        installer.verify_http(timeout_seconds=float(args.timeout_seconds))
    checks = installer.checks
    if args.json:
        print(
            json.dumps(
                {
                    "ok": all(item.ok for item in checks),
                    "summary": summarize(checks),
                    "checks": [asdict(item) for item in checks],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render_text(checks), end="")
    return 0 if all(item.ok for item in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
