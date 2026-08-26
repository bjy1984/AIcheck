from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from libs.contracts.responses import server_time
from libs.model_usage import estimate_messages_tokens
from libs.review_evidence import active_node_document_versions

PROMPT_VERSION = "project-monolithic-analysis@1.0.0"
DEFAULT_BUSINESS_PACK_ID = "engineering_inspection_v1"
DEFAULT_MODEL_ALIAS = "project-review-large"

_HTML_TAG_PATTERN = re.compile(r"<[^>]*>")
_HTML_IMAGE_PATTERN = re.compile(r"<img\b[^>]*?/?>", re.IGNORECASE)


SYSTEM_PROMPT = """你是压力管道安装工程监督检验 AI 审查代理。

你将收到一个工程中所有有有效挂接资料业务节点的规则、资料要求、node.fileRefs，以及项目级唯一 project.fileCorpus。请在同一次模型调用中完成全部节点分析。

强制要求：
1. Resolve every node.fileRefs[].fileId against project.fileCorpus before reviewing that node.
2. Use only fileCorpus entries referenced by the current node.fileRefs.
3. criteria、checkMethod 和 configuredRequirements 是审查依据，不是已被证据证明的事实。
4. quotedText 必须逐字存在于对应 fullOcrText；不连续原文必须拆成多条 evidenceRef。
5. ruleRef 只能逐字引用当前节点 criteria 或 checkMethod。
6. 没有直接证据时使用 insufficient_evidence、human_confirm 和空 evidenceRefs。
7. 所有 Finding 强制 requiresHumanConfirmation=true，不得改变正式业务状态。
8. 只输出符合 outputSchema 的一个合法 JSON 对象。
"""


OUTPUT_SCHEMA = {
    "schemaVersion": "AIAllReviewResult@2.0.0",
    "projectId": "string",
    "projectCode": "string",
    "projectName": "string",
    "nodeReviews": [
        {
            "nodeId": "number",
            "nodeName": "string",
            "reviewResult": "supported|partially_supported|insufficient_evidence|conflict|mismatch",
            "supportSummary": "string",
            "missingEvidence": ["string"],
            "conflicts": ["string"],
            "risks": ["string"],
            "recommendations": ["string"],
            "findings": [
                {
                    "findingType": "string",
                    "severity": "low|medium|high|critical",
                    "title": "string",
                    "description": "string",
                    "confidence": "0..1",
                    "suggestedAction": "human_confirm|request_correction",
                    "evidenceRefs": [
                        {
                            "fileId": "string",
                            "documentVersionId": "string",
                            "fileName": "string",
                            "pageNo": "number|null",
                            "quotedText": "verbatim string",
                        }
                    ],
                    "ruleRefs": [
                        {"source": "criteria|checkMethod", "text": "verbatim string"}
                    ],
                    "kbRefs": [],
                    "groundingStatus": "grounded|insufficient_evidence",
                    "unsupportedClaims": ["string"],
                    "requiresHumanConfirmation": True,
                }
            ],
        }
    ],
    "projectSummary": {
        "supportedNodeCount": "number",
        "partialNodeCount": "number",
        "insufficientNodeCount": "number",
        "conflictNodeCount": "number",
        "mismatchNodeCount": "number",
        "humanReviewNodeCount": "number",
        "priorityRisks": ["string"],
        "priorityManualActions": ["string"],
    },
    "disclaimer": "以上内容仅作为监检审查提示，不替代最终人工结论。",
}


class ProjectAnalysisContextLimitError(RuntimeError):
    def __init__(
        self,
        *,
        estimated_tokens: int,
        max_context_tokens: int,
        reserved_output_tokens: int,
    ) -> None:
        self.estimated_tokens = int(estimated_tokens)
        self.max_context_tokens = int(max_context_tokens)
        self.reserved_output_tokens = int(reserved_output_tokens)
        self.available_input_tokens = max(
            0, self.max_context_tokens - self.reserved_output_tokens
        )
        super().__init__("PROJECT_ANALYSIS_CONTEXT_LIMIT_EXCEEDED")


def _stable_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clean_project_ocr_text(source: str) -> str:
    text = unicodedata.normalize("NFC", str(source)).replace("\r\n", "\n").replace("\r", "\n")
    text = _HTML_IMAGE_PATTERN.sub("", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</t[dh]\s*>", " | ", text, flags=re.IGNORECASE)
    text = re.sub(r"</tr\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</table\s*>", "\n", text, flags=re.IGNORECASE)
    text = _HTML_TAG_PATTERN.sub("", text)
    text = html.unescape(text)
    text = "".join(
        character
        for character in text
        if character in "\n\t"
        or (
            unicodedata.category(character) not in {"Cc", "Cf"}
            and character != "\ufffd"
        )
    )
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"[ \t\u00a0\u3000]+", " ", raw_line).strip()
        line = re.sub(r"(?:\s*\|\s*){2,}", " | ", line).strip(" |")
        if line or (lines and lines[-1]):
            lines.append(line)
    return "\n".join(lines).strip()


def _records(state: dict[str, Any], primary: str, fallback: str | None = None) -> list[dict[str, Any]]:
    rows = state.get(primary)
    if not isinstance(rows, list) and fallback:
        rows = state.get(fallback)
    return [row for row in rows or [] if isinstance(row, dict)]


def _latest_parse_result(state: dict[str, Any], version_id: str) -> dict[str, Any]:
    rows = [
        row
        for row in _records(state, "ocr_parse_results")
        if str(row.get("documentVersionId") or "") == str(version_id)
    ]
    rows.sort(
        key=lambda row: str(
            row.get("finishedAt")
            or row.get("updatedAt")
            or row.get("createdAt")
            or row.get("id")
            or ""
        ),
        reverse=True,
    )
    return rows[0] if rows else {}


def _full_ocr_text(parse_result: dict[str, Any]) -> str:
    for key in ("fullText", "markdown", "contentMarkdown", "text"):
        value = parse_result.get(key)
        if isinstance(value, str) and value.strip():
            return value
    fragments = [
        row for row in parse_result.get("fragments") or [] if isinstance(row, dict)
    ]
    fragments.sort(
        key=lambda row: (
            int(row.get("pageNo") or 0),
            str(row.get("id") or ""),
        )
    )
    return "\n".join(
        str(row.get("text") or row.get("content") or "")
        for row in fragments
        if str(row.get("text") or row.get("content") or "").strip()
    )


def _node_record(state: dict[str, Any], project_id: str, node_id: int) -> dict[str, Any]:
    return next(
        (
            row
            for row in _records(state, "tree_nodes", "project_nodes")
            if str(row.get("projectId") or "") == str(project_id)
            and int(row.get("nodeId") or row.get("id") or 0) == int(node_id)
        ),
        {},
    )


def _node_requirements(state: dict[str, Any], project_id: str, node_id: int) -> list[dict[str, Any]]:
    return [
        deepcopy(row)
        for row in _records(state, "requirements", "node_requirements")
        if str(row.get("projectId") or project_id) == str(project_id)
        and int(row.get("nodeId") or 0) == int(node_id)
    ]


def _route_limits(model_route: dict[str, Any]) -> tuple[int, int]:
    budget = model_route.get("budgetPolicy") if isinstance(model_route.get("budgetPolicy"), dict) else {}
    maximum = int(model_route.get("maxContextTokens") or budget.get("maxContextTokens") or 0)
    reserved = int(model_route.get("reservedOutputTokens") or budget.get("reservedOutputTokens") or 0)
    return maximum, reserved


def build_project_analysis_snapshot(
    state: dict[str, Any],
    project_id: str,
    *,
    business_pack_id: str = DEFAULT_BUSINESS_PACK_ID,
    prompt_version: str = PROMPT_VERSION,
    model_route: dict[str, Any],
) -> dict[str, Any]:
    node_ids = sorted(
        {
            int(row.get("nodeId") or 0)
            for row in _records(state, "node_evidence_links")
            if str(row.get("projectId") or "") == str(project_id)
            and str(row.get("manualStatus") or "").lower() != "rejected"
            and int(row.get("nodeId") or 0) > 0
        }
    )
    nodes: list[dict[str, Any]] = []
    document_versions: set[str] = set()
    node_snapshot_hashes: dict[str, str] = {}
    for node_id in node_ids:
        active = active_node_document_versions(state, project_id, node_id)
        if not active:
            continue
        node = _node_record(state, project_id, node_id)
        file_refs = [
            {
                "fileId": str(row.get("documentId") or ""),
                "documentVersionId": str(row.get("documentVersionId") or ""),
            }
            for row in active
        ]
        document_versions.update(row["documentVersionId"] for row in file_refs)
        node_payload = {
            "nodeId": node_id,
            "nodeName": node.get("name") or node.get("nodeName") or f"节点 {node_id}",
            "criteria": node.get("criteria") or "",
            "checkMethod": node.get("checkMethod") or "",
            "configuredRequirements": _node_requirements(state, project_id, node_id),
            "fileRefs": file_refs,
        }
        nodes.append(node_payload)
        node_snapshot_hashes[str(node_id)] = _stable_hash(node_payload)
    maximum, reserved = _route_limits(model_route)
    core = {
        "schemaVersion": "ProjectAnalysisSnapshot@1.0.0",
        "projectId": str(project_id),
        "businessPackId": str(business_pack_id),
        "nodeIds": [row["nodeId"] for row in nodes],
        "nodes": nodes,
        "nodeSnapshotHashes": node_snapshot_hashes,
        "documentVersionIds": sorted(document_versions),
        "promptVersion": str(prompt_version),
        "modelAlias": str(model_route.get("modelAlias") or DEFAULT_MODEL_ALIAS),
        "modelRouteVersion": str(model_route.get("version") or model_route.get("id") or ""),
        "maxContextTokens": maximum,
        "reservedOutputTokens": reserved,
    }
    snapshot_hash = _stable_hash(core)
    return {
        "id": f"PASNAP-{snapshot_hash.removeprefix('sha256:')[:16].upper()}",
        "projectAnalysisSnapshotId": f"PASNAP-{snapshot_hash.removeprefix('sha256:')[:16].upper()}",
        **core,
        "snapshotHash": snapshot_hash,
        "createdAt": server_time(),
    }


def build_project_analysis_request(
    state: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    model_alias: str = DEFAULT_MODEL_ALIAS,
) -> dict[str, Any]:
    documents = {
        str(row.get("id") or ""): row for row in _records(state, "documents")
    }
    file_corpus: dict[str, dict[str, Any]] = {}
    nodes = deepcopy(snapshot.get("nodes") or [])
    for node in nodes:
        for file_ref in node.get("fileRefs") or []:
            file_id = str(file_ref.get("fileId") or "")
            version_id = str(file_ref.get("documentVersionId") or "")
            document = documents.get(file_id) or {}
            parse_result = _latest_parse_result(state, version_id)
            source_text = _full_ocr_text(parse_result)
            cleaned_text = clean_project_ocr_text(source_text)
            file_name = str(document.get("fileName") or file_id)
            file_ref["fileName"] = file_name
            if file_id not in file_corpus:
                file_corpus[file_id] = {
                    "fileId": file_id,
                    "documentVersionId": version_id,
                    "fileName": file_name,
                    "sourceContentHash": _stable_hash(source_text),
                    "cleanedContentHash": _stable_hash(cleaned_text),
                    "fullOcrText": cleaned_text,
                }
    project = next(
        (
            row
            for row in _records(state, "projects")
            if str(row.get("id") or "") == str(snapshot.get("projectId") or "")
        ),
        {},
    )
    payload = {
        "task": "Analyze every included business node in one response.",
        "requirements": [
            "Resolve every node.fileRefs[].fileId against project.fileCorpus before reviewing the node.",
            "Use only fileCorpus entries referenced by the current node.fileRefs.",
            "Read every resolved fullOcrText completely and do not truncate evidence.",
            "Every finding requires human confirmation.",
        ],
        "project": {
            "projectId": snapshot.get("projectId"),
            "projectCode": project.get("projectCode") or project.get("code") or snapshot.get("projectId"),
            "projectName": project.get("name") or project.get("projectName") or snapshot.get("projectId"),
            "includedNodeCount": len(nodes),
            "nodes": nodes,
            "fileCorpus": file_corpus,
        },
        "outputSchema": OUTPUT_SCHEMA,
    }
    return {
        "model": model_alias,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            },
        ],
    }


def project_analysis_preview(
    state: dict[str, Any],
    project_id: str,
    *,
    model_route: dict[str, Any],
) -> dict[str, Any]:
    snapshot = build_project_analysis_snapshot(
        state,
        project_id,
        business_pack_id=str(
            next(
                (
                    row.get("businessPackId")
                    for row in _records(state, "projects")
                    if str(row.get("id") or "") == str(project_id)
                ),
                DEFAULT_BUSINESS_PACK_ID,
            )
            or DEFAULT_BUSINESS_PACK_ID
        ),
        prompt_version=PROMPT_VERSION,
        model_route=model_route,
    )
    request = build_project_analysis_request(state, snapshot)
    estimated = estimate_messages_tokens(request["messages"])
    maximum, reserved = _route_limits(model_route)
    available = max(0, maximum - reserved)
    payload = json.loads(request["messages"][1]["content"])
    reference_count = sum(
        len(node.get("fileRefs") or []) for node in payload["project"]["nodes"]
    )
    return {
        "projectId": str(project_id),
        "snapshot": snapshot,
        "request": request,
        "snapshotHash": snapshot["snapshotHash"],
        "includedNodeCount": len(snapshot["nodeIds"]),
        "uniqueFileCount": len(payload["project"]["fileCorpus"]),
        "fileReferenceCount": reference_count,
        "estimatedInputTokens": estimated,
        "maxContextTokens": maximum,
        "reservedOutputTokens": reserved,
        "availableInputTokens": available,
        "contextLimitExceeded": estimated > available,
        "modelAlias": model_route.get("modelAlias") or DEFAULT_MODEL_ALIAS,
        "modelRouteVersion": snapshot["modelRouteVersion"],
    }


def prepare_project_analysis_request(
    state: dict[str, Any],
    project_id: str,
    *,
    model_route: dict[str, Any],
    model_call: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    preview = project_analysis_preview(state, project_id, model_route=model_route)
    if preview["contextLimitExceeded"]:
        raise ProjectAnalysisContextLimitError(
            estimated_tokens=preview["estimatedInputTokens"],
            max_context_tokens=preview["maxContextTokens"],
            reserved_output_tokens=preview["reservedOutputTokens"],
        )
    if model_call:
        model_call(preview["request"])
    return preview
