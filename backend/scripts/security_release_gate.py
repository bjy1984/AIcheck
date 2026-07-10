from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


REQUIRED_IMAGE_SERVICES = (
    "api-service",
    "worker-service",
    "review-worker-service",
    "ocr-service",
    "embedding-service",
    "litellm-service",
)
MAX_SCAN_AGE = timedelta(hours=72)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or validate AIcheck release SBOM and vulnerability evidence.")
    parser.add_argument("--compose-file", default="docker-compose.yml")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--generate", action="store_true", help="Build/pull images and run Trivy plus dependency audits.")
    parser.add_argument("--skip-build", action="store_true", help="Scan images already present in the Docker daemon.")
    parser.add_argument("--frontend-dir", default="../frontend")
    parser.add_argument("--requirements", default="requirements.txt")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON evidence {path}: {exc}") from exc


def _trivy_severity_counts(payload: dict[str, Any]) -> dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0}
    for result in payload.get("Results") or []:
        if not isinstance(result, dict):
            continue
        for item in result.get("Vulnerabilities") or []:
            if not isinstance(item, dict):
                continue
            severity = str(item.get("Severity") or "unknown").strip().lower()
            counts[severity if severity in counts else "unknown"] += 1
    return counts


def _pip_audit_vulnerability_count(payload: Any) -> int:
    dependencies = payload.get("dependencies") if isinstance(payload, dict) else payload
    if not isinstance(dependencies, list):
        raise ValueError("pip-audit evidence must contain a dependency list")
    return sum(len(item.get("vulns") or []) for item in dependencies if isinstance(item, dict))


def _pnpm_audit_counts(payload: dict[str, Any]) -> dict[str, int]:
    metadata = payload.get("metadata") or {}
    raw = metadata.get("vulnerabilities") or {}
    if not isinstance(raw, dict):
        raise ValueError("pnpm audit evidence must contain metadata.vulnerabilities")
    return {severity: int(raw.get(severity) or 0) for severity in ("critical", "high", "moderate", "low")}


def validate_scan_directory(output_dir: Path) -> dict[str, Any]:
    failures: list[str] = []
    services: list[dict[str, Any]] = []
    try:
        manifest = _read_json(output_dir / "scan-manifest.json")
        if not isinstance(manifest, dict):
            raise ValueError("scan-manifest must be a JSON object")
        generated_at = datetime.fromisoformat(str(manifest.get("generatedAt") or "").replace("Z", "+00:00"))
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=UTC)
        if datetime.now(UTC) - generated_at > MAX_SCAN_AGE:
            failures.append("scan-manifest: evidence is older than 72 hours")
        manifest_services = manifest.get("services") or {}
        if not isinstance(manifest_services, dict):
            raise ValueError("scan-manifest services must be an object")
        for service in REQUIRED_IMAGE_SERVICES:
            service_manifest = manifest_services.get(service) or {}
            image_id = str(service_manifest.get("imageId") or "") if isinstance(service_manifest, dict) else ""
            if not image_id.startswith("sha256:"):
                failures.append(f"scan-manifest: {service} has no immutable image ID")
        source_commit = str(manifest.get("sourceCommit") or "")
        if len(source_commit) < 7:
            failures.append("scan-manifest: sourceCommit is missing")
    except (ValueError, TypeError) as exc:
        manifest = {}
        failures.append(f"scan-manifest: {exc}")
    for service in REQUIRED_IMAGE_SERVICES:
        sbom_path = output_dir / f"{service}.sbom.cdx.json"
        scan_path = output_dir / f"{service}.trivy.json"
        service_result: dict[str, Any] = {
            "service": service,
            "sbom": str(sbom_path),
            "scan": str(scan_path),
            "status": "fail",
        }
        try:
            sbom = _read_json(sbom_path)
            if not isinstance(sbom, dict) or sbom.get("bomFormat") != "CycloneDX":
                raise ValueError("SBOM is not CycloneDX")
            scan = _read_json(scan_path)
            if not isinstance(scan, dict):
                raise ValueError("Trivy report must be a JSON object")
            counts = _trivy_severity_counts(scan)
            service_result["vulnerabilities"] = counts
            if counts["critical"] or counts["high"]:
                failures.append(f"{service}: critical={counts['critical']}, high={counts['high']}")
            else:
                service_result["status"] = "pass"
        except ValueError as exc:
            failures.append(f"{service}: {exc}")
            service_result["error"] = str(exc)
        services.append(service_result)

    dependency_checks: dict[str, Any] = {}
    try:
        pip_count = _pip_audit_vulnerability_count(_read_json(output_dir / "pip-audit.json"))
        dependency_checks["pipAudit"] = {"status": "pass" if pip_count == 0 else "fail", "vulnerabilities": pip_count}
        if pip_count:
            failures.append(f"pip-audit: vulnerabilities={pip_count}")
    except ValueError as exc:
        dependency_checks["pipAudit"] = {"status": "fail", "error": str(exc)}
        failures.append(f"pip-audit: {exc}")

    try:
        pnpm_counts = _pnpm_audit_counts(_read_json(output_dir / "pnpm-audit.json"))
        dependency_checks["pnpmAudit"] = {
            "status": "pass" if pnpm_counts["critical"] == 0 and pnpm_counts["high"] == 0 else "fail",
            "vulnerabilities": pnpm_counts,
        }
        if pnpm_counts["critical"] or pnpm_counts["high"]:
            failures.append(f"pnpm-audit: critical={pnpm_counts['critical']}, high={pnpm_counts['high']}")
    except ValueError as exc:
        dependency_checks["pnpmAudit"] = {"status": "fail", "error": str(exc)}
        failures.append(f"pnpm-audit: {exc}")

    return {
        "schemaVersion": "aicheck-security-release-gate-v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "status": "pass" if not failures else "fail",
        "manifest": manifest,
        "services": services,
        "dependencyChecks": dependency_checks,
        "failures": failures,
    }


def _run(command: list[str], *, cwd: Path, output: Path | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if output is not None:
        output.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0 and output is None:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{detail}")
    return completed


def generate_evidence(
    *, compose_file: Path, output_dir: Path, frontend_dir: Path, requirements: Path, skip_build: bool
) -> None:
    for executable in ("docker", "trivy"):
        if not shutil.which(executable):
            raise RuntimeError(f"required executable not found: {executable}")
    output_dir.mkdir(parents=True, exist_ok=True)
    compose_dir = compose_file.parent
    compose_name = compose_file.name
    if not skip_build:
        _run(
            ["docker", "compose", "-f", compose_name, "build", *REQUIRED_IMAGE_SERVICES[:-1]],
            cwd=compose_dir,
        )
        _run(["docker", "compose", "-f", compose_name, "pull", "litellm-service"], cwd=compose_dir)

    manifest_services: dict[str, Any] = {}
    for service in REQUIRED_IMAGE_SERVICES:
        image_result = _run(
            ["docker", "compose", "-f", compose_name, "images", "-q", service],
            cwd=compose_dir,
        )
        image_id = next((line.strip() for line in image_result.stdout.splitlines() if line.strip()), "")
        if not image_id:
            raise RuntimeError(f"no local image found for service: {service}")
        inspect_result = _run(["docker", "image", "inspect", image_id], cwd=compose_dir)
        inspect_payload = json.loads(inspect_result.stdout)
        image_info = inspect_payload[0] if isinstance(inspect_payload, list) and inspect_payload else {}
        manifest_services[service] = {
            "imageId": str(image_info.get("Id") or image_id),
            "repoDigests": image_info.get("RepoDigests") or [],
        }
        _run(
            ["trivy", "image", "--format", "cyclonedx", "--output", str(output_dir / f"{service}.sbom.cdx.json"), image_id],
            cwd=compose_dir,
        )
        _run(
            [
                "trivy",
                "image",
                "--scanners",
                "vuln",
                "--format",
                "json",
                "--output",
                str(output_dir / f"{service}.trivy.json"),
                image_id,
            ],
            cwd=compose_dir,
        )

    commit_result = _run(["git", "rev-parse", "HEAD"], cwd=compose_dir)
    (output_dir / "scan-manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": "aicheck-security-scan-manifest-v1",
                "generatedAt": datetime.now(UTC).isoformat(),
                "sourceCommit": commit_result.stdout.strip(),
                "services": manifest_services,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    pip_audit = [sys.executable, "-m", "pip_audit", "-r", str(requirements), "--format", "json"]
    _run(pip_audit, cwd=compose_dir, output=output_dir / "pip-audit.json")
    _run(["pnpm", "audit", "--prod", "--json"], cwd=frontend_dir, output=output_dir / "pnpm-audit.json")


def main() -> int:
    args = parse_args()
    compose_file = Path(args.compose_file).resolve()
    output_dir = Path(args.output_dir).resolve()
    try:
        if args.generate:
            generate_evidence(
                compose_file=compose_file,
                output_dir=output_dir,
                frontend_dir=Path(args.frontend_dir).resolve(),
                requirements=Path(args.requirements).resolve(),
                skip_build=bool(args.skip_build),
            )
        report = validate_scan_directory(output_dir)
    except (RuntimeError, ValueError) as exc:
        report = {
            "schemaVersion": "aicheck-security-release-gate-v1",
            "generatedAt": datetime.now(UTC).isoformat(),
            "status": "fail",
            "services": [],
            "dependencyChecks": {},
            "failures": [str(exc)],
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "security-release-gate.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"security release gate: {report['status']} ({len(report['failures'])} failures)")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
