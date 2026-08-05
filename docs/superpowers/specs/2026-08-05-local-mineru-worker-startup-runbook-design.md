# Local MinerU Worker Startup Runbook Design

## Objective

Fix the current local MinerU `MINERU_PERSIST_FAILED` error without changing application code or server deployment behavior.

## Selected Approach

Local development must start through `scripts/start-local-dev.zsh`. The script loads `backend/.env`, then deliberately overrides:

- `AICHECK_DATABASE_URL=postgresql:///aicheck`
- `AICHECK_MINERU_EXECUTION_MODE=postgres`
- `AICHECK_MINIO_ENDPOINT=`
- `AICHECK_REQUIRE_OBJECT_STORAGE=false`

These values apply to both the API process and the independent MinerU worker. A worker started manually after only sourcing `backend/.env` is invalid for local development because it enables required MinIO at `127.0.0.1:9000`.

## Operating Procedure

1. Stop any existing `apps.mineru_worker.main` process that was not started with the local overrides.
2. From the repository root run `AICHECK_DEV_NO_FOLLOW=true zsh scripts/start-local-dev.zsh`.
3. Verify `/healthz` reports PostgreSQL and a fresh MinerU worker heartbeat.
4. Retry the failed OCR knowledge task. The worker may reuse the persisted MinerU provider task metadata, but the new OCR job remains the authoritative retry record.
5. Verify the document reaches `已识别`, `已切片`, and `已向量化`.

## Server Compatibility

No server environment file, Compose manifest, deployment manifest, or application storage behavior changes. Server deployments that configure MinIO continue to require and archive MinerU artifacts exactly as before.

## Failure Prevention

For local use, do not run `.venv/bin/python -m apps.mineru_worker.main` after merely sourcing `backend/.env`. Always use the repository startup script, or explicitly provide all four local override variables above.
