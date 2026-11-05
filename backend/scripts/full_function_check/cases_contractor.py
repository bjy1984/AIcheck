"""施工方工作台：看待办节点、上传资料、挂节点、存草稿、改资料类别、看退回、删草稿资料。

正式提交和补正提交在主业务链路（cases_flow.py）里走，因为要先等识别完成。
"""

from __future__ import annotations

from scripts.full_function_check.base import Context, api_case, check, items_of
from scripts.full_function_check.helpers import bind, upload_pdf


def contractor_project(ctx: Context) -> str:
    project = ctx.need("project")
    return project


@api_case(
    "CONT-01",
    "项目列表：只看到自己参与的项目，退回补正的排前面",
    role="contractor",
    steps=["施工方登录", "GET /api/workbench/projects?role=contractor"],
    expected="只列出被授权的项目；有「退回补正中」的项目排在最前",
    priority="P0",
)
def project_list(ctx: Context) -> None:
    contractor = ctx.session("contractor")
    projects = items_of(contractor.ok_get("/api/workbench/projects", role="contractor"))
    check(projects, "施工方看不到任何项目")
    ids = [str(item.get("id")) for item in projects]
    check(ctx.need("project") in ids, f"施工方项目列表里没有主测项目：{ids}")
    statuses = [str(item.get("status") or "") for item in projects]
    if "退回补正中" in statuses:
        check(statuses[0] == "退回补正中", f"退回补正中的项目应排第一，实际顺序 {statuses}")


@api_case(
    "CONT-02",
    "工作台：本方负责的节点和待办数字",
    role="contractor",
    steps=[
        "GET /api/projects/{项目}/workbench/context?role=contractor",
        "GET …/workbench/summary?role=contractor",
    ],
    expected="都成功；只含施工方负责的节点",
    priority="P0",
)
def workbench(ctx: Context) -> None:
    project = contractor_project(ctx)
    contractor = ctx.session("contractor")
    contractor.ok_get(f"/api/projects/{project}/workbench/context", role="contractor")
    contractor.ok_get(f"/api/projects/{project}/workbench/summary", role="contractor")


@api_case(
    "CONT-03",
    "节点资料要求（必传清单）",
    role="contractor",
    steps=["GET /api/projects/{项目}/nodes/{节点}/package"],
    expected="列出该节点的必传资料、已挂资料和缺项",
    priority="P0",
)
def node_requirements(ctx: Context) -> None:
    project, node = contractor_project(ctx), int(ctx.need("node"))
    package = ctx.session("contractor").ok_get(f"/api/projects/{project}/nodes/{node}/package")
    check(package.get("requirements"), "看不到必传清单")


@api_case(
    "CONT-04",
    "上传资料（建会话→传文件→完成）",
    role="contractor",
    steps=[
        "POST …/documents/upload-session（文件名、大小、类型）",
        "PUT 上传地址传文件内容",
        "POST …/complete（大小与 SHA-256）",
    ],
    expected="三步都成功；资料出现在项目资料列表里，状态为已上传、等待识别",
    priority="P0",
    writes=True,
)
def upload(ctx: Context) -> None:
    project = contractor_project(ctx)
    contractor = ctx.session("contractor")
    uploaded = upload_pdf(contractor, project, "全功能验收-施工方上传.pdf")
    ctx.store["contractor_upload"] = uploaded
    documents = items_of(
        contractor.ok_get(f"/api/projects/{project}/documents", page=1, pageSize=200)
    )
    check(
        any(str(item.get("id")) == uploaded["documentId"] for item in documents),
        "上传后的资料不在项目资料列表里",
    )


@api_case(
    "CONT-05",
    "上传不支持的文件类型被拒",
    role="contractor",
    steps=["POST …/documents/upload-session，文件名 virus.exe，类型 application/x-msdownload"],
    expected="被拒绝（文件类型不支持），不建会话",
    priority="P1",
    writes=True,
)
def reject_bad_type(ctx: Context) -> None:
    project = contractor_project(ctx)
    reply = ctx.session("contractor").call(
        "POST",
        f"/api/projects/{project}/documents/upload-session",
        json={
            "files": [
                {
                    "fileName": "virus.exe",
                    "fileSize": 1024,
                    "contentType": "application/x-msdownload",
                }
            ]
        },
    )
    check(reply.code not in (0, None), f"exe 文件应被拒，实际 {reply.brief()}")


@api_case(
    "CONT-06",
    "把资料挂到节点（草稿挂载）",
    role="contractor",
    steps=["POST …/documents/bindings，把刚上传的资料挂到节点 24", "GET …/nodes/24/package 看挂载"],
    expected="挂载成功，状态为「草稿挂载」，节点资料包里能看到它",
    priority="P0",
    writes=True,
)
def bind_to_node(ctx: Context) -> None:
    project, node = contractor_project(ctx), int(ctx.need("node"))
    uploaded = ctx.need("contractor_upload")
    contractor = ctx.session("contractor")
    binding_id = bind(contractor, project, uploaded["documentId"], node)
    ctx.store["contractor_binding"] = binding_id
    package = contractor.ok_get(f"/api/projects/{project}/nodes/{node}/package")
    mine = [item for item in package.get("bindings") or [] if str(item.get("id")) == binding_id]
    check(mine, "节点资料包里看不到刚挂的资料")
    check(
        mine[0].get("bindingStatus") == "草稿挂载",
        f"挂载状态应为草稿挂载，实际 {mine[0].get('bindingStatus')}",
    )


@api_case(
    "CONT-07",
    "保存提交草稿、查看提交记录",
    role="contractor",
    steps=[
        "POST …/submissions/drafts（节点 24、刚挂的资料）",
        "GET …/submissions/drafts/{草稿}",
        "GET …/submissions",
    ],
    expected="草稿保存成功并能读回；提交记录列表可读",
    priority="P1",
    writes=True,
)
def save_draft(ctx: Context) -> None:
    project, node = contractor_project(ctx), int(ctx.need("node"))
    binding_id = ctx.need("contractor_binding")
    contractor = ctx.session("contractor")
    draft = contractor.ok(
        "POST",
        f"/api/projects/{project}/submissions/drafts",
        json={"nodeIds": [node], "bindingIds": [binding_id], "batchName": "全功能验收草稿"},
    )
    check(draft.get("draftId"), "没返回草稿编号")
    detail = contractor.ok_get(f"/api/projects/{project}/submissions/drafts/{draft['draftId']}")
    check(binding_id in str(detail), "草稿详情里没有挂载的资料")
    contractor.ok_get(f"/api/projects/{project}/submissions", page=1, pageSize=20)


@api_case(
    "CONT-08",
    "修改资料类别（上传时归错类可改）",
    role="contractor",
    steps=[
        "PATCH …/documents/{资料}/material-category，materialCategory 改成「焊接人员与焊接工艺」",
        "再用一个不存在的类别改一次",
    ],
    expected="合法类别修改成功；不存在的类别被拒（提示可选类别）",
    priority="P2",
    writes=True,
)
def change_category(ctx: Context) -> None:
    project = contractor_project(ctx)
    uploaded = ctx.need("contractor_upload")
    contractor = ctx.session("contractor")
    path = f"/api/projects/{project}/documents/{uploaded['documentId']}/material-category"
    contractor.ok("PATCH", path, json={"materialCategory": "焊接人员与焊接工艺"})
    bad = contractor.call("PATCH", path, json={"materialCategory": "不存在的类别-全功能验收"})
    check(bad.code == 40001, f"不存在的类别应被拒，实际 {bad.brief()}")


@api_case(
    "CONT-09",
    "查看被退回的事项（整改单）",
    role="contractor",
    steps=["GET /api/projects/{项目}/rectifications?page=1&pageSize=20"],
    expected="列出监检退回给本方的事项，带意见和期限（可为空）",
    priority="P0",
)
def rectifications(ctx: Context) -> None:
    project = contractor_project(ctx)
    data = ctx.session("contractor").ok_get(
        f"/api/projects/{project}/rectifications", page=1, pageSize=20
    )
    for item in items_of(data):
        check(item.get("projectId") == project, "整改单串了项目")


@api_case(
    "CONT-10",
    "删除未提交的资料",
    role="contractor",
    steps=[
        "再上传一份资料（不挂、不提交）",
        "DELETE /api/projects/{项目}/documents/{资料}",
        "查项目资料列表",
    ],
    expected="删除成功，列表里不再出现；已提交的资料不能这样删",
    priority="P1",
    writes=True,
)
def delete_draft_document(ctx: Context) -> None:
    project = contractor_project(ctx)
    contractor = ctx.session("contractor")
    uploaded = upload_pdf(contractor, project, "全功能验收-待删除.pdf")
    contractor.ok("DELETE", f"/api/projects/{project}/documents/{uploaded['documentId']}")
    documents = items_of(
        contractor.ok_get(f"/api/projects/{project}/documents", page=1, pageSize=200)
    )
    check(
        not any(str(item.get("id")) == uploaded["documentId"] for item in documents),
        "删除后资料仍在列表里",
    )


@api_case(
    "CONT-11",
    "施工方看不到监检的审查工作区",
    role="contractor",
    steps=["施工方 GET …/inspection/nodes/{节点}/audit-workspace"],
    expected="被拒绝（核对过程和 AI 建议只给监检）",
    priority="P0",
)
def no_inspection_internals(ctx: Context) -> None:
    project, node = contractor_project(ctx), int(ctx.need("node"))
    contractor = ctx.session("contractor")
    contractor.denied(
        "GET",
        f"/api/projects/{project}/inspection/nodes/{node}/audit-workspace",
        codes={401, 403, 40301, 40404},
    )
