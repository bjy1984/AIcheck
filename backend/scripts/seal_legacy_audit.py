from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.legacy_audit_manifest import canonical_bytes, verify_locked_reference, verify_manifest
from scripts.prepare_legacy_production import TENANT_PATTERN
from scripts.production_audit_ops import append_operational_audit


def validate_database(connection, manifest: dict, tenant_id: str) -> dict:
    migration = connection.execute(
        "SELECT checksum FROM schema_migrations WHERE version = '0001_backend_audit_hardening'"
    ).fetchone()
    if not migration:
        raise RuntimeError("Migration 0001 must be applied before sealing the legacy audit import")
    legacy = connection.execute(
        "SELECT count(*) FROM audit_events WHERE tenant_id=%s AND sequence IS NULL",
        (tenant_id,),
    ).fetchone()[0]
    chained = connection.execute(
        "SELECT count(*) FROM audit_events WHERE tenant_id=%s AND sequence IS NOT NULL",
        (tenant_id,),
    ).fetchone()[0]
    if int(legacy) != int(manifest["legacyAuditRows"]):
        raise RuntimeError(f"Legacy audit count mismatch: manifest={manifest['legacyAuditRows']}, database={legacy}")
    return {"legacyUnsealedEvents": int(legacy), "chainedEvents": int(chained), "migrationChecksum": str(migration[0])}


def main() -> int:
    parser = argparse.ArgumentParser(description="Append the genesis seal for a WORM-locked legacy audit manifest.")
    parser.add_argument("--database-url", default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL"))
    parser.add_argument("--tenant-id", default=os.getenv("AICHECK_TENANT_ID") or "TENANT-DEFAULT")
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--manifest-reference", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirmation", default="")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or AICHECK_DATABASE_URL is required")
    if not TENANT_PATTERN.fullmatch(args.tenant_id):
        parser.error("--tenant-id is invalid")
    if not TENANT_PATTERN.fullmatch(args.incident_id):
        parser.error("--incident-id is invalid")

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    manifest_hash = verify_manifest(manifest)
    if manifest.get("incidentId") != args.incident_id or manifest.get("tenantId") != args.tenant_id:
        raise RuntimeError("Manifest incident/tenant does not match the requested seal")
    if "versionId=" not in args.manifest_reference or not args.manifest_reference.startswith("minio://"):
        raise RuntimeError("A versioned MinIO manifest reference is required")
    configured_days = int(os.getenv("AICHECK_AUDIT_ANCHOR_RETENTION_DAYS", "3650"))
    if configured_days != 3650:
        raise RuntimeError("Legacy seal requires exactly 3650 days of audit-anchor retention")
    if os.getenv("AICHECK_AUDIT_ANCHOR_OBJECT_LOCK", "false").lower() != "true":
        raise RuntimeError("Legacy seal requires AICHECK_AUDIT_ANCHOR_OBJECT_LOCK=true")
    from libs.integrations.storage import ObjectStorage

    storage = ObjectStorage()
    worm = verify_locked_reference(
        storage,
        args.manifest_reference,
        configured_days,
        verify_delete_denied=False,
        expected_body=canonical_bytes(manifest),
        expected_bucket=storage.bucket_name("audit-anchors"),
    )

    import psycopg

    with psycopg.connect(args.database_url, autocommit=False) as connection:
        status = validate_database(connection, manifest, args.tenant_id)
        result: dict = {
            "mode": "plan",
            "tenantId": args.tenant_id,
            "incidentId": args.incident_id,
            "manifestHash": manifest_hash,
            "worm": worm,
            "database": status,
        }
        if args.apply:
            if args.confirmation != args.incident_id:
                parser.error("--apply requires --confirmation to exactly equal --incident-id")
            if status["chainedEvents"]:
                existing = connection.execute(
                    """
                    SELECT payload FROM audit_events
                    WHERE tenant_id=%s AND sequence=1
                    """,
                    (args.tenant_id,),
                ).fetchone()
                if not existing or existing[0].get("reasonCode") != "LEGACY_IMPORT_SEAL":
                    raise RuntimeError("Tenant audit chain already exists without the expected legacy import seal")
            event = append_operational_audit(
                connection,
                tenant_id=args.tenant_id,
                action="封存旧审计导入边界",
                object_type="legacy_audit_manifest",
                object_id=args.incident_id,
                reason_code="LEGACY_IMPORT_SEAL",
                incident_id=args.incident_id,
                event_id=f"AUD-LEGACY-SEAL-{manifest_hash.removeprefix('sha256:')[:12].upper()}",
                metadata={
                    "manifestHash": manifest_hash,
                    "manifestReference": args.manifest_reference,
                    "legacyAuditRows": manifest["legacyAuditRows"],
                    "legacyIntegrityStatus": "legacy_unverified",
                },
            )
            connection.commit()
            from libs.audit_anchor import write_pending_audit_anchors

            anchors = write_pending_audit_anchors(args.database_url)
            if not anchors:
                with psycopg.connect(args.database_url, autocommit=True) as anchor_connection:
                    existing_anchor = anchor_connection.execute(
                        """
                        SELECT sink_reference FROM audit_chain_anchors
                        WHERE tenant_id=%s AND head_sequence=%s AND head_hash=%s
                        """,
                        (args.tenant_id, event["sequence"], event["eventHash"]),
                    ).fetchone()
                if not existing_anchor:
                    raise RuntimeError("Legacy import seal committed but no immutable audit anchor was written")
                anchors = [{"sinkReference": str(existing_anchor[0]), "existing": True}]
            result.update({"mode": "applied", "event": event, "anchors": anchors})
        else:
            connection.rollback()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
