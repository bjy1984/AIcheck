"""平台规则送达既有项目（2026-11-04，意见反馈审批方案第三阶段）。差异计算在 libs/business_pack_diff.py。

- GET  /admin/business-pack/updates          本院各项目冻结的业务包副本和现行版本差在哪、影响哪些节点、
                                              这些节点上已有几条结论（升级后要重审才会按新规则判）
- POST /admin/business-pack/updates/apply    {projectIds: [...]}：选中的项目升级到现行业务包
                                              （与 /projects/{id}/business-pack/apply 相同步骤；历史运行不受影响）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, Request

from apps.api import routes as api
from libs.business_pack import DEFAULT_BUSINESS_PACK_ID, business_pack_snapshot, load_business_pack
from libs.business_pack_diff import pack_diff
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.repository import repo
from libs.probe_projects import is_probe_project

pack_update_router = APIRouter()
DONE_STATUSES = {"waiting_human_review", "accepted_by_human", "edited_by_human", "rejected_by_human", "completed"}


def _admin_error(request: Request):
    actor_role, error = api.effective_role_for_request(request)
    if error:
        return error
    if actor_role != "admin":
        return fail(errors.FORBIDDEN, request, message="只有管理员可以升级项目的业务规则。", http_status=403)
    return None


def _update_info(project: dict[str, Any], packs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pack_id = str(project.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID)
    if pack_id not in packs:
        packs[pack_id] = load_business_pack(pack_id)
    current = packs[pack_id]
    stored = project.get("businessPackSnapshot")
    frozen = isinstance(stored, dict)
    diff = pack_diff(stored if frozen else current, current)
    affected = set(diff["affectedNodeIds"])
    conclusions = sum(
        1 for run in repo.state.get("review_runs") or []
        if run.get("projectId") == project.get("id") and int(run.get("nodeId") or 0) in affected
        and str(run.get("status") or "") in DONE_STATUSES
    )
    return {
        "projectId": project.get("id"),
        "projectName": project.get("name"),
        "projectStatus": project.get("status"),
        "businessPackId": pack_id,
        "frozenVersion": (stored or {}).get("version") if frozen else current.get("version"),
        "currentVersion": current.get("version"),
        "snapshotHash": project.get("businessPackSnapshotHash"),
        "currentHash": current.get("snapshotHash"),
        "upToDate": (not frozen) or project.get("businessPackSnapshotHash") == current.get("snapshotHash") or diff["upToDate"],
        "diff": diff,
        "affectedConclusionCount": conclusions,
    }


@pack_update_router.get("/admin/business-pack/updates")
def list_business_pack_updates(request: Request):
    if error := _admin_error(request):
        return error
    packs: dict[str, dict[str, Any]] = {}
    items = [_update_info(project, packs) for project in repo.state.get("projects") or []
             if isinstance(project, dict) and not is_probe_project(project)]
    items.sort(key=lambda row: (row["upToDate"], -len(row["diff"]["affectedNodeIds"]), str(row["projectName"] or "")))
    return ok({"items": items, "outdatedCount": sum(1 for row in items if not row["upToDate"])}, request)


@pack_update_router.post("/admin/business-pack/updates/apply")
def apply_business_pack_updates(request: Request, body: dict[str, Any] = Body(default_factory=dict),
                                idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if error := _admin_error(request):
        return error
    project_ids = [str(item) for item in body.get("projectIds") or [] if item]
    if not project_ids:
        return fail(errors.VALIDATION_ERROR, request, message="请选择要升级的项目。")

    def produce():
        packs: dict[str, dict[str, Any]] = {}
        results = []
        for project_id in project_ids:
            project = repo.require_project(project_id)
            if not project:
                results.append({"projectId": project_id, "applied": False, "reason": "项目不存在"})
                continue
            if api.mutation_guard(request, project_id, if_match="*"):
                results.append({"projectId": project_id, "applied": False, "reason": "没有权限升级这个项目"})
                continue
            info = _update_info(project, packs)
            pack = packs[info["businessPackId"]]
            project.update({
                "businessPackId": pack["id"],
                "businessPackVersion": pack["version"],
                "domainType": pack["domainType"],
                "businessPackSnapshotHash": pack["snapshotHash"],
                "businessPackSnapshot": business_pack_snapshot(pack),
            })
            nodes, requirements = api.attach_business_pack_project_scaffold(project, pack)
            repo.touch_project(project_id)
            repo.add_audit("升级项目业务规则", "BusinessPack", pack["id"], project_id=project_id,
                           before={"version": info["frozenVersion"], "hash": info["snapshotHash"]},
                           after={"version": pack["version"], "hash": pack["snapshotHash"]})
            results.append({"projectId": project_id, "applied": True, "fromVersion": info["frozenVersion"],
                            "toVersion": pack["version"], "affectedNodeIds": info["diff"]["affectedNodeIds"],
                            "affectedConclusionCount": info["affectedConclusionCount"],
                            "createdNodeCount": nodes, "createdRequirementCount": requirements})
        return ok({"results": results, "appliedCount": sum(1 for row in results if row["applied"])}, request)

    return api.idempotent(request, idempotency_key, produce, fingerprint_source={"body": body})
