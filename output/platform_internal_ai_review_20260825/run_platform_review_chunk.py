from __future__ import annotations

import argparse
import json
import os
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


WORKTREE = Path("/Volumes/7up/github/knowledgetools/.worktrees/qwen-auto-gold-classification")
BACKEND = WORKTREE / "backend"
MAIN_ROOT = Path("/Volumes/7up/github/knowledgetools")


def configure_environment() -> None:
    load_dotenv(MAIN_ROOT / "backend" / ".env", override=True)
    for key in ("AICHECK_DATABASE_URL", "DATABASE_URL", "AICHECK_SQLITE_PATH"):
        os.environ.pop(key, None)
    os.environ.update(
        {
            "AICHECK_SQLITE_DISABLE": "true",
            "AICHECK_ENABLE_DEMO_DATA": "true",
            "AICHECK_ENABLE_COMPATIBILITY_MOCKS": "true",
            "AICHECK_REQUIRE_AUTH": "false",
            "AICHECK_REQUIRE_IF_MATCH": "false",
            "AICHECK_STRICT_PRODUCTION": "false",
            "AICHECK_REVIEW_ORCHESTRATION": "inline",
            "AICHECK_REVIEW_LLM_EXECUTION": "litellm",
            "AICHECK_AUDIT_INPUT_MODE": "ocr_llm",
            "AICHECK_LANGGRAPH_CHECKPOINT_DISABLE": "true",
        }
    )


configure_environment()
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402
from libs.db.repository import repo  # noqa: E402


BASE_PROJECT_ID = "P-2026-HDCP-001"
HEADERS = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def chunks(text: str, size: int = 1800) -> list[str]:
    normalized = re.sub(r"\n{4,}", "\n\n", text).strip()
    if not normalized:
        return []
    parts: list[str] = []
    cursor = 0
    while cursor < len(normalized):
        end = min(len(normalized), cursor + size)
        if end < len(normalized):
            split = max(normalized.rfind("\n", cursor, end), normalized.rfind("。", cursor, end))
            if split > cursor + size // 2:
                end = split + 1
        part = normalized[cursor:end].strip()
        if part:
            parts.append(part)
        cursor = end
    return parts


def ocr_text(project: str, case_id: str) -> str:
    roots = {
        "test": MAIN_ROOT / "output" / "test_qwen_classification_20260824" / "ocr",
        "test2": MAIN_ROOT / "output" / "two_project_node_eval_20260824" / "test2" / "ocr",
    }
    root = roots[project]
    for suffix in (".md", ".office.txt"):
        path = root / f"{case_id}{suffix}"
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
    return ""


def clear_base_project_materials() -> None:
    project_document_ids = {
        str(item.get("id"))
        for item in repo.state.get("documents", [])
        if str(item.get("projectId")) == BASE_PROJECT_ID
    }
    project_version_ids = {
        str(item.get("id"))
        for item in repo.state.get("versions", [])
        if str(item.get("documentId")) in project_document_ids
    }
    for collection in (
        "documents",
        "bindings",
        "node_evidence_links",
        "ai_runs",
        "review_runs",
        "review_step_runs",
        "review_graph_nodes",
        "review_tool_calls",
        "review_events",
        "retrieval_traces",
        "rule_check_results",
        "review_findings",
        "model_call_attempts",
        "ai_trace_steps",
    ):
        repo.state[collection] = [
            item
            for item in repo.state.get(collection, [])
            if str(item.get("projectId") or "") != BASE_PROJECT_ID
        ]
    repo.state["versions"] = [
        item for item in repo.state.get("versions", []) if str(item.get("id")) not in project_version_ids
    ]
    for collection in ("ocr_parse_results", "extracted_fields", "evidence_links"):
        repo.state[collection] = [
            item
            for item in repo.state.get(collection, [])
            if str(item.get("documentVersionId") or "") not in project_version_ids
        ]


def requirement_for(node_id: int, material_codes: list[str]) -> dict[str, Any]:
    rows = [
        item
        for item in repo.state.get("requirements", [])
        if str(item.get("projectId")) == BASE_PROJECT_ID and int(item.get("nodeId") or 0) == node_id
    ]
    return next(
        (item for item in rows if str(item.get("materialTypeCode") or "") in set(material_codes)),
        rows[0] if rows else {},
    )


def seed_project(project: str, targeting: dict[str, Any]) -> dict[str, Any]:
    clear_base_project_materials()
    project_record = repo.require_project(BASE_PROJECT_ID)
    project_record["name"] = f"{project} OCR+LLM分类挂载验证项目"
    project_record["code"] = f"PLATFORM-REVIEW-{project.upper()}"
    project_record["status"] = "监检审查中"
    target = next(item for item in targeting["projects"] if item["project"] == project)
    seeded_files: list[dict[str, Any]] = []
    for index, file in enumerate(target["files"], 1):
        case_id = str(file["caseId"])
        document_id = f"DOC-{project.upper()}-{index:03d}"
        version_id = f"DV-{project.upper()}-{index:03d}-V1"
        material_codes = [str(value) for value in file.get("predictedMaterialTypeCodes") or []]
        repo.state["documents"].append(
            {
                "id": document_id,
                "projectId": BASE_PROJECT_ID,
                "fileName": Path(str(file.get("relativePath") or case_id)).name,
                "fileType": Path(str(file.get("relativePath") or "file.pdf")).suffix.lstrip(".") or "pdf",
                "currentVersionId": version_id,
                "fileStatus": "已上传",
                "currentOcrStatus": "已识别",
                "sliceStatus": "已切片",
                "vectorStatus": "已向量化",
                "materialTypeCode": material_codes[0] if material_codes else None,
                "materialTypeCodes": material_codes,
                "classificationSource": "qwen_auto_gold",
                "sourceCaseId": case_id,
                "tenantId": "TENANT-DEFAULT",
            }
        )
        repo.state["versions"].append(
            {
                "id": version_id,
                "documentId": document_id,
                "versionNo": "V1",
                "hash": f"sha256:{project}:{case_id}",
                "storageKey": f"validation/{project}/{case_id}",
                "ocrStatus": "已识别",
                "sliceStatus": "已切片",
                "vectorStatus": "已向量化",
                "isCurrent": True,
                "tenantId": "TENANT-DEFAULT",
            }
        )
        text_parts = chunks(ocr_text(project, case_id))
        fragments = []
        for part_no, part in enumerate(text_parts, 1):
            bbox = [40, 80 + (part_no % 8) * 90, 1160, 150 + (part_no % 8) * 90]
            fragments.append(
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
                    "id": f"EV-{project.upper()}-{index:03d}-{part_no:03d}",
                    "objectType": "ocr_fragment",
                    "objectId": f"PARSE-{project.upper()}-{index:03d}",
                    "documentId": document_id,
                    "documentVersionId": version_id,
                    "fileName": Path(str(file.get("relativePath") or case_id)).name,
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
                "documentId": document_id,
                "documentVersionId": version_id,
                "status": "success",
                "sourceMethod": "mineru_markdown_import",
                "fragments": fragments,
                "fields": [],
                "tables": [],
                "seals": [],
                "quality": {"reviewRequired": False, "source": "offline_mineru_markdown"},
                "tenantId": "TENANT-DEFAULT",
            }
        )
        formal_nodes = [int(value) for value in file.get("formalNodeIds") or []]
        for node_id in formal_nodes:
            requirement = requirement_for(node_id, material_codes)
            binding_id = f"BIND-{project.upper()}-{index:03d}-{node_id:02d}"
            repo.state["bindings"].append(
                {
                    "id": binding_id,
                    "projectId": BASE_PROJECT_ID,
                    "nodeId": node_id,
                    "requirementId": requirement.get("id"),
                    "requirementName": requirement.get("name"),
                    "documentId": document_id,
                    "documentVersionId": version_id,
                    "fileName": Path(str(file.get("relativePath") or case_id)).name,
                    "versionNo": "V1",
                    "usage": "OCR+LLM自动分类挂载",
                    "bindingStatus": "已提交",
                    "boundByName": "Qwen自动分类",
                    "tenantId": "TENANT-DEFAULT",
                }
            )
            first_part = text_parts[0] if text_parts else ""
            repo.state["node_evidence_links"].append(
                {
                    "id": f"NEL-{project.upper()}-{index:03d}-{node_id:02d}",
                    "projectId": BASE_PROJECT_ID,
                    "nodeId": node_id,
                    "nodeName": (repo.node(BASE_PROJECT_ID, node_id) or {}).get("name"),
                    "reviewPointId": requirement.get("id"),
                    "reviewContent": requirement.get("note") or requirement.get("name"),
                    "materialTypeCode": material_codes[0] if material_codes else None,
                    "materialTypeCodes": material_codes,
                    "materialTypeName": requirement.get("name"),
                    "requiredType": requirement.get("requiredType") or "必传",
                    "documentId": document_id,
                    "documentVersionId": version_id,
                    "fileName": Path(str(file.get("relativePath") or case_id)).name,
                    "pageNo": 1,
                    "bbox": [40, 80, 1160, 150],
                    "fieldName": "OCR Markdown",
                    "quotedText": first_part[:1000],
                    "matchedEvidenceItems": [first_part[:200]] if first_part else [],
                    "supportStatus": "supported",
                    "confidence": 0.9,
                    "manualStatus": "pending",
                    "source": "qwen_classification_formal_binding",
                    "tenantId": "TENANT-DEFAULT",
                }
            )
        seeded_files.append(
            {
                "caseId": case_id,
                "documentId": document_id,
                "documentVersionId": version_id,
                "materialTypeCodes": material_codes,
                "formalNodeIds": formal_nodes,
                "fragmentCount": len(text_parts),
            }
        )
    for node in repo.state.get("tree_nodes", []):
        if str(node.get("projectId")) != BASE_PROJECT_ID:
            continue
        node_id = int(node.get("nodeId") or 0)
        node["status"] = "待审查" if any(int(binding["nodeId"]) == node_id for binding in repo.state["bindings"]) else "待提交"
        node["fileCount"] = sum(1 for binding in repo.state["bindings"] if int(binding["nodeId"]) == node_id)
    return {"fileCount": len(seeded_files), "files": seeded_files}


def assert_ok(response: Any) -> dict[str, Any]:
    payload = response.json()
    if response.status_code != 200 or payload.get("code") != 0:
        raise RuntimeError(f"api_failed status={response.status_code} payload={payload}")
    return payload["data"]


def visible_result(project: str, node_id: int, response_data: dict[str, Any]) -> dict[str, Any]:
    ai_run = repo.find_one("ai_runs", str(response_data["runId"])) or response_data.get("latestRun") or {}
    review_run_id = str(ai_run.get("reviewRunId") or (response_data.get("dispatch") or {}).get("reviewRunId") or "")
    review_run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") if review_run_id else None
    attempts = [
        item
        for item in repo.state.get("model_call_attempts", [])
        if str(item.get("reviewRunId") or "") == review_run_id
    ]
    graph_nodes = [
        item
        for item in repo.state.get("review_graph_nodes", [])
        if str(item.get("reviewRunId") or "") == review_run_id
    ]
    return {
        "project": project,
        "platformProjectId": BASE_PROJECT_ID,
        "nodeId": node_id,
        "nodeName": (repo.node(BASE_PROJECT_ID, node_id) or {}).get("name"),
        "runId": ai_run.get("id"),
        "reviewRunId": review_run_id or None,
        "status": (review_run or {}).get("status") or ai_run.get("status"),
        "errorCode": (review_run or {}).get("errorCode") or ai_run.get("errorCode"),
        "errorMessage": (review_run or {}).get("errorMessage") or ai_run.get("errorMessage"),
        "currentStep": (review_run or {}).get("currentStep"),
        "reviewMode": ai_run.get("reviewMode"),
        "advisoryOnly": ai_run.get("advisoryOnly"),
        "suggestion": deepcopy(ai_run.get("suggestion") or {}),
        "findingDrafts": deepcopy((review_run or {}).get("findingDrafts") or ai_run.get("findingDrafts") or []),
        "qualityGate": deepcopy((review_run or {}).get("qualityGate") or {}),
        "evidenceBudget": deepcopy((review_run or {}).get("evidenceBudget") or ai_run.get("evidenceBudget") or {}),
        "inputDocumentVersionIds": deepcopy((review_run or {}).get("inputDocumentVersionIds") or ai_run.get("inputDocumentVersionIds") or []),
        "model": ((review_run or {}).get("llmMetadata") or ai_run.get("llmMetadata") or {}).get("modelResolved"),
        "usage": deepcopy(((review_run or {}).get("llmMetadata") or ai_run.get("llmMetadata") or {}).get("usage") or {}),
        "modelAttempts": [
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "model": item.get("model"),
                "usage": item.get("usage"),
                "usageNormalized": item.get("usageNormalized"),
                "failureReason": item.get("failureReason"),
            }
            for item in attempts
        ],
        "graphNodes": [
            {
                "nodeKey": item.get("nodeKey"),
                "status": item.get("status"),
                "details": deepcopy(item.get("details") or {}),
            }
            for item in graph_nodes
        ],
        "dispatch": deepcopy(response_data.get("dispatch") or {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", choices=("test", "test2"), required=True)
    parser.add_argument("--nodes", required=True, help="comma-separated node ids")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    node_ids = [int(value) for value in args.nodes.split(",") if value.strip()]
    targeting = load_json(MAIN_ROOT / "output" / "two_project_node_eval_20260824" / "node_targeting_results.json")
    seeded = seed_project(args.project, targeting)
    results: list[dict[str, Any]] = []
    with TestClient(app) as client:
        for index, node_id in enumerate(node_ids, 1):
            print(f"[{args.project}] node {node_id} ({index}/{len(node_ids)}) starting", flush=True)
            try:
                data = assert_ok(
                    client.post(
                        f"/api/projects/{BASE_PROJECT_ID}/inspection/nodes/{node_id}/ai-recheck",
                        json={"reviewMode": "gap_precheck", "auditInputMode": "ocr_llm"},
                        headers={**HEADERS, "Idempotency-Key": f"platform-{args.project}-{node_id}"},
                    )
                )
                result = visible_result(args.project, node_id, data)
                print(
                    f"[{args.project}] node {node_id} status={result['status']} findings={len(result['findingDrafts'])} model={result['model']}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001
                result = {
                    "project": args.project,
                    "platformProjectId": BASE_PROJECT_ID,
                    "nodeId": node_id,
                    "nodeName": (repo.node(BASE_PROJECT_ID, node_id) or {}).get("name"),
                    "status": "failed_to_start",
                    "errorType": type(exc).__name__,
                    "errorMessage": str(exc)[:1000],
                }
                print(f"[{args.project}] node {node_id} ERROR {result['errorMessage']}", flush=True)
            results.append(result)
    payload = {
        "schemaVersion": "platform-internal-ai-review-chunk@1",
        "project": args.project,
        "reviewMode": "gap_precheck",
        "auditInputMode": "ocr_llm",
        "platformFlow": "POST /projects/{projectId}/inspection/nodes/{nodeId}/ai-recheck -> ReviewRun -> LangGraph -> Qwen -> grounding guardrails",
        "seeded": seeded,
        "requestedNodeIds": node_ids,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
