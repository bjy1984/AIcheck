from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.data_migration import (
    BundleValidationError,
    require_destructive_confirmation,
    safe_user_roles,
    sha256_file,
    validate_manifest,
)


def valid_manifest(root: Path) -> dict[str, object]:
    payload = root / "databases" / "aicheck.dump"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"postgres-dump")
    return {
        "schemaVersion": "aicheck-data-migration-v1",
        "migrationId": "migration-20260812T120000Z",
        "databases": ["aicheck", "litellm", "workflow"],
        "buckets": ["documents", "previews", "exports", "ocr-artifacts"],
        "files": {
            "databases/aicheck.dump": {
                "size": 13,
                "sha256": "sha256:" + hashlib.sha256(b"postgres-dump").hexdigest(),
            }
        },
    }


def test_validate_manifest_accepts_exact_inventory_and_real_file_digest(tmp_path: Path) -> None:
    manifest = valid_manifest(tmp_path)

    validated = validate_manifest(manifest, tmp_path)

    assert validated["migrationId"] == "migration-20260812T120000Z"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("databases", ["aicheck", "workflow"]),
        ("databases", ["aicheck", "litellm", "workflow", "other"]),
        ("buckets", ["documents", "previews", "exports"]),
        ("buckets", ["documents", "previews", "exports", "ocr-artifacts", "other"]),
    ],
)
def test_validate_manifest_rejects_incomplete_or_extra_inventory(
    tmp_path: Path, field: str, value: list[str]
) -> None:
    manifest = valid_manifest(tmp_path)
    manifest[field] = value

    with pytest.raises(BundleValidationError, match=field):
        validate_manifest(manifest, tmp_path)


def test_validate_manifest_rejects_changed_payload(tmp_path: Path) -> None:
    manifest = valid_manifest(tmp_path)
    (tmp_path / "databases" / "aicheck.dump").write_bytes(b"changed")

    with pytest.raises(BundleValidationError, match="size|SHA-256"):
        validate_manifest(manifest, tmp_path)


def test_validate_manifest_rejects_path_escape(tmp_path: Path) -> None:
    manifest = valid_manifest(tmp_path)
    manifest["files"] = {
        "../outside.dump": {
            "size": 0,
            "sha256": "sha256:" + hashlib.sha256(b"").hexdigest(),
        }
    }

    with pytest.raises(BundleValidationError, match="relative"):
        validate_manifest(manifest, tmp_path)


def test_safe_user_roles_preserves_postgres_builtin_and_bootstrap_roles() -> None:
    roles = ["postgres", "pg_monitor", "restore_admin", "aicheck", "litellm", "temporary"]

    assert safe_user_roles(roles, bootstrap_role="restore_admin") == [
        "aicheck",
        "litellm",
        "temporary",
    ]


def test_destructive_restore_requires_matching_id_and_explicit_confirmation() -> None:
    require_destructive_confirmation(
        manifest_id="migration-20260812T120000Z",
        requested_id="migration-20260812T120000Z",
        confirmed=True,
    )

    with pytest.raises(BundleValidationError, match="--confirm-replace"):
        require_destructive_confirmation(
            manifest_id="migration-20260812T120000Z",
            requested_id="migration-20260812T120000Z",
            confirmed=False,
        )
    with pytest.raises(BundleValidationError, match="migration ID"):
        require_destructive_confirmation(
            manifest_id="migration-20260812T120000Z",
            requested_id="different",
            confirmed=True,
        )


def test_sha256_file_streams_real_file(tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"abc" * 4096)

    assert sha256_file(payload) == "sha256:" + hashlib.sha256(b"abc" * 4096).hexdigest()


def test_manifest_fixture_is_json_serializable(tmp_path: Path) -> None:
    json.dumps(valid_manifest(tmp_path))
