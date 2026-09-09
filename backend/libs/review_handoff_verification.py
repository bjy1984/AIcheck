"""Append-only human attestations bound to a handoff; never grant execution authority."""

from __future__ import annotations

from copy import deepcopy
from threading import Lock
from typing import Any

from libs.review_workstations import digest

_VERIFICATION_LOCK = Lock()


def verification_history(record: dict[str, Any]) -> list[dict[str, Any]]:
    rows = record.get("verifications", [])
    if not isinstance(rows, list):
        raise TypeError("handoff_verification_history_invalid")
    previous = None
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("handoff_verification_record_invalid")
        content = {key: value for key, value in row.items() if key != "id"}
        if (
            row.get("id") != "HVERIFY-" + digest(content)[:24].upper()
            or row.get("previousId") != previous
            or row.get("handoffId") != record["id"]
            or row.get("snapshotHash") != record["draft"]["snapshotHash"]
        ):
            raise ValueError("handoff_verification_history_changed")
        previous = row["id"]
    return rows


def append_verification(
    record: dict[str, Any], body: dict[str, Any], *, actor: str, created_at: str
) -> None:
    # Serializes optimistic append within this repository process. Deployment still
    # requires database-level coordination before enabling multiple API writers.
    with _VERIFICATION_LOCK:
        _append_verification(record, body, actor=actor, created_at=created_at)


def _append_verification(
    record: dict[str, Any], body: dict[str, Any], *, actor: str, created_at: str
) -> None:
    fields = {
        "snapshotHash",
        "expectedPreviousId",
        "subject",
        "outcome",
        "objectMatchConfirmed",
        "evidenceSupportConfirmed",
        "note",
    }
    if set(body) != fields:
        raise ValueError("handoff_verification_fields_invalid")
    draft = record["draft"]
    if draft["schemaVersion"] not in {"review-handoff-draft-v2", "review-handoff-draft-v3"}:
        raise ValueError("handoff_event_scoped_draft_required")
    history = verification_history(record)
    previous = history[-1]["id"] if history else None
    if body["expectedPreviousId"] != previous or body["snapshotHash"] != draft["snapshotHash"]:
        raise ValueError("handoff_verification_revision_changed")
    if body["subject"] != draft["subject"]:
        raise ValueError("handoff_verification_subject_changed")
    if (
        body["outcome"] not in {"verified", "rejected"}
        or type(body["objectMatchConfirmed"]) is not bool
        or type(body["evidenceSupportConfirmed"]) is not bool
        or not isinstance(body["note"], str)
        or not body["note"].strip()
    ):
        raise ValueError("handoff_verification_decision_invalid")
    if body["outcome"] == "verified" and not (
        body["objectMatchConfirmed"] and body["evidenceSupportConfirmed"]
    ):
        raise ValueError("handoff_verification_confirmations_required")
    if not actor or not created_at:
        raise ValueError("handoff_verification_actor_required")
    row = {
        "schemaVersion": "review-handoff-verification-v1",
        "handoffId": record["id"],
        "snapshotHash": draft["snapshotHash"],
        "subject": deepcopy(draft["subject"]),
        "previousId": previous,
        "outcome": body["outcome"],
        "objectMatchConfirmed": body["objectMatchConfirmed"],
        "evidenceSupportConfirmed": body["evidenceSupportConfirmed"],
        "note": body["note"].strip(),
        "reviewedByUserId": actor,
        "createdAt": created_at,
    }
    row["id"] = "HVERIFY-" + digest(row)[:24].upper()
    record["verifications"] = [*history, row]


def verification_view(record: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    try:
        history = verification_history(record)
    except (TypeError, ValueError):
        return {"status": "invalid_history", "authoritative": False}
    if not history:
        return {"status": "unreviewed", "authoritative": False}
    current = (
        validation.get("status") == "current_draft"
        and (validation.get("inputSourceCheck") or {}).get("status") == "current"
    )
    return {
        "status": history[-1]["outcome"] if current else "stale",
        "latestVerificationId": history[-1]["id"],
        "authoritative": False,
    }
