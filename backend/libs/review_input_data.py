"""Shared review OCR selection and correction application, independent of tool registries."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_document_scope import validate_document_sources


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
    return apply_field_corrections_to_parse_results(state, results, context=context)


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
    for item in corrections:
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
            field["originalValue"] = field.get("value") if "value" in field else field.get("fieldValue")
            for key in ("value", "fieldValue", "text"):
                if key in field:
                    field[key] = correction.get("correctedValue")
            field["humanCorrected"] = True
            field["correctionId"] = correction.get("id")
        clone["humanCorrectedFieldCount"] = sum(
            1 for f in clone.get("fields") or [] if isinstance(f, dict) and f.get("humanCorrected")
        )
        patched.append(clone)
    return patched


