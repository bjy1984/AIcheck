"""Whole-document, per-node Jev routing suggestions for uploaded project files.

This is an asynchronous shadow signal. It never changes a material type, node
binding, evidence link, or review result; those still require their own checks.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from libs.material_targeting import MANUAL_REJECTED, review_points_for_project
from libs.review_orchestrator.jev_client import MODEL, ask_jev, jev_stage_enabled
from libs.review_orchestrator.jev_state import scoped_document_states

CONFIDENCE_FLOOR = 0.90
QUESTION_BATCH_SIZE = 30
MAX_TEMPLATE_CHARS = 6_000
MAX_REQUEST_CHARS = 40_000
_CRITERIA = {
    "yes": "本文件的原文包含该节点至少一项审查所需的实质资料，不只是顺带提到名称。",
    "no": "本文件原文与该节点的审查资料无关，或只顺带提到该节点。",
    "uncertain": "OCR 原文不足、对象不明或资料归属有歧义，不能可靠判断。",
}


def _node_questions(points: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, int], list[int]]:
    grouped: dict[int, list[dict[str, str]]] = defaultdict(list)
    for point in points:
        node_id = int(point.get("nodeId") or 0)
        if node_id < 1:
            continue
        grouped[node_id].append({
            "nodeName": str(point.get("nodeName") or ""),
            "reviewContent": str(point.get("reviewContent") or ""),
            "materialType": str(point.get("materialTypeName") or ""),
            "fileContent": str(point.get("fileContent") or ""),
        })
    questions: dict[str, dict[str, Any]] = {}
    node_ids: dict[str, int] = {}
    overlong: list[int] = []
    for node_id in sorted(grouped):
        template = json.dumps(grouped[node_id], ensure_ascii=False, sort_keys=True)
        if len(template) > MAX_TEMPLATE_CHARS:
            overlong.append(node_id)
            continue
        key = f"node_{node_id}"
        questions[key] = {
            "type": "choice",
            "instructions": (
                f"仅根据这份文件的完整 OCR 原文，判断它是否可作为节点 {node_id} 的审查资料。"
                "不得仅凭文件名、资料类型代码或正文中偶然出现的关键词判是。"
                f"该节点审查模板：{template}"
            ),
            "criteria": _CRITERIA,
        }
        node_ids[key] = node_id
    return questions, node_ids, overlong


def _question_batches(full_state: str, questions: dict[str, dict[str, Any]]) -> list[dict[str, dict[str, Any]]]:
    """Limit the whole request envelope, not just its OCR state."""
    batches: list[dict[str, dict[str, Any]]] = []
    batch: dict[str, dict[str, Any]] = {}
    for key, question in questions.items():
        candidate = {**batch, key: question}
        length = len(json.dumps({"state": full_state, "model": MODEL, "questions": candidate}, ensure_ascii=False))
        if len(candidate) > QUESTION_BATCH_SIZE or length > MAX_REQUEST_CHARS:
            if not batch:
                return []
            batches.append(batch)
            batch = {key: question}
            length = len(json.dumps({"state": full_state, "model": MODEL, "questions": batch}, ensure_ascii=False))
            if length > MAX_REQUEST_CHARS:
                return []
        else:
            batch = candidate
    if batch:
        batches.append(batch)
    return batches


def classify_document_node_routing(
    repo: Any, project_id: str, document_id: str, version_id: str,
) -> dict[str, Any]:
    """Return version-bound suggestions; unavailable answers never become bindings."""
    base = {"model": MODEL, "projectId": project_id, "documentId": document_id,
            "documentVersionId": version_id}
    if not jev_stage_enabled("DOCUMENT_ROUTING"):
        return {**base, "status": "disabled"}
    project = repo.require_project(project_id)
    document = repo.find_one("documents", document_id)
    version = repo.find_one("versions", version_id)
    if (not project or not document or not version
            or str(document.get("projectId") or "") != project_id
            or str(version.get("documentId") or "") != document_id):
        return {**base, "status": "invalid_scope"}
    if str(document.get("currentVersionId") or "") != version_id:
        return {**base, "status": "stale_version"}
    run_scope = {"projectId": project_id, "tenantId": document.get("tenantId"),
                 "nodeId": "待归属", "inputDocumentVersionIds": [version_id]}
    try:
        states, _, overlong_versions = scoped_document_states(repo.state, run_scope, [])
    except ValueError:
        return {**base, "status": "invalid_scope"}
    if overlong_versions:
        return {**base, "status": "overlong_document", "overlongDocumentVersionIds": overlong_versions}
    if not states or not states[0]["hasOcrText"]:
        return {**base, "status": "no_ocr_text"}
    questions, node_ids, overlong_templates = _node_questions(review_points_for_project(repo, project))
    if not questions:
        return {**base, "status": "no_templates", "overlongNodeIds": overlong_templates}
    full_state = states[0]["state"]
    rejected_nodes = {
        int(item.get("nodeId") or 0)
        for item in repo.state.get("node_evidence_links", [])
        if item.get("projectId") == project_id and item.get("documentVersionId") == version_id
        and item.get("manualStatus") == MANUAL_REJECTED
    }
    existing_nodes = {
        int(item.get("nodeId") or 0)
        for item in repo.state.get("node_evidence_links", [])
        if item.get("projectId") == project_id and item.get("documentVersionId") == version_id
        and item.get("manualStatus") != MANUAL_REJECTED
    }
    input_hash = hashlib.sha256(json.dumps(
        [full_state, questions, sorted(rejected_nodes), sorted(existing_nodes)],
        ensure_ascii=False, sort_keys=True,
    ).encode("utf-8")).hexdigest()
    previous = document.get("jevRoutingShadow") or {}
    if (previous.get("status") in {"completed", "partial"} and previous.get("model") == MODEL
            and previous.get("projectId") == project_id
            and previous.get("documentId") == document_id
            and previous.get("documentVersionId") == version_id
            and previous.get("inputHash") == input_hash):
        return {**previous, "reused": True}
    batches = _question_batches(full_state, questions)
    if not batches:
        return {**base, "status": "request_overlong", "inputHash": input_hash,
                "overlongNodeIds": overlong_templates}
    answers: dict[str, Any] = {}
    try:
        for batch in batches:
            answers.update(ask_jev(full_state, batch))
    except (OSError, RuntimeError, ValueError) as exc:
        return {**base, "status": "unavailable", "inputHash": input_hash,
                "reason": type(exc).__name__, "overlongNodeIds": overlong_templates}
    if set(answers) != set(questions):
        return {**base, "status": "invalid_response", "inputHash": input_hash,
                "overlongNodeIds": overlong_templates}
    scores = [
        {"nodeId": node_ids[key], "choice": answer["choice"], "confidence": answer["confidence"]}
        for key, answer in answers.items() if key in node_ids
    ]
    scores.sort(key=lambda item: item["nodeId"])
    suggestions = {
        item["nodeId"] for item in scores
        if item["choice"] == "yes" and item["confidence"] >= CONFIDENCE_FLOOR
        and item["nodeId"] not in rejected_nodes
    }
    return {
        **base, "status": "partial" if overlong_templates else "completed", "inputHash": input_hash,
        "requestBatchCount": len(batches),
        "nodeScores": scores, "suggestedNodeIds": sorted(suggestions),
        "existingNodeIds": sorted(existing_nodes),
        "disagreementNodeIds": sorted(suggestions ^ existing_nodes),
        "humanRejectedNodeIds": sorted(rejected_nodes),
        "overlongNodeIds": overlong_templates,
    }
