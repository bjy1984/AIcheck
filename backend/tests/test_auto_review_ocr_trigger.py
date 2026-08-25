from __future__ import annotations

from libs.db.repository import repo


def setup_function() -> None:
    repo.reset()


def _enable_realtime(project_id: str) -> None:
    repo.state["auto_review_policies"].append(
        {
            "id": f"ARP-{project_id}",
            "tenantId": "TENANT-DEFAULT",
            "projectId": project_id,
            "enabled": True,
            "triggerModes": ["ocr_mounted"],
            "reviewMode": "gap_precheck",
            "revision": 1,
        }
    )


def _ocr_document(project_id: str = "P-2026-HDCP-001") -> tuple[dict, dict]:
    document, version = repo.create_document(project_id, "设计许可证.pdf", "application/pdf")
    result = {
        "status": "success",
        "fields": [],
        "tables": [],
        "seals": [],
        "fragments": [
            {
                "id": "FRAG-1",
                "pageNo": 1,
                "text": "许可证编号TS1844171-2028",
                "bbox": [1, 2, 30, 40],
            }
        ],
    }
    job = repo.create_ocr_job_record(
        document_id=document["id"],
        version_id=version["id"],
        storage_key=version["storageKey"],
        file_name=document["fileName"],
        document_type="design_license",
    )
    repo.finish_ocr_job_record(job, result)
    repo.apply_ocr_result(document["id"], version["id"], result)
    return document, version


def test_disabled_policy_does_not_enqueue_mount_event() -> None:
    from libs.auto_review import enqueue_auto_review_evidence_event

    event, created = enqueue_auto_review_evidence_event(
        repo.state,
        tenant_id="TENANT-DEFAULT",
        project_id="P-1",
        document_version_id="DV-1",
        node_ids=[1],
        mount_revision=1,
    )

    assert event is None
    assert created is False
    assert repo.state["auto_review_outbox"] == []


def test_realtime_policy_enqueues_one_deduplicated_event_for_affected_nodes() -> None:
    from libs.auto_review import enqueue_auto_review_evidence_event

    _enable_realtime("P-1")
    first, created = enqueue_auto_review_evidence_event(
        repo.state,
        tenant_id="TENANT-DEFAULT",
        project_id="P-1",
        document_version_id="DV-1",
        node_ids=[2, 1, 2],
        mount_revision=4,
    )
    duplicate, duplicate_created = enqueue_auto_review_evidence_event(
        repo.state,
        tenant_id="TENANT-DEFAULT",
        project_id="P-1",
        document_version_id="DV-1",
        node_ids=[1, 2],
        mount_revision=4,
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate["id"] == first["id"]
    assert first["nodeIds"] == [1, 2]
    assert first["status"] == "pending"
    assert len(repo.state["auto_review_outbox"]) == 1


def test_document_intelligence_enqueues_after_targeting_created_links(monkeypatch) -> None:
    from libs import document_intelligence

    document, version = _ocr_document()
    _enable_realtime(document["projectId"])
    monkeypatch.setattr(
        document_intelligence,
        "classify_material",
        lambda **_kwargs: {"materialTypeCode": "design_license", "classificationStatus": "classified"},
    )
    monkeypatch.setattr(
        document_intelligence,
        "run_material_targeting",
        lambda *_args, **_kwargs: {
            "id": "MTR-1",
            "status": "completed",
            "createdLinks": [{"nodeId": 2}, {"nodeId": 1}, {"nodeId": 1}],
            "createdLinkCount": 3,
            "createdBindingCount": 2,
        },
    )

    result = document_intelligence.process_document_classification_and_targeting(
        repo,
        document["projectId"],
        document["id"],
        version["id"],
        triggered_by="test",
    )

    assert result["status"] == "completed"
    assert result["targeting"]["autoReviewEventId"]
    assert repo.state["auto_review_outbox"][0]["nodeIds"] == [1, 2]


def test_auto_review_event_failure_does_not_change_document_intelligence_success(monkeypatch) -> None:
    from libs import document_intelligence

    document, version = _ocr_document()
    _enable_realtime(document["projectId"])
    monkeypatch.setattr(
        document_intelligence,
        "classify_material",
        lambda **_kwargs: {"materialTypeCode": "design_license", "classificationStatus": "classified"},
    )
    monkeypatch.setattr(
        document_intelligence,
        "run_material_targeting",
        lambda *_args, **_kwargs: {
            "id": "MTR-1",
            "status": "completed",
            "createdLinks": [{"nodeId": 1}],
            "createdLinkCount": 1,
            "createdBindingCount": 1,
        },
    )
    monkeypatch.setattr(
        document_intelligence,
        "enqueue_auto_review_evidence_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("queue unavailable")),
    )

    result = document_intelligence.process_document_classification_and_targeting(
        repo,
        document["projectId"],
        document["id"],
        version["id"],
        triggered_by="test",
    )

    assert result["status"] == "completed"
    assert result["targeting"]["autoReviewDispatch"]["status"] == "not_enqueued"


def test_ocr_persistence_scope_includes_auto_review_event_for_same_version() -> None:
    from apps.worker.tasks import ocr_result_state_records

    repo.state["auto_review_outbox"].append(
        {
            "id": "AREVT-PERSIST",
            "projectId": "P-2026-HDCP-001",
            "documentVersionId": "DV-PERSIST-1",
            "nodeIds": [1],
            "status": "pending",
        }
    )

    records = ocr_result_state_records("DOC-PERSIST-1", "DV-PERSIST-1")

    assert records["auto_review_outbox"] == [repo.state["auto_review_outbox"][0]]
