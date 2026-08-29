"""主业务链路端到端（API 层，P0 护栏）。

此前整条「上传 → 提交 → AI 复核 → 人工结论 → 打回 → 补正 → 通过」链路没有任何
一个测试从头走到尾——各环节分散在不同用例里，环节之间的衔接（状态转移、数据
交接）恰恰是回归最常出现的地方。浏览器 e2e 只有 1 条 smoke。

本测试用真实 HTTP 调用走完整链，AI 复核用可控替身（stub 派发，不打真 LLM）。
每一步都断言「下一步依赖的状态」，让链路中断在发生的环节报错，而不是最后一步。
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from fastapi.testclient import TestClient

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


# 一份贴近真实 OCR 产物的载荷：带页码、带 bbox、置信度有高有低。
# 用它是为了让 apply_ocr_result 真正跑一遍字段落库与证据链生成，而不是绕过。
WELDER_CERT_OCR_RESULT = {
    "fileName": "焊工资格证-链路测试.pdf",
    # 可用性由 status + fragments/tables 判定（libs/ocr_readiness.py），
    # 不是自己声明一个 ingestionStatus 就算数——第一版就在这里写错过
    "status": "success",
    "fragments": [
        {"text": "特种设备作业人员证", "pageNo": 1, "bbox": [100, 120, 520, 180]},
        {"text": "证书编号 TS6J-2024-03158", "pageNo": 1, "bbox": [120, 240, 420, 286]},
        {"text": "姓名 王建国", "pageNo": 1, "bbox": [120, 300, 260, 344]},
        {"text": "合格项目 GTAW-FeII-6G-3/57-FefS-02/11/12", "pageNo": 2, "bbox": [118, 402, 560, 448]},
    ],
    "fields": [
        {
            "fieldName": "证书编号",
            "fieldValue": "TS6J-2024-03158",
            "pageNo": 1,
            "bbox": [120, 240, 420, 286],
            "confidence": 0.96,
        },
        {
            "fieldName": "姓名",
            "fieldValue": "王建国",
            "pageNo": 1,
            "bbox": [120, 300, 260, 344],
            "confidence": 0.93,
        },
        {
            # 低置信度字段必须照样落库并标记，不能因为「不够确定」就丢掉——
            # 丢掉的结果是监检看不到这一项，也就不会去核对（M-7 的病根）
            "fieldName": "合格项目",
            "fieldValue": "GTAW-FeII-6G-3/57-FefS-02/11/12",
            "pageNo": 2,
            "bbox": [118, 402, 560, 448],
            "confidence": 0.61,
        },
    ],
}


def run_ocr_pipeline(document_id: str, result: dict[str, Any] | None = None) -> dict[str, Any]:
    """走真实的 OCR 落库路径，而不是直接改状态。

    原实现把 ocrStatus/sliceStatus/vectorStatus 直接置为完成，链路是通了，但
    apply_ocr_result 里「字段落库 + 证据链生成 + bbox 保留」这段代码端到端从未被跑过——
    而那正是本轮出现静默丢字段（M-7）的地方。现在喂真实形状的产物，让这段代码
    真的执行，再断言产物能从 API 出来。

    切片/向量化仍是替身：它们不产出审查依据，且需要真实 worker 与 pgvector。
    """
    document = repo.find_one("documents", document_id)
    assert document, f"文档 {document_id} 不存在"
    version_id = str(document.get("currentVersionId") or "")
    assert version_id, f"文档 {document_id} 没有当前版本"

    applied = repo.apply_ocr_result(document_id, version_id, result or WELDER_CERT_OCR_RESULT)

    version = repo.find_one("versions", version_id) or {}
    if str(version.get("ocrStatus") or "") == "已识别":
        # 切片与向量化不影响审查依据，保持替身
        version["sliceStatus"] = "已切片"
        version["vectorStatus"] = "已向量化"
        for knowledge_file in repo.state.get("knowledge_files", []):
            if str(knowledge_file.get("documentVersionId") or "") == version_id:
                knowledge_file["ocrStatus"] = "已识别"
                knowledge_file["sliceStatus"] = "已切片"
                knowledge_file["vectorStatus"] = "已向量化"
    return applied


def mark_ocr_pipeline_complete(document_id: str) -> None:
    run_ocr_pipeline(document_id)


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


def test_inline_review_readiness_is_explicitly_local_only(monkeypatch) -> None:
    """Strict production must not accidentally treat the local inline executor as deployable."""
    from libs.integrations import task_dispatcher

    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", "inline")
    monkeypatch.delenv("AICHECK_STRICT_PRODUCTION", raising=False)

    local = task_dispatcher.ai_recheck_dispatch_readiness()

    assert local["ready"] is True
    assert local["mode"] == "inline"
    assert local["statusReason"] == "inline_local_development_enabled"
    assert local["deploymentScope"] == "local_development"

    monkeypatch.setenv("AICHECK_STRICT_PRODUCTION", "true")

    production = task_dispatcher.ai_recheck_dispatch_readiness()

    assert production["ready"] is False
    assert production["mode"] == "inline"
    assert production["statusReason"] == "inline_local_development_only"
    assert production["deploymentScope"] == "local_development"


def test_health_payload_uses_shared_dispatch_snapshot_without_second_temporal_probe(monkeypatch) -> None:
    """Health must expose the exact service/worker result that dispatch consumes."""
    from apps.api import main as api_main

    shared = {
        "runtimeReady": False,
        "workflowReady": False,
        "workflowSchemaReady": True,
        "workflowSchema": {"ready": True},
        "reviewDispatchReadiness": {
            "ready": False,
            "mode": "temporal",
            "orchestrationMode": "temporal",
            "statusReason": "temporal_worker_unavailable",
            "reasonCodes": ["temporal_worker_unavailable"],
            "dependencies": {"service": True, "schema": True, "workerHeartbeat": False},
            "dependencyDetails": {
                "workerHeartbeat": {"ready": False, "activeCount": 0, "lastSeenAt": None},
            },
        },
        "temporalReadiness": {
            "ready": False,
            "serviceConnected": True,
            "mode": "temporal",
            "address": "temporal.test:7233",
            "namespace": "default",
            "statusReason": "temporal_worker_unavailable",
        },
        "materialMappingReady": True,
        "materialMappingVersion": "test",
        "materialMappingCount": 1,
        "materialMappingHash": "sha256:test",
        "serviceReadiness": {},
    }

    def runtime_status(**kwargs):
        assert kwargs == {"refresh_review_readiness": True}
        return shared

    async def ready() -> bool:
        return True

    async def forbidden_temporal_probe():
        raise AssertionError("health_payload must not perform a second Temporal probe")

    monkeypatch.setattr(api_main, "production_runtime_status", runtime_status)
    monkeypatch.setattr(api_main, "temporal_health_status", forbidden_temporal_probe)
    monkeypatch.setattr(api_main.security_sessions, "ready", ready)
    monkeypatch.setattr(api_main, "review_workflow_metrics", lambda: {})
    monkeypatch.setattr(api_main, "raw_vault_health_status", lambda: {"ready": True})
    monkeypatch.setattr(api_main, "mineru_worker_health_status", lambda: {"ready": True})

    payload = asyncio.run(api_main.health_payload())

    assert payload["workflowReady"] is False
    assert payload["temporal"] == shared["temporalReadiness"]
    assert payload["workflowMetrics"]["reviewWorkerHeartbeat"] == {
        "ready": False,
        "activeCount": 0,
        "lastSeenAt": None,
    }
    assert payload["reviewDispatchReadiness"] == shared["reviewDispatchReadiness"]


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
        lambda project_id, node_id, run_id, **_kwargs: {"mode": "test", "taskId": f"TEST-{run_id}"},
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


# ---- OCR 环节：主链路此前从上传直接跳到提交，这段代码端到端从未被跑过 ----


def test_ocr_products_reach_the_api_with_locatable_coordinates() -> None:
    """OCR 抽取 → 字段落库 → 证据链 → API 可读，逐段断言。

    这条链是「证据可溯源」的地基：字段没落库，监检就没东西可核；证据链没 bbox，
    界面就只能报页码、画不出框。两者都属于「坏了也不会报错」的那类。
    """
    document_id = upload_document("焊工证-OCR链路.pdf", "ocr-chain")
    applied = run_ocr_pipeline(document_id)

    assert applied["status"] != "failed", f"OCR 应判定为可用：{applied}"
    assert applied["fieldCount"] == 3, f"三个字段都要落库，实际 {applied['fieldCount']}"

    fields = ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/documents/{document_id}/ocr-fields",
            headers=INSPECTION,
        ),
        "读 OCR 字段",
    )
    by_name = {str(item["fieldName"]): item for item in fields}
    assert set(by_name) == {"证书编号", "姓名", "合格项目"}, f"字段有丢失：{sorted(by_name)}"
    assert by_name["证书编号"]["fieldValue"] == "TS6J-2024-03158"

    # 低置信度字段必须落库并被标出来，而不是悄悄丢掉——丢掉的结果是监检
    # 根本看不到这一项，也就不会去核对（M-7 的病根）
    assert by_name["合格项目"]["reviewStatus"] == "低置信度"
    assert by_name["证书编号"]["reviewStatus"] == "已确认"

    # 页码要跟着字段走：合格项目在第 2 页，界面据此跳页
    assert by_name["合格项目"]["pageNo"] == 2

    detail = ok(
        client.get(
            f"/api/projects/{PROJECT_ID}/documents/{document_id}",
            headers=INSPECTION,
        ),
        "读文档详情",
    )
    links = detail.get("evidenceLinks") or []
    assert len(links) >= 3, f"每个字段都应生成证据链条目，实际 {len(links)}"

    # bbox 是前端画高亮的唯一依据。后端为它付了完整代价（必填校验、
    # bboxCoverage 就绪度指标），这里断言它真的能一路传到 API。
    linked = {str(item.get("fieldName")): item for item in links}
    assert linked["证书编号"]["bbox"] == [120, 240, 420, 286]
    assert linked["合格项目"]["pageNo"] == 2

    # 字段 → 证据链的引用必须接得上，否则界面拿字段查不到坐标
    evidence_ids = {str(item.get("id")) for item in links}
    for name, field in by_name.items():
        assert str(field.get("evidenceLinkId")) in evidence_ids, f"{name} 的证据引用断了"


def test_failed_ocr_blocks_submission_instead_of_passing_an_empty_shell() -> None:
    """OCR 失败时不能让空壳资料混进审查视野（U-5 的端到端形态）。"""
    document_id = upload_document("扫描失败件.pdf", "ocr-failed")
    applied = run_ocr_pipeline(
        document_id,
        {"fileName": "扫描失败件.pdf", "status": "failed", "fragments": [], "fields": []},
    )
    assert applied["status"] == "failed"
    assert applied["fieldCount"] == 0

    binding_id = bind_to_node(document_id, "ocr-failed")
    response = client.post(
        f"/api/projects/{PROJECT_ID}/submissions",
        headers={**CONTRACTOR, "Idempotency-Key": "ocr-failed-submit", "If-Match": "*"},
        json={"nodeIds": [NODE_ID], "bindingIds": [binding_id], "batchName": "失败件提交"},
    )
    payload = response.json()
    assert payload["code"] != 0, "OCR 失败的资料不该能提交"
    assert document_id in (payload.get("data") or {}).get("incompleteDocumentIds", []), payload

    # 失败必须留下可诊断的痕迹，而不是只把状态置为失败
    document = repo.find_one("documents", document_id)
    assert document["currentOcrStatus"] == "识别失败"
