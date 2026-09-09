"""Resolve explicit, run-only input versions without changing persistent document bindings."""
from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

from apps.api.document_access_policy import actor_visible_evidence_repository
from apps.api.review_condition_selection import prepare_condition_selection
from apps.api.review_page_count import fixed_version_page_count
from libs.audit_runtime import audit_runtime_public_config
from libs.material_targeting import build_node_evidence_readiness
from libs.review_page_scope import located_record_in_range, normalize_page_ranges


class ReviewInputSelectionError(ValueError):
    pass


def selected_input_evidence_links(links, versions, ranges):
    return [link for link in links if link.get("documentVersionId") in versions
            and (link["documentVersionId"] not in ranges
                 or located_record_in_range(link, ranges[link["documentVersionId"]]))]


def resolve_review_input_selection(services, request, project_id: str, node_id: int,
                                   body: dict[str, Any]) -> tuple[list[str], dict[str, Any]] | None:
    if "inputDocumentPageRanges" in body and os.getenv("AICHECK_REVIEW_PAGE_RANGES_ENABLED", "").lower() not in {"1", "true", "yes"}:
        # Never accept a range while downstream readers could still consume the whole file.
        raise ReviewInputSelectionError("页码范围尚未完成全链路验收，暂不能按指定页码发起审查。")
    if "inputDocumentVersionIds" not in body:
        if "conditionObjectMapping" in body:
            raise ReviewInputSelectionError("对象选择必须明确指定本次文件版本。")
        if "inputDocumentPageRanges" in body:
            raise ReviewInputSelectionError("指定页码时必须明确选择文件版本。")
        return None
    if os.getenv("AICHECK_WORKSTATIONS_ENABLED", "").lower() not in {"1", "true", "yes"}:
        raise ReviewInputSelectionError("本环境尚未开放本次审查文件选择。")
    versions = body["inputDocumentVersionIds"]
    if (not isinstance(versions, list) or not versions or len(versions) > 500
            or any(not isinstance(value, str) or not value.strip() for value in versions)
            or len(set(versions)) != len(versions)):
        raise ReviewInputSelectionError("请选择 1–500 个不同的文件版本。")
    detached = actor_visible_evidence_repository(services, request, project_id)
    visible = {str(row.get("id") or ""): row for row in detached.state.get("versions", [])
               if services.tenant_id_for_record(row) == services.request_tenant_id(request)}
    if set(versions) - visible.keys():
        raise ReviewInputSelectionError("所选文件版本不存在或不在当前账号可访问范围，请刷新后重新选择。")
    chosen = set(versions)
    documents = {str(row.get("id") or ""): row for row in detached.state.get("documents", [])}
    if any(not services.document_body_uploaded(documents.get(str(visible[value].get("documentId") or "")), visible[value])
           for value in versions):
        raise ReviewInputSelectionError("所选文件版本尚未上传完整，请完成上传后重新选择。")
    ranges = {}
    page_counts = {}
    if "inputDocumentPageRanges" in body:
        try:
            ranges = normalize_page_ranges(body["inputDocumentPageRanges"], versions)
        except ValueError as exc:
            raise ReviewInputSelectionError("页码范围无效，请填写所选版本的起止页码（从1开始）。") from exc
        runtime = audit_runtime_public_config(mode=str(body.get("auditInputMode") or body.get("auditRuntimeMode") or "") or None)
        if ranges and not runtime["useOcrEvidence"]:
            raise ReviewInputSelectionError("指定页码需要使用 OCR + LLM 模式，当前模式不读取页内证据。")
        for version_id, bounds in ranges.items():
            try:
                count = fixed_version_page_count(services, visible[version_id])
            except Exception as exc:
                raise ReviewInputSelectionError("无法核验所选版本的PDF页数，请检查原文是否可用、完整且未加密。") from exc
            if bounds["end"] > count:
                raise ReviewInputSelectionError(f"所选页码超出PDF实际页数（共{count}页），请重新选择。")
            page_counts[version_id] = count

    def selected(row):
        version = row.get("documentVersionId")
        if version:
            return str(version) in chosen
        document = documents.get(str(row.get("documentId") or "")) or {}
        return str(document.get("currentVersionId") or "") in chosen

    for key in ("bindings", "node_evidence_links"):
        detached.state[key] = [row for row in detached.state.get(key, []) if selected(row)]
    if ranges:
        detached.state["node_evidence_links"] = [row for row in detached.state.get("node_evidence_links", [])
            if row.get("documentVersionId") not in ranges
            or located_record_in_range(row, ranges[row["documentVersionId"]])]
    readiness = deepcopy(build_node_evidence_readiness(detached, project_id, node_id))
    # Supplemental files need not already be mounted or matched to a requirement.
    # Formal readiness still comes exclusively from existing confirmed evidence.
    readiness["readyForGapPrecheck"] = True
    ordered = list(versions) if "conditionObjectMapping" in body else sorted(chosen)
    readiness["inputSelection"] = {"mode": "explicit", "documentVersionIds": ordered, "scope": "run_only"}
    if "inputDocumentPageRanges" in body:
        readiness["inputSelection"].update(documentPageRanges=ranges, originalPageCounts=page_counts)
    if "conditionObjectMapping" in body:
        try:
            runtime = audit_runtime_public_config(mode=str(body.get("auditInputMode") or body.get("auditRuntimeMode") or "") or None)
            if not runtime["useOcrEvidence"]:
                raise ValueError("对象选择需要使用 OCR 资料模式。")
            readiness["inputSelection"]["conditionObjectMapping"] = prepare_condition_selection(
                services, request, project_id, node_id, body, ordered, ranges)
        except (TypeError, ValueError) as exc:
            raise ReviewInputSelectionError(str(exc)) from exc
    return ordered, readiness
