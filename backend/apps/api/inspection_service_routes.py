"""Public review capabilities without project uploads or persisted results."""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool

from apps.api import routes as api
from apps.api.std_samr_routes import StdSamrVerifyRequest, verify_std_samr_standard
from libs.inspection_standard_corpus import standard_state
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.important_node_review import NODE_IDS, skill_catalog
from libs.inspection_services import (
    InspectionServiceError,
    certificate_registry,
    certificate_validity,
    service_capabilities,
)

inspection_service_router = APIRouter(prefix="/inspection-services")


def public_review_request(method: str, path: str) -> bool:
    """Explicit method/path allowlist; never opens knowledge administration."""
    if method == "GET":
        return path in {"/inspection-services/capabilities", "/inspection-services/rules",
                        "/inspection-services/standards"} or (
            path.startswith("/inspection-services/standards/")
            and path.endswith("/canonical"))
    return method == "POST" and path in {
        "/inspection-services/certificate-validity", "/inspection-services/certificate-registry",
        "/inspection-services/standard-status", "/inspection-services/requests"}


def _public_standard(request: Request, file: dict, state: dict | None = None) -> bool:
    state = state if state is not None else api.repo.state
    document = next((doc for doc in state.get("documents", []) if doc.get("id") == file.get("documentId")), {})
    return (file.get("sourceType") == "standard" and not file.get("projectId")
            and not document.get("projectId") and api.record_visible_for_request(request, file))


@inspection_service_router.get("/standards")
def standards(request: Request, keyword: str = "", page_no: int = Query(1, alias="page", ge=1, le=1000),
              page_size: int = Query(20, alias="pageSize", ge=1, le=200)):
    from libs.db.repository import ensure_collections_loaded
    ensure_collections_loaded("knowledge_page_index_nodes", "standard_knowledge_records")
    source_state = standard_state(api.repo.state)
    files = [file for file in source_state.get("knowledge_files", []) if _public_standard(request, file, source_state)]
    from libs.knowledge_retrieval import standard_refs_from_text
    requested = standard_refs_from_text(keyword)
    from libs.inspection_standard_identity import identity_check, matches_requested_identity
    records = {r.get("knowledgeFileId"): r for r in source_state.get("standard_knowledge_records", [])}
    checks = {f["id"]: identity_check(f, records.get(f["id"])) for f in files}
    if requested:
        files = [file for file in files if matches_requested_identity(requested, checks[file["id"]])]
    ids = {file["id"] for file in files}
    state = {"knowledge_files": files, "knowledge_sources": source_state.get("knowledge_sources", [])}
    for collection, field in (("standard_knowledge_records", "knowledgeFileId"),
                              ("knowledge_clauses", "fileId"), ("knowledge_chunks", "fileId"),
                              ("knowledge_page_index_nodes", "fileId")):
        state[collection] = [item for item in source_state.get(collection, [])
                             if item.get(field) in ids and not item.get("projectId")]
    retrieval = api.retrieve_knowledge_clauses(state, query=keyword or "审查依据",
        business_pack_id=api.DEFAULT_BUSINESS_PACK_ID, top_k=page_no * page_size, query_type="clause_list", require_query_match=not bool(requested))
    items = retrieval["trace"]["selectedClauses"]
    for item in items:
        file_id = item.get("fileId")
        item["matchBasis"] = "standard_identifier" if requested else "lexical"
        item["identityCheck"] = checks.get(file_id, {"status": "unverified", "manualConfirmationRequired": True})
        if item["identityCheck"]["status"] != "verified":
            item["formalEvidenceEligible"] = False
        item["fileName"] = next((f.get("fileName") for f in files if f["id"] == file_id), None)
        record = next((r for r in source_state.get("standard_knowledge_records", []) if r.get("knowledgeFileId") == file_id), None)
        is_note = item.get("sourceMethod") == "reference_note"
        is_rule = not is_note and (item.get("sourceMethod") == "business_rule_reference" or str(item.get("clauseId", "")).startswith("BUSINESS-RULE-") or item.get("contextType") in {"business_rule_context", "context_only"})
        item["evidenceKind"] = "reference_note" if is_note else "business_rule" if is_rule else "standard_text"
        item["ruleFamily"] = "legacy-business-rules" if is_rule else None
        item["standardContentAvailable"] = bool(record and file_id in ids)
        item["standardContentArguments"] = {"fileId": file_id} if item["standardContentAvailable"] else None
        item["contentUnavailableReason"] = None if item["standardContentAvailable"] else "canonical_record_missing"
        if is_note:
            item["formalEvidenceEligible"] = False
        if is_rule:
            item["formalEvidenceEligible"] = False
            item["ruleSequence"] = item.get("pageNo")
            item["pageNo"] = None
            item["bbox"] = None
    return ok(api.page(items, page_no, page_size), request)


@inspection_service_router.get("/standards/{file_id:path}/canonical")
def standard_content(request: Request, file_id: str, page_no: int | None = Query(None, alias="pageNo"),
                     section: str | None = None):
    if not re.fullmatch(r"KF-KB-[A-Za-z0-9_-]+", file_id):
        return fail(errors.VALIDATION_ERROR, request, message="fileId 必须是检索返回的文件 ID，不能是文件路径。", http_status=400)
    state = standard_state(api.repo.state)
    file = next((item for item in state.get("knowledge_files", []) if item.get("id") == file_id), None)
    if not file or not _public_standard(request, file, state):
        return fail(errors.NOT_FOUND, request, message="文件不存在或未对公共审查开放；请使用检索返回的 fileId。", data={"serviceReason": "standardFileUnavailable"})
    from libs.inspection_standard_content import select_content
    record = next((r for r in state.get("standard_knowledge_records", []) if r.get("knowledgeFileId") == file_id), None)
    if not record:
        return fail(errors.NOT_FOUND, request, message="文件存在，规范化原文尚未就绪。", data={"serviceReason": "standardContentNotReady"})
    try:
        return ok(select_content(record, page_no=page_no, section=section), request)
    except InspectionServiceError as exc:
        return fail(errors.VALIDATION_ERROR, request, message=str(exc),
                    data={"serviceReason": exc.reason}, http_status=exc.status)


@inspection_service_router.post("/standard-status")
async def standard_status(body: StdSamrVerifyRequest, request: Request):
    if re.fullmatch(r"TSG\s*[A-Z]*\s*\d+(?:[-—－]\d{4})?", body.standardRef.strip(), re.I):
        return ok({"status": "UNSUPPORTED", "verdict": "unsupported_family", "citedRef": body.standardRef,
                   "reviewDate": body.reviewDate, "manualConfirmationRequired": True,
                   "reason": "TSG 属安全技术规范，当前标准公共平台适配器不支持；应核对总局公告原文。"}, request)
    return await verify_std_samr_standard(body, request)


def _invoke(request: Request, handler, *args):
    try:
        return ok(handler(*args), request)
    except InspectionServiceError as exc:
        return fail(errors.EXTERNAL_TOOL_FAILED if exc.status == 503 else errors.VALIDATION_ERROR,
                    request, message=str(exc), data={"serviceReason": exc.reason}, http_status=exc.status)


async def _body_invoke(request: Request, handler, *, limit: int = 1024 * 1024):
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > limit:
            return fail(errors.VALIDATION_ERROR, request, message="请求内容超过服务限制。", http_status=413)
        content.extend(chunk)
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return fail(errors.VALIDATION_ERROR, request, message="请求须为 JSON 对象。", http_status=400)
    if not isinstance(payload, dict):
        return fail(errors.VALIDATION_ERROR, request, message="请求须为 JSON 对象。", http_status=400)
    return await run_in_threadpool(_invoke, request, handler, payload)


@inspection_service_router.get("/capabilities")
def capabilities(request: Request):
    from libs.db.repository import ensure_collections_loaded
    ensure_collections_loaded("standard_knowledge_records")
    def snapshot():
        data = service_capabilities()
        state = standard_state(api.repo.state)
        files = [file for file in state.get("knowledge_files", []) if _public_standard(request, file, state)]
        ids = {file["id"] for file in files}
        records = [record for record in state.get("standard_knowledge_records", [])
                   if record.get("knowledgeFileId") in ids]
        data["standardContent"] = {"available": bool(records), "publicFileCount": len(files),
            "canonicalRecordCount": len(records),
            "referenceNoteCount": sum(record.get("sourceMethod") == "reference_note" for record in records),
            "reason": None if records else "canonical_records_missing"}
        data["standardStatus"] = {"available": True, "unsupportedFamilies": ["TSG"],
            "historicalVerdict": "as_of_review_date", "missingHistoricalDates": "ambiguous"}
        return data
    return _invoke(request, snapshot)


@inspection_service_router.get("/rules")
def rules(request: Request, nodeId: int | None = None):
    def selected_rules():
        if nodeId is not None and nodeId not in NODE_IDS:
            raise InspectionServiceError("当前 v3 审查规则不包含此节点。")
        return {"nodes": [node for node in skill_catalog() if nodeId is None or node["nodeId"] == nodeId]}
    return _invoke(request, selected_rules)


@inspection_service_router.post("/certificate-validity")
async def validity(request: Request):
    return await _body_invoke(request, certificate_validity)


@inspection_service_router.post("/certificate-registry")
async def registry(request: Request):
    return await _body_invoke(request, certificate_registry, limit=4096)


@inspection_service_router.post("/requests")
async def register_review_request(request: Request):
    """Explicitly retained request text; never an engineering file upload."""
    from datetime import datetime, timezone
    from uuid import UUID
    from libs.db.repository import ensure_collections_loaded, flush_state_records, postgres_persistence_configured

    def save(payload):
        allowed = {"requestId", "requestText", "platform", "nodeIds"}
        if set(payload) - allowed:
            raise InspectionServiceError("请求包含不支持的字段。")
        try:
            request_id = str(UUID(payload.get("requestId", "")))
        except (ValueError, TypeError, AttributeError):
            raise InspectionServiceError("requestId 必须是 UUID；重试使用同一个 ID。")
        text = payload.get("requestText")
        platform = payload.get("platform", "unknown")
        nodes = payload.get("nodeIds", [])
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise InspectionServiceError("requestText 须为1–4000字符的本次审查指令。")
        if not isinstance(platform, str) or not platform.strip() or len(platform) > 80:
            raise InspectionServiceError("platform 须为1–80字符。")
        if not isinstance(nodes, list) or len(nodes) > 12 or any(type(n) is not int or n not in NODE_IDS for n in nodes):
            raise InspectionServiceError("nodeIds 只能包含受支持的审查节点。")
        if not (postgres_persistence_configured() or api.repo.sqlite_enabled):
            raise InspectionServiceError("请求登记需要启用数据库持久化；当前服务仅为内存模式。", status=503)
        tenant = api.request_tenant_id(request)
        ensure_collections_loaded("inspection_requests")
        rows = api.repo.state.setdefault("inspection_requests", [])
        old = next((row for row in rows if row["id"] == request_id and row.get("tenantId") == tenant), None)
        values = dict(requestText=text, platform=platform, nodeIds=sorted(set(nodes)))
        if old:
            if any(old.get(k) != v for k, v in values.items()):
                raise InspectionServiceError("同一requestId不能保存不同内容。", status=409)
            return {"requestId": request_id, "saved": True, "duplicate": True}
        record = dict(id=request_id, tenantId=tenant, createdAt=datetime.now(timezone.utc).isoformat(),
                      identityVerified=False, **values)
        # Persist before making the row visible; failures must not report success.
        try:
            flush_state_records({"inspection_requests": [record]})
        except Exception:
            raise InspectionServiceError("请求登记暂不可用，请保留requestId稍后重试。", status=503) from None
        rows.insert(0, record)
        return {"requestId": request_id, "saved": True, "duplicate": False}

    return await _body_invoke(request, save, limit=24576)


@inspection_service_router.get("/requests")
def list_review_requests(request: Request, keyword: str = Query("", max_length=200),
                         page_no: int = Query(1, alias="page", ge=1),
                         page_size: int = Query(20, alias="pageSize", ge=1, le=100)):
    from libs.db.repository import ensure_collections_loaded
    role, identity_error = api.effective_role_for_request(request)
    if identity_error:
        return identity_error
    if role != "admin":
        return fail(errors.FORBIDDEN, request, message="仅管理员可查询Skill请求记录。", http_status=403)
    ensure_collections_loaded("inspection_requests")
    rows = [row for row in api.repo.state.get("inspection_requests", [])
            if row.get("tenantId") == api.request_tenant_id(request)]
    if keyword.strip():
        term = keyword.strip().casefold()
        rows = [row for row in rows if term in row["requestText"].casefold() or term in row["platform"].casefold()]
    rows.sort(key=lambda row: (row["createdAt"], row["id"]), reverse=True)
    from fastapi.responses import JSONResponse
    return JSONResponse(ok(api.page(rows, page_no, page_size), request), headers={"Cache-Control": "no-store"})
