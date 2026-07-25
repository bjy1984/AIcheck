from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from uuid import uuid4


RAW_EVENT_SCHEMA_VERSION = "aicheck-agent-raw-event@1"
GENESIS_HASH = "GENESIS"
DEFAULT_RAW_VAULT_BUCKET = "agent-raw-vault"
logger = logging.getLogger(__name__)


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RawCaptureContext:
    tenant_id: str
    run_stream_id: str
    project_id: str | None = None
    review_run_id: str | None = None
    ai_run_id: str | None = None
    model_call_attempt_id: str | None = None
    provider_tool_call_id: str | None = None
    stage: str | None = None
    turn: int | None = None


@dataclass(frozen=True)
class CapturedRawEvent:
    id: str
    schema_version: str
    tenant_id: str
    run_stream_id: str
    event_type: str
    sequence: int
    has_payload: bool
    previous_event_hash: str
    event_hash: str
    metadata: dict[str, Any]
    created_at: str
    project_id: str | None = None
    review_run_id: str | None = None
    ai_run_id: str | None = None
    model_call_attempt_id: str | None = None
    provider_tool_call_id: str | None = None
    stage: str | None = None
    turn: int | None = None
    payload_media_type: str | None = None
    payload_byte_length: int | None = None
    payload_hash: str | None = None
    object_bucket: str | None = None
    object_key: str | None = None


@dataclass(frozen=True)
class RawCaptureFailure:
    event_type: str
    reason: str
    tenant_id: str
    run_stream_id: str


@dataclass(frozen=True)
class ChainVerification:
    status: str
    findings: list[dict[str, Any]]
    event_count: int
    chain_head: str | None


class RawVaultStore(Protocol):
    def append(
        self,
        context: RawCaptureContext,
        event_type: str,
        payload: bytes,
        media_type: str,
        metadata: dict[str, Any],
    ) -> CapturedRawEvent: ...

    def append_metadata(
        self,
        context: RawCaptureContext,
        event_type: str,
        metadata: dict[str, Any],
    ) -> CapturedRawEvent: ...


def event_hash_document(event: CapturedRawEvent) -> dict[str, Any]:
    document = asdict(event)
    document.pop("event_hash", None)
    return document


def calculate_event_hash(event: CapturedRawEvent) -> str:
    canonical = canonical_json_bytes(event_hash_document(event))
    return "sha256:" + hashlib.sha256(
        event.previous_event_hash.encode("utf-8") + b":" + canonical
    ).hexdigest()


def _object_extension(media_type: str) -> str:
    return "json" if "json" in media_type.lower() else "bin"


def _event_without_hash(
    context: RawCaptureContext,
    *,
    event_id: str,
    event_type: str,
    sequence: int,
    previous_event_hash: str,
    metadata: dict[str, Any],
    created_at: str,
    payload: bytes | None,
    media_type: str | None,
    bucket: str,
) -> CapturedRawEvent:
    has_payload = payload is not None
    object_key = None
    if has_payload and media_type is not None:
        object_key = (
            f"{context.tenant_id}/{context.run_stream_id}/"
            f"{sequence:06d}-{event_id}.{_object_extension(media_type)}"
        )
    event = CapturedRawEvent(
        id=event_id,
        schema_version=RAW_EVENT_SCHEMA_VERSION,
        tenant_id=context.tenant_id,
        run_stream_id=context.run_stream_id,
        project_id=context.project_id,
        review_run_id=context.review_run_id,
        ai_run_id=context.ai_run_id,
        model_call_attempt_id=context.model_call_attempt_id,
        provider_tool_call_id=context.provider_tool_call_id,
        stage=context.stage,
        event_type=event_type,
        turn=context.turn,
        sequence=sequence,
        has_payload=has_payload,
        payload_media_type=media_type if has_payload else None,
        payload_byte_length=len(payload) if payload is not None else None,
        payload_hash=sha256_bytes(payload) if payload is not None else None,
        object_bucket=bucket if has_payload else None,
        object_key=object_key,
        previous_event_hash=previous_event_hash,
        event_hash="",
        metadata=dict(metadata),
        created_at=created_at,
    )
    return CapturedRawEvent(**{**asdict(event), "event_hash": calculate_event_hash(event)})


class InMemoryRawVaultStore:
    def __init__(self, *, bucket: str = DEFAULT_RAW_VAULT_BUCKET) -> None:
        self.bucket = bucket
        self._events: dict[tuple[str, str], list[CapturedRawEvent]] = {}
        self._payloads: dict[str, bytes] = {}
        self._pending: list[str] = []
        self._lock = threading.Lock()

    def append(
        self,
        context: RawCaptureContext,
        event_type: str,
        payload: bytes,
        media_type: str,
        metadata: dict[str, Any],
    ) -> CapturedRawEvent:
        return self._append(context, event_type, bytes(payload), media_type, metadata)

    def append_metadata(
        self,
        context: RawCaptureContext,
        event_type: str,
        metadata: dict[str, Any],
    ) -> CapturedRawEvent:
        return self._append(context, event_type, None, None, metadata)

    def _append(
        self,
        context: RawCaptureContext,
        event_type: str,
        payload: bytes | None,
        media_type: str | None,
        metadata: dict[str, Any],
    ) -> CapturedRawEvent:
        key = (context.tenant_id, context.run_stream_id)
        with self._lock:
            events = self._events.setdefault(key, [])
            sequence = len(events) + 1
            previous_hash = events[-1].event_hash if events else GENESIS_HASH
            event = _event_without_hash(
                context,
                event_id=f"RAWEVT-{uuid4().hex[:16].upper()}",
                event_type=event_type,
                sequence=sequence,
                previous_event_hash=previous_hash,
                metadata=metadata,
                created_at=utc_timestamp(),
                payload=payload,
                media_type=media_type,
                bucket=self.bucket,
            )
            events.append(event)
            if payload is not None:
                self._payloads[event.id] = payload
                self._pending.append(event.id)
            return event

    def events_for_run(self, tenant_id: str, run_stream_id: str) -> list[CapturedRawEvent]:
        with self._lock:
            return list(self._events.get((tenant_id, run_stream_id), []))

    def payload_for(self, event_id: str) -> bytes | None:
        with self._lock:
            return self._payloads.get(event_id)

    def pending_event_ids(self) -> list[str]:
        with self._lock:
            return list(self._pending)


class PostgresRawVaultStore:
    def __init__(self, dsn: str, *, bucket: str = DEFAULT_RAW_VAULT_BUCKET) -> None:
        self.dsn = dsn
        self.bucket = bucket

    def append(
        self,
        context: RawCaptureContext,
        event_type: str,
        payload: bytes,
        media_type: str,
        metadata: dict[str, Any],
    ) -> CapturedRawEvent:
        return self._append(context, event_type, bytes(payload), media_type, metadata)

    def append_metadata(
        self,
        context: RawCaptureContext,
        event_type: str,
        metadata: dict[str, Any],
    ) -> CapturedRawEvent:
        return self._append(context, event_type, None, None, metadata)

    def _append(
        self,
        context: RawCaptureContext,
        event_type: str,
        payload: bytes | None,
        media_type: str | None,
        metadata: dict[str, Any],
    ) -> CapturedRawEvent:
        import psycopg
        from psycopg.types.json import Jsonb

        with psycopg.connect(self.dsn, autocommit=False) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"aicheck:raw-vault:{context.tenant_id}:{context.run_stream_id}",),
            )
            head = connection.execute(
                """
                SELECT sequence, event_hash
                FROM raw_vault_events
                WHERE tenant_id = %s AND run_stream_id = %s
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (context.tenant_id, context.run_stream_id),
            ).fetchone()
            sequence = int(head[0]) + 1 if head else 1
            previous_hash = str(head[1]) if head else GENESIS_HASH
            event = _event_without_hash(
                context,
                event_id=f"RAWEVT-{uuid4().hex[:16].upper()}",
                event_type=event_type,
                sequence=sequence,
                previous_event_hash=previous_hash,
                metadata=metadata,
                created_at=utc_timestamp(),
                payload=payload,
                media_type=media_type,
                bucket=self.bucket,
            )
            connection.execute(
                """
                INSERT INTO raw_vault_events (
                    tenant_id, id, run_stream_id, project_id, review_run_id, ai_run_id,
                    model_call_attempt_id, provider_tool_call_id, stage, event_type, turn,
                    sequence, has_payload, payload_media_type, payload_byte_length,
                    payload_hash, object_bucket, object_key, previous_event_hash,
                    event_hash, metadata, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::timestamptz
                )
                """,
                (
                    event.tenant_id,
                    event.id,
                    event.run_stream_id,
                    event.project_id,
                    event.review_run_id,
                    event.ai_run_id,
                    event.model_call_attempt_id,
                    event.provider_tool_call_id,
                    event.stage,
                    event.event_type,
                    event.turn,
                    event.sequence,
                    event.has_payload,
                    event.payload_media_type,
                    event.payload_byte_length,
                    event.payload_hash,
                    event.object_bucket,
                    event.object_key,
                    event.previous_event_hash,
                    event.event_hash,
                    Jsonb(event.metadata),
                    event.created_at,
                ),
            )
            if payload is not None:
                connection.execute(
                    """
                    INSERT INTO raw_vault_outbox (
                        tenant_id, event_id, run_stream_id, payload, payload_hash,
                        object_bucket, object_key
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        event.tenant_id,
                        event.id,
                        event.run_stream_id,
                        payload,
                        event.payload_hash,
                        event.object_bucket,
                        event.object_key,
                    ),
                )
            connection.commit()
            return event


def default_failure_reporter(payload: dict[str, str]) -> None:
    logger.critical("raw_vault_capture_failed %s", json.dumps(payload, sort_keys=True))


class RawCapture:
    def __init__(
        self,
        *,
        store: RawVaultStore,
        failure_reporter: Callable[[dict[str, str]], None] | None = None,
    ) -> None:
        self.store = store
        self.failure_reporter = failure_reporter or default_failure_reporter

    def capture_bytes(
        self,
        context: RawCaptureContext,
        event_type: str,
        payload: bytes,
        media_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> CapturedRawEvent:
        return self.store.append(context, event_type, bytes(payload), media_type, metadata or {})

    def append_metadata_event(
        self,
        context: RawCaptureContext,
        event_type: str,
        metadata: dict[str, Any],
    ) -> CapturedRawEvent:
        return self.store.append_metadata(context, event_type, dict(metadata))

    def capture_best_effort(
        self,
        context: RawCaptureContext,
        event_type: str,
        payload: bytes,
        media_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> CapturedRawEvent | RawCaptureFailure:
        try:
            return self.capture_bytes(context, event_type, payload, media_type, metadata)
        except Exception as exc:
            reason = exc.__class__.__name__
            report = {
                "eventType": event_type,
                "reason": reason,
                "runStreamId": context.run_stream_id,
                "tenantId": context.tenant_id,
            }
            self.failure_reporter(report)
            return RawCaptureFailure(
                event_type=event_type,
                reason=reason,
                tenant_id=context.tenant_id,
                run_stream_id=context.run_stream_id,
            )


def verify_event_chain(
    events: list[CapturedRawEvent],
    payload_loader: Callable[[str], bytes | None] | None = None,
) -> ChainVerification:
    findings: list[dict[str, Any]] = []
    expected_sequence = 1
    previous_hash = GENESIS_HASH
    for event in sorted(events, key=lambda item: item.sequence):
        if event.sequence != expected_sequence:
            findings.append(
                {
                    "eventId": event.id,
                    "reason": "sequence_mismatch",
                    "expected": expected_sequence,
                    "actual": event.sequence,
                }
            )
            break
        if event.previous_event_hash != previous_hash:
            findings.append({"eventId": event.id, "reason": "previous_event_hash_mismatch"})
            break
        if calculate_event_hash(replace_event_hash(event, "")) != event.event_hash:
            findings.append({"eventId": event.id, "reason": "event_hash_mismatch"})
            break
        if event.has_payload and payload_loader is not None:
            payload = payload_loader(event.id)
            if payload is None:
                findings.append({"eventId": event.id, "reason": "payload_missing"})
                break
            if sha256_bytes(payload) != event.payload_hash:
                findings.append({"eventId": event.id, "reason": "payload_hash_mismatch"})
                break
        previous_hash = event.event_hash
        expected_sequence += 1
    return ChainVerification(
        status="hash_mismatch" if findings else "verified",
        findings=findings,
        event_count=len(events),
        chain_head=events[-1].event_hash if events else None,
    )


def replace_event_hash(event: CapturedRawEvent, event_hash: str) -> CapturedRawEvent:
    values = asdict(event)
    values["event_hash"] = event_hash
    return CapturedRawEvent(**values)


def raw_capture_from_environment() -> RawCapture | None:
    dsn = os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        return None
    bucket = os.getenv("AICHECK_RAW_VAULT_BUCKET", DEFAULT_RAW_VAULT_BUCKET)
    return RawCapture(store=PostgresRawVaultStore(dsn, bucket=bucket))


def raw_context_from_record(
    record: dict[str, Any],
    *,
    run_stream_id: str | None = None,
    model_call_attempt_id: str | None = None,
    stage: str | None = None,
    turn: int | None = None,
) -> RawCaptureContext:
    stream = str(
        run_stream_id
        or record.get("reviewRunId")
        or record.get("pipelineRunId")
        or record.get("aiRunId")
        or record.get("id")
        or ""
    )
    if not stream:
        raise ValueError("raw vault run_stream_id is required")
    return RawCaptureContext(
        tenant_id=str(record.get("tenantId") or os.getenv("AICHECK_TENANT_ID") or "default"),
        run_stream_id=stream,
        project_id=str(record.get("projectId") or "") or None,
        review_run_id=str(record.get("reviewRunId") or "") or None,
        ai_run_id=str(record.get("aiRunId") or "") or None,
        model_call_attempt_id=model_call_attempt_id,
        stage=stage or (str(record.get("stage") or "") or None),
        turn=turn,
    )


def postgres_events_for_run(
    dsn: str,
    tenant_id: str,
    run_id: str,
) -> tuple[list[CapturedRawEvent], int]:
    import psycopg

    with psycopg.connect(dsn) as connection:
        rows = connection.execute(
            """
            SELECT id, run_stream_id, event_type, sequence, has_payload,
                   previous_event_hash, event_hash, metadata, created_at,
                   project_id, review_run_id, ai_run_id, model_call_attempt_id,
                   provider_tool_call_id, stage, turn, payload_media_type,
                   payload_byte_length, payload_hash, object_bucket, object_key
            FROM raw_vault_events
            WHERE tenant_id = %s AND (review_run_id = %s OR run_stream_id = %s)
            ORDER BY sequence
            """,
            (tenant_id, run_id, run_id),
        ).fetchall()
        events = [
            CapturedRawEvent(
                id=str(row[0]),
                schema_version=RAW_EVENT_SCHEMA_VERSION,
                tenant_id=tenant_id,
                run_stream_id=str(row[1]),
                event_type=str(row[2]),
                sequence=int(row[3]),
                has_payload=bool(row[4]),
                previous_event_hash=str(row[5]),
                event_hash=str(row[6]),
                metadata=dict(row[7] or {}),
                created_at=row[8].isoformat(),
                project_id=row[9],
                review_run_id=row[10],
                ai_run_id=row[11],
                model_call_attempt_id=row[12],
                provider_tool_call_id=row[13],
                stage=row[14],
                turn=row[15],
                payload_media_type=row[16],
                payload_byte_length=row[17],
                payload_hash=row[18],
                object_bucket=row[19],
                object_key=row[20],
            )
            for row in rows
        ]
        pending = connection.execute(
            """
            SELECT count(*)
            FROM raw_vault_outbox o
            JOIN raw_vault_events e ON e.tenant_id = o.tenant_id AND e.id = o.event_id
            WHERE o.tenant_id = %s AND (e.review_run_id = %s OR e.run_stream_id = %s)
              AND o.status <> 'hash_mismatch'
            """,
            (tenant_id, run_id, run_id),
        ).fetchone()
        return events, int(pending[0] if pending else 0)


def postgres_pending_payload(dsn: str, tenant_id: str, event_id: str) -> bytes | None:
    import psycopg

    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            "SELECT payload FROM raw_vault_outbox WHERE tenant_id = %s AND event_id = %s",
            (tenant_id, event_id),
        ).fetchone()
        return bytes(row[0]) if row else None


def capture_agent_turn(
    capture: RawCapture | None,
    context: RawCaptureContext,
    event_type: str,
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    model_parameters: dict[str, Any] | None = None,
) -> CapturedRawEvent | RawCaptureFailure | None:
    if capture is None:
        return None
    return capture.capture_best_effort(
        context,
        event_type,
        canonical_json_bytes(
            {
                "messages": messages,
                "tools": tools or [],
                "modelParameters": model_parameters or {},
                "turn": context.turn,
                "stage": context.stage,
            }
        ),
        "application/json",
    )


def capture_tool_request(
    capture: RawCapture | None,
    context: RawCaptureContext,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    provider_tool_call_id: str,
    raw_arguments: str | bytes | None = None,
) -> CapturedRawEvent | RawCaptureFailure | None:
    if capture is None:
        return None
    payload = (
        raw_arguments.encode("utf-8")
        if isinstance(raw_arguments, str)
        else bytes(raw_arguments)
        if raw_arguments is not None
        else canonical_json_bytes(arguments)
    )
    return capture.capture_best_effort(
        replace(context, provider_tool_call_id=provider_tool_call_id),
        "tool.call.requested",
        payload,
        "application/json",
        {"toolName": tool_name, "parsedArguments": arguments},
    )


def capture_tool_result(
    capture: RawCapture | None,
    context: RawCaptureContext,
    tool_name: str,
    result: Any,
    *,
    provider_tool_call_id: str,
) -> CapturedRawEvent | RawCaptureFailure | None:
    if capture is None:
        return None
    return capture.capture_best_effort(
        replace(context, provider_tool_call_id=provider_tool_call_id),
        "tool.call.completed",
        canonical_json_bytes(result),
        "application/json",
        {"toolName": tool_name},
    )


def capture_tool_error(
    capture: RawCapture | None,
    context: RawCaptureContext,
    tool_name: str,
    exc: Exception,
    *,
    provider_tool_call_id: str,
) -> CapturedRawEvent | RawCaptureFailure | None:
    if capture is None:
        return None
    return capture.capture_best_effort(
        replace(context, provider_tool_call_id=provider_tool_call_id),
        "tool.call.failed",
        canonical_json_bytes(
            {
                "exceptionType": type(exc).__name__,
                "message": str(exc)[:500],
                "phase": "tool_execution",
                "toolName": tool_name,
            }
        ),
        "application/json",
        {"toolName": tool_name},
    )
