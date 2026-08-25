from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn


WORKTREE = Path("/Volumes/7up/github/knowledgetools/.worktrees/qwen-auto-gold-classification")
BACKEND = WORKTREE / "backend"
MAIN_ROOT = Path("/Volumes/7up/github/knowledgetools")
OUTPUT = MAIN_ROOT / "output" / "platform_internal_ai_review_20260825"
TARGETING_PATH = MAIN_ROOT / "output" / "two_project_node_eval_20260824" / "node_targeting_results.json"
MONITOR_RESULTS_PATH = OUTPUT / "platform_monitor_view_results.json"

BASE_PROJECT_ID = "P-2026-HDCP-001"
PROJECT_IDS = {"test": "P-TEST-OCR-001", "test2": "P-TEST-OCR-002"}
PROJECT_NAMES = {
    "test": "TEST项目一｜珠海海瑞德制药压力管道安装",
    "test2": "TEST项目二｜珠海新建化工区管道气站",
}
NOW = "2026-08-25 12:00:00"


os.environ.update(
    {
        "AICHECK_ENABLE_DEMO_DATA": "true",
        "AICHECK_ENABLE_DEMO_USERS": "true",
        "AICHECK_ENABLE_COMPATIBILITY_MOCKS": "true",
        "AICHECK_REQUIRE_AUTH": "true",
        "AICHECK_REQUIRE_IF_MATCH": "false",
        "AICHECK_SQLITE_DISABLE": "true",
        "AICHECK_STRICT_PRODUCTION": "false",
    }
)
for key in ("AICHECK_DATABASE_URL", "DATABASE_URL", "AICHECK_SQLITE_PATH"):
    os.environ.pop(key, None)

sys.path.insert(0, str(BACKEND))

from apps.api.main import app  # noqa: E402
from libs.db.repository import repo  # noqa: E402


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_paths() -> list[Path]:
    paths = [TARGETING_PATH, MONITOR_RESULTS_PATH]
    paths.extend((MAIN_ROOT / "output" / "test_qwen_classification_20260824" / "ocr").glob("*.md"))
    paths.extend((MAIN_ROOT / "output" / "test_qwen_classification_20260824" / "classification_fixed").glob("*.json"))
    paths.extend((MAIN_ROOT / "output" / "two_project_node_eval_20260824" / "test2" / "ocr").glob("*.md"))
    paths.extend((MAIN_ROOT / "output" / "two_project_node_eval_20260824" / "test2" / "classification").glob("*.json"))
    return sorted({path.resolve() for path in paths if path.is_file()})


def chunks(text: str, size: int = 1800) -> list[str]:
    value = re.sub(r"\n{4,}", "\n\n", text).strip()
    result: list[str] = []
    cursor = 0
    while cursor < len(value):
        end = min(len(value), cursor + size)
        if end < len(value):
            split = max(value.rfind("\n", cursor, end), value.rfind("。", cursor, end))
            if split > cursor + size // 2:
                end = split + 1
        part = value[cursor:end].strip()
        if part:
            result.append(part)
        cursor = end
    return result


def ocr_path(project: str, case_id: str) -> Path | None:
    root = (
        MAIN_ROOT / "output" / "test_qwen_classification_20260824" / "ocr"
        if project == "test"
        else MAIN_ROOT / "output" / "two_project_node_eval_20260824" / "test2" / "ocr"
    )
    for suffix in (".md", ".office.txt"):
        candidate = root / f"{case_id}{suffix}"
        if candidate.exists():
            return candidate
    return None


def classification_path(project: str, case_id: str) -> Path | None:
    root = (
        MAIN_ROOT / "output" / "test_qwen_classification_20260824" / "classification_fixed"
        if project == "test"
        else MAIN_ROOT / "output" / "two_project_node_eval_20260824" / "test2" / "classification"
    )
    candidate = root / f"{case_id}.json"
    return candidate if candidate.exists() else None


def classification_payload(project: str, case_id: str) -> dict[str, Any]:
    path = classification_path(project, case_id)
    return load(path) if path else {}


def clone_project_scaffold(project: str) -> tuple[dict[str, str], dict[int, dict[str, Any]]]:
    project_id = PROJECT_IDS[project]
    source_project = repo.require_project(BASE_PROJECT_ID)
    record = deepcopy(source_project)
    record.update(
        {
            "id": project_id,
            "code": project_id,
            "name": PROJECT_NAMES[project],
            "status": "监检审查中",
            "currentNodeId": 1,
            "riskLevel": "高",
            "updatedAt": NOW,
            "createdAt": NOW,
            "dataSource": "test_ocr_llm_frozen_import",
            "sourceBusinessDataImmutable": True,
        }
    )
    repo.state["projects"].append(record)

    node_map: dict[int, dict[str, Any]] = {}
    for source in [item for item in repo.state["tree_nodes"] if item.get("projectId") == BASE_PROJECT_ID]:
        node = deepcopy(source)
        node_id = int(node["nodeId"])
        node.update(
            {
                "id": f"{project_id}-{node_id}",
                "projectId": project_id,
                "status": "待提交",
                "fileCount": 0,
                "revision": 1,
            }
        )
        repo.state["tree_nodes"].append(node)
        node_map[node_id] = node

    requirement_ids: dict[str, str] = {}
    for source in [item for item in repo.state["requirements"] if item.get("projectId") == BASE_PROJECT_ID]:
        requirement = deepcopy(source)
        old_id = str(requirement["id"])
        new_id = f"{old_id}-{project.upper()}"
        requirement.update({"id": new_id, "projectId": project_id})
        requirement_ids[old_id] = new_id
        repo.state["requirements"].append(requirement)

    for source in [
        item
        for item in repo.state["project_node_clause_packages"]
        if item.get("projectId") == BASE_PROJECT_ID
    ]:
        package = deepcopy(source)
        package.update(
            {
                "id": f"PNCP-{project_id}-{source['nodeId']}",
                "projectId": project_id,
                "boundAt": NOW,
            }
        )
        repo.state["project_node_clause_packages"].append(package)

    repo.state["project_members"].append(
        {
            "id": f"PM-INSPECTION-{project.upper()}",
            "projectId": project_id,
            "userId": "USER-INSPECTION-001",
            "name": "张工",
            "orgName": "省特检院一部",
            "role": "inspection",
            "nodeScope": list(range(1, 70)),
            "actions": [
                "project:view",
                "file:view",
                "file:preview",
                "review:view",
                "review:save",
                "review:return-correction",
                "ai:recheck",
                "report:view",
            ],
            "status": "启用",
            "updatedAt": NOW,
            "tenantId": "TENANT-DEFAULT",
        }
    )
    return requirement_ids, node_map


def find_requirement(project_id: str, node_id: int, material_codes: list[str]) -> dict[str, Any]:
    rows = [
        item
        for item in repo.state["requirements"]
        if item.get("projectId") == project_id and int(item.get("nodeId") or 0) == node_id
    ]
    return next(
        (item for item in rows if str(item.get("materialTypeCode") or "") in set(material_codes)),
        rows[0] if rows else {},
    )


def import_documents_and_bindings(
    project: str,
    targeting_project: dict[str, Any],
    node_map: dict[int, dict[str, Any]],
) -> tuple[list[str], dict[int, list[dict[str, Any]]]]:
    project_id = PROJECT_IDS[project]
    all_binding_ids: list[str] = []
    links_by_node: dict[int, list[dict[str, Any]]] = {}
    for index, file in enumerate(targeting_project["files"], 1):
        case_id = str(file["caseId"])
        document_id = f"DOC-{project.upper()}-{index:03d}"
        version_id = f"DV-{project.upper()}-{index:03d}-V1"
        material_codes = [str(value) for value in file.get("predictedMaterialTypeCodes") or []]
        classification = classification_payload(project, case_id)
        source_ocr = ocr_path(project, case_id)
        markdown = source_ocr.read_text(encoding="utf-8", errors="replace") if source_ocr else ""
        fragments = chunks(markdown)
        repo.state["documents"].append(
            {
                "id": document_id,
                "projectId": project_id,
                "fileName": Path(str(file["relativePath"])).name,
                "relativePath": file["relativePath"],
                "fileType": Path(str(file["relativePath"])).suffix.lstrip(".") or "file",
                "sourceOrgName": "测试项目原始资料",
                "uploaderName": "测试数据导入",
                "currentVersionId": version_id,
                "fileStatus": "已上传",
                "currentOcrStatus": "已识别",
                "sliceStatus": "已切片",
                "vectorStatus": "已向量化",
                "materialTypeCode": material_codes[0] if material_codes else None,
                "materialTypeCodes": material_codes,
                "materialCategory": ",".join(file.get("materialCategoryLabels") or []),
                "autoClassification": {
                    "source": "qwen3.8-max",
                    "materialTypeCodes": material_codes,
                    "materialCategoryLabels": file.get("materialCategoryLabels") or [],
                    "classificationTargetingMode": file.get("classificationTargetingMode"),
                },
                "sourceCaseId": case_id,
                "businessDataImmutable": True,
                "updatedAt": NOW,
                "tenantId": "TENANT-DEFAULT",
            }
        )
        repo.state["versions"].append(
            {
                "id": version_id,
                "documentId": document_id,
                "versionNo": "V1",
                "hash": f"sha256:{sha256(source_ocr) if source_ocr else hashlib.sha256(case_id.encode()).hexdigest()}",
                "fileSize": source_ocr.stat().st_size if source_ocr else 0,
                "storageKey": f"test-import/{project}/{case_id}",
                "ocrStatus": "已识别",
                "sliceStatus": "已切片",
                "vectorStatus": "已向量化",
                "uploaderName": "测试数据导入",
                "uploadTime": NOW,
                "isCurrent": True,
                "tenantId": "TENANT-DEFAULT",
            }
        )
        ocr_fragments = []
        for part_no, part in enumerate(fragments, 1):
            bbox = [40, 80 + (part_no % 8) * 90, 1160, 150 + (part_no % 8) * 90]
            evidence_id = f"EV-{project.upper()}-{index:03d}-{part_no:03d}"
            ocr_fragments.append(
                {
                    "pageNo": part_no,
                    "text": part,
                    "bbox": bbox,
                    "confidence": 0.9,
                    "sourceEngine": "mineru_markdown_import",
                }
            )
            repo.state["evidence_links"].append(
                {
                    "id": evidence_id,
                    "projectId": project_id,
                    "objectType": "ocr_fragment",
                    "objectId": f"PARSE-{project.upper()}-{index:03d}",
                    "documentId": document_id,
                    "documentVersionId": version_id,
                    "fileName": Path(str(file["relativePath"])).name,
                    "pageNo": part_no,
                    "fieldName": "OCR Markdown",
                    "quotedText": part[:1000],
                    "bbox": bbox,
                    "confidence": 0.9,
                    "tenantId": "TENANT-DEFAULT",
                }
            )
        repo.state["ocr_parse_results"].append(
            {
                "id": f"PARSE-{project.upper()}-{index:03d}",
                "parseResultId": f"PARSE-{project.upper()}-{index:03d}",
                "projectId": project_id,
                "documentId": document_id,
                "documentVersionId": version_id,
                "status": "success",
                "sourceMethod": "mineru_markdown_import",
                "markdownArtifact": str(source_ocr) if source_ocr else None,
                "fragments": ocr_fragments,
                "fields": [],
                "tables": [],
                "seals": [],
                "quality": {"reviewRequired": False, "source": "frozen_test_mineru_markdown"},
                "createdAt": NOW,
                "tenantId": "TENANT-DEFAULT",
            }
        )
        repo.state["document_classification_runs"].append(
            {
                "id": f"DCR-{project.upper()}-{index:03d}",
                "runId": f"DCR-{project.upper()}-{index:03d}",
                "projectId": project_id,
                "documentId": document_id,
                "documentVersionId": version_id,
                "caseId": case_id,
                "status": "success",
                "protocolStatus": classification.get("protocolStatus") or "accepted",
                "model": classification.get("model") or "qwen3.8-max",
                "provider": classification.get("provider") or "Model Studio / DashScope",
                "predictedMaterialTypeCodes": material_codes,
                "materialCategoryLabels": file.get("materialCategoryLabels") or [],
                "structuredResponse": classification.get("structuredResponse")
                or {"labels": classification.get("labels") or [], "documentSummary": (classification.get("rawModelOutput") or {}).get("documentSummary")},
                "rawModelOutput": classification.get("rawModelOutput") or {},
                "inputTokens": classification.get("inputTokens") or (classification.get("usage") or {}).get("prompt_tokens"),
                "outputTokens": classification.get("outputTokens") or (classification.get("usage") or {}).get("completion_tokens"),
                "createdAt": NOW,
                "updatedAt": NOW,
                "tenantId": "TENANT-DEFAULT",
            }
        )

        for node_id in [int(value) for value in file.get("formalNodeIds") or []]:
            requirement = find_requirement(project_id, node_id, material_codes)
            binding_id = f"BIND-{project.upper()}-{index:03d}-{node_id:02d}"
            binding = {
                "id": binding_id,
                "projectId": project_id,
                "nodeId": node_id,
                "requirementId": requirement.get("id"),
                "requirementName": requirement.get("name"),
                "documentId": document_id,
                "documentVersionId": version_id,
                "fileName": Path(str(file["relativePath"])).name,
                "versionNo": "V1",
                "usage": "OCR+LLM自动分类正式挂载",
                "bindingStatus": "已提交",
                "boundByName": "Qwen自动分类",
                "boundAt": NOW,
                "tenantId": "TENANT-DEFAULT",
            }
            repo.state["bindings"].append(binding)
            all_binding_ids.append(binding_id)
            first = fragments[0] if fragments else ""
            link = {
                "id": f"NEL-{project.upper()}-{index:03d}-{node_id:02d}",
                "projectId": project_id,
                "nodeId": node_id,
                "nodeName": node_map[node_id]["name"],
                "reviewPointId": requirement.get("id"),
                "reviewContent": requirement.get("note") or requirement.get("name"),
                "materialTypeCode": material_codes[0] if material_codes else None,
                "materialTypeCodes": material_codes,
                "materialTypeName": requirement.get("name"),
                "requiredType": requirement.get("requiredType") or "必传",
                "documentId": document_id,
                "documentVersionId": version_id,
                "fileName": Path(str(file["relativePath"])).name,
                "pageNo": 1,
                "bbox": [40, 80, 1160, 150],
                "fieldName": "OCR Markdown",
                "quotedText": first[:1000],
                "matchedEvidenceItems": [first[:200]] if first else [],
                "supportStatus": "supported",
                "confidence": 0.9,
                "manualStatus": "pending",
                "source": "qwen_classification_formal_binding",
                "createdAt": NOW,
                "tenantId": "TENANT-DEFAULT",
            }
            repo.state["node_evidence_links"].append(link)
            links_by_node.setdefault(node_id, []).append(link)

        repo.state["material_targeting_runs"].append(
            {
                "id": f"MTR-{project.upper()}-{index:03d}",
                "runId": f"MTR-{project.upper()}-{index:03d}",
                "projectId": project_id,
                "documentId": document_id,
                "documentVersionId": version_id,
                "materialTypeCodes": material_codes,
                "formalNodeIds": file.get("formalNodeIds") or [],
                "advisoryNodeIds": file.get("advisoryNodeIds") or [],
                "boundNodeIds": file.get("boundNodeIds") or [],
                "classificationTargetingMode": file.get("classificationTargetingMode"),
                "status": "completed",
                "createdAt": NOW,
                "tenantId": "TENANT-DEFAULT",
            }
        )
    return all_binding_ids, links_by_node


def import_submission(project: str, binding_ids: list[str]) -> None:
    project_id = PROJECT_IDS[project]
    submission_id = f"SUB-{project.upper()}-001"
    node_ids = sorted(
        {
            int(item["nodeId"])
            for item in repo.state["bindings"]
            if item.get("projectId") == project_id and item.get("id") in set(binding_ids)
        }
    )
    document_ids = sorted(
        {
            str(item["documentId"])
            for item in repo.state["bindings"]
            if item.get("projectId") == project_id and item.get("id") in set(binding_ids)
        }
    )
    repo.state["submissions"].append(
        {
            "id": submission_id,
            "submissionId": submission_id,
            "snapshotId": f"SNAPSHOT-{project.upper()}-001",
            "projectId": project_id,
            "submissionType": "document",
            "nodeIds": node_ids,
            "documentIds": document_ids,
            "bindingIds": binding_ids,
            "batchName": f"{project} OCR+LLM分类挂载测试资料",
            "submitterName": "测试数据导入",
            "submitterComment": "保持原始业务数据不变，仅补齐提交过程记录。",
            "status": "已提交",
            "nextStatus": "待审查",
            "submittedAt": NOW,
            "createdAt": NOW,
            "tenantId": "TENANT-DEFAULT",
        }
    )


def import_review_runs(project: str, monitor_project: dict[str, Any], links_by_node: dict[int, list[dict[str, Any]]]) -> None:
    project_id = PROJECT_IDS[project]
    for node in monitor_project["nodes"]:
        source = node.get("platformReview")
        node_id = int(node["nodeId"])
        if not source:
            continue
        ai_run_id = f"AIRUN-{project.upper()}-{node_id:02d}"
        review_run_id = f"RRUN-{project.upper()}-{node_id:02d}"
        drafts = []
        for index, original in enumerate(source.get("findingDrafts") or [], 1):
            draft = deepcopy(original)
            draft.update(
                {
                    "id": f"FND-{project.upper()}-{node_id:02d}-{index:02d}",
                    "reviewRunId": review_run_id,
                    "projectId": project_id,
                    "nodeId": node_id,
                    "status": "pending_human_review",
                }
            )
            drafts.append(draft)
        version_ids = list(source.get("inputDocumentVersionIds") or [])
        evidence_links = deepcopy(links_by_node.get(node_id) or [])
        review_run = {
            "id": review_run_id,
            "reviewRunId": review_run_id,
            "aiRunId": ai_run_id,
            "projectId": project_id,
            "nodeId": node_id,
            "businessPackId": "engineering_inspection_v1",
            "businessPackVersion": "2026.07.16",
            "agentId": "compliance_review_agent",
            "agentVersion": "1.1.0",
            "promptVersion": f"node-{node_id}-v1",
            "modelAlias": "review-chat",
            "modelGateway": "qwen_runtime",
            "auditInputMode": "ocr_llm",
            "reviewMode": "gap_precheck",
            "advisoryOnly": True,
            "inputDocumentVersionIds": version_ids,
            "status": "waiting_human_review",
            "currentStep": "waiting_human_review",
            "workflowEngine": "inline_temporal_compatible",
            "graphEngine": "langgraph",
            "findingDrafts": drafts,
            "qualityGate": deepcopy(source.get("qualityGate") or {}),
            "evidenceBudget": deepcopy(source.get("evidenceBudget") or {}),
            "llmMetadata": {
                "llmExecution": "qwen_runtime",
                "llmCalled": True,
                "modelAlias": "review-chat",
                "modelResolved": source.get("model") or "qwen3.7-plus",
                "usage": deepcopy(source.get("usage") or {}),
                "resultText": json.dumps({"findings": drafts}, ensure_ascii=False),
                "reasoningProcess": "模型返回结构化审查草稿；未返回单独的公开推理摘要。",
                "auditInputMode": "ocr_llm",
            },
            "createdAt": NOW,
            "startedAt": NOW,
            "finishedAt": NOW,
            "updatedAt": NOW,
            "revision": 2,
            "tenantId": "TENANT-DEFAULT",
        }
        repo.state["review_runs"].append(review_run)
        ai_run = {
            "id": ai_run_id,
            "projectId": project_id,
            "nodeId": node_id,
            "reviewRunId": review_run_id,
            "subject": node["nodeName"],
            "model": "review-chat",
            "auditInputMode": "ocr_llm",
            "reviewMode": "gap_precheck",
            "advisoryOnly": True,
            "status": "完成",
            "suggestion": deepcopy(source.get("suggestion") or {}),
            "findingDrafts": drafts,
            "evidenceLinks": evidence_links,
            "inputDocumentVersionIds": version_ids,
            "llmMetadata": deepcopy(review_run["llmMetadata"]),
            "steps": [
                {
                    "id": f"RGN-{project.upper()}-{node_id:02d}-{index:02d}",
                    "title": graph.get("nodeKey"),
                    "action": graph.get("nodeKey"),
                    "conclusion": graph.get("status"),
                    "evidenceLinkIds": [item["id"] for item in evidence_links[:3]],
                }
                for index, graph in enumerate(source.get("graphNodes") or [], 1)
            ],
            "startedAt": NOW,
            "finishedAt": NOW,
            "tenantId": "TENANT-DEFAULT",
        }
        repo.state["ai_runs"].insert(0, ai_run)
        for index, graph in enumerate(source.get("graphNodes") or [], 1):
            repo.state["review_graph_nodes"].append(
                {
                    "id": f"RGN-{project.upper()}-{node_id:02d}-{index:02d}",
                    "reviewRunId": review_run_id,
                    "projectId": project_id,
                    "nodeId": node_id,
                    "nodeKey": graph.get("nodeKey"),
                    "label": graph.get("nodeKey"),
                    "sequence": index,
                    "status": graph.get("status"),
                    "details": deepcopy(graph.get("details") or {}),
                    "startedAt": NOW,
                    "finishedAt": NOW,
                    "tenantId": "TENANT-DEFAULT",
                }
            )
        for sequence, event in enumerate(
            [
                ("review_run.created", "AI审查任务已创建", "queued"),
                ("review_run.started", "LangGraph审查已启动", "running"),
                ("review_run.waiting_human", "等待人工确认", "waiting_human_review"),
            ],
            1,
        ):
            repo.state["review_events"].append(
                {
                    "id": f"REVT-{project.upper()}-{node_id:02d}-{sequence}",
                    "reviewRunId": review_run_id,
                    "projectId": project_id,
                    "nodeId": node_id,
                    "sequence": sequence,
                    "eventType": event[0],
                    "title": event[1],
                    "status": event[2],
                    "createdAt": NOW,
                    "tenantId": "TENANT-DEFAULT",
                }
            )
        usage = source.get("usage") or {}
        repo.state["model_call_attempts"].append(
            {
                "id": f"MCALL-{project.upper()}-{node_id:02d}",
                "reviewRunId": review_run_id,
                "aiRunId": ai_run_id,
                "projectId": project_id,
                "nodeId": node_id,
                "stage": "review_generate_findings",
                "modelAlias": "review-chat",
                "model": source.get("model") or "qwen3.7-plus",
                "provider": "Model Studio / DashScope",
                "status": "success",
                "usage": deepcopy(usage),
                "createdAt": NOW,
                "finishedAt": NOW,
                "tenantId": "TENANT-DEFAULT",
            }
        )
        session_id = f"RSESSION-{project.upper()}-{node_id:02d}"
        selected_ids = [item["id"] for item in evidence_links]
        session = {
            "id": session_id,
            "projectId": project_id,
            "nodeId": node_id,
            "role": "inspection",
            "status": "active",
            "currentTask": node["nodeName"],
            "activeReviewRunId": review_run_id,
            "selectedEvidenceLinkIds": selected_ids,
            "selectedJudgmentIds": [],
            "contextRevision": 2,
            "revision": 2,
            "createdBy": "USER-INSPECTION-001",
            "createdByName": "张工",
            "tenantId": "TENANT-DEFAULT",
            "createdAt": NOW,
            "updatedAt": NOW,
        }
        repo.state["review_sessions"].append(session)
        suggestion = source.get("suggestion") or {}
        finding_lines = []
        for index, finding in enumerate(drafts, 1):
            severity = {"critical": "严重", "high": "高", "medium": "中", "low": "低"}.get(
                str(finding.get("severity") or ""), str(finding.get("severity") or "未标注")
            )
            finding_lines.append(
                f"{index}. **[{severity}] {finding.get('title') or 'AI审查意见'}**\n"
                f"   {finding.get('description') or '请结合证据链人工确认。'}"
            )
        message_text = "\n\n".join(
            [
                f"## AI建议：{suggestion.get('result') or '需人工确认'}",
                str(suggestion.get("opinionDraft") or "AI缺项预审已完成，请人工确认。"),
                "### AI findings\n" + "\n".join(finding_lines),
                "以上内容仅作为监检审查提示，不替代最终人工结论。",
            ]
        )
        assistant_message = {
            "id": f"RMSG-{project.upper()}-{node_id:02d}-AI",
            "sessionId": session_id,
            "sequence": 1,
            "role": "assistant",
            "messageType": "review_response",
            "status": "completed",
            "contentBlocks": [
                {"type": "text", "text": message_text},
                {
                    "type": "evidence_card",
                    "title": "本次AI审查关联证据",
                    "evidenceLinkIds": selected_ids,
                    "items": evidence_links,
                },
                {
                    "type": "judgment_summary",
                    "reviewRunId": review_run_id,
                    "status": "waiting_human_review",
                    "currentStep": "waiting_human_review",
                    "findingCount": len(drafts),
                },
                {
                    "type": "action_suggestions",
                    "actions": [
                        {"actionKey": "search_evidence", "label": "检索证据"},
                        {"actionKey": "explain_basis", "label": "标准条款"},
                        {"actionKey": "draft_opinion", "label": "草拟意见"},
                    ],
                },
            ],
            "execution": {
                "mode": "llm_agent",
                "modelCalled": True,
                "agentEnabled": True,
                "provider": "Model Studio / DashScope",
                "model": source.get("model") or "qwen3.7-plus",
                "toolCallCount": len(source.get("graphNodes") or []),
                "turnCount": 1,
                "usage": deepcopy(usage),
            },
            "reviewRunId": review_run_id,
            "createdAt": NOW,
            "tenantId": "TENANT-DEFAULT",
        }
        repo.state["review_messages"].append(assistant_message)
        for sequence, (event_type, title, payload) in enumerate(
            [
                ("session.created", "AI复核会话已建立", {"currentTask": node["nodeName"]}),
                (
                    "agent.message.completed",
                    "AI复核助手已返回审查结果",
                    {"messageId": assistant_message["id"], "findingCount": len(drafts)},
                ),
            ],
            1,
        ):
            repo.state["review_session_events"].append(
                {
                    "id": f"RSEVT-{project.upper()}-{node_id:02d}-{sequence}",
                    "eventId": f"RSEVT-{project.upper()}-{node_id:02d}-{sequence}",
                    "schema": "review-event/v1",
                    "sessionId": session_id,
                    "projectId": project_id,
                    "nodeId": node_id,
                    "reviewRunId": review_run_id,
                    "sequence": sequence,
                    "eventType": event_type,
                    "title": title,
                    "payload": payload,
                    "createdAt": NOW,
                    "tenantId": "TENANT-DEFAULT",
                }
            )
        node_record = repo.node(project_id, node_id)
        if node_record:
            node_record["status"] = "待人工确认"


def import_audit_logs(project: str, targeting_project: dict[str, Any], reviewed_node_ids: list[int]) -> None:
    project_id = PROJECT_IDS[project]
    entries = [
        ("测试项目导入", "Project", project_id, None),
        ("原始文件上传完成", "DocumentBatch", f"{project_id}-FILES", None),
        ("MinerU OCR完成", "OcrBatch", f"{project_id}-OCR", None),
        ("Qwen文件分类完成", "ClassificationBatch", f"{project_id}-CLASSIFY", None),
        ("资料类型节点挂载完成", "MaterialTargeting", f"{project_id}-TARGET", None),
        ("施工资料提交监检", "Submission", f"SUB-{project.upper()}-001", None),
        ("AI缺项预审完成", "ReviewBatch", f"{project_id}-REVIEW", None),
    ]
    for index, (action, object_type, object_id, node_id) in enumerate(entries, 1):
        repo.state["audit_logs"].append(
            {
                "id": f"AUD-{project.upper()}-{index:03d}",
                "projectId": project_id,
                "nodeId": node_id,
                "action": action,
                "objectType": object_type,
                "objectId": object_id,
                "actorId": "SYSTEM-TEST-IMPORT",
                "actorName": "测试数据导入",
                "actorRole": "system",
                "result": "成功",
                "createdAt": NOW,
                "tenantId": "TENANT-DEFAULT",
            }
        )


def import_all() -> dict[str, Any]:
    before = {str(path): sha256(path) for path in source_paths()}
    # 内置演示用户由 demo USERS 提供，避免 fresh_state 中无密码哈希的同名记录遮蔽它。
    repo.state["users"] = [item for item in repo.state["users"] if item.get("username") != "inspection"]
    targeting = load(TARGETING_PATH)
    monitor = load(MONITOR_RESULTS_PATH)
    targeting_by_project = {item["project"]: item for item in targeting["projects"]}
    monitor_by_project = {item["project"]: item for item in monitor["projects"]}
    imported = []
    for project in ("test", "test2"):
        _, node_map = clone_project_scaffold(project)
        binding_ids, links_by_node = import_documents_and_bindings(project, targeting_by_project[project], node_map)
        import_submission(project, binding_ids)
        import_review_runs(project, monitor_by_project[project], links_by_node)
        reviewed_node_ids = monitor_by_project[project]["reviewedNodeIds"]
        import_audit_logs(project, targeting_by_project[project], reviewed_node_ids)
        for node_id, node in node_map.items():
            node["fileCount"] = sum(
                1
                for binding in repo.state["bindings"]
                if binding.get("projectId") == PROJECT_IDS[project] and int(binding.get("nodeId") or 0) == node_id
            )
        imported.append(
            {
                "project": project,
                "projectId": PROJECT_IDS[project],
                "name": PROJECT_NAMES[project],
                "fileCount": targeting_by_project[project]["fileCount"],
                "formalBindingNodeCount": len(targeting_by_project[project]["formalNodeIds"]),
                "reviewRunCount": len(reviewed_node_ids),
                "findingCount": sum(
                    len((node.get("platformReview") or {}).get("findingDrafts") or [])
                    for node in monitor_by_project[project]["nodes"]
                ),
            }
        )
    after = {str(path): sha256(path) for path in source_paths()}
    if before != after:
        raise RuntimeError("source_business_data_changed_during_import")
    manifest = {
        "schemaVersion": "inspection-test-project-import@1",
        "generatedAt": datetime.now().isoformat(),
        "inspectionAccount": "inspection / USER-INSPECTION-001 / 张工",
        "sourceBusinessDataImmutable": True,
        "sourceHashesVerified": True,
        "sourceHashCount": len(before),
        "projects": imported,
    }
    (OUTPUT / "inspection_import_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


MANIFEST = import_all()

if __name__ == "__main__":
    print(json.dumps(MANIFEST, ensure_ascii=False), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8000)
