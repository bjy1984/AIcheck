"""Scoped typed NDT table rows with recorded source locations, shared by station E."""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from libs.review_input_data import selected_parse_results
from libs.review_workstations import digest
from libs.table_schema_mapping import classify_table, load_signatures, map_row


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


_SIGNATURES: list[dict[str, Any]] | None = None


def _signatures() -> list[dict[str, Any]]:
    global _SIGNATURES
    if _SIGNATURES is None:
        _SIGNATURES = load_signatures()
    return _SIGNATURES


def _signature_for(table: dict[str, Any], schemas: dict[str, str]) -> dict[str, Any] | None:
    """只在本次读取要的 schema 里认；认出别的表结构对这个节点没有意义。"""
    name = classify_table(table, _signatures())
    if name is None or name not in schemas:
        return None
    return next(item for item in _signatures() if item["businessSchema"] == name)


def _mapped_payload(row: dict[str, Any], signature: dict[str, Any], run: dict[str, Any], version_id: Any) -> dict[str, Any] | None:
    from libs.table_schema_mapping import normalize_header

    headers = {normalize_header(key): value for key, value in row.items()}
    object_id = next(
        (str(headers[normalize_header(column)]).strip()
         for column in signature.get("objectIdColumns") or []
         if str(headers.get(normalize_header(column)) or "").strip()),
        "",
    )
    if not object_id:
        # 没有对象识别的行归属不到任何被审查对象，宁可不产生，也不并到别人名下。
        return None
    return {
        "projectId": run.get("projectId"),
        "objectType": signature.get("objectType"),
        "objectId": object_id,
        # frozen_domain_checks 的 scope 四栏之一；缺了它整域判成证据不足。
        "recordVersionId": version_id,
        **({"domain": signature["domain"]} if signature.get("domain") else {}),
        **({"applicable": True}
           if signature.get("domain") and signature.get("applicableWhen") == "table_present"
           else {}),
        **map_row(row, signature),
    }


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
            if not isinstance(table, dict):
                continue
            schema = table.get("businessSchema")
            signature = None
            if schema not in schemas:
                # OCR 沒認出來的表，用规则包里的签名再认一次。生产库里 1004 列真实
                # 表格数据就是躺在 businessSchema 为空的表里，而事实构建按名字取表，
                # 于是规则永远拿不到它们。这里按读取时机补认，既有文件不必重跑 OCR。
                signature = _signature_for(table, schemas)
                if signature is None:
                    continue
                schema = signature["businessSchema"]
            for index, row in enumerate(table.get("normalizedRows") or []):
                if not isinstance(row, dict):
                    continue
                ref = {"documentVersionId": version_id, **_table_location(table),
                       "tableId": table.get("tableId") or table.get("id"), "rowIndex": index}
                ref["id"] = f"R{node_id}-REF-" + digest(ref)[:24]
                ref["evidenceRefId"] = ref["id"]
                ref["confidence"] = row.get("confidence", table.get("structureConfidence"))
                # Client/OCR supplied evidenceRefs cannot redirect a record to another document.
                # 签名认出来的表要按签名对映；原样塞进去的话，判据读的是
                # actualPath，而表头是中文列名，一个也对不上。
                payload = _mapped_payload(row, signature, run, version_id) if signature else deepcopy(row)
                if payload is None:
                    continue
                record = {**payload, "documentVersionId": version_id, "evidence": ref, "evidenceRefs": [ref]}
                groups[schemas[schema]].append(record)
    return groups
