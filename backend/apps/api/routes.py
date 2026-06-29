from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from apps.api.adapters.engineering_inspection import (
    ENGINEERING_DOMAIN_TYPE,
    ENGINEERING_PROJECT_DEFAULTS,
)
from apps.ocr_service.evaluation import compact_evaluation_report, evaluate_cases
from apps.ocr_service.readiness import build_ocr_100_scorecard
from libs.business_pack import (
    DEFAULT_BUSINESS_PACK_ID,
    build_project_requirements,
    build_project_tree,
    business_pack_snapshot,
    business_pack_summary,
    list_business_packs,
    load_business_pack,
    validate_all_business_packs,
    validate_business_pack,
)
from libs.contracts import errors
from libs.contracts.responses import fail, ok, page, server_time
from libs.db.repository import load_state, repo
from libs.db.seed import PROJECT_ID, ROLE_NODE_MAP
from libs.integrations import task_dispatcher
from libs.integrations.errors import IntegrationServiceError
from libs.integrations.ocr_client import OcrClient
from libs.knowledge_readiness import build_knowledge_rule_scorecard
from libs.knowledge_retrieval import answer_draft_from_clauses, retrieve_knowledge_clauses
from libs.review_orchestrator import (
    build_review_orchestration_scorecard,
    clone_review_run_for_replay,
    graph_view_for_review_run,
    human_decision_for_review_run,
    review_run_timeline,
    review_run_view,
    signal_review_run_cancel,
    signal_review_run_human_decision,
)
from libs.security.auth import ROLE_DEFAULT_PATHS, USERS, authenticate, decode_token, issue_token, user_by_username
from scripts.ocr_100_label_studio_export import label_config_xml, label_studio_task, label_studio_task_without_image
from scripts.ocr_100_label_studio_import import import_label_studio_annotations
from scripts.ocr_annotation_readiness import build_annotation_readiness_from_tasks

router = APIRouter(tags=["AIcheck API"])
mock_router = APIRouter(tags=["Compatibility Mock"])
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]

REPORT_GENERATION_BLOCKED_STATUSES = {"待提交", "需补正", "退回补正中", "部分提交", "AI 预审中"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
MAX_NDT_UPLOAD_BYTES = 500 * 1024 * 1024
ALLOWED_UPLOAD_TYPES = {
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "png",
    "jpg",
    "jpeg",
    "zip",
    "7z",
    "application/pdf",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/png",
    "image/jpg",
    "image/jpeg",
    "application/zip",
    "application/x-zip-compressed",
    "application/x-7z-compressed",
}
ALLOWED_NDT_UPLOAD_TYPES = ALLOWED_UPLOAD_TYPES | {"dcm", "dicom", "application/dicom"}
CONFIG_METADATA_FIELDS = {"revision", "etag", "updatedAt", "lastPublishedVersion", "lastPublishedAt", "lastPublishedScope"}
KNOWLEDGE_TASK_STATUS_ORDER = {
    "失败": 0,
    "排队中": 1,
    "运行中": 2,
    "已取消": 3,
    "成功": 4,
}


def refresh_state_from_mongo_for_live_read() -> None:
    if repo.sync_mongo is not None:
        load_state()
AI_FEEDBACK_TYPES = {
    "accepted",
    "edited",
    "rejected_false_positive",
    "missed_issue",
    "wrong_evidence",
    "wrong_rule_reference",
    "wrong_severity",
    "hallucination",
    "format_error",
    "unsafe_output",
}

FDE_ROLES = {"fde"}

FDE_REPLAY_TYPES = {
    "diagnostic_replay",
    "evaluation_replay",
    "shadow_replay",
}

FDE_ROOT_CAUSES = {
    "ocr_error",
    "field_mapping_error",
    "rule_error",
    "kb_retrieval_error",
    "kb_content_error",
    "prompt_error",
    "model_reasoning_error",
    "schema_error",
    "business_pack_config_error",
    "user_uploaded_bad_file",
    "ambiguous_business_standard",
    "human_review_error",
}


def role_from_query(role: str | None = None, x_role: str | None = None) -> str:
    return (x_role or role or "inspection").strip() or "inspection"


def file_type_tokens(file: dict[str, Any]) -> set[str]:
    raw_values = [file.get("fileType"), file.get("contentType")]
    file_name = str(file.get("fileName") or "")
    if "." in file_name:
        raw_values.append(file_name.rsplit(".", 1)[-1])
    tokens = {str(value).strip().lower() for value in raw_values if value}
    return tokens


def validate_upload_files(
    request: Request,
    files: list[dict[str, Any]],
    *,
    ndt: bool = False,
) -> JSONResponse | None:
    if not files:
        error = errors.NDT_REPORT_REQUIRED if ndt else errors.VALIDATION_ERROR
        return fail(error, request, message="上传文件不能为空。")
    allowed_types = ALLOWED_NDT_UPLOAD_TYPES if ndt else ALLOWED_UPLOAD_TYPES
    max_bytes = MAX_NDT_UPLOAD_BYTES if ndt else MAX_UPLOAD_BYTES
    for index, file in enumerate(files):
        file_name = file.get("fileName") or f"第 {index + 1} 个文件"
        try:
            file_size = int(file.get("fileSize") or 0)
        except (TypeError, ValueError):
            file_size = 0
        if file_size < 1:
            return fail(errors.VALIDATION_ERROR, request, message=f"{file_name} 文件大小必须大于 0。", data={"fileName": file_name})
        if file_size > max_bytes:
            error = errors.NDT_FILE_TOO_LARGE if ndt else errors.FILE_TOO_LARGE
            return fail(error, request, message=f"{file_name} 超过 {max_bytes // 1024 // 1024}MB 上传限制。", data={"fileName": file_name, "fileSize": file_size})
        if not (file_type_tokens(file) & allowed_types):
            error = errors.UNSUPPORTED_NDT_FILE_TYPE if ndt else errors.UNSUPPORTED_FILE_TYPE
            return fail(error, request, message=f"{file_name} 文件类型不支持。", data={"fileName": file_name, "fileType": file.get("fileType")})
    return None


def missing_required_fields(item: dict[str, Any], fields: list[str]) -> list[str]:
    return [field for field in fields if item.get(field) in {None, ""}]


def resolved_role_for_read(request: Request, role: str | None = None, x_role: str | None = None) -> tuple[str, JSONResponse | None]:
    effective_role, identity_error = effective_role_for_request(request, x_role)
    if identity_error:
        return "inspection", identity_error
    requested_role = role_from_query(role, x_role)
    claims = getattr(request.state, "auth", None)
    token_role = claims.get("role") if claims else None
    if token_role and token_role != "admin":
        if requested_role != token_role:
            return requested_role, fail(errors.FORBIDDEN, request, message="请求角色与登录身份不一致。")
        return token_role, None
    return requested_role or effective_role or "inspection", None


def mutation_guard(
    request: Request,
    project_id: str | None = None,
    *,
    x_role: str | None = None,
    if_match: str | None = None,
    node_ids: list[int] | None = None,
) -> JSONResponse | None:
    effective_role, identity_error = effective_role_for_request(request, x_role)
    if identity_error:
        return identity_error
    if project_id:
        project = repo.require_project(project_id)
        if not project:
            return fail(errors.NOT_FOUND, request)
        if project.get("status") == "已归档":
            return fail(errors.ARCHIVED_READONLY, request)
        effective_if_match = if_match
        if effective_if_match is None and "/reports/" not in request.url.path:
            effective_if_match = request.headers.get("If-Match")
        if not project_if_match_valid(project, effective_if_match):
            return fail(errors.ETAG_CONFLICT, request)
        node_scope_error = member_node_scope_error(request, project_id, effective_role, node_ids=node_ids)
        if node_scope_error:
            return node_scope_error
    action_code = request.headers.get("X-Action-Code")
    if action_code and effective_role and action_code not in repo.role_actions(effective_role):
        return fail(errors.FORBIDDEN, request, message=f"角色 {effective_role} 无权执行 {action_code}。")
    if effective_role in FDE_ROLES:
        return fail(errors.FORBIDDEN, request, message="FDE 只能管理 AI 能力和治理流程，不能执行正式业务写操作。")
    if effective_role in {"owner"}:
        return fail(errors.FORBIDDEN, request)
    if effective_role == "admin" and "/review-opinions" in request.url.path:
        return fail(errors.FORBIDDEN, request, message="管理员不能代替业务角色保存审查意见。")
    return None


def effective_role_for_request(request: Request, x_role: str | None = None) -> tuple[str | None, JSONResponse | None]:
    header_role = x_role or request.headers.get("X-Role")
    claims = getattr(request.state, "auth", None)
    if not claims:
        return header_role, None
    token_role = claims.get("role")
    auth_user = getattr(request.state, "auth_user", None) or user_by_username(claims.get("sub"))
    token_user_id = auth_user.get("id") if auth_user else None
    header_user_id = request.headers.get("X-User-Id")
    if header_role and token_role and header_role != token_role and token_role != "admin":
        return None, fail(errors.FORBIDDEN, request, message="请求角色与登录身份不一致。")
    if header_user_id and token_user_id and header_user_id != token_user_id and token_role != "admin":
        return None, fail(errors.FORBIDDEN, request, message="请求用户与登录身份不一致。")
    return header_role or token_role, None


def request_user_id(request: Request) -> str | None:
    auth_user = getattr(request.state, "auth_user", None)
    if auth_user and auth_user.get("id"):
        return auth_user["id"]
    return request.headers.get("X-User-Id")


def member_node_scope_error(
    request: Request,
    project_id: str,
    role: str | None,
    *,
    node_ids: list[int] | None = None,
) -> JSONResponse | None:
    if role == "admin":
        return None
    user_id = request_user_id(request)
    if not user_id:
        return None
    member = next(
        (
            item
            for item in repo.state["project_members"]
            if item.get("projectId") == project_id
            and item.get("userId") == user_id
            and (not role or item.get("role") == role)
            and item.get("status") == "启用"
        ),
        None,
    )
    if member is None:
        return fail(errors.FORBIDDEN, request, message="用户未获得该项目授权。")
    requested_node_ids = {int(item) for item in node_ids or []}
    match = re.search(r"/nodes/(\d+)", request.url.path)
    if match:
        requested_node_ids.add(int(match.group(1)))
    node_scope = {int(item) for item in member.get("nodeScope") or []}
    out_of_scope = sorted(requested_node_ids - node_scope)
    if out_of_scope:
        return fail(errors.FORBIDDEN, request, message="用户不在该节点授权范围内。")
    return None


def node_ids_from_body(body: dict[str, Any], default_node_id: int | None = None) -> list[int]:
    raw_node_ids = body.get("nodeIds")
    if not raw_node_ids:
        raw_node_ids = [body.get("nodeId") or default_node_id]
    return [int(item) for item in raw_node_ids if item is not None and item != ""]


def binding_node_ids(project_id: str, binding_id: str) -> list[int]:
    binding = repo.find_one("bindings", binding_id)
    if not binding or binding.get("projectId") != project_id:
        return []
    return [int(binding["nodeId"])]


def document_node_ids(project_id: str, document_id: str) -> list[int]:
    document = repo.find_one("documents", document_id)
    if not document or document.get("projectId") != project_id:
        return []
    node_ids = {
        int(binding["nodeId"])
        for binding in repo.state["bindings"]
        if binding.get("projectId") == project_id and binding.get("documentId") == document_id
    }
    _add_node_id(node_ids, document.get("nodeId"))
    return sorted(node_ids)


def report_node_ids(project_id: str, report_id: str) -> list[int]:
    report = repo.find_one("reports", report_id)
    if not report or report.get("projectId") != project_id:
        return []
    return [int(item) for item in report.get("nodeIds") or []]


def project_revision(project: dict[str, Any]) -> int:
    return int(project.get("revision") or 1)


def project_etag(project: dict[str, Any]) -> str:
    return f'W/"project-{project["id"]}-r{project_revision(project)}"'


def project_if_match_valid(project: dict[str, Any], if_match: str | None) -> bool:
    if not if_match:
        return True
    revision = project_revision(project)
    return if_match in {"*", str(revision), f'W/"{revision}"', project_etag(project)}


def versioned_project(project: dict[str, Any]) -> dict[str, Any]:
    cloned = repo.clone(project)
    cloned["revision"] = project_revision(project)
    cloned["etag"] = project_etag(project)
    return cloned


def report_etag(report: dict[str, Any]) -> str:
    revision = int(report.get("revision") or 1)
    return str(report.get("etag") or f'W/"report-{report["id"]}-r{revision}"')


def versioned_report(report: dict[str, Any]) -> dict[str, Any]:
    cloned = repo.clone(report)
    cloned["revision"] = int(report.get("revision") or 1)
    cloned["etag"] = report_etag(report)
    cloned["updatedAt"] = cloned.get("updatedAt") or cloned.get("generatedAt")
    return cloned


def report_if_match_valid(report: dict[str, Any], if_match: str | None) -> bool:
    if not if_match:
        return True
    revision = int(report.get("revision") or 1)
    return if_match in {"*", str(revision), f'W/"{revision}"', report_etag(report)}


def singleton_revision(config: dict[str, Any]) -> int:
    return int(config.get("revision") or 1)


def singleton_etag(prefix: str, config: dict[str, Any]) -> str:
    return f'W/"{prefix}-r{singleton_revision(config)}"'


def versioned_singleton(prefix: str, config: dict[str, Any]) -> dict[str, Any]:
    cloned = repo.clone(config)
    cloned["revision"] = singleton_revision(config)
    cloned["etag"] = singleton_etag(prefix, config)
    cloned["updatedAt"] = cloned.get("updatedAt") or server_time()
    return cloned


def singleton_if_match_valid(prefix: str, config: dict[str, Any], if_match: str | None) -> bool:
    if not if_match:
        return True
    revision = singleton_revision(config)
    return if_match in {"*", str(revision), f'W/"{revision}"', singleton_etag(prefix, config)}


def bump_singleton_revision(config: dict[str, Any]) -> None:
    config["revision"] = singleton_revision(config) + 1
    config["updatedAt"] = server_time()


def record_revision(record: dict[str, Any]) -> int:
    return int(record.get("revision") or 1)


def record_etag(prefix: str, record: dict[str, Any]) -> str:
    return f'W/"{prefix}-{record["id"]}-r{record_revision(record)}"'


def versioned_record(prefix: str, record: dict[str, Any]) -> dict[str, Any]:
    cloned = repo.clone(record)
    cloned["revision"] = record_revision(record)
    cloned["etag"] = record_etag(prefix, record)
    cloned["updatedAt"] = cloned.get("updatedAt") or cloned.get("finishedAt") or cloned.get("createdAt") or server_time()
    return cloned


def record_if_match_valid(prefix: str, record: dict[str, Any], if_match: str | None) -> bool:
    if not if_match:
        return True
    revision = record_revision(record)
    return if_match in {"*", str(revision), f'W/"{revision}"', record_etag(prefix, record)}


def bump_record_revision(record: dict[str, Any]) -> None:
    record["revision"] = record_revision(record) + 1
    record["updatedAt"] = server_time()


def ndt_submission_node_ids(project_id: str, body: dict[str, Any]) -> list[int]:
    node_ids = set(node_ids_from_body(body, 40))
    for report_id in body.get("reportIds") or []:
        report = repo.find_one("ndt_reports", str(report_id))
        if report and report.get("projectId") == project_id:
            node_ids.update(record_node_ids(project_id, report))
    for film_id in body.get("filmIds") or []:
        film = repo.find_one("ndt_films", str(film_id))
        if film and film.get("projectId") == project_id:
            node_ids.update(record_node_ids(project_id, film))
    return sorted(node_ids)


def authorized_node_scope(request: Request, project_id: str) -> set[int] | None:
    claims = getattr(request.state, "auth", None)
    if not claims or claims.get("role") == "admin":
        return None
    user_id = request_user_id(request)
    role = claims.get("role")
    member = next(
        (
            item
            for item in repo.state["project_members"]
            if item.get("projectId") == project_id
            and item.get("userId") == user_id
            and item.get("role") == role
            and item.get("status") == "启用"
        ),
        None,
    )
    if member is None:
        return set()
    return {int(item) for item in member.get("nodeScope") or []}


def project_visible_for_request(request: Request, project_id: str) -> bool:
    scope = authorized_node_scope(request, project_id)
    return scope is None or bool(scope)


def filter_node_groups_for_scope(groups: list[dict[str, Any]], scope: set[int] | None) -> list[dict[str, Any]]:
    if scope is None:
        return groups
    scoped_groups = []
    for group in groups:
        nodes = [node for node in group.get("nodes", []) if int(node.get("nodeId")) in scope]
        if nodes:
            scoped_groups.append({**group, "nodes": nodes})
    return scoped_groups


def document_visible_in_scope(document: dict[str, Any], scope: set[int] | None) -> bool:
    if scope is None:
        return True
    binding_node_ids = {
        int(binding["nodeId"])
        for binding in repo.state["bindings"]
        if binding.get("projectId") == document.get("projectId") and binding.get("documentId") == document.get("id")
    }
    _add_node_id(binding_node_ids, document.get("nodeId"))
    return not binding_node_ids or bool(binding_node_ids & scope)


def report_visible_in_scope(report: dict[str, Any], scope: set[int] | None) -> bool:
    if scope is None:
        return True
    node_ids = {int(item) for item in report.get("nodeIds") or []}
    return bool(node_ids) and node_ids.issubset(scope)


def archive_visible_in_scope(item: dict[str, Any], scope: set[int] | None) -> bool:
    if scope is None:
        return True
    if not scope:
        return False
    node_id = item.get("nodeId")
    return node_id is not None and int(node_id) in scope


def _add_node_id(node_ids: set[int], value: Any) -> None:
    if value is None or value == "":
        return
    try:
        node_ids.add(int(value))
    except (TypeError, ValueError):
        return


def _document_project_id(document_id: str | None) -> str | None:
    if not document_id:
        return None
    document = repo.find_one("documents", document_id)
    return document.get("projectId") if document else None


def _document_id_from_version(version_id: str | None) -> str | None:
    if not version_id:
        return None
    version = repo.find_one("versions", version_id)
    return version.get("documentId") if version else None


def _knowledge_file(file_id: str | None) -> dict[str, Any] | None:
    if not file_id:
        return None
    return repo.find_one("knowledge_files", file_id)


def _knowledge_file_node_ids(file: dict[str, Any]) -> set[int]:
    node_ids: set[int] = set()
    _add_node_id(node_ids, file.get("nodeId"))
    project_id = file.get("projectId") or _document_project_id(file.get("documentId"))
    if project_id and file.get("documentId"):
        node_ids.update(document_node_ids(project_id, file["documentId"]))
    return node_ids


def knowledge_file_visible_in_scope(file: dict[str, Any], scope: set[int] | None) -> bool:
    if scope is None:
        return True
    if not scope:
        return False
    node_ids = _knowledge_file_node_ids(file)
    return not node_ids or bool(node_ids & scope)


def _target_record(collection: str, record_id: str | None, id_field: str = "id") -> dict[str, Any] | None:
    if not record_id:
        return None
    return repo.find_one(collection, record_id, id_field=id_field)


def record_project_id(record: dict[str, Any]) -> str | None:
    if record.get("projectId"):
        return str(record["projectId"])
    for key in ("documentId",):
        project_id = _document_project_id(record.get(key))
        if project_id:
            return project_id
    if record.get("documentVersionId"):
        project_id = _document_project_id(_document_id_from_version(record.get("documentVersionId")))
        if project_id:
            return project_id
    for key in ("fileId", "targetId"):
        file_id = record.get(key)
        file = _knowledge_file(file_id)
        if file and file.get("projectId"):
            return str(file["projectId"])
        project_id = _document_project_id(file_id)
        if project_id:
            return project_id
    target_type = record.get("targetType")
    target_id = record.get("targetId")
    if target_type == "rectification":
        rectification = _target_record("rectifications", target_id)
        return rectification.get("projectId") if rectification else None
    if target_type == "submission":
        submission = _target_record("submissions", target_id, id_field="submissionId")
        return submission.get("projectId") if submission else None
    if target_type == "report":
        report = _target_record("reports", target_id)
        return report.get("projectId") if report else None
    return None


def record_node_ids(project_id: str, record: dict[str, Any]) -> set[int]:
    node_ids: set[int] = set()
    _add_node_id(node_ids, record.get("nodeId"))
    for node_id in record.get("nodeIds") or []:
        _add_node_id(node_ids, node_id)

    document_id = record.get("documentId") or _document_id_from_version(record.get("documentVersionId"))
    if document_id:
        node_ids.update(document_node_ids(project_id, document_id))

    file_id = record.get("fileId")
    if file_id:
        file = _knowledge_file(file_id)
        if file:
            node_ids.update(_knowledge_file_node_ids(file))
        else:
            node_ids.update(document_node_ids(project_id, file_id))

    film_id = record.get("filmId")
    if not film_id and str(record.get("id", "")).startswith("FILM-"):
        film_id = record.get("id")
    node_ids.update(ndt_film_node_ids(project_id, film_id))

    ndt_report_id = record.get("reportId")
    if not ndt_report_id and str(record.get("id", "")).startswith("NDT-RPT-"):
        ndt_report_id = record.get("id")
    node_ids.update(ndt_report_node_ids(project_id, ndt_report_id))
    for related_film_id in record.get("relatedFilmIds") or []:
        node_ids.update(ndt_film_node_ids(project_id, related_film_id))
    for related_report_id in record.get("relatedReportIds") or []:
        node_ids.update(ndt_report_node_ids(project_id, related_report_id))

    if record.get("reportId"):
        node_ids.update(report_node_ids(project_id, str(record["reportId"])))
    if record.get("exportType") == "report":
        inferred_report_id = record.get("reportId")
        if not inferred_report_id and str(record.get("id", "")).startswith("EXP-RPT-"):
            inferred_report_id = str(record["id"]).replace("EXP-", "", 1)
        if inferred_report_id:
            node_ids.update(report_node_ids(project_id, str(inferred_report_id)))

    target_type = record.get("targetType")
    target_id = record.get("targetId")
    if target_type == "node":
        _add_node_id(node_ids, target_id)
    elif target_type == "rectification":
        rectification = _target_record("rectifications", target_id)
        if rectification:
            _add_node_id(node_ids, rectification.get("nodeId"))
    elif target_type == "submission":
        submission = _target_record("submissions", target_id, id_field="submissionId")
        if submission:
            for node_id in submission.get("nodeIds") or []:
                _add_node_id(node_ids, node_id)
    elif target_type == "report":
        node_ids.update(report_node_ids(project_id, str(target_id)))
    elif target_type == "file":
        file = _knowledge_file(str(target_id))
        if file:
            node_ids.update(_knowledge_file_node_ids(file))
        else:
            node_ids.update(document_node_ids(project_id, str(target_id)))
    return node_ids


def record_references_report(record: dict[str, Any]) -> bool:
    return bool(record.get("reportId")) or record.get("targetType") == "report" or record.get("exportType") == "report"


def ndt_film_node_ids(project_id: str, film_id: str | None) -> set[int]:
    if not film_id:
        return set()
    node_ids: set[int] = set()
    for record in repo.state["ndt_records"]:
        if record.get("projectId") == project_id and record.get("filmId") == film_id:
            _add_node_id(node_ids, record.get("nodeId"))
    for feedback in repo.state["ndt_feedback"]:
        if feedback.get("projectId") == project_id and film_id in set(feedback.get("relatedFilmIds") or []):
            _add_node_id(node_ids, feedback.get("nodeId"))
    for report in repo.state["ndt_reports"]:
        if report.get("projectId") == project_id and film_id in set(report.get("relatedFilmIds") or []):
            node_ids.update(ndt_report_node_ids(project_id, report.get("id")))
    return node_ids


def ndt_report_node_ids(project_id: str, report_id: str | None) -> set[int]:
    if not report_id:
        return set()
    node_ids: set[int] = set()
    report = repo.find_one("ndt_reports", report_id)
    if report and report.get("projectId") == project_id:
        _add_node_id(node_ids, report.get("nodeId"))
        if report.get("fileId"):
            node_ids.update(document_node_ids(project_id, report["fileId"]))
        for film_id in report.get("relatedFilmIds") or []:
            for record in repo.state["ndt_records"]:
                if record.get("projectId") == project_id and record.get("filmId") == film_id:
                    _add_node_id(node_ids, record.get("nodeId"))
            for feedback in repo.state["ndt_feedback"]:
                if feedback.get("projectId") == project_id and film_id in set(feedback.get("relatedFilmIds") or []):
                    _add_node_id(node_ids, feedback.get("nodeId"))
    for record in repo.state["ndt_records"]:
        if record.get("projectId") == project_id and record.get("reportId") == report_id:
            _add_node_id(node_ids, record.get("nodeId"))
    for feedback in repo.state["ndt_feedback"]:
        if feedback.get("projectId") == project_id and report_id in set(feedback.get("relatedReportIds") or []):
            _add_node_id(node_ids, feedback.get("nodeId"))
    return node_ids


def record_visible_for_scope(record: dict[str, Any], scope: set[int] | None, *, project_id: str | None = None) -> bool:
    if scope is None:
        return True
    if not scope:
        return False
    effective_project_id = project_id or record_project_id(record)
    if not effective_project_id:
        return True
    node_ids = record_node_ids(effective_project_id, record)
    if not node_ids:
        return True
    if record_references_report(record):
        return node_ids.issubset(scope)
    return bool(node_ids & scope)


def record_visible_for_request(request: Request, record: dict[str, Any], project_id: str | None = None) -> bool:
    effective_project_id = project_id or record_project_id(record)
    if not effective_project_id:
        return True
    scope = authorized_node_scope(request, effective_project_id)
    return record_visible_for_scope(record, scope, project_id=effective_project_id)


def scope_error_for_record(request: Request, record: dict[str, Any], project_id: str | None = None) -> JSONResponse | None:
    if record_visible_for_request(request, record, project_id):
        return None
    return fail(errors.FORBIDDEN, request, message="用户不在该资源授权范围内。")


def idempotency_fingerprint(source: Any) -> str:
    encoded = json.dumps(source, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def idempotent(request: Request, key: str | None, producer, fingerprint_source: Any | None = None):
    if not key:
        return producer()
    scope = f"{request.method}:{request.url.path}:{key}"
    cached = repo.state["idempotency"].get(scope)
    fingerprint = idempotency_fingerprint(fingerprint_source) if fingerprint_source is not None else None
    if cached is not None:
        if isinstance(cached, dict) and "response" in cached:
            if fingerprint and cached.get("requestHash") and cached["requestHash"] != fingerprint:
                return fail(errors.IDEMPOTENCY_KEY_CONFLICT, request)
            return repo.clone(cached["response"])
        return repo.clone(cached)
    result = producer()
    if not isinstance(result, JSONResponse):
        repo.state["idempotency"][scope] = {
            "requestHash": fingerprint,
            "response": repo.clone(result),
        }
    return result


def filter_keyword(items: list[dict[str, Any]], keyword: str | None, fields: list[str]) -> list[dict[str, Any]]:
    if not keyword:
        return items
    lowered = keyword.lower()
    return [
        item
        for item in items
        if any(lowered in str(item.get(field, "")).lower() for field in fields)
    ]


def signed_url_for_task(task: dict[str, Any]) -> dict[str, Any] | JSONResponse:
    if task["status"] == "已过期":
        return {"error": errors.EXPORT_TASK_EXPIRED}
    if task["status"] != "可下载":
        return {"error": errors.EXPORT_TASK_NOT_READY}
    return repo.signed_get(
        task["fileName"],
        task.get("downloadUrl") or f"mock://download/exports/{task['id']}",
        file_size=task.get("fileSize"),
    )


def admin_user_snapshot(user_id: str | None, role: str | None = None) -> dict[str, Any]:
    users = repo.state["admin_config"].get("users", [])
    user = next((item for item in users if item.get("id") == user_id), None)
    if user is None and role:
        user = next((item for item in users if item.get("role") == role), None)
    if user is None and role == "admin":
        user = {"id": user_id or "USER-ADMIN-001", "name": "系统管理员", "orgName": "省特检院平台组", "role": "admin"}
    return user or {"id": user_id or "USER-UNKNOWN", "name": "新授权成员", "orgName": "联调组织", "role": role or "inspection"}


def scoped_binding_ids(project_id: str, node_ids: list[int], binding_ids: list[str] | None) -> list[str]:
    if binding_ids:
        return binding_ids
    scoped = [
        item["id"]
        for item in repo.state["bindings"]
        if item["projectId"] == project_id
        and int(item["nodeId"]) in set(node_ids)
        and item.get("bindingStatus") != "已通过"
    ]
    return scoped


def build_config_diff(target: str, object_id: str, values: dict[str, Any], *, object_name: str | None = None) -> dict[str, Any]:
    changed = []
    for field, value in values.items():
        if isinstance(value, dict):
            value = ", ".join(f"{key}: {nested}" for key, nested in value.items())
        changed.append(
            {
                "field": field,
                "label": field,
                "before": None,
                "after": value,
                "severity": "info",
            }
        )
    return {
        "target": target,
        "objectId": object_id,
        "objectName": object_name or values.get("name") or values.get("scene") or target,
        "previewedAt": server_time(),
        "changed": changed,
    }


def project_member_snapshot(
    project_id: str,
    role: str,
    user_id: str | None = None,
    *,
    org_name: str | None = None,
    node_scope: list[int] | None = None,
    actions: list[str] | None = None,
) -> dict[str, Any]:
    user = admin_user_snapshot(user_id, role)
    return {
        "id": f"PM-{uuid4().hex[:8].upper()}",
        "projectId": project_id,
        "userId": user_id or user["id"],
        "name": user.get("name") or "授权成员",
        "orgName": org_name or user.get("orgName") or "联调组织",
        "role": role,
        "nodeScope": node_scope or [ROLE_NODE_MAP.get(role, 1)],
        "actions": actions or repo.role_actions(role),
        "status": "启用",
        "updatedAt": server_time(),
        "revision": 1,
    }


def project_detail_payload(project_id: str, request: Request | None = None) -> dict[str, Any] | None:
    project = repo.require_project(project_id)
    if not project:
        return None
    members = [versioned_record("project-member", item) for item in repo.state["project_members"] if item["projectId"] == project_id]
    if request is not None and getattr(request.state, "auth", None) and getattr(request.state, "auth", {}).get("role") != "admin":
        current_user_id = request_user_id(request)
        members = [item for item in members if item.get("userId") == current_user_id]
    scope = authorized_node_scope(request, project_id) if request is not None else None
    node_summary = []
    groups = filter_node_groups_for_scope(repo.node_groups(project_id), scope)
    for group in groups:
        nodes = group["nodes"]
        node_summary.append(
            {
                "groupName": group["groupName"],
                "total": len(nodes),
                "passed": len([item for item in nodes if item.get("status") == "已通过"]),
                "pending": len([item for item in nodes if item.get("status") in {"待提交", "待审查", "待人工确认"}]),
                "correction": len([item for item in nodes if item.get("status") in {"需补正", "补正中"}]),
            }
        )
    return {
        "project": versioned_project(project),
        "members": members,
        "participantUnits": [
            {"unitType": "owner", "unitName": project["ownerOrgName"], "contactName": "赵经理", "contactPhone": "13800000001"},
            {"unitType": "contractor", "unitName": project["contractorOrgName"], "contactName": "李工", "contactPhone": "13800000002"},
            {"unitType": "ndt", "unitName": project["ndtOrgName"], "contactName": "王工", "contactPhone": "13800000003"},
            {"unitType": "inspection", "unitName": project["inspectionOrgName"], "contactName": "张工", "contactPhone": "13800000004"},
        ],
        "nodeSummary": node_summary,
        "recentExportTasks": [repo.clone(item) for item in repo.state["export_tasks"] if item.get("projectId") == project_id],
    }


def business_pack_for_project(project: dict[str, Any] | None) -> dict[str, Any]:
    pack_id = (project or {}).get("businessPackId") or DEFAULT_BUSINESS_PACK_ID
    return load_business_pack(pack_id)


def business_pack_snapshot_for_project(project: dict[str, Any]) -> dict[str, Any]:
    stored = project.get("businessPackSnapshot")
    if isinstance(stored, dict):
        return repo.clone(stored)
    return business_pack_snapshot(business_pack_for_project(project))


def project_defaults_for_pack(pack: dict[str, Any]) -> dict[str, str]:
    if pack.get("domainType") == ENGINEERING_DOMAIN_TYPE:
        return dict(ENGINEERING_PROJECT_DEFAULTS)
    reviewer = next((role for role in pack.get("roles") or [] if role.get("platformRole") == "reviewer"), {})
    submitter = next((role for role in pack.get("roles") or [] if role.get("platformRole") == "submitter"), {})
    observer = next((role for role in pack.get("roles") or [] if role.get("platformRole") == "observer"), {})
    return {
        "name": f"新建{pack['name']}项目",
        "type": pack["name"],
        "ownerOrgName": f"{observer.get('label') or '观察者'}单位",
        "contractorOrgName": f"{submitter.get('label') or '提交者'}单位",
        "ndtOrgName": "专项资料单位",
        "inspectionOrgName": f"{reviewer.get('label') or '审核者'}机构",
    }


def project_requirements_for_node(project_id: str, node_id: int) -> list[dict[str, Any]]:
    scoped = [
        repo.clone(item)
        for item in repo.state["requirements"]
        if int(item["nodeId"]) == int(node_id) and item.get("projectId") == project_id
    ]
    if scoped:
        return scoped
    return [
        repo.clone(item)
        for item in repo.state["requirements"]
        if int(item["nodeId"]) == int(node_id) and not item.get("projectId")
    ]


def attach_business_pack_project_scaffold(project: dict[str, Any], pack: dict[str, Any]) -> tuple[int, int]:
    project_id = project["id"]
    existing_nodes = {item["id"] for item in repo.state["tree_nodes"]}
    nodes = [
        item
        for item in build_project_tree(project_id, pack)
        if item["id"] not in existing_nodes
    ]
    repo.state["tree_nodes"].extend(nodes)
    existing_requirement_keys = {
        (item.get("projectId"), item["id"]) for item in repo.state["requirements"]
    }
    requirements = [
        item
        for item in build_project_requirements(pack, project_id=project_id)
        if (item.get("projectId"), item["id"]) not in existing_requirement_keys
    ]
    repo.state["requirements"].extend(requirements)
    return len(nodes), len(requirements)


def simple_routes(role: str | None = None) -> list[dict[str, Any]]:
    routes = [
        {
            "path": "/workbench",
            "component": "#",
            "redirect": ROLE_DEFAULT_PATHS.get(role or "inspection", "/workbench/inspection"),
            "name": "Workbench",
            "meta": {"title": "业务工作台", "icon": "vi-ep:monitor", "alwaysShow": True, "roles": ["inspection", "contractor", "ndt", "owner"]},
            "children": [
                {"path": "generic", "component": "views/AICheck/GenericReviewWorkbench", "name": "GenericReviewWorkbench", "meta": {"title": "通用资料审查", "roles": ["admin", "inspection", "contractor", "owner"]}},
                {"path": "inspection", "component": "views/AICheck/Workbench", "name": "InspectionWorkbench", "meta": {"title": "监检工作台", "roles": ["inspection"]}},
                {"path": "contractor", "component": "views/AICheck/Workbench", "name": "ContractorWorkbench", "meta": {"title": "施工方工作台", "roles": ["contractor"]}},
                {"path": "ndt", "component": "views/AICheck/Workbench", "name": "NdtWorkbench", "meta": {"title": "无损检测工作台", "roles": ["ndt"]}},
                {"path": "owner", "component": "views/AICheck/Workbench", "name": "OwnerWorkbench", "meta": {"title": "建设方工作台", "roles": ["owner"]}},
            ],
        },
        {
            "path": "/admin",
            "component": "#",
            "redirect": "/admin/overview",
            "name": "AICheckAdmin",
            "meta": {"title": "管理后台", "icon": "vi-ep:setting", "alwaysShow": True, "roles": ["admin"]},
            "children": [
                {"path": item, "component": "views/AICheck/AdminOverview", "name": f"Admin{item.title().replace('-', '')}", "meta": {"title": "项目与权限配置", "roles": ["admin"]}}
                for item in ["overview", "projects", "org", "permission", "rules", "fine-config", "integration", "audit"]
            ],
        },
        {
            "path": "/knowledge",
            "component": "#",
            "redirect": "/knowledge/overview",
            "name": "Knowledge",
            "meta": {"title": "AI 知识库", "icon": "vi-ep:collection", "alwaysShow": True, "roles": ["admin"]},
            "children": [
                {"path": item, "component": "views/AICheck/KnowledgeOverview", "name": f"Knowledge{item.title().replace('-', '')}", "meta": {"title": "AI 知识库管理", "roles": ["admin"]}}
                for item in ["overview", "sources", "files", "tasks", "rules", "retrieval", "reasoning", "compare", "config"]
            ],
        },
        {
            "path": "/fde",
            "component": "#",
            "redirect": "/fde/dashboard",
            "name": "FdeConsole",
            "meta": {"title": "FDE 后台", "icon": "vi-ep:operation", "alwaysShow": True, "roles": sorted(FDE_ROLES)},
            "children": [
                {
                    "path": item["path"],
                    "component": "views/AICheck/FdeConsole",
                    "name": f"Fde{item['path'].title().replace('-', '')}",
                    "meta": {"title": item["title"], "roles": sorted(FDE_ROLES)},
                }
                for item in [
                    {"path": "dashboard", "title": "AI 驾驶舱"},
                    {"path": "ai-runs", "title": "AI Run 追踪"},
                    {"path": "review-runs", "title": "任务编排"},
                    {"path": "feedback", "title": "反馈与标注"},
                    {"path": "evaluation", "title": "评估实验室"},
                    {"path": "capability-bundles", "title": "能力组合"},
                    {"path": "releases", "title": "发布治理"},
                    {"path": "ocr-quality", "title": "OCR 质量"},
                    {"path": "business-packs", "title": "业务包工厂"},
                    {"path": "security", "title": "数据安全"},
                    {"path": "costs", "title": "成本预算"},
                    {"path": "incidents", "title": "事故 RCA"},
                    {"path": "acceptance", "title": "交付验收"},
                ]
            ],
        },
    ]
    return filter_routes_for_role(routes, role) if role else routes


def filter_routes_for_role(routes: list[dict[str, Any]], role: str | None) -> list[dict[str, Any]]:
    if not role:
        return routes
    filtered = []
    for route in routes:
        roles = route.get("meta", {}).get("roles")
        if roles and role not in roles:
            continue
        copy = repo.clone(route)
        if copy.get("children"):
            copy["children"] = filter_routes_for_role(copy["children"], role)
            if not copy["children"]:
                continue
        filtered.append(copy)
    return filtered


@mock_router.post("/mock/user/login")
def mock_login(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    user = authenticate(str(body.get("username", "")), str(body.get("password", "")))
    if not user:
        return fail(errors.AUTH_REQUIRED, request, message="账号或密码错误")
    return ok(user, request)


@mock_router.get("/mock/user/loginOut")
def mock_logout(request: Request):
    return ok(None, request)


@mock_router.get("/mock/role/list")
def mock_role_list(request: Request, roleName: str | None = None):
    user = user_by_username(roleName)
    return ok(simple_routes(user.get("role") if user else None), request)


@mock_router.get("/mock/role/list2")
def mock_role_list2(request: Request):
    return ok(["*.*.*"], request)


@mock_router.get("/mock/user/list")
def mock_user_list(request: Request):
    users = [{key: value for key, value in user.items() if key != "password"} for user in USERS.values()]
    return ok({"list": users, "total": len(users)}, request)


@router.post("/auth/login")
def auth_login(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    user = authenticate(str(body.get("username", "")), str(body.get("password", "")))
    if not user:
        return fail(errors.AUTH_REQUIRED, request, message="账号或密码错误")
    return ok({"token": issue_token(user), "user": user}, request)


@router.post("/auth/logout")
def auth_logout(request: Request):
    return ok(None, request)


@router.get("/auth/me")
def auth_me(request: Request):
    claims = decode_token(request.headers.get("Authorization", ""))
    user = user_by_username(claims.get("sub") if claims else None) or user_by_username("admin")
    role = (user or {}).get("role", "admin")
    user_id = (user or {}).get("id")
    project_authorizations = repo.clone(repo.state["project_members"])
    if role != "admin" and user_id:
        project_authorizations = [item for item in project_authorizations if item.get("userId") == user_id]
    return ok(
        {
            **(user or {}),
            "defaultRole": role,
            "projectAuthorizations": project_authorizations,
        },
        request,
    )


@router.get("/auth/routes")
def auth_routes(request: Request, role: str | None = None):
    return ok(simple_routes(role), request)


@router.get("/auth/actions")
def auth_actions(request: Request, role: str = Query(default="inspection")):
    return ok(repo.role_actions(role), request)


@router.get("/permissions/node-actions")
def node_actions(request: Request, role: str = Query(default="inspection")):
    return ok(repo.role_actions(role), request)


@router.get("/permissions/resources")
def permission_resources(request: Request):
    return ok(repo.state["admin_config"]["permissionMatrix"], request)


@router.get("/business-packs")
def get_business_packs(request: Request):
    return ok(list_business_packs(), request)


@router.post("/business-packs/validate-all")
def validate_all_business_packs_endpoint(request: Request):
    return ok(validate_all_business_packs(), request)


@router.get("/business-packs/{pack_id}")
def get_business_pack(request: Request, pack_id: str):
    try:
        pack = load_business_pack(pack_id)
    except ValueError:
        return fail(errors.NOT_FOUND, request, message="业务包不存在。")
    return ok(
        {
            "summary": business_pack_summary(pack),
            "roles": repo.clone(pack["roles"]),
            "nodeTemplates": repo.clone(pack["nodeTemplates"]),
            "materialTypes": repo.clone(pack["materialTypes"]),
            "workflowStateMachines": repo.clone(pack["workflowStateMachines"]),
            "ruleSets": repo.clone(pack["ruleSets"]),
            "reportTemplates": repo.clone(pack["reportTemplates"]),
            "agentSops": repo.clone(pack.get("agentSops") or []),
        },
        request,
    )


@router.get("/business-packs/{pack_id}/snapshot")
def get_business_pack_snapshot(request: Request, pack_id: str):
    try:
        pack = load_business_pack(pack_id)
    except ValueError:
        return fail(errors.NOT_FOUND, request, message="业务包不存在。")
    return ok(business_pack_snapshot(pack), request)


@router.post("/business-packs/{pack_id}/validate")
def validate_business_pack_endpoint(request: Request, pack_id: str):
    try:
        pack = load_business_pack(pack_id)
    except ValueError as exc:
        return fail(errors.NOT_FOUND, request, message=str(exc))
    return ok({"summary": business_pack_summary(pack), "validation": validate_business_pack(pack)}, request)


@router.get("/workbench/projects")
def list_workbench_projects(
    request: Request,
    role: str = Query(default="inspection"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    resolved_role, role_error = resolved_role_for_read(request, role, x_role)
    if role_error:
        return role_error
    items = [item for item in repo.state["projects"] if project_visible_for_request(request, item["id"])]
    return ok([versioned_project(repo.project_for_role(item, resolved_role)) for item in items], request)


@router.get("/projects")
def list_projects(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), keyword: str | None = None):
    items = [versioned_project(item) for item in repo.state["projects"] if project_visible_for_request(request, item["id"])]
    items = filter_keyword(items, keyword, ["name", "code", "region"])
    return ok(page(items, page_no, page_size), request)


@router.post("/projects")
def create_project(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    return create_admin_project(request, body, idempotency_key)


@router.get("/projects/{project_id}")
def get_project_detail(request: Request, project_id: str):
    detail = project_detail_payload(project_id, request)
    if not detail:
        return fail(errors.NOT_FOUND, request)
    return ok(detail, request)


@router.patch("/projects/{project_id}")
def update_project(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, if_match=if_match)
        if guard:
            return guard
        project = repo.require_project(project_id)
        if not project:
            return fail(errors.NOT_FOUND, request)
        changed = []
        for field in ["name", "type", "region", "ownerOrgName", "contractorOrgName", "ndtOrgName", "inspectionOrgName"]:
            if field in body and project.get(field) != body[field]:
                changed.append({"field": field, "before": project.get(field), "after": body[field]})
                project[field] = body[field]
        if changed:
            repo.touch_project(project_id)
        return ok({"project": versioned_project(project), **repo.mutation_result("更新项目", "Project", project_id, changed=changed)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"projectId": project_id, "body": body})


@router.post("/projects/{project_id}/business-pack/apply")
def apply_business_pack(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, if_match="*")
        if guard:
            return guard
        project = repo.require_project(project_id)
        if not project:
            return fail(errors.NOT_FOUND, request)
        pack_id = body.get("businessPackId") or project.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID
        try:
            pack = load_business_pack(pack_id)
        except ValueError as exc:
            return fail(errors.VALIDATION_ERROR, request, message=str(exc))
        project.update(
            {
                "businessPackId": pack["id"],
                "businessPackVersion": pack["version"],
                "domainType": pack["domainType"],
                "businessPackSnapshotHash": pack["snapshotHash"],
                "businessPackSnapshot": business_pack_snapshot(pack),
            }
        )
        created_node_count, created_requirement_count = attach_business_pack_project_scaffold(project, pack)
        repo.touch_project(project_id)
        audit_id = repo.add_audit("应用业务包", "BusinessPack", pack["id"])
        return ok(
            {
                "project": versioned_project(project),
                "businessPack": business_pack_summary(pack),
                "createdNodeCount": created_node_count,
                "createdRequirementCount": created_requirement_count,
                "auditLogId": audit_id,
            },
            request,
        )

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "body": body},
    )


@router.get("/projects/{project_id}/business-pack/snapshot")
def get_project_business_pack_snapshot(request: Request, project_id: str):
    project = repo.require_project(project_id)
    if not project:
        return fail(errors.NOT_FOUND, request)
    snapshot = business_pack_snapshot_for_project(project)
    return ok(
        {
            "projectId": project_id,
            "businessPackId": project.get("businessPackId"),
            "businessPackVersion": project.get("businessPackVersion"),
            "businessPackSnapshotHash": project.get("businessPackSnapshotHash"),
            "snapshotMatchesCurrent": project.get("businessPackSnapshotHash") == snapshot.get("snapshotHash"),
            "snapshot": snapshot,
        },
        request,
    )


@router.get("/projects/{project_id}/participants")
def list_participants(request: Request, project_id: str):
    detail = get_project_detail(request, project_id)
    if isinstance(detail, JSONResponse):
        return detail
    return ok(detail["data"]["participantUnits"], request)


@router.post("/projects/{project_id}/participants")
def save_participant(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        participant_id = body.get("id") or f"PU-{uuid4().hex[:8].upper()}"
        repo.touch_project(project_id)
        return ok({**repo.mutation_result("保存参建单位", "ProjectUnit", participant_id), "project": versioned_project(repo.require_project(project_id))}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"projectId": project_id, "body": body})


@router.patch("/projects/{project_id}/participants/{participant_id}")
def update_participant(
    request: Request,
    project_id: str,
    participant_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        repo.touch_project(project_id)
        return ok({**repo.mutation_result("更新参建单位", "ProjectUnit", participant_id, changed=[{"field": "values", "after": body}]), "project": versioned_project(repo.require_project(project_id))}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"projectId": project_id, "participantId": participant_id, "body": body})


@router.get("/projects/{project_id}/members")
def list_project_members(request: Request, project_id: str, role: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [versioned_record("project-member", item) for item in repo.state["project_members"] if item["projectId"] == project_id]
    if role:
        items = [item for item in items if item["role"] == role]
    return ok(page(items, page_no, page_size), request)


@router.post("/projects/{project_id}/members")
def authorize_member(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        role = body.get("role", "inspection")
        user = admin_user_snapshot(body.get("userId"), role)
        user_id = body.get("userId") or user["id"]
        incoming_scope = body.get("nodeScope") or [ROLE_NODE_MAP.get(role, 24)]
        existing = next(
            (
                item
                for item in repo.state["project_members"]
                if item.get("projectId") == project_id
                and item.get("userId") == user_id
                and item.get("role") == role
            ),
            None,
        )
        if existing:
            merged_scope = list(dict.fromkeys([*(existing.get("nodeScope") or []), *incoming_scope]))
            existing.update(
                {
                    "name": body.get("name") or existing.get("name") or user.get("name") or "新授权成员",
                    "orgName": body.get("orgName") or existing.get("orgName") or user.get("orgName") or "联调组织",
                    "nodeScope": merged_scope,
                    "actions": body.get("actions") or existing.get("actions") or repo.role_actions(role),
                    "status": "启用",
                    "expiresAt": body.get("expiresAt") or existing.get("expiresAt"),
                    "updatedAt": server_time(),
                }
            )
            bump_record_revision(existing)
            repo.touch_project(project_id)
            audit_id = repo.add_audit("更新项目成员授权", "ProjectMember", existing["id"])
            return ok({"member": versioned_record("project-member", existing), "auditLogId": audit_id}, request)

        member = {
            "id": f"PM-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "userId": user_id,
            "name": body.get("name") or user.get("name") or "新授权成员",
            "orgName": body.get("orgName") or user.get("orgName") or "联调组织",
            "role": role,
            "nodeScope": incoming_scope,
            "actions": body.get("actions") or repo.role_actions(role),
            "status": "启用",
            "expiresAt": body.get("expiresAt"),
            "updatedAt": server_time(),
            "revision": 1,
        }
        repo.state["project_members"].insert(0, member)
        repo.touch_project(project_id)
        audit_id = repo.add_audit("项目成员授权", "ProjectMember", member["id"])
        return ok({"member": versioned_record("project-member", member), "auditLogId": audit_id}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source=body,
    )


@router.put("/projects/{project_id}/members/{member_id}")
def update_member(
    request: Request,
    project_id: str,
    member_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, if_match="*")
        if guard:
            return guard
        member = repo.find_one("project_members", member_id)
        if not member or member.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request, message="项目成员不存在。")
        if not record_if_match_valid("project-member", member, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        changed = []
        for field in ["role", "nodeScope", "actions", "status", "expiresAt"]:
            if field in body and member.get(field) != body[field]:
                changed.append({"field": field, "before": member.get(field), "after": body[field]})
                member[field] = body[field]
        if changed:
            bump_record_revision(member)
            repo.touch_project(project_id)
        audit_id = repo.add_audit("更新项目成员授权", "ProjectMember", member_id)
        return ok({"member": versioned_record("project-member", member), "auditLogId": audit_id, "changed": changed}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"memberId": member_id, "body": body})


@router.post("/projects/{project_id}/initialize-workflow")
def initialize_workflow(
    request: Request,
    project_id: str,
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        repo.touch_project(project_id, "草稿/立项中", 1)
        node_count = len([item for item in repo.state["tree_nodes"] if item.get("projectId") == project_id])
        return ok(
            {
                **repo.mutation_result("初始化项目节点流程", "Project", project_id),
                "createdNodeCount": node_count,
                "project": versioned_project(repo.require_project(project_id)),
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source={"projectId": project_id})


@router.get("/projects/{project_id}/workbench/context")
def workbench_context(request: Request, project_id: str, role: str = Query(default="inspection"), x_role: str | None = Header(default=None, alias="X-Role")):
    project = repo.require_project(project_id)
    if not project:
        return fail(errors.NOT_FOUND, request)
    resolved_role, role_error = resolved_role_for_read(request, role, x_role)
    if role_error:
        return role_error
    scope = authorized_node_scope(request, project_id)
    visible_todos = [
        item
        for item in repo.state["todos"]
        if item.get("projectId") == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    visible_messages = [
        item
        for item in repo.state["messages"]
        if item.get("projectId") == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    current_node_id = ROLE_NODE_MAP.get(resolved_role, project.get("currentNodeId", 24))
    role_project = repo.project_for_role(project, resolved_role)
    return ok(
        {
            "project": role_project,
            "role": resolved_role,
            "currentNodeId": current_node_id,
            "topbar": {
                "todoCount": len(visible_todos),
                "messageCount": len([item for item in visible_messages if not item.get("read")]),
                "statusText": project.get("status"),
                "projectSwitcherEnabled": True,
            },
            "actions": role_project["actions"],
        },
        request,
    )


@router.get("/projects/{project_id}/workbench/summary")
def workbench_summary(request: Request, project_id: str, role: str = Query(default="inspection")):
    resolved_role, role_error = resolved_role_for_read(request, role)
    if role_error:
        return role_error
    scope = authorized_node_scope(request, project_id)
    role_todos = [
        item
        for item in repo.state["todos"]
        if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    visible_nodes = [
        item
        for item in repo.state["tree_nodes"]
        if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    visible_documents = [
        item
        for item in repo.project_documents(project_id)
        if document_visible_in_scope(item, scope)
    ]
    visible_reports = [
        item
        for item in repo.state["reports"]
        if item["projectId"] == project_id and report_visible_in_scope(item, scope)
    ]
    visible_messages = [
        item
        for item in repo.state["messages"]
        if item.get("projectId") == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    correction_count = len([item for item in visible_nodes if item["status"] in {"需补正", "补正中"}])
    metrics = [
        {"key": "todo", "label": "待办", "value": len(role_todos), "tone": "orange"},
        {"key": "correction", "label": "补正", "value": correction_count, "tone": "red"},
        {"key": "document", "label": "资料", "value": len(visible_documents), "tone": "blue"},
        {"key": "report", "label": "报告", "value": len(visible_reports), "tone": "green"},
    ]
    if resolved_role == "owner":
        metrics = [
            {"key": "progress", "label": "总体进度", "value": "42%", "tone": "blue"},
            {"key": "report", "label": "报告版本", "value": len(visible_reports), "tone": "green"},
            {"key": "archive", "label": "归档资料", "value": len([item for item in repo.state["archive_items"] if item.get("projectId") == project_id and archive_visible_in_scope(item, scope)]), "tone": "gray"},
        ]
    return ok(
        {
            "metrics": metrics,
            "todos": [repo.clone(item) for item in role_todos[:5]],
            "messages": [repo.clone(item) for item in visible_messages[:5]],
            "updatedAt": server_time(),
        },
        request,
    )


@router.get("/projects/{project_id}/tree")
def project_tree(request: Request, project_id: str):
    project = repo.require_project(project_id)
    if not project:
        return fail(errors.NOT_FOUND, request)
    scope = authorized_node_scope(request, project_id)
    groups = filter_node_groups_for_scope(repo.node_groups(project_id), scope)
    return ok({"project": repo.clone(project), "groups": groups}, request)


@router.get("/projects/{project_id}/nodes/{node_id}")
def node_detail(request: Request, project_id: str, node_id: int):
    node = repo.node(project_id, node_id)
    if not node:
        return fail(errors.NOT_FOUND, request)
    return ok({"node": repo.clone(node)}, request)


@router.get("/projects/{project_id}/nodes/{node_id}/requirements")
def node_requirements(request: Request, project_id: str, node_id: int):
    return ok(project_requirements_for_node(project_id, node_id), request)


@router.get("/projects/{project_id}/nodes/{node_id}/package")
def node_package(request: Request, project_id: str, node_id: int):
    effective_project_id = project_id
    node = repo.node(effective_project_id, node_id)
    if not node:
        return fail(errors.NOT_FOUND, request)
    scope = authorized_node_scope(request, project_id)
    bindings = repo.bindings_for_node(effective_project_id, node_id)
    version_ids = {item["documentVersionId"] for item in bindings}
    project_files = [
        item
        for item in repo.project_documents(effective_project_id)
        if document_visible_in_scope(item, scope)
    ]
    visible_document_ids = {item["id"] for item in project_files}
    return ok(
        {
            "node": repo.clone(node),
            "requirements": project_requirements_for_node(project_id, node_id),
            "bindings": bindings,
            "projectFiles": project_files,
            "availableVersions": [
                repo.clone(item)
                for item in repo.state["versions"]
                if item["id"] in version_ids or item.get("documentId") in visible_document_ids
            ],
            "extractedFields": repo.fields_for_versions(version_ids),
            "reviewOpinions": [repo.clone(item) for item in repo.state["review_opinions"] if item["projectId"] == effective_project_id and int(item["nodeId"]) == int(node_id)],
            "aiRuns": [repo.clone(item) for item in repo.state["ai_runs"] if item["projectId"] == effective_project_id and int(item["nodeId"]) == int(node_id)],
            "actions": repo.clone(node.get("actions", [])),
        },
        request,
    )


@router.get("/projects/{project_id}/documents")
def list_documents(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), keyword: str | None = None, nodeId: int | None = None):
    scope = authorized_node_scope(request, project_id)
    effective_project_id = project_id
    items = [
        item
        for item in repo.project_documents(effective_project_id)
        if document_visible_in_scope(item, scope)
    ]
    if nodeId:
        document_ids = {
            binding["documentId"]
            for binding in repo.state["bindings"]
            if binding.get("projectId") == effective_project_id and int(binding.get("nodeId")) == int(nodeId)
        }
        items = [item for item in items if item["id"] in document_ids]
    items = filter_keyword(items, keyword, ["fileName", "sourceOrgName"])
    return ok(page(items, page_no, page_size), request)


@router.get("/projects/{project_id}/documents/bindings")
def list_bindings(request: Request, project_id: str, nodeId: int | None = None):
    scope = authorized_node_scope(request, project_id)
    items = repo.bindings_for_project(project_id)
    if scope is not None:
        items = [item for item in items if int(item["nodeId"]) in scope]
    if nodeId:
        items = [item for item in items if int(item["nodeId"]) == int(nodeId)]
    return ok(items, request)


@router.post("/projects/{project_id}/documents/upload-session")
def create_upload_session(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        files = body.get("files") or []
        validation_error = validate_upload_files(request, files)
        if validation_error:
            return validation_error
        session_id, upload_urls = repo.create_upload_session(project_id, files)
        repo.add_audit("创建上传会话", "UploadSession", session_id)
        return ok({"uploadSessionId": session_id, "expiresAt": upload_urls[0]["expiresAt"], "uploadUrls": upload_urls}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source=body,
    )


@router.post("/projects/{project_id}/documents/upload-session/{session_id}/complete")
def complete_upload_session(
    request: Request,
    project_id: str,
    session_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        session = repo.find_one("upload_sessions", session_id)
        if not session or session.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        files = repo.complete_upload_session(session_id)
        dispatches = []
        for file in files:
            dispatches.append(
                task_dispatcher.dispatch_parse_document(
                    file["documentId"],
                    file["documentVersionId"],
                    file["storageKey"],
                    file.get("fileName"),
                )
            )
        result = repo.mutation_result("完成上传会话", "UploadSession", session_id, next_status="排队中")
        return ok({**result, "queuedTasks": dispatches, "fileCount": len(files)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"sessionId": session_id, "body": body})


@router.get("/projects/{project_id}/documents/{document_id}")
def document_detail(request: Request, project_id: str, document_id: str):
    document = repo.find_one("documents", document_id)
    if not document or document.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    versions = repo.versions_for_document(document_id)
    version_ids = {item["id"] for item in versions}
    preview = repo.document_preview(document)
    return ok(
        {
            "document": repo.clone(document),
            "currentVersion": repo.current_version(document_id),
            "versions": versions,
            "bindings": [item for item in repo.bindings_for_project(document["projectId"]) if item["documentId"] == document_id],
            "extractedFields": repo.fields_for_versions(version_ids),
            "evidenceLinks": repo.evidence_for_versions(version_ids),
            "preview": preview,
            "download": repo.document_download(document),
        },
        request,
    )


@router.get("/projects/{project_id}/documents/{document_id}/versions")
def document_versions(request: Request, project_id: str, document_id: str):
    return ok(repo.versions_for_document(document_id), request)


@router.get("/projects/{project_id}/documents/{document_id}/preview-url")
def document_preview_url(request: Request, project_id: str, document_id: str):
    document = repo.find_one("documents", document_id)
    if not document or document.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    return ok(repo.document_preview(document), request)


@router.get("/projects/{project_id}/documents/{document_id}/download-url")
def document_download_url(request: Request, project_id: str, document_id: str):
    document = repo.find_one("documents", document_id)
    if not document or document.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    return ok(repo.document_download(document), request)


@router.get("/projects/{project_id}/documents/{document_id}/ocr-fields")
def document_ocr_fields(request: Request, project_id: str, document_id: str):
    versions = repo.versions_for_document(document_id)
    return ok(repo.fields_for_versions({item["id"] for item in versions}), request)


@router.get("/projects/{project_id}/documents/{document_id}/review-feedback")
def document_review_feedback(request: Request, project_id: str, document_id: str):
    return ok({"opinions": repo.clone(repo.state["review_opinions"]), "rectifications": repo.clone(repo.state["rectifications"])}, request)


@router.post("/projects/{project_id}/documents/{document_id}/versions")
def append_document_version(
    request: Request,
    project_id: str,
    document_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=document_node_ids(project_id, document_id))
        if guard:
            return guard
        document = repo.find_one("documents", document_id)
        if not document or document.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        version_id = f"DV-{uuid4().hex[:8].upper()}-V{len(repo.versions_for_document(document_id)) + 1}"
        for version in repo.state["versions"]:
            if version["documentId"] == document_id:
                version["isCurrent"] = False
        version = {
            "id": version_id,
            "documentId": document_id,
            "versionNo": f"V{len(repo.versions_for_document(document_id)) + 1}",
            "hash": f"mock-sha256-{version_id}",
            "fileSize": int(body.get("fileSize") or 245760),
            "storageKey": f"documents/{project_id}/{version_id}",
            "ocrStatus": "排队中",
            "sliceStatus": "未切片",
            "vectorStatus": "未向量化",
            "uploaderName": "李工",
            "uploadTime": server_time(),
            "isCurrent": True,
        }
        repo.state["versions"].insert(0, version)
        document["currentVersionId"] = version_id
        document["fileStatus"] = "已追加版本" if body.get("mode") == "append" else "已替换"
        document["updatedAt"] = server_time()
        return ok({"version": version, **repo.mutation_result("新增文件版本", "DocumentVersion", version_id, next_status=document["fileStatus"])}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"documentId": document_id, "body": body})


@router.post("/projects/{project_id}/documents/bindings")
def bind_documents(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    node_ids = node_ids_from_body(body, ROLE_NODE_MAP["contractor"])

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        binding_inputs = body.get("bindings") or []
        if not binding_inputs:
            return fail(errors.EMPTY_BINDINGS, request)
        created = []
        changed = []
        for node_id in node_ids:
            requirements = [item for item in repo.state["requirements"] if int(item["nodeId"]) == node_id]
            for index, binding_input in enumerate(binding_inputs):
                document = repo.find_one("documents", binding_input.get("documentId"))
                version_id = binding_input.get("documentVersionId") or (document or {}).get("currentVersionId")
                if not document or not version_id:
                    continue
                requirement = requirements[index % len(requirements)] if requirements else None
                binding = {
                    "id": f"BIND-{node_id}-{uuid4().hex[:6].upper()}",
                    "projectId": project_id,
                    "nodeId": node_id,
                    "requirementId": requirement.get("id") if requirement else None,
                    "requirementName": requirement.get("name") if requirement else None,
                    "documentId": document["id"],
                    "documentVersionId": version_id,
                    "fileName": document["fileName"],
                    "versionNo": "V1",
                    "usage": binding_input.get("usage") or body.get("usage") or "原始提交",
                    "sourceOrgName": document["sourceOrgName"],
                    "bindingStatus": "草稿挂载",
                    "boundByName": "李工",
                    "boundAt": server_time(),
                    "actions": ["submission:submit", "submission:withdraw"],
                }
                repo.state["bindings"].insert(0, binding)
                created.append(binding["id"])
            changed.append(repo.set_node_status(project_id, node_id, "部分提交"))
        return ok(repo.mutation_result("保存节点挂载关系", "NodeFileBinding", created[0] if created else "BIND-EMPTY", next_status="部分提交", changed=changed, affected_ids=created), request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source=body,
    )


@router.patch("/projects/{project_id}/documents/bindings/{binding_id}")
def update_binding(
    request: Request,
    project_id: str,
    binding_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=binding_node_ids(project_id, binding_id))
        if guard:
            return guard
        binding = repo.find_one("bindings", binding_id)
        if not binding or binding.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        changed = []
        for field in ["requirementId", "requirementName", "usage", "bindingStatus"]:
            if field in body and binding.get(field) != body[field]:
                changed.append({"field": field, "before": binding.get(field), "after": body[field]})
                binding[field] = body[field]
        return ok({**repo.mutation_result("更新挂载关系", "NodeFileBinding", binding_id, changed=changed), "binding": repo.clone(binding)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"bindingId": binding_id, "body": body})


@router.delete("/projects/{project_id}/documents/bindings/{binding_id}")
def delete_binding(
    request: Request,
    project_id: str,
    binding_id: str,
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=binding_node_ids(project_id, binding_id))
        if guard:
            return guard
        binding = repo.find_one("bindings", binding_id)
        if not binding or binding.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        before = len(repo.state["bindings"])
        repo.state["bindings"] = [item for item in repo.state["bindings"] if item["id"] != binding_id]
        if len(repo.state["bindings"]) == before:
            return fail(errors.NOT_FOUND, request)
        return ok({**repo.mutation_result("解除草稿挂载", "NodeFileBinding", binding_id, next_status="已解除挂载"), "binding": repo.clone(binding)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"bindingId": binding_id})


@router.post("/projects/{project_id}/documents/{document_id}/withdraw")
def withdraw_document(
    request: Request,
    project_id: str,
    document_id: str,
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=document_node_ids(project_id, document_id))
        if guard:
            return guard
        doc = repo.find_one("documents", document_id)
        if not doc or doc.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        doc["fileStatus"] = "已撤回"
        doc["updatedAt"] = server_time()
        return ok({**repo.mutation_result("撤回文件", "Document", document_id, next_status="已撤回"), "document": repo.clone(doc)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"documentId": document_id})


@router.post("/projects/{project_id}/documents/{document_id}/void")
def void_document(
    request: Request,
    project_id: str,
    document_id: str,
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=document_node_ids(project_id, document_id))
        if guard:
            return guard
        doc = repo.find_one("documents", document_id)
        if not doc or doc.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        doc["fileStatus"] = "已作废"
        doc["updatedAt"] = server_time()
        return ok({**repo.mutation_result("作废文件", "Document", document_id, next_status="已作废"), "document": repo.clone(doc)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"documentId": document_id})


@router.post("/projects/{project_id}/documents/batch-classify")
def batch_classify_documents(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        suggestions = [
            {"documentId": doc["id"], "fileName": doc["fileName"], "suggestedNodeIds": [24 if "焊工" in doc["fileName"] else 16], "confidence": 0.82}
            for doc in repo.project_documents(project_id)
        ]
        audit_id = repo.add_audit("批量资料智能分类", "Document", project_id)
        return ok({"suggestions": suggestions, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"projectId": project_id, "body": body})


@router.post("/projects/{project_id}/submissions/drafts")
def save_submission_draft(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    node_ids = node_ids_from_body(body, ROLE_NODE_MAP["contractor"])

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        draft_id = f"DRAFT-{uuid4().hex[:8].upper()}"
        binding_ids = scoped_binding_ids(project_id, node_ids, body.get("bindingIds") or [])
        if not binding_ids:
            return fail(errors.EMPTY_NODE_PACKAGE, request)
        draft = {
            "draftId": draft_id,
            "projectId": project_id,
            "nodeIds": node_ids,
            "bindingIds": binding_ids,
            "batchName": body.get("batchName"),
            "remark": body.get("remark"),
            "savedAt": server_time(),
        }
        repo.state["submission_drafts"].insert(0, draft)
        repo.add_audit("保存提交草稿", "SubmissionDraft", draft_id)
        return ok({"draftId": draft_id, "savedAt": draft["savedAt"], "bindingIds": binding_ids}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


def draft_summary(draft: dict[str, Any]) -> dict[str, Any]:
    nodes = [repo.node(draft["projectId"], node_id) for node_id in draft.get("nodeIds", [])]
    return {
        "draftId": draft["draftId"],
        "projectId": draft["projectId"],
        "nodeIds": draft.get("nodeIds", []),
        "nodeNames": [node["name"] for node in nodes if node],
        "bindingCount": len(draft.get("bindingIds", [])),
        "batchName": draft.get("batchName"),
        "remark": draft.get("remark"),
        "savedAt": draft["savedAt"],
    }


def submission_summary(submission: dict[str, Any]) -> dict[str, Any]:
    nodes = [repo.node(submission["projectId"], node_id) for node_id in submission.get("nodeIds", [])]
    return {
        "submissionId": submission["submissionId"],
        "snapshotId": submission["snapshotId"],
        "projectId": submission["projectId"],
        "nodeIds": submission.get("nodeIds", []),
        "nodeNames": [node["name"] for node in nodes if node],
        "bindingCount": len(submission.get("bindingIds", [])),
        "todoCount": len(submission.get("createdTodoIds", [])),
        "batchName": submission.get("batchName"),
        "submitterComment": submission.get("submitterComment"),
        "nextStatus": submission.get("nextStatus"),
        "submittedAt": submission["submittedAt"],
        "withdrawal": submission.get("withdrawal"),
    }


@router.get("/projects/{project_id}/submissions")
def list_submissions(request: Request, project_id: str):
    drafts = [draft_summary(item) for item in repo.state["submission_drafts"] if item["projectId"] == project_id]
    submissions = [submission_summary(item) for item in repo.state["submissions"] if item["projectId"] == project_id]
    return ok({"drafts": drafts, "submissions": submissions}, request)


@router.get("/projects/{project_id}/submissions/drafts/{draft_id}")
def get_submission_draft(request: Request, project_id: str, draft_id: str):
    draft = next((item for item in repo.state["submission_drafts"] if item["projectId"] == project_id and item["draftId"] == draft_id), None)
    if not draft:
        return fail(errors.NOT_FOUND, request)
    bindings = [item for item in repo.bindings_for_project(project_id) if item["id"] in set(draft.get("bindingIds", []))]
    nodes = [repo.node(project_id, node_id) for node_id in draft.get("nodeIds", [])]
    return ok({**draft_summary(draft), "nodes": [repo.clone(item) for item in nodes if item], "bindings": bindings}, request)


@router.post("/projects/{project_id}/submissions")
def submit_node_package(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    node_ids = node_ids_from_body(body, ROLE_NODE_MAP["contractor"])

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        submission_id = f"SUB-{uuid4().hex[:8].upper()}"
        snapshot_id = f"SNAP-{uuid4().hex[:8].upper()}"
        binding_ids = scoped_binding_ids(project_id, node_ids, body.get("bindingIds") or [])
        if not binding_ids:
            return fail(errors.EMPTY_NODE_PACKAGE, request)
        changed = []
        for binding in repo.state["bindings"]:
            if binding["id"] in binding_ids:
                binding["bindingStatus"] = "已提交"
        for node_id in node_ids:
            changed.append(repo.set_node_status(project_id, node_id, "AI 预审中"))
        todo_id = f"TODO-{uuid4().hex[:8].upper()}"
        repo.state["todos"].insert(
            0,
            {
                "id": todo_id,
                "title": "节点资料已提交，待 AI 预审",
                "projectId": project_id,
                "nodeId": node_ids[0] if node_ids else None,
                "targetType": "submission",
                "targetId": submission_id,
                "status": "待处理",
                "priority": "中",
                "assigneeName": "张工",
                "actions": ["ai:recheck"],
            },
        )
        submission = {
            "submissionId": submission_id,
            "snapshotId": snapshot_id,
            "projectId": project_id,
            "nodeIds": node_ids,
            "bindingIds": binding_ids,
            "batchName": body.get("batchName"),
            "submitterComment": body.get("submitterComment"),
            "nextStatus": "AI 预审中",
            "submittedAt": server_time(),
            "createdTodoIds": [todo_id],
            "changed": changed,
        }
        repo.state["submissions"].insert(0, submission)
        return ok({"submissionId": submission_id, "snapshotId": snapshot_id, "nextStatus": "AI 预审中", "createdTodos": [repo.state["todos"][0]]}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/submissions/{submission_id}")
def get_submission_detail(request: Request, project_id: str, submission_id: str):
    submission = next((item for item in repo.state["submissions"] if item["projectId"] == project_id and item["submissionId"] == submission_id), None)
    if not submission:
        return fail(errors.NOT_FOUND, request)
    bindings = [item for item in repo.bindings_for_project(project_id) if item["id"] in set(submission.get("bindingIds", []))]
    nodes = [repo.node(project_id, node_id) for node_id in submission.get("nodeIds", [])]
    todos = [item for item in repo.state["todos"] if item["id"] in set(submission.get("createdTodoIds", []))]
    return ok(
        {
            **submission_summary(submission),
            "submissionType": submission.get("submissionType", "document"),
            "nodes": [repo.clone(item) for item in nodes if item],
            "bindings": bindings,
            "createdTodos": todos,
            "changed": submission.get("changed", []),
            "snapshot": repo.clone(submission.get("snapshot")),
        },
        request,
    )


@router.post("/projects/{project_id}/submissions/{submission_id}/withdraw-items")
def withdraw_submission_items(
    request: Request,
    project_id: str,
    submission_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        binding_ids = [str(item) for item in (body.get("bindingIds") or []) if item]
        if not binding_ids:
            return fail(errors.EMPTY_BINDINGS, request)
        requested_ids = set(binding_ids)
        submission = next(
            (
                item
                for item in repo.state["submissions"]
                if item["projectId"] == project_id and item["submissionId"] == submission_id
            ),
            None,
        )
        if not submission:
            return fail(errors.NOT_FOUND, request)
        submitted_ids = set(submission.get("bindingIds") or [])
        invalid_ids = sorted(requested_ids - submitted_ids)
        if invalid_ids:
            return fail(
                errors.CONFLICT,
                request,
                message="只能撤回当前提交批次内的资料。",
                data={"invalidBindingIds": invalid_ids},
            )
        binding_by_id = {
            binding["id"]: binding
            for binding in repo.state["bindings"]
            if binding.get("projectId") == project_id and binding["id"] in requested_ids
        }
        missing_ids = sorted(requested_ids - set(binding_by_id))
        if missing_ids:
            return fail(errors.NOT_FOUND, request, data={"missingBindingIds": missing_ids})
        locked_ids = sorted(
            binding["id"]
            for binding in binding_by_id.values()
            if binding.get("bindingStatus") in {"已通过", "已锁定", "已归档"}
        )
        if locked_ids:
            return fail(errors.WITHDRAW_LOCKED, request, data={"lockedBindingIds": locked_ids})
        for binding in binding_by_id.values():
            binding["bindingStatus"] = "草稿挂载"
        withdrawn_ids = sorted(set(submission.get("withdrawnBindingIds") or []) | requested_ids)
        submission["withdrawnBindingIds"] = withdrawn_ids
        submission["withdrawal"] = {
            "bindingCount": len(withdrawn_ids),
            "reason": body.get("reason") or "撤回未提交项",
            "withdrawnAt": server_time(),
        }
        submission["nextStatus"] = "部分提交"
        node_ids = sorted({int(item["nodeId"]) for item in binding_by_id.values()})
        changed = [repo.set_node_status(project_id, node_id, "部分提交") for node_id in node_ids]
        return ok(repo.mutation_result("撤回未提交项", "Submission", submission_id, next_status="部分提交", changed=changed, affected_ids=binding_ids), request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/projects/{project_id}/rectifications")
def submit_rectification(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    node_ids = node_ids_from_body(body, ROLE_NODE_MAP["contractor"])

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        node_id = node_ids[0] if node_ids else ROLE_NODE_MAP["contractor"]
        node = repo.node(project_id, node_id)
        if not node:
            return fail(errors.NOT_FOUND, request)
        binding_ids = [str(item) for item in (body.get("bindingIds") or []) if item]
        if not binding_ids:
            return fail(errors.EMPTY_BINDINGS, request)
        node_binding_ids = {item["id"] for item in repo.state["bindings"] if item["projectId"] == project_id and int(item["nodeId"]) == node_id}
        invalid_binding_ids = sorted(set(binding_ids) - node_binding_ids)
        if invalid_binding_ids:
            return fail(
                errors.CONFLICT,
                request,
                message="补正反馈资料必须属于当前节点。",
                data={"invalidBindingIds": invalid_binding_ids},
            )
        rectification_id = body.get("rectificationId")
        if rectification_id:
            rectification = next(
                (
                    item
                    for item in repo.state["rectifications"]
                    if item["projectId"] == project_id and item["id"] == rectification_id
                ),
                None,
            )
            if not rectification:
                return fail(errors.NOT_FOUND, request)
            if int(rectification["nodeId"]) != node_id:
                return fail(errors.CONFLICT, request, message="补正单不属于当前节点。")
        else:
            rectification = next(
                (
                    item
                    for item in repo.state["rectifications"]
                    if item["projectId"] == project_id and int(item["nodeId"]) == node_id and item.get("status") == "待反馈"
                ),
                None,
            )
            if not rectification:
                return fail(errors.CONFLICT, request, message="当前节点没有待反馈补正单。")
        if rectification.get("status") != "待反馈":
            return fail(errors.CONFLICT, request, message="补正单当前状态不允许提交反馈。")
        rectification["status"] = "已反馈"
        rectification["comment"] = body.get("comment") or body.get("description")
        rectification["bindingIds"] = binding_ids
        rectification["feedbackAt"] = server_time()
        rectification["feedbackByName"] = "李工"
        changed = [repo.set_node_status(project_id, node_id, "复审中")]
        return ok(
            {
                "rectification": {
                    "id": rectification["id"],
                    "projectId": project_id,
                    "nodeId": node_id,
                    "status": rectification["status"],
                },
                "nextStatus": "复审中",
                "createdTodos": [],
                **repo.mutation_result(
                    "提交补正反馈",
                    "Rectification",
                    rectification["id"],
                    next_status="复审中",
                    changed=changed,
                    affected_ids=[rectification["id"], *binding_ids],
                ),
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/rectifications")
def list_rectifications(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return ok(page([repo.clone(item) for item in repo.state["rectifications"] if item["projectId"] == project_id], page_no, page_size), request)


@router.get("/projects/{project_id}/rectifications/{rectification_id}")
def rectification_detail(request: Request, project_id: str, rectification_id: str):
    item = repo.find_one("rectifications", rectification_id)
    if not item:
        return fail(errors.NOT_FOUND, request)
    return ok({"rectification": repo.clone(item), "bindings": repo.bindings_for_node(project_id, item["nodeId"]), "evidenceLinks": repo.clone(repo.state["evidence_links"])}, request)


@router.get("/projects/{project_id}/workflow")
def project_workflow(request: Request, project_id: str):
    project = repo.require_project(project_id)
    if not project:
        return fail(errors.NOT_FOUND, request)
    return ok({"projectId": project_id, "status": project["status"], "stateMachineVersion": "WF-PIPE-2026"}, request)


@router.get("/projects/{project_id}/workflow/instances/{workflow_id}")
def workflow_instance(request: Request, project_id: str, workflow_id: str):
    return ok({"id": workflow_id, "projectId": project_id, "status": "运行中", "currentNodeId": ROLE_NODE_MAP["inspection"]}, request)


@router.get("/projects/{project_id}/workflow/timeline")
def workflow_timeline(request: Request, project_id: str):
    return ok(
        [
            {"title": "资料提交", "actorName": "李工", "status": "已提交", "createdAt": "2026-06-25 10:45:00"},
            {"title": "AI 预审", "actorName": "系统", "status": "完成", "createdAt": "2026-06-25 15:10:00"},
            {"title": "监检审查", "actorName": "张工", "status": "待人工确认", "createdAt": "2026-06-26 09:12:00"},
        ],
        request,
    )


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/attachments")
def inspection_attachments(
    request: Request,
    project_id: str,
    node_id: int,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return create_upload_session(request, project_id, {"files": body.get("files") or [{"fileName": "监检资料.pdf", "fileSize": 245760, "fileType": "application/pdf"}]}, idempotency_key, x_role)


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/file-bindings")
def inspection_file_bindings(
    request: Request,
    project_id: str,
    node_id: int,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    body = {**body, "nodeId": node_id}
    return bind_documents(request, project_id, body, idempotency_key, x_role)


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/ai-recheck")
def ai_recheck(
    request: Request,
    project_id: str,
    node_id: int,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=[node_id])
        if guard:
            return guard
        run_id = f"AIRUN-{node_id}-{uuid4().hex[:8].upper()}"
        node = repo.node(project_id, node_id)
        project = repo.require_project(project_id)
        pack = business_pack_for_project(project)
        agent = (pack.get("agentSops") or [{}])[0]
        rule = next(
            (item for item in pack.get("ruleSets") or [] if node_id in set(item.get("nodeIds") or [])),
            (pack.get("ruleSets") or [{}])[0],
        )
        run = {
            "id": run_id,
            "projectId": project_id,
            "nodeId": node_id,
            "businessPackId": pack["id"],
            "businessPackVersion": pack["version"],
            "businessPackSnapshotHash": pack["snapshotHash"],
            "agentId": agent.get("id") or "review_agent",
            "agentVersion": agent.get("version") or "1.0.0",
            "subject": node["name"] if node else "节点 AI 复核",
            "model": "review-chat",
            "promptVersion": f"node-{node_id}-v1",
            "ruleVersion": rule.get("version") or "ruleset-v1",
            "inputDocumentVersionIds": [item["documentVersionId"] for item in repo.bindings_for_node(project_id, node_id)],
            "status": "推理中",
            "startedAt": server_time(),
            "steps": [],
            "suggestion": {
                "id": f"AIS-{uuid4().hex[:8].upper()}",
                "result": "需人工确认",
                "opinionDraft": "AI 复核任务已进入队列，完成后将更新审查建议。",
                "risks": [],
                "confidence": 0.0,
                "manualConfirmItems": [],
            },
            "evidenceLinks": [],
            "findingDrafts": [],
        }
        repo.state["ai_runs"].insert(0, run)
        repo.set_node_status(project_id, node_id, "业务核验中")
        dispatch = task_dispatcher.dispatch_ai_recheck(project_id, node_id, run_id)
        if dispatch.get("reviewRunId"):
            run["reviewRunId"] = dispatch.get("reviewRunId")
        if dispatch.get("workflowId"):
            run["workflowId"] = dispatch.get("workflowId")
        return ok({"runId": run_id, "status": run["status"], "latestRun": run, "dispatch": dispatch}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "nodeId": node_id},
    )


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/ai-runs")
def list_ai_runs(request: Request, project_id: str, node_id: int):
    return ok([repo.clone(item) for item in repo.state["ai_runs"] if item["projectId"] == project_id and int(item["nodeId"]) == int(node_id)], request)


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/ai-runs/{run_id}")
def get_ai_run(request: Request, project_id: str, node_id: int, run_id: str):
    run = repo.find_one("ai_runs", run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    return ok(repo.clone(run), request)


@router.get("/review-runs/{review_run_id}")
def get_review_run(request: Request, review_run_id: str):
    refresh_state_from_mongo_for_live_read()
    run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    project_id = run.get("projectId")
    if project_id and not project_visible_for_request(request, str(project_id)):
        return fail(errors.FORBIDDEN, request)
    return ok({"run": review_run_view(run)}, request)


@router.get("/review-runs/{review_run_id}/timeline")
def get_review_run_timeline(request: Request, review_run_id: str):
    refresh_state_from_mongo_for_live_read()
    run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    project_id = run.get("projectId")
    if project_id and not project_visible_for_request(request, str(project_id)):
        return fail(errors.FORBIDDEN, request)
    return ok({"reviewRunId": review_run_id, "events": review_run_timeline(review_run_id)}, request)


@router.get("/review-runs/{review_run_id}/graph")
def get_review_run_graph(request: Request, review_run_id: str):
    refresh_state_from_mongo_for_live_read()
    run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    project_id = run.get("projectId")
    if project_id and not project_visible_for_request(request, str(project_id)):
        return fail(errors.FORBIDDEN, request)
    return ok({"reviewRunId": review_run_id, **graph_view_for_review_run(review_run_id)}, request)


@router.post("/review-runs/{review_run_id}/human-decision")
def submit_review_run_human_decision(
    request: Request,
    review_run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        refresh_state_from_mongo_for_live_read()
        run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
        if not run:
            return fail(errors.NOT_FOUND, request)
        project_id = run.get("projectId")
        if project_id and not project_visible_for_request(request, str(project_id)):
            return fail(errors.FORBIDDEN, request)
        decision = str(body.get("decision") or "accept")
        result = human_decision_for_review_run(review_run_id, decision, body)
        if result.get("status") in {"missing", "invalid_decision"}:
            return fail(errors.VALIDATION_ERROR, request, data=result)
        temporal_signal = signal_review_run_human_decision(
            result["reviewRun"],
            {
                "decision": decision,
                "status": result["status"],
                "comment": body.get("comment") or body.get("reason"),
                "decidedAt": result["reviewRun"].get("humanDecision", {}).get("decidedAt"),
            },
        )
        result["reviewRun"]["temporalSignal"] = temporal_signal
        audit_id = repo.add_audit("提交 ReviewRun 人工确认", "ReviewRun", review_run_id)
        return ok(
            {
                "reviewRun": review_run_view(result["reviewRun"]),
                "feedback": result.get("feedback"),
                "temporalSignal": temporal_signal,
                "auditLogId": audit_id,
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source={"reviewRunId": review_run_id, "body": body})


@router.post("/review-runs/{review_run_id}/cancel")
def cancel_review_run(
    request: Request,
    review_run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        refresh_state_from_mongo_for_live_read()
        run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
        if not run:
            return fail(errors.NOT_FOUND, request)
        run["status"] = "cancelled"
        run["cancelReason"] = body.get("reason") or "用户取消 ReviewRun"
        run["updatedAt"] = server_time()
        temporal_signal = signal_review_run_cancel(run, run["cancelReason"])
        run["temporalSignal"] = temporal_signal
        audit_id = repo.add_audit("取消 ReviewRun", "ReviewRun", review_run_id)
        return ok({"reviewRun": review_run_view(run), "temporalSignal": temporal_signal, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"reviewRunId": review_run_id, "body": body})


@router.post("/review-runs/{review_run_id}/rerun")
def rerun_review_run(
    request: Request,
    review_run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        refresh_state_from_mongo_for_live_read()
        parent = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
        if not parent:
            return fail(errors.NOT_FOUND, request)
        project_id = parent.get("projectId")
        if project_id and not project_visible_for_request(request, str(project_id)):
            return fail(errors.FORBIDDEN, request)
        child = clone_review_run_for_replay(parent, run_mode="diagnostic_replay", reason=body.get("reason") or "业务端请求重跑")
        audit_id = repo.add_audit("业务端请求 ReviewRun 重跑", "ReviewRun", child["reviewRunId"])
        return ok({"reviewRun": review_run_view(child), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"reviewRunId": review_run_id, "body": body})


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/review-opinions")
def save_review_opinion(request: Request, project_id: str, node_id: int, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=[node_id])
        if guard:
            return guard
        opinion = {
            "id": f"OPN-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "nodeId": node_id,
            "result": body.get("result") or "满足要求",
            "opinion": body.get("opinion") or "资料、证据链与规则要求一致，同意通过。",
            "basis": body.get("basis"),
            "riskLevel": body.get("riskLevel", "低"),
            "closeStatus": "未关闭",
            "evidenceLinkIds": body.get("evidenceLinkIds") or [],
            "reviewerName": "张工",
            "createdAt": server_time(),
        }
        repo.state["review_opinions"].insert(0, opinion)
        next_status = "已通过" if opinion["result"] == "满足要求" else "需补正"
        repo.set_node_status(project_id, node_id, next_status)
        return ok({"opinion": opinion, "nextStatus": next_status}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/review-opinions")
def list_review_opinions(request: Request, project_id: str, node_id: int):
    return ok([repo.clone(item) for item in repo.state["review_opinions"] if item["projectId"] == project_id and int(item["nodeId"]) == int(node_id)], request)


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/ai-suggestions/{suggestion_id}/adopt")
def adopt_ai_suggestion(request: Request, project_id: str, node_id: int, suggestion_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=[node_id])
        if guard:
            return guard
        draft = {
            "id": f"OPN-DRAFT-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "nodeId": node_id,
            "result": body.get("result") or "满足要求",
            "opinion": body.get("opinion") or "采纳 AI 建议。",
            "evidenceLinkIds": body.get("evidenceLinkIds") or ["EV-24-001"],
            "reviewerName": "张工",
            "createdAt": server_time(),
        }
        audit_id = repo.add_audit("采纳 AI 建议", "AiSuggestion", suggestion_id)
        return ok({"draftOpinion": draft, "auditLogId": audit_id}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "nodeId": node_id, "suggestionId": suggestion_id, "body": body},
    )


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/ai-suggestions/{suggestion_id}/reject")
def reject_ai_suggestion(request: Request, project_id: str, node_id: int, suggestion_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=[node_id])
        if guard:
            return guard
        return ok(repo.mutation_result("驳回 AI 建议", "AiSuggestion", suggestion_id, changed=[{"field": "reason", "after": body.get("reason")}]), request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "nodeId": node_id, "suggestionId": suggestion_id, "body": body},
    )


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/actions/return-correction")
def return_correction(request: Request, project_id: str, node_id: int, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=[node_id])
        if guard:
            return guard
        rectification = {
            "id": f"REC-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "nodeId": node_id,
            "status": "待反馈",
            "comment": body.get("reason") or body.get("requirement") or "请补充说明。",
            "createdAt": server_time(),
        }
        repo.state["rectifications"].insert(0, rectification)
        changed = [repo.set_node_status(project_id, node_id, "需补正")]
        todo = {
            "id": f"TODO-{uuid4().hex[:8].upper()}",
            "title": f"节点 {node_id} 退回补正",
            "projectId": project_id,
            "nodeId": node_id,
            "targetType": "rectification",
            "targetId": rectification["id"],
            "status": "待处理",
            "priority": "高",
            "assigneeName": "李工",
            "actions": ["rectification:submit"],
        }
        repo.state["todos"].insert(0, todo)
        return ok({"rectification": {"id": rectification["id"], "projectId": project_id, "nodeId": node_id, "status": rectification["status"]}, "nextStatus": "需补正", "createdTodos": [todo], **repo.mutation_result("退回补正", "Rectification", rectification["id"], next_status="需补正", changed=changed)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/evidence-chain")
def evidence_chain(request: Request, project_id: str, node_id: int):
    node = repo.node(project_id, node_id)
    if not node:
        return fail(errors.NOT_FOUND, request)
    links = repo.clone(repo.state["evidence_links"])
    grouped = []
    for object_type in sorted({item["objectType"] for item in links}):
        grouped.append({"objectType": object_type, "links": [item for item in links if item["objectType"] == object_type]})
    return ok({"node": repo.clone(node), "links": links, "groupedByObject": grouped}, request)


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/standards")
def standards(request: Request, project_id: str, node_id: int):
    return ok(
        [
            {
                "clauseId": "TSG-Z6002-3.2",
                "standardName": "TSG Z6002 焊接人员考核细则",
                "clauseNo": "3.2",
                "title": "焊工资格覆盖要求",
                "summary": "焊工持证项目应覆盖实际焊接方法、材料类别和焊接位置。",
                "effectiveVersion": "2010",
                "evidenceLinkId": "EV-24-002",
            }
        ],
        request,
    )


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/date-compare")
def date_compare(request: Request, project_id: str, node_id: int):
    return ok(
        [
            {
                "fieldName": "证书有效期",
                "leftLabel": "证书有效期",
                "leftValue": "2024-03-15 至 2028-03-14",
                "rightLabel": "施工周期",
                "rightValue": "2026-06-01 至 2026-12-31",
                "result": "覆盖",
                "evidenceLinkIds": ["EV-24-001"],
            }
        ],
        request,
    )


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/rules/current-version")
def current_rule_version(request: Request, project_id: str, node_id: int):
    rule = repo.state["rule_versions"][0]
    return ok({"rule": repo.clone(rule)}, request)


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/review-log")
def review_log(request: Request, project_id: str, node_id: int):
    return ok([repo.clone(item) for item in repo.state["review_opinions"] if item["projectId"] == project_id and int(item["nodeId"]) == int(node_id)], request)


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/report-review")
def generate_report_review(request: Request, project_id: str, node_id: int, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=[node_id])
        if guard:
            return guard
        node = repo.node(project_id, node_id)
        if not node:
            return fail(errors.NOT_FOUND, request)
        if node.get("status") in REPORT_GENERATION_BLOCKED_STATUSES:
            return fail(
                errors.CONFLICT,
                request,
                message=f"节点状态 {node.get('status')} 不允许生成报告草稿。",
                data={"nodeId": node_id, "status": node.get("status")},
            )
        report = {
            "id": f"RPT-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "reportNo": f"GDJ-JJ-2026-{len(repo.state['reports']) + 1:03d}",
            "versionNo": "V1",
            "title": f"{repo.require_project(project_id)['name']}监督检验报告",
            "status": "复核中",
            "scope": body.get("reportScope") or "currentNode",
            "nodeIds": [node_id],
            "templateVersion": "TPL-PIPE-2026.06",
            "generatedAt": server_time(),
            "generatedByName": "张工",
            "reviewerName": "张工",
            "dataSnapshotId": f"SNAP-RPT-{uuid4().hex[:8].upper()}",
            "previewUrl": "mock://preview/reports/new",
            "actions": ["report:view", "report:export", "report:archive"],
        }
        repo.state["reports"].insert(0, report)
        repo.touch_project(project_id, "报告生成/复核中", node_id)
        todo = {"id": f"TODO-{uuid4().hex[:8].upper()}", "title": "报告复核", "projectId": project_id, "targetType": "report", "targetId": report["id"], "status": "待处理", "priority": "中", "assigneeName": "张工", "actions": ["report:review"]}
        repo.state["todos"].insert(0, todo)
        return ok({"report": report, "nextStatus": "报告生成/复核中", "createdTodos": [todo]}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/owner/reports")
def owner_reports(request: Request, project_id: str):
    scope = authorized_node_scope(request, project_id)
    return ok(
        [
            versioned_report(item)
            for item in repo.state["reports"]
            if item["projectId"] == project_id and report_visible_in_scope(item, scope)
        ],
        request,
    )


@router.get("/projects/{project_id}/reports")
def list_reports(request: Request, project_id: str):
    scope = authorized_node_scope(request, project_id)
    return ok(
        [
            versioned_report(item)
            for item in repo.state["reports"]
            if item["projectId"] == project_id and report_visible_in_scope(item, scope)
        ],
        request,
    )


@router.get("/projects/{project_id}/reports/{report_id}")
def report_detail(request: Request, project_id: str, report_id: str):
    report = repo.find_one("reports", report_id)
    if not report or report.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    return ok(
        {
            "report": versioned_report(report),
            "sections": [
                {"key": "summary", "title": "检验结论", "content": "资料、证据链与规则要求一致，建议复核后签发。", "evidenceLinkIds": ["EV-24-001"]},
                {"key": "node-24", "title": "焊工资格证及持证合格项目", "content": "证书有效期覆盖施工周期，持证项目覆盖焊接方法。", "evidenceLinkIds": ["EV-24-001", "EV-24-002"]},
            ],
            "evidenceLinks": repo.clone(repo.state["evidence_links"]),
            "reviewTrail": [{"title": "生成报告草稿", "actorName": report.get("generatedByName", "张工"), "result": report["status"], "createdAt": report["generatedAt"]}],
            "versionHistory": [{"id": report["id"], "versionNo": report.get("versionNo", "V1"), "status": report["status"], "generatedAt": report["generatedAt"], "summary": "当前版本"}],
        },
        request,
    )


@router.patch("/projects/{project_id}/reports/{report_id}")
def update_report(
    request: Request,
    project_id: str,
    report_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=report_node_ids(project_id, report_id))
        if guard:
            return guard
        report = repo.find_one("reports", report_id)
        if not report or report.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        if not report_if_match_valid(report, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        changed = []
        for field in ["title", "status"]:
            if field in body:
                changed.append({"field": field, "before": report.get(field), "after": body[field]})
                report[field] = body[field]
        if changed:
            report["revision"] = int(report.get("revision") or 1) + 1
            report["updatedAt"] = server_time()
        return ok({"report": versioned_report(report), **repo.mutation_result("保存报告", "Report", report_id, changed=changed)}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "reportId": report_id, "body": body},
    )


@router.get("/projects/{project_id}/reports/{report_id}/versions")
def report_versions(request: Request, project_id: str, report_id: str):
    report = repo.find_one("reports", report_id)
    if not report or report.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    return ok([{"id": report_id, "versionNo": report.get("versionNo", "V1"), "status": report["status"], "generatedAt": report["generatedAt"], "summary": "当前版本"}], request)


@router.post("/projects/{project_id}/reports/{report_id}/export")
def export_report(request: Request, project_id: str, report_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=report_node_ids(project_id, report_id))
        if guard:
            return guard
        report = repo.find_one("reports", report_id)
        if not report or report.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        export_id = f"EXP-RPT-{uuid4().hex[:8].upper()}"
        task = {
            "id": export_id,
            "projectId": project_id,
            "reportId": report_id,
            "nodeIds": report.get("nodeIds") or [],
            "exportType": "report",
            "status": "可下载",
            "progress": 100,
            "fileName": f"{report['title']}.{body.get('format') or 'pdf'}",
            "fileSize": 2097152,
            "downloadUrl": f"mock://download/reports/{report_id}.{body.get('format') or 'pdf'}",
            "createdAt": server_time(),
            "finishedAt": server_time(),
            "expiresAt": "2026-06-27 18:00:00",
        }
        repo.attach_export_artifact(task, content_type="application/pdf" if (body.get("format") or "pdf") == "pdf" else None)
        repo.state["export_tasks"].insert(0, task)
        next_status = "已签发" if report.get("status") == "待签发" else "复核中"
        if report.get("status") != next_status:
            report["status"] = next_status
            report["revision"] = int(report.get("revision") or 1) + 1
            report["updatedAt"] = server_time()
        return ok({"exportId": export_id, "report": versioned_report(report)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/projects/{project_id}/reports/{report_id}/archive")
def archive_report(
    request: Request,
    project_id: str,
    report_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=report_node_ids(project_id, report_id))
        if guard:
            return guard
        report = repo.find_one("reports", report_id)
        if not report or report.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        if not report_if_match_valid(report, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        report["status"] = "已归档"
        report["revision"] = int(report.get("revision") or 1) + 1
        report["updatedAt"] = server_time()
        repo.touch_project(project_id, "已归档")
        item = {
            "id": f"ARCH-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "name": f"{report['title']}.pdf",
            "type": "report",
            "nodeId": report.get("nodeIds", [None])[0],
            "sourceOrgName": "省特检院一部",
            "status": "已归档",
            "updatedAt": server_time(),
            "downloadUrl": report.get("exportUrl") or f"mock://download/reports/{report_id}.pdf",
        }
        repo.state["archive_items"].insert(0, item)
        return ok({"report": versioned_report(report), "nextStatus": "已归档"}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/archive")
def list_archive(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), keyword: str | None = None, nodeId: int | None = None):
    scope = authorized_node_scope(request, project_id)
    items = [
        repo.clone(item)
        for item in repo.state["archive_items"]
        if item.get("projectId") == project_id and archive_visible_in_scope(item, scope)
    ]
    if nodeId:
        items = [item for item in items if int(item.get("nodeId") or 0) == int(nodeId)]
    items = filter_keyword(items, keyword, ["name", "sourceOrgName", "status"])
    return ok(page(items, page_no, page_size), request)


@router.get("/projects/{project_id}/archive/package")
def archive_package(request: Request, project_id: str):
    scope = authorized_node_scope(request, project_id)
    export_id = "EXP-ARCHIVE-QUEUE-001"
    existing_task = repo.find_one("export_tasks", export_id)
    task = existing_task or {
        "id": export_id,
        "projectId": project_id,
        "exportType": "archive-package",
        "status": "排队中",
        "progress": 0,
        "fileName": f"{project_id}-归档资料包.zip",
        "fileSize": 4194304,
        "downloadUrl": f"mock://download/archive/{project_id}.zip",
        "createdAt": server_time(),
    }
    if not existing_task:
        repo.state["export_tasks"].insert(0, task)
    task["status"] = "可下载"
    task["progress"] = 100
    task["finishedAt"] = server_time()
    task["updatedAt"] = task["finishedAt"]
    repo.attach_export_artifact(task, content_type="application/zip")
    item_count = len([item for item in repo.state["archive_items"] if item.get("projectId") == project_id and archive_visible_in_scope(item, scope)])
    download_url = task.get("downloadUrl") or f"mock://download/archive/{project_id}.zip"
    return ok({**repo.signed_get(task["fileName"], download_url, "application/zip", task.get("fileSize")), "exportId": export_id, "projectId": project_id, "packageType": "archive", "itemCount": item_count, "generatedAt": server_time()}, request)


@router.get("/projects/{project_id}/archive/evidence-package")
def evidence_package(request: Request, project_id: str, nodeId: int | None = None):
    scope = authorized_node_scope(request, project_id)
    effective_node_id = nodeId or 24
    if scope is not None and effective_node_id not in scope:
        return fail(errors.FORBIDDEN, request, message="用户不在该节点授权范围内。")
    export_id = "EXP-EVIDENCE-RUNNING-001"
    file_name = f"{project_id}-节点{effective_node_id}-证据定位包.zip"
    task = repo.find_one("export_tasks", export_id) or {"id": export_id, "projectId": project_id, "exportType": "evidence-package", "status": "排队中", "progress": 0, "fileName": file_name, "fileSize": 786432, "downloadUrl": f"mock://download/archive/{project_id}-evidence.zip", "createdAt": server_time()}
    if not repo.find_one("export_tasks", export_id):
        repo.state["export_tasks"].insert(0, task)
    task["status"] = "可下载"
    task["progress"] = 100
    task["finishedAt"] = server_time()
    task["updatedAt"] = task["finishedAt"]
    repo.attach_export_artifact(task, content_type="application/zip")
    return ok({**repo.signed_get(file_name, task["downloadUrl"], "application/zip", task.get("fileSize")), "exportId": export_id, "projectId": project_id, "packageType": "evidence", "itemCount": len(repo.state["evidence_links"]), "generatedAt": server_time()}, request)


@router.get("/projects/{project_id}/archive/{archive_item_id}")
def archive_item_detail(request: Request, project_id: str, archive_item_id: str):
    item = repo.find_one("archive_items", archive_item_id)
    if not item or item.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    scope = authorized_node_scope(request, project_id)
    if not archive_visible_in_scope(item, scope):
        return fail(errors.FORBIDDEN, request, message="用户不在该资源授权范围内。")
    report = repo.state["reports"][0] if item["type"] == "report" else None
    return ok(
        {
            "item": repo.clone(item),
            "preview": {**repo.signed_get(item["name"], item.get("downloadUrl") or f"mock://preview/archive/{item['id']}", "application/pdf"), "previewType": "pdf", "readonly": True, "pageCount": 4},
            "download": repo.signed_get(item["name"], item.get("downloadUrl") or f"mock://download/archive/{item['id']}"),
            "report": repo.clone(report) if report else None,
            "document": None,
            "evidenceLinks": repo.clone(repo.state["evidence_links"]),
            "relatedExportTasks": [repo.clone(task) for task in repo.state["export_tasks"] if task.get("projectId") == project_id],
        },
        request,
    )


@router.get("/projects/{project_id}/export-tasks/{export_id}")
def project_export_task(request: Request, project_id: str, export_id: str):
    task = repo.find_one("export_tasks", export_id)
    if not task or task.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, task, project_id)
    if scope_error:
        return scope_error
    return ok({"task": repo.clone(task)}, request)


@router.get("/exports/{export_id}")
def get_export_task(request: Request, export_id: str):
    task = repo.find_one("export_tasks", export_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, task)
    if scope_error:
        return scope_error
    return ok({"task": repo.clone(task)}, request)


@router.get("/exports/{export_id}/download-url")
def export_download_url(request: Request, export_id: str):
    task = repo.find_one("export_tasks", export_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, task)
    if scope_error:
        return scope_error
    signed = signed_url_for_task(task)
    if isinstance(signed, dict) and "error" in signed:
        return fail(signed["error"], request)
    return ok(signed, request)


@router.get("/downloads/{file_id}/signed-url")
def file_signed_url(request: Request, file_id: str):
    return ok(repo.signed_get(f"{file_id}.bin", f"mock://download/{file_id}"), request)


@router.post("/exports")
def create_export(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        project_id = body.get("projectId")
        node_ids = node_ids_from_body(body)
        if project_id and body.get("reportId"):
            node_ids = sorted({*node_ids, *report_node_ids(project_id, str(body["reportId"]))})
        if project_id:
            role, identity_error = effective_role_for_request(request)
            if identity_error:
                return identity_error
            scope_error = member_node_scope_error(request, project_id, role, node_ids=node_ids)
            if scope_error:
                return scope_error
        export_id = f"EXP-{uuid4().hex[:8].upper()}"
        task = {
            "id": export_id,
            "projectId": body.get("projectId"),
            "nodeIds": node_ids,
            "reportId": body.get("reportId"),
            "exportType": body.get("exportType") or "config-package",
            "status": "排队中",
            "progress": 0,
            "fileName": body.get("fileName") or f"{export_id}.zip",
            "fileSize": 0,
            "createdAt": server_time(),
            "expiresAt": "2026-06-27 18:00:00",
        }
        repo.state["export_tasks"].insert(0, task)
        dispatch = task_dispatcher.dispatch_export(export_id)
        return ok({"exportId": export_id, "status": task["status"], "task": task, "dispatch": dispatch}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/ndt/summary")
def ndt_summary(request: Request, project_id: str):
    scope = authorized_node_scope(request, project_id)
    films = [item for item in repo.state["ndt_films"] if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)]
    records = [item for item in repo.state["ndt_records"] if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)]
    reports = [item for item in repo.state["ndt_reports"] if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)]
    feedback = [item for item in repo.state["ndt_feedback"] if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)]
    return ok({"filmCount": len(films), "recordCount": len(records), "reportCount": len(reports), "feedbackCount": len(feedback)}, request)


@router.get("/projects/{project_id}/ndt/films")
def list_ndt_films(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), status: str | None = None, method: str | None = None, keyword: str | None = None):
    scope = authorized_node_scope(request, project_id)
    items = [
        repo.clone(item)
        for item in repo.state["ndt_films"]
        if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    if status:
        items = [item for item in items if item["status"] == status]
    if method:
        items = [item for item in items if item["method"] == method]
    items = filter_keyword(items, keyword, ["filmNo", "weldNo", "pipelineNo"])
    return ok(page(items, page_no, page_size), request)


@router.post("/projects/{project_id}/ndt/films")
def create_ndt_film(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    node_ids = node_ids_from_body(body, 40)

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        missing = missing_required_fields(body, ["filmNo", "weldNo", "method"])
        if missing:
            return fail(errors.NDT_FILM_REQUIRED, request, data={"fields": missing})
        node_id = node_ids[0] if node_ids else 40
        film = {
            "id": f"FILM-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "nodeId": node_id,
            "filmNo": body.get("filmNo"),
            "weldNo": body.get("weldNo"),
            "pipelineNo": body.get("pipelineNo"),
            "method": body.get("method"),
            "testDate": body.get("testDate"),
            "status": "待提交",
            "actions": ["ndt:submit"],
        }
        repo.state["ndt_films"].insert(0, film)
        return ok({"film": film}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/ndt/films/{film_id}")
def ndt_film_detail(request: Request, project_id: str, film_id: str):
    film = repo.find_one("ndt_films", film_id)
    if not film or film.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, film, project_id)
    if scope_error:
        return scope_error
    return ok({"film": repo.clone(film)}, request)


@router.patch("/projects/{project_id}/ndt/films/{film_id}")
def update_ndt_film(request: Request, project_id: str, film_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        film = repo.find_one("ndt_films", film_id)
        if not film or film.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=sorted(record_node_ids(project_id, film)))
        if guard:
            return guard
        film.update({key: value for key, value in body.items() if value is not None})
        return ok({"film": repo.clone(film), **repo.mutation_result("更新底片", "NdtFilm", film_id)}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "filmId": film_id, "body": body},
    )


@router.post("/projects/{project_id}/ndt/films/import")
def import_ndt_films(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        rows = body.get("rows") or []
        node_ids = sorted({*node_ids_from_body(body, 40), *[int(row["nodeId"]) for row in rows if row.get("nodeId") is not None]})
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        if not rows:
            return fail(errors.NDT_FILM_REQUIRED, request, message="导入底片行不能为空。")
        failed = [
            {"row": index + 1, "fields": missing_required_fields(row, ["filmNo", "weldNo", "method"])}
            for index, row in enumerate(rows)
            if missing_required_fields(row, ["filmNo", "weldNo", "method"])
        ]
        if failed:
            return fail(errors.NDT_FILM_REQUIRED, request, data={"failed": failed})
        created = []
        node_id = node_ids[0] if node_ids else 40
        for row in rows:
            film = {"id": f"FILM-{uuid4().hex[:8].upper()}", "projectId": project_id, "nodeId": int(row.get("nodeId") or node_id), "filmNo": row.get("filmNo"), "weldNo": row.get("weldNo"), "method": row.get("method"), "status": "待提交", "actions": ["ndt:submit"]}
            repo.state["ndt_films"].insert(0, film)
            created.append(film)
        return ok({"imported": len(created), "failed": [], "films": created}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "body": body},
    )


@router.get("/projects/{project_id}/ndt/records")
def list_ndt_records(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), filmId: str | None = None, reportId: str | None = None, sampleStatus: str | None = None):
    scope = authorized_node_scope(request, project_id)
    items = [
        repo.clone(item)
        for item in repo.state["ndt_records"]
        if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    if filmId:
        items = [item for item in items if item.get("filmId") == filmId]
    if reportId:
        items = [item for item in items if item.get("reportId") == reportId]
    if sampleStatus:
        items = [item for item in items if item.get("sampleStatus") == sampleStatus]
    return ok(page(items, page_no, page_size), request)


@router.post("/projects/{project_id}/ndt/records/import")
def import_ndt_records(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    node_ids = node_ids_from_body(body, 40)

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        rows = body.get("rows") or []
        if not rows:
            return fail(errors.NDT_RECORD_REQUIRED, request, message="导入检测记录行不能为空。")
        failed = [
            {"row": index + 1, "fields": missing_required_fields(row, ["recordNo", "weldNo", "method"])}
            for index, row in enumerate(rows)
            if missing_required_fields(row, ["recordNo", "weldNo", "method"])
        ]
        if failed:
            return fail(errors.NDT_RECORD_REQUIRED, request, data={"failed": failed})
        created = []
        for row in rows:
            record = {
                "id": f"NDT-REC-{uuid4().hex[:8].upper()}",
                "projectId": project_id,
                "nodeId": node_ids[0] if node_ids else 40,
                "recordNo": row.get("recordNo"),
                "filmId": row.get("filmId"),
                "reportId": row.get("reportId"),
                "weldNo": row.get("weldNo"),
                "pipelineNo": row.get("pipelineNo"),
                "method": row.get("method"),
                "testDate": row.get("testDate") or "2026-06-26",
                "evaluatorName": row.get("evaluatorName") or "王工",
                "result": row.get("result") or "待复核",
                "sampleStatus": row.get("sampleStatus") or "未抽查",
                "conclusion": row.get("conclusion"),
                "importedAt": server_time(),
                "actions": ["ndt:record-import"],
            }
            repo.state["ndt_records"].insert(0, record)
            created.append(record)
        return ok({"imported": len(created), "failed": [], "records": created}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "body": body},
    )


@router.get("/projects/{project_id}/ndt/reports")
def list_ndt_reports(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), status: str | None = None, method: str | None = None):
    scope = authorized_node_scope(request, project_id)
    items = [
        repo.clone(item)
        for item in repo.state["ndt_reports"]
        if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    if status:
        items = [item for item in items if item["status"] == status]
    if method:
        items = [item for item in items if item["method"] == method]
    return ok(page(items, page_no, page_size), request)


@router.post("/projects/{project_id}/ndt/reports/upload-session")
def ndt_report_upload_session(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    node_ids = node_ids_from_body(body, 40)

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        node_id = node_ids[0] if node_ids else 40
        files = body.get("files") or []
        validation_error = validate_upload_files(request, files, ndt=True)
        if validation_error:
            return validation_error
        session_id = f"UPS-NDT-{uuid4().hex[:8].upper()}"
        upload_urls = []
        for file in files:
            doc, version = repo.create_document(project_id, file.get("fileName", "RT检测报告.pdf"), file.get("fileType", "pdf"), source_org_name="华测检测有限公司", uploader_name="王工")
            doc["nodeId"] = node_id
            knowledge_file = repo.find_one("knowledge_files", f"KF-{doc['id']}")
            if knowledge_file:
                knowledge_file["nodeId"] = node_id
            report = {
                "id": f"NDT-RPT-{uuid4().hex[:8].upper()}",
                "projectId": project_id,
                "nodeId": node_id,
                "reportNo": file.get("fileName", "RT检测报告").split(".")[0],
                "method": "UT" if "UT" in file.get("fileName", "") else "RT",
                "fileId": doc["id"],
                "relatedFilmIds": body.get("relatedFilmIds") or [],
                "status": "待提交",
                "uploadedAt": server_time(),
                "actions": ["ndt:submit"],
            }
            repo.state["ndt_reports"].insert(0, report)
            content_type = file.get("fileType") or "application/pdf"
            upload_urls.append({"fileName": doc["fileName"], "documentId": doc["id"], "documentVersionId": version["id"], "url": repo.signed_put("documents", version["storageKey"], f"mock://upload/ndt/{session_id}/{doc['id']}", content_type=content_type), "method": "PUT", "expiresAt": "2026-06-27 18:00:00", "headers": {"Content-Type": content_type}})
        return ok({"uploadSessionId": session_id, "expiresAt": "2026-06-27 18:00:00", "uploadUrls": upload_urls}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/ndt/reports/{report_id}")
def ndt_report_detail(request: Request, project_id: str, report_id: str):
    report = repo.find_one("ndt_reports", report_id)
    if not report or report.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, report, project_id)
    if scope_error:
        return scope_error
    scope = authorized_node_scope(request, project_id)
    films = [repo.clone(item) for item in repo.state["ndt_films"] if item["id"] in set(report.get("relatedFilmIds", [])) and record_visible_for_scope(item, scope, project_id=project_id)]
    records = [repo.clone(item) for item in repo.state["ndt_records"] if item.get("reportId") == report_id and record_visible_for_scope(item, scope, project_id=project_id)]
    document = repo.find_one("documents", report.get("fileId"))
    feedback = [repo.clone(item) for item in repo.state["ndt_feedback"] if record_visible_for_scope(item, scope, project_id=project_id)]
    return ok({"report": repo.clone(report), "films": films, "records": records, "document": repo.clone(document) if document else None, "feedback": feedback}, request)


@router.post("/projects/{project_id}/ndt/submissions")
def submit_ndt(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    node_ids = ndt_submission_node_ids(project_id, body)

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        node_id = node_ids[0] if node_ids else 40
        submission_id = f"NDT-SUB-{uuid4().hex[:8].upper()}"
        snapshot_id = f"SNAP-{submission_id}"
        submitted_at = server_time()
        submitted_report_ids = set(body.get("reportIds") or [])
        submitted_film_ids = set(body.get("filmIds") or [])
        if not submitted_report_ids:
            return fail(errors.NDT_REPORT_REQUIRED, request)
        submitable_reports = [
            report
            for report in repo.state["ndt_reports"]
            if report.get("projectId") == project_id
            and report.get("id") in submitted_report_ids
            and report.get("status") in {"草稿", "待提交", "需补正"}
            and record_visible_for_request(request, report, project_id)
        ]
        if len(submitable_reports) != len(submitted_report_ids):
            return fail(errors.NDT_REPORT_REQUIRED, request, message="未找到可提交的无损检测报告。")
        submitable_films = [
            film
            for film in repo.state["ndt_films"]
            if film.get("projectId") == project_id
            and film.get("id") in submitted_film_ids
            and record_visible_for_request(request, film, project_id)
        ]
        if submitted_film_ids and len(submitable_films) != len(submitted_film_ids):
            return fail(errors.NDT_FILM_REQUIRED, request, message="未找到可提交的无损检测底片。")
        for report in submitable_reports:
            report["status"] = "待审查"
            report["submittedAt"] = submitted_at
        for film in submitable_films:
            film["status"] = "待审查"
            film["submittedAt"] = submitted_at
        changed = [repo.set_node_status(project_id, node_id, "待审查")]
        todo = {
            "id": f"TODO-{uuid4().hex[:8].upper()}",
            "title": "无损检测资料待审查",
            "projectId": project_id,
            "nodeId": node_id,
            "targetType": "submission",
            "targetId": submission_id,
            "status": "待处理",
            "priority": "中",
            "assigneeName": "张工",
            "actions": ["review:save"],
        }
        repo.state["todos"].insert(0, todo)
        related_records = [
            repo.clone(record)
            for record in repo.state["ndt_records"]
            if record.get("projectId") == project_id
            and (record.get("reportId") in submitted_report_ids or record.get("filmId") in submitted_film_ids)
            and record_visible_for_request(request, record, project_id)
        ]
        submission = {
            "submissionId": submission_id,
            "snapshotId": snapshot_id,
            "projectId": project_id,
            "nodeId": node_id,
            "nodeIds": node_ids,
            "submissionType": "ndt",
            "batchName": body.get("batchName") or "无损检测资料提交",
            "submitterComment": body.get("comment") or body.get("submitterComment"),
            "nextStatus": "待审查",
            "submittedAt": submitted_at,
            "createdTodoIds": [todo["id"]],
            "reportIds": sorted(submitted_report_ids),
            "filmIds": sorted(submitted_film_ids),
            "changed": changed,
            "snapshot": {
                "reports": [repo.clone(report) for report in submitable_reports],
                "films": [repo.clone(film) for film in submitable_films],
                "records": related_records,
            },
        }
        repo.state["submissions"].insert(0, submission)
        return ok(
            {
                "submissionId": submission_id,
                "snapshotId": snapshot_id,
                "nextStatus": "待审查",
                "createdTodos": [todo],
                "submittedReportIds": sorted(submitted_report_ids),
                "submittedFilmIds": sorted(submitted_film_ids),
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/projects/{project_id}/ndt/rectifications")
def ndt_rectification(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    node_ids = node_ids_from_body(body, 40)

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        node_id = node_ids[0] if node_ids else 40
        rectification_id = body.get("rectificationId") or f"NDT-REC-{uuid4().hex[:8].upper()}"
        if not body.get("description") or (not body.get("rectificationId") and not body.get("reportIds") and not body.get("filmIds")):
            return fail(errors.NDT_RECTIFICATION_REQUIRED, request)
        feedback = repo.find_one("ndt_feedback", rectification_id)
        if feedback:
            scope_error = scope_error_for_record(request, feedback, project_id)
            if scope_error:
                return scope_error
            feedback["status"] = "已反馈"
            feedback["feedbackDescription"] = body.get("description")
            feedback["feedbackAt"] = server_time()
        else:
            feedback = {
                "id": rectification_id,
                "projectId": project_id,
                "nodeId": node_id,
                "title": "无损检测补正反馈",
                "description": body.get("description") or "已补充无损检测资料。",
                "status": "已反馈",
                "relatedReportIds": body.get("reportIds") or [],
                "relatedFilmIds": body.get("filmIds") or [],
                "createdAt": server_time(),
            }
            repo.state["ndt_feedback"].insert(0, feedback)
        rectification = {"id": feedback["id"], "projectId": project_id, "nodeId": node_id, "status": feedback["status"]}
        repo.set_node_status(project_id, node_id, "复审中")
        return ok({"rectification": rectification, "nextStatus": "复审中"}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/ndt/inspection-feedback")
def list_ndt_feedback(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), status: str | None = None):
    scope = authorized_node_scope(request, project_id)
    items = [
        repo.clone(item)
        for item in repo.state["ndt_feedback"]
        if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    if status:
        items = [item for item in items if item["status"] == status]
    return ok(page(items, page_no, page_size), request)


@router.get("/projects/{project_id}/ndt/inspection-feedback/{feedback_id}")
def ndt_feedback_detail(request: Request, project_id: str, feedback_id: str):
    feedback = repo.find_one("ndt_feedback", feedback_id)
    if not feedback or feedback.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, feedback, project_id)
    if scope_error:
        return scope_error
    scope = authorized_node_scope(request, project_id)
    return ok(
        {
            "feedback": repo.clone(feedback),
            "reports": [repo.clone(item) for item in repo.state["ndt_reports"] if item["id"] in set(feedback.get("relatedReportIds", [])) and record_visible_for_scope(item, scope, project_id=project_id)],
            "films": [repo.clone(item) for item in repo.state["ndt_films"] if item["id"] in set(feedback.get("relatedFilmIds", [])) and record_visible_for_scope(item, scope, project_id=project_id)],
            "records": [repo.clone(item) for item in repo.state["ndt_records"] if record_visible_for_scope(item, scope, project_id=project_id)],
            "evidenceLinks": repo.clone(repo.state["evidence_links"]),
            "timeline": [{"title": "监检反馈", "actorName": "张工", "status": feedback["status"], "createdAt": feedback["createdAt"], "comment": feedback["description"]}],
        },
        request,
    )


@router.get("/search")
def search(request: Request, keyword: str = Query(default=""), projectId: str | None = None, type: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    results: list[dict[str, Any]] = []
    lowered = keyword.lower()
    for project in repo.state["projects"]:
        scope = authorized_node_scope(request, project["id"])
        if (not projectId or project["id"] == projectId) and (scope is None or bool(scope)):
            results.append({"type": "project", "id": project["id"], "title": project["name"], "description": project["status"], "route": f"/workbench/inspection?projectId={project['id']}", "highlights": [project["code"], project["region"]]})
    for node in repo.state["tree_nodes"]:
        scope = authorized_node_scope(request, node["projectId"])
        if (not projectId or node["projectId"] == projectId) and record_visible_for_scope(node, scope, project_id=node["projectId"]):
            results.append({"type": "node", "id": str(node["nodeId"]), "title": f"节点 {node['nodeId']} {node['name']}", "description": node["status"], "route": f"/workbench/inspection?nodeId={node['nodeId']}", "highlights": [node["groupName"], node["inspectionType"]]})
    for doc in repo.state["documents"]:
        scope = authorized_node_scope(request, doc["projectId"])
        if (not projectId or doc["projectId"] == projectId) and document_visible_in_scope(doc, scope):
            results.append({"type": "document", "id": doc["id"], "title": doc["fileName"], "description": doc["sourceOrgName"], "route": f"/workbench/contractor?documentId={doc['id']}", "highlights": [doc["currentOcrStatus"]]})
    for report in repo.state["reports"]:
        scope = authorized_node_scope(request, report["projectId"])
        if (not projectId or report["projectId"] == projectId) and report_visible_in_scope(report, scope):
            results.append({"type": "report", "id": report["id"], "title": report["title"], "description": report["status"], "route": f"/workbench/owner?reportId={report['id']}", "highlights": [report["reportNo"]]})
    if type:
        results = [item for item in results if item["type"] == type]
    if keyword:
        results = [item for item in results if lowered in f"{item['title']} {item['description']} {' '.join(item['highlights'])}".lower()]
    return ok(page(results, page_no, page_size), request)


@router.get("/todos")
def list_todos(request: Request, role: str | None = None, projectId: str | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [versioned_record("todo", item) for item in repo.state["todos"] if record_visible_for_request(request, item)]
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if status:
        items = [item for item in items if item.get("status") == status]
    return ok(page(items, page_no, page_size), request)


@router.get("/todos/{todo_id}")
def todo_detail(request: Request, todo_id: str):
    todo = repo.find_one("todos", todo_id)
    if not todo:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, todo)
    if scope_error:
        return scope_error
    return ok({**versioned_record("todo", todo), "relatedObject": None, "evidenceLinks": repo.clone(repo.state["evidence_links"])}, request)


@router.post("/todos/{todo_id}/complete")
def complete_todo(
    request: Request,
    todo_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        todo = repo.find_one("todos", todo_id)
        if not todo:
            return fail(errors.NOT_FOUND, request)
        scope_error = scope_error_for_record(request, todo)
        if scope_error:
            return scope_error
        if not record_if_match_valid("todo", todo, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        if todo.get("status") != "已完成":
            todo["status"] = "已完成"
            todo["completedAt"] = server_time()
            todo["completedComment"] = body.get("comment") or body.get("result")
            bump_record_revision(todo)
        result = repo.mutation_result("完成待办", "Todo", todo_id, next_status="已完成")
        return ok({**result, "todo": versioned_record("todo", todo)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"todoId": todo_id, "body": body})


@router.post("/todos/{todo_id}/defer")
def defer_todo(
    request: Request,
    todo_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        todo = repo.find_one("todos", todo_id)
        if not todo:
            return fail(errors.NOT_FOUND, request)
        scope_error = scope_error_for_record(request, todo)
        if scope_error:
            return scope_error
        if not record_if_match_valid("todo", todo, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        if todo.get("status") != "已延期":
            todo["status"] = "已延期"
            todo["deferredUntil"] = body.get("deferredUntil")
            bump_record_revision(todo)
        result = repo.mutation_result("延期待办", "Todo", todo_id, next_status="已延期")
        return ok({**result, "todo": versioned_record("todo", todo)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"todoId": todo_id, "body": body})


@router.get("/messages")
def list_messages(request: Request, projectId: str | None = None, read: bool | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [versioned_record("message", item) for item in repo.state["messages"] if record_visible_for_request(request, item)]
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if read is not None:
        items = [item for item in items if item.get("read") is read]
    return ok(page(items, page_no, page_size), request)


@router.post("/messages/{message_id}/read")
def mark_message_read(
    request: Request,
    message_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        message = repo.find_one("messages", message_id)
        if not message:
            return fail(errors.NOT_FOUND, request)
        scope_error = scope_error_for_record(request, message)
        if scope_error:
            return scope_error
        if not record_if_match_valid("message", message, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        if not message.get("read"):
            message["read"] = True
            message["readAt"] = server_time()
            bump_record_revision(message)
        result = repo.mutation_result("标记消息已读", "Message", message_id)
        return ok({**result, "message": versioned_record("message", message)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"messageId": message_id})


@router.post("/messages/read-all")
def mark_all_messages_read(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        if if_match and if_match != "*":
            return fail(errors.ETAG_CONFLICT, request, message="批量消息操作仅支持 If-Match: *。")
        affected = 0
        updated_messages = []
        for message in repo.state["messages"]:
            if body.get("projectId") and message.get("projectId") != body.get("projectId"):
                continue
            if not record_visible_for_request(request, message):
                continue
            if not message.get("read"):
                message["read"] = True
                message["readAt"] = server_time()
                bump_record_revision(message)
                affected += 1
            updated_messages.append(versioned_record("message", message))
        audit_id = repo.add_audit("全部消息已读", "Message", body.get("projectId") or "all")
        return ok({"affectedCount": affected, "messages": updated_messages, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/workflow/commands")
def execute_workflow_command(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    def produce():
        project_id = body.get("projectId")
        if not project_id:
            return fail(errors.VALIDATION_ERROR, request, message="projectId 不能为空。")
        node_id = body.get("nodeId")
        guard = mutation_guard(
            request,
            project_id,
            x_role=x_role,
            node_ids=[int(node_id)] if node_id is not None else None,
        )
        if guard:
            return guard
        project = repo.require_project(project_id)
        if not project:
            return fail(errors.NOT_FOUND, request)
        pack = business_pack_for_project(project)
        action = body.get("action") or body.get("command")
        transitions = [
            transition
            for workflow in pack.get("workflowStateMachines") or []
            for transition in workflow.get("transitions") or []
            if transition.get("action") == action
        ]
        next_status = body.get("nextStatus") or (transitions[0].get("to") if transitions else "submitted")
        changed = []
        if node_id is not None:
            node = repo.node(project_id, int(node_id))
            if not node:
                return fail(errors.NOT_FOUND, request, message="节点不存在。")
            changed.append(repo.set_node_status(project_id, int(node_id), next_status))
        repo.touch_project(project_id)
        audit_id = repo.add_audit("执行工作流命令", "WorkflowCommand", body.get("commandId") or action or "command")
        return ok(
            {
                "commandId": body.get("commandId") or f"CMD-{uuid4().hex[:8].upper()}",
                "projectId": project_id,
                "nodeId": node_id,
                "action": action,
                "nextStatus": next_status,
                "changed": changed,
                "auditLogId": audit_id,
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/review-workbench")
def generic_review_workbench(request: Request, project_id: str, nodeId: int | None = None):
    project = repo.require_project(project_id)
    if not project:
        return fail(errors.NOT_FOUND, request)
    scope = authorized_node_scope(request, project_id)
    nodes = [
        item
        for item in repo.state["tree_nodes"]
        if item.get("projectId") == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    if nodeId is not None:
        nodes = [item for item in nodes if int(item["nodeId"]) == int(nodeId)]
    findings = [
        repo.clone(item)
        for item in repo.state["review_findings"]
        if item.get("projectId") == project_id and (nodeId is None or int(item.get("nodeId") or 0) == int(nodeId))
    ]
    return ok(
        {
            "project": versioned_project(project),
            "businessPack": business_pack_summary(business_pack_for_project(project)),
            "nodes": repo.clone(nodes),
            "findings": findings,
            "aiRuns": [
                repo.clone(item)
                for item in repo.state["ai_runs"]
                if item.get("projectId") == project_id and (nodeId is None or int(item.get("nodeId") or 0) == int(nodeId))
            ],
        },
        request,
    )


@router.post("/review/findings")
def create_review_finding(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    def produce():
        project_id = body.get("projectId")
        node_id = int(body.get("nodeId") or 0)
        if not project_id or not node_id:
            return fail(errors.VALIDATION_ERROR, request, message="projectId 和 nodeId 不能为空。")
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=[node_id])
        if guard:
            return guard
        project = repo.require_project(project_id)
        if not project:
            return fail(errors.NOT_FOUND, request)
        pack = business_pack_for_project(project)
        agent = (pack.get("agentSops") or [{}])[0]
        evidence_link_ids = body.get("evidenceLinkIds") or []
        rule_refs = body.get("ruleRefs") or []
        if body.get("source") == "ai" and (not evidence_link_ids or not rule_refs):
            return fail(
                errors.VALIDATION_ERROR,
                request,
                message="AI 审查发现必须包含 evidenceLinkIds 和 ruleRefs。",
            )
        finding = {
            "id": body.get("id") or f"FND-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "nodeId": node_id,
            "businessPackId": pack["id"],
            "businessPackVersion": pack["version"],
            "businessPackSnapshotHash": pack["snapshotHash"],
            "agentId": body.get("agentId") or agent.get("id"),
            "agentVersion": body.get("agentVersion") or agent.get("version"),
            "findingType": body.get("findingType") or "manual_review",
            "severity": body.get("severity") or "medium",
            "title": body.get("title") or "审查发现",
            "description": body.get("description") or body.get("opinion") or "请人工确认该发现。",
            "evidenceLinkIds": evidence_link_ids,
            "ruleRefs": rule_refs,
            "kbRefs": body.get("kbRefs") or [],
            "confidence": float(body.get("confidence") or 1),
            "suggestedAction": body.get("suggestedAction") or "human_confirm",
            "status": "draft",
            "source": body.get("source") or "human",
            "humanStatus": body.get("humanStatus") or "pending_human_review",
            "createdAt": server_time(),
            "revision": 1,
        }
        repo.state["review_findings"].insert(0, finding)
        audit_id = repo.add_audit("创建审查发现", "ReviewFinding", finding["id"])
        return ok({"finding": finding, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/review/findings/{finding_id}/accept")
def accept_review_finding(
    request: Request,
    finding_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    def produce():
        finding = repo.find_one("review_findings", finding_id)
        if not finding:
            return fail(errors.NOT_FOUND, request)
        guard = mutation_guard(request, finding["projectId"], x_role=x_role, node_ids=[int(finding["nodeId"])])
        if guard:
            return guard
        finding["status"] = "accepted"
        finding["acceptedAt"] = server_time()
        finding["revision"] = int(finding.get("revision") or 1) + 1
        opinion = {
            "id": f"OPN-{uuid4().hex[:8].upper()}",
            "projectId": finding["projectId"],
            "nodeId": finding["nodeId"],
            "result": body.get("result") or ("需补正" if finding.get("suggestedAction") == "request_correction" else "满足要求"),
            "opinion": body.get("opinion") or finding["description"],
            "findingType": finding["findingType"],
            "ruleRefs": finding.get("ruleRefs") or [],
            "kbRefs": finding.get("kbRefs") or [],
            "evidenceLinkIds": finding.get("evidenceLinkIds") or [],
            "reviewerName": "张工",
            "createdAt": server_time(),
        }
        repo.state["review_opinions"].insert(0, opinion)
        audit_id = repo.add_audit("采纳审查发现", "ReviewFinding", finding_id)
        return ok({"finding": finding, "opinion": opinion, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"findingId": finding_id, "body": body})


@router.post("/review/findings/{finding_id}/reject")
def reject_review_finding(
    request: Request,
    finding_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    def produce():
        finding = repo.find_one("review_findings", finding_id)
        if not finding:
            return fail(errors.NOT_FOUND, request)
        guard = mutation_guard(request, finding["projectId"], x_role=x_role, node_ids=[int(finding["nodeId"])])
        if guard:
            return guard
        finding["status"] = "rejected"
        finding["rejectReason"] = body.get("reason") or "人工驳回。"
        finding["rejectedAt"] = server_time()
        finding["revision"] = int(finding.get("revision") or 1) + 1
        audit_id = repo.add_audit("驳回审查发现", "ReviewFinding", finding_id)
        return ok({"finding": finding, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"findingId": finding_id, "body": body})


@router.post("/ai/runs/{run_id}/feedback")
def create_ai_run_feedback(
    request: Request,
    run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    def produce():
        run = repo.find_one("ai_runs", run_id)
        if not run:
            return fail(errors.NOT_FOUND, request)
        guard = mutation_guard(
            request,
            run["projectId"],
            x_role=x_role,
            node_ids=[int(run["nodeId"])],
        )
        if guard:
            return guard
        feedback_type = body.get("feedbackType") or body.get("type") or "edited"
        if feedback_type not in AI_FEEDBACK_TYPES:
            return fail(
                errors.VALIDATION_ERROR,
                request,
                message="AI 反馈类型不支持。",
                data={"allowedTypes": sorted(AI_FEEDBACK_TYPES)},
            )
        feedback = {
            "id": body.get("id") or f"AIFB-{uuid4().hex[:8].upper()}",
            "aiRunId": run_id,
            "projectId": run["projectId"],
            "nodeId": run["nodeId"],
            "agentId": run.get("agentId"),
            "agentVersion": run.get("agentVersion"),
            "businessPackId": run.get("businessPackId"),
            "businessPackVersion": run.get("businessPackVersion"),
            "feedbackType": feedback_type,
            "accepted": bool(body.get("accepted", False)),
            "comment": body.get("comment") or body.get("reason"),
            "correctedOutput": body.get("correctedOutput"),
            "shouldEnterEvaluationSet": bool(body.get("shouldEnterEvaluationSet", False)),
            "createdAt": server_time(),
        }
        repo.state["ai_feedback"].insert(0, feedback)
        run.setdefault("humanFeedback", []).insert(0, feedback)
        run["status"] = "已人工确认" if feedback["accepted"] else run.get("status")
        audit_id = repo.add_audit("记录 AI 反馈", "AIRun", run_id)
        return ok({"feedback": feedback, "aiRun": repo.clone(run), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"runId": run_id, "body": body})


def fde_error_unless_allowed(request: Request, action: str | None = None) -> tuple[str | None, JSONResponse | None]:
    role, identity_error = effective_role_for_request(request)
    if identity_error:
        return None, identity_error
    role = role or "inspection"
    if role != "admin" and role not in FDE_ROLES:
        return role, fail(errors.FORBIDDEN, request, message="仅 FDE 或管理员可访问 AI 交付治理后台。")
    if action and role != "admin" and action not in repo.role_actions(role):
        return role, fail(errors.FORBIDDEN, request, message=f"角色 {role} 无权执行 {action}。")
    return role, None


def stable_hash_payload(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ai_run_snapshot(run: dict[str, Any]) -> dict[str, Any]:
    project = repo.require_project(run.get("projectId"))
    pack = business_pack_for_project(project) if project else load_business_pack(run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID)
    return {
        "businessPackId": run.get("businessPackId") or pack["id"],
        "businessPackVersion": run.get("businessPackVersion") or pack["version"],
        "businessPackSnapshotHash": run.get("businessPackSnapshotHash") or pack["snapshotHash"],
        "agentId": run.get("agentId") or "unknown_agent",
        "agentVersion": run.get("agentVersion") or "unknown",
        "promptVersion": run.get("promptVersion") or "unknown",
        "modelAlias": run.get("model") or "review-chat",
        "modelResolved": run.get("modelResolved") or run.get("model") or "review-chat",
        "ruleSetVersion": run.get("ruleVersion") or "unknown",
        "knowledgeBaseVersion": run.get("knowledgeBaseVersion") or "proj-v2026.06.26",
        "ocrResultVersions": run.get("ocrResultVersions") or [],
        "inputDocumentVersionIds": run.get("inputDocumentVersionIds") or [],
        "schemaVersion": run.get("schemaVersion") or "ReviewFindingDraftList@1.0.0",
        "runType": run.get("runType") or "production",
    }


def has_raw_access(request: Request, target_type: str, target_id: str) -> bool:
    role, _ = effective_role_for_request(request)
    if role == "admin":
        return True
    user_id = fde_subject_user_id(request)
    if not user_id:
        return False
    now = server_time()
    return any(
        grant.get("subjectUserId") == user_id
        and grant.get("targetType") == target_type
        and grant.get("targetId") == target_id
        and grant.get("status") == "approved"
        and str(grant.get("expiresAt") or "") >= now
        for grant in repo.state.get("access_grants", [])
    )


def fde_subject_user_id(request: Request) -> str | None:
    explicit_user_id = request_user_id(request)
    if explicit_user_id:
        return explicit_user_id
    role, _ = effective_role_for_request(request)
    if role and role in USERS:
        return USERS[role].get("id")
    return None


def mask_text(value: Any, *, visible: int = 24) -> Any:
    if not isinstance(value, str):
        return value
    if len(value) <= visible:
        return value
    return f"{value[:visible]}...<masked>"


def fde_ai_run_view(run: dict[str, Any], *, raw_access: bool = False) -> dict[str, Any]:
    snapshot = ai_run_snapshot(run)
    view = repo.clone(run)
    view["versionSnapshot"] = snapshot
    view["inputHash"] = run.get("inputHash") or stable_hash_payload(snapshot["inputDocumentVersionIds"])
    view["outputHash"] = run.get("outputHash") or stable_hash_payload(
        {"suggestion": run.get("suggestion"), "findingDrafts": run.get("findingDrafts") or []}
    )
    view["immutable"] = True
    view["rawAccess"] = raw_access
    if not raw_access:
        suggestion = view.get("suggestion") or {}
        if isinstance(suggestion, dict):
            suggestion["opinionDraft"] = mask_text(suggestion.get("opinionDraft"), visible=60)
        for evidence in view.get("evidenceLinks") or []:
            if isinstance(evidence, dict):
                evidence["quotedText"] = mask_text(evidence.get("quotedText"), visible=36)
        for finding in view.get("findingDrafts") or []:
            if isinstance(finding, dict):
                finding["description"] = mask_text(finding.get("description"), visible=80)
    return view


def fde_metric(label: str, value: Any, tone: str = "blue", suffix: str = "") -> dict[str, Any]:
    return {"label": label, "value": value, "tone": tone, "suffix": suffix}


def acceptance_rate() -> float:
    feedback = repo.state.get("ai_feedback", [])
    if not feedback:
        return 0.0
    accepted = len([item for item in feedback if item.get("accepted") or item.get("feedbackType") in {"accepted", "edited"}])
    return round(accepted / len(feedback), 4)


def evidence_hit_rate() -> float:
    findings = [item for item in repo.state.get("review_findings", []) if item.get("source") == "ai"]
    if not findings:
        return 0.0
    with_evidence = len([item for item in findings if item.get("evidenceLinkIds") and item.get("ruleRefs")])
    return round(with_evidence / len(findings), 4)


def hallucination_rate() -> float:
    feedback = repo.state.get("ai_feedback", [])
    if not feedback:
        return 0.0
    hallucinations = len([item for item in feedback if item.get("feedbackType") == "hallucination"])
    return round(hallucinations / len(feedback), 4)


def false_positive_rate() -> float:
    feedback = repo.state.get("ai_feedback", [])
    if not feedback:
        return 0.0
    false_positive = len([item for item in feedback if item.get("feedbackType") == "rejected_false_positive"])
    return round(false_positive / len(feedback), 4)


def suspected_miss_rate() -> float:
    feedback = repo.state.get("ai_feedback", [])
    if not feedback:
        return 0.0
    missed = len([item for item in feedback if item.get("feedbackType") == "missed_issue"])
    return round(missed / len(feedback), 4)


def fde_trace_steps_for_run(run: dict[str, Any]) -> list[dict[str, Any]]:
    run_id = str(run.get("id"))
    steps = [repo.clone(item) for item in repo.state.get("ai_trace_steps", []) if item.get("aiRunId") == run_id]
    if steps:
        return sorted(steps, key=lambda item: int(item.get("sequence") or 0))
    return repo.clone(run.get("steps") or [])


def fde_evaluation_report_for_run(run_id: str) -> dict[str, Any] | None:
    return repo.find_one("evaluation_reports", run_id, id_field="evaluationRunId")


def fde_find_evaluation_report(report_ref: str | None) -> dict[str, Any] | None:
    if not report_ref:
        return None
    return repo.find_one("evaluation_reports", report_ref) or repo.find_one(
        "evaluation_reports", report_ref, id_field="evaluationRunId"
    )


def fde_release_gate_results(plan: dict[str, Any]) -> list[dict[str, Any]]:
    risk_level = plan.get("riskLevel") or "medium"
    report_id = plan.get("evaluationReportId")
    rollback_plan_id = plan.get("rollbackPlanId")
    report = fde_find_evaluation_report(str(report_id)) if report_id else None
    approvals = [
        item
        for item in repo.state.get("release_approvals", [])
        if item.get("releasePlanId") == plan.get("id")
        and item.get("status") == "approved"
        and item.get("role") in {"admin", "ai_owner", "platform_admin", "customer_admin"}
    ]
    active_risk_set = any(
        item.get("setType") == "risk" and item.get("status") == "active"
        for item in repo.state.get("evaluation_sets", [])
    )
    gates = [
        {
            "gate": "capability_bundle",
            "passed": bool(repo.find_one("capability_bundles", plan.get("capabilityBundleId"))),
            "message": "Capability Bundle 存在" if plan.get("capabilityBundleId") else "缺少 Capability Bundle",
        },
        {
            "gate": "evaluation_report",
            "passed": bool(report and report.get("status") == "passed"),
            "message": "评估报告已通过" if report and report.get("status") == "passed" else ("评估报告未通过" if report else "缺少评估报告"),
        },
        {
            "gate": "risk_set",
            "passed": active_risk_set,
            "message": "Risk Set 已启用" if active_risk_set else "缺少启用状态的 Risk Set",
        },
        {
            "gate": "rollback_plan",
            "passed": bool(rollback_plan_id),
            "message": "已绑定回滚方案" if rollback_plan_id else "缺少回滚方案",
        },
        {
            "gate": "release_approval",
            "passed": bool(approvals),
            "message": "已获得非 FDE 发布审批" if approvals else "高风险发布需要 AI 负责人或管理员审批",
        },
    ]
    if risk_level != "high":
        for gate in gates:
            if gate["gate"] in {"evaluation_report", "risk_set", "rollback_plan", "release_approval"}:
                gate["passed"] = True
                gate["message"] = "中低风险发布不强制此门禁"
    return gates


def fde_persist_release_gates(plan: dict[str, Any], gates: list[dict[str, Any]]) -> None:
    release_id = plan["id"]
    repo.state["release_gates"] = [
        item for item in repo.state.get("release_gates", []) if item.get("releasePlanId") != release_id
    ]
    for gate in gates:
        repo.state["release_gates"].append(
            {
                "id": f"RGATE-{uuid4().hex[:8].upper()}",
                "releasePlanId": release_id,
                "gate": gate["gate"],
                "passed": gate["passed"],
                "message": gate["message"],
                "checkedAt": server_time(),
            }
        )


def fde_business_pack_validation_result(pack_id: str) -> dict[str, Any] | None:
    try:
        pack = load_business_pack(pack_id)
    except FileNotFoundError:
        return None
    validation = validate_business_pack(pack)
    return {"summary": business_pack_summary(pack), "validation": validation}


def fde_state_list(collection: str) -> list[dict[str, Any]]:
    repo.state.setdefault(collection, [])
    return repo.state[collection]


def fde_diff_value(value: Any) -> Any:
    if isinstance(value, dict):
        ignored = {"createdAt", "updatedAt", "installedAt", "submittedAt", "approvedAt", "shadowStartedAt"}
        return {key: fde_diff_value(value[key]) for key in sorted(value) if key not in ignored}
    if isinstance(value, list):
        return [fde_diff_value(item) for item in value]
    return value


def fde_record_diff(current: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    baseline = baseline or {}
    current_normalized = fde_diff_value(current)
    baseline_normalized = fde_diff_value(baseline)
    keys = sorted(set(current_normalized) | set(baseline_normalized))
    changes = []
    for key in keys:
        before = baseline_normalized.get(key)
        after = current_normalized.get(key)
        if before != after:
            changes.append({"field": key, "before": before, "after": after})
    return {
        "changed": bool(changes),
        "changeCount": len(changes),
        "changes": changes,
        "addedKeys": [key for key in keys if key not in baseline_normalized],
        "removedKeys": [key for key in keys if key not in current_normalized],
    }


def fde_default_masking_policies() -> list[dict[str, Any]]:
    policies = fde_state_list("masking_policies")
    if policies:
        return policies
    defaults = [
        {
            "id": "MASK-AIRUN-DEFAULT",
            "targetType": "ai_run",
            "fieldPath": "suggestion.opinionDraft",
            "strategy": "prefix",
            "visibleChars": 60,
            "status": "active",
            "riskLevel": "medium",
            "createdAt": server_time(),
        },
        {
            "id": "MASK-EVIDENCE-DEFAULT",
            "targetType": "evidence",
            "fieldPath": "quotedText",
            "strategy": "prefix",
            "visibleChars": 36,
            "status": "active",
            "riskLevel": "high",
            "createdAt": server_time(),
        },
    ]
    policies.extend(defaults)
    return policies


def fde_audit_event_scope(item: dict[str, Any]) -> bool:
    action = str(item.get("action") or "")
    object_type = str(item.get("objectType") or "")
    return action.startswith(("FDE", "管理员批准 FDE", "管理员审批 FDE")) or object_type in {
        "AccessGrant",
        "DataExport",
        "AIRunReplay",
        "ReviewRun",
        "FeedbackTriage",
        "EvaluationRun",
        "CapabilityBundle",
        "ReleasePlan",
        "BusinessPackInstallation",
        "IncidentRCA",
        "OcrCorrection",
        "OcrEvaluationRun",
        "CostBudgetChangeRequest",
        "MaskingPolicy",
    }


@router.get("/fde/dashboard")
def fde_dashboard(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:dashboard:view")
    if role_error:
        return role_error
    ai_runs = repo.state.get("ai_runs", [])
    failed_runs = [item for item in ai_runs if item.get("status") == "失败"]
    ocr_documents = repo.state.get("documents", [])
    ocr_success = len([item for item in ocr_documents if item.get("currentOcrStatus") == "已识别"])
    ocr_total = len(ocr_documents) or 1
    return ok(
        {
            "metrics": [
                fde_metric("AI Run", len(ai_runs)),
                fde_metric("成功率", round((len(ai_runs) - len(failed_runs)) / (len(ai_runs) or 1), 4), "green", "%"),
                fde_metric("采纳率", acceptance_rate(), "green", "%"),
                fde_metric("证据命中率", evidence_hit_rate(), "blue", "%"),
                fde_metric("误报率", false_positive_rate(), "orange", "%"),
                fde_metric("疑似漏报率", suspected_miss_rate(), "red", "%"),
                fde_metric("幻觉率", hallucination_rate(), "red", "%"),
                fde_metric("OCR 成功率", round(ocr_success / ocr_total, 4), "orange", "%"),
            ],
            "alerts": [
                {"id": item["id"], "severity": item["severity"], "title": item["title"], "status": item["status"]}
                for item in repo.state.get("incidents", [])
            ],
            "agentPerformance": [
                {
                    "agentId": agent["agentId"],
                    "version": agent["version"],
                    "status": agent["status"],
                    "riskLevel": agent["riskLevel"],
                    "acceptanceRate": acceptance_rate(),
                    "evidenceHitRate": evidence_hit_rate(),
                    "hallucinationRate": hallucination_rate(),
                }
                for agent in repo.state.get("agent_versions", [])
            ],
            "cost": {
                "tokenEstimate": sum(int(item.get("tokenUsage") or 0) for item in ai_runs),
                "estimatedPrice": round(sum(float(item.get("estimatedPrice") or 0) for item in ai_runs), 4),
                "budgetStatus": (repo.state.get("cost_budgets") or [{"status": "normal"}])[0].get("status", "normal"),
            },
            "releaseStatus": {
                "bundles": len(repo.state.get("capability_bundles", [])),
                "releasePlans": len(repo.state.get("release_plans", [])),
                "pendingApprovals": len([item for item in repo.state.get("release_plans", []) if item.get("status") in {"submitted", "canary_requested"}]),
            },
        },
        request,
    )


@router.get("/fde/audit-events")
def fde_audit_events(
    request: Request,
    objectType: str | None = None,
    objectId: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    _, role_error = fde_error_unless_allowed(request, "fde:security:manage")
    if role_error:
        return role_error
    items = [repo.clone(item) for item in repo.state.get("audit_logs", []) if fde_audit_event_scope(item)]
    if objectType:
        items = [item for item in items if item.get("objectType") == objectType]
    if objectId:
        items = [item for item in items if item.get("objectId") == objectId]
    return ok({"events": items[:limit], "total": len(items)}, request)


@router.get("/fde/security/masking-policies")
def fde_masking_policies(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:security:manage")
    if role_error:
        return role_error
    return ok(repo.clone(fde_default_masking_policies()), request)


@router.post("/fde/security/masking-policies")
def fde_create_masking_policy(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:security:manage")
        if role_error:
            return role_error
        policy = {
            "id": body.get("id") or f"MASK-{uuid4().hex[:8].upper()}",
            "targetType": body.get("targetType") or "ai_run",
            "fieldPath": body.get("fieldPath") or "suggestion.opinionDraft",
            "strategy": body.get("strategy") or "prefix",
            "visibleChars": int(body.get("visibleChars") or 24),
            "status": body.get("status") or "draft",
            "riskLevel": body.get("riskLevel") or "medium",
            "createdByRole": effective_role_for_request(request)[0],
            "createdAt": server_time(),
        }
        fde_state_list("masking_policies").insert(0, policy)
        audit_id = repo.add_audit("FDE 创建脱敏策略草稿", "MaskingPolicy", policy["id"])
        return ok({"policy": policy, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/fde/ai-runs")
def fde_ai_runs(
    request: Request,
    projectId: str | None = None,
    businessPackId: str | None = None,
    status: str | None = None,
    page_no: int = Query(default=1, alias="page"),
    page_size: int = Query(default=20, alias="pageSize"),
):
    _, role_error = fde_error_unless_allowed(request, "fde:ai-run:view-masked")
    if role_error:
        return role_error
    items = [repo.clone(item) for item in repo.state.get("ai_runs", [])]
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if businessPackId:
        items = [item for item in items if item.get("businessPackId") == businessPackId]
    if status:
        items = [item for item in items if item.get("status") == status]
    return ok(page([fde_ai_run_view(item) for item in items], page_no, page_size), request)


@router.get("/fde/ai-runs/{run_id}")
def fde_ai_run_detail(request: Request, run_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:ai-run:view-masked")
    if role_error:
        return role_error
    run = repo.find_one("ai_runs", run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    raw = has_raw_access(request, "ai_run", run_id)
    return ok(
        {
            "run": fde_ai_run_view(run, raw_access=raw),
            "traceSteps": fde_trace_steps_for_run(run),
            "replays": [repo.clone(item) for item in repo.state.get("ai_run_replays", []) if item.get("parentRunId") == run_id],
            "feedback": [repo.clone(item) for item in repo.state.get("ai_feedback", []) if item.get("aiRunId") == run_id],
            "accessPolicy": {"rawAccess": raw, "rawAccessRequiresGrant": not raw},
        },
        request,
    )


@router.get("/fde/review-runs")
def fde_review_runs(
    request: Request,
    projectId: str | None = None,
    businessPackId: str | None = None,
    status: str | None = None,
    page_no: int = Query(default=1, alias="page"),
    page_size: int = Query(default=20, alias="pageSize"),
):
    _, role_error = fde_error_unless_allowed(request, "fde:ai-run:view-masked")
    if role_error:
        return role_error
    refresh_state_from_mongo_for_live_read()
    items = [repo.clone(item) for item in repo.state.get("review_runs", [])]
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if businessPackId:
        items = [item for item in items if item.get("businessPackId") == businessPackId]
    if status:
        items = [item for item in items if item.get("status") == status]
    return ok(page([review_run_view(item) for item in items], page_no, page_size), request)


@router.get("/fde/review-runs/{review_run_id}")
def fde_review_run_detail(request: Request, review_run_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:ai-run:view-masked")
    if role_error:
        return role_error
    refresh_state_from_mongo_for_live_read()
    run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    graph = graph_view_for_review_run(review_run_id)
    temporal = temporal_history_summary(run)
    return ok(
        {
            "run": review_run_view(run),
            "graph": graph,
            "timeline": review_run_timeline(review_run_id),
            "temporal": temporal,
            "scorecard": build_review_orchestration_scorecard(
                review_run=run,
                graph_view=graph,
                temporal_history=temporal,
            ),
        },
        request,
    )


@router.get("/fde/review-runs/{review_run_id}/graph")
def fde_review_run_graph(request: Request, review_run_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:ai-run:view-masked")
    if role_error:
        return role_error
    refresh_state_from_mongo_for_live_read()
    run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    return ok({"reviewRunId": review_run_id, **graph_view_for_review_run(review_run_id)}, request)


@router.get("/fde/review-runs/{review_run_id}/temporal-history")
def fde_review_run_temporal_history(request: Request, review_run_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:ai-run:view-masked")
    if role_error:
        return role_error
    refresh_state_from_mongo_for_live_read()
    run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    return ok(temporal_history_summary(run), request)


@router.post("/fde/review-runs/{review_run_id}/replay")
def fde_replay_review_run(
    request: Request,
    review_run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:ai-run:replay")
        if role_error:
            return role_error
        refresh_state_from_mongo_for_live_read()
        parent = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
        if not parent:
            return fail(errors.NOT_FOUND, request)
        run_type = body.get("runMode") or body.get("runType") or "diagnostic_replay"
        if run_type not in FDE_REPLAY_TYPES:
            return fail(errors.VALIDATION_ERROR, request, message="FDE ReviewRun 重跑类型不支持。", data={"allowedTypes": sorted(FDE_REPLAY_TYPES)})
        child = clone_review_run_for_replay(parent, run_mode=run_type, reason=body.get("reason"))
        audit_id = repo.add_audit("FDE 创建 ReviewRun 重跑", "ReviewRun", child["reviewRunId"])
        return ok({"reviewRun": review_run_view(child), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"reviewRunId": review_run_id, "body": body})


@router.post("/fde/review-runs/{review_run_id}/shadow-run")
def fde_shadow_review_run(
    request: Request,
    review_run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    body = {**body, "runMode": "shadow_replay", "reason": body.get("reason") or "FDE Shadow Run"}
    return fde_replay_review_run(request, review_run_id, body, idempotency_key)


def temporal_history_summary(run: dict[str, Any]) -> dict[str, Any]:
    events = review_run_timeline(str(run.get("reviewRunId") or run.get("id")))
    return {
        "workflowEngine": run.get("workflowEngine") or "temporal",
        "workflowType": run.get("workflowType") or "ReviewRunWorkflow",
        "workflowId": run.get("workflowId"),
        "temporalRunId": run.get("temporalRunId"),
        "namespace": run.get("temporalNamespace") or "default",
        "historyPolicy": "ids_hashes_versions_only",
        "payloadCodecRequired": bool((run.get("sensitivePayloadPolicy") or {}).get("payloadCodecRequiredInProduction", True)),
        "eventCount": len(events),
        "events": events[:100],
    }


@router.get("/fde/access-grants")
def fde_access_grants(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:security:manage")
    if role_error:
        return role_error
    return ok(repo.clone(repo.state.get("access_grants", [])), request)


@router.post("/fde/access-grants/request")
def fde_request_access_grant(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:security:manage")
        if role_error:
            return role_error
        target_type = body.get("targetType") or "ai_run"
        target_id = body.get("targetId")
        if target_type != "ai_run" or not target_id or not repo.find_one("ai_runs", target_id):
            return fail(errors.VALIDATION_ERROR, request, message="targetType/targetId 无效。")
        grant = {
            "id": body.get("id") or f"AGRANT-{uuid4().hex[:8].upper()}",
            "subjectUserId": fde_subject_user_id(request) or "USER-FDE-001",
            "targetType": target_type,
            "targetId": target_id,
            "status": "pending",
            "reason": body.get("reason") or "FDE 诊断需要查看原文。",
            "requestedByRole": effective_role_for_request(request)[0],
            "requestedAt": server_time(),
            "expiresAt": body.get("expiresAt") or "9999-12-31 23:59:59",
        }
        repo.state["access_grants"].insert(0, grant)
        audit_id = repo.add_audit("FDE 申请原文访问授权", "AccessGrant", grant["id"])
        return ok({"grant": grant, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/fde/access-grants/{grant_id}/approve")
def fde_approve_access_grant(
    request: Request,
    grant_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, identity_error = effective_role_for_request(request)
        if identity_error:
            return identity_error
        if role != "admin":
            return fail(errors.FORBIDDEN, request, message="只有管理员可以批准 FDE 原文访问。")
        grant = repo.find_one("access_grants", grant_id)
        if not grant:
            return fail(errors.NOT_FOUND, request)
        grant["status"] = body.get("status") or "approved"
        grant["approvedByRole"] = role
        grant["approvedAt"] = server_time()
        grant["expiresAt"] = body.get("expiresAt") or grant.get("expiresAt") or "9999-12-31 23:59:59"
        audit_id = repo.add_audit("管理员批准 FDE 原文访问", "AccessGrant", grant_id)
        return ok({"grant": repo.clone(grant), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"grantId": grant_id, "body": body})


@router.post("/fde/data-exports")
def fde_create_data_export(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:security:manage")
        if role_error:
            return role_error
        export = {
            "id": body.get("id") or f"DEXP-{uuid4().hex[:8].upper()}",
            "requesterUserId": fde_subject_user_id(request) or "USER-FDE-001",
            "targetType": body.get("targetType") or "ai_run",
            "targetId": body.get("targetId"),
            "status": "pending_approval",
            "masked": bool(body.get("masked", True)),
            "watermark": f"FDE-{uuid4().hex[:6].upper()}",
            "createdAt": server_time(),
            "expiresAt": body.get("expiresAt") or "9999-12-31 23:59:59",
        }
        repo.state["data_exports"].insert(0, export)
        audit_id = repo.add_audit("FDE 创建数据导出申请", "DataExport", export["id"])
        return ok({"export": export, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/fde/data-exports/{export_id}/approve")
def fde_approve_data_export(
    request: Request,
    export_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, identity_error = effective_role_for_request(request)
        if identity_error:
            return identity_error
        if role != "admin":
            return fail(errors.FORBIDDEN, request, message="只有管理员可以批准 FDE 数据导出。")
        export = next((item for item in fde_state_list("data_exports") if item.get("id") == export_id), None)
        if not export:
            return fail(errors.NOT_FOUND, request)
        export["status"] = body.get("status") or "approved"
        export["approvedByRole"] = role
        export["approvedAt"] = server_time()
        export["downloadStatus"] = "ready" if export["status"] == "approved" else "blocked"
        audit_id = repo.add_audit("管理员批准 FDE 数据导出", "DataExport", export_id)
        return ok({"export": repo.clone(export), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"exportId": export_id, "body": body})


@router.post("/fde/data-exports/{export_id}/expire")
def fde_expire_data_export(
    request: Request,
    export_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:security:manage")
        if role_error:
            return role_error
        export = next((item for item in fde_state_list("data_exports") if item.get("id") == export_id), None)
        if not export:
            return fail(errors.NOT_FOUND, request)
        export["status"] = "expired"
        export["expiredAt"] = server_time()
        export["expireReason"] = body.get("reason") or "FDE 手动过期导出。"
        export["downloadStatus"] = "expired"
        audit_id = repo.add_audit("FDE 过期数据导出", "DataExport", export_id)
        return ok({"export": repo.clone(export), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"exportId": export_id, "body": body})


@router.post("/fde/ai-runs/{run_id}/replay")
def fde_replay_ai_run(
    request: Request,
    run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:ai-run:replay")
        if role_error:
            return role_error
        parent = repo.find_one("ai_runs", run_id)
        if not parent:
            return fail(errors.NOT_FOUND, request)
        run_type = body.get("runType") or "diagnostic_replay"
        if run_type not in FDE_REPLAY_TYPES:
            return fail(errors.VALIDATION_ERROR, request, message="FDE 重跑类型不支持。", data={"allowedTypes": sorted(FDE_REPLAY_TYPES)})
        child_id = body.get("childRunId") or f"AIRUN-REPLAY-{uuid4().hex[:8].upper()}"
        child = repo.clone(parent)
        child.update(
            {
                "id": child_id,
                "parentRunId": run_id,
                "runType": run_type,
                "status": "排队中",
                "startedAt": server_time(),
                "finishedAt": None,
                "replayReason": body.get("reason") or "FDE 诊断重跑",
                "immutable": True,
                "inputHash": stable_hash_payload(parent.get("inputDocumentVersionIds") or []),
                "outputHash": stable_hash_payload(parent.get("suggestion") or {}),
            }
        )
        replay = {
            "id": f"REPLAY-{uuid4().hex[:8].upper()}",
            "parentRunId": run_id,
            "childRunId": child_id,
            "runType": run_type,
            "status": "created",
            "requestedByRole": effective_role_for_request(request)[0],
            "reason": body.get("reason"),
            "createdAt": server_time(),
        }
        repo.state["ai_runs"].insert(0, child)
        repo.state["ai_run_replays"].insert(0, replay)
        audit_id = repo.add_audit("FDE 创建 AI Run 重跑", "AIRunReplay", replay["id"])
        return ok({"replay": replay, "childRun": fde_ai_run_view(child), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"runId": run_id, "body": body})


@router.get("/fde/feedback")
def fde_feedback(request: Request, feedbackType: str | None = None, status: str | None = None):
    _, role_error = fde_error_unless_allowed(request, "fde:feedback:view")
    if role_error:
        return role_error
    items = [repo.clone(item) for item in repo.state.get("ai_feedback", [])]
    if feedbackType:
        items = [item for item in items if item.get("feedbackType") == feedbackType]
    if status:
        items = [item for item in items if item.get("status") == status]
    triage_by_feedback = {item.get("feedbackId"): item for item in repo.state.get("feedback_triage", [])}
    return ok([fde_feedback_governance_view(item, triage_by_feedback.get(item["id"])) for item in items], request)


def fde_feedback_governance_view(
    feedback: dict[str, Any],
    triage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item = repo.clone(feedback)
    triage_record = triage or repo.find_one("feedback_triage", str(item.get("id")), id_field="feedbackId")
    evaluation_case = next(
        (
            case
            for case in repo.state.get("evaluation_cases", [])
            if case.get("sourceFeedbackId") == item.get("id")
        ),
        None,
    )
    can_use_for_eval = bool((triage_record or {}).get("canUseForEval", item.get("shouldEnterEvaluationSet", False)))
    can_use_for_training = bool((triage_record or {}).get("canUseForTraining", False))
    adjudication_required = bool((triage_record or {}).get("adjudicationRequired", False))
    if adjudication_required:
        governance_state = "needs_adjudication"
    elif evaluation_case:
        governance_state = "promoted_to_eval"
    elif not triage_record:
        governance_state = "needs_triage"
    elif can_use_for_eval:
        governance_state = "ready_for_eval"
    else:
        governance_state = "triaged"
    item.update(
        {
            "triage": repo.clone(triage_record) if triage_record else None,
            "evaluationCaseId": (evaluation_case or {}).get("id"),
            "evaluationSetId": (evaluation_case or {}).get("evaluationSetId"),
            "evaluationCaseStatus": (evaluation_case or {}).get("status"),
            "canUseForEval": can_use_for_eval,
            "canUseForTraining": can_use_for_training,
            "dataSensitivity": (triage_record or {}).get("dataSensitivity") or "masked",
            "adjudicationRequired": adjudication_required,
            "governanceState": governance_state,
            "sampleUsage": {
                "sourceFeedbackId": item.get("id"),
                "evaluationCaseId": (evaluation_case or {}).get("id"),
                "canUseForEval": can_use_for_eval,
                "canUseForTraining": can_use_for_training,
                "dataSensitivity": (triage_record or {}).get("dataSensitivity") or "masked",
                "adjudicationRequired": adjudication_required,
            },
        }
    )
    return item


def fde_expected_findings_from_feedback(feedback: dict[str, Any]) -> list[Any]:
    corrected = feedback.get("correctedOutput")
    if isinstance(corrected, dict):
        for key in ("findings", "manualConfirmItems", "expectedFindings"):
            value = corrected.get(key)
            if isinstance(value, list):
                return repo.clone(value)
        if corrected.get("title"):
            return [repo.clone(corrected)]
    if isinstance(corrected, list):
        return repo.clone(corrected)
    if feedback.get("feedbackType") == "rejected_false_positive":
        return []
    original = feedback.get("originalAiOutput")
    return repo.clone(original if isinstance(original, list) else [])


def fde_select_evaluation_set(feedback: dict[str, Any], triage: dict[str, Any], requested_set_id: str | None = None) -> dict[str, Any]:
    if requested_set_id:
        requested = repo.find_one("evaluation_sets", requested_set_id)
        if requested:
            return requested
    business_pack_id = feedback.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID
    preferred_type = (
        "risk"
        if triage.get("rootCause") in {"kb_retrieval_error", "kb_content_error", "model_reasoning_error", "schema_error"}
        else "golden"
    )
    active_sets = [
        item
        for item in repo.state.get("evaluation_sets", [])
        if item.get("status") == "active" and item.get("businessPackId") == business_pack_id
    ]
    for item in active_sets:
        if item.get("setType") == preferred_type:
            return item
    if active_sets:
        return active_sets[0]
    created = {
        "id": f"ESET-{preferred_type.upper()}-{uuid4().hex[:8].upper()}",
        "name": "FDE 反馈自动评估集",
        "setType": preferred_type,
        "businessPackId": business_pack_id,
        "caseCount": 0,
        "riskLevel": "high" if preferred_type == "risk" else "medium",
        "status": "active",
        "createdAt": server_time(),
        "source": "fde_feedback_triage",
    }
    repo.state.setdefault("evaluation_sets", []).insert(0, created)
    return created


def fde_upsert_evaluation_case_from_feedback(
    feedback: dict[str, Any],
    triage: dict[str, Any],
    *,
    evaluation_set_id: str | None = None,
) -> dict[str, Any] | None:
    if not (triage.get("status") == "approved_for_eval" or bool(triage.get("canUseForEval"))):
        return None
    repo.state.setdefault("evaluation_cases", [])
    evaluation_set = fde_select_evaluation_set(feedback, triage, evaluation_set_id)
    existing = next(
        (item for item in repo.state["evaluation_cases"] if item.get("sourceFeedbackId") == feedback.get("id")),
        None,
    )
    inferred_risk_level = (
        "high" if triage.get("rootCause") in {"kb_retrieval_error", "kb_content_error", "model_reasoning_error"} else "medium"
    )
    payload = {
        "id": (existing or {}).get("id") or f"ECASE-{uuid4().hex[:8].upper()}",
        "evaluationSetId": evaluation_set["id"],
        "businessPackId": feedback.get("businessPackId") or evaluation_set.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
        "nodeId": feedback.get("nodeId"),
        "source": "human_feedback",
        "sourceFeedbackId": feedback.get("id"),
        "feedbackType": feedback.get("feedbackType"),
        "rootCause": triage.get("rootCause"),
        "riskLevel": triage.get("riskLevel") or inferred_risk_level,
        "inputDocumentVersionIds": repo.clone(feedback.get("inputDocumentVersionIds") or []),
        "expectedFindings": fde_expected_findings_from_feedback(feedback),
        "expectedEvidence": repo.clone(feedback.get("expectedEvidence") or feedback.get("evidenceRefs") or []),
        "expectedEvidenceLinkIds": repo.clone(feedback.get("expectedEvidenceLinkIds") or []),
        "dataSensitivity": triage.get("dataSensitivity") or "masked",
        "canUseForEval": bool(triage.get("canUseForEval", True)),
        "canUseForTraining": bool(triage.get("canUseForTraining", False)),
        "status": "approved_for_eval",
        "updatedAt": server_time(),
    }
    if existing:
        existing.update(payload)
        return repo.clone(existing)
    payload["createdAt"] = payload["updatedAt"]
    repo.state["evaluation_cases"].insert(0, payload)
    evaluation_set["caseCount"] = int(evaluation_set.get("caseCount") or 0) + 1
    return repo.clone(payload)


@router.post("/fde/feedback/{feedback_id}/triage")
def fde_triage_feedback(
    request: Request,
    feedback_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:feedback:triage")
        if role_error:
            return role_error
        feedback = repo.find_one("ai_feedback", feedback_id)
        if not feedback:
            return fail(errors.NOT_FOUND, request)
        root_cause = body.get("rootCause") or feedback.get("rootCause") or "prompt_error"
        if root_cause not in FDE_ROOT_CAUSES:
            return fail(errors.VALIDATION_ERROR, request, message="纠错归因类型不支持。", data={"allowedTypes": sorted(FDE_ROOT_CAUSES)})
        triage = repo.find_one("feedback_triage", feedback_id, id_field="feedbackId")
        payload = {
            "id": (triage or {}).get("id") or f"FBT-{uuid4().hex[:8].upper()}",
            "feedbackId": feedback_id,
            "status": body.get("status") or "triaged",
            "rootCause": root_cause,
            "dataSensitivity": body.get("dataSensitivity") or "masked",
            "canUseForEval": bool(body.get("canUseForEval", feedback.get("shouldEnterEvaluationSet", False))),
            "canUseForTraining": bool(body.get("canUseForTraining", False)),
            "adjudicationRequired": bool(body.get("adjudicationRequired", False)),
            "updatedAt": server_time(),
        }
        if triage:
            triage.update(payload)
        else:
            repo.state["feedback_triage"].insert(0, payload)
        feedback["status"] = payload["status"]
        feedback["rootCause"] = root_cause
        evaluation_case = fde_upsert_evaluation_case_from_feedback(
            feedback,
            payload,
            evaluation_set_id=body.get("evaluationSetId"),
        )
        audit_id = repo.add_audit("FDE 反馈归因", "HumanFeedback", feedback_id)
        return ok(
            {
                "feedback": fde_feedback_governance_view(feedback, payload),
                "triage": payload,
                "evaluationCase": evaluation_case,
                "auditLogId": audit_id,
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source={"feedbackId": feedback_id, "body": body})


@router.get("/fde/evaluation-sets")
def fde_evaluation_sets(request: Request, setType: str | None = None):
    _, role_error = fde_error_unless_allowed(request, "fde:evaluation:view")
    if role_error:
        return role_error
    items = [repo.clone(item) for item in repo.state.get("evaluation_sets", [])]
    if setType:
        items = [item for item in items if item.get("setType") == setType]
    return ok(
        {
            "sets": items,
            "cases": repo.clone(repo.state.get("evaluation_cases", [])),
            "runs": repo.clone(repo.state.get("evaluation_runs", [])),
            "reports": repo.clone(repo.state.get("evaluation_reports", [])),
        },
        request,
    )


def fde_normalize_eval_value(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("title", "description", "message", "fieldCode", "fieldName"):
            if value.get(key):
                return str(value.get(key)).strip()
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value).strip()


def fde_evaluation_case_overrides(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = body.get("caseResults") or body.get("caseOverrides") or {}
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items() if isinstance(value, dict)}
    if isinstance(raw, list):
        mapped: dict[str, dict[str, Any]] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            case_id = item.get("evaluationCaseId") or item.get("caseId") or item.get("id")
            if case_id:
                mapped[str(case_id)] = item
        return mapped
    return {}


def fde_expected_evidence_for_case(case: dict[str, Any]) -> list[Any]:
    for key in ("expectedEvidence", "expectedEvidenceRefs", "expectedEvidenceLinkIds"):
        value = case.get(key)
        if isinstance(value, list):
            return repo.clone(value)
    return []


def fde_normalize_clause_ref(value: Any) -> str:
    return str(value or "").strip().lower()


def fde_expected_clause_ids_for_case(case: dict[str, Any]) -> list[str]:
    for key in ("expectedClauseIds", "expectedClauses", "expectedKbRefs"):
        value = case.get(key)
        if not isinstance(value, list):
            continue
        clause_ids: list[str] = []
        for item in value:
            if isinstance(item, dict):
                clause_id = item.get("clauseId") or item.get("id")
            else:
                clause_id = item
            if clause_id:
                clause_ids.append(str(clause_id))
        if clause_ids:
            return clause_ids
    return []


def fde_retrieval_query_for_case(case: dict[str, Any], override: dict[str, Any]) -> str:
    for key in ("retrievalQuery", "question", "query"):
        if override.get(key):
            return str(override.get(key))
        if case.get(key):
            return str(case.get(key))
    expected_findings = case.get("expectedFindings") or []
    if expected_findings:
        return fde_normalize_eval_value(expected_findings[0])
    return "审查依据"


def fde_evaluate_retrieval_for_case(
    *,
    evaluation_run_id: str,
    case: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any] | None:
    expected_clause_ids = fde_expected_clause_ids_for_case(case)
    if not expected_clause_ids:
        return None
    query = fde_retrieval_query_for_case(case, override)
    top_k = int(override.get("retrievalTopK") or case.get("retrievalTopK") or 5)
    node_value = case.get("nodeId")
    node_id = int(node_value) if str(node_value or "").isdigit() else None
    trace: dict[str, Any] | None = None
    if "actualClauseIds" in override or "selectedClauseIds" in override:
        selected_clause_ids = [str(item) for item in (override.get("actualClauseIds") or override.get("selectedClauseIds") or [])]
        selected_route = str(override.get("selectedRoute") or case.get("expectedRoute") or "manual_override")
    else:
        retrieval = retrieve_knowledge_clauses(
            repo.state,
            query=query,
            review_run_id=evaluation_run_id,
            business_pack_id=case.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
            node_id=node_id,
            top_k=top_k,
            query_type="fde_evaluation_retrieval",
        )
        trace = retrieval["trace"]
        trace["evaluationRunId"] = evaluation_run_id
        trace["evaluationCaseId"] = case.get("id")
        repo.state.setdefault("retrieval_traces", []).append(trace)
        selected_clause_ids = [str(item.get("clauseId")) for item in trace.get("selectedClauses") or [] if item.get("clauseId")]
        selected_route = str(trace.get("selectedRoute") or "")
    expected_norm = {fde_normalize_clause_ref(item) for item in expected_clause_ids}
    selected_norm = {fde_normalize_clause_ref(item) for item in selected_clause_ids}
    missing_clause_ids = [item for item in expected_clause_ids if fde_normalize_clause_ref(item) not in selected_norm]
    matched_clause_count = len(expected_norm & selected_norm)
    top_clause_id = selected_clause_ids[0] if selected_clause_ids else None
    unexpected_top_clause_id = (
        top_clause_id if top_clause_id and fde_normalize_clause_ref(top_clause_id) not in expected_norm else None
    )
    expected_route = override.get("expectedRoute") or case.get("expectedRoute")
    route_passed = not expected_route or selected_route == str(expected_route)
    expected_count = len(expected_clause_ids)
    retrieval_passed = not missing_clause_ids and not unexpected_top_clause_id and bool(route_passed)
    return {
        "retrievalQuery": query,
        "retrievalTraceId": (trace or {}).get("retrievalTraceId"),
        "expectedClauseIds": expected_clause_ids,
        "selectedClauseIds": selected_clause_ids,
        "missingClauseIds": missing_clause_ids,
        "unexpectedTopClauseId": unexpected_top_clause_id,
        "expectedClauseCount": expected_count,
        "matchedClauseCount": matched_clause_count,
        "retrievalRecall": round(matched_clause_count / expected_count, 4) if expected_count else 1.0,
        "retrievalPassed": retrieval_passed,
        "selectedRoute": selected_route,
        "expectedRoute": expected_route,
        "routePassed": bool(route_passed),
    }


def fde_build_evaluation_case_results(
    *,
    evaluation_run_id: str,
    cases: list[dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("id"))
        override = overrides.get(case_id) or overrides.get(str(case.get("sourceFeedbackId"))) or {}
        expected_findings = repo.clone(case.get("expectedFindings") or [])
        if "actualFindings" in override:
            actual_findings = repo.clone(override.get("actualFindings") or [])
        elif "findings" in override:
            actual_findings = repo.clone(override.get("findings") or [])
        elif "actualFindings" in case:
            actual_findings = repo.clone(case.get("actualFindings") or [])
        elif "candidateFindings" in case:
            actual_findings = repo.clone(case.get("candidateFindings") or [])
        else:
            actual_findings = repo.clone(expected_findings)
        expected_values = {fde_normalize_eval_value(item) for item in expected_findings}
        actual_values = {fde_normalize_eval_value(item) for item in actual_findings}
        missing_findings = sorted(value for value in expected_values if value and value not in actual_values)
        unexpected_findings = sorted(value for value in actual_values if value and value not in expected_values)
        expected_evidence = fde_expected_evidence_for_case(case)
        if "actualEvidence" in override:
            actual_evidence = repo.clone(override.get("actualEvidence") or [])
        elif "evidenceRefs" in override:
            actual_evidence = repo.clone(override.get("evidenceRefs") or [])
        else:
            actual_evidence = repo.clone(expected_evidence)
        evidence_passed = not expected_evidence or bool(actual_evidence)
        retrieval_result = fde_evaluate_retrieval_for_case(
            evaluation_run_id=evaluation_run_id,
            case=case,
            override=override,
        )
        retrieval_passed = True if retrieval_result is None else bool(retrieval_result.get("retrievalPassed"))
        status = "passed" if not missing_findings and evidence_passed and retrieval_passed else "failed"
        result = {
            "id": f"ECRES-{uuid4().hex[:8].upper()}",
            "evaluationRunId": evaluation_run_id,
            "evaluationCaseId": case_id,
            "sourceFeedbackId": case.get("sourceFeedbackId"),
            "businessPackId": case.get("businessPackId"),
            "nodeId": case.get("nodeId"),
            "feedbackType": case.get("feedbackType"),
            "rootCause": case.get("rootCause"),
            "riskLevel": case.get("riskLevel"),
            "status": status,
            "expectedFindingCount": len(expected_findings),
            "matchedFindingCount": max(0, len(expected_values) - len(missing_findings)),
            "actualFindingCount": len(actual_findings),
            "missingFindings": missing_findings,
            "unexpectedFindings": unexpected_findings,
            "expectedEvidenceCount": len(expected_evidence),
            "actualEvidenceCount": len(actual_evidence),
            "evidencePassed": evidence_passed,
            "replayMode": override.get("replayMode") or "static_baseline",
            "createdAt": server_time(),
        }
        if retrieval_result:
            result.update(retrieval_result)
        results.append(result)
    return results


def fde_evaluation_case_summary(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(case_results)
    passed = len([item for item in case_results if item.get("status") == "passed"])
    expected_total = sum(int(item.get("expectedFindingCount") or 0) for item in case_results)
    matched_total = sum(int(item.get("matchedFindingCount") or 0) for item in case_results)
    evidence_required = len([item for item in case_results if int(item.get("expectedEvidenceCount") or 0) > 0])
    evidence_passed = len(
        [
            item
            for item in case_results
            if int(item.get("expectedEvidenceCount") or 0) > 0 and bool(item.get("evidencePassed"))
        ]
    )
    retrieval_required = [
        item for item in case_results if int(item.get("expectedClauseCount") or 0) > 0
    ]
    expected_clause_total = sum(int(item.get("expectedClauseCount") or 0) for item in retrieval_required)
    matched_clause_total = sum(int(item.get("matchedClauseCount") or 0) for item in retrieval_required)
    wrong_reference_count = len([item for item in retrieval_required if item.get("unexpectedTopClauseId")])
    pageindex_triggered = len([item for item in retrieval_required if item.get("selectedRoute") == "pageindex_tree_search"])
    retrieval_passed = len([item for item in retrieval_required if bool(item.get("retrievalPassed"))])
    return {
        "cases": total,
        "passed": passed,
        "failed": total - passed,
        "casePassRate": round(passed / total, 4) if total else 0.0,
        "findingRecall": round(matched_total / expected_total, 4) if expected_total else 1.0,
        "evidenceCoverage": round(evidence_passed / evidence_required, 4) if evidence_required else 1.0,
        "retrievalCases": len(retrieval_required),
        "retrievalPassRate": round(retrieval_passed / len(retrieval_required), 4) if retrieval_required else 1.0,
        "retrievalRecall": round(matched_clause_total / expected_clause_total, 4) if expected_clause_total else 1.0,
        "wrongReferenceRate": round(wrong_reference_count / len(retrieval_required), 4) if retrieval_required else 0.0,
        "pageIndexTriggerRate": round(pageindex_triggered / len(retrieval_required), 4) if retrieval_required else 0.0,
    }


def fde_metric_threshold(metric: str) -> tuple[float, str]:
    if metric == "humanAcceptanceRate":
        return 0.85, ">="
    if metric in {"evidenceHitRate", "casePassRate", "findingRecall", "evidenceCoverage"}:
        return 0.9, ">="
    if metric in {"retrievalRecall", "retrievalPassRate"}:
        return 0.9, ">="
    if metric == "wrongReferenceRate":
        return 0.03, "<="
    if metric == "schemaPassRate":
        return 1.0, ">="
    if metric == "hallucinationRate":
        return 0.01, "<="
    if metric == "highRiskMissRate":
        return 0.005, "<="
    if metric == "failedCaseCount":
        return 0.0, "<="
    if metric == "caseCount":
        return 1.0, ">="
    return 0.0, ">="


def fde_metric_passed(metric: str, value: float | int) -> bool:
    threshold, operator = fde_metric_threshold(metric)
    return float(value) >= threshold if operator == ">=" else float(value) <= threshold


@router.post("/fde/evaluation-runs")
def fde_create_evaluation_run(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:evaluation:run")
        if role_error:
            return role_error
        set_id = body.get("evaluationSetId")
        bundle_id = body.get("capabilityBundleId") or "BUNDLE-REVIEW-202606"
        if not set_id or not repo.find_one("evaluation_sets", set_id):
            return fail(errors.VALIDATION_ERROR, request, message="evaluationSetId 无效。")
        cases = [item for item in repo.state.get("evaluation_cases", []) if item.get("evaluationSetId") == set_id]
        run_id = body.get("id") or f"ERUN-{uuid4().hex[:8].upper()}"
        case_results = fde_build_evaluation_case_results(
            evaluation_run_id=run_id,
            cases=repo.clone(cases),
            overrides=fde_evaluation_case_overrides(body),
        )
        case_summary = fde_evaluation_case_summary(case_results)
        case_count = len(cases)
        metrics = {
            "humanAcceptanceRate": acceptance_rate() or 0.86,
            "evidenceHitRate": evidence_hit_rate() or 0.92,
            "hallucinationRate": hallucination_rate(),
            "highRiskMissRate": 0.0,
            "schemaPassRate": 1.0,
            "casePassRate": case_summary["casePassRate"],
            "findingRecall": case_summary["findingRecall"],
            "evidenceCoverage": case_summary["evidenceCoverage"],
            "retrievalRecall": case_summary["retrievalRecall"],
            "retrievalPassRate": case_summary["retrievalPassRate"],
            "wrongReferenceRate": case_summary["wrongReferenceRate"],
            "pageIndexTriggerRate": case_summary["pageIndexTriggerRate"],
            "failedCaseCount": case_summary["failed"],
            "caseCount": case_count,
        }
        run = {
            "id": run_id,
            "evaluationSetId": set_id,
            "capabilityBundleId": bundle_id,
            "status": "completed",
            "startedAt": server_time(),
            "finishedAt": server_time(),
            "metrics": metrics,
            "caseSummary": case_summary,
            "requestedByRole": effective_role_for_request(request)[0],
        }
        gate_results = [
            {"gate": "golden_set", "passed": metrics["evidenceHitRate"] >= 0.9},
            {"gate": "schema_validation", "passed": metrics["schemaPassRate"] >= 1.0},
            {"gate": "hallucination", "passed": metrics["hallucinationRate"] <= 0.01},
            {"gate": "high_risk_miss", "passed": metrics["highRiskMissRate"] <= 0.005},
            {"gate": "case_pass_rate", "passed": metrics["casePassRate"] >= 0.9},
            {"gate": "finding_recall", "passed": metrics["findingRecall"] >= 0.9},
            {"gate": "evidence_coverage", "passed": metrics["evidenceCoverage"] >= 0.9},
            {"gate": "retrieval_recall", "passed": metrics["retrievalRecall"] >= 0.9},
            {"gate": "wrong_reference", "passed": metrics["wrongReferenceRate"] <= 0.03},
        ]
        report_status = "passed" if all(item["passed"] for item in gate_results) else "failed"
        report = {
            "id": body.get("reportId") or f"EREPORT-{uuid4().hex[:8].upper()}",
            "evaluationRunId": run["id"],
            "capabilityBundleId": bundle_id,
            "businessPackId": (repo.find_one("capability_bundles", bundle_id) or {}).get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
            "status": report_status,
            "summary": "离线评测通过，关键指标满足 FDE 发布门禁。"
            if report_status == "passed"
            else "离线评测未通过，存在样本或指标未满足发布门禁。",
            "metrics": metrics,
            "caseSummary": case_summary,
            "caseResults": repo.clone(case_results),
            "gateResults": gate_results,
            "createdAt": server_time(),
        }
        repo.state.setdefault("evaluation_case_results", [])
        repo.state["evaluation_runs"].insert(0, run)
        repo.state["evaluation_reports"].insert(0, report)
        repo.state["evaluation_case_results"][:0] = repo.clone(case_results)
        for metric, value in metrics.items():
            if isinstance(value, (int, float)):
                threshold, operator = fde_metric_threshold(metric)
                repo.state["evaluation_metrics"].insert(
                    0,
                    {
                        "id": f"EMET-{uuid4().hex[:8].upper()}",
                        "evaluationRunId": run["id"],
                        "metric": metric,
                        "value": value,
                        "threshold": threshold,
                        "operator": operator,
                        "passed": fde_metric_passed(metric, value),
                    },
                )
        audit_id = repo.add_audit("FDE 发起离线评测", "EvaluationRun", run["id"])
        return ok({"run": run, "report": report, "caseResults": case_results, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/fde/evaluation-runs/{run_id}/report")
def fde_evaluation_report(request: Request, run_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:evaluation:view")
    if role_error:
        return role_error
    report = fde_evaluation_report_for_run(run_id)
    if not report:
        return fail(errors.NOT_FOUND, request)
    metrics = [repo.clone(item) for item in repo.state.get("evaluation_metrics", []) if item.get("evaluationRunId") == run_id]
    case_results = [
        repo.clone(item) for item in repo.state.get("evaluation_case_results", []) if item.get("evaluationRunId") == run_id
    ]
    return ok({"report": repo.clone(report), "metrics": metrics, "caseResults": case_results}, request)


@router.get("/fde/capability-bundles")
def fde_capability_bundles(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:business-pack:view")
    if role_error:
        return role_error
    return ok(
        {
            "bundles": repo.clone(repo.state.get("capability_bundles", [])),
            "agents": repo.clone(repo.state.get("agent_versions", [])),
            "prompts": repo.clone(repo.state.get("prompt_versions", [])),
            "modelRoutes": repo.clone(repo.state.get("model_route_versions", [])),
            "ocrProfiles": repo.clone(repo.state.get("ocr_profile_versions", [])),
        },
        request,
    )


@router.post("/fde/capability-bundles")
def fde_create_capability_bundle(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:capability-bundle:manage")
        if role_error:
            return role_error
        bundle = {
            "id": body.get("id") or f"BUNDLE-{uuid4().hex[:8].upper()}",
            "name": body.get("name") or "FDE 草稿能力组合",
            "businessPackId": body.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
            "agentVersionId": body.get("agentVersionId"),
            "promptVersionId": body.get("promptVersionId"),
            "modelRouteVersionId": body.get("modelRouteVersionId"),
            "ruleSetVersion": body.get("ruleSetVersion"),
            "knowledgeBaseVersion": body.get("knowledgeBaseVersion"),
            "ocrProfileVersionId": body.get("ocrProfileVersionId"),
            "schemaVersion": body.get("schemaVersion") or "ReviewFindingDraftList@1.0.0",
            "riskLevel": body.get("riskLevel") or "medium",
            "status": "draft",
            "createdAt": server_time(),
        }
        repo.state["capability_bundles"].insert(0, bundle)
        audit_id = repo.add_audit("FDE 创建 Capability Bundle 草稿", "CapabilityBundle", bundle["id"])
        return ok({"bundle": bundle, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/fde/capability-bundles/{bundle_id}/diff")
def fde_capability_bundle_diff(request: Request, bundle_id: str, compareTo: str | None = None):
    _, role_error = fde_error_unless_allowed(request, "fde:business-pack:view")
    if role_error:
        return role_error
    bundle = repo.find_one("capability_bundles", bundle_id)
    if not bundle:
        return fail(errors.NOT_FOUND, request)
    baseline = repo.find_one("capability_bundles", compareTo) if compareTo else None
    if not baseline:
        baseline = next(
            (
                item
                for item in repo.state.get("capability_bundles", [])
                if item.get("id") != bundle_id and item.get("businessPackId") == bundle.get("businessPackId")
            ),
            None,
        )
    component_fields = [
        "agentVersionId",
        "promptVersionId",
        "modelRouteVersionId",
        "ruleSetVersion",
        "knowledgeBaseVersion",
        "ocrProfileVersionId",
        "schemaVersion",
        "riskLevel",
        "businessPackId",
    ]
    current = {field: bundle.get(field) for field in component_fields}
    previous = {field: (baseline or {}).get(field) for field in component_fields}
    diff = fde_record_diff(current, previous)
    return ok(
        {
            "bundleId": bundle_id,
            "compareTo": (baseline or {}).get("id"),
            "current": current,
            "baseline": previous,
            "diff": diff,
            "riskImpact": "high" if any(item["field"] in {"ruleSetVersion", "knowledgeBaseVersion", "schemaVersion"} for item in diff["changes"]) else bundle.get("riskLevel", "medium"),
        },
        request,
    )


@router.get("/fde/releases")
def fde_release_plans(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:release:view")
    if role_error:
        return role_error
    return ok(
        {
            "plans": repo.clone(repo.state.get("release_plans", [])),
            "approvals": repo.clone(repo.state.get("release_approvals", [])),
            "gates": repo.clone(repo.state.get("release_gates", [])),
        },
        request,
    )


@router.get("/fde/releases/{release_id}/impact")
def fde_release_impact(request: Request, release_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:release:view")
    if role_error:
        return role_error
    plan = repo.find_one("release_plans", release_id)
    if not plan:
        return fail(errors.NOT_FOUND, request)
    bundle = repo.find_one("capability_bundles", plan.get("capabilityBundleId"))
    target_scope = plan.get("targetScope") or {}
    project_ids = set(target_scope.get("projectIds") or [])
    business_pack_ids = set(target_scope.get("businessPackIds") or [])
    if not business_pack_ids and bundle:
        business_pack_ids.add(bundle.get("businessPackId"))
    projects = [
        repo.clone(project)
        for project in repo.state.get("projects", [])
        if (not project_ids or project.get("id") in project_ids)
        and (not business_pack_ids or project.get("businessPackId", DEFAULT_BUSINESS_PACK_ID) in business_pack_ids)
    ]
    related_runs = [
        repo.clone(run)
        for run in repo.state.get("review_runs", [])
        if not business_pack_ids or run.get("businessPackId", DEFAULT_BUSINESS_PACK_ID) in business_pack_ids
    ][:20]
    gates = [repo.clone(item) for item in repo.state.get("release_gates", []) if item.get("releasePlanId") == release_id]
    return ok(
        {
            "releasePlanId": release_id,
            "targetScope": target_scope,
            "bundle": repo.clone(bundle),
            "affectedProjectCount": len(projects),
            "affectedProjects": projects[:20],
            "affectedReviewRunCount": len(related_runs),
            "sampleReviewRuns": related_runs,
            "gateSummary": {
                "total": len(gates),
                "passed": len([item for item in gates if item.get("passed")]),
                "blocked": [item.get("message") for item in gates if not item.get("passed")],
            },
        },
        request,
    )


@router.post("/fde/releases")
def fde_create_release_plan(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:release:submit")
        if role_error:
            return role_error
        bundle_id = body.get("capabilityBundleId")
        bundle = repo.find_one("capability_bundles", bundle_id) if bundle_id else None
        if not bundle:
            return fail(errors.VALIDATION_ERROR, request, message="capabilityBundleId 无效。")
        risk_level = body.get("riskLevel") or bundle.get("riskLevel") or "medium"
        plan = {
            "id": body.get("id") or f"REL-{uuid4().hex[:8].upper()}",
            "releaseType": body.get("releaseType") or "capability_bundle",
            "capabilityBundleId": bundle_id,
            "riskLevel": risk_level,
            "status": "submitted",
            "targetScope": body.get("targetScope") or {"tenantIds": ["demo"], "businessPackIds": [bundle.get("businessPackId")], "projectIds": []},
            "changeSummary": body.get("changeSummary") or "FDE 发起能力组合发布申请。",
            "evaluationReportId": body.get("evaluationReportId"),
            "rollbackPlanId": body.get("rollbackPlanId"),
            "blockingReasons": [],
            "createdByRole": effective_role_for_request(request)[0],
            "createdAt": server_time(),
        }
        repo.state["release_plans"].insert(0, plan)
        gates = fde_release_gate_results(plan)
        fde_persist_release_gates(plan, gates)
        blocking_reasons = [item["message"] for item in gates if not item["passed"]]
        plan["blockingReasons"] = blocking_reasons
        if blocking_reasons:
            plan["status"] = "blocked_by_gate"
        audit_id = repo.add_audit("FDE 创建发布计划", "ReleasePlan", plan["id"])
        return ok({"plan": plan, "gates": gates, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/fde/releases/{release_id}/submit")
def fde_submit_release_plan(
    request: Request,
    release_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:release:submit")
        if role_error:
            return role_error
        plan = repo.find_one("release_plans", release_id)
        if not plan:
            return fail(errors.NOT_FOUND, request)
        if body.get("evaluationReportId"):
            plan["evaluationReportId"] = body["evaluationReportId"]
        if body.get("rollbackPlanId"):
            plan["rollbackPlanId"] = body["rollbackPlanId"]
        gates = fde_release_gate_results(plan)
        fde_persist_release_gates(plan, gates)
        blocking = [item["message"] for item in gates if not item["passed"]]
        plan["blockingReasons"] = blocking
        plan["status"] = "submitted" if not blocking else "blocked_by_gate"
        plan["submittedAt"] = server_time()
        audit_id = repo.add_audit("FDE 提交发布门禁", "ReleasePlan", release_id)
        return ok({"plan": repo.clone(plan), "gates": gates, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"releaseId": release_id, "body": body})


@router.post("/fde/releases/{release_id}/approve")
def fde_approve_release_plan(
    request: Request,
    release_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, identity_error = effective_role_for_request(request)
        if identity_error:
            return identity_error
        if role != "admin":
            return fail(errors.FORBIDDEN, request, message="高风险 AI 发布必须由非 FDE 管理员/AI 负责人审批。")
        plan = repo.find_one("release_plans", release_id)
        if not plan:
            return fail(errors.NOT_FOUND, request)
        approval = {
            "id": body.get("id") or f"RAPP-{uuid4().hex[:8].upper()}",
            "releasePlanId": release_id,
            "role": body.get("approvalRole") or "admin",
            "status": body.get("status") or "approved",
            "comment": body.get("comment") or "管理员批准高风险 AI 发布进入灰度。",
            "approvedByRole": role,
            "approvedAt": server_time(),
        }
        repo.state["release_approvals"].insert(0, approval)
        gates = fde_release_gate_results(plan)
        fde_persist_release_gates(plan, gates)
        blocking = [item["message"] for item in gates if not item["passed"]]
        plan["blockingReasons"] = blocking
        plan["status"] = "submitted" if not blocking else "blocked_by_gate"
        plan["approvedAt"] = approval["approvedAt"] if not blocking else plan.get("approvedAt")
        audit_id = repo.add_audit("管理员审批 FDE 发布计划", "ReleasePlan", release_id)
        return ok({"plan": repo.clone(plan), "approval": approval, "gates": gates, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"releaseId": release_id, "body": body})


@router.post("/fde/releases/{release_id}/start-shadow")
def fde_start_shadow_release(
    request: Request,
    release_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:release:shadow")
        if role_error:
            return role_error
        plan = repo.find_one("release_plans", release_id)
        if not plan:
            return fail(errors.NOT_FOUND, request)
        gates = fde_release_gate_results(plan)
        fde_persist_release_gates(plan, gates)
        blocking = [item["message"] for item in gates if not item["passed"]]
        if blocking:
            plan["status"] = "blocked_by_gate"
            plan["blockingReasons"] = blocking
            return ok({"plan": repo.clone(plan), "gates": gates, "auditLogId": None}, request)
        plan["status"] = "shadow_running"
        plan["shadowStartedAt"] = server_time()
        plan["shadowSampleRate"] = body.get("sampleRate", 0.0)
        audit_id = repo.add_audit("FDE 启动 Shadow Run", "ReleasePlan", release_id)
        return ok({"plan": repo.clone(plan), "gates": gates, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"releaseId": release_id, "body": body})


@router.post("/fde/releases/{release_id}/mark-shadow-passed")
def fde_mark_shadow_passed(
    request: Request,
    release_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:release:shadow")
        if role_error:
            return role_error
        plan = repo.find_one("release_plans", release_id)
        if not plan:
            return fail(errors.NOT_FOUND, request)
        if plan.get("status") not in {"shadow_running", "shadow_passed"}:
            return fail(errors.VALIDATION_ERROR, request, message="只有 shadow_running 状态可以标记 Shadow 通过。")
        plan["status"] = "shadow_passed"
        plan["shadowPassedAt"] = server_time()
        plan["shadowMetrics"] = body.get("metrics") or {"sampleRate": plan.get("shadowSampleRate", 0), "failedRuns": 0}
        audit_id = repo.add_audit("FDE 标记 Shadow Run 通过", "ReleasePlan", release_id)
        return ok({"plan": repo.clone(plan), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"releaseId": release_id, "body": body})


@router.post("/fde/releases/{release_id}/request-canary")
def fde_request_canary_release(
    request: Request,
    release_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:release:canary")
        if role_error:
            return role_error
        plan = repo.find_one("release_plans", release_id)
        if not plan:
            return fail(errors.NOT_FOUND, request)
        gates = fde_release_gate_results(plan)
        fde_persist_release_gates(plan, gates)
        blocking = [item["message"] for item in gates if not item["passed"]]
        if blocking:
            plan["status"] = "blocked_by_gate"
            plan["blockingReasons"] = blocking
            return ok({"plan": repo.clone(plan), "gates": gates, "auditLogId": None}, request)
        if plan.get("status") not in {"shadow_running", "shadow_passed"}:
            return fail(errors.VALIDATION_ERROR, request, message="当前发布状态不允许申请 canary。")
        plan["status"] = "canary_requested"
        plan["canaryPolicy"] = {
            "tenantPercent": body.get("tenantPercent", 10),
            "durationHours": body.get("durationHours", 24),
            "rollbackOnFailureRate": body.get("rollbackOnFailureRate", 0.02),
        }
        plan["canaryRequestedAt"] = server_time()
        audit_id = repo.add_audit("FDE 申请 Canary 发布", "ReleasePlan", release_id)
        return ok({"plan": repo.clone(plan), "gates": gates, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"releaseId": release_id, "body": body})


@router.post("/fde/releases/{release_id}/approve-production")
def fde_approve_production_release(
    request: Request,
    release_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, identity_error = effective_role_for_request(request)
        if identity_error:
            return identity_error
        if role != "admin":
            return fail(errors.FORBIDDEN, request, message="生产发布必须由非 FDE 管理员/AI 负责人审批。")
        plan = repo.find_one("release_plans", release_id)
        if not plan:
            return fail(errors.NOT_FOUND, request)
        gates = fde_release_gate_results(plan)
        fde_persist_release_gates(plan, gates)
        blocking = [item["message"] for item in gates if not item["passed"]]
        if blocking:
            plan["status"] = "blocked_by_gate"
            plan["blockingReasons"] = blocking
            return ok({"plan": repo.clone(plan), "gates": gates, "auditLogId": None}, request)
        if plan.get("status") not in {"canary_requested", "canary_running", "canary_passed", "shadow_passed", "submitted"}:
            return fail(errors.VALIDATION_ERROR, request, message="当前发布状态不允许批准生产。")
        plan["status"] = body.get("targetStatus") or "production_approved"
        plan["productionApprovedAt"] = server_time()
        plan["productionApprovedByRole"] = role
        plan["productionApprovalComment"] = body.get("comment") or "管理员批准进入生产。"
        audit_id = repo.add_audit("管理员批准 FDE 生产发布", "ReleasePlan", release_id)
        return ok({"plan": repo.clone(plan), "gates": gates, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"releaseId": release_id, "body": body})


@router.post("/fde/releases/{release_id}/rollback")
def fde_rollback_release(
    request: Request,
    release_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:release:rollback")
        if role_error:
            return role_error
        plan = repo.find_one("release_plans", release_id)
        if not plan:
            return fail(errors.NOT_FOUND, request)
        plan["status"] = "rollback_requested"
        plan["rollbackReason"] = body.get("reason") or "FDE 请求回滚能力组合。"
        plan["rollbackRequestedAt"] = server_time()
        audit_id = repo.add_audit("FDE 请求发布回滚", "ReleasePlan", release_id)
        return ok({"plan": repo.clone(plan), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"releaseId": release_id, "body": body})


@router.post("/fde/business-packs/validate-all")
def fde_validate_business_packs(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:business-pack:validate")
    if role_error:
        return role_error
    return ok(validate_all_business_packs(), request)


@router.get("/fde/business-packs/{pack_id}/diff")
def fde_business_pack_diff(request: Request, pack_id: str, compareTo: str | None = None, tenantId: str | None = None):
    _, role_error = fde_error_unless_allowed(request, "fde:business-pack:view")
    if role_error:
        return role_error
    validation_result = fde_business_pack_validation_result(pack_id)
    if not validation_result:
        return fail(errors.NOT_FOUND, request)
    current_summary = validation_result["summary"]
    baseline_summary: dict[str, Any] = {}
    if compareTo:
        compare_result = fde_business_pack_validation_result(compareTo)
        if not compare_result:
            return fail(errors.NOT_FOUND, request, message="compareTo 业务包不存在。")
        baseline_summary = compare_result["summary"]
    else:
        installation = next(
            (
                item
                for item in repo.state.get("business_pack_installations", [])
                if item.get("businessPackId") == pack_id and (not tenantId or item.get("tenantId") == tenantId)
            ),
            None,
        )
        if installation:
            baseline_summary = {
                "id": installation.get("businessPackId"),
                "version": installation.get("businessPackVersion"),
                "tenantId": installation.get("tenantId"),
                "status": installation.get("status"),
                "snapshotHash": installation.get("businessPackSnapshotHash"),
            }
    diff = fde_record_diff(current_summary, baseline_summary)
    return ok(
        {
            "businessPackId": pack_id,
            "compareTo": compareTo or baseline_summary.get("version"),
            "tenantId": tenantId,
            "current": current_summary,
            "baseline": baseline_summary,
            "validation": validation_result["validation"],
            "diff": diff,
            "requiresMigrationReview": any(item["field"] in {"roles", "nodes", "materials", "workflow", "rules"} for item in diff["changes"]),
        },
        request,
    )


@router.post("/fde/business-packs/{pack_id}/install")
def fde_install_business_pack(
    request: Request,
    pack_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:business-pack:install")
        if role_error:
            return role_error
        validation_result = fde_business_pack_validation_result(pack_id)
        if not validation_result:
            return fail(errors.NOT_FOUND, request)
        tenant_id = body.get("tenantId") or "demo"
        dry_run = bool(body.get("dryRun", True))
        summary = validation_result["summary"]
        validation = validation_result["validation"]
        status = "dry_run_passed" if dry_run and validation.get("ok") else "production" if validation.get("ok") else "validation_failed"
        installation = {
            "id": body.get("id") or f"BPINST-{uuid4().hex[:8].upper()}",
            "businessPackId": pack_id,
            "businessPackVersion": summary["version"],
            "tenantId": tenant_id,
            "status": status,
            "installedByRole": effective_role_for_request(request)[0],
            "installedAt": server_time(),
            "rollbackToVersion": body.get("rollbackToVersion"),
            "validationStatus": "passed" if validation.get("ok") else "failed",
            "dryRun": dry_run,
        }
        repo.state["business_pack_installations"].insert(0, installation)
        audit_id = repo.add_audit("FDE 安装业务包", "BusinessPackInstallation", installation["id"])
        return ok({"installation": installation, "validation": validation, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"packId": pack_id, "body": body})


@router.post("/fde/business-packs/{pack_id}/upgrade")
def fde_upgrade_business_pack(
    request: Request,
    pack_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:business-pack:install")
        if role_error:
            return role_error
        validation_result = fde_business_pack_validation_result(pack_id)
        if not validation_result:
            return fail(errors.NOT_FOUND, request)
        tenant_id = body.get("tenantId") or "demo"
        current = next(
            (
                item
                for item in repo.state.get("business_pack_installations", [])
                if item.get("businessPackId") == pack_id and item.get("tenantId") == tenant_id
            ),
            None,
        )
        summary = validation_result["summary"]
        upgrade = {
            "id": body.get("id") or f"BPUPG-{uuid4().hex[:8].upper()}",
            "businessPackId": pack_id,
            "businessPackVersion": summary["version"],
            "tenantId": tenant_id,
            "status": "upgrade_dry_run_passed" if body.get("dryRun", True) else "upgrade_planned",
            "previousVersion": (current or {}).get("businessPackVersion"),
            "installedByRole": effective_role_for_request(request)[0],
            "installedAt": server_time(),
            "validationStatus": "passed" if validation_result["validation"].get("ok") else "failed",
            "dryRun": bool(body.get("dryRun", True)),
        }
        repo.state["business_pack_installations"].insert(0, upgrade)
        audit_id = repo.add_audit("FDE 升级业务包", "BusinessPackInstallation", upgrade["id"])
        return ok({"installation": upgrade, "validation": validation_result["validation"], "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"packId": pack_id, "body": body})


@router.post("/fde/business-packs/{pack_id}/rollback")
def fde_rollback_business_pack(
    request: Request,
    pack_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:business-pack:install")
        if role_error:
            return role_error
        tenant_id = body.get("tenantId") or "demo"
        installation = {
            "id": body.get("id") or f"BPROLL-{uuid4().hex[:8].upper()}",
            "businessPackId": pack_id,
            "businessPackVersion": body.get("targetVersion") or "previous",
            "tenantId": tenant_id,
            "status": "rollback_planned",
            "rollbackReason": body.get("reason") or "FDE 请求业务包回滚。",
            "installedByRole": effective_role_for_request(request)[0],
            "installedAt": server_time(),
            "validationStatus": "pending",
            "dryRun": bool(body.get("dryRun", True)),
        }
        repo.state["business_pack_installations"].insert(0, installation)
        audit_id = repo.add_audit("FDE 回滚业务包", "BusinessPackInstallation", installation["id"])
        return ok({"installation": installation, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"packId": pack_id, "body": body})


def fde_ocr_quality_snapshot() -> dict[str, Any]:
    documents = repo.state.get("documents", [])
    fields = repo.state.get("extracted_fields", [])
    jobs = repo.state.get("ocr_jobs", [])
    results = repo.state.get("ocr_parse_results", [])
    corrections = repo.state.get("ocr_corrections", [])
    eval_runs = repo.state.get("ocr_eval_runs", [])
    low_confidence = [item for item in fields if float(item.get("confidence") or 0) < 0.85]
    result_diagnostics = [
        diagnostic
        for result in results
        for diagnostic in result.get("diagnostics", [])
        if isinstance(diagnostic, dict) or diagnostic
    ]
    diagnostic_table_failures = [
        item
        for item in result_diagnostics
        if "TABLE" in str((item or {}).get("code") if isinstance(item, dict) else item).upper()
    ]
    diagnostic_seal_failures = [
        item
        for item in result_diagnostics
        if "SEAL" in str((item or {}).get("code") if isinstance(item, dict) else item).upper()
    ]
    engine_failures = [
        item
        for item in result_diagnostics
        if "ENGINE" in str((item or {}).get("code") if isinstance(item, dict) else item).upper()
        or "FAILED" in str((item or {}).get("code") if isinstance(item, dict) else item).upper()
    ]
    field_failures = fde_ocr_field_failures(results, fields)
    table_failures = [*diagnostic_table_failures, *fde_ocr_table_failures(results)]
    seal_failures = [*diagnostic_seal_failures, *fde_ocr_seal_failures(results)]
    quality_reason_counts = fde_ocr_quality_reason_counts(results)
    field_level = fde_ocr_field_level(results, fields, corrections)
    evidence_level = fde_ocr_evidence_level(results)
    table_level = fde_ocr_table_level(results)
    seal_level = fde_ocr_seal_level(results)
    success_documents = len([item for item in documents if item.get("currentOcrStatus") == "已识别"])
    failed_documents = len([item for item in documents if item.get("currentOcrStatus") == "识别失败"])
    success_results = len([item for item in results if item.get("status") == "success"])
    failed_results = len([item for item in results if item.get("status") != "success"])
    cache_metrics = fde_ocr_cache_metrics(results, jobs)
    runtime_doctor_report = fde_ocr_runtime_doctor_report()
    return {
        "fileLevel": {
            "total": len(documents),
            "success": success_documents,
            "failed": failed_documents,
            "parseSuccessRate": round(success_results / (len(results) or 1), 4),
        },
        "fieldLevel": field_level,
        "evidenceLevel": evidence_level,
        "tableLevel": table_level,
        "sealLevel": seal_level,
        "jobLevel": {
            "total": len(jobs),
            "success": success_results,
            "failed": failed_results,
            "running": len([item for item in jobs if item.get("status") in {"queued", "running"}]),
        },
        "lowConfidenceFields": repo.clone(low_confidence[:20]),
        "jobs": repo.clone(jobs[:20]),
        "parseResults": repo.clone(results[:20]),
        "corrections": repo.clone(corrections[:20]),
        "evalRuns": repo.clone(eval_runs[:20]),
        "cacheMetrics": cache_metrics,
        "qualityReasonCounts": quality_reason_counts,
        "runtimeDoctor": fde_ocr_runtime_doctor_snapshot(runtime_doctor_report),
        "ocr100Scorecard": fde_ocr_100_scorecard_snapshot(results, eval_runs, runtime_doctor_report),
        "failurePools": {
            "fieldFailures": repo.clone(field_failures[:20]),
            "tableFailures": repo.clone(table_failures[:20]),
            "sealFailures": repo.clone(seal_failures[:20]),
            "engineFailures": repo.clone(engine_failures[:20]),
        },
    }


def fde_ocr_field_failures(results: list[dict[str, Any]], extracted_fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        parse_result_id = result.get("parseResultId") or result.get("id")
        for diagnostic_item in result.get("diagnostics", []):
            code = str((diagnostic_item or {}).get("code") if isinstance(diagnostic_item, dict) else diagnostic_item)
            upper_code = code.upper()
            if "FIELD" in upper_code or "CONFLICT" in upper_code:
                payload = repo.clone(diagnostic_item) if isinstance(diagnostic_item, dict) else {"code": code}
                payload["parseResultId"] = parse_result_id
                payload.setdefault("source", "diagnostic")
                failures.append(payload)
        for field in result.get("fields", []):
            if not isinstance(field, dict):
                continue
            flags = [str(flag) for flag in field.get("qualityFlags") or []]
            confidence = float(field.get("confidence") or 0)
            if flags or confidence < 0.75:
                if "field_value_conflict" in flags:
                    code = "FIELD_VALUE_CONFLICT"
                elif "field_evidence_missing" in flags:
                    code = "FIELD_EVIDENCE_MISSING"
                else:
                    code = "FIELD_LOW_CONFIDENCE"
                failures.append(
                    {
                        "code": code,
                        "source": "field",
                        "parseResultId": parse_result_id,
                        "fieldCode": field.get("fieldCode") or field.get("fieldName"),
                        "fieldName": field.get("fieldName"),
                        "fieldValue": field.get("fieldValue"),
                        "confidence": field.get("confidence"),
                        "qualityFlags": flags,
                    }
                )
        failures.extend(
            fde_missing_evidence_items(
                result,
                target_type="field",
                code="FIELD_EVIDENCE_MISSING",
                parse_result_id=parse_result_id,
            )
        )
    for field in extracted_fields:
        confidence = float(field.get("confidence") or 0)
        if confidence < 0.75:
            failures.append(
                {
                    "code": "FIELD_LOW_CONFIDENCE",
                    "source": "extracted_field",
                    "fieldId": field.get("id"),
                    "documentVersionId": field.get("documentVersionId"),
                    "fieldCode": field.get("fieldCode") or field.get("fieldName"),
                    "fieldName": field.get("fieldName"),
                    "fieldValue": field.get("fieldValue"),
                    "confidence": field.get("confidence"),
                }
            )
    return failures


def fde_ocr_table_failures(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        parse_result_id = result.get("parseResultId") or result.get("id")
        for table in result.get("tables", []):
            if not isinstance(table, dict):
                continue
            flags = [str(flag) for flag in table.get("qualityFlags") or []]
            review_flags = [flag for flag in flags if ocr_quality_flag_requires_review(flag)]
            if not review_flags:
                continue
            failures.append(
                {
                    "code": "TABLE_EVIDENCE_MISSING" if "table_evidence_missing" in review_flags else "TABLE_REVIEW_REQUIRED",
                    "source": "table",
                    "parseResultId": parse_result_id,
                    "tableId": table.get("tableId"),
                    "businessSchema": table.get("businessSchema"),
                    "sourceEngine": table.get("sourceEngine"),
                    "structureConfidence": table.get("structureConfidence"),
                    "qualityFlags": review_flags,
                }
            )
        failures.extend(
            fde_missing_evidence_items(
                result,
                target_type="table",
                code="TABLE_EVIDENCE_MISSING",
                parse_result_id=parse_result_id,
            )
        )
    return dedupe_failure_pool(failures)


def fde_ocr_seal_failures(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        parse_result_id = result.get("parseResultId") or result.get("id")
        for seal in result.get("seals", []):
            if not isinstance(seal, dict):
                continue
            flags = [str(flag) for flag in seal.get("qualityFlags") or []]
            review_flags = [flag for flag in flags if ocr_quality_flag_requires_review(flag)]
            if not review_flags:
                continue
            failures.append(
                {
                    "code": "SEAL_EVIDENCE_MISSING" if "seal_evidence_missing" in review_flags else "SEAL_REVIEW_REQUIRED",
                    "source": "seal",
                    "parseResultId": parse_result_id,
                    "sealId": seal.get("sealId"),
                    "sealName": seal.get("sealName"),
                    "sealType": seal.get("sealType"),
                    "sourceEngine": seal.get("sourceEngine"),
                    "ocrConfidence": seal.get("ocrConfidence"),
                    "qualityFlags": review_flags,
                }
            )
        failures.extend(
            fde_missing_evidence_items(
                result,
                target_type="seal",
                code="SEAL_EVIDENCE_MISSING",
                parse_result_id=parse_result_id,
            )
        )
    return dedupe_failure_pool(failures)


def ocr_quality_flag_requires_review(flag: Any) -> bool:
    normalized = str(flag or "").lower()
    return any(
        token in normalized
        for token in ["missing", "requires", "review", "low_confidence", "conflict", "fallback", "failed", "timeout"]
    )


def fde_missing_evidence_items(
    result: dict[str, Any],
    *,
    target_type: str,
    code: str,
    parse_result_id: str | None,
) -> list[dict[str, Any]]:
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    items = []
    for item in quality.get("missingEvidence") or []:
        if not isinstance(item, dict) or item.get("targetType") != target_type:
            continue
        items.append(
            {
                **repo.clone(item),
                "code": code,
                "source": "quality.missingEvidence",
                "parseResultId": parse_result_id,
            }
        )
    return items


def dedupe_failure_pool(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for item in items:
        key = (
            item.get("code"),
            item.get("parseResultId"),
            item.get("targetType"),
            item.get("targetId"),
            item.get("tableId"),
            item.get("sealId"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def fde_ocr_quality_reason_counts(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for result in results:
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        for reason in quality.get("reasons") or []:
            key = str(reason)
            counts[key] = counts.get(key, 0) + 1
    return [{"reason": reason, "count": count} for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def fde_ocr_field_level(
    results: list[dict[str, Any]],
    extracted_fields: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
) -> dict[str, Any]:
    parse_fields = [
        field
        for result in results
        for field in result.get("fields", [])
        if isinstance(field, dict)
    ]
    source_counts: dict[str, int] = {}
    code_counts: dict[str, int] = {}
    flag_counts: dict[str, int] = {}
    missing_required_counts: dict[str, int] = {}
    missing_required_items: list[dict[str, Any]] = []
    low_confidence_parse_fields = []
    conflict_fields = []
    evidence_missing_fields = []
    confidence_values: list[float] = []
    for result in results:
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        for field_code in quality.get("missingFields") or []:
            key = str(field_code or "unknown")
            missing_required_counts[key] = missing_required_counts.get(key, 0) + 1
            missing_required_items.append(
                {
                    "fieldCode": key,
                    "parseResultId": result.get("parseResultId") or result.get("id"),
                    "profileId": result.get("profileId"),
                    "documentType": result.get("documentType"),
                }
            )
    for field in parse_fields:
        flags = [str(flag) for flag in field.get("qualityFlags") or []]
        source = str(field.get("sourceEngine") or field.get("source") or "unknown")
        code = str(field.get("fieldCode") or field.get("fieldName") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        code_counts[code] = code_counts.get(code, 0) + 1
        for flag in flags:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
        confidence = safe_float(field.get("confidence"))
        confidence_values.append(confidence)
        if confidence < 0.75:
            low_confidence_parse_fields.append(field)
        if any("conflict" in flag.lower() for flag in flags):
            conflict_fields.append(field)
        if any("evidence_missing" in flag.lower() or "missing_evidence" in flag.lower() for flag in flags):
            evidence_missing_fields.append(field)

    low_confidence_extracted = [item for item in extracted_fields if safe_float(item.get("confidence")) < 0.85]
    field_count = len(parse_fields)
    return {
        "total": len(extracted_fields),
        "lowConfidence": len(low_confidence_extracted),
        "manualCorrectionRate": round(len(corrections) / (len(extracted_fields) or 1), 4),
        "parseResultCount": len(results),
        "parseFieldCount": field_count,
        "lowConfidenceParseFieldCount": len(low_confidence_parse_fields),
        "conflictFieldCount": len(conflict_fields),
        "evidenceMissingFieldCount": len(evidence_missing_fields),
        "missingRequiredFieldCount": len(missing_required_items),
        "averageFieldConfidence": round(sum(confidence_values) / (len(confidence_values) or 1), 4),
        "missingRequiredFieldBreakdown": [
            {"fieldCode": code, "count": count}
            for code, count in sorted(missing_required_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "sampleMissingRequiredFields": repo.clone(missing_required_items[:10]),
        "sourceBreakdown": [
            {"source": source, "count": count}
            for source, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "fieldCodeBreakdown": [
            {"fieldCode": code, "count": count}
            for code, count in sorted(code_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "qualityFlagCounts": [
            {"flag": flag, "count": count}
            for flag, count in sorted(flag_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "sampleFields": repo.clone(parse_fields[:10]),
    }


def fde_ocr_table_level(results: list[dict[str, Any]]) -> dict[str, Any]:
    tables = [
        table
        for result in results
        for table in result.get("tables", [])
        if isinstance(table, dict)
    ]
    source_counts: dict[str, int] = {}
    flag_counts: dict[str, int] = {}
    missing_required_counts: dict[str, int] = {}
    missing_required_items: list[dict[str, Any]] = []
    formal_tables = []
    heuristic_tables = []
    review_required = []
    business_row_count = 0
    normalized_row_count = 0
    cell_count = 0
    confidence_values: list[float] = []
    for result in results:
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        for table_code in quality.get("missingTables") or []:
            key = str(table_code or "unknown")
            missing_required_counts[key] = missing_required_counts.get(key, 0) + 1
            missing_required_items.append(
                {
                    "tableCode": key,
                    "parseResultId": result.get("parseResultId") or result.get("id"),
                    "profileId": result.get("profileId"),
                    "documentType": result.get("documentType"),
                }
            )
    for table in tables:
        flags = [str(flag) for flag in table.get("qualityFlags") or []]
        source = str(table.get("sourceEngine") or table.get("source") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        for flag in flags:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
        try:
            confidence_values.append(float(table.get("structureConfidence") or table.get("confidence") or 0))
        except (TypeError, ValueError):
            confidence_values.append(0.0)
        if fde_table_is_heuristic(table):
            heuristic_tables.append(table)
        else:
            formal_tables.append(table)
        if any(ocr_quality_flag_requires_review(flag) for flag in flags):
            review_required.append(table)
        business_row_count += len([row for row in table.get("businessRows") or [] if isinstance(row, dict)])
        normalized_row_count += len([row for row in table.get("normalizedRows") or [] if isinstance(row, dict)])
        cell_count += len([cell for cell in table.get("cells") or [] if isinstance(cell, dict)])
    table_count = len(tables)
    return {
        "parseResultCount": len(results),
        "tableCount": table_count,
        "formalTableCount": len(formal_tables),
        "heuristicTableCount": len(heuristic_tables),
        "reviewRequiredCount": len(review_required),
        "missingRequiredTableCount": len(missing_required_items),
        "businessRowCount": business_row_count,
        "normalizedRowCount": normalized_row_count,
        "cellCount": cell_count,
        "averageTableConfidence": round(sum(confidence_values) / (len(confidence_values) or 1), 4),
        "formalTableRate": round(len(formal_tables) / (table_count or 1), 4),
        "heuristicTableRate": round(len(heuristic_tables) / (table_count or 1), 4),
        "reviewRequiredRate": round(len(review_required) / (table_count or 1), 4),
        "missingRequiredTableBreakdown": [
            {"tableCode": code, "count": count}
            for code, count in sorted(missing_required_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "sampleMissingRequiredTables": repo.clone(missing_required_items[:10]),
        "sourceBreakdown": [
            {"source": source, "count": count}
            for source, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "qualityFlagCounts": [
            {"flag": flag, "count": count}
            for flag, count in sorted(flag_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "sampleTables": repo.clone(tables[:10]),
    }


def fde_table_is_heuristic(table: dict[str, Any]) -> bool:
    source = str(table.get("sourceEngine") or "")
    flags = {str(flag) for flag in table.get("qualityFlags") or []}
    return source.startswith("heuristic_") or "heuristic_table_fallback" in flags


def fde_table_business_rows(table: dict[str, Any]) -> list[Any]:
    rows = table.get("businessRows") or table.get("normalizedRows") or []
    return rows if isinstance(rows, list) else []


def fde_seal_is_fragment_fusion(seal: dict[str, Any]) -> bool:
    source = str(seal.get("sourceEngine") or "")
    flags = {str(flag) for flag in seal.get("qualityFlags") or []}
    return source == "fragment_seal_text_fusion" or "fragment_seal_text" in flags


def fde_ocr_seal_level(results: list[dict[str, Any]]) -> dict[str, Any]:
    seals = [
        seal
        for result in results
        for seal in result.get("seals", [])
        if isinstance(seal, dict)
    ]
    source_counts: dict[str, int] = {}
    flag_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    readable_type_counts: dict[str, int] = {}
    matched_expected_counts: dict[str, int] = {}
    missing_expected_counts: dict[str, int] = {}
    missing_expected_items: list[dict[str, Any]] = []
    fragment_seals = []
    readable_seals = []
    visual_candidates = []
    review_required = []
    confidence_values: list[float] = []
    for result in results:
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        for seal_type in quality.get("matchedSealTypes") or []:
            key = str(seal_type or "unknown")
            matched_expected_counts[key] = matched_expected_counts.get(key, 0) + 1
        for seal_type in quality.get("missingExpectedSealTypes") or []:
            key = str(seal_type or "unknown")
            missing_expected_counts[key] = missing_expected_counts.get(key, 0) + 1
            missing_expected_items.append(
                {
                    "sealType": key,
                    "parseResultId": result.get("parseResultId") or result.get("id"),
                    "profileId": result.get("profileId"),
                    "documentType": result.get("documentType"),
                }
            )
    for seal in seals:
        flags = [str(flag) for flag in seal.get("qualityFlags") or []]
        source = str(seal.get("sourceEngine") or seal.get("source") or "unknown")
        seal_type = str(seal.get("sealType") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        type_counts[seal_type] = type_counts.get(seal_type, 0) + 1
        for flag in flags:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
        try:
            confidence_values.append(float(seal.get("ocrConfidence") or seal.get("visualConfidence") or 0))
        except (TypeError, ValueError):
            confidence_values.append(0.0)
        if "fragment_seal_text" in flags or source == "fragment_seal_text_fusion":
            fragment_seals.append(seal)
        if fde_seal_is_visual_candidate(seal):
            visual_candidates.append(seal)
        if fde_seal_text_is_readable(seal):
            readable_seals.append(seal)
            readable_type_counts[seal_type] = readable_type_counts.get(seal_type, 0) + 1
        if any(ocr_quality_flag_requires_review(flag) for flag in flags):
            review_required.append(seal)
    seal_count = len(seals)
    return {
        "parseResultCount": len(results),
        "sealCount": seal_count,
        "readableSealCount": len(readable_seals),
        "fragmentSealCount": len(fragment_seals),
        "visualCandidateCount": len(visual_candidates),
        "reviewRequiredCount": len(review_required),
        "missingExpectedSealTypeCount": len(missing_expected_items),
        "missingTextCount": len([seal for seal in visual_candidates if not fde_seal_text_is_readable(seal)]),
        "averageSealConfidence": round(sum(confidence_values) / (len(confidence_values) or 1), 4),
        "readableSealRate": round(len(readable_seals) / (seal_count or 1), 4),
        "fragmentSealRate": round(len(fragment_seals) / (seal_count or 1), 4),
        "visualCandidateReviewRate": round(len(review_required) / (len(visual_candidates) or 1), 4),
        "sealTypeBreakdown": [
            {"sealType": seal_type, "count": count}
            for seal_type, count in sorted(type_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "readableSealTypeBreakdown": [
            {"sealType": seal_type, "count": count}
            for seal_type, count in sorted(readable_type_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "matchedExpectedSealTypeBreakdown": [
            {"sealType": seal_type, "count": count}
            for seal_type, count in sorted(matched_expected_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "missingExpectedSealTypeBreakdown": [
            {"sealType": seal_type, "count": count}
            for seal_type, count in sorted(missing_expected_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "sampleMissingExpectedSealTypes": repo.clone(missing_expected_items[:10]),
        "sourceBreakdown": [
            {"source": source, "count": count}
            for source, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "qualityFlagCounts": [
            {"flag": flag, "count": count}
            for flag, count in sorted(flag_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "sampleSeals": repo.clone(seals[:10]),
    }


def fde_seal_is_visual_candidate(seal: dict[str, Any]) -> bool:
    flags = {str(flag) for flag in seal.get("qualityFlags") or []}
    seal_type = str(seal.get("sealType") or "")
    seal_name = str(seal.get("sealName") or "")
    return "visual_candidate_only" in flags or seal_type.startswith("visual_") or seal_name.startswith("视觉")


def fde_seal_text_is_readable(seal: dict[str, Any]) -> bool:
    if fde_seal_is_visual_candidate(seal):
        return False
    seal_name = str(seal.get("sealName") or "").strip()
    if not seal_name:
        return False
    try:
        confidence = float(seal.get("ocrConfidence") or 0)
    except (TypeError, ValueError):
        return False
    return confidence >= 0.65


def fde_ocr_evidence_level(results: list[dict[str, Any]]) -> dict[str, Any]:
    scores: list[float] = []
    missing_items: list[dict[str, Any]] = []
    by_type = {"field": 0, "table": 0, "seal": 0, "unknown": 0}
    for result in results:
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        if "evidenceCompleteness" in quality:
            try:
                scores.append(float(quality.get("evidenceCompleteness") or 0))
            except (TypeError, ValueError):
                scores.append(0.0)
        missing_evidence = [item for item in quality.get("missingEvidence") or [] if isinstance(item, dict)]
        for item in missing_evidence:
            target_type = str(item.get("targetType") or "unknown")
            if target_type not in by_type:
                target_type = "unknown"
            by_type[target_type] += 1
            missing_items.append(
                {
                    **repo.clone(item),
                    "parseResultId": result.get("parseResultId") or result.get("id"),
                    "profileId": result.get("profileId"),
                    "documentType": result.get("documentType"),
                }
            )
    return {
        "parseResultCount": len(results),
        "scoredResultCount": len(scores),
        "averageEvidenceCompleteness": round(sum(scores) / (len(scores) or 1), 4),
        "missingEvidence": len(missing_items),
        "fieldEvidenceMissing": by_type["field"],
        "tableEvidenceMissing": by_type["table"],
        "sealEvidenceMissing": by_type["seal"],
        "unknownEvidenceMissing": by_type["unknown"],
        "missingEvidenceItems": repo.clone(missing_items[:20]),
    }


def fde_ocr_cache_metrics(results: list[dict[str, Any]], jobs: list[dict[str, Any]]) -> dict[str, Any]:
    sources = results if results else jobs
    engine_runs = [
        run
        for source in sources
        for run in source.get("engineRuns", [])
        if isinstance(run, dict)
    ]
    total_runs = len(engine_runs)
    engine_cache_hits = len([run for run in engine_runs if bool(run.get("engineCacheHit"))])
    variant_cache_hits = len([run for run in engine_runs if bool(run.get("variantCacheHit"))])
    result_cache_hits = len([run for run in engine_runs if bool(run.get("resultCacheHit")) or run.get("engine") == "ocr_result_cache"])
    total_duration = sum(safe_int(run.get("durationMs")) for run in engine_runs)
    by_engine: dict[str, dict[str, Any]] = {}
    for run in engine_runs:
        engine = str(run.get("engine") or "unknown")
        item = by_engine.setdefault(
            engine,
            {
                "engine": engine,
                "runCount": 0,
                "engineCacheHits": 0,
                "variantCacheHits": 0,
                "failures": 0,
                "totalDurationMs": 0,
                "averageDurationMs": 0,
            },
        )
        item["runCount"] += 1
        item["engineCacheHits"] += 1 if bool(run.get("engineCacheHit")) else 0
        item["variantCacheHits"] += 1 if bool(run.get("variantCacheHit")) else 0
        item["failures"] += 1 if str(run.get("status") or "") == "failed" else 0
        item["totalDurationMs"] += safe_int(run.get("durationMs"))
    for item in by_engine.values():
        item["averageDurationMs"] = round(item["totalDurationMs"] / (item["runCount"] or 1), 2)
        item["engineCacheHitRate"] = round(item["engineCacheHits"] / (item["runCount"] or 1), 4)
    slow_engines = sorted(by_engine.values(), key=lambda item: item["totalDurationMs"], reverse=True)[:8]
    return {
        "engineRunCount": total_runs,
        "engineCacheHits": engine_cache_hits,
        "engineCacheHitRate": round(engine_cache_hits / (total_runs or 1), 4),
        "variantCacheHits": variant_cache_hits,
        "variantCacheHitRate": round(variant_cache_hits / (total_runs or 1), 4),
        "resultCacheHits": result_cache_hits,
        "totalDurationMs": total_duration,
        "averageDurationMs": round(total_duration / (total_runs or 1), 2),
        "slowEngines": repo.clone(slow_engines),
    }


def safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def fde_ocr_runtime_doctor_report() -> dict[str, Any]:
    client = OcrClient()
    if not client.enabled:
        return {
            "schemaVersion": "aicheck-ocr-runtime-doctor-unavailable-v1",
            "ok": False,
            "summary": {"pass": 0, "warn": 1, "fail": 0, "total": 1},
            "checks": [
                {
                    "name": "ocr.base-url",
                    "status": "warn",
                    "message": "AICHECK_OCR_BASE_URL is not configured for API service.",
                    "fix": "Set AICHECK_OCR_BASE_URL so FDE can read OCR runtime doctor.",
                }
            ],
        }
    try:
        return client.runtime_doctor()
    except (IntegrationServiceError, RuntimeError) as exc:
        return {
            "schemaVersion": "aicheck-ocr-runtime-doctor-error-v1",
            "ok": False,
            "summary": {"pass": 0, "warn": 0, "fail": 1, "total": 1},
            "checks": [
                {
                    "name": "ocr.runtime-doctor",
                    "status": "fail",
                    "message": f"OCR runtime doctor is unavailable: {exc.__class__.__name__}",
                    "fix": "Check ocr-service network, /internal/ocr/doctor, and AICHECK_OCR_BASE_URL.",
                }
            ],
        }


def fde_ocr_runtime_doctor_snapshot(report: dict[str, Any] | None = None) -> dict[str, Any]:
    report = report or fde_ocr_runtime_doctor_report()
    checks = [item for item in report.get("checks") or [] if isinstance(item, dict)]
    top_issues = [item for item in checks if item.get("status") in {"fail", "warn"}][:8]
    return {
        "status": "ready" if report.get("ok") else "attention",
        "ok": bool(report.get("ok")),
        "summary": report.get("summary") or {},
        "topIssues": repo.clone(top_issues),
        "subprocessPython": report.get("subprocessPython"),
        "schemaVersion": report.get("schemaVersion"),
    }


def fde_ocr_100_scorecard_snapshot(
    results: list[dict[str, Any]],
    eval_runs: list[dict[str, Any]],
    runtime_doctor_report: dict[str, Any],
) -> dict[str, Any]:
    latest_eval_run = next(iter(eval_runs), {})
    evaluation_report = fde_ocr_100_evaluation_report_from_run(latest_eval_run)
    return build_ocr_100_scorecard(
        evaluation_report=evaluation_report,
        runtime_doctor=runtime_doctor_report,
        sample_summaries=fde_ocr_sample_summaries(results),
    )


def fde_ocr_100_evaluation_report_from_run(run: dict[str, Any]) -> dict[str, Any]:
    report = repo.clone(run.get("evaluationReport") or {}) if isinstance(run, dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    if not report:
        return {
            "ok": False,
            "summary": {"cases": 0, "passed": 0, "failed": 0, "averageScore": 0},
            "metrics": {},
            "findingCounts": {},
            "thresholdFailures": [],
            "scenarios": {},
            "cases": [],
        }
    cases = []
    for item in run.get("caseDiagnostics") or []:
        if isinstance(item, dict):
            cases.append(
                {
                    "caseId": item.get("caseId"),
                    "scenario": item.get("scenario"),
                    "score": item.get("score"),
                    "passed": item.get("passed"),
                    "findings": item.get("findings") or [],
                    "bootstrapGenerated": item.get("bootstrapGenerated"),
                    "fixtureDerived": item.get("fixtureDerived"),
                    "collectionStatus": item.get("collectionStatus"),
                }
            )
    return {
        **report,
        "summary": {
            "cases": summary.get("cases") or run.get("caseCount") or len(cases),
            "passed": summary.get("passed") or 0,
            "failed": summary.get("failed") or 0,
            "averageScore": summary.get("averageScore") or 0,
        },
        "scenarios": repo.clone(run.get("scenarioMetrics") or {}),
        "cases": cases,
    }


def fde_ocr_sample_summaries(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for result in results[:10]:
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        tables = [item for item in result.get("tables") or [] if isinstance(item, dict)]
        seals = [item for item in result.get("seals") or [] if isinstance(item, dict)]
        summaries.append(
            {
                "parseResultId": result.get("parseResultId") or result.get("id"),
                "profileId": result.get("profileId"),
                "gatePassed": result.get("status") == "success" and quality.get("status") == "auto_usable",
                "qualityStatus": quality.get("status"),
                "fields": len([item for item in result.get("fields") or [] if isinstance(item, dict)]),
                "formalTables": len([item for item in tables if not fde_table_is_heuristic(item)]),
                "businessRows": sum(len(fde_table_business_rows(item)) for item in tables),
                "readableSeals": len([item for item in seals if str(item.get("sealName") or "").strip()]),
                "fragmentSeals": len([item for item in seals if fde_seal_is_fragment_fusion(item)]),
                "missingExpectedSealTypeCount": len(quality.get("missingExpectedSealTypes") or []),
                "evidenceCompleteness": quality.get("evidenceCompleteness"),
            }
        )
    return summaries


def fde_build_ocr_evaluation_report(body: dict[str, Any]) -> dict[str, Any]:
    cases = body.get("cases") if isinstance(body.get("cases"), list) else None
    thresholds = body.get("thresholds") if isinstance(body.get("thresholds"), dict) else None
    if cases is None:
        cases = fde_ocr_evaluation_cases_from_results(str(body.get("profileId") or "all"))
    if not cases:
        cases = [
            {
                "caseId": "ocr-empty-eval",
                "scenario": "quality_gate_profile",
                "minScore": 0,
                "result": {"parseResultId": "empty", "status": "failed", "fields": [], "tables": [], "seals": [], "quality": {"status": "failed", "reasons": ["NO_OCR_RESULTS"]}},
                "expected": {"qualityStatus": "failed", "qualityReasons": ["NO_OCR_RESULTS"]},
            }
        ]
    return evaluate_cases(cases, thresholds=thresholds)


def fde_ocr_evaluation_cases_from_results(profile_id: str) -> list[dict[str, Any]]:
    results = [
        item
        for item in repo.state.get("ocr_parse_results", [])
        if profile_id in {"", "all"} or str(item.get("profileId") or "") == profile_id
    ]
    if not results and profile_id not in {"", "all"}:
        results = list(repo.state.get("ocr_parse_results", []))
    cases: list[dict[str, Any]] = []
    for result in results[:20]:
        parse_id = str(result.get("parseResultId") or result.get("id") or "ocr-result")
        if result.get("fields"):
            cases.append(
                {
                    "caseId": f"{parse_id}-fields",
                    "scenario": "field_extraction_profile",
                    "profileId": result.get("profileId"),
                    "documentType": result.get("documentType"),
                    "result": result,
                    "expected": {"fields": expected_fields_from_result(result)},
                    "minScore": 0.9,
                }
            )
        if result.get("tables"):
            cases.append(
                {
                    "caseId": f"{parse_id}-tables",
                    "scenario": "table_structure_profile",
                    "profileId": result.get("profileId"),
                    "documentType": result.get("documentType"),
                    "result": result,
                    "expected": {"tables": expected_tables_from_result(result)},
                    "minScore": 0.9,
                }
            )
        if result.get("seals"):
            cases.append(
                {
                    "caseId": f"{parse_id}-seals",
                    "scenario": "seal_text_profile",
                    "profileId": result.get("profileId"),
                    "documentType": result.get("documentType"),
                    "result": result,
                    "expected": {"seals": expected_seals_from_result(result)},
                    "minScore": 0.9,
                }
            )
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        if quality.get("status") or quality.get("reasons"):
            cases.append(
                {
                    "caseId": f"{parse_id}-quality",
                    "scenario": "quality_gate_profile",
                    "profileId": result.get("profileId"),
                    "documentType": result.get("documentType"),
                    "result": result,
                    "expected": {
                        "qualityStatus": quality.get("status"),
                        "qualityReasons": quality.get("reasons") or [],
                    },
                    "minScore": 0.9,
                }
            )
    return cases


def expected_fields_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    expected = []
    for field in result.get("fields") or []:
        if not isinstance(field, dict):
            continue
        field_code = str(field.get("fieldCode") or field.get("fieldName") or "")
        if not field_code:
            continue
        item = {"fieldCode": field_code, "value": field.get("fieldValue")}
        if field.get("bbox") or field.get("polygon"):
            item["bbox"] = field.get("bbox") or field.get("polygon")
            item["bboxIouThreshold"] = 0.5
        expected.append(item)
    return expected[:50]


def expected_tables_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    expected = []
    for table in result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        item: dict[str, Any] = {
            "businessSchema": table.get("businessSchema"),
            "tableId": table.get("tableId"),
            "minRows": int(table.get("rows") or 0),
            "minColumns": int(table.get("columns") or 0),
        }
        rows = table.get("businessRows") or table.get("normalizedRows") or []
        if rows and isinstance(rows[0], dict):
            item["requiredBusinessKeys"] = [key for key, value in rows[0].items() if value not in {None, ""}][:12]
        if table.get("bbox") or table.get("polygon"):
            item["bbox"] = table.get("bbox") or table.get("polygon")
            item["bboxIouThreshold"] = 0.5
        expected.append({key: value for key, value in item.items() if fde_expected_value_present(value)})
    return expected[:20]


def expected_seals_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    expected = []
    for seal in result.get("seals") or []:
        if not isinstance(seal, dict):
            continue
        seal_name = str(seal.get("sealName") or "")
        item: dict[str, Any] = {
            "sealType": seal.get("sealType"),
            "nameContains": seal_name,
            "minConfidence": min(float(seal.get("ocrConfidence") or seal.get("visualConfidence") or 0), 0.8),
        }
        if seal.get("bbox") or seal.get("polygon"):
            item["bbox"] = seal.get("bbox") or seal.get("polygon")
            item["bboxIouThreshold"] = 0.5
        expected.append({key: value for key, value in item.items() if fde_expected_value_present(value)})
    return expected[:20]


def fde_expected_value_present(value: Any) -> bool:
    return value is not None and value != "" and value != []


@router.get("/fde/ocr-quality")
def fde_ocr_quality(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
    if role_error:
        return role_error
    return ok(fde_ocr_quality_snapshot(), request)


@router.get("/fde/ocr-runs")
def fde_ocr_runs(
    request: Request,
    status: str | None = None,
    profileId: str | None = None,
    pageNo: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=100),
):
    _, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
    if role_error:
        return role_error
    items = repo.clone(repo.state.get("ocr_jobs", []))
    if status:
        items = [item for item in items if str(item.get("status") or "") == status]
    if profileId:
        items = [item for item in items if str(item.get("profileId") or "") == profileId]
    return ok(page(items, pageNo, pageSize), request)


@router.get("/fde/ocr-runs/{job_id}")
def fde_ocr_run_detail(request: Request, job_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
    if role_error:
        return role_error
    job = repo.find_one("ocr_jobs", job_id) or repo.find_one("ocr_jobs", job_id, id_field="jobId")
    if not job:
        return fail(errors.NOT_FOUND, request)
    result = None
    if job.get("parseResultId"):
        result = repo.find_one("ocr_parse_results", str(job["parseResultId"]), id_field="parseResultId")
    corrections = [
        item
        for item in repo.state.get("ocr_corrections", [])
        if item.get("documentVersionId") == job.get("documentVersionId")
    ]
    return ok({"job": repo.clone(job), "parseResult": repo.clone(result), "corrections": repo.clone(corrections)}, request)


@router.post("/fde/ocr-corrections")
def fde_create_ocr_correction(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
        if role_error:
            return role_error
        field_id = str(body.get("fieldId") or "")
        field = repo.find_one("extracted_fields", field_id)
        if field_id and not field:
            return fail(errors.NOT_FOUND, request)
        payload = {**body, "createdByRole": role or "fde"}
        correction = repo.create_ocr_correction(payload)
        audit_id = repo.add_audit("FDE OCR 字段纠错", "OcrCorrection", correction["id"])
        return ok({"correction": correction, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/fde/ocr-evaluation-runs")
def fde_create_ocr_evaluation_run(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, role_error = fde_error_unless_allowed(request, "fde:evaluation:run")
        if role_error:
            return role_error
        evaluation_report = fde_build_ocr_evaluation_report(body)
        case_diagnostics = [
            {
                "caseId": case.get("caseId"),
                "scenario": case.get("scenario"),
                "score": case.get("score"),
                "passed": case.get("passed"),
                "findings": case.get("findings") or [],
                "details": case.get("details") or {},
                "bootstrapGenerated": case.get("bootstrapGenerated"),
                "fixtureDerived": case.get("fixtureDerived"),
                "collectionStatus": case.get("collectionStatus"),
            }
            for case in evaluation_report.get("cases", [])
        ]
        evaluation_summary = compact_evaluation_report(evaluation_report)
        evaluation_case_count = int(
            (evaluation_report.get("summary") or {}).get("cases") or len(evaluation_report.get("cases") or [])
        )
        run = repo.create_ocr_eval_run(
            {
                **body,
                "createdByRole": role or "fde",
                "caseCount": evaluation_case_count,
                "evaluationReport": {
                    "ok": evaluation_report.get("ok"),
                    "summary": evaluation_report.get("summary"),
                    "metrics": evaluation_report.get("metrics"),
                    "findingCounts": evaluation_report.get("findingCounts") or {},
                    "thresholdFailures": evaluation_report.get("thresholdFailures") or [],
                },
                "evaluationSummary": evaluation_summary,
                "scenarioMetrics": evaluation_report.get("scenarios") or {},
                "caseDiagnostics": case_diagnostics,
            }
        )
        audit_id = repo.add_audit("FDE OCR 离线评测", "OcrEvaluationRun", run["id"])
        return ok({"run": run, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


def fde_ocr_annotation_tasks_source() -> list[dict[str, Any]]:
    tasks = repo.clone(repo.state.setdefault("ocr_annotation_tasks", []))
    if tasks:
        return tasks
    derived: list[dict[str, Any]] = []
    for result in repo.state.get("ocr_parse_results", []):
        if not isinstance(result, dict):
            continue
        parse_id = str(result.get("parseResultId") or result.get("id") or uuid4().hex)
        scenario = fde_ocr_annotation_scenario(result)
        expected = {
            "qualityStatus": (result.get("quality") or {}).get("status") or "needs_human_review",
            "fields": expected_fields_from_result(result),
            "tables": expected_tables_from_result(result),
            "seals": expected_seals_from_result(result),
        }
        derived.append(
            {
                "taskId": f"ANNO-{parse_id}",
                "caseId": f"real-{scenario}-{parse_id}",
                "scenario": scenario,
                "profileId": result.get("profileId") or "all",
                "documentType": result.get("documentType") or "unknown",
                "documentVersionId": result.get("documentVersionId"),
                "sourcePath": result.get("storageKey") or result.get("fileName"),
                "collectionStatus": "needs_labeling",
                "pageCount": len(result.get("pages") or []) or 1,
                "expectedTemplate": expected,
                "suggestedExpected": expected,
                "parseResultId": parse_id,
            }
        )
    return derived


def fde_ocr_annotation_scenario(result: dict[str, Any]) -> str:
    profile = str(result.get("profileId") or "")
    document_type = str(result.get("documentType") or "")
    if "piping" in profile or "table" in document_type:
        return "piping_table_profile"
    if "seal" in profile:
        return "seal_text_profile"
    if "quality_certificate" in profile or "quality_certificate" in document_type:
        return "quality_certificate_profile"
    return "evidence_profile"


def fde_ocr_annotation_task(task_id: str) -> dict[str, Any] | None:
    existing = next(
        (
            item
            for item in repo.state.setdefault("ocr_annotation_tasks", [])
            if str(item.get("taskId") or item.get("caseId") or "") == task_id
        ),
        None,
    )
    if existing:
        return existing
    derived = next(
        (
            item
            for item in fde_ocr_annotation_tasks_source()
            if str(item.get("taskId") or item.get("caseId") or "") == task_id
        ),
        None,
    )
    if derived:
        repo.state.setdefault("ocr_annotation_tasks", []).append(repo.clone(derived))
        return repo.state["ocr_annotation_tasks"][-1]
    return None


def fde_ocr_annotation_readiness(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return build_annotation_readiness_from_tasks(repo.clone(tasks), source="api:fde.ocr-annotation")


def fde_ocr_annotation_task_view(task: dict[str, Any]) -> dict[str, Any]:
    view = repo.clone(task)
    readiness = fde_ocr_annotation_readiness([task])
    status = (readiness.get("tasks") or [{}])[0]
    view["readinessBlockers"] = status.get("blockers") or []
    view["readyForEval"] = bool(status.get("readyForEval"))
    view["candidateCounts"] = fde_ocr_annotation_expected_counts(
        view.get("suggestedExpected") if isinstance(view.get("suggestedExpected"), dict) else {}
    )
    view["labelCounts"] = fde_ocr_annotation_expected_counts(
        view.get("labeledExpected") if isinstance(view.get("labeledExpected"), dict) else {}
    )
    view["previewUrl"] = view.get("previewUrl") or view.get("pagePreviewUrl") or fde_ocr_annotation_preview_url(view)
    view.setdefault("pageDimensions", fde_ocr_annotation_default_page_dimensions(view))
    return view


def fde_ocr_annotation_expected_counts(expected: dict[str, Any]) -> dict[str, int]:
    return {
        "fields": len([item for item in expected.get("fields") or [] if isinstance(item, dict)]),
        "tables": len([item for item in expected.get("tables") or [] if isinstance(item, dict)]),
        "seals": len([item for item in expected.get("seals") or [] if isinstance(item, dict)]),
    }


def fde_ocr_annotation_preview_url(task: dict[str, Any]) -> str | None:
    for key in ["pagePreviewUrl", "previewUrl", "previewDataUrl"]:
        value = str(task.get(key) or "").strip()
        if value:
            return value
    task_id = str(task.get("taskId") or task.get("caseId") or "").strip()
    if task_id and fde_ocr_annotation_preview_path(task):
        return f"/api/fde/ocr-annotation/tasks/{task_id}/preview"
    return None


def fde_ocr_annotation_preview_path(task: dict[str, Any]) -> Path | None:
    preview_paths = task.get("previewPaths") if isinstance(task.get("previewPaths"), list) else []
    raw = str(task.get("pagePreviewPath") or (preview_paths[0] if preview_paths else None) or task.get("sourcePath") or "").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = WORKSPACE_ROOT / candidate
    try:
        resolved = candidate.resolve()
        allowed_roots = [WORKSPACE_ROOT.resolve(), Path(tempfile.gettempdir()).resolve()]
        if not any(resolved == root or root in resolved.parents for root in allowed_roots):
            return None
        if resolved.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            return None
        return resolved if resolved.exists() else None
    except OSError:
        return None


def fde_ocr_annotation_default_page_dimensions(task: dict[str, Any]) -> dict[str, list[int]]:
    dimensions = task.get("pageDimensions") if isinstance(task.get("pageDimensions"), dict) else {}
    if dimensions:
        return repo.clone(dimensions)
    return {"1": [2000, 1500]}


def fde_update_ocr_annotation_readiness(task: dict[str, Any]) -> dict[str, Any]:
    readiness = fde_ocr_annotation_readiness([task])
    task["readinessBlockers"] = (readiness.get("tasks") or [{}])[0].get("blockers") or []
    task["readyForEval"] = bool((readiness.get("tasks") or [{}])[0].get("readyForEval"))
    task["updatedAt"] = server_time()
    return readiness


@router.get("/fde/ocr-annotation/tasks")
def fde_ocr_annotation_tasks(
    request: Request,
    status: str | None = None,
    scenario: str | None = None,
    profileId: str | None = None,
    pageNo: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=100),
):
    _, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
    if role_error:
        return role_error
    tasks = fde_ocr_annotation_tasks_source()
    if status:
        tasks = [item for item in tasks if str(item.get("collectionStatus") or "") == status]
    if scenario:
        tasks = [item for item in tasks if str(item.get("scenario") or "") == scenario]
    if profileId:
        tasks = [item for item in tasks if str(item.get("profileId") or "") == profileId]
    readiness = fde_ocr_annotation_readiness(tasks)
    task_views = [fde_ocr_annotation_task_view(item) for item in tasks]
    return ok({"summary": readiness["summary"], "nextActions": readiness["nextActions"], "page": page(task_views, pageNo, pageSize)}, request)


@router.get("/fde/ocr-annotation/tasks/{task_id}/preview")
def fde_ocr_annotation_task_preview(request: Request, task_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
    if role_error:
        return role_error
    task = fde_ocr_annotation_task(task_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    preview_path = fde_ocr_annotation_preview_path(task)
    if not preview_path:
        return fail(errors.NOT_FOUND, request)
    return FileResponse(preview_path)


@router.get("/fde/ocr-annotation/tasks/{task_id}")
def fde_ocr_annotation_task_detail(request: Request, task_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
    if role_error:
        return role_error
    task = next(
        (
            item
            for item in fde_ocr_annotation_tasks_source()
            if str(item.get("taskId") or item.get("caseId") or "") == task_id
        ),
        None,
    )
    if not task:
        return fail(errors.NOT_FOUND, request)
    readiness = fde_ocr_annotation_readiness([task])
    return ok({"task": fde_ocr_annotation_task_view(task), "readiness": readiness}, request)


@router.post("/fde/ocr-annotation/readiness")
def fde_ocr_annotation_readiness_endpoint(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
        if role_error:
            return role_error
        body_tasks = body.get("tasks") if isinstance(body.get("tasks"), list) else None
        tasks = [item for item in (body_tasks or fde_ocr_annotation_tasks_source()) if isinstance(item, dict)]
        return ok(fde_ocr_annotation_readiness(tasks), request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/fde/ocr-annotation/import-pack")
def fde_import_ocr_annotation_pack(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
        if role_error:
            return role_error
        payload = body.get("tasks")
        if payload is None and isinstance(body.get("pack"), dict):
            payload = body["pack"].get("tasks")
        if not isinstance(payload, list):
            return fail(errors.VALIDATION_ERROR, request, message="tasks must be an OCR annotation task list.")
        incoming = [repo.clone(item) for item in payload if isinstance(item, dict)]
        now = server_time()
        for index, task in enumerate(incoming, start=1):
            task_id = str(task.get("taskId") or task.get("caseId") or f"ANNO-IMPORT-{uuid4().hex[:8].upper()}").strip()
            task["taskId"] = task_id
            task.setdefault("caseId", f"imported-{index}")
            task.setdefault("collectionStatus", "needs_labeling")
            task["importedAt"] = now
            task["updatedAt"] = now
        if body.get("replace"):
            repo.state["ocr_annotation_tasks"] = incoming
        else:
            existing = repo.state.setdefault("ocr_annotation_tasks", [])
            index_by_id = {str(item.get("taskId") or item.get("caseId") or ""): idx for idx, item in enumerate(existing)}
            for task in incoming:
                identity = str(task.get("taskId") or task.get("caseId") or "")
                if identity in index_by_id:
                    existing[index_by_id[identity]] = {**existing[index_by_id[identity]], **task}
                else:
                    existing.append(task)
        tasks = repo.state.setdefault("ocr_annotation_tasks", [])
        readiness = fde_ocr_annotation_readiness(tasks)
        audit_id = repo.add_audit("FDE OCR 标注任务包导入", "OcrAnnotationPack", "import-pack")
        return ok(
            {
                "summary": {
                    "importedTasks": len(incoming),
                    "totalTasks": len(tasks),
                    "replace": bool(body.get("replace")),
                },
                "readiness": readiness,
                "page": page([fde_ocr_annotation_task_view(item) for item in tasks], 1, 20),
                "auditLogId": audit_id,
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.put("/fde/ocr-annotation/tasks/{task_id}/label")
def fde_save_ocr_annotation_label(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
        if role_error:
            return role_error
        task = fde_ocr_annotation_task(task_id)
        if not task:
            return fail(errors.NOT_FOUND, request)
        labeled = body.get("labeledExpected")
        if not isinstance(labeled, dict) or not labeled:
            return fail(errors.VALIDATION_ERROR, request, message="labeledExpected must be a non-empty object.")
        now = server_time()
        task["labeledExpected"] = repo.clone(labeled)
        task["labeler"] = str(body.get("labeler") or fde_subject_user_id(request) or role or "fde").strip()
        task["labelUpdatedAt"] = now
        task["collectionStatus"] = str(body.get("collectionStatus") or "labeled")
        task["labelComment"] = str(body.get("comment") or "")
        if isinstance(body.get("pageDimensions"), dict):
            task["pageDimensions"] = repo.clone(body["pageDimensions"])
        for key in ["pageNo", "previewUrl", "pagePreviewUrl", "pagePreviewPath", "sourcePath"]:
            if body.get(key) is not None:
                task[key] = body.get(key)
        readiness = fde_update_ocr_annotation_readiness(task)
        audit_id = repo.add_audit("FDE OCR 人工标注保存", "OcrAnnotationTask", str(task.get("taskId") or task_id))
        return ok({"task": fde_ocr_annotation_task_view(task), "readiness": readiness, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"taskId": task_id, "body": body})


@router.post("/fde/ocr-annotation/tasks/{task_id}/verify")
def fde_verify_ocr_annotation_task(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
        if role_error:
            return role_error
        task = fde_ocr_annotation_task(task_id)
        if not task:
            return fail(errors.NOT_FOUND, request)
        if not isinstance(task.get("labeledExpected"), dict):
            return fail(errors.VALIDATION_ERROR, request, message="task must be labeled before verify.")
        now = server_time()
        decision = str(body.get("decision") or "approved")
        if decision not in {"approved", "rejected"}:
            return fail(errors.VALIDATION_ERROR, request, message="decision must be approved or rejected.")
        expected = repo.clone(task["labeledExpected"])
        expected.setdefault("review", {})
        expected["review"].update(
            {
                "labeler": str(body.get("labeler") or task.get("labeler") or "").strip(),
                "reviewer": str(body.get("reviewer") or fde_subject_user_id(request) or role or "fde").strip(),
                "reviewedAt": now,
                "decision": decision,
                "comment": body.get("comment") or body.get("reason") or "",
            }
        )
        task["labeledExpected"] = expected
        task["reviewer"] = expected["review"]["reviewer"]
        task["reviewedAt"] = now
        task["reviewStatus"] = decision
        task["collectionStatus"] = "ready_for_eval" if decision == "approved" else "rejected"
        if decision == "rejected":
            task["rejectionReason"] = body.get("reason") or body.get("comment") or ""
        readiness = fde_update_ocr_annotation_readiness(task)
        audit_id = repo.add_audit("FDE OCR 标注确认", "OcrAnnotationTask", str(task.get("taskId") or task_id), decision)
        return ok({"task": fde_ocr_annotation_task_view(task), "readiness": readiness, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"taskId": task_id, "body": body})


@router.post("/fde/ocr-annotation/tasks/{task_id}/review")
def fde_review_ocr_annotation_task(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
        if role_error:
            return role_error
        task = fde_ocr_annotation_task(task_id)
        if not task:
            return fail(errors.NOT_FOUND, request)
        now = server_time()
        labeler = str(body.get("labeler") or task.get("labeler") or "").strip()
        reviewer = str(body.get("reviewer") or fde_subject_user_id(request) or role or "fde").strip()
        if isinstance(body.get("labeledExpected"), dict):
            task["labeledExpected"] = repo.clone(body["labeledExpected"])
        if not isinstance(task.get("labeledExpected"), dict) and isinstance(task.get("suggestedExpected"), dict):
            task["labeledExpected"] = repo.clone(task["suggestedExpected"])
        expected = task.get("labeledExpected") if isinstance(task.get("labeledExpected"), dict) else {}
        expected.setdefault("review", {})
        expected["review"].update(
            {
                "labeler": labeler,
                "reviewer": reviewer,
                "reviewedAt": now,
                "comment": body.get("comment") or "",
            }
        )
        task["labeledExpected"] = expected
        task["labeler"] = labeler
        task["reviewer"] = reviewer
        task["reviewedAt"] = now
        task["collectionStatus"] = body.get("collectionStatus") or "ready_for_eval"
        readiness = fde_update_ocr_annotation_readiness(task)
        audit_id = repo.add_audit("FDE OCR 标注二审", "OcrAnnotationTask", str(task.get("taskId") or task_id))
        return ok({"task": fde_ocr_annotation_task_view(task), "readiness": readiness, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"taskId": task_id, "body": body})


@router.post("/fde/ocr-annotation/export-label-studio")
def fde_export_ocr_annotation_label_studio(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
        if role_error:
            return role_error
        tasks = [item for item in (body.get("tasks") if isinstance(body.get("tasks"), list) else fde_ocr_annotation_tasks_source()) if isinstance(item, dict)]
        preview_base_dir = Path(str(body.get("previewBaseDir") or ".")).expanduser().resolve()
        local_files_root = Path(str(body.get("localFilesRoot") or preview_base_dir)).expanduser().resolve()
        image_url_prefix = str(body.get("imageUrlPrefix") or "/data/local-files/?d=")
        include_without_image = bool(body.get("includeWithoutImage", True))
        converted_tasks: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for task in tasks:
            converted, reason = label_studio_task(
                task,
                preview_base_dir=preview_base_dir,
                local_files_root=local_files_root,
                image_url_prefix=image_url_prefix,
            )
            if converted is None:
                skipped.append({"caseId": task.get("caseId"), "taskId": task.get("taskId"), "reason": reason})
                if not include_without_image:
                    continue
                converted = label_studio_task_without_image(task, reason=reason)
            converted_tasks.append(converted)
        summary = {
            "schemaVersion": "aicheck-ocr-annotation-label-studio-export-v1",
            "generatedAt": server_time(),
            "tasks": len(converted_tasks),
            "sourceTasks": len(tasks),
            "skipped": len(skipped),
            "predictionTasks": len([item for item in converted_tasks if item.get("predictions")]),
            "includeWithoutImage": include_without_image,
            "skippedItems": skipped[:50],
        }
        return ok({"summary": summary, "labelConfigXml": label_config_xml(), "tasks": converted_tasks}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/fde/ocr-annotation/import-label-studio")
def fde_import_ocr_annotation_label_studio(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
        if role_error:
            return role_error
        label_export = body.get("labelStudioExport") or body.get("labelStudioTasks") or body.get("tasks")
        if not isinstance(label_export, list):
            return fail(errors.VALIDATION_ERROR, request, message="labelStudioExport must be a Label Studio task list.")
        source_tasks = body.get("annotationTasks") if isinstance(body.get("annotationTasks"), list) else repo.state.setdefault("ocr_annotation_tasks", [])
        with tempfile.TemporaryDirectory(prefix="aicheck-fde-ocr-annotation-") as temp_dir:
            temp_path = Path(temp_dir)
            label_path = temp_path / "label_studio_export.json"
            tasks_path = temp_path / "annotation_tasks.json"
            output_path = temp_path / "labeled_tasks.json"
            label_path.write_text(json.dumps(label_export, ensure_ascii=False), encoding="utf-8")
            tasks_path.write_text(json.dumps({"tasks": source_tasks}, ensure_ascii=False), encoding="utf-8")
            report = import_label_studio_annotations(
                label_path,
                annotation_tasks=tasks_path,
                output_path=output_path,
                mark_status=str(body.get("markStatus") or "labeled"),
                allow_incomplete=bool(body.get("allowIncomplete", False)),
            )
        repo.state["ocr_annotation_tasks"] = repo.clone(report.get("tasks") or [])
        import_record = {
            "id": f"OCRANNOIMP-{uuid4().hex[:8].upper()}",
            "summary": report.get("summary") or {},
            "ok": bool(report.get("ok")),
            "imported": repo.clone(report.get("imported") or []),
            "failures": repo.clone(report.get("failures") or []),
            "createdAt": server_time(),
        }
        repo.state.setdefault("ocr_annotation_imports", []).insert(0, import_record)
        readiness = fde_ocr_annotation_readiness(repo.state["ocr_annotation_tasks"])
        audit_id = repo.add_audit("FDE OCR 标注导入", "OcrAnnotationImport", import_record["id"], "成功" if report.get("ok") else "失败")
        return ok({"import": import_record, "readiness": readiness, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/fde/incidents")
def fde_incidents(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:incident:manage")
    if role_error:
        return role_error
    return ok({"incidents": repo.clone(repo.state.get("incidents", [])), "rca": repo.clone(repo.state.get("incident_rca", []))}, request)


@router.post("/fde/incidents/{incident_id}/rca")
def fde_update_incident_rca(
    request: Request,
    incident_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:incident:manage")
        if role_error:
            return role_error
        incident = repo.find_one("incidents", incident_id)
        if not incident:
            return fail(errors.NOT_FOUND, request)
        rca = repo.find_one("incident_rca", incident_id, id_field="incidentId")
        payload = {
            "id": (rca or {}).get("id") or f"RCA-{uuid4().hex[:8].upper()}",
            "incidentId": incident_id,
            "status": body.get("status") or "open",
            "rootCause": body.get("rootCause") or incident.get("rootCause") or "unknown",
            "impactScope": body.get("impactScope") or {"aiRunIds": incident.get("relatedAiRunIds") or []},
            "temporaryAction": body.get("temporaryAction") or "已记录临时处置。",
            "longTermAction": body.get("longTermAction") or "待 FDE 补充长期修复。",
            "owner": body.get("owner") or "FDE 工程师",
            "updatedAt": server_time(),
        }
        if rca:
            rca.update(payload)
        else:
            repo.state["incident_rca"].insert(0, payload)
        audit_id = repo.add_audit("FDE 更新事故 RCA", "IncidentRCA", payload["id"])
        return ok({"rca": payload, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"incidentId": incident_id, "body": body})


@router.post("/fde/incidents/{incident_id}/close")
def fde_close_incident(
    request: Request,
    incident_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:incident:manage")
        if role_error:
            return role_error
        incident = repo.find_one("incidents", incident_id)
        if not incident:
            return fail(errors.NOT_FOUND, request)
        incident["status"] = "closed"
        incident["closedAt"] = server_time()
        incident["resolution"] = body.get("resolution") or "FDE 已完成 RCA 和整改追踪。"
        incident["closedByRole"] = effective_role_for_request(request)[0]
        audit_id = repo.add_audit("FDE 关闭事故", "Incident", incident_id)
        return ok({"incident": repo.clone(incident), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"incidentId": incident_id, "body": body})


@router.get("/fde/cost-budgets")
def fde_cost_budgets(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:dashboard:view")
    if role_error:
        return role_error
    ai_runs = repo.state.get("ai_runs", [])
    return ok(
        {
            "budgets": repo.clone(repo.state.get("cost_budgets", [])),
            "usage": {
                "tokenEstimate": sum(int(item.get("tokenUsage") or 0) for item in ai_runs),
                "estimatedPrice": round(sum(float(item.get("estimatedPrice") or 0) for item in ai_runs), 4),
                "runCount": len(ai_runs),
            },
            "exports": repo.clone(repo.state.get("data_exports", [])),
            "changeRequests": repo.clone(fde_state_list("cost_budget_change_requests")),
        },
        request,
    )


@router.post("/fde/cost-budgets/{budget_id}/propose-change")
def fde_propose_cost_budget_change(
    request: Request,
    budget_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:cost:manage")
        if role_error:
            return role_error
        budget = next((item for item in repo.state.get("cost_budgets", []) if item.get("id") == budget_id), None)
        if not budget:
            return fail(errors.NOT_FOUND, request)
        change = {
            "id": body.get("id") or f"CBCHG-{uuid4().hex[:8].upper()}",
            "budgetId": budget_id,
            "status": "pending_approval",
            "currentBudget": repo.clone(budget),
            "proposedLimit": body.get("proposedLimit"),
            "proposedPolicy": body.get("proposedPolicy") or {},
            "reason": body.get("reason") or "FDE 提交成本预算调整建议。",
            "requestedByRole": effective_role_for_request(request)[0],
            "createdAt": server_time(),
        }
        fde_state_list("cost_budget_change_requests").insert(0, change)
        audit_id = repo.add_audit("FDE 提交成本预算变更申请", "CostBudgetChangeRequest", change["id"])
        return ok({"changeRequest": change, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"budgetId": budget_id, "body": body})


@router.get("/fde/acceptance-reports")
def fde_acceptance_reports(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:business-pack:view")
    if role_error:
        return role_error
    return ok(repo.clone(repo.state.get("delivery_acceptance_reports", [])), request)


@router.get("/knowledge/overview")
def knowledge_overview(request: Request):
    sources = repo.state["knowledge_sources"]
    files = repo.state["knowledge_files"]
    tasks = repo.state["knowledge_tasks"]
    return ok(
        {
            "metrics": [
                {"key": "source", "label": "知识源", "value": len(sources), "tone": "blue"},
                {"key": "file", "label": "项目文件", "value": len(files), "tone": "green"},
                {"key": "task", "label": "运行任务", "value": len([item for item in tasks if item["status"] in {"排队中", "运行中"}]), "tone": "orange"},
                {"key": "failed", "label": "失败任务", "value": len([item for item in tasks if item["status"] == "失败"]), "tone": "red"},
            ],
            "libraries": [
                {
                    "key": source["id"],
                    "name": source["name"],
                    "fileCount": source["fileCount"],
                    "chunkCount": source["chunkCount"],
                    "vectorCount": source["chunkCount"],
                    "indexVersion": source.get("version") or "v1",
                    "status": source["status"],
                    "updatedAt": source["updatedAt"],
                }
                for source in sources
            ],
            "scorecard": build_knowledge_rule_scorecard(repo.state),
        },
        request,
    )


@router.get("/knowledge/sources")
def list_knowledge_sources(request: Request, keyword: str | None = None, sourceType: str | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [versioned_record("knowledge-source", item) for item in repo.state["knowledge_sources"]]
    if sourceType:
        items = [item for item in items if item["sourceType"] == sourceType]
    if status:
        items = [item for item in items if item["status"] == status]
    items = filter_keyword(items, keyword, ["name", "version", "status"])
    return ok(page(items, page_no, page_size), request)


@router.post("/knowledge/sources")
def create_knowledge_source(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        source = {
            "id": f"KS-{uuid4().hex[:8].upper()}",
            "name": body.get("name") or "新知识源",
            "sourceType": body.get("sourceType") or "manual",
            "version": body.get("version"),
            "status": body.get("status") or "启用",
            "fileCount": int(body.get("fileCount") or 0),
            "chunkCount": int(body.get("chunkCount") or 0),
            "vectorStatus": body.get("vectorStatus") or "待向量化",
            "updatedAt": server_time(),
            "actions": ["knowledge:view", "knowledge:manage", "knowledge:reindex"],
            "revision": 1,
        }
        repo.state["knowledge_sources"].insert(0, source)
        audit_id = repo.add_audit("新增知识源", "KnowledgeSource", source["id"])
        return ok({"source": versioned_record("knowledge-source", source), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/knowledge/sources/{source_id}")
def get_knowledge_source(request: Request, source_id: str):
    source = repo.find_one("knowledge_sources", source_id)
    if not source:
        return fail(errors.NOT_FOUND, request)
    return ok({"source": versioned_record("knowledge-source", source)}, request)


@router.put("/knowledge/sources/{source_id}")
@router.patch("/knowledge/sources/{source_id}")
def update_knowledge_source(
    request: Request,
    source_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        source = repo.find_one("knowledge_sources", source_id)
        if not source:
            return fail(errors.NOT_FOUND, request)
        effective_if_match = if_match if if_match is not None else request.headers.get("If-Match")
        if not record_if_match_valid("knowledge-source", source, effective_if_match):
            return fail(errors.ETAG_CONFLICT, request)
        changed = []
        for field in ["name", "sourceType", "version", "status", "fileCount", "chunkCount", "vectorStatus"]:
            if field in body and source.get(field) != body[field]:
                changed.append({"field": field, "before": source.get(field), "after": body[field]})
                source[field] = body[field]
        if changed:
            bump_record_revision(source)
        audit_id = repo.add_audit("更新知识源", "KnowledgeSource", source_id)
        return ok({"source": versioned_record("knowledge-source", source), "auditLogId": audit_id, "changed": changed}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"sourceId": source_id, "body": body})


@router.post("/knowledge/sources/{source_id}/enable")
def enable_knowledge_source(request: Request, source_id: str, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    return update_knowledge_source(request, source_id, {"status": "启用"}, idempotency_key=idempotency_key, if_match=if_match)


@router.post("/knowledge/sources/{source_id}/disable")
def disable_knowledge_source(request: Request, source_id: str, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    return update_knowledge_source(request, source_id, {"status": "停用"}, idempotency_key=idempotency_key, if_match=if_match)


@router.get("/knowledge/project-files")
def list_knowledge_files(request: Request, keyword: str | None = None, projectId: str | None = None, nodeId: int | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [
        repo.clone(item)
        for item in repo.state["knowledge_files"]
        if record_visible_for_request(request, item)
    ]
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if nodeId:
        items = [item for item in items if int(item.get("nodeId") or 0) == int(nodeId)]
    if status:
        items = [item for item in items if status in {item.get("ocrStatus"), item.get("sliceStatus"), item.get("vectorStatus")}]
    items = filter_keyword(items, keyword, ["fileName", "sourceName", "nodeName"])
    return ok(page(items, page_no, page_size), request)


@router.get("/knowledge/files/{file_id}")
def knowledge_file_detail(request: Request, file_id: str):
    file = repo.find_one("knowledge_files", file_id)
    if not file:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, file)
    if scope_error:
        return scope_error
    document = repo.find_one("documents", file.get("documentId"))
    latest_task = next((item for item in repo.state["knowledge_tasks"] if item.get("targetId") == file_id), None)
    return ok(
        {
            "file": repo.clone(file),
            "document": repo.clone(document) if document else None,
            "currentVersion": repo.current_version(document["id"]) if document else None,
            "latestTask": versioned_record("knowledge-task", latest_task) if latest_task else None,
            "vectorSummary": {
                "vectorStatus": file.get("vectorStatus"),
                "vectorCount": file.get("vectorCount", 0),
                "indexVersion": "proj-v2026.06.26",
                "dimensions": 3072,
                "updatedAt": file.get("updatedAt"),
            },
        },
        request,
    )


@router.get("/knowledge/files/{file_id}/chunks")
def knowledge_file_chunks(request: Request, file_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    file = repo.find_one("knowledge_files", file_id)
    if file:
        scope_error = scope_error_for_record(request, file)
        if scope_error:
            return scope_error
    chunks = [repo.clone(item) for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == file_id]
    if not chunks:
        chunks = [
            {"id": f"CHK-{file_id}-{idx}", "chunkNo": idx, "text": f"知识切片 {idx}：压力管道资料审查关键字段与证据定位。", "pageNo": idx, "evidenceLinkId": "EV-24-001", "tokenCount": 128}
            for idx in range(1, 8)
        ]
    return ok(page(chunks, page_no, page_size), request)


@router.get("/knowledge/files/{file_id}/vectors")
def knowledge_file_vectors(request: Request, file_id: str):
    file = repo.find_one("knowledge_files", file_id)
    if not file:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, file)
    if scope_error:
        return scope_error
    return ok({"vectorStatus": file.get("vectorStatus"), "vectorCount": file.get("vectorCount", 0), "indexVersion": "proj-v2026.06.26", "dimensions": 3072, "updatedAt": file.get("updatedAt")}, request)


@router.get("/knowledge/files/{file_id}/reasoning-references")
def knowledge_file_reasoning_refs(request: Request, file_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    file = repo.find_one("knowledge_files", file_id)
    if file:
        scope_error = scope_error_for_record(request, file)
        if scope_error:
            return scope_error
    refs = [
        {"runId": run["id"], "nodeId": run["nodeId"], "subject": run["subject"], "model": run["model"], "quotedText": "证据链引用该文件的 OCR 字段。", "createdAt": run.get("finishedAt") or run.get("startedAt")}
        for run in repo.state["ai_runs"]
        if record_visible_for_request(request, run)
    ]
    return ok(page(refs, page_no, page_size), request)


@router.post("/knowledge/files/{file_id}/reindex")
def reindex_file(request: Request, file_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        file = repo.find_one("knowledge_files", file_id)
        if not file:
            return fail(errors.NOT_FOUND, request)
        scope_error = scope_error_for_record(request, file)
        if scope_error:
            return scope_error
        task = {"id": f"KT-{uuid4().hex[:8].upper()}", "taskType": "reindex", "targetType": "file", "targetId": file_id, "targetName": file["fileName"], "status": "排队中", "progress": 0, "createdAt": server_time(), "updatedAt": server_time(), "revision": 1, "actions": ["knowledge:task-retry"]}
        repo.state["knowledge_tasks"].insert(0, task)
        return ok({"task": versioned_record("knowledge-task", task)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/knowledge/tasks")
def list_knowledge_tasks(request: Request, taskType: str | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [versioned_record("knowledge-task", item) for item in repo.state["knowledge_tasks"] if record_visible_for_request(request, item)]
    if taskType:
        items = [item for item in items if item["taskType"] == taskType]
    if status:
        items = [item for item in items if item["status"] == status]
    items.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    items.sort(key=lambda item: KNOWLEDGE_TASK_STATUS_ORDER.get(str(item.get("status")), 99))
    return ok(page(items, page_no, page_size), request)


@router.get("/knowledge/tasks/{task_id}")
def knowledge_task_detail(request: Request, task_id: str):
    task = repo.find_one("knowledge_tasks", task_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, task)
    if scope_error:
        return scope_error
    return ok({"task": versioned_record("knowledge-task", task)}, request)


@router.get("/knowledge/tasks/{task_id}/logs")
def knowledge_task_logs(request: Request, task_id: str):
    task = repo.find_one("knowledge_tasks", task_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, task)
    if scope_error:
        return scope_error
    logs = task.get("logs") or [{"createdAt": task.get("createdAt") or server_time(), "level": "info", "message": f"任务 {task_id} 已进入队列。"}]
    return ok(logs, request)


def retry_dispatch_for_knowledge_task(request: Request, task: dict[str, Any]) -> tuple[list[dict[str, Any]], JSONResponse | None]:
    task_type = task.get("taskType")
    dispatches: list[dict[str, Any]] = []
    task["attempts"] = int(task.get("attempts") or 0) + 1
    task["status"] = "排队中"
    task["progress"] = 0
    task["updatedAt"] = server_time()
    task.pop("errorMessage", None)
    task.pop("finishedAt", None)
    repo.append_task_log(task, "info", f"第 {task['attempts']} 次重试已投递。")

    if task_type == "ocr":
        file = repo.find_one("knowledge_files", task.get("targetId"))
        document_id = task.get("documentId") or (file or {}).get("documentId")
        version_id = task.get("documentVersionId") or (file or {}).get("documentVersionId")
        version = repo.find_one("versions", version_id) if version_id else None
        document = repo.find_one("documents", document_id) if document_id else None
        if not document or not version:
            repo.mark_task_failed(task, "OCR 重试失败：找不到关联文档版本。")
            return [], fail(errors.NOT_FOUND, request, message="找不到关联文档版本。")
        task["documentId"] = document["id"]
        task["documentVersionId"] = version["id"]
        dispatches.append(
            task_dispatcher.dispatch_parse_document(
                document["id"],
                version["id"],
                version.get("storageKey") or version["id"],
                document.get("fileName") or task.get("targetName"),
            )
        )
    elif task_type == "slice":
        if not repo.find_one("knowledge_files", task.get("targetId")):
            repo.mark_task_failed(task, "切片重试失败：找不到关联知识文件。")
            return [], fail(errors.NOT_FOUND, request, message="找不到关联知识文件。")
        dispatches.append(task_dispatcher.dispatch_slice(task["targetId"]))
    elif task_type in {"vector", "embed"}:
        if not repo.find_one("knowledge_files", task.get("targetId")):
            repo.mark_task_failed(task, "向量化重试失败：找不到关联知识文件。")
            return [], fail(errors.NOT_FOUND, request, message="找不到关联知识文件。")
        dispatches.append(task_dispatcher.dispatch_embed(task["targetId"]))
    elif task_type == "reindex":
        target_type = task.get("targetType")
        if target_type == "file":
            targets = [repo.find_one("knowledge_files", task.get("targetId"))]
        else:
            targets = [item for item in repo.state["knowledge_files"] if item.get("sourceId") == task.get("targetId")]
        targets = [item for item in targets if item]
        if not targets:
            repo.mark_task_failed(task, "重建索引失败：找不到可重建的知识文件。")
            return [], fail(errors.NOT_FOUND, request, message="找不到可重建的知识文件。")
        for file in targets:
            slice_task = repo.upsert_knowledge_task(
                task_type="slice",
                target_id=file["id"],
                target_name=file["fileName"],
                document_id=file.get("documentId"),
                version_id=file.get("documentVersionId"),
            )
            vector_task = repo.upsert_knowledge_task(
                task_type="vector",
                target_id=file["id"],
                target_name=file["fileName"],
                document_id=file.get("documentId"),
                version_id=file.get("documentVersionId"),
            )
            dispatches.append({"knowledgeTaskId": slice_task["id"], **task_dispatcher.dispatch_slice(file["id"])})
            dispatches.append({"knowledgeTaskId": vector_task["id"], **task_dispatcher.dispatch_embed(file["id"])})
        task["status"] = "成功"
        task["progress"] = 100
        task["finishedAt"] = server_time()
        repo.append_task_log(task, "info", f"重建索引已创建 {len(dispatches)} 个子任务。")
    else:
        repo.mark_task_failed(task, f"不支持的任务类型：{task_type}")
        return [], fail(errors.VALIDATION_ERROR, request, message=f"不支持的任务类型：{task_type}")

    task["lastDispatch"] = dispatches[0] if len(dispatches) == 1 else {"dispatches": dispatches}
    return dispatches, None


@router.post("/knowledge/tasks/{task_id}/retry")
def retry_knowledge_task(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        task = repo.find_one("knowledge_tasks", task_id)
        if not task:
            return fail(errors.NOT_FOUND, request)
        scope_error = scope_error_for_record(request, task)
        if scope_error:
            return scope_error
        if not record_if_match_valid("knowledge-task", task, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        dispatches, error = retry_dispatch_for_knowledge_task(request, task)
        if error:
            return error
        bump_record_revision(task)
        return ok({"task": versioned_record("knowledge-task", task), "dispatches": dispatches}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"taskId": task_id, "body": body})


@router.post("/knowledge/tasks/{task_id}/cancel")
def cancel_knowledge_task(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        task = repo.find_one("knowledge_tasks", task_id)
        if not task:
            return fail(errors.NOT_FOUND, request)
        scope_error = scope_error_for_record(request, task)
        if scope_error:
            return scope_error
        if not record_if_match_valid("knowledge-task", task, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        task["status"] = "已取消"
        bump_record_revision(task)
        repo.append_task_log(task, "info", "任务已取消。")
        return ok({"task": versioned_record("knowledge-task", task)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"taskId": task_id, "body": body})


@router.post("/knowledge/reindex")
def batch_reindex(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        ids = []
        targets = repo.state["knowledge_files"] if body.get("scope") != "source" else repo.state["knowledge_sources"]
        for target in targets[:3]:
            task = {"id": f"KT-{uuid4().hex[:8].upper()}", "taskType": "reindex", "targetType": "file" if "fileName" in target else "source", "targetId": target["id"], "targetName": target.get("fileName") or target.get("name"), "status": "排队中", "progress": 0, "createdAt": server_time(), "updatedAt": server_time(), "revision": 1, "actions": ["knowledge:task-retry"]}
            repo.state["knowledge_tasks"].insert(0, task)
            ids.append(task["id"])
        return ok({"taskIds": ids}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/knowledge/retrieval-test")
def retrieval_test(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    question = body.get("question") or "焊工资格证有效期如何校验？"
    retrieval = retrieve_knowledge_clauses(
        repo.state,
        query=str(question),
        business_pack_id=body.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
        node_id=int(body.get("nodeId")) if str(body.get("nodeId") or "").isdigit() else None,
        kb_version=body.get("kbVersion"),
        top_k=int(body.get("topK") or 5),
        query_type="interactive_retrieval_test",
    )
    return ok(
        {
            "answerDraft": answer_draft_from_clauses(str(question), retrieval["clauses"]),
            "hits": retrieval["trace"]["selectedClauses"],
            "retrievalTrace": retrieval["trace"],
            "latencyMs": 12,
            "usedIndexVersions": sorted({item.get("kbVersion") for item in retrieval["clauses"] if item.get("kbVersion")}),
        },
        request,
    )


@router.get("/knowledge/clauses")
def list_knowledge_clauses(
    request: Request,
    keyword: str | None = None,
    nodeId: int | None = None,
    businessPackId: str | None = None,
    page_no: int = Query(default=1, alias="page"),
    page_size: int = Query(default=20, alias="pageSize"),
):
    retrieval = retrieve_knowledge_clauses(
        repo.state,
        query=keyword or "审查依据",
        business_pack_id=businessPackId or DEFAULT_BUSINESS_PACK_ID,
        node_id=nodeId,
        top_k=max(page_no * page_size, page_size),
        query_type="clause_list",
    )
    items = retrieval["trace"]["selectedClauses"]
    return ok(page(items, page_no, page_size), request)


@router.get("/knowledge/page-index-nodes")
def list_knowledge_page_index_nodes(
    request: Request,
    keyword: str | None = None,
    kbDocId: str | None = None,
    parentNodeId: str | None = None,
    page_no: int = Query(default=1, alias="page"),
    page_size: int = Query(default=20, alias="pageSize"),
):
    items = [repo.clone(item) for item in repo.state.get("knowledge_page_index_nodes", [])]
    if kbDocId:
        items = [item for item in items if item.get("kbDocId") == kbDocId]
    if parentNodeId is not None:
        items = [item for item in items if str(item.get("parentNodeId")) == str(parentNodeId)]
    items = filter_keyword(items, keyword, ["title", "summary", "nodeId", "pageIndexNodeId"])
    if keyword:
        query = str(keyword).lower()
        items.sort(
            key=lambda item: (
                query in str(item.get("title") or "").lower(),
                query in str(item.get("summary") or "").lower(),
                not bool(item.get("children")),
            ),
            reverse=True,
        )
    return ok(page(items, page_no, page_size), request)


@router.get("/rules/versions")
def list_rule_versions(request: Request, keyword: str | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [versioned_record("rule-version", item) for item in repo.state["rule_versions"]]
    if status:
        items = [item for item in items if item["status"] == status]
    items = filter_keyword(items, keyword, ["name", "ruleKey", "version"])
    return ok(page(items, page_no, page_size), request)


@router.get("/rules/versions/{version_id}/diff")
def rule_version_diff(request: Request, version_id: str, targetVersionId: str | None = None, targetVersion: str | None = None):
    base = repo.find_one("rule_versions", version_id) or repo.state["rule_versions"][0]
    target = repo.find_one("rule_versions", targetVersionId or "") or repo.state["rule_versions"][-1]
    return ok(
        {
            "base": versioned_record("rule-version", base),
            "target": versioned_record("rule-version", target),
            "comparedAt": server_time(),
            "summary": {"added": 1, "changed": 2, "removed": 0, "warning": 1},
            "changes": [
                {"field": "version", "label": "版本号", "before": target.get("version"), "after": base.get("version"), "severity": "info", "changeType": "changed"},
                {"field": "nodes", "label": "适用节点", "before": target.get("nodeIds"), "after": base.get("nodeIds"), "severity": "warning", "changeType": "changed"},
            ],
        },
        request,
    )


@router.post("/rules/versions/{version_id}/publish")
def publish_rule_version(
    request: Request,
    version_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        rule = repo.find_one("rule_versions", version_id)
        if not rule:
            return fail(errors.NOT_FOUND, request)
        if not record_if_match_valid("rule-version", rule, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        rule["status"] = "已发布"
        rule["publishedAt"] = server_time()
        bump_record_revision(rule)
        result = repo.mutation_result("发布规则版本", "RuleVersion", version_id, next_status="已发布")
        return ok({**result, "rule": versioned_record("rule-version", rule)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"versionId": version_id, "body": body})


@router.post("/rules/versions/{version_id}/rollback")
def rollback_rule_version(
    request: Request,
    version_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        rule = repo.find_one("rule_versions", version_id)
        if not rule:
            return fail(errors.NOT_FOUND, request)
        if not record_if_match_valid("rule-version", rule, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        target = (
            repo.find_one("rule_versions", body.get("targetVersionId") or "")
            or next((item for item in repo.state["rule_versions"] if item.get("version") == body.get("targetVersion")), None)
            or repo.state["rule_versions"][0]
        )
        rule["status"] = "已回滚"
        bump_record_revision(rule)
        if target.get("id") != rule.get("id"):
            target["status"] = "已发布"
            target["publishedAt"] = server_time()
            bump_record_revision(target)
        result = repo.mutation_result("回滚规则版本", "RuleVersion", version_id, next_status="已回滚")
        return ok({**result, "rule": versioned_record("rule-version", rule), "target": versioned_record("rule-version", target)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"versionId": version_id, "body": body})


@router.get("/knowledge/config")
def get_knowledge_config(request: Request):
    config = versioned_singleton("knowledge-config", repo.state["knowledge_config"])
    return ok({"config": config, "updatedAt": config["updatedAt"], "revision": config["revision"], "etag": config["etag"]}, request)


@router.put("/knowledge/config")
@router.patch("/knowledge/config")
def update_knowledge_config(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    def produce():
        if not singleton_if_match_valid("knowledge-config", repo.state["knowledge_config"], if_match):
            return fail(errors.ETAG_CONFLICT, request)
        repo.state["knowledge_config"].update({key: value for key, value in body.items() if value is not None and key not in CONFIG_METADATA_FIELDS})
        bump_singleton_revision(repo.state["knowledge_config"])
        config = versioned_singleton("knowledge-config", repo.state["knowledge_config"])
        audit_id = repo.add_audit("更新知识库配置", "KnowledgeConfig", "default")
        return ok({"config": config, "updatedAt": config["updatedAt"], "revision": config["revision"], "etag": config["etag"], "auditLogId": audit_id}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source=body,
    )


@router.get("/knowledge/audit-logs")
def knowledge_audit_logs(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), keyword: str | None = None, objectType: str | None = None, result: str | None = None):
    items = [repo.clone(item) for item in repo.state["audit_logs"]]
    if objectType:
        items = [item for item in items if item.get("objectType") == objectType]
    if result:
        items = [item for item in items if item.get("result") == result]
    items = filter_keyword(items, keyword, ["action", "objectType", "objectId", "actorName"])
    return ok(page(items, page_no, page_size), request)


@router.get("/reasoning/logs")
def reasoning_logs(request: Request, projectId: str | None = None, nodeId: int | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [repo.clone(item) for item in repo.state["ai_runs"] if record_visible_for_request(request, item)]
    if projectId:
        items = [item for item in items if item["projectId"] == projectId]
    if nodeId:
        items = [item for item in items if int(item["nodeId"]) == int(nodeId)]
    if status:
        items = [item for item in items if item["status"] == status]
    return ok(page(items, page_no, page_size), request)


@router.get("/reasoning/logs/{log_id}")
def reasoning_log_detail(request: Request, log_id: str):
    run = repo.find_one("ai_runs", log_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, run)
    if scope_error:
        return scope_error
    return ok({"log": repo.clone(run), "evidenceLinks": repo.clone(run.get("evidenceLinks") or repo.state["evidence_links"])}, request)


@router.get("/reasoning/logs/{log_id}/evidence")
def reasoning_log_evidence(request: Request, log_id: str):
    run = repo.find_one("ai_runs", log_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, run)
    if scope_error:
        return scope_error
    return ok(repo.clone(run.get("evidenceLinks") or repo.state["evidence_links"]), request)


@router.post("/llm/compare")
def llm_compare(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        project_id = body.get("projectId")
        node_ids = node_ids_from_body(body)
        if project_id:
            role, identity_error = effective_role_for_request(request)
            if identity_error:
                return identity_error
            scope_error = member_node_scope_error(request, project_id, role, node_ids=node_ids)
            if scope_error:
                return scope_error
        run_id = f"CMP-{uuid4().hex[:8].upper()}"
        run = {
            "runId": run_id,
            "question": body.get("question") or "请对比审查意见。",
            "modelCodes": body.get("modelCodes") or ["default-chat", "compare-fast"],
            "createdAt": server_time(),
            "projectId": body.get("projectId"),
            "nodeId": body.get("nodeId"),
            "evidenceLinkIds": body.get("evidenceLinkIds") or ["EV-24-001"],
            "status": "排队中",
            "results": [],
        }
        repo.state["llm_compare_runs"].insert(0, run)
        dispatch = task_dispatcher.dispatch_llm_compare(run_id)
        return ok({**run, "dispatch": dispatch}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/llm/compare-runs")
def list_compare_runs(request: Request, projectId: str | None = None, nodeId: int | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [repo.clone(item) for item in repo.state["llm_compare_runs"] if record_visible_for_request(request, item)]
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if nodeId:
        items = [item for item in items if int(item.get("nodeId") or 0) == int(nodeId)]
    summaries = [
        {
            "runId": item["runId"],
            "question": item["question"],
            "modelCodes": item["modelCodes"],
            "createdAt": item["createdAt"],
            "projectId": item.get("projectId"),
            "nodeId": item.get("nodeId"),
            "status": item.get("status", "完成"),
        }
        for item in items
    ]
    return ok(page(summaries, page_no, page_size), request)


@router.get("/llm/compare-runs/{run_id}")
def compare_run_detail(request: Request, run_id: str):
    run = repo.find_one("llm_compare_runs", run_id, id_field="runId")
    if not run:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, run)
    if scope_error:
        return scope_error
    return ok(repo.clone(run), request)


@router.get("/admin/config-overview")
def admin_config_overview(request: Request):
    overview = repo.build_admin_overview()
    overview.update(
        {
            "revision": singleton_revision(repo.state["admin_config"]),
            "etag": singleton_etag("admin-config", repo.state["admin_config"]),
            "updatedAt": repo.state["admin_config"].get("updatedAt") or server_time(),
        }
    )
    return ok(overview, request)


@router.post("/admin/projects")
def create_admin_project(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        pack_id = body.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID
        try:
            pack = load_business_pack(pack_id)
        except ValueError as exc:
            return fail(errors.VALIDATION_ERROR, request, message=str(exc))
        project_id = body.get("code") or f"P-2026-{uuid4().hex[:6].upper()}"
        defaults = project_defaults_for_pack(pack)
        project = {
            "id": project_id,
            "code": project_id,
            "name": body.get("name") or defaults["name"],
            "type": body.get("type") or defaults["type"],
            "region": body.get("region") or "华东",
            "ownerOrgName": body.get("ownerOrgName") or defaults["ownerOrgName"],
            "contractorOrgName": body.get("contractorOrgName") or defaults["contractorOrgName"],
            "ndtOrgName": body.get("ndtOrgName") or defaults["ndtOrgName"],
            "inspectionOrgName": body.get("inspectionOrgName") or defaults["inspectionOrgName"],
            "businessPackId": pack["id"],
            "businessPackVersion": pack["version"],
            "domainType": pack["domainType"],
            "businessPackSnapshotHash": pack["snapshotHash"],
            "businessPackSnapshot": business_pack_snapshot(pack),
            "status": "草稿/立项中",
            "todoCount": 0,
            "messageCount": 0,
            "currentNodeId": int(body.get("currentNodeId") or pack["nodeTemplates"][0]["nodeId"]),
            "updatedAt": server_time(),
            "actions": ["project:view", "project:authorize-member"],
            "revision": 1,
        }
        repo.state["projects"].insert(0, project)
        created_node_count, created_requirement_count = attach_business_pack_project_scaffold(project, pack)
        member_user_ids = body.get("memberUserIds") or {}
        role_node_scope = {
            role["code"]: [int(item["nodeId"]) for item in pack["nodeTemplates"]]
            for role in pack["roles"]
            if role["code"] != "admin"
        }
        role_org_names = {
            "owner": project["ownerOrgName"],
            "contractor": project["contractorOrgName"],
            "ndt": project["ndtOrgName"],
            "inspection": project["inspectionOrgName"],
            "observer": project["ownerOrgName"],
            "submitter": project["contractorOrgName"],
            "auditor": project["inspectionOrgName"],
        }
        for role_def in [item for item in pack["roles"] if item["code"] != "admin"]:
            role = role_def["code"]
            repo.state["project_members"].insert(
                0,
                project_member_snapshot(
                    project_id,
                    role,
                    member_user_ids.get(role),
                    org_name=role_org_names.get(role, project["inspectionOrgName"]),
                    node_scope=role_node_scope[role],
                    actions=role_def["actions"],
                ),
            )
        audit_id = repo.add_audit("项目立项", "Project", project_id)
        detail_data = project_detail_payload(project_id)
        return ok(
            {
                "project": versioned_project(project),
                "detail": detail_data,
                "businessPack": business_pack_summary(pack),
                "auditLogId": audit_id,
                "createdNodeCount": created_node_count,
                "createdRequirementCount": created_requirement_count,
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/admin/integration-contract")
def integration_contract(request: Request, module: str | None = None, status: str | None = None):
    modules = [
        ("workbench", "工作台首屏"),
        ("documents", "资料文件"),
        ("submissions", "提交补正"),
        ("inspection", "监检审查"),
        ("ndt-owner-report", "无损与报告"),
        ("knowledge-admin", "知识库与后台"),
    ]
    fields = [
        {
            "id": "IC-001",
            "module": "workbench",
            "moduleLabel": "工作台首屏",
            "endpoint": "/api/workbench/projects",
            "method": "GET",
            "frontendField": "projects[].riskLevel",
            "backendField": "riskLevel",
            "required": False,
            "status": "已对齐",
            "severity": "info",
            "owner": "backend",
            "note": "工作台项目列表按节点状态、待办、补正、AI/任务失败实时计算风险等级。",
            "updatedAt": server_time(),
        },
        {
            "id": "IC-002",
            "module": "submissions",
            "moduleLabel": "提交补正",
            "endpoint": "/api/projects/{projectId}/submissions",
            "method": "GET",
            "frontendField": "drafts[].nodeNames",
            "backendField": "drafts[].nodeNames",
            "required": True,
            "status": "已对齐",
            "severity": "info",
            "owner": "backend",
            "note": "提交草稿和提交批次摘要均已返回节点名称。",
            "updatedAt": server_time(),
        },
        {
            "id": "IC-003",
            "module": "inspection",
            "moduleLabel": "监检审查",
            "endpoint": "/api/projects/{projectId}/inspection/nodes/{nodeId}/review-opinions",
            "method": "POST",
            "frontendField": "riskLevel",
            "backendField": "riskLevel",
            "required": True,
            "status": "已对齐",
            "severity": "info",
            "owner": "backend",
            "note": "审查意见保存已返回风险等级。",
            "updatedAt": server_time(),
        },
        {
            "id": "IC-004",
            "module": "knowledge-admin",
            "moduleLabel": "知识库与后台",
            "endpoint": "/api/knowledge/tasks",
            "method": "GET",
            "frontendField": "items[].targetName",
            "backendField": "targetName",
            "required": True,
            "status": "已对齐",
            "severity": "info",
            "owner": "backend",
            "note": "任务中心支持重试和取消。",
            "updatedAt": server_time(),
        },
        {
            "id": "IC-005",
            "module": "documents",
            "moduleLabel": "资料文件",
            "endpoint": "/api/projects/{projectId}/documents/upload-session",
            "method": "POST",
            "frontendField": "uploadUrls[].documentVersionId",
            "backendField": "uploadUrls[].documentVersionId",
            "required": True,
            "status": "已对齐",
            "severity": "info",
            "owner": "backend",
            "note": "上传会话返回 documentId/documentVersionId、signed PUT URL 和 expiresAt，完成上传后创建 OCR 任务。",
            "updatedAt": server_time(),
        },
        {
            "id": "IC-006",
            "module": "ndt-owner-report",
            "moduleLabel": "无损与报告",
            "endpoint": "/api/projects/{projectId}/ndt/reports",
            "method": "GET",
            "frontendField": "items[].relatedFilmIds",
            "backendField": "relatedFilmIds",
            "required": True,
            "status": "已对齐",
            "severity": "info",
            "owner": "backend",
            "note": "NDT 报告列表返回状态、方法、关联底片和可执行动作；报告/归档导出产物包含可审计 manifest。",
            "updatedAt": server_time(),
        },
    ]
    if module and module != "all":
        fields = [item for item in fields if item["module"] == module]
    if status and status != "all":
        fields = [item for item in fields if item["status"] == status]
    module_summaries = []
    for code, label in modules:
        module_fields = [item for item in fields if item["module"] == code]
        total = len(module_fields)
        aligned = len([item for item in module_fields if item["status"] == "已对齐"])
        pending = len([item for item in module_fields if item["status"] in {"待后端确认", "命名不一致"}])
        blockers = len([item for item in module_fields if item["status"] in {"前端缺失", "后端缺失"}])
        module_summaries.append({"module": code, "label": label, "total": total, "aligned": aligned, "pending": pending, "blockers": blockers})
    return ok(
        {
            "summary": {
                "total": len(fields),
                "aligned": len([item for item in fields if item["status"] == "已对齐"]),
                "pending": len([item for item in fields if item["status"] in {"待后端确认", "命名不一致"}]),
                "blockers": len([item for item in fields if item["status"] in {"前端缺失", "后端缺失"}]),
            },
            "modules": module_summaries,
            "fields": fields,
            "generatedAt": server_time(),
        },
        request,
    )


@router.post("/admin/config-diff/preview")
def admin_config_diff_preview(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    values = body.get("values") or {}
    return ok(build_config_diff(body.get("target") or "config", body.get("id") or "new", values), request)


@router.post("/admin/config-items/{target}")
def create_admin_config_item(request: Request, target: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    def produce():
        if not singleton_if_match_valid("admin-config", repo.state["admin_config"], if_match):
            return fail(errors.ETAG_CONFLICT, request)
        values = body.get("values") or {}
        item_id = f"CFG-{uuid4().hex[:8].upper()}"
        item = {"id": item_id, **values, "updatedAt": server_time()}
        repo.state["admin_config"].setdefault(admin_collection_for(target), []).insert(0, item)
        bump_singleton_revision(repo.state["admin_config"])
        diff = build_config_diff(target, item_id, values, object_name=values.get("name") or values.get("scene") or target)
        audit_id = repo.add_audit("新增配置项", "AdminConfig", diff["objectId"])
        overview = repo.build_admin_overview()
        overview.update({"revision": singleton_revision(repo.state["admin_config"]), "etag": singleton_etag("admin-config", repo.state["admin_config"]), "updatedAt": repo.state["admin_config"]["updatedAt"]})
        return ok({"overview": overview, "diff": diff, "auditLogId": audit_id, "updatedAt": repo.state["admin_config"]["updatedAt"], "revision": overview["revision"], "etag": overview["etag"]}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"target": target, "body": body},
    )


@router.put("/admin/config-items/{target}/{item_id}")
def save_admin_config_item(request: Request, target: str, item_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    def produce():
        if not singleton_if_match_valid("admin-config", repo.state["admin_config"], if_match):
            return fail(errors.ETAG_CONFLICT, request)
        values = body.get("values") or {}
        collection = repo.state["admin_config"].setdefault(admin_collection_for(target), [])
        item = next((entry for entry in collection if entry.get("id") == item_id or entry.get("role") == item_id), None)
        if not item:
            return fail(errors.NOT_FOUND, request)
        item.update(values)
        item["updatedAt"] = server_time()
        bump_singleton_revision(repo.state["admin_config"])
        diff = build_config_diff(target, item_id, values, object_name=values.get("name") or values.get("scene") or target)
        audit_id = repo.add_audit("保存配置项", "AdminConfig", item_id)
        overview = repo.build_admin_overview()
        overview.update({"revision": singleton_revision(repo.state["admin_config"]), "etag": singleton_etag("admin-config", repo.state["admin_config"]), "updatedAt": repo.state["admin_config"]["updatedAt"]})
        return ok({"overview": overview, "diff": diff, "auditLogId": audit_id, "updatedAt": repo.state["admin_config"]["updatedAt"], "revision": overview["revision"], "etag": overview["etag"]}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"target": target, "itemId": item_id, "body": body},
    )


def admin_collection_for(kind: str) -> str:
    return {
        "todo-rule": "todoRules",
        "todo-rules": "todoRules",
        "message-template": "messageTemplates",
        "message-templates": "messageTemplates",
        "tool-source": "toolSources",
        "tool-sources": "toolSources",
        "field-mapping": "fieldMappings",
        "field-mappings": "fieldMappings",
        "workflow": "workflowStateMachines",
        "workflow-state-machines": "workflowStateMachines",
        "node-template": "nodeTemplates",
        "tree-nodes": "nodeTemplates",
        "permission": "permissionMatrix",
        "node-role-mappings": "permissionMatrix",
        "roles": "permissionMatrix",
        "rules": "ruleVersions",
    }.get(kind, kind)


@router.post("/admin/config-export")
def admin_config_export(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        export_id = f"EXP-CFG-{uuid4().hex[:8].upper()}"
        scope = body.get("scope") or "all"
        task = {"id": export_id, "exportType": "config-package", "status": "可下载", "progress": 100, "fileName": f"后台配置包-{scope}-20260626.zip", "fileSize": 204800, "downloadUrl": f"mock://download/admin/{export_id}.zip", "createdAt": server_time(), "finishedAt": server_time(), "expiresAt": "2026-06-27 18:00:00"}
        repo.attach_export_artifact(task, content_type="application/zip")
        repo.state["export_tasks"].insert(0, task)
        return ok({"exportId": export_id, "task": task}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/admin/{kind}")
def admin_generic_list(request: Request, kind: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    if kind == "audit-logs":
        return audit_logs(request, page_no, page_size)
    if kind == "config-overview":
        return admin_config_overview(request)
    if kind == "integration-contract":
        return integration_contract(request)
    collection = admin_collection_for(kind)
    items = repo.state["admin_config"].get(collection, [])
    return ok(page(repo.clone(items), page_no, page_size), request)


@router.post("/admin/{kind}")
def admin_generic_create(request: Request, kind: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    def produce():
        if not singleton_if_match_valid("admin-config", repo.state["admin_config"], if_match):
            return fail(errors.ETAG_CONFLICT, request)
        collection = admin_collection_for(kind)
        values = body.get("values") or body
        item = {"id": f"CFG-{uuid4().hex[:8].upper()}", **values, "updatedAt": server_time()}
        repo.state["admin_config"].setdefault(collection, []).insert(0, item)
        bump_singleton_revision(repo.state["admin_config"])
        return ok({"item": item, "auditLogId": repo.add_audit("新增后台配置", "AdminConfig", item["id"]), "revision": singleton_revision(repo.state["admin_config"]), "etag": singleton_etag("admin-config", repo.state["admin_config"]), "updatedAt": repo.state["admin_config"]["updatedAt"]}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"kind": kind, "body": body},
    )


@router.patch("/admin/{kind}/{item_id}")
def admin_generic_update(request: Request, kind: str, item_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    def produce():
        if not singleton_if_match_valid("admin-config", repo.state["admin_config"], if_match):
            return fail(errors.ETAG_CONFLICT, request)
        collection = admin_collection_for(kind)
        items = repo.state["admin_config"].setdefault(collection, [])
        item = next((entry for entry in items if entry.get("id") == item_id), None)
        if not item:
            return fail(errors.NOT_FOUND, request)
        item.update(body)
        item["updatedAt"] = server_time()
        bump_singleton_revision(repo.state["admin_config"])
        return ok({"item": item, "auditLogId": repo.add_audit("更新后台配置", "AdminConfig", item_id), "revision": singleton_revision(repo.state["admin_config"]), "etag": singleton_etag("admin-config", repo.state["admin_config"]), "updatedAt": repo.state["admin_config"]["updatedAt"]}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"kind": kind, "itemId": item_id, "body": body},
    )


@router.get("/admin/workflow-state-machines")
def workflow_state_machines(request: Request):
    return ok(repo.state["admin_config"]["workflowStateMachines"], request)


@router.post("/admin/workflow-state-machines")
def create_workflow_state_machine(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    return admin_generic_create(request, "workflowStateMachines", body, idempotency_key, if_match)


@router.patch("/admin/workflow-state-machines/{state_machine_id}")
def update_workflow_state_machine(request: Request, state_machine_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    return admin_generic_update(request, "workflowStateMachines", state_machine_id, body, idempotency_key, if_match)


@router.post("/admin/config-overview/publish")
def publish_admin_config(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        if not singleton_if_match_valid("admin-config", repo.state["admin_config"], if_match):
            return fail(errors.ETAG_CONFLICT, request)
        publish_id = f"PUB-{uuid4().hex[:8].upper()}"
        audit_id = repo.add_audit("发布后台配置", "AdminConfig", publish_id)
        version = "config-v2026.06.27"
        scope = body.get("scope") or "all"
        repo.state["admin_config"]["lastPublishedVersion"] = version
        repo.state["admin_config"]["lastPublishedAt"] = server_time()
        repo.state["admin_config"]["lastPublishedScope"] = scope
        bump_singleton_revision(repo.state["admin_config"])
        message = {
            "id": f"MSG-{uuid4().hex[:8].upper()}",
            "title": f"后台配置已发布：{version}",
            "content": f"发布范围 {scope}，权限、待办和消息模板已完成联动刷新。",
            "projectId": PROJECT_ID,
            "targetType": "admin_config",
            "targetId": publish_id,
            "read": False,
            "createdAt": server_time(),
        }
        todo = {
            "id": f"TODO-{uuid4().hex[:8].upper()}",
            "title": "字段映射配置发布影响",
            "projectId": PROJECT_ID,
            "nodeId": 24,
            "targetType": "admin_config",
            "targetId": publish_id,
            "status": "待处理",
            "priority": "中",
            "assigneeName": "张工",
            "actions": ["admin:config", "knowledge:manage"],
        }
        repo.state["messages"].insert(0, message)
        repo.state["todos"].insert(0, todo)
        impacts = [
            {"domain": "permission", "label": "权限矩阵", "affectedCount": 5, "status": "已同步", "trace": "权限矩阵已同步到工作台动作权限"},
            {"domain": "message-template", "label": "消息模板", "affectedCount": 2, "status": "已同步", "trace": "消息模板已刷新待办通知"},
            {"domain": "field-mapping", "label": "字段映射", "affectedCount": 1, "status": "需复核", "trace": "字段映射阈值变更后需在真实 OCR 样例中复核"},
        ]
        return ok({"publishId": publish_id, "status": "已发布", "version": version, "auditLogId": audit_id, "publishedAt": repo.state["admin_config"]["lastPublishedAt"], "revision": singleton_revision(repo.state["admin_config"]), "etag": singleton_etag("admin-config", repo.state["admin_config"]), "impactSummary": {"totalAffected": 8, "warningCount": 1, "linkedProjects": len([item for item in repo.state["projects"] if item["status"] != "已归档"]), "pushedMessages": 1, "reviewTodos": 1}, "impacts": impacts}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/admin/audit-logs")
def audit_logs(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), keyword: str | None = None, result: str | None = None, objectType: str | None = None):
    items = [repo.clone(item) for item in repo.state["audit_logs"]]
    if result:
        items = [item for item in items if item.get("result") == result]
    if objectType:
        items = [item for item in items if item.get("objectType") == objectType]
    items = filter_keyword(items, keyword, ["action", "objectType", "objectId", "actorName"])
    return ok(page(items, page_no, page_size), request)


@router.get("/audit-logs")
def global_audit_logs(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return audit_logs(request, page_no, page_size)


@router.get("/projects/{project_id}/audit-logs")
def project_audit_logs(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return audit_logs(request, page_no, page_size)


@router.get("/projects/{project_id}/nodes/{node_id}/audit-logs")
def node_audit_logs(request: Request, project_id: str, node_id: int, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return audit_logs(request, page_no, page_size)


@router.get("/admin/org-units")
def org_units_alias(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return ok(page(repo.clone(repo.state["admin_config"]["orgUnits"]), page_no, page_size), request)


@router.get("/admin/users")
def users_alias(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return ok(page(repo.clone(repo.state["admin_config"]["users"]), page_no, page_size), request)


@router.get("/orgs")
def legacy_orgs(request: Request):
    return ok(repo.clone(repo.state["admin_config"]["orgUnits"]), request)


@router.get("/users")
def legacy_users(request: Request):
    return ok(repo.clone(repo.state["admin_config"]["users"]), request)
