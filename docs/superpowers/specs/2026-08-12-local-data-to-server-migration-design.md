# Local Data to Server Migration Design

## Goal

Copy the complete local AIcheck test dataset to the dedicated empty server through the existing SSH jump-host path. The migration replaces the server PostgreSQL databases, PostgreSQL user-defined global roles, and the four application MinIO buckets as one coordinated dataset.

## Scope

The migration includes:

- PostgreSQL databases `aicheck`, `litellm`, and `workflow`.
- PostgreSQL user-defined global roles, role memberships, password verifiers, and grants exported with `pg_dumpall --globals-only`.
- MinIO buckets `documents`, `previews`, `exports`, and `ocr-artifacts`, including object names, metadata, and content.
- A machine-readable manifest containing the source Git commit, migration identifier, tool versions, database inventory, table counts, selected row counts, bucket object counts and byte totals, file sizes, and SHA-256 digests.
- Scripts and operator documentation committed to Git.

The migration excludes SSH private keys and the local `.env` file because neither is required in the transfer bundle. The database dumps, MinIO objects, generated manifest, and migration logs are transferred outside Git.

## Assumptions

- The target PostgreSQL instance is dedicated to AIcheck and can be reset to an empty state.
- The target MinIO buckets can be emptied and replaced.
- A complete source write freeze is available while both PostgreSQL and MinIO are captured.
- The target remains in maintenance mode until all restore checks pass.
- Source and target use PostgreSQL major version 16. The preflight rejects a major-version mismatch.
- The existing SSH alias `aicheck-prod-new` reaches the server through its configured jump host.
- All migrated content, including PostgreSQL role password verifiers, is test data. The transfer bundle is not encrypted or specially permissioned.

## Architecture

The solution uses a staged logical migration bundle rather than copying Docker volumes or streaming directly into the target. A local export command creates PostgreSQL custom-format dumps, a global-role SQL file, and a filesystem mirror of the four MinIO buckets. It then writes a manifest, computes SHA-256 digests, and creates a plain `tar.gz` archive.

An upload command transfers the archive and its checksum with `scp` to `/home/dev-bjy/aicheck-migrations/<migration-id>/` using `aicheck-prod-new`. A server-side restore command verifies the checksum before making any changes, stops all writers, resets the target data, restores the PostgreSQL roles and databases, mirrors the MinIO objects, and runs layered verification. Git distributes only scripts, configuration, and documentation.

## Components and Responsibilities

### Local export command

The local command:

1. Verifies Docker, PostgreSQL, MinIO Client, `tar`, `sha256sum` or `shasum`, and free disk space.
2. Records the current Git commit and source service versions.
3. Confirms that all three databases and all four buckets exist.
4. Enters the approved write-freeze window by stopping API and asynchronous writers while leaving PostgreSQL and MinIO running.
5. Exports user-defined global roles with `pg_dumpall --globals-only`. The generated SQL may contain password verifiers and is preserved verbatim.
6. Creates one PostgreSQL custom-format dump per database with `pg_dump -Fc`.
7. Mirrors each MinIO bucket into a separate bundle directory with `mc mirror`.
8. Captures database inventory and bucket totals after the dump while the source remains frozen.
9. Generates file-level SHA-256 digests and a manifest.
10. Creates a plain `tar.gz` archive and an archive checksum file.
11. Restarts local services only after the complete source snapshot is closed.

If any export step fails, the command records failure, restarts any source services that it stopped, and leaves the incomplete staging directory for diagnosis. It does not create a ready-to-upload marker.

### Upload command

The upload command accepts only a locally complete bundle with a ready marker and matching SHA-256 checksum. It creates a migration-specific server directory and sends the archive, checksum, and non-secret operator metadata through the existing SSH alias. It verifies the uploaded archive checksum on the server. A checksum failure prevents restore and returns a non-zero status.

Transfer resumption may use `rsync --partial` over the same SSH alias when available. `scp` remains the baseline transport.

### Server restore command

The restore command:

1. Validates the archive checksum and manifest schema before stopping services.
2. Confirms target PostgreSQL 16, target database identity, MinIO reachability, expected Compose/project paths, and sufficient free space.
3. Refuses to run unless an explicit migration identifier and destructive confirmation flag are supplied.
4. Stops `api-service`, all worker services, OCR writers, Temporal services, and LiteLLM. PostgreSQL and MinIO remain running.
5. Creates a small pre-restore target snapshot and inventory receipt even when the target is expected to be empty.
6. Terminates connections to `aicheck`, `litellm`, and `workflow`, then drops and recreates those databases.
7. Removes conflicting user-defined roles. PostgreSQL built-in roles, names beginning with `pg_`, and the bootstrap administrator used by the restore are never removed.
8. Applies `globals.sql` to restore source roles, password verifiers, memberships, and grants.
9. Restores all three custom-format dumps with `pg_restore --clean --if-exists --no-owner`, then reapplies source database ownership from the manifest.
10. Empties the four target MinIO buckets and mirrors the staged objects into them. Missing buckets are created before mirroring.
11. Runs structural, content, and application verification.
12. Starts all required services only after structural restoration succeeds. External maintenance mode remains active until application verification passes.

The restore is an all-or-nothing operational procedure. If one database or bucket fails, the server is not returned to service with a partial dataset; the target is reset and the complete restore is rerun.

## Data Flow

```text
local write freeze
  -> PostgreSQL global-role export and three custom dumps
  -> four MinIO bucket mirrors
  -> inventory manifest and SHA-256 digests
  -> plain tar.gz archive
  -> scp/rsync through aicheck-prod-new jump-host configuration
  -> server checksum and preflight
  -> stop target writers
  -> reset and restore PostgreSQL roles/databases
  -> empty and restore MinIO buckets
  -> structural verification
  -> start services under maintenance mode
  -> application verification
  -> release maintenance mode
```

## PostgreSQL Global Role Policy

“Replace system roles” means replacing every source-managed, user-defined PostgreSQL global role and its memberships on the dedicated target instance. It does not mean deleting PostgreSQL built-in roles. The restore preserves:

- the active bootstrap administrator required to finish restoration;
- the `postgres` administrative role if present;
- all PostgreSQL-maintained roles whose names begin with `pg_`.

All other conflicting target roles may be dropped before applying `globals.sql`. After role restoration, the procedure verifies the source and target user-defined role names, login flags, superuser flags, inheritance flags, connection limits, and memberships. Password verifiers are restored by the SQL file but are not compared in a report beyond successful authentication checks.

## Verification and Acceptance

### Transfer integrity

- The server archive SHA-256 equals the local archive SHA-256.
- Every file listed in the manifest exists after extraction and has the recorded size and SHA-256.

### PostgreSQL structure and content

- The target contains `aicheck`, `litellm`, and `workflow` with the recorded owners.
- User-defined global roles and memberships match the source inventory.
- Each database restores without `pg_restore` errors.
- Schema counts, table counts, and source-recorded row counts match.
- Large or operational tables not included in exact row-count checks are compared using deterministic aggregate checks recorded in the manifest.
- PostgreSQL extensions required by the application, including vector support where used, are present.

### MinIO content

- All four expected buckets exist.
- Per-bucket target object count and total logical bytes equal the source manifest.
- The verifier checks hashes for every object when the MinIO API exposes a usable checksum. Otherwise it verifies size for every object and SHA-256 for a deterministic sample of at least 20 objects per bucket or all objects when the bucket has fewer than 20.
- No target object exists outside the source manifest after replacement.

### Application acceptance

- `GET /healthz` reports PostgreSQL transactions, authentication, and object storage enabled.
- `scripts/verify_deployment.py --strict-production --roles admin,inspection,contractor,ndt,owner,fde` passes against the restored server configuration, or the deployment's documented non-strict test profile is explicitly selected and recorded when the current server is intentionally not strict-production capable.
- All six roles can authenticate.
- Historical projects, documents, ReviewRuns, AI feedback, and audit records are queryable.
- Representative historical files support preview and download through signed MinIO URLs.
- LiteLLM model aliases are queryable and Temporal/LangGraph records can be opened.

The restore receipt records each check, its status, start and completion timestamps, the migration identifier, and the Git commit. Maintenance mode is removed only when all mandatory checks pass.

## Failure Handling and Rollback

- Export failure: restart locally stopped writers, retain the incomplete staging directory, and do not mark the bundle ready.
- Upload or checksum failure: leave the target unchanged and resume or repeat transfer.
- Preflight failure: leave target services and data unchanged.
- PostgreSQL restore failure: keep target application writers stopped, reset all three databases, and rerun the complete restore.
- MinIO restore failure: keep maintenance mode active, empty all four buckets, and rerun all bucket mirrors.
- Application verification failure: keep maintenance mode active and retain logs. Either correct the environment and rerun verification, repeat the complete migration, or restore the target pre-restore snapshot.

Because the target is disposable and initially empty, the primary rollback is a complete reset followed by a fresh restore. The pre-restore target snapshot remains available as secondary evidence and rollback material until acceptance.

## Data Handling and Retention

The bundle is ordinary test data:

- It is a plain `tar.gz`, not encrypted.
- Logs may include database names, table names, row counts, bucket names, object names, PostgreSQL role definitions, and command output.
- No special file modes or secret-redaction layer is required.
- `globals.sql` is transferred verbatim, including password verifiers.
- SSH private keys and `.env` are excluded because they are unnecessary, not because the bundle is classified as secret.
- The server transfer bundle is retained for three days after successful acceptance and then removed manually or by a migration-specific cleanup command.
- Migration bundles are never committed to Git.

## Git Workflow

Git synchronizes the export, upload, restore, verification, and cleanup scripts plus this documentation. Generated migration directories are added to `.gitignore`. Each migration manifest records the exact source Git commit, while data continues through the SSH transfer channel.

The existing `backend/scripts/deploy_to_server.sh` is not used to transport database content. Its current hard-coded application credentials are outside the data migration bundle and do not block this test-data migration, though replacing them with environment configuration remains a separate deployment-hardening task.

## Operational Sequence

1. Start local Docker services and measure database, bucket, archive, and free-space requirements.
2. Validate server reachability, target versions, target capacity, and empty/dedicated-instance assumptions.
3. Synchronize reviewed migration scripts through Git.
4. Enter local write freeze and generate the migration bundle.
5. Verify the local bundle and restart local writers.
6. Upload and verify the bundle on the server.
7. Put the target into maintenance mode and execute the destructive restore.
8. Run data-level and application-level verification.
9. Release maintenance mode and record the restore receipt.
10. Retain the server bundle for three days, then remove it.

## Out of Scope

- Merging local and server records.
- Incremental replication or continuous synchronization.
- Migrating Redis cache contents.
- Copying Docker/PostgreSQL physical data directories.
- Committing data archives to Git.
- Refactoring existing deployment credentials as part of the migration.
