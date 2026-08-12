# Local Data to Server Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export the complete local AIcheck PostgreSQL and MinIO test dataset, transfer it through `aicheck-prod-new`, replace the dedicated target data, and prove the restored application works.

**Architecture:** A testable Python CLI builds and validates a portable migration bundle; a small shell entry point invokes the same CLI locally and over SSH. Destructive restore requires the exact migration ID plus `--confirm-replace`, preserves PostgreSQL built-in/bootstrap roles, and does not release the target until manifest and application checks pass.

**Tech Stack:** Python 3.11+, pytest, Docker Compose, PostgreSQL 16 (`pg_dump`, `pg_dumpall`, `pg_restore`, `psql`), MinIO Client (`mc`), SSH/SCP, tar, SHA-256.

## Global Constraints

- Source databases are exactly `aicheck`, `litellm`, and `workflow`.
- Source and target buckets are exactly `documents`, `previews`, `exports`, and `ocr-artifacts`.
- Target SSH alias is `aicheck-prod-new` and target staging root is `/home/dev-bjy/aicheck-migrations`.
- Target is a dedicated empty/resettable PostgreSQL and MinIO test instance.
- Migration bundles are plain `tar.gz`; they are not encrypted or redacted and must never be committed to Git.
- SSH private keys and `.env` files are excluded from bundles.
- Restore must reject PostgreSQL major versions other than 16, checksum mismatches, incomplete manifests, and missing destructive confirmation.
- PostgreSQL built-in roles, `postgres`, roles beginning `pg_`, and the active restore administrator are never dropped.

---

### Task 1: Bundle contract and safety validation

**Files:**
- Create: `backend/scripts/data_migration.py`
- Create: `backend/tests/test_data_migration.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `MigrationManifest`, `validate_manifest(payload)`, `sha256_file(path)`, `safe_user_roles(roles, bootstrap_role)`, and CLI subcommand `validate-bundle`.
- Consumes: only Python standard library.

- [ ] **Step 1: Write failing tests for exact database/bucket sets, checksum validation, role preservation, and destructive confirmation.**

  Tests construct temporary manifests and assert invalid database/bucket inventories, changed files, missing confirmation, `postgres`, `pg_*`, and bootstrap-role deletion attempts are rejected.

- [ ] **Step 2: Run the focused test and verify it fails because `scripts.data_migration` does not exist.**

  Run: `cd backend && pytest -q tests/test_data_migration.py`
  Expected: collection error for missing `scripts.data_migration`.

- [ ] **Step 3: Implement the manifest model, digest functions, validation, safe role filtering, and `validate-bundle`.**

  The manifest schema is `aicheck-data-migration-v1`; paths must be relative, may not contain `..`, and must match the SHA-256 and byte size recorded in the manifest.

- [ ] **Step 4: Run focused tests and verify they pass.**

  Run: `cd backend && pytest -q tests/test_data_migration.py`
  Expected: all Task 1 tests pass.

- [ ] **Step 5: Add `backend/data-migrations/` to `.gitignore` and commit.**

  ```bash
  git add .gitignore backend/scripts/data_migration.py backend/tests/test_data_migration.py
  git commit -m "feat: add safe data migration bundle contract"
  ```

### Task 2: Local export and inventory

**Files:**
- Modify: `backend/scripts/data_migration.py`
- Modify: `backend/tests/test_data_migration.py`

**Interfaces:**
- Produces CLI subcommand `export` with `--output-root`, `--compose-file`, `--env-file`, and `--migration-id`.
- Produces bundle layout `globals.sql`, `databases/*.dump`, `minio/<bucket>/`, `manifest.json`, `READY`, `<migration-id>.tar.gz`, and `<migration-id>.tar.gz.sha256`.

- [ ] **Step 1: Write failing command-generation and failure-cleanup tests.**

  Assert the exporter stops only writer services, runs `pg_dumpall --globals-only`, runs three `pg_dump -Fc` commands, mirrors exactly four buckets, restarts stopped services in `finally`, and creates `READY` only after manifest validation.

- [ ] **Step 2: Run focused tests and verify expected assertion failures.**

  Run: `cd backend && pytest -q tests/test_data_migration.py -k export`

- [ ] **Step 3: Implement export orchestration with an injectable command runner.**

  Docker Compose commands use explicit project directory/compose/env arguments. Inventory is captured from `psql` and `mc`; no `.env` file is copied into staging.

- [ ] **Step 4: Run all migration tests.**

  Run: `cd backend && pytest -q tests/test_data_migration.py`

- [ ] **Step 5: Commit.**

  ```bash
  git add backend/scripts/data_migration.py backend/tests/test_data_migration.py
  git commit -m "feat: export PostgreSQL and MinIO migration bundle"
  ```

### Task 3: Upload and destructive server restore

**Files:**
- Modify: `backend/scripts/data_migration.py`
- Modify: `backend/tests/test_data_migration.py`
- Create: `backend/scripts/migrate_local_data_to_server.sh`

**Interfaces:**
- Produces CLI subcommands `upload` and `restore`.
- `upload` accepts `--archive`, `--ssh-host`, and `--remote-root`.
- `restore` accepts `--bundle`, `--compose-file`, `--env-file`, `--migration-id`, `--confirm-replace`, and `--bootstrap-role`.

- [ ] **Step 1: Write failing tests for upload checksum verification and destructive restore guards.**

  Assert upload uses a migration-specific directory, verifies SHA-256 remotely, restore refuses mismatched migration IDs, target PostgreSQL non-16, missing target services, and missing confirmation.

- [ ] **Step 2: Run focused tests and verify expected failures.**

  Run: `cd backend && pytest -q tests/test_data_migration.py -k 'upload or restore'`

- [ ] **Step 3: Implement upload and restore.**

  Restore stops writers, captures target inventory, drops/recreates the three databases, filters and drops only conflicting user roles, applies `globals.sql`, restores dumps, empties and mirrors the four MinIO buckets, and writes `restore-receipt.json`. Any failure keeps target application writers stopped.

- [ ] **Step 4: Implement the operator shell wrapper.**

  The wrapper executes `preflight`, `export`, `upload`, then the remote `restore` using `ssh aicheck-prod-new`; all variable values have explicit defaults and can be overridden without editing the script.

- [ ] **Step 5: Run migration tests and shell syntax validation.**

  ```bash
  cd backend
  pytest -q tests/test_data_migration.py
  bash -n scripts/migrate_local_data_to_server.sh
  ```

- [ ] **Step 6: Commit.**

  ```bash
  git add backend/scripts/data_migration.py backend/scripts/migrate_local_data_to_server.sh backend/tests/test_data_migration.py
  git commit -m "feat: restore migration bundles through jump host"
  ```

### Task 4: Dry-run preflight and real migration

**Files:**
- Create at runtime only: `backend/data-migrations/<migration-id>/`
- Create at runtime only on server: `/home/dev-bjy/aicheck-migrations/<migration-id>/`

**Interfaces:**
- Consumes the CLI and wrapper from Tasks 1–3.
- Produces local/remote preflight output, archive checksum, and server `restore-receipt.json`.

- [ ] **Step 1: Start local Docker and inspect actual source services, database sizes, bucket totals, and free disk space.**

  Run Docker Desktop if necessary, then use read-only Docker/psql/mc commands. Select the actual local compose/env arguments from observed containers and configuration.

- [ ] **Step 2: Verify jump-host connectivity and target identity without modifying it.**

  Run: `ssh -o BatchMode=yes aicheck-prod-new 'hostname; docker ps --format "{{.Names}}"; df -h /home/dev-bjy'`

- [ ] **Step 3: Run local and remote preflight.**

  Expected: source/target PostgreSQL major version 16, three source databases, four source buckets, expected target services, and enough space.

- [ ] **Step 4: Execute the approved write freeze, export, upload, checksum verification, and destructive restore.**

  Use a timestamped migration ID and record it in the operator log. The exact restore call must contain both the same `--migration-id` and `--confirm-replace`.

- [ ] **Step 5: Preserve receipts and record any interruption.**

  If execution fails, do not restart target writers automatically; diagnose from the receipt/log and rerun the entire restore after correction.

### Task 5: End-to-end acceptance and handoff

**Files:**
- Modify if needed: `DEPLOYMENT.md`
- Runtime evidence only: `backend/data-migrations/<migration-id>/acceptance/`

**Interfaces:**
- Consumes restored PostgreSQL/MinIO data and existing `scripts/verify_deployment.py`.
- Produces final source-target inventory comparison and application acceptance evidence.

- [ ] **Step 1: Compare source and target database inventories and MinIO totals.**

  Exact database/table/selected row counts and per-bucket object counts/bytes must match the source manifest.

- [ ] **Step 2: Run application verification.**

  Run the strict verifier when the target is strict-production capable; otherwise run and record the documented server test profile, including six-role login, PostgreSQL transaction probe, historical project/document reads, signed preview/download, LiteLLM aliases, and workflow records.

- [ ] **Step 3: Run the complete relevant automated test suite and static checks.**

  ```bash
  cd backend
  pytest -q tests/test_data_migration.py tests/test_backup_recoverability.py tests/test_verify_deployment.py
  bash -n scripts/migrate_local_data_to_server.sh
  git diff --check
  ```

- [ ] **Step 4: Update operator documentation only if actual environment details differ from the approved design, then rerun checks.**

- [ ] **Step 5: Commit documentation/evidence references, report the migration ID and verification results, and mark the goal complete.**
