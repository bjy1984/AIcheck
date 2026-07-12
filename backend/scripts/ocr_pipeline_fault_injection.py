from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.contracts.responses import server_time
from libs.db.repository import load_state
from scripts.ocr_accuracy_pipeline_batch import (
    TERMINAL_STATUSES,
    build_report,
    dispatch_case,
    load_cases,
    require_server_runtime,
    safe_campaign,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run isolated OCR/Qwen retry and idempotency fault probes.")
    parser.add_argument("--manifest", default="/validation/ocr_eval/scan_regression_manifest_v2.json")
    parser.add_argument("--source-root", default="/validation/Scan")
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--ocr-proxy", default="http://ocr-fault-proxy:18010")
    parser.add_argument("--qwen-proxy", default="http://qwen-fault-proxy:18020")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--output")
    return parser.parse_args()


def configure_proxy(base_url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(
        f"{base_url.rstrip('/')}/__fault__/configure",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def wait_for_case(
    manifest: dict[str, Any],
    case: dict[str, Any],
    campaign: str,
    *,
    timeout_seconds: int,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(1, timeout_seconds)
    report = build_report(manifest, [case], campaign)
    while report["items"][0]["status"] not in TERMINAL_STATUSES and time.monotonic() < deadline:
        time.sleep(max(0.5, poll_seconds))
        report = build_report(manifest, [case], campaign)
    report["timedOut"] = report["items"][0]["status"] not in TERMINAL_STATUSES
    return report


def scenario_passed(report: dict[str, Any]) -> bool:
    summary = report["summary"]
    return bool(
        not report.get("timedOut")
        and summary["systemFailures"] == 0
        and summary["applicableEngineFailureCount"] == 0
        and summary["duplicatePipelineRunCount"] == 0
        and summary["duplicateStageRunCount"] == 0
        and summary["invalidCandidateIdCount"] == 0
        and summary["unsupportedAttributionCount"] == 0
        and summary["formalEvidenceReadyCount"] == 0
    )


def main() -> int:
    args = parse_args()
    require_server_runtime()
    token = str(os.getenv("AICHECK_VALIDATION_FAULT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("AICHECK_VALIDATION_FAULT_TOKEN is required")
    manifest, cases = load_cases(Path(args.manifest), Path(args.source_root), 2)
    if len(cases) < 2:
        raise RuntimeError("fault injection requires two cold probe cases")
    base_campaign = safe_campaign(args.campaign)
    load_state()
    scenarios: list[dict[str, Any]] = []
    try:
        ocr_campaign = f"{base_campaign}-ocr-503"
        configure_proxy(args.ocr_proxy, token, {"mode": "status", "statusCode": 503, "remaining": 1})
        first_dispatch = dispatch_case(cases[0], ocr_campaign)
        duplicate_dispatch = dispatch_case(cases[0], ocr_campaign)
        ocr_report = wait_for_case(
            manifest,
            cases[0],
            ocr_campaign,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
        scenarios.append(
            {
                "scenario": "ocr_503_then_recover_with_duplicate_dispatch",
                "dispatches": [first_dispatch, duplicate_dispatch],
                "passed": scenario_passed(ocr_report),
                "report": ocr_report,
            }
        )

        ocr_timeout_campaign = f"{base_campaign}-ocr-timeout"
        configure_proxy(
            args.ocr_proxy,
            token,
            {
                "mode": "delay",
                "delaySeconds": float(os.getenv("AICHECK_VALIDATION_OCR_TIMEOUT_DELAY_SECONDS", "305")),
                "remaining": 1,
            },
        )
        ocr_timeout_dispatch = dispatch_case(cases[0], ocr_timeout_campaign)
        ocr_timeout_report = wait_for_case(
            manifest,
            cases[0],
            ocr_timeout_campaign,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
        scenarios.append(
            {
                "scenario": "ocr_timeout_then_retry",
                "dispatches": [ocr_timeout_dispatch],
                "passed": scenario_passed(ocr_timeout_report),
                "report": ocr_timeout_report,
            }
        )

        qwen_campaign = f"{base_campaign}-qwen-429"
        configure_proxy(args.qwen_proxy, token, {"mode": "status", "statusCode": 429, "remaining": 1})
        qwen_dispatch = dispatch_case(cases[1], qwen_campaign)
        qwen_report = wait_for_case(
            manifest,
            cases[1],
            qwen_campaign,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
        scenarios.append(
            {
                "scenario": "qwen_429_then_retry",
                "dispatches": [qwen_dispatch],
                "passed": scenario_passed(qwen_report),
                "report": qwen_report,
            }
        )

        qwen_timeout_campaign = f"{base_campaign}-qwen-timeout"
        configure_proxy(
            args.qwen_proxy,
            token,
            {
                "mode": "delay",
                "delaySeconds": float(os.getenv("AICHECK_VALIDATION_QWEN_TIMEOUT_DELAY_SECONDS", "185")),
                "remaining": 1,
            },
        )
        qwen_timeout_dispatch = dispatch_case(cases[1], qwen_timeout_campaign)
        qwen_timeout_report = wait_for_case(
            manifest,
            cases[1],
            qwen_timeout_campaign,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
        scenarios.append(
            {
                "scenario": "qwen_timeout_then_retry",
                "dispatches": [qwen_timeout_dispatch],
                "passed": scenario_passed(qwen_timeout_report),
                "report": qwen_timeout_report,
            }
        )
    finally:
        for proxy in [args.ocr_proxy, args.qwen_proxy]:
            try:
                configure_proxy(proxy, token, {"mode": "pass", "remaining": 0})
            except Exception:
                pass
    result = {
        "schemaVersion": "aicheck-ocr-pipeline-fault-injection@1",
        "generatedAt": server_time(),
        "campaign": base_campaign,
        "passed": all(item["passed"] for item in scenarios),
        "scenarios": scenarios,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
