from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env"
REQUIRED_ENV = {
    "AICHECK_AGENTDESIGN_HOST_PATH": "agentdesign source checkout",
    "AICHECK_MINIO_SECRET_KEY": "MinIO root password and signing secret",
    "AICHECK_JWT_SECRET": "JWT signing secret",
    "LITELLM_API_KEY": "LiteLLM master key used by API/worker probes",
    "LITELLM_POSTGRES_PASSWORD": "LiteLLM PostgreSQL password",
    "OPENAI_API_KEY": "upstream provider key consumed by LiteLLM",
}
PRODUCTION_FLAG_DEFAULTS = {
    "AICHECK_REQUIRE_AUTH": "true",
    "AICHECK_ENABLE_DEMO_USERS": "false",
    "AICHECK_OCR_ALLOW_PLACEHOLDER": "false",
    "AICHECK_MONGO_TRANSACTIONS": "true",
}
HOST_PORTS = {
    8000: "api-service",
    8010: "ocr-service",
    4001: "litellm-service",
    9000: "minio-api",
    9001: "minio-console",
    27017: "mongodb",
    6379: "redis",
    5433: "litellm-postgres",
}
PLACEHOLDER_MARKERS = ("replace-with", "change-me", "placeholder", "example", "sk-aicheck-dev")


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""
    data: dict[str, object] | None = None

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
        self.check_production_flags()
        self.check_agentdesign()
        self.check_ports()
        self.check_live_probe_command()
        return self.results

    def add(self, name: str, status: str, detail: str = "", data: dict[str, object] | None = None) -> None:
        self.results.append(CheckResult(name=name, status=status, detail=detail, data=data))

    def check_docker(self) -> None:
        docker = shutil.which("docker")
        if not docker:
            self.add("runtime.docker", "fail", "docker CLI was not found on PATH.")
            self.add("runtime.compose", "fail", "docker compose cannot be checked without docker CLI.")
            return

        version = self.run_command([docker, "--version"])
        self.add("runtime.docker", "pass" if version[0] else "fail", version[1])

        compose = self.run_command([docker, "compose", "version"])
        self.add("runtime.compose", "pass" if compose[0] else "fail", compose[1])

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
            )

    def check_required_env(self) -> None:
        missing = sorted(key for key in REQUIRED_ENV if not self.env.get(key))
        placeholders = sorted(key for key in REQUIRED_ENV if is_placeholder(self.env.get(key)))
        if missing:
            self.add("env.required", "fail", "Missing required variables: " + ", ".join(missing))
            return
        if self.strict_production and placeholders:
            self.add("env.required", "fail", "Placeholder values remain: " + ", ".join(placeholders))
            return
        status = "warn" if placeholders else "pass"
        detail = "Required variables are present."
        if placeholders:
            detail = "Required variables are present, but placeholders remain: " + ", ".join(placeholders)
        self.add("env.required", status, detail, {"variables": sorted(REQUIRED_ENV)})

    def check_production_flags(self) -> None:
        failures: list[str] = []
        for key, expected in PRODUCTION_FLAG_DEFAULTS.items():
            actual = self.env.get(key, expected).strip().lower()
            if actual != expected:
                failures.append(f"{key}={actual}, expected {expected}")
        if failures:
            self.add("env.production-flags", "fail", "; ".join(failures))
            return
        self.add(
            "env.production-flags",
            "pass",
            "Authentication, OCR, and Mongo transaction flags are production-ready.",
        )

    def check_agentdesign(self) -> None:
        raw_path = self.env.get("AICHECK_AGENTDESIGN_HOST_PATH")
        if not raw_path:
            self.add("agentdesign.path", "fail", "AICHECK_AGENTDESIGN_HOST_PATH is missing.")
            return
        root = Path(raw_path).expanduser()
        pipeline = root / "mvp-system" / "backend" / "seal_ocr" / "pipeline.py"
        requirements = root / "requirements" / "mvp-ocr.txt"
        missing = [str(path) for path in (pipeline, requirements) if not path.exists()]
        if missing:
            self.add("agentdesign.path", "fail", "Missing OCR reference files: " + ", ".join(missing))
            return
        self.add("agentdesign.path", "pass", f"{root} contains the expected OCR baseline files.")

    def check_ports(self) -> None:
        open_ports = {port: service for port, service in HOST_PORTS.items() if tcp_port_open(port)}
        if not open_ports:
            self.add("host.ports", "pass", "Default Compose ports are currently free.")
            return
        status = "fail" if self.require_ports_free else "warn"
        detail = "Default Compose ports are already open: " + ", ".join(
            f"{service}:{port}" for port, service in sorted(open_ports.items())
        )
        self.add("host.ports", status, detail, {"openPorts": open_ports})

    def check_live_probe_command(self) -> None:
        blockers = [
            result.name
            for result in self.results
            if result.status == "fail"
            and result.name in {"runtime.docker", "runtime.compose", "env.file", "env.required"}
        ]
        if blockers:
            self.add(
                "probe.command-ready",
                "fail",
                "Cannot run 96+ live probes until these checks pass: " + ", ".join(blockers),
            )
            return
        self.add(
            "probe.command-ready",
            "pass",
            (
                "Run deployment_report.py with --include-live --write-probes --ocr-object-probe "
                "--litellm-provider-probes after docker compose is healthy."
            ),
            {
                "command": (
                    "python scripts/deployment_report.py --strict-production --include-live "
                    "--write-probes --ocr-object-probe --litellm-provider-probes "
                    "--output-dir ./deployment-reports/latest"
                )
            },
        )


def render_text(results: list[CheckResult]) -> str:
    lines = ["AIcheck 96+ Preflight", ""]
    for item in results:
        lines.append(f"- {item.status.upper()} {item.name}: {item.detail}")
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
