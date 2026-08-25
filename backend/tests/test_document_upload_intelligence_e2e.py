from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api import routes as routes_module
from apps.api.main import app
from apps.worker import tasks
from libs.business_pack import load_business_pack
from libs.db.repository import repo
from libs.integrations import task_dispatcher
from libs.material_targeting import targeting_input_versions_for_node


client = TestClient(app)
PROJECT_ID = "P-2026-HDCP-001"
PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
CONTRACTOR = {
    "X-Dev-Role": "contractor",
    "X-Dev-User": "USER-CONTRACTOR-001",
    "X-Role": "contractor",
}
NDT = {
    "X-Dev-Role": "ndt",
    "X-Dev-User": "USER-NDT-001",
    "X-Role": "ndt",
}
INSPECTION = {
    "X-Dev-Role": "inspection",
    "X-Dev-User": "USER-INSPECTION-001",
    "X-Role": "inspection",
}


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def _ok(response, step: str) -> dict[str, Any]:
    assert response.status_code == 200, f"[{step}] HTTP {response.status_code}: {response.text}"
    payload = response.json()
    assert payload.get("code") == 0, f"[{step}] {payload}"
    return payload.get("data") or {}


def _upload(file_name: str, headers: dict[str, str], key: str) -> tuple[dict, dict]:
    session = _ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session",
            headers={**headers, "Idempotency-Key": f"{key}-session"},
            json={
                "files": [
                    {
                        "fileName": file_name,
                        "fileSize": len(PDF_BYTES),
                        "fileType": "application/pdf",
                    }
                ]
            },
        ),
        f"{key}:session",
    )
    target = session["uploadUrls"][0]
    put_response = client.put(
        target["url"].removeprefix("/api"),
        headers={**headers, **target["headers"]},
        content=PDF_BYTES,
    )
    _ok(put_response, f"{key}:put")
    _ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/documents/upload-session/{session['uploadSessionId']}/complete",
            headers={**headers, "Idempotency-Key": f"{key}-complete"},
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
        f"{key}:complete",
    )
    document = repo.find_one("documents", target["documentId"])
    version = repo.find_one("versions", target["documentVersionId"])
    assert document is not None
    assert version is not None
    assert routes_module.document_body_uploaded(document, version)
    return document, version


def _ocr_result(
    *,
    file_name: str,
    material_type: str,
    evidence: list[tuple[str, str]],
) -> dict[str, Any]:
    text = "；".join(f"{name}：{value}" for name, value in evidence)
    return {
        "parseResultId": f"PARSE-E2E-{material_type.upper()}",
        "status": "success",
        "outcomeStatus": "completed",
        "fileName": file_name,
        "documentType": material_type,
        "profileId": f"{material_type}_v1",
        "fragments": [
            {
                "pageNo": 1,
                "text": text,
                "bbox": [10, 10, 580, 300],
                "confidence": 0.96,
            }
        ],
        "fields": [
            {
                "fieldName": name,
                "fieldValue": value,
                "pageNo": 1,
                "bbox": [20, 20 + index * 28, 500, 44 + index * 28],
                "confidence": 0.95,
            }
            for index, (name, value) in enumerate(evidence)
        ],
        "tables": [],
        "seals": [],
        "quality": {"status": "usable", "blockingReasons": []},
    }


def _apply_ocr_slice_and_vectorize(
    monkeypatch: pytest.MonkeyPatch,
    document: dict,
    version: dict,
    result: dict[str, Any],
) -> dict[str, Any]:
    monkeypatch.setattr(tasks, "refresh_worker_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "refresh_ocr_worker_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "sync_state_records", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "flush_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "flush_state_records", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("AICHECK_EMBEDDING_FORCE_OFFLINE_HASH", "true")
    job = repo.create_ocr_job_record(
        document_id=document["id"],
        version_id=version["id"],
        storage_key=version["storageKey"],
        file_name=document["fileName"],
        document_type=result.get("documentType"),
        profile_id=result.get("profileId"),
    )
    repo.finish_ocr_job_record(job, deepcopy(result))
    previous_ids = tasks.state_record_ids(tasks.ocr_result_state_records(document["id"], version["id"]))
    applied, intelligence = tasks.pipeline_apply_result(
        document["id"],
        version["id"],
        deepcopy(result),
        previous_ids,
    )
    assert applied["status"] == "success"
    knowledge_file = repo.knowledge_file_for_version(version["id"])
    assert knowledge_file is not None
    sliced = tasks.slice_knowledge.run(knowledge_file["id"], False)
    assert sliced["status"] == "success"
    embedded = tasks.embed_knowledge.run(knowledge_file["id"], 0, False)
    assert embedded["status"] == "success"
    assert routes_module.document_upload_pipeline_complete(document)
    return intelligence


CASES = [
    (
        "扫描件-设计许可.pdf",
        "design_license",
        1,
        CONTRACTOR,
        [
            ("设计许可证机构名称", "华东设计院有限公司"),
            ("许可范围", "压力管道设计 GC1"),
            ("许可级别", "GC1"),
            ("有效期", "2029-08-11"),
            ("印章", "设计许可专用章"),
        ],
    ),
    (
        "扫描件-质量证明.pdf",
        "quality_certificate",
        16,
        CONTRACTOR,
        [
            ("制造单位", "河北管件制造有限公司"),
            ("产品名称", "无缝钢管"),
            ("规格", "DN50"),
            ("材质牌号", "20#"),
            ("批号/炉号", "H20260821"),
            ("证书编号", "Q-2026-0821"),
        ],
    ),
    (
        "扫描件-焊工资格.pdf",
        "welder_certificate",
        24,
        CONTRACTOR,
        [
            ("姓名", "王建国"),
            ("证书编号", "TS6J-2024-03158"),
            ("持证合格项目", "GTAW-FeII-6G"),
            ("有效期至", "2029-12-31"),
        ],
    ),
    (
        "扫描件-无损报告.pdf",
        "ndt_report",
        40,
        NDT,
        [
            ("报告编号", "RT-2026-0821"),
            ("方法", "RT"),
            ("焊口编号", "W-001"),
            ("比例", "100%"),
            ("结论", "合格"),
            ("印章", "无损检测专用章"),
        ],
    ),
]


@pytest.mark.parametrize(("file_name", "material_type", "node_id", "headers", "evidence"), CASES)
def test_ordinary_upload_classifies_and_targets_expected_node(
    monkeypatch: pytest.MonkeyPatch,
    file_name: str,
    material_type: str,
    node_id: int,
    headers: dict[str, str],
    evidence: list[tuple[str, str]],
) -> None:
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "disabled")
    document, version = _upload(file_name, headers, f"e2e-{material_type}")
    intelligence = _apply_ocr_slice_and_vectorize(
        monkeypatch,
        document,
        version,
        _ocr_result(file_name=file_name, material_type=material_type, evidence=evidence),
    )

    assert document["materialTypeCode"] == material_type
    assert intelligence["classification"]["classificationConfidence"] > 0
    matching_bindings = [
        binding
        for binding in repo.state["bindings"]
        if binding.get("documentVersionId") == version["id"]
        and int(binding.get("nodeId") or 0) == node_id
        and str(binding.get("id") or "").startswith("BIND-AUTO-")
    ]
    assert len(matching_bindings) == 1
    assert matching_bindings[0]["bindingStatus"] == "草稿挂载"


def test_classified_ordinary_upload_can_submit_automatic_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "disabled")
    file_name, material_type, node_id, upload_headers, evidence = CASES[0]
    document, version = _upload(file_name, upload_headers, "e2e-submit")
    _apply_ocr_slice_and_vectorize(
        monkeypatch,
        document,
        version,
        _ocr_result(file_name=file_name, material_type=material_type, evidence=evidence),
    )
    binding = next(
        item
        for item in repo.state["bindings"]
        if item.get("documentVersionId") == version["id"] and int(item.get("nodeId") or 0) == node_id
    )
    member = next(
        item
        for item in repo.state["project_members"]
        if item.get("projectId") == PROJECT_ID
        and item.get("userId") == "USER-CONTRACTOR-001"
        and item.get("role") == "contractor"
    )
    member["nodeScope"] = sorted(
        set(member.get("nodeScope") or [])
        | set(routes_module.document_node_ids(PROJECT_ID, document["id"]))
    )

    submitted = _ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/submissions",
            headers={**upload_headers, "Idempotency-Key": "e2e-auto-binding-submit", "If-Match": "*"},
            json={"nodeIds": [node_id], "bindingIds": [binding["id"]], "batchName": "自动打靶提交"},
        ),
        "submit",
    )

    assert submitted["bindingIds"] == [binding["id"]]
    assert repo.find_one("bindings", binding["id"])["bindingStatus"] == "已提交"


def test_zero_signal_upload_is_searchable_fallback_without_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "disabled")
    document, version = _upload("扫描件-zero.pdf", CONTRACTOR, "e2e-zero")
    result = _ocr_result(
        file_name=document["fileName"],
        material_type="",
        evidence=[("内容", "无法确定资料类型但包含设计压力2.5MPa")],
    )
    result["documentType"] = ""
    result["profileId"] = ""
    intelligence = _apply_ocr_slice_and_vectorize(monkeypatch, document, version, result)

    assert document["materialTypeCode"] == "unclassified_material"
    assert intelligence["classification"]["classificationConfidence"] == 0.0
    assert not [
        binding for binding in repo.state["bindings"] if binding.get("documentVersionId") == version["id"]
    ]
    knowledge_file = repo.knowledge_file_for_version(version["id"])
    assert knowledge_file is not None
    assert document["currentOcrStatus"] == "已识别"
    assert version["ocrStatus"] == "已识别"
    assert knowledge_file["materialTypeCode"] == "unclassified_material"
    assert knowledge_file["sliceStatus"] == "已切片"
    assert knowledge_file["vectorStatus"] == "已向量化"
    repo.state["bindings"] = []
    repo.state["node_evidence_links"] = []
    assert targeting_input_versions_for_node(repo, PROJECT_ID, 1) == [version["id"]]

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
    review = _ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/inspection/nodes/1/ai-recheck",
            headers={**INSPECTION, "Idempotency-Key": "e2e-unclassified-fallback-review"},
        ),
        "unclassified-fallback-review",
    )
    assert review["latestRun"]["inputDocumentVersionIds"] == [version["id"]]
