# AIcheck Deployment Acceptance Report

- Generated at: 2026-07-10 06:50:02
- Strict production: True
- Live probes: False
- Overall: PASS

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
| live-deployment | live.probes | SKIP | Pass --include-live to run target API/OCR/LiteLLM probes. |

Summary: total=36, pass=35, warn=0, fail=0, skip=1.
