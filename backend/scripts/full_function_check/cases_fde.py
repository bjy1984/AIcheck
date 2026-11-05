"""FDE 治理台：各页面只读冒烟。FDE 的写操作（发布、回滚、打标）影响全局，不在本脚本里做。"""

from __future__ import annotations

from scripts.full_function_check.base import Context, api_case, check

FDE_PAGES = (
    ("/api/fde/dashboard", "治理总览"),
    ("/api/fde/meta", "元数据"),
    ("/api/fde/blockers", "阻断项"),
    ("/api/fde/projects", "项目审计工作台"),
    ("/api/fde/ai-runs", "AI Run 追踪"),
    ("/api/fde/review-runs", "Agent 审查编排"),
    ("/api/fde/feedback", "人工反馈与样本池"),
    ("/api/fde/feedback/metrics", "反馈指标"),
    ("/api/fde/evaluation-sets", "评估实验室"),
    ("/api/fde/capability-bundles", "能力包"),
    ("/api/fde/releases", "发布治理"),
    ("/api/fde/ocr-quality", "OCR 质量与标注"),
    ("/api/fde/business-packs/validation", "业务类型工厂"),
    ("/api/fde/security/masking-policies", "数据安全"),
    ("/api/fde/incidents", "事故复盘"),
    ("/api/fde/cost-budgets", "成本预算"),
    ("/api/fde/acceptance-reports", "客户验收"),
    ("/api/fde/audit-events", "审计事件"),
    ("/api/fde/access-grants", "访问授权"),
)


@api_case(
    "FDE-01",
    "FDE 治理台各页面数据可读",
    role="fde",
    steps=[f"FDE GET {path}（{label}）" for path, label in FDE_PAGES],
    expected="每个页面的接口都成功返回",
    priority="P2",
)
def pages_readable(ctx: Context) -> None:
    fde = ctx.session("fde")
    failures = []
    for path, label in FDE_PAGES:
        reply = fde.get(path)
        if not (reply.http == 200 and reply.code == 0):
            failures.append(f"{label} {path}: {reply.brief()}")
    check(not failures, "；".join(failures))


@api_case(
    "FDE-02",
    "FDE 看到的 AI 运行记录是脱敏的",
    role="fde",
    steps=["GET /api/fde/ai-runs", "取一条 GET /api/fde/ai-runs/{运行}"],
    expected="详情里不出现身份证号、手机号原文",
    priority="P1",
)
def masked_runs(ctx: Context) -> None:
    import re

    fde = ctx.session("fde")
    runs = fde.ok_get("/api/fde/ai-runs")
    items = runs.get("items") if isinstance(runs, dict) else runs
    if not items:
        return
    detail = fde.get(f"/api/fde/ai-runs/{items[0].get('id')}")
    text = detail.text
    check(not re.search(r"(?<!\d)\d{17}[\dXx](?!\d)", text), "AI 运行详情里出现了疑似身份证号原文")
    check(not re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", text), "AI 运行详情里出现了疑似手机号原文")
