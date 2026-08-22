"""Organization-, tenant-, and relationship-aware document read policy.

``apps.api.routes`` remains the composition root.  The explicit service protocol
keeps this policy reusable without importing the route monolith or duplicating
its authentication and node-scope rules.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from fastapi import Request
from fastapi.responses import JSONResponse

from libs.contracts import errors
from libs.contracts.responses import fail
from libs.db.repository import InMemoryRepository
from libs.material_targeting import build_node_evidence_readiness
from libs.node_document_identity import record_references_report


class DocumentAccessServices(Protocol):
    """Route-level policy operations consumed by the extracted predicates."""

    repo: Any
    SUBMITTED_DOCUMENT_BINDING_STATUSES: set[str]

    def request_user_id(self, request: Request) -> str | None: ...
    def request_tenant_id(self, request: Request) -> str: ...
    def tenant_id_for_record(self, record: dict[str, Any]) -> str: ...
    def effective_role_for_request(
        self, request: Request, x_role: str | None = None
    ) -> tuple[str | None, JSONResponse | None]: ...
    def authentication_enforced(self) -> bool: ...
    def authorized_node_scope(self, request: Request, project_id: str) -> set[int] | None: ...
    def member_node_scope_error(self, request: Request, project_id: str, role: str | None, **kwargs: Any) -> JSONResponse | None: ...
    def document_node_ids(self, project_id: str, document_id: str) -> list[int]: ...
    def report_node_ids(self, project_id: str, report_id: str) -> set[int]: ...
    def record_visible_for_request(self, request: Request, record: dict[str, Any], project_id: str) -> bool: ...
    def document_read_error(self, request: Request, project_id: str, document: dict[str, Any] | None) -> JSONResponse | None: ...
    def scoped_binding_ids(self, project_id: str, node_ids: list[int], binding_ids: list[str] | None) -> list[str]: ...


def add_node_id(node_ids: set[int], value: Any) -> None:
    if value is None or value == "":
        return
    try:
        node_ids.add(int(value))
    except (TypeError, ValueError):
        return


def document_project_id(
    services: DocumentAccessServices,
    document_id: str | None,
) -> str | None:
    if not document_id:
        return None
    document = services.repo.find_one("documents", document_id)
    return document.get("projectId") if document else None


def document_id_from_version(
    services: DocumentAccessServices,
    version_id: str | None,
) -> str | None:
    if not version_id:
        return None
    version = services.repo.find_one("versions", version_id)
    return version.get("documentId") if version else None


def knowledge_file(
    services: DocumentAccessServices,
    file_id: str | None,
) -> dict[str, Any] | None:
    if not file_id:
        return None
    return services.repo.find_one("knowledge_files", file_id)


def document_for_record(
    services: DocumentAccessServices,
    record: dict[str, Any],
) -> dict[str, Any] | None:
    record_id = str(record.get("id") or "")
    direct = services.repo.find_one("documents", record_id) if record_id else None
    if direct:
        return direct
    document_id = str(record.get("documentId") or "")
    if not document_id and record.get("documentVersionId"):
        document_id = str(
            document_id_from_version(services, str(record["documentVersionId"])) or ""
        )
    if not document_id and record.get("fileId"):
        possible_file = knowledge_file(services, str(record["fileId"]))
        document_id = str(
            (possible_file or {}).get("documentId") or record.get("fileId") or ""
        )
    return services.repo.find_one("documents", document_id) if document_id else None


def knowledge_file_node_ids(
    services: DocumentAccessServices,
    file: dict[str, Any],
) -> set[int]:
    node_ids: set[int] = set()
    add_node_id(node_ids, file.get("nodeId"))
    project_id = file.get("projectId") or document_project_id(
        services,
        file.get("documentId"),
    )
    if project_id and file.get("documentId"):
        node_ids.update(services.document_node_ids(project_id, file["documentId"]))
    return node_ids


def knowledge_file_visible_in_scope(
    services: DocumentAccessServices,
    file: dict[str, Any],
    scope: set[int] | None,
) -> bool:
    if scope is None:
        return True
    if not scope:
        return False
    node_ids = knowledge_file_node_ids(services, file)
    return not node_ids or bool(node_ids & scope)


def target_record(
    services: DocumentAccessServices,
    collection: str,
    record_id: str | None,
    id_field: str = "id",
) -> dict[str, Any] | None:
    if not record_id:
        return None
    return services.repo.find_one(collection, record_id, id_field=id_field)


def record_project_id(
    services: DocumentAccessServices,
    record: dict[str, Any],
) -> str | None:
    if record.get("projectId"):
        return str(record["projectId"])
    project_id = document_project_id(services, record.get("documentId"))
    if project_id:
        return project_id
    if record.get("documentVersionId"):
        project_id = document_project_id(
            services,
            document_id_from_version(services, record.get("documentVersionId")),
        )
        if project_id:
            return project_id
    for key in ("fileId", "targetId"):
        file_id = record.get(key)
        file = knowledge_file(services, file_id)
        if file and file.get("projectId"):
            return str(file["projectId"])
        project_id = document_project_id(services, file_id)
        if project_id:
            return project_id
    target_type = record.get("targetType")
    target_id = record.get("targetId")
    if target_type == "rectification":
        related = target_record(services, "rectifications", target_id)
        return related.get("projectId") if related else None
    if target_type == "submission":
        related = target_record(
            services,
            "submissions",
            target_id,
            id_field="submissionId",
        )
        return related.get("projectId") if related else None
    if target_type == "report":
        related = target_record(services, "reports", target_id)
        return related.get("projectId") if related else None
    return None


def ndt_report_node_ids(
    services: DocumentAccessServices,
    project_id: str,
    report_id: str | None,
) -> set[int]:
    if not report_id:
        return set()
    node_ids: set[int] = set()
    report = services.repo.find_one("ndt_reports", report_id)
    if report and report.get("projectId") == project_id:
        add_node_id(node_ids, report.get("nodeId"))
        if report.get("fileId"):
            node_ids.update(services.document_node_ids(project_id, report["fileId"]))
        for film_id in report.get("relatedFilmIds") or []:
            for record in services.repo.state["ndt_records"]:
                if (
                    record.get("projectId") == project_id
                    and record.get("filmId") == film_id
                ):
                    add_node_id(node_ids, record.get("nodeId"))
            for feedback in services.repo.state["ndt_feedback"]:
                if (
                    feedback.get("projectId") == project_id
                    and film_id in set(feedback.get("relatedFilmIds") or [])
                ):
                    add_node_id(node_ids, feedback.get("nodeId"))
    for record in services.repo.state["ndt_records"]:
        if (
            record.get("projectId") == project_id
            and record.get("reportId") == report_id
        ):
            add_node_id(node_ids, record.get("nodeId"))
    for feedback in services.repo.state["ndt_feedback"]:
        if (
            feedback.get("projectId") == project_id
            and report_id in set(feedback.get("relatedReportIds") or [])
        ):
            add_node_id(node_ids, feedback.get("nodeId"))
    return node_ids


def ndt_film_node_ids(
    services: DocumentAccessServices,
    project_id: str,
    film_id: str | None,
) -> set[int]:
    if not film_id:
        return set()
    node_ids: set[int] = set()
    for record in services.repo.state["ndt_records"]:
        if record.get("projectId") == project_id and record.get("filmId") == film_id:
            add_node_id(node_ids, record.get("nodeId"))
    for feedback in services.repo.state["ndt_feedback"]:
        if (
            feedback.get("projectId") == project_id
            and film_id in set(feedback.get("relatedFilmIds") or [])
        ):
            add_node_id(node_ids, feedback.get("nodeId"))
    for report in services.repo.state["ndt_reports"]:
        if (
            report.get("projectId") == project_id
            and film_id in set(report.get("relatedFilmIds") or [])
        ):
            node_ids.update(
                ndt_report_node_ids(services, project_id, report.get("id"))
            )
    return node_ids


def record_node_ids(
    services: DocumentAccessServices,
    project_id: str,
    record: dict[str, Any],
) -> set[int]:
    node_ids: set[int] = set()
    add_node_id(node_ids, record.get("nodeId"))
    for node_id in record.get("nodeIds") or []:
        add_node_id(node_ids, node_id)

    record_id = str(record.get("id") or "")
    direct_document = (
        services.repo.find_one("documents", record_id) if record_id else None
    )
    document_id = (
        (direct_document or {}).get("id")
        or record.get("documentId")
        or document_id_from_version(services, record.get("documentVersionId"))
    )
    if document_id:
        node_ids.update(services.document_node_ids(project_id, document_id))

    file_id = record.get("fileId")
    if file_id:
        file = knowledge_file(services, file_id)
        if file:
            node_ids.update(knowledge_file_node_ids(services, file))
        else:
            node_ids.update(services.document_node_ids(project_id, file_id))

    film_id = record.get("filmId")
    if not film_id and str(record.get("id", "")).startswith("FILM-"):
        film_id = record.get("id")
    node_ids.update(ndt_film_node_ids(services, project_id, film_id))

    ndt_report_id = record.get("reportId")
    if not ndt_report_id and str(record.get("id", "")).startswith("NDT-RPT-"):
        ndt_report_id = record.get("id")
    node_ids.update(ndt_report_node_ids(services, project_id, ndt_report_id))
    for related_film_id in record.get("relatedFilmIds") or []:
        node_ids.update(ndt_film_node_ids(services, project_id, related_film_id))
    for related_report_id in record.get("relatedReportIds") or []:
        node_ids.update(
            ndt_report_node_ids(services, project_id, related_report_id)
        )

    if record.get("reportId"):
        node_ids.update(services.report_node_ids(project_id, str(record["reportId"])))
    if record.get("exportType") == "report":
        inferred_report_id = record.get("reportId")
        if not inferred_report_id and str(record.get("id", "")).startswith("EXP-RPT-"):
            inferred_report_id = str(record["id"]).replace("EXP-", "", 1)
        if inferred_report_id:
            node_ids.update(
                services.report_node_ids(project_id, str(inferred_report_id))
            )

    target_type = record.get("targetType")
    target_id = record.get("targetId")
    if target_type == "node":
        add_node_id(node_ids, target_id)
    elif target_type == "rectification":
        related = target_record(services, "rectifications", target_id)
        if related:
            add_node_id(node_ids, related.get("nodeId"))
    elif target_type == "submission":
        related = target_record(
            services,
            "submissions",
            target_id,
            id_field="submissionId",
        )
        if related:
            for node_id in related.get("nodeIds") or []:
                add_node_id(node_ids, node_id)
    elif target_type == "report":
        node_ids.update(services.report_node_ids(project_id, str(target_id)))
    elif target_type == "file":
        file = knowledge_file(services, str(target_id))
        if file:
            node_ids.update(knowledge_file_node_ids(services, file))
        else:
            node_ids.update(services.document_node_ids(project_id, str(target_id)))
    return node_ids


def record_visible_for_scope(
    services: DocumentAccessServices,
    record: dict[str, Any],
    scope: set[int] | None,
    *,
    project_id: str | None = None,
) -> bool:
    if scope is None:
        return True
    if not scope:
        return False
    effective_project_id = project_id or record_project_id(services, record)
    if not effective_project_id:
        return True
    node_ids = record_node_ids(services, effective_project_id, record)
    if not node_ids:
        return True
    if record_references_report(record):
        return node_ids.issubset(scope)
    return bool(node_ids & scope)


def record_visible_for_request(
    services: DocumentAccessServices,
    request: Request,
    record: dict[str, Any],
    project_id: str | None = None,
) -> bool:
    if services.tenant_id_for_record(record) != services.request_tenant_id(request):
        return False
    resolved_project_id = record_project_id(services, record)
    if project_id and resolved_project_id and project_id != resolved_project_id:
        return False
    effective_project_id = project_id or resolved_project_id
    if not effective_project_id:
        return True
    scope = services.authorized_node_scope(request, effective_project_id)
    if not record_visible_for_scope(
        services,
        record,
        scope,
        project_id=effective_project_id,
    ):
        return False
    document = document_for_record(services, record)
    if not document:
        return True
    if str(document.get("projectId") or "") != effective_project_id:
        return False
    role, identity_error = effective_document_actor_for_request(services, request)
    if identity_error:
        return False
    member = active_project_member_for_request(
        services,
        request,
        effective_project_id,
        role,
    )
    return document_visible_to_actor(services, document, role, member)


def active_project_member_for_request(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    role: str | None,
) -> dict[str, Any] | None:
    """Resolve exactly one active grant; ambiguous duplicates fail closed."""
    user_id = services.request_user_id(request)
    if not user_id or not role:
        return None
    matches = [
        item
        for item in services.repo.state.get("project_members", [])
        if item.get("projectId") == project_id
        and services.tenant_id_for_record(item) == services.request_tenant_id(request)
        and item.get("userId") == user_id
        and item.get("role") == role
        and item.get("status") == "启用"
    ]
    return matches[0] if len(matches) == 1 else None


def document_visible_in_scope(
    services: DocumentAccessServices,
    document: dict[str, Any],
    scope: set[int] | None,
    *,
    document_repo: Any = None,
) -> bool:
    if scope is None:
        return True
    if not scope:
        return False
    source_repo = document_repo or services.repo
    binding_node_ids = {
        int(binding["nodeId"])
        for binding in source_repo.state["bindings"]
        if binding.get("projectId") == document.get("projectId")
        and binding.get("documentId") == document.get("id")
    }
    add_node_id(binding_node_ids, document.get("nodeId"))
    return not binding_node_ids or bool(binding_node_ids & scope)


def document_is_submitted(
    services: DocumentAccessServices,
    document: dict[str, Any],
) -> bool:
    if str(document.get("poolSubmissionStatus") or "") == "已提交":
        return True
    document_id = str(document.get("id") or "")
    project_id = str(document.get("projectId") or "")
    return any(
        str(binding.get("bindingStatus") or "")
        in services.SUBMITTED_DOCUMENT_BINDING_STATUSES
        for binding in services.repo.state.get("bindings", [])
        if str(binding.get("documentId") or "") == document_id
        and str(binding.get("projectId") or "") == project_id
    )


def normalized_organization_name(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"\s+", "", normalized)


def document_visible_to_actor(
    services: DocumentAccessServices,
    document: dict[str, Any],
    role: str | None,
    member: dict[str, Any] | None,
) -> bool:
    """Apply the single role/organization visibility matrix."""
    effective_role = str(role or "").strip().lower()
    if effective_role in {"admin", "fde", "inspection"}:
        return True
    if effective_role in {"contractor", "ndt"}:
        if not member:
            return False
        document_org_id = str(document.get("sourceOrgId") or "").strip()
        member_org_id = str(member.get("orgId") or "").strip()
        if document_org_id:
            return bool(member_org_id) and document_org_id == member_org_id
        document_org_name = normalized_organization_name(document.get("sourceOrgName"))
        member_org_name = normalized_organization_name(member.get("orgName"))
        return (
            bool(document_org_name and member_org_name)
            and document_org_name == member_org_name
        )
    if effective_role == "owner":
        return document_is_submitted(services, document)
    return False


def effective_document_actor_for_request(
    services: DocumentAccessServices,
    request: Request,
) -> tuple[str | None, JSONResponse | None]:
    role, identity_error = services.effective_role_for_request(request)
    if identity_error:
        return None, identity_error
    if (
        role is None
        and services.request_user_id(request) is None
        and not services.authentication_enforced()
    ):
        return "inspection", None
    return role, None


def visible_project_documents_for_request(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    *,
    document_repo: Any = None,
) -> list[dict[str, Any]]:
    """Project every actor-facing list/count through the same policy."""
    source_repo = document_repo or services.repo.project_document_read_view(project_id)
    role, identity_error = effective_document_actor_for_request(services, request)
    if identity_error:
        return []
    member = active_project_member_for_request(services, request, project_id, role)
    scope = services.authorized_node_scope(request, project_id)
    return [
        item
        for item in source_repo.project_documents(project_id)
        if services.tenant_id_for_record(item) == services.request_tenant_id(request)
        and document_visible_in_scope(
            services,
            item,
            scope,
            document_repo=source_repo,
        )
        and document_visible_to_actor(services, item, role, member)
    ]


def actor_visible_evidence_repository(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    *,
    document_repo: Any = None,
) -> InMemoryRepository:
    """Build one detached actor-visible evidence state for reuse across nodes."""
    source_repo = document_repo or services.repo.project_document_read_view(project_id)
    visible_documents = visible_project_documents_for_request(
        services,
        request,
        project_id,
        document_repo=source_repo,
    )
    visible_document_ids = {str(item.get("id") or "") for item in visible_documents}
    source_versions = list(source_repo.state.get("versions", []))
    visible_versions = [
        item
        for item in source_versions
        if str(item.get("documentId") or "") in visible_document_ids
    ]
    version_document_ids = {
        str(item.get("id") or ""): str(item.get("documentId") or "")
        for item in source_versions
    }
    role, _ = effective_document_actor_for_request(services, request)
    privileged = str(role or "") in {"admin", "fde", "inspection"}

    def relation_visible(item: dict[str, Any]) -> bool:
        document_id = str(item.get("documentId") or "")
        version_id = str(item.get("documentVersionId") or "")
        version_document_id = version_document_ids.get(version_id, "") if version_id else ""
        if document_id:
            return document_id in visible_document_ids and (
                not version_id or version_document_id == document_id
            )
        if version_id:
            return bool(version_document_id and version_document_id in visible_document_ids)
        return privileged

    detached = InMemoryRepository(seed=False)
    detached.state = {
        key: list(value)
        if isinstance(value, list)
        else dict(value)
        if isinstance(value, dict)
        else value
        for key, value in services.repo.state.items()
    }
    detached.state["documents"] = [
        item
        for item in source_repo.state.get("documents", [])
        if str(item.get("id") or "") in visible_document_ids
    ]
    detached.state["versions"] = visible_versions
    detached.state["bindings"] = [
        item
        for item in source_repo.state.get("bindings", [])
        if relation_visible(item)
    ]
    detached.state["node_evidence_links"] = [
        item
        for item in source_repo.state.get("node_evidence_links", [])
        if relation_visible(item)
    ]
    return detached


def actor_node_evidence_readiness(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    node_id: int,
    *,
    document_repo: Any = None,
    evidence_repo: InMemoryRepository | None = None,
) -> dict[str, Any]:
    detached = evidence_repo or actor_visible_evidence_repository(
        services,
        request,
        project_id,
        document_repo=document_repo,
    )
    return build_node_evidence_readiness(detached, project_id, node_id)


def document_read_error(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    document: dict[str, Any] | None,
) -> JSONResponse | None:
    """Guard one document by project, node scope, and source organization."""
    if not document or document.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    role, identity_error = effective_document_actor_for_request(services, request)
    if identity_error:
        return identity_error
    scope_error = services.member_node_scope_error(
        request,
        project_id,
        role,
        node_ids=services.document_node_ids(
            project_id,
            str(document.get("id") or ""),
        ),
    )
    if scope_error:
        return scope_error
    member = active_project_member_for_request(services, request, project_id, role)
    if not document_visible_to_actor(services, document, role, member):
        return fail(
            errors.FORBIDDEN,
            request,
            message="当前角色无权查看该单位的资料。",
            http_status=403,
        )
    return None


def ndt_source_org_visible_for_request(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    record: dict[str, Any],
) -> bool:
    role, identity_error = effective_document_actor_for_request(services, request)
    if identity_error:
        return False
    if str(role or "") in {"admin", "fde", "inspection"}:
        return True
    if not record.get("sourceOrgId") and not record.get("sourceOrgName"):
        return False
    member = active_project_member_for_request(services, request, project_id, role)
    return document_visible_to_actor(
        services,
        {
            "id": f"NDT-SOURCE-{record.get('id') or ''}",
            "projectId": project_id,
            "sourceOrgId": record.get("sourceOrgId"),
            "sourceOrgName": record.get("sourceOrgName"),
        },
        role,
        member,
    )


def ndt_report_document_visible_for_request(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    report: dict[str, Any],
) -> bool:
    if (
        report.get("projectId") != project_id
        or not services.record_visible_for_request(request, report, project_id)
    ):
        return False
    file_id = str(report.get("fileId") or "")
    if file_id:
        document = services.repo.find_one("documents", file_id)
        return bool(
            document
            and str(document.get("projectId") or "") == project_id
            and services.record_visible_for_request(
                request,
                document,
                project_id,
            )
        )
    return ndt_source_org_visible_for_request(services, request, project_id, report)


def ndt_report_ids_for_film(
    services: DocumentAccessServices,
    project_id: str,
    film_id: str,
) -> set[str]:
    report_ids = {
        str(record.get("reportId"))
        for record in services.repo.state.get("ndt_records", [])
        if record.get("projectId") == project_id
        and record.get("filmId") == film_id
        and record.get("reportId")
    }
    report_ids.update(
        str(report.get("id"))
        for report in services.repo.state.get("ndt_reports", [])
        if report.get("projectId") == project_id
        and film_id in set(report.get("relatedFilmIds") or [])
        and report.get("id")
    )
    return report_ids


def ndt_film_visible_for_request(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    film: dict[str, Any],
) -> bool:
    if (
        film.get("projectId") != project_id
        or not services.record_visible_for_request(request, film, project_id)
    ):
        return False
    report_ids = ndt_report_ids_for_film(
        services,
        project_id,
        str(film.get("id") or ""),
    )
    if not report_ids:
        return ndt_source_org_visible_for_request(services, request, project_id, film)
    reports = [
        services.repo.find_one("ndt_reports", report_id)
        for report_id in sorted(report_ids)
    ]
    return all(
        report
        and ndt_report_document_visible_for_request(
            services,
            request,
            project_id,
            report,
        )
        for report in reports
    )


def ndt_report_visible_for_request(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    report: dict[str, Any],
) -> bool:
    if not ndt_report_document_visible_for_request(
        services,
        request,
        project_id,
        report,
    ):
        return False
    film_ids = {str(item) for item in report.get("relatedFilmIds") or [] if item}
    films = [
        services.repo.find_one("ndt_films", film_id) for film_id in sorted(film_ids)
    ]
    return all(
        film
        and ndt_film_visible_for_request(services, request, project_id, film)
        for film in films
    )


def ndt_record_visible_for_request(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    record: dict[str, Any],
) -> bool:
    if (
        record.get("projectId") != project_id
        or not services.record_visible_for_request(request, record, project_id)
    ):
        return False
    checks: list[bool] = []
    report_id = str(record.get("reportId") or "")
    if report_id:
        report = services.repo.find_one("ndt_reports", report_id)
        checks.append(
            bool(
                report
                and ndt_report_visible_for_request(
                    services,
                    request,
                    project_id,
                    report,
                )
            )
        )
    film_id = str(record.get("filmId") or "")
    if film_id:
        film = services.repo.find_one("ndt_films", film_id)
        checks.append(
            bool(
                film
                and ndt_film_visible_for_request(
                    services,
                    request,
                    project_id,
                    film,
                )
            )
        )
    return (
        all(checks)
        if checks
        else ndt_source_org_visible_for_request(services, request, project_id, record)
    )


def ndt_feedback_visible_for_request(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    feedback: dict[str, Any],
) -> bool:
    if (
        feedback.get("projectId") != project_id
        or not services.record_visible_for_request(request, feedback, project_id)
    ):
        return False
    checks: list[bool] = []
    report_ids = {
        str(item) for item in feedback.get("relatedReportIds") or [] if item
    }
    for report_id in sorted(report_ids):
        report = services.repo.find_one("ndt_reports", report_id)
        checks.append(
            bool(
                report
                and ndt_report_visible_for_request(
                    services,
                    request,
                    project_id,
                    report,
                )
            )
        )
    film_ids = {str(item) for item in feedback.get("relatedFilmIds") or [] if item}
    for film_id in sorted(film_ids):
        film = services.repo.find_one("ndt_films", film_id)
        checks.append(
            bool(
                film
                and ndt_film_visible_for_request(
                    services,
                    request,
                    project_id,
                    film,
                )
            )
        )
    return (
        all(checks)
        if checks
        else ndt_source_org_visible_for_request(services, request, project_id, feedback)
    )


def submission_record_document_ids(
    services: DocumentAccessServices,
    record: dict[str, Any],
) -> set[str]:
    binding_ids = {str(item) for item in record.get("bindingIds") or [] if item}
    document_ids = {str(item) for item in record.get("documentIds") or [] if item}
    document_ids.update(
        str(binding.get("documentId"))
        for binding in services.repo.state.get("bindings", [])
        if str(binding.get("id") or "") in binding_ids and binding.get("documentId")
    )
    report_ids = {str(item) for item in record.get("reportIds") or [] if item}
    document_ids.update(
        str(report.get("fileId"))
        for report in services.repo.state.get("ndt_reports", [])
        if str(report.get("id") or "") in report_ids and report.get("fileId")
    )
    return document_ids


def submission_record_visible_for_request(
    services: DocumentAccessServices,
    request: Request,
    record: dict[str, Any],
) -> bool:
    project_id = str(record.get("projectId") or "")
    if (
        not project_id
        or not services.record_visible_for_request(request, record, project_id)
    ):
        return False
    document_ids = submission_record_document_ids(services, record)
    documents_visible = all(
        (document := services.repo.find_one("documents", document_id)) is not None
        and str(document.get("projectId") or "") == project_id
        and services.record_visible_for_request(request, document, project_id)
        for document_id in document_ids
    )
    if not documents_visible:
        return False
    report_ids = {str(item) for item in record.get("reportIds") or [] if item}
    reports = [
        services.repo.find_one("ndt_reports", report_id)
        for report_id in sorted(report_ids)
    ]
    if not all(
        report
        and ndt_report_visible_for_request(
            services,
            request,
            project_id,
            report,
        )
        for report in reports
    ):
        return False
    film_ids = {str(item) for item in record.get("filmIds") or [] if item}
    films = [
        services.repo.find_one("ndt_films", film_id) for film_id in sorted(film_ids)
    ]
    return all(
        film
        and ndt_film_visible_for_request(services, request, project_id, film)
        for film in films
    )


def submission_snapshot_for_request(
    services: DocumentAccessServices,
    request: Request,
    submission: dict[str, Any],
) -> Any:
    if str(submission.get("submissionType") or "") != "ndt":
        return services.repo.clone(submission.get("snapshot"))
    project_id = str(submission.get("projectId") or "")
    report_ids = {str(item) for item in submission.get("reportIds") or [] if item}
    film_ids = {str(item) for item in submission.get("filmIds") or [] if item}
    reports = [
        services.repo.clone(item)
        for item in services.repo.state.get("ndt_reports", [])
        if str(item.get("id") or "") in report_ids
        and ndt_report_visible_for_request(
            services,
            request,
            project_id,
            item,
        )
    ]
    films = [
        services.repo.clone(item)
        for item in services.repo.state.get("ndt_films", [])
        if str(item.get("id") or "") in film_ids
        and ndt_film_visible_for_request(
            services,
            request,
            project_id,
            item,
        )
    ]
    records = [
        services.repo.clone(item)
        for item in services.repo.state.get("ndt_records", [])
        if (
            str(item.get("reportId") or "") in report_ids
            or str(item.get("filmId") or "") in film_ids
        )
        and ndt_record_visible_for_request(
            services,
            request,
            project_id,
            item,
        )
    ]
    return {"reports": reports, "films": films, "records": records}


def document_mutation_error(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    *,
    document_ids: Iterable[Any] = (),
    binding_ids: Iterable[Any] = (),
) -> JSONResponse | None:
    """Authorize every document reachable from a generic write request."""
    resolved_document_ids = {
        str(item).strip() for item in document_ids if str(item or "").strip()
    }
    for raw_binding_id in binding_ids:
        binding_id = str(raw_binding_id or "").strip()
        if not binding_id:
            continue
        binding = services.repo.find_one("bindings", binding_id)
        if not binding or str(binding.get("projectId") or "") != project_id:
            return fail(errors.NOT_FOUND, request)
        document_id = str(binding.get("documentId") or "").strip()
        if not document_id:
            return fail(errors.NOT_FOUND, request)
        resolved_document_ids.add(document_id)
    for document_id in sorted(resolved_document_ids):
        document = services.repo.find_one("documents", document_id)
        if not document or str(document.get("projectId") or "") != project_id:
            return fail(errors.NOT_FOUND, request)
        access_error = document_read_error(
            services,
            request,
            project_id,
            document,
        )
        if access_error:
            return access_error
    return None


def binding_inputs_mutation_error(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    binding_inputs: Iterable[Any],
) -> JSONResponse | None:
    document_ids: list[str] = []
    for raw_input in binding_inputs:
        if not isinstance(raw_input, dict):
            return fail(errors.VALIDATION_ERROR, request)
        document_id = str(raw_input.get("documentId") or "").strip()
        if not document_id:
            return fail(errors.NOT_FOUND, request)
        document_ids.append(document_id)
        version_id = str(raw_input.get("documentVersionId") or "").strip()
        if version_id:
            version = services.repo.find_one("versions", version_id)
            if not version or str(version.get("documentId") or "") != document_id:
                return fail(errors.NOT_FOUND, request)
    return document_mutation_error(
        services,
        request,
        project_id,
        document_ids=document_ids,
    )


def visible_project_bindings_for_request(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
) -> list[dict[str, Any]]:
    return [
        binding
        for binding in services.repo.bindings_for_project(project_id)
        if binding_relation_visible_for_request(services, request, project_id, binding)
    ]


def binding_relation_visible_for_request(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    binding: dict[str, Any],
    *,
    document_repo: Any = None,
) -> bool:
    source_repo = document_repo or services.repo
    document_id = str(binding.get("documentId") or "").strip()
    document = source_repo.find_one("documents", document_id) if document_id else None
    if not document or str(document.get("projectId") or "") != project_id:
        return False
    version_id = str(binding.get("documentVersionId") or "").strip()
    if version_id:
        version = source_repo.find_one("versions", version_id)
        if not version or str(version.get("documentId") or "") != document_id:
            return False
    role, identity_error = effective_document_actor_for_request(services, request)
    if identity_error:
        return False
    member = active_project_member_for_request(services, request, project_id, role)
    scope = services.authorized_node_scope(request, project_id)
    return bool(
        services.tenant_id_for_record(document) == services.request_tenant_id(request)
        and document_visible_in_scope(services, document, scope, document_repo=source_repo)
        and document_visible_to_actor(services, document, role, member)
    )


def document_version_relation_visible_for_request(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    record: dict[str, Any],
) -> bool:
    document_id = str(record.get("documentId") or "").strip()
    version_id = str(record.get("documentVersionId") or "").strip()
    if version_id:
        version = services.repo.find_one("versions", version_id)
        version_document_id = str((version or {}).get("documentId") or "").strip()
        if not version_document_id or (document_id and version_document_id != document_id):
            return False
        document_id = document_id or version_document_id
    if not document_id:
        return False
    document = services.repo.find_one("documents", document_id)
    return bool(
        document
        and str(document.get("projectId") or "") == project_id
        and record_visible_for_request(services, request, document, project_id)
    )


def rectification_visible_for_request(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    rectification: dict[str, Any],
) -> bool:
    if str(rectification.get("projectId") or "") != project_id or not record_visible_for_request(
        services, request, rectification, project_id
    ):
        return False
    binding_ids = {str(item) for item in rectification.get("bindingIds") or [] if item}
    if binding_ids:
        bindings = [services.repo.find_one("bindings", binding_id) for binding_id in sorted(binding_ids)]
        if not all(
            binding
            and binding_relation_visible_for_request(
                services, request, project_id, binding
            )
            for binding in bindings
        ):
            return False
    submission_id = str(rectification.get("submissionId") or "").strip()
    if submission_id:
        submission = services.repo.find_one("submissions", submission_id, id_field="submissionId")
        if not submission or not submission_record_visible_for_request(services, request, submission):
            return False
    if binding_ids or submission_id:
        return True
    role, _ = effective_document_actor_for_request(services, request)
    return str(role or "") in {"admin", "fde", "inspection"}


def pending_rectification_for_bindings(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    binding_ids: Iterable[Any],
) -> tuple[dict[str, Any] | None, bool]:
    requested_ids = {str(item) for item in binding_ids if item}
    candidates = [
        item
        for item in services.repo.state.get("rectifications", [])
        if item.get("projectId") == project_id
        and item.get("status") == "待反馈"
        and bool(requested_ids & {str(value) for value in item.get("bindingIds") or []})
    ]
    if any(
        not rectification_visible_for_request(services, request, project_id, item)
        for item in candidates
    ):
        return None, True
    return max(
        candidates,
        key=lambda item: str(item.get("returnedAt") or item.get("createdAt") or ""),
        default=None,
    ), False


def enrich_project_tree_for_request(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    groups: list[dict[str, Any]],
    enrich_node: Callable[..., dict[str, Any]],
) -> list[dict[str, Any]]:
    document_repo = services.repo.project_document_read_view(project_id)
    evidence_repo = actor_visible_evidence_repository(
        services, request, project_id, document_repo=document_repo
    )
    project_bindings = visible_project_bindings_for_request(services, request, project_id)
    for group in groups:
        group["nodes"] = [
            enrich_node(
                project_id,
                node,
                project_bindings=project_bindings,
                evidence_readiness=actor_node_evidence_readiness(
                    services,
                    request,
                    project_id,
                    int(node.get("nodeId") or 0),
                    document_repo=document_repo,
                    evidence_repo=evidence_repo,
                ),
                slim=True,
            )
            for node in group.get("nodes", [])
        ]
    return groups


def recompute_visible_project_targeting(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    run_targeting: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    documents = visible_project_documents_for_request(
        services,
        request,
        project_id,
    )
    runs = [
        run_targeting(
            services.repo,
            project_id,
            str(document.get("id") or ""),
            document.get("currentVersionId"),
            triggered_by="manual_api",
        )
        for document in documents
    ]
    return {
        "projectId": project_id,
        "documentCount": len(documents),
        "runCount": len(runs),
        "createdLinkCount": sum(int(run.get("createdLinkCount") or 0) for run in runs),
        "createdBindingCount": sum(int(run.get("createdBindingCount") or 0) for run in runs),
        "runs": runs,
    }


def ndt_related_films_visible_for_request(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    film_ids: Iterable[Any],
) -> bool:
    resolved_ids = {str(item).strip() for item in film_ids if str(item or "").strip()}
    films = [services.repo.find_one("ndt_films", film_id) for film_id in sorted(resolved_ids)]
    return all(
        film
        and ndt_film_visible_for_request(
            services,
            request,
            project_id,
            film,
        )
        for film in films
    )


def ndt_related_films_error(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    film_ids: Iterable[Any],
) -> JSONResponse | None:
    if ndt_related_films_visible_for_request(
        services,
        request,
        project_id,
        film_ids,
    ):
        return None
    return fail(
        errors.FORBIDDEN,
        request,
        message="当前角色无权关联所选无损检测底片。",
        http_status=403,
    )


def submission_body_mutation_error(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    node_ids: list[int],
    body: dict[str, Any],
    *,
    project_level: bool = False,
) -> JSONResponse | None:
    binding_ids = [] if project_level else services.scoped_binding_ids(
        project_id,
        node_ids,
        body.get("bindingIds") or [],
    )
    return document_mutation_error(
        services,
        request,
        project_id,
        document_ids=body.get("documentIds") or [],
        binding_ids=binding_ids,
    )


def ndt_upload_context_error(
    services: DocumentAccessServices,
    request: Request,
    project_id: str,
    session: dict[str, Any],
) -> dict[str, Any] | None:
    film_ids = (session.get("ndtReportContext") or {}).get("relatedFilmIds") or []
    if ndt_related_films_visible_for_request(
        services,
        request,
        project_id,
        film_ids,
    ):
        return None
    return {
        "errorReason": "FORBIDDEN",
        "message": "当前角色无权关联所选无损检测底片。",
    }


def upload_session_requested_node_ids(
    services: DocumentAccessServices,
    project_id: str,
    files: list[dict[str, Any]],
) -> list[int]:
    node_ids: set[int] = set()
    for file in files:
        for raw_node_id in file.get("nodeIds") or []:
            try:
                node_ids.add(int(raw_node_id))
            except (TypeError, ValueError):
                continue
        replacement_id = str(file.get("replaceDocumentId") or "").strip()
        if replacement_id:
            node_ids.update(services.document_node_ids(project_id, replacement_id))
    return sorted(node_ids)
