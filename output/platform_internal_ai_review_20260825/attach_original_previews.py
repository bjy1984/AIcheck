from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


MAIN_ROOT = Path("/Volumes/7up/github/knowledgetools")
WORKTREE = MAIN_ROOT / ".worktrees" / "qwen-auto-gold-classification"
BACKEND = WORKTREE / "backend"
OUTPUT = MAIN_ROOT / "output" / "platform_internal_ai_review_20260825"
PROJECT_ROOTS = {
    "P-TEST-OCR-001": MAIN_ROOT / "test",
    "P-TEST-OCR-002": MAIN_ROOT / "test2",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    load_dotenv(MAIN_ROOT / "backend" / ".env", override=True)
    sys.path.insert(0, str(BACKEND))
    import psycopg

    from libs.integrations.storage import object_storage

    dsn = os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("database_url_not_configured")
    object_storage.ensure_buckets()
    uploaded: list[dict[str, Any]] = []
    with psycopg.connect(dsn, autocommit=False) as connection:
        rows = connection.execute(
            """
            SELECT object_id, payload
            FROM aicheck_state
            WHERE tenant_id = 'TENANT-DEFAULT'
              AND collection = 'documents'
              AND payload->>'projectId' = ANY(%s)
            ORDER BY payload->>'projectId', object_id
            """,
            (list(PROJECT_ROOTS),),
        ).fetchall()
        if len(rows) != 43:
            raise RuntimeError(f"expected_43_documents_found_{len(rows)}")
        for document_id, document in rows:
            project_id = str(document.get("projectId") or "")
            relative_path = str(document.get("relativePath") or "")
            project_root = PROJECT_ROOTS[project_id].resolve()
            source = (project_root / relative_path).resolve()
            try:
                source.relative_to(project_root)
            except ValueError as exc:
                raise RuntimeError(f"source_path_outside_project:{relative_path}") from exc
            if not source.is_file():
                raise RuntimeError(f"source_file_missing:{source}")
            version_id = str(document.get("currentVersionId") or "")
            version_row = connection.execute(
                """
                SELECT payload FROM aicheck_state
                WHERE tenant_id = 'TENANT-DEFAULT'
                  AND collection = 'document_versions'
                  AND object_id = %s
                """,
                (version_id,),
            ).fetchone()
            if not version_row:
                raise RuntimeError(f"document_version_missing:{version_id}")
            version = dict(version_row[0])
            data = source.read_bytes()
            sha = digest(data)
            object_name = f"test-project-originals/{project_id}/{document_id}/{source.name}"
            content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
            storage_url = object_storage.put_bytes(
                "documents", object_name, data, content_type=content_type
            )
            if not storage_url:
                raise RuntimeError(f"object_storage_upload_failed:{document_id}")
            stored = object_storage.get_bytes("documents", object_name)
            if stored != data or digest(stored) != sha:
                raise RuntimeError(f"object_storage_roundtrip_mismatch:{document_id}")
            metadata = object_storage.object_metadata("documents", object_name) or {}
            version.update(
                {
                    "storageBucket": "documents",
                    "storageKey": storage_url,
                    "hash": f"sha256-{sha}",
                    "fileSize": len(data),
                    "contentType": content_type,
                    "storageEtag": metadata.get("etag"),
                    "originalObjectAttached": True,
                    "originalObjectAttachedAt": "2026-08-25 12:00:00",
                    "sourceBusinessDataImmutable": True,
                }
            )
            connection.execute(
                """
                UPDATE aicheck_state
                SET payload = %s::jsonb, updated_at = now()
                WHERE tenant_id = 'TENANT-DEFAULT'
                  AND collection = 'document_versions'
                  AND object_id = %s
                """,
                (json.dumps(version, ensure_ascii=False), version_id),
            )
            uploaded.append(
                {
                    "projectId": project_id,
                    "documentId": document_id,
                    "documentVersionId": version_id,
                    "fileName": document.get("fileName"),
                    "relativePath": relative_path,
                    "contentType": content_type,
                    "fileSize": len(data),
                    "sha256": sha,
                    "storageKey": storage_url,
                    "storageRoundtripVerified": True,
                }
            )
        connection.commit()

    receipt = {
        "schemaVersion": "test-project-original-preview-attachment@1",
        "attachedAt": datetime.now().isoformat(),
        "database": "aicheck/public/TENANT-DEFAULT",
        "objectStorage": "MinIO/documents",
        "documentCount": len(uploaded),
        "projectCounts": {
            project_id: sum(1 for item in uploaded if item["projectId"] == project_id)
            for project_id in PROJECT_ROOTS
        },
        "sourceBusinessDataImmutable": True,
        "storageRoundtripVerifiedCount": sum(
            1 for item in uploaded if item["storageRoundtripVerified"]
        ),
        "backup": {
            "path": str(OUTPUT / "aicheck-before-preview-fix.dump"),
            "sha256": "fd59b74654a9ce63f15061ef36fefb2bdf6243648a1d86f0c4799853a7e3dd93",
        },
        "documents": uploaded,
    }
    (OUTPUT / "original_preview_attachment_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "documentCount": receipt["documentCount"],
                "projectCounts": receipt["projectCounts"],
                "storageRoundtripVerifiedCount": receipt[
                    "storageRoundtripVerifiedCount"
                ],
                "receipt": str(OUTPUT / "original_preview_attachment_receipt.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
