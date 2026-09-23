"""Prepare a scoped, self-consistent Jev state without making a network request.

This module intentionally fails closed. A model must never receive an OCR result
merely because its version ID happens to appear in a run: the version must also
belong to the run's project. Long documents are reported, never truncated.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from libs.review_input_data import selected_parse_results

MAX_STATE_CHARS = 40_000
_SCOPE_CODE = re.compile(r"(?:^|:)scope_covers_(GC\d|GCD)$", re.IGNORECASE)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _check_identity(check: dict[str, Any]) -> tuple[str, str] | None:
    code = str(check.get("code") or "")
    actual = check.get("actual")
    expected = check.get("expected")
    scope = _SCOPE_CODE.search(code)
    if scope:
        return ("scope_covers:" + scope.group(1).upper(), _json(actual))
    if code.endswith(":scope_covers_required") or code == "scope_covers_required":
        if isinstance(expected, list) and len(expected) == 1:
            return ("scope_covers:" + str(expected[0]).upper(), _json(actual))
        return None
    if code and actual is not None and expected is not None:
        return (code, _json([actual, expected]))
    return None


def consistent_rule_checks(rule_results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Exclude *both* sides of a contradictory check from model context.

    The returned rows contain only the check and its atomic ID; raw tool output
    and free-text findings are not copied into Jev's allegedly verified block.
    """
    rows: list[dict[str, Any]] = []
    by_identity: dict[tuple[str, str], list[int]] = defaultdict(list)
    for rule in rule_results:
        for atomic in rule.get("atomicCheckResults") or []:
            for tool in atomic.get("toolResults") or []:
                if tool.get("status") != "succeeded" or tool.get("result") not in {"passed", "failed"}:
                    continue
                for check in tool.get("checks") or []:
                    if not isinstance(check, dict) or not isinstance(check.get("passed"), bool):
                        continue
                    identity = _check_identity(check)
                    if identity is None:
                        continue
                    row = {"atomicCheckId": atomic.get("atomicCheckId"), "code": check.get("code"),
                           "passed": check["passed"], "actual": check.get("actual"),
                           "expected": check.get("expected")}
                    by_identity[identity].append(len(rows))
                    rows.append(row)
    conflict_indexes: set[int] = set()
    conflicts: list[dict[str, Any]] = []
    for identity, indexes in by_identity.items():
        if len({rows[index]["passed"] for index in indexes}) > 1:
            conflict_indexes.update(indexes)
            conflicts.append({"factKey": identity[0], "atomicCheckIds":
                              sorted({str(rows[index]["atomicCheckId"]) for index in indexes})})
    return [row for index, row in enumerate(rows) if index not in conflict_indexes], conflicts


def _document_text(parse: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("layoutBlocks", "fields", "fragments", "tables"):
        for item_index, item in enumerate(parse.get(key) or [], 1):
            if not isinstance(item, dict):
                continue
            page = item.get("pageNo") or item.get("page") or "?"
            value = (item.get("text") or item.get("fullText") or item.get("fieldValue")
                     or item.get("value") or item.get("html") or item.get("markdown"))
            if value:
                parts.append(f"[第 {page} 页] {value}")
            if key == "tables":
                parts.append(f"[表格 {item_index}，第 {page} 页]")
                for row_index, row in enumerate(item.get("normalizedRows") or item.get("records") or [], 1):
                    if isinstance(row, dict):
                        parts.append(f"[表格 {item_index} 第 {row_index} 行] {_json(row)}")
    return "\n".join(parts)


def latest_selected_parses(
    state: dict[str, Any], review_run: dict[str, Any], requested: set[str],
) -> dict[str, dict[str, Any]]:
    """Use one OCR attempt per frozen version, including a newer failed attempt."""
    latest: dict[str, dict[str, Any]] = {}
    for parse in selected_parse_results(state, {}, context={"reviewRun": review_run}):
        version_id = str(parse.get("documentVersionId") or "")
        if version_id not in requested:
            continue
        previous = latest.get(version_id)
        stamp = str(parse.get("finishedAt") or parse.get("updatedAt") or parse.get("createdAt") or "")
        order = (stamp, str(parse.get("id") or parse.get("parseResultId") or ""))
        if previous is None:
            latest[version_id] = parse
            continue
        previous_stamp = str(previous.get("finishedAt") or previous.get("updatedAt")
                             or previous.get("createdAt") or "")
        previous_order = (previous_stamp, str(previous.get("id") or previous.get("parseResultId") or ""))
        if order > previous_order:
            latest[version_id] = parse
    return latest


def scoped_document_states(
    state: dict[str, Any], review_run: dict[str, Any], rule_results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Return full-document states, excluded conflicts, and overlong version IDs.

    A caller may batch whole documents while under MAX_STATE_CHARS. It must not
    split a single oversized document into snippets or silently omit it.
    """
    project_id = str(review_run.get("projectId") or "")
    tenant_id = str(review_run.get("tenantId") or "")
    documents = {str(row.get("id")): row for row in state.get("documents") or []
                 if isinstance(row, dict) and str(row.get("projectId") or "") == project_id
                 and (not tenant_id or not row.get("tenantId") or str(row["tenantId"]) == tenant_id)}
    versions = {str(row.get("id") or row.get("documentVersionId")): row
                for row in [*(state.get("versions") or []), *(state.get("document_versions") or [])]
                if isinstance(row, dict)}
    requested = {str(item) for item in review_run.get("inputDocumentVersionIds") or []}
    for version_id in requested:
        version = versions.get(version_id)
        if version is None or str(version.get("documentId") or "") not in documents:
            raise ValueError("jev_document_outside_project")
    checks, conflicts = consistent_rule_checks(rule_results)
    parses = latest_selected_parses(state, review_run, requested)
    result: list[dict[str, Any]] = []
    overlong: list[str] = []
    for version_id in sorted(requested):
        document = documents[str(versions[version_id]["documentId"])]
        parse = parses.get(version_id) or {}
        ocr_status = str(parse.get("status") or "").lower()
        ocr_not_ready = bool(parse) and ocr_status not in {
            "", "success", "succeeded", "completed", "已识别", "人工修正",
        }
        content = "" if ocr_not_ready else _document_text(parse)
        full_state = (f"工程：{project_id}；节点：{review_run.get('nodeId')}\n"
                      f"文件：{document.get('fileName') or document.get('name') or version_id}；版本：{version_id}\n"
                      f"{content or '（本文件没有可用 OCR 原文）'}\n"
                      f"已核实且无冲突的规则检查：{_json(checks)}")
        if len(full_state) > MAX_STATE_CHARS:
            overlong.append(version_id)
            continue
        result.append({"documentVersionId": version_id, "state": full_state,
                       "hasOcrText": bool(content), "ocrNotReady": ocr_not_ready})
    return result, conflicts, overlong
