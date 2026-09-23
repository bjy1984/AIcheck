"""Offline Jev routing capacity preflight for approved OCR fixtures.

Reads complete Markdown OCR files and prints sizes/status only. It never loads
an API key, sends a request, or includes OCR text in the output.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.db.seed import DEFAULT_MATERIAL_REVIEW_POINTS
from libs.jev_document_routing import MAX_ROUTING_BATCHES, QUESTION_BATCH_SIZE, _node_questions
from libs.review_orchestrator.jev_client import batch_jev_questions
from libs.review_orchestrator.jev_state import scoped_document_states

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
    documents, _, overlong = scoped_document_states(state, scope, [])
    row: dict[str, Any] = {"caseId": path.stem, "ocrChars": len(raw), "questionCount": len(questions)}
    if overlong:
        return {**row, "status": "overlong_document", "requestCount": 0}
    if not documents or not documents[0]["hasOcrText"]:
        return {**row, "status": "no_ocr_text", "requestCount": 0}
    full_state = documents[0]["state"]
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


def preflight_directory(ocr_dir: Path, points: list[dict[str, Any]]) -> dict[str, Any]:
    questions, node_ids, overlong_nodes = _node_questions(points)
    files = [preflight_file(path, questions) for path in sorted(ocr_dir.glob("*.md"))]
    return {
        "schemaVersion": "jev-document-routing-preflight-v1",
        "source": str(ocr_dir), "templateCount": len(points), "nodeCount": len(node_ids),
        "overlongTemplateNodeIds": overlong_nodes,
        "fileCount": len(files), "readyCount": sum(row["status"] == "ready" for row in files),
        "requestCount": sum(row["requestCount"] for row in files), "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr-dir", type=Path, default=DEFAULT_OCR_DIR)
    args = parser.parse_args()
    if not args.ocr_dir.is_dir():
        parser.error("OCR directory does not exist")
    report = preflight_directory(args.ocr_dir, DEFAULT_MATERIAL_REVIEW_POINTS)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["fileCount"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
