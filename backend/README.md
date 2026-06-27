# AIcheck Backend

FastAPI backend for the AIcheck frontend contract, with production-like MongoDB, MinIO, Redis/Celery, OCR, and LiteLLM integration paths.

Deployment guide: see [`../DEPLOYMENT.md`](../DEPLOYMENT.md).

## Services

- `api-service`: FastAPI business API. It serves both stripped paths such as `/workbench/projects` and direct `/api/workbench/projects`.
- `worker-service`: Celery worker with Redis queues for OCR, knowledge slicing, embedding, AI recheck, LLM compare, and export packaging.
- `ocr-service`: internal OCR wrapper. It imports the `agentdesign` seal OCR pipeline when available and falls back to a normalized placeholder result.
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

The contract suite covers the response envelope, compatibility login paths, mutation idempotency, archived/etag guards, upload-to-OCR task creation, inline OCR field/chunk writeback, LiteLLM failure mapping, object-storage export artifacts, optional JWT/action/node-scope guards, and Mongo state round-trip.

## Infrastructure

```bash
cd backend
docker compose up --build
```

MongoDB indexes are declared in `libs/db/indexes.py` and applied on startup when `AICHECK_MONGO_URL` is set. If the database is empty, the API seeds the current demo state into the planned collections. Mutating API calls then flush state back to Mongo so restarts preserve business data.

Key environment variables:

- `AICHECK_MONGO_URL`, `AICHECK_MONGO_DB`: business data persistence.
- `AICHECK_REDIS_URL`, `AICHECK_TASK_DISPATCH=celery`: Celery broker/result backend and API task dispatch.
- `AICHECK_MINIO_ENDPOINT`, `AICHECK_MINIO_ACCESS_KEY`, `AICHECK_MINIO_SECRET_KEY`: signed upload/download and export artifacts.
- `LITELLM_BASE_URL`, `LITELLM_API_KEY`, `OPENAI_API_KEY`: LiteLLM gateway and provider credentials.
- `AICHECK_REQUIRE_AUTH=true`: enforce JWT on non-public routes; disabled by default for existing frontend smoke compatibility.
