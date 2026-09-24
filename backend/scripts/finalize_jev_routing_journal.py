"""Validate a checkpointed private Jev sweep and derive metadata/shadow artifacts."""

from __future__ import annotations

import argparse
import json
import os
import stat
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.evaluate_jev_document_routing import _shadows


def aggregate_journal(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not rows or rows[0].get("phase") != "manifest":
        raise ValueError("sweep_manifest_required")
    manifest = rows[0]
    reservations: dict[int, dict[str, Any]] = {}
    results: dict[int, dict[str, Any]] = {}
    errors = 0
    for row in rows[1:]:
        index = row.get("index")
        if type(index) is not int or index < 1:
            raise ValueError("invalid_sweep_index")
        phase = row.get("phase")
        if phase == "reserved":
            if index in reservations:
                raise ValueError("duplicate_sweep_reservation")
            reservations[index] = row
        elif phase == "result":
            if index in results:
                raise ValueError("duplicate_sweep_result")
            results[index] = row
        elif phase == "unexpected_error":
            errors += 1
        else:
            raise ValueError("invalid_sweep_phase")
    if set(results) - set(reservations):
        raise ValueError("sweep_result_without_reservation")
    shadows = []
    statuses = Counter()
    attempted = planned = 0
    elapsed = 0.0
    costs = []
    sent_documents = 0
    for index, row in sorted(results.items()):
        reservation = reservations[index]
        identity = ("projectId", "documentId", "documentVersionId")
        if any(row.get(key) != reservation.get(key) for key in identity):
            raise ValueError("sweep_identity_changed")
        report = row.get("report") or {}
        if report.get("send") is not True or len(report.get("shadows") or []) != 1:
            raise ValueError("live_single_document_report_required")
        shadow = report["shadows"][0]
        if any(shadow.get(key) != row.get(key) for key in identity):
            raise ValueError("sweep_shadow_identity_changed")
        if shadow.get("inputHash") != reservation.get("inputHash"):
            raise ValueError("sweep_input_hash_changed")
        expected = reservation.get("expectedRequestCount")
        if (type(expected) is not int or expected < 0
                or report.get("plannedRequestCount") != expected
                or type(report.get("attemptedRequestCount")) is not int
                or not 0 <= report["attemptedRequestCount"] <= expected):
            raise ValueError("sweep_request_count_mismatch")
        planned += expected
        attempted += report["attemptedRequestCount"]
        elapsed += float(report.get("elapsedSeconds") or 0)
        if report["attemptedRequestCount"]:
            sent_documents += 1
        if report.get("providerReportedCostUSD") is not None:
            costs.append(float(report["providerReportedCostUSD"]))
        statuses[shadow["status"]] += 1
        shadows.append(shadow)
    _shadows(shadows)
    completed = [row for row in shadows if row["status"] == "completed"]
    scores = [score for row in completed for score in row.get("nodeScores") or []]
    choices = Counter(score["choice"] for score in scores)
    complete = (not errors and len(reservations) == len(results)
                == manifest.get("documentCount")
                and planned == manifest.get("expectedRequestCount"))
    summary = {"schemaVersion": "jev-routing-evaluation-run-v1", "model": "jev-1.13.0",
               "send": True, "inputSnapshotSha256": manifest.get("snapshotSha256"),
               "selectedDocumentCount": len(results),
               "expectedDocumentCount": manifest.get("documentCount"),
               "plannedRequestCount": planned,
               "preflightRequestCount": manifest.get("expectedRequestCount"),
               "attemptedRequestCount": attempted,
               "unresolvedReservationCount": len(reservations) - len(results),
               "unexpectedErrorCount": errors,
               "statusCounts": dict(sorted(statuses.items())),
               "elapsedSeconds": round(elapsed, 3),
               "providerReportedCostUSD": round(sum(costs), 6) if len(costs) == sent_documents and costs else None,
               "costStatus": "provider_reported" if len(costs) == sent_documents and costs
               else "not_reported_by_api",
               "descriptiveRouting": {
                   "scoredNodePairs": len(scores), "choiceCounts": dict(sorted(choices.items())),
                   "yesAtLeast090": sum(score["choice"] == "yes" and score["confidence"] >= 0.90
                                       for score in scores),
                   "suggestedBindingCount": sum(len(row.get("suggestedNodeIds") or [])
                                                for row in completed),
                   "existingBindingCount": sum(len(row.get("existingNodeIds") or [])
                                               for row in completed),
                   "documentsWithBindingDifference": sum(bool(row.get("disagreementNodeIds"))
                                                         for row in completed),
                   "bindingPairDifferenceCount": sum(len(row.get("disagreementNodeIds") or [])
                                                     for row in completed),
                   "interpretation": "Existing bindings are a comparison baseline, not independent truth",
               },
               "completedSweep": complete}
    return summary, shadows


def _private_write(path: Path, body: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(body)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--shadows", type=Path, required=True)
    args = parser.parse_args()
    try:
        if stat.S_IMODE(args.journal.stat().st_mode) & 0o077:
            raise ValueError("private_journal_permissions_required")
        rows = [json.loads(line) for line in args.journal.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        summary, shadows = aggregate_journal(rows)
        _private_write(args.report, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        _private_write(args.shadows, "".join(json.dumps(row, ensure_ascii=False) + "\n"
                                             for row in shadows))
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"completedSweep": summary["completedSweep"],
                      "attemptedRequestCount": summary["attemptedRequestCount"],
                      "statusCounts": summary["statusCounts"]}, ensure_ascii=False))
    return 0 if summary["completedSweep"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
