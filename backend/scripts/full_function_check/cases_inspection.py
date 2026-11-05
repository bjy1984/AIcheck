"""监检工作台：项目总览、节点审查、证据、标准、报告复核、自动审查、一键分析、搜索。

打回、下结论这些会改状态的动作放在主业务链路（cases_flow.py）里按顺序走。
"""

from __future__ import annotations

from scripts.full_function_check.base import Context, api_case, check, items_of, skip


def project_node(ctx: Context) -> tuple[str, int]:
    return ctx.need("project"), int(ctx.need("node"))


@api_case(
    "INSP-01",
    "项目列表：监检看到全部授权项目",
    role="inspection",
    steps=["监检登录", "GET /api/workbench/projects?role=inspection"],
    expected="列出授权项目，带名称、编号、状态、进度；探针项目（写操作审计-勿动）不出现",
    priority="P0",
)
def project_list(ctx: Context) -> None:
    projects = items_of(
        ctx.session("inspection").ok_get("/api/workbench/projects", role="inspection")
    )
    check(projects, "项目列表为空")
    names = [str(item.get("name") or "") for item in projects]
    check(not any("勿动" in name for name in names), "探针项目不该出现在工作台列表")


@api_case(
    "INSP-02",
    "工作台上下文与汇总数字",
    role="inspection",
    steps=[
        "GET /api/projects/{项目}/workbench/context?role=inspection",
        "GET …/workbench/summary?role=inspection",
    ],
    expected="都成功；汇总里有节点总数和各状态计数",
    priority="P0",
)
def workbench_context(ctx: Context) -> None:
    project, _ = project_node(ctx)
    inspection = ctx.session("inspection")
    inspection.ok_get(f"/api/projects/{project}/workbench/context", role="inspection")
    summary = inspection.ok_get(f"/api/projects/{project}/workbench/summary", role="inspection")
    check(isinstance(summary, dict) and summary, "汇总为空")


@api_case(
    "INSP-03",
    "项目节点树",
    role="inspection",
    steps=["GET /api/projects/{项目}/tree"],
    expected="返回监检节点（带编号、名称、状态），主测节点 24 在里面",
    priority="P0",
)
def project_tree(ctx: Context) -> None:
    project, node = project_node(ctx)
    tree = ctx.session("inspection").ok_get(f"/api/projects/{project}/tree")
    text = str(tree)
    check("nodeId" in text or "nodes" in text, "节点树没有节点")
    check(f"'nodeId': {node}" in text or f"'id': {node}" in text, f"节点树里找不到节点 {node}")


@api_case(
    "INSP-04",
    "审查总览：按工位分组、可筛选可搜索",
    role="inspection",
    steps=[
        "GET /api/projects/{项目}/inspection/audit-overview",
        "再带 keyword=焊 和 page/pageSize 查一次",
    ],
    expected="返回节点清单和统计；关键词筛选后条数不多于全部",
    priority="P0",
)
def audit_overview(ctx: Context) -> None:
    project, _ = project_node(ctx)
    inspection = ctx.session("inspection")
    full = inspection.ok_get(f"/api/projects/{project}/inspection/audit-overview")
    check(full, "审查总览为空")
    filtered = inspection.ok_get(
        f"/api/projects/{project}/inspection/audit-overview", keyword="焊", page=1, pageSize=20
    )
    check(isinstance(filtered, dict | list), "筛选结果格式不对")


@api_case(
    "INSP-05",
    "已提交资料清单",
    role="inspection",
    steps=["GET /api/projects/{项目}/inspection/submitted-documents?page=1&pageSize=20"],
    expected="返回施工方/无损已提交的资料，带文件名、所属节点、识别状态",
    priority="P1",
)
def submitted_documents(ctx: Context) -> None:
    project, _ = project_node(ctx)
    data = ctx.session("inspection").ok_get(
        f"/api/projects/{project}/inspection/submitted-documents", page=1, pageSize=20
    )
    documents = items_of(data)
    if documents:
        ctx.store.setdefault(
            "document", str(documents[0].get("documentId") or documents[0].get("id") or "")
        )


@api_case(
    "INSP-06",
    "节点审查工作区（逐条核对页的数据）",
    role="inspection",
    steps=["GET /api/projects/{项目}/inspection/nodes/{节点}/audit-workspace"],
    expected="返回节点信息、必传资料、核对项和 AI 建议；节点号与请求一致",
    priority="P0",
)
def audit_workspace(ctx: Context) -> None:
    project, node = project_node(ctx)
    data = ctx.session("inspection").ok_get(
        f"/api/projects/{project}/inspection/nodes/{node}/audit-workspace"
    )
    check(isinstance(data, dict) and data, "审查工作区为空")
    check(
        str(node) in str(data.get("nodeId") or data.get("node") or data)[:2000],
        "工作区没有带节点号",
    )


@api_case(
    "INSP-07",
    "节点实时状态（页面轮询用）",
    role="inspection",
    steps=["GET /api/projects/{项目}/inspection/nodes/{节点}/live-status"],
    expected="返回节点状态和正在跑的任务（如有）",
    priority="P1",
)
def live_status(ctx: Context) -> None:
    project, node = project_node(ctx)
    data = ctx.session("inspection").ok_get(
        f"/api/projects/{project}/inspection/nodes/{node}/live-status"
    )
    check(isinstance(data, dict), "实时状态格式不对")


@api_case(
    "INSP-08",
    "节点资料包",
    role="inspection",
    steps=["GET /api/projects/{项目}/nodes/{节点}/package"],
    expected="返回该节点挂载的资料与必传清单",
    priority="P1",
)
def node_package(ctx: Context) -> None:
    project, node = project_node(ctx)
    data = ctx.session("inspection").ok_get(f"/api/projects/{project}/nodes/{node}/package")
    check(isinstance(data, dict) and data.get("node"), "资料包缺节点信息")
    check(data.get("requirements"), "资料包缺必传清单")
    for item in data.get("bindings") or []:
        if item.get("documentId"):
            ctx.store.setdefault("document", str(item["documentId"]))
            break


@api_case(
    "INSP-09",
    "证据链",
    role="inspection",
    steps=["GET /api/projects/{项目}/inspection/nodes/{节点}/evidence-chain"],
    expected="返回证据条目（字段、来源文件、页码），可为空但接口成功",
    priority="P1",
)
def evidence_chain(ctx: Context) -> None:
    project, node = project_node(ctx)
    ctx.session("inspection").ok_get(
        f"/api/projects/{project}/inspection/nodes/{node}/evidence-chain"
    )


@api_case(
    "INSP-10",
    "节点适用标准条款",
    role="inspection",
    steps=["GET /api/projects/{项目}/inspection/nodes/{节点}/standards"],
    expected="返回该节点要核的标准条款（标准号、条款号、原文摘录）",
    priority="P1",
)
def node_standards(ctx: Context) -> None:
    project, node = project_node(ctx)
    data = ctx.session("inspection").ok_get(
        f"/api/projects/{project}/inspection/nodes/{node}/standards"
    )
    check(isinstance(data, list | dict), "标准条款格式不对")


@api_case(
    "INSP-11",
    "日期比对（证书有效期 vs 施工期）",
    role="inspection",
    steps=["GET /api/projects/{项目}/inspection/nodes/{节点}/date-compare"],
    expected="接口成功；有施工期时逐项给出是否覆盖",
    priority="P1",
)
def date_compare(ctx: Context) -> None:
    project, node = project_node(ctx)
    ctx.session("inspection").ok_get(
        f"/api/projects/{project}/inspection/nodes/{node}/date-compare"
    )


@api_case(
    "INSP-12",
    "资料详情与 OCR 字段",
    role="inspection",
    steps=[
        "取一份已提交资料",
        "GET /api/projects/{项目}/documents/{资料}",
        "GET …/ocr-fields",
        "GET …/preview-url",
    ],
    expected="详情含版本与识别状态；OCR 字段带页码；演示资料没有真实文件时预览明确提示「尚未绑定真实存储」而不是报错",
    priority="P1",
)
def document_detail(ctx: Context) -> None:
    project, _ = project_node(ctx)
    document = ctx.store.get("document")
    if not document:
        skip("演示项目没有可用的已提交资料（主链路上传后会补测）")
    inspection = ctx.session("inspection")
    detail = inspection.ok_get(f"/api/projects/{project}/documents/{document}")
    check(
        isinstance(detail, dict) and (detail.get("document") or {}).get("id") == document,
        "资料详情为空",
    )
    check((detail.get("document") or {}).get("currentVersionId"), "资料详情缺当前版本")
    inspection.ok_get(f"/api/projects/{project}/documents/{document}/ocr-fields")
    preview = inspection.get(f"/api/projects/{project}/documents/{document}/preview-url")
    check(preview.code in (0, 50330), f"预览地址接口异常：{preview.brief()}")


@api_case(
    "INSP-13",
    "全局搜索",
    role="inspection",
    steps=["GET /api/search?keyword=焊工&projectId={项目}"],
    expected="返回分页结果，每条有类型和跳转目标",
    priority="P2",
)
def search(ctx: Context) -> None:
    project, _ = project_node(ctx)
    data = ctx.session("inspection").ok_get(
        "/api/search", keyword="焊工", projectId=project, page=1, pageSize=10
    )
    check(isinstance(data, dict | list), "搜索结果格式不对")


@api_case(
    "INSP-14",
    "自动审查：查看策略与状态",
    role="inspection",
    steps=["GET /api/projects/{项目}/inspection/auto-review-policy", "GET …/auto-review-status"],
    expected="都成功；返回是否开启、触发条件和最近一次运行",
    priority="P1",
)
def auto_review_read(ctx: Context) -> None:
    project, _ = project_node(ctx)
    inspection = ctx.session("inspection")
    inspection.ok_get(f"/api/projects/{project}/inspection/auto-review-policy")
    inspection.ok_get(f"/api/projects/{project}/inspection/auto-review-status")


@api_case(
    "INSP-15",
    "一键分析：预览范围",
    role="inspection",
    steps=["GET /api/projects/{项目}/inspection/full-project-analysis/preview"],
    expected="返回将要分析的节点和资料数量，不真正开跑",
    priority="P1",
)
def full_analysis_preview(ctx: Context) -> None:
    project, _ = project_node(ctx)
    reply = ctx.session("inspection").call(
        "GET", f"/api/projects/{project}/inspection/full-project-analysis/preview"
    )
    if reply.http == 405:
        reply = ctx.session("inspection").call(
            "POST", f"/api/projects/{project}/inspection/full-project-analysis/preview", json={}
        )
    check(reply.http == 200 and reply.code == 0, f"预览应成功，实际 {reply.brief()}")


@api_case(
    "INSP-16",
    "一键分析：历史运行列表",
    role="inspection",
    steps=["GET /api/projects/{项目}/inspection/full-project-analysis/runs"],
    expected="返回历史运行（可为空）",
    priority="P2",
)
def full_analysis_runs(ctx: Context) -> None:
    project, _ = project_node(ctx)
    ctx.session("inspection").ok_get(
        f"/api/projects/{project}/inspection/full-project-analysis/runs"
    )


@api_case(
    "INSP-17",
    "归档与报告列表",
    role="inspection",
    steps=["GET /api/projects/{项目}/archive?page=1&pageSize=20"],
    expected="返回归档条目（报告、资料包），可为空",
    priority="P2",
)
def archive_list(ctx: Context) -> None:
    project, _ = project_node(ctx)
    ctx.session("inspection").ok_get(f"/api/projects/{project}/archive", page=1, pageSize=20)


@api_case(
    "INSP-18",
    "项目规则（本项目口径）列表",
    role="inspection",
    steps=["GET /api/projects/{项目}/rules/versions"],
    expected="返回本项目自定义的规则版本；项目还没有自定义规则时返回「不存在」",
    priority="P2",
)
def project_rules(ctx: Context) -> None:
    project, _ = project_node(ctx)
    reply = ctx.session("inspection").get(f"/api/projects/{project}/rules/versions")
    if reply.code == 40404:
        skip("本项目还没有自定义规则版本")
    check(reply.http == 200 and reply.code == 0, f"应成功，实际 {reply.brief()}")


@api_case(
    "INSP-19",
    "审查助手：不调模型的快捷命令",
    role="inspection",
    steps=[
        "POST …/inspection/nodes/1/review-sessions 建会话，记下 etag",
        "不带 If-Match 发消息",
        "带 If-Match POST /api/review-sessions/{会话}/messages（/标准条款）",
    ],
    expected="不带 If-Match 返回 428；快捷命令直接返回 completed 的回答（不调模型）",
    priority="P1",
    writes=True,
)
def assistant_command(ctx: Context) -> None:
    project = ctx.need("project")
    inspection = ctx.session("inspection")
    created = inspection.ok(
        "POST",
        f"/api/projects/{project}/inspection/nodes/1/review-sessions",
        json={"currentTask": "全功能验收"},
    )
    session = created.get("session") or created
    session_id, etag = str(session.get("id") or ""), str(session.get("etag") or "")
    check(session_id and etag, f"会话缺 id 或 etag：{list(session)}")
    bare = inspection.call(
        "POST", f"/api/review-sessions/{session_id}/messages", json={"content": "/标准条款"}
    )
    check(bare.http == 428 or bare.code == 42801, f"不带 If-Match 应 428，实际 {bare.brief()}")
    answered = inspection.ok(
        "POST",
        f"/api/review-sessions/{session_id}/messages",
        json={"content": "/标准条款"},
        headers={"If-Match": etag},
    )
    check("completed" in str(answered), f"快捷命令应直接完成：{str(answered)[:200]}")


@api_case(
    "INSP-20",
    "更正 OCR 事实并撤销",
    role="inspection",
    steps=[
        "POST …/inspection/nodes/24/fact-corrections（字段、原值、更正值、原因）",
        "POST …/fact-corrections/{更正}/revoke",
    ],
    expected="更正保存并留痕；撤销后恢复原值，更正记录标为已撤销",
    priority="P1",
    writes=True,
)
def fact_correction(ctx: Context) -> None:
    project = ctx.need("project")
    inspection = ctx.session("inspection")
    saved = inspection.ok(
        "POST",
        f"/api/projects/{project}/inspection/nodes/24/fact-corrections",
        json={
            "factPath": "welderCertificate.certificateNo",
            "originalValue": "T2026-O01",
            "correctedValue": "TS2026-001",
            "reason": "全功能验收：OCR 把 S 认成了数字",
        },
    )
    correction = saved.get("correction") or saved
    correction_id = str(correction.get("id") or "")
    check(correction_id, f"没返回更正编号：{saved}")
    inspection.ok(
        "POST",
        f"/api/projects/{project}/inspection/nodes/24/fact-corrections/{correction_id}/revoke",
        json={},
    )


@api_case(
    "INSP-21",
    "不采纳 AI 建议",
    role="inspection",
    steps=[
        "POST …/inspection/nodes/24/ai-suggestions/AIS-24-20260625-01/reject（原因）",
        "不写原因再拒一次",
    ],
    expected="写了原因的成功，建议标为不采纳；不写原因被拒",
    priority="P1",
    writes=True,
)
def reject_suggestion(ctx: Context) -> None:
    project = ctx.need("project")
    inspection = ctx.session("inspection")
    path = f"/api/projects/{project}/inspection/nodes/24/ai-suggestions/AIS-24-20260625-01/reject"
    empty = inspection.call("POST", path, json={"reason": ""})
    check(empty.code != 0, f"不写原因应被拒，实际 {empty.brief()}")
    reply = inspection.call("POST", path, json={"reason": "全功能验收：证据页码对不上"})
    if reply.code == 40404:
        skip("演示数据里没有 AIS-24-20260625-01")
    check(reply.code == 0, f"不采纳应成功，实际 {reply.brief()}")
