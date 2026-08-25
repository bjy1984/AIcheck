from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from libs.contracts.responses import server_time
from libs.integrations.errors import IntegrationServiceError
from libs.review_evidence import (
    evidence_coverage_report,
    grounding_input_for_evidence_shard,
)


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


def _replace_node_finding_aggregate(
    state: dict[str, Any], aggregate: dict[str, Any]
) -> None:
    rows = state.setdefault("node_finding_aggregates", [])
    rows[:] = [
        row
        for row in rows
        if str(row.get("reviewRunId") or "")
        != str(aggregate.get("reviewRunId") or "")
    ]
    rows.append(aggregate)


def generate_sharded_finding_drafts(
    state: dict[str, Any],
    review_run: dict[str, Any],
    context: dict[str, Any],
    *,
    mode: str,
    generate_once,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest, shards = review_run_evidence_package(state, review_run)
    if not manifest or not shards:
        return generate_once(review_run, context)

    shard_results: list[dict[str, Any]] = []
    metadata_rows: list[dict[str, Any]] = []
    deterministic = mode in {"deterministic", "disabled", "mock"}
    failed_shard_ids: list[str] = []
    if deterministic:
        for shard in shards:
            grounding_input = grounding_input_for_evidence_shard(shard)
            shard.update(
                {
                    "status": "completed",
                    "processingMode": mode,
                    "processedInputHash": _stable_hash(grounding_input),
                    "modelAttemptIds": [],
                    "startedAt": shard.get("startedAt") or server_time(),
                    "completedAt": server_time(),
                    "updatedAt": server_time(),
                }
            )
        drafts, _metadata = generate_once(review_run, context)
        shard_results.append(
            {
                "evidenceShardId": None,
                "modelAttemptIds": [],
                "findingDrafts": drafts,
            }
        )
    else:
        for shard in shards:
            shard_id = str(shard.get("evidenceShardId") or shard.get("id") or "")
            if str(shard.get("status") or "") == "completed" and isinstance(
                shard.get("findingDrafts"), list
            ):
                shard_results.append(
                    {
                        "evidenceShardId": shard_id,
                        "modelAttemptIds": deepcopy(shard.get("modelAttemptIds") or []),
                        "findingDrafts": deepcopy(shard.get("findingDrafts") or []),
                    }
                )
                continue
            shard_context = deepcopy(context)
            shard_context.pop("promptShape", None)
            grounding_input = grounding_input_for_evidence_shard(shard)
            grounding_input["reviewMode"] = review_run.get("reviewMode")
            grounding_input["advisoryOnly"] = bool(review_run.get("advisoryOnly"))
            shard_context["groundingInput"] = grounding_input
            shard_context["evidenceShardId"] = shard_id
            for key in ("fields", "tables", "seals", "fragments", "evidenceLinks"):
                shard_context[key] = grounding_input.get(key) or []
            prior_attempt_ids = set(review_run.get("modelCallAttemptIds") or [])
            shard.update(
                {
                    "status": "running",
                    "processingMode": mode,
                    "processedInputHash": _stable_hash(grounding_input),
                    "startedAt": shard.get("startedAt") or server_time(),
                    "updatedAt": server_time(),
                }
            )
            try:
                drafts, metadata = generate_once(review_run, shard_context)
            except Exception as exc:
                attempt_ids = [
                    str(row.get("id") or "")
                    for row in state.get("model_call_attempts") or []
                    if isinstance(row, dict)
                    and str(row.get("reviewRunId") or "")
                    == str(review_run.get("reviewRunId") or "")
                    and str(row.get("evidenceShardId") or "") == shard_id
                ]
                for attempt_id in attempt_ids:
                    if attempt_id and attempt_id not in review_run.setdefault(
                        "modelCallAttemptIds", []
                    ):
                        review_run["modelCallAttemptIds"].append(attempt_id)
                failure_reason = (
                    str(exc.reason)
                    if isinstance(exc, IntegrationServiceError) and exc.reason
                    else exc.__cause__.__class__.__name__
                    if isinstance(exc, IntegrationServiceError)
                    and exc.__cause__ is not None
                    else exc.__class__.__name__
                )
                shard.update(
                    {
                        "status": "failed",
                        "failureReason": failure_reason,
                        "modelAttemptIds": attempt_ids,
                        "failedAt": server_time(),
                        "updatedAt": server_time(),
                    }
                )
                failed_shard_ids.append(shard_id)
                continue
            attempt_ids = [
                str(item)
                for item in review_run.get("modelCallAttemptIds") or []
                if str(item) not in prior_attempt_ids
            ]
            shard.update(
                {
                    "status": "completed",
                    "modelAttemptIds": attempt_ids,
                    "findingDrafts": deepcopy(drafts),
                    "completedAt": server_time(),
                    "updatedAt": server_time(),
                }
            )
            shard_results.append(
                {
                    "evidenceShardId": shard_id,
                    "modelAttemptIds": attempt_ids,
                    "findingDrafts": drafts,
                }
            )
            metadata_rows.append(metadata)

    aggregate = aggregate_shard_findings(review_run, shard_results)
    if deterministic:
        aggregate["sourceEvidenceShardIds"] = sorted(
            str(shard.get("evidenceShardId") or shard.get("id") or "")
            for shard in shards
        )
        for finding in aggregate["findingDrafts"]:
            finding["sourceEvidenceShardIds"] = deepcopy(
                aggregate["sourceEvidenceShardIds"]
            )
    coverage = evidence_coverage_report(manifest, shards)
    review_run["evidenceCoverage"] = coverage
    review_run["nodeFindingAggregate"] = aggregate
    _replace_node_finding_aggregate(state, aggregate)
    combined_metadata = {
        "llmExecution": mode,
        "llmCalled": not deterministic,
        "processedShardCount": coverage["completedShardCount"],
        "expectedShardCount": coverage["expectedShardCount"],
        "coveragePassed": coverage["coveragePassed"],
        "shardCalls": metadata_rows,
        "sourceModelAttemptIds": aggregate["sourceModelAttemptIds"],
    }
    review_run["llmMetadata"] = deepcopy(combined_metadata)
    if not deterministic and failed_shard_ids:
        raise EvidenceShardProcessingIncomplete(failed_shard_ids)
    return aggregate["findingDrafts"], combined_metadata


def mark_review_run_incomplete(
    review_run: dict[str, Any],
    ai_run: dict[str, Any] | None,
    error: EvidenceShardProcessingIncomplete,
    *,
    bump_revision,
    append_event,
) -> dict[str, Any]:
    review_run.update(
        {
            "status": "review_incomplete",
            "currentStep": "review_incomplete",
            "retryableFailure": True,
            "errorCode": "EVIDENCE_SHARD_PROCESSING_INCOMPLETE",
            "errorMessage": str(error),
            "failedEvidenceShardIds": list(error.failed_shard_ids),
            "finishedAt": server_time(),
        }
    )
    bump_revision(review_run)
    append_event(
        str(review_run.get("reviewRunId") or ""),
        event_type="review_run.incomplete",
        title="证据分片处理未完成",
        status="review_incomplete",
        details={
            "errorCode": "EVIDENCE_SHARD_PROCESSING_INCOMPLETE",
            "failedEvidenceShardIds": error.failed_shard_ids,
            "retryable": True,
        },
    )
    if ai_run:
        ai_run.update(
            {
                "status": "审查未完成",
                "errorCode": "EVIDENCE_SHARD_PROCESSING_INCOMPLETE",
                "errorMessage": "部分证据分片处理失败，可仅重试未完成分片。",
            }
        )
    return {
        "reviewRunId": review_run.get("reviewRunId"),
        "status": "review_incomplete",
        "errorCode": "EVIDENCE_SHARD_PROCESSING_INCOMPLETE",
        "failedEvidenceShardIds": error.failed_shard_ids,
        "retryable": True,
    }
