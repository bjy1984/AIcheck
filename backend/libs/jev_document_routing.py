"""Whole-document, per-node Jev routing suggestions shown in the Lab picker.

The suggestion is version-bound and directly available to the person selecting
materials. Accepting it uses the existing binding action and human confirmation.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from libs.jev_evaluation_input import approved_ocr_text
from libs.material_targeting import MANUAL_REJECTED, review_points_for_project
from libs.review_orchestrator.jev_client import (
    MODEL,
    RETRY_DELAYS_SECONDS,
    ask_jev,
    batch_jev_questions,
    jev_stage_enabled,
)
from libs.review_plugins.settings import project_plugin_enabled

CONFIDENCE_FLOOR = 0.90
QUESTION_BATCH_SIZE = 30
MAX_ROUTING_BATCHES = 10
MAX_TEMPLATE_CHARS = 6_000
# ask_jev 默认的单次请求超时。一批最坏：首次加每个退避各一次尝试都超时，再加退避等待；
# 批次串行，整份文件最多 MAX_ROUTING_BATCHES 批。worker 的路由锁必须撑过这段时间。
JEV_REQUEST_TIMEOUT_SECONDS = 15.0
ROUTING_REQUEST_BUDGET_SECONDS = MAX_ROUTING_BATCHES * (
    JEV_REQUEST_TIMEOUT_SECONDS * (len(RETRY_DELAYS_SECONDS) + 1) + sum(RETRY_DELAYS_SECONDS))
_CRITERIA = {
    "yes": "正文有该节点所需的实质资料，非仅提及名称。",
    "no": "正文无关或仅顺带提及。",
    "uncertain": "OCR 不足、对象不明或归属有歧义。",
}


def _node_questions(points: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, int], list[int]]:
    grouped: dict[int, dict[str, Any]] = defaultdict(lambda: {"nodeName": "", "requirements": []})
    for point in points:
        node_id = int(point.get("nodeId") or 0)
        if node_id < 1:
            continue
        group = grouped[node_id]
        group["nodeName"] = group["nodeName"] or str(point.get("nodeName") or "")
        group["requirements"].append({
            "review": str(point.get("reviewContent") or ""),
            "material": str(point.get("materialTypeName") or ""),
            "file": str(point.get("fileContent") or ""),
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
                f"仅凭完整 OCR 正文判断文件是否可用于节点 {node_id}。"
                f"不能只看文件名或关键词。节点模板：{template}"
            ),
            "criteria": _CRITERIA,
        }
        node_ids[key] = node_id
    return questions, node_ids, overlong


def routing_question_points(
    points: list[dict[str, Any]], *, project_id: str, business_pack_id: str,
    requirements: list[dict[str, Any]], tree_nodes: list[dict[str, Any]],
    configured_points: list[dict[str, Any]], business_pack_version: str = "",
) -> list[dict[str, Any]]:
    """Cover nodes with required files but no review point, without reviving disabled points.

    The project tree and requirements are the installed pack snapshot. A point
    explicitly disabled in admin configuration must stay out of Jev routing.
    """
    configured_node_ids = {
        int(row.get("nodeId") or 0)
        for row in configured_points
        if isinstance(row, dict)
        and str(row.get("businessPackId") or business_pack_id) == business_pack_id
    }
    active_nodes = {
        int(row.get("nodeId") or 0): row
        for row in tree_nodes
        if isinstance(row, dict) and str(row.get("projectId") or "") == project_id
        and str(row.get("businessPackId") or business_pack_id) == business_pack_id
        and (not business_pack_version or not row.get("businessPackVersion")
             or str(row["businessPackVersion"]) == business_pack_version)
    }
    supplemental: list[dict[str, Any]] = []
    for requirement in requirements:
        if not isinstance(requirement, dict) or str(requirement.get("projectId") or "") != project_id:
            continue
        if str(requirement.get("businessPackId") or business_pack_id) != business_pack_id:
            continue
        if (business_pack_version and requirement.get("businessPackVersion")
                and str(requirement["businessPackVersion"]) != business_pack_version):
            continue
        node_id = int(requirement.get("nodeId") or 0)
        if node_id not in active_nodes or node_id in configured_node_ids:
            continue
        node_version = str(active_nodes[node_id].get("businessPackVersion") or "")
        requirement_version = str(requirement.get("businessPackVersion") or "")
        if node_version and requirement_version and node_version != requirement_version:
            continue
        supplemental.append({
            "nodeId": node_id,
            "nodeName": str(active_nodes[node_id].get("name") or ""),
            "reviewContent": "仅判断文件能否作为此节点的资料；人工评价结论仍由监检人员作出。",
            "materialTypeName": str(requirement.get("name") or requirement.get("materialTypeCode") or ""),
            "fileContent": str(requirement.get("note") or ""),
        })
    return [*points, *supplemental]


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
    # 工程选用了 Jev 插件才外发；没有明确设定的工程沿用原来的文件归属白名单。
    if not project_plugin_enabled(project, "jev", legacy_env="AICHECK_JEV_DOCUMENT_ROUTING_ALLOWED_PROJECTS"):
        return {**base, "status": "project_not_approved_for_jev"}
    if str(document.get("currentVersionId") or "") != version_id:
        return {**base, "status": "stale_version"}
    run_scope = {"projectId": project_id, "tenantId": document.get("tenantId"),
                 "nodeId": "待归属", "inputDocumentVersionIds": [version_id]}
    # 只送 OCR 正文：工程号、节点、文件名、内部版本号都留在本地，也免得按文件名归类。
    # 与路由评测、预检脚本走同一条已批准的出站入口。
    ocr_status, full_state = approved_ocr_text(repo.state, run_scope)
    if ocr_status == "invalid_scope":
        return {**base, "status": "invalid_scope"}
    if ocr_status == "overlong_document":
        return {**base, "status": "overlong_document", "overlongDocumentVersionIds": [version_id]}
    if ocr_status == "ocr_not_ready":
        return {**base, "status": "ocr_not_ready"}
    if ocr_status != "ready":
        return {**base, "status": "no_ocr_text"}
    business_pack_id = str(project.get("businessPackId") or "engineering_inspection_v1")
    points = routing_question_points(
        review_points_for_project(repo, project), project_id=project_id,
        business_pack_id=business_pack_id,
        business_pack_version=str(project.get("businessPackVersion") or ""),
        requirements=repo.state.get("requirements") or [],
        tree_nodes=repo.state.get("tree_nodes") or [],
        configured_points=(repo.state.get("admin_config") or {}).get("materialReviewPoints") or [],
    )
    questions, node_ids, overlong_templates = _node_questions(points)
    if not questions:
        return {**base, "status": "no_templates", "overlongNodeIds": overlong_templates}
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
    previous = document.get("jevRoutingDecision") or {}
    if (previous.get("status") in {"completed", "partial"} and previous.get("model") == MODEL
            and previous.get("projectId") == project_id
            and previous.get("documentId") == document_id
            and previous.get("documentVersionId") == version_id
            and previous.get("inputHash") == input_hash):
        return {**previous, "reused": True}
    try:
        batches = batch_jev_questions(full_state, questions, max_questions=QUESTION_BATCH_SIZE)
    except ValueError:
        return {**base, "status": "request_overlong", "inputHash": input_hash,
                "overlongNodeIds": overlong_templates}
    if len(batches) > MAX_ROUTING_BATCHES:
        return {**base, "status": "request_budget_exceeded", "inputHash": input_hash,
                "requiredBatchCount": len(batches), "overlongNodeIds": overlong_templates}
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
