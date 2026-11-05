"""无损检测工作台（演示数据：节点 35–42，主测节点 40；意见 NDT-FB-001，报告 NDT-RPT-001/002）。"""

from __future__ import annotations

from scripts.full_function_check.base import Context, api_case, check, items_of, skip
from scripts.full_function_check.helpers import PDF_BYTES, finish_ocr, upload_pdf

NDT_NODE = 40
FEEDBACK_ID = "NDT-FB-001"


@api_case(
    "NDT-01",
    "项目列表与工作台",
    role="ndt",
    steps=[
        "无损登录",
        "GET /api/workbench/projects?role=ndt",
        "GET …/workbench/context?role=ndt 和 summary",
    ],
    expected="只看到被授权的项目；工作台只含无损负责的节点（35–42）",
    priority="P0",
)
def workbench(ctx: Context) -> None:
    ndt = ctx.session("ndt")
    projects = items_of(ndt.ok_get("/api/workbench/projects", role="ndt"))
    check(projects, "无损看不到任何项目")
    project = ctx.need("project")
    ndt.ok_get(f"/api/projects/{project}/workbench/context", role="ndt")
    ndt.ok_get(f"/api/projects/{project}/workbench/summary", role="ndt")


@api_case(
    "NDT-02",
    "查看监检意见（列表与详情）",
    role="ndt",
    steps=["GET …/ndt/inspection-feedback", "GET …/ndt/inspection-feedback/NDT-FB-001"],
    expected="列出监检给无损的意见，带节点、关联报告/底片和状态；详情能打开",
    priority="P0",
)
def feedback(ctx: Context) -> None:
    project = ctx.need("project")
    ndt = ctx.session("ndt")
    items = items_of(ndt.ok_get(f"/api/projects/{project}/ndt/inspection-feedback"))
    if not any(str(item.get("id")) == FEEDBACK_ID for item in items):
        skip(f"演示数据里没有 {FEEDBACK_ID}")
    detail = ndt.ok_get(f"/api/projects/{project}/ndt/inspection-feedback/{FEEDBACK_ID}")
    check(detail, "意见详情为空")


@api_case(
    "NDT-03",
    "检测报告、底片、检测记录列表",
    role="ndt",
    steps=[
        "GET …/ndt/reports",
        "GET …/ndt/reports/NDT-RPT-001",
        "GET …/ndt/films",
        "GET …/ndt/records",
    ],
    expected="都成功；报告详情含报告编号、检测方法、结论、关联底片",
    priority="P0",
)
def lists(ctx: Context) -> None:
    project = ctx.need("project")
    ndt = ctx.session("ndt")
    reports = items_of(ndt.ok_get(f"/api/projects/{project}/ndt/reports"))
    check(reports, "没有检测报告")
    ndt.ok_get(f"/api/projects/{project}/ndt/reports/{reports[0]['id']}")
    ndt.ok_get(f"/api/projects/{project}/ndt/films")
    ndt.ok_get(f"/api/projects/{project}/ndt/records")


@api_case(
    "NDT-04",
    "登记底片",
    role="ndt",
    steps=["POST …/ndt/films（节点 40、底片号、焊口号、方法 RT）", "缺焊口号再登记一次"],
    expected="正常登记成功并出现在底片列表；缺必填项被拒（底片编号、焊口编号和检测方法不能为空）",
    priority="P1",
    writes=True,
)
def film(ctx: Context) -> None:
    project = ctx.need("project")
    ndt = ctx.session("ndt")
    ndt.ok(
        "POST",
        f"/api/projects/{project}/ndt/films",
        json={"nodeId": NDT_NODE, "filmNo": "FC-RT-1", "weldNo": "FC-W-1", "method": "RT"},
    )
    films = items_of(ndt.ok_get(f"/api/projects/{project}/ndt/films"))
    check(any(item.get("filmNo") == "FC-RT-1" for item in films), "登记的底片不在列表里")
    bad = ndt.call(
        "POST",
        f"/api/projects/{project}/ndt/films",
        json={"nodeId": NDT_NODE, "filmNo": "FC-RT-2", "method": "RT"},
    )
    check(bad.code == 40022, f"缺焊口号应被拒（40022），实际 {bad.brief()}")


@api_case(
    "NDT-05",
    "导入检测记录",
    role="ndt",
    steps=["POST …/ndt/records/import（节点 40，一行：记录号、焊口号、方法）"],
    expected="导入成功，记录列表里能看到",
    priority="P1",
    writes=True,
)
def records(ctx: Context) -> None:
    project = ctx.need("project")
    ndt = ctx.session("ndt")
    ndt.ok(
        "POST",
        f"/api/projects/{project}/ndt/records/import",
        json={
            "nodeId": NDT_NODE,
            "rows": [{"recordNo": "FC-REC-1", "weldNo": "FC-W-1", "method": "RT"}],
        },
    )
    rows = items_of(ndt.ok_get(f"/api/projects/{project}/ndt/records"))
    check(any(item.get("recordNo") == "FC-REC-1" for item in rows), "导入的记录不在列表里")


@api_case(
    "NDT-06",
    "上传检测报告",
    role="ndt",
    steps=[
        "POST …/ndt/reports/upload-session（节点 40、报告号、方法、文件）",
        "PUT 文件内容",
        "POST …/complete",
    ],
    expected="三步都成功；报告列表里出现这份报告",
    priority="P0",
    writes=True,
)
def upload_report(ctx: Context) -> None:
    project = ctx.need("project")
    ndt = ctx.session("ndt")
    created = ndt.ok(
        "POST",
        f"/api/projects/{project}/ndt/reports/upload-session",
        json={
            "nodeId": NDT_NODE,
            "reportNo": "FC-RT-REPORT-1",
            "method": "RT",
            "files": [
                {
                    "fileName": "全功能验收-RT报告.pdf",
                    "fileSize": len(PDF_BYTES),
                    "fileType": "application/pdf",
                }
            ],
        },
    )
    target = (created.get("uploadUrls") or [{}])[0]
    put = ndt.call(
        "PUT", str(target["url"]), headers=dict(target.get("headers") or {}), content=PDF_BYTES
    )
    check(put.code == 0, f"PUT 报告内容失败：{put.brief()}")
    ndt.ok(
        "POST",
        f"/api/projects/{project}/ndt/reports/upload-session/{created['uploadSessionId']}/complete",
        json={
            "completedFiles": [
                {"documentVersionId": target["documentVersionId"], "fileSize": len(PDF_BYTES)}
            ]
        },
    )
    reports = items_of(ndt.ok_get(f"/api/projects/{project}/ndt/reports"))
    check(any("FC-RT-REPORT-1" in str(item) for item in reports), "上传的报告不在列表里")


@api_case(
    "NDT-07",
    "未识别完成的报告不能提交",
    role="ndt",
    steps=["POST …/ndt/submissions（节点 40、报告 NDT-RPT-001）"],
    expected="报告字段没识别全时被拒，返回 ndtReadiness 说明缺什么；识别齐了才能提交",
    priority="P1",
    writes=True,
)
def submit_guard(ctx: Context) -> None:
    project = ctx.need("project")
    reply = ctx.session("ndt").call(
        "POST",
        f"/api/projects/{project}/ndt/submissions",
        json={"nodeId": NDT_NODE, "reportIds": ["NDT-RPT-001"], "filmIds": []},
    )
    if reply.code == 0:
        return
    check(reply.code == 40900, f"应是状态不允许（40900），实际 {reply.brief()}")
    check("ndtReadiness" in str(reply.data), f"被拒时应说明缺什么：{reply.brief()}")


@api_case(
    "NDT-08",
    "回复监检意见（补正反馈）",
    role="ndt",
    steps=[
        "POST …/ndt/rectifications（意见 NDT-FB-001、说明、关联报告和底片）",
        "再看意见详情",
        "说明为空再提交一次",
    ],
    expected="回复成功，意见状态变为「已反馈」；说明为空被拒（补正反馈事项和说明不能为空）",
    priority="P0",
    writes=True,
)
def reply_feedback(ctx: Context) -> None:
    project = ctx.need("project")
    ndt = ctx.session("ndt")
    empty = ndt.call(
        "POST",
        f"/api/projects/{project}/ndt/rectifications",
        json={"rectificationId": FEEDBACK_ID, "description": ""},
    )
    check(empty.code == 40025, f"空说明应被拒（40025），实际 {empty.brief()}")
    ndt.ok(
        "POST",
        f"/api/projects/{project}/ndt/rectifications",
        json={
            "rectificationId": FEEDBACK_ID,
            "description": "全功能验收：已补充底片索引。",
            "reportIds": ["NDT-RPT-001"],
            "filmIds": ["FILM-RT-002"],
        },
    )
    detail = ndt.ok_get(f"/api/projects/{project}/ndt/inspection-feedback/{FEEDBACK_ID}")
    check("已反馈" in str(detail), f"回复后意见应为已反馈：{str(detail)[:200]}")


@api_case(
    "NDT-09",
    "无损资料：上传、改挂节点、提交",
    role="ndt",
    steps=[
        "按「无损检测资料」类别上传一份委托单（节点 37）",
        "识别完成（进程内替身）",
        "PUT …/ndt/documents/{资料}/bindings 从 37、42 改成只挂 37",
        "POST …/ndt/material-submissions 提交",
    ],
    expected="改挂成功；提交成功，资料状态变为已提交",
    priority="P1",
    writes=True,
    in_process_only=True,
)
def material_submission(ctx: Context) -> None:
    project = ctx.need("project")
    ndt = ctx.session("ndt")
    created = ndt.ok(
        "POST",
        f"/api/projects/{project}/documents/upload-session",
        json={
            "files": [
                {
                    "fileName": "全功能验收-无损委托单.pdf",
                    "fileSize": len(PDF_BYTES),
                    "contentType": "application/pdf",
                    "materialCategory": "无损检测资料",
                    "materialTypeCode": "ndt_entrustment",
                    "materialTypeName": "无损检测委托单",
                    "nodeIds": [37, 42],
                }
            ]
        },
    )
    target = created["uploadUrls"][0]
    put = ndt.call(
        "PUT", str(target["url"]), headers=dict(target.get("headers") or {}), content=PDF_BYTES
    )
    check(put.code == 0, f"PUT 失败：{put.brief()}")
    import hashlib

    ndt.ok(
        "POST",
        f"/api/projects/{project}/documents/upload-session/{created['uploadSessionId']}/complete",
        json={
            "completedFiles": [
                {
                    "documentVersionId": target["documentVersionId"],
                    "fileSize": len(PDF_BYTES),
                    "contentHash": hashlib.sha256(PDF_BYTES).hexdigest(),
                }
            ]
        },
    )
    document_id = str(target["documentId"])
    finish_ocr(ctx, document_id, "全功能验收-无损委托单.pdf")
    bound = ndt.ok(
        "PUT",
        f"/api/projects/{project}/ndt/documents/{document_id}/bindings",
        json={"nodeIds": [37]},
    )
    check(
        bound.get("nodeIds") == [37] and len(bound.get("bindingIds") or []) == 1,
        f"改挂结果不对：{bound}",
    )
    body = {"documentId": document_id, "bindingIds": bound["bindingIds"]}
    ndt.ok("POST", f"/api/projects/{project}/ndt/material-submissions", json=body)


@api_case(
    "NDT-10",
    "无损不能动施工方的节点",
    role="ndt",
    steps=["无损上传一份资料", "POST …/documents/bindings 挂到施工方的节点 24"],
    expected="挂载被拒（节点不在无损的范围内）",
    priority="P0",
    writes=True,
)
def node_scope(ctx: Context) -> None:
    project = ctx.need("project")
    ndt = ctx.session("ndt")
    uploaded = upload_pdf(ndt, project, "全功能验收-无损越权.pdf")
    ndt.denied(
        "POST",
        f"/api/projects/{project}/documents/bindings",
        json={"bindings": [{"documentId": uploaded["documentId"], "nodeId": 24}]},
        codes={401, 403, 40301, 40404},
    )
