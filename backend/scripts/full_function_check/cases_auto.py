"""自动审查与批量复核：开关策略、手动跑一次全量、批量复核。派发用替身，只在进程内跑。"""

from __future__ import annotations

from scripts.full_function_check.base import Context, api_case, check
from scripts.full_function_check.cases_flow import stub_ai_dispatch


@api_case(
    "AUTO-01",
    "开启自动审查策略",
    role="inspection",
    steps=[
        "不带 If-Match PUT …/inspection/auto-review-policy",
        "带 If-Match PUT（enabled=true，触发方式=资料识别挂载后+每天 03:30）",
        "GET …/auto-review-policy 读回",
    ],
    expected="不带版本号被拒；带了保存成功；读回与保存一致",
    priority="P1",
    writes=True,
)
def enable_policy(ctx: Context) -> None:
    project = ctx.need("project")
    inspection = ctx.session("inspection")
    path = f"/api/projects/{project}/inspection/auto-review-policy"
    body = {
        "enabled": True,
        "triggerModes": ["ocr_mounted", "daily_schedule"],
        "dailyTime": "03:30",
        "timezone": "Asia/Shanghai",
    }
    bare = inspection.call("PUT", path, json=body)
    check(bare.code != 0, f"不带 If-Match 不该能改策略：{bare.brief()}")
    inspection.ok("PUT", path, json=body, headers={"If-Match": "*"})
    saved = inspection.ok_get(path)
    check(
        "03:30" in str(saved) and "daily_schedule" in str(saved),
        f"读回的策略不对：{str(saved)[:200]}",
    )


@api_case(
    "AUTO-02",
    "手动跑一次全量自动审查",
    role="inspection",
    steps=["POST …/inspection/auto-review/run", "GET …/auto-review-status"],
    expected="生成一次父运行和各节点子运行；状态接口能看到这次运行（派发用替身）",
    priority="P1",
    writes=True,
    in_process_only=True,
)
def run_auto_review(ctx: Context) -> None:
    project = ctx.need("project")
    stub_ai_dispatch(ctx)
    inspection = ctx.session("inspection")
    reply = inspection.call("POST", f"/api/projects/{project}/inspection/auto-review/run")
    check(reply.code == 0, f"手动全量审查应成功，实际 {reply.brief()}")
    inspection.ok_get(f"/api/projects/{project}/inspection/auto-review-status")


@api_case(
    "AUTO-03",
    "批量 AI 复核",
    role="inspection",
    steps=["POST …/inspection/ai-recheck-batch（nodeIds=[16]）"],
    expected="接口成功；每个节点给出已发起或不能发起的原因",
    priority="P2",
    writes=True,
    in_process_only=True,
)
def batch_recheck(ctx: Context) -> None:
    project = ctx.need("project")
    stub_ai_dispatch(ctx)
    reply = ctx.session("inspection").call(
        "POST", f"/api/projects/{project}/inspection/ai-recheck-batch", json={"nodeIds": [16]}
    )
    check(reply.code == 0, f"批量复核应成功，实际 {reply.brief()}")
