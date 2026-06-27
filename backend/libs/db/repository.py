from __future__ import annotations

import asyncio
import hashlib
import json
import os
from copy import deepcopy
from datetime import timedelta
from typing import Any
from uuid import uuid4

from libs.contracts.responses import server_time
from libs.integrations.storage import object_storage

from .seed import PROJECT_ID, ROLE_ACTIONS, ROLE_NODE_MAP, fresh_state


STATE_COLLECTIONS = {
    "projects": "projects",
    "tree_nodes": "project_nodes",
    "requirements": "node_requirements",
    "documents": "documents",
    "versions": "document_versions",
    "bindings": "node_bindings",
    "evidence_links": "evidence_links",
    "extracted_fields": "extracted_fields",
    "ai_runs": "ai_runs",
    "review_opinions": "review_opinions",
    "reports": "reports",
    "archive_items": "archive_items",
    "export_tasks": "export_tasks",
    "ndt_films": "ndt_films",
    "ndt_records": "ndt_records",
    "ndt_reports": "ndt_reports",
    "ndt_feedback": "ndt_feedback",
    "todos": "todos",
    "messages": "messages",
    "knowledge_sources": "knowledge_sources",
    "knowledge_files": "knowledge_files",
    "knowledge_tasks": "knowledge_tasks",
    "knowledge_chunks": "knowledge_chunks",
    "rule_versions": "rule_versions",
    "llm_compare_runs": "llm_compare_runs",
    "project_members": "project_members",
    "users": "users",
    "roles": "roles",
    "submission_drafts": "submission_drafts",
    "submissions": "submissions",
    "rectifications": "rectifications",
    "upload_sessions": "upload_sessions",
    "audit_logs": "audit_logs",
}

SINGLETON_COLLECTIONS = {
    "admin_config": "admin_configs",
    "knowledge_config": "knowledge_configs",
}

IDEMPOTENCY_COLLECTION = "idempotency_keys"


def mongo_transactions_enabled() -> bool:
    return os.getenv("AICHECK_MONGO_TRANSACTIONS", "false").lower() == "true"


class InMemoryRepository:
    def __init__(self) -> None:
        self.state = fresh_state()
        self.state.setdefault("knowledge_chunks", [])
        self.state.setdefault("upload_sessions", [])
        self.mongo = None
        self.sync_mongo = None
        self.mongo_enabled = False
        self._flush_lock = asyncio.Lock()

    def reset(self) -> None:
        self.state = fresh_state()
        self.state.setdefault("knowledge_chunks", [])
        self.state.setdefault("upload_sessions", [])

    def clone(self, value: Any) -> Any:
        return deepcopy(value)

    def list(self, collection: str) -> list[dict[str, Any]]:
        return self.state[collection]

    def find_one(self, collection: str, object_id: str, id_field: str = "id") -> dict[str, Any] | None:
        return next((item for item in self.state[collection] if item.get(id_field) == object_id), None)

    def require_project(self, project_id: str) -> dict[str, Any] | None:
        return self.find_one("projects", project_id)

    def role_actions(self, role: str) -> list[str]:
        return list(ROLE_ACTIONS.get(role, ROLE_ACTIONS["inspection"]))

    def project_for_role(self, project: dict[str, Any], role: str) -> dict[str, Any]:
        cloned = self.clone(project)
        cloned["currentNodeId"] = ROLE_NODE_MAP.get(role, project.get("currentNodeId", 24))
        cloned["riskLevel"] = self.project_risk_level(project["id"])
        if project.get("status") == "已归档":
            cloned["actions"] = ["project:view", "archive:view", "archive:download"]
        else:
            cloned["actions"] = self.role_actions(role)
        return cloned

    def project_risk_level(self, project_id: str) -> str:
        if any(item.get("projectId") == project_id and item.get("status") == "失败" for item in self.state["ai_runs"]):
            return "高"
        if any(item.get("projectId") == project_id and item.get("status") == "失败" for item in self.state["export_tasks"]):
            return "高"
        failed_knowledge_task_project_ids = {
            (self.find_one("knowledge_files", item.get("targetId")) or {}).get("projectId")
            for item in self.state["knowledge_tasks"]
            if item.get("status") == "失败"
        }
        if project_id in failed_knowledge_task_project_ids:
            return "高"
        project_nodes = [item for item in self.state["tree_nodes"] if item.get("projectId") == project_id]
        risky_statuses = {"需补正", "退回补正中", "识别失败", "失败"}
        if any(item.get("status") in risky_statuses for item in project_nodes):
            return "高"
        if any(item.get("projectId") == project_id and item.get("status") == "待反馈" for item in self.state["rectifications"]):
            return "高"
        if any(item.get("projectId") == project_id and item.get("status") == "待反馈" for item in self.state["ndt_feedback"]):
            return "高"
        pending_statuses = {"待提交", "待审查", "AI 预审中", "复审中", "报告生成/复核中", "部分提交"}
        if any(item.get("status") in pending_statuses for item in project_nodes):
            return "中"
        project = self.require_project(project_id)
        if project and (int(project.get("todoCount") or 0) > 0 or int(project.get("messageCount") or 0) > 0):
            return "中"
        return "低"

    def node(self, project_id: str, node_id: int) -> dict[str, Any] | None:
        return next(
            (
                node
                for node in self.state["tree_nodes"]
                if node["projectId"] == project_id and int(node["nodeId"]) == int(node_id)
            ),
            None,
        )

    def node_groups(self, project_id: str) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        for node in [item for item in self.state["tree_nodes"] if item["projectId"] == project_id]:
            group = next((item for item in groups if item["groupName"] == node["groupName"]), None)
            if not group:
                group = {"groupName": node["groupName"], "nodes": []}
                groups.append(group)
            group["nodes"].append(self.clone(node))
        return groups

    def project_documents(self, project_id: str) -> list[dict[str, Any]]:
        return [self.clone(item) for item in self.state["documents"] if item["projectId"] == project_id]

    def versions_for_document(self, document_id: str) -> list[dict[str, Any]]:
        return [self.clone(item) for item in self.state["versions"] if item["documentId"] == document_id]

    def current_version(self, document_id: str) -> dict[str, Any] | None:
        return next((item for item in self.versions_for_document(document_id) if item.get("isCurrent")), None)

    def bindings_for_node(self, project_id: str, node_id: int) -> list[dict[str, Any]]:
        return [
            self.clone(item)
            for item in self.state["bindings"]
            if item["projectId"] == project_id and int(item["nodeId"]) == int(node_id)
        ]

    def bindings_for_project(self, project_id: str) -> list[dict[str, Any]]:
        return [self.clone(item) for item in self.state["bindings"] if item["projectId"] == project_id]

    def fields_for_versions(self, version_ids: set[str]) -> list[dict[str, Any]]:
        return [
            self.clone(item)
            for item in self.state["extracted_fields"]
            if item["documentVersionId"] in version_ids
        ]

    def evidence_for_versions(self, version_ids: set[str]) -> list[dict[str, Any]]:
        return [
            self.clone(item)
            for item in self.state["evidence_links"]
            if item.get("documentVersionId") in version_ids or item.get("objectId") in version_ids
        ]

    def add_audit(self, action: str, object_type: str, object_id: str, result: str = "成功") -> str:
        audit_id = f"AUD-{uuid4().hex[:10].upper()}"
        self.state["audit_logs"].insert(
            0,
            {
                "id": audit_id,
                "actorId": "USER-SYSTEM",
                "actorName": "系统联调用户",
                "actorOrgName": "AIcheck",
                "action": action,
                "objectType": object_type,
                "objectId": object_id,
                "result": result,
                "createdAt": server_time(),
            },
        )
        return audit_id

    def mutation_result(
        self,
        action: str,
        object_type: str,
        object_id: str,
        *,
        next_status: str | None = None,
        changed: list[dict[str, Any]] | None = None,
        affected_ids: list[str] | None = None,
        todo_delta: int = 0,
        message_delta: int = 0,
    ) -> dict[str, Any]:
        audit_id = self.add_audit(action, object_type, object_id)
        return {
            "id": f"MUT-{uuid4().hex[:10].upper()}",
            "objectType": object_type,
            "objectId": object_id,
            "nextStatus": next_status,
            "changed": changed or [],
            "todoDelta": todo_delta,
            "messageDelta": message_delta,
            "auditLogId": audit_id,
            "affectedIds": affected_ids or [object_id],
        }

    def set_node_status(self, project_id: str, node_id: int, status: str) -> dict[str, Any]:
        node = self.node(project_id, node_id)
        before = node.get("status") if node else None
        if node is not None:
            node["status"] = status
            node["revision"] = int(node.get("revision", 1)) + 1
        return {"field": f"nodes.{node_id}.status", "before": before, "after": status}

    def touch_project(self, project_id: str, status: str | None = None, current_node_id: int | None = None) -> None:
        project = self.require_project(project_id)
        if not project:
            return
        if status:
            project["status"] = status
        if current_node_id:
            project["currentNodeId"] = current_node_id
        project["updatedAt"] = server_time()
        project["revision"] = int(project.get("revision", 1)) + 1

    def signed_get(self, file_name: str, url: str, content_type: str | None = None, file_size: int | None = None) -> dict[str, Any]:
        signed_url = object_storage.presigned_get_url(url, file_name=file_name)
        payload = {
            "url": signed_url or url,
            "method": "GET",
            "expiresAt": object_storage.expires_at(),
            "fileName": file_name,
        }
        if content_type:
            payload["contentType"] = content_type
        if file_size:
            payload["fileSize"] = file_size
        return payload

    def signed_put(self, bucket: str, object_name: str, fallback_url: str, *, content_type: str | None = None) -> str:
        return object_storage.presigned_put_url(bucket, object_name, content_type=content_type) or fallback_url

    def document_storage_url(self, document: dict[str, Any], *, fallback_prefix: str) -> str:
        version = self.current_version(document["id"])
        bucket = (version or {}).get("storageBucket")
        storage_key = (version or {}).get("storageKey")
        if bucket and storage_key:
            return f"minio://{bucket}/{storage_key}"
        return f"mock://{fallback_prefix}/documents/{document['id']}?versionId={document.get('currentVersionId')}"

    def document_content_type(self, document: dict[str, Any]) -> str | None:
        raw_type = str(document.get("fileType") or "").lower()
        if "/" in raw_type:
            return raw_type
        suffix = raw_type or str(document.get("fileName") or "").rsplit(".", 1)[-1].lower()
        content_types = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        return content_types.get(suffix)

    def document_preview_type(self, document: dict[str, Any]) -> str:
        raw_type = str(document.get("fileType") or "").lower()
        file_name = str(document.get("fileName") or "").lower()
        suffix = file_name.rsplit(".", 1)[-1] if "." in file_name else raw_type
        if raw_type == "application/pdf" or suffix == "pdf":
            return "pdf"
        if raw_type.startswith("image/") or suffix in {"png", "jpg", "jpeg"}:
            return "image"
        if suffix in {"xlsx", "docx"}:
            return "office"
        return "unsupported"

    def document_preview(self, document: dict[str, Any]) -> dict[str, Any]:
        preview_type = self.document_preview_type(document)
        return {
            **self.document_signed_get(document, fallback_prefix="preview"),
            "previewType": preview_type,
            "readonly": True,
            "pageCount": 3 if preview_type == "pdf" else None,
        }

    def document_download(self, document: dict[str, Any]) -> dict[str, Any]:
        return self.document_signed_get(document, fallback_prefix="download")

    def document_signed_get(self, document: dict[str, Any], *, fallback_prefix: str) -> dict[str, Any]:
        content_type = self.document_content_type(document)
        primary = self.signed_get(
            document["fileName"],
            self.document_storage_url(document, fallback_prefix=fallback_prefix),
            content_type,
            file_size=245760,
        )
        if not str(primary.get("url") or "").startswith("minio://"):
            return primary
        return self.signed_get(
            document["fileName"],
            f"mock://{fallback_prefix}/documents/{document['id']}?versionId={document.get('currentVersionId')}",
            content_type,
            file_size=245760,
        )

    def create_document(
        self,
        project_id: str,
        file_name: str,
        file_type: str,
        *,
        source_org_name: str = "中石化安装有限公司",
        uploader_name: str = "李工",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        seed = uuid4().hex[:8].upper()
        document_id = f"DOC-{seed}"
        version_id = f"DV-{seed}-V1"
        now = server_time()
        doc = {
            "id": document_id,
            "projectId": project_id,
            "fileName": file_name,
            "fileType": file_type or file_name.split(".")[-1],
            "sourceOrgName": source_org_name,
            "uploaderName": uploader_name,
            "currentVersionId": version_id,
            "fileStatus": "已上传",
            "currentOcrStatus": "排队中",
            "updatedAt": now,
            "actions": ["file:view", "file:bind", "file:preview", "file:download"],
        }
        version = {
            "id": version_id,
            "documentId": document_id,
            "versionNo": "V1",
            "hash": f"mock-sha256-{document_id}",
            "fileSize": 245760,
            "storageKey": f"documents/{project_id}/{version_id}",
            "storageBucket": "documents",
            "ocrStatus": "排队中",
            "sliceStatus": "未切片",
            "vectorStatus": "未向量化",
            "uploaderName": uploader_name,
            "uploadTime": now,
            "isCurrent": True,
        }
        self.state["documents"].insert(0, doc)
        self.state["versions"].insert(0, version)
        knowledge_file = {
            "id": f"KF-{document_id}",
            "fileName": file_name,
            "sourceId": "KS-PROJECT-FILE",
            "sourceName": "项目文件知识库",
            "projectId": project_id,
            "projectName": self.require_project(project_id).get("name") if self.require_project(project_id) else "",
            "documentId": document_id,
            "documentVersionId": version_id,
            "ocrStatus": "排队中",
            "sliceStatus": "未切片",
            "vectorStatus": "待向量化",
            "chunkCount": 0,
            "vectorCount": 0,
            "updatedAt": now,
            "actions": ["knowledge:view", "knowledge:reindex"],
        }
        self.state["knowledge_files"].insert(0, knowledge_file)
        self.state["knowledge_tasks"].insert(
            0,
            {
                "id": f"KT-{seed}",
                "taskType": "ocr",
                "targetType": "file",
                "targetId": knowledge_file["id"],
                "targetName": file_name,
                "documentId": document_id,
                "documentVersionId": version_id,
                "status": "排队中",
                "progress": 0,
                "createdAt": now,
                "actions": ["knowledge:task-retry"],
            },
        )
        return doc, version

    def create_upload_session(self, project_id: str, files: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        session_id = f"UPS-{uuid4().hex[:10].upper()}"
        upload_urls = []
        session_files = []
        for file in files:
            doc, version = self.create_document(
                project_id,
                file.get("fileName") or "未命名资料.pdf",
                file.get("fileType") or "pdf",
            )
            content_type = file.get("fileType") or "application/octet-stream"
            upload_url = object_storage.presigned_put_url(
                "documents",
                version["storageKey"],
                content_type=content_type,
            )
            upload_urls.append(
                {
                    "fileName": doc["fileName"],
                    "documentId": doc["id"],
                    "documentVersionId": version["id"],
                    "url": upload_url or f"mock://upload/{session_id}/{doc['id']}",
                    "method": "PUT",
                    "expiresAt": object_storage.expires_at(),
                    "headers": {"Content-Type": content_type},
                }
            )
            session_files.append(
                {
                    "documentId": doc["id"],
                    "documentVersionId": version["id"],
                    "fileName": doc["fileName"],
                    "storageBucket": "documents",
                    "storageKey": version["storageKey"],
                }
            )
        self.state["upload_sessions"].insert(
            0,
            {
                "id": session_id,
                "projectId": project_id,
                "status": "待上传",
                "files": session_files,
                "createdAt": server_time(),
                "expiresAt": object_storage.expires_at(),
            },
        )
        return session_id, upload_urls

    def complete_upload_session(self, session_id: str) -> list[dict[str, Any]]:
        session = self.find_one("upload_sessions", session_id)
        if not session:
            return []
        session["status"] = "已完成"
        session["completedAt"] = server_time()
        return self.clone(session.get("files") or [])

    def upload_session_files(self, session_id: str) -> list[dict[str, Any]]:
        session = self.find_one("upload_sessions", session_id)
        return self.clone(session.get("files") or []) if session else []

    def upsert_knowledge_task(
        self,
        *,
        task_type: str,
        target_id: str,
        target_name: str,
        document_id: str | None = None,
        version_id: str | None = None,
        status: str = "排队中",
        progress: int = 0,
    ) -> dict[str, Any]:
        existing = next(
            (
                item
                for item in self.state["knowledge_tasks"]
                if item.get("taskType") == task_type and item.get("targetId") == target_id
            ),
            None,
        )
        if existing:
            existing.update({"status": status, "progress": progress, "updatedAt": server_time()})
            return existing
        seed = uuid4().hex[:8].upper()
        task = {
            "id": f"KT-{seed}",
            "taskType": task_type,
            "targetType": "file",
            "targetId": target_id,
            "targetName": target_name,
            "documentId": document_id,
            "documentVersionId": version_id,
            "status": status,
            "progress": progress,
            "createdAt": server_time(),
            "actions": ["knowledge:task-retry"],
        }
        self.state["knowledge_tasks"].insert(0, task)
        return task

    def append_task_log(self, task: dict[str, Any], level: str, message: str) -> dict[str, Any]:
        entry = {"createdAt": server_time(), "level": level, "message": message}
        task.setdefault("logs", []).append(entry)
        return entry

    def ocr_task_for(self, document_id: str, version_id: str, file_name: str | None = None) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in self.state["knowledge_tasks"]
                if item.get("taskType") == "ocr"
                and (
                    item.get("documentVersionId") == version_id
                    or item.get("targetId") == f"KF-{document_id}"
                    or (file_name and item.get("targetName") == file_name)
                )
            ),
            None,
        )

    def mark_task_running(self, task: dict[str, Any] | None, message: str) -> None:
        if not task:
            return
        task["status"] = "运行中"
        task["progress"] = max(int(task.get("progress") or 0), 10)
        task["startedAt"] = server_time()
        task["updatedAt"] = task["startedAt"]
        self.append_task_log(task, "info", message)

    def mark_task_failed(self, task: dict[str, Any] | None, message: str) -> None:
        if not task:
            return
        task["status"] = "失败"
        task["errorMessage"] = message
        task["finishedAt"] = server_time()
        task["updatedAt"] = task["finishedAt"]
        self.append_task_log(task, "error", message)

    def apply_ocr_result(self, document_id: str, version_id: str, result: dict[str, Any]) -> dict[str, Any]:
        document = self.find_one("documents", document_id)
        version = self.find_one("versions", version_id)
        knowledge_file = next(
            (item for item in self.state["knowledge_files"] if item.get("documentVersionId") == version_id),
            None,
        )
        task = next(
            (
                item
                for item in self.state["knowledge_tasks"]
                if item.get("documentVersionId") == version_id
                or item.get("targetId") == f"KF-{document_id}"
                or item.get("targetName") == result.get("fileName")
            ),
            None,
        )
        success = result.get("status") == "success"
        now = server_time()
        status = "已识别" if success else "识别失败"
        if document:
            document["currentOcrStatus"] = status
            document["updatedAt"] = now
        if version:
            version["ocrStatus"] = status
            version["sliceStatus"] = "待切片" if success else "未切片"
            version["vectorStatus"] = "待向量化" if success else "未向量化"
        if knowledge_file:
            knowledge_file["ocrStatus"] = status
            knowledge_file["sliceStatus"] = "待切片" if success else "未切片"
            knowledge_file["vectorStatus"] = "待向量化" if success else "待向量化"
            knowledge_file["updatedAt"] = now
        if task:
            task["status"] = "成功" if success else "失败"
            task["progress"] = 100 if success else task.get("progress", 0)
            task["finishedAt"] = now
            task["updatedAt"] = now
            if not success:
                task["errorMessage"] = "; ".join(str(item) for item in result.get("diagnostics") or ["OCR failed"])
                self.append_task_log(task, "error", task["errorMessage"])
            else:
                task.pop("errorMessage", None)
                self.append_task_log(task, "info", "OCR 任务完成。")

        if not success:
            return {"documentId": document_id, "versionId": version_id, "status": "failed", "fieldCount": 0}

        self.state["extracted_fields"] = [
            item for item in self.state["extracted_fields"] if item.get("documentVersionId") != version_id
        ]
        self.state["evidence_links"] = [
            item
            for item in self.state["evidence_links"]
            if item.get("documentVersionId") != version_id or item.get("objectType") == "knowledgeClause"
        ]
        fields = normalize_fields(result)
        if not fields:
            fields = fields_from_fragments(result)
        for index, field in enumerate(fields, start=1):
            field_id = f"FIELD-{version_id}-{index}"
            evidence_id = f"EV-{version_id}-{index}"
            page_no = int(field.get("pageNo") or 1)
            confidence = float(field.get("confidence") or 0.8)
            self.state["extracted_fields"].append(
                {
                    "id": field_id,
                    "documentVersionId": version_id,
                    "fieldName": field["fieldName"],
                    "fieldValue": field["fieldValue"],
                    "pageNo": page_no,
                    "bbox": field.get("bbox"),
                    "confidence": confidence,
                    "extractionMethod": field.get("extractionMethod") or "PaddleOCR+seal",
                    "reviewStatus": "已确认" if confidence >= 0.85 else "低置信度",
                    "evidenceLinkId": evidence_id,
                }
            )
            self.state["evidence_links"].append(
                {
                    "id": evidence_id,
                    "objectType": "extractedField",
                    "objectId": field_id,
                    "documentId": document_id,
                    "documentVersionId": version_id,
                    "fileName": (document or {}).get("fileName") or result.get("fileName"),
                    "pageNo": page_no,
                    "fieldName": field["fieldName"],
                    "quotedText": str(field["fieldValue"])[:200],
                    "bbox": field.get("bbox"),
                    "confidence": confidence,
                }
            )
        if knowledge_file:
            self.upsert_knowledge_task(
                task_type="slice",
                target_id=knowledge_file["id"],
                target_name=knowledge_file["fileName"],
                document_id=document_id,
                version_id=version_id,
            )
            self.upsert_knowledge_task(
                task_type="vector",
                target_id=knowledge_file["id"],
                target_name=knowledge_file["fileName"],
                document_id=document_id,
                version_id=version_id,
            )
        return {"documentId": document_id, "versionId": version_id, "status": "success", "fieldCount": len(fields)}

    def apply_slice_result(self, file_id: str, fragments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        file = self.find_one("knowledge_files", file_id)
        if not file:
            return {"fileId": file_id, "status": "missing", "chunkCount": 0}
        existing_ids = {
            item["id"] for item in self.state.get("knowledge_chunks", []) if item.get("fileId") == file_id
        }
        chunks = []
        source_fragments = fragments or [{"pageNo": 1, "text": f"{file['fileName']} OCR 文本切片。"}]
        for index, fragment in enumerate(source_fragments, start=1):
            chunk_id = f"CHK-{file_id}-{index}"
            if chunk_id in existing_ids:
                continue
            chunks.append(
                {
                    "id": chunk_id,
                    "fileId": file_id,
                    "documentId": file.get("documentId"),
                    "documentVersionId": file.get("documentVersionId"),
                    "chunkNo": index,
                    "text": str(fragment.get("text") or "")[:1800],
                    "pageNo": int(fragment.get("pageNo") or 1),
                    "bbox": fragment.get("bbox"),
                    "tokenCount": max(1, len(str(fragment.get("text") or "")) // 2),
                    "createdAt": server_time(),
                }
            )
        self.state.setdefault("knowledge_chunks", []).extend(chunks)
        file["sliceStatus"] = "已切片"
        file["chunkCount"] = len([item for item in self.state["knowledge_chunks"] if item.get("fileId") == file_id])
        file["updatedAt"] = server_time()
        task = next(
            (item for item in self.state["knowledge_tasks"] if item.get("taskType") == "slice" and item.get("targetId") == file_id),
            None,
        )
        if task:
            task["status"] = "成功"
            task["progress"] = 100
            task["finishedAt"] = server_time()
            task["updatedAt"] = task["finishedAt"]
            self.append_task_log(task, "info", "切片任务完成。")
        return {"fileId": file_id, "status": "success", "chunkCount": file["chunkCount"]}

    def apply_embed_result(self, file_id: str, vector_count: int | None = None) -> dict[str, Any]:
        file = self.find_one("knowledge_files", file_id)
        if not file:
            return {"fileId": file_id, "status": "missing", "vectorCount": 0}
        count = vector_count if vector_count is not None else len([item for item in self.state.get("knowledge_chunks", []) if item.get("fileId") == file_id]) or file.get("chunkCount", 1)
        file["vectorStatus"] = "已向量化"
        file["vectorCount"] = count
        file["updatedAt"] = server_time()
        task = next(
            (item for item in self.state["knowledge_tasks"] if item.get("taskType") == "vector" and item.get("targetId") == file_id),
            None,
        )
        if task:
            task["status"] = "成功"
            task["progress"] = 100
            task["finishedAt"] = server_time()
            task["updatedAt"] = task["finishedAt"]
            self.append_task_log(task, "info", "向量化任务完成。")
        return {"fileId": file_id, "status": "success", "vectorCount": count}

    def attach_export_artifact(self, task: dict[str, Any], *, content_type: str | None = None, body: bytes | None = None) -> dict[str, Any]:
        file_name = task.get("fileName") or f"{task['id']}.zip"
        suffix = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "zip"
        content_type = content_type or ("application/pdf" if suffix == "pdf" else "application/zip")
        artifact_body = body or build_export_artifact(file_name, task, content_type, self)
        object_key = f"{task.get('projectId') or 'global'}/{task['id']}/{file_name}"
        stored_url = object_storage.put_bytes("exports", object_key, artifact_body, content_type=content_type)
        if stored_url:
            task["downloadUrl"] = stored_url
            task["storageBucket"] = "exports"
            task["storageKey"] = object_key
            task["fileSize"] = len(artifact_body)
            task["contentType"] = content_type
        return task

    async def load_from_mongo(self, database: Any) -> None:
        self.mongo = database
        self.mongo_enabled = True
        if await database[STATE_COLLECTIONS["projects"]].count_documents({}) == 0:
            await self.flush_to_mongo(database)
            return
        loaded = fresh_state()
        loaded.setdefault("knowledge_chunks", [])
        loaded.setdefault("upload_sessions", [])
        for state_key, collection_name in STATE_COLLECTIONS.items():
            docs = await database[collection_name].find({}).to_list(length=None)
            loaded[state_key] = [strip_mongo_id(doc) for doc in docs]
        for state_key, collection_name in SINGLETON_COLLECTIONS.items():
            doc = await database[collection_name].find_one({"_singleton": state_key})
            if doc:
                loaded[state_key] = strip_mongo_id(doc).get("payload", loaded.get(state_key))
        idempotency_docs = await database[IDEMPOTENCY_COLLECTION].find({}).to_list(length=None)
        loaded["idempotency"] = {
            doc["scope"]: doc.get("payload") for doc in idempotency_docs if doc.get("scope")
        }
        self.state = loaded

    async def flush_to_mongo(self, database: Any | None = None) -> None:
        target = database if database is not None else self.mongo
        if target is None:
            return
        async with self._flush_lock:
            client = getattr(target, "client", None)
            if mongo_transactions_enabled() and client is not None:
                async with await client.start_session() as session:
                    async with session.start_transaction():
                        await self._flush_to_mongo(target, session=session)
                return
            await self._flush_to_mongo(target)

    async def _flush_to_mongo(self, target: Any, *, session: Any | None = None) -> None:
        for state_key, collection_name in STATE_COLLECTIONS.items():
            collection = target[collection_name]
            await collection.delete_many({}, session=session)
            docs = [self.clone(item) for item in self.state.get(state_key, [])]
            if docs:
                await collection.insert_many(docs, session=session)
        for state_key, collection_name in SINGLETON_COLLECTIONS.items():
            await target[collection_name].replace_one(
                {"_singleton": state_key},
                {"_singleton": state_key, "payload": self.clone(self.state.get(state_key))},
                upsert=True,
                session=session,
            )
        collection = target[IDEMPOTENCY_COLLECTION]
        await collection.delete_many({}, session=session)
        docs = [
            {
                "id": stable_doc_id(scope),
                "scope": scope,
                "payload": self.clone(payload),
                "updatedAt": server_time(),
            }
            for scope, payload in self.state.get("idempotency", {}).items()
        ]
        if docs:
            await collection.insert_many(docs, session=session)

    def configure_sync_mongo_from_env(self) -> None:
        if self.sync_mongo is not None:
            return
        mongo_url = os.getenv("AICHECK_MONGO_URL")
        if not mongo_url:
            return
        try:
            from pymongo import MongoClient
        except Exception:
            return
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=1500)
        database = client[os.getenv("AICHECK_MONGO_DB", "aicheck")]
        try:
            client.admin.command("ping")
        except Exception:
            client.close()
            return
        self.sync_mongo = database

    def load_from_sync_mongo(self) -> None:
        self.configure_sync_mongo_from_env()
        if self.sync_mongo is None:
            return
        if self.sync_mongo[STATE_COLLECTIONS["projects"]].count_documents({}) == 0:
            self.flush_to_sync_mongo()
            return
        loaded = fresh_state()
        loaded.setdefault("knowledge_chunks", [])
        loaded.setdefault("upload_sessions", [])
        for state_key, collection_name in STATE_COLLECTIONS.items():
            loaded[state_key] = [strip_mongo_id(doc) for doc in self.sync_mongo[collection_name].find({})]
        for state_key, collection_name in SINGLETON_COLLECTIONS.items():
            doc = self.sync_mongo[collection_name].find_one({"_singleton": state_key})
            if doc:
                loaded[state_key] = strip_mongo_id(doc).get("payload", loaded.get(state_key))
        loaded["idempotency"] = {
            doc["scope"]: doc.get("payload")
            for doc in self.sync_mongo[IDEMPOTENCY_COLLECTION].find({})
            if doc.get("scope")
        }
        self.state = loaded

    def flush_to_sync_mongo(self) -> None:
        self.configure_sync_mongo_from_env()
        if self.sync_mongo is None:
            return
        client = getattr(self.sync_mongo, "client", None)
        if mongo_transactions_enabled() and client is not None:
            with client.start_session() as session:
                with session.start_transaction():
                    self._flush_to_sync_mongo(session=session)
            return
        self._flush_to_sync_mongo()

    def _flush_to_sync_mongo(self, *, session: Any | None = None) -> None:
        for state_key, collection_name in STATE_COLLECTIONS.items():
            collection = self.sync_mongo[collection_name]
            collection.delete_many({}, session=session)
            docs = [self.clone(item) for item in self.state.get(state_key, [])]
            if docs:
                collection.insert_many(docs, session=session)
        for state_key, collection_name in SINGLETON_COLLECTIONS.items():
            self.sync_mongo[collection_name].replace_one(
                {"_singleton": state_key},
                {"_singleton": state_key, "payload": self.clone(self.state.get(state_key))},
                upsert=True,
                session=session,
            )
        collection = self.sync_mongo[IDEMPOTENCY_COLLECTION]
        collection.delete_many({}, session=session)
        docs = [
            {"id": stable_doc_id(scope), "scope": scope, "payload": self.clone(payload), "updatedAt": server_time()}
            for scope, payload in self.state.get("idempotency", {}).items()
        ]
        if docs:
            collection.insert_many(docs, session=session)

    def build_admin_overview(self) -> dict[str, Any]:
        config = self.clone(self.state["admin_config"])
        config["metrics"] = [
            {"key": "project", "label": "项目数", "value": len(self.state["projects"]), "tone": "blue"},
            {"key": "member", "label": "授权成员", "value": len(self.state["project_members"]), "tone": "green"},
            {"key": "rule", "label": "规则版本", "value": len(self.state["rule_versions"]), "tone": "orange"},
            {"key": "audit", "label": "审计记录", "value": len(self.state["audit_logs"]), "tone": "gray"},
        ]
        config["ruleVersions"] = self.clone(self.state["rule_versions"])
        return config


def strip_mongo_id(doc: dict[str, Any]) -> dict[str, Any]:
    cleaned = deepcopy(doc)
    cleaned.pop("_id", None)
    return cleaned


def stable_doc_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def normalize_fields(result: dict[str, Any]) -> list[dict[str, Any]]:
    fields = []
    for raw in result.get("fields") or []:
        if not isinstance(raw, dict):
            continue
        name = raw.get("fieldName") or raw.get("name") or raw.get("key") or raw.get("label")
        value = raw.get("fieldValue") or raw.get("value") or raw.get("text")
        if name and value is not None:
            fields.append(
                {
                    "fieldName": str(name),
                    "fieldValue": str(value),
                    "pageNo": raw.get("pageNo") or raw.get("page") or 1,
                    "bbox": raw.get("bbox") or raw.get("box"),
                    "confidence": raw.get("confidence") or raw.get("score") or 0.8,
                    "extractionMethod": raw.get("extractionMethod") or raw.get("method"),
                }
            )
    return fields


def fields_from_fragments(result: dict[str, Any]) -> list[dict[str, Any]]:
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    fields = []
    for index, fragment in enumerate(fragments[:5], start=1):
        text = str(fragment.get("text") or "").strip()
        if not text:
            continue
        fields.append(
            {
                "fieldName": "OCR文本" if index == 1 else f"OCR文本{index}",
                "fieldValue": text[:200],
                "pageNo": fragment.get("pageNo") or 1,
                "bbox": fragment.get("bbox"),
                "confidence": fragment.get("confidence") or 0.8,
                "extractionMethod": "PaddleOCR",
            }
        )
    return fields


def build_export_artifact(
    file_name: str,
    task: dict[str, Any],
    content_type: str,
    repository: InMemoryRepository,
) -> bytes:
    if content_type == "application/pdf" or file_name.lower().endswith(".pdf"):
        return build_pdf_artifact(file_name, task, repository)
    return build_zip_artifact(file_name, task, repository)


def export_context(task: dict[str, Any], repository: InMemoryRepository) -> dict[str, Any]:
    project_id = task.get("projectId")
    report_id = task.get("reportId")
    project = repository.require_project(project_id) if project_id else None
    reports = []
    if report_id:
        report = repository.find_one("reports", str(report_id))
        reports = [repository.clone(report)] if report else []
    elif project_id:
        reports = [repository.clone(item) for item in repository.state["reports"] if item.get("projectId") == project_id]
    documents = [repository.clone(item) for item in repository.state["documents"] if not project_id or item.get("projectId") == project_id]
    document_ids = {item["id"] for item in documents}
    archive_items = [
        repository.clone(item)
        for item in repository.state["archive_items"]
        if not project_id or item.get("projectId") == project_id
    ]
    evidence_links = [
        repository.clone(item)
        for item in repository.state["evidence_links"]
        if not document_ids or item.get("documentId") in document_ids
    ]
    return {
        "project": repository.clone(project) if project else None,
        "reports": reports,
        "documents": documents,
        "archiveItems": archive_items,
        "evidenceLinks": evidence_links,
        "counts": {
            "reports": len(reports),
            "documents": len(documents),
            "archiveItems": len(archive_items),
            "evidenceLinks": len(evidence_links),
        },
    }


def build_zip_artifact(file_name: str, task: dict[str, Any], repository: InMemoryRepository) -> bytes:
    import io
    import zipfile

    context = export_context(task, repository)
    manifest = {
        "schemaVersion": "aicheck-export-v1",
        "generatedAt": server_time(),
        "taskId": task.get("id"),
        "exportType": task.get("exportType"),
        "projectId": task.get("projectId"),
        "reportId": task.get("reportId"),
        "fileName": file_name,
        "counts": context["counts"],
        "contents": [
            "manifest.json",
            "task.json",
            "project.json",
            "reports.json",
            "documents.json",
            "archive_items.json",
            "evidence_links.json",
            "README.txt",
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json_dump(manifest))
        archive.writestr("task.json", json_dump(task))
        archive.writestr("project.json", json_dump(context["project"] or {}))
        archive.writestr("reports.json", json_dump(context["reports"]))
        archive.writestr("documents.json", json_dump(context["documents"]))
        archive.writestr("archive_items.json", json_dump(context["archiveItems"]))
        archive.writestr("evidence_links.json", json_dump(context["evidenceLinks"]))
        archive.writestr(
            "README.txt",
            "AIcheck export package\n"
            f"Task: {task.get('id')}\n"
            f"Type: {task.get('exportType')}\n"
            f"Project: {task.get('projectId') or 'global'}\n"
            "This package contains machine-readable manifest and business snapshots for audit and recovery.\n",
        )
    return buffer.getvalue()


def build_pdf_artifact(file_name: str, task: dict[str, Any], repository: InMemoryRepository) -> bytes:
    context = export_context(task, repository)
    project = context["project"] or {}
    report = context["reports"][0] if context["reports"] else {}
    lines = [
        "AIcheck Export Report",
        f"Task: {task.get('id')}",
        f"File: {file_name}",
        f"Project: {project.get('code') or project.get('id') or task.get('projectId') or '-'}",
        f"Report: {report.get('title') or report.get('reportNo') or task.get('reportId') or '-'}",
        f"Export Type: {task.get('exportType') or '-'}",
        f"Generated At: {server_time()}",
        f"Documents: {context['counts']['documents']}",
        f"Evidence Links: {context['counts']['evidenceLinks']}",
    ]
    return simple_pdf(lines)


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def simple_pdf(lines: list[str]) -> bytes:
    content_lines = ["BT", "/F1 12 Tf", "72 760 Td", "14 TL"]
    for index, line in enumerate(lines):
        prefix = "" if index == 0 else "T* "
        content_lines.append(f"{prefix}({pdf_escape(line)}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")[:120]


repo = InMemoryRepository()
