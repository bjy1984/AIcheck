"""知识库：总览、标准规范库、项目文件库、任务中心、规则版本、检索测试、推理日志、配置。"""

from __future__ import annotations

from scripts.full_function_check.base import Context, api_case, check, items_of, skip

READ_PAGES = (
    ("/api/knowledge/overview", {}, "总览"),
    ("/api/knowledge/sources", {"page": 1, "pageSize": 20}, "标准规范库"),
    ("/api/knowledge/project-files", {"page": 1, "pageSize": 20}, "项目文件知识库"),
    ("/api/knowledge/tasks", {"page": 1, "pageSize": 20}, "OCR/向量任务中心"),
    ("/api/rules/versions", {"page": 1, "pageSize": 20}, "业务判断规则版本"),
    ("/api/reasoning/logs", {"page": 1, "pageSize": 20}, "推理链路日志"),
    ("/api/knowledge/config", {}, "知识库配置"),
    ("/api/knowledge/audit-logs", {"page": 1, "pageSize": 20}, "配置审计"),
    ("/api/knowledge/page-index-nodes", {"page": 1, "pageSize": 20}, "章节索引"),
    ("/api/llm/compare-runs", {"page": 1, "pageSize": 20}, "多模型对比记录"),
)


@api_case(
    "KNOW-01",
    "知识库各页面数据可读",
    role="admin",
    steps=[f"管理员 GET {path}（{label}）" for path, _, label in READ_PAGES],
    expected="每个页面的接口都成功返回",
    priority="P1",
)
def pages_readable(ctx: Context) -> None:
    admin = ctx.session("admin")
    failures = []
    for path, params, label in READ_PAGES:
        reply = admin.get(path, **params)
        if not (reply.http == 200 and reply.code == 0):
            failures.append(f"{label} {path}: {reply.brief()}")
    check(not failures, "；".join(failures))


@api_case(
    "KNOW-02",
    "标准规范详情与切片",
    role="admin",
    steps=["从标准规范库取第一份标准文件", "GET /api/knowledge/files/{文件}", "GET …/chunks"],
    expected="详情含标准号、版本、识别状态；切片可分页读取",
    priority="P2",
)
def standard_file_detail(ctx: Context) -> None:
    admin = ctx.session("admin")
    sources = items_of(admin.ok_get("/api/knowledge/sources", page=1, pageSize=20))
    file_id = ""
    for source in sources:
        detail = admin.get(f"/api/knowledge/sources/{source.get('id')}")
        for item in items_of(
            (detail.data or {}).get("files") if isinstance(detail.data, dict) else []
        ):
            file_id = str(item.get("id") or "")
            if file_id:
                break
        if file_id:
            break
    if not file_id:
        skip("演示数据里没有标准文件")
    admin.ok_get(f"/api/knowledge/files/{file_id}")
    admin.ok_get(f"/api/knowledge/files/{file_id}/chunks", page=1, pageSize=10)


@api_case(
    "KNOW-03",
    "知识检索测试",
    role="admin",
    steps=[
        "POST /api/knowledge/retrieval-test（问题：焊工资格证持证项目要求）",
        "再指定 sourceId=KS-PROJECT-FILE 查一次",
    ],
    expected="标准库检索正常返回（可为空）；指定项目资料库被拒——检索测试只查审查依据",
    priority="P2",
)
def retrieval_test(ctx: Context) -> None:
    admin = ctx.session("admin")
    admin.ok(
        "POST",
        "/api/knowledge/retrieval-test",
        json={"question": "焊工资格证持证项目要求", "topK": 5},
    )
    project_files = admin.call(
        "POST",
        "/api/knowledge/retrieval-test",
        json={"question": "焊工资格证", "sourceId": "KS-PROJECT-FILE"},
    )
    check(project_files.code == 40001, f"检索项目资料应被拒，实际 {project_files.brief()}")


@api_case(
    "KNOW-04",
    "对外角色进不了知识库",
    role="outside",
    steps=["施工方、无损、建设方 GET /api/knowledge/overview"],
    expected="全部被拒",
    priority="P1",
)
def outside_denied(ctx: Context) -> None:
    for role in ("contractor", "ndt", "owner"):
        ctx.session(role).denied("GET", "/api/knowledge/overview")
