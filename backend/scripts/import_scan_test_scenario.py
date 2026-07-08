from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.contracts.responses import server_time
from libs.db.repository import flush_state, load_state, repo, stable_doc_id
from libs.knowledge_indexing import (
    OFFLINE_EMBEDDING_MODEL,
    OFFLINE_VECTOR_DIMENSIONS,
    STANDARD_INDEX_VERSION,
    offline_hash_embeddings,
)
from libs.material_targeting import run_material_targeting


SCENARIO_TAG = "scan-test-scenario-v1"
DEFAULT_PROJECT_ID = "P-2026-GDLNG-002"
CONTRACTOR_USER = {"userId": "USER-CONTRACTOR-001", "org": "粤海安装工程有限公司", "name": "李工"}
NDT_USER = {"userId": "USER-NDT-001", "org": "粤检无损检测", "name": "王工"}
INSPECTION_REVIEWER = "张工"

FILE_MAPPINGS: dict[str, dict[str, Any]] = {
    "20260623104523.pdf": {
        "role": "contractor",
        "nodeId": 2,
        "requirementId": "REQ-02-01",
        "materialCategory": "施工单位许可资质",
        "materialTypeCode": "construction_license",
    },
    "20260623104555.pdf": {
        "role": "contractor",
        "nodeId": 12,
        "requirementId": "REQ-12-01",
        "materialCategory": "制造单位许可资质",
        "materialTypeCode": "manufacturing_license",
    },
    "20260623104703.pdf": {
        "role": "contractor",
        "nodeId": 16,
        "requirementId": "REQ-16-01",
        "materialCategory": "产品质量证明文件",
        "materialTypeCode": "quality_certificate",
    },
    "20260623104730.pdf": {
        "role": "contractor",
        "nodeId": 16,
        "requirementId": "REQ-16-01",
        "materialCategory": "产品质量证明文件",
        "materialTypeCode": "quality_certificate",
    },
    "20260623104828.pdf": {
        "role": "contractor",
        "nodeId": 16,
        "requirementId": "REQ-16-01",
        "materialCategory": "产品质量证明文件",
        "materialTypeCode": "quality_certificate",
    },
    "20260623105454.pdf": {
        "role": "contractor",
        "nodeId": 11,
        "requirementId": "REQ-11-01",
        "materialCategory": "施工组织设计",
        "materialTypeCode": "construction_organization_design",
    },
    "20260623105534.pdf": {
        "role": "contractor",
        "nodeId": 12,
        "requirementId": "REQ-12-01",
        "materialCategory": "制造单位许可资质",
        "materialTypeCode": "manufacturing_license",
    },
    "20260623105636.pdf": {
        "role": "ndt",
        "nodeId": 40,
        "requirementId": "REQ-40-01",
        "materialCategory": "无损检测报告",
        "materialTypeCode": "ndt_report",
    },
    "IMG_6508.heic": {
        "role": "contractor",
        "nodeId": 53,
        "requirementId": "REQ-53-02",
        "materialCategory": "管道安装材料表",
        "materialTypeCode": "design_document",
    },
    "IMG_6509.heic": {
        "role": "contractor",
        "nodeId": 1,
        "requirementId": "REQ-01-03",
        "materialCategory": "管道特性表",
        "materialTypeCode": "design_document",
    },
    "IMG_6510.heic": {
        "role": "contractor",
        "nodeId": 9,
        "requirementId": "REQ-09-01",
        "materialCategory": "管道及仪表流程图",
        "materialTypeCode": "design_document",
    },
    "IMG_6511.heic": {
        "role": "contractor",
        "nodeId": 6,
        "requirementId": "REQ-06-02",
        "materialCategory": "压力管道强度计算书",
        "materialTypeCode": "calculation_report",
    },
    "IMG_6512.heic": {
        "role": "contractor",
        "nodeId": 8,
        "requirementId": "REQ-08-01",
        "materialCategory": "工艺设计说明书",
        "materialTypeCode": "design_document",
    },
    "IMG_6513.heic": {
        "role": "contractor",
        "nodeId": 4,
        "requirementId": "REQ-04-01",
        "materialCategory": "设备一览表",
        "materialTypeCode": "design_document",
    },
    "IMG_6514.heic": {
        "role": "contractor",
        "nodeId": 4,
        "requirementId": "REQ-04-01",
        "materialCategory": "工艺设计说明书",
        "materialTypeCode": "design_document",
    },
    "IMG_6515.heic": {
        "role": "contractor",
        "nodeId": 4,
        "requirementId": "REQ-04-01",
        "materialCategory": "工艺设计说明书",
        "materialTypeCode": "design_document",
    },
    "IMG_6516.heic": {
        "role": "contractor",
        "nodeId": 1,
        "requirementId": "REQ-01-03",
        "materialCategory": "设计说明书",
        "materialTypeCode": "design_document",
    },
    "IMG_6517.heic": {
        "role": "contractor",
        "nodeId": 8,
        "requirementId": "REQ-08-01",
        "materialCategory": "工艺设计说明书",
        "materialTypeCode": "design_document",
    },
    "IMG_6518.heic": {
        "role": "contractor",
        "nodeId": 8,
        "requirementId": "REQ-08-01",
        "materialCategory": "工艺设计说明书",
        "materialTypeCode": "design_document",
    },
    "IMG_6519.heic": {
        "role": "contractor",
        "nodeId": 8,
        "requirementId": "REQ-08-01",
        "materialCategory": "工艺设计说明书",
        "materialTypeCode": "design_document",
    },
    "IMG_6520.heic": {
        "role": "contractor",
        "nodeId": 53,
        "requirementId": "REQ-53-02",
        "materialCategory": "综合材料表",
        "materialTypeCode": "design_document",
    },
    "IMG_6521.heic": {
        "role": "contractor",
        "nodeId": 53,
        "requirementId": "REQ-53-02",
        "materialCategory": "综合材料表",
        "materialTypeCode": "design_document",
    },
    "IMG_6522.heic": {
        "role": "contractor",
        "nodeId": 53,
        "requirementId": "REQ-53-02",
        "materialCategory": "综合材料表",
        "materialTypeCode": "design_document",
    },
    "IMG_6523.heic": {
        "role": "contractor",
        "nodeId": 53,
        "requirementId": "REQ-53-02",
        "materialCategory": "综合材料表",
        "materialTypeCode": "design_document",
    },
    "IMG_6524.heic": {
        "role": "contractor",
        "nodeId": 9,
        "requirementId": "REQ-09-01",
        "materialCategory": "配管平面图",
        "materialTypeCode": "design_document",
    },
    "IMG_6526.heic": {
        "role": "contractor",
        "nodeId": 4,
        "requirementId": "REQ-04-01",
        "materialCategory": "设计图纸",
        "materialTypeCode": "design_document",
    },
    "IMG_6527.heic": {
        "role": "contractor",
        "nodeId": 4,
        "requirementId": "REQ-04-01",
        "materialCategory": "设计图纸",
        "materialTypeCode": "design_document",
    },
    "IMG_6528.heic": {
        "role": "contractor",
        "nodeId": 4,
        "requirementId": "REQ-04-01",
        "materialCategory": "设计图纸",
        "materialTypeCode": "design_document",
    },
    "IMG_6529.heic": {
        "role": "contractor",
        "nodeId": 43,
        "requirementId": "REQ-43-02",
        "materialCategory": "设备及管道油漆保温一览表",
        "materialTypeCode": "design_document",
    },
    "IMG_6530.heic": {
        "role": "contractor",
        "nodeId": 1,
        "requirementId": "REQ-01-03",
        "materialCategory": "管道特性表",
        "materialTypeCode": "design_document",
    },
}


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def content_type_for(path: Path) -> str:
    if path.suffix.lower() == ".heic":
        return "image/heic"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def load_ocr_items(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(item.get("source_file") or ""): item for item in payload if item.get("source_file")}


def scan_files(scan_dir: Path) -> list[Path]:
    allowed = {".pdf", ".heic"}
    return sorted(
        [item for item in scan_dir.iterdir() if item.is_file() and item.suffix.lower() in allowed],
        key=lambda item: item.name,
    )


def requirement(project_id: str, requirement_id: str | None, node_id: int) -> dict[str, Any] | None:
    if requirement_id:
        item = next(
            (
                req
                for req in repo.state.get("requirements", [])
                if req.get("projectId") == project_id and req.get("id") == requirement_id
            ),
            None,
        )
        if item:
            return item
    return next(
        (
            req
            for req in repo.state.get("requirements", [])
            if req.get("projectId") == project_id and int(req.get("nodeId") or 0) == int(node_id)
        ),
        None,
    )


def find_document(project_id: str, file_name: str, hash_value: str, size: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    hash_key = f"sha256-{hash_value}"
    for version in repo.state.get("versions", []):
        if version.get("hash") != hash_key:
            continue
        document = repo.find_one("documents", str(version.get("documentId") or ""))
        if document and document.get("projectId") == project_id:
            return document, version
    for document in repo.state.get("documents", []):
        if document.get("projectId") != project_id or document.get("fileName") != file_name:
            continue
        version = repo.find_one("versions", str(document.get("currentVersionId") or ""))
        if version and int(version.get("fileSize") or 0) == size:
            return document, version
    return None, None


def remove_records_by_ids(collection: str, ids: set[str], id_field: str = "id") -> int:
    before = len(repo.state.get(collection, []))
    repo.state[collection] = [item for item in repo.state.get(collection, []) if str(item.get(id_field) or "") not in ids]
    return before - len(repo.state.get(collection, []))


def clear_prior_scan_flow(project_id: str, scan_file_names: set[str]) -> dict[str, int]:
    stats: dict[str, int] = defaultdict(int)
    scan_doc_ids = {
        str(doc.get("id"))
        for doc in repo.state.get("documents", [])
        if doc.get("projectId") == project_id
        and (doc.get("fileName") in scan_file_names or doc.get("scenarioTag") == SCENARIO_TAG)
    }
    scan_version_ids = {
        str(version.get("id"))
        for version in repo.state.get("versions", [])
        if version.get("documentId") in scan_doc_ids or version.get("scenarioTag") == SCENARIO_TAG
    }
    scan_file_ids = {
        str(file.get("id"))
        for file in repo.state.get("knowledge_files", [])
        if file.get("documentId") in scan_doc_ids or file.get("scenarioTag") == SCENARIO_TAG
    }

    binding_ids = {
        str(binding.get("id"))
        for binding in repo.state.get("bindings", [])
        if binding.get("projectId") == project_id
        and (binding.get("documentId") in scan_doc_ids or binding.get("scenarioTag") == SCENARIO_TAG)
    }
    stats["bindingsRemoved"] += remove_records_by_ids("bindings", binding_ids)

    report_ids = {
        str(report.get("id"))
        for report in repo.state.get("ndt_reports", [])
        if report.get("projectId") == project_id
        and (report.get("fileId") in scan_doc_ids or report.get("scenarioTag") == SCENARIO_TAG)
    }
    stats["ndtReportsRemoved"] += remove_records_by_ids("ndt_reports", report_ids)
    repo.state["ndt_records"] = [
        item
        for item in repo.state.get("ndt_records", [])
        if item.get("reportId") not in report_ids and item.get("scenarioTag") != SCENARIO_TAG
    ]
    repo.state["ndt_films"] = [item for item in repo.state.get("ndt_films", []) if item.get("scenarioTag") != SCENARIO_TAG]

    submission_ids = {
        str(submission.get("submissionId"))
        for submission in repo.state.get("submissions", [])
        if submission.get("projectId") == project_id
        and (
            submission.get("scenarioTag") == SCENARIO_TAG
            or bool(set(submission.get("bindingIds") or []) & binding_ids)
            or bool(set(submission.get("reportIds") or []) & report_ids)
        )
    }
    before = len(repo.state.get("submissions", []))
    repo.state["submissions"] = [
        item for item in repo.state.get("submissions", []) if str(item.get("submissionId") or "") not in submission_ids
    ]
    stats["submissionsRemoved"] += before - len(repo.state.get("submissions", []))

    todo_ids = {
        str(todo.get("id"))
        for todo in repo.state.get("todos", [])
        if todo.get("projectId") == project_id
        and (
            todo.get("scenarioTag") == SCENARIO_TAG
            or str(todo.get("targetId") or "") in submission_ids
            or str(todo.get("targetId") or "") in report_ids
        )
    }
    stats["todosRemoved"] += remove_records_by_ids("todos", todo_ids)

    stats["ocrJobsRemoved"] += remove_records_by_ids(
        "ocr_jobs",
        {
            str(job.get("id"))
            for job in repo.state.get("ocr_jobs", [])
            if job.get("documentVersionId") in scan_version_ids or job.get("scenarioTag") == SCENARIO_TAG
        },
    )
    stats["ocrParseResultsRemoved"] += remove_records_by_ids(
        "ocr_parse_results",
        {
            str(result.get("id") or result.get("parseResultId"))
            for result in repo.state.get("ocr_parse_results", [])
            if result.get("documentVersionId") in scan_version_ids or result.get("scenarioTag") == SCENARIO_TAG
        },
    )
    repo.state["extracted_fields"] = [
        item
        for item in repo.state.get("extracted_fields", [])
        if item.get("documentVersionId") not in scan_version_ids and item.get("scenarioTag") != SCENARIO_TAG
    ]
    repo.state["evidence_links"] = [
        item
        for item in repo.state.get("evidence_links", [])
        if item.get("documentVersionId") not in scan_version_ids and item.get("scenarioTag") != SCENARIO_TAG
    ]
    repo.state["knowledge_chunks"] = [
        item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") not in scan_file_ids
    ]
    repo.state["knowledge_vectors"] = [
        item for item in repo.state.get("knowledge_vectors", []) if item.get("fileId") not in scan_file_ids
    ]
    repo.state["knowledge_tasks"] = [
        item
        for item in repo.state.get("knowledge_tasks", [])
        if item.get("targetId") not in scan_file_ids and item.get("documentVersionId") not in scan_version_ids
    ]
    repo.state["ai_runs"] = [
        item
        for item in repo.state.get("ai_runs", [])
        if not (item.get("projectId") == project_id and item.get("scenarioTag") == SCENARIO_TAG)
    ]
    repo.state["review_findings"] = [
        item
        for item in repo.state.get("review_findings", [])
        if not (item.get("projectId") == project_id and item.get("scenarioTag") == SCENARIO_TAG)
    ]
    return dict(stats)


def scenario_node_ids() -> set[int]:
    return {int(item["nodeId"]) for item in FILE_MAPPINGS.values()}


def ensure_document_records(project_id: str, source_path: Path, mapping: dict[str, Any], upload_session_id: str) -> dict[str, Any]:
    data = source_path.read_bytes()
    hash_value = hashlib.sha256(data).hexdigest()
    size = len(data)
    file_name = source_path.name
    document, version = find_document(project_id, file_name, hash_value, size)
    seed = f"SCAN{hash_value[:8].upper()}"
    created = False
    project = repo.require_project(project_id) or {}
    role = mapping["role"]
    actor = NDT_USER if role == "ndt" else CONTRACTOR_USER
    if not document or not version:
        document, version, knowledge_file, knowledge_task = repo._build_document_records(  # type: ignore[attr-defined]
            project_id,
            file_name,
            content_type_for(source_path),
            source_org_name=actor["org"],
            uploader_name=actor["name"],
            material_category=mapping.get("materialCategory"),
            seed=seed,
        )
        repo._insert_document_records(document, version, knowledge_file, knowledge_task)  # type: ignore[attr-defined]
        created = True
    else:
        knowledge_file = repo.find_one("knowledge_files", f"KF-{document['id']}") or next(
            (
                item
                for item in repo.state.get("knowledge_files", [])
                if item.get("documentVersionId") == version.get("id")
            ),
            None,
        )
        if not knowledge_file:
            knowledge_file = {
                "id": f"KF-{document['id']}",
                "fileName": file_name,
                "sourceId": "KS-PROJECT-FILE",
                "sourceName": "项目文件知识库",
                "projectId": project_id,
                "projectName": project.get("name") or "",
                "documentId": document["id"],
                "documentVersionId": version["id"],
                "chunkCount": 0,
                "vectorCount": 0,
                "actions": ["knowledge:view", "knowledge:reindex"],
            }
            repo.state["knowledge_files"].insert(0, knowledge_file)

    target_dir = WORKSPACE_ROOT / "output" / "document_uploads" / project_id / upload_session_id / version["id"]
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / file_name
    if not target_path.exists() or hashlib.sha256(target_path.read_bytes()).hexdigest() != hash_value:
        shutil.copy2(source_path, target_path)
    storage_key = f"local://{target_path.relative_to(WORKSPACE_ROOT)}"
    now = server_time()
    document.update(
        {
            "projectId": project_id,
            "businessPackId": project.get("businessPackId"),
            "materialTypeCode": mapping.get("materialTypeCode") or "generic_review_material",
            "materialCategory": mapping.get("materialCategory"),
            "fileName": file_name,
            "fileType": content_type_for(source_path),
            "sourceOrgName": actor["org"],
            "uploaderName": actor["name"],
            "currentVersionId": version["id"],
            "fileStatus": "已上传",
            "currentOcrStatus": "排队中",
            "updatedAt": now,
            "scenarioTag": SCENARIO_TAG,
            "sourceRelativePath": str(source_path.relative_to(WORKSPACE_ROOT)),
            "actions": ["file:view", "file:bind", "file:preview", "file:download"],
        }
    )
    if role == "ndt":
        document["nodeId"] = int(mapping["nodeId"])
    version.update(
        {
            "documentId": document["id"],
            "versionNo": version.get("versionNo") or "V1",
            "hash": f"sha256-{hash_value}",
            "fileSize": size,
            "storageKey": storage_key,
            "storageBucket": "local",
            "ocrStatus": "排队中",
            "sliceStatus": "未切片",
            "vectorStatus": "未向量化",
            "uploaderName": actor["name"],
            "uploadTime": now,
            "isCurrent": True,
            "scenarioTag": SCENARIO_TAG,
        }
    )
    knowledge_file = repo.find_one("knowledge_files", f"KF-{document['id']}") or next(
        item for item in repo.state["knowledge_files"] if item.get("documentVersionId") == version["id"]
    )
    knowledge_file.update(
        {
            "fileName": file_name,
            "sourceId": "KS-PROJECT-FILE",
            "sourceName": "项目文件知识库",
            "projectId": project_id,
            "projectName": project.get("name") or "",
            "documentId": document["id"],
            "documentVersionId": version["id"],
            "materialCategory": mapping.get("materialCategory"),
            "ocrStatus": "排队中",
            "sliceStatus": "未切片",
            "vectorStatus": "待向量化",
            "updatedAt": now,
            "scenarioTag": SCENARIO_TAG,
            "sourceRelativePath": str(source_path.relative_to(WORKSPACE_ROOT)),
            "actions": ["knowledge:view", "knowledge:reindex"],
        }
    )
    if role == "ndt":
        knowledge_file["nodeId"] = int(mapping["nodeId"])
    repo.upsert_knowledge_task(
        task_type="ocr",
        target_id=knowledge_file["id"],
        target_name=file_name,
        document_id=document["id"],
        version_id=version["id"],
        status="排队中",
        progress=0,
    )["scenarioTag"] = SCENARIO_TAG
    return {
        "created": created,
        "document": document,
        "version": version,
        "knowledgeFile": knowledge_file,
        "targetPath": target_path,
        "storageKey": storage_key,
    }


def observations_for_page(page: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in page.get("observations") or [] if isinstance(item, dict) and str(item.get("text") or "").strip()]


def fragments_from_ocr(raw: dict[str, Any]) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    for page_index, page in enumerate(raw.get("pages") or [], start=1):
        page_no = int(page.get("source_page") or page.get("pageNo") or page_index)
        observations = observations_for_page(page)
        if observations:
            for observation in observations:
                fragments.append(
                    {
                        "pageNo": page_no,
                        "text": str(observation.get("text") or "").strip(),
                        "bbox": observation.get("boundingBox") or observation.get("bbox"),
                        "confidence": observation.get("confidence"),
                        "sourceMethod": observation.get("extraction_method") or "scan_ocr_import",
                        "ocrEngine": "macos_vision_ocr_v1",
                    }
                )
            continue
        text = str(page.get("text") or "").strip()
        if text:
            fragments.append(
                {
                    "pageNo": page_no,
                    "text": text,
                    "confidence": raw.get("avg_confidence"),
                    "sourceMethod": "scan_ocr_import",
                    "ocrEngine": "macos_vision_ocr_v1",
                }
            )
    return fragments


def all_ocr_text(raw: dict[str, Any]) -> str:
    return "\n".join(str(page.get("text") or "").strip() for page in raw.get("pages") or [] if str(page.get("text") or "").strip())


def extract_regex_field(text: str, label: str, patterns: list[str]) -> dict[str, Any] | None:
    import re

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            values = [group for group in match.groups() if group is not None]
            value = " 至 ".join(item.strip() for item in values if item.strip()) if len(values) > 1 else match.group(1).strip()
            return {"fieldName": label, "fieldValue": value, "pageNo": 1, "confidence": 0.8}
    return None


def fields_from_ocr(raw: dict[str, Any], mapping: dict[str, Any]) -> list[dict[str, Any]]:
    text = all_ocr_text(raw)
    fields: list[dict[str, Any]] = [
        {
            "fieldName": "资料类型",
            "fieldValue": mapping.get("materialCategory") or raw.get("knowledge_type") or raw.get("category") or "未分类",
            "pageNo": 1,
            "confidence": 0.9,
            "extractionMethod": "scan_ocr_import",
        },
        {
            "fieldName": "OCR分类依据",
            "fieldValue": str(raw.get("evidence") or raw.get("knowledge_type") or "")[:200],
            "pageNo": 1,
            "confidence": float(raw.get("avg_confidence") or 0.8),
            "extractionMethod": "scan_ocr_import",
        },
        {
            "fieldName": "页数",
            "fieldValue": str(raw.get("page_count") or len(raw.get("pages") or []) or 1),
            "pageNo": 1,
            "confidence": 1,
            "extractionMethod": "scan_ocr_import",
        },
    ]
    for field in [
        extract_regex_field(text, "项目名称", [r"项目名称[:：]\s*([^\n]{4,80})", r"工程名称[:：]\s*([^\n]{4,80})"]),
        extract_regex_field(text, "证书编号", [r"证书编号[:：]\s*([A-Z0-9\-]+)", r"编号[:：]\s*([A-Z]{1,4}[0-9][A-Z0-9\-]+)"]),
        extract_regex_field(text, "报告编号", [r"报告编号[:：]\s*([A-Z0-9\-]+)"]),
        extract_regex_field(text, "图号", [r"图号[:：]?\s*([A-ZQX0-9\-—_]{6,40})"]),
        extract_regex_field(text, "有效期至", [r"有效期至[:：]?\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)"]),
        extract_regex_field(text, "机构名称", [r"(?:单位名称|施工单位|安装单位)[:：]\s*([^\n]{4,80})"]),
        extract_regex_field(text, "许可范围", [r"((?:工业管道|压力管道)[^\n]{0,80}(?:GC1|GC2|GCD)[^\n]{0,40})"]),
        extract_regex_field(text, "管道级别", [r"(?:压力管道级别|管道级别)[:：为\s]*([A-Z0-9、,，/ ]{2,40})"]),
        extract_regex_field(text, "施工计划工期", [r"工期目标[:：]\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)[^\n]{0,20}(?:进场|开工)[^\n]{0,20}([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)[^\n]{0,20}(?:竣工|完工|验收)"]),
        extract_regex_field(text, "安装工期", [r"安装开工日期[:：]?\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)[\s\S]{0,80}安装竣工日期[:：]?\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)"]),
    ]:
        if field:
            field["extractionMethod"] = "scan_ocr_import"
            fields.append(field)
    return fields


def apply_ocr_and_index(document: dict[str, Any], version: dict[str, Any], raw: dict[str, Any], mapping: dict[str, Any], *, with_vectors: bool) -> dict[str, Any]:
    fragments = fragments_from_ocr(raw)
    result = {
        "parseResultId": f"PARSE-SCAN-{stable_doc_id(version['id'])[:12].upper()}",
        "storageKey": version.get("storageKey"),
        "fileName": document.get("fileName"),
        "status": "success",
        "profileId": "scan_import_v1",
        "documentType": raw.get("category") or mapping.get("materialTypeCode"),
        "parserVersion": "scan_ocr_classifier_v1",
        "engineVersion": "macos_vision_ocr_v1",
        "modelManifest": {"source": "output/ocr/raw_ocr_pages.json", "scenarioTag": SCENARIO_TAG},
        "engineRuns": [
            {
                "engine": "scan_ocr_import",
                "status": "success",
                "avgConfidence": raw.get("avg_confidence"),
                "pageCount": raw.get("page_count"),
            }
        ],
        "diagnostics": [],
        "pages": raw.get("pages") or [],
        "fragments": fragments,
        "fields": fields_from_ocr(raw, mapping),
        "quality": {
            "avgConfidence": raw.get("avg_confidence"),
            "lineCount": raw.get("line_count"),
            "charCount": raw.get("char_count"),
            "classification": raw.get("category"),
            "knowledgeType": raw.get("knowledge_type"),
        },
        "scenarioTag": SCENARIO_TAG,
    }
    job = repo.create_ocr_job_record(
        document_id=document["id"],
        version_id=version["id"],
        storage_key=version["storageKey"],
        file_name=document["fileName"],
        profile_id="scan_import_v1",
        document_type=str(result.get("documentType") or ""),
    )
    job["scenarioTag"] = SCENARIO_TAG
    parse_result = repo.finish_ocr_job_record(job, result)
    if parse_result:
        parse_result["scenarioTag"] = SCENARIO_TAG
    applied = repo.apply_ocr_result(document["id"], version["id"], result)
    targeting_result = run_material_targeting(
        repo,
        str(document["projectId"]),
        document["id"],
        version["id"],
        triggered_by="scan_import",
    )
    knowledge_file = repo.knowledge_file_for_version(version["id"])
    slice_result = {"status": "skipped", "chunkCount": 0}
    vector_result = {"status": "skipped", "vectorCount": 0}
    if knowledge_file:
        for task in repo.state.get("knowledge_tasks", []):
            if task.get("targetId") == knowledge_file["id"]:
                task["scenarioTag"] = SCENARIO_TAG
        slice_result = repo.apply_slice_result(knowledge_file["id"], fragments)
        if with_vectors and slice_result.get("status") == "success":
            chunks = sorted(
                [item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == knowledge_file["id"]],
                key=lambda item: int(item.get("chunkNo") or 0),
            )
            vectors = offline_hash_embeddings([str(item.get("text") or "") for item in chunks])
            vector_result = repo.apply_embed_result(
                knowledge_file["id"],
                vector_count=len(chunks),
                vectors=vectors,
                embedding_model=OFFLINE_EMBEDDING_MODEL,
                index_version=STANDARD_INDEX_VERSION,
                expected_dimensions=OFFLINE_VECTOR_DIMENSIONS,
                vector_status_reason="scan_test_import",
            )
        version["sliceStatus"] = knowledge_file.get("sliceStatus") or version.get("sliceStatus")
        version["vectorStatus"] = knowledge_file.get("vectorStatus") or version.get("vectorStatus")
        version["chunkCount"] = knowledge_file.get("chunkCount", 0)
        version["vectorCount"] = knowledge_file.get("vectorCount", 0)
        if knowledge_file.get("embeddingModel"):
            version["embeddingModel"] = knowledge_file.get("embeddingModel")
        if knowledge_file.get("indexVersion"):
            version["indexVersion"] = knowledge_file.get("indexVersion")
        for chunk in repo.state.get("knowledge_chunks", []):
            if chunk.get("fileId") == knowledge_file["id"]:
                chunk["scenarioTag"] = SCENARIO_TAG
        for vector in repo.state.get("knowledge_vectors", []):
            if vector.get("fileId") == knowledge_file["id"]:
                vector["scenarioTag"] = SCENARIO_TAG
    for field in repo.state.get("extracted_fields", []):
        if field.get("documentVersionId") == version["id"]:
            field["scenarioTag"] = SCENARIO_TAG
    for evidence in repo.state.get("evidence_links", []):
        if evidence.get("documentVersionId") == version["id"]:
            evidence["scenarioTag"] = SCENARIO_TAG
    return {"applied": applied, "targeting": targeting_result, "slice": slice_result, "vector": vector_result}


def ensure_binding(project_id: str, document: dict[str, Any], version: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    req = requirement(project_id, mapping.get("requirementId"), int(mapping["nodeId"]))
    binding_id = f"BIND-SCAN-{stable_doc_id(document['id'] + str(mapping['nodeId']))[:10].upper()}"
    existing = repo.find_one("bindings", binding_id)
    if not existing:
        existing = {
            "id": binding_id,
            "projectId": project_id,
            "nodeId": int(mapping["nodeId"]),
            "requirementId": (req or {}).get("id"),
            "requirementName": (req or {}).get("name"),
            "documentId": document["id"],
            "documentVersionId": version["id"],
            "fileName": document["fileName"],
            "versionNo": version.get("versionNo") or "V1",
            "usage": "原始提交" if mapping.get("role") == "contractor" else "检测报告",
            "sourceOrgName": document["sourceOrgName"],
            "bindingStatus": "已提交",
            "boundByName": document.get("uploaderName") or "李工",
            "boundAt": server_time(),
            "scenarioTag": SCENARIO_TAG,
            "actions": ["review:save", "review:return-correction"] if mapping.get("role") == "contractor" else ["ndt:submit"],
        }
        repo.state["bindings"].insert(0, existing)
    else:
        existing.update(
            {
                "nodeId": int(mapping["nodeId"]),
                "requirementId": (req or {}).get("id"),
                "requirementName": (req or {}).get("name"),
                "documentId": document["id"],
                "documentVersionId": version["id"],
                "fileName": document["fileName"],
                "sourceOrgName": document["sourceOrgName"],
                "bindingStatus": "已提交",
                "scenarioTag": SCENARIO_TAG,
            }
        )
    return existing


def make_upload_sessions(project_id: str, imported: list[dict[str, Any]]) -> None:
    for role in ("contractor", "ndt"):
        session_id = f"UPS-SCAN-{role.upper()}-V1"
        repo.state["upload_sessions"] = [item for item in repo.state.get("upload_sessions", []) if item.get("id") != session_id]
        actor = NDT_USER if role == "ndt" else CONTRACTOR_USER
        files = [
            {
                "documentId": item["document"]["id"],
                "documentVersionId": item["version"]["id"],
                "fileName": item["document"]["fileName"],
                "materialCategory": item["mapping"].get("materialCategory"),
                "storageBucket": "local",
                "storageKey": item["version"]["storageKey"],
                "status": "已上传",
                "fileSize": item["version"]["fileSize"],
                "contentType": item["document"]["fileType"],
                "uploadedAt": item["version"]["uploadTime"],
            }
            for item in imported
            if item["mapping"].get("role") == role
        ]
        if not files:
            continue
        repo.state["upload_sessions"].insert(
            0,
            {
                "id": session_id,
                "projectId": project_id,
                "status": "已完成",
                "files": files,
                "uploadToken": stable_doc_id(session_id),
                "createdAt": server_time(),
                "completedAt": server_time(),
                "expiresAt": server_time(),
                "scenarioTag": SCENARIO_TAG,
                "sourceOrgName": actor["org"],
                "uploaderName": actor["name"],
            },
        )


def ensure_role_member_scope(project_id: str, role: str, actor: dict[str, str], node_ids: set[int]) -> dict[str, Any]:
    desired_scope = sorted({int(item) for item in node_ids if int(item)})
    existing = next(
        (
            item
            for item in repo.state.get("project_members", [])
            if item.get("projectId") == project_id
            and item.get("role") == role
            and item.get("userId") == actor["userId"]
        ),
        None,
    )
    if existing is None:
        existing = {
            "id": f"PM-SCAN-{role.upper()}-{stable_doc_id(project_id + role)[:8].upper()}",
            "projectId": project_id,
            "userId": actor["userId"],
            "role": role,
            "status": "启用",
            "actions": repo.role_actions(role),
        }
        repo.state.setdefault("project_members", []).insert(0, existing)
    existing_scope = {int(item) for item in existing.get("nodeScope") or []}
    existing.update(
        {
            "name": actor["name"],
            "orgName": actor["org"],
            "nodeScope": sorted(existing_scope | set(desired_scope)),
            "actions": repo.role_actions(role),
            "status": "启用",
            "updatedAt": server_time(),
            "scenarioTag": SCENARIO_TAG,
        }
    )
    return existing


def create_contractor_submission(project_id: str, node_id: int, bindings: list[dict[str, Any]]) -> dict[str, Any]:
    submission_id = f"SUB-SCAN-{node_id}-{stable_doc_id('|'.join(sorted(item['id'] for item in bindings)))[:8].upper()}"
    snapshot_id = f"SNAP-{submission_id}"
    todo_id = f"TODO-SCAN-{node_id}-{stable_doc_id(submission_id)[:8].upper()}"
    changed = [repo.set_node_status(project_id, node_id, "待人工确认")]
    todo = {
        "id": todo_id,
        "title": f"节点 {node_id} 资料待人工确认",
        "projectId": project_id,
        "nodeId": node_id,
        "targetType": "submission",
        "targetId": submission_id,
        "status": "待处理",
        "priority": "高",
        "assigneeName": INSPECTION_REVIEWER,
        "actions": ["review:save", "ai:recheck"],
        "scenarioTag": SCENARIO_TAG,
    }
    repo.state["todos"].insert(0, todo)
    submission = {
        "submissionId": submission_id,
        "snapshotId": snapshot_id,
        "projectId": project_id,
        "nodeIds": [node_id],
        "bindingIds": [item["id"] for item in bindings],
        "batchName": f"Scan 测试资料提交 - 节点 {node_id}",
        "submitterComment": "由 Scan 离线资料迁移生成，施工方已完成上传并提交。",
        "nextStatus": "待人工确认",
        "submittedAt": server_time(),
        "createdTodoIds": [todo_id],
        "changed": changed,
        "createdBindingIds": [item["id"] for item in bindings],
        "scenarioTag": SCENARIO_TAG,
        "snapshot": {"bindings": [repo.clone(item) for item in bindings]},
    }
    repo.state["submissions"].insert(0, submission)
    input_versions = [item["documentVersionId"] for item in bindings]
    ai_run_id = f"AIRUN-SCAN-{node_id}-{stable_doc_id(submission_id)[:8].upper()}"
    repo.state["ai_runs"].insert(
        0,
        {
            "id": ai_run_id,
            "projectId": project_id,
            "nodeId": node_id,
            "subject": (repo.node(project_id, node_id) or {}).get("name") or f"节点 {node_id}",
            "model": "scan-import-offline-review",
            "promptVersion": f"scan-node-{node_id}-v1",
            "ruleVersion": "scan-test-fixture",
            "inputDocumentVersionIds": input_versions,
            "status": "待人工确认",
            "startedAt": server_time(),
            "finishedAt": server_time(),
            "steps": [
                {
                    "id": f"STEP-SCAN-{node_id}-001",
                    "title": "Scan OCR 结果导入",
                    "action": "导入已完成 OCR 的测试资料",
                    "conclusion": "待人工确认",
                    "evidenceLinkIds": [
                        item["id"]
                        for item in repo.state.get("evidence_links", [])
                        if item.get("documentVersionId") in set(input_versions)
                    ][:8],
                }
            ],
            "suggestion": {
                "id": f"AIS-SCAN-{node_id}-{stable_doc_id(submission_id)[:8].upper()}",
                "result": "需人工确认",
                "opinionDraft": "Scan 测试资料已完成 OCR 和证据入库，请监检人员核对原文、OCR 字段和节点资料要求。",
                "risks": ["离线 OCR 结果需人工确认", "HEIC 图纸类资料需核对原图可读性"],
                "confidence": 0.72,
                "manualConfirmItems": ["原文一致性", "OCR 字段", "资料项匹配"],
            },
            "evidenceLinks": [
                repo.clone(item)
                for item in repo.state.get("evidence_links", [])
                if item.get("documentVersionId") in set(input_versions)
            ][:12],
            "findingDrafts": [],
            "scenarioTag": SCENARIO_TAG,
        },
    )
    return submission


def create_ndt_submission(project_id: str, ndt_items: list[dict[str, Any]], ndt_bindings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not ndt_items:
        return None
    node_id = 40
    report_ids: list[str] = []
    for item in ndt_items:
        document = item["document"]
        report_id = f"NDT-RPT-SCAN-{stable_doc_id(document['id'])[:8].upper()}"
        report = {
            "id": report_id,
            "projectId": project_id,
            "nodeId": node_id,
            "reportNo": "2021SHZH-014RTBG-01",
            "entrustNo": "WT-SCAN-2021SHZH-014",
            "method": "RT",
            "detectionRatio": "10%",
            "standardCode": "NB/T 47013.2-2015",
            "evaluatorName": "王工",
            "reviewerName": "赵工",
            "fileId": document["id"],
            "relatedFilmIds": [],
            "status": "待审查",
            "conclusion": "Scan 导入射线检测报告，OCR 已完成，等待监检审查。",
            "uploadedAt": item["version"].get("uploadTime") or server_time(),
            "submittedAt": server_time(),
            "actions": ["ndt:submit", "review:save"],
            "scenarioTag": SCENARIO_TAG,
        }
        repo.state["ndt_reports"].insert(0, report)
        repo.state["ndt_records"].insert(
            0,
            {
                "id": f"NDT-REC-SCAN-{stable_doc_id(document['id'])[:8].upper()}",
                "projectId": project_id,
                "nodeId": node_id,
                "recordNo": "REC-RT-SCAN-001",
                "reportId": report_id,
                "weldNo": "W-SCAN-RT-001",
                "pipelineNo": "PL8301",
                "entrustNo": report["entrustNo"],
                "reportNo": report["reportNo"],
                "method": "RT",
                "testDate": "2021-04-01",
                "detectionRatio": report["detectionRatio"],
                "standardCode": report["standardCode"],
                "evaluatorName": report["evaluatorName"],
                "reviewerName": report["reviewerName"],
                "result": "合格",
                "evaluationLevel": "II",
                "signatureStatus": "待人工确认",
                "stampStatus": "待人工确认",
                "sampleStatus": "待审查",
                "conclusion": report["conclusion"],
                "importedAt": server_time(),
                "actions": ["ndt:record-import", "review:save"],
                "scenarioTag": SCENARIO_TAG,
            },
        )
        report_ids.append(report_id)

    submission_id = f"NDT-SUB-SCAN-{stable_doc_id('|'.join(report_ids))[:8].upper()}"
    todo_id = f"TODO-SCAN-NDT-{stable_doc_id(submission_id)[:8].upper()}"
    changed = [repo.set_node_status(project_id, node_id, "待审查")]
    todo = {
        "id": todo_id,
        "title": "无损检测资料待审查",
        "projectId": project_id,
        "nodeId": node_id,
        "targetType": "submission",
        "targetId": submission_id,
        "status": "待处理",
        "priority": "高",
        "assigneeName": INSPECTION_REVIEWER,
        "actions": ["review:save"],
        "scenarioTag": SCENARIO_TAG,
    }
    repo.state["todos"].insert(0, todo)
    submission = {
        "submissionId": submission_id,
        "snapshotId": f"SNAP-{submission_id}",
        "projectId": project_id,
        "nodeId": node_id,
        "nodeIds": [node_id],
        "submissionType": "ndt",
        "batchName": "Scan 无损检测资料提交",
        "submitterComment": "由 Scan 离线资料迁移生成，无损机构已完成上传并提交。",
        "nextStatus": "待审查",
        "submittedAt": server_time(),
        "createdTodoIds": [todo_id],
        "reportIds": report_ids,
        "filmIds": [],
        "bindingIds": [item["id"] for item in ndt_bindings],
        "changed": changed,
        "scenarioTag": SCENARIO_TAG,
        "snapshot": {
            "reports": [repo.clone(report) for report in repo.state["ndt_reports"] if report.get("id") in set(report_ids)],
            "films": [],
            "records": [repo.clone(record) for record in repo.state["ndt_records"] if record.get("reportId") in set(report_ids)],
        },
    }
    repo.state["submissions"].insert(0, submission)
    return submission


def refresh_knowledge_source_counts() -> None:
    source = repo.find_one("knowledge_sources", "KS-PROJECT-FILE")
    if not source:
        return
    file_ids = {item["id"] for item in repo.state.get("knowledge_files", []) if item.get("sourceId") == "KS-PROJECT-FILE"}
    source["fileCount"] = len(file_ids)
    source["chunkCount"] = len([item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") in file_ids])
    source["vectorStatus"] = "已向量化"
    source["updatedAt"] = server_time()


def build_plan(scan_dir: Path, raw_ocr: dict[str, dict[str, Any]], project_id: str) -> list[dict[str, Any]]:
    plan = []
    for path in scan_files(scan_dir):
        mapping = FILE_MAPPINGS.get(path.name)
        raw = raw_ocr.get(path.name)
        if not mapping:
            plan.append({"file": path.name, "status": "skipped", "reason": "没有映射规则"})
            continue
        if not raw:
            plan.append({"file": path.name, "status": "skipped", "reason": "没有 OCR 结果"})
            continue
        hash_value = sha256_file(path)
        document, version = find_document(project_id, path.name, hash_value, path.stat().st_size)
        req = requirement(project_id, mapping.get("requirementId"), int(mapping["nodeId"]))
        plan.append(
            {
                "file": path.name,
                "status": "ready",
                "role": mapping["role"],
                "nodeId": mapping["nodeId"],
                "requirementId": (req or {}).get("id"),
                "requirementName": (req or {}).get("name"),
                "materialCategory": mapping.get("materialCategory"),
                "existingDocumentId": (document or {}).get("id"),
                "existingVersionId": (version or {}).get("id"),
                "ocrPages": raw.get("page_count"),
                "ocrCategory": raw.get("category"),
            }
        )
    return plan


def print_plan(plan: list[dict[str, Any]]) -> None:
    print("file\trole\tnode\trequirement\tmaterial\texisting\tocr")
    for item in plan:
        if item["status"] != "ready":
            print(f"{item['file']}\t-\t-\t-\t-\t{item['status']}\t{item['reason']}")
            continue
        existing = item.get("existingDocumentId") or "NEW"
        print(
            f"{item['file']}\t{item['role']}\t{item['nodeId']}\t{item.get('requirementName') or item.get('requirementId')}\t"
            f"{item['materialCategory']}\t{existing}\t{item.get('ocrCategory')}:{item.get('ocrPages')}p"
        )


def apply_import(scan_dir: Path, raw_ocr: dict[str, dict[str, Any]], project_id: str, *, with_vectors: bool) -> dict[str, Any]:
    clear_stats = clear_prior_scan_flow(project_id, set(raw_ocr.keys()))
    imported: list[dict[str, Any]] = []
    bindings_by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in scan_files(scan_dir):
        mapping = FILE_MAPPINGS.get(path.name)
        raw = raw_ocr.get(path.name)
        if not mapping or not raw:
            continue
        upload_session_id = f"UPS-SCAN-{mapping['role'].upper()}-V1"
        records = ensure_document_records(project_id, path, mapping, upload_session_id)
        apply_ocr_and_index(records["document"], records["version"], raw, mapping, with_vectors=with_vectors)
        binding = ensure_binding(project_id, records["document"], records["version"], mapping)
        imported.append({**records, "mapping": mapping, "ocr": raw, "binding": binding})
        bindings_by_role[mapping["role"]].append(binding)
    make_upload_sessions(project_id, imported)

    contractor_by_node: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for binding in bindings_by_role.get("contractor", []):
        contractor_by_node[int(binding["nodeId"])].append(binding)
    contractor_submissions = [
        create_contractor_submission(project_id, node_id, bindings)
        for node_id, bindings in sorted(contractor_by_node.items())
        if bindings
    ]
    ndt_items = [item for item in imported if item["mapping"].get("role") == "ndt"]
    ndt_submission = create_ndt_submission(project_id, ndt_items, bindings_by_role.get("ndt", []))
    contractor_member = ensure_role_member_scope(
        project_id,
        "contractor",
        CONTRACTOR_USER,
        {int(item["nodeId"]) for item in bindings_by_role.get("contractor", [])},
    )
    ndt_member = ensure_role_member_scope(
        project_id,
        "ndt",
        NDT_USER,
        {int(item["nodeId"]) for item in bindings_by_role.get("ndt", [])},
    )
    refresh_knowledge_source_counts()
    project = repo.require_project(project_id)
    if project:
        project["status"] = "在监检审查中"
        project["currentNodeId"] = 40 if ndt_submission else (contractor_submissions[0]["nodeIds"][0] if contractor_submissions else project.get("currentNodeId"))
        project["updatedAt"] = server_time()
        project["scenarioTag"] = SCENARIO_TAG
    return {
        "clear": clear_stats,
        "importedFiles": len(imported),
        "contractorSubmissions": len(contractor_submissions),
        "ndtSubmission": bool(ndt_submission),
        "bindings": len([item for values in bindings_by_role.values() for item in values]),
        "roleScopes": {
            "contractor": contractor_member.get("nodeScope", []),
            "ndt": ndt_member.get("nodeScope", []),
        },
    }


def backup_sqlite() -> Path | None:
    if not repo.sqlite_path:
        return None
    source = Path(repo.sqlite_path)
    if not source.exists():
        return None
    backup = source.with_suffix(source.suffix + f".bak-{server_time().replace(':', '').replace(' ', '-')}")
    shutil.copy2(source, backup)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Scan files and OCR output as a complete review-ready test scenario.")
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--scan-dir", default=str(WORKSPACE_ROOT / "Scan"))
    parser.add_argument("--ocr-json", default=str(WORKSPACE_ROOT / "output" / "ocr" / "raw_ocr_pages.json"))
    parser.add_argument("--apply", action="store_true", help="Write changes. Default is dry-run.")
    parser.add_argument("--skip-vectors", action="store_true", help="Do not generate offline vectors.")
    parser.add_argument("--no-backup", action="store_true", help="Do not back up SQLite before apply.")
    args = parser.parse_args()

    scan_dir = Path(args.scan_dir).resolve()
    ocr_json = Path(args.ocr_json).resolve()
    if not scan_dir.is_dir():
        raise SystemExit(f"Scan directory not found: {scan_dir}")
    if not ocr_json.is_file():
        raise SystemExit(f"OCR JSON not found: {ocr_json}")

    load_state()
    raw_ocr = load_ocr_items(ocr_json)
    plan = build_plan(scan_dir, raw_ocr, args.project_id)
    print_plan(plan)
    ready_count = len([item for item in plan if item.get("status") == "ready"])
    print(f"\nready={ready_count} skipped={len(plan) - ready_count} project={args.project_id} scenarioTag={SCENARIO_TAG}")
    if not args.apply:
        print("dry-run only; rerun with --apply to write.")
        return 0

    backup = None if args.no_backup else backup_sqlite()
    if backup:
        print(f"sqliteBackup={backup}")
    result = apply_import(scan_dir, raw_ocr, args.project_id, with_vectors=not args.skip_vectors)
    flush_state()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
