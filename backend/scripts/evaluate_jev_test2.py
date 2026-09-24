"""Live, read-only Jev claim probe over two user-approved test2 OCR files.

The complete OCR for each selected file is sent to TypeSafe. Run only when the
test2 data-egress approval applies. No API key or OCR text is saved in output.
This does not replace the 33 inspector labels or measure node verdict quality.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import time
from html import unescape
from pathlib import Path
from typing import Any

from libs.review_orchestrator.jev_claims import verify_finding_claims
from libs.review_orchestrator.jev_state import MAX_STATE_CHARS, scoped_document_states
from libs.review_orchestrator.jev_tables import business_rows, classify_review_tables

ROOT = Path(__file__).resolve().parents[2]
OCR_ROOT = ROOT / "output/two_project_node_eval_20260824/test2/ocr"
CASES = {
    "test2-020": [
        ("焊接工艺卡编号为JH-HJGYK-01", "supported"),
        ("焊接工艺评定报告编号为HP/P-2023-01", "supported"),
        ("施焊技术为GTAW+SMAW", "supported"),
        ("母材为20#", "supported"),
        ("焊接工艺卡编号为JH-HJGYK-02", "contradicted"),
        ("施焊技术为SAW", "contradicted"),
        ("母材为304", "contradicted"),
        ("焊工证书有效期至2029年1月1日", "not_in_materials"),
    ],
    "test2-019": [
        ("焊接工艺评定报告编号为HP/P-2023-01", "supported"),
        ("焊接方法为GTAW+SMAW", "supported"),
        ("焊接工艺评定报告编号为HP/P-2023-99", "contradicted"),
    ],
}


def evaluate_file(case_id: str, claims: list[tuple[str, str]]) -> dict[str, Any]:
    path = OCR_ROOT / f"{case_id}.md"
    raw = path.read_text(encoding="utf-8")
    version_id = f"EVAL-{case_id}"
    if len(raw) + 2000 > MAX_STATE_CHARS:
        raise ValueError(f"whole_document_over_safe_limit:{case_id}")
    state = {
        "documents": [{"id": version_id, "projectId": "EVAL-TEST2", "fileName": path.name}],
        "document_versions": [{"id": version_id, "documentId": version_id}],
        "ocr_parse_results": [{"documentVersionId": version_id,
                               "fragments": [{"pageNo": 1, "text": raw}]}],
    }
    review_run = {"projectId": "EVAL-TEST2", "nodeId": 25,
                  "inputDocumentVersionIds": [version_id]}
    drafts = [{"id": f"EVAL-F{i}", "title": "测试主张", "description": claim,
               "claims": [claim], "confidence": 0.9} for i, (claim, _) in enumerate(claims)]
    started = time.monotonic()
    result = verify_finding_claims(state, review_run, [], drafts)
    elapsed = round(time.monotonic() - started, 3)
    answers = [item["claims"][0] for item in result.get("findings") or []]
    items = [{"index": i + 1, "expected": expected, "actual": answer["choice"],
              "confidence": answer["confidence"], "exact": answer["choice"] == expected,
              "safe": answer["choice"] == "supported" if expected == "supported" else
                      answer["choice"] in {"contradicted", "not_in_materials", "needs_human"}}
             for i, ((_, expected), answer) in enumerate(zip(claims, answers))]
    return {"caseId": case_id, "inputChars": len(raw), "sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "status": result["status"], "elapsedSeconds": elapsed, "items": items,
            "exactCount": sum(item["exact"] for item in items), "safeCount": sum(item["safe"] for item in items)}


def evaluate_table_sample() -> dict[str, Any]:
    """Classify two complete tables while supplying the document's full OCR."""
    raw = (OCR_ROOT / "test2-019.md").read_text(encoding="utf-8")
    html_tables = re.findall(r"<table\b[^>]*>.*?</table>", raw, re.IGNORECASE | re.DOTALL)
    if len(html_tables) < 6:
        raise ValueError("test2_019_table_sample_missing")
    selected = []
    for source_index in (5, 6):
        rows = []
        for html_row in re.findall(r"<tr\b[^>]*>.*?</tr>", html_tables[source_index - 1],
                                   re.IGNORECASE | re.DOTALL):
            cells = [unescape(" ".join(re.sub(r"<[^>]+>", " ", cell).split()))
                     for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", html_row,
                                            re.IGNORECASE | re.DOTALL)]
            rows.append({f"列{index}": value for index, value in enumerate(cells, 1)})
        selected.append({"pageNo": 1, "normalizedRows": rows})
    version_id = "EVAL-test2-019"
    state = {
        "documents": [{"id": version_id, "projectId": "EVAL-TEST2", "fileName": "test2-019.md"}],
        "document_versions": [{"id": version_id, "documentId": version_id}],
        "ocr_parse_results": [{"documentVersionId": version_id,
                               "fragments": [{"pageNo": 1, "text": raw}], "tables": selected}],
    }
    review_run = {"projectId": "EVAL-TEST2", "nodeId": 25,
                  "inputDocumentVersionIds": [version_id]}
    full_states, _, overlong = scoped_document_states(state, review_run, [])
    if overlong:
        raise ValueError("test2_019_table_sample_over_safe_limit")
    started = time.monotonic()
    result = classify_review_tables(state, review_run)
    elapsed = round(time.monotonic() - started, 3)
    predictions = result.get("tables", {}).get(version_id, [])
    kept = business_rows(state["ocr_parse_results"][0], result, skip_mechanical=True)
    return {"status": result["status"], "stateChars": len(full_states[0]["state"]),
            "elapsedSeconds": elapsed, "sourceHtmlTableNumbers": [5, 6],
            "rowsPerTable": [len(table["normalizedRows"]) for table in selected],
            "tableTypes": [{"choice": row["tableType"]["choice"],
                            "confidence": row["tableType"]["confidence"]} for row in predictions],
            "mechanicalRowsRemoved": all(row not in kept for row in selected[1]["normalizedRows"]),
            "keptRowCount": len(kept)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-key", action="store_true", help="Read a test API key without echoing or saving it")
    parser.add_argument("--table-sample", action="store_true", help="Classify two complete tables in full test2 OCR")
    parser.add_argument("--tables-only", action="store_true", help="Skip repeated claim probes; requires --table-sample")
    args = parser.parse_args()
    if args.tables_only and not args.table_sample:
        parser.error("--tables-only requires --table-sample")
    if args.prompt_key:
        os.environ["AICHECK_JEV_API_KEY"] = getpass.getpass("Jev test API key: ").strip()
    if not os.environ.get("AICHECK_JEV_API_KEY"):
        parser.error("AICHECK_JEV_API_KEY is required")
    os.environ["AICHECK_JEV_ENABLED"] = "true"
    os.environ["AICHECK_JEV_DATA_EGRESS_APPROVED"] = "true"
    os.environ["AICHECK_JEV_CLAIM_SHADOW_ENABLED"] = "true"
    if args.table_sample:
        os.environ["AICHECK_JEV_TABLE_CLASSIFICATION_ENABLED"] = "true"
    for gate in ("AICHECK_JEV_CALIBRATION_APPROVED", "AICHECK_JEV_CLAIM_GATE_ENABLED"):
        os.environ.pop(gate, None)
    try:
        rows = [] if args.tables_only else [evaluate_file(case_id, claims) for case_id, claims in CASES.items()]
        table_sample = evaluate_table_sample() if args.table_sample else None
    finally:
        os.environ.pop("AICHECK_JEV_API_KEY", None)
    report = {"dataset": "user_approved_test2_complete_ocr", "model": "jev-1.13.0", "files": rows,
              "exactCount": sum(row["exactCount"] for row in rows),
              "safeCount": sum(row["safeCount"] for row in rows),
              "total": sum(len(row["items"]) for row in rows),
              **({"tableSample": table_sample} if table_sample else {})}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["safeCount"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
