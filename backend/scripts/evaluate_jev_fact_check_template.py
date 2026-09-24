"""Run the production certificate fact check (jev_fact_check) on fictional licences.

The boundary suite measured Jev on hand-written questions; this measures the
exact template the product sends. For each validity wording, the rule's
extracted end date is set to the correct value, to the start date the old
extractor produced, and to a date one year off; certificate number and holder
are always correct. Truth is known, so the report gives how many wrong dates
were flagged as suspect and how many correct facts were flagged by mistake.
Only fictional text is sent. The key is read from the terminal and kept only in
this process.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

from libs.review_orchestrator import jev_fact_check
from scripts import evaluate_jev_extraction_check as extraction

HOLDER = "示例管道安装有限公司"
CERT_NO = "TS3841999-2028"


def cases() -> list[dict[str, Any]]:
    rows = []
    for case_id, lines, truth, old_value in extraction.CASES:
        if not truth:
            continue
        text = "\n".join(extraction.HEAD + lines + extraction.TAIL)
        truth_date = date.fromisoformat(truth)
        claims = [("correct", truth), ("year_off", truth_date.replace(year=truth_date.year - 1).isoformat())]
        if old_value:
            claims.append(("old_extractor_start_date", old_value))
        for kind, claimed in claims:
            rows.append({"caseId": case_id, "kind": kind, "claimed": claimed, "text": text,
                         "wrongUntil": kind != "correct"})
    return rows


def _state(text: str) -> dict[str, Any]:
    return {"documents": [{"id": "D", "projectId": "SYN", "fileName": "synthetic.pdf"}],
            "versions": [{"id": "V", "documentId": "D"}],
            "ocr_parse_results": [{"id": "O", "documentVersionId": "V", "status": "success",
                                   "fragments": [{"pageNo": 1, "text": text}]}]}


def _verification(valid_until: str) -> dict[str, Any]:
    return {"atomicCheckId": "AC-SYN", "certificateType": "installation_license", "certificates": [{
        "certificateType": "installation_license", "holder": HOLDER, "certificateNo": CERT_NO,
        "validUntil": valid_until, "evidenceRefs": [{"documentVersionId": "V"}]}]}


def _until(row: dict[str, Any]) -> dict[str, Any]:
    return next(fact for fact in row["facts"] if fact["field"] == "validUntil")


def score(results: list[dict[str, Any]]) -> dict[str, Any]:
    wrong = [row for row in results if row["wrongUntil"]]
    right = [row for row in results if not row["wrongUntil"]]
    other = [fact for row in results for fact in row["facts"] if fact["field"] != "validUntil"]
    return {
        "wrongEndDateFlagged": f"{sum(_until(r).get('suspect') is True for r in wrong)}/{len(wrong)}",
        "oldExtractorErrorFlagged": "{}/{}".format(
            sum(_until(r).get("suspect") is True for r in wrong if r["kind"] == "old_extractor_start_date"),
            sum(r["kind"] == "old_extractor_start_date" for r in wrong)),
        "correctEndDateFlagged": f"{sum(_until(r).get('suspect') is True for r in right)}/{len(right)}",
        "correctNumberOrHolderFlagged": f"{sum(f.get('suspect') is True for f in other)}/{len(other)}",
        "lowConfidenceAnswers": f"{sum(f.get('lowConfidence') is True for r in results for f in r['facts'])}/"
                                f"{sum(len(r['facts']) for r in results)}",
        "failedRequests": sum(r["status"] != "completed" for r in results),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    rows = cases()
    if not args.send:
        print(json.dumps({"status": "plan_only", "requests": len(rows), "questions": len(rows) * 3}))
        return 0
    key = getpass.getpass("Jev test API key: ").strip()
    if not key:
        parser.error("jev_test_key_required")
    env = {"AICHECK_JEV_API_KEY": key, "AICHECK_JEV_ENABLED": "true", "AICHECK_JEV_DATA_EGRESS_APPROVED": "true",
           "AICHECK_JEV_FACT_CHECK_ENABLED": "true", "AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS": "SYN"}
    results = []
    with patch.dict(os.environ, env):
        for index, row in enumerate(rows, 1):
            print(f"\rcase {index}/{len(rows)}", end="", flush=True)
            outcome = jev_fact_check.check_certificate_facts(
                _state(row["text"]), {"projectId": "SYN", "reviewMode": "formal", "inputDocumentVersionIds": ["V"]},
                _verification(row["claimed"]))
            results.append({key: row[key] for key in ("caseId", "kind", "claimed", "wrongUntil")}
                           | {"status": outcome["status"], "facts": outcome["facts"]})
    print()
    report = {"schemaVersion": "jev-fact-check-template-v1", "fictionalInputsOnly": True,
              "templateVersion": jev_fact_check.TEMPLATE_VERSION, **score(results), "results": results}
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
