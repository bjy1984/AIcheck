"""Office 在线预览配置（线上审计 L-4）。

线上项目的 10 份资料全是 .docx，此前在系统里完全无法查看——界面只提示
「请下载后用 Word 打开」。监检得离开系统、在本地比对，再回来填结论。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import apps.api.routes as routes_module
from apps.api.main import app
from libs.db.repository import repo

client = TestClient(app)
INSPECTION = {
    "X-Dev-Role": "inspection",
    "X-Dev-User": "USER-INSPECTION-001",
    "X-Role": "inspection",
}
CONTRACTOR = {
    "X-Dev-Role": "contractor",
    "X-Dev-User": "USER-CONTRACTOR-001",
    "X-Role": "contractor",
}
PROJECT_ID = "P-2026-HDCP-001"


def _first_document_id() -> str:
    docs = [
        item
        for item in repo.state.get("documents", [])
        if str(item.get("projectId")) == PROJECT_ID
    ]
    assert docs, "该项目没有文档，测试前提不成立"
    return str(docs[0]["id"])


def test_unconfigured_service_says_so_instead_of_failing_obscurely(monkeypatch) -> None:
    """没部署时要明说「预览服务未部署」，不能给个空配置让前端白转圈。"""
    monkeypatch.setenv("AICHECK_ONLYOFFICE_BASE", "")
    response = client.get(
        f"/api/projects/{PROJECT_ID}/documents/{_first_document_id()}/office-preview",
        headers=INSPECTION,
    )
    payload = response.json()
    assert payload["code"] != 0
    assert (payload.get("data") or {}).get("reason") == "ONLYOFFICE_NOT_CONFIGURED"


def test_non_office_file_is_rejected_with_its_suffix(monkeypatch) -> None:
    """PDF/图片各有自己的预览路径，不该走 Office 服务。"""
    monkeypatch.setenv("AICHECK_ONLYOFFICE_BASE", "http://ds.example")
    document = next(
        (
            item
            for item in repo.state.get("documents", [])
            if str(item.get("projectId")) == PROJECT_ID
            and str(item.get("fileName") or "").lower().endswith(".pdf")
        ),
        None,
    )
    if document is None:
        pytest.skip("该项目没有 PDF 文档")
    response = client.get(
        f"/api/projects/{PROJECT_ID}/documents/{document['id']}/office-preview",
        headers=INSPECTION,
    )
    assert response.json()["code"] != 0


def test_config_is_view_only(monkeypatch) -> None:
    """审查场景里原始资料一旦可改，证据链就断了——权限必须全关。"""
    monkeypatch.setenv("AICHECK_ONLYOFFICE_BASE", "http://ds.example")
    monkeypatch.setattr(
        routes_module.object_storage,
        "presigned_get_url",
        lambda url, **kwargs: "http://minio:9000/documents/x?sig=1",
    )
    document = next(
        (
            item
            for item in repo.state.get("documents", [])
            if str(item.get("projectId")) == PROJECT_ID
            and str(item.get("fileName") or "").lower().endswith((".docx", ".xlsx"))
        ),
        None,
    )
    if document is None:
        pytest.skip("该项目没有 Office 文档")
    response = client.get(
        f"/api/projects/{PROJECT_ID}/documents/{document['id']}/office-preview",
        headers=INSPECTION,
    )
    payload = response.json()
    assert payload["code"] == 0, payload
    config = payload["data"]["config"]
    assert config["editorConfig"]["mode"] == "view"
    permissions = config["document"]["permissions"]
    assert not any(permissions.values()), f"存在未关闭的权限：{permissions}"


def test_document_url_uses_the_internal_endpoint(monkeypatch) -> None:
    """给 ONLYOFFICE 的地址必须是内网的。

    它和 API 在同一 docker 网络，拿到浏览器用的 127.0.0.1:19000 会去连自己的
    容器，必然取不到文件——而且这种失败很难诊断，因为签名本身合法。
    """
    monkeypatch.setenv("AICHECK_ONLYOFFICE_BASE", "http://ds.example")
    seen: dict[str, object] = {}

    def _fake_presign(url: str, **kwargs: object) -> str:
        seen.update(kwargs)
        return "http://minio:9000/documents/x?sig=1"

    monkeypatch.setattr(routes_module.object_storage, "presigned_get_url", _fake_presign)
    document = next(
        (
            item
            for item in repo.state.get("documents", [])
            if str(item.get("projectId")) == PROJECT_ID
            and str(item.get("fileName") or "").lower().endswith((".docx", ".xlsx"))
        ),
        None,
    )
    if document is None:
        pytest.skip("该项目没有 Office 文档")
    client.get(
        f"/api/projects/{PROJECT_ID}/documents/{document['id']}/office-preview",
        headers=INSPECTION,
    )
    assert seen.get("internal") is True, f"未要求内网签名：{seen}"


def test_role_scope_is_enforced(monkeypatch) -> None:
    """预览配置带着可取文件的签名地址，范围校验不能少。"""
    monkeypatch.setenv("AICHECK_ONLYOFFICE_BASE", "http://ds.example")
    response = client.get(
        f"/api/projects/P-2026-GDLNG-002/documents/{_first_document_id()}/office-preview",
        headers=INSPECTION,
    )
    assert response.json()["code"] == 40404, response.text
