"""平台规则送达既有项目（2026-11-04，意见反馈审批方案第三阶段）。差异计算在 libs/business_pack_diff.py。

- GET  /admin/business-pack/updates          本院各项目冻结的业务包副本和现行版本差在哪、影响哪些节点、
                                              这些节点上已有几条结论（升级后要重审才会按新规则判）
- POST /admin/business-pack/updates/apply    {projectIds: [...]}：选中的项目升级到现行业务包
                                              （与 /projects/{id}/business-pack/apply 相同步骤；历史运行不受影响）
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Header, Request

from apps.api import routes as api
from libs.business_pack import (
    DEFAULT_BUSINESS_PACK_ID,
    build_project_requirements,
    business_pack_snapshot,
    load_business_pack,
)
from libs.business_pack_diff import no_changes, pack_diff, reconcile_requirements
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


def _latest_done_runs(project_id: Any) -> dict[int, dict[str, Any]]:
    """每个节点最近一次完成的复核：「已有结论」只数现行的，被后来的运行取代的历史结论不算（2026-11-04 审计）。"""
    latest: dict[int, dict[str, Any]] = {}
    for run in repo.state.get("review_runs") or []:
        if run.get("projectId") != project_id or str(run.get("status") or "") not in DONE_STATUSES:
            continue
        node = int(run.get("nodeId") or 0)
        stamp = str(run.get("finishedAt") or run.get("updatedAt") or run.get("createdAt") or "")
        if node not in latest or stamp > str(latest[node].get("finishedAt") or latest[node].get("updatedAt")
                                              or latest[node].get("createdAt") or ""):
            latest[node] = run
    return latest


def _broken_info(project: dict[str, Any], pack_id: str, reason: str) -> dict[str, Any]:
    """业务包读不出来的项目单独一行说明，别让整页 500（2026-11-04 审计）。"""
    return {"projectId": project.get("id"), "projectName": project.get("name"), "projectStatus": project.get("status"),
            "businessPackId": pack_id, "frozenVersion": None, "currentVersion": None, "snapshotHash": None,
            "currentHash": None, "upToDate": False, "archived": project.get("status") == "已归档", "upgradable": False,
            "error": reason, "diff": no_changes({}) | {"upToDate": False}, "affectedConclusionCount": 0}


def _update_info(project: dict[str, Any], packs: dict[str, dict[str, Any] | str]) -> dict[str, Any]:
    pack_id = str(project.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID)
    if pack_id not in packs:
        try:
            packs[pack_id] = load_business_pack(pack_id)
        except Exception as exc:  # noqa: BLE001 -- one bad pack id must not break the whole page
            packs[pack_id] = f"业务包 {pack_id} 读不出来：{exc}"
    if isinstance(packs[pack_id], str):
        return _broken_info(project, pack_id, str(packs[pack_id]))
    current = packs[pack_id]
    stored = project.get("businessPackSnapshot")
    frozen = isinstance(stored, dict)
    archived = project.get("status") == "已归档"
    # 指纹不同就算旧版（2026-11-04 审计）：原来差异算不出来时也判「已是最新」，升级入口就没了
    up_to_date = (not frozen) or project.get("businessPackSnapshotHash") == current.get("snapshotHash")
    # 已是最新的不用算差异（一份约 11 毫秒，项目多了就是整页的大头）
    diff = no_changes(current) if up_to_date else pack_diff(stored, current)
    affected = set(diff["affectedNodeIds"])
    conclusions = sum(1 for node in _latest_done_runs(project.get("id")) if node in affected) if affected else 0
    return {
        "projectId": project.get("id"),
        "projectName": project.get("name"),
        "projectStatus": project.get("status"),
        "businessPackId": pack_id,
        "frozenVersion": (stored or {}).get("version") if frozen else current.get("version"),
        "currentVersion": current.get("version"),
        "snapshotHash": project.get("businessPackSnapshotHash"),
        "currentHash": current.get("snapshotHash"),
        "upToDate": up_to_date,
        "archived": archived,
        "upgradable": not up_to_date and not archived,
        "diff": diff,
        "affectedConclusionCount": conclusions,
    }


def _guard_reason(guard: Any) -> str:
    try:
        return str(json.loads(guard.body).get("message") or "") or "没有权限升级这个项目"
    except (AttributeError, ValueError):
        return "没有权限升级这个项目"


@pack_update_router.get("/admin/business-pack/updates")
def list_business_pack_updates(request: Request):
    if error := _admin_error(request):
        return error
    packs: dict[str, dict[str, Any]] = {}
    items = [_update_info(project, packs) for project in repo.state.get("projects") or []
             if isinstance(project, dict) and not is_probe_project(project)]
    items.sort(key=lambda row: (not row["upgradable"], row["upToDate"], -len(row["diff"]["affectedNodeIds"]),
                                str(row["projectName"] or "")))
    # 已归档的项目只读，升级不了，不算进「可升级」
    return ok({"items": items, "outdatedCount": sum(1 for row in items if row["upgradable"])}, request)


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
            if guard := api.mutation_guard(request, project_id, if_match="*"):
                results.append({"projectId": project_id, "applied": False, "reason": _guard_reason(guard)})
                continue
            info = _update_info(project, packs)
            if info.get("error"):
                results.append({"projectId": project_id, "applied": False, "reason": info["error"]})
                continue
            if info["upToDate"]:
                results.append({"projectId": project_id, "applied": False, "reason": "已是现行规则"})
                continue
            pack = packs[info["businessPackId"]]
            project.update({
                "businessPackId": pack["id"],
                "businessPackVersion": pack["version"],
                "domainType": pack["domainType"],
                "businessPackSnapshotHash": pack["snapshotHash"],
                "businessPackSnapshot": business_pack_snapshot(pack),
            })
            nodes, requirements = api.attach_business_pack_project_scaffold(project, pack)
            reconciled = reconcile_requirements(repo.state, project_id, build_project_requirements(pack, project_id=project_id))
            repo.touch_project(project_id)
            repo.add_audit("升级项目业务规则", "BusinessPack", pack["id"], project_id=project_id,
                           before={"version": info["frozenVersion"], "hash": info["snapshotHash"]},
                           after={"version": pack["version"], "hash": pack["snapshotHash"]})
            results.append({"projectId": project_id, "applied": True, "fromVersion": info["frozenVersion"],
                            "toVersion": pack["version"], "affectedNodeIds": info["diff"]["affectedNodeIds"],
                            "affectedConclusionCount": info["affectedConclusionCount"],
                            "createdNodeCount": nodes, "createdRequirementCount": requirements, **reconciled})
        return ok({"results": results, "appliedCount": sum(1 for row in results if row["applied"])}, request)

    return api.idempotent(request, idempotency_key, produce, fingerprint_source={"body": body})
