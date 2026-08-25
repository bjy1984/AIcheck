from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from libs.contracts.responses import server_time


class EvidenceShardProcessingIncomplete(RuntimeError):
    def __init__(self, failed_shard_ids: list[str]) -> None:
        self.failed_shard_ids = sorted({str(item) for item in failed_shard_ids if item})
        super().__init__("evidence shard processing incomplete")


def _stable_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def review_run_evidence_package(
    state: dict[str, Any], review_run: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    manifest_id = str(review_run.get("evidenceManifestId") or "")
    manifest = next(
        (
            row
            for row in state.get("evidence_manifests") or []
            if isinstance(row, dict)
            and str(row.get("evidenceManifestId") or row.get("id") or "")
            == manifest_id
        ),
        None,
    )
    wanted_ids = {
        str(item) for item in review_run.get("evidenceShardIds") or [] if item
    }
    shards = [
        row
        for row in state.get("evidence_shards") or []
        if isinstance(row, dict)
        and str(row.get("evidenceShardId") or row.get("id") or "") in wanted_ids
    ]
    shards.sort(
        key=lambda row: (
            int(row.get("shardIndex") or 0),
            str(row.get("evidenceShardId") or row.get("id") or ""),
        )
    )
    return manifest, shards


def _finding_key(finding: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        " ".join(str(finding.get(key) or "").split()).casefold()
        for key in (
            "findingType",
            "title",
            "description",
            "severity",
            "suggestedAction",
        )
    )


def _union_records(
    first: list[dict[str, Any]], second: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in [*first, *second]:
        if not isinstance(row, dict):
            continue
        key = _stable_hash(row)
        if key in seen:
            continue
        seen.add(key)
        result.append(deepcopy(row))
    return result


def aggregate_shard_findings(
    review_run: dict[str, Any], shard_results: list[dict[str, Any]]
) -> dict[str, Any]:
    findings_by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    source_shard_ids: list[str] = []
    source_attempt_ids: list[str] = []
    for result in shard_results:
        shard_id = str(result.get("evidenceShardId") or "")
        attempt_ids = [str(item) for item in result.get("modelAttemptIds") or [] if item]
        if shard_id and shard_id not in source_shard_ids:
            source_shard_ids.append(shard_id)
        for attempt_id in attempt_ids:
            if attempt_id not in source_attempt_ids:
                source_attempt_ids.append(attempt_id)
        for source_finding in result.get("findingDrafts") or []:
            if not isinstance(source_finding, dict):
                continue
            finding = deepcopy(source_finding)
            finding.setdefault("sourceEvidenceShardIds", [])
            finding.setdefault("sourceModelAttemptIds", [])
            if shard_id and shard_id not in finding["sourceEvidenceShardIds"]:
                finding["sourceEvidenceShardIds"].append(shard_id)
            for attempt_id in attempt_ids:
                if attempt_id not in finding["sourceModelAttemptIds"]:
                    finding["sourceModelAttemptIds"].append(attempt_id)
            key = _finding_key(finding)
            existing = findings_by_key.get(key)
            if not existing:
                findings_by_key[key] = finding
                continue
            for refs_key in ("evidenceRefs", "ruleRefs", "kbRefs"):
                existing[refs_key] = _union_records(
                    existing.get(refs_key) or [], finding.get(refs_key) or []
                )
            for lineage_key in (
                "sourceEvidenceShardIds",
                "sourceModelAttemptIds",
            ):
                existing[lineage_key] = list(
                    dict.fromkeys(
                        [
                            *(existing.get(lineage_key) or []),
                            *(finding.get(lineage_key) or []),
                        ]
                    )
                )

    findings = list(findings_by_key.values())
    conflict_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for finding in findings:
        conflict_key = (
            " ".join(str(finding.get("findingType") or "").split()).casefold(),
            " ".join(str(finding.get("title") or "").split()).casefold(),
        )
        conflict_groups.setdefault(conflict_key, []).append(finding)
    conflicts: list[dict[str, Any]] = []
    for grouped in conflict_groups.values():
        if len(grouped) < 2:
            continue
        conflicts.append(
            {
                "findingType": grouped[0].get("findingType"),
                "title": grouped[0].get("title"),
                "findingIds": [
                    str(finding.get("id") or "") for finding in grouped
                ],
                "sourceEvidenceShardIds": sorted(
                    {
                        str(shard_id)
                        for finding in grouped
                        for shard_id in finding.get("sourceEvidenceShardIds") or []
                        if shard_id
                    }
                ),
                "requiresHumanConfirmation": True,
            }
        )
    core = {
        "schemaVersion": "NodeFindingAggregate@1.0.0",
        "reviewRunId": review_run.get("reviewRunId"),
        "projectReviewRunId": review_run.get("projectReviewRunId"),
        "projectId": review_run.get("projectId"),
        "nodeId": review_run.get("nodeId"),
        "evidenceSnapshotId": review_run.get("evidenceSnapshotId"),
        "evidenceManifestId": review_run.get("evidenceManifestId"),
        "sourceEvidenceShardIds": sorted(source_shard_ids),
        "sourceModelAttemptIds": sorted(source_attempt_ids),
        "findingDrafts": findings,
        "conflicts": conflicts,
        "aggregationVersion": "exact-semantic-dedupe@1.0.0",
    }
    aggregate_hash = _stable_hash(core)
    return {
        "id": f"NFAGG-{aggregate_hash.removeprefix('sha256:')[:16].upper()}",
        **core,
        "aggregateHash": aggregate_hash,
        "createdAt": server_time(),
    }
