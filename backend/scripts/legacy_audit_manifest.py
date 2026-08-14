from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from scripts.prepare_legacy_production import TENANT_PATTERN, legacy_report


def canonical_bytes(document: dict) -> bytes:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()


def build_manifest(preflight: dict, *, incident_id: str, backup_reference: str) -> dict:
    document = {
        "schemaVersion": "aicheck-legacy-audit-manifest-v1",
        "incidentId": incident_id,
        "tenantId": preflight["tenantId"],
        "database": preflight["database"],
        "generatedAt": datetime.now(UTC).isoformat(),
        "backupReference": backup_reference,
        "legacyAuditRows": preflight["legacyAuditRows"],
        "legacyAuditDigest": preflight["legacyAuditDigest"],
        "legacyAuditWindow": preflight["legacyAuditWindow"],
        "stateRows": preflight["stateRows"],
        "stateDigestWithoutTenant": preflight["stateDigestWithoutTenant"],
        "integrityStatus": "legacy_unverified",
    }
    document["manifestHash"] = "sha256:" + hashlib.sha256(canonical_bytes(document)).hexdigest()
    return document


def verify_manifest(document: dict) -> str:
    expected = str(document.get("manifestHash") or "")
    unsigned = {key: value for key, value in document.items() if key != "manifestHash"}
    actual = "sha256:" + hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
    if expected != actual:
        raise RuntimeError(f"Legacy audit manifest hash mismatch: expected={expected}, actual={actual}")
    return actual


def verify_locked_reference(
    storage,
    reference: str,
    retention_days: int,
    *,
    verify_delete_denied: bool,
    expected_body: bytes | None = None,
    expected_bucket: str | None = None,
) -> dict:
    parsed = urlparse(reference)
    query = parse_qs(parsed.query)
    version_id = (query.get("versionId") or [None])[0]
    if parsed.scheme != "minio" or not parsed.netloc or not parsed.path or not version_id:
        raise RuntimeError("WORM manifest reference must be a versioned minio:// URL")
    client = storage.client()
    if client is None:
        raise RuntimeError("MinIO client is unavailable")
    bucket = parsed.netloc
    object_name = unquote(parsed.path.lstrip("/"))
    if expected_bucket and bucket != expected_bucket:
        raise RuntimeError(
            f"WORM manifest bucket mismatch: expected={expected_bucket}, actual={bucket}"
        )
    object_sha256 = None
    if expected_body is not None:
        response = client.get_object(bucket, object_name, version_id=version_id)
        try:
            body = response.read()
        finally:
            response.close()
            response.release_conn()
        expected_sha256 = hashlib.sha256(expected_body).hexdigest()
        object_sha256 = hashlib.sha256(body).hexdigest()
        if body != expected_body:
            raise RuntimeError(
                "WORM manifest object content mismatch: "
                f"expected=sha256:{expected_sha256}, actual=sha256:{object_sha256}"
            )
    stat = client.stat_object(bucket, object_name, version_id=version_id)
    retention = client.get_object_retention(bucket, object_name, version_id=version_id)
    if retention is None or str(retention.mode).upper() != "COMPLIANCE":
        raise RuntimeError("Legacy manifest object is not protected by COMPLIANCE retention")
    retention_started_at = getattr(stat, "last_modified", None)
    if retention_started_at is None:
        raise RuntimeError("Legacy manifest object creation time is unavailable")
    retain_until = retention.retain_until_date
    minimum = retention_started_at + timedelta(days=retention_days) - timedelta(minutes=5)
    if retain_until is None or retain_until < minimum:
        raise RuntimeError(f"Legacy manifest retention is shorter than {retention_days} days")
    delete_denied = None
    if verify_delete_denied:
        from minio.error import S3Error

        try:
            client.remove_object(bucket, object_name, version_id=version_id)
        except S3Error as exc:
            delete_denied = exc.code
        if not delete_denied:
            raise RuntimeError("Versioned legacy manifest deletion unexpectedly succeeded")
    return {
        "bucket": bucket,
        "objectName": object_name,
        "versionId": version_id,
        "retentionMode": str(retention.mode),
        "retentionStartedAt": retention_started_at.isoformat(),
        "retainUntil": retain_until.isoformat(),
        "retentionDurationSeconds": (retain_until - retention_started_at).total_seconds(),
        "deleteDeniedCode": delete_denied,
        "objectSha256": f"sha256:{object_sha256}" if object_sha256 else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and optionally WORM-lock a legacy audit manifest.")
    parser.add_argument("--database-url", default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL"))
    parser.add_argument("--tenant-id", default=os.getenv("AICHECK_TENANT_ID") or "TENANT-DEFAULT")
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--backup-reference", required=True)
    parser.add_argument("--output")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--confirm-retention-days", type=int)
    parser.add_argument("--verify-delete-denied", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or AICHECK_DATABASE_URL is required")
    if not TENANT_PATTERN.fullmatch(args.tenant_id):
        parser.error("--tenant-id is invalid")
    if not TENANT_PATTERN.fullmatch(args.incident_id):
        parser.error("--incident-id is invalid")

    import psycopg

    with psycopg.connect(args.database_url, autocommit=True) as connection:
        manifest = build_manifest(
            legacy_report(connection, args.tenant_id),
            incident_id=args.incident_id,
            backup_reference=args.backup_reference,
        )
    verify_manifest(manifest)
    result: dict = {"mode": "plan", "manifest": manifest}
    if args.upload:
        configured_days = int(os.getenv("AICHECK_AUDIT_ANCHOR_RETENTION_DAYS", "3650"))
        if args.confirm_retention_days != configured_days or configured_days != 3650:
            parser.error("--upload requires --confirm-retention-days=3650 and matching environment")
        if os.getenv("AICHECK_AUDIT_ANCHOR_OBJECT_LOCK", "false").lower() != "true":
            parser.error("AICHECK_AUDIT_ANCHOR_OBJECT_LOCK=true is required")
        from libs.integrations.storage import ObjectStorage

        storage = ObjectStorage()
        object_name = (
            f"legacy/{args.tenant_id}/{args.incident_id}/"
            f"{manifest['manifestHash'].removeprefix('sha256:')}.json"
        )
        reference = storage.put_bytes(
            "audit-anchors",
            object_name,
            canonical_bytes(manifest),
            content_type="application/json",
        )
        if not reference:
            raise RuntimeError("Legacy audit manifest upload failed")
        result.update(
            {
                "mode": "uploaded",
                "manifestReference": reference,
                "worm": verify_locked_reference(
                    storage,
                    reference,
                    configured_days,
                    verify_delete_denied=args.verify_delete_denied,
                    expected_body=canonical_bytes(manifest),
                    expected_bucket=storage.bucket_name("audit-anchors"),
                ),
            }
        )
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
