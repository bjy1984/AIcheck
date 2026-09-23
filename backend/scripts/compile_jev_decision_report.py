"""Recompute an OCR-only Jev decision report from private, version-bound artifacts.

The output has no OCR or model prompt. Missing live calls, inspector labels, or
provider billing remain explicit blockers; no threshold is approved here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.evaluate_jev_atomic_opinions import (
    candidates_from_state,
    evaluate_labels,
    r19_candidates_from_state,
)
from scripts.evaluate_jev_document_routing import _read_jsonl, _read_labels, evaluate_routing


def decision_report(*, routing_run: dict[str, Any] | None = None,
                    routing_shadows: list[dict[str, Any]] | None = None,
                    routing_labels: list[dict[str, Any]] | None = None,
                    atomic_run: dict[str, Any] | None = None,
                    atomic_labels: list[dict[str, Any]] | None = None,
                    r19_run: dict[str, Any] | None = None,
                    r19_labels: list[dict[str, Any]] | None = None,
                    billing: dict[str, Any] | None = None,
                    routing_preflight: dict[str, Any] | None = None,
                    input_snapshot_sha256: str | None = None) -> dict[str, Any]:
    blockers = []
    live = {}
    for name, run in (("routing", routing_run), ("atomic", atomic_run), ("r19", r19_run)):
        if not run or not run.get("send") or not run.get("attemptedRequestCount"):
            blockers.append(f"{name}_live_requests_missing")
        live[name] = {"attemptedRequestCount": int((run or {}).get("attemptedRequestCount") or 0),
                      "plannedRequestCount": int((run or {}).get("plannedRequestCount") or 0),
                      "elapsedSeconds": (run or {}).get("elapsedSeconds"),
                      "providerReportedCostUSD": (run or {}).get("providerReportedCostUSD"),
                      "statusCounts": (run or {}).get("statusCounts") or {}}
    routing = None
    if routing_shadows is not None and routing_labels is not None:
        routing = evaluate_routing(routing_shadows, routing_labels)
        if (routing["status"] != "ready_for_review"
                or routing["documents"]["completedInspectorLabeled"] != 28
                or routing["documents"]["staleInputHashLabeled"]):
            blockers.append("routing_28_document_truth_incomplete")
    else:
        blockers.append("routing_inspector_truth_missing")
    atomic = None
    if atomic_run is not None and atomic_labels is not None:
        prepared = candidates_from_state(atomic_run)
        atomic = evaluate_labels(prepared["candidates"], atomic_labels)
        if (prepared["status"] != "ready_for_inspector"
                or atomic["inspectorComparedCount"] != 33 or atomic["staleInputHashCount"]):
            blockers.append("atomic_33_inspector_truth_incomplete")
    else:
        blockers.append("atomic_inspector_truth_missing")
    r19 = None
    if r19_run is not None and r19_labels is not None:
        prepared = r19_candidates_from_state(r19_run)
        r19 = evaluate_labels(prepared["candidates"], r19_labels)
        if (prepared["status"] != "ready_for_inspector"
                or r19["inspectorComparedCount"] != prepared["candidateCount"]
                or r19["staleInputHashCount"]):
            blockers.append("r19_inspector_truth_incomplete")
    else:
        blockers.append("r19_inspector_truth_missing")
    if (not billing or billing.get("source") != "provider_invoice"
            or type(billing.get("amountUSD")) not in {int, float}
            or billing["amountUSD"] < 0 or not billing.get("invoiceRef")):
        blockers.append("provider_billing_unverified")
    input_capacity = None
    if routing_preflight is not None:
        statuses = Counter(row.get("status") for project in routing_preflight.get("projects") or []
                           for row in project.get("files") or [])
        input_capacity = {
            "projectCount": routing_preflight.get("projectCount"),
            "documentCount": routing_preflight.get("documentCount"),
            "readyCount": routing_preflight.get("readyCount"),
            "plannedRoutingRequestCount": routing_preflight.get("requestCount"),
            "ocrAttemptCount": routing_preflight.get("ocrAttemptCount"),
            "duplicateOcrVersionCount": routing_preflight.get("duplicateOcrVersionCount"),
            "invalidEvidenceLinks": routing_preflight.get("invalidEvidenceLinks") or {},
            "statusCounts": dict(sorted(statuses.items())),
        }
    return {"schemaVersion": "jev-ocr-only-decision-report-v1",
            "status": "ready_for_decision" if not blockers else "incomplete",
            "blockers": blockers, "model": "jev-1.13.0", "inputMode": "approved_ocr_only",
            "live": live, "routing": routing, "atomicRiskSample": atomic, "r19": r19,
            "inputSnapshotSha256": input_snapshot_sha256,
            "routingInputCapacity": input_capacity,
            "atomicDiscoveryStatusCounts": (atomic_run or {}).get("discoveryStatusCounts") or {},
            "billingUSD": billing.get("amountUSD") if billing and "provider_billing_unverified" not in blockers
            else None,
            "samplingCaveat": "16+17 risk-selected atomic cases are not population accuracy; routing truth covers 28 sampled documents",
            "formalVerdictChanged": False, "autoBindingEnabled": False,
            "releaseThresholdApproved": False}


def _private_json(path: Path) -> Any:
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("private_evaluation_file_permissions_required")
    return json.loads(path.read_text(encoding="utf-8"))


def _label_cases(path: Path) -> list[dict[str, Any]]:
    value = _private_json(path)
    return value["cases"] if isinstance(value, dict) and "cases" in value else value


def _private_write(path: Path, value: Any) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("routing-run", "routing-shadows", "routing-labels", "atomic-run",
                 "atomic-labels", "r19-run", "r19-labels", "billing"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--routing-preflight", type=Path)
    parser.add_argument("--input-snapshot", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        def optional(name: str) -> Any:
            path = getattr(args, name)
            return _private_json(path) if path else None

        for path in (args.routing_shadows, args.routing_labels):
            if path and stat.S_IMODE(path.stat().st_mode) & 0o077:
                raise ValueError("private_evaluation_file_permissions_required")
        if args.input_snapshot and stat.S_IMODE(args.input_snapshot.stat().st_mode) & 0o077:
            raise ValueError("private_snapshot_permissions_required")
        report = decision_report(
            routing_run=optional("routing_run"),
            routing_shadows=_read_jsonl(args.routing_shadows) if args.routing_shadows else None,
            routing_labels=_read_labels(args.routing_labels) if args.routing_labels else None,
            atomic_run=optional("atomic_run"),
            atomic_labels=_label_cases(args.atomic_labels) if args.atomic_labels else None,
            r19_run=optional("r19_run"),
            r19_labels=_label_cases(args.r19_labels) if args.r19_labels else None,
            billing=optional("billing"),
            routing_preflight=optional("routing_preflight"),
            input_snapshot_sha256=(hashlib.sha256(args.input_snapshot.read_bytes()).hexdigest()
                                   if args.input_snapshot else None),
        )
        _private_write(args.output, report)
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"status": report["status"], "blockers": report["blockers"],
                      "attemptedRequestCount": sum(row["attemptedRequestCount"]
                                                   for row in report["live"].values())}, ensure_ascii=False))
    return 0 if report["status"] == "ready_for_decision" else 2


if __name__ == "__main__":
    raise SystemExit(main())
