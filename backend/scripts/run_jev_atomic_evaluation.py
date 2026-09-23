"""Read-only OCR-only Jev atomic probe over pinned seven-project review runs.

Deterministic results and run identifiers stay local. No ReviewRun is created or
updated, and no verified rule check is sent to Jev. R19/Qwen is kept separate.
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

from libs.jev_evaluation_input import approved_ocr_text
from libs.review_orchestrator.jev_client import MODEL, ask_jev, batch_jev_questions, jev_enabled
from libs.review_orchestrator.jev_opinion import CHOICES, _r19_shadow_questions
from libs.review_orchestrator.r19_agent import r19_semantic_questions
from scripts.preflight_jev_document_routing import preflight_project_corpus

Ask = Callable[..., dict[str, Any]]


def _local_atomic_results(results: list[dict[str, Any]]) -> dict[str, str] | None:
    current: dict[str, str] = {}
    for result in results:
        for item in result.get("atomicCheckResults") or []:
            if not isinstance(item, dict) or not item.get("atomicCheckId"):
                continue
            atomic_id = str(item["atomicCheckId"])
            outcome = str(item.get("result") or "")
            if atomic_id in current and current[atomic_id] != outcome:
                return None
            current[atomic_id] = outcome
    return current


def discover_atomic_cases(snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    preflight_project_corpus(snapshot, expected_project_count=7)
    projects = {str(row.get("id")): row for row in snapshot["projects"]}
    results: dict[str, list[dict[str, Any]]] = {}
    for row in snapshot.get("rule_check_results") or []:
        results.setdefault(str(row.get("reviewRunId") or ""), []).append(row)
    cases = []
    counts = Counter()
    for run in sorted(snapshot.get("review_runs") or [], key=lambda row: str(row.get("reviewRunId") or "")):
        run_id = str(run.get("reviewRunId") or run.get("id") or "")
        node_id = int(run.get("nodeId") or 0)
        if not run_id or node_id == 0:
            counts["invalid_run_identity"] += 1
            continue
        if node_id == 19:
            counts["r19_separate_comparison"] += 1
            continue
        if node_id in {24, 29}:
            counts["multi_person_question_not_supported"] += 1
            continue
        if str(run.get("reviewMode") or "formal") != "formal":
            counts["nonformal_run"] += 1
            continue
        project = projects.get(str(run.get("projectId") or "")) or {}
        pack = project.get("businessPackSnapshot") or {}
        current = _local_atomic_results(results.get(run_id, []))
        if current is None:
            counts["contradictory_local_rule_results"] += 1
            continue
        checks = [item for item in pack.get("atomicChecks") or []
                  if isinstance(item, dict) and str(item.get("nodeId")) == str(node_id)
                  and str(item.get("id") or "") in current and str(item.get("instruction") or "").strip()]
        if not checks:
            counts["missing_frozen_checks_or_results"] += 1
            continue
        questions = {f"q{index}": {"type": "choice",
                                    "instructions": "只根据完整 OCR 原文判断此固定审查题；缺证据不能选符合："
                                    + str(check["instruction"]), "criteria": CHOICES}
                     for index, check in enumerate(checks)}
        known_local = [str(run.get("projectId") or ""), run_id]
        known_local.extend(str(item.get("id") or "") for item in snapshot["documents"])
        known_local.extend(str(item.get("currentVersionId") or "") for item in snapshot["documents"])
        known_local.extend(str(item.get("fileName") or "") for item in snapshot["documents"])
        if any(value and value in json.dumps(questions, ensure_ascii=False) for value in known_local):
            counts["question_contains_local_identifier"] += 1
            continue
        cases.append({"run": run, "projectId": run["projectId"], "reviewRunId": run_id,
                      "nodeId": node_id, "kind": "atomic", "questions": questions,
                      "atomicIds": {f"q{index}": str(check["id"]) for index, check in enumerate(checks)},
                      "currentResults": current, "state": snapshot})
        counts["eligible"] += 1
    return cases, dict(sorted(counts.items()))


def atomic_cases(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return discover_atomic_cases(snapshot)[0]


def r19_cases(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    preflight_project_corpus(snapshot, expected_project_count=7)
    results: dict[str, list[dict[str, Any]]] = {}
    for row in snapshot.get("rule_check_results") or []:
        results.setdefault(str(row.get("reviewRunId") or ""), []).append(row)
    cases = []
    for run in sorted(snapshot.get("review_runs") or [], key=lambda row: str(row.get("reviewRunId") or "")):
        if (int(run.get("nodeId") or 0) != 19 or str(run.get("reviewMode") or "formal") != "formal"
                or run.get("advisoryOnly")):
            continue
        run_id = str(run.get("reviewRunId") or run.get("id") or "")
        current = _local_atomic_results(results.get(run_id, []))
        if current is None:
            continue
        try:
            catalog = r19_semantic_questions(run)
        except ValueError:
            continue
        if len(catalog) != 8 or any(item["questionId"] not in current for item in catalog):
            continue
        questions = _r19_shadow_questions(catalog, {})
        known_local = [str(run.get("projectId") or ""), run_id]
        known_local.extend(str(item.get("currentVersionId") or "") for item in snapshot["documents"])
        if any(value and value in json.dumps(questions, ensure_ascii=False) for value in known_local):
            continue
        cases.append({"run": run, "projectId": run["projectId"], "reviewRunId": run_id,
                      "nodeId": 19, "kind": "r19", "questions": questions,
                      "r19Catalog": catalog, "currentResults": current, "state": snapshot})
    return cases


def _prepared(case: dict[str, Any]) -> dict[str, Any]:
    base = {key: case[key] for key in ("projectId", "reviewRunId", "nodeId")}
    status, text = approved_ocr_text(case["state"], case["run"])
    if status != "ready":
        return {**base, "status": status, "requestCount": 0}
    try:
        batches = batch_jev_questions(text, case["questions"])
    except ValueError:
        return {**base, "status": "request_overlong", "requestCount": 0}
    input_hash = hashlib.sha256(json.dumps([text, case["questions"]],
                                           ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {**base, "status": "ready", "requestCount": len(batches), "inputHash": input_hash,
            "_text": text, "_batches": batches}


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
    output_runs = []
    output_results = []
    statuses = Counter()
    metrics = []
    attempted = 0
    for case, row in zip(selected, prepared):
        status = row["status"]
        if status == "ready" and send:
            answers = {}
            try:
                for batch in row["_batches"]:
                    attempted += 1
                    answers.update(ask(row["_text"], batch, observe=metrics.append))
            except (OSError, RuntimeError, ValueError):
                status = "unavailable"
            else:
                status = "completed" if set(answers) == set(case["questions"]) else "invalid_response"
        else:
            answers = {}
        statuses[status] += 1
        opinion = {"status": status, "model": MODEL,
                   "comparisonSource": "r19_semantic_review" if case["kind"] == "r19" else "rule_engine",
                   "inputMode": "approved_ocr_only", "atomic": []}
        if status == "completed":
            if case["kind"] == "r19":
                for index, item in enumerate(case["r19Catalog"]):
                    applicability, judgment = answers[f"a{index}"], answers[f"j{index}"]
                    applies = applicability["choice"]
                    choice = ("not_applicable" if applies == "not_applicable" else
                              "evidence_insufficient" if applies == "unknown" else judgment["choice"])
                    confidence = (float(applicability["confidence"]) if applies != "applicable" else
                                  min(float(applicability["confidence"]), float(judgment["confidence"])))
                    opinion["atomic"].append({"atomicCheckId": item["questionId"], "choice": choice,
                                              "confidence": confidence, "applicability": applies,
                                              "instruction": item["instruction"],
                                              "sourceDocumentVersionIds": case["run"].get(
                                                  "inputDocumentVersionIds") or []})
            else:
                opinion["atomic"] = [
                    {"atomicCheckId": case["atomicIds"][key], "choice": answer["choice"],
                     "confidence": answer["confidence"],
                     "instruction": case["questions"][key]["instructions"],
                     "sourceDocumentVersionIds": case["run"].get("inputDocumentVersionIds") or []}
                    for key, answer in answers.items()
                ]
        output_runs.append({"reviewRunId": case["reviewRunId"], "projectId": case["projectId"],
                            "nodeId": case["nodeId"], "inputHash": row.get("inputHash"),
                            "jevSecondOpinions": opinion})
        atomic_ids = ([item["questionId"] for item in case["r19Catalog"]] if case["kind"] == "r19"
                      else list(case["atomicIds"].values()))
        output_results.append({"reviewRunId": case["reviewRunId"], "atomicCheckResults": [
            {"atomicCheckId": atomic_id, "result": case["currentResults"][atomic_id]}
            for atomic_id in atomic_ids]})
    costs = [row.get("usage", {}).get("cost_usd", row.get("usage", {}).get("total_cost_usd"))
             for row in metrics]
    costs = [float(value) for value in costs if type(value) in {int, float}]
    return {"schemaVersion": "jev-atomic-ocr-only-evaluation-v1", "model": MODEL,
            "send": send, "selectedRunCount": len(selected), "plannedRequestCount": planned,
            "attemptedRequestCount": attempted, "statusCounts": dict(sorted(statuses.items())),
            "elapsedSeconds": round(sum(row["elapsedSeconds"] for row in metrics), 3),
            "providerReportedCostUSD": round(sum(costs), 6) if len(costs) == attempted and costs else None,
            "review_runs": output_runs, "rule_check_results": output_results}


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
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--mode", choices=("atomic", "r19"), default="atomic")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--run-id", action="append", help="Exact ReviewRun ID; may be repeated")
    parser.add_argument("--max-requests", type=int, default=10)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if stat.S_IMODE(args.snapshot.stat().st_mode) & 0o077:
            raise ValueError("private_snapshot_permissions_required")
        snapshot = json.loads(zlib.decompress(args.snapshot.read_bytes()))
        if args.mode == "r19":
            cases, discovery_counts = r19_cases(snapshot), {}
        else:
            cases, discovery_counts = discover_atomic_cases(snapshot)
        if args.run_id:
            chosen = set(args.run_id)
            cases = [case for case in cases if case["reviewRunId"] in chosen]
            if len(cases) != len(chosen):
                raise ValueError("run_id_missing_or_ambiguous")
        if args.send and not jev_enabled():
            raise ValueError("fresh_test_jev_key_and_egress_gates_required")
        dry_run = run_cases(cases, send=False, limit=args.limit, max_requests=args.max_requests)
        if args.send and dry_run["plannedRequestCount"] > args.max_requests:
            raise ValueError("evaluation_request_budget_exceeded")
        _private_write(args.output, {"status": "reserved_before_outbound"} if args.send else {})
        report = run_cases(cases, send=args.send, limit=args.limit, max_requests=args.max_requests)
        report["discoveryStatusCounts"] = discovery_counts
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({key: value for key, value in report.items()
                      if key not in {"review_runs", "rule_check_results"}}, ensure_ascii=False))
    return 0 if (not args.send or report["attemptedRequestCount"] > 0) and not report["statusCounts"].get(
        "unavailable") else 2


if __name__ == "__main__":
    raise SystemExit(main())
