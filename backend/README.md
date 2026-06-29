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
# Required offline OCR subdirectories include:
# paddleocr/PP-OCRv6_medium_det, paddleocr/PP-OCRv6_medium_rec,
# paddlex/PP-DocLayout-L, paddlex/SLANeXt_wired, paddlex/RT-DETR-L_wired_table_cell_det,
# paddlex/SLANeXt_wireless, paddlex/RT-DETR-L_wireless_table_cell_det,
# paddlex/PP-OCRv4_server_seal_det, and paddleocr/PP-OCRv4_server_rec.
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

The verifier checks API health flags, role login/default paths, JWT protection, the MongoDB transaction probe, read-only project/task endpoints, identity-spoof rejection, action-bypass rejection, read-scope rejection, OCR health/readyz, OCR runtime doctor, OCR parse/bad-request contracts, and LiteLLM health/models without creating business data or spending model quota. In `--strict-production`, MongoDB must be connected with `AICHECK_MONGO_TRANSACTIONS=true` and the transaction probe must pass; OCR must report local engines, placeholder disabled, offline-only enabled, network disabled, existing model directories, and no failed runtime doctor checks.

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
- `AICHECK_PADDLEOCR_DET_MODEL_DIR`, `AICHECK_PADDLEOCR_REC_MODEL_DIR`, `AICHECK_PPSTRUCTURE_*_MODEL_DIR`, `AICHECK_SEAL_DET_MODEL_DIR`, `AICHECK_SEAL_REC_MODEL_DIR`: explicit local model folders for text OCR, PP-StructureV3 table/layout, and optional PaddleX seal recognition. Missing PP-Structure folders keep the table engine unavailable instead of downloading at runtime; the piping profile can still infer a basic table from OCR text coordinates.
- `AICHECK_ENABLE_OPENCV_TABLE_GRID=true`, `AICHECK_OPENCV_TABLE_GRID_MAX_CELLS=1800`: enable the local OpenCV table-grid detector. It runs against the `table_line_enhanced` candidate image, uses adaptive/edge/color line masks, and can align OCR text rows to detected grid evidence when PP-StructureV3 is unavailable.
- `AICHECK_OCR_ENABLE_PERSISTENT_SUBPROCESS=true`, `AICHECK_OCR_PERSISTENT_WORKER_TIMEOUT=180`: keep the PaddleOCR subprocess worker alive across requests. If the worker fails or times out, the engine resets it and falls back to one-shot subprocess OCR.
- `AICHECK_OCR_PREPROCESS_CACHE_DIR`, `AICHECK_OCR_DISABLE_VARIANT_CACHE=false`: cache generated preprocess variants by source hash, Profile, and preprocess policy. OCR results expose `imageVariants[].cacheHit`, `preprocessStatus.requestedVariants/generatedVariants/missingVariants`, and `engineRuns[].variantCacheHit` for FDE performance analysis. If OpenCV is missing and no `AICHECK_OCR_SUBPROCESS_PYTHON` is configured, the result keeps the original image only and adds `PREPROCESS_VARIANT_GENERATION_UNAVAILABLE`.
- `AICHECK_OCR_RESULT_CACHE_DIR`, `AICHECK_OCR_DISABLE_RESULT_CACHE=false`: cache successful local parse results by source hash, Profile, model manifest, preprocess policy, and engine options. Cache hits return a fresh `parseResultId` with `resultCacheHit=true` and skip OCR engine execution.
- `AICHECK_OCR_ENGINE_RESULT_CACHE_DIR`, `AICHECK_OCR_DISABLE_ENGINE_RESULT_CACHE=false`: cache individual local engine outputs by source hash, engine version, candidate-image hash, Profile preprocess policy, and model manifest. This cache intentionally ignores Profile `postprocessVersion`, so table/field/quality rule tuning can reuse expensive PaddleOCR or seal OCR outputs while still recomputing fusion and quality gates.
- `LITELLM_BASE_URL`, `LITELLM_API_KEY`, `OPENAI_API_KEY`: LiteLLM gateway and provider credentials. When production flags are enabled, the worker/API clients require an explicit `LITELLM_API_KEY` and reject the built-in development key. Keep `AICHECK_LITELLM_NO_PROXY` including `127.0.0.1` and `localhost`; LiteLLM's Prisma query-engine uses local HTTP health probes and can fail DB-backed key management if routed through a proxy.
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

Each case can embed a `result`, point to a `resultPath`, or provide a local `source` and run with `--run-ocr`.
Relative `resultPath` values, and relative `source` values when `--run-ocr` is enabled, are resolved from the eval
set file's directory so release fixtures can move together without depending on the current shell directory.
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
