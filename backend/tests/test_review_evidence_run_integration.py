from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo
from libs.db.seed import PROJECT_ID
from libs.integrations import task_dispatcher
from libs.review_orchestrator.execution import (
    create_review_run_from_ai_run,
    review_run_state_records,
)


client = TestClient(app)


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def _assert_ok(response) -> dict:
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def _mount_ocr_document(
    *,
    document_id_hint: str,
    file_name: str,
    material_type_code: str,
    quoted_text: str,
) -> str:
    document, version = repo.create_document(
        PROJECT_ID,
        file_name,
        "application/pdf",
        material_category="资质证照" if material_type_code == "design_license" else "设计文件",
    )
    document["materialTypeCode"] = material_type_code
    parse_result = {
        "status": "success",
        "documentType": material_type_code,
        "fileName": file_name,
        "artifactHash": f"sha256:{document_id_hint.lower()}",
        "fields": [
            {
                "fieldName": "OCR全文",
                "fieldValue": quoted_text,
                "pageNo": 1,
                "bbox": [10, 20, 500, 80],
                "confidence": 0.96,
            }
        ],
        "fragments": [
            {
                "id": f"FRAG-{document_id_hint}",
                "pageNo": 1,
                "text": quoted_text,
                "bbox": [10, 20, 500, 80],
                "confidence": 0.96,
            }
        ],
        "tables": [],
        "seals": [],
    }
    repo.apply_ocr_result(document["id"], version["id"], parse_result)
    repo.state["node_evidence_links"].append(
        {
            "id": f"NEL-{document_id_hint}",
            "projectId": PROJECT_ID,
            "nodeId": 1,
            "nodeName": "设计单位许可资质",
            "reviewPointId": f"REQ-{document_id_hint}",
            "documentId": document["id"],
            "documentVersionId": version["id"],
            "fileName": file_name,
            "materialTypeCode": material_type_code,
            "materialTypeName": file_name,
            "requiredType": "必传",
            "supportStatus": "命中",
            "confidence": 0.96,
            "matchedEvidenceItems": [quoted_text],
            "manualStatus": "confirmed",
            "revision": 1,
            "source": "test",
        }
    )
    return version["id"]


def _allow_dispatch(monkeypatch) -> None:
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


def test_later_upload_review_run_uses_all_current_node_documents(monkeypatch) -> None:
    _allow_dispatch(monkeypatch)
    license_version = _mount_ocr_document(
        document_id_hint="LICENSE",
        file_name="设计许可证.pdf",
        material_type_code="design_license",
        quoted_text="许可证编号TS1844171-2028，工业管道GC1覆盖GC2。",
    )

    first = _assert_ok(
        client.post(
            f"/projects/{PROJECT_ID}/inspection/nodes/1/ai-recheck",
            json={"reviewMode": "gap_precheck"},
        )
    )["latestRun"]

    drawing_version = _mount_ocr_document(
        document_id_hint="DRAWING",
        file_name="施工图.pdf",
        material_type_code="design_document",
        quoted_text="设计单位广东政和工程有限公司，压力管道级别GC2。",
    )
    second = _assert_ok(
        client.post(
            f"/projects/{PROJECT_ID}/inspection/nodes/1/ai-recheck",
            json={"reviewMode": "gap_precheck"},
        )
    )["latestRun"]

    assert first["evidenceSnapshotHash"] != second["evidenceSnapshotHash"]
    assert first["inputDocumentVersionIds"] == [license_version]
    assert second["inputDocumentVersionIds"] == sorted([license_version, drawing_version])
    assert second["evidenceManifestId"]
    assert second["evidenceShardIds"]
    assert second["evidenceCoverage"]["structuralCoveragePassed"] is True
    assert second["evidenceCoverage"]["processingCoveragePassed"] is False
    assert second["evidenceCoverage"]["coveragePassed"] is False


def test_review_run_copies_and_flushes_the_persisted_evidence_package(monkeypatch) -> None:
    _allow_dispatch(monkeypatch)
    _mount_ocr_document(
        document_id_hint="LICENSE",
        file_name="设计许可证.pdf",
        material_type_code="design_license",
        quoted_text="许可证编号TS1844171-2028，工业管道GC1覆盖GC2。",
    )
    ai_run = _assert_ok(
        client.post(
            f"/projects/{PROJECT_ID}/inspection/nodes/1/ai-recheck",
            json={
                "reviewMode": "gap_precheck",
                "projectReviewRunId": "PRRUN-PARENT-1",
                "triggerType": "manual_full",
                "autoReviewPolicyRevision": 3,
            },
        )
    )["latestRun"]

    review_run = create_review_run_from_ai_run(ai_run, mode="inline")
    records = review_run_state_records(review_run["reviewRunId"])

    assert review_run["evidenceSnapshotId"] == ai_run["evidenceSnapshotId"]
    assert review_run["evidenceManifestId"] == ai_run["evidenceManifestId"]
    assert review_run["evidenceShardIds"] == ai_run["evidenceShardIds"]
    assert review_run["projectReviewRunId"] == "PRRUN-PARENT-1"
    assert review_run["triggerType"] == "manual_full"
    assert review_run["autoReviewPolicyRevision"] == 3
    assert records["evidence_snapshots"][0]["reviewRunId"] == review_run["reviewRunId"]
    assert records["evidence_manifests"][0]["reviewRunId"] == review_run["reviewRunId"]
    assert records["evidence_shards"]
    assert all(
        row["reviewRunId"] == review_run["reviewRunId"]
        for row in records["evidence_shards"]
    )
