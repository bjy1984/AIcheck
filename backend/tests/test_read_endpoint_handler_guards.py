"""高敏读端点的 handler 层防御（issue #12 的 S-2）。

中间件按 URL 正则推断 scope（/nodes/(\\d+)、/documents/([^/]+)）当前无洞，但那是
单层防御：路由改名、id 改走 query，正则跟不上就静默漏判，而 handler 又没有兜底。
三万行路由文件的演进速度下，这些端点必须自己也校验一次。
"""

from __future__ import annotations

import inspect

from fastapi.testclient import TestClient

import apps.api.routes as routes_module
from apps.api.main import app

client = TestClient(app)

INSPECTION_HEADERS = {
    "X-Dev-Role": "inspection",
    "X-Dev-User": "USER-INSPECTION-001",
    "X-Role": "inspection",
}

# 审计 S-2 点名的 5 个端点，逐一确认 handler 自身带校验
SENSITIVE_READ_HANDLERS = [
    ("list_review_opinions", "监检人工结论全文"),
    ("project_document_original_context", "原始文件下载（original 的公共入口）"),
    ("document_versions", "文档版本历史"),
    ("project_workflow", "项目工作流状态"),
    ("evidence_chain", "节点证据链"),
    # 以下两个不在审计 S-2 清单里，是本轮扫描「声明 project_id 却不用」发现的
    ("document_ocr_fields", "OCR 抽取字段"),
    ("document_review_feedback", "退回补正往返"),
]


# 直接调用，或经这些共享辅助间接调用，都算数
SCOPE_CHECK_MARKERS = ("member_node_scope_error", "document_read_scope_error")


def test_sensitive_read_handlers_carry_their_own_scope_check() -> None:
    """靠中间件是单层防御；这些 handler 必须自带范围校验。

    只认「源码里出现范围校验」这一个信号，是为了让防御被摘掉时立刻失败——
    这类缺失不会有任何运行时症状。
    """
    missing = []
    for name, label in SENSITIVE_READ_HANDLERS:
        handler = getattr(routes_module, name, None)
        assert handler is not None, f"{name} 不存在——端点被改名时这个测试要能发现"
        source = inspect.getsource(handler)
        if not any(marker in source for marker in SCOPE_CHECK_MARKERS):
            missing.append(f"{name}（{label}）")
    assert not missing, "以下高敏读端点缺少 handler 层范围校验：" + "、".join(missing)


def test_document_versions_rejects_mismatched_project() -> None:
    """原先 project_id 在函数体里完全没被用到，传任意项目 id 都能读到版本历史。"""
    response = client.get(
        "/api/projects/P-2026-GDLNG-002/documents/DOC-20260625-001/versions",
        headers=INSPECTION_HEADERS,
    )
    # 本项目约定：HTTP 保持 200，业务错误码在 body 里
    assert response.json()["code"] == 40404, response.text


def test_document_versions_allows_the_owning_project() -> None:
    response = client.get(
        "/api/projects/P-2026-HDCP-001/documents/DOC-20260625-001/versions",
        headers=INSPECTION_HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0


def test_project_workflow_and_evidence_chain_still_serve_authorized_reads() -> None:
    """补防御不能把正常读路径一起挡掉。"""
    workflow = client.get("/api/projects/P-2026-HDCP-001/workflow", headers=INSPECTION_HEADERS)
    assert workflow.status_code == 200, workflow.text
    assert workflow.json()["data"]["projectId"] == "P-2026-HDCP-001"

    chain = client.get(
        "/api/projects/P-2026-HDCP-001/inspection/nodes/24/evidence-chain",
        headers=INSPECTION_HEADERS,
    )
    assert chain.status_code == 200, chain.text
    assert chain.json()["data"]["node"]["nodeId"] == 24


# ---- 本轮扫描发现的两个同类端点（审计 S-2 清单未列出）----

CONTRACTOR_HEADERS = {
    "X-Dev-Role": "contractor",
    "X-Dev-User": "USER-CONTRACTOR-001",
    "X-Role": "contractor",
}
OWNER_HEADERS = {"X-Dev-Role": "owner", "X-Dev-User": "USER-OWNER-001", "X-Role": "owner"}


def test_no_route_declares_project_id_without_using_it() -> None:
    """扫描全部路由：声明了 project_id 却在函数体里从不引用 = 归属校验必然缺失。

    这条规则抓出了 document_ocr_fields 与 document_review_feedback——两者都不在
    审计 S-2 的 5 个端点清单里。一个个补容易漏，让规则自己去找。
    """
    import ast

    from apps.api import routes

    source = inspect.getsource(routes)
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_route = any(
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr in {"get", "post", "put", "patch", "delete"}
            for dec in node.decorator_list
        )
        if not is_route:
            continue
        params = {arg.arg for arg in node.args.args} | {arg.arg for arg in node.args.kwonlyargs}
        if "project_id" not in params:
            continue
        body_uses = sum(
            1
            for stmt in node.body
            for inner in ast.walk(stmt)
            if isinstance(inner, ast.Name) and inner.id == "project_id"
        )
        if body_uses == 0:
            offenders.append(f"{node.name} (routes.py:{node.lineno})")
    assert not offenders, "以下路由声明了 project_id 却从不使用，归属校验必然缺失：" + "、".join(offenders)


def test_review_feedback_does_not_bypass_role_isolation() -> None:
    """同一份监检结论，正门 403、后门 200 等于没设卡。

    修复前实测：施工方与建设方走 /inspection/nodes/{id}/review-opinions 被 403 拦下，
    走 /documents/{id}/review-feedback 却能拿到全文。
    """
    for headers in (CONTRACTOR_HEADERS, OWNER_HEADERS):
        front = client.get(
            "/api/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions", headers=headers
        )
        back = client.get(
            "/api/projects/P-2026-HDCP-001/documents/DOC-20260625-001/review-feedback",
            headers=headers,
        )
        assert front.json()["code"] == 403, front.text
        assert back.json()["code"] == 403, (
            f"后门必须与正门同样拦截，实际 {back.json()['code']}：{back.text}"
        )


def test_review_feedback_is_scoped_to_the_document_not_the_whole_state() -> None:
    """原实现返回 repo.state 里全部意见与整改单，跨项目数据一并送出。"""
    response = client.get(
        "/api/projects/P-2026-HDCP-001/documents/DOC-20260625-001/review-feedback",
        headers=INSPECTION_HEADERS,
    )
    assert response.json()["code"] == 0, response.text
    data = response.json()["data"]
    for key in ("opinions", "rectifications"):
        foreign = [item for item in data[key] if item.get("projectId") != "P-2026-HDCP-001"]
        assert not foreign, f"{key} 混入了其他项目的数据：{foreign[:2]}"


def test_ocr_fields_rejects_mismatched_project() -> None:
    response = client.get(
        "/api/projects/P-2026-GDLNG-002/documents/DOC-20260625-001/ocr-fields",
        headers=INSPECTION_HEADERS,
    )
    assert response.json()["code"] == 40404, response.text
