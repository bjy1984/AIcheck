"""系统与运行状态。"""

from __future__ import annotations

from scripts.full_function_check.base import Context, api_case, check, items_of

MAIN_PROJECT = "P-2026-HDCP-001"
MAIN_NODE = 24


@api_case(
    "SYS-01",
    "健康检查接口可用",
    role="public",
    steps=["不登录，GET /api/healthz"],
    expected="HTTP 200，返回运行状态（数据库、安全服务等就绪标志）",
    priority="P0",
)
def health(ctx: Context) -> None:
    reply = ctx.send("GET", "/api/healthz")
    check(reply.http == 200, f"健康检查应返回 200，实际 {reply.brief()}")
    check(isinstance(reply.body, dict), "健康检查应返回 JSON")


@api_case(
    "SYS-02",
    "运行环境信息（登录页和页脚用）",
    role="public",
    steps=["不登录，GET /api/runtime/ui-context"],
    expected="返回环境名、是否严格生产、构建版本和支持联系方式；不含任何密钥",
    priority="P1",
)
def ui_context(ctx: Context) -> None:
    reply = ctx.send("GET", "/api/runtime/ui-context")
    check(reply.http == 200 and reply.code == 0, f"应成功，实际 {reply.brief()}")
    data = reply.data or {}
    for key in ("environment", "strictProduction", "buildVersion", "support"):
        check(key in data, f"缺少字段 {key}")
    text = reply.text.lower()
    for secret in ("password", "secret", "database_url", "token"):
        check(secret not in text, f"环境信息里不该出现 {secret}")


@api_case(
    "SYS-03",
    "演示项目数据就绪（后续用例的前置）",
    role="inspection",
    steps=[
        "监检登录",
        "GET /api/workbench/projects?role=inspection",
        "记下主测项目（优先 P-2026-HDCP-001）",
    ],
    expected="至少有 1 个项目；项目有编号、名称、状态",
    priority="P0",
)
def projects_ready(ctx: Context) -> None:
    projects = items_of(
        ctx.session("inspection").ok_get("/api/workbench/projects", role="inspection")
    )
    check(projects, "监检看不到任何项目")
    ids = [str(item.get("id")) for item in projects]
    ctx.store["project"] = MAIN_PROJECT if MAIN_PROJECT in ids else ids[0]
    ctx.store["node"] = MAIN_NODE
    ctx.store["projects"] = ids
    first = projects[0]
    for key in ("id", "name", "status"):
        check(first.get(key), f"项目缺少 {key}")
