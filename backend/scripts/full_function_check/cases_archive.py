"""报告归档：项目的最后一步。归档后整个项目只读（页面确认框也这么说），所以放在最后跑。"""

from __future__ import annotations

from scripts.full_function_check.base import Context, api_case, check, items_of
from scripts.full_function_check.cases_flow import report_etag


@api_case(
    "ARCH-01",
    "报告归档，项目转为只读",
    role="inspection",
    steps=[
        "不带 If-Match POST …/reports/{报告}/archive",
        "带过期的报告版本号再归档",
        "带当前报告版本号归档（主链路已签发并导出）",
        "GET …/archive 看归档条目",
        "再对该项目做一次写操作（存提交草稿）",
    ],
    expected="不带头被拒（IF_MATCH_REQUIRED）；过期版本号被拒（ETAG_CONFLICT）；当前版本归档成功并出现在归档列表；"
    "之后项目只读，写操作返回「项目已归档，只读查看」",
    priority="P0",
    writes=True,
    in_process_only=True,
)
def archive_report(ctx: Context) -> None:
    project = ctx.need("project")
    report_id = ctx.need("flow_report")
    inspection = ctx.session("inspection")
    path = f"/api/projects/{project}/reports/{report_id}/archive"
    bare = ctx.send(
        "POST",
        path,
        json={"archiveNote": "不带头"},
        headers={
            key: value
            for key, value in inspection.headers(method="POST", path=path).items()
            if key != "If-Match"
        },
    )
    check(
        (bare.data or {}).get("reason") == "IF_MATCH_REQUIRED", f"不带头应被拦，实际 {bare.brief()}"
    )
    stale = inspection.call(
        "POST", path, json={"archiveNote": "过期"}, headers={"If-Match": 'W/"report-stale-r0"'}
    )
    check(stale.code == 40904, f"过期版本号应被拒（40904），实际 {stale.brief()}")
    inspection.ok(
        "POST",
        path,
        json={"archiveNote": "全功能验收归档"},
        headers={"If-Match": report_etag(ctx, project, report_id)},
    )
    archive = items_of(inspection.ok_get(f"/api/projects/{project}/archive", page=1, pageSize=100))
    check(report_id in str(archive), "归档列表里没有这份报告")
    after = ctx.session("contractor").call(
        "POST",
        f"/api/projects/{project}/submissions/drafts",
        json={"nodeIds": [24], "bindingIds": [ctx.need("flow_binding")]},
    )
    check(after.code == 40903, f"归档后项目应只读（40903），实际 {after.brief()}")
