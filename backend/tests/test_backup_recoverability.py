from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.backup.verify_backup_readiness import build_report
from scripts.backup.verify_local_backup import build_local_report


def valid_evidence(now: datetime):
    timestamp = int((now - timedelta(hours=2)).timestamp())
    full_timestamp = int((now - timedelta(days=2)).timestamp())
    pgbackrest = [
        {
            "status": {"code": 0},
            "backup": [
                {"label": "full", "type": "full", "timestamp": {"stop": full_timestamp}},
                {"label": "diff", "type": "diff", "timestamp": {"stop": timestamp}},
            ],
        }
    ]
    logical = {
        "status": "uploaded_and_size_verified",
        "completedAt": (now - timedelta(hours=2)).isoformat(),
        "databases": ["aicheck", "litellm", "workflow", "postgres"],
    }
    replication = {
        "status": "verified",
        "completedAt": (now - timedelta(hours=1)).isoformat(),
        "buckets": ["documents", "previews", "exports", "ocr-artifacts", "audit-anchors-v2"],
    }
    restore = {
        "status": "verified",
        "completedAt": (now - timedelta(days=7)).isoformat(),
        "rpoSeconds": 300,
        "rtoSeconds": 1800,
    }
    return pgbackrest, logical, replication, restore


def test_backup_recoverability_passes_only_with_fresh_complete_evidence() -> None:
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    report = build_report(*valid_evidence(now), now=now)

    assert report["ok"] is True
    assert report["schemaVersion"] == "aicheck-backup-recoverability-v1"
    assert report["reportHash"].startswith("sha256:")
    assert all(item["status"] == "pass" for item in report["checks"])


def test_backup_recoverability_fails_stale_restore_and_missing_database() -> None:
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    pgbackrest, logical, replication, restore = valid_evidence(now)
    logical["databases"].remove("workflow")
    restore["completedAt"] = (now - timedelta(days=32)).isoformat()

    report = build_report(pgbackrest, logical, replication, restore, now=now)

    assert report["ok"] is False
    failed = {item["name"] for item in report["checks"] if item["status"] == "fail"}
    assert failed == {"logical.database-inventory", "restore.drill"}


def test_local_backup_report_passes_but_never_claims_formal_recoverability() -> None:
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    pgbackrest, _logical, _replication, restore = valid_evidence(now)

    report = build_local_report(pgbackrest, restore, now=now)

    assert report["ok"] is True
    assert report["mode"] == "local_only"
    assert report["formalRecoverability"] is False
    assert report["offsiteVerified"] is False
    assert all(item["status"] == "pass" for item in report["checks"])


def test_local_backup_report_fails_without_recent_restore() -> None:
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    pgbackrest, _logical, _replication, restore = valid_evidence(now)
    restore["completedAt"] = (now - timedelta(days=40)).isoformat()

    report = build_local_report(pgbackrest, restore, now=now)

    assert report["ok"] is False
    assert report["formalRecoverability"] is False
    assert {item["name"] for item in report["checks"] if item["status"] == "fail"} == {"restore.drill"}
