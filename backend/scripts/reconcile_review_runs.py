from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.production_audit_ops import append_operational_audit

TEMPORAL_ACTIONS = {"preserve_waiting", "terminate_orphan", "terminate_keep_failed"}
DATABASE_ACTIONS = {"mark_failed_to_start"}
SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def load_plan(path: str) -> dict[str, Any]:
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan.get("schemaVersion") != "aicheck-review-reconciliation-v1":
        raise RuntimeError("Unsupported reconciliation plan schemaVersion")
    if not str(plan.get("incidentId") or "").strip() or not str(plan.get("tenantId") or "").strip():
        raise RuntimeError("Reconciliation plan requires incidentId and tenantId")
    for field in ("incidentId", "tenantId"):
        if not SAFE_IDENTIFIER.fullmatch(str(plan[field])):
            raise RuntimeError(f"Reconciliation plan {field} is not a safe identifier")
    for section in ("temporal", "databaseOnly"):
        if not isinstance(plan.get(section, []), list):
            raise RuntimeError(f"Reconciliation plan {section} must be a list")
    seen: set[str] = set()
    for item in plan.get("temporal") or []:
        if not isinstance(item, dict):
            raise RuntimeError("Temporal reconciliation entries must be objects")
        required = {"reviewRunId", "workflowId", "runId", "action", "expectedDbStatus"}
        if not required.issubset(item):
            raise RuntimeError(f"Temporal reconciliation entry is incomplete: {item}")
        if not SAFE_IDENTIFIER.fullmatch(str(item["reviewRunId"])):
            raise RuntimeError("Temporal reconciliation reviewRunId is not a safe identifier")
        for field in ("workflowId", "runId", "expectedDbStatus"):
            if not str(item[field]).strip() or len(str(item[field])) > 512:
                raise RuntimeError(f"Temporal reconciliation {field} is invalid")
        if item["action"] not in TEMPORAL_ACTIONS:
            raise RuntimeError(f"Unsupported Temporal action: {item['action']}")
        if item["reviewRunId"] in seen:
            raise RuntimeError(f"Duplicate ReviewRun in reconciliation plan: {item['reviewRunId']}")
        seen.add(item["reviewRunId"])
    for item in plan.get("databaseOnly") or []:
        if not isinstance(item, dict):
            raise RuntimeError("Database-only reconciliation entries must be objects")
        required = {"reviewRunId", "workflowId", "action", "expectedDbStatus", "reasonCode"}
        if not required.issubset(item):
            raise RuntimeError(f"Database-only reconciliation entry is incomplete: {item}")
        if item["action"] not in DATABASE_ACTIONS:
            raise RuntimeError(f"Unsupported database action: {item['action']}")
        if not SAFE_IDENTIFIER.fullmatch(str(item["reviewRunId"])):
            raise RuntimeError("Database-only reconciliation reviewRunId is not a safe identifier")
        for field in ("workflowId", "expectedDbStatus", "reasonCode"):
            if not str(item[field]).strip() or len(str(item[field])) > 512:
                raise RuntimeError(f"Database-only reconciliation {field} is invalid")
        if item["reviewRunId"] in seen:
            raise RuntimeError(f"Duplicate ReviewRun in reconciliation plan: {item['reviewRunId']}")
        seen.add(item["reviewRunId"])
    return plan


def deterministic_audit_event_id(
    incident_id: str,
    review_run_id: str,
    phase: str,
) -> str:
    digest = hashlib.sha256(
        f"{incident_id}\0{review_run_id}\0{phase}".encode()
    ).hexdigest()[:20].upper()
    return f"AUD-OPS-{digest}"


def database_snapshot(connection: Any, tenant_id: str, review_run_id: str) -> dict[str, Any]:
    tenant_column = connection.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='aicheck_state' AND column_name='tenant_id'
        )
        """
    ).fetchone()[0]
    tenant_filter = "AND tenant_id = %s" if tenant_column else ""
    params: tuple[Any, ...] = (review_run_id, review_run_id, tenant_id) if tenant_column else (review_run_id, review_run_id)
    rows = connection.execute(
        f"""
        SELECT collection, object_id, payload, updated_at
        FROM aicheck_state
        WHERE (object_id = %s OR payload ->> 'reviewRunId' = %s)
        {tenant_filter}
        ORDER BY collection, object_id
        """,
        params,
    ).fetchall()
    records = [
        {
            "collection": str(collection),
            "objectId": str(object_id),
            "payload": payload,
            "updatedAt": updated_at.isoformat(),
        }
        for collection, object_id, payload, updated_at in rows
    ]
    review = next(
        (
            item
            for item in records
            if item["collection"] == "review_runs" and item["objectId"] == review_run_id
        ),
        None,
    )
    return {
        "reviewRunId": review_run_id,
        "dbStatus": review["payload"].get("status") if review else None,
        "records": records,
        "recordsHash": canonical_hash(records),
    }


async def temporal_snapshot(client: Any, entry: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    handle = client.get_workflow_handle(entry["workflowId"], run_id=entry["runId"])
    description = await handle.describe()
    state = await handle.query("get_review_state")
    try:
        current_step = await handle.query("get_current_step")
    except Exception as exc:
        current_step = {"queryError": exc.__class__.__name__}
    history = await handle.fetch_history()
    history_json = history.to_json()
    snapshot = {
        "workflowId": entry["workflowId"],
        "runId": entry["runId"],
        "status": str(getattr(description, "status", "")),
        "state": state,
        "currentStep": current_step,
        "history": json.loads(history_json),
        "historyHash": "sha256:" + hashlib.sha256(history_json.encode()).hexdigest(),
    }
    return handle, snapshot


async def workflow_exists(client: Any, workflow_id: str) -> bool:
    from temporalio.service import RPCError, RPCStatusCode

    try:
        await client.get_workflow_handle(workflow_id).describe()
        return True
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            return False
        raise


def validate_temporal_entry(entry: dict[str, Any], db: dict[str, Any], temporal: dict[str, Any]) -> None:
    if db["dbStatus"] != entry["expectedDbStatus"]:
        raise RuntimeError(
            f"{entry['reviewRunId']} database status changed: expected={entry['expectedDbStatus']}, actual={db['dbStatus']}"
        )
    state = temporal.get("state") or {}
    if str(state.get("reviewRunId") or "") != entry["reviewRunId"]:
        raise RuntimeError(f"{entry['reviewRunId']} Temporal query returned a different aggregate")
    if entry["action"] == "preserve_waiting":
        if db["dbStatus"] != "waiting_human_review" or state.get("status") != "waiting_human_review":
            raise RuntimeError(f"{entry['reviewRunId']} is not consistently waiting for human review")
    elif entry["action"] == "terminate_orphan" and db["dbStatus"] is not None:
        raise RuntimeError(f"{entry['reviewRunId']} is no longer a database orphan")
    elif entry["action"] == "terminate_keep_failed" and db["dbStatus"] != "failed":
        raise RuntimeError(f"{entry['reviewRunId']} is no longer a failed database run")


def mark_failed_to_start(connection: Any, *, tenant_id: str, incident_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    from psycopg.types.json import Jsonb

    row = connection.execute(
        """
        SELECT payload, revision
        FROM aicheck_state
        WHERE tenant_id=%s AND collection='review_runs' AND object_id=%s
        FOR UPDATE
        """,
        (tenant_id, entry["reviewRunId"]),
    ).fetchone()
    if not row:
        raise RuntimeError(f"Database-only ReviewRun disappeared: {entry['reviewRunId']}")
    payload, revision = dict(row[0]), int(row[1])
    if payload.get("status") != entry["expectedDbStatus"]:
        raise RuntimeError(
            f"{entry['reviewRunId']} status changed: expected={entry['expectedDbStatus']}, actual={payload.get('status')}"
        )
    side_effects = connection.execute(
        """
        SELECT collection, count(*)
        FROM aicheck_state
        WHERE tenant_id=%s AND payload->>'reviewRunId'=%s
          AND collection NOT IN ('review_runs','review_events','review_graph_nodes')
        GROUP BY collection ORDER BY collection
        """,
        (tenant_id, entry["reviewRunId"]),
    ).fetchall()
    if side_effects:
        raise RuntimeError(f"{entry['reviewRunId']} has nontrivial side effects: {side_effects}")
    now = datetime.now(UTC).isoformat()
    payload.update(
        {
            "status": "failed_to_start",
            "errorCode": entry["reasonCode"],
            "reconciledIncidentId": incident_id,
            "updatedAt": now,
        }
    )
    updated = connection.execute(
        """
        UPDATE aicheck_state
        SET payload=%s, revision=revision+1, updated_at=%s::timestamptz
        WHERE tenant_id=%s AND collection='review_runs' AND object_id=%s
          AND revision=%s AND payload->>'status'=%s
        RETURNING revision
        """,
        (
            Jsonb(payload),
            now,
            tenant_id,
            entry["reviewRunId"],
            revision,
            entry["expectedDbStatus"],
        ),
    ).fetchone()
    if not updated:
        raise RuntimeError(f"Concurrent reconciliation conflict: {entry['reviewRunId']}")
    event = append_operational_audit(
        connection,
        tenant_id=tenant_id,
        action="标记未启动 ReviewRun 为失败",
        object_type="review_run",
        object_id=entry["reviewRunId"],
        reason_code=entry["reasonCode"],
        incident_id=incident_id,
        metadata={"previousStatus": entry["expectedDbStatus"], "nextStatus": "failed_to_start"},
    )
    return {"reviewRunId": entry["reviewRunId"], "revision": int(updated[0]), "auditEventId": event["id"]}


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    import psycopg
    from temporalio.client import Client

    plan = load_plan(args.plan_file)
    incident_id = plan["incidentId"]
    tenant_id = plan["tenantId"]
    if args.apply and args.confirmation != incident_id:
        raise RuntimeError("--apply requires --confirmation to exactly match the plan incidentId")
    evidence_root = Path(args.evidence_dir) / incident_id
    evidence_root.mkdir(parents=True, exist_ok=True)
    evidence_root.chmod(0o700)
    client = await Client.connect(args.temporal_address, namespace=args.namespace)
    result: dict[str, Any] = {"mode": "apply" if args.apply else "plan", "incidentId": incident_id, "items": []}
    with psycopg.connect(args.database_url, autocommit=False) as connection:
        for entry in plan.get("temporal") or []:
            db = database_snapshot(connection, tenant_id, entry["reviewRunId"])
            _, temporal = await temporal_snapshot(client, entry)
            validate_temporal_entry(entry, db, temporal)
            evidence = {"plan": entry, "database": db, "temporal": temporal}
            evidence["evidenceHash"] = canonical_hash(evidence)
            target = evidence_root / f"{entry['reviewRunId']}.json"
            target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
            target.chmod(0o600)
            result["items"].append(
                {"reviewRunId": entry["reviewRunId"], "action": entry["action"], "evidence": str(target), "evidenceHash": evidence["evidenceHash"]}
            )
        for entry in plan.get("databaseOnly") or []:
            db = database_snapshot(connection, tenant_id, entry["reviewRunId"])
            if db["dbStatus"] != entry["expectedDbStatus"]:
                raise RuntimeError(f"{entry['reviewRunId']} database status changed")
            exists = await workflow_exists(client, entry["workflowId"])
            if exists:
                raise RuntimeError(f"Database-only workflow now exists: {entry['workflowId']}")
            evidence = {"plan": entry, "database": db, "temporalWorkflowExists": False}
            evidence["evidenceHash"] = canonical_hash(evidence)
            target = evidence_root / f"{entry['reviewRunId']}.json"
            target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
            target.chmod(0o600)
            result["items"].append(
                {"reviewRunId": entry["reviewRunId"], "action": entry["action"], "evidence": str(target), "evidenceHash": evidence["evidenceHash"]}
            )
        connection.rollback()

        if args.apply:
            intent_events = []
            applied_db = []
            for entry in plan.get("temporal") or []:
                if entry["action"].startswith("terminate_"):
                    db = database_snapshot(connection, tenant_id, entry["reviewRunId"])
                    handle, temporal = await temporal_snapshot(client, entry)
                    validate_temporal_entry(entry, db, temporal)
                    with connection.transaction():
                        intent = append_operational_audit(
                            connection,
                            tenant_id=tenant_id,
                            action="记录 Temporal ReviewRun 终止意图",
                            object_type="review_run",
                            object_id=entry["reviewRunId"],
                            reason_code="TEMPORAL_TERMINATION_INTENT",
                            incident_id=incident_id,
                            event_id=deterministic_audit_event_id(
                                incident_id, entry["reviewRunId"], "termination-intent"
                            ),
                            metadata={
                                "workflowId": entry["workflowId"],
                                "runId": entry["runId"],
                                "intendedAction": entry["action"],
                                "evidenceHash": next(
                                    item["evidenceHash"]
                                    for item in result["items"]
                                    if item["reviewRunId"] == entry["reviewRunId"]
                                ),
                            },
                        )
                    intent_events.append(
                        {"reviewRunId": entry["reviewRunId"], "auditEventId": intent["id"]}
                    )
                    await handle.terminate(
                        reason=f"{incident_id}:{entry['action']}"
                    )
                    with connection.transaction():
                        event = append_operational_audit(
                            connection,
                            tenant_id=tenant_id,
                            action="终止不一致 Temporal ReviewRun",
                            object_type="review_run",
                            object_id=entry["reviewRunId"],
                            reason_code=(
                                "TEMPORAL_ORPHAN_NO_DB_RECORD"
                                if entry["action"] == "terminate_orphan"
                                else "TEMPORAL_TERMINATED_DB_ALREADY_FAILED"
                            ),
                            incident_id=incident_id,
                            event_id=deterministic_audit_event_id(
                                incident_id, entry["reviewRunId"], "termination-complete"
                            ),
                            metadata={
                                "workflowId": entry["workflowId"],
                                "runId": entry["runId"],
                                "evidenceHash": next(
                                    item["evidenceHash"]
                                    for item in result["items"]
                                    if item["reviewRunId"] == entry["reviewRunId"]
                                ),
                            },
                        )
                        applied_db.append(
                            {"reviewRunId": entry["reviewRunId"], "auditEventId": event["id"]}
                        )
            for entry in plan.get("databaseOnly") or []:
                if await workflow_exists(client, entry["workflowId"]):
                    raise RuntimeError(f"Database-only workflow now exists: {entry['workflowId']}")
                with connection.transaction():
                    applied_db.append(
                        mark_failed_to_start(
                            connection,
                            tenant_id=tenant_id,
                            incident_id=incident_id,
                            entry=entry,
                        )
                    )
            result["intentAuditEvents"] = intent_events
            result["databaseChanges"] = applied_db
            if intent_events or applied_db:
                from libs.audit_anchor import write_pending_audit_anchors

                anchors = write_pending_audit_anchors(args.database_url)
                head = connection.execute(
                    """
                    SELECT sequence, event_hash FROM audit_events
                    WHERE tenant_id=%s AND sequence IS NOT NULL
                    ORDER BY sequence DESC LIMIT 1
                    """,
                    (tenant_id,),
                ).fetchone()
                anchored = (
                    connection.execute(
                        """
                        SELECT sink_reference FROM audit_chain_anchors
                        WHERE tenant_id=%s AND head_sequence=%s AND head_hash=%s
                        """,
                        (tenant_id, head[0], head[1]),
                    ).fetchone()
                    if head
                    else None
                )
                if head and not anchored:
                    raise RuntimeError("Reconciliation audit head was not written to an immutable anchor")
                result["anchors"] = anchors or [
                    {"sinkReference": str(anchored[0]), "existing": True}
                ]
    receipt = evidence_root / "receipt.json"
    result["receiptHash"] = canonical_hash(result)
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    receipt.chmod(0o600)
    result["receipt"] = str(receipt)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Evidence-first production ReviewRun/Temporal reconciliation.")
    parser.add_argument("--database-url", default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL"))
    parser.add_argument("--temporal-address", default=os.getenv("TEMPORAL_ADDRESS") or "127.0.0.1:7233")
    parser.add_argument("--namespace", default=os.getenv("TEMPORAL_NAMESPACE") or "default")
    parser.add_argument("--plan-file", required=True)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirmation", default="")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or AICHECK_DATABASE_URL is required")
    result = asyncio.run(execute(args))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
