# AIcheck Backend

FastAPI backend for the AIcheck frontend contract, with production-like MongoDB, MinIO, Redis/Celery, OCR, and LiteLLM integration paths.

Deployment guide: see [`../DEPLOYMENT.md`](../DEPLOYMENT.md).

## Services

- `api-service`: FastAPI business API. It serves both stripped paths such as `/workbench/projects` and direct `/api/workbench/projects`.
- `worker-service`: Celery worker with Redis queues for OCR, knowledge slicing, embedding, AI recheck, LLM compare, and export packaging.
- `ocr-service`: local-only Document Intelligence service built from `Dockerfile.ocr`. It keeps the legacy agentdesign seal OCR import path, adds async document-parse jobs, and requires local model artifacts mounted at `/models`; production should keep `AICHECK_OCR_ALLOW_PLACEHOLDER=false`, `AICHECK_OCR_OFFLINE_ONLY=true`, and `AICHECK_OCR_DISABLE_NETWORK=true`.
- `litellm-service`: LiteLLM proxy configured by `config/litellm.yaml`; PostgreSQL is only for LiteLLM metadata.
- `mongodb`, `redis`, `minio`: business persistence, task queue, and object storage for documents/previews/exports/OCR artifacts.
- Docker Compose healthchecks are declared for API, worker, OCR, MongoDB, Redis, MinIO, LiteLLM PostgreSQL, and LiteLLM; service dependencies use `condition: service_healthy` for startup ordering.

## Local Run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
AICHECK_BOOTSTRAP_LOCAL_ROLES=true \
AICHECK_BOOTSTRAP_PASSWORD_ADMIN='Local!2026-SystemZ' \
AICHECK_BOOTSTRAP_PASSWORD_INSPECTION='Local!2026-InspectZ' \
AICHECK_BOOTSTRAP_PASSWORD_CONTRACTOR='Local!2026-BuildZ' \
AICHECK_BOOTSTRAP_PASSWORD_NDT='Local!2026-TestZ' \
AICHECK_BOOTSTRAP_PASSWORD_OWNER='Local!2026-ViewZ' \
uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

Without `AICHECK_MONGO_URL`, `AICHECK_MINIO_ENDPOINT`, or `AICHECK_TASK_DISPATCH`, the API runs in compatibility mode using seeded in-memory data and mock URLs. This mode is intended for fast frontend contract tests.
Set `AICHECK_BOOTSTRAP_LOCAL_ROLES=true` to inject the five PBKDF2 role accounts into the in-memory repository for local login checks without MongoDB.

Frontend live-backend mode:

```bash
cd frontend
pnpm vite --mode live
```

The Vite proxy forwards `/api/*` to FastAPI after stripping `/api`, and forwards `/mock/*` unchanged for login compatibility.

## Tests

```bash
cd backend
source .venv/bin/activate
pytest
```

The contract suite covers the response envelope, compatibility login paths, persistent user login with demo users disabled, mutation idempotency and body-conflict detection, archived/etag guards, submission withdrawal, rectification feedback, report-generation state guards, backend-inferred action-code guards, read/write URL/body/resource-derived node-scope guards, list-level node-scope filtering, upload-to-OCR task creation, OCR HTTP client dispatch, inline OCR field/chunk writeback, retry/cancel behavior for knowledge tasks, LiteLLM failure mapping, async LLM compare, object-storage export artifacts, JWT/action/node-scope identity guards, and Mongo state round-trip.

Deployment verification:

```bash
python scripts/verify_deployment.py --strict-production
python scripts/deployment_report.py --strict-production --output-dir ./deployment-reports/latest
python scripts/audit_frontend_contract.py
```

96+ live acceptance runbook:

```bash
cd backend
cp .env.example .env
# Replace placeholders in .env with real secrets, provider keys, and local OCR model paths.
# AICHECK_OCR_MODELS_HOST_PATH must contain paddleocr/, paddlex/, paddleocr-vl/, and docling/.
python scripts/check_96_preflight.py --strict-production
docker compose --env-file .env up --build -d
set -a; source .env; set +a
python scripts/deployment_report.py \
  --strict-production \
  --include-live \
  --write-probes \
  --ocr-object-probe \
  --litellm-management-probes \
  --litellm-provider-probes \
  --output-dir ./deployment-reports/latest
```

`check_96_preflight.py` fails early when Docker Compose, `backend/.env`, production flags, LiteLLM/provider keys, the `agentdesign` OCR reference path, or local OCR model directories are missing. Text and JSON output include `remediation` steps for each failing check so the deployment host can be corrected before live probes. The management probe creates and deletes a temporary LiteLLM virtual key to verify DB-backed key, budget, and rate-limit management. The provider probe spends real LiteLLM upstream quota; omit `--litellm-provider-probes` only for a dry infrastructure check.

The verifier checks API health flags, role login/default paths, JWT protection, the MongoDB transaction probe, read-only project/task endpoints, identity-spoof rejection, action-bypass rejection, read-scope rejection, OCR health/readyz, OCR parse/bad-request contracts, and LiteLLM health/models without creating business data or spending model quota. In `--strict-production`, MongoDB must be connected with `AICHECK_MONGO_TRANSACTIONS=true` and the transaction probe must pass; OCR must report local engines, placeholder disabled, offline-only enabled, network disabled, and existing model directories.

Add `--write-probes` to create a short-lived upload session, PUT a small PDF to the returned HTTP/HTTPS signed URL, complete the upload, verify document preview/download signed GET URLs can read the object, confirm the OCR task appears, and create/read an export task.
Add `--ocr-object-probe` with `--write-probes` when you want the OCR service to parse the newly uploaded MinIO object and prove the real OCR pipeline can read object storage.
Add `--litellm-management-probes` when you want to verify LiteLLM virtual key creation/deletion, max budget, RPM, and TPM management against PostgreSQL.
Add `--litellm-provider-probes` when you want a quota-consuming production check that calls `default-chat` and `embedding-default` through LiteLLM.
`deployment_report.py` aggregates config validation, API mutation idempotency coverage, frontend route coverage, frontend mutation header coverage, and optional live probes into `report.json` and `report.md` for release evidence.
The contract auditor statically compares `frontend/src/api/aicheck` and `frontend/src/api/login` request paths against FastAPI routes and fails if any required client endpoint is missing. The deployment report also fails if a non-exempt backend mutation lacks direct or delegated idempotency handling, or if a real frontend mutation omits `Idempotency-Key` generation.

## Infrastructure

```bash
cd backend
# backend/.env must provide:
# AICHECK_AGENTDESIGN_HOST_PATH=/absolute/path/to/agentdesign
# AICHECK_OCR_MODELS_HOST_PATH=/absolute/path/to/local/ocr/models
docker compose up --build
```

MongoDB indexes are declared in `libs/db/indexes.py` and applied on startup when `AICHECK_MONGO_URL` is set. If the database is empty, the API seeds the current demo state into the planned collections. Mutating API calls then flush state back to Mongo so restarts preserve business data. Set `AICHECK_MONGO_TRANSACTIONS=true` only when MongoDB is running as a replica set or sharded cluster; the Compose stack starts Mongo as a single-node `rs0` replica set for this.
The index test suite also verifies every persisted collection in `STATE_COLLECTIONS`, `SINGLETON_COLLECTIONS`, and `idempotency_keys` has an explicit index declaration.

Key environment variables:

- `AICHECK_MONGO_URL`, `AICHECK_MONGO_DB`, `AICHECK_MONGO_TRANSACTIONS=true`: business data persistence and transactional cross-collection flushes.
- `AICHECK_REDIS_URL`, `AICHECK_TASK_DISPATCH=celery`: Celery broker/result backend and API task dispatch.
- `AICHECK_MINIO_ENDPOINT`, `AICHECK_MINIO_ACCESS_KEY`, `AICHECK_MINIO_SECRET_KEY`: signed upload/download and export artifacts.
- `AICHECK_OCR_BASE_URL`, `AICHECK_AGENTDESIGN_HOST_PATH`, `AICHECK_AGENTDESIGN_BACKEND`, `AICHECK_OCR_MODELS_HOST_PATH`, `AICHECK_OCR_ALLOW_PLACEHOLDER=false`, `AICHECK_OCR_OFFLINE_ONLY=true`, `AICHECK_OCR_DISABLE_NETWORK=true`: worker-to-OCR calls, host-side reference pipeline, local model artifact mount, and local-only OCR policy. `Dockerfile.ocr` installs the PaddleOCR/PaddleX/PyMuPDF/OpenCV baseline in `requirements-ocr.txt`; model weights are mounted read-only instead of downloaded at runtime.
- `LITELLM_BASE_URL`, `LITELLM_API_KEY`, `OPENAI_API_KEY`: LiteLLM gateway and provider credentials. When production flags are enabled, the worker/API clients require an explicit `LITELLM_API_KEY` and reject the built-in development key. Keep `AICHECK_LITELLM_NO_PROXY` including `127.0.0.1` and `localhost`; LiteLLM's Prisma query-engine uses local HTTP health probes and can fail DB-backed key management if routed through a proxy.
- `AICHECK_JWT_SECRET`, `AICHECK_REQUIRE_AUTH=true`, `AICHECK_ENABLE_DEMO_USERS=false`: production authentication and demo-account controls.
- `scripts/create_roles.py --password-file ... --require-strong-passwords`: initialize persistent role users with strong, non-default passwords; output is redacted by default and existing hashes are preserved unless `--rotate-passwords` is passed.
