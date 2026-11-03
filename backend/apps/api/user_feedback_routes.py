"""意见反馈：各角色把使用不便、审计不准等意见提给管理员；管理员查看、回复、改状态，提交人能看到回复。

和 ai_feedback 分开存：那是挂在某次 AI 复核上的纠错，进 FDE 分诊和评测集；这里是给人看的意见箱，
内容是自由文字，不该混进评测数据。独立 router，不往 routes.py 里加（巨石棘轮）。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, Header, Request

from apps.api import routes as api
from libs.contracts import errors
from libs.contracts.responses import fail, ok, server_time
from libs.db.repository import repo

user_feedback_router = APIRouter()

COLLECTION = "user_feedback"
CATEGORIES = {
    "usability": "使用不便",
    "audit_accuracy": "审计不准确",
    "bug": "功能异常",
    "suggestion": "功能建议",
    "other": "其他",
}
STATUSES = {
    "open": "待处理",
    "acknowledged": "已受理",
    "resolved": "已解决",
    "declined": "暂不采纳",
}
CONTENT_MIN, CONTENT_MAX = 5, 2000
REPLY_MAX = 1000
# 只收这几项上下文：说清是在哪一页、哪个工程哪个节点、哪次 AI 复核遇到的，管理员才好复现
CONTEXT_FIELDS = {"page": 300, "pageTitle": 80, "projectId": 80, "nodeId": 20, "aiRunId": 80}


def _rows() -> list[dict[str, Any]]:
    return repo.state.setdefault(COLLECTION, [])


def _line(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _paragraphs(value: Any, limit: int) -> str:
    # 正文和回复保留换行：意见常常是分条写的
    return str(value or "").strip()[:limit]


def _view(row: dict[str, Any]) -> dict[str, Any]:
    item = repo.clone(row)
    item["categoryLabel"] = CATEGORIES.get(str(item.get("category")), "其他")
    item["statusLabel"] = STATUSES.get(str(item.get("status")), "待处理")
    return item


def _own(request: Request, row: dict[str, Any]) -> bool:
    return api.tenant_id_for_record(row) == api.request_tenant_id(request)


def _flush(request: Request, row: dict[str, Any]) -> None:
    # 只落这一条和本次审计：意见箱的写入不该触发整库落盘
    request.state.scoped_flush_records = lambda: {COLLECTION: [repo.clone(row)]}


@user_feedback_router.post("/user-feedback")
def submit_user_feedback(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    role, error = api.effective_role_for_request(request)
    if error:
        return error
    user_id = api.request_user_id(request)
    if not role or not user_id:
        return fail(errors.FORBIDDEN, request, message="请先登录再提交意见反馈。", http_status=403)
    category = str(body.get("category") or "")
    if category not in CATEGORIES:
        return fail(errors.VALIDATION_ERROR, request, message="请选择反馈类型。", data={"allowedCategories": sorted(CATEGORIES)})
    content = _paragraphs(body.get("content"), CONTENT_MAX)
    if len(content) < CONTENT_MIN:
        return fail(errors.VALIDATION_ERROR, request, message=f"请把问题写清楚一些（至少 {CONTENT_MIN} 个字）。")
    raw_context = body.get("context") if isinstance(body.get("context"), dict) else {}
    context = {key: _line(raw_context.get(key), limit) for key, limit in CONTEXT_FIELDS.items() if raw_context.get(key)}

    def produce():
        now = server_time()
        user = getattr(request.state, "auth_user", None) or {}
        row = {
            "id": f"UFB-{uuid4().hex[:10].upper()}",
            "tenantId": api.request_tenant_id(request),
            "category": category,
            "content": content,
            "context": context,
            "status": "open",
            "submittedBy": {
                "userId": user_id,
                "username": str(user.get("username") or ""),
                "name": api.request_actor_name(request),
                "role": role,
                "orgUnitName": str(user.get("orgUnitName") or ""),
            },
            "reply": None,
            "createdAt": now,
            "updatedAt": now,
        }
        _rows().insert(0, row)
        audit_id = repo.add_audit("提交意见反馈", "UserFeedback", row["id"], project_id=context.get("projectId") or None)
        _flush(request, row)
        return ok({"feedback": _view(row), "auditLogId": audit_id}, request)

    return api.idempotent(request, idempotency_key, produce, fingerprint_source={"body": body})


@user_feedback_router.get("/user-feedback/mine")
def my_user_feedback(request: Request):
    _, error = api.effective_role_for_request(request)
    if error:
        return error
    user_id = api.request_user_id(request)
    if not user_id:
        return fail(errors.FORBIDDEN, request, message="请先登录。", http_status=403)
    items = [_view(row) for row in _rows() if _own(request, row) and (row.get("submittedBy") or {}).get("userId") == user_id]
    return ok({"items": items, "categories": CATEGORIES, "statuses": STATUSES}, request)


@user_feedback_router.get("/admin/user-feedback")
def admin_user_feedback(request: Request, status: str | None = None, category: str | None = None, role: str | None = None):
    actor_role, error = api.effective_role_for_request(request)
    if error:
        return error
    if actor_role != "admin":
        return fail(errors.FORBIDDEN, request, message="只有管理员可以查看全部意见反馈。", http_status=403)
    rows = [row for row in _rows() if _own(request, row)]
    counts = {key: sum(1 for row in rows if row.get("status") == key) for key in STATUSES}
    if status:
        rows = [row for row in rows if row.get("status") == status]
    if category:
        rows = [row for row in rows if row.get("category") == category]
    if role:
        rows = [row for row in rows if (row.get("submittedBy") or {}).get("role") == role]
    return ok({"items": [_view(row) for row in rows], "statusCounts": counts,
               "categories": CATEGORIES, "statuses": STATUSES}, request)


@user_feedback_router.post("/admin/user-feedback/{feedback_id}/reply")
def reply_user_feedback(
    request: Request,
    feedback_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    actor_role, error = api.effective_role_for_request(request)
    if error:
        return error
    if actor_role != "admin":
        return fail(errors.FORBIDDEN, request, message="只有管理员可以处理意见反馈。", http_status=403)
    row = next((item for item in _rows() if item.get("id") == feedback_id and _own(request, item)), None)
    if not row:
        return fail(errors.NOT_FOUND, request)
    status = str(body.get("status") or "")
    if status not in STATUSES:
        return fail(errors.VALIDATION_ERROR, request, message="处理状态不支持。", data={"allowedStatuses": sorted(STATUSES)})
    reply = _paragraphs(body.get("reply"), REPLY_MAX)
    if status in {"resolved", "declined"} and not reply:
        # 关掉一条意见却不说为什么，提交人只看到「已解决 / 暂不采纳」，等于没回
        return fail(errors.VALIDATION_ERROR, request, message="标为已解决或暂不采纳时，请写一句回复给提交人。")

    def produce():
        before = {"status": row.get("status"), "reply": repo.clone(row.get("reply"))}
        now = server_time()
        row["status"] = status
        if reply:
            row["reply"] = {"content": reply, "repliedBy": api.request_actor_name(request),
                            "repliedByUserId": api.request_user_id(request), "repliedAt": now}
        row["updatedAt"] = now
        audit_id = repo.add_audit("处理意见反馈", "UserFeedback", feedback_id, before=before,
                                  after={"status": status, "reply": repo.clone(row.get("reply"))})
        _flush(request, row)
        return ok({"feedback": _view(row), "auditLogId": audit_id}, request)

    return api.idempotent(request, idempotency_key, produce,
                          fingerprint_source={"feedbackId": feedback_id, "body": body})
