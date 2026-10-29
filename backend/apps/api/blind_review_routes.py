"""P12 F4：盲审任务的抽样、领取、判定——独立 router，不进 routes.py 棘轮。"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Body, Header, Request

from apps.api.routes import (
    document_read_error, fde_error_unless_allowed, idempotent, request_actor_name,
    request_tenant_id, tenant_id_for_record,
)
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.repository import flush_state, repo
from libs.feedback.blind_review import (
    DEFAULT_SAMPLE_RATIO,
    blind_task_view,
    record_blind_decision,
    rubber_stamp_index,
    sample_blind_review_tasks,
)

blind_review_router = APIRouter()


@blind_review_router.post("/fde/blind-review/sample")
def fde_blind_review_sample(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:feedback:triage")
        if role_error:
            return role_error
        ratio = float(body.get("ratio") or DEFAULT_SAMPLE_RATIO)
        window_days = body.get("windowDays", 7)
        tasks = sample_blind_review_tasks(
            repo.state,
            ratio=ratio,
            seed=body.get("seed"),
            window_days=int(window_days) if window_days else None,
            created_by=request_actor_name(request),
        )
        if tasks:
            repo.add_audit("FDE 抽样盲审任务", "BlindReviewBatch", tasks[0]["batchId"])
            flush_state(selected_state_keys={"blind_review_tasks", "audit_logs"})
        return ok({"tasks": [blind_task_view(task) for task in tasks], "sampled": len(tasks)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@blind_review_router.get("/fde/blind-review/tasks")
def fde_blind_review_tasks(request: Request, status: str | None = None, reveal: bool = False):
    _, role_error = fde_error_unless_allowed(request, "fde:feedback:view")
    if role_error:
        return role_error
    items = [item for item in repo.state.get("blind_review_tasks") or [] if isinstance(item, dict)]
    if status:
        items = [item for item in items if item.get("status") == status]
    # reveal 只对已完成任务生效：未判的任务无论谁看都不能露 AI 结论
    return ok(
        {
            "tasks": [blind_task_view(item, reveal=bool(reveal and item.get("status") == "done")) for item in items],
            "rubberStampIndex": rubber_stamp_index(repo.state),
        },
        request,
    )


@blind_review_router.get("/fde/blind-review/tasks/{task_id}/materials")
def fde_blind_review_materials(request: Request, task_id: str):
    """Only source-file metadata from the sampled run; never return review conclusions."""
    _, role_error = fde_error_unless_allowed(request, "fde:feedback:view")
    if role_error:
        return role_error
    task = repo.find_one("blind_review_tasks", task_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    run = repo.find_one("ai_runs", task.get("aiRunId"))
    snapshot = (run or {}).get("inputDocumentVersionIds")
    scope_source = "run_snapshot"
    if not run or run.get("projectId") != task.get("projectId") or str(run.get("nodeId")) != str(task.get("nodeId")) or not isinstance(snapshot, list):
        snapshot = []
        scope_source = "unavailable"
    materials = []
    unavailable_count = 0
    for version_id in dict.fromkeys(str(value) for value in snapshot if value):
        version = repo.find_one("versions", version_id)
        document = repo.find_one("documents", (version or {}).get("documentId"))
        if (not version or not document
                or tenant_id_for_record(version) != request_tenant_id(request)
                or document_read_error(request, str(task.get("projectId")), document) is not None):
            unavailable_count += 1
            continue
        project_id = quote(str(task["projectId"]), safe="")
        document_id = quote(str(document["id"]), safe="")
        materials.append({
            "documentId": document["id"],
            "documentVersionId": version["id"],
            "fileName": version.get("fileName") or document.get("fileName") or version["id"],
            "fileType": version.get("fileType") or document.get("fileType"),
            "originalUrl": f"/api/projects/{project_id}/documents/{document_id}/original?versionId={quote(version_id, safe='')}&disposition=inline",
            "downloadUrl": f"/api/projects/{project_id}/documents/{document_id}/original?versionId={quote(version_id, safe='')}&disposition=attachment",
        })
    return ok({
        "taskId": task_id,
        "scopeSource": scope_source,
        "materials": materials,
        "unavailableCount": unavailable_count,
        "unavailableReason": "该任务缺少当时的资料版本快照，无法确认盲审依据，请联系管理员核实后重新抽样。" if scope_source == "unavailable" else "",
    }, request)


@blind_review_router.post("/fde/blind-review/tasks/{task_id}/decision")
def fde_blind_review_decision(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:feedback:triage")
        if role_error:
            return role_error
        task = repo.find_one("blind_review_tasks", task_id)
        if not task:
            return fail(errors.NOT_FOUND, request)
        outcome = record_blind_decision(
            task,
            result=str(body.get("result") or "").strip(),
            reviewer_name=body.get("reviewerName") or request_actor_name(request),
            comment=body.get("comment"),
        )
        if isinstance(outcome, str):
            return fail(errors.VALIDATION_ERROR, request, message=outcome)
        repo.add_audit("盲审判定", "BlindReviewTask", task_id)
        flush_state(selected_state_keys={"blind_review_tasks", "audit_logs"})
        return ok({"task": blind_task_view(task, reveal=True), "rubberStampIndex": rubber_stamp_index(repo.state)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"taskId": task_id, "body": body})
