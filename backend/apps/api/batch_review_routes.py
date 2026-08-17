"""监检的「一键审查」（0817 第 3 条，从 routes.py 拆出）。

## 用户要的

    「监检平台显示自动审核状态，对于施工方已经提交的文件支持一键审查」

原先只能一个节点一个节点点 ai-recheck。一个项目几十个节点，
监检要点几十次，还得自己记住哪些点过了——**这不是效率问题，
是「漏掉一个也不会有人发现」的问题。**

## 为什么放在独立文件

routes.py 有行数棘轮，卡在上限上。棘轮的用意就是逼新代码不要再往单体里堆
（issue #12 A-2 的增量拆分）。往里加会触发棘轮，抬高上限则是把警报关掉
——那等于取消这条约束。

## 两条设计判据

1. **跳过要说出理由。** 没有待审资料、正在跑、被规则挡住……
   每个都得回明原因。只回「已发起 3 个」的话，另外 20 个去哪了没人知道，
   而监检会以为全跑过了。
2. **一个失败不许影响其余节点。** 批量最怕中途炸掉：前面跑了、后面没跑，
   而返回的是一个 500，监检根本不知道现在是什么状态。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, Request

from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.repository import repo

batch_review_router = APIRouter()

# 一次最多发起多少个。不设上限的话，一次点击可能拉起上百个模型调用，
# 既烧钱又会把编排队列堵死；超出的部分明确回报，而不是悄悄截断。
MAX_BATCH_NODES = 30


def _node_has_reviewable_material(project_id: str, node_id: int) -> bool:
    """这个节点有没有已提交、值得审的资料。

    口径用 SUBMITTED_DOCUMENT_BINDING_STATUSES 那一套的成员，
    和监检别处看到的「已提交」保持一致——换个口径就会出现
    「界面显示已提交，一键审查却说没有资料」。
    """
    submitted = {"已提交", "需补正", "已通过"}
    return any(
        str(binding.get("projectId")) == str(project_id)
        and int(binding.get("nodeId") or 0) == int(node_id)
        and str(binding.get("bindingStatus") or "") in submitted
        for binding in repo.state.get("bindings", [])
    )


def _node_has_running_review(project_id: str, node_id: int) -> bool:
    running = {"运行中", "排队中", "执行中", "RUNNING", "QUEUED"}
    return any(
        str(run.get("projectId")) == str(project_id)
        and int(run.get("nodeId") or 0) == int(node_id)
        and str(run.get("status") or "") in running
        for run in repo.state.get("review_runs", [])
    )


@batch_review_router.post("/projects/{project_id}/inspection/ai-recheck-batch")
def ai_recheck_batch(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    """对一批节点一次性发起 AI 复核。

    不传 nodeIds 就取「有已提交资料」的全部节点——这正是监检想要的
    「把该审的都审一遍」，而不是逼他先自己列清单。
    """
    # 循环依赖：批量复用单节点那条路，不重写一遍
    from apps.api.routes import ai_recheck, idempotent

    project = repo.require_project(project_id)
    if not project:
        return fail(errors.NOT_FOUND, request)

    requested = body.get("nodeIds")
    if requested:
        node_ids = [int(value) for value in requested]
    else:
        # 集合叫 tree_nodes，不是 nodes。第一版写 "nodes" —— 不报错，
        # 只是**一个节点都不遍历**，返回「已发起 0 个」，看着像「没什么可审的」。
        # 猜集合名的代价就是这种静默空转。
        node_ids = sorted(
            {
                int(node.get("nodeId") or 0)
                for node in repo.state.get("tree_nodes", [])
                if str(node.get("projectId")) == str(project_id)
            }
            - {0}
        )

    def produce():
        # producer 必须返回 Response（ok()/fail()），不是 dict——
        # idempotent 无键时直接把它当返回值往外抛，返回 dict 的话
        # 响应里连 code 都没有，前端拿到一个不认识的形状。
        return _run_batch(request, project_id, node_ids, body, x_role, ai_recheck)

    # 必须支持幂等键：监检连点两次「一键审查」不该发起两批。
    # 部署报告的 api.mutation-idempotency 检查会拦住漏掉这一步的写接口——
    # 这次就是被它拦下来的。
    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


def _run_batch(request, project_id, node_ids, body, x_role, ai_recheck) -> dict[str, Any]:
    started: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    overflow: list[int] = []

    for node_id in node_ids:
        if len(started) >= MAX_BATCH_NODES:
            overflow.append(node_id)
            continue
        if not _node_has_reviewable_material(project_id, node_id):
            skipped.append({"nodeId": node_id, "reason": "NO_SUBMITTED_MATERIAL", "message": "该节点没有已提交的资料"})
            continue
        if _node_has_running_review(project_id, node_id):
            skipped.append({"nodeId": node_id, "reason": "ALREADY_RUNNING", "message": "该节点已有审查在跑"})
            continue
        try:
            response = ai_recheck(
                request,
                project_id,
                node_id,
                {"trigger": "batch", **(body.get("payload") or {})},
                None,
                x_role,
            )
        except Exception as error:  # noqa: BLE001
            # 一个节点炸掉不能带走整批。把它记成跳过并说明，
            # 其余节点继续——否则监检拿到一个 500，完全不知道跑到哪了。
            skipped.append({"nodeId": node_id, "reason": "START_FAILED", "message": str(error)[:200]})
            continue
        payload = getattr(response, "body", b"")
        started.append({"nodeId": node_id, "accepted": bool(payload)})

    if overflow:
        skipped.extend(
            {"nodeId": node_id, "reason": "BATCH_LIMIT", "message": f"单次最多发起 {MAX_BATCH_NODES} 个节点"}
            for node_id in overflow
        )

    return ok(
        {
            "startedCount": len(started),
            "started": started,
            # 跳过的一定要带理由：只回「已发起 3 个」的话，
            # 另外 20 个去哪了没人知道，而监检会以为全跑过了。
            "skippedCount": len(skipped),
            "skipped": skipped,
            "batchLimit": MAX_BATCH_NODES,
        },
        request,
    )
