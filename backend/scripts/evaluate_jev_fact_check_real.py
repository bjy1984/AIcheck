"""Known-answer fact check on real certificate OCR from the local seven-project snapshot.

The truth is fixed by construction, not by a model. For every certificate the
rules extracted, a value that is literally written in its source document is a
"yes" claim; injected values are "no" claims: the start date of a validity
range given as its end (the R02-02 error), the end date shifted by a year, a
date, number or holder taken from another certificate in the same document,
and a mutated certificate number. Correct claims and each kind of wrong claim
go in separate requests, as production asks one value per field. Questions
use the production template (jev_fact_check). Real OCR is sent to Jev: run
only with the owner's approval. The key is read from the terminal and kept
only in this process; the report is written 0600 outside the repository.
"""

from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import time
import zlib
from datetime import date
from pathlib import Path
from typing import Any

from libs.review_orchestrator.certificate_facts import (
    CERTIFICATE_NODE_PROFILES,
    build_certificate_facts,
)
from libs.review_orchestrator.jev_fact_check import (
    certificate_fact_items,
    check_facts,
    locate_value,
)

SCHEMA_VERSION = "jev-fact-check-real-v1"
FIELDS = ("validUntil", "validFrom", "certificateNo", "holder")


def load_snapshot(path: Path) -> dict[str, Any]:
    snapshot = json.loads(zlib.decompress(path.read_bytes()))
    if snapshot.get("source") != "read_only_seven_project_ocr_snapshot":
        raise ValueError("approved_seven_project_snapshot_required")
    return restore_version_tenants(snapshot)


def restore_version_tenants(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Give each version its document's tenant, as the database row has it.

    Snapshots exported before 2026-09-24 kept only id/documentId for versions.
    Every fact builder that checks the version tenant (all R35+ nodes, through
    source_coverage and ndt_table_facts) then rejected every source as
    "missing or ambiguous", so nothing after R34 was ever extracted.
    """
    tenants = {str(row.get("id")): row.get("tenantId") for row in snapshot.get("documents") or []}
    for version in snapshot.get("versions") or []:
        if version.get("tenantId") is None and tenants.get(str(version.get("documentId"))):
            version["tenantId"] = tenants[str(version.get("documentId"))]
    return snapshot


def certificates(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Every certificate the rules extract from the snapshot, with its single source version."""
    rows = []
    for project in snapshot["projects"]:
        for node_id in sorted(CERTIFICATE_NODE_PROFILES):
            versions = sorted({str(link["documentVersionId"]) for link in snapshot.get("node_evidence_links") or []
                               if link.get("projectId") == project["id"] and int(link.get("nodeId") or 0) == node_id
                               and link.get("documentVersionId")})
            if not versions:
                continue
            facts = build_certificate_facts(snapshot, project["id"], node_id, versions)
            for cert in (facts.get("certificateFacts") or {}).get("certificates") or []:
                sources = sorted({str(ref.get("documentVersionId")) for ref in cert.get("evidence") or []
                                  if isinstance(ref, dict) and ref.get("documentVersionId")})
                if len(sources) == 1:
                    rows.append({"projectId": project["id"], "nodeId": node_id, "version": sources[0],
                                 "tenantId": project.get("tenantId"), "cert": cert})
    return rows


def _shift_year(value: str, years: int) -> str | None:
    try:
        parsed = date.fromisoformat(value)
        return parsed.replace(year=parsed.year + years).isoformat()
    except ValueError:
        return None


def _mutate_number(value: str) -> str | None:
    digits = [index for index, char in enumerate(value) if char.isdigit()]
    if not digits:
        return None
    index = digits[-1]
    return value[:index] + str((int(value[index]) + 3) % 10) + value[index + 1:]


def claims(rows: list[dict[str, Any]], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Known-answer claims: literal values are true; injected values are false."""
    by_version: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_version.setdefault(row["version"], []).append(row)
    output = []
    for row in rows:
        cert, run = row["cert"], {"projectId": row["projectId"], "tenantId": row["tenantId"]}
        others = [other["cert"] for other in by_version[row["version"]] if other is not row]
        for field in FIELDS:
            value = str(cert.get(field) or "").strip()
            if value and locate_value(snapshot, run, [row["version"]], field, value):
                output.append({**row, "field": field, "claimed": value, "kind": "literal_value", "expected": "yes"})
        wrong: list[tuple[str, str, str | None]] = [
            ("validUntil", "range_start_as_end", cert.get("validFrom")
             if cert.get("validFrom") and cert.get("validFrom") != cert.get("validUntil") else None),
            ("validUntil", "end_shifted_one_year", _shift_year(str(cert.get("validUntil") or ""), -1)
             if cert.get("validUntil") else None),
            ("certificateNo", "mutated_number", _mutate_number(str(cert.get("certificateNo") or ""))
             if cert.get("certificateNo") else None),
        ]
        for other in others:
            for field, kind in (("validUntil", "other_certificate_date"), ("certificateNo", "other_certificate_number"),
                                ("holder", "other_certificate_holder")):
                if other.get(field) and other.get(field) != cert.get(field):
                    wrong.append((field, kind, str(other[field])))
        for field, kind, value in wrong:
            if value and value != cert.get(field):
                output.append({**row, "field": field, "claimed": str(value), "kind": kind, "expected": "no"})
    return output


def _requests(claim_rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """One request per (document, variant): true claims together, each wrong kind on its own."""
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in claim_rows:
        variant = "true" if row["expected"] == "yes" else row["kind"]
        slot = 0
        while any(existing["field"] == row["field"] and existing["cert"] is row["cert"]
                  for existing in groups.get((row["version"], variant, slot), [])):
            slot += 1
        groups.setdefault((row["version"], variant, slot), []).append(row)
    return [groups[key] for key in sorted(groups)]


def _items(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for row in group:
        cert = {**row["cert"], row["field"]: row["claimed"], "evidenceRefs": [{"documentVersionId": row["version"]}]}
        verification = {"certificateType": cert.get("certificateType"),
                        "certificates": [cert]}
        items.extend(item for item in certificate_fact_items(verification) if item["field"] == row["field"])
    return items


def _wilson(hits: int, total: int) -> str:
    if not total:
        return "n/a"
    p, z = hits / total, 1.96
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return f"{hits}/{total} ({max(centre - half, 0):.0%}–{min(centre + half, 1):.0%})"


def score(results: list[dict[str, Any]]) -> dict[str, Any]:
    answered = [row for row in results if row.get("choice")]
    wrong = [row for row in answered if row["expected"] == "no"]
    right = [row for row in answered if row["expected"] == "yes"]
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for row in wrong:
        by_kind.setdefault(row["kind"], []).append(row)
    return {
        "claims": len(results), "answered": len(answered),
        "unanswered": {status: sum(row.get("status") == status for row in results)
                       for status in sorted({str(row.get("status")) for row in results if not row.get("choice")})},
        "wrongFlaggedAsSuspect": _wilson(sum(bool(row.get("suspect")) for row in wrong), len(wrong)),
        "wrongByKind": {kind: _wilson(sum(bool(row.get("suspect")) for row in rows), len(rows))
                        for kind, rows in sorted(by_kind.items())},
        "correctFlaggedAsSuspect": _wilson(sum(bool(row.get("suspect")) for row in right), len(right)),
        "correctConfirmed": _wilson(sum(row.get("choice") == "yes" for row in right), len(right)),
        "lowConfidenceShare": _wilson(sum(bool(row.get("lowConfidence")) for row in answered), len(answered)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    os.environ["AICHECK_CERT_PLATFORM_VERIFY"] = "off"
    snapshot = load_snapshot(args.snapshot)
    rows = claims(certificates(snapshot), snapshot)
    groups = _requests(rows)
    planned = {"certificates": len({id(row["cert"]) for row in rows}), "documents": len({row["version"] for row in rows}),
               "claims": len(rows), "trueClaims": sum(row["expected"] == "yes" for row in rows),
               "requests": len(groups)}
    if not args.send:
        print(json.dumps({"status": "plan_only", **planned}, ensure_ascii=False))
        return 0
    key = getpass.getpass("Jev test API key: ").strip()
    if not key:
        parser.error("jev_test_key_required")
    env = {"AICHECK_JEV_API_KEY": key, "AICHECK_JEV_ENABLED": "true", "AICHECK_JEV_DATA_EGRESS_APPROVED": "true",
           "AICHECK_JEV_FACT_CHECK_ENABLED": "true"}
    previous = {name: os.environ.get(name) for name in [*env, "AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS"]}
    results: list[dict[str, Any]] = []
    started = time.monotonic()
    try:
        os.environ.update(env)
        for index, group in enumerate(groups, 1):
            print(f"\rrequest {index}/{len(groups)}", end="", flush=True)
            head = group[0]
            os.environ["AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS"] = head["projectId"]
            run = {"projectId": head["projectId"], "tenantId": head["tenantId"], "reviewMode": "formal",
                   "inputDocumentVersionIds": [head["version"]]}
            outcome = check_facts(snapshot, run, _items(group))
            answers = outcome.get("facts") or []
            for row, answer in zip(group, answers + [{}] * (len(group) - len(answers)), strict=True):
                results.append({key: row[key] for key in ("projectId", "nodeId", "version", "field", "claimed",
                                                          "kind", "expected")}
                               | {name: answer.get(name) for name in ("status", "choice", "confidence", "suspect",
                                                                      "lowConfidence")}
                               | {"requestStatus": outcome.get("status")})
        print()
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    report = {"schemaVersion": SCHEMA_VERSION, "realOcr": True, "snapshot": str(args.snapshot), **planned,
              "wallSeconds": round(time.monotonic() - started, 1), **score(results), "results": results}
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
