"""改进任务接口：意见反馈「送平台审批」→ 平台审批 → AI 领取修复 → 上线关闭（2026-11-04）。

逻辑在 libs/improvement_tasks.py。独立 router，不往 routes.py 里加（巨石棘轮），排在主 router 前注册。

- 院管理员：POST /admin/user-feedback/{id}/escalate  把本院一条反馈送平台审批
- 平台管理员：GET/POST /platform/improvement-tasks…  审批、不采纳、合并、标上线/关闭/重新打开
- AI（用平台管理员授权的令牌）：同一组接口的 claim / release / submit，GET 单条拿任务包

写入边界：任务只在平台院；回写反馈在来源院里写，各自 save_in_current_tenant。请求收尾只落审计。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, Header, Request

from apps.api import routes as api
from apps.api.platform_routes import _guard as platform_guard
from apps.api.user_feedback_routes import COLLECTION as FEEDBACK_COLLECTION
from libs import improvement_tasks as it
from libs import institutes
from libs.contracts import errors
from libs.contracts.responses import fail, ok, server_time
from libs.db.repository import repo

improvement_router = APIRouter()
STATUS_ORDER = ["pending_review", "approved", "claimed", "in_review", "deployed", "closed", "declined", "merged"]


def _tasks(state: dict[str, Any]) -> list[dict[str, Any]]:
    return state.setdefault(it.COLLECTION, [])


def _find(state: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    return next((row for row in _tasks(state) if row.get("id") == task_id), None)


def _save(task: dict[str, Any]) -> None:
    task["updatedAt"] = server_time()
    with institutes.platform_scope():
        institutes.save_in_current_tenant(it.COLLECTION, task)


def _mirror(task: dict[str, Any], *, sources: list[dict[str, Any]] | None = None, reply: str = "") -> None:
    """把平台进度写回每条来源反馈（在来源院里写）。关闭、不采纳时顺带回复提交人。"""
    mirror = it.feedback_mirror(task)
    for src in sources if sources is not None else task.get("sources") or []:
        with institutes.tenant_scope(str(src.get("sourceTenantId"))) as state:
            row = next((item for item in state.get(FEEDBACK_COLLECTION) or [] if item.get("id") == src.get("feedbackId")), None)
            if row is None:
                continue
            row["platformTask"] = dict(mirror)
            if task.get("status") == "closed":
                row["status"] = "resolved"
            elif task.get("status") == "declined":
                row["status"] = "declined"
            elif task.get("status") in {"pending_review", "approved", "claimed", "in_review"}:
                # 重新打开（2026-11-04 审计）：已解决的反馈回到「已送平台」，旧的确认作废，
                # 上线后提交人才能再确认；否则确认接口 409、任务永远关不掉
                if row.get("status") == "resolved":
                    row["status"] = "escalated"
                row.pop("submitterConfirmation", None)
            if reply:
                row["reply"] = {"content": reply, "repliedBy": "平台", "repliedByUserId": None, "repliedAt": server_time()}
            row["updatedAt"] = server_time()
            institutes.save_in_current_tenant(FEEDBACK_COLLECTION, row)


def _institute_names() -> dict[str, str]:
    names = {institutes.platform_tenant_id(): "平台（默认院）"}
    names.update({str(row.get("id")): str(row.get("name") or row.get("id")) for row in institutes.list_institutes()})
    return names


def _view(task: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    item = it.view(task)
    item["sourceInstitutes"] = sorted({names.get(str(src.get("sourceTenantId")), str(src.get("sourceTenantId")))
                                       for src in task.get("sources") or []})
    return item


def _claim_mismatch(task: dict[str, Any], body: dict[str, Any]) -> tuple[int, str] | None:
    """回报、释放要带领取时拿到的领取号；对不上说明领取已过期、被别的 agent 领走了。"""
    claim_id = str((task.get("claim") or {}).get("id") or "")
    if claim_id and str(body.get("claimId") or "") != claim_id:
        return 409, "领取号对不上：这条任务的领取已过期并被别人领走，请重新领取。"
    return None


def _finish(request: Request, payload: dict[str, Any]):
    request.state.scoped_flush_records = dict  # 只落本次审计；任务和反馈上面已各自落库
    return ok(payload, request)


def _mutate(request: Request, task_id: str, idempotency_key: str | None, body: dict[str, Any], change):
    """平台侧对一条任务的修改：守卫 → 在平台院里改 → 落库 → 回写反馈 → 审计。change 返回 (错误, 审计动作, 回复)。"""
    if error := platform_guard(request):
        return error

    def produce():
        actor = api.request_actor_name(request)
        with institutes.platform_scope() as state:
            task = _find(state, task_id)
            if task is None:
                return fail(errors.NOT_FOUND, request, message="没有这条改进任务。")
            before = it.effective_status(task)
            failure, action, reply = change(state, task, actor)
            if failure:
                return fail(errors.CONFLICT if failure[0] == 409 else errors.VALIDATION_ERROR, request,
                            http_status=failure[0], message=failure[1])
            task.setdefault("history", []).append(it.history_entry(action, actor, before=before, after=task["status"],
                                                                    note=str(body.get("note") or body.get("reason") or "")[:500]))
            _save(task)
            snapshot = repo.clone(task)
        _mirror(snapshot, reply=reply)
        audit_id = repo.add_audit(f"改进任务：{action}", "ImprovementTask", task_id,
                                  before={"status": before}, after={"status": snapshot["status"]})
        return _finish(request, {"task": _view(snapshot, _institute_names()), "auditLogId": audit_id})

    return api.idempotent(request, idempotency_key, produce, fingerprint_source={"taskId": task_id, "body": body})


# ── 院管理员：送平台审批 ─────────────────────────────────────────────────────────

@improvement_router.post("/admin/user-feedback/{feedback_id}/escalate")
def escalate_user_feedback(
    request: Request,
    feedback_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    actor_role, error = api.effective_role_for_request(request)
    if error:
        return error
    if actor_role != "admin":
        return fail(errors.FORBIDDEN, request, message="只有管理员可以把反馈送平台审批。", http_status=403)
    tenant_id = api.request_tenant_id(request)
    row = next((item for item in repo.state.get(FEEDBACK_COLLECTION) or []
                if item.get("id") == feedback_id and api.tenant_id_for_record(item) == tenant_id), None)
    if not row:
        return fail(errors.NOT_FOUND, request)
    if row.get("status") in {"resolved", "declined", "escalated"}:
        return fail(errors.CONFLICT, request, http_status=409, message="这条反馈已处理或已送平台，不能再送。")
    scope = str(body.get("scope") or "public")
    if scope not in it.SCOPES:
        return fail(errors.VALIDATION_ERROR, request, message="请选择：公共改进，或各院口径不一。",
                    data={"allowedScopes": sorted(it.SCOPES)})
    note = it.text(body.get("note"), "note")

    def produce():
        actor = api.request_actor_name(request)
        source = it.source_from_feedback(row, tenant_id, note=note, actor=actor)
        task = it.new_task(source, scope=scope, actor=actor)
        with institutes.platform_scope() as state:
            _tasks(state).insert(0, task)
            institutes.save_in_current_tenant(it.COLLECTION, task)
        row.update({"status": "escalated", "platformTask": it.feedback_mirror(task), "updatedAt": server_time(),
                    "escalation": {"by": actor, "at": server_time(), "scope": scope, "note": note}})
        audit_id = repo.add_audit("意见反馈送平台审批", "UserFeedback", feedback_id, after={"taskId": task["id"], "scope": scope})
        request.state.scoped_flush_records = lambda: {FEEDBACK_COLLECTION: [repo.clone(row)]}
        return ok({"feedback": repo.clone(row), "taskId": task["id"], "auditLogId": audit_id}, request)

    return api.idempotent(request, idempotency_key, produce, fingerprint_source={"feedbackId": feedback_id, "body": body})


# ── 平台管理员：队列与审批 ───────────────────────────────────────────────────────

@improvement_router.get("/platform/improvement-tasks")
def list_improvement_tasks(request: Request, status: str | None = None, scope: str | None = None):
    if error := platform_guard(request):
        return error
    names = _institute_names()
    with institutes.platform_scope() as state:
        rows = [_view(task, names) for task in _tasks(state)]
    counts = {key: sum(1 for row in rows if row["status"] == key) for key in it.STATUSES}
    if status:
        rows = [row for row in rows if row["status"] == status]
    if scope:
        rows = [row for row in rows if row.get("scope") == scope]
    # 先按状态，再按优先级，同优先级多个院报的排前面：几个院都遇到的事更该先修
    rows.sort(key=lambda row: (STATUS_ORDER.index(row["status"]) if row["status"] in STATUS_ORDER else 99,
                               str(row.get("priority") or "P9"), -row["sourceTenantCount"], str(row.get("createdAt") or "")))
    return ok({"items": rows, "statusCounts": counts, "statuses": it.STATUSES, "scopes": it.SCOPES,
               "priorities": it.PRIORITIES}, request)


@improvement_router.get("/platform/improvement-tasks/{task_id}")
def get_improvement_task(request: Request, task_id: str):
    """单条任务；`packet` 就是给 AI 的任务包（aicheck-feedback skill 的 tasks show）。"""
    if error := platform_guard(request):
        return error
    with institutes.platform_scope() as state:
        task = _find(state, task_id)
        if task is None:
            return fail(errors.NOT_FOUND, request, message="没有这条改进任务。")
        snapshot = repo.clone(task)
    return ok({"task": _view(snapshot, _institute_names()), "packet": it.packet(snapshot)}, request)


@improvement_router.post("/platform/improvement-tasks/{task_id}/approve")
def approve_improvement_task(request: Request, task_id: str, body: dict[str, Any] = Body(default_factory=dict),
                             idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def change(state, task, actor):
        if it.effective_status(task) not in {"pending_review", "approved"}:
            return (409, "只有待平台审批或待开发的任务能审批、改任务描述。"), "", ""
        statement, criteria = it.text(body.get("taskStatement"), "taskStatement"), it.text(body.get("acceptanceCriteria"), "acceptanceCriteria")
        if not statement or not criteria:
            return (400, "请写任务描述和验收标准：AI 只按这两段干活，不按用户原话。"), "", ""
        priority, scope = str(body.get("priority") or task.get("priority") or "P2"), str(body.get("scope") or task.get("scope"))
        if priority not in it.PRIORITIES or scope not in it.SCOPES:
            return (400, "优先级或归属不支持。"), "", ""
        title = it.text(body.get("title"), "title") or str(task.get("title") or "")
        if not title:
            return (400, "请写一个标题：会显示给提交人，不要写工程名、人名。"), "", ""
        task.update({"status": "approved", "taskStatement": statement, "acceptanceCriteria": criteria, "priority": priority,
                     "scope": scope, "title": title,
                     "approvedBy": actor, "approvedAt": server_time()})
        return None, "审批通过", ""
    return _mutate(request, task_id, idempotency_key, body, change)


@improvement_router.post("/platform/improvement-tasks/{task_id}/decline")
def decline_improvement_task(request: Request, task_id: str, body: dict[str, Any] = Body(default_factory=dict),
                             idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def change(state, task, actor):
        reason = it.text(body.get("reason"), "note")
        if not reason:
            return (400, "暂不采纳要写理由，会回复给提交人。"), "", ""
        if it.effective_status(task) not in {"pending_review", "approved"}:
            return (409, "开发中或已上线的任务不能直接不采纳；先重新打开。"), "", ""
        task.update({"status": "declined", "claim": None, "declineReason": reason})
        return None, "暂不采纳", f"平台暂不采纳：{reason}"
    return _mutate(request, task_id, idempotency_key, body, change)


@improvement_router.post("/platform/improvement-tasks/{task_id}/merge")
def merge_improvement_task(request: Request, task_id: str, body: dict[str, Any] = Body(default_factory=dict),
                           idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    """重复的反馈合并到一条任务：来源都挂到目标任务上，目标的来源院数变多，排序靠前。"""
    target_id = str(body.get("intoTaskId") or "")
    moved: list[dict[str, Any]] = []
    target_snapshot: dict[str, Any] = {}

    def change(state, task, actor):
        target = _find(state, target_id)
        if target is None or target_id == task_id:
            return (400, "请选择要合并到的另一条任务。"), "", ""
        open_states = {"pending_review", "approved"}
        if it.effective_status(task) not in open_states or it.effective_status(target) not in open_states | {"claimed"}:
            return (409, "只有还没开始修的任务能合并。"), "", ""
        seen = {(src.get("sourceTenantId"), src.get("feedbackId")) for src in target.get("sources") or []}
        for src in task.get("sources") or []:
            if (src.get("sourceTenantId"), src.get("feedbackId")) not in seen:
                target.setdefault("sources", []).append(src)
                moved.append(src)
        target.setdefault("history", []).append(it.history_entry("并入同类反馈", actor, note=f"来自 {task_id}"))
        _save(target)
        target_snapshot.update(repo.clone(target))
        task.update({"status": "merged", "mergedInto": target_id})
        return None, "合并到其他任务", ""

    response = _mutate(request, task_id, idempotency_key, body, change)
    if target_snapshot:
        _mirror(target_snapshot, sources=moved)
    return response


@improvement_router.post("/platform/improvement-tasks/{task_id}/status")
def set_improvement_task_status(request: Request, task_id: str, body: dict[str, Any] = Body(default_factory=dict),
                                idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    """人工推进：已合并部署 → 已上线；确认解决 → 关闭；审核不通过或上线后没解决 → 重新打开（待开发）。"""
    def change(state, task, actor):
        target = str(body.get("status") or "")
        if target not in it.MANUAL_TRANSITIONS or it.effective_status(task) not in it.MANUAL_TRANSITIONS[target]:
            return (409, f"不能从「{it.STATUSES.get(it.effective_status(task))}」改成这个状态。"), "", ""
        if target == "approved" and not str(body.get("note") or "").strip():
            return (400, "重新打开要写原因，AI 会照着重修。"), "", ""
        task["status"] = target
        if target == "approved":
            task.update({"claim": None, "reopenNote": it.redact(it.text(body.get("note"), "note"))})
            for src in task.get("sources") or []:
                src.pop("submitterConfirmation", None)
        reply = f"平台已修复并上线：{task.get('title') or task_id}" if target == "closed" else ""
        return None, {"deployed": "标为已上线", "closed": "关闭", "approved": "重新打开"}[target], reply
    return _mutate(request, task_id, idempotency_key, body, change)


# ── AI：领取、释放、回报 ─────────────────────────────────────────────────────────

@improvement_router.post("/platform/improvement-tasks/{task_id}/claim")
def claim_improvement_task(request: Request, task_id: str, body: dict[str, Any] = Body(default_factory=dict),
                           idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def change(state, task, actor):
        if it.effective_status(task) != "approved":
            return (409, f"这条任务现在是「{it.STATUSES.get(it.effective_status(task))}」，不能领取。"), "", ""
        # 领取号（2026-11-04 审计）：回报、释放要带同一个号，领取过期被别人领走后，旧 agent 的回报会被拒
        task.update({"status": "claimed", "claim": {"id": f"CLM-{uuid4().hex[:12].upper()}", "by": actor,
                                                    "agent": it.text(body.get("agent"), "agent") or "agent",
                                                    "at": server_time(), "expiresAt": it.now_plus(it.CLAIM_SECONDS)}})
        return None, "AI 领取", ""
    return _mutate(request, task_id, idempotency_key, body, change)


@improvement_router.post("/platform/improvement-tasks/{task_id}/release")
def release_improvement_task(request: Request, task_id: str, body: dict[str, Any] = Body(default_factory=dict),
                             idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def change(state, task, actor):
        if task.get("status") != "claimed":
            return (409, "这条任务没有被领取。"), "", ""
        if failure := _claim_mismatch(task, body):
            return failure, "", ""
        task.update({"status": "approved", "claim": None})
        return None, "释放", ""
    return _mutate(request, task_id, idempotency_key, body, change)


@improvement_router.post("/platform/improvement-tasks/{task_id}/submit")
def submit_improvement_task(request: Request, task_id: str, body: dict[str, Any] = Body(default_factory=dict),
                            idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def change(state, task, actor):
        if task.get("status") != "claimed":
            return (409, "先领取再回报；领取超时被别人领走的要重新领。"), "", ""
        if failure := _claim_mismatch(task, body):
            return failure, "", ""
        pr_url = it.text(body.get("prUrl"), "prUrl")
        tests = it.text(body.get("tests"), "tests")
        if not pr_url or not tests:
            return (400, "回报要带 PR 链接和测试结果。"), "", ""
        task.update({"status": "in_review", "claim": None, "result": {
            "prUrl": pr_url, "commit": it.text(body.get("commit"), "commit"), "tests": tests,
            "note": it.text(body.get("note"), "note"), "by": actor, "at": server_time()}})
        return None, "AI 回报修改", ""
    return _mutate(request, task_id, idempotency_key, body, change)


# ── 提交人：上线后确认解决，或说明仍有问题 ─────────────────────────────────────────

@improvement_router.post("/user-feedback/{feedback_id}/confirm")
def confirm_user_feedback(
    request: Request,
    feedback_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """提交人确认（2026-11-04）：「已解决」→ 这条反馈关闭，任务的来源都确认了任务就自动关闭；
    「仍有问题」→ 写明哪里不对，任务重新打开回到待开发，原因脱敏后给 AI 重修。"""
    _, error = api.effective_role_for_request(request)
    if error:
        return error
    tenant_id, user_id = api.request_tenant_id(request), api.request_user_id(request)
    row = next((item for item in repo.state.get(FEEDBACK_COLLECTION) or []
                if item.get("id") == feedback_id and api.tenant_id_for_record(item) == tenant_id), None)
    if not row or (row.get("submittedBy") or {}).get("userId") != user_id:
        return fail(errors.NOT_FOUND, request)
    task_id = str((row.get("platformTask") or {}).get("taskId") or "")
    if row.get("status") != "escalated" or (row.get("platformTask") or {}).get("status") != "deployed" or not task_id:
        return fail(errors.CONFLICT, request, http_status=409, message="平台标为已上线后才能确认。")
    resolved = bool(body.get("resolved"))
    note = it.text(body.get("note"), "note")
    if not resolved and not note:
        return fail(errors.VALIDATION_ERROR, request, message="请写一句哪里还不对，平台会照着重修。")

    def produce():
        with institutes.platform_scope() as state:
            task = _find(state, task_id)
            if task is None or it.effective_status(task) != "deployed":
                return fail(errors.CONFLICT, request, http_status=409, message="平台的任务状态已变化，请刷新。")
            for src in task.get("sources") or []:
                if src.get("sourceTenantId") == tenant_id and src.get("feedbackId") == feedback_id:
                    src["submitterConfirmation"] = {"resolved": resolved, "at": server_time(), "note": it.redact(note)}
            if resolved:
                action = "提交人确认已解决"
                if all((src.get("submitterConfirmation") or {}).get("resolved") for src in task.get("sources") or []):
                    task["status"], action = "closed", "提交人都确认已解决，自动关闭"
            else:
                task.update({"status": "approved", "claim": None, "reopenNote": f"提交人反馈仍有问题：{it.redact(note)}"})
                action = "提交人说仍有问题，重新打开"
            # 平台记录里只写「提交人」，不写姓名：送平台时承诺不带提交人姓名
            task.setdefault("history", []).append(it.history_entry(action, "提交人", after=task["status"], note=it.redact(note)))
            _save(task)
            snapshot = repo.clone(task)
        # 「已解决」只记确认，反馈等任务关闭时才变成已解决（2026-11-04 审计：提前标已解决会被院管理员再送平台）
        row["submitterConfirmation"] = {"resolved": resolved, "at": server_time(), "note": note}
        institutes.save_in_current_tenant(FEEDBACK_COLLECTION, row)
        closed_reply = f"平台已修复并上线：{snapshot.get('title') or task_id}" if snapshot["status"] == "closed" else ""
        _mirror(snapshot, reply=closed_reply)
        audit_id = repo.add_audit(f"意见反馈：{action}", "UserFeedback", feedback_id, after={"taskId": task_id, "resolved": resolved})
        return _finish(request, {"feedback": repo.clone(row), "taskStatus": snapshot["status"], "auditLogId": audit_id})

    return api.idempotent(request, idempotency_key, produce, fingerprint_source={"feedbackId": feedback_id, "body": body})
