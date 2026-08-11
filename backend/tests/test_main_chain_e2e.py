"""主业务链路端到端（API 层，P0 护栏）。

此前整条「上传 → 提交 → AI 复核 → 人工结论 → 打回 → 补正 → 通过」链路没有任何
一个测试从头走到尾——各环节分散在不同用例里，环节之间的衔接（状态转移、数据
交接）恰恰是回归最常出现的地方。浏览器 e2e 只有 1 条 smoke。

本测试用真实 HTTP 调用走完整链，AI 复核用可控替身（stub 派发，不打真 LLM）。
每一步都断言「下一步依赖的状态」，让链路中断在发生的环节报错，而不是最后一步。
"""
from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

import libs.review_orchestrator  # noqa: F401  # 先初始化，规避 review_tools 循环导入
from apps.api.main import app
from libs.db.repository import repo

client = TestClient(app)

PROJECT_ID = "P-2026-HDCP-001"
NODE_ID = 24
CONTRACTOR = {
    "X-Dev-Role": "contractor",
    "X-Dev-User": "USER-CONTRACTOR-001",
    "X-Role": "contractor",
}
INSPECTION = {
    "X-Dev-Role": "inspection",
    "X-Dev-User": "USER-INSPECTION-001",
    "X-Role": "inspection",
}
PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def ok(response, step: str) -> dict:
    assert response.status_code == 200, f"[{step}] HTTP {response.status_code}: {response.text}"
    payload = response.json()
    assert payload.get("code") == 0, f"[{step}] {payload}"
    return payload.get("data") or {}


def upload_document(file_name: str, key: str) -> str:
    """真实上传三步：会话 → PUT 内容 → 完成清单（带大小与哈希）。"""
    session = ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers={**CONTRACTOR, "Idempotency-Key": f"{key}-session"},
            json={
                "files": [
                    {"fileName": file_name, "fileSize": len(PDF_BYTES), "contentType": "application/pdf"}
                ]
            },
        ),
        f"{key}:创建上传会话",
    )
    target = session["uploadUrls"][0]
    put = client.put(
        target["url"].removeprefix("/api"),
        headers={**CONTRACTOR, **target["headers"]},
        content=PDF_BYTES,
    )
    assert put.json()["code"] == 0, f"[{key}:PUT] {put.text}"
    ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session/{session['uploadSessionId']}/complete",
            headers={**CONTRACTOR, "Idempotency-Key": f"{key}-complete"},
            json={
                "completedFiles": [
                    {
                        "documentVersionId": target["documentVersionId"],
                        "fileSize": len(PDF_BYTES),
                        "contentHash": hashlib.sha256(PDF_BYTES).hexdigest(),
                    }
                ]
            },
        ),
        f"{key}:完成上传",
    )
    document_id = str(target["documentId"])
    mark_ocr_pipeline_complete(document_id)
    return document_id


def mark_ocr_pipeline_complete(document_id: str) -> None:
    """OCR/切片/向量化的可控替身。

    测试环境不跑 worker，管线状态停在「排队中」；而施工方提交现在要求管线完成
    （2026-08-10 上传重试专项加的门：document_upload_pipeline_complete）。
    这里直接把三段状态置为完成——与该专项自己的契约测试同一做法。
    """
    document = repo.find_one("documents", document_id)
    assert document, f"文档 {document_id} 不存在"
    version = repo.find_one("versions", str(document.get("currentVersionId") or "")) or {}
    document["currentOcrStatus"] = "已识别"
    version["ocrStatus"] = "已识别"
    version["sliceStatus"] = "已切片"
    version["vectorStatus"] = "已向量化"
    for knowledge_file in repo.state.get("knowledge_files", []):
        if str(knowledge_file.get("documentVersionId") or "") == str(document.get("currentVersionId") or ""):
            knowledge_file["ocrStatus"] = "已识别"
            knowledge_file["sliceStatus"] = "已切片"
            knowledge_file["vectorStatus"] = "已向量化"


def bind_to_node(document_id: str, key: str) -> str:
    ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/bindings",
            headers={**CONTRACTOR, "Idempotency-Key": f"{key}-bind"},
            json={"bindings": [{"documentId": document_id, "nodeId": NODE_ID}]},
        ),
        f"{key}:挂载",
    )
    binding = next(
        item
        for item in repo.state["bindings"]
        if str(item.get("documentId") or "") == document_id
    )
    assert int(binding["nodeId"]) == NODE_ID, "声明的节点必须生效（M-8 回归点）"
    assert binding["bindingStatus"] == "草稿挂载"
    return str(binding["id"])


def node_status() -> str:
    return str(repo.node(PROJECT_ID, NODE_ID)["status"])


def test_main_chain_upload_review_return_rectify_pass(monkeypatch) -> None:
    # ---- 第 1 环：施工方上传真实内容并挂载到节点 ----
    document_id = upload_document("焊工证-主链路.pdf", "chain-first")
    binding_id = bind_to_node(document_id, "chain-first")

    # ---- 第 2 环：正式提交给监检 ----
    ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/submissions",
            headers={**CONTRACTOR, "Idempotency-Key": "chain-submit", "If-Match": "*"},
            json={"nodeIds": [NODE_ID], "bindingIds": [binding_id], "batchName": "主链路提交"},
        ),
        "提交",
    )
    assert repo.find_one("bindings", binding_id)["bindingStatus"] == "已提交"
    assert node_status() == "待审查", f"提交后节点应转待审查，实际 {node_status()}"

    # ---- 第 3 环：AI 复核（可控替身：stub 派发，不打真 LLM）----
    from libs.business_pack import load_business_pack
    from libs.integrations import task_dispatcher

    pack = load_business_pack("engineering_inspection_v1")
    monkeypatch.setitem(pack["atomicCheckToolBindingSet"], "lifecycleStatus", "published")
    monkeypatch.setattr(
        task_dispatcher,
        "ai_recheck_dispatch_readiness",
        lambda: {"ready": True, "mode": "test", "statusReason": "test_dispatch"},
    )
    monkeypatch.setattr(
        task_dispatcher,
        "dispatch_ai_recheck",
        lambda project_id, node_id, run_id: {"mode": "test", "taskId": f"TEST-{run_id}"},
    )
    run = ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/ai-recheck",
            headers={**INSPECTION, "Idempotency-Key": "chain-recheck"},
        ),
        "AI 复核",
    )
    assert run.get("runId"), "AI 复核应返回运行 ID"

    # ---- 第 4 环：监检打回（触发补正流程）----
    ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/actions/return-correction",
            headers={**INSPECTION, "Idempotency-Key": "chain-return", "If-Match": "*"},
            json={
                "reason": "焊工证持证项目未覆盖本工程焊接方法，请补充。",
                "bindingIds": [binding_id],
            },
        ),
        "打回",
    )
    assert node_status() == "需补正", f"打回后节点应转需补正，实际 {node_status()}"
    assert repo.find_one("bindings", binding_id)["bindingStatus"] == "需补正"
    rectification = next(
        item
        for item in repo.state["rectifications"]
        if item.get("projectId") == PROJECT_ID
        and int(item.get("nodeId") or 0) == NODE_ID
        and item.get("status") == "待反馈"
    )
    assert rectification.get("comment"), "打回理由必须落到整改单上，施工方要看得到"

    # ---- 第 5 环：施工方上传新资料补正（M-6 的核心场景）----
    new_document_id = upload_document("补充的焊工证-主链路.pdf", "chain-second")
    new_binding_id = bind_to_node(new_document_id, "chain-second")
    ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/rectifications",
            headers={**CONTRACTOR, "Idempotency-Key": "chain-rectify", "If-Match": "*"},
            json={
                "nodeId": NODE_ID,
                "rectificationId": rectification["id"],
                "bindingIds": [new_binding_id],
                "comment": "已补充覆盖本工程焊接方法的焊工证。",
            },
        ),
        "补正提交",
    )
    updated = repo.find_one("rectifications", rectification["id"])
    assert new_binding_id in (updated.get("replacementBindingIds") or []), "补正留痕必须能区分新资料"
    assert updated["feedbackComment"] == "已补充覆盖本工程焊接方法的焊工证。"
    assert repo.find_one("bindings", new_binding_id)["bindingStatus"] == "已提交"
    assert node_status() == "复审中", f"补正后节点应转复审中，实际 {node_status()}"

    # ---- 第 6 环：监检确认证据并给出「满足要求」，节点办结 ----
    from test_contract import seed_confirmed_node_24_evidence

    evidence_ids = seed_confirmed_node_24_evidence(PROJECT_ID)
    saved = ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-opinions",
            headers={**INSPECTION, "Idempotency-Key": "chain-opinion", "If-Match": "*"},
            json={
                "result": "满足要求",
                "opinion": "补正后资料齐全，焊工资格覆盖本工程焊接方法。",
                "evidenceLinkIds": evidence_ids,
            },
        ),
        "人工结论",
    )
    assert saved["nextStatus"] == "已通过"
    assert node_status() == "已通过", f"链路终点应为已通过，实际 {node_status()}"

    # ---- 终态守卫仍然有效（N-4）：办结的节点拖不回流程起点 ----
    from libs.db.repository import IllegalNodeStatusTransition

    try:
        repo.set_node_status(PROJECT_ID, NODE_ID, "待提交")
    except IllegalNodeStatusTransition:
        pass
    else:
        raise AssertionError("已通过节点不应能被改回待提交")
    assert node_status() == "已通过"
