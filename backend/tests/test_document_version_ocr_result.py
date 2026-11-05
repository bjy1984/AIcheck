"""平台上一份资料一版已有的识别结果（2026-11-04）。

节点审计 skill 原来把服务器节点上已经识别过的原件再上传、再跑一遍 MinerU：服务器多存一份含身份证号的原件、
多等十几分钟、轮询时每次整表加载。现在先取平台现成的那份——审查读的也是这一份。

但只能复用 MinerU（含千问兜底）出的：导入的测试场景用本机 OCR（macos_vision_ocr_v1），没有表格和印章，
skill 读它会比自己识别差。所以接口要如实说是哪个引擎出的、能不能复用。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from starlette.requests import Request

from apps.api import mineru_ocr_routes as m
from libs.data_service_ocr_result import (
    document_version_ocr_payload,
    latest_version_parse_result,
    parse_result_provider,
)

MINERU = {
    "id": "PARSE-AAA",
    "parseResultId": "PARSE-AAA",
    "documentVersionId": "VER-1",
    "parserVersion": "mineru-vlm-adapter@1",
    "engineRuns": [{"engine": "mineru_vlm", "provider": "mineru"}],
    "finishedAt": "2026-11-01T10:00:00",
    "pages": [{"pageNo": 1}, {"pageNo": 2}],
    "fragments": [{"pageNo": 1, "text": "焊工证", "readingOrder": 1}, {"pageNo": 2, "text": "第二页"}],
    "seals": [{"pageNo": 2, "text": "某某公司"}],
}
VISION_IMPORT = {
    "id": "PARSE-SCAN-1",
    "parseResultId": "PARSE-SCAN-1",
    "documentVersionId": "VER-1",
    "parserVersion": "scan_ocr_classifier_v1",
    "engineVersion": "macos_vision_ocr_v1",
    "engineRuns": [{"engine": "scan_ocr_import", "status": "success"}],
    "pages": [{"pageNo": 1}],
    "fragments": [{"pageNo": 1, "text": "x"}],
}


def test_认出是哪个引擎出的():
    assert parse_result_provider(MINERU) == "mineru"
    assert parse_result_provider({"parseResultId": "PARSE-QWEN-J1", "engineVersion": "aliyun-qwen-ocr"}) == "qwen"
    assert parse_result_provider(VISION_IMPORT) == "macos_vision_ocr_v1"
    assert parse_result_provider({}) == "unknown"


def test_取这一版最近完成的一份_流水线中间阶段不算():
    older = {**MINERU, "id": "OLD", "finishedAt": "2026-10-01T00:00:00"}
    stage = {**MINERU, "id": "STAGE", "finishedAt": "2026-11-03T00:00:00", "pipelineStage": "seal"}
    other_version = {**MINERU, "id": "OTHER", "documentVersionId": "VER-2", "finishedAt": "2026-11-04T00:00:00"}
    assert latest_version_parse_result([older, MINERU, stage, other_version], "VER-1")["id"] == "PARSE-AAA"
    assert latest_version_parse_result([other_version], "VER-1") is None


def test_返回和任务结果同形状_并标明能不能复用():
    payload = document_version_ocr_payload(MINERU, document_id="DOC-1", document_version_id="VER-1")
    assert payload["resultAvailable"] and payload["reusable"] and payload["ocrProvider"] == "mineru"
    assert payload["pageCount"] == 2 and payload["parseResultId"] == "PARSE-AAA"
    assert payload["fragments"][0]["text"] == "焊工证" and payload["seals"][0]["text"] == "某某公司"
    imported = document_version_ocr_payload(VISION_IMPORT, document_id="DOC-1", document_version_id="VER-1")
    assert imported["resultAvailable"] and imported["reusable"] is False
    assert imported["ocrProvider"] == "macos_vision_ocr_v1"
    assert document_version_ocr_payload(None, document_id="DOC-1", document_version_id="VER-1") == {
        "documentId": "DOC-1", "documentVersionId": "VER-1", "resultAvailable": False}


def request(role: str) -> Request:
    scope = {"type": "http", "method": "GET", "path": "/", "headers": [(b"x-role", role.encode())]}
    req = Request(scope)
    req.state.operation_id = "TEST"
    return req


def install(monkeypatch, role: str, parse_results: list, versions: dict | None = None):
    from apps.api import routes

    monkeypatch.setattr(routes, "effective_role_for_request", lambda req, x_role=None: (role, None))
    monkeypatch.setattr(routes, "document_read_scope_error", lambda req, project_id, document_id: None)
    versions = versions if versions is not None else {"VER-1": {"id": "VER-1", "documentId": "DOC-1"}}
    view = SimpleNamespace(find_one=lambda collection, item_id: versions.get(item_id) if collection == "versions" else None,
                           state={"ocr_parse_results": parse_results})
    monkeypatch.setattr(m, "repo", SimpleNamespace(project_document_read_view=lambda project_id: view))


def body(response) -> dict:
    return response if isinstance(response, dict) else json.loads(response.body)


def test_监检能取到_施工方无损建设方不能(monkeypatch):
    for role in ("inspection", "admin"):
        install(monkeypatch, role, [MINERU])
        ok_body = body(m.get_document_version_ocr_result(request(role), "P-1", "DOC-1", "VER-1"))
        assert ok_body["code"] == 0 and ok_body["data"]["reusable"] and ok_body["data"]["fragments"]
    for role in ("contractor", "ndt", "owner"):
        install(monkeypatch, role, [MINERU])
        denied = body(m.get_document_version_ocr_result(request(role), "P-1", "DOC-1", "VER-1"))
        assert denied["code"] == 403 and "data" in denied and not denied["data"].get("fragments"), role


def test_版本不属于这份资料就是不存在(monkeypatch):
    install(monkeypatch, "inspection", [MINERU], versions={"VER-1": {"id": "VER-1", "documentId": "DOC-OTHER"}})
    assert body(m.get_document_version_ocr_result(request("inspection"), "P-1", "DOC-1", "VER-1"))["code"] == 40404
    install(monkeypatch, "inspection", [MINERU], versions={})
    assert body(m.get_document_version_ocr_result(request("inspection"), "P-1", "DOC-1", "VER-9"))["code"] == 40404


def test_还没有识别结果时如实说没有(monkeypatch):
    install(monkeypatch, "inspection", [])
    data = body(m.get_document_version_ocr_result(request("inspection"), "P-1", "DOC-1", "VER-1"))["data"]
    assert data == {"documentId": "DOC-1", "documentVersionId": "VER-1", "resultAvailable": False}
