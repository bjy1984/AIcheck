from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.data_migration import (
    BundleValidationError,
    ExportConfig,
    UploadConfig,
    bootstrap_role_password_sql,
    export_bundle,
    require_destructive_confirmation,
    safe_user_roles,
    sha256_file,
    upload_bundle,
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


def test_bootstrap_role_sync_preserves_privileges_and_copies_only_scram_password() -> None:
    globals_sql = """
CREATE ROLE aicheck;
ALTER ROLE aicheck WITH NOSUPERUSER INHERIT NOCREATEROLE NOCREATEDB LOGIN NOREPLICATION NOBYPASSRLS PASSWORD 'SCRAM-SHA-256$4096:salt$stored:server';
"""

    assert bootstrap_role_password_sql(globals_sql, role="aicheck") == (
        "ALTER ROLE aicheck PASSWORD "
        "'SCRAM-SHA-256$4096:salt$stored:server';"
    )


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


class ExportRunner:
    def __init__(self, *, fail_database: str | None = None) -> None:
        self.commands: list[list[str]] = []
        self.fail_database = fail_database

    def __call__(self, command: list[str], *, output: Path | None = None) -> str:
        self.commands.append(command)
        database = command[-1] if command and command[0].endswith("pg_dump") else None
        if self.fail_database is not None and database == self.fail_database:
            raise RuntimeError(f"failed to dump {database}")
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("CREATE ROLE aicheck;\n", encoding="utf-8")
        for argument in command:
            if argument.startswith("--file="):
                target = Path(argument.removeprefix("--file="))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(f"dump:{database}".encode())
        return ""


def make_source_files(root: Path) -> None:
    files = {
        "output/document_uploads/project/document.pdf": b"document",
        "output/knowledge_uploads/source/standard.pdf": b"knowledge",
        "rules/standards/rule.pdf": b"rule",
    }
    for relative, body in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


def test_export_bundle_captures_three_databases_and_local_file_roots(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "migrations"
    make_source_files(source)
    runner = ExportRunner()

    result = export_bundle(
        ExportConfig(
            migration_id="migration-20260812T120000Z",
            source_root=source,
            output_root=output,
            git_commit="abc123",
            pg_bin=Path("/postgres/bin"),
        ),
        runner=runner,
    )

    bundle_root = output / "migration-20260812T120000Z"
    manifest = json.loads((bundle_root / "manifest.json").read_text())
    assert (bundle_root / "READY").is_file()
    assert result.archive == output / "migration-20260812T120000Z.tar.gz"
    assert result.archive.is_file()
    assert result.checksum_file.read_text().split()[0] == sha256_file(result.archive).removeprefix("sha256:")
    assert manifest["databases"] == ["aicheck", "litellm", "workflow"]
    assert manifest["localFileRoots"] == [
        "output/document_uploads",
        "output/knowledge_uploads",
        "rules",
    ]
    assert set(manifest["files"]) == {
        "globals.sql",
        "databases/aicheck.dump",
        "databases/litellm.dump",
        "databases/workflow.dump",
        "files/output/document_uploads/project/document.pdf",
        "files/output/knowledge_uploads/source/standard.pdf",
        "files/rules/standards/rule.pdf",
    }
    assert [command[-1] for command in runner.commands if command[0].endswith("pg_dump")] == [
        "aicheck",
        "litellm",
        "workflow",
    ]


def test_export_bundle_never_marks_failed_snapshot_ready(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "migrations"
    make_source_files(source)

    with pytest.raises(RuntimeError, match="workflow"):
        export_bundle(
            ExportConfig(
                migration_id="migration-failed",
                source_root=source,
                output_root=output,
                git_commit="abc123",
                pg_bin=Path("/postgres/bin"),
            ),
            runner=ExportRunner(fail_database="workflow"),
        )

    assert not (output / "migration-failed" / "READY").exists()
    assert not (output / "migration-failed.tar.gz").exists()


class UploadRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], *, output: Path | None = None) -> str:
        assert output is None
        self.commands.append(command)
        return ""


def test_upload_bundle_uses_migration_directory_and_remote_checksum(tmp_path: Path) -> None:
    archive = tmp_path / "migration-20260812T120000Z.tar.gz"
    archive.write_bytes(b"archive")
    checksum = tmp_path / "migration-20260812T120000Z.tar.gz.sha256"
    checksum.write_text(
        f"{hashlib.sha256(b'archive').hexdigest()}  {archive.name}\n", encoding="utf-8"
    )
    runner = UploadRunner()

    remote = upload_bundle(
        UploadConfig(
            migration_id="migration-20260812T120000Z",
            archive=archive,
            checksum_file=checksum,
            ssh_host="dev-bjy",
            remote_root="/home/dev-bjy/aicheck-migrations",
        ),
        runner=runner,
    )

    assert remote == "/home/dev-bjy/aicheck-migrations/migration-20260812T120000Z"
    assert runner.commands == [
        [
            "ssh",
            "dev-bjy",
            "mkdir -p -- /home/dev-bjy/aicheck-migrations/migration-20260812T120000Z",
        ],
        [
            "scp",
            str(archive),
            str(checksum),
            "dev-bjy:/home/dev-bjy/aicheck-migrations/migration-20260812T120000Z/",
        ],
        [
            "ssh",
            "dev-bjy",
            "cd /home/dev-bjy/aicheck-migrations/migration-20260812T120000Z && "
            "sha256sum -c migration-20260812T120000Z.tar.gz.sha256",
        ],
    ]


def test_restore_script_refuses_to_touch_target_without_confirmation(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "restore_data_migration.sh"

    result = subprocess.run(
        [
            "bash",
            str(script),
            "--migration-id",
            "migration-20260812T120000Z",
            "--archive",
            str(tmp_path / "missing.tar.gz"),
            "--checksum",
            str(tmp_path / "missing.sha256"),
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 64
    assert "--confirm-replace" in result.stderr


def test_server_runtime_profile_never_mutates_restored_data() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "deploy_runtime_profile.sh"

    result = subprocess.run(
        ["bash", str(script), "--json"],
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(result.stdout) == {
        "bootstrapLocalRoles": False,
        "enableDemoData": False,
    }
