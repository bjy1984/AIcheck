"""Office 文件在线预览（线上审计 L-4）。

线上项目的资料全是 .docx，此前在系统里完全无法查看——界面只提示「请下载后用
Word 打开」。监检得离开系统、在本地比对，再回来填结论。

先接过 ONLYOFFICE Document Server，卡在转换器 error:-7 / x2t code=88 未果
（同一文件手动跑 x2t 成功、DS 服务调用就失败，排查多轮）。改用 LibreOffice
headless 转 PDF，复用已验证可用的 PDF 预览路径。
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

# Office 预览已从 routes.py 拆到独立模块（issue #12 A-2 的增量拆分）。
# monkeypatch 必须打在真正持有这些符号的模块上——打在 routes 上不会报错，
# 只是替身没生效、用例静默测了真实实现。
import apps.api.office_preview_routes as routes_module
from apps.api.main import app
from libs.db.repository import repo
from libs.office_preview import (
    CONVERTIBLE_SUFFIXES,
    OfficeConversionFailed,
    OfficeConversionUnavailable,
    office_html_to_text,
)

client = TestClient(app)
INSPECTION = {
    "X-Dev-Role": "inspection",
    "X-Dev-User": "USER-INSPECTION-001",
    "X-Role": "inspection",
}
PROJECT_ID = "P-2026-HDCP-001"


def _office_document() -> dict | None:
    return next(
        (
            item
            for item in repo.state.get("documents", [])
            if str(item.get("projectId")) == PROJECT_ID
            and str(item.get("fileName") or "").lower().endswith((".docx", ".xlsx"))
        ),
        None,
    )


def _any_document_id() -> str:
    docs = [x for x in repo.state.get("documents", []) if str(x.get("projectId")) == PROJECT_ID]
    assert docs, "该项目没有文档，测试前提不成立"
    return str(docs[0]["id"])


def test_missing_libreoffice_says_so_instead_of_failing_obscurely(monkeypatch) -> None:
    """运行环境没装 LibreOffice 时要明说，不能让前端白转圈。"""
    monkeypatch.setattr(routes_module, "office_preview_available", lambda: False)
    response = client.get(
        f"/api/projects/{PROJECT_ID}/documents/{_any_document_id()}/office-preview",
        headers=INSPECTION,
    )
    payload = response.json()
    assert payload["code"] != 0
    assert (payload.get("data") or {}).get("reason") == "LIBREOFFICE_NOT_INSTALLED"


def test_non_office_file_is_rejected_with_its_suffix(monkeypatch) -> None:
    """PDF/图片各有自己的预览路径，不该走转换。"""
    monkeypatch.setattr(routes_module, "office_preview_available", lambda: True)
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


def test_conversion_failure_is_reported_not_swallowed(monkeypatch) -> None:
    """转换失败要如实告知并提示下载原文，不能返回一个打不开的空地址。"""
    document = _office_document()
    if document is None:
        pytest.skip("该项目没有 Office 文档")
    monkeypatch.setattr(routes_module, "office_preview_available", lambda: True)
    # 缓存查询必须返回 None，否则会走「已有产物」的快路径，根本不触发转换。
    # internal=True 是取源文件那次，得给地址。
    monkeypatch.setattr(
        routes_module.object_storage,
        "presigned_get_url",
        lambda url, **kw: "http://minio/source" if kw.get("internal") else None,
    )
    monkeypatch.setattr(
        routes_module,
        "convert_office_to_pdf",
        lambda data, name: (_ for _ in ()).throw(OfficeConversionFailed("转换未产出 PDF")),
    )
    # 端点用 `with urllib.request.urlopen(...)`，所以替身要能进上下文。
    # io.BytesIO 天生支持，不必自己造类。
    monkeypatch.setattr(
        routes_module.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"x")
    )
    response = client.get(
        f"/api/projects/{PROJECT_ID}/documents/{document['id']}/office-preview",
        headers=INSPECTION,
    )
    payload = response.json()
    assert payload["code"] != 0
    assert (payload.get("data") or {}).get("reason") == "OFFICE_CONVERSION_FAILED"




def test_role_scope_is_enforced(monkeypatch) -> None:
    """预览会签发可取文件的地址，范围校验不能少。"""
    monkeypatch.setattr(routes_module, "office_preview_available", lambda: True)
    response = client.get(
        f"/api/projects/P-2026-GDLNG-002/documents/{_any_document_id()}/office-preview",
        headers=INSPECTION,
    )
    assert response.json()["code"] == 40404, response.text


def test_preview_object_name_is_keyed_by_content_hash() -> None:
    """同一版本只转一次；内容变了哈希就变，缓存自然失效，不必手动清。"""
    first = routes_module.office_preview_object_name("DOC-1", "a" * 64)
    same = routes_module.office_preview_object_name("DOC-1", "a" * 64)
    changed = routes_module.office_preview_object_name("DOC-1", "b" * 64)
    assert first == same
    assert first != changed
    assert first.endswith(".pdf")


def test_convertible_suffixes_cover_the_formats_seen_in_real_projects() -> None:
    """范围保守：只列监检资料里真实出现过的，不给「什么都能预览」的错觉。"""
    for suffix in ("docx", "xlsx", "doc", "xls"):
        assert suffix in CONVERTIBLE_SUFFIXES
    for suffix in ("pdf", "png", "zip", "exe"):
        assert suffix not in CONVERTIBLE_SUFFIXES


@pytest.mark.parametrize("suffix", ["doc", "docx", "xls", "xlsx"])
def test_document_preview_routes_convertible_office_suffixes_to_office(suffix: str) -> None:
    """老版 .doc/.xls 也必须走 LibreOffice，不能在前端被提前判成 unsupported。"""
    document = {"id": "DOC-OFFICE", "fileName": f"资料.{suffix}", "fileType": suffix}

    assert repo.document_preview_type(document) == "office"


def test_office_html_to_text_preserves_headings_and_table_cells_for_classification() -> None:
    html = """
    <html><head><style>p { font-size: 12pt; }</style></head><body>
      <h1>施工组织设计</h1>
      <table><tr><th>工程名称</th><td>储罐区压力管道</td></tr></table>
      <p>施工进度计划</p>
    </body></html>
    """

    text = office_html_to_text(html)

    assert "施工组织设计" in text
    assert "工程名称" in text
    assert "储罐区压力管道" in text
    assert "施工进度计划" in text
    assert "font-size" not in text


def test_conversion_module_raises_when_libreoffice_is_absent(monkeypatch) -> None:
    """模块层：没有 soffice 就抛明确异常，而不是返回空字节。"""
    import libs.office_preview as office

    monkeypatch.setattr(office, "soffice_executable", lambda: None)
    with pytest.raises(OfficeConversionUnavailable):
        office.convert_office_to_pdf(b"x", "a.docx")


def test_conversion_module_rejects_unsupported_suffix(monkeypatch) -> None:
    import libs.office_preview as office

    monkeypatch.setattr(office, "soffice_executable", lambda: "/usr/bin/soffice")
    with pytest.raises(OfficeConversionFailed):
        office.convert_office_to_pdf(b"x", "a.zip")


def test_cache_hit_requires_the_object_to_actually_exist() -> None:
    """缓存判据必须是「对象在不在」，不能是「能不能签发 URL」。

    线上踩过：原实现写 cached = presigned_get_url(...)，而签发是纯计算，对不
    存在的对象照样返回一个合法 URL。于是「缓存命中」永远成立、转换分支一次都
    没执行过——接口返回 200 带地址，前端一取就是 404。

    这是最贵的那种失败：所有信号都说成功了。
    """
    from apps.api import office_preview_routes as routes

    calls: list[tuple[str, str]] = []

    class _Storage:
        def object_metadata(self, bucket: str, object_name: str) -> None:
            calls.append((bucket, object_name))
            # 对象不存在

        def presigned_get_url(self, *args, **kwargs) -> str:  # pragma: no cover - 不该被当判据
            return "http://example.invalid/looks-fine-but-404"

    original = routes.object_storage
    routes.object_storage = _Storage()
    try:
        assert routes.office_preview_cached("office-preview/DOC-X/abc.pdf") is False
    finally:
        routes.object_storage = original
    assert calls, "必须实查 stat，而不是只签个 URL 就当命中"


def test_metadata_lookup_error_is_treated_as_cache_miss() -> None:
    """查不动就当没有：多转一次浪费几秒，判成「有」则是返回一个坏链接。"""
    from apps.api import office_preview_routes as routes

    class _Storage:
        def object_metadata(self, bucket: str, object_name: str) -> None:
            raise RuntimeError("网络抖动")

    original = routes.object_storage
    routes.object_storage = _Storage()
    try:
        assert routes.office_preview_cached("office-preview/DOC-X/abc.pdf") is False
    finally:
        routes.object_storage = original


def test_missing_minio_cache_object_is_treated_as_cache_miss() -> None:
    """首次预览还没有转换缓存时必须进入转换，不能把 NoSuchKey 当存储故障。"""
    from apps.api import office_preview_routes as routes
    from libs.integrations.storage import ObjectStorageUnavailable

    class _Storage:
        def object_metadata(self, bucket: str, object_name: str) -> None:
            raise ObjectStorageUnavailable(
                "对象存储文件确认失败：S3 operation failed; code: NoSuchKey, "
                "message: Object does not exist"
            )

    original = routes.object_storage
    routes.object_storage = _Storage()
    try:
        assert routes.office_preview_cached("office-preview/DOC-X/abc.pdf") is False
    finally:
        routes.object_storage = original
