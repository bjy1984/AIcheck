#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.backup.verify_backup_readiness import age_hours, check, load_json, pgbackrest_summary
except ModuleNotFoundError:
    from verify_backup_readiness import age_hours, check, load_json, pgbackrest_summary


SCHEMA_VERSION = "aicheck-local-backup-readiness-v1"


def build_local_report(
    pgbackrest_info: Any,
    restore_receipt: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    physical = pgbackrest_summary(pgbackrest_info, now=current)
    restore_age = age_hours(restore_receipt.get("completedAt"), now=current)
    checks = [
        check("pgbackrest.stanza", physical["stanzaStatus"] == 0, "Local pgBackRest stanza must report status code 0.", physical),
        check("pgbackrest.latest", physical["latestBackupAgeHours"] is not None and physical["latestBackupAgeHours"] <= 26, "Latest local physical backup must be no older than 26 hours.", physical),
        check("pgbackrest.full", physical["latestFullAgeHours"] is not None and physical["latestFullAgeHours"] <= 8 * 24, "Latest local full backup must be no older than eight days.", physical),
        check("restore.drill", restore_receipt.get("status") == "verified" and restore_age is not None and restore_age <= 31 * 24, "An isolated local restore drill must pass at least every 31 days.", {"ageHours": restore_age}),
        check("restore.rpo", isinstance(restore_receipt.get("rpoSeconds"), (int, float)) and restore_receipt["rpoSeconds"] <= 15 * 60, "Measured local restore point loss must be at most 15 minutes.", restore_receipt.get("rpoSeconds")),
        check("restore.rto", isinstance(restore_receipt.get("rtoSeconds"), (int, float)) and restore_receipt["rtoSeconds"] <= 4 * 60 * 60, "Measured local recovery time must be at most four hours.", restore_receipt.get("rtoSeconds")),
    ]
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": current.isoformat(),
        "mode": "local_only",
        "ok": all(item["status"] == "pass" for item in checks),
        "formalRecoverability": False,
        "offsiteVerified": False,
        "checks": checks,
        "limitations": [
            "Repository is on the production host and does not survive host loss.",
            "No offsite replication, KMS-backed copy, or offsite restore is verified.",
        ],
    }
    unsigned = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    report["reportHash"] = "sha256:" + hashlib.sha256(unsigned).hexdigest()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local-only AIcheck physical backup and restore evidence.")
    parser.add_argument("--pgbackrest-info", required=True)
    parser.add_argument("--restore-receipt", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = build_local_report(load_json(args.pgbackrest_info), load_json(args.restore_receipt))
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "mode": report["mode"], "output": str(target), "reportHash": report["reportHash"]}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
