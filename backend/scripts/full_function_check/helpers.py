"""几个用例共用的操作：上传一份 PDF、挂到节点、把 OCR 跑完（进程内替身）。"""

from __future__ import annotations

import hashlib
from typing import Any

from scripts.full_function_check.base import Context, RoleSession, check, skip

PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"

# 贴近真实 OCR 产物：带页码、bbox，置信度有高有低（同 tests/test_main_chain_e2e.py）。
WELDER_CERT_OCR = {
    "status": "success",
    "fragments": [
        {"text": "特种设备作业人员证", "pageNo": 1, "bbox": [100, 120, 520, 180]},
        {"text": "证书编号 TS6J-2024-03158", "pageNo": 1, "bbox": [120, 240, 420, 286]},
        {"text": "姓名 王建国", "pageNo": 1, "bbox": [120, 300, 260, 344]},
        {
            "text": "合格项目 GTAW-FeII-6G-3/57-FefS-02/11/12",
            "pageNo": 2,
            "bbox": [118, 402, 560, 448],
        },
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
            "fieldName": "合格项目",
            "fieldValue": "GTAW-FeII-6G-3/57-FefS-02/11/12",
            "pageNo": 2,
            "bbox": [118, 402, 560, 448],
            "confidence": 0.61,
        },
    ],
}


def upload_pdf(
    session: RoleSession, project: str, file_name: str, *, payload: bytes = PDF_BYTES
) -> dict[str, str]:
    """真实上传三步：建会话 → PUT 内容 → 完成（带大小与哈希）。回 documentId / documentVersionId。"""
    created = session.ok(
        "POST",
        f"/api/projects/{project}/documents/upload-session",
        json={
            "files": [
                {"fileName": file_name, "fileSize": len(payload), "contentType": "application/pdf"}
            ]
        },
    )
    target = (created.get("uploadUrls") or [{}])[0]
    check(target.get("url") and target.get("documentId"), f"上传会话没给上传地址：{created}")
    put = session.call(
        "PUT", str(target["url"]), headers=dict(target.get("headers") or {}), content=payload
    )
    check(put.http == 200 and put.code == 0, f"PUT 文件内容失败：{put.brief()}")
    session.ok(
        "POST",
        f"/api/projects/{project}/documents/upload-session/{created['uploadSessionId']}/complete",
        json={
            "completedFiles": [
                {
                    "documentVersionId": target["documentVersionId"],
                    "fileSize": len(payload),
                    "contentHash": hashlib.sha256(payload).hexdigest(),
                }
            ]
        },
    )
    return {
        "documentId": str(target["documentId"]),
        "documentVersionId": str(target["documentVersionId"]),
    }


def finish_ocr(
    ctx: Context, document_id: str, file_name: str, result: dict[str, Any] | None = None
) -> dict[str, Any]:
    """进程内替身：走真实的 OCR 落库（repo.apply_ocr_result），切片/向量化直接置完成。

    打服务时没有替身：等服务器自己的 OCR 工人，没识别完就跳过依赖它的用例。
    """
    if not ctx.in_process:
        skip("打服务模式下不替 OCR 工人干活；需要识别完成的步骤跳过")
    from libs.db.repository import repo

    document = repo.find_one("documents", document_id)
    check(document, f"资料 {document_id} 不存在")
    version_id = str(document.get("currentVersionId") or "")
    applied = repo.apply_ocr_result(
        document_id, version_id, {"fileName": file_name, **(result or WELDER_CERT_OCR)}
    )
    version = repo.find_one("versions", version_id) or {}
    if str(version.get("ocrStatus") or "") == "已识别":
        version["sliceStatus"] = "已切片"
        version["vectorStatus"] = "已向量化"
        for knowledge_file in repo.state.get("knowledge_files", []):
            if str(knowledge_file.get("documentVersionId") or "") == version_id:
                knowledge_file.update(
                    {"ocrStatus": "已识别", "sliceStatus": "已切片", "vectorStatus": "已向量化"}
                )
    return applied


def bind(session: RoleSession, project: str, document_id: str, node: int) -> str:
    """挂到节点，回 bindingId。"""
    data = session.ok(
        "POST",
        f"/api/projects/{project}/documents/bindings",
        json={"bindings": [{"documentId": document_id, "nodeId": node}]},
    )
    for key in ("bindingIds", "createdBindingIds"):
        ids = (data or {}).get(key) if isinstance(data, dict) else None
        if ids:
            return str(ids[0])
    for item in (data or {}).get("bindings") or [] if isinstance(data, dict) else []:
        if str(item.get("documentId")) == document_id:
            return str(item.get("id"))
    package = session.ok_get(f"/api/projects/{project}/nodes/{node}/package")
    for item in package.get("bindings") or []:
        if str(item.get("documentId")) == document_id:
            return str(item.get("id"))
    raise AssertionError(f"挂载后找不到 {document_id} 的挂载记录：{data}")


def node_status(session: RoleSession, project: str, node: int) -> str:
    package = session.ok_get(f"/api/projects/{project}/nodes/{node}/package")
    return str((package.get("node") or {}).get("status") or "")


def seed_confirmed_evidence(
    ctx: Context, project: str, node: int, document: dict[str, str]
) -> list[str]:
    """进程内替身：给节点每个必传审查点补一条「监检已确认」的证据（同 tests/test_contract.py 的做法）。

    页面上这一步是监检逐条点「确认」；演示数据只上传了焊工证，其他必传类型没有资料可确认，
    要走到「已通过」只能补齐。打服务模式下不做，依赖它的用例跳过。
    """
    if not ctx.in_process:
        skip("打服务模式下不补证据")
    from libs.db.repository import repo
    from libs.material_targeting import review_points_for_project

    record = repo.require_project(project)
    points = [
        p
        for p in review_points_for_project(repo, record, node_id=node)
        if p.get("requiredType") != "可选"
    ]
    ids: list[str] = []
    for index, point in enumerate(points, start=1):
        link_id = f"NEL-FULLCHECK-{node}-{index}"
        if not repo.find_one("node_evidence_links", link_id):
            repo.state["node_evidence_links"].append(
                {
                    "id": link_id,
                    "projectId": project,
                    "nodeId": node,
                    "nodeName": point.get("nodeName"),
                    "reviewPointId": point.get("id"),
                    "reviewContent": point.get("reviewContent"),
                    "materialTypeCode": point.get("materialTypeCode"),
                    "materialTypeName": point.get("materialTypeName"),
                    "requiredType": point.get("requiredType"),
                    "documentId": document["documentId"],
                    "documentVersionId": document["documentVersionId"],
                    "fileName": "全功能验收-补充焊工证.pdf",
                    "pageNo": 1,
                    "bbox": [10, 20, 180, 42],
                    "fieldName": "证书编号",
                    "quotedText": "TS6J-2024-03158",
                    "matchedEvidenceItems": ["TS6J-2024-03158"],
                    "supportStatus": "supported",
                    "confidence": 0.96,
                    "manualStatus": "confirmed",
                    "manualStatusLabel": "已确认",
                    "confirmedByName": "张工",
                    "confirmedAt": "2026-11-05 00:00:00",
                    "source": "fullcheck_confirmed_evidence",
                    "createdAt": "2026-11-05 00:00:00",
                }
            )
        ids.append(link_id)
    return ids
