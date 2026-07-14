from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def canonical_event_hash(previous_hash: str, event: dict[str, Any]) -> str:
    canonical_event = {
        key: value
        for key, value in event.items()
        if key not in {"eventHash", "integrityStatus"}
    }
    canonical = json.dumps(
        canonical_event,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(f"{previous_hash}:{canonical}".encode()).hexdigest()


def append_operational_audit(
    connection: Any,
    *,
    tenant_id: str,
    action: str,
    object_type: str,
    object_id: str,
    reason_code: str,
    incident_id: str,
    metadata: dict[str, Any] | None = None,
    event_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Append one tenant-scoped remediation event using the production hash contract."""

    from psycopg.types.json import Jsonb

    tenant_id = str(tenant_id or "").strip()
    incident_id = str(incident_id or "").strip()
    if not tenant_id or not incident_id:
        raise ValueError("tenant_id and incident_id are required")
    event_id = str(event_id or f"AUD-OPS-{uuid4().hex[:12].upper()}")
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        (f"aicheck:audit:{tenant_id}",),
    )
    existing = connection.execute(
        "SELECT payload FROM aicheck_state WHERE tenant_id = %s AND collection = 'audit_logs' AND object_id = %s",
        (tenant_id, event_id),
    ).fetchone()
    if existing:
        payload = dict(existing[0])
        if payload.get("incidentId") != incident_id or payload.get("reasonCode") != reason_code:
            raise RuntimeError(f"Operational audit id collision: {event_id}")
        return payload
    head = connection.execute(
        """
        SELECT sequence, event_hash
        FROM audit_events
        WHERE tenant_id = %s AND sequence IS NOT NULL
        ORDER BY sequence DESC
        LIMIT 1
        """,
        (tenant_id,),
    ).fetchone()
    sequence = int(head[0]) + 1 if head else 1
    previous_hash = str(head[1]) if head and head[1] else "GENESIS"
    event: dict[str, Any] = {
        "id": event_id,
        "tenantId": tenant_id,
        "actorId": "SYSTEM-PRODUCTION-REMEDIATION",
        "actorName": "Production Remediation",
        "actorRole": "system",
        "action": action,
        "objectType": object_type,
        "objectId": object_id,
        "result": "成功",
        "outcome": "success",
        "reasonCode": reason_code,
        "incidentId": incident_id,
        "sequence": sequence,
        "previousHash": previous_hash,
        "createdAt": created_at or datetime.now(timezone.utc).isoformat(),
    }
    if metadata:
        event["metadata"] = metadata
    event["eventHash"] = canonical_event_hash(previous_hash, event)
    event["integrityStatus"] = "verified"
    connection.execute(
        """
        INSERT INTO aicheck_state (
            tenant_id, collection, object_id, payload, revision, updated_at
        ) VALUES (%s, 'audit_logs', %s, %s, 1, %s::timestamptz)
        """,
        (tenant_id, event_id, Jsonb(event), event["createdAt"]),
    )
    return event
