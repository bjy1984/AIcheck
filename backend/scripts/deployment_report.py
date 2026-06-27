from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libs.contracts.responses import SERVER_TZ
from libs.db.seed import PROJECT_ID
from scripts.audit_frontend_contract import audit
from scripts.validate_deployment_config import DeploymentConfigValidator
from scripts.verify_deployment import DEFAULT_ROLES, DeploymentVerifier, VerifyConfig


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AIcheck deployment acceptance evidence report.")
    parser.add_argument("--strict-production", action="store_true")
    parser.add_argument("--include-live", action="store_true", help="Run live API/OCR/LiteLLM probes in addition to static checks.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--ocr-base", default="http://127.0.0.1:8010")
    parser.add_argument("--litellm-base", default="http://127.0.0.1:4001")
    parser.add_argument("--litellm-api-key", default="")
    parser.add_argument("--project-id", default=PROJECT_ID)
    parser.add_argument("--roles", default=",".join(DEFAULT_ROLES))
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--skip-litellm", action="store_true")
    parser.add_argument("--write-probes", action="store_true")
    parser.add_argument("--ocr-object-probe", action="store_true")
    parser.add_argument("--litellm-provider-probes", action="store_true")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--output-dir", help="Optional directory for report.json and report.md.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    return parser.parse_args()


class DeploymentReportBuilder:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args

    def build(self) -> dict[str, Any]:
        sections = [self.config_section(), self.frontend_contract_section()]
        if self.args.include_live:
            sections.append(self.live_section())
        else:
            sections.append(
                {
                    "name": "live-deployment",
                    "ok": True,
                    "skipped": True,
                    "checks": [
                        {
                            "name": "live.probes",
                            "status": "skip",
                            "detail": "Pass --include-live to run target API/OCR/LiteLLM probes.",
                            "data": None,
                        }
                    ],
                }
            )
        summary = summarize_sections(sections)
        return {
            "schemaVersion": "aicheck-deployment-report-v1",
            "generatedAt": datetime.now(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "strictProduction": bool(self.args.strict_production),
            "includeLive": bool(self.args.include_live),
            "ok": summary["fail"] == 0,
            "summary": summary,
            "sections": sections,
        }

    def config_section(self) -> dict[str, Any]:
        validator = DeploymentConfigValidator(
            BACKEND_ROOT / "docker-compose.yml",
            BACKEND_ROOT / "config/litellm.yaml",
            strict_production=bool(self.args.strict_production),
        )
        results = validator.run()
        return {
            "name": "deployment-config",
            "ok": all(item.ok for item in results),
            "checks": [asdict(item) for item in results],
        }

    def frontend_contract_section(self) -> dict[str, Any]:
        result = audit(
            REPO_ROOT / "frontend" / "src" / "api",
            ["aicheck/**/*.ts", "login/**/*.ts"],
            include_mock=False,
        )
        check = {
            "name": "frontend.contract",
            "status": "pass" if result.ok else "fail",
            "detail": f"frontend={result.frontend_count}, backend={result.backend_count}, missing={len(result.missing)}",
            "data": {
                "frontendCount": result.frontend_count,
                "backendCount": result.backend_count,
                "missing": [asdict(item) for item in result.missing],
            },
        }
        return {"name": "frontend-contract", "ok": result.ok, "checks": [check]}

    def live_section(self) -> dict[str, Any]:
        roles = [item.strip() for item in str(self.args.roles).split(",") if item.strip()]
        config = VerifyConfig(
            api_base=str(self.args.api_base).rstrip("/"),
            ocr_base=None if self.args.skip_ocr else str(self.args.ocr_base).rstrip("/"),
            litellm_base=None if self.args.skip_litellm else str(self.args.litellm_base).rstrip("/"),
            litellm_api_key=str(self.args.litellm_api_key or ""),
            project_id=str(self.args.project_id),
            roles=roles,
            strict_production=bool(self.args.strict_production),
            skip_ocr=bool(self.args.skip_ocr),
            skip_litellm=bool(self.args.skip_litellm),
            write_probes=bool(self.args.write_probes),
            ocr_object_probe=bool(self.args.ocr_object_probe),
            litellm_provider_probes=bool(self.args.litellm_provider_probes),
        )
        with httpx.Client(base_url=config.api_base, timeout=self.args.timeout) as api_client:
            storage_client = httpx.Client(timeout=self.args.timeout)
            ocr_client = httpx.Client(base_url=config.ocr_base, timeout=self.args.timeout) if config.ocr_base else None
            litellm_client = httpx.Client(base_url=config.litellm_base, timeout=self.args.timeout) if config.litellm_base else None
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
                storage_client.close()
                if ocr_client:
                    ocr_client.close()
                if litellm_client:
                    litellm_client.close()
        return {
            "name": "live-deployment",
            "ok": all(item.ok or item.status == "skip" for item in results),
            "checks": [asdict(item) for item in results],
        }


def summarize_sections(sections: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"pass": 0, "warn": 0, "fail": 0, "skip": 0, "total": 0}
    for section in sections:
        for check in section.get("checks", []):
            status = str(check.get("status") or "")
            if status in summary:
                summary[status] += 1
            summary["total"] += 1
    return summary


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# AIcheck Deployment Acceptance Report",
        "",
        f"- Generated at: {report['generatedAt']}",
        f"- Strict production: {report['strictProduction']}",
        f"- Live probes: {report['includeLive']}",
        f"- Overall: {'PASS' if report['ok'] else 'FAIL'}",
        "",
        "| Section | Check | Status | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for section in report["sections"]:
        for check in section.get("checks", []):
            lines.append(
                "| {section} | {name} | {status} | {detail} |".format(
                    section=section["name"],
                    name=check.get("name", ""),
                    status=str(check.get("status", "")).upper(),
                    detail=str(check.get("detail") or "").replace("|", "\\|"),
                )
            )
    lines.append("")
    summary = report["summary"]
    lines.append(
        f"Summary: total={summary['total']}, pass={summary['pass']}, warn={summary['warn']}, fail={summary['fail']}, skip={summary['skip']}."
    )
    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any], output_dir: str | None) -> None:
    if not output_dir:
        return
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "report.md").write_text(markdown_report(report), encoding="utf-8")


def main() -> int:
    args = parse_args()
    report = DeploymentReportBuilder(args).build()
    write_outputs(report, args.output_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(markdown_report(report), end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
