# AIcheck Backend

FastAPI backend for the AIcheck frontend contract, with PostgreSQL business persistence, MinIO, Redis/Celery, local OCR, Temporal/LangGraph review orchestration, and LiteLLM integration paths.

Deployment guide: see [`../DEPLOYMENT.md`](../DEPLOYMENT.md).

## Services

- `api-service`: FastAPI business API. It serves both stripped paths such as `/workbench/projects` and direct `/api/workbench/projects`.
- `worker-service`: Celery worker with Redis queues for OCR, knowledge slicing, embedding, AI recheck, LLM compare, and export packaging.
- `review-worker-service`: Temporal worker for `ReviewRunWorkflow`. The outer workflow handles long-running review state, retry/cancel/wait-for-human behavior, and the inner LangGraph-compatible graph records each review step for FDE visualization.
- `ocr-service`: local-only Document Intelligence service built from `Dockerfile.ocr`. It keeps the legacy agentdesign seal OCR import path, adds async document-parse jobs, and requires local model artifacts mounted at `/models`; production should keep `AICHECK_OCR_ALLOW_PLACEHOLDER=false`, `AICHECK_OCR_OFFLINE_ONLY=true`, and `AICHECK_OCR_DISABLE_NETWORK=true`.
- `embedding-service`: local Infinity embedding server. It defaults to `Qwen/Qwen3-Embedding-0.6B`, serves the stable `embedding-default` alias through LiteLLM, keeps model files in `AICHECK_EMBEDDING_CACHE_HOST_PATH`, and can use `HF_ENDPOINT` for first-run model downloads on restricted networks. `BAAI/bge-m3` remains the 1024-dimensional fallback model.
- `litellm-service`: LiteLLM proxy configured by `config/litellm.yaml`; it uses the unified PostgreSQL service for metadata and routes chat aliases to DeepSeek plus embeddings to the local Infinity service.
- `temporal-service`, `temporal-ui`: durable review workflow engine and workflow UI.
- `postgres`, `redis`, `minio`: unified PostgreSQL databases for AIcheck/LiteLLM/workflow, task queue/cache, and object storage for documents/previews/exports/OCR artifacts.
- Docker Compose healthchecks are declared for API, worker, review worker, OCR, PostgreSQL, Redis, MinIO, Temporal, local embedding, and LiteLLM; service dependencies use `condition: service_healthy` for startup ordering.

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

Without `AICHECK_DATABASE_URL`, `AICHECK_MINIO_ENDPOINT`, or `AICHECK_TASK_DISPATCH`, the API runs in compatibility mode using seeded in-memory data and mock URLs. This mode is intended for fast frontend contract tests.
Set `AICHECK_BOOTSTRAP_LOCAL_ROLES=true` to inject the five PBKDF2 role accounts into the in-memory repository for local login checks without PostgreSQL.

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

The contract suite covers the response envelope, compatibility login paths, persistent user login with demo users disabled, mutation idempotency and body-conflict detection, archived/etag guards, submission withdrawal, rectification feedback, report-generation state guards, backend-inferred action-code guards, read/write URL/body/resource-derived node-scope guards, list-level node-scope filtering, upload-to-OCR task creation, OCR HTTP client dispatch, inline OCR field/chunk writeback, retry/cancel behavior for knowledge tasks, Temporal/LangGraph-compatible ReviewRun creation, graph visualization, human decision handling, AI feedback sample creation, FDE feedback triage to evaluation cases, FDE ReviewRun replay/shadow APIs, LiteLLM failure mapping, async LLM compare, object-storage export artifacts, JWT/action/node-scope identity guards, and PostgreSQL state round-trip.

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
# Supported OCR model layouts:
# 1) Bundle: AICHECK_OCR_MODELS_HOST_PATH contains paddleocr/, paddlex/, paddleocr-vl/, and docling/.
# 2) PaddleX official cache: AICHECK_OCR_MODELS_HOST_PATH points at .paddlex-cache/official_models,
#    explicit AICHECK_*_MODEL_DIR values use /models/<model-dir>, and Docling may use
#    DOCLING_ARTIFACTS_PATH=/opt/agentdesign/docling.
# Required offline OCR model directories include:
# paddleocr/PP-OCRv6_medium_det, paddleocr/PP-OCRv6_medium_rec,
# paddlex/PP-DocLayout-L, paddlex/SLANeXt_wired, paddlex/RT-DETR-L_wired_table_cell_det,
# paddlex/SLANeXt_wireless, paddlex/RT-DETR-L_wireless_table_cell_det,
# paddlex/PP-OCRv4_server_seal_det, paddleocr/PP-OCRv4_server_rec,
# paddleocr-vl/PP-DocLayoutV3, and paddleocr-vl/PaddleOCR-VL-1.6-0.9B.
python scripts/check_96_preflight.py --strict-production
docker compose --env-file .env up --build -d
set -a; source .env; set +a
python scripts/deployment_report.py \
  --strict-production \
  --include-live \
  --roles admin,inspection,contractor,ndt,owner,fde \
  --write-probes \
  --ocr-object-probe \
  --review-run-probe \
  --review-run-wait-seconds 20 \
  --litellm-management-probes \
  --litellm-provider-probes \
  --output-dir ./deployment-reports/latest
```

`check_96_preflight.py` fails early when Docker Compose, `backend/.env`, production flags, LiteLLM/provider keys, the `agentdesign` OCR reference path, or local OCR model directories are missing. Text and JSON output include `remediation` steps for each failing check so the deployment host can be corrected before live probes. The ReviewRun probe creates a temporary AI recheck, requires Temporal dispatch in strict production, waits for the worker to advance the LangGraph step graph, verifies ReviewRun business endpoints, submits a human decision, and verifies FDE diagnostic replay. The management probe creates and deletes a temporary LiteLLM virtual key to verify DB-backed key, budget, and rate-limit management. The provider probe spends real LiteLLM upstream quota; omit `--litellm-provider-probes` only for a dry infrastructure check.

The verifier checks API health flags, role login/default paths, JWT protection, the PostgreSQL transaction probe, read-only project/task endpoints, identity-spoof rejection, action-bypass rejection, read-scope rejection, OCR health/readyz, OCR runtime doctor, OCR parse/bad-request contracts, and LiteLLM health/models without creating business data or spending model quota. In `--strict-production`, PostgreSQL must be connected through `AICHECK_DATABASE_URL` and the transaction probe must pass; OCR must report local engines, placeholder disabled, offline-only enabled, network disabled, existing model directories, and no failed runtime doctor checks.

Add `--write-probes` to create a short-lived upload session, PUT a small PDF to the returned HTTP/HTTPS signed URL, complete the upload, verify document preview/download signed GET URLs can read the object, confirm the OCR task appears, and create/read an export task.
Add `--ocr-object-probe` with `--write-probes` when you want the OCR service to parse the newly uploaded MinIO object and prove the real OCR pipeline can read object storage.
Add `--review-run-probe --review-run-wait-seconds 20 --roles admin,inspection,contractor,ndt,owner,fde` when you want the verifier to create a ReviewRun through `/inspection/nodes/24/ai-recheck`, check `/api/review-runs/{id}` detail/graph/timeline, confirm the worker advanced the graph in strict production, submit human confirmation, and verify FDE immutable replay.
Add `--litellm-management-probes` when you want to verify LiteLLM virtual key creation/deletion, max budget, RPM, and TPM management against PostgreSQL.
Add `--litellm-provider-probes` when you want a quota-consuming production check that calls `default-chat` and `embedding-default` through LiteLLM. `default-chat`, `review-chat`, and `compare-fast` route to DeepSeek `deepseek-reasoner`; `embedding-default` routes to the local Infinity served-model alias, which defaults to `Qwen/Qwen3-Embedding-0.6B` and should return 1024-dimensional vectors.
`deployment_report.py` aggregates config validation, API mutation idempotency coverage, knowledge/rule/retrieval validation contracts, Temporal/LangGraph ReviewRun orchestration contracts, FDE release-governance gates, AI HR feedback/evaluation-case contracts, frontend route coverage, frontend mutation header coverage, and optional live probes into `report.json` and `report.md` for release evidence. The knowledge/rule gate checks `knowledge_clauses`, `knowledge_page_index_nodes`, `RetrievalTrace.selectedClauses`, `RetrievalTrace.pageIndexTree`, `queryRouter/selectedRoute/routerSignals`, exact clause lookup, Hybrid RAG, PageIndex conditional routing, and `RuleCheckResult.linkedClauseIds` so AI findings can be traced back to explicit local clauses and the retrieval route that produced them. The FDE governance gate checks high-risk releases for evaluation, risk set, rollback plan, non-FDE approval, shadow, and canary controls. The feedback HR gate checks that human review decisions create immutable `ai_feedback` records, FDE triage can promote approved feedback into `evaluation_cases`, and FDE evaluation runs persist case-level `evaluation_case_results` with finding recall, evidence coverage, retrieval recall, wrong-reference rate, and gate status.
The contract auditor statically compares `frontend/src/api/aicheck` and `frontend/src/api/login` request paths against FastAPI routes and fails if any required client endpoint is missing. The deployment report also fails if a non-exempt backend mutation lacks direct or delegated idempotency handling, or if a real frontend mutation omits `Idempotency-Key` generation.

For a local ReviewRun orchestration 100/100 check, copy `backend/.env.review100.example` to `.env.review100`, replace
the placeholder secrets and provider key, and run the real local workflow stack:

```bash
docker compose --env-file .env.review100 up -d \
  postgres temporal-service redis minio \
  litellm-service api-service review-worker-service

python scripts/review_orchestration_100_probe.py \
  --api-base http://127.0.0.1:8000 \
  --project-id P-2026-HDCP-001 \
  --node-id 24 \
  --wait-seconds 60 \
  --json
```

This probe is stricter than the inline unit tests: it requires `dispatch.mode=temporal`,
`workflowEngine=temporal`, `graphRunner=langgraph`, `graphExecution.checkpointer=postgres`, FDE
`scorecard.score=100`, and a real Temporal human-decision signal. Inline mode remains useful for fast tests, but it is
not the local 100/100 scoring path.

## Infrastructure

```bash
cd backend
# backend/.env must provide:
# AICHECK_AGENTDESIGN_HOST_PATH=/absolute/path/to/agentdesign
# AICHECK_OCR_MODELS_HOST_PATH=/absolute/path/to/local/ocr/models
docker compose up --build
```

PostgreSQL persistence is enabled when `AICHECK_DATABASE_URL` is set. On startup the API creates the first-stage JSONB state tables (`aicheck_state`, `aicheck_singletons`, `idempotency_records`) and seeds the current demo state when the business database is empty. Mutating API calls flush state back to PostgreSQL so restarts preserve business data. The index test suite verifies the JSONB state table, singleton table, idempotency primary key, and GIN payload index contract.

Key environment variables:

- `AICHECK_DATABASE_URL`, `AICHECK_POSTGRES_DB`, `AICHECK_POSTGRES_USER`, `AICHECK_POSTGRES_PASSWORD`: unified PostgreSQL persistence for AIcheck business data, LiteLLM metadata, Temporal, and LangGraph checkpoint databases.
- `AICHECK_REDIS_URL`, `AICHECK_TASK_DISPATCH=celery`: Celery broker/result backend and API task dispatch.
- `AICHECK_REVIEW_ORCHESTRATION=temporal`, `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `AICHECK_REVIEW_*_TASK_QUEUE`, `AICHECK_REVIEW_LLM_EXECUTION=litellm`, `AICHECK_LANGGRAPH_DISABLE=false`, `AICHECK_LANGGRAPH_CHECKPOINT_DISABLE=false`, `AICHECK_LANGGRAPH_CHECKPOINT_SETUP=false`, `LANGGRAPH_CHECKPOINT_DSN`: Temporal/LangGraph review orchestration, LiteLLM-backed finding generation, checkpoint storage, shadow runs, replay, and human decision/cancel signals.
- `AICHECK_MINIO_ENDPOINT`, `AICHECK_MINIO_ACCESS_KEY`, `AICHECK_MINIO_SECRET_KEY`: signed upload/download and export artifacts.
- `AICHECK_OCR_BASE_URL`, `AICHECK_AGENTDESIGN_HOST_PATH`, `AICHECK_AGENTDESIGN_BACKEND`, `AICHECK_OCR_MODELS_HOST_PATH`, `AICHECK_OCR_ALLOW_PLACEHOLDER=false`, `AICHECK_OCR_OFFLINE_ONLY=true`, `AICHECK_OCR_DISABLE_NETWORK=true`: worker-to-OCR calls, host-side reference pipeline, local model artifact mount, and local-only OCR policy. `Dockerfile.ocr` supports two dependency tiers: `requirements-ocr-core.txt` is the default fast deploy tier for PaddleOCR/PaddleX/PyMuPDF/OpenCV, while `requirements-ocr.txt` is the full offline tier that also installs Docling/Transformers/Torch for advanced local document parsing. Set `AICHECK_OCR_REQUIREMENTS=requirements-ocr.txt` only when building the full OCR image intentionally; model weights are mounted read-only instead of downloaded at runtime. `AICHECK_ENABLE_PADDLEOCR_VL` defaults to `false` because VL is a heavy fallback; enable it only for controlled offline evaluation or manually scoped complex-document tests.
- `AICHECK_PADDLEOCR_DET_MODEL_DIR`, `AICHECK_PADDLEOCR_REC_MODEL_DIR`, `AICHECK_PPSTRUCTURE_*_MODEL_DIR`, `AICHECK_SEAL_DET_MODEL_DIR`, `AICHECK_SEAL_REC_MODEL_DIR`: explicit local model folders for text OCR, PP-StructureV3 table/layout, and optional PaddleX seal recognition. Missing PP-Structure folders keep the table engine unavailable instead of downloading at runtime; the piping profile can still infer a basic table from OCR text coordinates.
- `AICHECK_ENABLE_OPENCV_TABLE_GRID=true`, `AICHECK_OPENCV_TABLE_GRID_MAX_CELLS=1800`: enable the local OpenCV table-grid detector. It runs against the `table_line_enhanced` candidate image, uses adaptive/edge/color line masks, and can align OCR text rows to detected grid evidence when PP-StructureV3 is unavailable.
- `AICHECK_OCR_ENABLE_PERSISTENT_SUBPROCESS=true`, `AICHECK_OCR_PERSISTENT_WORKER_TIMEOUT=180`: keep the PaddleOCR subprocess worker alive across requests. If the worker fails or times out, the engine resets it and falls back to one-shot subprocess OCR.
- `AICHECK_OCR_PREPROCESS_CACHE_DIR`, `AICHECK_OCR_DISABLE_VARIANT_CACHE=false`: cache generated preprocess variants by source hash, Profile, and preprocess policy. OCR results expose `imageVariants[].cacheHit`, `preprocessStatus.requestedVariants/generatedVariants/missingVariants`, and `engineRuns[].variantCacheHit` for FDE performance analysis. If OpenCV is missing and no `AICHECK_OCR_SUBPROCESS_PYTHON` is configured, the result keeps the original image only and adds `PREPROCESS_VARIANT_GENERATION_UNAVAILABLE`.
- `AICHECK_OCR_RESULT_CACHE_DIR`, `AICHECK_OCR_DISABLE_RESULT_CACHE=false`: cache successful local parse results by source hash, Profile, model manifest, preprocess policy, and engine options. Cache hits return a fresh `parseResultId` with `resultCacheHit=true` and skip OCR engine execution.
- `AICHECK_OCR_ENGINE_RESULT_CACHE_DIR`, `AICHECK_OCR_DISABLE_ENGINE_RESULT_CACHE=false`: cache individual local engine outputs by source hash, engine version, candidate-image hash, Profile preprocess policy, and model manifest. This cache intentionally ignores Profile `postprocessVersion`, so table/field/quality rule tuning can reuse expensive PaddleOCR or seal OCR outputs while still recomputing fusion and quality gates.
- `LITELLM_BASE_URL`, `LITELLM_API_KEY`, `DEEPSEEK_API_KEY`: LiteLLM gateway and chat provider credentials. `review-chat` uses DeepSeek `deepseek-reasoner`; `embedding-default` is local-only through `embedding-service`. `OPENAI_API_KEY` is optional and only needed if you add OpenAI-backed aliases yourself.
- `INFINITY_API_KEY`, `AICHECK_EMBEDDING_MODEL_ID=Qwen/Qwen3-Embedding-0.6B`, `AICHECK_EMBEDDING_SERVED_MODEL_NAME=embedding-default`, `AICHECK_EMBEDDING_ENGINE=torch`, `AICHECK_EMBEDDING_CACHE_HOST_PATH`, `HF_ENDPOINT`: local embedding-service configuration. First startup downloads the selected model into the cache path; after that, restarts reuse the local cache. `HF_ENDPOINT=https://hf-mirror.com` is useful on China-hosted servers where direct Hugging Face access is unreliable. Qwen3-0.6B and BGE-M3 are both 1024-dimensional in the supported hot-swap path, but switching model families still requires a separate index version and re-embedding.
- When production flags are enabled, the worker/API clients require an explicit `LITELLM_API_KEY` and reject the built-in development key. Keep `AICHECK_LITELLM_NO_PROXY` including `127.0.0.1`, `localhost`, `postgres`, and `embedding-service`; LiteLLM's Prisma query-engine and local provider calls can fail if routed through a proxy.
- `AICHECK_JWT_SECRET`, `AICHECK_REQUIRE_AUTH=true`, `AICHECK_ENABLE_DEMO_USERS=false`: production authentication and demo-account controls.
- `scripts/create_roles.py --password-file ... --require-strong-passwords`: initialize persistent role users with strong, non-default passwords; output is redacted by default and existing hashes are preserved unless `--rotate-passwords` is passed.

Local OCR sample probe:

```bash
cd backend
python scripts/ocr_runtime_doctor.py --json
python scripts/ocr_runtime_doctor.py --strict-production
```

The doctor does not run OCR inference. It checks local packages, `AICHECK_OCR_SUBPROCESS_PYTHON`, model
directories, engine availability, offline policy, and whether preprocess variants can be generated. Use it before
sample probes: if `preprocess.variants`, `engine.paddle_ocr_subprocess`, or `engine.pp_structure_v3` fails, fix the
runtime or mounted model paths before tuning Profile extraction rules. The same payload is available from
`GET /internal/ocr/doctor`; FDE also receives its summarized `runtimeDoctor` in `GET /api/fde/ocr-quality`.
When `AICHECK_AGENTDESIGN_HOST_PATH` points at a local agentdesign checkout, the doctor also reports
`recommendedEnv` for discovered OCR Python environments and cached model directories, for example
`.venv-ocr311/bin/python` and `.paddlex-cache/official_models/PP-OCRv6_medium_det`.
In Docker, keep `AICHECK_OCR_SUBPROCESS_PYTHON=/usr/local/bin/python` so it uses the OCR image dependencies;
only use the host `.venv-ocr311` path for non-container local probes.
For a bare-metal local probe, add `--auto-discover-runtime` to `ocr_sample_probe.py` to apply the doctor's
recommended OCR Python and model paths when the corresponding environment variables are not already set.

Prepare local PaddleX/PaddleOCR model artifacts before enabling runtime offline-only mode:

```bash
python scripts/ocr_prefetch_models.py \
  --python /path/to/ocr-python \
  --cache-home /absolute/path/to/paddlex-cache \
  --ocr-100

# If a large PaddleOCR-VL download was interrupted, move the partial cache aside
# and retry explicitly.
python scripts/ocr_prefetch_models.py \
  --python /path/to/ocr-python \
  --cache-home /absolute/path/to/paddlex-cache \
  --model PaddleOCR-VL-1.6-0.9B \
  --vl-download-method hf-snapshot \
  --timeout-seconds 3600 \
  --download-retries 3 \
  --disable-hf-xet \
  --clean-incomplete

python scripts/ocr_prefetch_models.py \
  --python /path/to/ocr-python \
  --cache-home /absolute/path/to/paddlex-cache \
  --ocr-100 \
  --verify-only
```

The prefetch step is allowed to contact official model sources in a controlled deployment-prep environment. Production
`ocr-service` should then mount the resulting `official_models` directory read-only and run with
`AICHECK_OCR_OFFLINE_ONLY=true` and `AICHECK_OCR_DISABLE_NETWORK=true`.
OCR 100 also requires `docling` and `transformers` in the OCR image, plus a non-empty local `DOCLING_ARTIFACTS_PATH` and
PaddleOCR-VL artifact directories. The prefetch CLI downloads Docling's default offline artifacts when `--ocr-100` is
used, unless `--no-docling` is set. PaddleX may normalize the VL recognition directory to `PaddleOCR-VL-1.6`; both that
name and `PaddleOCR-VL-1.6-0.9B` are accepted, but the directory must contain real `transformers` artifacts such as
`model.safetensors`. Missing `PP-DocLayoutV3` or an incomplete VL recognition directory keeps the VL adapter unavailable
by design.

For OCR 100 certification, generate a real-sample collection plan and reject bootstrap/fixture-derived cases:

```bash
python scripts/ocr_100_ingest_samples.py ../files ../Scan \
  --output ./ocr_eval/reports/ocr_100_real_sample_queue.json \
  --base-dir ..

python scripts/ocr_100_ingest_samples.py ../Scan \
  --manifest ./ocr_eval/scan_sample_manifest.json \
  --output ./ocr_eval/reports/scan_sample_queue.json \
  --base-dir ..

python scripts/ocr_100_annotation_pack.py ./ocr_eval/reports/scan_sample_queue.json \
  --output-dir ./ocr_eval/reports/scan_annotation_pack \
  --source-base-dir .. \
  --render-previews \
  --page-level-tasks

python scripts/ocr_100_annotation_prelabel.py ./ocr_eval/reports/scan_annotation_pack \
  --output ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks.json \
  --source-base-dir .. \
  --run-ocr \
  --auto-discover-runtime \
  --disable-result-cache \
  --save-result-dir ./ocr_eval/reports/scan_ocr_results \
  --limit 5

python scripts/ocr_100_label_studio_export.py ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks.json \
  --output-dir ./ocr_eval/reports/scan_label_studio \
  --preview-base-dir ./ocr_eval/reports/scan_annotation_pack \
  --local-files-root ./ocr_eval/reports/scan_annotation_pack

python scripts/ocr_100_label_studio_import.py ./ocr_eval/reports/scan_label_studio/label_studio_export.json \
  --annotation-tasks ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks.json \
  --output ./ocr_eval/reports/scan_annotation_pack/labeled_tasks.json \
  --report-output ./ocr_eval/reports/scan_label_studio_import_report.json

python scripts/ocr_annotation_readiness.py ./ocr_eval/reports/scan_annotation_pack/labeled_tasks.json \
  --output ./ocr_eval/reports/scan_annotation_readiness.json \
  --markdown-output ./ocr_eval/reports/scan_annotation_readiness.md

python scripts/ocr_100_annotation_export.py ./ocr_eval/reports/scan_annotation_pack/labeled_tasks.json \
  --output ./ocr_eval/reports/scan_labeled_release_set.json \
  --report-output ./ocr_eval/reports/scan_annotation_export_report.json

python scripts/ocr_100_corpus.py ./ocr_eval \
  --report-output ./ocr_eval/reports/ocr_100_corpus_report.json \
  --collection-plan-output ./ocr_eval/reports/ocr_100_collection_plan.json \
  --collection-todo-output ./ocr_eval/reports/ocr_100_collection_todo.csv \
  --require-real-samples
```

Public benchmark datasets can be indexed as foundation-only baselines. They are useful for layout/table regression, but
they never count toward AIcheck OCR 100 production certification:

```bash
python scripts/ocr_public_benchmark.py --list-datasets

python scripts/ocr_public_benchmark.py \
  --dataset doclaynet \
  --dataset-root ./ocr_eval/public_datasets/doclaynet \
  --split val \
  --limit 100 \
  --output ./ocr_eval/public_reports/doclaynet_val_report.json \
  --case-output ./ocr_eval/public_reports/doclaynet_val_cases.json
```

```bash
cd backend
AICHECK_OCR_ALLOWED_LOCAL_DIRS=/tmp \
AICHECK_OCR_SUBPROCESS_PYTHON=/path/to/ocr-python \
AICHECK_PADDLEX_MODEL_CACHE=/absolute/path/to/local/models \
python scripts/ocr_sample_probe.py /tmp/sample.png \
  --profile-id piping_characteristic_list_v1 \
  --min-fragments 300 \
  --min-fields 5 \
  --require-field-code project_name \
  --require-field-code document_title \
  --require-field-code drawing_no \
  --max-missing-required-fields 0 \
  --max-field-conflicts 0 \
  --min-tables 1 \
  --min-formal-tables 1 \
  --min-business-rows 5 \
  --max-missing-required-tables 0 \
  --max-heuristic-tables 0 \
  --min-seals 1 \
  --min-readable-seals 1 \
  --min-fragment-seals 1 \
  --require-seal-type design_license_seal \
  --max-missing-expected-seal-types 0 \
  --require-quality-status auto_usable \
  --disable-result-cache \
  --min-evidence-completeness 1 \
  --max-low-confidence-fields 0 \
  --max-missing-evidence 0 \
  --output /tmp/aicheck-ocr-sample-full.json \
  --summary-output /tmp/aicheck-ocr-sample-summary.json
```

Shortcut for a local host that already has the agentdesign OCR venv/model cache:

```bash
cd backend
AICHECK_OCR_ALLOWED_LOCAL_DIRS=/tmp \
python scripts/ocr_sample_probe.py /tmp/sample.png \
  --auto-discover-runtime \
  --profile-id piping_characteristic_list_v1 \
  --min-fragments 300 \
  --min-fields 5 \
  --require-field-code project_name \
  --require-field-code document_title \
  --max-missing-required-fields 0 \
  --min-tables 1 \
  --min-formal-tables 1 \
  --min-business-rows 5 \
  --max-missing-required-tables 0 \
  --min-seals 1 \
  --min-readable-seals 1 \
  --min-fragment-seals 1 \
  --require-seal-type design_license_seal \
  --max-missing-expected-seal-types 0 \
  --require-quality-status auto_usable
```

Use `--disable-result-cache` while tuning Profile postprocessing, field fusion, or quality gates: it bypasses the
whole-result cache but still lets expensive text/seal/table engine outputs come from `AICHECK_OCR_ENGINE_RESULT_CACHE_DIR`.
Use `--disable-engine-cache` only when validating changed model paths or engine adapter behavior, and
`--run-all-variants` only for deliberate candidate-image comparisons because it increases runtime. Add
`--min-evidence-completeness`, `--max-low-confidence-fields`, and `--max-missing-evidence` to make real samples fail
when OCR has values but lacks field/table/seal evidence. For field-required Profiles, add `--min-fields`,
repeat `--require-field-code` for required business fields, and use `--max-field-conflicts 0` on strict regression
sets so profile extraction conflicts cannot pass silently. Add `--max-missing-required-fields 0` to make the Profile's
own `quality.missingFields` gate fail even when a loose sample command forgot a specific `--require-field-code`.
For seal-required Profiles, add `--min-readable-seals`, `--min-fragment-seals`, `--require-seal-type`, and
`--max-missing-expected-seal-types 0` so visual seal candidates cannot pass without a readable expected seal type or
the expected OCR-fragment fusion. Use `--max-seal-review-required` only for strict seal-specific regression sets where
every detected seal candidate must be resolved. For table-required Profiles, add `--min-formal-tables`,
`--min-business-rows`, `--max-missing-required-tables 0`, and optionally `--max-heuristic-tables` or
`--max-table-review-required` to prevent missing required tables or heuristic table fallback from satisfying a
production sample gate. After one cache-warming run, add
`--min-engine-cache-hit-rate`, `--max-engine-duration-ms`, and `--max-single-engine-duration-ms` to turn the sample
probe into a performance gate. Add `--fail-on-engine-failure` when validating optional enhancement engines such as
agentdesign seal OCR, so a slow timeout is not hidden by a successful fused OCR fallback.
When `source` is a directory, the summary also includes `qualityReasonCounts`, `diagnosticCodeCounts`,
`engineStatusCounts`, `fieldCodeCounts`, `missingRequiredFieldCounts`, `fieldSourceCounts`, `fieldQualityFlagCounts`,
`missingRequiredTableCounts`, `tableSourceCounts`, `tableQualityFlagCounts`, `matchedExpectedSealTypeCounts`,
`missingExpectedSealTypeCounts`, `sealTypeCounts`, `readableSealTypeCounts`, `failedEngineRunCount`,
`slowestEngineRuns`, and `slowestFiles` so FDE can rank the dominant OCR failure causes before opening per-file JSON.
`--output` writes the full parse result for evidence review; use `--summary-output` for a compact CI/FDE gate payload
that keeps counts, quality status, diagnostics, cache hit rate, failed/slow engine runs, `gateFailures/gateFailureCounts`,
missing required-field/table counts, seal readability/fusion counts, expected seal type matches/misses, and slow-file
rankings without dumping all OCR text.

OCR parse results now include non-breaking accuracy metadata: `pageQuality`, `imageVariants`, `preprocessStatus`,
`quality.status`, `quality.reasons`, `profilePostprocessVersion`, `resultCacheHit`, `imageVariants[].cacheHit`, and per-engine `variantId/preprocessChain/purpose/variantCacheHit/engineCacheHit/workerMode`. Existing consumers can keep reading
`fragments/fields/tables/seals/diagnostics`; FDE and release probes can use the new fields to compare preprocess
variants and route low-confidence pages to human review.
FDE `GET /api/fde/ocr-quality` also exposes `fieldLevel` with parse-result field candidates, low-confidence parse
fields, conflict fields, missing-evidence fields, field-code distribution, source distribution, and quality-flag
counts. Its `evidenceLevel` reports average evidence completeness and field/table/seal missing-evidence pools, so
operators can distinguish low confidence from missing traceability.
Its `tableLevel` block separates formal tables, heuristic fallbacks, required-table misses, review-required tables,
business rows, and source/flag breakdowns.
Its `sealLevel` block separates readable seals, `fragment_seal_text` fusion seals, visual candidates that still need
review, expected seal type matches/misses, and source/flag/type breakdowns.
The result cache key includes `profilePostprocessVersion`, so Profile row-mapping or field-extraction upgrades do not
reuse stale cached parse results.
When `preprocessStatus.missingVariants` is non-empty, treat the run as an OCR runtime/dependency issue before tuning
Profile rules. For table + seal documents, the variant router keeps both `table_line_enhanced` and `seal_color_mask`
inside the candidate cap so seal evidence is not lost behind table optimization.
For documents with required seals, visual color candidates alone are intentionally not enough for `auto_usable`. If OCR
fragments inside the visual seal bbox contain readable seal text such as license scope or `TS...` certificate numbers,
the fusion layer marks the seal with `fragment_seal_text` and can satisfy the seal gate without running a slow full-page
seal OCR. If neither fragment seal text nor PaddleX/agentdesign seal OCR is readable, or the readable formal seal type
does not match the Profile's `sealRules.expectedSealTypes`, the quality gate should report `needs_human_review`.
For high-accuracy local seal text OCR, set `AICHECK_ENABLE_AGENTDESIGN_SEAL_OCR=true`. This runs the
agentdesign `seal_ocr.recognize_document` pipeline in `AICHECK_OCR_SUBPROCESS_PYTHON`, returns formal seal fields
such as `organization_name`, `seal_type`, `valid_until`, and keeps visual candidates as fallback. It is intentionally
off by default because the accuracy-first seal pipeline can add roughly a minute on large engineering photos.
For documents with required tables, heuristic table reconstruction is treated as a fallback candidate; until a formal
table engine result is available, the quality gate should report `TABLE_HEURISTIC_REVIEW_REQUIRED`. The local
`opencv_table_grid_subprocess` engine is accepted as formal grid evidence when it detects table lines and the Profile
postprocessor aligns OCR text rows to that grid; such results use `sourceEngine=opencv_grid_text_aligned` and include
`gridEvidence` for FDE review.
Field value conflicts are governed by each Profile's `qualityRules.criticalConflictFields` plus that Profile's
`requiredFields`. Non-critical optional conflicts stay visible on the field as `field_value_conflict` for FDE review,
but they do not block `auto_usable`.
When PP-StructureV3 returns table HTML, the OCR normalizer converts it into `cells`, `rows`, `columns`, and
`normalizedRows`, including basic `rowspan/colspan` handling. This lets formal table-engine output feed the same
field and evidence pipeline as profile-specific table extraction.
For `piping_characteristic_list_v1`, table rows are additionally mapped to `businessRows` with stable keys such as
`pipeNo`, `nominalDiameter`, `mediumName`, `designPressure`, and `weldDetectionMethod`; rules should prefer these
keys over raw OCR header text. Blank pipe-code continuation rows inherit the previous `pipeNo` and include
`isContinuation=true`, so downstream rules can keep branch rows without treating them as separate pipe numbers.

Local OCR release evaluation:

```bash
cd backend
python scripts/ocr_eval_set.py ./ocr_eval/piping_release_set.json \
  --output ./ocr_eval/reports/piping_release_report.json \
  --summary-output ./ocr_eval/reports/piping_release_summary.json \
  --markdown-output ./ocr_eval/reports/piping_release_report.md \
  --min-average-score 0.90
```

Strict OCR 100 readiness is a separate gate. It is expected to fail until the local runtime has all required engines
and the evaluation corpus reaches 100 cases across the required scenarios:

```bash
python scripts/ocr_100_corpus.py ./ocr_eval \
  --output ./ocr_eval/reports/ocr_100_release_set.json \
  --report-output ./ocr_eval/reports/ocr_100_corpus_report.json

python scripts/ocr_100_ingest_samples.py ../files ../Scan \
  --output ./ocr_eval/reports/ocr_100_real_sample_queue.json \
  --base-dir ..

python scripts/ocr_100_ingest_samples.py ../Scan \
  --manifest ./ocr_eval/scan_sample_manifest.json \
  --output ./ocr_eval/reports/scan_sample_queue.json \
  --base-dir ..

python scripts/ocr_100_annotation_pack.py ./ocr_eval/reports/scan_sample_queue.json \
  --output-dir ./ocr_eval/reports/scan_annotation_pack \
  --source-base-dir .. \
  --render-previews

python scripts/ocr_100_annotation_prelabel.py ./ocr_eval/reports/scan_annotation_pack \
  --output ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks.json \
  --source-base-dir .. \
  --run-ocr \
  --auto-discover-runtime \
  --disable-result-cache \
  --save-result-dir ./ocr_eval/reports/scan_ocr_results \
  --limit 5

python scripts/ocr_100_label_studio_export.py ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks.json \
  --output-dir ./ocr_eval/reports/scan_label_studio \
  --preview-base-dir ./ocr_eval/reports/scan_annotation_pack \
  --local-files-root ./ocr_eval/reports/scan_annotation_pack

python scripts/ocr_100_label_studio_import.py ./ocr_eval/reports/scan_label_studio/label_studio_export.json \
  --annotation-tasks ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks.json \
  --output ./ocr_eval/reports/scan_annotation_pack/labeled_tasks.json \
  --report-output ./ocr_eval/reports/scan_label_studio_import_report.json

python scripts/ocr_100_annotation_export.py ./ocr_eval/reports/scan_annotation_pack/labeled_tasks.json \
  --output ./ocr_eval/reports/scan_labeled_release_set.json \
  --report-output ./ocr_eval/reports/scan_annotation_export_report.json

# Optional collection skeleton only. Replace fixtureDerived cases with real labelled samples before certification.
python scripts/ocr_100_corpus.py ./ocr_eval/piping_release_set.json \
  --bootstrap-to-targets \
  --output ./ocr_eval/reports/ocr_100_collection_skeleton.json \
  --report-output ./ocr_eval/reports/ocr_100_collection_skeleton_report.json

python scripts/ocr_eval_set.py ./ocr_eval/piping_release_set.json \
  --auto-discover-runtime \
  --disable-result-cache \
  --strict-100 \
  --summary-output ./ocr_eval/reports/piping_release_100_summary.json

python scripts/ocr_100_scorecard.py \
  --eval-set ./ocr_eval/piping_release_set.json \
  --auto-discover-runtime \
  --sample-summary /tmp/aicheck-ocr-sample-summary.json \
  --output ./ocr_eval/reports/ocr_100_scorecard.json
```

The scorecard is intentionally objective: runtime engines/offline policy count for 25 points, release evaluation
coverage and metrics for 45 points, real sample probes for 20 points, and observability fields for 10 points. Current
small fixtures prove the evaluator and Profile contracts; they do not by themselves certify a 100-point OCR service.
`ocr_100_corpus.py` combines real eval set files and fails duplicate case IDs, missing required scenarios, fewer than
100 cases, target scenario count gaps, and expected field/table/seal items without positive-area bbox or polygon evidence.
Use `--collection-plan-output` for the full JSON plan and `--collection-todo-output` for a CSV task board that lists
each missing case, required annotations, source requirements, and scenario-specific collection hints such as the
required UT report evidence.
`ocr_100_ingest_samples.py` scans local PDFs/images into a `collectionStatus=needs_labeling` queue, auto-excluding
likely standard/specification documents unless `--include-standards` is set. The generated `expected` values are
annotation placeholders only; they must be replaced with real field/table/seal labels and positive-area coordinates
before `--require-real-samples` can pass.
For numerically named scan files, pass `--manifest ./ocr_eval/scan_sample_manifest.json`; the current `Scan/`
inventory yields 30 queue cases across quality certificate, piping table, construction record, qualification,
welding, RT report, seal-text, fragment-seal, evidence, and quality-gate scenarios; UT report samples are still
missing from the local Scan batch.
`ocr_100_annotation_pack.py` turns that queue into annotator-facing `annotation_tasks.json`, CSV, Markdown, and
optional page/image previews. Use `--page-level-tasks` for multi-page PDFs or long scans; each generated page task keeps
`parentTaskId`, `pageNo`, a single `pagePreviewPath`, and a one-page `previewPaths` value so field/table/seal bboxes do
not get mixed across pages. The generated pack is a local work artifact; after labeling, copy the verified labels back
into a release eval set and re-run `ocr_100_corpus.py --require-real-samples`.
`ocr_100_annotation_prelabel.py` can pre-fill machine suggestions into `suggestedExpected` from existing OCR result
JSON files or by running local OCR with `--run-ocr`; use `--auto-discover-runtime` to apply the runtime-doctor OCR
Python/model recommendations, `--disable-result-cache` when refreshing stale failed results, `--save-result-dir` to
persist raw OCR JSON per case, and `--case-id`/`--limit` to batch expensive OCR work. These suggestions are not
exported as human truth until a reviewer copies/edits them into `labeledExpected`.
`ocr_100_label_studio_export.py` converts annotation/prelabel tasks into `label_config.xml` and
`label_studio_tasks.json`. Configure Label Studio local files with the same `--local-files-root`; machine
`suggestedExpected` bbox values become editable prediction regions, and page-level tasks only export predictions whose
`pageNo` matches the current page. This helps reviewers correct table/field/seal coordinates without cross-page noise.
The export is strict by default: tasks without usable preview images make the command fail instead of silently shrinking
the annotation batch. Use `--allow-skipped` only for partial draft batches.
`ocr_100_label_studio_import.py` reads Label Studio's exported human `annotations` back into `labeledExpected`.
It imports a full `label_json` value when reviewers provide one; otherwise it converts corrected rectangle regions
back into pixel bboxes and merges matching `suggestedExpected` metadata. It deliberately ignores `predictions` by
default, so machine prelabels do not become ground truth without a human annotation. The import step is also a strict
certification gate: placeholder labels, zero-area boxes, schema failures, or missing field/table/seal evidence make the
report fail. Failed imports now write `<output>.draft.json` instead of overwriting the official `--output`; use
`--allow-incomplete` only for a draft review artifact.
`ocr_annotation_readiness.py` applies the same schema and evidence checks plus a two-person review gate for
`collectionStatus=ready_for_eval`: labeler and reviewer must both be present and cannot be the same person.
FDE can inspect and operate the same queue through `/api/fde/ocr-annotation/tasks`,
`/readiness`, `/export-label-studio`, `/import-label-studio`, and `/tasks/{taskId}/review`; these APIs use the single
FDE role and never grant business approval permissions.
`ocr_100_annotation_export.py` is the strict handoff from annotation pack to release eval set: it refuses placeholder
labels, zero-area bbox values, and missing field/table/seal evidence. Use `--allow-incomplete` only to write a draft
review artifact; it will still report the unresolved failure count and must not be used for OCR 100 certification.
`--bootstrap-to-targets` creates a 100-case collection skeleton from existing templates and marks generated items with
`bootstrapGenerated=true`; cross-scenario derived items also get `fixtureDerived=true` /
`collectionStatus=needs_real_sample_replacement`. It is useful for sample collection planning, not for production
certification by itself. `ocr_100_scorecard.py` treats any `bootstrapGenerated` or `fixtureDerived` case as a blocker
even when the synthetic metrics are perfect.
The default 100-case target distribution is: piping table 12, quality certificate 10, NDT RT 10, NDT UT 8,
construction record 10, welding record 10, qualification certificate 8, seal text 8, fragment seal 8, evidence 8,
and quality gate 8. The corpus report prints `scenarioTargetGaps` so the next sample collection batch is explicit.

Each case can embed a `result`, point to a `resultPath`, or provide a local `source` and run with `--run-ocr`.
Relative `resultPath` values, and relative `source` values when `--run-ocr` is enabled, are resolved from the eval
set file's directory so release fixtures can move together without depending on the current shell directory.
Use `--auto-discover-runtime` with `--run-ocr` for local OCR evaluation and `--disable-result-cache` when the eval
must refresh stale OCR cache entries.
The evaluator reports field recall, field value accuracy, field/table/seal evidence recall, bbox IoU hit rates for
fields/tables/seals, table recall, seal recall, quality status match, quality reason recall, and optional
`quality.evidenceCompleteness` range matching. Top-level `thresholds` can set overall
metric gates and per-scenario gates such as `piping_table_profile`, `seal_text_profile`, `fragment_seal_profile`, and
`quality_gate_profile`; `fragment_seal_profile` locks the visual-seal-plus-OCR-fragment fusion contract by checking
seal source, quality flags, extracted seal fields, and bbox evidence. `field_confidence_profile` covers
required/critical field low-confidence review gates, and `evidence_profile` covers required field/table/seal bbox or
polygon evidence gates. The CLI summary prints scenario
scores so a strong average cannot hide a weak OCR scene. Full JSON reports include
`findingCounts`, `details.fields/tables/seals/quality`, candidate values, bbox IoU, and mismatch status so FDE can diagnose whether a
failure came from value extraction, missing evidence, or bad coordinates. Use it as the lightweight release gate for
OCR Profile, preprocess policy, model manifest, and PP-Structure/Seal changes before promoting a Capability Bundle.
`--summary-output` writes a compact CI/FDE payload with `ok`, `summary`, `metrics`, `findingCounts`,
`thresholdFailures`, `scenarioMetrics`, and `failedCases`; use the full `--output` or `--markdown-output` when opening
the detailed evidence trail. All report outputs create their parent directories automatically, so a fresh
`ocr_eval/reports` folder is not required before the first run.
The FDE endpoint `POST /api/fde/ocr-evaluation-runs` can also accept explicit `cases` and `thresholds`; its response
keeps the legacy proxy metrics and adds the same compact `evaluationSummary`, plus `evaluationReport`,
`scenarioMetrics`, and `caseDiagnostics` from the shared evaluator.
