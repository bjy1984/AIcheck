"""Read an explicitly selected version without current-version or filename fallback."""
from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath

from fastapi.responses import FileResponse

from libs.contracts import errors
from libs.contracts.responses import fail


def selected_version_original(api, request, project_id, document_id, version_id, disposition):
    document = api.repo.find_one("documents", document_id)
    if error := api.document_read_error(request, project_id, document):
        return error
    version = api.repo.find_one("versions", version_id)
    if (not version or version.get("documentId") != document_id
            or api.tenant_id_for_record(version) != api.request_tenant_id(request)):
        return fail(errors.NOT_FOUND, request, message="未找到可访问的文档版本。")
    storage_key = str(version.get("storageKey") or "")
    file_name = str(version.get("fileName") or PurePosixPath(storage_key).name or document.get("fileName") or f"{version_id}.bin")
    file_type = str(version.get("fileType") or "")
    content_type = file_type if "/" in file_type else mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    local_path = api.local_storage_path(storage_key)
    if local_path and local_path.is_file():
        if disposition == "inline":
            rendered = api.project_document_render_inline_original(local_path, file_name)
            if rendered is not None:
                return rendered
        return FileResponse(local_path, media_type=content_type, filename=file_name,
                            content_disposition_type="attachment" if disposition == "attachment" else "inline")
    storage_object = api.project_document_storage_object(version)
    if storage_object:
        streamed = api.stream_object_storage_file(*storage_object, content_type=content_type,
                                                 file_name=file_name, disposition=disposition)
        if streamed is not None:
            return streamed
    return fail(errors.NOT_FOUND, request, message="所选版本的原文不可用，请重新上传或联系资料管理员。")
