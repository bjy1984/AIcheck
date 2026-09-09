"""Draft workstation handoffs; publication and authoritative consumption are separate gates."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_workstations import digest, station_snapshot


class ReviewHandoffError(ValueError):
    pass


def _identity(run: dict[str, Any]) -> dict[str, Any]:
    station = station_snapshot(run)
    if not station:
        raise ReviewHandoffError("handoff_workstation_snapshot_required")
    values = {"runId": run.get("reviewRunId") or run.get("id"), "projectId": run.get("projectId"),
              "tenantId": run.get("tenantId"), "businessPackId": run.get("businessPackId"),
              "inputHash": run.get("inputHash"), "stationId": station["stationId"], "nodeId": run.get("nodeId")}
    if any(value is None or value == "" for value in values.values()):
        raise ReviewHandoffError("handoff_run_identity_incomplete")
    values["documentVersionIds"] = deepcopy(run.get("inputDocumentVersionIds") or [])
    values["versionHash"] = digest({"identity": values, "station": station,
                                   "documents": run.get("documentScopeSnapshot"),
                                   "documentVersionIds": run.get("inputDocumentVersionIds"), "status": run.get("status"),
                                   "rule": run.get("effectiveRuleSnapshot"),
                                   "outputHash": run.get("outputHash"), "findings": run.get("findingDrafts")})
    return values


def create_handoff_draft(source: dict[str, Any], target: dict[str, Any], *, kind: str,
                         subject: dict[str, Any], payload: dict[str, Any], evidence_refs: list[dict[str, Any]]) -> dict[str, Any]:
    """New drafts bind a caller-supplied event; its real-world identity is unverified."""
    return _build_handoff_draft(source, target, kind=kind, subject=subject, payload=payload,
                                evidence_refs=evidence_refs, schema="review-handoff-draft-v2")


def _build_handoff_draft(source, target, *, kind, subject, payload, evidence_refs, schema):
    """Reconstruct v1 only for historical validation; no public downgrade path."""
    if kind not in {"facts", "judgment", "collaboration"}:
        raise ReviewHandoffError("handoff_kind_invalid")
    if not isinstance(payload, dict) or not payload:
        raise ReviewHandoffError("handoff_payload_required")
    fields = {"objectType", "objectId", "repairRound"}
    if schema == "review-handoff-draft-v2":
        fields.add("eventId")
    if (not isinstance(subject, dict) or set(subject) != fields
            or subject["objectType"] not in {"project", "pipeline", "weld", "material", "component"}
            or not isinstance(subject["objectId"], str) or not subject["objectId"].strip()
            or type(subject["repairRound"]) is not int or subject["repairRound"] < 0):
        raise ReviewHandoffError("handoff_subject_invalid")
    if schema == "review-handoff-draft-v2" and (
            not isinstance(subject["eventId"], str) or not subject["eventId"].strip()
            or subject["eventId"] != subject["eventId"].strip()):
        raise ReviewHandoffError("handoff_event_identity_required")
    origin, recipient = _identity(source), _identity(target)
    if any(origin[key] != recipient[key] for key in ("projectId", "tenantId", "businessPackId")):
        raise ReviewHandoffError("handoff_scope_mismatch")
    if origin["runId"] == recipient["runId"] or origin["nodeId"] == recipient["nodeId"]:
        raise ReviewHandoffError("handoff_distinct_nodes_required")
    allowed = set(source.get("inputDocumentVersionIds") or [])
    if not isinstance(evidence_refs, list) or (kind != "collaboration" and not evidence_refs):
        raise ReviewHandoffError("handoff_evidence_required")
    for evidence in evidence_refs:
        if (not isinstance(evidence, dict) or evidence.get("documentVersionId") not in allowed
                or type(evidence.get("pageNo")) is not int or evidence["pageNo"] < 1):
            raise ReviewHandoffError("handoff_evidence_outside_source")
    record = {"schemaVersion": schema, "kind": kind, "source": origin, "target": recipient,
              "subject": deepcopy(subject), "payload": deepcopy(payload), "evidenceRefs": deepcopy(evidence_refs),
              "lifecycleStatus": "draft", "authoritative": False, "objectMatchStatus": "unverified",
              "evidenceVerificationStatus": "unverified"}
    record["snapshotHash"] = digest(record)
    record["id"] = "HANDOFF-" + record["snapshotHash"][:24].upper()
    return record


def validate_handoff_draft(record: dict[str, Any], source: dict[str, Any], target: dict[str, Any],
                           *, subject: dict[str, Any]) -> None:
    """Reject changed inputs, destinations, objects and repair rounds; never mutate history."""
    if record.get("schemaVersion") not in {"review-handoff-draft-v1", "review-handoff-draft-v2"}:
        raise ReviewHandoffError("handoff_schema_invalid")
    content = {key: value for key, value in record.items() if key not in {"id", "snapshotHash"}}
    if record.get("snapshotHash") != digest(content) or record.get("id") != "HANDOFF-" + digest(content)[:24].upper():
        raise ReviewHandoffError("handoff_snapshot_changed")
    if record.get("source") != _identity(source) or record.get("target") != _identity(target):
        raise ReviewHandoffError("handoff_run_version_changed")
    if record.get("subject") != subject:
        raise ReviewHandoffError("handoff_subject_changed")
    if record.get("lifecycleStatus") != "draft" or record.get("authoritative") is not False:
        raise ReviewHandoffError("handoff_draft_cannot_grant_authority")
    expected = _build_handoff_draft(source, target, kind=record.get("kind"), subject=subject,
                                   payload=record.get("payload"), evidence_refs=record.get("evidenceRefs"),
                                   schema=record["schemaVersion"])
    if record != expected:
        raise ReviewHandoffError("handoff_draft_contract_changed")
