"""建设方工作台：只读——看进度、节点、已签发的报告、归档、消息。"""

from __future__ import annotations

from scripts.full_function_check.base import Context, api_case, check, items_of

SETTLED = {"已签发", "已归档"}


@api_case(
    "OWN-01",
    "项目列表与工程进度",
    role="owner",
    steps=[
        "建设方登录",
        "GET /api/workbench/projects?role=owner",
        "GET …/workbench/summary?role=owner",
    ],
    expected="只看到本单位的项目；汇总里有进度指标（metrics）",
    priority="P0",
)
def progress(ctx: Context) -> None:
    owner = ctx.session("owner")
    projects = items_of(owner.ok_get("/api/workbench/projects", role="owner"))
    check(projects, "建设方看不到任何项目")
    project = ctx.need("project")
    owner.ok_get(f"/api/projects/{project}/workbench/context", role="owner")
    summary = owner.ok_get(f"/api/projects/{project}/workbench/summary", role="owner")
    check(isinstance(summary, dict) and "metrics" in summary, "汇总里没有进度指标 metrics")


@api_case(
    "OWN-02",
    "节点状态一览",
    role="owner",
    steps=["GET /api/projects/{项目}/tree"],
    expected="能看到节点和状态（只读）",
    priority="P1",
)
def tree(ctx: Context) -> None:
    ctx.session("owner").ok_get(f"/api/projects/{ctx.need('project')}/tree")


@api_case(
    "OWN-03",
    "报告列表只显示已签发或已归档的",
    role="owner",
    steps=["GET /api/projects/{项目}/owner/reports"],
    expected="列表里每份报告都是「已签发」或「已归档」；复核中的报告看不到",
    priority="P0",
)
def reports(ctx: Context) -> None:
    items = items_of(
        ctx.session("owner").ok_get(f"/api/projects/{ctx.need('project')}/owner/reports")
    )
    unsettled = [item.get("status") for item in items if item.get("status") not in SETTLED]
    check(not unsettled, f"建设方看到了未签发的报告：{unsettled}")


@api_case(
    "OWN-04",
    "归档资料与归档包",
    role="owner",
    steps=["GET …/archive?page=1&pageSize=20", "GET …/archive/package"],
    expected="都成功；归档包给出可下载的清单或说明尚未生成",
    priority="P2",
)
def archive(ctx: Context) -> None:
    owner = ctx.session("owner")
    project = ctx.need("project")
    owner.ok_get(f"/api/projects/{project}/archive", page=1, pageSize=20)
    reply = owner.get(f"/api/projects/{project}/archive/package")
    check(reply.http == 200 and reply.code in (0, 40930, 40404), f"归档包接口异常：{reply.brief()}")


@api_case(
    "OWN-05",
    "建设方不能做任何写操作",
    role="owner",
    steps=["建设方尝试：提交资料、下审查结论、完成待办"],
    expected="全部被拒",
    priority="P0",
)
def read_only(ctx: Context) -> None:
    owner = ctx.session("owner")
    project = ctx.need("project")
    codes = {401, 403, 40301, 40404}
    owner.denied(
        "POST",
        f"/api/projects/{project}/submissions",
        json={"nodeIds": [24], "bindingIds": []},
        codes=codes,
    )
    owner.denied(
        "POST",
        f"/api/projects/{project}/inspection/nodes/24/review-opinions",
        json={"result": "满足要求", "opinion": "越权"},
        codes=codes,
    )
    owner.denied("POST", "/api/todos/TODO-001/complete", json={"comment": "越权"}, codes=codes)
