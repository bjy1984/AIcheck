# AIcheck Backend

FastAPI backend for the AIcheck frontend contract, with production-like MongoDB, MinIO, Redis/Celery, OCR, and LiteLLM integration paths.

Deployment guide: see [`../DEPLOYMENT.md`](../DEPLOYMENT.md).

## Services

- `api-service`: FastAPI business API. It serves both stripped paths such as `/workbench/projects` and direct `/api/workbench/projects`.
- `worker-service`: Celery worker with Redis queues for OCR, knowledge slicing, embedding, AI recheck, LLM compare, and export packaging.
- `ocr-service`: internal OCR wrapper. It imports the `agentdesign` seal OCR pipeline when available. Production should set `AICHECK_OCR_ALLOW_PLACEHOLDER=false` so missing OCR dependencies produce retryable task failures.
- `litellm-service`: LiteLLM proxy configured by `config/litellm.yaml`; PostgreSQL is only for LiteLLM metadata.
- `mongodb`, `redis`, `minio`: business persistence, task queue, and object storage for documents/previews/exports/OCR artifacts.

## Local Run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

Without `AICHECK_MONGO_URL`, `AICHECK_MINIO_ENDPOINT`, or `AICHECK_TASK_DISPATCH`, the API runs in compatibility mode using seeded in-memory data and mock URLs. This mode is intended for fast frontend contract tests.

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
python scripts/audit_frontend_contract.py
```

The verifier checks API health flags, role login/default paths, JWT protection, read-only project/task endpoints, identity-spoof rejection, action-bypass rejection, read-scope rejection, OCR health, and LiteLLM health/models without creating business data.
The contract auditor statically compares `frontend/src/api/aicheck` and `frontend/src/api/login` request paths against FastAPI routes and fails if any required client endpoint is missing.

## Infrastructure

```bash
cd backend
docker compose up --build
```

MongoDB indexes are declared in `libs/db/indexes.py` and applied on startup when `AICHECK_MONGO_URL` is set. If the database is empty, the API seeds the current demo state into the planned collections. Mutating API calls then flush state back to Mongo so restarts preserve business data. Set `AICHECK_MONGO_TRANSACTIONS=true` only when MongoDB is running as a replica set or sharded cluster; the Compose stack starts Mongo as a single-node `rs0` replica set for this.

Key environment variables:

- `AICHECK_MONGO_URL`, `AICHECK_MONGO_DB`, `AICHECK_MONGO_TRANSACTIONS=true`: business data persistence and transactional cross-collection flushes.
- `AICHECK_REDIS_URL`, `AICHECK_TASK_DISPATCH=celery`: Celery broker/result backend and API task dispatch.
- `AICHECK_MINIO_ENDPOINT`, `AICHECK_MINIO_ACCESS_KEY`, `AICHECK_MINIO_SECRET_KEY`: signed upload/download and export artifacts.
- `AICHECK_OCR_BASE_URL`, `AICHECK_AGENTDESIGN_BACKEND`, `AICHECK_OCR_ALLOW_PLACEHOLDER=false`: worker-to-OCR service calls, pipeline import path, and OCR dependency failure policy.
- `LITELLM_BASE_URL`, `LITELLM_API_KEY`, `OPENAI_API_KEY`: LiteLLM gateway and provider credentials.
- `AICHECK_JWT_SECRET`, `AICHECK_REQUIRE_AUTH=true`, `AICHECK_ENABLE_DEMO_USERS=false`: production authentication and demo-account controls.
