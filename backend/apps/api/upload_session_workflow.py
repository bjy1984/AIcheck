"""Upload-session aggregate, storage recovery, and completion helpers.

The API route module owns HTTP registration and request-policy composition.  This
module owns the upload aggregate itself.  Callers inject the few route-level
policy callbacks explicitly so authorization and test seams stay visible rather
than being hidden behind a circular import of ``apps.api.routes``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from libs.content_hash import normalized_content_hash
from libs.contracts import errors
from libs.contracts.responses import fail, ok, server_time
from libs.integrations.storage import ObjectStorage


class UploadSessionServices(Protocol):
    """Live composition dependencies supplied by the route module."""

    repo: Any
    task_dispatcher: Any

    def flush_mutation_records(
        self,
        records: dict[str, list[dict[str, Any]]],
        deleted_records: list[Any],
    ) -> None: ...


def upload_session_state_records(
    services: UploadSessionServices,
    session_id: str,
) -> dict[str, list[dict[str, Any]]]:
    """Return every row in the upload aggregate, including superseded versions."""
    repo = services.repo
    session = repo.find_one("upload_sessions", session_id)
    if not session:
        return {}
    document_ids = {
        str(item.get("documentId"))
        for item in session.get("files") or []
        if item.get("documentId")
    }
    version_ids = {
        str(item.get("documentVersionId"))
        for item in session.get("files") or []
        if item.get("documentVersionId")
    }
    knowledge_file_ids = {
        str(item.get("id"))
        for item in repo.state.get("knowledge_files", [])
        if str(item.get("documentId") or "") in document_ids
        or str(item.get("documentVersionId") or "") in version_ids
    }
    return {
        "upload_sessions": [session],
        "documents": [
            item
            for item in repo.state.get("documents", [])
            if str(item.get("id") or "") in document_ids
        ],
        # A replacement changes the prior version's isCurrent flag, so all
        # versions of each affected document belong to the durable aggregate.
        "versions": [
            item
            for item in repo.state.get("versions", [])
            if str(item.get("id") or "") in version_ids
            or str(item.get("documentId") or "") in document_ids
        ],
        "bindings": [
            item
            for item in repo.state.get("bindings", [])
            if str(item.get("documentId") or "") in document_ids
        ],
        "knowledge_files": [
            item
            for item in repo.state.get("knowledge_files", [])
            if str(item.get("id") or "") in knowledge_file_ids
        ],
        "knowledge_tasks": [
            item
            for item in repo.state.get("knowledge_tasks", [])
            if str(item.get("documentId") or "") in document_ids
            or str(item.get("documentVersionId") or "") in version_ids
            or str(item.get("targetId") or "") in knowledge_file_ids
        ],
        "ndt_reports": [
            item
            for item in repo.state.get("ndt_reports", [])
            if str(item.get("fileId") or "") in document_ids
        ],
    }


def validate_upload_session_completion(
    services: UploadSessionServices,
    session: dict[str, Any],
    body: dict[str, Any],
    *,
    object_storage: ObjectStorage | Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Verify every declared upload against the authoritative stored bytes."""
    repo = services.repo
    session_files = [item for item in session.get("files") or [] if isinstance(item, dict)]
    completed_files = [
        item for item in body.get("completedFiles") or [] if isinstance(item, dict)
    ]
    if not session_files:
        return None, {"message": "上传会话中没有待确认文件。", "fields": ["completedFiles"]}

    claims: dict[str, dict[str, Any]] = {}
    duplicate_ids: list[str] = []
    for item in completed_files:
        version_id = str(item.get("documentVersionId") or "").strip()
        if not version_id:
            continue
        if version_id in claims:
            duplicate_ids.append(version_id)
        claims[version_id] = item

    expected_ids = {
        str(item.get("documentVersionId") or "").strip()
        for item in session_files
        if item.get("documentVersionId")
    }
    claimed_ids = set(claims)
    if duplicate_ids or claimed_ids != expected_ids:
        return None, {
            "message": "上传完成清单与上传会话文件不一致。",
            "missingDocumentVersionIds": sorted(expected_ids - claimed_ids),
            "unexpectedDocumentVersionIds": sorted(claimed_ids - expected_ids),
            "duplicateDocumentVersionIds": sorted(set(duplicate_ids)),
        }

    verified: dict[str, Any] = {}
    storage_updates: list[dict[str, Any]] = []
    for file_entry in session_files:
        version_id = str(file_entry.get("documentVersionId") or "")
        claim = claims[version_id]
        try:
            claimed_size = int(claim.get("fileSize") or 0)
        except (TypeError, ValueError):
            claimed_size = 0
        if claimed_size <= 0:
            return None, {
                "message": "上传完成清单缺少有效文件大小。",
                "documentVersionId": version_id,
            }

        actual_size = int(file_entry.get("fileSize") or 0)
        if file_entry.get("status") != "已上传":
            storage_bucket = str(file_entry.get("storageBucket") or "documents")
            storage_key = str(file_entry.get("storageKey") or "")
            metadata = (
                object_storage.object_metadata(storage_bucket, storage_key)
                if storage_key
                else None
            )
            if not metadata or int(metadata.get("size") or 0) <= 0:
                return None, {
                    "message": "文件尚未上传完成，不能完成上传会话。",
                    "documentVersionId": version_id,
                    "status": file_entry.get("status") or "待上传",
                }
            actual_size = int(metadata["size"])
            storage_updates.append(
                {
                    "fileEntry": file_entry,
                    "versionId": version_id,
                    "documentId": str(file_entry.get("documentId") or ""),
                    "storageBucket": storage_bucket,
                    "storageKey": storage_key,
                    "metadata": metadata,
                }
            )

        if actual_size <= 0 or claimed_size != actual_size:
            return None, {
                "message": "上传文件大小与完成清单不一致。",
                "documentVersionId": version_id,
                "claimedFileSize": claimed_size,
                "actualFileSize": actual_size,
            }
        claimed_hash = normalized_content_hash(
            claim.get("contentHash") or claim.get("hash")
        )
        version = repo.find_one("versions", version_id) or {}
        actual_hash = normalized_content_hash(version.get("hash"))
        if claimed_hash and actual_hash and claimed_hash != actual_hash:
            return None, {
                "message": "上传文件哈希与完成清单不一致。",
                "documentVersionId": version_id,
            }
        verified[version_id] = {
            "documentVersionId": version_id,
            "fileSize": actual_size,
            "hash": actual_hash or claimed_hash or None,
        }

    # Direct/external uploads never pass through the API byte stream. Their body
    # hash must therefore come from stored bytes, not from the uploader's claim.
    # Resolve every authoritative hash before mutating any aggregate row so one
    # hashing failure leaves the whole completion retryable and unchanged.
    for update in storage_updates:
        version_id = update["versionId"]
        try:
            storage_hash = object_storage.content_hash(
                update["storageBucket"], update["storageKey"]
            )
        except Exception:  # noqa: BLE001 - surface retryable authoritative failure
            return None, {
                "message": "无法核验对象存储中的文件内容哈希，请稍后重试。",
                "reason": "AUTHORITATIVE_CONTENT_HASH_UNAVAILABLE",
                "retryable": True,
                "documentVersionId": version_id,
            }
        authoritative_hash = str(storage_hash or "").strip()
        if not authoritative_hash:
            return None, {
                "message": "对象存储未返回文件内容哈希，请稍后重试。",
                "reason": "AUTHORITATIVE_CONTENT_HASH_UNAVAILABLE",
                "retryable": True,
                "documentVersionId": version_id,
            }
        claimed_hash = normalized_content_hash(
            claims[version_id].get("contentHash") or claims[version_id].get("hash")
        )
        if claimed_hash and claimed_hash != normalized_content_hash(authoritative_hash):
            return None, {
                "message": "上传文件哈希与对象存储内容不一致。",
                "documentVersionId": version_id,
            }
        update["authoritativeHash"] = authoritative_hash
        verified.setdefault(version_id, {})["hash"] = authoritative_hash

    for update in storage_updates:
        metadata = update["metadata"]
        actual_size = int(metadata["size"])
        version_id = update["versionId"]
        update["fileEntry"].update(
            {
                "status": "已上传",
                "fileSize": actual_size,
                "contentType": metadata.get("contentType"),
                "etag": metadata.get("etag"),
                "uploadedAt": server_time(),
            }
        )
        version = repo.find_one("versions", update["versionId"])
        if version:
            version.update(
                {
                    "fileSize": actual_size,
                    "storageBucket": update["storageBucket"],
                    "storageKey": update["storageKey"],
                    "uploadTime": server_time(),
                }
            )
            version["hash"] = update["authoritativeHash"]
        document = repo.find_one("documents", update["documentId"])
        if document:
            document["fileStatus"] = "已上传"
            document["currentOcrStatus"] = "排队中"
            document["updatedAt"] = server_time()
    return verified, None


def local_review_confidence(
    missing_count: int,
    pending_count: int,
    manual_item_count: int,
) -> float:
    unresolved = max(0, int(missing_count)) + max(0, int(pending_count))
    total = unresolved + max(0, int(manual_item_count))
    if total <= 0:
        return 0.7
    return round(0.35 + 0.35 * (1 - unresolved / total), 2)


def duplicate_documents_in_project(
    services: UploadSessionServices,
    project_id: str,
    files: list[dict[str, Any]],
    *,
    request: Request | None = None,
    record_visible: Callable[[Request, dict[str, Any], str], bool] | None = None,
) -> list[dict[str, Any]]:
    """Report same-project content duplicates without blocking the upload."""
    repo = services.repo
    results: list[dict[str, Any]] = []
    for file in files or []:
        document_id = str(file.get("documentId") or "")
        version = repo.current_version(document_id)
        content_hash = str((version or {}).get("hash") or "").strip()
        if not content_hash:
            continue
        existing = [
            {"documentId": str(item.get("id") or ""), "fileName": item.get("fileName")}
            for item in repo.project_documents(project_id)
            if str(item.get("id") or "") != document_id
            and (
                request is None
                or record_visible is None
                or record_visible(request, item, project_id)
            )
            and str(
                (repo.current_version(str(item.get("id") or "")) or {}).get("hash")
                or ""
            )
            == content_hash
        ]
        if existing:
            results.append(
                {
                    "documentId": document_id,
                    "fileName": file.get("fileName"),
                    "contentHash": content_hash,
                    "existingDocuments": existing,
                    "message": (
                        f"项目内已存在内容相同的资料（{len(existing)} 份），"
                        "可考虑复用而非重复上传。"
                    ),
                }
            )
    return results


def document_body_uploaded(
    services: UploadSessionServices,
    document: dict[str, Any] | None,
    version: dict[str, Any] | None = None,
) -> bool:
    """Accept only a version whose stored body has an authoritative content hash."""
    repo = services.repo
    if not document:
        return False
    checked = version if version is not None else repo.current_version(
        str(document.get("id") or "")
    )
    return bool(checked and checked.get("hash"))


def unuploaded_document_error(
    request: Request,
    documents: list[tuple[dict[str, Any] | None, dict[str, Any] | None]],
    *,
    body_uploaded: Callable[
        [dict[str, Any] | None, dict[str, Any] | None], bool
    ],
) -> JSONResponse | None:
    missing = [
        {
            "documentId": str((document or {}).get("id") or ""),
            "fileName": str((document or {}).get("fileName") or ""),
        }
        for document, version in documents
        if not body_uploaded(document, version)
    ]
    if not missing:
        return None
    names = "、".join(item["fileName"] or item["documentId"] for item in missing[:3])
    return fail(
        errors.CONFLICT,
        request,
        message=f"以下资料尚未上传成功，不能挂载或提交：{names}。请重新上传后再试。",
        data={"reason": "DOCUMENT_BODY_MISSING", "missingDocuments": missing},
    )


def validate_replace_targets(
    services: UploadSessionServices,
    request: Request,
    project_id: str,
    files: list[dict[str, Any]],
    *,
    document_read_error: Callable[
        [Request, str, dict[str, Any]], JSONResponse | None
    ],
) -> JSONResponse | None:
    """Permit direct replacement only for an actor-readable draft/upload."""
    repo = services.repo
    replaceable_status = {"草稿", "已上传"}
    for file in files:
        document_id = str((file or {}).get("replaceDocumentId") or "").strip()
        if not document_id:
            continue
        document = repo.find_one("documents", document_id)
        if not document or str(document.get("projectId") or "") != project_id:
            return fail(
                errors.NOT_FOUND,
                request,
                message="要替换的资料不存在或不属于当前项目。",
                data={"replaceDocumentId": document_id},
            )
        read_error = document_read_error(request, project_id, document)
        if read_error:
            return read_error
        status = str(document.get("fileStatus") or "")
        if status not in replaceable_status:
            return fail(
                errors.CONFLICT,
                request,
                message=f"该资料当前状态为「{status}」，不能直接替换；请通过补正流程处理。",
                data={"replaceDocumentId": document_id, "fileStatus": status},
            )
    return None


def local_upload_artifact_path(
    storage_key: Any,
    *,
    local_storage_path: Callable[[str | None], Path | None],
    document_upload_root: Path,
) -> Path | None:
    path = local_storage_path(str(storage_key or ""))
    if not path:
        return None
    try:
        path.relative_to(document_upload_root.resolve())
    except ValueError:
        return None
    return path


def staged_local_upload_matches(path: Path | None, file_entry: dict[str, Any]) -> bool:
    try:
        if not path or not path.is_file():
            return False
        if path.stat().st_size != int(file_entry.get("stagedFileSize") or 0):
            return False
        expected_hash = str(file_entry.get("stagedContentHash") or "").strip()
        if not expected_hash:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return expected_hash == f"sha256-{digest.hexdigest()}"
    except OSError:
        return False


def reconcile_staged_local_upload(
    services: UploadSessionServices,
    request: Request,
    *,
    project_id: str,
    session_id: str,
    document_version_id: str,
    upload_token: str,
    file_entry: dict[str, Any],
    document_upload_root: Path,
    artifact_path: Callable[[Any], Path | None],
    artifact_matches: Callable[[Path | None, dict[str, Any]], bool],
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """Recover a durably staged local upload under its generation lease."""
    repo = services.repo
    temporary_path = artifact_path(file_entry.get("stagedTemporaryStorageKey"))
    final_path = artifact_path(file_entry.get("stagedStorageKey"))
    expected_directory = (
        document_upload_root / project_id / session_id / document_version_id
    ).resolve()
    for name, path in (("temporary", temporary_path), ("final", final_path)):
        if not path:
            continue
        try:
            path.relative_to(expected_directory)
        except ValueError:
            if name == "temporary":
                temporary_path = None
            else:
                final_path = None
    # Evaluate both snapshots before taking the lease. Tests deliberately pause
    # this boundary to prove a stale claimant cannot delete a winner's body.
    artifact_matches(final_path, file_entry)
    artifact_matches(temporary_path, file_entry)
    expected_staging_id = str(file_entry.get("stagingId") or "")
    claim = repo.claim_upload_session_file_recovery(
        session_id,
        document_version_id,
        expected_staging_id=expected_staging_id,
    )
    if not claim.get("applied"):
        current_file = claim.get("file") if isinstance(claim.get("file"), dict) else None
        current_version = repo.find_one("versions", document_version_id)
        current_body_path = artifact_path((current_version or {}).get("storageKey"))
        if (
            current_file
            and current_file.get("status") == "已上传"
            and str((current_version or {}).get("hash") or "")
            == str(file_entry.get("stagedContentHash") or "")
            and artifact_matches(current_body_path, file_entry)
        ):
            request.state.scoped_flush_records = dict
            return {
                "documentId": current_file.get("documentId"),
                "documentVersionId": document_version_id,
                "storageBucket": current_file.get("storageBucket") or "local",
                "storageKey": current_file.get("storageKey"),
                "fileSize": current_file.get("fileSize"),
                "recovered": True,
                "recoverySource": "concurrent",
            }, None
        request.state.scoped_flush_records = dict
        return None, fail(
            errors.CONFLICT,
            request,
            message="暂存文件正在由其他请求恢复，请稍后重试。",
            data={"reason": "UPLOAD_STAGING_RECOVERY_IN_PROGRESS", "retryable": True},
        )

    recovery_token = str(claim.get("recoveryToken") or "")
    file_entry = claim.get("file") if isinstance(claim.get("file"), dict) else file_entry
    temporary_path = artifact_path(file_entry.get("stagedTemporaryStorageKey"))
    staged_path = artifact_path(file_entry.get("stagedStorageKey"))
    owned_path = artifact_path(file_entry.get("recoveryStorageKey"))
    stale_paths = [
        path
        for item in file_entry.get("staleRecoveryStorageKeys") or []
        if (path := artifact_path(item)) is not None
    ]
    for name, path in (
        ("temporary", temporary_path),
        ("staged", staged_path),
        ("owned", owned_path),
    ):
        if not path:
            continue
        try:
            path.relative_to(expected_directory)
        except ValueError:
            if name == "temporary":
                temporary_path = None
            elif name == "owned":
                owned_path = None
            else:
                staged_path = None
    stale_paths = [
        path
        for path in stale_paths
        if expected_directory == path or expected_directory in path.parents
    ]
    staged_matches = artifact_matches(staged_path, file_entry)
    temporary_matches = artifact_matches(temporary_path, file_entry)
    owned_matches = artifact_matches(owned_path, file_entry)
    stale_source = next(
        (path for path in stale_paths if artifact_matches(path, file_entry)),
        None,
    )
    source_path = (
        owned_path
        if owned_matches
        else staged_path
        if staged_matches
        else temporary_path
        if temporary_matches
        else stale_source
    )
    recovery_source = (
        "owned"
        if source_path == owned_path
        else "promoted"
        if source_path == staged_path
        else "temporary"
        if source_path == temporary_path
        else "takeover"
        if source_path is not None
        else None
    )

    if source_path and owned_path and source_path != owned_path:
        owned_path.parent.mkdir(parents=True, exist_ok=True)
        publish_temp = owned_path.with_name(f".{owned_path.name}.{recovery_token}.publish")
        try:
            shutil.copyfile(source_path, publish_temp)
            os.replace(publish_temp, owned_path)
        except OSError as exc:
            cleanup_required = True
            try:
                publish_temp.unlink(missing_ok=True)
            except OSError:
                cleanup_required = True
            repo.fail_upload_session_file_promotion(
                session_id,
                document_version_id,
                error_code=f"RECOVERY_{exc.__class__.__name__.upper()}",
                cleanup_required=cleanup_required,
                expected_staging_id=expected_staging_id,
                recovery_token=recovery_token,
            )
            request.state.scoped_flush_records = dict
            return None, fail(
                errors.CONFLICT,
                request,
                message="暂存文件恢复失败，请重新上传。",
                data={"reason": "UPLOAD_STAGING_RECOVERY_FAILED", "retryable": True},
            )
    elif not source_path or not owned_path:
        cleanup_required = False
        for artifact in (temporary_path, staged_path, owned_path):
            if artifact:
                try:
                    artifact.unlink(missing_ok=True)
                except OSError:
                    cleanup_required = True
        compensation = repo.fail_upload_session_file_promotion(
            session_id,
            document_version_id,
            error_code="STAGED_ARTIFACT_MISSING_OR_INVALID",
            cleanup_required=cleanup_required,
            expected_staging_id=expected_staging_id,
            recovery_token=recovery_token,
        )
        request.state.scoped_flush_records = dict
        if not compensation.get("applied"):
            return None, fail(
                errors.CONFLICT,
                request,
                message="暂存文件恢复代次已变化，请稍后重试。",
                data={"reason": "UPLOAD_STAGING_GENERATION_CHANGED", "retryable": True},
            )
        if cleanup_required:
            return None, fail(
                errors.CONFLICT,
                request,
                message="暂存文件清理失败，请稍后重试恢复。",
                data={
                    "reason": "UPLOAD_STAGING_CLEANUP_REQUIRED",
                    "retryable": True,
                    "cleanupRequired": True,
                },
            )
        return None, None

    try:
        updated = repo.finalize_upload_session_file_promotion(
            session_id,
            document_version_id,
            project_id=project_id,
            upload_token=upload_token,
            expected_staging_id=expected_staging_id,
            recovery_token=recovery_token,
        )
    except Exception as exc:  # noqa: BLE001 - recovery remains retryable
        current_session = repo.find_one("upload_sessions", session_id)
        current_file = next(
            (
                item
                for item in (current_session or {}).get("files") or []
                if str(item.get("documentVersionId") or "") == document_version_id
            ),
            None,
        )
        current_version = repo.find_one("versions", document_version_id)
        if (
            current_file
            and current_file.get("status") == "已上传"
            and str((current_version or {}).get("hash") or "")
            == str(file_entry.get("stagedContentHash") or "")
            and artifact_matches(owned_path, file_entry)
        ):
            request.state.scoped_flush_records = dict
            return {
                "documentId": current_file.get("documentId"),
                "documentVersionId": document_version_id,
                "storageBucket": current_file.get("storageBucket") or "local",
                "storageKey": current_file.get("storageKey"),
                "fileSize": current_file.get("fileSize"),
                "recovered": True,
                "recoverySource": "concurrent",
            }, None
        ownership = repo.claim_upload_session_file_recovery(
            session_id,
            document_version_id,
            expected_staging_id=expected_staging_id,
            recovery_token=recovery_token,
        )
        if not ownership.get("applied"):
            request.state.scoped_flush_records = dict
            return None, fail(
                errors.CONFLICT,
                request,
                message="暂存文件恢复租约已变化，请稍后重试。",
                data={"reason": "UPLOAD_STAGING_RECOVERY_LEASE_CHANGED", "retryable": True},
            )
        cleanup_required = False
        try:
            if owned_path:
                owned_path.unlink(missing_ok=True)
        except OSError:
            cleanup_required = True
        repo.fail_upload_session_file_promotion(
            session_id,
            document_version_id,
            error_code=f"RECOVERY_{exc.__class__.__name__.upper()}",
            cleanup_required=cleanup_required,
            expected_staging_id=expected_staging_id,
            recovery_token=recovery_token,
        )
        request.state.scoped_flush_records = dict
        return None, fail(
            errors.CONFLICT,
            request,
            message="暂存文件状态恢复失败，请重新上传。",
            data={
                "reason": "UPLOAD_STAGING_FINALIZATION_FAILED",
                "retryable": True,
                "cleanupRequired": cleanup_required,
            },
        )
    if source_path and owned_path and source_path != owned_path:
        try:
            source_path.unlink(missing_ok=True)
        except OSError:
            pass
    request.state.scoped_flush_records = dict
    updated_file = updated["file"]
    return {
        "documentId": updated_file.get("documentId"),
        "documentVersionId": document_version_id,
        "storageBucket": updated_file.get("storageBucket") or "local",
        "storageKey": updated_file.get("storageKey"),
        "fileSize": updated_file.get("fileSize"),
        "recovered": True,
        "recoverySource": recovery_source,
    }, None


async def upload_session_file(
    services: UploadSessionServices,
    request: Request,
    project_id: str,
    session_id: str,
    document_version_id: str,
    x_role: str | None,
    idempotency_key: str | None,
    *,
    mutation_guard: Callable[..., JSONResponse | None],
    reconcile_upload: Callable[..., tuple[dict[str, Any] | None, JSONResponse | None]],
    artifact_matches: Callable[[Path | None, dict[str, Any]], bool],
    safe_file_name: Callable[[str], str],
    idempotent: Callable[..., Any],
    document_upload_root: Path,
    workspace_root: Path,
    max_upload_bytes: int,
) -> Any:
    """Handle one local upload while keeping promotion state crash-recoverable."""
    repo = services.repo
    upload_token = request.headers.get("X-Upload-Session-Token")
    if not upload_token:
        return fail(errors.FORBIDDEN, request, message="上传会话令牌无效，请重新选择文件。")
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    try:
        authoritative_file = repo.validate_upload_session_file_target(
            session_id,
            document_version_id,
            project_id=project_id,
            upload_token=upload_token,
        )
    except ValueError as exc:
        reason = str(exc)
        if reason == "UPLOAD_SESSION_TOKEN_INVALID":
            return fail(
                errors.FORBIDDEN,
                request,
                message="上传会话令牌无效，请重新选择文件。",
            )
        if reason in {"UPLOAD_SESSION_NOT_FOUND", "UPLOAD_SESSION_FILE_NOT_FOUND"}:
            return fail(
                errors.NOT_FOUND,
                request,
                message="未找到上传会话文件，请重新选择文件。",
            )
        return fail(
            errors.CONFLICT,
            request,
            message="上传会话状态已变化，请重新选择文件。",
            data={"reason": reason},
        )
    if authoritative_file.get("status") == "待落盘":
        recovered, recovery_error = reconcile_upload(
            request,
            project_id=project_id,
            session_id=session_id,
            document_version_id=document_version_id,
            upload_token=upload_token,
            file_entry=authoritative_file,
        )
        if recovery_error:
            return recovery_error
        if recovered:
            return ok(recovered, request)
        authoritative_file = repo.validate_upload_session_file_target(
            session_id,
            document_version_id,
            project_id=project_id,
            upload_token=upload_token,
        )
    data = await request.body()
    if not data:
        return fail(errors.VALIDATION_ERROR, request, message="上传文件不能为空。")
    if len(data) > max_upload_bytes:
        return fail(
            errors.FILE_TOO_LARGE,
            request,
            message=f"文件超过 {max_upload_bytes // 1024 // 1024}MB 上传限制。",
        )

    def produce() -> Any:
        file_name = safe_file_name(
            str(authoritative_file.get("fileName") or f"{document_version_id}.bin")
        )
        content_type = str(request.headers.get("content-type") or "application/octet-stream")
        staging_id = uuid4().hex
        target_dir = (
            document_upload_root
            / project_id
            / session_id
            / document_version_id
            / "generations"
            / staging_id
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / file_name
        temporary_path = target_dir / f".{file_name}.{uuid4().hex}.upload"
        temporary_path.write_bytes(data)
        storage_key = f"local://{target_path.relative_to(workspace_root)}"
        try:
            staged = repo.stage_upload_session_file(
                session_id,
                document_version_id,
                storage_bucket="local",
                storage_key=storage_key,
                file_size=len(data),
                content_type=content_type,
                content_hash=f"sha256-{hashlib.sha256(data).hexdigest()}",
                temporary_storage_key=(
                    f"local://{temporary_path.relative_to(workspace_root)}"
                ),
                staging_id=staging_id,
                project_id=project_id,
                upload_token=upload_token,
            )
        except ValueError as exc:
            temporary_path.unlink(missing_ok=True)
            return fail(
                errors.CONFLICT,
                request,
                message="上传会话状态已变化，请重新选择文件。",
                data={"reason": str(exc)},
            )
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
        expected_staging_id = str(staged["file"].get("stagingId") or "")
        try:
            request.state.scoped_flush_records = dict
            os.replace(temporary_path, target_path)
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            repo.fail_upload_session_file_promotion(
                session_id,
                document_version_id,
                error_code=exc.__class__.__name__.upper(),
                expected_staging_id=expected_staging_id,
            )
            return fail(
                errors.CONFLICT,
                request,
                message="文件落盘失败，请重试上传。",
                data={"reason": "UPLOAD_FILE_PROMOTION_FAILED", "retryable": True},
            )
        try:
            updated = repo.finalize_upload_session_file_promotion(
                session_id,
                document_version_id,
                project_id=project_id,
                upload_token=upload_token,
                expected_staging_id=expected_staging_id,
            )
        except Exception as exc:  # noqa: BLE001 - compensate committed staging
            claim = repo.claim_upload_session_file_recovery(
                session_id,
                document_version_id,
                expected_staging_id=expected_staging_id,
            )
            if not claim.get("applied"):
                current_file = (
                    claim.get("file") if isinstance(claim.get("file"), dict) else None
                )
                current_version = repo.find_one("versions", document_version_id)
                if (
                    current_file
                    and current_file.get("status") == "已上传"
                    and current_version
                    and str(current_version.get("hash") or "")
                    == str(staged["file"].get("stagedContentHash") or "")
                    and artifact_matches(target_path, staged["file"])
                ):
                    request.state.scoped_flush_records = dict
                    return ok(
                        {
                            "documentId": current_file.get("documentId"),
                            "documentVersionId": document_version_id,
                            "storageBucket": current_file.get("storageBucket") or "local",
                            "storageKey": current_file.get("storageKey"),
                            "fileSize": current_file.get("fileSize"),
                            "recovered": True,
                            "recoverySource": "concurrent",
                        },
                        request,
                    )
                request.state.scoped_flush_records = dict
                return fail(
                    errors.CONFLICT,
                    request,
                    message="文件正在由其他请求恢复，请稍后重试。",
                    data={"reason": "UPLOAD_FILE_RECOVERY_IN_PROGRESS", "retryable": True},
                )
            recovery_token = str(claim.get("recoveryToken") or "")
            cleanup_required = False
            try:
                target_path.unlink(missing_ok=True)
            except OSError:
                cleanup_required = True
            repo.fail_upload_session_file_promotion(
                session_id,
                document_version_id,
                error_code=(
                    f"{exc.__class__.__name__.upper()}_CLEANUP_REQUIRED"
                    if cleanup_required
                    else exc.__class__.__name__.upper()
                ),
                cleanup_required=cleanup_required,
                expected_staging_id=expected_staging_id,
                recovery_token=recovery_token,
            )
            return fail(
                errors.CONFLICT,
                request,
                message="文件状态确认失败，已回退为可重试状态。",
                data={
                    "reason": "UPLOAD_FILE_FINALIZATION_FAILED",
                    "retryable": True,
                    "cleanupRequired": cleanup_required,
                },
            )
        finally:
            temporary_path.unlink(missing_ok=True)
        updated_file = updated["file"]
        request.state.scoped_flush_records = dict
        return ok(
            {
                "documentId": updated_file.get("documentId"),
                "documentVersionId": document_version_id,
                "storageBucket": "local",
                "storageKey": storage_key,
                "fileSize": len(data),
            },
            request,
        )

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={
            "projectId": project_id,
            "sessionId": session_id,
            "documentVersionId": document_version_id,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    )


def dispatch_completed_upload_files(
    services: UploadSessionServices,
    files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Dispatch durable OCR tasks after the upload aggregate commits."""
    repo = services.repo
    task_dispatcher = services.task_dispatcher
    dispatches: list[dict[str, Any]] = []
    changed_tasks_by_id: dict[str, dict[str, Any]] = {}
    for file in files:
        document_id = str(file.get("documentId") or "")
        version_id = str(file.get("documentVersionId") or "")
        task: dict[str, Any] | None = None
        try:
            task = repo.ocr_task_for(document_id, version_id, file.get("fileName"))
            raw_dispatch = task_dispatcher.dispatch_parse_document(
                file["documentId"],
                file["documentVersionId"],
                file["storageKey"],
                file.get("fileName"),
            )
            deferred = str(raw_dispatch.get("mode") or "") == "disabled"
            outcome = {
                **raw_dispatch,
                "documentId": document_id,
                "documentVersionId": version_id,
                "status": "dispatch_deferred" if deferred else "dispatched",
                "retryable": deferred,
            }
            if task:
                task["dispatchStatus"] = "pending" if deferred else "dispatched"
                task["retryable"] = deferred
                task["lastDispatch"] = repo.clone(outcome)
                task["updatedAt"] = server_time()
        except Exception as exc:  # noqa: BLE001 - completion is already durable
            outcome = {
                "documentId": document_id,
                "documentVersionId": version_id,
                "status": "dispatch_failed",
                "retryable": True,
                "errorCode": exc.__class__.__name__.upper(),
            }
            if task:
                repo.mark_task_failed(task, "OCR 派发失败，可从任务中心重试。")
                task["dispatchStatus"] = "retry_pending"
                task["retryable"] = True
                task["lastDispatch"] = repo.clone(outcome)
        dispatches.append(outcome)
        if task:
            task_key = str(task.get("id") or task.get("documentVersionId") or id(task))
            changed_tasks_by_id[task_key] = task
    if changed_tasks_by_id:
        try:
            services.flush_mutation_records(
                {"knowledge_tasks": list(changed_tasks_by_id.values())}, []
            )
        except Exception:  # noqa: BLE001 - durable task state remains retryable
            for outcome in dispatches:
                outcome["statePersistence"] = "pending"
    return dispatches


def upload_dispatch_processing_status(dispatches: list[dict[str, Any]]) -> str:
    if any(item.get("status") == "dispatch_failed" for item in dispatches):
        return "需重试"
    if any(item.get("status") == "dispatch_deferred" for item in dispatches):
        return "等待派发"
    return "排队中"


def replay_upload_dispatch_outcomes(
    services: UploadSessionServices,
    files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Describe the durable outbox/task state without dispatching it again."""
    outcomes: list[dict[str, Any]] = []
    for file in files:
        document_id = str(file.get("documentId") or "")
        version_id = str(file.get("documentVersionId") or "")
        try:
            task = services.repo.ocr_task_for(
                document_id,
                version_id,
                file.get("fileName"),
            )
            last_dispatch = services.repo.clone((task or {}).get("lastDispatch") or {})
            if last_dispatch.get("status") in {
                "dispatched",
                "dispatch_deferred",
                "dispatch_failed",
            }:
                outcome = last_dispatch
            else:
                outcome = {
                    "documentId": document_id,
                    "documentVersionId": version_id,
                    "status": "dispatch_deferred",
                    "retryable": True,
                }
        except Exception as exc:  # noqa: BLE001 - replay must remain truthful
            outcome = {
                "documentId": document_id,
                "documentVersionId": version_id,
                "status": "dispatch_failed",
                "retryable": True,
                "errorCode": exc.__class__.__name__.upper(),
            }
        outcomes.append(outcome)
    return outcomes


def completed_upload_response(
    services: UploadSessionServices,
    request: Request,
    *,
    project_id: str,
    session_id: str,
    outcome: dict[str, Any],
    dispatch_files: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    duplicate_projection: Callable[..., list[dict[str, Any]]] | None,
    reports_field: str = "ndtReports",
) -> dict[str, Any]:
    """Build a non-raising response after the aggregate is durably committed."""
    files = list(outcome.get("files") or [])
    warnings: list[dict[str, str]] = []
    if outcome.get("replayed"):
        dispatches = replay_upload_dispatch_outcomes(services, files)
    else:
        try:
            dispatches = dispatch_files(files)
        except Exception as exc:  # noqa: BLE001 - commit already succeeded
            dispatches = [
                {
                    "documentId": str(file.get("documentId") or ""),
                    "documentVersionId": str(file.get("documentVersionId") or ""),
                    "status": "dispatch_failed",
                    "retryable": True,
                    "errorCode": exc.__class__.__name__.upper(),
                }
                for file in files
            ]
            warnings.append(
                {
                    "stage": "dispatch",
                    "status": "failed",
                    "errorCode": exc.__class__.__name__.upper(),
                }
            )
    duplicates: list[dict[str, Any]] | None = None
    if duplicate_projection is not None:
        try:
            duplicates = duplicate_projection(project_id, files, request=request)
        except Exception as exc:  # noqa: BLE001 - projection cannot undo commit
            duplicates = []
            warnings.append(
                {
                    "stage": "duplicate_projection",
                    "status": "failed",
                    "errorCode": exc.__class__.__name__.upper(),
                }
            )
    result = dict(outcome.get("mutationResult") or {})
    if not result:
        result = {
            "id": f"MUT-UPLOAD-{session_id}",
            "objectType": "UploadSession",
            "objectId": session_id,
            "nextStatus": "已完成",
            "changed": [],
            "todoDelta": 0,
            "messageDelta": 0,
            "auditLogId": None,
            "affectedIds": [session_id],
        }
    request.state.scoped_flush_records = dict
    response = {
        **result,
        "processingStatus": upload_dispatch_processing_status(dispatches),
        "queuedTasks": dispatches,
        "fileCount": len(files),
        "documents": list(outcome.get("documents") or []),
        reports_field: list(outcome.get("reports") or []),
        "completionWarnings": warnings,
    }
    if duplicates is not None:
        response["duplicates"] = duplicates
    return ok(response, request)


def create_ndt_atomic_drafts_for_completed_session(
    services: UploadSessionServices,
    project_id: str,
    files: list[dict[str, Any]],
    *,
    material_category: str,
    allowed_node_ids: set[int],
    ensure_bindings: Callable[..., tuple[list[str], Any, list[str]]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Create all declared NDT bindings or return a complete validation error."""
    repo = services.repo
    atomic_files = [
        file
        for file in files
        if str(file.get("materialCategory") or "").strip() == material_category
    ]
    prepared: list[tuple[dict[str, Any], str, str, list[int]]] = []
    invalid_atomic_items: list[dict[str, str]] = []
    for file in atomic_files:
        document_id = str(file.get("documentId") or "").strip()
        version_id = str(file.get("documentVersionId") or "").strip()
        document = repo.find_one("documents", document_id) if document_id else None
        version = repo.find_one("versions", version_id) if version_id else None
        if not document_id:
            invalid_atomic_items.append({"documentId": "", "reason": "DOCUMENT_ID_REQUIRED"})
            continue
        if not document or document.get("projectId") != project_id:
            invalid_atomic_items.append(
                {"documentId": document_id, "reason": "DOCUMENT_NOT_FOUND"}
            )
            continue
        if (
            not version_id
            or not version
            or str(version.get("documentId") or "") != document_id
            or str(document.get("currentVersionId") or "") != version_id
        ):
            invalid_atomic_items.append(
                {"documentId": document_id, "reason": "DOCUMENT_VERSION_NOT_CURRENT"}
            )
            continue
        raw_node_ids = file.get("nodeIds")
        try:
            node_ids = (
                sorted({int(node_id) for node_id in raw_node_ids})
                if isinstance(raw_node_ids, list)
                else []
            )
        except (TypeError, ValueError):
            node_ids = []
        if not node_ids or any(node_id not in allowed_node_ids for node_id in node_ids):
            invalid_atomic_items.append(
                {"documentId": document_id, "reason": "INVALID_NODE_IDS"}
            )
            continue
        prepared.append((file, document_id, version_id, node_ids))

    if invalid_atomic_items:
        return [], {
            "message": "无损检测原子资料清单无效，上传会话未完成。",
            "invalidAtomicItems": invalid_atomic_items,
        }

    documents: list[dict[str, Any]] = []
    binding_ids_before = {
        str(item.get("id") or "") for item in repo.state.get("bindings", [])
    }
    for file, document_id, version_id, node_ids in prepared:
        binding_ids, _, invalid_document_ids = ensure_bindings(
            project_id,
            node_ids,
            [document_id],
            usage="证明材料",
        )
        if invalid_document_ids or len(binding_ids) != len(node_ids):
            repo.state["bindings"] = [
                item
                for item in repo.state.get("bindings", [])
                if str(item.get("id") or "") in binding_ids_before
            ]
            return [], {
                "message": "无损检测原子资料挂载不完整，上传会话未完成。",
                "invalidAtomicItems": [
                    {"documentId": document_id, "reason": "BINDING_CREATION_INCOMPLETE"}
                ],
            }
        documents.append(
            {
                "documentId": document_id,
                "documentVersionId": version_id,
                "materialTypeCode": file.get("materialTypeCode"),
                "materialTypeName": file.get("materialTypeName"),
                "nodeIds": node_ids,
                "bindingIds": binding_ids,
            }
        )
    return documents, None


def ndt_atomic_draft_consistency_error(
    services: UploadSessionServices,
    files: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    draft_error: dict[str, Any] | None,
    *,
    material_category: str,
) -> dict[str, Any] | None:
    """Re-read binding rows and reject incomplete or cross-record results."""
    repo = services.repo
    atomic_files = [
        file
        for file in files
        if str(file.get("materialCategory") or "").strip() == material_category
    ]
    expected_document_ids = [
        str(file.get("documentId") or "").strip() for file in atomic_files
    ]
    created_document_ids = [
        str(item.get("documentId") or "").strip() for item in documents
    ]
    invalid_atomic_bindings: list[dict[str, Any]] = []
    for index, document_result in enumerate(documents):
        document_id = str(document_result.get("documentId") or "").strip()
        atomic_file = atomic_files[index] if index < len(atomic_files) else {}
        version_id = str(atomic_file.get("documentVersionId") or "").strip()
        expected_node_ids = {
            int(item)
            for item in atomic_file.get("nodeIds") or []
            if str(item).strip().isdigit()
        }
        returned_node_ids = {
            int(item)
            for item in document_result.get("nodeIds") or []
            if str(item).strip().isdigit()
        }
        returned_binding_ids = [
            str(item).strip()
            for item in document_result.get("bindingIds") or []
            if str(item).strip()
        ]
        actual_by_id = {
            str(item.get("id") or ""): item
            for item in repo.state.get("bindings", [])
            if str(item.get("id") or "") in set(returned_binding_ids)
        }
        missing_binding_ids = sorted(set(returned_binding_ids) - set(actual_by_id))
        document = repo.find_one("documents", document_id)
        expected_project_id = str((document or {}).get("projectId") or "")
        unexpected_binding_ids = sorted(
            binding_id
            for binding_id, binding in actual_by_id.items()
            if str(binding.get("projectId") or "") != expected_project_id
            or str(binding.get("documentId") or "") != document_id
            or str(binding.get("documentVersionId") or "") != version_id
        )
        valid_bindings = [
            binding
            for binding_id, binding in actual_by_id.items()
            if binding_id not in set(unexpected_binding_ids)
        ]
        actual_node_ids = {int(item.get("nodeId") or 0) for item in valid_bindings}
        missing_node_ids = sorted(
            (expected_node_ids - actual_node_ids)
            | (expected_node_ids - returned_node_ids)
        )
        unexpected_node_ids = sorted(
            (actual_node_ids - expected_node_ids)
            | (returned_node_ids - expected_node_ids)
        )
        if (
            missing_binding_ids
            or unexpected_binding_ids
            or missing_node_ids
            or unexpected_node_ids
            or len(returned_binding_ids) != len(expected_node_ids)
            or len(set(returned_binding_ids)) != len(returned_binding_ids)
        ):
            invalid_atomic_bindings.append(
                {
                    "documentId": document_id,
                    "missingBindingIds": missing_binding_ids,
                    "unexpectedBindingIds": unexpected_binding_ids,
                    "missingNodeIds": missing_node_ids,
                    "unexpectedNodeIds": unexpected_node_ids,
                }
            )
    if (
        draft_error is None
        and expected_document_ids == created_document_ids
        and not invalid_atomic_bindings
    ):
        return None
    result = dict(draft_error or {})
    result.setdefault(
        "message",
        "无损检测原子资料挂载结果与上传清单不一致，上传会话未完成。",
    )
    result.update(
        {
            "expectedAtomicDocumentIds": expected_document_ids,
            "createdAtomicDocumentIds": created_document_ids,
            "missingAtomicDocumentIds": sorted(
                set(expected_document_ids) - set(created_document_ids)
            ),
            "unexpectedAtomicDocumentIds": sorted(
                set(created_document_ids) - set(expected_document_ids)
            ),
            "invalidAtomicBindings": invalid_atomic_bindings,
        }
    )
    return result


def create_ndt_reports_for_completed_session(
    services: UploadSessionServices,
    project_id: str,
    session: dict[str, Any] | None,
    files: list[dict[str, Any]],
    *,
    metadata_fields: list[str],
) -> list[dict[str, Any]]:
    repo = services.repo
    context = (session or {}).get("ndtReportContext") or {}
    if context.get("kind") != "report":
        return []
    created: list[dict[str, Any]] = []
    for file in files:
        document = repo.find_one("documents", str(file.get("documentId") or ""))
        if not document:
            continue
        existing = next(
            (
                report
                for report in repo.state.get("ndt_reports", [])
                if report.get("fileId") == document["id"]
            ),
            None,
        )
        if existing:
            created.append(repo.clone(existing))
            continue
        file_name = document.get("fileName") or file.get("fileName") or "RT检测报告.pdf"
        report_no = context.get("reportNo") or Path(str(file_name)).stem
        method = context.get("method") or (
            "UT" if "UT" in str(file_name).upper() else "RT"
        )
        report = {
            "id": f"NDT-RPT-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "nodeId": int(context.get("nodeId") or document.get("nodeId") or 40),
            "reportNo": report_no,
            "method": method,
            "fileId": document["id"],
            "relatedFilmIds": context.get("relatedFilmIds") or [],
            "status": "待提交",
            "uploadedAt": server_time(),
            "actions": ["ndt:submit"],
        }
        report.update(
            {
                field: context.get(field)
                for field in metadata_fields
                if context.get(field) is not None
            }
        )
        repo.state["ndt_reports"].insert(0, report)
        created.append(repo.clone(report))
    return created


def complete_upload_session_aggregate_transaction(
    services: UploadSessionServices,
    project_id: str,
    session_id: str,
    body: dict[str, Any],
    *,
    validate_completion: Callable[
        [dict[str, Any], dict[str, Any]],
        tuple[dict[str, Any] | None, dict[str, Any] | None],
    ],
    create_atomic_drafts: Callable[
        [str, list[dict[str, Any]]],
        tuple[list[dict[str, Any]], dict[str, Any] | None],
    ],
    atomic_consistency_error: Callable[
        [list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None],
        dict[str, Any] | None,
    ],
    create_ndt_reports: Callable[
        [str, dict[str, Any] | None, list[dict[str, Any]]],
        list[dict[str, Any]],
    ],
) -> dict[str, Any]:
    """Validate, bind, complete, and persist one upload aggregate atomically."""

    repo = services.repo

    def mutate(session: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
        if not session or session.get("projectId") != project_id:
            return {"errorReason": "NOT_FOUND", "message": "未找到上传会话。"}, False
        if session.get("status") != "待上传":
            return {
                "errorReason": "CONFLICT",
                "message": "上传会话已完成或状态已变化。",
                "data": {"sessionStatus": session.get("status")},
            }, False
        _, completion_error = validate_completion(session, body)
        if completion_error:
            return {
                "errorReason": "VALIDATION_ERROR",
                "message": str(completion_error.pop("message")),
                "data": completion_error,
            }, False
        missing_body_hashes = repo.upload_session_missing_body_hashes(session_id)
        if missing_body_hashes:
            return {
                "errorReason": "VALIDATION_ERROR",
                "message": "上传会话仍有文件缺少已存储的内容哈希。",
                "data": {"missingDocumentVersionIds": missing_body_hashes},
            }, False
        files = repo.upload_session_files(session_id)
        documents, draft_error = create_atomic_drafts(project_id, files)
        consistency_error = atomic_consistency_error(files, documents, draft_error)
        if consistency_error:
            return {
                "errorReason": "VALIDATION_ERROR",
                "message": str(consistency_error.pop("message")),
                "data": consistency_error,
            }, False
        dispatch_task_ids: list[str] = []
        for file in files:
            task = repo.ocr_task_for(
                str(file.get("documentId") or ""),
                str(file.get("documentVersionId") or ""),
                file.get("fileName"),
            )
            if not task:
                knowledge_file = repo.knowledge_file_for_version(
                    str(file.get("documentVersionId") or "")
                )
                task = repo.upsert_knowledge_task(
                    task_type="ocr",
                    target_id=str(
                        (knowledge_file or {}).get("id")
                        or f"KF-{file.get('documentId')}"
                    ),
                    target_name=str(file.get("fileName") or "待识别文件"),
                    document_id=str(file.get("documentId") or ""),
                    version_id=str(file.get("documentVersionId") or ""),
                    status="排队中",
                    progress=0,
                )
            task["documentId"] = str(file.get("documentId") or "")
            task["documentVersionId"] = str(file.get("documentVersionId") or "")
            task["status"] = "排队中"
            task["dispatchStatus"] = "pending"
            task["retryable"] = True
            task["lastDispatch"] = {
                "documentId": file.get("documentId"),
                "documentVersionId": file.get("documentVersionId"),
                "status": "pending",
                "retryable": True,
            }
            task["updatedAt"] = server_time()
            task["revision"] = int(task.get("revision") or 1) + 1
            dispatch_task_ids.append(str(task.get("id") or ""))
        reports = create_ndt_reports(project_id, session, files)
        completed_files = repo.complete_upload_session(session_id)
        completion_result = {
            "files": completed_files,
            "documents": documents,
            "reports": reports,
            "dispatchTaskIds": dispatch_task_ids,
            "mutationResult": {
                "id": f"MUT-UPLOAD-{session_id}",
                "objectType": "UploadSession",
                "objectId": session_id,
                "nextStatus": "已完成",
                "changed": [],
                "todoDelta": 0,
                "messageDelta": 0,
                "auditLogId": None,
                "affectedIds": [session_id],
            },
            "replayed": False,
        }
        completed_session = repo.find_one("upload_sessions", session_id)
        if completed_session is not None:
            completed_session["completionResult"] = repo.clone(completion_result)
        return completion_result, True

    return repo.mutate_upload_session_atomically(session_id, mutate)


def upload_session_transaction_error_response(
    request: Request,
    outcome: dict[str, Any],
) -> JSONResponse | None:
    reason = str(outcome.get("errorReason") or "")
    if not reason:
        return None
    error = {
        "NOT_FOUND": errors.NOT_FOUND,
        "CONFLICT": errors.CONFLICT,
        "VALIDATION_ERROR": errors.VALIDATION_ERROR,
    }.get(reason, errors.VALIDATION_ERROR)
    return fail(
        error,
        request,
        message=str(outcome.get("message") or error.message),
        data=outcome.get("data") if isinstance(outcome.get("data"), dict) else None,
    )


def upload_session_completion_error(
    services: UploadSessionServices,
    request: Request,
    project_id: str,
    session: dict[str, Any] | None,
    *,
    tenant_id_for_record: Callable[[dict[str, Any]], str],
    request_tenant_id: Callable[[Request], str],
    effective_document_actor: Callable[
        [Request], tuple[str | None, JSONResponse | None]
    ],
    active_project_member: Callable[
        [Request, str, str | None], dict[str, Any] | None
    ],
    request_user_id: Callable[[Request], str | None],
    document_read_error: Callable[
        [Request, str, dict[str, Any]], JSONResponse | None
    ],
) -> JSONResponse | None:
    """Authorize every session document before entering the CAS transaction."""
    repo = services.repo
    if (
        not session
        or session.get("projectId") != project_id
        or tenant_id_for_record(session) != request_tenant_id(request)
    ):
        return fail(errors.NOT_FOUND, request)
    role, identity_error = effective_document_actor(request)
    if identity_error:
        return identity_error
    member = active_project_member(request, project_id, role)
    creator_org_id = str(session.get("creatorOrgId") or "").strip()
    creator_user_id = str(session.get("creatorUserId") or "").strip()
    if str(role or "") in {"contractor", "ndt"}:
        member_org_id = str((member or {}).get("orgId") or "").strip()
        if creator_org_id and (not member_org_id or member_org_id != creator_org_id):
            return fail(
                errors.FORBIDDEN,
                request,
                message="当前角色无权完成该上传会话。",
                http_status=403,
            )
        if (
            not creator_org_id
            and creator_user_id
            and request_user_id(request) != creator_user_id
        ):
            return fail(
                errors.FORBIDDEN,
                request,
                message="当前角色无权完成该上传会话。",
                http_status=403,
            )
    for file_entry in session.get("files") or []:
        document_id = str(file_entry.get("documentId") or "").strip()
        document = repo.find_one("documents", document_id) if document_id else None
        if not document or document.get("projectId") != project_id:
            return fail(
                errors.VALIDATION_ERROR,
                request,
                message="上传会话引用的文件记录不存在或已失效。",
                data={
                    "invalidAtomicItems": [
                        {"documentId": document_id, "reason": "DOCUMENT_NOT_FOUND"}
                    ]
                },
            )
        document_org_id = str(document.get("sourceOrgId") or "").strip()
        if creator_org_id and document_org_id and document_org_id != creator_org_id:
            return fail(
                errors.FORBIDDEN,
                request,
                message="当前角色无权完成该上传会话。",
                http_status=403,
            )
        read_error = document_read_error(request, project_id, document)
        if read_error:
            return read_error
    return None
