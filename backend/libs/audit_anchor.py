from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from typing import Any

from libs.integrations.storage import object_storage


def anchor_required() -> bool:
    return os.getenv("AICHECK_REQUIRE_AUDIT_ANCHOR", "false").strip().lower() == "true"


def write_pending_audit_anchors(database_url: str) -> list[dict[str, Any]]:
    """Write each tenant's latest audit head to a content-addressed external sink."""

    import psycopg

    with psycopg.connect(database_url, autocommit=False) as connection:
        heads = connection.execute(
            """
            SELECT DISTINCT ON (tenant_id) tenant_id, sequence, event_hash
            FROM audit_events
            WHERE sequence IS NOT NULL AND event_hash IS NOT NULL
            ORDER BY tenant_id, sequence DESC
            """
        ).fetchall()
        written: list[dict[str, Any]] = []
        for tenant_id, sequence, event_hash in heads:
            exists = connection.execute(
                """
                SELECT sink_reference
                FROM audit_chain_anchors
                WHERE tenant_id = %s AND head_sequence = %s AND sink_type = 'minio-object-lock'
                """,
                (str(tenant_id), int(sequence)),
            ).fetchone()
            if exists:
                continue
            anchored_at = datetime.now(UTC).isoformat()
            envelope = {
                "schemaVersion": "aicheck-audit-anchor-v1",
                "tenantId": str(tenant_id),
                "headSequence": int(sequence),
                "headHash": str(event_hash),
                "anchoredAt": anchored_at,
            }
            canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
            envelope["envelopeHash"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
            body = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            object_name = (
                f"{tenant_id}/{int(sequence):020d}-{str(event_hash).removeprefix('sha256:')}.json"
            )
            sink_reference = object_storage.put_bytes(
                "audit-anchors",
                object_name,
                body,
                content_type="application/json",
            )
            if not sink_reference:
                if anchor_required():
                    raise RuntimeError("Audit anchor object-lock sink is required but unavailable.")
                continue
            connection.execute(
                """
                INSERT INTO audit_chain_anchors (
                    tenant_id, head_sequence, head_hash, sink_type, sink_reference, anchored_at
                ) VALUES (%s, %s, %s, 'minio-object-lock', %s, %s::timestamptz)
                ON CONFLICT (tenant_id, head_sequence, sink_type) DO NOTHING
                """,
                (str(tenant_id), int(sequence), str(event_hash), sink_reference, anchored_at),
            )
            written.append({**envelope, "sinkReference": sink_reference})
        connection.commit()
        return written
