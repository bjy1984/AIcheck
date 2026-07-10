# AIcheck Deployment Acceptance Report

- Generated at: 2026-07-10 07:00:18
- Strict production: True
- Live probes: True
- Overall: FAIL

| Section | Check | Status | Detail |
| --- | --- | --- | --- |
| deployment-config | compose.load | PASS | /Volumes/Volume/project/AIcheck/backend/docker-compose.yml |
| deployment-config | litellm.load | PASS | /Volumes/Volume/project/AIcheck/backend/config/litellm.yaml |
| deployment-config | dockerfile.load | PASS | /Volumes/Volume/project/AIcheck/backend/Dockerfile |
| deployment-config | dockerfile.ocr-load | PASS | /Volumes/Volume/project/AIcheck/backend/Dockerfile.ocr |
| deployment-config | requirements.ocr-load | PASS | /Volumes/Volume/project/AIcheck/backend/requirements-ocr.txt |
| deployment-config | dockerfile.build-contract | PASS | Backend image installs dependencies, runs non-root, and exposes API/OCR ports. |
| deployment-config | requirements.ocr-baseline | PASS | OCR dependency baseline includes PaddleOCR, PaddleX, PyMuPDF, OpenCV, Docling, and Transformers. |
| deployment-config | dockerfile.ocr-build-contract | PASS | OCR image installs PaddleOCR baseline dependencies and runs non-root. |
| deployment-config | compose.services | PASS | Required services are declared. |
| deployment-config | compose.depends-on | PASS | Service dependencies cover database, queue, object storage, OCR, and LiteLLM. |
| deployment-config | compose.commands-ports | PASS | Commands, queues, PostgreSQL service, and public ports are valid. |
| deployment-config | compose.healthchecks | PASS | Core services declare production healthchecks. |
| deployment-config | compose.environment | PASS | Required service environment and production-safe defaults are present. |
| deployment-config | compose.ocr-artifacts | PASS | OCR service requires local model artifacts and mounts OCR artifacts read-only. |
| deployment-config | compose.volumes | PASS | Persistent data volumes are declared. |
| deployment-config | litellm.config | PASS | LiteLLM aliases, provider params, master key, and database settings are valid. |
| auth-contract | auth.role-contract | PASS | roles=6, missingRoles=0, badPaths=0, missingActions=0, ownerWriteLeaks=0, specFailures=0, planFailures=0 |
| data-contract | postgres.index-contract | PASS | tables=4, persistedCollections=89, tableMissing=0, planMissing=0, criticalMissing=0 |
| storage-contract | storage.bucket-contract | PASS | buckets=4, missingBuckets=0, unexpectedBuckets=0, methodFailures=0, repositoryFailures=0, parseFailures=0 |
| ocr-service-contract | ocr.service-contract | PASS | OCR service health, parse endpoint, source resolution, and result envelope are valid. |
| ocr-service-contract | ocr.profile-contract | PASS | profiles=20, businessProfiles=19, failures=0 |
| ocr-service-contract | ocr.evaluation-contract | PASS | OCR release evaluation set and runner are usable. |
| litellm-client-contract | litellm.client-contract | PASS | LiteLLM client and worker usage match OpenAI-compatible gateway contract. |
| knowledge-rule-contract | knowledge-rule.contract | PASS | Knowledge source, rule version, retrieval trace, rule-check, and reference validation contracts are present. |
| review-orchestration-contract | review-orchestration.contract | PASS | Temporal/LangGraph ReviewRun orchestration, routes, state, tools, and replay contracts are present. |
| fde-governance-contract | fde.governance-contract | PASS | FDE high-risk release gates require evaluation, risk set, rollback plan, non-FDE approval, shadow, and canary controls. |
| feedback-hr-contract | feedback.hr-contract | PASS | Human review decisions create immutable AI feedback and FDE triage can promote feedback into evaluation cases. |
| export-artifact-contract | export.artifact-contract | PASS | Export ZIP/PDF artifacts include manifest, audit snapshots, and PDF summary. |
| worker-contract | worker.task-contract | PASS | tasks=7, missingTasks=0, routeMismatches=0, retryMissing=0, dispatcherMissing=0, dispatcherMismatches=0 |
| api-contract | api.response-envelope | PASS | ok()/fail() response envelope matches frontend contract. |
| api-contract | api.mutation-idempotency | PASS | mutatingRoutes=334, missing=0, direct=302, delegated=16, exempt=16 |
| api-contract | api.action-coverage | PASS | mutatingRoutes=334, covered=328, missing=0, exempt=6 |
| frontend-contract | frontend.contract | PASS | frontend=230, backend=656, missing=0 |
| frontend-contract | frontend.mutation-headers | PASS | mutations=122, missing=0, exempt=5 |
| frontend-contract | frontend.mutation-helper | PASS | mutationHeaders carries Idempotency-Key and If-Match. |
| live-deployment | api.health | PASS | API health envelope and runtime flags are present. |
| live-deployment | api.strict-production | FAIL | authRequired expected True, got False; demoUsersEnabled expected False, got True; postgresEnabled expected True, got False; postgresTransactions expected True, got False; objectStorageEnabled expected True, got False |
| live-deployment | auth.gate | SKIP | AICHECK_REQUIRE_AUTH is false. |
| live-deployment | auth.login.admin | PASS | defaultPath=/admin/overview |
| live-deployment | auth.me.admin | PASS |  |
| live-deployment | auth.login.inspection | PASS | defaultPath=/workbench/inspection |
| live-deployment | auth.me.inspection | PASS |  |
| live-deployment | auth.login.contractor | PASS | defaultPath=/workbench/contractor |
| live-deployment | auth.me.contractor | PASS |  |
| live-deployment | auth.login.ndt | PASS | defaultPath=/workbench/ndt |
| live-deployment | auth.me.ndt | PASS |  |
| live-deployment | auth.login.owner | PASS | defaultPath=/workbench/owner |
| live-deployment | auth.me.owner | PASS |  |
| live-deployment | postgres.transaction-probe | FAIL | postgresEnabled must be true; transactionsConfigured must be true; transactionProbe must be pass, got 'skipped' |
| live-deployment | auth.admin-reads | SKIP | Auth is disabled or contractor token is unavailable. |
| live-deployment | api.projects | PASS |  |
| live-deployment | api.knowledge-tasks | PASS |  |
| live-deployment | api.write-probes | SKIP | Write probes disabled; pass --write-probes to verify upload/OCR/export mutations. |
| live-deployment | api.review-run-probe | SKIP | Pass --review-run-probe with --roles including inspection,fde to verify Temporal/LangGraph ReviewRun orchestration. |
| live-deployment | auth.identity-spoof | SKIP | Auth is disabled or contractor token is unavailable. |
| live-deployment | auth.action-bypass | SKIP | Auth is disabled or contractor token is unavailable. |
| live-deployment | auth.read-scope | SKIP | Auth is disabled or contractor token is unavailable. |
| live-deployment | ocr.health | SKIP | OCR check disabled. |
| live-deployment | ocr.readyz | SKIP | OCR check disabled. |
| live-deployment | ocr.runtime-doctor | SKIP | OCR check disabled. |
| live-deployment | ocr.parse-contract | SKIP | OCR check disabled. |
| live-deployment | ocr.bad-request | SKIP | OCR check disabled. |
| live-deployment | litellm.health | SKIP | LiteLLM check disabled. |
| live-deployment | qwen.official-probe | SKIP | Pass --qwen-official-probe to verify the official Qwen API. |

Summary: total=64, pass=48, warn=0, fail=2, skip=14.
