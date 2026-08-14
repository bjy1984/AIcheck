"""节点与文档的标识归一。

从 apps/api/routes.py 搬出来的纯函数：把节点号、文档号、记录 ID 归一成
统一形状，供各处比对使用。

这批既不碰 repo 也不碰 Request，只做取值与归一——留在两万七千行的路由文件里
既难找也没人测，而它们算错不会报错，只会让「同一份资料」被当成两份。
"""

from __future__ import annotations

from typing import Any


def record_revision(record: dict[str, Any]) -> int:
    return int(record.get("revision") or 1)

def record_etag(prefix: str, record: dict[str, Any]) -> str:
    return f'W/"{prefix}-{record["id"]}-r{record_revision(record)}"'

def record_if_match_valid(prefix: str, record: dict[str, Any], if_match: str | None) -> bool:
    if not if_match:
        return True
    revision = record_revision(record)
    return if_match in {"*", str(revision), f'W/"{revision}"', record_etag(prefix, record)}

def record_references_report(record: dict[str, Any]) -> bool:
    return bool(record.get("reportId")) or record.get("targetType") == "report" or record.get("exportType") == "report"

def document_ai_shadow_run_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        key: run.get(key)
        for key in [
            "id",
            "runId",
            "status",
            "advisoryOnly",
            "businessImpact",
            "documentId",
            "documentVersionId",
            "parseResultId",
            "profileId",
            "templateVersion",
            "fileName",
            "operationId",
            "taskId",
            "remoteRunId",
            "modelRevision",
            "paddleModelRevision",
            "priorCandidateCount",
            "priorOmittedCandidateCount",
            "priorEstimatedTokenCount",
            "selectedPageNos",
            "queueTimeMs",
            "inferenceTimeMs",
            "totalTimeMs",
            "jsonRetryCount",
            "tableExtractionDeferred",
            "failureReason",
            "createdAt",
            "queuedAt",
            "startedAt",
            "finishedAt",
            "updatedAt",
        ]
        if run.get(key) is not None
    }

def document_audit_pipeline_comparison_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        key: run.get(key)
        for key in [
            "id",
            "runId",
            "status",
            "documentAiShadowRunId",
            "documentId",
            "documentVersionId",
            "profileId",
            "fileName",
            "selectedPageNos",
            "baselinePipelineId",
            "baselineProvider",
            "baselineModel",
            "baselineModelResolved",
            "challengerPipelineId",
            "challengerProvider",
            "challengerModel",
            "challengerModelResolved",
            "baselineTimeMs",
            "challengerUpstreamDocumentAiTimeMs",
            "challengerDeepSeekTimeMs",
            "challengerEndToEndTimeMs",
            "comparisonMetrics",
            "failureReason",
            "createdAt",
            "queuedAt",
            "startedAt",
            "finishedAt",
            "updatedAt",
        ]
        if run.get(key) is not None
    }
