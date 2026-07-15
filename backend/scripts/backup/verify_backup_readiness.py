#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "aicheck-backup-recoverability-v1"


def parse_time(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def age_hours(value: Any, *, now: datetime) -> float | None:
    parsed = parse_time(value)
    return None if parsed is None else max(0.0, (now - parsed).total_seconds() / 3600)


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def command_json(command: list[str]) -> Any:
    return json.loads(subprocess.check_output(command, text=True, stderr=subprocess.STDOUT))


def pgbackrest_summary(document: Any, *, now: datetime) -> dict[str, Any]:
    stanza = document[0] if isinstance(document, list) and document else {}
    backups = stanza.get("backup") if isinstance(stanza, dict) else []
    backups = backups if isinstance(backups, list) else []
    completed = [item for item in backups if isinstance(item, dict) and item.get("timestamp", {}).get("stop")]
    latest = max(completed, key=lambda item: item["timestamp"]["stop"], default=None)
    full = [item for item in completed if item.get("type") == "full"]
    latest_full = max(full, key=lambda item: item["timestamp"]["stop"], default=None)
    return {
        "stanzaStatus": (stanza.get("status") or {}).get("code") if isinstance(stanza, dict) else None,
        "backupCount": len(completed),
        "latestBackupAgeHours": age_hours((latest or {}).get("timestamp", {}).get("stop"), now=now),
        "latestFullAgeHours": age_hours((latest_full or {}).get("timestamp", {}).get("stop"), now=now),
        "latestBackupLabel": (latest or {}).get("label"),
        "latestFullLabel": (latest_full or {}).get("label"),
    }


def check(name: str, passed: bool, detail: str, data: Any = None) -> dict[str, Any]:
    return {"name": name, "status": "pass" if passed else "fail", "detail": detail, "data": data}


def build_report(
    pgbackrest_info: Any,
    logical_receipt: dict[str, Any],
    replication_receipt: dict[str, Any],
    restore_receipt: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    physical = pgbackrest_summary(pgbackrest_info, now=current)
    logical_age = age_hours(logical_receipt.get("completedAt"), now=current)
    replication_age = age_hours(replication_receipt.get("completedAt"), now=current)
    restore_age = age_hours(restore_receipt.get("completedAt"), now=current)
    databases = set(logical_receipt.get("databases") or [])
    required_databases = {"aicheck", "litellm", "workflow"}
    checks = [
        check("pgbackrest.stanza", physical["stanzaStatus"] == 0, "pgBackRest stanza must report status code 0.", physical),
        check("pgbackrest.latest", physical["latestBackupAgeHours"] is not None and physical["latestBackupAgeHours"] <= 26, "Latest physical backup must be no older than 26 hours.", physical),
        check("pgbackrest.full", physical["latestFullAgeHours"] is not None and physical["latestFullAgeHours"] <= 8 * 24, "Latest full backup must be no older than eight days.", physical),
        check("logical.latest", logical_receipt.get("status") == "uploaded_and_size_verified" and logical_age is not None and logical_age <= 26, "All-database logical backup must be uploaded and verified within 26 hours.", {"ageHours": logical_age}),
        check("logical.database-inventory", required_databases.issubset(databases), "Logical backup must include aicheck, litellm, and workflow databases.", {"databases": sorted(databases)}),
        check("minio.replication", replication_receipt.get("status") == "verified" and replication_age is not None and replication_age <= 26, "MinIO replication inventory must be verified within 26 hours.", {"ageHours": replication_age, "buckets": replication_receipt.get("buckets")}),
        check("restore.drill", restore_receipt.get("status") == "verified" and restore_age is not None and restore_age <= 31 * 24, "An isolated restore drill must pass at least every 31 days.", {"ageHours": restore_age, "rpoSeconds": restore_receipt.get("rpoSeconds"), "rtoSeconds": restore_receipt.get("rtoSeconds")}),
        check("restore.rpo", isinstance(restore_receipt.get("rpoSeconds"), (int, float)) and restore_receipt["rpoSeconds"] <= 15 * 60, "Measured restore point loss must be at most 15 minutes.", restore_receipt.get("rpoSeconds")),
        check("restore.rto", isinstance(restore_receipt.get("rtoSeconds"), (int, float)) and restore_receipt["rtoSeconds"] <= 4 * 60 * 60, "Measured recovery time must be at most four hours.", restore_receipt.get("rtoSeconds")),
    ]
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": current.isoformat(),
        "ok": all(item["status"] == "pass" for item in checks),
        "checks": checks,
    }
    unsigned = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    report["reportHash"] = "sha256:" + hashlib.sha256(unsigned).hexdigest()
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify AIcheck backup freshness and tested recoverability.")
    parser.add_argument("--pgbackrest-info", help="Existing pgBackRest --output=json evidence; command is run when omitted.")
    parser.add_argument("--logical-receipt", required=True)
    parser.add_argument("--replication-receipt", required=True)
    parser.add_argument("--restore-receipt", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pgbackrest_info = load_json(args.pgbackrest_info) if args.pgbackrest_info else command_json(["pgbackrest", "--stanza=aicheck", "--output=json", "info"])
    report = build_report(
        pgbackrest_info,
        load_json(args.logical_receipt),
        load_json(args.replication_receipt),
        load_json(args.restore_receipt),
    )
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "output": str(target), "reportHash": report["reportHash"]}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
