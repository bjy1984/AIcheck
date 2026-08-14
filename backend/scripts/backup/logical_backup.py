#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from minio import Minio

SCHEMA_VERSION = "aicheck-backup-manifest-v1"
SECRET_DIR = Path(os.getenv("AICHECK_BACKUP_SECRET_DIR", "/run/secrets/aicheck-backup"))


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def read_secret(name: str) -> str:
    path = SECRET_DIR / name
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError(f"backup secret {path} is missing or not mode 0600")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"backup secret {path} is empty")
    return value


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    password_file = Path(env.get("PGPASSWORD_FILE", str(SECRET_DIR / "postgres_password")))
    if not password_file.is_file() or password_file.stat().st_mode & 0o077:
        raise RuntimeError(f"PostgreSQL password file {password_file} is missing or not mode 0600")
    env["PGPASSWORD"] = password_file.read_text(encoding="utf-8").strip()
    return env


def run(command: list[str], *, env: dict[str, str], output: Path | None = None) -> str:
    if output is None:
        return subprocess.check_output(command, env=env, text=True, stderr=subprocess.STDOUT).strip()
    with output.open("wb") as target:
        subprocess.run(command, env=env, stdout=target, stderr=subprocess.PIPE, check=True)
    return ""


def database_names(env: dict[str, str]) -> list[str]:
    sql = "SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate ORDER BY datname"
    raw = run(["psql", "--no-psqlrc", "--tuples-only", "--no-align", "--command", sql], env=env)
    return [line.strip() for line in raw.splitlines() if line.strip()]


def build_manifest(root: Path, *, started_at: str, databases: list[str], postgres_metadata: dict[str, Any]) -> dict[str, Any]:
    files = {
        path.relative_to(root).as_posix(): {"sha256": sha256_file(path), "size": path.stat().st_size}
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    manifest: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "backupId": datetime.now(UTC).strftime("logical-%Y%m%dT%H%M%SZ"),
        "backupType": "logical-all-databases",
        "startedAt": started_at,
        "completedAt": utc_now(),
        "databases": databases,
        "postgres": postgres_metadata,
        "release": {
            "releaseId": os.getenv("AICHECK_RELEASE_ID"),
            "gitSha": os.getenv("AICHECK_GIT_SHA"),
            "manifestHash": os.getenv("AICHECK_RELEASE_MANIFEST_HASH"),
        },
        "encryption": {"format": "OpenPGP", "cipher": "AES256", "encrypted": True},
        "files": files,
    }
    manifest["manifestHash"] = "sha256:" + hashlib.sha256(canonical_bytes(manifest)).hexdigest()
    return manifest


def main() -> int:
    started_at = utc_now()
    env = command_env()
    databases = database_names(env)
    if not databases:
        raise RuntimeError("no non-template PostgreSQL databases were discovered")
    expected = {item.strip() for item in os.getenv("AICHECK_EXPECTED_DATABASES", "aicheck,litellm,workflow").split(",") if item.strip()}
    missing = sorted(expected.difference(databases))
    if missing:
        raise RuntimeError(f"required databases are missing: {', '.join(missing)}")

    postgres_metadata = json.loads(
        run(
            [
                "psql", "--no-psqlrc", "--tuples-only", "--no-align", "--command",
                "SELECT json_build_object('version', version(), 'walLsn', pg_current_wal_lsn(), 'inRecovery', pg_is_in_recovery())",
            ],
            env=env,
        )
    )
    receipt_dir = Path(os.getenv("AICHECK_BACKUP_RECEIPT_DIR", "/var/lib/aicheck-backup/receipts"))
    receipt_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aicheck-logical-backup-") as temporary:
        root = Path(temporary) / "payload"
        root.mkdir()
        # Role password verifiers are required for a complete recovery. They are
        # never uploaded in plaintext because the bundle is encrypted below.
        run(["pg_dumpall", "--globals-only"], env=env, output=root / "globals.sql")
        dump_dir = root / "databases"
        dump_dir.mkdir()
        for database in databases:
            run(
                ["pg_dump", "--format=custom", "--compress=6", "--no-owner", "--file", str(dump_dir / f"{database}.dump"), database],
                env=env,
            )
        manifest = build_manifest(root, started_at=started_at, databases=databases, postgres_metadata=postgres_metadata)
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        archive = Path(temporary) / f"{manifest['backupId']}.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(root, arcname=manifest["backupId"])
        encrypted = archive.with_suffix(archive.suffix + ".gpg")
        read_secret("logical_backup_passphrase")
        subprocess.run(
            [
                "gpg", "--batch", "--yes", "--pinentry-mode", "loopback", "--passphrase-file",
                str(SECRET_DIR / "logical_backup_passphrase"), "--symmetric", "--cipher-algo", "AES256",
                "--output", str(encrypted), str(archive),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        archive.unlink()

        client = Minio(
            os.environ["AICHECK_OFFSITE_MINIO_ENDPOINT"],
            access_key=read_secret("offsite_minio_access_key"),
            secret_key=read_secret("offsite_minio_secret_key"),
            secure=os.getenv("AICHECK_OFFSITE_MINIO_SECURE", "true").lower() == "true",
        )
        bucket = os.getenv("AICHECK_LOGICAL_BACKUP_BUCKET", "aicheck-db-logical-backups")
        if not client.bucket_exists(bucket):
            raise RuntimeError(f"offsite bucket {bucket!r} does not exist; backup job will not create retention policy")
        prefix = datetime.now(UTC).strftime("%Y/%m/%d")
        encrypted_object = f"{prefix}/{encrypted.name}"
        manifest_object = f"{prefix}/{manifest['backupId']}.manifest.json"
        client.fput_object(bucket, encrypted_object, str(encrypted), content_type="application/pgp-encrypted")
        client.fput_object(bucket, manifest_object, str(manifest_path), content_type="application/json")
        stored = client.stat_object(bucket, encrypted_object)
        if stored.size != encrypted.stat().st_size:
            raise RuntimeError("offsite encrypted backup size verification failed")

        receipt = {
            "schemaVersion": "aicheck-backup-receipt-v1",
            "status": "uploaded_and_size_verified",
            "completedAt": utc_now(),
            "bucket": bucket,
            "encryptedObject": encrypted_object,
            "manifestObject": manifest_object,
            "encryptedSha256": sha256_file(encrypted),
            "encryptedSize": encrypted.stat().st_size,
            "manifestHash": manifest["manifestHash"],
            "databases": databases,
        }
        receipt_path = receipt_dir / "latest-logical-backup.json"
        temporary_receipt = receipt_path.with_suffix(".tmp")
        temporary_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        shutil.move(temporary_receipt, receipt_path)
        print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
