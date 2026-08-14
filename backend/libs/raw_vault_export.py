from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable
from dataclasses import asdict

from libs.raw_vault import (
    CapturedRawEvent,
    ChainVerification,
    canonical_json_bytes,
    sha256_bytes,
    verify_event_chain,
)


def build_raw_vault_summary(
    events: list[CapturedRawEvent],
    *,
    pending_count: int = 0,
) -> dict:
    verification = verify_event_chain(events)
    status = (
        "hash_mismatch"
        if verification.status != "verified"
        else "archive_incomplete"
        if pending_count
        else "complete"
    )
    return {
        "reviewRunId": events[0].review_run_id if events else None,
        "runStreamId": events[0].run_stream_id if events else None,
        "status": status,
        "chainHead": verification.chain_head,
        "eventCount": len(events),
        "pendingCount": pending_count,
        "events": [event_public_view(event) for event in events],
    }


def event_public_view(event: CapturedRawEvent) -> dict:
    return {
        "id": event.id,
        "eventType": event.event_type,
        "sequence": event.sequence,
        "stage": event.stage,
        "turn": event.turn,
        "hasPayload": event.has_payload,
        "payloadHash": event.payload_hash,
        "payloadByteLength": event.payload_byte_length,
        "payloadMediaType": event.payload_media_type,
        "eventHash": event.event_hash,
        "previousEventHash": event.previous_event_hash,
        "metadata": event.metadata,
        "createdAt": event.created_at,
    }


def build_raw_vault_export(
    events: list[CapturedRawEvent],
    *,
    payload_loader: Callable[[str], bytes | None],
) -> bytes:
    ordered = sorted(events, key=lambda event: event.sequence)
    event_documents = [asdict(event) for event in ordered]
    payloads: list[dict] = []
    payload_files: dict[str, bytes] = {}
    for event in ordered:
        if not event.has_payload:
            continue
        payload = payload_loader(event.id)
        if payload is None:
            raise ValueError(f"raw vault payload missing: {event.id}")
        extension = "json" if "json" in str(event.payload_media_type).lower() else "bin"
        path = f"payloads/{event.sequence:06d}-{event.id}.{extension}"
        payload_files[path] = payload
        payloads.append(
            {
                "eventId": event.id,
                "path": path,
                "sha256": event.payload_hash,
                "byteLength": len(payload),
                "mediaType": event.payload_media_type,
            }
        )
    events_bytes = canonical_json_bytes(event_documents)
    manifest = {
        "schemaVersion": "aicheck-raw-vault-export@1",
        "tenantId": ordered[0].tenant_id if ordered else None,
        "runStreamId": ordered[0].run_stream_id if ordered else None,
        "eventCount": len(ordered),
        "chainHead": ordered[-1].event_hash if ordered else None,
        "eventsPath": "events.json",
        "eventsSha256": sha256_bytes(events_bytes),
        "payloads": payloads,
    }
    manifest["manifestRoot"] = sha256_bytes(canonical_json_bytes(manifest))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("manifest.json", canonical_json_bytes(manifest))
        package.writestr("events.json", events_bytes)
        for path, payload in payload_files.items():
            package.writestr(path, payload)
    return output.getvalue()


def verify_export_bytes(archive: bytes) -> ChainVerification:
    findings: list[dict] = []
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            manifest = json.loads(package.read("manifest.json"))
            root = manifest.pop("manifestRoot", None)
            if root != sha256_bytes(canonical_json_bytes(manifest)):
                findings.append({"reason": "manifest_root_mismatch"})
            events_bytes = package.read(str(manifest["eventsPath"]))
            if sha256_bytes(events_bytes) != manifest["eventsSha256"]:
                findings.append({"reason": "events_hash_mismatch"})
            documents = json.loads(events_bytes)
            events = [CapturedRawEvent(**document) for document in documents]
            payload_by_event: dict[str, bytes] = {}
            for item in manifest.get("payloads") or []:
                payload = package.read(item["path"])
                payload_by_event[str(item["eventId"])] = payload
                if sha256_bytes(payload) != item["sha256"]:
                    findings.append(
                        {"eventId": item["eventId"], "reason": "payload_hash_mismatch"}
                    )
            chain = verify_event_chain(events, payload_loader=payload_by_event.get)
            findings.extend(chain.findings)
            return ChainVerification(
                status="hash_mismatch" if findings else "verified",
                findings=findings,
                event_count=len(events),
                chain_head=chain.chain_head,
            )
    except Exception as exc:
        return ChainVerification(
            status="hash_mismatch",
            findings=[{"reason": "invalid_archive", "error": type(exc).__name__}],
            event_count=0,
            chain_head=None,
        )
