"""Scoped typed NDT table rows with recorded source locations, shared by station E."""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from libs.review_input_data import selected_parse_results
from libs.review_workstations import digest


def _table_location(table: dict[str, Any]) -> dict[str, Any]:
    bbox = table.get("bbox")
    valid_bbox = (isinstance(bbox, list) and len(bbox) == 4
                  and all(type(value) in (int, float) and math.isfinite(value) for value in bbox)
                  and bbox[0] >= 0 and bbox[1] >= 0 and bbox[2] > bbox[0] and bbox[3] > bbox[1])
    page = table.get("pageNo")
    text = table.get("contentMarkdown")
    return {"pageNo": page if type(page) is int and page > 0 else None,
            "bbox": deepcopy(bbox) if valid_bbox else None,
            "quotedText": text if isinstance(text, str) and text.strip() else None}


def read_ndt_tables(state: dict[str, Any], run: dict[str, Any], schemas: dict[str, str], *, node_id: int) -> dict[str, list]:
    if (any(not isinstance(run.get(key), str) or not run[key].strip() for key in ("projectId", "tenantId"))
            or run.get("nodeId") != node_id):
        raise ValueError(f"r{node_id}_review_identity_incomplete_or_wrong_node")
    groups: dict[str, list] = {value: [] for value in schemas.values()}
    versions = {row["id"]: row for row in state.get("versions", []) if row.get("tenantId") == run.get("tenantId")}
    documents = {row["id"] for row in state.get("documents", [])
                 if row.get("projectId") == run.get("projectId") and row.get("tenantId") == run.get("tenantId")}
    for parse in selected_parse_results(state, {}, context={"reviewRun": run}):
        version_id = parse.get("documentVersionId")
        if (parse.get("tenantId") != run.get("tenantId") or versions.get(version_id, {}).get("documentId") not in documents):
            continue
        for table in parse.get("tables") or []:
            if not isinstance(table, dict) or table.get("businessSchema") not in schemas:
                continue
            for index, row in enumerate(table.get("normalizedRows") or []):
                if not isinstance(row, dict):
                    continue
                ref = {"documentVersionId": version_id, **_table_location(table),
                       "tableId": table.get("tableId") or table.get("id"), "rowIndex": index}
                ref["id"] = f"R{node_id}-REF-" + digest(ref)[:24]
                ref["evidenceRefId"] = ref["id"]
                ref["confidence"] = row.get("confidence", table.get("structureConfidence"))
                # Client/OCR supplied evidenceRefs cannot redirect a record to another document.
                record = {**deepcopy(row), "documentVersionId": version_id, "evidence": ref, "evidenceRefs": [ref]}
                groups[schemas[table["businessSchema"]]].append(record)
    return groups
