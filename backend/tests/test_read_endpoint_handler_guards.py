"""高敏读端点的 handler 层防御（issue #12 的 S-2）。

中间件按 URL 正则推断 scope（/nodes/(\\d+)、/documents/([^/]+)）当前无洞，但那是
单层防御：路由改名、id 改走 query，正则跟不上就静默漏判，而 handler 又没有兜底。
三万行路由文件的演进速度下，这些端点必须自己也校验一次。
"""

from __future__ import annotations

import inspect

from fastapi.testclient import TestClient

import apps.api.routes as routes_module
import libs.review_orchestrator  # noqa: F401  # 先初始化，规避 review_tools 循环导入
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
]


def test_sensitive_read_handlers_carry_their_own_scope_check() -> None:
    """靠中间件是单层防御；这些 handler 必须自带 member_node_scope_error。"""
    missing = []
    for name, label in SENSITIVE_READ_HANDLERS:
        handler = getattr(routes_module, name, None)
        assert handler is not None, f"{name} 不存在——端点被改名时这个测试要能发现"
        source = inspect.getsource(handler)
        if "member_node_scope_error" not in source:
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
