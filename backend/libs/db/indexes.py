from __future__ import annotations

MONGO_INDEXES = {
    "projects": [
        {"keys": [("code", 1)], "options": {"unique": True}},
        [("status", 1), ("updatedAt", -1)],
    ],
    "project_nodes": [[("projectId", 1), ("nodeId", 1), ("status", 1)]],
    "node_requirements": [("nodeId", 1), ("requiredType", 1)],
    "documents": [
        [("projectId", 1), ("currentVersionId", 1), ("updatedAt", -1)],
        [("projectId", 1), ("nodeId", 1), ("status", 1), ("updatedAt", -1)],
    ],
    "document_versions": [
        [("documentId", 1), ("id", 1)],
        {"keys": [("id", 1)], "options": {"unique": True}},
    ],
    "node_bindings": [[("projectId", 1), ("nodeId", 1), ("bindingStatus", 1)]],
    "submissions": [
        ("projectId", 1),
        ("submittedAt", -1),
        [("projectId", 1), ("nodeIds", 1), ("nextStatus", 1), ("submittedAt", -1)],
    ],
    "submission_drafts": [
        [("projectId", 1), ("draftId", 1)],
        [("projectId", 1), ("nodeIds", 1), ("savedAt", -1)],
    ],
    "rectifications": [[("projectId", 1), ("nodeId", 1), ("status", 1)]],
    "ai_runs": [[("projectId", 1), ("nodeId", 1), ("status", 1), ("startedAt", -1)]],
    "ai_feedback": [[("aiRunId", 1), ("feedbackType", 1), ("createdAt", -1)]],
    "access_grants": [[("subjectUserId", 1), ("targetType", 1), ("targetId", 1), ("expiresAt", 1)]],
    "ai_trace_steps": [[("aiRunId", 1), ("sequence", 1)], [("traceId", 1), ("status", 1)]],
    "ai_run_replays": [
        [("parentRunId", 1), ("childRunId", 1)],
        [("runType", 1), ("status", 1), ("createdAt", -1)],
    ],
    "feedback_triage": [[("feedbackId", 1), ("status", 1), ("createdAt", -1)]],
    "evaluation_sets": [[("businessPackId", 1), ("setType", 1), ("status", 1)]],
    "evaluation_cases": [[("evaluationSetId", 1), ("riskLevel", 1)], [("businessPackId", 1), ("nodeId", 1)]],
    "evaluation_runs": [[("evaluationSetId", 1), ("status", 1), ("startedAt", -1)]],
    "evaluation_metrics": [[("evaluationRunId", 1), ("metric", 1)]],
    "evaluation_reports": [[("evaluationRunId", 1), ("capabilityBundleId", 1), ("status", 1)]],
    "agent_versions": [[("agentId", 1), ("version", 1), ("status", 1)]],
    "prompt_versions": [[("promptKey", 1), ("version", 1), ("status", 1)]],
    "model_route_versions": [[("modelAlias", 1), ("version", 1), ("status", 1)]],
    "ocr_profile_versions": [[("profileKey", 1), ("version", 1), ("status", 1)]],
    "capability_bundles": [[("businessPackId", 1), ("status", 1), ("riskLevel", 1)]],
    "release_plans": [[("capabilityBundleId", 1), ("status", 1), ("riskLevel", 1)], [("createdAt", -1)]],
    "release_approvals": [[("releasePlanId", 1), ("role", 1), ("status", 1)]],
    "release_gates": [[("releasePlanId", 1), ("gate", 1), ("passed", 1)]],
    "incidents": [[("severity", 1), ("status", 1), ("createdAt", -1)]],
    "incident_rca": [[("incidentId", 1), ("status", 1), ("updatedAt", -1)]],
    "business_pack_installations": [[("businessPackId", 1), ("tenantId", 1), ("status", 1)]],
    "business_pack_overrides": [[("businessPackId", 1), ("tenantId", 1), ("scope", 1)]],
    "cost_budgets": [[("tenantId", 1), ("scopeType", 1), ("scopeId", 1)]],
    "data_exports": [[("requesterUserId", 1), ("status", 1), ("createdAt", -1)]],
    "delivery_acceptance_reports": [[("businessPackId", 1), ("status", 1), ("confirmedAt", -1)]],
    "review_findings": [[("projectId", 1), ("nodeId", 1), ("status", 1), ("createdAt", -1)]],
    "extracted_fields": [[("documentVersionId", 1), ("fieldName", 1)], [("reviewStatus", 1), ("confidence", 1)]],
    "evidence_links": [[("objectType", 1), ("objectId", 1)], [("targetType", 1), ("targetId", 1)]],
    "reports": [[("projectId", 1), ("status", 1), ("generatedAt", -1)]],
    "archive_items": [[("projectId", 1), ("nodeId", 1), ("updatedAt", -1)]],
    "export_tasks": [[("projectId", 1), ("status", 1), ("createdAt", -1)]],
    "knowledge_sources": [
        [("sourceType", 1), ("status", 1), ("updatedAt", -1)],
        [("name", 1), ("version", 1)],
    ],
    "knowledge_files": [[("projectId", 1), ("nodeId", 1), ("sourceId", 1)]],
    "knowledge_tasks": [[("taskType", 1), ("status", 1), ("targetType", 1), ("targetId", 1)]],
    "knowledge_chunks": [[("fileId", 1), ("documentVersionId", 1)]],
    "todos": [[("projectId", 1), ("status", 1), ("deadline", 1)]],
    "messages": [[("projectId", 1), ("read", 1), ("createdAt", -1)]],
    "audit_logs": [
        [("createdAt", -1), ("objectType", 1), ("objectId", 1)],
        [("objectType", 1), ("objectId", 1), ("createdAt", -1)],
    ],
    "admin_configs": [
        {"keys": [("_singleton", 1)], "options": {"unique": True}},
        ("target", 1),
        ("id", 1),
    ],
    "knowledge_configs": [{"keys": [("_singleton", 1)], "options": {"unique": True}}],
    "idempotency_keys": [{"keys": [("scope", 1)], "options": {"unique": True}}],
    "project_members": [
        {"keys": [("projectId", 1), ("userId", 1), ("role", 1)], "options": {"unique": True}},
        [("projectId", 1), ("role", 1), ("status", 1)],
        [("projectId", 1), ("nodeScope", 1)],
    ],
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
    "business_packs": [
        {"keys": [("id", 1)], "options": {"unique": True}},
        [("domainType", 1), ("status", 1)],
    ],
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
