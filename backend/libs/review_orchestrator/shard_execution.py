from __future__ import annotations

import hashlib
import json
import logging
import re
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


LOGGER = logging.getLogger(__name__)


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


def evidence_shard_scope(state: dict[str, Any], shard: dict[str, Any], shard_count: int) -> dict[str, Any]:
    """告诉模型它看到的是哪一片、含哪些资料。

    2026-11-02 server8 复盘：提示词从没说过证据是分片送的，GDLNG 节点 9 只装了设计说明照片的那一片
    断言「缺检测比例、缺试验压力」，而这些都写在别的片里的管道特性表上。
    """
    version_ids = list(
        dict.fromkeys(
            str(segment.get("documentVersionId") or "")
            for segment in shard.get("artifactSegments") or []
            if isinstance(segment, dict) and segment.get("documentVersionId")
        )
    )
    versions = {
        str(row.get("id") or row.get("documentVersionId") or ""): row
        for row in [*(state.get("versions") or []), *(state.get("document_versions") or [])]
        if isinstance(row, dict)
    }
    documents = {str(row.get("id") or ""): row for row in state.get("documents") or [] if isinstance(row, dict)}
    names = []
    for version_id in version_ids:
        document = documents.get(str((versions.get(version_id) or {}).get("documentId") or "")) or {}
        names.append({"documentVersionId": version_id, "fileName": str(document.get("fileName") or "")})
    return {"shardIndex": int(shard.get("shardIndex") or 0), "shardCount": int(shard_count), "documents": names}


DOWNGRADED_TITLE = "证据不足，需人工确认"
_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _finding_key(finding: dict[str, Any]) -> tuple[str, ...]:
    """合并键。

    守卫降级后的条目标题、正文都是同一句模板，只有 unsupportedClaims 不同；原来把 severity
    也放进键里，9 个分片各降一条就并排 9 条"证据不足"（2026-09-06 节点 2 实测 13 条里 10 条）。
    降级条目改按"断言集合"去重，severity 由合并时取最高。
    """
    title = " ".join(str(finding.get("title") or "").split())
    if _is_discarded(finding):
        # 原文已被守卫丢弃、只剩同一句模板的条目，一个节点并成一条，待核对断言取并集。
        # 原来按断言集合分开：2026-11-02 server8 复盘 113 条里 74 条是这句模板并排，
        # 每条只差「1245」「2026-05-01」这类碎片，监检没法据此做任何事。
        return ("discarded",)
    if title.startswith(DOWNGRADED_TITLE) and (finding.get("modelTitle") or finding.get("modelDescription")):
        # 降级但保留了模型原文的条目，各自说的是不同的事：按原文做键。原来和模板句一样按断言集合，
        # 它们没有断言，同一 findingType 的全部被并成一条（「耐压缺试验压力」吞掉「泄漏缺试验压力」）。
        return ("downgraded_kept", str(finding.get("findingType") or "").casefold(), _finding_label(finding), _finding_body(finding))
    if title.startswith(DOWNGRADED_TITLE):
        claims = sorted(
            {
                " ".join(str(item.get("claim") if isinstance(item, dict) else item).split()).casefold()
                for item in finding.get("unsupportedClaims") or []
                if item
            }
        )
        return ("downgraded", str(finding.get("findingType") or "").casefold(), *claims)
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


# 「系统读取质量」类条目：说的是我们的 OCR / 抽取没读好，不是资料本身的问题。
# 这类情况逐项结论的理由里已经写了（provider_confidence_unavailable 等），单独成条只会刷屏：
# 2026-11-02 server8 复盘 39 条保留原文的发现里 16 条是噪音，其中多数是这一类。
_META_TITLE_RE = re.compile(r"置信度|识别管线|OCR")
_META_TEXT_RE = re.compile(r"仅(?:显示|提取到|抽到)表头|只(?:抽|提取|读)到表头|签字识别管线未启用")


def _finding_label(finding: dict[str, Any]) -> str:
    title = " ".join(str(finding.get("title") or "").split())
    if title.startswith(DOWNGRADED_TITLE) and finding.get("modelTitle"):
        return " ".join(str(finding.get("modelTitle")).split())
    return title


def _finding_body(finding: dict[str, Any]) -> str:
    return " ".join(str(finding.get("modelDescription") or finding.get("description") or "").split())


def _is_discarded(finding: dict[str, Any]) -> bool:
    title = " ".join(str(finding.get("title") or "").split())
    return title.startswith(DOWNGRADED_TITLE) and not finding.get("modelTitle") and not finding.get("modelDescription")


def _is_meta_finding(finding: dict[str, Any]) -> bool:
    if _is_discarded(finding):
        return False
    return bool(_META_TITLE_RE.search(_finding_label(finding)) or _META_TEXT_RE.search(_finding_body(finding)))


def _bigrams(text: str) -> set[str]:
    compact = re.sub(r"[\s，。、；：,.;:（）()“”\"'！!？?·…—-]+", "", text)
    return {compact[index:index + 2] for index in range(max(len(compact) - 1, 0))}


def _similarity(first: str, second: str) -> float:
    a, b = _bigrams(first), _bigrams(second)
    return len(a & b) / len(a | b) if a and b else 0.0


# 「说的是哪类事」。字面相似分不开同类句式的不同事项：「耐压试验缺试验压力」和「泄漏试验缺试验压力」
# 两两相似度 0.78，真正同义的「缺管道数据表…」几种写法反而只有 0.3–0.6（2026-11-02 server8 实测）。
# 先要求这些事项类别完全一致，再看相似度。
_FINDING_TOPICS = {
    "耐压": ("耐压", "压力试验", "强度试验", "水压试验"),
    "泄漏": ("泄漏", "气密"),
    "无损检测": ("无损检测", "射线", "超声", "检测比例"),
    "防腐": ("防腐", "除锈", "涂层", "涂漆"),
    "签字": ("签字", "签名", "签署"),
    "许可": ("许可",),
    "标准版本": ("标准", "版本", "年份"),
    "数据表": ("数据表", "特性表"),
    "布置图": ("布置图", "平面图", "配管图"),
    "材料表": ("材料表", "材料一览表", "材料等级"),
    "计算书": ("计算书", "应力"),
    "质量证明": ("合格证", "质量证明", "质证书"),
    "焊接": ("焊工", "焊接", "焊材"),
    "制造单位": ("制造单位", "生产厂家", "制造厂"),
}


def _topics(text: str) -> frozenset[str]:
    return frozenset(topic for topic, words in _FINDING_TOPICS.items() if any(word in text for word in words))


def _similar_finding(candidates, finding: dict[str, Any]) -> dict[str, Any] | None:
    """同一节点里换个说法的同一件事（各片各写一遍「缺管道数据表…」）并成一条。

    事项类别要完全一致、建议动作要相同、标题或正文要足够像，才算同一件事：标题相同但
    正文说法相反（「资料不足」对「已经覆盖」）是冲突，必须两条都留着交人工。
    """
    if _is_discarded(finding):
        return None
    label, body = _finding_label(finding), _finding_body(finding)
    topics = _topics(label + body)
    for candidate in candidates:
        if _is_discarded(candidate):
            continue
        if str(candidate.get("suggestedAction") or "") != str(finding.get("suggestedAction") or ""):
            continue
        other_label, other_body = _finding_label(candidate), _finding_body(candidate)
        if _topics(other_label + other_body) != topics:
            continue
        # 认不出事项类别时只合并同一 findingType 的；认得出时允许跨类型——各片对同一件事给的类型常常不同
        same_type = str(candidate.get("findingType") or "").casefold() == str(finding.get("findingType") or "").casefold()
        if not topics and not same_type:
            continue
        title_sim, body_sim = _similarity(label, other_label), _similarity(body, other_body)
        if (title_sim >= 0.5 and body_sim >= 0.4) if not topics else (title_sim >= 0.35 or body_sim >= 0.45):
            return candidate
    return None


def _merge_severity(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    current = _SEVERITY_RANK.get(str(existing.get("severity") or "").lower(), 0)
    candidate = _SEVERITY_RANK.get(str(incoming.get("severity") or "").lower(), 0)
    if candidate > current:
        existing["severity"] = incoming.get("severity")


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
    suppressed_meta: list[str] = []
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
            if _is_meta_finding(finding):
                suppressed_meta.append(_finding_label(finding))
                continue
            key = _finding_key(finding)
            existing = findings_by_key.get(key)
            if not existing:
                existing = _similar_finding(findings_by_key.values(), finding)
            if not existing:
                findings_by_key[key] = finding
                continue
            if finding.get("groundingStatus") == "grounded" and existing.get("groundingStatus") != "grounded":
                # 有据的那条做底：留它的标题和正文，原先那条只并入引用、断言与来源
                previous = deepcopy(existing)
                existing.clear()
                existing.update(deepcopy(finding))
                existing["mergedFindingIds"] = list(previous.get("mergedFindingIds") or [])
                existing["mergedTitles"] = list(previous.get("mergedTitles") or [])
                finding = previous
            _merge_severity(existing, finding)
            existing.setdefault("mergedFindingIds", []).append(str(finding.get("id") or ""))
            merged_label = _finding_label(finding)
            if merged_label and merged_label != _finding_label(existing) and not _is_discarded(finding):
                existing.setdefault("mergedTitles", [])
                if merged_label not in existing["mergedTitles"]:
                    existing["mergedTitles"].append(merged_label)
            for list_key in ("unsupportedClaims", "evidenceValidationFailures"):
                if finding.get(list_key):
                    existing[list_key] = _union_records(existing.get(list_key) or [], finding.get(list_key) or [])
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
        # 不单独出发现的「系统读取质量」类条目：只留计数和标题，这些情况逐项结论的理由里已经写了
        "suppressedMetaFindings": {"count": len(suppressed_meta), "titles": list(dict.fromkeys(suppressed_meta))[:20]},
        "aggregationVersion": "similar-merge-meta-suppress@1.1.0",
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
            shard_context["evidenceShardScope"] = evidence_shard_scope(state, shard, len(shards))
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
                # 分片失败原因此前只留在 failureReason 的类名里，排查时看不到堆栈；记一条 warning
                LOGGER.warning("evidence shard %s failed: %r", shard_id, exc, exc_info=True)
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
    combined_metadata["failedShardIds"] = list(failed_shard_ids)
    review_run["failedEvidenceShardIds"] = list(failed_shard_ids)
    review_run["llmMetadata"] = deepcopy(combined_metadata)
    # P8 H4：失败分片不再让整次审查 review_incomplete。修复与升级都试过仍失败的分片
    # 记进 failedEvidenceShardIds，其余分片照常完成，质量门禁标"部分分片未完成"；
    # 只有一片都没完成（没有任何可审的产出）才整次标未完成。
    if not deterministic and failed_shard_ids and not shard_results:
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
