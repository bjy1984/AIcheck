#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SCHEMA_VERSION = "aicheck-data-migration-v1"
EXPECTED_DATABASES = frozenset({"aicheck", "litellm", "workflow"})
EXPECTED_BUCKETS = frozenset({"documents", "previews", "exports", "ocr-artifacts"})


class BundleValidationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise BundleValidationError(f"bundle file path must be a safe relative path: {value!r}")
    return path


def validate_manifest(manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise BundleValidationError("unsupported manifest schemaVersion")
    migration_id = manifest.get("migrationId")
    if not isinstance(migration_id, str) or not migration_id.strip():
        raise BundleValidationError("manifest migrationId is required")
    if set(manifest.get("databases", [])) != EXPECTED_DATABASES:
        raise BundleValidationError("manifest databases must match the required inventory")
    if set(manifest.get("buckets", [])) != EXPECTED_BUCKETS:
        raise BundleValidationError("manifest buckets must match the required inventory")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise BundleValidationError("manifest files inventory is required")
    resolved_root = root.resolve()
    for relative_name, metadata in files.items():
        if not isinstance(relative_name, str) or not isinstance(metadata, dict):
            raise BundleValidationError("invalid manifest files entry")
        relative_path = _safe_relative_path(relative_name)
        path = root.joinpath(*relative_path.parts)
        try:
            path.resolve().relative_to(resolved_root)
        except ValueError as exc:
            raise BundleValidationError(f"bundle file path must be relative: {relative_name!r}") from exc
        if not path.is_file():
            raise BundleValidationError(f"bundle file is missing: {relative_name}")
        if path.stat().st_size != metadata.get("size"):
            raise BundleValidationError(f"bundle file size differs: {relative_name}")
        if sha256_file(path) != metadata.get("sha256"):
            raise BundleValidationError(f"bundle file SHA-256 differs: {relative_name}")
    return manifest


def safe_user_roles(roles: Iterable[str], *, bootstrap_role: str) -> list[str]:
    preserved = {"postgres", bootstrap_role}
    return sorted(role for role in roles if role not in preserved and not role.startswith("pg_"))


def require_destructive_confirmation(
    *, manifest_id: str, requested_id: str, confirmed: bool
) -> None:
    if manifest_id != requested_id:
        raise BundleValidationError("requested migration ID does not match the bundle")
    if not confirmed:
        raise BundleValidationError("destructive restore requires --confirm-replace")
