from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts.security_release_gate import REQUIRED_IMAGE_SERVICES, validate_scan_directory


def write_clean_evidence(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "scan-manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": "aicheck-security-scan-manifest-v1",
                "generatedAt": datetime.now(UTC).isoformat(),
                "sourceCommit": "abcdef1234567890",
                "composeSha256": "a" * 64,
                "frontendLockSha256": "b" * 64,
                "services": {
                    service: {
                        "imageId": f"sha256:{index:064x}",
                        "repoDigests": [f"registry.example/{service}@sha256:{index:064x}"],
                    }
                    for index, service in enumerate(REQUIRED_IMAGE_SERVICES, start=1)
                },
            }
        ),
        encoding="utf-8",
    )
    for service in REQUIRED_IMAGE_SERVICES:
        (directory / f"{service}.sbom.cdx.json").write_text(
            json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []}),
            encoding="utf-8",
        )
        (directory / f"{service}.trivy.json").write_text(
            json.dumps({"SchemaVersion": 2, "Results": []}),
            encoding="utf-8",
        )
    (directory / "pip-audit.json").write_text(json.dumps({"dependencies": []}), encoding="utf-8")
    (directory / "pnpm-audit.json").write_text(
        json.dumps(
            {
                "metadata": {
                    "vulnerabilities": {"critical": 0, "high": 0, "moderate": 0, "low": 0, "total": 0}
                }
            }
        ),
        encoding="utf-8",
    )


def test_security_release_gate_accepts_complete_clean_evidence(tmp_path: Path) -> None:
    write_clean_evidence(tmp_path)

    report = validate_scan_directory(tmp_path)

    assert report["status"] == "pass"
    assert report["failures"] == []
    assert len(report["services"]) == len(REQUIRED_IMAGE_SERVICES)


def test_security_release_gate_rejects_high_or_missing_evidence(tmp_path: Path) -> None:
    write_clean_evidence(tmp_path)
    vulnerable_service = REQUIRED_IMAGE_SERVICES[0]
    (tmp_path / f"{vulnerable_service}.trivy.json").write_text(
        json.dumps(
            {
                "SchemaVersion": 2,
                "Results": [{"Vulnerabilities": [{"VulnerabilityID": "CVE-TEST", "Severity": "HIGH"}]}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "pip-audit.json").unlink()

    report = validate_scan_directory(tmp_path)

    assert report["status"] == "fail"
    assert any(vulnerable_service in failure and "high=1" in failure for failure in report["failures"])
    assert any(failure.startswith("pip-audit:") for failure in report["failures"])
