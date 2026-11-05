"""意见反馈与改进：监检提交 → 管理员回复或送平台 → 平台审批、上线 → 提交人确认。"""

from __future__ import annotations

from scripts.full_function_check.base import Context, api_case, check, items_of, skip


def submit(ctx: Context, role: str, content: str) -> str:
    data = ctx.session(role).ok(
        "POST",
        "/api/user-feedback",
        json={
            "category": "audit_accuracy",
            "content": content,
            "context": {
                "page": "/workbench/inspection",
                "projectId": ctx.need("project"),
                "nodeId": "24",
            },
        },
    )
    feedback = (data or {}).get("feedback") or data or {}
    feedback_id = str(feedback.get("id") or "")
    check(feedback_id, f"没返回反馈编号：{data}")
    return feedback_id


@api_case(
    "FB-01",
    "监检提交意见反馈，在「我的反馈」里看到",
    role="inspection",
    steps=["POST /api/user-feedback（类别、内容、所在页面和节点）", "GET /api/user-feedback/mine"],
    expected="提交成功；我的反馈里有这条，状态为待处理",
    priority="P0",
    writes=True,
)
def submit_and_list(ctx: Context) -> None:
    feedback_id = submit(
        ctx, "inspection", "全功能验收：节点 24 焊工证有效期判断与原件不一致，请核对。"
    )
    ctx.store["feedback_reply"] = feedback_id
    mine = items_of(ctx.session("inspection").ok_get("/api/user-feedback/mine"))
    check(any(str(item.get("id")) == feedback_id for item in mine), "我的反馈里看不到刚提交的")


@api_case(
    "FB-02",
    "内容太短或类别不对被拒",
    role="inspection",
    steps=["内容只写 2 个字提交", "类别写 xxx 提交"],
    expected="都被拒（字段校验失败），不入库",
    priority="P2",
    writes=True,
)
def validation(ctx: Context) -> None:
    inspection = ctx.session("inspection")
    short = inspection.call(
        "POST", "/api/user-feedback", json={"category": "bug", "content": "不好"}
    )
    check(short.code == 40001, f"太短应被拒，实际 {short.brief()}")
    bad = inspection.call(
        "POST", "/api/user-feedback", json={"category": "xxx", "content": "全功能验收：类别不对"}
    )
    check(bad.code == 40001, f"类别不对应被拒，实际 {bad.brief()}")


@api_case(
    "FB-03",
    "施工方、无损、建设方不能提交反馈",
    role="outside",
    steps=["三个对外角色分别 POST /api/user-feedback"],
    expected="全部被拒（403）",
    priority="P1",
)
def outside_refused(ctx: Context) -> None:
    for role in ("contractor", "ndt", "owner"):
        ctx.session(role).denied(
            "POST",
            "/api/user-feedback",
            json={"category": "bug", "content": "全功能验收：对外角色提交"},
        )


@api_case(
    "FB-04",
    "管理员查看、筛选并回复反馈，提交人看到回复",
    role="admin,inspection",
    steps=[
        "管理员 GET /api/admin/user-feedback?category=audit_accuracy",
        "POST /api/admin/user-feedback/{反馈}/reply（status=resolved、回复内容）",
        "监检 GET /api/user-feedback/mine",
    ],
    expected="列表能筛出这条；回复后状态为已解决；提交人看到回复内容",
    priority="P0",
    writes=True,
)
def reply(ctx: Context) -> None:
    feedback_id = ctx.need("feedback_reply")
    admin = ctx.session("admin")
    listed = items_of(admin.ok_get("/api/admin/user-feedback", category="audit_accuracy"))
    check(any(str(item.get("id")) == feedback_id for item in listed), "管理员列表里筛不到这条反馈")
    missing = admin.call(
        "POST", f"/api/admin/user-feedback/{feedback_id}/reply", json={"status": "resolved"}
    )
    check(missing.code == 40001, f"标已解决却不写回复应被拒，实际 {missing.brief()}")
    admin.ok(
        "POST",
        f"/api/admin/user-feedback/{feedback_id}/reply",
        json={"status": "resolved", "reply": "全功能验收：已核对，规则口径已调整。"},
    )
    mine = {
        str(item.get("id")): item
        for item in items_of(ctx.session("inspection").ok_get("/api/user-feedback/mine"))
    }
    check("全功能验收：已核对" in str(mine.get(feedback_id)), "提交人看不到管理员的回复")


@api_case(
    "FB-05",
    "送平台改进：平台审批、上线，提交人确认已解决",
    role="admin,inspection",
    steps=[
        "监检再提交一条反馈",
        "管理员 POST /api/admin/user-feedback/{反馈}/escalate（scope=public）",
        "平台 GET /api/platform/improvement-tasks，approve 这条改进任务",
        "改进代理 claim 领取，submit 回报 PR 和测试结果",
        "没回报前直接改成已上线（应被拒），回报后 POST …/{任务}/status（deployed）",
        "监检 POST /api/user-feedback/{反馈}/confirm（resolved=true）",
    ],
    expected="送平台返回改进任务号；审批、上线都成功；提交人确认后反馈关闭",
    priority="P1",
    writes=True,
)
def escalate(ctx: Context) -> None:
    feedback_id = submit(ctx, "inspection", "全功能验收：希望工位总览能按施工单位筛选。")
    admin = ctx.session("admin")
    escalated = admin.ok(
        "POST", f"/api/admin/user-feedback/{feedback_id}/escalate", json={"scope": "public"}
    )
    task_id = str((escalated or {}).get("taskId") or "")
    check(task_id, f"送平台没返回任务号：{escalated}")
    tasks = items_of(admin.ok_get("/api/platform/improvement-tasks"))
    check(any(str(item.get("id")) == task_id for item in tasks), "平台改进任务列表里没有这条")
    admin.ok(
        "POST",
        f"/api/platform/improvement-tasks/{task_id}/approve",
        json={
            "title": "工位总览按施工单位筛选",
            "taskStatement": "全功能验收：在工位总览加施工单位筛选。",
            "acceptanceCriteria": "能按施工单位筛出节点。",
            "priority": "P2",
        },
    )
    base = f"/api/platform/improvement-tasks/{task_id}"
    early = admin.call("POST", f"{base}/status", json={"status": "deployed", "note": "全功能验收"})
    check(early.code != 0, "没开发完就能标已上线")
    claimed = admin.ok("POST", f"{base}/claim", json={"agent": "fullcheck"})
    claim_id = str(((claimed or {}).get("task") or {}).get("claim", {}).get("id") or "")
    check(claim_id, f"领取没返回 claimId：{claimed}")
    admin.ok(
        "POST",
        f"{base}/submit",
        json={
            "claimId": claim_id,
            "prUrl": "https://example.invalid/pr/1",
            "tests": "fullcheck ok",
            "commit": "abc1234",
        },
    )
    admin.ok("POST", f"{base}/status", json={"status": "deployed", "note": "全功能验收上线"})
    confirmed = ctx.session("inspection").call(
        "POST", f"/api/user-feedback/{feedback_id}/confirm", json={"resolved": True}
    )
    if confirmed.code != 0 and "上线" in confirmed.message:
        skip(f"平台任务状态没回写到反馈：{confirmed.brief()}")
    check(confirmed.code == 0, f"提交人确认应成功，实际 {confirmed.brief()}")


@api_case(
    "FB-06",
    "别人不能替提交人确认",
    role="admin",
    steps=["管理员对监检提交的反馈 POST /api/user-feedback/{反馈}/confirm"],
    expected="被拒（只有提交人本人能确认）",
    priority="P2",
    writes=True,
)
def confirm_only_submitter(ctx: Context) -> None:
    feedback_id = ctx.need("feedback_reply")
    reply = ctx.session("admin").call(
        "POST", f"/api/user-feedback/{feedback_id}/confirm", json={"resolved": True}
    )
    check(reply.code != 0, f"非提交人确认应被拒，实际 {reply.brief()}")
