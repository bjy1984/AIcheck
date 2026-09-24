from __future__ import annotations

from typing import Any

from libs.material_targeting import set_node_evidence_link_manual_status


def apply_manual_evidence_decision(
    repo: Any,
    project_id: str,
    node_id: int,
    link_id: str,
    manual_status: str,
    body: dict[str, Any],
    actor: dict[str, Any],
) -> dict[str, Any] | None:
    expected_revision = body.get("expectedRevision")
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
        raise ValueError("invalid_evidence_revision")
    actor_name = str(body.get("actorName") or actor.get("name") or actor.get("username") or "").strip()
    return set_node_evidence_link_manual_status(
        repo, project_id, node_id, link_id, manual_status,
        actor_name=actor_name,
        comment=str(body.get("comment") or ""),
        expected_revision=expected_revision,
    )
