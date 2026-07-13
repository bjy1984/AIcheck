from __future__ import annotations

from typing import Any


OCR_READY_STATUSES = {"ready"}
OCR_RETRYABLE_STATUSES = {"failed", "incomplete", "inconsistent"}
OCR_FORMAL_BLOCKING_REASONS = {
    "FIELD_EVIDENCE_MISSING",
    "TABLE_EVIDENCE_MISSING",
    "SEAL_EVIDENCE_MISSING",
    "REQUIRED_FIELD_MISSING",
    "REQUIRED_TABLE_MISSING",
    "SEAL_NOT_FOUND",
    "OCR_OUTPUT_TRUNCATED",
    "DOCUMENT_COST_LIMIT_EXCEEDED",
    "PAGE_COST_REVIEW_REQUIRED",
    "UNSUPPORTED_ATTRIBUTION",
    "PROFILE_NOT_CERTIFIED_FOR_FORMAL_READINESS",
}


def parse_result_quality_blockers(parse_result: dict[str, Any] | None) -> list[str]:
    quality = (parse_result or {}).get("quality")
    if not isinstance(quality, dict):
        return []
    reasons = {str(item) for item in quality.get("reasons") or []}
    return sorted(reasons & OCR_FORMAL_BLOCKING_REASONS)


def parse_result_outcome_status(parse_result: dict[str, Any] | None) -> str:
    execution_status = str((parse_result or {}).get("status") or "").lower()
    quality = (parse_result or {}).get("quality")
    quality_status = str(quality.get("status") or "") if isinstance(quality, dict) else ""
    if execution_status not in {"success", "succeeded", "completed"} or quality_status == "failed":
        return "failed"
    if parse_result_quality_blockers(parse_result):
        return "partial"
    return "completed"


def _has_bbox(item: dict[str, Any]) -> bool:
    bbox = item.get("bbox") or item.get("box") or item.get("boundingBox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return False
    try:
        left, top, right, bottom = (float(value) for value in bbox[:4])
    except (TypeError, ValueError):
        return False
    return right > left and bottom > top


def _has_content(item: dict[str, Any]) -> bool:
    for key in ("fieldValue", "value", "text", "content", "html"):
        if str(item.get(key) or "").strip():
            return True
    rows = item.get("rows") or item.get("cells")
    return isinstance(rows, list) and bool(rows)


def _latest_parse_result(repo: Any, document_version_id: str | None) -> dict[str, Any] | None:
    if not document_version_id:
        return None
    matches = [
        item
        for item in repo.state.get("ocr_parse_results", [])
        if str(item.get("documentVersionId") or "") == str(document_version_id)
    ]
    if not matches:
        return None
    return max(
        matches,
        key=lambda item: str(item.get("finishedAt") or item.get("createdAt") or ""),
    )


def build_document_ocr_readiness(repo: Any, document: dict[str, Any]) -> dict[str, Any]:
    document_version_id = str(document.get("currentVersionId") or "") or None
    parse_result = _latest_parse_result(repo, document_version_id)
    source_status = str(document.get("currentOcrStatus") or "")
    field_rows = [item for item in (parse_result or {}).get("fields", []) if isinstance(item, dict) and _has_content(item)]
    fragment_rows = [item for item in (parse_result or {}).get("fragments", []) if isinstance(item, dict) and _has_content(item)]
    table_rows = [item for item in (parse_result or {}).get("tables", []) if isinstance(item, dict) and _has_content(item)]
    seal_rows = [item for item in (parse_result or {}).get("seals", []) if isinstance(item, dict) and _has_content(item)]
    evidence_rows = [*field_rows, *fragment_rows, *table_rows, *seal_rows]
    positioned_count = len([item for item in evidence_rows if _has_bbox(item)])
    bbox_coverage = round(positioned_count / len(evidence_rows), 4) if evidence_rows else 0.0
    issues: list[dict[str, Any]] = []
    pipeline_runs = [
        item
        for item in repo.state.get("ocr_pipeline_runs", [])
        if str(item.get("documentVersionId") or "") == str(document_version_id or "")
    ]
    pipeline_run = max(
        pipeline_runs,
        key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""),
    ) if pipeline_runs else None
    pipeline_stages = [
        item
        for item in repo.state.get("ocr_stage_runs", [])
        if pipeline_run and item.get("pipelineRunId") == pipeline_run.get("id")
    ]
    stages_by_name = {str(item.get("stage") or ""): item for item in pipeline_stages}

    if source_status in {"排队中"}:
        status = "queued"
    elif source_status in {"识别中"}:
        status = "processing"
    elif source_status in {"识别失败"}:
        status = "failed"
    elif source_status in {"抽取不完整"}:
        status = "incomplete"
    elif not parse_result:
        status = "inconsistent" if source_status in {"已识别", "人工修正"} else "not_started"
        if status == "inconsistent":
            issues.append(
                {
                    "code": "OCR_STATUS_WITHOUT_PARSE_RESULT",
                    "message": "文件标记为已识别，但没有可追溯的 OCR parse result。",
                    "actionKey": "retry_ocr",
                    "targetId": document.get("id"),
                }
            )
    elif parse_result_outcome_status(parse_result) == "failed":
        status = "failed"
        issues.append(
            {
                "code": "OCR_PARSE_RESULT_FAILED",
                "message": "最近一次 OCR parse result 未成功完成。",
                "actionKey": "retry_ocr",
                "targetId": document.get("id"),
            }
        )
    elif parse_result_quality_blockers(parse_result):
        status = "incomplete"
        issues.append(
            {
                "code": "OCR_QUALITY_GATE_BLOCKED",
                "message": "OCR 已执行，但必填字段、表格、印章或可定位证据仍不完整。",
                "qualityReasons": parse_result_quality_blockers(parse_result),
                "actionKey": "review_ocr",
                "targetId": document.get("id"),
            }
        )
    elif not evidence_rows:
        status = "incomplete"
        issues.append(
            {
                "code": "OCR_RESULT_HAS_NO_EVIDENCE",
                "message": "OCR 已完成，但没有有效文字、字段、表格或印章产物。",
                "actionKey": "retry_ocr",
                "targetId": document.get("id"),
            }
        )
    elif positioned_count == 0:
        status = "incomplete"
        issues.append(
            {
                "code": "OCR_EVIDENCE_HAS_NO_BBOX",
                "message": "OCR 有文本产物，但没有可定位的 bbox，不能作为正式审计证据。",
                "actionKey": "review_ocr",
                "targetId": document.get("id"),
            }
        )
    else:
        status = "ready"

    structure_status = str((stages_by_name.get("structure_scan") or {}).get("status") or "")
    seal_status = str((stages_by_name.get("seal_signature_scan") or {}).get("status") or "")
    qwen_status = str((stages_by_name.get("qwen_extract") or {}).get("status") or "")
    qwen_validation = (pipeline_run or {}).get("groundingValidation") or {}
    parse_metadata = (parse_result or {}).get("metadata")
    parse_metadata = parse_metadata if isinstance(parse_metadata, dict) else {}
    return {
        "schemaVersion": "aicheck-ocr-readiness@1",
        "status": status,
        "artifactIntegrity": status == "ready",
        "sourceStatus": source_status or None,
        "documentVersionId": document_version_id,
        "parseResultId": (parse_result or {}).get("parseResultId") or (parse_result or {}).get("id"),
        "outcomeStatus": parse_result_outcome_status(parse_result) if parse_result else None,
        "qualityStatus": ((parse_result or {}).get("quality") or {}).get("status"),
        "fieldCount": len(field_rows),
        "fragmentCount": len(fragment_rows),
        "tableCount": len(table_rows),
        "sealCount": len(seal_rows),
        "positionedEvidenceCount": positioned_count,
        "bboxCoverage": bbox_coverage,
        "blockingReasons": issues,
        "retryable": status in OCR_RETRYABLE_STATUSES,
        "finishedAt": (parse_result or {}).get("finishedAt"),
        "pipelineRunId": (pipeline_run or {}).get("id"),
        "pipelineMode": (pipeline_run or {}).get("mode"),
        "pipelineStatus": (pipeline_run or {}).get("status"),
        "pipelineStage": (pipeline_run or {}).get("currentStage"),
        "scannerReady": bool(parse_result and evidence_rows),
        "structureReady": structure_status in {"success", "skipped"},
        "sealEvidenceReady": seal_status in {"success", "skipped"},
        "qwenGrounded": bool(
            qwen_status == "success"
            and int(qwen_validation.get("invalidCandidateIdCount") or 0) == 0
        ),
        "formalEvidenceReady": bool((pipeline_run or {}).get("formalEvidenceReady")),
        "formalReadinessBlockingReasons": (pipeline_run or {}).get("formalReadinessBlockingReasons") or [],
        "formalReadinessProfileAllowed": bool(
            (pipeline_run or {}).get("formalReadinessProfileAllowed")
            or parse_metadata.get("formalReadinessProfileAllowed")
        ),
        "providerMode": (pipeline_run or {}).get("providerMode") or parse_metadata.get("providerMode"),
        "provider": (pipeline_run or {}).get("provider") or parse_metadata.get("provider"),
        "model": (pipeline_run or {}).get("model") or parse_metadata.get("model"),
        "cloudGrounded": bool((pipeline_run or {}).get("cloudGrounded") or parse_metadata.get("cloudGrounded")),
        "providerReady": not any(
            str(item.get("code") or "") in {"OFFICIAL_OCR_FAILED", "CIRCUIT_OPEN"}
            for item in ((pipeline_run or {}).get("blockingReasons") or [])
            if isinstance(item, dict)
        ),
        "globalCapacityReady": not any(
            str(item.get("code") or "") in {"PROVIDER_CAPACITY_UNAVAILABLE", "REDIS_CONTROL_UNAVAILABLE"}
            for item in ((pipeline_run or {}).get("blockingReasons") or [])
            if isinstance(item, dict)
        ),
        "outputTruncated": bool(
            ((pipeline_run or {}).get("groundingValidation") or {}).get("outputTruncated")
            or parse_metadata.get("outputTruncated")
        ),
        "providerRequestId": (
            ((pipeline_run or {}).get("providerRequestIds") or parse_metadata.get("providerRequestIds") or [None])[0]
        ),
        "costCny": float((pipeline_run or {}).get("costCny") or parse_metadata.get("costCny") or 0.0),
        "fallbackReason": (pipeline_run or {}).get("fallbackReason") or parse_metadata.get("fallbackReason"),
        "providerWaitReason": (pipeline_run or {}).get("providerWaitReason"),
        "lastHeartbeatAt": (pipeline_run or {}).get("lastHeartbeatAt"),
    }


def attach_document_ocr_readiness(repo: Any, document: dict[str, Any]) -> dict[str, Any]:
    cloned = repo.clone(document)
    cloned["ocrReadiness"] = build_document_ocr_readiness(repo, cloned)
    return cloned
