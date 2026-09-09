"""Project-scoped draft editing for authorized inspection members."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Body, Header, Request

from apps.api import document_access_policy
from apps.api import routes as api
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.repository import repo
from libs.review_condition_facts import condition_candidates_from_run, resolve_condition_candidates
from libs.review_workstations import digest
from libs.rule_condition_bindings import compile_condition_bindings
from libs.rule_conditions import evaluate_conditions, validate_conditions

project_rule_router = APIRouter()
EDITABLE_FIELDS = {
    "executionConditions",
    "inspectionCategory", "inspectionItem", "inspectionClass", "standardText", "witnessText",
    "agentThinking", "toolchainThinking", "nodeIds", "criteria", "checkMethod", "description",
    "name", "version", "sourceDocument", "sourceSequence", "reviewClass",
}


def _guard(request, project_id, node_ids=None):
    if os.getenv("AICHECK_WORKSTATIONS_ENABLED", "").lower() not in {"true", "1", "yes"}:
        return fail(errors.NOT_FOUND, request)
    role, identity_error = api.effective_role_for_request(request)
    if identity_error:
        return identity_error
    if role != "inspection" or not api.request_user_id(request):
        return fail(errors.FORBIDDEN, request, message="工程规则编辑需要已授权的监检身份。")
    if not repo.require_project(project_id):
        return fail(errors.NOT_FOUND, request)
    return api.member_node_scope_error(request, project_id, role, node_ids=node_ids)


def _body_error(request, body):
    if set(body) - EDITABLE_FIELDS:
        return fail(errors.VALIDATION_ERROR, request, message="请求包含不可编辑的身份、状态或执行字段。")
    if "executionConditions" in body:
        try:
            validate_conditions(body["executionConditions"])
        except (TypeError, ValueError) as exc:
            return fail(errors.VALIDATION_ERROR, request, message=str(exc))
    return None


@project_rule_router.get("/projects/{project_id}/rules/versions")
def list_project_rules(request: Request, project_id: str):
    if error := _guard(request, project_id):
        return error
    project = repo.require_project(project_id)
    items = []
    for rule in repo.state.get("rule_versions", []):
        if rule.get("projectId") not in {None, "", project_id}:
            continue
        if str(rule.get("businessPackId") or api.DEFAULT_BUSINESS_PACK_ID) != str(project.get("businessPackId") or api.DEFAULT_BUSINESS_PACK_ID):
            continue
        if _guard(request, project_id, api.parse_rule_node_ids(rule.get("nodeIds"))) is None:
            items.append(api.versioned_record("rule-version", rule))
    pack = project.get("businessPackSnapshot") or api.load_business_pack(project.get("businessPackId") or api.DEFAULT_BUSINESS_PACK_ID)
    allowed_nodes = {node_id for node_id in {row["nodeId"] for row in pack.get("atomicChecks") or []}
                     if _guard(request, project_id, [node_id]) is None}
    atomic_checks = [{"id": row["id"], "name": row.get("name") or row["id"], "nodeId": row["nodeId"]}
                     for row in pack.get("atomicChecks") or [] if row["nodeId"] in allowed_nodes]
    return ok({"items": sorted(items, key=api.rule_version_sort_key), "total": len(items), "atomicChecks": atomic_checks}, request)


@project_rule_router.post("/projects/{project_id}/rules/versions")
def create_project_rule(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict),
                        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if error := _body_error(request, body):
        return error
    nodes = api.parse_rule_node_ids(body.get("nodeIds"))
    if error := _guard(request, project_id, nodes):
        return error
    if not nodes:
        return fail(errors.VALIDATION_ERROR, request, message="请选择规则适用节点。")
    project = repo.require_project(project_id)
    return api.create_rule_version(request, {**body, "projectId": project_id,
        "businessPackId": project.get("businessPackId") or api.DEFAULT_BUSINESS_PACK_ID}, idempotency_key)


@project_rule_router.patch("/projects/{project_id}/rules/versions/{version_id}")
def edit_project_rule(request: Request, project_id: str, version_id: str,
                      body: dict[str, Any] = Body(default_factory=dict),
                      idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                      if_match: str | None = Header(default=None, alias="If-Match")):
    if error := _guard(request, project_id):
        return error
    rule = repo.find_one("rule_versions", version_id)
    if not rule or rule.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    if error := _body_error(request, body):
        return error
    nodes = api.parse_rule_node_ids(rule.get("nodeIds")) + api.normalize_business_rule_version_record({**rule, **body})["nodeIds"]
    if error := _guard(request, project_id, nodes):
        return error
    if "nodeIds" in body and not api.parse_rule_node_ids(body["nodeIds"]):
        return fail(errors.VALIDATION_ERROR, request, message="规则必须保留适用节点。")
    if not if_match:
        return fail(errors.VALIDATION_ERROR, request, message="编辑规则需要 If-Match 版本标记。")
    return api.update_rule_version(request, version_id, body, idempotency_key, if_match)


@project_rule_router.post("/projects/{project_id}/rules/versions/{version_id}/fork")
def fork_project_rule(request: Request, project_id: str, version_id: str,
                      body: dict[str, Any] = Body(default_factory=dict),
                      idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if error := _guard(request, project_id):
        return error
    source = repo.find_one("rule_versions", version_id)
    if not source or source.get("projectId") not in {None, "", project_id}:
        return fail(errors.NOT_FOUND, request)
    if error := _body_error(request, body):
        return error
    nodes = api.parse_rule_node_ids(source.get("nodeIds")) + api.normalize_business_rule_version_record({**source, **body})["nodeIds"]
    if error := _guard(request, project_id, nodes):
        return error
    if "nodeIds" in body and not api.parse_rule_node_ids(body["nodeIds"]):
        return fail(errors.VALIDATION_ERROR, request, message="规则必须保留适用节点。")
    return api.fork_rule_version(request, version_id, {**body, "projectId": project_id}, idempotency_key)


@project_rule_router.post("/projects/{project_id}/rules/versions/{version_id}/trial")
def trial_project_rule(request: Request, project_id: str, version_id: str,
                       body: dict[str, Any] = Body(default_factory=dict),
                       if_match: str | None = Header(default=None, alias="If-Match")):
    if error := _guard(request, project_id):
        return error
    rule = repo.find_one("rule_versions", version_id)
    if not rule or rule.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    if error := _guard(request, project_id, api.parse_rule_node_ids(rule.get("nodeIds"))):
        return error
    if not if_match:
        return fail(errors.VALIDATION_ERROR, request, message="试跑需要 If-Match 版本标记。")
    if not api.record_if_match_valid("rule-version", rule, if_match):
        return fail(errors.ETAG_CONFLICT, request)
    if set(body) - {"facts", "reviewRunId", "objectMapping"} or ("objectMapping" in body and "reviewRunId" not in body):
        return fail(errors.VALIDATION_ERROR, request, message="对象映射仅能使用任务原文资料。")
    facts, diagnostics, run, candidates = body.get("facts"), {}, {}, {}
    run_id = body.get("reviewRunId")
    if run_id is not None:
        if not isinstance(run_id, str) or not run_id or "facts" in body:
            return fail(errors.VALIDATION_ERROR, request, message="请选择任务资料或手填示例，不能混用。")
        run = repo.find_one("review_runs", run_id, id_field="reviewRunId")
        if not run or run.get("projectId") != project_id or api.tenant_id_for_record(run) != api.request_tenant_id(request):
            return fail(errors.NOT_FOUND, request)
        visible = document_access_policy.actor_visible_evidence_repository(api._DOCUMENT_ACCESS_SERVICES, request, project_id)
        visible_versions = {row["id"] for row in visible.state.get("versions", [])
                            if api.tenant_id_for_record(row) == api.request_tenant_id(request)}
        if set(run.get("inputDocumentVersionIds") or []) - visible_versions:
            return fail(errors.FORBIDDEN, request)
        if str(run.get("nodeId")) not in {str(node) for node in api.parse_rule_node_ids(rule.get("nodeIds"))}:
            return fail(errors.VALIDATION_ERROR, request, message="任务节点不属于规则适用范围。")
        if str(run.get("businessPackId")) != str(rule.get("businessPackId") or api.DEFAULT_BUSINESS_PACK_ID):
            return fail(errors.VALIDATION_ERROR, request, message="任务与规则业务包不一致。")
        try:
            candidates = condition_candidates_from_run(repo.state, run, rule.get("executionConditions"))
            facts, diagnostics = resolve_condition_candidates(candidates, object_mapping=body.get("objectMapping"))
        except (TypeError, ValueError) as exc:
            return fail(errors.VALIDATION_ERROR, request, message=str(exc))
    try:
        result = evaluate_conditions(rule.get("executionConditions"), facts)
        if any("atomicCheckId" in check for check in rule["executionConditions"]["checks"]):
            project = repo.require_project(project_id)
            pack = project.get("businessPackSnapshot") or api.load_business_pack(rule.get("businessPackId") or api.DEFAULT_BUSINESS_PACK_ID)
            result["bindingPlan"] = compile_condition_bindings(rule, pack)
    except (TypeError, ValueError) as exc:
        return fail(errors.VALIDATION_ERROR, request, message=str(exc))
    mapping_snapshot = None
    if body.get("objectMapping") is not None:
        mapping_snapshot = {"schemaVersion": "condition-trial-object-mapping-v1",
                            "selection": repo.clone(body["objectMapping"]), "ruleVersionId": version_id,
                            "ruleRevision": rule.get("revision"), "reviewRunId": run_id,
                            "sourceSnapshotHash": run["documentScopeSnapshot"]["snapshotHash"],
                            "selectedByUserId": api.request_user_id(request), "evidenceVerified": False}
        mapping_snapshot["snapshotHash"] = digest(mapping_snapshot)
    versions_by_id = {row["id"]: row for row in visible.state.get("versions", [])
                      if api.tenant_id_for_record(row) == api.request_tenant_id(request)} if run_id else {}
    documents_by_id = {row["id"]: row for row in visible.state.get("documents", [])} if run_id else {}
    source_documents = []
    for document_version_id in run.get("inputDocumentVersionIds", []):
        version = versions_by_id[document_version_id]
        item = {"documentId": version["documentId"], "versionId": document_version_id,
                "fileName": version.get("fileName") or (documents_by_id.get(version["documentId"]) or {}).get("fileName") or document_version_id, "versionNo": version.get("versionNo")}
        bounds = (run.get("inputDocumentPageRanges") or {}).get(document_version_id)
        if bounds:
            item["pageRange"] = repo.clone(bounds)
        source_documents.append(item)
    return ok({"sourcePageRanges": run.get("inputDocumentPageRanges"), "sourceDocuments": source_documents, "factCandidates": candidates, "objectMappingSnapshot": mapping_snapshot, "mode": "draft_trial", "advisoryOnly": True, "ruleVersionId": version_id,
               "ruleRevision": rule.get("revision"), "sourceMode": "run_ocr" if run_id else "manual_examples",
               "sourceReviewRunId": run_id, "sourceSnapshotHash": (run.get("documentScopeSnapshot") or {}).get("snapshotHash"),
               "factDiagnostics": diagnostics, "evidenceVerified": False, **result}, request)


def _project_operation_guard(request, project_id, version_id, action, body, *, preview):
    if action not in {"publish", "rollback"}:
        return fail(errors.NOT_FOUND, request)
    if error := _guard(request, project_id):
        return error
    allowed = {"reason"} | ({"targetVersionId"} if action == "rollback" else set()) | (set() if preview else {"previewId"})
    if set(body) - allowed:
        return fail(errors.VALIDATION_ERROR, request, message="请求包含不可写的发布字段。")
    if not preview and not body.get("previewId"):
        return fail(errors.VALIDATION_ERROR, request, message="请先预览影响，再确认发布或回滚。")
    rule = repo.find_one("rule_versions", version_id)
    if not rule or rule.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    if error := _guard(request, project_id, api.parse_rule_node_ids(rule.get("nodeIds"))):
        return error
    if error := api.rule_project_mutation_error(request, rule, publishing=action == "publish"):
        return error
    if action == "rollback":
        target = api.matching_rule_target(rule, target_version_id=body.get("targetVersionId"))
        if not target or target.get("projectId") != project_id or target["id"] == rule["id"]:
            return fail(errors.VALIDATION_ERROR, request, message="请选择本工程同一规则的其他版本。")
        if error := _guard(request, project_id, api.parse_rule_node_ids(target.get("nodeIds"))):
            return error
        if error := api.rule_project_mutation_error(request, target, publishing=True):
            return error
    return None


@project_rule_router.post("/projects/{project_id}/rules/versions/{version_id}/{action}-preview")
def preview_project_rule_operation(request: Request, project_id: str, version_id: str, action: str,
                                   body: dict[str, Any] = Body(default_factory=dict),
                                   idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if error := _project_operation_guard(request, project_id, version_id, action, body, preview=True):
        return error
    return api.idempotent(request, idempotency_key,
                          lambda: api.preview_rule_version_operation(request, version_id, action, body),
                          fingerprint_source={"versionId": version_id, "action": action, "body": body})


@project_rule_router.post("/projects/{project_id}/rules/versions/{version_id}/{action}")
def apply_project_rule_operation(request: Request, project_id: str, version_id: str, action: str,
                                 body: dict[str, Any] = Body(default_factory=dict),
                                 idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                                 if_match: str | None = Header(default=None, alias="If-Match")):
    if error := _project_operation_guard(request, project_id, version_id, action, body, preview=False):
        return error
    if not if_match:
        return fail(errors.VALIDATION_ERROR, request, message="发布或回滚需要 If-Match 版本标记。")
    operation = api.publish_rule_version if action == "publish" else api.rollback_rule_version
    def produce():
        rule = repo.find_one("rule_versions", version_id)
        if action == "rollback":
            target = api.matching_rule_target(rule, target_version_id=body.get("targetVersionId"))
            if rule.get("status") != "已发布" or target.get("status") != "已回滚":
                return fail(errors.CONFLICT, request, message="只能从当前生效版本恢复到此前使用过的版本，请刷新列表。")
            overlapping = [row for row in repo.state.get("rule_versions", [])
                           if row.get("projectId") == project_id and row.get("businessPackId") == rule.get("businessPackId")
                           and row.get("status") == "已发布" and row["id"] != rule["id"]
                           and (row.get("ruleKey") == target.get("ruleKey")
                                or set(row.get("nodeIds") or []) & set(target.get("nodeIds") or []))]
            if overlapping:
                return fail(errors.CONFLICT, request, message="目标节点已有其他生效规则，请先核对冲突版本。")
        return operation(request, version_id, body, idempotency_key, if_match)
    return api.idempotent(request, idempotency_key,
                          produce,
                          fingerprint_source={"versionId": version_id, "body": body})


@project_rule_router.post("/projects/{project_id}/rules/draft-suggestion")
def suggest_project_rule(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict),
                         idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    from libs.integrations.errors import IntegrationServiceError
    from libs.rule_draft_generation import generate_rule_draft

    node_id, description = body.get("nodeId"), body.get("description")
    if set(body) != {"nodeId", "description"} or type(node_id) is not int or not isinstance(description, str) or not 1 <= len(description.strip()) <= 4000:
        return fail(errors.VALIDATION_ERROR, request, message="请选择节点，并用4000字以内描述规则要求。")
    if error := _guard(request, project_id, [node_id]):
        return error
    project = repo.require_project(project_id)
    pack = project.get("businessPackSnapshot") or api.load_business_pack(project.get("businessPackId") or api.DEFAULT_BUSINESS_PACK_ID)
    if not any(item.get("nodeId") == node_id for item in pack.get("atomicChecks") or []):
        return fail(errors.VALIDATION_ERROR, request, message="所选节点不在本工程业务规则范围内。")
    def produce():
        try:
            suggestion = generate_rule_draft(description.strip(), node_id)
        except (ValueError, TypeError, KeyError, IndexError, IntegrationServiceError):
            return fail(errors.EXTERNAL_TOOL_FAILED, request, message="这次没能生成可核对的草稿。原规则未变，请调整描述或稍后重试。")
        # Recheck authorization after the provider call; no generated data enters rule storage.
        if error := _guard(request, project_id, [node_id]):
            return error
        return ok({**suggestion, "requiresHumanConfirmation": True, "saved": False}, request)

    return api.idempotent(request, idempotency_key, produce, fingerprint_source={"projectId": project_id, "body": body})
