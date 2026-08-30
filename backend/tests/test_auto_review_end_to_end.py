from __future__ import annotations

from datetime import UTC, datetime

from apps.worker import tasks
from libs.auto_review import (
    consume_auto_review_evidence_events,
    dispatch_pending_auto_review_candidates,
    enqueue_auto_review_evidence_event,
)
from libs.db.repository import repo
from libs.db.seed import PROJECT_ID
from libs.integrations import task_dispatcher


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def _mount(file_name: str, text: str, sequence: int) -> str:
    document, version = repo.create_document(PROJECT_ID, file_name, "application/pdf")
    repo.apply_ocr_result(
        document["id"],
        version["id"],
        {
            "status": "success",
            "artifactHash": f"sha256:ocr-{sequence}",
            "fields": [],
            "tables": [],
            "seals": [],
            "fragments": [
                {
                    "id": f"FRAG-{sequence}",
                    "pageNo": 1,
                    "text": text,
                    "bbox": [1, 2, 30, 40],
                    "confidence": 0.99,
                }
            ],
        },
    )
    repo.state["node_evidence_links"].append(
        {
            "id": f"NEL-E2E-{sequence}",
            "projectId": PROJECT_ID,
            "nodeId": 1,
            "documentId": document["id"],
            "documentVersionId": version["id"],
            "manualStatus": "confirmed",
            "revision": sequence,
        }
    )
    return version["id"]


def _trigger(version_id: str, revision: int) -> None:
    event, created = enqueue_auto_review_evidence_event(
        repo.state,
        tenant_id="TENANT-DEFAULT",
        project_id=PROJECT_ID,
        document_version_id=version_id,
        node_ids=[1],
        mount_revision=revision,
    )
    assert event and created
    consume_auto_review_evidence_events(repo.state, now=datetime.now(UTC))
    dispatch_pending_auto_review_candidates(
        repo.state,
        start_node_review=tasks._start_auto_review_node,
    )


def test_realtime_auto_review_rechecks_cumulative_node_evidence(monkeypatch) -> None:
    repo.state["node_evidence_links"] = []
    repo.state["auto_review_policies"].append(
        {
            "id": "ARP-E2E",
            "tenantId": "TENANT-DEFAULT",
            "projectId": PROJECT_ID,
            "enabled": True,
            "triggerModes": ["ocr_mounted"],
            "dailyTime": "02:00",
            "timezone": "Asia/Shanghai",
            "reviewMode": "gap_precheck",
            "revision": 1,
        }
    )
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

    license_version = _mount(
        "设计许可证.pdf",
        "许可证编号TS1844171-2028，工业管道GC1覆盖GC2。",
        1,
    )
    _trigger(license_version, 1)
    first_run = repo.state["ai_runs"][0]

    drawing_version = _mount(
        "施工图.pdf",
        "设计单位广东政和工程有限公司，压力管道级别GC2。",
        2,
    )
    _trigger(drawing_version, 2)
    second_run = repo.state["ai_runs"][0]

    assert first_run["nodeId"] == 1
    assert first_run["inputDocumentVersionIds"] == [license_version]
    assert second_run["nodeId"] == 1
    assert second_run["inputDocumentVersionIds"] == sorted(
        [license_version, drawing_version]
    )
    assert first_run["evidenceSnapshotHash"] != second_run["evidenceSnapshotHash"]
    assert second_run["projectReviewRunId"] != first_run["projectReviewRunId"]
    assert all(run["advisoryOnly"] is True for run in (first_run, second_run))
    second_parent = next(
        row
        for row in repo.state["project_review_runs"]
        if row["projectReviewRunId"] == second_run["projectReviewRunId"]
    )
    assert second_parent["nodeSnapshotHashes"] == {
        "1": second_run["evidenceSnapshotHash"]
    }
