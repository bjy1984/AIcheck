"""Offline Jev routing capacity preflight for approved OCR fixtures.

Reads complete Markdown OCR files and prints sizes/status only. It never loads
an API key, sends a request, or includes OCR text in the output.
"""

from __future__ import annotations

import argparse
import json
import zlib
from collections import Counter
from pathlib import Path
from typing import Any

from libs.business_pack import build_project_requirements, build_project_tree
from libs.db.seed import DEFAULT_BUSINESS_PACK, DEFAULT_MATERIAL_REVIEW_POINTS
from libs.jev_document_routing import (
    MAX_ROUTING_BATCHES,
    QUESTION_BATCH_SIZE,
    _node_questions,
    routing_question_points,
)
from libs.jev_evaluation_input import approved_ocr_text
from libs.review_orchestrator.jev_client import batch_jev_questions

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OCR_DIR = ROOT / "output/two_project_node_eval_20260824/test2/ocr"


def preflight_file(path: Path, questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    state = {
        "documents": [{"id": "D", "projectId": "EVAL", "fileName": path.name}],
        "versions": [{"id": "V", "documentId": "D"}],
        "ocr_parse_results": [{"documentVersionId": "V", "fragments": [
            {"pageNo": 1, "text": raw},
        ]}],
    }
    scope = {"projectId": "EVAL", "nodeId": "待归属", "inputDocumentVersionIds": ["V"]}
    row: dict[str, Any] = {"caseId": path.stem, "ocrChars": len(raw), "questionCount": len(questions)}
    status, full_state = approved_ocr_text(state, scope)
    if status != "ready":
        return {**row, "status": status, "requestCount": 0}
    row["stateChars"] = len(full_state)
    try:
        batches = batch_jev_questions(full_state, questions, max_questions=QUESTION_BATCH_SIZE)
    except ValueError:
        return {**row, "status": "request_overlong", "requestCount": 0}
    if len(batches) > MAX_ROUTING_BATCHES:
        return {**row, "status": "request_budget_exceeded", "requestCount": 0,
                "requiredBatchCount": len(batches)}
    return {**row, "status": "ready", "requestCount": len(batches),
            "largestBatchQuestions": max(map(len, batches), default=0)}


def preflight_directory(ocr_dir: Path, points: list[dict[str, Any]], *,
                        requirements: list[dict[str, Any]] | None = None,
                        tree_nodes: list[dict[str, Any]] | None = None,
                        project_id: str = "EVAL", business_pack_id: str = "engineering_inspection_v1",
                        business_pack_version: str = "") -> dict[str, Any]:
    if requirements is not None and tree_nodes is not None:
        points = routing_question_points(
            points, project_id=project_id, business_pack_id=business_pack_id,
            requirements=requirements, tree_nodes=tree_nodes, configured_points=points,
            business_pack_version=business_pack_version,
        )
    questions, node_ids, overlong_nodes = _node_questions(points)
    files = [preflight_file(path, questions) for path in sorted(ocr_dir.glob("*.md"))]
    return {
        "schemaVersion": "jev-document-routing-preflight-v1",
        "source": str(ocr_dir), "templateCount": len(points), "nodeCount": len(node_ids),
        "overlongTemplateNodeIds": overlong_nodes,
        "fileCount": len(files), "readyCount": sum(row["status"] == "ready" for row in files),
        "requestCount": sum(row["requestCount"] for row in files), "files": files,
    }


def preflight_project_corpus(snapshot: dict[str, Any], *, expected_project_count: int | None = None) -> dict[str, Any]:
    """Size frozen project OCR for routing without exporting answers or calling Jev."""
    if snapshot.get("source") != "read_only_seven_project_ocr_snapshot":
        raise ValueError("read_only_project_ocr_snapshot_required")
    projects = {str(row.get("id")): row for row in snapshot.get("projects") or [] if isinstance(row, dict)}
    documents = {str(row.get("id")): row for row in snapshot.get("documents") or [] if isinstance(row, dict)}
    versions = {str(row.get("id") or row.get("documentVersionId")): row
                for row in snapshot.get("versions") or [] if isinstance(row, dict)}
    if (not projects or len(projects) != len(snapshot.get("projects") or [])
            or len(documents) != len(snapshot.get("documents") or [])
            or len(versions) != len(snapshot.get("versions") or [])
            or (expected_project_count is not None and len(projects) != expected_project_count)):
        raise ValueError("invalid_project_corpus_identity")
    if (set(snapshot.get("routingPointsByProject") or {}) != set(projects)
            or any(str(row.get("projectId") or "") not in projects for row in documents.values())
            or any(str(row.get("documentId") or "") not in documents for row in versions.values())
            or any(str(row.get("documentVersionId") or "") not in versions
                   for row in snapshot.get("ocr_parse_results") or [] if isinstance(row, dict))):
        raise ValueError("project_corpus_scope_mismatch")
    parse_counts = Counter(str(row.get("documentVersionId")) for row in snapshot.get("ocr_parse_results") or []
                           if isinstance(row, dict))
    invalid_links = Counter()
    routing_state = {key: snapshot.get(key) or []
                     for key in ("documents", "versions", "ocr_parse_results")}
    for link in snapshot.get("node_evidence_links") or []:
        if not isinstance(link, dict):
            invalid_links["invalid_row"] += 1
            continue
        version = versions.get(str(link.get("documentVersionId") or ""))
        document = documents.get(str((version or {}).get("documentId") or ""))
        if version is None:
            invalid_links["missing_version"] += 1
        elif document is None:
            invalid_links["missing_document"] += 1
        elif str(document.get("projectId") or "") != str(link.get("projectId") or ""):
            invalid_links["wrong_project"] += 1
    project_rows: list[dict[str, Any]] = []
    for project_id, project in sorted(projects.items()):
        configured = snapshot.get("configuredPoints") or []
        points = routing_question_points(
            (snapshot.get("routingPointsByProject") or {}).get(project_id) or [],
            project_id=project_id, business_pack_id=str(project.get("businessPackId") or "engineering_inspection_v1"),
            business_pack_version=str(project.get("businessPackVersion") or ""),
            requirements=snapshot.get("requirements") or [], tree_nodes=snapshot.get("tree_nodes") or [],
            configured_points=configured,
        )
        questions, node_ids, overlong_nodes = _node_questions(points)
        files: list[dict[str, Any]] = []
        for document in sorted((row for row in documents.values() if row.get("projectId") == project_id),
                               key=lambda row: str(row.get("id") or "")):
            version_id = str(document.get("currentVersionId") or "")
            version = versions.get(version_id)
            row: dict[str, Any] = {"documentId": str(document.get("id") or ""),
                                   "documentVersionId": version_id, "requestCount": 0}
            if not version or str(version.get("documentId") or "") != row["documentId"]:
                row["status"] = "invalid_scope"
            elif not questions:
                row["status"] = "no_templates"
            else:
                scope = {"projectId": project_id, "tenantId": document.get("tenantId"),
                         "nodeId": "待归属", "inputDocumentVersionIds": [version_id]}
                status, full_state = approved_ocr_text(routing_state, scope)
                if status != "ready":
                    row["status"] = status
                else:
                    try:
                        batches = batch_jev_questions(full_state, questions,
                                                      max_questions=QUESTION_BATCH_SIZE)
                    except ValueError:
                        row["status"] = "request_overlong"
                    else:
                        row["requestCount"] = len(batches)
                        row["status"] = ("request_budget_exceeded" if len(batches) > MAX_ROUTING_BATCHES
                                         else "partial_templates" if overlong_nodes else "ready")
            files.append(row)
        statuses = Counter(row["status"] for row in files)
        project_rows.append({"projectId": project_id, "documentCount": len(files),
                             "nodeCount": len(node_ids), "templateCount": len(points),
                             "overlongTemplateNodeIds": overlong_nodes,
                             "statusCounts": dict(sorted(statuses.items())),
                             "requestCount": sum(row["requestCount"] for row in files if row["status"] == "ready"),
                             "files": files})
    return {
        "schemaVersion": "jev-project-corpus-preflight-v1",
        "projectCount": len(projects), "documentCount": len(documents),
        "readyCount": sum(row["statusCounts"].get("ready", 0) for row in project_rows),
        "ocrAttemptCount": sum(parse_counts.values()),
        "duplicateOcrVersionCount": sum(count > 1 for count in parse_counts.values()),
        "evidenceLinkCount": len(snapshot.get("node_evidence_links") or []),
        "invalidEvidenceLinks": dict(sorted(invalid_links.items())),
        "requestCount": sum(row["requestCount"] for row in project_rows),
        "projects": project_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr-dir", type=Path, default=DEFAULT_OCR_DIR)
    parser.add_argument("--snapshot", type=Path, help="Private zlib-compressed JSON project OCR snapshot")
    parser.add_argument("--expected-project-count", type=int)
    parser.add_argument("--output", type=Path, help="Write a metadata-only report to this path")
    args = parser.parse_args()
    if args.snapshot:
        report = preflight_project_corpus(
            json.loads(zlib.decompress(args.snapshot.read_bytes())),
            expected_project_count=args.expected_project_count,
        )
        if args.output:
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["invalidEvidenceLinks"] else 2
    if not args.ocr_dir.is_dir():
        parser.error("OCR directory does not exist")
    report = preflight_directory(
        args.ocr_dir, DEFAULT_MATERIAL_REVIEW_POINTS,
        requirements=build_project_requirements(DEFAULT_BUSINESS_PACK, project_id="EVAL"),
        tree_nodes=build_project_tree("EVAL", DEFAULT_BUSINESS_PACK),
        project_id="EVAL", business_pack_id=DEFAULT_BUSINESS_PACK["id"],
        business_pack_version=DEFAULT_BUSINESS_PACK["version"],
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["fileCount"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
