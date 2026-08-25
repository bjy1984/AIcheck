from __future__ import annotations

import pytest


def test_default_policy_is_disabled_and_project_scoped() -> None:
    from libs.auto_review import default_auto_review_policy

    first = default_auto_review_policy("P-1", "TENANT-1")
    second = default_auto_review_policy("P-2", "TENANT-1")

    assert first["projectId"] == "P-1"
    assert first["tenantId"] == "TENANT-1"
    assert first["enabled"] is False
    assert first["reviewMode"] == "gap_precheck"
    assert first["id"] != second["id"]


def test_policy_supports_realtime_daily_and_combined_modes() -> None:
    from libs.auto_review import default_auto_review_policy, validate_auto_review_policy

    existing = default_auto_review_policy("P-1", "TENANT-1")
    for modes in (["ocr_mounted"], ["daily_schedule"], ["ocr_mounted", "daily_schedule"]):
        updated = validate_auto_review_policy(
            {"enabled": True, "triggerModes": modes},
            existing,
        )
        assert updated["triggerModes"] == sorted(modes)
        assert updated["reviewMode"] == "gap_precheck"


def test_enabled_policy_rejects_empty_or_unknown_trigger_modes() -> None:
    from libs.auto_review import default_auto_review_policy, validate_auto_review_policy

    existing = default_auto_review_policy("P-1", "TENANT-1")
    with pytest.raises(ValueError, match="trigger mode"):
        validate_auto_review_policy({"enabled": True, "triggerModes": []}, existing)
    with pytest.raises(ValueError, match="trigger mode"):
        validate_auto_review_policy(
            {"enabled": True, "triggerModes": ["weekly_schedule"]},
            existing,
        )


def test_policy_validates_daily_time_timezone_and_debounce() -> None:
    from libs.auto_review import default_auto_review_policy, validate_auto_review_policy

    existing = default_auto_review_policy("P-1", "TENANT-1")
    valid = validate_auto_review_policy(
        {
            "dailyTime": "23:45",
            "timezone": "Asia/Shanghai",
            "debounceSeconds": 600,
        },
        existing,
    )
    assert valid["dailyTime"] == "23:45"
    assert valid["timezone"] == "Asia/Shanghai"
    assert valid["debounceSeconds"] == 600
    with pytest.raises(ValueError, match="dailyTime"):
        validate_auto_review_policy({"dailyTime": "25:90"}, existing)
    with pytest.raises(ValueError, match="timezone"):
        validate_auto_review_policy({"timezone": "Mars/Olympus"}, existing)
    with pytest.raises(ValueError, match="debounceSeconds"):
        validate_auto_review_policy({"debounceSeconds": 7200}, existing)


def test_policy_update_cannot_change_scope_and_increments_revision() -> None:
    from libs.auto_review import default_auto_review_policy, validate_auto_review_policy

    existing = default_auto_review_policy("P-1", "TENANT-1")
    existing["revision"] = 7
    updated = validate_auto_review_policy(
        {"projectId": "P-OTHER", "tenantId": "TENANT-OTHER", "enabled": True},
        existing,
    )
    assert updated["projectId"] == "P-1"
    assert updated["tenantId"] == "TENANT-1"
    assert updated["revision"] == 8


def test_policy_allows_only_enabled_configured_trigger() -> None:
    from libs.auto_review import default_auto_review_policy, policy_allows_trigger

    policy = default_auto_review_policy("P-1", "TENANT-1")
    policy["triggerModes"] = ["ocr_mounted"]
    assert policy_allows_trigger(policy, "ocr_mounted") is False
    policy["enabled"] = True
    assert policy_allows_trigger(policy, "ocr_mounted") is True
    assert policy_allows_trigger(policy, "daily_schedule") is False


def test_candidate_key_and_upsert_are_snapshot_and_policy_idempotent() -> None:
    from libs.auto_review import auto_review_candidate_key, upsert_auto_review_candidate

    state: dict = {"auto_review_candidates": []}
    first, created = upsert_auto_review_candidate(
        state,
        tenant_id="TENANT-1",
        project_id="P-1",
        node_id=12,
        evidence_snapshot_hash="sha256:snapshot-a",
        policy_revision=3,
        trigger_type="ocr_mounted",
    )
    duplicate, duplicate_created = upsert_auto_review_candidate(
        state,
        tenant_id="TENANT-1",
        project_id="P-1",
        node_id=12,
        evidence_snapshot_hash="sha256:snapshot-a",
        policy_revision=3,
        trigger_type="daily_schedule",
    )
    changed, changed_created = upsert_auto_review_candidate(
        state,
        tenant_id="TENANT-1",
        project_id="P-1",
        node_id=12,
        evidence_snapshot_hash="sha256:snapshot-b",
        policy_revision=3,
        trigger_type="ocr_mounted",
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate["id"] == first["id"]
    assert changed_created is True
    assert changed["id"] != first["id"]
    assert len(state["auto_review_candidates"]) == 2
    assert first["candidateKey"] == auto_review_candidate_key(
        "TENANT-1", "P-1", 12, "sha256:snapshot-a", 3
    )
