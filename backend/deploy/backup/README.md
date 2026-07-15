# AIcheck production backup and recovery

This stack adds encrypted pgBackRest physical backups with continuous WAL archiving, an encrypted logical backup of
every non-template database, version-preserving MinIO replication, and a destructive restore test that is restricted to
a dedicated Docker volume. It does not modify application rows, test fixtures, users, or roles. The restore drill only
forces a PostgreSQL WAL switch to establish a measurable recovery canary.

## Recovery objectives

- RPO: at most 15 minutes. PostgreSQL uses continuous WAL archiving with `archive_timeout=60s`; the monthly drill must
  recover the exact WAL canary captured immediately before the drill.
- RTO: at most four hours, measured from canary capture through isolated PostgreSQL startup and database inventory.
- Retention: six weekly full physical backups and up to 35 daily differential backups. Archive retention follows the
  six retained full backup sets.
- Logical coverage: `aicheck`, `litellm`, `workflow`, `postgres`, and every other non-template database discovered at
  runtime. Global roles and password verifiers are inside the encrypted bundle.

## Secrets and prerequisites

Create an off-host MinIO deployment running the exact same MinIO release as production. Configure KMS-backed SSE-S3
on the offsite service. The replication bootstrap deliberately fails if SSE-S3, versioning, same-version replication,
or `audit-anchors-v2` COMPLIANCE retention cannot be established.

Create a root-owned directory, mode `0700`, containing mode `0600` files:

```text
postgres_password
pgbackrest_s3_key
pgbackrest_s3_key_secret
pgbackrest_cipher_pass
logical_backup_passphrase
offsite_minio_access_key
offsite_minio_secret_key
```

The pgBackRest S3 repository and logical backup bucket must already exist on the offsite target. Bucket creation and
retention are infrastructure-owner actions; the logical backup job intentionally refuses to invent a bucket without a
retention policy.

Copy `backup.env.example` to `/etc/aicheck/backup.env`, replace every placeholder, and put the production Compose env
at the path named by `AICHECK_ENV_FILE`. Never place secret values in either env file.

## Enable without replacing PostgreSQL data

Render the candidate configuration first:

```bash
docker compose --env-file /etc/aicheck/production.env \
  -f docker-compose.deploy.yml \
  -f docker-compose.production-data.yml \
  -f docker-compose.backup.yml config --quiet
```

Build the custom PostgreSQL image, take and verify the existing final logical snapshot, and restart only PostgreSQL in
the approved maintenance window. Enabling `archive_mode` requires a PostgreSQL restart but does not reinitialize
`/home/dev-bjy/aicheck-data/postgres`.

Install `scripts/backup/run_backup.sh` as `/usr/local/bin/aicheck-run-backup`, install the units in
`deploy/systemd`, then initialize the stanza and take the first full backup:

```bash
sudo /usr/local/bin/aicheck-run-backup init
sudo /usr/local/bin/aicheck-run-backup full
sudo /usr/local/bin/aicheck-run-backup logical
sudo systemctl enable --now \
  aicheck-backup-full.timer \
  aicheck-backup-diff.timer \
  aicheck-backup-logical.timer \
  aicheck-backup-restore-drill.timer \
  aicheck-backup-verify.timer
```

## MinIO replication

Run `scripts/backup/configure_minio_replication.sh` from a hardened administration host with `mc` and `jq`. It enables
versioning on both ends, KMS-backed SSE-S3 on the destination, existing/new object replication without delete
replication, ten-year COMPLIANCE retention for the offsite audit-anchor bucket, and version inventory verification.
Store the generated receipt as `minio-replication-receipt.json` in the backup receipt directory.

## Restore drill and release gate

The monthly drill restores into the `restore-drill-data` volume only. The script refuses any other `PGDATA`. It checks
WAL canary recovery, database inventory, and measured RTO, then writes `latest-restore-drill.json`.

After physical, logical, replication, and restore evidence exists:

```bash
sudo /usr/local/bin/aicheck-run-backup verify
python -m scripts.deployment_report \
  --release-gate \
  --release-manifest /secure/release/release-manifest.json \
  --backup-recoverability-report /home/dev-bjy/aicheck-data/backup-receipts/backup-recoverability.json \
  ...
```

Any missing/stale receipt, missing database, RPO above 15 minutes, RTO above four hours, or failed restore drill is a
formal NO-GO. A successful upload without a successful isolated restore is not accepted as a backup.

## Local-only interim mode

When an approved offsite S3/KMS destination is not yet available, use `docker-compose.backup-local.yml` with
`AICHECK_BACKUP_MODE=local_only`. This enables AES-256 encrypted pgBackRest backups, continuous WAL archiving, and the
same isolated restore drill on the production host. Enable only the full, differential, restore-drill, and verify
timers; the logical-upload timer intentionally remains disabled.

The generated `local-backup-readiness.json` always contains `formalRecoverability: false` and `offsiteVerified: false`.
Local-only mode reduces recovery risk for database or application failure but does not survive loss or compromise of
the production host and never satisfies the formal production recoverability gate.
