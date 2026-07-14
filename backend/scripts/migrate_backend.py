from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


MIGRATIONS_ROOT = Path(__file__).resolve().parents[1] / "db" / "migrations"
MIGRATIONS_MANIFEST = MIGRATIONS_ROOT / "manifest.json"


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_ROOT.glob("*.sql"))


def validate_migration_manifest() -> dict[str, str]:
    if not MIGRATIONS_MANIFEST.is_file():
        raise RuntimeError(f"Migration manifest is missing: {MIGRATIONS_MANIFEST}")
    document = json.loads(MIGRATIONS_MANIFEST.read_text(encoding="utf-8"))
    entries = document.get("migrations") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise RuntimeError("Migration manifest must contain a migrations list.")
    declared: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError("Migration manifest entries must be objects.")
        version = str(entry.get("version") or "")
        checksum = str(entry.get("sha256") or "")
        if not version or len(checksum) != 64 or entry.get("immutable") is not True:
            raise RuntimeError(f"Invalid immutable migration manifest entry: {version or '<missing>'}")
        if version in declared:
            raise RuntimeError(f"Duplicate migration manifest entry: {version}")
        declared[version] = checksum
    files = migration_files()
    actual_versions = [path.stem for path in files]
    if actual_versions != list(declared):
        raise RuntimeError(
            "Migration manifest order/content mismatch: "
            f"declared={list(declared)}, actual={actual_versions}"
        )
    for path in files:
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if declared[path.stem] != checksum:
            raise RuntimeError(f"Immutable migration checksum mismatch: {path.stem}")
    return declared


def apply_migrations(database_url: str, *, dry_run: bool = False) -> list[str]:
    declared = validate_migration_manifest()
    try:
        import psycopg
    except Exception as exc:
        raise RuntimeError(f"psycopg is required for backend migrations: {exc}") from exc

    applied: list[str] = []
    with psycopg.connect(database_url, autocommit=False) as connection:
        try:
            connection.execute("SELECT pg_advisory_xact_lock(hashtext('aicheck_backend_migrations'))")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version text PRIMARY KEY,
                    checksum text NOT NULL,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            existing = {
                str(version): str(checksum)
                for version, checksum in connection.execute(
                    "SELECT version, checksum FROM schema_migrations"
                ).fetchall()
            }
            database_only = sorted(set(existing) - set(declared))
            if database_only:
                raise RuntimeError(
                    "Database contains migration versions unknown to this build: "
                    + ", ".join(database_only)
                )
            for path in migration_files():
                version = path.stem
                sql = path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
                if version in existing:
                    if existing[version] != checksum:
                        raise RuntimeError(f"Applied migration checksum changed: {version}")
                    continue
                applied.append(version)
                if dry_run:
                    continue
                connection.execute(sql)
                connection.execute(
                    "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                    (version, checksum),
                )
            if dry_run:
                connection.rollback()
            else:
                connection.commit()
        except Exception:
            connection.rollback()
            raise
    return applied


def migration_status(database_url: str) -> dict[str, object]:
    """Inspect source/database migration compatibility without changing the database."""

    declared = validate_migration_manifest()
    try:
        import psycopg
    except Exception as exc:
        raise RuntimeError(f"psycopg is required for backend migrations: {exc}") from exc

    with psycopg.connect(database_url, autocommit=True) as connection:
        table_exists = connection.execute(
            "SELECT to_regclass('schema_migrations') IS NOT NULL"
        ).fetchone()[0]
        database_versions = (
            {
                str(version): str(checksum)
                for version, checksum in connection.execute(
                    "SELECT version, checksum FROM schema_migrations ORDER BY version"
                ).fetchall()
            }
            if table_exists
            else {}
        )

    migrations: list[dict[str, str | None]] = []
    for version, source_checksum in declared.items():
        database_checksum = database_versions.get(version)
        if database_checksum is None:
            status = "pending"
        elif database_checksum == source_checksum:
            status = "applied"
        else:
            status = "checksum_mismatch"
        migrations.append(
            {
                "version": version,
                "status": status,
                "sourceChecksum": source_checksum,
                "databaseChecksum": database_checksum,
            }
        )
    for version, database_checksum in database_versions.items():
        if version not in declared:
            migrations.append(
                {
                    "version": version,
                    "status": "database_only",
                    "sourceChecksum": None,
                    "databaseChecksum": database_checksum,
                }
            )

    counts = {
        status: sum(item["status"] == status for item in migrations)
        for status in ("applied", "pending", "checksum_mismatch", "database_only")
    }
    compatible = counts["checksum_mismatch"] == 0 and counts["database_only"] == 0
    return {
        "compatible": compatible,
        "current": compatible and counts["pending"] == 0,
        "schemaMigrationsTable": bool(table_exists),
        "summary": counts,
        "migrations": migrations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply versioned AIcheck backend migrations.")
    parser.add_argument("--database-url", default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--status", action="store_true", help="Inspect database migration checksums without writing.")
    args = parser.parse_args()
    if args.verify_only:
        verified = validate_migration_manifest()
        print(json.dumps({"verified": list(verified), "manifest": str(MIGRATIONS_MANIFEST)}))
        return 0
    if not args.database_url:
        parser.error("--database-url or AICHECK_DATABASE_URL is required")
    if args.status:
        status = migration_status(args.database_url)
        print(json.dumps(status, indent=2))
        return 0 if status["compatible"] else 1
    applied = apply_migrations(args.database_url, dry_run=args.dry_run)
    print(json.dumps({"dryRun": args.dry_run, "pendingOrApplied": applied}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
