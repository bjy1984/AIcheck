#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable


SCHEMA_VERSION = "aicheck-data-migration-v1"
EXPECTED_DATABASES = frozenset({"aicheck", "litellm", "workflow"})
EXPECTED_BUCKETS = frozenset({"documents", "previews", "exports", "ocr-artifacts"})
DATABASE_ORDER = ("aicheck", "litellm", "workflow")
BUCKET_ORDER = ("documents", "previews", "exports", "ocr-artifacts")
LOCAL_FILE_ROOTS = (
    "output/document_uploads",
    "output/knowledge_uploads",
    "rules",
)


class BundleValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ExportConfig:
    migration_id: str
    source_root: Path
    output_root: Path
    git_commit: str
    pg_bin: Path = Path("/opt/homebrew/opt/postgresql@16/bin")
    pg_host: str | None = None
    pg_port: int | None = None
    pg_user: str | None = None


@dataclass(frozen=True)
class ExportResult:
    bundle_root: Path
    archive: Path
    checksum_file: Path


@dataclass(frozen=True)
class UploadConfig:
    migration_id: str
    archive: Path
    checksum_file: Path
    ssh_host: str = "dev-bjy"
    remote_root: str = "/home/dev-bjy/aicheck-migrations"


CommandRunner = Callable[..., str]


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


def run_command(command: list[str], *, output: Path | None = None) -> str:
    if output is None:
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as target:
        subprocess.run(command, stdout=target, stderr=subprocess.PIPE, check=True)
    return ""


def _postgres_connection_args(config: ExportConfig) -> list[str]:
    arguments: list[str] = []
    if config.pg_host:
        arguments.extend(["--host", config.pg_host])
    if config.pg_port:
        arguments.extend(["--port", str(config.pg_port)])
    if config.pg_user:
        arguments.extend(["--username", config.pg_user])
    return arguments


def _copy_required_file_roots(config: ExportConfig, bundle_root: Path) -> None:
    destination_root = bundle_root / "files"
    for relative in LOCAL_FILE_ROOTS:
        source = config.source_root / relative
        if not source.is_dir():
            raise BundleValidationError(f"required local file root is missing: {source}")
        destination = destination_root / relative
        shutil.copytree(source, destination, copy_function=shutil.copy2)


def _payload_inventory(bundle_root: Path) -> dict[str, dict[str, int | str]]:
    inventory: dict[str, dict[str, int | str]] = {}
    for path in sorted(bundle_root.rglob("*")):
        if not path.is_file() or path.name in {"manifest.json", "READY"}:
            continue
        relative = path.relative_to(bundle_root).as_posix()
        inventory[relative] = {"size": path.stat().st_size, "sha256": sha256_file(path)}
    return inventory


def export_bundle(
    config: ExportConfig,
    *,
    runner: CommandRunner = run_command,
) -> ExportResult:
    if not config.migration_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in config.migration_id):
        raise BundleValidationError("migration ID may contain only letters, numbers, dash, and underscore")
    bundle_root = config.output_root / config.migration_id
    archive = config.output_root / f"{config.migration_id}.tar.gz"
    checksum_file = config.output_root / f"{config.migration_id}.tar.gz.sha256"
    if bundle_root.exists() or archive.exists() or checksum_file.exists():
        raise BundleValidationError(f"migration output already exists: {config.migration_id}")
    bundle_root.mkdir(parents=True)
    try:
        connection_args = _postgres_connection_args(config)
        runner(
            [str(config.pg_bin / "pg_dumpall"), *connection_args, "--globals-only"],
            output=bundle_root / "globals.sql",
        )
        database_root = bundle_root / "databases"
        database_root.mkdir()
        for database in DATABASE_ORDER:
            runner(
                [
                    str(config.pg_bin / "pg_dump"),
                    *connection_args,
                    "--format=custom",
                    "--compress=6",
                    f"--file={database_root / f'{database}.dump'}",
                    database,
                ]
            )
        _copy_required_file_roots(config, bundle_root)
        manifest: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "migrationId": config.migration_id,
            "gitCommit": config.git_commit,
            "databases": list(DATABASE_ORDER),
            "buckets": list(BUCKET_ORDER),
            "sourceStorageMode": "local_filesystem",
            "localFileRoots": list(LOCAL_FILE_ROOTS),
            "files": _payload_inventory(bundle_root),
        }
        (bundle_root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        validate_manifest(manifest, bundle_root)
        (bundle_root / "READY").write_text(config.migration_id + "\n", encoding="utf-8")
        config.output_root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "w:gz", compresslevel=1) as target:
            target.add(bundle_root, arcname=config.migration_id)
        checksum = sha256_file(archive).removeprefix("sha256:")
        checksum_file.write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
        return ExportResult(bundle_root=bundle_root, archive=archive, checksum_file=checksum_file)
    except Exception:
        archive.unlink(missing_ok=True)
        checksum_file.unlink(missing_ok=True)
        raise


def upload_bundle(
    config: UploadConfig,
    *,
    runner: CommandRunner = run_command,
) -> str:
    if not config.archive.is_file() or not config.checksum_file.is_file():
        raise BundleValidationError("archive and checksum file are required")
    expected_archive_name = f"{config.migration_id}.tar.gz"
    if config.archive.name != expected_archive_name:
        raise BundleValidationError("archive name does not match migration ID")
    expected_checksum = sha256_file(config.archive).removeprefix("sha256:")
    checksum_fields = config.checksum_file.read_text(encoding="utf-8").strip().split()
    if len(checksum_fields) != 2 or checksum_fields != [expected_checksum, expected_archive_name]:
        raise BundleValidationError("local archive checksum file does not match archive")
    remote_dir = f"{config.remote_root.rstrip('/')}/{config.migration_id}"
    quoted_dir = shlex.quote(remote_dir)
    runner(["ssh", config.ssh_host, f"mkdir -p -- {quoted_dir}"])
    runner(
        [
            "scp",
            str(config.archive),
            str(config.checksum_file),
            f"{config.ssh_host}:{remote_dir}/",
        ]
    )
    runner(
        [
            "ssh",
            config.ssh_host,
            f"cd {quoted_dir} && sha256sum -c {shlex.quote(config.checksum_file.name)}",
        ]
    )
    return remote_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Build, validate, and upload AIcheck data migration bundles.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--migration-id", required=True)
    export_parser.add_argument("--source-root", type=Path, required=True)
    export_parser.add_argument("--output-root", type=Path, required=True)
    export_parser.add_argument("--git-commit", required=True)
    export_parser.add_argument("--pg-bin", type=Path, default=Path("/opt/homebrew/opt/postgresql@16/bin"))
    export_parser.add_argument("--pg-host")
    export_parser.add_argument("--pg-port", type=int)
    export_parser.add_argument("--pg-user")

    validate_parser = subparsers.add_parser("validate-bundle")
    validate_parser.add_argument("--bundle-root", type=Path, required=True)

    upload_parser = subparsers.add_parser("upload")
    upload_parser.add_argument("--migration-id", required=True)
    upload_parser.add_argument("--archive", type=Path, required=True)
    upload_parser.add_argument("--checksum", type=Path, required=True)
    upload_parser.add_argument("--ssh-host", default="dev-bjy")
    upload_parser.add_argument("--remote-root", default="/home/dev-bjy/aicheck-migrations")

    args = parser.parse_args()
    if args.command == "export":
        result = export_bundle(
            ExportConfig(
                migration_id=args.migration_id,
                source_root=args.source_root.resolve(),
                output_root=args.output_root.resolve(),
                git_commit=args.git_commit,
                pg_bin=args.pg_bin,
                pg_host=args.pg_host,
                pg_port=args.pg_port,
                pg_user=args.pg_user,
            )
        )
        print(json.dumps({"archive": str(result.archive), "checksum": str(result.checksum_file)}))
        return 0
    if args.command == "validate-bundle":
        root = args.bundle_root.resolve()
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        validate_manifest(manifest, root)
        if (root / "READY").read_text(encoding="utf-8").strip() != manifest["migrationId"]:
            raise BundleValidationError("bundle READY marker does not match migration ID")
        print(json.dumps({"valid": True, "migrationId": manifest["migrationId"]}))
        return 0
    remote = upload_bundle(
        UploadConfig(
            migration_id=args.migration_id,
            archive=args.archive.resolve(),
            checksum_file=args.checksum.resolve(),
            ssh_host=args.ssh_host,
            remote_root=args.remote_root,
        )
    )
    print(json.dumps({"remoteDirectory": remote}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
