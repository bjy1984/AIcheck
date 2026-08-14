"""FDE 控制台的视图组装。

从 apps/api/routes.py 搬出来的 82 个纯函数（1330 行）：把审计运行、标准条款、
向量索引、OCR 采样等数据整形成控制台要显示的形状。

## 为什么单独成模块

routes.py 三万余行，其中 368 个路由端点、576 个模块级函数。这批 fde_* 视图
组装既不碰 repo 也不碰 Request，只做数据整形——留在路由文件里既难找也难单测，
而它们恰恰是最该被单测钉住的那类（形状错了界面就空一块，不报错）。

搬迁口径是**自封闭**：只搬那些传递引用全在本组内的函数。有 50 个 fde_* 函数
因为回引 routes.py 里依赖 repo/Request 的东西而留在原处——强行搬会造成循环
import，那比文件大更糟。
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from libs.business_pack import (
    business_pack_summary,
    load_business_pack,
    validate_business_pack,
)
from libs.integrations.errors import IntegrationServiceError
from libs.integrations.ocr_client import OcrClient
from libs.knowledge_indexing import (
    OFFLINE_EMBEDDING_MODEL,
    noise_like_text,
)
from libs.ocr.utils import parse_bool


def fde_bounded_expiry(
    raw_value: Any,
    *,
    default_minutes: int,
    max_hours: int = 24,
) -> str:
    now = datetime.now(UTC)
    if raw_value:
        normalized = str(raw_value).strip().replace("Z", "+00:00")
        expires_at = datetime.fromisoformat(normalized)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        else:
            expires_at = expires_at.astimezone(UTC)
    else:
        expires_at = now + timedelta(minutes=default_minutes)
    if expires_at <= now:
        raise ValueError("授权有效期必须晚于当前时间。")
    if expires_at > now + timedelta(hours=max_hours):
        raise ValueError(f"授权有效期不能超过 {max_hours} 小时。")
    return expires_at.isoformat()

def fde_expiry_is_active(raw_value: Any) -> bool:
    if not raw_value:
        return False
    try:
        normalized = str(raw_value).strip().replace("Z", "+00:00")
        expires_at = datetime.fromisoformat(normalized)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at.astimezone(UTC) > datetime.now(UTC)
    except (TypeError, ValueError):
        return False

FDE_STATUS_CATALOG = [
    {"code": "not_started", "label": "未开始", "tone": "info", "terminal": False},
    {"code": "in_progress", "label": "处理中", "tone": "primary", "terminal": False},
    {"code": "needs_attention", "label": "需关注", "tone": "warning", "terminal": False},
    {"code": "failed", "label": "执行失败", "tone": "danger", "terminal": True},
    {"code": "failed_to_start", "label": "启动失败", "tone": "danger", "terminal": True},
    {"code": "completed", "label": "已完成", "tone": "success", "terminal": True},
]

def fde_metric(
    label: str,
    value: Any,
    tone: str = "blue",
    suffix: str = "",
    *,
    key: str | None = None,
    numerator: float | None = None,
    denominator: float | None = None,
    sample_size: int | None = None,
    availability: str = "available",
    scope: str = "tenant",
) -> dict[str, Any]:
    return {
        "key": key or re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or label,
        "label": label,
        "value": value,
        "tone": tone,
        "suffix": suffix,
        "unit": suffix or "count",
        "numerator": numerator,
        "denominator": denominator,
        "sampleSize": sample_size,
        "availability": availability,
        "scope": scope,
    }

def fde_status_code(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"failed_to_start"}:
        return "failed_to_start"
    if normalized in {"failed", "failure", "error", "失败", "识别失败", "rejected"}:
        return "failed"
    if normalized in {
        "completed",
        "complete",
        "success",
        "succeeded",
        "passed",
        "done",
        "已完成",
        "已识别",
        "识别完成",
        "已人工确认",
        "closed",
    }:
        return "completed"
    if normalized in {
        "queued",
        "running",
        "processing",
        "submitted",
        "canary_requested",
        "canary_running",
        "shadow_running",
        "pending",
        "pending_approval",
        "排队中",
        "运行中",
        "识别中",
    }:
        return "in_progress"
    if normalized in {
        "blocked",
        "blocked_by_gate",
        "waiting_human_review",
        "needs_human_review",
        "attention",
        "warning",
    }:
        return "needs_attention"
    return "not_started"

def fde_status_summary(items: list[dict[str, Any]], *, field: str = "status") -> dict[str, int]:
    summary = {item["code"]: 0 for item in FDE_STATUS_CATALOG}
    for item in items:
        code = fde_status_code(item.get(field))
        summary[code] = summary.get(code, 0) + 1
    return summary

def fde_blocker_record(
    *,
    domain: str,
    category: str,
    severity: str,
    code: str,
    title: str,
    source_type: str,
    source_id: Any,
    route: str,
    description: str | None = None,
    project_id: Any = None,
    detected_at: Any = None,
    action_label: str = "查看详情",
) -> dict[str, Any]:
    stable_source_id = str(source_id or "unknown")
    return {
        "id": f"{domain}:{source_type}:{stable_source_id}:{code}",
        "domain": domain,
        "category": category,
        "severity": severity,
        "code": code,
        "title": title,
        "description": description or title,
        "sourceType": source_type,
        "sourceId": stable_source_id,
        "projectId": project_id,
        "statusCode": "failed" if severity == "critical" else "needs_attention",
        "statusLabel": "执行失败" if severity == "critical" else "需关注",
        "statusTone": "danger" if severity == "critical" else "warning",
        "detectedAt": detected_at,
        "route": route,
        "actionLabel": action_label,
    }

def fde_business_pack_validation_result(pack_id: str) -> dict[str, Any] | None:
    try:
        pack = load_business_pack(pack_id)
    except FileNotFoundError:
        return None
    validation = validate_business_pack(pack)
    return {"summary": business_pack_summary(pack), "validation": validation}

def fde_diff_value(value: Any) -> Any:
    if isinstance(value, dict):
        ignored = {"createdAt", "updatedAt", "installedAt", "submittedAt", "approvedAt", "shadowStartedAt"}
        return {key: fde_diff_value(value[key]) for key in sorted(value) if key not in ignored}
    if isinstance(value, list):
        return [fde_diff_value(item) for item in value]
    return value

def fde_record_diff(current: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    baseline = baseline or {}
    current_normalized = fde_diff_value(current)
    baseline_normalized = fde_diff_value(baseline)
    keys = sorted(set(current_normalized) | set(baseline_normalized))
    changes = []
    for key in keys:
        before = baseline_normalized.get(key)
        after = current_normalized.get(key)
        if before != after:
            changes.append({"field": key, "before": before, "after": after})
    return {
        "changed": bool(changes),
        "changeCount": len(changes),
        "changes": changes,
        "addedKeys": [key for key in keys if key not in baseline_normalized],
        "removedKeys": [key for key in keys if key not in current_normalized],
    }

def fde_audit_event_scope(item: dict[str, Any]) -> bool:
    action = str(item.get("action") or "")
    object_type = str(item.get("objectType") or "")
    return action.startswith(("FDE", "管理员批准 FDE", "管理员审批 FDE")) or object_type in {
        "AccessGrant",
        "DataExport",
        "AIRunReplay",
        "ReviewRun",
        "FeedbackTriage",
        "EvaluationRun",
        "CapabilityBundle",
        "ReleasePlan",
        "BusinessPackInstallation",
        "IncidentRCA",
        "OcrCorrection",
        "OcrEvaluationRun",
        "CostBudgetChangeRequest",
        "MaskingPolicy",
    }

def fde_as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default

def fde_knowledge_lineage_stage(
    *,
    key: str,
    label: str,
    done: bool,
    status: str,
    evidence: str,
    action: str,
    blocker: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "done": done,
        "tone": "green" if done else "orange",
        "evidence": evidence,
        "action": action,
        "blocker": blocker,
        "metrics": metrics or {},
    }

def fde_document_knowledge_lineage(document: dict[str, Any]) -> dict[str, Any]:
    """Build a FDE-facing lineage view for one document without mutating business state."""
    ocr_status = str(document.get("currentOcrStatus") or document.get("ocrStatus") or "")
    slice_status = str(document.get("sliceStatus") or "")
    vector_status = str(document.get("vectorStatus") or "")
    page_index_status = str(document.get("pageIndexStatus") or "")
    chunk_count = fde_as_int(document.get("chunkCount"))
    vector_count = fde_as_int(document.get("vectorCount"))
    vector_gap = max(0, chunk_count - vector_count)
    page_index_node_count = fde_as_int(document.get("pageIndexNodeCount"))
    latest_task = document.get("latestKnowledgeTask")
    if isinstance(latest_task, dict):
        latest_task_status = str(latest_task.get("status") or latest_task.get("taskStatus") or "-")
        latest_task_type = str(latest_task.get("taskType") or "-")
    else:
        latest_task_status = str(latest_task or "-")
        latest_task_type = "-"

    ocr_done = "已识别" in ocr_status or "人工修正" in ocr_status or "success" in ocr_status
    sliced = "已切片" in slice_status or chunk_count > 0
    vectorized = "已向量化" in vector_status or (vector_count > 0 and vector_gap == 0)
    page_index_ready = "已构建" in page_index_status or page_index_node_count > 0
    review_ready = ocr_done and sliced and vectorized and page_index_ready

    stages = [
        fde_knowledge_lineage_stage(
            key="ocr_parse",
            label="资料解析",
            done=ocr_done,
            status=ocr_status or "等待OCR",
            evidence=f"OCR状态：{ocr_status or '未开始'}",
            action="进入 OCR 打标或重跑文档解析" if not ocr_done else "保留字段、表格、印章和 bbox 证据",
            blocker=None if ocr_done else "OCR 未完成",
            metrics={"status": ocr_status},
        ),
        fde_knowledge_lineage_stage(
            key="knowledge_slice",
            label="知识切片",
            done=sliced,
            status=slice_status or "待切片",
            evidence=f"切片 {chunk_count} 条",
            action="重跑 knowledge.slice" if not sliced else "切片已保留页码、bbox 和资料 Profile",
            blocker=None if sliced else "知识切片未完成",
            metrics={"chunkCount": chunk_count},
        ),
        fde_knowledge_lineage_stage(
            key="vector_embed",
            label="向量入库",
            done=vectorized,
            status=vector_status or "待向量化",
            evidence=f"向量 {vector_count}/{chunk_count} 条，模型 {document.get('embeddingModel') or OFFLINE_EMBEDDING_MODEL}",
            action=(
                "排查失败 chunk 并补跑 knowledge.embed"
                if vector_gap
                else ("重跑 knowledge.embed" if not vectorized else "可参与 Hybrid RAG 检索")
            ),
            blocker=("向量条目少于切片" if vector_gap else (None if vectorized else "向量入库未完成")),
            metrics={"vectorCount": vector_count, "chunkCount": chunk_count, "vectorGap": vector_gap},
        ),
        fde_knowledge_lineage_stage(
            key="pageindex_tree",
            label="PageIndex",
            done=page_index_ready,
            status=page_index_status or "待构建",
            evidence=f"PageIndex 节点 {page_index_node_count} 个",
            action="构建 PageIndex tree 并校验条款映射" if not page_index_ready else "可用于长文档跨章节溯源",
            blocker=None if page_index_ready else "PageIndex 未构建",
            metrics={"pageIndexNodeCount": page_index_node_count},
        ),
        fde_knowledge_lineage_stage(
            key="review_ready",
            label="审查可用",
            done=review_ready,
            status="可用于审查" if review_ready else "需补齐",
            evidence="规则、知识检索和 Agent 编排可引用该资料" if review_ready else "存在 OCR/切片/向量/PageIndex 缺口",
            action="纳入 ReviewRun 规则、RAG 和 PageIndex 溯源" if review_ready else "按前置阻断顺序补齐后再进入审查",
            blocker=None if review_ready else "资料知识资产未达到审查可用门禁",
            metrics={"reviewReady": review_ready},
        ),
    ]
    blockers = [stage["blocker"] for stage in stages if stage.get("blocker")]
    return {
        "schemaVersion": "FdeKnowledgeLineage@1.0.0",
        "documentId": document.get("id"),
        "documentVersionId": document.get("currentVersionId") or document.get("documentVersionId"),
        "knowledgeFileId": document.get("knowledgeFileId"),
        "fileName": document.get("fileName"),
        "readiness": "ready_for_review" if review_ready else "needs_attention",
        "readinessLabel": "可用于审查" if review_ready else "需补齐",
        "auditConclusion": "该资料可进入规则、Hybrid RAG、PageIndex 和 Agent 审查编排。"
        if review_ready
        else "该资料仍有知识资产缺口，FDE 应先补齐阻断再放入审查链。",
        "localOnly": True,
        "latestTaskType": latest_task_type,
        "latestTaskStatus": latest_task_status,
        "vectorIndex": {
            "embeddingModel": document.get("embeddingModel") or OFFLINE_EMBEDDING_MODEL,
            "indexVersion": document.get("indexVersion") or "knowledge-index@local",
            "dimensions": fde_as_int(document.get("vectorDimensions"), 1024),
            "chunkCount": chunk_count,
            "vectorCount": vector_count,
            "vectorGap": vector_gap,
        },
        "pageIndex": {
            "status": page_index_status or "待构建",
            "nodeCount": page_index_node_count,
            "coverageLabel": "已覆盖" if page_index_ready else "待构建",
        },
        "stages": stages,
        "blockers": blockers,
    }

def fde_ratio(numerator: float, denominator: float, *, default: float = 0.0) -> float:
    try:
        denominator_value = float(denominator)
        if denominator_value <= 0:
            return default
        return max(0.0, min(1.0, float(numerator) / denominator_value))
    except (TypeError, ValueError, ZeroDivisionError):
        return default

def fde_score_section(
    *,
    key: str,
    name: str,
    score: float,
    max_score: float,
    metric: float,
    threshold: float,
    blockers: list[str],
) -> dict[str, Any]:
    score = round(max(0.0, min(score, max_score)), 2)
    return {
        "key": key,
        "name": name,
        "score": score,
        "maxScore": max_score,
        "metric": round(max(0.0, min(metric, 1.0)), 4),
        "threshold": threshold,
        "status": "pass" if score >= max_score * threshold and not blockers else "warn",
        "blockers": blockers,
    }

def fde_trace_selected_clauses(trace: dict[str, Any]) -> list[dict[str, Any]]:
    selected = trace.get("selectedClauses") or trace.get("clauses") or []
    return [item for item in selected if isinstance(item, dict)]

def fde_trace_evidence_backed(trace: dict[str, Any]) -> bool:
    for clause in fde_trace_selected_clauses(trace):
        if clause.get("pageNo") is not None and clause.get("bbox"):
            return True
    return False

def fde_chunk_text_preview(text: Any, limit: int = 180) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."

def fde_chunk_text_hash(text: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return ""
    return f"sha256:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]}"

def fde_trace_chunk_identifiers(trace: dict[str, Any]) -> set[str]:
    identifiers: set[str] = set()
    for clause in fde_trace_selected_clauses(trace):
        for key in ("id", "clauseId", "chunkId"):
            value = clause.get(key)
            if not value:
                continue
            text = str(value)
            identifiers.add(text)
            if text.startswith("KC-"):
                identifiers.add(text[3:])
    return identifiers

def fde_trace_matches_document(trace: dict[str, Any], *, file_id: str, document_version_id: str) -> bool:
    for clause in fde_trace_selected_clauses(trace):
        if file_id and str(clause.get("fileId") or "") == file_id:
            return True
        if document_version_id and str(clause.get("documentVersionId") or "") == document_version_id:
            return True
    return False

def fde_chunk_quality_flags(chunk: dict[str, Any], *, vector_ready: bool, retrieval_hit_count: int, duplicate: bool) -> list[str]:
    flags: list[str] = []
    text = str(chunk.get("text") or "")
    token_count = fde_as_int(chunk.get("tokenCount"))
    if not chunk.get("materialized", True):
        flags.append("not_materialized")
    if not text.strip():
        flags.append("empty_text")
    elif token_count < 20 or len(text) < 40:
        flags.append("too_short")
    elif token_count > 1200 or len(text) > 2400:
        flags.append("too_long")
    if chunk.get("pageNo") is None:
        flags.append("missing_page")
    if not chunk.get("bbox"):
        flags.append("missing_bbox")
    if not vector_ready:
        flags.append("missing_vector")
    if retrieval_hit_count <= 0:
        flags.append("not_retrieved")
    if duplicate:
        flags.append("duplicate_text")
    if fde_roi_is_noise_text(text):
        flags.append("noise_like_watermark")
    return flags

def fde_noise_chunk_blocker(flag_counts: dict[str, int], effective_count: int) -> str | None:
    noise_count = fde_as_int(flag_counts.get("noise_like_watermark"))
    if noise_count <= 0 or effective_count <= 0:
        return None
    noise_ratio = fde_ratio(noise_count, effective_count, default=0.0)
    if noise_count >= 3 or noise_ratio >= 0.05:
        return f"疑似水印/下载站文本 {noise_count} 条，占比 {noise_ratio:.1%}，需要重新 OCR/切片治理"
    return None

def fde_noise_chunk_score_penalty(flag_counts: dict[str, int], effective_count: int) -> float:
    noise_count = fde_as_int(flag_counts.get("noise_like_watermark"))
    if noise_count <= 0 or effective_count <= 0:
        return 0.0
    return min(18.0, round(100 * fde_ratio(noise_count, effective_count, default=0.0) * 0.6, 2))

def fde_pipeline_ocr_view(
    document_version_id: str,
    parse_result: dict[str, Any] | None,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    parse_fields = (parse_result or {}).get("fields") or []
    parse_fragments = (parse_result or {}).get("fragments") or []
    parse_tables = (parse_result or {}).get("tables") or []
    parse_seals = (parse_result or {}).get("seals") or []
    source_fields = [item for item in parse_fields if isinstance(item, dict)] or fields
    field_rows = [
        {
            "fieldName": item.get("fieldName") or item.get("name") or item.get("fieldCode"),
            "fieldCode": item.get("fieldCode") or item.get("code"),
            "fieldValue": item.get("fieldValue") or item.get("value"),
            "pageNo": item.get("pageNo"),
            "bbox": item.get("bbox"),
            "confidence": item.get("confidence"),
            "source": item.get("sourceEngine") or item.get("extractionMethod") or "extracted_fields",
        }
        for item in source_fields[:20]
    ]
    return {
        "stage": "ocr",
        "label": "OCR 结构化识别",
        "status": (parse_result or {}).get("status") or ("field_only" if fields else "missing"),
        "parseResultId": (parse_result or {}).get("parseResultId"),
        "profileId": (parse_result or {}).get("profileId"),
        "documentType": (parse_result or {}).get("documentType"),
        "parserVersion": (parse_result or {}).get("parserVersion"),
        "engineVersion": (parse_result or {}).get("engineVersion"),
        "engineRuns": (parse_result or {}).get("engineRuns") or [],
        "diagnostics": (parse_result or {}).get("diagnostics") or [],
        "summary": {
            "pageCount": len((parse_result or {}).get("pages") or []),
            "fragmentCount": len(parse_fragments or []),
            "fieldCount": len(source_fields),
            "tableCount": len(parse_tables or []),
            "sealCount": len(parse_seals or []),
        },
        "fieldRows": field_rows,
        "fragmentRows": [
            {
                "fragmentId": item.get("fragmentId") or item.get("id") or f"fragment-{index}",
                "pageNo": item.get("pageNo"),
                "textPreview": fde_chunk_text_preview(item.get("text")),
                "bbox": item.get("bbox"),
                "confidence": item.get("confidence"),
                "sourceEngine": item.get("sourceEngine"),
            }
            for index, item in enumerate(parse_fragments[:20], start=1)
            if isinstance(item, dict)
        ],
        "quality": (parse_result or {}).get("quality") or {},
        "documentVersionId": document_version_id,
    }

def fde_ocr_artifacts_view(
    document_version_id: str,
    parse_result: dict[str, Any] | None,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    ocr = fde_pipeline_ocr_view(document_version_id, parse_result, fields)
    parse_tables = (parse_result or {}).get("tables") or []
    parse_seals = (parse_result or {}).get("seals") or []
    return {
        "schemaVersion": "FdeOcrArtifacts@1.0.0",
        **ocr,
        "fields": ocr["fieldRows"],
        "fragments": ocr["fragmentRows"],
        "tables": [
            {
                "tableId": item.get("tableId") or item.get("id") or f"table-{index}",
                "pageNo": item.get("pageNo"),
                "bbox": item.get("bbox"),
                "rowCount": item.get("rows") or item.get("rowCount"),
                "columnCount": item.get("columns") or item.get("columnCount"),
                "structureConfidence": item.get("structureConfidence") or item.get("confidence"),
                "schema": item.get("businessSchema") or item.get("schema"),
                "sourceEngine": item.get("sourceEngine"),
            }
            for index, item in enumerate(parse_tables[:20], start=1)
            if isinstance(item, dict)
        ],
        "seals": [
            {
                "sealId": item.get("sealId") or item.get("id") or f"seal-{index}",
                "pageNo": item.get("pageNo"),
                "bbox": item.get("bbox"),
                "sealType": item.get("sealType"),
                "sealName": item.get("sealName") or item.get("text"),
                "visualConfidence": item.get("visualConfidence"),
                "ocrConfidence": item.get("ocrConfidence") or item.get("confidence"),
                "qualityFlags": item.get("qualityFlags") or [],
                "sourceEngine": item.get("sourceEngine"),
            }
            for index, item in enumerate(parse_seals[:20], start=1)
            if isinstance(item, dict)
        ],
    }

def fde_roi_bbox_extents(raw: Any) -> list[float] | None:
    if not isinstance(raw, list) or len(raw) < 4:
        return None
    if isinstance(raw[0], list):
        points: list[tuple[float, float]] = []
        for point in raw:
            if not isinstance(point, list) or len(point) < 2:
                continue
            try:
                x = float(point[0])
                y = float(point[1])
            except (TypeError, ValueError):
                continue
            if math.isfinite(x) and math.isfinite(y):
                points.append((x, y))
        if not points:
            return None
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return [min(xs), min(ys), max(xs), max(ys)]
    try:
        values = [float(value) for value in raw[:4]]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in values):
        return None
    x1, y1, x2, y2 = values
    return [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]

def fde_roi_polygon(raw: Any, extents: list[float] | None = None) -> list[list[float]]:
    if isinstance(raw, list) and raw and isinstance(raw[0], list):
        polygon: list[list[float]] = []
        for point in raw:
            if not isinstance(point, list) or len(point) < 2:
                continue
            try:
                x = float(point[0])
                y = float(point[1])
            except (TypeError, ValueError):
                continue
            if math.isfinite(x) and math.isfinite(y):
                polygon.append([round(x, 4), round(y, 4)])
        if len(polygon) >= 3:
            return polygon
    if not extents:
        return []
    x1, y1, x2, y2 = extents
    return [[round(x1, 4), round(y1, 4)], [round(x2, 4), round(y1, 4)], [round(x2, 4), round(y2, 4)], [round(x1, 4), round(y2, 4)]]

def fde_page_source_dimensions_for_roi(
    *,
    bbox: list[float] | None,
    source_method: str,
    page_info: dict[str, Any] | None,
) -> tuple[str, float | None, float | None, list[str]]:
    warnings: list[str] = []
    page_width = float(page_info.get("width") or 0) if page_info else 0.0
    page_height = float(page_info.get("height") or 0) if page_info else 0.0
    preview_width = float(page_info.get("previewWidth") or 0) if page_info else 0.0
    preview_height = float(page_info.get("previewHeight") or 0) if page_info else 0.0
    ocr_width = float(page_info.get("ocrImageWidth") or 0) if page_info else 0.0
    ocr_height = float(page_info.get("ocrImageHeight") or 0) if page_info else 0.0
    declared_source_width = float(page_info.get("sourceImageWidth") or 0) if page_info else 0.0
    declared_source_height = float(page_info.get("sourceImageHeight") or 0) if page_info else 0.0
    declared_coordinate_system = str((page_info or {}).get("coordinateSystem") or "")
    source_method_lower = source_method.lower()
    coordinate_system = "pdf_page_points" if page_width and page_height else "unknown"
    source_width = page_width or None
    source_height = page_height or None
    if "ocr" in source_method_lower:
        coordinate_system = str((page_info or {}).get("ocrCoordinateSystem") or "ocr_image_px")
        if ocr_width and ocr_height:
            source_width = ocr_width
            source_height = ocr_height
        elif page_width and page_height and page_width < 1000 and page_height < 1600 and preview_width and preview_height:
            source_width = preview_width
            source_height = preview_height
            coordinate_system = "ocr_preview_px"
        elif page_width and page_height:
            source_width = page_width
            source_height = page_height
        elif preview_width and preview_height:
            source_width = preview_width
            source_height = preview_height
            coordinate_system = "ocr_preview_px"
    elif declared_coordinate_system in {"preview_image_px", "visual_page_preview_px"} and declared_source_width and declared_source_height:
        source_width = declared_source_width
        source_height = declared_source_height
        coordinate_system = declared_coordinate_system
    if bbox and source_width and source_height:
        _, _, x2, y2 = bbox
        if preview_width and preview_height and (x2 > source_width * 1.05 or y2 > source_height * 1.05):
            source_width = preview_width
            source_height = preview_height
            coordinate_system = "ocr_preview_px" if "ocr" in source_method_lower else "preview_image_px"
        elif x2 > source_width * 1.05 or y2 > source_height * 1.05:
            warnings.append("bbox_outside_source_bounds")
    if not source_width or not source_height:
        warnings.append("source_image_dimensions_missing")
    if coordinate_system == "unknown":
        warnings.append("coordinate_system_inferred")
    return coordinate_system, source_width, source_height, warnings

def fde_roi_is_noise_text(text: Any) -> bool:
    return noise_like_text(text)

def fde_build_roi_payload(record: dict[str, Any], page_info: dict[str, Any] | None = None) -> dict[str, Any]:
    raw_roi = record.get("roi") if isinstance(record.get("roi"), dict) else {}
    merged_page_info = dict(page_info or {})
    for key in ("coordinateSystem", "sourceImageWidth", "sourceImageHeight", "previewWidth", "previewHeight", "width", "height"):
        if raw_roi.get(key) not in (None, "", []):
            merged_page_info[key] = raw_roi.get(key)
    raw_boxes = raw_roi.get("boxes") if isinstance(raw_roi.get("boxes"), list) else []
    if not raw_boxes:
        raw_boxes = record.get("boxes") if isinstance(record.get("boxes"), list) else []
    if not raw_boxes and record.get("bbox") is not None:
        raw_boxes = [{"bbox": record.get("bbox"), "text": record.get("text") or record.get("textPreview")}]
    normalized_boxes: list[dict[str, Any]] = []
    union: list[float] | None = None
    source_method = str(record.get("sourceMethod") or raw_roi.get("sourceMethod") or "")
    for index, box in enumerate(raw_boxes, start=1):
        box_payload = box if isinstance(box, dict) else {"bbox": box}
        raw_bbox = box_payload.get("polygon") or box_payload.get("bbox")
        extents = fde_roi_bbox_extents(raw_bbox)
        if not extents:
            continue
        polygon = fde_roi_polygon(raw_bbox, extents)
        union = extents if union is None else [min(union[0], extents[0]), min(union[1], extents[1]), max(union[2], extents[2]), max(union[3], extents[3])]
        normalized_boxes.append(
            {
                "id": str(box_payload.get("id") or box_payload.get("sourceFragmentId") or f"{record.get('id') or record.get('chunkId') or 'roi'}-box-{index}"),
                "pageNo": fde_as_int(box_payload.get("pageNo") or record.get("pageNo")),
                "bbox": [round(value, 4) for value in extents],
                "polygon": polygon,
                "text": fde_chunk_text_preview(box_payload.get("text") or record.get("text") or record.get("textPreview"), 180),
                "confidence": box_payload.get("confidence") or record.get("confidence"),
                "sourceFragmentId": box_payload.get("sourceFragmentId") or box_payload.get("fragmentId"),
                "sourceMethod": str(box_payload.get("sourceMethod") or source_method),
            }
        )
    coordinate_system, source_width, source_height, warnings = fde_page_source_dimensions_for_roi(
        bbox=union,
        source_method=source_method,
        page_info=merged_page_info,
    )
    if not normalized_boxes:
        warnings.append("missing_bbox")
    elif union:
        x1, y1, x2, y2 = union
        if x2 <= x1 or y2 <= y1:
            warnings.append("degenerate_bbox")
        if source_width and source_height and (x1 < 0 or y1 < 0 or x2 > source_width * 1.02 or y2 > source_height * 1.02):
            warnings.append("bbox_outside_source_bounds")
    if fde_roi_is_noise_text(record.get("text") or record.get("textPreview")):
        warnings.append("noise_like_watermark")
    return {
        "schemaVersion": "FdeRoi@1.0.0",
        "pageNo": fde_as_int(record.get("pageNo")),
        "coordinateSystem": coordinate_system,
        "sourceMethod": source_method,
        "sourceImageWidth": source_width,
        "sourceImageHeight": source_height,
        "previewWidth": merged_page_info.get("previewWidth") if merged_page_info else None,
        "previewHeight": merged_page_info.get("previewHeight") if merged_page_info else None,
        "pageWidth": merged_page_info.get("width") if merged_page_info else None,
        "pageHeight": merged_page_info.get("height") if merged_page_info else None,
        "boxes": normalized_boxes,
        "unionBBox": [round(value, 4) for value in union] if union else None,
        "qualityWarnings": sorted(set(warnings)),
    }

def fde_source_pages_by_no(source_preview: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    if not isinstance(source_preview, dict):
        return {}
    pages = source_preview.get("pages")
    if not isinstance(pages, list):
        return {}
    return {fde_as_int(page.get("pageNo")): page for page in pages if isinstance(page, dict) and fde_as_int(page.get("pageNo")) > 0}

def fde_attach_roi_to_chunk_row(row: dict[str, Any], page_info: dict[str, Any] | None = None) -> dict[str, Any]:
    roi = fde_build_roi_payload(row, page_info)
    is_noise = fde_roi_is_noise_text(row.get("text") or row.get("textPreview"))
    if is_noise:
        roi = {
            **roi,
            "boxes": [],
            "unionBBox": None,
            "suppressed": True,
            "suppressedReason": "noise_like_watermark",
            "qualityWarnings": sorted({*(roi.get("qualityWarnings") or []), "noise_like_watermark"}),
        }
    return {
        **row,
        "roi": roi,
        "bbox": None if is_noise else row.get("bbox") if row.get("bbox") is not None else roi.get("unionBBox"),
        "originalBbox": row.get("bbox") if is_noise else row.get("originalBbox"),
        "evidenceUsable": not is_noise,
        "evidenceStatusReason": "noise_like_watermark" if is_noise else row.get("evidenceStatusReason"),
        "roiQualityWarnings": roi.get("qualityWarnings") or [],
    }

def fde_vector_correction_summary(corrections: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for item in corrections:
        status = str(item.get("status") or "pending_review")
        correction_type = str(item.get("correctionType") or "text")
        status_counts[status] = status_counts.get(status, 0) + 1
        type_counts[correction_type] = type_counts.get(correction_type, 0) + 1
    return {
        "total": len(corrections),
        "pending": status_counts.get("pending_review", 0),
        "approved": status_counts.get("approved", 0),
        "applied": status_counts.get("applied", 0),
        "rejected": status_counts.get("rejected", 0),
        "statusCounts": status_counts,
        "typeCounts": type_counts,
    }

def fde_standard_file_page_index_nodes(file: dict[str, Any], page_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    file_id = str(file.get("id") or "")
    source_path = str(file.get("sourceRelativePath") or "")
    file_node_ids = {
        str(node.get("id") or node.get("pageIndexNodeId") or "")
        for node in page_nodes
        if str(node.get("nodeId") or "") == file_id
        or (source_path and str(node.get("sourceRelativePath") or "") == source_path and str(node.get("parentNodeId") or ""))
    }
    if not file_node_ids and source_path:
        file_node_ids = {
            str(node.get("id") or node.get("pageIndexNodeId") or "")
            for node in page_nodes
            if str(node.get("sourceRelativePath") or "") == source_path
        }
    return [
        node
        for node in page_nodes
        if str(node.get("id") or node.get("pageIndexNodeId") or "") in file_node_ids
        or str(node.get("parentNodeId") or "") in file_node_ids
        or (source_path and str(node.get("sourceRelativePath") or "") == source_path)
    ]

def fde_document_page_dimensions(local_path: Path, page_no: int = 1) -> tuple[float | None, float | None, int | None]:
    suffix = local_path.suffix.lower()
    if suffix == ".pdf":
        try:
            import fitz  # type: ignore

            with fitz.open(str(local_path)) as doc:
                if len(doc) < 1:
                    return None, None, 0
                page = doc[max(0, min(page_no - 1, len(doc) - 1))]
                rect = page.rect
                return round(float(rect.width), 2), round(float(rect.height), 2), len(doc)
        except Exception:
            return None, None, None
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        try:
            from PIL import Image

            with Image.open(local_path) as image:
                width, height = image.size
                return float(width), float(height), 1
        except Exception:
            return None, None, None
    return None, None, None

def fde_document_page_preview_dimensions(
    local_path: Path,
    *,
    page_width: float | None = None,
    page_height: float | None = None,
) -> tuple[int | None, int | None]:
    suffix = local_path.suffix.lower()
    if suffix == ".pdf" and page_width and page_height:
        return max(1, math.ceil(float(page_width) * 2)), max(1, math.ceil(float(page_height) * 2))
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        try:
            from PIL import Image

            with Image.open(local_path) as image:
                image.thumbnail((1600, 1600))
                width, height = image.size
                return int(width), int(height)
        except Exception:
            return None, None
    return None, None

def fde_render_standard_page_preview(local_path: Path, page_no: int) -> tuple[bytes, str] | None:
    suffix = local_path.suffix.lower()
    if suffix == ".pdf":
        return (
            fde_render_pdf_page_preview_with_fitz(local_path, page_no)
            or fde_render_pdf_page_preview_with_pdfium(local_path, page_no)
            or fde_render_pdf_page_preview_with_qlmanage(local_path, page_no)
            or fde_render_pdf_page_preview_with_magick(local_path, page_no)
        )
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        return fde_render_image_page_preview(local_path)
    return None

def fde_runtime_env_value(name: str, fallback: str) -> str:
    value = os.getenv(name)
    return value if value not in {None, ""} else fallback

def fde_normalize_eval_value(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("title", "description", "message", "fieldCode", "fieldName"):
            if value.get(key):
                return str(value.get(key)).strip()
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value).strip()

def fde_evaluation_case_overrides(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = body.get("caseResults") or body.get("caseOverrides") or {}
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items() if isinstance(value, dict)}
    if isinstance(raw, list):
        mapped: dict[str, dict[str, Any]] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            case_id = item.get("evaluationCaseId") or item.get("caseId") or item.get("id")
            if case_id:
                mapped[str(case_id)] = item
        return mapped
    return {}

def fde_normalize_clause_ref(value: Any) -> str:
    return str(value or "").strip().lower()

def fde_expected_clause_ids_for_case(case: dict[str, Any]) -> list[str]:
    for key in ("expectedClauseIds", "expectedClauses", "expectedKbRefs"):
        value = case.get(key)
        if not isinstance(value, list):
            continue
        clause_ids: list[str] = []
        for item in value:
            if isinstance(item, dict):
                clause_id = item.get("clauseId") or item.get("id")
            else:
                clause_id = item
            if clause_id:
                clause_ids.append(str(clause_id))
        if clause_ids:
            return clause_ids
    return []

def fde_retrieval_query_for_case(case: dict[str, Any], override: dict[str, Any]) -> str:
    for key in ("retrievalQuery", "question", "query"):
        if override.get(key):
            return str(override.get(key))
        if case.get(key):
            return str(case.get(key))
    expected_findings = case.get("expectedFindings") or []
    if expected_findings:
        return fde_normalize_eval_value(expected_findings[0])
    return "审查依据"

def fde_evaluation_case_summary(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(case_results)
    passed = len([item for item in case_results if item.get("status") == "passed"])
    expected_total = sum(int(item.get("expectedFindingCount") or 0) for item in case_results)
    matched_total = sum(int(item.get("matchedFindingCount") or 0) for item in case_results)
    evidence_required = len([item for item in case_results if int(item.get("expectedEvidenceCount") or 0) > 0])
    evidence_passed = len(
        [
            item
            for item in case_results
            if int(item.get("expectedEvidenceCount") or 0) > 0 and bool(item.get("evidencePassed"))
        ]
    )
    retrieval_required = [
        item for item in case_results if int(item.get("expectedClauseCount") or 0) > 0
    ]
    expected_clause_total = sum(int(item.get("expectedClauseCount") or 0) for item in retrieval_required)
    matched_clause_total = sum(int(item.get("matchedClauseCount") or 0) for item in retrieval_required)
    wrong_reference_count = len([item for item in retrieval_required if item.get("unexpectedTopClauseId")])
    pageindex_triggered = len([item for item in retrieval_required if item.get("selectedRoute") == "pageindex_tree_search"])
    retrieval_passed = len([item for item in retrieval_required if bool(item.get("retrievalPassed"))])
    return {
        "cases": total,
        "passed": passed,
        "failed": total - passed,
        "casePassRate": round(passed / total, 4) if total else 0.0,
        "findingRecall": round(matched_total / expected_total, 4) if expected_total else 1.0,
        "evidenceCoverage": round(evidence_passed / evidence_required, 4) if evidence_required else 1.0,
        "retrievalCases": len(retrieval_required),
        "retrievalPassRate": round(retrieval_passed / len(retrieval_required), 4) if retrieval_required else 1.0,
        "retrievalRecall": round(matched_clause_total / expected_clause_total, 4) if expected_clause_total else 1.0,
        "wrongReferenceRate": round(wrong_reference_count / len(retrieval_required), 4) if retrieval_required else 0.0,
        "pageIndexTriggerRate": round(pageindex_triggered / len(retrieval_required), 4) if retrieval_required else 0.0,
    }

def fde_metric_threshold(metric: str) -> tuple[float, str]:
    if metric == "humanAcceptanceRate":
        return 0.85, ">="
    if metric in {"evidenceHitRate", "casePassRate", "findingRecall", "evidenceCoverage"}:
        return 0.9, ">="
    if metric in {"retrievalRecall", "retrievalPassRate"}:
        return 0.9, ">="
    if metric == "wrongReferenceRate":
        return 0.03, "<="
    if metric == "schemaPassRate":
        return 1.0, ">="
    if metric == "hallucinationRate":
        return 0.01, "<="
    if metric == "highRiskMissRate":
        return 0.005, "<="
    if metric == "failedCaseCount":
        return 0.0, "<="
    if metric == "caseCount":
        return 1.0, ">="
    return 0.0, ">="

def fde_metric_passed(metric: str, value: float) -> bool:
    threshold, operator = fde_metric_threshold(metric)
    return float(value) >= threshold if operator == ">=" else float(value) <= threshold

def fde_ocr_quality_reason_counts(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for result in results:
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        for reason in quality.get("reasons") or []:
            key = str(reason)
            counts[key] = counts.get(key, 0) + 1
    return [{"reason": reason, "count": count} for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]

def fde_table_is_heuristic(table: dict[str, Any]) -> bool:
    source = str(table.get("sourceEngine") or "")
    flags = {str(flag) for flag in table.get("qualityFlags") or []}
    return source.startswith("heuristic_") or "heuristic_table_fallback" in flags

def fde_table_business_rows(table: dict[str, Any]) -> list[Any]:
    rows = table.get("businessRows") or table.get("normalizedRows") or []
    return rows if isinstance(rows, list) else []

def fde_seal_is_fragment_fusion(seal: dict[str, Any]) -> bool:
    source = str(seal.get("sourceEngine") or "")
    flags = {str(flag) for flag in seal.get("qualityFlags") or []}
    return source == "fragment_seal_text_fusion" or "fragment_seal_text" in flags

def fde_seal_is_visual_candidate(seal: dict[str, Any]) -> bool:
    flags = {str(flag) for flag in seal.get("qualityFlags") or []}
    seal_type = str(seal.get("sealType") or "")
    seal_name = str(seal.get("sealName") or "")
    return "visual_candidate_only" in flags or seal_type.startswith("visual_") or seal_name.startswith("视觉")

def fde_seal_text_is_readable(seal: dict[str, Any]) -> bool:
    if fde_seal_is_visual_candidate(seal):
        return False
    seal_name = str(seal.get("sealName") or "").strip()
    if not seal_name:
        return False
    try:
        confidence = float(seal.get("ocrConfidence") or 0)
    except (TypeError, ValueError):
        return False
    return confidence >= 0.65

def fde_ocr_runtime_doctor_report() -> dict[str, Any]:
    client = OcrClient()
    if not client.enabled:
        return {
            "schemaVersion": "aicheck-ocr-runtime-doctor-unavailable-v1",
            "ok": False,
            "summary": {"pass": 0, "warn": 1, "fail": 0, "total": 1},
            "checks": [
                {
                    "name": "ocr.base-url",
                    "status": "warn",
                    "message": "API 服务未配置 OCR 服务地址（AICHECK_OCR_BASE_URL）。",
                    "fix": "在 API 服务环境变量中配置 AICHECK_OCR_BASE_URL，FDE 才能读取 OCR 运行体检结果。",
                }
            ],
        }
    try:
        return client.runtime_doctor()
    except (IntegrationServiceError, RuntimeError) as exc:
        return {
            "schemaVersion": "aicheck-ocr-runtime-doctor-error-v1",
            "ok": False,
            "summary": {"pass": 0, "warn": 0, "fail": 1, "total": 1},
            "checks": [
                {
                    "name": "ocr.runtime-doctor",
                    "status": "fail",
                    "message": f"OCR 运行体检不可用：{exc.__class__.__name__}",
                    "fix": "检查 OCR 服务网络、/internal/ocr/doctor 运行体检接口，以及 AICHECK_OCR_BASE_URL 配置。",
                }
            ],
        }

def fde_ocr_100_handoff_stale_reasons(
    manifest_summary: dict[str, Any],
    current_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    if not current_summary:
        return []
    keys = [
        "status",
        "score",
        "readyForEval",
        "requiredReadyForEval",
        "collectionMissingCases",
        "placeholderSampleSlots",
        "annotationTasks",
        "remainingHumanLabels",
        "newLocalCandidates",
        "duplicateLocalCandidates",
        "actions",
    ]
    reasons: list[dict[str, Any]] = []
    for key in keys:
        manifest_value = fde_ocr_100_summary_value(manifest_summary.get(key))
        current_value = fde_ocr_100_summary_value(current_summary.get(key))
        if manifest_value != current_value:
            reasons.append(
                {
                    "field": key,
                    "handoff": manifest_summary.get(key),
                    "current": current_summary.get(key),
                }
            )
    manifest_lanes = (
        manifest_summary.get("laneCounts")
        if isinstance(manifest_summary.get("laneCounts"), dict)
        else {}
    )
    current_lanes = (
        current_summary.get("laneCounts")
        if isinstance(current_summary.get("laneCounts"), dict)
        else {}
    )
    if manifest_lanes != current_lanes:
        reasons.append(
            {"field": "laneCounts", "handoff": manifest_lanes, "current": current_lanes}
        )
    return reasons

def fde_ocr_100_summary_value(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value

def fde_ocr_100_handoff_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "text/csv; charset=utf-8"
    if suffix == ".md":
        return "text/markdown; charset=utf-8"
    if suffix == ".json":
        return "application/json"
    return "application/octet-stream"

def fde_read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}

def fde_ocr_sample_summaries(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for result in results[:10]:
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        tables = [item for item in result.get("tables") or [] if isinstance(item, dict)]
        seals = [item for item in result.get("seals") or [] if isinstance(item, dict)]
        summaries.append(
            {
                "parseResultId": result.get("parseResultId") or result.get("id"),
                "profileId": result.get("profileId"),
                "gatePassed": result.get("status") == "success" and quality.get("status") == "auto_usable",
                "qualityStatus": quality.get("status"),
                "fields": len([item for item in result.get("fields") or [] if isinstance(item, dict)]),
                "formalTables": len([item for item in tables if not fde_table_is_heuristic(item)]),
                "businessRows": sum(len(fde_table_business_rows(item)) for item in tables),
                "readableSeals": len([item for item in seals if str(item.get("sealName") or "").strip()]),
                "fragmentSeals": len([item for item in seals if fde_seal_is_fragment_fusion(item)]),
                "missingExpectedSealTypeCount": len(quality.get("missingExpectedSealTypes") or []),
                "evidenceCompleteness": quality.get("evidenceCompleteness"),
            }
        )
    return summaries

def fde_expected_value_present(value: Any) -> bool:
    return value is not None and value != "" and value != []

def fde_capability_test_file_preview_type(file_name: str, content_type: str | None = None) -> str:
    suffix = Path(str(file_name or "")).suffix.lower().lstrip(".")
    content = str(content_type or "").lower()
    if suffix == "pdf" or "pdf" in content:
        return "pdf"
    if suffix in {"png", "jpg", "jpeg", "webp", "bmp", "heic", "heif"} or content.startswith("image/"):
        return "image"
    if suffix in {"doc", "docx", "xls", "xlsx"}:
        return "office"
    return "unsupported"

def fde_capability_test_safe_file_name(file_name: str | None) -> str:
    safe = re.sub(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+", "_", Path(str(file_name or "ocr-test-file")).name)
    return safe[:120] or "ocr-test-file"

def fde_capability_test_upload_root() -> Path:
    return Path(
        os.getenv(
            "AICHECK_FDE_OCR_UPLOAD_DIR",
            "/tmp/aicheck-fde-ocr-uploads",
        )
    ).expanduser()

def fde_capability_test_local_path(path_value: str | None) -> Path | None:
    raw = str(path_value or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        return None
    try:
        root = fde_capability_test_upload_root().resolve()
        resolved = path.expanduser().resolve()
    except Exception:
        return None
    if resolved == root or root in resolved.parents:
        return resolved
    return None

def fde_render_image_page_preview(local_path: Path) -> tuple[bytes, str] | None:
    try:
        from PIL import Image

        with Image.open(local_path) as image:
            image.thumbnail((1600, 1600))
            output = io.BytesIO()
            image.convert("RGB").save(output, format="PNG")
            return output.getvalue(), "image/png"
    except Exception:
        return None

def fde_render_heic_page_preview(local_path: Path) -> tuple[bytes, str] | None:
    pillow_preview = fde_render_image_page_preview(local_path)
    if pillow_preview:
        return pillow_preview
    if not shutil.which("sips"):
        return None
    with tempfile.TemporaryDirectory(prefix="aicheck-fde-heic-preview-") as temp_dir:
        target = Path(temp_dir) / "page.png"
        completed = subprocess.run(
            ["sips", "-Z", "1600", "-s", "format", "png", str(local_path), "--out", str(target)],
            check=False,
            capture_output=True,
            timeout=30,
        )
        if completed.returncode != 0 or not target.is_file():
            return None
        return fde_render_image_page_preview(target) or (target.read_bytes(), "image/png")

def fde_render_pdf_page_preview_with_fitz(local_path: Path, page_no: int) -> tuple[bytes, str] | None:
    try:
        import fitz  # type: ignore

        with fitz.open(str(local_path)) as doc:
            if len(doc) < 1:
                return None
            page = doc[max(0, min(page_no - 1, len(doc) - 1))]
            matrix = fitz.Matrix(2, 2)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            return pixmap.tobytes("png"), "image/png"
    except Exception:
        return None

def fde_render_pdf_page_preview_with_pdfium(local_path: Path, page_no: int) -> tuple[bytes, str] | None:
    try:
        import pypdfium2 as pdfium  # type: ignore

        pdf = pdfium.PdfDocument(str(local_path))
        try:
            if len(pdf) < 1:
                return None
            page = pdf[max(0, min(page_no - 1, len(pdf) - 1))]
            bitmap = page.render(scale=2)
            pil_image = bitmap.to_pil()
            output = io.BytesIO()
            pil_image.convert("RGB").save(output, format="PNG")
            return output.getvalue(), "image/png"
        finally:
            pdf.close()
    except Exception:
        return None

def fde_render_pdf_page_preview_with_qlmanage(local_path: Path, page_no: int) -> tuple[bytes, str] | None:
    if page_no != 1 or not shutil.which("qlmanage"):
        return None
    with tempfile.TemporaryDirectory(prefix="aicheck-fde-pdf-preview-") as temp_dir:
        completed = subprocess.run(
            ["qlmanage", "-t", "-s", "1600", "-o", temp_dir, str(local_path)],
            check=False,
            capture_output=True,
            timeout=30,
        )
        if completed.returncode != 0:
            return None
        candidates = sorted(
            Path(temp_dir).glob("*.png"),
            key=lambda item: item.stat().st_size,
            reverse=True,
        )
        if not candidates:
            return None
        return candidates[0].read_bytes(), "image/png"

def fde_render_pdf_page_preview_with_magick(local_path: Path, page_no: int) -> tuple[bytes, str] | None:
    magick = shutil.which("magick") or shutil.which("convert")
    if not magick:
        return None
    with tempfile.TemporaryDirectory(prefix="aicheck-fde-pdf-preview-") as temp_dir:
        target = Path(temp_dir) / "page.png"
        source = f"{local_path}[{max(0, page_no - 1)}]"
        command = [magick, source, "-thumbnail", "1600x1600", str(target)]
        completed = subprocess.run(command, check=False, capture_output=True, timeout=30)
        if completed.returncode != 0 or not target.is_file():
            return None
        return target.read_bytes(), "image/png"

def fde_capability_test_direct_upload_url(session_id: str) -> str:
    return f"/api/fde/capability-tests/ocr/upload-session/{session_id}/file"

def fde_capability_test_storage_url(storage_key: str) -> str:
    raw = str(storage_key or "").strip()
    if fde_capability_test_local_path(raw):
        return raw
    if raw.startswith(("minio://", "s3://", "mock://", "http://", "https://", "file://")):
        return raw
    return f"minio://ocr-artifacts/{raw}"

def fde_capability_test_upload_ready(upload_session: dict[str, Any]) -> bool:
    status = str(upload_session.get("status") or "")
    if status in {"uploaded", "used"}:
        return True
    upload_url = str(upload_session.get("uploadUrl") or "")
    storage_url = str(upload_session.get("storageUrl") or upload_session.get("storageKey") or "")
    return bool(upload_url and not upload_url.startswith("mock://") and storage_url)

def fde_capability_test_result_summary(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {
            "pages": 0,
            "fields": 0,
            "tables": 0,
            "seals": 0,
            "fragments": 0,
            "diagnostics": 0,
            "qualityStatus": "unknown",
            "overallConfidence": 0,
            "engineDurationMs": 0,
        }
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    engine_runs = [item for item in result.get("engineRuns") or [] if isinstance(item, dict)]
    duration = sum(int(item.get("durationMs") or item.get("latencyMs") or 0) for item in engine_runs)
    return {
        "pages": len([item for item in result.get("pages") or [] if isinstance(item, dict)]),
        "fields": len([item for item in result.get("fields") or [] if isinstance(item, dict)]),
        "tables": len([item for item in result.get("tables") or [] if isinstance(item, dict)]),
        "seals": len([item for item in result.get("seals") or [] if isinstance(item, dict)]),
        "fragments": len([item for item in result.get("fragments") or [] if isinstance(item, dict)]),
        "diagnostics": len(result.get("diagnostics") or []),
        "qualityStatus": quality.get("status") or "unknown",
        "overallConfidence": quality.get("overallConfidence") or quality.get("confidence") or 0,
        "engineDurationMs": duration,
    }

def fde_capability_test_profile_document_type(file_name: str, body: dict[str, Any]) -> tuple[str, str]:
    profile_id = str(body.get("profileId") or "").strip()
    document_type = str(body.get("documentType") or "").strip()
    if profile_id in {"all", "auto"}:
        profile_id = ""
    if document_type in {"all", "auto"}:
        document_type = ""
    if not profile_id:
        profile_id = "generic_document_v1"
    if not document_type:
        document_type = {
            "generic_document_v1": "generic_document",
            "piping_characteristic_list_v1": "engineering_table_photo",
            "quality_certificate_v1": "quality_certificate",
            "acceptance_witness_record_v1": "acceptance_witness_record",
            "sampling_witness_record_v1": "sampling_witness_record",
            "material_retest_report_v1": "material_retest_report",
            "material_ndt_report_v1": "material_ndt_report",
            "ndt_rt_report_v1": "ndt_report",
        }.get(profile_id, "engineering_document")
    return profile_id, document_type

def fde_capability_test_bool(body: dict[str, Any], key: str, default: bool) -> bool:
    return parse_bool(body.get(key), default) is True

def fde_capability_test_int(body: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(body.get(key) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))

def fde_capability_test_timeout_seconds(options: dict[str, Any]) -> int:
    max_pages = fde_capability_test_int(options, "maxPages", 1, 1, 10)
    enabled_heavy_steps = sum(
        1
        for key in ("enableTables", "enableSeals", "enableFallback")
        if parse_bool(options.get(key), False) is True
    )
    return max(300, min(900, 180 + max_pages * 90 + enabled_heavy_steps * 180))

def fde_ocr_annotation_task_identity(task: dict[str, Any]) -> str:
    return str(task.get("taskId") or task.get("caseId") or "").strip()

def fde_ocr_annotation_scenario(result: dict[str, Any]) -> str:
    profile = str(result.get("profileId") or "")
    document_type = str(result.get("documentType") or "")
    if "piping" in profile or "table" in document_type:
        return "piping_table_profile"
    if "seal" in profile:
        return "seal_text_profile"
    if "quality_certificate" in profile or "quality_certificate" in document_type:
        return "quality_certificate_profile"
    return "evidence_profile"

def fde_ocr_annotation_result_page_dimensions(result: dict[str, Any] | None) -> dict[str, list[int]]:
    dimensions: dict[str, list[int]] = {}
    if not isinstance(result, dict):
        return dimensions
    for page_item in result.get("pages") or []:
        if not isinstance(page_item, dict):
            continue
        page_no = str(page_item.get("pageNo") or page_item.get("page") or len(dimensions) + 1)
        try:
            width = int(float(page_item.get("width") or page_item.get("imageWidth") or 0))
            height = int(float(page_item.get("height") or page_item.get("imageHeight") or 0))
        except (TypeError, ValueError):
            width = 0
            height = 0
        if width > 0 and height > 0:
            dimensions[page_no] = [width, height]
    return dimensions

def fde_ocr_annotation_expected_counts(expected: dict[str, Any]) -> dict[str, int]:
    return {
        "fields": len([item for item in expected.get("fields") or [] if isinstance(item, dict)]),
        "tables": len([item for item in expected.get("tables") or [] if isinstance(item, dict)]),
        "seals": len([item for item in expected.get("seals") or [] if isinstance(item, dict)]),
    }

FDE_OCR_ANNOTATION_PREVIEW_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".heic", ".heif", ".pdf")
