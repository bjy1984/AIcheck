"""主业务链路（跨角色）：上传 → 提交 → AI 复核 → 打回 → 补正 → 确认证据 → 下结论 → 报告复核。

每一步断言「下一步依赖的状态」，链路断在哪一环就报在哪一环。整条链会改状态，
只在进程内模式跑（OCR 工人与 AI 复核派发用替身，不打真模型）。
"""

from __future__ import annotations

from typing import Any

from scripts.full_function_check.base import Context, api_case, check, items_of, skip
from scripts.full_function_check.helpers import (
    bind,
    finish_ocr,
    node_status,
    seed_confirmed_evidence,
    upload_pdf,
)

FLOW_NODE = 24


def stub_ai_dispatch(ctx: Context) -> None:
    from libs.business_pack import load_business_pack
    from libs.integrations import task_dispatcher

    pack = load_business_pack("engineering_inspection_v1")
    binding_set = pack["atomicCheckToolBindingSet"]
    original = binding_set.get("lifecycleStatus")
    binding_set["lifecycleStatus"] = "published"
    ctx._patches.append((_DictSlot(binding_set), "value", original))
    ctx.patch(
        task_dispatcher,
        "ai_recheck_dispatch_readiness",
        lambda: {"ready": True, "mode": "test", "statusReason": "fullcheck_stub"},
    )
    ctx.patch(
        task_dispatcher,
        "dispatch_ai_recheck",
        lambda project_id, node_id, run_id, **_kwargs: {
            "mode": "test",
            "taskId": f"FULLCHECK-{run_id}",
        },
    )


class _DictSlot:
    """让 restore_patches 能把字典里的一个键改回去。"""

    def __init__(self, target: dict[str, Any]):
        self._target = target

    @property
    def value(self) -> Any:
        return self._target.get("lifecycleStatus")

    @value.setter
    def value(self, original: Any) -> None:
        if original is None:
            self._target.pop("lifecycleStatus", None)
        else:
            self._target["lifecycleStatus"] = original


@api_case(
    "FLOW-01",
    "施工方正式提交节点资料",
    role="contractor",
    steps=[
        "施工方上传焊工证 PDF（三步上传）",
        "识别完成（进程内用真实落库路径喂一份 OCR 结果）",
        "挂到节点 24",
        "POST …/submissions（nodeIds、bindingIds、批次名，带 If-Match）",
    ],
    expected="提交成功；挂载变为「已提交」；节点转为「待审查」",
    priority="P0",
    writes=True,
    in_process_only=True,
)
def submit(ctx: Context) -> None:
    project = ctx.need("project")
    contractor = ctx.session("contractor")
    uploaded = upload_pdf(contractor, project, "全功能验收-焊工证.pdf")
    applied = finish_ocr(ctx, uploaded["documentId"], "全功能验收-焊工证.pdf")
    check(applied.get("status") != "failed", f"OCR 落库失败：{applied}")
    binding_id = bind(contractor, project, uploaded["documentId"], FLOW_NODE)
    contractor.ok(
        "POST",
        f"/api/projects/{project}/submissions",
        json={"nodeIds": [FLOW_NODE], "bindingIds": [binding_id], "batchName": "全功能验收提交"},
    )
    ctx.store["flow_document"] = uploaded
    ctx.store["flow_binding"] = binding_id
    ctx.store.setdefault("document", uploaded["documentId"])
    status = node_status(ctx.session("inspection"), project, FLOW_NODE)
    check(status == "待审查", f"提交后节点应为待审查，实际 {status}")


@api_case(
    "FLOW-02",
    "识别失败的资料不能提交",
    role="contractor",
    steps=["上传一份资料，识别结果为失败", "挂到节点后正式提交"],
    expected="提交被拒，返回里列出未识别完成的资料编号；节点状态不变",
    priority="P0",
    writes=True,
    in_process_only=True,
)
def failed_ocr_blocks_submit(ctx: Context) -> None:
    project = ctx.need("project")
    contractor = ctx.session("contractor")
    uploaded = upload_pdf(contractor, project, "全功能验收-扫描失败件.pdf")
    finish_ocr(
        ctx,
        uploaded["documentId"],
        "全功能验收-扫描失败件.pdf",
        {"status": "failed", "fragments": [], "fields": []},
    )
    binding_id = bind(contractor, project, uploaded["documentId"], FLOW_NODE)
    before = node_status(ctx.session("inspection"), project, FLOW_NODE)
    reply = contractor.call(
        "POST",
        f"/api/projects/{project}/submissions",
        json={"nodeIds": [FLOW_NODE], "bindingIds": [binding_id], "batchName": "失败件提交"},
    )
    check(reply.code != 0, "识别失败的资料不该能提交")
    check(uploaded["documentId"] in str(reply.data), f"返回里应列出失败的资料：{reply.brief()}")
    check(
        node_status(ctx.session("inspection"), project, FLOW_NODE) == before,
        "被拒的提交不该改节点状态",
    )
    # 失败件留着会挡住后面的正式提交：撤掉挂载并删除。
    contractor.call("DELETE", f"/api/projects/{project}/documents/{uploaded['documentId']}")


@api_case(
    "FLOW-03",
    "监检发起 AI 复核（证据不全时只能做缺项预审）",
    role="inspection",
    steps=[
        "证据未齐时 POST …/inspection/nodes/24/ai-recheck（reviewMode=formal）",
        "改用 reviewMode=gap_precheck 再发起",
        "GET …/live-status 看任务",
    ],
    expected="正式复核被拒并提示先处理阻断项；缺项预审返回运行编号（派发用替身，不打真模型）",
    priority="P0",
    writes=True,
    in_process_only=True,
)
def ai_recheck(ctx: Context) -> None:
    project = ctx.need("project")
    ctx.need("flow_binding")
    stub_ai_dispatch(ctx)
    inspection = ctx.session("inspection")
    path = f"/api/projects/{project}/inspection/nodes/{FLOW_NODE}/ai-recheck"
    package = inspection.ok_get(f"/api/projects/{project}/nodes/{FLOW_NODE}/package")
    readiness = package.get("evidenceReadiness") or {}
    formal = inspection.call("POST", path, json={"reviewMode": "formal"})
    if not readiness.get("readyForAiFormal"):
        check(formal.code == 40900, f"证据未齐时正式复核应被拒，实际 {formal.brief()}")
        run = inspection.ok("POST", path, json={"reviewMode": "gap_precheck"})
    else:
        check(formal.code == 0, f"证据已齐，正式复核应成功，实际 {formal.brief()}")
        run = formal.data or {}
    check(run.get("runId"), f"没返回运行编号：{run}")
    ctx.store["flow_run"] = run["runId"]
    inspection.ok_get(f"/api/projects/{project}/inspection/nodes/{FLOW_NODE}/live-status")


@api_case(
    "FLOW-04",
    "监检打回补正",
    role="inspection",
    steps=["POST …/inspection/nodes/24/actions/return-correction（理由、要补的挂载，带 If-Match）"],
    expected="节点转「需补正」；挂载转「需补正」；生成一张「待反馈」的整改单，理由原样带上",
    priority="P0",
    writes=True,
    in_process_only=True,
)
def return_correction(ctx: Context) -> None:
    project = ctx.need("project")
    binding_id = ctx.need("flow_binding")
    reason = "全功能验收：焊工证持证项目未覆盖本工程焊接方法，请补充。"
    ctx.session("inspection").ok(
        "POST",
        f"/api/projects/{project}/inspection/nodes/{FLOW_NODE}/actions/return-correction",
        json={"reason": reason, "bindingIds": [binding_id]},
    )
    status = node_status(ctx.session("inspection"), project, FLOW_NODE)
    check(status == "需补正", f"打回后节点应为需补正，实际 {status}")
    items = items_of(
        ctx.session("contractor").ok_get(
            f"/api/projects/{project}/rectifications", page=1, pageSize=50
        )
    )
    open_items = [
        item
        for item in items
        if int(item.get("nodeId") or 0) == FLOW_NODE
        and item.get("status") == "待反馈"
        and reason in str(item)
    ]
    check(open_items, "施工方看不到这次退回的整改单（或理由没带上）")
    ctx.store["flow_rectification"] = str(open_items[0]["id"])


@api_case(
    "FLOW-05",
    "施工方补正后重新提交",
    role="contractor",
    steps=[
        "上传补充资料并识别完成",
        "挂到节点 24",
        "POST …/rectifications（整改单、新挂载、说明，带 If-Match）",
    ],
    expected="补正成功；整改单记下新资料和说明；节点转「复审中」",
    priority="P0",
    writes=True,
    in_process_only=True,
)
def rectify(ctx: Context) -> None:
    project = ctx.need("project")
    rectification_id = ctx.need("flow_rectification")
    contractor = ctx.session("contractor")
    uploaded = upload_pdf(contractor, project, "全功能验收-补充焊工证.pdf")
    finish_ocr(ctx, uploaded["documentId"], "全功能验收-补充焊工证.pdf")
    binding_id = bind(contractor, project, uploaded["documentId"], FLOW_NODE)
    comment = "全功能验收：已补充覆盖本工程焊接方法的焊工证。"
    contractor.ok(
        "POST",
        f"/api/projects/{project}/rectifications",
        json={
            "nodeId": FLOW_NODE,
            "rectificationId": rectification_id,
            "bindingIds": [binding_id],
            "comment": comment,
        },
        headers={"If-Match": "*"},
    )
    detail = contractor.ok_get(f"/api/projects/{project}/rectifications/{rectification_id}")
    check(comment in str(detail), "整改单里没记下补正说明")
    status = node_status(ctx.session("inspection"), project, FLOW_NODE)
    check(status == "复审中", f"补正后节点应为复审中，实际 {status}")


@api_case(
    "FLOW-06",
    "监检逐条确认证据",
    role="inspection",
    steps=[
        "GET …/nodes/24/package 取证据条目",
        "对每条 POST …/nodes/24/evidence-links/{证据}/confirm",
    ],
    expected="确认成功，证据状态变为「已确认」",
    priority="P0",
    writes=True,
    in_process_only=True,
)
def confirm_evidence(ctx: Context) -> None:
    project = ctx.need("project")
    ctx.need("flow_rectification")
    inspection = ctx.session("inspection")
    package = inspection.ok_get(f"/api/projects/{project}/nodes/{FLOW_NODE}/package")
    links = [item for item in package.get("nodeEvidenceLinks") or [] if item.get("id")]
    if not links:
        skip("节点 24 没有可确认的证据条目")
    confirmed: list[str] = []
    for link in links:
        reply = inspection.call(
            "POST",
            f"/api/projects/{project}/nodes/{FLOW_NODE}/evidence-links/{link['id']}/confirm",
            json={"comment": "全功能验收确认"},
        )
        if reply.code == 0:
            confirmed.append(str(link["id"]))
    check(confirmed, "一条证据都没确认成功")
    ctx.store["flow_evidence"] = confirmed


@api_case(
    "FLOW-07",
    "监检下结论「满足要求」，节点办结",
    role="inspection",
    steps=[
        "（进程内替身）其余必传审查点补上「已确认」证据——页面上是监检逐条点确认",
        "POST …/inspection/nodes/24/review-opinions（满足要求、意见、引用的证据，带 If-Match）",
    ],
    expected="保存成功，nextStatus=已通过；节点状态为「已通过」",
    priority="P0",
    writes=True,
    in_process_only=True,
)
def conclude(ctx: Context) -> None:
    project = ctx.need("project")
    ctx.need("flow_rectification")
    evidence = seed_confirmed_evidence(ctx, project, FLOW_NODE, ctx.need("flow_document"))
    saved = ctx.session("inspection").ok(
        "POST",
        f"/api/projects/{project}/inspection/nodes/{FLOW_NODE}/review-opinions",
        json={
            "result": "满足要求",
            "opinion": "全功能验收：补正后资料齐全。",
            "evidenceLinkIds": evidence,
        },
    )
    check(saved.get("nextStatus") == "已通过", f"nextStatus 应为已通过：{saved}")
    status = node_status(ctx.session("inspection"), project, FLOW_NODE)
    check(status == "已通过", f"节点应为已通过，实际 {status}")


@api_case(
    "FLOW-08",
    "已办结的节点不能再打回",
    role="inspection",
    steps=["对已通过的节点 24 再 POST …/actions/return-correction"],
    expected="被拒（状态不允许）；节点仍为「已通过」",
    priority="P0",
    writes=True,
    in_process_only=True,
)
def closed_node_guard(ctx: Context) -> None:
    project = ctx.need("project")
    inspection = ctx.session("inspection")
    if node_status(inspection, project, FLOW_NODE) != "已通过":
        skip("节点 24 没走到已通过")
    reply = inspection.call(
        "POST",
        f"/api/projects/{project}/inspection/nodes/{FLOW_NODE}/actions/return-correction",
        json={"reason": "办结后再打回（应被拒）", "bindingIds": [ctx.need("flow_binding")]},
    )
    check(reply.code != 0, "已通过的节点不该还能打回")
    check(node_status(inspection, project, FLOW_NODE) == "已通过", "被拒的打回改了节点状态")


@api_case(
    "FLOW-09",
    "生成节点报告复核稿",
    role="inspection",
    steps=["POST …/inspection/nodes/24/report-review（带证据、范围=节点）"],
    expected="生成成功，返回报告编号和版本；建设方报告列表能看到已发布的报告",
    priority="P1",
    writes=True,
    in_process_only=True,
)
def report_review(ctx: Context) -> None:
    project = ctx.need("project")
    reply = ctx.session("inspection").call(
        "POST",
        f"/api/projects/{project}/inspection/nodes/{FLOW_NODE}/report-review",
        json={"includeEvidence": True, "reportScope": "currentNode", "reviewerNote": "全功能验收"},
    )
    check(reply.code == 0, f"报告复核应成功，实际 {reply.brief()}")
    data = reply.data or {}
    report_id = str(
        data.get("reportId") or data.get("id") or (data.get("report") or {}).get("id") or ""
    )
    if report_id:
        ctx.store["flow_report"] = report_id


def report_etag(ctx: Context, project: str, report_id: str) -> str:
    reply = ctx.session("inspection").get(f"/api/projects/{project}/reports/{report_id}")
    check(reply.code == 0, f"读报告失败：{reply.brief()}")
    data = reply.data or {}
    report = data.get("report") if isinstance(data.get("report"), dict) else data
    return str(report.get("etag") or reply.headers.get("etag") or "*")


@api_case(
    "FLOW-10",
    "报告复核完成并签发",
    role="inspection",
    steps=[
        "GET …/reports/{报告} 取版本号（etag）",
        "PATCH …/reports/{报告} status=复核完成（带 If-Match）",
        "再 PATCH status=已签发",
    ],
    expected="两次都成功；报告状态为「已签发」",
    priority="P0",
    writes=True,
    in_process_only=True,
)
def sign_report(ctx: Context) -> None:
    project = ctx.need("project")
    report_id = ctx.need("flow_report")
    inspection = ctx.session("inspection")
    for status in ("复核完成", "已签发"):
        etag = report_etag(ctx, project, report_id)
        inspection.ok(
            "PATCH",
            f"/api/projects/{project}/reports/{report_id}",
            json={"status": status, "remark": f"全功能验收：{status}"},
            headers={"If-Match": etag},
        )
    detail = inspection.ok_get(f"/api/projects/{project}/reports/{report_id}")
    check("已签发" in str(detail)[:3000], "签发后报告状态不是已签发")


@api_case(
    "FLOW-11",
    "建设方能看到已签发的报告",
    role="owner",
    steps=["建设方 GET …/owner/reports"],
    expected="刚签发的报告出现在列表里",
    priority="P0",
    in_process_only=True,
)
def owner_sees_report(ctx: Context) -> None:
    project = ctx.need("project")
    report_id = ctx.need("flow_report")
    items = items_of(ctx.session("owner").ok_get(f"/api/projects/{project}/owner/reports"))
    check(any(str(item.get("id")) == report_id for item in items), "建设方看不到刚签发的报告")


@api_case(
    "FLOW-12",
    "导出报告",
    role="inspection",
    steps=["POST …/reports/{报告}/export（format=pdf）", "GET …/export-tasks/{导出任务}"],
    expected="生成导出任务；任务可查询（生成中或已完成）",
    priority="P1",
    writes=True,
    in_process_only=True,
)
def export_report(ctx: Context) -> None:
    project = ctx.need("project")
    report_id = ctx.need("flow_report")
    inspection = ctx.session("inspection")
    data = inspection.ok(
        "POST", f"/api/projects/{project}/reports/{report_id}/export", json={"format": "pdf"}
    )
    export_id = str(
        (data or {}).get("exportId") or (data or {}).get("id") or (data or {}).get("taskId") or ""
    )
    check(export_id, f"没返回导出任务编号：{data}")
    reply = inspection.get(f"/api/projects/{project}/export-tasks/{export_id}")
    check(reply.code in (0, 40930), f"导出任务查询异常：{reply.brief()}")


@api_case(
    "FLOW-14",
    "监检预览和下载刚上传的原件",
    role="inspection",
    steps=[
        "GET …/documents/{本轮上传的资料}/preview-url",
        "GET …/download-url",
        "按预览地址取文件",
    ],
    expected="拿到预览和下载地址；取到的内容就是上传的 PDF",
    priority="P1",
    in_process_only=True,
)
def preview_original(ctx: Context) -> None:
    from scripts.full_function_check.helpers import PDF_BYTES

    project = ctx.need("project")
    document = ctx.need("flow_document")
    inspection = ctx.session("inspection")
    preview = inspection.ok_get(
        f"/api/projects/{project}/documents/{document['documentId']}/preview-url"
    )
    inspection.ok_get(f"/api/projects/{project}/documents/{document['documentId']}/download-url")
    url = str((preview or {}).get("url") or (preview or {}).get("previewUrl") or "")
    check(url, f"没返回预览地址：{preview}")
    if url.startswith("http") and "127.0.0.1:8000" not in url:
        return
    path = url.split("127.0.0.1:8000", 1)[-1]
    fetched = inspection.call("GET", path)
    check(
        fetched.http == 200 and fetched.content.startswith(b"%PDF"),
        f"按预览地址取不到原件：HTTP {fetched.http}",
    )
    check(fetched.content == PDF_BYTES, "取回的内容与上传的不一致")
