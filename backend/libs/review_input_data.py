"""Shared review OCR selection and correction application, independent of tool registries."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_document_scope import validate_document_sources
from libs.review_page_scope import (
    normalize_page_ranges,
    page_record_in_range,
    restrict_parse_result,
)


def selected_parse_results(
    state: dict[str, Any],
    arguments: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    context = context or {}
    requested = {
        str(item)
        for item in arguments.get("documentVersionIds")
        or context.get("documentVersionIds")
        or context.get("inputDocumentVersionIds")
        or []
        if item
    }
    review_run = context.get("reviewRun")
    if review_run is not None:
        validate_document_sources(review_run, state)
        allowed = {str(item) for item in review_run.get("inputDocumentVersionIds") or [] if item}
        requested = requested & allowed if requested else allowed
    results = [item for item in state.get("ocr_parse_results", []) if isinstance(item, dict)]
    if requested or review_run is not None:
        results = [item for item in results if str(item.get("documentVersionId") or "") in requested]
    results = apply_field_corrections_to_parse_results(state, results, context=context)
    if review_run is not None:
        ranges = normalize_page_ranges(review_run.get("inputDocumentPageRanges", {}),
                                       review_run.get("inputDocumentVersionIds") or [])
        results = [restrict_parse_result(row, ranges[row["documentVersionId"]])
                   if row.get("documentVersionId") in ranges else row for row in results]
    return results


def latest_selected_parses(
    state: dict[str, Any], review_run: dict[str, Any], requested: set[str],
) -> dict[str, dict[str, Any]]:
    """Select the latest OCR attempt for each frozen version after scope/correction checks."""
    return _latest_by_version(
        selected_parse_results(state, {}, context={"reviewRun": review_run}), requested,
    )


def _latest_by_version(
    results: list[dict[str, Any]], requested: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    ambiguous: set[str] = set()
    for parse in results:
        version_id = str(parse.get("documentVersionId") or "")
        if not version_id or (requested is not None and version_id not in requested):
            continue
        if parse.get("pipelineStage"):
            # 流水线中间阶段（结构/印章/融合）只是候选；权威结果由 finalize 另存且不带该标记。
            continue
        previous = latest.get(version_id)
        stamp = str(parse.get("finishedAt") or parse.get("updatedAt") or parse.get("createdAt") or "")
        if previous is None:
            latest[version_id] = parse
            continue
        previous_stamp = str(previous.get("finishedAt") or previous.get("updatedAt")
                             or previous.get("createdAt") or "")
        if stamp == previous_stamp:
            # A record ID is not an OCR attempt clock. Ties cannot establish current evidence.
            ambiguous.add(version_id)
        elif stamp > previous_stamp:
            latest[version_id] = parse
            ambiguous.discard(version_id)
    return {version_id: parse for version_id, parse in latest.items() if version_id not in ambiguous}


def ocr_parse_usable(parse: dict[str, Any]) -> bool:
    """A failed or pending latest attempt must not expose an older OCR as current evidence."""
    status = str(parse.get("status") or "success").lower()
    outcome = str(parse.get("outcomeStatus") or "").lower()
    quality = parse.get("quality") if isinstance(parse.get("quality"), dict) else {}
    quality_status = str(quality.get("status") or "").lower()
    # A partial OCR can still contain traceable facts; each rule checks its own page gap.
    return (status in {"success", "succeeded", "completed", "已识别", "人工修正"}
            and outcome != "failed" and quality_status != "failed")


def current_selected_parse_results(
    state: dict[str, Any], arguments: dict[str, Any], *,
    context: dict[str, Any] | None = None, include_unusable: bool = False,
) -> list[dict[str, Any]]:
    """Current OCR for each selected version, retaining the existing scope and page rules."""
    latest = _latest_by_version(selected_parse_results(state, arguments, context=context))
    return [parse for parse in latest.values() if include_unusable or ocr_parse_usable(parse)]


def latest_usable_selected_parses(
    state: dict[str, Any], review_run: dict[str, Any], requested: set[str],
) -> list[dict[str, Any]]:
    """Never fall back to an older successful OCR after the latest attempt failed."""
    return [
        parse for parse in latest_selected_parses(state, review_run, requested).values()
        if ocr_parse_usable(parse)
    ]


def apply_field_corrections_to_parse_results(
    state: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """把监检人员对 OCR 抽取字段的修正覆盖到解析结果上。

    修正记录在 `fact_corrections` 中以 fieldId 为键；这里按 fieldName 匹配解析结果里的
    字段，使所有读 OCR 的确定性工具都看到修正后的值。仅对本项目本节点生效，
    不跨节点传播（业务口径：节点独立）。返回副本，不改动持久化状态。
    """
    review_run = (context or {}).get("reviewRun") or {}
    project_id = str(review_run.get("projectId") or "")
    node_id = review_run.get("nodeId")
    if not project_id or node_id is None:
        return results
    corrections = [
        item
        for item in state.get("fact_corrections", []) or []
        if item.get("status") == "active"
        and item.get("fieldId")
        and item.get("projectId") == project_id
        and int(item.get("nodeId") or 0) == int(node_id)
    ]
    if not corrections:
        return results

    by_version: dict[str, dict[str, Any]] = {}
    page_ranges = normalize_page_ranges(review_run.get("inputDocumentPageRanges", {}),
                                       review_run.get("inputDocumentVersionIds") or [])
    for item in corrections:
        bounds = page_ranges.get(str(item.get("documentVersionId") or ""))
        if bounds is not None and not page_record_in_range(item, bounds):
            continue
        by_version.setdefault(str(item.get("documentVersionId") or ""), {})[
            str(item.get("fieldName") or "")
        ] = item

    patched: list[dict[str, Any]] = []
    for result in results:
        overrides = by_version.get(str(result.get("documentVersionId") or "")) or {}
        if not overrides:
            patched.append(result)
            continue
        clone = deepcopy(result)
        for field in clone.get("fields") or []:
            if not isinstance(field, dict):
                continue
            correction = overrides.get(str(field.get("fieldName") or field.get("name") or ""))
            if not correction:
                continue
            if str(result.get("documentVersionId") or "") in page_ranges and field.get("pageNo") != correction.get("pageNo"):
                continue
            field["originalValue"] = field.get("value") if "value" in field else field.get("fieldValue")
            for key in ("value", "fieldValue", "text"):
                if key in field:
                    field[key] = correction.get("correctedValue")
            field["humanCorrected"] = True
            field["correctionId"] = correction.get("id")
            # 人核过的值配得上 1.0（与公示平台登记记录、已核验引用同一口径）：
            # 否则 MinerU 通道的字段改完仍是 0.0/置信度未知，grounding 永远只能「需人工判断」，
            # 人核一百次系统也不记得。
            field["confidence"] = 1.0
            field["confidenceUnavailable"] = False
        clone["humanCorrectedFieldCount"] = sum(
            1 for f in clone.get("fields") or [] if isinstance(f, dict) and f.get("humanCorrected")
        )
        patched.append(clone)
    return patched
