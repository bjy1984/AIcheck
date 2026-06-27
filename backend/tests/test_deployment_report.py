from __future__ import annotations

import json
from argparse import Namespace

from scripts.deployment_report import DeploymentReportBuilder, markdown_report, write_outputs


def report_args(**overrides):
    values = {
        "strict_production": True,
        "include_live": False,
        "api_base": "http://api",
        "ocr_base": "http://ocr",
        "litellm_base": "http://litellm",
        "litellm_api_key": "sk-test",
        "project_id": "P-2026-HDCP-001",
        "roles": "admin,inspection,contractor",
        "skip_ocr": False,
        "skip_litellm": False,
        "write_probes": False,
        "ocr_object_probe": False,
        "litellm_provider_probes": False,
        "timeout": 1.0,
        "output_dir": None,
        "json": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_deployment_report_static_sections_pass_and_live_is_skipped() -> None:
    report = DeploymentReportBuilder(report_args()).build()

    assert report["schemaVersion"] == "aicheck-deployment-report-v1"
    assert report["ok"] is True
    sections = {section["name"]: section for section in report["sections"]}
    assert sections["deployment-config"]["ok"] is True
    assert sections["frontend-contract"]["ok"] is True
    assert sections["live-deployment"]["skipped"] is True
    assert any(check["name"] == "dockerfile.build-contract" for check in sections["deployment-config"]["checks"])
    assert any(check["name"] == "dockerfile.ocr-build-contract" for check in sections["deployment-config"]["checks"])
    assert any(check["name"] == "requirements.ocr-baseline" for check in sections["deployment-config"]["checks"])
    assert any(check["name"] == "compose.healthchecks" for check in sections["deployment-config"]["checks"])
    assert any(check["name"] == "compose.ocr-artifacts" for check in sections["deployment-config"]["checks"])
    assert any(check["name"] == "frontend.contract" for check in sections["frontend-contract"]["checks"])
    assert report["summary"]["fail"] == 0
    assert report["summary"]["skip"] == 1


def test_deployment_report_markdown_contains_summary() -> None:
    report = DeploymentReportBuilder(report_args()).build()
    markdown = markdown_report(report)

    assert "# AIcheck Deployment Acceptance Report" in markdown
    assert "| deployment-config | compose.services | PASS |" in markdown
    assert "Summary: total=" in markdown


def test_deployment_report_writes_json_and_markdown(tmp_path) -> None:
    report = DeploymentReportBuilder(report_args()).build()

    write_outputs(report, str(tmp_path))

    report_json = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    report_md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert report_json["ok"] is True
    assert report_json["schemaVersion"] == "aicheck-deployment-report-v1"
    assert "AIcheck Deployment Acceptance Report" in report_md
