"""Resolve explicit, run-only input versions without changing persistent document bindings."""
from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

from apps.api.document_access_policy import actor_visible_evidence_repository
from libs.material_targeting import build_node_evidence_readiness


class ReviewInputSelectionError(ValueError):
    pass


def resolve_review_input_selection(services, request, project_id: str, node_id: int,
                                   body: dict[str, Any]) -> tuple[list[str], dict[str, Any]] | None:
    if "inputDocumentVersionIds" not in body:
        return None
    if os.getenv("AICHECK_WORKSTATIONS_ENABLED", "").lower() not in {"1", "true", "yes"}:
        raise ReviewInputSelectionError("本环境尚未开放本次审查文件选择。")
    versions = body["inputDocumentVersionIds"]
    if (not isinstance(versions, list) or not versions or len(versions) > 500
            or any(not isinstance(value, str) or not value.strip() for value in versions)
            or len(set(versions)) != len(versions)):
        raise ReviewInputSelectionError("请选择 1–500 个不同的文件版本。")
    detached = actor_visible_evidence_repository(services, request, project_id)
    visible = {str(row.get("id") or ""): row for row in detached.state.get("versions", [])
               if services.tenant_id_for_record(row) == services.request_tenant_id(request)}
    if set(versions) - visible.keys():
        raise ReviewInputSelectionError("所选文件版本不存在或不在当前账号可访问范围，请刷新后重新选择。")
    chosen = set(versions)
    documents = {str(row.get("id") or ""): row for row in detached.state.get("documents", [])}
    if any(not services.document_body_uploaded(documents.get(str(visible[value].get("documentId") or "")), visible[value])
           for value in versions):
        raise ReviewInputSelectionError("所选文件版本尚未上传完整，请完成上传后重新选择。")

    def selected(row):
        version = row.get("documentVersionId")
        if version:
            return str(version) in chosen
        document = documents.get(str(row.get("documentId") or "")) or {}
        return str(document.get("currentVersionId") or "") in chosen

    for key in ("bindings", "node_evidence_links"):
        detached.state[key] = [row for row in detached.state.get(key, []) if selected(row)]
    readiness = deepcopy(build_node_evidence_readiness(detached, project_id, node_id))
    # Supplemental files need not already be mounted or matched to a requirement.
    # Formal readiness still comes exclusively from existing confirmed evidence.
    readiness["readyForGapPrecheck"] = True
    readiness["inputSelection"] = {"mode": "explicit", "documentVersionIds": sorted(chosen), "scope": "run_only"}
    return sorted(chosen), readiness
