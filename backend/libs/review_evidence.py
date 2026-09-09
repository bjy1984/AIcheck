from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from typing import Any

from libs.contracts.responses import server_time
from libs.model_usage import estimate_text_tokens, is_cjk_char
from libs.review_page_scope import located_record_in_range, normalize_page_ranges


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _records(state: dict[str, Any], primary: str, fallback: str | None = None) -> list[dict[str, Any]]:
    rows = state.get(primary)
    if not isinstance(rows, list) and fallback:
        rows = state.get(fallback)
    return [row for row in rows or [] if isinstance(row, dict)]


def _latest_parse_result(
    state: dict[str, Any], document_version_id: str
) -> dict[str, Any] | None:
    rows = [
        row
        for row in _records(state, "ocr_parse_results")
        if str(row.get("documentVersionId") or "") == str(document_version_id)
    ]
    if not rows:
        return None
    rows.sort(
        key=lambda row: str(
            row.get("finishedAt")
            or row.get("updatedAt")
            or row.get("createdAt")
            or row.get("parseResultId")
            or row.get("id")
            or ""
        ),
        reverse=True,
    )
    return rows[0]


def active_node_document_versions(
    state: dict[str, Any], project_id: str, node_id: int
) -> list[dict[str, Any]]:
    documents = {
        str(row.get("id")): row
        for row in _records(state, "documents")
        if row.get("id") and str(row.get("projectId") or "") == str(project_id)
    }
    links = [
        row
        for row in _records(state, "node_evidence_links")
        if str(row.get("projectId") or "") == str(project_id)
        and int(row.get("nodeId") or 0) == int(node_id)
        and str(row.get("manualStatus") or "").strip().lower() != "rejected"
        and row.get("documentVersionId")
    ]

    active: dict[str, dict[str, Any]] = {}
    for link in links:
        document_id = str(link.get("documentId") or "")
        document = documents.get(document_id)
        if not document:
            continue
        linked_version_id = str(link.get("documentVersionId") or "")
        current_version_id = str(document.get("currentVersionId") or linked_version_id)
        if linked_version_id != current_version_id:
            continue
        entry = active.setdefault(
            current_version_id,
            {
                "documentId": document_id,
                "documentVersionId": current_version_id,
                "mountLinkIds": [],
                "mountRevision": 0,
            },
        )
        link_id = str(link.get("id") or "")
        if link_id and link_id not in entry["mountLinkIds"]:
            entry["mountLinkIds"].append(link_id)
        entry["mountRevision"] = max(
            int(entry.get("mountRevision") or 0),
            int(link.get("revision") or 0),
        )

    # 人工「选择环节 + 提交」只写 node_bindings，不产证据链接；原来这里只看链接，
    # 项目里一旦有自动打靶链接，人工挂载的资料就从审查视野里消失（2026-09-03 审计：
    # 测试项目3 节点 2 已提交 3 份、AI 只看到 2 份）。已提交挂载与链接取并集。
    from libs.manual_binding_links import submitted_binding_document_versions

    for entry in submitted_binding_document_versions(state, project_id, node_id):
        existing = active.get(entry["documentVersionId"])
        if existing is None:
            active[entry["documentVersionId"]] = entry
            continue
        for mount_id in entry["mountLinkIds"]:
            if mount_id not in existing["mountLinkIds"]:
                existing["mountLinkIds"].append(mount_id)
        existing["mountRevision"] = max(int(existing.get("mountRevision") or 0), int(entry["mountRevision"]))
    for entry in active.values():
        entry["mountLinkIds"].sort()
    return sorted(active.values(), key=lambda row: row["documentVersionId"])


def _enrich_document_versions(
    state: dict[str, Any], active_versions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    versions = {
        str(row.get("id")): row
        for row in _records(state, "document_versions", "versions")
        if row.get("id")
    }
    enriched: list[dict[str, Any]] = []
    for active in active_versions:
        version_id = str(active["documentVersionId"])
        version = versions.get(version_id) or {}
        parse_result = _latest_parse_result(state, version_id)
        ocr_hash = None
        parse_result_id = None
        if parse_result:
            parse_result_id = parse_result.get("parseResultId") or parse_result.get("id")
            ocr_hash = (
                parse_result.get("artifactHash")
                or parse_result.get("contentHash")
                or parse_result.get("outputHash")
                or _stable_hash(parse_result)
            )
        enriched.append(
            {
                **active,
                "documentContentHash": (
                    version.get("contentHash")
                    or version.get("sha256")
                    or version.get("checksum")
                    or _stable_hash(version)
                ),
                "ocrParseResultId": parse_result_id,
                "ocrContentHash": ocr_hash,
            }
        )
    return enriched


def build_evidence_snapshot(
    state: dict[str, Any],
    project_id: str,
    node_id: int,
    *,
    rule_version: str,
    clause_package_version: str,
    prompt_version: str,
    strategy_version: str,
    document_version_ids: list[str] | None = None,
    document_page_ranges: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    active = active_node_document_versions(state, project_id, node_id)
    if document_version_ids is not None:
        documents = {str(row.get("id")): row for row in _records(state, "documents")
                     if str(row.get("projectId") or "") == str(project_id)}
        owners = {str(row.get("id")): str(row.get("documentId"))
                  for row in _records(state, "document_versions", "versions") if str(row.get("documentId")) in documents}
        owners.update({str(row.get("currentVersionId")): identity for identity, row in documents.items() if row.get("currentVersionId")})
        if any(version not in owners for version in document_version_ids):
            raise ValueError("review_input_version_outside_project")
        active = [{"documentId": owners[version], "documentVersionId": version,
                   "mountLinkIds": [], "mountRevision": 0, "selectionMode": "run_only"}
                  for version in sorted(set(document_version_ids))]
    document_versions = _enrich_document_versions(state, active)
    hash_payload = {
        "projectId": str(project_id),
        "nodeId": int(node_id),
        "documentVersions": document_versions,
        "ruleVersion": str(rule_version),
        "clausePackageVersion": str(clause_package_version),
        "promptVersion": str(prompt_version),
        "strategyVersion": str(strategy_version),
    }
    if document_page_ranges is not None:
        hash_payload["documentPageRanges"] = normalize_page_ranges(
            document_page_ranges, [row["documentVersionId"] for row in document_versions])
    snapshot_hash = _stable_hash(hash_payload)
    return {
        "evidenceSnapshotId": f"ESNAP-{snapshot_hash.removeprefix('sha256:')[:16].upper()}",
        **hash_payload,
        "documentVersionCount": len(document_versions),
        "snapshotHash": snapshot_hash,
        "createdAt": server_time(),
    }


def _manifest_artifact(
    artifact_type: str,
    document_version_id: str,
    source_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    core = {
        "artifactType": artifact_type,
        "documentVersionId": document_version_id,
        "sourceId": source_id,
        "payload": deepcopy(payload),
    }
    content_hash = _stable_hash(core)
    return {
        "artifactId": f"EART-{content_hash.removeprefix('sha256:')[:16].upper()}",
        **core,
        "contentHash": content_hash,
    }


def _artifacts_for_document(
    state: dict[str, Any], document_version_id: str, bounds: dict[str, int] | None = None
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    fields = [
        row
        for row in _records(state, "extracted_fields")
        if str(row.get("documentVersionId") or "") == document_version_id
        and (bounds is None or located_record_in_range(row, bounds))
    ]
    for index, field in enumerate(fields, start=1):
        source_id = str(field.get("id") or f"field:{index}")
        artifacts.append(
            _manifest_artifact("field", document_version_id, source_id, field)
        )

    parse_result = _latest_parse_result(state, document_version_id) or {}
    parse_result_id = str(parse_result.get("parseResultId") or parse_result.get("id") or "ocr")
    parse_groups = (
        ("table", "tables"),
        ("seal", "seals"),
        ("fragment", "fragments"),
    )
    for artifact_type, collection_name in parse_groups:
        rows = [
            compact_artifact_payload(artifact_type, row)
            for row in parse_result.get(collection_name) or []
            if isinstance(row, dict) and (bounds is None or located_record_in_range(row, bounds))
        ]
        if artifact_type == "fragment":
            rows = _collapse_empty_fragments(rows, parse_result_id)
        for index, row in enumerate(rows, start=1):
            source_id = str(
                row.get("id")
                or row.get(f"{artifact_type}Id")
                or f"{parse_result_id}:{artifact_type}:{index}"
            )
            artifacts.append(
                _manifest_artifact(
                    artifact_type,
                    document_version_id,
                    source_id,
                    row,
                )
            )

    evidence_links = [
        row
        for row in _records(state, "evidence_links")
        if str(row.get("documentVersionId") or "") == document_version_id
        and (bounds is None or located_record_in_range(row, bounds))
    ]
    for index, link in enumerate(evidence_links, start=1):
        source_id = str(link.get("id") or f"evidence-link:{index}")
        artifacts.append(
            _manifest_artifact(
                "evidenceLink",
                document_version_id,
                source_id,
                link,
            )
        )
    return artifacts


def _artifact_counts(artifacts: list[dict[str, Any]]) -> dict[str, int]:
    type_to_key = {
        "field": "fields",
        "table": "tables",
        "seal": "seals",
        "fragment": "fragments",
        "evidenceLink": "evidenceLinks",
    }
    counts = {key: 0 for key in type_to_key.values()}
    for artifact in artifacts:
        key = type_to_key[str(artifact["artifactType"])]
        counts[key] += 1
    counts["total"] = len(artifacts)
    return counts


def build_evidence_manifest(
    state: dict[str, Any], snapshot: dict[str, Any]
) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    ranges = normalize_page_ranges(snapshot.get("documentPageRanges", {}),
                                   [row["documentVersionId"] for row in snapshot.get("documentVersions") or []])
    for snapshot_document in snapshot.get("documentVersions") or []:
        if not isinstance(snapshot_document, dict):
            continue
        version_id = str(snapshot_document.get("documentVersionId") or "")
        if not version_id:
            continue
        document_artifacts = _artifacts_for_document(state, version_id, ranges.get(version_id))
        artifacts.extend(document_artifacts)
        documents.append(
            {
                **deepcopy(snapshot_document),
                "artifactIds": [row["artifactId"] for row in document_artifacts],
                "artifactCount": len(document_artifacts),
            }
        )

    core = {
        "schemaVersion": "EvidenceManifest@1.0.0",
        "evidenceSnapshotId": snapshot.get("evidenceSnapshotId"),
        "evidenceSnapshotHash": snapshot.get("snapshotHash"),
        "projectId": snapshot.get("projectId"),
        "nodeId": snapshot.get("nodeId"),
        "documents": documents,
        "artifacts": artifacts,
        "counts": _artifact_counts(artifacts),
        **({"documentPageRanges": deepcopy(ranges)} if "documentPageRanges" in snapshot else {}),
    }
    manifest_hash = _stable_hash(core)
    return {
        "evidenceManifestId": f"EMAN-{manifest_hash.removeprefix('sha256:')[:16].upper()}",
        **core,
        "manifestHash": manifest_hash,
        "createdAt": server_time(),
    }


def _estimated_tokens(value: Any) -> int:
    """分片估算。中文感知（P8 H2）：此前按 len/4 估，节点 2 目标 12,000 的分片计费 5.5 万 token。"""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return estimate_text_tokens(raw)


def _split_text_by_tokens(text: str, max_tokens: int) -> list[tuple[int, int]]:
    """按估算 token 切分正文，返回 [start, end) 字符区间；区间首尾相接可原样拼回。"""
    budget = max(1, int(max_tokens))
    ranges: list[tuple[int, int]] = []
    start = 0
    spent = 0.0
    for index, char in enumerate(text):
        cost = 1.0 if is_cjk_char(char) else 0.25
        if spent + cost > budget and index > start:
            ranges.append((start, index))
            start = index
            spent = 0.0
        spent += cost
    if start < len(text) or not ranges:
        ranges.append((start, len(text)))
    return ranges


# 分片层的无损压缩（P8 H2）。OCR 解析结果把同一张表原样带了三份——table.html、
# table.rows/cells、以及同页一条 blockType=table 的 fragment 还带 tableHtml；
# 单元格里 bbox/confidence 为 null 的键也一起送。提示词层已经去掉 rows/cellsSummary
# 别名，但分片按压缩前的体量切，片数照旧。这里只去重复与空值，不动任何有内容的键。
_TABLE_ALIAS_PAIRS = (("rows", "normalizedRows"), ("cells", "cellsSummary"))
_EMPTY_VALUES = (None, "", [], {})


def _compact_cells(cells: Any) -> Any:
    if not isinstance(cells, list):
        return cells
    return [
        {key: value for key, value in cell.items() if value not in _EMPTY_VALUES}
        if isinstance(cell, dict)
        else cell
        for cell in cells
    ]


def compact_artifact_payload(artifact_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """去掉 OCR 载荷里的重复副本与空值。严格无损：删掉的都是另一键的同一内容或 null。"""
    if not isinstance(payload, dict):
        return payload
    item = dict(payload)
    if artifact_type == "table":
        for keep, alias in _TABLE_ALIAS_PAIRS:
            if alias in item and keep in item and item[alias] == item[keep]:
                item.pop(alias)
            elif alias in item and keep not in item:
                item[keep] = item.pop(alias)
        if item.get("rows") or item.get("cells"):
            item.pop("html", None)
        if "cells" in item:
            item["cells"] = _compact_cells(item["cells"])
        if "rows" in item and isinstance(item["rows"], list):
            item["rows"] = [
                {key: value for key, value in row.items() if value not in _EMPTY_VALUES}
                if isinstance(row, dict)
                else row
                for row in item["rows"]
            ]
    elif artifact_type == "fragment":
        if str(item.get("text") or "").strip():
            item.pop("tableHtml", None)
        item = {key: value for key, value in item.items() if value is not None}
    return item


def _collapse_empty_fragments(rows: list[dict[str, Any]], parse_result_id: str) -> list[dict[str, Any]]:
    """同一页里没有文本的碎片合成一条"该页无可用 OCR 文本"。

    空碎片只有 bbox 与 null 字段，对审查没有信息量，却按条计入分片。
    审计计划原文写"置信度全 0 的整页"，但 MinerU 给所有碎片都标 confidence 0.0，
    按置信度判会把整份资料判空——这里只看有没有文本。
    """
    kept: list[dict[str, Any]] = []
    empty_by_page: dict[int, int] = {}
    for row in rows:
        if str(row.get("text") or "").strip():
            kept.append(row)
            continue
        try:
            page_no = int(row.get("pageNo") or row.get("page") or 0)
        except (TypeError, ValueError):
            page_no = 0
        empty_by_page[page_no] = empty_by_page.get(page_no, 0) + 1
    for page_no, count in sorted(empty_by_page.items()):
        kept.append(
            {
                "fragmentId": f"{parse_result_id}:page-{page_no}:no-text",
                "pageNo": page_no,
                "text": "",
                "ocrTextUnavailable": True,
                "collapsedFragmentCount": count,
                "note": f"第 {page_no} 页有 {count} 个 OCR 碎片没有文本，已合并为一条。",
            }
        )
    return kept


def _chunk_sequence(
    field_name: str,
    rows: list[Any],
    *,
    max_estimated_tokens: int,
) -> list[dict[str, Any]]:
    chunks: list[list[Any]] = []
    current: list[Any] = []
    for row in rows:
        candidate = [*current, deepcopy(row)]
        if current and _estimated_tokens({field_name: candidate}) > max_estimated_tokens:
            chunks.append(current)
            current = [deepcopy(row)]
        else:
            current = candidate
    if current:
        chunks.append(current)
    return [{field_name: chunk} for chunk in chunks]


def _split_text_payload(
    payload: dict[str, Any],
    *,
    max_estimated_tokens: int,
) -> list[dict[str, Any]]:
    string_fields = [
        key
        for key, value in payload.items()
        if isinstance(value, str) and value
    ]
    if not string_fields:
        return [{"payloadSlice": deepcopy(payload), "segmentKind": "complete"}]
    text_key = max(string_fields, key=lambda key: len(str(payload[key])))
    text = str(payload[text_key])
    metadata = {key: deepcopy(value) for key, value in payload.items() if key != text_key}
    metadata_tokens = _estimated_tokens(metadata)
    segments: list[dict[str, Any]] = []
    for start, end in _split_text_by_tokens(text, max_estimated_tokens - metadata_tokens - 20):
        segments.append(
            {
                "payloadSlice": {**deepcopy(metadata), text_key: text[start:end]},
                "segmentKind": f"text:{text_key}",
                "characterRange": {"field": text_key, "start": start, "end": end},
            }
        )
    return segments


def _split_table_payload(
    payload: dict[str, Any],
    *,
    max_estimated_tokens: int,
) -> list[dict[str, Any]]:
    rows = [deepcopy(row) for row in payload.get("rows") or []]
    cells = [deepcopy(cell) for cell in payload.get("cells") or []]
    metadata = {
        key: deepcopy(value)
        for key, value in payload.items()
        if key not in {"rows", "cells"}
    }
    segments: list[dict[str, Any]] = []
    if metadata:
        if _estimated_tokens(metadata) <= max_estimated_tokens:
            segments.append({"payloadSlice": metadata, "segmentKind": "table:metadata"})
        else:
            segments.extend(
                {
                    **segment,
                    "segmentKind": f"table:{segment['segmentKind']}",
                }
                for segment in _split_text_payload(
                    metadata,
                    max_estimated_tokens=max_estimated_tokens,
                )
            )
    segments.extend(
        {
            "payloadSlice": chunk,
            "segmentKind": "table:rows",
        }
        for chunk in _chunk_sequence(
            "rows",
            rows,
            max_estimated_tokens=max_estimated_tokens,
        )
    )
    segments.extend(
        {
            "payloadSlice": chunk,
            "segmentKind": "table:cells",
        }
        for chunk in _chunk_sequence(
            "cells",
            cells,
            max_estimated_tokens=max_estimated_tokens,
        )
    )
    return segments or [{"payloadSlice": deepcopy(payload), "segmentKind": "complete"}]


def _artifact_segments(
    artifact: dict[str, Any],
    *,
    max_estimated_tokens: int,
) -> list[dict[str, Any]]:
    payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
    if _estimated_tokens(payload) <= max_estimated_tokens:
        raw_segments = [{"payloadSlice": deepcopy(payload), "segmentKind": "complete"}]
    elif artifact.get("artifactType") == "table":
        raw_segments = _split_table_payload(
            payload,
            max_estimated_tokens=max_estimated_tokens,
        )
    else:
        raw_segments = _split_text_payload(
            payload,
            max_estimated_tokens=max_estimated_tokens,
        )

    segment_count = len(raw_segments)
    segments: list[dict[str, Any]] = []
    for index, raw_segment in enumerate(raw_segments):
        core = {
            "artifactId": artifact.get("artifactId"),
            "artifactType": artifact.get("artifactType"),
            "documentVersionId": artifact.get("documentVersionId"),
            "sourceId": artifact.get("sourceId"),
            "segmentIndex": index,
            "segmentCount": segment_count,
            **raw_segment,
        }
        segment_hash = _stable_hash(core)
        segments.append(
            {
                "artifactSegmentId": f"ESEG-{segment_hash.removeprefix('sha256:')[:16].upper()}",
                **core,
                "segmentHash": segment_hash,
                "estimatedTokens": _estimated_tokens(core),
            }
        )
    return segments


def build_evidence_shards(
    manifest: dict[str, Any],
    *,
    max_shard_estimated_tokens: int,
) -> list[dict[str, Any]]:
    if int(max_shard_estimated_tokens) <= 0:
        raise ValueError("max_shard_estimated_tokens must be positive")
    segments = [
        segment
        for artifact in manifest.get("artifacts") or []
        if isinstance(artifact, dict)
        for segment in _artifact_segments(
            artifact,
            max_estimated_tokens=int(max_shard_estimated_tokens),
        )
    ]
    segment_groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_tokens = 0
    for segment in segments:
        segment_tokens = int(segment.get("estimatedTokens") or 0)
        if current and current_tokens + segment_tokens > int(max_shard_estimated_tokens):
            segment_groups.append(current)
            current = []
            current_tokens = 0
        current.append(segment)
        current_tokens += segment_tokens
    if current:
        segment_groups.append(current)

    shards: list[dict[str, Any]] = []
    for index, group in enumerate(segment_groups, start=1):
        artifact_ids = list(dict.fromkeys(str(row.get("artifactId")) for row in group))
        core = {
            "evidenceManifestId": manifest.get("evidenceManifestId"),
            "evidenceSnapshotId": manifest.get("evidenceSnapshotId"),
            "projectId": manifest.get("projectId"),
            "nodeId": manifest.get("nodeId"),
            "shardIndex": index,
            "artifactIds": artifact_ids,
            "artifactSegments": group,
        }
        shard_hash = _stable_hash(core)
        shards.append(
            {
                "evidenceShardId": f"ESHARD-{shard_hash.removeprefix('sha256:')[:16].upper()}",
                **core,
                "estimatedTokens": sum(int(row.get("estimatedTokens") or 0) for row in group),
                "status": "pending",
                "shardHash": shard_hash,
                "createdAt": server_time(),
            }
        )
    return shards


_SHARD_ARTIFACT_COLLECTIONS = {
    "field": "fields",
    "table": "tables",
    "seal": "seals",
    "fragment": "fragments",
    "evidenceLink": "evidenceLinks",
}


def _text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if isinstance(value, dict):
        values: list[str] = []
        for nested in value.values():
            values.extend(_text_values(nested))
        return values
    if isinstance(value, list):
        values = []
        for nested in value:
            values.extend(_text_values(nested))
        return values
    return []


def _has_locatable_shard_evidence(item: dict[str, Any]) -> bool:
    try:
        page_no = int(item.get("pageNo") or item.get("page") or 0)
    except (TypeError, ValueError):
        page_no = 0
    bbox = item.get("bbox")
    return page_no > 0 and isinstance(bbox, list) and len(bbox) == 4


def grounding_input_for_evidence_shard(shard: dict[str, Any]) -> dict[str, Any]:
    """Project one immutable shard into the normal grounded-review contract.

    The projection consumes only persisted ``payloadSlice`` values. It never
    rereads a whole OCR result, so a physical model call cannot silently regain
    sibling-shard content and exceed the partition boundary.
    """

    collections: dict[str, list[dict[str, Any]]] = {
        collection: [] for collection in _SHARD_ARTIFACT_COLLECTIONS.values()
    }
    document_version_ids: set[str] = set()
    segment_ids: list[str] = []
    evidence_texts: list[str] = []
    locatable_count = 0
    for segment in shard.get("artifactSegments") or []:
        if not isinstance(segment, dict):
            continue
        artifact_type = str(segment.get("artifactType") or "")
        collection = _SHARD_ARTIFACT_COLLECTIONS.get(artifact_type)
        if not collection:
            continue
        payload = (
            deepcopy(segment.get("payloadSlice"))
            if isinstance(segment.get("payloadSlice"), dict)
            else {}
        )
        document_version_id = str(segment.get("documentVersionId") or "")
        lineage = {
            "artifactId": segment.get("artifactId"),
            "artifactSegmentId": segment.get("artifactSegmentId"),
            "documentVersionId": document_version_id or payload.get("documentVersionId"),
            "sourceId": segment.get("sourceId"),
            "segmentIndex": int(segment.get("segmentIndex") or 0),
            "segmentCount": int(segment.get("segmentCount") or 1),
            "segmentKind": segment.get("segmentKind") or "complete",
        }
        projected = {**payload, **lineage}
        # Evidence-link IDs are part of the grounding contract. Preserve the
        # OCR record's real ID and only fall back to its stable source ID.
        if artifact_type == "evidenceLink" and not projected.get("id"):
            projected["id"] = segment.get("sourceId")
        collections[collection].append(projected)
        if document_version_id:
            document_version_ids.add(document_version_id)
        if segment.get("artifactSegmentId"):
            segment_ids.append(str(segment["artifactSegmentId"]))
        evidence_texts.extend(_text_values(payload))
        if _has_locatable_shard_evidence(projected):
            locatable_count += 1

    evidence_texts = list(dict.fromkeys(evidence_texts))
    evidence_count = sum(len(rows) for rows in collections.values())
    grounding_status = (
        "grounded"
        if evidence_texts and (locatable_count > 0 or bool(collections["evidenceLinks"]))
        else "insufficient_evidence"
    )
    summary = {
        "fieldCount": len(collections["fields"]),
        "tableCount": len(collections["tables"]),
        "sealCount": len(collections["seals"]),
        "fragmentCount": len(collections["fragments"]),
        "evidenceLinkCount": len(collections["evidenceLinks"]),
        "artifactSegmentCount": evidence_count,
        "groundingStatus": grounding_status,
    }
    blocking_issues = []
    if grounding_status != "grounded":
        blocking_issues.append(
            {
                "code": "SHARD_EVIDENCE_NOT_LOCATABLE",
                "message": "The evidence shard has no locatable OCR evidence.",
            }
        )
    return {
        "schemaVersion": "EvidenceGroundedReviewInput@1.0.0",
        "evidenceShardId": shard.get("evidenceShardId") or shard.get("id"),
        "evidenceSnapshotId": shard.get("evidenceSnapshotId"),
        "evidenceManifestId": shard.get("evidenceManifestId"),
        "projectId": shard.get("projectId"),
        "nodeId": shard.get("nodeId"),
        "documentVersionIds": sorted(document_version_ids),
        "artifactSegmentIds": segment_ids,
        "groundingStatus": grounding_status,
        "blockingIssues": blocking_issues,
        **collections,
        "quality": [],
        "evidenceTextCorpus": evidence_texts,
        "summary": summary,
        "reviewWarnings": [
            "当前证据分片缺少可定位的页码/bbox，模型输出必须降级为人工确认。"
        ]
        if blocking_issues
        else [],
    }


def _duplicate_values(values: list[tuple[str, int]]) -> list[str]:
    seen: set[tuple[str, int]] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value[0])
        seen.add(value)
    return sorted(duplicates)


def evidence_coverage_report(
    manifest: dict[str, Any], shards: list[dict[str, Any]]
) -> dict[str, Any]:
    expected_ids = [
        str(row.get("artifactId"))
        for row in manifest.get("artifacts") or []
        if isinstance(row, dict) and row.get("artifactId")
    ]
    segments = [
        segment
        for shard in shards
        if isinstance(shard, dict)
        for segment in shard.get("artifactSegments") or []
        if isinstance(segment, dict) and segment.get("artifactId")
    ]
    segment_keys = [
        (str(segment["artifactId"]), int(segment.get("segmentIndex") or 0))
        for segment in segments
    ]
    duplicate_ids = _duplicate_values(segment_keys)
    segments_by_artifact: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        segments_by_artifact.setdefault(str(segment["artifactId"]), []).append(segment)

    missing_ids = sorted(set(expected_ids) - set(segments_by_artifact))
    unexpected_ids = sorted(set(segments_by_artifact) - set(expected_ids))
    incomplete_ids: list[str] = []
    complete_ids: list[str] = []
    for artifact_id in expected_ids:
        artifact_segments = segments_by_artifact.get(artifact_id) or []
        if not artifact_segments:
            continue
        expected_segment_count = int(artifact_segments[0].get("segmentCount") or 0)
        actual_indices = sorted(int(row.get("segmentIndex") or 0) for row in artifact_segments)
        counts_agree = all(
            int(row.get("segmentCount") or 0) == expected_segment_count
            for row in artifact_segments
        )
        if (
            not counts_agree
            or actual_indices != list(range(expected_segment_count))
            or artifact_id in duplicate_ids
        ):
            incomplete_ids.append(artifact_id)
        else:
            complete_ids.append(artifact_id)

    structural_coverage_passed = not any(
        [missing_ids, unexpected_ids, incomplete_ids, duplicate_ids]
    ) and len(complete_ids) == len(expected_ids)
    completed_shard_count = sum(
        str(row.get("status")) == "completed" for row in shards
    )
    failed_shard_count = sum(str(row.get("status")) == "failed" for row in shards)
    processing_coverage_passed = bool(shards) and (
        completed_shard_count == len(shards) and failed_shard_count == 0
    )
    return {
        "expectedShardCount": len(shards),
        "completedShardCount": completed_shard_count,
        "failedShardCount": failed_shard_count,
        "expectedArtifactCount": len(expected_ids),
        "processedArtifactCount": len(complete_ids),
        "missingArtifactIds": missing_ids,
        "unexpectedArtifactIds": unexpected_ids,
        "incompleteArtifactIds": sorted(incomplete_ids),
        "duplicateArtifactIds": duplicate_ids,
        "structuralCoveragePassed": structural_coverage_passed,
        "processingCoveragePassed": processing_coverage_passed,
        "coveragePassed": structural_coverage_passed and processing_coverage_passed,
    }


def review_shard_target_tokens() -> int:
    raw = str(os.getenv("AICHECK_REVIEW_SHARD_TARGET_TOKENS", "12000")).strip()
    try:
        value = int(raw)
    except ValueError:
        return 12000
    return value if value > 0 else 12000


def build_review_evidence_package(
    state: dict[str, Any],
    project_id: str,
    node_id: int,
    *,
    rule_version: str,
    clause_package_version: str,
    prompt_version: str,
    strategy_version: str,
    max_shard_estimated_tokens: int | None = None,
    document_version_ids: list[str] | None = None,
    document_page_ranges: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    snapshot = build_evidence_snapshot(
        state,
        project_id,
        node_id,
        rule_version=rule_version,
        clause_package_version=clause_package_version,
        prompt_version=prompt_version,
        strategy_version=strategy_version,
        document_version_ids=document_version_ids,
        **({"document_page_ranges": document_page_ranges} if document_page_ranges is not None else {}),
    )
    manifest = build_evidence_manifest(state, snapshot)
    shards = build_evidence_shards(
        manifest,
        max_shard_estimated_tokens=(
            int(max_shard_estimated_tokens)
            if max_shard_estimated_tokens is not None
            else review_shard_target_tokens()
        ),
    )
    coverage = evidence_coverage_report(manifest, shards)
    return {
        "snapshot": snapshot,
        "manifest": manifest,
        "shards": shards,
        "coverage": coverage,
    }


def _upsert_state_record(
    state: dict[str, Any], collection: str, record: dict[str, Any]
) -> None:
    rows = state.setdefault(collection, [])
    record_id = str(record.get("id") or record.get("evidenceSnapshotId") or record.get("evidenceManifestId") or record.get("evidenceShardId") or "")
    for index, existing in enumerate(rows):
        existing_id = str(
            existing.get("id")
            or existing.get("evidenceSnapshotId")
            or existing.get("evidenceManifestId")
            or existing.get("evidenceShardId")
            or ""
        )
        if record_id and existing_id == record_id:
            rows[index] = record
            return
    rows.append(record)


def persist_review_evidence_package(
    state: dict[str, Any], package: dict[str, Any], *, ai_run_id: str
) -> None:
    snapshot = {**deepcopy(package["snapshot"]), "id": package["snapshot"]["evidenceSnapshotId"], "aiRunId": ai_run_id}
    manifest = {**deepcopy(package["manifest"]), "id": package["manifest"]["evidenceManifestId"], "aiRunId": ai_run_id}
    _upsert_state_record(state, "evidence_snapshots", snapshot)
    _upsert_state_record(state, "evidence_manifests", manifest)
    for source_shard in package.get("shards") or []:
        shard = {
            **deepcopy(source_shard),
            "id": source_shard["evidenceShardId"],
            "aiRunId": ai_run_id,
        }
        _upsert_state_record(state, "evidence_shards", shard)


def attach_review_evidence_package_to_ai_run(
    state: dict[str, Any],
    ai_run: dict[str, Any],
    *,
    clause_package_snapshot: dict[str, Any] | None,
    orchestration_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze and attach the cumulative node evidence package to an AiRun."""

    package = build_review_evidence_package(
        state,
        str(ai_run.get("projectId") or ""),
        int(ai_run.get("nodeId") or 0),
        rule_version=str(ai_run.get("ruleVersion") or "ruleset-v1"),
        clause_package_version=str(
            (clause_package_snapshot or {}).get("snapshotHash") or "none"
        ),
        prompt_version=str(ai_run.get("promptVersion") or "review_prompt@1.0.0"),
        strategy_version="node-review-strategy-v1",
        document_version_ids=(list(ai_run.get("inputDocumentVersionIds") or [])
                              if "inputDocumentPageRanges" in ai_run or (ai_run.get("evidenceReadiness") or {}).get("inputSelection", {}).get("mode") == "explicit" else None),
        **({"document_page_ranges": ai_run["inputDocumentPageRanges"]}
           if "inputDocumentPageRanges" in ai_run else {}),
    )
    snapshot_versions = sorted(
        str(item.get("documentVersionId"))
        for item in package["snapshot"].get("documentVersions") or []
        if item.get("documentVersionId")
    )
    metadata = orchestration_metadata or {}
    ai_run.update(
        {
            "projectReviewRunId": metadata.get("projectReviewRunId"),
            "triggerType": metadata.get("triggerType") or "manual_node",
            "autoReviewPolicyRevision": metadata.get("autoReviewPolicyRevision"),
            "inputDocumentVersionIds": snapshot_versions
            or list(ai_run.get("inputDocumentVersionIds") or []),
            "evidenceSnapshotId": package["snapshot"]["evidenceSnapshotId"],
            "evidenceSnapshotHash": package["snapshot"]["snapshotHash"],
            "evidenceManifestId": package["manifest"]["evidenceManifestId"],
            "evidenceManifestHash": package["manifest"]["manifestHash"],
            "evidenceShardIds": [
                item["evidenceShardId"] for item in package["shards"]
            ],
            "evidenceCoverage": package["coverage"],
        }
    )
    persist_review_evidence_package(
        state, package, ai_run_id=str(ai_run.get("id") or "")
    )
    return package


def bind_evidence_package_to_review_run(
    state: dict[str, Any], *, ai_run_id: str, review_run_id: str
) -> None:
    for collection in ("evidence_snapshots", "evidence_manifests", "evidence_shards"):
        for record in state.get(collection) or []:
            if str(record.get("aiRunId") or "") == str(ai_run_id):
                record["reviewRunId"] = review_run_id


def review_run_evidence_lineage(ai_run: dict[str, Any]) -> dict[str, Any]:
    return {
        "projectReviewRunId": ai_run.get("projectReviewRunId"),
        "triggerType": ai_run.get("triggerType") or "manual_node",
        "autoReviewPolicyRevision": ai_run.get("autoReviewPolicyRevision"),
        "evidenceSnapshotId": ai_run.get("evidenceSnapshotId"),
        "evidenceSnapshotHash": ai_run.get("evidenceSnapshotHash"),
        "evidenceManifestId": ai_run.get("evidenceManifestId"),
        "evidenceManifestHash": ai_run.get("evidenceManifestHash"),
        "evidenceShardIds": deepcopy(ai_run.get("evidenceShardIds") or []),
        "evidenceCoverage": deepcopy(ai_run.get("evidenceCoverage") or {}),
    }
