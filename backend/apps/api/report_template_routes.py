"""报告模板管理路由（自 routes.py 拆出，2026-08-28）。

单体棘轮拆分：/admin/report-templates 全家迁移，零行为变化。
共享辅助从 apps.api.routes 导入（该方向无环）。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, Header, Query, Request

from apps.api.routes import (
    DEFAULT_BUSINESS_PACK_ID,
    bump_record_revision,
    compact_plain_text,
    errors,
    fail,
    filter_keyword,
    idempotent,
    ok,
    page,
    record_if_match_valid,
    repo,
    server_time,
    versioned_record,
)

report_template_router = APIRouter()
router = report_template_router  # 迁移块沿用 @router

REPORT_TEMPLATE_STATUSES = {"draft", "production", "retired", "草稿", "已发布", "已停用"}
REPORT_TEMPLATE_EXPORT_TYPES = {"report", "archive-package", "evidence-package"}


def normalize_report_template_sections(raw_sections: Any) -> list[dict[str, str]]:
    if not isinstance(raw_sections, list):
        return []
    sections: list[dict[str, str]] = []
    for item in raw_sections[:20]:
        if not isinstance(item, dict):
            continue
        code = compact_plain_text(item.get("code"), 80)
        title = compact_plain_text(item.get("title"), 160)
        source = compact_plain_text(item.get("source"), 120)
        if code and title:
            sections.append({"code": code, "title": title, "source": source})
    return sections


def validate_report_template_record(record: dict[str, Any]) -> str | None:
    if not str(record.get("name") or "").strip():
        return "请填写报告模板名称。"
    sections = record.get("sections") or []
    if not sections:
        return "报告模板至少需要一个有效章节，且章节必须包含 code 和 title。"
    codes = [str(item.get("code") or "") for item in sections]
    if len(codes) != len(set(codes)):
        return "报告模板章节 code 不能重复。"
    return None


def normalize_report_template_record(
    raw: dict[str, Any], existing: dict[str, Any] | None = None
) -> dict[str, Any]:
    now = server_time()
    status = str(raw.get("status") or (existing or {}).get("status") or "draft")
    if status not in REPORT_TEMPLATE_STATUSES:
        status = "draft"
    requested_export_types = (
        raw.get("exportTypes")
        if raw.get("exportTypes") is not None
        else (existing or {}).get("exportTypes")
    )
    export_types = [
        str(item)
        for item in (requested_export_types or ["report"])
        if str(item) in REPORT_TEMPLATE_EXPORT_TYPES
    ]
    requested_sections = (
        raw.get("sections") if raw.get("sections") is not None else (existing or {}).get("sections")
    )
    return {
        **repo.clone(existing or {}),
        "id": str(raw.get("id") or (existing or {}).get("id") or f"RTPL-{uuid4().hex[:10].upper()}"),
        "name": compact_plain_text(raw.get("name") or (existing or {}).get("name"), 120),
        "version": compact_plain_text(
            raw.get("version") or (existing or {}).get("version") or now[:10].replace("-", "."),
            80,
        ),
        "status": status,
        "businessPackId": compact_plain_text(
            raw.get("businessPackId")
            or (existing or {}).get("businessPackId")
            or DEFAULT_BUSINESS_PACK_ID,
            120,
        ),
        "businessPackVersion": compact_plain_text(
            raw.get("businessPackVersion") or (existing or {}).get("businessPackVersion"), 80
        ),
        "exportTypes": list(dict.fromkeys(export_types)) or ["report"],
        "sections": normalize_report_template_sections(requested_sections),
        "updatedAt": now,
        "createdAt": (existing or {}).get("createdAt") or raw.get("createdAt") or now,
        "revision": int((existing or {}).get("revision") or raw.get("revision") or 1),
    }


@router.get("/admin/report-templates")
def list_report_templates(
    request: Request,
    keyword: str | None = None,
    status: str | None = None,
    businessPackId: str | None = None,
    page_no: int = Query(default=1, alias="page"),
    page_size: int = Query(default=20, alias="pageSize"),
):
    items = [versioned_record("report-template", item) for item in repo.state.get("report_templates", [])]
    if status:
        items = [item for item in items if item.get("status") == status]
    if businessPackId:
        items = [item for item in items if item.get("businessPackId") == businessPackId]
    items = filter_keyword(items, keyword, ["name", "version", "businessPackId"])
    return ok(page(items, page_no, page_size), request)


@router.post("/admin/report-templates")
def create_report_template(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        record = normalize_report_template_record(body)
        if record.get("status") in {"production", "已发布"}:
            record["status"] = "draft"
        validation_message = validate_report_template_record(record)
        if validation_message:
            return fail(errors.VALIDATION_ERROR, request, message=validation_message)
        repo.state.setdefault("report_templates", []).insert(0, record)
        audit_id = repo.add_audit("新增报告模板", "ReportTemplate", record["id"])
        return ok(
            {"template": versioned_record("report-template", record), "auditLogId": audit_id},
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/admin/report-templates/{template_id}")
def get_report_template(request: Request, template_id: str):
    template = repo.find_one("report_templates", template_id)
    if not template:
        return fail(errors.NOT_FOUND, request)
    return ok({"template": versioned_record("report-template", template)}, request)


@router.put("/admin/report-templates/{template_id}")
@router.patch("/admin/report-templates/{template_id}")
def update_report_template(
    request: Request,
    template_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        template = repo.find_one("report_templates", template_id)
        if not template:
            return fail(errors.NOT_FOUND, request)
        if not record_if_match_valid("report-template", template, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        if template.get("status") in {"production", "已发布"}:
            return fail(
                errors.VALIDATION_ERROR,
                request,
                message="生产中的报告模板不可直接编辑，请新建草稿版本后发布。",
            )
        normalized = normalize_report_template_record(
            {**template, **body, "id": template_id}, existing=template
        )
        if normalized.get("status") in {"production", "已发布"}:
            normalized["status"] = str(template.get("status") or "draft")
        validation_message = validate_report_template_record(normalized)
        if validation_message:
            return fail(errors.VALIDATION_ERROR, request, message=validation_message)
        normalized["revision"] = int(template.get("revision") or 1)
        template.clear()
        template.update(normalized)
        bump_record_revision(template)
        audit_id = repo.add_audit("编辑报告模板", "ReportTemplate", template_id)
        return ok(
            {"template": versioned_record("report-template", template), "auditLogId": audit_id},
            request,
        )

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"templateId": template_id, "body": body},
    )


@router.post("/admin/report-templates/{template_id}/publish")
def publish_report_template(
    request: Request,
    template_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        template = repo.find_one("report_templates", template_id)
        if not template:
            return fail(errors.NOT_FOUND, request)
        if not record_if_match_valid("report-template", template, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        validation_message = validate_report_template_record(template)
        if validation_message:
            return fail(errors.VALIDATION_ERROR, request, message=validation_message)
        for item in repo.state.get("report_templates", []):
            if item.get("id") == template_id:
                continue
            if (
                item.get("businessPackId") == template.get("businessPackId")
                and item.get("status") in {"production", "已发布"}
            ):
                item["status"] = "retired"
                bump_record_revision(item)
        template["status"] = "production"
        template["publishedAt"] = server_time()
        template["publishedReason"] = compact_plain_text(body.get("reason"), 500)
        bump_record_revision(template)
        audit_id = repo.add_audit("发布报告模板", "ReportTemplate", template_id)
        return ok(
            {"template": versioned_record("report-template", template), "auditLogId": audit_id},
            request,
        )

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"templateId": template_id, "body": body},
    )


@router.delete("/admin/report-templates/{template_id}")
def delete_report_template(
    request: Request,
    template_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        template = repo.find_one("report_templates", template_id)
        if not template:
            return fail(errors.NOT_FOUND, request)
        if not record_if_match_valid("report-template", template, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        if template.get("status") in {"production", "已发布"}:
            return fail(
                errors.VALIDATION_ERROR,
                request,
                message="生产中的报告模板不能删除，请先发布替代版本。",
            )
        repo.state["report_templates"] = [
            item for item in repo.state.get("report_templates", []) if item.get("id") != template_id
        ]
        audit_id = repo.add_audit("删除报告模板", "ReportTemplate", template_id)
        return ok({"deleted": True, "templateId": template_id, "auditLogId": audit_id}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"templateId": template_id},
    )


