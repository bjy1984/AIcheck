# Production remediation runbook

This runbook is the only supported path for upgrading a legacy AIcheck production database that does not yet contain
`schema_migrations`. Normal Compose startup must not be used to apply the first hardening migration.

## Fixed production decisions

- Canonical tenant: `TENANT-DEFAULT`
- Tenant mode after cutover: `isolated`
- Maintenance window: 90 minutes, zero accepted writes
- Audit anchor bucket: `audit-anchors-v2`
- Object retention: `COMPLIANCE`, 3650 days
- Rollback before reopening writes: restore the database snapshot and old image together

## Before the window

1. Block public raw service ports at the cloud security group. Only the approved HTTPS ingress and allowlisted SSH may
   remain. Do not enable host firewalld blindly on a Docker host.
   Render `backend/deploy/nginx/aicheck.conf.template` for the application domain and
   `backend/deploy/nginx/aicheck-files.conf.template` for the signed-object domain. Set
   `AICHECK_MINIO_PUBLIC_ENDPOINT=https://<files-domain>`; never publish the raw MinIO port.
2. Create a PostgreSQL custom-format dump and a volume snapshot. Restore the dump into an isolated PostgreSQL 16
   instance with the same pgvector version.
3. On the restored database, capture the plan and digest:

   ```bash
   cd backend
   python -m scripts.prepare_legacy_production \
     --database-url "$RESTORED_DATABASE_URL" \
     --tenant-id TENANT-DEFAULT \
     --manifest-output /secure/incident/preflight.json
   ```

4. Run the preparation against the restored database using the exact row count and digest printed by step 3. Then run
   it with `--apply --incident-id "$INCIDENT_ID" --confirmation "$INCIDENT_ID"`, followed by
   `python -m scripts.migrate_backend`; set up LangGraph checkpoints, start the candidate image, and run all live probes.
   `--plan-only`/`--dry-run` does not execute SQL and is never accepted as a rehearsal.
5. Restore the pre-migration snapshot again and prove the old image starts. Record migration and restore durations;
   both must fit the 90-minute window.
6. Create `audit-anchors-v2` with Object Lock enabled at bucket creation time. Set
   `AICHECK_AUDIT_ANCHOR_OBJECT_LOCK=true` and `AICHECK_AUDIT_ANCHOR_RETENTION_DAYS=3650`, then use
   `scripts.legacy_audit_manifest --upload --verify-delete-denied` to prove versioned COMPLIANCE retention.

## ReviewRun evidence and reconciliation

Create an `aicheck-review-reconciliation-v1` JSON plan with exact workflow and run IDs. Run
`scripts.reconcile_review_runs` without `--apply` first and store its evidence directory off-host. The production plan is:

- terminate Temporal orphans `RRUN-AB67B7F4C5` and `RRUN-C96C1EC5E9` after evidence export;
- terminate Temporal executions for database-terminal `RRUN-373DD7A1C6` and `RRUN-9C880127CE`, retaining failed DB rows;
- preserve `RRUN-24E422D36C` and `RRUN-46186380EB` only if Temporal replay and DB/query state both pass;
- mark `RRUN-1`, `RRUN-REPLAY-2D7C8DAA`, and `RRUN-REPLAY-2F03A634` as `failed_to_start` only after confirming no
  corresponding Temporal execution exists.

Application deletes, ad-hoc JSONB updates, Temporal reset, and suffix-based termination are prohibited.

## Maintenance window

1. Put the reverse proxy in mutation-deny maintenance mode. Stop API, Celery, review workers, schedulers, and migration
   jobs. Leave PostgreSQL, Temporal, and MinIO available for evidence capture.
2. Confirm there are no active business transactions or in-flight queue items. Take the final custom dump and volume
   snapshot and verify the dump by restoring it to a temporary database.
3. Generate and WORM-lock the legacy audit manifest using the final backup reference.
4. Run `prepare_legacy_production --apply` with the exact incident ID, row count, and digest from the final preflight.
   Use batch size 100. Any foreign key, count, digest, lock, or disk guard failure is NO-GO.
5. Run `migrate_backend --verify-only`, `migrate_backend --status`, then apply migration 0001 with PostgreSQL
   `lock_timeout=5s` and the rehearsed statement timeout. Never start the `workflow-migrate` profile before this point.
6. Run `setup_langgraph_checkpoint`, then `seal_legacy_audit --apply`. The seal must create sequence 1 and a versioned
   immutable anchor before any application write is enabled.
7. Start API and workers from fixed image digests. `/readyz` must report every check true. Run role-login, permission
   denial, object upload/download, Qwen/LiteLLM, Temporal, outbox/inbox, and audit-chain probes.
8. Run the reconciliation plan with `--apply`, re-run its read-only mode, and confirm there are no split-brain workflows.
9. Reopen writes only after collection counts and payload digests match the final backup and every GO gate is signed.

## Rollback

- Before writes reopen: stop candidate services, restore the final snapshot/dump, verify the original digest, then start
  the old image. Rolling back only the application image is prohibited.
- After writes reopen: preserve a post-cutover dump and audit anchor and use a reviewed forward fix. A destructive
  snapshot rollback is prohibited because it would discard new business and audit writes.
- Network restrictions, TLS, credential rotation, isolated tenant mode, and Object Lock are never rolled back.
