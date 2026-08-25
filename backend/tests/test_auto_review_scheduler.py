from __future__ import annotations

from datetime import UTC, datetime

from libs.db.repository import repo


def _state_with_node() -> dict:
    return {
        "documents": [{"id": "DOC-1", "projectId": "P-1", "currentVersionId": "DV-1"}],
        "document_versions": [{"id": "DV-1", "documentId": "DOC-1", "contentHash": "sha256:doc"}],
        "versions": [{"id": "DV-1", "documentId": "DOC-1", "contentHash": "sha256:doc"}],
        "node_evidence_links": [
            {
                "id": "NEL-1",
                "projectId": "P-1",
                "nodeId": 1,
                "documentId": "DOC-1",
                "documentVersionId": "DV-1",
                "manualStatus": "confirmed",
            }
        ],
        "ocr_parse_results": [
            {"id": "OCR-1", "documentVersionId": "DV-1", "artifactHash": "sha256:ocr", "status": "success"}
        ],
        "review_runs": [],
        "ai_runs": [],
        "auto_review_candidates": [],
        "auto_review_outbox": [],
        "auto_review_policies": [
            {
                "id": "ARP-1",
                "tenantId": "TENANT-1",
                "projectId": "P-1",
                "enabled": True,
                "triggerModes": ["ocr_mounted", "daily_schedule"],
                "dailyTime": "02:00",
                "timezone": "Asia/Shanghai",
                "reviewMode": "gap_precheck",
                "debounceSeconds": 0,
                "revision": 2,
            }
        ],
    }


def test_daily_policy_uses_project_timezone_and_runs_once_per_local_day() -> None:
    from libs.auto_review import policy_due_for_daily_scan

    policy = _state_with_node()["auto_review_policies"][0]
    before = datetime(2026, 8, 25, 17, 30, tzinfo=UTC)  # Shanghai 01:30 on Aug 26
    due = datetime(2026, 8, 25, 18, 30, tzinfo=UTC)  # Shanghai 02:30 on Aug 26

    assert policy_due_for_daily_scan(policy, before) is False
    assert policy_due_for_daily_scan(policy, due) is True
    policy["lastDailyRunLocalDate"] = "2026-08-26"
    assert policy_due_for_daily_scan(policy, due) is False


def test_daily_scan_creates_dirty_candidates_and_records_local_run_date() -> None:
    from libs.auto_review import scan_due_auto_review_policies

    state = _state_with_node()
    result = scan_due_auto_review_policies(
        state,
        now=datetime(2026, 8, 25, 18, 30, tzinfo=UTC),
    )

    assert result["dueProjectIds"] == ["P-1"]
    assert result["createdCandidateIds"]
    assert state["auto_review_candidates"][0]["nodeId"] == 1
    assert state["auto_review_policies"][0]["lastDailyRunLocalDate"] == "2026-08-26"


def test_event_consumer_creates_snapshot_candidate_and_completes_event() -> None:
    from libs.auto_review import consume_auto_review_evidence_events

    state = _state_with_node()
    state["auto_review_outbox"].append(
        {
            "id": "AREVT-1",
            "eventType": "node.evidence.mounted",
            "tenantId": "TENANT-1",
            "projectId": "P-1",
            "documentVersionId": "DV-1",
            "nodeIds": [1],
            "policyRevision": 2,
            "status": "pending",
            "attemptCount": 0,
        }
    )

    result = consume_auto_review_evidence_events(
        state,
        now=datetime(2026, 8, 26, 1, 0, tzinfo=UTC),
    )

    assert result["completedEventIds"] == ["AREVT-1"]
    assert result["createdCandidateIds"]
    assert state["auto_review_outbox"][0]["status"] == "completed"
    assert state["auto_review_candidates"][0]["evidenceSnapshotHash"].startswith("sha256:")


def test_event_consumer_skips_when_policy_was_disabled_after_event_creation() -> None:
    from libs.auto_review import consume_auto_review_evidence_events

    state = _state_with_node()
    state["auto_review_policies"][0]["enabled"] = False
    state["auto_review_outbox"].append(
        {
            "id": "AREVT-1",
            "tenantId": "TENANT-1",
            "projectId": "P-1",
            "nodeIds": [1],
            "status": "pending",
        }
    )

    result = consume_auto_review_evidence_events(
        state,
        now=datetime(2026, 8, 26, 1, 0, tzinfo=UTC),
    )

    assert result["skippedEventIds"] == ["AREVT-1"]
    assert state["auto_review_candidates"] == []


def test_celery_registers_auto_review_beat_and_business_light_routes() -> None:
    from apps.worker.celery_app import celery_app

    routes = dict(celery_app.conf.task_routes)
    beat = dict(celery_app.conf.beat_schedule)

    assert routes["apps.worker.tasks.auto_review_consume_evidence_events"]["queue"] == "business.light"
    assert routes["apps.worker.tasks.auto_review_scan_due_projects"]["queue"] == "business.light"
    assert beat["auto-review-consume-evidence-events"]["schedule"] == 60.0
    assert beat["auto-review-scan-due-projects"]["schedule"] == 60.0


def test_pending_candidates_start_one_parent_with_node_children() -> None:
    from libs.auto_review import dispatch_pending_auto_review_candidates

    state = _state_with_node()
    state["auto_review_candidates"] = [
        {
            "id": "ARC-1",
            "tenantId": "TENANT-1",
            "projectId": "P-1",
            "nodeId": 1,
            "policyRevision": 2,
            "status": "pending",
        }
    ]
    calls: list[tuple[str, int, dict]] = []

    def start_node(project_id: str, node_id: int, metadata: dict) -> dict:
        calls.append((project_id, node_id, metadata))
        return {"aiRunId": "AIRUN-1", "reviewRunId": "RRUN-1", "status": "queued"}

    result = dispatch_pending_auto_review_candidates(
        state,
        start_node_review=start_node,
    )

    assert len(result["projectReviewRunIds"]) == 1
    assert calls[0][0:2] == ("P-1", 1)
    assert calls[0][2]["triggerType"] == "ocr_mounted"
    assert state["auto_review_candidates"][0]["status"] == "dispatched"
    assert state["auto_review_candidates"][0]["projectReviewRunId"] == result["projectReviewRunIds"][0]


def test_celery_registers_pending_candidate_starter() -> None:
    from apps.worker.celery_app import celery_app

    routes = dict(celery_app.conf.task_routes)
    beat = dict(celery_app.conf.beat_schedule)

    assert routes["apps.worker.tasks.auto_review_start_pending_candidates"]["queue"] == "business.light"
    assert beat["auto-review-start-pending-candidates"]["schedule"] == 60.0
