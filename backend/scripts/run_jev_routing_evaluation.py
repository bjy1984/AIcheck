"""Controlled, read-only Jev routing probe for approved test2 or seven-project OCR.

Dry-run is the default. Sending requires an explicit --send, the three Jev test
environment gates, a bounded request budget, and a private metadata-only output.
This never writes a document binding, review result, or production state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import zlib
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from libs.business_pack import build_project_requirements, build_project_tree
from libs.db.seed import DEFAULT_BUSINESS_PACK, DEFAULT_MATERIAL_REVIEW_POINTS
from libs.jev_document_routing import (
    CONFIDENCE_FLOOR,
    MAX_ROUTING_BATCHES,
    QUESTION_BATCH_SIZE,
    _node_questions,
    routing_question_points,
)
from libs.jev_evaluation_input import approved_ocr_text
from libs.material_targeting import MANUAL_REJECTED
from libs.review_orchestrator.jev_client import MODEL, ask_jev, batch_jev_questions, jev_enabled
from scripts.preflight_jev_document_routing import DEFAULT_OCR_DIR, preflight_project_corpus

Ask = Callable[..., dict[str, Any]]


def test2_cases(ocr_dir: Path = DEFAULT_OCR_DIR) -> list[dict[str, Any]]:
    if not ocr_dir.is_dir():
        raise ValueError("test2_ocr_directory_missing")
    points = routing_question_points(
        DEFAULT_MATERIAL_REVIEW_POINTS, project_id="EVAL-TEST2",
        business_pack_id=DEFAULT_BUSINESS_PACK["id"],
        business_pack_version=DEFAULT_BUSINESS_PACK["version"],
        requirements=build_project_requirements(DEFAULT_BUSINESS_PACK, project_id="EVAL-TEST2"),
        tree_nodes=build_project_tree("EVAL-TEST2", DEFAULT_BUSINESS_PACK),
        configured_points=DEFAULT_MATERIAL_REVIEW_POINTS,
    )
    questions, node_ids, overlong_nodes = _node_questions(points)
    cases = []
    for path in sorted(ocr_dir.glob("*.md")):
        version_id = f"EVAL-{path.stem}"
        state = {"documents": [{"id": version_id, "projectId": "EVAL-TEST2", "fileName": path.name}],
                 "versions": [{"id": version_id, "documentId": version_id}],
                 "ocr_parse_results": [{"documentVersionId": version_id, "fragments": [
                     {"pageNo": 1, "text": path.read_text(encoding="utf-8")},
                 ]}]}
        cases.append({"state": state, "scope": {"projectId": "EVAL-TEST2", "nodeId": "待归属",
                     "inputDocumentVersionIds": [version_id]},
                     "projectId": "EVAL-TEST2", "documentId": version_id,
                     "documentVersionId": version_id, "questions": questions, "nodeIds": node_ids,
                     "overlongNodeIds": overlong_nodes, "existingNodeIds": [], "humanRejectedNodeIds": []})
    return cases


def snapshot_cases(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    preflight = preflight_project_corpus(snapshot, expected_project_count=7)
    if preflight["invalidEvidenceLinks"]:
        raise ValueError("invalid_project_evidence_links")
    projects = {str(row["id"]): row for row in snapshot["projects"]}
    versions = {str(row.get("id") or row.get("documentVersionId")): row for row in snapshot["versions"]}
    configured = snapshot.get("configuredPoints") or []
    routing_state = {key: snapshot.get(key) or []
                     for key in ("documents", "versions", "ocr_parse_results")}
    cases = []
    for project_id, project in sorted(projects.items()):
        points = routing_question_points(
            (snapshot.get("routingPointsByProject") or {}).get(project_id) or [],
            project_id=project_id,
            business_pack_id=str(project.get("businessPackId") or "engineering_inspection_v1"),
            business_pack_version=str(project.get("businessPackVersion") or ""),
            requirements=snapshot.get("requirements") or [], tree_nodes=snapshot.get("tree_nodes") or [],
            configured_points=configured,
        )
        questions, node_ids, overlong_nodes = _node_questions(points)
        for document in sorted((row for row in snapshot["documents"] if row.get("projectId") == project_id),
                               key=lambda row: str(row.get("id") or "")):
            document_id = str(document.get("id") or "")
            version_id = str(document.get("currentVersionId") or "")
            version = versions.get(version_id)
            links = [row for row in snapshot.get("node_evidence_links") or []
                     if row.get("projectId") == project_id and row.get("documentVersionId") == version_id]
            cases.append({"state": routing_state, "scope": {"projectId": project_id,
                         "tenantId": document.get("tenantId"), "nodeId": "待归属",
                         "inputDocumentVersionIds": [version_id]},
                         "projectId": project_id, "documentId": document_id,
                         "documentVersionId": version_id, "questions": questions, "nodeIds": node_ids,
                         "overlongNodeIds": overlong_nodes,
                         "invalidScope": not version or str(version.get("documentId") or "") != document_id,
                         "existingNodeIds": sorted({int(row.get("nodeId") or 0) for row in links
                                                    if row.get("manualStatus") != MANUAL_REJECTED}),
                         "humanRejectedNodeIds": sorted({int(row.get("nodeId") or 0) for row in links
                                                         if row.get("manualStatus") == MANUAL_REJECTED})})
    return cases


def _prepared(case: dict[str, Any]) -> dict[str, Any]:
    base = {key: case[key] for key in ("projectId", "documentId", "documentVersionId")}
    base["model"] = MODEL
    if case.get("invalidScope"):
        return {**base, "status": "invalid_scope", "requestCount": 0}
    if not case["questions"]:
        return {**base, "status": "no_templates", "requestCount": 0}
    status, full_state = approved_ocr_text(case["state"], case["scope"])
    if status != "ready":
        return {**base, "status": status, "requestCount": 0}
    try:
        batches = batch_jev_questions(full_state, case["questions"], max_questions=QUESTION_BATCH_SIZE)
    except ValueError:
        return {**base, "status": "request_overlong", "requestCount": 0}
    if len(batches) > MAX_ROUTING_BATCHES:
        return {**base, "status": "request_budget_exceeded", "requestCount": 0,
                "requiredBatchCount": len(batches)}
    input_hash = hashlib.sha256(json.dumps(
        [full_state, case["questions"]],
        ensure_ascii=False, sort_keys=True,
    ).encode()).hexdigest()
    return {**base, "status": "ready", "requestCount": len(batches), "inputHash": input_hash,
            "overlongNodeIds": case["overlongNodeIds"], "_state": full_state, "_batches": batches}


def run_cases(cases: list[dict[str, Any]], *, send: bool, limit: int, max_requests: int,
              ask: Ask = ask_jev) -> dict[str, Any]:
    if limit < 1 or max_requests < 1:
        raise ValueError("positive_case_and_request_limits_required")
    selected = cases[:limit]
    prepared = [_prepared(case) for case in selected]
    planned = sum(row["requestCount"] for row in prepared if row["status"] == "ready")
    if send and not jev_enabled():
        raise ValueError("fresh_test_jev_key_and_egress_gates_required")
    if send and planned > max_requests:
        raise ValueError("evaluation_request_budget_exceeded")
    shadows = []
    metrics = []
    attempted = 0
    for case, row in zip(selected, prepared):
        public = {key: value for key, value in row.items() if not key.startswith("_")}
        if row["status"] != "ready":
            shadows.append(public)
            continue
        if not send:
            shadows.append(public)
            continue
        answers: dict[str, Any] = {}
        try:
            for batch in row["_batches"]:
                attempted += 1
                answers.update(ask(row["_state"], batch, observe=metrics.append))
        except (OSError, RuntimeError, ValueError) as exc:
            shadows.append({**public, "status": "unavailable", "reason": type(exc).__name__})
            continue
        if set(answers) != set(case["questions"]):
            shadows.append({**public, "status": "invalid_response"})
            continue
        scores = sorted(({"nodeId": case["nodeIds"][key], "choice": answer["choice"],
                          "confidence": answer["confidence"]} for key, answer in answers.items()),
                        key=lambda item: item["nodeId"])
        rejected = set(case["humanRejectedNodeIds"])
        existing = set(case["existingNodeIds"])
        suggested = {item["nodeId"] for item in scores if item["choice"] == "yes"
                     and item["confidence"] >= CONFIDENCE_FLOOR and item["nodeId"] not in rejected}
        shadows.append({**public, "status": "partial" if case["overlongNodeIds"] else "completed",
                        "requestBatchCount": row["requestCount"], "nodeScores": scores,
                        "suggestedNodeIds": sorted(suggested), "existingNodeIds": sorted(existing),
                        "disagreementNodeIds": sorted(suggested ^ existing),
                        "humanRejectedNodeIds": sorted(rejected)})
    costs = [row["usage"].get("cost_usd", row["usage"].get("total_cost_usd")) for row in metrics]
    costs = [float(value) for value in costs if type(value) in {int, float}]
    return {"schemaVersion": "jev-routing-evaluation-run-v1", "model": MODEL,
            "send": send, "selectedDocumentCount": len(selected), "plannedRequestCount": planned,
            "attemptedRequestCount": attempted, "statusCounts": dict(sorted(Counter(
                row["status"] for row in shadows).items())),
            "elapsedSeconds": round(sum(row["elapsedSeconds"] for row in metrics), 3),
            "providerReportedCostUSD": round(sum(costs), 6) if costs and len(costs) == attempted else None,
            "costStatus": ("not_run" if not send else "provider_reported"
                           if costs and len(costs) == attempted else "not_reported_by_api"),
            "shadows": shadows}


def _private_write(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--test2", action="store_true")
    sources.add_argument("--snapshot", type=Path, help="Private zlib JSON seven-project OCR snapshot")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--case-id", action="append", help="Select an exact document ID; may be repeated")
    parser.add_argument("--max-requests", type=int, default=10)
    parser.add_argument("--send", action="store_true", help="Actually send approved test OCR to Jev")
    parser.add_argument("--output-shadows", type=Path, help="New 0600 JSONL file; no OCR text")
    parser.add_argument("--output-report", type=Path, help="New 0600 metadata report")
    args = parser.parse_args()
    if args.send and not args.output_shadows:
        parser.error("--send requires --output-shadows")
    try:
        if args.snapshot:
            if stat.S_IMODE(args.snapshot.stat().st_mode) & 0o077:
                raise ValueError("private_snapshot_permissions_required")
            cases = snapshot_cases(json.loads(zlib.decompress(args.snapshot.read_bytes())))
        else:
            cases = test2_cases()
        if args.case_id:
            chosen = set(args.case_id)
            selected = [case for case in cases if case["documentId"] in chosen]
            if len(selected) != len(chosen):
                raise ValueError("case_id_missing_or_ambiguous")
            cases = selected
        reserved: list[Path] = []
        if args.send:
            dry_run = run_cases(cases, send=False, limit=args.limit, max_requests=args.max_requests)
            if dry_run["plannedRequestCount"] > args.max_requests:
                raise ValueError("evaluation_request_budget_exceeded")
            if not jev_enabled():
                raise ValueError("fresh_test_jev_key_and_egress_gates_required")
            # Reserve output files before any paid call; a save-path failure must not
            # leave an unrecorded outbound evaluation.
            try:
                for path in (args.output_shadows, args.output_report):
                    if path:
                        _private_write(path, "")
                        reserved.append(path)
            except BaseException:
                for path in reserved:
                    path.unlink(missing_ok=True)
                raise
        try:
            report = run_cases(cases, send=args.send, limit=args.limit, max_requests=args.max_requests)
            if args.output_shadows:
                body = "".join(json.dumps(row, ensure_ascii=False) + "\n"
                               for row in report["shadows"] if row["status"] != "ready")
                if args.send:
                    args.output_shadows.write_text(body, encoding="utf-8")
                else:
                    _private_write(args.output_shadows, body)
            if args.output_report:
                body = json.dumps({key: value for key, value in report.items()
                                   if key != "shadows"}, ensure_ascii=False, indent=2) + "\n"
                if args.send:
                    args.output_report.write_text(body, encoding="utf-8")
                else:
                    _private_write(args.output_report, body)
        except BaseException:
            for path in reserved:
                path.unlink(missing_ok=True)
            raise
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({key: value for key, value in report.items() if key != "shadows"}, ensure_ascii=False, indent=2))
    return 0 if (not args.send or report["attemptedRequestCount"] > 0) and not report["statusCounts"].get(
        "unavailable") else 2


if __name__ == "__main__":
    raise SystemExit(main())
