from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSE = BACKEND_ROOT / "docker-compose.ocr-validation.yml"
REMOTE_CONFIRMATION = "I_UNDERSTAND_REMOTE_ONLY"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the isolated OCR validation fault suite on the server host.")
    parser.add_argument("--confirm-server", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--compose", default=str(DEFAULT_COMPOSE))
    parser.add_argument("--source-root", default="/validation/Scan")
    parser.add_argument("--manifest", default="/validation/ocr_eval/scan_regression_manifest_v2.json")
    parser.add_argument("--reports-dir", default=str(BACKEND_ROOT / "reports" / "ocr-validation"))
    parser.add_argument("--injection-delay-seconds", type=float, default=8.0)
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    parser.add_argument("--output")
    return parser.parse_args()


def compose_base(compose_path: Path) -> list[str]:
    return ["docker", "compose", "-f", str(compose_path)]


def run(command: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=BACKEND_ROOT,
        check=check,
        capture_output=capture,
        text=True,
    )


def runner_command(
    compose: list[str],
    *,
    script: str,
    campaign: str,
    manifest: str,
    source_root: str,
    output_path: str,
    timeout_seconds: int,
) -> list[str]:
    return [
        *compose,
        "--profile",
        "runner",
        "run",
        "--rm",
        "runner",
        "python",
        script,
        "--campaign",
        campaign,
        "--manifest",
        manifest,
        "--source-root",
        source_root,
        "--timeout-seconds",
        str(timeout_seconds),
        "--output",
        output_path,
    ]


def report_gate(report: dict[str, Any]) -> bool:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return bool(
        not report.get("timedOut")
        and int(summary.get("systemFailures") or 0) == 0
        and int(summary.get("applicableEngineFailureCount") or 0) == 0
        and int(summary.get("duplicatePipelineRunCount") or 0) == 0
        and int(summary.get("duplicateStageRunCount") or 0) == 0
        and int(summary.get("invalidCandidateIdCount") or 0) == 0
        and int(summary.get("unsupportedAttributionCount") or 0) == 0
        and int(summary.get("formalEvidenceReadyCount") or 0) == 0
    )


def run_restart_scenario(
    compose: list[str],
    *,
    service: str,
    campaign: str,
    manifest: str,
    source_root: str,
    reports_dir: Path,
    injection_delay_seconds: float,
    timeout_seconds: int,
) -> dict[str, Any]:
    report_name = f"{campaign}.json"
    container_report = f"/validation/reports/ocr-validation/{report_name}"
    host_report = reports_dir / report_name
    command = [
        *runner_command(
            compose,
            script="scripts/ocr_accuracy_pipeline_batch.py",
            campaign=campaign,
            manifest=manifest,
            source_root=source_root,
            output_path=container_report,
            timeout_seconds=timeout_seconds,
        ),
        "--limit",
        "2",
    ]
    started = time.monotonic()
    stdout_log = reports_dir / f"{campaign}.stdout.log"
    stderr_log = reports_dir / f"{campaign}.stderr.log"
    with stdout_log.open("w", encoding="utf-8") as stdout_handle, stderr_log.open("w", encoding="utf-8") as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=BACKEND_ROOT,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
        )
        time.sleep(max(1.0, injection_delay_seconds))
        restart = run([*compose, "restart", service], check=False)
        run([*compose, "up", "-d", "--wait", service], check=False)
        try:
            process.wait(timeout=timeout_seconds + 300)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=30)
    stdout = stdout_log.read_text(encoding="utf-8")
    stderr = stderr_log.read_text(encoding="utf-8")
    report = json.loads(host_report.read_text(encoding="utf-8")) if host_report.is_file() else {}
    passed = process.returncode == 0 and restart.returncode == 0 and report_gate(report)
    return {
        "scenario": f"restart_{service}_during_pipeline",
        "service": service,
        "passed": passed,
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "runnerExitCode": process.returncode,
        "restartExitCode": restart.returncode,
        "stdoutTail": stdout[-2000:],
        "stderrTail": stderr[-2000:],
        "reportPath": str(host_report),
        "summary": report.get("summary") or {},
    }


def main() -> int:
    args = parse_args()
    if args.confirm_server != REMOTE_CONFIRMATION:
        raise RuntimeError("Refusing to run: this suite must be explicitly confirmed on the remote server host")
    compose_path = Path(args.compose).resolve()
    if not compose_path.is_file():
        raise FileNotFoundError(compose_path)
    reports_dir = Path(args.reports_dir).resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)
    compose = compose_base(compose_path)
    run([*compose, "up", "-d", "--wait"])

    proxy_report_name = f"{args.campaign}-proxy-faults.json"
    proxy_host_report = reports_dir / proxy_report_name
    proxy_command = runner_command(
        compose,
        script="scripts/ocr_pipeline_fault_injection.py",
        campaign=f"{args.campaign}-proxy",
        manifest=args.manifest,
        source_root=args.source_root,
        output_path=f"/validation/reports/ocr-validation/{proxy_report_name}",
        timeout_seconds=args.timeout_seconds,
    )
    proxy = run(proxy_command, check=False)
    proxy_report = json.loads(proxy_host_report.read_text(encoding="utf-8")) if proxy_host_report.is_file() else {}
    scenarios: list[dict[str, Any]] = [
        {
            "scenario": "ocr_and_qwen_proxy_faults",
            "passed": proxy.returncode == 0 and bool(proxy_report.get("passed")),
            "runnerExitCode": proxy.returncode,
            "stdoutTail": proxy.stdout[-2000:],
            "stderrTail": proxy.stderr[-2000:],
            "reportPath": str(proxy_host_report),
            "details": proxy_report,
        }
    ]
    for service in [
        "redis-ocr-validation",
        "minio-ocr-validation",
        "postgres-ocr-validation",
        "cpu-heavy-ocr-validation",
    ]:
        scenarios.append(
            run_restart_scenario(
                compose,
                service=service,
                campaign=f"{args.campaign}-{service}",
                manifest=args.manifest,
                source_root=args.source_root,
                reports_dir=reports_dir,
                injection_delay_seconds=args.injection_delay_seconds,
                timeout_seconds=args.timeout_seconds,
            )
        )
    result = {
        "schemaVersion": "aicheck-ocr-validation-fault-suite@1",
        "campaign": args.campaign,
        "passed": all(item.get("passed") for item in scenarios),
        "scenarios": scenarios,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    output = Path(args.output).resolve() if args.output else reports_dir / f"{args.campaign}-fault-suite.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
