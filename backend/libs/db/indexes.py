from __future__ import annotations

MONGO_INDEXES = {
    "projects": [
        {"keys": [("code", 1)], "options": {"unique": True}},
        [("status", 1), ("updatedAt", -1)],
    ],
    "project_nodes": [[("projectId", 1), ("nodeId", 1), ("status", 1)]],
    "node_requirements": [("nodeId", 1), ("requiredType", 1)],
    "documents": [[("projectId", 1), ("currentVersionId", 1), ("updatedAt", -1)]],
    "document_versions": [[("documentId", 1), ("id", 1)]],
    "node_bindings": [[("projectId", 1), ("nodeId", 1), ("bindingStatus", 1)]],
    "submissions": [("projectId", 1), ("submittedAt", -1)],
    "rectifications": [[("projectId", 1), ("nodeId", 1), ("status", 1)]],
    "ai_runs": [[("projectId", 1), ("nodeId", 1), ("status", 1), ("startedAt", -1)]],
    "evidence_links": [[("objectType", 1), ("objectId", 1)], [("targetType", 1), ("targetId", 1)]],
    "reports": [[("projectId", 1), ("status", 1), ("generatedAt", -1)]],
    "archive_items": [[("projectId", 1), ("nodeId", 1), ("updatedAt", -1)]],
    "export_tasks": [[("projectId", 1), ("status", 1), ("createdAt", -1)]],
    "knowledge_files": [[("projectId", 1), ("nodeId", 1), ("sourceId", 1)]],
    "knowledge_tasks": [[("taskType", 1), ("status", 1), ("targetType", 1), ("targetId", 1)]],
    "knowledge_chunks": [[("fileId", 1), ("documentVersionId", 1)]],
    "todos": [[("projectId", 1), ("status", 1), ("deadline", 1)]],
    "messages": [[("projectId", 1), ("read", 1), ("createdAt", -1)]],
    "audit_logs": [[("createdAt", -1), ("objectType", 1), ("objectId", 1)]],
    "admin_configs": [("target", 1), ("id", 1)],
    "idempotency_keys": [{"keys": [("scope", 1)], "options": {"unique": True}}],
    "upload_sessions": [[("projectId", 1), ("status", 1), ("createdAt", -1)]],
    "ndt_films": [[("projectId", 1), ("status", 1), ("method", 1)]],
    "ndt_records": [[("projectId", 1), ("filmId", 1), ("reportId", 1)]],
    "ndt_reports": [[("projectId", 1), ("status", 1), ("method", 1)]],
    "ndt_feedback": [[("projectId", 1), ("status", 1), ("nodeId", 1)]],
    "llm_compare_runs": [[("projectId", 1), ("nodeId", 1), ("createdAt", -1)]],
    "review_opinions": [[("projectId", 1), ("nodeId", 1), ("createdAt", -1)]],
    "rule_versions": [[("ruleKey", 1), ("status", 1), ("updatedAt", -1)]],
    "users": [
        {"keys": [("username", 1)], "options": {"unique": True}},
        [("role", 1), ("status", 1)],
    ],
    "roles": [{"keys": [("role", 1)], "options": {"unique": True}}, ("status", 1)],
}


async def ensure_mongo_indexes(database) -> None:
    for collection_name, index_specs in MONGO_INDEXES.items():
        collection = database[collection_name]
        for spec in index_specs:
            if isinstance(spec, dict):
                await collection.create_index(spec["keys"], **spec.get("options", {}))
            elif spec and isinstance(spec[0], str):
                await collection.create_index([spec])
            else:
                await collection.create_index(spec)
